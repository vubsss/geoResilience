import json
import math
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pytest
from scipy.sparse.csgraph import dijkstra

from georesilience.config import CriticalityConfig, RunConfig
from georesilience.criticality import compute_criticality, information_centrality
from georesilience.figures import FIGURE_FILENAMES
from georesilience.links import _link_rows
from georesilience.pipeline import run
from georesilience.removal import (ActiveEdgeGraph, AffectedSourceRecompute, BaselineDistances,
                                   analytic_bridge_damage, full_link_damage)
from georesilience.screening import screen_network


def road_graph(simple, scale=1):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for i, node in enumerate(simple):
        graph.add_node(node, x=500000 + 100 * i, y=1900000 + 100 * (i % 3))
    for way, (u, v, data) in enumerate(simple.edges(data=True), start=1):
        for a, b in ((u, v), (v, u)):
            graph.add_edge(a, b, length=data.get("length", scale), osmid=way,
                           name=f"Road {way}", highway="residential")
    return graph


def setup(graph, config=None):
    links = _link_rows(graph)
    for row in links:
        row["edge_betweenness"] = 1.0
    screening = screen_network(graph, links, dict.fromkeys(graph, 0), config or CriticalityConfig())
    for row in links:
        row.update(screening.link_metrics[row["link_id"]])
    return links, screening


def assert_damage(actual, expected, tol=1e-9):
    for key, value in expected.items():
        if math.isnan(value):
            assert math.isnan(actual[key]), key
        else:
            assert actual[key] == pytest.approx(value, abs=tol), key


def reference_csr(graph, nodes):
    simple = nx.DiGraph()
    simple.add_nodes_from(nodes)
    for u, v, data in graph.edges(data=True):
        if u != v and (not simple.has_edge(u, v) or data["length"] < simple[u][v]["length"]):
            simple.add_edge(u, v, length=data["length"])
    return nx.to_scipy_sparse_array(simple, nodelist=nodes, weight="length", format="csr")


def reference_damage(before, after, weights=None):
    n = len(before)
    weights = np.ones(n) if weights is None else np.asarray(weights)
    pairs = weights[:, None] * weights[None, :]
    np.fill_diagonal(pairs, 0)
    reachable = np.isfinite(before) & (before > 0)
    remain = np.isfinite(after) & (after > 0)
    inv = np.divide(1, before, out=np.zeros_like(before), where=reachable)
    changed_inv = np.divide(1, after, out=np.zeros_like(after), where=remain)
    longer = reachable & remain & (after > before)
    extra = (after[longer] - before[longer]).sum()
    count = int(longer.sum())
    return {"eff_drop": (np.sum(inv * pairs) - np.sum(changed_inv * pairs)) / np.sum(inv * pairs),
            "disc_pair_frac": np.sum(pairs[reachable & ~remain]) / pairs.sum(),
            "extra_km_total": extra / 1000, "affected_pairs": count,
            "extra_m_mean_affected": extra / count if count else math.nan}


def test_known_ring_path_star_and_deterministic_ranks():
    graph = road_graph(nx.cycle_graph(4))
    links, screened = setup(graph)
    result = compute_criticality(graph, links, screened, n_jobs=1, budget_bytes=1024**2)
    for row in links:
        assert_damage(result.link_metrics[row["link_id"]], {
            "eff_drop": 2 / 15, "disc_pair_frac": 0, "extra_km_total": 0.004,
            "affected_pairs": 2, "extra_m_mean_affected": 2})
    assert [result.link_metrics[i]["crit_rank"] for i in range(4)] == [1, 2, 3, 4]
    np.testing.assert_allclose(list(result.information.values()), 0.5, atol=1e-15)
    assert result.summary["counts_by_method"] == {"full": 4, "analytic": 0}
    assert result.information_summary["coverage"] == "all"
    graph = road_graph(nx.path_graph(4))
    links, screened = setup(graph)
    result = compute_criticality(graph, links, screened, n_jobs=1, budget_bytes=1024**2)
    middle = next(row["link_id"] for row in links if {row["_u"], row["_v"]} == {1, 2})
    assert_damage(result.link_metrics[middle], {
        "eff_drop": 7 / 13, "disc_pair_frac": 2 * 2 * 2 / (4 * 3), "extra_km_total": 0,
        "affected_pairs": 0, "extra_m_mean_affected": math.nan})
    assert result.link_metrics[middle]["damage_method"] == "analytic"
    assert result.link_metrics[middle]["crit_rank"] == 1
    links, full_screened = setup(graph, CriticalityConfig(bridge_analytic_max_side=0))
    full_result = compute_criticality(graph, links, full_screened, n_jobs=1, budget_bytes=1024**2)
    assert full_result.link_metrics[middle]["damage_method"] == "full"
    assert_damage(full_result.link_metrics[middle], {key: result.link_metrics[middle][key] for key in (
        "eff_drop", "disc_pair_frac", "extra_km_total", "affected_pairs", "extra_m_mean_affected")})
    graph = road_graph(nx.star_graph(4))
    links, screened = setup(graph)
    result = compute_criticality(graph, links, screened, n_jobs=1, budget_bytes=1024**2)
    assert result.information[0] == 1
    np.testing.assert_allclose([result.information[i] for i in range(1, 5)], 5 / 14, atol=1e-15)


