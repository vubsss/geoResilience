"""Independent zone arithmetic, spatial edge cases and pipeline invariance."""

import json
import math

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
import pytest
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, box

from georesilience.config import RunConfig, ZonesConfig, load_config
from georesilience.figures import write_zones_figure
from georesilience.links import _link_rows
from georesilience.pipeline import run
from georesilience.zones import aggregate_zones, load_zones, zones_report


def zone_file(tmp_path, geometries=None, ids=None, crs=32644):
    geometries = geometries if geometries is not None else [box(499950, 1899950, 500150, 1900250),
                                                           box(500150, 1899950, 500250, 1900250)]
    frame = gpd.GeoDataFrame({'ward': ids if ids is not None else ['1', '2'],
                             'label': [f'Zone {i}' for i in range(len(geometries))]},
                            geometry=geometries, crs=32644)
    path = tmp_path / 'wards.gpkg'
    frame.to_crs(crs).to_file(path, driver='GPKG', engine='pyogrio')
    return ZonesConfig(path=path, id_field='ward', name_field='label')


def grid():
    graph = nx.MultiDiGraph(crs='EPSG:32644', simplified=True)
    for y in range(3):
        for x in range(3):
            graph.add_node(y * 3 + x, x=500000. + x * 100, y=1900000. + y * 100)
    way = 0
    for y in range(3):
        for x in range(3):
            for dx, dy in ((1, 0), (0, 1)):
                if x + dx < 3 and y + dy < 3:
                    u, v = y * 3 + x, (y + dy) * 3 + x + dx
                    way += 1
                    for a, b in ((u, v), (v, u)):
                        graph.add_edge(a, b, length=100., osmid=way, highway='residential', name=f'Road {way}')
    return graph


def layers(population=True):
    graph = grid()
    nodes = gpd.GeoDataFrame({'node_id': [str(i) for i in graph],
                             'p_connected': [i / 10 for i in graph],
                             'vuln': [1 - i / 10 for i in graph],
                             'hansen_a': [i + 1. for i in graph],
                             'hansen_a_pop': [2 * (i + 1.) for i in graph]},
                            geometry=[Point(d['x'], d['y']) for _, d in graph.nodes(data=True)], crs=32644)
    if population:
        nodes['population'] = np.arange(1., 10.)
        nodes['vuln_pop'] = .123  # This destination weighting must not replace structural zone vuln.
    links = gpd.GeoDataFrame([{k: v for k, v in row.items() if not k.startswith('_')}
                              for row in _link_rows(graph)], crs=32644)
    links['is_bridge'] = links.link_id % 2 == 0
    links['crit_rank'] = np.arange(1., len(links) + 1)
    links['access_rank'] = np.arange(45., 45 + len(links))
    return nodes, links


def test_two_square_grid_hand_computed_inventory_and_weighted_metrics(tmp_path):
    zones = load_zones(zone_file(tmp_path), 32644)
    nodes, links = layers()
    result = aggregate_zones(zones, nodes, links)
    first, second = result.zones.iloc[0], result.zones.iloc[1]
    assert [first.n_nodes, second.n_nodes] == [6, 3]
    assert [first.n_links, second.n_links] == [10, 2]
    assert [first.road_km, second.road_km] == pytest.approx([1, .2])
    assert [first.population, second.population] == [27, 18]
    assert first.area_km2 == pytest.approx(.06)
    assert first.road_density_km_per_km2 == pytest.approx(1 / .06)
    assert first.road_km_per_1000_pop == pytest.approx(1000 / 27)
    indices = [0, 1, 3, 4, 6, 7]
    # Scalar reference, independent of the group/mean implementation.
    assert first.mean_p_connected == pytest.approx(sum(i / 10 for i in indices) / 6)
    assert first.pop_weighted_p_connected == pytest.approx(sum((i + 1) * i / 10 for i in indices) / 27)
    assert first.mean_vuln == pytest.approx(sum(1 - i / 10 for i in indices) / 6)
    assert first.pop_weighted_vuln == pytest.approx(sum((i + 1) * (1 - i / 10) for i in indices) / 27)
    assert first.expected_pop_cut_off == pytest.approx(sum((i + 1) * (1 - i / 10) for i in indices))
    assert first.mean_hansen_a == 4.5 and first.mean_hansen_a_pop == 9
    assert first.p90_vuln == pytest.approx(.95)
    assert first.rank_vulnerability == 1 and second.rank_vulnerability == 2
    assert first.n_top50_critical_links == 10 and second.n_top50_critical_links == 2
    for row in result.zones.itertuples():
        selected = result.links[result.links.zone_id == row.zone_id]
        assert row.bridge_km_frac == pytest.approx(sum(r.length_m for r in selected.itertuples() if r.is_bridge)
                                                 / sum(r.length_m for r in selected.itertuples()))
        assert row.n_top50_access_links == sum(1 <= r.access_rank <= 50 for r in selected.itertuples())
    assert result.summary['unassigned_nodes'] == result.summary['unassigned_links'] == 0
    assert result.summary['assigned_population'] == 45
    json.dumps(result.summary, allow_nan=False)
    assert 'zone_id' not in nodes and 'zone_id' not in links  # Caller layers untouched.


