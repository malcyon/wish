"""File > Preferences: one precedence, and a report that says what it found.

Two rules this file obeys, both learned the hard way:

* **No modal dialog, ever.** `WishWindow.show_dialog` is the seam -- the dialog
  is built and inspected, never `exec()`ed. A run that puts a stream of boxes
  in front of whoever started it is a broken run.
* **No game data in the repository.** The folders here are empty files of the
  right *name*, which is all a glob can see, and the one test that needs real
  maps and real item names reads them off the player's own disks through
  `tests/gamedata.py` and skips when there are none.
"""

from __future__ import annotations

import json
import os
import pathlib
from dataclasses import asdict, fields

import pytest
from gamedata import disk_dir, needs_disks

from automap import paths
from automap.config import Settings, clamp_to_screen, restore_geometry
from por import games
from wish import preferences
from wish.preferences import PreferencesDialog, report

CURSE = games.CURSE_OF_THE_AZURE_BONDS


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_disks_env(monkeypatch):
    """$POR_DISKS and $POR_ULTIMATE are the player's, not this file's."""
    for name in ("POR_DISKS", "POR_GAME_DISK", "POR_ULTIMATE",
                 "POR_ULTIMATE_PASSWORD", "WISH_ULTIMATE"):
        monkeypatch.delenv(name, raising=False)
    preferences._scan.cache_clear()


def disks(where, *names):
    """Empty files standing in for disk images."""
    where.mkdir(parents=True, exist_ok=True)
    for name in names:
        (where / name).write_bytes(b"")
    return where


def nowhere(tmp_path, monkeypatch):
    """A machine with no disks anywhere the search looks."""
    empty = tmp_path / "empty-home"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(paths, "_home", lambda: empty)
    monkeypatch.chdir(empty)


def window(app, save=None, **kw):
    """A window with no emulator, no maps and nothing modal."""
    from wish.session import Session
    from wish.window import WishWindow
    win = WishWindow(save, maps={}, session=Session(find=lambda pref=None: None),
                     **kw)
    win.announce = lambda title, text: None
    return win


# --- the precedence rule -----------------------------------------------------

def test_the_flag_beats_the_preference_which_beats_the_environment(
        tmp_path, monkeypatch):
    """One sentence, made observable: the setting is the answer, and a
    command-line option beats it for one run."""
    nowhere(tmp_path, monkeypatch)
    flag = disks(tmp_path / "flag", "POOL1.D64")
    saved = disks(tmp_path / "saved", "POOL1.D64")
    env = disks(tmp_path / "env", "POOL1.D64")
    settings = Settings(disks=str(saved))
    monkeypatch.setenv("POR_DISKS", str(env))

    assert paths.resolve_disks(flag=str(flag), settings=settings) == (
        flag, paths.FLAG)
    assert paths.resolve_disks(settings=settings) == (saved, paths.PREFERENCE)
    assert paths.resolve_disks(settings=Settings()) == (env, paths.ENVIRONMENT)


def test_below_the_environment_come_the_save_and_the_search(tmp_path,
                                                            monkeypatch):
    nowhere(tmp_path, monkeypatch)
    beside = disks(tmp_path / "saves", "POOL1.D64")
    save = beside / "PORSAVE.D64"
    save.write_bytes(b"")
    assert paths.resolve_disks(beside=str(save), settings=Settings()) == (
        beside, paths.BESIDE)

    found = disks(tmp_path / "home" / "c64" / "Pool of Radiance Disks",
                  "POOL1.D64")
    monkeypatch.setattr(paths, "_home", lambda: tmp_path / "home")
    assert paths.resolve_disks(settings=Settings()) == (found, paths.SEARCHED)


def test_with_nothing_anywhere_the_answer_is_nothing_found(tmp_path,
                                                           monkeypatch):
    nowhere(tmp_path, monkeypatch)
    assert paths.resolve_disks(settings=Settings()) == (None, paths.NOWHERE)


def test_a_folder_that_holds_no_disks_is_still_the_answer(tmp_path,
                                                          monkeypatch):
    """Reporting an empty folder as empty beats silently searching elsewhere:
    "it is ignoring what I typed" is the complaint this avoids."""
    nowhere(tmp_path, monkeypatch)
    empty = tmp_path / "typo"
    empty.mkdir()
    where, source = paths.resolve_disks(settings=Settings(disks=str(empty)))
    assert (where, source) == (empty, paths.PREFERENCE)


# --- a folder per title (#22, steps 1 and 3) ---------------------------------
#
# Step 2 -- a row per title in Preferences -- needs a label, which is
# Donald's, and is deliberately not built here.

