"""Cumulative directed attacks and reproducible random-failure experiments."""

import csv
import math
from dataclasses import dataclass
from time import perf_counter

import networkit as nk
import numpy as np
from scipy.sparse.csgraph import connected_components

from .progress import StageProgress
from .removal import ActiveEdgeGraph, node_weights
from .shortest_paths import ShortestPathEngine


CURVE_COLUMNS = ("element", "mode", "run", "step", "f", "S_scc", "S_wcc", "E_rel")


@dataclass
class RobustnessResult:
    rows: list
    summary: dict
    # Per-step increments, not full graph snapshots. Node IDs here are indices
    # into the original node order; link IDs retain physical-link identities.
    removals: dict
    runtime_seconds: dict


@dataclass
class _SampleReducer:
    weights: np.ndarray

    def __call__(self, distances, sources):
        np.divide(1.0, distances, out=distances, where=distances > 0)
        # Each row is reduced independently so chunk boundaries cannot change
        # BLAS accumulation order when n_jobs or the memory budget changes.
        return np.array([np.sum(row * self.weights) for row in distances])


def removal_schedule(total, steps, f_max):
    """Spread the integer removal budget across steps, never exceeding f_max."""
    budget = min(total, math.floor(total * f_max + 1e-12))
    if total and budget / total > f_max:
        budget -= 1
    counts = np.rint(np.arange(steps + 1) * budget / steps).astype(int)
    return counts


def sampled_efficiency(graph, sources, weights, *, n_jobs, budget_bytes):
    total_weight = float(weights.sum())
    denominator = math.fsum(float(weights[s] * (total_weight - weights[s])) for s in sources)
    if denominator <= 0:
        return 0.0
    engine = ShortestPathEngine(graph, n_jobs=n_jobs, budget_bytes=budget_bytes)
    contributions = []
    for indices, values in engine.reduce(sources, _SampleReducer(weights), directed=True):
        contributions.extend(float(weights[source] * value) for source, value in zip(indices, values))
    return math.fsum(contributions) / denominator


def _measure(graph, removed_nodes, sources, weights, baseline, *, n_jobs, budget_bytes):
    n = graph.shape[0]
    keep = np.ones(n, dtype=bool)
    keep[list(removed_nodes)] = False
    fractions = []
    for connection in ("strong", "weak"):
        count, labels = connected_components(graph, directed=True, connection=connection)
        largest = np.bincount(labels[keep], minlength=count).max(initial=0)
        fractions.append(float(largest / n))
    estimate = sampled_efficiency(graph, sources, weights, n_jobs=n_jobs, budget_bytes=budget_bytes)
    relative = min(1.0, max(0.0, estimate / baseline)) if baseline > 0 else math.nan
    return {"S_scc": fractions[0], "S_wcc": fractions[1], "E_rel": relative}


def attack_scores(active, graph, element, remaining, removed_links, removed_nodes, metric, n_jobs):
    """Exact directed weighted betweenness; unique-neighbour degree is undirected."""
    if element == "nodes" and metric == "degree":
        undirected = graph.maximum(graph.T).tocsr()
        degree = np.diff(undirected.indptr)
        return {node: float(degree[node]) for node in remaining}
    nk.setNumberOfThreads(n_jobs)
    network = nk.Graph(graph.shape[0], weighted=True, directed=True)
    for u in range(graph.shape[0]):
        for offset in range(graph.indptr[u], graph.indptr[u + 1]):
            network.addEdge(u, int(graph.indices[offset]), float(graph.data[offset]))
    network.indexEdges()
    algorithm = nk.centrality.Betweenness(network, normalized=False, computeEdgeCentrality=element == "links")
    algorithm.run()
    if element == "nodes":
        values = algorithm.scores()
        return {node: float(values[node]) for node in remaining}
    # A CSR arc belongs to its shortest active physical link. Equal-length
    # parallel ties use the lowest link ID, consistently with Ticket 03.
    selected = {}
    for u, v, length, link_id in zip(active.rows, active.cols, active.lengths, active.link_ids):
        if link_id in removed_links or u in removed_nodes or v in removed_nodes:
            continue
        pair = (int(u), int(v))
        choice = (float(length), int(link_id))
        if pair not in selected or choice < selected[pair]:
            selected[pair] = choice
    values = algorithm.edgeScores()
    scores = dict.fromkeys(remaining, 0.0)
    for (u, v), (_, link_id) in selected.items():
        scores[link_id] = max(scores[link_id], float(values[network.edgeId(u, v)]))
    return scores


