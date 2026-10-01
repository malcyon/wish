"""The Amiga Pool of Radiance wilderness: the travel grid, its tiles and its colours.

All three come off the player's own disks at run time and nothing is stored
here. `/program` holds the grid (hunk 31 + `GRID_AT`, one byte a square,
tile + 1, `y * 44 + world_x`) and the 16 travel colours (hunk 23 + `PALETTE_AT`,
12-bit words; `+0x20` is a byte-identical copy). The tiles are 24 x 24 pixels in
`bacpac.dax` and `sqrpaci.dax`.

**A tile block is a 12-byte header, then four bit planes one after the other**
(bit p of a pixel's colour index is plane p). Each plane holds `rows` tile-rows
of 24 lines, and a line is 6 bytes: tile `t` is in tile-row `t // 2`, column
`t % 2`. Tiles 0-41 are `bacpac.dax` block 1, 42-127 `sqrpaci.dax` block 1, and
128-255 `sqrpaci.dax` block 2 at index `t & 0x7F`.

**The picture draws the grid unchanged.** The nine site records in hunk 26 cover
a site with plain terrain while the game hides it, and the map hides nothing,
so none of them is read.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from . import amiga_dax, amiga_hunks
from .amiga_adf import AmigaDisk, AmigaDiskError
from .world import TILE_PIXELS, WORLD_ACROSS, WORLD_DOWN, WorldError

PALETTE_HUNK = 23
PALETTE_AT = 0x60
PALETTE_SIZE = 16
GRID_HUNK = 31
GRID_AT = 0x1A84
#: The grid is 44 squares across; the picture is 44 by 36 squares, the C64's size.
GRID_STRIDE = WORLD_ACROSS
GRID_SIZE = GRID_STRIDE * WORLD_DOWN

HEADER = 12
PLANES = 4
LINE_BYTES = 6
TILE_ROW_BYTES = TILE_PIXELS * LINE_BYTES           # 144
BACPAC_TILES = 42
SQRPACI_BANK = 128

#: The header's first, second and sixth words: the tile size in pixels, the
#: bytes of a line (two tiles), and the bytes of one plane's tile-row.
HEADER_WORDS = {0: TILE_PIXELS, 1: 6, 5: TILE_ROW_BYTES}


class _Tiles:
    """One tile block, checked against its header."""

    def __init__(self, block: bytes, name: str) -> None:
        if len(block) < HEADER:
            raise WorldError(f"{name} is too short to hold a tile header")
        words = struct.unpack(">6H", block[:HEADER])
        for at, want in HEADER_WORDS.items():
            if words[at] != want:
                raise WorldError(
                    f"{name} header word {at} is {words[at]:#x}, not {want:#x}")
        self.rows = words[4]
        if len(block) != HEADER + PLANES * self.rows * TILE_ROW_BYTES:
            raise WorldError(
                f"{name} is {len(block)} bytes, not {HEADER + PLANES * self.rows * TILE_ROW_BYTES} "
                f"for {self.rows} tile-rows")
        self.block = block
        self.name = name

    def count(self) -> int:
        return 2 * self.rows

    def lines(self, tile: int) -> list[bytes]:
        """The tile's 24 lines of `TILE_PIXELS` colour indices."""
        if not 0 <= tile < self.count():
            raise WorldError(f"{self.name} has no tile {tile}")
        row, column = divmod(tile, 2)
        out = []
        for line in range(TILE_PIXELS):
            at = row * TILE_ROW_BYTES + line * LINE_BYTES + column * 3
            planes = [int.from_bytes(self.block[HEADER + p * self.rows * TILE_ROW_BYTES + at:
                                                HEADER + p * self.rows * TILE_ROW_BYTES + at + 3],
                                     "big") for p in range(PLANES)]
            out.append(bytes(
                sum(((planes[p] >> (TILE_PIXELS - 1 - x)) & 1) << p for p in range(PLANES))
                for x in range(TILE_PIXELS)))
        return out


def colour(word: int) -> str:
    """A 12-bit Amiga colour word as `#RRGGBB`, each nibble times 17."""
    return "#%02X%02X%02X" % (17 * (word >> 8 & 15), 17 * (word >> 4 & 15),
                              17 * (word & 15))


