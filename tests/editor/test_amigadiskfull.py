"""A full Amiga disk image shows "Disk is out of space." on every route that
writes one, under that route's own error title, and leaves the image as it was.

The party is a made-up Pool of Radiance save whose disk has no free block.
Its character's item file is one block long; sixteen items make it three, so
Save, Save As and the Convert window each need blocks the disk has not got. A
save that keeps every file its size still fits, because AmigaDOS frees a
replaced file before it allocates the new one. No game data is read.
"""
from __future__ import annotations

import errno
import os
import pathlib
import shutil
import struct

import pytest
from support.editorwindow import make_root
from test_saveasui import _silver_blades_dos_binding
from test_saveplan import SILVER_BLADES, amiga_por_disk

import editor.window as ew
from editor import convert, saveplan
from editor.roster import Party
from goldbox import amiga_savegame, dos_savegame
from goldbox.amiga_adf import AmigaDisk

TEXT = "Disk is out of space."


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _fill(path: pathlib.Path, leave: int = 0) -> bytes:
    """Take every free block but `leave` of the image at `path`, and return
    the image."""
    disk = AmigaDisk.open(str(path))
    disk._allocate(disk.free_count() - leave)
    disk._fix_bitmap()
    disk.save(str(path))
    assert AmigaDisk.open(str(path)).free_count() == leave
    return path.read_bytes()


def _full_party_disk(tmp_path: pathlib.Path) -> pathlib.Path:
    path = amiga_por_disk(tmp_path)
    _fill(path)
    return path


def _carry_sixteen_items(party: Party) -> None:
    inventory = party.members[0].inventory
    raw = next(r for r in inventory.raws if not inventory.block_is_empty(r))
    while inventory.add(raw) is not None:
        pass


def _recorded(monkeypatch) -> list:
    """Every `QMessageBox.critical` the window opens, as `(title, text)`."""
    seen: list = []
    monkeypatch.setattr(
        ew.QMessageBox, "critical",
        lambda _parent, title, text, *a, **k: seen.append((title, text)))
    return seen


def _open(tmp_path, path: pathlib.Path):
    window = ew.EditorBinding(make_root())
    window.backups = str(tmp_path / "backups")
    window.load(str(path))
    assert window.party is not None
    return window


def test_the_line_is_exactly_the_approved_one():
    assert saveplan.DISK_FULL == TEXT
    assert ew.DISK_FULL == TEXT


def test_a_save_in_place_on_a_full_disk_says_so_and_writes_nothing(
        app, monkeypatch, tmp_path):
    path = _full_party_disk(tmp_path)
    before = path.read_bytes()
    window = _open(tmp_path, path)
    boxes = _recorded(monkeypatch)
    _carry_sixteen_items(window.party)
    window.dirty.add(0)

    assert window.save() == "failed"

    assert boxes == [("Cannot save", TEXT)]
    assert path.read_bytes() == before
    assert not (tmp_path / "backups").exists()


def test_a_save_as_started_on_a_full_disk_says_so_and_opens_no_section(
        app, monkeypatch, tmp_path):
    path = _full_party_disk(tmp_path)
    before = path.read_bytes()
    window = _open(tmp_path, path)
    _carry_sixteen_items(window.party)
    boxes = _recorded(monkeypatch)

    window.begin_save_as("amiga")

    assert boxes == [("Cannot save", TEXT)]
    assert window._save_as_port is None
    assert path.read_bytes() == before


def test_a_save_as_pressed_after_the_disk_filled_says_so_and_writes_nothing(
        app, monkeypatch, tmp_path):
    path = _full_party_disk(tmp_path)
    before = path.read_bytes()
    window = _open(tmp_path, path)
    boxes = _recorded(monkeypatch)
    window.begin_save_as("amiga")
    assert boxes == []
    _carry_sixteen_items(window.party)
    target = tmp_path / "out.adf"
    window._child("destination_path").setText(str(target))

    window._child("button_destination_save_as").click()

    assert boxes == [("Cannot save", TEXT)]
    assert not target.exists()
    assert path.read_bytes() == before


