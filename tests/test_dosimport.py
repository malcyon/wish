"""File > Import > DOS save: the window over `por/dos.py`'s converter.

The conversion itself is `tests/test_dosconvert.py`'s. What is tested here is
the one thing a menu can get wrong that a command line cannot: **the losses
are on screen before anything is written**, and a refusal reaches the user as
a sentence rather than as a traceback.

Both halves need somebody's files. The DOS save is Donald's unpacked copy of
*Forgotten Realms: The Archives* (`$FR_ARCHIVES`), the C64 template is his save
disk directory, and with either missing the module skips -- which is what CI
does. Nothing here opens a window: `tests/conftest.py` forces the offscreen
platform before Qt is imported.
"""

from __future__ import annotations

import pathlib

import pytest
from gamedata import disk_path
from test_dossave import _save_dir, needs_dos_saves

from por import dos, dos_savegame

# `PORSAVE11` stands in New Phlan, which is where the archives' slot A party
# stands; `PORSAVE13` stands in the Slums. Since the loaded-files cache was
# decoded either will do as a template, and that is what the pair now tests.
# Both are read only ever as a template and always through a copy.
SAME_AREA = "PORSAVE11"
OTHER_AREA = "PORSAVE13"

needs_disks = pytest.mark.skipif(
    disk_path(SAME_AREA) is None or disk_path(OTHER_AREA) is None,
    reason="needs the save disks")


@pytest.fixture
def app():
    """The session-wide application `tests/conftest.py` holds a reference to."""
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _copy(name: str, tmp_path) -> pathlib.Path:
    src = disk_path(name)
    if src is None:
        pytest.skip("needs the save disks")
    out = tmp_path / f"{name}.D64"
    out.write_bytes(src.read_bytes())
    return out


@pytest.fixture
def template(tmp_path):
    return _copy(SAME_AREA, tmp_path)


@pytest.fixture
def elsewhere(tmp_path):
    return _copy(OTHER_AREA, tmp_path)


@pytest.fixture
def dos_save():
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES")
    return where


# --- the rehearsal, which is the whole point --------------------------------

@needs_dos_saves
@needs_disks
def test_the_conversion_is_rehearsed_and_writes_nothing(dos_save, template):
    """`rehearse` builds the converted disk in memory and leaves the file it
    read alone. Everything downstream depends on that: the report cannot be
    shown before the write unless there is a conversion with no write in it."""
    from editor.dosimport import rehearse

    before = template.read_bytes()
    conversion = rehearse(dos_save, "A", template)
    assert template.read_bytes() == before
    assert conversion.disk.to_bytes() != before
    assert conversion.report.dropped


@needs_dos_saves
@needs_disks
def test_the_report_names_the_fields_with_no_c64_home(dos_save, template):
    """The list `docs/117-save-conversion.md` requires: encumbrance, the item
    count, the icon choice and the strength-bonus boolean, by name."""
    from editor.dosimport import dropped_text, rehearse

    text = dropped_text(rehearse(dos_save, "A", template).report)
    for field in ("encumbrance", "item_count", "icon_choice", "strength_bonus"):
        assert field in text


# --- the window -------------------------------------------------------------

@needs_dos_saves
@needs_disks
def test_the_losses_are_on_screen_before_the_button_is_pressable(
        app, dos_save, template):
    """The dialog rehearses on construction, so the pane is filled and the
    template file is untouched at the moment Convert first becomes pressable."""
    from PyQt6.QtWidgets import QDialogButtonBox

    from editor.dosimport import DROPPED_HEADING, DosImportDialog

    before = template.read_bytes()
    dialog = DosImportDialog(dos_save, template)
    text = dialog.report_pane.toPlainText()
    assert text.startswith(DROPPED_HEADING)
    assert "encumbrance" in text
    assert dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert template.read_bytes() == before


@needs_dos_saves
@needs_disks
def test_a_template_from_another_area_converts(app, dos_save, elsewhere):
    """A Slums template against a New Phlan DOS party. This was the refusal;
    the loaded-files cache is decoded and `convert_save` writes it, so the
    dialog rehearses, reports the losses and offers the button like any other
    template. `docs/140-loaded-files-cache.md`."""
    from PyQt6.QtWidgets import QDialogButtonBox

    from editor.dosimport import DROPPED_HEADING, DosImportDialog

    dialog = DosImportDialog(dos_save, elsewhere)
    text = dialog.report_pane.toPlainText()
    assert text.startswith(DROPPED_HEADING)
    assert "Traceback" not in text
    assert dialog.conversion is not None
    assert dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()
    payload = dialog.conversion.save0.to_bytes()
    at = dos.FILE_CACHE[0] - dos.SAVE0_BASE
    there = dos_savegame.area_id(
        (dos_save / f"SAVGAM{dialog.slot}.DAT").read_bytes())
    want = bytearray(b"\xFF" * dos.FILE_CACHE[1])
    want[dos.CACHE_GEO] = want[dos.CACHE_ECL] = there
    # Slot 11: the save carries `ANIMATE00` in `SAVEDGAME1`'s tail, so the
    # cache has to say it is resident or the party cannot walk into an area
    # (#102). The literal 11 and 0, not the module's names, so this fails on a
    # renumbering rather than following it.
    want[11] = 0
    assert payload[at:at + dos.FILE_CACHE[1]] == bytes(want)


@needs_dos_saves
@needs_disks
def test_changing_the_template_re_rehearses(app, dos_save, template,
                                            elsewhere):
    """Every change re-rehearses, so the pane is never the losses of a
    conversion other than the one the button would commit."""
    from editor.dosimport import DosImportDialog

    dialog = DosImportDialog(dos_save, elsewhere)
    first = dialog.conversion
    assert first is not None
    dialog.set_template(template)
    assert dialog.conversion is not None and dialog.conversion is not first
    assert dialog.conversion.template == template


