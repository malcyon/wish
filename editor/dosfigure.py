"""A DOS Pool of Radiance, Curse or Silver Blades character's combat figure, as the ICON screen draws it.

The art and the box behind it are read from the player's own DOS game folder
when a party opens (`goldbox/dos_icons.py` has the rules and the sixteen
colours); nothing here holds any of them.
"""

from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass

from PyQt6.QtCore import QRunnable, QThreadPool

from goldbox import dos_icons as art

from .amigafigure import Loaded
from .iconwidget import Figure

_log = logging.getLogger(__name__)


@dataclass
class FigureArt:
    """One title's heads, bodies and box, and the colours its ICON screen shows."""

    game: art.GameArt
    title: str
    palette: tuple[tuple[int, int, int], ...]

    def figure(self, native) -> Figure | None:
        """`native`'s figure, or None when its blocks are not in the folder."""
        head, body = native.get("icon_head"), native.get("icon_body")
        size = native.get("size")
        try:
            poses = art.compose(self.game.heads, self.game.bodies, head, body,
                                size, bytes(native.get("icon_colours")),
                                self.title)
            shown = tuple(
                tuple(tuple(self.palette[v] for v in row)
                      for row in art.on_frame(
                          art.frame_for(self.game, n, self.title), pose))
                for n, pose in enumerate(poses))
        except Exception as exc:
            _log.debug("no figure for head %s body %s size %s: %s",
                       head, body, size, exc)
            return None
        return Figure(shown, self.palette[0])


class _Job(QRunnable):
    def __init__(self, serial: int, folders, title: str, carrier: Loaded):
        super().__init__()
        self._serial, self._folders = serial, list(folders)
        self._title, self._carrier = title, carrier

    def run(self) -> None:
        try:
            found = load(self._folders, self._title)
        except Exception as exc:
            _log.debug("the figure art load failed: %s", exc)
            found = None
        try:
            self._carrier.done.emit(self._serial, found)
        except RuntimeError:
            _log.debug("the window closed before the figure art arrived")


def start(serial: int, folders, title: str, carrier: Loaded) -> None:
    """Run :func:`load` on a worker thread and emit `carrier.done(serial, art)`
    when it ends; `art` is None when nothing was found.

    Reading and decoding three `.DAX` files takes long enough that the window
    does not wait for it.
    """
    QThreadPool.globalInstance().start(_Job(serial, folders, title, carrier))


def load(folders, title: str) -> FigureArt | None:
    """The figure art off the first game folder that holds all of it, or None."""
    for folder in folders:
        try:
            return FigureArt(art.read_game(pathlib.Path(folder)), title,
                             art.icon_palette(title))
        except Exception as exc:
            _log.debug("%s holds no figure art: %s", folder, exc)
    return None
