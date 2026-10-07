"""The Pools of Darkness disk 3 row in the Save As Amiga destination section,
behind `WISH_EXPERIMENTAL_POD_CONVERT`.

The row appears only when Preferences cannot supply the disk, stays once
shown, and holds Save As off while the file named at it is not a disk 3. Its
three strings are empty until Donald words them, so these tests pin the
behaviour and not any text. They read no game data.
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
WRONG = "label_amiga_disk_three_wrong"
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
    assert window._child(WRONG).isHidden()
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
    assert window._child(WRONG).isHidden()


def test_another_disk_at_the_row_holds_save_as_and_shows_the_wrong_line(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    window._child(FIELD).setText(
        str(_disk_file(tmp_path, _disk_one(), "disk1.adf")))
    assert not window._child(SAVE_AS).isEnabled()
    assert not window._child(ROW).isHidden()
    assert not window._child(WRONG).isHidden()
    assert window._child(WRONG).text() == ew.WRONG_DISK_THREE


def test_choosing_the_right_disk_after_the_wrong_one_clears_the_line(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    field = window._child(FIELD)
    field.setText(str(_disk_file(tmp_path, _disk_one(), "disk1.adf")))
    field.setText(str(_disk_file(tmp_path, _disk_three())))
    assert window._child(WRONG).isHidden()
    assert window._child(SAVE_AS).isEnabled()


def test_a_file_that_is_no_disk_at_all_is_a_wrong_disk_three(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    notes = tmp_path / "notes.adf"
    notes.write_bytes(b"not a disk")
    window._child(FIELD).setText(str(notes))
    assert not window._child(WRONG).isHidden()
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
    window._child("button_amiga_disk_three_browse").click()
    assert asked == [(convert.DISK_THREE_TITLE, convert.DISK_FILTER)]
    assert window._child(FIELD).text() == str(disk)
    assert window._child(SAVE_AS).isEnabled()


def test_a_new_save_as_forgets_the_row_and_what_was_typed_at_it(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    window._child(FIELD).setText(
        str(_disk_file(tmp_path, _disk_one(), "disk1.adf")))
    window.begin_save_as("amiga")
    assert window._child(FIELD).text() == ""
    assert window._child(WRONG).isHidden()
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


def test_the_three_strings_stay_empty_until_donald_words_them(
        app, monkeypatch, tmp_path):
    window = _save_as_amiga(monkeypatch, tmp_path)
    assert window._child("label_amiga_disk_three_caption").text() == ""
    assert convert.DISK_THREE_TITLE == ""
    assert ew.WRONG_DISK_THREE == ""


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
