"""Static traffic assignment and directed-edge traffic inputs."""

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import numpy as np
from scipy.optimize import brentq


@dataclass
class TrafficResult:
    summary: dict
    rows: list[dict]
    edge_seconds: dict
    od_rows: list[dict]
    demand: dict | None = None
    capacities: dict | None = None
    closure_rows: list[dict] | None = None


def _arcs(graph):
    return [(u, v, key, data) for u, v, key, data in graph.edges(keys=True, data=True) if u != v]


def _edge_lookup(graph):
    arcs = _arcs(graph)
    lookup = {}
    for u, v, key, _ in arcs:
        label = (str(u), str(v), str(key))
        if label in lookup:
            raise ValueError(f"traffic: ambiguous directed edge identity {label}")
        lookup[label] = (u, v, key)
    return arcs, lookup


def _read_csv(path, required):
    with Path(path).open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not set(required).issubset(reader.fieldnames):
            raise ValueError(f"traffic: {path} needs columns {', '.join(required)}")
        return list(reader)


def _positive(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"traffic: {label} must be finite and positive") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"traffic: {label} must be finite and positive")
    return number


def _read_edges(path, lookup, field):
    values = {}
    for row in _read_csv(path, ("u", "v", "key", field)):
        label = (row["u"], row["v"], row["key"])
        if label not in lookup or lookup[label] in values:
            raise ValueError(f"traffic: unknown or duplicate directed edge {label}")
        values[lookup[label]] = _positive(row[field], field)
    if set(values) != set(lookup.values()):
        raise ValueError(f"traffic: {path} must cover every directed non-loop edge")
    return values


def _read_od(path, graph):
    nodes = {str(node): node for node in graph}
    if len(nodes) != len(graph):
        raise ValueError("traffic: ambiguous stringified node IDs")
    demand = {}
    for row in _read_csv(path, ("origin", "destination", "demand_pcu_h")):
        origin, destination = row["origin"], row["destination"]
        if origin not in nodes or destination not in nodes or origin == destination:
            raise ValueError(f"traffic: invalid OD pair {(origin, destination)}")
        pair = (nodes[origin], nodes[destination])
        demand[pair] = demand.get(pair, 0.0) + _positive(row["demand_pcu_h"], "demand_pcu_h")
    if not demand:
        raise ValueError("traffic: OD CSV has no positive inter-node demand")
    return demand


def gravity_od(graph, free_flow_seconds, zone_mass_csv, total_demand_pcu_h,
               gravity_lambda_per_min):
    """Doubly constrained synthetic OD over explicitly supplied zone centroids."""
    nodes = {str(node): node for node in graph}
    if len(nodes) != len(graph):
        raise ValueError("traffic: ambiguous stringified node IDs")
    zones, masses = [], []
    for row in _read_csv(zone_mass_csv, ("node", "mass")):
        if row["node"] not in nodes or nodes[row["node"]] in zones:
            raise ValueError(f"traffic: unknown or duplicate zone node {row['node']!r}")
        zones.append(nodes[row["node"]])
        masses.append(_positive(row["mass"], "zone mass"))
    if len(zones) < 2:
        raise ValueError("traffic: gravity demand requires at least two zone nodes")
    total = _positive(total_demand_pcu_h, "total_demand_pcu_h")
    decay = _positive(gravity_lambda_per_min, "gravity_lambda_per_min")
    masses = np.array(masses)
    targets = total * masses / masses.sum()
    if max(targets) > total / 2 + 1e-9:
        raise ValueError("traffic: excluding intrazonal trips makes these zone masses infeasible")
    simple = nx.DiGraph()
    simple.add_nodes_from(graph)
    for u, v, key, _ in _arcs(graph):
        time = _positive(free_flow_seconds[(u, v, key)], "free_flow_time_s")
        if not simple.has_edge(u, v) or time < simple[u][v]["weight"]:
            simple.add_edge(u, v, weight=time)
    kernel = np.zeros((len(zones), len(zones)))
    for i, origin in enumerate(zones):
        distances = nx.single_source_dijkstra_path_length(simple, origin, weight="weight")
        for j, destination in enumerate(zones):
            if i != j and destination in distances:
                kernel[i, j] = math.exp(-decay * distances[destination] / 60)
    if (kernel.sum(axis=0) == 0).any() or (kernel.sum(axis=1) == 0).any():
        raise ValueError("traffic: some gravity zones cannot reach or be reached from others")
    matrix = kernel.copy()
    for _ in range(10000):
        row_sums = matrix.sum(axis=1)
        if (row_sums <= 0).any():
            raise ValueError("traffic: gravity balancing lost a reachable production zone")
        matrix *= (targets / row_sums)[:, None]
        column_sums = matrix.sum(axis=0)
        if (column_sums <= 0).any():
            raise ValueError("traffic: gravity balancing lost a reachable attraction zone")
        matrix *= (targets / column_sums)[None, :]
        if (np.all(np.abs(matrix.sum(axis=1) - targets) <= 1e-8 * np.maximum(targets, 1)) and
                np.all(np.abs(matrix.sum(axis=0) - targets) <= 1e-8 * np.maximum(targets, 1))):
            break
    else:
        raise ValueError("traffic: gravity balancing did not converge; inspect zone masses and reachability")
    return {(zones[i], zones[j]): float(matrix[i, j]) for i in range(len(zones))
            for j in range(len(zones)) if matrix[i, j] > 0}


