"""An Amiga Pools of Darkness character's combat figure, as the ICON screen draws it.

The art, the boxes and the 32 colours are read from the player's own Amiga disks
when a party opens (`goldbox/amiga_pod_icons.py` has the rules); nothing here
holds any of them.
"""

from __future__ import annotations

import logging
import pathlib

from goldbox import amiga_pod
from goldbox import amiga_pod_icons as art

from . import amigafigure, amigalaterfigure
from .amigafigure import Loaded
from .iconwidget import Figure

_log = logging.getLogger(__name__)


class FigureArt(amigalaterfigure.FigureArt):
    """The heads, bodies, boxes, recolour tables and ICON palette of the title."""

    def figure(self, native) -> Figure | None:
        """The figure of a character record's bytes, or None when its blocks
        are not on the disks."""
        try:
            colours = amiga_pod.ICON_COLOURS
            return self.drawn(
                native[amiga_pod.ICON_HEAD], native[amiga_pod.ICON_BODY],
                native[amiga_pod.SIZE],
                bytes(native[colours:colours + amiga_pod.ICON_COLOUR_COUNT]))
        except (TypeError, IndexError) as exc:
            _log.debug("no figure for a record that is not a character: %s", exc)
            return None


def start(serial: int, folders, carrier: Loaded) -> None:
    """Load :func:`load`'s art on a worker thread and emit
    `carrier.done(serial, art)` when it ends; `art` is None when nothing was
    found.

    Opening the `.adf` images of up to five folders and decoding two tile
    libraries takes as long as they are many, so the window does not wait for
    it.
    """
    folders = list(folders)
    amigafigure.start(serial, lambda: load(folders), carrier)


def load(folders) -> FigureArt | None:
    """The figure art off the first folder whose `.adf` images hold all of it,
    or None."""
    for folder in folders:
        try:
            opened = amigalaterfigure.disks(pathlib.Path(folder))
            return FigureArt(art.read_art(art.disk_files(opened)))
        except Exception as exc:
            _log.debug("%s holds no figure art: %s", folder, exc)
    return None
