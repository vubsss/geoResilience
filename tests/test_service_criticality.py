"""Independent closure, redistribution, screening and ranking acceptance checks."""

import numpy as np
import pytest

from georesilience.metrics import compute_local_metrics
from georesilience.service_criticality import access_consequences, compute_service_criticality
from georesilience.services import service_node_weights
from georesilience.sfca import compute_sfca
from tests.test_sfca import brute_force, service_fixture


def test_competition_gains_do_not_cancel_shortfall(tmp_path):
    graph, pop, config, prepared, routing = service_fixture(tmp_path)
    config.hospital.importance = 0
    local = compute_local_metrics(graph, pop, coverage='all')
    result = compute_service_criticality(local, prepared, pop, config, routing)
    link = next(row for row in local.links if (0, 2) in [(u,v) for u,v,k in row['_edges']])
    baseline = compute_sfca(prepared, pop, config, routing)
    damaged = compute_sfca(prepared, pop, config, routing, removed_links=[link['link_id']])
    a, b = baseline.categories['school'], damaged.categories['school']
    assert b.node_access[1] > a.node_access[1]
    assert b.summary['population_mean'] == a.summary['population_mean']
    assert pop @ b.node_access == pytest.approx(2)
    assert result.links[link['link_id']]['school_access_shortfall'] == pytest.approx(.25)
    assert result.links[link['link_id']]['school_population_mean_change'] == pytest.approx(0)
    assert result.links[link['link_id']]['school_newly_unserved_population_share'] == .5
    assert result.links[link['link_id']]['service_combined_shortfall'] == pytest.approx(.25)


def test_every_closure_matches_full_independent_oracle_and_rankings(tmp_path):
    graph, pop, config, prepared, routing = service_fixture(tmp_path,
        facilities=[(2, 'school', 2), (3, 'school', 3), (2, 'hospital', 5)])
    local = compute_local_metrics(graph, pop, coverage='all')
    result = compute_service_criticality(local, prepared, pop, config, routing)
    for scope, items in [('nodes', list(local.nodes.items())),
            ('links', [(r['link_id'], r) for r in local.links])]:
        expected_ranks = {c: [] for c in ['school', 'hospital']}
        for identifier, row in items:
            removed = row['_edges'] if scope == 'links' else ()
            isolated = (identifier,) if scope == 'nodes' else ()
            for category in ['school', 'hospital']:
                a, _, _ = brute_force(graph, pop, prepared.facilities, category)
                b, _, _ = brute_force(graph, pop, prepared.facilities, category, removed=removed, isolated=isolated)
                loss = sum(p*max(x-y, 0) for p,x,y in zip(pop,a,b))/sum(p*x for p,x in zip(pop,a))
                assert row[f'{category}_access_shortfall'] == pytest.approx(loss)
                assert 0 <= row[f'{category}_access_shortfall'] <= 1
                assert row[f'{category}_population_mean_change'] == pytest.approx(pop @ (b-a)/pop.sum())
                expected_ranks[category].append((row.get('link_uid', str(identifier)), loss))
        for category in ['school', 'hospital']:
            ranking = result.summary['rankings'][scope][category]
            assert {r['id']: r['access_shortfall'] for r in ranking} == pytest.approx(dict(expected_ranks[category]))
            assert [r['access_shortfall'] for r in ranking] == sorted([v for _,v in expected_ranks[category]], reverse=True)


def test_node_closure_disables_all_colocated_supply_and_demand_but_link_does_not(tmp_path):
    _, pop, config, prepared, routing = service_fixture(tmp_path, population=[2, 3],
        edges=[(0,1,20), (1,0,20)], facilities=[(1,'school',5), (1,'school',10), (1,'hospital',30)])
    baseline = compute_sfca(prepared, pop, config, routing)
    road = compute_sfca(prepared, pop, config, routing, removed_links=routing.topology.ids)
    failed = compute_sfca(prepared, pop, config, routing, isolated_nodes=(1,))
    for category in ('school', 'hospital'):
        assert road.categories[category].node_access[1] > 0
        assert road.categories[category].node_access[0] == 0
        np.testing.assert_array_equal(failed.categories[category].node_access, [0,0])
        assert all(r['available_capacity'] == 0 for r in failed.categories[category].facilities)
    values, reasons = access_consequences(baseline, failed, pop, config)
    assert values['service_combined_shortfall'] == 1
    assert values['school_newly_unserved_population_share'] == 1
    assert not reasons
    assert pop.sum() == 5
    assert [f.node_index for f in prepared.facilities] == [1,1,1]


def triangle_fixture(tmp_path):
    return service_fixture(tmp_path, population=[1,1,1],
        edges=[(0,1,10),(1,0,10),(0,2,10),(2,0,10),(1,2,10),(2,1,10)], facilities=[(0,'school',10)])


def test_shared_screened_candidates_exact_ids_unevaluated_nulls_and_all_mode(tmp_path):
    graph, pop, config, prepared, routing = triangle_fixture(tmp_path)
    original = compute_local_metrics(graph,pop,coverage='screened',node_candidate_limit=0,link_candidate_limit=0)
    assert original.coverage['nodes']['evaluated'] == original.coverage['links']['evaluated'] == 0
    weights = service_node_weights(prepared,config)
    service_nodes = [node for node,weight in zip(graph,weights) if weight > 0]
    local = compute_local_metrics(graph,pop,coverage='screened',node_candidate_limit=0,
        link_candidate_limit=0,service_nodes=service_nodes)
    assert local.coverage['nodes']['ids'] == ['0']
    incident = {r['link_uid'] for r in local.links if r['_u']==0 or r['_v']==0}
    assert set(local.coverage['links']['ids']) == incident
    compute_service_criticality(local,prepared,pop,config,routing)
    for row in [*local.nodes.values(), *local.links]:
        assert row['service_evaluated'] == row['evaluated']
        if not row['evaluated']:
            assert row['school_access_shortfall'] is None
            assert 'not evaluated' in row['service_null_reasons']['school_access_shortfall']
    all_local = compute_local_metrics(graph,pop,coverage='all',service_nodes=service_nodes)
    assert all_local.coverage['nodes']['evaluated'] == 3
    assert all_local.coverage['links']['evaluated'] == 3


def test_zero_baseline_and_incomplete_combined_score(tmp_path):
    graph, pop, config, prepared, routing = service_fixture(tmp_path, facilities=[(2,'school',0)])
    local = compute_local_metrics(graph,pop,coverage='all')
    result = compute_service_criticality(local,prepared,pop,config,routing)
    for row in result.nodes.values():
        assert row['school_access_shortfall'] is None
        assert 'zero baseline' in row['service_null_reasons']['school_access_shortfall']
        assert row['service_combined_shortfall'] is None
        assert row['school_newly_unserved_population_share'] == 0
    _, pop, config, prepared, routing = service_fixture(tmp_path)
    baseline = compute_sfca(prepared,pop,config,routing)
    values,reasons = access_consequences(baseline,baseline,pop,config)
    assert values['school_access_shortfall'] == 0
    assert values['service_combined_shortfall'] is None
    assert 'hospital' in reasons['service_combined_shortfall']
