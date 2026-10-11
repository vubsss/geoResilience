import csv
import importlib.util
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
from pyproj import Transformer
from scipy.stats import t

from georesilience.config import ReliabilityConfig, RunConfig, load_config
from georesilience.connectivity import (ConnectivityTopology, ODInputs, _importance, compute_connectivity,
                                       load_od_pairs, mean_interval, wilson_interval)
from georesilience.links import _link_rows
from georesilience.pipeline import run


def roads(edges, nodes=None):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    if nodes is None:
        nodes = sorted({node for u, v, *_ in edges for node in (u, v)})
    for index, node in enumerate(nodes):
        graph.add_node(node, x=float(500000 + index*100), y=float(1900000 + (index % 2)*100))
    for way, (u, v, two_way) in enumerate(edges, 1):
        for a, b in [(u, v), (v, u)] if two_way else [(u, v)]:
            graph.add_edge(a, b, length=float(1000 + way), osmid=way, highway="residential")
    return graph


def compute(graph, user=None, *, samples=1000, seed=42, jobs=1, weights=None, **settings):
    config = ReliabilityConfig(samples=samples, **settings)
    return compute_connectivity(graph, _link_rows(graph), config, user or {}, seed=seed, n_jobs=jobs,
                                budget_bytes=32*1024**2, weights=weights)


def exact_reference(graph, probabilities, weights=None, pairs=()):
    """Independent NetworkX enumeration, including direction and physical closures."""
    links = [link for link in _link_rows(graph) if not link["is_self_loop"]]
    assert len(links) <= 15
    nodes = list(graph)
    masses = dict(zip(nodes, np.ones(len(nodes)) if weights is None else weights))
    denominator = sum(masses[u]*masses[v] for u in nodes for v in nodes if u != v)
    total, node_values, od_values = 0.0, dict.fromkeys(nodes, 0.0), np.zeros(len(pairs))
    down_sum, up_sum = np.zeros(len(links)), np.zeros(len(links))
    down_prob, up_prob = np.zeros(len(links)), np.zeros(len(links))
    for down in itertools.product([False, True], repeat=len(links)):
        probability = math.prod(probabilities[link["link_id"]] if failed else 1-probabilities[link["link_id"]]
                                for link, failed in zip(links, down))
        changed = nx.DiGraph()
        changed.add_nodes_from(nodes)
        for link, failed in zip(links, down):
            if not failed:
                changed.add_edges_from((u, v) for u, v, _ in link["_edges"])
        components = list(nx.strongly_connected_components(changed))
        numerator = sum(masses[u]*masses[v] for component in components for u in component
                        for v in component if u != v)
        value = numerator/denominator if denominator else 0
        main = min(components, key=lambda component: (-len(component), min(component)))
        total += probability*value
        for node in main:
            node_values[node] += probability
        for index, (origin, dest) in enumerate(pairs):
            od_values[index] += probability*nx.has_path(changed, origin, dest)
        for index, failed in enumerate(down):
            if failed:
                down_sum[index] += probability*value
                down_prob[index] += probability
            else:
                up_sum[index] += probability*value
                up_prob[index] += probability
    importance = [up_sum[i]/up_prob[i] - down_sum[i]/down_prob[i]
                  if up_prob[i] and down_prob[i] else None for i in range(len(links))]
    return total, node_values, od_values, importance


def write_od(path, graph, pairs):
    transform = Transformer.from_crs(graph.graph["crs"], 4326, always_xy=True)
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["label", "origin_lon", "origin_lat", "dest_lon", "dest_lat"])
        for label, origin, dest in pairs:
            a, b = graph.nodes[origin], graph.nodes[dest]
            writer.writerow([label, *transform.transform(a["x"], a["y"]), *transform.transform(b["x"], b["y"])])
    return path


def test_two_node_corrected_acceptance_and_all_ci_fields():
    graph = roads([(0, 1, True)])
    result = compute(graph, {1: .5}, samples=10000)
    assert result.summary["ci_low"] < .5 < result.summary["ci_high"]
    assert result.node_metrics[0]["p_connected"] == 1
    assert result.node_metrics[1]["p_connected"] == result.summary["conn_reliability"]
    assert result.node_metrics[1]["p_connected"] == pytest.approx(.5, abs=.02)
    assert result.link_metrics[0]["rel_importance"] == 1
    assert result.link_metrics[0]["rel_importance_ci_low"] == 1
    assert result.summary["node"]["p_connected_mean"] == pytest.approx(.75, abs=.01)
    assert result.summary["unique_probability_vectors"] == 1
    json.dumps(result.summary, allow_nan=False)


