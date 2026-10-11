from itertools import combinations
import json
import math

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pytest

from georesilience.accessibility import (AccessibilityReducer, accessibility_baseline,
    bridge_accessibility_loss, compute_accessibility, link_accessibility_loss)
from georesilience.config import AccessibilityConfig, CriticalityConfig, RunConfig, load_config
from georesilience.links import _link_rows
from georesilience.pipeline import run
from georesilience.removal import ActiveEdgeGraph, AffectedSourceRecompute
from georesilience.screening import screen_network


def roads(n, edges):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for node in range(n):
        graph.add_node(node, x=500000. + node * 100, y=1900000. + (node % 3) * 100)
    for way, (u, v, length, two_way) in enumerate(edges, 1):
        for a, b in ((u, v), (v, u)) if two_way else ((u, v),):
            graph.add_edge(a, b, length=float(length), osmid=way, highway="residential")
    return graph


def setup(graph, *, candidates=True, analytic_size=2000):
    links = _link_rows(graph)
    for row in links:
        row["edge_betweenness"] = 1
    screen = screen_network(graph, links, dict.fromkeys(graph, 0), CriticalityConfig(
        k_betweenness=len(links) if candidates else 0, k_detour=0,
        bridge_analytic_max_side=analytic_size))
    return links, screen


def compute(graph, settings=None, *, weights=None, candidates=True, analytic_size=2000, jobs=1, budget=2**20):
    links, screen = setup(graph, candidates=candidates, analytic_size=analytic_size)
    result = compute_accessibility(graph, links, screen, AccessibilityConfig(**(settings or {})),
                                   n_jobs=jobs, budget_bytes=budget, weights=weights)
    return result, links, screen


def naive(graph, links, settings, removed=(), weights=None):
    # Independent NetworkX routing, scalar exponential sum, and original node set.
    masses = dict(zip(graph, np.ones(len(graph)) if weights is None else weights))
    closed = {arc for row in links if row["link_id"] in removed for arc in row["_edges"]}
    view = nx.subgraph_view(graph, filter_edge=lambda u, v, key: (u, v, key) not in closed)
    radius = settings.half_distance_km * 1000 * settings.cutoff_factor
    beta = math.log(2) / (settings.half_distance_km * 1000)
    return np.array([sum(masses[dest] * math.exp(-beta * length) for dest, length in
                        nx.single_source_dijkstra_path_length(view, node, cutoff=radius, weight="length").items()
                        if dest != node) for node in graph])


def test_two_nodes_half_distance_and_unequal_destination_masses():
    graph = roads(2, [(0, 1, 1000, True)])
    result, links, _ = compute(graph, {"half_distance_km": 1})
    for node in graph:
        assert result.node_metrics[node]["hansen_a"] == .5
        assert result.node_metrics[node]["vuln"] == 1
        assert not result.node_metrics[node]["isolated_in_R"]
    assert result.link_metrics[links[0]["link_id"]]["access_drop"] == 1
    assert result.summary["counts_by_method"]["analytic_bridge"] == 1
    weighted, _, _ = compute(graph, {"half_distance_km": 1}, weights=[2, 3])
    assert weighted.node_metrics[0]["hansen_a"] == 1.5
    assert weighted.node_metrics[1]["hansen_a"] == 1
    assert weighted.summary["total_accessibility"] == 2.5  # No origin-mass multiplication.


def test_inclusive_cutoff_just_inside_outside_and_directed_outbound():
    graph = roads(4, [(0, 1, 1000, False), (0, 2, 999.999, False), (0, 3, 1000.001, False)])
    result, _, _ = compute(graph, {"half_distance_km": 1, "cutoff_factor": 1})
    assert result.node_metrics[0]["hansen_a"] == pytest.approx(.5 + 2 ** (-.999999))
    for node in (1, 2, 3):
        assert result.node_metrics[node]["hansen_a"] == 0
        assert result.node_metrics[node]["isolated_in_R"]
        assert math.isnan(result.node_metrics[node]["vuln"])
    assert result.summary["isolated_in_R_count"] == 3
    json.dumps(result.summary, allow_nan=False)


