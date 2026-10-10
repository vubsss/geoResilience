"""Generate known-answer roads and three seeded spatial probability scenarios."""

import argparse
import csv
import io
import json
import math
from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
import yaml

from georesilience.failure_probabilities import export_edge_template
from georesilience.links import _link_rows


def _road(graph, u, v, length, ways, name, two_way=True):
    for a, b in [(u, v), (v, u)] if two_way else [(u, v)]:
        graph.add_edge(a, b, length=float(length), osmid=ways, name=name, highway="residential")


def exact_graph():
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for node, (x, y) in enumerate([(0, 0), (1000, 0), (0, 1000)]):
        graph.add_node(node, x=float(500000 + x), y=float(1900000 + y))
    _road(graph, 0, 1, 2000, 101, "2 km proxy")
    _road(graph, 1, 2, 3000, [201, 202], "3 km mixed")
    _road(graph, 2, 0, 1000, 301, "Single supplied way")
    _road(graph, 0, 2, 1500, [401, 402], "Two supplied ways", two_way=False)
    _road(graph, 1, 0, 2500, [501, 502], "Different supplied probabilities", two_way=False)
    return graph


def spatial_graph(n=200, seed=42):
    if n < 20:
        raise ValueError("use at least 20 spatial nodes")
    topology_seed, length_seed = np.random.SeedSequence(seed).spawn(2)
    topology_rng, length_rng = np.random.default_rng(topology_seed), np.random.default_rng(length_seed)
    radius = math.sqrt(12 / (math.pi * n))
    for attempt in range(1, 1001):
        chosen_seed = int(topology_rng.integers(0, 2**32))
        simple = nx.random_geometric_graph(n, radius, seed=chosen_seed)
        if nx.is_connected(simple):
            break
    else:
        raise ValueError("could not sample a connected spatial graph in 1000 attempts")
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for node, data in simple.nodes(data=True):
        x, y = data["pos"]
        graph.add_node(node, x=float(500000 + 5000 * x), y=float(1900000 + 5000 * y))
    for index, (u, v) in enumerate(sorted(simple.edges)):
        # Adjacent records reuse a way ID; every third road contains two ways.
        ways = [10000 + index // 2]
        if index % 3 == 0:
            ways.append(20000 + index)
        distance = math.dist(simple.nodes[u]["pos"], simple.nodes[v]["pos"]) * 5000
        length = distance * length_rng.uniform(1.0, 1.3)
        _road(graph, u, v, length, ways, f"Spatial road {index}")
    return graph, {"nodes": n, "links": simple.number_of_edges(), "radius": radius,
                   "topology_seed": chosen_seed, "sampling_attempts": attempt,
                   "length_rule": "Euclidean metres times U(1.0,1.3)", "seed": seed}


def _write_input(graph, folder, name):
    ox.save_graphml(graph, filepath=folder / f"{name}.graphml")
    nodes, edges = ox.graph_to_gdfs(graph)
    target = folder / f"{name}-input.gpkg"
    target.unlink(missing_ok=True)
    nodes.to_file(target, layer="nodes", driver="GPKG", engine="pyogrio")
    edges.to_file(target, layer="edges", driver="GPKG", engine="pyogrio")
    export_edge_template(graph, folder / f"{name}-template.csv")


def _write_csv(path, records):
    with path.open("w", newline="") as stream:
        stream.write("# Synthetic per-event probabilities for software testing; not calibrated road risks.\n")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["osm_way_id", "p_fail"])
        writer.writerows(records)


def _reference(graph, user, p0, path):
    # Deliberately direct survival products rather than the production log-domain calculation.
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["link_id", "name", "osm_way_ids", "length_m",
                                "expected_p_fail", "expected_source"], lineterminator="\n")
        writer.writeheader()
        for link in _link_rows(graph):
            ways = set(map(int, link["osm_way_ids"].split(",")))
            covered = ways & user.keys()
            uncovered_share = 1 - len(covered) / len(ways)
            p = 1 - math.prod(1 - user[way] for way in covered) * (
                (1 - p0) ** (link["length_m"] / 1000 * uncovered_share))
            source = "proxy" if not covered else "user" if covered == ways else "mixed"
            writer.writerow({"link_id": link["link_id"], "name": link["name"],
                             "osm_way_ids": link["osm_way_ids"], "length_m": link["length_m"],
                             "expected_p_fail": p, "expected_source": source})


