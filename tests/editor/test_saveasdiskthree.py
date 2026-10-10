"""The Pools of Darkness disk 3 row in the Save As Amiga destination section,
behind `WISH_EXPERIMENTAL_POD_CONVERT`.

The row appears only when Preferences cannot supply the disk, stays once
shown, and holds Save As off while the file named at it is not a disk 3. Its
caption, picker title, wrong-file pop-up and full-disk pop-up carry the
wording Donald approved. They read no game data.
"""
from __future__ import annotations

import pathlib

import pytest
from support.editorwindow import make_root
from test_podparty import _flag
from test_podwindow import _no_box, _window
from test_saveplan_pod import _disk_file, _disk_one, _disk_three, _dos_folder

import editor.window as ew
from editor import convert

ROW = "box_amiga_disk_three"
FIELD = "destination_amiga_disk_three"
SAVE_AS = "button_destination_save_as"


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _save_as_amiga(monkeypatch, tmp_path, preferences=None):
    """A DOS Pools of Darkness save open, Save As Amiga chosen, with
    `preferences` as the Pools of Darkness folder in Preferences."""
    _flag(monkeypatch, "1")
    _no_box(monkeypatch)
    window = _window(preferences)
    window.load(str(_dos_folder(tmp_path)))
    window.begin_save_as("amiga")
    return window


def _recorded_boxes(monkeypatch) -> list:
    """Every `QMessageBox.critical` call as `(title, text)`, in order."""
    seen: list = []
    monkeypatch.setattr(
        ew.QMessageBox, "critical",
        lambda _parent, title, text, *a, **k: seen.append((title, text)))
    return seen


def _preferences(tmp_path, *disks) -> pathlib.Path:
    folder = tmp_path / "preferences"
    folder.mkdir()
    for name, disk in disks:
        (folder / name).write_bytes(disk.to_bytes())
    return folder


def test_a_disk_three_in_preferences_shows_no_row_and_leaves_save_as_on(
        app, monkeypatch, tmp_path):
    folder = _preferences(tmp_path, ("three.adf", _disk_three()))
    window = _save_as_amiga(monkeypatch, tmp_path, folder)
    assert window._child(ROW).isHidden()
    assert window._child(SAVE_AS).isEnabled()


def test_no_disk_three_in_preferences_shows_the_row_and_holds_save_as(
        app, monkeypatch, tmp_path):
    folder = _preferences(tmp_path, ("one.adf", _disk_one()))
    window = _save_as_amiga(monkeypatch, tmp_path, folder)
    assert not window._child(ROW).isHidden()
    assert window._child(FIELD).text() == ""
    assert not window._child(SAVE_AS).isEnabled()


