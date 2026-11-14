"""Raster contracts, bounded recovery, and exact line/cell coverage accounting."""

import itertools
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject
from rasterio.windows import Window
from scipy import ndimage
from scipy.interpolate import LinearNDInterpolator
from shapely.geometry import LineString


class TerrainUnavailable(ValueError):
    """Valid terrain metadata, but insufficient physical coverage to run a solver."""


@dataclass
class Grid:
    values: np.ndarray
    transform: object
    crs: object

    @property
    def shape(self):
        return self.values.shape


def validate_raster(path, *, nonnegative=False, categorical=False, units=None):
    with rasterio.open(path) as ds:
        if ds.crs is None or ds.count != 1 or ds.width == 0 or ds.height == 0:
            raise ValueError(f"{path}: requires one georeferenced raster band")
        if (
            not ds.transform.is_rectilinear
            or ds.transform.a <= 0
            or ds.transform.e >= 0
        ):
            raise ValueError(
                f"{path}: requires a north-up raster with positive pixel sizes"
            )
        declared = ds.units[0] or ds.tags(1).get("units") or ds.tags().get("units")
        aliases = {
            "m": {"m", "meter", "meters", "metre", "metres"},
            "mm": {"mm", "millimeter", "millimeters", "millimetre", "millimetres"},
        }
        if units and declared and declared.strip().lower() not in aliases[units]:
            raise ValueError(
                f"{path}: declared raster units conflict with required {units}"
            )
        for _, window in ds.block_windows(1):
            block = ds.read(1, window=window, masked=True)
            valid = block.compressed()
            if np.any(~np.isfinite(valid)):
                raise ValueError(f"{path}: non-finite values must be declared NoData")
            if nonnegative and np.any(valid < 0):
                raise ValueError(f"{path}: negative values are invalid")
            if categorical and np.any(valid != np.floor(valid)):
                raise ValueError(f"{path}: category codes must be integers")


def read_grid(path, max_cells=4_000_000):
    with rasterio.open(path) as ds:
        if ds.width * ds.height > max_cells:
            raise ValueError(
                f"{path}: exceeds max_cells; provide a smaller hydrologic domain or increase the limit"
            )
        return Grid(
            ds.read(1, masked=True).astype(float).filled(np.nan), ds.transform, ds.crs
        )


def on_grid(path, grid, *, categorical=False):
    """Resample without inventing values outside the supplied source footprint."""
    result = np.full(grid.shape, np.nan, dtype=float)
    with rasterio.open(path) as ds:
        reproject(
            rasterio.band(ds, 1),
            result,
            src_transform=ds.transform,
            src_crs=ds.crs,
            src_nodata=ds.nodata,
            dst_transform=grid.transform,
            dst_crs=grid.crs,
            dst_nodata=np.nan,
            resampling=Resampling.nearest if categorical else Resampling.bilinear,
        )
    return result


def write_grid(path, grid, *, dtype="float32", nodata=-9999):
    values = np.where(np.isfinite(grid.values), grid.values, nodata).astype(dtype)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype=dtype,
        crs=grid.crs,
        transform=grid.transform,
        nodata=nodata,
        compress="deflate",
    ) as ds:
        ds.write(values, 1)


def recovery_distances(values, changed, transform, crs):
    """Nearest original support distance; geographic grids use local geodesic scale."""
    if not changed.any():
        return np.full(values.shape, np.nan)
    crs = CRS(crs)
    dx, dy = abs(transform.a), abs(transform.e)
    if crs.is_projected:
        factors = crs.axis_info
        dx *= factors[0].unit_conversion_factor
        dy *= factors[1].unit_conversion_factor
    else:
        x, y = transform * (values.shape[1] / 2, values.shape[0] / 2)
        geod = crs.get_geod()
        dx = abs(geod.inv(x - dx / 2, y, x + dx / 2, y)[2])
        dy = abs(geod.inv(x, y - dy / 2, x, y + dy / 2)[2])
    distance = ndimage.distance_transform_edt(~np.isfinite(values), sampling=(dy, dx))
    return np.where(changed, distance, np.nan)