def create_examples(folder=Path("data/ticket08-demo"), n=200, seed=42):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    exact = exact_graph()
    spatial, metadata = spatial_graph(n, seed)
    _write_input(exact, folder, "exact")
    _write_input(spatial, folder, "spatial")
    exact_user = {201: 0.1, 301: 0.1, 401: 0.1, 402: 0.1, 501: 0.1, 502: 0.3}
    _write_csv(folder / "exact-probabilities.csv", [*exact_user.items(), (202, "")])
    template = list(csv.DictReader(io.StringIO("\n".join(
        line for line in export_edge_template(spatial).splitlines() if not line.startswith("#")))))
    way_ids = [int(row["osm_way_id"]) for row in template]
    rng = np.random.default_rng(np.random.SeedSequence(seed).spawn(3)[2])
    full = dict(zip(way_ids, map(float, rng.uniform(0.01, 0.25, len(way_ids)))))
    full[way_ids[0]], full[way_ids[-1]] = 0.0, 1.0
    mixed = {way: full[way] for index, way in enumerate(way_ids) if index % 3 == 0}
    _write_csv(folder / "spatial-full-probabilities.csv", full.items())
    _write_csv(folder / "spatial-mixed-probabilities.csv", [
        *mixed.items(), *((way, "") for index, way in enumerate(way_ids) if index % 3 == 2),
        (99999999, 0.25)])
    scenarios = [("exact", exact, exact_user, "exact-probabilities.csv"),
                 ("spatial-proxy", spatial, {}, None),
                 ("spatial-user", spatial, full, "spatial-full-probabilities.csv"),
                 ("spatial-mixed", spatial, mixed, "spatial-mixed-probabilities.csv")]
    for name, graph, user, csv_name in scenarios:
        config = {
            "input": {"source": "graphml", "path": str(folder / ("exact.graphml" if name == "exact" else "spatial.graphml"))},
            "cleaning": {"consolidate": False},
            "analysis": {"seed": seed, "n_jobs": 2, "max_memory_gb": 0.25},
            "criticality": {"k_betweenness": 5, "k_detour": 5, "k_nodes": 12, "exact_info_max_nodes": 0},
            "robustness": {"removal": ["nodes"], "steps": 4, "failure_runs": 2, "efficiency_sources": 32},
            "reliability": {"p0": 0.01, "p0_sweep": [0.001, 0.05],
                            "p_fail_csv": str(folder / csv_name) if csv_name else None},
            "output": {"dir": f"results/ticket08-{name}", "figures": False}}
        (folder / f"{name}.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
        _reference(graph, user, 0.01, folder / f"{name}-expected.csv")
    manifest = {"description": "Synthetic probabilities, not calibrated hazard risks. Same spatial graph in all three scenarios.",
                "spatial": metadata, "scenarios": [name for name, *_ in scenarios],
                "exact_expected_by_name": {"2 km proxy": 0.0199, "3 km mixed": 1 - .9 * .99**1.5,
                                           "Single supplied way": .1, "Two supplied ways": .19,
                                           "Different supplied probabilities": .37},
                "spatial_mixed": "Every third way supplied, every third blank, remainder omitted; one unmatched ID.",
                "notes": "Coordinates are projected schematic positions; line crossings share a junction only at graph nodes. "
                         "Template lengths use equal shares. Expected CSVs use independent direct survival products."}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Generated exact fixture and {n}-node / {metadata['links']}-link spatial graph in {folder}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/ticket08-demo"))
    parser.add_argument("--nodes", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    create_examples(args.out, args.nodes, args.seed)


if __name__ == "__main__":
    main()
