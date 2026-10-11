import csv
import itertools
import json
import math
import subprocess
import sys

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pytest
from scipy.sparse.csgraph import dijkstra

from georesilience.config import ReliabilityConfig, RunConfig, TravelTimeConfig, load_config
from georesilience.connectivity import ODInputs, mean_interval
from georesilience.links import _link_rows
from georesilience.pipeline import run
from georesilience.time_models import (FreeFlowTimeModel, PreparedTimeModel,
                                       TimeContext, _parsed_speed, prepare_time_model)
from georesilience.travel_time import (HIST_EDGES, TravelTimeTopology, compute_travel_time,
                                      histogram_quantiles, time_success, travel_time_report)


def roads(edges=((0, 1, 1000, 60, True), (0, 1, 3000, 60, True)), n=None):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    n = max(max(u, v) for u, v, *_ in edges)+1 if n is None else n
    for node in range(n):
        graph.add_node(node, x=float(500000+100*node), y=float(1900000+100*(node % 2)))
    for way, (u, v, length, speed, both) in enumerate(edges, 1):
        for a, b in [(u, v), (v, u)] if both else [(u, v)]:
            data = dict(length=float(length), osmid=way, highway="residential", name=f"Road {way}")
            if speed is not None:
                data["maxspeed"] = speed
            graph.add_edge(a, b, **data)
    return graph


def compute(graph, user=None, *, samples=1000, seed=42, jobs=1, budget=32*1024**2,
            od_inputs=None, provider=None, **settings):
    return compute_travel_time(graph, _link_rows(graph), TravelTimeConfig(samples=samples, **settings),
                               ReliabilityConfig(), user or {}, seed=seed, n_jobs=jobs,
                               budget_bytes=budget, od_inputs=od_inputs, time_model=provider)


def od(*pairs):
    return ODInputs([{"label": label, "_origin": origin, "_dest": dest}
                     for label, origin, dest in pairs], {})


@pytest.mark.parametrize("tau,expected", [(0, .5), (.5, .5), (2, 1), (2.5, 1)])
def test_exact_fast_slow_route_and_threshold_equality(tau, expected):
    result = compute(roads(), {1: .5, 2: 0}, tau=tau, samples=5000,
                     od_inputs=od(("forward", 0, 1), ("reverse", 1, 0), ("same", 0, 0)))
    assert result.summary["tt_reliability"] == pytest.approx(expected, abs=.025)
    assert result.od_metrics["forward"]["p_tt_ok"] == result.summary["tt_reliability"]
    assert result.od_metrics["forward"]["tt0_min"] == 1
    assert result.od_metrics["same"]["p_tt_ok"] == 1
    assert result.od_metrics["same"]["tt0_min"] == 0
    assert result.summary["detour_histogram"]["reachable_pair_observations"] == 10000
    assert result.summary["detour_factor_percentiles"]["p90"] == pytest.approx(3, rel=.004)
    assert set(result.summary["origin_node_ids"]) == {"0", "1"}
    json.dumps(result.summary, allow_nan=False)


def test_threshold_monotonicity_and_sample_prefix():
    small = compute(roads(), {1: .5, 2: 0}, samples=300, tau=.5)
    large = compute(roads(), {1: .5, 2: 0}, samples=600, tau=.5)
    relaxed = compute(roads(), {1: .5, 2: 0}, samples=300, tau=2)
    assert np.array_equal(small.pair_fractions, large.pair_fractions[:300])
    assert np.all(small.pair_fractions <= relaxed.pair_fractions)


def test_every_state_directed_and_parallel_vs_networkx():
    graph = roads([(0, 1, 1000, 60, True), (0, 1, 3000, 30, True),
                   (1, 2, 1000, 40, False), (2, 0, 1200, 30, False)])
    links = _link_rows(graph)
    prepared = FreeFlowTimeModel().prepare(graph, TravelTimeConfig())
    topology = TravelTimeTopology(graph, links, prepared)
    for up in itertools.product([False, True], repeat=len(links)):
        reference = nx.MultiDiGraph()
        reference.add_nodes_from(graph)
        for link, active in zip(links, up):
            if active:
                for u, v, key in link["_edges"]:
                    data = graph[u][v][key]
                    reference.add_edge(u, v, seconds=3.6*data["length"]/float(data["maxspeed"]))
        expected = np.asarray(nx.floyd_warshall_numpy(reference, nodelist=list(graph), weight="seconds"))
        actual = dijkstra(topology.csr(up), directed=True)
        assert np.allclose(actual, expected)


