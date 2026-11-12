"""Accumulation-preserving rainfall forcing and bounded spatial reconstruction."""

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely.geometry import MultiPoint

from .grids import Grid, on_grid, validate_raster, write_grid

# Forcing provenance codes, also written to the report/manifest.
CODES = {
    0: "event",
    1: "interpolated",
    2: "extrapolated",
    3: "average",
    4: "assumed",
    5: "temporal_interpolation",
}


@dataclass
class Rainfall:
    edges_seconds: np.ndarray
    rates: np.ndarray  # interval-average mm/hour, (time, north-to-south y, x)
    codes: np.ndarray
    summary: dict


def fallback_rate(config, duration_hours):
    if config.average_value is None:
        return config.assumed_total_mm / duration_hours, 4
    if config.average_units in ("mm/month", "mm/year"):
        return config.climatology_event_total_mm / duration_hours, 3
    if config.average_units == "mm":
        return config.average_value / duration_hours, 3
    return config.average_value / (24 if config.average_units == "mm/day" else 1), 3


def _timestamps(frame):
    if frame.empty or "rain_mm" not in frame:
        raise ValueError(
            "rainfall CSV requires nonempty start_utc,end_utc,rain_mm records"
        )
    for key in ("start_utc", "end_utc"):
        if key not in frame:
            raise ValueError("rainfall CSV requires start_utc,end_utc,rain_mm")
        raw = frame[key].astype(str)
        if not raw.str.contains(r"(?:Z|[+-]\d\d:\d\d)$", regex=True).all():
            raise ValueError("rainfall timestamps require explicit UTC offsets")
        frame[key] = pd.to_datetime(raw, utc=True, errors="raise")
    if not (frame.end_utc > frame.start_utc).all():
        raise ValueError("rainfall accumulation intervals must have positive duration")
    frame["rain_mm"] = pd.to_numeric(frame.rain_mm, errors="raise")
    if np.isinf(frame.rain_mm).any() or (frame.rain_mm.dropna() < 0).any():
        raise ValueError(
            "rainfall must be finite nonnegative amounts or blank missing observations"
        )
    return frame


def _edges(duration, step):
    if not np.isfinite(duration) or not 0 < duration <= 744 * 3600:
        raise ValueError(
            "event rainfall window must be positive and no longer than 31 days"
        )
    result = np.arange(0, duration, step, dtype=float)
    return np.append(result, duration)


def validate_rainfall_inputs(config):
    """Validate declared observations even when a supplied depth raster is sufficient."""
    if config.raster:
        validate_raster(config.raster, nonnegative=True, units="mm")
    path = config.series or config.stations
    if path:
        frame = _timestamps(pd.read_csv(path))
        if config.stations:
            if (
                not {"station_id", "x", "y"} <= set(frame)
                or frame.station_id.isna().any()
            ):
                raise ValueError("station CSV requires nonempty station_id,x,y")
            locations = frame[["station_id", "x", "y"]].drop_duplicates()
            if (
                locations.station_id.duplicated().any()
                or locations[["x", "y"]].duplicated().any()
                or not np.isfinite(locations[["x", "y"]].to_numpy(float)).all()
            ):
                raise ValueError(
                    "station coordinates must be finite, unique, and fixed per station"
                )
            from pyproj import CRS

            CRS(config.station_crs)
            groups = [rows for _, rows in frame.groupby("station_id")]
        else:
            groups = [frame]
        for rows in groups:
            ordered = rows.sort_values("start_utc")
            if np.any(
                ordered.start_utc.iloc[1:].to_numpy()
                < ordered.end_utc.iloc[:-1].to_numpy()
            ):
                raise ValueError("overlapping rainfall intervals at one station/source")
        _edges(
            (frame.end_utc.max() - frame.start_utc.min()).total_seconds(),
            config.interval_minutes * 60,
        )
    if config.netcdf:
        from rasterio.transform import from_origin

        _netcdf(
            config,
            Grid(np.ones((2, 2)), from_origin(0, 40, 20, 20), "EPSG:32644"),
            100_000_000,
        )


