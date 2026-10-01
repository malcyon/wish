"""A status line the game has already moved past is not believed."""
from support.stalestatus import curse_target, walk_into_the_sewers

from automap.state import Automapper, Exploration
from goldbox import c64_port
from goldbox.geo import (
    ATTRIBUTES,
    BARRIERS,
    GEO_SIZE,
    GRID,
    WALLS_NORTH_EAST,
    WALLS_SOUTH_WEST,
    Geo,
)

CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS


def synthetic_map(salt: int) -> Geo:
    """Doors on every edge, so two salts are two maps a resident match tells apart."""
    raw = bytearray(GEO_SIZE)
    for i in range(GRID * GRID):
        raw[WALLS_NORTH_EAST + i] = 0x11
        raw[WALLS_SOUTH_WEST + i] = 0x11
        raw[BARRIERS + i] = 0x55
    raw[ATTRIBUTES] = salt
    return Geo(bytes(raw))


def test_the_sewers_are_entered_at_the_square_the_game_names(tmp_path, monkeypatch):
    mapper = walk_into_the_sewers(synthetic_map(1), synthetic_map(2),
                                  tmp_path, monkeypatch)
    state = mapper.state
    assert state.area == "GEO03"
    assert (state.x, state.y, state.facing) == (0, 0, 2)
    assert (14, 15) not in state.exploration


def arrive_in_the_sewers(arrival, tmp_path, monkeypatch):
    """Tilverton, then the sewers' map loaded with the engine at *arrival* and
    the line without coordinates, all on one target whose bytes change in place."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    town, sewers = synthetic_map(1), synthetic_map(2)
    target = curse_target("S 8:37 14,15", (14, 15, 2), town)
    mapper = Automapper(target, {"GEO01": town, "GEO03": sewers},
                        area="GEO01", title=CURSE.title)
    for _ in range(mapper.RESIDENT_EVERY - 1):
        mapper.poll()
    go(target, mapper, (*arrival, 2), sewers)
    assert mapper.state.area == "GEO03"
    return target, mapper, sewers


def go(target, mapper, triple, geo=None, polls=1):
    target.memory.update(curse_target("S 8:37", triple, geo).memory)
    for _ in range(polls):
        mapper.poll()


def test_an_adjacent_first_step_confirms_the_arrival(tmp_path, monkeypatch):
    target, mapper, _ = arrive_in_the_sewers((0, 0), tmp_path, monkeypatch)
    go(target, mapper, (0, 1, 2))
    go(target, mapper, (7, 7, 2), polls=3)
    assert (mapper.state.x, mapper.state.y) == (0, 1)
    assert (0, 0) in mapper.state.exploration


def test_an_overturned_arrival_leaves_no_trace(tmp_path, monkeypatch):
    target, mapper, sewers = arrive_in_the_sewers((14, 15), tmp_path, monkeypatch)
    assert (14, 15) in mapper.state.exploration
    go(target, mapper, (0, 0, 2), polls=2)
    state = mapper.state
    assert (state.x, state.y) == (0, 0)
    expected = Exploration()
    expected.visit(0, 0, sewers)
    assert state.exploration.seen == expected.seen
    assert state.exploration.trail == [(0, 0)]


def test_a_fresh_connection_is_not_provisional(tmp_path, monkeypatch):
    target, mapper, sewers = arrive_in_the_sewers((0, 0), tmp_path, monkeypatch)
    again = curse_target("S 8:37", (0, 0, 2), sewers)
    mapper.target = again
    mapper.poll()
    go(again, mapper, (7, 7, 2), polls=3)
    assert (mapper.state.x, mapper.state.y) == (0, 0)
