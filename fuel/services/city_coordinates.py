"""Offline city/state -> coordinate lookup.

The supplied fuel dataset has no latitude or longitude, only `City` and `State`,
so stations have to be placed on the map before they can be matched to a route.
Geocoding 3,800 distinct cities over Nominatim would take over an hour at its
one-request-a-second policy, so coordinates come from a bundled gazetteer built
from the US Census Bureau Gazetteer files (public domain) by
`scripts/build_city_coordinates.py`.

Place names are matched on a normalised key rather than verbatim, because the
Census spells things differently from the fuel feed: "St. Louis" against
"Saint Louis", "Nashville-Davidson metropolitan government (balance)" against
"Nashville", "Mahwah township" against "Mahwah". Normalisation lifts coverage of
the dataset's US rows from 93.7% to 97.3%.

Consequence worth knowing: a station sits at its city's centroid, not at its
real forecourt, which is the reason the route corridor is tens of miles wide
rather than a few (see `routes.services.route_projection`).
"""

from __future__ import annotations

import csv
import gzip
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from core.geo import Coordinate

_PLACE_SUFFIXES = re.compile(
    r"\s+(census designated place|CDP|city and borough|charter township|city|town|"
    r"village|borough|municipality|township|CCD|county|comunidad|zona urbana|"
    r"plantation|reservation|district|precinct|division|unorganized territory|UT)$",
    re.IGNORECASE,
)
_ABBREVIATIONS = (
    (re.compile(r"\bSAINT\b"), "ST"),
    (re.compile(r"\bSTE\b"), "ST"),
    (re.compile(r"\bMOUNT\b"), "MT"),
    (re.compile(r"\bFORT\b"), "FT"),
)


def normalize_place_name(name: str) -> str:
    """Collapse a place name to a key that survives spelling differences."""
    without_parentheticals = re.sub(r"\(.*?\)", " ", name)
    trimmed = without_parentheticals.strip()
    previous = None
    while previous != trimmed:
        previous = trimmed
        trimmed = _PLACE_SUFFIXES.sub("", trimmed).strip()
    key = trimmed.upper()
    for pattern, replacement in _ABBREVIATIONS:
        key = pattern.sub(replacement, key)
    return re.sub(r"[^A-Z0-9]", "", key)


def name_variants(name: str) -> set[str]:
    """Keys a gazetteer entry should be reachable by.

    Consolidated city-county governments appear as "Augusta-Richmond County
    consolidated government", which no feed ever writes, so the part before the
    first hyphen is indexed as well.
    """
    stripped = _PLACE_SUFFIXES.sub("", re.sub(r"\(.*?\)", " ", name).strip()).strip()
    candidates = {stripped}
    if "-" in stripped:
        candidates.add(stripped.split("-", 1)[0])
    return {key for key in (normalize_place_name(c) for c in candidates) if key}


@lru_cache(maxsize=1)
def _gazetteer() -> dict[tuple[str, str], tuple[float, float]]:
    path = Path(settings.CITY_COORDINATES_PATH)
    if not path.exists():
        raise FileNotFoundError(
            f"City gazetteer missing at {path}. Run scripts/build_city_coordinates.py."
        )
    table: dict[tuple[str, str], tuple[float, float]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) != 4:
                continue
            key, state, latitude, longitude = row
            table[(key, state)] = (float(latitude), float(longitude))
    return table


def lookup(city: str, state: str) -> Coordinate | None:
    """Coordinate for a city/state pair, or None when the gazetteer has no match."""
    found = _gazetteer().get((normalize_place_name(city), state.strip().upper()))
    return None if found is None else Coordinate(found[0], found[1])
