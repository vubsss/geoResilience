"""Combined importance across indices, checked against independent pair oracles."""

from itertools import product
import json

import geopandas as gpd
import numpy as np
import pytest

from georesilience.links import identify_links
from georesilience.metrics import PairUniverse, compute_baseline, compute_local_metrics
from georesilience.services import combined_node_importance
from tests.test_directory_cli import invoke, read_summary, run_args
from tests.test_event_reliability import compute, independent_exact, roads
from tests.test_metric_baselines import independent_reference, path_graph
from tests.test_service_pipeline import service_args, service_input


@pytest.mark.parametrize('time_costs', [False, True])
def test_importance_baselines_and_removals_match_independent_pairs(time_costs):
    graph = path_graph()
    population = [90, 10, 0]
    importance, _, _ = combined_node_importance(population, [0, 1, 1], 2)
    costs = {edge: graph.edges[edge]['length'] / 10 for edge in graph.edges(keys=True)} if time_costs else None
    reference_graph = graph.copy()
    if costs is not None:
        for edge, cost in costs.items():
            reference_graph.edges[edge]['length'] = cost
    expected = independent_reference(reference_graph, importance)
    local = compute_local_metrics(graph, population, node_importance=importance,
        edge_costs=costs, coverage='all', half_distance_km=.1)
    baseline = local.baseline
    np.testing.assert_allclose(baseline.node_hansen_importance, expected['node_hansen_pop'])
    for measure in ('accessibility', 'efficiency', 'reachable_fraction'):
        assert getattr(baseline, measure + '_importance') == pytest.approx(expected[measure + '_pop'])
    assert baseline.accessibility_importance != pytest.approx(baseline.accessibility_pop)
    # Removing an edge or isolating a node keeps the intact importance denominator.
    for row in local.links:
        damaged = reference_graph.copy()
        damaged.remove_edges_from(row['_edges'])
        after = independent_reference(damaged, importance)
        for measure, field in (('accessibility', 'accessibility_drop'), ('efficiency', 'efficiency_drop')):
            before = expected[measure + '_pop']
            assert row[field + '_importance'] == pytest.approx((before - after[measure + '_pop']) / before)
        assert row['disconnected_pair_fraction_importance'] == pytest.approx(
            expected['reachable_fraction_pop'] - after['reachable_fraction_pop'])
    for node, row in local.nodes.items():
        damaged = reference_graph.copy()
        damaged.remove_edges_from([edge for edge in list(damaged.edges(keys=True)) if node in edge[:2]])
        after = independent_reference(damaged, importance)
        assert row['information_centrality_importance'] == pytest.approx(
            (expected['efficiency_pop'] - after['efficiency_pop']) / expected['efficiency_pop'])
        assert row['accessibility_drop_importance'] == pytest.approx(
            (expected['accessibility_pop'] - after['accessibility_pop']) / expected['accessibility_pop'])


@pytest.mark.parametrize('population,services', [([90, 10, 0], [0, 1, 1]), ([0, 0, 0], [1, 0, 3])])
def test_importance_reliability_all_states_matches_independent_oracle(population, services):
    graph = roads([(0, 1, 100, 10, True), (1, 2, 100, 10, True)])
    links = identify_links(graph, 'test-reliability-input')
    uniforms = np.array(list(product([.25, .75], repeat=len(links))))
    importance, _, _ = combined_node_importance(population, services, 2)
    expected = independent_exact(graph, links, importance, .5)
    result = compute(graph, population, node_importance=importance, service_weights=services,
        samples=len(uniforms), uniform_samples=uniforms, p0_sweep={'dry': 0}, n_jobs=2)
    original = compute(graph, population, samples=len(uniforms), uniform_samples=uniforms, p0_sweep={'dry': 0})
    for group in ('unweighted', 'population_weighted'):
        assert result.summary[group] == original.summary[group]
    for i, key in enumerate(('connectivity_reliability', 'travel_time_reliability')):
        assert result.summary['node_importance_weighted'][key]['value'] == pytest.approx(expected[i, 1])
        # The dry scenario retains user-provided 0.5 failure probabilities too.
        assert 'node_importance_weighted' in result.summary['scenarios']['dry']
    scaled = compute(graph, population, node_importance=importance * 100,
        samples=len(uniforms), uniform_samples=uniforms)
    for key in ('connectivity_reliability', 'travel_time_reliability'):
        assert scaled.summary['node_importance_weighted'][key]['value'] == pytest.approx(
            result.summary['node_importance_weighted'][key]['value'])