def test_directed_disconnection_and_distinct_pair_denominator():
    graph = roads([(0, 1, 1000, 60, False), (1, 0, 1000, 60, False)])
    result = compute(graph, {1: 0, 2: 1}, od_inputs=od(("forward", 0, 1), ("reverse", 1, 0)))
    assert result.summary["tt_reliability"] == .5
    assert result.od_metrics["forward"]["p_tt_ok"] == 1
    assert result.od_metrics["reverse"]["p_tt_ok"] == 0
    assert result.node_metrics[0]["p_tt_ok"] == 1 and result.node_metrics[1]["p_tt_ok"] == 0
    one_way = roads([(0, 1, 1000, 60, False)])
    result = compute(one_way, {1: 0}, od_inputs=od(("unreachable", 1, 0)))
    assert result.summary["baseline_unreachable_pairs"] == 1
    assert result.summary["tt_reliability"] == .5
    assert result.od_metrics["unreachable"]["tt0_min"] is None
    assert result.od_metrics["unreachable"]["p_tt_ok"] == 0


@pytest.mark.parametrize("raw,expected", [("60", 60), (30, 30), ("30 mph", 48.2802),
    (["30 mph", "60"], 54.1401), ("30 mph|60 km/h", 54.1401), ("40,5 km/h", 40.5),
    ("GB:nsl_restricted", 48.28), (None, None), ("signals", None), ("10 knots", None),
    ("0", None), ("nan", None)])
def test_speed_parser_units_and_invalid_tags(raw, expected):
    value = _parsed_speed(raw)
    assert value == pytest.approx(expected) if expected is not None else value is None


def test_speed_coverage_user_and_inferred_classes():
    graph = roads([(0, 1, 1000, 60, True), (1, 2, 2000, None, True),
                   (2, 3, 3000, None, True), (3, 0, 4000, None, True)])
    for u, v, key in graph.edges(keys=True):
        if graph[u][v][key]["osmid"] == 3:
            graph[u][v][key]["highway"] = "secondary"
        if graph[u][v][key]["osmid"] == 4:
            graph[u][v][key]["highway"] = "service"
    prepared = FreeFlowTimeModel().prepare(graph, TravelTimeConfig(highway_speeds_kph={"secondary": 30}))
    coverage = prepared.summary["maxspeed_coverage"]
    assert {key: value["length_pct"] for key, value in coverage.items()} == {
        "tagged": 10, "class_mean": 20, "user_table": 30, "network_class_mean": 40}
    assert prepared.edge_seconds[(0, 1, 0)] == 60
    assert prepared.edge_seconds[(2, 3, 0)] == 360
    assert "speed_kph" not in graph[0][1][0]  # provider preserves source data
    partial = roads([(0, 1, 1000, None, True)])
    partial[0][1][0]["maxspeed"] = "30 mph"
    covered = FreeFlowTimeModel().prepare(partial, TravelTimeConfig()).summary["maxspeed_coverage"]
    assert covered["tagged"]["length_pct"] == 50
    assert covered["class_mean"]["length_pct"] == 50
    partial.add_edge(0, 0, length=100, osmid=99, highway="residential", maxspeed="300")
    with_loop = FreeFlowTimeModel().prepare(partial, TravelTimeConfig())
    assert with_loop.edge_seconds[(1, 0, 0)] == pytest.approx(3.6*1000/48.2802)


def test_no_speed_skip_table_fallback_and_disabled():
    graph = roads([(0, 1, 1000, "signals", True)])
    skipped = compute(graph)
    assert skipped.summary["status"] == "skipped: no speed data"
    assert all(value["p_tt_ok"] is None for value in skipped.node_metrics.values())
    assert "skipped: no speed data" in "\n".join(travel_time_report(skipped.summary))
    supplied = compute(graph, {1: 0}, highway_speeds_kph={"residential": 30})
    assert supplied.summary["tt_reliability"] == 1
    assert supplied.summary["maxspeed_coverage"]["user_table"]["length_pct"] == 100
    assert compute(roads(), enabled=False).summary["status"] == "disabled"


