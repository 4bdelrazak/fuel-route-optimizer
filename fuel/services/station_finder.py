"""Local candidate-station lookup.

Stations are found with one indexed database query over the route's bounding box
and nothing else: no routing or geocoding call is ever made per station, which is
the performance constraint the assignment sets.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.geo import BoundingBox, Coordinate
from fuel.models import FuelStation


@dataclass(frozen=True, slots=True)
class StationRecord:
    """A station as the optimizer sees it, detached from the ORM."""

    opis_id: int
    name: str
    address: str
    city: str
    state: str
    price_per_gallon: float
    coordinate: Coordinate


def stations_within(box: BoundingBox) -> list[StationRecord]:
    """Every station inside the box, as plain records.

    `values_list` keeps this to a single query returning tuples, so a
    transcontinental route costs one round trip and no model instantiation.
    """
    rows = FuelStation.objects.filter(
        latitude__gte=box.min_latitude,
        latitude__lte=box.max_latitude,
        longitude__gte=box.min_longitude,
        longitude__lte=box.max_longitude,
    ).values_list(
        "opis_id", "name", "address", "city", "state", "retail_price", "latitude", "longitude"
    )
    return [
        StationRecord(
            opis_id=opis_id,
            name=name,
            address=address,
            city=city,
            state=state,
            price_per_gallon=float(price),
            coordinate=Coordinate(latitude, longitude),
        )
        for opis_id, name, address, city, state, price, latitude, longitude in rows.iterator()
    ]
