"""The tabbed window: the character editor and the live map, in one place.

Both tabs are the windows that already existed, unchanged in what they do. They
are `QMainWindow`s used as pages, which Qt allows and which is what keeps this
file thin: the editor's form, bindings and losslessness rules are untouched, and
the map still paints exactly what `render.py` gives it.

What the outer window adds is the three things a merged application owes you:

* **one connection.** `wish/session.py` owns it, because VICE serves exactly one
  binary-monitor connection and ignores the second in silence.
* **one status bar**, answering "what am I looking at" -- the file on the editor
  tab, the connection and the party's square on the map tab.
* **one title**, carrying the open save and a dirty marker whichever tab shows.

The editor tab is never handed the target. That is the project's first decision
made structural (`docs/README.md`): `editor/` imports nothing from `automap/`, and the
file path works with no emulator anywhere.
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
)

from automap import paths
from automap.config import (
    Settings,
    clamp_to_screen,
    hold_geometry,
    remember_geometry,
    restore_geometry,
)
from automap.state import Automapper
from automap.window import AutomapBinding
from editor.window import EditorBinding, RowSplitter
from goldbox import games
from ui.appicon import app_icon

from . import backends, debuglog, debugmode, licenses, nativewatch
from .about import install as install_help
from .preferences import (
    SHORTCUT,
    PreferencesDialog,
    apply_ultimate_host,
    backup_folder,
    chosen_backup_folder,
    game_named,
)
from .session import BUSY, CONNECTED, Session
from .ui_window import Ui_WishWindow

# The map is what a player has open while playing; the editor is the
# occasional visit. Index order is tab order, so the map is first.
MAP_TAB, EDITOR_TAB = 0, 1

#: No preference: `backends.find` takes whichever answers first. The ordinary
#: case, and what an empty `Settings.backend` means.
ANY_BACKEND = ""


def load_maps(disks: str | None = None) -> dict:
    """Every GEO off the game disks, or nothing if they cannot be found."""
    return load_maps_titled(disks)[0]


def load_maps_titled(disks: str | None = None, game=None) -> tuple[dict, object]:
    """The maps and their title, or nothing at all.

    Nothing here is fatal: with no disks the map tab draws an empty grid and
    says so, and the editor tab does not care at all. A truncated download
    sitting in the folder is the same -- a reason to draw no map, not a reason
    to take the window down when somebody points the preference at it.
    """
    try:
        from automap.maps import load_maps_titled as _load
        return _load(disks, game)
    except Exception:
        debuglog.exception("could not read the maps under %s", disks)
        return {}, None


class WishWindow(QMainWindow):
    """The application window."""

    def __init__(self, save: str | None = None, game_disk: str | None = None,
                 maps: dict | None = None, area: str | None = None,
                 settings: Settings | None = None,
                 session: Session | None = None,
                 tab: int = MAP_TAB, title: str | None = None,
                 disks: str | None = None):
        super().__init__()
        self.ui = Ui_WishWindow()
        self.ui.setupUi(self)
        self.tabs = self.ui.tabs
        self.settings = settings or Settings()

        # What the log has already said, so a title change or a poll does not
        # write the same line again.
        self._logged_save: str | None = None
        self._logged_area: str | None = None

        # `--disks`, kept so every re-resolution knows a flag was given: it
        # beats the preference for this run and the dialog says so rather than
        # letting the setting look ignored.
        self.disks_flag = disks
        self._title = title
        self.disks, self.disks_source = paths.resolve_disks(
            flag=disks, beside=save, game=game_named(title),
            settings=self.settings)
        apply_ultimate_host(getattr(self.settings, "ultimate_host", "") or "")

        self.editor = EditorBinding(self, save, game_disk, disks=self.disks_text(), backups="", last_save_folder=self.settings.last_save_folder, saves_folder=self.settings.saves_folder)
        # The divider between the roster and Character and the sheet below
        # them, and the heights the user last dragged it to (#97). Built here
        # rather than inside `EditorBinding` because the settings file is the
        # window's, and a remembered height is the only part of this that
        # outlives the run.
        self.editor_rows = RowSplitter(self, self.settings, parent=self)
        # The backup folder follows whatever save is open until somebody
        # chooses one, so the window has to hear about every open. `""` above
        # is deliberate: the editor is managed from here, and until this says
        # otherwise there is nowhere to put a copy.
        self.editor.opened.connect(lambda _p: self.follow_save())
        self.follow_save()
        # Whose area names to print. `GEO15` is Sokol Keep in Pool of Radiance
        # and somewhere else in Curse, so the caller that loaded the maps says
        # which title they are. Failing that the open save says, and only with
        # nothing open at all is this the title it has always been.
        self.mapper = Automapper(
            None, maps if maps is not None else load_maps(self.disks_text()),
            area=area, title=title or self._open_title())
        self.map = AutomapBinding(self, self.mapper, settings=self.settings, drive=False, disks=self.disks_text())


        # One status bar for the window. The pages keep their own -- they are
        # whole windows and are still usable alone -- but a status bar inside a
        # tab inside a window reads as clutter, so theirs are hidden here and
        # their lines forwarded to this one.
        self.statusBar().addPermanentWidget(self.map.fog_box)
        # A log that survives a restart is one you forget is on, so while it is
        # on the window says so without being asked -- here, and in the title.
        self.log_flag = QLabel("● debug log on")
        self.log_flag.setStyleSheet("color: #b00")
        self.log_flag.setVisible(False)
        self.statusBar().addPermanentWidget(self.log_flag)
        self._retitle()

        self.session = session or Session(
            preferred=getattr(self.settings, "backend", "") or None,
            interval_ms=getattr(self.settings, "interval_ms", 0) or None)
        self.session.changed.connect(self._session_said)
        self.map.statusChanged.connect(self._map_said)

        self._menu()
        self._log_fasttravels()
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.setCurrentIndex(tab)
        self._tab_changed(self.tabs.currentIndex())
        self.session.start()

    def _open_title(self) -> str:
        """The open save's game, or Pool of Radiance when nothing is open."""
        game = getattr(getattr(self.editor, "party", None), "game", None)
        return getattr(game, "title", None) or games.DEFAULT.title

    # -- chrome ----------------------------------------------------------

    def _menu(self) -> None:
        """File actions, so the keys work from either tab.

        The editor's own buttons stay: this is the same three calls, reachable
        without going back to the editor tab to click them.
        """
        menu = self.menuBar().addMenu("&File")
        for text, slot, key in (
                ("&Open…", self.editor.open_file, QKeySequence.StandardKey.Open),
                ("&Save", self.editor.save, QKeySequence.StandardKey.Save),
                ("Save &As…", self.editor.save_as,
                 QKeySequence.StandardKey.SaveAs)):
            action = QAction(text, self)
            action.setShortcut(key)
            action.triggered.connect(lambda _checked=False, s=slot: s())
            menu.addAction(action)

        # A submenu with one item in it, because the thing it imports is one
        # of several ports and the next one goes beside it rather than growing
        # the File menu another top-level verb.
        #
        # Built only when `WISH_EXPERIMENTAL_DOS_IMPORT` says so -- see `editor/dosimport.py`.
        # Not built rather than disabled: a greyed-out entry invites the
        # question of how to un-grey it, and the answer would be a sentence
        # this window does not want.
        from editor import dosimport
        self.import_dos_action = None
        if dosimport.enabled():
            imports = menu.addMenu(dosimport.MENU_IMPORT)
            dos_save = QAction(dosimport.MENU_DOS_SAVE, self)
            dos_save.triggered.connect(
                lambda _checked=False: self.editor.import_dos_save())
            imports.addAction(dos_save)
            self.import_dos_action = dos_save

        # Export beside Import rather than one dialog with a source and a
        # destination: the source is always the save this window already has
        # open, so a source control would be a control with one sensible
        # value -- and an import lands in the open document while an export
        # writes elsewhere and is final, which is a difference a direction
        # combo box would hide.
        #
        # Built only when `WISH_EXPERIMENTAL_EXPORT` says so -- see
        # `editor/exports.py`, where every string in it is still a placeholder.
        from editor import exports
        self.export_dos_action = None
        self.export_amiga_action = None
        if exports.enabled():
            out = menu.addMenu(exports.MENU_EXPORT)
            for text, slot in (
                    (exports.MENU_DOS, self.editor.export_dos_save),
                    (exports.MENU_AMIGA, self.editor.export_amiga_party)):
                action = QAction(text, self)
                action.triggered.connect(
                    lambda _checked=False, s=slot: s())
                out.addAction(action)
            self.export_dos_action, self.export_amiga_action = out.actions()

        menu.addSeparator()
        prefs = QAction("&Preferences…", self)
        prefs.setShortcut(QKeySequence(SHORTCUT))
        prefs.triggered.connect(lambda _checked=False: self.preferences())
        menu.addAction(prefs)
        self.preferences_action = prefs

        menu.addSeparator()
        quit_ = QAction("&Quit", self)
        quit_.setShortcut(QKeySequence.StandardKey.Quit)
        quit_.triggered.connect(self.close)
        menu.addAction(quit_)

        view = self.menuBar().addMenu("&View")
        for i, name in ((MAP_TAB, "&Automapper"), (EDITOR_TAB, "&Character Editor")):
            action = QAction(name, self)
            action.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            action.triggered.connect(lambda _c=False, at=i:
                                     self.tabs.setCurrentIndex(at))
            view.addAction(action)

        # The switch is in File > Preferences now, and it is remembered. The
        # action stays because it is the model the dialog's checkbox is a view
        # of -- and because the log has to be turned back on at startup by
        # something, without the modal note that a click gets.
        self.debug_action = QAction("&Debug log", self, checkable=True)
        self.debug_action.toggled.connect(self._debug_log)
        view.addSeparator()
        self.show_log_action = QAction("Sho&w log", self)
        self.show_log_action.setEnabled(False)
        self.show_log_action.triggered.connect(self.show_log)
        view.addAction(self.show_log_action)

        self._make_backend_actions()
        help_menu = install_help(self)
        self.licenses_action = licenses.install(self, help_menu)
        if getattr(self.settings, "diagnostics", False):
            self.debug_action.blockSignals(True)
            self.debug_action.setChecked(True)
            self.debug_action.blockSignals(False)
            self._debug_log(True, announce=False)

    # -- which backend ---------------------------------------------------

    def _make_backend_actions(self) -> None:
        """Prefer one backend over another, without editing the JSON.

        It only ever breaks a tie: with one thing answering, `backends.find`
        needs no help and this changes nothing. The labels say which are
        answering and which are unverified, because one of them is written from
        a vendor document and nobody on this project has the hardware.

        These are actions in no menu: File > Preferences draws them as radio
        buttons. One model, so the preference, the session and the dialog
        cannot get out of step.
        """
        group = QActionGroup(self)
        group.setExclusive(True)
        self.backend_actions: dict[str, QAction] = {}
        #: name -> (state, verified), filled by `label_backends`. The dialog
        #: draws the state as a badge, so it needs it apart from the label.
        self.backend_status: dict[str, tuple[str, bool]] = {}
        rows = [(ANY_BACKEND, "&Whichever answers", "")]
        rows += [(b.name, b.name, b.setup_hint) for b in backends.backends()]
        for name, text, hint in rows:
            action = QAction(text, self, checkable=True)
            action.setToolTip(hint)
            action.setChecked(
                (self.settings.backend or "").lower() == name.lower())
            action.triggered.connect(
                lambda _checked=False, n=name: self._prefer_backend(n))
            group.addAction(action)
            self.backend_actions[name] = action
        if not any(a.isChecked() for a in self.backend_actions.values()):
            # A remembered name for a backend this build no longer offers.
            self.backend_actions[ANY_BACKEND].setChecked(True)

    def label_backends(self) -> None:
        """Say which are answering, when the dialog asks and not before.

        `probe()` is a TCP connect with a short timeout; doing it on the poll
        timer would be noise, and doing it once at startup would be stale by
        the time anybody looked.

        The state is also kept in `backend_status`, apart from the label: the
        dialog draws it as a badge, because on Windows "Ultimate not
        answering, unverified…" ran into its own label as one sentence.
        """
        for backend in backends.backends():
            action = self.backend_actions.get(backend.name)
            if action is None:
                continue
            state = "answering" if backend.present() else "not answering"
            self.backend_status[backend.name] = (state, backend.verified)
            if not backend.verified:
                state += ", unverified: nobody here has the hardware"
            action.setText(f"{backend.name} - {state}")

    def _prefer_backend(self, name: str) -> None:
        """Remember the preference and act on it now.

        The settings are this window's to keep; dropping a backend that is
        already attached is the session's, and `Session.prefer` does it.
        """
        self.settings.backend = name
        self.settings.save()
        self.session.prefer(name)
        self.statusBar().showMessage(
            f"backend: {name}" if name else "backend: whichever answers")

    # -- preferences -----------------------------------------------------

    def preferences(self) -> PreferencesDialog:
        """File > Preferences. Returns the dialog, which is what a test wants."""
        dialog = PreferencesDialog(self)
        self.show_dialog(dialog)
        return dialog

    def show_dialog(self, dialog) -> None:
        """Put a dialog up. A method so a test can open one without blocking."""
        dialog.exec()

    def disks_text(self) -> str | None:
        """The resolved Game directory as a plain path, for the two tabs."""
        return str(self.disks) if self.disks is not None else None

    def game(self):
        """Which title is open, as a `Game`, or None if nothing says."""
        return (getattr(getattr(self.editor, "party", None), "game", None)
                or game_named(self._title))

    def map_game(self):
        """Which title the *automapper* is labelling with, as a `Game`.

        **Not `game()`**, which is the open save's and is None with nothing
        open. The fast-travel list has to agree with the map, and the map
        always has a title -- it falls back through the open save, the disks
        folder and `games.DEFAULT` (`docs/138-multiple-games.md` §3). A list
        keyed off anything else would offer one game's areas in another's
        session, which is the whole of #14.
        """
        return game_named(getattr(self.map.state, "title", None))

    def set_disks(self, folder: str) -> None:
        """The Game directory changed: remember it, and act on it now.

        Both tabs are fed from the one answer -- the editor's item names and
        icons, and the map's GEOs and roster names -- so a folder typed here
        works without a restart. That is the acceptance test for the whole
        dialog: set one folder, get names and a map.
        """
        folder = (folder or "").strip()
        if folder == (getattr(self.settings, "disks", "") or ""):
            return
        self.settings.disks = folder
        self.settings.save()
        self.reload_disks()

    def reload_disks(self) -> None:
        """Re-resolve where the disks are and hand the answer to both tabs."""
        self.disks, self.disks_source = paths.resolve_disks(
            flag=self.disks_flag, beside=self.editor.path, game=self.game(),
            settings=self.settings)
        where = self.disks_text()
        debuglog.note("game disks: %s (%s)", where or "nothing found",
                      self.disks_source)
        self.editor.set_disks(where)
        maps, game = load_maps_titled(where, self.game())
        self.map.set_maps(maps, title=game.title if game else None,
                          disks=where)
        self.statusBar().showMessage(
            f"game disks: {where} - {len(maps)} maps" if where
            else "no game disks found")

    def follow_save(self) -> None:
        """A save was opened: point the automatic backup folder at it, and
        remember its folder for the next `File > Open` (#66).

        The backup half does nothing at all once the user has chosen a folder
        in the dialog -- *"never change it after they've specified it
        themselves"* -- but the remembered-folder half always follows: it is a
        convenience, not a preference, so every open updates it.
        """
        if not chosen_backup_folder(self.settings):
            where = backup_folder(self.settings, self.editor.path)
            if where != (self.settings.backup_folder or ""):
                self.settings.backup_folder = where
                self.settings.save()
        self.editor.set_backup_folder(self.settings.backup_folder or "")
        if self.editor.path:
            folder = str(self.editor.path.parent)
            if folder != (self.settings.last_save_folder or ""):
                self.settings.last_save_folder = folder
                self.settings.save()

    def set_backup_folder(self, folder: str) -> None:
        """The user typed, browsed or cleared one in the dialog.

        Anything they typed is theirs and is never moved again. **Clearing it
        is the way back to automatic**: a setting a user cannot undo is a trap,
        and the field fills in again from the open save -- immediately when
        there is one, otherwise the next time one is opened.
        """
        folder = (folder or "").strip()
        self.settings.backup_folder = folder
        self.settings.backup_folder_chosen = bool(folder)
        self.settings.save()
        self.follow_save()

    def set_saves_folder(self, folder: str) -> None:
        """The user typed, browsed or cleared the saves folder in the
        dialog (#66 steps 2 and 3).

        Unlike the backup folder above, this has no automatic state to fall
        back to: it is either set or it is not, and clearing it goes back to
        the folder a save was last opened from, or beside the one already
        open.
        """
        folder = (folder or "").strip()
        self.settings.saves_folder = folder
        self.settings.save()
        self.editor.set_saves_folder(folder)

    def set_ultimate_host(self, host: str) -> None:
        """Where the Commodore 64 Ultimate is. Empty means "no device"."""
        self.settings.ultimate_host = host
        self.settings.save()
        apply_ultimate_host(host)

    def set_interval(self, interval_ms: int) -> None:
        """How often to poll, or 0 for the backend's own."""
        self.settings.interval_ms = interval_ms
        self.settings.save()
        self.session.set_interval(interval_ms)

    def set_fast_travel_targets(self, ids) -> None:
        """Which areas the Fast Travel dropdown offers, by `goldbox/areas.py` id.

        Empty is a choice like any other and is saved as one: the setting is
        None only until somebody has ticked or unticked anything. Filed under
        the open title's key, because an area id means nothing without one.
        """
        self.settings.set_chosen_areas(ids, self.map_game())
        self.settings.save()
        self.map.fasttravel_bar.reload_areas()

    # -- the fasttravel row ----------------------------------------------------

    def _log_fasttravels(self) -> None:
        """A line in the debug log for every fasttravel attempted, with its writes.

        Our own writes to our own machine, so the log's privacy claims are
        unaffected -- it still records no file paths, no character names and no
        bytes from a save.
        """
        bar = getattr(self.map, "fasttravel_bar", None)
        if bar is None:
            return
        onward = bar.say

        def say(text: str, detail: str = "", alarm: bool = False) -> None:
            outcome = bar.last
            where = ", ".join(f"${a:04X}+{len(b)}"
                               for a, b in getattr(outcome, "writes", ()))
            debuglog.note("fasttravel: %s [%s]", text, where or "no writes")
            onward(text, detail, alarm=alarm)

        bar.say = say

    # -- the debug log ---------------------------------------------------

    def _debug_log(self, on: bool, announce: bool = True) -> None:
        """Start or stop writing, at once, and say where the file is.

        Remembered between sessions since 2026-08, at Donald's request. The
        reason it was not has not gone away -- a log you forget is on grows for
        months and is worth nothing when you finally read it -- so `_flag_log`
        says it is on wherever you are looking.

        **Turning it on puts no box on the screen.** It used to explain what
        the log records and where; a debug log needs no explanation, and a
        modal note for a checkbox is a poor trade. The path goes to the status
        bar instead, and View > Show log opens it. `announce` survives for the
        one thing worth interrupting for -- a log file that would not open --
        and is False at startup, where a box before the window is even up is
        worse than the setting it reports.
        """
        self.settings.diagnostics = bool(on)
        self.settings.save()
        if not on:
            debuglog.stop()
            self.show_log_action.setEnabled(False)
            self._flag_log()
            self.statusBar().showMessage("debug log off")
            return
        path = debuglog.start()
        if path is None:
            self.debug_action.setChecked(False)
            if announce:
                self.announce("Debug log",
                              "The log file could not be opened. Check that "
                              "the settings directory is writable.")
            return
        self.show_log_action.setEnabled(True)
        self._flag_log()
        self._log_the_state()
        self.statusBar().showMessage(f"debug log: {path}")

    def _flag_log(self) -> None:
        """Say the log is on, in two places nobody has to go looking for.

        The status bar because it is on screen whatever the window is doing,
        and the title because that is what a screenshot in a bug report shows.
        """
        self.log_flag.setVisible(debuglog.is_on())
        self._retitle()

    def _retitle(self, base: str | None = None) -> None:
        if base is not None:
            self._editor_title = base
        self.setWindowTitle(getattr(self, "_editor_title", "Wish")
                            + (" [logging]" if debuglog.is_on() else ""))

    def announce(self, title: str, text: str) -> None:
        """A modal note. A method so a test can silence it."""
        QMessageBox.information(self, title, text)

    def show_log(self) -> None:
        """Open the log in whatever the desktop uses for a text file."""
        path = debuglog.path()
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _log_the_state(self) -> None:
        """What was already true when the log was turned on."""
        debuglog.note("tab: %s", self.tabs.tabText(self.tabs.currentIndex()))
        debuglog.note("%s", debugmode.note())
        debuglog.note("session: %s, polling every %d ms",
                      self.session.note, self.session.interval_ms)
        self._log_save()
        self._log_area()

    def _log_save(self) -> None:
        """The shape of the open file: size, blocks, characters, area."""
        if not debuglog.is_on() or self.editor.party is None:
            return
        shape = debuglog.save_shape(self.editor.party, self.editor.path)
        if shape != self._logged_save:
            self._logged_save = shape
            debuglog.note("save file: %s", shape)

    def _log_area(self) -> None:
        """Which map is being drawn, and how sure the fingerprint is."""
        if not debuglog.is_on():
            return
        shape = debuglog.area_shape(self.mapper.state)
        if shape != self._logged_area:
            self._logged_area = shape
            debuglog.note("map area: %s", shape)

    def _editor_said(self, text: str) -> None:
        if self.tabs.currentIndex() == EDITOR_TAB and text:
            self.statusBar().showMessage(text)

    def _map_said(self, text: str) -> None:
        if self.tabs.currentIndex() == MAP_TAB:
            self.statusBar().showMessage(text)

    def _session_said(self, note: str) -> None:
        # A busy monitor is said in red: the game IS running, and "waiting for
        # a game" in the ordinary colour reads as "nothing is there".
        self.map.waiting("" if self.session.state == CONNECTED else note,
                         alarm=self.session.state == BUSY)
        

    # -- which tab is watching -------------------------------------------

    def _tab_changed(self, index: int) -> None:
        """Only the visible tab polls; the others cost nothing.

        The editor is handed no reader at all, which is the promise that it
        never talks to a live machine expressed as code rather than as a rule.
        """
        self.map.fog_box.setVisible(index == MAP_TAB)
        if index == MAP_TAB:
            self.session.set_reader(self._read_map)
            self.map.canvas.setFocus()
            self.statusBar().showMessage(self.map.status_text())
        else:
            self.session.set_reader(None)
            self.statusBar().showMessage(self._file_note())
        debuglog.note("tab: %s, polling every %d ms", self.tabs.tabText(index),
                      self.session.interval_ms)

    def _read_map(self, target) -> None:
        self.mapper.target = target
        self.map.tick()
        self._log_area()

    def _file_note(self) -> str:
        if self.editor.party is None:
            return "Open a save disk to begin"
        name = self.editor.path.name if self.editor.path else "?"
        return f"{name} - {self.editor.party.describe()}"

    # -- shutting down ---------------------------------------------------

    def closeEvent(self, event) -> None:
        """The editor asks about unsaved changes first, and may refuse.

        Its own `closeEvent` owns that question -- the merged window must not
        grow a second copy of it and get the two out of step.
        """
        if not self.editor.close():
            event.ignore()
            return
        remember_geometry(self, self.settings)
        self.settings.save()
        self.session.close()
        self.map.shutdown()
        debuglog.stop()
        super().closeEvent(event)


