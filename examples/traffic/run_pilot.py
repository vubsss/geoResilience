"""Paired, explicitly synthetic traffic experiments on the supplied Hyderabad archives.

Run from the repository root with PYTHONPATH=src. Does not modify core pipeline code.
Population is replayed by exact node identity, never nearest-neighbour reassignment.
"""

import argparse
import csv
import hashlib
import json
import math
import platform
import subprocess
import zipfile
from importlib.metadata import version
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from georesilience.config import CleaningConfig, NetworkConfig, TrafficConfig, TravelTimeConfig
from georesilience.network import load_and_clean
from georesilience.time_models import FreeFlowTimeModel
from georesilience.traffic import (
    _road_capacities, gravity_od, prepare_traffic, write_traffic_csv, write_traffic_od_csv,
)
from types import SimpleNamespace


CITIES = ("gachibowli", "old-hyderabad")
# Common scenario assumptions for untagged roads, NOT Hyderabad calibration.
SPEEDS = {"motorway": 80, "motorway_link": 40, "trunk": 60, "trunk_link": 30,
          "primary": 50, "primary_link": 25, "secondary": 40, "secondary_link": 20,
          "tertiary": 30, "tertiary_link": 20, "residential": 20,
          "living_street": 10, "unclassified": 20, "road": 20}
