"""Choose where to buy fuel, and how much, for the cheapest practical trip.

Model
-----
The tank starts empty, so every gallon burned has to be bought somewhere. The
driver fuels up where the trip starts and then pulls over only when the range
forces it, so a plan has two parts:

  * `start_fill`  - the fuel bought before departing, priced at the cheapest
                    station in the corridor near the start.
  * `fuel_stops`  - the pull-overs the range forces during the drive. Empty for
                    any route inside the vehicle's range.

Algorithm
---------
Stations reduce to points on a line with a mile position and a price, so no
geography is left by the time the policy runs. It is three rules, in order:

  1. If the destination is within range, buy exactly the fuel needed to finish
     and drive there. The vehicle never stops once it can reach the end, which is
     what keeps `fuel_stops` empty on a short route.
  2. Otherwise a stop is unavoidable, so aim at the cheapest station still in
     range, preferring the farthest when prices tie so fewer stops are made.
  3. Buy only as much as the trip to that station needs when it is cheaper than
     here, and fill the tank when it is not, because then this is the cheapest
     fuel for the whole reachable stretch ahead. Skip the purchase outright when
     it would be too small to be worth pulling over for and the fuel aboard
     already covers the drive to that station.

Rules 2 and 3 only move forward and only ever target a station already in range,
so the range limit holds by construction rather than by a check after the fact.

Why this policy
---------------
The textbook optimum for the unconstrained gas-station problem is a different
greedy: buy just enough to reach the next *cheaper* station. It was implemented
and measured against this one on real routes. It costs 0.2-0.7% less on some
routes, more on others, and it buys fuel in useless dribbles: twenty stops on
Seattle to Miami against ten here, seven of them under five gallons. Rule 1 also
breaks its optimality guarantee, so it is not actually optimal for this problem
either. Aiming at the cheapest reachable station is simpler, makes half as many
stops, and costs within a percent. The numbers are in the README.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import pairwise

from core.errors import NoFeasibleFuelPlan
from routes.services.route_projection import ProjectedStation

logger = logging.getLogger(__name__)

DISTANCE_TOLERANCE_MILES = 0.5
"""Slack applied to every range comparison.

Route geometry is simplified and station coordinates are city centroids, so mile
positions carry real error, not just floating-point error. Without this slack a
route of almost exactly 500 miles would be told to stop for fuel it does not
need.
"""

MINIMUM_REPORTED_GALLONS = 1e-6
"""Purchases below this are rounding artefacts and are not reported as stops."""

MINIMUM_USEFUL_GALLONS = 5.0
"""A stop that would buy less than this is not worth pulling over for.

