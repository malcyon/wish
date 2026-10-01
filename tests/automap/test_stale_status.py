"""A status line that disagrees with the engine at an area change is the old area's.

Curse redraws its status line a step late, so on the poll where the new
area is first named the line can still read the old area's square. The
engine's square is taken instead, and that exact line is refused until the
game redraws it. Nothing is held back after that poll: a later disagreement
between the line and the engine is an ordinary jump.
"""
from support.stalestatus import curse_target, walk_into_the_sewers

from automap.area import RESIDENT_GEO
from automap.state import Automapper, AutomapState
from goldbox import c64_port
from goldbox.geo import (
    ATTRIBUTES,
    BARRIERS,
    GEO_SIZE,
    GRID,
    SOUTH,
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


def arrive_in_the_sewers(arrival, tmp_path, monkeypatch, sewers=None):
    """Tilverton, then the sewers' map loaded with the engine at *arrival* while
    the line still reads the town's square, all on one target whose bytes change
    in place."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    town = synthetic_map(1)
    sewers = sewers or synthetic_map(2)
    target = curse_target("S 8:37 14,15", (14, 15, 2), town)
    mapper = Automapper(target, {"GEO01": town, "GEO03": sewers},
                        area="GEO01", title=CURSE.title)
    for _ in range(mapper.RESIDENT_EVERY - 1):
        mapper.poll()
    go(target, mapper, (*arrival, 2), sewers, status="S 8:37 14,15")
    assert mapper.state.area == "GEO03"
    return target, mapper, sewers


def go(target, mapper, triple, geo=None, polls=1, status="S 8:37"):
    target.memory.update(curse_target(status, triple, geo).memory)
    for _ in range(polls):
        mapper.poll()


def stand_then_load_again(target, mapper, polls=4):
    """The engine moves on to (9,9) while `$0400` still holds the same map."""
    go(target, mapper, (9, 9, 2), polls=polls)


def test_a_stationary_arrival_does_not_leak_the_next_load(tmp_path, monkeypatch):
    target, mapper, _ = arrive_in_the_sewers((0, 0), tmp_path, monkeypatch)
    go(target, mapper, (0, 0, 2), polls=2)
    stand_then_load_again(target, mapper)
    state = mapper.state
    assert (state.x, state.y) == (0, 0)
    assert (9, 9) not in state.exploration
    assert (0, 0) in state.exploration


def test_a_revisit_keeps_what_was_explored_before(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    before = AutomapState(title=CURSE.title, area="GEO03")
    before.exploration.seen = {(10, 3), (11, 3), (5, 12)}
    before.save_notes()
    target, mapper, _ = arrive_in_the_sewers((0, 0), tmp_path, monkeypatch)
    go(target, mapper, (0, 0, 2), polls=2)
    stand_then_load_again(target, mapper)
    state = mapper.state
    assert before.exploration.seen <= state.exploration.seen
    assert (0, 0) in state.exploration


def test_a_confirmed_status_jump_after_an_arrival_keeps_it_explored(
        tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    town, sewers = synthetic_map(1), synthetic_map(2)
    target = curse_target("S 8:37 14,15", (14, 15, 2), town)
    mapper = Automapper(target, {"GEO01": town, "GEO03": sewers},
                        area="GEO01", title=CURSE.title)
    for _ in range(mapper.RESIDENT_EVERY - 1):
        mapper.poll()
    target.memory.update(curse_target("S 8:37 14,15", (0, 0, 2), sewers).memory)
    mapper.poll()
    assert mapper.state.area == "GEO03"
    assert (mapper.state.x, mapper.state.y) == (0, 0)
    target.memory.update(curse_target("S 8:38 9,9", (9, 9, 2), sewers).memory)
    mapper.poll()
    mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (9, 9)
    assert (0, 0) in mapper.state.exploration


def sewers_entry_with_a_stale_line(tmp_path, monkeypatch):
    """The area-change poll of `walk_into_the_sewers`, and no more."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    town, sewers = synthetic_map(1), synthetic_map(2)
    target = curse_target("S 8:37 14,15", (14, 15, 2), town)
    mapper = Automapper(target, {"GEO01": town, "GEO03": sewers},
                        area="GEO01", title=CURSE.title)
    for _ in range(mapper.RESIDENT_EVERY - 1):
        mapper.poll()
    target.memory.update(curse_target("S 8:37 14,15", (0, 0, 2), sewers).memory)
    mapper.poll()
    return target, mapper


def test_the_stale_line_is_refused_while_it_stays_on_screen(tmp_path, monkeypatch):
    _, mapper = sewers_entry_with_a_stale_line(tmp_path, monkeypatch)
    for _ in range(4):
        assert (mapper.state.area, mapper.state.x, mapper.state.y,
                mapper.state.facing) == ("GEO03", 0, 0, 2)
        mapper.poll()
    assert (14, 15) not in mapper.state.exploration


def test_the_rejection_ends_when_the_game_redraws_the_line(tmp_path, monkeypatch):
    target, mapper = sewers_entry_with_a_stale_line(tmp_path, monkeypatch)
    mapper.poll()
    target.memory.update(curse_target("S 8:38 1,0", (1, 0, 2), synthetic_map(2)).memory)
    mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (1, 0)


def sewers_edge_move(tmp_path, monkeypatch, sewers=None):
    """The party on (2,15) with the line hiding coordinates, then moved to (9,0)."""
    target, mapper, sewers = arrive_in_the_sewers((2, 15), tmp_path, monkeypatch,
                                                  sewers)
    go(target, mapper, (2, 15, 2), polls=2, status="S 8:50")
    go(target, mapper, (9, 0, 2), polls=3, status="S 8:50")
    return target, mapper


def test_a_hidden_coordinate_edge_move_is_believed_at_the_next_step(
        tmp_path, monkeypatch):
    target, mapper = sewers_edge_move(tmp_path, monkeypatch)
    assert (mapper.state.x, mapper.state.y) == (2, 15)
    go(target, mapper, (9, 1, 2), polls=1, status="S 8:50")
    assert (mapper.state.x, mapper.state.y) == (9, 1)
    assert (9, 0) in mapper.state.exploration


def test_a_step_through_a_closed_edge_from_the_held_square_stays_held(
        tmp_path, monkeypatch):
    raw = bytearray(synthetic_map(2).to_bytes())
    raw[BARRIERS + 0 * GRID + 9] &= ~(0x03 << (2 * SOUTH))
    sewers = Geo(bytes(raw))
    assert not sewers.is_passable(9, 0, SOUTH)
    target, mapper = sewers_edge_move(tmp_path, monkeypatch, sewers)
    go(target, mapper, (9, 1, 2), polls=2, status="S 8:50")
    assert (mapper.state.x, mapper.state.y) == (2, 15)
    assert (9, 0) not in mapper.state.exploration


def test_a_move_two_squares_from_the_held_square_stays_held(tmp_path, monkeypatch):
    target, mapper = sewers_edge_move(tmp_path, monkeypatch)
    go(target, mapper, (9, 2, 2), polls=2, status="S 8:50")
    assert (mapper.state.x, mapper.state.y) == (2, 15)
    assert (9, 0) not in mapper.state.exploration


def test_a_step_straight_after_the_jump_is_held(tmp_path, monkeypatch):
    target, mapper, sewers = arrive_in_the_sewers((2, 15), tmp_path, monkeypatch)
    go(target, mapper, (2, 15, 2), polls=2, status="S 8:50")
    go(target, mapper, (9, 0, 2), polls=1, status="S 8:50")
    go(target, mapper, (9, 1, 2), polls=1, status="S 8:50")
    assert (mapper.state.x, mapper.state.y) == (2, 15)
    assert (9, 0) not in mapper.state.exploration


def test_a_load_that_steps_before_its_block_changes_explores_nothing_old(
        tmp_path, monkeypatch):
    target, mapper, sewers = arrive_in_the_sewers((2, 15), tmp_path, monkeypatch)
    go(target, mapper, (2, 15, 2), polls=2, status="S 8:50")
    go(target, mapper, (9, 0, 2), polls=1, status="S 8:50")
    go(target, mapper, (9, 1, 2), polls=1, status="S 8:50")
    assert (9, 0) not in mapper.state.exploration
    assert (9, 1) not in mapper.state.exploration
    go(target, mapper, (9, 1, 2), synthetic_map(1), polls=2, status="S 8:50")
    assert mapper.state.area == "GEO01"
    assert (9, 0) not in mapper.state.exploration


def test_a_held_status_jump_is_not_explored_by_a_memory_step(tmp_path, monkeypatch):
    target, mapper, sewers = arrive_in_the_sewers((2, 15), tmp_path, monkeypatch)
    go(target, mapper, (2, 15, 2), polls=2, status="S 8:50")
    go(target, mapper, (9, 0, 2), polls=1, status="S 8:50 9,0")
    go(target, mapper, (9, 1, 2), polls=3, status="S 8:50")
    assert (9, 0) not in mapper.state.exploration


def test_a_load_whose_block_goes_unknown_during_the_hold_explores_nothing(
        tmp_path, monkeypatch):
    target, mapper, sewers = arrive_in_the_sewers((2, 15), tmp_path, monkeypatch)
    go(target, mapper, (2, 15, 2), polls=2, status="S 8:50")
    go(target, mapper, (9, 0, 2), polls=1, status="S 8:50")
    target.memory[RESIDENT_GEO] = bytes(GEO_SIZE)
    go(target, mapper, (9, 0, 2), polls=1, status="S 8:50")
    target.memory[RESIDENT_GEO] = sewers.to_bytes()
    go(target, mapper, (9, 1, 2), polls=3, status="S 8:50")
    assert (mapper.state.x, mapper.state.y) == (2, 15)
    assert (9, 0) not in mapper.state.exploration


def test_the_block_is_read_on_every_poll_only_while_a_jump_is_held(
        tmp_path, monkeypatch):
    target, mapper = sewers_edge_move(tmp_path, monkeypatch)
    reads = []
    verdict = mapper.resident.verdict
    mapper.resident.verdict = lambda maps: reads.append(1) or verdict(maps)
    go(target, mapper, (9, 0, 2), polls=3, status="S 8:50")
    assert len(reads) == 3
    go(target, mapper, (9, 1, 2), polls=1, status="S 8:50")
    reads.clear()
    first = mapper._ticks + 1
    go(target, mapper, (9, 2, 2), polls=3, status="S 8:50")
    periodic = [t for t in range(first, first + 3) if t % mapper.RESIDENT_EVERY == 0]
    assert len(reads) == len(periodic)


def test_the_marker_follows_the_walk_after_a_blank_block_blip(tmp_path, monkeypatch):
    target, mapper, sewers = arrive_in_the_sewers((2, 15), tmp_path, monkeypatch)
    go(target, mapper, (2, 15, 2), polls=2, status="S 8:50")
    go(target, mapper, (9, 0, 2), polls=1, status="S 8:50")
    target.memory[RESIDENT_GEO] = bytes(GEO_SIZE)
    go(target, mapper, (9, 0, 2), polls=1, status="S 8:50")
    target.memory[RESIDENT_GEO] = sewers.to_bytes()
    for y in (1, 2, 3, 4):
        go(target, mapper, (9, y, 2), polls=3, status="S 8:50")
    assert (mapper.state.x, mapper.state.y) == (9, 4)
    assert (9, 3) in mapper.state.exploration
