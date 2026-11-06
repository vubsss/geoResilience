"""WorldPop count rasters, reproducible acquisition and cell-centre allocation."""

from dataclasses import dataclass
import hashlib
from pathlib import Path

import numpy as np
import geopandas as gpd
from pyproj import CRS, Transformer
import rasterio
from rasterio.mask import mask
from scipy.spatial import cKDTree
from shapely.geometry import mapping, box
from shapely.ops import transform
from shapely import get_coordinates

from .od import node_id_key
from .progress import StageProgress

def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class PopulationResult:
    weights: np.ndarray
    summary: dict
    provenance: dict


def study_boundary(graph, boundary_path=None, snap_max_m=500):
    """Return a WGS84 study crop and the exact method/bounds used to derive it."""
    graph_crs = CRS.from_user_input(graph.graph["crs"])
    if not graph_crs.is_projected or any(not np.isclose(axis.unit_conversion_factor, 1)
                                        for axis in graph_crs.axis_info[:2]):
        raise ValueError("study boundary requires a projected graph CRS with metre units")
    if boundary_path is not None:
        frame = gpd.read_file(boundary_path)
        if frame.crs is None:
            raise ValueError("boundary must declare a CRS")
        if frame.empty or not frame.geom_type.isin(["Polygon", "MultiPolygon"]).all():
            raise ValueError("boundary must contain polygons")
        geometry = frame.to_crs(graph_crs).geometry.union_all()
        method = "supplied_boundary"
    else:
        xy = np.array([(data["x"], data["y"]) for _, data in graph.nodes(data=True)])
        if not len(xy) or not np.isfinite(xy).all():
            raise ValueError("study boundary requires finite retained node coordinates")
        if not np.isfinite(snap_max_m) or snap_max_m < 0:
            raise ValueError("snap_max_m must be finite and nonnegative")
        lo, hi = xy.min(axis=0) - snap_max_m, xy.max(axis=0) + snap_max_m
        geometry = box(*lo, *hi)
        method = "retained_graph_extent_plus_snap"
    if geometry.is_empty or not geometry.is_valid or geometry.area <= 0:
        raise ValueError("study boundary must have positive area; supply a boundary or positive snap distance")
    boundary = transform(Transformer.from_crs(graph_crs, 4326, always_xy=True).transform, geometry)
    return boundary, {"method": method, "bounds_graph_crs": list(geometry.bounds),
                      "graph_crs": graph_crs.to_string(), "bounds_wgs84": list(boundary.bounds),
                      "snap_max_m": snap_max_m}


def allocate_population(graph, boundary, path, snap_max_m):
    """Boundary is WGS84; nearest nodes and distances use the metric graph CRS."""
    if boundary is None:
        boundary, _ = study_boundary(graph, snap_max_m=snap_max_m)
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
        units = " ".join(str(value).lower() for value in [raster.units[0], *raster.tags().values(),
                                                          *raster.tags(1).values()] if value is not None)
        if any(token in units for token in ("density", "per km", "/km", "km-2", "km^-2", "per hectare", "/ha", "per square", "per sq", "/m2", "/m²")):
            raise ValueError("population raster must contain counts, not population density")
        if raster.scales[0] != 1 or raster.offsets[0] != 0:
            raise ValueError("population raster must contain unscaled population counts")
        projected = transform(Transformer.from_crs(4326, raster.crs, always_xy=True).transform, boundary)
        if not np.isfinite(get_coordinates(projected)).all():
            raise ValueError("population boundary cannot be projected into the raster CRS")
        try:
            clipped, affine = mask(raster, [mapping(projected)], crop=True, filled=False)
        except ValueError as exc:
            if "overlap" not in str(exc):
                raise
            raise ValueError("population raster does not overlap the study boundary") from exc
        valid = clipped[0].compressed().astype(float)
        if not np.isfinite(valid).all() or (valid < 0).any():
            raise ValueError("population raster contains invalid nonfinite or negative counts")
        if not valid.size:
            raise ValueError("population raster has no valid count cells in the study boundary")
        cells = clipped[0].filled(0).astype(float)
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


def prepare_population(graph, boundary, config, *, uniform_if_missing=False):
    if config.worldpop is None:
        if not uniform_if_missing:
            return None
        n = len(graph)
        return PopulationResult(np.ones(n),
            {"total": float(n), "allocated": float(n), "unallocated": 0., "unallocated_pct": 0.,
             "units": "uniform node demand units", "basis": "uniform_node_demand", "snap_max_m": None},
            {"source": "uniform_node_demand", "units": "one demand unit per retained node",
             "assumption": "population data absent; equal origin demand, not estimated resident counts"})
    path = Path(config.worldpop).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"population GeoTIFF does not exist: {path}")
    if boundary is None:
        boundary, _ = study_boundary(graph, snap_max_m=config.snap_max_m)
    with StageProgress("Population allocation", 1) as progress:
        weights, totals = allocate_population(graph, boundary, path, config.snap_max_m)
        progress.advance()
    provenance = {"path": str(path), "sha256": sha256_file(path), "source": "local_count_raster",
                  "units": "people per cell", "product": "user-supplied WorldPop count raster"}
    return PopulationResult(weights, {**totals, "snap_max_m": config.snap_max_m, "units": "people"}, provenance)
