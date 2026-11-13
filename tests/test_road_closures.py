"""Closure contracts use physical road exports, real raster coverage and strict CSV parsing."""

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point

from georesilience.closure import ClosureConfig, RainfallConfig, enrich_road_closures
from georesilience.closure.config import load_config
from georesilience.closure.grids import Grid, fill_small_holes, read_grid, write_grid
from georesilience.closure.probability import closure_probability, fragility
from georesilience.closure.rainfall import (
    interpolate_stations,
    prepare_rainfall,
    rebin_intervals,
)
from georesilience.failure_probabilities import read_failure_csv


def make_cleaned_network(tmp_path):
    roads = gpd.GeoDataFrame(
        {
            "link_uid": ["short", "long", "loop", "outside"],
            "u": ["1", "2", "3", "3"],
            "v": ["2", "3", "3", "4"],
            "length_m": [20.0, 100.0, 40.0, 20.0],
            "p_fail": [0.1, 0.9, None, 0.5],
            "p_fail_source": ["proxy", "proxy", None, "proxy"],
            "name": ["a", "b", "c", "d"],
        },
        geometry=[
            LineString([(30, 170), (50, 170)]),
            LineString([(30, 150), (130, 150)]),
            LineString([(70, 130), (90, 130), (70, 130)]),
            LineString([(230, 170), (250, 170)]),
        ],
        crs="EPSG:32644",
    )
    nodes = gpd.GeoDataFrame(
        {"node_id": ["1", "2", "3", "4"], "population": [1, 2, 3, 4]},
        geometry=[Point(30, 170), Point(50, 170), Point(70, 130), Point(250, 170)],
        crs=roads.crs,
    )
    path = tmp_path / "network.gpkg"
    nodes.to_file(path, layer="nodes", driver="GPKG")
    roads.to_file(path, layer="edges", driver="GPKG")
    return path, roads, nodes


@pytest.fixture
def cleaned(tmp_path):
    return make_cleaned_network(tmp_path)


def raster(tmp_path, values, name="depth.tif", transform=None):
    path = tmp_path / name
    write_grid(
        path,
        Grid(
            np.asarray(values, float),
            transform or from_origin(0, 200, 20, 20),
            "EPSG:32644",
        ),
    )
    return path


def enrich(cleaned, tmp_path, **settings):
    result = enrich_road_closures(
        ClosureConfig(roads=cleaned[0], out=tmp_path / "closure", **settings)
    )
    return result, gpd.read_file(result.network, layer="edges")


def test_roads_only_uniform_even_self_loops_preserves_all_features(cleaned, tmp_path):
    result, edges = enrich(cleaned, tmp_path)
    assert edges.p_fail.tolist() == [0.01] * 4
    assert edges.p_fail_source.tolist() == ["uniform_default"] * 4
    assert edges.depth_coverage.eq(0).all()
    original = cleaned[1]
    assert edges[["link_uid", "u", "v", "length_m", "name"]].equals(
        original[["link_uid", "u", "v", "length_m", "name"]]
    )
    assert edges.geometry.to_wkb().equals(original.geometry.to_wkb())
    assert edges.crs == original.crs
    np.testing.assert_allclose(edges.input_p_fail, original.p_fail, equal_nan=True)
    pd.testing.assert_series_equal(
        edges.input_p_fail_source, original.p_fail_source, check_names=False
    )
    nodes = gpd.read_file(result.network, layer="nodes")
    pd.testing.assert_frame_equal(nodes, cleaned[2])
    manifest = json.loads(result.manifest.read_text())
    assert manifest["status"] == "complete" and manifest["inputs"]["roads"]["sha256"]
    assert manifest["validation"]["identity_geometry_crs_preserved"]