@pytest.mark.parametrize('importance', [[0, 0, 0], [0, 1, 0]])
def test_no_distinct_importance_pairs_are_unavailable(importance):
    graph = path_graph()
    baseline = compute_baseline(graph, [1, 1, 1], node_importance=importance)
    for measure in ('efficiency', 'accessibility', 'reachable_fraction'):
        assert getattr(baseline, measure + '_importance') is None
    result = compute(roads([(0, 1, 100, 10, True)], nodes=[0, 1, 2]),
        node_importance=importance, samples=2)
    for metric in result.summary['node_importance_weighted'].values():
        assert metric['value'] is None and 'importance' in metric['reason']


def test_importance_validation_and_screened_nulls():
    graph = roads([(0, 1, 100, 10, True), (1, 2, 100, 10, True), (2, 0, 100, 10, True)])
    for invalid in ([1, 2], [-1, 2, 3], [1, float('nan'), 3]):
        with pytest.raises(ValueError):
            PairUniverse([1, 1, 1], node_importance=invalid)
    result = compute_local_metrics(graph, [1, 1, 1], node_importance=[.1, .2, .7],
        link_candidate_limit=0, node_candidate_limit=0)
    for row in [*result.nodes.values(), *result.links]:
        assert not row['evaluated']
        assert row['accessibility_drop_importance'] is None
        assert 'not evaluated' in row['null_reasons']['accessibility_drop_importance']


def test_importance_headline_exports_all_components_and_replays(tmp_path):
    from georesilience.pipeline import replay_manifest
    directory, _, _, facilities = service_input(tmp_path)
    output = tmp_path / 'importance'
    assert invoke(service_args(directory, output, facilities, figures=True,
        extra=['--default-view', 'node_importance_weighted'])) == 0
    summary = read_summary(output)
    assert summary['default_view'] == 'node_importance_weighted'
    headline = summary['composite']['node_importance_weighted']
    assert summary['headline'] == headline
    measures = summary['node_importance_weighted']
    assert measures == summary['services']['node_importance_weighted']
    assert headline['components']['accessibility'] == measures['hansen_accessibility']['value']
    for key in ('connectivity_reliability', 'travel_time_reliability'):
        assert headline['components'][key] == measures[key]['value']
    assert headline['components']['attack'] == pytest.approx(
        measures['targeted_attack_robustness']['value'] / summary['attack']['horizon'])
    # This fixture is a tree: no finite detour means the full composite is unavailable.
    assert headline['value'] is None and 'detour' in headline['reason']
    assert headline['components']['bridge'] == summary['unweighted']['bridge_redundancy']['value']
    nodes = gpd.read_file(output / 'network.gpkg', layer='nodes')
    edges = gpd.read_file(output / 'network.gpkg', layer='edges')
    assert {'hansen_accessibility_importance', 'information_centrality_importance',
        'accessibility_drop_importance', 'disconnected_pair_fraction_importance'} <= set(nodes)
    assert {'efficiency_drop_importance', 'accessibility_drop_importance',
        'disconnected_pair_fraction_importance'} <= set(edges)
    assert 'node_importance_weighted' in (output / 'composite.csv').read_text()
    assert 'Node Importance Weighted' in (output / 'report.txt').read_text()
    manifest = json.loads((output / 'run_manifest.json').read_text())
    assert manifest['pair_universe']['normalized_node_importance_pair_mass'] > 0
    replay = replay_manifest(output / 'run_manifest.json', tmp_path / 'replayed')
    assert replay == summary
    # A facility-dependent headline cannot be requested without facility inputs.
    assert invoke(run_args(directory, tmp_path / 'invalid', '--default-view', 'node_importance_weighted')) == 2
