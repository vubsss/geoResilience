"""Auditable OSM-to-capacity assumptions, in PCU/hour per directed arc.

Tags describe road geometry, not measured traffic capacity. Directional suffixes
refer to OSM way order, never compass bearings or numerical node-ID order.
"""
import json
import math
import re
from collections import Counter

MODEL_VERSION = 'road-capacity-v2'
CAPACITY_TAGS = ('lanes', 'lanes:forward', 'lanes:backward', 'lanes:both_ways',
                 'width', 'width:carriageway', 'width:forward', 'width:backward',
                 'oneway', 'reversed')
AUDIT_FIELDS = ('capacity_rule', 'capacity_direction', 'capacity_assumptions',
                'capacity_invalid_fields', 'capacity_raw_tags', 'capacity_model_version')


def _items(value):
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


def _present(value):
    return value is not None and str(value).strip() != ''


def tag_number(value, *, width=False, zero=False):
    """Parse complete values; a simplified segment list uses its bottleneck.

    Do not interpret '2;3', '2-3', lane-wise pipes or prose as a single count.
    Width supports metres, cm, mm, km, feet, inches and feet/inches notation.
    A list containing an invalid entry is unavailable rather than cherry-picked.
    """
    result = []
    for item in _items(value):
        if item is None or isinstance(item, bool):
            return None
        text = str(item).strip().lower()
        feet = re.fullmatch(r'(\d+(?:\.\d+)?)\s*\'\s*(?:(\d+(?:\.\d+)?)\s*\")?', text)
        if width and feet:
            inches = float(feet[2] or 0)
            if inches >= 12:
                return None
            number = float(feet[1]) * .3048 + inches * .0254
        else:
            match = re.fullmatch(r'(\d+(?:\.\d+)?)(?:\s*(m|metres?|meters?|cm|mm|km|ft|feet|foot|in|inches?|\"))?', text)
            if match is None or (match[2] and not width):
                return None
            scale = {'cm': .01, 'mm': .001, 'km': 1000, 'ft': .3048,
                     'feet': .3048, 'foot': .3048, 'in': .0254,
                     'inch': .0254, 'inches': .0254, '"': .0254}.get(match[2], 1)
            number = float(match[1]) * scale
        if not math.isfinite(number) or number < 0 or (not zero and number == 0):
            return None
        if not width and not number.is_integer():
            return None
        result.append(number)
    return min(result) if result else None


def _boolean(value):
    values = []
    for item in _items(value):
        text = str(item).strip().lower()
        if text in ('true', 'yes', '1', '-1', 'reverse'):
            values.append(True)
        elif text in ('false', 'no', '0'):
            values.append(False)
        else:
            return None
    return values[0] if values and len(set(values)) == 1 else None


def _raw_tags(data):
    # canonical_traffic_graph retains pre-resolution values for the audit.
    return data.get('_traffic_capacity_tags', {k: data[k] for k in CAPACITY_TAGS if k in data})