def rebin_intervals(starts, ends, amounts, edges):
    """Conserve observed mm; expose uncovered duration rather than treating it as zero."""
    order = np.argsort(starts)
    starts, ends, amounts = (
        np.asarray(starts)[order],
        np.asarray(ends)[order],
        np.asarray(amounts)[order],
    )
    if np.any(starts[1:] < ends[:-1] - 1e-8):
        raise ValueError("overlapping rainfall intervals at one station/source")
    mm, known = np.zeros(len(edges) - 1), np.zeros(len(edges) - 1)
    for a, b, amount in zip(starts, ends, amounts):
        if not np.isfinite(amount):
            continue
        overlap = np.maximum(0, np.minimum(edges[1:], b) - np.maximum(edges[:-1], a))
        mm += amount * overlap / (b - a)
        known += overlap
    duration = np.diff(edges)
    rates = np.divide(mm * 3600, known, out=np.full(mm.shape, np.nan), where=known > 0)
    complete = known >= duration - 1e-7
    codes = np.zeros(len(rates), dtype="uint8")
    # Only a single entirely missing interior interval may be reconstructed in time.
    original = rates.copy()
    for j in range(1, len(rates) - 1):
        if known[j] == 0 and complete[j - 1] and complete[j + 1]:
            mids = (edges[:-1] + edges[1:]) / 2
            rates[j] = np.interp(
                mids[j], [mids[j - 1], mids[j + 1]], [original[j - 1], original[j + 1]]
            )
            known[j] = duration[j]
            codes[j] = 5
    return mm, known, rates, codes


def _idw(xy, values, targets):
    distances, indices = cKDTree(xy).query(targets, k=min(8, len(xy)))
    if distances.ndim == 1:
        distances, indices = distances[:, None], indices[:, None]
    weights = 1 / np.maximum(distances, 1e-9) ** 2
    predicted = (weights * values[indices]).sum(axis=1) / weights.sum(axis=1)
    exact = distances[:, 0] < 1e-8
    predicted[exact] = values[indices[exact, 0]]
    return predicted, distances[:, 0]


def _kriging(xy, values, targets):
    try:
        from pykrige.ok import OrdinaryKriging
    except ImportError as exc:
        raise RuntimeError(
            "kriging requires the optional closure-simulation dependencies"
        ) from exc
    model = OrdinaryKriging(
        xy[:, 0],
        xy[:, 1],
        values,
        variogram_model="spherical",
        nlags=6,
        exact_values=True,
        pseudo_inv=True,
        verbose=False,
    )
    parameters = np.asarray(model.variogram_model_parameters)
    if not np.isfinite(parameters).all() or parameters[0] <= 0 or parameters[1] <= 0:
        raise ValueError("unstable rainfall variogram")
    result, variance = model.execute(
        "points",
        targets[:, 0],
        targets[:, 1],
        backend="loop",
        n_closest_points=min(20, len(xy)),
    )
    result, variance = np.asarray(result), np.asarray(variance)
    if (
        np.any(~np.isfinite(result))
        or np.any(~np.isfinite(variance))
        or np.any(variance < -1e-8)
    ):
        raise ValueError("invalid kriging predictions/variance")
    return np.maximum(0, result)


def interpolate_stations(xy, values, targets, config):
    """Choose a method by held-out locations; extrapolate only within explicit bounds."""
    if len(xy) == 0:
        return (
            np.full(len(targets), np.nan),
            np.full(len(targets), 255, dtype="uint8"),
            np.full(len(targets), np.nan),
            {"method": "none"},
        )
    candidates = ["idw", "mean"]
    if len(xy) >= 10 and config.allow_kriging and np.ptp(values) > 0:
        candidates.append("kriging")
    scores, rejected = {}, {}
    if len(xy) >= 5:
        for method in candidates:
            errors = []
            try:
                for i in range(len(xy)):
                    keep = np.arange(len(xy)) != i
                    if method == "mean":
                        guess = values[keep].mean()
                    elif method == "idw":
                        guess = _idw(xy[keep], values[keep], xy[i : i + 1])[0][0]
                    else:
                        guess = _kriging(xy[keep], values[keep], xy[i : i + 1])[0]
                    errors.append((guess - values[i]) ** 2)
                scores[method] = float(np.sqrt(np.mean(errors)))
            except (ValueError, RuntimeError, np.linalg.LinAlgError) as exc:
                rejected[method] = str(exc)
                continue
    method = (
        min(scores, key=lambda key: (scores[key], candidates.index(key)))
        if scores
        else "idw"
    )
    predicted, nearest = _idw(xy, values, targets)
    hull = MultiPoint(xy).convex_hull
    outside_distance = shapely.distance(shapely.points(targets), hull)
    inside = outside_distance <= 1e-7
    supported = nearest <= config.support_distance_m
    if len(xy) > 1:
        supported &= inside | (outside_distance <= config.extrapolation_distance_m)
    if method == "mean":
        predicted[inside] = np.mean(values)
    elif method == "kriging":
        try:
            predicted[inside] = (
                _kriging(xy, values, targets[inside])
                if inside.any()
                else predicted[inside]
            )
        except (ValueError, np.linalg.LinAlgError) as exc:
            # A selected method failing on its actual target grid is not a successful reconstruction.
            raise ValueError("selected rainfall kriging failed on target grid") from exc
    # Always preserve exact observations, including when CV selected a uniform mean.
    exact_dist, exact_ix = cKDTree(xy).query(targets)
    exact = exact_dist < 1e-7
    predicted[exact] = values[exact_ix[exact]]
    predicted[~supported] = np.nan
    codes = np.where(inside, 1, 2).astype("uint8")
    codes[exact] = 0
    if len(xy) == 1:
        codes[supported & ~exact] = 1
    codes[~supported] = 255
    return (
        predicted,
        codes,
        nearest,
        {
            "method": method,
            "stations": len(xy),
            "validation_rmse_mm_hour": scores,
            "ineligible_methods": rejected,
            "validation": "leave_one_location_out"
            if scores
            else "insufficient_stations",
            "single_station_uniformity_assumption": len(xy) == 1,
        },
    )