@pytest.mark.parametrize('ids', [['1', '1'], ['1', ' 1 '], [None, '2'], ['', '2']])
def test_invalid_ids(tmp_path, ids):
    with pytest.raises(ValueError, match='IDs'):
        load_zones(zone_file(tmp_path, ids=ids), 32644)


def test_overlap_shared_borders_and_field_validation(tmp_path):
    config = zone_file(tmp_path, geometries=[box(0, 0, 10, 10), box(9, 0, 20, 10)])
    with pytest.raises(ValueError, match='overlaps.*1 / 2'):
        load_zones(config, 32644)
    config = zone_file(tmp_path, geometries=[box(0, 0, 10, 10), box(10, 0, 20, 10)])
    assert len(load_zones(config, 32644)) == 2
    with pytest.raises(ValueError, match='zones.id_field'):
        ZonesConfig(path=config.path)
    for field in ('id_field', 'name_field'):
        with pytest.raises(ValueError, match='nonempty'):
            ZonesConfig(**{field: ' '})
    config.id_field = 'absent'
    with pytest.raises(ValueError, match='missing field'):
        load_zones(config, 32644)
    config.id_field, config.name_field = 'ward', 'absent'
    with pytest.raises(ValueError, match='missing field'):
        load_zones(config, 32644)


@pytest.mark.parametrize('geometry', [Point(1, 2), Polygon(),
    Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)]), None])
def test_bad_geometries(tmp_path, geometry):
    config = zone_file(tmp_path, geometries=[geometry], ids=['1'])
    with pytest.raises(ValueError, match='valid Polygon'):
        load_zones(config, 32644)


def test_missing_crs_empty_input_and_metric_crs(tmp_path):
    path = tmp_path / 'no-crs.gpkg'
    gpd.GeoDataFrame({'ward': ['1']}, geometry=[box(0, 0, 10, 10)]).to_file(path)
    with pytest.raises(ValueError, match='declare a CRS'):
        load_zones(ZonesConfig(path=path, id_field='ward'), 32644)
    config = zone_file(tmp_path)
    with pytest.raises(ValueError, match='metre units'):
        load_zones(config, 4326)
    with pytest.raises(ValueError, match='metre units'):
        load_zones(config, 2277)
    frame = gpd.GeoDataFrame({'ward': pd.Series(dtype=str)}, geometry=[], crs=32644)
    frame.to_file(path)
    with pytest.raises(ValueError, match='at least one'):
        load_zones(ZonesConfig(path=path, id_field='ward'), 32644)
    with pytest.raises(ValueError, match='does not exist'):
        load_zones(ZonesConfig(path=tmp_path / 'missing.geojson', id_field='ward'), 32644)
    assert load_zones(ZonesConfig(), 4326) is None


