"""A Silver Blades landing is judged against the square for the departure taken.

Four areas place the party by the area it came from, so one table square
cannot be the answer for every Fast Travel departure.
"""

from __future__ import annotations

import pytest
from conftest import load_tools_module

from goldbox import areas

SSBWARP = load_tools_module("ssbwarp")

GAME = areas.SECRET_OF_THE_SILVER_BLADES

# area, departure the table square holds for, that square, another departure,
# and the square that departure lands on.
CASES = [
    (0x10, 0x20, "15,8 W", 0x11, "3,0 W"),
    (0x42, 0x60, "12,13 N", 0x41, "0,7 W"),
    (0x60, 0x61, "15,0 W", 0x62, "0,7 E"),
    (0x61, 0x60, "15,0 W", 0x62, "0,15 E"),
]


@pytest.mark.parametrize("area,home,square,other,elsewhere", CASES)
def test_expected_landing_depends_on_the_departure(area, home, square, other,
                                                   elsewhere):
    row = areas.area_in(area, GAME)
    assert str(row.arrival_for(home)) == square
    assert str(row.arrival_for(other)) == elsewhere


def test_an_area_placed_by_no_departure_has_one_square():
    row = areas.area_in(0x22, GAME)
    assert row.arrival_for(0x10) == row.arrival == row.arrival_for(None)


def _state(area, x, y, facing):
    return {"area": area, "disk": 1, "square": [x, y, facing],
            "resident": {"name": "GEO10"}}


def test_a_landing_at_3_0_w_in_area_16_from_area_17_passes():
    row = areas.area_in(0x10, GAME)
    got = SSBWARP.verdict_of(_state(0x10, 3, 0, 3), row, departure=0x11)
    assert got["arrival"] is True


def test_a_landing_at_the_table_square_from_another_departure_fails():
    row = areas.area_in(0x10, GAME)
    got = SSBWARP.verdict_of(_state(0x10, 15, 8, 3), row, departure=0x11)
    assert got["arrival"] is False


def test_the_recorded_expectation_is_the_departures_square():
    state = {}
    SSBWARP.expect_arrival(state, areas.area_in(0x10, GAME), 0x11)
    assert state["expected_arrival"] == "3,0 W"
