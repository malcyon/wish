"""Silver Blades' status line can print a frame of its own, and the marker uses the map's.

The game prints `$4CFD`,`$4CFE` in place of the engine's square while `$4CFD`
is below `$80`, and adds `$4CFF` to the printed facing whatever `$4CFD`
holds. The Ruins keep that pair moved and turned against the map, so at the
entrance from New Verdigris the line reads `0,15 E` while the party stands at
11,2 facing east on `GEO20`. Everywhere else, and in every other title, the
line's square still wins.
"""
import pytest
from support.stalestatus import curse_target
from test_stale_status import synthetic_map

from automap import c64
from automap.state import Automapper
from automap.target import party_fix
from goldbox import c64_port

SSB = c64_port.SECRET_OF_THE_SILVER_BLADES
CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS
POOL = c64_port.POOL_OF_RADIANCE
PRINTED = 0x4CFD


def machine(status, triple, frame, geo=None):
    """Row 14 reading *status*, `$C04B` holding *triple*, `$4CFD` holding *frame*."""
    target = curse_target(status, triple, geo)
    target.memory[PRINTED] = bytes(frame)
    return target


def reading(target, game=SSB):
    fix = party_fix(target.read, game)
    return fix.x, fix.y, fix.facing, fix.source


def test_only_silver_blades_has_a_printed_frame_at_4cfd():
    assert c64.machine_for(SSB).printed_frame == PRINTED
    for key, row in c64.MACHINES.items():
        if key != SSB.key:
            assert row.printed_frame is None, key


def test_the_ruins_entrance_reads_the_engine_square():
    target = machine("E 0:17  0,15", (11, 2, 1), (0x00, 0x0F, 0))
    assert reading(target) == (11, 2, 1, "memory")


@pytest.mark.parametrize("frame, expected", [
    ((0x7F, 0, 0), (11, 2, 1, "memory")),   # the last value that prints the pair
    ((0x80, 0, 0), (0, 15, 1, "status")),   # the first that prints the engine's
    ((0xFF, 0, 4), (0, 15, 1, "status")),   # a turn of 4 is no turn, mod 4
], ids=["7F", "80", "FF-turn-4"])
def test_the_frame_boundaries_are_the_games(frame, expected):
    target = machine("E 0:17  0,15", (11, 2, 1), frame)
    assert reading(target) == expected


def test_a_leftover_turn_in_town_turns_the_facing_back_and_keeps_the_line():
    """`$4CFD` = `$FF` with `$4CFF` = 2: the game prints the engine square and
    east as west, so the line's square stands and its facing is turned back."""
    target = machine("W 4:34  15,8", (15, 8, 1), (0xFF, 0x0F, 2))
    assert reading(target) == (15, 8, 1, "status")


def test_the_line_still_wins_where_silver_blades_prints_the_engine_square():
    target = machine("S 8:37  3,4", (3, 5, 2), (0xFF, 0, 0))
    assert reading(target) == (3, 4, 2, "status")


@pytest.mark.parametrize("game", [CURSE, POOL], ids=["curse", "pool"])
def test_other_titles_ignore_the_same_bytes(game):
    """In Curse `$4CFD`-`$4CFF` are unrelated script variables."""
    target = machine("E 0:17  0,15", (11, 2, 1), (0x00, 0x0F, 3))
    assert reading(target, game) == (0, 15, 1, "status")
    assert all(addr != PRINTED for addr, _ in target.reads)


def test_a_printed_pair_outside_the_grid_costs_no_frame_read():
    """Printed 20,15 cannot be the engine's square, so the frame is not read."""
    target = machine("E 0:17  20,15", (11, 2, 1), (0x14, 0x0F, 0))
    assert reading(target) == (11, 2, 1, "memory")
    assert all(addr != PRINTED for addr, _ in target.reads)


def test_a_printed_pair_inside_the_grid_reads_the_frame_once():
    target = machine("E 0:17  0,15", (11, 2, 1), (0x00, 0x0F, 0))
    reading(target)
    assert [r for r in target.reads if r[0] == PRINTED] == [(PRINTED, 3)]


