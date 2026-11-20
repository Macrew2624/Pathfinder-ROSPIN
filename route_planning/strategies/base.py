from __future__ import annotations

from typing import Protocol

import numpy as np


class RouteStrategy(Protocol):
    """Interface implemented by each interchangeable route search strategy."""

    name: str

    def find_path(
        self,
        cost_surface: np.ndarray,
        start_rc: tuple[int, int],
        end_rc: tuple[int, int],
    ) -> np.ndarray:
        """Return an ``N x 2`` row/column path, or an empty array if unreachable.

        Implementations receive one shared cost surface so search algorithms
        can be swapped without duplicating raster preparation or constraints.
        """
