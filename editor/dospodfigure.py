"""A DOS Pools of Darkness character's combat figure, as the ICON screen draws it.

The art, the box behind it and the colours are read from the player's own game
folder when a party opens (`goldbox/dos_pod_icons.py` has the rules); nothing
here holds any of them.
"""

from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass

from goldbox import dos_pod_icons as art

from .iconwidget import Figure

_log = logging.getLogger(__name__)


@dataclass
class FigureArt:
    """One game folder's heads, bodies and box, and the colours its ICON screen shows."""

    game: art.PodGameArt
    palette: dict[int, tuple[int, int, int]]

    def figure(self, native) -> Figure | None:
        """`native`'s figure, or None when its blocks are not in the folder."""
        head, body = native.get("icon_head"), native.get("icon_body")
        size = native.get("size")
        try:
            poses = art.compose(self.game.heads, self.game.bodies, head, body,
                                size, bytes(native.get("icon_colours")))
            shown = tuple(
                tuple(tuple(self.palette[v] for v in row)
                      for row in art.on_box(self.game.box, pose))
                for pose in poses)
        except Exception as exc:
            _log.debug("no figure for head %s body %s size %s: %s",
                       head, body, size, exc)
            return None
        return Figure(shown, self.palette[0])


def load(folders) -> FigureArt | None:
    """The figure art off the first game folder that holds all of it, or None."""
    for folder in folders:
        try:
            game = art.read_game(pathlib.Path(folder))
            return FigureArt(game, art.icon_palette(game))
        except Exception as exc:
            _log.debug("%s holds no figure art: %s", folder, exc)
    return None
