#!/usr/bin/env python3
"""Draw the combat map's square as a letter over a miniature health bar, so
`#345` can be decided by looking at it.

Donald settled the shape on 2026-09-06 -- *"Change the hit point number in
the square to a miniature health bar. Put a letter above it to indicate who
the square belongs to"* -- and nobody had drawn one. This draws it, in the
canvas's own colours and at the cells the canvas actually paints: 12 px at
the window's minimum, 30 px at the size it asks for, 66 px at 1400 x 900,
and 20 and 40 between. Nothing in `automap/` changes; the square is drawn
here, through one function, and `automap/window.py` takes whichever look he
picks afterwards.

    tools/combatbarsheet.py                    # everything, under work/reports/345/bars/
    tools/combatbarsheet.py --out work/x/      # somewhere else

What comes out:

* `sheet.png` -- the three candidate looks side by side, one block each, a
  row per cell size and a column per case: a party member at full, half,
  nearly dead and zero; a monster labelled `DF` (the longest label under the
  two-character table) at the same; the gold helpless fill; a square whose
  occupant cannot be read; and `7LDF`, the four-character label the table
  replaced, so it is on the record why it was replaced.
* `closeup.png` -- the 12 and 20 px rows of every look magnified four times,
  because at true size the question is whether it can be read and at four
  times it is what was actually drawn.
* `canvas-<size>-<look>.png` -- the real `CombatCanvas` drawing the synthetic
  arena with the same function in place of its hit-point number, at the
  window's minimum, its hint and 1400 x 900, so the picture is the program
  and not a diagram of it.

The three looks differ in the things a reader actually sees differently, and
in nothing else:

* **paper** -- a paper-white bar on the square's own fill, with the empty
  part of the track drawn as a faint outline, so an empty bar is still
  visibly a bar. A combatant at zero shows the outline and nothing in it.
* **signal** -- the bar coloured by how much is left, green to amber to red,
  on a dark track. What is left is a colour before it is a length.
* **bare** -- the paper bar and nothing else: no track, no outline. A
  combatant at zero has nothing under its letter.

The font is sized to the room: the largest bold sans whose capitals fit
between the top of the square and the bar, and whose width fits inside the
square. The pixel size each label ends up at is printed and written into the
sheet's captions, because *"maybe lower the font size if it doesn't all
fit"* is a direction and the size at which a letter stops being readable is
a measurement he needs.

Runs offscreen; nothing here opens a window. The output is our own drawing
of our own colours and holds none of the game's art, but it goes under
`work/` all the same, because a screenshot is a run's output.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))
sys.path.insert(0, str(TOOLS.parent / "tests"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import QApplication  # noqa: E402

from automap import combat  # noqa: E402
from automap.render import Label  # noqa: E402
from automap.target import MemoryTarget  # noqa: E402
from automap.window import (  # noqa: E402
    COMBATANT_FILL,
    FADED,
    FOE,
    HP_INK,
    INK,
    LATTICE,
    PAPER,
    CombatCanvas,
)

#: The cells the canvas paints, smallest to largest. 12 is `combat.CELL_MIN`,
#: the window's minimum; 30 is what `cell_for` gives every fight seen so far;
#: 66 is what a 1400 x 900 window leaves for the synthetic arena.
CELLS = (12, 20, 30, 40, 66)

LOOKS = ("paper", "signal", "bare")

#: The bar coloured by what is left, for the `signal` look. Light shades,
#: because they sit on the party's green and the enemy's red and a bar the
#: colour of its own square is no bar at all.
SIGNAL_HIGH = QColor("#9be7a8")
SIGNAL_MID = QColor("#f3cf5a")
SIGNAL_LOW = QColor("#ff8c7a")
TRACK = QColor(22, 32, 43, 110)         # INK, thinned
TRACK_OUTLINE = QColor(251, 252, 253, 130)  # PAPER, thinned


@dataclasses.dataclass(frozen=True)
class Square:
    """One case on the sheet: who the square belongs to and how hurt."""

    caption: str
    text: str
    kind: str           # a `Combatant.kind`: party, enemy, helpless, -dim
    hp: int | None
    hp_max: int | None
    ready: bool = False


CASES = (
    Square("party, full", "B", "party", 11, 11, ready=True),
    Square("party, half", "B", "party", 6, 11),
    Square("party, nearly dead", "B", "party", 1, 11),
    Square("party, zero", "B", "party-dim", 0, 11),
    Square("monster, full", "DF", "enemy", 30, 30, ready=True),
    Square("monster, half", "DF", "enemy", 15, 30),
    Square("monster, nearly dead", "DF", "enemy", 2, 30),
    Square("monster, dead", "DF", "enemy-dim", 0, 30),
    Square("helpless, half", "DF", "helpless", 15, 30),
    Square("unreadable", "?", "enemy", None, None),
    Square("four letters", "7LDF", "enemy", 30, 30),
)


def fraction(hp: int | None, hp_max: int | None) -> float | None:
    """How much of the bar is filled, 0 to 1, or None when there is nothing
    to draw it from. A combatant carrying more than its maximum -- which the
    game allows -- fills the bar and no more."""
    if hp is None or not hp_max:
        return None
    return max(0.0, min(1.0, hp / hp_max))


def geometry(cell: int) -> tuple[int, int, int]:
    """`(inset, bar_height, gap)` for a cell: how far the bar sits in from the
    square's edge, how tall it is, and the room left between it and the
    letter. Two pixels of bar at 12 px, nine at 66."""
    inset = 1 if cell < 20 else 2
    bar_h = max(2, round(cell * 0.13))
    gap = 1 if cell < 20 else 2
    return inset, bar_h, gap


def fit_font(text: str, width: float, height: float) -> tuple[QFont, float]:
    """The largest bold sans whose capitals stand `height` tall at most and
    whose `text` runs `width` wide at most, with the pixel size it landed on.

    Sized in pixels rather than points, because a cell is a number of
    pixels and the same cell must get the same letter on every machine.
    Never below 4 px, at which point nothing is a letter any more and the
    sheet should show that rather than hide it.
    """
    size = max(4, int(height * 1.5))
    while size > 4:
        font = QFont("sans")
        font.setPixelSize(size)
        font.setWeight(QFont.Weight.Bold)
        fm = QFontMetricsF(font)
        if fm.capHeight() <= height and fm.horizontalAdvance(text) <= width:
            return font, size
        size -= 1
    font = QFont("sans")
    font.setPixelSize(size)
    font.setWeight(QFont.Weight.Bold)
    return font, size


def draw_square(p: QPainter, left: float, top: float, cell: int,
                square: Square, look: str) -> int:
    """One combatant's square, exactly as `CombatCanvas._draw` fills it and
    then the letter over the bar. Returns the letter's pixel size."""
    base = square.kind.removesuffix("-dim")
    dim = square.kind.endswith("-dim")
    colour = QColor(COMBATANT_FILL.get(base, FOE))
    if dim:
        colour.setAlpha(70)
    p.setPen(QPen(INK, 1))
    p.setBrush(colour)
    p.drawRect(QRectF(left + 1, top + 1, cell - 2, cell - 2))
    if square.ready and not dim:
        p.setPen(QPen(INK, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(left - 1, top - 1, cell + 2, cell + 2))
    p.setBrush(Qt.BrushStyle.NoBrush)

    ink_kind = "hp-dim" if dim else "hp-ink" if base == "helpless" else "hp"
    ink = HP_INK.get(ink_kind, PAPER)
    return draw_letter_over_bar(p, left, top, cell, square.text, ink,
                                fraction(square.hp, square.hp_max), look, dim)


def draw_letter_over_bar(p: QPainter, left: float, top: float, cell: int,
                         text: str, ink: QColor, filled: float | None,
                         look: str, dim: bool) -> int:
    """The letter and the bar, on a square already filled. What
    `CombatCanvas._draw` would do in place of its number."""
    inset, bar_h, gap = geometry(cell)
    bar_w = cell - 2 - 2 * inset
    bar_x = left + 1 + inset
    bar_y = top + cell - 1 - inset - bar_h

    # The letter, in whatever room is above the bar.
    room_top = top + 1 + (1 if cell < 20 else 2)
    room_h = bar_y - gap - room_top
    font, px = fit_font(text, cell - 2 - 2 * inset, room_h)
    fm = QFontMetricsF(font)
    x = left + cell / 2 - fm.horizontalAdvance(text) / 2
    baseline = room_top + (room_h + fm.capHeight()) / 2
    p.setFont(font)
    p.setPen(QPen(ink))
    p.drawText(QPointF(x, baseline), text)

    if filled is None:
        # Nothing to draw a bar from: the letter says `?` and the square says
        # nothing about health, rather than drawing an empty bar that would
        # read as dead.
        return px
    fill_w = round(bar_w * filled)
    p.setPen(Qt.PenStyle.NoPen)
    if look == "paper":
        p.setBrush(FADED if dim else TRACK_OUTLINE)
        p.setPen(QPen(FADED if dim else TRACK_OUTLINE, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(bar_x + 0.5, bar_y + 0.5, bar_w - 1, bar_h - 1))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(FADED if dim else ink)
        if fill_w:
            p.drawRect(QRectF(bar_x, bar_y, fill_w, bar_h))
    elif look == "signal":
        p.setBrush(TRACK)
        p.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h))
        if filled > 2 / 3:
            shade = SIGNAL_HIGH
        elif filled > 1 / 3:
            shade = SIGNAL_MID
        else:
            shade = SIGNAL_LOW
        p.setBrush(FADED if dim else shade)
        if fill_w:
            p.drawRect(QRectF(bar_x, bar_y, fill_w, bar_h))
    else:  # bare
        p.setBrush(FADED if dim else ink)
        if fill_w:
            p.drawRect(QRectF(bar_x, bar_y, fill_w, bar_h))
    p.setBrush(Qt.BrushStyle.NoBrush)
    return px


