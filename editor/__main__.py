"""The character editor.

    python -m editor [SAVE.D64]

The form lives in `editor/character.ui`. Open it in Qt Designer
(`/usr/lib/qt6/bin/designer editor/character.ui`), rearrange it, save, and
restart -- the layout is recompiled automatically.
"""

from __future__ import annotations

import argparse
import sys

#: The size the sheet asks for when there is room for all four columns.
WANTED = (1875, 1030)
#: What a title bar and a resize border cost before the window has been shown,
#: when `frameGeometry` still equals `geometry` and measures the chrome as
#: nothing. Windows 11 draws 32 px of caption, GNOME about 37.
UNSHOWN_CHROME = (16, 48)


def fit_on_screen(window, space=None) -> None:
    """Never wider or taller than the display, whatever the sheet wants.

    The character sheet is four columns and does not fit a small desktop: it
    is inside a scroll area for exactly that reason, and scrolling is the
    answer. What must not happen is the *window* opening bigger than the
    screen -- Donald's compositor hands out 1280x662 of a 1920x1080 desktop,
    and a window that takes 1875 of it puts its right-hand column and its
    status bar where nobody can reach them.

    `space` overrides the work area, which is how a test fakes a display
    smaller than the one it is running on. The mapper has the same rule and
    this is not imported from it: the editor package imports nothing from the
    live-reading side, which `docs/README.md` decision 1 states and a grep in
    `tests/test_wish.py` holds.
    """
    from PyQt6.QtGui import QGuiApplication

    if window.isMaximized() or window.isFullScreen():
        return
    if space is None:
        screen = window.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        space = screen.availableGeometry()
    frame, inner = window.frameGeometry(), window.geometry()
    chrome = (frame.width() - inner.width(), frame.height() - inner.height())
    if not window.isVisible() and chrome == (0, 0):
        chrome = UNSHOWN_CHROME
    wide = min(inner.width(), max(space.width() - chrome[0], 1))
    high = min(inner.height(), max(space.height() - chrome[1], 1))
    if (wide, high) != (inner.width(), inner.height()):
        window.resize(wide, high)
    frame = window.frameGeometry()
    x = min(max(frame.x(), space.x()), space.right() - frame.width() + 1)
    y = min(max(frame.y(), space.y()), space.bottom() - frame.height() + 1)
    if (x, y) != (frame.x(), frame.y()):
        window.move(x, y)


def main(argv: list[str] | None = None) -> int:
    # Uncaught exceptions to the debug log rather than to a stderr a windowed
    # Windows build has not got -- `wish/debuglog.py`. Imported here because
    # `editor` may not import a package that could reach an emulator, and
    # `tests/test_wish.py` greps this one for that.
    from wish import debuglog
    debuglog.install_excepthook()

    ap = argparse.ArgumentParser(description="Gold Box character editor")
    ap.add_argument("save", nargs="?", help="a .D64 to open")
    ap.add_argument("--game-disk",
                    help="a game disk of the same title as the save -- "
                         "POOL*.D64, CURSE*.D64, SILVER*.D64 -- for item "
                         "names and icons")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    from tools.genui import ensure_current
    if ensure_current():
        print("ui files changed; recompiled forms")

    from PyQt6.QtWidgets import QApplication

    from .window import EditorWindow

    app = QApplication(sys.argv[:1])
    win = EditorWindow(args.save, args.game_disk)
    win.resize(*WANTED)
    fit_on_screen(win)
    win.show()
    # Again, now that there is a frame to measure: before `show()` the title
    # bar does not exist yet and the estimate above stands in for it.
    fit_on_screen(win)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
