"""Run importance-weighted city analyses with verified intact traffic/flood reuse.

Run from the repository root. The scoped prepare_traffic replacement supplies an
input-checked TrafficResult to the ordinary pipeline; all metric calculations,
local consequences, attack and failure-state assignments run through production
code. No previously published output is modified.
"""

import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'

import argparse
import copy
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np

from georesilience import pipeline
from georesilience.config import CompositeConfig, RunConfig
from georesilience.population import sha256_file
from georesilience.traffic import TrafficResult, _read_od, _read_edges, _edge_lookup
from georesilience.traffic_failures import ReassignedTrafficTimeModel

SOURCE = ROOT / 'results/final_deliverables/GeoResilience_Final_Results_20261114'
DEFAULT_OUTPUT = ROOT / 'results/importance_weighted_20261114'
CITIES = ('gachibowli', 'old-hyderabad')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def log(message):
    print(f'[{datetime.now(timezone.utc).isoformat()}] {message}', flush=True)


def read_csv(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def run_city(city, output, jobs=1, memory_gb=.35):
    started = perf_counter()
    output = Path(output).resolve()
    target = output / 'cities' / city
    if target.exists():
        raise ValueError(f'refusing to replace existing city output: {target}')
    prior = SOURCE / 'cities' / city
    summary = read(prior / 'analysis/summary.json')
    manifest = read(prior / 'analysis/run_manifest.json')
    checksums = read(SOURCE / 'verification/checksums.json')
    checked = {}
    # Authenticate every source city artifact, including probabilities and GIS.
    for relative, checksum in checksums.items():
        if relative.startswith(f'cities/{city}/'):
            assert sha256_file(SOURCE / relative) == checksum, relative
            checked[relative] = checksum
    assert summary['traffic']['status'] == 'converged'
    assert read(prior / 'workflow_complete.json')['status'] == 'complete'
    values = copy.deepcopy(manifest['resolved_config'])
    original_config = RunConfig.model_validate(values)
    input_checks = []
    for item in manifest['inputs']:
        path = (prior / 'flood/failure_probabilities.csv' if item['role'] == 'failure_probabilities'
                else Path(item['path']))
        assert sha256_file(path) == item['sha256'], str(path)
        input_checks.append({**item, 'verified_path': str(path)})
    target.mkdir(parents=True)
    shutil.copytree(prior / 'flood', target / 'flood')
    shutil.copytree(prior / 'prepared', target / 'prepared')
    config_folder = target / 'configuration'
    config_folder.mkdir()
    for suffix in ('_facilities.csv', '_facility_coverage.json', '_flood_scenario.json', '_boundary.geojson'):
        shutil.copy2(ROOT / 'data/final_study' / (city + suffix), config_folder / (city + suffix))
    values['analysis'].update(default_view='node_importance_weighted', n_jobs=jobs, max_memory_gb=memory_gb)
    values['composite'] = CompositeConfig().model_dump(mode='json')
    values['reliability'].update(p_fail_csv=str(target / 'flood/failure_probabilities.csv'), require_complete_failures=True)
    values['output'].update(dir=str(target / 'analysis'), figures=True)
    config = RunConfig.model_validate(values)
    save(target / 'study_config.json', {'run': config.model_dump(mode='json'),
        'reused_flood': str(prior / 'flood'), 'reused_intact_traffic': str(prior / 'analysis')})
    receipt = {'status': 'inputs_verified', 'city': city, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'source': str(prior), 'checked_source_files': checked, 'checked_inputs': input_checks,
        'input_cleaning_fingerprint': manifest['input_cleaning_fingerprint'],
        'reuse': ['previous flood simulation and fingerprint-bound extracted probabilities',
                  'previous converged intact traffic assignment, OD, capacities and skims'],
        'recomputed': ['all configured local metrics and screened removals with combined node importance',
            'targeted attack', '64 failure traffic assignments and per-state 2SFCA',
            'paired unweighted, population, service and combined-importance reliability',
            'all composites, reports, GIS and figures'],
        'resource_settings': {'jobs': jobs, 'max_memory_gb': memory_gb},
        'source_code_sha256': {str(p.relative_to(ROOT)): sha256_file(p)
            for p in sorted((ROOT / 'src/georesilience').rglob('*.py'))},
        'runner_sha256': sha256_file(Path(__file__))}
    save(target / 'reuse_manifest.json', receipt)

    def cached_traffic(graph, traffic_config, free_flow_seconds, population):
        assert traffic_config == original_config.traffic
        assert graph.graph['input_cleaning_fingerprint'] == manifest['input_cleaning_fingerprint']
        _, lookup = _edge_lookup(graph)
        raw = read_csv(prior / 'analysis/traffic_arcs.csv')
        assert len(raw) == len(lookup)
        numeric = {'free_flow_time_s', 'capacity_pcu_h', 'assigned_volume_pcu_h',
                   'vc_ratio', 'congested_time_s', 'delay_s', 'width_m', 'lanes_tag', 'effective_lanes'}
        rows = [{key: float(value) if key in numeric and value else value
                 for key, value in row.items() if value or key in ('u', 'v', 'key')} for row in raw]
        capacities = _read_edges(traffic_config.capacity_csv, lookup, 'capacity_pcu_h')
        times = {}
        for row in rows:
            edge = lookup[row['u'], row['v'], row['key']]
            assert np.isclose(free_flow_seconds[edge], row['free_flow_time_s'], rtol=1e-12, atol=1e-9)
            assert capacities[edge] == row['capacity_pcu_h']
            assert np.isfinite(row['congested_time_s']) and row['congested_time_s'] > 0
            times[edge] = row['congested_time_s']
        assert set(times) == set(lookup.values())
        demand = _read_od(traffic_config.od_csv, graph)
        od_rows = read_csv(prior / 'analysis/traffic_od.csv')
        od_rows = [{key: value if key in ('origin', 'destination') else float(value)
                    for key, value in row.items()} for row in od_rows]
        assert np.isclose(sum(demand.values()), summary['traffic']['demand_pcu_h'], rtol=1e-12)
        metadata = copy.deepcopy(summary['traffic'])
        metadata.pop('failure_reassignment', None)
        receipt['intact_traffic_reuse_verified'] = {
            'directed_arcs': len(times), 'original_od_pairs': len(demand),
            'free_flow_seconds_match': True, 'capacities_match': True,
            'converged': True, 'original_relative_gap': metadata['relative_gap']}
        save(target / 'reuse_manifest.json', receipt)
        log(f'{city}: reusing verified intact assignment ({len(times)} arcs)')
        return TrafficResult(metadata, rows, times, od_rows, demand, capacities)

    snapshot_folder = target / 'traffic_failure_snapshots'
    snapshot_folder.mkdir()

    class RecordedReassignment(ReassignedTrafficTimeModel):
        def costs(self, context):
            if context.sample_index is None:
                return super().costs(context)
            begin = perf_counter()
            log(f'{city}: traffic failure sample {context.sample_index + 1}/64, {len(context.closed_link_ids)} closed roads')
            times = super().costs(context)
            edges = list(self.free)
            np.savez_compressed(snapshot_folder / f'sample_{context.sample_index:04d}.npz',
                edges=np.asarray([(str(u), str(v), str(k)) for u, v, k in edges]),
                seconds=np.asarray([times[edge] for edge in edges]),
                closed_link_ids=np.asarray(sorted(context.closed_link_ids), dtype=np.int64))
            log(f'{city}: traffic sample {context.sample_index + 1}/64 complete in {perf_counter() - begin:.1f}s')
            return times

    log(f'{city}: starting comprehensive importance-weighted production analysis')
    with patch.object(pipeline, 'prepare_traffic', cached_traffic), \
            patch.object(pipeline, 'ReassignedTrafficTimeModel', RecordedReassignment):
        result = pipeline.run(config)
    assert result['default_view'] == 'node_importance_weighted'
    assert result['traffic']['failure_reassignment']['all_converged']
    assert result['traffic']['failure_reassignment']['evaluated_states'] == 64
    assert result['headline']['value'] is not None
    receipt.update(status='complete', elapsed_seconds=perf_counter() - started,
        finished_utc=datetime.now(timezone.utc).isoformat(), headline=result['headline'])
    save(target / 'reuse_manifest.json', receipt)
    # Include cache provenance in the normal run manifest too.
    run_manifest = read(target / 'analysis/run_manifest.json')
    run_manifest['reused_stages'] = {'manifest': '../reuse_manifest.json',
        'intact_traffic_source': str(prior / 'analysis'),
        'failure_traffic': 'recomputed; full directed snapshots saved in ../traffic_failure_snapshots',
        'flood_probabilities_sha256': sha256_file(target / 'flood/failure_probabilities.csv')}
    save(target / 'analysis/run_manifest.json', run_manifest)
    save(target / 'workflow_complete.json', {'status': 'complete', 'default_view': result['default_view'],
        'headline': result['headline'], 'flood_used': True, 'flood_reused': True,
        'intact_traffic_reused': True, 'failure_traffic_recomputed': True,
        'analysis': str(target / 'analysis'), 'elapsed_seconds': perf_counter() - started})
    log(f'{city}: complete, composite {result["headline"]["value"]:.8f}, elapsed {perf_counter() - started:.1f}s')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--city', required=True, choices=CITIES)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--memory-gb', type=float, default=.35)
    args = parser.parse_args()
    run_city(args.city, args.output, args.jobs, args.memory_gb)
