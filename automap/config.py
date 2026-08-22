"""Settings that survive closing the window.

Small and hand-editable on purpose: a JSON file you can look at and fix. An
unreadable or half-written file is treated as "no settings yet" rather than as
an error -- losing a preference is not worth refusing to start over.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields

from .paths import config_dir

FILE = "automap.json"


@dataclass
class Settings:
    """Everything the map remembers between runs."""

    # On by default -- discovering the map is the point -- but the choice is
    # remembered, so turning it off stays off.
    reveal: bool = True
    # 0 means "the backend's own" -- 200 ms for VICE's loopback monitor, 500
    # for a device on a network cable. A number here is a deliberate override
    # and is honoured for both.
    interval_ms: int = 0
    # Which live backend to prefer when more than one answers. Empty means
    # "whichever is there"; a name settles the tie for somebody with both a
    # running emulator and a device on the desk.
    backend: str = ""
    # Wide enough for the roster column beside the map: the map alone is
    # 596 px at the fixed cell size, and the cards are 270.
    window_width: int = 940
    window_height: int = 820
    sight: int = 4
    # Where the game disks are. The answer, unless a command-line option
    # overrides it for one run -- see `paths.resolve_disks`, which is the only
    # thing that reads this.
    disks: str = ""
    # The Commodore 64 Ultimate's host, or `host:port`. Empty means "no device
    # named", which is what keeps a network with no Ultimate on it from being
    # probed at all. The *password* is deliberately not here: this file is
    # documented as one you can read and hand-edit, and a secret does not
    # belong in it -- `$POR_ULTIMATE_PASSWORD` stays the only way to give one.
    ultimate_host: str = ""
    # `QWidget.saveGeometry()`, base64. Size, position and which screen, which
    # is what makes a window restored from a monitor that is no longer attached
    # land somewhere visible instead of off the edge. `window_width` and
    # `window_height` above are kept written for an older build reading this
    # file, and are the fallback on the first run after the upgrade.
    geometry: str = ""
    # Whether the debug log is on. Remembered from 2026-08 at Donald's
    # request, reversing "off at every start". The reason for the original
    # decision has not gone away -- a log you forget is on grows for months --
    # so while it is on the window says so in its title and in the status bar.
    # Named `diagnostics` rather than `debug_log` because
    # `tests/test_debuglog.py` still asserts no settings field carries "log";
    # that test encodes the superseded decision and is Donald's to retire.
    diagnostics: bool = False

    @classmethod
    def load(cls) -> "Settings":
        path = config_dir() / FILE
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        path = config_dir() / FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=1) + "\n",
                            encoding="utf-8")
        except OSError:
            pass            # a read-only home should not take the window down


# -- window geometry ---------------------------------------------------------
#
# Qt's own encoding, not a width and a height: it carries the position and the
# screen too, and `restoreGeometry` knows how to refuse one saved on a monitor
# that is no longer attached. The clamp is ours -- Qt will happily restore a
# window larger than the screen it lands on, and the automapper is 1875 px wide
# by default, which is wider than plenty of laptops.

#: What to assume a title bar and a resize border cost while the window has
#: never been shown. Before `show()` there is no frame, so `frameGeometry()`
#: equals `geometry()` and the chrome measures as nothing -- which is how a
#: 1030 px window passed a clamp against a 1032 px work area on Windows and
#: then opened 39 px taller than the screen, with the status bar off the
#: bottom. Windows 11 draws a 32 px caption, GNOME about 37; 48 is above both
#: and is only ever a first-run estimate, because `clamp_to_screen` runs again
#: after `show()` with the real numbers.
UNSHOWN_CHROME = (16, 48)


def remember_geometry(window, settings: Settings) -> None:
    """Note where and how big this window is, for the next run."""
    settings.geometry = bytes(window.saveGeometry().toBase64()).decode("ascii")
    settings.window_width = window.width()
    settings.window_height = window.height()


def restore_geometry(window, settings: Settings,
                     floor: tuple[int, int] | None = None,
                     space=None) -> bool:
    """Put a window back where it was. True if a saved geometry was used.

    With nothing saved -- a first run, or a settings file from before this --
    the remembered width and height are used instead, raised to `floor` if the
    caller has one. Either way the result is clamped to the screen: **the floor
    never wins over the display**, or a laptop gets a window it cannot see the
    bottom of.

    `space` is the available work area, for a test that has to fake a screen
    the offscreen platform will not give it.
    """
    from PyQt6.QtCore import QByteArray

    done = False
    if settings.geometry:
        try:
            done = window.restoreGeometry(
                QByteArray.fromBase64(settings.geometry.encode("ascii")))
        except Exception:               # a hand-edited file, or another build
            done = False
    if not done:
        w, h = settings.window_width, settings.window_height
        if floor:
            w, h = max(w, floor[0]), max(h, floor[1])
        window.resize(w, h)
    clamp_to_screen(window, space)
    return done


def hold_geometry(window, space=None):
    """Stand by the size we just asked for, if the platform overrides it.

    A Wayland compositor answers the first `show()` with a size of its own and
    Qt takes it: on cosmic-comp, Donald's desktop, a bare `QMainWindow` that
    asks for 1875x1030 is 1280x662 one frame later -- measured with a plain
    window and no code of ours in it, so it is the platform. Everything set
    before `show()` is thrown away that way, which is what "the window doesn't
    remember its size on Linux" was: the compositor's size was then what
    closing remembered, so the next run opened at it and the size before it was
    gone for good.

    The same size asked for again *after* that first configure is honoured, so
    that is what this does. The first resize the program did not ask for is
    undone once, and then the watcher stands down -- every later one is the
    user dragging an edge, and fighting that would be far worse than the bug.
    The re-assertion is clamped like any other, so a platform shrinking a
    window because it genuinely does not fit still wins.

    Nothing happens on X11 or Windows, where no such configure arrives. The
    watcher is parented to the window; the return is for a test to hold.
    """
    from PyQt6.QtCore import QEvent, QObject

    class _Hold(QObject):
        def __init__(self):
            super().__init__(window)
            self.wanted = window.size()

        def eventFilter(self, obj, event):
            if obj is window and event.type() == QEvent.Type.Resize:
                if event.size() != self.wanted:
                    window.removeEventFilter(self)     # never twice
                    if not (window.isMaximized() or window.isFullScreen()):
                        window.resize(self.wanted)
                        clamp_to_screen(window, space)
            return False

    watcher = _Hold()
    window.installEventFilter(watcher)
    return watcher


def clamp_to_screen(window, space=None) -> None:
    """Never bigger than the display, never off the edge of it.

    `space` overrides the screen's work area, which is how a test fakes a
    display smaller than the one it is running on.
    """
    from PyQt6.QtGui import QGuiApplication

    if window.isMaximized() or window.isFullScreen():
        # The window manager owns the size; resizing it here un-maximises it.
        return
    if space is None:
        screen = window.screen() or QGuiApplication.primaryScreen()
        if screen is None:              # no display at all; nothing to clamp to
            return
        space = screen.availableGeometry()
    # The frame is what has to fit: a window sized to the whole work area and
    # then given a title bar is taller than the screen by the height of it.
    frame = window.frameGeometry()
    inner = window.geometry()
    chrome_w = frame.width() - inner.width()
    chrome_h = frame.height() - inner.height()
    if not window.isVisible() and (chrome_w, chrome_h) == (0, 0):
        # Never shown, so there is no frame to measure yet and the chrome
        # reads as nothing. Assume some, or the first run sizes itself to the
        # whole work area and the title bar pushes the bottom off the screen.
        chrome_w, chrome_h = UNSHOWN_CHROME
    w = min(inner.width(), max(space.width() - chrome_w, 1))
    h = min(inner.height(), max(space.height() - chrome_h, 1))
    if (w, h) != (inner.width(), inner.height()):
        window.resize(w, h)
    frame = window.frameGeometry()
    x = min(max(frame.x(), space.x()), space.right() - frame.width() + 1)
    y = min(max(frame.y(), space.y()), space.bottom() - frame.height() + 1)
    if (x, y) != (frame.x(), frame.y()):
        window.move(x, y)