@pytest.mark.parametrize("seed", range(5))
def test_random_spatial_affected_sources_and_full_metrics(seed):
    rng = np.random.default_rng(seed)
    xy = rng.uniform(0, 1000, (9, 2))
    edges = [(i, i + 1, np.linalg.norm(xy[i] - xy[i + 1]) * rng.uniform(1, 1.3), True) for i in range(8)]
    for u, v in combinations(range(9), 2):
        if v != u + 1 and rng.random() < .25:
            edges.append((u, v, np.linalg.norm(xy[u] - xy[v]) * rng.uniform(1, 1.3), bool(rng.integers(2))))
    edges.extend([(0, 1, edges[0][2] * 1.4, False), (0, 0, 0, False)])
    graph = roads(9, edges)
    for node in graph:
        graph.nodes[node].update(x=float(xy[node, 0] + 500000), y=float(xy[node, 1] + 1900000))
    weights = rng.integers(0, 6, 9).astype(float)
    settings = AccessibilityConfig(half_distance_km=.3, cutoff_factor=3, all_links=True, k=2)
    result, links, _ = compute(graph, settings.model_dump(), weights=weights, budget=20000)
    baseline = naive(graph, links, settings, weights=weights)
    np.testing.assert_allclose([result.node_metrics[node]["hansen_a"] for node in graph], baseline, atol=1e-12)
    active = ActiveEdgeGraph(graph, links)
    recompute = AffectedSourceRecompute(active, n_jobs=1, budget_bytes=20000)
    reducer = AccessibilityReducer(weights, math.log(2) / 300, 900)
    all_relative = {}
    for row in links:
        key = row["link_id"]
        if row["is_self_loop"]:
            assert math.isnan(result.link_metrics[key]["access_drop"])
            continue
        after = naive(graph, links, settings, [key], weights)
        loss, _ = link_accessibility_loss(recompute, baseline, key, reducer)
        np.testing.assert_allclose(loss, baseline - after, rtol=0, atol=1e-9)
        assert result.link_metrics[key]["access_drop"] == pytest.approx((baseline - after).sum() / baseline.sum(), abs=1e-12)
        all_relative[key] = np.divide(baseline - after, baseline, out=np.zeros(9), where=baseline > 0)
    for index, node in enumerate(graph):
        if baseline[index] == 0:
            assert math.isnan(result.node_metrics[node]["vuln"])
            continue
        ordered = sorted(all_relative, key=lambda key: (-all_relative[key][index], key))
        assert result.node_metrics[node]["vuln"] == pytest.approx(all_relative[ordered[0]][index], abs=1e-12)
        chosen = result.top_links[node]
        assert len(chosen) == min(3, len(all_relative))
        # k=2 is exactly the specified three-pair search, not all M choose 2.
        pair_max = max((baseline[index] - naive(graph, links, settings, pair, weights)[index]) / baseline[index]
                       for pair in combinations(chosen, 2))
        assert result.node_metrics[node]["vuln_k2"] == pytest.approx(pair_max, abs=1e-12)
    json.dumps(result.summary, allow_nan=False)


@pytest.mark.parametrize("directed", [False, True])
def test_small_side_analytic_bridges_against_full_recomputation(directed):
    graph = roads(6, [(0, 1, 200, True), (1, 2, 300, not directed), (2, 3, 400, True),
                      (3, 4, 500, not directed), (4, 5, 600, True)])
    weights = np.array([2, 0, 3, 1, 7, 4.])
    settings = AccessibilityConfig(half_distance_km=.5, cutoff_factor=2, all_links=True)
    analytic, links, screen = compute(graph, settings.model_dump(), weights=weights, jobs=2, budget=12000)
    full, _, _ = compute(graph, settings.model_dump(), weights=weights, analytic_size=0)
    active = ActiveEdgeGraph(graph, links)
    recompute = AffectedSourceRecompute(active, n_jobs=2, budget_bytes=2000)
    reducer = AccessibilityReducer(weights, math.log(2) / 500, 1000)
    baseline = naive(graph, links, settings, weights=weights)
    for key in screen.analytic_bridges:
        actual, _ = bridge_accessibility_loss(recompute, key, reducer)
        expected = baseline - naive(graph, links, settings, [key], weights)
        np.testing.assert_allclose(actual, expected, atol=1e-9, rtol=0)
        assert analytic.link_metrics[key]["access_drop"] == pytest.approx(full.link_metrics[key]["access_drop"], abs=1e-12)


def test_pair_search_includes_zero_effect_links_and_matches_global_when_three_links():
    # Either route alone preserves the best outbound distance; jointly closing
    # the two equal routes causes a large loss. Zero single-link drops matter.
    graph = roads(2, [(0, 1, 1000, True), (0, 1, 1000, True), (0, 1, 4000, True)])
    result, links, _ = compute(graph, {"half_distance_km": 1, "k": 2, "all_links": True})
    for node in graph:
        assert result.node_metrics[node]["vuln"] == 0
        assert result.top_links[node] == [0, 1, 2]
        assert result.node_metrics[node]["vuln_k2"] == .875
        assert result.node_metrics[node]["vuln_k2_link_ids"] == "0;1"
    assert result.summary["k2_pair_trials"] == 6


