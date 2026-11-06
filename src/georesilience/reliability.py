"""Independent physical-link event simulations with paired, fixed OD universes."""

import csv
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

import numpy as np
from scipy.sparse.csgraph import connected_components, dijkstra

from .config import TravelTimeConfig
from .failure_probabilities import probabilities_at_p0
from .metrics import POPULATION_REASON, PairUniverse
from .od import OD_COLUMNS, ODInputs
from .removal import ActiveEdgeGraph
from .time_models import prepare_time_model
from .time_routing import TimeTopology

CONNECTIVITY = "fraction of original distinct ordered node pairs mutually reachable in the same directed SCC"
TRAVEL_TIME = "fraction of original distinct ordered node pairs with finite event travel time <= (1 + threshold) times intact travel time"
INTERVAL = "Hoeffding bound for independent bounded scenario pair fractions"
OD_OUTPUT_COLUMNS = (*OD_COLUMNS, "origin_node_id", "dest_node_id", "origin_snap_m", "dest_snap_m",
    "baseline_time_seconds", "connectivity_reliability", "connectivity_ci_low", "connectivity_ci_high",
    "travel_time_reliability", "travel_time_ci_low", "travel_time_ci_high", "travel_time_reason")


@dataclass
class ReliabilityResult:
    summary: dict
    od_rows: list
    computation: dict


def _score(total, samples, definition, reason=None):
    value = None if reason else float(np.clip(total / samples, 0, 1))
    half = math.sqrt(math.log(40) / (2 * samples))
    return {"value": value, "reason": reason, "definition": definition,
        "ci_low": max(0., value - half) if value is not None else None,
        "ci_high": min(1., value + half) if value is not None else None,
        "samples": samples, "confidence": .95, "interval_method": INTERVAL}


def _exclusive(weights):
    return (np.r_[0., np.cumsum(weights[:-1])] + np.r_[np.cumsum(weights[:0:-1])[::-1], 0.])


def _connectivity(matrix, universe):
    _, labels = connected_components(matrix, directed=True, connection="strong")
    sizes = np.bincount(labels)
    structural = float(np.sum(sizes * (sizes - 1)) / universe.denominator) if universe.denominator else 0.
    weighted = 0.
    if universe.denominator_pop:
        order = np.argsort(labels, kind="stable")
        offsets = np.r_[0, np.cumsum(sizes)]
        for component in range(len(sizes)):
            weights = universe.weights[order[offsets[component]:offsets[component + 1]]]
            if len(weights) > 1:
                weighted += float(weights @ _exclusive(weights))
        weighted /= universe.denominator_pop
    return (structural, min(1., max(0., weighted))), labels



def _time_success(baseline, damaged, threshold):
    with np.errstate(over="ignore", invalid="ignore"):
        bound = (1 + threshold) * baseline
        return np.isfinite(baseline) & np.isfinite(damaged) & (damaged <= bound + 1e-9 + 1e-12 * np.abs(bound))


