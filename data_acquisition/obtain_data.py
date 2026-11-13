from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

import requests
from dotenv import load_dotenv
from pyproj import Transformer

S2_EVALSCRIPT = """//VERSION=3
function setup() {
  return { input: [{ bands: ["B02", "B03", "B04", "B08", "B11", "B12", "SCL", "dataMask"] }],
           output: { bands: 8, sampleType: "FLOAT32" } };
}
function evaluatePixel(s) {
  return [s.B02, s.B03, s.B04, s.B08, s.B11, s.B12, s.SCL, s.dataMask];
}
"""

S1_EVALSCRIPT = """//VERSION=3
function setup() {
  return { input: [{ bands: ["VV", "VH", "dataMask"] }],
           output: { bands: 3, sampleType: "FLOAT32" } };
}
function evaluatePixel(s) { return [s.VV, s.VH, s.dataMask]; }
"""

DEM_EVALSCRIPT = """//VERSION=3
function setup() {
  return { input: [{ bands: ["DEM", "dataMask"] }],
           output: { bands: 2, sampleType: "FLOAT32" } };
}
function evaluatePixel(s) { return [s.DEM, s.dataMask]; }
"""


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    today = date.today()
    parser = argparse.ArgumentParser(
        description="Fetch a Sentinel-1, Sentinel-2 and Copernicus DEM stack for a road-planning AOI."
    )
    parser.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("WEST", "SOUTH", "EAST", "NORTH"),
                        help="AOI bounds in WGS84 longitude/latitude degrees.")
    parser.add_argument("--start", nargs=2, type=float, required=True, metavar=("LON", "LAT"),
                        help="Road start point in WGS84 longitude/latitude.")
    parser.add_argument("--end", nargs=2, type=float, required=True, metavar=("LON", "LAT"),
                        help="Road end point in WGS84 longitude/latitude.")
    parser.add_argument("--from-date", default=(today - timedelta(days=90)).isoformat(), help="Imagery window start (YYYY-MM-DD; default: 90 days ago).")
    parser.add_argument("--to-date", default=today.isoformat(), help="Imagery window end (YYYY-MM-DD; default: today).")
    parser.add_argument("--resolution", type=float, default=10, help="Output pixel size in metres (default: 10).")
    parser.add_argument("--cloud-cover", type=float, default=30, help="Maximum Sentinel-2 cloud cover percentage (default: 30).")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data",
                        help="Output directory (default: project-root/data).")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.local",
                        help="Credentials file (default: project-root/.env.local).")
    return parser


def validate_inputs(
    bbox: Sequence[float], start: Sequence[float], end: Sequence[float],
    from_date: str, to_date: str, resolution: float, cloud_cover: float,
) -> None:
    if len(bbox) != 4:
        raise ValueError("bbox must contain west, south, east, north.")
    if len(start) != 2 or len(end) != 2:
        raise ValueError("start and end must each contain longitude and latitude.")
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox must be west south east north in valid WGS84 order.")
    for name, point in (("start", start), ("end", end)):
        lon, lat = point
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError(f"{name} must be a valid WGS84 longitude/latitude pair.")
        if not (west <= lon <= east and south <= lat <= north):
            raise ValueError(f"{name} point must lie inside bbox.")
    if resolution <= 0:
        raise ValueError("resolution must be greater than zero.")
    if not 0 <= cloud_cover <= 100:
        raise ValueError("cloud_cover must be between 0 and 100.")
    try:
        if date.fromisoformat(from_date) > date.fromisoformat(to_date):
            raise ValueError("from_date must not be after to_date.")
    except ValueError as exc:
        raise ValueError("Dates must use YYYY-MM-DD, and from_date must not be after to_date.") from exc


def get_token(session: requests.Session, client_id: str, client_secret: str) -> str:
    response = session.post(os.getenv("TOKEN_URL"), data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=60)
    response.raise_for_status()
    return response.json()["access_token"]


