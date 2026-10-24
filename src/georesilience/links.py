"""Physical links: pair reciprocal arcs once and retain parallel roads separately."""

import hashlib
import json
from numbers import Integral

from shapely.geometry import LineString


def _way_ids(value):
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return sorted({int(item) for item in values if item is not None})


def _text(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        return ";".join(sorted(map(str, value)))
    return str(value)


def node_key(value):
    if isinstance(value, Integral):
        return "int", str(int(value))
    return type(value).__name__, str(value)


def _geometry_key(geometry):
    if geometry is None:
        return ()
    coords = tuple(tuple(round(float(x), 6) for x in point[:2]) for point in geometry.coords)
    return min(coords, coords[::-1])


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def cleaning_fingerprint(road_path, network, cleaning):
    """Versioned binding to input bytes, cleaning settings, filter and loader version."""
    from .population import sha256_file
    import osmnx as ox
    return _digest({"schema": "physical-links-v1", "road_sha256": sha256_file(road_path),
                    "network": network.model_dump(mode="json"),
                    "cleaning": cleaning.model_dump(mode="json"), "osmnx": ox.__version__})


def _link_rows(graph):
    buckets = {}
    representatives = {node: node for node in graph}
    for u, v, key, data in graph.edges(keys=True, data=True):
        # NetworkX accepts equal scalar aliases (e.g. int and np.int64) as one
        # node. Consolidation may retain those aliases on opposite arc ends.
        u, v = representatives[u], representatives[v]
        endpoints = tuple(sorted((node_key(u), node_key(v))))
        signature = (endpoints, tuple(_way_ids(data.get("osmid"))), round(float(data.get("length", 0)), 1))
        buckets.setdefault(signature, []).append((u, v, key, data))
    groups = []
    for signature in sorted(buckets):
        arcs = sorted(buckets[signature], key=lambda e: (node_key(e[0]), node_key(e[1]), node_key(e[2])))
        forward, reverse = [], []
        for arc in arcs:
            (forward if node_key(arc[0]) <= node_key(arc[1]) else reverse).append(arc)
        # Parallel reciprocal arcs are paired one-to-one, never merged into one link.
        if signature[0][0] == signature[0][1]:
            groups.extend([[arc] for arc in arcs])
        else:
            for arc in forward:
                geometry = _geometry_key(arc[3].get("geometry"))
                compatible = [i for i, other in enumerate(reverse)
                    if not geometry or not _geometry_key(other[3].get("geometry"))
                    or geometry == _geometry_key(other[3].get("geometry"))]
                if compatible:
                    chosen = min(compatible, key=lambda i: (
                        _geometry_key(reverse[i][3].get("geometry")) != geometry,
                        node_key(reverse[i][2]) != node_key(arc[2]), i))
                    groups.append([arc, reverse.pop(chosen)])
                else:
                    groups.append([arc])
            groups.extend([[arc] for arc in reverse])
    rows = []
    seen = set()
    fingerprint = graph.graph.get("input_cleaning_fingerprint", "unbound-python-graph")
    for link_id, edges in enumerate(groups):
        u, v, _, data = edges[0]
        geometry = data.get("geometry")
        if geometry is None:
            geometry = LineString([(graph.nodes[u]["x"], graph.nodes[u]["y"]),
                                   (graph.nodes[v]["x"], graph.nodes[v]["y"])])
        canonical = [{"u": node_key(a), "v": node_key(b), "key": node_key(key),
                      "ways": _way_ids(d.get("osmid")), "length": float(d.get("length", 0)),
                      "geometry": _geometry_key(d.get("geometry"))} for a, b, key, d in edges]
        uid = "link_" + _digest({"fingerprint": fingerprint, "arcs": canonical})
        if uid in seen:
            raise ValueError("physical-link UID collision")
        seen.add(uid)
        rows.append({"link_id": link_id, "link_uid": uid, "u": str(u), "v": str(v), "_u": u, "_v": v,
                     "_edges": tuple((a, b, key) for a, b, key, _ in edges),
                     "osm_way_ids": ",".join(map(str, _way_ids([way for _, _, _, edge in edges
                                                                for way in _way_ids(edge.get("osmid"))]))),
                     "name": _text(data.get("name")), "highway": _text(data.get("highway")),
                     "length_m": float(data.get("length", 0)), "oneway": len(edges) == 1,
                     "is_self_loop": u == v, "geometry": geometry})
    return rows


def identify_links(graph, fingerprint):
    graph.graph["input_cleaning_fingerprint"] = fingerprint
    return _link_rows(graph)
