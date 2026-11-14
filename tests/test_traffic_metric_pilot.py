"""Known-answer checks for the isolated time-cost comparison adapter."""
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import pytest

pytest.importorskip('networkit',reason='optional accelerated traffic metric pilot dependency')

sys.path.insert(0, str(Path(__file__).parents[1] / "examples" / "traffic"))
from run_metrics_comparison import cost_topology, detours, snapshot, structural_scores, attack
from run_legacy_attack import legacy_attack, numerical_rank
from validate_traffic_service import service_scores, failed_state, audit_arcs, canonical_input_graph
from georesilience.links import _link_rows
from georesilience.metrics import _structural
from georesilience.robustness import compute_targeted_attack


def roads(pairs):
    graph=nx.MultiDiGraph()
    for way,(u,v,length) in enumerate(pairs,1):
        for node in (u,v):
            graph.add_node(node,x=100*node,y=0)
        for a,b in ((u,v),(v,u)):
            graph.add_edge(a,b,key=0,length=length,osmid=way)
    return graph


def test_asymmetric_costs_preserve_one_physical_road_and_half_time_units():
    graph=roads([(0,1,2000)])
    links=_link_rows(graph)
    costs={(0,1,0):360.,(1,0,0):720.}
    topology=cost_topology(graph,links,costs)
    assert len(links)==1
    assert len(set(topology.link_ids))==1
    result=snapshot(topology,[2,7],360)
    np.testing.assert_allclose(result.node_hansen,[.5,.25])
    assert result.accessibility==pytest.approx(.375)
    assert result.accessibility_pop==pytest.approx((2*.5+7*.25)/9)
    assert graph[0][1][0]['length']==2000
    assert links[0]['length_m']==2000
    removed=topology.csr(removed_links=[links[0]['link_id']])
    assert removed.nnz==0


def test_accelerated_betweenness_matches_current_physical_graph_convention():
    graph=roads([(0,1,10),(1,2,15),(0,2,50),(2,3,5)])
    links=_link_rows(graph)
    costs={(u,v,k):d['length'] for u,v,k,d in graph.edges(keys=True,data=True)}
    nodes,edges=structural_scores(graph,links,costs)
    expected_nodes,expected_edges,_,_=_structural(graph,links)
    assert nodes==pytest.approx(expected_nodes,abs=1e-12)
    assert edges==pytest.approx(expected_edges,abs=1e-12)


def test_detours_use_each_original_direction_cost_not_mean_direction_denominator():
    graph=roads([(0,1,10),(0,2,20),(2,1,20)])
    links=_link_rows(graph)
    costs={(u,v,k):float(d['length']) for u,v,k,d in graph.edges(keys=True,data=True)}
    costs[1,0,0]=40
    topology=cost_topology(graph,links,costs)
    values=detours(topology,links,costs)
    selected=next(r for r in links if {r['_u'],r['_v']}=={0,1})
    assert values[selected['link_id']]==(4.,False)


def test_adaptive_attack_matches_current_core_on_known_graph():
    graph=roads([(0,1,100),(1,2,100),(2,3,100)])
    links=_link_rows(graph)
    costs={(u,v,k):d['length'] for u,v,k,d in graph.edges(keys=True,data=True)}
    population=[1,2,3,4]
    actual=attack(graph,links,population,costs,fraction=.67,steps=2)
    expected=compute_targeted_attack(graph,links,population,fraction=.67,steps=2)
    assert actual['removal_order']==expected.removal_order
    assert actual['raw_auc']['node_share']==pytest.approx(expected.summary['unweighted']['value'])
    assert actual['raw_auc']['population_share']==pytest.approx(expected.summary['population_weighted']['value'])