def test_candidate_scope_empty_set_and_fewer_than_two_links():
    graph = roads(4, [(0, 1, 100, True), (1, 2, 100, True), (2, 3, 100, True), (3, 0, 100, True)])
    empty, _, _ = compute(graph, candidates=False)
    assert empty.summary["links_evaluated"] == 0
    assert all(math.isnan(row["vuln"]) and not row["isolated_in_R"] for row in empty.node_metrics.values())
    all_links, _, _ = compute(graph, {"all_links": True}, candidates=False)
    assert all_links.summary["links_evaluated"] == 4
    assert all(math.isfinite(row["vuln"]) for row in all_links.node_metrics.values())
    only, _, _ = compute(roads(2, [(0, 1, 1000, True)]), {"k": 2})
    assert math.isnan(only.node_metrics[0]["vuln_k2"])
    assert only.summary["k2_pair_trials"] == 0


def test_zero_masses_no_neighbours_and_singleton():
    for graph, settings, weights in [(roads(2, [(0, 1, 1000, True)]), {}, [0, 0]),
            (roads(2, [(0, 1, 1000, True)]), {"half_distance_km": .01}, None),
            (roads(1, [(0, 0, 0, False)]), {"k": 2}, None)]:
        result, _, _ = compute(graph, settings, weights=weights)
        assert result.summary["total_accessibility"] == 0
        assert result.summary["top20_links"] == []
        assert all(row["isolated_in_R"] and math.isnan(row["vuln"]) for row in result.node_metrics.values())
        json.dumps(result.summary, allow_nan=False)
    with pytest.raises(ValueError, match="node weights"):
        compute(roads(2, [(0, 1, 1000, True)]), weights=[-1, 1])
    with pytest.raises(ValueError, match="too small"):
        compute(roads(2, [(0, 1, 1000, True)]), budget=1)


@pytest.mark.parametrize("values", [{"half_distance_km": 0}, {"half_distance_km": -1},
    {"half_distance_km": math.nan}, {"half_distance_km": math.inf}, {"half_distance_km": 1e308},
    {"cutoff_factor": 0}, {"cutoff_factor": -1}, {"cutoff_factor": math.inf}, {"k": 3}])
def test_invalid_config(values):
    with pytest.raises(ValueError):
        AccessibilityConfig(**values)


def test_pipeline_outputs_figures_and_k2_overwrite(tmp_path):
    graph = roads(3, [(0, 1, 1000, True), (1, 2, 1000, True)])
    source = tmp_path / "input.graphml"
    ox.save_graphml(graph, filepath=source)
    config = RunConfig(input={"path": source}, cleaning={"consolidate": False},
        analysis={"n_jobs": 1, "max_memory_gb": .05, "directed_removal": False},
        robustness={"steps": 1, "failure_runs": 1}, reliability={"samples": 2, "p0_sweep": [0]},
        travel_time={"enabled": False}, accessibility={"half_distance_km": 1, "k": 2, "all_links": True},
        output={"dir": tmp_path / "out"})
    summary = run(config)
    nodes = gpd.read_file(config.output.dir / "network.gpkg", layer="nodes")
    edges = gpd.read_file(config.output.dir / "network.gpkg", layer="edges")
    assert {"hansen_a", "vuln", "vuln_link_id", "vuln_k2", "isolated_in_R", "vuln_k2_link_ids"} <= set(nodes.columns)
    assert {"access_drop", "access_rank"} <= set(edges.columns)
    assert sorted(nodes.hansen_a) == [.75, .75, 1]
    assert summary["metrics"]["accessibility"]["directed"]  # Independent of directed_removal.
    assert "Accessibility" in (config.output.dir / "report.txt").read_text()
    for name in ("hansen_a_map.png", "vuln_map.png", "access_drop_map.png"):
        assert (config.output.dir / "figures" / name).is_file()
    resolved = load_config(config.output.dir / "run_config.yaml")
    assert resolved.accessibility == config.accessibility
    config.accessibility.k = 1
    config.output.figures = False
    run(config, overwrite=True)
    nodes = gpd.read_file(config.output.dir / "network.gpkg", layer="nodes")
    assert "vuln_k2" not in nodes
    assert not (config.output.dir / "figures" / "vuln_map.png").exists()
