"""Offline facility contract and preparation checks using synthetic records."""

import csv

import pytest
from pydantic import ValidationError

from georesilience.config import RunConfig, ServicesConfig
from georesilience.service_inputs import load_facility_records

FIELDS = ['facility_id', 'service_type', 'longitude', 'latitude', 'capacity', 'capacity_unit', 'capacity_source']


def facility_csv(tmp_path, rows=None, fields=FIELDS):
    path = tmp_path / 'facilities.csv'
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows if rows is not None else [school()])
    return path


def school(**changes):
    return {**dict(zip(FIELDS, ['001', 'school', '78.47', '17.4', '200', 'student_seats', 'school register'])), **changes}


def sfca_config(path, **changes):
    return ServicesConfig.model_validate({'facilities_csv': path, 'mode': 'sfca',
        'school': {'catchment_minutes': 10}, 'hospital': {'catchment_minutes': 20}, **changes})


def test_records_json_leading_zeros_provenance_and_independent_units(tmp_path):
    path = facility_csv(tmp_path, [school(), school(facility_id='002', service_type='hospital',
        capacity='0', capacity_unit='staffed_beds', capacity_source='hospital registry')])
    config = sfca_config(path)
    records = load_facility_records(config)
    assert [r.facility_id for r in records] == ['001', '002']
    assert records[1].capacity == 0
    assert records[1].capacity_source == 'hospital registry'
    assert config.school.catchment_seconds == 600
    assert ServicesConfig.model_validate_json(config.model_dump_json()) == config
    run = RunConfig(input={'path': 'roads.graphml'}, services=config)
    assert RunConfig.model_validate_json(run.model_dump_json()) == run


def test_location_only_weights_and_unknown_capacity(tmp_path):
    path = facility_csv(tmp_path, [{key: school()[key] for key in FIELDS[:4]}], fields=FIELDS[:4])
    records = load_facility_records(ServicesConfig(facilities_csv=path))
    assert records[0].capacity is None
    assert records[0].capacity_unit is None
    assert records[0].capacity_source is None


@pytest.mark.parametrize('field,value,match', [
    ('facility_id', '', 'facility_id'), ('service_type', 'clinic', 'service_type'),
    ('longitude', 'nan', 'coordinates'), ('latitude', 'inf', 'coordinates'),
    ('longitude', '181', 'coordinates'), ('latitude', '-91', 'coordinates'),
    ('longitude', 'garbage', 'coordinates'),
    *[('capacity', value, 'capacity') for value in ['-1', 'nan', 'NaN', 'inf', '-inf', 'bad', '']],
    ('capacity_unit', '', 'capacity_unit'), ('capacity_source', ' ', 'capacity_source'),
])
def test_row_errors_are_actionable(tmp_path, field, value, match):
    path = facility_csv(tmp_path, [school(**{field: value})])
    with pytest.raises(ValueError, match=match) as error:
        load_facility_records(sfca_config(path))
    assert 'row 2' in str(error.value)


def test_duplicate_ids_and_incompatible_units(tmp_path):
    path = facility_csv(tmp_path, [school(), school()])
    with pytest.raises(ValueError, match='unique'):
        load_facility_records(sfca_config(path))
    path = facility_csv(tmp_path, [school(), school(facility_id='002', capacity_unit='teachers')])
    with pytest.raises(ValueError, match='row 3.*incompatible school'):
        load_facility_records(sfca_config(path))
    path = facility_csv(tmp_path)
    with pytest.raises(ValueError, match='incompatible school'):
        load_facility_records(sfca_config(path, school={'catchment_minutes': 10, 'capacity_unit': 'teachers'}))


@pytest.mark.parametrize('content,match', [
    ('', 'headers'), ('facility_id,facility_id\n1,1\n', 'headers'),
    ('facility_id,,latitude\n1,2,3\n', 'headers'),
    ('facility_id,service_type\n1,school\n', 'missing columns'),
    (','.join(FIELDS) + '\n1,school,0,0,1,u,s,EXTRA\n', 'number of fields'),
    (','.join(FIELDS) + '\n1,school,0,0\n', 'number of fields'),
    (','.join(FIELDS) + '\n"unterminated', 'invalid CSV'),
])
def test_bad_headers_and_csv_shapes(tmp_path, content, match):
    path = tmp_path / 'facilities.csv'
    path.write_text(content)
    with pytest.raises(ValueError, match=match):
        load_facility_records(sfca_config(path))