def test_edge_attribute_model_and_non_distance_factors():
    graph = roads()
    for u, v, key, data in graph.edges(keys=True, data=True):
        data["with_signals_s"] = data["length"]*.06 + 5
        data.pop("maxspeed")
    result = compute(graph, {1: .5, 2: 0}, time_attribute="with_signals_s", time_model="edge_attribute")
    assert result.summary["tt_reliability"] == pytest.approx(.5, abs=.04)
    assert result.summary["maxspeed_coverage"] is None
    assert result.summary["time_function"] == "supplied directed-edge attribute with_signals_s"


class ScenarioDelayModel:
    def prepare(self, graph, config):
        costs = {(u, v, key): 60. for u, v, key in graph.edges(keys=True) if u != v}
        def scenarios(context):
            # A sample-specific delay, even when no road closes: proves that the
            # reliability stage obtains costs from the provider on every sample.
            return {edge: value if context.sample_index is None else 120. for edge, value in costs.items()}
        return PreparedTimeModel(costs, {"status": "computed", "time_model": "test_delays"}, scenarios)


def test_custom_scenario_time_provider_and_context():
    graph = roads([(0, 1, 1000, None, True)])
    result = compute(graph, {1: 0}, samples=40, provider=ScenarioDelayModel())
    assert result.summary["tt_reliability"] == 0
    assert result.summary["time_model"] == "test_delays"
    assert result.summary["detour_factor_percentiles"]["p50"] == pytest.approx(2, rel=.004)
    calls = []
    def callback(context):
        calls.append(context)
        return {(u, v, key): 60 for u, v, key in graph.edges(keys=True)}
    prepared = PreparedTimeModel({}, {"status": "computed", "time_model": "recorded"}, callback)
    topology = TravelTimeTopology(graph, _link_rows(graph), prepared)
    topology.csr([False], sample_index=9)
    assert calls == [TimeContext(), TimeContext(9, frozenset({0}))]


@pytest.mark.parametrize("value", [0, -1, math.inf, math.nan, "word"])
def test_invalid_custom_edge_costs(value):
    graph = roads([(0, 1, 1000, None, True)])
    for _, _, data in graph.edges(data=True):
        data["seconds"] = value
    with pytest.raises(ValueError, match="travel_time"):
        compute(graph, time_attribute="seconds", **{"time_model": "edge_attribute"})


def test_missing_attribute_and_invalid_provider_contract():
    with pytest.raises(ValueError, match="missing"):
        compute(roads(), **{"time_model": "edge_attribute"})
    class Invalid:
        def prepare(self, graph, config):
            return {}
    with pytest.raises(ValueError, match="PreparedTimeModel"):
        prepare_time_model(roads(), TravelTimeConfig(), Invalid())


def ring(n=60):
    return roads([(i, (i+1) % n, 1000+(i % 7)*10, 40, True) for i in range(n)])


def test_worker_and_chunk_reproducibility_origins_and_od_independence():
    graph = ring()
    user = {way: .2 for way in range(1, 61)}
    serial = compute(graph, user, samples=1024, n_origins=8)
    parallel = compute(graph, user, samples=1024, n_origins=8, jobs=4)
    constrained = compute(graph, user, samples=1024, n_origins=8, jobs=4, budget=130000)
    assert parallel.computation["travel_time_workers"] == 4
    assert constrained.computation["travel_time_chunk_rows"] < parallel.computation["travel_time_chunk_rows"]
    for other in [parallel, constrained]:
        assert np.array_equal(serial.pair_fractions, other.pair_fractions)
        assert serial.summary == other.summary
        assert serial.node_metrics == other.node_metrics
    sampled = set(serial.summary["origin_node_ids"])
    assert len(sampled) == 8
    extra = next(node for node in graph if str(node) not in sampled)
    added = compute(graph, user, samples=1024, n_origins=8, od_inputs=od(("extra", extra, 0)))
    assert np.array_equal(serial.pair_fractions, added.pair_fractions)
    assert added.summary["routing_origins_including_od"] == 9
    assert added.node_metrics[extra]["p_tt_ok"] is None
    with pytest.raises(ValueError, match="too small"):
        compute(graph, budget=1)


