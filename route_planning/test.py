"""Quick interactive 3D visualization for testing route planning."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import to_rgba
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from rasterio.transform import xy

from route_planning import PlanningConfig, RouteResult
from route_planning.planner import PROJECT_ROOT, plan_route_from_endpoints

DEFAULT_ENDPOINTS_PATH = PROJECT_ROOT / "data" / "road_endpoints.geojson"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "route_planning" / "output" / "planned_route.geojson"

DEFAULT_SCL_COLORS: dict[int, str] = {
    0: "#4c4c4c",
    1: "#d73027",
    2: "#fdae61",
    3: "#8c510a",
    4: "#1a9850",
    5: "#91cf60",
    6: "#4575b4",
    7: "#bdbdbd",
    8: "#fee08b",
    9: "#f46d43",
    10: "#74add1",
    11: "#762a83",
}


def run_planning_test(
        start_endpoint: Sequence[float],
        end_endpoint: Sequence[float],
        *,
        class_colors: Mapping[int, str] | None = None,
        route_color: str = "#ff00ff",
        sampling_stride: int = 10,
        route_elevation_offset_m: float = 0.0,
        dem_path: Path | str = PROJECT_ROOT / "data" / "copernicus_dem_glo30.tif",
        sentinel2_path: Path | str = PROJECT_ROOT / "data" / "sentinel2_l2a.tif",
        output_path: Path | str = DEFAULT_OUTPUT_PATH,
        config: PlanningConfig | None = None,
) -> RouteResult:
    """Plan and display a route between WGS84 endpoints.

    The optional route elevation offset lifts the line for display only.
    """
    start = _as_wgs84_point("start", start_endpoint)
    end = _as_wgs84_point("end", end_endpoint)

    result = plan_route_from_endpoints(
        start,
        end,
        dem_path=dem_path,
        sentinel2_path=sentinel2_path,
        output_path=output_path,
        config=config,
    )
    _display_route(
        result,
        dem_path=dem_path,
        sentinel2_path=sentinel2_path,
        class_colors=class_colors,
        route_color=route_color,
        sampling_stride=sampling_stride,
        route_elevation_offset_m=route_elevation_offset_m,
    )
    return result


def test_sample_route() -> RouteResult:
    """Read the sample endpoints GeoJSON and run the interactive route test."""
    start, end = _read_sample_endpoints(DEFAULT_ENDPOINTS_PATH)
    return run_planning_test(start, end)


def _as_wgs84_point(name: str, point: Sequence[float]) -> tuple[float, float]:
    if len(point) != 2:
        raise ValueError(f"The {name} endpoint must contain longitude and latitude.")
    longitude, latitude = float(point[0]), float(point[1])
    if not (math.isfinite(longitude) and math.isfinite(latitude)):
        raise ValueError(f"The {name} endpoint must contain finite WGS84 coordinates.")
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise ValueError(f"The {name} endpoint is outside the valid WGS84 coordinate range.")
    return longitude, latitude


def _validate_bbox(bbox: Sequence[float]) -> tuple[float, float, float, float]:
    if len(bbox) != 4:
        raise ValueError("bbox must contain west, south, east, north in WGS84.")
    west, south, east, north = (float(value) for value in bbox)
    if not all(math.isfinite(value) for value in (west, south, east, north)):
        raise ValueError("bbox values must be finite WGS84 coordinates.")
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox must be west south east north in valid WGS84 order.")
    return west, south, east, north


def _read_sample_endpoints(path: Path) -> tuple[tuple[float, float], tuple[float, float]]:
    if not path.exists():
        raise ValueError(f"Endpoint GeoJSON file does not exist: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    geometry = document.get("geometry", {}) if document.get("type") == "Feature" else document
    if geometry.get("type") != "LineString":
        raise ValueError("Endpoint GeoJSON must contain a LineString.")
    coordinates = geometry.get("coordinates", [])
    if len(coordinates) != 2:
        raise ValueError("Endpoint LineString must contain exactly two coordinates.")
    return _as_wgs84_point("start", coordinates[0][:2]), _as_wgs84_point("end", coordinates[1][:2])


def _display_route(
        result: RouteResult,
        *,
        dem_path: Path | str,
        sentinel2_path: Path | str,
        class_colors: Mapping[int, str] | None,
        route_color: str,
        sampling_stride: int,
        route_elevation_offset_m: float,
) -> None:
    if sampling_stride < 1:
        raise ValueError("sampling_stride must be at least 1.")
    if not math.isfinite(route_elevation_offset_m) or route_elevation_offset_m < 0:
        raise ValueError("route_elevation_offset_m must be finite and nonnegative.")

    colors = DEFAULT_SCL_COLORS.copy()
    if class_colors is not None:
        colors.update({int(scl_class): color for scl_class, color in class_colors.items()})

    with rasterio.open(dem_path) as dem, rasterio.open(sentinel2_path) as sentinel2:
        elevation = dem.read(1)
        dem_valid = dem.read(2) > 0
        if dem.nodata is not None:
            dem_valid &= elevation != dem.nodata
        scl = sentinel2.read(7)
        imagery_valid = sentinel2.read(8) > 0
        valid = dem_valid & imagery_valid & np.isfinite(elevation)

        sampled_rows = np.unique(np.r_[0:dem.height:sampling_stride, dem.height - 1])
        sampled_cols = np.unique(np.r_[0:dem.width:sampling_stride, dem.width - 1])
        rows, cols = np.meshgrid(sampled_rows, sampled_cols, indexing="ij")
        sampled_valid = valid[rows, cols]
        sampled_elevation = np.where(sampled_valid, elevation[rows, cols], np.nan)
        sampled_scl = scl[rows, cols]
        x_coords, northing = dem.transform * (cols + 0.5, rows + 0.5)

        fig = plt.figure(figsize=(12, 9))
        ax = fig.add_subplot(111, projection="3d")
        legend_items: list[Patch | Line2D] = []
        face_colors = np.zeros((*rows.shape, 4))
        for scl_class in sorted(int(value) for value in np.unique(sampled_scl[sampled_valid])):
            class_mask = sampled_scl == scl_class
            color = colors.get(scl_class, "#000000")
            face_colors[class_mask] = to_rgba(color)
            legend_items.append(Patch(color=color, label=f"SCL class {scl_class}"))
        valid_faces = (sampled_valid[:-1, :-1] & sampled_valid[1:, :-1]
                       & sampled_valid[:-1, 1:] & sampled_valid[1:, 1:])
        face_colors[:-1, :-1, 3] *= valid_faces
        ax.plot_surface(x_coords, northing, sampled_elevation, facecolors=face_colors,
                        rstride=1, cstride=1, linewidth=0, antialiased=False)

        path_rc = result.path_rc
        path_rows, path_cols = path_rc[:, 0], path_rc[:, 1]
        path_elevation = elevation[path_rows, path_cols].astype(float) + route_elevation_offset_m
        path_x, path_northing = xy(dem.transform, path_rows, path_cols, offset="center")
        # Overlay the full-resolution route on the coarser display mesh.
        route_line, = ax.plot(path_x, path_northing, path_elevation, color=route_color,
                              linewidth=2, zorder=5, label="Planned route")
        legend_items.append(route_line)

        ax.set_xlabel("Easting (m)")
        ax.set_ylabel("Northing (m)")
        ax.set_zlabel("Elevation (m)")
        ax.set_proj_type("ortho")
        ax.set_box_aspect([np.ptp(limits) for limits in
                           (ax.get_xlim3d(), ax.get_ylim3d(), ax.get_zlim3d())])
        # At true scale the vertical axis is too short for multiple labels.
        ax.set_zticks([round(float(np.nanmedian(path_elevation)))])
        ax.set_title(f"Planned route — {result.strategy}, {result.length_m:.1f} m")
        ax.legend(handles=legend_items, loc="upper left", bbox_to_anchor=(1.02, 1.0))
        fig.tight_layout()
        plt.show()


if __name__ == "__main__":
    test_sample_route()