def _station_fields(frame, grid, config, max_values):
    frame = _timestamps(frame)
    required = {"station_id", "x", "y"}
    if not required <= set(frame):
        raise ValueError(
            "station CSV requires station_id,x,y,start_utc,end_utc,rain_mm"
        )
    if frame.station_id.isna().any():
        raise ValueError("station IDs must be nonempty")
    locations = frame[["station_id", "x", "y"]].drop_duplicates()
    if (
        locations.station_id.duplicated().any()
        or locations[["x", "y"]].duplicated().any()
    ):
        raise ValueError("station locations must be unique and fixed per station")
    coords = locations[["x", "y"]].to_numpy(dtype=float)
    if not np.isfinite(coords).all():
        raise ValueError("station coordinates must be finite")
    origin = frame.start_utc.min()
    duration = (frame.end_utc.max() - origin).total_seconds()
    # Retain source interval boundaries as well as requested time bins so
    # unequal station intervals cannot discard a partially observed bin.
    starts = (frame.start_utc - origin).dt.total_seconds().to_numpy()
    ends = (frame.end_utc - origin).dt.total_seconds().to_numpy()
    edges = np.unique(
        np.concatenate([_edges(duration, config.interval_minutes * 60), starts, ends])
    )
    _check_size(edges, grid, max_values)
    raw = np.full((len(edges) - 1, len(locations)), np.nan)
    temporal = np.zeros(raw.shape, dtype=bool)
    for j, station in enumerate(locations.station_id):
        rows = frame[frame.station_id == station]
        a = (rows.start_utc - origin).dt.total_seconds().to_numpy()
        b = (rows.end_utc - origin).dt.total_seconds().to_numpy()
        _, covered, rates, codes = rebin_intervals(a, b, rows.rain_mm.to_numpy(), edges)
        raw[:, j] = np.where(covered >= np.diff(edges) - 1e-7, rates, np.nan)
        temporal[:, j] = codes == 5
    transformer = Transformer.from_crs(config.station_crs, grid.crs, always_xy=True)
    xy = np.column_stack(transformer.transform(coords[:, 0], coords[:, 1]))
    rr, cc = np.indices(grid.shape)
    xx, yy = grid.transform * (cc + 0.5, rr + 0.5)
    targets = np.column_stack((xx.ravel(), yy.ravel()))
    fields, codes, distances, details = [], [], [], []
    for i in range(len(raw)):
        valid = np.isfinite(raw[i])
        predicted, code, nearest, detail = interpolate_stations(
            xy[valid], raw[i, valid], targets, config
        )
        detail["temporal_reconstruction_station_ids"] = (
            locations.loc[temporal[i], "station_id"].astype(str).tolist()
        )
        if temporal[i, valid].any():
            code[(code != 255) & (code != 2)] = 5
        fields.append(predicted.reshape(grid.shape))
        codes.append(code.reshape(grid.shape))
        distances.append(nearest.reshape(grid.shape))
        details.append(detail)
    return (
        edges,
        np.asarray(fields),
        np.asarray(codes),
        np.asarray(distances),
        details,
        origin.isoformat(),
    )


