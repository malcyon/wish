"""The pure parts of `tools/amiga/fsuaepor.py`, and what its recorded run shows.

The name-field and capture helpers need nothing. The last three tests read the
`por-amiga-ff-names` specimen -- the party panel and character sheet Amiga
Pool of Radiance drew in FS-UAE -- and skip when the specimen tree does not
have it, which is what CI does.
"""

from __future__ import annotations

import pytest

from goldbox import amiga_savegame
from goldbox.amiga_adf import AmigaDisk
from tools.amiga import amiganamespaces, fsuaepor


def test_parse_name_reads_python_escapes_as_single_bytes():
    assert fsuaepor.parse_name(r"MARY\xffSUE") == b"MARY\xffSUE"
    assert fsuaepor.parse_name("A  B") == b"A  B"


def test_set_name_changes_the_name_field_and_nothing_else():
    record = bytes(range(256)) + bytes(32)
    after = fsuaepor.set_name(record, b"J. R")
    assert after[:16] == b"J. R" + bytes(12)
    assert after[16:] == record[16:]
    assert len(after) == len(record)


def test_set_name_refuses_a_name_with_no_room_for_its_nul():
    with pytest.raises(ValueError):
        fsuaepor.set_name(bytes(288), b"ABCDEFGHIJKLMNOP")


def test_name_of_stops_at_the_first_nul_and_keeps_the_residue():
    field = b"MARYSUEFOX\x00x\x00\x00\x00\x00"
    name, whole = fsuaepor.name_of(field + bytes(272))
    assert name == b"MARYSUEFOX"
    assert whole == field


def test_drop_slot_removes_the_files_and_the_letter():
    disk = AmigaDisk.blank("poolgame")
    disk.make_dir("save")
    for name in ("CHRDATD1.sav", "CHRDATD1.itm", "savgamD.dat",
                 "CHRDATE1.sav", "savgamE.dat"):
        disk.write_file(f"save/{name}", b"x")
    disk.write_file("save/save", amiga_savegame.slot_list_bytes("DE"))
    gone = fsuaepor.drop_slot(disk, "D")
    assert gone == ["CHRDATD1.itm", "CHRDATD1.sav", "savgamD.dat"]
    assert amiga_savegame.read_slot_list(disk) == ["E"]
    assert disk.read_file("save/CHRDATE1.sav") == b"x"


class _Picture:
    """A grab with ink at the given columns on every row."""

    def __init__(self, inked: set[int]):
        self.inked = inked

    def getpixel(self, at):
        return (255, 255, 255) if at[0] in self.inked else (0, 0, 0)


def test_glyph_runs_and_blank_cells_on_a_drawn_row():
    # Two 10-pixel glyphs with a 2-pixel gap, then one blank 12-pixel cell.
    inked = set(range(0, 10)) | set(range(12, 22)) | set(range(36, 46))
    runs = fsuaepor.glyph_runs(_Picture(inked), (0, 4), (0, 60),
                               fsuaepor.white_ink)
    assert runs == [(0, 10), (12, 22), (36, 46)]
    assert fsuaepor.blank_cells(runs, 12) == [0, 1]


def _capture(name: str):
    image = pytest.importorskip("PIL.Image")
    where = amiganamespaces.specimen(amiganamespaces.WATCHED_SPECIMEN)
    if where is None:
        pytest.skip(f"No {amiganamespaces.WATCHED_SPECIMEN} in the specimen "
                    f"tree here.")
    return image.open(where / name).convert("RGB")


def _panel(picture):
    """The three rows as runs: the selected row is white, the rest green."""
    return ([fsuaepor.glyph_runs(picture, fsuaepor.PANEL_ROWS[0],
                                 fsuaepor.PANEL_COLUMNS, fsuaepor.white_ink)]
            + [fsuaepor.glyph_runs(picture, rows, fsuaepor.PANEL_COLUMNS,
                                   fsuaepor.green_ink)
               for rows in fsuaepor.PANEL_ROWS[1:]])


def _pitch(runs_of_a_space_space_b) -> float:
    """One character cell, from `A  B`: B starts three cells after A."""
    first, last = runs_of_a_space_space_b[0], runs_of_a_space_space_b[-1]
    return (last[0] - first[0]) / 3


def test_the_panel_draws_ff_as_one_blank_cell_like_a_space():
    """Slot C loaded, before any save: `MARY<FF>SUE`, `A  B`, `J. R`.

    The gap in `MARY SUE` is one cell and the gap in `A  B` two, so `$FF` is
    drawn exactly as a space is, and nothing is drawn in its place.
    """
    mary, a_b, j_r = _panel(_capture("boot1-loaded-c-panel.png"))
    pitch = _pitch(a_b)
    assert fsuaepor.blank_cells(mary, pitch) == [1]
    assert fsuaepor.blank_cells(a_b, pitch) == [2]
    assert fsuaepor.blank_cells(j_r, pitch) == [0, 1]


@pytest.mark.parametrize("name", ["boot1-after-g-h-panel.png",
                                  "boot2-loaded-h-panel.png"])
def test_after_two_saves_ff_is_still_drawn_and_the_spaces_are_gone(name):
    """After G and H in one boot, and again after a cold boot loaded H."""
    pitch = _pitch(_panel(_capture("boot1-loaded-c-panel.png"))[1])
    mary, a_b, j_r = _panel(_capture(name))
    assert fsuaepor.blank_cells(mary, pitch) == [1]
    assert len(a_b) == 1 and len(j_r) == 1


@pytest.mark.parametrize("name", ["boot1-sheet-c1.png", "boot2-sheet-h1.png"])
def test_the_sheet_draws_ff_as_a_blank_cell(name):
    pitch = _pitch(_panel(_capture("boot1-loaded-c-panel.png"))[1])
    runs = fsuaepor.glyph_runs(_capture(name), fsuaepor.SHEET_NAME_ROWS,
                               fsuaepor.SHEET_NAME_COLUMNS, fsuaepor.green_ink)
    assert fsuaepor.blank_cells(runs, pitch).count(1) == 1
    assert sum(fsuaepor.blank_cells(runs, pitch)) == 1
