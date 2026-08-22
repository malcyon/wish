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

def test_a_backup_goes_beside_the_save_disk(tmp_path):
    """Donald: "no user is ever going to think to look there" -- and mostly
    they do not have to, because the copy lands beside the disk."""
    from wish.preferences import backup_folder
    save = tmp_path / "PORSAVE14.D64"
    save.write_bytes(b"")
    where, fallback = backup_folder(save)
    assert (where, fallback) == (tmp_path / "backups", False)


@pytest.mark.skipif(os.name == "nt", reason="chmod does not make a directory "
                    "unwritable on Windows -- it toggles the read-only "
                    "attribute, which is meaningless for a directory, and "
                    "os.access(dir, W_OK) answers True anyway")
@pytest.mark.skipif(getattr(os, "geteuid", lambda: 1)() == 0,
                    reason="root ignores the permission bits")
def test_an_unwritable_folder_falls_back_to_the_user_data_directory(tmp_path):
    from editor import files
    from wish.preferences import backup_folder
    shelf = tmp_path / "read only"
    shelf.mkdir()
    save = shelf / "PORSAVE14.D64"
    save.write_bytes(b"")
    shelf.chmod(0o555)
    try:
        where, fallback = backup_folder(save)
    finally:
        shelf.chmod(0o755)
    assert (where, fallback) == (files.fallback_dir(), True)


def test_a_folder_that_is_not_there_falls_back(tmp_path):
    """The same branch as the test above, on every platform and as root: a
    folder that does not exist cannot be written to by anybody."""
    from editor import files
    from wish.preferences import backup_folder
    save = tmp_path / "gone" / "PORSAVE14.D64"      # never created
    assert backup_folder(save) == (files.fallback_dir(), True)


def test_with_nothing_open_the_fallback_is_named_and_called_one(tmp_path):
    from editor import files
    from wish.preferences import backup_folder
    assert backup_folder(None) == (files.fallback_dir(), True)


def test_asking_where_the_backups_go_creates_nothing(app, tmp_path,
                                                     monkeypatch):
    """`editor.files.backup_dir_for` answers by *making* the folder and
    touching a probe file in it. A dialog that only reports must not write to
    the folder somebody keeps their disks in."""
    from wish.preferences import backup_folder
    nowhere(tmp_path, monkeypatch)
    shelf = tmp_path / "disks"
    shelf.mkdir()
    save = shelf / "PORSAVE14.D64"
    save.write_bytes(b"")
    backup_folder(save)
    win = window(app)
    try:
        PreferencesDialog(win)
    finally:
        win.close()
    assert list(shelf.iterdir()) == [save]


def test_the_dialog_says_where_backups_go_and_the_two_standing_facts(
        app, tmp_path, monkeypatch):
    """The path, which of the two folders it is as a badge, and the facts.

    Donald asked for "the same effect" the backend states got, so the answer to
    *which folder is this* is a badge beside the path rather than a clause in
    the middle of a sentence with two other things in it.
    """
    from editor import files
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        said, badge = dialog.backups.text(), dialog.backups_badge
        note = dialog.backups_note.text()
    finally:
        win.close()
    assert said == str(files.fallback_dir())
    assert badge.text() == "fallback"
    assert "border" in badge.styleSheet()      # framed, like the backends
    assert "only when something changed" in note.lower()
    assert str(files.KEEP_BACKUPS) in note


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

def test_the_poll_interval_is_remembered_and_zero_means_the_backend_s_own(
        app, tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    dialog = PreferencesDialog(win)
    dialog.interval.setValue(750)
    assert Settings.load().interval_ms == 750
    assert win.session._interval_override == 750
    dialog.interval.setValue(0)
    assert Settings.load().interval_ms == 0
    assert win.session._interval_override is None


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
