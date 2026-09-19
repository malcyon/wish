#!/usr/bin/env python3
"""Measure the editor window's minimum width on Windows, at Windows' own font.

Runs **inside the Windows 11 VM**, not here -- `tools/gui/winwish.py` puts it there
and starts it. `tools/gui/rosterfloorshot.py` takes the same measurement on Linux
with the offscreen plugin; this one takes it on the real `windows` platform
plugin and the real `windows11` style, which is the only way the number means
anything about what a player meets.

Two parties, because `#474 (Raising the UI font grows the window's minimum
width with an ordinary party open, which is the defect #41 removed for the
widest one)` is exactly the gap between them: `_ordinary_party` from
`tests/test_windowslayout.py`, and `gamedata.synthetic_party`, the widest the
record and the title's tables allow.

It also writes the ordinary party's disk to `--save`, so `winwish.py start` has
something real to open the visible window on.

Measured on the guest, 2026-09-10, Windows 11 26100, Qt 6.11.0, Segoe UI 9pt,
96 DPI, 100% scaling: ordinary 976 at +0 and 1075 at +6; widest 1215 at +0 and
1216 at +10.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys
import tempfile


def main(root: pathlib.Path, save: pathlib.Path) -> int:
    # `tests/test_windowslayout.py` does `setdefault("QT_QPA_PLATFORM",
    # "offscreen")`, and offscreen on Windows draws Fusion with a fallback font
    # -- a number about neither platform. Claim the variable before importing
    # it, so the real Windows plugin and the real Windows style are measured.
    os.environ["QT_QPA_PLATFORM"] = os.environ.get("WISH_MEASURE_PLATFORM",
                                                   "windows")
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tests"))

    import gamedata
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication
    from test_windowslayout import _ordinary_party

    app = QApplication.instance() or QApplication([])
    base = app.font()
    screen = app.primaryScreen()
    print("platform:", app.platformName(), " style:", app.style().objectName())
    print("base font:", base.family(), base.pointSizeF(), "pt",
          " dpi:", screen.logicalDotsPerInch(),
          " devicePixelRatio:", screen.devicePixelRatio())
    print("screen:", screen.geometry().width(), "x", screen.geometry().height())

    tmp = pathlib.Path(tempfile.mkdtemp())
    ordinary = _ordinary_party(tmp)
    # Never overwrite it while the visible window has it open.
    if not save.exists():
        shutil.copyfile(ordinary, save)
    widest = gamedata.synthetic_save(tmp, "WIDEST.D64")
    print("ordinary:", save)
    print("widest:  ", widest)

    from wish.session import Session
    from wish.window import EDITOR_TAB, WishWindow

    rows = []
    for which, disk in (("ordinary", save), ("widest", widest)):
        for extra in (0, 3, 6, 10):
            bigger = QFont(base)
            bigger.setPointSizeF(base.pointSizeF() + extra)
            app.setFont(bigger)
            win = WishWindow(str(disk), maps={},
                             session=Session(find=lambda pref=None: None),
                             tab=EDITOR_TAB)
            # The window is measured, never shown: this runs in the guest's
            # own session 1, where a window really would appear on its screen.
            win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            win.show()
            app.processEvents()
            floor = win.minimumSizeHint()
            roster = win.editor._child("roster")
            rows.append((which, extra, floor.width(), floor.height(),
                         getattr(roster, "_natural", None),
                         roster.minimumWidth()))
            win.close()
    app.setFont(base)

    print()
    print(f"{'party':<9} {'+font':<6} {'min width':<10} {'min height':<11} "
          f"{'roster natural':<15} {'roster min'}")
    for which, extra, w, h, natural, rmin in rows:
        print(f"{which:<9} +{extra:<5} {w:<10} {h:<11} {str(natural):<15} {rmin}")
    return 0


if __name__ == "__main__":
    # `argparse` before anything imports Qt, the way `tests/test_toolhelp.py`
    # requires of every tool that constructs a `QApplication`.
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path,
                        default=pathlib.Path(r"C:\Wish\wish"),
                        help="the repository's root inside the guest")
    parser.add_argument("--save", type=pathlib.Path,
                        default=pathlib.Path(r"C:\Wish\ORDINARY.D64"),
                        help="where to leave the ordinary party's disk")
    got = parser.parse_args()
    raise SystemExit(main(got.root, got.save))
