import json
import math

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pytest

from georesilience.config import CriticalityConfig, RunConfig, load_config
from georesilience.links import _link_rows
from georesilience.pipeline import run
from georesilience.screening import screen_network


def road_graph(simple):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for i, node in enumerate(simple):
        pos = simple.nodes[node].get("pos", (i, i % 3))
        graph.add_node(node, x=500000 + 100 * pos[0], y=1900000 + 100 * pos[1])
    for way, (u, v, data) in enumerate(simple.edges(data=True), start=1):
        for a, b in ((u, v), (v, u)):
            graph.add_edge(a, b, length=data.get("length", 1.0), osmid=way,
                           name=f"Road {way}", highway="residential")
    return graph


def screen(graph, config=None, jobs=1):
    links = _link_rows(graph)
    for row in links:
        row["edge_betweenness"] = float(row["link_id"] + 1)
    values = {node: float(i) for i, node in enumerate(graph)}
    return links, screen_network(graph, links, values, config or CriticalityConfig(), jobs)


def test_tree_cut_sizes_and_articulations():
    links, result = screen(road_graph(nx.path_graph(6)))
    for row in links:
        metrics = result.link_metrics[row["link_id"]]
        u = min(row["_u"], row["_v"])
        assert metrics["is_bridge"]
        assert metrics["cut_side_nodes"] == min(u + 1, 5 - u)
        assert metrics["cut_side_frac"] == pytest.approx(min(u + 1, 5 - u) / 6)
        assert math.isnan(metrics["detour_ratio"]) and metrics["detour_none"]
        assert not metrics["is_directed_bridge"]
    assert [result.node_metrics[i]["artic_max_cut"] for i in range(6)] == [0, 1, 2, 2, 1, 0]
    assert result.summary["bridge_frac"] == result.summary["bridge_length_frac"] == 1
    assert result.summary["detour_ratio"] == {"median": None, "p90": None, "p99": None}
    assert len(result.analytic_bridges) == 5 and not result.candidate_links
    _, star = screen(road_graph(nx.star_graph(4)))
    assert star.node_metrics[0]["artic_max_cut"] == 3


def test_ring_two_way_and_one_way_orientation():
    graph = road_graph(nx.cycle_graph(6))
    links, result = screen(graph)
    assert result.summary["bridge_count"] == result.summary["articulation_count"] == 0
    assert all(values["detour_ratio"] == 5 for values in result.link_metrics.values())
    graph.remove_edge(1, 0)
    links, result = screen(graph)
    assert result.summary["directed_bridge_count"] == 5
    for row in links:
        values = result.link_metrics[row["link_id"]]
        if {row["_u"], row["_v"]} == {0, 1}:
            assert row["oneway"] and not values["is_directed_bridge"]
            assert values["detour_ratio"] == 5
        else:
            assert values["is_directed_bridge"] and values["detour_none"]
    # Reverse the one-way segment: compute its existing direction, not stored endpoint order.
    graph.add_edge(1, 0, length=1, osmid=1)
    graph.remove_edge(0, 1)
    links, result = screen(graph)
    assert result.summary["directed_bridge_count"] == 5
    one_way = next(row for row in links if row["oneway"])
    assert result.link_metrics[one_way["link_id"]]["detour_ratio"] == 5


def test_parallel_links_and_self_loops():
    graph = road_graph(nx.path_graph(2))
    for u, v in ((0, 1), (1, 0)):
        graph.add_edge(u, v, length=1.5, osmid=99)
    graph.add_edge(0, 0, length=0, osmid=100)
    links, result = screen(graph)
    by_way = {row["osm_way_ids"]: result.link_metrics[row["link_id"]] for row in links}
    assert not any(row["is_bridge"] for row in by_way.values())
    assert by_way["1"]["detour_ratio"] == 1.5
    assert by_way["99"]["detour_ratio"] == pytest.approx(2 / 3)
    loop = by_way["100"]
    assert all(math.isnan(loop[key]) for key in ("cut_side_nodes", "cut_side_frac", "detour_ratio"))
    assert not loop["detour_none"] and not loop["is_criticality_candidate"]
    assert loop["candidate_reason"] == ""
    assert result.summary["non_self_loop_link_count"] == 2


