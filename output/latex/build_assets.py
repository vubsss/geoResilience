"""Build presentation charts from saved outputs; no analysis code/results are modified."""
from pathlib import Path
import hashlib
import json
import shutil

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ASSETS = HERE / 'assets'
ASSETS.mkdir(exist_ok=True)
RUNS = ROOT / 'results/ticket14-demo'
NAVY, TEAL, GOLD, RED = '#15324F', '#007F86', '#DAA641', '#BC4141'
plt.rcParams.update({'font.size': 12, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.labelcolor': NAVY, 'text.color': NAVY, 'axes.titleweight': 'bold',
                     'savefig.facecolor': 'white', 'pdf.fonttype': 42})
sources = []

def record(output, source, kind='local saved output'):
    path = ROOT / source
    sources.append({'asset': output, 'source': source, 'evidence_type': kind,
                    'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None})

def save(fig, name, source, kind='local saved output'):
    fig.tight_layout()
    fig.savefig(ASSETS / name, bbox_inches='tight')
    plt.close(fig)
    record(name, source, kind)

uniform = json.loads((RUNS/'uniform/summary.json').read_text())
pop = json.loads((RUNS/'population/summary.json').read_text())
weighted = json.loads((RUNS/'user-weighted/summary.json').read_text())
for name in ['population_map.png','vuln_map.png','zones_vulnerability_map.png','edge_betweenness_map.png',
             'critical_links_map.png','scorecard.png']:
    shutil.copy2(RUNS/'population/figures'/name, ASSETS/name)
    record(name, 'results/ticket14-demo/population/figures/'+name)
shutil.copy2(RUNS/'missing-metrics/figures/scorecard.png', ASSETS/'missing_scorecard.png')
record('missing_scorecard.png','results/ticket14-demo/missing-metrics/figures/scorecard.png')

# Illustrative mechanism, clearly separated from measured results.
fig, axes = plt.subplots(1,2,figsize=(11,3.5))
points = [(x,y) for x in range(3) for y in range(2)]
edges = [(a,b) for a in range(6) for b in range(a+1,6)
         if abs(points[a][0]-points[b][0])+abs(points[a][1]-points[b][1])==1]
for ax, closed in zip(axes,[False,True]):
    for offset in [0,4]:
        for a,b in edges:
            ax.plot([points[a][0]+offset,points[b][0]+offset],[points[a][1],points[b][1]],color=TEAL,lw=3)
        ax.scatter([x+offset for x,y in points],[y for x,y in points],s=100,color=NAVY,zorder=3)
    ax.plot([2,4],[1,1],color=RED if closed else GOLD,lw=4,ls='--' if closed else '-')
    if closed:
        ax.scatter([3],[1],marker='x',s=220,color=RED,lw=3,zorder=5)
    ax.text(3,1.35,'Connecting road',ha='center',fontsize=11)
    ax.set_title('Road open' if not closed else 'Road closed',fontsize=15)
    ax.set_xlim(-.3,6.3); ax.set_ylim(-.2,1.8); ax.set_aspect('equal'); ax.axis('off')
save(fig,'problem_schematic.pdf','GeoResilient_Project_Proposal.pdf','illustrative topology; no empirical measurements')

# The saved Monte Carlo/removal output is replotted with presentation-size type.
curves = pd.read_csv(RUNS/'population/robustness_curves.csv')
attack = curves.loc[(curves.element=='links') & (curves['mode']=='attack')]
failure = curves.loc[(curves.element=='links') & (curves['mode']=='failure')].groupby('f')[['S_scc','E_rel']].mean().reset_index()
fig, axes = plt.subplots(1,2,figsize=(11.5,4.2))
for ax, field, title in zip(axes,['S_scc','E_rel'],['Largest strongly connected share','Relative distance efficiency']):
    for data,color,label in [(attack,RED,'Targeted attack'),(failure,TEAL,'Random failure mean')]:
        ax.plot(data.f*100,data[field],'-o',color=color,lw=2.4,label=label,ms=6)
        ax.plot([data.f.iloc[-1]*100,20],[data[field].iloc[-1]]*2,':',color=color,lw=2)
    ax.set(xlim=(0,20),ylim=(.8,1.025),xlabel='Physical roads removed (%)',ylabel='Fraction of baseline',title=title)
    ax.grid(alpha=.18); ax.legend(fontsize=10,loc='lower left')
save(fig,'robustness_links.pdf','results/ticket14-demo/population/robustness_curves.csv')

fig, ax = plt.subplots(figsize=(7.5,4.2))
x=np.arange(2); width=.34
for shift,key,color,label in [(-width/2,'mean',TEAL,'Mean'),(width/2,'p90',NAVY,'90th percentile')]:
    values=[uniform['metrics']['accessibility']['vuln'][key]*100,pop['metrics']['accessibility']['vuln_pop'][key]*100]
    bars=ax.bar(x+shift,values,width,color=color,label=label)
    ax.bar_label(bars,fmt='%.2f%%',padding=4,fontsize=11)
ax.set(xticks=x,xticklabels=['Uniform destinations','Population destinations'],ylim=(0,50),ylabel='Worst evaluated single-road loss (%)')
ax.legend(loc='upper left',fontsize=10); ax.grid(axis='y',alpha=.18); ax.set_axisbelow(True)
save(fig,'accessibility_comparison.pdf','results/ticket14-demo/population/summary.json')

fig, ax = plt.subplots(figsize=(8.5,4.6))
keys=list(pop['scorecard']['normalised_scores'])
labels=['Link attack AUC','Link failure AUC','Bridge redundancy','Inverse median detour','Mutual-pair reliability','Accessibility retained']
y=np.arange(6); height=.34
for shift,data,color,label in [(-height/2,uniform, '#ADBCCC','Structural'),(height/2,pop,TEAL,'Population where defined')]:
    values=[data['scorecard']['normalised_scores'][key] for key in keys]
    ax.barh(y+shift,values,height=height,color=color,label=label)
for i,key in enumerate(keys):
    value=pop['scorecard']['normalised_scores'][key]
    ax.text(max(value,uniform['scorecard']['normalised_scores'][key])+.025,i,f'{value:.4f}',va='center',fontsize=11)
ax.set(yticks=y,yticklabels=labels,xlim=(0,1.15),xlabel='Project-normalised score (1 = resilient under the metric)')
ax.invert_yaxis(); ax.grid(axis='x',alpha=.18); ax.set_axisbelow(True)
ax.legend(loc='lower center',bbox_to_anchor=(.5,-.28),ncol=2,frameon=False,fontsize=11)
save(fig,'scorecard_comparison.pdf','results/ticket14-demo/population/summary.json')

# Historical real-data numbers are recorded in README, not rerun in this checkout.
fig,ax=plt.subplots(figsize=(7.5,4.1))
allocated=np.array([183190.237518,190423.954834]); unallocated=np.array([7233.717316,0.])
x=np.arange(2)
ax.bar(x,allocated/1000,width=.5,color=TEAL,label='Allocated')
ax.bar(x,unallocated/1000,bottom=allocated/1000,width=.5,color=GOLD,label='Unallocated')
for i in range(2):
    ax.text(i,allocated[i]/1000/2,f'{allocated[i]:,.0f}',ha='center',va='center',color='white',fontsize=14,fontweight='bold')
    ax.text(i,197,f'{100*unallocated[i]/190423.954834:.2f}% unallocated',ha='center',fontsize=11)
ax.set(xticks=x,xticklabels=['100 m snap limit','500 m snap limit'],ylim=(0,215),ylabel='Estimated population (thousands)')
ax.legend(loc='upper center',bbox_to_anchor=(.5,-.16),ncol=2,frameon=False)
ax.grid(axis='y',alpha=.15); ax.set_axisbelow(True)
save(fig,'male_allocation.pdf','README.md','recorded real-data validation, 12 October 2026; raw run outputs absent locally')

fig,ax=plt.subplots(figsize=(7.5,3.8))
d=np.linspace(0,500,501); w=np.exp(-np.log(2)*d/100)
ax.plot(d,w,color=TEAL,lw=2.5)
ax.plot([500,500],[w[-1],0],':',color=TEAL,lw=2)
ax.plot([500,650],[0,0],color=TEAL,lw=2.5)
ax.axvline(100,color=GOLD,ls='--',alpha=.8); ax.scatter([100],[.5],color=NAVY,s=45,zorder=5)
ax.annotate('Half-distance = 100 m\nContribution = 0.5',xy=(100,.5),xytext=(190,.65),arrowprops={'arrowstyle':'->','color':NAVY},fontsize=11)
ax.axvline(500,color=RED,ls='--',alpha=.5); ax.text(515,.26,'Beyond R:\nzero contribution',color=RED,fontsize=11)
ax.set(xlim=(0,650),ylim=(-.03,1.05),xlabel='Outbound shortest-road distance (m)',ylabel='Contribution / destination mass')
ax.grid(alpha=.15)
save(fig,'hansen_decay.pdf','src/georesilience/accessibility.py','plot of implemented exponential definition, h=100 m and R=500 m')

zones=gpd.read_file(RUNS/'population/zones.gpkg').set_index('zone_id')
nodes=gpd.read_file(RUNS/'population/network.gpkg',layer='nodes')
roads=gpd.read_file(RUNS/'population/network.gpkg',layer='edges')
for field,name,label,vmax in [('population','presentation_population.pdf','Allocated count (synthetic)',9),
                              ('vuln','presentation_vulnerability.pdf','Structural accessibility loss (%)',30)]:
    fig,ax=plt.subplots(figsize=(5.4,4.8))
    roads.plot(ax=ax,color='#BCC8CD',linewidth=1.4)
    values=nodes[field].to_numpy()*(100 if field=='vuln' else 1)
    scatter=ax.scatter(nodes.geometry.x,nodes.geometry.y,c=values,s=170,cmap='viridis',vmin=0,vmax=vmax,zorder=3)
    for row in nodes.itertuples():
        text=str(int(row.population)) if field=='population' else str(row.node_id)
        ax.annotate(text,(row.geometry.x,row.geometry.y),xytext=(8,7),textcoords='offset points',fontsize=13,color=NAVY)
    fig.colorbar(scatter,ax=ax,shrink=.8,label=label)
    ax.set_xlim(nodes.geometry.x.min()-35,nodes.geometry.x.max()+40)
    ax.set_ylim(nodes.geometry.y.min()-30,nodes.geometry.y.max()+35)
    ax.set_aspect('equal');ax.axis('off')
    save(fig,name,'results/ticket14-demo/population/network.gpkg')
fig,ax=plt.subplots(figsize=(5.4,4.8))
roads.plot(ax=ax,column='eff_drop_pop',cmap='YlOrRd',linewidth=4,vmin=0,
           legend=True,legend_kwds={'label':'Population-weighted efficiency loss (fraction)','shrink':.8})
for row in roads.itertuples():
    point=row.geometry.interpolate(.5,normalized=True)
    ax.text(point.x,point.y,str(row.link_id),fontsize=12,ha='center',va='center',color=NAVY,
            bbox={'facecolor':'white','edgecolor':'none','alpha':.9,'pad':1})
ax.set_xlim(nodes.geometry.x.min()-25,nodes.geometry.x.max()+25)
ax.set_ylim(nodes.geometry.y.min()-25,nodes.geometry.y.max()+25)
ax.set_aspect('equal');ax.axis('off')
save(fig,'presentation_criticality.pdf','results/ticket14-demo/population/network.gpkg')
macros={
 'MeanUniformLoss':f"{100*uniform['metrics']['accessibility']['vuln']['mean']:.2f}",
 'MeanPopulationLoss':f"{100*pop['metrics']['accessibility']['vuln_pop']['mean']:.2f}",
 'PninetyUniformLoss':f"{100*uniform['metrics']['accessibility']['vuln']['p90']:.2f}",
 'PninetyPopulationLoss':f"{100*pop['metrics']['accessibility']['vuln_pop']['p90']:.2f}",
 'UniformConnectivity':f"{100*pop['reliability']['conn_reliability']:.4f}",
 'PopulationConnectivity':f"{100*pop['reliability']['conn_reliability_pop']:.4f}",
 'PopulationRetained':f"{100*(1-pop['reliability']['expected_pop_cut_off']/45):.4f}",
 'ExpectedCutOff':f"{pop['reliability']['expected_pop_cut_off']:.6f}",
 'ExampleComposite':f"{weighted['composite_user_weighted']:.4f}",
 'WestVuln':f"{100*zones.loc['1','pop_weighted_vuln']:.2f}",
 'EastVuln':f"{100*zones.loc['2','pop_weighted_vuln']:.2f}",
}
critical_rows=''.join(f'{int(row.link_id)} & {100*row.eff_drop:.2f} & {100*row.eff_drop_pop:.2f}\\\\\n'
                      for row in roads.sort_values(['eff_drop_pop','link_id'],ascending=[False,True]).head(3).itertuples())
(HERE/'results_macros.tex').write_text('% Values derived from local saved outputs by build_assets.py\n'+''.join(f'\\newcommand{{\\{key}}}{{{value}}}\n' for key,value in macros.items())+'\\newcommand{\\CriticalRows}{'+critical_rows+'}\n',encoding='utf-8')
(HERE/'asset_sources.json').write_text(json.dumps(sources,indent=2)+'\n')
print(f'Built {len(sources)} source-tracked presentation assets')
