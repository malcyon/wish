"""Turn `automap.icons` path data into something Qt can paint.

Kept apart from `icons.py` so the table stays importable with no display, and
apart from the widgets so the map and the roster draw the same glyph the same
way. One `QPainterPath` is built per icon and cached: the paths are static, and
building one per paint would parse twelve of them sixty times a second.

**Winding fill, not the Qt default.** `QPainterPath` fills odd-even; SVG fills
non-zero. `location-dot`'s counter and `hood`'s face are subpaths wound the
other way, and under odd-even they come out solid -- which is exactly the blob
the icon was chosen to avoid.

**One icon is a character, not a path** -- `icons.TEXT_GLYPHS`, the Encounter
note's U+2694. A glyph has no 640 box to scale from and its advance is nothing
like its ink, so it is measured and fitted to the box the paths are drawn in.
That is what keeps it the same visual size as the note beside it; what it
cannot keep is the drawing, which is the platform's.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPixmap,
)

from . import icons

_CACHE: dict[str, QPainterPath] = {}
#: `(character, pixel size) -> (font, ink rectangle)`. Measuring a glyph is a
#: shaping run, and the map repaints on every poll.
_TEXT_CACHE: dict[tuple[str, int], tuple[QFont, object]] = {}


def painter_path(name: str) -> QPainterPath:
    """The icon in its own 640x640 box."""
    cached = _CACHE.get(name)
    if cached is not None:
        return cached
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    for cmd in icons.commands(name):
        if cmd[0] == "M":
            path.moveTo(cmd[1], cmd[2])
        elif cmd[0] == "L":
            path.lineTo(cmd[1], cmd[2])
        elif cmd[0] == "C":
            path.cubicTo(QPointF(cmd[1], cmd[2]), QPointF(cmd[3], cmd[4]),
                         QPointF(cmd[5], cmd[6]))
        else:
            path.closeSubpath()
    _CACHE[name] = path
    return path


def _fitted(ch: str, size: float):
    """The font and ink rectangle for one character at one box size."""
    key = (ch, int(size))
    cached = _TEXT_CACHE.get(key)
    if cached is not None:
        return cached
    font = QFont()
    font.setPixelSize(max(6, int(size)))
    ink = QFontMetricsF(font).tightBoundingRect(ch)
    _TEXT_CACHE[key] = (font, ink)
    return font, ink


def draw_text_glyph(p: QPainter, ch: str, x: float, y: float, size: float,
                    colour) -> None:
    """Draw one character to fill the `size` box at `(x, y)`.

    Fitted by its **ink**, not its advance: U+2694 in DejaVu Sans is 9x10 of
    ink inside an 11.6 advance at 13px, and drawing it on the baseline like
    text would put it half out of the cell and two pixels smaller than the
    Font Awesome note beside it.
    """
    font, ink = _fitted(ch, size)
    if ink.width() <= 0 or ink.height() <= 0:
        return
    scale = size / max(ink.width(), ink.height())
    p.save()
    p.setFont(font)
    p.setPen(colour)
    p.translate(x + (size - ink.width() * scale) / 2,
                y + (size - ink.height() * scale) / 2)
    p.scale(scale, scale)
    p.drawText(QPointF(-ink.x(), -ink.y()), ch)
    p.restore()


def draw_icon(p: QPainter, name: str, x: float, y: float, size: float,
              colour) -> None:
    """Fill `name` into the `size` box whose top-left corner is `(x, y)`."""
    text = icons.TEXT_GLYPHS.get(name)
    if text is not None:
        draw_text_glyph(p, text, x, y, size, colour)
        return
    p.save()
    p.translate(x, y)
    p.scale(size / icons.BOX, size / icons.BOX)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colour)
    p.drawPath(painter_path(name))
    p.restore()


def icon_pixmap(name: str, size: int, colour) -> QPixmap:
    """The icon as a pixmap, for a `QIcon` in a list or on a button.

    Drawn at the device pixel ratio the application is running at, so a note
    icon in the list is as sharp as the one on the map.
    """
    ratio = QGuiApplication.instance().devicePixelRatio() \
        if QGuiApplication.instance() else 1.0
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_icon(p, name, 0, 0, size, colour)
    p.end()
    return pixmap
