"""Directed resident-to-service metrics with fixed original P_i*w_j mass."""

from dataclasses import dataclass
import math

import numpy as np
from scipy.sparse import csr_matrix

from .metrics import score
from .shortest_paths import ShortestPathEngine


class ServiceUniverse:
    def __init__(self, population, service_weights):
        self.population = np.asarray(population, dtype=float)
        self.service_weights = np.asarray(service_weights, dtype=float)
        if (self.population.ndim != 1 or self.service_weights.shape != self.population.shape
                or not np.isfinite(self.population).all() or not np.isfinite(self.service_weights).all()
                or (self.population < 0).any() or (self.service_weights < 0).any()):
            raise ValueError('population and service weights must be matching finite nonnegative vectors')
        self.n = len(self.population)
        self.population_total = float(self.population.sum())
        self.service_total = float(self.service_weights.sum())
        if not math.isfinite(self.population_total) or not math.isfinite(self.service_total):
            raise ValueError('population and service totals must be finite')
        self.origins = self.population / self.population_total if self.population_total else np.zeros(self.n)
        self.destinations = self.service_weights / self.service_total if self.service_total else np.zeros(self.n)

    @property
    def reason(self):
        if self.population_total == 0:
            return 'zero original population mass'
        if self.service_total == 0:
            return 'zero original service importance mass'
        return None


@dataclass
class ServiceSnapshot:
    node_reachability: np.ndarray
    node_hansen: np.ndarray
    summary: dict


@dataclass
class _ServiceReducer:
    destinations: np.ndarray
    beta: float
    cutoff: float
    isolated_nodes: tuple

    def __call__(self, distances, sources):
        if self.isolated_nodes:
            distances[:, self.isolated_nodes] = np.inf
            distances[np.isin(sources, self.isolated_nodes), :] = np.inf
        reachable = np.isfinite(distances) @ self.destinations
        distances[distances > self.cutoff] = np.inf
        np.multiply(distances, -self.beta, out=distances)
        np.exp(distances, out=distances)
        return np.column_stack((reachable, distances @ self.destinations))


def evaluate_service_matrix(matrix, universe, *, half_distance_km=2, cutoff_factor=5,
                            isolated_nodes=(), n_jobs=1, budget_bytes=2**26):
    """Co-located pairs contribute one; closed origins/supply contribute zero.

    The universe stays original after closures, so no surviving mass is silently
    renormalized. Length-based reachability has no Hansen distance cutoff.
    """
    n = universe.n
    if matrix.shape != (n, n):
        raise ValueError('service matrix must retain the original node universe')
    if len(isolated_nodes):
        arcs = matrix.tocoo()
        keep = ~np.isin(arcs.row, isolated_nodes) & ~np.isin(arcs.col, isolated_nodes)
        matrix = csr_matrix((arcs.data[keep], (arcs.row[keep], arcs.col[keep])), shape=(n, n))
    half = half_distance_km * 1000
    cutoff = half * cutoff_factor
    if not all(math.isfinite(v) and v > 0 for v in (half, cutoff, math.log(2) / half)):
        raise ValueError('service Hansen half-distance, decay and cutoff must be finite and positive')
    minimum = max(1, n) * 8 * 8
    if budget_bytes < minimum:
        raise ValueError('memory budget too small for one service shortest-path row')
    jobs = min(n_jobs, max(1, n), max(1, budget_bytes // minimum))
    values = np.zeros((n, 2))
    reducer = _ServiceReducer(universe.destinations, math.log(2) / half, cutoff, tuple(isolated_nodes))
    engine = ShortestPathEngine(matrix, n_jobs=jobs, budget_bytes=budget_bytes // 3)
    for sources, block in engine.reduce(np.arange(n), reducer, directed=True):
        values[sources] = block
    reason = universe.reason
    definitions = {'directed_reachability': 'original population-to-service P_i*w_j share reachable in the directed graph, including co-location',
        'hansen_accessibility': 'original population-to-service P_i*w_j normalized length-decay Hansen, including co-location'}
    summary = {key: score(float(universe.origins @ values[:, i]) if reason is None else None, definition, reason)
               for i, (key, definition) in enumerate(definitions.items())}
    if universe.service_total == 0:
        values[:] = np.nan
    return ServiceSnapshot(values[:, 0], values[:, 1], summary)
