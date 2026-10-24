"""Validated optional WGS84 OD pairs snapped to retained metric nodes."""

import math
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from pyproj import CRS, Transformer
from scipy.spatial import cKDTree

OD_COLUMNS = ("label", "origin_lon", "origin_lat", "dest_lon", "dest_lat")


def node_id_key(node):
    """Numeric IDs sort numerically; other IDs lexically, with a stable type tie."""
    try:
        return (0, int(str(node)), type(node).__name__)
    except ValueError:
        return (1, str(node), type(node).__name__)


@dataclass
class ODInputs:
    pairs: list
    warnings: dict


def load_od_pairs(graph, path=None):
    """Snap WGS84 CSV endpoints to retained metric graph nodes."""
    notices = {"total_count": 0, "shown": [], "omitted_count": 0}
    if path is None:
        return ODInputs([], notices)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", pd.errors.ParserWarning)
            frame = pd.read_csv(path, comment="#", dtype=str, keep_default_na=False, index_col=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, pd.errors.ParserWarning) as exc:
        raise ValueError(f"od_pairs_csv: invalid CSV: {exc}") from exc
    missing = set(OD_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"od_pairs_csv: missing columns: {', '.join(sorted(missing))}")
    records, errors, seen = [], [], set()
    for number, values in enumerate(frame[list(OD_COLUMNS)].itertuples(index=False, name=None), 1):
        label = str(values[0]).strip()
        if not label or label in seen:
            errors.append(f"OD data row {number}: label must be nonempty and unique: {label!r}")
        seen.add(label)
        try:
            coords = [float(value) for value in values[1:]]
            if not all(math.isfinite(value) for value in coords):
                raise ValueError
            if not (-180 <= coords[0] <= 180 and -90 <= coords[1] <= 90
                    and -180 <= coords[2] <= 180 and -90 <= coords[3] <= 90):
                raise ValueError
        except (ValueError, TypeError):
            errors.append(f"OD data row {number} ({label!r}): coordinates must be finite WGS84 lon/lat")
            continue
        records.append(dict(zip(OD_COLUMNS, [label, *coords])))
    if errors:
        raise ValueError("od_pairs_csv validation failed:\n" + "\n".join(errors))
    if not records:
        return ODInputs([], notices)
    crs = CRS.from_user_input(graph.graph.get("crs"))
    if not crs.is_projected or any(not math.isclose(axis.unit_conversion_factor, 1)
                                   for axis in crs.axis_info[:2]):
        raise ValueError("OD snapping requires a projected graph CRS with metre units")
    node_ids = list(graph)
    if not node_ids:
        raise ValueError("OD snapping requires a nonempty graph")
    coordinates = np.array([[graph.nodes[node]["x"], graph.nodes[node]["y"]] for node in node_ids])
    if not np.isfinite(coordinates).all():
        raise ValueError("OD snapping requires finite node coordinates")
    tree = cKDTree(coordinates)
    transform = Transformer.from_crs(4326, crs, always_xy=True)
    for row in records:
        for endpoint in ("origin", "dest"):
            point = np.array(transform.transform(row[f"{endpoint}_lon"], row[f"{endpoint}_lat"]))
            if not np.isfinite(point).all():
                raise ValueError(f"OD {row['label']!r}: endpoint cannot be projected into the graph CRS")
            distance, nearest = tree.query(point)
            # Resolve coincident/equidistant nodes by the same ID order as SCC ties.
            candidates = tree.query_ball_point(point, distance + max(1e-8, distance * 1e-12))
            nearest = min(candidates, key=lambda index: (node_id_key(node_ids[index])))
            actual = np.linalg.norm(coordinates[nearest] - point)
            if not math.isclose(actual, distance, rel_tol=1e-12, abs_tol=1e-8):
                nearest = int(tree.query(point)[1])
                actual = np.linalg.norm(coordinates[nearest] - point)
            row[f"_{endpoint}"] = int(nearest)
            row[f"{endpoint}_node_id"] = str(node_ids[nearest])
            row[f"{endpoint}_snap_m"] = float(actual)
            if actual > 500:
                notices["total_count"] += 1
                if len(notices["shown"]) < 20:
                    notices["shown"].append(
                        f"OD {row['label']!r}: {endpoint} snap distance {actual:.1f} m exceeds 500 m")
    notices["omitted_count"] = notices["total_count"] - len(notices["shown"])
    return ODInputs(records, notices)