# ---------------------------------------------------------------- the sheet

CAPTION_PT = 8
GUTTER = 14
LEFT_MARGIN = 200
HEAD = 26


def caption_font(pt: int = CAPTION_PT) -> QFont:
    return QFont("sans", pt)


def draw_look(look: str, sizes: dict[int, dict[str, int]]) -> QImage:
    """One block: a row per cell, a column per case, captions down the left
    and along the top. Records the pixel size every label got in `sizes`."""
    col_w = max(CELLS) + GUTTER
    width = LEFT_MARGIN + len(CASES) * col_w + GUTTER
    height = HEAD + 40 + sum(c + 2 * GUTTER for c in CELLS)
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(PAPER)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    p.setPen(QPen(INK))
    p.setFont(QFont("sans", 11, QFont.Weight.Bold))
    p.drawText(QPointF(GUTTER, 18), f"{look}")
    p.setFont(caption_font())
    p.save()
    for i, case in enumerate(CASES):
        # Column headings, one word per line so they fit above a 66 px cell.
        cx = LEFT_MARGIN + i * col_w
        for j, word in enumerate(case.caption.split(", ")):
            p.drawText(QPointF(cx, HEAD + 12 + j * 11), word)
    p.restore()

    y = HEAD + 40
    for cell in CELLS:
        y += GUTTER
        got = sizes.setdefault(cell, {})
        for i, case in enumerate(CASES):
            cx = LEFT_MARGIN + i * col_w
            px = draw_square(p, cx, y, cell, case, look)
            got[case.text] = px
        p.setPen(QPen(INK))
        p.setFont(caption_font())
        p.drawText(QPointF(GUTTER, y + 10), f"{cell} px cell")
        line = "  ".join(f"{t}:{px}px" for t, px in got.items()
                         if t in ("B", "DF", "7LDF"))
        p.drawText(QPointF(GUTTER, y + 22), line)
        y += cell + GUTTER
    p.end()
    return img


