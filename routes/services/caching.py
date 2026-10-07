"""Cache the two external calls a request can make.

Geocoding is cached because Nominatim's usage policy is about one request a
second and "Boston, MA" does not move. Routing is cached because the road network
does not change between two requests either, and it is the slowest call in the
request.

Both are keyed on the resolved input rather than the raw request, so
"boston, ma" and "Boston,  MA" share a geocode entry, and two different spellings
of the same city share a route entry once geocoded.
"""

from __future__ import annotations

import hashlib
import logging

from django.conf import settings
from django.core.cache import cache

from core.geo import Coordinate
from integrations.geocoding.base import GeocodedLocation, GeocodingProvider
from integrations.routing.base import Route, RoutingProvider

logger = logging.getLogger(__name__)

COORDINATE_KEY_DECIMALS = 5
"""About one metre. Finer than this would only ever miss the cache."""


def geocode(provider: GeocodingProvider, query: str) -> GeocodedLocation:
    normalized = " ".join(query.lower().split())
    key = "geocode:" + hashlib.sha256(normalized.encode()).hexdigest()[:32]
    cached = cache.get(key)
    if cached is not None:
        logger.info("Geocode cache hit")
        return cached
    location = provider.geocode(query)
    cache.set(key, location, settings.GEOCODE_CACHE_SECONDS)
    return location


def driving_route(provider: RoutingProvider, start: Coordinate, finish: Coordinate) -> Route:
    key = (
        "route:"
        f"{round(start.latitude, COORDINATE_KEY_DECIMALS)},"
        f"{round(start.longitude, COORDINATE_KEY_DECIMALS)}:"
        f"{round(finish.latitude, COORDINATE_KEY_DECIMALS)},"
        f"{round(finish.longitude, COORDINATE_KEY_DECIMALS)}"
    )
    cached = cache.get(key)
    if cached is not None:
        logger.info("Route cache hit")
        return cached
    route = provider.driving_route(start, finish)
    cache.set(key, route, settings.ROUTE_CACHE_SECONDS)
    return route