def _check_size(edges, grid, limit):
    if (len(edges) - 1) * grid.values.size > limit:
        raise ValueError(
            "rainfall forcing exceeds max_forcing_values; use coarser intervals/grid or increase limit"
        )


def _recover_gridded(field, grid, config):
    """Bounded IDW for incomplete gridded rain; grid pixels are not independent gauges."""
    finite = np.isfinite(field)
    codes = np.where(finite, 0, 255).astype("uint8")
    distance = np.where(finite, 0.0, np.nan)
    detail = {
        "method": "grid_bounded_idw",
        "validation": "no_independent_gauge_validation",
        "recovered_cells": 0,
        "single_pixel_uniformity_assumption": int(finite.sum()) == 1,
    }
    if finite.all() or not finite.any():
        return field, codes, distance, detail
    rr, cc = np.indices(field.shape)
    xx, yy = grid.transform * (cc + 0.5, rr + 0.5)
    xy = np.column_stack((xx[finite], yy[finite]))
    targets = np.column_stack((xx[~finite], yy[~finite]))
    predicted, nearest = _idw(xy, field[finite], targets)
    boundary = finite & ~ndimage.binary_erosion(finite)
    hull = MultiPoint(np.column_stack((xx[boundary], yy[boundary]))).convex_hull
    outside = shapely.distance(shapely.points(targets), hull)
    supported = (nearest <= config.support_distance_m) & (
        outside <= config.extrapolation_distance_m
    )
    result = field.copy()
    predicted[~supported] = np.nan
    result[~finite] = predicted
    codes[~finite] = np.where(supported, np.where(outside <= 1e-7, 1, 2), 255)
    distance[~finite] = nearest
    detail["recovered_cells"] = int(supported.sum())
    return result, codes, distance, detail


