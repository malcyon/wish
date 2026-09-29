"""`geowalk.route` plans over `Geo.is_passable`, and can keep off named squares."""

from gamedata import synthetic_geo

from goldbox.geo import Geo
from tools.areas import geowalk


def _geo():
    return Geo.from_bytes(synthetic_geo())


def test_route_defaults_to_the_shortest_walk():
    path = geowalk.route(_geo(), (8, 10), (12, 10))
    assert path == [(x, 10) for x in range(8, 13)]


def test_route_goes_round_an_avoided_square():
    path = geowalk.route(_geo(), (8, 10), (12, 10), avoid={(10, 10)})
    assert path[0] == (8, 10) and path[-1] == (12, 10)
    assert (10, 10) not in path and len(path) > 5


def test_route_ends_on_an_avoided_goal():
    path = geowalk.route(_geo(), (8, 10), (10, 10), avoid={(10, 10)})
    assert path[-1] == (10, 10)


def test_route_is_none_when_every_way_is_avoided():
    wall = {(10, y) for y in range(16)}
    assert geowalk.route(_geo(), (8, 10), (12, 10), avoid=wall) is None


def test_a_reverse_step_is_one_m_by_default():
    assert geowalk.keys_for([(5, 5), (5, 6)], 0) == ["m"]


def test_a_reverse_step_can_turn_twice_and_step_forward():
    path = [(5, 5), (5, 6), (5, 7), (6, 7)]
    # South is behind a north-facing party; then straight on; then a left turn.
    assert geowalk.keys_for(path, 0, reverse="turn") == [
        "k", "k", "i", "i", "j", "i"]


def test_reverse_option_rejects_an_unknown_value():
    import pytest
    with pytest.raises(ValueError):
        geowalk.keys_for([(5, 5), (5, 6)], 0, reverse="x")
