"""Run an offline, illustrative Tier 4 traffic experiment without GIS dependencies."""

import argparse
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import networkx as nx

from georesilience.traffic import (evaluate_closures, prepare_traffic,
                                  write_traffic_closures_csv, write_traffic_csv,
                                  write_traffic_od_csv)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("results/tier4-core-demo"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for node, (x, y) in enumerate(((500000, 1900000), (501000, 1900000),
                                    (500500, 1901000))):
        graph.add_node(node, x=float(x), y=float(y))
    links = []
    for way, (u, v) in enumerate(((0, 1), (1, 2), (0, 2)), 1):
        edges = []
        for a, b in ((u, v), (v, u)):
            key = graph.add_edge(a, b, length=1000.0, maxspeed="60", lanes="2",
                                 osmid=way, highway="residential")
            edges.append((a, b, key))
        links.append({"link_id": way, "osm_way_ids": str(way), "is_self_loop": False,
                      "_edges": tuple(edges)})
    nx.write_graphml(graph, args.out / "network.graphml")
    zone_file = args.out / "zone_mass.csv"
    with zone_file.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["node", "mass"])
        writer.writeheader()
        writer.writerows({"node": node, "mass": 1} for node in graph)
    config = SimpleNamespace(source="assignment", demand_source="gravity", zone_mass_csv=zone_file,
                             total_demand_pcu_h=300, gravity_lambda_per_min=.1,
                             capacity_csv=None, capacity_pcu_h=100, vdf="bpr", alpha=.15,
                             beta=4.0, relative_gap=1e-4, max_iterations=200,
                             period="illustrative_one_hour", duration_h=1.0, closure_top_n=1)
    free = {(u, v, key): 60.0 for u, v, key in graph.edges(keys=True)}
    result = prepare_traffic(graph, config, free)
    evaluate_closures(graph, links, result, free, config)
    result.summary["closures"] = result.closure_rows
    result.summary["assumptions"] = ("Three-zone synthetic network; equal zone mass; "
                                     "300 PCU/h; uniform 100 PCU/h arc capacity; "
                                     "BPR alpha=0.15 beta=4; not Hyderabad observations")
    write_traffic_csv(result, args.out / "traffic_arcs.csv")
    write_traffic_od_csv(result, args.out / "traffic_od.csv")
    write_traffic_closures_csv(result, args.out / "traffic_closures.csv")
    (args.out / "summary.json").write_text(json.dumps(result.summary, indent=2) + "\n")
    print(json.dumps(result.summary, indent=2))


if __name__ == "__main__":
    main()
