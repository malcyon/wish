"""The application's own icon, for now: game-icons.net's `pointy-hat`, on a
filled tile.

**This is a stand-in, not the chosen icon.** Donald: *"I am paying an artist
to create an app logo and icon. In the meantime, please use `pointy-hat`."*
It comes off, and `hat-wizard` or whatever replaces it goes back, the moment
the artist delivers -- which is why it is its own commit, separate from the
note icons and the toolbar (`#167`), so it can be reverted on its own.

Beside `iconpaint.py` because it is the same job -- `icons.py` path data turned
into pixels -- and because putting it here means the taskbar icon, the About
picture and the `.ico` PyInstaller embeds are all one drawing. There is no
raster to keep in step with the glyph, so they cannot drift.

**Why a tile and not a bare silhouette.** `docs/132-logo.md` §2: a shape on
transparency is grey pixels against a taskbar whose colour we do not know, and
it vanishes on half of them. The tile supplies the ground.

**Why the hat is painted light rather than cut out.** Cutting it out leaves the
taskbar showing through the hat, so on a dark desktop a dark tile would carry a
dark hole and there would be nothing to see. Filling it with paper is the same
silhouette with a ground guaranteed on both sides of every edge, and it still
reads in monochrome, which Windows sometimes wants.

**The path data is drawn exactly as Lorc drew it, at every size.** Colouring
it and placing it on the tile is composition; moving a point would be
redrawing somebody else's art, which this project does not do.

**Scaled from the hat's own ink, not from a box constant.** `pointy-hat` sits
on game-icons.net's 512 canvas rather than `hat-wizard`'s 640, and a
different shape besides -- but `paint()` below never reads either box
constant: it fits `glyph().boundingRect()` to the tile, so the scaling is
correct for any glyph's own ink regardless of the canvas it was drawn on.
Checked at 16, 32 and 256px; the hat reads at all three.

The path data is game-icons.net, CC BY 3.0, attributed in the README and in
Help > About, which is where the obligation for a Windows resource has to
live -- an `.ico` has nowhere to carry one.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPixmap,
)

from .iconpaint import painter_path

NAME = "pointy-hat"

#: Indigo rather than the interface's near-black `#16202b`: a near-black tile
#: on Windows' dark taskbar is a tile nobody can see, and the whole point of
#: having one is that it is visible against an unknown ground.
TILE = QColor("#2b3a67")
GLYPH = QColor("#f7f9fb")

#: Fractions of the side. The corner radius is the shell's own idiom; the inset
#: is what stops the brim touching the edge at 16 px, where one pixel of margin
#: is all there is.
RADIUS = 0.18
INSET = 0.10


def glyph() -> QPainterPath:
    """The hat, as Lorc drew it."""
    return painter_path(NAME)


def paint(p: QPainter, size: float, x: float = 0.0, y: float = 0.0) -> None:
    """The whole icon -- tile and hat -- into a `size` box at `(x, y)`."""
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(x, y, size, size), size * RADIUS, size * RADIUS)
    p.setPen(Qt.PenStyle.NoPen)
    p.fillPath(tile, TILE)

    # Centred on the hat's own ink rather than on its canvas, which it does
    # not fill.
    hat = glyph()
    ink = hat.boundingRect()
    inner = size * (1 - 2 * INSET)
    scale = min(inner / ink.width(), inner / ink.height())
    p.save()
    p.translate(x + (size - ink.width() * scale) / 2,
                y + (size - ink.height() * scale) / 2)
    p.scale(scale, scale)
    p.translate(-ink.x(), -ink.y())
    p.setBrush(GLYPH)
    p.drawPath(hat)
    p.restore()


def image(size: int) -> QImage:
    """One square of the icon, drawn at its own size rather than scaled down.

    Every size is rendered from the vector. Windows asks for 16, 20, 24, 32,
    40, 48 and 64 at the various display scalings and bilinearly scales
    whatever it cannot find; a 256 squeezed to 16 is mush.
    """
    out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint(p, size)
    p.end()
    return out


def pixmap(size: int) -> QPixmap:
    """The icon for a widget, drawn at the ratio the application is running at.

    `iconpaint.icon_pixmap` does the same for the small glyphs, and for the
    same reason: on a 2x display a 64-logical picture asked for as 64 device
    pixels is a soft one.
    """
    ratio = (QGuiApplication.instance().devicePixelRatio()
             if QGuiApplication.instance() else 1.0)
    out = QPixmap.fromImage(image(int(size * ratio)))
    out.setDevicePixelRatio(ratio)
    return out


#: What `setWindowIcon` gets. Qt picks the nearest entry and scales the rest,
#: so the sizes the title bar, Alt-Tab and the taskbar button ask for are all
#: present as their own drawing.
WINDOW_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def app_icon() -> QIcon:
    """The window and taskbar icon, one hand-drawn pixmap per size."""
    icon = QIcon()
    for size in WINDOW_SIZES:
        # Device pixels, ratio 1: these are the entries Qt chooses between, and
        # a ratio on them would make Qt read each as a smaller logical size.
        icon.addPixmap(QPixmap.fromImage(image(size)))
    return icon
