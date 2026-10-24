"""Deterministic discovery of local input files."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InputFiles:
    directory: Path
    road: Path
    population: Path
    boundary: Path | None

    @property
    def source(self):
        return "graphml" if self.road.suffix.lower() == ".graphml" else "osm_xml"


def resolve_inputs(directory, boundary=None):
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"input directory does not exist: {directory}")
    files = sorted((path for path in directory.iterdir() if path.is_file()), key=lambda p: p.name)
    pbf = [path.name for path in files if path.name.lower().endswith(".osm.pbf")]
    if pbf:
        raise ValueError("unsupported .osm.pbf input: " + ", ".join(pbf) + "; supply .osm XML or .graphml")

    def exactly_one(label, candidates):
        if len(candidates) != 1:
            names = ", ".join(path.name for path in candidates) or "none"
            raise ValueError(f"expected exactly one {label}; candidates: {names}")
        return candidates[0]

    road = exactly_one("road file (.osm, .osm.xml, .graphml)", [
        path for path in files if path.name.lower().endswith((".osm", ".osm.xml", ".graphml"))])
    population = exactly_one("population GeoTIFF (.tif, .tiff)", [
        path for path in files if path.suffix.lower() in {".tif", ".tiff"}])
    if boundary is not None:
        boundary = Path(boundary).expanduser().resolve()
        if not boundary.is_file() or boundary.suffix.lower() not in {".geojson", ".gpkg"}:
            raise ValueError(f"boundary must be an existing .geojson or .gpkg: {boundary}")
    else:
        candidates = [path for path in files if path.name.lower() in {"boundary.geojson", "boundary.gpkg"}]
        if len(candidates) > 1:
            raise ValueError("ambiguous boundary files: " + ", ".join(p.name for p in candidates))
        boundary = candidates[0] if candidates else None
    return InputFiles(directory, road, population, boundary)


def directory_config(directory, *, boundary=None, network_type="drive", consolidation_m=15,
                     consolidate=True, snap_max_m=500):
    from .config import RunConfig
    files = resolve_inputs(directory, boundary)
    if files.source == "osm_xml" and network_type not in {"drive", "all"}:
        raise ValueError("local XML supports network-type drive or all (as supplied)")
    return RunConfig(input={"source": files.source, "path": files.road,
                           "directory": files.directory, "boundary": files.boundary},
        network={"type": network_type}, cleaning={"consolidate": consolidate, "tolerance_m": consolidation_m},
        population={"worldpop": str(files.population), "snap_max_m": snap_max_m})
