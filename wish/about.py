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

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QGuiApplication, QImage, QPixmap
from PyQt6.QtWidgets import QMainWindow, QMenu, QMessageBox

from goldbox.assets import asset_path

from . import __version__

#: The artist's own file, committed rather than left under `work/`. Resolved
#: through `goldbox.assets`, which is what finds it in a frozen build; built
#: from `__file__`, as it was, the Windows package drew no picture at all --
#: `#351 (The Windows build shows no logo in About and a black square on the
#: taskbar, because the artist's SVGs are not in the package)`.
#:
#: **His PNG export, not his vector, and this is not a preference.** The five
#: glowing nodes at the star's points are `<circle>` elements filled from
#: radial gradients, and only the first carries its own colour stops: the
#: other four are defined by `xlink:href="#radial-gradient"`, inheriting the
#: stops and overriding the position. That is ordinary SVG and **Qt's SVG
#: module does not implement it**, so four of the five nodes resolve to
#: nothing and are painted as nothing. Donald saw one point where the artist
#: drew five, in a Windows build on 2026-09-06, and the same comparison run
#: on Linux reproduces it from the committed vector.
#:
#: It is the second time Qt has rendered this artist's work incompletely --
#: `ui/appicon.py` draws the taskbar icon from his PNG for the same class of
#: reason, the mark's hairline rings -- and the rule both follow is the one
#: Donald gave: *"We should faithfully reproduce the artist's image exactly
#: as he intended it."* His raster is what he intended; our renderer is what
#: falls short of it.
#:
#: The vector stays committed. It is the source, it is what a future Qt or a
#: different renderer would draw correctly, and `tests/test_appicon.py`
#: pins both files' hashes.
PICTURE_ASSET = asset_path("assets", "logo", "combo-mark-color-500.png")

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


def _picture(size: int) -> QPixmap:
    """The combo mark at `size` logical pixels, scaled from the artist's own
    500-pixel export at the display's own ratio -- `ui.appicon.image` does
    the same for the taskbar icon, and for the same reason: a 2x display
    asked for `size` device pixels gets a soft picture.

    **Scaled, and nothing else.** 500 is larger than any size this dialog
    asks for, even at a 2x ratio, so this only ever shrinks his drawing --
    which is the whole of what we may do to it. `PICTURE_ASSET`'s note says
    why it is his raster rather than his vector."""
    ratio = (QGuiApplication.instance().devicePixelRatio()
             if QGuiApplication.instance() else 1.0)
    device = int(size * ratio)
    image = QImage(str(PICTURE_ASSET))
    image = image.scaled(device, device, Qt.AspectRatioMode.KeepAspectRatio,
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
