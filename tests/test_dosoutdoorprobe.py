"""The seed and the route `tools/dosoutdoorprobe.py` plants before DOSBox runs.

The tool's *output* is a specimen the DOS engine wrote and cannot be tested
here -- it takes DOSBox, a private X display and about four minutes a boot.
What can be tested is everything that decides whether the run will mean
anything: the route the party walks, and the seed it walks from.

**The seed's whole point is the wallset triple it does not touch.**
`tools/dosoutdoor.py` writes `(0, $FFFF, $FFFF)` over whatever the source
carried, which is right for making a specimen and useless for measuring one:
`#59 (Map the DOS saved game, not just the character record)` left the
outdoor triple UNKNOWN for a month because every overland save had departed
from the one indoor save that holds those same three words, so live could
never be told from stale. `seed(..., wallset=None)` keeps the source's, and
that is what separated them -- a seed carrying Sokol Keep's `(1, 5, 9)` came
back `(0, $FFFF, $FFFF)` from three engine resaves.

The saves are Donald's, not the repository's, so the seed tests skip without
them -- the same gate `tests/test_dosoutdoor.py` uses. `parse_route` needs no
save and no emulator at all.
"""
from __future__ import annotations

import pathlib
import sys

import pytest
from test_dossave import _save_dir, needs_dos_saves

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos_savegame as sg  # noqa: E402
from tools import dosoutdoorprobe as probe  # noqa: E402

#: A script of the right shape and none of the game's bytes: `retarget` copies
#: it into the ECL buffer from byte 2 on, so what matters is the header and
#: the length rather than what it says.
FAKE_SCRIPT = b"\x00\x02" + bytes(range(256)) * 4

#: A triple no area holds, so a test that finds it in the seed knows the
#: parameter was honoured rather than a real value coinciding.
ODD_WALLSET = (11, 12, 13)


# -- parse_route: no save, no emulator -----------------------------------

def test_a_route_is_moves_and_saves():
    assert probe.parse_route("U,SC,R,SD") == ["U", "SC", "R", "SD"]


def test_a_route_is_read_case_insensitively_and_ignores_spaces():
    assert probe.parse_route(" u , sc ,, R ") == ["U", "SC", "R"]


@pytest.mark.parametrize("bad", ["X", "N,SC", "U,S", "U,S1", "up", ""])
def test_a_step_that_is_neither_a_move_nor_a_save_is_refused(bad):
    """A typo would walk a route that is not the one anybody asked for.

    `""` is in the list because an empty route step comes from a stray comma
    and `"U,S"` because a bare `S` names no slot.
    """
    if bad == "":
        assert probe.parse_route("") == []      # nothing asked, nothing done
        return
    with pytest.raises(ValueError):
        probe.parse_route(bad)


def test_the_same_slot_letter_twice_is_refused():
    """The second save overwrites the first waypoint's specimen in place.

    The game writes `SAVGAM<slot>.DAT`, so a route saving to C twice reports
    two waypoints while keeping the evidence for one -- and keeping every
    waypoint's own file is the only reason this tool exists rather than
    `tools/dosoutdoor.py`.
    """
    with pytest.raises(ValueError, match="twice"):
        probe.parse_route("U,SC,R,SC")


def test_the_duplicate_check_is_on_the_slot_and_not_the_move():
    """Walking north four times is ordinary; saving to C twice is not."""
    assert probe.parse_route("U,U,U,U,SC") == ["U", "U", "U", "U", "SC"]


def test_every_move_letter_maps_to_an_arrow_key():
    """Outdoors the arrows move the party rather than turning it, so a
    route needs no turn-then-step pair and all four directions are moves."""
    assert set(probe.MOVES) == {"U", "D", "L", "R"}
    assert sorted(probe.MOVES.values()) == ["Down", "Left", "Right", "Up"]


# -- the seed ------------------------------------------------------------

def _indoor_savgam(slot: str = "A") -> bytes:
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    path = where / f"SAVGAM{slot}.DAT"
    if not path.exists():
        pytest.skip(f"no SAVGAM{slot}.DAT here")
    save = path.read_bytes()
    if sg.outdoors(save):
        pytest.skip(f"SAVGAM{slot}.DAT is already outdoors")
    return save


