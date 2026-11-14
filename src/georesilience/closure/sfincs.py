"""Pinned native SFINCS adapter; solver errors never become default probabilities."""

import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from scipy import ndimage

from .grids import (
    Grid,
    TerrainUnavailable,
    fill_small_holes,
    on_grid,
    recovery_distances,
    simulation_grid,
    write_grid,
)
from .rainfall import prepare_rainfall

LOOKUP_VERSION = "worldcover-tr55-screening-v1"
# WorldCover codes; TR-55 cover analogues are project mappings, not calibrated local values.
CN = {
    10: [30, 55, 70, 77],
    20: [48, 67, 77, 83],
    30: [39, 61, 74, 80],
    40: [67, 78, 85, 89],
    50: [89, 92, 94, 95],
    60: [77, 86, 91, 94],
    70: [98] * 4,
    80: [100] * 4,
    90: [85, 90, 95, 97],
    95: [85, 90, 95, 97],
    100: [49, 69, 79, 84],
}
MANNING = {
    10: 0.10,
    20: 0.06,
    30: 0.035,
    40: 0.04,
    50: 0.08,
    60: 0.03,
    70: 0.03,
    80: 0.025,
    90: 0.07,
    95: 0.10,
    100: 0.04,
}


def parameter_maps(config, grid, directory):
    active = np.isfinite(grid.values)
    flags, recovery = [], {}
    cn = np.full(grid.shape, config.simulation.curve_number)
    rough = np.full(grid.shape, config.simulation.manning)
    cn_source = np.zeros(grid.shape, dtype="uint8")
    rough_source = np.zeros(grid.shape, dtype="uint8")
    if config.landcover:
        cover = on_grid(config.landcover, grid, categorical=True)
        cover_original = cover.copy()
        cover, filled = fill_small_holes(cover, categorical=True)
        write_grid(
            directory / "landcover_reconstruction.tif",
            Grid(filled.astype(float), grid.transform, grid.crs),
            dtype="uint8",
            nodata=255,
        )
        write_grid(
            directory / "landcover_reconstruction_support_m.tif",
            Grid(
                recovery_distances(cover_original, filled, grid.transform, grid.crs),
                grid.transform,
                grid.crs,
            ),
        )
        write_grid(
            directory / "landcover_resolved.tif", Grid(cover, grid.transform, grid.crs)
        )
        recovery["landcover_nearest_cells"] = int(filled.sum())
        if filled.any():
            flags.append("categorical_nearest_recovery_upstream_possible")
        soil = (
            on_grid(config.soil_groups, grid, categorical=True)
            if config.soil_groups
            else np.full(grid.shape, np.nan)
        )
        soil_original = soil.copy()
        soil, soil_filled = fill_small_holes(soil, categorical=True)
        valid_soil = np.isin(soil, [1, 2, 3, 4])
        soil = np.where(valid_soil, soil, 3).astype(int)
        write_grid(
            directory / "soil_groups_resolved.tif",
            Grid(soil.astype(float), grid.transform, grid.crs),
        )
        write_grid(
            directory / "soil_group_assumed.tif",
            Grid((~valid_soil).astype(float), grid.transform, grid.crs),
            dtype="uint8",
            nodata=255,
        )
        write_grid(
            directory / "soil_reconstruction.tif",
            Grid(soil_filled.astype(float), grid.transform, grid.crs),
            dtype="uint8",
            nodata=255,
        )
        write_grid(
            directory / "soil_reconstruction_support_m.tif",
            Grid(
                recovery_distances(
                    soil_original, soil_filled, grid.transform, grid.crs
                ),
                grid.transform,
                grid.crs,
            ),
        )
        if np.any(~valid_soil & active):
            flags.append("soil_group_C_assumed_upstream_possible")
        recovery["soil_nearest_cells"] = int(soil_filled.sum())
        if soil_filled.any():
            flags.append("categorical_nearest_recovery_upstream_possible")
        found = np.zeros(grid.shape, bool)
        for code, numbers in CN.items():
            match = cover == code
            cn[match] = np.asarray(numbers)[soil[match] - 1]
            rough[match] = MANNING[code]
            cn_source[match] = 1
            rough_source[match] = 1
            found |= match
        if np.any(~found & active):
            flags.extend(
                ["default_CN_upstream_possible", "default_Manning_upstream_possible"]
            )
        flags.append("landcover_parameter_transfer_uncalibrated")
    else:
        flags.extend(
            ["default_CN_upstream_possible", "default_Manning_upstream_possible"]
        )
    for path, values, name, low, high in (
        (config.curve_number_map, cn, "CN", 0, 100),
        (config.roughness_map, rough, "Manning", 0, 0.5),
    ):
        if path:
            supplied = on_grid(path, grid)
            valid = np.isfinite(supplied)
            if np.any((supplied[valid] <= low) | (supplied[valid] > high)):
                raise ValueError(f"invalid {name} raster values")
            values[valid] = supplied[valid]
            (cn_source if name == "CN" else rough_source)[valid] = 2
            if np.all(valid[active]):
                flags = [
                    flag
                    for flag in flags
                    if flag != f"default_{name}_upstream_possible"
                ]
    for name, values in (("curve_number", cn), ("manning", rough)):
        write_grid(
            directory / f"{name}.tif",
            Grid(np.where(active, values, np.nan), grid.transform, grid.crs),
        )
    for name, values in (("CN", cn_source), ("Manning", rough_source)):
        write_grid(
            directory / f"{name}_source.tif",
            Grid(np.where(active, values, np.nan), grid.transform, grid.crs),
            dtype="uint8",
            nodata=255,
        )
    return (
        cn,
        rough,
        sorted(set(flags)),
        {
            "lookup_version": LOOKUP_VERSION,
            "recovery": recovery,
            "CN_min": float(cn[active].min()),
            "CN_max": float(cn[active].max()),
            "Manning_min": float(rough[active].min()),
            "Manning_max": float(rough[active].max()),
            "source_codes": {
                "0": "uniform_default",
                "1": "landcover_transfer",
                "2": "supplied_parameter_map",
            },
        },
    )


