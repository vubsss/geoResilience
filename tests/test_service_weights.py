"""Independent count and population-by-service formula checks."""

import math

import networkx as nx
import numpy as np
import pytest
from scipy.sparse import csr_matrix

from georesilience.config import ServicesConfig
from georesilience.service_metrics import ServiceUniverse, evaluate_service_matrix
from georesilience.services import prepare_services, service_node_fields, service_node_weights
from tests.test_service_inputs import facility_csv, metric_graph, school


@pytest.mark.parametrize('rows,importance,expected', [
    ([], {}, [0, 0]),
    ([school()], {}, [1, 0]),
    ([school(), school(facility_id='002')], {}, [2, 0]),
    ([school(), school(facility_id='002', service_type='hospital', capacity_unit='beds')], {}, [2, 0]),
    ([school(), school(facility_id='002', service_type='hospital', capacity_unit='beds')],
        {'school': {'importance': 2}, 'hospital': {'importance': 7}}, [9, 0]),
    ([school()], {'school': {'importance': 0}}, [0, 0]),
])
def test_count_weights_and_capacity_scaling(tmp_path, rows, importance, expected):
    rows = [{**row, 'longitude': '0', 'latitude': '0'} for row in rows]
    graph = metric_graph([(1, 0, 0), (2, 100, 0)])
    path = facility_csv(tmp_path, rows)
    config = ServicesConfig(facilities_csv=path, **importance)
    first = prepare_services(graph, config)
    weights = service_node_weights(first, config)
    np.testing.assert_array_equal(weights, expected)
    fields = service_node_fields(first, weights)
    assert fields[1]['school_count'] == sum(row['service_type'] == 'school' for row in rows)
    assert fields[1]['service_weight'] == expected[0]
    facility_csv(tmp_path, [{**row, 'capacity': str(float(row['capacity']) * 1000),
        'capacity_unit': row['capacity_unit'] + '_scaled'} for row in rows])
    np.testing.assert_array_equal(service_node_weights(prepare_services(graph, config), config), weights)


def explicit_sum(graph, population, weights, *, isolated=(), half=100, cutoff=500):
    reached, hansen = [], []
    damaged = graph.copy()
    damaged.remove_edges_from([(u, v) for u, v in graph.edges if u in isolated or v in isolated])
    for i in graph:
        r, h = 0, 0
        for j in graph:
            if i in isolated or j in isolated:
                continue
            try:
                d = nx.shortest_path_length(damaged, i, j, weight='length')
            except nx.NetworkXNoPath:
                continue
            r += weights[j]
            if d <= cutoff:
                h += weights[j] * math.exp(-math.log(2) * d / half)
        reached.append(r / sum(weights))
        hansen.append(h / sum(weights))
    return reached, hansen, sum(p*h for p, h in zip(population, hansen)) / sum(population)


def test_directed_reachability_and_hansen_match_explicit_pairs():
    graph = nx.DiGraph()
    graph.add_nodes_from(range(4))
    graph.add_edge(0, 1, length=100)
    graph.add_edge(1, 2, length=100)
    graph.add_edge(3, 0, length=1000)
    matrix = nx.to_scipy_sparse_array(graph, nodelist=list(graph), weight='length', format='csr')
    population, weights = [3, 2, 1, 4], [0, 2, 5, 0]
    universe = ServiceUniverse(population, weights)
    for isolated in ((), (1,)):
        expected_r, expected_h, expected_mean = explicit_sum(graph, population, weights, isolated=isolated)
        snapshot = evaluate_service_matrix(matrix, universe, half_distance_km=.1, isolated_nodes=isolated)
        np.testing.assert_allclose(snapshot.node_reachability, expected_r)
        np.testing.assert_allclose(snapshot.node_hansen, expected_h)
        assert snapshot.summary['hansen_accessibility']['value'] == pytest.approx(expected_mean)
        assert snapshot.summary['directed_reachability']['value'] == pytest.approx(np.dot(population, expected_r)/10)


def test_diagonal_access_and_fixed_original_denominators():
    u = ServiceUniverse([2, 3], [1, 4])
    no_roads = csr_matrix((2, 2))
    baseline = evaluate_service_matrix(no_roads, u)
    assert baseline.summary['directed_reachability']['value'] == pytest.approx(14/25)
    closed = evaluate_service_matrix(no_roads, u, isolated_nodes=(1,))
    assert closed.summary['directed_reachability']['value'] == pytest.approx(2/25)
    assert evaluate_service_matrix(csr_matrix((1, 1)), ServiceUniverse([8], [3])).node_hansen[0] == 1


@pytest.mark.parametrize('population,weights,reason', [([0, 0], [1, 1], 'population'),
    ([1, 1], [0, 0], 'service'), ([], [], 'population')])
def test_zero_masses_are_unavailable(population, weights, reason):
    result = evaluate_service_matrix(csr_matrix((len(population), len(population))), ServiceUniverse(population, weights))
    for metric in result.summary.values():
        assert metric['value'] is None and reason in metric['reason']


def test_no_capacity_input_is_still_counted_and_unknown_capacity_is_null(tmp_path):
    path = facility_csv(tmp_path, [school(longitude='0', latitude='0', capacity='')])
    config = ServicesConfig(facilities_csv=path)
    prepared = prepare_services(metric_graph([(1, 0, 0)]), config)
    weights = service_node_weights(prepared, config)
    assert weights[0] == 1
    assert service_node_fields(prepared, weights)[1]['school_capacity'] is None