@pytest.mark.parametrize("probability,network,status", [(0, 1, "insufficient_down"), (1, 0, "insufficient_up")])
def test_never_down_never_up_and_numeric_id_ties(probability, network, status):
    graph = roads([(10, 2, True)], nodes=[10, 2])
    result = compute(graph, {1: probability})
    assert result.summary["conn_reliability"] == network
    assert result.link_metrics[0]["rel_importance"] is None
    assert result.link_metrics[0]["rel_importance_status"] == status
    assert result.link_metrics[0]["rel_up_count"] == (1-probability)*1000
    assert result.link_metrics[0]["rel_down_count"] == probability*1000
    if probability == 1:
        assert result.node_metrics[2]["p_connected"] == 1
        assert result.node_metrics[10]["p_connected"] == 0


@pytest.mark.parametrize("probability,status", [(.001, "insufficient_down"), (.999, "insufficient_up")])
def test_minimum_counts_in_both_states(probability, status):
    result = compute(roads([(0, 1, True)]), {1: probability})
    assert result.link_metrics[0]["rel_importance_status"] == status
    assert result.link_metrics[0]["rel_importance_ci_low"] is None


def test_directed_od_and_mutual_pairs_are_distinct(tmp_path):
    graph = roads([(0, 1, False), (1, 0, False)])
    path = write_od(tmp_path / "od.csv", graph, [("forward", 0, 1), ("reverse", 1, 0), ("same", 1, 1)])
    result = compute(graph, {1: 0, 2: .5}, od_pairs_csv=path, samples=10000)
    assert result.od_rows[0]["p_od"] == 1
    assert result.od_rows[1]["p_od"] == result.summary["conn_reliability"]
    assert result.od_rows[2]["p_od"] == 1
    topology = ConnectivityTopology(graph, _link_rows(graph))
    snapped = load_od_pairs(graph, path)
    score, main, od = topology.evaluate([True, False], snapped.pairs)
    assert score == 0 and od.tolist() == [True, False, True]
    assert main.tolist() == [True, False]


def test_bfs_reused_per_distinct_origin(monkeypatch):
    graph = roads([(0, 1, False)], nodes=[0, 1, 2])
    topology = ConnectivityTopology(graph, _link_rows(graph))
    pairs = [{"_origin": 0, "_dest": 1}, {"_origin": 0, "_dest": 2}, {"_origin": 1, "_dest": 0}]
    from georesilience import connectivity
    original = connectivity.breadth_first_order
    calls = []
    def wrapped(graph, origin, **kwargs):
        calls.append(origin)
        return original(graph, origin, **kwargs)
    monkeypatch.setattr(connectivity, "breadth_first_order", wrapped)
    _, _, od = topology.evaluate([True], pairs)
    assert od.tolist() == [True, False, False] and calls == [0, 1]


@pytest.mark.parametrize("edges,weights", [
    ([(0, 1, True), (1, 2, True), (2, 0, True)], None),
    ([(0, 1, True), (1, 2, True), (2, 0, True)], [1, 2, 7]),
    ([(0, 1, False), (1, 2, False), (2, 0, False)], None),
    ([(0, 1, True), (0, 1, True)], None),
])
def test_every_failure_state_against_independent_networkx(edges, weights):
    graph = roads(edges)
    links = _link_rows(graph)
    topology = ConnectivityTopology(graph, links, weights)
    nodes = list(graph)
    pairs = [(u, v) for u in nodes for v in nodes if u != v]
    od = [{"_origin": nodes.index(u), "_dest": nodes.index(v)} for u, v in pairs]
    for up in itertools.product([False, True], repeat=len(links)):
        expected = exact_reference(graph, {index: 0 if state else 1 for index, state in enumerate(up)}, weights, pairs)
        value, main, reachable = topology.evaluate(up, od)
        assert value == pytest.approx(expected[0])
        assert main.tolist() == [bool(expected[1][node]) for node in nodes]
        assert reachable.tolist() == list(map(bool, expected[2]))