# Fixed before inspecting traffic outputs; every case applies to BOTH areas.
CASES = [
    dict(name="base", rate=.1, cell=500, lane_capacity=1000, uniform=False),
    dict(name="low_demand", rate=.05, cell=500, lane_capacity=1000, uniform=False),
    dict(name="high_demand", rate=.2, cell=500, lane_capacity=1000, uniform=False),
    dict(name="lower_capacity", rate=.1, cell=500, lane_capacity=500, uniform=False),
    dict(name="coarser_zones", rate=.1, cell=750, lane_capacity=1000, uniform=False),
    dict(name="uniform_capacity", rate=.1, cell=500, lane_capacity=1000, uniform=True),
    dict(name="equal_demand_control", rate=.1, cell=500, lane_capacity=1000,
         uniform=False, total=10000),
]


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def save_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def extract(archive, root):
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    with zipfile.ZipFile(archive) as zipped:
        for entry in zipped.infolist():
            destination = (root / entry.filename).resolve()
            if not destination.is_relative_to(root):
                raise ValueError(f"Archive path outside destination: {entry.filename}")
            if entry.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            payload = zipped.read(entry)
            if destination.exists() and destination.read_bytes() != payload:
                raise ValueError(f"Refusing to replace different input: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)


def prepare_city(city, source, output):
    roads = source / "data" / city / "raw_network.graphml"
    historical = source / "results" / f"{city}-population"
    config = SimpleNamespace(
        input=SimpleNamespace(source="graphml", path=roads, model_dump=lambda **kw: {}),
        network=NetworkConfig(), cleaning=CleaningConfig(consolidate=False))
    graph, _, cleaning = load_and_clean(config)
    nodes = gpd.read_file(historical / "network.gpkg", layer="nodes")
    if set(nodes.node_id.astype(str)) != set(map(str, graph)) or nodes.node_id.duplicated().any():
        raise ValueError(f"{city}: cleaned node identities differ from population export")
    if not nodes.crs or not nodes.crs.is_projected or not graph.graph["crs"].is_projected:
        raise ValueError("Zoning requires projected metre coordinates")
    if any(axis.unit_name != "metre" for axis in graph.graph["crs"].axis_info):
        raise ValueError("Zoning requires metre units")
    lookup = nodes.set_index(nodes.node_id.astype(str))
    nodes_on_graph = nodes.to_crs(graph.graph["crs"]).set_index(nodes.node_id.astype(str))
    if any(math.hypot(float(data['x']) - nodes_on_graph.loc[str(node)].geometry.x,
                      float(data['y']) - nodes_on_graph.loc[str(node)].geometry.y) > .1
           for node, data in graph.nodes(data=True)):
        raise ValueError("Exported node coordinates do not match cleaned graph")
    population = {node: float(lookup.loc[str(node), "population"]) for node in graph}
    if not all(math.isfinite(x) and x >= 0 for x in population.values()):
        raise ValueError("Invalid exported population")
    old = json.loads((historical / "summary.json").read_text(encoding="utf-8"))
    if not math.isclose(sum(population.values()), old["population"]["allocated"], rel_tol=1e-8):
        raise ValueError("Population total mismatch")
    free = FreeFlowTimeModel().prepare(graph, TravelTimeConfig(highway_speeds_kph=SPEEDS))
    if free.summary["status"] != "computed":
        raise ValueError("Cannot obtain free-flow costs")
    arcs = [(u, v, k, d) for u, v, k, d in graph.edges(keys=True, data=True) if u != v]
    _, _, coverage = _road_capacities(arcs, TrafficConfig())
    audit = dict(city=city, archive_sha256=digest(Path(city + ".zip")),
                 graph_sha256=digest(roads), population_gpkg_sha256=digest(historical / "network.gpkg"),
                 nodes=len(graph), directed_arcs=len(arcs), cleaning=cleaning,
                 population=old["population"], free_flow=free.summary,
                 capacity_tag_coverage=coverage,
                 historical_redundancy={k: old["metrics"]["redundancy"][k]
                                        for k in ("bridge_frac", "bridge_length_frac", "detour_ratio")})
    save_json(output / city / "input_audit.json", audit)
    return graph, population, free.edge_seconds, audit


def zone_masses(graph, population, cell_m):
    """Prototype pilot zoning; not a replacement for teammate's production module."""
    groups = {}
    for node, mass in population.items():
        if mass > 0:
            data = graph.nodes[node]
            tile = (math.floor(data["x"] / cell_m), math.floor(data["y"] / cell_m))
            groups.setdefault(tile, []).append((node, mass))
    rows, assignments = [], []
    for tile, members in sorted(groups.items()):
        mass = math.fsum(value for _, value in members)
        cx = math.fsum(graph.nodes[node]["x"] * value for node, value in members) / mass
        cy = math.fsum(graph.nodes[node]["y"] * value for node, value in members) / mass
        anchor = min(members, key=lambda pair: (
            (graph.nodes[pair[0]]["x"] - cx)**2 + (graph.nodes[pair[0]]["y"] - cy)**2,
            str(pair[0])))[0]
        rows.append(dict(node=str(anchor), mass=mass))
        assignments.extend(dict(node=str(node), anchor=str(anchor), population=value,
                                grid_x=tile[0], grid_y=tile[1]) for node, value in members)
    if len(rows) < 2 or not math.isclose(sum(r["mass"] for r in rows), sum(population.values()), rel_tol=1e-10):
        raise ValueError("Invalid zone population accounting")
    return rows, assignments


def run_case(city, case, graph, population, free, output, max_iterations, gap):
    target = output / city / case["name"]
    target.mkdir(parents=True, exist_ok=True)
    zones, memberships = zone_masses(graph, population, case["cell"])
    zone_path = target / "zone_masses.csv"
    save_csv(zone_path, zones)
    save_csv(target / "zone_membership.csv", memberships)
    total = case.get("total", sum(population.values()) * case["rate"])
    demand = gravity_od(graph, free, zone_path, total, .08)
    # Independent accounting of the existing gravity adapter's returned margins.
    productions = dict.fromkeys(graph, 0.0)
    attractions = dict.fromkeys(graph, 0.0)
    for (u, v), value in demand.items():
        productions[u] += value
        attractions[v] += value
    targets = {r["node"]: total * r["mass"] / sum(population.values()) for r in zones}
    margin_error = max(abs(values[node] - targets[str(node)]) / max(targets[str(node)], 1)
                       for values in (productions, attractions) for node in graph if str(node) in targets)
    if margin_error > 1e-7 or not math.isclose(sum(demand.values()), total, rel_tol=1e-8):
        raise ValueError("OD margin conservation failed")
    od_path = target / "input_od.csv"
    save_csv(od_path, [dict(origin=str(u), destination=str(v), demand_pcu_h=value)
                       for (u, v), value in demand.items()])
    config = TrafficConfig(enabled=True, demand_source="od_csv", od_csv=od_path,
                           capacity_pcu_h=1000 if case["uniform"] else None,
                           road_capacity_pcu_h_per_lane=case["lane_capacity"],
                           relative_gap=gap, max_iterations=max_iterations)
    result = prepare_traffic(graph, config, free)
    # Check net arc flows against OD injections independently of path assignment.
    balance = dict.fromkeys(graph, 0.0)
    by_string = {str(n): n for n in graph}
    for row in result.rows:
        balance[by_string[row["u"]]] += row["assigned_volume_pcu_h"]
        balance[by_string[row["v"]]] -= row["assigned_volume_pcu_h"]
    residual = max(abs(balance[n] - productions[n] + attractions[n]) for n in graph)
    if residual > 1e-6 * max(total, 1):
        raise ValueError("Assignment flow conservation failed")
    if any(row['congested_time_s'] < row['free_flow_time_s'] for row in result.rows):
        raise ValueError("Congested cost below free flow")
    summary = result.summary
    mean_free = sum(r["demand_pcu_h"] * r["free_flow_time_s"] for r in result.od_rows) / total
    length = sum(graph[by_string[r["u"]]][by_string[r["v"]]][int(r["key"])]["length"]
                 for r in result.rows)
    over_length = sum(graph[by_string[r["u"]]][by_string[r["v"]]][int(r["key"])]["length"]
                      for r in result.rows if r["vc_ratio"] > 1)
    pair = dict(city=city, case=case["name"], status=summary["status"],
                rate_pcu_person_h=None if "total" in case else case["rate"],
                demand_pcu_h=total, cell_m=case["cell"], zones=len(zones),
                capacity_mode="uniform" if case["uniform"] else "tags_common_fallback",
                lane_capacity_pcu_h=case["lane_capacity"],
                free_flow_mean_min=mean_free / 60,
                congested_mean_min=summary["mean_od_time_s"] / 60,
                mean_delay_min=summary["mean_od_delay_s"] / 60,
                travel_time_index=summary["mean_od_time_s"] / mean_free,
                over_capacity_arc_length_pct=100 * over_length / length,
                tstt_pcu_hours=summary["tstt_pcu_hours"],
                relative_gap=summary["relative_gap"], iterations=summary["iterations"],
                max_flow_residual_pcu_h=residual, max_relative_margin_error=margin_error)
    save_json(target / "summary.json", dict(**pair, assignment=summary, settings=case))
    write_traffic_csv(result, target / "traffic_arcs.csv")
    write_traffic_od_csv(result, target / "traffic_od.csv")
    if case["name"] == "base":
        geometry = []
        from shapely.geometry import LineString
        for row in result.rows:
            u, v, k = by_string[row["u"]], by_string[row["v"]], int(row["key"])
            geometry.append(graph[u][v][k].get("geometry") or LineString([
                (graph.nodes[u]["x"], graph.nodes[u]["y"]),
                (graph.nodes[v]["x"], graph.nodes[v]["y"])]))
        gpd.GeoDataFrame(result.rows, geometry=geometry, crs=graph.graph["crs"]).to_file(
            target / "traffic.gpkg", layer="traffic_arcs", driver="GPKG")
    print(json.dumps(pair), flush=True)
    return pair


def figures(rows, output):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for ax, field, title in zip(axes, ["travel_time_index", "mean_delay_min"],
                               ["Travel-time index (congested / free-flow)", "Mean OD delay (minutes)"]):
        x = np.arange(len(CASES))
        for i, city in enumerate(CITIES):
            selected = [next(r for r in rows if r["city"] == city and r["case"] == c["name"]) for c in CASES]
            bars = ax.bar(x + (i - .5) * .36, [r[field] for r in selected], .36,
                         label=city, color=["#258f9b", "#d87a43"][i])
            for bar, row in zip(bars, selected):
                if row["status"] != "converged":
                    bar.set_hatch("///")
        ax.set_xticks(x, [c["name"].replace("_", "\n") for c in CASES], fontsize=8)
        ax.set_title(title, fontsize=11)
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=.2)
    fig.suptitle("Synthetic traffic scenarios — common rules for both Hyderabad areas", fontsize=13)
    fig.savefig(output / "scenario_comparison.png", dpi=180)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for ax, city in zip(axes, CITIES):
        frame = gpd.read_file(output / city / "base/traffic.gpkg")
        frame.plot(column="vc_ratio", ax=ax, cmap="YlOrRd", vmin=0, vmax=2,
                   linewidth=1, legend=True, legend_kwds={"label": "V/C (colour capped at 2)"})
        ax.set_title(city + " — synthetic base case")
        ax.set_aspect("equal")
        ax.set_axis_off()
    fig.savefig(output / "base_vc_maps.png", dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=Path("data/traffic_comparison"))
    parser.add_argument("--output", type=Path, default=Path("results/traffic_comparison"))
    parser.add_argument("--max-iterations", type=int, default=600)
    parser.add_argument("--gap", type=float, default=1e-3)
    args = parser.parse_args()
    # Keep results attributable to one complete invocation, never stale mixed runs.
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Choose a fresh --output directory; existing results are preserved")
    args.output.mkdir(parents=True, exist_ok=True)
    save_json(args.output / "experiment.json", dict(
        claim="Synthetic scenario comparison, not observed traffic or a required ranking reversal",
        git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        script_sha256=digest(Path(__file__)), python=platform.python_version(),
        versions={p: version(p) for p in ("osmnx", "networkx", "numpy", "scipy", "geopandas")},
        cases=CASES, speed_fallbacks_kph=SPEEDS, gravity_lambda_per_min=.08,
        bpr_alpha=.15, bpr_beta=4, relative_gap=args.gap, max_iterations=args.max_iterations,
        caveats=["Resident-only synthetic OD; population supplies both margins, no measured trips/jobs.",
                 "All generated demand is interzonal; intrazonal/external trips are not estimated.",
                 "Representative road nodes concentrate zone demand; sensitivity is essential.",
                 "Archived SCC population allocation retained, including Gachibowli undercoverage.",
                 "No measured capacity calibration, signals, queues, parking or mode-specific traffic.",
                 "Mean times reflect different trip patterns; no single overall resilience ranking."]))
    rows = []
    for city in CITIES:
        extract(Path(city + ".zip"), args.inputs)
        graph, population, free, _ = prepare_city(city, args.inputs, args.output)
        for case in CASES:
            rows.append(run_case(city, case, graph, population, free, args.output,
                                 args.max_iterations, args.gap))
            save_csv(args.output / "comparison.csv", rows)
    figures(rows, args.output)
    print("COMPLETE", args.output.resolve(), flush=True)


if __name__ == "__main__":
    main()