def request_raster(
    session: requests.Session, token: str, bbox: list[float], resolution: float,
    collection: str, evalscript: str, output: Path, from_date: str, to_date: str,
    cloud_cover: float | None = None,
) -> None:
    west, south, east, north = bbox
    center_lon = (west + east) / 2
    center_lat = (south + north) / 2
    zone = max(1, min(60, int((center_lon + 180) // 6) + 1))
    epsg = (32600 if center_lat >= 0 else 32700) + zone
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    corners = [to_utm.transform(west, south), to_utm.transform(west, north),
               to_utm.transform(east, south), to_utm.transform(east, north)]
    min_x = min(point[0] for point in corners)
    max_x = max(point[0] for point in corners)
    min_y = min(point[1] for point in corners)
    max_y = max(point[1] for point in corners)
    width = max(1, round((max_x - min_x) / resolution))
    height = max(1, round((max_y - min_y) / resolution))

    data_filter: dict[str, object] = {}
    if collection != "dem":
        data_filter["timeRange"] = {
            "from": f"{from_date}T00:00:00Z", "to": f"{to_date}T23:59:59Z",
        }
    if collection == "sentinel-2-l2a":
        data_filter["maxCloudCoverage"] = cloud_cover
        data_filter["mosaickingOrder"] = "leastCC"
    if collection == "sentinel-1-grd":
        data_filter["acquisitionMode"] = "IW"
        data_filter["polarization"] = "DV"
    if collection == "dem":
        data_filter["demInstance"] = "COPERNICUS_30"

    request_body = {
        "input": {
            "bounds": {"bbox": [min_x, min_y, max_x, max_y],
                       "properties": {"crs": f"http://www.opengis.net/def/crs/EPSG/0/{epsg}"}},
            "data": [{"type": collection, "dataFilter": data_filter}],
        },
        "output": {"width": width, "height": height,
                   "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]},
        "evalscript": evalscript,
    }
    response = session.post(os.getenv("PROCESS_URL"), headers={"Authorization": f"Bearer {token}", "Accept": "image/tiff"},
                            json=request_body, timeout=300)
    if not response.ok:
        detail = response.text[:1200]
        raise RuntimeError(f"{collection} request failed ({response.status_code}): {detail}")
    output.write_bytes(response.content)
    print(f"Saved {output} ({width} x {height} px, EPSG:{epsg})")

class DataAcquisition:
    """Fetch and save the three raster layers and road endpoint geometry."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        env_file: Path | str = PROJECT_ROOT / ".env.local",
    ) -> None:
        load_dotenv(Path(env_file))
        self.client_id = client_id or os.getenv("CDSE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("CDSE_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            raise ValueError(
                f"Set CDSE_CLIENT_ID and CDSE_CLIENT_SECRET in {env_file}, "
                "or pass them to DataAcquisition."
            )

    def obtain_data(
        self,
        bbox: Sequence[float],
        start: Sequence[float],
        end: Sequence[float],
        from_date: str | None = None,
        to_date: str | None = None,
        resolution: float = 10,
        cloud_cover: float = 30,
        output: Path | str = PROJECT_ROOT / "data",
    ) -> dict[str, Path]:
        """Download rasters for WGS84 ``bbox`` and save the requested route endpoints.

        Returns a mapping from ``sentinel2``, ``sentinel1``, ``dem``, and
        ``road_endpoints`` to the paths written on disk.
        """
        today = date.today()
        from_date = from_date or (today - timedelta(days=90)).isoformat()
        to_date = to_date or today.isoformat()
        validate_inputs(bbox, start, end, from_date, to_date, resolution, cloud_cover)

        output_dir = Path(output)
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "sentinel2": output_dir / "sentinel2_l2a.tif",
            "sentinel1": output_dir / "sentinel1_grd.tif",
            "dem": output_dir / "copernicus_dem_glo30.tif",
            "road_endpoints": output_dir / "road_endpoints.geojson",
        }
        with requests.Session() as session:
            token = get_token(session, self.client_id, self.client_secret)
            common = (session, token, list(bbox), resolution)
            request_raster(*common, "sentinel-2-l2a", S2_EVALSCRIPT, paths["sentinel2"],
                           from_date, to_date, cloud_cover)
            request_raster(*common, "sentinel-1-grd", S1_EVALSCRIPT, paths["sentinel1"],
                           from_date, to_date)
            request_raster(*common, "dem", DEM_EVALSCRIPT, paths["dem"], from_date, to_date)

        route = {"type": "Feature", "properties": {"name": "planned_road_endpoints"},
                 "geometry": {"type": "LineString", "coordinates": [list(start), list(end)]}}
        paths["road_endpoints"].write_text(json.dumps(route, indent=2) + "\n", encoding="utf-8")
        return paths


def main() -> int:
    args = build_parser().parse_args()
    try:
        acquirer = DataAcquisition(env_file=args.env_file)
        paths = acquirer.obtain_data(
            bbox=args.bbox, start=args.start, end=args.end,
            from_date=args.from_date, to_date=args.to_date,
            resolution=args.resolution, cloud_cover=args.cloud_cover, output=args.output,
        )
        for path in paths.values():
            print(f"Saved {path}")
        return 0
    except (ValueError, requests.RequestException, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
