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


VERDICTS = [
    # area, departure, landing, passes
    (0x42, 0x41, (0, 7, 3), True),
    (0x42, 0x41, (12, 13, 0), False),
    (0x42, 0x60, (12, 13, 0), True),
    (0x60, 0x62, (0, 7, 1), True),
    (0x60, 0x62, (0, 8, 1), True),
    (0x60, 0x62, (15, 0, 3), False),
    (0x60, 0x61, (15, 0, 3), True),
    (0x61, 0x62, (0, 15, 1), True),
    (0x61, 0x62, (15, 0, 3), False),
    (0x61, 0x60, (15, 0, 3), True),
]


@pytest.mark.parametrize("area,departure,landing,passes", VERDICTS)
def test_verdict_of_judges_areas_66_96_and_97_by_departure(
        area, departure, landing, passes):
    row = areas.area_in(area, GAME)
    got = SSBWARP.verdict_of(_state(area, *landing), row, departure=departure)
    assert got["arrival"] is passes


class _Sess:
    def settle(self, n):
        pass


def _return(monkeypatch, tmp_path, departure):
    seen = []
    monkeypatch.setattr(SSBWARP, "idle_in_key_window", lambda s, a: 1)
    monkeypatch.setattr(SSBWARP, "wait_idle", lambda s, a, t=None: (True, 0))

    def measure(sess, addr, maps, row, out, tag, departure=None):
        seen.append(departure)
        return {"square": [3, 0, 3], "area": 0x10,
                "resident": {"name": "GEO10"}, "disk": 1}

    monkeypatch.setattr(SSBWARP, "measure", measure)

    class FT:
        def apply_back(self, target):
            return type("O", (), {"ok": True, "message": "m", "writes": []})()

    row = areas.area_in(0x10, GAME)
    out = SSBWARP.return_via_actions(_Sess(), None, {}, FT(), None, row,
                                     tmp_path, "back1-11", 0x10,
                                     departure=departure)
    return seen, out


def test_return_via_actions_judges_the_landing_by_its_departure(
        monkeypatch, tmp_path):
    seen, out = _return(monkeypatch, tmp_path, 0x11)
    assert seen == [0x11]
    assert out["verdict"]["arrival"] is True


def test_return_via_actions_without_a_departure_judges_by_the_table_square(
        monkeypatch, tmp_path):
    seen, out = _return(monkeypatch, tmp_path, None)
    assert seen == [None]
    assert out["verdict"]["arrival"] is False


def test_area_96_has_two_squares_for_a_departure_that_is_not_97():
    row = areas.area_in(0x60, GAME)
    assert [str(a) for a in row.arrivals_for(0x62)] == ["0,7 E", "0,8 E"]
    assert [str(a) for a in row.arrivals_for(0x61)] == ["15,0 W"]
