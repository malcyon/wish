"""Silver Blades' status line can print a frame of its own, and the marker uses the map's.

In The Ruins the area script keeps a second coordinate pair and a facing turn
at `$4CFD`-`$4CFF`, and the status line prints those instead of the engine's
square and facing (`DUNGEON` `$0A23`, `$09F9`). Arriving from New Verdigris
the line reads `0,15 E` while the party stands at 11,2 facing east on
`GEO20`. Everywhere else, and in every other title, the line still wins.
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


def test_only_silver_blades_has_a_printed_frame_at_4cfd():
    assert c64.machine_for(SSB).printed_frame == PRINTED
    for key, row in c64.MACHINES.items():
        if key != SSB.key:
            assert row.printed_frame is None, key


def test_the_ruins_entrance_reads_the_engine_square():
    """The arrival measured live: line `0,15 E`, engine 11,2 east."""
    target = machine("E 0:17  0,15", (11, 2, 1), (0x00, 0x0F, 0))
    fix = party_fix(target.read, SSB)
    assert (fix.x, fix.y, fix.facing, fix.source) == (11, 2, 1, "memory")


def test_a_turned_frame_reads_the_engine_facing():
    """`$4CFF` = 2 prints east as west; the square is the engine's here."""
    target = machine("W 0:17  3,3", (3, 3, 1), (0xFF, 0, 2))
    fix = party_fix(target.read, SSB)
    assert (fix.x, fix.y, fix.facing, fix.source) == (3, 3, 1, "memory")


def test_the_line_still_wins_where_silver_blades_prints_the_engine_square():
    """`$4CFD` = `$FF`, as in every in-world Silver Blades save we have."""
    target = machine("S 8:37  3,4", (3, 5, 2), (0xFF, 0, 0))
    fix = party_fix(target.read, SSB)
    assert (fix.x, fix.y, fix.facing, fix.source) == (3, 4, 2, "status")


@pytest.mark.parametrize("game", [CURSE, POOL], ids=["curse", "pool"])
def test_other_titles_ignore_the_same_bytes(game):
    """In Curse `$4CFD`-`$4CFF` are unrelated script variables."""
    target = machine("E 0:17  0,15", (11, 2, 1), (0x00, 0x0F, 3))
    fix = party_fix(target.read, game)
    assert (fix.x, fix.y, fix.facing, fix.source) == (0, 15, 1, "status")


def test_the_marker_walks_the_ruins_on_the_engine_square(tmp_path, monkeypatch):
    """Arrival and two steps north, as #37's Amiga run read them: the line
    goes 0,15 / 0,14 / 0,13 and the engine 11,2 / 11,1 / 11,0."""
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