def test_active_edge_masks_parallel_replacement_oneway_and_self_loop():
    graph = road_graph(nx.path_graph(2), scale=100)
    for u, v in ((0, 1), (1, 0)):
        graph.add_edge(u, v, length=150, osmid=99)
    graph.add_edge(0, 0, length=0, osmid=100)
    links, screened = setup(graph)
    active = ActiveEdgeGraph(graph, links)
    primary = next(row["link_id"] for row in links if row["osm_way_ids"] == "1")
    backup = next(row["link_id"] for row in links if row["osm_way_ids"] == "99")
    assert active.csr()[0, 1] == 100
    assert active.csr([primary])[0, 1] == 150
    assert active.csr([backup])[0, 1] == 100
    assert active.csr([primary, backup]).nnz == 0
    result = compute_criticality(graph, links, screened, n_jobs=1, budget_bytes=1024**2)
    assert_damage(result.link_metrics[primary], {
        "eff_drop": 1 / 3, "disc_pair_frac": 0, "extra_km_total": 0.1,
        "affected_pairs": 2, "extra_m_mean_affected": 50})
    assert result.link_metrics[backup]["eff_drop"] == 0
    assert result.link_metrics[backup]["affected_pairs"] == 0
    loop = next(row["link_id"] for row in links if row["is_self_loop"])
    assert math.isnan(result.link_metrics[loop]["eff_drop"])
    assert result.link_metrics[loop]["damage_method"] is None
    assert math.isnan(result.link_metrics[loop]["crit_rank"])
    graph.remove_edge(1, 0, 0)
    active = ActiveEdgeGraph(graph, _link_rows(graph))
    assert active.csr()[0, 1] == 100 and active.csr()[1, 0] == 150
    undirected = ActiveEdgeGraph(graph, _link_rows(graph), directed=False)
    assert undirected.csr()[0, 1] == undirected.csr()[1, 0] == 100


def test_cache_stream_chunks_jobs_and_cleanup():
    graph = road_graph(nx.cycle_graph(6), scale=100)
    graph.remove_edge(1, 0)
    links, screened = setup(graph)
    baseline = compute_criticality(graph, links, screened, n_jobs=1, budget_bytes=1024**2)
    assert baseline.computation["criticality_baseline"] == "cached"
    for cache, jobs, budget in ((False, 1, 128), (True, 2, 1024**2), (False, 2, 256), (None, 1, 128)):
        result = compute_criticality(graph, links, screened, n_jobs=jobs, budget_bytes=budget, cache=cache)
        for row in links:
            key = row["link_id"]
            assert_damage(result.link_metrics[key], {k: baseline.link_metrics[key][k] for k in (
                "eff_drop", "disc_pair_frac", "extra_km_total", "affected_pairs", "extra_m_mean_affected")})
        np.testing.assert_allclose(list(result.information.values()), list(baseline.information.values()), atol=1e-12)
        assert [row["link_id"] for row in result.summary["top_20"]] == [row["link_id"] for row in baseline.summary["top_20"]]
        if budget < 1024:
            assert result.computation["criticality_baseline"] == "recomputed"
    active = ActiveEdgeGraph(graph, links)
    with BaselineDistances(active.csr(), n_jobs=1, budget_bytes=1024**2) as distances:
        folder = Path(distances._folder.name)
        assert folder.exists()
    assert not folder.exists()


