"""Explicit normalization and configurable six-component resilience index."""
import csv
import math
from pathlib import Path


def calculate_composites(summary, config):
    weights = config.weights.model_dump()
    results = {}
    views = ['population_weighted', 'unweighted']
    if 'node_importance_weighted' in summary:
        views.append('node_importance_weighted')
    for view in views:
        measures = summary[view]
        redundancy = summary['unweighted']
        ratio = redundancy['detour_redundancy']['value']
        horizon = summary['attack']['horizon']
        area = measures['targeted_attack_robustness']['value']
        components = {
            'bridge': redundancy['bridge_redundancy']['value'],
            'detour': 1 / ratio if ratio is not None and ratio >= 1 else None,
            'attack': area / horizon if area is not None and horizon > 0 else None,
            'accessibility': measures['hansen_accessibility']['value'],
            'travel_time_reliability': measures['travel_time_reliability']['value'],
            'connectivity_reliability': measures['connectivity_reliability']['value']}
        for key, value in components.items():
            if value is not None and (not math.isfinite(value) or not -1e-12 <= value <= 1+1e-12):
                raise ValueError(f'composite {key} is outside its normalized range')
            if value is not None:
                components[key] = min(1., max(0., value))
        unavailable = [key for key, value in components.items() if value is None and weights[key] > 0]
        contributions = {key: weights[key]*value if value is not None else (0. if weights[key] == 0 else None)
                         for key, value in components.items()}
        value = None if unavailable else math.fsum(contributions.values())
        # Uniform demand is kept visible, never described as resident-weighted.
        if view == 'population_weighted' and summary['population'].get('basis') == 'uniform_node_demand':
            value = None
            unavailable.append('resident population absent; uniform fallback is not a population-weighted composite')
        results[view] = {'value': value, 'reason': '; '.join(unavailable) if unavailable else None,
            'components': components, 'weights': weights, 'contributions': contributions,
            'normalization': {'bridge': '1 - physical bridge fraction', 'detour': '1 / median finite detour ratio',
                'attack': 'raw targeted-attack AUC / actual removal horizon',
                'accessibility': 'normalized ordinary Hansen',
                'reliability': 'fractions of original ordered pairs, equal or population-product weights'},
            'facility_metrics': 'reported separately; not included in this index'}
        if view == 'node_importance_weighted':
            results[view]['normalization'].update(
                accessibility='normalized Hansen with combined importance at origins and destinations',
                reliability='fractions of original distinct ordered pairs weighted by combined importance products I_i*I_j')
            results[view]['facility_metrics'] = (
                'school/hospital points included through combined node importance in attack, accessibility and reliability; '
                'bridge/detour remain structural; capacity-based 2SFCA reported separately')
    return results


def write_composites(results, path):
    with Path(path).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['view', 'metric', 'value', 'weight', 'contribution', 'composite', 'reason'])
        writer.writeheader()
        for view, result in results.items():
            for metric, value in result['components'].items():
                writer.writerow(dict(view=view, metric=metric, value=value, weight=result['weights'][metric],
                    contribution=result['contributions'][metric], composite=result['value'], reason=result['reason']))
