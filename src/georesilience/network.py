"""Source adapters and the auditable network cleaning pipeline."""

import sys
from datetime import datetime, timezone

import geopandas as gpd
import networkx as nx
import osmnx as ox
from shapely.geometry import box

from .links import _link_rows

EXTRA_WAY_TAGS = (
    "motor_vehicle", "motorcar", "hgv", "access", "service", "area",
    "lanes", "surface", "maxspeed",
)
DRIVE_EXCLUDED_HIGHWAYS = {
    "abandoned", "bridleway", "bus_guideway", "construction", "corridor", "cycleway",
    "elevator", "escalator", "footway", "no", "path", "pedestrian", "planned",
    "platform", "proposed", "raceway", "razed", "service", "steps", "track",
}
BOUNDARY_WARNING = "clipped boundaries create artificial dead-ends; buffered download is planned"


def _log(message):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {message}", file=sys.stderr, flush=True)


def _has_tag(value, excluded):
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return any(item in excluded for item in values)


def _filter_drive(graph):
    graph = graph.copy()
    rejected = [
        (u, v, k) for u, v, k, d in graph.edges(keys=True, data=True)
        if _has_tag(d.get("highway"), DRIVE_EXCLUDED_HIGHWAYS)
        or _has_tag(d.get("area"), {"yes"})
        or _has_tag(d.get("access"), {"private"})
        or _has_tag(d.get("motor_vehicle"), {"no"})
        or _has_tag(d.get("motorcar"), {"no"})
    ]
    graph.remove_edges_from(rejected)
    graph.remove_nodes_from(list(nx.isolates(graph)))
    return graph


def _counts(graph):
    links = _link_rows(graph)
    return {
        "node_count": len(graph), "link_count": len(links),
        "total_length_km": sum(row["length_m"] for row in links) / 1000,
    }


def _dead_ends(graph):
    # Distinct neighbours: reciprocal directed edges count as one street.
    simple = nx.Graph(graph)
    simple.remove_edges_from(list(nx.selfloop_edges(simple)))
    return sum(degree == 1 for _, degree in simple.degree())


def _guard_dead_ends(before, after):
    change = abs(after - before) / before if before else (0 if after == 0 else 1)
    if change >= 0.05:
        raise ValueError(
            f"cleaning.consolidate: degree-1 node count changed from {before} to {after} "
            f"({change:.1%}); expected less than 5%. Reduce cleaning.tolerance_m "
            "or set cleaning.consolidate: false and inspect the junctions."
        )


