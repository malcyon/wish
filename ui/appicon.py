"""The application's own icon: the artist's mark, on its own ground.

**This is the commissioned mark, not a stand-in.** `docs/132-logo.md` records
the two stand-ins that came before it -- Font Awesome's `hat-wizard`, then
game-icons.net's `pointy-hat` -- each chosen only because no artist existed
yet. One delivered on 2026-09-05: a gold pentacle inside a ring, on a dark
square it already carries as its own ground. Donald chose this over a
transparent glyph and over a light/dark pair, on the grounds that a square
that supplies its own background reads the same on a light desktop, a dark
one and in a macOS dock -- nothing has to guess what is behind it.

**The drawing stopped being generated, and that is a deliberate trade.**
Every icon before this one was painted at run time from `ui/icons.py`'s path
data, specifically so no raster could drift from the glyph the program
painted elsewhere. There is nowhere else in the program that paints this
mark, so that property bought nothing here, and the mark is a fixed,
committed SVG instead: `assets/logo/mark.svg`, the artist's file, verbatim.
`image()` below renders it at whatever size is asked for, straight off the
vector, the same way `tools/genicons.py` always insisted on for every other
size -- so a 256 is never a downscale of anything and neither is a 16.

**The asset is not modified.** Composing it into the sizes a taskbar or a
`.ico` wants is placement, not art; nothing here moves a point of the artist's
drawing.

**This mark carries no CC BY obligation.** It is Donald's own commissioned
work, not lifted from a licensed set, so there is no attribution to discharge
here the way `pointy-hat`'s belonged to Lorc at game-icons.net -- see
`ui/icons.py`'s own docstring, where that credit still lives for the icons
still drawn from it.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from goldbox.assets import asset_path

#: The artist's own file, committed rather than left under `work/`, which is
#: gitignored and has been lost twice. Resolved through `goldbox.assets` so
#: a frozen build finds it under `sys._MEIPASS` -- a path built from
#: `__file__` here is what shipped a black square on the Windows taskbar,
#: `#351 (The Windows build shows no logo in About and a black square on the
#: taskbar, because the artist's SVGs are not in the package)`.
ASSET = asset_path("assets", "logo", "mark.svg")

#: One renderer, reused: `QSvgRenderer` parses the file once and renders it at
#: any size afterwards, and re-parsing a 1.8 MB file per icon size would be
#: the wrong place to spend that cost.
_renderer: QSvgRenderer | None = None


def _svg() -> QSvgRenderer:
    global _renderer
    if _renderer is None or not _renderer.isValid():
        _renderer = QSvgRenderer(str(ASSET))
    return _renderer


def image(size: int) -> QImage:
    """The icon at `size`, rendered from the vector rather than scaled down.

    Every size Windows or a Linux icon theme asks for is rendered here on its
    own terms; a 256 squeezed to 16 is mush, and the artist's file is a vector
    for exactly this reason.
    """
    out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _svg().render(p, QRectF(0, 0, size, size))
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
