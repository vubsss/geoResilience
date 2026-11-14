"""Known-answer road cross sections and explicitly uncertain OSM metadata."""
import csv
import json

import networkx as nx
import pytest

from georesilience.config import TrafficConfig
from georesilience.traffic import _road_capacities, canonical_traffic_graph, prepare_traffic, write_traffic_csv
from georesilience.traffic_capacity import tag_number


def infer(data, reverse=None):
    tags = dict(data)
    if reverse is not None:
        tags['reversed'] = reverse
    values, attrs, counts = _road_capacities([(10, 2, 0, tags)], TrafficConfig())
    return values[10, 2, 0], attrs[10, 2, 0], counts


def test_asymmetric_lanes_follow_way_orientation_not_node_ids():
    tags = {'lanes': '5', 'lanes:forward': '3', 'lanes:backward': '2', 'oneway': False}
    assert infer(tags, False)[0] == 3000
    assert infer(tags, True)[0] == 2000


def test_shared_centre_lane_is_not_counted_in_both_directions():
    tags = {'lanes': 3, 'lanes:forward': 1, 'lanes:backward': 1, 'lanes:both_ways': 1, 'oneway': False}
    assert infer(tags, False)[0] == infer(tags, True)[0] == 1000
    tags.pop('lanes:forward'); tags.pop('lanes:backward')
    assert infer(tags, False)[0] == infer(tags, True)[0] == 1000


def test_shared_only_road_requires_explicit_capacity_instead_of_double_counting():
    with pytest.raises(ValueError, match='shared-only road'):
        infer({'lanes': 1, 'lanes:both_ways': 1, 'oneway': False}, False)


def test_other_direction_can_be_derived_with_explicit_total():
    tags = {'lanes': 4, 'lanes:forward': 3, 'oneway': False}
    cap, attrs, _ = infer(tags, True)
    assert cap == 1000
    assert attrs['capacity_rule'] == 'opposite_lanes_remainder'


@pytest.mark.parametrize('reverse', [None, [True, False], 'unknown'])
def test_direction_ambiguity_does_not_assign_forward_lanes_to_both_arcs(reverse):
    cap, attrs, _ = infer({'lanes': 5, 'lanes:forward': 3, 'lanes:backward': 2, 'oneway': False}, reverse)
    assert cap == 1000
    assert attrs['capacity_source'] == 'default_lanes'
    assert 'no_direction_guess' in attrs['capacity_assumptions']


@pytest.mark.parametrize('oneway', [True, 'yes', '-1'])
def test_oneway_total_lanes_are_not_halved(oneway):
    assert infer({'lanes': 3, 'oneway': oneway})[0] == 3000


def test_oneway_with_missing_total_can_use_a_single_directional_count():
    assert infer({'lanes:backward': 2, 'oneway': True})[0] == 2000
    cap, attrs, _ = infer({'lanes:forward': 2, 'lanes:backward': 1, 'oneway': True})
    assert cap == 1000 and 'inconsistent_lane_tags' in attrs['capacity_assumptions']


def test_inconsistent_counts_fall_back_explicitly():
    cap, attrs, _ = infer({'lanes': 2, 'lanes:forward': 2, 'lanes:backward': 2, 'oneway': False}, False)
    assert cap == 1000
    assert attrs['capacity_source'] == 'default_lanes'
    assert 'inconsistent_lane_tags' in attrs['capacity_assumptions']


def test_explicit_zero_directional_lanes_does_not_create_phantom_capacity():
    with pytest.raises(ValueError, match='explicitly zero directional lanes'):
        infer({'lanes': 2, 'lanes:forward': 0, 'lanes:backward': 2, 'oneway': False}, False)


@pytest.mark.parametrize('value', ['2;3', '2|3', '2-3', 'two', '2.5', '-2', '2 lanes', '0'])
def test_ambiguous_total_lane_values_are_not_silently_parsed(value):
    cap, attrs, counts = infer({'lanes': value})
    assert cap == 1000 and counts['invalid_tag_arcs'] == 1
    assert json.loads(attrs['capacity_invalid_fields']) == ['lanes']


@pytest.mark.parametrize('value,expected', [('7 m', 7), ('700 cm', 7), ('7000 mm', 7),
    ('20 ft', 6.096), ("16'3\"", 4.953), ('0.007 km', 7)])