def test_weighted_damage_information_and_invalid_weights():
    graph = road_graph(nx.path_graph(3))
    links, screened = setup(graph)
    weights = np.array([1.0, 2.0, 3.0])
    active = ActiveEdgeGraph(graph, links)
    recompute = AffectedSourceRecompute(active, n_jobs=1, budget_bytes=1024**2)
    with BaselineDistances(recompute.graph, n_jobs=1, budget_bytes=1024**2, weights=weights) as baseline:
        recompute.budget_bytes = baseline.working_budget_bytes
        full, _ = full_link_damage(recompute, baseline, 0)
        analytic = analytic_bridge_damage(recompute, baseline, 0)
        assert full["eff_drop"] == pytest.approx(7 / 19)
        assert full["disc_pair_frac"] == pytest.approx(5 / 11)
        assert_damage(analytic, full)
    result = compute_criticality(graph, links, screened, n_jobs=1, budget_bytes=1024**2, weights=weights)
    before = dijkstra(reference_csr(graph, list(graph)), directed=True)
    for node in graph:
        copy = graph.copy()
        copy.remove_edges_from(list(copy.in_edges(node, keys=True)) + list(copy.out_edges(node, keys=True)))
        after = dijkstra(reference_csr(copy, list(graph)), directed=True)
        assert result.information[node] == pytest.approx(reference_damage(before, after, weights)["eff_drop"])
    for weights in ([1], [-1, 1, 1], [1, math.nan, 1], [1, math.inf, 1]):
        with pytest.raises(ValueError, match="node weights"):
            BaselineDistances(active.csr(), n_jobs=1, budget_bytes=1024**2, weights=weights)
    singleton = road_graph(nx.empty_graph(1))
    links, screened = setup(singleton)
    result = compute_criticality(singleton, links, screened, n_jobs=1, budget_bytes=1024)
    assert math.isnan(result.information[0]) and result.information_summary["coverage"] == "all"


def test_streaming_weighted_bridges_and_undirected_removal():
    graph = road_graph(nx.path_graph(3))
    links, _ = setup(graph)
    active = ActiveEdgeGraph(graph, links)
    recompute = AffectedSourceRecompute(active, n_jobs=1, budget_bytes=128)
    with BaselineDistances(recompute.graph, n_jobs=1, budget_bytes=128, weights=[1, 2, 3]) as baseline:
        assert baseline.cache is None
        full, _ = full_link_damage(recompute, baseline, 0)
        assert_damage(analytic_bridge_damage(recompute, baseline, 0), full)
        assert full["eff_drop"] == pytest.approx(7 / 19)
    links, screened = setup(graph)
    zero = compute_criticality(graph, links, screened, n_jobs=1, budget_bytes=1024, weights=[0, 0, 0])
    assert all(math.isnan(row["eff_drop"]) and math.isnan(row["crit_rank"]) for row in zero.link_metrics.values())
    assert not zero.summary["top_20"]
    graph = road_graph(nx.cycle_graph(4))
    graph.remove_edge(1, 0)
    links, screened = setup(graph)
    result = compute_criticality(graph, links, screened, n_jobs=1, budget_bytes=1024**2, directed=False)
    assert result.summary["graph"] == "undirected"
    assert result.summary["baseline_efficiency"] == pytest.approx(5 / 6)
    assert all(row["eff_drop"] == pytest.approx(2 / 15) for row in result.link_metrics.values())


def spatial_fixture(seed):
    rng = np.random.default_rng(seed)
    simple = nx.random_geometric_graph(195, 0.105, seed=seed)
    components = list(nx.connected_components(simple))
    for left, right in zip(components, components[1:]):
        pair = min(((u, v) for u in left for v in right),
                   key=lambda pair: math.dist(simple.nodes[pair[0]]["pos"], simple.nodes[pair[1]]["pos"]))
        simple.add_edge(*pair)
    for node in range(195, 200):
        simple.add_node(node, pos=(1 + (node - 194) * 0.1, 1))
        simple.add_edge(0 if node == 195 else node - 1, node)
    for u, v in simple.edges:
        simple[u][v]["length"] = 1000 * math.dist(simple.nodes[u]["pos"], simple.nodes[v]["pos"]) * rng.uniform(1, 1.3)
    backbone = {frozenset(edge) for edge in nx.minimum_spanning_tree(simple, weight="length").edges}
    graph = road_graph(simple)
    for u, v in simple.edges:
        if frozenset((u, v)) not in backbone and rng.random() < 0.5:
            graph.remove_edge(v, u)
    assert nx.is_strongly_connected(graph)
    # Include a slower parallel road to exercise post-removal minimum rebuilding.
    u, v = next(iter(simple.edges))
    for a, b in ((u, v), (v, u)):
        graph.add_edge(a, b, length=2 * simple[u][v]["length"], osmid=99999)
    return graph


