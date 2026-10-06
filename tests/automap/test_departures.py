"""The departures table: each row names something that exists."""
from __future__ import annotations

from itertools import combinations

from automap import departures, fasttravel


def test_every_route_row_names_a_route_of_its_own_title_that_cannot_fight():
    for row in departures.DEPARTURES:
        if row.route_to is None:
            continue
        assert row.title == departures.POOL_OF_RADIANCE, row
        assert fasttravel.ADDRESSES[row.title].has_exit_reentry, row
        for area in row.areas:
            route = fasttravel.EXIT_ROUTES[(area, row.route_to)]
            assert not route.combat, (area, row.route_to)


def test_no_two_rows_overlap():
    for one, other in combinations(departures.DEPARTURES, 2):
        if one.title != other.title or not one.ports & other.ports:
            continue
        assert one.areas.isdisjoint(other.areas), (one, other)


def test_a_row_is_found_by_title_port_and_area():
    assert departures.find("pool-of-radiance", "c64", 13, 0).member
    assert departures.find("pool-of-radiance", "amiga", 16, 0).route_to == 27
    assert departures.find("pool-of-radiance", "c64", 0, 18) is None
    assert departures.find("secret-of-the-silver-blades", "c64", 16, 0) is None


def test_the_pools_of_darkness_row_is_dormant_and_amiga_only():
    row = departures.find("pools-of-darkness", "amiga", 17, 19,
                          to_overland=False)
    assert row.writes == ((0x24, 0), (0x22, 1))
    assert departures.find("pools-of-darkness", "amiga", 17, 19) is None
    assert departures.find("pools-of-darkness", "amiga", 17, 19,
                           to_overland=True) is None
    assert departures.find("pools-of-darkness", "c64", 17, 19,
                           to_overland=False) is None
    assert departures.find("pools-of-darkness", "amiga", 19, 17,
                           to_overland=False) is None


def test_a_guard_tests_the_byte_the_way_its_operation_says():
    assert departures.Guard(1, "==", 3).holds(3)
    assert departures.Guard(1, "!=", 3).holds(4)
    assert not departures.Guard(1, "not in", (254, 255)).holds(255)
    assert departures.Guard(1, "bits", 0x08).holds(0x18)
    assert not departures.Guard(1, "bits", 0x08).holds(0x10)


def test_applies_is_none_when_a_byte_or_the_party_cannot_be_read():
    row = departures.find("pool-of-radiance", "c64", 13, 0)
    assert departures.applies(row, lambda a: None, None) is None
    assert departures.applies(row, lambda a: 0, ["PRINCESS FATIMA"])
    assert departures.applies(row, lambda a: 0, ["BRUTUS"]) is False
    row = departures.find("pool-of-radiance", "c64", 16, 0)
    assert departures.applies(row, lambda a: None, None) is None
    assert departures.applies(row, lambda a: 255, None) is False
