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

import pytest
from support.editorwindow import make_root
from test_saveasui import _silver_blades_dos_binding
from test_saveplan import SILVER_BLADES, amiga_por_disk

import editor.window as ew
from editor import saveplan
from editor.roster import Party
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


def test_an_error_with_no_errno_is_not_out_of_space_even_without_edquot(
        monkeypatch):
    from editor import files

    monkeypatch.delattr(errno, "EDQUOT", raising=False)
    assert not files.out_of_space(OSError("copy failed"))
    assert not files.out_of_space(shutil.Error("copy failed"))
    assert files.out_of_space(OSError(errno.ENOSPC, "full"))


# ---------------------------------------------------------------------------
# A Pools of Darkness Amiga disk saved as a DOS folder
# ---------------------------------------------------------------------------

def _pod_disk_binding(tmp_path: pathlib.Path, monkeypatch):
    """The made-up Pools of Darkness disk 3 of `test_doscase`, opened."""
    from test_doscase import _amiga_save

    from goldbox import amiga_savegame

    disk = AmigaDisk.blank("PDARKSAVE")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    disk.write_file(amiga_savegame.pod_slot_path("A"), _amiga_save())
    path = tmp_path / "pod.adf"
    disk.save(str(path))
    # No game disk is set, so opening shows the Missing Game Disk warning.
    monkeypatch.setattr(ew.QMessageBox, "warning", lambda *a, **k: None)
    _recorded(monkeypatch)
    window = ew.EditorBinding(make_root())
    window.load(str(path))
    assert window.party is not None
    return window


def _save_as_dos(window, target: pathlib.Path) -> None:
    window.begin_save_as("dos")
    window._child("destination_path").setText(str(target))
    window._child("button_destination_save_as").click()


@pytest.mark.parametrize("code", _DRIVE_FULL)
def test_a_pools_of_darkness_save_as_dos_on_a_full_drive_says_so_and_leaves_no_folder(
        app, monkeypatch, tmp_path, code):
    window = _pod_disk_binding(tmp_path, monkeypatch)
    boxes = _recorded(monkeypatch)
    monkeypatch.setattr(ew.files, "publish_folder", _raise(code))
    out = tmp_path / "out"

    _save_as_dos(window, out)

    assert boxes == [("Cannot save", TEXT)]
    assert not out.exists() or list(out.iterdir()) == []


def test_a_pools_of_darkness_save_as_dos_that_fails_for_another_reason_keeps_its_own_text(
        app, monkeypatch, tmp_path):
    window = _pod_disk_binding(tmp_path, monkeypatch)
    boxes = _recorded(monkeypatch)
    monkeypatch.setattr(ew.files, "publish_folder", _raise(errno.EACCES))

    _save_as_dos(window, tmp_path / "out")

    assert boxes == [("Cannot save", ew.SAVE_AS_FAILED)]
