"""Exact single-link damage and fixed-node-set information centrality."""

import math
from dataclasses import dataclass
from time import perf_counter

import numpy as np

from .centralities import describe
from .progress import StageProgress as _Progress
from .removal import (ActiveEdgeGraph, AffectedSourceRecompute, BaselineDistances, InverseReducer,
                      analytic_bridge_damage, full_link_damage, node_weights, removal_engine)
from .shortest_paths import aggregate_efficiency


DAMAGE_FIELDS = ("eff_drop", "disc_pair_frac", "extra_km_total", "affected_pairs", "extra_m_mean_affected")


@dataclass
class CriticalityResult:
    link_metrics: dict
    information: dict
    summary: dict
    information_summary: dict
    computation: dict
    runtime_seconds: dict


def _json_value(value):
    if isinstance(value, (float, np.floating)) and not math.isfinite(value):
        return None
    return value


def information_centrality(active, candidates, *, n_jobs, budget_bytes, weights=None,
                           baseline_efficiency=None):
    """Deactivate all incident edges; retain all N nodes and the pair denominator."""
    n = len(active.node_ids)
    weights = node_weights(n, weights)
    reducer = InverseReducer(weights)
    if baseline_efficiency is None:
        sums = np.zeros(n)
        engine = removal_engine(active.csr(), n_jobs, budget_bytes)
        for sources, values in engine.reduce(np.arange(n), reducer, directed=True):
            sums[sources] = values
        baseline_efficiency = aggregate_efficiency(sums, weights)
    information = dict.fromkeys(active.node_ids, math.nan)
    selected = [node for node in active.node_ids if node in candidates]
    with _Progress("Information nodes", len(selected)) as progress:
        for node in selected:
            sums = np.zeros(n)
            modified = active.csr(isolated_nodes=[active.index[node]])
            engine = removal_engine(modified, n_jobs, budget_bytes)
            # Parallelise source chunks even when the small graph fits in one
            # budget-sized block; no nested per-node/process parallelism.
            engine.chunk_rows = min(engine.chunk_rows, max(1, math.ceil(n / n_jobs)))
            for sources, values in engine.reduce(np.arange(n), reducer, directed=True):
                sums[sources] = values
            changed = aggregate_efficiency(sums, weights)
            information[node] = (max(0.0, (baseline_efficiency - changed) / baseline_efficiency)
                                 if baseline_efficiency > 0 else math.nan)
            progress.advance()
    return information, {
        "coverage": "all" if len(selected) == n else "candidates", "candidate_count": len(selected),
        "baseline_efficiency": baseline_efficiency, "efficiency_convention": "inverse_distance",
        "graph": "undirected", "statistics": describe(list(information.values())),
    }