def test_the_marker_walks_the_ruins_on_the_engine_square(tmp_path, monkeypatch):
    """Arrival and two steps north: the line goes 0,15 / 0,14 / 0,13 and the
    engine 11,2 / 11,1 / 11,0."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    ruins = synthetic_map(3)
    target = machine("E 0:17  0,15", (11, 2, 1), (0x00, 0x0F, 0), ruins)
    mapper = Automapper(target, {"GEO20": ruins}, area="GEO20",
                        title=SSB.title)
    seen = []
    for status, triple, printed in [
            ("E 0:17  0,15", (11, 2, 1), (0x00, 0x0F, 0)),
            ("N 0:17  0,15", (11, 2, 0), (0x00, 0x0F, 0)),
            ("N 0:18  0,14", (11, 1, 0), (0x00, 0x0E, 0)),
            ("N 0:19  0,13", (11, 0, 0), (0x00, 0x0D, 0))]:
        target.memory.update(machine(status, triple, printed, ruins).memory)
        mapper.poll()
        state = mapper.state
        seen.append((state.x, state.y, state.facing))
    assert seen == [(11, 2, 1), (11, 2, 0), (11, 1, 0), (11, 0, 0)]
    for square in [(11, 2), (11, 1), (11, 0)]:
        assert square in mapper.state.exploration
    for square in [(0, 15), (0, 14), (0, 13)]:
        assert square not in mapper.state.exploration


def test_the_marker_crosses_between_town_and_ruins_both_ways(tmp_path, monkeypatch):
    """New Verdigris at 15,8 E, into The Ruins at 11,2 with the line still
    on the town's square, a turn there, then west back to 15,8 with the line
    still on the Ruins' pair, and a step on to 14,8."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    town, ruins = synthetic_map(1), synthetic_map(3)
    target = machine("E 4:34  15,8", (15, 8, 1), (0xFF, 0, 0), town)
    mapper = Automapper(target, {"GEO10": town, "GEO20": ruins},
                        area="GEO10", title=SSB.title)
    for _ in range(mapper.RESIDENT_EVERY - 1):
        mapper.poll()
    state = mapper.state
    assert (state.area, state.x, state.y, state.facing, state.source) == (
        "GEO10", 15, 8, 1, "status")

    def go(status, triple, frame, geo, polls=1):
        target.memory.update(machine(status, triple, frame, geo).memory)
        for _ in range(polls):
            mapper.poll()
        s = mapper.state
        return s.area, s.x, s.y, s.facing, s.source

    # Into The Ruins: the script has written its pair, the line is stale.
    assert go("E 4:34  15,8", (11, 2, 1), (0x00, 0x0F, 0), ruins) == (
        "GEO20", 11, 2, 1, "memory")
    assert go("E 4:34  0,15", (11, 2, 1), (0x00, 0x0F, 0), ruins, 2) == (
        "GEO20", 11, 2, 1, "memory")
    # A turn, read twice: a printed (0,15) would be a confirmed jump.
    assert go("N 4:34  0,15", (11, 2, 0), (0x00, 0x0F, 0), ruins, 2) == (
        "GEO20", 11, 2, 0, "memory")
    assert go("W 4:38  0,15", (11, 2, 3), (0x00, 0x0F, 0), ruins, 2) == (
        "GEO20", 11, 2, 3, "memory")
    # Back west into town: `$4CFD` is `$FF` again, the line still reads the
    # Ruins' pair, which the area change blocks until the game redraws it.
    assert go("W 4:38  0,15", (15, 8, 3), (0xFF, 0x0F, 0), town) == (
        "GEO10", 15, 8, 3, "memory")
    assert go("W 4:38  0,15", (15, 8, 3), (0xFF, 0x0F, 0), town, 2) == (
        "GEO10", 15, 8, 3, "memory")
    assert go("W 4:38  15,8", (15, 8, 3), (0xFF, 0x0F, 0), town) == (
        "GEO10", 15, 8, 3, "status")
    assert go("W 4:39  14,8", (14, 8, 3), (0xFF, 0x0F, 0), town) == (
        "GEO10", 14, 8, 3, "status")
    assert (0, 15) not in mapper.state.exploration
