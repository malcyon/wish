#!/usr/bin/env python3
"""What part of the Level up button a player can actually see and press -- a
probe for `#168 (A character ready to level loses the Level up button, even
with nothing running)`.

    .venv/bin/python tools/levelupstubhit.py

Prints the button's width, its visible region and its state, then which widget
a hit test finds under it every four pixels. Offscreen; writes nothing.
"""
from __future__ import annotations

import pathlib
import sys

from PyQt6.QtCore import QPoint

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import rostercardvariants as O  # noqa: E402


def main(argv=None) -> int:
    O.parser(__doc__).parse_args(argv)
    app = O.application()
    win, roster = O.build(app, badges=0, readied=(), levelling=True)
    btn = roster.cards[0].level_up
    print("button width", btn.width(),
          "| visibleRegion", btn.visibleRegion().boundingRect(),
          "| enabled", btn.isEnabled(), "| visible", btn.isVisible())
    for x in range(0, btn.width(), 4):
        p = btn.mapTo(win, QPoint(x, btn.height() // 2))
        u = win.childAt(p)
        print(f"  x={x:2d} -> {type(u).__name__}/"
              f"{u.objectName() if u else '-'}")
    O.close(app, win)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