@needs_dos_saves
def test_with_no_template_there_is_nothing_to_convert(app, dos_save):
    from PyQt6.QtWidgets import QDialogButtonBox

    from editor.dosimport import NO_TEMPLATE, DosImportDialog

    dialog = DosImportDialog(dos_save)
    assert dialog.report_pane.toPlainText() == NO_TEMPLATE
    assert not dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()


@needs_dos_saves
def test_the_slots_offered_are_the_ones_the_folder_holds(app, dos_save):
    from editor.dosimport import DosImportDialog

    dialog = DosImportDialog(dos_save)
    offered = [dialog.slots.itemText(i) for i in range(dialog.slots.count())]
    assert offered == dos.slots_available(dos_save)


# --- what reaches the editor -------------------------------------------------

@needs_dos_saves
@needs_disks
def test_the_import_lands_unsaved_and_the_editors_own_save_writes_it(
        app, tmp_path, dos_save, template):
    """The converted party is in the window, marked dirty, and the file on
    disk is still the template. Save is what writes it -- through
    `editor/files.py`, so the backup is taken like any other write."""
    from editor.dosimport import rehearse
    from editor.window import EditorWindow

    before = template.read_bytes()
    window = EditorWindow(backups=str(tmp_path / "backups"))
    note = window.adopt_conversion(rehearse(dos_save, "A", template))

    assert window.dirty                      # unsaved, and the title says so
    assert window.path == template
    assert template.read_bytes() == before   # nothing written yet
    # Slot order, which the C64 reads back to front: the character DOS lists
    # first is the one the game puts at the head of the marching order, and
    # that is the *highest* slot (#101, `dos.marching_slot`).
    names = [m.name for m in window.party.members if m.name]
    assert names == [c.name for c in dos.read_party(dos_save, "A")][::-1]
    assert "slot A" in note or "A" in note

    window.save(interactive=False)
    assert template.read_bytes() != before
    assert list((tmp_path / "backups").glob("*.D64.*"))
    window.close()


@needs_dos_saves
@needs_disks
def test_import_dos_save_is_cancellable_without_touching_anything(
        app, tmp_path, dos_save, template, monkeypatch):
    """A folder picker dismissed is a menu item that did nothing."""
    from editor.window import EditorWindow

    window = EditorWindow(backups=str(tmp_path / "backups"))
    before = template.read_bytes()
    assert window.import_dos_save(folder="") == "cancelled"
    assert template.read_bytes() == before
    window.close()


def test_a_folder_with_no_dos_save_says_so(app, tmp_path, monkeypatch):
    """And says it in a box rather than opening an empty conversion window."""
    import editor.window as ew
    from editor.window import EditorWindow

    said = []
    monkeypatch.setattr(ew.QMessageBox, "warning",
                        lambda *a, **k: said.append(a[2]))
    window = EditorWindow(backups=str(tmp_path / "backups"))
    assert window.import_dos_save(folder=str(tmp_path)) == "no DOS save"
    assert said and str(tmp_path) in said[0]
    window.close()


# --- the menu ----------------------------------------------------------------

def _window(tmp_path, monkeypatch):
    """A window with nothing to attach to. The caller closes it."""
    from wish.session import Session
    from wish.window import WishWindow

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # Nothing answering, and nothing looked for: a menu test must not go
    # probing the ports a human's own game session is on.
    return WishWindow(maps={}, session=Session(find=lambda pref=None: None))


def _file_menu(window):
    return next(a.menu() for a in window.menuBar().actions()
                if a.text() == "&File")


def test_the_import_is_not_offered_unless_it_is_asked_for(app, tmp_path,
                                                          monkeypatch):
    """The gate, asserted from the outside: no submenu, not a greyed one.

    The conversion drops the portrait and the clock in this direction too
    (#57, #58), so until those close a player should not be able to reach it
    by accident. `dosimport.ENV` unset is the shipped state.
    """
    from editor.dosimport import ENV, MENU_IMPORT

    monkeypatch.delenv(ENV, raising=False)
    window = _window(tmp_path, monkeypatch)
    assert MENU_IMPORT not in [a.text() for a in _file_menu(window).actions()]
    assert window.import_dos_action is None
    window.close()


def test_a_variable_somebody_forgot_does_not_turn_it_on(app, tmp_path,
                                                        monkeypatch):
    """`0` and `off` are off, the same rule `wish/debugmode.py` follows."""
    from editor.dosimport import ENV, MENU_IMPORT

    for value in ("", "0", "off", "no"):
        monkeypatch.setenv(ENV, value)
        window = _window(tmp_path, monkeypatch)
        assert MENU_IMPORT not in [a.text()
                                   for a in _file_menu(window).actions()], value
        window.close()


def test_the_file_menu_carries_the_import(app, tmp_path, monkeypatch):
    from editor.dosimport import ENV, MENU_DOS_SAVE, MENU_IMPORT
    from wish.window import WishWindow  # noqa: F401

    monkeypatch.setenv(ENV, "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # Nothing answering, and nothing looked for: a menu test must not go
    # probing the ports a human's own game session is on.
    from wish.session import Session
    window = WishWindow(maps={},
                        session=Session(find=lambda pref=None: None))
    file_menu = next(a.menu() for a in window.menuBar().actions()
                     if a.text() == "&File")
    submenu = next(a.menu() for a in file_menu.actions()
                   if a.text() == MENU_IMPORT)
    assert [a.text() for a in submenu.actions()] == [MENU_DOS_SAVE]
    assert window.import_dos_action.text() == MENU_DOS_SAVE
    window.close()
