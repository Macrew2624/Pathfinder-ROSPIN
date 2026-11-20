# Route planning

This package converts the acquired elevation and Sentinel-2 rasters into a
terrain cost surface, then runs a selected route-search strategy. Search
strategies share the same cost surface and `RouteStrategy` interface, so new
implementations such as ACO can be registered independently.

## Current A* model

- Maximum local terrain slope is a hard constraint (default: 10 degrees).
- Sentinel-2 SCL class 6 (water) and invalid/missing raster cells are blocked.
- Traversable cells have cost `1 + weight * (slope / max_slope) ** 2`; the
  default slope cost weight is 3. This biases the route toward gentler terrain
  while preserving a positive minimum cost for A*.
- `pyastar2d` runs an 8-connected A* search. The output is a GeoJSON LineString
  in WGS84, with route length and relative weighted cost in its properties.

The slope limit applies to the terrain gradient estimated from neighboring DEM
cells. A 10-degree slope corresponds to a 17.6% grade. Individual route steps
can exceed that grade because the planner checks each cell's estimated slope
and does not constrain the elevation change between successive route cells.
To assess a climb or descent, sample the DEM along the route and calculate
`100 × elevation change / horizontal distance` over the section of interest.

The default water mask uses Sentinel-2 SCL. Tune `--impassable-scl-classes` for
the local planning assumptions. The DEM and Sentinel-2 raster must have the
same CRS, dimensions, and pixel grid.

## Run

Install project dependencies, then use the acquisition outputs:

```powershell
py -m pip install -r requirements.txt
py -m route_planning --max-slope-degrees 8
```

By default, the route is written to
`route_planning/output/planned_route.geojson`. Override input files, strategy,
constraints, or output location with the corresponding CLI flags. For example:

```powershell
py -m route_planning `
  --strategy astar `
  --max-slope-degrees 8 `
  --slope-cost-weight 4 `
  --impassable-scl-classes 6 11 `
  --output .\route_planning\output\route.geojson
```

## View the route on the terrain

From the project root, run the interactive example with the endpoints in
`data/road_endpoints.geojson`.

```powershell
py -m route_planning.test
```

The example plans the route, writes `route_planning/output/planned_route.geojson`,
and opens the plot. The planner reuses the local DEM and Sentinel-2 rasters when
both cover the endpoints. If either file is missing or an endpoint falls outside
its coverage, it requests both rasters for a padded bounding box around the
endpoints. Those downloads use `RASTER_RESOLUTION` in [config.py](../config.py)
(currently 20 m per pixel) and require CDSE credentials.

Easting and northing form the horizontal plane. Elevation is vertical, with
the same scale per metre on all three axes. A few hundred metres of relief
across tens of kilometres will therefore look nearly flat. Surface colors
show Sentinel-2 scene classes. The route line uses the DEM elevation at every
route cell.

For a finer display mesh, pass a smaller `sampling_stride` to
`run_planning_test`. The default draws the surface using every tenth raster
row and column. Route planning still uses the full grid. The optional
`route_elevation_offset_m` lifts the line for visibility and defaults to zero.

## Add a strategy

Implement `RouteStrategy.find_path(cost_surface, start_rc, end_rc)` and
register the class with `@register_strategy("name")` in
`route_planning/strategies/`. New strategies receive the same positive-cost
surface with blocked cells represented as infinity. Add their module import to
`route_planning/strategies/__init__.py` so registration happens at startup.

## Basic bitch python

Run `plan_route_from_endpoints` from `planner.py`, where the two endpoints are in WGS84.
The planner will automatically download new satellite data if the current one does not
cover the bounding box.