The policy can arrive at the cheapest station in range with a nearly full tank,
where topping up buys a gallon or two. Skipping such a stop costs a fraction of a
percent and removes a third of the stops from a long plan, so it is only skipped
when the fuel already aboard covers the drive to the next candidate.
"""


@dataclass(frozen=True, slots=True)
class VehicleSpec:
    max_range_miles: float
    fuel_economy_mpg: float

    @property
    def tank_capacity_gallons(self) -> float:
        return self.max_range_miles / self.fuel_economy_mpg


@dataclass(frozen=True, slots=True)
class FuelPurchase:
    station: ProjectedStation
    distance_from_previous_miles: float
    gallons: float
    cost: float

    @property
    def price_per_gallon(self) -> float:
        return self.station.station.price_per_gallon


@dataclass(frozen=True, slots=True)
class FuelPlan:
    start_fill: FuelPurchase | None
    fuel_stops: tuple[FuelPurchase, ...]
    total_gallons: float
    total_cost: float
    distance_to_finish_miles: float
    """Miles from the last purchase to the destination."""


@dataclass(frozen=True, slots=True)
class _Point:
    """Somewhere fuel can be bought: the start, or a station along the route."""

    position_miles: float
    price_per_gallon: float
    station: ProjectedStation


EMPTY_PLAN = FuelPlan(None, (), 0.0, 0.0, 0.0)


def plan_fuel(
    route_distance_miles: float,
    stations: list[ProjectedStation],
    vehicle: VehicleSpec,
    start_fill_window_miles: float,
    position_bucket_miles: float,
) -> FuelPlan:
    """The fuel plan for a route, or `NoFeasibleFuelPlan` if none exists."""
    if route_distance_miles <= DISTANCE_TOLERANCE_MILES:
        return EMPTY_PLAN

    candidates = _thin(stations, position_bucket_miles, route_distance_miles)
    if not candidates:
        raise NoFeasibleFuelPlan("No fuel station lies within the search corridor of this route.")

    start = _start_point(candidates, start_fill_window_miles, route_distance_miles)
    points = [start] + [c for c in candidates if c.position_miles > 0.0]
    _require_reachable_chain(points, route_distance_miles, vehicle)
    return _walk(points, route_distance_miles, vehicle)


def _thin(
    stations: list[ProjectedStation], bucket_miles: float, route_distance_miles: float
) -> list[_Point]:
    """Keep the cheapest station per bucket of route distance.

    Station coordinates are city centroids, so two stations a few miles apart
    along the route are not actually distinguishable by position and keeping the
    cheaper one discards no real option. It also bounds the candidate count by
    route length instead of by dataset density, which is what keeps the walk fast
    on a transcontinental route. Ties go to the smaller detour.
    """
    limit = route_distance_miles + DISTANCE_TOLERANCE_MILES
    best: dict[int, ProjectedStation] = {}
    for station in stations:
        if not -DISTANCE_TOLERANCE_MILES <= station.route_distance_miles <= limit:
            continue
        bucket = int(max(0.0, station.route_distance_miles) // bucket_miles)
        incumbent = best.get(bucket)
        if incumbent is None or _rank(station) < _rank(incumbent):
            best[bucket] = station
    ordered = sorted(best.values(), key=lambda s: s.route_distance_miles)
    return [
        _Point(max(0.0, s.route_distance_miles), s.station.price_per_gallon, s) for s in ordered
    ]


def _rank(station: ProjectedStation) -> tuple[float, float]:
    return (station.station.price_per_gallon, station.detour_miles)


def _start_point(
    candidates: list[_Point], window_miles: float, route_distance_miles: float
) -> _Point:
    """The start fill, priced at the cheapest station near the start.

    The trip begins at a street address rather than at a truck stop, so the
    departure tank is priced from the cheapest station the driver could really
    use on the way out of town. Stations past the window are excluded: quoting a
    price from 300 miles ahead for fuel bought at mile zero would understate the
    trip.
    """
    window = min(window_miles, route_distance_miles) + DISTANCE_TOLERANCE_MILES
    nearby = [c for c in candidates if c.position_miles <= window]
    if not nearby:
        raise NoFeasibleFuelPlan(
            "No fuel station was found near the start location, so the vehicle "
            "cannot be fuelled for departure."
        )
    cheapest = min(nearby, key=lambda c: (c.price_per_gallon, c.position_miles))
    return _Point(0.0, cheapest.price_per_gallon, cheapest.station)


def _require_reachable_chain(
    points: list[_Point], route_distance_miles: float, vehicle: VehicleSpec
) -> None:
    """Reject the route unless every gap from start to stations to finish fits the range.

    This is exactly the feasibility condition. One tank covers at most
    `max_range_miles`, so a wider gap cannot be bridged whichever stations are
    chosen; and if no gap is wider, every station is reachable from the one
    before it. Checking it up front means the walk below can never dead-end.
    """
    limit = vehicle.max_range_miles + DISTANCE_TOLERANCE_MILES
    milestones = [p.position_miles for p in points] + [route_distance_miles]
    for previous, current in pairwise(milestones):
        gap = current - previous
        if gap > limit:
            logger.info("Fuel plan infeasible: %.1f mile gap exceeds vehicle range", gap)
            raise NoFeasibleFuelPlan(
                f"A {gap:.0f} mile stretch of this route has no reachable fuel "
                f"station, which exceeds the vehicle's "
                f"{vehicle.max_range_miles:.0f} mile range."
            )


def _walk(points: list[_Point], route_distance_miles: float, vehicle: VehicleSpec) -> FuelPlan:
    """Drive the policy from the start to the destination, recording every purchase."""
    reach = vehicle.max_range_miles + DISTANCE_TOLERANCE_MILES
    mpg = vehicle.fuel_economy_mpg
    capacity = vehicle.tank_capacity_gallons

    purchases: list[FuelPurchase] = []
    index = 0
    fuel_gallons = 0.0
    last_purchase_position = 0.0

    while True:
        current = points[index]
        position = current.position_miles
        remaining = route_distance_miles - position

        if remaining <= reach:
            # Rule 1. Not capped at tank capacity: within the half-mile tolerance
            # a cap would silently under-fuel the trip and break the arithmetic
            # that `total_gallons * mpg == distance`.
            gallons = remaining / mpg - fuel_gallons
            next_index = None
        else:
            # Rule 2.
            next_index = _cheapest_reachable(points, index, position + reach)
            if next_index is None:
                # Unreachable: `_require_reachable_chain` already proved every
                # gap fits the range. Kept so a future change to that check
                # fails loudly instead of planning an impossible trip.
                raise NoFeasibleFuelPlan
            # Rule 3.
            if points[next_index].price_per_gallon < current.price_per_gallon:
                to_cover = points[next_index].position_miles - position
                gallons = min(capacity, to_cover / mpg) - fuel_gallons
            else:
                gallons = capacity - fuel_gallons

        gallons = max(0.0, gallons)
        if (
            next_index is not None
            and gallons < MINIMUM_USEFUL_GALLONS
            and _can_coast_to(fuel_gallons, mpg, points[next_index].position_miles - position)
        ):
            gallons = 0.0

        if gallons > MINIMUM_REPORTED_GALLONS:
            purchases.append(
                FuelPurchase(
                    station=current.station,
                    distance_from_previous_miles=position - last_purchase_position,
                    gallons=gallons,
                    cost=gallons * current.price_per_gallon,
                )
            )
            last_purchase_position = position
            fuel_gallons += gallons

        if next_index is None:
            break
        fuel_gallons = max(0.0, fuel_gallons - (points[next_index].position_miles - position) / mpg)
        index = next_index

    return FuelPlan(
        start_fill=purchases[0] if purchases else None,
        fuel_stops=tuple(purchases[1:]),
        total_gallons=sum(p.gallons for p in purchases),
        total_cost=sum(p.cost for p in purchases),
        distance_to_finish_miles=route_distance_miles - last_purchase_position,
    )


def _cheapest_reachable(points: list[_Point], index: int, limit: float) -> int | None:
    """Index of the cheapest point ahead within `limit`; the farthest wins ties.

    Preferring the farthest of equally priced options means fewer stops, which is
    what a driver wants when the cost is identical either way.
    """
    best: int | None = None
    for candidate in range(index + 1, len(points)):
        if points[candidate].position_miles > limit:
            break
        if best is None or _reach_rank(points[candidate]) < _reach_rank(points[best]):
            best = candidate
    return best


def _reach_rank(point: _Point) -> tuple[float, float]:
    return (point.price_per_gallon, -point.position_miles)


def _can_coast_to(fuel_gallons: float, mpg: float, distance_miles: float) -> bool:
    """Whether the fuel already aboard covers `distance_miles`."""
    return fuel_gallons * mpg >= distance_miles - DISTANCE_TOLERANCE_MILES
