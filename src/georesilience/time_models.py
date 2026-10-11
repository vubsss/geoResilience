"""Travel-time providers, independent of routing and reliability estimation.

All costs are positive seconds on directed, non-self-loop edges. Providers may
combine arbitrary edge data. A scenario evaluator optionally supplies a different
static cost snapshot for each failure sample; departure-time-dependent routing
and flow assignment are separate future algorithms.
"""

import math
import re
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

import numpy as np
import osmnx as ox


@dataclass(frozen=True)
class TimeContext:
    sample_index: int | None = None  # None identifies the intact baseline
    closed_link_ids: frozenset[int] = frozenset()


@dataclass
class PreparedTimeModel:
    edge_seconds: Mapping
    summary: dict
    scenario_times: Callable[[TimeContext], Mapping] | None = None

    def costs(self, context):
        return self.edge_seconds if self.scenario_times is None else self.scenario_times(context)


class TravelTimeModel(Protocol):
    def prepare(self, graph, config) -> PreparedTimeModel:
        """Return directed edge costs, model metadata and optional scenario evaluator."""
        ...


def _parsed_speed(value):
    """Normalize numeric/lane/list tags to km/h; keep OSMnx implicit-code support.

    The OSMnx 2.x implicit-code parser is isolated here. Explicit units are
    normalized before public speed imputation, including mixed mph/km/h lists.
    Unsupported units are missing data, rather than silently interpreted as km/h.
    """
    if isinstance(value, (list, tuple)):
        parsed = [_parsed_speed(item) for item in value]
        valid = [item for item in parsed if item is not None]
        return float(np.mean(valid)) if valid else None
    if value is None:
        return None
    text = str(value).strip()
    if "|" in text:
        return _parsed_speed(text.split("|"))
    match = re.fullmatch(r"([0-9]+(?:[.,][0-9]+)?)\s*(km/h|kmh|kph|mph)?", text, re.IGNORECASE)
    if match:
        number = float(match[1].replace(",", "."))
        if (match[2] or "").lower() == "mph":
            number *= 1.60934
    else:
        number = ox.routing._clean_maxspeed(text)
        # OSMnx accepts knots as numeric kph; do not inherit that conversion.
        if "knots" in text.lower():
            return None
    return float(number) if number is not None and math.isfinite(number) and number > 0 else None


def _highway(data):
    value = data.get("highway", "unclassified")
    if isinstance(value, (list, tuple)):
        value = value[0] if value else "unclassified"
    return str(value)


class FreeFlowTimeModel:
    """Default provider: time = 3.6 * distance_metres / speed_kph."""

    def prepare(self, graph, config):
        working = graph.copy()
        working.remove_edges_from([(u, v, key) for u, v, key in working.edges(keys=True) if u == v])
        parsed, classes, invalid = {}, set(), 0
        for u, v, key, data in working.edges(keys=True, data=True):
            if u != v and (not math.isfinite(float(data["length"])) or float(data["length"]) <= 0):
                raise ValueError("travel_time: road lengths must be finite and strictly positive")
            data["highway"] = _highway(data)
            speed = _parsed_speed(data.get("maxspeed"))
            if speed is not None:
                data["maxspeed"] = str(speed)
                if u != v:
                    parsed[(u, v, key)] = speed
                    classes.add(data["highway"])
            else:
                invalid += int(u != v and data.get("maxspeed") is not None)
                data.pop("maxspeed", None)
        metadata = {"time_model": "free_flow", "time_units": "seconds",
                    "time_function": "3.6 * length_m / speed_kph",
                    "assumptions": "free-flow speeds; no traffic (Tier 4)",
                    "invalid_maxspeed_edges": invalid}
        if not parsed and config.highway_speeds_kph is None:
            return PreparedTimeModel({}, {**metadata, "status": "skipped: no speed data",
                                          "maxspeed_coverage": None})
        working = ox.routing.add_edge_speeds(working, hwy_speeds=config.highway_speeds_kph)
        for u, v, key, data in working.edges(keys=True, data=True):
            if not math.isfinite(float(data["speed_kph"])) or data["speed_kph"] <= 0:
                raise ValueError(f"travel_time: edge {(u,v,key)} has no finite positive speed")
        working = ox.routing.add_edge_travel_times(working)
        lengths = dict.fromkeys(("tagged", "user_table", "class_mean", "network_class_mean"), 0.0)
        costs = {}
        # A physical road's length is split across its directed edges for coverage.
        # Thus asymmetric tags contribute fractional coverage, not doubled road km.
        from .links import _link_rows
        for link in _link_rows(graph):
            if link["is_self_loop"]:
                continue
            arcs = link["_edges"]
            total = sum(float(graph[u][v][key]["length"]) for u, v, key in arcs)
            for edge in arcs:
                u, v, key = edge
                data = working[u][v][key]
                highway = data["highway"]
                source = ("tagged" if edge in parsed else "user_table"
                          if highway in (config.highway_speeds_kph or {}) else "class_mean"
                          if highway in classes else "network_class_mean")
                lengths[source] += link["length_m"] * float(data["length"]) / total
                costs[edge] = float(data["travel_time"])
        total = sum(lengths.values())
        coverage = {source: {"length_m": value, "length_pct": 100*value/total if total else None}
                    for source, value in lengths.items()}
        return PreparedTimeModel(costs, {**metadata, "status": "computed", "maxspeed_coverage": coverage})


class EdgeAttributeTimeModel:
    """Use externally calculated seconds, allowing distance, delays and other factors."""

    def prepare(self, graph, config):
        costs = {}
        for u, v, key, data in graph.edges(keys=True, data=True):
            if u == v:
                continue
            if config.time_attribute not in data:
                raise ValueError(f"travel_time: missing {config.time_attribute!r} on edge {(u,v,key)}")
            costs[(u, v, key)] = data[config.time_attribute]
        return PreparedTimeModel(costs, {
            "status": "computed", "time_model": "edge_attribute", "time_units": "seconds",
            "time_attribute": config.time_attribute,
            "time_function": f"supplied directed-edge attribute {config.time_attribute}",
            "assumptions": "supplied static edge times; factors and calibration are user-provided",
            "maxspeed_coverage": None})


def prepare_time_model(graph, config, model=None):
    if not config.enabled:
        return PreparedTimeModel({}, {"status": "disabled", "time_model": config.time_model})
    if model is None:
        if config.time_model == "custom":
            raise ValueError("travel_time.time_model: custom requires a Python time_model provider")
        model = FreeFlowTimeModel() if config.time_model == "free_flow" else EdgeAttributeTimeModel()
    prepared = model.prepare(graph, config)
    if not isinstance(prepared, PreparedTimeModel):
        raise ValueError("travel_time: time model must return PreparedTimeModel")
    if "status" not in prepared.summary or "time_model" not in prepared.summary:
        raise ValueError("travel_time: time model metadata requires status and time_model")
    prepared.summary.setdefault("time_function", "custom provider of additive directed-edge seconds")
    prepared.summary.setdefault("assumptions", "custom time model; see provider metadata")
    prepared.summary.setdefault("time_units", "seconds")
    if prepared.summary["time_units"] != "seconds":
        raise ValueError("travel_time: provider costs must use seconds")
    return prepared
