"""Directed physical-link closures, paired weighting views, and screening gaps."""

import math

import networkx as nx
import numpy as np
import pytest

from georesilience.metrics import compute_link_consequences
from tests.test_metric_baselines import independent_reference


CONSEQUENCES = ("efficiency_drop", "accessibility_drop", "disconnected_pair_fraction")


def road_graph(kind):
    graph = nx.MultiDiGraph(crs=32644, simplified=True)
    n = 2 if kind == "parallel" else 3
    for node in range(n):
        graph.add_node(node, x=500000 + 100 * node, y=1900000 + (node % 2) * 100)
    edges = [(0, 1, 100), (1, 2, 100)]
    if kind in {"cycle", "oneway"}:
        edges.append((2, 0, 100))
    elif kind == "parallel":
        edges = [(0, 1, 100), (0, 1, 300)]
    for way, (u, v, length) in enumerate(edges, 1):
        graph.add_edge(u, v, length=length, osmid=way)
        if kind != "oneway":
            graph.add_edge(v, u, length=length, osmid=way)
    return graph


def random_graph():
    graph = nx.MultiDiGraph(crs=32644, simplified=True)
    for node in range(8):
        graph.add_node(node, x=500000 + node * 100, y=1900000 + node % 3 * 100)
    random = np.random.default_rng(42)
    roads = [(node, (node + 1) % 8, True) for node in range(8)]
    roads.extend([(0, 3, False), (1, 5, True), (2, 6, False), (4, 7, True), (0, 1, True)])
    for way, (u, v, reciprocal) in enumerate(roads, 1):
        length = float(random.integers(50, 301))
        graph.add_edge(u, v, length=length, osmid=way)
        if reciprocal:
            graph.add_edge(v, u, length=length, osmid=way)
    return graph


def reference_closure(graph, link, population):
    closed = graph.copy()
    closed.remove_edges_from(link["_edges"])
    before = independent_reference(graph, population)
    after = independent_reference(closed, population)
    expected = {}
    for suffix in ("", "_pop"):
        for field in ("efficiency", "accessibility"):
            base, damaged = before[field + suffix], after[field + suffix]
            expected[field + "_drop" + suffix] = ((base - damaged) / base if base else None)
        base, damaged = before["reachable_fraction" + suffix], after["reachable_fraction" + suffix]
        expected["disconnected_pair_fraction" + suffix] = base - damaged if base is not None else None
    alternatives = []
    for u, v in {(u, v) for u, v, _ in link["_edges"]}:
        try:
            alternatives.append(nx.shortest_path_length(closed, u, v, weight="length"))
        except nx.NetworkXNoPath:
            alternatives.append(math.inf)
    detour = max(alternatives) / link["length_m"]
    expected["detour_ratio"] = detour if math.isfinite(detour) else None
    expected["detour_none"] = not math.isfinite(detour)
    return expected


@pytest.mark.parametrize("kind", ["path", "cycle", "oneway", "parallel", "random"])
def test_every_link_closure_matches_independent_directed_fixed_universe(kind):
    graph = random_graph() if kind == "random" else road_graph(kind)
    population = [1, 0, 2, 5, 0, 3, 7, 1] if kind == "random" else [2, 3, 5][:len(graph)]
    result = compute_link_consequences(graph, population, coverage="all", half_distance_km=.1)
    assert result.coverage["links"]["mode"] == "all"
    assert result.coverage["links"]["evaluated"] == result.coverage["links"]["total"] == len(result.links)
    assert len(result.coverage["links"]["ids"]) == len(result.links)
    for row in result.links:
        expected = reference_closure(graph, row, population)
        assert row["evaluated"] is True
        for field, value in expected.items():
            if value is None:
                assert row[field] is None, (kind, row["link_id"], field)
            elif isinstance(value, bool):
                assert bool(row[field]) == value
            else:
                assert row[field] == pytest.approx(value, rel=1e-11, abs=1e-13), (kind, row["link_id"], field)
        assert math.isfinite(row["edge_betweenness"])


def test_parallel_alternative_can_be_faster_than_the_closed_long_road():
    result = compute_link_consequences(road_graph("parallel"), [2, 7], coverage="all")
    by_length = {row["length_m"]: row for row in result.links}
    assert by_length[100]["detour_ratio"] == pytest.approx(3)
    assert by_length[300]["detour_ratio"] == pytest.approx(1 / 3)
    assert by_length[300]["efficiency_drop"] == 0
    assert all(not row["is_bridge"] and not row["detour_none"] for row in result.links)


def test_oneway_cycle_detects_directed_disconnection_without_undirected_bridges():
    result = compute_link_consequences(road_graph("oneway"), [2, 3, 5], coverage="all")
    assert all(not row["is_bridge"] for row in result.links)
    assert all(row["detour_none"] and row["detour_ratio"] is None for row in result.links)
    assert all(row["disconnected_pair_fraction"] > 0 for row in result.links)


def test_screened_ring_reports_uncomputed_consequences_as_null_with_reasons():
    result = compute_link_consequences(road_graph("cycle"), [2, 3, 5],
                                       coverage="screened", candidate_limit=0)
    coverage = result.coverage["links"]
    assert coverage["mode"] == "screened"
    assert coverage["evaluated"] == 0 and coverage["total"] == 3
    assert coverage["ids"] == [] and coverage["method"]
    for row in result.links:
        assert row["evaluated"] is False
        assert row["detour_ratio"] == pytest.approx(2)
        for field in CONSEQUENCES:
            for suffix in ("", "_pop"):
                assert row[field + suffix] is None
                assert row["null_reasons"][field + suffix]


def test_allzero_population_preserves_structural_consequences_and_explains_weighted_nulls():
    result = compute_link_consequences(road_graph("path"), [0, 0, 0], coverage="all")
    for row in result.links:
        for field in CONSEQUENCES:
            assert row[field] is not None
            assert row[field + "_pop"] is None
            assert row["null_reasons"][field + "_pop"]
    for row in result.nodes.values():
        assert row["hansen_accessibility"] is not None
        assert row["hansen_accessibility_pop"] is None


def test_redundancy_scores_distinguish_bridges_and_directed_no_alternative():
    path = compute_link_consequences(road_graph("path"), [2, 3, 5], coverage="all")
    cycle = compute_link_consequences(road_graph("cycle"), [2, 3, 5], coverage="all")
    oneway = compute_link_consequences(road_graph("oneway"), [2, 3, 5], coverage="all")
    assert all(row["is_bridge"] for row in path.links)
    assert path.nodes[1]["is_articulation"] is True
    assert not any(row["is_articulation"] for row in cycle.nodes.values())
    assert path.redundancy["bridge_redundancy"]["value"] == 0
    assert cycle.redundancy["bridge_redundancy"]["value"] == 1
    assert oneway.redundancy["bridge_redundancy"]["value"] == 1
    assert path.redundancy["detour_redundancy"]["value"] is None
    assert path.redundancy["detour_redundancy"]["reason"]
    assert cycle.redundancy["detour_redundancy"]["value"] == pytest.approx(2)
    assert path.redundancy["detour_no_alternative_share"]["value"] == 1
    assert cycle.redundancy["detour_no_alternative_share"]["value"] == 0
    assert oneway.redundancy["detour_no_alternative_share"]["value"] == 1