def test_parallel_road_reliability_and_importance():
    graph = roads([(0, 1, True), (0, 1, True)])
    expected = exact_reference(graph, {0: .5, 1: .25})
    assert expected[0] == .875 and expected[3] == [.25, .5]
    result = compute(graph, {1: .5, 2: .25}, samples=10000)
    assert result.summary["conn_reliability"] == pytest.approx(.875, abs=.02)
    for row, value in zip(result.link_metrics.values(), expected[3]):
        assert row["rel_importance"] == pytest.approx(value, abs=.03)
        assert row["rel_importance_ci_low"] <= value <= row["rel_importance_ci_high"]


def test_exact_enumeration_and_99_percent_ci_coverage_100_seeds():
    graph = roads([(0, 1, True), (1, 2, True), (2, 0, True)])
    user = {1: .2, 2: .3, 3: .4}
    exact = exact_reference(graph, {way-1: value for way, value in user.items()})[0]
    covered = 0
    for seed in range(100):
        result = compute(graph, user, samples=400, seed=seed)
        ci = mean_interval(result.pair_fractions[:, 0], confidence=.99)
        covered += ci["ci_low"] <= exact <= ci["ci_high"]
    assert covered >= 95


def test_wilson_and_welch_intervals_independent_known_answers():
    low, high = wilson_interval([0, 50, 100], 100)
    assert low[0] == 0 and high[2] == 1
    assert low[1] == pytest.approx(.40383153) and high[1] == pytest.approx(.59616847)
    up, down = np.array([.8, .9, 1]), np.array([.1, .2, .3])
    config = ReliabilityConfig(min_up_count=2, min_down_count=2)
    row = _importance(3, down.sum(), down@down, up.sum(), up@up, 6, config, True)
    half = t.ppf(.975, 4)*math.sqrt((.01+.01)/3)
    assert row["rel_importance"] == pytest.approx(.7)
    assert row["rel_importance_ci_low"] == pytest.approx(.7-half)
    assert row["rel_importance_ci_high"] == pytest.approx(.7+half)
    assert mean_interval([0, 1]) == {"conn_reliability": .5, "ci_low": 0, "ci_high": 1}


