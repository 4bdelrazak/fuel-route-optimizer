"""Place fuel stations onto a route.

A route is a polyline; a station is a point. To plan fuel we need, for every
station, how far along the route it sits and how far off the route it lies. Both
come from local geometry, so the routing API is called once for the route and
never again.

Doing this naively is O(stations x segments): a transcontinental route against
7,000 stations is tens of millions of point-to-segment tests. Instead each
segment is filed into the grid cells its corridor-padded bounding box covers,
and a station is then only tested against the segments filed in its own cell.
That is exact, not approximate: if a station lies within the corridor of a
segment, the segment's padded box contains the station, so the segment is filed
in the station's cell.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from core.geo import MILES_PER_DEGREE, Coordinate, cumulative_miles, point_to_segment
from fuel.services.station_finder import StationRecord

GRID_CELL_DEGREES = 1.0


@dataclass(frozen=True, slots=True)
class ProjectedStation:
    station: StationRecord
    route_distance_miles: float
    """How far along the route the station's nearest point sits."""
    detour_miles: float
    """Straight-line distance from the route to the station."""


def project_stations(
    geometry: list[Coordinate],
    route_distance_miles: float,
    stations: list[StationRecord],
    corridor_miles: float,
) -> list[ProjectedStation]:
    """Stations within `corridor_miles` of the route, ordered along it.

    Along-route distances are rescaled so the polyline's own length matches the
    distance the routing provider reported. The provider's figure is
    authoritative (it follows the real road network at full resolution) while the
    returned geometry is simplified, so without this the mile positions would
    drift from the total the API reports and the fuel maths would not add up.
    """
    if len(geometry) < 2 or not stations:
        return []

    cumulative = cumulative_miles(geometry)
    polyline_miles = cumulative[-1]
    if polyline_miles <= 0:
        return []
    scale = route_distance_miles / polyline_miles

    grid = _index_segments(geometry, corridor_miles)
    projected: list[ProjectedStation] = []
    for station in stations:
        cell = _cell(station.coordinate)
        best_detour = math.inf
        best_position = 0.0
        for index in grid.get(cell, ()):
            start, end = geometry[index], geometry[index + 1]
            detour, fraction = point_to_segment(station.coordinate, start, end)
            if detour < best_detour:
                best_detour = detour
                segment_length = cumulative[index + 1] - cumulative[index]
                best_position = cumulative[index] + fraction * segment_length
        if best_detour <= corridor_miles:
            projected.append(
                ProjectedStation(
                    station=station,
                    route_distance_miles=best_position * scale,
                    detour_miles=best_detour,
                )
            )

    projected.sort(key=lambda p: p.route_distance_miles)
    return projected


def _index_segments(
    geometry: list[Coordinate], corridor_miles: float
) -> dict[tuple[int, int], list[int]]:
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    latitude_pad = corridor_miles / MILES_PER_DEGREE
    for index in range(len(geometry) - 1):
        start, end = geometry[index], geometry[index + 1]
        worst_latitude = min(max(abs(start.latitude), abs(end.latitude)), 89.0)
        cos_latitude = max(math.cos(math.radians(worst_latitude)), 1e-6)
        longitude_pad = corridor_miles / (MILES_PER_DEGREE * cos_latitude)

        min_row = _cell_index(min(start.latitude, end.latitude) - latitude_pad)
        max_row = _cell_index(max(start.latitude, end.latitude) + latitude_pad)
        min_col = _cell_index(min(start.longitude, end.longitude) - longitude_pad)
        max_col = _cell_index(max(start.longitude, end.longitude) + longitude_pad)
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                grid[(row, col)].append(index)
    return grid


def _cell_index(degrees: float) -> int:
    return math.floor(degrees / GRID_CELL_DEGREES)


def _cell(coordinate: Coordinate) -> tuple[int, int]:
    return _cell_index(coordinate.latitude), _cell_index(coordinate.longitude)
