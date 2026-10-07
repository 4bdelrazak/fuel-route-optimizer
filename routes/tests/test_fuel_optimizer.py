import random

import pytest

from conftest import projected_station
from core.errors import NoFeasibleFuelPlan
from routes.services.fuel_optimizer import (
    DISTANCE_TOLERANCE_MILES,
    VehicleSpec,
    plan_fuel,
)

VEHICLE = VehicleSpec(max_range_miles=500.0, fuel_economy_mpg=10.0)
WINDOW = 50.0
BUCKET = 5.0


def plan(distance, stations, vehicle=VEHICLE, window=WINDOW, bucket=BUCKET):
    return plan_fuel(distance, stations, vehicle, window, bucket)


def legs(result, distance):
    """Every drive between purchases, plus the final run to the destination."""
    purchases = ([result.start_fill] if result.start_fill else []) + list(result.fuel_stops)
    return [p.distance_from_previous_miles for p in purchases[1:]] + [
        result.distance_to_finish_miles
    ]


# --- the vehicle's constants -------------------------------------------------


def test_tank_capacity_is_derived_from_range_and_economy():
    assert VEHICLE.tank_capacity_gallons == 50.0


# --- a route inside the vehicle's range --------------------------------------


def test_a_short_route_needs_no_stop_but_still_costs_money():
    """The brief's example: 250 miles, 25 gallons, no stops."""
    result = plan(250.0, [projected_station(10.0, 3.00)])

    assert result.fuel_stops == ()
    assert result.total_gallons == pytest.approx(25.0)
    assert result.total_cost == pytest.approx(75.0)
    assert result.start_fill is not None
    assert result.start_fill.gallons == pytest.approx(25.0)
    assert result.distance_to_finish_miles == pytest.approx(250.0)


def test_the_start_fill_is_priced_at_the_cheapest_station_near_the_start():
    stations = [
        projected_station(5.0, 3.50, name="NEAR EXPENSIVE"),
        projected_station(40.0, 3.00, name="NEAR CHEAP"),
        projected_station(200.0, 1.00, name="FAR BARGAIN"),
    ]

    result = plan(250.0, stations)

    assert result.start_fill.station.station.name == "NEAR CHEAP"
    assert result.total_cost == pytest.approx(75.0)


def test_a_bargain_beyond_the_start_window_does_not_price_the_start_fill():
    """Quoting a price from 200 miles ahead for fuel bought at mile zero would lie."""
    result = plan(250.0, [projected_station(10.0, 3.00), projected_station(200.0, 0.50)])

    assert result.start_fill.price_per_gallon == pytest.approx(3.00)


def test_a_route_of_exactly_the_vehicle_range_needs_no_stop():
    result = plan(500.0, [projected_station(10.0, 3.00)])

    assert result.fuel_stops == ()
    assert result.total_gallons == pytest.approx(50.0)


@pytest.mark.parametrize("distance", [499.9, 500.0, 500.0000001, 500.4])
def test_floating_point_noise_near_the_range_limit_does_not_force_a_stop(distance):
    result = plan(distance, [projected_station(10.0, 3.00), projected_station(450.0, 2.00)])

    assert result.fuel_stops == ()


def test_just_past_the_range_limit_does_force_a_stop():
    result = plan(520.0, [projected_station(10.0, 3.00), projected_station(450.0, 2.00)])

    assert len(result.fuel_stops) == 1


def test_a_zero_length_route_buys_nothing():
    result = plan(0.0, [projected_station(10.0, 3.00)])

    assert result.start_fill is None
    assert result.fuel_stops == ()
    assert result.total_cost == 0.0


# --- the deterministic worked example ----------------------------------------


def test_it_skips_an_expensive_station_for_a_cheaper_reachable_one():
    """A at $3.00, B at $4.00, C at $2.80 over a 1,000 mile route.

    From the start the cheapest in range is A, so buy only enough to reach it.
    From A the cheapest in range is C, so skip B entirely and buy enough to reach
    C. From C the destination is in range, so buy the rest there.
    """
    stations = [
        projected_station(10.0, 3.50, name="DEPARTURE"),
        projected_station(100.0, 3.00, name="A"),
        projected_station(400.0, 4.00, name="B"),
        projected_station(550.0, 2.80, name="C"),
    ]

    result = plan(1000.0, stations)

    assert [s.station.station.name for s in result.fuel_stops] == ["A", "C"]
    assert result.start_fill.gallons == pytest.approx(10.0)
    assert result.start_fill.cost == pytest.approx(35.00)
    assert result.fuel_stops[0].gallons == pytest.approx(45.0)
    assert result.fuel_stops[0].cost == pytest.approx(135.00)
    assert result.fuel_stops[1].gallons == pytest.approx(45.0)
    assert result.fuel_stops[1].cost == pytest.approx(126.00)
    assert result.total_gallons == pytest.approx(100.0)
    assert result.total_cost == pytest.approx(296.00)


