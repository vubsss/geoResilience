"""Recalculate Tier 1/2 metric families with frozen physical roads and new costs.

Experimental adapter, not a silent change to the production distance metrics.
Stages write separate files and can be run independently after baseline.
"""
import argparse
import csv
import json
import math
import os
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import networkit as nk
import networkx as nx
import numpy as np
from scipy.sparse.csgraph import dijkstra

from georesilience.config import TravelTimeConfig
from georesilience.links import _link_rows, node_key
from georesilience.metrics import PairUniverse, evaluate_matrix, relative_drop
from georesilience.reliability import compute_reliability
from georesilience.removal import ActiveEdgeGraph
from georesilience.time_models import PreparedTimeModel
from run_pilot import CITIES, digest, prepare_city, save_csv, save_json

MODES = ("distance", "free_flow", "congested")
HALF_TIME_S = 360.0


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def cost_topology(graph, links, costs):
    """Physical link membership is fixed BEFORE replacing routing costs."""
    working = graph.copy()
    for edge, cost in costs.items():
        if not math.isfinite(cost) or cost <= 0:
            raise ValueError("Routing costs must be positive")
        working.edges[edge]["length"] = cost
    return ActiveEdgeGraph(working, links, directed=True)


def snapshot(topology, population, half_units):
    # evaluate_matrix's name is distance-specific but its reducer is unit-agnostic.
    # Its internal *1000 converts this numeric adapter argument to half_units.
    return evaluate_matrix(topology.csr(), PairUniverse(population),
                           half_distance_km=half_units / 1000, cutoff_factor=5,
                           n_jobs=1, budget_bytes=512 * 1024**2)


def structural_scores(graph, links, costs):
    """Current undirected min-physical-link convention; mean directional cost."""
    nodes = list(graph)
    positions = {node: i for i, node in enumerate(nodes)}
    pairs = {}
    for row in links:
        if row["is_self_loop"]:
            continue
        u, v = sorted((positions[row["_u"]], positions[row["_v"]]))
        candidate = (math.fsum(costs[e] for e in row["_edges"]) / len(row["_edges"]), row["link_id"])
        if (u, v) not in pairs or candidate < pairs[u, v]:
            pairs[u, v] = candidate
    native = nk.Graph(len(nodes), weighted=True, directed=False)
    for (u, v), (cost, _) in sorted(pairs.items()):
        native.addEdge(u, v, cost)
    native.indexEdges()
    algorithm = nk.centrality.Betweenness(native, normalized=True, computeEdgeCentrality=True).run()
    node_b = dict(zip(nodes, algorithm.scores()))
    edge_b = {row["link_id"]: None if row["is_self_loop"] else 0.0 for row in links}
    scores = algorithm.edgeScores()
    for (u, v), (_, link_id) in pairs.items():
        edge_b[link_id] = float(scores[native.edgeId(u, v)])
    return node_b, edge_b


def bridge_ids(links):
    simple = nx.Graph()
    physical = {}
    for row in links:
        if not row["is_self_loop"]:
            pair = frozenset((row["_u"], row["_v"]))
            physical.setdefault(pair, []).append(row["link_id"])
            simple.add_edge(row["_u"], row["_v"])
    return {physical[frozenset(pair)][0] for pair in nx.bridges(simple)
            if len(physical[frozenset(pair)]) == 1}


def detours(topology, links, costs):
    results = {}
    for row in links:
        if row["is_self_loop"]:
            results[row["link_id"]] = (None, False)
            continue
        directions = {}
        for u, v, k in row["_edges"]:
            directions[u, v] = min(directions.get((u, v), math.inf), costs[u, v, k])
        sources = list(dict.fromkeys(u for u, _ in directions))
        matrix = topology.csr(removed_links=[row["link_id"]])
        after = dijkstra(matrix, directed=True, indices=[topology.index[u] for u in sources])
        ratios = [after[sources.index(u), topology.index[v]] / direct
                  for (u, v), direct in directions.items()]
        ratio = max(ratios)
        results[row["link_id"]] = (float(ratio) if math.isfinite(ratio) else None,
                                   not math.isfinite(ratio))
    return results


