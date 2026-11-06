"""Offline service CLI, publication, population refinement and replay acceptance."""

import json

import geopandas as gpd
import numpy as np
import pytest
from pyproj import Transformer

from georesilience.pipeline import replay_manifest
from georesilience.services import combined_node_importance
from tests.test_directory_cli import (CORE_FILES, assert_public_summary, invoke, make_input,
    read_summary, run_args, snapshot_files)
from tests.test_service_inputs import facility_csv, school


def service_input(tmp_path, source='graphml', *, zero_population=False, speeds=True, zero_supply=False):
    directory,road,raster,graph=make_input(tmp_path,source,zero_population=zero_population,speeds=speeds)
    lon,lat=(78.47,17.4) if graph is None else Transformer.from_crs(graph.graph['crs'],4326,always_xy=True).transform(
        graph.nodes[0]['x'],graph.nodes[0]['y'])
    path=facility_csv(tmp_path,[school(longitude=str(lon),latitude=str(lat),capacity='0' if zero_supply else '100'),
        school(facility_id='002',service_type='hospital',longitude=str(lon),latitude=str(lat),
            capacity='0' if zero_supply else '20',capacity_unit='beds',capacity_source='hospital register')])
    return directory,road,raster,path


def service_args(directory,output,path,*,mode='2sfca',figures=False,extra=()):
    args=run_args(directory,output,'--facilities',path,'--service-mode',mode,
        '--service-catchment-minutes','school=10','--service-catchment-minutes','hospital=10',*extra)
    return [arg for arg in args if arg!='--no-figures'] if figures else args


@pytest.mark.parametrize('source',['graphml','osm_xml'])
@pytest.mark.parametrize('uniform',[False,True])
def test_offline_service_schema_gis_report_node_importance_and_replay(tmp_path,source,uniform):
    directory,road,raster,path=service_input(tmp_path,source)
    if uniform:raster.unlink()
    output=tmp_path/'result'
    assert invoke(service_args(directory,output,path,extra=['--population-importance','2']))==0
    assert {p.name for p in output.iterdir()}==CORE_FILES
    summary=read_summary(output)
    assert_public_summary(summary)
    assert summary['schema_version']==2 and summary['services']['schema_version']==1
    assert summary['services']['demand']['basis']==('uniform_node_demand' if uniform else 'population')
    nodes=gpd.read_file(output/'network.gpkg',layer='nodes')
    facilities=gpd.read_file(output/'network.gpkg',layer='facilities')
    edges=gpd.read_file(output/'network.gpkg',layer='edges')
    np.testing.assert_allclose(nodes.importance_population_component,2*nodes.population/nodes.population.sum())
    np.testing.assert_allclose(nodes.importance_service_component,nodes.service_weight/nodes.service_weight.sum())
    np.testing.assert_allclose(nodes.node_importance,nodes.importance_population_component+nodes.importance_service_component)
    assert nodes.node_importance.sum()==pytest.approx(3)
    if uniform:
        np.testing.assert_allclose(nodes.importance_population_component,2/len(nodes))
    assert facilities.facility_id.tolist()==['001','002']
    assert facilities.capacity_source.tolist()==['school register','hospital register']
    assert facilities.crs.to_epsg()==4326
    assert {'node_id','snap_m','catchment_demand','supply_demand_ratio','capacity_unit'}<=set(facilities)
    assert {'school_sfca','hospital_sfca','school_access_shortfall','node_importance'}<=set(nodes)
    assert {'school_access_shortfall','hospital_access_shortfall','service_evaluated'}<=set(edges)
    for category in ('school','hospital'):
        assert summary['services']['sfca'][category]['status']=='computed'
        assert np.dot(nodes.population,nodes[f'{category}_sfca'])==pytest.approx(
            summary['services']['sfca'][category]['positive_demand_capacity'])
    text=(output/'report.txt').read_text()
    for phrase in ('Node importance:','school:','hospital:','Capacity sources:','Standard 2SFCA','access shortfall'):
        assert phrase in text
    if uniform:
        assert 'not resident counts' in text
        assert 'uniform node demand unit' in summary['services']['sfca']['school']['raw_unit']
    manifest=json.loads((output/'run_manifest.json').read_text())
    assert {r['role'] for r in manifest['inputs']}==({'roads','facilities'} if uniform else {'roads','population','facilities'})
    assert len(manifest['services']['facility_mappings'])==2
    assert manifest['services']['node_importance']['population_importance']==2
    replay=tmp_path/'replayed'
    replay_manifest(output/'run_manifest.json',replay)
    assert read_summary(replay)==summary
    assert (output/'attack_curve.csv').read_bytes()==(replay/'attack_curve.csv').read_bytes()
    assert 'node_importance_share' in (output/'attack_curve.csv').read_text().splitlines()[0]
    path.write_text(path.read_text()+'\n')
    with pytest.raises(ValueError,match='checksum'):
        replay_manifest(output/'run_manifest.json',tmp_path/'changed')
    assert not (tmp_path/'changed').exists()


