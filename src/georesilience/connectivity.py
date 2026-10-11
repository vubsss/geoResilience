"""Independent-link Monte Carlo for mutual connectivity and directed OD reachability."""

import csv
import math
import warnings
from dataclasses import dataclass
from time import perf_counter

import numpy as np
import pandas as pd
from joblib import Parallel, delayed, parallel_config
from pyproj import CRS, Transformer
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import breadth_first_order, connected_components
from scipy.spatial import cKDTree
from scipy.stats import norm, t

from .failure_probabilities import probabilities_at_p0
from .progress import StageProgress
from .removal import ActiveEdgeGraph, node_weights

BATCH_SIZE = 256
OD_COLUMNS = ("label", "origin_lon", "origin_lat", "dest_lon", "dest_lat")
OD_OUTPUT_COLUMNS = (*OD_COLUMNS, "origin_node_id", "dest_node_id", "origin_snap_m",
                     "dest_snap_m", "p_od", "ci_low", "ci_high")


def node_id_key(node):
    """Numeric IDs sort numerically; other IDs lexically, with a stable type tie."""
    try:
        return (0, int(str(node)), type(node).__name__)
    except ValueError:
        return (1, str(node), type(node).__name__)


@dataclass
class ODInputs:
    pairs: list
    warnings: dict


def load_od_pairs(graph, path=None):
    """Snap WGS84 CSV endpoints to metric graph nodes, reusable by Ticket 10."""
    notices = {"total_count": 0, "shown": [], "omitted_count": 0}
    if path is None:
        return ODInputs([], notices)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", pd.errors.ParserWarning)
            frame = pd.read_csv(path, comment="#", dtype=str, keep_default_na=False, index_col=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, pd.errors.ParserWarning) as exc:
        raise ValueError(f"od_pairs_csv: invalid CSV: {exc}") from exc
    missing = set(OD_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"od_pairs_csv: missing columns: {', '.join(sorted(missing))}")
    records, errors, seen = [], [], set()
    for number, values in enumerate(frame[list(OD_COLUMNS)].itertuples(index=False, name=None), 1):
        label = str(values[0]).strip()
        if not label or label in seen:
            errors.append(f"OD data row {number}: label must be nonempty and unique: {label!r}")
        seen.add(label)
        try:
            coords = [float(value) for value in values[1:]]
            if not all(math.isfinite(value) for value in coords):
                raise ValueError
            if not (-180 <= coords[0] <= 180 and -90 <= coords[1] <= 90
                    and -180 <= coords[2] <= 180 and -90 <= coords[3] <= 90):
                raise ValueError
        except (ValueError, TypeError):
            errors.append(f"OD data row {number} ({label!r}): coordinates must be finite WGS84 lon/lat")
            continue
        records.append(dict(zip(OD_COLUMNS, [label, *coords])))
    if errors:
        raise ValueError("od_pairs_csv validation failed:\n" + "\n".join(errors))
    if not records:
        return ODInputs([], notices)
    crs = CRS.from_user_input(graph.graph.get("crs"))
    if not crs.is_projected or any(not math.isclose(axis.unit_conversion_factor, 1)
                                   for axis in crs.axis_info[:2]):
        raise ValueError("OD snapping requires a projected graph CRS with metre units")
    node_ids = list(graph)
    if not node_ids:
        raise ValueError("OD snapping requires a nonempty graph")
    coordinates = np.array([[graph.nodes[node]["x"], graph.nodes[node]["y"]] for node in node_ids])
    if not np.isfinite(coordinates).all():
        raise ValueError("OD snapping requires finite node coordinates")
    tree = cKDTree(coordinates)
    transform = Transformer.from_crs(4326, crs, always_xy=True)
    for row in records:
        for endpoint in ("origin", "dest"):
            point = np.array(transform.transform(row[f"{endpoint}_lon"], row[f"{endpoint}_lat"]))
            if not np.isfinite(point).all():
                raise ValueError(f"OD {row['label']!r}: endpoint cannot be projected into the graph CRS")
            distance, nearest = tree.query(point)
            # Resolve coincident/equidistant nodes by the same ID order as SCC ties.
            candidates = tree.query_ball_point(point, distance + max(1e-8, distance * 1e-12))
            nearest = min(candidates, key=lambda index: (node_id_key(node_ids[index])))
            actual = np.linalg.norm(coordinates[nearest] - point)
            if not math.isclose(actual, distance, rel_tol=1e-12, abs_tol=1e-8):
                nearest = int(tree.query(point)[1])
                actual = np.linalg.norm(coordinates[nearest] - point)
            row[f"_{endpoint}"] = int(nearest)
            row[f"{endpoint}_node_id"] = str(node_ids[nearest])
            row[f"{endpoint}_snap_m"] = float(actual)
            if actual > 500:
                notices["total_count"] += 1
                if len(notices["shown"]) < 20:
                    notices["shown"].append(
                        f"OD {row['label']!r}: {endpoint} snap distance {actual:.1f} m exceeds 500 m")
    notices["omitted_count"] = notices["total_count"] - len(notices["shown"])
    return ODInputs(records, notices)


