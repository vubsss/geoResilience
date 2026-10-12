"""Directed travel-time reliability with replaceable, additive edge-time models."""

import math
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np
from joblib import Parallel, delayed, parallel_config
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.stats import norm

from .connectivity import BATCH_SIZE, load_od_pairs, wilson_interval
from .failure_probabilities import probabilities_at_p0
from .progress import StageProgress
from .time_models import TimeContext, prepare_time_model

# Logarithmic bins give bounded-memory quantiles. A separate [1,nextafter(1)]
# bin preserves the exact no-detour atom, including an entirely intact run.
HIST_EDGES = np.unique(np.r_[0, np.geomspace(1e-6, 1e6, 4097), np.nextafter(1., np.inf), np.inf])


class TravelTimeTopology:
    """Rebuild minimum-cost parallel arcs after physical closures."""

    def __init__(self, graph, links, prepared):
        self.node_ids = list(graph)
        if not self.node_ids:
            raise ValueError("travel_time requires a nonempty graph")
        index = {node: i for i, node in enumerate(self.node_ids)}
        self.link_ids = [link["link_id"] for link in links if not link["is_self_loop"]]
        arcs = [(index[u], index[v], position, (u, v, key))
                for position, link in enumerate(link for link in links if not link["is_self_loop"])
                for u, v, key in link["_edges"]]
        arcs.sort(key=lambda arc: (arc[0], arc[1]))
        self.rows = np.array([arc[0] for arc in arcs], dtype=np.int64)
        self.cols = np.array([arc[1] for arc in arcs], dtype=np.int64)
        self.arc_links = np.array([arc[2] for arc in arcs], dtype=np.int64)
        self.edges = [arc[3] for arc in arcs]
        self.prepared = prepared
        self.baseline_costs = self._values(prepared.costs(TimeContext()))

    def _values(self, mapping):
        try:
            values = np.array([float(mapping[edge]) for edge in self.edges])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("travel_time: model must supply numeric seconds for every directed non-loop edge") from exc
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError("travel_time: model edge seconds must be finite and strictly positive")
        return values

    def csr(self, up, sample_index=None):
        if sample_index is not None and self.prepared.scenario_times is not None:
            closed = frozenset(link for link, state in zip(self.link_ids, up) if not state)
            values = self._values(self.prepared.costs(TimeContext(sample_index, closed)))
        else:
            values = self.baseline_costs
        keep = np.asarray(up, dtype=bool)[self.arc_links]
        rows, cols, values = self.rows[keep], self.cols[keep], values[keep]
        if len(rows):
            starts = np.flatnonzero(np.r_[True, (rows[1:] != rows[:-1]) | (cols[1:] != cols[:-1])])
            values = np.minimum.reduceat(values, starts)
            rows, cols = rows[starts], cols[starts]
        return csr_matrix((values, (rows, cols)), shape=(len(self.node_ids), len(self.node_ids)))


def time_success(baseline, damaged, tau):
    """Finite directed reachability and inclusive delay bound (seconds)."""
    # A small absolute/relative tolerance handles equivalent sums of edge costs.
    with np.errstate(over="ignore", invalid="ignore"):
        threshold = (1 + tau)*baseline
        tolerance = 1e-9 + 1e-12*np.abs(threshold)
        return np.isfinite(baseline) & np.isfinite(damaged) & (damaged <= threshold+tolerance)


def histogram_quantiles(counts):
    total = int(counts.sum())
    result, bounds = {}, {}
    cumulative = counts.cumsum()
    for name, probability in (("p50", .5), ("p90", .9), ("p99", .99)):
        if not total:
            result[name], bounds[name] = None, None
            continue
        index = int(np.searchsorted(cumulative, math.ceil(total*probability)))
        low, high = HIST_EDGES[index:index+2]
        if low == 0 or not math.isfinite(high):
            result[name], bounds[name] = None, [float(low), float(high) if math.isfinite(high) else None]
        else:
            result[name], bounds[name] = float(math.sqrt(low)*math.sqrt(high)), [float(low), float(high)]
    return result, bounds


@dataclass
class _TimeBatch:
    fractions: np.ndarray
    origin_sum: np.ndarray
    origin_square: np.ndarray
    od_counts: np.ndarray
    histogram: np.ndarray


@contextmanager
def _baseline_map(path, shape, mode):
    baseline = np.memmap(path, dtype=np.float64, mode=mode, shape=shape)
    try:
        yield baseline
    finally:
        # Tracebacks and array views can retain the mapping after del baseline.
        # Close it explicitly so Windows can remove the temporary file on errors.
        baseline._mmap.close()