def test_width_units_are_fully_converted(value, expected):
    assert tag_number(value, width=True) == pytest.approx(expected)


def test_directional_width_is_not_halved_again():
    tags = {'width': 10.5, 'width:forward': 7, 'width:backward': 3.5, 'oneway': False}
    assert infer(tags, False)[0] == 2000
    assert infer(tags, True)[0] == 1000
    assert infer({'maxwidth': 7}, False)[0] == 1000  # vehicle clearance is not carriageway width
    assert infer({'width:backward': 7, 'oneway': True})[0] == 2000
    assert infer({'width': 7, 'width:forward': 3.5, 'oneway': True})[0] == 1000


def test_conflicting_width_descriptions_are_not_cherry_picked():
    cap, attrs, _ = infer({'width': 7, 'width:carriageway': 14})
    assert cap == 1000 and attrs['capacity_source'] == 'default_lanes'
    assert 'conflicting_total_width_tags' in attrs['capacity_assumptions']


def test_lane_list_with_invalid_member_does_not_hide_missing_information():
    cap, attrs, counts = infer({'lanes': ['2', 'unknown']})
    assert cap == 1000 and counts['invalid_tag_arcs'] == 1
    assert attrs['capacity_source'] == 'default_lanes'


def test_mixed_width_units_and_lane_lists_remain_order_independent():
    graph = nx.MultiDiGraph()
    graph.add_edge(0, 1, lanes=['2', '3'], width=['7 m', '20 ft'], oneway=False)
    fixed, _ = canonical_traffic_graph(graph)
    a = _road_capacities(list(fixed.edges(keys=True, data=True)), TrafficConfig())
    assert a[0][0, 1, 0] == 1000
    assert json.loads(a[1][0, 1, 0]['capacity_raw_tags'])['width'] == ['7 m', '20 ft']
    graph[0][1][0]['lanes'].reverse()
    again, _ = canonical_traffic_graph(graph)
    assert _road_capacities(list(again.edges(keys=True, data=True)), TrafficConfig())[0] == a[0]
    assert graph[0][1][0]['width'] == ['7 m', '20 ft']


def test_pipeline_traffic_exports_capacity_provenance(tmp_path):
    graph = nx.MultiDiGraph()
    graph.add_edge(0, 1, key=0, lanes=3, **{'lanes:forward': 2, 'lanes:backward': 1}, oneway=False, reversed=False)
    graph.add_edge(1, 0, key=0, lanes=3, **{'lanes:forward': 2, 'lanes:backward': 1}, oneway=False, reversed=True)
    od = tmp_path/'od.csv'
    od.write_text('origin,destination,demand_pcu_h\n0,1,100\n', encoding='utf-8')
    result = prepare_traffic(graph, TrafficConfig(enabled=True, od_csv=od), {(0, 1, 0): 60, (1, 0, 0): 60})
    assert result.summary['capacity_audit']['by_rule'] == {'explicit_directional_lanes': 2}
    assert result.capacities == {(0, 1, 0): 2000, (1, 0, 0): 1000}
    target = tmp_path/'arcs.csv'; write_traffic_csv(result, target)
    with target.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]['capacity_rule'] == 'explicit_directional_lanes'
    assert json.loads(rows[0]['capacity_raw_tags'])['lanes:forward'] == 2
    assert result.summary['capacity_audit']['fallback_arc_pct'] == 0


def test_osm_xml_import_preserves_directional_lane_tags(tmp_path):
    from georesilience.config import RunConfig
    from georesilience.network import load_and_clean
    source = tmp_path/'roads.osm'
    source.write_text('''<osm version="0.6">
      <node id="1" lat="17.0" lon="78.5"/><node id="2" lat="17.001" lon="78.5"/>
      <way id="11"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/>
        <tag k="lanes" v="3"/><tag k="lanes:forward" v="2"/><tag k="lanes:backward" v="1"/>
      </way></osm>''', encoding='utf-8')
    graph, _, _ = load_and_clean(RunConfig(input={'source': 'osm_xml', 'path': source}, cleaning={'consolidate': False}))
    fixed, _ = canonical_traffic_graph(graph)
    capacities, attrs, _ = _road_capacities(list(fixed.edges(keys=True, data=True)), TrafficConfig())
    assert sorted(capacities.values()) == [1000, 2000]
    assert {r['capacity_rule'] for r in attrs.values()} == {'explicit_directional_lanes'}