def _binary(path, values, active, dtype):
    # Native indexing: one-based column-major, with rows ascending from the lower left.
    np.flipud(values).T[np.flipud(active).T].astype(dtype).tofile(path)


def _forcing(path, grid, rainfall, stop):
    try:
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError(
            "install georesilience[closure-simulation] to run SFINCS"
        ) from exc
    # SFINCS FEWS reader interprets x/y as lower-left cell coordinates, not centres.
    times = (
        np.append(rainfall.edges_seconds, stop)
        if stop > rainfall.edges_seconds[-1]
        else rainfall.edges_seconds
    )
    rates = np.concatenate(
        [rainfall.rates, np.zeros((len(times) - len(rainfall.rates), *grid.shape))]
    )
    origin = datetime.fromisoformat(
        rainfall.summary["origin_utc"].replace("Z", "+00:00")
    ).replace(tzinfo=None)
    if not np.allclose(times / 60, np.round(times / 60), rtol=0, atol=1e-7):
        raise ValueError(
            "SFINCS FEWS forcing requires event/recession durations in whole minutes"
        )
    # The pinned FEWS reader always converts integer minutes, regardless of a
    # declared seconds unit. Pad one cell so its bilinear stencil covers all cells.
    forcing = np.pad(
        np.flip(rates, axis=1), ((0, 0), (1, 1), (1, 1)), mode="edge"
    ).astype("float32")
    ds = xr.Dataset(
        {"Precipitation": (("time", "y", "x"), forcing)},
        coords={
            "time": times / 60,
            "x": grid.transform.c
            + (np.arange(grid.shape[1] + 2) - 1) * grid.transform.a,
            "y": grid.transform.f
            + grid.shape[0] * grid.transform.e
            + (np.arange(grid.shape[0] + 2) - 1) * (-grid.transform.e),
        },
    )
    ds.time.attrs["units"] = "minutes since " + origin.strftime("%Y-%m-%d %H:%M:%S")
    ds.Precipitation.attrs["units"] = "mm h-1"
    ds.to_netcdf(path, engine="netcdf4")
    return origin


