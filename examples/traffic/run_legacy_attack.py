"""Replay the mid-evaluation directed, 20-batch attack without changing core code.

Algorithm recovered from main^ (f144768), robustness.py. Also evaluate current
free-flow/congested costs so the historical attack definition can be held fixed.
"""
import argparse
import json
import math
from pathlib import Path

import networkit as nk
import numpy as np
from scipy.sparse.csgraph import connected_components

from georesilience.links import node_key
from run_metrics_comparison import MODES, cost_topology, load_city
from run_pilot import CITIES, digest, save_csv, save_json


def numerical_rank(scores):
    ordered=sorted(scores,key=lambda item:(-scores[item],item))
    result=[];start=0
    while start<len(ordered):
        end=start+1;score=scores[ordered[start]]
        while end<len(ordered) and math.isclose(score,scores[ordered[end]],rel_tol=1e-12,abs_tol=1e-12):
            end+=1
        result.extend(sorted(ordered[start:end]));start=end
    return result


def directed_scores(topology, matrix, remaining, removed):
    native=nk.Graph(matrix.shape[0],weighted=True,directed=True)
    for u in range(matrix.shape[0]):
        for offset in range(matrix.indptr[u],matrix.indptr[u+1]):
            native.addEdge(u,int(matrix.indices[offset]),float(matrix.data[offset]))
    native.indexEdges()
    values=nk.centrality.Betweenness(native,normalized=False,computeEdgeCentrality=True).run().edgeScores()
    selected={}
    for u,v,cost,link in zip(topology.rows,topology.cols,topology.lengths,topology.link_ids):
        if link in removed:continue
        pair=(int(u),int(v));candidate=(float(cost),int(link))
        if pair not in selected or candidate<selected[pair]:selected[pair]=candidate
    scores=dict.fromkeys(remaining,0.)
    for (u,v),(_,link) in selected.items():
        scores[link]=max(scores[link],float(values[native.edgeId(u,v)]))
    return scores


def legacy_attack(graph,links,population,costs,steps=20,fraction=.2):
    topology=cost_topology(graph,links,costs)
    active={r['link_id'] for r in links if not r['is_self_loop']}
    count=len(active);budget=math.floor(count*fraction+1e-12)
    if count and budget/count>fraction:budget-=1
    schedule=np.rint(np.arange(steps+1)*budget/steps).astype(int)
    removed=set();curve=[];history=[]
    current=topology.csr()
    for step,total_removed in enumerate(schedule):
        delta=int(total_removed-(schedule[step-1] if step else 0))
        if delta:
            batch=numerical_rank(directed_scores(topology,current,active,removed))[:delta]
            active.difference_update(batch);removed.update(batch);history.extend(batch)
            current=topology.csr(removed_links=removed)
        _,labels=connected_components(current,directed=True,connection='strong')
        components=[np.flatnonzero(labels==label) for label in np.unique(labels)]
        selected=min(components,key=lambda ids:(-len(ids),tuple(sorted(node_key(topology.node_ids[i]) for i in ids))))
        curve.append(dict(fraction_removed=float(total_removed/count),links_removed=int(total_removed),
                          node_share=len(selected)/len(graph),population_share=float(population[selected].sum()/population.sum())))
    normalized={}
    for field in ('node_share','population_share'):
        x=[r['fraction_removed'] for r in curve]+[fraction]
        y=[r[field] for r in curve]+[curve[-1][field]]
        normalized[field]=float(np.trapezoid(y,x)/fraction)
    return dict(normalized_auc=normalized,curve=curve,removal_order=history,
                method='mid-evaluation: directed weighted max-arc betweenness; adaptive 20 batches; normalized AUC to requested 0.2',
                requested_horizon=fraction,actual_horizon=budget/count)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',type=Path,default=Path('data/traffic_comparison'))
    parser.add_argument('--traffic',type=Path,default=Path('results/traffic_comparison'))
    parser.add_argument('--output',type=Path,default=Path('results/traffic_metrics'))
    parser.add_argument('--cities',nargs='+',choices=CITIES,default=CITIES)
    args=parser.parse_args();args.stage='legacy_attack'
    nk.setNumberOfThreads(2)
    save_json(args.output/'manifest_legacy_attack.json',dict(script_sha256=digest(Path(__file__)),
        helper_sha256=digest(Path(__file__).with_name('run_metrics_comparison.py')),
        historical_source_commit='f144768',note='Recovered original directed attack schedule and numerical tie rules'))
    for city in args.cities:
        graph,links,population,costs,_=load_city(city,args)
        # Old IDs followed graph insertion order; current IDs are canonical.
        # Restore the archived IDs to preserve the original numerical tie break.
        import geopandas as gpd
        old=gpd.read_file(args.inputs/'results'/f'{city}-population'/'network.gpkg',layer='edges')
        def identity(u,v,ways,length):
            return (frozenset((str(u),str(v))),str(ways),round(float(length),1))
        mapping={identity(r.u,r.v,r.osm_way_ids,r.length_m):int(r.link_id) for _,r in old.iterrows()}
        if len(mapping)!=len(old):raise ValueError('Ambiguous archived physical road identity')
        links=[{**r,'link_id':mapping[identity(r['u'],r['v'],r['osm_way_ids'],r['length_m'])]}
               for r in links if not r['is_self_loop']]
        if len({r['link_id'] for r in links})!=len(links):raise ValueError('Legacy road mapping is not one to one')
        for mode in MODES:
            result=legacy_attack(graph,links,population,costs[mode])
            if mode=='distance':
                historical=json.loads((args.inputs/'results'/f'{city}-population'/'summary.json').read_text())
                expected=historical['metrics']['robustness']['links']['auc_attack_S']
                result['historical_distance_auc']=expected
                result['historical_replay_difference']=result['normalized_auc']['node_share']-expected
                if abs(result['historical_replay_difference'])>1e-9:
                    raise ValueError(f'{city}: historical attack replay differs: {result["historical_replay_difference"]}')
            save_json(args.output/city/mode/'legacy_attack.json',result)
            save_csv(args.output/city/mode/'legacy_attack_curve.csv',result['curve'])
            print(city,mode,result['normalized_auc'],flush=True)


if __name__=='__main__':main()
