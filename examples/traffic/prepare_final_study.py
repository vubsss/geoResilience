"""Prepare reproducible study JSONs from the user's original Hyderabad archives.

Run from repository root. Reuses original population counts and audited OD demand.
Capacities are freshly inferred from available road tags with disclosed defaults;
they are not measured capacities or copies of the earlier pilot's capacity CSV.
"""
import csv
import io
import json
from pathlib import Path
import zipfile

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree

from georesilience.config import RunConfig
from georesilience.network import load_and_clean

ROOT = Path(__file__).resolve().parents[2]
SPEEDS = {'motorway': 80, 'motorway_link': 40, 'trunk': 60, 'trunk_link': 30,
    'primary': 50, 'primary_link': 25, 'secondary': 40, 'secondary_link': 20,
    'tertiary': 30, 'tertiary_link': 20, 'residential': 20, 'living_street': 10,
    'unclassified': 20, 'road': 20}


def save_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    folder = ROOT/'data/final_study'
    folder.mkdir(parents=True, exist_ok=True)
    for city in ('gachibowli', 'old-hyderabad'):
        source = ROOT/'data/traffic_comparison'
        roads = source/f'data/{city}/raw_network.graphml'
        config = RunConfig(input={'path': roads}, cleaning={'consolidate': False})
        graph, _, _ = load_and_clean(config)
        tree = cKDTree([(d['x'], d['y']) for _, d in graph.nodes(data=True)])
        transform = Transformer.from_crs(4326, graph.graph['crs'], always_xy=True)
        west, south, east, north = json.loads((source/f'data/{city}/extraction_metadata.json').read_text())['bbox_west_south_east_north']
        with zipfile.ZipFile(ROOT/'datasett/hyderabad-critical-node-inputs.zip') as archive:
            raw = list(csv.DictReader(io.StringIO(archive.read(
                f'hyderabad-critical-node-inputs/inputs/{city}/facilities.csv').decode('utf-8-sig'))))
        selected, excluded = [], []
        for record in raw:
            x, y = float(record['longitude']), float(record['latitude'])
            if not (west <= x <= east and south <= y <= north):
                continue
            distance = float(tree.query(transform.transform(x, y))[0])
            if distance <= 500:
                selected.append(record)
            else:
                excluded.append({'facility_id': record['facility_id'], 'snap_m': distance})
        facilities = folder/f'{city}_facilities.csv'
        save_csv(facilities, selected)
        (folder/f'{city}_facility_coverage.json').write_text(json.dumps({
            'attached': len(selected), 'excluded_by_500m_snap': excluded,
            'capacity': '1 assumed unit per institution; no measured beds/seats',
            'footprint_warning': 'Gachibowli upload misses northern strip of original box; supply census incomplete'}, indent=2)+'\n')
        base = ROOT/f'results/traffic_validation_v2/fresh_assignment/{city}/base'
        from georesilience.traffic import canonical_traffic_graph, _road_capacities
        from georesilience.config import TrafficConfig
        fixed, _ = canonical_traffic_graph(graph, SPEEDS)
        inferred, _, _ = _road_capacities([(u, v, k, d) for u, v, k, d in fixed.edges(keys=True, data=True) if u != v], TrafficConfig())
        capacities = folder/f'{city}_capacities.csv'
        save_csv(capacities, [dict(u=u, v=v, key=k, capacity_pcu_h=value) for (u, v, k), value in inferred.items()])
        boundary = folder/f'{city}_boundary.geojson'
        from shapely.geometry import box
        gpd.GeoDataFrame(geometry=[box(west, south, east, north)], crs=4326).to_file(boundary, driver='GeoJSON')
        values = {'input': {'path': str(roads), 'boundary': str(boundary)},
            'cleaning': {'consolidate': False},
            'population': {'node_counts': str(source/f'results/{city}-population/network.gpkg')},
            'analysis': {'default_view': 'population_weighted', 'n_jobs': 2, 'max_memory_gb': 1.},
            'criticality': {'coverage': 'screened', 'link_candidates': 30, 'node_candidates': 30},
            'robustness': {'fraction': .2, 'steps': 50, 'order': 'adaptive'},
            'travel_time': {'samples': 64, 'highway_speeds_kph': SPEEDS},
            'reliability': {'samples': 64},
            'traffic': {'enabled': True, 'source': 'assignment', 'demand_source': 'od_csv',
                'od_csv': str(base/'input_od.csv'),
                'reassign_failures': True, 'relative_gap': .001, 'max_iterations': 600},
            'services': {'facilities_csv': str(facilities), 'mode': 'sfca',
                'school': {'catchment_minutes': 10, 'capacity_unit': 'assumed_school_capacity_units'},
                'hospital': {'catchment_minutes': 10, 'capacity_unit': 'assumed_hospital_capacity_units'}},
            'accessibility': {'cost': 'auto', 'half_time_minutes': 6},
            'output': {'dir': str(ROOT/f'results/final_pipeline/{city}_defaults'), 'figures': True}}
        for scenario in ('defaults', 'flood'):
            values['output']['dir'] = str(ROOT/f'results/final_pipeline/{city}_{scenario}')
            study = {'run': values}
            if scenario == 'flood':
                flood = folder/f'{city}_flood_scenario.json'
                # Previously completed, real pinned-SFINCS maximum-depth raster.
                # The full workflow still validates rasters and extracts/fingerprints probabilities afresh.
                flood.write_text(json.dumps({'dem': str(ROOT/'datasett/P5_PAN_CD_N17_000_E078_000_DEM_30m/P5_PAN_CD_N17_000_E078_000_DEM_30m.tif'),
                    'depth': str(ROOT/'results/reassignment_facilities_20261114/flood_results/gachibowli/closure/maximum_depth.tif'),
                    'scenario_id': 'reported_20201014_daily',
                    'rainfall': {'raster': str(ROOT/'datasett/rainfall_reported_20201014_mandal_totals.tif'), 'duration_hours': 24, 'assumed_total_mm': 100},
                    'simulation': {'resolution_m': 120, 'recession_hours': 6, 'curve_number': 85, 'manning': .04, 'threads': 4},
                    'uniform_probability': .01, 'threshold_m': .3, 'dispersion': .35}, indent=2)+'\n')
                study['flood_config'] = str(flood)
            (folder/f'{city}_{scenario}.json').write_text(json.dumps(study, indent=2)+'\n')
    print('Prepared study inputs/configurations:', folder)


if __name__ == '__main__':
    main()