def test_valid_dem_without_usable_terrain_uses_uniform_without_solver(
    cleaned, tmp_path, monkeypatch
):
    import subprocess

    def unexpected_solver(*args, **kwargs):
        pytest.fail("an unavailable terrain domain must not start a solver")

    monkeypatch.setattr(subprocess, "run", unexpected_solver)
    dem = raster(tmp_path, np.full((10, 10), np.nan), "empty_dem.tif")
    result, edges = enrich(cleaned, tmp_path, dem=dem)
    assert edges.p_fail.eq(0.01).all()
    assert edges.depth_coverage.eq(0).all()
    assert edges.assumption_flags.str.contains("insufficient_terrain").all()
    manifest = json.loads(result.manifest.read_text())
    assert manifest["simulation"] is None
    assert "fewer than nine" in manifest["simulation_unavailable"]
    assert "Simulation unavailable" in result.coverage_report.read_text()
    assert not (result.network.parent / "maximum_depth.tif").exists()


def test_depth_dry_nodata_and_partial_fallback_once(cleaned, tmp_path):
    values = np.full((10, 10), 0.3)
    values[1, :] = 0  # first road entirely dry
    values[:, 4] = np.nan  # long road and loop have a missing section
    depth = raster(tmp_path, values)
    _, edges = enrich(cleaned, tmp_path, depth=depth)
    assert edges.p_fail.iloc[0] == 0
    assert edges.p_fail_source.iloc[0] == "depth_fragility"
    assert edges.depth_coverage.iloc[1] == pytest.approx(0.8)
    assert edges.p_fail.iloc[1] == pytest.approx(0.505, abs=1e-7)
    assert edges.p_fail.iloc[2] == pytest.approx(0.505, abs=1e-7)
    assert edges.p_fail_source.iloc[1:3].eq("hybrid_uniform").all()
    assert edges.p_fail.iloc[3] == 0.01
    assert edges.depth_coverage.iloc[3] == 0


def test_many_unknown_sections_do_not_repeat_fallback(cleaned, tmp_path):
    values = np.full((10, 10), 0.3)
    values[:, [2, 4]] = np.nan
    _, edges = enrich(cleaned, tmp_path, depth=raster(tmp_path, values))
    assert edges.p_fail.iloc[1] == pytest.approx(0.505, abs=1e-7)
    assert closure_probability(0.3, 0.001)[0] == closure_probability(0.3, 0.999)[0]


def test_fragility_is_single_feature_threshold():
    np.testing.assert_allclose(
        fragility([0, 0.3, 0.6]), [0, 0.5, 0.9761718517], atol=1e-10
    )
    assert closure_probability(None, 0, 0.02) == (0.02, "uniform_default")
    with pytest.raises(ValueError):
        fragility(-1)


def test_provenance_name_collision_rejected_before_publication(cleaned, tmp_path):
    roads = cleaned[1].assign(input_p_fail=0.0)
    path = tmp_path / "conflict.gpkg"
    roads.to_file(path, layer="edges")
    with pytest.raises(ValueError, match="conflicting provenance"):
        enrich_road_closures(ClosureConfig(roads=path, out=tmp_path / "out"))
    assert not (tmp_path / "out").exists()


def test_template_complete_nonself_loop_set_and_fingerprint(cleaned, tmp_path):
    template = tmp_path / "template.csv"
    template.write_text(
        "# georesilience_fingerprint=network123\nlink_uid,p_fail\nshort,\nlong,\noutside,\n"
    )
    result, _edges = enrich(cleaned, tmp_path, failure_template=template)
    links = [
        {"link_uid": r.link_uid, "is_self_loop": r.u == r.v}
        for _, r in cleaned[1].iterrows()
    ]
    values, report = read_failure_csv(
        result.probabilities_csv, links, "network123", require_complete=True
    )
    assert (
        values == {"short": 0.01, "long": 0.01, "outside": 0.01}
        and report["uncovered_links"] == 0
    )
    template.write_text(
        "# georesilience_fingerprint=network123\nlink_uid,p_fail\nshort,\nlong,\n"
    )
    with pytest.raises(ValueError, match="exactly match"):
        enrich_road_closures(
            ClosureConfig(
                roads=cleaned[0], out=tmp_path / "bad", failure_template=template
            )
        )