def load_and_clean(config):
    # Extend, never replace: retain OSMnx defaults and make repeated runs idempotent.
    ox.settings.useful_tags_way = list(dict.fromkeys([*ox.settings.useful_tags_way, *EXTRA_WAY_TAGS]))
    source = config.input.source
    input_meta = config.input.model_dump(mode="json", exclude_none=True)
    boundary = None
    warnings = []
    applied = "as-provided"
    download_utc = None
    _log(f"Loading {source} network")
    kwargs = {
        "network_type": config.network.type, "custom_filter": config.network.custom_filter,
        "simplify": False, "retain_all": True,
    }
    if source in {"polygon", "osm_xml", "graphml"}:
        path = config.input.path.resolve()
        if not path.is_file():
            raise ValueError(f"input.path does not exist: {path}")
        input_meta["path"] = str(path)
    if source == "place":
        try:
            boundary = ox.geocode_to_gdf(config.input.place).to_crs(4326).geometry.union_all()
        except TypeError as exc:
            raise ValueError(
                f"input.place: {config.input.place!r} must resolve to a boundary polygon; "
                "choose a mapped administrative area or use input.source: bbox/polygon"
            ) from exc
        graph = ox.graph_from_place(config.input.place, **kwargs)
    elif source == "polygon":
        frame = gpd.read_file(path)
        if frame.crs is None:
            raise ValueError("input.path: boundary polygons must declare a CRS")
        if frame.empty or not frame.geom_type.isin(["Polygon", "MultiPolygon"]).all():
            raise ValueError("input.path: expected boundary polygons, not road lines or points")
        boundary = frame.to_crs(4326).geometry.union_all()
        if boundary.is_empty or not boundary.is_valid:
            raise ValueError("input.path: boundary polygon is empty or invalid")
        graph = ox.graph_from_polygon(boundary, **kwargs)
    elif source == "bbox":
        boundary = box(*config.input.bbox)
        graph = ox.graph_from_bbox(bbox=config.input.bbox, **kwargs)
    elif source == "osm_xml":
        # Filter before simplification: aggregating access/highway tags first can
        # combine a legal road with a forbidden one and discard both.
        graph = ox.graph_from_xml(path, simplify=False, retain_all=True)
    else:
        graph = ox.load_graphml(filepath=path)
    if source in {"place", "polygon", "bbox"}:
        download_utc = datetime.now(timezone.utc).isoformat()
        applied = "custom_filter" if config.network.custom_filter is not None else config.network.type
    if graph.number_of_edges() == 0:
        raise ValueError("input: network has no road edges")
    cleaning = {"raw": _counts(graph)}
    if source == "osm_xml":
        if config.network.type == "drive":
            graph = _filter_drive(graph)
            applied = "drive"
        else:
            warnings.append(f"XML network.type={config.network.type} cannot be applied; keeping as-provided")
        if config.network.custom_filter is not None:
            warnings.append("network.custom_filter cannot be applied to XML; using the XML network.type rules")
        if graph.number_of_edges() == 0:
            raise ValueError("network.type: XML drive filter removed all road edges")
        cleaning["filtered"] = _counts(graph)
    elif source == "graphml" and config.network.custom_filter is not None:
        warnings.append("network.custom_filter cannot be applied to GraphML; keeping as-provided")
    _log("Simplifying and projecting network")
    if graph.graph.get("simplified") is not True:
        graph = ox.simplify_graph(graph)
    if graph.number_of_edges() == 0:
        raise ValueError("cleaning: simplification left no road edges")
    graph = ox.project_graph(graph)
    cleaning["simplified"] = _counts(graph)
    before = _dead_ends(graph)
    if config.cleaning.consolidate:
        _log(f"Consolidating intersections (tolerance {config.cleaning.tolerance_m:g} m)")
        nx.set_node_attributes(graph, ox.stats.count_streets_per_node(graph), "street_count")
        graph = ox.consolidate_intersections(
            graph, tolerance=config.cleaning.tolerance_m, rebuild_graph=True,
            dead_ends=True, reconnect_edges=True,
        )
        _guard_dead_ends(before, _dead_ends(graph))
    cleaning["consolidated"] = _counts(graph)
    cleaning["consolidation_enabled"] = config.cleaning.consolidate
    cleaning["dead_ends"] = {"before": before, "after": _dead_ends(graph)}
    if not graph:
        raise ValueError("cleaning: consolidation left an empty graph")
    _log("Keeping largest strongly connected component")
    component_count = nx.number_strongly_connected_components(graph)
    graph = ox.truncate.largest_component(graph, strongly=True)
    if graph.number_of_edges() == 0:
        raise ValueError("cleaning: largest strongly connected component has no road edges")
    cleaning["final"] = _counts(graph)
    length_before = cleaning["consolidated"]["total_length_km"]
    length_dropped = max(0, length_before - cleaning["final"]["total_length_km"])
    cleaning["dropped_components"] = {
        "count": component_count - 1,
        "nodes_dropped": cleaning["consolidated"]["node_count"] - len(graph),
        "length_dropped_km": length_dropped,
        "length_dropped_pct": 100 * length_dropped / length_before if length_before else 0,
    }
    if cleaning["dropped_components"]["length_dropped_pct"] > 5:
        warnings.append("check boundary clipping / one-way slivers")
    warnings.append(BOUNDARY_WARNING)
    cleaning["warnings"] = warnings
    for warning in warnings:
        _log(f"WARNING: {warning}")
    return graph, {
        "input": input_meta, "osm_download_utc": download_utc,
        "network_type_applied": applied,
        "study_boundary_wkt": boundary.wkt if boundary is not None else None,
    }, cleaning


def cleaning_report(cleaning):
    lines = ["Cleaning", "Stage            Nodes      Links     Length (km)"]
    for stage in ("raw", "filtered", "simplified", "consolidated", "final"):
        if stage in cleaning:
            row = cleaning[stage]
            lines.append(f"{stage:<14} {row['node_count']:>7} {row['link_count']:>10} {row['total_length_km']:>15.3f}")
    dropped = cleaning["dropped_components"]
    lines.append(
        f"Dropped components: {dropped['count']}; nodes: {dropped['nodes_dropped']}; "
        f"length: {dropped['length_dropped_km']:.3f} km ({dropped['length_dropped_pct']:.2f}%)"
    )
    lines.append(f"Degree-1 nodes: {cleaning['dead_ends']['before']} -> {cleaning['dead_ends']['after']}")
    lines.extend(f"WARNING: {message}" for message in cleaning["warnings"])
    return lines