def wilson_interval(successes, samples, confidence=.95):
    """Wilson binomial interval, scalar or array, with exact bounded endpoints."""
    if samples < 1 or not 0 < confidence < 1:
        raise ValueError("Wilson interval requires samples >= 1 and confidence in (0,1)")
    count = np.asarray(successes, dtype=float)
    if not np.isfinite(count).all() or (count < 0).any() or (count > samples).any():
        raise ValueError("success counts must lie between zero and samples")
    z = norm.ppf((1 + confidence) / 2)
    p = count / samples
    divisor = 1 + z*z / samples
    centre = (p + z*z / (2*samples)) / divisor
    half = z * np.sqrt(p*(1-p)/samples + z*z/(4*samples*samples)) / divisor
    low, high = np.maximum(0, centre-half), np.minimum(1, centre+half)
    low, high = np.where(count == 0, 0, low), np.where(count == samples, 1, high)
    return low, high


def mean_interval(values, confidence=.95):
    """Normal Monte Carlo mean interval; undefined pair universes return nulls."""
    values = np.asarray(values, dtype=float)
    if len(values) < 2 or not 0 < confidence < 1:
        raise ValueError("mean interval requires at least two samples and confidence in (0,1)")
    if not np.isfinite(values).all():
        return {"conn_reliability": None, "ci_low": None, "ci_high": None}
    mean = float(values.mean())
    half = float(norm.ppf((1 + confidence)/2) * values.std(ddof=1) / math.sqrt(len(values)))
    return {"conn_reliability": mean, "ci_low": max(0.0, mean-half), "ci_high": min(1.0, mean+half)}