def test_road_surface_elevation_and_unknown_bridge(cleaned, tmp_path):
    roads = cleaned[1].assign(
        bridge=["yes", "yes", "no", "no"], deck=[None, 5.0, None, None]
    )
    path = tmp_path / "bridge.gpkg"
    roads.to_file(path, layer="edges")
    depth = raster(tmp_path, np.full((10, 10), 0.7))
    terrain = raster(tmp_path, np.full((10, 10), 4.5), "dem.tif")
    _, edges = enrich(
        (path, roads, None),
        tmp_path,
        depth=depth,
        dem=terrain,
        road_elevation_attribute="deck",
    )
    assert edges.p_fail.iloc[0] == 0.01
    assert "structure_carriageway_elevation_unknown" in edges.assumption_flags.iloc[0]
    assert edges.max_depth_m.iloc[1] == pytest.approx(0.2, abs=1e-6)


def test_small_hole_recovery_observations_and_disconnected_zones(tmp_path):
    data = np.add.outer(np.arange(9), np.arange(9)).astype(float)
    data[3, 3] = np.nan
    filled, mask = fill_small_holes(data)
    assert filled[3, 3] == 6 and mask.sum() == 1
    np.testing.assert_array_equal(filled[np.isfinite(data)], data[np.isfinite(data)])
    zones = np.ones((9, 9))
    zones[:, 3:] = 2
    _, mask = fill_small_holes(data, zones=zones)
    assert mask.sum() == 0
    data[1:5, 1:5] = np.nan
    _, mask = fill_small_holes(data)
    assert mask.sum() == 0
    data = np.ones((9, 9))
    data[3, 3] = np.nan
    data[2, 3] = 0
    _, mask = fill_small_holes(data, zones=np.ones_like(data))
    assert mask.sum() == 0


def test_connected_flood_gap_recovers_in_output(cleaned, tmp_path):
    data = np.full((10, 10), 0.3)
    data[2, 3] = np.nan
    result, edges = enrich(
        cleaned,
        tmp_path,
        depth=raster(tmp_path, data),
        flood_zones=raster(tmp_path, np.ones((10, 10)), "zones.tif"),
    )
    assert edges.depth_coverage.iloc[1] == 1
    assert edges.p_fail_source.iloc[1] == "depth_fragility"
    assert "connected_flood_linear_recovery" in edges.reconstruction_flags.iloc[1]
    assert (
        read_grid(result.network.parent / "depth_reconstruction.tif").values.sum() == 1
    )


def test_rainfall_totals_and_climatology_validation(tmp_path):
    grid = Grid(np.ones((3, 3)), from_origin(0, 60, 20, 20), "EPSG:32644")
    for index, config in enumerate(
        [
            RainfallConfig(),
            RainfallConfig(average_value=20, average_units="mm/hour"),
            RainfallConfig(average_value=120, average_units="mm"),
        ]
    ):
        rain = prepare_rainfall(grid, config, tmp_path / str(index), 10000)
        expected = 100 if index == 0 else 120
        assert rain.summary["total_mm_min"] == pytest.approx(expected)
        assert rain.summary["scenario_kind"] == (
            "synthetic" if index == 0 else "representative"
        )
    with pytest.raises(ValueError, match="monthly/annual"):
        RainfallConfig(average_value=800, average_units="mm/year")
    config = RainfallConfig(
        average_value=800, average_units="mm/year", climatology_event_total_mm=80
    )
    assert (
        prepare_rainfall(grid, config, tmp_path / "interpreted", 10000).summary[
            "total_mm_max"
        ]
        == 80
    )


def test_rainfall_temporal_accumulations_and_missing_not_zero(tmp_path):
    series = tmp_path / "rain.csv"
    series.write_text(
        "start_utc,end_utc,rain_mm\n2000-01-01T00:00:00Z,2000-01-01T01:00:00Z,10\n"
        "2000-01-01T01:00:00Z,2000-01-01T02:00:00Z,\n"
        "2000-01-01T02:00:00Z,2000-01-01T03:00:00Z,30\n"
    )
    grid = Grid(np.ones((3, 3)), from_origin(0, 60, 20, 20), "EPSG:32644")
    rain = prepare_rainfall(
        grid, RainfallConfig(series=series), tmp_path / "rain", 10000
    )
    np.testing.assert_allclose(rain.rates[:, 1, 1], [10, 20, 30])
    assert rain.summary["total_mm_min"] == 60
    assert rain.codes[1, 1, 1] == 5
    mm, known, _, _ = rebin_intervals([0], [7200], [20.0], [0, 1800, 3600, 7200])
    np.testing.assert_allclose(mm, [5, 5, 10])
    np.testing.assert_allclose(known, [1800, 1800, 3600])