class AmigaWorld:
    """The wilderness picture of Amiga Pool of Radiance."""

    def __init__(self, program: bytes, sqrpaci: dict[int, bytes],
                 bacpac: dict[int, bytes]) -> None:
        try:
            hunks, _relocs = amiga_hunks.parse(program)
        except (ValueError, struct.error) as error:
            raise WorldError(f"/program is not a Hunk executable: {error}") from None
        by_number = {h.number: h for h in hunks}
        palette = by_number.get(PALETTE_HUNK)
        grid = by_number.get(GRID_HUNK)
        if palette is None or palette.file_offset is None:
            raise WorldError(f"/program has no initialised hunk {PALETTE_HUNK}")
        if grid is None or grid.file_offset is None:
            raise WorldError(f"/program has no initialised hunk {GRID_HUNK}")
        at = palette.file_offset + PALETTE_AT
        if PALETTE_AT + 2 * PALETTE_SIZE > palette.size:
            raise WorldError(f"hunk {PALETTE_HUNK} is too short to hold the colours")
        self.colours = [colour(w) for w in
                        struct.unpack(">16H", program[at:at + 2 * PALETTE_SIZE])]
        at = grid.file_offset + GRID_AT
        if GRID_AT + GRID_SIZE > grid.size:
            raise WorldError(f"hunk {GRID_HUNK} is too short to hold the grid")
        self.grid = bytes(program[at:at + GRID_SIZE])
        try:
            self._banks = (_Tiles(bacpac[1], "bacpac.dax block 1"),
                           _Tiles(sqrpaci[1], "sqrpaci.dax block 1"),
                           _Tiles(sqrpaci[2], "sqrpaci.dax block 2"))
        except KeyError as missing:
            raise WorldError(f"no block {missing} in the tile archives") from None

    @classmethod
    def from_disks(cls, disks: Sequence[AmigaDisk]) -> "AmigaWorld":
        """The world off the game's two disks, found by file name."""
        wanted = {"program": None, "sqrpaci.dax": None, "bacpac.dax": None}
        for disk in disks:
            for path, _entry in disk.walk():
                name = path.rsplit("/", 1)[-1].lower()
                if name in wanted and wanted[name] is None:
                    wanted[name] = disk.read_file(path)
        for name, data in wanted.items():
            if data is None:
                raise WorldError(f"no disk here carries {name}")
        try:
            return cls(wanted["program"],
                       dict(amiga_dax.blocks(wanted["sqrpaci.dax"], "sqrpaci.dax")),
                       dict(amiga_dax.blocks(wanted["bacpac.dax"], "bacpac.dax")))
        except (amiga_dax.AmigaDaxError, AmigaDiskError) as error:
            raise WorldError(str(error)) from None

    def _tile(self, value: int) -> list[bytes]:
        """The 24 lines drawn for a grid byte; 0 is no tile and draws colour 0."""
        if value == 0:
            return [bytes(TILE_PIXELS)] * TILE_PIXELS
        tile = value - 1
        if tile < BACPAC_TILES:
            return self._banks[0].lines(tile)
        if tile < SQRPACI_BANK:
            return self._banks[1].lines(tile)
        return self._banks[2].lines(tile & 0x7F)

    def picture(self) -> tuple[bytes, list[str]]:
        """`(pixels, colours)`: `WORLD_ACROSS * TILE_PIXELS` by
        `WORLD_DOWN * TILE_PIXELS` colour indices, row-major, and the 16
        `#RRGGBB` colours they index."""
        width = WORLD_ACROSS * TILE_PIXELS
        out = bytearray(width * WORLD_DOWN * TILE_PIXELS)
        cache: dict[int, list[bytes]] = {}
        for y in range(WORLD_DOWN):
            for x in range(WORLD_ACROSS):
                value = self.grid[y * GRID_STRIDE + x]
                if value not in cache:
                    cache[value] = self._tile(value)
                for py, row in enumerate(cache[value]):
                    at = (y * TILE_PIXELS + py) * width + x * TILE_PIXELS
                    out[at:at + TILE_PIXELS] = row
        return bytes(out), list(self.colours)

    def identify(self, block: bytes) -> None:
        """None: the running game states its window, so no grid is matched."""
        return None
