#!/usr/bin/env python3
"""Open the real program with points added to the interface font.

    .venv/bin/python tools/bigfont.py 6
    .venv/bin/python tools/bigfont.py 10 --tab map

The number is points added to the font the desktop gives Qt. `CLAUDE.md`
records that **+6 here measures about like Windows' base font**, and that +10
is the largest worth caring about -- 9pt base here, so the range a person
uses is 9pt to 19pt.

**Why a window and not a screenshot.** `tools/shotwindow.py` photographs the
window offscreen at a chosen font and captions its floor, which is the right
tool for a measurement. It cannot drag a splitter, resize the window, or show
what happens when somebody tries -- and that is the whole of what a font
question usually turns out to be. `#97 (The character editor's page cannot be
made shorter than the screen at a large interface font)` was argued for a
session from numbers and settled in a minute by pulling the window's bottom
edge.

The font has to be on the `QApplication` **before** the window is built: half
of what the window's floor is made of is measured while its widgets are being
constructed, and `wish.window.run` reuses an existing instance rather than
making its own.

**This puts a window on the screen**, which is the point, so it is a tool for
a person at the machine and never for an unattended agent -- see `CLAUDE.md`,
"Nothing an agent runs may put a window on Donald's screen".
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PyQt6.QtGui import QFont  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

TABS = {"map": 0, "editor": 1}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("points", nargs="?", type=float, default=6.0,
                    help="points to add to the interface font (try 6, then 10)")
    ap.add_argument("--tab", choices=sorted(TABS), default="editor",
                    help="which tab to open on")
    ap.add_argument("--save", default=None, help="a save disk to open with")
    args = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])
    font = QFont(app.font())
    font.setPointSizeF(font.pointSizeF() + args.points)
    app.setFont(font)

    from wish.window import run  # noqa: E402  -- after the font is set

    print(f"UI font {font.pointSizeF():g}pt (+{args.points:g}). "
          f"Try making the window shorter than it wants to be.")
    return run(args.save, tab=TABS[args.tab])


if __name__ == "__main__":
    raise SystemExit(main())
