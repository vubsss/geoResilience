"""Known-answer score/composite checks and end-to-end reporting contracts."""

from copy import deepcopy
import json
import math

import geopandas as gpd
import numpy as np
import osmnx as ox
import pytest
from pyproj import Transformer
from shapely.geometry import LineString, Point, box

from georesilience.cartography import decorate_map, map_canvas
from georesilience.config import COMPOSITE_KEYS, CompositeConfig, load_config
from georesilience.figures import FIGURE_FILENAMES, write_scorecard_figure
from georesilience.pipeline import run
from georesilience.reporting import build_locator_tables, collect_coverage_warnings
from georesilience.scorecard import build_scorecard, scorecard_report
from test_zones import pipeline_config, zone_file


def known_summary(population=False):
    result = {'metrics': {'robustness': {'parameters': {'f_max': .2},
                                        'links': {'auc_attack_S': .8, 'auc_failure_S': .9}},
                          'redundancy': {'non_self_loop_link_count': 4, 'bridge_frac': .25,
                                         'detour_ratio': {'median': 2}, 'finite_detour_count': 3, 'detour_none_count': 1},
                          'accessibility': {'vuln': {'mean': .3, 'p90': .5}, 'undefined_vulnerability_count': 2}},
              'reliability': {'conn_reliability': .6, 'ci_low': .5, 'ci_high': .7},
              'travel_time': {'status': 'skipped: no speed data'},
              'classification': {'network_label': 'inconclusive', 'label_basis': 'information',
                                 'distributions': {'information': {'reason': 'too few values'}}}}
    if population:
        result['population'] = {'allocated': 100, 'unallocated': 10, 'unallocated_pct': 10/110*100}
        result['reliability'].update(conn_reliability_pop=.4, conn_reliability_pop_ci_low=.3,
                                     conn_reliability_pop_ci_high=.5, expected_pop_cut_off=25,
                                     expected_pop_cut_off_ci_low=10, expected_pop_cut_off_ci_high=40)
        result['metrics']['accessibility']['vuln_pop'] = {'mean': .5, 'p90': .8}
    return result


@pytest.mark.parametrize('population', [False, True])
def test_scores_known_answers_variants_intervals_and_no_default_composite(population):
    summary = known_summary(population)
    untouched = deepcopy(summary)
    scorecard = build_scorecard(summary, CompositeConfig())
    expected = [.8, .9, .75, .5, .4 if population else .6, .5 if population else .7]
    assert list(scorecard['normalised_scores']) == list(COMPOSITE_KEYS)
    assert list(scorecard['normalised_scores'].values()) == pytest.approx(expected)
    rows = {row['key']: row for row in scorecard['rows']}
    assert rows['accessibility']['uniform_value'] == .3 and rows['accessibility']['uniform_p90'] == .5
    assert rows['reliability']['ci_95'] == ([.3, .5] if population else [.5, .7])
    if population:
        assert rows['population_connected']['value'] == .75
        assert rows['population_connected']['ci_95'] == pytest.approx([.6, .9])
        assert rows['accessibility']['p90'] == .8
    else:
        assert rows['population_connected']['value'] is None
        assert rows['accessibility']['population_reason'] == 'population disabled'
    assert rows['network_class']['value'] == 'inconclusive' and rows['network_class']['normalised_score'] is None
    assert rows['travel_time']['status'] == 'not computed' and 'speed data' in rows['travel_time']['reason']
    assert all(row['citation'] in scorecard['sources'] and row['meaning'] for row in scorecard['rows'])
    assert 'composite' not in scorecard and summary == untouched
    json.dumps(scorecard, allow_nan=False)


def test_composite_hand_calculation_normalized_weights_and_scale_invariance():
    config = CompositeConfig(weights={'robustness_attack': 2, 'reliability': 3, 'accessibility': 5})
    result = build_scorecard(known_summary(True), config)['composite']
    assert result['value'] == pytest.approx(.2*.8 + .3*.4 + .5*.5)
    assert result['weights'] == {'robustness_attack': .2, 'reliability': .3, 'accessibility': .5}
    assert result['supplied_weights'] == config.weights
    assert 'weights chosen by the user, not part of the method' in result['label']
    huge = build_scorecard(known_summary(True), CompositeConfig(weights={k: v*1e307 for k, v in config.weights.items()}))
    assert huge['composite']['value'] == pytest.approx(result['value'])
    assert sum(huge['composite']['weights'].values()) == pytest.approx(1)


@pytest.mark.parametrize('weights', [{}, {'reliability': 0}, {'unknown': 1}, {'network_class': 1},
    {'reliability_pop': 1}, {'accessibility': -1}, {'accessibility': math.nan}, {'accessibility': math.inf}])
