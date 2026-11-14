"""One configuration-driven workflow: cleaned roads, optional flood, full analysis."""
import json
from pathlib import Path

import geopandas as gpd
from pydantic import model_validator

from .config import RunConfig, StrictModel
from .closure.config import load_config
from .closure.pipeline import enrich_road_closures
from .failure_probabilities import export_edge_template
from .links import _link_rows
from .network import load_and_clean
from .pipeline import run


class StudyConfig(StrictModel):
    run: RunConfig
    flood_config: Path | None = None

    @model_validator(mode='after')
    def probability_source(self):
        if self.flood_config is not None and self.run.reliability.p_fail_csv is not None:
            raise ValueError('choose flood_config or a supplied reliability.p_fail_csv, not both')
        return self


def load_study(path):
    path = Path(path).expanduser().resolve()
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('study configuration must be a JSON object')
    data = StudyConfig.model_validate(data).model_dump(mode='json')
    for section, keys in {
        'input': ('path', 'directory', 'boundary'), 'output': ('dir',),
        'population': ('worldpop', 'node_counts'),
        'traffic': ('od_csv', 'zone_mass_csv', 'edge_times_csv', 'capacity_csv'),
        'reliability': ('p_fail_csv', 'od_pairs_csv'), 'services': ('facilities_csv',)}.items():
        values = data.get('run', {}).get(section) or {}
        for key in keys:
            if values.get(key) is not None:
                values[key] = str((path.parent / Path(values[key]).expanduser()).resolve())
    if data.get('flood_config') is not None:
        data['flood_config'] = path.parent / Path(data['flood_config']).expanduser()
    return StudyConfig.model_validate(data)


def run_study(path):
    config = load_study(path)
    root = config.run.output.dir.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('study output must be fresh; refusing to overwrite prior results')
    input_dir = (config.run.input.directory or config.run.input.path.parent).resolve()
    if root == input_dir or input_dir in root.parents:
        raise ValueError('study output must be outside the input directory')
    # Validate original consumed inputs and avoid ever putting output over an input.
    from .pipeline import _consumed
    consumed = _consumed(config.run)
    if any(root == Path(r['path']) or root in Path(r['path']).parents for r in consumed):
        raise ValueError('study output cannot contain consumed inputs')
    if config.flood_config is not None:
        flood = load_config(config.flood_config, roads=root/'prepared/network.gpkg', out=root/'flood')
        if any(root == p.resolve() or root in p.resolve().parents for k, p in flood.input_paths().items()
               if k not in ('roads', 'failure_template')):
            raise ValueError('study output cannot contain flood inputs')
    root.mkdir(parents=True, exist_ok=True)
    resolved = config.model_dump(mode='json')
    (root/'study_config.json').write_text(json.dumps(resolved, indent=2)+'\n', encoding='utf-8')
    if config.flood_config is not None:
        graph, _, _ = load_and_clean(config.run)
        folder = root/'prepared'
        folder.mkdir()
        roads = []
        for row in _link_rows(graph):
            record = {k: v for k, v in row.items() if not k.startswith('_')}
            # Preserve all available structure tags, across simplified segments.
            for field in ('bridge', 'tunnel', 'layer'):
                values = [graph.edges[e].get(field) for e in row['_edges']]
                values = [v for v in values if v is not None]
                if values:
                    record[field] = str(values[0]) if all(v == values[0] for v in values) else json.dumps(values, default=str)
            roads.append(record)
        network = folder/'network.gpkg'
        gpd.GeoDataFrame(roads, crs=graph.graph['crs']).to_file(network, layer='edges', driver='GPKG', index=False)
        template = folder/'failure_template.csv'
        export_edge_template(graph, template)
        flood = load_config(config.flood_config, roads=network, out=root/'flood', failure_template=template)
        result = enrich_road_closures(flood)
        if result.probabilities_csv is None:
            raise RuntimeError('flood workflow did not publish fingerprint-matched road probabilities')
        config.run.reliability.p_fail_csv = result.probabilities_csv
        config.run.reliability.require_complete_failures = True
    config.run.output.dir = root/'analysis'
    summary = run(config.run)
    (root/'workflow_complete.json').write_text(json.dumps({
        'status': 'complete', 'default_view': summary['default_view'],
        'headline': summary['headline'], 'flood_used': config.flood_config is not None,
        'analysis': str(config.run.output.dir), 'facility_metrics': 'separate from composite'}, indent=2)+'\n', encoding='utf-8')
    return summary
