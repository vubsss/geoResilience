"""Audit actual traffic assignment and compare two explicit reliability references.

Adds a pilot with demand reassigned after physical-road failures. Preserves all
previous outputs, composite coefficients, input assumptions and metric definitions.
"""
import argparse
import json
import math
import os
import time
from pathlib import Path

os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','2')

import networkx as nx
import numpy as np
from scipy.sparse.csgraph import dijkstra

from georesilience.failure_probabilities import probabilities_at_p0
from georesilience.links import _link_rows
from georesilience.metrics import PairUniverse
from georesilience.reliability import _connectivity, _time_success
from georesilience.traffic import assign_traffic
from georesilience.traffic import _tag_number
from georesilience.time_models import FreeFlowTimeModel, _parsed_speed
from georesilience.config import TravelTimeConfig
from run_metrics_comparison import cost_topology, read_csv, snapshot, structural_scores
from run_pilot import CASES, CITIES, SPEEDS, digest, prepare_city, run_case, save_csv, save_json

# Predeclared policy sensitivity; 1.5 is the old project's primary 50% allowance.
FACTORS=(1.2,1.5,2.0)


def canonical_input_graph(graph):
    """Resolve simplified-path tag lists without relying on set iteration order.

    Minimum lane count is a bottleneck approximation. For mixed speed/road-class
    segments, the slowest usable tag/fallback is a conservative approximation;
    segment-specific lengths would be needed to reconstruct actual travel time.
    """
    result=graph.copy();changes=[]
    for u,v,k,data in result.edges(keys=True,data=True):
        for field in ('lanes','width','maxspeed','highway'):
            raw=data.get(field)
            if not isinstance(raw,(list,tuple,set)):continue
            if field=='highway':
                value=min(map(str,raw),key=lambda tag:(SPEEDS.get(tag,20),tag)) if raw else 'unclassified'
            elif field=='maxspeed':
                usable=[_parsed_speed(x) for x in raw]
                usable=[x for x in usable if x is not None and x>0]
                value=str(min(usable)) if usable else None
            else:
                usable=[]
                for item in raw:
                    number=_tag_number(item)
                    if number is None or not math.isfinite(number) or number<=0:continue
                    if field=='width' and any(unit in str(item).lower() for unit in ('ft','feet',"'")):
                        number*=.3048
                    usable.append(number)
                value=min(usable) if usable else None
            changes.append(dict(u=str(u),v=str(v),key=str(k),field=field,
                                original_values=json.dumps(sorted(map(str,raw))),resolved=value))
            if value is None:data.pop(field,None)
            else:data[field]=value
    return result,changes


def service_scores(event,free_reference,intact_congested,population,demands,factors=FACTORS):
    """Same observed/simulated event times, two different explicit questions."""
    universe=PairUniverse(population)
    n=universe.n
    output={}
    for reference_name,reference in [('free_flow',free_reference),('intact_congested',intact_congested)]:
        for factor in factors:
            success=_time_success(reference,event,factor-1)
            np.fill_diagonal(success,False)
            prefix=f'{reference_name}_{factor:g}'
            output[prefix+'_unweighted']=float(success.sum()/universe.denominator)
            output[prefix+'_population']=float(universe.weights @ (success @ universe.weights)/universe.denominator_pop)
            output[prefix+'_demand']=float(sum(amount*success[i,j] for (i,j),amount in demands.items())/sum(demands.values()))
    return output


