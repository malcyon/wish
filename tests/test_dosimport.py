"""File > Import > DOS save: the window over `goldbox/dos.py`'s converter.

The conversion itself is `tests/test_dosconvert.py`'s. What is tested here is
the one thing a menu can get wrong that a command line cannot: **the losses
are on screen before anything is written**, a refusal reaches the user as a
sentence rather than as a traceback, and the import refuses outright when the
player's game disks are not there rather than writing a save with invented
bytes in it (#118).

Both halves need somebody's files. The DOS save is Donald's unpacked copy of
*Forgotten Realms: The Archives* (`$FR_ARCHIVES`) and the game disks are his
`POOL*.D64`; with either missing the tests that need them skip, which is what
CI does. Nothing here opens a window: `tests/conftest.py` forces the offscreen
platform before Qt is imported.
"""

from __future__ import annotations

import pytest
from gamedata import disk_dir, game_disk
from test_dossave import _save_dir, needs_dos_saves

from goldbox import dos, dos_savegame

needs_disks = pytest.mark.skipif(disk_dir() is None,
                                 reason="needs the game disks")


@pytest.fixture
def app():
    """The session-wide application `tests/conftest.py` holds a reference to."""
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dos_save():
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES")
    return where


@pytest.fixture
def files():
    """The icon and `ANIMATE00`, read off the player's own disks.

    The two live on different sides -- `SPELLE64`/`SPELLN64` on the
    character-creation disk and `ANIMATE00` on all eight -- so each is found
    by trying to read it, which is what `EditorWindow._find_disk` does in the
    running program.
    """
    from editor.dosimport import GameFiles
    from goldbox.d64 import load_payload
    from goldbox.iconparts import IconParts

    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks")
    icon = animate = None
    icon_disk = animate_disk = ""
    for disk in sorted(where.glob("POOL*.[dD]64")):
        try:
            if icon is None:
                icon = IconParts.load(str(disk)).default_icon()
                icon_disk = str(disk)
        except Exception:
            pass
        try:
            if animate is None:
                animate = load_payload(str(disk), dos.ANIMATE_FILE)
                animate_disk = str(disk)
        except Exception:
            pass
    if icon is None or animate is None:
        pytest.skip("the game disks here carry neither SPELLE64 nor ANIMATE00")
    return GameFiles(icon=icon, animate=animate,
                     icon_disk=icon_disk, animate_disk=animate_disk)


# --- the rehearsal, which is the whole point --------------------------------

@needs_dos_saves
@needs_disks
def test_the_conversion_is_rehearsed_and_writes_nothing(dos_save, files,
                                                        tmp_path):
    """`rehearse` builds the converted disk in memory and touches no file at
    all. Everything downstream depends on that: the report cannot be shown
    before the write unless there is a conversion with no write in it.

    It now has no template to leave alone either, so what this asserts is the
    stronger thing -- the directory it was pointed at is unchanged and the
    working directory has gained nothing.
    """
    from editor.dosimport import rehearse

    before = sorted((p.name, p.stat().st_mtime, p.stat().st_size)
                    for p in dos_save.iterdir() if p.is_file())
    conversion = rehearse(dos_save, "A", files)
    after = sorted((p.name, p.stat().st_mtime, p.stat().st_size)
                   for p in dos_save.iterdir() if p.is_file())
    assert after == before
    assert conversion.report.dropped
    assert len(conversion.disk.to_bytes()) == 174848


@needs_dos_saves
@needs_disks
def test_the_converted_disk_carries_the_two_files_and_nothing_else(
        dos_save, files):
    """Thirteen of the player's fifteen save disks hold `SAVEDGAME1` and
    `SAVEDGAME0` in that order and nothing else, so that is what a disk built
    from nothing has to be -- and it has to read back as a Pool of Radiance
    save with this party in it."""
    from editor.dosimport import rehearse
    from goldbox.savegame import load_save

    conversion = rehearse(dos_save, "A", files)
    names = [bytes(e.name) for e in conversion.disk.directory()]
    assert names == [b"SAVEDGAME1", b"SAVEDGAME0"]
    game, sg0, _sg1 = load_save(conversion.disk)
    assert game.key == conversion.game.key
    read_back = [s.record.name for s in sg0.slots if s.occupied]
    assert read_back == [c.name for c in dos.read_party(dos_save, "A")][::-1]


