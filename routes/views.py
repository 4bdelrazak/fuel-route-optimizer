"""The optimize endpoint.

The view validates, delegates and responds. Every decision about routing,
candidate stations and fuel lives in `routes.services`.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from routes.serializers import (
    ErrorSerializer,
    OptimizeRequestSerializer,
    TripPlanSerializer,
)
from routes.services.trip_planner import plan_trip


class OptimizeRouteView(APIView):
    """Plan a route between two US locations and pick its cheapest fuel stops."""

    @extend_schema(
        operation_id="optimizeRoute",
        summary="Plan a route and its cost-optimal fuel stops",
        description=(
            "Geocodes both locations, fetches one driving route, and returns the "
            "route geometry together with the cheapest feasible fuel plan for a "
            "vehicle with a 500 mile range and 10 MPG fuel economy.\n\n"
            "The vehicle starts with an empty tank, so `start_fill` is the tank "
            "bought before departing and `fuel_stops` lists only the pull-overs "
            "the range forces during the drive."
        ),
        request=OptimizeRequestSerializer,
        responses={
            200: TripPlanSerializer,
            400: OpenApiResponse(
                ErrorSerializer,
                description="Invalid input, unknown location, or a location outside the USA.",
            ),
            422: OpenApiResponse(
                ErrorSerializer,
                description="No driving route exists, or no feasible fuel plan was found.",
            ),
            503: OpenApiResponse(
                ErrorSerializer, description="A routing or geocoding provider is unavailable."
            ),
        },
        examples=[
            OpenApiExample(
                "Short route",
                value={"start": "Boston, MA", "finish": "New York, NY"},
                request_only=True,
            ),
            OpenApiExample(
                "Long route needing several stops",
                value={"start": "New York, NY", "finish": "Los Angeles, CA"},
                request_only=True,
            ),
        ],
    )
    def post(self, request: Request) -> Response:
        payload = OptimizeRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        plan = plan_trip(
            start_query=payload.validated_data["start"],
            finish_query=payload.validated_data["finish"],
        )
        return Response(TripPlanSerializer(plan).data, status=status.HTTP_200_OK)