def test_invalid_weight_configs(weights):
    with pytest.raises(ValueError):
        CompositeConfig(weights=weights)


def test_missing_weighted_metric_never_falls_back_and_even_zero_weight_requires_metric():
    summary = known_summary(True)
    summary['metrics']['accessibility'].pop('vuln_pop')
    result = build_scorecard(summary, CompositeConfig())
    assert result['normalised_scores']['accessibility'] is None
    assert result['rows'][5]['uniform_value'] == .3
    with pytest.raises(ValueError, match='accessibility.*not computed|not computed.*accessibility'):
        build_scorecard(summary, CompositeConfig(weights={'reliability': 1, 'accessibility': 0}))
    summary['metrics']['robustness'].pop('links')
    with pytest.raises(ValueError, match='link removal experiment not configured'):
        build_scorecard(summary, CompositeConfig(weights={'robustness_attack': 1}))


def test_empty_stages_zero_population_and_shorter_alternative_are_honest(tmp_path):
    empty = build_scorecard({}, CompositeConfig())
    assert all(value is None for value in empty['normalised_scores'].values())
    assert all(row['status'] == 'not computed' and row['reason'] for row in empty['rows'])
    assert 'not computed' in '\n'.join(scorecard_report(empty))
    write_scorecard_figure(empty, tmp_path)
    assert (tmp_path/'scorecard.png').stat().st_size > 1000
    summary = known_summary(True)
    summary['population']['allocated'] = 0
    summary['reliability']['conn_reliability_pop'] = None
    summary['metrics']['redundancy']['detour_ratio']['median'] = .5
    scorecard = build_scorecard(summary, CompositeConfig())
    assert scorecard['normalised_scores']['redundancy_detour'] == 2
    assert scorecard['normalised_scores']['reliability'] is None
    assert next(row for row in scorecard['rows'] if row['key']=='population_connected')['value'] is None
    summary['scorecard'] = scorecard
    assert any('exceeds 1' in row['message'] for row in collect_coverage_warnings(summary))
    write_scorecard_figure(scorecard, tmp_path, run_name='Shorter alternative')
    json.dumps(scorecard, allow_nan=False)


def test_locator_coordinates_geometry_midpoint_incident_names_and_population_order():
    nodes = gpd.GeoDataFrame({'node_id': ['2', '10'], 'vuln': [.2, .4], 'vuln_pop': [.8, .1]},
                            geometry=[Point(500000,1900000),Point(500100,1900000)],crs=32644)
    # Geometry midpoint differs from the endpoint average.
    links = gpd.GeoDataFrame({'link_id': [1,2], 'u': ['2','2'], 'v': ['10','10'],
                             'name': ['Main road','Other road'], 'highway': ['primary','residential'],
                             'osm_way_ids': ['7,9','3'], 'is_self_loop': [False,False],
                             'eff_drop': [.5,.2], 'eff_drop_pop': [.1,.9],
                             'disc_pair_frac': [0,0], 'disc_pair_frac_pop': [0,0]},
                            geometry=[LineString([(500000,1900000),(500100,1900000),(500100,1900100)]),
                                      LineString([(500000,1900000),(500100,1900000)])],crs=32644)
    uniform = build_locator_tables(nodes,links,False)
    weighted = build_locator_tables(nodes,links,True)
    assert [row['link_id'] for row in uniform['top20_critical_links']] == [1,2]
    assert [row['link_id'] for row in weighted['top20_critical_links']] == [2,1]
    assert [row['node_id'] for row in weighted['top20_vulnerable_nodes']] == ['2','10']
    row=uniform['top20_critical_links'][0]
    lon,lat=Transformer.from_crs(32644,4326,always_xy=True).transform(500100,1900000)
    assert [row['longitude'],row['latitude']] == pytest.approx([lon,lat],abs=1e-10)
    assert row['first_osm_way_id']=='7'
    row=weighted['top20_vulnerable_nodes'][0]
    assert row['name']=='Main road; Other road' and row['first_osm_way_id']=='3'
    assert row['highway']=='primary; residential'
    assert 'rank' not in links and 'rank' not in nodes
    json.dumps(weighted,allow_nan=False)


