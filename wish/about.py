"""Help > About: the version, so a bug report can name the build it came from.

Its own file because `window.py` is thin on purpose, and because the version
string is the one thing here that has to be right.
"""

from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMainWindow, QMessageBox

from . import __version__

TEXT = f"""<h3>wish {__version__}</h3>
<p>A character editor and live automapper for Pool of Radiance (Commodore 64).</p>
<p>GPL-3.0-or-later. The game's own data stays on the player's disks.</p>
<p>Some icons from <a href="https://fontawesome.com">Font Awesome Free 7.3.1</a>
by Fonticons, Inc., licensed CC BY 4.0.</p>"""


def about(parent: QMainWindow | None = None) -> None:
    QMessageBox.about(parent, "About wish", TEXT)


def install(window: QMainWindow) -> None:
    """Add the Help menu to a window's menu bar."""
    action = QAction("&About wish", window)
    action.triggered.connect(lambda _checked=False: about(window))
    window.menuBar().addMenu("&Help").addAction(action)
