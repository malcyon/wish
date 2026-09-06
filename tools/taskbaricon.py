"""Draw the taskbar-icon choices side by side, at the sizes Windows draws.

    .venv/bin/python tools/taskbaricon.py work/reports/taskbar-choices.png

Donald, 2026-09-06, of the artist's mark on a Windows taskbar: *"It is too
small for the color image. I am open to suggestions."* And then: *"I don't
really understand your choices. please offer me an image with comparisons."*
This is that image. One row per option, one column per size Windows asks a
`.ico` for -- 16, 20, 24, 32, 48 and 256 -- each shown at true size on a
light and a dark taskbar and then magnified beside it, because nobody can
judge a 16-pixel icon by squinting at it.

**Nothing here decides.** The mark is Dustin Geddy Parker's and the choice is
Donald's; the rows are labelled so he can answer with a letter.

**The artist's files are not modified.** Every row is rendered off
`assets/logo/mark.svg` or `assets/logo/combo-mark-color.svg` as committed,
by three kinds of placement: rendering the file at a size, rendering a
*window* of it (`QSvgRenderer.setViewBox`, a crop), and rendering it with
the two ring bitmaps left out (a layer switched off, the polygons untouched).
The one row that is not the artist's drawing says so in its label: a
pentagram drawn from five points, as a stand-in for what a hand-tuned small
glyph could look like, never as the glyph itself -- `.claude/rules/art.md`.

**Why the rings are the problem** is measured rather than argued.
`docs/132-logo.md` §5: the two rings are the only parts of the file that are
not vector -- embedded PNGs about 3,600 pixels square carrying a hairline
each. At 1080 the ring strokes are 4 pixels wide and the star's strokes 12;
at 16 those are 0.06 and 0.18 of a pixel, so the renderer blends both into
the ground and what is left is a faint smudge of gold where a star was.
"""

from __future__ import annotations

import math
import os
import pathlib
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QByteArray, QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
)
from PyQt6.QtSvg import QSvgRenderer  # noqa: E402

from ui import appicon  # noqa: E402

#: The sizes a Windows `.ico` is asked for -- `docs/132-logo.md` §1b -- minus
#: 40 and 64, which are 32 and 48 at a display scaling and add no new
#: judgement. 256 is Explorer's big view and the Properties sheet.
SIZES = (16, 20, 24, 32, 48, 256)

#: How much each size is blown up beside its true-size cell, chosen so every
#: magnified cell is about 192 pixels: 256 is shown at true size only.
MAGNIFY = {16: 12, 20: 9, 24: 8, 32: 6, 48: 4, 256: 1}

#: The artist's own two colours, read off the files: the ground the mark
#: carries and the gold of its strokes.
GROUND = QColor("#17140e")
GOLD = QColor("#ebb551")

#: A Windows 11 taskbar, light theme and dark theme, so each true-size cell
#: sits on what it will actually sit on.
TASKBAR_LIGHT = QColor("#eeeeee")
TASKBAR_DARK = QColor("#202020")

PAPER = QColor("#fbfcfd")
INK = QColor("#16202b")
MUTED = QColor("#5c6b7a")

MARK = appicon.ASSET
COMBO = MARK.parent / "combo-mark-color.svg"


# --- the drawings ----------------------------------------------------------


def _renderer(text: str) -> QSvgRenderer:
    renderer = QSvgRenderer(QByteArray(text.encode("utf-8")))
    if not renderer.isValid():
        raise RuntimeError("the SVG did not parse")
    return renderer


def _render(renderer: QSvgRenderer, size: int,
            window: QRectF | None = None) -> QImage:
    """`renderer` into a `size` square; `window` is the part of the file's
    1080-unit canvas to show, the whole of it when None."""
    if window is not None:
        renderer.setViewBox(window)
    out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return out


_IMAGE = re.compile(r"<image\b[^>]*?/>", re.S)


def mark_as_is(size: int) -> QImage:
    """A. The mark, rendered down -- exactly what `ui.appicon` does today."""
    return appicon.image(size)


def star_cropped(size: int) -> QImage:
    """B. The artist's star with the two ring bitmaps switched off, cropped to
    fill the square.

    The polygons and their glow are rendered as drawn; only the two `<image>`
    elements are left out of the document handed to the renderer, and the
    file on disk is untouched. The star's bounding box on the 1080 canvas is
    x 188..891, y 162..839 (measured off a render); the window is that box
    made square with a margin of 30 units.
    """
    text = _IMAGE.sub("", MARK.read_text(encoding="utf-8"))
    box = QRectF(188, 162, 703, 677)
    side = max(box.width(), box.height()) + 60
    window = QRectF(box.center().x() - side / 2, box.center().y() - side / 2,
                    side, side)
    return _render(_renderer(text), size, window)


def star_heavy(size: int) -> QImage:
    """C. A pentagram drawn from five points with strokes a tenth of the box
    wide, gold on the artist's ground.

    **Not the artist's drawing.** A stand-in for the shape a hand-tuned small
    glyph would take -- one silhouette, strokes that survive a pixel grid --
    drawn here so the sheet can show what that shape buys at 16 before
    anybody is asked to draw one.
    """
    out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(GROUND)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    radius = 0.42 * size
    # A pentagram's visual centre sits above its circumcircle's, since three
    # of the five points lie below the middle; the shift is the difference
    # between the top point and the bottom pair, halved.
    cx = size / 2
    cy = size / 2 + radius * (1 - math.cos(math.radians(36))) / 2
    points = [QPointF(cx + radius * math.sin(math.radians(72 * i)),
                      cy - radius * math.cos(math.radians(72 * i)))
              for i in range(5)]
    pen = QPen(GOLD, max(1.0, 0.1 * size))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    for i in range(5):
        painter.drawLine(points[i], points[(i + 2) % 5])
    painter.end()
    return out


