"""Independent directed, fixed-universe structural and population baselines."""

import math

import networkx as nx
import numpy as np
import pytest

from georesilience.metrics import PairUniverse, compute_baseline, evaluate_matrix, relative_drop


def path_graph():
    graph = nx.MultiDiGraph(crs=32644, simplified=True)
    for node in range(3):
        graph.add_node(node, x=500000 + 100 * node, y=1900000)
    graph.add_edge(0, 1, length=100, osmid=10)
    graph.add_edge(1, 2, length=100, osmid=20)
    return graph


def independent_reference(graph, population, half_distance_km=.1, cutoff_factor=5):
    """Enumerate ordered pairs without the product's shortest-path reducers."""
    nodes = list(graph)
    population = np.asarray(population, dtype=float)
    distances = dict(nx.all_pairs_dijkstra_path_length(graph, weight="length"))
    n = len(nodes)
    decay = np.zeros((n, n))
    inverse = np.zeros((n, n))
    reached = np.zeros((n, n))
    for i, origin in enumerate(nodes):
        for j, destination in enumerate(nodes):
            if i == j:
                continue
            distance = distances[origin].get(destination, math.inf)
            if math.isfinite(distance):
                reached[i, j] = 1
                inverse[i, j] = 1 / distance
                if distance <= half_distance_km * 1000 * cutoff_factor:
                    decay[i, j] = math.exp(-math.log(2) * distance / (half_distance_km * 1000))
    structural_denominator = n * (n - 1)
    population_pairs = population[:, None] * population[None, :]
    np.fill_diagonal(population_pairs, 0)
    population_denominator = population_pairs.sum()
    destination_population = population.sum() - population
    node_hansen = decay.sum(axis=1) / (n - 1) if n > 1 else np.full(n, np.nan)
    node_hansen_pop = np.divide(decay @ population, destination_population,
                                out=np.full(n, np.nan), where=destination_population > 0)
    return {
        "node_hansen": node_hansen,
        "node_hansen_pop": node_hansen_pop,
        "efficiency": inverse.sum() / structural_denominator if structural_denominator else None,
        "efficiency_pop": (inverse * population_pairs).sum() / population_denominator
            if population_denominator else None,
        "accessibility": node_hansen.mean() if n > 1 else None,
        "accessibility_pop": (np.nansum(node_hansen_pop * population) / population.sum()
            if population_denominator else None),
        "reachable_fraction": reached.sum() / structural_denominator if structural_denominator else None,
        "reachable_fraction_pop": (reached * population_pairs).sum() / population_denominator
            if population_denominator else None,
    }


def assert_snapshot_matches(snapshot, reference):
    for field, expected in reference.items():
        actual = getattr(snapshot, field)
        if isinstance(expected, np.ndarray):
            np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-15, equal_nan=True)
        elif expected is None:
            assert actual is None, field
        else:
            assert actual == pytest.approx(expected, rel=1e-12, abs=1e-15), field


def test_two_node_half_distance_has_half_accessibility_for_both_weightings():
    graph = path_graph().subgraph([0, 1]).copy()
    graph.add_edge(1, 0, length=100, osmid=10)
    result = compute_baseline(graph, [2, 7], half_distance_km=.1)
    np.testing.assert_allclose(result.node_hansen, [.5, .5])
    np.testing.assert_allclose(result.node_hansen_pop, [.5, .5])
    assert result.accessibility == pytest.approx(.5)
    assert result.accessibility_pop == pytest.approx(.5)
    assert result.efficiency == pytest.approx(.01)
    assert result.efficiency_pop == pytest.approx(.01)
    assert result.reachable_fraction == result.reachable_fraction_pop == 1


@pytest.mark.parametrize("population", [[2, 3, 5], [0, 3, 5], [1, 1, 1]])
def test_directed_path_matches_independent_ordered_pair_formulas(population):
    graph = path_graph()
    result = compute_baseline(graph, population, half_distance_km=.1)
    assert_snapshot_matches(result, independent_reference(graph, population))
    np.testing.assert_allclose(result.node_hansen, [.375, .25, 0])
    assert result.efficiency == pytest.approx(.025 / 6)
    assert result.reachable_fraction == .5


def test_population_origin_average_uses_population_and_fixed_destination_denominators():
    result = compute_baseline(path_graph(), [2, 3, 5], half_distance_km=.1)
    expected_nodes = [(3 * .5 + 5 * .25) / 8, (5 * .5) / 7, 0]
    np.testing.assert_allclose(result.node_hansen_pop, expected_nodes)
    assert result.accessibility_pop == pytest.approx((2 * expected_nodes[0] + 3 * expected_nodes[1]) / 10)
    assert result.efficiency_pop == pytest.approx((6 / 100 + 10 / 200 + 15 / 100) / 62)


def test_hansen_cutoff_is_inclusive_and_only_changes_accessibility():
    graph = path_graph()
    included = compute_baseline(graph, [2, 3, 5], half_distance_km=.1, cutoff_factor=2)
    excluded = compute_baseline(graph, [2, 3, 5], half_distance_km=.1, cutoff_factor=1.999)
    np.testing.assert_allclose(included.node_hansen, [.375, .25, 0])
    np.testing.assert_allclose(excluded.node_hansen, [.25, .25, 0])
    assert included.accessibility > excluded.accessibility
    assert included.efficiency == excluded.efficiency
    assert included.efficiency_pop == excluded.efficiency_pop
    assert included.reachable_fraction == excluded.reachable_fraction


