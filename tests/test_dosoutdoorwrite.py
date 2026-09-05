from __future__ import annotations

"""Writing a C64 party that is standing on the travel grid into a DOS save.

`#190 (A C64 party standing on the travel grid cannot be written into a DOS
save)`.  The converter used to refuse an outdoor party outright, and before
that it wrote one standing on **the template's** square in the template's
area, which is the failure `.claude/rules/conversions.md` exists to prevent:
the file loads, the party is somewhere it has never been, and nothing about
the run says so.

What is different outdoors, and what each test here holds:

* `$49C5` is 0 rather than the area id -- the overland names no `GEO` -- and
  it is *not* the C64's own `$49C5`, which out there holds the `SQRDATA`
  number;
* the square is the travel pair at `$49C3`/`$49C4`, window-local, while
  12801/12802 keep the stale indoor square the party left the grid on;
* the wallset triple is the overland's own `(0, $FFFF, $FFFF)`, which is
  **not** what the C64 cache reads out there (`$FF` in all three slots);
* byte 12803, the facing, is the one field this conversion cannot carry: the
  C64 keeps its travel heading at `$033D`, outside the `$4900`-`$64FF` a save
  is an image of.

**Nothing here is committed game data.**  The party is the repository's own
`party6_savedgame0.bin` fixture -- the player's save, on the allowlist -- with
three bytes changed to put it on the travel grid, and the `ECL<n>.DAX` the
conversion stages is *generated* by `_dax_with`, since what the write path
needs from it is a block of the right id and not the game's own text.

The run that proves the file loads is not here and cannot be:
`tools/dosnewsave.py --c64 work/p190/C64OUT1.D64`, whose party stands on
window 26 and walks.
"""

import pathlib
import struct

import pytest

from goldbox import areas, dos
from goldbox import dos_savegame as sg
from goldbox.savegame import SaveGame0

#: Window 26, the middle wilderness window, and a square inside it.  The
#: numbers are `work/p190/C64OUT1.D64`'s, which the game itself walked the
#: party to and saved.
WINDOW = 26
TRAVEL_X, TRAVEL_Y = 7, 27


def _dax_with(block_id: int, body: bytes) -> bytes:
    """A `.DAX` container holding one block, in the format the reader wants.

    Generated rather than copied: `goldbox.dos._area_script` reads a block of
    a given id out of `ECL<n>.DAX` and stages it, and every test here is
    about *where the party ends up*, not about what the game's script says.
    Run-length coded the way `dax_unpack` decodes -- a lead byte under 128
    copies the next `n + 1` bytes -- in literal runs of at most 128.
    """
    packed = bytearray()
    for at in range(0, len(body), 128):
        run = body[at:at + 128]
        packed += bytes([len(run) - 1]) + run
    index = struct.pack("<BIHH", block_id, 0, len(body), len(packed))
    return struct.pack("<H", len(index)) + index + bytes(packed)


@pytest.fixture
def game_dir(tmp_path) -> pathlib.Path:
    """A game directory holding an `ECL<n>.DAX` for every area used here."""
    here = tmp_path / "game"
    here.mkdir()
    for area in (25, 26, 27, 20):
        where = areas.area(area)
        body = b"\x88\x13" + bytes(range(256)) * 4
        (here / f"ECL{where.disk}.DAX").write_bytes(_dax_with(area, body))
    return here


def _fixture_save0() -> bytearray:
    """The six-character fixture party's `SAVEDGAME0`, as a payload."""
    here = pathlib.Path(__file__).resolve().parent / "fixtures"
    return bytearray(SaveGame0.from_prg(
        (here / "party6_savedgame0.bin").read_bytes()).to_bytes())


def _c64_on_the_travel_grid(x: int = TRAVEL_X, y: int = TRAVEL_Y,
                            facing: int = 3) -> bytes:
    """The fixture party, standing on window 26 the way the C64 keeps it.

    Built rather than committed, and built to the outdoor form the C64
    engine's own save holds -- measured on `work/p190/C64OUT1.D64`, which the
    game wrote after walking there:

    * `$49F2` is the window id and `$49E6` is 0;
    * `$49C5` holds the `SQRDATA` number, not the area id;
    * `$49C3`/`$49C4` are the live travel square;
    * `$49C0`-`$49C2` are the frozen square the party left the grid on, kept
      here at the fixture's own Slums values so a test can tell the two pairs
      apart;
    * the loaded-files cache reads `$FF` in the three `WALLSET` slots,
      because the travel grid loads none.
    """
    save0 = _c64_on_the_travel_grid_raw(x, y, facing)
    return bytes(save0)


