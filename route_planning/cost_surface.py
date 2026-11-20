from __future__ import annotations

import numpy as np
import rasterio

from .models import PlanningConfig


def build_cost_surface(
    dem: rasterio.io.DatasetReader,
    sentinel2: rasterio.io.DatasetReader,
    config: PlanningConfig,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a positive per-cell traversal cost and a hard-blocked-cell mask.

    Sentinel-2 band 7 is SCL and band 8 is dataMask. DEM band 1 is elevation
    and band 2 is dataMask, matching the acquisition script's output schema.
    Water is excluded by default. Other SCL classes can be excluded through
    ``PlanningConfig``.
    """
    _require_aligned_grids(dem, sentinel2)
    if dem.count < 2 or sentinel2.count < 8:
        raise ValueError("Expected a two-band DEM and eight-band Sentinel-2 raster.")

    # Read elevation and acquisition validity masks. A cell must have valid
    # data in both sources so cost estimates are never made from missing pixels.
    elevation = dem.read(1).astype(np.float64, copy=False)
    dem_valid = (dem.read(2) > 0) & np.isfinite(elevation)
    if dem.nodata is not None:
        dem_valid &= elevation != dem.nodata

    scl = sentinel2.read(7)
    imagery_valid = (sentinel2.read(8) > 0) & np.isfinite(scl)
    blocked = ~(dem_valid & imagery_valid)
    if dem.nodata is not None:
        blocked |= elevation == dem.nodata
    for scl_class in config.impassable_scl_classes:
        blocked |= imagery_valid & (scl == scl_class)

    # pyastar2d uses equal-length grid directions, so require square, north-up
    # pixels. The acquisition module currently writes this raster geometry.
    x_resolution = abs(dem.transform.a)
    y_resolution = abs(dem.transform.e)
    if x_resolution <= 0 or y_resolution <= 0:
        raise ValueError("DEM pixel dimensions must be positive.")
    if abs(x_resolution - y_resolution) / max(x_resolution, y_resolution) > 0.01:
        raise ValueError("A* grid cells must be square; reproject rasters to a square grid first.")
    if abs(dem.transform.b) > 1e-9 or abs(dem.transform.d) > 1e-9:
        raise ValueError("Rotated rasters are not supported; reproject to a north-up grid first.")

    # Estimate local terrain steepness from elevation change per metre. These
    # derivatives use only valid neighbors, avoiding nodata values at edges.
    dz_dy = _axis_gradient(elevation, dem_valid, axis=0, spacing=y_resolution)
    dz_dx = _axis_gradient(elevation, dem_valid, axis=1, spacing=x_resolution)
    slope_degrees = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
    blocked |= ~np.isfinite(slope_degrees)
    blocked |= slope_degrees > config.max_slope_degrees

    # Keep every traversable cost >= 1 for pyastar2d's admissible heuristic;
    # the quadratic term makes steep-but-allowed cells less attractive.
    relative_slope = np.clip(slope_degrees / config.max_slope_degrees, 0.0, 1.0)
    traversable_cost = 1.0 + config.slope_cost_weight * np.square(relative_slope)
    costs = np.full(elevation.shape, np.inf, dtype=np.float32)
    costs[~blocked] = traversable_cost[~blocked].astype(np.float32)
    return np.ascontiguousarray(costs), blocked


def _axis_gradient(
    values: np.ndarray,
    valid: np.ndarray,
    axis: int,
    spacing: float,
) -> np.ndarray:
    """Compute one-axis elevation derivatives without sampling nodata cells.

    Central differences are used where both neighbors are valid; at data
    boundaries or nodata gaps, a one-sided difference is used instead.
    """
    previous = np.roll(values, 1, axis=axis)
    following = np.roll(values, -1, axis=axis)
    previous_valid = np.roll(valid, 1, axis=axis)
    following_valid = np.roll(valid, -1, axis=axis)

    if axis == 0:
        previous_valid[0, :] = False
        following_valid[-1, :] = False
    else:
        previous_valid[:, 0] = False
        following_valid[:, -1] = False

    gradient = np.zeros(values.shape, dtype=np.float64)
    both = valid & previous_valid & following_valid
    only_previous = valid & previous_valid & ~following_valid
    only_following = valid & ~previous_valid & following_valid
    gradient[both] = (following[both] - previous[both]) / (2 * spacing)
    gradient[only_previous] = (values[only_previous] - previous[only_previous]) / spacing
    gradient[only_following] = (following[only_following] - values[only_following]) / spacing
    return gradient


def _require_aligned_grids(
    first: rasterio.io.DatasetReader,
    second: rasterio.io.DatasetReader,
) -> None:
    """Ensure both inputs describe the same pixel locations before combining them."""
    if first.width != second.width or first.height != second.height:
        raise ValueError("DEM and Sentinel-2 rasters must have matching dimensions.")
    if first.crs != second.crs or not first.transform.almost_equals(second.transform):
        raise ValueError("DEM and Sentinel-2 rasters must share a CRS and pixel grid.")
