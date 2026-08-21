"""Turn `automap.icons` path data into something Qt can paint.

Kept apart from `icons.py` so the table stays importable with no display, and
apart from the widgets so the map and the roster draw the same glyph the same
way. One `QPainterPath` is built per icon and cached: the paths are static, and
building one per paint would parse twelve of them sixty times a second.

**Winding fill, not the Qt default.** `QPainterPath` fills odd-even; SVG fills
non-zero. `location-dot`'s counter and `mask`'s eyes are subpaths wound the
other way, and under odd-even they come out solid -- which is exactly the blob
the icon was chosen to avoid.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QGuiApplication, QPainter, QPainterPath, QPixmap

from . import icons

_CACHE: dict[str, QPainterPath] = {}


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


def draw_icon(p: QPainter, name: str, x: float, y: float, size: float,
              colour) -> None:
    """Fill `name` into the `size` box whose top-left corner is `(x, y)`."""
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
