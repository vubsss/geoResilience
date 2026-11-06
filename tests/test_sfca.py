"""Independent standard 2SFCA oracle; no production routing/reducers reused."""

import csv

import networkx as nx
import numpy as np
import pytest
from pyproj import Transformer

from georesilience.config import ServicesConfig, TravelTimeConfig
from georesilience.links import _link_rows
from georesilience.services import prepare_services
from georesilience.sfca import compute_sfca
from georesilience.time_routing import prepare_static_time


def service_fixture(tmp_path, *, population=(4, 4, 0, 0), edges=None,
                    facilities=((2, 'school', 1), (3, 'school', 1)), mode='sfca'):
    graph = nx.MultiDiGraph(crs='EPSG:3857')
    graph.add_nodes_from((i, {'x': i * 100., 'y': 0.}) for i in range(len(population)))
    for u, v, seconds in ([(0, 2, 60), (1, 2, 60), (1, 3, 60)] if edges is None else edges):
        graph.add_edge(u, v, length=max(1, abs(u-v))*100., travel_time_s=seconds,
            osmid=100 + min(u,v)*10 + max(u,v))
    path = tmp_path / 'facilities.csv'
    transform = Transformer.from_crs(3857, 4326, always_xy=True)
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['facility_id', 'service_type', 'longitude', 'latitude', 'capacity', 'capacity_unit', 'capacity_source'])
        for i, (node, category, capacity) in enumerate(facilities):
            writer.writerow([f'{i:03d}', category, *transform.transform(graph.nodes[node]['x'], 0),
                capacity, 'seats' if category == 'school' else 'beds', 'synthetic registry'])
    config = ServicesConfig(facilities_csv=path, mode=mode,
        school={'catchment_minutes': 1}, hospital={'catchment_minutes': 1})
    prepared = prepare_services(graph, config)
    routing = prepare_static_time(graph, _link_rows(graph), TravelTimeConfig(time_model='edge_attribute'))
    return graph, np.asarray(population, dtype=float), config, prepared, routing


def brute_force(graph, population, facilities, category, cutoff=60, *, removed=(), isolated=()):
    damaged = graph.copy()
    damaged.remove_edges_from(removed)
    damaged.remove_edges_from([(u, v, k) for u, v, k in list(damaged.edges(keys=True)) if u in isolated or v in isolated])
    access = np.zeros(len(graph))
    demands, ratios = [], []
    for facility in facilities:
        if facility.record.service_type != category:
            continue
        resident_nodes = []
        for origin in graph:
            if origin in isolated or facility.node_id in isolated:
                continue
            try:
                seconds = nx.shortest_path_length(damaged, origin, facility.node_id, weight='travel_time_s')
            except nx.NetworkXNoPath:
                continue
            if seconds <= cutoff:
                resident_nodes.append(origin)
        demand = sum(population[i] for i in resident_nodes)
        supply = 0 if facility.node_id in isolated else facility.record.capacity
        ratio = supply/demand if demand else None
        demands.append(demand)
        ratios.append(ratio)
        if ratio is not None:
            for origin in resident_nodes:
                access[origin] += ratio
    return access, demands, ratios


def test_paper_example_and_both_aggregation_views(tmp_path):
    graph, pop, config, prepared, routing = service_fixture(tmp_path)
    result = compute_sfca(prepared, pop, config, routing).categories['school']
    assert [r['catchment_demand'] for r in result.facilities] == [8, 4]
    assert [r['supply_demand_ratio'] for r in result.facilities] == [1/8, 1/4]
    np.testing.assert_allclose(result.node_access, [1/8, 3/8, 1/8, 1/4])
    assert result.summary['population_mean'] == pytest.approx(1/4)
    assert result.summary['equal_node_mean'] == pytest.approx(7/32)
    assert result.summary['population_mean_per_1000'] == 250
    assert result.summary['zero_access_population_share'] == 0
    expected, demand, ratios = brute_force(graph, pop, prepared.facilities, 'school')
    np.testing.assert_allclose(result.node_access, expected)


