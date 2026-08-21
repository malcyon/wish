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

The editor tab is never handed the target. That is `docs/PLAN.md`'s first
decision made structural: `editor/` imports nothing from `automap/`, and the
file path works with no emulator anywhere.
"""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QStatusBar, QTabWidget

from automap.config import Settings
from automap.state import Automapper
from automap.window import AutomapWindow
from editor.window import EditorWindow

from . import backends, debuglog, debugmode
from .about import install as install_help
from .session import BUSY, CONNECTED, Session

# The map is what a player has open while playing; the editor is the
# occasional visit. Index order is tab order, so the map is first.
MAP_TAB, EDITOR_TAB = 0, 1

#: No preference: `backends.find` takes whichever answers first. The ordinary
#: case, and what an empty `Settings.backend` means.
ANY_BACKEND = ""


def load_maps(disks: str | None = None) -> dict:
    """Every GEO off the game disks, or nothing if they cannot be found.

    Nothing here is fatal: with no disks the map tab draws an empty grid and
    says so, and the editor tab does not care at all.
    """
    try:
        from automap.__main__ import load_maps as _load
        return _load(disks)
    except Exception:
        return {}


class WishWindow(QMainWindow):
    """The application window."""

    def __init__(self, save: str | None = None, game_disk: str | None = None,
                 maps: dict | None = None, area: str | None = None,
                 settings: Settings | None = None,
                 session: Session | None = None,
                 tab: int = MAP_TAB):
        super().__init__()
        self.settings = settings or Settings()

        # What the log has already said, so a title change or a poll does not
        # write the same line again.
        self._logged_save: str | None = None
        self._logged_area: str | None = None

        self.editor = EditorWindow(save, game_disk)
        self.mapper = Automapper(None, maps if maps is not None else load_maps(),
                                 area=area)
        self.map = AutomapWindow(self.mapper, settings=self.settings,
                                 drive=False)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.map, "Automapper")
        self.tabs.addTab(self.editor, "Character Editor")
        self.setCentralWidget(self.tabs)

        # One status bar for the window. The pages keep their own -- they are
        # whole windows and are still usable alone -- but a status bar inside a
        # tab inside a window reads as clutter, so theirs are hidden here and
        # their lines forwarded to this one.
        self.setStatusBar(QStatusBar())
        for page in (self.editor, self.map):
            page.statusBar().hide()
        self.statusBar().addPermanentWidget(self.map.fog_box)
        self.editor.statusBar().messageChanged.connect(self._editor_said)
        self.map.statusChanged.connect(self._map_said)
        self.editor.windowTitleChanged.connect(self.setWindowTitle)
        self.editor.windowTitleChanged.connect(lambda _t: self._log_save())
        self.setWindowTitle(self.editor.windowTitle())

        self.session = session or Session(
            preferred=getattr(self.settings, "backend", "") or None)
        self.session.changed.connect(self._session_said)

        self._menu()
        self._log_warps()
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.setCurrentIndex(tab)
        self._tab_changed(self.tabs.currentIndex())
        self.session.start()

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

        # Off at every start, and deliberately not remembered: a logging
        # setting that survives a restart is one you forget is on.
        view.addSeparator()
        self.debug_action = QAction("&Debug log", self, checkable=True)
        self.debug_action.setChecked(False)
        self.debug_action.toggled.connect(self._debug_log)
        view.addAction(self.debug_action)
        self.show_log_action = QAction("Sho&w log", self)
        self.show_log_action.setEnabled(False)
        self.show_log_action.triggered.connect(self.show_log)
        view.addAction(self.show_log_action)

        self._backend_menu(view)
        install_help(self)

    # -- which backend ---------------------------------------------------

    def _backend_menu(self, view) -> None:
        """Prefer one backend over another, without editing the JSON.

        It only ever breaks a tie: with one thing answering, `backends.find`
        needs no help and this menu changes nothing. The labels say which are
        answering and which are unverified, because one of them is written from
        a vendor document and nobody on this project has the hardware.
        """
        view.addSeparator()
        menu = view.addMenu("&Backend")
        menu.setToolTipsVisible(True)
        self.backend_menu = menu
        group = QActionGroup(self)
        group.setExclusive(True)
        self.backend_actions: dict[str, QAction] = {}
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
            menu.addAction(action)
            self.backend_actions[name] = action
        if not any(a.isChecked() for a in self.backend_actions.values()):
            # A remembered name for a backend this build no longer offers.
            self.backend_actions[ANY_BACKEND].setChecked(True)
        menu.aboutToShow.connect(self.label_backends)

    def label_backends(self) -> None:
        """Say which are answering, when the menu is opened and not before.

        `probe()` is a TCP connect with a short timeout; doing it on the poll
        timer would be noise, and doing it once at startup would be stale by
        the time anybody looked.
        """
        for backend in backends.backends():
            action = self.backend_actions.get(backend.name)
            if action is None:
                continue
            state = "answering" if backend.present() else "not answering"
            if not backend.verified:
                state += ", unverified: nobody here has the hardware"
            action.setText(f"{backend.name} - {state}")

    def _prefer_backend(self, name: str) -> None:
        """Remember the preference and act on it now.

        `Session` takes its preference when it is built and offers no setter,
        so this is the whole of the state it keeps about one. A different
        backend already attached is dropped: the next poll reattaches, and the
        point of choosing is to be on the other one.
        """
        self.settings.backend = name
        self.settings.save()
        self.session._preferred = name or None
        attached = getattr(self.session, "backend", None)
        if name and attached is not None and \
                attached.name.lower() != name.lower():
            self.session.detach(f"switching to {name}")
        self.statusBar().showMessage(
            f"backend: {name}" if name else "backend: whichever answers")

    # -- the warp row ----------------------------------------------------

    def _log_warps(self) -> None:
        """A line in the debug log for every warp attempted, with its writes.

        Our own writes to our own machine, so the log's privacy claims are
        unaffected -- it still records no file paths, no character names and no
        bytes from a save.
        """
        bar = getattr(self.map, "warp_bar", None)
        if bar is None:
            return
        onward = bar.say

        def say(text: str, detail: str = "", alarm: bool = False) -> None:
            outcome = bar.last
            where = ", ".join(f"${a:04X}+{len(b)}"
                               for a, b in getattr(outcome, "writes", ()))
            debuglog.note("warp: %s [%s]", text, where or "no writes")
            onward(text, detail, alarm=alarm)

        bar.say = say

    # -- the debug log ---------------------------------------------------

    def _debug_log(self, on: bool) -> None:
        """Start or stop writing, at once, and say where the file is."""
        if not on:
            debuglog.stop()
            self.show_log_action.setEnabled(False)
            self.statusBar().showMessage("debug log off")
            return
        path = debuglog.start()
        if path is None:
            self.debug_action.setChecked(False)
            self.announce("Debug log",
                          "The log file could not be opened. Check that the "
                          "settings directory is writable.")
            return
        self.show_log_action.setEnabled(True)
        self._log_the_state()
        self.statusBar().showMessage(f"debug log: {path}")
        self.announce(
            "Debug log",
            f"Writing to:\n\n{path}\n\n"
            "It records versions, which backend attached, the tab in view, "
            "errors with their tracebacks, and the shape of an open save -- "
            "not file paths, character names or any bytes from a save. "
            "Nothing is sent anywhere: read it before you attach it to a "
            "report. View > Show log opens it.")

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
        if self.tabs.currentIndex() == MAP_TAB and self.session.target is None:
            self.statusBar().showMessage(note)

    # -- which tab is watching -------------------------------------------

    def _tab_changed(self, index: int) -> None:
        """Only the visible tab polls; the others cost nothing.

        The editor is handed no reader at all, which is the promise that it
        never talks to a live machine expressed as code rather than as a rule.
        """
        self.map.fog_box.setVisible(index == MAP_TAB)
        if index == MAP_TAB:
            self.session.set_reader(self._read_map)
            self.map.setFocus()
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
        self.session.close()
        self.map.shutdown()
        debuglog.stop()
        super().closeEvent(event)


def run(save: str | None = None, game_disk: str | None = None,
        maps: dict | None = None, area: str | None = None,
        tab: int = EDITOR_TAB, interval_ms: int | None = None) -> int:
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    settings = Settings.load()
    session = Session(preferred=getattr(settings, "backend", "") or None,
                      interval_ms=interval_ms)
    win = WishWindow(save, game_disk, maps=maps, area=area, settings=settings,
                     session=session, tab=tab)
    win.resize(max(settings.window_width, 1875), max(settings.window_height, 1030))
    win.show()
    return app.exec()
