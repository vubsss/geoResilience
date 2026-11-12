"""Validated settings for the local-directory CLI and Python API."""

from pathlib import Path
from typing import Annotated, Literal
import math

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputConfig(StrictModel):
    source: Literal["osm_xml", "graphml"] = "graphml"
    path: Path
    directory: Path | None = None
    boundary: Path | None = None


class NetworkConfig(StrictModel):
    type: Literal["drive", "all"] = "drive"


class CleaningConfig(StrictModel):
    consolidate: bool = True
    tolerance_m: float = Field(default=15, gt=0, allow_inf_nan=False)


class AnalysisConfig(StrictModel):
    seed: int = Field(default=42, ge=0)
    n_jobs: Annotated[int, Field(ge=1)] | Literal["auto"] = "auto"
    max_memory_gb: Annotated[float, Field(gt=0, allow_inf_nan=False)] | Literal["auto"] = "auto"


class OutputConfig(StrictModel):
    dir: Path = Path("results")
    figures: bool = True


class CriticalityConfig(StrictModel):
    coverage: Literal["screened", "all"] = "screened"
    link_candidates: int = Field(default=250, ge=0)
    node_candidates: int = Field(default=300, ge=0)


class RobustnessConfig(StrictModel):
    fraction: float = Field(default=.20, gt=0, le=1, allow_inf_nan=False)
    steps: int = Field(default=50, ge=1)
    order: Literal["adaptive", "static"] = "adaptive"


class ReliabilityConfig(StrictModel):
    p_fail_csv: Path | None = None
    require_complete_failures: bool = False
    p0: float = Field(default=.01, ge=0, le=1, allow_inf_nan=False)
    p0_sweep: dict[str, Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]] = Field(default_factory=dict)
    samples: int = Field(default=10000, ge=2)
    od_pairs_csv: Path | None = None

    @model_validator(mode="after")
    def validate_scenarios(self):
        if any(not key.strip() or key == "primary" for key in self.p0_sweep):
            raise ValueError("p0 scenario names must be nonempty and cannot be primary")
        return self


class TravelTimeConfig(StrictModel):
    enabled: bool = True  # API-only switch
    samples: int = Field(default=1000, ge=2)
    tau: float = Field(default=.5, ge=0, allow_inf_nan=False)
    highway_speeds_kph: dict[str, Annotated[float, Field(gt=0, allow_inf_nan=False)]] | None = None
    time_model: Literal["free_flow", "edge_attribute", "custom"] = "free_flow"
    time_attribute: str = "travel_time_s"

    @model_validator(mode="after")
    def validate_model(self):
        if self.highway_speeds_kph is not None and (not self.highway_speeds_kph or
                any(not key.strip() for key in self.highway_speeds_kph)):
            raise ValueError("speed table must contain nonempty highway classes")
        if not self.time_attribute.strip():
            raise ValueError("time_attribute must be nonempty")
        return self


class TrafficConfig(StrictModel):
    enabled: bool = False
    source: Literal["assignment", "edge_times_csv"] = "assignment"
    period: str = "illustrative_one_hour"
    duration_h: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    demand_source: Literal["od_csv", "gravity", "population"] = "od_csv"
    od_csv: Path | None = None
    zone_mass_csv: Path | None = None
    total_demand_pcu_h: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    gravity_lambda_per_min: float | None = Field(default=0.08, gt=0, allow_inf_nan=False)
    population_trip_rate_per_person_h: float = Field(default=0.1, gt=0, allow_inf_nan=False)
    population_zone_limit: int = Field(default=100, ge=2)
    road_capacity_pcu_h_per_lane: float = Field(default=1000, gt=0, allow_inf_nan=False)
    default_lanes_per_direction: float = Field(default=1, gt=0, allow_inf_nan=False)
    lane_width_m: float = Field(default=3.5, gt=0, allow_inf_nan=False)
    edge_times_csv: Path | None = None
    capacity_csv: Path | None = None
    capacity_pcu_h: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    vdf: Literal["bpr", "conical"] = "bpr"
    alpha: float = Field(default=0.15, gt=0, allow_inf_nan=False)
    beta: float = Field(default=4.0, gt=0, allow_inf_nan=False)
    relative_gap: float = Field(default=1e-4, gt=0, allow_inf_nan=False)
    max_iterations: int = Field(default=200, ge=1)
    closure_top_n: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_inputs(self):
        if not self.enabled:
            return self
        if not self.period.strip():
            raise ValueError("traffic.period must be nonempty")
        if self.source == "assignment":
            if self.demand_source == "od_csv" and self.od_csv is None:
                raise ValueError("traffic assignment needs od_csv")
            if self.demand_source == "od_csv" and self.zone_mass_csv is not None:
                raise ValueError("traffic demand must use either od_csv or zone_mass_csv, not both")
            if self.demand_source == "gravity" and (self.zone_mass_csv is None or
                                                    self.total_demand_pcu_h is None or
                                                    self.gravity_lambda_per_min is None):
                raise ValueError("traffic gravity demand needs zone_mass_csv, total_demand_pcu_h and gravity_lambda_per_min")
            if self.demand_source == "population" and self.gravity_lambda_per_min is None:
                raise ValueError("traffic population demand needs gravity_lambda_per_min")
            if self.demand_source == "population" and self.total_demand_pcu_h is not None:
                raise ValueError("traffic population demand uses population_trip_rate_per_person_h, not total_demand_pcu_h")
            if self.demand_source == "gravity" and self.od_csv is not None:
                raise ValueError("traffic demand must use either od_csv or zone_mass_csv, not both")
            if self.vdf == "conical" and abs(1 + math.hypot(self.alpha, self.beta) -
                                              self.alpha - self.beta) > .01:
                raise ValueError("traffic conical alpha/beta must give approximately free-flow time at zero volume")
        else:
            if self.edge_times_csv is None:
                raise ValueError("traffic.edge_times_csv is required for supplied edge times")
            if self.closure_top_n:
                raise ValueError("traffic.closure_top_n requires assignment demand and a VDF")
        return self


class AccessibilityConfig(StrictModel):
    half_distance_km: float = Field(default=2, gt=0, allow_inf_nan=False)
    cutoff_factor: float = Field(default=5, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_distances(self):
        half_m = self.half_distance_km * 1000
        if not math.isfinite(half_m) or half_m <= 0:
            raise ValueError("Hansen half-distance in metres must be finite and positive")
        if not all(math.isfinite(value) and value > 0 for value in (math.log(2) / half_m, half_m * self.cutoff_factor)):
            raise ValueError("Hansen decay and cutoff must be finite and positive")
        return self


class PopulationConfig(StrictModel):
    worldpop: str | None = None
    snap_max_m: float = Field(default=500, ge=0, allow_inf_nan=False)


class RunConfig(StrictModel):
    input: InputConfig
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    cleaning: CleaningConfig = Field(default_factory=CleaningConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    criticality: CriticalityConfig = Field(default_factory=CriticalityConfig)
    robustness: RobustnessConfig = Field(default_factory=RobustnessConfig)
    reliability: ReliabilityConfig = Field(default_factory=ReliabilityConfig)
    travel_time: TravelTimeConfig = Field(default_factory=TravelTimeConfig)
    traffic: TrafficConfig = Field(default_factory=TrafficConfig)
    accessibility: AccessibilityConfig = Field(default_factory=AccessibilityConfig)
    population: PopulationConfig = Field(default_factory=PopulationConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
