"""Generate synthetic inputs and exercise all five closure acceptance scenarios."""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point

from georesilience.closure import ClosureConfig, RainfallConfig, enrich_road_closures
from georesilience.closure.grids import Grid, write_grid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    inputs = out / "inputs"
    if inputs.exists():
        raise ValueError("choose a fresh demo output directory")
    inputs.mkdir(parents=True)
    roads = gpd.GeoDataFrame(
        {
            "link_uid": ["demo_short", "demo_long", "demo_loop", "demo_outside"],
            "u": ["1", "2", "3", "3"],
            "v": ["2", "3", "3", "4"],
            "length_m": [20.0, 100.0, 40.0, 20.0],
            "p_fail": [0.1, 0.9, None, 0.2],
            "p_fail_source": ["proxy", "proxy", None, "proxy"],
        },
        geometry=[
            LineString([(500030, 1900170), (500050, 1900170)]),
            LineString([(500030, 1900150), (500130, 1900150)]),
            LineString([(500070, 1900130), (500090, 1900130), (500070, 1900130)]),
            LineString([(500230, 1900170), (500250, 1900170)]),
        ],
        crs="EPSG:32644",
    )
    network = inputs / "network.gpkg"
    roads.to_file(network, layer="edges", driver="GPKG", index=False)
    gpd.GeoDataFrame(
        {"node_id": ["1", "2", "3", "4"]},
        geometry=[
            Point(500030, 1900170),
            Point(500050, 1900170),
            Point(500070, 1900130),
            Point(500250, 1900170),
        ],
        crs=roads.crs,
    ).to_file(network, layer="nodes", index=False)
    terrain = np.full((10, 10), 5.0)
    terrain[2:8, 2:8] = 4.9
    dem = inputs / "dem.tif"
    transform = from_origin(500000, 1900200, 20, 20)
    write_grid(dem, Grid(terrain, transform, roads.crs))
    event = inputs / "event.csv"
    event.write_text(
        "start_utc,end_utc,rain_mm\n2000-01-01T00:00:00Z,2000-01-01T06:00:00Z,100\n"
    )
    stations = inputs / "stations.csv"
    pd.DataFrame(
        [
            {
                "station_id": str(i),
                "x": 500000 + x,
                "y": 1900000 + y,
                "start_utc": "2000-01-01T00:00:00Z",
                "end_utc": "2000-01-01T06:00:00Z",
                "rain_mm": 60 + 10 * i,
            }
            for i, (x, y) in enumerate(
                [(30, 170), (110, 170), (30, 90), (70, 110), (90, 150)]
            )
        ]
    ).to_csv(stations, index=False)
    terrain[4, 4] = np.nan
    partial = inputs / "dem_partial.tif"
    write_grid(partial, Grid(terrain, transform, roads.crs))
    scenarios = [
        ("roads_only", None, RainfallConfig()),
        ("event", dem, RainfallConfig(series=event)),
        ("average", dem, RainfallConfig(average_value=20, average_units="mm/hour")),
        ("assumed", dem, RainfallConfig()),
        (
            "partial",
            partial,
            RainfallConfig(
                stations=stations,
                station_crs=str(roads.crs),
                support_distance_m=70,
                extrapolation_distance_m=20,
            ),
        ),
    ]
    for name, elevation, rainfall in scenarios:
        result = enrich_road_closures(
            ClosureConfig(
                roads=network,
                out=out / name,
                dem=elevation,
                rainfall=rainfall,
                scenario_id="synthetic_" + name,
            )
        )
        print(name, result.network, flush=True)


if __name__ == "__main__":
    main()