def test_capacity_columns_required_only_for_sfca_and_catchment_only_for_present_type(tmp_path):
    path = facility_csv(tmp_path, [{key: school()[key] for key in FIELDS[:4]}], fields=FIELDS[:4])
    with pytest.raises(ValueError, match='missing columns'):
        load_facility_records(sfca_config(path))
    path = facility_csv(tmp_path)
    assert load_facility_records(sfca_config(path, hospital={}))
    with pytest.raises(ValueError, match='school requires explicit positive catchment'):
        load_facility_records(sfca_config(path, school={}))


@pytest.mark.parametrize('setting', ['importance', 'catchment_minutes', 'snap_max_m'])
@pytest.mark.parametrize('bad', [-1, float('nan'), float('inf'), -float('inf')])
def test_numeric_config_rejects_bad_values(tmp_path, setting, bad):
    data = {'facilities_csv': tmp_path / 'f.csv'}
    data.update({'snap_max_m': bad} if setting == 'snap_max_m' else {'school': {setting: bad}})
    with pytest.raises(ValidationError):
        ServicesConfig.model_validate(data)


def test_zero_settings_and_overflow_policies(tmp_path):
    data = {'facilities_csv': tmp_path / 'f.csv', 'snap_max_m': 0, 'school': {'importance': 0}}
    assert ServicesConfig.model_validate(data).school.importance == 0
    with pytest.raises(ValidationError, match='positive category importance'):
        ServicesConfig.model_validate({**data, 'hospital': {'importance': 0}})
    for value in (0, 1e308):
        with pytest.raises(ValidationError):
            ServicesConfig.model_validate({**data, 'school': {'catchment_minutes': value}})


def test_weights_only_still_rejects_invalid_supplied_capacity(tmp_path):
    path = facility_csv(tmp_path, [school(capacity='nan')])
    with pytest.raises(ValueError, match='capacity'):
        load_facility_records(ServicesConfig(facilities_csv=path))


def metric_graph(nodes):
    import networkx as nx
    graph = nx.MultiDiGraph(crs='EPSG:3857')
    for node, x, y in nodes:
        graph.add_node(node, x=x, y=y)
    return graph


def test_projected_snapping_inclusive_limit_and_just_outside(tmp_path):
    from pyproj import Transformer
    from georesilience.services import prepare_services
    x, y = Transformer.from_crs(4326, 3857, always_xy=True).transform(78.47, 17.4)
    graph = metric_graph([(7, x + 20, y)])
    path = facility_csv(tmp_path)
    result = prepare_services(graph, ServicesConfig(facilities_csv=path, snap_max_m=20))
    f = result.facilities[0]
    assert f.node_id == 7 and f.node_index == 0
    assert f.snap_m == 20 and f.x == x and f.y == y
    assert f.record.longitude == 78.47 and f.record.latitude == 17.4
    with pytest.raises(ValueError, match="'001'.*exceeds inclusive"):
        prepare_services(graph, ServicesConfig(facilities_csv=path, snap_max_m=19.999999))


def test_ties_zero_limit_and_node_order_are_deterministic(tmp_path):
    from georesilience.services import prepare_services
    path = facility_csv(tmp_path, [school(longitude='0', latitude='0')])
    for nodes in ([(10, -1, 0), (2, 1, 0)], [(2, 1, 0), (10, -1, 0)]):
        result = prepare_services(metric_graph(nodes), ServicesConfig(facilities_csv=path, snap_max_m=1))
        assert result.facilities[0].node_id == 2
    graph = metric_graph([(10, 0, 0), (2, 0, 0), ('01', 0, 0), ('1', 0, 0)])
    result = prepare_services(graph, ServicesConfig(facilities_csv=path, snap_max_m=0))
    assert result.facilities[0].node_id == '01'
    assert result.facilities[0].snap_m == 0


