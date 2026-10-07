"""Request validation and response shaping for the optimize endpoint.

The response serializers read the service-layer dataclasses directly, so the
OpenAPI schema and the JSON a client receives can never drift apart.
"""

from __future__ import annotations

from rest_framework import serializers


class RoundedFloatField(serializers.FloatField):
    """A float rendered at a fixed number of decimals.

    Distances, gallons and money are reported at the precision they are actually
    known to; raw floats would leak seventeen meaningless digits.
    """

    def __init__(self, decimals: int, **kwargs) -> None:
        self.decimals = decimals
        kwargs.setdefault("read_only", True)
        super().__init__(**kwargs)

    def to_representation(self, value) -> float:
        return round(float(value), self.decimals)


class OptimizeRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=200,
        trim_whitespace=True,
        allow_blank=False,
        help_text='Start location in the USA, for example "Boston, MA".',
    )
    finish = serializers.CharField(
        max_length=200,
        trim_whitespace=True,
        allow_blank=False,
        help_text='Finish location in the USA, for example "New York, NY".',
    )


class LocationSerializer(serializers.Serializer):
    input = serializers.CharField(source="query", read_only=True)
    resolved_name = serializers.CharField(source="display_name", read_only=True)
    latitude = RoundedFloatField(6, source="coordinate.latitude")
    longitude = RoundedFloatField(6, source="coordinate.longitude")


class GeometrySerializer(serializers.Serializer):
    """The route as a GeoJSON LineString, ready to drop onto a map."""

    type = serializers.SerializerMethodField()
    coordinates = serializers.SerializerMethodField()

    def get_type(self, _route) -> str:
        return "LineString"

    def get_coordinates(self, route) -> list[list[float]]:
        return [[round(point.longitude, 5), round(point.latitude, 5)] for point in route.geometry]


class RouteSerializer(serializers.Serializer):
    distance_miles = RoundedFloatField(1)
    duration_minutes = RoundedFloatField(1)
    geometry = serializers.SerializerMethodField()

    def get_geometry(self, route) -> dict:
        return GeometrySerializer(route).data


class VehicleSerializer(serializers.Serializer):
    max_range_miles = RoundedFloatField(1)
    fuel_economy_mpg = RoundedFloatField(1)
    tank_capacity_gallons = RoundedFloatField(2)


class StationSerializer(serializers.Serializer):
    opis_id = serializers.IntegerField(source="station.opis_id", read_only=True)
    name = serializers.CharField(source="station.name", read_only=True)
    address = serializers.CharField(source="station.address", read_only=True)
    city = serializers.CharField(source="station.city", read_only=True)
    state = serializers.CharField(source="station.state", read_only=True)
    latitude = RoundedFloatField(6, source="station.coordinate.latitude")
    longitude = RoundedFloatField(6, source="station.coordinate.longitude")
    route_distance_miles = RoundedFloatField(1)
    detour_miles = RoundedFloatField(1)


class FuelPurchaseSerializer(serializers.Serializer):
    station = StationSerializer(read_only=True)
    distance_from_previous_miles = RoundedFloatField(1)
    gallons = RoundedFloatField(2)
    price_per_gallon = RoundedFloatField(3)
    cost = RoundedFloatField(2)


class FuelPlanSerializer(serializers.Serializer):
    start_fill = FuelPurchaseSerializer(read_only=True, allow_null=True)
    fuel_stops = FuelPurchaseSerializer(many=True, read_only=True)
    total_gallons = RoundedFloatField(2)
    total_cost = RoundedFloatField(2)
    distance_to_finish_miles = RoundedFloatField(1)


class TripPlanSerializer(serializers.Serializer):
    start = LocationSerializer(read_only=True)
    finish = LocationSerializer(read_only=True)
    route = RouteSerializer(read_only=True)
    vehicle = VehicleSerializer(read_only=True)
    fuel_plan = FuelPlanSerializer(read_only=True)


class ErrorBodySerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()


class ErrorSerializer(serializers.Serializer):
    error = ErrorBodySerializer()