@pytest.mark.parametrize("seed", [11, 42])
def test_random_200_nodes_every_link_against_full_recompute(seed):
    graph = spatial_fixture(seed)
    links, screened = setup(graph)
    active = ActiveEdgeGraph(graph, links)
    nodes = list(graph)
    before = dijkstra(reference_csr(graph, nodes), directed=True)
    recompute = AffectedSourceRecompute(active, n_jobs=1, budget_bytes=1024**2)
    with BaselineDistances(recompute.graph, n_jobs=1, budget_bytes=1024**2) as baseline:
        recompute.budget_bytes = baseline.working_budget_bytes
        for row in links:
            link_id = row["link_id"]
            copy = graph.copy()
            copy.remove_edges_from(row["_edges"])
            after = dijkstra(reference_csr(copy, nodes), directed=True)
            expected = reference_damage(before, after)
            full, _ = full_link_damage(recompute, baseline, link_id)
            assert_damage(full, expected)
            if link_id in screened.analytic_bridges:
                assert_damage(analytic_bridge_damage(recompute, baseline, link_id), expected)
        # Check every node independently using NetworkX distance dictionaries.
        undirected = nx.Graph()
        undirected.add_nodes_from(nodes)
        for row in links:
            u, v, length = row["_u"], row["_v"], row["length_m"]
            if not undirected.has_edge(u, v) or undirected[u][v]["length"] > length:
                undirected.add_edge(u, v, length=length)
        inv = sum(1 / distance for source, lengths in nx.all_pairs_dijkstra_path_length(undirected, weight="length")
                  for target, distance in lengths.items() if source != target)
        result, summary = information_centrality(ActiveEdgeGraph(graph, links, directed=False), set(nodes),
                                                n_jobs=1, budget_bytes=1024**2)
        assert summary["coverage"] == "all"
        for node in nodes:
            copy = undirected.copy()
            copy.remove_edges_from(list(copy.edges(node)))
            changed = sum(1 / distance for source, lengths in nx.all_pairs_dijkstra_path_length(copy, weight="length")
                          for target, distance in lengths.items() if source != target)
            assert result[node] == pytest.approx((inv - changed) / inv, abs=1e-9)


def test_partial_candidates_outputs_and_no_figures_overwrite(tmp_path, capsys):
    graph = road_graph(nx.cycle_graph(6), scale=100)
    graph.add_edge(0, 0, length=0, osmid=99)
    source = tmp_path / "ring.graphml"
    ox.save_graphml(graph, source)
    config = RunConfig(input={"path": source}, cleaning={"consolidate": False},
                       analysis={"n_jobs": 1, "max_memory_gb": 0.1},
                       criticality={"k_betweenness": 1, "k_detour": 0, "k_nodes": 1, "exact_info_max_nodes": 0},
                       output={"dir": tmp_path / "output"})
    summary = run(config)
    output = config.output.dir
    edges = gpd.read_file(output / "network.gpkg", layer="edges")
    nodes = gpd.read_file(output / "network.gpkg", layer="nodes")
    assert {"eff_drop", "disc_pair_frac", "extra_km_total", "affected_pairs", "extra_m_mean_affected",
            "damage_method", "crit_rank"} <= set(edges.columns)
    assert edges.eff_drop.notna().sum() == edges.crit_rank.notna().sum() == 1
    assert edges.loc[edges.is_criticality_candidate, "damage_method"].item() == "full"
    assert edges.loc[~edges.is_criticality_candidate, "damage_method"].isna().all()
    assert nodes.information.notna().sum() == 1
    assert summary["metrics"]["information"]["coverage"] == "candidates"
    assert summary["metrics"]["criticality"]["evaluated_link_count"] == 1
    stored = (output / "summary.json").read_text()
    assert "NaN" not in stored and "Infinity" not in stored
    assert json.loads(stored)["metrics"]["criticality"] == summary["metrics"]["criticality"]
    text = (output / "report.txt").read_text()
    assert all(label in text for label in ("Critical links", "Information centrality", "candidate_reason", "mean(1/d)"))
    assert text.isascii() and max(map(len, text.splitlines())) <= 100
    assert (output / "figures" / "critical_links_map.png").stat().st_size > 1000
    logs = capsys.readouterr().err
    assert "Link damage: 1/1" in logs and "estimated time remaining" in logs
    config.output.figures = False
    run(config, overwrite=True)
    assert not any((output / "figures" / name).exists() for name in FIGURE_FILENAMES)