def spatial_graph():
    spec = importlib.util.spec_from_file_location("ticket08", "examples/create_ticket08_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.spatial_graph(200, 42)[0]


def test_jobs_1_and_4_memory_limits_and_common_uniform_sweep():
    graph = spatial_graph()
    config = ReliabilityConfig(samples=1024)
    links = _link_rows(graph)
    def call(jobs, budget):
        return compute_connectivity(graph, links, config, {}, seed=42, n_jobs=jobs, budget_bytes=budget)
    serial = call(1, 32*1024**2)
    parallel = call(4, 32*1024**2)
    constrained = call(4, 750000)
    assert parallel.computation["reliability_workers"] == 4
    assert constrained.computation["reliability_workers"] == 1
    for other in [parallel, constrained]:
        assert np.array_equal(serial.pair_fractions, other.pair_fractions)
        assert serial.node_metrics == other.node_metrics and serial.link_metrics == other.link_metrics
        assert serial.summary == other.summary
    assert np.all(np.diff(serial.pair_fractions, axis=1) <= 0)
    with pytest.raises(ValueError, match="too small"):
        call(1, 1)


def test_seed_sample_prefix_and_sweep_primary_independence():
    graph = roads([(0, 1, True), (1, 2, True)])
    short = compute(graph, samples=300, p0=.3, p0_sweep=[.3])
    longer = compute(graph, samples=600, p0=.3, p0_sweep=[.3])
    swept = compute(graph, samples=300, p0=.3, p0_sweep=[.1, .3, .6])
    assert np.array_equal(short.pair_fractions, longer.pair_fractions[:300])
    assert np.array_equal(short.pair_fractions[:, 0], swept.pair_fractions[:, 1])
    assert short.node_metrics == swept.node_metrics and short.link_metrics == swept.link_metrics
    changed = compute(graph, samples=300, p0=.3, p0_sweep=[.3], seed=43)
    assert not np.array_equal(short.pair_fractions, changed.pair_fractions)


def test_weights_zero_pair_universe_and_self_loops():
    graph = roads([(0, 1, True), (1, 2, True)])
    graph.add_edge(0, 0, length=0, osmid=99)
    result = compute(graph, {1: .2, 2: .4}, weights=[1, 2, 7], samples=10000)
    links = _link_rows(graph)
    expected = exact_reference(graph, {link['link_id']: {1: .2, 2: .4}[int(link['osm_way_ids'])]
                                        for link in links if not link['is_self_loop']}, [1, 2, 7])[0]
    assert result.summary["conn_reliability"] == pytest.approx(expected, abs=.02)
    loop_id = next(link['link_id'] for link in links if link['is_self_loop'])
    assert result.link_metrics[loop_id]["rel_importance_status"] == "self_loop"
    assert result.link_metrics[loop_id]["rel_down_count"] == 0
    zero = compute(graph, weights=[0, 0, 0], samples=10)
    assert zero.summary["conn_reliability"] is None
    road_id = next(link['link_id'] for link in links if not link['is_self_loop'])
    assert zero.link_metrics[road_id]["rel_importance_status"] == "undefined_pair_universe"
    json.dumps(zero.summary, allow_nan=False)
    singleton = roads([], nodes=[0])
    assert compute(singleton, samples=10).summary["conn_reliability"] is None


@pytest.mark.parametrize("weights", [[1], [1, -1], [1, math.nan]])
def test_invalid_weights(weights):
    with pytest.raises(ValueError, match="weights"):
        compute(roads([(0, 1, True)]), weights=weights)


@pytest.mark.parametrize("settings", [{"samples": 1}, {"min_up_count": 1}, {"min_down_count": 1}])
def test_new_config_validation(settings):
    with pytest.raises(ValueError):
        ReliabilityConfig(**settings)


@pytest.mark.parametrize("row", ["x,181,0,0,0\n", "x,0,91,0,0\n", "x,NaN,0,0,0\n",
                                 "x,word,0,0,0\n", ",0,0,0,0\n", "x,0,0,0,0\nx,0,0,0,0\n"])
def test_od_csv_validation(tmp_path, row):
    path = tmp_path / "bad.csv"
    path.write_text("label,origin_lon,origin_lat,dest_lon,dest_lat\n" + row)
    with pytest.raises(ValueError, match="OD data row"):
        load_od_pairs(roads([(0, 1, True)]), path)


def test_od_snapping_far_warning_ties_and_missing_columns(tmp_path):
    graph = roads([(10, 2, True)], nodes=[10, 2])
    graph.nodes[2].update(graph.nodes[10])
    path = write_od(tmp_path / "ties.csv", graph, [("tie", 10, 2)])
    result = load_od_pairs(graph, path)
    assert result.pairs[0]["origin_node_id"] == result.pairs[0]["dest_node_id"] == "2"
    transform = Transformer.from_crs(32644, 4326, always_xy=True)
    lon, lat = transform.transform(510000, 1910000)
    path.write_text("label,origin_lon,origin_lat,dest_lon,dest_lat\n" +
                    "".join(f"far-{i},{lon},{lat},{lon},{lat}\n" for i in range(12)))
    result = load_od_pairs(graph, path)
    assert result.warnings["total_count"] == 24 and len(result.warnings["shown"]) == 20
    assert result.warnings["omitted_count"] == 4
    path.write_text("label,origin_lon\nx,0\n")
    with pytest.raises(ValueError, match="missing columns"):
        load_od_pairs(graph, path)
    path.write_text("label,origin_lon,origin_lat,dest_lon,dest_lat\n")
    assert load_od_pairs(graph, path).pairs == []


def test_pipeline_preserves_coverage_exports_cis_and_cleans_stale_outputs(tmp_path):
    graph = roads([(0, 1, False), (1, 0, False)])
    source = tmp_path / "graph.graphml"
    ox.save_graphml(graph, source)
    probabilities = tmp_path / "probabilities.csv"
    probabilities.write_text("osm_way_id,p_fail\n1,0\n2,.5\n")
    od = write_od(tmp_path / "od.csv", graph, [("forward", 0, 1), ("reverse", 1, 0)])
    config = RunConfig(input={"path": source}, cleaning={"consolidate": False},
                       analysis={"n_jobs": 1, "max_memory_gb": .1},
                       robustness={"steps": 1, "failure_runs": 1, "removal": ["nodes"]},
                       reliability={"samples": 256, "p_fail_csv": probabilities, "od_pairs_csv": od,
                                    "min_down_count": 2, "min_up_count": 2}, output={"dir": tmp_path / "out"})
    summary = run(config)
    out = config.output.dir
    reliability = summary["reliability"]
    assert reliability["coverage"]["by_source"]["user"]["links_pct"] == 100
    assert reliability["warnings"]["total_count"] == 0
    nodes = gpd.read_file(out / "network.gpkg", layer="nodes")
    edges = gpd.read_file(out / "network.gpkg", layer="edges")
    assert {"p_connected", "p_connected_ci_low", "p_connected_ci_high"} <= set(nodes.columns)
    assert {"p_fail", "p_fail_source", "rel_importance", "rel_up_count", "rel_down_count",
            "rel_importance_ci_low", "rel_importance_ci_high", "rel_importance_status"} <= set(edges.columns)
    assert (out / "figures/connectivity_nodes_map.png").stat().st_size > 1000
    assert (out / "od_reliability.csv").is_file()
    assert json.loads(json.dumps(summary, allow_nan=False)) == json.loads((out / "summary.json").read_text())
    resolved = load_config(out / "run_config.yaml")
    assert resolved.reliability == config.reliability
    report = (out / "report.txt").read_text()
    assert "mutually reachable distinct node pairs" in report and "main-SCC membership" in report
    assert report.isascii() and max(map(len, report.splitlines())) <= 100
    resolved.output.figures = False
    resolved.reliability.od_pairs_csv = None
    run(resolved, overwrite=True)
    assert not (out / "od_reliability.csv").exists()
    assert not (out / "figures/connectivity_nodes_map.png").exists()


def test_bad_od_stops_before_centralities(tmp_path, monkeypatch):
    graph = roads([(0, 1, True)])
    source = tmp_path / "graph.graphml"
    ox.save_graphml(graph, source)
    path = tmp_path / "bad.csv"
    path.write_text("label,origin_lon,origin_lat,dest_lon,dest_lat\nx,word,0,0,0\n")
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid OD must fail before centralities")
    monkeypatch.setattr("georesilience.pipeline.compute_centralities", forbidden)
    config = RunConfig(input={"path": source}, cleaning={"consolidate": False},
                       reliability={"od_pairs_csv": path}, output={"dir": tmp_path / "out"})
    with pytest.raises(ValueError, match="OD data row 1"):
        run(config)


def test_demo_generation_and_all_six_scenarios(tmp_path):
    folder = tmp_path / "demo"
    subprocess.run([sys.executable, "examples/create_ticket09_demo.py", "--out", str(folder),
                    "--nodes", "20", "--samples", "512"], check=True, capture_output=True, text=True)
    manifest = json.loads((folder / "manifest.json").read_text())
    assert len(manifest["scenarios"]) == 6
    for name in manifest["scenarios"]:
        config = load_config(folder / f"{name}.yaml")
        config.output.dir = tmp_path / name
        config.output.figures = False
        summary = run(config)
        reliability = summary["reliability"]
        assert reliability["samples"] == 512
        assert len(reliability["od_pairs"]) == (3 if name.startswith("spatial") else 2)
        assert len(reliability["sweep"]) == 3
        assert (config.output.dir / "od_reliability.csv").is_file()
        if name.startswith("spatial"):
            assert len(gpd.read_file(config.output.dir / "network.gpkg", layer="nodes")) == 20
        else:
            reference = json.loads((folder / f"{name}-expected.json").read_text())
            assert reliability["conn_reliability"] == pytest.approx(reference["conn_reliability"], abs=.07)
    half = json.loads((folder / "half-expected.json").read_text())
    assert half["conn_reliability"] == .5
    assert half["node_membership"] == {"0": 1, "1": .5}
    directed = json.loads((folder / "directed-expected.json").read_text())
    assert directed["od_reliability"] == {"forward": 1, "reverse": .5}
