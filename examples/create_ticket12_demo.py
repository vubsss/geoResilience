"""Run an offline synthetic population example through the real cleaning/pipeline.

Only the OSM download is substituted with a frozen synthetic bbox graph. This is a
population-count fixture, not actual WorldPop data; the exported provenance says local.
The YAMLs use normal bbox inputs and can also be run against live OSM roads, in which
case their graph and answers will differ from this controlled example.
"""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box
from shapely.ops import transform
import yaml

from georesilience.config import RunConfig
from georesilience.pipeline import run


def create_examples(folder, results):
    folder, results = Path(folder), Path(results)
    folder.mkdir(parents=True, exist_ok=True)
    affine = from_origin(500000, 1900300, 100, 100)
    to_wgs = Transformer.from_crs(32644, 4326, always_xy=True)
    boundary = transform(to_wgs.transform, box(500000, 1900000, 500300, 1900300))
    graph = nx.MultiDiGraph(crs='EPSG:4326', simplified=True)
    for node in range(8):
        x, y = rasterio.transform.xy(affine, node//3, node%3)
        lon, lat = to_wgs.transform(x, y)
        graph.add_node(node, x=lon, y=lat)
    order = [0, 1, 2, 5, 4, 3, 6, 7]
    for way, (u, v) in enumerate(zip(order, order[1:]), 1):
        for a, b in ((u, v), (v, u)):
            xy = [(graph.nodes[i]['x'], graph.nodes[i]['y']) for i in (a, b)]
            graph.add_edge(a, b, length=100., osmid=way, highway='residential',
                           name=f'Fixture road {way}', geometry=LineString(xy))
    verification = {}
    for name, values in [('unequal-k2', np.arange(1, 10, dtype='float32').reshape(3, 3)),
                         ('ones-k2', np.ones((3, 3), dtype='float32'))]:
        raster_path = (folder/f'{name}.tif').resolve()
        with rasterio.open(raster_path, 'w', driver='GTiff', width=3, height=3, count=1,
                           dtype='float32', crs=32644, transform=affine, nodata=-9999) as raster:
            raster.write(values, 1)
        settings = {
            'input': {'source': 'bbox', 'bbox': list(boundary.bounds)},
            'cleaning': {'consolidate': False},
            'analysis': {'n_jobs': 1, 'max_memory_gb': .1, 'seed': 42},
            'population': {'worldpop': str(raster_path), 'snap_max_m': 10},
            'accessibility': {'half_distance_km': .1, 'cutoff_factor': 5, 'k': 2, 'all_links': True},
            'robustness': {'steps': 2, 'failure_runs': 1, 'efficiency_sources': 8, 'removal': ['links']},
            'reliability': {'samples': 1024, 'p0': .2, 'p0_sweep': [0, .2, 1]},
            'travel_time': {'enabled': False},
            'output': {'dir': str(results/f'ticket12-{name}'), 'figures': True}}
        config_path = folder/f'{name}.yaml'
        config_path.write_text(yaml.safe_dump(settings, sort_keys=False))
        # Keep the actual bbox boundary, projection, cleaning, allocation and analyses.
        with patch('georesilience.network.ox.graph_from_bbox', return_value=graph.copy()):
            summary = run(RunConfig.model_validate(settings), overwrite=True)
        expected_allocated = 36 if name == 'unequal-k2' else 8
        expected_unallocated = 9 if name == 'unequal-k2' else 1
        assert summary['population']['allocated'] == expected_allocated
        assert summary['population']['unallocated'] == expected_unallocated
        if name == 'ones-k2':
            access = summary['metrics']['accessibility']
            assert access['total_accessibility'] == access['total_accessibility_pop']
            assert summary['reliability']['conn_reliability'] == summary['reliability']['conn_reliability_pop']
        verification[name] = {'population': summary['population'],
                              'total_accessibility': summary['metrics']['accessibility']['total_accessibility'],
                              'total_accessibility_pop': summary['metrics']['accessibility']['total_accessibility_pop'],
                              'conn_reliability': summary['reliability']['conn_reliability'],
                              'conn_reliability_pop': summary['reliability']['conn_reliability_pop'],
                              'expected_pop_cut_off': summary['reliability']['expected_pop_cut_off']}
    results.mkdir(parents=True, exist_ok=True)
    (results/'ticket12-verification.json').write_text(json.dumps(verification, indent=2)+'\n')
    print(json.dumps(verification, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('data/ticket12-demo'))
    parser.add_argument('--results', type=Path, default=Path('results'))
    args = parser.parse_args()
    create_examples(args.out, args.results)
