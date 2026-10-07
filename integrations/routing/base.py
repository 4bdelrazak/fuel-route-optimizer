"""Routing provider contract.

The application depends on `Route` and `RoutingProvider` only, so swapping OSRM
for another provider means adding one module and changing one setting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.geo import Coordinate


@dataclass(frozen=True, slots=True)
class Route:
    distance_miles: float
    duration_minutes: float
    geometry: list[Coordinate]
    """Ordered polyline from start to finish, usable directly on a map."""


class RoutingProvider(Protocol):
    def driving_route(self, start: Coordinate, finish: Coordinate) -> Route:
        """Return the driving route, or raise `NoRouteFound` /
        `RoutingServiceUnavailable`."""
