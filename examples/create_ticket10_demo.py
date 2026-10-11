"""Generate travel-time threshold, speed, custom-time and sparse spatial examples."""

import argparse
import json
import math
from pathlib import Path

import networkx as nx
import yaml

from create_ticket08_demo import _road, _write_csv, _write_input
from create_ticket09_demo import write_od


def route_graph(speeds=True, attribute=False):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    graph.add_node(0, x=500000., y=1900000.)
    graph.add_node(1, x=501000., y=1900000.)
    for way, length in [(1, 1000), (2, 3000)]:
        _road(graph, 0, 1, length, way, "Fast road" if way == 1 else "Slow alternative")
    for _, _, data in graph.edges(data=True):
        if speeds:
            data["maxspeed"] = "60"
        if attribute:
            data["signal_delay_s"] = 15. if data["osmid"] == 1 else 30.
            data["modelled_time_s"] = 3.6*data["length"]/60 + data["signal_delay_s"]
    return graph


def sparse_graph(n=200):
    if n < 20 or n % 2:
        raise ValueError("--nodes must be even and at least 20")
    side = n//2
    width = math.ceil(math.sqrt(side))
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for node in range(n):
        region, index = divmod(node, side)
        graph.add_node(node, x=float(500000+region*(width+3)*100+(index % width)*100),
                       y=float(1900000+(index//width)*100))
    pairs = []
    for region in range(2):
        for node in range(side):
            for dest in (node+1, node+width):
                if dest < side and (dest != node+1 or node//width == dest//width):
                    pairs.append((region*side+node, region*side+dest, False))
    pairs.append((side-1, side, True))
    user = {}
    for way, (u, v, bridge) in enumerate(pairs, 1):
        a, b = graph.nodes[u], graph.nodes[v]
        _road(graph, u, v, math.hypot(a["x"]-b["x"], a["y"]-b["y"]), way,
              "Joining bridge" if bridge else f"Grid road {way}")
        user[way] = .3 if bridge else .08
        for key in graph[u][v]:
            graph[u][v][key]["maxspeed"] = str(30 if bridge else [30, 40, 50][way % 3])
        for key in graph[v][u]:
            graph[v][u][key]["maxspeed"] = str(30 if bridge else [30, 40, 50][way % 3])
    return graph, user


def create_examples(folder, n=200, seed=42, samples=1000):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    graphs = {"routes": route_graph(), "no-speeds": route_graph(speeds=False),
              "attribute": route_graph(speeds=False, attribute=True)}
    spatial, spatial_probabilities = sparse_graph(n)
    graphs["sparse"] = spatial
    for name, graph in graphs.items():
        _write_input(graph, folder, name)
        pairs = [("forward", 0, 1), ("reverse", 1, 0), ("same-node", 0, 0)] if name != "sparse" else [
            ("across-bridge", 0, n-1), ("across-reverse", n-1, 0), ("nearby", 0, 1)]
        write_od(graph, folder/f"{name}-od.csv", pairs)
    _write_csv(folder/"routes-probabilities.csv", [(1, .5), (2, 0)])
    _write_csv(folder/"sparse-probabilities.csv", spatial_probabilities.items())
    scenarios = [("tight", "routes", .5), ("boundary", "routes", 2), ("relaxed", "routes", 2.5),
                 ("skip", "no-speeds", .5), ("speed-table", "no-speeds", .5),
                 ("attribute", "attribute", .5), ("sparse", "sparse", .25)]
    for name, source, tau in scenarios:
        travel = {"enabled": True, "samples": samples, "n_origins": 24, "tau": tau}
        if name == "speed-table":
            travel["highway_speeds_kph"] = {"residential": 30}
        if name == "attribute":
            travel.update(time_model="edge_attribute", time_attribute="modelled_time_s")
        config = {
            "input": {"source": "graphml", "path": str(folder/f"{source}.graphml")},
            "cleaning": {"consolidate": False}, "analysis": {"seed": seed, "n_jobs": 2, "max_memory_gb": .25},
            "criticality": {"k_betweenness": 5, "k_detour": 5, "k_nodes": 8, "exact_info_max_nodes": 0},
            "robustness": {"removal": ["nodes"], "steps": 4, "failure_runs": 2,
                           "efficiency_sources": 24, "node_attack_metric": "degree"},
            "reliability": {"samples": 2000, "p0_sweep": [.01],
                            "p_fail_csv": str(folder/("sparse-probabilities.csv" if name == "sparse" else "routes-probabilities.csv")),
                            "od_pairs_csv": str(folder/f"{source}-od.csv")},
            "travel_time": travel, "output": {"dir": f"results/ticket10-{name}", "figures": False}}
        (folder/f"{name}.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    expected = {"tight": {"p_tt_ok": .5, "tt0_min": 1}, "boundary": {"p_tt_ok": 1, "tt0_min": 1},
                "relaxed": {"p_tt_ok": 1, "tt0_min": 1}, "skip": {"status": "skipped: no speed data"},
                "speed-table": {"p_tt_ok": .5, "tt0_min": 2}, "attribute": {"p_tt_ok": .5, "tt0_min": 1.25}}
    (folder/"expected.json").write_text(json.dumps(expected, indent=2)+"\n")
    manifest = {"scenarios": [name for name, *_ in scenarios], "seed": seed, "travel_time_samples": samples,
                "sparse_nodes": n, "sparse_physical_links": len(spatial_probabilities),
                "sparse_probabilities": "0.08 internal roads; 0.30 joining bridge; independent synthetic closures",
                "attribute_function": "modelled_time_s = 3.6 * length_m / 60 + signal_delay_s",
                "notes": "Small references are exact route calculations. Sparse case has no exact oracle. "
                         "The scenarios are software experiments, not calibrated traffic/hazard models."}
    (folder/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(f"Generated seven Ticket 10 scenarios, including {n}-node sparse network, in {folder}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/ticket10-demo"))
    parser.add_argument("--nodes", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--samples", type=int, default=1000)
    args = parser.parse_args()
    if args.samples < 2:
        parser.error("--samples must be at least 2")
    create_examples(args.out, args.nodes, args.seed, args.samples)


if __name__ == "__main__":
    main()