def _travel_times(free_flow, capacity, volume, vdf, alpha, beta):
    ratio = volume / capacity
    if vdf == "bpr":
        multiplier = 1 + alpha * ratio**beta
    else:
        gap = 1 - ratio
        multiplier = 2 + np.sqrt(alpha**2 * gap**2 + beta**2) - alpha * gap - beta
    return free_flow * multiplier


def _all_or_nothing(arcs, times, demand, nodes):
    simple = nx.DiGraph()
    simple.add_nodes_from(nodes)
    for i, (u, v, key, _) in enumerate(arcs):
        if not simple.has_edge(u, v) or times[i] < simple[u][v]["weight"]:
            simple.add_edge(u, v, weight=float(times[i]), arc=i)
    by_origin = {}
    for (origin, destination), amount in demand.items():
        by_origin.setdefault(origin, []).append((destination, amount))
    assigned = np.zeros(len(arcs))
    shortest_total = 0.0
    for origin, destinations in by_origin.items():
        distances, paths = nx.single_source_dijkstra(simple, origin, weight="weight")
        for destination, amount in destinations:
            if destination not in paths:
                raise ValueError(f"traffic: OD pair {origin!r}->{destination!r} is unreachable")
            path = paths[destination]
            shortest_total += amount * distances[destination]
            for u, v in zip(path, path[1:]):
                assigned[simple[u][v]["arc"]] += amount
    return assigned, shortest_total


def _od_skims(graph, demand, free_flow_seconds, traffic_seconds):
    def distances_for(costs):
        simple = nx.DiGraph()
        simple.add_nodes_from(graph)
        for u, v, key, _ in _arcs(graph):
            value = costs[(u, v, key)]
            if not simple.has_edge(u, v) or value < simple[u][v]["weight"]:
                simple.add_edge(u, v, weight=value)
        return {origin: nx.single_source_dijkstra_path_length(simple, origin, weight="weight")
                for origin in {pair[0] for pair in demand}}
    free = distances_for(free_flow_seconds)
    congested = distances_for(traffic_seconds)
    return [{"origin": str(origin), "destination": str(destination), "demand_pcu_h": amount,
             "free_flow_time_s": float(free[origin][destination]),
             "congested_time_s": float(congested[origin][destination]),
             "delay_s": float(congested[origin][destination] - free[origin][destination])}
            for (origin, destination), amount in demand.items()]


