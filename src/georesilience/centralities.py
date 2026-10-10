"""Exact metric centralities on the minimum-length undirected link graph."""

from dataclasses import dataclass
from threading import Event, Thread
from time import perf_counter

import networkit as nk
import numpy as np
from scipy.sparse import csr_matrix

from .network import _log
from .shortest_paths import CentralityReducer, GIB, ShortestPathEngine, aggregate_efficiency, resolve_resources


@dataclass
class AnalysisGraph:
    node_ids: list
    coordinates: np.ndarray
    csr: csr_matrix
    # (node index, node index) -> physical link which supplies the minimum.
    edge_links: dict


def build_analysis_graph(graph, links):
    node_ids = list(graph.nodes)
    index = {node: i for i, node in enumerate(node_ids)}
    coordinates = np.array([(graph.nodes[node]["x"], graph.nodes[node]["y"])
                            for node in node_ids], dtype=float).reshape(-1, 2)
    selected = {}
    for link in links:
        if link["is_self_loop"]:
            continue
        length = link["length_m"]
        if not np.isfinite(length) or length <= 0:
            raise ValueError(f"link {link['link_id']}: length_m must be finite and positive")
        pair = tuple(sorted((index[link["_u"]], index[link["_v"]])))
        candidate = (length, link["link_id"])
        if pair not in selected or candidate < selected[pair]:
            selected[pair] = candidate
    rows, cols, lengths = [], [], []
    for (u, v), (length, _) in selected.items():
        rows.extend((u, v))
        cols.extend((v, u))
        lengths.extend((length, length))
    csr = csr_matrix((lengths, (rows, cols)), shape=(len(node_ids), len(node_ids)), dtype=float)
    csr.sort_indices()
    return AnalysisGraph(node_ids, coordinates, csr,
                         {pair: link_id for pair, (_, link_id) in selected.items()})


def exact_betweenness(analysis, links, n_jobs):
    n = len(analysis.node_ids)
    nk.setNumberOfThreads(n_jobs)
    graph = nk.Graph(n, weighted=True, directed=False)
    for u, v in analysis.edge_links:
        graph.addEdge(u, v, float(analysis.csr[u, v]))
    graph.indexEdges()
    algorithm = nk.centrality.Betweenness(
        graph, normalized=False, computeEdgeCentrality=True,
    )
    stopped = Event()
    started = perf_counter()

    def progress():
        while not stopped.wait(30):
            _log(f"Exact betweenness still running ({perf_counter() - started:.0f} seconds elapsed)")

    heartbeat = Thread(target=progress, daemon=True)
    heartbeat.start()
    try:
        algorithm.run()
    finally:
        stopped.set()
        heartbeat.join()
    # NetworKit's unnormalised undirected scores count ORDERED pairs.
    node_scores = np.asarray(algorithm.scores(), dtype=float)
    node_scores = node_scores / ((n - 1) * (n - 2)) if n > 2 else np.zeros(n)
    edge_scores = np.asarray(algorithm.edgeScores(), dtype=float)
    values = {row["link_id"]: (np.nan if row["is_self_loop"] else 0.0) for row in links}
    for (u, v), link_id in analysis.edge_links.items():
        values[link_id] = float(edge_scores[graph.edgeId(u, v)] / (n * (n - 1))) if n > 1 else 0.0
    return node_scores, values


def describe(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if not values.size:
        return dict.fromkeys(("mean", "median", "p90", "max"), None)
    return {"mean": float(np.mean(values)), "median": float(np.median(values)),
            "p90": float(np.percentile(values, 90)), "max": float(np.max(values))}


def compute_centralities(graph, links, config):
    if config.directed_centrality:
        raise NotImplementedError("analysis.directed_centrality: true is planned; use false for Ticket 03")
    start = perf_counter()
    n_jobs, budget = resolve_resources(config.n_jobs, config.max_memory_gb)
    analysis = build_analysis_graph(graph, links)
    prepared = perf_counter()
    n = len(analysis.node_ids)
    engine = ShortestPathEngine(analysis.csr, n_jobs=n_jobs, budget_bytes=budget)
    _log(f"Exact shortest paths: {n} sources, up to {min(n, engine.chunk_rows)} rows/chunk, {n_jobs} jobs")
    reducer = CentralityReducer(analysis.coordinates)
    values = np.zeros((n, 3))
    chunks_done = 0
    last_log = perf_counter()
    for sources, reduced in engine.reduce(np.arange(n), reducer):
        values[sources] = reduced
        chunks_done += 1
        if perf_counter() - last_log >= 10:
            _log(f"Shortest paths: {min(chunks_done * engine.chunk_rows, n)}/{n} sources reduced")
            last_log = perf_counter()
    paths_done = perf_counter()
    _log(f"Exact node and link betweenness ({n_jobs} NetworKit threads)")
    betweenness, edge_betweenness = exact_betweenness(analysis, links, n_jobs)
    finished = perf_counter()
    _log(f"Centralities completed in {finished - start:.3f} seconds")
    node_metrics = {"closeness": values[:, 0], "straightness": values[:, 1], "betweenness": betweenness}
    efficiency = aggregate_efficiency(values[:, 2], reducer.weights)
    statistics = {name: describe(scores) for name, scores in node_metrics.items()}
    statistics["edge_betweenness"] = describe(list(edge_betweenness.values()))
    statistics["global_efficiency"] = efficiency
    statistics["runtime_seconds"] = {
        "analysis_graph": prepared - start, "shortest_paths": paths_done - prepared,
        "betweenness": finished - paths_done, "centralities_total": finished - start,
    }
    return analysis, node_metrics, edge_betweenness, statistics, {
        "n_jobs": n_jobs,
        "max_memory_gb": budget / GIB if config.max_memory_gb == "auto" else config.max_memory_gb,
        "memory_budget_bytes": budget,
        "chunk_rows": engine.chunk_rows, "shortest_path_chunks": chunks_done,
    }


def centrality_report(statistics, links):
    lines = ["Centralities", "Measure                  Mean       Median          P90          Max"]
    for name in ("closeness", "straightness", "betweenness", "edge_betweenness"):
        row = statistics[name]
        lines.append(f"{name:<20} " + " ".join(f"{row[key]:>12.6g}" if row[key] is not None else f"{'N/A':>12}"
                                              for key in ("mean", "median", "p90", "max")))
    lines.append(f"Global efficiency (1/metres): {statistics['global_efficiency']:.9g}")
    lines.append("Closeness units: 1/metres; straightness and betweenness: dimensionless")
    lines.append("Runtime (seconds):")
    lines.extend(f"  {name}: {seconds:.3f}" for name, seconds in statistics["runtime_seconds"].items())
    lines.extend(["", "Top 20 links by edge betweenness", "link_id | name | highway | first_osm_way_id | edge_betweenness"])
    active = [row for row in links if np.isfinite(row["edge_betweenness"])]
    active.sort(key=lambda row: (-row["edge_betweenness"], row["link_id"]))
    for row in active[:20]:
        lines.append(f"{row['link_id']} | {row['name'] or '-'} | {row['highway'] or '-'} | "
                     f"{row['osm_way_ids'].split(',')[0] or '-'} | {row['edge_betweenness']:.9g}")
    return lines
