"""WorldPop count rasters, reproducible acquisition and cell-centre allocation."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.mask import mask
import requests
from scipy.spatial import cKDTree
from shapely.geometry import mapping
from shapely.ops import transform
from shapely import get_coordinates

from .connectivity import node_id_key
from .progress import StageProgress

# Verified 2026-10-12 at https://hub.worldpop.org/rest/data/pop and with ?iso3=MDV.
# This is the original constrained 2020 count series, not the UN-adjusted or G2 series.
WORLDPOP_ALIAS = "cic2020_100m"
CATALOGUE_URL = f"https://hub.worldpop.org/rest/data/pop/{WORLDPOP_ALIAS}"


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_catalogue(payload, year, iso3):
    entries = payload.get("data")
    if not isinstance(entries, list):
        raise ValueError("WorldPop catalogue: expected a data list")
    entries = [row for row in entries if row.get("iso3", iso3).upper() == iso3]
    years = sorted({int(row["popyear"]) for row in entries if str(row.get("popyear", "")).isdigit()})
    selected = [row for row in entries if str(row.get("popyear")) == str(year)]
    if not selected:
        raise ValueError(f"WorldPop year {year} unavailable for {iso3}; available years: "
                         + (", ".join(map(str, years)) or "none"))
    if len(selected) != 1:
        raise ValueError(f"WorldPop catalogue: ambiguous dataset for {iso3} in {year}")
    row = selected[0]
    files = row.get("files", [])
    tiffs = [item for item in files if isinstance(item, str)
             and urlparse(item).path.lower().endswith((".tif", ".tiff"))]
    if len(tiffs) != 1:
        raise ValueError("WorldPop catalogue: expected exactly one GeoTIFF URL")
    url = tiffs[0]
    if urlparse(url).scheme != "https":
        raise ValueError("WorldPop catalogue: download must use HTTPS")
    size = row.get("size_bytes", row.get("file_size", row.get("size")))
    # Only exact byte counts can be checked; human-readable sizes are not exact.
    size = int(size) if str(size).isdigit() else None
    return {"alias": WORLDPOP_ALIAS, "url": url, "year": year, "iso3": iso3,
            "size_bytes": size, "dataset_id": row.get("id")}


def acquire_population(config):
    if config.worldpop != "auto":
        path = Path(config.worldpop).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"population.worldpop: GeoTIFF does not exist: {path}")
        return path, {"path": str(path), "sha256": sha256_file(path), "year": config.year,
                      "alias": None, "url": None, "source": "local"}
    cache = config.cache_dir.expanduser()
    cache.mkdir(parents=True, exist_ok=True)
    stem = f"{WORLDPOP_ALIAS}-{config.iso3}-{config.year}"
    path, metadata = cache / f"{stem}.tif", cache / f"{stem}.json"
    if path.exists() and metadata.exists():
        saved = json.loads(metadata.read_text())
        if (saved.get("alias"), saved.get("iso3"), saved.get("year")) != (
                WORLDPOP_ALIAS, config.iso3, config.year):
            raise ValueError(f"WorldPop cache metadata mismatch: {metadata}")
        if saved.get("sha256") != sha256_file(path):
            raise ValueError(f"WorldPop cache SHA-256 mismatch: {path}; remove the invalid cache entry")
        return path, {**saved, "path": str(path.resolve()), "source": "auto"}
    with requests.get(CATALOGUE_URL, params={"iso3": config.iso3}, timeout=(15, 60)) as response:
        response.raise_for_status()
        provenance = parse_catalogue(response.json(), config.year, config.iso3)
    if path.exists():
        expected = provenance["size_bytes"]
        if expected is not None and path.stat().st_size != expected:
            raise ValueError(f"WorldPop cached file size mismatch: {path}")
    else:
        temporary = None
        try:
            with NamedTemporaryFile(dir=cache, prefix=stem, suffix=".part", delete=False) as stream:
                temporary = Path(stream.name)
                with requests.get(provenance["url"], stream=True, timeout=(15, 120)) as response:
                    response.raise_for_status()
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        stream.write(chunk)
                    header = response.headers.get("Content-Length")
                    sizes = [provenance["size_bytes"]]
                    if header and header.isdigit() and not response.headers.get("Content-Encoding"):
                        sizes.append(int(header))
                actual = stream.tell()
                if any(size is not None and actual != size for size in sizes):
                    raise ValueError(f"WorldPop download size mismatch: received {actual} bytes")
            # Do not turn an HTML/error response into a valid cache entry.
            with rasterio.open(temporary) as raster:
                if raster.count != 1 or raster.crs is None:
                    raise ValueError("WorldPop download must be a single-band georeferenced raster")
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    provenance.update(sha256=sha256_file(path), path=str(path.resolve()), source="auto")
    with NamedTemporaryFile(dir=cache, mode="w", suffix=".json", delete=False) as stream:
        json.dump(provenance, stream, indent=2)
        metadata_temp = Path(stream.name)
    metadata_temp.replace(metadata)
    return path, provenance


@dataclass
class PopulationResult:
    weights: np.ndarray
    summary: dict
    provenance: dict


def allocate_population(graph, boundary, path, snap_max_m):
    """Boundary is WGS84; nearest nodes and distances use the metric graph CRS."""
    if boundary is None:
        raise ValueError("population needs input.source place | polygon | bbox")
    graph_crs = CRS.from_user_input(graph.graph["crs"])
    if not graph_crs.is_projected or any(not np.isclose(axis.unit_conversion_factor, 1)
                                        for axis in graph_crs.axis_info[:2]):
        raise ValueError("population allocation requires a projected graph CRS with metre units")
    node_ids = list(graph)
    coordinates = np.array([[graph.nodes[node]["x"], graph.nodes[node]["y"]] for node in node_ids])
    if not node_ids or not np.isfinite(coordinates).all():
        raise ValueError("population allocation requires nonempty finite node coordinates")
    tree = cKDTree(coordinates)
    weights = np.zeros(len(node_ids))
    with rasterio.open(path) as raster:
        if raster.crs is None or raster.count != 1:
            raise ValueError("population raster must have a CRS and one population-count band")
        projected = transform(Transformer.from_crs(4326, raster.crs, always_xy=True).transform, boundary)
        if not np.isfinite(get_coordinates(projected)).all():
            raise ValueError("population boundary cannot be projected into the raster CRS")
        try:
            clipped, affine = mask(raster, [mapping(projected)], crop=True, filled=False)
        except ValueError as exc:
            if "overlap" not in str(exc):
                raise
            return weights, {"total": 0.0, "allocated": 0.0, "unallocated": 0.0, "unallocated_pct": 0.0}
        cells = clipped[0].filled(0).astype(float)
        cells[~np.isfinite(cells) | (cells < 0)] = 0
        rows, cols = np.nonzero(cells > 0)
        populations = cells[rows, cols]
        if not len(populations):
            return weights, {"total": 0.0, "allocated": 0.0, "unallocated": 0.0, "unallocated_pct": 0.0}
        xs, ys = rasterio.transform.xy(affine, rows, cols, offset="center")
        projection = Transformer.from_crs(raster.crs, graph_crs, always_xy=True)
        points = np.column_stack(projection.transform(xs, ys))
    allocated = np.zeros(len(populations), dtype=bool)
    finite = np.isfinite(points).all(axis=1)
    # Chunk cell queries and resolve exact/equidistant ties by stable node ID.
    for start in range(0, len(points), 65536):
        indices = np.flatnonzero(finite[start:start+65536]) + start
        if not len(indices):
            continue
        distances, nearest = tree.query(points[indices], k=min(2, len(node_ids)))
        if len(node_ids) > 1:
            tied = np.isclose(distances[:, 0], distances[:, 1], rtol=1e-12, atol=1e-8)
            best, distance = nearest[:, 0].copy(), distances[:, 0]
            for offset in np.flatnonzero(tied):
                candidates = tree.query_ball_point(points[indices[offset]], distance[offset] + 1e-8)
                best[offset] = min(candidates, key=lambda i: node_id_key(node_ids[i]))
        else:
            best, distance = nearest, distances
        keep = distance <= snap_max_m
        allocated[indices[keep]] = True
        np.add.at(weights, best[keep], populations[indices[keep]])
    total = float(populations.sum())
    unallocated = float(populations[~allocated].sum())
    return weights, {"total": total, "allocated": float(weights.sum()), "unallocated": unallocated,
                     "unallocated_pct": 100 * unallocated / total if total else 0.0}


def prepare_population(graph, boundary, config):
    if config.worldpop is None:
        return None
    if boundary is None:
        raise ValueError("population needs input.source place | polygon | bbox")
    with StageProgress("WorldPop acquisition", 1) as progress:
        path, provenance = acquire_population(config)
        progress.advance()
    with StageProgress("Population allocation", 1) as progress:
        weights, totals = allocate_population(graph, boundary, path, config.snap_max_m)
        progress.advance()
    return PopulationResult(weights, {**totals, "year": provenance["year"], "alias": provenance["alias"],
                                      "snap_max_m": config.snap_max_m}, provenance)


def population_report(summary):
    return ["Population", "WorldPop is a modelled estimate, not a census",
            f"Year: {summary['year']}; dataset alias: {summary['alias'] or 'local raster'}",
            f"Boundary population: {summary['total']:.9g}; allocated: {summary['allocated']:.9g}",
            f"Unallocated: {summary['unallocated']:.9g} ({summary['unallocated_pct']:.4f}%); "
            f"maximum snap distance: {summary['snap_max_m']:g} m",
            "Unallocated cells are excluded from population-weighted metrics; counts may be fractional."]
