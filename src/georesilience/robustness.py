"""One deterministic physical-link attack with paired SCC-share curves."""

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import numpy as np

from .links import node_key
from .metrics import _structural, score
from .service_metrics import ServiceUniverse

CURVE_COLUMNS = ("fraction_removed", "links_removed", "node_share", "population_share", "removed_link_uid")


@dataclass
class AttackResult:
    curve: list[dict]
    summary: dict
    removal_order: list[str]


def _largest_component(graph):
    components = nx.strongly_connected_components(graph)
    return min(components, key=lambda component: (
        -len(component), tuple(sorted(node_key(node) for node in component))), default=set())


def compute_targeted_attack(graph, links, population, fraction=.20, steps=50, order="adaptive", seed=42, *, service_weights=None):
    """Remove floor(fraction * M) links; recompute adaptive rank after each link.

    Export at most ``steps`` post-removal points and integrate only that exported
    curve, to its actual integer-removal horizon. Population uses the same SCC
    selected by node count, with canonical node IDs breaking component ties.
    """
    if not math.isfinite(fraction) or not 0 <= fraction <= 1:
        raise ValueError("attack fraction must be finite and in [0,1]")
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise ValueError("attack steps must be a positive integer")
    if order not in {"adaptive", "static"}:
        raise ValueError("attack order must be adaptive or static")
    population = np.asarray(population, dtype=float)
    original_nodes = list(graph)
    if population.shape != (len(original_nodes),) or not np.isfinite(population).all() or (population < 0).any():
        raise ValueError("population must be finite, nonnegative and match original nodes")
    total_population = float(population.sum())
    if not math.isfinite(total_population):
        raise ValueError("total population must be finite")
    node_population = dict(zip(original_nodes, population))
    services = ServiceUniverse(population, service_weights) if service_weights is not None else None
    node_services = dict(zip(original_nodes, services.destinations)) if services is not None else {}
    active = sorted((row for row in links if not row["is_self_loop"]),
                    key=lambda row: (row["link_uid"], row["link_id"]))
    if (len({row["link_uid"] for row in active}) != len(active)
            or len({row["link_id"] for row in active}) != len(active)):
        raise ValueError("attack requires unique physical-link IDs")
    arcs = [arc for row in active for arc in row["_edges"]]
    if len(set(arcs)) != len(arcs) or any(not graph.has_edge(*arc) for arc in arcs):
        raise ValueError("attack physical links must contain distinct existing arcs")
    if any(not math.isfinite(row["length_m"]) or row["length_m"] <= 0 for row in active):
        raise ValueError("attack physical-link lengths must be finite and positive")
    # Canonical insertion order makes floating point betweenness summation and
    # tie selection independent of the input graph's iteration order.
    damaged = nx.MultiDiGraph()
    damaged.add_nodes_from(sorted(original_nodes, key=node_key))
    damaged.add_edges_from(arcs)
    structural_nodes = nx.Graph()
    structural_nodes.add_nodes_from(damaged)
    total_links = len(active)
    horizon = min(total_links, math.floor(fraction * total_links))
    reported_steps = min(steps, horizon)
    sample_counts = {((i * horizon + reported_steps - 1) // reported_steps)
                     for i in range(1, reported_steps + 1)}
    actual_fraction = horizon / total_links if total_links else 0.0
    n = len(original_nodes)
    curve = []
    removal_order = []

    def record(removed, last_uid=None):
        component = _largest_component(damaged)
        people = math.fsum(float(node_population[node]) for node in sorted(component, key=node_key))
        curve.append({"fraction_removed": removed / total_links if total_links else 0.0,
            "links_removed": removed, "node_share": len(component) / n if n else None,
            "population_share": people / total_population if total_population else None,
            "removed_link_uid": last_uid})
        if services is not None:
            curve[-1]["service_share"] = (math.fsum(float(node_services[node]) for node in sorted(component, key=node_key))
                if services.service_total else None)

    def ranked(rows):
        _, scores, _, _ = _structural(structural_nodes, rows)
        return sorted(rows, key=lambda row: (-scores[row["link_id"]], row["link_uid"], row["link_id"]))

    record(0)
    static_order = ranked(active) if horizon and order == "static" else None
    for removed in range(1, horizon + 1):
        chosen = ranked(active)[0] if order == "adaptive" else static_order[removed - 1]
        damaged.remove_edges_from(chosen["_edges"])
        active.remove(chosen)
        removal_order.append(chosen["link_uid"])
        if removed in sample_counts:
            record(removed, chosen["link_uid"])
    x = [row["fraction_removed"] for row in curve]
    node_auc = float(np.trapezoid([row["node_share"] for row in curve], x)) if horizon and n else None
    pop_auc = (float(np.trapezoid([row["population_share"] for row in curve], x))
               if horizon and total_population else None)
    definition = "area under largest directed SCC share versus fraction of physical links removed, to actual removal horizon"
    summary = {"unweighted": score(node_auc, definition,
                   "no original nodes" if not n else "no links removed"),
        "population_weighted": score(pop_auc, definition + "; population in the same node-selected SCC",
                   "zero total population" if not total_population else "no links removed"),
        "order": order, "seed": seed, "requested_fraction": fraction, "horizon": actual_fraction,
        "steps": steps, "reported_steps": reported_steps, "links_removed": horizon,
        "non_self_loop_link_count": total_links, "original_node_count": n,
        "sampling": "baseline plus evenly spaced integer removal counts; floor(fraction * link_count) maximum",
        "component_selection": "largest SCC by node count; ties use sorted canonical node IDs",
        "auc_convention": "trapezoidal integral of exported curve; raw area, no extrapolation"}
    if services is not None:
        auc = float(np.trapezoid([r["service_share"] for r in curve], x)) if horizon and services.service_total else None
        summary["service_weighted"] = score(auc, definition + "; original service importance in the same node-selected SCC",
            "zero original service importance mass" if not services.service_total else "no links removed")
    return AttackResult(curve, summary, removal_order)


def write_curve(result, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        columns = (*CURVE_COLUMNS, "service_share") if result.curve and "service_share" in result.curve[0] else CURVE_COLUMNS
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(result.curve)
    return path
