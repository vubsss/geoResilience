"""Shared directed seconds topology for reliability and static catchments."""

from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix

from .shortest_paths import ShortestPathEngine
from .time_models import TimeContext, prepare_time_model


class TimeTopology:
    def __init__(self, graph, links, prepared):
        index = {node: i for i, node in enumerate(graph)}
        arcs = sorted((index[u], index[v], position, (u, v, key))
            for position, row in enumerate(links) for u, v, key in row["_edges"] if u != v)
        self.rows = np.array([a[0] for a in arcs], dtype=int)
        self.cols = np.array([a[1] for a in arcs], dtype=int)
        self.positions = np.array([a[2] for a in arcs], dtype=int)
        self.edges = [a[3] for a in arcs]
        self.ids = [row["link_id"] for row in links]
        self.node_ids = tuple(graph)
        self.n, self.prepared = len(graph), prepared
        self.baseline_values = self.values(prepared.costs(TimeContext()))

    def values(self, mapping):
        try:
            values = np.array([float(mapping[edge]) for edge in self.edges])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("travel_time: provider must supply numeric seconds for every directed non-loop edge") from exc
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError("travel_time: edge seconds must be finite and strictly positive")
        return values

    def csr(self, up=None, sample_index=None, *, removed_links=(), isolated_nodes=(), transpose=False):
        if up is None:
            up = ~np.isin(self.ids, list(removed_links))
        up = np.asarray(up, dtype=bool)
        if up.shape != (len(self.ids),):
            raise ValueError("time topology link states must match original physical links")
        values = self.baseline_values
        if sample_index is not None and self.prepared.scenario_times is not None:
            closed = frozenset(link for link, state in zip(self.ids, up) if not state)
            values = self.values(self.prepared.costs(TimeContext(sample_index, closed)))
        keep = up[self.positions]
        if len(isolated_nodes):
            keep &= ~np.isin(self.rows, isolated_nodes) & ~np.isin(self.cols, isolated_nodes)
        rows, cols, costs = self.rows[keep], self.cols[keep], values[keep]
        if len(rows):
            starts = np.flatnonzero(np.r_[True, (rows[1:] != rows[:-1]) | (cols[1:] != cols[:-1])])
            rows, cols, costs = rows[starts], cols[starts], np.minimum.reduceat(costs, starts)
        matrix = csr_matrix((costs, (rows, cols)), shape=(self.n, self.n))
        return matrix.T.tocsr() if transpose else matrix


    def reduce(self, sources, reducer, *, cutoff_seconds=np.inf, n_jobs=1,
               budget_bytes=2**26, removed_links=(), isolated_nodes=(), transpose=False):
        """Bounded static queries; reducers must return reduced, not dense blocks."""
        if self.prepared.scenario_times is not None:
            raise ValueError('static time queries require a static provider; dynamic custom providers are unsupported for 2SFCA')
        minimum = max(1, self.n) * 8 * 8
        if budget_bytes < minimum:
            raise ValueError('memory budget too small for one time-catchment row')
        jobs = min(n_jobs, max(1, len(sources)), max(1, budget_bytes // minimum))
        engine = ShortestPathEngine(self.csr(removed_links=removed_links,
            isolated_nodes=isolated_nodes, transpose=transpose), n_jobs=jobs, budget_bytes=budget_bytes // 3)
        yield from engine.reduce(sources, reducer, directed=True, limit=cutoff_seconds)


@dataclass
class StaticTimeRouting:
    topology: TimeTopology | None
    summary: dict

    @property
    def reason(self):
        return None if self.topology is not None else self.summary['status']


def prepare_static_time(graph, links, time_config, time_model=None, *, prepared=None):
    """Resolve seconds once; unavailable costs never fall back to lengths."""
    if prepared is None:
        prepared = prepare_time_model(graph, time_config, time_model)
    if prepared.scenario_times is not None:
        raise ValueError('2SFCA requires static seconds; dynamic custom time providers are unsupported; supply static edge times')
    topology = TimeTopology(graph, links, prepared) if prepared.summary['status'] == 'computed' else None
    return StaticTimeRouting(topology, dict(prepared.summary))
