"""Audit retained road tags and replay intact traffic with current capacity rules.

Does not overwrite published studies or recalculate/select composite weights.
Requires the prepared original-city study configs and their recorded inputs.
"""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path

import osmnx as ox

from georesilience.network import load_and_clean
from georesilience.population import sha256_file
from georesilience.time_models import FreeFlowTimeModel
from georesilience.traffic import canonical_traffic_graph, prepare_traffic, write_traffic_csv, write_traffic_od_csv
from georesilience.traffic_capacity import CAPACITY_TAGS
from georesilience.workflow import load_study

ROOT = Path(__file__).resolve().parents[2]


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8')


def read_csv(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def save_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def inventory(graph):
    arcs = [d for u, v, d in graph.edges(data=True) if u != v]
    return {'directed_nonloop_arcs': len(arcs),
            'present_tag_arc_counts': {tag: sum(tag in d for d in arcs) for tag in CAPACITY_TAGS},
            'all_lane_width_tag_keys': dict(Counter(k for d in arcs for k in d if 'lane' in k or 'width' in k))}


def main(output):
    output = output.resolve()
    if output.exists():
        raise ValueError('choose a fresh output directory; existing studies are never overwritten')
    output.mkdir(parents=True)
    comparison, manifests = [], {}
    for city in ('gachibowli', 'old-hyderabad'):
        folder = output/city; folder.mkdir()
        study_path = ROOT/f'data/final_study/{city}_flood.json'
        config = load_study(study_path).run
        if config.traffic.demand_source != 'od_csv':
            raise ValueError('this matched replay requires the original supplied OD matrix')
        old_path = ROOT/f'results/final_pipeline/{city}_flood/analysis/traffic_arcs.csv'
        config.traffic.capacity_csv = None
        config.traffic.capacity_pcu_h = None
        graph, _, _ = load_and_clean(config)
        raw = ox.load_graphml(config.input.path)
        fixed, changed = canonical_traffic_graph(graph, config.travel_time.highway_speeds_kph)
        free = FreeFlowTimeModel().prepare(fixed, config.travel_time)
        if free.summary['status'] != 'computed':
            raise ValueError('complete positive free-flow times required')
        result = prepare_traffic(fixed, config.traffic, free.edge_seconds)
        if result.summary['status'] != 'converged':
            raise RuntimeError(f'{city}: intact replay did not converge')
        label = lambda r: (r['u'], r['v'], r['key'])
        old = {label(r): r for r in read_csv(old_path)}
        current = {label(r): r for r in result.rows}
        if set(old) != set(current):
            raise ValueError('baseline and replay have different directed arc identities')
        differences = {field: {'changed_arcs': sum(abs(float(old[k][field])-float(current[k][field])) > 1e-9 for k in old),
            'max_absolute_difference': max(abs(float(old[k][field])-float(current[k][field])) for k in old)}
            for field in ('capacity_pcu_h', 'free_flow_time_s', 'assigned_volume_pcu_h', 'congested_time_s')}
        write_traffic_csv(result, folder/'traffic_arcs.csv')
        write_traffic_od_csv(result, folder/'traffic_od.csv')
        # Values-only CSV remains compatible with the existing override contract.
        save_csv(folder/'capacities.csv', [{k: r[k] for k in ('u', 'v', 'key', 'capacity_pcu_h')} for r in result.rows])
        audit = result.summary['capacity_audit']
        summary = {'status': 'complete', 'city': city, 'raw_inventory': inventory(raw),
            'retained_inventory': inventory(graph), 'capacity': audit,
            'traffic': result.summary, 'baseline_differences': differences,
            'mixed_tag_fields_resolved': changed,
            'scope': 'Intact capacity/traffic replay only. Flood, reliability and composite are not rerun or changed.'}
        save_json(folder/'summary.json', summary)
        sources = [('study_config', study_path), ('roads', config.input.path),
                   ('original_od', config.traffic.od_csv), ('checkpoint_arcs', old_path),
                   ('capacity_implementation', ROOT/'src/georesilience/traffic_capacity.py'),
                   ('traffic_implementation', ROOT/'src/georesilience/traffic.py'),
                   ('network_implementation', ROOT/'src/georesilience/network.py'), ('audit_script', Path(__file__))]
        manifests[city] = {'inputs': [{'role': role, 'path': str(path.resolve()), 'sha256': sha256_file(path)} for role, path in sources],
            'traffic_config': config.traffic.model_dump(mode='json'),
            'speed_config': config.travel_time.model_dump(mode='json')}
        save_json(folder/'manifest.json', manifests[city])
        comparison.append({'city': city, 'arcs': audit['directed_arcs'],
            'lanes_tag_arcs': audit['by_source'].get('lanes_tag', 0),
            'width_inferred_arcs': audit['by_source'].get('width_inferred_lanes', 0),
            'default_arcs': audit['by_source'].get('default_lanes', 0),
            'default_pct': audit['fallback_arc_pct'],
            'directional_tag_arcs': sum(any(k in json.loads(r['capacity_raw_tags']) for k in
                ('lanes:forward', 'lanes:backward', 'width:forward', 'width:backward')) for r in result.rows),
            'changed_capacity_arcs': differences['capacity_pcu_h']['changed_arcs'],
            'max_changed_travel_seconds': differences['congested_time_s']['max_absolute_difference'],
            'assignment_relative_gap': result.summary['relative_gap']})
        print(city, json.dumps(comparison[-1]), flush=True)
    save_csv(output/'comparison.csv', comparison)
    lines = ['# Road-capacity audit', '',
        'Both original study networks were audited and their intact traffic reassigned using the unchanged OD demand, speed table, BPR parameters and convergence target. No composite or flood outputs were overwritten.', '',
        '| Area | Directed arcs | Lane-based | Width-based | Defaults | Default % | Directional tags | Changed capacities |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for r in comparison:
        lines.append(f"| {r['city']} | {r['arcs']} | {r['lanes_tag_arcs']} | {r['width_inferred_arcs']} | {r['default_arcs']} | {r['default_pct']:.3f} | {r['directional_tag_arcs']} | {r['changed_capacity_arcs']} |")
    lines += ['',
        'Lane/width tags constrain geometry; the configured PCU/hour/lane remains an assumption. Missing archival tags cannot be recovered by changing a parser. No new OSM download was substituted, so geography and road identities remain matched.', '',
        'Rules: use explicit directional counts only with unambiguous OSMnx way orientation; exclude shared centre lanes from independent through capacity; derive a missing directional count only from consistent total/opposite counts; otherwise label equal splits, width inference or configured defaults. One-way totals are not halved. Shared narrow-road conflicts, reserved lanes, signals and parking are not calibrated.', '',
        'Per-city traffic_arcs.csv includes original capacity tags, resolved rule, assumptions and invalid-field flags; capacities.csv provides compatible values-only overrides. summary.json records raw and retained tag inventories, exact baseline differences and convergence. manifest.json binds consumed inputs and implementation files by SHA-256.', '',
        'Reproduce with PYTHONPATH=src and python examples/traffic/audit_capacities.py --output <fresh-directory>.', '']
    (output/'README.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Complete:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'results/traffic_capacity_audit')
    main(parser.parse_args().output)
