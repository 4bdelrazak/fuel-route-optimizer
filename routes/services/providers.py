"""Construct the configured external providers.

One place builds them, so tests patch one seam and a different provider is a
one-line change here.
"""

from __future__ import annotations

from django.conf import settings

from integrations.geocoding.base import GeocodingProvider
from integrations.geocoding.nominatim import NominatimGeocodingProvider
from integrations.routing.base import RoutingProvider
from integrations.routing.osrm import OsrmRoutingProvider


def routing_provider() -> RoutingProvider:
    return OsrmRoutingProvider(
        base_url=settings.OSRM_BASE_URL,
        timeout_seconds=settings.OSRM_TIMEOUT_SECONDS,
    )


def geocoding_provider() -> GeocodingProvider:
    return NominatimGeocodingProvider(
        base_url=settings.NOMINATIM_BASE_URL,
        user_agent=settings.NOMINATIM_USER_AGENT,
        timeout_seconds=settings.NOMINATIM_TIMEOUT_SECONDS,
    )