def attack(graph, links, population, costs, fraction=.2, steps=50, order="adaptive"):
    """Same per-link adaptive removal/SCC convention as current pipeline.

    Exact Brandes is accelerated with NetworKit; numerical ties at 12 decimals
    are broken by frozen physical UID. No traffic reassignment inside attacks.
    """
    active = [r for r in links if not r["is_self_loop"]]
    damaged = nx.MultiDiGraph()
    damaged.add_nodes_from(sorted(graph, key=node_key))
    damaged.add_edges_from(e for r in active for e in r["_edges"])
    masses = dict(zip(graph, population))
    count, total = len(active), float(sum(population))
    horizon = math.floor(fraction * count)
    reporting = min(steps, horizon)
    sample_counts = {math.ceil(i * horizon / reporting) for i in range(1, reporting + 1)} if reporting else set()
    curve = []
    removal_order = []

    def record(removed, uid=None):
        component = min(nx.strongly_connected_components(damaged), key=lambda c: (
            -len(c), tuple(sorted(node_key(n) for n in c))), default=set())
        curve.append(dict(fraction_removed=removed / count if count else 0,
                          links_removed=removed, node_share=len(component) / len(graph),
                          population_share=sum(masses[n] for n in sorted(component, key=node_key)) / total,
                          removed_link_uid=uid))

    def ranked():
        _, scores = structural_scores(graph, active, costs)
        return sorted(active, key=lambda r: (-round(scores[r["link_id"]], 12), r["link_uid"], r["link_id"]))

    record(0)
    static = ranked() if order == "static" else None
    start = time.perf_counter()
    for removed in range(1, horizon + 1):
        chosen = ranked()[0] if order == "adaptive" else static[removed - 1]
        damaged.remove_edges_from(chosen["_edges"])
        active.remove(chosen)
        removal_order.append(chosen["link_uid"])
        if removed in sample_counts:
            record(removed, chosen["link_uid"])
        if removed % 50 == 0:
            print(f"attack {removed}/{horizon}, elapsed {time.perf_counter()-start:.1f}s", flush=True)
    actual = horizon / count if count else 0
    raw = {key: float(np.trapezoid([r[key] for r in curve], [r['fraction_removed'] for r in curve]))
           for key in ("node_share", "population_share")}
    return dict(raw_auc=raw, normalized_auc={k: v / actual if actual else None for k, v in raw.items()},
                horizon=actual, steps=steps, order=order, links_removed=horizon,
                curve=curve, removal_order=removal_order,
                method="per-link adaptive exact Brandes; undirected mean-direction cost; 12dp UID tie break")


def load_city(city, args):
    graph, masses, _, audit = prepare_city(city, args.inputs, args.output / "audit" / args.stage)
    population = np.array([masses[n] for n in graph])
    links = _link_rows(graph)
    path = args.traffic / city / "base" / "traffic_arcs.csv"
    old_audit = json.loads((args.traffic / city / "input_audit.json").read_text())
    if audit["graph_sha256"] != old_audit["graph_sha256"] or audit["population_gpkg_sha256"] != old_audit["population_gpkg_sha256"]:
        raise ValueError("Traffic run and metric inputs differ")
    lookup = {(str(u), str(v), str(k)): (u, v, k) for u, v, k in graph.edges(keys=True) if u != v}
    traffic = read_csv(path)
    if {tuple(r[k] for k in ("u", "v", "key")) for r in traffic} != set(lookup):
        raise ValueError("Traffic costs must cover exact directed arc IDs")
    costs = {"distance": {e: float(graph.edges[e]["length"]) for e in lookup.values()}}
    for mode, field in (("free_flow", "free_flow_time_s"), ("congested", "congested_time_s")):
        costs[mode] = {lookup[r["u"], r["v"], r["key"]]: float(r[field]) for r in traffic}
    if any(costs['congested'][e] < costs['free_flow'][e] for e in lookup.values()):
        raise ValueError("Traffic costs fell below free flow")
    return graph, links, population, costs, audit