class ConnectivityTopology:
    """Binary CSR topology; retain parallel roads until every supplying road fails."""

    def __init__(self, graph, links, weights=None):
        active = ActiveEdgeGraph(graph, links, directed=True)
        self.node_ids = active.node_ids
        self.n = len(self.node_ids)
        if not self.n:
            raise ValueError("connectivity reliability requires a nonempty graph")
        self.link_ids = [link["link_id"] for link in links if not link["is_self_loop"]]
        positions = {link: index for index, link in enumerate(self.link_ids)}
        self.rows, self.cols = active.rows, active.cols
        self.arc_links = np.array([positions[int(link)] for link in active.link_ids], dtype=np.int64)
        self.weights = node_weights(self.n, weights)
        maximum = self.weights.max(initial=0)
        if maximum:
            self.weights = self.weights / maximum  # pair ratios are invariant to weight units
        self.denominator = float(self.weights @ (self.weights.sum() - self.weights))
        self.tie_order = np.array(sorted(range(self.n), key=lambda i: node_id_key(self.node_ids[i])))

    def csr(self, up):
        keep = np.asarray(up, dtype=bool)[self.arc_links]
        return csr_matrix((np.ones(np.count_nonzero(keep), dtype=bool),
                           (self.rows[keep], self.cols[keep])), shape=(self.n, self.n))

    def evaluate(self, up, pairs=(), *, details=True):
        graph = self.csr(up)
        count, labels = connected_components(graph, directed=True, connection="strong")
        if self.denominator <= 0:
            score = math.nan
        elif count == 1:
            score = 1.0
        else:
            masses = np.bincount(labels, weights=self.weights, minlength=count)
            score = float(self.weights @ (masses[labels] - self.weights) / self.denominator)
            score = min(1.0, max(0.0, score))
        if not details:
            return score, None, None
        sizes = np.bincount(labels, minlength=count)
        tied = sizes == sizes.max()
        first = self.tie_order[np.argmax(tied[labels[self.tie_order]])]
        main = labels == labels[first]
        od = np.array([labels[row["_origin"]] == labels[row["_dest"]] for row in pairs], dtype=bool)
        origins = {pairs[index]["_origin"] for index in np.flatnonzero(~od)}
        for origin in sorted(origins):
            reached = np.zeros(self.n, dtype=bool)
            reached[breadth_first_order(graph, origin, directed=True, return_predecessors=False)] = True
            for index, row in enumerate(pairs):
                if row["_origin"] == origin:
                    od[index] = reached[row["_dest"]]
        return score, main, od


@dataclass
class _Batch:
    fractions: np.ndarray
    node_counts: np.ndarray
    od_counts: np.ndarray
    down_counts: np.ndarray
    down_sum: np.ndarray
    down_square: np.ndarray
    up_sum: np.ndarray
    up_square: np.ndarray


def _sample_batch(topology, probabilities, primary, pairs, seed, samples):
    rng = np.random.default_rng(seed)
    m = len(topology.link_ids)
    result = _Batch(np.empty((samples, len(probabilities))), np.zeros(topology.n, dtype=np.int64),
                    np.zeros(len(pairs), dtype=np.int64), np.zeros(m, dtype=np.int64),
                    *[np.zeros(m) for _ in range(4)])
    baseline = topology.evaluate(np.ones(m, dtype=bool), pairs)
    previous = [None] * len(probabilities)
    for index in range(samples):
        uniform = rng.random(m)
        for scenario, probability in enumerate(probabilities):
            up = uniform >= probability
            if up.all():
                value, main, od = baseline
            elif previous[scenario] is not None and np.array_equal(up, previous[scenario][0]):
                value, main, od = previous[scenario][1]
            else:
                value, main, od = topology.evaluate(up, pairs, details=scenario == primary)
                previous[scenario] = (up, (value, main, od))
            result.fractions[index, scenario] = value
            if scenario == primary:
                result.node_counts += main
                result.od_counts += od
                down = ~up
                result.down_counts += down
                if math.isfinite(value):
                    result.down_sum += down * value
                    result.down_square += down * value*value
                    result.up_sum += up * value
                    result.up_square += up * value*value
    return result


def _importance(down, down_sum, down_square, up_sum, up_square, samples, config, defined):
    up = samples - down
    common = {"rel_down_count": int(down), "rel_up_count": int(up),
              "rel_importance": None, "rel_importance_ci_low": None, "rel_importance_ci_high": None}
    if not defined:
        status = "undefined_pair_universe"
    elif down < config.min_down_count:
        status = "insufficient_down"
    elif up < config.min_up_count:
        status = "insufficient_up"
    else:
        mean_up, mean_down = up_sum/up, down_sum/down
        difference = float(mean_up - mean_down)
        var_up = max(0.0, (up_square - up_sum*up_sum/up)/(up-1)) / up
        var_down = max(0.0, (down_square - down_sum*down_sum/down)/(down-1)) / down
        variance = var_up + var_down
        divisor = var_up*var_up/(up-1) + var_down*var_down/(down-1)
        half = (float(t.ppf(.975, variance*variance/divisor)) * math.sqrt(variance)
                if divisor > 0 else 0.0)
        common.update(rel_importance=difference, rel_importance_ci_low=max(-1.0, difference-half),
                      rel_importance_ci_high=min(1.0, difference+half))
        status = "estimated"
    return {**common, "rel_importance_status": status}


