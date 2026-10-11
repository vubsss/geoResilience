"""Ticket 11: directed, truncated exponential Hansen accessibility.

Destination masses enter A_i; origin masses do not weight the network sum.
All distances are road metres. Radius truncation is part of the definition.
"""

from dataclasses import dataclass
from itertools import combinations
import math
from time import perf_counter

import numpy as np

from .centralities import describe
from .progress import StageProgress
from .removal import ActiveEdgeGraph, AffectedSourceRecompute, node_weights, removal_engine


def _kernel(distances, sources, beta, radius):
    # Reuse the distance block; unreachable/outside-radius contributions are 0.
    distances[~np.isfinite(distances) | (distances > radius)] = np.inf
    with np.errstate(over="ignore"):
        np.multiply(distances, -beta, out=distances)
    np.exp(distances, out=distances)
    distances[np.arange(len(sources)), sources] = 0.0
    return distances


@dataclass
class AccessibilityReducer:
    weights: np.ndarray
    beta: float
    radius: float

    def __call__(self, distances, sources):
        return _kernel(distances, sources, self.beta, self.radius) @ self.weights


@dataclass
class ReverseBridgeReducer:
    weights: np.ndarray
    outside: np.ndarray
    beta: float
    radius: float

    def __call__(self, distances, sources):
        # Reverse rows from s give d(i,s); the destination mass is W_s.
        kernel = _kernel(distances, sources, self.beta, self.radius)
        kernel *= self.weights[sources, None]
        result = kernel.sum(axis=0)
        result[~self.outside] = 0.0
        return result


def accessibility_baseline(active, weights, beta, radius, *, n_jobs, budget_bytes):
    values = np.zeros(len(active.node_ids))
    engine = removal_engine(active.csr(), n_jobs, budget_bytes)
    reducer = AccessibilityReducer(weights, beta, radius)
    with StageProgress("Accessibility baseline sources", len(values)) as progress:
        for sources, block in engine.reduce(np.arange(len(values)), reducer, directed=True, limit=radius):
            values[sources] = block
            for _ in sources:
                progress.advance()
    return values


def link_accessibility_loss(recompute, baseline, link_id, reducer):
    sources = recompute.affected_sources(link_id, limit=reducer.radius)
    loss = np.zeros(len(baseline))
    for indices, changed in recompute.recompute([link_id], sources, reducer, limit=reducer.radius):
        loss[indices] = np.clip(baseline[indices] - changed, 0, baseline[indices])
    return loss, len(sources)


def bridge_accessibility_loss(recompute, link_id, reducer):
    """Exact directed cross-cut losses, using only small-side truncated rows."""
    side = recompute.bridge_side(link_id)
    n = len(reducer.weights)
    outside = np.ones(n, dtype=bool)
    outside[side] = False
    loss = np.zeros(n)
    forward = AccessibilityReducer(reducer.weights * outside, reducer.beta, reducer.radius)
    reverse = ReverseBridgeReducer(reducer.weights, outside, reducer.beta, reducer.radius)
    for graph, reduction, reversed_graph in ((recompute.graph, forward, False),
                                             (recompute.reverse, reverse, True)):
        engine = removal_engine(graph, recompute.n_jobs, recompute.budget_bytes)
        for sources, values in engine.reduce(side, reduction, directed=True, limit=reducer.radius):
            if reversed_graph:
                loss += values
            else:
                loss[sources] = values
    return loss, len(side)


class StreamingTopThree:
    """O(N) state; ties retain the smaller link ID (updates arrive in ID order)."""

    def __init__(self, valid):
        self.valid = valid
        self.scores = np.full((len(valid), 3), -np.inf)
        self.links = np.full((len(valid), 3), -1, dtype=np.int64)

    def update(self, link_id, drops):
        better = drops[:, None] > self.scores
        insert = self.valid & better.any(axis=1)
        positions = better.argmax(axis=1)
        for column in (2, 1, 0):
            if column:
                shift = insert & (positions < column)
                self.scores[shift, column] = self.scores[shift, column - 1]
                self.links[shift, column] = self.links[shift, column - 1]
            here = insert & (positions == column)
            self.scores[here, column] = drops[here]
            self.links[here, column] = link_id


@dataclass
class AccessibilityResult:
    node_metrics: dict
    link_metrics: dict
    summary: dict
    top_links: dict
    runtime_seconds: dict
    computation: dict


