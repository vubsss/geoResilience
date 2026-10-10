"""Active-edge CSR graphs and exact, memory-bounded removal recomputations."""

import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

from .shortest_paths import ShortestPathEngine, aggregate_efficiency, fits_in_memory


def node_weights(n, weights=None):
    values = np.ones(n) if weights is None else np.asarray(weights, dtype=np.float64)
    if values.shape != (n,) or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("node weights must be finite, nonnegative and match the node count")
    return values


def removal_engine(graph, n_jobs, budget_bytes):
    # Removal reducers can hold old/new distances plus row temporaries. Reserve
    # eight float64 blocks rather than the centrality engine's three blocks.
    return ShortestPathEngine(graph, n_jobs=n_jobs, budget_bytes=max(1, budget_bytes * 3 // 8))


class ActiveEdgeGraph:
    """Sort arcs once; rebuild minimum-parallel-edge CSR in O(m) per closure.

    Node indices are retained even when every incident edge is removed.
    """

    def __init__(self, graph, links, *, directed=True):
        self.node_ids = list(graph)
        self.index = {node: i for i, node in enumerate(self.node_ids)}
        self.directed = directed
        arcs = []
        for row in links:
            if row["is_self_loop"]:
                continue
            if directed:
                edges = [(u, v, float(graph[u][v][key]["length"])) for u, v, key in row["_edges"]]
            else:
                u, v = row["_u"], row["_v"]
                edges = [(u, v, row["length_m"]), (v, u, row["length_m"])]
            for u, v, length in edges:
                if not math.isfinite(length) or length <= 0:
                    raise ValueError(f"link {row['link_id']}: edge length must be finite and positive")
                arcs.append((self.index[u], self.index[v], length, row["link_id"]))
        self.rows = np.array([arc[0] for arc in arcs], dtype=np.int64)
        self.cols = np.array([arc[1] for arc in arcs], dtype=np.int64)
        self.lengths = np.array([arc[2] for arc in arcs], dtype=np.float64)
        self.link_ids = np.array([arc[3] for arc in arcs], dtype=np.int64)
        order = np.lexsort((self.cols, self.rows))
        self.rows, self.cols = self.rows[order], self.cols[order]
        self.lengths, self.link_ids = self.lengths[order], self.link_ids[order]
        self.link_arcs = {}
        for u, v, length, link_id in arcs:
            self.link_arcs.setdefault(link_id, []).append((u, v, length))

    def csr(self, removed_links=(), isolated_nodes=()):
        active = ~np.isin(self.link_ids, list(removed_links))
        if len(isolated_nodes):
            active &= ~np.isin(self.rows, isolated_nodes) & ~np.isin(self.cols, isolated_nodes)
        rows, cols, lengths = self.rows[active], self.cols[active], self.lengths[active]
        if len(rows):
            starts = np.flatnonzero(np.r_[True, (rows[1:] != rows[:-1]) | (cols[1:] != cols[:-1])])
            lengths = np.minimum.reduceat(lengths, starts)
            rows, cols = rows[starts], cols[starts]
        return csr_matrix((lengths, (rows, cols)), shape=(len(self.node_ids), len(self.node_ids)))


@dataclass
class InverseReducer:
    weights: np.ndarray

    def __call__(self, distances, sources):
        np.divide(1.0, distances, out=distances, where=distances > 0)
        return distances @ self.weights


class BaselineDistances:
    """Cache float64 distances only when cache plus workspace fits the budget.

    A temporary memory map shares the cache with process workers without copying
    an N x N array per task. Its file is removed when the context closes.
    Otherwise only row aggregates are retained, and old rows are recomputed.
    """

    def __init__(self, graph, *, n_jobs, budget_bytes, weights=None, cache=None):
        self.graph = graph
        self.n_jobs = n_jobs
        self.weights = node_weights(graph.shape[0], weights)
        self.denominator = float(self.weights.sum() ** 2 - self.weights @ self.weights)
        self.cache = None
        self._folder = None
        n = graph.shape[0]
        matrix_bytes = n * n * 8
        reserve = max(1, n * 8 * 8 * n_jobs)
        can_cache = fits_in_memory(n, budget_bytes=budget_bytes) and matrix_bytes + reserve <= budget_bytes
        self.budget_bytes = budget_bytes
        if cache is not False and can_cache:
            self._folder = TemporaryDirectory(prefix="georesilience-baseline-")
            # The cache is memory-budgeted but also needs temporary disk space.
            if shutil.disk_usage(self._folder.name).free >= matrix_bytes + reserve:
                try:
                    self.cache = np.memmap(Path(self._folder.name) / "distances.bin", mode="w+",
                                           dtype=np.float64, shape=(n, n))
                except OSError:
                    self._folder.cleanup()
                    self._folder = None
            else:
                self._folder.cleanup()
                self._folder = None
        self.working_budget_bytes = budget_bytes - (matrix_bytes if self.cache is not None else 0)
        self.engine = removal_engine(graph, n_jobs, self.working_budget_bytes)
        self.row_sums = np.zeros(n)
        reducer = InverseReducer(self.weights)
        try:
            if self.cache is not None:
                for start in range(0, n, self.engine.chunk_rows):
                    sources = np.arange(start, min(n, start + self.engine.chunk_rows))
                    distances = dijkstra(graph, directed=True, indices=sources)
                    self.cache[sources] = distances
                    self.row_sums[sources] = reducer(distances, sources)
                self.cache.flush()
                self.cache.flags.writeable = False
            else:
                for sources, values in self.engine.reduce(np.arange(n), reducer, directed=True):
                    self.row_sums[sources] = values
            self.inverse_total = float(self.weights @ self.row_sums)
            self.efficiency = aggregate_efficiency(self.row_sums, self.weights)
        except BaseException:
            self.close()
            raise

    def close(self):
        self.cache = None
        if self._folder is not None:
            self._folder.cleanup()
            self._folder = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class AffectedSourceRecompute:
    """Reusable endpoint-column shortcut and chunked active-graph reducer API."""

    def __init__(self, active_graph, *, n_jobs, budget_bytes):
        self.active_graph = active_graph
        self.graph = active_graph.csr()
        self.reverse = self.graph.T.tocsr()
        self.n_jobs = n_jobs
        self.budget_bytes = budget_bytes

    def affected_sources(self, link_id, *, limit=np.inf):
        arcs = self.active_graph.link_arcs.get(link_id, [])
        endpoints = list(dict.fromkeys(node for u, v, _ in arcs for node in (u, v)))
        if not endpoints:
            return np.array([], dtype=np.int64)
        columns = dijkstra(self.reverse, directed=True, indices=endpoints, limit=limit)
        position = {node: i for i, node in enumerate(endpoints)}
        affected = np.zeros(self.graph.shape[0], dtype=bool)
        for u, v, length in arcs:
            du, dv = columns[position[u]], columns[position[v]]
            affected |= np.isfinite(du) & np.isfinite(dv) & np.isclose(du + length, dv, rtol=1e-9, atol=0)
        return np.flatnonzero(affected)

    def recompute(self, removed_links, sources, reducer, *, limit=np.inf):
        changed = self.active_graph.csr(removed_links=removed_links)
        engine = removal_engine(changed, self.n_jobs, self.budget_bytes)
        yield from engine.reduce(sources, reducer, directed=True, limit=limit)

    def bridge_side(self, link_id):
        changed = self.active_graph.csr(removed_links=[link_id])
        count, labels = connected_components(changed, directed=False)
        if count != 2:
            raise ValueError("analytic bridge removal must split the network into two components")
        return np.flatnonzero(labels == np.argmin(np.bincount(labels)))


@dataclass
class DamageReducer:
    baseline_graph: csr_matrix
    baseline_cache: np.ndarray | None
    weights: np.ndarray

    def __call__(self, changed, sources):
        baseline = (None if self.baseline_cache is not None else
                    dijkstra(self.baseline_graph, directed=True, indices=sources))
        result = np.zeros((len(sources), 4))
        for i, source in enumerate(sources):
            before = self.baseline_cache[source] if baseline is None else baseline[i]
            after = changed[i]
            reachable = np.isfinite(before) & (before > 0)
            still_reachable = np.isfinite(after) & (after > 0)
            pair_weights = self.weights * self.weights[source]
            inverse_loss = np.divide(1.0, before, out=np.zeros_like(before), where=reachable)
            inverse_loss -= np.divide(1.0, after, out=np.zeros_like(after), where=still_reachable)
            lost = reachable & ~still_reachable
            longer = reachable & still_reachable & (after > before)
            extra = after[longer] - before[longer]
            result[i] = (inverse_loss @ pair_weights, pair_weights[lost].sum(),
                         extra.sum(), np.count_nonzero(longer))
        return result


def _damage_metrics(inverse_loss, lost_pairs, extra_m, affected_pairs, baseline):
    return {
        "eff_drop": max(0.0, float(inverse_loss / baseline.inverse_total)) if baseline.inverse_total > 0 else math.nan,
        "disc_pair_frac": float(lost_pairs / baseline.denominator) if baseline.denominator > 0 else math.nan,
        "extra_km_total": float(extra_m / 1000), "affected_pairs": int(affected_pairs),
        "extra_m_mean_affected": float(extra_m / affected_pairs) if affected_pairs else math.nan,
    }


def full_link_damage(recompute, baseline, link_id):
    sources = recompute.affected_sources(link_id)
    reducer = DamageReducer(baseline.graph, baseline.cache, baseline.weights)
    totals = np.zeros(4)
    for _, values in recompute.recompute([link_id], sources, reducer):
        # Sum in source order so results do not depend on chunk boundaries/jobs.
        for row in values:
            totals += row
    return _damage_metrics(*totals, baseline), len(sources)


@dataclass
class CrossCutReducer:
    weights: np.ndarray
    outside: np.ndarray

    def __call__(self, distances, sources):
        result = np.zeros((len(sources), 2))
        for i, source in enumerate(sources):
            row = distances[i]
            reachable = self.outside & np.isfinite(row) & (row > 0)
            inverse = np.divide(1.0, row, out=np.zeros_like(row), where=reachable)
            result[i] = (inverse @ self.weights, self.weights[reachable].sum())
            result[i] *= self.weights[source]
        return result


def analytic_bridge_damage(recompute, baseline, link_id):
    side = recompute.bridge_side(link_id)
    outside = np.ones(len(baseline.weights), dtype=bool)
    outside[side] = False
    reducer = CrossCutReducer(baseline.weights, outside)
    totals = np.zeros(2)
    if baseline.cache is not None:
        # Row/column views avoid materialising an |S| x N copy of the cache.
        for source in side:
            for row in (baseline.cache[source], baseline.cache[:, source]):
                totals += reducer(row[None, :], np.array([source]))[0]
    else:
        for graph in (recompute.graph, recompute.reverse):
            engine = removal_engine(graph, recompute.n_jobs, recompute.budget_bytes)
            for _, values in engine.reduce(side, reducer, directed=True):
                for row in values:
                    totals += row
    return _damage_metrics(*totals, 0.0, 0, baseline)