def _rank(scores):
    """Group numerical ties before ordering by ID, independent of thread sums."""
    ordered = sorted(scores, key=lambda item: (-scores[item], item))
    result = []
    start = 0
    while start < len(ordered):
        end = start + 1
        score = scores[ordered[start]]
        while end < len(ordered) and math.isclose(score, scores[ordered[end]], rel_tol=1e-12, abs_tol=1e-12):
            end += 1
        result.extend(sorted(ordered[start:end]))
        start = end
    return result


def normalized_auc(rows, measure, f_max):
    values = [row[measure] for row in rows]
    if not all(math.isfinite(value) for value in values):
        return None
    fractions = [row["f"] for row in rows]
    # When a fractional element cannot be removed, hold the last observation
    # constant to the requested horizon instead of shortening AUC's denominator.
    fractions.append(f_max)
    values.append(values[-1])
    area = math.fsum((right - left) * (a + b) / 2 for left, right, a, b in
                     zip(fractions, fractions[1:], values, values[1:]))
    return min(1.0, max(0.0, area / f_max))


def _failure_band(runs, steps):
    band = []
    for step in range(steps + 1):
        entry = {"step": step, "f": runs[0][step]["f"]}
        for measure in ("S_scc", "S_wcc", "E_rel"):
            values = np.array([run[step][measure] for run in runs])
            finite = values[np.isfinite(values)]
            stats = [float(np.mean(finite)), *map(float, np.quantile(finite, [.05, .95]))] if len(finite) else [None] * 3
            entry.update(zip((f"{measure}_mean", f"{measure}_p05", f"{measure}_p95"), stats))
        band.append(entry)
    return band


