"""Exact-state references for paired physical-link event reliability."""

import csv
from itertools import product
import json
import math

import networkx as nx
import numpy as np
import pytest

from georesilience.config import TravelTimeConfig
from georesilience.links import identify_links
from georesilience.od import ODInputs
from georesilience.reliability import compute_reliability, write_od_reliability
from georesilience.time_models import PreparedTimeModel, TimeContext


def roads(specs=None, nodes=None):
    specs = [(0, 1, 100, 10, True)] if specs is None else specs
    graph = nx.MultiDiGraph(crs=32644, simplified=True)
    for node in sorted(set(nodes or []) | {value for road in specs for value in road[:2]}):
        graph.add_node(node, x=500000 + node * 100, y=1900000)
    for way, (u, v, length, seconds, reciprocal) in enumerate(specs, 1):
        graph.add_edge(u, v, length=length, seconds=seconds, highway="residential", osmid=way)
        if reciprocal:
            graph.add_edge(v, u, length=length, seconds=seconds, highway="residential", osmid=way)
    return graph


def compute(graph, population=None, user=None, samples=8, **kwargs):
    links = identify_links(graph, "test-reliability-input")
    population = np.arange(1, len(graph) + 1) if population is None else population
    user = {row["link_uid"]: .5 for row in links if not row["is_self_loop"]} if user is None else user
    kwargs.setdefault("time_config", TravelTimeConfig(time_model="edge_attribute", time_attribute="seconds"))
    kwargs.setdefault("connectivity_samples", samples)
    kwargs.setdefault("travel_time_samples", samples)
    return compute_reliability(graph, links, population, user, **kwargs)


def independent_exact(graph, links, population, threshold):
    n = len(graph)
    population = np.asarray(population, dtype=float)
    denominator = sum(population[i] * population[j] for i in range(n) for j in range(n) if i != j)
    intact = dict(nx.all_pairs_dijkstra_path_length(graph, weight="seconds"))
    totals = np.zeros((2, 2))
    for up in product([False, True], repeat=len(links)):
        damaged = graph.copy()
        for row, state in zip(links, up):
            if not state:
                damaged.remove_edges_from(row["_edges"])
        distances = dict(nx.all_pairs_dijkstra_path_length(damaged, weight="seconds"))
        components = list(nx.strongly_connected_components(damaged))
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                mutual = any(i in component and j in component for component in components)
                before = intact[i].get(j, math.inf)
                after = distances[i].get(j, math.inf)
                tt = math.isfinite(before) and math.isfinite(after) and after <= (1 + threshold) * before
                for metric, value in enumerate([mutual, tt]):
                    totals[metric, 0] += value / (n * (n - 1))
                    if denominator:
                        totals[metric, 1] += value * population[i] * population[j] / denominator
    return totals / 2**len(links)


@pytest.mark.parametrize("specs,population", [
    ([(0, 1, 100, 10, True)], [2, 7]),
    ([(0, 1, 100, 10, True), (1, 2, 100, 10, True)], [1, 2, 7]),
    ([(0, 1, 100, 10, False), (1, 2, 100, 10, False), (2, 0, 100, 10, False)], [2, 0, 5]),
    ([(0, 1, 100, 10, True), (0, 1, 200, 20, True)], [2, 7]),
])
@pytest.mark.parametrize("threshold", [0, 1])
def test_all_equally_likely_states_match_independent_networkx(specs, population, threshold):
    graph = roads(specs)
    links = identify_links(graph, "test-reliability-input")
    uniforms = np.array(list(product([.25, .75], repeat=len(links))))
    expected = independent_exact(graph, links, population, threshold)
    result = compute(graph, population, samples=len(uniforms), uniform_samples=uniforms, time_threshold=threshold)
    for column, group in enumerate(("unweighted", "population_weighted")):
        for metric, key in enumerate(("connectivity_reliability", "travel_time_reliability")):
            score = result.summary[group][key]
            assert score["value"] == pytest.approx(expected[metric, column], abs=1e-14)
            assert score["ci_low"] <= expected[metric, column] <= score["ci_high"]
            assert score["confidence"] == .95 and "Hoeffding" in score["interval_method"]
    json.dumps(result.summary, allow_nan=False)