def test_holes_multipolygons_boundary_ties_numeric_ids_and_row_order(tmp_path):
    hole = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)],
                   holes=[[(2, 2), (4, 2), (4, 4), (2, 4)]])
    config = zone_file(tmp_path, [hole, MultiPolygon([box(10, 0, 20, 10), box(30, 0, 40, 10)])], ['10', '2'])
    zones = load_zones(config, 32644)
    nodes, links = layers(False)
    nodes = nodes.iloc[:6].copy()
    nodes.geometry = [Point(1, 1), Point(3, 3), Point(2, 3), Point(10, 5), Point(10, 10), Point(35, 5)]
    nodes.index = [9, 8, 7, 6, 5, 4]
    links = links.iloc[:1].copy()
    links.geometry = [LineString([(9, 5), (11, 5)])]
    result = aggregate_zones(zones, nodes, links)
    assert result.nodes.zone_id.fillna('-').tolist() == ['10', '-', '10', '2', '2', '2']
    assert result.links.zone_id.tolist() == ['2']
    assert result.summary['unassigned_nodes'] == 1
    # Reversing polygon input order must not alter any assignments.
    frame = gpd.read_file(config.path).iloc[::-1]
    frame.to_file(config.path)
    repeat = aggregate_zones(load_zones(config, 32644), nodes, links)
    assert repeat.summary == result.summary
    pd.testing.assert_series_equal(repeat.nodes.zone_id, result.nodes.zone_id)


def test_curved_and_multipart_midpoints_parallel_roads_and_self_loops(tmp_path):
    zones = load_zones(zone_file(tmp_path, [box(0, 0, 10, 20), box(10, 0, 30, 20)]), 32644)
    nodes, links = layers(False)
    nodes.geometry = [Point(1, 1)] * len(nodes)
    links = links.iloc[:4].copy()
    # Endpoint average (9,1) lies left, but half of this geometry lies right.
    links.geometry = [LineString([(1, 1), (20, 1), (20, 15), (17, 1)]),
                      MultiLineString([[(1, 1), (2, 1)], [(2, 1), (25, 1)]]),
                      LineString([(1, 1), (5, 1)]), LineString([(1, 1), (1, 1)])]
    links['is_self_loop'] = [False, False, False, True]
    links['length_m'] = [100., 100., 100., 999.]
    result = aggregate_zones(zones, nodes, links)
    assert result.links.zone_id.tolist() == ['2', '2', '1', '1']
    assert result.zones.road_km.tolist() == pytest.approx([.1, .2])
    assert result.summary['excluded_self_loop_links'] == 1
    assert sum(result.zones.n_links) == 3


def test_missing_metrics_empty_zones_zero_population_and_coverage(tmp_path):
    zones = load_zones(zone_file(tmp_path, [box(499950, 1899950, 500250, 1900250), box(0, 0, 10, 10)]), 32644)
    nodes, links = layers()
    nodes.loc[0, ['vuln', 'p_connected']] = np.nan
    result = aggregate_zones(zones, nodes, links)
    first, empty = result.zones.iloc[0], result.zones.iloc[1]
    assert first.n_valid_vuln == 8
    assert first.vuln_population_coverage_frac == pytest.approx(44 / 45)
    assert math.isnan(first.expected_pop_cut_off)  # Never silently underestimate an absolute loss.
    assert empty.n_nodes == empty.n_links == empty.population == empty.road_km == 0
    assert math.isnan(empty.mean_vuln) and pd.isna(empty.rank_vulnerability)
    assert empty.expected_pop_cut_off == 0
    nodes['population'] = 0.
    zero = aggregate_zones(zones, nodes, links)
    assert zero.zones['rank_vulnerability'].isna().all()
    assert zero.zones.expected_pop_cut_off.tolist() == [0, 0]
    assert zero.summary['rank_basis'] == 'pop_weighted_vuln'
    nodes = nodes.drop(columns=['population', 'hansen_a_pop', 'p_connected', 'vuln'])
    links = links.drop(columns=['crit_rank', 'access_rank', 'is_bridge'])
    missing = aggregate_zones(zones, nodes, links)
    for name in ('population', 'mean_hansen_a_pop', 'mean_p_connected', 'mean_vuln', 'bridge_km_frac',
                 'n_top50_critical_links', 'n_top50_access_links'):
        assert missing.zones[name].isna().all()
    assert missing.summary['top_10'] == []
    json.dumps(missing.summary, allow_nan=False)
    assert 'not computed' in '\n'.join(zones_report(missing.summary))
    write_zones_figure(missing.zones, missing.links, tmp_path / 'figures')
    assert (tmp_path / 'figures/zones_vulnerability_map.png').stat().st_size > 1000


def test_outside_totals_and_ranking_ties(tmp_path):
    zones = load_zones(zone_file(tmp_path, [box(499950, 1899950, 500050, 1900250),
                                         box(500150, 1899950, 500250, 1900250)], ['10', '2']), 32644)
    nodes, links = layers()
    nodes['vuln'] = .5
    result = aggregate_zones(zones, nodes, links)
    assert result.summary['unassigned_nodes'] == 3
    assert result.zones.population.sum() + result.summary['unassigned_population'] == nodes.population.sum()
    assert result.zones.road_km.sum() + result.summary['unassigned_road_km'] == pytest.approx(1.2)
    assert result.summary['top_10'][0]['zone_id'] == '2'


