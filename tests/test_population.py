"""Ticket 12: cell allocation, acquisition and independent weighted references."""

from itertools import combinations, product
import json
import math
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
from pyproj import Transformer
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box
from shapely.ops import transform
import yaml

from georesilience.accessibility import compute_accessibility
from georesilience.config import AccessibilityConfig, CriticalityConfig, PopulationConfig, RunConfig, load_config
from georesilience.connectivity import ConnectivityTopology, compute_connectivity
from georesilience.config import ReliabilityConfig
from georesilience.criticality import compute_criticality
from georesilience.links import _link_rows
from georesilience.pipeline import run
from georesilience.population import (WORLDPOP_ALIAS, acquire_population, allocate_population,
                                      parse_catalogue, prepare_population, sha256_file)
from georesilience.removal import AffectedSourceRecompute
from georesilience.screening import screen_network

FIXTURE = Path(__file__).parent / 'fixtures/worldpop-mdv-cic2020_100m.json'
BUDGET = 2**20


def raster_fixture(tmp_path, values=None, crs=32644):
    path = tmp_path / 'counts.tif'
    values = np.arange(1, 10, dtype='float32').reshape(3, 3) if values is None else np.array(values, dtype='float32')
    affine = from_origin(500000, 1900300, 100, 100)
    if crs == 4326:
        affine = from_origin(78, 17.003, .001, .001)
    with rasterio.open(path, 'w', driver='GTiff', height=3, width=3, count=1,
                       dtype='float32', crs=crs, transform=affine, nodata=-9999) as raster:
        raster.write(values, 1)
    return path, affine