def fill_small_holes(
    values, max_width=3, zones=None, categorical=False, wet_values=None
):
    """Only enclosed <=3x3 holes; optional positive, explicit hydraulic partitions."""
    result = values.copy()
    recovered = np.zeros(values.shape, dtype=bool)
    missing = ~np.isfinite(values)
    labels, _ = ndimage.label(missing)
    for label, slices in enumerate(ndimage.find_objects(labels), 1):
        if slices is None:
            continue
        r, c = slices
        if (
            r.start == 0
            or c.start == 0
            or r.stop == values.shape[0]
            or c.stop == values.shape[1]
        ):
            continue
        if r.stop - r.start > max_width or c.stop - c.start > max_width:
            continue
        box = (slice(r.start - 1, r.stop + 1), slice(c.start - 1, c.stop + 1))
        hole = labels[box] == label
        local = values[box]
        ring = ndimage.binary_dilation(hole) & ~hole
        if not np.all(np.isfinite(local[ring])):
            continue
        if zones is not None:
            z = zones[box]
            ids = z[hole | ring]
            if (
                np.any(~np.isfinite(ids))
                or np.any(ids <= 0)
                or len(np.unique(ids)) != 1
            ):
                continue
            wet = local if wet_values is None else wet_values[box]
            if not categorical and (
                np.any(~np.isfinite(wet[ring])) or np.any(wet[ring] <= 0)
            ):
                # Explicit dry cells are not evidence for a connected flooded gap.
                continue
        rr, cc = np.nonzero(ring)
        target = np.column_stack(np.nonzero(hole))
        if categorical:
            from scipy.spatial import cKDTree

            _, ix = cKDTree(np.column_stack((rr, cc))).query(target)
            predicted = local[ring][ix]
        else:
            predicted = LinearNDInterpolator(np.column_stack((rr, cc)), local[ring])(
                target
            )
        if np.any(~np.isfinite(predicted)):
            continue
        sub = result[box]
        sub[hole] = predicted
        recovered[box] |= hole
    return result, recovered


def recover_raster(
    source,
    destination,
    mask_path,
    *,
    zones_path=None,
    categorical=False,
    elevation_path=None,
    water_surface=False,
):
    """Windowed recovery with a halo; never fills missing regions touching a tile halo."""
    with rasterio.open(source) as src:
        profile = src.profile.copy()
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
        precision = "float64" if np.dtype(src.dtypes[0]).itemsize > 4 else "float32"
        profile.update(
            driver="GTiff", dtype=precision, nodata=-9999, compress="deflate"
        )
        mask_profile = profile | {"dtype": "uint8", "nodata": 255}
        support_path = Path(mask_path).with_name(
            Path(mask_path).stem + "_support_m.tif"
        )
        count = 0
        with (
            rasterio.open(destination, "w", **profile) as dst,
            rasterio.open(mask_path, "w", **mask_profile) as masks,
            rasterio.open(support_path, "w", **profile) as supports,
        ):
            for r in range(0, src.height, 256):
                for c in range(0, src.width, 256):
                    window = Window(
                        c, r, min(256, src.width - c), min(256, src.height - r)
                    )
                    halo = Window(
                        max(0, c - 4),
                        max(0, r - 4),
                        min(src.width, c + window.width + 4) - max(0, c - 4),
                        min(src.height, r + window.height + 4) - max(0, r - 4),
                    )
                    data = (
                        src.read(1, window=halo, masked=True)
                        .astype(float)
                        .filled(np.nan)
                    )
                    zone_values = None
                    if zones_path:
                        local_grid = Grid(data, src.window_transform(halo), src.crs)
                        zone_values = on_grid(zones_path, local_grid, categorical=True)
                    ground = (
                        on_grid(
                            elevation_path,
                            Grid(data, src.window_transform(halo), src.crs),
                        )
                        if elevation_path
                        else None
                    )
                    if ground is not None:
                        level = data if water_surface else data + ground
                        wet = data - ground if water_surface else data
                        candidate, changed = fill_small_holes(
                            level,
                            zones=zone_values,
                            categorical=categorical,
                            wet_values=wet,
                        )
                        changed &= np.isfinite(ground)
                        filled = data.copy()
                        filled[changed] = (
                            candidate[changed]
                            if water_surface
                            else np.maximum(0, candidate[changed] - ground[changed])
                        )
                    else:
                        filled, changed = fill_small_holes(
                            data, zones=zone_values, categorical=categorical
                        )
                    crop = (
                        slice(
                            int(r - halo.row_off),
                            int(r - halo.row_off + window.height),
                        ),
                        slice(
                            int(c - halo.col_off),
                            int(c - halo.col_off + window.width),
                        ),
                    )
                    dst.write(
                        np.where(np.isfinite(filled[crop]), filled[crop], -9999).astype(
                            precision
                        ),
                        1,
                        window=window,
                    )
                    masks.write(changed[crop].astype("uint8"), 1, window=window)
                    distances = recovery_distances(
                        data, changed, src.window_transform(halo), src.crs
                    )[crop]
                    supports.write(
                        np.where(np.isfinite(distances), distances, -9999).astype(
                            "float32"
                        ),
                        1,
                        window=window,
                    )
                    count += int(changed[crop].sum())
    return count


