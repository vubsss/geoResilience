"""Physical redundancy, directed detours, and candidates for later damage analysis."""

import math
import time
from collections import defaultdict
from dataclasses import dataclass

import networkx as nx
import numpy as np
from joblib import Parallel, delayed, parallel_config

from .network import _log


REASONS = ("betweenness", "detour", "directed_bridge", "large_bridge", "analytic_bridge")


@dataclass
class ScreeningResult:
    link_metrics: dict
    node_metrics: dict
    candidate_links: set
    analytic_bridges: set
    candidate_nodes: set
    summary: dict
    runtime_seconds: dict


def _rooted_weights(tree, weights):
    """Subtree weights and parents of a connected, integer-labelled tree."""
    root = next(iter(tree))
    parent = {root: None}
    order = [root]
    for node in order:
        for neighbour in tree[node]:
            if neighbour not in parent:
                parent[neighbour] = node
                order.append(neighbour)
    subtree = dict(weights)
    for node in reversed(order[1:]):
        subtree[parent[node]] += subtree[node]
    return subtree, parent


def _undirected_screen(graph, links):
    simple = nx.Graph()
    simple.add_nodes_from(graph)
    pair_links = defaultdict(list)
    for row in links:
        if not row["is_self_loop"]:
            u, v = row["_u"], row["_v"]
            simple.add_edge(u, v)
            pair_links[frozenset((u, v))].append(row["link_id"])
    if not len(simple) or not nx.is_connected(simple):
        raise ValueError("redundancy screening requires a nonempty, weakly connected network")
    n = len(simple)
    bridge_pairs = {frozenset(pair) for pair in nx.bridges(simple)
                    if len(pair_links[frozenset(pair)]) == 1}
    cut_sizes = {}
    if bridge_pairs:
        without_bridges = nx.subgraph_view(
            simple, filter_edge=lambda u, v: frozenset((u, v)) not in bridge_pairs)
        components = list(nx.connected_components(without_bridges))
        component_of = {node: i for i, nodes in enumerate(components) for node in nodes}
        tree = nx.Graph()
        tree.add_nodes_from(range(len(components)))
        for pair in bridge_pairs:
            u, v = tuple(pair)
            tree.add_edge(component_of[u], component_of[v], link_id=pair_links[pair][0])
        subtree, parent = _rooted_weights(tree, {i: len(nodes) for i, nodes in enumerate(components)})
        for node, ancestor in parent.items():
            if ancestor is not None:
                cut_sizes[tree[node][ancestor]["link_id"]] = min(subtree[node], n - subtree[node])

    articulation = set(nx.articulation_points(simple))
    severity = dict.fromkeys(simple, 0)
    if articulation:
        # Block nodes count their non-articulation vertices; articulation nodes
        # each weigh one. Removing an articulation then splits this weighted tree.
        blocks = list(nx.biconnected_components(simple))
        artic_index = {node: len(blocks) + i for i, node in enumerate(simple) if node in articulation}
        tree = nx.Graph()
        weights = {}
        for i, block in enumerate(blocks):
            tree.add_node(i)
            weights[i] = len(block - articulation)
            for node in block & articulation:
                tree.add_edge(i, artic_index[node])
                weights[artic_index[node]] = 1
        subtree, parent = _rooted_weights(tree, weights)
        for node, index in artic_index.items():
            branches = [subtree[other] if parent[other] == index else n - subtree[index]
                        for other in tree[index]]
            severity[node] = n - 1 - max(branches)
    return cut_sizes, articulation, severity


def _directed_graph(graph, links):
    """Retain all directed edges, including slower parallel alternatives."""
    directed = nx.MultiDiGraph()
    directed.add_nodes_from(graph)
    for row in links:
        if not row["is_self_loop"]:
            for u, v, key in row["_edges"]:
                directed.add_edge(u, v, key=key, length=float(graph[u][v][key]["length"]),
                                  link_id=row["link_id"])
    return directed


def _detour_batch(graph, tasks):
    result = []
    for link_id, length, directions in tasks:
        view = nx.subgraph_view(
            graph, filter_edge=lambda u, v, key: graph[u][v][key]["link_id"] != link_id)
        distances = []
        for u, v in directions:
            try:
                distance, _ = nx.bidirectional_dijkstra(view, u, v, weight="length")
                distances.append(distance)
            except nx.NetworkXNoPath:
                distances.append(math.inf)
                break
        result.append((link_id, max(distances) / length))
    return result