def cell_graph(affine, crs=32644, cells=8):
    graph = nx.MultiDiGraph(crs='EPSG:32644', simplified=True)
    projection = Transformer.from_crs(crs, 32644, always_xy=True)
    for node in range(cells):
        xy = rasterio.transform.xy(affine, node // 3, node % 3)
        x, y = projection.transform(*xy)
        graph.add_node(node, x=x, y=y)
    for way, (u, v) in enumerate(zip(range(cells-1), range(1, cells)), 1):
        distance = math.dist((graph.nodes[u]['x'], graph.nodes[u]['y']), (graph.nodes[v]['x'], graph.nodes[v]['y']))
        for a, b in ((u, v), (v, u)):
            graph.add_edge(a, b, length=distance, osmid=way, highway='residential')
    return graph


def boundary_for(affine, crs=32644, cols=3):
    left, top = affine * (0, 0)
    right, bottom = affine * (cols, 3)
    return transform(Transformer.from_crs(crs, 4326, always_xy=True).transform, box(left, bottom, right, top))


@pytest.mark.parametrize('crs', [32644, 4326])
def test_3x3_allocation_and_far_cell(tmp_path, crs):
    path, affine = raster_fixture(tmp_path, crs=crs)
    graph = cell_graph(affine, crs=crs)
    weights, summary = allocate_population(graph, boundary_for(affine, crs), path, 10)
    np.testing.assert_array_equal(weights, np.arange(1, 9))
    assert summary == {'total': 45, 'allocated': 36, 'unallocated': 9, 'unallocated_pct': 20}


def test_clipping_nodata_zero_and_no_overlap(tmp_path):
    path, affine = raster_fixture(tmp_path)
    graph = cell_graph(affine, cells=9)
    weights, totals = allocate_population(graph, boundary_for(affine, cols=2), path, 10)
    np.testing.assert_array_equal(weights, [1, 2, 0, 4, 5, 0, 7, 8, 0])
    assert totals['allocated'] == 27
    path, affine = raster_fixture(tmp_path, [[-9999, 0, -1], [float('nan'), 2, 0], [0, 0, 0]])
    weights, totals = allocate_population(graph, boundary_for(affine), path, 10)
    assert weights.sum() == totals['total'] == 2
    weights, totals = allocate_population(graph, box(80, 16, 80.1, 16.1), path, 10)
    assert weights.sum() == totals['total'] == 0
    path, affine = raster_fixture(tmp_path, np.zeros((3, 3)))
    weights, totals = allocate_population(graph, boundary_for(affine), path, 10)
    assert weights.sum() == totals['total'] == 0


def test_allocation_stable_ties_and_boundary_error(tmp_path):
    path, affine = raster_fixture(tmp_path, [[0, 0, 0], [0, 10, 0], [0, 0, 0]])
    graph = nx.MultiDiGraph(crs=32644)
    graph.add_node(10, x=500100., y=1900150.)
    graph.add_node(2, x=500200., y=1900150.)
    weights, summary = allocate_population(graph, boundary_for(affine), path, 50)
    np.testing.assert_array_equal(weights, [0, 10])
    assert summary['unallocated'] == 0
    with pytest.raises(ValueError, match=r'population needs input.source place \| polygon \| bbox'):
        allocate_population(graph, None, path, 10)
    for source in ('graphml', 'osm_xml'):
        with pytest.raises(ValueError, match='population needs input.source'):
            RunConfig(input={'source': source, 'path': path}, population={'worldpop': str(path)})


def test_catalogue_recorded_response_year_and_errors():
    payload = json.loads(FIXTURE.read_text())
    row = parse_catalogue(payload, 2020, 'MDV')
    assert row['alias'] == WORLDPOP_ALIAS and row['year'] == 2020
    assert row['url'].endswith('mdv_ppp_2020_constrained.tif')
    with pytest.raises(ValueError, match='available years: 2020'):
        parse_catalogue(payload, 2021, 'MDV')
    with pytest.raises(ValueError, match='data list'):
        parse_catalogue({}, 2020, 'MDV')
    with pytest.raises(ValueError, match='exactly one GeoTIFF'):
        parse_catalogue({'data': [{'popyear': '2020', 'files': []}]}, 2020, 'MDV')


class Response:
    def __init__(self, *, payload=None, content=b'', headers=None):
        self.payload, self.content, self.headers = payload, content, headers or {}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def raise_for_status(self):
        pass
    def json(self):
        return self.payload
    def iter_content(self, chunk_size):
        yield self.content[:100]
        yield self.content[100:]


def test_auto_stream_cache_sha_size_and_partial_cleanup(tmp_path, monkeypatch):
    path, affine = raster_fixture(tmp_path)
    content = path.read_bytes()
    payload = json.loads(FIXTURE.read_text())
    payload['data'][0]['size_bytes'] = len(content)
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response(payload=payload) if 'params' in kwargs else Response(content=content)
    monkeypatch.setattr('georesilience.population.requests.get', get)
    config = PopulationConfig(worldpop='auto', iso3='MDV', cache_dir=tmp_path/'cache')
    cached, provenance = acquire_population(config)
    assert len(calls) == 2 and calls[1][1]['stream']
    assert cached.read_bytes() == content and provenance['sha256'] == sha256_file(path)
    monkeypatch.setattr('georesilience.population.requests.get', lambda *a, **k: pytest.fail('cache must make no request'))
    assert acquire_population(config) == (cached, provenance)
    cached.write_bytes(content + b'x')
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        acquire_population(config)
    monkeypatch.setattr('georesilience.population.requests.get', get)
    config.cache_dir = tmp_path/'bad-size'
    payload['data'][0]['size_bytes'] += 1
    with pytest.raises(ValueError, match='size mismatch'):
        acquire_population(config)
    assert list(config.cache_dir.iterdir()) == []


def test_local_provenance_and_config_validation(tmp_path):
    path, affine = raster_fixture(tmp_path)
    graph = cell_graph(affine)
    result = prepare_population(graph, boundary_for(affine), PopulationConfig(worldpop=str(path)))
    assert result.provenance['path'] == str(path.resolve())
    assert result.provenance['sha256'] == sha256_file(path)
    assert prepare_population(graph, None, PopulationConfig()) is None
    for kwargs in ({'snap_max_m': -1}, {'snap_max_m': float('inf')}, {'iso3': 'india'}, {'worldpop': ''},
                   {'product': 'density'}):
        with pytest.raises(ValueError):
            PopulationConfig(**kwargs)


def metric_graph(kind='mixed'):
    graph = nx.MultiDiGraph(crs=32644, simplified=True)
    for node in range(5):
        graph.add_node(node, x=500000. + 100*node, y=1900000.)
    edges = [(0, 1), (1, 2), (2, 0), (2, 3), (3, 4)] if kind == 'mixed' else [(0, 1), (1, 2), (2, 3), (3, 4)]
    for way, (u, v) in enumerate(edges, 1):
        for a, b in ((u, v), (v, u)):
            graph.add_edge(a, b, length=100. * way, osmid=way, highway='residential')
    return graph


def screened(graph, analytic=True):
    links = _link_rows(graph)
    for row in links:
        row['edge_betweenness'] = 1.
    screen = screen_network(graph, links, dict.fromkeys(graph, 0), CriticalityConfig(
        all=True, bridge_analytic_max_side=2000 if analytic else 0))
    return links, screen


@pytest.mark.parametrize('analytic', [False, True])
@pytest.mark.parametrize('cache', [False, None])
def test_joint_criticality_matches_independent_weighted_damage(analytic, cache):
    graph = metric_graph()
    links, screen = screened(graph, analytic)
    pop = np.array([2, 0, 7, 3, 11.])
    kwargs = dict(n_jobs=1, budget_bytes=BUDGET, cache=cache)
    joint = compute_criticality(graph, links, screen, population_weights=pop, **kwargs)
    weighted = compute_criticality(graph, links, screen, weights=pop, **kwargs)
    before = dict(nx.all_pairs_dijkstra_path_length(graph, weight='length'))
    baseline_inverse = sum(pop[i] * pop[j] / distance for i, distances in before.items()
                           for j, distance in distances.items() if i != j)
    denominator = sum(pop[i] * pop[j] for i in graph for j in graph if i != j)
    for row in links:
        key = row['link_id']
        for field in ('eff_drop', 'disc_pair_frac'):
            assert joint.link_metrics[key][field+'_pop'] == weighted.link_metrics[key][field]
        closed = graph.copy()
        closed.remove_edges_from(row['_edges'])
        after = dict(nx.all_pairs_dijkstra_path_length(closed, weight='length'))
        inverse = sum(pop[i] * pop[j] / distance for i, distances in after.items()
                      for j, distance in distances.items() if i != j)
        disconnected = sum(pop[i] * pop[j] for i in graph for j in graph if i != j and j not in after[i])
        assert joint.link_metrics[key]['eff_drop_pop'] == pytest.approx((baseline_inverse-inverse)/baseline_inverse)
        assert joint.link_metrics[key]['disc_pair_frac_pop'] == pytest.approx(disconnected/denominator)
        if key in screen.analytic_bridges:
            changed = nx.Graph(graph)
            changed.remove_edge(row['_u'], row['_v'])
            sides = list(nx.connected_components(changed))
            small = min(sides, key=len)
            assert joint.link_metrics[key]['people_disconnected'] == pop[list(small)].sum()
        else:
            assert math.isnan(joint.link_metrics[key]['people_disconnected'])


def test_all_ones_exact_and_shared_traversals(monkeypatch):
    graph = metric_graph()
    links, screen = screened(graph)
    kwargs = dict(n_jobs=1, budget_bytes=BUDGET)
    calls = []
    original = AffectedSourceRecompute.affected_sources
    def affected(self, link, **kwargs):
        calls.append(link)
        return original(self, link, **kwargs)
    monkeypatch.setattr(AffectedSourceRecompute, 'affected_sources', affected)
    critical = compute_criticality(graph, links, screen, population_weights=np.ones(5), **kwargs)
    assert len(calls) == len(screen.candidate_links - screen.analytic_bridges)
    for values in critical.link_metrics.values():
        assert values['eff_drop'] == values['eff_drop_pop']
        assert values['disc_pair_frac'] == values['disc_pair_frac_pop']
    calls.clear()
    access = compute_accessibility(graph, links, screen, AccessibilityConfig(k=2), population_weights=np.ones(5), **kwargs)
    assert len(calls) == len(screen.candidate_links - screen.analytic_bridges)
    for values in access.node_metrics.values():
        for name in ('hansen_a', 'vuln', 'vuln_k2', 'vuln_link_id', 'vuln_k2_link_ids'):
            assert values[name] == values[name+'_pop']
    for values in access.link_metrics.values():
        assert values['access_drop'] == values['access_drop_pop']
        assert values['access_rank'] == values['access_rank_pop']
    assert access.computation['accessibility_shared_pair_trials'] == access.summary['k2_pair_trials']
    reliability = compute_connectivity(graph, links, ReliabilityConfig(samples=512), {}, seed=42,
                                        population_weights=np.ones(5), **kwargs)
    np.testing.assert_array_equal(reliability.pair_fractions, reliability.pair_fractions_pop)
    assert reliability.summary['conn_reliability'] == reliability.summary['conn_reliability_pop']


@pytest.mark.parametrize('analytic', [False, True])
def test_joint_accessibility_independent_networkx_and_population_pair_selection(analytic):
    graph = metric_graph()
    links, screen = screened(graph, analytic)
    pop = np.array([1, 0, 50, 2, 7.])
    config = AccessibilityConfig(half_distance_km=.4, cutoff_factor=2, k=2, all_links=True)
    result = compute_accessibility(graph, links, screen, config, n_jobs=1, budget_bytes=BUDGET, population_weights=pop)
    def scores(removed=()):
        changed = graph.copy()
        for row in links:
            if row['link_id'] in removed:
                changed.remove_edges_from(row['_edges'])
        return np.array([sum(pop[j] * 2 ** (-d/400) for j, d in nx.single_source_dijkstra_path_length(
            changed, i, cutoff=800, weight='length').items() if j != i) for i in graph])
    before = scores()
    np.testing.assert_allclose([row['hansen_a_pop'] for row in result.node_metrics.values()], before, atol=1e-12)
    for row in links:
        loss = before - scores([row['link_id']])
        assert result.link_metrics[row['link_id']]['access_drop_pop'] == pytest.approx(loss.sum()/before.sum(), abs=1e-12)
    for i, row in result.node_metrics.items():
        if before[i] == 0:
            assert math.isnan(row['vuln_pop'])
            continue
        selected = list(map(int, row['access_top3_link_ids_pop'].split(';')))
        expected = max((before[i] - scores(pair)[i])/before[i] for pair in combinations(selected, 2))
        assert row['vuln_k2_pop'] == pytest.approx(expected, abs=1e-12)
    assert any(row['access_top3_link_ids'] != row['access_top3_link_ids_pop'] for row in result.node_metrics.values())


def test_weighted_reliability_exact_enumeration_and_node_count_main_scc():
    graph = metric_graph()
    links, screen = screened(graph)
    pop = np.array([1, 2, 3, 100, 200.])
    topology = ConnectivityTopology(graph, links, population_weights=pop)
    probability = .35
    exact_score = exact_cut = 0.
    for up in product([False, True], repeat=len(links)):
        chance = math.prod(1-probability if active else probability for active in up)
        changed = nx.DiGraph()
        changed.add_nodes_from(graph)
        for row, active in zip(links, up):
            if active:
                changed.add_edges_from((u, v) for u, v, _ in row['_edges'])
        components = list(nx.strongly_connected_components(changed))
        main = min(components, key=lambda c: (-len(c), min(c)))
        denominator = sum(pop[i]*pop[j] for i in graph for j in graph if i != j)
        score = sum(pop[i]*pop[j] for c in components for i in c for j in c if i != j)/denominator
        actual, membership, _ = topology.evaluate(up, joint=True)
        assert actual[1] == pytest.approx(score, abs=1e-15)
        assert {i for i in graph if membership[i]} == main
        exact_score += chance*score
        exact_cut += chance*sum(pop[i] for i in graph if i not in main)
    probabilities = {int(row['osm_way_ids']): probability for row in links}
    result = compute_connectivity(graph, links, ReliabilityConfig(samples=20000, p0=probability, p0_sweep=[probability]),
                                  probabilities, seed=42, n_jobs=1, budget_bytes=8*BUDGET, population_weights=pop)
    assert result.summary['conn_reliability_pop'] == pytest.approx(exact_score, abs=.015)
    assert result.summary['expected_pop_cut_off'] == pytest.approx(exact_cut, abs=3)
    json.dumps(result.summary, allow_nan=False)


def test_zero_population_ratios_undefined_and_parallel_reproducibility():
    graph = metric_graph()
    links, screen = screened(graph)
    for pop in (np.zeros(5), np.array([0, 0, 10, 0, 0])):
        critical = compute_criticality(graph, links, screen, n_jobs=1, budget_bytes=BUDGET, population_weights=pop)
        assert all(math.isnan(row['eff_drop_pop']) and math.isnan(row['disc_pair_frac_pop'])
                   for row in critical.link_metrics.values())
        assert critical.summary['baseline_efficiency_pop'] is None
        json.dumps(critical.summary, allow_nan=False)
        access = compute_accessibility(graph, links, screen, AccessibilityConfig(k=2),
                                       n_jobs=1, budget_bytes=BUDGET, population_weights=pop)
        if not pop.any():
            assert access.summary['total_accessibility_pop'] == 0
            assert all(math.isnan(row['vuln_pop']) and math.isnan(row['vuln_k2_pop'])
                       for row in access.node_metrics.values())
        json.dumps(access.summary, allow_nan=False)
        reliability = compute_connectivity(graph, links, ReliabilityConfig(samples=512), {}, seed=42,
                                            n_jobs=1, budget_bytes=BUDGET, population_weights=pop)
        assert reliability.summary['conn_reliability_pop'] is None
    pop = np.array([1, 0, 50, 2, 7.])
    results = [compute_connectivity(graph, links, ReliabilityConfig(samples=32768), {}, seed=42,
               n_jobs=jobs, budget_bytes=8*BUDGET, population_weights=pop) for jobs in (1, 2)]
    assert [result.computation['reliability_workers'] for result in results] == [1, 2]
    np.testing.assert_array_equal(results[0].pair_fractions_pop, results[1].pair_fractions_pop)
    assert results[0].summary == results[1].summary


def test_pipeline_exports_provenance_and_overwrite(tmp_path, monkeypatch):
    path, affine = raster_fixture(tmp_path)
    graph = cell_graph(affine)
    boundary = boundary_for(affine)
    # Reuse real cleaning metadata for report schema without any OSM requests.
    import osmnx as ox
    from georesilience.network import load_and_clean
    source = tmp_path/'fixture.graphml'
    ox.save_graphml(graph, source)
    base = RunConfig(input={'path': source}, cleaning={'consolidate': False})
    cleaned, meta, cleaning = load_and_clean(base)
    meta['study_boundary_wkt'] = boundary.wkt
    monkeypatch.setattr('georesilience.pipeline.load_and_clean', lambda config: (cleaned, meta, cleaning))
    config = RunConfig(input={'source': 'bbox', 'bbox': list(boundary.bounds)}, population={'worldpop': str(path), 'snap_max_m': 10},
        cleaning={'consolidate': False}, analysis={'n_jobs': 1, 'max_memory_gb': .1},
        robustness={'steps': 1, 'failure_runs': 1, 'efficiency_sources': 8, 'removal': ['links']},
        reliability={'samples': 64, 'p0_sweep': [0]}, travel_time={'enabled': False}, accessibility={'k': 2},
        output={'dir': tmp_path/'output'})
    summary = run(config)
    out = config.output.dir
    nodes = gpd.read_file(out/'network.gpkg', layer='nodes')
    edges = gpd.read_file(out/'network.gpkg', layer='edges')
    assert {'population', 'hansen_a_pop', 'vuln_pop', 'vuln_k2_pop', 'vuln_link_id_pop', 'vuln_k2_link_ids_pop'} <= set(nodes)
    assert {'eff_drop_pop', 'disc_pair_frac_pop', 'access_drop_pop', 'access_rank_pop', 'people_disconnected'} <= set(edges)
    assert summary['population']['allocated'] == 36 and summary['population']['unallocated'] == 9
    assert 'conn_reliability_pop' in summary['reliability'] and 'expected_pop_cut_off' in summary['reliability']
    resolved = yaml.safe_load((out/'run_config.yaml').read_text())
    assert resolved['population_provenance']['sha256'] == sha256_file(path)
    assert load_config(out/'run_config.yaml').population == config.population
    report = (out/'report.txt').read_text()
    for label in ('Population', 'WorldPop is a modelled estimate, not a census', 'conn_reliability_pop',
                  'expected_pop_cut_off', 'vuln_k2_pop', 'people_disconnected'):
        assert label in report
    assert report.isascii() and max(map(len, report.splitlines())) <= 100
    assert (out/'figures/population_map.png').stat().st_size > 1000
    json.dumps(summary, allow_nan=False)
    config.population.worldpop = None
    config.output.figures = False
    run(config, overwrite=True)
    assert 'population' not in gpd.read_file(out/'network.gpkg', layer='nodes')
    assert not (out/'figures/population_map.png').exists()
    assert 'population' not in json.loads((out/'summary.json').read_text())


@pytest.mark.network
def test_live_maldives_auto_and_no_request_on_second_run(tmp_path, monkeypatch):
    config = PopulationConfig(worldpop='auto', iso3='MDV', cache_dir=tmp_path/'cache')
    path, provenance = acquire_population(config)
    with rasterio.open(path) as raster:
        assert raster.crs.to_epsg() == 4326 and raster.count == 1
    assert provenance['alias'] == WORLDPOP_ALIAS
    monkeypatch.setattr('georesilience.population.requests.get', lambda *a, **k: pytest.fail('cached run contacted network'))
    assert acquire_population(config) == (path, provenance)


def test_seeded_200_node_spatial_population_against_networkx():
    # A city-like geometric graph, with directed non-tree roads and a tail that
    # exercises analytic bridges. Screening keeps this ordinary check bounded.
    from test_criticality import spatial_fixture
    graph = spatial_fixture(42)
    links = _link_rows(graph)
    for row in links:
        row['edge_betweenness'] = 1.
    screen = screen_network(graph, links, dict.fromkeys(graph, 0), CriticalityConfig(
        k_betweenness=3, k_detour=2, k_nodes=0, exact_info_max_nodes=0))
    pop = np.random.default_rng(12).integers(0, 100, len(graph)).astype(float)
    critical = compute_criticality(graph, links, screen, n_jobs=1, budget_bytes=8*BUDGET,
                                    population_weights=pop)
    settings = AccessibilityConfig(half_distance_km=.15, cutoff_factor=3)
    access = compute_accessibility(graph, links, screen, settings, n_jobs=1, budget_bytes=8*BUDGET,
                                    population_weights=pop)
    def reference(changed):
        distances = dict(nx.all_pairs_dijkstra_path_length(changed, weight='length'))
        inverse = sum(pop[i]*pop[j]/d for i, row in distances.items() for j, d in row.items() if i != j)
        accessible = np.array([sum(pop[j] * 2**(-d/150) for j, d in distances[i].items()
                                   if i != j and d <= 450) for i in graph])
        lost = sum(pop[i]*pop[j] for i in graph for j in graph if i != j and j not in distances[i])
        return inverse, accessible, lost
    baseline_inverse, baseline_access, _ = reference(graph)
    np.testing.assert_allclose([row['hansen_a_pop'] for row in access.node_metrics.values()],
                               baseline_access, rtol=0, atol=1e-9)
    denominator = sum(pop[i]*pop[j] for i in graph for j in graph if i != j)
    evaluated = screen.candidate_links | screen.analytic_bridges
    for row in links:
        if row['link_id'] not in evaluated:
            continue
        changed = graph.copy()
        changed.remove_edges_from(row['_edges'])
        inverse, accessible, disconnected = reference(changed)
        actual = critical.link_metrics[row['link_id']]
        assert actual['eff_drop_pop'] == pytest.approx((baseline_inverse-inverse)/baseline_inverse, abs=1e-9)
        assert actual['disc_pair_frac_pop'] == pytest.approx(disconnected/denominator, abs=1e-9)
        assert access.link_metrics[row['link_id']]['access_drop_pop'] == pytest.approx(
            (baseline_access-accessible).sum()/baseline_access.sum(), abs=1e-9)


def test_population_distance_reductions_with_two_workers_and_small_chunks():
    graph = metric_graph()
    links, screen = screened(graph)
    pop = np.array([1, 0, 50, 2, 7.])
    settings = AccessibilityConfig(half_distance_km=.4, cutoff_factor=2, k=2)
    criticals = [compute_criticality(graph, links, screen, n_jobs=jobs, budget_bytes=3500,
                 cache=False, population_weights=pop) for jobs in (1, 2)]
    accesses = [compute_accessibility(graph, links, screen, settings, n_jobs=jobs, budget_bytes=3500,
                population_weights=pop) for jobs in (1, 2)]
    assert accesses[1].computation['accessibility_workers'] == 2
    for row in links:
        key = row['link_id']
        for name in ('eff_drop', 'eff_drop_pop', 'disc_pair_frac', 'disc_pair_frac_pop'):
            assert criticals[0].link_metrics[key][name] == pytest.approx(criticals[1].link_metrics[key][name], abs=1e-12)
        for name in ('access_drop', 'access_drop_pop'):
            assert accesses[0].link_metrics[key][name] == pytest.approx(accesses[1].link_metrics[key][name], abs=1e-12)
    for node in graph:
        for name in ('hansen_a', 'hansen_a_pop', 'vuln', 'vuln_pop', 'vuln_k2', 'vuln_k2_pop'):
            assert accesses[0].node_metrics[node][name] == pytest.approx(accesses[1].node_metrics[node][name], abs=1e-12)
