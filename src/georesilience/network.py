"""Source adapters and the auditable network cleaning pipeline."""

import sys
import math
from datetime import datetime, timezone

import networkx as nx
import osmnx as ox
from shapely.geometry import LineString

from .links import _link_rows, cleaning_fingerprint, identify_links

EXTRA_WAY_TAGS = (
    "motor_vehicle", "motorcar", "hgv", "access", "service", "area",
    "lanes", "surface", "maxspeed",
)
DRIVE_EXCLUDED_HIGHWAYS = {
    "abandoned", "bridleway", "bus_guideway", "construction", "corridor", "cycleway",
    "elevator", "escalator", "footway", "no", "path", "pedestrian", "planned",
    "platform", "proposed", "raceway", "razed", "service", "steps", "track",
}


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


def _orient_arc_geometries(graph):
    """Align each stored LineString with its arc, before endpoint reconnection.

    MultiGraph.to_directed copies geometry unchanged to both directions. OSMnx
    consolidation prepends/appends centroids assuming u->v geometry, so an
    uncorrected reverse copy creates artificial backtracking and unequal lengths.
    """
    reversed_count = 0
    for u, v, data in graph.edges(data=True):
        geometry = data.get("geometry")
        if geometry is None or u == v:
            continue
        coords = list(geometry.coords)
        start = (graph.nodes[u]["x"], graph.nodes[u]["y"])
        end = (graph.nodes[v]["x"], graph.nodes[v]["y"])
        forward = math.dist(coords[0][:2], start) + math.dist(coords[-1][:2], end)
        reverse = math.dist(coords[0][:2], end) + math.dist(coords[-1][:2], start)
        if reverse < forward:
            data["geometry"] = LineString(coords[::-1])
            reversed_count += 1
    return reversed_count


def _node_identifier(value):
    try:
        number = int(value)
        return number if str(number) == str(value) else str(value)
    except (ValueError, TypeError):
        return str(value)


def load_and_clean(config):
    ox.settings.useful_tags_way = list(dict.fromkeys([*ox.settings.useful_tags_way, *EXTRA_WAY_TAGS]))
    source = config.input.source
    path = config.input.path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"input.path does not exist: {path}")
    _log(f"Loading {source} network")
    if source == "osm_xml":
        graph = ox.graph_from_xml(path, simplify=False, retain_all=True)
    else:
        graph = ox.load_graphml(filepath=path, node_dtypes={"osmid": _node_identifier})
    if graph.number_of_edges() == 0:
        raise ValueError("input: network has no road edges")
    if graph.graph.get("crs") is None:
        raise ValueError("road graph must declare a CRS")
    for node, data in graph.nodes(data=True):
        try:
            valid = all(math.isfinite(float(data[key])) for key in ("x", "y"))
        except (KeyError, ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError(f"road node {node}: finite x,y coordinates are required")
    for u, v, data in graph.edges(data=True):
        try:
            length = float(data["length"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("road edges require numeric length in metres") from exc
        if not math.isfinite(length) or length < 0 or (u != v and length == 0):
            raise ValueError("non-loop road lengths must be finite and positive metres")
    cleaning = {"raw": _counts(graph)}
    applied = "as-provided"
    if source == "osm_xml":
        if config.network.type == "drive":
            graph = _filter_drive(graph)
            applied = "drive"
        if graph.number_of_edges() == 0:
            raise ValueError("network.type: XML drive filter removed all road edges")
        cleaning["filtered"] = _counts(graph)
    _log("Simplifying and projecting network")
    if graph.graph.get("simplified") is not True:
        graph = ox.simplify_graph(graph)
    if graph.number_of_edges() == 0:
        raise ValueError("cleaning: simplification left no road edges")
    graph = ox.project_graph(graph)
    cleaning["simplified"] = _counts(graph)
    before = _dead_ends(graph)
    cleaning["arc_geometries_reoriented"] = _orient_arc_geometries(graph)
    if config.cleaning.consolidate:
        _log(f"Consolidating intersections (tolerance {config.cleaning.tolerance_m:g} m)")
        nx.set_node_attributes(graph, ox.stats.count_streets_per_node(graph), "street_count")
        graph = ox.consolidate_intersections(graph, tolerance=config.cleaning.tolerance_m,
            rebuild_graph=True, dead_ends=True, reconnect_edges=True)
        _guard_dead_ends(before, _dead_ends(graph))
    if not graph:
        raise ValueError("cleaning: consolidation left an empty graph")
    cleaning["consolidated"] = _counts(graph)
    cleaning["consolidation_enabled"] = config.cleaning.consolidate
    cleaning["dead_ends"] = {"before": before, "after": _dead_ends(graph)}
    component_count = nx.number_strongly_connected_components(graph)
    # Stable component ties preserve reproducibility for identically supplied inputs.
    from .links import node_key
    component = min(nx.strongly_connected_components(graph),
        key=lambda nodes: (-len(nodes), tuple(sorted(node_key(node) for node in nodes))))
    graph = graph.subgraph(component).copy()
    if graph.number_of_edges() == 0:
        raise ValueError("cleaning: largest strongly connected component has no road edges")
    cleaning["final"] = _counts(graph)
    length_before = cleaning["consolidated"]["total_length_km"]
    dropped = max(0, length_before - cleaning["final"]["total_length_km"])
    cleaning["dropped_components"] = {"count": component_count - 1,
        "nodes_dropped": cleaning["consolidated"]["node_count"] - len(graph),
        "length_dropped_km": dropped, "length_dropped_pct": 100 * dropped / length_before if length_before else 0}
    cleaning["warnings"] = (["check boundary clipping / one-way slivers"]
        if cleaning["dropped_components"]["length_dropped_pct"] > 5 else [])
    identify_links(graph, cleaning_fingerprint(path, config.network, config.cleaning))
    return graph, {"input": {**config.input.model_dump(mode="json", exclude_none=True), "path": str(path)},
        "network_type_applied": applied, "osm_download_utc": None, "study_boundary_wkt": None}, cleaning