def _resolve(data, config):
    raw = _raw_tags(data)
    flags, invalid = [], []
    numbers = {}
    for key in CAPACITY_TAGS[:-2]:
        value = raw.get(key)
        numbers[key] = tag_number(value, width=key.startswith('width'), zero=key.startswith('lanes:')) if _present(value) else None
        if _present(value) and numbers[key] is None:
            invalid.append(key)
        if isinstance(value, (list, tuple, set)) and len(set(map(str, value))) > 1:
            flags.append('mixed_segments_bottleneck_' + key)
    total, forward, backward, shared = (numbers[k] for k in ('lanes', 'lanes:forward', 'lanes:backward', 'lanes:both_ways'))
    shared_value = shared or 0
    oneway = _boolean(raw.get('oneway'))
    if oneway is None:
        flags.append('oneway_missing_or_ambiguous_assumed_two_way')
    is_oneway = oneway is True
    reverse = _boolean(raw.get('reversed'))
    direction = 'oneway' if is_oneway else ('backward' if reverse else 'forward') if reverse is not None else 'unknown'
    f, b = (backward, forward) if reverse else (forward, backward)
    directional_present = any(_present(raw.get(k)) for k in ('lanes:forward', 'lanes:backward'))
    lane_conflict = bool((_present(raw.get('lanes:both_ways')) and shared is None)
                         or (shared is not None and total is not None and shared > total))
    if not is_oneway and total is not None:
        if forward is not None and backward is not None:
            lane_conflict |= not math.isclose(forward + backward + shared_value, total)
        else:
            lane_conflict |= any(v is not None and v + shared_value >= total for v in (forward, backward))
    if is_oneway:
        lane_conflict |= shared_value > 0 or (forward is not None and backward is not None and forward > 0 and backward > 0)
        lane_conflict |= any(v is not None and v > 0 and total is not None and v != total for v in (forward, backward))
    if lane_conflict:
        flags.append('inconsistent_lane_tags_not_used')
    if not is_oneway and total is not None and total == shared_value and total > 0 and not lane_conflict:
        raise ValueError('traffic: shared-only road needs a capacity override; independent directional through capacity is unresolved')
    if not is_oneway and reverse is not None and f == 0 and not lane_conflict:
        raise ValueError('traffic: retained arc has explicitly zero directional lanes; correct access/direction or supply a capacity override')
    lanes, rule, source = None, None, None
    if not lane_conflict:
        if is_oneway and total is not None:
            lanes, rule = total, 'oneway_total_lanes'
        elif is_oneway and directional_present:
            positive = [v for v in (forward, backward) if v is not None and v > 0]
            if len(positive) == 1:
                lanes, rule = positive[0], 'oneway_single_directional_count'
                flags.append('single_directional_count_assumed_along_oneway')
        elif directional_present:
            if reverse is not None and f is not None and f > 0:
                lanes, rule = f, 'explicit_directional_lanes'
            elif reverse is not None and total is not None and b is not None and total - b - shared_value > 0:
                lanes, rule = total - b - shared_value, 'opposite_lanes_remainder'
                if shared is None:
                    flags.append('unreported_shared_lanes_assumed_zero')
            elif reverse is None and forward is not None and forward == backward and forward > 0:
                lanes, rule = forward, 'equal_explicit_directional_lanes'
            else:
                flags.append('directional_lanes_unresolved_no_direction_guess')
        elif total is not None and total > shared_value:
            lanes, rule = (total - shared_value) / 2, 'total_lanes_equal_split'
            flags.append('equal_directional_split_assumed')
            if total == 1:
                flags.append('shared_single_lane_conflicts_not_modelled')
        if lanes is not None:
            source = 'lanes_tag'
    if shared_value:
        flags.append('shared_centre_lanes_not_independent_through_capacity')
    width = numbers['width:carriageway'] if numbers['width:carriageway'] is not None else numbers['width']
    if numbers['width:carriageway'] is not None and numbers['width'] is not None and not math.isclose(numbers['width:carriageway'], numbers['width']):
        width = None
        flags.append('conflicting_total_width_tags_not_used')
    wf, wb = numbers['width:forward'], numbers['width:backward']
    directional_width = wb if reverse else wf
    width_directional_present = any(_present(raw.get(k)) for k in ('width:forward', 'width:backward'))
    if lanes is None:
        usable_width = None
        if is_oneway and width_directional_present:
            positive = [v for v in (wf, wb) if v is not None and v > 0]
            if len(positive) == 1 and (width is None or positive[0] <= width):
                usable_width, rule = positive[0], 'oneway_single_directional_width'
                flags.append('single_directional_width_assumed_along_oneway')
            else:
                flags.append('inconsistent_oneway_directional_width_not_used')
        elif not is_oneway and width_directional_present:
            if reverse is not None and directional_width is not None:
                usable_width, rule = directional_width, 'explicit_directional_width'
            elif reverse is None and wf is not None and wf == wb:
                usable_width, rule = wf, 'equal_explicit_directional_width'
            else:
                flags.append('directional_width_unresolved_no_direction_guess')
            if usable_width is not None and width is not None and (usable_width > width or (wf is not None and wb is not None and wf + wb > width + 1e-9)):
                usable_width = None
                flags.append('inconsistent_directional_width_not_used')
        elif width is not None:
            usable_width = width if is_oneway else (width - shared_value * config.lane_width_m) / 2
            rule = 'oneway_width' if is_oneway else 'total_width_equal_split'
            if not is_oneway:
                flags.append('equal_directional_width_split_assumed')
            if shared_value:
                flags.append('shared_centre_width_assumed_from_lane_width')
        if usable_width is not None and usable_width > 0:
            lanes, source = usable_width / config.lane_width_m, 'width_inferred_lanes'
            flags.append('kerb_width_assumed_usable_includes_possible_parking_or_cycle_space')
        else:
            lanes, source, rule = config.default_lanes_per_direction, 'default_lanes', 'configured_default_per_direction'
            flags.append('default_directional_lanes_assumed')
    flags.append('per_lane_pcu_capacity_is_configured_assumption')
    if not math.isfinite(lanes) or lanes <= 0:
        raise ValueError('traffic: no finite positive directional capacity')
    serial = {k: sorted(map(str, v)) if isinstance(v, set) else v for k, v in raw.items()}
    return {'width_m': width, 'lanes_tag': total, 'effective_lanes': lanes, 'capacity_source': source,
            'capacity_rule': rule, 'capacity_direction': direction,
            'capacity_assumptions': json.dumps(sorted(set(flags))),
            'capacity_invalid_fields': json.dumps(invalid),
            'capacity_raw_tags': json.dumps(serial, sort_keys=True, default=str),
            'capacity_model_version': MODEL_VERSION}


def infer_capacities(arcs, config):
    capacities, attributes = {}, {}
    counts = dict(lanes_tagged=0, width_tagged=0, fallback=0, invalid_tag_arcs=0)
    for u, v, key, data in arcs:
        row = _resolve(data, config)
        edge = u, v, key
        capacity = row['effective_lanes'] * config.road_capacity_pcu_h_per_lane
        if not math.isfinite(capacity) or capacity <= 0:
            raise ValueError(f'traffic: invalid capacity for {edge}')
        capacities[edge], attributes[edge] = capacity, row
        counts[{'lanes_tag': 'lanes_tagged', 'width_inferred_lanes': 'width_tagged', 'default_lanes': 'fallback'}[row['capacity_source']]] += 1
        counts['invalid_tag_arcs'] += bool(json.loads(row['capacity_invalid_fields']))
    return capacities, attributes, counts


def capacity_audit(attributes):
    rows = list(attributes.values())
    sources = Counter(row['capacity_source'] for row in rows)
    return {'model_version': MODEL_VERSION, 'directed_arcs': len(rows),
            'by_source': dict(sources), 'by_rule': dict(Counter(row['capacity_rule'] for row in rows)),
            'fallback_arc_pct': 100 * sources['default_lanes'] / len(rows) if rows else None,
            'assumption_arc_counts': dict(Counter(flag for row in rows for flag in json.loads(row['capacity_assumptions']))),
            'invalid_field_arc_counts': dict(Counter(flag for row in rows for flag in json.loads(row['capacity_invalid_fields']))),
            'interpretation': 'All capacities are estimates using configured PCU/hour/lane; OSM tags do not measure capacity. CSV overrides have their own external provenance.'}