def test_it_fills_the_tank_when_nothing_cheaper_is_in_reach():
    """At $2.00 with only pricier fuel ahead, take a full 50 gallons."""
    stations = [
        projected_station(10.0, 2.00, name="BARGAIN"),
        projected_station(480.0, 4.00, name="PRICEY"),
        projected_station(900.0, 4.50, name="PRICIER"),
    ]

    result = plan(1200.0, stations, window=50.0)

    assert result.start_fill.gallons == pytest.approx(50.0)
    assert result.start_fill.cost == pytest.approx(100.0)


def test_distance_between_stops_is_reported_from_the_previous_purchase():
    stations = [
        projected_station(10.0, 3.00),
        projected_station(400.0, 2.00),
        projected_station(800.0, 1.00),
    ]

    result = plan(1000.0, stations)

    assert [round(s.distance_from_previous_miles) for s in result.fuel_stops] == [400, 400]
    assert result.distance_to_finish_miles == pytest.approx(200.0)


# --- cost arithmetic ---------------------------------------------------------


@pytest.mark.parametrize("distance", [120.0, 499.0, 780.0, 1550.0, 2800.0])
def test_total_gallons_always_equals_distance_over_fuel_economy(distance):
    stations = [
        projected_station(float(mile), 3.0 + (mile % 7) * 0.1) for mile in range(10, 3000, 120)
    ]

    result = plan(distance, stations)

    assert result.total_gallons * VEHICLE.fuel_economy_mpg == pytest.approx(distance, rel=1e-9)


def test_each_cost_is_its_gallons_times_its_price():
    stations = [
        projected_station(float(mile), 3.0 + (mile % 5) * 0.2) for mile in range(10, 2000, 90)
    ]

    result = plan(1800.0, stations)

    purchases = [result.start_fill, *result.fuel_stops]
    for purchase in purchases:
        assert purchase.cost == pytest.approx(purchase.gallons * purchase.price_per_gallon)
    assert result.total_cost == pytest.approx(sum(p.cost for p in purchases))


# --- the range constraint ----------------------------------------------------


def test_no_leg_of_a_long_plan_exceeds_the_vehicle_range():
    stations = [
        projected_station(float(mile), 3.0 + (mile % 11) * 0.05) for mile in range(10, 3000, 70)
    ]

    result = plan(2800.0, stations)

    assert len(result.fuel_stops) >= 5
    assert max(legs(result, 2800.0)) <= VEHICLE.max_range_miles + DISTANCE_TOLERANCE_MILES


def test_a_smaller_tank_forces_more_stops():
    stations = [projected_station(float(mile), 3.0) for mile in range(10, 1200, 50)]

    big = plan(1000.0, stations, vehicle=VehicleSpec(500.0, 10.0))
    small = plan(1000.0, stations, vehicle=VehicleSpec(200.0, 10.0))

    assert len(small.fuel_stops) > len(big.fuel_stops)
    assert max(legs(small, 1000.0)) <= 200.0 + DISTANCE_TOLERANCE_MILES


# --- infeasible routes -------------------------------------------------------


def test_no_station_anywhere_in_the_corridor_is_rejected():
    with pytest.raises(NoFeasibleFuelPlan, match="within the search corridor"):
        plan(300.0, [])


def test_no_station_near_the_start_is_rejected():
    with pytest.raises(NoFeasibleFuelPlan, match="near the start location"):
        plan(800.0, [projected_station(300.0, 3.00)])


def test_a_gap_wider_than_the_range_is_rejected_with_the_distance():
    """The chain here is start -> mile 10 -> mile 900, so the unbridgeable gap is 890."""
    stations = [projected_station(10.0, 3.00), projected_station(900.0, 3.00)]

    with pytest.raises(NoFeasibleFuelPlan, match="890 mile stretch"):
        plan(1500.0, stations)


def test_a_gap_before_the_destination_wider_than_the_range_is_rejected():
    with pytest.raises(NoFeasibleFuelPlan, match="exceeds the vehicle"):
        plan(1200.0, [projected_station(10.0, 3.00), projected_station(400.0, 3.00)])


# --- candidate thinning ------------------------------------------------------


def test_the_cheaper_of_two_stations_at_the_same_place_is_the_one_used():
    stations = [
        projected_station(10.0, 3.00, name="DEARER"),
        projected_station(11.0, 2.50, name="CHEAPER"),
    ]

    result = plan(200.0, stations, bucket=5.0)

    assert result.start_fill.station.station.name == "CHEAPER"