def _indoor_with_a_wallset() -> bytes:
    """A source whose triple is *not* the one the outdoor default writes.

    Without that the keep test is vacuous -- it would pass on a save that
    already held `(0, $FFFF, $FFFF)` whether or not the code kept anything.
    Slot B stands in Sokol Keep and holds `(1, 5, 9)`.
    """
    from tools import dosoutdoor
    for slot in "BJA":
        where = _save_dir()
        if where is None or not (where / f"SAVGAM{slot}.DAT").exists():
            continue
        save = (where / f"SAVGAM{slot}.DAT").read_bytes()
        if not sg.outdoors(save) and \
                sg.wall_triple(save) != dosoutdoor.OUTDOOR_WALLSET:
            return save
    pytest.skip("no indoor save here carries a distinctive wallset triple")


@needs_dos_saves
def test_the_seed_keeps_the_sources_wallset_when_asked_to():
    """The one thing this seed does that `tools/dosoutdoor.py`'s does not.

    A seed that overwrites the field can never say whether the field
    mattered, and that is exactly how the outdoor triple stayed UNKNOWN.
    """
    save = _indoor_with_a_wallset()
    planted = probe.seed(save, area=26, x=7, y=29, script=FAKE_SCRIPT,
                         wallset=None)
    assert sg.wall_triple(planted) == sg.wall_triple(save)


@needs_dos_saves
def test_the_seed_writes_the_wallset_it_is_given():
    """And the parameter is honoured rather than ignored either way."""
    planted = probe.seed(_indoor_savgam(), area=26, x=7, y=29,
                         script=FAKE_SCRIPT, wallset=ODD_WALLSET)
    assert sg.wall_triple(planted) == ODD_WALLSET


@needs_dos_saves
@pytest.mark.parametrize("area,disk", [(25, 6), (26, 7), (27, 8)])
def test_the_seed_says_outdoors_in_all_four_places(area, disk):
    """The four fields that separate an overland save from an indoor one.

    `$49E6` is what boots travel mode, `$49F2` alone carries the area id out
    there, `$49C5` is 0 because the overland names no `GEO`, and the square
    lives at `$49C3`/`$49C4` rather than at 12801/12802.
    """
    planted = probe.seed(_indoor_savgam(), area=area, x=7, y=29,
                         script=FAKE_SCRIPT, wallset=None)
    assert sg.outdoors(planted)                     # $49E6 = 0
    assert sg.word(planted, sg.SCRIPT) == area      # $49F2
    assert sg.word(planted, sg.AREA) == 0           # $49C5
    assert sg.travel_square(planted) == (7, 29)
    assert planted[0] == disk and sg.word(planted, sg.DISK) == disk


@needs_dos_saves
def test_the_seed_leaves_the_dungeon_square_where_the_engine_left_it():
    """12801/12802 go stale outdoors and the engine maintains them itself.

    Measured 10 of 10 on the overland specimens: each freezes at its own
    lineage's last indoor square. Writing the travel square over them would
    invent a value for a field the game does not keep out there.
    """
    save = _indoor_savgam()
    planted = probe.seed(save, area=26, x=7, y=29, script=FAKE_SCRIPT,
                         wallset=None)
    assert sg.position(planted) == sg.position(save)


@needs_dos_saves
@pytest.mark.parametrize("area", [0, 20, 21, 99])
def test_an_area_that_is_not_a_travel_window_is_refused(area):
    """A probe is only ever wanted for the overland, and 99 is no area."""
    with pytest.raises(ValueError):
        probe.seed(_indoor_savgam(), area=area, x=7, y=29,
                   script=FAKE_SCRIPT, wallset=None)


# -- what the report records ---------------------------------------------

@needs_dos_saves
def test_the_report_carries_the_words_the_probe_exists_to_compare():
    """A run that did not record `$4AFA` or `$507A` answered nothing."""
    got = probe.fields(probe.seed(_indoor_savgam(), area=26, x=7, y=29,
                                  script=FAKE_SCRIPT, wallset=ODD_WALLSET))
    assert got["wallset"] == list(ODD_WALLSET)     # the live/stale question
    assert got["wallmap"] == [1, 2, 3]             # moves with the triple
    assert got["travel"] == [7, 29]
    assert got["outdoors"] is True
    # `$4AFA`-`$4AFC` is the `wallset` key above rather than a `words` entry.
    for address in ("$507A", "$507B", "$507C", "$49C3", "$49C4", "$49E6"):
        assert address in got["words"], address