#: The first run's size, when nothing has been remembered yet. Wide enough for
#: the map, the roster cards and the notes column side by side; clamped to the
#: screen, so a smaller display gets its own size rather than this one.
FIRST_RUN = (1875, 1030)


def dress(app) -> None:
    """The application's name and its icon, before the first window exists.

    Three separate mechanisms, one drawing:

    * **`setWindowIcon`** is the title bar, Alt-Tab and the taskbar button of a
      running window. It is a `QIcon` carrying a pixmap per size, painted from
      `ui/icons.py`, so Qt picks rather than scales. What a *pinned* shortcut
      and Explorer show is the `.ico` in the executable's resource instead --
      `wish.spec` -- and the two have to be the same drawing, which they are
      because both come from the same path data.
    * **`setDesktopFileName`** is how GNOME and KDE match a window to its
      `.desktop` entry, and without it a Wayland window gets the toolkit's
      generic icon whatever `setWindowIcon` said. `wish` is the id the
      freedesktop icons under `assets/icons/hicolor` are named for.
    * **the app user model id** is Windows' key for taskbar grouping and
      pinning. Left unset, a Python-hosted window can be grouped under the
      interpreter rather than under itself, and a pin can attach to the wrong
      thing.
    """
    app.setApplicationName("Wish")
    # Not `setApplicationDisplayName`: Qt appends it to every window title, and
    # the title already starts with "Wish".
    app.setDesktopFileName(paths.APP)
    app.setWindowIcon(app_icon())
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "net.donaldmorton.wish")
        except Exception as exc:             # noqa: BLE001 -- cosmetic only
            debuglog.debug("no app user model id: %s", exc)


