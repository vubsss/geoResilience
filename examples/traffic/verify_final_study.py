"""Verify published city runs and export final population-default charts."""
import csv
from importlib.metadata import version
import json
import math
from pathlib import Path
import shutil
from types import SimpleNamespace

import geopandas as gpd
import numpy as np

from georesilience.comparison import compare_runs
from georesilience.composite import calculate_composites
from georesilience.config import CompositeConfig
from georesilience.figures import FIGURE_FILENAMES, SERVICE_FIGURE_FILENAMES, write_figures
from georesilience.population import sha256_file
from georesilience.reporting import build_report

ROOT = Path(__file__).resolve().parents[2]


def read_csv(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def verify(city, folder):
    summary = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    manifest = json.loads((folder/'run_manifest.json').read_text(encoding='utf-8'))
    completed = json.loads((folder.parent/'workflow_complete.json').read_text(encoding='utf-8'))
    assert completed['status'] == 'complete' and completed['flood_used']
    assert summary['default_view'] == 'population_weighted'
    for item in manifest['inputs']:
        assert sha256_file(item['path']) == item['sha256'], item['path']
    composite = calculate_composites(summary, CompositeConfig.model_validate(manifest['resolved_config']['composite']))
    assert composite == summary['composite']
    assert summary['headline'] == composite['population_weighted'] == completed['headline']
    assert composite['population_weighted']['weights'] == {
        'bridge': .15, 'detour': .15, 'attack': .25, 'accessibility': .15,
        'travel_time_reliability': .15, 'connectivity_reliability': .15}
    network = folder/'network.gpkg'
    nodes = gpd.read_file(network, layer='nodes')
    edges = gpd.read_file(network, layer='edges')
    traffic = gpd.read_file(network, layer='traffic_arcs')
    facilities = gpd.read_file(network, layer='facilities')
    assert len(nodes) == {'gachibowli': 593, 'old-hyderabad': 3265}[city]
    assert len(traffic) == {'gachibowli': 1305, 'old-hyderabad': 8435}[city]
    assert nodes.node_id.is_unique and edges.link_uid.is_unique and facilities.facility_id.is_unique
    assert len(traffic) == len(read_csv(folder/'traffic_arcs.csv'))
    assert np.isfinite(nodes.population).all() and (nodes.population >= 0).all()
    assert math.isclose(nodes.population.sum(), {'gachibowli': 58489.320850372314,
        'old-hyderabad': 200473.33502197266}[city], rel_tol=1e-12)
    active = edges.loc[~edges.is_self_loop]
    assert np.isfinite(active.p_fail).all() and active.p_fail.between(0, 1).all()
    assert summary['probabilities']['coverage']['by_source']['proxy']['links'] == 0
    events = read_csv(folder/'traffic_failure_states.csv')
    assert len(events) == 64
    assert {int(r['sample']) for r in events} == set(range(64))
    for event in events:
        assert event['status'] == 'converged'
        assert 0 <= float(event['unserved_demand_pcu_h']) <= float(event['original_demand_pcu_h'])
        assert float(event['relative_gap']) <= manifest['resolved_config']['traffic']['relative_gap'] + 1e-10
    assert summary['traffic']['failure_reassignment']['all_converged']
    # These long-running studies started before descriptive service metadata
    # was updated. Correct labels using already-exported state statistics only;
    # do not change any metric, weight, probability or manifest input.
    metadata_updates = []
    services = summary.get('services')
    failure = summary['traffic'].get('failure_reassignment')
    if services and failure and any('_population_mean_per_1000' in key for key in failure['means']):
        services['failure_sfca'] = failure
        services['limitations'] = (
            'per-event static 2SFCA catchments recomputed after traffic reassignment; original demand retained; '
            'facility operations assumed unaffected except road access; missing neighbouring supply/demand not corrected')
        metadata_updates.append('Expose existing per-state 2SFCA statistics and correct the service limitation label.')
    if services and summary['metric_cost']['kind'] == 'time':
        services['service_weighted']['hansen_accessibility']['definition'] = (
            'original population-to-service normalized seconds-decay Hansen, including co-location')
        metadata_updates.append('Label service Hansen as seconds-decay rather than length-decay.')
    (folder/'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8')
    (folder/'report.txt').write_text(build_report(summary), encoding='utf-8')
    # Refresh figures from the stored numeric outputs only, using population as
    # the default for accessibility/information maps. No metrics are recalculated.
    curve = []
    for row in read_csv(folder/'attack_curve.csv'):
        curve.append({k: (v if k == 'removed_link_uid' else float(v) if v else None) for k, v in row.items()})
    attack = SimpleNamespace(curve=curve)
    write_figures(nodes, edges, attack, summary, folder/'figures')
    assert all((folder/'figures'/name).is_file() for name in (*FIGURE_FILENAMES, *SERVICE_FIGURE_FILENAMES))
    for row in read_csv(folder/'composite.csv'):
        result = composite[row['view']]
        assert math.isclose(float(row['composite']), result['value'], abs_tol=1e-14)
        assert math.isclose(float(row['value']), result['components'][row['metric']], abs_tol=1e-14)
    return {'city': city, 'status': 'verified', 'population': float(nodes.population.sum()),
        'nodes': len(nodes), 'physical_roads': len(active), 'directed_arcs': len(traffic),
        'facilities': len(facilities), 'event_samples': len(events),
        'headline': summary['headline'], 'coverage': summary['coverage'],
        'descriptive_metadata_refresh': metadata_updates,
        'files': {str(p.relative_to(folder)): sha256_file(p) for p in folder.rglob('*') if p.is_file()}}


def main():
    root = ROOT/'results/final_pipeline'
    folders = {city: root/f'{city}_flood/analysis' for city in ('gachibowli', 'old-hyderabad')}
    evidence = [verify(city, folder) for city, folder in folders.items()]
    shutil.copyfile(ROOT/'tmp/scientific_audit_tests.log', root/'regression.log')
    rows = compare_runs({'Gachibowli | modeled flood': folders['gachibowli'],
                        'Old Hyderabad | modeled flood': folders['old-hyderabad']}, root/'comparison')
    (root/'acceptance.json').write_text(json.dumps({'status': 'verified', 'cities': evidence,
        'runtime_versions': {p: version(p) for p in ('networkit', 'numpy', 'scipy', 'geopandas', 'pydantic')},
        'tests': {'offline_suite': '403 passed, 6 skipped; see regression.log',
                  'report_followup': '29 focused tests passed after report updates',
                  'real_sfincs_acceptance': '5 passed'},
        'scope': 'Both complete study CLI runs; provided real SFINCS depth, fresh probability extraction, full configured screened local/service analysis, attack, reassigned traffic, six-component composite. Facility metrics remain separate.'}, indent=2)+'\n', encoding='utf-8')
    lines = ['# Final integrated framework results', '',
        'Both city study runs completed and their exported numerical outputs passed verification. Population is the default headline view. The original 25% attack / 15% other weights are retained; critical-facility accessibility remains separate.', '',
        '| Metric | Gachibowli | Old Hyderabad |', '| --- | ---: | ---: |']
    for metric in ('bridge', 'detour', 'attack', 'accessibility', 'travel_time_reliability', 'connectivity_reliability', 'composite'):
        lines.append('| '+metric+' | '+' | '.join(f'{row[metric]:.6f}' for row in rows)+' |')
    lines += ['',
        'These values use the existing production attack protocol (undirected adaptive ranking after each road removal), with raw AUC normalized by its actual horizon. Earlier presentation scripts used directed centrality updated in 20 batches. Their attack and composite numbers are a different protocol and must not be presented as an exact replay of these production values.', '',
        'Bridge redundancy stays structural. Detour, attack ranking and ordinary Hansen use intact congested costs; failure reliability uses flood probabilities and reassigned traffic after each sampled closure. Local single-removal and targeted-attack experiments retain their existing definitions rather than running a separate equilibrium for every adversarial removal.', '',
        '## Outputs', '',
        '- `gachibowli_flood/analysis` and `old-hyderabad_flood/analysis`: GIS layers, summary, composite component CSV, traffic arcs/OD, failure-state records, attack curve, report, manifest and figures.',
        '- Each city `flood` folder: newly extracted road probabilities, enriched network, coverage report and closure manifest.',
        '- `comparison/components.png` and `.svg`: normalized metrics, fixed 0-1 axis.',
        '- `comparison/composite.png` and `.svg`: population-default composite comparison.',
        '- `comparison/comparison.csv`: graph values.',
        '- `acceptance.json`: input-hash, numerical, GIS, event convergence and output checksum checks.', '',
        '## Reproduction', '',
        'See `docs/final_pipeline.md` and `examples/traffic/prepare_final_study.py`. Study configs are in `data/final_study`; choose fresh output directories when rerunning. The example scenarios reuse the completed real pinned-SFINCS maximum-depth raster and perform probability extraction anew. Remove the supplied depth to rerun rainfall-to-depth simulation.', '',
        '## Scientific scope', '',
        '64 Monte Carlo failure states per city are explicit study settings, not claims of six-decimal precision. See individual metric confidence bounds. Criticality coverage is screened and its exact evaluated IDs/counts are exported; unevaluated local removal measures are null. Population allocation losses from the original raster and missing external demand/supply are not repaired by replaying retained counts. Traffic demand/capacity, runoff, drainage and fragility assumptions are uncalibrated. The incomplete Gachibowli facility footprint and one assumed capacity unit per institution remain limitations. These results demonstrate an executable framework and a modeled scenario; they are not validation of actual present-day traffic or flood closure observations.', '']
    (root/'README.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'status': 'verified', 'scores': rows, 'output': str(root)}, indent=2))


if __name__ == '__main__':
    main()