def compute_accessibility(graph, links, screening, config, *, n_jobs, budget_bytes, weights=None):
    started = perf_counter()
    if n_jobs < 1 or budget_bytes < 1:
        raise ValueError("accessibility jobs and memory budget must be positive")
    active = ActiveEdgeGraph(graph, links, directed=True)
    n = len(active.node_ids)
    masses = node_weights(n, weights)
    beta = math.log(2) / (config.half_distance_km * 1000)
    radius = (config.half_distance_km * 1000) * config.cutoff_factor
    # Baseline, top-three state, endpoint columns, losses and graph storage.
    fixed_bytes = 160 * n + 64 * len(active.rows)
    working_bytes = budget_bytes - fixed_bytes
    row_bytes = max(1, n * 8 * 8)
    if working_bytes < row_bytes:
        raise ValueError("analysis.max_memory_gb is too small for accessibility working arrays")
    jobs = min(n_jobs, max(1, n), max(1, working_bytes // row_bytes))
    reducer = AccessibilityReducer(masses, beta, radius)
    baseline = accessibility_baseline(active, masses, beta, radius, n_jobs=jobs, budget_bytes=working_bytes)
    baseline_done = perf_counter()
    total = float(baseline.sum())
    valid = baseline > 0
    top = StreamingTopThree(valid)
    eligible = {row["link_id"] for row in links if not row["is_self_loop"]}
    evaluated = (eligible if config.all_links else
                 eligible & (screening.candidate_links | screening.analytic_bridges))
    analytic = evaluated & screening.analytic_bridges
    recompute = AffectedSourceRecompute(active, n_jobs=jobs, budget_bytes=working_bytes)
    link_metrics = {row["link_id"]: {"access_drop": math.nan, "access_rank": None,
                    "access_method": "not_evaluated"} for row in links}
    affected_count, small_side_rows = 0, 0
    with StageProgress("Accessibility link removals", len(evaluated)) as progress:
        for link_id in sorted(evaluated):
            if link_id in analytic:
                loss, size = bridge_accessibility_loss(recompute, link_id, reducer)
                loss = np.clip(loss, 0, baseline)
                small_side_rows += 2 * size
                method = "analytic_bridge"
            else:
                loss, count = link_accessibility_loss(recompute, baseline, link_id, reducer)
                affected_count += count
                method = "affected_sources"
            relative = np.divide(loss, baseline, out=np.zeros(n), where=valid)
            top.update(link_id, relative)
            link_metrics[link_id] = {"access_drop": float(np.clip(loss.sum() / total, 0, 1))
                                     if total > 0 else math.nan,
                                     "access_rank": None, "access_method": method}
            progress.advance()
    removals_done = perf_counter()
    ranked = sorted((key for key in evaluated if math.isfinite(link_metrics[key]["access_drop"])),
                    key=lambda key: (-link_metrics[key]["access_drop"], key))
    for rank, key in enumerate(ranked, 1):
        link_metrics[key]["access_rank"] = rank
    node_metrics, top_links = {}, {}
    pair_trials = 0
    with StageProgress("Accessibility node pair tests", n if config.k == 2 else 0) as progress:
        for index, node in enumerate(active.node_ids):
            selected = [int(link) for link in top.links[index] if link >= 0]
            top_links[node] = selected
            has_single = valid[index] and bool(selected)
            values = {"hansen_a": float(baseline[index]),
                      "vuln": float(top.scores[index, 0]) if has_single else math.nan,
                      "vuln_link_id": selected[0] if has_single else None,
                      "isolated_in_R": not bool(valid[index]),
                      "access_top3_link_ids": ";".join(map(str, selected))}
            if config.k == 2:
                best, winning = math.nan, None
                for pair in combinations(selected, 2):
                    for _, changed in recompute.recompute(pair, np.array([index]), reducer, limit=radius):
                        drop = float(np.clip((baseline[index] - changed[0]) / baseline[index], 0, 1))
                    if winning is None or drop > best:
                        best, winning = drop, pair
                    pair_trials += 1
                values.update(vuln_k2=best, vuln_k2_link_ids=";".join(map(str, winning)) if winning else None)
                progress.advance()
            node_metrics[node] = values
    finished = perf_counter()
    vulnerability = describe([row["vuln"] for row in node_metrics.values()])
    node_order = {node: index for index, node in enumerate(active.node_ids)}
    ranked_nodes = sorted((node for node, row in node_metrics.items() if math.isfinite(row["vuln"])),
                          key=lambda node: (-node_metrics[node]["vuln"], node_order[node]))
    scope = "all non-self-loop physical links" if config.all_links else "screening candidates plus analytic bridges"
    summary = {"definition": "sum of destination W_j * exp(-beta*d_ij), j != i, outbound d_ij <= R",
               "beta_per_m": beta, "radius_m": radius, "half_distance_km": config.half_distance_km,
               "cutoff_factor": config.cutoff_factor, "directed": True, "self_term": "excluded",
               "cutoff": "inclusive; truncation is part of the definition",
               "mass_convention": "uniform unit destination masses (structural accessibility)"
                    if np.all(masses == 1) else "supplied destination masses",
               "destination_mass_total": float(masses.sum()), "origin_aggregation": "unweighted sum of A_i",
               "total_accessibility": total, "mean_accessibility": float(baseline.mean()) if n else None,
               "vuln": vulnerability, "isolated_in_R_count": int((~valid).sum()),
               "undefined_vulnerability_count": sum(not math.isfinite(row["vuln"]) for row in node_metrics.values()),
               "k": config.k, "all_links": config.all_links, "vulnerability_scope": scope,
               "links_evaluated": len(evaluated), "evaluated_link_ids": sorted(evaluated),
               "counts_by_method": {"analytic_bridge": len(analytic), "affected_sources": len(evaluated - analytic)},
               "k2_scope": "pairs from each node's top three evaluated single-link drops; not the global worst pair",
               "k2_pair_trials": pair_trials,
               "top20_links": [{"link_id": key, **link_metrics[key]} for key in ranked[:20]],
               "top20_nodes": [{"node_id": str(node), "vuln": node_metrics[node]["vuln"],
                                 "vuln_link_id": node_metrics[node]["vuln_link_id"]} for node in ranked_nodes[:20]]}
    if config.k == 2:
        summary["vuln_k2"] = describe([row["vuln_k2"] for row in node_metrics.values()])
    return AccessibilityResult(node_metrics, link_metrics, summary, top_links,
        {"accessibility_baseline": baseline_done - started, "accessibility_links": removals_done - baseline_done,
         "accessibility_pairs": finished - removals_done, "accessibility_total": finished - started},
        {"accessibility_workers": int(jobs), "accessibility_fixed_bytes_estimate": fixed_bytes,
         "accessibility_affected_source_rows": affected_count, "accessibility_analytic_source_rows": small_side_rows,
         "accessibility_top_links_per_node": 3})


def accessibility_report(summary):
    lines = ["Accessibility", f"Masses: {summary['mass_convention']}",
             "Directed outbound road distances in metres; self excluded; inclusive cutoff is part of the definition.",
             f"Half-distance: {summary['half_distance_km']:g} km; beta: {summary['beta_per_m']:.9g} per metre; "
             f"R: {summary['radius_m']:g} m (cutoff factor {summary['cutoff_factor']:g}).",
             f"Total A: {summary['total_accessibility']:.9g}; mean A: {summary['mean_accessibility']}",
             f"vuln mean: {summary['vuln']['mean']}; p90: {summary['vuln']['p90']}",
             f"Links evaluated: {summary['links_evaluated']}; methods: {summary['counts_by_method']}",
             f"Single-link vulnerability scope: {summary['vulnerability_scope']}.",
             f"Nodes with A=0 (isolated_in_R): {summary['isolated_in_R_count']}; "
             f"undefined vulnerability: {summary['undefined_vulnerability_count']}.",
             "Undefined vulnerability is NaN in layers (null in summaries); also undefined if no links were evaluated."]
    if summary["k"] == 2:
        lines.extend([f"k=2 scope: {summary['k2_scope']}.",
                      f"Pair trials: {summary['k2_pair_trials']}; vuln_k2 mean: {summary['vuln_k2']['mean']}; "
                      f"p90: {summary['vuln_k2']['p90']}",
                      "vuln_k2 is undefined when fewer than two evaluated links are available."])
    lines.extend(["Top 20 critical accessibility links: link_id | access_drop | access_rank | method"])
    lines.extend(f"{row['link_id']} | {row['access_drop']:.9g} | {row['access_rank']} | {row['access_method']}"
                 for row in summary["top20_links"])
    lines.append("Top 20 vulnerable nodes: node_id | vuln | vuln_link_id")
    lines.extend(f"{row['node_id']} | {row['vuln']:.9g} | {row['vuln_link_id']}" for row in summary["top20_nodes"])
    return lines