@dataclass
class ConnectivityResult:
    summary: dict
    node_metrics: dict
    link_metrics: dict
    od_rows: list
    pair_fractions: np.ndarray
    runtime_seconds: dict
    computation: dict


def compute_connectivity(graph, links, config, user_probabilities, *, seed, n_jobs, budget_bytes,
                         weights=None, od_inputs=None):
    started = perf_counter()
    if n_jobs < 1 or budget_bytes < 1:
        raise ValueError("connectivity n_jobs and budget_bytes must be positive")
    topology = ConnectivityTopology(graph, links, weights)
    od_inputs = load_od_pairs(graph, config.od_pairs_csv) if od_inputs is None else od_inputs
    vectors, sweep_indices = [], []
    for p0 in config.p0_sweep:
        mapping = probabilities_at_p0(links, user_probabilities, p0)
        vector = np.array([mapping[link] for link in topology.link_ids])
        same = next((index for index, old in enumerate(vectors) if np.array_equal(vector, old)), None)
        if same is None:
            same = len(vectors)
            vectors.append(vector)
        sweep_indices.append(same)
    primary = sweep_indices[config.p0_sweep.index(config.p0)]
    batches = math.ceil(config.samples / BATCH_SIZE)
    seeds = np.random.SeedSequence([seed, 9]).spawn(batches)
    # O(nodes + arcs + links) per worker and O(samples*sweep) in the parent.
    # Budget estimates are conservative working-array estimates, excluding Python/runtime overhead.
    parent_bytes = config.samples * len(vectors) * 8 + 128*(topology.n + len(topology.link_ids) + len(od_inputs.pairs))
    worker_bytes = max(1, 128*(topology.n + len(topology.link_ids) + len(topology.rows))
                       + BATCH_SIZE*len(vectors)*8)
    if parent_bytes + worker_bytes > budget_bytes:
        raise ValueError("analysis.max_memory_gb is too small for connectivity working arrays")
    useful_jobs = max(1, config.samples*(topology.n + len(topology.rows))*len(vectors)//500000)
    jobs = min(n_jobs, batches, useful_jobs, max(1, (budget_bytes - parent_bytes)//worker_bytes))
    tasks = [(seeds[index], min(BATCH_SIZE, config.samples-index*BATCH_SIZE)) for index in range(batches)]
    fractions = np.empty((config.samples, len(vectors)))
    combined = _Batch(fractions, np.zeros(topology.n, dtype=np.int64),
                      np.zeros(len(od_inputs.pairs), dtype=np.int64),
                      np.zeros(len(topology.link_ids), dtype=np.int64),
                      *[np.zeros(len(topology.link_ids)) for _ in range(4)])

    def collect(results):
        offset = 0
        with StageProgress("Connectivity Monte Carlo batches", batches) as progress:
            for result in results:
                end = offset + len(result.fractions)
                fractions[offset:end] = result.fractions
                for name in ("node_counts", "od_counts", "down_counts", "down_sum", "down_square", "up_sum", "up_square"):
                    getattr(combined, name)[:] += getattr(result, name)
                offset = end
                progress.advance()

    if jobs == 1:
        collect(_sample_batch(topology, vectors, primary, od_inputs.pairs, child, count)
                for child, count in tasks)
    else:
        with parallel_config(backend="loky", inner_max_num_threads=1):
            with Parallel(n_jobs=jobs, return_as="generator", batch_size=1, pre_dispatch=jobs) as parallel:
                collect(parallel(delayed(_sample_batch)(topology, vectors, primary, od_inputs.pairs, child, count)
                                 for child, count in tasks))
    node_low, node_high = wilson_interval(combined.node_counts, config.samples)
    node_metrics = {node: {"p_connected": float(combined.node_counts[index]/config.samples),
                          "p_connected_ci_low": float(node_low[index]),
                          "p_connected_ci_high": float(node_high[index])}
                    for index, node in enumerate(topology.node_ids)}
    link_metrics = {}
    for index, link_id in enumerate(topology.link_ids):
        link_metrics[link_id] = _importance(
            combined.down_counts[index], combined.down_sum[index], combined.down_square[index],
            combined.up_sum[index], combined.up_square[index], config.samples, config, topology.denominator > 0)
    for link in links:
        if link["is_self_loop"]:
            link_metrics[link["link_id"]] = {"rel_down_count": 0, "rel_up_count": 0,
                "rel_importance": None, "rel_importance_ci_low": None, "rel_importance_ci_high": None,
                "rel_importance_status": "self_loop"}
    od_low, od_high = wilson_interval(combined.od_counts, config.samples)
    od_rows = [{**{key: value for key, value in row.items() if not key.startswith("_")},
                "p_od": float(combined.od_counts[index]/config.samples),
                "ci_low": float(od_low[index]), "ci_high": float(od_high[index])}
               for index, row in enumerate(od_inputs.pairs)]
    least = [{"node_id": str(node), **node_metrics[node]} for node in sorted(
        topology.node_ids, key=lambda node: (node_metrics[node]["p_connected"], node_id_key(node)))[:20]]
    top_links = [{"link_id": link_id, **row} for link_id, row in sorted(
        link_metrics.items(), key=lambda item: (-(item[1]["rel_importance"] or 0), item[0]))
        if row["rel_importance_status"] == "estimated"][:20]
    primary_values = fractions[:, primary]
    summary = {**mean_interval(primary_values), "samples": config.samples, "seed": seed,
        "primary_p0": config.p0, "network_measure": "mutual_pair_fraction",
        "node_measure": "main_scc_membership", "od_measure": "directed_reachability",
        "failure_model": "independent_physical_links", "node_weights": "uniform" if weights is None else "custom",
        "main_scc_tie_break": "largest node count, then smallest minimum node ID (numeric IDs sort numerically)",
        "pair_universe_status": "defined" if topology.denominator > 0 else "no_positive_weight_distinct_pairs",
        "batch_size": BATCH_SIZE, "batch_count": batches, "common_random_numbers": True,
        "unique_probability_vectors": len(vectors),
        "ci_methods": {"network": "normal mean interval, clipped to [0,1]",
                       "node": "Wilson binomial", "od": "Wilson binomial",
                       "link": "Welch t interval for conditional mean difference, clipped to [-1,1]"},
        "confidence_level": .95,
        "sweep": [{"p0": p0, **mean_interval(fractions[:, index])}
                  for p0, index in zip(config.p0_sweep, sweep_indices)],
        "node": {"p_connected_mean": float(combined.node_counts.mean()/config.samples),
                 "p_connected_p10": float(np.quantile(combined.node_counts/config.samples, .1)),
                 "max_wilson_half_width": float(np.max((node_high-node_low)/2)), "least_reliable": least},
        "link": {"min_down_count": config.min_down_count, "min_up_count": config.min_up_count,
                 "estimated": sum(row["rel_importance_status"] == "estimated" for row in link_metrics.values()),
                 "unavailable": sum(row["rel_importance_status"] != "estimated" for row in link_metrics.values()),
                 "top_importance": top_links},
        "od_pairs": od_rows, "od_warnings": od_inputs.warnings}
    return ConnectivityResult(summary, node_metrics, link_metrics, od_rows, fractions,
                              {"connectivity_reliability": perf_counter()-started},
                              {"reliability_workers": int(jobs),
                               "reliability_estimated_working_bytes": int(parent_bytes + jobs*worker_bytes)})


def write_od_reliability(result, path):
    if not result.od_rows:
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OD_OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(result.od_rows)


def connectivity_report(summary):
    def interval(row, value, low="ci_low", high="ci_high"):
        if row[value] is None:
            return "undefined (no positive-weight distinct node pairs)"
        return f"{row[value]:.6f} [{row[low]:.6f}, {row[high]:.6f}]"

    lines = ["Connectivity reliability", "AP3-inspired connectivity analysis; accessibility-based vulnerability is a later stage.",
             "Network: expected fraction of mutually reachable distinct node pairs (same SCC).",
             "Uniform node pairs represent potential connections, not observed trip demand."
             if summary["node_weights"] == "uniform" else "Node-pair weights are products of the supplied node weights.",
             f"Independent physical-link failures; samples: {summary['samples']}; seed: {summary['seed']}",
             f"Primary p0: {summary['primary_p0']:g}; conn_reliability (95% CI): {interval(summary, 'conn_reliability')}",
             "p0 sweep (same random uniforms across p0; primary node/link/OD outputs only):",
             "p0           Mutual pair fraction [95% CI]"]
    lines.extend(f"{row['p0']:<12g} {interval(row, 'conn_reliability')}" for row in summary["sweep"])
    first, last = summary["sweep"][0], summary["sweep"][-1]
    if first["conn_reliability"] is not None:
        lines.append(f"From p0={first['p0']:g} to {last['p0']:g}, mutual connectivity decreases by "
                     f"{100*(first['conn_reliability']-last['conn_reliability']):.4f} percentage points.")
    lines.extend([
        "p_connected means main-SCC membership; a selected singleton can count without reaching another node.",
        "Main SCC: largest node count; ties select the component with the smallest minimum node ID.",
        f"Node membership mean: {summary['node']['p_connected_mean']:.6f}; "
        f"p10: {summary['node']['p_connected_p10']:.6f}; "
        f"maximum Wilson 95% CI half-width: {summary['node']['max_wilson_half_width']:.6f}",
        "Up to 20 least reliable nodes (main-SCC membership, 95% Wilson CI):"])
    lines.extend(f"Node {row['node_id']}: {interval(row, 'p_connected', 'p_connected_ci_low', 'p_connected_ci_high')}"
                 for row in summary["node"]["least_reliable"])
    lines.extend([
        "Link importance = mean(mutual pair fraction | up) - mean(mutual pair fraction | down).",
        f"Requires >= {summary['link']['min_down_count']} down and >= {summary['link']['min_up_count']} up observations.",
        f"Estimated link importances: {summary['link']['estimated']}; unavailable (including self-loops): {summary['link']['unavailable']}",
        "Up to 20 links by estimated importance (Welch 95% CI):"])
    lines.extend(f"Link {row['link_id']}: "
                 f"{interval(row, 'rel_importance', 'rel_importance_ci_low', 'rel_importance_ci_high')}; "
                 f"down={row['rel_down_count']}; up={row['rel_up_count']}"
                 for row in summary["link"]["top_importance"])
    lines.append("Negative importance estimates can reflect Monte Carlo noise; inspect their intervals.")
    lines.append("OD reliability uses true directed origin-to-destination reachability (95% Wilson CI):")
    if not summary["od_pairs"]:
        lines.append("No OD pairs supplied.")
    lines.extend(f"{row['label']}: {row['origin_node_id']} -> {row['dest_node_id']}; "
                 f"snap {row['origin_snap_m']:.1f}/{row['dest_snap_m']:.1f} m; {interval(row, 'p_od')}"
                 for row in summary["od_pairs"])
    notices = summary["od_warnings"]
    lines.append(f"OD snap warnings: {notices['total_count']} total; {len(notices['shown'])} shown; {notices['omitted_count']} omitted")
    lines.extend(f"WARNING: {message}" for message in notices["shown"])
    lines.extend([
        "CIs quantify sampling uncertainty conditional on the failure model; they exclude proxy/hazard uncertainty.",
        "Normal/Welch intervals are approximate; constant sampled scores can conceal rare disconnections.",
        "Whole-network connectivity is outside this metric's scope; it is not assumed universally near zero."])
    return lines
