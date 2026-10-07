import pytest

from conftest import FakeGeocoder, FakeRouter, straight_route, us_location
from core.errors import LocationNotFound, RoutingServiceUnavailable
from core.geo import Coordinate
from routes.services import caching

BOSTON = Coordinate(42.3601, -71.0589)
NEW_YORK = Coordinate(40.7128, -74.0060)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("clear_cache")]


@pytest.fixture
def geocoder():
    return FakeGeocoder({"Boston, MA": us_location("Boston, MA", 42.3601, -71.0589)})


def test_a_repeated_geocode_does_not_reach_the_provider(geocoder):
    first = caching.geocode(geocoder, "Boston, MA")
    second = caching.geocode(geocoder, "Boston, MA")

    assert first == second
    assert geocoder.calls == ["Boston, MA"]


@pytest.mark.parametrize("variant", ["boston, ma", "BOSTON, MA", "  Boston,   MA  "])
def test_case_and_spacing_differences_share_one_cache_entry(geocoder, variant):
    caching.geocode(geocoder, "Boston, MA")
    caching.geocode(geocoder, variant)

    assert len(geocoder.calls) == 1


def test_different_locations_do_not_share_a_cache_entry():
    geocoder = FakeGeocoder(
        {
            "Boston, MA": us_location("Boston, MA", 42.36, -71.06),
            "New York, NY": us_location("New York, NY", 40.71, -74.01),
        }
    )

    caching.geocode(geocoder, "Boston, MA")
    caching.geocode(geocoder, "New York, NY")

    assert len(geocoder.calls) == 2


def test_a_failed_geocode_is_not_cached(geocoder):
    """Caching a failure would keep a transient outage alive for a month."""
    for _ in range(2):
        with pytest.raises(LocationNotFound):
            caching.geocode(geocoder, "Asdfghjkl")

    assert len(geocoder.calls) == 2


def test_a_repeated_route_does_not_reach_the_provider():
    router = FakeRouter(straight_route(BOSTON, NEW_YORK, 214.0))

    first = caching.driving_route(router, BOSTON, NEW_YORK)
    second = caching.driving_route(router, BOSTON, NEW_YORK)

    assert first == second
    assert len(router.calls) == 1


def test_the_reverse_direction_is_a_different_route():
    router = FakeRouter(straight_route(BOSTON, NEW_YORK, 214.0))

    caching.driving_route(router, BOSTON, NEW_YORK)
    caching.driving_route(router, NEW_YORK, BOSTON)

    assert len(router.calls) == 2


def test_coordinates_differing_below_a_metre_share_one_cache_entry():
    router = FakeRouter(straight_route(BOSTON, NEW_YORK, 214.0))
    nudged = Coordinate(BOSTON.latitude + 1e-9, BOSTON.longitude)

    caching.driving_route(router, BOSTON, NEW_YORK)
    caching.driving_route(router, nudged, NEW_YORK)

    assert len(router.calls) == 1


def test_a_meaningfully_different_start_is_a_different_route():
    router = FakeRouter(straight_route(BOSTON, NEW_YORK, 214.0))

    caching.driving_route(router, BOSTON, NEW_YORK)
    caching.driving_route(router, Coordinate(42.5, -71.0589), NEW_YORK)

    assert len(router.calls) == 2


def test_a_failed_route_lookup_is_not_cached():
    router = FakeRouter(error=RoutingServiceUnavailable())

    for _ in range(2):
        with pytest.raises(RoutingServiceUnavailable):
            caching.driving_route(router, BOSTON, NEW_YORK)

    assert len(router.calls) == 2


def test_a_cached_route_round_trips_its_geometry():
    router = FakeRouter(straight_route(BOSTON, NEW_YORK, 214.0, duration_minutes=282.0))

    caching.driving_route(router, BOSTON, NEW_YORK)
    cached = caching.driving_route(router, BOSTON, NEW_YORK)

    assert cached.distance_miles == 214.0
    assert cached.duration_minutes == 282.0
    assert cached.geometry == [BOSTON, NEW_YORK]
