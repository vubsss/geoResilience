"""Strict, independently usable configuration for cleaned-road enrichment."""

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..config import StrictModel


class RainfallConfig(StrictModel):
    stations: Path | None = None
    station_crs: str = "EPSG:4326"
    series: Path | None = None
    raster: Path | None = None
    netcdf: Path | None = None
    netcdf_variable: str = "rain_mm"
    average_value: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    average_units: Literal["mm", "mm/hour", "mm/day", "mm/month", "mm/year"] = "mm"
    climatology_event_total_mm: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    duration_hours: float = Field(default=6, gt=0, le=744, allow_inf_nan=False)
    interval_minutes: int = Field(default=60, ge=1, le=1440)
    assumed_total_mm: float = Field(default=100, ge=0, allow_inf_nan=False)
    support_distance_m: float = Field(default=10000, gt=0, allow_inf_nan=False)
    extrapolation_distance_m: float = Field(default=2000, ge=0, allow_inf_nan=False)
    allow_kriging: bool = True

    @model_validator(mode="after")
    def coherent(self):
        if (
            sum(
                p is not None
                for p in (self.stations, self.series, self.raster, self.netcdf)
            )
            > 1
        ):
            raise ValueError(
                "choose one event rainfall source: stations, series, raster, or netcdf"
            )
        if (
            self.average_value is not None
            and self.average_units in ("mm/month", "mm/year")
            and self.climatology_event_total_mm is None
        ):
            raise ValueError(
                "monthly/annual rainfall requires explicit climatology_event_total_mm"
            )
        return self


class SimulationConfig(StrictModel):
    executable: Path | None = None
    docker_image: str = "deltares/sfincs-cpu@sha256:4301bffc74f3cb3f334be5d21aa75dfe5742a16c9838942cdfc2f870859fb404"
    resolution_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    curve_number: float = Field(default=85, gt=0, le=100, allow_inf_nan=False)
    manning: float = Field(default=0.04, gt=0, le=0.5, allow_inf_nan=False)
    recession_hours: float = Field(default=6, ge=0, allow_inf_nan=False)
    initial_level_m: float | None = Field(default=None, allow_inf_nan=False)
    boundary: Literal["outflow", "closed"] = "outflow"
    max_cells: int = Field(default=4_000_000, ge=9)
    max_forcing_values: int = Field(default=100_000_000, ge=1)
    timeout_seconds: int = Field(default=7200, ge=1)
    threads: int = Field(default=1, ge=1)
    wetting_depth_m: float = Field(default=0.001, gt=0, le=0.01, allow_inf_nan=False)
    # Optional native SFINCS structures/boundaries use the same projected grid and vertical datum.
    native_files: dict[str, Path] = Field(default_factory=dict)

    @model_validator(mode="after")
    def native_keys(self):
        allowed = {
            "bndfile",
            "bzsfile",
            "srcfile",
            "disfile",
            "drnfile",
            "thdfile",
            "weirfile",
        }
        if self.native_files.keys() - allowed:
            raise ValueError("unsupported native SFINCS file keyword")
        for left, right in (("bndfile", "bzsfile"), ("srcfile", "disfile")):
            if (left in self.native_files) != (right in self.native_files):
                raise ValueError(f"{left} and {right} must be supplied together")
        return self


class SensitivityConfig(StrictModel):
    enabled: bool = False
    rainfall_multipliers: list[float] = Field(default_factory=lambda: [0.8, 1.2])
    assumed_curve_numbers: list[float] = Field(default_factory=lambda: [70, 95])
    thresholds_m: list[float] = Field(default_factory=lambda: [0.2, 0.5])
    uniform_probabilities: list[float] = Field(default_factory=lambda: [0.001, 0.05])

    @model_validator(mode="after")
    def ranges(self):
        import math

        for values, lo, hi in (
            (self.rainfall_multipliers, 0, 10),
            (self.assumed_curve_numbers, 0, 100),
            (self.thresholds_m, 0, 10),
            (self.uniform_probabilities, -1e-20, 1),
        ):
            if any(not math.isfinite(x) or not lo < x <= hi for x in values):
                raise ValueError("invalid sensitivity parameter")
        return self


