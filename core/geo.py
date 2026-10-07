"""Geographic primitives.

All distances are statute miles. Coordinates are WGS84 decimal degrees.

The route-projection hot path runs tens of thousands of point-to-segment tests
per request, so segment maths uses a local equirectangular projection rather
than repeated haversine calls: over a highway segment the error is far below
the corridor width we filter on, and it costs a handful of multiplications.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

EARTH_RADIUS_MILES = 3958.7613
MILES_PER_DEGREE = math.pi * EARTH_RADIUS_MILES / 180.0


@dataclass(frozen=True, slots=True)
class Coordinate:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError(f"latitude out of range: {self.latitude}")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude out of range: {self.longitude}")


@dataclass(frozen=True, slots=True)
class BoundingBox:
    min_latitude: float
    min_longitude: float
    max_latitude: float
    max_longitude: float

    @classmethod
    def around(cls, points: list[Coordinate]) -> BoundingBox:
        if not points:
            raise ValueError("cannot build a bounding box from no points")
        lats = [p.latitude for p in points]
        lons = [p.longitude for p in points]
        return cls(min(lats), min(lons), max(lats), max(lons))

    def padded(self, miles: float) -> BoundingBox:
        """Grow the box by `miles` in every direction.

        Longitude degrees shrink towards the poles, so the padding is computed at
        whichever bounding latitude is nearest a pole: that is the worst case and
        keeps the box conservative (never too small).
        """
        lat_pad = miles / MILES_PER_DEGREE
        worst_latitude = max(abs(self.min_latitude), abs(self.max_latitude))
        cos_lat = max(math.cos(math.radians(min(worst_latitude, 89.0))), 1e-6)
        lon_pad = miles / (MILES_PER_DEGREE * cos_lat)
        return BoundingBox(
            max(self.min_latitude - lat_pad, -90.0),
            max(self.min_longitude - lon_pad, -180.0),
            min(self.max_latitude + lat_pad, 90.0),
            min(self.max_longitude + lon_pad, 180.0),
        )


def haversine_miles(a: Coordinate, b: Coordinate) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.latitude, a.longitude, b.latitude, b.longitude))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(min(1.0, h)))


def cumulative_miles(points: list[Coordinate]) -> list[float]:
    """Running along-path distance for each point, starting at 0."""
    out = [0.0]
    for previous, current in pairwise(points):
        out.append(out[-1] + haversine_miles(previous, current))
    return out


def point_to_segment(point: Coordinate, start: Coordinate, end: Coordinate) -> tuple[float, float]:
    """Return (perpendicular miles from the segment, fraction along the segment).

    The fraction is clamped to [0, 1], so a point beyond either end measures to
    that endpoint.
    """
    cos_lat = math.cos(math.radians((start.latitude + end.latitude) / 2.0))
    scale_x = MILES_PER_DEGREE * cos_lat
    ax = start.longitude * scale_x
    ay = start.latitude * MILES_PER_DEGREE
    bx = end.longitude * scale_x
    by = end.latitude * MILES_PER_DEGREE
    px = point.longitude * scale_x
    py = point.latitude * MILES_PER_DEGREE

    dx = bx - ax
    dy = by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0.0:
        return math.hypot(px - ax, py - ay), 0.0
    fraction = min(1.0, max(0.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    nearest_x = ax + fraction * dx
    nearest_y = ay + fraction * dy
    return math.hypot(px - nearest_x, py - nearest_y), fraction