def compute_robustness(graph, links, config, *, seed, n_jobs, budget_bytes, weights=None):
    started = perf_counter()
    active = ActiveEdgeGraph(graph, links, directed=True)
    n = len(active.node_ids)
    if not n:
        raise ValueError("robustness requires a nonempty network")
    weights = node_weights(n, weights)
    # Fixed stream slots keep node/link failures unchanged if the other element
    # is disabled, reordered, or the failure-run count is increased.
    sample_seed, link_seed, node_seed = np.random.SeedSequence(seed).spawn(3)
    sources = np.sort(np.random.default_rng(sample_seed).choice(n, min(n, config.efficiency_sources), replace=False))
    original = active.csr()
    with StageProgress("Robustness baseline", 1) as progress:
        baseline = sampled_efficiency(original, sources, weights, n_jobs=n_jobs, budget_bytes=budget_bytes)
        baseline_state = _measure(original, set(), sources, weights, baseline, n_jobs=n_jobs, budget_bytes=budget_bytes)
        progress.advance()
    summary = {"parameters": config.model_dump(mode="json"), "seed": seed, "graph": "directed",
               "efficiency_convention": "inverse_distance", "original_node_count": n,
               "efficiency_sources_used": len(sources), "efficiency_exact": len(sources) == n,
               "efficiency_sample_node_ids": [str(active.node_ids[i]) for i in sources],
               "baseline_sampled_efficiency": baseline,
               "rounding": "cumulative nearest integer within floor(f_max * total); actual f; plateau to f_max for AUC"}
    rows, histories = [], {}
    elements = [element for element in ("links", "nodes") if element in config.removal]
    work = len(elements) * (config.failure_runs + 1) * (config.steps + 1)
    with StageProgress("Robustness steps", work) as progress:
        for element in elements:
            population = sorted(active.link_arcs) if element == "links" else list(range(n))
            counts = removal_schedule(len(population), config.steps, config.f_max)
            children = (link_seed if element == "links" else node_seed).spawn(config.failure_runs)
            experiments = [("attack", 0, None)] + [("failure", run + 1, child) for run, child in enumerate(children)]
            curves = []
            for mode, run, child in experiments:
                removed_links, removed_nodes = set(), set()
                remaining = set(population)
                current = original
                state = baseline_state
                order = (np.random.default_rng(child).permutation(population).tolist() if child is not None else None)
                increments, curve = [], []
                for step, count in enumerate(counts):
                    delta = count - (counts[step - 1] if step else 0)
                    batch = []
                    if delta:
                        if mode == "attack" and (order is None or config.adaptive):
                            scores = attack_scores(active, current, element, remaining, removed_links,
                                                   removed_nodes, config.node_attack_metric, n_jobs)
                            order = _rank(scores)
                        if mode == "attack" and config.adaptive:
                            batch = order[:delta]
                        else:
                            batch = order[count - delta:count]
                        remaining.difference_update(batch)
                        (removed_links if element == "links" else removed_nodes).update(batch)
                        current = active.csr(removed_links=removed_links, isolated_nodes=sorted(removed_nodes))
                        state = _measure(current, removed_nodes, sources, weights, baseline,
                                         n_jobs=n_jobs, budget_bytes=budget_bytes)
                    increments.append(tuple(map(int, batch)))
                    row = {"element": element, "mode": mode, "run": run, "step": step,
                           "f": float(count / len(population)) if population else 0.0, **state}
                    rows.append(row)
                    curve.append(row)
                    progress.advance()
                histories[(element, mode, run)] = increments
                curves.append(curve)
            attack, failures = curves[0], curves[1:]
            def mean_auc(measure):
                values = [normalized_auc(curve, measure, config.f_max) for curve in failures]
                return float(np.mean(values)) if all(value is not None for value in values) else None
            summary[element] = {
                "headline": element == "links", "auc_attack_S": normalized_auc(attack, "S_scc", config.f_max),
                "auc_attack_E": normalized_auc(attack, "E_rel", config.f_max),
                "auc_failure_S": mean_auc("S_scc"), "auc_failure_E": mean_auc("E_rel"),
                "f_half_attack": next((row["f"] for row in attack if row["S_scc"] < 0.5), None),
                "parameters": {**config.model_dump(mode="json"), "seed": seed, "total_elements": len(population),
                               "removed_count": int(counts[-1]), "actual_f_max": attack[-1]["f"],
                               "removals_per_step": np.diff(counts).tolist()},
                "attack_final": {key: (value if math.isfinite(value) else None) for key, value in
                                 attack[-1].items() if key in ("f", "S_scc", "S_wcc", "E_rel")},
                "failure_band": _failure_band(failures, config.steps),
            }
    return RobustnessResult(rows, summary, histories, {"robustness": perf_counter() - started})


def write_curves(result, path):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CURVE_COLUMNS)
        writer.writeheader()
        for row in result.rows:
            writer.writerow({key: "" if isinstance(value, float) and not math.isfinite(value) else value
                             for key, value in row.items()})


def robustness_report(summary):
    lines = ["Robustness", "Directed cumulative removals; original N and fixed source sample retained.",
             f"Efficiency sources: {summary['efficiency_sources_used']}; "
             f"{'exact all-source' if summary['efficiency_exact'] else 'sampled estimate'}; mean(1/d).",
             "Element          Attack AUC(S)  Failure AUC(S)  Attack AUC(E)  Failure AUC(E)"]
    for element in ("links", "nodes"):
        if element not in summary:
            continue
        data = summary[element]
        label = "links (headline)" if element == "links" else "nodes"
        values = [data[key] for key in ("auc_attack_S", "auc_failure_S", "auc_attack_E", "auc_failure_E")]
        lines.append(f"{label:<17}" + " ".join(f"{value:>14.6g}" if value is not None else f"{'N/A':>14}" for value in values))
        final = data["attack_final"]
        lines.append(f"Targeted removal of {100 * final['f']:.6g}% of {element} reduces the largest "
                     f"connected component to {100 * final['S_scc']:.6g}% (strongly connected).")
        lines.append(f"  First S_scc < 0.5: {data['f_half_attack'] if data['f_half_attack'] is not None else 'not reached'}")
    lines.extend([f"Adaptive attack: {summary['parameters']['adaptive']}; "
                  f"node metric: {summary['parameters']['node_attack_metric']}; failure band: 5-95% across runs.",
                  "Fractions use actual integer removals; AUC holds the last value to requested f_max.",
                  "Removed sampled sources remain in the efficiency denominator and contribute zero."])
    return lines
