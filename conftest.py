"""Shared test fixtures.

No test touches the network. The routing and geocoding providers are replaced at
the single seam `routes.services.providers` exposes, and every fixture here is
built from in-memory fakes.
"""

from __future__ import annotations

import pytest

from core.geo import Coordinate
from fuel.models import FuelStation
from integrations.geocoding.base import GeocodedLocation
from integrations.routing.base import Route


class FakeGeocoder:
    """Resolves from a fixed table and counts calls, so tests can assert caching."""

    def __init__(self, table: dict[str, GeocodedLocation]) -> None:
        self.table = table
        self.calls: list[str] = []

    def geocode(self, query: str) -> GeocodedLocation:
        from core.errors import LocationNotFound

        self.calls.append(query)
        try:
            return self.table[query]
        except KeyError:
            raise LocationNotFound(f"Could not find a location matching {query!r}.") from None


class FakeRouter:
    def __init__(self, route: Route | None = None, error: Exception | None = None) -> None:
        self.route = route
        self.error = error
        self.calls: list[tuple[Coordinate, Coordinate]] = []

    def driving_route(self, start: Coordinate, finish: Coordinate) -> Route:
        self.calls.append((start, finish))
        if self.error is not None:
            raise self.error
        assert self.route is not None
        return self.route


def us_location(query: str, latitude: float, longitude: float) -> GeocodedLocation:
    return GeocodedLocation(
        query=query,
        coordinate=Coordinate(latitude, longitude),
        display_name=f"{query}, United States",
        country_code="us",
    )


def straight_route(
    start: Coordinate, finish: Coordinate, distance_miles: float, duration_minutes: float = 600.0
) -> Route:
    """A two-point route whose reported distance is set independently of its geometry.

    Projection rescales along-route positions onto the provider's reported
    distance, so a test can state "a 1,200 mile route" and have station mile
    positions follow, without hand-building a realistic polyline.
    """
    return Route(
        distance_miles=distance_miles, duration_minutes=duration_minutes, geometry=[start, finish]
    )


@pytest.fixture
def patch_providers(monkeypatch):
    """Install fake providers and hand back the two fakes."""

    def install(geocoder: FakeGeocoder, router: FakeRouter):
        monkeypatch.setattr("routes.services.providers.geocoding_provider", lambda: geocoder)
        monkeypatch.setattr("routes.services.providers.routing_provider", lambda: router)
        return geocoder, router

    return install


@pytest.fixture
def clear_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def make_station(db):
    """Create a FuelStation with sensible defaults."""
    counter = iter(range(1, 100_000))

    def factory(latitude: float, longitude: float, price: float, **kwargs) -> FuelStation:
        index = next(counter)
        return FuelStation.objects.create(
            opis_id=kwargs.pop("opis_id", index),
            name=kwargs.pop("name", f"Station {index}"),
            address=kwargs.pop("address", f"{index} Interstate Dr"),
            city=kwargs.pop("city", f"City {index}"),
            state=kwargs.pop("state", "TX"),
            rack_id=kwargs.pop("rack_id", 100),
            retail_price=price,
            latitude=latitude,
            longitude=longitude,
            **kwargs,
        )

    return factory


def projected_station(position_miles: float, price: float, detour_miles: float = 0.0, **kwargs):
    """A station already projected onto a route, for optimizer tests.

    The optimizer only sees a mile position and a price, so these tests do not
    need real geography and stay readable.
    """
    from fuel.services.station_finder import StationRecord
    from routes.services.route_projection import ProjectedStation

    return ProjectedStation(
        station=StationRecord(
            opis_id=kwargs.pop("opis_id", int(position_miles * 100) + 1),
            name=kwargs.pop("name", f"Station at mile {position_miles:g}"),
            address=kwargs.pop("address", "Interstate exit"),
            city=kwargs.pop("city", "Somewhere"),
            state=kwargs.pop("state", "TX"),
            price_per_gallon=price,
            coordinate=Coordinate(kwargs.pop("latitude", 35.0), kwargs.pop("longitude", -100.0)),
        ),
        route_distance_miles=position_miles,
        detour_miles=detour_miles,
    )
