"""The character editor.

    python -m editor [SAVE.D64]

The form lives in `editor/character.ui`. Open it in Qt Designer
(`/usr/lib/qt6/bin/designer editor/character.ui`), rearrange it, save, and
restart -- the layout is recompiled automatically.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pool of Radiance character editor")
    ap.add_argument("save", nargs="?", help="a .D64 to open")
    ap.add_argument("--game-disk", help="a POOL*.D64, for item names and icons")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    from tools.genui import ensure_current
    if ensure_current():
        print("character.ui changed; recompiled the form")

    from PyQt6.QtWidgets import QApplication

    from .window import EditorWindow

    app = QApplication(sys.argv[:1])
    win = EditorWindow(args.save, args.game_disk)
    win.resize(1875, 1030)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
