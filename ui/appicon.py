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
committed SVG instead: `assets/logo/mark.svg`, the artist's file, verbatim,
beside his own PNG exports of it at 80, 150, 200 and 500.

**Below 500 pixels the icon is his PNG scaled down, not his SVG rendered.**
`image()` has the reason and the measurement; the short form is that Qt's
SVG renderer drops the mark's hairline rings at a taskbar size and the
artist's exporter did not. Every size is still made on its own terms from
the smallest delivered file no smaller than it, the way `tools/genicons.py`
always insisted on -- so a 16 is never a squeezed 256 of ours.

**The assets are not modified.** Resizing a delivered file into the sizes a
taskbar or a `.ico` wants is placement, not art; nothing here moves a point
of the artist's drawing or a pixel of his export.

**This mark carries no CC BY obligation.** It is Donald's own commissioned
work, not lifted from a licensed set, so there is no attribution to discharge
here the way `pointy-hat`'s belonged to Lorc at game-icons.net -- see
`ui/icons.py`'s own docstring, where that credit still lives for the icons
still drawn from it.
"""

from __future__ import annotations

import pathlib

from PyQt6.QtCore import QRectF, Qt
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

#: The artist's own PNG exports of the same mark, by side, byte for byte as
#: he delivered them (`Marks/Color/Color Mark NxN.png`, 2026-08-31). Four
#: separate literal calls rather than a loop, because `tests/test_assets.py`
#: reads `asset_path(...)` calls out of the source to check each file is in
#: `wish.spec`'s `datas`, and a path assembled from a variable is one it
#: cannot see.
RASTERS: dict[int, pathlib.Path] = {
    80: asset_path("assets", "logo", "mark-80.png"),
    150: asset_path("assets", "logo", "mark-150.png"),
    200: asset_path("assets", "logo", "mark-200.png"),
    500: asset_path("assets", "logo", "mark-500.png"),
}

#: One renderer, reused: `QSvgRenderer` parses the file once and renders it at
#: any size afterwards, and re-parsing a 1.8 MB file per icon size would be
#: the wrong place to spend that cost.
_renderer: QSvgRenderer | None = None

#: The PNGs, decoded once each.
_rasters: dict[int, QImage] = {}


def _svg() -> QSvgRenderer:
    global _renderer
    if _renderer is None or not _renderer.isValid():
        _renderer = QSvgRenderer(str(ASSET))
    return _renderer


def _raster(side: int) -> QImage:
    if side not in _rasters:
        _rasters[side] = QImage(str(RASTERS[side])).convertToFormat(
            QImage.Format.Format_ARGB32_Premultiplied)
    return _rasters[side]


def raster_side(size: int) -> int | None:
    """Which delivered PNG a `size` square is scaled from: the smallest no
    smaller than it, so a raster is only ever scaled down. `None` above the
    largest, where the SVG is the only source there is."""
    return next((side for side in sorted(RASTERS) if side >= size), None)


def source(size: int) -> pathlib.Path:
    """The file the icon at `size` is made from."""
    side = raster_side(size)
    return ASSET if side is None else RASTERS[side]


def render_svg(size: int) -> QImage:
    """The SVG rendered whole into a `size` square. What `image` uses above
    the largest PNG, and kept callable on its own so a test can show what
    the renderer does to the rings at a taskbar size."""
    out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _svg().render(p, QRectF(0, 0, size, size))
    p.end()
    return out


def image(size: int) -> QImage:
    """The icon at `size`: the artist's smallest PNG no smaller than it,
    scaled down whole; the SVG only above his largest PNG.

    **Do not simplify this back to rendering the SVG at every size.** It was
    that, and it looked right in a checkout and wrong on a Windows taskbar:
    the mark's two rings are embedded hairline bitmaps in the artist's SVG,
    and Qt's renderer drops most of each below 48 pixels, leaving scattered
    dots where a circle should be. His own PNG export kept them as a faint
    circle. Measured on 2026-09-06 around the outer ring at 24 pixels, the
    scaled 80 lights 72 of 72 sample points and the SVG render lights 20;
    `tests/test_appicon.py::test_the_ring_is_a_circle_at_the_taskbar_sizes`
    keeps both figures. A taskbar button is 24 logical pixels, 32 at 150 %
    scaling, so those two sizes are the whole reason for the rule, and the
    rule is applied at every size so no size is a downscale of a render
    that lost something. Donald chose it off the comparison sheet as row B
    (`docs/132-logo.md` §7).

    A raster that is missing decodes to a null `QImage`, and scaling one
    gives an empty square -- the black-square failure `#351 (The Windows
    build shows no logo in About and a black square on the taskbar, because
    the artist's SVGs are not in the package)` was about. The SVG stands in
    for it here so a player still gets a mark; `tests/test_assets.py` is
    what keeps the PNGs in the package, so the stand-in should never run.
    """
    side = raster_side(size)
    if side is None or _raster(side).isNull():
        return render_svg(size)
    return _raster(side).scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)


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
#: present as their own square, each scaled from a delivered file.
WINDOW_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def app_icon() -> QIcon:
    """The window and taskbar icon, one pixmap per size."""
    icon = QIcon()
    for size in WINDOW_SIZES:
        # Device pixels, ratio 1: these are the entries Qt chooses between, and
        # a ratio on them would make Qt read each as a smaller logical size.
        icon.addPixmap(QPixmap.fromImage(image(size)))
    return icon