def compute_reliability(graph, links, population, user_probabilities, *, p0=.01, p0_sweep=None,
        connectivity_samples=10000, travel_time_samples=1000, time_threshold=.5, seed=42,
        n_jobs=1, budget_bytes=2**26, time_config=None, time_model=None, od_inputs=None, uniform_samples=None):
    """Use common per-link uniforms across weighting views, sample counts and p0 scenarios.

    Each sample has its own SeedSequence([seed, index]). Ordered reductions make
    estimates independent of worker count. All origins are evaluated in bounded
    row chunks; an intact time matrix is cached only when it fits the budget.
    """
    for name, count in (("connectivity_samples", connectivity_samples), ("travel_time_samples", travel_time_samples), ("n_jobs", n_jobs)):
        if isinstance(count, bool) or not isinstance(count, int) or count < (1 if name == "n_jobs" else 2):
            raise ValueError(f"{name} must be an integer >= {1 if name == 'n_jobs' else 2}")
    if not math.isfinite(time_threshold) or time_threshold < 0:
        raise ValueError("time_threshold must be finite and nonnegative")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    universe = PairUniverse(population)
    if not universe.n or universe.n != len(graph):
        raise ValueError("population must match a nonempty original graph")
    active = sorted((row for row in links if not row["is_self_loop"]), key=lambda row: row["link_id"])
    if len({row["link_id"] for row in active}) != len(active):
        raise ValueError("physical-link IDs must be unique")
    scenarios = {"primary": p0}
    if p0_sweep is not None:
        if not isinstance(p0_sweep, dict) or any(not isinstance(key, str) or not key.strip() or key == "primary" for key in p0_sweep):
            raise ValueError("p0_sweep must map nonempty scenario names (excluding primary) to p0")
        scenarios.update(p0_sweep)
    probabilities = {name: np.array(list(probabilities_at_p0(active, user_probabilities, value).values()))
                     for name, value in scenarios.items()}
    pairs = (od_inputs or ODInputs([], {})).pairs
    for row in pairs:
        if any(not isinstance(row.get(key), (int, np.integer)) or not 0 <= row[key] < universe.n
               for key in ("_origin", "_dest")):
            raise ValueError("OD indices must reference original graph nodes")
    maximum = max(connectivity_samples, travel_time_samples)
    if uniform_samples is not None:
        uniform_samples = np.asarray(uniform_samples, dtype=float)
        if (uniform_samples.shape != (maximum, len(active)) or not np.isfinite(uniform_samples).all()
                or (uniform_samples < 0).any() or (uniform_samples > 1).any()):
            raise ValueError("uniform_samples must have shape (max_samples, active_links) with finite values in [0,1]")
    row_bytes = max(1, universe.n) * 8 * 8
    if budget_bytes < row_bytes:
        raise ValueError("memory budget too small for one travel-time row")
    prepared = prepare_time_model(graph, time_config or TravelTimeConfig(), time_model)
    time_reason = None if prepared.summary["status"] == "computed" else prepared.summary["status"]
    evaluated_samples = max(connectivity_samples, travel_time_samples if not time_reason else 0)
    topology = ActiveEdgeGraph(graph, active, directed=True)
    times = None if time_reason else TimeTopology(graph, active, prepared)
    baseline_matrix = times.csr(np.ones(len(active), dtype=bool)) if times else None
    cache_bytes = universe.n ** 2 * 8
    cache = dijkstra(baseline_matrix, directed=True) if times and cache_bytes + row_bytes <= budget_bytes // 2 else None
    available = budget_bytes - (cache_bytes if cache is not None else 0)
    workers = min(n_jobs, evaluated_samples, max(1, available // row_bytes))
    chunk_rows = max(1, min(universe.n, available // workers // row_bytes))
    baseline_od = []
    for row in pairs:
        value = (cache[row["_origin"], row["_dest"]] if cache is not None else
            dijkstra(baseline_matrix, directed=True, indices=row["_origin"])[row["_dest"]]) if times else math.inf
        baseline_od.append(float(value) if math.isfinite(value) else None)

    def sample(index):
        uniforms = (uniform_samples[index] if uniform_samples is not None else
                    np.random.default_rng(np.random.SeedSequence([seed, index])).random(len(active)))
        output = {}
        for name, probability in probabilities.items():
            up = (uniforms >= probability) & (probability < 1)
            closed = [row["link_id"] for row, state in zip(active, up) if not state]
            conn, labels = _connectivity(topology.csr(removed_links=closed), universe)
            mutual = np.array([labels[row["_origin"]] == labels[row["_dest"]] for row in pairs], dtype=float)
            travel, od_time = np.zeros((universe.n, 2)), np.zeros(len(pairs))
            if times and index < travel_time_samples:
                damaged_matrix = times.csr(up, index)
                for start in range(0, universe.n, chunk_rows):
                    origins = np.arange(start, min(universe.n, start + chunk_rows))
                    before = cache[origins] if cache is not None else dijkstra(baseline_matrix, directed=True, indices=origins)
                    damaged = dijkstra(damaged_matrix, directed=True, indices=origins)
                    success = _time_success(before, damaged, time_threshold)
                    for j, row in enumerate(pairs):
                        if start <= row["_origin"] < start + len(origins):
                            od_time[j] = success[row["_origin"] - start, row["_dest"]]
                    success[np.arange(len(origins)), origins] = False
                    travel[origins, 0] = success.sum(axis=1)
                    # Row-wise sums give identical rounding for every chunk size.
                    travel[origins, 1] = np.sum(success * universe.weights, axis=1)
            tt = (float(travel[:, 0].sum() / universe.denominator) if universe.denominator else 0.,
                  float(universe.weights @ travel[:, 1] / universe.denominator_pop) if universe.denominator_pop else 0.)
            output[name] = (conn, tt, mutual, od_time)
        return output

    totals = {name: np.zeros((2, 2)) for name in scenarios}
    od_totals = np.zeros((2, len(pairs)))
    indices = iter(range(evaluated_samples))
    executor = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
    try:
        while batch := list(islice(indices, workers * 2)):
            results = executor.map(sample, batch) if executor else map(sample, batch)
            for index, result in zip(batch, results):
                for name, (conn, tt, mutual, od_time) in result.items():
                    if index < connectivity_samples:
                        totals[name][0] += conn
                        if name == "primary":
                            od_totals[0] += mutual
                    if index < travel_time_samples:
                        totals[name][1] += tt
                        if name == "primary":
                            od_totals[1] += od_time
    finally:
        if executor:
            executor.shutdown(wait=True, cancel_futures=True)
    structural_reason = None if universe.denominator else "no distinct original node pairs"
    population_reason = None if universe.denominator_pop else POPULATION_REASON
    results = {}
    for name, total in totals.items():
        result = {"p0": scenarios[name]}
        for column, group, reason in ((0, "unweighted", structural_reason), (1, "population_weighted", population_reason)):
            result[group] = {
                "connectivity_reliability": _score(total[0, column], connectivity_samples, CONNECTIVITY, reason),
                "travel_time_reliability": _score(total[1, column], travel_time_samples, TRAVEL_TIME, time_reason or reason)}
        results[name] = result
    summary = {**results["primary"], "scenarios": results, "time_threshold": time_threshold,
        "speed_source": dict(prepared.summary), "time_model": dict(prepared.summary), "seed": seed,
        "failure_model": "independent physical-link closures during one event/scenario; not annual probabilities",
        "sampling": "common per-link uniforms; SeedSequence([seed, sample_index]); all original origins and pairs",
        "od_warnings": (od_inputs or ODInputs([], {})).warnings}
    od_rows = []
    for i, row in enumerate(pairs):
        connectivity = _score(od_totals[0, i], connectivity_samples, "mutual directed connectivity of snapped OD nodes")
        travel = _score(od_totals[1, i], travel_time_samples, TRAVEL_TIME,
                        time_reason or ("no finite intact directed OD travel time" if baseline_od[i] is None else None))
        od_rows.append({**{key: value for key, value in row.items() if not key.startswith("_")},
            "baseline_time_seconds": baseline_od[i], "connectivity_reliability": connectivity["value"],
            "connectivity_ci_low": connectivity["ci_low"], "connectivity_ci_high": connectivity["ci_high"],
            "travel_time_reliability": travel["value"], "travel_time_ci_low": travel["ci_low"],
            "travel_time_ci_high": travel["ci_high"], "travel_time_reason": travel["reason"]})
    return ReliabilityResult(summary, od_rows, {"reliability_workers": workers,
        "travel_time_chunk_rows": chunk_rows, "baseline_time_cache": cache is not None,
        "memory_budget_bytes": budget_bytes, "all_origins": universe.n,
        "connectivity_samples_evaluated": connectivity_samples,
        "travel_time_samples_evaluated": travel_time_samples if times else 0})


def write_od_reliability(result, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=OD_OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(result.od_rows)
    return path