def test_legacy_attack_retains_requested_horizon_and_directed_batch_schedule():
    graph=roads([(0,1,100),(1,2,100),(2,3,100)])
    links=_link_rows(graph)
    costs={(u,v,k):d['length'] for u,v,k,d in graph.edges(keys=True,data=True)}
    actual=legacy_attack(graph,links,np.array([1.,2.,3.,4.]),costs,steps=2,fraction=.67)
    assert [r['links_removed'] for r in actual['curve']]==[0,1,2]
    assert [r['node_share'] for r in actual['curve']]==[1,.5,.5]
    expected=(.25+1/6+(.67-2/3)*.5)/.67
    assert actual['normalized_auc']['node_share']==pytest.approx(expected)


def test_legacy_numerical_ties_use_original_physical_ids():
    assert numerical_rank({10:2+1e-13,2:2,3:1})==[2,10,3]


def test_common_free_flow_budget_detects_congestion_hidden_by_own_reference():
    free=np.array([[0.,10.],[10.,0.]])
    congested=np.array([[0.,30.],[30.,0.]])
    values=service_scores(congested,free,congested,[2,7],{(0,1):100.},factors=(1.5,))
    for weighting in ['unweighted','population','demand']:
        assert values['free_flow_1.5_'+weighting]==0
        assert values['intact_congested_1.5_'+weighting]==1


def test_closure_reassigns_flows_and_recomputes_congestion_on_alternative():
    graph=roads([(0,1,100),(0,2,100),(2,1,100)])
    links=_link_rows(graph)
    closed=next(r['link_id'] for r in links if {r['_u'],r['_v']}=={0,1})
    free={edge:60. for edge in graph.edges(keys=True)}
    capacities={edge:100. for edge in free}
    distances,summary,lost,_=failed_state(graph,links,{closed},[1,1,1],{(0,1):100.},free,capacities)
    assert summary['status']=='converged'
    assert lost==0
    assert distances[0,1]==pytest.approx(138.)


def test_unserved_trips_remain_in_service_denominator():
    graph=roads([(0,1,100),(1,2,100)])
    links=_link_rows(graph)
    closed=next(r['link_id'] for r in links if {r['_u'],r['_v']}=={0,1})
    free={edge:60. for edge in graph.edges(keys=True)}
    distances,_,lost,_=failed_state(graph,links,{closed},[1,1,1],{(0,1):100.},free,{e:100. for e in free})
    assert lost==100
    reference=np.ones((3,3))*60;np.fill_diagonal(reference,0)
    values=service_scores(distances,reference,reference,[1,1,1],{(0,1):100.},factors=(1.5,))
    assert values['free_flow_1.5_demand']==0


def test_assignment_audit_rejects_unchanged_free_flow_cost_at_positive_loading():
    graph=roads([(0,1,100)])
    rows=[dict(u='0',v='1',key='0',free_flow_time_s=10,capacity_pcu_h=10,
               assigned_volume_pcu_h=10,congested_time_s=10),
          dict(u='1',v='0',key='0',free_flow_time_s=10,capacity_pcu_h=10,
               assigned_volume_pcu_h=0,congested_time_s=10)]
    with pytest.raises(ValueError,match='BPR'):
        audit_arcs(graph,rows,{(0,1):10})


def test_ambiguous_simplified_tags_are_order_independent_and_preserve_roads():
    graph=roads([(0,1,100)])
    for u,v,k in graph.edges(keys=True):
        graph[u][v][k].update(lanes=['3','2'],maxspeed=['40','20'],highway=['residential','living_street'])
    fixed,_=canonical_input_graph(graph)
    for u,v,k in graph.edges(keys=True):
        graph[u][v][k]['lanes'].reverse()
        graph[u][v][k]['maxspeed'].reverse()
        graph[u][v][k]['highway'].reverse()
    again,_=canonical_input_graph(graph)
    assert fixed[0][1][0]['lanes']==again[0][1][0]['lanes']==2
    assert fixed[0][1][0]['maxspeed']==again[0][1][0]['maxspeed']=='20.0'
    assert fixed[0][1][0]['highway']==again[0][1][0]['highway']=='living_street'
    assert {r['link_uid'] for r in _link_rows(fixed)}=={r['link_uid'] for r in _link_rows(graph)}