@pytest.mark.parametrize("seed", range(5))
def test_random_spatial_reference_removals(seed):
    simple = nx.random_geometric_graph(200, 0.18, seed=seed)
    assert nx.is_connected(simple)
    # Include guaranteed bridges and articulation points in the spatial fixture.
    for i in range(200, 205):
        simple.add_node(i, pos=(1 + (i - 199) * 0.1, 1))
        simple.add_edge(0 if i == 200 else i - 1, i)
    rng = np.random.default_rng(seed)
    for u, v in simple.edges:
        simple[u][v]["length"] = math.dist(simple.nodes[u]["pos"], simple.nodes[v]["pos"]) * rng.uniform(1, 1.3)
    graph = road_graph(simple)
    for u, v, key in list(graph.edges(keys=True)):
        if u < v and rng.random() < 0.3:
            graph.remove_edge(v, u, key)
    for u, v in ((0, 1), (1, 0)):
        graph.add_edge(u, v, length=2.0, osmid=99999)
    links, result = screen(graph)
    for row in links:
        copy = graph.copy()
        copy.remove_edges_from(row["_edges"])
        components = list(nx.connected_components(copy.to_undirected()))
        values = result.link_metrics[row["link_id"]]
        assert values["is_bridge"] == (len(components) > 1)
        assert values["cut_side_nodes"] == (min(map(len, components)) if len(components) > 1 else 0)
        distances = []
        for u, v in set((u, v) for u, v, _ in row["_edges"]):
            try:
                distances.append(nx.dijkstra_path_length(copy, u, v, weight="length"))
            except nx.NetworkXNoPath:
                distances.append(math.inf)
        expected = max(distances) / row["length_m"]
        if math.isinf(expected):
            assert values["detour_none"] and math.isnan(values["detour_ratio"])
        else:
            assert not values["detour_none"]
            assert values["detour_ratio"] == pytest.approx(expected, abs=1e-12)
        assert values["is_directed_bridge"] == (math.isinf(expected) and len(components) == 1)
    for node, values in result.node_metrics.items():
        copy = simple.copy()
        copy.add_edge(0, 1)
        copy.remove_node(node)
        sizes = [len(component) for component in nx.connected_components(copy)]
        assert values["is_articulation"] == (len(sizes) > 1)
        assert values["artic_max_cut"] == len(simple) - 1 - max(sizes)


def test_candidate_arithmetic_ties_thresholds_and_all_mode():
    graph = road_graph(nx.cycle_graph(6))
    links = _link_rows(graph)
    # Detours rank short roads first, betweenness ranks long roads first.
    for row in links:
        length = row["link_id"] + 1
        for u, v, key in row["_edges"]:
            graph[u][v][key]["length"] = length
    config = CriticalityConfig(k_betweenness=2, k_detour=2, k_nodes=2, exact_info_max_nodes=0)
    links, result = screen(graph, config)
    assert result.candidate_links == {0, 1, 4, 5}
    assert result.candidate_nodes == {4, 5}
    assert result.summary["candidate_counts_by_reason"] == {
        "betweenness": 2, "detour": 2, "directed_bridge": 0, "large_bridge": 0, "analytic_bridge": 0}
    config.all = True
    _, all_result = screen(graph, config)
    assert all_result.candidate_links == set(range(6)) and all_result.candidate_nodes == set(graph)
    assert all_result.link_metrics[2]["candidate_reason"] == ""
    assert all_result.link_metrics[2]["is_criticality_candidate"]
    config.all = False
    values = dict.fromkeys(graph, 0)
    for row in links:
        row["edge_betweenness"] = 0
    first = screen_network(graph, links, values, config)
    second = screen_network(graph, list(reversed(links)), values, config)
    assert first.candidate_links == second.candidate_links
    assert first.candidate_nodes == second.candidate_nodes == {0, 1}

    config = CriticalityConfig(bridge_analytic_max_side=2, k_betweenness=0, k_detour=0)
    links, result = screen(road_graph(nx.path_graph(6)), config)
    assert len(result.candidate_links) == 1 and len(result.analytic_bridges) == 4
    large = next(iter(result.candidate_links))
    assert result.link_metrics[large]["cut_side_nodes"] == 3
    assert result.link_metrics[large]["candidate_reason"] == "large_bridge"
    config.all = True
    _, result = screen(road_graph(nx.path_graph(6)), config)
    assert len(result.candidate_links) == 1  # Analytic bridges stay out of full recomputation.
    config = CriticalityConfig(k_nodes=3, exact_info_max_nodes=0)
    graph = road_graph(nx.path_graph(80))
    links = _link_rows(graph)
    for row in links:
        row["edge_betweenness"] = 0
    result = screen_network(graph, links, dict.fromkeys(graph, 0), config)
    assert result.candidate_nodes == set(range(15, 65)) | {0, 1, 2}


