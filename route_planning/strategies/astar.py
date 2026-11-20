from __future__ import annotations

import numpy as np
import pyastar2d

from .registry import register_strategy


@register_strategy("astar")
class AStarStrategy:
    """A* search over a two-dimensional, positive-cost raster."""

    name = "astar"

    def find_path(
        self,
        cost_surface: np.ndarray,
        start_rc: tuple[int, int],
        end_rc: tuple[int, int],
    ) -> np.ndarray:
        """Run compiled A* on the weighted grid and return raster cell indices.

        Infinite costs represent barriers. Contiguous float32 weights match
        pyastar2d's input requirements and avoid making an explicit graph.
        """
        if cost_surface.ndim != 2:
            raise ValueError("A* cost surface must be a two-dimensional array.")
        if not np.any(np.isfinite(cost_surface)):
            raise ValueError("The cost surface has no traversable cells.")
        finite_costs = cost_surface[np.isfinite(cost_surface)]
        if np.min(finite_costs) < 1.0:
            raise ValueError("pyastar2d requires every traversable cell cost to be at least 1.")

        # Normalize only the storage layout and dtype; preserving the actual
        # costs keeps route choices consistent with the shared cost model.
        weights = np.ascontiguousarray(cost_surface, dtype=np.float32)
        path = pyastar2d.astar_path(weights, start_rc, end_rc, allow_diagonal=True)
        if path is None or len(path) == 0:
            return np.empty((0, 2), dtype=np.int32)
        return np.asarray(path, dtype=np.int32)
