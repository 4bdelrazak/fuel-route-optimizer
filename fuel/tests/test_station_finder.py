import pytest

from core.geo import BoundingBox
from fuel.services.station_finder import stations_within


@pytest.mark.django_db
def test_returns_only_stations_inside_the_box(make_station, django_assert_num_queries):
    inside = make_station(35.0, -100.0, 3.00, name="INSIDE")
    make_station(45.0, -100.0, 2.50, name="TOO FAR NORTH")
    make_station(35.0, -80.0, 2.00, name="TOO FAR EAST")

    box = BoundingBox(34.0, -101.0, 36.0, -99.0)
    with django_assert_num_queries(1):
        found = stations_within(box)

    assert [s.name for s in found] == ["INSIDE"]
    assert found[0].opis_id == inside.opis_id


@pytest.mark.django_db
def test_price_comes_back_as_a_float_for_the_optimizer(make_station):
    make_station(35.0, -100.0, 3.14159265)

    found = stations_within(BoundingBox(34.0, -101.0, 36.0, -99.0))

    assert isinstance(found[0].price_per_gallon, float)
    assert found[0].price_per_gallon == pytest.approx(3.14159265)


@pytest.mark.django_db
def test_one_query_regardless_of_how_many_stations_match(make_station, django_assert_num_queries):
    """Guards against an N+1 creeping into candidate lookup."""
    for index in range(40):
        make_station(35.0 + index * 0.01, -100.0, 3.00 + index * 0.01)

    with django_assert_num_queries(1):
        found = stations_within(BoundingBox(34.0, -101.0, 36.0, -99.0))

    assert len(found) == 40


@pytest.mark.django_db
def test_returns_nothing_when_the_box_is_empty(make_station):
    make_station(35.0, -100.0, 3.00)

    assert stations_within(BoundingBox(10.0, -20.0, 11.0, -19.0)) == []