class ClosureConfig(StrictModel):
    roads: Path
    out: Path
    layer: str = "edges"
    scenario_id: str = "primary"
    dem: Path | None = None
    depth: Path | None = None
    depth_reference: Literal["ground", "road", "water_surface"] = "ground"
    # Explicit wet-area/barrier partitions: positive integer IDs, one connected water body per ID.
    flood_zones: Path | None = None
    domain: Path | None = None
    landcover: Path | None = None
    soil_groups: Path | None = None
    curve_number_map: Path | None = None
    roughness_map: Path | None = None
    road_elevation_attribute: str | None = None
    uniform_probability: float = Field(default=0.01, ge=0, le=1, allow_inf_nan=False)
    threshold_m: float = Field(default=0.30, gt=0, allow_inf_nan=False)
    dispersion: float = Field(default=0.35, gt=0, allow_inf_nan=False)
    use_existing_probabilities: bool = False
    failure_template: Path | None = None
    overwrite: bool = False
    rainfall: RainfallConfig = Field(default_factory=RainfallConfig)
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    sensitivity: SensitivityConfig = Field(default_factory=SensitivityConfig)

    @model_validator(mode="after")
    def coherent(self):
        if not self.layer.strip() or not self.scenario_id.strip():
            raise ValueError("layer and scenario_id must be nonempty")
        if self.depth_reference == "water_surface" and self.depth is None:
            raise ValueError(
                "water_surface reference requires a supplied depth/water-level raster"
            )
        if (
            self.depth_reference == "water_surface"
            and self.road_elevation_attribute is None
            and self.dem is None
        ):
            raise ValueError("water_surface requires road elevations or a DEM")
        if self.flood_zones is not None and self.depth is None:
            raise ValueError(
                "flood_zones is only used to reconstruct a supplied flood raster"
            )
        return self

    def input_paths(self):
        result = {
            k: v
            for k, v in self.model_dump().items()
            if isinstance(v, Path) and k != "out"
        }
        for key in ("stations", "series", "raster", "netcdf"):
            if (path := getattr(self.rainfall, key)) is not None:
                result["rainfall." + key] = path
        result.update(
            {"simulation." + k: v for k, v in self.simulation.native_files.items()}
        )
        if self.simulation.executable:
            result["simulation.executable"] = self.simulation.executable
        return result


def load_config(path, **overrides):
    """JSON paths are relative to the configuration file; CLI paths remain relative to cwd."""
    import json

    path = Path(path).expanduser().resolve() if path else None
    values = json.loads(path.read_text()) if path else {}
    if not isinstance(values, dict):
        # External JSON validation follows the CLI's ValueError contract.
        raise ValueError("closure configuration must be a JSON object")  # noqa: TRY004
    if path:
        base = path.parent
        for key in (
            "roads",
            "out",
            "dem",
            "depth",
            "flood_zones",
            "domain",
            "landcover",
            "soil_groups",
            "curve_number_map",
            "roughness_map",
            "failure_template",
        ):
            if values.get(key) is not None:
                values[key] = base / Path(values[key]).expanduser()
        for key in ("stations", "series", "raster", "netcdf"):
            if values.get("rainfall", {}).get(key) is not None:
                values["rainfall"][key] = (
                    base / Path(values["rainfall"][key]).expanduser()
                )
        sim = values.get("simulation", {})
        if sim.get("executable"):
            sim["executable"] = base / Path(sim["executable"]).expanduser()
        for key, value in sim.get("native_files", {}).items():
            sim["native_files"][key] = base / Path(value).expanduser()
    values.update({key: value for key, value in overrides.items() if value is not None})
    return ClosureConfig.model_validate(values)
