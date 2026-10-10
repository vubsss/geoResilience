import json
import math
import subprocess
import sys

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
import pytest

from georesilience.config import RobustnessConfig, RunConfig, load_config
from georesilience.links import _link_rows
from georesilience.pipeline import run
from georesilience.removal import ActiveEdgeGraph
from georesilience.robustness import (CURVE_COLUMNS, attack_scores, compute_robustness, normalized_auc,
                                     removal_schedule, sampled_efficiency)


def road_graph(simple):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for i, node in enumerate(simple):
        graph.add_node(node, x=500000 + i * 100, y=1900000 + (i % 3) * 100)
    for way, (u, v, data) in enumerate(simple.edges(data=True), 1):
        for a, b in ((u, v), (v, u)):
            graph.add_edge(a, b, length=data.get("length", 1.0), osmid=way, highway="residential")
    return graph


def compute(graph, config=None, seed=42, jobs=1, budget=1024**2, weights=None):
    return compute_robustness(graph, _link_rows(graph), config or RobustnessConfig(),
                              seed=seed, n_jobs=jobs, budget_bytes=budget, weights=weights)


def test_star_ring_and_actual_integer_schedule():
    graph = road_graph(nx.star_graph(4))
    config = RobustnessConfig(removal=["nodes"], steps=1, f_max=.2, node_attack_metric="degree", failure_runs=2)
    result = compute(graph, config)
    assert result.removals[("nodes", "attack", 0)][1] == (0,)
    attack = [row for row in result.rows if row["mode"] == "attack"]
    assert attack[1]["S_scc"] == attack[1]["S_wcc"] == 1 / 5
    assert attack[1]["E_rel"] == 0
    assert result.summary["nodes"]["auc_attack_S"] == .6
    assert result.summary["nodes"]["f_half_attack"] == .2
    config = RobustnessConfig(removal=["links"], steps=1, f_max=.25, failure_runs=5)
    result = compute(road_graph(nx.cycle_graph(4)), config)
    assert all(row["S_scc"] == 1 for row in result.rows)
    assert all(row["E_rel"] == pytest.approx(13 / 15) for row in result.rows if row["step"] == 1)
    assert result.summary["links"]["headline"]
    # Independent per-step rounding would remove zero; cumulative counts do not.
    counts = removal_schedule(500, 50, .2)
    assert counts[-1] == 100 and np.all(np.diff(counts) == 2)
    counts = removal_schedule(5, 50, .2)
    assert counts[-1] == 1 and np.count_nonzero(np.diff(counts)) == 1
    counts = removal_schedule(7, 50, .2)
    assert counts[-1] == 1 and counts[-1] / 7 <= .2
    assert removal_schedule(5, 50, .19999999999999)[-1] == 0
    assert normalized_auc([{"f": 0, "S_scc": 1}, {"f": 1/7, "S_scc": .5}], "S_scc", .2) == pytest.approx(19 / 28)


def test_adaptive_and_static_second_removal_differ():
    graph = road_graph(nx.path_graph(6))
    config = RobustnessConfig(removal=["links"], steps=2, f_max=.4, failure_runs=1)
    adaptive = compute(graph, config)
    config.adaptive = False
    static = compute(graph, config)
    assert adaptive.removals[("links", "attack", 0)] == [(), (2,), (0,)]
    assert static.removals[("links", "attack", 0)] == [(), (2,), (1,)]


def test_direction_parallel_link_scores_and_node_removal_denominators():
    graph = road_graph(nx.path_graph(2))
    for u, v in ((0, 1), (1, 0)):
        graph.add_edge(u, v, length=2, osmid=99)
    graph.add_edge(0, 0, length=0, osmid=100)
    links = _link_rows(graph)
    active = ActiveEdgeGraph(graph, links)
    scores = attack_scores(active, active.csr(), "links", set(active.link_arcs), set(), set(), "betweenness", 2)
    primary = next(row["link_id"] for row in links if row["osm_way_ids"] == "1")
    backup = next(row["link_id"] for row in links if row["osm_way_ids"] == "99")
    assert scores[primary] == 1 and scores[backup] == 0
    changed = active.csr([primary])
    scores = attack_scores(active, changed, "links", {backup}, {primary}, set(), "betweenness", 2)
    assert scores[backup] == 1
    config = RobustnessConfig(removal=["links"], steps=1, f_max=.5, failure_runs=1)
    result = compute(graph, config)
    assert result.summary["links"]["parameters"]["total_elements"] == 2  # Self-loop excluded.
    assert result.removals[("links", "attack", 0)][1] == (primary,)
    cycle = nx.MultiDiGraph()
    for node in range(3):
        cycle.add_node(node, x=float(node), y=0.)
    for u, v in ((0, 1), (1, 2), (2, 0)):
        cycle.add_edge(u, v, length=1, osmid=u)
    result = compute(cycle, RobustnessConfig(removal=["links"], steps=1, f_max=1/3, failure_runs=1))
    assert all(row["S_scc"] == 1/3 and row["S_wcc"] == 1 for row in result.rows if row["step"])
    graph = road_graph(nx.path_graph(3))
    config = RobustnessConfig(removal=["nodes"], steps=3, f_max=1, node_attack_metric="degree", failure_runs=1)
    result = compute(graph, config, weights=[1, 2, 3])
    assert result.summary["baseline_sampled_efficiency"] == pytest.approx(19 / 22)
    attack = [row for row in result.rows if row["mode"] == "attack"]
    assert attack[1]["E_rel"] == 0  # Isolating the hub destroys every weighted trip.
    assert attack[-1]["S_scc"] == attack[-1]["S_wcc"] == 0  # Removed isolates are not alive.