def test_equally_priced_stations_at_the_same_place_prefer_the_shorter_detour():
    stations = [
        projected_station(10.0, 3.00, detour_miles=20.0, name="LONG DETOUR"),
        projected_station(11.0, 3.00, detour_miles=1.0, name="SHORT DETOUR"),
    ]

    result = plan(200.0, stations, bucket=5.0)

    assert result.start_fill.station.station.name == "SHORT DETOUR"


def test_stations_past_the_destination_are_ignored():
    stations = [projected_station(10.0, 3.00), projected_station(900.0, 0.10, name="PAST THE END")]

    result = plan(300.0, stations)

    assert result.total_cost == pytest.approx(90.0)


# --- reference comparison over random instances ------------------------------


def classic_greedy_cost(distance, positions, prices, vehicle):
    """The textbook optimum for the *unconstrained* gas-station problem.

    At each station, buy just enough to reach the nearest cheaper station in
    range; if none is in range, fill the tank and move to the cheapest in range.
    This is allowed to stop whenever it likes, so it is a lower bound on any
    policy that may not. Used only as a yardstick.
    """
    mpg, capacity = vehicle.fuel_economy_mpg, vehicle.tank_capacity_gallons
    reach = vehicle.max_range_miles
    cost, index, fuel = 0.0, 0, 0.0
    while True:
        position, price = positions[index], prices[index]
        window = [j for j in range(index + 1, len(positions)) if positions[j] <= position + reach]
        cheaper = [j for j in window if prices[j] < price]
        if cheaper and positions[min(cheaper)] < distance:
            target = min(cheaper)
            buy = max(0.0, min(capacity, (positions[target] - position) / mpg) - fuel)
        elif distance - position <= reach:
            cost += max(0.0, (distance - position) / mpg - fuel) * price
            return cost
        else:
            if not window:
                raise AssertionError("instance is infeasible")
            target = min(window, key=lambda j: (prices[j], -positions[j]))
            buy = capacity - fuel
        cost += buy * price
        fuel += buy
        fuel = max(0.0, fuel - (positions[target] - position) / mpg)
        index = target


def naive_nearest_cost(distance, positions, prices, vehicle):
    """Ignore price: always drive to the farthest reachable station and fill up."""
    mpg, capacity = vehicle.fuel_economy_mpg, vehicle.tank_capacity_gallons
    reach = vehicle.max_range_miles
    cost, index, fuel = 0.0, 0, 0.0
    while True:
        position, price = positions[index], prices[index]
        if distance - position <= reach:
            return cost + max(0.0, (distance - position) / mpg - fuel) * price
        window = [j for j in range(index + 1, len(positions)) if positions[j] <= position + reach]
        target = max(window, key=lambda j: positions[j])
        buy = capacity - fuel
        cost += buy * price
        fuel = max(0.0, capacity - (positions[target] - position) / mpg)
        index = target


@pytest.mark.parametrize("seed", range(40))
def test_random_instances_respect_every_invariant_and_beat_a_price_blind_baseline(seed):
    rng = random.Random(seed)
    distance = rng.uniform(600.0, 3000.0)
    # Stations every 80-300 miles, so the chain is always feasible by construction.
    positions, mile = [], rng.uniform(5.0, 40.0)
    while mile < distance:
        positions.append(mile)
        mile += rng.uniform(80.0, 300.0)
    prices = [round(rng.uniform(2.50, 4.50), 3) for _ in positions]
    stations = [
        projected_station(p, c, name=f"S{i}")
        for i, (p, c) in enumerate(zip(positions, prices, strict=True))
    ]

    result = plan(distance, stations, bucket=1.0)

    assert result.total_gallons * 10 == pytest.approx(distance, rel=1e-9)
    assert max(legs(result, distance)) <= VEHICLE.max_range_miles + DISTANCE_TOLERANCE_MILES
    stop_positions = [s.station.route_distance_miles for s in result.fuel_stops]
    assert stop_positions == sorted(stop_positions)
    assert all(0 < p < distance for p in stop_positions)

    # The start fill is priced from the window, so the yardsticks start there too.
    reference_positions = [0.0, *(p for p in positions if p > 0)]
    reference_prices = [
        result.start_fill.price_per_gallon,
        *(c for p, c in zip(positions, prices, strict=True) if p > 0),
    ]
    optimum = classic_greedy_cost(distance, reference_positions, reference_prices, VEHICLE)
    naive = naive_nearest_cost(distance, reference_positions, reference_prices, VEHICLE)

    assert result.total_cost >= optimum - 1e-6, "cannot beat the unconstrained optimum"
    assert result.total_cost <= naive + 1e-6, "must beat a price-blind baseline"
    assert result.total_cost <= optimum * 1.10, "regret against the optimum must stay small"
