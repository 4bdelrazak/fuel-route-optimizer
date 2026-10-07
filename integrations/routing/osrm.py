"""OSRM routing provider.

OSRM is used because it needs no API key, returns GeoJSON geometry plus distance
and duration in a single request, and is self-hostable, so the one public demo
server is never a hard dependency (see `OSRM_BASE_URL`).

`overview=simplified` is requested deliberately: the full-resolution geometry of
a transcontinental route runs to tens of thousands of vertices, which bloats the
response and slows projection, while the simplification error stays far inside
the station corridor we filter on.
"""

from __future__ import annotations

import logging

import requests

from core.errors import NoRouteFound, RoutingServiceUnavailable
from core.geo import Coordinate
from integrations.routing.base import Route

logger = logging.getLogger(__name__)

METERS_PER_MILE = 1609.344


class OsrmRoutingProvider:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def driving_route(self, start: Coordinate, finish: Coordinate) -> Route:
        url = (
            f"{self._base_url}/route/v1/driving/"
            f"{start.longitude},{start.latitude};{finish.longitude},{finish.latitude}"
        )
        params = {"overview": "simplified", "geometries": "geojson", "alternatives": "false"}
        logger.info("Requesting OSRM route", extra={"url": url})
        try:
            response = requests.get(url, params=params, timeout=self._timeout)
        except requests.Timeout as exc:
            raise RoutingServiceUnavailable(
                "The routing service did not respond in time. Please try again."
            ) from exc
        except requests.RequestException as exc:
            raise RoutingServiceUnavailable from exc

        if response.status_code == 429:
            raise RoutingServiceUnavailable(
                "The routing service is rate limiting requests. Please try again shortly."
            )
        if response.status_code >= 400:
            logger.warning("OSRM returned HTTP %s", response.status_code)
            raise RoutingServiceUnavailable

        try:
            payload = response.json()
        except ValueError as exc:
            raise RoutingServiceUnavailable(
                "The routing service returned an unreadable response."
            ) from exc

        return self._parse(payload)

    @staticmethod
    def _parse(payload: object) -> Route:
        if not isinstance(payload, dict):
            raise RoutingServiceUnavailable("The routing service returned an unexpected response.")
        code = payload.get("code")
        if code == "NoRoute":
            raise NoRouteFound
        if code != "Ok":
            logger.warning("OSRM responded with code %s", code)
            raise RoutingServiceUnavailable

        routes = payload.get("routes") or []
        if not routes:
            raise NoRouteFound
        route = routes[0]
        try:
            distance_meters = float(route["distance"])
            duration_seconds = float(route["duration"])
            raw_geometry = route["geometry"]["coordinates"]
            geometry = [Coordinate(float(lat), float(lon)) for lon, lat in raw_geometry]
        except (KeyError, TypeError, ValueError) as exc:
            raise RoutingServiceUnavailable(
                "The routing service returned an unexpected response."
            ) from exc

        if len(geometry) < 2:
            raise NoRouteFound

        return Route(
            distance_miles=distance_meters / METERS_PER_MILE,
            duration_minutes=duration_seconds / 60.0,
            geometry=geometry,
        )