def test_threshold_equality_and_parallel_road_connectivity_are_separate():
    graph = roads([(0, 1, 100, 10, True), (0, 1, 200, 20, True)])
    uniforms = np.array([[.25, .75], [.25, .75]])
    below = compute(graph, uniform_samples=uniforms, samples=2, time_threshold=.999)
    equal = compute(graph, uniform_samples=uniforms, samples=2, time_threshold=1)
    assert below.summary["unweighted"]["connectivity_reliability"]["value"] == 1
    assert below.summary["unweighted"]["travel_time_reliability"]["value"] == 0
    assert equal.summary["unweighted"]["travel_time_reliability"]["value"] == 1


def test_directional_travel_time_does_not_imply_mutual_connectivity():
    graph = roads([(0, 1, 100, 10, False)])
    result = compute(graph, user={}, p0=0)
    assert result.summary["unweighted"]["connectivity_reliability"]["value"] == 0
    assert result.summary["unweighted"]["travel_time_reliability"]["value"] == .5


@pytest.mark.parametrize("population", [[0, 0], [3, 0]])
def test_no_distinct_population_pairs_are_null_and_structural_remains_defined(population):
    result = compute(roads(), population, user={}, p0=0)
    for metric in ("connectivity_reliability", "travel_time_reliability"):
        assert result.summary["unweighted"][metric]["value"] == 1
        weighted = result.summary["population_weighted"][metric]
        assert weighted["value"] is weighted["ci_low"] is weighted["ci_high"] is None
        assert weighted["reason"]


def test_extremely_imbalanced_population_preserves_within_component_pair_mass():
    graph = roads([(0, 1, 100, 10, True)], nodes=[0, 1, 2])
    result = compute(graph, [1e200, 1, 1], user={}, p0=0)
    assert result.summary["population_weighted"]["connectivity_reliability"]["value"] == pytest.approx(.5)
    assert result.summary["population_weighted"]["travel_time_reliability"]["value"] == pytest.approx(.5)


def test_missing_speed_is_explicit_and_does_not_disable_connectivity():
    result = compute(roads(), user={}, p0=0, time_config=TravelTimeConfig(),
                     connectivity_samples=2, travel_time_samples=100)
    assert result.summary["unweighted"]["connectivity_reliability"]["value"] == 1
    for group in ("unweighted", "population_weighted"):
        score = result.summary[group]["travel_time_reliability"]
        assert score["value"] is None and "speed" in score["reason"]
    assert result.summary["speed_source"]["status"] == "skipped: no speed data"
    assert result.computation["connectivity_samples_evaluated"] == 2
    assert result.computation["travel_time_samples_evaluated"] == 0


def test_probability_one_is_always_closed_even_for_supplied_uniform_endpoint_one():
    result = compute(roads(), user={}, p0=1, samples=2, uniform_samples=np.ones((2, 1)))
    for group in ("unweighted", "population_weighted"):
        assert result.summary[group]["connectivity_reliability"]["value"] == 0
        assert result.summary[group]["travel_time_reliability"]["value"] == 0


def test_singleton_has_no_network_distinct_pairs():
    result = compute(roads([], nodes=[0]), population=[7], user={}, samples=2)
    for group in ("unweighted", "population_weighted"):
        for metric in ("connectivity_reliability", "travel_time_reliability"):
            assert result.summary[group][metric]["value"] is None
            assert result.summary[group][metric]["reason"]


def test_workers_memory_chunks_and_named_sweeps_leave_primary_identical():
    graph = roads([(0, 1, 100, 10, True), (1, 2, 100, 10, True), (2, 0, 100, 10, True)])
    serial = compute(graph, user={}, p0=.2, samples=40)
    parallel = compute(graph, user={}, p0=.2, samples=40, n_jobs=4, budget_bytes=1536)
    sweep = compute(graph, user={}, p0=.2, samples=40, p0_sweep={"low": .01, "high": .8})
    assert serial.summary == parallel.summary
    assert serial.summary["unweighted"] == sweep.summary["unweighted"]
    assert serial.summary["population_weighted"] == sweep.summary["population_weighted"]
    assert parallel.computation["reliability_workers"] >= 2
    assert parallel.computation["travel_time_chunk_rows"] < serial.computation["travel_time_chunk_rows"]
    for group in ("unweighted", "population_weighted"):
        for metric in ("connectivity_reliability", "travel_time_reliability"):
            assert sweep.summary["scenarios"]["low"][group][metric]["value"] >= sweep.summary["scenarios"]["high"][group][metric]["value"]


