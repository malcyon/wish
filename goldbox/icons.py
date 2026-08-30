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

from .d64 import D64, load_payload
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


# -- drawing the thing ------------------------------------------------------

# The 18 cells are **two 3x3 poses stacked**, not one 3x6 figure. Rendering the
# party's icons showed a fighter in one stance on top and a second stance below.
CELL_COLS = 3
POSE_ROWS = 3
POSES = 2
CELL_ROWS = POSE_ROWS * POSES

# The glyphs. CHARPIC00 -- "character picture" -- is the only charset on the
# disks big enough: icon shape codes reach 243, and the other candidate,
# CHARSET, holds 64 glyphs. Byte-identical on all eight disks.
#
# **Eight bytes per glyph from byte 0, no header.** Splitting it at every phase,
# phase 0 is the only one with a blank glyph anywhere meaningful, and that blank
# is index 32 -- the screen code for space, which real icons use. The payload is
# 2030 bytes, six past the end of glyph 252, so the file stops two bytes into
# glyph 253: 2032 = 8 x 254 is the largest an eight-block PRG carries, and a full
# 2048-byte charset would need a ninth block. Glyph 253's lost tail is `D4 D4`,
# recoverable because glyphs 81 and 251 are the only ones sharing its six present
# bytes. Nothing reaches it -- the highest shape code across every source is 243,
# ending 72 bytes clear -- so the clamp in `icon_pixels` never fires.
ICON_CHARSET_FILE = b"CHARPIC00"

# Combat is a **multicolour** text screen, so a cell is four double-width pixels
# per row, not eight. Three of the four colours are shared and live in VIC
# registers, not in the save. COM.PREP -- the combat-preparation overlay, byte
# identical on all eight disks -- sets them:
#
#     LDX #$0C / STX $D020 / DEX / STX $D021 / DEX / STX $D022
#     LDA #$00 / STA $D023
COMBAT_BORDER = 0x0C            # grey
COMBAT_BACKGROUND = 0x0B        # dark grey   -> bit pair 00
COMBAT_MULTICOLOUR_1 = 0x0A     # light red   -> bit pair 01
COMBAT_MULTICOLOUR_2 = 0x00     # black       -> bit pair 10
#                                 bit pair 11 -> the cell's own colour, low 3 bits

# Pepto's measured VIC-II palette, as #rrggbb.
C64_PALETTE = [
    "#000000", "#FFFFFF", "#813338", "#75CEC8", "#8E3C97", "#56AC4D",
    "#2E2C9B", "#EDF171", "#8E5029", "#553800", "#C46C71", "#4A4A4A",
    "#7B7B7B", "#A9FF9F", "#706DEB", "#B2B2B2",
]

PIXELS_WIDE = CELL_COLS * 8      # 8 hi-res pixels per cell
PIXELS_HIGH = CELL_ROWS * 8


def load_icon_charset(disk: D64 | str) -> bytes:
    """The glyph bitmaps the combat icons are drawn from."""
    payload = load_payload(disk, ICON_CHARSET_FILE)
    return payload


def icon_pixels(icon: "Icon", charset: bytes) -> list[list[int]]:
    """Both poses as a grid of C64 colour indices, `[y][x]`.

    Pure data -- no Qt, no image library -- so the renderer can be tested and
    the same function serves the editor, a PNG dump and a terminal preview.
    """
    shared = {0: COMBAT_BACKGROUND, 1: COMBAT_MULTICOLOUR_1,
              2: COMBAT_MULTICOLOUR_2}
    out = [[COMBAT_BACKGROUND] * PIXELS_WIDE for _ in range(PIXELS_HIGH)]
    for cell in range(CELLS):
        code = icon.shape[cell]
        color_byte = icon.colours[cell]
        is_mc = bool(color_byte & 0x08)
        own = color_byte & 0x07
        cx, cy = cell % CELL_COLS, cell // CELL_COLS
        base = code * 8
        glyph = charset[base:base + 8]
        for row in range(8):
            bits = glyph[row] if row < len(glyph) else 0
            if is_mc:
                for pair in range(4):
                    value = (bits >> (6 - pair * 2)) & 0x03
                    c = shared.get(value, own)
                    out[cy * 8 + row][cx * 8 + pair * 2] = c
                    out[cy * 8 + row][cx * 8 + pair * 2 + 1] = c
            else:
                for bit in range(8):
                    value = (bits >> (7 - bit)) & 0x01
                    c = own if value else COMBAT_BACKGROUND
                    out[cy * 8 + row][cx * 8 + bit] = c
    return out