def test_station_interpolation_validation_and_bounded_extrapolation():
    xy = np.array([[0, 0], [1000, 0], [0, 1000], [1000, 1000], [500, 500]], float)
    values = np.array([10, 20, 15, 25, 17], float)
    targets = np.vstack([xy, [[500, 750], [1500, 500], [4000, 500], [20000, 500]]])
    result, codes, _support, meta = interpolate_stations(
        xy, values, targets, RainfallConfig(allow_kriging=False)
    )
    np.testing.assert_array_equal(result[:5], values)
    assert codes[5] == 1 and codes[6] == 2
    assert np.isnan(result[7:]).all() and meta["validation"] == "leave_one_location_out"
    result, codes, _, meta = interpolate_stations(
        xy[:1], values[:1], np.array([[500, 0], [15000, 0]]), RainfallConfig()
    )
    assert (
        result[0] == 10
        and np.isnan(result[1])
        and meta["single_station_uniformity_assumption"]
    )


def test_cli_and_config_relative_paths(cleaned, tmp_path, capsys):
    from georesilience.cli import main

    config = tmp_path / "scenario.json"
    config.write_text(
        '{"uniform_probability":0.03,"roads":"network.gpkg","out":"configured"}'
    )
    assert load_config(config).roads == cleaned[0]
    assert (
        main(
            [
                "closure",
                "--roads",
                str(cleaned[0]),
                "--config",
                str(config),
                "--out",
                str(tmp_path / "cli"),
            ]
        )
        == 0
    )
    assert (
        gpd.read_file(tmp_path / "cli/network_with_closure.gpkg", layer="edges")
        .p_fail.eq(0.03)
        .all()
    )


def test_failed_solver_does_not_replace_existing_result(cleaned, tmp_path, monkeypatch):
    result, _ = enrich(cleaned, tmp_path)
    before = result.network.read_bytes()
    dem = raster(tmp_path, np.ones((10, 10)), "dem.tif")

    def fail(*args, **kwargs):
        raise RuntimeError("solver failure")

    monkeypatch.setattr("georesilience.closure.pipeline.run_simulation", fail)
    with pytest.raises(RuntimeError, match="solver failure"):
        enrich_road_closures(
            ClosureConfig(
                roads=cleaned[0], out=result.network.parent, dem=dem, overwrite=True
            )
        )
    assert result.network.read_bytes() == before
    assert not list(tmp_path.glob(".closure-*"))


def test_repository_output_and_complete_csv_reused_by_existing_analysis(tmp_path):
    from tests.test_directory_cli import invoke, make_input, run_args

    directory, _, _, _ = make_input(tmp_path)
    output = tmp_path / "analysis"
    assert invoke(run_args(directory, output)) == 0
    template = tmp_path / "template.csv"
    assert (
        invoke(
            ["failures-template", directory, "--out", template, "--no-consolidation"]
        )
        == 0
    )
    closure = enrich_road_closures(
        ClosureConfig(
            roads=output / "network.gpkg",
            out=tmp_path / "closure",
            failure_template=template,
        )
    )
    assert (
        invoke(
            run_args(
                directory,
                tmp_path / "replay",
                "--failure-probs",
                closure.probabilities_csv,
                "--require-complete-failures",
            )
        )
        == 0
    )
    edges = gpd.read_file(tmp_path / "replay/network.gpkg", layer="edges")
    assert edges.loc[edges.u != edges.v, "p_fail"].eq(0.01).all()


def test_large_native_dem_hole_is_not_filled_after_coarsening(tmp_path):
    from georesilience.closure import SimulationConfig
    from georesilience.closure.grids import simulation_grid

    data = np.ones((20, 20))
    data[6:10, 6:10] = np.nan
    dem = raster(tmp_path, data, "native.tif", from_origin(0, 200, 10, 10))
    grid, meta = simulation_grid(
        dem,
        SimulationConfig(),
        clean_crs(),
        tmp_path / "prepared.tif",
        tmp_path / "recovery.tif",
    )
    assert meta["filled_terrain_cells"] == 0
    assert np.isnan(grid.values).any()


