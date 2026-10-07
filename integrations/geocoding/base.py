"""Geocoding provider contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.geo import Coordinate


@dataclass(frozen=True, slots=True)
class GeocodedLocation:
    query: str
    coordinate: Coordinate
    display_name: str
    country_code: str
    """ISO 3166-1 alpha-2, lowercased. Used to enforce the USA-only rule."""


class GeocodingProvider(Protocol):
    def geocode(self, query: str) -> GeocodedLocation:
        """Resolve free text to a location, or raise `LocationNotFound` /
        `GeocodingServiceUnavailable`."""
