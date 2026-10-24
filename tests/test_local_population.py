"""Offline local-road population crops and population-count raster contracts."""

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import LineString, Polygon, box
from shapely.ops import transform

from georesilience.config import RunConfig
from georesilience.network import load_and_clean
from georesilience.population import allocate_population, study_boundary
from tests.helpers.small_inputs import boundary_for, cell_graph, raster_fixture, xml_fixture


def test_derived_crop_uses_retained_node_extent_and_snap_distance(tmp_path):
    _, affine = raster_fixture(tmp_path)
    graph = cell_graph(affine, cells=9)
    boundary, metadata = study_boundary(graph, snap_max_m=25)
    expected = [500025, 1900025, 500275, 1900275]
    projected = transform(Transformer.from_crs(4326, 32644, always_xy=True).transform, boundary)
    np.testing.assert_allclose(projected.bounds, expected, atol=1e-6, rtol=0)
    np.testing.assert_allclose(metadata["bounds_graph_crs"], expected, atol=1e-6, rtol=0)
    np.testing.assert_allclose(metadata["bounds_wgs84"], boundary.bounds, atol=1e-12, rtol=0)
    assert metadata["method"] == "retained_graph_extent_plus_snap"
    assert metadata["snap_max_m"] == 25
    assert study_boundary(graph, snap_max_m=25)[1] == metadata


def test_explicit_projected_boundary_takes_precedence_and_controls_count_crop(tmp_path):
    path, affine = raster_fixture(tmp_path)
    graph = cell_graph(affine, cells=9)
    supplied = box(500000, 1900000, 500200, 1900300)
    boundary_path = tmp_path / "boundary.gpkg"
    gpd.GeoDataFrame(geometry=[supplied], crs=32644).to_file(boundary_path, driver="GPKG")
    explicit, metadata = study_boundary(graph, boundary_path=boundary_path, snap_max_m=10)
    derived, derived_metadata = study_boundary(graph, snap_max_m=10)
    assert metadata["method"] == "supplied_boundary"
    assert derived_metadata["method"] == "retained_graph_extent_plus_snap"
    projected = transform(Transformer.from_crs(4326, 32644, always_xy=True).transform, explicit)
    assert projected.hausdorff_distance(supplied) < 1e-6
    _, explicit_totals = allocate_population(graph, explicit, path, 10)
    _, derived_totals = allocate_population(graph, derived, path, 10)
    assert explicit_totals["total"] == explicit_totals["allocated"] == 27
    assert derived_totals["total"] == derived_totals["allocated"] == 45


@pytest.mark.parametrize("geometry", [
    LineString([(500000, 1900000), (500100, 1900100)]),
    Polygon([(500000, 1900000), (500100, 1900100), (500000, 1900100),
             (500100, 1900000), (500000, 1900000)]),
])
def test_explicit_boundary_rejects_lines_and_invalid_polygons(tmp_path, geometry):
    _, affine = raster_fixture(tmp_path)
    boundary_path = tmp_path / "boundary.gpkg"
    gpd.GeoDataFrame(geometry=[geometry], crs=32644).to_file(boundary_path, driver="GPKG")
    with pytest.raises(ValueError, match="(?i)polygon|boundary|invalid"):
        study_boundary(cell_graph(affine), boundary_path=boundary_path)


def test_explicit_boundary_requires_crs(tmp_path):
    _, affine = raster_fixture(tmp_path)
    boundary_path = tmp_path / "boundary.shp"
    gpd.GeoDataFrame(geometry=[box(500000, 1900000, 500300, 1900300)]).to_file(
        boundary_path, driver="ESRI Shapefile")
    with pytest.raises(ValueError, match="CRS"):
        study_boundary(cell_graph(affine), boundary_path=boundary_path)


def test_derived_boundary_requires_finite_metric_node_coordinates():
    empty = nx.MultiDiGraph(crs=32644)
    with pytest.raises(ValueError):
        study_boundary(empty)
    invalid = nx.MultiDiGraph(crs=32644)
    invalid.add_node(0, x=float("nan"), y=1900000)
    with pytest.raises(ValueError):
        study_boundary(invalid)
    geographic = nx.MultiDiGraph(crs=4326)
    geographic.add_node(0, x=78, y=17)
    with pytest.raises(ValueError, match="(?i)metre|metric|projected"):
        study_boundary(geographic)