def _time_batch(topology, probabilities, origins, sampled_count, pairs, baseline_path,
                chunk_rows, tau, seed, sample_start, samples):
    rng = np.random.default_rng(seed)
    n = len(topology.node_ids)
    with _baseline_map(baseline_path, (len(origins), n), "r") as baseline:
        result = _TimeBatch(np.empty(samples), np.zeros(sampled_count), np.zeros(sampled_count),
                            np.zeros(len(pairs), dtype=np.int64), np.zeros(len(HIST_EDGES)-1, dtype=np.int64))
        pairs_by_origin = {}
        for index, row in enumerate(pairs):
            pairs_by_origin.setdefault(row["_origin"], []).append((index, row["_dest"]))
        for sample in range(samples):
            up = rng.random(len(probabilities)) >= probabilities
            graph = topology.csr(up, sample_start+sample)
            successes = 0
            for start in range(0, len(origins), chunk_rows):
                end = min(len(origins), start+chunk_rows)
                source_ids = origins[start:end]
                damaged = dijkstra(graph, directed=True, indices=source_ids)
                intact = baseline[start:end]
                okay = time_success(intact, damaged, tau)
                # Explicit OD self-pairs succeed; self-pairs never inflate network scores.
                for row_index, origin in enumerate(source_ids):
                    for od_index, dest in pairs_by_origin.get(int(origin), ()):
                        result.od_counts[od_index] += bool(okay[row_index, dest])
                    okay[row_index, origin] = False
                count = min(end, sampled_count)-start
                if count > 0:
                    values = okay[:count].sum(axis=1)/(n-1) if n > 1 else np.zeros(count)
                    successes += int(okay[:count].sum())
                    result.origin_sum[start:start+count] += values
                    result.origin_square[start:start+count] += values*values
                    base, changed = intact[:count], damaged[:count]
                    valid = np.isfinite(base) & np.isfinite(changed) & (base > 0)
                    with np.errstate(over="ignore", invalid="ignore"):
                        ratios = changed[valid]/base[valid]
                    result.histogram += np.histogram(ratios, bins=HIST_EDGES)[0]
            result.fractions[sample] = successes/(sampled_count*(n-1)) if n > 1 else math.nan
    return result


def _normal_interval(mean, square_sum, samples):
    variance = np.maximum(0, (square_sum-samples*mean*mean)/(samples-1))
    half = norm.ppf(.975)*np.sqrt(variance/samples)
    return np.maximum(0, mean-half), np.minimum(1, mean+half)


@dataclass
class TravelTimeResult:
    summary: dict
    node_metrics: dict
    od_metrics: dict
    pair_fractions: np.ndarray
    runtime_seconds: dict
    computation: dict


