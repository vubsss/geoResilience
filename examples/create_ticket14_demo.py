"""Offline scorecard/report examples with independent exported-result checks."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import osmnx as ox
from pyproj import Transformer
import yaml

from create_ticket13_demo import create_examples
from georesilience.config import RunConfig
from georesilience.pipeline import run


HEADINGS = ('Scorecard', 'Data and coverage warnings', 'Cleaning', 'Centralities', 'Network class',
            'Redundancy', 'Critical links', 'Robustness', 'Failure probabilities', 'Connectivity reliability',
            'Travel-time reliability', 'Accessibility', 'Population', 'Zones', 'Method notes')


def verify(out):
    summary = json.loads((out/'summary.json').read_text())
    nodes = gpd.read_file(out/'network.gpkg', layer='nodes')
    links = gpd.read_file(out/'network.gpkg', layer='edges')
    population = 'population' in summary
    scores = summary['scorecard']['normalised_scores']
    metric = summary['metrics']
    if 'links' in metric['robustness']:
        for key, field in [('robustness_attack','auc_attack_S'),('robustness_failure','auc_failure_S')]:
            assert scores[key] == metric['robustness']['links'][field]
    active = links.loc[~links.is_self_loop.astype(bool)]
    assert np.isclose(scores['redundancy_bridges'], 1-active.is_bridge.mean())
    finite = active.detour_ratio[np.isfinite(active.detour_ratio)]
    if len(finite):
        assert np.isclose(scores['redundancy_detour'], 1/np.median(finite))
    reliability_key = 'conn_reliability_pop' if population else 'conn_reliability'
    assert scores['reliability'] == summary['reliability'][reliability_key]
    column = 'vuln_pop' if population else 'vuln'
    defined = nodes[column][np.isfinite(nodes[column])]
    if len(defined):
        assert np.isclose(scores['accessibility'], 1-np.mean(defined))
    else:
        assert scores['accessibility'] is None
    if 'composite_user_weighted' in summary:
        weights = summary['scorecard']['composite']['supplied_weights']
        expected = sum(weights[key]*scores[key] for key in weights)/sum(weights.values())
        assert np.isclose(expected, summary['composite_user_weighted'])
    else:
        assert 'composite' not in summary['scorecard']
    transformer = Transformer.from_crs(nodes.crs,4326,always_xy=True)
    for kind, layer, id_field in [('critical_links',links,'link_id'),('vulnerable_nodes',nodes,'node_id')]:
        indexed = layer.set_index(id_field)
        for row in summary['critical_tables']['top20_'+kind]:
            geometry = indexed.loc[row[id_field]].geometry
            point = geometry.interpolate(.5,normalized=True) if kind=='critical_links' else geometry
            lon,lat = transformer.transform(point.x,point.y)
            assert np.allclose([row['longitude'],row['latitude']],[lon,lat],rtol=0,atol=1e-9)
    report = (out/'report.txt').read_text()
    assert report.isascii() and max(map(len,report.splitlines())) <= 100
    positions = [report.splitlines().index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)
    assert (out/'figures/scorecard.png').stat().st_size > 1000
    return {'scores':scores,'composite_user_weighted':summary.get('composite_user_weighted'),
            'population_present':population,'report_max_width':max(map(len,report.splitlines())),
            'locator_coordinates_verified':True,'headline_values_verified':True}


def create_demo(folder, results):
    folder,results = Path(folder).resolve(),Path(results).resolve()
    create_examples(folder,results)
    graph = ox.load_graphml(folder/'grid.graphml')
    settings = yaml.safe_load((folder/'population.yaml').read_text())
    settings['composite'] = {'weights':{'robustness_attack':3,'robustness_failure':1,'redundancy_bridges':1,
                                       'redundancy_detour':1,'reliability':2,'accessibility':2}}
    settings['output']['dir'] = str(results/'user-weighted')
    (folder/'user-weighted.yaml').write_text(yaml.safe_dump(settings,sort_keys=False))
    with patch('georesilience.network.ox.graph_from_bbox',side_effect=lambda **_:graph.copy()):
        run(RunConfig.model_validate(settings),overwrite=True)
    settings = yaml.safe_load((folder/'uniform.yaml').read_text())
    settings['robustness']['removal'] = ['nodes']
    settings['accessibility']['half_distance_km'] = .0001
    settings['travel_time']['enabled'] = True
    settings['output']['dir'] = str(results/'missing-metrics')
    (folder/'missing-metrics.yaml').write_text(yaml.safe_dump(settings,sort_keys=False))
    run(RunConfig.model_validate(settings),overwrite=True)
    verification = {name:verify(results/name) for name in ('uniform','population','user-weighted','missing-metrics')}
    (results/'verification.json').write_text(json.dumps(verification,indent=2,allow_nan=False)+'\n')
    print(f'Verified Ticket 14 examples in {results}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path('data/ticket14-demo'))
    parser.add_argument('--results',type=Path,default=Path('results/ticket14-demo'))
    args = parser.parse_args()
    create_demo(args.out,args.results)
