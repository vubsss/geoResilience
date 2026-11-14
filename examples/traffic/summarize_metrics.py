"""Assemble verified traffic-weighted metrics and the user-specified composite."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from run_metrics_comparison import MODES, read_csv
from run_pilot import CITIES, digest, save_csv, save_json


def composite(bridge,detour,hansen,attack,travel,connectivity):
    return .25*attack+.15*(bridge+detour+hansen+travel+connectivity)


def assemble(root,inputs):
    rows=[];historical=[];previous_roads=[];previous_nodes=[]
    for city in CITIES:
        import geopandas as gpd
        old_gpkg=inputs/'results'/f'{city}-population'/'network.gpkg'
        old_edges=gpd.read_file(old_gpkg,layer='edges')
        old_nodes=gpd.read_file(old_gpkg,layer='nodes')
        archive=json.loads((inputs/'results'/f'{city}-population'/'summary.json').read_text())
        old=dict(city=city,bridge_redundancy=1-archive['metrics']['redundancy']['bridge_frac'],
            detour_index=1/archive['metrics']['redundancy']['detour_ratio']['median'],
            hansen=archive['metrics']['accessibility']['mean_accessibility']/(archive['cleaning']['final']['node_count']-1),
            attack=archive['metrics']['robustness']['links']['auc_attack_S'],
            travel=archive['travel_time']['tt_reliability'],connectivity=archive['reliability']['conn_reliability'])
        old['composite']=composite(old['bridge_redundancy'],old['detour_index'],old['hansen'],old['attack'],old['travel'],old['connectivity'])
        assert abs(old['composite']-({'gachibowli':.5739,'old-hyderabad':.6186}[city]))<.00005
        historical.append(old)
        reliabilities={mode:json.loads((root/city/mode/'reliability.json').read_text())['summary']
                       for mode in ('free_flow','congested')}
        for mode in MODES:
            folder=root/city/mode
            baseline=json.loads((folder/'baseline.json').read_text())
            current=json.loads((folder/'attack.json').read_text())
            legacy=json.loads((folder/'legacy_attack.json').read_text())
            if mode=='distance':assert abs(legacy['historical_replay_difference'])<1e-9
            rel=reliabilities['free_flow' if mode=='distance' else mode]
            for view,suffix in [('unweighted',''),('population_weighted','_pop')]:
                share='node_share' if not suffix else 'population_share'
                travel=rel[view]['travel_time_reliability']['value']
                connectivity=rel[view]['connectivity_reliability']['value']
                row=dict(city=city,cost=mode,view=view,
                    bridge_share=baseline['bridge_share'],bridge_index=baseline['bridge_redundancy'],
                    alternative_share=baseline['detour_alternative_share'],
                    median_detour=baseline['median_detour_ratio'],detour_index=baseline['detour_index'],
                    hansen=baseline['hansen'+suffix],efficiency=baseline['efficiency'+suffix],
                    raw_unweighted_hansen_mean=baseline['raw_node_hansen_mean'],
                    efficiency_units='1/metre' if mode=='distance' else '1/second',
                    half_cost=baseline['half_cost'],attack_current_raw=current['raw_auc'][share],
                    attack_current_normalized=current['normalized_auc'][share],
                    attack_mid_normalized=legacy['normalized_auc'][share],
                    travel_time_reliability=travel,connectivity_reliability=connectivity)
                for protocol in ('current','mid'):
                    row['composite_'+protocol]=composite(row['bridge_index'],row['detour_index'],row['hansen'],
                        row['attack_'+protocol+'_normalized'],travel,connectivity)
                assert all(0<=row[k]<=1 for k in ('bridge_index','detour_index','hansen','composite_current','composite_mid'))
                rows.append(row)
            # Merge exact node/road metrics with explicit null coverage for removals.
            n_damage={r['node']:r for r in read_csv(folder/'node_consequences.csv')}
            e_damage={r['link_id']:r for r in read_csv(folder/'link_consequences.csv')}
            nodes=[];edges=[]
            for node in read_csv(folder/'nodes.csv'):
                d=n_damage.get(node['node'],{})
                nodes.append({**node,'information_centrality':d.get('efficiency_drop'),
                    'information_centrality_pop':d.get('efficiency_drop_pop'),
                    'node_accessibility_drop':d.get('accessibility_drop'),
                    'node_accessibility_drop_pop':d.get('accessibility_drop_pop'),
                    'removal_evaluated':bool(d),'removal_reason':None if d else 'outside declared common screening set'})
            for link in read_csv(folder/'links.csv'):
                d=e_damage.get(link['link_id'],{})
                edges.append({**link,**{k:d.get(k) for k in ('efficiency_drop','efficiency_drop_pop',
                    'accessibility_drop','accessibility_drop_pop')},'removal_evaluated':bool(d),
                    'removal_reason':None if d else 'self-loop or outside declared common screening set'})
            save_csv(folder/'node_metrics.csv',nodes);save_csv(folder/'link_metrics.csv',edges)
            for kind,field in [('previous_highest_access_drop','access_drop'),
                               ('previous_highest_population_access_drop','access_drop_pop')]:
                old_road=old_edges.nlargest(1,field).iloc[0]
                matching=[r for r in edges if {r['u'],r['v']}=={str(old_road.u),str(old_road.v)}
                          and r['osm_way_ids']==str(old_road.osm_way_ids)]
                if len(matching)!=1:raise ValueError('Ambiguous historical example road')
                current=matching[0]
                if not current['removal_evaluated']:raise ValueError('Historical example road was not evaluated')
                previous_roads.append(dict(city=city,cost=mode,example=kind,
                    archived_link_id=int(old_road.link_id),link_id=current['link_id'],name=current['name'],
                    edge_betweenness=current['edge_betweenness'],
                    **{k:current[k] for k in ('efficiency_drop','efficiency_drop_pop','accessibility_drop','accessibility_drop_pop')}))
            old_node=str(old_nodes.nlargest(1,'information').iloc[0].node_id)
            selected=next(r for r in nodes if r['node']==old_node)
            if not selected['removal_evaluated']:raise ValueError('Historical information node not evaluated')
            previous_nodes.append(dict(city=city,cost=mode,node=old_node,
                **{k:selected[k] for k in ('betweenness','information_centrality','information_centrality_pop',
                                          'hansen','hansen_pop')}))
        for view in ('unweighted','population_weighted'):
            assert reliabilities['free_flow'][view]['connectivity_reliability']==reliabilities['congested'][view]['connectivity_reliability']
    save_csv(root/'metrics_comparison.csv',rows)
    save_csv(root/'historical_comparison.csv',historical)
    save_csv(root/'previous_critical_roads.csv',previous_roads)
    save_csv(root/'previous_information_nodes.csv',previous_nodes)
    return rows,historical


def write_report(root,rows,historical):
    def lookup(city,cost,view='unweighted'):
        return next(r for r in rows if r['city']==city and r['cost']==cost and r['view']==view)
    def table(fields,cost='congested',view='unweighted'):
        result=['| Metric | Gachibowli | Old Hyderabad |','| --- | ---: | ---: |']
        for label,field in fields:
            result.append('| '+label+' | '+' | '.join(f'{lookup(c,cost,view)[field]:.6f}' for c in CITIES)+' |')
        return '\n'.join(result)
    main_fields=[('Bridge redundancy index','bridge_index'),('Median finite time detour','median_detour'),
        ('Detour redundancy index','detour_index'),('Attack robustness: mid-evaluation protocol','attack_mid_normalized'),
        ('Normalized time Hansen, 6-minute half-life','hansen'),('Travel-time reliability','travel_time_reliability'),
        ('Mutual-pair connectivity reliability','connectivity_reliability'),
        ('Composite: original weights and mid-evaluation attack','composite_mid')]
    lines=['# Full Tier 1/2 metric comparison with simulated traffic','',
        'Calculated 13 November 2026 from the base traffic case. All traffic values are synthetic.',
        'The presentation PDF supplied by the user provides the historical comparison; the archive summaries provide its unrounded values.','',
        f"With the original composite weights and mid-evaluation attack protocol, the new unweighted composite is {lookup('gachibowli','congested')['composite_mid']:.6f} for Gachibowli and {lookup('old-hyderabad','congested')['composite_mid']:.6f} for Old Hyderabad. This aggregate must be interpreted alongside delay, accessibility and its chosen weighting, rather than treated as a measured overall traffic ranking.",'',
        '## New values in the previous presentation format','',
        table(main_fields[:4]+[('Raw unit-opportunity Hansen mean','raw_unweighted_hansen_mean')]+main_fields[4:]),'',
        'These use the original directed, 20-batch attack protocol so that the attack definition remains consistent with mid-evaluation. The composite coefficients remain exactly the user-specified 25% attack plus 15% each for bridge, detour, Hansen, travel-time reliability and connectivity reliability.','',
        '## Population-weighted version','',table(main_fields,view='population_weighted'),'',
        'Population counts are unchanged. Population weights apply to Hansen, efficiency/information, event-pair reliability and SCC population share. Bridge and detour remain road-topology/cost measures; inventing population weights for them would define different metrics.','',
        '## Matched free-flow to congestion comparison','',
        '| Area | Free-flow Hansen | Congested Hansen | Free-flow composite, mid protocol | Congested composite, mid protocol |',
        '| --- | ---: | ---: | ---: | ---: |']
    for city in CITIES:
        f,c=lookup(city,'free_flow'),lookup(city,'congested')
        lines.append(f"| {city} | {f['hansen']:.6f} | {c['hansen']:.6f} | {f['composite_mid']:.6f} | {c['composite_mid']:.6f} |")
    lines+=['',
        'This is the comparison that isolates congestion: identical roads, populations, speeds, demand scenario, accessibility half-life, attack protocol and event draws, with free-flow versus assigned congested costs. Comparing the old distance index directly against a new time index does not isolate congestion.','',
        '## Current pipeline attack protocol, reported separately','',table([
            ('Attack normalized AUC','attack_current_normalized'),('Attack raw AUC','attack_current_raw'),
            ('Composite using current attack protocol','composite_current')]),'',
        'The current pipeline removes one road and updates an undirected betweenness ranking after every removal; it reports raw AUC to the actual integer horizon. The mid-evaluation code used directed betweenness, updated in 20 batches, and normalized area to the requested 20% horizon. The comparison adapter exports both protocols. A raw AUC near 0.02 must not be inserted into a formula expecting a normalized 0-1 attack index.','',
        'Current-protocol distance/free-flow/congested baselines are all in metrics_comparison.csv. A ranking difference already present in the recomputed distance baseline cannot be attributed to traffic. The two attack protocols must not be mixed in one before/after claim.','',
        '## Historical checks','',
        '| Area | Archived distance Hansen | Replayed historical attack | Reconstructed old composite |',
        '| --- | ---: | ---: | ---: |']
    for r in historical:
        lines.append(f"| {r['city']} | {r['hansen']:.6f} | {r['attack']:.6f} | {r['composite']:.6f} |")
    lines+=['',
        'Distance bridge shares, median detours and normalized Hansen reproduce the archives. Historical directed attack AUC also replays to floating-point precision after restoring the archived road IDs used to break ties. Reconstructed composites round to the slide values 0.5739 and 0.6186.','',
        'Historical reliability estimates are not an exact replay: the current simulator has different event-draw/link-order conventions, and evaluates all travel-time origins rather than the old 100-origin sample. Small old-versus-new connectivity changes are Monte Carlo/implementation differences, not effects of congestion. Connectivity is exactly identical in the paired new free-flow and congested runs.','',
        '## What changed in the calculations','',
        '- Physical road grouping, directions, parallel roads, populations and failure probabilities stay fixed. Asymmetric arc times must never split one physical road into two failure events.',
        '- Routing cost is seconds in the new time variants. Betweenness, detours, efficiency, information centrality and Hansen are recomputed against those costs.',
        '- Undirected node/edge betweenness retains the current pipeline convention: select the minimum-cost physical road per unordered node pair. For time costs, each road uses its mean directional time. Directed accessibility and reliability retain each individual arc time.',
        '- Time detour uses alternative travel time divided by the original road time in that same direction, then takes the worst direction. It is not divided by physical metres.',
        '- Distance Hansen uses the original 2 km half-distance. Time Hansen uses a common six-minute half-life and 30-minute cutoff, corresponding to 2 km at an assumed reference speed of 20 km/h. This is a declared scenario choice, not a fitted accessibility threshold. Three- and twelve-minute sensitivity is also exported.',
        '- Efficiencies have units 1/metre or 1/second. Compare time efficiency before/after congestion; do not compare its raw magnitude against distance efficiency.',
        '- Bridge share and the existence of an alternative cannot change when only positive travel costs change. Mutual connectivity reliability is identical across the paired free-flow/congested runs because the same physical failures are used.',
        '- Travel-time reliability compares event times with 1.5 times the corresponding intact time. Baseline congestion can therefore leave this index unchanged or increase it slightly. It is not a direct measure of everyday congestion.',
        '- Event probabilities retain the existing physical-length proxy: p0=0.01 per km under independent closures. Traffic alone does not provide new flood/link failure probabilities.',
        '- Reliability uses 1,024 connectivity events, 512 travel-time events, seed 42 and all original origins/pairs. Population and unweighted views share the draws. The old travel-time calculation sampled 100 origins, so its six-decimal result need not replay under the current all-origin estimator.',
        '- Every closure/removal uses fixed intact free-flow or assigned costs. Traffic demand is not reassigned after each event. These are fixed-cost resilience calculations, not full disruption-induced congestion simulations.','',
        '## Local metrics and evaluated coverage','',
        'Each area/cost folder contains node_metrics.csv and link_metrics.csv. Betweenness and Hansen are calculated for every node; edge betweenness, bridge flags and detours for every applicable physical road. Information centrality and single-removal consequences are exact on a declared common screening set, not on every possible removal. local_coverage.json records the IDs and selection method. Unevaluated values are blank with a reason, never zero.','',
        'The common set is the union of top-30 betweenness nodes/roads from all three cost views, plus the archived top-10 information nodes and access-drop roads. Results on these candidates must be labelled "highest among evaluated candidates", not claimed as proven global maxima. The historical node-information implementation was undirected; current directed information is reported with a matched directed baseline.','',
        '| Area | Evaluated node isolations per cost | Evaluated road removals per cost |',
        '| --- | ---: | ---: |']
    for city in CITIES:
        coverage=json.loads((root/city/'local_coverage.json').read_text())
        lines.append(f"| {city} | {len(coverage['common_node_ids'])} | {len(coverage['common_link_ids'])} |")
    lines+=['','### Other cost-dependent indices, congested case','',
        '| Metric | Gachibowli | Old Hyderabad |','| --- | ---: | ---: |']
    for label,field in [('Directed network efficiency, 1/second','efficiency'),
                        ('Population-weighted efficiency, 1/second','efficiency_pop'),
                        ('Mean node betweenness','node_betweenness_mean'),
                        ('Maximum node betweenness','node_betweenness_max'),
                        ('Mean physical-edge betweenness','edge_betweenness_mean'),
                        ('Maximum physical-edge betweenness','edge_betweenness_max')]:
        values=[json.loads((root/c/'congested/baseline.json').read_text())[field] for c in CITIES]
        lines.append(f'| {label} | {values[0]:.8f} | {values[1]:.8f} |')
    lines+=['','### Highest local values among the evaluated candidates','',
        '| Area | Node with highest information | Information value | Road with highest access drop | Access drop | Road with highest population access drop | Population access drop |',
        '| --- | --- | ---: | --- | ---: | --- | ---: |']
    local_summary=[]
    for city in CITIES:
        nodes=[r for r in read_csv(root/city/'congested/node_metrics.csv') if r['information_centrality']]
        edges=[r for r in read_csv(root/city/'congested/link_metrics.csv') if r['accessibility_drop']]
        node=max(nodes,key=lambda r:float(r['information_centrality']))
        edge=max(edges,key=lambda r:float(r['accessibility_drop']))
        pop=max(edges,key=lambda r:float(r['accessibility_drop_pop']))
        def road(r):return (r['name'] or 'unnamed')+' (ID '+r['link_id']+')'
        lines.append(f"| {city} | {node['node']} | {float(node['information_centrality']):.6f} | {road(edge)} | {float(edge['accessibility_drop']):.6f} | {road(pop)} | {float(pop['accessibility_drop_pop']):.6f} |")
        local_summary.append(dict(city=city,node=node['node'],information_centrality=float(node['information_centrality']),
            access_drop_road=road(edge),accessibility_drop=float(edge['accessibility_drop']),
            population_access_drop_road=road(pop),accessibility_drop_pop=float(pop['accessibility_drop_pop'])))
    save_csv(root/'local_summary.csv',local_summary)
    lines+=['',
        '## Limitations and interpretation','',
        'The input coverage and demand/capacity limitations documented in docs/traffic/results.md still apply. Most capacities are fallback assumptions; resident-only OD omits jobs, visitors and through trips. Gachibowli has substantial clipped-road and unallocated-population losses. No measured traffic validation has been performed.','',
        'Monte Carlo intervals are exported in each reliability.json; six printed decimals describe the numerical estimate, not six-decimal empirical accuracy. The conservative 95% Hoeffding interval half-widths are about 0.0424 for connectivity and 0.0600 for travel-time reliability. Small differences near one are not established as statistically significant by these intervals.','',
        'The original composite is an aggregation preference, not ground truth. An area can have lower time accessibility and greater delay yet retain a higher composite because bridge/detour and attack scores receive substantial weight. Do not change weights or failure probabilities to force a preferred ordering.','',
        '## Outputs','',
        '- metrics_comparison.csv: all three costs, both population views, both attack/composite protocols.',
        '- historical_comparison.csv: original unrounded values and reconstructed composite.',
        '- previous_critical_roads.csv and previous_information_nodes.csv: new values on the same historical example roads/nodes, for all three costs.',
        '- metrics_comparison.png: matched time-Hansen and composite plots.',
        '- <area>/<cost>/node_metrics.csv and link_metrics.csv: detailed metric rows and coverage.',
        '- <area>/<cost>/attack_curve.csv and legacy_attack_curve.csv: both attack definitions.',
        '- <area>/<cost>/reliability.json: values, intervals and simulation settings (time modes).',
        '- <area>/<cost>/baseline.json: redundancy, Hansen sensitivity, efficiency and centrality statistics.',
        '- manifest_*.json and audit/: code/input hashes and settings.','',
        'Validation: 33 targeted metric/traffic tests passed. One previously known full-pipeline integration test was explicitly excluded; this experiment does not certify that test or a full raster-based CLI run. Physical identities, units, directional detours, current attack equivalence on a known graph, historical distance results and paired-connectivity invariance were checked.','',
        'Production code and presentation files were not edited. Reproduction commands are in examples/traffic/README.md.']
    (root/'comparison_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return '\n'.join(lines[:15])


def plot(root,rows):
    fig,axes=plt.subplots(1,3,figsize=(13,4.5),layout='constrained')
    for ax,field,title in zip(axes,['hansen','composite_mid','composite_current'],
        ['Time Hansen (6-minute half-life)','Composite: mid-evaluation attack','Composite: current attack']):
        x=np.arange(2)
        for i,cost in enumerate(('free_flow','congested')):
            vals=[next(r[field] for r in rows if r['city']==city and r['cost']==cost and r['view']=='unweighted') for city in CITIES]
            bars=ax.bar(x+(i-.5)*.34,vals,.34,label=cost.replace('_',' '),color=['#258f9b','#d87a43'][i])
            ax.bar_label(bars,fmt='%.3f',fontsize=8,padding=3)
        ax.set_ylim(0,1);ax.set_xticks(x,['Gachibowli','Old Hyderabad'])
        ax.set_title(title,fontsize=10);ax.grid(axis='y',alpha=.2);ax.legend(fontsize=8)
    fig.suptitle('Synthetic traffic: matched free-flow versus congestion; fixed composite weights',fontsize=12)
    fig.savefig(root/'metrics_comparison.png',dpi=180);plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('results/traffic_metrics'))
    parser.add_argument('--inputs',type=Path,default=Path('data/traffic_comparison'))
    args=parser.parse_args()
    rows,historical=assemble(args.root,args.inputs)
    report=write_report(args.root,rows,historical);plot(args.root,rows)
    save_json(args.root/'manifest_summary.json',dict(script_sha256=digest(Path(__file__)),
        pdf_sha256=digest(Path('Spatial_MID (1).pdf')),composite_weights_sum=.25+5*.15))
    print(report)


if __name__=='__main__':main()
