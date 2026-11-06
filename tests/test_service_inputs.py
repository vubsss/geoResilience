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
