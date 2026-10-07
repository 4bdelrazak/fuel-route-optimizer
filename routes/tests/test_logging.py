"""The assignment asks for logging around specific events, so it is asserted.

The application loggers do not propagate to the root logger, so these use the
`app_logs` fixture rather than `caplog` directly.
"""

import logging

import pytest

from conftest import projected_station
from core.errors import NoFeasibleFuelPlan, RoutingServiceUnavailable
from core.geo import Coordinate
from integrations.geocoding.nominatim import NominatimGeocodingProvider
from integrations.routing.osrm import OsrmRoutingProvider
from integrations.tests.conftest import FakeResponse
from routes.services.fuel_optimizer import VehicleSpec, plan_fuel

VEHICLE = VehicleSpec(500.0, 10.0)


def test_a_routing_request_is_logged(app_logs, monkeypatch):
    payload = {
        "code": "Ok",
        "routes": [
            {
                "distance": 1000.0,
                "duration": 60.0,
                "geometry": {"coordinates": [[-71.0, 42.0], [-74.0, 40.0]]},
            }
        ],
    }
    monkeypatch.setattr(
        "integrations.routing.osrm.requests.get", lambda url, **kw: FakeResponse(payload=payload)
    )

    with app_logs("integrations.routing.osrm") as logs:
        OsrmRoutingProvider("https://osrm.example", 5.0).driving_route(
            Coordinate(42.0, -71.0), Coordinate(40.0, -74.0)
        )

    assert "Requesting OSRM route" in logs.text


def test_a_routing_failure_is_logged_with_its_status(app_logs, monkeypatch):
    monkeypatch.setattr(
        "integrations.routing.osrm.requests.get",
        lambda url, **kw: FakeResponse(status_code=502, payload={}),
    )

    provider = OsrmRoutingProvider("https://osrm.example", 5.0)
    with (
        app_logs("integrations.routing.osrm", logging.WARNING) as logs,
        pytest.raises(RoutingServiceUnavailable),
    ):
        provider.driving_route(Coordinate(42.0, -71.0), Coordinate(40.0, -74.0))

    assert "502" in logs.text


def test_a_geocoding_request_is_logged_without_the_query(app_logs, monkeypatch):
    """The query is a user-supplied location, so it is not written to the log."""
    payload = [
        {"lat": "42.0", "lon": "-71.0", "display_name": "x", "address": {"country_code": "us"}}
    ]
    monkeypatch.setattr(
        "integrations.geocoding.nominatim.requests.get",
        lambda url, **kw: FakeResponse(payload=payload),
    )

    with app_logs("integrations.geocoding.nominatim") as logs:
        NominatimGeocodingProvider("https://nominatim.example", "tests/1.0", 5.0).geocode(
            "221B Baker Street"
        )

    assert "Requesting Nominatim geocode" in logs.text
    assert "Baker Street" not in logs.text


def test_an_optimization_failure_is_logged_with_the_offending_gap(app_logs):
    stations = [projected_station(10.0, 3.00), projected_station(900.0, 3.00)]

    with app_logs("routes.services.fuel_optimizer") as logs, pytest.raises(NoFeasibleFuelPlan):
        plan_fuel(1500.0, stations, VEHICLE, 50.0, 5.0)

    assert "infeasible" in logs.text
    assert "890" in logs.text


@pytest.mark.django_db
def test_the_dataset_import_is_logged(app_logs, tmp_path):
    from django.core.management import call_command

    path = tmp_path / "prices.csv"
    path.write_text(
        "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"
        "1,STOP,Addr,Big Cabin,OK,1,3.10\n",
        encoding="utf-8",
    )

    with app_logs("fuel.management.commands.import_fuel_prices") as logs:
        call_command("import_fuel_prices", str(path), verbosity=0)

    assert "Imported 1 fuel stations" in logs.text
