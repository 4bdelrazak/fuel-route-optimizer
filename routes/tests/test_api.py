"""End-to-end tests for the optimize endpoint.

Both external providers are replaced with in-memory fakes, so nothing here
touches the network and the number of provider calls is observable.
"""

import pytest

from conftest import FakeGeocoder, FakeRouter, straight_route, us_location
from core.errors import (
    GeocodingServiceUnavailable,
    NoRouteFound,
    RoutingServiceUnavailable,
)
from core.geo import Coordinate, haversine_miles

URL = "/api/v1/routes/optimize/"

WEST = Coordinate(35.0, -100.0)
EAST = Coordinate(35.0, -85.0)
GEOMETRY_MILES = haversine_miles(WEST, EAST)

WEST_QUERY = "Amarillo, TX"
EAST_QUERY = "Chattanooga, TN"


def geocoder_for(**extra):
    table = {
        WEST_QUERY: us_location(WEST_QUERY, *astuple(WEST)),
        EAST_QUERY: us_location(EAST_QUERY, *astuple(EAST)),
    }
    table.update(extra)
    return FakeGeocoder(table)


def astuple(coordinate: Coordinate) -> tuple[float, float]:
    return coordinate.latitude, coordinate.longitude


def station_at(make_station, fraction: float, price: float, **kwargs):
    """Put a station on the straight route at `fraction` of the way along it."""
    longitude = WEST.longitude + (EAST.longitude - WEST.longitude) * fraction
    return make_station(WEST.latitude, longitude, price, **kwargs)


@pytest.fixture
def setup(db, patch_providers, clear_cache, make_station):
    """Wire fakes and return a helper that posts to the endpoint."""

    def build(distance_miles: float, stations: list[tuple[float, float]], **kwargs):
        for fraction, price in stations:
            station_at(make_station, fraction, price)
        geocoder = kwargs.pop("geocoder", None) or geocoder_for()
        router = kwargs.pop("router", None) or FakeRouter(
            straight_route(WEST, EAST, distance_miles)
        )
        patch_providers(geocoder, router)
        return geocoder, router

    return build


# --- the happy paths ---------------------------------------------------------


def test_a_route_inside_the_vehicle_range_returns_no_stops(client, setup):
    setup(300.0, [(0.02, 3.00)])

    response = client.post(URL, {"start": WEST_QUERY, "finish": EAST_QUERY}, "application/json")

    assert response.status_code == 200
    body = response.json()
    assert body["route"]["distance_miles"] == pytest.approx(300.0)
    assert body["fuel_plan"]["fuel_stops"] == []
    assert body["fuel_plan"]["total_gallons"] == pytest.approx(30.0)
    assert body["fuel_plan"]["total_cost"] == pytest.approx(90.0)
    assert body["fuel_plan"]["start_fill"]["gallons"] == pytest.approx(30.0)


def test_the_response_carries_both_locations_and_the_vehicle_spec(client, setup):
    setup(300.0, [(0.02, 3.00)])

    body = client.post(URL, {"start": WEST_QUERY, "finish": EAST_QUERY}, "application/json").json()

    assert body["start"]["input"] == WEST_QUERY
    assert body["start"]["latitude"] == pytest.approx(35.0)
    assert body["finish"]["input"] == EAST_QUERY
    assert body["finish"]["longitude"] == pytest.approx(-85.0)
    assert body["vehicle"] == {
        "max_range_miles": 500.0,
        "fuel_economy_mpg": 10.0,
        "tank_capacity_gallons": 50.0,
    }


def test_the_route_is_returned_as_a_geojson_linestring(client, setup):
    setup(300.0, [(0.02, 3.00)])

    body = client.post(URL, {"start": WEST_QUERY, "finish": EAST_QUERY}, "application/json").json()

    geometry = body["route"]["geometry"]
    assert geometry["type"] == "LineString"
    assert geometry["coordinates"][0] == [-100.0, 35.0], "GeoJSON is longitude first"
    assert geometry["coordinates"][-1] == [-85.0, 35.0]
    assert body["route"]["duration_minutes"] > 0


