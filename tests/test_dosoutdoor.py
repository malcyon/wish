"""The seed `tools/dosoutdoor.py` plants before the DOS engine resaves it.

The tool's *output* is a specimen the DOS engine wrote and cannot be tested
here -- it takes DOSBox, a private X display and about ninety seconds.  What
can be tested is the half that decides whether the engine will accept it at
all: an indoor saved game moved onto a travel window carries four fields
measured to differ outdoors, and forgetting any one of them is a seed that
loads into the wrong world or does not load.

Those four came from `#59 (Map the DOS saved game, not just the character
record)`, three overland specimens against three indoor ones, and the seed
built from them was loaded in DOSBox on 2026-09-02 for `#50 (Lift the
wilderness refusal from the DOS save converter)`: the game drew the travel
window and the status line read `20,29 N 10:02`, which is window-local (7,29)
plus window 26's offset of 13.

The saves are Donald's, not the repository's, so these skip without them --
the same gate `tests/test_dosconvert.py` uses.
"""
from __future__ import annotations

import pathlib
import sys

import pytest
from test_dossave import _save_dir, needs_dos_saves

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos_savegame as sg  # noqa: E402
from tools import dosoutdoor  # noqa: E402

#: A script of the right shape and none of the game's bytes: `retarget` copies
#: it into the ECL buffer from byte 2 on, so what matters here is the header
#: and the length, not what it says.
FAKE_SCRIPT = b"\x00\x02" + bytes(range(256)) * 4


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


@needs_dos_saves
@pytest.mark.parametrize("area,disk", [(25, 6), (26, 7), (27, 8)])
def test_the_seed_says_outdoors_in_all_four_places(area, disk):
    """The four fields that separate an overland save from an indoor one.

    Drop any and the DOS engine is being asked to load a party into the world
    it is not in: `$49E6` is what boots travel mode, `$49F2` alone carries the
    area id out there, `$49C5` is 0 because the overland names no `GEO`, and
    the square lives at `$49C3`/`$49C4` rather than at 12801/12802.
    """
    planted = dosoutdoor.seed(_indoor_savgam(), area=area, x=7, y=29,
                              script=FAKE_SCRIPT)
    assert sg.outdoors(planted)                     # $49E6 = 0
    assert sg.word(planted, sg.SCRIPT) == area      # $49F2
    assert sg.word(planted, sg.AREA) == 0           # $49C5
    assert sg.travel_square(planted) == (7, 29)
    assert sg.current_area(planted) == area
    assert planted[0] == disk and sg.word(planted, sg.DISK) == disk


@needs_dos_saves
def test_the_seed_leaves_the_dungeon_square_where_the_engine_left_it():
    """12801/12802 go stale outdoors and the engine maintains them itself.

    Writing the travel square over them would be inventing a value for a
    field the game does not keep out there -- the opposite of what the
    specimen is being made to avoid.
    """
    save = _indoor_savgam()
    planted = dosoutdoor.seed(save, area=26, x=7, y=29, script=FAKE_SCRIPT)
    assert sg.position(planted) == sg.position(save)


@needs_dos_saves
def test_the_seed_writes_the_outdoor_tail_state():
    """Bytes 12804 and 12806, measured 14 and 3 in every overland specimen."""
    planted = dosoutdoor.seed(_indoor_savgam(), area=26, x=7, y=29,
                              script=FAKE_SCRIPT)
    assert planted[sg.SCRATCH_BYTE] == sg.SCRATCH_OUTDOORS
    assert planted[sg.VIEW_MODE_BYTE] == sg.VIEW_MODE_OUTDOORS


@needs_dos_saves
def test_the_script_reaches_the_ecl_buffer_from_byte_two():
    """`retarget`'s rule, and the one write that is not a word or a byte."""
    planted = dosoutdoor.seed(_indoor_savgam(), area=26, x=7, y=29,
                              script=FAKE_SCRIPT)
    start = sg.ECL_BUFFER[0]
    body = FAKE_SCRIPT[sg.ECL_HEADER:]
    assert planted[start:start + len(body)] == body


@needs_dos_saves
@pytest.mark.parametrize("area", [0, 20, 21, 99])
def test_an_area_that_is_not_a_travel_window_is_refused(area):
    """A seed is only ever wanted for the overland, and 99 is no area at all.

    Refusing here is what stops the tool quietly making an indoor specimen
    and a reader believing it was made outdoors.
    """
    with pytest.raises(ValueError):
        dosoutdoor.seed(_indoor_savgam(), area=area, x=7, y=29,
                        script=FAKE_SCRIPT)
