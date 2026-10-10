import json
import platform
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox
import yaml
from pyproj import CRS
from shapely.geometry import LineString, Point

from . import __version__
from .config import RunConfig


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


def _versions():
    result = {"python": platform.python_version()}
    for package in ("osmnx", "networkx", "scipy", "networkit", "numpy"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "not installed"
    return result


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


def _resolved_config(config, out_dir):
    values = config.model_dump(mode="json")
    values["output"]["dir"] = str(out_dir)
    values["versions"] = _versions()
    return values


def run(config: RunConfig, out_override: Path | None = None, overwrite: bool = False):
    out_dir = out_override or config.output.dir
    if out_dir.exists() and any(out_dir.iterdir()) and not overwrite:
        raise ValueError(f"output.dir exists and is not empty: {out_dir} (use --overwrite)")
    out_dir.mkdir(parents=True, exist_ok=True)
    if overwrite:
        for name in ("network.gpkg", "summary.json", "report.txt", "run_config.yaml"):
            (out_dir / name).unlink(missing_ok=True)
        figure = out_dir / "figures" / "degree_hist.png"
        figure.unlink(missing_ok=True)
        try:
            figure.parent.rmdir()
        except OSError:
            pass
    input_path = config.input.path
    if not input_path.is_absolute():
        input_path = input_path.resolve()
    if not input_path.is_file():
        raise ValueError(f"input.path does not exist: {input_path}")
    graph = ox.load_graphml(filepath=input_path)
    if graph.graph.get("simplified") is not True:
        graph = ox.simplify_graph(graph)
    graph = ox.project_graph(graph)

    links = _link_rows(graph)
    analysis = nx.Graph()
    analysis.add_nodes_from(graph.nodes)
    for row in links:
        if row["_u"] != row["_v"]:
            analysis.add_edge(row["_u"], row["_v"])
    degree = dict(analysis.degree())
    n = len(analysis)
    nodes = []
    for node, data in graph.nodes(data=True):
        d = degree[node]
        nodes.append({"node_id": str(node), "x": data["x"], "y": data["y"],
                      "degree": d, "degree_centrality": d / (n - 1) if n > 1 else 0.0,
                      "geometry": Point(data["x"], data["y"])})
    crs = graph.graph.get("crs", "EPSG:4326")
    gpd.GeoDataFrame(nodes, geometry="geometry", crs=crs).to_file(
        out_dir / "network.gpkg", layer="nodes", driver="GPKG", engine="pyogrio")
    gpkg_links = [{key: value for key, value in row.items() if not key.startswith("_")} for row in links]
    gpd.GeoDataFrame(gpkg_links, geometry="geometry", crs=crs).to_file(
        out_dir / "network.gpkg", layer="edges", driver="GPKG", engine="pyogrio", mode="a")

    histogram = dict(sorted(Counter(degree.values()).items()))
    summary = {
        "meta": {"package_version": __version__,
                 "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                 "input": {"source": config.input.source, "path": str(input_path)},
                 "crs_epsg": CRS.from_user_input(crs).to_epsg(),
                 "node_count": len(graph), "link_count": len(links),
                 "directed_edge_count": graph.number_of_edges()},
        "metrics": {"degree": {"mean": sum(degree.values()) / n if n else 0,
                                 "max": max(degree.values(), default=0),
                                 "histogram": histogram}},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    lines = [f"GeoResilience {__version__}", f"Input: {input_path}",
             f"UTC: {summary['meta']['timestamp_utc']}", "", "Network",
             f"Nodes: {len(graph)}", f"Links: {len(links)}",
             f"Directed edges: {graph.number_of_edges()}", "", "Degree", "degree: count"]
    lines.extend(f"{key}: {value}" for key, value in histogram.items())
    (out_dir / "report.txt").write_text("\n".join(lines) + "\n")
    (out_dir / "run_config.yaml").write_text(yaml.safe_dump(_resolved_config(config, out_dir), sort_keys=False))
    if config.output.figures:
        import matplotlib.pyplot as plt
        figure_dir = out_dir / "figures"
        figure_dir.mkdir(exist_ok=True)
        plt.hist(list(degree.values()), bins=range(max(degree.values(), default=0) + 2), align="left")
        plt.xlabel("Degree")
        plt.ylabel("Node count")
        plt.savefig(figure_dir / "degree_hist.png", bbox_inches="tight")
        plt.close()
    return summary