def test_seed_jobs_chunks_and_element_stream_independence():
    simple = nx.convert_node_labels_to_integers(nx.grid_2d_graph(6, 6))
    rng = np.random.default_rng(13)
    for u, v in simple.edges:
        simple[u][v]["length"] = rng.uniform(1, 1.3)
    graph = road_graph(simple)
    config = RobustnessConfig(steps=3, f_max=.2, failure_runs=2, efficiency_sources=10)
    baseline = compute(graph, config, budget=300)
    for jobs in (1, 2):
        other = compute(graph, config, jobs=jobs, budget=300)
        assert other.rows == baseline.rows
        assert other.removals == baseline.removals
    other = compute(graph, config, seed=43)
    assert other.removals != baseline.removals
    config.removal = ["nodes"]
    nodes = compute(graph, config)
    assert nodes.rows == [row for row in baseline.rows if row["element"] == "nodes"]
    config.removal = ["nodes", "links"]
    reversed_order = compute(graph, config)
    assert reversed_order.rows == baseline.rows
    config.failure_runs = 3
    extra = compute(graph, config)
    assert [row for row in extra.rows if row["run"] <= 2] == baseline.rows


@pytest.mark.parametrize("seed", [11, 42])
def test_200_node_directed_spatial_graph_all_steps_against_networkx(seed):
    rng = np.random.default_rng(seed)
    simple = nx.random_geometric_graph(200, .18, seed=seed)
    assert nx.is_connected(simple)
    for u, v in simple.edges:
        simple[u][v]["length"] = 1000 * math.dist(simple.nodes[u]["pos"], simple.nodes[v]["pos"]) * rng.uniform(1, 1.3)
    graph = road_graph(simple)
    backbone = {frozenset(pair) for pair in nx.minimum_spanning_tree(simple, weight="length").edges}
    for u, v in simple.edges:
        if frozenset((u, v)) not in backbone and rng.random() < .4:
            graph.remove_edge(v, u)
    links = _link_rows(graph)
    result = compute(graph, RobustnessConfig(steps=3, f_max=.2, failure_runs=2, efficiency_sources=500))
    assert result.summary["efficiency_exact"]
    original = sum(1/d for source, distances in nx.all_pairs_dijkstra_path_length(graph, weight="length")
                   for target, d in distances.items() if source != target)
    link_map = {row["link_id"]: row for row in links}
    for key, increments in result.removals.items():
        element, mode, run_id = key
        copy = graph.copy()
        curve = [row for row in result.rows if (row["element"], row["mode"], row["run"]) == key]
        for row, batch in zip(curve, increments):
            if element == "links":
                for link_id in batch:
                    copy.remove_edges_from(link_map[link_id]["_edges"])
            else:
                copy.remove_nodes_from(batch)
            inverse = sum(1/d for source, distances in nx.all_pairs_dijkstra_path_length(copy, weight="length")
                          for target, d in distances.items() if source != target)
            assert row["E_rel"] == pytest.approx(inverse / original, abs=1e-9)
            strong = max(map(len, nx.strongly_connected_components(copy)), default=0) / 200
            weak = max(map(len, nx.weakly_connected_components(copy)), default=0) / 200
            assert row["S_scc"] == strong and row["S_wcc"] == weak
    # Independent initial attack scores, not just measurements after our ranking.
    active = ActiveEdgeGraph(graph, links)
    scores = attack_scores(active, active.csr(), "nodes", set(graph), set(), set(), "betweenness", 1)
    expected = nx.betweenness_centrality(graph, normalized=False, weight="length")
    np.testing.assert_allclose([scores[node] for node in graph], [expected[node] for node in graph], atol=1e-9)


