"""Freeze and validate real OSM roads and WorldPop counts in central Male, Maldives.

Download once with --download-only, then run --offline to reuse checksum-verified inputs.
The offline runner injects the frozen OSM download at the source adapter; actual cleaning,
boundary handling, population allocation and all pipeline analyses still run normally.
"""

import argparse
from contextlib import nullcontext
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
from pyproj import Transformer
import rasterio
import requests
from rasterio.mask import mask
from rasterio.windows import from_bounds, Window
from shapely.geometry import LineString, Point, box, mapping
from shapely.ops import transform
import yaml

from georesilience.config import PopulationConfig, RunConfig
from georesilience.network import EXTRA_WAY_TAGS, _filter_drive, load_and_clean
from georesilience.pipeline import run, _versions
from georesilience.population import acquire_population, sha256_file

BBOX = (73.500, 4.167, 73.521, 4.181)  # west, south, east, north; central Male island
SNAPS = (100, 500)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def frozen_inputs(folder, offline=False, osm_api=False):
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / 'manifest.json'
    graph_path = folder / 'raw.graphml'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if tuple(manifest['bbox']) != BBOX:
            raise ValueError('Frozen study boundary differs from this experiment')
        for filename, digest in manifest['sha256'].items():
            path = folder / filename
            if not path.is_file() or sha256_file(path) != digest:
                raise ValueError(f'Frozen input missing or checksum mismatch: {path}')
        return ox.load_graphml(graph_path), manifest
    if offline:
        raise ValueError('Frozen inputs missing; first run with --download-only')
    ox.settings.cache_folder = folder / 'osm-cache'
    ox.settings.useful_tags_way = list(dict.fromkeys([*ox.settings.useful_tags_way, *EXTRA_WAY_TAGS]))
    ox.settings.requests_timeout = 180
    if osm_api:
        print('Obtaining central Male roads from the OSM map API', flush=True)
        xml_path = folder / 'map.osm'
        osm_url = 'https://www.openstreetmap.org/api/0.6/map'
        if not xml_path.exists():
            response = requests.get(osm_url, params={'bbox': ','.join(map(str, BBOX))}, timeout=(15, 120),
                                    headers={'User-Agent': 'GeoResilience course project validation', 'Accept': '*/*'})
            response.raise_for_status()
            xml_path.write_bytes(response.content)
        graph = ox.graph_from_xml(xml_path, simplify=False, retain_all=True)
        # The map API includes buildings and non-road ways. Retain tagged highways,
        # apply the project's documented XML drive filter, then clip shape nodes.
        graph.remove_edges_from([(u, v, key) for u, v, key, data in graph.edges(keys=True, data=True)
                                 if not data.get('highway')])
        graph = _filter_drive(graph)
        graph = ox.truncate.truncate_graph_bbox(graph, bbox=BBOX, truncate_by_edge=False)
        source = 'OSM map API XML; tagged highways and project XML drive filter; clipped to fixed bbox'
        downloaded = datetime.fromtimestamp(xml_path.stat().st_mtime, timezone.utc).isoformat()
    else:
        print('Downloading central Male OSM drive roads', flush=True)
        graph = ox.graph_from_bbox(bbox=BBOX, network_type='drive', simplify=False, retain_all=True)
        source, osm_url = 'OSMnx Overpass drive download', ox.settings.overpass_url
        downloaded = datetime.now(timezone.utc).isoformat()
    ox.save_graphml(graph, graph_path)
    print('Acquiring Maldives WorldPop constrained 2020 counts', flush=True)
    raster_path, provenance = acquire_population(PopulationConfig(
        worldpop='auto', iso3='MDV', year=2020, cache_dir=folder / 'worldpop'))
    boundary_path = folder / 'boundary.geojson'
    gpd.GeoDataFrame({'name': ['Central Male study window']}, geometry=[box(*BBOX)],
                     crs=4326).to_file(boundary_path, driver='GeoJSON')
    manifest = {'name': 'Central Male, Maldives', 'bbox': BBOX, 'network_type': 'drive',
                'osm_download_utc': downloaded, 'osm_source': source, 'osm_url': osm_url,
                'raw_nodes': len(graph), 'raw_directed_edges': graph.number_of_edges(), 'population': provenance,
                'raster_relative_path': str(raster_path.resolve().relative_to(folder.resolve())),
                'source_notes': ['OSM roads from download date; WorldPop population year 2020.',
                                 'Population is modelled residential counts, not observed trips.',
                                 'Fixed partial-city window; clipped boundaries and largest-SCC selection apply.'],
                'osm_attribution': 'OpenStreetMap contributors, ODbL, https://www.openstreetmap.org/copyright',
                'versions': _versions(), 'sha256': {}}
    for path in (graph_path, boundary_path, raster_path):
        manifest['sha256'][str(path.resolve().relative_to(folder.resolve()))] = sha256_file(path)
    if osm_api:
        manifest['sha256']['map.osm'] = sha256_file(xml_path)
    write_json(manifest_path, manifest)
    return graph, manifest