def test_colocated_categories_keep_identity_totals_and_provenance(tmp_path):
    import copy
    import numpy as np
    from georesilience.services import prepare_services
    graph = metric_graph([(1, 0, 0), (2, 100, 0)])
    before = copy.deepcopy(graph)
    rows = [school(facility_id='002', longitude='0', latitude='0', capacity='70'),
        school(facility_id='001', longitude='0', latitude='0', capacity='50'),
        school(facility_id='003', longitude='0', latitude='0', service_type='hospital',
            capacity='5', capacity_unit='beds', capacity_source='hospital record')]
    path = facility_csv(tmp_path, rows)
    first = prepare_services(graph, sfca_config(path, snap_max_m=0))
    assert [f.record.facility_id for f in first.facilities] == ['001', '002', '003']
    assert [f.node_id for f in first.facilities] == [1, 1, 1]
    np.testing.assert_array_equal(first.counts['school'], [2, 0])
    np.testing.assert_array_equal(first.capacities['school'], [120, 0])
    np.testing.assert_array_equal(first.capacities['hospital'], [5, 0])
    assert first.summary['categories']['hospital']['capacity_sources'] == ['hospital record']
    assert first.summary['categories']['school']['known_capacity_total'] == 120
    assert first.summary['attached_count'] == 3 and first.summary['excluded_count'] == 0
    path = facility_csv(tmp_path, rows[::-1])
    second = prepare_services(graph, sfca_config(path, snap_max_m=0))
    assert [f.public() for f in first.facilities] == [f.public() for f in second.facilities]
    assert first.summary == second.summary
    assert dict(graph.nodes(data=True)) == dict(before.nodes(data=True))
    assert list(graph.edges(data=True)) == list(before.edges(data=True))


def test_unknown_capacity_not_zero_and_zero_supply_is_counted(tmp_path):
    import numpy as np
    from georesilience.services import prepare_services
    path = facility_csv(tmp_path, [school(longitude='0', latitude='0', capacity=''),
        school(facility_id='002', longitude='0', latitude='0', capacity='0')])
    result = prepare_services(metric_graph([(1, 0, 0)]), ServicesConfig(facilities_csv=path))
    assert np.isnan(result.capacities['school'][0])
    category = result.summary['categories']['school']
    assert category['capacity_total'] is None
    assert category['known_capacity_total'] == 0
    assert category['unknown_capacity_count'] == category['zero_capacity_count'] == 1


@pytest.mark.parametrize('kind', ['geographic', 'feet', 'missing_crs', 'missing_xy', 'nan_xy', 'empty'])
def test_invalid_graph_crs_and_coordinates(tmp_path, kind):
    from georesilience.services import prepare_services
    graph = metric_graph([(1, 0, 0)])
    if kind == 'geographic':
        graph.graph['crs'] = 'EPSG:4326'
    elif kind == 'feet':
        graph.graph['crs'] = 'EPSG:2263'
    elif kind == 'missing_crs':
        del graph.graph['crs']
    elif kind == 'missing_xy':
        del graph.nodes[1]['x']
    elif kind == 'nan_xy':
        graph.nodes[1]['y'] = float('nan')
    else:
        graph.clear()
        graph.graph['crs'] = 'EPSG:3857'
    path = facility_csv(tmp_path)
    with pytest.raises(ValueError, match='requires'):
        prepare_services(graph, ServicesConfig(facilities_csv=path))


def test_attachment_uses_cleaned_retained_consolidated_nodes(tmp_path):
    from pyproj import Transformer
    from georesilience.inputs import directory_config
    from georesilience.network import load_and_clean
    from georesilience.services import prepare_services
    from tests.test_directory_cli import make_input
    directory, _, _, _ = make_input(tmp_path)
    config = directory_config(directory, consolidate=True, consolidation_m=15)
    graph, _, _ = load_and_clean(config)
    node = next(iter(graph))
    lon, lat = Transformer.from_crs(graph.graph['crs'], 4326, always_xy=True).transform(
        graph.nodes[node]['x'], graph.nodes[node]['y'])
    path = facility_csv(tmp_path, [school(longitude=str(lon), latitude=str(lat))])
    result = prepare_services(graph, ServicesConfig(facilities_csv=path, snap_max_m=.001))
    assert result.facilities[0].node_id == node
    assert result.node_ids == tuple(graph)
