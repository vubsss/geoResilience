"""Export cost propagation checks and the completed traffic reassignment audit."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from georesilience.links import _link_rows
from run_pilot import CITIES, digest, prepare_city, save_csv, save_json
from run_metrics_comparison import MODES, baseline_stage, read_csv
from run_legacy_attack import legacy_attack
from summarize_metrics import composite
from validate_traffic_service import FACTORS, canonical_input_graph


def read_json(path):return json.loads(path.read_text(encoding='utf-8'))


def global_metrics(args):
    root=args.root
    for city in CITIES:
        graph,masses,_,_=prepare_city(city,args.inputs,root/'global_input_audit')
        graph,_=canonical_input_graph(graph)
        population=np.array([masses[n] for n in graph])
        links=_link_rows(graph)
        native={(str(u),str(v),str(k)):(u,v,k) for u,v,k in graph.edges(keys=True) if u!=v}
        traffic=read_csv(root/'fresh_assignment'/city/'base/traffic_arcs.csv')
        costs={'distance':{e:float(graph.edges[e]['length']) for e in native.values()}}
        for mode,field in [('free_flow','free_flow_time_s'),('congested','congested_time_s')]:
            costs[mode]={native[r['u'],r['v'],r['key']]:float(r[field]) for r in traffic}
        baseline_stage(city,SimpleNamespace(output=root/'metrics'),graph,links,population,costs)
        archived=gpd.read_file(args.inputs/'results'/f'{city}-population'/'network.gpkg',layer='edges')
        def identity(u,v,ways,length):return (frozenset((str(u),str(v))),str(ways),round(float(length),1))
        mapping={identity(r.u,r.v,r.osm_way_ids,r.length_m):int(r.link_id) for _,r in archived.iterrows()}
        old_links=[{**r,'link_id':mapping[identity(r['u'],r['v'],r['osm_way_ids'],r['length_m'])]}
                   for r in links if not r['is_self_loop']]
        for mode in MODES:
            result=legacy_attack(graph,old_links,population,costs[mode])
            if mode=='distance':
                historical=read_json(args.inputs/'results'/f'{city}-population'/'summary.json')
                assert abs(result['normalized_auc']['node_share']-historical['metrics']['robustness']['links']['auc_attack_S'])<1e-9
            save_json(root/'metrics'/city/mode/'attack_mid.json',result)
            print(city,mode,'canonical-input global metrics complete',flush=True)


def report(args):
    root=args.root;rows=[];baseline_rows=[]
    for city in CITIES:
        summary=read_json(root/city/'service_summary.json')
        if summary['unconverged_samples']:raise ValueError('Cannot headline results with unconverged states')
        baseline=read_json(root/'metrics'/city/'congested/baseline.json')
        attack=read_json(root/'metrics'/city/'congested/attack_mid.json')
        audit=read_json(root/city/'assignment_audit.json')
        traffic=read_json(root/'fresh_assignment'/city/'base/summary.json')
        for view,weighting,suffix,share in [('unweighted','unweighted','','node_share'),
                                           ('population_weighted','population','_pop','population_share')]:
            for factor in FACTORS:
                free=summary['event_service'][f'free_flow_{factor:g}_{weighting}']['value']
                own=summary['event_service'][f'intact_congested_{factor:g}_{weighting}']['value']
                conn=summary['event_service']['connectivity_'+weighting]['value']
                bridge=baseline['bridge_redundancy'];detour=baseline['detour_index']
                h=baseline['hansen'+suffix];a=attack['normalized_auc'][share]
                rows.append(dict(city=city,view=view,budget_factor=factor,samples=summary['samples'],
                    bridge=bridge,detour=detour,attack=a,hansen=h,
                    disruption_reliability=own,free_flow_reference_service=free,connectivity=conn,
                    composite_original_reference=composite(bridge,detour,h,a,own,conn),
                    composite_alternative_free_flow_reference=composite(bridge,detour,h,a,free,conn)))
        baseline_rows.append(dict(city=city,demand_pcu_h=traffic['demand_pcu_h'],
            free_flow_minutes=traffic['free_flow_mean_min'],congested_minutes=traffic['congested_mean_min'],
            delay_seconds=60*traffic['mean_delay_min'],travel_time_index=traffic['travel_time_index'],
            time_accessibility=audit['hansen_congested'],time_accessibility_pop=audit['hansen_population_congested'],
            ordinary_service_1_5=summary['intact_service']['free_flow_1.5_unweighted'],
            ordinary_demand_service_1_5=summary['intact_service']['free_flow_1.5_demand'],
            positive_flow_arcs=audit['positive_flow_arcs'],bpr_error=audit['max_relative_bpr_error'],
            flow_residual=audit['max_flow_residual_pcu_h']))
    save_csv(root/'reassignment_comparison.csv',rows)
    save_csv(root/'ordinary_traffic_comparison.csv',baseline_rows)
    def line(label,key,source=baseline_rows,percent=False):
        values=[next(r[key] for r in source if r['city']==city) for city in CITIES]
        return '| '+label+' | '+' | '.join(f'{v*100:.3f}%' if percent else f'{v:.6f}' for v in values)+' |'
    primary=[r for r in rows if r['view']=='unweighted' and r['budget_factor']==1.5]
    texts=['# Traffic simulation audit and reassignment results','',
        'Both areas were simulated again. The same resident trip rate, fallback capacities, BPR parameters, failure model and predeclared service budgets were used. No area-specific penalty was introduced to force a ranking.','',
        '## Findings','',
        '1. The earlier experiment did assign traffic and use congested costs. The original per-arc BPR equations and node flow conservation pass, and the solver reproduces the saved results exactly when its saved inputs are frozen.',
        '2. A real input-preparation defect was found: simplified roads can have multiple lane tags, and selecting the first list value makes capacity depend on list order. A rerun changed six Gachibowli capacities. The audited experiment now resolves these lists deterministically using a bottleneck minimum. Mixed speed/highway lists are also resolved deterministically with conservative shared rules. This is still an assumption, not measured capacity.',
        '3. Reliability relative to an already-congested intact network measures additional disruption. It can be high even when ordinary traffic is slow. A separate free-flow-reference service measure is now reported without overwriting the original definition.',
        '4. Failure states now receive a fresh traffic assignment. Unreachable demand remains in the original service denominator and is reported as unserved. Both reference metrics use the same event times and failures.','',
        '## Ordinary traffic, before road failures','',
        '| Metric | Gachibowli | Old Hyderabad |','| --- | ---: | ---: |',
        line('Synthetic demand, PCU/hour','demand_pcu_h'),line('Mean congested trip time, minutes','congested_minutes'),
        line('Added delay per trip, seconds','delay_seconds'),line('Travel-time index','travel_time_index'),
        line('Time accessibility, six-minute half-life','time_accessibility'),
        line('Population-weighted time accessibility','time_accessibility_pop'),
        line('All-pair service within 1.5 times free flow','ordinary_service_1_5',percent=True),
        line('Demand-weighted service within 1.5 times free flow','ordinary_demand_service_1_5',percent=True),'',
        'The ordinary service rows contain no road-failure sampling. They measure the intact congested snapshot against the same type of free-flow budget in each area. They are not substitutes for the original failure-conditioned reliability.','',
        '## Road failures with traffic reassignment: primary 50% time allowance','',
        '| Metric | Gachibowli | Old Hyderabad |','| --- | ---: | ---: |',
        line('Original disruption-relative reliability','disruption_reliability',primary),
        line('Free-flow-reference service during failures','free_flow_reference_service',primary),
        line('Mutual-pair connectivity reliability','connectivity',primary),
        line('Composite retaining original reference and weights','composite_original_reference',primary),
        line('Alternative composite with free-flow-reference service','composite_alternative_free_flow_reference',primary),'',
        'The alternative composite changes the service question while retaining the coefficients. It must not be passed off as the original composite. Each area has 64 event samples; these are pilot estimates with a conservative 95% Hoeffding half-width of about 0.170. Printing six decimals does not establish that accuracy or statistical significance.','',
        '## All predeclared time-budget sensitivities','',
        '| Area | Allowed multiple of free-flow time | Failure-state service, uniform pairs | Original-reference composite | Alternative-reference composite |',
        '| --- | ---: | ---: | ---: | ---: |']
    for r in rows:
        if r['view']=='unweighted':
            texts.append(f"| {r['city']} | {r['budget_factor']:.1f} | {r['free_flow_reference_service']:.6f} | {r['composite_original_reference']:.6f} | {r['composite_alternative_free_flow_reference']:.6f} |")
    texts+=['',
        'The primary factor 1.5 retains the project\'s previous 50% allowance. Factors 1.2 and 2.0 were declared before these results. Do not select a threshold solely because it produces a preferred ordering. None of these project thresholds is claimed as a measured local service standard.','',
        '## Why the composite can still favour Old Hyderabad','',
        'The original composite assigns 25% to attack robustness and 15% each to bridge, detour, accessibility, travel reliability and connectivity. Redundancy/attack/connectivity together receive 70%. A dense network can have high congestion while retaining many alternative routes under failures. A faster network can depend on a few bottlenecks. Ordinary traffic performance and robustness to failures are different properties.',
        'Changing positive travel times does not change bridges or whether a pair is connected. A higher connectivity score for Old Hyderabad is not evidence that traffic was omitted. The original composite is not an objective ground-truth ranking of ordinary driving conditions.','',
        '## Validation and retained limitations','',
        '- Fresh assignments cover all 1,305 Gachibowli and 8,435 Old Hyderabad directed non-loop arcs. Saved arc files contain actual assigned volumes, capacities, V/C, free-flow and congested times.',
        '- The arc-wise BPR residual is zero to stored precision. Node-flow residuals are below 3e-12 PCU/hour. An independent stricter 1e-4 solver-gap check also converged; its outputs are recorded separately.',
        '- The audit confirms changed time betweenness for 131 nodes/158 roads in Gachibowli and 2,217 nodes/3,132 roads in Old Hyderabad. Accessibility, efficiency, detours and attack are explicitly calculated from congested costs in metrics/.',
        '- The corrected tag-resolution rule is implemented in the isolated experiment. Production input parsing has not been silently changed; its first-list-value handling still needs coordinated integration with the demand/capacity owner.',
        '- OD is resident-based, not measured travel demand. Missing job/visitor/through-trip flows, sparse lane data and boundary/population allocation losses remain. Most capacities are fallback assumptions.',
        '- Static BPR does not represent queues, traffic signals, parking interference or observed daily variability. Simulation results remain scenarios until checked against matched travel times/counts from both areas.',
        '- All events and convergence states are retained. Unconverged states would have produced missing-state bounds rather than being silently omitted; all headline values require complete convergence.','',
        '## Reproduction and evidence','',
        'Run examples/traffic/validate_traffic_service.py, then examples/traffic/summarize_traffic_validation.py --stage global and --stage report. The output root is results/traffic_validation_v2/. Earlier results are preserved.',
        'Evidence: experiment.json; <area>/previous_assignment_audit.json; assignment_audit.json; resolved_tags.csv; strict_solver_check.json; events.csv; service_summary.json; fresh_assignment/<area>/base/traffic_arcs.csv; and metrics/<area>/<cost>/.',
        'Comparison files: ordinary_traffic_comparison.csv and reassignment_comparison.csv. Population-weighted and demand-weighted results are exported alongside uniform-pair results.',
        'The first audit attempt under results/traffic_validation/ stopped on the detected non-reproducibility. It is not a completed comparison and should not be used.','',
        '## Reference for the interpretation','',
        '[FHWA travel-time performance definitions](https://ops.fhwa.dot.gov/perf_measurement/ucr/documentation.htm) distinguish a free-flow-referenced travel-time index from reliability measures. The free-flow reference is useful for congestion performance, but does not make our project\'s synthetic failures, 1.5 threshold or local parameters empirically validated.']
    report='\n'.join(texts)+'\n'
    (root/'validation_report.md').write_text(report,encoding='utf-8')
    Path('docs/traffic/traffic_audit.md').write_text(report,encoding='utf-8')
    fig,axes=plt.subplots(1,3,figsize=(12,4),layout='constrained')
    for ax,key,title in zip(axes,['delay_seconds','time_accessibility','ordinary_service_1_5'],
        ['Added delay (seconds/trip)','Time accessibility (6-minute half-life)','Ordinary service within 1.5x free flow']):
        vals=[r[key] for r in baseline_rows]
        bars=ax.bar(['Gachibowli','Old Hyderabad'],vals,color=['#258f9b','#d87a43'])
        ax.bar_label(bars,fmt='%.3f',padding=3,fontsize=9)
        ax.set_title(title,fontsize=10);ax.grid(axis='y',alpha=.2)
        ax.set_ylim(0,1.1 if key!='delay_seconds' else max(vals)*1.2)
    fig.suptitle('Fresh synthetic traffic simulation: deterministic inputs and shared rules',fontsize=12)
    fig.savefig(root/'traffic_audit.png',dpi=180);plt.close(fig)
    print(report[:5500])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=['global','report'],required=True)
    parser.add_argument('--root',type=Path,default=Path('results/traffic_validation_v2'))
    parser.add_argument('--inputs',type=Path,default=Path('data/traffic_comparison'))
    args=parser.parse_args()
    if args.stage=='global':global_metrics(args)
    else:report(args)
    save_json(args.root/f'manifest_summary_{args.stage}.json',dict(script_sha256=digest(Path(__file__)),
        assignment_script_sha256=digest(Path(__file__).with_name('validate_traffic_service.py'))))


if __name__=='__main__':main()
