"""Application-level errors.

Every failure a client can observe is one of these. They carry a stable machine
code so the API never leaks an external service's error text or a stack trace.
"""

from __future__ import annotations

from rest_framework import status


class ApiError(Exception):
    """Base class for errors rendered as `{"error": {"code", "message"}}`."""

    code = "INTERNAL_ERROR"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class LocationNotFound(ApiError):
    code = "LOCATION_NOT_FOUND"
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "The location could not be found."


class LocationOutsideUsa(ApiError):
    code = "LOCATION_OUTSIDE_USA"
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "Only locations inside the USA are supported."


class NoRouteFound(ApiError):
    code = "NO_ROUTE_FOUND"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_message = "No driving route exists between these locations."


class NoFeasibleFuelPlan(ApiError):
    code = "NO_FEASIBLE_FUEL_PLAN"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_message = "No fuel station is reachable within the vehicle's maximum range."


class RoutingServiceUnavailable(ApiError):
    code = "ROUTING_SERVICE_UNAVAILABLE"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_message = "The routing service is temporarily unavailable. Please try again."


class GeocodingServiceUnavailable(ApiError):
    code = "GEOCODING_SERVICE_UNAVAILABLE"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_message = "The geocoding service is temporarily unavailable. Please try again."
