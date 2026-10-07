import math

import pytest

from core.geo import BoundingBox, Coordinate, cumulative_miles, haversine_miles, point_to_segment

BOSTON = Coordinate(42.3601, -71.0589)
NEW_YORK = Coordinate(40.7128, -74.0060)
LOS_ANGELES = Coordinate(34.0522, -118.2437)


def test_haversine_matches_known_great_circle_distances():
    # Published great-circle distances, good to about a mile.
    assert haversine_miles(BOSTON, NEW_YORK) == pytest.approx(190.0, abs=2.0)
    assert haversine_miles(NEW_YORK, LOS_ANGELES) == pytest.approx(2446.0, abs=5.0)


def test_haversine_is_zero_for_the_same_point_and_symmetric():
    assert haversine_miles(BOSTON, BOSTON) == 0.0
    assert haversine_miles(BOSTON, NEW_YORK) == pytest.approx(haversine_miles(NEW_YORK, BOSTON))


def test_coordinate_rejects_out_of_range_values():
    with pytest.raises(ValueError, match="latitude"):
        Coordinate(91.0, 0.0)
    with pytest.raises(ValueError, match="longitude"):
        Coordinate(0.0, 181.0)


def test_cumulative_miles_accumulates_and_starts_at_zero():
    points = [Coordinate(35.0, -100.0), Coordinate(35.0, -99.0), Coordinate(35.0, -98.0)]
    distances = cumulative_miles(points)

    assert distances[0] == 0.0
    assert distances[1] == pytest.approx(56.6, abs=0.5)
    assert distances[2] == pytest.approx(2 * distances[1])


def test_point_to_segment_measures_perpendicular_distance_at_the_midpoint():
    start, end = Coordinate(35.0, -100.0), Coordinate(35.0, -99.0)
    # One tenth of a degree of latitude north of the midpoint.
    distance, fraction = point_to_segment(Coordinate(35.1, -99.5), start, end)

    assert distance == pytest.approx(6.9, abs=0.2)
    assert fraction == pytest.approx(0.5, abs=0.01)


def test_point_to_segment_clamps_beyond_either_end():
    start, end = Coordinate(35.0, -100.0), Coordinate(35.0, -99.0)

    before, fraction_before = point_to_segment(Coordinate(35.0, -101.0), start, end)
    after, fraction_after = point_to_segment(Coordinate(35.0, -98.0), start, end)

    assert fraction_before == 0.0
    assert fraction_after == 1.0
    assert before == pytest.approx(haversine_miles(Coordinate(35.0, -101.0), start), rel=0.01)
    assert after == pytest.approx(haversine_miles(Coordinate(35.0, -98.0), end), rel=0.01)


def test_point_to_segment_handles_a_zero_length_segment():
    point = Coordinate(35.1, -100.0)
    distance, fraction = point_to_segment(point, Coordinate(35.0, -100.0), Coordinate(35.0, -100.0))

    assert fraction == 0.0
    assert distance == pytest.approx(6.9, abs=0.2)


def test_bounding_box_padding_grows_the_box_by_at_least_the_requested_miles():
    box = BoundingBox.around([Coordinate(35.0, -100.0), Coordinate(40.0, -90.0)])
    padded = box.padded(25.0)

    assert padded.min_latitude < box.min_latitude
    assert padded.max_longitude > box.max_longitude
    # A point exactly 25 miles due north of the top edge must fall inside.
    north_edge = Coordinate(box.max_latitude, box.max_longitude)
    assert haversine_miles(
        north_edge, Coordinate(padded.max_latitude, box.max_longitude)
    ) == pytest.approx(25.0, abs=0.5)


def test_bounding_box_padding_is_conservative_in_longitude():
    """Longitude degrees shrink towards the poles, so padding must use the worst case.

    A box spanning Texas to the Canadian border must be padded using the
    northern edge, where a degree of longitude is shortest. Padding at the
    southern edge would leave the northern edge short of the corridor and drop
    valid stations.
    """
    box = BoundingBox.around([Coordinate(25.0, -100.0), Coordinate(49.0, -100.0)])
    padded = box.padded(25.0)

    for latitude in (25.0, 35.0, 49.0):
        reach = haversine_miles(
            Coordinate(latitude, box.min_longitude),
            Coordinate(latitude, padded.min_longitude),
        )
        assert reach >= 25.0 - 0.01, f"padding falls short at latitude {latitude}"


def test_bounding_box_rejects_an_empty_point_list():
    with pytest.raises(ValueError):
        BoundingBox.around([])


def test_bounding_box_padding_stays_inside_valid_coordinates():
    padded = BoundingBox.around([Coordinate(89.9, 179.9)]).padded(500.0)

    assert padded.max_latitude <= 90.0
    assert padded.max_longitude <= 180.0
    assert not math.isnan(padded.min_longitude)
