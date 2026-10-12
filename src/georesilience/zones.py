"""Spatial reporting only: zones never enter routing or failure experiments."""

from dataclasses import dataclass
import math
from numbers import Integral, Real
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
from shapely import get_coordinates


ZONE_FIGURES = ("zones_vulnerability_map.png",)


def _zone_key(value):
    text = str(value)
    try:
        return (0, int(text), text)
    except ValueError:
        return (1, text)


def _id(value):
    if pd.isna(value) or isinstance(value, (bool, np.bool_)):
        raise ValueError("zones.id_field: IDs must be non-null strings or finite numbers")
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Real):
        if not math.isfinite(value):
            raise ValueError("zones.id_field: IDs must be finite")
        return str(int(value)) if float(value).is_integer() else str(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("zones.id_field: IDs must be nonempty strings or finite numbers")
    return value.strip()


def _metric_crs(crs):
    result = CRS.from_user_input(crs)
    if not result.is_projected or any(not math.isclose(axis.unit_conversion_factor, 1)
                                       for axis in result.axis_info[:2]):
        raise ValueError("zones require a projected graph CRS with metre units")
    return result


def load_zones(config, graph_crs):
    """Validate the entire supplied partition, including zones outside the graph."""
    if config.path is None:
        return None
    if config.id_field is None:
        raise ValueError("zones.id_field is required when zones.path is set")
    crs = _metric_crs(graph_crs)
    path = Path(config.path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"zones.path does not exist: {path}")
    frame = gpd.read_file(path)
    if frame.crs is None:
        raise ValueError("zones.path: polygons must declare a CRS")
    if frame.empty:
        raise ValueError("zones.path: expected at least one zone polygon")
    for field in (config.id_field, config.name_field):
        if field is not None and field not in frame.columns:
            raise ValueError(f"zones.path: missing field {field!r}")
    ids = frame[config.id_field].map(_id)
    duplicates = sorted(set(ids[ids.duplicated(keep=False)]), key=_zone_key)
    if duplicates:
        raise ValueError("zones.id_field: duplicate IDs: " + ", ".join(duplicates))
    if (frame.geometry.isna().any() or frame.geometry.is_empty.any()
            or not frame.geom_type.isin(["Polygon", "MultiPolygon"]).all()
            or not frame.geometry.is_valid.all()):
        raise ValueError("zones.path: every geometry must be a nonempty valid Polygon or MultiPolygon")
    names = (frame[config.name_field].map(lambda value: None if pd.isna(value) else str(value))
             if config.name_field is not None else pd.Series(None, index=frame.index, dtype=object))
    zones = gpd.GeoDataFrame({"zone_id": ids, "zone_name": names}, geometry=frame.geometry, crs=frame.crs)
    zones = zones.to_crs(crs)
    if (not np.isfinite(get_coordinates(zones.geometry)).all()
            or not zones.geometry.is_valid.all() or zones.geometry.is_empty.any()
            or not np.isfinite(zones.area).all() or (zones.area <= 0).any()):
        raise ValueError("zones.path: reprojected polygons must be finite, valid and have positive area")
    # Canonical order gives repeatable boundary assignment and ranking ties.
    order = sorted(range(len(zones)), key=lambda i: _zone_key(zones.zone_id.iloc[i]))
    zones = zones.iloc[order].reset_index(drop=True)
    overlaps = []
    index = zones.sindex
    for i, geometry in enumerate(zones.geometry):
        for j in index.query(geometry, predicate="intersects"):
            if j > i and geometry.intersection(zones.geometry.iloc[j]).area > 0:
                overlaps.append((zones.zone_id.iloc[i], zones.zone_id.iloc[j]))
    if overlaps:
        raise ValueError("zones.path: positive-area overlaps between IDs: "
                         + "; ".join(f"{a} / {b}" for a, b in overlaps))
    return zones


def _assign(points, zones):
    """Inclusive point-in-polygon; lowest canonical zone ID wins shared borders."""
    assigned = np.full(len(points), None, dtype=object)
    if (points.isna().any() or points.is_empty.any()
            or not points.geom_type.eq("Point").all()
            or not np.isfinite(get_coordinates(points)).all()):
        raise ValueError("zone assignment requires finite nonempty points")
    index = zones.sindex
    for start in range(0, len(points), 65536):
        inputs, polygons = index.query(points.iloc[start:start + 65536], predicate="intersects")
        best = np.full(min(65536, len(points) - start), len(zones), dtype=np.int64)
        np.minimum.at(best, inputs, polygons)
        found = best < len(zones)
        assigned[start:start + len(best)][found] = zones.zone_id.to_numpy()[best[found]]
    return pd.array(assigned, dtype="string")


def _midpoint(geometry):
    if geometry is None or geometry.is_empty or geometry.geom_type not in ("LineString", "MultiLineString"):
        raise ValueError("zone link assignment requires nonempty road line geometries")
    if not np.isfinite(get_coordinates(geometry)).all():
        raise ValueError("zone link assignment requires finite road geometries")
    if geometry.geom_type == "LineString":
        return geometry.interpolate(.5, normalized=True)
    # Interpolate over the complete multipart length, not only its first part.
    remaining = geometry.length / 2
    for part in geometry.geoms:
        if remaining <= part.length:
            return part.interpolate(remaining)
        remaining -= part.length
    return geometry.geoms[-1].interpolate(1, normalized=True)


def _values(frame, column):
    return (frame[column].to_numpy(dtype=float, na_value=np.nan) if column in frame
            else np.full(len(frame), np.nan))


def _mean(values):
    finite = values[np.isfinite(values)]
    return float(finite.mean()) if len(finite) else math.nan


def _weighted(values, weights):
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    mass = float(weights[valid].sum())
    return float(np.dot(values[valid], weights[valid]) / mass) if mass > 0 else math.nan


def _records(frame):
    return [{key: None if pd.isna(value) else value for key, value in row.items()}
            for row in frame.drop(columns="geometry").to_dict("records")]


@dataclass
class ZoneResult:
    zones: gpd.GeoDataFrame
    nodes: gpd.GeoDataFrame
    links: gpd.GeoDataFrame
    summary: dict


def aggregate_zones(zones, nodes, links):
    """Consume finished layers, returning copies with assignments and zone aggregates.

    pop_weighted_vuln weights structural vuln by resident origin population.
    It is distinct from vuln_pop, which changes Hansen destination masses.
    """
    crs = _metric_crs(nodes.crs)
    if zones.crs != nodes.crs or links.crs != nodes.crs:
        raise ValueError("zone aggregation layers must share the graph CRS")
    nodes, links = nodes.copy(), links.copy()
    nodes["zone_id"] = _assign(nodes.geometry, zones)
    midpoints = gpd.GeoSeries([_midpoint(geometry) for geometry in links.geometry], crs=crs)
    links["zone_id"] = _assign(midpoints, zones)
    active = links.loc[~links["is_self_loop"].astype(bool)]
    lengths = _values(active, "length_m")
    if not np.isfinite(lengths).all() or (lengths <= 0).any():
        raise ValueError("zone road totals require positive finite physical link lengths")
    population_on = "population" in nodes
    if population_on:
        population = _values(nodes, "population")
        if not np.isfinite(population).all() or (population < 0).any():
            raise ValueError("zone population must be finite and nonnegative")
    node_groups = {key: group for key, group in nodes.groupby("zone_id")}
    link_groups = {key: group for key, group in active.groupby("zone_id")}
    available_ranks = {column: np.isfinite(_values(active, column)).any()
                       for column in ("crit_rank", "access_rank")}
    rows = []
    for zone in zones.itertuples(index=False):
        group = node_groups.get(zone.zone_id, nodes.iloc[:0])
        roads = link_groups.get(zone.zone_id, active.iloc[:0])
        road_km = float(roads.length_m.sum() / 1000)
        area = float(zone.geometry.area / 1e6)
        weights = _values(group, "population")
        pop = float(weights.sum()) if population_on else math.nan
        connected, vuln = _values(group, "p_connected"), _values(group, "vuln")
        finite_vuln = vuln[np.isfinite(vuln)]
        bridge_values = _values(roads, "is_bridge")
        bridge_km = float(roads.loc[bridge_values == 1, "length_m"].sum() / 1000)
        cutoff_defined = population_on and np.isfinite(connected[weights > 0]).all()
        cutoff = float(np.dot(weights[weights > 0], 1 - connected[weights > 0])) if cutoff_defined else math.nan
        row = {"zone_id": zone.zone_id, "zone_name": zone.zone_name, "geometry": zone.geometry,
               "n_nodes": len(group), "n_links": len(roads), "area_km2": area,
               "road_km": road_km, "road_density_km_per_km2": road_km / area,
               "population": pop, "road_km_per_1000_pop": road_km * 1000 / pop if pop > 0 else math.nan,
               "bridge_km_frac": bridge_km / road_km if road_km > 0 and np.isfinite(bridge_values).all() else math.nan,
               "mean_p_connected": _mean(connected), "pop_weighted_p_connected": _weighted(connected, weights),
               "mean_hansen_a": _mean(_values(group, "hansen_a")),
               "mean_hansen_a_pop": _mean(_values(group, "hansen_a_pop")),
               "mean_vuln": _mean(vuln), "pop_weighted_vuln": _weighted(vuln, weights),
               "p90_vuln": float(np.percentile(finite_vuln, 90)) if len(finite_vuln) else math.nan,
               "expected_pop_cut_off": cutoff,
               "n_valid_p_connected": int(np.isfinite(connected).sum()),
               "n_valid_vuln": len(finite_vuln),
               "vuln_population_coverage_frac": float(weights[np.isfinite(vuln)].sum() / pop) if pop > 0 else math.nan,
               "connected_population_coverage_frac": float(weights[np.isfinite(connected)].sum() / pop) if pop > 0 else math.nan}
        for column, output in (("crit_rank", "n_top50_critical_links"), ("access_rank", "n_top50_access_links")):
            ranks = _values(roads, column)
            row[output] = int(((ranks >= 1) & (ranks <= 50)).sum()) if available_ranks[column] else math.nan
        rows.append(row)
    result = gpd.GeoDataFrame(rows, crs=crs)
    basis = "pop_weighted_vuln" if population_on else "mean_vuln"
    ranked = sorted((i for i, value in enumerate(result[basis]) if math.isfinite(value)),
                    key=lambda i: (-result[basis].iloc[i], _zone_key(result.zone_id.iloc[i])))
    result["rank_vulnerability"] = pd.array([None] * len(result), dtype="Int64")
    for rank, index in enumerate(ranked, 1):
        result.loc[index, "rank_vulnerability"] = rank
    outside_nodes = nodes.loc[nodes.zone_id.isna()]
    outside_links = active.loc[active.zone_id.isna()]
    summary = {"zone_count": len(result), "rank_basis": basis, "ranked_zone_count": len(ranked),
               "unassigned_nodes": len(outside_nodes), "unassigned_links": len(outside_links),
               "unassigned_road_km": float(outside_links.length_m.sum() / 1000),
               "assigned_road_km": float(result.road_km.sum()),
               "excluded_self_loop_links": int(links.is_self_loop.sum()),
               "unassigned_population": float(outside_nodes.population.sum()) if population_on else None,
               "assigned_population": float(result.population.sum()) if population_on else None,
               "top_10": _records(result.iloc[ranked[:10]]),
               "bottom_10": _records(result.iloc[list(reversed(ranked))[:10]]),
               "assignment": "node point / road geometry half-length point; boundary included; lowest zone ID wins ties",
               "road_definition": "non-self-loop physical links counted once; entire stored length assigned by midpoint",
               "population_definition": "allocated node population; unallocated raster cells excluded",
               "vulnerability_definition": "pop_weighted_vuln = population-weighted structural vuln, not destination-weighted vuln_pop",
               "missing_values": "means exclude nonfinite values; weighted means use positive population with finite metric; coverage reported",
               "cut_off_definition": "sum(population * (1 - p_connected)); undefined if a positive-population node lacks membership probability"}
    return ZoneResult(result, nodes, links, summary)


def zones_report(summary):
    def number(value):
        return "not computed" if value is None else f"{value:.6g}"

    lines = ["Zones", f"Zone count: {summary['zone_count']}; ranked: {summary['ranked_zone_count']}; basis: {summary['rank_basis']}",
             f"Unassigned nodes: {summary['unassigned_nodes']}; non-loop roads: {summary['unassigned_links']} "
             f"({summary['unassigned_road_km']:.6g} km)",
             f"Unassigned allocated population: {number(summary['unassigned_population'])}",
             summary["assignment"], summary["road_definition"], summary["population_definition"],
             summary["vulnerability_definition"], summary["missing_values"], summary["cut_off_definition"],
             "Zone rankings inherit the evaluated-link scope of node vulnerability; zones never change analysis."]
    for title, rows in (("Top 10 most vulnerable zones", summary["top_10"]),
                        ("Bottom 10 least vulnerable ranked zones", summary["bottom_10"])):
        lines.extend(["", title, "rank | zone_id | name | nodes | road_km | population | vulnerability | expected_pop_cut_off"])
        for row in rows:
            lines.append(f"{row['rank_vulnerability']} | {row['zone_id']} | {row['zone_name'] or '-'} | "
                         f"{row['n_nodes']} | {number(row['road_km'])} | {number(row['population'])} | "
                         f"{number(row[summary['rank_basis']])} | {number(row['expected_pop_cut_off'])}")
        if not rows:
            lines.append("(none; zone vulnerability is undefined)")
    return lines
