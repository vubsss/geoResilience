"""Shared ordered-pair universe, normalized Hansen indices and removal measures.

All consequences use directed paths and the original node/pair denominators.
Population products are a resident-to-resident demand proxy, not observed trips.
"""

from dataclasses import dataclass
import math

import numpy as np

from .links import _link_rows
from .removal import ActiveEdgeGraph
from .shortest_paths import ShortestPathEngine

POPULATION_REASON = "no population on distinct origin-destination nodes"


class PairUniverse:
    def __init__(self, population):
        population = np.asarray(population, dtype=float)
        if population.ndim != 1 or not np.isfinite(population).all() or (population < 0).any():
            raise ValueError("population weights must be finite, nonnegative and one-dimensional")
        total = float(population.sum())
        if not math.isfinite(total):
            raise ValueError("total population must be finite")
        self.population = population
        self.n = len(population)
        self.total = total
        self.weights = population / total if total else np.zeros(self.n)
        self.denominator = self.n * (self.n - 1)
        # Exclusive sums avoid cancellation when one node holds almost all residents.
        self.destination_weights = (np.r_[0., np.cumsum(self.weights[:-1])]
            + np.r_[np.cumsum(self.weights[:0:-1])[::-1], 0.]) if self.n else np.array([])
        self.denominator_pop = float(self.weights @ self.destination_weights)


@dataclass
class MetricsSnapshot:
    universe: PairUniverse
    node_hansen: np.ndarray
    node_hansen_pop: np.ndarray
    efficiency: float | None
    efficiency_pop: float | None
    accessibility: float | None
    accessibility_pop: float | None
    reachable_fraction: float | None
    reachable_fraction_pop: float | None


@dataclass
class Baseline(MetricsSnapshot):
    topology: ActiveEdgeGraph


@dataclass
class _PairReducer:
    universe: PairUniverse
    beta: float
    cutoff: float

    def __call__(self, distances, sources):
        u = self.universe
        distances[np.arange(len(sources)), sources] = np.inf
        reachable = np.isfinite(distances)
        inverse = np.divide(1., distances, out=np.zeros_like(distances), where=reachable & (distances > 0))
        decay = np.exp(-self.beta * distances)
        decay[distances > self.cutoff] = 0
        return np.column_stack((inverse.sum(axis=1), inverse @ u.weights,
            decay.sum(axis=1), decay @ u.weights, reachable.sum(axis=1), reachable @ u.weights))