def audit_arcs(graph,rows,demand):
    index={(str(u),str(v),str(k)):(u,v,k) for u,v,k in graph.edges(keys=True) if u!=v}
    costs={};capacities={};flows={};free={}
    errors=[]
    for row in rows:
        edge=index[row['u'],row['v'],row['key']]
        base=float(row['free_flow_time_s']);cap=float(row['capacity_pcu_h']);flow=float(row['assigned_volume_pcu_h'])
        actual=float(row['congested_time_s'])
        expected=base*(1+.15*(flow/cap)**4)
        if not all(math.isfinite(x) for x in (base,cap,flow,actual)) or min(base,cap,actual)<=0 or flow<0:
            raise ValueError('Invalid assignment arc')
        errors.append(abs(actual-expected)/max(expected,1))
        costs[edge]=actual;capacities[edge]=cap;flows[edge]=flow;free[edge]=base
    if set(costs)!=set(index.values()) or len(rows)!=len(index):raise ValueError('Arc coverage mismatch')
    balance=dict.fromkeys(graph,0.)
    for (u,v,_),flow in flows.items():balance[u]+=flow;balance[v]-=flow
    for (u,v),amount in demand.items():balance[u]-=amount;balance[v]+=amount
    if max(errors)>1e-12 or max(map(abs,balance.values()))>1e-6:
        raise ValueError('BPR or flow conservation audit failed')
    return costs,capacities,free,dict(max_relative_bpr_error=max(errors),
        max_flow_residual_pcu_h=max(map(abs,balance.values())),
        arcs=len(rows),positive_flow_arcs=sum(v>0 for v in flows.values()),
        congested_arcs=sum(costs[e]>free[e]+1e-9 for e in costs),
        demand_pcu_h=sum(demand.values()))


def failed_state(graph,links,closed,population,demand,free,capacities,max_iterations=600):
    """Keep original trip denominators; unserved OD trips are reported explicitly."""
    damaged=graph.copy()
    damaged.remove_edges_from(e for row in links if row['link_id'] in closed for e in row['_edges'])
    reachable={u:nx.descendants(damaged,u) for u in {u for u,_ in demand}}
    served={pair:value for pair,value in demand.items() if pair[1] in reachable[pair[0]]}
    lost=math.fsum(value for pair,value in demand.items() if pair not in served)
    remaining={(u,v,k) for u,v,k in damaged.edges(keys=True) if u!=v}
    metrics={};summary=dict(status='converged',relative_gap=0.,iterations=0)
    if served:
        metrics,summary=assign_traffic(damaged,{e:free[e] for e in remaining},
            {e:capacities[e] for e in remaining},served,relative_gap=1e-3,max_iterations=max_iterations)
        if summary['status']!='converged':
            metrics,summary=assign_traffic(damaged,{e:free[e] for e in remaining},
                {e:capacities[e] for e in remaining},served,relative_gap=1e-3,max_iterations=2000)
    times={e:metrics[e]['congested_time_s'] if metrics else free[e] for e in remaining}
    active=[r for r in links if r['link_id'] not in closed]
    topology=cost_topology(damaged,active,times)
    matrix=topology.csr()
    return dijkstra(matrix,directed=True),summary,lost,matrix


