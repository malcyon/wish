"""Help > About: the version, so a bug report can name the build it came from.

Its own file because `window.py` is thin on purpose, and because the version
string is the one thing here that has to be right.

Built by hand rather than with `QMessageBox.about`, which paints the platform's
information icon and takes no picture of its own. `box()` returns the dialog
without showing it, so a test can read what it says without a modal window.

**The picture is the colour combo mark, not the application icon.** The
taskbar/dock icon is `ui.appicon` -- the pentacle alone, cropped in tight for a
small square. About has room for the fuller mark: the pentacle with the WISH
lettering inside it, `assets/logo/combo-mark-color.svg`, on the same near-black
ground the artist drew it on. That ground is what lets this dialog skip the
theme detection a transparent mark would have needed -- the combo carries its
own background, so it cannot vanish the way black-on-transparent art would on
a dark-themed dialog. `docs/132-logo.md` §0 has the reasoning; Donald chose
this colourway once that was in front of him.
"""

from __future__ import annotations

import pathlib

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QAction, QGuiApplication, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QMainWindow, QMenu, QMessageBox

from . import __version__

#: The artist's own file, committed rather than left under `work/`.
PICTURE_ASSET = (pathlib.Path(__file__).resolve().parent.parent
                  / "assets" / "logo" / "combo-mark-color.svg")

#: How big the picture is beside three lines of text. Was 64 -- Qt's own about
#: boxes use that for a bare application icon -- and Donald asked for it
#: doubled once the combo mark, with its own lettering, was the picture:
#: *"Use the color combo with the black background, but double its size."*
#:
#: Doubled again on 2026-09-05, for a reason about the drawing rather than
#: about the layout: *"The circle around the star is broken up and does not
#: look clear at all."*  The ring is a thin stroke in the vector, and at 128
#: it lands under a pixel wide, so antialiasing leaves it as a dotted line
#: rather than a circle.  At 256 the stroke has a whole pixel to sit in.
PICTURE = 256


#: How many times bigger than the target the mark is drawn before it is
#: scaled down.
#:
#: **The two rings around the star are the only parts of the artist's file
#: that are not vector.** Each is an embedded PNG about 3,600 pixels square
#: carrying a single hairline -- 41 and 31 pixels of stroke, around 1% of the
#: image's width. Asked to put that straight into a 256-pixel box, Qt's SVG
#: renderer shrinks the bitmap fourteen times and the ring comes out uneven
#: rather than thin. `SmoothPixmapTransform` makes no difference to it.
#:
#: Drawing four times as large and letting `QImage.scaled` do the shrink
#: fixes it, because the reduction is then the image scaler's work rather
#: than the SVG renderer's. Donald, 2026-09-05: *"The circle around the star
#: is broken up and does not look clear at all."*
#:
#: This goes when the artist's file draws those two circles as circles.
OVERSAMPLE = 4


def _picture(size: int) -> QPixmap:
    """The combo mark at `size` logical pixels, rendered from the vector at
    the display's own ratio -- `ui.appicon.image` does the same for the
    taskbar icon, and for the same reason: a 2x display asked for `size`
    device pixels gets a soft picture.

    Drawn `OVERSAMPLE` times larger and scaled down, which is what keeps the
    two embedded rings continuous."""
    ratio = (QGuiApplication.instance().devicePixelRatio()
             if QGuiApplication.instance() else 1.0)
    device = int(size * ratio)
    big = device * OVERSAMPLE
    image = QImage(big, big, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    QSvgRenderer(str(PICTURE_ASSET)).render(painter, QRectF(0, 0, big, big))
    painter.end()
    image = image.scaled(device, device, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap

#: Donald's own wording, 2026-09-05, replacing two lines that were mine.
#:
#: `GPL-3.0-or-later` is an SPDX identifier -- the machine-readable form that
#: belongs in `pyproject.toml`, where it still is. It was never meant to be
#: read by a person, and he said so: *"is 'GPL-3.0-or-later.' a common
#: phrasing in licensing? It looks really awkward."*
#:
#: The Game-icons.net attribution came out on his instruction -- *"I think
#: having the icon licenses under help->licenses is enough"* -- and the
#: artists are still credited there, which is where the CC BY attribution
#: lives.
TEXT = f"""<h3>Wish {__version__}</h3>
<p>A character editor and live automapper for Pool of Radiance (Commodore 64).</p>
<p>Wish is licensed under GPLv3.</p>
<p>Written by Donald Morton.</p>
<p>Wish logo and logo mark designed by Dustin Geddy Parker.</p>"""


def box(parent: QMainWindow | None = None) -> QMessageBox:
    """The dialog, built and not shown."""
    dialog = QMessageBox(parent)
    dialog.setWindowTitle("About Wish")
    dialog.setTextFormat(Qt.TextFormat.RichText)
    dialog.setText(TEXT)
    dialog.setIconPixmap(_picture(PICTURE))
    dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
    return dialog


def about(parent: QMainWindow | None = None) -> None:
    box(parent).exec()


def install(window: QMainWindow) -> QMenu:
    """Add the Help menu to a window's menu bar, and hand it back.

    Returned rather than dropped so `window.py` can put Licenses beside About
    without reaching into the menu bar to find the menu again.
    """
    action = QAction("&About Wish", window)
    action.triggered.connect(lambda _checked=False: about(window))
    menu = window.menuBar().addMenu("&Help")
    menu.addAction(action)
    return menu
