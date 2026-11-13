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

These are preliminary screening constraints. In particular, the slope angle
is calculated from the local DEM surface and is not a designed road grade.
The default water mask uses Sentinel-2 SCL; tune `--impassable-scl-classes` for
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

## Add a strategy

Implement `RouteStrategy.find_path(cost_surface, start_rc, end_rc)` and
register the class with `@register_strategy("name")` in
`route_planning/strategies/`. New strategies receive the same positive-cost
surface with blocked cells represented as infinity. Add their module import to
`route_planning/strategies/__init__.py` so registration happens at startup.
