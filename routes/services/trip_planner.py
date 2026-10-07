"""Turn two place names into a route and a fuel plan.

This is the only place that knows the order of operations, and it is the whole
external-call budget of a request:

    1 geocoding call per uncached location  (2 at most)
  + 1 routing call per uncached route       (1 at most)
  + 0 calls of any kind per fuel station

Stations come from one indexed database query over the route's bounding box and
are matched to the route with local geometry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

from core.errors import LocationOutsideUsa
from core.geo import BoundingBox, Coordinate, haversine_miles
from fuel.services.station_finder import stations_within
from integrations.geocoding.base import GeocodedLocation
from integrations.routing.base import Route
from routes.services import caching, providers
from routes.services.fuel_optimizer import EMPTY_PLAN, FuelPlan, VehicleSpec, plan_fuel
from routes.services.route_projection import project_stations

logger = logging.getLogger(__name__)

SAME_LOCATION_MILES = 0.1
"""Below this the start and finish are the same place and no route is needed."""


@dataclass(frozen=True, slots=True)
class TripPlan:
    start: GeocodedLocation
    finish: GeocodedLocation
    route: Route
    vehicle: VehicleSpec
    fuel_plan: FuelPlan


def plan_trip(start_query: str, finish_query: str) -> TripPlan:
    geocoder = providers.geocoding_provider()
    start = _resolve(geocoder, start_query, "start")
    finish = _resolve(geocoder, finish_query, "finish")

    vehicle = VehicleSpec(
        max_range_miles=settings.VEHICLE_MAX_RANGE_MILES,
        fuel_economy_mpg=settings.VEHICLE_FUEL_ECONOMY_MPG,
    )

    if haversine_miles(start.coordinate, finish.coordinate) < SAME_LOCATION_MILES:
        # Same place: there is nothing to route and nothing to burn, so the
        # routing API is not called at all.
        logger.info("Start and finish are the same location; skipping routing call")
        empty_route = Route(0.0, 0.0, [start.coordinate, finish.coordinate])
        return TripPlan(start, finish, empty_route, vehicle, EMPTY_PLAN)

    route = caching.driving_route(providers.routing_provider(), start.coordinate, finish.coordinate)
    stations = _candidate_stations(route.geometry)
    projected = project_stations(
        geometry=route.geometry,
        route_distance_miles=route.distance_miles,
        stations=stations,
        corridor_miles=settings.STATION_CORRIDOR_MILES,
    )
    logger.info(
        "Route of %.0f miles: %d stations in bounding box, %d within corridor",
        route.distance_miles,
        len(stations),
        len(projected),
    )
    fuel_plan = plan_fuel(
        route_distance_miles=route.distance_miles,
        stations=projected,
        vehicle=vehicle,
        start_fill_window_miles=settings.START_FILL_WINDOW_MILES,
        position_bucket_miles=settings.STATION_POSITION_BUCKET_MILES,
    )
    return TripPlan(start, finish, route, vehicle, fuel_plan)


def _resolve(geocoder, query: str, label: str) -> GeocodedLocation:
    location = caching.geocode(geocoder, query)
    if location.country_code != "us":
        raise LocationOutsideUsa(
            f"The {label} location {query!r} resolved to "
            f"{location.display_name!r}, which is outside the USA."
        )
    return location


def _candidate_stations(geometry: list[Coordinate]):
    box = BoundingBox.around(geometry).padded(settings.STATION_CORRIDOR_MILES)
    return stations_within(box)