def pipeline_config(tmp_path):
    source = tmp_path / 'grid.graphml'
    ox.save_graphml(grid(), source)
    return RunConfig(input={'path': source}, cleaning={'consolidate': False},
                     analysis={'n_jobs': 1, 'max_memory_gb': .1},
                     robustness={'steps': 1, 'failure_runs': 1},
                     reliability={'samples': 64, 'p0': .2, 'p0_sweep': [.2]},
                     travel_time={'enabled': False}, output={'dir': tmp_path / 'output', 'figures': False})


def test_pipeline_exports_reprojection_invariance_resolved_config_and_cleanup(tmp_path):
    config = pipeline_config(tmp_path)
    baseline = run(config)
    before_nodes = gpd.read_file(config.output.dir / 'network.gpkg', layer='nodes')
    before_edges = gpd.read_file(config.output.dir / 'network.gpkg', layer='edges')
    assert 'zone_id' not in before_nodes and 'zone_id' not in before_edges
    assert not (config.output.dir / 'zones.gpkg').exists()
    config.zones = zone_file(tmp_path, crs=4326)
    frame = gpd.read_file(config.zones.path)
    frame['label'] = 'Ward వార్డు ' + 'long name ' * 15
    frame.to_file(config.zones.path)
    config.output.figures = True
    after = run(config, overwrite=True)
    for summary in (baseline, after):
        summary['meta'].pop('timestamp_utc')
        summary['metrics'].pop('runtime_seconds')
        summary.pop('coverage_warnings')  # Zone context changes, while network analysis does not.
    zones_summary = after.pop('zones')
    assert after == baseline
    out = config.output.dir
    for layer, before in (('nodes', before_nodes), ('edges', before_edges)):
        frame = gpd.read_file(out / 'network.gpkg', layer=layer)
        assert 'zone_id' in frame
        pd.testing.assert_frame_equal(frame.drop(columns='zone_id'), before)
    zones = gpd.read_file(out / 'zones.gpkg', layer='zones')
    assert zones.crs == before_nodes.crs and len(zones) == 2
    assert {'population', 'road_density_km_per_km2', 'rank_vulnerability'} <= set(zones)
    assert zones.population.isna().all()
    stored = json.loads((out / 'summary.json').read_text())
    assert stored['zones'] == zones_summary
    assert (out / 'figures/zones_vulnerability_map.png').stat().st_size > 1000
    report = (out / 'report.txt').read_text()
    assert all(label in report for label in ('Zones', 'Top 10 most vulnerable zones', 'Bottom 10', 'Unassigned nodes'))
    assert report.isascii() and max(map(len, report.splitlines())) <= 100
    resolved = load_config(out / 'run_config.yaml')
    assert resolved.zones == config.zones
    resolved.zones.path = None
    resolved.output.figures = False
    run(resolved, overwrite=True)
    assert not (out / 'zones.gpkg').exists() and not (out / 'figures/zones_vulnerability_map.png').exists()
    assert 'zone_id' not in gpd.read_file(out / 'network.gpkg', layer='nodes')
    assert 'zone_id' not in gpd.read_file(out / 'network.gpkg', layer='edges')


def test_invalid_zones_fail_before_population_or_analysis(tmp_path, monkeypatch):
    config = pipeline_config(tmp_path)
    config.zones = zone_file(tmp_path, [box(0, 0, 10, 10), box(1, 1, 5, 5)])
    def forbidden(*args, **kwargs):
        pytest.fail('invalid zones reached expensive analysis')
    monkeypatch.setattr('georesilience.pipeline.compute_centralities', forbidden)
    monkeypatch.setattr('georesilience.pipeline.prepare_population', forbidden)
    with pytest.raises(ValueError, match='overlaps'):
        run(config)


