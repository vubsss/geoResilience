"""Independently verify and ZIP the two importance-weighted traffic/flood runs."""

import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import geopandas as gpd
import numpy as np
from PIL import Image
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

from georesilience.comparison import compare_runs
from georesilience.composite import calculate_composites
from georesilience.config import CompositeConfig
from georesilience.figures import FIGURE_FILENAMES, SERVICE_FIGURE_FILENAMES
from georesilience.population import sha256_file

SOURCE = ROOT / 'results/final_deliverables/GeoResilience_Final_Results_20261114'
DEFAULT_OUTPUT = ROOT / 'results/node_importance_traffic_flood_20261114'
CITIES = ('gachibowli', 'old-hyderabad')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def read_csv(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def verify_city(city, output):
    folder = output / 'cities' / city
    analysis = folder / 'analysis'
    summary = read(analysis / 'summary.json')
    manifest = read(analysis / 'run_manifest.json')
    assert read(folder / 'workflow_complete.json')['status'] == 'complete'
    receipt = read(folder / 'reuse_manifest.json')
    assert receipt['status'] == 'complete'
    for relative, checksum in receipt['source_code_sha256'].items():
        assert sha256_file(ROOT / relative) == checksum, relative
    assert sha256_file(ROOT / 'examples/traffic/run_importance_study.py') == receipt['runner_sha256']
    # Keep a native StudyConfig alongside the checkpoint loader's audit config.
    save(folder / 'configuration/rerun_study.json', {'run': manifest['resolved_config']})
    for item in manifest['inputs']:
        assert sha256_file(item['path']) == item['sha256'], item['path']
    assert summary['default_view'] == 'node_importance_weighted'
    assert summary['headline'] == summary['composite']['node_importance_weighted']
    assert calculate_composites(summary, CompositeConfig.model_validate(
        manifest['resolved_config']['composite'])) == summary['composite']
    nodes = gpd.read_file(analysis / 'network.gpkg', layer='nodes')
    edges = gpd.read_file(analysis / 'network.gpkg', layer='edges')
    arcs = gpd.read_file(analysis / 'network.gpkg', layer='traffic_arcs')
    facilities = gpd.read_file(analysis / 'network.gpkg', layer='facilities')
    assert len(nodes) == {'gachibowli': 593, 'old-hyderabad': 3265}[city]
    assert len(arcs) == {'gachibowli': 1305, 'old-hyderabad': 8435}[city]
    assert nodes.node_id.is_unique and edges.link_uid.is_unique and facilities.facility_id.is_unique
    assert np.isfinite(nodes.population).all() and (nodes.population >= 0).all()
    p = nodes.population.to_numpy(dtype=float)
    w = nodes.service_weight.to_numpy(dtype=float)
    coefficient = manifest['resolved_config']['services']['population_importance']
    expected_importance = coefficient * p / p.sum() + w / w.sum()
    np.testing.assert_allclose(nodes.node_importance, expected_importance, rtol=1e-13)
    np.testing.assert_allclose(nodes.importance_population_component, coefficient * p / p.sum(), rtol=1e-13)
    np.testing.assert_allclose(nodes.importance_service_component, w / w.sum(), rtol=1e-13)
    assert int(nodes.evaluated.sum()) == summary['coverage']['nodes']['evaluated']
    assert int(edges.evaluated.sum()) == summary['coverage']['links']['evaluated']
    assert summary['probabilities']['coverage']['by_source']['proxy']['links'] == 0
    for frame, fields in ((nodes, ('information_centrality_importance', 'accessibility_drop_importance',
                                  'disconnected_pair_fraction_importance')),
                          (edges, ('efficiency_drop_importance', 'accessibility_drop_importance',
                                  'disconnected_pair_fraction_importance'))):
        for field in fields:
            values = frame[field].dropna().to_numpy(dtype=float)
            assert np.isfinite(values).all() and (values >= -1e-12).all() and (values <= 1 + 1e-12).all()
            assert frame.loc[~frame.evaluated.astype(bool), field].isna().all()
    for category in ('school', 'hospital'):
        sfca = summary['services']['sfca'][category]
        assert sfca['status'] == 'computed'
        np.testing.assert_allclose(p @ nodes[category + '_sfca'].to_numpy(), sfca['positive_demand_capacity'], rtol=1e-12)

    prior = read(SOURCE / 'cities' / city / 'analysis/summary.json')
    original_views = {}
    for group in ('unweighted', 'population_weighted'):
        original_views[group] = {}
        for metric, old in prior[group].items():
            value = summary[group][metric]['value']
            if old['value'] is None:
                assert value is None
            else:
                np.testing.assert_allclose(value, old['value'], rtol=1e-11, atol=1e-13,
                    err_msg=f'{city}: original {group}.{metric} changed')
                original_views[group][metric] = value - old['value']
    # Check all 64 failure states independently from saved directed time maps.
    # This oracle uses its own CSR assembly and weight formulas, not the product
    # PairUniverse/reliability reducers or time topology.
    events = read_csv(analysis / 'traffic_failure_states.csv')
    assert len(events) == 64 and {int(r['sample']) for r in events} == set(range(64))
    node_index = {str(node): i for i, node in enumerate(nodes.node_id)}
    arc_to_link = {}
    # Traffic GIS has the physical link UID for every retained directed arc.
    link_id = dict(zip(edges.link_uid, edges.link_id.astype(int)))
    for row in arcs.itertuples():
        arc_to_link[str(row.u), str(row.v), str(row.key)] = link_id[row.link_uid]
    baseline_seconds = {(str(r.u), str(r.v), str(r.key)): float(r.congested_time_s) for r in arcs.itertuples()}

    def matrix(times, closed=(), isolated=()):
        closed, isolated = set(closed), set(isolated)
        minimum = {}
        for edge, seconds in times.items():
            u, v = node_index[edge[0]], node_index[edge[1]]
            if u == v or u in isolated or v in isolated or arc_to_link[edge] in closed:
                continue
            minimum[u, v] = min(minimum.get((u, v), float('inf')), seconds)
        return csr_matrix(([value for value in minimum.values()],
            ([uv[0] for uv in minimum], [uv[1] for uv in minimum])), shape=(len(nodes), len(nodes)))

    baseline = matrix(baseline_seconds)
    importance = nodes.node_importance.to_numpy(dtype=float, copy=True)
    importance /= importance.sum()
    pair_denominator = 1 - np.square(importance).sum()
    half_cost = summary['metric_cost']['half_cost']
    cutoff = half_cost * manifest['resolved_config']['accessibility']['cutoff_factor']
    hansen = np.empty(len(nodes))
    baseline_distances = []
    for start in range(0, len(nodes), 128):
        sources = np.arange(start, min(len(nodes), start + 128))
        before = dijkstra(baseline, directed=True, indices=sources)
        baseline_distances.append(before)
        decay = np.exp(-np.log(2) * before / half_cost)
        decay[before > cutoff] = 0
        decay[np.arange(len(sources)), sources] = 0
        hansen[sources] = (decay @ importance) / (1 - importance[sources])
    np.testing.assert_allclose(hansen, nodes.hansen_accessibility_importance, rtol=1e-11, atol=1e-13)
    np.testing.assert_allclose(importance @ hansen, summary['node_importance_weighted']['hansen_accessibility']['value'], rtol=1e-12)

    def aggregate(blocks):
        efficiency, access, reachable = 0., 0., 0.
        for block, start in enumerate(range(0, len(nodes), 128)):
            sources = np.arange(start, min(len(nodes), start + 128))
            costs = blocks[block]
            finite = np.isfinite(costs) & (costs > 0)
            inverse = np.divide(1., costs, out=np.zeros_like(costs), where=finite)
            decay = np.exp(-np.log(2) * costs / half_cost)
            decay[costs > cutoff] = 0
            decay[np.arange(len(sources)), sources] = 0
            finite[np.arange(len(sources)), sources] = False
            efficiency += float(importance[sources] @ (inverse @ importance)) / pair_denominator
            reachable += float(importance[sources] @ (finite @ importance)) / pair_denominator
            access += float(importance[sources] @ ((decay @ importance) / (1 - importance[sources])))
        return {'efficiency': efficiency, 'accessibility': access, 'reachable_fraction': reachable}

    intact = aggregate(baseline_distances)
    np.testing.assert_allclose(intact['efficiency'], summary['node_importance_weighted']['efficiency']['value'], rtol=1e-12)
    np.testing.assert_allclose(intact['reachable_fraction'], summary['node_importance_weighted']['reachable_pair_fraction']['value'], rtol=1e-12)
    local_checks = []
    # Independently verify the three largest evaluated road access losses and
    # node information losses, retaining every original node/pair denominator.
    for scope, chosen in (
            ('links', edges.dropna(subset=['accessibility_drop_importance']).nlargest(3, 'accessibility_drop_importance')),
            ('nodes', nodes.dropna(subset=['information_centrality_importance']).nlargest(3, 'information_centrality_importance'))):
        for identifier, row in chosen.iterrows():
            damaged = (matrix(baseline_seconds, closed=[int(row.link_id)]) if scope == 'links'
                       else matrix(baseline_seconds, isolated=[node_index[str(row.node_id)]]))
            blocks = [dijkstra(damaged, directed=True, indices=np.arange(start, min(len(nodes), start + 128)))
                      for start in range(0, len(nodes), 128)]
            after = aggregate(blocks)
            efficiency_field = 'efficiency_drop_importance' if scope == 'links' else 'information_centrality_importance'
            np.testing.assert_allclose(row[efficiency_field], (intact['efficiency'] - after['efficiency']) / intact['efficiency'], rtol=1e-10, atol=1e-12)
            np.testing.assert_allclose(row.accessibility_drop_importance,
                (intact['accessibility'] - after['accessibility']) / intact['accessibility'], rtol=1e-10, atol=1e-12)
            np.testing.assert_allclose(row.disconnected_pair_fraction_importance,
                intact['reachable_fraction'] - after['reachable_fraction'], rtol=1e-10, atol=1e-12)
            local_checks.append({'scope': scope, 'id': str(row.link_uid if scope == 'links' else row.node_id),
                                 'efficiency_information': float(row[efficiency_field]),
                                 'accessibility_loss': float(row.accessibility_drop_importance)})
    threshold = manifest['resolved_config']['travel_time']['tau']
    probabilities = dict(zip(edges.link_id.astype(int), edges.p_fail))
    active_ids = sorted(edges.loc[~edges.is_self_loop.astype(bool), 'link_id'].astype(int))
    probability_array = np.asarray([probabilities[key] for key in active_ids])
    seed = manifest['seed']
    totals = np.zeros(2)
    event_evidence = []
    for row in sorted(events, key=lambda r: int(r['sample'])):
        sample = int(row['sample'])
        assert row['status'] == 'converged'
        assert float(row['relative_gap']) <= manifest['resolved_config']['traffic']['relative_gap'] + 1e-10
        assert 0 <= float(row['unserved_demand_pcu_h']) <= float(row['original_demand_pcu_h'])
        closed = json.loads(row['closed_link_ids'])
        uniforms = np.random.default_rng(np.random.SeedSequence([seed, sample])).random(len(active_ids))
        expected_closed = [key for key, uniform, prob in zip(active_ids, uniforms, probability_array)
                           if uniform < prob or prob == 1]
        assert closed == expected_closed
        path = folder / 'traffic_failure_snapshots' / f'sample_{sample:04d}.npz'
        with np.load(path, allow_pickle=False) as snapshot:
            assert snapshot['closed_link_ids'].tolist() == closed
            assert len(snapshot['seconds']) == len(arcs)
            assert np.isfinite(snapshot['seconds']).all() and (snapshot['seconds'] > 0).all()
            times = {tuple(edge): float(seconds) for edge, seconds in zip(snapshot['edges'], snapshot['seconds'])}
        assert set(times) == set(baseline_seconds)
        event = matrix(times, closed)
        _, labels = connected_components(event, directed=True, connection='strong')
        mass = np.bincount(labels, weights=importance)
        connectivity = (np.square(mass).sum() - np.square(importance).sum()) / pair_denominator
        travel = 0.
        for block, start in enumerate(range(0, len(nodes), 128)):
            sources = np.arange(start, min(len(nodes), start + 128))
            before = baseline_distances[block]
            after = dijkstra(event, directed=True, indices=sources)
            bound = (1 + threshold) * before
            success = np.isfinite(before) & np.isfinite(after) & (after <= bound + 1e-9 + 1e-12 * np.abs(bound))
            success[np.arange(len(sources)), sources] = False
            travel += float(importance[sources] @ (success @ importance)) / pair_denominator
        totals += [connectivity, travel]
        event_evidence.append({'sample': sample, 'closed_roads': len(closed),
            'connectivity_importance': connectivity, 'travel_time_importance': travel,
            'snapshot_sha256': sha256_file(path)})
        if (sample + 1) % 16 == 0:
            print(f'{city}: independently checked {sample + 1}/64 failure snapshots', flush=True)
    for metric, expected in zip(('connectivity_reliability', 'travel_time_reliability'), totals / len(events)):
        actual = summary['node_importance_weighted'][metric]
        np.testing.assert_allclose(actual['value'], expected, rtol=1e-11, atol=1e-13)
        assert actual['samples'] == 64 and actual['ci_low'] <= actual['value'] <= actual['ci_high']
    curve = read_csv(analysis / 'attack_curve.csv')
    area = np.trapezoid([float(r['node_importance_share']) for r in curve],
        [float(r['fraction_removed']) for r in curve])
    np.testing.assert_allclose(area, summary['node_importance_weighted']['targeted_attack_robustness']['value'], rtol=1e-13)
    for name in (*FIGURE_FILENAMES, *SERVICE_FIGURE_FILENAMES):
        with Image.open(analysis / 'figures' / name) as png:
            assert png.width > 500 and png.height > 300
            png.verify()
    for frame, filename in ((nodes, 'node_metrics.csv'), (edges, 'link_metrics.csv')):
        frame.drop(columns='geometry').to_csv(analysis / filename, index=False)
    write_criticality_maps(city, edges, analysis, summary)
    evidence = {'status': 'verified', 'city': city,
        'nodes': len(nodes), 'physical_roads_including_self_loops': len(edges),
        'non_self_loop_roads': int((~edges.is_self_loop.astype(bool)).sum()), 'directed_arcs': len(arcs),
        'facilities': len(facilities), 'population': float(p.sum()),
        'importance_total': float(nodes.node_importance.sum()),
        'coverage': {k: {key: value for key, value in v.items() if key != 'ids'}
                     for k, v in summary['coverage'].items()},
        'all_original_view_differences': original_views,
        'independent_hansen_check': 'all original origins and destinations',
        'independent_local_removal_checks': local_checks,
        'independent_reliability_check': 'all 64 states and all original distinct importance-weighted pairs',
        'event_evidence': event_evidence, 'headline': summary['headline']}
    save(output / 'verification' / (city + '.json'), evidence)
    return evidence


def write_criticality_maps(city, edges, analysis, summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fields = [('efficiency_drop_importance', 'Relative network efficiency loss'),
              ('accessibility_drop_importance', 'Relative Hansen accessibility loss'),
              ('disconnected_pair_fraction_importance', 'Original directed pair mass lost')]
    fig, axes = plt.subplots(1, 3, figsize=(17, 6))
    rows = []
    for ax, (field, label) in zip(axes, fields):
        edges.plot(ax=ax, color='#cccccc', linewidth=.6)
        selected = edges.loc[edges.evaluated.astype(bool) & edges[field].notna()].copy()
        maximum = max(float(selected[field].max()), 1e-12)
        selected.plot(ax=ax, column=field, cmap='magma_r', vmin=0, vmax=maximum,
            linewidth=1.5, legend=True, legend_kwds={'shrink': .65})
        ax.set_title(label, fontsize=11)
        ax.set_axis_off()
        ordered = selected.sort_values([field, 'link_uid'], ascending=[False, True])
        for rank, row in enumerate(ordered.head(20).itertuples(), 1):
            rows.append({'metric': field, 'rank_among_evaluated': rank, 'link_uid': row.link_uid,
                         'name': row.name, 'value': float(getattr(row, field))})
    coverage = summary['coverage']['links']
    fig.suptitle(f'{city.replace("-", " ").title()} | importance-weighted road closure consequences', fontsize=15)
    fig.text(.5, .035, f'Screened: {coverage["evaluated"]} / {coverage["total"]} roads evaluated. '
        'Grey roads are unevaluated. Panels use their own labeled color scales. Intact congested costs.',
        ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .07, 1, .94))
    fig.savefig(analysis / 'figures/link_criticality_importance.png', dpi=160)
    plt.close(fig)
    with (analysis / 'top_evaluated_links_importance.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def package(output):
    output = output.resolve()
    evidence = [verify_city(city, output) for city in CITIES]
    for relative, checksum in read(SOURCE / 'verification/checksums.json').items():
        if relative.startswith(('shared_flood_model/', 'capacity_audit/')):
            assert sha256_file(SOURCE / relative) == checksum, relative
    shared = output / 'shared_flood_model'
    if not shared.exists():
        shutil.copytree(SOURCE / 'shared_flood_model', shared)
    audit = output / 'capacity_audit'
    if not audit.exists():
        shutil.copytree(SOURCE / 'capacity_audit', audit)
    compare_runs({'Gachibowli': output / 'cities/gachibowli/analysis',
                  'Old Hyderabad': output / 'cities/old-hyderabad/analysis'}, output / 'comparison')
    weights = {key: evidence[0]['headline']['weights'][key] for key in
        ('bridge', 'detour', 'attack', 'accessibility', 'travel_time_reliability', 'connectivity_reliability')}
    with (output / 'final_scores.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['city', *weights, 'composite'])
        writer.writeheader()
        for item in evidence:
            writer.writerow({'city': item['city'], **item['headline']['components'], 'composite': item['headline']['value']})
    with (output / 'weighting_comparison.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['city', 'view', *weights, 'composite'])
        writer.writeheader()
        for city in CITIES:
            summary = read(output / 'cities' / city / 'analysis/summary.json')
            for view, result in summary['composite'].items():
                writer.writerow({'city': city, 'view': view, **result['components'], 'composite': result['value']})
    lines = ['# Combined node importance: traffic and flood results', '',
        'Gachibowli and Old Hyderabad. Headline: node_importance_weighted. Both complete analyses use the existing combined population-plus-school/hospital importance. Composite coefficients are recorded below and in the manifests; defaults give redundancy, robustness, accessibility and reliability 25% each.',
        'Applied metric weights: ' + ', '.join(f'{key} {value:.1%}' for key, value in weights.items()) + '.', '',
        '| Normalized component | Gachibowli | Old Hyderabad |', '| --- | ---: | ---: |']
    for metric in weights:
        lines.append('| ' + metric + ' | ' + ' | '.join(f'{x["headline"]["components"][metric]:.6f}' for x in evidence) + ' |')
    lines.append('| Composite | ' + ' | '.join(f'{x["headline"]["value"]:.6f}' for x in evidence) + ' |')
    lines += ['', '## Files', '',
        '- cities/<area>/analysis/network.gpkg: QGIS layers nodes, edges, traffic_arcs, facilities.',
        '- cities/<area>/analysis/report.txt and summary.json: all metric views, definitions, coverage and confidence bounds; headline selects combined importance.',
        '- cities/<area>/analysis/figures/: metric, attack, reliability, composite and service maps/charts.',
        '- cities/<area>/analysis/figures/link_criticality_importance.png and top_evaluated_links_importance.csv: importance-weighted road closure maps and the highest evaluated losses; panel color scales are labeled separately.',
        '- cities/<area>/analysis/composite.csv, node_metrics.csv, link_metrics.csv, attack_curve.csv, traffic_arcs.csv, traffic_od.csv and traffic_failure_states.csv: full numeric exports.',
        '- cities/<area>/analysis/run_manifest.json: consumed input hashes, settings, versions, weights and original pair mass.',
        '- cities/<area>/traffic_failure_snapshots/: full directed seconds for all 64 failure samples, with closed physical-road IDs; reusable for later weighting changes.',
        '- cities/<area>/flood/ and shared_flood_model/: reused flood probabilities, coverage, hydraulic metadata and maximum-depth raster.',
        '- cities/<area>/reuse_manifest.json and workflow_complete.json: explicit reuse and recomputation receipt.',
        '- cities/<area>/configuration/rerun_study.json: native study settings; set a fresh output directory before rerunning.',
        '- comparison/: both-area component/composite CSV and PNG/SVG charts. final_scores.csv summarizes headline values.',
        '- weighting_comparison.csv: all six normalized components and composite under combined importance, population and unweighted views for each area.',
        '- verification/: independent numerical checks, regression logs, source snapshots and checksums.', '',
        '## Method and reuse', '',
        'I_i = population_importance * P_i/sum(P) + service_weight_i/sum(service_weight), using the already calculated importance. Pair metrics use original I_i*I_j weights on distinct ordered pairs; Hansen excludes the origin from destination mass and averages origins by I_i. Original weights and denominators are fixed after failures. Attack uses importance retained in the same node-selected SCC. Bridge/detour and betweenness retain their structural definitions. Capacity-based 2SFCA and traffic demand retain resident counts.', '',
        'Previously verified flood probabilities and converged intact traffic are reused after source/input SHA-256 checks, cleaning-fingerprint checks and matching every directed free-flow time and capacity. All configured local consequences and attack are recomputed. All 64 event traffic assignments and per-state 2SFCA are recomputed because prior results did not retain full directed event times. Current failure snapshots are included for future reuse. Original population and unweighted results reproduce the previous run within numerical tolerance.', '',
        '## Coverage and interpretation', '',
        'There are 64 Monte Carlo failure states per area, seed 42, with all original origins/pairs evaluated. All assignments converged. Confidence intervals are in summary.json; displayed decimals are numerical precision, not empirical accuracy. Local single-removal analysis retains screened coverage (top 30 centrality/detour candidates plus all bridges/no-alternative roads, service nodes and incident roads). Unevaluated removals are null with reasons, not zero. Exact evaluated IDs are in each manifest. These screening results do not establish a global maximum across unevaluated closures.', '',
        'Traffic and flood are modeled scenarios, not measured present-day conditions. Demand, mostly default road capacities, hydraulic runoff/roughness and fragility remain uncalibrated. The original flood uses reported rainfall and 120 m terrain. Gachibowli facility coverage is incomplete; each institution has one assumed capacity unit rather than measured beds/seats. Boundary effects and original unallocated population remain limitations. Flood reliability reassigns traffic; targeted attack and local single removals retain intact congested costs.', '',
        '## Reproduction', '',
        'The outputs are standalone for inspection. Manifests preserve absolute original paths for audit; reruns need the repository and original inputs. The source files, runnable study settings and runner are included under verification/source. Run examples/traffic/run_importance_study.py with --city and a fresh --output directory. The runner applies an explicitly scoped checkpoint loader to the ordinary pipeline traffic-preparation stage; all metric and failure calculations use production functions. No prior published result is edited.', '']
    (output / 'README.md').write_text('\n'.join(lines), encoding='utf-8')
    source_folder = output / 'verification/source'
    for path in [*sorted((ROOT / 'src/georesilience').rglob('*.py')),
                 ROOT / 'examples/traffic/run_importance_study.py', Path(__file__),
                 ROOT / 'README.md', ROOT / 'docs/final_pipeline.md', ROOT / 'pyproject.toml',
                 ROOT / 'tests/test_node_importance_indices.py']:
        target = source_folder / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    for city, name in (('gachibowli', 'importance_gachibowli_final.log'), ('old-hyderabad', 'importance_old_hyderabad_final.log')):
        raw = (ROOT / 'tmp' / name).read_bytes()
        text = raw.decode('utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig')
        (output / 'verification' / (city + '_run.log')).write_text(text, encoding='utf-8')
    raw = (ROOT / 'tmp/importance_regression.log').read_bytes()
    regression = raw.decode('utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig')
    assert '447 passed, 6 skipped' in regression
    (output / 'verification/importance_regression.log').write_text(regression, encoding='utf-8')
    save(output / 'verification/acceptance.json', {'status': 'verified', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'cities': [{k: v for k, v in item.items() if k != 'event_evidence'} for item in evidence],
        'tests': 'See importance_regression.log; individual data checks also cover all 64 saved event snapshots.'})
    checksums = {p.relative_to(output).as_posix(): sha256_file(p)
                 for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'checksums.json'}
    save(output / 'verification/checksums.json', checksums)
    archive_path = ROOT / 'results/final_deliverables/GeoResilience_Node_Importance_Traffic_Flood_20261114.zip'
    if archive_path.exists():
        raise ValueError('refusing to replace an existing ZIP')
    prefix = 'GeoResilience_Node_Importance_Traffic_Flood_20261114'
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                archive.write(path, prefix + '/' + path.relative_to(output).as_posix())
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        for relative, checksum in checksums.items():
            with archive.open(prefix + '/' + relative) as stream:
                digest = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
                assert digest.hexdigest() == checksum, relative
    print(json.dumps({'status': 'verified', 'zip': str(archive_path),
        'size_mb': archive_path.stat().st_size / 1e6, 'files': len(checksums) + 1,
        'composites': {x['city']: x['headline']['value'] for x in evidence}}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--verify-city', choices=CITIES)
    args = parser.parse_args()
    if args.verify_city:
        verify_city(args.verify_city, args.output.resolve())
    else:
        package(args.output.resolve())