class RasterSampler:
    """Small LRU tile cache; no full raster allocation for long road networks."""

    def __init__(self, path):
        self.dataset = rasterio.open(path)
        self.transform = self.dataset.transform
        self.crs = self.dataset.crs
        self._cached = lru_cache(maxsize=64)(self._block)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._cached.cache_clear()
        self.dataset.close()

    def _block(self, br, bc):
        return self.dataset.read(
            1, window=Window(bc * 256, br * 256, 256, 256), masked=True
        )

    def value(self, row, col):
        if not (0 <= row < self.dataset.height and 0 <= col < self.dataset.width):
            return None
        v = self._cached(row // 256, col // 256)[row % 256, col % 256]
        return None if np.ma.is_masked(v) or not np.isfinite(v) else float(v)

    def at_xy(self, x, y, crs):
        if CRS(crs) != self.crs:
            x, y = Transformer.from_crs(crs, self.crs, always_xy=True).transform(x, y)
        col, row = ~self.transform * (x, y)
        return self.value(math.floor(row), math.floor(col))


def line_cells(geometry, source_crs, sampler, metric_crs, additional_samplers=()):
    """Split every segment at grid crossings; yield pixel and actual projected length.

    Zero-length corner touches contribute nothing; a line exactly on a cell edge
    belongs to the cell selected by floor(midpoint), consistently across runs.
    """
    project = Transformer.from_crs(source_crs, sampler.crs, always_xy=True)
    metric = Transformer.from_crs(sampler.crs, metric_crs, always_xy=True)
    inv = ~sampler.transform
    secondary = [
        (other, Transformer.from_crs(sampler.crs, other.crs, always_xy=True))
        for other in additional_samplers
        if other is not sampler
    ]
    parts = geometry.geoms if geometry.geom_type == "MultiLineString" else [geometry]
    for part in parts:
        xy = [project.transform(*coord[:2]) for coord in part.coords]
        for a, b in itertools.pairwise(xy):
            ax, ay = inv * a
            bx, by = inv * b
            cuts = [0.0, 1.0]
            axes = [(ax, bx, sampler.dataset.width), (ay, by, sampler.dataset.height)]
            for other, project_other in secondary:
                ox, oy = ~other.transform * project_other.transform(*a)
                px, py = ~other.transform * project_other.transform(*b)
                axes.extend(
                    [(ox, px, other.dataset.width), (oy, py, other.dataset.height)]
                )
            for v0, v1, bound in axes:
                if abs(v1 - v0) > 1e-12:
                    # Include only crossings within raster extent; outside portions still count.
                    lower, upper = (
                        max(0, math.ceil(min(v0, v1))),
                        min(bound, math.floor(max(v0, v1))),
                    )
                    cuts.extend(
                        (k - v0) / (v1 - v0)
                        for k in range(lower, upper + 1)
                        if 0 < (k - v0) / (v1 - v0) < 1
                    )
            cuts = sorted(set(cuts))
            for lo, hi in itertools.pairwise(cuts):
                mid = (lo + hi) / 2
                col, row = (
                    math.floor(ax + (bx - ax) * mid),
                    math.floor(ay + (by - ay) * mid),
                )
                p = (a[0] + (b[0] - a[0]) * lo, a[1] + (b[1] - a[1]) * lo)
                q = (a[0] + (b[0] - a[0]) * hi, a[1] + (b[1] - a[1]) * hi)
                length = LineString([metric.transform(*p), metric.transform(*q)]).length
                if length > 0:
                    cx, cy = a[0] + (b[0] - a[0]) * mid, a[1] + (b[1] - a[1]) * mid
                    yield row, col, length, cx, cy


def simulation_grid(
    dem_path, config, metric_crs, destination, recovery_path, domain=None
):
    validate_raster(dem_path)
    # Enforce the three-cell rule on the source terrain, before any coarsening.
    # Otherwise a large native gap could shrink to a "small" computational hole.
    prepared = Path(destination).with_name("source_dem_recovered.tif")
    source_mask = Path(recovery_path).with_name("source_terrain_reconstruction.tif")
    native_filled = recover_raster(dem_path, prepared, source_mask)
    with rasterio.open(prepared) as src:
        native, _, _ = calculate_default_transform(
            src.crs, metric_crs, src.width, src.height, *src.bounds
        )
        resolution = config.resolution_m or max(20.0, abs(native.a), abs(native.e))
        shapes = None
        domain_clipped = False
        if domain is not None:
            import geopandas as gpd
            from rasterio.features import geometry_mask
            from rasterio.transform import from_origin
            from rasterio.warp import transform_bounds

            shapes = gpd.read_file(domain)
            if (
                shapes.empty
                or shapes.crs is None
                or not shapes.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
                or not shapes.is_valid.all()
            ):
                raise ValueError("domain requires valid georeferenced polygons")
            shapes = shapes.to_crs(metric_crs)
            left, bottom, right, top = shapes.total_bounds
            dl, db, dr, dt = transform_bounds(src.crs, metric_crs, *src.bounds)
            domain_clipped = left < dl or bottom < db or right > dr or top > dt
            left, bottom, right, top = (
                max(left, dl),
                max(bottom, db),
                min(right, dr),
                min(top, dt),
            )
            if left >= right or bottom >= top:
                raise ValueError("hydrologic domain does not overlap DEM")
            transform = from_origin(left, top, resolution, resolution)
            width, height = (
                math.ceil((right - left) / resolution),
                math.ceil((top - bottom) / resolution),
            )
        else:
            transform, width, height = calculate_default_transform(
                src.crs,
                metric_crs,
                src.width,
                src.height,
                *src.bounds,
                resolution=resolution,
            )
        if width * height > config.max_cells:
            raise ValueError(
                "simulation grid exceeds max_cells; supply a hydrologic domain/coarser resolution or increase limit"
            )
        grid = Grid(np.full((height, width), np.nan), transform, metric_crs)
        grid.values = on_grid(prepared, grid)
        from rasterio.vrt import WarpedVRT

        with WarpedVRT(
            src,
            crs=metric_crs,
            transform=transform,
            width=width,
            height=height,
            resampling=Resampling.nearest,
        ) as vrt:
            grid.values[np.ma.getmaskarray(vrt.read(1, masked=True))] = np.nan
    filled = on_grid(source_mask, grid, categorical=True) == 1
    inside = np.ones(grid.shape, dtype=bool)
    if domain is not None:
        inside = geometry_mask(shapes.geometry, grid.shape, transform, invert=True)
        grid.values[~inside] = np.nan
        filled &= inside
    if np.isfinite(grid.values).sum() < 9:
        raise TerrainUnavailable(
            "DEM/domain has fewer than nine usable computational cells"
        )
    write_grid(destination, grid)
    write_grid(
        recovery_path,
        Grid(filled.astype(float), transform, metric_crs),
        dtype="uint8",
        nodata=255,
    )
    return grid, {
        "filled_terrain_cells": native_filled,
        "filled_computational_cells": int(filled.sum()),
        "resolution_m": resolution,
        "incomplete_terrain": bool(
            domain_clipped or np.any(~np.isfinite(grid.values) & inside)
        ),
        "domain_clipped_to_dem": bool(domain_clipped),
        "domain": "supplied" if domain else "DEM footprint",
    }