def test_no_preferences_folder_at_all_shows_the_row(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    assert not window._child(ROW).isHidden()
    assert not window._child(SAVE_AS).isEnabled()


def test_a_disk_three_typed_at_the_row_frees_save_as_and_the_row_stays(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    window._child(FIELD).setText(str(_disk_file(tmp_path, _disk_three())))
    assert window._child(SAVE_AS).isEnabled()
    assert not window._child(ROW).isHidden()


def test_typing_another_disk_at_the_row_opens_no_pop_up_and_holds_save_as(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    boxes = _recorded_boxes(monkeypatch)
    window._child(FIELD).setText(
        str(_disk_file(tmp_path, _disk_one(), "disk1.adf")))
    assert boxes == []
    assert not window._child(SAVE_AS).isEnabled()
    assert not window._child(ROW).isHidden()


def test_finishing_the_edit_of_another_disk_pops_up_once_and_clears_the_row(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    boxes = _recorded_boxes(monkeypatch)
    field = window._child(FIELD)
    field.setText(str(_disk_file(tmp_path, _disk_one(), "disk1.adf")))
    field.editingFinished.emit()
    assert boxes == [(ew.CANNOT_SAVE_TITLE, ew.WRONG_DISK_THREE)]
    assert field.text() == ""
    assert not window._child(ROW).isHidden()
    assert not window._child(SAVE_AS).isEnabled()
    field.editingFinished.emit()
    assert len(boxes) == 1


def test_choosing_the_right_disk_after_the_wrong_one_frees_save_as(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    boxes = _recorded_boxes(monkeypatch)
    field = window._child(FIELD)
    field.setText(str(_disk_file(tmp_path, _disk_one(), "disk1.adf")))
    field.editingFinished.emit()
    field.setText(str(_disk_file(tmp_path, _disk_three())))
    field.editingFinished.emit()
    assert len(boxes) == 1
    assert window._child(SAVE_AS).isEnabled()


def test_a_file_that_is_no_disk_at_all_pops_up_the_wrong_disk_three(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    boxes = _recorded_boxes(monkeypatch)
    notes = tmp_path / "notes.adf"
    notes.write_bytes(b"not a disk")
    field = window._child(FIELD)
    field.setText(str(notes))
    field.editingFinished.emit()
    assert boxes == [(ew.CANNOT_SAVE_TITLE, ew.WRONG_DISK_THREE)]
    assert field.text() == ""
    assert not window._child(SAVE_AS).isEnabled()


def test_finishing_the_edit_of_an_empty_row_opens_no_pop_up(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    boxes = _recorded_boxes(monkeypatch)
    window._child(FIELD).editingFinished.emit()
    assert boxes == []


def test_browse_returning_another_disk_pops_up_and_clears_the_row(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    boxes = _recorded_boxes(monkeypatch)
    disk = _disk_file(tmp_path, _disk_one(), "disk1.adf")
    monkeypatch.setattr(ew.QFileDialog, "getOpenFileName",
                        lambda *a: (str(disk), ""))
    window._child("button_amiga_disk_three_browse").click()
    assert boxes == [(ew.CANNOT_SAVE_TITLE, ew.WRONG_DISK_THREE)]
    assert window._child(FIELD).text() == ""
    assert not window._child(SAVE_AS).isEnabled()


def test_the_browse_button_opens_the_disk_three_picker_and_fills_the_row(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    disk = _disk_file(tmp_path, _disk_three())
    asked = []

    def picked(*args):
        asked.append((args[1], args[3]))
        return str(disk), ""
    monkeypatch.setattr(ew.QFileDialog, "getOpenFileName", picked)
    boxes = _recorded_boxes(monkeypatch)
    window._child("button_amiga_disk_three_browse").click()
    assert asked == [(convert.DISK_THREE_TITLE, convert.DISK_FILTER)]
    assert window._child(FIELD).text() == str(disk)
    assert window._child(SAVE_AS).isEnabled()
    assert boxes == []


def test_a_new_save_as_forgets_the_row_and_what_was_typed_at_it(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    window._child(FIELD).setText(
        str(_disk_file(tmp_path, _disk_one(), "disk1.adf")))
    window.begin_save_as("amiga")
    assert window._child(FIELD).text() == ""
    assert not window._child(ROW).isHidden()
    window.begin_save_as("dos")
    assert window._child(ROW).isHidden()


def test_a_save_as_dos_shows_no_disk_three_row(app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    window.begin_save_as("dos")
    assert window._child(ROW).isHidden()


def test_the_row_stays_off_every_other_titles_save_as(app, tmp_path):
    from gamedata import synthetic_save

    path = synthetic_save(tmp_path, "SYNTHETIC.D64")
    window = ew.EditorBinding(make_root(), str(path))
    for port in ("c64", "dos", "amiga"):
        window.begin_save_as(port)
        assert window._child(ROW).isHidden()


def test_the_four_approved_strings_are_exactly_these(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    assert (window._child("label_amiga_disk_three_caption").text()
            == "Amiga game disk 3")
    assert convert.DISK_THREE_TITLE == "Select location of Amiga game disk 3"
    assert ew.WRONG_DISK_THREE == (
        "This is not a Pools of Darkness Amiga game disk 3.")
    assert ew.DISK_FULL == "Disk is out of space."


def test_the_row_has_no_inline_wrong_disk_line(app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    assert window._child("label_amiga_disk_three_wrong") is None


def test_a_full_disk_three_pops_up_the_disk_is_full_line_and_writes_nothing(
        app, monkeypatch, tmp_path):
    full = _disk_three()
    full._allocate(full.free_count() - 2)
    full._fix_bitmap()
    window = _save_as_amiga(monkeypatch, tmp_path)
    boxes = _recorded_boxes(monkeypatch)
    field = window._child(FIELD)
    field.setText(str(_disk_file(tmp_path, full)))
    target = tmp_path / "out.adf"
    window._child("destination_path").setText(str(target))
    window._child(SAVE_AS).click()
    assert boxes == [(ew.CANNOT_SAVE_TITLE, ew.DISK_FULL)]
    assert not target.exists()


# ---------------------------------------------------------------------------
# The flag: the row exists only where the Amiga destination does
# ---------------------------------------------------------------------------

def _amiga_offered(window) -> bool:
    return any(d.destination_port == "amiga"
               for d in convert.destinations_for(window._save_as_source))


@pytest.mark.parametrize("value", [None, "0", "off"])
def test_flag_off_at_open_the_save_never_loads_and_no_row_shows(
        app, monkeypatch, tmp_path, value):
    _flag(monkeypatch, value)
    monkeypatch.setattr(ew.QMessageBox, "critical", lambda *a, **k: None)
    window = _window()
    window.load(str(_dos_folder(tmp_path)))
    window.begin_save_as("amiga")
    assert window.party is None
    assert window._save_as_source is None
    assert window._child("destination_section").isHidden()


@pytest.mark.parametrize("value", [None, "0", "off"])
def test_flag_off_offers_no_amiga_destination_for_a_dos_save(
        app, monkeypatch, tmp_path, value):
    window = _save_as_amiga(monkeypatch, tmp_path)
    assert _amiga_offered(window)
    _flag(monkeypatch, value)
    assert not _amiga_offered(window)


def test_flag_on_offers_amiga_and_shows_the_row(app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    assert _amiga_offered(window)
    assert not window._child(ROW).isHidden()