def test_all_coverage_diagnostics_and_constant_scores_are_retained():
    summary=known_summary(True)
    summary['cleaning']={'dropped_components':{'count':2,'nodes_dropped':4,'length_dropped_pct':12},'warnings':['boundary issue']}
    summary['reliability'].update(coverage={'proxy_length_pct':65}, warnings={'shown':['unmatched way'],'omitted_count':2},ci_low=.6,ci_high=.6)
    summary['metrics']['information']={'coverage':'candidate','candidate_count':2}
    summary['scorecard']=build_scorecard(summary,CompositeConfig())
    # Weighted row uses population CI; add a constant observed weighted interval.
    summary['scorecard']['rows'][4]['ci_95']=[.4,.4]
    messages='\n'.join(row['message'] for row in collect_coverage_warnings(summary))
    for fragment in ['65%', 'Unallocated population','candidate','boundary issue','unmatched way','additional warnings','speed data','rare unseen failures']:
        assert fragment in messages


def test_shared_map_has_known_metre_scale_north_title_and_equal_aspect():
    import matplotlib.pyplot as plt
    frame=gpd.GeoDataFrame(geometry=[box(500000,1900000,501000,1900500)],crs=32644)
    fig,ax=map_canvas(frame)
    decorate_map(ax,frame.crs,'Known metric','Fixture run')
    assert 'Fixture run' in ax.get_title() and 'Known metric' in ax.get_title()
    assert any(text.get_text()=='N' for text in ax.texts)
    assert any(text.get_text()=='200 m' for text in ax.texts)
    assert np.diff(ax.lines[0].get_xdata())[0]==pytest.approx(200)
    assert ax.get_aspect()==1
    plt.close(fig)


def test_pipeline_report_order_sources_outputs_and_composite_roundtrip(tmp_path):
    config=pipeline_config(tmp_path)
    graph=ox.load_graphml(config.input.path)
    long_name='Road వార్డు ' + 'long street name '*15 + '\nMethod notes'
    for _,_,_,data in graph.edges(keys=True,data=True):
        data['name']=long_name
    ox.save_graphml(graph,config.input.path)
    config.travel_time.enabled=True  # Grid has no usable maxspeed: real skip path.
    config.output.figures=True
    config.zones=zone_file(tmp_path)
    config.composite=CompositeConfig(weights={'robustness_attack':2,'reliability':3,'accessibility':5})
    summary=run(config)
    out=config.output.dir
    expected=sum(summary['scorecard']['normalised_scores'][key]*weight for key,weight in [('robustness_attack',.2),('reliability',.3),('accessibility',.5)])
    assert summary['composite_user_weighted']==pytest.approx(expected)
    assert json.loads((out/'summary.json').read_text())==json.loads(json.dumps(summary,allow_nan=False))
    assert load_config(out/'run_config.yaml').composite==config.composite
    report=(out/'report.txt').read_text()
    headings=['Scorecard','Data and coverage warnings','Cleaning','Centralities','Network class','Redundancy','Critical links','Robustness','Failure probabilities','Connectivity reliability','Travel-time reliability','Accessibility','Population','Zones','Method notes']
    positions=[report.splitlines().index(heading) for heading in headings]
    assert positions==sorted(positions)
    assert report.isascii() and max(map(len,report.splitlines()))<=100
    assert '\\u0c35' in report  # Unicode is preserved visibly through ASCII escaping.
    assert 'latitude | longitude' in report and 'weights chosen by the user' in report
    assert summary['travel_time']['status']=='skipped: no speed data'
    assert next(row for row in summary['scorecard']['rows'] if row['key']=='travel_time')['reason']=='skipped: no speed data'
    for name in FIGURE_FILENAMES:
        assert (out/'figures'/name).stat().st_size>1000
    assert (out/'figures/zones_vulnerability_map.png').stat().st_size>1000
    layers={name:gpd.read_file(out/'network.gpkg',layer=name) for name in ['nodes','edges']}
    assert layers['edges']['name'].eq(long_name).all()
    for row in summary['critical_tables']['top20_critical_links']:
        original=layers['edges'].set_index('link_id').loc[row['link_id']]
        assert row['eff_drop']==original.eff_drop
        assert f"{row['latitude']:.7f}" in report
    config.composite=CompositeConfig()
    config.output.figures=False
    config.zones.path=None
    after=run(config,overwrite=True)
    assert 'composite_user_weighted' not in after and 'composite' not in after['scorecard']
    assert not (out/'figures/scorecard.png').exists()


def test_missing_metric_composite_pipeline_fails_with_reason(tmp_path):
    config=pipeline_config(tmp_path)
    config.robustness.removal=['nodes']
    config.composite=CompositeConfig(weights={'robustness_attack':1})
    with pytest.raises(ValueError,match='not computed.*robustness_attack.*not configured'):
        run(config)
    assert not (config.output.dir/'summary.json').exists()