def test_a_long_route_returns_several_stops_and_a_consistent_total(client, setup):
    stations = [(0.01, 3.20)] + [(step / 20, 3.00 + (step % 4) * 0.25) for step in range(1, 20)]
    setup(1800.0, stations)

    body = client.post(URL, {"start": WEST_QUERY, "finish": EAST_QUERY}, "application/json").json()

    plan = body["fuel_plan"]
    assert len(plan["fuel_stops"]) >= 2
    assert plan["total_gallons"] == pytest.approx(180.0, abs=0.01)
    purchases = [plan["start_fill"], *plan["fuel_stops"]]
    assert plan["total_cost"] == pytest.approx(sum(p["cost"] for p in purchases), abs=0.05)
    legs = [p["distance_from_previous_miles"] for p in plan["fuel_stops"]]
    legs.append(plan["distance_to_finish_miles"])
    assert max(legs) <= 500.5


def test_every_stop_reports_price_gallons_cost_and_where_it_is(client, setup):
    setup(1200.0, [(0.01, 3.10)] + [(step / 10, 3.00 + step * 0.1) for step in range(1, 10)])

    body = client.post(URL, {"start": WEST_QUERY, "finish": EAST_QUERY}, "application/json").json()

    stop = body["fuel_plan"]["fuel_stops"][0]
    assert stop["cost"] == pytest.approx(stop["gallons"] * stop["price_per_gallon"], abs=0.02)
    assert stop["distance_from_previous_miles"] > 0
    station = stop["station"]
    assert set(station) == {
        "opis_id",
        "name",
        "address",
        "city",
        "state",
        "latitude",
        "longitude",
        "route_distance_miles",
        "detour_miles",
    }
    assert station["state"] == "TX"


def test_the_same_start_and_finish_is_answered_without_a_routing_call(client, setup):
    _, router = setup(300.0, [(0.02, 3.00)])

    response = client.post(URL, {"start": WEST_QUERY, "finish": WEST_QUERY}, "application/json")

    assert response.status_code == 200
    body = response.json()
    assert body["route"]["distance_miles"] == 0.0
    assert body["fuel_plan"]["fuel_stops"] == []
    assert body["fuel_plan"]["total_cost"] == 0.0
    assert router.calls == [], "no route to look up when you are already there"


# --- input validation --------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"start": WEST_QUERY},
        {"finish": EAST_QUERY},
        {"start": "", "finish": EAST_QUERY},
        {"start": "   ", "finish": EAST_QUERY},
        {"start": WEST_QUERY, "finish": None},
        {"start": "x" * 201, "finish": EAST_QUERY},
    ],
)
def test_a_bad_request_body_is_rejected_with_a_field_breakdown(client, setup, payload):
    setup(300.0, [(0.02, 3.00)])

    response = client.post(URL, payload, "application/json")

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "INVALID_INPUT"
    assert "fields" in error