def baseline_stage(city, args, graph, links, population, costs):
    target = args.output / city
    bridges = bridge_ids(links)
    m = sum(not r["is_self_loop"] for r in links)
    for mode in MODES:
        dest = target / mode
        dest.mkdir(parents=True, exist_ok=True)
        start = time.perf_counter()
        topology = cost_topology(graph, links, costs[mode])
        half = 2000 if mode == "distance" else HALF_TIME_S
        base = snapshot(topology, population, half)
        node_b, edge_b = structural_scores(graph, links, costs[mode])
        alternative = detours(topology, links, costs[mode])
        finite = [r[0] for r in alternative.values() if r[0] is not None]
        median = float(np.median(finite))
        rows = [dict(node=str(n), population=float(population[i]), betweenness=float(node_b[n]),
                     hansen=float(base.node_hansen[i]), hansen_pop=float(base.node_hansen_pop[i]))
                for i, n in enumerate(graph)]
        save_csv(dest / "nodes.csv", rows)
        save_csv(dest / "links.csv", [dict(link_id=r['link_id'], link_uid=r['link_uid'],
                 name=r['name'], u=r['u'], v=r['v'], osm_way_ids=r['osm_way_ids'],
                 length_m=r['length_m'], is_self_loop=r['is_self_loop'], is_bridge=r['link_id'] in bridges,
                 edge_betweenness=edge_b[r['link_id']], detour_ratio=alternative[r['link_id']][0],
                 detour_none=alternative[r['link_id']][1]) for r in links])
        summary = dict(mode=mode, cost_unit="metres" if mode == "distance" else "seconds",
            bridge_share=len(bridges)/m, bridge_redundancy=1-len(bridges)/m,
            detour_alternative_share=len(finite)/m, median_detour_ratio=median, detour_index=1/median,
            hansen=float(base.accessibility), hansen_pop=float(base.accessibility_pop),
            raw_node_hansen_mean=float(base.accessibility)*(len(graph)-1),
            efficiency=float(base.efficiency), efficiency_pop=float(base.efficiency_pop),
            half_cost=half, cost_scope="fixed baseline costs during closures/removals",
            node_betweenness_mean=float(np.mean(list(node_b.values()))),
            node_betweenness_max=float(max(node_b.values())),
            edge_betweenness_mean=float(np.mean([v for v in edge_b.values() if v is not None])),
            edge_betweenness_max=float(max(v for v in edge_b.values() if v is not None)),
            bridge_count=len(bridges), link_count=m)
        if mode != "distance":
            summary['hansen_half_time_sensitivity'] = {str(minutes): dict(hansen=s.accessibility,
                hansen_pop=s.accessibility_pop) for minutes in (3, 6, 12)
                for s in [snapshot(topology, population, minutes*60)]}
        save_json(dest / "baseline.json", summary)
        print(city, mode, 'baseline', json.dumps(summary), 'seconds',time.perf_counter()-start,flush=True)
    # Monotonicity must hold for equal decay thresholds and identical OD universes.
    f = json.loads((target/'free_flow/baseline.json').read_text())
    c = json.loads((target/'congested/baseline.json').read_text())
    assert c['hansen'] <= f['hansen'] + 1e-12 and c['hansen_pop'] <= f['hansen_pop'] + 1e-12
    assert c['efficiency'] <= f['efficiency'] + 1e-12


class FixedTimeModel:
    def __init__(self, costs, name): self.costs, self.name = costs, name
    def prepare(self, graph, config):
        return PreparedTimeModel(self.costs, dict(status="computed", time_model=self.name,
            time_units="seconds", assumptions="fixed assigned times; no event reassignment"))


def reliability_stage(city, args, graph, links, population, costs):
    connection = None
    for mode in ('free_flow','congested'):
        print(city,mode,'reliability starting',flush=True)
        start=time.perf_counter()
        result = compute_reliability(graph, links, population, {}, p0=.01,
            connectivity_samples=1024, travel_time_samples=512, time_threshold=.5, seed=42,
            n_jobs=2, budget_bytes=1024**3, time_config=TravelTimeConfig(),
            time_model=FixedTimeModel(costs[mode], mode))
        save_json(args.output/city/mode/'reliability.json',dict(summary=result.summary,
            computation=result.computation, elapsed_s=time.perf_counter()-start))
        if connection is not None:
            for view in ('unweighted','population_weighted'):
                assert result.summary[view]['connectivity_reliability'] == connection[view]['connectivity_reliability']
        connection=result.summary
        print(city,mode,'reliability finished',time.perf_counter()-start,
              result.summary['unweighted'],flush=True)


