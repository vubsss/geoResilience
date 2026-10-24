"""Original-universe, directed single-node isolation consequences."""

import networkx as nx
import pytest

from georesilience.metrics import add_node_consequences, compute_link_consequences, compute_local_metrics
from tests.test_link_consequences import random_graph, road_graph
from tests.test_metric_baselines import independent_reference


NODE_CONSEQUENCES = ("information_centrality", "accessibility_drop", "disconnected_pair_fraction")


def reference_node_isolation(graph, node, population, half_distance_km=.1):
    isolated = graph.copy()
    isolated.remove_edges_from(set(graph.in_edges(node, keys=True)) | set(graph.out_edges(node, keys=True)))
    before = independent_reference(graph, population, half_distance_km=half_distance_km)
    after = independent_reference(isolated, population, half_distance_km=half_distance_km)
    metrics = {}
    for suffix in ("", "_pop"):
        for output, aggregate in (("information_centrality", "efficiency"),
                                  ("accessibility_drop", "accessibility")):
            base, damaged = before[aggregate + suffix], after[aggregate + suffix]
            metrics[output + suffix] = (base - damaged) / base if base else None
        base, damaged = before["reachable_fraction" + suffix], after["reachable_fraction" + suffix]
        metrics["disconnected_pair_fraction" + suffix] = base - damaged if base is not None else None
    return metrics


def test_path_hand_computed_information_disconnection_and_hansen_losses():
    graph = road_graph("path")
    for _, _, _, data in graph.edges(keys=True, data=True):
        data["length"] = 1
    result = compute_local_metrics(graph, [1, 2, 3], coverage="all", half_distance_km=.001)
    leaf = result.nodes[0]
    assert leaf["information_centrality"] == pytest.approx(3 / 5)
    assert leaf["disconnected_pair_fraction"] == pytest.approx(2 / 3)
    assert leaf["information_centrality_pop"] == pytest.approx(7 / 19)
    assert leaf["disconnected_pair_fraction_pop"] == pytest.approx(5 / 11)
    # Structural H=5/12; surviving 1<->2 pair contributes H=1/6.
    assert leaf["accessibility_drop"] == pytest.approx(3 / 5)
    # Destination denominators remain [5,4,3], and origin weights remain [1,2,3]/6.
    assert leaf["accessibility_drop_pop"] == pytest.approx(17 / 52)
    center = result.nodes[1]
    for field in NODE_CONSEQUENCES:
        assert center[field] == 1
        assert center[field + "_pop"] == 1
    assert leaf["is_articulation"] is False and center["is_articulation"] is True


@pytest.mark.parametrize("kind", ["path", "cycle", "oneway", "parallel", "random"])
def test_every_node_matches_independent_directed_isolation_in_original_universe(kind):
    graph = random_graph() if kind == "random" else road_graph(kind)
    population = [1, 0, 2, 5, 0, 3, 7, 1] if kind == "random" else [2, 3, 5][:len(graph)]
    result = compute_local_metrics(graph, population, coverage="all", half_distance_km=.1)
    coverage = result.coverage["nodes"]
    assert coverage["mode"] == "all"
    assert coverage["evaluated"] == coverage["total"] == len(graph)
    assert len(coverage["ids"]) == len(graph)
    assert len(result.baseline.universe.population) == len(graph)
    for node, metrics in result.nodes.items():
        assert metrics["evaluated"] is True
        for field, expected in reference_node_isolation(graph, node, population).items():
            if expected is None:
                assert metrics[field] is None
            else:
                assert metrics[field] == pytest.approx(expected, rel=1e-11, abs=1e-13), (kind, node, field)
        assert "efficiency_drop" not in metrics
        assert "efficiency_drop_pop" not in metrics


def test_non_articulation_node_can_still_cause_directed_information_loss():
    graph = road_graph("oneway")
    result = compute_local_metrics(graph, [2, 3, 5], coverage="all", half_distance_km=.1)
    assert all(not row["is_articulation"] for row in result.nodes.values())
    assert all(row["information_centrality"] > 0 for row in result.nodes.values())
    assert all(row["disconnected_pair_fraction"] > 0 for row in result.nodes.values())
    undirected = graph.to_undirected().to_directed()
    other = compute_local_metrics(undirected, [2, 3, 5], coverage="all", half_distance_km=.1)
    assert result.nodes[0]["information_centrality"] != pytest.approx(other.nodes[0]["information_centrality"])


def test_add_node_consequences_preserves_link_result_and_adds_node_coverage():
    result = compute_link_consequences(road_graph("cycle"), [2, 3, 5], coverage="all")
    baseline = result.baseline
    links = [dict(row) for row in result.links]
    returned = add_node_consequences(result, coverage="all")
    assert returned is result
    assert result.baseline is baseline
    assert result.links == links
    assert result.coverage["nodes"]["evaluated"] == 3


def test_screened_ring_with_no_candidates_keeps_node_scores_null_and_explained():
    result = compute_local_metrics(road_graph("cycle"), [2, 3, 5], coverage="screened",
                                   link_candidate_limit=0, node_candidate_limit=0)
    coverage = result.coverage["nodes"]
    assert coverage["mode"] == "screened"
    assert coverage["evaluated"] == 0 and coverage["total"] == 3
    assert coverage["ids"] == [] and coverage["method"]
    for row in result.nodes.values():
        assert row["evaluated"] is False
        assert row["hansen_accessibility"] is not None
        for field in NODE_CONSEQUENCES:
            for suffix in ("", "_pop"):
                assert row[field + suffix] is None
                assert row["null_reasons"][field + suffix]


def test_zero_population_node_consequences_keep_structural_values_and_explain_weighted_nulls():
    result = compute_local_metrics(road_graph("path"), [0, 0, 0], coverage="all")
    for row in result.nodes.values():
        assert row["evaluated"] is True
        for field in NODE_CONSEQUENCES:
            assert row[field] is not None
            assert row[field + "_pop"] is None
            assert row["null_reasons"][field + "_pop"]
