"""Paired targeted-link curves and exact exported-horizon integration."""

import csv

import networkx as nx
import numpy as np
import pytest

from georesilience.links import _link_rows
from georesilience.robustness import CURVE_COLUMNS, compute_targeted_attack, write_curve


def path_graph(n=4):
    graph = nx.MultiDiGraph(crs=32644, simplified=True)
    for node in range(n):
        graph.add_node(node, x=node * 100, y=0)
    for way in range(n - 1):
        graph.add_edge(way, way + 1, length=100, osmid=way + 1)
        graph.add_edge(way + 1, way, length=100, osmid=way + 1)
    return graph


def test_path_exact_auc_and_same_component_population_tie(tmp_path):
    graph = path_graph()
    links = _link_rows(graph)
    result = compute_targeted_attack(graph, links, [1, 1, 100, 100], fraction=1 / 3)
    assert len(result.removal_order) == 1
    assert result.removal_order[0] == next(row["link_uid"] for row in links if row["_u"] == 1)
    assert result.curve[0]["node_share"] == result.curve[0]["population_share"] == 1
    last = result.curve[-1]
    assert last["node_share"] == .5
    # The equally sized SCC containing nodes 0,1 wins by canonical IDs even
    # though the other component contains 100 times as many residents.
    assert last["population_share"] == pytest.approx(1 / 101)
    assert result.summary["unweighted"]["value"] == pytest.approx(1 / 4)
    assert result.summary["population_weighted"]["value"] == pytest.approx(17 / 101)
    assert last["removed_link_uid"] == result.removal_order[-1]
    path = write_curve(result, tmp_path / "attack_curve.csv")
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames) == CURVE_COLUMNS
        rows = list(reader)
    x = [float(row["fraction_removed"]) for row in rows]
    for key, column in [("unweighted", "node_share"), ("population_weighted", "population_share")]:
        assert result.summary[key]["value"] == pytest.approx(
            np.trapezoid([float(row[column]) for row in rows], x))


@pytest.mark.parametrize("order", ["adaptive", "static"])
def test_population_does_not_change_attack_order_or_node_curve(order):
    graph = path_graph(7)
    links = _link_rows(graph)
    structural = compute_targeted_attack(graph, links, [1] * 7, fraction=.8, steps=3, order=order)
    weighted = compute_targeted_attack(graph, links, [0, 0, 20, 1, 2, 0, 0], fraction=.8, steps=3, order=order)
    assert structural.removal_order == weighted.removal_order
    assert [row["node_share"] for row in structural.curve] == [row["node_share"] for row in weighted.curve]
    assert len(structural.removal_order) == 4
    assert structural.curve[-1]["fraction_removed"] == pytest.approx(4 / 6)
    assert structural.summary["horizon"] <= .8
    assert len(structural.curve) <= 4
    assert structural.summary["order"] == order


def test_adaptive_recomputes_after_each_removal_even_between_exported_points(monkeypatch):
    import georesilience.robustness as module
    calls = []
    original = module._structural

    def observed(graph, active):
        calls.append(len(active))
        return original(graph, active)

    monkeypatch.setattr(module, "_structural", observed)
    graph = path_graph(7)
    result = compute_targeted_attack(graph, _link_rows(graph), [1] * 7, fraction=1, steps=2)
    assert calls == [6, 5, 4, 3, 2, 1]
    assert [row["links_removed"] for row in result.curve] == [0, 3, 6]
    calls.clear()
    compute_targeted_attack(graph, _link_rows(graph), [1] * 7, fraction=1, steps=2, order="static")
    assert calls == [6]


def test_seed_and_iteration_order_do_not_change_results():
    graph = path_graph(7)
    links = _link_rows(graph)
    first = compute_targeted_attack(graph, links, [1, 2, 3, 4, 5, 6, 7], fraction=1, steps=5)
    reordered = nx.MultiDiGraph(**graph.graph)
    reordered.add_nodes_from(reversed(list(graph.nodes(data=True))))
    reordered.add_edges_from(reversed(list(graph.edges(keys=True, data=True))))
    second = compute_targeted_attack(reordered, list(reversed(_link_rows(reordered))),
        [7, 6, 5, 4, 3, 2, 1], fraction=1, steps=5, seed=99)
    assert first.curve == second.curve
    assert first.removal_order == second.removal_order
    assert first.summary["unweighted"] == second.summary["unweighted"]
    assert first.summary["population_weighted"] == second.summary["population_weighted"]
    assert graph.number_of_edges() == 12


def test_zero_population_and_single_populated_origin_have_distinct_results(tmp_path):
    graph = path_graph()
    zero = compute_targeted_attack(graph, _link_rows(graph), [0] * 4, fraction=1)
    assert zero.summary["unweighted"]["value"] is not None
    assert zero.summary["population_weighted"]["value"] is None
    assert zero.summary["population_weighted"]["reason"] == "zero total population"
    assert all(row["population_share"] is None for row in zero.curve)
    path = write_curve(zero, tmp_path / "zero.csv")
    with path.open(newline="") as stream:
        assert all(row["population_share"] == "" for row in csv.DictReader(stream))
    one = compute_targeted_attack(graph, _link_rows(graph), [5, 0, 0, 0], fraction=1)
    assert one.summary["population_weighted"]["value"] is not None
    assert all(row["population_share"] in (0, 1) for row in one.curve)


@pytest.mark.parametrize("fraction", [0, .2])
def test_integer_horizon_never_rounds_up_or_extrapolates(fraction):
    graph = path_graph()
    result = compute_targeted_attack(graph, _link_rows(graph), [1] * 4, fraction=fraction)
    assert result.removal_order == []
    assert len(result.curve) == 1
    assert result.summary["horizon"] == 0
    for weighting in ("unweighted", "population_weighted"):
        assert result.summary[weighting]["value"] is None
        assert result.summary[weighting]["reason"] == "no links removed"
    assert not {"random", "failure", "node_attack", "efficiency"} & result.summary.keys()


def test_oneway_physical_link_removal_and_parallel_arc_preservation():
    graph = path_graph(2)
    graph.add_edge(0, 1, length=200, osmid=99)
    graph.add_edge(1, 0, length=200, osmid=99)
    result = compute_targeted_attack(graph, _link_rows(graph), [1, 3], fraction=1)
    assert [row["node_share"] for row in result.curve] == [1, 1, .5]
    assert result.curve[-1]["population_share"] == .25
    directed = nx.MultiDiGraph()
    for node in range(3):
        directed.add_node(node, x=node, y=0)
    for way in range(3):
        directed.add_edge(way, (way + 1) % 3, length=1, osmid=way + 1)
    result = compute_targeted_attack(directed, _link_rows(directed), [1, 2, 3], fraction=1 / 3)
    assert result.curve[-1]["node_share"] == pytest.approx(1 / 3)
    assert result.curve[-1]["population_share"] == pytest.approx(1 / 6)


@pytest.mark.parametrize("options", [{"fraction": -1}, {"fraction": 1.1}, {"fraction": float("nan")},
    {"steps": 0}, {"steps": 1.5}, {"order": "random"}])
def test_invalid_attack_options_fail(options):
    graph = path_graph()
    with pytest.raises(ValueError):
        compute_targeted_attack(graph, _link_rows(graph), [1] * 4, **options)
