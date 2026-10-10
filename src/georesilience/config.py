from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputConfig(StrictModel):
    source: Literal["graphml"] = "graphml"
    path: Path


class AnalysisConfig(StrictModel):
    seed: int = 42
    n_jobs: int | Literal["auto"] = "auto"
    max_memory_gb: float | Literal["auto"] = "auto"
    directed_centrality: bool = False
    directed_removal: bool = True


class OutputConfig(StrictModel):
    dir: Path = Path("results")
    figures: bool = True


class RunConfig(StrictModel):
    input: InputConfig
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


def load_config(path: Path) -> RunConfig:
    try:
        raw = yaml.safe_load(path.read_text())
        if not isinstance(raw, dict):
            raise ValueError("configuration must be a YAML mapping")
        return RunConfig.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
        )
        raise ValueError(details) from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML: {exc}") from exc
