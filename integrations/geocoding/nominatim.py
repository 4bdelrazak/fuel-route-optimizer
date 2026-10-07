"""Nominatim geocoding provider.

Nominatim is free and keyless but its usage policy allows roughly one request a
second, so every lookup goes through the cache in
`routes.services.geocoding_cache` and a request only ever reaches the network for
a location nobody has resolved yet.

The query is intentionally *not* constrained with `countrycodes=us`. Doing so
would quietly snap "Toronto, ON" onto some same-named US place; instead we
resolve the location honestly and reject it on the country we get back.
"""

from __future__ import annotations

import logging

import requests

from core.errors import GeocodingServiceUnavailable, LocationNotFound
from core.geo import Coordinate
from integrations.geocoding.base import GeocodedLocation

logger = logging.getLogger(__name__)


class NominatimGeocodingProvider:
    def __init__(self, base_url: str, user_agent: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._timeout = timeout_seconds

    def geocode(self, query: str) -> GeocodedLocation:
        logger.info("Requesting Nominatim geocode")
        try:
            response = requests.get(
                f"{self._base_url}/search",
                params={
                    "q": query,
                    "format": "jsonv2",
                    "limit": 1,
                    "addressdetails": 1,
                },
                headers={"User-Agent": self._user_agent, "Accept-Language": "en"},
                timeout=self._timeout,
            )
        except requests.Timeout as exc:
            raise GeocodingServiceUnavailable(
                "The geocoding service did not respond in time. Please try again."
            ) from exc
        except requests.RequestException as exc:
            raise GeocodingServiceUnavailable from exc

        if response.status_code == 429:
            raise GeocodingServiceUnavailable(
                "The geocoding service is rate limiting requests. Please try again shortly."
            )
        if response.status_code >= 400:
            logger.warning("Nominatim returned HTTP %s", response.status_code)
            raise GeocodingServiceUnavailable

        try:
            results = response.json()
        except ValueError as exc:
            raise GeocodingServiceUnavailable(
                "The geocoding service returned an unreadable response."
            ) from exc

        if not isinstance(results, list) or not results:
            raise LocationNotFound(f"Could not find a location matching {query!r}.")

        first = results[0]
        try:
            coordinate = Coordinate(float(first["lat"]), float(first["lon"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise GeocodingServiceUnavailable(
                "The geocoding service returned an unexpected response."
            ) from exc

        address = first.get("address") or {}
        return GeocodedLocation(
            query=query,
            coordinate=coordinate,
            display_name=str(first.get("display_name") or query),
            country_code=str(address.get("country_code") or "").lower(),
        )