@needs_dos_saves
@needs_disks
def test_nothing_in_the_converted_save_is_left_to_a_previous_owner(
        dos_save, files):
    """The whole of #118 in one assertion: every one of the 9216 bytes has a
    provenance and none of them is "whatever was already there".

    `unwritten` is the list of offsets the conversion did not write. Against a
    template it holds 5405 of them; from nothing it must be empty, and
    `new_save` refuses rather than returning a save it cannot account for.
    """
    from editor.dosimport import rehearse

    report = rehearse(dos_save, "A", files).report
    assert report.unwritten == []
    assert report.unaccounted == []
    assert len(report.sources) == report.total == 9216


@needs_dos_saves
@needs_disks
def test_the_report_names_the_fields_with_no_c64_home(dos_save, files):
    """The list `docs/117-save-conversion.md` requires: encumbrance, the item
    count, the portrait and icon ids, the icon colours and the strength-bonus
    boolean, by name.

    The portrait entry used to be one field called `icon_choice`; #57 split it
    into the four the record actually has, so the report names four.
    """
    from editor.dosimport import dropped_text, rehearse

    text = dropped_text(rehearse(dos_save, "A", files).report)
    for field in ("encumbrance", "item_count", "strength_bonus",
                  "portrait_head", "portrait_body", "icon_head", "icon_body",
                  "icon_colours"):
        assert field in text, field


# --- the window -------------------------------------------------------------

@needs_dos_saves
@needs_disks
def test_the_losses_are_on_screen_before_the_button_is_pressable(
        app, dos_save, files):
    """The dialog rehearses on construction, so the pane is filled at the
    moment Convert first becomes pressable."""
    from PyQt6.QtWidgets import QDialogButtonBox

    from editor.dosimport import DROPPED_HEADING, DosImportDialog

    dialog = DosImportDialog(dos_save, files)
    text = dialog.report_pane.toPlainText()
    assert text.startswith(DROPPED_HEADING)
    assert "encumbrance" in text
    assert dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()


@needs_dos_saves
@needs_disks
def test_the_save_points_at_the_area_the_dos_party_is_in(app, dos_save, files):
    """There is no template to agree or disagree with any more, so the
    loaded-files cache is computed from the DOS save alone every time.
    `docs/140-loaded-files-cache.md`."""
    from editor.dosimport import DosImportDialog

    dialog = DosImportDialog(dos_save, files)
    assert dialog.conversion is not None
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
def test_changing_the_slot_re_rehearses(app, dos_save, files):
    """Every change re-rehearses, so the pane is never the losses of a
    conversion other than the one the button would commit."""
    from editor.dosimport import DosImportDialog

    offered = dos.slots_available(dos_save)
    if len(offered) < 2:
        pytest.skip("needs a DOS save folder holding two slots")
    dialog = DosImportDialog(dos_save, files)
    first = dialog.conversion
    assert first is not None
    other = next(s for s in offered if s != dialog.slot)
    dialog.slots.setCurrentText(other)
    assert dialog.conversion is not None and dialog.conversion is not first
    assert dialog.conversion.slot == other


@needs_dos_saves
@needs_disks
def test_the_slots_offered_are_the_ones_the_folder_holds(app, dos_save, files):
    from editor.dosimport import DosImportDialog

    dialog = DosImportDialog(dos_save, files)
    offered = [dialog.slots.itemText(i) for i in range(dialog.slots.count())]
    assert offered == dos.slots_available(dos_save)


# --- the refusal when the game disks are missing (#118) ----------------------

def test_no_game_disks_is_a_pop_up_and_no_folder_picker(app, tmp_path,
                                                        monkeypatch):
    """Donald's ruling, 2026-08-27: *"We should never attempt to write a save
    file if we don't have the game disks and we need them. That would mean
    making up data, which we will not do."*

    The check fires **before** the folder picker, so a user with no disks is
    not asked to choose a folder and only then told it was pointless. This
    fails without the guard in two ways at once: the picker opens, and the
    box is never shown.
    """
    import editor.window as ew
    from editor.dosimport import NO_DISKS, NO_DISKS_TITLE
    from editor.window import EditorWindow

    said, picked = [], []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append((a[1], a[2])))
    monkeypatch.setattr(ew.QFileDialog, "getExistingDirectory",
                        lambda *a, **k: picked.append(a) or "")
    # An empty folder for the Game directory and nothing in the environment,
    # so nothing on this machine can be found however many disks it has.
    monkeypatch.delenv("POR_DISKS", raising=False)
    monkeypatch.delenv("POR_GAME_DISK", raising=False)
    empty = tmp_path / "no disks here"
    empty.mkdir()
    monkeypatch.chdir(empty)
    window = EditorWindow(backups=str(tmp_path / "backups"),
                          disks=str(empty))
    assert window.import_dos_save() == "no game disks"
    assert said == [(NO_DISKS_TITLE, NO_DISKS)]
    assert picked == [], "the folder picker opened before the refusal"
    window.close()


