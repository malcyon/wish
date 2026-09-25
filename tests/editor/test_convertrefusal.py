"""File > Convert... refuses a conversion with a reported loss, except the
flagged Pools of Darkness direction, and is on the menu only behind
`WISH_EXPERIMENTAL_POD_CONVERT` (#511, stage 4 / B4).

Every source is synthetic and the rehearsal is a fake whose report carries a
loss, so no game data is read and nothing skips.
"""

from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication

from editor import convert, dosimport
from goldbox import amiga_savegame, dos_port, dos_savegame
from goldbox.amiga_adf import AmigaDisk

LOSSY = SimpleNamespace(
    messages=[],
    losses=["SOVELISS: Name 'Soveliss' is longer than the DOS 15 "
            "characters; truncated"],
    dropped=[])


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _pod_savegame() -> bytes:
    out = bytearray(amiga_savegame.POD_VAR_BYTES)
    out[dos_savegame.POD_PARTY_COUNT - 1] = 1
    out += bytes((3, 4, 2, 5, 137, 0))
    out += bytes((dos_savegame.POD_MODE_DUNGEON,
                  dos_savegame.POD_MODE_DUNGEON))
    out += struct.pack(">HHH", 6, 0, 1)
    record = bytearray(b"\x5A" * amiga_savegame.POD_RECORD_BYTES)
    struct.pack_into(">I", record, amiga_savegame.POD_ITEM_COUNT_AT, 0)
    struct.pack_into(">I", record, amiga_savegame.POD_EFFECT_HEAD_AT, 0)
    record[amiga_savegame.POD_NAME_AT:amiga_savegame.POD_NAME_AT + 5] = \
        b"WHO0\x00"
    out += record
    out += b"\xA5" * (amiga_savegame.POD_SAVEGAME_SIZE - len(out))
    return bytes(out)


def _pod_disk(tmp_path):
    disk = AmigaDisk.blank("PDARKSAVE")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    disk.write_file(amiga_savegame.pod_slot_path("A"), _pod_savegame())
    path = tmp_path / "pod.adf"
    disk.save(path)
    return path


def _dos_folder(tmp_path):
    """Just real enough for `Source.detect` to name its shape."""
    folder = tmp_path / "dos"
    folder.mkdir()
    (folder / "SAVGAMA.DAT").write_bytes(b"\x00")
    (folder / "CHRDATA1.SAV").write_bytes(
        b"\x00" * dos_port.POOL_OF_RADIANCE.record_size)
    return folder


def _capture_modals(monkeypatch):
    warned, critical = [], []
    monkeypatch.setattr(convert.QMessageBox, "warning",
                        lambda self_, t, x: warned.append((t, x)))
    monkeypatch.setattr(convert.QMessageBox, "critical",
                        lambda self_, t, x: critical.append((t, x)))
    return warned, critical


def _lossy_rehearsal(monkeypatch):
    """`saveplan.rehearse` answers a report carrying a loss, whatever the
    direction."""
    monkeypatch.setattr(
        convert.saveplan, "rehearse",
        lambda direction, source, assets: (
            convert.Rehearsal(LOSSY, {"X.SAV": b"\x00"}), "A"))


def test_a_lossy_dos_to_c64_conversion_is_refused_with_the_approved_sentence(
        tmp_path, monkeypatch):
    _lossy_rehearsal(monkeypatch)
    warned, critical = _capture_modals(monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    game_files = dosimport.GameFiles(icon=b"", animate=b"")
    dialog = convert.ConvertDialog(
        str(_dos_folder(tmp_path)), None, lambda game: game_files,
        destination="c64", folder=str(out))
    try:
        #: Construction is not interactive, so no modal fires until the
        #: player's next action replans.
        dialog.replan()
        assert dialog.rehearsal is None
        assert dialog._blocked == (convert.DIALOG_TITLE, convert.CANNOT_CONVERT)
        ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
        assert not ok.isEnabled()
    finally:
        dialog.close()
    assert warned == []
    assert critical == [(convert.DIALOG_TITLE, convert.CANNOT_CONVERT)]
    assert list(out.iterdir()) == []


def test_a_lossy_pools_of_darkness_conversion_is_not_blocked(
        tmp_path, monkeypatch):
    """Its known losses belong to #650 and #651, which fix them behind the
    flag; the experiment keeps its behaviour."""
    monkeypatch.setenv(convert.POD_CONVERT_ENV, "1")
    _lossy_rehearsal(monkeypatch)
    warned, critical = _capture_modals(monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    dialog = convert.ConvertDialog(
        str(_pod_disk(tmp_path)), None, lambda game: None,
        destination="dos", folder=str(out))
    try:
        assert isinstance(dialog.direction, convert.PodAmigaToDos)
        assert dialog.rehearsal is not None
        assert dialog._blocked is None
    finally:
        dialog.close()
    assert (warned, critical) == ([], [])


def test_a_conversion_with_nothing_lost_is_not_refused(tmp_path, monkeypatch):
    clean = SimpleNamespace(messages=[], losses=[], dropped=[])
    monkeypatch.setattr(
        convert.saveplan, "rehearse",
        lambda direction, source, assets: (
            convert.Rehearsal(clean, {"X.SAV": b"\x00"}), "A"))
    _, critical = _capture_modals(monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    game_files = dosimport.GameFiles(icon=b"", animate=b"")
    dialog = convert.ConvertDialog(
        str(_dos_folder(tmp_path)), None, lambda game: game_files,
        destination="c64", folder=str(out))
    try:
        assert dialog.rehearsal is not None
        assert dialog._blocked is None
    finally:
        dialog.close()
    assert critical == []


# -- the menu entry, behind its flag --------------------------------------

FLAG_OFF_MENU = ["&Open…", "Open &DOS folder…", "&Save", "Save &As…",
                 "&Preview changes…", "", "&Preferences…", "", "&Quit"]


def _menu_texts(app, tmp_path, monkeypatch):
    from wish.session import Session
    from wish.window import WishWindow

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    window = WishWindow(maps={}, session=Session(find=lambda pref=None: None))
    try:
        file_menu = next(a.menu() for a in window.menuBar().actions()
                         if a.text() == "&File")
        return [a.text() for a in file_menu.actions()], window.convert_action
    finally:
        window.close()


@pytest.mark.parametrize("value", [None, "", "0", "off", "no"])
def test_the_file_menu_has_no_convert_unless_the_flag_is_on(
        value, app, tmp_path, monkeypatch):
    if value is None:
        monkeypatch.delenv(convert.POD_CONVERT_ENV, raising=False)
    else:
        monkeypatch.setenv(convert.POD_CONVERT_ENV, value)
    texts, action = _menu_texts(app, tmp_path, monkeypatch)
    assert texts == FLAG_OFF_MENU
    assert action is None


def test_the_file_menu_has_convert_in_its_place_when_the_flag_is_on(
        app, tmp_path, monkeypatch):
    monkeypatch.setenv(convert.POD_CONVERT_ENV, "1")
    texts, action = _menu_texts(app, tmp_path, monkeypatch)
    assert texts == ["&Open…", "Open &DOS folder…", "&Save", "Save &As…",
                     "&Preview changes…", convert.MENU_CONVERT, "",
                     "&Preferences…", "", "&Quit"]
    assert action.text() == convert.MENU_CONVERT
