"""Service scenario views reuse the existing event universe and attack order."""

import csv

import networkx as nx
import numpy as np
import pytest

from georesilience.config import TravelTimeConfig
from georesilience.links import _link_rows
from georesilience.reliability import compute_reliability
from georesilience.robustness import compute_targeted_attack, write_curve
from tests.test_sfca import service_fixture


def reliability(graph, population, weights=None, **kwargs):
    return compute_reliability(graph,_link_rows(graph),population,{},connectivity_samples=8,
        travel_time_samples=8,time_config=TravelTimeConfig(time_model='edge_attribute'),
        service_weights=weights,**kwargs)


def test_exact_directed_no_failure_and_certain_closure(tmp_path):
    graph,pop,_,_,_=service_fixture(tmp_path,population=[3,2,1,4],
        edges=[(0,1,10),(1,2,10)],facilities=[(1,'school',5),(2,'hospital',5)])
    weights = np.array([0,1,2,0])
    expected = sum(pop[i]*weights[j] for i in graph for j in graph if nx.has_path(graph,i,j))/(sum(pop)*sum(weights))
    for p0,target in [(0,expected),(1,4/30)]:
        result = reliability(graph,pop,weights,p0=p0)
        metrics = result.summary['service_weighted']
        assert metrics['directed_reachability_reliability']['value'] == pytest.approx(target)
        assert metrics['travel_time_reliability']['value'] == pytest.approx(target)
        assert result.summary['unweighted']['connectivity_reliability']['value'] == 0
        for metric in metrics.values():
            assert 0 <= metric['ci_low'] <= metric['value'] <= metric['ci_high'] <= 1


def test_shared_seed_events_workers_and_p0_sweeps(tmp_path):
    graph,pop,_,_,_=service_fixture(tmp_path,population=[3,2,1,4],
        edges=[(0,1,10),(1,0,10),(1,2,20),(2,1,20),(2,3,30),(3,2,30)])
    options = dict(p0=.7,p0_sweep={'safe':0,'closed':1},seed=19)
    old = reliability(graph,pop,**options)
    serial = reliability(graph,pop,[0,1,2,0],n_jobs=1,budget_bytes=4*64,**options)
    parallel = reliability(graph,pop,[0,1,2,0],n_jobs=3,budget_bytes=4*64*3,**options)
    assert 'service_weighted' not in old.summary
    for scenario in ['primary','safe','closed']:
        for group in ['unweighted','population_weighted']:
            assert old.summary['scenarios'][scenario][group] == serial.summary['scenarios'][scenario][group]
        assert serial.summary['scenarios'][scenario] == parallel.summary['scenarios'][scenario]
    assert serial.summary['scenarios']['safe']['service_weighted']['directed_reachability_reliability']['value'] == pytest.approx(1)
    assert serial.summary['scenarios']['closed']['service_weighted']['directed_reachability_reliability']['value'] == pytest.approx(4/30)
    # Reconstruct exactly the seeded link states and independently sum directed pairs.
    links = sorted(_link_rows(graph),key=lambda r:r['link_id'])
    probability = np.array([1-(1-.7)**(r['length_m']/1000) for r in links])
    expected=[]
    for index in range(8):
        uniform=np.random.default_rng(np.random.SeedSequence([19,index])).random(len(links))
        damaged=graph.copy()
        damaged.remove_edges_from([arc for row,u,p in zip(links,uniform,probability) if u<p for arc in row['_edges']])
        expected.append(sum(pop[i]*[0,1,2,0][j] for i in graph for j in graph if nx.has_path(damaged,i,j))/30)
    assert serial.summary['service_weighted']['directed_reachability_reliability']['value'] == pytest.approx(np.mean(expected))


def test_missing_times_and_zero_original_mass(tmp_path):
    graph,pop,_,_,_=service_fixture(tmp_path)
    result=compute_reliability(graph,_link_rows(graph),pop,{},connectivity_samples=2,travel_time_samples=2,service_weights=[1,0,0,0])
    assert result.summary['service_weighted']['directed_reachability_reliability']['value'] is not None
    assert result.summary['service_weighted']['travel_time_reliability']['value'] is None
    assert 'speed' in result.summary['service_weighted']['travel_time_reliability']['reason']
    for population,weights,reason in [(pop,[0,0,0,0],'service'),([0,0,0,0],[1,0,0,0],'population')]:
        result=reliability(graph,population,weights)
        for metric in result.summary['service_weighted'].values():
            assert metric['value'] is None and reason in metric['reason']


def test_attack_same_order_scc_ties_raw_auc_and_conditional_csv(tmp_path):
    graph,pop,_,_,_=service_fixture(tmp_path,population=[1,2,3,4],
        edges=[(0,1,10),(1,0,10),(2,3,10),(3,2,10)])
    links=_link_rows(graph)
    old=compute_targeted_attack(graph,links,pop,fraction=1,steps=2)
    result=compute_targeted_attack(graph,links,pop,fraction=1,steps=2,service_weights=[0,0,1,3])
    assert result.removal_order == old.removal_order
    assert [{k:v for k,v in r.items() if k!='service_share'} for r in result.curve] == old.curve
    assert result.curve[0]['service_share'] == 0  # node-selected SCC is {0,1}, not service-rich {2,3}
    expected=np.trapezoid([r['service_share'] for r in result.curve],[r['fraction_removed'] for r in result.curve])
    assert result.summary['service_weighted']['value'] == expected
    path=tmp_path/'curve.csv'
    write_curve(result,path)
    assert 'service_share' in next(csv.reader(path.open()))
    write_curve(old,path)
    assert 'service_share' not in next(csv.reader(path.open()))
    zero=compute_targeted_attack(graph,links,pop,fraction=0,service_weights=[0,0,1,3])
    assert zero.summary['service_weighted']['value'] is None
    assert zero.summary['service_weighted']['reason']=='no links removed'
    no_service=compute_targeted_attack(graph,links,pop,fraction=1,service_weights=[0,0,0,0])
    assert no_service.summary['service_weighted']['value'] is None
    assert all(r['service_share'] is None for r in no_service.curve)