def test_an_unknown_location_is_rejected_with_its_own_code(client, setup):
    setup(300.0, [(0.02, 3.00)])

    response = client.post(
        URL, {"start": "Asdfghjkl Qwerty", "finish": EAST_QUERY}, "application/json"
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "LOCATION_NOT_FOUND"


def test_a_location_outside_the_usa_is_rejected(client, setup):
    toronto = GeocodedLocationFactory("Toronto, ON", 43.65, -79.38, "ca")
    setup(300.0, [(0.02, 3.00)], geocoder=geocoder_for(**{"Toronto, ON": toronto}))

    response = client.post(URL, {"start": WEST_QUERY, "finish": "Toronto, ON"}, "application/json")

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "LOCATION_OUTSIDE_USA"
    assert "finish" in error["message"]


def test_the_start_being_outside_the_usa_is_rejected_before_routing(client, setup):
    toronto = GeocodedLocationFactory("Toronto, ON", 43.65, -79.38, "ca")
    _, router = setup(300.0, [(0.02, 3.00)], geocoder=geocoder_for(**{"Toronto, ON": toronto}))

    response = client.post(URL, {"start": "Toronto, ON", "finish": EAST_QUERY}, "application/json")

    assert response.status_code == 400
    assert "start" in response.json()["error"]["message"]
    assert router.calls == []


def test_get_is_not_allowed(client, db):
    response = client.get(URL)

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


# --- failures the client can act on ------------------------------------------


def test_no_station_in_the_corridor_returns_no_feasible_fuel_plan(client, setup):
    setup(1200.0, [])

    response = client.post(URL, {"start": WEST_QUERY, "finish": EAST_QUERY}, "application/json")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NO_FEASIBLE_FUEL_PLAN"


def test_an_unbridgeable_gap_returns_no_feasible_fuel_plan(client, setup):
    setup(2000.0, [(0.01, 3.00), (0.99, 3.00)])

    response = client.post(URL, {"start": WEST_QUERY, "finish": EAST_QUERY}, "application/json")

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "NO_FEASIBLE_FUEL_PLAN"
    assert "range" in body["error"]["message"]


def test_a_routing_outage_returns_503_without_leaking_the_cause(client, setup):
    setup(300.0, [(0.02, 3.00)], router=FakeRouter(error=RoutingServiceUnavailable()))

    response = client.post(URL, {"start": WEST_QUERY, "finish": EAST_QUERY}, "application/json")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "ROUTING_SERVICE_UNAVAILABLE"
    assert "try again" in body["error"]["message"]
    assert set(body) == {"error"}


def test_no_driving_route_returns_422(client, setup):
    setup(300.0, [(0.02, 3.00)], router=FakeRouter(error=NoRouteFound()))

    response = client.post(URL, {"start": WEST_QUERY, "finish": EAST_QUERY}, "application/json")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NO_ROUTE_FOUND"


def test_a_geocoding_outage_returns_503(client, setup, patch_providers):
    class BrokenGeocoder:
        def geocode(self, query):
            raise GeocodingServiceUnavailable

    setup(300.0, [(0.02, 3.00)], geocoder=BrokenGeocoder())

    response = client.post(URL, {"start": WEST_QUERY, "finish": EAST_QUERY}, "application/json")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "GEOCODING_SERVICE_UNAVAILABLE"


# --- the external-call budget ------------------------------------------------


def test_one_request_costs_one_geocode_per_location_and_one_route(client, setup):
    geocoder, router = setup(300.0, [(0.02, 3.00)])

    client.post(URL, {"start": WEST_QUERY, "finish": EAST_QUERY}, "application/json")

    assert geocoder.calls == [WEST_QUERY, EAST_QUERY]
    assert len(router.calls) == 1, "never one call per fuel station"


def test_repeating_a_request_makes_no_external_calls_at_all(client, setup):
    geocoder, router = setup(300.0, [(0.02, 3.00)])
    body = {"start": WEST_QUERY, "finish": EAST_QUERY}

    first = client.post(URL, body, "application/json")
    second = client.post(URL, body, "application/json")

    assert first.json() == second.json()
    assert len(geocoder.calls) == 2, "both locations cached after the first request"
    assert len(router.calls) == 1, "the route is cached too"


def test_a_differently_spelled_but_identical_location_reuses_the_geocode(client, setup):
    geocoder, _ = setup(300.0, [(0.02, 3.00)])

    client.post(URL, {"start": WEST_QUERY, "finish": EAST_QUERY}, "application/json")
    client.post(URL, {"start": WEST_QUERY.lower(), "finish": EAST_QUERY}, "application/json")

    assert len(geocoder.calls) == 2


def test_the_number_of_stations_does_not_change_the_number_of_external_calls(client, setup):
    geocoder, router = setup(
        1800.0, [(index / 60, 3.00 + index * 0.01) for index in range(1, 60)]
    )  # first station is already inside the start window

    client.post(URL, {"start": WEST_QUERY, "finish": EAST_QUERY}, "application/json")

    assert len(geocoder.calls) == 2
    assert len(router.calls) == 1


# --- documentation endpoints -------------------------------------------------


def test_the_openapi_schema_is_served(client, db):
    response = client.get("/api/schema/")

    assert response.status_code == 200
    assert b"optimizeRoute" in response.content


def test_the_swagger_page_is_served(client, db):
    assert client.get("/api/docs/").status_code == 200


def GeocodedLocationFactory(query, latitude, longitude, country_code):
    from integrations.geocoding.base import GeocodedLocation

    return GeocodedLocation(
        query=query,
        coordinate=Coordinate(latitude, longitude),
        display_name=f"{query}, Somewhere",
        country_code=country_code,
    )


def test_the_endpoint_is_rate_limited(client, setup, monkeypatch):
    """The API fronts two free services, so one caller cannot spend their budget freely.

    DRF reads the rate into a class attribute at import time, so the limit is
    lowered there rather than through the settings fixture.
    """
    from rest_framework.throttling import AnonRateThrottle

    monkeypatch.setattr(AnonRateThrottle, "THROTTLE_RATES", {"anon": "2/min"})
    setup(300.0, [(0.02, 3.00)])
    body = {"start": WEST_QUERY, "finish": EAST_QUERY}

    statuses = [client.post(URL, body, "application/json").status_code for _ in range(3)]

    assert statuses == [200, 200, 429]
    assert client.post(URL, body, "application/json").json()["error"]["code"] == "THROTTLED"