_WORKER_GRAPH = None


def _init_detour_worker(graph):
    # Send the graph once per worker instead of serializing it for every link.
    global _WORKER_GRAPH
    _WORKER_GRAPH = graph


def _worker_batch(tasks):
    return _detour_batch(_WORKER_GRAPH, tasks)


def directed_detours(graph, links, bridges, n_jobs=1):
    ratios = {link_id: math.inf for link_id in bridges}
    tasks = []
    for row in links:
        if row["is_self_loop"] or row["link_id"] in bridges:
            continue
        directions = tuple(dict.fromkeys((u, v) for u, v, _ in row["_edges"]))
        tasks.append((row["link_id"], row["length_m"], directions))
    if not tasks:
        return ratios
    directed = _directed_graph(graph, links)
    jobs = min(n_jobs, len(tasks))
    batch_size = max(1, math.ceil(len(tasks) / (8 * jobs)))
    batches = [tasks[i:i + batch_size] for i in range(0, len(tasks), batch_size)]
    if jobs == 1:
        for batch in batches:
            ratios.update(_detour_batch(directed, batch))
    else:
        with parallel_config(backend="loky", inner_max_num_threads=1):
            results = Parallel(n_jobs=jobs, return_as="generator", pre_dispatch=jobs,
                               initializer=_init_detour_worker, initargs=(directed,))(
                delayed(_worker_batch)(batch) for batch in batches)
            for result in results:
                ratios.update(result)
    return ratios


def screen_network(graph, links, node_betweenness, config, n_jobs=1):
    started = time.perf_counter()
    _log("Screening physical bridges and articulation points")
    cut_sizes, articulation, severity = _undirected_screen(graph, links)
    topology_done = time.perf_counter()
    _log(f"Computing directed detours for {sum(not row['is_self_loop'] for row in links)} links")
    ratios = directed_detours(graph, links, cut_sizes, n_jobs)
    detours_done = time.perf_counter()
    nonbridges = [row for row in links if not row["is_self_loop"] and row["link_id"] not in cut_sizes]
    betweenness_order = sorted(nonbridges, key=lambda row: (-row["edge_betweenness"], row["link_id"]))
    detour_order = sorted(nonbridges, key=lambda row: (
        -ratios[row["link_id"]], -row["edge_betweenness"], row["link_id"]))
    selected = {
        "betweenness": {row["link_id"] for row in betweenness_order[:config.k_betweenness]},
        "detour": {row["link_id"] for row in detour_order[:config.k_detour]},
        "directed_bridge": {row["link_id"] for row in nonbridges if math.isinf(ratios[row["link_id"]])},
        "large_bridge": {key for key, size in cut_sizes.items() if size > config.bridge_analytic_max_side},
        "analytic_bridge": {key for key, size in cut_sizes.items() if size <= config.bridge_analytic_max_side},
    }
    analytic = selected["analytic_bridge"]
    candidates = set().union(*(selected[reason] for reason in REASONS[:-1]))
    if config.all:
        candidates = {row["link_id"] for row in links if not row["is_self_loop"]} - analytic
    nodes = list(graph)
    n = len(nodes)
    if config.all or n <= config.exact_info_max_nodes:
        candidate_nodes = set(nodes)
    else:
        order = {node: i for i, node in enumerate(nodes)}
        ranked = sorted(nodes, key=lambda node: (-node_betweenness[node], order[node]))
        ranked_artic = sorted(articulation, key=lambda node: (-severity[node], order[node]))
        candidate_nodes = set(ranked[:config.k_nodes]) | set(ranked_artic[:50])
    link_metrics = {}
    for row in links:
        key = row["link_id"]
        loop = row["is_self_loop"]
        ratio = ratios.get(key, math.nan)
        size = cut_sizes.get(key, 0)
        link_metrics[key] = {
            "is_bridge": key in cut_sizes,
            "cut_side_nodes": math.nan if loop else size,
            "cut_side_frac": math.nan if loop else size / n,
            "detour_ratio": ratio if math.isfinite(ratio) else math.nan,
            "detour_none": math.isinf(ratio),
            "is_directed_bridge": key in selected["directed_bridge"],
            "candidate_reason": ";".join(reason for reason in REASONS if key in selected[reason]),
            "is_criticality_candidate": key in candidates,
            "is_analytic_bridge": key in analytic,
        }
    node_metrics = {node: {"is_articulation": node in articulation, "artic_max_cut": severity[node],
                           "is_info_candidate": node in candidate_nodes} for node in nodes}
    active = [row for row in links if not row["is_self_loop"]]
    total_length = sum(row["length_m"] for row in active)
    bridge_length = sum(row["length_m"] for row in active if row["link_id"] in cut_sizes)
    finite = [value for value in ratios.values() if math.isfinite(value)]
    quantiles = np.quantile(finite, [.5, .9, .99]).tolist() if finite else [None] * 3
    summary = {
        "non_self_loop_link_count": len(active), "bridge_count": len(cut_sizes),
        "bridge_frac": len(cut_sizes) / len(active) if active else 0.0,
        "bridge_length_frac": bridge_length / total_length if total_length else 0.0,
        "detour_ratio": dict(zip(("median", "p90", "p99"), quantiles)),
        "finite_detour_count": len(finite),
        "detour_none_count": sum(math.isinf(value) for value in ratios.values()),
        "directed_bridge_count": len(selected["directed_bridge"]),
        "articulation_count": len(articulation), "articulation_frac": len(articulation) / n,
        "candidate_link_count": len(candidates), "analytic_bridge_count": len(analytic),
        "candidate_node_count": len(candidate_nodes),
        "candidate_counts_by_reason": {reason: len(selected[reason]) for reason in REASONS},
    }
    finished = time.perf_counter()
    _log(f"Screening complete: {len(cut_sizes)} bridges, {len(selected['directed_bridge'])} directed "
         f"bridges; {len(candidates)} full-recompute links and {len(analytic)} analytic bridges")
    return ScreeningResult(link_metrics, node_metrics, candidates, analytic, candidate_nodes, summary,
                           {"screening_topology": topology_done - started,
                            "screening_detours": detours_done - topology_done,
                            "screening_candidates": finished - detours_done,
                            "screening_total": finished - started})