def prepare_rainfall(grid, config, directory, max_values, multiplier=1.0):
    """Resolve event observations, then average, then synthetic rainfall, cell by cell."""
    directory.mkdir(parents=True, exist_ok=True)
    edges = _edges(config.duration_hours * 3600, config.interval_minutes * 60)
    origin = "2000-01-01T00:00:00+00:00"
    details, support = [], None
    if config.stations:
        frame = pd.read_csv(config.stations)
        edges, rates, codes, support, details, origin = _station_fields(
            frame, grid, config, max_values
        )
    elif config.series:
        frame = _timestamps(pd.read_csv(config.series))
        if frame.empty:
            raise ValueError("rainfall CSV is empty")
        origin_time = frame.start_utc.min()
        origin = origin_time.isoformat()
        edges = _edges(
            (frame.end_utc.max() - origin_time).total_seconds(),
            config.interval_minutes * 60,
        )
        _check_size(edges, grid, max_values)
        mm, known, rate, temporal = rebin_intervals(
            (frame.start_utc - origin_time).dt.total_seconds().to_numpy(),
            (frame.end_utc - origin_time).dt.total_seconds().to_numpy(),
            frame.rain_mm.to_numpy(),
            edges,
        )
        fallback, code = fallback_rate(config, edges[-1] / 3600)
        duration = np.diff(edges)
        # Keep the known portion exactly; fill only the unobserved duration.
        total = mm + (duration - known) / 3600 * fallback
        reconstructed = temporal == 5
        total[reconstructed] = rate[reconstructed] * duration[reconstructed] / 3600
        rate = total / (duration / 3600)
        code_array = np.where(known < duration - 1e-7, code, temporal).astype("uint8")
        rates = np.broadcast_to(rate[:, None, None], (len(rate), *grid.shape)).copy()
        codes = np.broadcast_to(code_array[:, None, None], rates.shape).copy()
        details = [
            {
                "method": "temporal_overlap_rebin",
                "partly_observed_intervals": int(
                    ((known > 0) & (known < duration - 1e-7)).sum()
                ),
            }
        ]
    elif config.netcdf:
        edges, rates, codes, origin, details, support = _netcdf(
            config, grid, max_values
        )
    else:
        _check_size(edges, grid, max_values)
        rates = np.full((len(edges) - 1, *grid.shape), np.nan, dtype=float)
        codes = np.full(rates.shape, 255, dtype="uint8")
        if config.raster:
            validate_raster(config.raster, nonnegative=True, units="mm")
            total = on_grid(config.raster, grid)
            total, spatial_codes, distance, detail = _recover_gridded(
                total, grid, config
            )
            rates[:] = total / (edges[-1] / 3600)
            codes[:] = spatial_codes
            support = np.broadcast_to(distance, rates.shape)
            details = [detail]
    fallback, fallback_code = fallback_rate(config, edges[-1] / 3600)
    missing = ~np.isfinite(rates)
    rates[missing] = fallback
    codes[missing] = fallback_code
    rates *= multiplier
    if not np.isfinite(rates).all() or (rates < 0).any():
        raise ValueError("resolved rainfall must be finite and nonnegative")
    valid = np.isfinite(grid.values)
    used = set(map(int, np.unique(codes[:, valid])))
    if any(item.get("partly_observed_intervals", 0) for item in details):
        used.add(0)
    observed = bool(used & {0, 1, 2, 5})
    source = (
        "event"
        if used <= {0, 1, 2, 5}
        else "average"
        if used == {3}
        else "assumed"
        if used == {4}
        else "mixed"
    )
    totals = np.sum(rates * np.diff(edges)[:, None, None] / 3600, axis=0)
    summary = {
        "source": source,
        "scenario_kind": "observed"
        if observed and used <= {0, 1, 2, 5}
        else "representative"
        if used == {3}
        else "synthetic"
        if used == {4}
        else "mixed",
        "origin_utc": origin,
        "duration_hours": edges[-1] / 3600,
        "total_mm_min": float(totals[valid].min()),
        "total_mm_max": float(totals[valid].max()),
        "rainfall_multiplier": multiplier,
        "provenance_codes": CODES,
        "code_counts": {CODES[c]: int((codes[:, valid] == c).sum()) for c in used},
        "reconstruction": details,
        "support_distance_m": config.support_distance_m,
        "extrapolation_distance_m": config.extrapolation_distance_m,
    }
    write_grid(
        directory / "rainfall_total_mm.tif", Grid(totals, grid.transform, grid.crs)
    )
    write_grid(
        directory / "rainfall_provenance.tif",
        Grid(codes.max(axis=0).astype(float), grid.transform, grid.crs),
        dtype="uint8",
        nodata=255,
    )
    if support is not None:
        nearest = np.max(np.where(np.isfinite(support), support, -1), axis=0)
        nearest[nearest < 0] = np.nan
        write_grid(
            directory / "rainfall_support_m.tif",
            Grid(nearest, grid.transform, grid.crs),
        )
    # Retain per-interval provenance rather than only the summary map's maximum
    # code: the same cell can have different reconstruction methods over time.
    np.savez_compressed(
        directory / "resolved_rainfall.npz",
        edges_seconds=edges,
        rates_mm_hour=rates,
        provenance=codes,
        support_m=support if support is not None else np.empty(0),
    )
    (directory / "rainfall.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n"
    )
    return Rainfall(edges, rates, codes, summary)


