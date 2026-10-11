"""Generate Hansen examples with hand-computed answers and a seeded spatial comparison."""

import argparse
import json
import math
from pathlib import Path

import networkx as nx
import yaml
from shapely.geometry import LineString

from create_ticket08_demo import _road, _write_input, spatial_graph


def graph_from_roads(n, roads):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for node in range(n):
        graph.add_node(node, x=500000. + 1000 * node, y=1900000.)
    for way, (u, v, length, two_way) in enumerate(roads, 1):
        _road(graph, u, v, length, way, f"Road {way}: {length:g} m", two_way=two_way)
    return graph


def create_examples(folder, n=100, seed=42):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    graphs = {
        "two-node": graph_from_roads(2, [(0, 1, 1000, True)]),
        "path-k2": graph_from_roads(3, [(0, 1, 1000, True), (1, 2, 1000, True)]),
        "cutoff": graph_from_roads(4, [(0, 1, 999, True), (0, 2, 1000, True), (0, 3, 1001, True)]),
        "parallel-k2": graph_from_roads(2, [(0, 1, 1000, True), (0, 1, 1000, True), (0, 1, 4000, True)]),
        "directed": graph_from_roads(3, [(0, 1, 1000, False), (1, 2, 1000, False), (2, 0, 1000, False)]),
    }
    # Spatial coordinates agree with the directed triangle's 1 km road lengths.
    graphs["directed"].nodes[2].update(x=500500., y=1900000. + math.sqrt(3) * 500)
    # Each cutoff spoke is drawn at its stored length, rather than 1/2/3 km.
    for node, xy in {1: (500999., 1900000.), 2: (500000., 1901000.), 3: (498999., 1900000.)}.items():
        graphs["cutoff"].nodes[node].update(x=xy[0], y=xy[1])
    # Draw the long parallel alternative as a deliberate 4 km V-shaped route.
    for u, v, data in graphs["parallel-k2"].edges(data=True):
        if data["osmid"] == 3:
            xy = [(500000., 1900000.), (500500., 1900000. + math.sqrt(2000**2 - 500**2)), (501000., 1900000.)]
            data["geometry"] = LineString(xy if u == 0 else xy[::-1])
    spatial, spatial_manifest = spatial_graph(n, seed)
    graphs["spatial"] = spatial
    for name, graph in graphs.items():
        _write_input(graph, folder, name)
    names = ["two-node", "path-k2", "cutoff", "parallel-k2", "directed", "spatial-candidates", "spatial-all"]
    for name in names:
        spatial_case = name.startswith("spatial")
        source = "spatial" if spatial_case else name
        accessibility = {"half_distance_km": .3 if spatial_case else 1.,
                         "cutoff_factor": 1 if name == "cutoff" else 2 if name in {"path-k2", "directed"} else 5,
                         "k": 2 if name.endswith("k2") else 1,
                         "all_links": name != "spatial-candidates"}
        config = {
            "input": {"source": "graphml", "path": str(folder / f"{source}.graphml")},
            "cleaning": {"consolidate": False},
            "analysis": {"seed": seed, "n_jobs": 2, "max_memory_gb": .25,
                         "directed_removal": name != "directed"},
            "criticality": {"k_betweenness": 8, "k_detour": 8, "k_nodes": 5, "exact_info_max_nodes": 0},
            "robustness": {"removal": ["nodes"], "steps": 2, "failure_runs": 1, "efficiency_sources": 16},
            "reliability": {"samples": 64, "p0": 0, "p0_sweep": [0]},
            "travel_time": {"enabled": False}, "accessibility": accessibility,
            "output": {"dir": f"results/ticket11-{name}", "figures": True}}
        (folder / f"{name}.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    w = 2 ** (-.999)
    expected = {
        "two-node": {"hansen_a": [.5, .5], "vuln": [1, 1], "access_drop": [1]},
        "path-k2": {"hansen_a": [.75, 1, .75], "vuln": [1, .5, 1], "vuln_k2": [1, 1, 1], "access_drop": [.6, .6]},
        "cutoff": {"hansen_a": [w + .5, w, .5, 0], "vuln": [w / (w + .5), 1, 1, None],
                   "isolated_in_R": [False, False, False, True], "note": "999 m inside; 1000 m included; 1001 m excluded"},
        "parallel-k2": {"hansen_a": [.5, .5], "vuln": [0, 0], "vuln_k2": [.875, .875], "access_drop": [0, 0, 0]},
        "directed": {"hansen_a": [.75, .75, .75], "vuln": [1, 1, 1], "access_drop": [4 / 9] * 3},
        "spatial": {"note": "Same graph in both runs: identical baseline A; all-link single-link vulnerability >= candidate-only vulnerability."}}
    (folder / "expected.json").write_text(json.dumps(expected, indent=2) + "\n")
    manifest = {"scenarios": names, "spatial": spatial_manifest, "mass_convention": "uniform unit masses",
                "accessibility_definition": "Ticket 11 plan: directed exponential distance decay, inclusive radius, no self term",
                "pair_scope": "Only pairs drawn from each node's top three evaluated single-link closures",
                "auxiliary_stages": "Connectivity uses 64 samples with p0=0; travel time disabled; other existing pipeline stages run normally."}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Generated seven Ticket 11 scenarios, including a {n}-node spatial graph, in {folder}")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/ticket11-demo"))
    parser.add_argument("--nodes", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    create_examples(args.out, args.nodes, args.seed)
