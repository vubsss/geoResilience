"""Strict, road-independent acquisition configuration for Ticket 17."""
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pyproj import CRS
from pyproj.exceptions import CRSError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Service = Literal["school", "hospital", "fire_station"]
FIELDS = {"source_id", "official_id", "name", "address", "status", "service_level", "management",
          "subtype", "reference_year", "supply_value", "supply_unit", "enrolment", "teachers", "classrooms"}


class FacilitySource(StrictModel):
    name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    kind: Literal["official", "osm"]
    format: Literal["csv", "gpkg", "osm_xml", "osm_bbox"]
    path: Path | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    layer: str | None = None
    service: Service | None = None
    columns: dict[str, str] = Field(default_factory=dict)
    x: str | None = None
    y: str | None = None
    crs: str | None = None
    id_namespace: str | None = None
    status_map: dict[str, Literal["active", "inactive", "unknown"]] = Field(default_factory=dict)
    default_status: Literal["active", "inactive", "unknown"] = "unknown"
    capacity_unit: str | None = None
    reference_year: str | None = None
    retrieved_at: str = Field(min_length=1)
    url: str = Field(min_length=1)
    licence: str = Field(min_length=1)
    bbox: tuple[float, float, float, float] | None = None
    cache_dir: Path = Path("cache/facilities")
    endpoint: str = "https://overpass-api.de/api/interpreter"

    @model_validator(mode="after")
    def validate_source(self):
        if set(self.columns) - FIELDS:
            raise ValueError(f"unknown facility columns: {sorted(set(self.columns) - FIELDS)}")
        if self.format != "osm_bbox" and self.path is None:
            raise ValueError("local facility sources require path")
        if self.format in {"osm_xml", "osm_bbox"} and self.kind != "osm":
            raise ValueError("OSM extraction requires kind: osm")
        if self.format in {"csv", "gpkg"}:
            if not self.service or "source_id" not in self.columns:
                raise ValueError("CSV/GPKG sources require service and columns.source_id")
            if self.format == "csv" and not (self.x and self.y and self.crs):
                raise ValueError("CSV sources require explicit x, y and crs")
            if self.format == "gpkg" and not self.layer:
                raise ValueError("GeoPackage sources require an explicit layer")
        if self.kind == "osm" and self.format == "csv":
            raise ValueError("offline OSM requires XML or a mapped GeoPackage")
        if self.crs:
            try:
                CRS.from_user_input(self.crs)
            except CRSError as exc:
                raise ValueError(f"invalid source CRS: {self.crs}") from exc
        if self.format == "osm_bbox" and not self.bbox:
            raise ValueError("osm_bbox requires bbox")
        if self.bbox:
            w, s, e, n = self.bbox
            if not (-180 <= w < e <= 180 and -90 < s < n < 90):
                raise ValueError("facility bbox must be WGS84 [west, south, east, north]")
        if self.capacity_unit and self.capacity_unit.strip().lower() in {"enrolment", "enrollment", "teachers", "classrooms"}:
            raise ValueError("enrolment and resource fields are not capacity")
        if "supply_value" in self.columns and any(
            self.columns["supply_value"] == self.columns.get(key) for key in ("enrolment", "teachers", "classrooms")
        ):
            raise ValueError("a resource/enrolment column cannot also be supply_value")
        return self


class FacilitySupply(StrictModel):
    mode: Literal["equal", "capacity"] = "equal"
    unit: str = "facilities"
    missing: Literal["error", "exclude", "keep_missing"] = "error"

    @model_validator(mode="after")
    def validate_unit(self):
        if self.mode == "equal" and self.unit != "facilities":
            raise ValueError("equal supply uses unit: facilities")
        if self.mode == "capacity" and (not self.unit.strip() or self.unit.strip().lower() in {
            "facilities", "enrolment", "enrollment", "teachers", "classrooms"
        }):
            raise ValueError("capacity needs a documented capacity unit, not enrolment/resources")
        return self


class FacilityConfig(StrictModel):
    sources: list[FacilitySource] = Field(min_length=1)
    supply: dict[Service, FacilitySupply]
    output_dir: Path = Path("results/facilities")
    metric_crs: str
    match_max_m: float = Field(default=100, ge=0, allow_inf_nan=False)
    overrides: Path | None = None
    override_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    include_osm_candidates: bool = False
    include_unknown_status: bool = True
    offline: bool = True
    figures: bool = True

    @model_validator(mode="after")
    def validate_registry(self):
        if len({s.name for s in self.sources}) != len(self.sources):
            raise ValueError("facility source names must be unique")
        try:
            crs = CRS.from_user_input(self.metric_crs)
        except CRSError as exc:
            raise ValueError(f"invalid metric CRS: {self.metric_crs}") from exc
        if not crs.is_projected or not crs.axis_info or any(a.unit_conversion_factor != 1 for a in crs.axis_info):
            raise ValueError("facilities.metric_crs must be projected in metres")
        if not self.supply:
            raise ValueError("declare supply convention for every imported service")
        return self


def load_facility_config(path: Path) -> FacilityConfig:
    try:
        raw = yaml.safe_load(path.read_text())
        return FacilityConfig.model_validate(raw)
    except (ValidationError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid facility configuration: {exc}") from exc
