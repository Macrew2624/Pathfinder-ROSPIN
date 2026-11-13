from __future__ import annotations

from collections.abc import Callable

from .base import RouteStrategy

_STRATEGIES: dict[str, Callable[[], RouteStrategy]] = {}


def register_strategy(name: str) -> Callable[[type], type]:
    """Register a strategy class for construction by the CLI or Python API.

    The strategy is created later by name, keeping the planner independent of
    which search algorithms have been added to the package.
    """

    def decorator(strategy_type: type) -> type:
        """Store the decorated class as the factory for this strategy name."""
        if name in _STRATEGIES:
            raise ValueError(f"A route strategy named {name!r} is already registered.")
        _STRATEGIES[name] = strategy_type
        return strategy_type

    return decorator


def create_strategy(name: str) -> RouteStrategy:
    """Instantiate a registered strategy and report available names on error."""
    try:
        factory = _STRATEGIES[name]
    except KeyError as exc:
        available = ", ".join(sorted(_STRATEGIES)) or "none"
        raise ValueError(f"Unknown strategy {name!r}. Available strategies: {available}.") from exc
    return factory()


def available_strategies() -> tuple[str, ...]:
    """Return registered strategy names for CLI choices and API discovery."""
    return tuple(sorted(_STRATEGIES))