def clean_crs():
    from pyproj import CRS

    return CRS("EPSG:32644")


def test_gridded_rainfall_recovers_small_gap_and_bounds_extrapolation(tmp_path):
    values = np.full((10, 10), 60.0)
    values[4, 4] = np.nan
    values[:, 7:] = np.nan
    rain_path = raster(tmp_path, values, "rain.tif")
    grid = Grid(np.ones((10, 10)), from_origin(0, 200, 20, 20), "EPSG:32644")
    rain = prepare_rainfall(
        grid,
        RainfallConfig(
            raster=rain_path, extrapolation_distance_m=20, support_distance_m=50
        ),
        tmp_path / "forcing",
        10000,
    )
    assert rain.codes[0, 4, 4] == 1
    assert rain.codes[0, 4, 7] == 2
    assert rain.codes[0, 4, 9] == 4
    assert rain.summary["source"] == "mixed"
    assert rain.rates[0, 4, 4] == pytest.approx(10)
    stored = np.load(tmp_path / "forcing/resolved_rainfall.npz")
    assert stored["provenance"].shape == rain.rates.shape
    assert stored["support_m"][0, 4, 4] == 20


def test_netcdf_temporal_gap_and_rate_units(tmp_path):
    xr = pytest.importorskip("xarray")
    data = np.array(
        [np.full((3, 3), 10.0), np.full((3, 3), np.nan), np.full((3, 3), 30.0)]
    )
    edges = pd.date_range("2000-01-01", periods=4, freq="h")
    ds = xr.Dataset(
        {
            "rain_mm": (("time", "y", "x"), data),
            "time_bounds": (
                ("time", "bounds"),
                np.column_stack((edges[:-1], edges[1:])),
            ),
        },
        coords={"time": edges[:-1], "y": [50.0, 30.0, 10.0], "x": [10.0, 30.0, 50.0]},
        attrs={"crs": "EPSG:32644"},
    )
    ds.rain_mm.attrs["units"] = "mm/hour"
    path = tmp_path / "rain.nc"
    ds.to_netcdf(path)
    grid = Grid(np.ones((3, 3)), from_origin(0, 60, 20, 20), "EPSG:32644")
    rain = prepare_rainfall(
        grid, RainfallConfig(netcdf=path), tmp_path / "forcing", 10000
    )
    np.testing.assert_allclose(rain.rates[:, 1, 1], [10, 20, 30])
    assert rain.codes[1, 1, 1] == 5 and rain.summary["source"] == "event"


