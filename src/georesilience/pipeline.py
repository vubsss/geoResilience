import json
import platform
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import geopandas as gpd
import yaml
from pyproj import CRS
from shapely.geometry import Point
from shapely import wkt

from . import __version__
from .config import RunConfig
from .centralities import compute_centralities
from .classification import classify_network, write_classification_figures
from .connectivity import compute_connectivity, load_od_pairs, write_od_reliability
from .criticality import compute_criticality
from .figures import (FIGURE_FILENAMES, POPULATION_FIGURES, write_connectivity_figure, write_figures,
                      write_robustness_figures, write_accessibility_figures, write_population_figure,
                      write_zones_figure, write_scorecard_figure)
from .failure_probabilities import compute_failure_probabilities
from .links import _link_rows
from .network import load_and_clean
from .screening import screen_network
from .robustness import compute_robustness, write_curves
from .time_models import prepare_time_model
from .travel_time import compute_travel_time
from .accessibility import compute_accessibility
from .population import prepare_population
from .zones import ZONE_FIGURES, aggregate_zones, load_zones
from .scorecard import build_scorecard
from .reporting import build_locator_tables, build_report, collect_coverage_warnings


def _versions():
    result = {"python": platform.python_version()}
    for package in ("osmnx", "networkx", "scipy", "networkit", "numpy", "powerlaw"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "not installed"
    return result


def _resolved_config(config, out_dir, computation, custom_time_model=False):
    values = config.model_dump(mode="json")
    values["output"]["dir"] = str(out_dir)
    values["analysis"]["n_jobs"] = computation["n_jobs"]
    values["analysis"]["max_memory_gb"] = computation["max_memory_gb"]
    values["versions"] = _versions()
    if custom_time_model:
        # A Python provider cannot be reconstructed from YAML. Refuse accidental
        # reruns with the default formula; callers must supply their provider again.
        values["travel_time"]["time_model"] = "custom"
    return values


def _population_column_order(frame):
    """Place weighted variants next to their uniform counterparts in exported layers."""
    columns = []
    for name in frame.columns:
        if name.endswith("_pop") and name[:-4] in frame.columns:
            continue
        columns.append(name)
        if name + "_pop" in frame.columns:
            columns.append(name + "_pop")
    return frame[columns]


def run(config: RunConfig, out_override: Path | None = None, overwrite: bool = False, *, time_model=None):
    if config.population.worldpop is not None and config.input.source in {"graphml", "osm_xml"}:
        raise ValueError("population needs input.source place | polygon | bbox")
    if config.analysis.directed_centrality:
        raise NotImplementedError("analysis.directed_centrality: true is planned; use false for Ticket 03")
    out_dir = out_override or config.output.dir
    if out_dir.exists() and any(out_dir.iterdir()) and not overwrite:
        raise ValueError(f"output.dir exists and is not empty: {out_dir} (use --overwrite)")
    graph, input_meta, cleaning = load_and_clean(config)
    zones = load_zones(config.zones, graph.graph["crs"])
    out_dir.mkdir(parents=True, exist_ok=True)
    if overwrite:
        for name in ("network.gpkg", "summary.json", "report.txt", "run_config.yaml", "robustness_curves.csv",
                     "od_reliability.csv", "zones.gpkg"):
            (out_dir / name).unlink(missing_ok=True)
        for name in (*FIGURE_FILENAMES, *POPULATION_FIGURES, *ZONE_FIGURES):
            (out_dir / "figures" / name).unlink(missing_ok=True)
        try:
            (out_dir / "figures").rmdir()
        except OSError:
            pass
    boundary_wkt = input_meta.get("study_boundary_wkt")
    population = prepare_population(graph, wkt.loads(boundary_wkt) if boundary_wkt else None, config.population)
    population_weights = population.weights if population is not None else None

    links = _link_rows(graph)
    failure_probabilities = compute_failure_probabilities(graph, links, config.reliability)
    od_inputs = load_od_pairs(graph, config.reliability.od_pairs_csv)
    prepared_times = prepare_time_model(graph, config.travel_time, time_model)
    for row in links:
        row.update(failure_probabilities.link_metrics[row["link_id"]])
    analysis, node_metrics, edge_scores, statistics, computation = compute_centralities(
        graph, links, config.analysis)
    degree = dict(zip(analysis.node_ids, map(int, analysis.csr.indptr[1:] - analysis.csr.indptr[:-1])))
    for row in links:
        row["edge_betweenness"] = edge_scores[row["link_id"]]
    screening = screen_network(
        graph, links, dict(zip(analysis.node_ids, node_metrics["betweenness"])),
        config.criticality, computation["n_jobs"])
    for row in links:
        row.update(screening.link_metrics[row["link_id"]])
    statistics["redundancy"] = screening.summary
    statistics["runtime_seconds"].update(screening.runtime_seconds)
    criticality = compute_criticality(
        graph, links, screening, n_jobs=computation["n_jobs"],
        budget_bytes=computation["memory_budget_bytes"], directed=config.analysis.directed_removal,
        undirected_efficiency=statistics["global_efficiency"], population_weights=population_weights)
    for row in links:
        row.update(criticality.link_metrics[row["link_id"]])
    statistics["criticality"] = criticality.summary
    statistics["information"] = criticality.information_summary
    statistics["runtime_seconds"].update(criticality.runtime_seconds)
    computation.update(criticality.computation)
    accessibility = compute_accessibility(
        graph, links, screening, config.accessibility, n_jobs=computation["n_jobs"],
        budget_bytes=computation["memory_budget_bytes"], population_weights=population_weights)
    for row in links:
        row.update(accessibility.link_metrics[row["link_id"]])
    statistics["accessibility"] = accessibility.summary
    statistics["runtime_seconds"].update(accessibility.runtime_seconds)
    computation.update(accessibility.computation)
    robustness = compute_robustness(
        graph, links, config.robustness, seed=config.analysis.seed, n_jobs=computation["n_jobs"],
        budget_bytes=computation["memory_budget_bytes"])
    statistics["robustness"] = robustness.summary
    statistics["runtime_seconds"].update(robustness.runtime_seconds)
    write_curves(robustness, out_dir / "robustness_curves.csv")
    classification = classify_network(
        {"degree": list(degree.values()), **node_metrics,
         "information": [criticality.information[node] for node in analysis.node_ids]},
        criticality.information_summary, robustness.summary)
    statistics["runtime_seconds"].update(classification.runtime_seconds)
    connectivity = compute_connectivity(
        graph, links, config.reliability, failure_probabilities.user_probabilities,
        seed=config.analysis.seed, n_jobs=computation["n_jobs"],
        budget_bytes=computation["memory_budget_bytes"], od_inputs=od_inputs, population_weights=population_weights)
    statistics["runtime_seconds"].update(connectivity.runtime_seconds)
    computation.update(connectivity.computation)
    travel_time = compute_travel_time(
        graph, links, config.travel_time, config.reliability, failure_probabilities.user_probabilities,
        seed=config.analysis.seed, n_jobs=computation["n_jobs"],
        budget_bytes=computation["memory_budget_bytes"], od_inputs=od_inputs, prepared=prepared_times)
    statistics["runtime_seconds"].update(travel_time.runtime_seconds)
    computation.update(travel_time.computation)
    write_od_reliability(connectivity, out_dir / "od_reliability.csv", travel_time.od_metrics)
    for row in links:
        row.update(connectivity.link_metrics[row["link_id"]])
    n = len(analysis.node_ids)
    nodes = []
    for i, (node, data) in enumerate(graph.nodes(data=True)):
        d = degree[node]
        nodes.append({"node_id": str(node), "x": data["x"], "y": data["y"],
                      **({"population": float(population_weights[i])} if population is not None else {}),
                      "degree": d, "degree_centrality": d / (n - 1) if n > 1 else 0.0,
                      **{name: float(values[i]) for name, values in node_metrics.items()},
                      **screening.node_metrics[node],
                      "information": criticality.information[node],
                      **connectivity.node_metrics[node],
                      **travel_time.node_metrics[node],
                      **accessibility.node_metrics[node],
                      "geometry": Point(data["x"], data["y"])})
    crs = graph.graph.get("crs", "EPSG:4326")
    nodes_gdf = gpd.GeoDataFrame(nodes, geometry="geometry", crs=crs)
    nodes_gdf = _population_column_order(nodes_gdf)
    gpkg_links = [{key: value for key, value in row.items() if not key.startswith("_")} for row in links]
    links_gdf = gpd.GeoDataFrame(gpkg_links, geometry="geometry", crs=crs)
    links_gdf = _population_column_order(links_gdf)
    zone_result = aggregate_zones(zones, nodes_gdf, links_gdf) if zones is not None else None
    if zone_result is not None:
        nodes_gdf, links_gdf = zone_result.nodes, zone_result.links

    histogram = dict(sorted(Counter(degree.values()).items()))
    summary = {
        "meta": {"package_version": __version__,
                 "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                 **input_meta,
                 "crs_epsg": CRS.from_user_input(crs).to_epsg(),
                 "node_count": len(graph), "link_count": len(links),
                 "directed_edge_count": graph.number_of_edges()},
        "cleaning": cleaning,
        "classification": classification.summary,
        "reliability": {**failure_probabilities.summary, **connectivity.summary},
        "travel_time": travel_time.summary,
        "computation": computation,
        "metrics": {"degree": {"mean": sum(degree.values()) / n if n else 0,
                                 "max": max(degree.values(), default=0),
                                 "histogram": histogram}, **statistics},
    }
    if population is not None:
        summary["population"] = population.summary
    if zone_result is not None:
        summary["zones"] = zone_result.summary
    summary["scorecard"] = build_scorecard(summary, config.composite)
    if "composite" in summary["scorecard"]:
        summary["composite_user_weighted"] = summary["scorecard"]["composite"]["value"]
    summary["critical_tables"] = build_locator_tables(nodes_gdf, links_gdf, population is not None)
    summary["coverage_warnings"] = collect_coverage_warnings(summary)
    if zone_result is not None:
        zone_result.zones.to_file(
            out_dir / "zones.gpkg", layer="zones", driver="GPKG", engine="pyogrio")
    nodes_gdf.to_file(
        out_dir / "network.gpkg", layer="nodes", driver="GPKG", engine="pyogrio")
    links_gdf.to_file(
        out_dir / "network.gpkg", layer="edges", driver="GPKG", engine="pyogrio", mode="a")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out_dir / "report.txt").write_text(build_report(summary, config, links, out_dir.name))
    resolved = _resolved_config(config, out_dir, computation, time_model is not None)
    if population is not None:
        resolved["population_provenance"] = population.provenance
    (out_dir / "run_config.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False))
    if config.output.figures:
        write_scorecard_figure(summary["scorecard"], out_dir / "figures", run_name=out_dir.name)
        write_figures(nodes_gdf, links_gdf, out_dir / "figures", run_name=out_dir.name)
        write_robustness_figures(robustness, out_dir / "figures")
        write_classification_figures(classification, out_dir / "figures")
        write_connectivity_figure(nodes_gdf, links_gdf, out_dir / "figures", run_name=out_dir.name)
        write_accessibility_figures(nodes_gdf, links_gdf, out_dir / "figures", run_name=out_dir.name)
        if population is not None:
            write_population_figure(nodes_gdf, links_gdf, out_dir / "figures", run_name=out_dir.name)
        if zone_result is not None:
            write_zones_figure(zone_result.zones, links_gdf, out_dir / "figures", run_name=out_dir.name)
    return summary
