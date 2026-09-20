#!/usr/bin/env python3
"""Photograph the character editor at a chosen UI font and divider position.

`tools/gui/shotwindow.py` draws the window at its minimum size and cannot move a
splitter, and the whole of #97 (The character editor tab gets taller as the UI font grows, so a large font stops the window fitting a 720-high screen)
is what the divider does.  This is that tool with two extra arguments: the
heights to ask the editor's divider for, and the window size.

    tools/gui/editorshotdivider.py OUT.png --font +16 --rows 700 1
    tools/gui/editorshotdivider.py OUT.png --size 1366 768

`--font` is points added to the base UI font.  The picture carries a caption
with the font, the minimum size, the drawn size and the divider heights.  Runs
offscreen on a synthetic save (`tests/gamedata.synthetic_save`), so it needs
no game disks and opens no window.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))          # `gamedata.synthetic_save`


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out")
    ap.add_argument("--font", type=float, default=0.0)
    ap.add_argument("--rows", type=int, nargs=2, default=None,
                    help="heights to ask the divider for, top then bottom")
    ap.add_argument("--size", type=int, nargs=2, default=(1366, 768))
    args = ap.parse_args(argv)

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.pop("XDG_SESSION_TYPE", None)
    os.environ["GDK_BACKEND"] = "x11"
    cfg = tempfile.TemporaryDirectory(prefix="wish-shots-")
    for n in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        os.environ[n] = cfg.name

    from gamedata import synthetic_save
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication, QSplitter

    from tools.gui.shotwindow import caption, floor_of
    from wish.session import Session
    from wish.window import EDITOR_TAB, WishWindow

    app = QApplication.instance() or QApplication(["shots"])
    base = app.font()
    bigger = QFont(base)
    bigger.setPointSizeF(base.pointSizeF() + args.font)
    app.setFont(bigger)

    tmp = tempfile.TemporaryDirectory()
    win = WishWindow(str(synthetic_save(tmp.name)), maps={}, tab=EDITOR_TAB,
                     session=Session(find=lambda pref=None: None))
    win.show()
    app.processEvents()
    floor = floor_of(win)
    win.resize(max(args.size[0], floor.width()), max(args.size[1], floor.height()))
    app.processEvents()
    split = win.findChild(QSplitter, "editor_split")
    rows = "no divider"
    if split is not None:
        if args.rows:
            split.setSizes(list(args.rows))
            app.processEvents()
        rows = "/".join(str(h) for h in split.sizes())
    line = (f"editor  |  UI font {bigger.pointSizeF():g}pt  |  "
            f"floor {floor.width()}x{floor.height()}  |  "
            f"drawn {win.width()}x{win.height()}  |  rows {rows}")
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    caption(win.grab().toImage(), line, None).save(str(out))
    print(f"{out}  {line}")
    win.session.close()
    win.hide()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
