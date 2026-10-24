"""Retained speed parsing and additive directed travel-time providers."""

import math

import pytest

from georesilience.config import TravelTimeConfig
from georesilience.time_models import (
    EdgeAttributeTimeModel, FreeFlowTimeModel, PreparedTimeModel, _parsed_speed, prepare_time_model,
)
from tests.test_event_reliability import roads


@pytest.mark.parametrize("raw,expected", [("60", 60), (30, 30), ("30 mph", 48.2802),
    (["30 mph", "60"], 54.1401), ("30 mph|60 km/h", 54.1401), ("40,5 km/h", 40.5),
    ("GB:nsl_restricted", 48.28), (None, None), ("signals", None), ("10 knots", None),
    ("0", None), ("nan", None)])
def test_speed_parser_units_and_invalid_tags(raw, expected):
    result = _parsed_speed(raw)
    assert result == pytest.approx(expected) if expected is not None else result is None


def test_speed_coverage_tagged_user_and_inferred_classes():
    graph = roads([(0, 1, 1000, 10, True), (1, 2, 2000, 10, True),
                   (2, 3, 3000, 10, True), (3, 0, 4000, 10, True)])
    for _, _, _, data in graph.edges(keys=True, data=True):
        if data["osmid"] == 1:
            data["maxspeed"] = 60
        if data["osmid"] == 3:
            data["highway"] = "secondary"
        if data["osmid"] == 4:
            data["highway"] = "service"
    prepared = FreeFlowTimeModel().prepare(graph, TravelTimeConfig(highway_speeds_kph={"secondary": 30}))
    assert {key: value["length_pct"] for key, value in prepared.summary["maxspeed_coverage"].items()} == {
        "tagged": 10, "class_mean": 20, "user_table": 30, "network_class_mean": 40}
    assert prepared.edge_seconds[(0, 1, 0)] == 60
    assert prepared.edge_seconds[(2, 3, 0)] == 360
    assert "speed_kph" not in graph[0][1][0]


def test_asymmetric_speed_tags_count_one_physical_road_and_ignore_self_loops():
    graph = roads()
    graph[0][1][0]["maxspeed"] = "30 mph"
    graph.add_edge(0, 0, length=1, osmid=99, highway="residential", maxspeed=300)
    prepared = FreeFlowTimeModel().prepare(graph, TravelTimeConfig())
    coverage = prepared.summary["maxspeed_coverage"]
    assert coverage["tagged"]["length_pct"] == coverage["class_mean"]["length_pct"] == 50
    assert prepared.edge_seconds[(1, 0, 0)] == pytest.approx(3.6 * 100 / 48.2802)
    assert (0, 0, 0) not in prepared.edge_seconds


def test_missing_speeds_table_fallback_and_disabled_model():
    graph = roads()
    assert prepare_time_model(graph, TravelTimeConfig()).summary["status"] == "skipped: no speed data"
    table = prepare_time_model(graph, TravelTimeConfig(highway_speeds_kph={"residential": 30}))
    assert table.edge_seconds[(0, 1, 0)] == 12
    assert table.summary["maxspeed_coverage"]["user_table"]["length_pct"] == 100
    assert prepare_time_model(graph, TravelTimeConfig(enabled=False)).summary["status"] == "disabled"


def test_unrelated_speed_table_with_no_observed_speeds_gives_explicit_missing_result():
    prepared = prepare_time_model(roads(), TravelTimeConfig(highway_speeds_kph={"motorway": 90}))
    assert prepared.summary["status"] != "computed"
    assert "speed" in prepared.summary["status"]
    assert not prepared.edge_seconds


def test_directed_edge_attribute_uses_supplied_seconds_and_preserves_graph():
    graph = roads()
    graph[0][1][0]["seconds"] = 8
    graph[1][0][0]["seconds"] = 21
    prepared = EdgeAttributeTimeModel().prepare(graph, TravelTimeConfig(time_attribute="seconds"))
    assert prepared.edge_seconds == {(0, 1, 0): 8, (1, 0, 0): 21}
    assert prepared.summary["time_units"] == "seconds"
    assert "seconds" in prepared.summary["time_function"]
    with pytest.raises(ValueError, match="missing"):
        prepare_time_model(graph, TravelTimeConfig(time_model="edge_attribute"))


@pytest.mark.parametrize("result,match", [({}, "PreparedTimeModel"),
    (PreparedTimeModel({}, {}), "status and time_model"),
    (PreparedTimeModel({}, {"status": "computed", "time_model": "wrong", "time_units": "hours"}), "seconds")])
def test_invalid_provider_contracts(result, match):
    class Provider:
        def prepare(self, graph, config):
            return result
    with pytest.raises(ValueError, match=match):
        prepare_time_model(roads(), TravelTimeConfig(), Provider())


def test_custom_config_requires_python_provider():
    with pytest.raises(ValueError, match="provider"):
        prepare_time_model(roads(), TravelTimeConfig(time_model="custom"))