def test_parallel_detours_and_reused_pool():
    config = CriticalityConfig()
    for size in (6, 9):
        graph = road_graph(nx.cycle_graph(size))
        graph.remove_edge(1, 0)
        links, serial = screen(graph, config)
        _, parallel = screen(graph, config, jobs=2)
        assert parallel.summary == serial.summary
        for row in links:
            key = row["link_id"]
            a, b = serial.link_metrics[key], parallel.link_metrics[key]
            assert a["detour_none"] == b["detour_none"]
            if not a["detour_none"]:
                assert a["detour_ratio"] == b["detour_ratio"]
        assert parallel.candidate_links == serial.candidate_links


def test_outputs_round_trip_and_config_validation(tmp_path):
    graph = road_graph(nx.cycle_graph(6))
    graph.remove_edge(1, 0)
    graph.add_node(6, x=500600, y=1900000)
    for u, v in ((5, 6), (6, 5)):
        graph.add_edge(u, v, length=100, osmid=99, name="Tail", highway="residential")
    graph.add_edge(0, 0, length=0, osmid=100)
    source = tmp_path / "input.graphml"
    ox.save_graphml(graph, source)
    config = RunConfig(input={"path": source}, cleaning={"consolidate": False},
                       analysis={"n_jobs": 1, "max_memory_gb": 0.1},
                       criticality={"bridge_analytic_max_side": 0}, output={"dir": tmp_path / "output"})
    summary = run(config)
    edges = gpd.read_file(config.output.dir / "network.gpkg", layer="edges")
    nodes = gpd.read_file(config.output.dir / "network.gpkg", layer="nodes")
    required = {"is_bridge", "cut_side_nodes", "cut_side_frac", "detour_ratio", "detour_none",
                "is_directed_bridge", "candidate_reason", "is_criticality_candidate", "is_analytic_bridge"}
    assert required <= set(edges.columns)
    assert {"is_articulation", "artic_max_cut", "is_info_candidate"} <= set(nodes.columns)
    assert edges.is_bridge.sum() == 1 and edges.is_directed_bridge.sum() == 5
    assert edges.loc[edges.detour_none, "detour_ratio"].isna().all()
    assert edges.loc[edges.is_self_loop, "cut_side_nodes"].isna().all()
    assert edges.loc[edges.is_bridge, "candidate_reason"].item() == "large_bridge"
    assert nodes.loc[nodes.node_id == "5", "artic_max_cut"].item() == 1
    text = (config.output.dir / "report.txt").read_text()
    assert all(label in text for label in ("Redundancy", "Top 20 bridges", "Top 20 non-bridges", "Tail"))
    assert text.isascii() and max(map(len, text.splitlines())) <= 100
    assert (config.output.dir / "figures" / "redundancy_map.png").stat().st_size > 1000
    stored = json.loads((config.output.dir / "summary.json").read_text())
    assert stored["metrics"]["redundancy"] == summary["metrics"]["redundancy"]
    assert "NaN" not in json.dumps(stored) and "Infinity" not in json.dumps(stored)
    resolved = load_config(config.output.dir / "run_config.yaml")
    assert resolved.criticality == config.criticality
    for name in ("k_betweenness", "k_detour", "k_nodes", "exact_info_max_nodes", "bridge_analytic_max_side"):
        with pytest.raises(ValueError):
            CriticalityConfig(**{name: -1})