def test_bad_declared_rainfall_prevents_roads_only_publication(cleaned, tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(
        "start_utc,end_utc,rain_mm\n2000-01-01T00:00:00Z,2000-01-01T01:00:00Z,-1\n"
    )
    with pytest.raises(ValueError, match="nonnegative"):
        enrich(cleaned, tmp_path, rainfall=RainfallConfig(series=path))
    assert not (tmp_path / "closure").exists()


def test_layer_override_sensitivity_and_safe_overwrite(cleaned, tmp_path):
    from georesilience.closure import SensitivityConfig

    custom = tmp_path / "custom.gpkg"
    cleaned[1].to_file(custom, layer="physical")
    config = ClosureConfig(
        roads=custom,
        out=tmp_path / "result",
        layer="physical",
        sensitivity=SensitivityConfig(enabled=True),
    )
    enrich_road_closures(config)
    (config.out / "notes.txt").write_text("keep my notes")
    second = enrich_road_closures(
        config.model_copy(update={"overwrite": True, "uniform_probability": 0.02})
    )
    assert (config.out / "notes.txt").read_text() == "keep my notes"
    assert gpd.read_file(second.network, layer="edges").p_fail.eq(0.02).all()
    sensitivity = pd.read_csv(config.out / "sensitivity.csv")
    assert sensitivity.scenario.nunique() == 5


def test_bound_hybrid_coverage_with_different_depth_and_dem_grids(
    tmp_path, monkeypatch
):
    # A long supplied NoData segment must be split at the secondary model grid,
    # not accepted/rejected from one midpoint sample.
    from georesilience.closure.pipeline import _extract

    roads = gpd.GeoDataFrame(
        {"link_uid": ["r"], "u": ["a"], "v": ["b"], "length_m": [100.0]},
        geometry=[LineString([(0, 50), (100, 50)])],
        crs="EPSG:32644",
    )
    supplied = raster(
        tmp_path, [[np.nan]], "supplied.tif", from_origin(0, 100, 100, 100)
    )
    simulated = raster(
        tmp_path,
        [[0.3, np.nan, 0.3, np.nan, 0.3]],
        "model.tif",
        from_origin(0, 100, 20, 100),
    )
    config = ClosureConfig(roads=tmp_path / "unused.gpkg", out=tmp_path / "unused")
    result = _extract(
        roads, clean_crs(), config, supplied=supplied, simulated=simulated
    )
    assert result.depth_coverage.iloc[0] == pytest.approx(0.6)
    assert result.p_fail.iloc[0] == pytest.approx(0.505, abs=1e-7)


def test_dry_ground_does_not_invent_water_on_below_ground_carriageway(tmp_path):
    from georesilience.closure.pipeline import _extract

    roads = gpd.GeoDataFrame(
        {
            "link_uid": ["r"],
            "u": ["a"],
            "v": ["b"],
            "length_m": [20.0],
            "tunnel": ["yes"],
            "deck": [4.0],
        },
        geometry=[LineString([(30, 170), (50, 170)])],
        crs="EPSG:32644",
    )
    depth = raster(tmp_path, np.zeros((10, 10)), "dry.tif")
    level = raster(tmp_path, np.full((10, 10), 5.0), "level.tif")
    config = ClosureConfig(
        roads=tmp_path / "unused.gpkg",
        out=tmp_path / "unused",
        road_elevation_attribute="deck",
    )
    result = _extract(roads, clean_crs(), config, simulated=depth, water=level)
    assert result.p_fail.iloc[0] == 0.01 and result.depth_coverage.iloc[0] == 0
    assert (
        "below_ground_carriageway_water_depth_unresolved"
        in result.assumption_flags.iloc[0]
    )


def test_flood_gap_reconstructs_water_level_over_nonuniform_terrain(cleaned, tmp_path):
    terrain = np.ones((10, 10))
    terrain[2, 3] = 1.5
    depths = 2 - terrain
    depths[2, 3] = np.nan
    result, _ = enrich(
        cleaned,
        tmp_path,
        depth=raster(tmp_path, depths),
        dem=raster(tmp_path, terrain, "dem.tif"),
        flood_zones=raster(tmp_path, np.ones((10, 10)), "zones.tif"),
    )
    recovered = read_grid(result.network.parent / "recovered_depth.tif").values
    assert recovered[2, 3] == pytest.approx(0.5)
    assert np.array_equal(recovered[np.isfinite(depths)], depths[np.isfinite(depths)])


def test_landcover_nearest_recovery_soil_C_and_parameter_map_precedence(tmp_path):
    from georesilience.closure.sfincs import parameter_maps

    cover = np.full((5, 5), 50.0)
    cover[2, 2] = np.nan
    supplied_cn = np.full((5, 5), 75.0)
    supplied_cn[2, 2] = np.nan
    config = ClosureConfig(
        roads=tmp_path / "unused.gpkg",
        out=tmp_path / "unused",
        landcover=raster(tmp_path, cover, "cover.tif"),
        curve_number_map=raster(tmp_path, supplied_cn, "CN.tif"),
    )
    grid = Grid(np.ones((5, 5)), from_origin(0, 200, 20, 20), clean_crs())
    directory = tmp_path / "parameters"
    directory.mkdir()
    cn, rough, flags, meta = parameter_maps(config, grid, directory)
    assert cn[2, 2] == 94 and cn[1, 1] == 75
    assert np.all(rough == 0.08)
    assert meta["recovery"]["landcover_nearest_cells"] == 1
    assert "soil_group_C_assumed_upstream_possible" in flags
    assert read_grid(directory / "landcover_reconstruction.tif").values[2, 2] == 1