def _c64_on_the_travel_grid_raw(x: int, y: int, facing: int) -> bytearray:
    save0 = _fixture_save0()
    save0[dos.CURRENT_SCRIPT - dos.SAVE0_BASE] = WINDOW
    save0[dos.CURRENT_GEO - dos.SAVE0_BASE] = \
        int(areas.area(WINDOW).sqrdata[len("SQRDATA"):], 16)
    save0[dos.INDOORS - dos.SAVE0_BASE] = 0
    save0[sg.TRAVEL_X - dos.SAVE0_BASE] = x
    save0[sg.TRAVEL_Y - dos.SAVE0_BASE] = y
    save0[dos.PARTY_X - dos.SAVE0_BASE] = 15      # the pier, frozen
    save0[dos.PARTY_Y - dos.SAVE0_BASE] = 4
    save0[dos.PARTY_FACING - dos.SAVE0_BASE] = facing
    at = dos.FILE_CACHE[0] - dos.SAVE0_BASE + dos.CACHE_WALLSET
    save0[at:at + dos.CACHE_WALLSET_PIECES] = \
        bytes([dos.FILE_CACHE_EMPTY]) * dos.CACHE_WALLSET_PIECES
    return save0


def _c64_in_the_slums() -> bytes:
    """The same fixture party indoors, as the control."""
    save0 = _fixture_save0()
    save0[dos.CURRENT_SCRIPT - dos.SAVE0_BASE] = 20
    save0[dos.CURRENT_GEO - dos.SAVE0_BASE] = 20
    save0[dos.INDOORS - dos.SAVE0_BASE] = 1
    at = dos.FILE_CACHE[0] - dos.SAVE0_BASE + dos.CACHE_WALLSET
    save0[at:at + dos.CACHE_WALLSET_PIECES] = bytes((2, 4, 1))
    return bytes(save0)


def _write(save0: bytes, tmp_path, game_dir) -> tuple[bytes, "dos.SaveReport"]:
    report = dos.new_dos_save(save0, None, tmp_path / "out", "A", game_dir)
    return (tmp_path / "out" / "SAVGAMA.DAT").read_bytes(), report


# --- the refusal that went ---------------------------------------------------

def test_the_travel_grid_is_no_longer_a_refusal():
    """It was refused because no outdoor DOS retarget had been driven; one
    has been now, so the reason is gone.  The other two refusals stay."""
    for window in (25, 26, 27):
        assert dos.retarget_reason(window) is None, window
    assert "not supported" in dos.retarget_reason(3)      # dynamic_geo
    assert "not supported" in dos.retarget_reason(8)      # loads no map
    assert "not an area" in dos.retarget_reason(31)


def test_a_retarget_onto_a_travel_window_names_no_geo():
    """`$49C5` is the one of the nine retarget writes that changes outdoors.

    Everything else is an area like any other: the DAX number in byte 0 and
    `$5012`, the id in `$49F2`, and the block in the script buffer.
    """
    script = b"\x88\x13" + bytes(64)
    indoor = bytearray(sg.SAVGAM_SIZE)
    sg.retarget(indoor, area=20, dax=2, wallset=(2, 4, 1), script=script)
    assert sg.word(indoor, sg.AREA) == 20

    outdoor = bytearray(sg.SAVGAM_SIZE)
    sg.put_word(outdoor, sg.INDOORS, 1)
    sg.retarget(outdoor, area=WINDOW, dax=7, wallset=sg.OUTDOOR_WALLSET,
                script=script, outdoors=True)
    assert sg.word(outdoor, sg.AREA) == 0
    assert sg.word(outdoor, sg.SCRIPT) == WINDOW
    assert sg.word(outdoor, sg.DISK) == 7 == outdoor[0]
    # `$49E6` is the conversion's write, not the retarget's: a move between
    # two areas of the same world must not change which world it is.
    assert sg.word(outdoor, sg.INDOORS) == 1


# --- the whole save ----------------------------------------------------------

def test_a_party_on_the_travel_grid_is_written_where_it_stands(tmp_path,
                                                               game_dir):
    """The place, field by field, against what an engine-written outdoor save
    holds -- `work/p50-outdoor/SAVGAMC.DAT` and `work/p59-wallset/keep`."""
    savgam, _ = _write(_c64_on_the_travel_grid(), tmp_path, game_dir)
    assert sg.outdoors(savgam)
    assert sg.travel_square(savgam) == (TRAVEL_X, TRAVEL_Y)
    assert sg.current_area(savgam) == WINDOW
    assert sg.word(savgam, sg.AREA) == 0
    assert sg.word(savgam, sg.SCRIPT) == WINDOW
    assert sg.dax_number(savgam) == 7 == sg.word(savgam, sg.DISK)
    # 12801/12802 are the frozen indoor square, not the travel one: reading
    # the travel square off `position()` is exactly the mistake #189 found in
    # the emulator driver, and a writer can make it too.
    assert sg.position(savgam)[:2] == (15, 4)
    assert savgam[sg.VIEW_MODE_BYTE] == sg.VIEW_MODE_OUTDOORS
    assert savgam[sg.SCRATCH_BYTE] == sg.SCRATCH_OUTDOORS
    assert savgam[sg.TAIL_CONSTANT_BYTE] == sg.TAIL_CONSTANT