def test_the_convert_window_on_a_full_disk_says_so_under_its_own_title(
        app, monkeypatch, tmp_path):
    path = _full_party_disk(tmp_path)
    before = path.read_bytes()
    party = Party(str(path))
    _carry_sixteen_items(party)
    critical: list = []
    monkeypatch.setattr(convert.QMessageBox, "critical",
                        lambda self_, t, x: critical.append((t, x)))
    out = tmp_path / "out"
    out.mkdir()
    dialog = convert.ConvertDialog(
        str(path), party, lambda game: None, destination="dos",
        folder=str(out))
    try:
        dialog.replan()
        assert dialog.rehearsal is None
        assert dialog._blocked == (convert.DIALOG_TITLE, TEXT)
    finally:
        dialog.close()
    assert critical == [(convert.DIALOG_TITLE, TEXT)]
    assert list(out.iterdir()) == []
    assert path.read_bytes() == before


def test_a_save_as_onto_a_full_disk_one_says_so_and_writes_nothing(
        app, monkeypatch, tmp_path):
    from support.amigasavegame import synthetic_disk_one

    binding = _silver_blades_dos_binding(app, tmp_path)
    binding.begin_save_as("amiga")
    one = tmp_path / "one.adf"
    synthetic_disk_one(SILVER_BLADES.key, slots=()).save(str(one))
    before = _fill(one)
    binding._child("destination_amiga_disk_one").setText(str(one))
    boxes = _recorded(monkeypatch)
    target = tmp_path / "fresh.adf"
    binding._child("destination_path").setText(str(target))

    binding._child("button_destination_save_as").click()

    assert boxes == [("Cannot save", TEXT)]
    assert not target.exists()
    assert one.read_bytes() == before


# ---------------------------------------------------------------------------
# The drive itself is full: the operating system answers ENOSPC to the write
# ---------------------------------------------------------------------------

_DRIVE_FULL = [errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)]


def _raise(code: int):
    def fail(*_args, **_kwargs):
        raise OSError(code, os.strerror(code))
    return fail


def _roomy_party_disk(tmp_path: pathlib.Path) -> pathlib.Path:
    return amiga_por_disk(tmp_path)


@pytest.mark.parametrize("code", _DRIVE_FULL)
def test_a_save_on_a_full_drive_says_so_and_leaves_the_image(
        app, monkeypatch, tmp_path, code):
    path = _roomy_party_disk(tmp_path)
    before = path.read_bytes()
    window = _open(tmp_path, path)
    _carry_sixteen_items(window.party)
    boxes = _recorded(monkeypatch)
    monkeypatch.setattr(AmigaDisk, "save", _raise(code))

    assert window.save() == "failed"

    assert boxes == [("Cannot save", TEXT)]
    assert path.read_bytes() == before


def test_a_save_that_fails_for_another_reason_keeps_its_own_text(
        app, monkeypatch, tmp_path):
    path = _roomy_party_disk(tmp_path)
    window = _open(tmp_path, path)
    _carry_sixteen_items(window.party)
    boxes = _recorded(monkeypatch)
    monkeypatch.setattr(AmigaDisk, "save", _raise(errno.EACCES))

    assert window.save() == "failed"

    assert boxes == [("Cannot save", str(OSError(
        errno.EACCES, os.strerror(errno.EACCES))))]


def _save_as_to(window, target: pathlib.Path) -> None:
    window.begin_save_as("amiga")
    window._child("destination_path").setText(str(target))
    window._child("button_destination_save_as").click()


@pytest.mark.parametrize("code", _DRIVE_FULL)
def test_a_save_as_on_a_full_drive_says_so_and_writes_nothing(
        app, monkeypatch, tmp_path, code):
    path = _roomy_party_disk(tmp_path)
    before = path.read_bytes()
    window = _open(tmp_path, path)
    boxes = _recorded(monkeypatch)
    monkeypatch.setattr(ew.files, "replace_file", _raise(code))
    target = tmp_path / "out.adf"

    _save_as_to(window, target)

    assert boxes == [("Cannot save", TEXT)]
    assert not target.exists()
    assert path.read_bytes() == before


