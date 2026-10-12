"""An Amiga Curse of the Azure Bonds or Secret of the Silver Blades character's combat figure, as the ICON screen draws it.

The art, the box behind it and the sixteen colours are read from the player's
own Amiga disks when a party opens (`goldbox/amiga_later_icons.py` has the
rules); nothing here holds any of them.
"""

from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass

from PyQt6.QtCore import QRunnable, QThreadPool

from goldbox import amiga_later_icons as art
from goldbox.amiga_adf import AmigaDisk

from .amigafigure import Loaded
from .iconwidget import Figure

_log = logging.getLogger(__name__)

#: The titles whose figures this module draws.
TITLES = frozenset(art.TITLES)


@dataclass
class FigureArt:
    """One title's heads, bodies, boxes, recolour tables and ICON palette."""

    art: art.LaterArt

    def figure(self, native) -> Figure | None:
        """`native`'s figure, or None when its blocks are not on the disks."""
        head, body = native.get("icon_head"), native.get("icon_body")
        size = native.get("size")
        try:
            shown = self.art.drawn(head, body, size,
                                   bytes(native.get("icon_colours")))
        except Exception as exc:
            _log.debug("no figure for head %s body %s size %s: %s",
                       head, body, size, exc)
            return None
        return Figure(shown, self.art.palette[0])


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

    Opening the `.adf` images of up to five folders and decoding two tile
    libraries takes as long as they are many, so the window does not wait for
    it.
    """
    QThreadPool.globalInstance().start(_Job(serial, folders, title, carrier))


def load(folders, title: str) -> FigureArt | None:
    """The figure art off the first folder whose `.adf` images hold all of it,
    or None."""
    for folder in folders:
        try:
            disks = _disks(pathlib.Path(folder))
            return FigureArt(art.read_art(title, art.disk_files(title, disks)))
        except Exception as exc:
            _log.debug("%s holds no figure art: %s", folder, exc)
    return None


def _disks(folder: pathlib.Path) -> list[AmigaDisk]:
    """Every readable `.adf` image in `folder`."""
    out = []
    for image in sorted(folder.iterdir()):
        if not image.is_file() or image.suffix.lower() != ".adf":
            continue
        try:
            disk = AmigaDisk.open(image)
            list(disk.walk())
        except Exception as exc:
            _log.debug("%s is not a readable disk: %s", image, exc)
            continue
        out.append(disk)
    return out
