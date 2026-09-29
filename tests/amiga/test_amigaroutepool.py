from __future__ import annotations

import pytest

from goldbox import geo
from tools.amiga import route_pool
from tools.amiga.route import RouteError

SOLID_WALL = 1


def _map(*, x: int, y: int, closed: tuple[int, ...] = (), doors: tuple[int, ...] = ()) -> geo.Geo:
    """A GEO with wall art and a solid barrier on `closed` edges, and an open door on `doors`, at one square."""
    data = bytearray(geo.GEO_SIZE)
    i = x + (y << 4)
    for direction in (*closed, *doors):
        shift = 4 if direction in (geo.NORTH, geo.SOUTH) else 0
        plane = geo.WALLS_NORTH_EAST if direction in (geo.NORTH, geo.EAST) else geo.WALLS_SOUTH_WEST
        data[plane + i] |= SOLID_WALL << shift
    for direction in doors:
        data[geo.BARRIERS + i] |= geo.PASSABLE << (2 * direction)
    return geo.Geo(data)


def _loader(walls: geo.Geo):
    return lambda name: walls


KOBOLD_CAVES = {"area": 13, "x": 6, "y": 5, "facing": geo.NORTH}


def test_a_closed_edge_behind_the_party_sends_the_route_forward():
    walls = _map(x=6, y=5, closed=(geo.SOUTH,))
    assert route_pool.pool_turns_about(KOBOLD_CAVES, load_geo=_loader(walls)) is False


def test_an_open_edge_behind_the_party_keeps_the_turn_about():
    walls = _map(x=6, y=5, closed=(geo.NORTH,))
    assert route_pool.pool_turns_about(KOBOLD_CAVES, load_geo=_loader(walls)) is True


def test_an_open_door_behind_the_party_keeps_the_turn_about():
    walls = _map(x=6, y=5, closed=(geo.NORTH,), doors=(geo.SOUTH,))
    assert route_pool.pool_turns_about(KOBOLD_CAVES, load_geo=_loader(walls)) is True


def test_a_square_closed_both_ways_is_refused():
    walls = _map(x=6, y=5, closed=(geo.NORTH, geo.SOUTH))
    with pytest.raises(RouteError, match="no open edge"):
        route_pool.pool_turns_about(KOBOLD_CAVES, load_geo=_loader(walls))


def test_an_area_with_two_maps_keeps_the_turn_about_without_reading_walls():
    def refuse(name):
        raise AssertionError("no wall data should be read")
    place = {"area": 24, "x": 8, "y": 11, "facing": geo.SOUTH}
    assert route_pool.pool_turns_about(place, load_geo=refuse) is True


def test_the_forward_route_has_no_turn_and_the_other_steps_are_unchanged():
    forward = route_pool.POOL_FORWARD
    assert forward.turn is None and route_pool.POOL.turn == "about"
    for got, kept in ((forward.route, route_pool.POOL.route),
                      (forward.measure_route, route_pool.POOL.measure_route)):
        assert ("NP2", "world", "turn") in kept and ("NP2", "world", "turn") not in got
        assert got == tuple(s for s in kept if s != ("NP2", "world", "turn"))
        assert ("NP8", "world", "move") in got


def test_the_manifest_picks_the_route_and_is_cross_checked_against_the_walls():
    walls = _loader(_map(x=6, y=5, closed=(geo.SOUTH,)))
    manifest = {"state_a": KOBOLD_CAVES, "turn_about": False}
    assert route_pool.pool_title_for(manifest, load_geo=walls) is route_pool.POOL_FORWARD
    with pytest.raises(RouteError, match="disagrees"):
        route_pool.pool_title_for(dict(manifest, turn_about=True), load_geo=walls)
    with pytest.raises(RouteError, match="boolean"):
        route_pool.pool_title_for(dict(manifest, turn_about="no"), load_geo=walls)
    # A manifest written before the choice existed keeps the route it was made for.
    assert route_pool.pool_title_for({"state_a": KOBOLD_CAVES}, load_geo=walls) is route_pool.POOL


def test_prepare_records_the_choice(monkeypatch):
    walls = _loader(_map(x=6, y=5, closed=(geo.SOUTH,)))
    real = route_pool.pool_turns_about
    monkeypatch.setattr(route_pool, "_prepare_from", lambda *a, **k: {"state_a": KOBOLD_CAVES})
    monkeypatch.setattr(route_pool, "pool_turns_about",
                        lambda place: real(place, load_geo=walls))
    assert route_pool._prepare_pool(None, None)["turn_about"] is False
