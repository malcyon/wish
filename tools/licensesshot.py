#!/usr/bin/env python3
"""Photograph Help > Licenses offscreen, at a chosen UI font size.

    tools/licensesshot.py [--out DIR]

Builds `wish.licenses.dialog()` at the base font and at six points more,
writes `licenses-0pt.png` and `licenses-+6pt.png` into DIR (default
the `licensesshot` scratch directory), and prints the size the dialog was shown at, its
`sizeHint` and its `minimumSizeHint`, which is what a caption on the picture
cannot say.  `+6` measures here about like Windows' base font.

Runs offscreen: it drops `WAYLAND_DISPLAY` and `XDG_SESSION_TYPE` and forces
`QT_QPA_PLATFORM=offscreen` before it creates the application, so nothing
opens on the desktop.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from tools import scratch  # noqa: E402
from wish import licenses  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(scratch.scratch_dir("licensesshot")),
                    help="where the PNGs go")
    args = ap.parse_args(argv)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.pop("XDG_SESSION_TYPE", None)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    app = QApplication([])
    base = app.font().pointSizeF()
    for bump in (0, 6):
        f = app.font()
        f.setPointSizeF(base + bump)
        app.setFont(f)
        box = licenses.dialog()
        box.show()
        app.processEvents()
        size = box.size()
        hint = box.sizeHint()
        floor = box.minimumSizeHint()
        path = out / f"licenses-{'+' if bump else ''}{bump}pt.png"
        box.grab().save(str(path))
        print(f"{bump:+d}pt base={base + bump:.1f}  "
              f"shown={size.width()}x{size.height()}"
              f"  sizeHint={hint.width()}x{hint.height()}"
              f"  minimumSizeHint={floor.width()}x{floor.height()}  -> {path}")
        box.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
