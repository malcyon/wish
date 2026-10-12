"""An Amiga Pool of Radiance character's combat figure, as the ICON screen draws it.

The art, the box behind it and the sixteen colours are read from the player's
own Amiga disks when a party opens (`goldbox/amiga_por_icons.py` has the rules);
nothing here holds any of them.
"""

from __future__ import annotations

import logging
import pathlib
from collections.abc import Callable
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from goldbox import amiga_dax, spell_names, stonecracker
from goldbox import amiga_por_icons as art
from goldbox.amiga_adf import AmigaDisk

from .iconwidget import Figure

_log = logging.getLogger(__name__)

#: The game's executable on disk 1, which holds the ICON screen's colours.
PROGRAM_FILE = spell_names.AMIGA_PROGRAMS["pool-of-radiance"].lower()


@dataclass
class FigureArt:
    """The unpacked disk files a figure is made from, decoded block by block."""

    heads: bytes
    bodies: bytes
    frame: art.ArtBlock
    palette: tuple[tuple[int, int, int], ...]
    _decoded: dict = field(default_factory=dict, repr=False)

    def _block(self, kind: str, block_id: int) -> art.ArtBlock:
        key = (kind, block_id)
        if key not in self._decoded:
            data, name = ((self.heads, art.HEAD_FILE) if kind == "head"
                          else (self.bodies, art.BODY_FILE))
            self._decoded[key] = art.decode_block(
                amiga_dax.block(data, block_id, name), f"{name} block {block_id}")
        return self._decoded[key]

    def figure(self, native) -> Figure | None:
        """`native`'s figure, or None when its blocks are not on the disk."""
        head, body = native.get("icon_head"), native.get("icon_body")
        size = native.get("size")
        try:
            heads = {i: self._block("head", i)
                     for i in art.block_ids("head", head, size)}
            bodies = {i: self._block("body", i)
                      for i in art.block_ids("body", body, size)}
            poses = art.compose(heads, bodies, head, body, size,
                                bytes(native.get("icon_colours")))
            shown = tuple(tuple(tuple(self.palette[v] for v in row)
                                for row in art.on_frame(self.frame, pose))
                          for pose in poses)
        except Exception as exc:
            _log.debug("no figure for head %s body %s size %s: %s",
                       head, body, size, exc)
            return None
        return Figure(shown, self.palette[0])


class Loaded(QObject):
    """Brings a background load's result back to the thread that owns it."""

    done = pyqtSignal(int, object)


class _Job(QRunnable):
    def __init__(self, serial: int, loader: Callable[[], object], carrier: Loaded):
        super().__init__()
        self._serial, self._loader, self._carrier = serial, loader, carrier

    def run(self) -> None:
        try:
            found = self._loader()
        except Exception as exc:
            _log.debug("the figure art load failed: %s", exc)
            found = None
        try:
            self._carrier.done.emit(self._serial, found)
        except RuntimeError:
            _log.debug("the window closed before the figure art arrived")


def start(serial: int, loader: Callable[[], object], carrier: Loaded) -> None:
    """Run `loader` on a worker thread and emit `carrier.done(serial, art)` when
    it ends; `art` is None when nothing was found.

    Opening the `.adf` images of up to five folders takes as long as they are
    many, so the window does not wait for it.
    """
    QThreadPool.globalInstance().start(_Job(serial, loader, carrier))


def load(folders) -> FigureArt | None:
    """The figure art off the first folder whose `.adf` images hold all of it,
    or None."""
    for folder in folders:
        try:
            found = _files(pathlib.Path(folder))
            if found is None:
                continue
            program = stonecracker.as_loaded(found[PROGRAM_FILE])
            frame = art.read_art(found[art.FRAME_FILE], art.FRAME_FILE)
            return FigureArt(found[art.HEAD_FILE], found[art.BODY_FILE],
                             frame[art.FRAME_BLOCK], art.icon_palette(program))
        except Exception as exc:
            _log.debug("%s holds no figure art: %s", folder, exc)
    return None


def _files(folder: pathlib.Path) -> dict[str, bytes] | None:
    """The four files the figure needs, off the disks in `folder`."""
    wanted = {name: None for name in (art.HEAD_FILE, art.BODY_FILE,
                                      art.FRAME_FILE, PROGRAM_FILE)}
    for image in sorted(folder.iterdir()):
        if not image.is_file() or image.suffix.lower() != ".adf":
            continue
        try:
            disk = AmigaDisk.open(image)
            names = {path.strip("/").lower(): path for path, _ in disk.walk()}
            for name in wanted:
                if wanted[name] is None and name in names:
                    wanted[name] = disk.read_file(names[name])
        except Exception as exc:
            _log.debug("%s is not a readable disk: %s", image, exc)
    return None if None in wanted.values() else wanted
