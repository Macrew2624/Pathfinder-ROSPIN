# Pathfinder-ROSPIN
Satellite-powered road planning platform that uses metaheuristic optimization to identify suitable routes for new roads.

## Obtain satellite and terrain data

The `data_acquisition/obtain_data.py` script requests clipped GeoTIFF rasters from the Copernicus Data Space Ecosystem (CDSE) Sentinel Hub Process API:

- Sentinel-2 L2A: B02, B03, B04, B08, B11, B12, scene classification (SCL), and data mask.
- Sentinel-1 GRD: VV, VH, and data mask.
- Copernicus DEM GLO-30 (`COPERNICUS_30`): elevation and data mask.

The Sentinel products are mosaicked over the requested date range. Sentinel-2 uses the least-cloudy mosaicking order and a maximum scene cloud-cover filter. Output is a local-UTM GeoTIFF at the selected pixel size; the DEM is static, so its output covers the same AOI and resolution. The road endpoints are saved as `road_endpoints.geojson` for the route-planning stage.

### Setup

1. Install Python 3.10 or newer and dependencies:

   ```powershell
   py -m pip install -r requirements.txt
   ```

2. Create OAuth client credentials for CDSE, then put them in `.env.local`:

   ```dotenv
   CDSE_CLIENT_ID=your-client-id
   CDSE_CLIENT_SECRET=your-client-secret
   ```

   `.env.local` is ignored by Git. `.env.example` documents the required variables. Access to Sentinel Hub and Copernicus DEM 30 m must be enabled for the CDSE account; DEM GLO-30 requires the applicable CCM authorization.

### Example

Coordinates are WGS84 longitude/latitude. `--bbox` is `west south east north`; both route points must be inside it.

```powershell
py .\data_acquisition\obtain_data.py `
  --bbox 24.90 45.80 25.10 46.00 `
  --start 24.94 45.84 `
  --end 25.06 45.96 `
  --from-date 2026-06-01 `
  --to-date 2026-09-01 `
  --output .\data
```

The defaults use a 90-day imagery window, 10 m output pixels, and a 30% Sentinel-2 cloud-cover limit. Adjust with `--resolution` and `--cloud-cover`. Results are written to `data/sentinel2_l2a.tif`, `data/sentinel1_grd.tif`, `data/copernicus_dem_glo30.tif`, and `data/road_endpoints.geojson`.

### Call from Python

`DataAcquisition.obtain_data()` is the reusable method; the command-line parser simply gathers the same values from terminal arguments and calls it. Import the class from your application and pass coordinates directly:

```python
from data_acquisition.obtain_data import DataAcquisition

acquisition = DataAcquisition()  # Loads credentials from project-root .env.local
files = acquisition.obtain_data(
    bbox=(24.90, 45.80, 25.10, 46.00),  # west, south, east, north
    start=(24.94, 45.84),                # longitude, latitude
    end=(25.06, 45.96),
    from_date="2026-06-01",
    to_date="2026-09-01",
    output="data",
)
print(files["sentinel2"])
```

The returned dictionary contains `Path` values for `sentinel2`, `sentinel1`, `dem`, and `road_endpoints`. You can also pass `client_id` and `client_secret` to `DataAcquisition(...)` directly, for example when the application manages secrets outside a local env file.

## Plan a candidate route

The `route_planning/` package builds a terrain cost surface from the acquired
DEM and Sentinel-2 rasters, then runs a selectable route-search strategy. The
initial strategy is A* via `pyastar2d`. Its defaults block water (Sentinel-2
SCL class 6), invalid pixels, and terrain above a 10-degree local slope. Tune
the maximum slope and slope penalty for each planning scenario:

```powershell
py -m pip install -r requirements.txt
py -m route_planning --max-slope-degrees 8 --slope-cost-weight 4
```

The route is saved by default to
`route_planning/output/planned_route.geojson`. See
[`route_planning/README.md`](route_planning/README.md) for the cost model,
available options, and instructions for adding strategies such as ACO.