def test_a_titles_own_folder_wins_over_the_shared_one(tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    shared = disks(tmp_path / "shared", "POOL1.D64")
    curses_own = disks(tmp_path / "curse-only", "CURSE1.D64")
    settings = Settings(disks=str(shared),
                        game_folders={CURSE.key: str(curses_own)})
    assert paths.resolve_disks(settings=settings, game=CURSE) == (
        curses_own, paths.GAME_PREFERENCE)
    # A title with no entry of its own still gets the shared folder.
    assert paths.resolve_disks(settings=settings, game=games.POOL_OF_RADIANCE) == (
        shared, paths.PREFERENCE)


def test_with_no_game_named_the_per_title_folders_are_not_consulted(
        tmp_path, monkeypatch):
    """`resolve_disks` cannot look a title up in `game_folders` when nothing
    says which title is wanted (#21 is that problem, not this one)."""
    nowhere(tmp_path, monkeypatch)
    shared = disks(tmp_path / "shared", "POOL1.D64")
    curses_own = disks(tmp_path / "curse-only", "CURSE1.D64")
    settings = Settings(disks=str(shared),
                        game_folders={CURSE.key: str(curses_own)})
    assert paths.resolve_disks(settings=settings) == (shared, paths.PREFERENCE)


def test_the_report_names_a_titles_own_preference_and_the_shared_one_it_beat(
        tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    shared = disks(tmp_path / "shared", "CURSE1.D64")
    own = disks(tmp_path / "curse-only", "CURSE1.D64")
    settings = Settings(disks=str(shared), game_folders={CURSE.key: str(own)})
    rows = dict(report(settings, game=CURSE))
    assert rows["In use"] == str(own)
    assert rows["Set by"].startswith("this title's own preference")
    assert str(shared) in rows["Set by"]


def test_an_old_settings_file_migrates_its_one_folder_to_the_title_in_it(
        tmp_path, monkeypatch):
    """The one-step migration must not lose anybody's existing setting: the
    shared folder is kept exactly as it was, and gains an entry for whichever
    title turns out to be in it."""
    nowhere(tmp_path, monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    only = disks(tmp_path / "my-curse-disks", "CURSE1.D64", "CURSE2.D64")
    Settings(disks=str(only)).save()
    again = Settings.load()
    assert again.disks == str(only)
    assert again.game_folders == {CURSE.key: str(only)}


def test_a_folder_recognising_nothing_migrates_to_no_title(tmp_path,
                                                           monkeypatch):
    """A folder that is gone, empty, or holds nothing this project recognises
    has no title to key it under -- `disks` is untouched and still the
    fallback `resolve_disks` tries."""
    nowhere(tmp_path, monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    empty = tmp_path / "nothing-here"
    empty.mkdir()
    Settings(disks=str(empty)).save()
    again = Settings.load()
    assert again.disks == str(empty)
    assert again.game_folders == {}


def test_a_file_already_using_game_folders_is_not_migrated_again(tmp_path,
                                                                 monkeypatch):
    """`game_folders` present -- even empty, a player who cleared every entry
    -- is a file this build already wrote, and migration must not overwrite a
    deliberate choice with a fresh guess."""
    nowhere(tmp_path, monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    shelf = disks(tmp_path / "shelf", "CURSE1.D64")
    Settings(disks=str(shelf), game_folders={}).save()
    assert Settings.load().game_folders == {}


# --- the report --------------------------------------------------------------

def test_the_report_names_the_folder_the_source_and_the_titles(tmp_path,
                                                               monkeypatch):
    nowhere(tmp_path, monkeypatch)
    shelf = disks(tmp_path / "Desktop" / "porgame",
                  "POOL1.D64", "POOL2.D64", "POOL3.D64", "CURSE1.D64")
    rows = dict(report(Settings(disks=str(shelf))))
    assert rows["In use"] == str(shelf)
    assert rows["Set by"] == "this preference"
    assert "Pool of Radiance (3 disks)" in rows["Titles"]
    assert "Curse of the Azure Bonds (1 disk)" in rows["Titles"]


def test_the_report_states_each_failure_in_its_own_slot(tmp_path, monkeypatch):
    """The empty answer is more informative than a missing row."""
    nowhere(tmp_path, monkeypatch)
    empty = tmp_path / "nothing here"
    empty.mkdir()
    rows = dict(report(Settings(disks=str(empty))))
    assert "POOL*.D64" in rows["Titles"] and rows["Titles"].startswith("none")
    assert rows["In use"] == str(empty)


def test_the_report_prints_three_lines_and_not_six(tmp_path, monkeypatch):
    """Donald, 2026-08: "remove Maps, Names, and Icons". The map tab and the
    item column already answer those where somebody is looking."""
    nowhere(tmp_path, monkeypatch)
    shelf = disks(tmp_path / "porgame", "POOL1.D64")
    for settings in (Settings(disks=str(shelf)), Settings()):
        assert [name for name, _ in report(settings)] == [
            "In use", "Set by", "Titles"]


def test_the_report_says_when_por_disks_is_set_and_overridden(tmp_path,
                                                              monkeypatch):
    nowhere(tmp_path, monkeypatch)
    saved = disks(tmp_path / "saved", "POOL1.D64")
    monkeypatch.setenv("POR_DISKS", str(tmp_path / "elsewhere"))
    rows = dict(report(Settings(disks=str(saved))))
    assert rows["Set by"].startswith("this preference")
    assert "$POR_DISKS is set and overridden" in rows["Set by"]


def test_a_flag_says_this_run_only_and_names_the_preference_it_beat(
        tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    saved = disks(tmp_path / "saved", "POOL1.D64")
    flag = disks(tmp_path / "third place", "POOL1.D64")
    rows = dict(report(Settings(disks=str(saved)), flag=str(flag)))
    assert rows["In use"] == str(flag)
    assert "this run only" in rows["Set by"]
    assert str(saved) in rows["Set by"]


def test_the_report_of_nowhere_is_three_stated_failures(tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    rows = dict(report(Settings()))
    assert rows["In use"] == "nothing found"
    assert rows["Set by"] == "nothing found"
    assert len(rows) == 3


def test_a_directory_holding_two_titles_reports_the_open_one_s_maps(
        tmp_path, monkeypatch):
    """`game` is threaded through, not defaulted: `GEO15` is Sokol Keep in one
    title and somewhere else in the other."""
    nowhere(tmp_path, monkeypatch)
    shelf = disks(tmp_path / "both", "POOL1.D64", "CURSE1.D64", "CURSE2.D64")
    rows = dict(report(Settings(disks=str(shelf)), game=CURSE))
    assert "Curse of the Azure Bonds (2 disks)" in rows["Titles"]
    assert "Pool of Radiance (1 disk)" in rows["Titles"]


# --- where the backups go ----------------------------------------------------
#
# Two states, and every test below names which one it is pinning. **Automatic**
# is what a fresh config is in: the folder follows whatever save is open.
# **Chosen** is a folder the user typed or picked, which is used for every save
# and which nothing automatic may touch again.


def opens(win, save):
    """What the editor does when a save is loaded, without needing a disk.

    `EditorWindow.load` sets `path` and emits `opened`; a real D64 is the
    player's and this rule has nothing to do with what is inside one.
    """
    save.parent.mkdir(parents=True, exist_ok=True)
    save.write_bytes(b"")
    win.editor.path = pathlib.Path(save)
    win.editor.opened.emit(str(save))


def test_a_fresh_config_has_no_backup_folder_at_all(app, tmp_path, monkeypatch):
    """Blank by default, and blank all the way down to the editor: with
    nowhere to put a copy there is nothing to save over a save with."""
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        assert win.settings.backup_folder == ""
        assert win.settings.backup_folder_chosen is False
        assert win.editor.backup_dir() == ""
        assert PreferencesDialog(win).backups.text() == ""
    finally:
        win.close()


def test_opening_a_save_fills_the_backup_folder_in(app, tmp_path, monkeypatch):
    """Automatic: `backups/` under the folder the save came from."""
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        shelf = tmp_path / "saves"
        opens(win, shelf / "PORSAVE11.D64")
        assert win.settings.backup_folder == str(shelf / "backups")
        assert win.settings.backup_folder_chosen is False
        assert win.editor.backup_dir() == str(shelf / "backups")
        assert PreferencesDialog(win).backups.text() == str(shelf / "backups")
    finally:
        win.close()


def test_a_save_from_another_folder_moves_it_while_it_is_automatic(
        app, tmp_path, monkeypatch):
    """*"Never change it after they've specified it themselves"* -- so before
    that it does keep changing, and this is the case that says so."""
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        opens(win, tmp_path / "first" / "PORSAVE11.D64")
        opens(win, tmp_path / "second" / "PORSAVE12.D64")
        assert win.settings.backup_folder == str(tmp_path / "second" / "backups")
    finally:
        win.close()


def test_a_chosen_folder_is_used_for_a_save_opened_anywhere(
        app, tmp_path, monkeypatch):
    """Chosen: fixed, and nothing automatic may move it again."""
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        mine = tmp_path / "my backups"
        PreferencesDialog(win).set_backup_folder(str(mine))
        assert win.settings.backup_folder_chosen is True
        opens(win, tmp_path / "somewhere" / "PORSAVE11.D64")
        opens(win, tmp_path / "elsewhere" / "PORSAVE12.D64")
        assert win.settings.backup_folder == str(mine)
        assert win.editor.backup_dir() == str(mine)
    finally:
        win.close()


def test_clearing_it_goes_back_to_following_the_save(app, tmp_path, monkeypatch):
    """A setting a user cannot undo is a trap, so clearing the box is the way
    back to automatic -- and it fills in again from the save that is open."""
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        shelf = tmp_path / "saves"
        opens(win, shelf / "PORSAVE11.D64")
        dialog = PreferencesDialog(win)
        dialog.set_backup_folder(str(tmp_path / "my backups"))
        dialog.set_backup_folder("")
        assert win.settings.backup_folder_chosen is False
        assert win.settings.backup_folder == str(shelf / "backups")
    finally:
        win.close()


def test_a_chosen_folder_survives_a_restart(app, tmp_path, monkeypatch):
    """Both halves of the state are in the file, or the next run would take a
    folder somebody chose for a folder it may move."""
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        PreferencesDialog(win).set_backup_folder(str(tmp_path / "my backups"))
    finally:
        win.close()
    again = Settings.load()
    assert again.backup_folder == str(tmp_path / "my backups")
    assert again.backup_folder_chosen is True


# --- the remembered `File > Open` folder (#66, steps 1 and 4) ---------------
#
# Steps 2 and 3 -- a Preferences row for this, and the preference winning over
# it -- need a label, which is Donald's to word, and are deliberately not
# built here.

def test_the_open_folder_is_remembered_and_used_with_nothing_open(tmp_path):
    from editor import files

    remembered = tmp_path / "saves" / "party one"
    remembered.mkdir(parents=True)
    assert files.open_start_dir(str(remembered), None) == str(remembered)
    assert files.open_start_dir("", None) == ""


def test_the_currently_open_save_still_wins_over_the_remembered_folder(
        tmp_path):
    """Unchanged from before this remembered anything: beside the save that
    is already open, not wherever the one before it was."""
    from editor import files

    remembered = tmp_path / "old-party"
    remembered.mkdir()
    current = tmp_path / "new-party" / "PORSAVE11.D64"
    assert (files.open_start_dir(str(remembered), str(current))
            == str(current.parent))


def test_a_remembered_folder_that_no_longer_exists_falls_back_to_nothing(
        tmp_path):
    """A remembered path always eventually hits one that moved or was deleted
    (#66 step 4) -- the dialog is left to decide for itself, same as a fresh
    config with nothing remembered yet."""
    from editor import files

    gone = tmp_path / "moved-away"
    assert not gone.exists()
    assert files.open_start_dir(str(gone), None) == ""


def test_the_remembered_folder_is_a_setting_and_survives_a_restart(
        tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings = Settings()
    assert settings.last_save_folder == ""
    settings.last_save_folder = str(tmp_path / "saves")
    settings.save()
    assert Settings.load().last_save_folder == str(tmp_path / "saves")


def test_asking_where_the_backups_go_creates_nothing(app, tmp_path,
                                                     monkeypatch):
    """A dialog that only reports must not write to the folder somebody keeps
    their disks in. The folder is made when there is a copy to put in it."""
    nowhere(tmp_path, monkeypatch)
    shelf = tmp_path / "disks"
    save = shelf / "PORSAVE14.D64"
    win = window(app)
    try:
        opens(win, save)
        PreferencesDialog(win)
    finally:
        win.close()
    assert list(shelf.iterdir()) == [save]


def test_the_backups_note_names_the_state_and_nothing_else(
        app, tmp_path, monkeypatch):
    """The path in a box you can edit, and a note naming the state it is in.

    The path alone cannot say: `/somewhere/backups` looks the same whether it
    is following the open save or was typed in and is never moving again.
    """
    from editor import files
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        blank = PreferencesDialog(win).backups_note.text()
        opens(win, tmp_path / "saves" / "PORSAVE11.D64")
        following = PreferencesDialog(win).backups_note.text()
        PreferencesDialog(win).set_backup_folder(str(tmp_path / "mine"))
        chosen = PreferencesDialog(win).backups_note.text()
    finally:
        win.close()
    # Blank says nothing about itself -- Donald removed that sentence: an empty
    # box with no save open explains itself. The standing facts stay.
    assert "no saving" not in blank.lower()
    assert "open a save" not in blank.lower()
    assert following == ""            # Donald removed this one too
    assert "yours" in chosen.lower()
    # The standing facts went too -- Donald removed them. The note names the
    # state and nothing else, and blank names nothing at all.
    for note in (blank, following, chosen):
        assert "only when something changed" not in note.lower()
        assert str(files.KEEP_BACKUPS) not in note
    assert blank == ""


def test_the_folder_box_is_wide_enough_to_read_its_own_placeholder(
        app, tmp_path, monkeypatch):
    """Donald: you can't read the helptext written in the Folder edit box.

    It was 137 px wide with 203 px of placeholder in it. The width is measured
    off the text, so this asserts the rule and not the number -- a longer
    sentence or a wider font moves both sides of it.
    """
    from wish.preferences import room_for
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        box = dialog.folder
        placeholder = box.placeholderText()
        assert box.minimumWidth() >= box.fontMetrics().horizontalAdvance(
            placeholder)
        # And the dialog is at least that wide, since it is what widened it.
        assert dialog.sizeHint().width() >= box.minimumWidth()
        # Measured, not chosen: more text needs more room.
        assert room_for(box, placeholder + " and then some") > room_for(
            box, placeholder)
    finally:
        win.close()


# --- the dialog --------------------------------------------------------------

def test_the_dialog_is_on_the_file_menu_with_a_shortcut_a_keyboard_has(
        app, tmp_path, monkeypatch):
    """`QKeySequence.StandardKey.Preferences` is the `XF86Settings` multimedia
    key on this build, which no ordinary keyboard produces."""
    from PyQt6.QtGui import QKeySequence
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    assert win.preferences_action.shortcut() == QKeySequence("Ctrl+,")
    assert win.preferences_action.shortcut() != QKeySequence(
        QKeySequence.StandardKey.Preferences)
    assert "&Preferences…" in menu_texts(win)


def menu_texts(win) -> list[str]:
    return [a.text() for m in win.menuBar().actions()
            for a in (m.menu().actions() if m.menu() else [])]


def test_opening_it_goes_through_a_seam_a_test_can_hold(app, tmp_path,
                                                        monkeypatch):
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    shown = []
    win.show_dialog = shown.append
    dialog = win.preferences()
    assert shown == [dialog]
    assert isinstance(dialog, PreferencesDialog)


def test_changing_the_folder_updates_the_report_with_no_ok_pressed(
        app, tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    dialog = PreferencesDialog(win)
    assert dict(rows(dialog))["In use"] == "nothing found"

    shelf = disks(tmp_path / "Desktop" / "porgame", "POOL1.D64", "POOL2.D64")
    dialog.set_folder(str(shelf))
    printed = dict(rows(dialog))
    assert printed["In use"] == str(shelf)
    assert printed["Set by"] == "this preference"
    assert "Pool of Radiance (2 disks)" in printed["Titles"]
    assert Settings.load().disks == str(shelf)


def rows(dialog) -> list[tuple[str, str]]:
    return [(name, label.text()) for name, label in dialog.report_rows.items()]


def test_clearing_the_folder_goes_back_to_searching(app, tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    shelf = disks(tmp_path / "porgame", "POOL1.D64")
    win = window(app)
    dialog = PreferencesDialog(win)
    dialog.set_folder(str(shelf))
    dialog.set_folder("")
    assert Settings.load().disks == ""
    assert dict(rows(dialog))["Set by"] == "nothing found"


def test_the_backend_radios_are_the_menu_s_actions_and_still_act(
        app, tmp_path, monkeypatch):
    """The View > Backend group moved across whole. One model underneath, so
    the preference, the session and the dialog cannot disagree."""
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    dialog = PreferencesDialog(win)
    assert set(dialog.radios) == set(win.backend_actions)
    dialog.radios["Ultimate"].click()
    assert win.settings.backend == "Ultimate"
    assert Settings.load().backend == "Ultimate"
    assert win.session._preferred == "Ultimate"
    assert win.backend_actions["Ultimate"].isChecked()


def test_an_unverified_backend_still_says_so_in_the_dialog(app, tmp_path,
                                                           monkeypatch):
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    dialog = PreferencesDialog(win)
    dialog.refresh()
    # In the badges beside the label now, not run into the label itself.
    assert dialog.radios["Ultimate"].text() == "Ultimate"
    assert dialog.badges["Ultimate"].text() == "not answering"
    assert dialog.unverified["Ultimate"].isVisibleTo(dialog)
    assert dialog.unverified["VICE"].isVisibleTo(dialog) is False


def test_the_view_menu_no_longer_carries_a_backend_submenu(app, tmp_path,
                                                           monkeypatch):
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    assert "&Backend" not in menu_texts(win)


# --- the Ultimate ------------------------------------------------------------

def test_the_ultimate_host_round_trips_and_reaches_the_backend(app, tmp_path,
                                                               monkeypatch):
    from wish import ultimate
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    dialog = PreferencesDialog(win)
    dialog.host.setText("ultimate64.local:8080")
    dialog._host_changed()
    assert Settings.load().ultimate_host == "ultimate64.local:8080"
    assert ultimate.configured() == ("ultimate64.local", 8080)

    dialog.host.setText("")
    dialog._host_changed()
    assert Settings.load().ultimate_host == ""
    assert ultimate.configured() is None


def test_no_password_is_ever_written_to_the_settings_file(app, tmp_path,
                                                          monkeypatch):
    """The settings file is documented as one you can read and hand-edit. A
    secret does not belong in a file described that way."""
    monkeypatch.setenv("POR_ULTIMATE_PASSWORD", "hunter2")
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    dialog = PreferencesDialog(win)
    dialog.host.setText("ultimate64.local")
    dialog._host_changed()
    dialog.refresh()

    assert "set" in dialog.password.text()
    assert "hunter2" not in dialog.password.text()
    assert not [f for f in fields(Settings) if "password" in f.name.lower()]
    assert "password" not in json.dumps(asdict(win.settings)).lower()
    written = (tmp_path / "wish" / "automap.json").read_text()
    assert "hunter2" not in written and "password" not in written.lower()


# --- the poll interval -------------------------------------------------------

def test_the_backend_default_checkbox_owns_the_poll_interval(
        app, tmp_path, monkeypatch):
    """Donald: the spin box printed a sentence at its lowest value and turned
    into milliseconds the moment an arrow was touched. The state is a checkbox
    now, the spin box only ever shows a number, and 0 is still how "the backend
    decides" is stored."""
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    dialog = PreferencesDialog(win)

    assert dialog.interval_default.isChecked()      # on by default
    assert not dialog.interval.isEnabled()          # and the number is disabled
    assert Settings.load().interval_ms == 0

    dialog.interval_default.setChecked(False)
    assert dialog.interval.isEnabled()
    dialog.interval.setValue(750)
    assert Settings.load().interval_ms == 750
    assert win.session._interval_override == 750

    dialog.interval_default.setChecked(True)
    assert not dialog.interval.isEnabled()
    assert Settings.load().interval_ms == 0
    assert win.session._interval_override is None

    # and it comes back ticked, with the box still disabled
    assert PreferencesDialog(win).interval_default.isChecked()


# --- fast travel -------------------------------------------------------------

def ticked(dialog):
    """The names with a tick against them, in table order."""
    from PyQt6.QtCore import Qt
    return [dialog.travel_table.item(i, 0).text()
            for i in range(dialog.travel_table.rowCount())
            if dialog.travel_table.item(i, 0).checkState()
            == Qt.CheckState.Checked]


def tick(dialog, name, on=True):
    from PyQt6.QtCore import Qt
    for i in range(dialog.travel_table.rowCount()):
        item = dialog.travel_table.item(i, 0)
        if item.text() == name:
            item.setCheckState(Qt.CheckState.Checked if on
                               else Qt.CheckState.Unchecked)
            return
    raise AssertionError(f"no row named {name}")


def test_a_fresh_config_ticks_the_three_areas_and_nothing_else(app, tmp_path,
                                                               monkeypatch):
    """Donald's three: New Phlan, The Slums, Sokol Keep. The visited-areas
    filter this replaces was inferred from our own map files, and a party
    walks wherever it likes while the map window is shut."""
    nowhere(tmp_path, monkeypatch)
    dialog = PreferencesDialog(window(app))
    assert ticked(dialog) == ["New Phlan", "Sokol Keep", "The Slums"]
    assert "3 areas" in dialog.travel_note.text()


def test_area_30_is_not_in_the_table_at_all(app, tmp_path, monkeypatch):
    """`ECL1E` is the attract-mode demo and entering it ends the session. It
    is `Area.warpable` that says so, not an id written down twice."""
    from por import areas

    nowhere(tmp_path, monkeypatch)
    dialog = PreferencesDialog(window(app))
    assert [a.id for a in dialog.travel_rows if not a.warpable] == []
    assert 30 not in [a.id for a in dialog.travel_rows]
    assert dialog.travel_table.rowCount() == len(
        [a for a in areas.AREAS if a.warpable])


def test_ticking_an_area_reaches_the_dropdown_and_the_settings_file(
        app, tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    dialog = PreferencesDialog(win)
    tick(dialog, "The Kobold Caves")
    assert 13 in Settings.load().chosen_areas()
    assert "The Kobold Caves" in [r.name for r in win.map.warp_bar.rows]

    tick(dialog, "Sokol Keep", on=False)
    assert 21 not in Settings.load().chosen_areas()
    assert "Sokol Keep" not in [r.name for r in win.map.warp_bar.rows]


def test_unticking_everything_is_an_answer_and_is_kept(app, tmp_path,
                                                       monkeypatch):
    """An empty dropdown is then the player's own choice, and the empty list
    survives a reload where the defaults would have come back.

    The note under the table is a count and no more. It explained itself --
    "Nothing ticked, so the Fast Travel list is empty" -- until Donald had that
    out in 2026-08: "the user will figure it out", and the dropdown's own
    disabled item says it where somebody is looking for it."""
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    dialog = PreferencesDialog(win)
    for name in list(ticked(dialog)):
        tick(dialog, name, on=False)
    assert ticked(dialog) == []
    assert Settings.load().fast_travel_targets == {"pool-of-radiance": []}
    assert Settings.load().chosen_areas() == ()
    assert dialog.travel_note.text() == "0 areas in the Fast Travel list."
    assert win.map.warp_bar.rows == ()


def test_a_saved_choice_is_what_the_next_window_opens_with(app, tmp_path,
                                                           monkeypatch):
    nowhere(tmp_path, monkeypatch)
    PreferencesDialog(window(app))          # writes nothing on its own
    assert Settings.load().fast_travel_targets is None

    tick(PreferencesDialog(window(app)), "Kovel Mansion")
    later = window(app, settings=Settings.load())
    assert "Kovel Mansion" in [r.name for r in later.map.warp_bar.rows]
    assert ticked(PreferencesDialog(later)) == [
        "Kovel Mansion", "New Phlan", "Sokol Keep", "The Slums"]


def test_a_title_with_no_area_table_gets_an_empty_table_and_a_sentence(
        app, tmp_path, monkeypatch):
    """#14. Ticking Pool of Radiance's thirty areas for a Curse session would
    file Pool of Radiance's ids under Curse's key, and the dropdown would then
    offer them. The table is the map's title's, and five of the six titles have
    none -- `docs/138-multiple-games.md` §7 task 1."""
    nowhere(tmp_path, monkeypatch)
    win = window(app, title=games.CURSE_OF_THE_AZURE_BONDS.title)
    dialog = PreferencesDialog(win)
    assert dialog.travel_rows == []
    assert dialog.travel_table.rowCount() == 0
    assert dialog.travel_note.text() == ("No areas are known for Curse of the "
                                         "Azure Bonds.")
    assert win.map.warp_bar.rows == ()


def test_the_warning_is_a_framed_box_in_the_same_amber_as_unverified(
        app, tmp_path, monkeypatch):
    """Donald's wording, unedited, and a box rather than a tooltip: it is the
    one thing in this section somebody has to read before they use it."""
    from PyQt6.QtWidgets import QLabel

    nowhere(tmp_path, monkeypatch)
    dialog = PreferencesDialog(window(app))
    boxes = [w for w in dialog.findChildren(QLabel)
             if w.text() == ("Fast travel to areas you haven't been to is "
                             "dangerous and can break the game.")]
    assert len(boxes) == 1
    style = boxes[0].styleSheet()
    assert style.startswith(preferences.UNVERIFIED)   # the same amber, framed
    assert "border" in style and boxes[0].wordWrap()


def written_config(tmp_path) -> dict:
    return json.loads((tmp_path / "wish" / "automap.json").read_text())


def test_a_config_file_written_before_the_rename_keeps_its_ticks(app, tmp_path,
                                                                  monkeypatch):
    """It was `warp_areas` until 2026-08 -- Donald: "since we aren't calling it
    warp_to anymore. We need consistency in our naming." His own file has the
    old key in it, so the old key is read; only the new one is written, so the
    rename finishes instead of being carried in the file forever."""
    nowhere(tmp_path, monkeypatch)
    (tmp_path / "wish").mkdir(parents=True, exist_ok=True)
    (tmp_path / "wish" / "automap.json").write_text(
        json.dumps({"warp_areas": [13, 21], "sight": 4}))

    old = Settings.load()
    # Two migrations in one read: the key rename, and then the bare list into
    # the per-title dict. A file from before 2026-08 takes both.
    assert old.fast_travel_targets == {"pool-of-radiance": [13, 21]}
    assert old.chosen_areas() == (13, 21)

    old.save()
    assert written_config(tmp_path)["fast_travel_targets"] == {
        "pool-of-radiance": [13, 21]}
    assert "warp_areas" not in written_config(tmp_path)


def test_the_new_key_wins_and_an_empty_old_list_is_still_a_choice(app, tmp_path,
                                                                  monkeypatch):
    nowhere(tmp_path, monkeypatch)
    (tmp_path / "wish").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "wish" / "automap.json"

    path.write_text(json.dumps({"warp_areas": [1], "fast_travel_targets": [2]}))
    assert Settings.load().chosen_areas() == (2,)

    path.write_text(json.dumps({"warp_areas": []}))
    assert Settings.load().fast_travel_targets == {"pool-of-radiance": []}
    assert Settings.load().chosen_areas() == ()      # not the default three


def test_a_config_already_keyed_by_title_is_read_as_it_stands(app, tmp_path,
                                                              monkeypatch):
    """The third shape: a file this build wrote. No migration, and a title
    nobody has ticked for keeps its own default rather than borrowing Pool of
    Radiance's."""
    nowhere(tmp_path, monkeypatch)
    (tmp_path / "wish").mkdir(parents=True, exist_ok=True)
    (tmp_path / "wish" / "automap.json").write_text(json.dumps(
        {"fast_travel_targets": {"pool-of-radiance": [13],
                                 "curse-of-the-azure-bonds": []}}))

    kept = Settings.load()
    assert kept.chosen_areas(games.POOL_OF_RADIANCE) == (13,)
    assert kept.chosen_areas(games.CURSE_OF_THE_AZURE_BONDS) == ()
    assert kept.chosen_areas(games.SECRET_OF_THE_SILVER_BLADES) == ()
    kept.save()
    assert written_config(tmp_path)["fast_travel_targets"] == {
        "pool-of-radiance": [13], "curse-of-the-azure-bonds": []}


# --- how big the dialog opens ------------------------------------------------

def test_every_control_is_wide_enough_for_what_it_has_to_show(app, tmp_path,
                                                               monkeypatch):
    """Donald: "A lot of fields are squished and unusable."

    Each number is asked of the style and the font, never written down, and the
    dialog is at least the widest of them.
    """
    from wish.preferences import room_for
    nowhere(tmp_path, monkeypatch)
    dialog = PreferencesDialog(window(app))
    needed = {
        "folder": room_for(dialog.folder, dialog.folder.placeholderText()),
        "host": room_for(dialog.host, dialog.host.placeholderText()),
        "interval": dialog.interval.minimumSizeHint().width(),
        "areas": dialog.travel_table.sizeHintForColumn(0),
    }
    assert dialog.folder.minimumWidth() >= needed["folder"]
    assert dialog.host.minimumWidth() >= needed["host"]
    assert dialog.travel_table.minimumWidth() >= needed["areas"]
    assert dialog.sizeHint().width() >= max(needed.values())
    assert dialog.width() >= max(needed.values())


def test_two_tabs_and_it_opens_on_general_every_time(app, tmp_path,
                                                      monkeypatch):
    """Donald: "What about tabs across the top? Can we have a General tab and
    a Fast Travel tab?" Nothing about which one was open is remembered -- a
    dialog reopening on a tab nobody chose is worse than one that forgets."""
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    dialog = PreferencesDialog(win)
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
        "General", "Fast travel"]
    assert dialog.tabs.currentIndex() == 0
    # The warning belongs beside the thing it warns about.
    travel = dialog.tabs.widget(1)
    assert travel.isAncestorOf(dialog.travel_table)
    assert not dialog.tabs.widget(0).isAncestorOf(dialog.travel_table)
    assert [w for w in travel.findChildren(type(dialog.travel_note))
            if w.text().startswith("Fast travel to areas")]
    assert not [f for f in fields(Settings) if "tab" in f.name.lower()]

    dialog.tabs.setCurrentIndex(1)
    assert PreferencesDialog(win).tabs.currentIndex() == 0


def test_it_opens_inside_the_work_area_with_nothing_squeezed(app, tmp_path,
                                                              monkeypatch):
    """cosmic-comp caps a window at 1280 x 662 (§12). A dialog handed less
    height than its layout's minimum does not refuse -- it squeezes what can be
    squeezed, and the Ultimate host box and the poll spinner went to nine
    pixels tall. Neither tab scrolls at the size it opens; the area table
    scrolls inside itself, which is what a table does."""
    nowhere(tmp_path, monkeypatch)
    dialog = PreferencesDialog(window(app))
    assert dialog.width() <= 1280 and dialog.height() <= 662
    dialog.show()
    try:
        assert dialog.host.height() >= dialog.host.sizeHint().height()
        assert dialog.interval.height() >= dialog.interval.sizeHint().height()
        assert dialog.folder.height() >= dialog.folder.sizeHint().height()
        # Given the height it asks for, General does not scroll. Asserted this
        # way round because the dialog caps itself to the screen: CI's offscreen
        # screen is smaller than Donald's, so a bare `maximum() == 0` failed
        # there by 40 px on Linux and 4 on Windows while being true on his
        # desktop. What matters is that the content fits when there is room --
        # the squeeze assertions above are what pin the small-screen case.
        dialog.resize(dialog.width(), 2000)
        app.processEvents()
        bar = dialog._general_scroll.verticalScrollBar()
        assert bar.maximum() == 0
        assert not dialog._general_scroll.horizontalScrollBar().isVisible()
        # The table takes the tab, which was the point of splitting it: it was
        # capped at 160 px in one column and shows three times as much now.
        dialog.tabs.setCurrentIndex(1)
        assert dialog.travel_table.height() > 400
    finally:
        dialog.close()


# --- the debug log -----------------------------------------------------------

def test_the_debug_log_is_in_the_dialog_and_survives_a_restart(
        app, tmp_path, monkeypatch):
    """Donald reversed "off at every start". The mitigation is that it says so
    -- see the next test -- not that it is forgotten."""
    import wish.debuglog as debuglog
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    dialog = PreferencesDialog(win)
    try:
        dialog.logging.setChecked(True)
        assert debuglog.is_on()
        assert Settings.load().diagnostics is True

        again = window(app, settings=Settings.load())
        try:
            assert again.debug_action.isChecked()
            assert debuglog.is_on()
        finally:
            again.debug_action.setChecked(False)
            again.close()
    finally:
        win.debug_action.setChecked(False)
        win.close()
    assert Settings.load().diagnostics is False


def test_while_it_is_on_the_window_says_so_without_being_asked(app, tmp_path,
                                                               monkeypatch):
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        assert win.log_flag.isVisibleTo(win.statusBar()) is False
        assert "[logging]" not in win.windowTitle()
        win.debug_action.setChecked(True)
        assert "[logging]" in win.windowTitle()
        assert win.log_flag.isVisibleTo(win.statusBar())
        win.debug_action.setChecked(False)
        assert "[logging]" not in win.windowTitle()
    finally:
        win.debug_action.setChecked(False)
        win.close()


def test_show_log_is_still_on_the_view_menu(app, tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    assert "Sho&w log" in menu_texts(win)
    assert "&Debug log" not in menu_texts(win)   # it lives in Preferences now


# --- window geometry ---------------------------------------------------------

def test_the_window_remembers_its_size_and_opens_at_it(app, tmp_path,
                                                       monkeypatch):
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    win.resize(701, 503)
    win.close()                       # closeEvent is what remembers
    saved = Settings.load()
    assert saved.geometry
    assert (saved.window_width, saved.window_height) == (701, 503)

    again = window(app)
    restore_geometry(again, saved)
    assert (again.width(), again.height()) == (701, 503)
    again.close()


def test_the_size_the_compositor_forces_does_not_become_the_memory(
        app, tmp_path, monkeypatch):
    """The loop Donald walks: size it, close it, open it again.

    On his desktop cosmic-comp answers the first `show()` with a size of its
    own -- a bare `QMainWindow` asking for 1875x1030 comes up 1280x662 -- and
    Qt takes it. So what closing wrote back was the compositor's idea and the
    size he had chosen was gone, every time. The compositor is played here by a
    plain `resize`, because the offscreen platform never sends one, and the
    window is laid out without going on anybody's screen.
    """
    from PyQt6.QtCore import QRect, Qt

    from automap.config import hold_geometry

    nowhere(tmp_path, monkeypatch)
    space = QRect(0, 0, 1920, 1032)
    win = window(app)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.show()
    # Measured off the window, not written down: the layout will not go under
    # its own minimum, and that minimum is a different number under every
    # theme and font.
    floor = win.minimumSizeHint()
    wanted = (floor.width() + 200, floor.height() + 100)
    win.resize(*wanted)
    hold_geometry(win, space=space)
    win.resize(floor.width() + 20, floor.height() + 10)     # the configure
    win.close()                       # closeEvent is what remembers

    # What the next run opens at. Reading it back through `restore_geometry`
    # is the test above; the offscreen screen is 800x800 and Qt's own
    # `restoreGeometry` cuts a shown window's size down to it, which is why
    # this one stops at what was written.
    saved = Settings.load()
    assert (saved.window_width, saved.window_height) == wanted
    assert saved.geometry


def test_a_geometry_bigger_than_the_screen_is_cut_down_to_it(app, tmp_path,
                                                             monkeypatch):
    """A window restored from a monitor that is no longer attached must not
    open larger than the display it lands on."""
    from PyQt6.QtGui import QGuiApplication
    nowhere(tmp_path, monkeypatch)
    space = QGuiApplication.primaryScreen().availableGeometry()
    win = window(app)
    win.resize(space.width() * 3, space.height() * 3)
    clamp_to_screen(win)
    assert win.width() <= space.width() and win.height() <= space.height()
    win.close()


def test_a_window_placed_off_the_edge_is_brought_back_on(app, tmp_path,
                                                         monkeypatch):
    from PyQt6.QtGui import QGuiApplication
    nowhere(tmp_path, monkeypatch)
    space = QGuiApplication.primaryScreen().availableGeometry()
    win = window(app)
    win.resize(300, 200)
    win.move(space.right() + 4000, space.bottom() + 4000)
    clamp_to_screen(win)
    assert space.contains(win.frameGeometry())
    win.close()


def test_settings_from_before_this_still_give_a_size(app, tmp_path,
                                                     monkeypatch):
    """Nobody loses their window: with no `geometry` the remembered width and
    height are used, and a floor raises a small one for the merged window.

    The sizes are deliberately small. `restore_geometry` clamps to the screen,
    and the offscreen platform's screen is 800x800 here and on CI -- asserting
    a 900-wide window measured 800 and failed everywhere but the machine it was
    written on.
    """
    nowhere(tmp_path, monkeypatch)
    old = Settings(window_width=420, window_height=300)
    win = window(app)
    assert restore_geometry(win, old) is False
    assert (win.width(), win.height()) == (420, 300)
    restore_geometry(win, old, floor=(500, 380))
    assert (win.width(), win.height()) == (500, 380)
    win.close()


# --- the acceptance case -----------------------------------------------------

def test_the_empty_map_tab_says_where_to_go(app, tmp_path, monkeypatch):
    """The failure this whole dialog exists for used to be reported to a
    stderr that a desktop launcher throws away."""
    from automap.window import NO_MAPS
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    assert win.map.no_maps is True
    assert NO_MAPS in win.map.waiting_text()
    assert "File > Preferences" in win.map.waiting_text()
    win.close()


@needs_disks
def test_one_folder_gets_item_names_and_a_map_without_a_restart(
        app, tmp_path, monkeypatch):
    """The whole point, end to end: disks somewhere no search covers, nothing
    typed in a terminal, one folder set in the dialog.

    The folder is symlinks to the player's own disks -- a real, non-obvious
    location, and not one byte of the game in this repository.
    """
    nowhere(tmp_path, monkeypatch)
    real = disk_dir()
    shelf = tmp_path / "Desktop" / "porgame"
    shelf.mkdir(parents=True)
    for image in sorted(real.glob("POOL*.[dD]64")):
        (shelf / image.name).symlink_to(image)

    win = window(app)
    try:
        assert win.disks is None                     # nothing found, as staged
        assert win.editor.item_names == {}
        assert win.map.no_maps is True

        dialog = PreferencesDialog(win)
        dialog.set_folder(str(shelf))

        printed = dict(rows(dialog))
        assert printed["Set by"] == "this preference"
        assert "Pool of Radiance" in printed["Titles"]
        assert win.editor.item_names, "item names arrive without a restart"
        assert win.map.no_maps is False
        assert win.mapper._maps

        # And it is still true after a restart, with nothing in the terminal.
        again = window(app, settings=Settings.load())
        assert str(again.disks) == str(shelf)
        assert again.editor.disks == str(shelf)
        again.close()
    finally:
        win.close()


@needs_disks
def test_the_editor_takes_the_folder_as_a_parameter_and_imports_nothing(
        app, tmp_path, monkeypatch):
    """`tests/test_wish.py::test_editor_imports_nothing_live` is the rule; this
    is the mechanism that keeps it true -- the folder arrives as an argument."""
    from editor.window import EditorWindow
    nowhere(tmp_path, monkeypatch)
    editor = EditorWindow()
    editor.set_disks(str(disk_dir()))
    assert editor.item_names
    assert editor.game_disk_found
    assert os.path.dirname(editor.game_disk_found) == str(disk_dir())