@pytest.mark.parametrize("window, dax", [(25, 6), (26, 7), (27, 8)])
def test_each_of_the_three_windows_carries_its_own_container(window, dax,
                                                             tmp_path,
                                                             game_dir):
    """Only window 26 has ever been driven, and the other two are the same
    write with a different container number -- `ECL6.DAX` block 25 and
    `ECL8.DAX` block 27 both exist in the player's archive, checked with
    `dax_block`.  A conversion that named the wrong one would stage a
    stranger's script, which is what kills the load in `Load3DMap` (#60)."""
    save0 = bytearray(_c64_on_the_travel_grid())
    save0[dos.CURRENT_SCRIPT - dos.SAVE0_BASE] = window
    savgam, _ = _write(bytes(save0), tmp_path, game_dir)
    assert sg.dax_number(savgam) == dax == sg.word(savgam, sg.DISK)
    assert sg.current_area(savgam) == window
    assert sg.word(savgam, sg.AREA) == 0
    assert sg.travel_square(savgam) == (TRAVEL_X, TRAVEL_Y)


def test_the_outdoor_wallset_is_the_engines_own_not_the_c64s_empty_cache(
        tmp_path, game_dir):
    """Outdoors the C64 loads no `WALLSET` and its cache slots 15-17 read
    `$FF`, which `c64_wall_triple` turns into three empty words -- where
    every engine-written outdoor save holds `(0, $FFFF, $FFFF)`.  Six
    specimens hold it, one of them seeded with Sokol Keep's `(1, 5, 9)` and
    resaved by the engine three times."""
    save0 = _c64_on_the_travel_grid()
    assert dos.c64_wall_triple(save0) == (sg.EMPTY, sg.EMPTY, sg.EMPTY)
    savgam, _ = _write(save0, tmp_path, game_dir)
    assert sg.wall_triple(savgam) == sg.OUTDOOR_WALLSET == (0, sg.EMPTY,
                                                            sg.EMPTY)
    assert [sg.word(savgam, sg.WALLMAP + i) for i in range(3)] == \
        [1, sg.EMPTY, sg.EMPTY]


def test_the_outdoor_facing_is_dropped_rather_than_taken_from_the_stale_byte(
        tmp_path, game_dir):
    """The C64's `$49C2` outdoors is the *dungeon* facing, frozen with the
    square beside it; DOS's 12803 is live out there and prints the facing
    letter.  Copying one into the other would put a direction on the status
    line taken from an unrelated moment, so the field is written north and
    said out loud instead."""
    savgam, report = _write(_c64_on_the_travel_grid(facing=3), tmp_path,
                            game_dir)
    assert savgam[sg.POS_FACING] == 0
    assert any("$033D" in d for d in report.dropped), report.dropped


def test_every_byte_of_an_outdoor_conversion_has_a_source(tmp_path, game_dir):
    """`new_dos_save` refuses a byte it did not write, so reaching the end is
    the assertion -- but say it out loud, because a save built for the travel
    grid is a different set of writes from an indoor one."""
    savgam, report = _write(_c64_on_the_travel_grid(), tmp_path, game_dir)
    assert report.unwritten == []
    assert len(report.sources) == report.total == sg.SAVGAM_SIZE == len(savgam)
    assert any("travel grid at (7,27)" in c for c in report.converted), \
        report.converted


def test_an_indoor_party_is_still_written_the_indoor_way(tmp_path, game_dir):
    """The control.  The outdoor branch is a branch, and a branch that
    changed the other side of itself would pass every test above."""
    savgam, _ = _write(_c64_in_the_slums(), tmp_path, game_dir)
    assert not sg.outdoors(savgam)
    assert sg.word(savgam, sg.AREA) == 20 == sg.word(savgam, sg.SCRIPT)
    assert sg.wall_triple(savgam) == (2, 4, 1)
    assert sg.position(savgam)[:2] == (
        _c64_in_the_slums()[dos.PARTY_X - dos.SAVE0_BASE],
        _c64_in_the_slums()[dos.PARTY_Y - dos.SAVE0_BASE])
    assert savgam[sg.VIEW_MODE_BYTE] == sg.VIEW_MODE_INDOORS
