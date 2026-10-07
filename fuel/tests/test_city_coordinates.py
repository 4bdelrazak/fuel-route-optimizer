import pytest

from fuel.services import city_coordinates
from fuel.services.city_coordinates import name_variants, normalize_place_name


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("Big Cabin", "BIGCABIN"),
        ("big cabin", "BIGCABIN"),
        ("Saint Louis", "STLOUIS"),
        ("St. Louis", "STLOUIS"),
        ("Ste. Genevieve", "STGENEVIEVE"),
        ("Mount Vernon", "MTVERNON"),
        ("Mt. Vernon", "MTVERNON"),
        ("Fort Worth", "FTWORTH"),
        ("Ft Worth", "FTWORTH"),
        ("O'Fallon", "OFALLON"),
        ("Winston-Salem", "WINSTONSALEM"),
    ],
)
def test_normalization_collapses_spelling_differences(written, expected):
    assert normalize_place_name(written) == expected


@pytest.mark.parametrize(
    ("census_name", "expected"),
    [
        ("Phoenix city", "PHOENIX"),
        ("Abanda CDP", "ABANDA"),
        ("Mahwah township", "MAHWAH"),
        ("Autaugaville CCD", "AUTAUGAVILLE"),
        ("Indianapolis city (balance)", "INDIANAPOLIS"),
    ],
)
def test_normalization_strips_census_legal_suffixes(census_name, expected):
    assert normalize_place_name(census_name) == expected


def test_name_variants_indexes_consolidated_governments_under_their_short_name():
    """The feed writes "Nashville"; the Census writes the full legal name."""
    variants = name_variants("Nashville-Davidson metropolitan government (balance)")

    assert "NASHVILLE" in variants


def test_name_variants_keeps_genuinely_hyphenated_names_whole():
    assert "WINSTONSALEM" in name_variants("Winston-Salem city")


def test_lookup_resolves_cities_from_the_bundled_gazetteer():
    phoenix = city_coordinates.lookup("Phoenix", "AZ")

    assert phoenix is not None
    assert phoenix.latitude == pytest.approx(33.5, abs=0.5)
    assert phoenix.longitude == pytest.approx(-112.1, abs=0.5)


def test_lookup_is_case_and_spelling_insensitive():
    assert city_coordinates.lookup("saint louis", "MO") == city_coordinates.lookup(
        "St. Louis", "MO"
    )


def test_lookup_is_scoped_by_state():
    """Many states have a Springfield, and they are different places."""
    illinois = city_coordinates.lookup("Springfield", "IL")
    missouri = city_coordinates.lookup("Springfield", "MO")

    assert illinois is not None and missouri is not None
    assert illinois != missouri


def test_lookup_returns_none_for_an_unknown_place():
    assert city_coordinates.lookup("Nowhere At All", "TX") is None
    assert city_coordinates.lookup("Phoenix", "ZZ") is None
