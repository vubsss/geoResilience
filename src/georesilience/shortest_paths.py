"""Memory-budgeted shortest paths. Workers reduce blocks before returning them."""

import math
import os

import numpy as np
import psutil
from joblib import Parallel, delayed, parallel_config
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

GIB = 1024**3


def resolve_resources(n_jobs="auto", max_memory_gb="auto"):
    if n_jobs == "auto":
        value = os.environ.get("SLURM_CPUS_PER_TASK")
        try:
            n_jobs = int(value) if value is not None else (os.cpu_count() or 1)
        except ValueError as exc:
            raise ValueError("SLURM_CPUS_PER_TASK must be a positive integer") from exc
    if not isinstance(n_jobs, int) or n_jobs < 1:
        raise ValueError("analysis.n_jobs must be a positive integer or auto")
    if max_memory_gb != "auto" and (not math.isfinite(float(max_memory_gb) * GIB) or float(max_memory_gb) <= 0):
        raise ValueError("analysis.max_memory_gb must be finite and positive")
    budget = (int(psutil.virtual_memory().available * 0.5) if max_memory_gb == "auto"
              else int(float(max_memory_gb) * GIB))
    if budget < 1:
        raise ValueError("analysis.max_memory_gb must allow at least one byte")
    return n_jobs, budget


def fits_in_memory(n, dtype=np.float64, *, budget_bytes=None):
    """Whether one dense N by N array fits (not the whole analysis workspace)."""
    if budget_bytes is None:
        budget_bytes = int(psutil.virtual_memory().available * 0.5)
    return n * n * np.dtype(dtype).itemsize <= budget_bytes


def _reduce_chunk(graph, sources, reducer, directed, limit):
    distances = dijkstra(graph, directed=directed, indices=sources, limit=limit)
    return sources, reducer(distances, sources)


class ShortestPathEngine:
    """Yield (source indices, reduced result) in source order.

    A reducer accepts ``(distance_block, sources)``. It may mutate the block,
    but must return reduced results rather than retain the block. With multiple
    chunks, loky processes run at most n_jobs tasks concurrently; only reduced
    results cross the process boundary. No all-pairs distance matrix is cached.
    """

    def __init__(self, graph, *, n_jobs=1, budget_bytes):
        self.graph = csr_matrix(graph, dtype=np.float64)
        if self.graph.shape[0] != self.graph.shape[1]:
            raise ValueError("shortest-path graph must be square")
        if n_jobs < 1 or budget_bytes < 1:
            raise ValueError("n_jobs and budget_bytes must be positive")
        if not np.isfinite(self.graph.data).all() or (self.graph.data < 0).any():
            raise ValueError("shortest-path edge weights must be finite and nonnegative")
        self.n_jobs = n_jobs
        self.budget_bytes = budget_bytes
        n = self.graph.shape[0]
        self.chunk_rows = max(1, budget_bytes // (max(1, n) * 8 * 3 * n_jobs))

    def fits_in_memory(self, n=None, dtype=np.float64):
        return fits_in_memory(self.graph.shape[0] if n is None else n, dtype,
                              budget_bytes=self.budget_bytes)

    def reduce(self, sources, reducer, *, directed=False, limit=np.inf):
        sources = np.asarray(sources, dtype=np.int64)
        if sources.ndim != 1 or ((sources < 0) | (sources >= self.graph.shape[0])).any():
            raise ValueError("sources must be a one-dimensional list of valid node indices")
        if limit < 0 or np.isnan(limit):
            raise ValueError("shortest-path limit must be nonnegative")
        chunks = (sources[start:start + self.chunk_rows]
                  for start in range(0, len(sources), self.chunk_rows))
        count = math.ceil(len(sources) / self.chunk_rows)
        if self.n_jobs == 1 or count <= 1:
            for chunk in chunks:
                yield _reduce_chunk(self.graph, chunk, reducer, directed, limit)
            return
        # Native BLAS threads must not multiply the requested process count.
        with parallel_config(backend="loky", inner_max_num_threads=1):
            with Parallel(n_jobs=min(self.n_jobs, count), return_as="generator",
                          pre_dispatch=min(self.n_jobs, count), batch_size=1) as parallel:
                yield from parallel(delayed(_reduce_chunk)(self.graph, chunk, reducer, directed, limit)
                                    for chunk in chunks)
