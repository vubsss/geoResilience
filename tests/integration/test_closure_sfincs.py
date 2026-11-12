"""Opt-in acceptance runs execute the digest-pinned CPU solver, never a mock.

GEORESILIENCE_TEST_SFINCS=1 python -m pytest tests/integration/test_closure_sfincs.py
Docker must already contain the pinned image (tests perform no network requests).
"""

import json
import os

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest

from georesilience.closure import (
    ClosureConfig,
    RainfallConfig,
    SensitivityConfig,
    enrich_road_closures,
)
from tests.test_road_closures import make_cleaned_network, raster

pytestmark = pytest.mark.skipif(
    os.environ.get("GEORESILIENCE_TEST_SFINCS") != "1",
    reason="requires explicit opt-in and pinned SFINCS Docker image",
)


@pytest.fixture
def cleaned(tmp_path):
    return make_cleaned_network(tmp_path)


@pytest.mark.parametrize("forcing", ["event", "average", "assumed", "partial", "dry"])
def test_real_sfincs_acceptance(cleaned, tmp_path, forcing):
    terrain = np.full((10, 10), 5.0)
    terrain[2:8, 2:8] = 4.9
    rain = RainfallConfig()
    if forcing == "event":
        series = tmp_path / "event.csv"
        series.write_text(
            "start_utc,end_utc,rain_mm\n2020-10-13T00:00:00Z,2020-10-13T06:00:00Z,100\n"
        )
        rain = RainfallConfig(series=series)
    elif forcing == "average":
        rain = RainfallConfig(average_value=20, average_units="mm/hour")
    elif forcing == "dry":
        rain = RainfallConfig(average_value=0, average_units="mm/hour")
    elif forcing == "partial":
        terrain[4, 4] = np.nan
        stations = tmp_path / "stations.csv"
        pd.DataFrame(
            [
                {
                    "station_id": str(i),
                    "x": x,
                    "y": y,
                    "start_utc": "2020-10-13T00:00:00Z",
                    "end_utc": "2020-10-13T06:00:00Z",
                    "rain_mm": 60 + 10 * i,
                }
                for i, (x, y) in enumerate(
                    [(30, 170), (110, 170), (30, 90), (70, 110), (90, 150)]
                )
            ]
        ).to_csv(stations, index=False)
        rain = RainfallConfig(
            stations=stations,
            station_crs="EPSG:32644",
            support_distance_m=70,
            extrapolation_distance_m=20,
        )
    dem = raster(tmp_path, terrain, "dem.tif")
    out = tmp_path / forcing
    result = enrich_road_closures(
        ClosureConfig(
            roads=cleaned[0],
            out=out,
            dem=dem,
            rainfall=rain,
            sensitivity=SensitivityConfig(enabled=forcing == "assumed"),
        )
    )
    edges = gpd.read_file(result.network, layer="edges")
    assert np.isfinite(edges.p_fail).all()
    assert edges.p_fail.iloc[-1] == 0.01
    assert edges.p_fail_source.iloc[:3].eq("depth_fragility").all()
    manifest = json.loads(result.manifest.read_text())
    sim = manifest["simulation"]
    assert (
        sim["solver_exit_code"] == 0
        and sim["maximum_rainfall_accumulation_error_mm"] < 2
    )
    assert (
        sim["rainfall"]["source"]
        == {
            "event": "event",
            "average": "average",
            "assumed": "assumed",
            "partial": "mixed",
            "dry": "average",
        }[forcing]
    )
    expected_total = {"event": 100, "average": 120, "assumed": 100, "dry": 0}
    if forcing in expected_total:
        assert sim["rainfall"]["total_mm_min"] == pytest.approx(expected_total[forcing])
    if forcing == "dry":
        assert edges.p_fail.iloc[:3].eq(0).all()
    assert (out / "maximum_depth.tif").is_file()
    if forcing == "partial":
        assert sim["terrain"]["filled_terrain_cells"] == 1
        assert (
            sim["rainfall"]["reconstruction"][0]["validation"]
            == "leave_one_location_out"
        )
        assert (
            edges.reconstruction_flags.iloc[:3]
            .str.contains("terrain_recovery_upstream_possible")
            .all()
        )
        assert (out / "simulation/rainfall/rainfall_support_m.tif").is_file()
    if forcing == "assumed":
        sensitivity = pd.read_csv(out / "sensitivity.csv")
        assert sensitivity.scenario.nunique() == 9
        assert set(sensitivity.link_uid) == set(edges.link_uid)
        assert "not confidence intervals" in (out / "sensitivity.txt").read_text()
