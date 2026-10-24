"""Active physical-link CSR graphs retain original node indices after closures."""

import math

import numpy as np
from scipy.sparse import csr_matrix


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
