import json
import platform
import textwrap
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import geopandas as gpd
import networkx as nx
import yaml
from pyproj import CRS
from shapely.geometry import Point

from . import __version__
from .config import RunConfig
from .links import _link_rows
from .network import cleaning_report, load_and_clean


def _versions():
    result = {"python": platform.python_version()}
    for package in ("osmnx", "networkx", "scipy", "networkit", "numpy"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "not installed"
    return result


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
    graph, input_meta, cleaning = load_and_clean(config)

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
                 **input_meta,
                 "crs_epsg": CRS.from_user_input(crs).to_epsg(),
                 "node_count": len(graph), "link_count": len(links),
                 "directed_edge_count": graph.number_of_edges()},
        "cleaning": cleaning,
        "metrics": {"degree": {"mean": sum(degree.values()) / n if n else 0,
                                 "max": max(degree.values(), default=0),
                                 "histogram": histogram}},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    lines = [f"GeoResilience {__version__}", f"Input: {summary['meta']['input']}",
             f"UTC: {summary['meta']['timestamp_utc']}", "", "Network",
             f"Nodes: {len(graph)}", f"Links: {len(links)}",
             f"Directed edges: {graph.number_of_edges()}",
             f"Network type requested: {config.network.type}",
             f"Network type applied: {summary['meta']['network_type_applied']}",
             "", *cleaning_report(cleaning), "", "Degree", "degree: count"]
    lines.extend(f"{key}: {value}" for key, value in histogram.items())
    lines = [line.encode("ascii", "backslashreplace").decode() for line in lines]
    lines = [textwrap.fill(line, width=100) if len(line) > 100 else line for line in lines]
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
