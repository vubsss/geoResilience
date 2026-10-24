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
    accessibility: AccessibilityConfig = Field(default_factory=AccessibilityConfig)
    population: PopulationConfig = Field(default_factory=PopulationConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