def test_a_save_as_that_fails_for_another_reason_keeps_its_own_text(
        app, monkeypatch, tmp_path):
    path = _roomy_party_disk(tmp_path)
    window = _open(tmp_path, path)
    boxes = _recorded(monkeypatch)
    monkeypatch.setattr(ew.files, "replace_file", _raise(errno.EACCES))

    _save_as_to(window, tmp_path / "out.adf")

    assert boxes == [("Cannot save", ew.SAVE_AS_FAILED)]


def _pod_disk(tmp_path: pathlib.Path) -> pathlib.Path:
    """A made-up Pools of Darkness disk 3 holding one slot with one character
    whose record is blank but for the name."""
    out = bytearray(amiga_savegame.POD_VAR_BYTES)
    out[dos_savegame.POD_PARTY_COUNT - 1] = 1
    out += bytes((3, 4, 2, 5, 137, 0))
    out += bytes((dos_savegame.POD_MODE_DUNGEON, dos_savegame.POD_MODE_DUNGEON))
    out += struct.pack(">HHH", 6, 0, 1)
    record = bytearray(amiga_savegame.POD_RECORD_BYTES)
    record[amiga_savegame.POD_NAME_AT:amiga_savegame.POD_NAME_AT + 5] = \
        b"WHO0\x00"
    out += record
    out += b"\xA5" * (amiga_savegame.POD_SAVEGAME_SIZE - len(out))
    disk = AmigaDisk.blank("PDARKSAVE")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    disk.write_file(amiga_savegame.pod_slot_path("A"), bytes(out))
    path = tmp_path / "pod.adf"
    disk.save(str(path))
    return path


def _convert_pod(window, monkeypatch, tmp_path, code: int):
    """File > Convert of a made-up Pools of Darkness disk to a DOS folder,
    whose write fails with `code`. Returns the folder and the line shown."""
    from PyQt6.QtWidgets import QDialog

    monkeypatch.setenv(convert.POD_CONVERT_ENV, "1")
    monkeypatch.setattr(convert.PodAmigaToDos, "write", _raise(code))
    answers = iter([QDialog.DialogCode.Accepted])
    monkeypatch.setattr(
        convert.ConvertDialog, "exec",
        lambda self: next(answers, QDialog.DialogCode.Rejected))
    out = tmp_path / "out"
    out.mkdir()
    disk = _pod_disk(tmp_path)
    boxes = _recorded(monkeypatch)
    window.convert(source=str(disk), destination="dos", folder=str(out))
    return out, boxes, disk


@pytest.mark.parametrize("code", _DRIVE_FULL)
def test_a_conversion_on_a_full_drive_says_so_and_leaves_no_folder(
        app, monkeypatch, tmp_path, code):
    window = ew.EditorBinding(make_root())
    out, boxes, disk = _convert_pod(window, monkeypatch, tmp_path, code)
    assert boxes == [(convert.DIALOG_TITLE, TEXT)]
    assert list(out.iterdir()) == []


def test_a_conversion_that_fails_for_another_reason_keeps_its_own_text(
        app, monkeypatch, tmp_path):
    window = ew.EditorBinding(make_root())
    out, boxes, disk = _convert_pod(window, monkeypatch, tmp_path,
                                    errno.EACCES)
    assert boxes == [(convert.DIALOG_TITLE, convert.CANNOT_CONVERT)]


def test_an_error_with_no_errno_is_not_out_of_space_even_without_edquot(
        monkeypatch):
    from editor import files

    monkeypatch.delattr(errno, "EDQUOT", raising=False)
    assert not files.out_of_space(OSError("copy failed"))
    assert not files.out_of_space(shutil.Error("copy failed"))
    assert files.out_of_space(OSError(errno.ENOSPC, "full"))
