import pytest

from core.errors import NoRouteFound, RoutingServiceUnavailable
from core.geo import Coordinate
from integrations.routing.osrm import OsrmRoutingProvider
from integrations.tests.conftest import FakeResponse

BOSTON = Coordinate(42.3601, -71.0589)
NEW_YORK = Coordinate(40.7128, -74.0060)
MODULE = "integrations.routing.osrm"

OK_PAYLOAD = {
    "code": "Ok",
    "routes": [
        {
            "distance": 344_000.0,
            "duration": 16_200.0,
            "geometry": {
                "type": "LineString",
                "coordinates": [[-71.0589, 42.3601], [-72.0, 41.5], [-74.0060, 40.7128]],
            },
        }
    ],
}


@pytest.fixture
def provider():
    return OsrmRoutingProvider("https://osrm.example/", timeout_seconds=5.0)


def test_parses_distance_duration_and_geometry(provider, fake_get):
    fake_get(MODULE, FakeResponse(payload=OK_PAYLOAD))

    route = provider.driving_route(BOSTON, NEW_YORK)

    assert route.distance_miles == pytest.approx(213.8, abs=0.2)
    assert route.duration_minutes == pytest.approx(270.0)
    assert route.geometry[0] == Coordinate(42.3601, -71.0589)
    assert route.geometry[-1] == Coordinate(40.7128, -74.0060)


def test_geometry_is_converted_from_geojson_longitude_first_order(provider, fake_get):
    fake_get(MODULE, FakeResponse(payload=OK_PAYLOAD))

    route = provider.driving_route(BOSTON, NEW_YORK)

    middle = route.geometry[1]
    assert (middle.latitude, middle.longitude) == (41.5, -72.0)


def test_one_request_is_made_with_a_timeout_and_geojson_geometry(provider, fake_get):
    calls = fake_get(MODULE, FakeResponse(payload=OK_PAYLOAD))

    provider.driving_route(BOSTON, NEW_YORK)

    assert len(calls) == 1
    assert calls[0]["timeout"] == 5.0
    assert calls[0]["params"]["geometries"] == "geojson"
    assert "-71.0589,42.3601;-74.006,40.7128" in calls[0]["url"]


def test_a_timeout_becomes_a_service_unavailable_error(provider, fake_get, timeout_error):
    fake_get(MODULE, error=timeout_error)

    with pytest.raises(RoutingServiceUnavailable, match="did not respond in time"):
        provider.driving_route(BOSTON, NEW_YORK)


def test_a_connection_failure_becomes_a_service_unavailable_error(
    provider, fake_get, connection_error
):
    fake_get(MODULE, error=connection_error)

    with pytest.raises(RoutingServiceUnavailable):
        provider.driving_route(BOSTON, NEW_YORK)


def test_rate_limiting_is_reported_as_such(provider, fake_get):
    fake_get(MODULE, FakeResponse(status_code=429, payload={}))

    with pytest.raises(RoutingServiceUnavailable, match="rate limiting"):
        provider.driving_route(BOSTON, NEW_YORK)


@pytest.mark.parametrize("status", [400, 403, 500, 502, 503])
def test_http_errors_become_a_service_unavailable_error(provider, fake_get, status):
    fake_get(MODULE, FakeResponse(status_code=status, payload={}))

    with pytest.raises(RoutingServiceUnavailable):
        provider.driving_route(BOSTON, NEW_YORK)


def test_an_unparseable_body_becomes_a_service_unavailable_error(provider, fake_get):
    fake_get(MODULE, FakeResponse(body="<html>down for maintenance</html>"))

    with pytest.raises(RoutingServiceUnavailable, match="unreadable"):
        provider.driving_route(BOSTON, NEW_YORK)


def test_osrms_no_route_code_becomes_no_route_found(provider, fake_get):
    fake_get(MODULE, FakeResponse(payload={"code": "NoRoute", "routes": []}))

    with pytest.raises(NoRouteFound):
        provider.driving_route(BOSTON, NEW_YORK)


def test_an_empty_route_list_becomes_no_route_found(provider, fake_get):
    fake_get(MODULE, FakeResponse(payload={"code": "Ok", "routes": []}))

    with pytest.raises(NoRouteFound):
        provider.driving_route(BOSTON, NEW_YORK)


def test_a_single_point_geometry_becomes_no_route_found(provider, fake_get):
    payload = {
        "code": "Ok",
        "routes": [
            {"distance": 0.0, "duration": 0.0, "geometry": {"coordinates": [[-71.0, 42.0]]}}
        ],
    }
    fake_get(MODULE, FakeResponse(payload=payload))

    with pytest.raises(NoRouteFound):
        provider.driving_route(BOSTON, NEW_YORK)


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "Ok", "routes": [{"duration": 1.0, "geometry": {"coordinates": []}}]},
        {
            "code": "Ok",
            "routes": [{"distance": "far", "duration": 1.0, "geometry": {"coordinates": []}}],
        },
        {"code": "InvalidQuery"},
        [],
        "nope",
    ],
)
def test_unexpected_payload_shapes_never_leak_out_as_a_crash(provider, fake_get, payload):
    fake_get(MODULE, FakeResponse(payload=payload))

    with pytest.raises(RoutingServiceUnavailable):
        provider.driving_route(BOSTON, NEW_YORK)
