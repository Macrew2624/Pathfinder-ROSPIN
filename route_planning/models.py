from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class PlanningConfig:
    """Shared terrain constraints and cost settings for route strategies."""

    max_slope_degrees: float = 10.0
    slope_cost_weight: float = 3.0
    impassable_scl_classes: frozenset[int] = field(default_factory=lambda: frozenset({6}))

    def __post_init__(self) -> None:
        """Reject invalid constraint values before any raster work begins."""
        if not 0 < self.max_slope_degrees < 90:
            raise ValueError("max_slope_degrees must be greater than 0 and less than 90.")
        if self.slope_cost_weight < 0:
            raise ValueError("slope_cost_weight must be zero or greater.")
        if any(value < 0 or value > 11 for value in self.impassable_scl_classes):
            raise ValueError("SCL class values must be between 0 and 11.")


@dataclass(frozen=True)
class RouteResult:
    """Computed route in raster row/column coordinates and summary metrics.

    ``weighted_cost`` is a relative terrain cost, while ``length_m`` is the
    route length estimated from the raster cell spacing.
    """

    path_rc: np.ndarray
    strategy: str
    weighted_cost: float
    length_m: float


@dataclass(frozen=True)
class InputPaths:
    """Group the three files consumed by the route-planning pipeline."""

    dem: Path
    sentinel2: Path
    endpoints: Path