def compute_criticality(graph, links, screening, *, n_jobs, budget_bytes, directed=True,
                        weights=None, cache=None, undirected_efficiency=None, population_weights=None):
    started = perf_counter()
    active = ActiveEdgeGraph(graph, links, directed=directed)
    recompute = AffectedSourceRecompute(active, n_jobs=n_jobs, budget_bytes=budget_bytes)
    evaluated = screening.candidate_links | screening.analytic_bridges
    metrics = {row["link_id"]: {**dict.fromkeys(DAMAGE_FIELDS, math.nan),
                               "damage_method": None, "crit_rank": math.nan} for row in links}
    if population_weights is not None:
        for values in metrics.values():
            values.update(eff_drop_pop=math.nan, disc_pair_frac_pop=math.nan, people_disconnected=math.nan)
    methods = {"full": 0, "analytic": 0}
    affected_sources_total = 0
    with _Progress("Removal baseline", 1) as progress:
        baseline = BaselineDistances(recompute.graph, n_jobs=n_jobs, budget_bytes=budget_bytes,
                                     weights=weights, cache=cache, population_weights=population_weights)
        progress.advance()
    baseline_done = perf_counter()
    with baseline:
        recompute.budget_bytes = baseline.working_budget_bytes
        computation = {"criticality_baseline": "cached" if baseline.cache is not None else "recomputed",
                       "criticality_cache_bytes": baseline.cache.nbytes if baseline.cache is not None else 0,
                       "criticality_working_budget_bytes": baseline.working_budget_bytes}
        baseline_efficiency = baseline.efficiency
        with _Progress("Link damage", len(evaluated)) as progress:
            for row in sorted(links, key=lambda row: row["link_id"]):
                link_id = row["link_id"]
                if link_id not in evaluated:
                    continue
                if link_id in screening.analytic_bridges:
                    values = analytic_bridge_damage(recompute, baseline, link_id)
                    method = "analytic"
                else:
                    values, sources = full_link_damage(recompute, baseline, link_id)
                    affected_sources_total += sources
                    method = "full"
                metrics[link_id].update(values, damage_method=method)
                methods[method] += 1
                progress.advance()
    links_done = perf_counter()
    ranked = sorted((row for row in links if row["link_id"] in evaluated
                     and math.isfinite(metrics[row["link_id"]]["eff_drop"])), key=lambda row: (
        -metrics[row["link_id"]]["eff_drop"], -metrics[row["link_id"]]["disc_pair_frac"], row["link_id"]))
    for rank, row in enumerate(ranked, start=1):
        metrics[row["link_id"]]["crit_rank"] = rank
    top = []
    for row in ranked[:20]:
        entry = {key: row.get(key) for key in ("link_id", "name", "highway", "candidate_reason")}
        entry["first_osm_way_id"] = row["osm_way_ids"].split(",")[0] or None
        entry.update({key: _json_value(value) for key, value in metrics[row["link_id"]].items()})
        top.append(entry)
    summary = {
        "graph": "directed" if directed else "undirected", "efficiency_convention": "inverse_distance",
        "node_weights": "uniform" if weights is None else "provided",
        "baseline_efficiency": baseline_efficiency, "evaluated_link_count": len(evaluated),
        "counts_by_method": methods, "unevaluated_link_count": sum(
            not row["is_self_loop"] and row["link_id"] not in evaluated for row in links),
        "top_20": top,
        "totals": {"eff_drop_sum": sum(metrics[key]["eff_drop"] for key in evaluated),
                   "disc_pair_frac_sum": sum(metrics[key]["disc_pair_frac"] for key in evaluated),
                   "extra_km_total": sum(metrics[key]["extra_km_total"] for key in evaluated),
                   "affected_pairs": sum(metrics[key]["affected_pairs"] for key in evaluated)},
    }
    summary["totals"] = {key: _json_value(value) for key, value in summary["totals"].items()}
    if population_weights is not None:
        summary["baseline_efficiency_pop"] = _json_value(baseline.efficiency_pop)
        for name in ("eff_drop_pop", "disc_pair_frac_pop"):
            summary["totals"][name + "_sum"] = _json_value(sum(metrics[key][name] for key in evaluated))
    computation["criticality_affected_sources_total"] = affected_sources_total
    undirected = active if not directed else ActiveEdgeGraph(graph, links, directed=False)
    # Only reuse the unweighted Ticket 03 baseline when no weights were supplied.
    information, info_summary = information_centrality(
        undirected, screening.candidate_nodes, n_jobs=n_jobs, budget_bytes=budget_bytes, weights=weights,
        baseline_efficiency=undirected_efficiency if weights is None else None)
    finished = perf_counter()
    return CriticalityResult(metrics, information, summary, info_summary, computation,
                             {"criticality_baseline": baseline_done - started,
                              "criticality_links": links_done - baseline_done,
                              "information": finished - links_done, "criticality_total": finished - started})


def criticality_report(criticality, information):
    methods = criticality["counts_by_method"]
    lines = ["Critical links", f"Removal graph: {criticality['graph']}; {criticality['node_weights']} node weights",
             f"Baseline efficiency (1/metres): {criticality['baseline_efficiency']:.9g}",
             f"Evaluated links: {criticality['evaluated_link_count']} "
             f"(full={methods['full']}, analytic={methods['analytic']}); "
             f"unevaluated={criticality['unevaluated_link_count']}",
             "Ranking: descending eff_drop, then disc_pair_frac, then ascending link_id",
             "Totals over independent single-road closures (not a simultaneous-closure result):"]
    lines.extend(f"  {name}: {value}" for name, value in criticality["totals"].items())
    lines.extend(["", "Top 20 critical links by eff_drop",
                  "link_id | name | highway | first_osm_way_id | eff_drop | disc_pair_frac | extra_km_total | candidate_reason"])
    for row in criticality["top_20"]:
        values = " | ".join(f"{row[key]:.9g}" if row[key] is not None else "N/A"
                            for key in ("eff_drop", "disc_pair_frac", "extra_km_total"))
        lines.append(f"{row['link_id']} | {row['name'] or '-'} | {row['highway'] or '-'} | "
                     f"{row['first_osm_way_id'] or '-'} | {values} | {row['candidate_reason'] or '-'}")
    if not criticality["top_20"]:
        lines.append("(none)")
    if "baseline_efficiency_pop" in criticality:
        lines.extend(["", f"Population-weighted baseline efficiency: {criticality['baseline_efficiency_pop']}",
                      "Population columns for the same critical links:",
                      "link_id | eff_drop_pop | disc_pair_frac_pop | people_disconnected"])
        for row in criticality["top_20"]:
            lines.append(f"{row['link_id']} | {row['eff_drop_pop']} | {row['disc_pair_frac_pop']} | "
                         f"{row['people_disconnected']}")
        lines.append("people_disconnected is the population of the smaller node-count side of an analytic bridge; "
                     "undefined for other closures. Pair fractions cannot be converted directly to persons.")
    lines.extend(["", "Information centrality", f"Coverage: {information['coverage']}; "
                  f"candidate count: {information['candidate_count']}",
                  "Undirected graph; all incident edges removed, original N retained.",
                  "Efficiency convention: mean(1/d), not AP2 spatial mean(d_E/d).",
                  f"Baseline efficiency (1/metres): {information['baseline_efficiency']:.9g}",
                  "Statistics: " + ", ".join(f"{key}={value}" for key, value in information["statistics"].items())])
    return lines