def evaluate_matrix(matrix, universe, *, half_distance_km=2, cutoff_factor=5, n_jobs=1, budget_bytes=2**26):
    n = universe.n
    half_m = half_distance_km * 1000
    if not math.isfinite(half_m) or half_m <= 0 or not math.isfinite(cutoff_factor) or cutoff_factor <= 0:
        raise ValueError("Hansen half-distance and cutoff factor must be finite and positive")
    if matrix.shape != (n, n):
        raise ValueError("matrix must retain the original node universe")
    # Reducer holds distance, inverse and decay blocks; reserve additional workspace.
    if budget_bytes < max(1, n) * 8 * 8:
        raise ValueError("memory budget too small for one shortest-path row")
    n_jobs = min(n_jobs, max(1, n), max(1, budget_bytes // (max(1, n) * 8 * 8)))
    engine = ShortestPathEngine(matrix, n_jobs=n_jobs, budget_bytes=budget_bytes // 3)
    values = np.zeros((n, 6))
    reducer = _PairReducer(universe, math.log(2) / half_m, half_m * cutoff_factor)
    for sources, reduced in engine.reduce(np.arange(n), reducer, directed=True):
        values[sources] = reduced
    h = values[:, 2] / (n - 1) if n > 1 else np.full(n, np.nan)
    destination_mass = universe.destination_weights
    hp = np.divide(values[:, 3], destination_mass, out=np.full(n, np.nan), where=destination_mass > 0)
    denominator, denominator_pop = universe.denominator, universe.denominator_pop
    weighted_access = (float(universe.weights @ np.nan_to_num(hp))
        if denominator_pop > 0 and np.isfinite(hp[universe.weights > 0]).all() else None)
    return MetricsSnapshot(universe, h, hp,
        float(values[:, 0].sum() / denominator) if denominator else None,
        float(universe.weights @ values[:, 1] / denominator_pop) if denominator_pop > 0 else None,
        float(h.mean()) if n > 1 else None, weighted_access,
        float(values[:, 4].sum() / denominator) if denominator else None,
        float(universe.weights @ values[:, 5] / denominator_pop) if denominator_pop > 0 else None)


def compute_baseline(graph, population, **kwargs):
    universe = PairUniverse(population)
    if universe.n != len(graph):
        raise ValueError("population must match the original node count")
    topology = ActiveEdgeGraph(graph, _link_rows(graph), directed=True)
    snapshot = evaluate_matrix(topology.csr(), universe, **kwargs)
    return Baseline(**snapshot.__dict__, topology=topology)


def relative_drop(baseline, damaged):
    if baseline is None or damaged is None or baseline <= 0:
        return None
    return float(np.clip((baseline - damaged) / baseline, 0, 1))


def score(value, definition, reason=None, **metadata):
    return {"value": value, "definition": definition,
            "reason": reason if value is None else None, **metadata}


@dataclass
class LocalResult:
    baseline: Baseline
    nodes: dict
    links: list
    coverage: dict
    redundancy: dict
    settings: dict


def _finite(value):
    return float(value) if value is not None and np.isfinite(value) else None


def _structural(graph, links):
    import networkx as nx
    simple = nx.Graph()
    simple.add_nodes_from(graph)
    pair_links = {}
    for row in links:
        if row["is_self_loop"]:
            continue
        u, v = row["_u"], row["_v"]
        pair_links.setdefault(frozenset((u, v)), []).append(row["link_id"])
        candidate = (row["length_m"], row["link_id"])
        if not simple.has_edge(u, v) or candidate < (simple[u][v]["length"], simple[u][v]["link_id"]):
            simple.add_edge(u, v, length=row["length_m"], link_id=row["link_id"])
    nodes = nx.betweenness_centrality(simple, weight="length", normalized=True)
    edge_scores = nx.edge_betweenness_centrality(simple, weight="length", normalized=True)
    betweenness = {row["link_id"]: None if row["is_self_loop"] else 0.0 for row in links}
    for (u, v), value in edge_scores.items():
        betweenness[simple[u][v]["link_id"]] = float(value)
    bridges = {pair_links[frozenset(pair)][0] for pair in nx.bridges(simple)
               if len(pair_links[frozenset(pair)]) == 1}
    return nodes, betweenness, bridges, set(nx.articulation_points(simple))


def _consequence_fields(baseline, damaged):
    values = {}
    reasons = {}
    for suffix in ("", "_pop"):
        for field, attribute in (("efficiency_drop", "efficiency"), ("accessibility_drop", "accessibility")):
            before, after = getattr(baseline, attribute + suffix), getattr(damaged, attribute + suffix)
            value = relative_drop(before, after)
            values[field + suffix] = value
            if value is None:
                reasons[field + suffix] = POPULATION_REASON if before is None and suffix else "baseline measure is zero or undefined"
        before, after = getattr(baseline, "reachable_fraction" + suffix), getattr(damaged, "reachable_fraction" + suffix)
        values["disconnected_pair_fraction" + suffix] = (float(np.clip(before - after, 0, 1))
            if before is not None and after is not None else None)
        if before is None:
            reasons["disconnected_pair_fraction" + suffix] = POPULATION_REASON if suffix else "no distinct node pairs"
    return values, reasons


CONSEQUENCE_FIELDS = tuple(field + suffix for field in (
    "efficiency_drop", "accessibility_drop", "disconnected_pair_fraction") for suffix in ("", "_pop"))


def compute_link_consequences(graph, population, *, coverage="screened", candidate_limit=250, service_nodes=(), **settings):
    import networkx as nx
    if coverage not in {"screened", "all"} or candidate_limit < 0:
        raise ValueError("coverage must be screened or all; candidate_limit must be nonnegative")
    baseline = compute_baseline(graph, population, **settings)
    links = _link_rows(graph)
    node_b, edge_b, bridges, articulations = _structural(graph, links)
    nodes = {}
    for i, node in enumerate(graph):
        h, hp = _finite(baseline.node_hansen[i]), _finite(baseline.node_hansen_pop[i])
        reasons = {}
        if h is None:
            reasons["hansen_accessibility"] = "no other nodes"
        if hp is None:
            reasons["hansen_accessibility_pop"] = "no destination population outside this node"
        nodes[node] = {"betweenness": float(node_b[node]), "hansen_accessibility": h,
                       "hansen_accessibility_pop": hp, "is_articulation": node in articulations,
                       "null_reasons": reasons}
    for row in links:
        key = row["link_id"]
        row.update(edge_betweenness=edge_b[key], is_bridge=key in bridges, null_reasons={})
        ratio = None
        if not row["is_self_loop"]:
            removed = set(row["_edges"])
            view = nx.subgraph_view(graph, filter_edge=lambda u, v, k: (u, v, k) not in removed)
            alternatives = []
            for u, v in dict.fromkeys((u, v) for u, v, _ in row["_edges"]):
                try:
                    alternatives.append(nx.shortest_path_length(view, u, v, weight="length"))
                except nx.NetworkXNoPath:
                    alternatives.append(math.inf)
            ratio = max(alternatives) / row["length_m"]
        row["detour_ratio"] = _finite(ratio)
        row["detour_none"] = bool(ratio is not None and math.isinf(ratio))
        if row["detour_ratio"] is None:
            row["null_reasons"]["detour_ratio"] = "self-loop excluded" if row["is_self_loop"] else "no alternative for at least one original direction"
        if row["is_self_loop"]:
            row["null_reasons"]["edge_betweenness"] = "self-loop excluded"
    active = [row for row in links if not row["is_self_loop"]]
    if coverage == "all":
        candidates = {row["link_id"] for row in active}
    else:
        by_b = sorted(active, key=lambda r: (-r["edge_betweenness"], r["link_id"]))
        by_d = sorted(active, key=lambda r: (-(r["detour_ratio"] or 0), r["link_id"]))
        candidates = {row["link_id"] for row in by_b[:candidate_limit] + by_d[:candidate_limit]}
        candidates.update(row["link_id"] for row in active if row["is_bridge"] or row["detour_none"])
    service_nodes = set(service_nodes)
    candidates.update(row["link_id"] for row in active
                      if row["_u"] in service_nodes or row["_v"] in service_nodes)
    for row in links:
        row["evaluated"] = row["link_id"] in candidates
        if row["evaluated"]:
            damaged = evaluate_matrix(baseline.topology.csr(removed_links=[row["link_id"]]), baseline.universe, **settings)
            values, reasons = _consequence_fields(baseline, damaged)
            row.update(values)
            row["null_reasons"].update(reasons)
        else:
            row.update(dict.fromkeys(CONSEQUENCE_FIELDS))
            reason = "self-loop excluded" if row["is_self_loop"] else "not evaluated in screened coverage"
            row["null_reasons"].update(dict.fromkeys(CONSEQUENCE_FIELDS, reason))
    finite = [row["detour_ratio"] for row in active if row["detour_ratio"] is not None]
    redundancy = {
        "bridge_redundancy": score(1 - len(bridges) / len(active) if active else None,
            "1 - bridge_count / non_self_loop_link_count", "no non-self-loop links", bridge_count=len(bridges), link_count=len(active)),
        "detour_redundancy": score(float(np.median(finite)) if finite else None,
            "median finite directed alternative-distance / physical-link length", "no finite alternatives", finite_count=len(finite)),
        "detour_no_alternative_share": score(sum(row["detour_none"] for row in active) / len(active) if active else None,
            "share of non-self-loop links with no alternative in at least one original direction", "no non-self-loop links")}
    counts = {"links": {"mode": coverage, "evaluated": len(candidates), "total": len(active),
        "ids": [r["link_uid"] for r in active if r["evaluated"]],
        "method": "all non-self-loop links" if coverage == "all" else
            f"top {candidate_limit} by betweenness and finite detour, all bridges and links without alternatives"}}
    if service_nodes and coverage == "screened":
        counts["links"]["method"] += "; all links incident to positive-weight service nodes"
    return LocalResult(baseline, nodes, links, counts, redundancy, settings)


def add_node_consequences(result, *, coverage="screened", candidate_limit=300, service_nodes=()):
    if coverage not in {"screened", "all"} or candidate_limit < 0:
        raise ValueError("coverage must be screened or all; candidate_limit must be nonnegative")
    ordered = list(result.nodes)
    order = {node: index for index, node in enumerate(ordered)}
    ranked = sorted(ordered, key=lambda node: (-result.nodes[node]["betweenness"], order[node]))
    candidates = (set(ordered) if coverage == "all" else set(ranked[:candidate_limit])
                  | {node for node in ordered if result.nodes[node]["is_articulation"]})
    candidates.update(set(service_nodes) & set(ordered))
    for index, node in enumerate(ordered):
        row = result.nodes[node]
        row["evaluated"] = node in candidates
        if row["evaluated"]:
            matrix = result.baseline.topology.csr(isolated_nodes=[index])
            damaged = evaluate_matrix(matrix, result.baseline.universe, **result.settings)
            values, reasons = _consequence_fields(result.baseline, damaged)
            for suffix in ("", "_pop"):
                values["information_centrality" + suffix] = values.pop("efficiency_drop" + suffix)
                if "efficiency_drop" + suffix in reasons:
                    reasons["information_centrality" + suffix] = reasons.pop("efficiency_drop" + suffix)
            row.update(values)
            row["null_reasons"].update(reasons)
        else:
            fields = [field + suffix for field in ("information_centrality", "accessibility_drop",
                       "disconnected_pair_fraction") for suffix in ("", "_pop")]
            row.update(dict.fromkeys(fields))
            row["null_reasons"].update(dict.fromkeys(fields, "not evaluated in screened coverage"))
    result.coverage["nodes"] = {"mode": coverage, "evaluated": len(candidates), "total": len(ordered),
        "ids": [str(node) for node in ordered if node in candidates],
        "method": "all retained nodes" if coverage == "all" else f"top {candidate_limit} by betweenness and all articulation points"}
    if service_nodes and coverage == "screened":
        result.coverage["nodes"]["method"] += "; all positive-weight service nodes"
    return result


def compute_local_metrics(graph, population, *, coverage="screened", link_candidate_limit=250,
                          node_candidate_limit=300, service_nodes=(), **settings):
    result = compute_link_consequences(graph, population, coverage=coverage,
                                      candidate_limit=link_candidate_limit, service_nodes=service_nodes, **settings)
    return add_node_consequences(result, coverage=coverage, candidate_limit=node_candidate_limit, service_nodes=service_nodes)
