"""Generate exact-answer and spatial examples for connectivity reliability."""

import argparse
import csv
import itertools
import json
import math
from pathlib import Path

import networkx as nx
import numpy as np
import yaml
from pyproj import Transformer

from create_ticket08_demo import _road, _write_csv, _write_input, spatial_graph
from georesilience.links import _link_rows


def small_graph(name):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    positions = [(0, 0), (1000, 0)] if name != "bridge" else [
        (0, 0), (500, 500), (1000, 0), (2000, 0), (2500, 500), (3000, 0)]
    for node, (x, y) in enumerate(positions):
        graph.add_node(node, x=float(500000+x), y=float(1900000+y))
    if name == "half":
        edges, probabilities = [(0, 1)], [.5]
    elif name == "directed":
        edges, probabilities = [(0, 1), (1, 0)], [0, .5]
    else:
        edges = [(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3), (2, 3)]
        probabilities = [.05]*6 + [.3]
    for way, (u, v) in enumerate(edges, 1):
        a, b = graph.nodes[u], graph.nodes[v]
        _road(graph, u, v, math.hypot(a["x"]-b["x"], a["y"]-b["y"]), way,
              "Bridge" if name == "bridge" and way == 7 else f"Road {way}", name != "directed")
    return graph, dict(enumerate(probabilities, 1))


def exact_reference(graph, user, pairs):
    """Independent NetworkX enumeration of every physical-link failure state."""
    links = _link_rows(graph)
    if len(links) > 15:
        raise ValueError("exact enumeration is limited to 15 physical links")
    probabilities = [user[int(link["osm_way_ids"])] for link in links]
    expected, nodes = 0.0, dict.fromkeys(graph, 0.0)
    ods = dict.fromkeys((label for label, _, _ in pairs), 0.0)
    up_sum, down_sum = np.zeros(len(links)), np.zeros(len(links))
    for down in itertools.product([False, True], repeat=len(links)):
        mass = math.prod(p if failed else 1-p for p, failed in zip(probabilities, down))
        changed = nx.DiGraph()
        changed.add_nodes_from(graph)
        for link, failed in zip(links, down):
            if not failed:
                changed.add_edges_from((u, v) for u, v, _ in link["_edges"])
        components = list(nx.strongly_connected_components(changed))
        score = sum(len(c)*(len(c)-1) for c in components)/(len(graph)*(len(graph)-1))
        main = min(components, key=lambda c: (-len(c), min(c)))
        expected += mass*score
        for node in main:
            nodes[node] += mass
        for label, origin, dest in pairs:
            ods[label] += mass*nx.has_path(changed, origin, dest)
        for index, failed in enumerate(down):
            (down_sum if failed else up_sum)[index] += mass*score
    return {"conn_reliability": expected, "node_membership": nodes, "od_reliability": ods,
            "links": [{"link_id": link["link_id"], "name": link["name"], "p_fail": p,
                       "rel_importance": float(up_sum[i]/(1-p)-down_sum[i]/p) if 0 < p < 1 else None}
                      for i, (link, p) in enumerate(zip(links, probabilities))],
            "states_enumerated": 2**len(links), "method": "independent NetworkX failure-state enumeration"}


def write_od(graph, path, pairs):
    transform = Transformer.from_crs(graph.graph["crs"], 4326, always_xy=True)
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["label", "origin_lon", "origin_lat", "dest_lon", "dest_lat"])
        for label, origin, dest in pairs:
            a, b = graph.nodes[origin], graph.nodes[dest]
            writer.writerow([label, *transform.transform(a["x"], a["y"]),
                             *transform.transform(b["x"], b["y"])])


