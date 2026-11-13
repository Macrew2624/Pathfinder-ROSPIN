from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import rowcol, xy

from .cost_surface import build_cost_surface
from .models import PlanningConfig, RouteResult
from .strategies import create_strategy
from .strategies.registry import available_strategies

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def plan_route(
    dem_path: Path | str = PROJECT_ROOT / "data" / "copernicus_dem_glo30.tif",
    sentinel2_path: Path | str = PROJECT_ROOT / "data" / "sentinel2_l2a.tif",
    endpoints_path: Path | str = PROJECT_ROOT / "data" / "road_endpoints.geojson",
    output_path: Path | str = PROJECT_ROOT / "route_planning" / "output" / "planned_route.geojson",
    strategy_name: str = "astar",
    config: PlanningConfig | None = None,
) -> RouteResult:
    """Plan a route from acquisition outputs and save a GeoJSON LineString.

    This function coordinates I/O, shared terrain constraints, strategy
    selection, output conversion, and summary metrics. Search itself stays in
    the selected strategy implementation.
    """
    config = config or PlanningConfig()
    strategy = create_strategy(strategy_name)
    start_lonlat, end_lonlat = _read_endpoints(Path(endpoints_path))

    # Open both rasters together so they are closed reliably after planning,
    # including when validation or route search raises an error.
    with rasterio.open(dem_path) as dem, rasterio.open(sentinel2_path) as sentinel2:
        costs, blocked = build_cost_surface(dem, sentinel2, config)
        start_rc = _point_to_cell(dem, start_lonlat)
        end_rc = _point_to_cell(dem, end_lonlat)
        _check_endpoint("start", start_rc, blocked)
        _check_endpoint("end", end_rc, blocked)

        path_rc = strategy.find_path(costs, start_rc, end_rc)
        if len(path_rc) == 0:
            raise RuntimeError("No route found between the endpoints under the current constraints.")

        weighted_cost, length_m = _path_metrics(path_rc, costs, dem.res)
        output_geometry = _path_to_wgs84(path_rc, dem, start_lonlat, end_lonlat)
        result = RouteResult(
            path_rc=path_rc,
            strategy=strategy.name,
            weighted_cost=weighted_cost,
            length_m=length_m,
        )

    _write_route(Path(output_path), output_geometry, result, config)
    return result


def _read_endpoints(path: Path) -> tuple[tuple[float | int, ...], tuple[float | int, ...]]:
    """Load the acquisition GeoJSON and return its WGS84 start/end points."""
    document = json.loads(path.read_text(encoding="utf-8"))
    geometry: Any = document.get("geometry")
    if document.get("type") == "Feature":
        geometry = document.get("geometry", {})
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        raise ValueError("Endpoint GeoJSON must contain a LineString with exactly two coordinates.")
    coordinates = geometry.get("coordinates", [])
    if len(coordinates) != 2:
        raise ValueError("Endpoint LineString must contain exactly two coordinates.")
    start = tuple(float(value) for value in coordinates[0][:2])
    end = tuple(float(value) for value in coordinates[1][:2])
    if not all(math.isfinite(value) for value in (*start, *end)):
        raise ValueError("Endpoint coordinates must be finite numbers.")
    return start, end


def _point_to_cell(
    dataset: rasterio.io.DatasetReader,
    point_lonlat: tuple[float, float],
) -> tuple[int, int]:
    """Project a WGS84 endpoint and locate its containing raster cell."""
    to_raster_crs = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True)
    x_coord, y_coord = to_raster_crs.transform(*point_lonlat)
    row, col = rowcol(dataset.transform, x_coord, y_coord)
    if not (0 <= row < dataset.height and 0 <= col < dataset.width):
        raise ValueError(f"Endpoint {point_lonlat} lies outside the raster coverage.")
    return int(row), int(col)


def _check_endpoint(name: str, cell: tuple[int, int], blocked: np.ndarray) -> None:
    """Fail early when an endpoint lands outside valid traversable terrain."""
    if blocked[cell]:
        raise ValueError(
            f"The {name} endpoint falls on an impassable or invalid cell. "
            "Move it to a traversable location or adjust the constraints."
        )


def _path_metrics(
    path_rc: np.ndarray,
    costs: np.ndarray,
    resolution: tuple[float, float],
) -> tuple[float, float]:
    """Measure path distance and integrated relative cost along grid edges.

    Each edge uses the average cost of its two cells multiplied by its physical
    length, including the longer diagonal steps in an 8-connected path.
    """
    if len(path_rc) < 2:
        return 0.0, 0.0
    weighted_cost = 0.0
    length_m = 0.0
    x_resolution, y_resolution = abs(resolution[0]), abs(resolution[1])
    for first, second in zip(path_rc[:-1], path_rc[1:]):
        row_delta = int(second[0] - first[0])
        col_delta = int(second[1] - first[1])
        step_length = math.hypot(row_delta * y_resolution, col_delta * x_resolution)
        average_cost = (float(costs[tuple(first)]) + float(costs[tuple(second)])) / 2.0
        weighted_cost += average_cost * step_length
        length_m += step_length
    return weighted_cost, length_m


def _path_to_wgs84(
    path_rc: np.ndarray,
    dem: rasterio.io.DatasetReader,
    start_lonlat: tuple[float, float],
    end_lonlat: tuple[float, float],
) -> list[list[float]]:
    """Convert cell centers to WGS84 and retain the user's exact endpoints."""
    to_wgs84 = Transformer.from_crs(dem.crs, "EPSG:4326", always_xy=True)
    coordinates: list[list[float]] = []
    for row, col in path_rc:
        x_coord, y_coord = xy(dem.transform, int(row), int(col), offset="center")
        lon, lat = to_wgs84.transform(x_coord, y_coord)
        coordinates.append([lon, lat])
    if coordinates:
        coordinates[0] = [start_lonlat[0], start_lonlat[1]]
        coordinates[-1] = [end_lonlat[0], end_lonlat[1]]
    else:
        coordinates = [list(start_lonlat), list(end_lonlat)]
    if len(coordinates) == 1:
        coordinates.append(list(end_lonlat))
    return coordinates


def _write_route(
    path: Path,
    coordinates: list[list[float]],
    result: RouteResult,
    config: PlanningConfig,
) -> None:
    """Write route geometry and planning settings as a GeoJSON Feature."""
    path.parent.mkdir(parents=True, exist_ok=True)
    feature = {
        "type": "Feature",
        "properties": {
            "strategy": result.strategy,
            "length_m": round(result.length_m, 2),
            "weighted_cost": round(result.weighted_cost, 2),
            "max_slope_degrees": config.max_slope_degrees,
            "slope_cost_weight": config.slope_cost_weight,
            "impassable_scl_classes": sorted(config.impassable_scl_classes),
        },
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }
    path.write_text(json.dumps(feature, indent=2) + "\n", encoding="utf-8")


def strategy_names() -> tuple[str, ...]:
    """Expose registered strategies to command-line argument parsing."""
    return available_strategies()
