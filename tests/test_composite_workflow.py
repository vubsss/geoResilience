"""Known answers for composite policy, population replay and reassignment."""
import json
from types import SimpleNamespace

import geopandas as gpd
import networkx as nx
import numpy as np
import pytest
from shapely.geometry import Point

from georesilience.composite import calculate_composites
from georesilience.config import CompositeConfig, CompositeWeights, PopulationConfig, TrafficConfig
from georesilience.population import prepare_population
from georesilience.time_models import TimeContext
from georesilience.traffic import TrafficResult
from georesilience.traffic_failures import ReassignedTrafficTimeModel


def sample_summary():
    result = {'population': {'basis': 'saved_node_counts'}, 'attack': {'horizon': .2}}
    for view in ('unweighted', 'population_weighted'):
        result[view] = {k: {'value': v} for k, v in {
            'targeted_attack_robustness': .1, 'hansen_accessibility': .6,
            'travel_time_reliability': .8, 'connectivity_reliability': .9}.items()}
    result['unweighted'].update(bridge_redundancy={'value': .75}, detour_redundancy={'value': 2.})
    return result


def test_default_composite_known_answer_and_custom_weights():
    summary = sample_summary()
    actual = calculate_composites(summary, CompositeConfig())['population_weighted']
    assert actual['value'] == pytest.approx(.25*.5 + .15*(.75+.5+.6+.8+.9))
    assert actual['components']['attack'] == .5  # raw AUC is normalized by horizon
    weights = dict.fromkeys(CompositeWeights.model_fields, 0.)
    weights['accessibility'] = 1.
    assert calculate_composites(summary, CompositeConfig(weights=weights))['population_weighted']['value'] == .6
    summary['population']['basis'] = 'uniform_node_demand'
    assert calculate_composites(summary, CompositeConfig())['population_weighted']['value'] is None


@pytest.mark.parametrize('weights', [{'attack': -.1}, {'attack': float('nan')}, {'attack': .5}, {'facility': .2}])
def test_invalid_composite_weights_fail(weights):
    with pytest.raises(ValueError):
        CompositeWeights(**weights)


def test_missing_positive_weight_component_is_not_silently_renormalized():
    summary = sample_summary()
    summary['population_weighted']['travel_time_reliability']['value'] = None
    result = calculate_composites(summary, CompositeConfig())['population_weighted']
    assert result['value'] is None and 'travel_time_reliability' in result['reason']


def test_saved_population_replays_ids_and_checks_coordinates(tmp_path):
    graph = nx.MultiDiGraph(crs='EPSG:32644')
    graph.add_node(1, x=500000., y=1900000.)
    graph.add_node(2, x=500100., y=1900000.)
    path = tmp_path/'saved.gpkg'
    frame = gpd.GeoDataFrame({'node_id': ['2', '1'], 'population': [90., 10.]},
        geometry=[Point(500100, 1900000), Point(500000, 1900000)], crs=graph.graph['crs'])
    frame.to_file(path, layer='nodes')
    result = prepare_population(graph, None, PopulationConfig(node_counts=path))
    np.testing.assert_array_equal(result.weights, [10., 90.])
    graph.nodes[1]['x'] += 5
    with pytest.raises(ValueError, match='coordinates'):
        prepare_population(graph, None, PopulationConfig(node_counts=path))


def test_reassignment_captures_congestion_and_counts_disconnected_demand():
    graph = nx.MultiDiGraph()
    graph.add_edge(0, 1, key=0)
    graph.add_edge(0, 2, key=0)
    graph.add_edge(2, 1, key=0)
    free = {e: 60. for e in graph.edges(keys=True)}
    links = [{'link_id': i, '_edges': (e,)} for i, e in enumerate(graph.edges(keys=True))]
    demand = {(0, 1): 100.}
    result = TrafficResult({'status': 'converged'}, [], free, [], demand, dict.fromkeys(free, 100.))
    provider = ReassignedTrafficTimeModel(graph, links, result, free,
        TrafficConfig(enabled=True, od_csv='unused.csv', relative_gap=1e-6))
    costs = provider.costs(TimeContext(0, frozenset([0])))
    assert costs[0, 2, 0] == pytest.approx(69.)
    assert costs[2, 1, 0] == pytest.approx(69.)
    provider.costs(TimeContext(1, frozenset([0, 2])))
    assert provider.summary()['means']['unserved_demand_pcu_h'] == 50.
    assert result.demand == demand


