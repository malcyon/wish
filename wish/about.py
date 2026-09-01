"""Help > About: the version, so a bug report can name the build it came from.

Its own file because `window.py` is thin on purpose, and because the version
string is the one thing here that has to be right.

Built by hand rather than with `QMessageBox.about`, which paints the platform's
information icon and takes no picture of its own. `box()` returns the dialog
without showing it, so a test can read what it says without a modal window.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMainWindow, QMenu, QMessageBox

from ui.appicon import pixmap

from . import __version__

#: How big the picture is beside three lines of text. 64 logical pixels is the
#: size Qt's own about boxes use for an application icon; `appicon.pixmap`
#: draws it at the display's ratio.
PICTURE = 64

TEXT = f"""<h3>Wish {__version__}</h3>
<p>A character editor and live automapper for Pool of Radiance (Commodore 64).</p>
<p>GPL-3.0-or-later.</p>
<p>The application icon and the interface icons are from
<a href="https://game-icons.net/">Game-icons.net</a>, licensed CC BY 3.0. The
artists are credited under <b>Help &gt; Licenses</b>.</p>"""


def box(parent: QMainWindow | None = None) -> QMessageBox:
    """The dialog, built and not shown."""
    dialog = QMessageBox(parent)
    dialog.setWindowTitle("About Wish")
    dialog.setTextFormat(Qt.TextFormat.RichText)
    dialog.setText(TEXT)
    dialog.setIconPixmap(pixmap(PICTURE))
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