def test_histogram_quantile_bounds_and_empty_extremes():
    values = np.r_[np.ones(80), np.full(20, 3)]
    counts = np.histogram(values, bins=HIST_EDGES)[0]
    quantiles, bounds = histogram_quantiles(counts)
    assert quantiles["p50"] == 1
    assert bounds["p90"][0] <= 3 <= bounds["p90"][1]
    assert quantiles["p90"] == pytest.approx(3, rel=.004)
    assert histogram_quantiles(np.zeros_like(counts))[0] == dict.fromkeys(["p50", "p90", "p99"])
    extreme = np.histogram([1e-9, 1e9], bins=HIST_EDGES)[0]
    assert histogram_quantiles(extreme)[0]["p50"] is None
    assert histogram_quantiles(extreme)[0]["p99"] is None


def test_ci_coverage_across_100_predefined_seeds():
    covered = 0
    for seed in range(100):
        result = compute(roads(), {1: .5, 2: 0}, seed=seed, samples=200)
        interval = mean_interval(result.pair_fractions, confidence=.99)
        covered += interval["ci_low"] <= .5 <= interval["ci_high"]
    assert covered >= 95


@pytest.mark.parametrize("settings", [{"samples": 1}, {"n_origins": 0}, {"tau": -1}, {"tau": math.inf},
    {"highway_speeds_kph": {}}, {"highway_speeds_kph": {"residential": 0}},
    {"highway_speeds_kph": {"residential": math.nan}}, {"time_attribute": " "}, {"time_model": "unknown"}])
def test_config_validation(settings):
    with pytest.raises(ValueError):
        TravelTimeConfig(**settings)


def test_pipeline_merged_od_fields_and_skip_overwrite(tmp_path):
    from pyproj import Transformer
    graph = roads()
    source = tmp_path/"roads.graphml"
    ox.save_graphml(graph, source)
    probabilities = tmp_path/"probabilities.csv"
    probabilities.write_text("osm_way_id,p_fail\n1,.5\n2,0\n")
    transformer = Transformer.from_crs(32644, 4326, always_xy=True)
    a, b = [transformer.transform(graph.nodes[node]["x"], graph.nodes[node]["y"]) for node in [0, 1]]
    path = tmp_path/"od.csv"
    path.write_text("label,origin_lon,origin_lat,dest_lon,dest_lat\n" + f"forward,{a[0]},{a[1]},{b[0]},{b[1]}\n")
    config = RunConfig(input={"path": source}, cleaning={"consolidate": False},
                       analysis={"n_jobs": 1, "max_memory_gb": .1},
                       robustness={"steps": 1, "failure_runs": 1, "removal": ["nodes"]},
                       reliability={"samples": 128, "p_fail_csv": probabilities, "od_pairs_csv": path},
                       travel_time={"samples": 256}, output={"dir": tmp_path/"out", "figures": False})
    summary = run(config)
    out = config.output.dir
    nodes = gpd.read_file(out/"network.gpkg", layer="nodes")
    assert {"p_tt_ok", "p_tt_ok_ci_low", "p_tt_ok_ci_high"} <= set(nodes.columns)
    row = next(csv.DictReader((out/"od_reliability.csv").open()))
    assert {"p_od", "ci_low", "ci_high", "p_tt_ok", "p_tt_ok_ci_low", "p_tt_ok_ci_high", "tt0_min"} <= row.keys()
    assert float(row["tt0_min"]) == 1
    assert summary["reliability"]["samples"] == 128 and summary["travel_time"]["samples"] == 256
    assert load_config(out/"run_config.yaml").travel_time == config.travel_time
    json.dumps(summary, allow_nan=False)
    report = (out/"report.txt").read_text()
    assert report.isascii() and max(map(len, report.splitlines())) <= 100
    assert "free-flow speeds; no traffic (Tier 4)" in report
    custom = run(config, overwrite=True, time_model=ScenarioDelayModel())
    assert custom["travel_time"]["time_model"] == "test_delays"
    resolved = load_config(out/"run_config.yaml")
    assert resolved.travel_time.time_model == "custom"
    with pytest.raises(ValueError, match="requires a Python"):
        prepare_time_model(graph, resolved.travel_time)
    config.travel_time.enabled = False
    run(config, overwrite=True)
    row = next(csv.DictReader((out/"od_reliability.csv").open()))
    assert "p_tt_ok" not in row
    assert gpd.read_file(out/"network.gpkg", layer="nodes").p_tt_ok.isna().all()


