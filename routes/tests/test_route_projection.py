from itertools import pairwise

import pytest

from core.geo import Coordinate, haversine_miles
from fuel.services.station_finder import StationRecord
from routes.services.route_projection import project_stations


def station(
    latitude: float, longitude: float, price: float = 3.0, name: str = "S"
) -> StationRecord:
    return StationRecord(
        opis_id=abs(hash((latitude, longitude, name))) % 100_000,
        name=name,
        address="Interstate exit",
        city="Somewhere",
        state="TX",
        price_per_gallon=price,
        coordinate=Coordinate(latitude, longitude),
    )


# A straight west-to-east line along the 35th parallel, about 283 miles long.
WEST = Coordinate(35.0, -100.0)
EAST = Coordinate(35.0, -95.0)
LINE = [WEST, EAST]
LINE_MILES = haversine_miles(WEST, EAST)


def test_a_station_on_the_route_projects_to_its_distance_along_it():
    midpoint = station(35.0, -97.5)

    [result] = project_stations(LINE, LINE_MILES, [midpoint], corridor_miles=25.0)

    assert result.detour_miles == pytest.approx(0.0, abs=0.01)
    assert result.route_distance_miles == pytest.approx(LINE_MILES / 2, rel=0.01)


def test_a_station_beside_the_route_keeps_its_along_route_position():
    beside = station(35.1, -97.5)  # about 7 miles north of the midpoint

    [result] = project_stations(LINE, LINE_MILES, [beside], corridor_miles=25.0)

    assert result.detour_miles == pytest.approx(6.9, abs=0.3)
    assert result.route_distance_miles == pytest.approx(LINE_MILES / 2, rel=0.01)


def test_stations_outside_the_corridor_are_dropped():
    near = station(35.1, -97.5, name="NEAR")
    far = station(36.0, -97.5, name="FAR")  # about 69 miles north

    results = project_stations(LINE, LINE_MILES, [near, far], corridor_miles=25.0)

    assert [r.station.name for r in results] == ["NEAR"]


def test_the_corridor_width_is_what_decides_inclusion():
    at_40_miles = station(35.58, -97.5)

    assert project_stations(LINE, LINE_MILES, [at_40_miles], corridor_miles=25.0) == []
    assert len(project_stations(LINE, LINE_MILES, [at_40_miles], corridor_miles=50.0)) == 1


def test_results_are_ordered_along_the_route():
    stations = [
        station(35.0, -96.0, name="THIRD"),
        station(35.0, -99.0, name="FIRST"),
        station(35.0, -97.0, name="SECOND"),
    ]

    results = project_stations(LINE, LINE_MILES, stations, corridor_miles=25.0)

    assert [r.station.name for r in results] == ["FIRST", "SECOND", "THIRD"]
    positions = [r.route_distance_miles for r in results]
    assert positions == sorted(positions)


def test_positions_are_rescaled_onto_the_providers_reported_distance():
    """Geometry is simplified, so the polyline is shorter than the real road.

    Mile positions must follow the distance the routing API reported, or the fuel
    arithmetic would not agree with the total the API returns.
    """
    reported = LINE_MILES * 1.2
    midpoint = station(35.0, -97.5)

    [result] = project_stations(LINE, reported, [midpoint], corridor_miles=25.0)

    assert result.route_distance_miles == pytest.approx(reported / 2, rel=0.01)


def test_a_station_near_a_bend_measures_to_the_nearest_leg():
    bend = [Coordinate(35.0, -100.0), Coordinate(35.0, -97.0), Coordinate(38.0, -97.0)]
    total = sum(haversine_miles(a, b) for a, b in pairwise(bend))
    inside_corner = station(35.1, -97.1)

    [result] = project_stations(bend, total, [inside_corner], corridor_miles=25.0)

    assert result.detour_miles < 10.0


def test_a_long_segment_still_finds_a_station_beside_its_middle():
    """The grid files each segment under every cell its corridor touches.

    A simplified transcontinental route has segments hundreds of miles long whose
    endpoints are nowhere near a station beside the middle of them.
    """
    long_line = [Coordinate(40.0, -105.0), Coordinate(40.0, -85.0)]
    total = haversine_miles(*long_line)
    beside_the_middle = station(40.05, -95.0)

    [result] = project_stations(long_line, total, [beside_the_middle], corridor_miles=25.0)

    assert result.detour_miles == pytest.approx(3.5, abs=0.5)
    assert result.route_distance_miles == pytest.approx(total / 2, rel=0.02)


@pytest.mark.parametrize("geometry", [[], [Coordinate(35.0, -100.0)]])
def test_a_degenerate_route_projects_nothing(geometry):
    assert project_stations(geometry, 100.0, [station(35.0, -100.0)], corridor_miles=25.0) == []


def test_no_stations_projects_nothing():
    assert project_stations(LINE, LINE_MILES, [], corridor_miles=25.0) == []


def test_a_zero_length_route_projects_nothing():
    same = Coordinate(35.0, -100.0)
    assert project_stations([same, same], 0.0, [station(35.0, -100.0)], corridor_miles=25.0) == []
