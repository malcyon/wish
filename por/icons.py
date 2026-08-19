"""Combat icons: the shared table at $4BE0 in SAVEDGAME0.

Eight entries of 36 bytes, one per character slot, ending exactly at $4D00
where slot 0 begins. Each entry splits cleanly in half:

    +0  .. +17    18 screen codes  -- the shape / pose
    +18 .. +35    18 colour values -- one per character cell, C64 colours 0-15

Established by having Donald change every character's icon in-game and diffing
(the combat-icon edits, docs/50-experiments.md). MAGNUS changed **only** bytes 18-35, all of them
in the range $00-$0F: a colour-only change. ROLAND and LADY KATHERINE changed
both halves. Nothing outside `$4BE0`-`$4CFF` moved.

The same 36 bytes appear at record offset `0x220` in an exported `.chr`, which
is why an export carries its icon while a save slot does not.
"""

from __future__ import annotations

from dataclasses import dataclass

from .savegame import SAVE0_LOAD_ADDRESS

ICON_TABLE_BASE = 0x4BE0
ICON_SIZE = 36
ICON_COUNT = 8
CELLS = 18                     # screen codes, then the same number of colours

C64_COLOURS = [
    "black", "white", "red", "cyan", "purple", "green", "blue", "yellow",
    "orange", "brown", "light red", "dark grey", "grey", "light green",
    "light blue", "light grey",
]


@dataclass(frozen=True)
class Icon:
    raw: bytes

    @property
    def shape(self) -> bytes:
        """The 18 screen codes that draw the icon."""
        return self.raw[:CELLS]

    @property
    def colours(self) -> bytes:
        """The 18 colour values, one per cell."""
        return self.raw[CELLS:]

    @property
    def colour_names(self) -> list[str]:
        return [C64_COLOURS[c & 0x0F] for c in self.colours]

    @property
    def palette(self) -> list[str]:
        """The distinct colours used, which is what an editor would offer."""
        seen: list[str] = []
        for c in self.colour_names:
            if c not in seen:
                seen.append(c)
        return seen

    def __repr__(self) -> str:
        return f"<Icon shape={self.shape.hex()} palette={'/'.join(self.palette)}>"


def icon_for_slot(save0_payload: bytes, slot: int) -> Icon:
    base = ICON_TABLE_BASE - SAVE0_LOAD_ADDRESS + slot * ICON_SIZE
    return Icon(bytes(save0_payload[base: base + ICON_SIZE]))
