#!/usr/bin/env python3
"""Count an icon's ink and its pieces at the size it is actually drawn at.

`docs/136-condition-badges.md` grades every condition badge as "pieces, ink"
at 13 px, and says the numbers come from "the same rig the rest of this file
uses" -- a rig that lived in a session and had to be rebuilt to add two rows
to that table on `#142 (The party effects line is computed every poll and
shown nowhere)`. This is that rig, kept.

The two numbers answer different questions and both matter:

* **ink** is how much of the glyph survives. `invisible` was dropped from the
  set at 55 -- a dashed outline whose dashes fall below a pixel long before
  13 px, so on a card it was a smudge rather than a badge.
* **pieces** is whether it survives as *one thing*. A glyph that comes apart
  is legible only as a general shape; `hat-wizard`'s brim stopped touching its
  cone at 13 px and it read as a shark's fin.

A pixel counts as ink when it is **at least half covered**, and pieces are
8-connected blobs of those pixels. Both thresholds are choices rather than
facts, and `docs/136-condition-badges.md` says where they are unkind: a glyph
drawn in fine strokes -- `eyelashes` -- loses most of its length to the 50%
rule while a human eye reads the antialiased blur as continuous. The picture
is the fairer judge; this is the number beside it.

    .venv/bin/python tools/inkcount.py mute snail
    .venv/bin/python tools/inkcount.py --size 26 --all
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

os.environ["QT_QPA_PLATFORM"] = os.environ.get("WISH_SHOT_PLATFORM",
                                               "offscreen")
if "WISH_SHOT_PLATFORM" not in os.environ:
    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.pop("XDG_SESSION_TYPE", None)
    os.environ["GDK_BACKEND"] = "x11"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PyQt6.QtGui import (  # noqa: E402
    QColor,
    QGuiApplication,
    QImage,
    QPainter,
)

from ui import icons  # noqa: E402
from ui.iconpaint import draw_icon  # noqa: E402

#: A pixel is ink when the fill covers at least this much of it. 128 of 255,
#: measured on the grey level of a black glyph on white.
HALF = 128


def inked(name: str, size: int) -> set[tuple[int, int]]:
    """The pixels of `name` at `size` that are at least half covered."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("white"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_icon(p, name, 0, 0, size, QColor("black"))
    p.end()
    return {(x, y) for y in range(size) for x in range(size)
            if QColor(image.pixel(x, y)).lightness() <= 255 - HALF}


def pieces(ink: set[tuple[int, int]]) -> int:
    """How many 8-connected blobs the ink comes apart into."""
    left, count = set(ink), 0
    while left:
        count += 1
        stack = [left.pop()]
        while stack:
            x, y = stack.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    at = (x + dx, y + dy)
                    if at in left:
                        left.discard(at)
                        stack.append(at)
    return count


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Count an icon's ink pixels and connected pieces.")
    ap.add_argument("names", nargs="*", help="icon names from ui/icons.py")
    ap.add_argument("--all", action="store_true",
                    help="every icon the program ships")
    ap.add_argument("--size", type=int, default=13, metavar="N",
                    help="the size to draw at (default: %(default)s, which is "
                         "`panel.ICON_SIZE` -- the roster card and the party "
                         "effects row)")
    args = ap.parse_args(argv[1:])

    names = sorted(icons.ICONS) if args.all else args.names
    if not names:
        ap.error("name an icon, or pass --all")
    unknown = [n for n in names if n not in icons.ICONS]
    if unknown:
        ap.error(f"not in ui/icons.py: {', '.join(unknown)}")

    app = QGuiApplication(["inkcount"])          # a QImage still wants one
    assert app is not None                       # and wants it kept alive
    print(f"{'icon':24} {'pieces':>6} {'ink':>5}   at {args.size}px")
    for name in names:
        ink = inked(name, args.size)
        print(f"{name:24} {pieces(ink):>6} {len(ink):>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
