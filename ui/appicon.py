"""The application's own icon: Font Awesome's `hat-wizard`, on a filled tile.

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

**The brim is a separate bar, and that is the whole difficulty.** Fonticons
draw the cone closing at y=464 and the brim as a rounded bar from y=512, so the
two never touch at any size -- which is why `docs/109-icon-choices.md` rejected
this glyph for the 13px map icons and why `wizard-hat` was drawn instead. As an
*application* icon the gap is the drawing rather than a fault: from 22 px up a
whole row of tile pixels survives between cone and bar and it reads as a hat
resting on a table. At 16 and 20 it does not -- the gap and the bar both land
on part-covered pixels and the icon is a fin over a grey smear -- so below
`CLOSE_BELOW` the bar is slid up until it meets the cone's foot and the
silhouette is one connected piece. `docs/132-logo.md` §6 has the sheet.

The path data is Font Awesome Free 7.3.1, CC BY 4.0, attributed in the README
and in Help > About, which is where the obligation for a Windows resource has
to live -- an `.ico` has nowhere to carry one. Sliding the brim is a change,
and saying so is part of the licence.
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

from . import icons
from .iconpaint import painter_path

NAME = "hat-wizard"

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

#: Read off the path data: the cone's last point is y=464.1 and the brim's bar
#: starts at y=512. A horizontal line anywhere between them separates the two,
#: and 488 is the middle of the gap.
GAP = QRectF(0.0, 488.0, float(icons.BOX), float(icons.BOX))
LIFT = 47.9

#: Below this the bar is slid up by `LIFT` so the hat is one mass. Measured on
#: the rasterised icon, not guessed: at 22 there is a row of pure tile between
#: cone and bar and at 24 there are two, so the gap reads as a gap; at 20 the
#: two nearest rows are both part-covered and at 16 the bar itself never
#: reaches full paper. 22 and up get the drawing as Fonticons drew it.
CLOSE_BELOW = 22


_CLOSED: dict[str, QPainterPath] = {}


def _closed() -> QPainterPath:
    """The same hat with its brim slid up against the cone's foot.

    Cut and translated rather than redrawn, so the small sizes are the same
    outline as the large ones and no coordinate here is invented. The boolean
    flattens the curves, which costs nothing at the two sizes that use it.
    """
    cached = _CLOSED.get(NAME)
    if cached is None:
        whole = painter_path(NAME)
        cut = QPainterPath()
        cut.addRect(GAP)
        cached = whole.subtracted(cut)
        cached.addPath(whole.intersected(cut).translated(0.0, -LIFT))
        _CLOSED[NAME] = cached
    return cached


def glyph(size: float) -> QPainterPath:
    """The drawing to use in a `size` box -- see `CLOSE_BELOW`."""
    return _closed() if size < CLOSE_BELOW else painter_path(NAME)


def paint(p: QPainter, size: float, x: float = 0.0, y: float = 0.0) -> None:
    """The whole icon -- tile and hat -- into a `size` box at `(x, y)`."""
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(x, y, size, size), size * RADIUS, size * RADIUS)
    p.setPen(Qt.PenStyle.NoPen)
    p.fillPath(tile, TILE)

    # Centred on the hat's own ink rather than on the 640 box, which it sits
    # high in -- and so the closed-up variant, 48 units shorter, is centred on
    # itself rather than left riding up.
    hat = glyph(size)
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