def run_simulation(config, metric_crs, directory, *, rainfall_multiplier=1.0):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    grid, terrain = simulation_grid(
        config.dem,
        config.simulation,
        metric_crs,
        directory / "dem.tif",
        directory / "terrain_reconstruction.tif",
        config.domain,
    )
    rain = prepare_rainfall(
        grid,
        config.rainfall,
        directory / "rainfall",
        config.simulation.max_forcing_values,
        rainfall_multiplier,
    )
    cn, rough, flags, parameters = parameter_maps(config, grid, directory)
    if terrain["filled_terrain_cells"]:
        flags.append("linear_terrain_recovery_upstream_possible")
    if terrain["incomplete_terrain"]:
        flags.append("incomplete_upstream_terrain")
    rain_codes = set(np.unique(rain.codes).tolist())
    flags.extend(
        f"rainfall_{name}_upstream_possible"
        for code, name in (
            (1, "interpolated"),
            (2, "extrapolated"),
            (3, "average"),
            (4, "assumed"),
            (5, "temporal_interpolation"),
        )
        if code in rain_codes
    )
    for detail in rain.summary["reconstruction"]:
        if detail.get("temporal_reconstruction_station_ids"):
            flags.append("rainfall_temporal_interpolation_upstream_possible")
        if detail.get("method") in ("idw", "mean", "kriging", "grid_bounded_idw"):
            flags.append(
                "rainfall_" + detail["method"] + "_reconstruction_upstream_possible"
            )
        if detail.get("single_station_uniformity_assumption") or detail.get(
            "single_pixel_uniformity_assumption"
        ):
            flags.append("single_observation_rainfall_uniformity_assumed")
    flags.extend(
        [
            "supplied_native_drainage_structures"
            if "drnfile" in config.simulation.native_files
            else "no_underground_drainage_removal",
            "initially_dry"
            if config.simulation.initial_level_m is None
            else "uniform_initial_water_level",
        ]
    )
    flags.append("hydrologic_domain_catchment_completeness_unverified")
    flags.append(
        f"solver_depths_at_or_below_{config.simulation.wetting_depth_m:g}m_reported_dry"
    )
    if (
        "bzsfile" not in config.simulation.native_files
        and "disfile" not in config.simulation.native_files
    ):
        flags.append("local_pluvial_no_external_river_forcing")
    active = np.isfinite(grid.values)
    mask = active.astype("uint8")
    edge = active & ~ndimage.binary_erosion(active, structure=np.ones((3, 3)))
    if config.simulation.boundary == "outflow":
        mask[edge] = 3
    if "bndfile" in config.simulation.native_files:
        # Native boundary coordinates activate only their nearest boundary cells.
        points = np.loadtxt(config.simulation.native_files["bndfile"], ndmin=2)
        for x, y, *_ in points:
            col, row = ~grid.transform * (x, y)
            row, col = int(np.floor(row)), int(np.floor(col))
            if not (
                0 <= row < grid.shape[0] and 0 <= col < grid.shape[1] and edge[row, col]
            ):
                raise ValueError(
                    "native boundary point must lie in an active domain boundary cell"
                )
            mask[row, col] = 2
    if not (mask == 1).any():
        raise TerrainUnavailable(
            "hydrologic domain has no interior computational cells"
        )
    lower_active = np.flipud(active).T.ravel()
    indices = np.flatnonzero(lower_active) + 1
    np.concatenate([[len(indices)], indices]).astype("<i4").tofile(
        directory / "sfincs.ind"
    )
    for name, values, dtype in (
        ("dep", grid.values, "<f4"),
        ("msk", mask, "u1"),
        ("man", rough, "<f4"),
        ("scs", 1000 / cn - 10, "<f4"),
    ):
        _binary(directory / f"sfincs.{name}", values, active, dtype)
    event_seconds = float(rain.edges_seconds[-1])
    stop = event_seconds + config.simulation.recession_hours * 3600
    if abs(stop - round(stop)) > 1e-6 or stop < 1:
        raise ValueError("solver duration must be a positive integer number of seconds")
    origin = _forcing(directory / "rainfall.nc", grid, rain, stop)
    values = {
        "mmax": grid.shape[1],
        "nmax": grid.shape[0],
        "dx": grid.transform.a,
        "dy": -grid.transform.e,
        "x0": grid.transform.c,
        "y0": grid.transform.f + grid.shape[0] * grid.transform.e,
        "rotation": 0,
        "epsg": grid.crs.to_epsg(),
        "tref": origin.strftime("%Y%m%d %H%M%S"),
        "tstart": origin.strftime("%Y%m%d %H%M%S"),
        "tstop": (origin + timedelta(seconds=stop)).strftime("%Y%m%d %H%M%S"),
        "inputformat": "bin",
        "outputformat": "net",
        "indexfile": "sfincs.ind",
        "depfile": "sfincs.dep",
        "mskfile": "sfincs.msk",
        "manningfile": "sfincs.man",
        "scsfile": "sfincs.scs",
        "sfacinf": 0.2,
        "netamprfile": "rainfall.nc",
        "amprblock": 1,
        "dtwnd": min(60.0, float(np.min(np.diff(rain.edges_seconds))) / 60),
        "dtout": stop,
        "dtmaxout": stop,
        "dthisout": stop,
        "storecumprcp": 1,
        "advection": 1,
        "theta": 1,
        "alpha": 0.5,
        "huthresh": config.simulation.wetting_depth_m,
        "zsini": config.simulation.initial_level_m
        if config.simulation.initial_level_m is not None
        else float(np.nanmin(grid.values) - 1),
    }
    for keyword, source in config.simulation.native_files.items():
        name = keyword + ".dat"
        shutil.copyfile(source, directory / name)
        values[keyword] = name
    (directory / "sfincs.inp").write_text(
        "\n".join(f"{key} = {value}" for key, value in values.items()) + "\n"
    )
    env = dict(os.environ, OMP_NUM_THREADS=str(config.simulation.threads))
    if config.simulation.executable:
        command = [str(config.simulation.executable.expanduser().resolve())]
    else:
        container_name = "georesilience-" + uuid.uuid4().hex
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            *(["--user", f"{os.getuid()}:{os.getgid()}"] if os.name != "nt" else []),
            "--name",
            container_name,
            "-e",
            f"OMP_NUM_THREADS={config.simulation.threads}",
            "-v",
            f"{directory.resolve()}:/data",
            "-w",
            "/data",
            config.simulation.docker_image,
        ]
    try:
        with (directory / "solver.log").open("w") as log:
            completed = subprocess.run(
                command,
                cwd=directory,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=config.simulation.timeout_seconds,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        if not config.simulation.executable:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        raise RuntimeError(f"SFINCS could not complete: {exc}") from exc
    logs = (directory / "solver.log").read_text(errors="replace")
    if (directory / "sfincs.log").exists():
        logs += (directory / "sfincs.log").read_text(errors="replace")
    if completed.returncode != 0 or "simulation finished" not in logs.lower():
        raise RuntimeError(
            f"SFINCS failed (exit {completed.returncode}); output was not published. Log tail: {logs[-1800:]}"
        )
    depth, water, accumulation_error = _read_maximum(
        directory / "sfincs_map.nc", grid, mask, stop, rain
    )
    write_grid(directory / "maximum_depth.tif", Grid(depth, grid.transform, grid.crs))
    write_grid(
        directory / "maximum_water_level.tif", Grid(water, grid.transform, grid.crs)
    )
    write_grid(
        directory / "simulation_support.tif",
        Grid((mask == 1).astype(float), grid.transform, grid.crs),
        dtype="uint8",
        nodata=255,
    )
    metadata = {
        "engine": "SFINCS",
        "image": config.simulation.docker_image
        if not config.simulation.executable
        else None,
        "executable": str(config.simulation.executable)
        if config.simulation.executable
        else None,
        "terrain": terrain,
        "parameters": parameters,
        "rainfall": rain.summary,
        "boundary": config.simulation.boundary,
        "boundary_cells_excluded_from_road_support": True,
        "forcing_update_seconds": values["dtwnd"],
        "flags": sorted(set(flags)),
        "duration_seconds": stop,
        "solver_exit_code": completed.returncode,
        "maximum_rainfall_accumulation_error_mm": accumulation_error,
    }
    (directory / "simulation.json").write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n"
    )
    return (
        directory / "maximum_depth.tif",
        directory / "maximum_water_level.tif",
        metadata,
    )