@needs_disks
def test_with_the_game_disks_there_the_import_gets_as_far_as_the_picker(
        app, tmp_path, monkeypatch):
    """The other direction, which is what stops the refusal being a refusal of
    everything: with the disks configured the import goes on to the folder
    picker, and cancelling it is the only reason it stops."""
    import editor.window as ew
    from editor.window import EditorWindow

    said, picked = [], []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append(a))
    monkeypatch.setattr(ew.QFileDialog, "getExistingDirectory",
                        lambda *a, **k: picked.append(a) or "")
    window = EditorWindow(backups=str(tmp_path / "backups"),
                          disks=str(game_disk().parent))
    assert window.import_dos_save() == "cancelled"
    assert said == []
    assert len(picked) == 1
    window.close()


@needs_disks
def test_the_game_files_an_import_needs_are_the_icon_and_animate(app, tmp_path):
    """What `game_files_for_import` actually found, rather than that it found
    something: a 36-byte icon that is not zero and `ANIMATE00`'s own 852."""
    from editor.window import EditorWindow

    window = EditorWindow(backups=str(tmp_path / "backups"),
                          disks=str(game_disk().parent))
    found = window.game_files_for_import()
    assert found is not None
    assert len(found.icon) == 36 and any(found.icon)
    assert len(found.animate) == dos.ANIMATE_SIZE
    window.close()


# --- what reaches the editor -------------------------------------------------

@needs_dos_saves
@needs_disks
def test_the_import_lands_with_no_file_behind_it_and_save_as_writes_it(
        app, tmp_path, dos_save, files, monkeypatch):
    """The converted party is in the window, marked dirty, and there is **no
    path**: the disk was built in memory a moment ago and no file it could
    have come from exists. Save As is what names one, and that is the write.
    """
    import editor.window as ew
    from editor.dosimport import rehearse
    from editor.window import EditorWindow

    window = EditorWindow(backups=str(tmp_path / "backups"))
    note = window.adopt_conversion(rehearse(dos_save, "A", files))

    assert window.dirty                      # unsaved, and the title says so
    assert window.path is None, "an import has no file behind it"
    # Slot order, which the C64 reads back to front: the character DOS lists
    # first is the one the game puts at the head of the marching order, and
    # that is the *highest* slot (#101, `dos.marching_slot`).
    names = [m.name for m in window.party.members if m.name]
    assert names == [c.name for c in dos.read_party(dos_save, "A")][::-1]
    assert "slot A" in note or "A" in note

    out = tmp_path / "NEW.D64"
    monkeypatch.setattr(ew.QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(out), ""))
    window.save_as()
    assert out.exists() and out.stat().st_size == 174848
    window.close()


@needs_dos_saves
@needs_disks
def test_import_dos_save_is_cancellable_without_touching_anything(
        app, tmp_path, dos_save, monkeypatch):
    """A folder picker dismissed is a menu item that did nothing."""
    from editor.window import EditorWindow

    window = EditorWindow(backups=str(tmp_path / "backups"),
                          disks=str(game_disk().parent))
    before = sorted(p.name for p in tmp_path.iterdir())
    assert window.import_dos_save(folder="") == "cancelled"
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    window.close()


@needs_disks
def test_a_folder_with_no_dos_save_says_so(app, tmp_path, monkeypatch):
    """And says it in a box rather than opening an empty conversion window."""
    import editor.window as ew
    from editor.window import EditorWindow

    said = []
    monkeypatch.setattr(ew.QMessageBox, "warning",
                        lambda *a, **k: said.append(a[2]))
    window = EditorWindow(backups=str(tmp_path / "backups"),
                          disks=str(game_disk().parent))
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