def test_seed_sample_prefix_and_different_counts_share_exact_uniforms():
    graph = roads([(0, 1, 100, 10, True), (1, 2, 100, 10, True)])
    uniforms = np.array([np.random.default_rng(np.random.SeedSequence([42, index])).random(2) for index in range(20)])
    generated = compute(graph, samples=20, connectivity_samples=20, travel_time_samples=8)
    supplied = compute(graph, samples=20, connectivity_samples=20, travel_time_samples=8, uniform_samples=uniforms)
    short = compute(graph, samples=8)
    assert generated.summary == supplied.summary
    for group in ("unweighted", "population_weighted"):
        assert generated.summary[group]["travel_time_reliability"] == short.summary[group]["travel_time_reliability"]


def test_optional_od_does_not_change_network_denominators_and_writes_csv(tmp_path):
    graph = roads([(0, 1, 100, 10, False)])
    pairs = ODInputs([{"label": "forward", "_origin": 0, "_dest": 1,
        "origin_node_id": "0", "dest_node_id": "1", "origin_snap_m": 0, "dest_snap_m": 0}], {})
    baseline = compute(graph, user={}, p0=0)
    with_od = compute(graph, user={}, p0=0, od_inputs=pairs)
    assert baseline.summary == with_od.summary
    row = with_od.od_rows[0]
    assert row["connectivity_reliability"] == 0
    assert row["travel_time_reliability"] == 1
    assert row["baseline_time_seconds"] == 10
    target = write_od_reliability(with_od, tmp_path / "od.csv")
    assert len(list(csv.DictReader(target.open()))) == 1
    empty = write_od_reliability(baseline, tmp_path / "empty.csv")
    assert len(empty.read_text().splitlines()) == 1


class ScenarioProvider:
    def __init__(self, value=20):
        self.value, self.contexts = value, []

    def prepare(self, graph, config):
        edges = list(graph.edges(keys=True))
        def costs(context):
            self.contexts.append(context)
            return {edge: 10 if context.sample_index is None else self.value for edge in edges}
        return PreparedTimeModel({}, {"status": "computed", "time_model": "scenario-delay"}, costs)


def test_custom_scenario_times_receive_sample_and_closed_physical_ids():
    graph = roads()
    provider = ScenarioProvider()
    result = compute(graph, samples=2, uniform_samples=np.array([[.25], [.75]]), time_model=provider)
    assert provider.contexts == [TimeContext(), TimeContext(0, frozenset({0})), TimeContext(1, frozenset())]
    assert result.summary["unweighted"]["connectivity_reliability"]["value"] == .5
    assert result.summary["unweighted"]["travel_time_reliability"]["value"] == 0


@pytest.mark.parametrize("value", [0, -1, math.inf, math.nan, "word"])
def test_invalid_per_sample_provider_costs_are_rejected(value):
    with pytest.raises(ValueError, match="travel_time"):
        compute(roads(), samples=2, time_model=ScenarioProvider(value))


def test_provider_must_supply_every_directed_arc_in_baseline_and_scenarios():
    class Missing:
        def prepare(self, graph, config):
            return PreparedTimeModel({(0, 1, 0): 10}, {"status": "computed", "time_model": "missing"})
    with pytest.raises(ValueError, match="every directed"):
        compute(roads(), samples=2, time_model=Missing())


@pytest.mark.parametrize("kwargs", [{"connectivity_samples": 1}, {"travel_time_samples": 1},
    {"time_threshold": -1}, {"time_threshold": math.inf}, {"seed": -1}, {"n_jobs": 0},
    {"budget_bytes": 1}, {"p0_sweep": {"primary": .1}}, {"p0_sweep": {"": .1}},
    {"uniform_samples": np.zeros((2, 2))}, {"uniform_samples": np.array([[0], [math.nan]])}])
def test_invalid_simulation_contracts(kwargs):
    with pytest.raises(ValueError):
        compute(roads(), samples=2, **kwargs)
