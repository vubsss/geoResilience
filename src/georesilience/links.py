"""Physical link grouping shared by cleaning and analysis."""

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
        return ";".join(map(str, value))
    return str(value)


def _link_rows(graph):
    groups = {}
    for u, v, key, data in graph.edges(keys=True, data=True):
        ways = _way_ids(data.get("osmid"))
        length = float(data.get("length", 0.0))
        pair = frozenset((u, v))
        group_key = (pair, tuple(ways), round(length, 1))
        groups.setdefault(group_key, []).append((u, v, key, data))
    rows = []
    for link_id, edges in enumerate(groups.values()):
        u, v, _, data = edges[0]
        loop = u == v
        geometry = data.get("geometry")
        if geometry is None:
            geometry = LineString([(graph.nodes[u]["x"], graph.nodes[u]["y"]),
                                   (graph.nodes[v]["x"], graph.nodes[v]["y"])])
        rows.append({
            "link_id": link_id, "u": str(u), "v": str(v), "_u": u, "_v": v,
            "osm_way_ids": ",".join(map(str, _way_ids(
                [way for _, _, _, edge in edges for way in _way_ids(edge.get("osmid"))]
            ))),
            "name": _text(data.get("name")), "highway": _text(data.get("highway")),
            "length_m": float(data.get("length", 0.0)), "oneway": len(edges) == 1,
            "is_self_loop": loop, "geometry": geometry,
        })
    return rows


