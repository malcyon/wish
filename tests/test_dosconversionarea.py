"""A conversion writes the area the C64 party is standing in, including the
areas whose script loads no map of its own.

`#276 (Converting a save out to DOS writes the area id into the resident-map
word)`.  The word at `$49C5` is the resident `GEO` and the word at `$49F2` is
the area, and they part company in six of Pool of Radiance's areas -- the
training hall among them, where an engine-written save holds `$49C5` = 0 with
`$49F2` = 11.  `savgam_writes` reads both out of the C64 save now; what these
tests hold is that the **refusal** in front of it lets the save through.

`dos.retarget_reason` and `dos.conversion_reason` answer two different
questions and this file pins the difference: a retarget names an area the
party has never been in, so `goldbox/areas.py` is its only source for the map;
a conversion reads the map out of the save it is converting.

Measured in the running game on 2026-09-05: `work/issue276/probe-geo00` loads
and draws the hall, and the same save with `$49C5` poked to 11 -- the value
this code used to write -- exits to DOS with `Unable to load geo in
Load3DMap.`
"""

from __future__ import annotations

import functools
import pathlib

import pytest

from goldbox import dos
from goldbox import dos_savegame as sg
from goldbox.savegame import SaveGame0

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

#: Pool of Radiance's training hall: its script issues no `LOADFILES`, so it
#: runs on whatever `GEO` the area before it left resident.  `goldbox/areas.py`
#: has no `geos` row for it and cannot have one.
TRAINING_HALL = 11

#: The `GEO` an engine-written training-hall save holds -- New Phlan's map,
#: which the school stands in.  `WISH-SPEC-por-c64-hall-resave` reads 0 here
#: with 11 at `$49F2`, and so does DOS Pool of Radiance's own resave of the
#: converted file.
HALL_GEO = 0


@functools.lru_cache(maxsize=1)
def _save_dir():
    """A played DOS Pool of Radiance save directory, or None.

    The same rule `tests/test_dossave.py` uses -- recognised by a
    `SAVGAM?.DAT` beside 285-byte `CHRDAT*.SAV` files rather than by its path,
    because Steam redirects the save directory out of the game folder.
    Repeated here rather than imported: a test module's private helpers are
    not another agent's to depend on.
    """
    from tools import gamedisks
    for root in gamedisks.candidates("dos-archives"):
        try:
            if not root.is_dir():
                continue
            for path in root.rglob("SAVGAM[ABJ].DAT"):
                records = [p for p in path.parent.glob("CHRDAT*.SAV")
                           if p.stat().st_size == 285]
                if records:
                    return path.parent
        except OSError:
            continue
    return None


needs_dos_game = pytest.mark.skipif(
    _save_dir() is None,
    reason="needs the DOS game's own ECL3.DAX; set FR_ARCHIVES")


def _c64_in_the_training_hall() -> bytes:
    """The committed six-character C64 fixture, standing in the hall.

    Built rather than committed, from the same three things the conversion
    reads to decide where the party is: the area at `$49F2`, the resident map
    at `$49C5` and the wallset cache.  The two numbers are the ones
    `WISH-SPEC-por-c64-hall-resave` holds, which is an engine-written save
    made in that room.
    """
    save0 = bytearray(SaveGame0.from_prg(
        (FIXTURES / "party6_savedgame0.bin").read_bytes()).to_bytes())
    save0[dos.CURRENT_SCRIPT - dos.SAVE0_BASE] = TRAINING_HALL
    save0[dos.CURRENT_GEO - dos.SAVE0_BASE] = HALL_GEO
    at = dos.FILE_CACHE[0] - dos.SAVE0_BASE + dos.CACHE_WALLSET
    save0[at:at + dos.CACHE_WALLSET_PIECES] = bytes((1, 5, 9))
    return bytes(save0)


def test_a_conversion_is_not_refused_an_area_whose_script_loads_no_map():
    """The six areas `retarget_reason` refuses are all conversions can write.

    Four of them load no map at all (8, 11, 19, 30) and two pick theirs at run
    time (3, 5).  Every one of those is a statement about the *area table*,
    and a conversion does not read the area table for the map -- it reads the
    save.
    """
    for area in (3, 5, 8, TRAINING_HALL, 19, 30):
        assert dos.retarget_reason(area) is not None, area
        assert dos.conversion_reason(area) is None, area


def test_a_conversion_still_refuses_an_area_with_no_row():
    """The one refusal the save cannot answer: there is no `ECL<n>.DAX` to
    lift a script out of and no disk number to write."""
    assert "not an area" in dos.conversion_reason(31)
    assert dos.conversion_reason(0) is None


def test_the_retarget_rule_is_unchanged():
    """A retarget names an area the party has never been in, so the area table
    really is the only source there is and its six refusals stand."""
    assert dos.UNSUPPORTED_LOCATION in dos.retarget_reason(TRAINING_HALL)
    assert dos.UNSUPPORTED_LOCATION in dos.retarget_reason(3)
    assert dos.retarget_reason(20) is None


@needs_dos_game
def test_a_party_in_the_training_hall_converts_and_keeps_its_own_map(tmp_path):
    """The whole of `#276` in one call: the save that used to be refused.

    `$49C5` comes out 0 and `$49F2` comes out 11, which is what an
    engine-written hall save holds and what DOS Pool of Radiance's own resave
    of this converted file holds.  Writing 11 into both -- what this code did
    before the fix -- names `GEO0B`, and the game exits to DOS.
    """
    save0 = _c64_in_the_training_hall()
    dos.write_dos_save(save0, None, None, tmp_path, "A",
                       game=_save_dir().parent)
    savgam = (tmp_path / "SAVGAMA.DAT").read_bytes()
    assert sg.geo_block(savgam) == HALL_GEO
    assert sg.word(savgam, sg.SCRIPT) == TRAINING_HALL
    # Area 11 is on disk 3, and the geo load reads the word rather than the
    # header byte (#59), so both have to say so.
    assert sg.dax_number(savgam) == 3 == sg.word(savgam, sg.DISK)