def test_fixed_removed_source_normalization_and_invalid_configs():
    graph = road_graph(nx.path_graph(4))
    active = ActiveEdgeGraph(graph, _link_rows(graph))
    sources = np.array([1, 3])
    before = sampled_efficiency(active.csr(), sources, np.ones(4), n_jobs=1, budget_bytes=1000)
    after = sampled_efficiency(active.csr(isolated_nodes=[1]), sources, np.ones(4), n_jobs=1, budget_bytes=1000)
    assert before == pytest.approx((2.5 + 1 + .5 + 1/3) / 6)
    assert after == pytest.approx(1 / 6)  # Removed source 1 remains in the two-source denominator.
    for values in ({"removal": []}, {"removal": ["links", "links"]}, {"removal": ["roads"]},
                   {"steps": 0}, {"f_max": 0}, {"f_max": 1.1}, {"f_max": math.nan},
                   {"failure_runs": 0}, {"efficiency_sources": 0}, {"node_attack_metric": "unknown"}):
        with pytest.raises(ValueError):
            RobustnessConfig(**values)
    with pytest.raises(ValueError, match="seed"):
        RunConfig(input={"path": "unused.graphml"}, analysis={"seed": -1})
    singleton = road_graph(nx.empty_graph(1))
    result = compute(singleton, RobustnessConfig(steps=1, failure_runs=1))
    assert result.summary["links"]["auc_attack_E"] is None
    json.dumps(result.summary, allow_nan=False)


def test_outputs_bands_auc_and_overwrite(tmp_path, capsys):
    graph = road_graph(nx.cycle_graph(6))
    source = tmp_path / "ring.graphml"
    ox.save_graphml(graph, source)
    config = RunConfig(input={"path": source}, cleaning={"consolidate": False},
                       analysis={"n_jobs": 1, "max_memory_gb": .1},
                       robustness={"steps": 3, "f_max": .5, "failure_runs": 3},
                       output={"dir": tmp_path / "output"})
    summary = run(config)
    curves = pd.read_csv(config.output.dir / "robustness_curves.csv")
    assert list(curves.columns) == list(CURVE_COLUMNS)
    assert len(curves) == 2 * 4 * 4
    assert set(curves.loc[curves["mode"] == "attack", "run"]) == {0}
    assert set(curves.loc[curves["mode"] == "failure", "run"]) == {1, 2, 3}
    for element in ("links", "nodes"):
        data = summary["metrics"]["robustness"][element]
        for key in ("auc_attack_S", "auc_attack_E", "auc_failure_S", "auc_failure_E"):
            assert 0 <= data[key] <= 1
        for step, entry in enumerate(data["failure_band"]):
            values = curves.loc[(curves.element == element) & (curves["mode"] == "failure") & (curves.step == step), "S_scc"]
            assert entry["S_scc_mean"] == pytest.approx(values.mean())
            assert entry["S_scc_p05"] == pytest.approx(values.quantile(.05))
            assert entry["S_scc_p95"] == pytest.approx(values.quantile(.95))
    text = (config.output.dir / "report.txt").read_text()
    assert "Robustness" in text and "links (headline)" in text and "Targeted removal of" in text
    assert text.isascii() and max(map(len, text.splitlines())) <= 100
    assert "estimated time remaining" in capsys.readouterr().err
    for filename in ("robustness_scc.png", "robustness_efficiency.png"):
        assert (config.output.dir / "figures" / filename).stat().st_size > 1000
    resolved = load_config(config.output.dir / "run_config.yaml")
    assert resolved.robustness == config.robustness
    resolved.robustness.removal = ["nodes"]
    resolved.output.figures = False
    run(resolved, overwrite=True)
    repeat = pd.read_csv(config.output.dir / "robustness_curves.csv")
    assert set(repeat.element) == {"nodes"}
    assert not (config.output.dir / "figures").exists()


def test_er_and_scale_free_generator(tmp_path):
    process = subprocess.run([sys.executable, "examples/create_ticket06_demo.py", "--nodes", "200", "--out", str(tmp_path)],
                             capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert (tmp_path / "models.png").stat().st_size > 1000
    for name in ("er", "scale-free"):
        graph = ox.load_graphml(tmp_path / f"{name}.graphml")
        assert len(graph) == 200 and nx.is_strongly_connected(graph)
        assert graph.graph["simplified"]
        assert all(data["length"] == 1000 for _, _, data in graph.edges(data=True))
        nodes = gpd.read_file(tmp_path / f"{name}-input.gpkg", layer="nodes")
        edges = gpd.read_file(tmp_path / f"{name}-input.gpkg", layer="edges")
        assert len(nodes) == 200 and len(edges) == 2 * manifest["graphs"][name]["link_count"]
    assert manifest["graphs"]["scale-free"]["link_count"] == 3 * (200 - 3)
    assert manifest["graphs"]["er"]["p"] == pytest.approx(6 / 199)