def local_stage(city, args, graph, links, population, costs):
    """Exact damage on a common declared screening set, not an all-removals claim."""
    target=args.output/city
    node_candidates=set()
    link_candidates=set()
    for mode in MODES:
        ns=read_csv(target/mode/'nodes.csv')
        es=read_csv(target/mode/'links.csv')
        node_candidates.update(r['node'] for r in sorted(ns,key=lambda r:-float(r['betweenness']))[:30])
        link_candidates.update(int(r['link_id']) for r in sorted((r for r in es if r['edge_betweenness']),
                                                               key=lambda r:-float(r['edge_betweenness']))[:30])
    # Include previously presented high-information nodes and access-drop roads.
    import geopandas as gpd
    archive=args.inputs/'results'/f'{city}-population'/'network.gpkg'
    old_nodes=gpd.read_file(archive,layer='nodes')
    node_candidates.update(old_nodes.nlargest(10,'information').node_id.astype(str))
    old_links=gpd.read_file(archive,layer='edges')
    wanted=set(old_links.nlargest(10,'access_drop').link_id)|set(old_links.nlargest(10,'access_drop_pop').link_id)
    for _, old in old_links[old_links.link_id.isin(wanted)].iterrows():
        for r in links:
            if {r['u'],r['v']}=={str(old.u),str(old.v)} and r['osm_way_ids']==str(old.osm_way_ids):
                link_candidates.add(r['link_id'])
    index={str(n):i for i,n in enumerate(graph)}
    settings=dict(coverage='screened',common_node_ids=sorted(node_candidates),
                  common_link_ids=sorted(link_candidates),
                  method='union of top30 betweenness per cost plus historical top10 information/access-drop examples')
    save_json(target/'local_coverage.json', settings)
    for mode in MODES:
        topology=cost_topology(graph,links,costs[mode]);half=2000 if mode=='distance' else HALF_TIME_S
        universe=PairUniverse(population)
        kwargs=dict(half_distance_km=half/1000, cutoff_factor=5, n_jobs=1,budget_bytes=512*1024**2)
        base=evaluate_matrix(topology.csr(),universe,**kwargs)
        def damage(matrix):
            after=evaluate_matrix(matrix,universe,**kwargs)
            return dict(efficiency_drop=relative_drop(base.efficiency,after.efficiency),
                efficiency_drop_pop=relative_drop(base.efficiency_pop,after.efficiency_pop),
                accessibility_drop=relative_drop(base.accessibility,after.accessibility),
                accessibility_drop_pop=relative_drop(base.accessibility_pop,after.accessibility_pop))
        nodes=[];edges=[]
        for i,node in enumerate(sorted(node_candidates)):
            nodes.append(dict(node=node,**damage(topology.csr(isolated_nodes=[index[node]]))))
            if i%20==0:print(city,mode,'node consequences',i+1,len(node_candidates),flush=True)
        save_csv(target/mode/'node_consequences.csv',nodes)
        for i,link in enumerate(sorted(link_candidates)):
            edges.append(dict(link_id=link,**damage(topology.csr(removed_links=[link]))))
            if i%20==0:print(city,mode,'link consequences',i+1,len(link_candidates),flush=True)
        save_csv(target/mode/'link_consequences.csv',edges)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=['baseline','attack','reliability','local'],required=True)
    parser.add_argument('--inputs',type=Path,default=Path('data/traffic_comparison'))
    parser.add_argument('--traffic',type=Path,default=Path('results/traffic_comparison'))
    parser.add_argument('--output',type=Path,default=Path('results/traffic_metrics'))
    parser.add_argument('--cities',nargs='+',choices=CITIES,default=CITIES)
    args=parser.parse_args()
    nk.setNumberOfThreads(2)
    args.output.mkdir(parents=True,exist_ok=True)
    manifest=dict(script_sha256=digest(Path(__file__)),networkit=nk.__version__,
        stage=args.stage,cities=args.cities,traffic_manifest_sha256=digest(args.traffic/'experiment.json'),
        half_time_seconds=HALF_TIME_S,half_distance_m=2000,cutoff_factor=5,
        composite_weights=dict(attack=.25,bridge=.15,detour=.15,hansen=.15,travel=.15,connectivity=.15),
        note='Composite uses normalized attack AUC, inverse median detour, normalized Hansen; population view separately.')
    save_json(args.output/f'manifest_{args.stage}.json',manifest)
    for city in args.cities:
        graph,links,population,costs,_=load_city(city,args)
        if args.stage=='baseline':baseline_stage(city,args,graph,links,population,costs)
        elif args.stage=='reliability':reliability_stage(city,args,graph,links,population,costs)
        elif args.stage=='local':local_stage(city,args,graph,links,population,costs)
        else:
            for mode in MODES:
                print(city,mode,'attack starting',flush=True)
                result=attack(graph,links,population,costs[mode])
                save_json(args.output/city/mode/'attack.json',result)
                save_csv(args.output/city/mode/'attack_curve.csv',result['curve'])
                print(city,mode,'attack complete',result['normalized_auc'],flush=True)


if __name__=='__main__':main()