def compute_travel_time(graph, links, config, reliability_config, user_probabilities, *, seed,
                        n_jobs, budget_bytes, od_inputs=None, prepared=None, time_model=None):
    started = perf_counter()
    prepared = prepare_time_model(graph, config, time_model) if prepared is None else prepared
    empty_nodes = {node: {"p_tt_ok": None, "p_tt_ok_ci_low": None, "p_tt_ok_ci_high": None} for node in graph}
    settings = {"tau": config.tau, "samples": config.samples, "seed": seed,
                "requested_n_origins": config.n_origins, "primary_p0": reliability_config.p0}
    if prepared.summary["status"] != "computed":
        return TravelTimeResult({**prepared.summary, **settings}, empty_nodes, {}, np.empty(0),
                                {"travel_time_reliability": perf_counter()-started}, {})
    if n_jobs < 1 or budget_bytes < 1:
        raise ValueError("travel_time n_jobs and budget_bytes must be positive")
    topology = TravelTimeTopology(graph, links, prepared)
    n = len(graph)
    od_inputs = load_od_pairs(graph, reliability_config.od_pairs_csv) if od_inputs is None else od_inputs
    # Origin selection and failures have independent namespaces. Changing tau,
    # chunking, OD inputs or worker count does not alter the closure stream.
    origin_rng = np.random.default_rng(np.random.SeedSequence([seed, 10, 0]))
    sampled = np.sort(origin_rng.choice(n, size=min(n, config.n_origins), replace=False))
    extras = sorted({row["_origin"] for row in od_inputs.pairs} - set(sampled))
    origins = np.r_[sampled, extras].astype(np.int64)
    probabilities = probabilities_at_p0(links, user_probabilities, reliability_config.p0)
    probabilities = np.array([probabilities[link] for link in topology.link_ids])
    batches = math.ceil(config.samples/BATCH_SIZE)
    histogram_bytes = (len(HIST_EDGES)-1)*8
    parent_bytes = (config.samples*8 + 128*(n+len(origins)+len(links)+len(od_inputs.pairs))
                    + len(topology.edges)*64 + histogram_bytes)
    worker_fixed = 80*(n+len(topology.edges)+len(links)+len(origins)) + histogram_bytes + BATCH_SIZE*8
    row_bytes = max(1, n*8*6)
    available = budget_bytes-parent_bytes
    if available < worker_fixed+row_bytes:
        raise ValueError("analysis.max_memory_gb is too small for travel-time working arrays")
    useful_jobs = max(1, config.samples*len(origins)*(n+len(topology.edges))//200000)
    jobs = min(n_jobs, batches, useful_jobs, available//(worker_fixed+row_bytes))
    chunk_rows = min(64, len(origins), max(1, (available//jobs-worker_fixed)//row_bytes))
    fractions = np.empty(config.samples)
    combined = _TimeBatch(fractions, np.zeros(len(sampled)), np.zeros(len(sampled)),
                          np.zeros(len(od_inputs.pairs), dtype=np.int64),
                          np.zeros(len(HIST_EDGES)-1, dtype=np.int64))
    seeds = np.random.SeedSequence([seed, 10, 1]).spawn(batches)
    baseline_unreachable, od_baseline = 0, {}
    with TemporaryDirectory(prefix="georesilience-times-") as temporary:
        baseline_path = Path(temporary)/"baseline.bin"
        with _baseline_map(baseline_path, (len(origins), n), "w+") as baseline:
            intact = topology.csr(np.ones(len(topology.link_ids), dtype=bool))
            with StageProgress("Travel-time baseline origins", len(origins)) as progress:
                for start in range(0, len(origins), chunk_rows):
                    end = min(len(origins), start+chunk_rows)
                    baseline[start:end] = dijkstra(intact, directed=True, indices=origins[start:end])
                    count = min(end, len(sampled))-start
                    if count > 0:
                        baseline_unreachable += int((~np.isfinite(baseline[start:start+count])).sum())
                    for origin in origins[start:end]:
                        progress.advance()
            positions = {int(origin): index for index, origin in enumerate(origins)}
            for row in od_inputs.pairs:
                value = baseline[positions[row["_origin"]], row["_dest"]]
                od_baseline[row["label"]] = float(value/60) if math.isfinite(value) else None
            baseline.flush()

        def collect(results):
            offset = 0
            with StageProgress("Travel-time Monte Carlo batches", batches) as progress:
                for result in results:
                    end = offset+len(result.fractions)
                    fractions[offset:end] = result.fractions
                    for name in ("origin_sum", "origin_square", "od_counts", "histogram"):
                        getattr(combined, name)[:] += getattr(result, name)
                    offset = end
                    progress.advance()

        arguments = [(seeds[index], index*BATCH_SIZE, min(BATCH_SIZE, config.samples-index*BATCH_SIZE))
                     for index in range(batches)]
        def tasks():
            for child, start, count in arguments:
                yield delayed(_time_batch)(topology, probabilities, origins, len(sampled), od_inputs.pairs,
                                           baseline_path, chunk_rows, config.tau, child, start, count)
        if jobs == 1:
            collect(_time_batch(topology, probabilities, origins, len(sampled), od_inputs.pairs,
                                baseline_path, chunk_rows, config.tau, child, start, count)
                    for child, start, count in arguments)
        else:
            with parallel_config(backend="loky", inner_max_num_threads=1):
                with Parallel(n_jobs=jobs, return_as="generator", batch_size=1, pre_dispatch=jobs) as parallel:
                    collect(parallel(tasks()))
    means = combined.origin_sum/config.samples
    lows, highs = _normal_interval(means, combined.origin_square, config.samples)
    node_metrics = empty_nodes
    for index, origin in enumerate(sampled):
        node_metrics[topology.node_ids[origin]] = {
            "p_tt_ok": float(means[index]) if n > 1 else None,
            "p_tt_ok_ci_low": float(lows[index]) if n > 1 else None,
            "p_tt_ok_ci_high": float(highs[index]) if n > 1 else None}
    od_low, od_high = wilson_interval(combined.od_counts, config.samples)
    od_metrics = {row["label"]: {"p_tt_ok": float(combined.od_counts[index]/config.samples),
                                 "p_tt_ok_ci_low": float(od_low[index]), "p_tt_ok_ci_high": float(od_high[index]),
                                 "tt0_min": od_baseline[row["label"]]}
                  for index, row in enumerate(od_inputs.pairs)}
    from .connectivity import mean_interval
    network = mean_interval(fractions)
    quantiles, bounds = histogram_quantiles(combined.histogram)
    summary = {**prepared.summary, **settings,
               "tt_reliability": network["conn_reliability"], "ci_low": network["ci_low"], "ci_high": network["ci_high"],
               "n_origins": len(sampled), "routing_origins_including_od": len(origins),
               "origin_node_ids": [str(topology.node_ids[index]) for index in sampled],
               "baseline_unreachable_pairs": baseline_unreachable,
               "network_measure": "directed_pairs_within_relative_time_threshold",
               "self_pairs": "excluded from network and ratios; same-node OD succeeds",
               "ci_methods": {"network": "normal interval across sample fractions",
                              "origin": "normal interval across sample destination fractions", "od": "Wilson binomial"},
               "confidence_level": .95, "ci_scope": "closure sampling conditional on fixed selected origins and time model",
               "batch_size": BATCH_SIZE, "batch_count": batches,
               "detour_factor_percentiles": quantiles, "detour_factor_bounds": bounds,
               "detour_histogram": {"method": "fixed logarithmic bins; exact no-detour atom",
                                     "reachable_pair_observations": int(combined.histogram.sum()),
                                     "underflow_count": int(combined.histogram[0]),
                                     "overflow_count": int(combined.histogram[-1]),
                                     "scope": "sampled origins, distinct destinations, finite positive baseline"},
               "od_pairs": [{"label": row["label"], **od_metrics[row["label"]]} for row in od_inputs.pairs]}
    return TravelTimeResult(summary, node_metrics, od_metrics, fractions,
                            {"travel_time_reliability": perf_counter()-started},
                            {"travel_time_workers": int(jobs), "travel_time_chunk_rows": int(chunk_rows),
                             "travel_time_estimated_working_bytes": int(parent_bytes+jobs*(worker_fixed+chunk_rows*row_bytes)),
                             "travel_time_baseline_disk_bytes": int(len(origins)*n*8)})


def travel_time_report(summary):
    lines = ["Travel-time reliability", f"Status: {summary['status']}; time model: {summary['time_model']}"]
    if "assumptions" in summary:
        lines.append(summary["assumptions"])
    if summary["status"] != "computed":
        return lines
    lines.extend([f"Time function: {summary['time_function']}",
                  f"Acceptable time: <= (1 + tau) * baseline; tau={summary['tau']:g} ({100*summary['tau']:g}% extra).",
                  f"Samples: {summary['samples']}; seed: {summary['seed']}; sampled origins: {summary['n_origins']}; "
                  f"routing origins including OD: {summary['routing_origins_including_od']}"])
    value = summary["tt_reliability"]
    lines.append(f"tt_reliability (95% CI): {value:.6f} [{summary['ci_low']:.6f}, {summary['ci_high']:.6f}]"
                 if value is not None else "tt_reliability: undefined (no distinct node pairs)")
    lines.extend(["Network: equally weighted directed pairs from sampled origins to distinct destinations.",
                  f"Baseline unreachable pairs: {summary['baseline_unreachable_pairs']} (counted as failures).",
                  "Node p_tt_ok averages destination success across samples; unsampled origins are null."])
    coverage = summary.get("maxspeed_coverage")
    if coverage is not None:
        lines.append("Speed coverage (physical road length split across directed edges):")
        lines.extend(f"{name}: {row['length_pct']:.2f}% ({row['length_m']/1000:.3f} km)" for name, row in coverage.items()
                     if row["length_pct"] is not None)
        lines.append(f"Unusable maxspeed tags on non-loop directed edges: {summary['invalid_maxspeed_edges']}")
    else:
        lines.append("Speed coverage: not applicable to this time model.")
    lines.append("Reachable-pair travel-time factors (damaged / baseline), approximate histogram percentiles:")
    for name, value in summary["detour_factor_percentiles"].items():
        bounds = summary["detour_factor_bounds"][name]
        lines.append(f"{name}: {value:.6f} (bin bounds {bounds[0]:.6f}, {bounds[1]:.6f})"
                     if value is not None else f"{name}: unavailable (no observations or outside histogram range)")
    histogram = summary["detour_histogram"]
    lines.append(f"Histogram observations: {histogram['reachable_pair_observations']}; "
                 f"underflow/overflow: {histogram['underflow_count']}/{histogram['overflow_count']}")
    lines.append("OD travel-time reliability (95% Wilson CI; baseline minutes):")
    if not summary["od_pairs"]:
        lines.append("No OD pairs supplied.")
    for row in summary["od_pairs"]:
        baseline = f"{row['tt0_min']:.6f}" if row["tt0_min"] is not None else "unreachable"
        lines.append(f"{row['label']}: baseline={baseline}; p_tt_ok={row['p_tt_ok']:.6f} "
                     f"[{row['p_tt_ok_ci_low']:.6f}, {row['p_tt_ok_ci_high']:.6f}]")
    lines.extend(["CIs cover closure sampling for fixed origins/time model; origin selection and speed uncertainty are excluded.",
                  "Normal intervals are approximate; constant observed scores can hide rare journey failures.",
                  "Same-node OD succeeds; self-pairs are excluded from network scores and travel-time factors.",
                  "Closures use primary p0 and an independent Ticket 10 seed stream; connectivity samples differ."])
    return lines
