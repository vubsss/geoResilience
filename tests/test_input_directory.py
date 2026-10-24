from pathlib import Path

import pytest

from georesilience.inputs import resolve_inputs


@pytest.mark.parametrize("road,source", [("x.osm", "osm_xml"), ("x.osm.xml", "osm_xml"), ("X.GRAPHML", "graphml")])
def test_discovery_independent_of_basename(tmp_path, road, source):
    (tmp_path / road).touch()
    (tmp_path / "residents.TIFF").touch()
    result = resolve_inputs(tmp_path)
    assert result.road.name == road and result.source == source
    assert result.population.name == "residents.TIFF" and result.boundary is None


@pytest.mark.parametrize("names,match", [([], "candidates: none"),
    (["a.osm", "b.graphml"], "a.osm, b.graphml"),
    (["a.osm"], "population GeoTIFF"),
    (["a.osm", "a.tif", "b.tiff"], "a.tif, b.tiff"),
    (["a.osm.pbf", "a.tif"], "unsupported .osm.pbf")])
def test_discovery_errors(tmp_path, names, match):
    for name in names:
        (tmp_path / name).touch()
    with pytest.raises(ValueError, match=match):
        resolve_inputs(tmp_path)


def test_boundary_selection_and_explicit_precedence(tmp_path):
    for name in ("roads.osm", "pop.tif", "boundary.geojson"):
        (tmp_path / name).touch()
    assert resolve_inputs(tmp_path).boundary.name == "boundary.geojson"
    (tmp_path / "boundary.gpkg").touch()
    with pytest.raises(ValueError, match="ambiguous boundary"):
        resolve_inputs(tmp_path)
    assert resolve_inputs(tmp_path, tmp_path / "boundary.gpkg").boundary.suffix == ".gpkg"
    with pytest.raises(ValueError, match="existing .geojson"):
        resolve_inputs(tmp_path, tmp_path / "missing.geojson")


def test_missing_directory(tmp_path):
    with pytest.raises(ValueError, match="directory does not exist"):
        resolve_inputs(tmp_path / "missing")