def test_non_overlapping_raster_is_an_error(tmp_path):
    path, affine = raster_fixture(tmp_path)
    with pytest.raises(ValueError, match="(?i)overlap"):
        allocate_population(cell_graph(affine), box(80, 16, 80.1, 16.1), path, 10)


@pytest.mark.parametrize("crs,bands", [(None, 1), (32644, 2)])
def test_population_raster_requires_crs_and_one_band(tmp_path, crs, bands):
    path, affine = raster_fixture(tmp_path)
    with rasterio.open(path, "w", driver="GTiff", height=3, width=3, count=bands,
                       dtype="float32", crs=crs, transform=affine) as raster:
        raster.write(np.ones((bands, 3, 3), dtype="float32"))
    with pytest.raises(ValueError, match="(?i)CRS|band"):
        allocate_population(cell_graph(affine), boundary_for(affine), path, 10)


@pytest.mark.parametrize("invalid_count", [-1, float("nan"), float("inf")])
def test_unmasked_negative_and_nonfinite_counts_are_rejected(tmp_path, invalid_count):
    path, affine = raster_fixture(tmp_path, [[invalid_count, 1, 0], [0, 0, 0], [0, 0, 0]])
    with pytest.raises(ValueError, match="(?i)finite|negative|count|invalid"):
        allocate_population(cell_graph(affine), boundary_for(affine), path, 10)


def test_masked_nodata_and_zero_population_are_valid(tmp_path):
    path, affine = raster_fixture(tmp_path, [[-9999, 0, 0], [0, 0, 0], [0, 0, 0]])
    weights, totals = allocate_population(cell_graph(affine), boundary_for(affine), path, 10)
    np.testing.assert_array_equal(weights, np.zeros(8))
    assert totals == {"total": 0, "allocated": 0, "unallocated": 0, "unallocated_pct": 0}


@pytest.mark.parametrize("metadata_location", ["tags", "band_unit"])
def test_detectable_density_units_are_rejected(tmp_path, metadata_location):
    path, affine = raster_fixture(tmp_path)
    with rasterio.open(path, "r+") as raster:
        if metadata_location == "tags":
            raster.update_tags(units="people/km2")
        else:
            raster.set_band_unit(1, "people/km2")
    with pytest.raises(ValueError, match="(?i)density|units|count"):
        allocate_population(cell_graph(affine), boundary_for(affine), path, 10)


@pytest.mark.parametrize("scale,offset", [(2, 0), (1, 10)])
def test_scaled_raster_values_are_not_silently_treated_as_counts(tmp_path, scale, offset):
    path, affine = raster_fixture(tmp_path)
    with rasterio.open(path, "r+") as raster:
        raster.scales = [scale]
        raster.offsets = [offset]
    with pytest.raises(ValueError, match="(?i)scale|offset|count"):
        allocate_population(cell_graph(affine), boundary_for(affine), path, 10)


@pytest.mark.parametrize("source", ["graphml", "osm_xml"])
def test_tiny_local_road_files_accept_population_and_allocate_retained_nodes(tmp_path, source):
    path, affine = raster_fixture(tmp_path)
    if source == "graphml":
        road_path = tmp_path / "roads.graphml"
        ox.save_graphml(cell_graph(affine), filepath=road_path)
    else:
        road_path = xml_fixture(tmp_path / "roads.osm")
    config = RunConfig(input={"source": source, "path": road_path},
                       cleaning={"consolidate": False},
                       population={"worldpop": str(path), "snap_max_m": 25})
    graph, _, _ = load_and_clean(config)
    # Align a tiny local raster to one retained node after XML projection.
    first = next(iter(graph.nodes.values()))
    affine = from_origin(first["x"] - 5, first["y"] + 5, 10, 10)
    with rasterio.open(path, "w", driver="GTiff", height=3, width=3, count=1,
                       dtype="float32", crs=graph.graph["crs"], transform=affine) as raster:
        raster.write(np.ones((3, 3), dtype="float32"), 1)
    boundary, _ = study_boundary(graph, snap_max_m=config.population.snap_max_m)
    weights, totals = allocate_population(graph, boundary, path, config.population.snap_max_m)
    assert len(weights) == len(graph) > 1
    assert 0 < totals["allocated"] <= totals["total"]
    assert totals["total"] == pytest.approx(totals["allocated"] + totals["unallocated"])
