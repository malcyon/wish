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

from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QMainWindow, QStatusBar, QTabWidget

from automap.config import Settings
from automap.state import Automapper
from automap.window import AutomapWindow
from editor.window import EditorWindow

from .session import BUSY, CONNECTED, Session

EDITOR_TAB, MAP_TAB = 0, 1


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
                 tab: int = EDITOR_TAB):
        super().__init__()
        self.settings = settings or Settings()

        self.editor = EditorWindow(save, game_disk)
        self.mapper = Automapper(None, maps if maps is not None else load_maps(),
                                 area=area)
        self.map = AutomapWindow(self.mapper, settings=self.settings,
                                 drive=False)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.editor, "Character Editor")
        self.tabs.addTab(self.map, "Automapper")
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
        self.setWindowTitle(self.editor.windowTitle())

        self.session = session or Session(
            preferred=getattr(self.settings, "backend", "") or None)
        self.session.changed.connect(self._session_said)

        self._menu()
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
        for i, name in ((EDITOR_TAB, "&Character Editor"), (MAP_TAB, "&Automapper")):
            action = QAction(name, self)
            action.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            action.triggered.connect(lambda _c=False, at=i:
                                     self.tabs.setCurrentIndex(at))
            view.addAction(action)

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

    def _read_map(self, target) -> None:
        self.mapper.target = target
        self.map.tick()

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
    win.resize(max(settings.window_width, 1180), max(settings.window_height, 800))
    win.show()
    return app.exec()