def assign_traffic(graph, free_flow_seconds, capacity_pcu_h, demand, *, vdf="bpr", alpha=.15,
                   beta=4.0, relative_gap=1e-4, max_iterations=200):
    """Frank-Wolfe user equilibrium on a directed MultiDiGraph for one static period."""
    if vdf not in {"bpr", "conical"}:
        raise ValueError("traffic: vdf must be bpr or conical")
    if not all(math.isfinite(x) and x > 0 for x in (alpha, beta, relative_gap)) or max_iterations < 1:
        raise ValueError("traffic: VDF parameters, relative_gap and max_iterations must be positive")
    if vdf == "conical" and abs(2 + math.hypot(alpha, beta) - alpha - beta - 1) > .01:
        raise ValueError("traffic: conical parameters must give approximately free-flow time at zero volume")
    arcs = _arcs(graph)
    if not arcs:
        raise ValueError("traffic: graph has no directed road arcs")
    edges = [(u, v, key) for u, v, key, _ in arcs]
    if set(free_flow_seconds) != set(edges) or set(capacity_pcu_h) != set(edges):
        raise ValueError("traffic: free-flow time and capacity must cover every directed road arc")
    free = np.array([_positive(free_flow_seconds[edge], "free_flow_time_s") for edge in edges])
    capacity = np.array([_positive(capacity_pcu_h[edge], "capacity_pcu_h") for edge in edges])
    if not demand or any(amount <= 0 or not math.isfinite(amount) for amount in demand.values()):
        raise ValueError("traffic: OD demand must be finite and positive")
    volume, _ = _all_or_nothing(arcs, free, demand, graph)
    gap = math.inf
    for iteration in range(1, max_iterations + 1):
        times = _travel_times(free, capacity, volume, vdf, alpha, beta)
        target, shortest_total = _all_or_nothing(arcs, times, demand, graph)
        current_total = float(np.dot(volume, times))
        gap = max(0.0, (current_total - shortest_total) / current_total)
        if gap <= relative_gap:
            break
        direction = target - volume
        def derivative(step):
            return float(np.dot(direction, _travel_times(
                free, capacity, volume + step * direction, vdf, alpha, beta)))
        step = 1.0 if derivative(1.0) <= 0 else brentq(derivative, 0.0, 1.0)
        volume += step * direction
    times = _travel_times(free, capacity, volume, vdf, alpha, beta)
    if not np.isfinite(times).all() or (times <= 0).any():
        raise ValueError("traffic: VDF produced invalid travel times")
    _, shortest_total = _all_or_nothing(arcs, times, demand, graph)
    gap = max(0.0, (float(np.dot(volume, times)) - shortest_total) / float(np.dot(volume, times)))
    return {edge: {"free_flow_time_s": float(free[i]), "capacity_pcu_h": float(capacity[i]),
                   "assigned_volume_pcu_h": float(volume[i]), "vc_ratio": float(volume[i] / capacity[i]),
                   "congested_time_s": float(times[i]), "delay_s": float(times[i] - free[i])}
            for i, edge in enumerate(edges)}, {"status": "converged" if gap <= relative_gap else "non_converged",
                                              "vdf": vdf, "alpha": alpha, "beta": beta,
                                              "iterations": iteration, "relative_gap": gap,
                                              "target_relative_gap": relative_gap,
                                              "demand_pcu_h": float(sum(demand.values())),
                                              "tstt_pcu_hours": float(np.dot(volume, times) / 3600),
                                              "delay_pcu_hours": float(np.dot(volume, times - free) / 3600)}


def prepare_traffic(graph, config, free_flow_seconds=None):
    """Build traffic results for pipeline export and time-model consumption."""
    arcs, lookup = _edge_lookup(graph)
    if config.source == "edge_times_csv":
        times = _read_edges(config.edge_times_csv, lookup, "travel_time_s")
        metrics = {edge: {"congested_time_s": value} for edge, value in times.items()}
        summary = {"status": "computed", "source": "edge_times_csv", "provenance": "supplied",
                   "arc_count": len(arcs), "period": config.period}
    else:
        if free_flow_seconds is None:
            raise ValueError("traffic: assignment requires free-flow seconds")
        if config.demand_source == "gravity":
            demand = gravity_od(graph, free_flow_seconds, config.zone_mass_csv,
                                config.total_demand_pcu_h, config.gravity_lambda_per_min)
        else:
            demand = _read_od(config.od_csv, graph)
        if config.capacity_csv is not None:
            capacity = _read_edges(config.capacity_csv, lookup, "capacity_pcu_h")
        else:
            capacity = {edge: config.capacity_pcu_h for edge in lookup.values()}
        metrics, assignment = assign_traffic(
            graph, free_flow_seconds, capacity, demand, vdf=config.vdf, alpha=config.alpha,
            beta=config.beta, relative_gap=config.relative_gap, max_iterations=config.max_iterations)
        assignment["tstt_pcu_hours"] *= config.duration_h
        assignment["delay_pcu_hours"] *= config.duration_h
        summary = {**assignment, "source": "assignment", "provenance": "simulated",
                   "arc_count": len(arcs), "period": config.period,
                   "duration_h": config.duration_h,
                   "demand_source": config.demand_source,
                   "capacity_source": "directed_csv" if config.capacity_csv else "uniform_assumption"}
        times = {edge: row["congested_time_s"] for edge, row in metrics.items()}
    rows = [{"u": str(u), "v": str(v), "key": str(key), **metrics[(u, v, key)]}
            for u, v, key, _ in arcs]
    od_rows = (_od_skims(graph, demand, free_flow_seconds, times)
               if config.source == "assignment" else [])
    if od_rows:
        total_demand = summary["demand_pcu_h"]
        summary["mean_od_time_s"] = sum(row["demand_pcu_h"] * row["congested_time_s"]
                                        for row in od_rows) / total_demand
        summary["mean_od_delay_s"] = sum(row["demand_pcu_h"] * row["delay_s"]
                                         for row in od_rows) / total_demand
    return TrafficResult(summary, rows, times, od_rows,
                         demand if config.source == "assignment" else None,
                         capacity if config.source == "assignment" else None)