@pytest.mark.parametrize('pop_scale,supply_scale', [(1, 7), (5, 1), (5, 7)])
def test_nonunit_scaling_and_conservation(tmp_path, pop_scale, supply_scale):
    graph, pop, config, prepared, routing = service_fixture(tmp_path,
        population=[4*pop_scale, 4*pop_scale, 0, 0],
        facilities=[(2, 'school', 2*supply_scale), (3, 'school', 3*supply_scale), (2, 'hospital', 5*supply_scale)])
    result = compute_sfca(prepared, pop, config, routing)
    for category in ('school', 'hospital'):
        expected, _, _ = brute_force(graph, pop, prepared.facilities, category)
        np.testing.assert_allclose(result.categories[category].node_access, expected)
        positive_supply = sum(f.record.capacity for f in prepared.facilities if f.record.service_type == category)
        assert pop @ expected == pytest.approx(positive_supply)
    assert result.categories['school'].node_access[1] == pytest.approx(supply_scale / pop_scale)


def test_colocation_zero_demand_and_raw_scores_above_one(tmp_path):
    graph, pop, config, prepared, routing = service_fixture(tmp_path, population=[1, 0, 0], edges=[],
        facilities=[(0, 'hospital', 10), (0, 'hospital', 20), (2, 'hospital', 5)])
    result = compute_sfca(prepared, pop, config, routing).categories['hospital']
    np.testing.assert_array_equal(result.node_access, [30, 0, 0])
    assert result.summary['zero_demand_capacity'] == 5
    assert result.summary['positive_demand_capacity'] == 30
    assert result.facilities[2]['supply_demand_ratio'] is None
    assert 'zero catchment demand' in result.facilities[2]['ratio_reason']
    assert pop @ result.node_access == 30
    assert result.summary['population_mean_per_1000'] == 30000


def test_known_zero_supply_and_unreachable_supply(tmp_path):
    _, pop, config, prepared, routing = service_fixture(tmp_path, population=[1, 1], edges=[],
        facilities=[(1, 'school', 0)])
    result = compute_sfca(prepared, pop, config, routing).categories['school']
    np.testing.assert_array_equal(result.node_access, [0, 0])
    assert result.facilities[0]['supply_demand_ratio'] == 0
    assert result.summary['zero_access_population_share'] == 1


@pytest.mark.parametrize('case,match', [('zero_population', 'zero original population'),
    ('missing_category', 'not supplied'), ('no_times', 'unavailable'), ('weights', 'weights-only')])
def test_unavailable_states_are_distinct(tmp_path, case, match):
    _, pop, config, prepared, routing = service_fixture(tmp_path,
        population=[0, 0, 0, 0] if case == 'zero_population' else [4, 4, 0, 0],
        mode='weights_only' if case == 'weights' else 'sfca')
    result = compute_sfca(prepared, pop, config, None if case == 'no_times' else routing)
    category = result.categories['hospital' if case == 'missing_category' else 'school']
    assert category.node_access is None and match in category.reason
    assert category.summary['population_mean'] is None


def test_multitype_oracle_and_serial_parallel_bounded_passes(tmp_path):
    graph, pop, config, prepared, routing = service_fixture(tmp_path, population=[3, 2, 1, 4, 0],
        edges=[(0, 1, 10), (1, 2, 20), (2, 1, 20), (2, 3, 40), (3, 4, 30)],
        facilities=[(0, 'school', 1), (1, 'school', 2), (2, 'school', 3),
            (3, 'school', 4), (4, 'school', 5), (2, 'hospital', 8), (3, 'hospital', 10)])
    for jobs, budget in [(1, 5*128), (2, 5*256), (2, 2**20)]:
        result = compute_sfca(prepared, pop, config, routing, n_jobs=jobs, budget_bytes=budget)
        for category in ('school', 'hospital'):
            expected, demands, ratios = brute_force(graph, pop, prepared.facilities, category)
            output = result.categories[category]
            np.testing.assert_allclose(output.node_access, expected)
            assert [r['catchment_demand'] for r in output.facilities] == demands
            assert [r['supply_demand_ratio'] for r in output.facilities] == ratios
            assert pop @ output.node_access == pytest.approx(output.summary['positive_demand_capacity'])
    with pytest.raises(ValueError, match='memory budget too small'):
        compute_sfca(prepared, pop, config, routing, budget_bytes=1)
