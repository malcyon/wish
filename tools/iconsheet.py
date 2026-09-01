"""Render every icon the program ships at the sizes it is actually seen at.

`docs/109-icon-choices.md` was once a table of names. A table of names is how
`hat-wizard` got chosen and how it turned out to read as a shark's fin at
13 pixels. This draws the icons instead, through `ui.iconpaint` -- the same
code the map and the roster paint with -- so what comes out is what the program
would do, not an approximation of it.

The candidates are gone; what is left is the set that won, kept renderable so
the next change to a drawing is judged the same way the first one was.

Each row is one icon, shown three ways:

* **in a map cell**, at the three sizes the program actually draws at -- 13 in
  the notes list, 15 in the note editor's picker, and `render.py`'s `NOTE_SIZE`
  of 26 on the map itself -- in `NOTE` ink on graph paper with a wall against
  it, where `note_primitives` puts it;
* **on a roster card**, at the same three sizes, in `MUTED` beside the class
  text, which is where `panel.py`'s `IconRow` puts it;
* **magnified**, 13px at 8x and 26px at 4x with nearest-neighbour scaling, so
  the pixels are visible. This column is the one that decided, and the one a
  replacement has to survive: a glyph that is mush is mush here and merely
  small everywhere else.

The map used to draw at 13 and the 13px rule was written for it. It draws at 26
now, so the rule binds on the notes list and nowhere else -- see
`docs/109-icon-choices.md`.

    .venv/bin/python tools/iconsheet.py work/reports/icon-sheet.png
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QRectF, Qt  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
)

from ui import icons  # noqa: E402
from ui.iconpaint import draw_icon  # noqa: E402

# `panel.py` and `window.py`, copied rather than imported: importing them pulls
# in the whole widget stack for six colour names.
PAPER = QColor("#fbfcfd")
CARD = QColor("#ffffff")
LATTICE = QColor("#dbe3ec")
INK = QColor("#16202b")
MUTED = QColor("#5c6b7a")
NOTE = QColor("#b8601f")
RULE = QColor("#e7ecf2")

SIZES = (13, 15, 26)
CELL = 34                       # `render.py`'s map cell
INSET = 3                       # `render.py`'s NOTE_INSET

LABEL_W = 210
MAP_W = 42
CARD_W = 104
BIG_SMALL, BIG_MAP = 8, 4       # magnification factors
ROW_H = 26 * BIG_MAP + 12
GAP = 10


#: What ships. `(section, [(name, source, note), ...])`.
#: `test_the_sheet_only_names_icons_that_exist` fails the build if a name here
#: is not in `ui.icons`, so a renamed drawing breaks the build rather than
#: the sheet.
SHEET = [

    ("Note types", [
        ("crossed-swords", "U+2694", "encounter -- a font character, not a "
                                     "path: what it looks like is the "
                                     "platform's"),
        ("gem", "FA Free, regular", "treasure -- the one icon lifted from "
                                    "`regular/` rather than `solid/`"),
        ("user", "FA Free", "person"),
        ("door-open", "FA Free", "exit"),
        ("lock", "FA Free", "locked"),
        ("stairs", "FA Free", "stairs -- the level changes here"),
        ("triangle-exclamation", "FA Free", "danger"),
        ("location-dot", "FA Free", "a plain note, and the 64-unit counter "
                                    "the size floor is measured against"),
        ("check", "FA Free", "done"),
    ]),
    ("Toolbar -- 16px beside the button text", [
        ("folder-open", "FA Free", "open"),
        ("floppy-disk", "FA Free", "save, and save as"),
        ("eye", "FA Free", "preview changes"),
    ]),
    ("Roster and popover", [
        ("skull", "FA Free", "no longer drawn -- `death-skull` replaced it"),
        ("arrow-down-long", "FA Free",
         "no longer drawn -- `oppression` replaced it"),
        ("person-running", "FA Free",
         "no longer drawn -- `sparkling-sabre` replaced it"),
        ("trash-can", "FA Free", "delete this note"),
    ]),
    ("Condition badges -- game-icons.net, CC BY 3.0, Donald's choices", [
        ("death-skull", "sbed", "dead or dying"),
        ("oppression", "Lorc", "levels drained"),
        ("running-ninja", "Darkzaitzev", "hasted -- effect 39"),
        ("healing-shield", "Delapouite", "blessed -- effects 1 and 35"),
        ("embrassed-energy", "Lorc",
         "warded -- effects 8, 9, 17, 28, 41 and 89"),
        ("invisible", "Delapouite", "invisible -- effect 25"),
        ("strong", "Lorc", "strengthened -- effects 12 and 38"),
        ("sparkling-sabre", "Lorc", "quickfight -- the roster card's own row"),
    ]),
]


def _map_cell(p: QPainter, x: float, y: float, name: str, size: int) -> None:
    """The icon where `note_primitives` puts it: top-right, clear of a wall."""
    p.fillRect(QRectF(x, y, CELL, CELL), PAPER)
    p.setPen(QPen(LATTICE, 1))
    p.drawRect(QRectF(x + .5, y + .5, CELL - 1, CELL - 1))
    p.setPen(QPen(INK, 3))                      # a wall on the left, to weigh
    p.drawLine(int(x), int(y), int(x), int(y + CELL))
    draw_icon(p, name, x + CELL - INSET - size, y + INSET, size, NOTE)


def _card(p: QPainter, x: float, y: float, name: str, size: int) -> None:
    """The icon where `IconRow` puts it: left of the class text, in MUTED."""
    h = 24
    p.fillRect(QRectF(x, y, CARD_W - 6, h), CARD)
    p.setPen(QPen(LATTICE, 1))
    p.drawRect(QRectF(x + .5, y + .5, CARD_W - 7, h - 1))
    draw_icon(p, name, x + 6, y + (h - size) / 2, size, MUTED)
    font = QFont()
    font.setPointSize(8)
    p.setFont(font)
    p.setPen(QPen(MUTED))
    p.drawText(QRectF(x + size + 11, y, CARD_W - size - 18, h),
               int(Qt.AlignmentFlag.AlignVCenter), "Fighter  L5")


def _magnified(p: QPainter, x: float, y: float, name: str, size: int,
               factor: int) -> None:
    """The icon drawn at `size` and blown up without smoothing.

    Nearest-neighbour on purpose: the question is what the pixels do, and a
    smooth upscale answers a different one.
    """
    tile = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    tile.fill(PAPER)
    q = QPainter(tile)
    q.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_icon(q, name, 0, 0, size, NOTE)
    q.end()
    big = tile.scaled(size * factor, size * factor,
                      Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.FastTransformation)
    p.drawImage(int(x), int(y), big)
    p.setPen(QPen(LATTICE, 1))
    p.drawRect(QRectF(x - .5, y - .5, size * factor + 1, size * factor + 1))


def build() -> QImage:
    width = (LABEL_W + len(SIZES) * MAP_W + GAP + len(SIZES) * CARD_W + GAP
             + 13 * BIG_SMALL + GAP + 26 * BIG_MAP + 2 * GAP)
    rows = sum(len(items) for _, items in SHEET)
    height = 96 + rows * ROW_H + len(SHEET) * 40 + 40

    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#f2f4f7"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    title = QFont()
    title.setPointSize(13)
    title.setBold(True)
    p.setFont(title)
    p.setPen(QPen(INK))
    p.drawText(GAP, 26, "Icons in use -- docs/109-icon-choices.md")
    small = QFont()
    small.setPointSize(8)
    p.setFont(small)
    p.setPen(QPen(MUTED))
    p.drawText(GAP, 44, "The 13px rule -- one connected silhouette, every "
                        "feature at least about 64 units in the 640 box -- "
                        "now binds on the notes list only. The map draws at "
                        "26.")
    p.drawText(GAP, 58, "Map cells are NOTE ink on graph paper with a wall "
                        "against them; cards are MUTED beside the class text. "
                        "This is the chosen set.")

    x0 = GAP
    map_x = x0 + LABEL_W
    card_x = map_x + len(SIZES) * MAP_W + GAP
    big_x = card_x + len(SIZES) * CARD_W + GAP

    head = QFont()
    head.setPointSize(8)
    head.setBold(True)
    p.setFont(head)
    p.setPen(QPen(INK))
    p.drawText(x0, 82, "icon")
    for i, size in enumerate(SIZES):
        p.drawText(map_x + i * MAP_W, 82, f"map {size}")
        p.drawText(card_x + i * CARD_W, 82, f"card {size}")
    p.drawText(big_x, 82, f"13px x{BIG_SMALL}")
    p.drawText(big_x + 13 * BIG_SMALL + GAP, 82, f"26px x{BIG_MAP}")

    y = 96
    for section, items in SHEET:
        p.setFont(title)
        p.setPen(QPen(INK))
        p.drawText(x0, y + 22, section)
        y += 34
        p.setPen(QPen(RULE, 1))
        p.drawLine(x0, y - 6, width - GAP, y - 6)

        for name, source, why in items:
            assert name in icons.NAMES, name
            p.setFont(head)
            p.setPen(QPen(INK))
            p.drawText(x0, y + 16, name)
            p.setFont(small)
            p.setPen(QPen(MUTED))
            p.drawText(x0, y + 32, source)
            p.drawText(QRectF(x0, y + 36, LABEL_W - 8, 40),
                       int(Qt.TextFlag.TextWordWrap), why)

            for i, size in enumerate(SIZES):
                _map_cell(p, map_x + i * MAP_W, y + 4, name, size)
                _card(p, card_x + i * CARD_W, y + 4, name, size)
            _magnified(p, big_x, y + 4, name, 13, BIG_SMALL)
            _magnified(p, big_x + 13 * BIG_SMALL + GAP, y + 4, name, 26,
                       BIG_MAP)

            y += ROW_H
            p.setPen(QPen(RULE, 1))
            p.drawLine(x0, y - 4, width - GAP, y - 4)
        y += 6

    p.end()
    return image


def main(argv: list[str]) -> int:
    out = argv[1] if len(argv) > 1 else "work/reports/icon-sheet.png"
    app = QGuiApplication(["iconsheet"])     # a QImage still wants one
    assert app is not None                  # and wants it kept alive
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    image = build()
    if not image.save(out):
        print(f"could not write {out}", file=sys.stderr)
        return 1
    print(f"{out}  {image.width()}x{image.height()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