def _netcdf(config, grid, max_values):
    try:
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError(
            "NetCDF rainfall requires the closure-simulation dependencies"
        ) from exc
    from affine import Affine

    with xr.open_dataset(config.netcdf) as ds:
        name = config.netcdf_variable
        if name not in ds or "time_bounds" not in ds:
            raise ValueError(
                "rainfall NetCDF requires configured variable and time_bounds(time,bounds)"
            )
        data = ds[name]
        if set(data.dims) != {"time", "y", "x"} or data.attrs.get("units") not in (
            "mm",
            "mm/hour",
        ):
            raise ValueError("NetCDF rainfall requires (time,y,x), units mm or mm/hour")
        crs = ds.attrs.get("crs")
        x, y = ds.x.values, ds.y.values
        if (
            crs is None
            or len(x) < 2
            or len(y) < 2
            or not np.isfinite(x).all()
            or not np.isfinite(y).all()
            or x[1] == x[0]
            or y[1] == y[0]
            or not np.allclose(np.diff(x), x[1] - x[0])
            or not np.allclose(np.diff(y), y[1] - y[0])
        ):
            raise ValueError(
                "NetCDF requires global crs and regular cell-centre x/y coordinates"
            )
        bounds = pd.to_datetime(ds.time_bounds.values.ravel(), utc=True).values.reshape(
            -1, 2
        )
        if (
            len(bounds) != data.sizes["time"]
            or len(bounds) == 0
            or np.isnat(bounds).any()
        ):
            raise ValueError(
                "NetCDF time_bounds must contain one finite interval per time frame"
            )
        origin = bounds[0, 0]
        starts = (bounds[:, 0] - origin) / np.timedelta64(1, "s")
        ends = (bounds[:, 1] - origin) / np.timedelta64(1, "s")
        if np.any(ends <= starts) or np.any(starts[1:] < ends[:-1]):
            raise ValueError("NetCDF rainfall bounds overlap or are unordered")
        edges = _edges(float(ends[-1]), config.interval_minutes * 60)
        _check_size(edges, grid, max_values)
        # Raster reprojection conserves the subsequent temporal accumulation accounting.
        from rasterio.enums import Resampling
        from rasterio.warp import reproject

        frames, spatial_codes, support, details = [], [], [], []
        for j in range(len(starts)):
            a = data.isel(time=j).transpose("y", "x").values.astype(float)
            if np.isinf(a).any() or np.any(a[np.isfinite(a)] < 0):
                raise ValueError("invalid NetCDF rainfall values")
            xx, yy = x.copy(), y.copy()
            if xx[1] < xx[0]:
                xx = xx[::-1]
                a = a[:, ::-1]
            if yy[1] > yy[0]:
                yy = yy[::-1]
                a = a[::-1, :]
            transform = Affine.translation(
                xx[0] - (xx[1] - xx[0]) / 2, yy[0] - (yy[1] - yy[0]) / 2
            ) * Affine.scale(xx[1] - xx[0], yy[1] - yy[0])
            target = np.full(grid.shape, np.nan)
            reproject(
                a,
                target,
                src_transform=transform,
                src_crs=crs,
                src_nodata=np.nan,
                dst_transform=grid.transform,
                dst_crs=grid.crs,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
            target, code, distance, detail = _recover_gridded(target, grid, config)
            frames.append(
                target
                if data.attrs["units"] == "mm"
                else target * (ends[j] - starts[j]) / 3600
            )
            spatial_codes.append(code)
            support.append(distance)
            details.append(detail)
        frames = np.asarray(frames)
        mm = np.zeros((len(edges) - 1, *grid.shape))
        known = np.zeros_like(mm)
        codes = np.zeros_like(mm, dtype="uint8")
        distances = np.full_like(mm, np.nan)
        for a, b, frame, source_codes, source_distances in zip(
            starts, ends, frames, spatial_codes, support
        ):
            overlap = np.maximum(
                0, np.minimum(edges[1:], b) - np.maximum(edges[:-1], a)
            )[:, None, None]
            finite = np.isfinite(frame)
            mm += np.where(finite, frame, 0)[None, :, :] * overlap / (b - a)
            known += finite[None, :, :] * overlap
            affected = (overlap > 0) & finite[None, :, :]
            codes = np.maximum(codes, np.where(affected, source_codes[None, :, :], 0))
            distances = np.fmax(
                distances, np.where(affected, source_distances[None, :, :], np.nan)
            )
        duration = np.diff(edges)[:, None, None]
        # Only isolated entirely missing intervals bounded by complete frames.
        complete = known >= duration - 1e-7
        original_rates = np.divide(
            mm * 3600, known, out=np.full_like(mm, np.nan), where=known > 0
        )
        mids = (edges[:-1] + edges[1:]) / 2
        for j in range(1, len(mm) - 1):
            isolated = (known[j] == 0) & complete[j - 1] & complete[j + 1]
            weight = (mids[j] - mids[j - 1]) / (mids[j + 1] - mids[j - 1])
            prediction = (
                original_rates[j - 1] * (1 - weight) + original_rates[j + 1] * weight
            )
            mm[j, isolated] = prediction[isolated] * duration[j, 0, 0] / 3600
            known[j, isolated] = duration[j, 0, 0]
            codes[j, isolated] = 5
            distances[j, isolated] = np.fmax(distances[j - 1], distances[j + 1])[
                isolated
            ]
        fallback, code = fallback_rate(config, edges[-1] / 3600)
        rates = (mm + (duration - known) / 3600 * fallback) / (duration / 3600)
        codes = np.where(known < duration - 1e-7, code, codes).astype("uint8")
        details.append(
            {
                "method": "temporal_overlap_rebin",
                "partly_observed_intervals": int(
                    ((known > 0) & (known < duration - 1e-7)).sum()
                ),
            }
        )
        return (
            edges,
            rates,
            codes,
            str(pd.Timestamp(origin).tz_localize("UTC")),
            details,
            distances,
        )
