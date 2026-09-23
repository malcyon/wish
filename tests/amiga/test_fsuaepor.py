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


def test_curse_disks_come_out_of_the_registry_in_drive_order():
    try:
        disks = fsuaepor.curse_disks()
    except SystemExit as exc:
        pytest.skip(str(exc))
    assert [AmigaDisk(d).volume_name for d in disks] == ["CurseA", "CurseB"]


def _argv(run, floppy=None, swap=None):
    drives, swaps = fsuaepor.default_images(run, floppy, swap)
    return fsuaepor.fsuae_argv(run, drives, swaps, "720x568",
                               run / "kick.rom"), drives, swaps


def _touch(run, *names):
    for name in names:
        (run / name).write_bytes(b"")


def test_a_pools_of_darkness_run_puts_disk_3_in_df1(tmp_path):
    _touch(tmp_path, "pod1.adf", "pod2.adf", "pod3.adf")
    argv, drives, swaps = _argv(tmp_path)
    assert (drives, swaps) == ([tmp_path / "pod1.adf", tmp_path / "pod3.adf"],
                               [tmp_path / "pod2.adf"])
    assert f"--floppy_drive_0={tmp_path / 'pod1.adf'}" in argv
    assert f"--floppy_drive_1={tmp_path / 'pod3.adf'}" in argv
    assert not any(a.startswith("--floppy_drive_2") for a in argv)


def test_every_image_is_offered_in_the_swap_list(tmp_path):
    _touch(tmp_path, "pod1.adf", "pod2.adf", "pod3.adf")
    argv, _, _ = _argv(tmp_path)
    assert [a for a in argv if a.startswith("--floppy_image_")] == [
        f"--floppy_image_{i}={tmp_path / name}"
        for i, name in enumerate(("pod1.adf", "pod3.adf", "pod2.adf"))]
    por = tmp_path / "por"
    por.mkdir()
    _touch(por, "por1.adf", "por2.adf", "poolsave.adf")
    argv, drives, swaps = _argv(por)
    assert [d.name for d in drives] == ["por1.adf", "por2.adf", "poolsave.adf"]
    assert swaps == []
    assert [a.split("=")[0] for a in argv if a.startswith("--floppy_")] == [
        "--floppy_drive_0", "--floppy_drive_1", "--floppy_drive_2",
        "--floppy_image_0", "--floppy_image_1", "--floppy_image_2",
        "--floppy_drive_speed"]


def _pc(name: str, status=(0, 0), active=1) -> bytes:
    record = bytearray(0x200)
    record[0x60:0x60 + len(name)] = name.encode()
    record[0x5E], record[0x5F] = status
    record[0x184] = active
    return bytes(record)


def _disk3(pcs: list[str], others=("VaultA.DAT", "SavGamA.pty")) -> AmigaDisk:
    disk = AmigaDisk.blank("POD 3")
    disk.make_dir("Save")
    for name in [*others, *pcs]:
        disk.write_file(f"Save/{name}", b"x")
    return disk


def test_the_picker_rows_are_the_pc_files_in_directory_order():
    disk = _disk3(["ONE.pc", "TWO.pc", "THREE.pc"])
    expected = [e.name for e in disk.entries(disk.lookup("Save").block)
                if e.name.endswith(".pc")]
    assert len(expected) == 3
    assert fsuaepor.picker_rows(disk) == expected
    assert "VaultA.DAT" not in expected


def test_the_panel_script_reaches_each_row_and_never_ends_the_session(
        tmp_path, monkeypatch):
    disk = AmigaDisk.blank("POD 3")
    disk.make_dir("Save")
    for n in range(14):
        disk.write_file(f"Save/{n:02d}.pc", b"x")
    names = fsuaepor.picker_rows(disk)
    adf = tmp_path / "pod3.adf"
    disk.save(adf)
    calls: list[tuple] = []
    monkeypatch.setattr(fsuaepor, "keys",
                        lambda a: calls.append(("key", tuple(a.key))))
    monkeypatch.setattr(fsuaepor, "shot",
                        lambda a: calls.append(("shot", a.path.name)))
    monkeypatch.setattr(fsuaepor, "_wait", lambda s: None)
    args = type("A", (), dict(display=":9", adf=str(adf), out=str(tmp_path / "s"),
                              boot=0, payload=[names[4], names[11], names[13]]))
    assert fsuaepor.pod_panel(args) == 0
    pressed = [c[1][0] for c in calls if c[0] == "key"]
    assert "Up" not in pressed and "y" not in pressed
    assert not any(a == b == "e" for a, b in zip(pressed, pressed[1:]))
    adds = [i for i, c in enumerate(calls) if c == ("key", ("a",))]
    assert len(adds) == 4      # ADD CHARACTER's own `a`, then three payloads
    downs = [sum(c == ("key", ("Down",)) for c in calls[lo:hi])
             for lo, hi in zip(adds[:-1], adds[1:])]
    assert downs == [4, 7, 2]
    for i in adds[1:]:
        assert calls[i + 1][0] == "shot"
    for i, c in enumerate(calls):
        if c == ("key", ("v",)):
            assert calls[i + 1][0] == "shot"


def test_pod_stage_leaves_only_the_payloads_in_the_save_drawer(
        tmp_path, monkeypatch, capsys):
    disk3 = _disk3(["OLD.pc"])
    disk3.save(tmp_path / "src3.adf")
    disks = [b"one", b"two", (tmp_path / "src3.adf").read_bytes()]
    payload = tmp_path / "outofparty.pc"
    payload.write_bytes(_pc("CLARISSA", active=0))
    monkeypatch.setattr(fsuaepor, "pod_disks", lambda: disks)
    out = tmp_path / "run"
    assert fsuaepor.pod_stage(type("A", (), dict(out=str(out), pc=[str(payload)]))) == 0
    staged = AmigaDisk((out / "pod3.adf").read_bytes())
    assert fsuaepor.picker_rows(staged) == ["outofparty.pc"]
    assert staged.read_file("Save/VaultA.DAT") == b"x"
    assert staged.read_file("Save/SavGamA.pty") == b"x"
    assert (out / "pod1.adf").read_bytes() == b"one"
    line = next(t for t in capsys.readouterr().out.splitlines() if t.startswith("row"))
    assert "row 1" in line and "'CLARISSA'" in line and "0x184 00" in line


def test_pod_disks_come_out_of_the_registry_in_drive_order():
    try:
        disks = fsuaepor.pod_disks()
    except SystemExit as exc:
        pytest.skip(str(exc))
    first, second, third = (AmigaDisk(d) for d in disks)
    assert [d.volume_name for d in (first, second, third)] == ["POD 1", "POD 2", "POD 3"]
    assert fsuaepor.picker_rows(third)
    assert first.read_file("Pools of Darkness")