def test_configured_full_workflow_uses_saved_population_facilities_and_custom_weights(tmp_path):
    from tests.test_service_pipeline import service_input
    from georesilience.workflow import run_study
    from georesilience.pipeline import run
    from georesilience.pipeline import replay_manifest
    from georesilience.config import RunConfig
    directory, road, raster, facilities = service_input(tmp_path)
    baseline = tmp_path/'baseline'
    initial = RunConfig(input={'path': road}, population={'worldpop': raster},
        cleaning={'consolidate': False}, analysis={'n_jobs': 1, 'max_memory_gb': .1},
        robustness={'fraction': .2, 'steps': 2}, reliability={'samples': 2},
        travel_time={'samples': 2}, output={'dir': baseline, 'figures': False})
    run(initial)
    config = tmp_path/'study.json'
    weights = dict.fromkeys(CompositeWeights.model_fields, 0.)
    weights['accessibility'] = 1.
    values = initial.model_dump(mode='json')
    values['population'] = {'node_counts': str(baseline/'network.gpkg')}
    values['traffic'] = {'enabled': True, 'demand_source': 'population', 'population_zone_limit': 4, 'relative_gap': .001}
    values['services'] = {'facilities_csv': str(facilities), 'mode': 'sfca',
        'school': {'catchment_minutes': 10}, 'hospital': {'catchment_minutes': 10}}
    values['composite'] = {'weights': weights}
    values['output']['dir'] = str(tmp_path/'study')
    config.write_text(json.dumps({'run': values}))
    result = run_study(config)
    assert result['default_view'] == 'population_weighted'
    assert result['headline']['value'] == result['population_weighted']['hansen_accessibility']['value']
    assert result['traffic']['failure_reassignment']['all_converged']
    assert result['services']['sfca']['school']['status'] == 'computed'
    assert (tmp_path/'study/analysis/traffic_failure_states.csv').is_file()
    assert (tmp_path/'study/workflow_complete.json').is_file()
    replayed = replay_manifest(tmp_path/'study/analysis/run_manifest.json', tmp_path/'replay')
    assert replayed['headline'] == result['headline']
    assert replayed['traffic']['failure_reassignment'] == result['traffic']['failure_reassignment']

    # Exercise the full cleaned-road -> closure CSV -> analysis handoff, using a
    # supplied dry raster so this contract test stays offline and solver-free.
    import rasterio
    from rasterio.transform import from_origin
    node_frame = gpd.read_file(baseline/'network.gpkg', layer='nodes')
    left, _, _, top = node_frame.total_bounds
    depth = tmp_path/'dry_depth.tif'
    with rasterio.open(depth, 'w', driver='GTiff', width=40, height=40, count=1,
            dtype='float32', crs=node_frame.crs,
            transform=from_origin(left-100, top+100, 100, 100)) as target:
        target.write(np.zeros((40, 40), dtype='float32'), 1)
    scenario = tmp_path/'flood.json'
    scenario.write_text(json.dumps({'depth': str(depth)}))
    values['output']['dir'] = str(tmp_path/'flood_study')
    config.write_text(json.dumps({'run': values, 'flood_config': str(scenario)}))
    flooded = run_study(config)
    assert (tmp_path/'flood_study/flood/failure_probabilities.csv').is_file()
    assert flooded['probabilities']['coverage']['by_source']['proxy']['links'] == 0
    assert json.loads((tmp_path/'flood_study/workflow_complete.json').read_text())['flood_used']


def test_population_zone_limit_is_an_actual_upper_bound():
    from georesilience.traffic import population_gravity_od
    graph = nx.MultiDiGraph()
    for node, (x, y) in enumerate(((0, 0), (100, 0), (0, 100), (100, 100))):
        graph.add_node(node, x=x, y=y)
    for a in graph:
        for b in graph:
            if a != b:
                graph.add_edge(a, b)
    times = dict.fromkeys(graph.edges(keys=True), 60.)
    demand = population_gravity_od(graph, times, [10, 20, 30, 40], .1, .08, zone_limit=2)
    assert len({n for pair in demand for n in pair}) <= 2
    assert sum(demand.values()) == pytest.approx(10.)
    for node in graph:
        graph.nodes[node].update(x=100.*node, y=0.)
    demand = population_gravity_od(graph, times, [10, 20, 30, 40], .1, .08, zone_limit=2)
    assert len({n for pair in demand for n in pair}) == 2


def test_comparison_charts_and_rejection_of_incompatible_views(tmp_path):
    from georesilience.comparison import compare_runs
    summary = sample_summary()
    summary['default_view'] = 'population_weighted'
    summary['metric_cost'] = {'kind': 'time', 'unit': 'seconds', 'half_cost': 360.}
    summary['composite'] = calculate_composites(summary, CompositeConfig())
    paths = {}
    for label in ('A', 'B'):
        folder = tmp_path/label
        folder.mkdir()
        (folder/'summary.json').write_text(json.dumps(summary))
        paths[label] = folder
    rows = compare_runs(paths, tmp_path/'comparison')
    assert len(rows) == 2 and rows[0]['view'] == 'population_weighted'
    assert (tmp_path/'comparison/components.png').is_file()
    assert (tmp_path/'comparison/composite.svg').is_file()
    summary['default_view'] = 'unweighted'
    (paths['B']/'summary.json').write_text(json.dumps(summary))
    with pytest.raises(ValueError, match='matching views'):
        compare_runs(paths, tmp_path/'incompatible')