def test_multinode_mc_against_independent_exact_enumeration():
    graph = roads([(0, 1, 1000, 60, True), (0, 1, 3000, 30, True),
                   (1, 2, 1000, 40, False), (2, 0, 1200, 30, False)])
    links = _link_rows(graph)
    user = {1: .2, 2: .35, 3: .4, 4: .1}
    for _, _, data in graph.edges(data=True):
        data["seconds"] = 3.6*data["length"]/float(data["maxspeed"])
    baseline = np.asarray(nx.floyd_warshall_numpy(graph, weight="seconds"))
    expected = 0.
    for up in itertools.product([False, True], repeat=len(links)):
        probabilities = [user[int(link["osm_way_ids"])] for link in links]
        mass = math.prod(1-p if state else p for p, state in zip(probabilities, up))
        changed = graph.copy()
        for link, state in zip(links, up):
            if not state:
                changed.remove_edges_from(link["_edges"])
        damaged = np.asarray(nx.floyd_warshall_numpy(changed, weight="seconds"))
        successes = sum(math.isfinite(damaged[i,j]) and damaged[i,j] <= 1.3*baseline[i,j]+1e-9
                        for i in range(3) for j in range(3) if i != j)
        expected += mass*successes/6
    result = compute(graph, user, samples=5000, tau=.3)
    interval = mean_interval(result.pair_fractions, confidence=.99)
    assert interval["ci_low"] <= expected <= interval["ci_high"]


def test_demo_generator_all_seven_scenarios(tmp_path):
    folder = tmp_path/"demo"
    subprocess.run([sys.executable, "examples/create_ticket10_demo.py", "--out", str(folder),
                    "--nodes", "20", "--samples", "128"], check=True, capture_output=True, text=True)
    manifest = json.loads((folder/"manifest.json").read_text())
    expected = json.loads((folder/"expected.json").read_text())
    assert len(manifest["scenarios"]) == 7
    for name in manifest["scenarios"]:
        config = load_config(folder/f"{name}.yaml")
        config.output.dir = tmp_path/name
        config.reliability.samples = 128
        result = run(config)["travel_time"]
        if name == "skip":
            assert result["status"] == expected[name]["status"]
        elif name != "sparse":
            assert result["tt_reliability"] == pytest.approx(expected[name]["p_tt_ok"], abs=.12)
            assert result["od_pairs"][0]["tt0_min"] == expected[name]["tt0_min"]
        else:
            assert result["status"] == "computed" and result["n_origins"] == 20


def test_all_closed_singleton_and_time_model_contract_limits():
    graph = roads([(0, 1, 1000, 60, True)])
    result = compute(graph, {1: 1}, samples=16, od_inputs=od(("same", 0, 0)))
    assert result.summary["tt_reliability"] == 0
    assert result.summary["detour_histogram"]["reachable_pair_observations"] == 0
    assert result.summary["detour_factor_percentiles"] == dict.fromkeys(["p50", "p90", "p99"])
    assert result.od_metrics["same"]["p_tt_ok"] == 1
    singleton = roads([], n=1)
    result = compute(singleton, samples=16, time_model="edge_attribute", od_inputs=od(("same", 0, 0)))
    assert result.summary["tt_reliability"] is None
    assert result.node_metrics[0]["p_tt_ok"] is None
    assert result.od_metrics["same"]["p_tt_ok"] == 1
    json.dumps(result.summary, allow_nan=False)
    class WrongUnits:
        def prepare(self, graph, config):
            return PreparedTimeModel({}, {"status": "computed", "time_model": "wrong", "time_units": "minutes"})
    with pytest.raises(ValueError, match="seconds"):
        compute(graph, provider=WrongUnits())
    class InvalidScenario:
        def prepare(self, graph, config):
            costs = {(u,v,k): 60 for u,v,k in graph.edges(keys=True)}
            return PreparedTimeModel(costs, {"status": "computed", "time_model": "invalid"},
                                     lambda context: costs if context.sample_index is None else dict.fromkeys(costs, 0))
    with pytest.raises(ValueError, match="strictly positive"):
        compute(graph, provider=InvalidScenario())
