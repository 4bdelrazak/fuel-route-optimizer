import pytest

from core.errors import GeocodingServiceUnavailable, LocationNotFound
from integrations.geocoding.nominatim import NominatimGeocodingProvider
from integrations.tests.conftest import FakeResponse

MODULE = "integrations.geocoding.nominatim"

BOSTON_PAYLOAD = [
    {
        "lat": "42.3602534",
        "lon": "-71.0582912",
        "display_name": "Boston, Suffolk County, Massachusetts, United States",
        "address": {"city": "Boston", "state": "Massachusetts", "country_code": "us"},
    }
]


@pytest.fixture
def provider():
    return NominatimGeocodingProvider(
        "https://nominatim.example/", "tests/1.0", timeout_seconds=4.0
    )


def test_parses_coordinates_display_name_and_country(provider, fake_get):
    fake_get(MODULE, FakeResponse(payload=BOSTON_PAYLOAD))

    location = provider.geocode("Boston, MA")

    assert location.query == "Boston, MA"
    assert location.coordinate.latitude == pytest.approx(42.36025, abs=1e-4)
    assert location.coordinate.longitude == pytest.approx(-71.05829, abs=1e-4)
    assert location.country_code == "us"
    assert "Massachusetts" in location.display_name


def test_sends_a_user_agent_and_a_timeout_as_nominatims_policy_requires(provider, fake_get):
    calls = fake_get(MODULE, FakeResponse(payload=BOSTON_PAYLOAD))

    provider.geocode("Boston, MA")

    assert len(calls) == 1
    assert calls[0]["headers"]["User-Agent"] == "tests/1.0"
    assert calls[0]["timeout"] == 4.0
    assert calls[0]["params"]["q"] == "Boston, MA"


def test_the_query_is_not_constrained_to_the_usa(provider, fake_get):
    """A country filter would snap a foreign place onto a same-named US one.

    Rejecting on the country that comes back is honest; filtering the query is
    not.
    """
    calls = fake_get(MODULE, FakeResponse(payload=BOSTON_PAYLOAD))

    provider.geocode("Toronto, ON")

    assert "countrycodes" not in calls[0]["params"]


def test_a_foreign_result_is_returned_with_its_real_country_code(provider, fake_get):
    payload = [
        {
            "lat": "43.6534817",
            "lon": "-79.3839347",
            "display_name": "Toronto, Ontario, Canada",
            "address": {"country_code": "ca"},
        }
    ]
    fake_get(MODULE, FakeResponse(payload=payload))

    assert provider.geocode("Toronto, ON").country_code == "ca"


def test_no_results_becomes_location_not_found(provider, fake_get):
    fake_get(MODULE, FakeResponse(payload=[]))

    with pytest.raises(LocationNotFound, match="Could not find"):
        provider.geocode("Asdfghjkl Qwerty")


def test_a_timeout_becomes_a_service_unavailable_error(provider, fake_get, timeout_error):
    fake_get(MODULE, error=timeout_error)

    with pytest.raises(GeocodingServiceUnavailable, match="did not respond in time"):
        provider.geocode("Boston, MA")


def test_rate_limiting_is_reported_as_such(provider, fake_get):
    fake_get(MODULE, FakeResponse(status_code=429, payload=[]))

    with pytest.raises(GeocodingServiceUnavailable, match="rate limiting"):
        provider.geocode("Boston, MA")


@pytest.mark.parametrize("status", [400, 403, 500, 503])
def test_http_errors_become_a_service_unavailable_error(provider, fake_get, status):
    fake_get(MODULE, FakeResponse(status_code=status, payload=[]))

    with pytest.raises(GeocodingServiceUnavailable):
        provider.geocode("Boston, MA")


def test_an_unparseable_body_becomes_a_service_unavailable_error(provider, fake_get):
    fake_get(MODULE, FakeResponse(body="<html>rate limited</html>"))

    with pytest.raises(GeocodingServiceUnavailable, match="unreadable"):
        provider.geocode("Boston, MA")


@pytest.mark.parametrize(
    "payload",
    [[{"display_name": "no coordinates"}], [{"lat": "abc", "lon": "def"}], {"not": "a list"}],
)
def test_unexpected_payload_shapes_never_leak_out_as_a_crash(provider, fake_get, payload):
    fake_get(MODULE, FakeResponse(payload=payload))

    with pytest.raises((GeocodingServiceUnavailable, LocationNotFound)):
        provider.geocode("Boston, MA")


def test_a_result_without_an_address_block_has_no_country_and_is_rejected_upstream(
    provider, fake_get
):
    fake_get(MODULE, FakeResponse(payload=[{"lat": "1.0", "lon": "2.0", "display_name": "x"}]))

    assert provider.geocode("somewhere").country_code == ""