def test_population_pipeline_zone_cutoff_matches_network_and_uniform_outputs(tmp_path, monkeypatch):
    from test_population import raster_fixture, cell_graph, boundary_for
    from georesilience.network import load_and_clean

    raster, affine = raster_fixture(tmp_path)
    graph = cell_graph(affine, cells=9)
    source = tmp_path / 'cells.graphml'
    ox.save_graphml(graph, source)
    cleaned, meta, cleaning = load_and_clean(RunConfig(input={'path': source}, cleaning={'consolidate': False}))
    boundary = boundary_for(affine)
    meta['study_boundary_wkt'] = boundary.wkt
    monkeypatch.setattr('georesilience.pipeline.load_and_clean', lambda _: (cleaned.copy(), meta.copy(), cleaning.copy()))
    config = RunConfig(input={'source': 'bbox', 'bbox': list(boundary.bounds)},
                       population={'worldpop': str(raster), 'snap_max_m': 10},
                       cleaning={'consolidate': False}, analysis={'n_jobs': 1, 'max_memory_gb': .1},
                       robustness={'steps': 1, 'failure_runs': 1}, reliability={'samples': 512, 'p0': .4, 'p0_sweep': [.4]},
                       travel_time={'enabled': False}, output={'dir': tmp_path / 'population', 'figures': False})
    baseline = run(config)
    before = gpd.read_file(config.output.dir / 'network.gpkg', layer='nodes')
    config.zones = zone_file(tmp_path, [box(500000, 1900000, 500200, 1900300), box(500200, 1900000, 500300, 1900300)])
    summary = run(config, overwrite=True)
    zones = gpd.read_file(config.output.dir / 'zones.gpkg')
    assert zones.population.tolist() == [27, 18]
    assert zones.expected_pop_cut_off.sum() == pytest.approx(summary['reliability']['expected_pop_cut_off'], abs=1e-10)
    assert summary['zones']['assigned_population'] == summary['population']['allocated'] == 45
    after = gpd.read_file(config.output.dir / 'network.gpkg', layer='nodes')
    pd.testing.assert_frame_equal(after.drop(columns='zone_id'), before)
    assert summary['reliability'] == baseline['reliability']
    assert summary['metrics']['accessibility'] == baseline['metrics']['accessibility']
    json.dumps(summary, allow_nan=False)


def test_invalid_zone_overwrite_preserves_existing_results(tmp_path, monkeypatch):
    config = pipeline_config(tmp_path)
    config.output.dir.mkdir()
    marker = config.output.dir / 'summary.json'
    marker.write_text('existing result')
    config.zones = zone_file(tmp_path, [box(0, 0, 10, 10), box(1, 1, 5, 5)])
    with pytest.raises(ValueError, match='overlaps'):
        run(config, overwrite=True)
    assert marker.read_text() == 'existing result'


def test_geojson_optional_names_and_null_name_geopackage_roundtrip(tmp_path):
    config = zone_file(tmp_path)
    path = tmp_path / 'wards.geojson'
    gpd.read_file(config.path).to_crs(4326).to_file(path, driver='GeoJSON')
    config.path, config.name_field = path, None
    zones = load_zones(config, 32644)
    nodes, links = layers(False)
    result = aggregate_zones(zones, nodes, links)
    assert result.zones.zone_name.isna().all()
    result.zones.to_file(tmp_path / 'zones.gpkg', layer='zones')
    assert gpd.read_file(tmp_path / 'zones.gpkg').zone_name.isna().all()
    assert all(row['zone_name'] is None for row in result.summary['top_10'])


def test_top_bottom_ten_are_network_zone_ranks_with_unicode_names(tmp_path):
    config = zone_file(tmp_path, [box(i * 10, 0, (i + 1) * 10, 10) for i in range(25)],
                       [str(i + 1) for i in range(25)])
    zones = load_zones(config, 32644)
    zones['zone_name'] = 'Ward వార్డు ' + 'long name ' * 15
    nodes = gpd.GeoDataFrame({'vuln': np.arange(25) / 25},
                            geometry=[Point(i * 10 + 5, 5) for i in range(25)], crs=32644)
    links = gpd.GeoDataFrame({'is_self_loop': pd.Series(dtype=bool), 'length_m': pd.Series(dtype=float)},
                            geometry=[], crs=32644)
    result = aggregate_zones(zones, nodes, links)
    assert [row['zone_id'] for row in result.summary['top_10']] == [str(i) for i in range(25, 15, -1)]
    assert [row['zone_id'] for row in result.summary['bottom_10']] == [str(i) for i in range(1, 11)]