def monogram(size: int) -> QImage:
    """D. The W of the artist's wordmark, on the artist's ground.

    Cropped out of `combo-mark-color.svg`: the document handed to the
    renderer is the file's own header, its ground rectangle and its lettering
    group, with the star and rings left out, and the window is the W's
    bounding box -- x 164..413, y 457..635 on the 1080 canvas, measured off
    a render of the lettering -- made square with a margin.
    """
    text = COMBO.read_text(encoding="utf-8")
    head = text[:text.index("<rect")]
    ground = re.search(r"<rect\b[^>]*?/>", text, re.S).group(0)
    letters = re.search(r'<g filter="url\(#outer-glow-2\)">.*?</g>',
                        text, re.S).group(0)
    box = QRectF(164, 457, 249, 178)
    side = max(box.width(), box.height()) * 1.3
    window = QRectF(box.center().x() - side / 2, box.center().y() - side / 2,
                    side, side)
    return _render(_renderer(head + ground + letters + "</svg>"), size,
                   window)


def two_drawings(small, size: int) -> QImage:
    """E and F. `small` below 32, the full mark from 32 up -- what a `.ico`
    is for, and what `packaging/geniconset.py` already does for macOS."""
    return small(size) if size < 32 else mark_as_is(size)


#: `(letter, title, what it is, drawing)`. The order is the order on the sheet.
OPTIONS = [
    ("A", "The mark as it is",
     "assets/logo/mark.svg rendered at each size -- what ships today",
     mark_as_is),
    ("B", "The star, rings off, cropped",
     "the artist's own star, the two ring bitmaps left out, filling the square",
     star_cropped),
    ("C", "A heavier star (a stand-in, not the artist's)",
     "five points, strokes a tenth of the box: the shape a hand-tuned glyph could take",
     star_heavy),
    ("D", "The W of the wordmark",
     "cropped from assets/logo/combo-mark-color.svg, on the artist's ground",
     monogram),
    ("E", "Two drawings: B below 32, A from 32",
     "a .ico can hold a different drawing per size; small sizes get the star",
     lambda size: two_drawings(star_cropped, size)),
    ("F", "Two drawings: D below 32, A from 32",
     "the same, with the W at the small sizes",
     lambda size: two_drawings(monogram, size)),
]


# --- the sheet -------------------------------------------------------------

LABEL_W = 400
GAP = 14
ROW_PAD = 26


def _magnified(image: QImage, factor: int) -> QImage:
    side = image.width() * factor
    return image.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation)


def sheet() -> QImage:
    columns = []       # (size, x, true-cell width, magnified width)
    x = LABEL_W
    for size in SIZES:
        true_w = size * 2 + 3 * 6 if size < 256 else 0
        mag_w = size * MAGNIFY[size]
        columns.append((size, x, true_w, mag_w))
        x += true_w + (GAP if true_w else 0) + mag_w + GAP * 2
    width = x
    header_h = 70
    row_h = 256 + ROW_PAD * 2 + 30
    height = header_h + row_h * len(OPTIONS) + 20

    out = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(PAPER)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    title, label, small = QFont(), QFont(), QFont()
    title.setPointSize(14)
    title.setBold(True)
    label.setPointSize(11)
    label.setBold(True)
    small.setPointSize(9)

    painter.setPen(INK)
    painter.setFont(title)
    painter.drawText(QRectF(GAP, 8, width, 30),
                     "Wish taskbar icon: six choices at the sizes Windows draws")
    painter.setFont(small)
    painter.setPen(MUTED)
    painter.drawText(QRectF(GAP, 36, width, 20),
                     "Each size: true size on a light and a dark taskbar, then "
                     "magnified. 256 is true size only.")
    for size, cx, true_w, mag_w in columns:
        painter.drawText(QRectF(cx, 52, true_w + GAP + mag_w, 16),
                         f"{size} px" + ("" if size < 256 else " (true size)"))

    for row, (letter, name, what, draw) in enumerate(OPTIONS):
        top = header_h + row * row_h
        painter.setPen(INK)
        painter.setFont(label)
        painter.drawText(QRectF(GAP, top + ROW_PAD, LABEL_W - GAP, 22),
                         f"{letter}.  {name}")
        painter.setFont(small)
        painter.setPen(MUTED)
        painter.drawText(QRectF(GAP, top + ROW_PAD + 26, LABEL_W - GAP * 2, 120),
                         int(Qt.TextFlag.TextWordWrap), what)
        for size, cx, true_w, mag_w in columns:
            image = draw(size)
            y = top + ROW_PAD
            if true_w:
                # True size, twice: on the light taskbar and on the dark one.
                painter.fillRect(QRectF(cx, y, true_w, size + 12), TASKBAR_LIGHT)
                painter.drawImage(QPointF(cx + 6, y + 6), image)
                painter.fillRect(QRectF(cx + size + 12, y, true_w - size - 12,
                                        size + 12), TASKBAR_DARK)
                painter.drawImage(QPointF(cx + size + 18, y + 6), image)
                mx = cx + true_w + GAP
            else:
                mx = cx
            painter.drawImage(QPointF(mx, y), _magnified(image, MAGNIFY[size]))
    painter.end()
    return out


def main(argv: list[str]) -> int:
    out = pathlib.Path(argv[1] if len(argv) > 1
                       else "work/reports/taskbar-choices.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication(["taskbaricon"])
    assert app is not None
    image = sheet()
    if not image.save(str(out)):
        raise RuntimeError(f"could not write {out}")
    print(f"{out}  {image.width()}x{image.height()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
