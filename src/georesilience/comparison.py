"""Export honest shared-scale comparison charts from published pipeline results."""
import csv
import json
from pathlib import Path

import numpy as np


def compare_runs(runs, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output = Path(output)
    summaries = {label: json.loads((Path(folder)/'summary.json').read_text(encoding='utf-8'))
                 for label, folder in runs.items()}
    if not summaries:
        raise ValueError('comparison requires at least one published run')
    reference = next(iter(summaries.values()))
    for summary in summaries.values():
        if (summary['default_view'] != reference['default_view']
                or summary['composite'][summary['default_view']]['weights'] != reference['composite'][reference['default_view']]['weights']
                or summary['metric_cost'] != reference['metric_cost']):
            raise ValueError('comparison requires matching views, composite weights and routing-cost definitions')
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for label, summary in summaries.items():
        view = summary['default_view']
        result = summary['composite'][view]
        rows.append(dict(run=label, view=view, **result['components'], composite=result['value']))
    with (output/'comparison.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    keys = ['bridge', 'detour', 'attack', 'accessibility', 'travel_time_reliability', 'connectivity_reliability']
    labels = ['Bridge\nredundancy', 'Detour\nredundancy', 'Attack\nrobustness', 'Time\naccessibility', 'Travel-time\nreliability', 'Connectivity\nreliability']
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    colors = ['#147d92', '#dd7544', '#294b72', '#7b6d9d']
    fig, ax = plt.subplots(figsize=(13, 6))
    width = .8/len(rows)
    x = np.arange(len(keys))
    for i, row in enumerate(rows):
        values = [row[k] if row[k] is not None else np.nan for k in keys]
        ax.bar(x-.4+width*(i+.5), values, width*.92, label=row['run'], color=colors[i%len(colors)])
    ax.set(xticks=x, xticklabels=labels, ylim=(0, 1), ylabel='Normalized component (higher is better)',
           title='Road-network resilience | ' + reference['default_view'].replace('_', ' ') + ' headline')
    ax.yaxis.grid(True, alpha=.18)
    ax.set_axisbelow(True)
    ax.legend(ncol=2, loc='upper center', bbox_to_anchor=(.5, -.12), frameon=False)
    fig.text(.01, .01, 'Bridge/detour remain road-based. Capacity-based facility metrics are separate. Failure results are modeled scenario estimates.', fontsize=8, color='#555555')
    fig.tight_layout(rect=(0, .08, 1, 1))
    for extension in ('png', 'svg'):
        fig.savefig(output/f'components.{extension}', dpi=180, bbox_inches='tight')
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(10, 5))
    values = [r['composite'] if r['composite'] is not None else np.nan for r in rows]
    bars = ax.barh([r['run'] for r in rows], values, color=colors[:len(rows)])
    for bar, value in zip(bars, values):
        if np.isfinite(value):
            ax.text(value+.01, bar.get_y()+bar.get_height()/2, f'{value:.4f}', va='center')
    ax.set(xlim=(0, 1), xlabel='Composite resilience index (higher is better)', title='Composite | common configured weights')
    ax.invert_yaxis()
    ax.xaxis.grid(True, alpha=.18)
    ax.set_axisbelow(True)
    fig.tight_layout()
    for extension in ('png', 'svg'):
        fig.savefig(output/f'composite.{extension}', dpi=180, bbox_inches='tight')
    plt.close(fig)
    (output/'sources.json').write_text(json.dumps({label: str(Path(folder).resolve()) for label, folder in runs.items()}, indent=2)+'\n', encoding='utf-8')
    return rows