def create_examples(folder, n=200, seed=42, samples=10000):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    scenarios = []
    for name in ("half", "directed", "bridge"):
        graph, user = small_graph(name)
        pairs = [("forward", 0, len(graph)-1), ("reverse", len(graph)-1, 0)]
        _write_input(graph, folder, name)
        _write_csv(folder / f"{name}-probabilities.csv", user.items())
        write_od(graph, folder / f"{name}-od.csv", pairs)
        reference = exact_reference(graph, user, pairs)
        (folder / f"{name}-expected.json").write_text(json.dumps(reference, indent=2) + "\n")
        scenarios.append((name, name, f"{name}-probabilities.csv", f"{name}-od.csv"))
    spatial, metadata = spatial_graph(n, seed)
    _write_input(spatial, folder, "spatial")
    ways = sorted({int(way) for link in _link_rows(spatial) for way in link["osm_way_ids"].split(",")})
    rng = np.random.default_rng(np.random.SeedSequence(seed).spawn(3)[2])
    full = dict(zip(ways, map(float, rng.uniform(.01, .25, len(ways)))))
    full[ways[0]], full[ways[-1]] = 0.0, 1.0
    mixed = {way: p for i, (way, p) in enumerate(full.items()) if i % 3 == 0}
    _write_csv(folder / "spatial-full-probabilities.csv", full.items())
    _write_csv(folder / "spatial-mixed-probabilities.csv", [*mixed.items(),
               *((way, "") for i, way in enumerate(ways) if i % 3 == 2), (99999999, .25)])
    # A long geometric route and its reverse, plus one short road.
    origin = min(spatial, key=lambda node: spatial.nodes[node]["x"])
    dest = max(spatial, key=lambda node: spatial.nodes[node]["x"])
    u, v = next(iter(spatial.edges()))[:2]
    write_od(spatial, folder / "spatial-od.csv", [("across", origin, dest),
              ("across-reverse", dest, origin), ("nearby", u, v)])
    scenarios.extend([(f"spatial-{kind}", "spatial", csv_name, "spatial-od.csv") for kind, csv_name in
                      [("proxy", None), ("user", "spatial-full-probabilities.csv"),
                       ("mixed", "spatial-mixed-probabilities.csv")]])
    for name, source, csv_name, od_name in scenarios:
        config = {
            "input": {"source": "graphml", "path": str(folder / f"{source}.graphml")},
            "cleaning": {"consolidate": False},
            "analysis": {"seed": seed, "n_jobs": 2, "max_memory_gb": .25},
            "criticality": {"k_betweenness": 5, "k_detour": 5, "k_nodes": 12, "exact_info_max_nodes": 0},
            "robustness": {"removal": ["nodes"], "steps": 4, "failure_runs": 2, "efficiency_sources": 32},
            "reliability": {"p0": .01, "p0_sweep": [.001, .05], "samples": samples,
                            "min_down_count": 30, "min_up_count": 30,
                            "p_fail_csv": str(folder / csv_name) if csv_name else None,
                            "od_pairs_csv": str(folder / od_name)},
            "output": {"dir": f"results/ticket09-{name}", "figures": name in ("half", "directed", "bridge", "spatial-mixed")}}
        (folder / f"{name}.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    manifest = {"description": "Synthetic independent physical-road failures, not calibrated hazard risks.",
                "scenarios": [name for name, *_ in scenarios], "samples": samples, "seed": seed,
                "spatial": metadata, "small_references": "<scenario>-expected.json uses exact state enumeration.",
                "spatial_validation": "Stress/coverage checks; no exact enumeration for the large graph.",
                "notes": "Same spatial graph in three coverage scenarios. Correlations between roads sharing OSM "
                         "ways are not modeled. Geometric crossings are junctions only at graph nodes."}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Generated three exact fixtures and three {n}-node / {metadata['links']}-link spatial scenarios in {folder}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/ticket09-demo"))
    parser.add_argument("--nodes", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--samples", type=int, default=10000)
    args = parser.parse_args()
    if args.samples < 2:
        parser.error("--samples must be at least 2")
    create_examples(args.out, args.nodes, args.seed, args.samples)


if __name__ == "__main__":
    main()