def _read_maximum(path, grid, mask, stop, rain):
    import xarray as xr

    with xr.open_dataset(path, decode_times=False, mask_and_scale=False) as ds:
        if "zsmax" not in ds or "time" not in ds or float(ds.time.max()) < stop - 0.1:
            raise RuntimeError("SFINCS output is missing the completed event/maxima")
        data = (
            ds.zsmax.max("timemax", skipna=True)
            if "timemax" in ds.zsmax.dims
            else ds.zsmax
        )
        if "nmesh2d_face" in data.dims:
            x, y = ds.mesh2d_face_x.values, ds.mesh2d_face_y.values
            water = np.full(grid.shape, np.nan)
            cols = np.floor((x - grid.transform.c) / grid.transform.a).astype(int)
            rows = np.floor((y - grid.transform.f) / grid.transform.e).astype(int)
            water[rows, cols] = data.values
        else:
            water = np.flipud(data.transpose("n", "m").values)
        # Native SFINCS writes its declared fill sentinel in active cells whose
        # maximum depth never exceeds huthresh. This is solver dry censoring,
        # distinct from supplied raster NoData and from non-finite solver errors.
        sentinel = ds.zsmax.attrs.get("_FillValue")
        if sentinel is not None:
            censored = (water == sentinel) & (mask == 1)
            bed = np.flipud(ds.zb.transpose("n", "m").values)
            if not np.isfinite(bed[mask == 1]).all() or not np.allclose(
                bed[mask == 1], grid.values[mask == 1], atol=1e-4
            ):
                raise RuntimeError(
                    "SFINCS output terrain does not match the prepared grid"
                )
            water[censored] = grid.values[censored]
        if water.shape != grid.shape or not np.isfinite(water[mask == 1]).all():
            raise RuntimeError(
                "SFINCS returned missing/non-finite maxima in active cells"
            )
        depth = np.maximum(water - grid.values, 0.0)
        expected = np.sum(
            rain.rates * np.diff(rain.edges_seconds)[:, None, None] / 3600, axis=0
        )
        if "cumprcp" not in ds or "nmesh2d_face" in data.dims:
            raise RuntimeError(
                "SFINCS output lacks a verifiable regular-grid rainfall accumulation"
            )
        actual = (
            np.flipud(ds.cumprcp.isel(timemax=-1).transpose("n", "m").values) * 1000
        )
        error = np.abs(actual - expected)
        if not np.isfinite(actual[mask == 1]).all() or np.any(
            error[mask == 1] > 0.5 + 0.02 * expected[mask == 1]
        ):
            raise RuntimeError(
                "SFINCS rainfall accumulation differs from prepared forcing; publication cancelled"
            )
        depth[mask != 1] = np.nan
        water[mask != 1] = np.nan
        return depth, water, float(error[mask == 1].max())