def run(save: str | None = None, game_disk: str | None = None,
        maps: dict | None = None, area: str | None = None,
        tab: int = EDITOR_TAB, interval_ms: int | None = None,
        title: str | None = None, disks: str | None = None) -> int:
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    dress(app)
    settings = Settings.load()
    session = Session(preferred=getattr(settings, "backend", "") or None,
                      interval_ms=interval_ms or settings.interval_ms or None)
    win = WishWindow(save, game_disk, maps=maps, area=area, settings=settings,
                     session=session, tab=tab, title=title, disks=disks)
    # Qt's own geometry, not a width and a height: it carries the position and
    # the screen too, so a window last closed on a monitor that is no longer
    # attached comes back on one that is.
    restore_geometry(win, settings, floor=FIRST_RUN)
    win.show()
    # Again, now that there is a frame to measure. Before `show()` the title
    # bar and the border do not exist yet, so the first clamp works off an
    # estimate (`config.UNSHOWN_CHROME`); this one works off the real numbers
    # and can only ever shrink the window further. A 1030 px window on a
    # 1920x1080 Windows desktop passed the first clamp and still opened with
    # its status bar below the bottom of the screen.
    clamp_to_screen(win)
    # And stand by that size when the compositor answers back with one of its
    # own. cosmic-comp does, a frame after the window appears, and Qt takes it:
    # without this the remembered size lived about 50 ms and what closing wrote
    # back was the compositor's idea, not Donald's.
    hold_geometry(win)
    # Off unless `WISH_NATIVE_LOG` is set. See `wish/nativewatch.py` for what
    # it is for and the bug it was written to catch.
    nativewatch.install_if_asked(app)
    return app.exec()
