#!/usr/bin/env python3
"""Photograph the window's minimum width, at an ordinary party, under each of
the three fix shapes `#474 (Raising the UI font grows the window's minimum
width with an ordinary party open, which is the defect #41 removed for the
widest one)` names -- and today's behaviour, for comparison.

`.claude/rules/gui-text.md`: any interface decision Donald is asked to make
comes with a picture of it, not a table of pixel widths. `QWidget.grab()`
works offscreen, so this never puts a window on his screen -- run it the way
the rule says:

    env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE QT_QPA_PLATFORM=offscreen \
        GDK_BACKEND=x11 .venv/bin/python tools/rosterfloorshot.py work/issue474

**No source file is edited to take these pictures.** `EditorBinding._size_
roster` is monkeypatched onto the class in memory, for the lifetime of one
window's construction, with a version that differs from `editor/window.py`'s
own only in the single line the issue names -- the choice of the roster's
`setMinimumWidth`. `editor/window.py` is `#489`'s file while this runs, so
nothing here ever writes to it.

The "round" shape's step is `#474`'s third shape's own free parameter -- how
coarse a jump counts as "coarse" -- which the issue leaves open. 100px,
hard-coded in `_round` below, is this tool's illustrative choice, not a
recommendation.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

#: The four things being compared. Each is a function of `(natural,
#: ROSTER_MIN_WIDTH)` -> the value `_size_roster` would hand `setMinimumWidth`
#: when there is at least one row. `None` means "call nothing", which is
#: shape 1: the roster keeps whatever minimum `QTableView` has of its own and
#: stops being a floor under the window.
def _today(natural: int, cap: int) -> int:
    return min(natural, cap)


def _pin(natural: int, cap: int) -> int:
    return cap


def _round(natural: int, cap: int, step: int = 100) -> int:
    rounded = ((natural + step - 1) // step) * step
    return min(rounded, cap)


SHAPES = {
    "today": _today,
    "scroll": None,
    "pin": _pin,
    "round": _round,
}


def _patched_size_roster(chosen):
    """A drop-in for `EditorBinding._size_roster`, identical to the one in
    `editor/window.py` except for the one line `#474` is about. Copied by
    hand rather than imported, so if `editor/window.py`'s own version has
    moved on by the time this runs again, diff the two by eye before trusting
    a picture this makes.
    """
    from PyQt6.QtWidgets import QStyle

    from editor.rosterview import NAME_COLUMN, ROSTER_MIN_WIDTH
    from editor.window import MAX_ROSTER_ROWS, ROSTER_SLACK

    def _size_roster(self) -> None:
        view = self._child("roster")
        if view is None:
            return
        header = view.horizontalHeader()
        for column in range(self.model.columnCount()):
            header.setSectionResizeMode(column,
                                        header.ResizeMode.ResizeToContents)
        view.resizeColumnsToContents()
        bar = view.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        natural = (header.length() + view.verticalHeader().width()
                   + 2 * view.frameWidth() + bar)
        header.setSectionResizeMode(NAME_COLUMN,
                                    header.ResizeMode.Interactive)
        view.measure(natural, header.sectionSize(NAME_COLUMN))
        if self.model.rowCount() and chosen is not None:
            view.setMinimumWidth(chosen(natural, ROSTER_MIN_WIDTH))
        view.setMaximumWidth(natural)
        rows = min(self.model.rowCount(), MAX_ROSTER_ROWS)
        height = (view.horizontalHeader().height()
                  + sum(view.rowHeight(r) for r in range(rows))
                  + 2 * view.frameWidth() + bar)
        view.setMinimumHeight(height + ROSTER_SLACK)
        view.setMaximumHeight(height + ROSTER_SLACK)
        self._size_active_effects(view.maximumHeight())

    return _size_roster


def _build(save: str, shape: str):
    """A `WishWindow` on the ordinary party, sized under `shape`, squeezed to
    its own minimum. `editor.window.EditorBinding._size_roster` is patched
    onto the class before construction and restored before returning, so
    nothing outlives this call.
    """
    from editor.window import EditorBinding
    from wish.session import Session
    from wish.window import EDITOR_TAB, WishWindow

    original = EditorBinding._size_roster
    EditorBinding._size_roster = _patched_size_roster(SHAPES[shape])
    try:
        win = WishWindow(save, maps={},
                          session=Session(find=lambda pref=None: None),
                          tab=EDITOR_TAB)
    finally:
        EditorBinding._size_roster = original

    from PyQt6.QtCore import Qt
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.show()
    floor = win.minimumSizeHint()
    win.resize(floor)
    return win, floor


def main(out: pathlib.Path) -> int:
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication
    from test_windowslayout import _ordinary_party

    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    base = app.font()

    tmp = pathlib.Path(tempfile.mkdtemp())
    save = _ordinary_party(tmp)

    rows = []
    try:
        for extra in (0, 6):
            bigger = QFont(base)
            bigger.setPointSizeF(base.pointSizeF() + extra)
            app.setFont(bigger)
            for shape in ("today", "scroll", "pin", "round"):
                win, floor = _build(save, shape)
                app.processEvents()
                path = out / f"roster-{shape}-plus{extra}.png"
                win.grab().save(str(path))
                rows.append((shape, extra, floor.width(), floor.height(), path))
                win.close()
    finally:
        app.setFont(base)

    print(f"{'shape':<8} {'+font':<6} {'width':<7} {'height':<7} path")
    for shape, extra, w, h, path in rows:
        print(f"{shape:<8} +{extra:<5} {w:<7} {h:<7} {path}")
    return 0


if __name__ == "__main__":
    # `argparse` before anything imports Qt: `tests/test_toolhelp.py` requires
    # it of every tool that constructs a `QApplication`, because `--help` or a
    # mistyped argument reaching one would put a window on Donald's screen
    # while he is working. `main` does the Qt import itself, so nothing here
    # touches it until the arguments are known good.
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "out", nargs="?", default="work/issue474", type=pathlib.Path,
        help="directory to write the pictures into (default: work/issue474)")
    raise SystemExit(main(parser.parse_args().out))