def run_city(city,args):
    start=time.perf_counter()
    graph,masses,_,input_audit=prepare_city(city,args.inputs,args.output/'inputs')
    population=np.array([masses[n] for n in graph])
    links=_link_rows(graph)
    native={(str(u),str(v),str(k)):(u,v,k) for u,v,k in graph.edges(keys=True) if u!=v}
    old_dir=args.traffic/city/'base'
    previous=read_csv(old_dir/'traffic_arcs.csv')
    free={native[r['u'],r['v'],r['key']]:float(r['free_flow_time_s']) for r in previous}
    demand_nodes={str(n):n for n in graph}
    old_demand={(demand_nodes[r['origin']],demand_nodes[r['destination']]):float(r['demand_pcu_h'])
                for r in read_csv(old_dir/'input_od.csv')}
    old_cost,old_cap,_,old_audit=audit_arcs(graph,previous,old_demand)
    replay,_=assign_traffic(graph,free,old_cap,old_demand,relative_gap=1e-3,max_iterations=600)
    old_audit['max_cost_change_using_frozen_inputs_s']=max(abs(replay[e]['congested_time_s']-old_cost[e]) for e in old_cost)
    if old_audit['max_cost_change_using_frozen_inputs_s']>1e-8:raise ValueError('Serialized-input solver replay failed')
    save_json(args.output/city/'previous_assignment_audit.json',old_audit)
    # Fresh deterministic input preparation, with the same rate/capacity defaults.
    graph,tag_changes=canonical_input_graph(graph)
    if tag_changes:save_csv(args.output/city/'resolved_tags.csv',tag_changes)
    free_prepared=FreeFlowTimeModel().prepare(graph,TravelTimeConfig(highway_speeds_kph=SPEEDS))
    free=free_prepared.edge_seconds
    run_case(city,CASES[0],graph,masses,free,args.output/'fresh_assignment',600,1e-3)
    folder=args.output/'fresh_assignment'/city/'base'
    demand={(demand_nodes[r['origin']],demand_nodes[r['destination']]):float(r['demand_pcu_h'])
            for r in read_csv(folder/'input_od.csv')}
    traffic,capacities,free,audit=audit_arcs(graph,read_csv(folder/'traffic_arcs.csv'),demand)
    previous_map={native[r['u'],r['v'],r['key']]:float(r['congested_time_s']) for r in previous}
    audit['max_cost_change_after_tag_resolution_s']=max(abs(traffic[e]-previous_map[e]) for e in traffic)
    audit['resolved_tag_fields']=len(tag_changes)
    save_json(args.output/city/'free_flow_provenance.json',free_prepared.summary)
    universe=PairUniverse(population)
    index={n:i for i,n in enumerate(graph)}
    demand_indices={(index[u],index[v]):value for (u,v),value in demand.items()}
    ff_topology=cost_topology(graph,links,free)
    c_topology=cost_topology(graph,links,traffic)
    ff_dist=dijkstra(ff_topology.csr(),directed=True)
    c_dist=dijkstra(c_topology.csr(),directed=True)
    intact=service_scores(c_dist,ff_dist,c_dist,population,demand_indices)
    hff=snapshot(ff_topology,population,360);hc=snapshot(c_topology,population,360)
    bf,ef=structural_scores(graph,links,free);bc,ec=structural_scores(graph,links,traffic)
    audit.update(hansen_free_flow=hff.accessibility,hansen_congested=hc.accessibility,
        hansen_population_free_flow=hff.accessibility_pop,hansen_population_congested=hc.accessibility_pop,
        nodes_with_changed_time_betweenness=sum(abs(bf[n]-bc[n])>1e-12 for n in graph),
        roads_with_changed_time_betweenness=sum(abs(ef[k]-ec[k])>1e-12 for k in ef if ef[k] is not None),
        fresh_traffic_sha256=digest(folder/'traffic_arcs.csv'),previous_traffic_sha256=digest(old_dir/'traffic_arcs.csv'),
        graph_sha256=input_audit['graph_sha256'],population_sha256=input_audit['population_gpkg_sha256'])
    save_json(args.output/city/'assignment_audit.json',audit)
    save_json(args.output/city/'intact_service.json',intact)
    print(city,'INTACT SERVICE',json.dumps(intact),flush=True)
    # Additional independent convergence check; never changes the primary scenario.
    strict,strict_summary=assign_traffic(graph,free,capacities,demand,relative_gap=1e-4,max_iterations=2000)
    strict_cost={e:r['congested_time_s'] for e,r in strict.items()}
    strict_h=snapshot(cost_topology(graph,links,strict_cost),population,360)
    save_json(args.output/city/'strict_solver_check.json',dict(summary=strict_summary,
        hansen_strict=strict_h.accessibility,hansen_primary=hc.accessibility,
        note='Numerical accuracy check only; no demand/capacity adjustment'))
    if strict_summary['status']!='converged':raise ValueError('Stricter convergence audit failed')
    active=sorted((r for r in links if not r['is_self_loop']),key=lambda r:r['link_id'])
    probabilities=probabilities_at_p0(active,{},.01)
    save_csv(args.output/city/'event_probabilities.csv',[dict(link_id=r['link_id'],link_uid=r['link_uid'],
        physical_length_m=r['length_m'],p_fail=probabilities[r['link_id']]) for r in active])
    cache={};events=[]
    for sample in range(args.samples):
        uniforms=np.random.default_rng(np.random.SeedSequence([42,sample])).random(len(active))
        closed=tuple(r['link_id'] for r,value in zip(active,uniforms) if value<probabilities[r['link_id']])
        if not closed:
            scores=intact
            state=dict(status='converged',relative_gap=0.,iterations=0)
            lost=0.;conn=_connectivity(c_topology.csr(),universe)[0]
        elif closed in cache:
            scores,state,lost,conn=cache[closed]
        else:
            distances,state,lost,matrix=failed_state(graph,links,set(closed),population,demand,free,capacities)
            scores=service_scores(distances,ff_dist,c_dist,population,demand_indices)
            conn=_connectivity(matrix,universe)[0]
            cache[closed]=(scores,state,lost,conn)
        row=dict(sample=sample,closed_physical_links=json.dumps(closed),closed_count=len(closed),
            status=state['status'],relative_gap=state['relative_gap'],iterations=state['iterations'],
            unserved_demand_pcu_h=lost,connectivity_unweighted=conn[0],connectivity_population=conn[1],**scores)
        events.append(row)
        save_csv(args.output/city/'events.csv',events)
        print(city,'event',sample+1,'/',args.samples,'closures',len(closed),'status',state['status'],flush=True)
    valid=[r for r in events if r['status']=='converged']
    unknown=len(events)-len(valid)
    keys=[*intact,'connectivity_unweighted','connectivity_population']
    summary=dict(city=city,samples=args.samples,converged_samples=len(valid),unconverged_samples=unknown,
        unique_damaged_assignments=len(cache),intact_service=intact,
        event_service={key:dict(value=float(np.mean([r[key] for r in valid])) if not unknown else None,
            lower_missing_state_bound=sum(r[key] for r in valid)/args.samples,
            upper_missing_state_bound=(sum(r[key] for r in valid)+unknown)/args.samples) for key in keys},
        interval_half_width_hoeffding_95=math.sqrt(math.log(40)/(2*args.samples)),
        mean_unserved_demand_pcu_h=float(np.mean([r['unserved_demand_pcu_h'] for r in events])),
        elapsed_seconds=time.perf_counter()-start,
        definitions=dict(free_flow='on-time service relative to fixed intact free-flow times',
            intact_congested='disruption-only reliability relative to intact congested times',
            demand='OD-demand-weighted trips, including unserved trips in the denominator',
            population='original ordered-pair population products',
            unweighted='all original distinct ordered node pairs'))
    save_json(args.output/city/'service_summary.json',summary)
    print(city,'COMPLETE',time.perf_counter()-start,flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,default=64)
    parser.add_argument('--inputs',type=Path,default=Path('data/traffic_comparison'))
    parser.add_argument('--traffic',type=Path,default=Path('results/traffic_comparison'))
    parser.add_argument('--output',type=Path,default=Path('results/traffic_validation_v2'))
    args=parser.parse_args()
    if args.samples<2:raise ValueError('Need at least two independent event samples')
    if args.output.exists() and any(args.output.iterdir()):raise ValueError('Choose a fresh output directory')
    args.output.mkdir(parents=True)
    save_json(args.output/'experiment.json',dict(script_sha256=digest(Path(__file__)),seed=42,
        samples=args.samples,primary_factor=1.5,policy_factors=FACTORS,
        base_rate_pcu_person_h=.1,lane_capacity_pcu_h=1000,default_directional_lanes=1,
        base_solver_gap=.001,strict_solver_gap=.0001,
        design='Both areas, unchanged base assumptions, fresh assignment, two explicit reference metrics, reroute/reassign after road failures',
        tag_policy='Minimum positive lane/width value over simplified path; slowest tagged/fallback speed on ambiguous lists; same rules in both areas',
        limitations=['Synthetic resident OD; no measured traffic calibration.',
          'Sparse lane data and clipped boundaries remain unresolved.',
          'Static assignment cannot represent queues/signals/daily observations.',
          '64 failure states are a pilot, not high-precision reliability estimates.',
          'Reference changes define a different service measure, not a correction to the original disruption-only formula.']))
    for city in CITIES:run_city(city,args)


if __name__=='__main__':main()