def evaluate_closures(graph, links, result, free_flow_seconds, config):
    """Reassign the highest-flow physical roads; report disconnected demand separately."""
    if result.demand is None or config.closure_top_n == 0:
        return []
    if result.summary["status"] != "converged":
        raise ValueError("traffic: baseline assignment must converge before closure reassignment")
    flow = {(row["u"], row["v"], row["key"]): row["assigned_volume_pcu_h"]
            for row in result.rows}
    candidates = sorted((row for row in links if not row["is_self_loop"]),
                        key=lambda row: (-sum(flow[(str(u), str(v), str(key))]
                                              for u, v, key in row["_edges"]), row["link_id"]))
    outcomes = []
    for link in candidates[:config.closure_top_n]:
        damaged = graph.copy()
        damaged.remove_edges_from(link["_edges"])
        reachable = {origin: nx.descendants(damaged, origin)
                     for origin in {pair[0] for pair in result.demand}}
        served = {pair: amount for pair, amount in result.demand.items()
                  if pair[1] in reachable[pair[0]]}
        lost = sum(amount for pair, amount in result.demand.items() if pair not in served)
        row = {"link_id": link["link_id"], "osm_way_ids": link["osm_way_ids"],
               "newly_unreachable_demand_pcu_h": float(lost),
               "baseline_tstt_pcu_hours": result.summary["tstt_pcu_hours"],
               "scenario_tstt_pcu_hours": None, "delta_tstt_pcu_hours": None,
               "status": "all_unreachable" if not served else "computed"}
        if served:
            remaining = {(u, v, key) for u, v, key, _ in _arcs(damaged)}
            _, assignment = assign_traffic(
                damaged, {edge: free_flow_seconds[edge] for edge in remaining},
                {edge: result.capacities[edge] for edge in remaining}, served,
                vdf=config.vdf, alpha=config.alpha, beta=config.beta,
                relative_gap=config.relative_gap, max_iterations=config.max_iterations)
            row["scenario_tstt_pcu_hours"] = assignment["tstt_pcu_hours"] * config.duration_h
            row["status"] = (assignment["status"] if not lost else
                             "partly_unreachable" if assignment["status"] == "converged"
                             else "partly_unreachable_non_converged")
            if not lost and assignment["status"] == "converged":
                row["delta_tstt_pcu_hours"] = (row["scenario_tstt_pcu_hours"] -
                                                row["baseline_tstt_pcu_hours"])
        outcomes.append(row)
    result.closure_rows = outcomes
    return outcomes


def write_traffic_csv(result, path):
    fields = ["u", "v", "key", "free_flow_time_s", "capacity_pcu_h", "assigned_volume_pcu_h",
              "vc_ratio", "congested_time_s", "delay_s"]
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result.rows)


def write_traffic_od_csv(result, path):
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["origin", "destination", "demand_pcu_h",
                                                     "free_flow_time_s", "congested_time_s", "delay_s"])
        writer.writeheader()
        writer.writerows(result.od_rows)


def write_traffic_closures_csv(result, path):
    fields = ["link_id", "osm_way_ids", "newly_unreachable_demand_pcu_h",
              "baseline_tstt_pcu_hours", "scenario_tstt_pcu_hours", "delta_tstt_pcu_hours", "status"]
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result.closure_rows or [])
