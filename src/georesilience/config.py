from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputConfig(StrictModel):
    source: Literal["place", "polygon", "bbox", "osm_xml", "graphml"] = "graphml"
    path: Path | None = None
    place: str | None = None
    bbox: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def validate_source(self):
        if self.source in {"polygon", "osm_xml", "graphml"} and self.path is None:
            raise ValueError(f"input.path is required for source: {self.source}")
        if self.source == "place" and not (self.place and self.place.strip()):
            raise ValueError("input.place is required for source: place")
        if self.source == "bbox":
            if self.bbox is None:
                raise ValueError("input.bbox is required for source: bbox")
            west, south, east, north = self.bbox
            if not (-180 <= west < east <= 180 and -90 < south < north < 90):
                raise ValueError("input.bbox must be [west, south, east, north] in WGS84")
        return self


class NetworkConfig(StrictModel):
    type: Literal["all", "all_public", "bike", "drive", "drive_service", "walk"] = "drive"
    custom_filter: str | None = None


class CleaningConfig(StrictModel):
    consolidate: bool = True
    tolerance_m: float = Field(default=15, gt=0, allow_inf_nan=False)


class AnalysisConfig(StrictModel):
    seed: int = Field(default=42, ge=0)
    n_jobs: Annotated[int, Field(ge=1)] | Literal["auto"] = "auto"
    max_memory_gb: Annotated[float, Field(gt=0, allow_inf_nan=False)] | Literal["auto"] = "auto"
    directed_centrality: bool = False
    directed_removal: bool = True


class OutputConfig(StrictModel):
    dir: Path = Path("results")
    figures: bool = True


class CriticalityConfig(StrictModel):
    k_betweenness: int = Field(default=250, ge=0)
    k_detour: int = Field(default=250, ge=0)
    k_nodes: int = Field(default=300, ge=0)
    exact_info_max_nodes: int = Field(default=5000, ge=0)
    bridge_analytic_max_side: int = Field(default=2000, ge=0)
    all: bool = False


class RobustnessConfig(StrictModel):
    removal: list[Literal["links", "nodes"]] = Field(default_factory=lambda: ["links", "nodes"])
    steps: int = Field(default=50, ge=1)
    f_max: float = Field(default=0.20, gt=0, le=1, allow_inf_nan=False)
    adaptive: bool = True
    node_attack_metric: Literal["betweenness", "degree"] = "betweenness"
    failure_runs: int = Field(default=10, ge=1)
    efficiency_sources: int = Field(default=500, ge=1)

    @model_validator(mode="after")
    def validate_removal(self):
        if not self.removal or len(set(self.removal)) != len(self.removal):
            raise ValueError("robustness.removal must contain links, nodes, or both without duplicates")
        return self


class ReliabilityConfig(StrictModel):
    p_fail_csv: Path | None = None
    p0: float = Field(default=0.01, ge=0, le=1, allow_inf_nan=False)
    p0_sweep: list[Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]] = Field(
        default_factory=lambda: [0.001, 0.01, 0.05])
    samples: int = Field(default=10000, ge=2)
    od_pairs_csv: Path | None = None
    min_down_count: int = Field(default=30, ge=2)
    min_up_count: int = Field(default=30, ge=2)

    @model_validator(mode="after")
    def include_primary(self):
        self.p0_sweep = sorted(set([*self.p0_sweep, self.p0]))
        return self


class RunConfig(StrictModel):
    input: InputConfig
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    cleaning: CleaningConfig = Field(default_factory=CleaningConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    criticality: CriticalityConfig = Field(default_factory=CriticalityConfig)
    robustness: RobustnessConfig = Field(default_factory=RobustnessConfig)
    reliability: ReliabilityConfig = Field(default_factory=ReliabilityConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


def load_config(path: Path) -> RunConfig:
    try:
        raw = yaml.safe_load(path.read_text())
        if not isinstance(raw, dict):
            raise ValueError("configuration must be a YAML mapping")
        # Output-only metadata must not prevent rerunning a resolved config.
        raw.pop("versions", None)
        return RunConfig.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
        )
        raise ValueError(details) from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML: {exc}") from exc
