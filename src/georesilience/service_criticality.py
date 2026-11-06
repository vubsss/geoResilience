"""Service access shortfall after shared node/link closure candidates."""

from dataclasses import dataclass

import numpy as np

from .od import node_id_key
from .service_inputs import SERVICE_TYPES
from .sfca import compute_sfca

TYPE_FIELDS = ('access_shortfall', 'newly_unserved_population_share', 'population_mean',
               'population_mean_change', 'equal_node_mean', 'equal_node_mean_change')
CONSEQUENCE_FIELDS = tuple(f'{category}_{field}' for category in SERVICE_TYPES for field in TYPE_FIELDS)
COMBINED = 'service_combined_shortfall'


@dataclass
class ServiceCriticality:
    nodes: dict
    links: dict
    summary: dict


def access_consequences(baseline, damaged, population, config):
    """Losses count independently of competition-induced gains elsewhere."""
    population = np.asarray(population, dtype=float)
    total = float(population.sum())
    origins = population / total if total else np.zeros_like(population)
    values, reasons, losses = {}, {}, {}
    for category in SERVICE_TYPES:
        before, after = baseline.categories[category], damaged.categories[category]
        reason = before.reason or after.reason
        fields = {field: None for field in TYPE_FIELDS}
        if reason is None:
            a, b = before.node_access, after.node_access
            denominator = float(origins @ a)
            loss = float(np.clip((origins @ np.maximum(a - b, 0)) / denominator, 0, 1)) if denominator > 0 else None
            fields.update(access_shortfall=loss,
                newly_unserved_population_share=float(origins[(a > 0) & (b == 0)].sum()),
                population_mean=float(origins @ b), population_mean_change=float(origins @ (b - a)),
                equal_node_mean=float(b.mean()), equal_node_mean_change=float((b - a).mean()))
        for field, value in fields.items():
            key = f'{category}_{field}'
            values[key] = value
            if value is None:
                reasons[key] = reason or 'zero baseline population access; shortfall undefined'
        losses[category] = fields['access_shortfall']
    enabled = [category for category in SERVICE_TYPES if getattr(config, category).importance > 0]
    if all(losses[category] is not None for category in enabled):
        scale = max(getattr(config, category).importance for category in enabled)
        weights = np.array([getattr(config, category).importance / scale for category in enabled])
        values[COMBINED] = float(weights @ [losses[c] for c in enabled] / weights.sum())
    else:
        values[COMBINED] = None
        reasons[COMBINED] = 'undefined loss baseline for positively weighted category: ' + ', '.join(
            category for category in enabled if losses[category] is None)
    return values, reasons


def compute_service_criticality(local, prepared, population, config, routing, *, baseline=None,
                                n_jobs=1, budget_bytes=2**26):
    """Use exactly the candidates already used for paired population consequences."""
    baseline = baseline or compute_sfca(prepared, population, config, routing, n_jobs=n_jobs, budget_bytes=budget_bytes)
    nodes, links = {}, {}
    for kind, features in (('nodes', list(local.nodes.items())),
            ('links', [(row['link_id'], row) for row in local.links])):
        target = nodes if kind == 'nodes' else links
        for identifier, row in features:
            if not row['evaluated']:
                reason = 'self-loop excluded' if row.get('is_self_loop') else 'not evaluated in screened coverage'
                values = dict.fromkeys((*CONSEQUENCE_FIELDS, COMBINED))
                reasons = dict.fromkeys(values, reason)
            else:
                kwargs = {'isolated_nodes': (local.baseline.topology.index[identifier],)} if kind == 'nodes' else {'removed_links': (identifier,)}
                damaged = compute_sfca(prepared, population, config, routing, n_jobs=n_jobs, budget_bytes=budget_bytes, **kwargs)
                values, reasons = access_consequences(baseline, damaged, population, config)
            target[identifier] = {**values, 'service_evaluated': bool(row['evaluated']), 'service_null_reasons': reasons}
            row.update(target[identifier])
    rankings = {}
    for scope, rows in (('nodes', nodes), ('links', links)):
        rankings[scope] = {}
        for category, field in [(c, f'{c}_access_shortfall') for c in SERVICE_TYPES] + [('combined', COMBINED)]:
            ordered = sorted((identifier for identifier, row in rows.items() if row[field] is not None),
                key=lambda identifier: (-rows[identifier][field], node_id_key(identifier), str(identifier)))
            uid = {r['link_id']: r['link_uid'] for r in local.links} if scope == 'links' else {}
            rankings[scope][category] = [{'id': uid.get(identifier, str(identifier)),
                'access_shortfall': rows[identifier][field]} for identifier in ordered]
    return ServiceCriticality(nodes, links, {'coverage': local.coverage, 'rankings': rankings,
        'primary_measure': 'population access shortfall sum(P*max(A_baseline-A_damaged,0))/sum(P*A_baseline)',
        'raw_changes': 'signed damaged-minus-baseline equal-node and population means in category supply units per resident',
        'node_closure': 'isolate node, disable attached supply and origin access; original population retained',
        'link_closure': 'remove physical-link arcs; co-located supply and demand remain',
        'screening_limitation': 'screened candidates may omit the globally most critical access closure'})