@pytest.mark.parametrize('case',['weights_only','missing_times','zero_population','zero_capacity','missing_category','empty'])
def test_service_missing_and_zero_policies(tmp_path,case):
    directory,_,_,path=service_input(tmp_path,zero_population=case=='zero_population',
        speeds=case!='missing_times',zero_supply=case=='zero_capacity')
    if case=='weights_only':
        rows=[school(capacity='',capacity_unit='',capacity_source='')]
        # Keep coordinates at the existing supplied location.
        import csv
        original=list(csv.DictReader(path.open()))[0]
        facility_csv(tmp_path,[{**original,**{k:rows[0][k] for k in ('capacity','capacity_unit','capacity_source')}}])
    if case=='missing_category':
        path.write_text('\n'.join(path.read_text().splitlines()[:2])+'\n')
    if case=='empty':
        path.write_text(path.read_text().splitlines()[0]+'\n')
    output=tmp_path/'result'
    assert invoke(service_args(directory,output,path,mode='weights-only' if case=='weights_only' else '2sfca'))==0
    summary=read_summary(output)['services']
    school_result=summary['sfca']['school']
    if case=='zero_capacity':
        assert school_result['population_mean']==0
        assert school_result['zero_access_population_share']==1
    elif case in ('weights_only','missing_times','zero_population','empty'):
        assert school_result['population_mean'] is None and school_result['reason']
    if case in ('missing_category','empty'):
        assert 'not supplied' in summary['sfca']['hospital']['reason']
        assert not summary['criticality']['rankings']['nodes']['combined']
    if case=='zero_population':
        assert summary['demand']['basis']=='population'
        nodes=gpd.read_file(output/'network.gpkg',layer='nodes')
        assert nodes.importance_population_component.sum()==0
        assert nodes.importance_service_component.sum()==pytest.approx(1)


def test_figures_and_overwrite_service_to_disabled_preserve_user_files(tmp_path):
    from georesilience.figures import FIGURE_FILENAMES,SERVICE_FIGURE_FILENAMES
    directory,_,_,path=service_input(tmp_path)
    output=tmp_path/'result'
    assert invoke(service_args(directory,output,path,figures=True))==0
    assert {p.name for p in (output/'figures').iterdir()}==set(FIGURE_FILENAMES)|set(SERVICE_FIGURE_FILENAMES)
    (output/'figures'/'my-notes.txt').write_text('keep')
    (output/'personal.txt').write_text('keep')
    assert invoke(run_args(directory,output,'--overwrite'))==0
    assert {p.name for p in (output/'figures').iterdir()}=={'my-notes.txt'}
    assert (output/'personal.txt').read_text()=='keep'
    assert 'services' not in read_summary(output)
    assert 'service_share' not in (output/'attack_curve.csv').read_text().splitlines()[0]
    import pyogrio
    assert set(pyogrio.list_layers(output/'network.gpkg')[:,0])=={'nodes','edges'}


def test_invalid_capacity_and_inflight_changed_input_preserve_existing_bytes(tmp_path,monkeypatch):
    from georesilience import pipeline
    directory,_,_,path=service_input(tmp_path)
    output=tmp_path/'result'
    assert invoke(service_args(directory,output,path))==0
    before=snapshot_files(output)
    original=path.read_text()
    path.write_text(original.replace(',100,',',-1,'))
    assert invoke(service_args(directory,output,path,extra=['--overwrite']))==2
    assert snapshot_files(output)==before
    path.write_text(original)
    old=pipeline.compute_targeted_attack
    def change_input(*args,**kwargs):
        result=old(*args,**kwargs)
        path.write_text(path.read_text()+'\n')
        return result
    monkeypatch.setattr(pipeline,'compute_targeted_attack',change_input)
    assert invoke(service_args(directory,output,path,extra=['--overwrite']))==2
    assert snapshot_files(output)==before
    monkeypatch.setattr(pipeline,'compute_targeted_attack',old)
    monkeypatch.setattr(pipeline,'write_figures',lambda *args: path.write_text(path.read_text()+'\n'))
    assert invoke(service_args(directory,output,path,figures=True,extra=['--overwrite']))==2
    assert snapshot_files(output)==before


def test_service_input_cannot_be_replaced_by_generated_output(tmp_path):
    directory,_,_,path=service_input(tmp_path)
    output=tmp_path/'result';output.mkdir()
    collision=output/'report.txt';collision.write_bytes(path.read_bytes())
    before=snapshot_files(output)
    assert invoke(service_args(directory,output,collision,extra=['--overwrite']))==2
    assert snapshot_files(output)==before


@pytest.mark.parametrize('bad',['-1','nan','inf'])
def test_population_importance_cli_rejects_bad_values(tmp_path,bad):
    directory,_,_,path=service_input(tmp_path)
    output=tmp_path/'result'
    assert invoke(service_args(directory,output,path,extra=['--population-importance',bad]))==2
    assert not output.exists()


def test_population_adds_independently_of_service_points_and_unit_scaling():
    combined,pop,services=combined_node_importance([90,10,0],[0,1,1],2)
    np.testing.assert_allclose(pop,[1.8,.2,0])
    np.testing.assert_allclose(services,[0,.5,.5])
    np.testing.assert_allclose(combined,[1.8,.7,.5])
    # A facility at a zero-population node retains importance; population-only nodes gain it.
    scaled,_,_=combined_node_importance([9000,1000,0],[0,10,10],2)
    np.testing.assert_allclose(scaled,combined)
    service_only,_,_=combined_node_importance([90,10,0],[0,1,1],0)
    np.testing.assert_allclose(service_only,[0,.5,.5])


def test_combined_node_importance_attack_uses_fixed_original_sum(tmp_path):
    from georesilience.links import _link_rows
    from georesilience.robustness import compute_targeted_attack
    from tests.test_sfca import service_fixture
    graph,pop,_,_,_=service_fixture(tmp_path,population=[90,10,0],
        edges=[(0,1,10),(1,0,10)],facilities=[(1,'school',1),(2,'school',1)])
    importance,_,_=combined_node_importance(pop,[0,1,1],2)
    result=compute_targeted_attack(graph,_link_rows(graph),pop,fraction=1,
        service_weights=[0,1,1],node_importance=importance)
    assert result.curve[0]['node_importance_share']==pytest.approx(2.5/3)
    assert result.curve[-1]['node_importance_share']==pytest.approx(1.8/3)
    assert result.summary['node_importance_weighted']['value']==pytest.approx((2.5/3+1.8/3)/2)
