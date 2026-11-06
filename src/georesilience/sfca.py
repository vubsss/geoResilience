"""Standard two-step floating catchment accessibility in independent supply units.

Both steps use resident-to-facility directed travel times. Transposed facility
searches permit bounded reductions without storing a resident-by-facility matrix.
"""

from dataclasses import dataclass
import math

import numpy as np

from .service_inputs import SERVICE_TYPES

METHOD_VERSION = 'standard-2sfca-v1'


@dataclass
class CategorySFCA:
    node_access: np.ndarray | None
    facilities: list[dict]
    summary: dict

    @property
    def reason(self):
        return self.summary['reason']


@dataclass
class SFCAResult:
    node_ids: tuple
    categories: dict[str, CategorySFCA]

    @property
    def summary(self):
        return {category: result.summary for category, result in self.categories.items()}


@dataclass
class _CatchmentReducer:
    population: np.ndarray
    isolated_nodes: tuple
    ratios: np.ndarray | None = None

    def __call__(self, distances, sources):
        if self.isolated_nodes:
            distances[:, self.isolated_nodes] = np.inf
            distances[np.isin(sources, self.isolated_nodes)] = np.inf
        reachable = np.isfinite(distances)
        if self.ratios is None:
            return reachable @ self.population
        return np.sum(reachable * self.ratios[sources, None], axis=0)


def compute_sfca(prepared, population, config, routing=None, *, removed_links=(),
                 isolated_nodes=(), n_jobs=1, budget_bytes=2**26):
    """Recompute catchment demand and ratios using original retained population.

    Node closures disable attached supply and that origin's access; link closures
    preserve co-located access. Each output retains individual facility identity.
    """
    population = np.asarray(population, dtype=float)
    n = len(prepared.node_ids)
    if (population.shape != (n,) or not np.isfinite(population).all() or (population < 0).any()
            or not math.isfinite(float(population.sum()))):
        raise ValueError('2SFCA population must match retained nodes and be finite/nonnegative')
    if routing is not None and routing.topology is not None and routing.topology.node_ids != prepared.node_ids:
        raise ValueError('2SFCA time topology must use the original facility node order')
    total = float(population.sum())
    categories = {}
    for category in SERVICE_TYPES:
        facilities = [f for f in prepared.facilities if f.record.service_type == category]
        settings = getattr(config, category)
        unit = prepared.summary['categories'][category]['capacity_unit']
        reason = ('weights-only mode; 2SFCA not requested' if config.mode != 'sfca' else
            'service category not supplied' if not facilities else
            'zero original population; 2SFCA demand is undefined' if total == 0 else
            'static travel times unavailable' if routing is None else routing.reason)
        summary = {'method_version': METHOD_VERSION, 'status': 'unavailable' if reason else 'computed',
            'reason': reason, 'capacity_unit': unit, 'raw_unit': f'{unit} per resident' if unit else None,
            'display_unit': f'{unit} per 1,000 residents' if unit else None,
            'catchment_minutes': settings.catchment_minutes, 'catchment_seconds': settings.catchment_seconds,
            'demand': 'allocated total population; school demand is an all-resident proxy',
            'direction': 'resident-to-facility', 'binary_catchment': True, 'inclusive_threshold': True,
            'equal_node_mean': None, 'population_mean': None, 'equal_node_mean_per_1000': None,
            'population_mean_per_1000': None, 'zero_access_population_share': None,
            'positive_demand_capacity': None, 'zero_demand_capacity': None, 'disabled_capacity': None,
            'facility_count': len(facilities)}
        rows = [{**f.public(), 'available_capacity': None, 'catchment_demand': None,
                 'supply_demand_ratio': None, 'ratio_reason': reason} for f in facilities]
        if reason:
            categories[category] = CategorySFCA(None, rows, summary)
            continue
        if settings.catchment_seconds is None:
            raise ValueError(f'{category}: enabled 2SFCA requires explicit catchment minutes')
        if any(f.record.capacity is None or not f.record.capacity_unit or not f.record.capacity_source for f in facilities):
            raise ValueError(f'{category}: enabled 2SFCA requires capacity, unit and source for every facility')
        if budget_bytes < max(1, n) * 8 * 16:
            raise ValueError('memory budget too small for two-pass 2SFCA workspace')
        query_options = dict(cutoff_seconds=settings.catchment_seconds, transpose=True,
            removed_links=removed_links, isolated_nodes=isolated_nodes,
            n_jobs=n_jobs, budget_bytes=budget_bytes // 2)
        sources = np.array(sorted({f.node_index for f in facilities}), dtype=int)
        demands, ratios = np.zeros(n), np.zeros(n)
        for nodes, values in routing.topology.reduce(sources, _CatchmentReducer(population, tuple(isolated_nodes)), **query_options):
            demands[nodes] = values
        positive_demand_capacity, zero_demand_capacity, disabled_capacity = 0., 0., 0.
        for facility, row in zip(facilities, rows):
            i, supply = facility.node_index, facility.record.capacity
            disabled = i in isolated_nodes
            demand = float(demands[i])
            available = 0. if disabled else supply
            ratio = available / demand if demand > 0 else None
            if ratio is not None and not math.isfinite(ratio):
                raise ValueError(f'{category}: supply/demand ratio exceeds finite numeric range')
            row.update(available_capacity=available, catchment_demand=demand, supply_demand_ratio=ratio,
                ratio_reason='facility disabled by node closure' if disabled else
                    'zero catchment demand; capacity contributes zero access' if demand == 0 else None)
            if disabled:
                disabled_capacity += supply
            elif demand == 0:
                zero_demand_capacity += supply
            else:
                positive_demand_capacity += supply
            if ratio is not None:
                ratios[i] += ratio
        access = np.zeros(n)
        for _, values in routing.topology.reduce(sources,
                _CatchmentReducer(population, tuple(isolated_nodes), ratios), **query_options):
            access += values
        if not np.isfinite(access).all() or not np.isfinite(access * 1000).all():
            raise ValueError(f'{category}: 2SFCA index exceeds finite numeric range')
        equal_mean, pop_mean = float(access.mean()), float((population / total) @ access)
        summary.update(equal_node_mean=equal_mean, population_mean=pop_mean,
            equal_node_mean_per_1000=1000 * equal_mean, population_mean_per_1000=1000 * pop_mean,
            zero_access_population_share=float(population[access == 0].sum() / total),
            positive_demand_capacity=positive_demand_capacity, zero_demand_capacity=zero_demand_capacity,
            disabled_capacity=disabled_capacity)
        categories[category] = CategorySFCA(access, rows, summary)
    return SFCAResult(prepared.node_ids, categories)