def config_for(out, raster_path, snap):
    return RunConfig(input={'source': 'bbox', 'bbox': BBOX}, cleaning={'consolidate': False},
        analysis={'seed': 42, 'n_jobs': 2, 'max_memory_gb': .5},
        population={'worldpop': 'auto', 'cache_dir': str(raster_path.parent.resolve()),
                    'iso3': 'MDV', 'year': 2020, 'snap_max_m': snap},
        accessibility={'half_distance_km': .3, 'cutoff_factor': 5, 'k': 2},
        criticality={'k_betweenness': 12, 'k_detour': 12, 'k_nodes': 8, 'exact_info_max_nodes': 0},
        robustness={'steps': 3, 'failure_runs': 2, 'efficiency_sources': 32, 'removal': ['links']},
        reliability={'samples': 1024, 'p0': .01, 'p0_sweep': [0, .01, .05]},
        travel_time={'enabled': False}, output={'dir': out / f'snap-{snap}m', 'figures': True})


def reference_cells(graph, path):
    """Independent centre-in-boundary selection and brute-force nearest node distances.

    Uses neither production rasterio.mask nor the production KD-tree allocator. Numeric
    OSM IDs are sorted before argmin, giving the same specified deterministic tie rule.
    """
    boundary = box(*BBOX)
    ids = sorted(graph, key=int)
    xy = np.array([(graph.nodes[node]['x'], graph.nodes[node]['y']) for node in ids])
    records = []
    with rasterio.open(path) as raster:
        projection = Transformer.from_crs(4326, raster.crs, always_xy=True)
        raster_boundary = transform(projection.transform, boundary)
        window = from_bounds(*raster_boundary.bounds, transform=raster.transform)
        row0 = max(0, int(np.floor(window.row_off)) - 1)
        col0 = max(0, int(np.floor(window.col_off)) - 1)
        row1 = min(raster.height, int(np.ceil(window.row_off + window.height)) + 1)
        col1 = min(raster.width, int(np.ceil(window.col_off + window.width)) + 1)
        values = raster.read(1, window=Window(col0, row0, col1-col0, row1-row0), masked=True)
        to_graph = Transformer.from_crs(raster.crs, graph.graph['crs'], always_xy=True)
        for r, c in np.ndindex(values.shape):
            value = values[r, c]
            if np.ma.is_masked(value) or not np.isfinite(value) or value <= 0:
                continue
            row, col = row0+r, col0+c
            x, y = raster.transform * (col+.5, row+.5)
            if not raster_boundary.covers(Point(x, y)):
                continue
            px, py = to_graph.transform(x, y)
            distances = np.hypot(xy[:, 0]-px, xy[:, 1]-py)
            nearest = int(distances.argmin())
            records.append({'cell_id': f'{row}:{col}', 'raster_row': row, 'raster_col': col,
                            'people': float(value), 'nearest_node_id': str(ids[nearest]),
                            'snap_distance_m': float(distances[nearest]),
                            'allocated_100m': bool(distances[nearest] <= 100),
                            'allocated_500m': bool(distances[nearest] <= 500),
                            'x': px, 'y': py, 'node_x': xy[nearest, 0], 'node_y': xy[nearest, 1]})
        # Separate visualization export; it does not feed the independent reference.
        clipped, affine = mask(raster, [mapping(raster_boundary)], crop=True, filled=False)
        profile = raster.profile.copy()
        profile.update(width=clipped.shape[2], height=clipped.shape[1], transform=affine,
                       dtype='float32', nodata=-9999., compress='deflate')
    return ids, records, clipped.filled(-9999).astype('float32'), profile


