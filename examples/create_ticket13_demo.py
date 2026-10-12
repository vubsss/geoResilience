"""Offline grid/zone example, with optional synthetic population counts.

GraphML uniform.yaml runs directly through the CLI. The population example
substitutes only bbox acquisition; its boundary, raster allocation and analyses
run normally. Its generated bbox YAML downloads real roads if invoked directly.
"""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
from pyproj import Transformer
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box
from shapely.ops import transform
import yaml

from georesilience.config import RunConfig
from georesilience.pipeline import run


def create_examples(folder, results):
    folder, results = Path(folder).resolve(), Path(results).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    graph = nx.MultiDiGraph(crs='EPSG:32644', simplified=True)
    for row in range(3):
        for col in range(3):
            graph.add_node(row * 3 + col, x=500050. + 100 * col, y=1900250. - 100 * row)
    way = 0
    for row in range(3):
        for col in range(3):
            for dc, dr in ((1, 0), (0, 1)):
                if col + dc < 3 and row + dr < 3:
                    u, v = row * 3 + col, (row + dr) * 3 + col + dc
                    way += 1
                    for a, b in ((u, v), (v, u)):
                        graph.add_edge(a, b, length=100., osmid=way, highway='residential', name=f'Grid road {way}')
    source, wards, raster = folder / 'grid.graphml', folder / 'wards.gpkg', folder / 'population.tif'
    ox.save_graphml(graph, source)
    gpd.GeoDataFrame({'ward_id': ['1', '2', '3'], 'name': ['West', 'East', 'Empty zone']},
                    geometry=[box(500000, 1900000, 500200, 1900300),
                              box(500200, 1900000, 500300, 1900300),
                              box(500400, 1900000, 500500, 1900300)], crs=32644).to_file(wards)
    with rasterio.open(raster, 'w', driver='GTiff', height=3, width=3, count=1,
                       dtype='float32', crs=32644, transform=from_origin(500000, 1900300, 100, 100)) as stream:
        stream.write(np.arange(1, 10, dtype='float32').reshape(3, 3), 1)
    boundary = transform(Transformer.from_crs(32644, 4326, always_xy=True).transform,
                         box(500000, 1900000, 500300, 1900300))
    common = {'cleaning': {'consolidate': False}, 'analysis': {'n_jobs': 1, 'max_memory_gb': .1},
              'criticality': {'all': True}, 'accessibility': {'all_links': True, 'half_distance_km': .1},
              'robustness': {'steps': 2, 'failure_runs': 2},
              'reliability': {'samples': 1024, 'p0': .2, 'p0_sweep': [.2]},
              'travel_time': {'enabled': False},
              'zones': {'path': str(wards), 'id_field': 'ward_id', 'name_field': 'name'}}
    manifest = {'inventory_expected': {'1': {'n_nodes': 6, 'road_km': 1., 'population': 27.},
                                       '2': {'n_nodes': 3, 'road_km': .2, 'population': 18.},
                                       '3': {'n_nodes': 0, 'road_km': 0., 'population': 0.}},
                'notes': 'Synthetic grid and count raster; no real ward or hazard claims. Empty zones are unranked.',
                'runs': {}}
    for name in ('uniform', 'population'):
        settings = {**common, 'input': {'source': 'graphml', 'path': str(source)},
                    'output': {'dir': str(results / name), 'figures': True}}
        if name == 'population':
            settings['input'] = {'source': 'bbox', 'bbox': list(boundary.bounds)}
            settings['population'] = {'worldpop': str(raster), 'snap_max_m': 10}
        (folder / f'{name}.yaml').write_text(yaml.safe_dump(settings, sort_keys=False))
        config = RunConfig.model_validate(settings)
        if name == 'population':
            with patch('georesilience.network.ox.graph_from_bbox', side_effect=lambda **_: graph.copy()):
                summary = run(config, overwrite=True)
        else:
            summary = run(config, overwrite=True)
        zones = gpd.read_file(config.output.dir / 'zones.gpkg').set_index('zone_id')
        for key, expected in manifest['inventory_expected'].items():
            assert zones.loc[key, 'n_nodes'] == expected['n_nodes']
            assert abs(zones.loc[key, 'road_km'] - expected['road_km']) < 1e-12
            if name == 'population':
                assert zones.loc[key, 'population'] == expected['population']
        assert summary['zones']['unassigned_nodes'] == 0
        manifest['runs'][name] = summary['zones']
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2, allow_nan=False) + '\n')
    print(f'Verified uniform/population zone outputs in {results}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('data/ticket13-demo'))
    parser.add_argument('--results', type=Path, default=Path('results/ticket13-demo'))
    args = parser.parse_args()
    create_examples(args.out, args.results)