def redundancy_report(summary, links):
    stats = summary["detour_ratio"]
    lines = ["Redundancy", f"Bridges: {summary['bridge_count']} "
             f"(fraction {summary['bridge_frac']:.6g}; length fraction {summary['bridge_length_frac']:.6g})",
             f"Directed bridges: {summary['directed_bridge_count']}",
             f"Articulations: {summary['articulation_count']} (fraction {summary['articulation_frac']:.6g})",
             f"Finite detour ratios: median={stats['median']}, p90={stats['p90']}, p99={stats['p99']}",
             f"No alternative: {summary['detour_none_count']} links; "
             f"finite alternatives: {summary['finite_detour_count']}",
             f"Candidates: {summary['candidate_link_count']} full-recompute links, "
             f"{summary['analytic_bridge_count']} analytic bridges, {summary['candidate_node_count']} nodes",
             "Selection reasons (overlapping counts): " + ", ".join(
                 f"{reason}={count}" for reason, count in summary["candidate_counts_by_reason"].items()),
             "artic_max_cut counts surviving nodes outside the largest component after node removal."]
    bridges = sorted((row for row in links if row["is_bridge"]),
                     key=lambda row: (-row["cut_side_nodes"], row["link_id"]))[:20]
    nonbridges = sorted((row for row in links if not row["is_self_loop"] and not row["is_bridge"]),
                        key=lambda row: (-(math.inf if row["detour_none"] else row["detour_ratio"]),
                                         -row["edge_betweenness"], row["link_id"]))[:20]
    for title, rows, measure in (("Top 20 bridges by cut_side_nodes", bridges, "cut_side_nodes"),
                                 ("Top 20 non-bridges by detour ratio", nonbridges, "detour_ratio")):
        lines.extend(["", title, f"link_id | {measure} | name | highway | first OSM way ID"])
        for row in rows:
            value = "inf" if measure == "detour_ratio" and row["detour_none"] else f"{row[measure]:g}"
            lines.append(f"{row['link_id']} | {value} | {row['name'] or '-'} | "
                         f"{row['highway'] or '-'} | {row['osm_way_ids'].split(',')[0] or '-'}")
        if not rows:
            lines.append("(none)")
    return lines