def export_audit(out, graph, records, clipped, profile):
    with rasterio.open(out / 'population-clipped.tif', 'w', **profile) as raster:
        raster.write(clipped)
    # Evenly sample nearest-node distances, including the closest/farthest cells.
    order = np.argsort([row['snap_distance_m'] for row in records], kind='stable')
    sample = set(order[np.linspace(0, len(order)-1, min(20, len(order)), dtype=int)].tolist())
    cells, segments = [], []
    for index, row in enumerate(records):
        attrs = {key: value for key, value in row.items() if key not in {'x', 'y', 'node_x', 'node_y'}}
        attrs['sampled'] = index in sample
        cells.append({**attrs, 'geometry': Point(row['x'], row['y'])})
        segments.append({**attrs, 'geometry': LineString([(row['x'], row['y']), (row['node_x'], row['node_y'])])})
    path = out / 'allocation-audit.gpkg'
    if path.exists():
        path.unlink()
    gpd.GeoDataFrame(cells, crs=graph.graph['crs']).to_file(path, layer='cells')
    gpd.GeoDataFrame(segments, crs=graph.graph['crs']).to_file(path, layer='snap_lines', mode='a')
    gpd.GeoDataFrame({'name': ['Study boundary']}, geometry=[box(*BBOX)], crs=4326).to_crs(
        graph.graph['crs']).to_file(path, layer='boundary', mode='a')
    with (out / 'sample-cells.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records[index] for index in sorted(sample))


def overlay_map(out, graph, records):
    """Raster/road/node overlay in the analysis CRS; reprojection is for display only."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    from rasterio.transform import array_bounds

    with rasterio.open(out / 'population-clipped.tif') as raster:
        affine, width, height = calculate_default_transform(
            raster.crs, graph.graph['crs'], raster.width, raster.height, *raster.bounds)
        image = np.full((height, width), -9999., dtype='float32')
        reproject(rasterio.band(raster, 1), image, src_transform=raster.transform,
                  src_crs=raster.crs, dst_transform=affine, dst_crs=graph.graph['crs'],
                  src_nodata=-9999., dst_nodata=-9999., resampling=Resampling.nearest)
    west, south, east, north = array_bounds(height, width, affine)
    frames = {snap: gpd.read_file(out / f'snap-{snap}m' / 'network.gpkg', layer='nodes') for snap in SNAPS}
    edges = gpd.read_file(out / 'snap-100m' / 'network.gpkg', layer='edges')
    maximum = max(float(frame.population.max()) for frame in frames.values())
    positive_min = min(float(frame.loc[frame.population > 0, 'population'].min()) for frame in frames.values())
    boundary = gpd.GeoSeries([box(*BBOX)], crs=4326).to_crs(graph.graph['crs'])
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), layout='constrained')
    for snap, ax in zip(SNAPS, axes):
        background = ax.imshow(np.ma.masked_less_equal(image, 0), extent=(west, east, south, north),
                               cmap='Greys', alpha=.55, norm=LogNorm())
        edges.plot(ax=ax, color='#536779', linewidth=.5, alpha=.7)
        frame = frames[snap]
        frame.loc[frame.population == 0].plot(ax=ax, color='lightgrey', markersize=5)
        positive = frame.loc[frame.population > 0]
        foreground = ax.scatter(positive.geometry.x, positive.geometry.y, c=positive.population,
                                s=16, cmap='viridis', norm=LogNorm(vmin=positive_min, vmax=maximum))
        far = [row for row in records if row['snap_distance_m'] > snap]
        if far:
            ax.scatter([row['x'] for row in far], [row['y'] for row in far], color='red', marker='x',
                       s=24, linewidths=1, label='Unallocated populated cell centre')
            ax.legend(loc='upper left', fontsize=8)
        boundary.boundary.plot(ax=ax, color='#d55e00', linewidth=1.2)
        ax.plot([west+80, west+580], [south+55, south+55], color='black', linewidth=3)
        ax.text(west+330, south+75, '500 m', ha='center', fontsize=8)
        ax.set_title(f'Male: {snap} m maximum snap distance')
        ax.set_aspect('equal')
        ax.set_axis_off()
    fig.colorbar(background, ax=axes, location='bottom', shrink=.5, label='WorldPop people per cell (display reprojection; log scale)')
    fig.colorbar(foreground, ax=axes, location='right', shrink=.8, label='Allocated people per node (log scale)')
    fig.suptitle('WorldPop constrained 2020 and frozen OSM drive roads\nPartial-city integration check; modelled population, not a census', fontsize=12)
    fig.savefig(out / 'allocation-overlay.png', dpi=180)
    plt.close(fig)


def validate(out, raw, manifest, overwrite=False):
    raster_path = out / 'inputs' / manifest['raster_relative_path']
    configs = {snap: config_for(out, raster_path, snap) for snap in SNAPS}
    # Frozen real OSM source, not fabricated geometry. All downstream steps are real.
    with patch('georesilience.network.ox.graph_from_bbox', side_effect=lambda **_: raw.copy()):
        graph, meta, cleaning = load_and_clean(configs[100])
        meta['osm_download_utc'] = manifest['osm_download_utc']
        ox.save_graphml(graph, out / 'inputs' / 'cleaned.graphml')
        summaries = {}
        for snap, config in configs.items():
            config_path = out / f'snap-{snap}m.yaml'
            config_path.write_text(yaml.safe_dump(config.model_dump(mode='json'), sort_keys=False))
            print(f'Running real data with {snap} m snap limit ({len(graph)} cleaned nodes)', flush=True)
            with patch('georesilience.pipeline.load_and_clean',
                       side_effect=lambda _: (graph.copy(), meta.copy(), cleaning.copy())):
                summaries[snap] = run(config, overwrite=overwrite)
    ids, cells, clipped, profile = reference_cells(graph, raster_path)
    if not cells:
        raise ValueError('No positive cells in real study window')
    export_audit(out, graph, cells, clipped, profile)
    uniform_columns = ['hansen_a', 'vuln', 'vuln_k2', 'p_connected', 'information',
                       'degree', 'closeness', 'straightness', 'betweenness']
    uniform_edges = ['access_drop', 'access_rank', 'eff_drop', 'disc_pair_frac', 'rel_importance',
                     'rel_down_count', 'rel_up_count']
    verification = {'scope': 'Real-data integration, independent allocation and baseline accessibility checks',
                    'nodes': len(graph), 'positive_cells': len(cells), 'sampled_cells': min(20, len(cells)),
                    'allocation_reference': 'centre-in-boundary scalar selection; exhaustive Euclidean nearest-node search',
                    'cases': {}}
    node_frames, edge_frames = {}, {}
    for snap in SNAPS:
        folder = configs[snap].output.dir
        nodes = gpd.read_file(folder / 'network.gpkg', layer='nodes').set_index('node_id')
        edges = gpd.read_file(folder / 'network.gpkg', layer='edges').set_index('link_id')
        node_frames[snap], edge_frames[snap] = nodes, edges
        weights = {str(node): 0. for node in ids}
        for cell in cells:
            if cell['snap_distance_m'] <= snap:
                weights[cell['nearest_node_id']] += cell['people']
        actual = nodes.loc[list(weights), 'population'].to_numpy()
        expected = np.array(list(weights.values()))
        np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-7)
        total = sum(cell['people'] for cell in cells)
        allocated = float(expected.sum())
        summary = summaries[snap]['population']
        np.testing.assert_allclose([summary['total'], summary['allocated'], summary['unallocated']],
                                   [total, allocated, total-allocated], rtol=0, atol=1e-7)
        # Twenty predefined evenly spaced numeric node IDs; independent NetworkX routing
        # and scalar sums, using independently allocated destination masses.
        selected = [ids[index] for index in np.linspace(0, len(ids)-1, min(20, len(ids)), dtype=int)]
        beta = np.log(2) / 300
        score_checks = []
        for node in selected:
            distances = nx.single_source_dijkstra_path_length(graph, node, cutoff=1500, weight='length')
            score = sum(weights[str(dest)] * np.exp(-beta*distance)
                        for dest, distance in distances.items() if dest != node)
            observed = float(nodes.loc[str(node), 'hansen_a_pop'])
            np.testing.assert_allclose(observed, score, rtol=0, atol=1e-7)
            score_checks.append({'node_id': str(node), 'expected': score, 'observed': observed,
                                 'absolute_error': abs(score-observed)})
        verification['cases'][str(snap)] = {**summary, 'allocation_max_error': float(np.max(abs(actual-expected))),
             'hansen_baseline_spot_checks': score_checks,
             'conn_reliability_pop': summaries[snap]['reliability']['conn_reliability_pop'],
             'expected_pop_cut_off': summaries[snap]['reliability']['expected_pop_cut_off']}
    for column in uniform_columns:
        np.testing.assert_allclose(node_frames[100].sort_index()[column].astype(float),
                                   node_frames[500].sort_index()[column].astype(float),
                                   rtol=0, atol=1e-12, equal_nan=True)
    checked_edges = []
    for column in uniform_edges:
        if column in edge_frames[100]:
            np.testing.assert_allclose(edge_frames[100].sort_index()[column].astype(float),
                                       edge_frames[500].sort_index()[column].astype(float),
                                       rtol=0, atol=1e-12, equal_nan=True)
            checked_edges.append(column)
    np.testing.assert_allclose(summaries[100]['reliability']['conn_reliability'],
                               summaries[500]['reliability']['conn_reliability'], rtol=0, atol=0)
    assert (node_frames[500].sort_index().population >= node_frames[100].sort_index().population - 1e-7).all()
    verification.update(passed=True, uniform_node_columns_checked=uniform_columns,
                        uniform_edge_columns_checked=checked_edges, uniform_conn_reliability_unchanged=True,
                        allocated_population_nondecreasing=True, physical_links=len(edge_frames[100]))
    write_json(out / 'verification.json', verification)
    overlay_map(out, graph, cells)
    lines = ['Ticket 12 real-data validation: PASS', f'Cleaned nodes: {len(graph)}; positive raster cells: {len(cells)}',
             'Population source: WorldPop constrained 2020; roads: frozen OSM download.',
             'Different observation dates: this is an integration check, not a census reconstruction.',
             'Independent per-cell nearest-node allocation and population conservation passed.',
             'Independent NetworkX baseline Hansen checks passed for 20 nodes at each snap limit.',
             'Uniform outputs unchanged; allocated population nondecreasing from 100 m to 500 m.',
             'snap_m | total | allocated | unallocated | unallocated_pct']
    for snap in SNAPS:
        p = summaries[snap]['population']
        lines.append(f"{snap} | {p['total']:.9f} | {p['allocated']:.9f} | {p['unallocated']:.9f} | {p['unallocated_pct']:.6f}")
    lines.extend(['', 'Open population-clipped.tif, allocation-audit.gpkg and each snap output network.gpkg in QGIS.',
                  'sample-cells.csv lists 20 assignments for manual inspection.',
                  'Candidate-only closure coverage and top-three k=2 pair scope still apply.',
                  'WorldPop is a modelled estimate, not a census.'])
    (out / 'validation_report.txt').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('results/ticket12-male'))
    parser.add_argument('--download-only', action='store_true')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--osm-api', action='store_true', help='Use OSM map XML with the project drive filter when Overpass is unavailable')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    if args.offline and args.download_only:
        parser.error('--offline and --download-only are mutually exclusive')
    args.out.mkdir(parents=True, exist_ok=True)
    def forbidden_request(*_, **__):
        raise AssertionError('Offline validation attempted an HTTP request')
    network_guard = patch('requests.sessions.Session.request', forbidden_request) if args.offline else nullcontext()
    with network_guard:
        raw, manifest = frozen_inputs(args.out / 'inputs', offline=args.offline, osm_api=args.osm_api)
        if not args.download_only:
            validate(args.out, raw, manifest, overwrite=args.overwrite)
