from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .models import PlanningConfig
from .planner import PROJECT_ROOT, plan_route, strategy_names


def build_parser() -> argparse.ArgumentParser:
    """Define file, strategy, and terrain-constraint command-line options."""
    parser = argparse.ArgumentParser(
        description="Plan a least-cost road corridor from the acquired terrain rasters."
    )
    parser.add_argument("--dem", type=Path, default=PROJECT_ROOT / "data" / "copernicus_dem_glo30.tif")
    parser.add_argument("--sentinel2", type=Path, default=PROJECT_ROOT / "data" / "sentinel2_l2a.tif")
    parser.add_argument("--endpoints", type=Path, default=PROJECT_ROOT / "data" / "road_endpoints.geojson")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "route_planning" / "output" / "planned_route.geojson",
    )
    parser.add_argument("--strategy", choices=strategy_names(), default="astar")
    parser.add_argument(
        "--max-slope-degrees",
        type=float,
        default=10.0,
        help="Maximum local terrain slope angle allowed (default: 10 degrees).",
    )
    parser.add_argument(
        "--slope-cost-weight",
        type=float,
        default=3.0,
        help="Extra relative cost at the maximum allowed slope (default: 3).",
    )
    parser.add_argument(
        "--impassable-scl-classes",
        type=int,
        nargs="+",
        default=[6],
        metavar="CLASS",
        help="Sentinel-2 SCL classes to block; class 6 (water) is blocked by default.",
    )
    return parser


def main() -> int:
    """Parse CLI arguments, run planning, and print a concise result summary."""
    args = build_parser().parse_args()
    try:
        config = PlanningConfig(
            max_slope_degrees=args.max_slope_degrees,
            slope_cost_weight=args.slope_cost_weight,
            impassable_scl_classes=frozenset(args.impassable_scl_classes),
        )
        result = plan_route(
            dem_path=args.dem,
            sentinel2_path=args.sentinel2,
            endpoints_path=args.endpoints,
            output_path=args.output,
            strategy_name=args.strategy,
            config=config,
        )
        print(f"Strategy: {result.strategy}")
        print(f"Route length: {result.length_m:.1f} m")
        print(f"Weighted cost: {result.weighted_cost:.1f}")
        print(f"Saved route: {args.output}")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