def side_by_side(images: list[QImage], gap: int = 24) -> QImage:
    w = sum(i.width() for i in images) + gap * (len(images) - 1)
    h = max(i.height() for i in images)
    out = QImage(w, h, QImage.Format.Format_ARGB32)
    out.fill(PAPER)
    p = QPainter(out)
    x = 0
    for img in images:
        p.drawImage(x, 0, img)
        x += img.width()
        if x < w:
            p.setPen(QPen(LATTICE, 1))
            p.drawLine(x + gap // 2, 0, x + gap // 2, h)
        x += gap
    p.end()
    return out


def stacked(images: list[QImage], gap: int = 24) -> QImage:
    w = max(i.width() for i in images)
    h = sum(i.height() for i in images) + gap * (len(images) - 1)
    out = QImage(w, h, QImage.Format.Format_ARGB32)
    out.fill(PAPER)
    p = QPainter(out)
    y = 0
    for img in images:
        p.drawImage(0, y, img)
        y += img.height() + gap
    p.end()
    return out


def closeup(look: str, zoom: int = 4) -> QImage:
    """The 12 and 20 px rows at `zoom` times, nearest-neighbour, so every
    pixel that was drawn is a `zoom`-pixel block and nothing is smoothed."""
    small = [c for c in CELLS if c <= 20]
    col_w = max(small) + 6
    width = len(CASES) * col_w + 6
    height = sum(c + 6 for c in small) + 6
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(PAPER)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    y = 6
    for cell in small:
        for i, case in enumerate(CASES):
            draw_square(p, 6 + i * col_w, y, cell, case, look)
        y += cell + 6
    p.end()
    big = img.scaled(img.width() * zoom, img.height() * zoom,
                     Qt.AspectRatioMode.IgnoreAspectRatio,
                     Qt.TransformationMode.FastTransformation)
    labelled = QImage(big.width(), big.height() + 24,
                      QImage.Format.Format_ARGB32)
    labelled.fill(PAPER)
    p = QPainter(labelled)
    p.setPen(QPen(INK))
    p.setFont(QFont("sans", 11, QFont.Weight.Bold))
    p.drawText(QPointF(8, 17), f"{look}: 12 px and 20 px rows at {zoom}x")
    p.drawImage(0, 24, big)
    p.end()
    return labelled


# ---------------------------------------------------------------- the canvas

class BarCanvas(CombatCanvas):
    """The real canvas, drawing the letter over the bar wherever it would
    have drawn the hit-point number. `labels` is index -> text."""

    def __init__(self, look: str, labels: dict[int, str], parent=None):
        super().__init__(parent)
        self.look = look
        self.labels = labels
        self.sizes: dict[str, int] = {}

    def _draw(self, p: QPainter, prim) -> None:
        if not isinstance(prim, Label):
            super()._draw(p, prim)
            return
        cell = self.drawn_cell
        square = combat.square_at(prim.x, prim.y, self.box, cell,
                                  combat.MARGIN)
        who = self.battle.at(*square) if square else None
        if who is None:
            return
        text = self.labels.get(who.index, who.name[:1] or "?")
        ink = HP_INK.get(prim.kind, PAPER)
        left, top = prim.x - cell / 2, prim.y - cell / 2
        px = draw_letter_over_bar(p, left, top, cell, text, ink,
                                  fraction(who.hp, who.hp_max), self.look,
                                  who.dimmed)
        self.sizes[text] = px


#: Who stands where in the arena shot: `(index, x, y, hp, hp_max, label)`.
#: Index 0 is the roster's one party member, BRUTUS; 8 upward are monsters,
#: which the synthetic arena gives records from the same save.
ARENA = (
    (0, 25, 13, 11, 11, "B"),
    (8, 30, 13, 5, 5, "O"),
    (9, 31, 13, 8, 16, "DF"),
    (10, 30, 14, 1, 12, "GL"),
    (11, 32, 12, 0, 9, "G"),
    (12, 29, 15, 20, 20, "DF"),
    (13, 33, 14, 3, 30, "T"),
)


def arena_battle():
    from gamedata import synthetic_arena

    fighters = tuple((i, x, y) for i, x, y, *_ in ARENA)
    battle = combat.read_battle(MemoryTarget(synthetic_arena(fighters)))
    wanted = {i: (hp, hp_max) for i, _, _, hp, hp_max, _ in ARENA}
    fixed = tuple(dataclasses.replace(c, hp=wanted[c.index][0],
                                      hp_max=wanted[c.index][1])
                  if c.index in wanted else c
                  for c in battle.combatants)
    return dataclasses.replace(battle, combatants=fixed)


def canvas_shots(app, out: pathlib.Path, look: str, battle) -> list[str]:
    labels = {i: text for i, _, _, _, _, text in ARENA}
    lines = []
    for name, size in (("min", None), ("hint", "hint"),
                       ("big", QSize(1400, 900))):
        canvas = BarCanvas(look, labels)
        canvas.show_battle(battle)
        canvas.resize(canvas.minimumSize() if size is None
                      else canvas.sizeHint() if size == "hint" else size)
        app.processEvents()
        img = canvas.grab().toImage()
        # Keep the part with the fight in it; the arena is mostly empty.
        cell = canvas.drawn_cell
        x0, y0, _, _ = canvas.box
        xs = [x for _, x, _, *_ in ARENA]
        ys = [y for _, _, y, *_ in ARENA]
        crop = QRectF(combat.MARGIN + (min(xs) - x0 - 2) * cell,
                      combat.MARGIN + (min(ys) - y0 - 2) * cell,
                      (max(xs) - min(xs) + 5) * cell,
                      (max(ys) - min(ys) + 5) * cell).toRect()
        crop = crop.intersected(img.rect())
        path = out / f"canvas-{name}-{look}.png"
        shot = img.copy(crop)
        shot.save(str(path))
        if name == "min":
            # The minimum is the picture that decides anything, and at true
            # size it is a thumbnail; keep a four-times copy beside it.
            shot.scaled(shot.width() * 4, shot.height() * 4,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation
                        ).save(str(out / f"canvas-{name}-{look}-4x.png"))
        lines.append(f"{path}: drawn cell {cell} px, letters "
                     + ", ".join(f"{t} {px}px"
                                 for t, px in sorted(canvas.sizes.items())))
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Draw the combat square as a letter over a health bar, "
                    "three ways, at every cell the canvas paints.")
    ap.add_argument("--out", default="work/reports/345/bars", metavar="DIR",
                    help="where the PNGs go (default: %(default)s)")
    ap.add_argument("--no-canvas", action="store_true",
                    help="skip the real-canvas shots (no fixtures needed)")
    args = ap.parse_args(argv)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])

    sizes: dict[int, dict[str, int]] = {}
    blocks = []
    for look in LOOKS:
        img = draw_look(look, sizes)
        img.save(str(out / f"sheet-{look}.png"))
        blocks.append(img)
    side_by_side(blocks).save(str(out / "sheet.png"))
    stacked([closeup(look) for look in LOOKS]).save(str(out / "closeup.png"))
    print(f"Wrote {out / 'sheet.png'} and {out / 'closeup.png'}")
    print()
    print("Letter pixel size by cell (the largest bold sans whose capitals "
          "fit above the bar and whose width fits the square):")
    print(f"  {'cell':>5}  " + "  ".join(f"{t:>5}" for t in ("B", "DF", "7LDF", "?")))
    for cell, got in sorted(sizes.items()):
        inset, bar_h, gap = geometry(cell)
        print(f"  {cell:>5}  "
              + "  ".join(f"{got.get(t, 0):>4}px" for t in ("B", "DF", "7LDF", "?"))
              + f"   bar {bar_h} px tall, {inset} px in from the edge")

    if not args.no_canvas:
        battle = arena_battle()
        print()
        for look in LOOKS:
            for line in canvas_shots(app, out, look, battle):
                print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