def test_zero_population_keeps_structural_metrics_and_marks_population_undefined():
    graph = path_graph()
    result = compute_baseline(graph, [0, 0, 0], half_distance_km=.1)
    assert_snapshot_matches(result, independent_reference(graph, [0, 0, 0]))
    assert np.isnan(result.node_hansen_pop).all()
    assert result.efficiency is not None and result.accessibility is not None
    assert result.reachable_fraction is not None


def test_one_populated_node_has_no_weighted_distinct_pair_universe():
    result = compute_baseline(path_graph(), [3, 0, 0], half_distance_km=.1)
    assert np.isnan(result.node_hansen_pop[0])
    np.testing.assert_allclose(result.node_hansen_pop[1:], [0, 0])
    assert result.efficiency_pop is result.accessibility_pop is result.reachable_fraction_pop is None


def test_singleton_metrics_are_undefined():
    graph = nx.MultiDiGraph(crs=32644)
    graph.add_node(0, x=500000, y=1900000)
    result = compute_baseline(graph, [7], half_distance_km=.1)
    assert_snapshot_matches(result, independent_reference(graph, [7]))
    assert np.isnan(result.node_hansen).all() and np.isnan(result.node_hansen_pop).all()


@pytest.mark.parametrize("population", [[-1, 2], [float("nan"), 1], [float("inf"), 1], [[1, 2]], 3])
def test_pair_universe_rejects_invalid_population(population):
    with pytest.raises(ValueError, match="(?i)population|weight|finite|nonnegative|dimension"):
        PairUniverse(population)


def test_baseline_rejects_population_length_mismatch():
    with pytest.raises(ValueError):
        compute_baseline(path_graph(), [1, 2])


def test_isolated_node_uses_same_directed_fixed_pair_universe_and_information_loss():
    graph = path_graph()
    population = [2, 3, 5]
    baseline = compute_baseline(graph, population, half_distance_km=.1)
    isolated_index = baseline.topology.index[1]
    after = evaluate_matrix(baseline.topology.csr(isolated_nodes=[isolated_index]), baseline.universe,
                            half_distance_km=.1)
    expected = graph.copy()
    expected.remove_edges_from(list(expected.in_edges(1, keys=True)) + list(expected.out_edges(1, keys=True)))
    assert_snapshot_matches(after, independent_reference(expected, population))
    assert len(after.node_hansen) == len(population)
    assert relative_drop(baseline.efficiency, after.efficiency) == 1
    assert relative_drop(baseline.efficiency_pop, after.efficiency_pop) == 1


def test_partial_node_isolation_matches_directed_reference_without_renormalization():
    graph = path_graph()
    population = [2, 3, 5]
    baseline = compute_baseline(graph, population, half_distance_km=.1)
    after = evaluate_matrix(baseline.topology.csr(isolated_nodes=[baseline.topology.index[0]]),
                            baseline.universe, half_distance_km=.1)
    expected = graph.copy()
    expected.remove_edges_from(list(expected.out_edges(0, keys=True)))
    assert_snapshot_matches(after, independent_reference(expected, population))
    assert after.efficiency == pytest.approx(.01 / 6)
    assert after.efficiency_pop == pytest.approx((15 / 100) / 62)
    assert relative_drop(baseline.efficiency, after.efficiency) == pytest.approx(.6)
    assert relative_drop(baseline.efficiency_pop, after.efficiency_pop) == pytest.approx(11 / 26)


def test_zero_or_undefined_baseline_has_no_relative_drop():
    assert relative_drop(0, 0) is None
    assert relative_drop(None, 0) is None
    assert relative_drop(1, .75) == .25


def test_extreme_population_imbalance_preserves_both_ordered_directions():
    graph = nx.MultiDiGraph()
    graph.add_node(0, x=0, y=0)
    graph.add_node(1, x=100, y=0)
    graph.add_edge(0, 1, length=100, osmid=1)
    graph.add_edge(1, 0, length=100, osmid=1)
    result = compute_baseline(graph, [1e17, 1], half_distance_km=.1)
    assert result.reachable_fraction_pop == pytest.approx(1)
    assert result.efficiency_pop == pytest.approx(.01)
    assert result.accessibility_pop == pytest.approx(.5)


def test_parallel_memory_bounded_rows_match_serial_baseline():
    graph = path_graph()
    serial = compute_baseline(graph, [2, 3, 5], half_distance_km=.1)
    parallel = compute_baseline(graph, [2, 3, 5], half_distance_km=.1, n_jobs=2, budget_bytes=384)
    assert_snapshot_matches(parallel, independent_reference(graph, [2, 3, 5]))
    np.testing.assert_allclose(serial.node_hansen_pop, parallel.node_hansen_pop)
    with pytest.raises(ValueError, match="memory budget"):
        compute_baseline(graph, [2, 3, 5], budget_bytes=1)
