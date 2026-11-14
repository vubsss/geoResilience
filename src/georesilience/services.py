"""Facility attachment and category accounting on the original retained graph."""

from dataclasses import asdict, dataclass
import math

import numpy as np
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError
from scipy.spatial import cKDTree

from .od import node_id_key
from .service_inputs import FacilityRecord, SERVICE_TYPES, load_facility_records


@dataclass(frozen=True)
class AttachedFacility:
    record: FacilityRecord
    node_id: object
    node_index: int
    snap_m: float
    x: float
    y: float

    def public(self):
        return {**asdict(self.record), 'node_id': str(self.node_id),
            'node_index': self.node_index, 'snap_m': self.snap_m,
            'projected_x': self.x, 'projected_y': self.y}


@dataclass
class PreparedServices:
    node_ids: tuple
    facilities: list[AttachedFacility]
    counts: dict[str, np.ndarray]
    capacities: dict[str, np.ndarray]
    unknown_counts: dict[str, np.ndarray]
    summary: dict


def prepare_services(graph, config):
    """Attach after cleaning; never mutate graph/population or merge facilities.

    Capacities at nodes containing unknown supply are NaN in the internal array;
    category summaries carry both known subtotals and explicit unknown coverage.
    """
    records = load_facility_records(config)
    try:
        crs = CRS.from_user_input(graph.graph.get('crs'))
    except (ValueError, TypeError, CRSError) as exc:
        raise ValueError('facility snapping requires a projected graph CRS with metre units') from exc
    if not crs.is_projected or len(crs.axis_info) < 2 or any(
            not math.isclose(axis.unit_conversion_factor, 1) for axis in crs.axis_info[:2]):
        raise ValueError('facility snapping requires a projected graph CRS with metre units')
    node_ids = tuple(graph)
    if not node_ids:
        raise ValueError('facility snapping requires a nonempty retained graph')
    try:
        coordinates = np.asarray([[graph.nodes[node]['x'], graph.nodes[node]['y']] for node in node_ids], dtype=float)
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError('facility snapping requires finite node x/y coordinates') from exc
    if not np.isfinite(coordinates).all():
        raise ValueError('facility snapping requires finite node x/y coordinates')
    tree = cKDTree(coordinates)
    transform = Transformer.from_crs(4326, crs, always_xy=True)
    facilities, errors = [], []
    for record in records:
        point = np.asarray(transform.transform(record.longitude, record.latitude))
        if not np.isfinite(point).all():
            errors.append(f'facility {record.facility_id!r}: point cannot be projected into graph CRS')
            continue
        distance, _ = tree.query(point)
        nearby = tree.query_ball_point(point, distance + max(1e-8, distance * 1e-12))
        tied = [(i, float(np.linalg.norm(coordinates[i] - point))) for i in nearby]
        tied = [(i, d) for i, d in tied if math.isclose(d, distance, rel_tol=1e-12, abs_tol=1e-8)
                and d <= config.snap_max_m]
        if not tied:
            errors.append(f'facility {record.facility_id!r}: nearest retained node is {distance:.12g} m away; '
                          f'exceeds inclusive facility snap limit {config.snap_max_m:g} m')
            continue
        index, actual = min(tied, key=lambda pair: (node_id_key(node_ids[pair[0]]), str(node_ids[pair[0]])))
        facilities.append(AttachedFacility(record, node_ids[index], index, actual, float(point[0]), float(point[1])))
    if errors:
        raise ValueError('facility attachment failed:\n' + '\n'.join(errors))
    counts, capacities, unknown_counts, categories = {}, {}, {}, {}
    for category in SERVICE_TYPES:
        counts[category] = np.zeros(len(node_ids), dtype=np.int64)
        capacities[category] = np.zeros(len(node_ids), dtype=float)
        unknown_counts[category] = np.zeros(len(node_ids), dtype=np.int64)
        rows = [f for f in facilities if f.record.service_type == category]
        known = [f.record.capacity for f in rows if f.record.capacity is not None]
        for facility in rows:
            i = facility.node_index
            counts[category][i] += 1
            if facility.record.capacity is None:
                unknown_counts[category][i] += 1
            else:
                capacities[category][i] += facility.record.capacity
        try:
            known_total = math.fsum(known)
        except OverflowError as exc:
            raise ValueError(f'{category}: total capacity exceeds finite numeric range') from exc
        if not math.isfinite(known_total) or not np.isfinite(capacities[category]).all():
            raise ValueError(f'{category}: total capacity exceeds finite numeric range')
        capacities[category][unknown_counts[category] > 0] = np.nan
        unknown = len(rows) - len(known)
        categories[category] = {'facility_count': len(rows), 'attached_node_count': int(np.count_nonzero(counts[category])),
            'known_capacity_count': len(known), 'unknown_capacity_count': unknown,
            'zero_capacity_count': sum(value == 0 for value in known),
            'positive_capacity_count': sum(value > 0 for value in known),
            'known_capacity_total': known_total, 'capacity_total': None if unknown else known_total,
            'capacity_unit': next((f.record.capacity_unit for f in rows if f.record.capacity_unit), None),
            'capacity_sources': sorted({f.record.capacity_source for f in rows if f.record.capacity_source}),
            'capacity_years': sorted({f.record.capacity_year for f in rows if f.record.capacity_year})}
    return PreparedServices(node_ids, facilities, counts, capacities, unknown_counts,
        {'input_count': len(records), 'attached_count': len(facilities), 'excluded_count': 0,
         'snap_max_m': config.snap_max_m, 'maximum_snap_m': max((f.snap_m for f in facilities), default=0),
         'graph_crs': crs.to_string(), 'categories': categories})


def service_node_weights(prepared, config):
    """Institution count importance, independent of capacity units or missingness."""
    with np.errstate(over='ignore'):
        weights = sum(getattr(config, category).importance * prepared.counts[category].astype(float)
                      for category in SERVICE_TYPES)
    if not np.isfinite(weights).all() or not math.isfinite(float(weights.sum())):
        raise ValueError('total service importance must be finite')
    return weights


def service_node_fields(prepared, weights):
    """Public category fields; unknown aggregate capacity is null, never zero."""
    result = {}
    for i, node in enumerate(prepared.node_ids):
        row = {'service_weight': float(weights[i])}
        for category in SERVICE_TYPES:
            value = prepared.capacities[category][i]
            row.update({f'{category}_count': int(prepared.counts[category][i]),
                f'{category}_capacity': float(value) if np.isfinite(value) else None,
                f'{category}_unknown_capacity_count': int(prepared.unknown_counts[category][i])})
        result[node] = row
    return result


def combined_node_importance(population, service_weights, population_importance=1):
    """Add normalized resident mass and service points, keeping both visible.

    I_i = alpha_P * P_i/sum(P) + w_i/sum(w). Uniform fallback is supplied as
    P_i=1, never substituted for a supplied all-zero population dataset.
    """
    from .service_metrics import ServiceUniverse
    universe = ServiceUniverse(population, service_weights)
    if not math.isfinite(population_importance) or population_importance < 0:
        raise ValueError('population importance must be finite and nonnegative')
    population_component = population_importance * universe.origins
    combined = population_component + universe.destinations
    if not np.isfinite(combined).all() or not math.isfinite(float(combined.sum())):
        raise ValueError('combined node importance must be finite')
    return combined, population_component, universe.destinations.copy()
