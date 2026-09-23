"""The overland travel map — `SQRDATA0n`, read and stitched into one world.

**Not `goldbox/world_state.py`**, which is where a *party* is standing
and when. This module is the map itself.

**The overland map is not a `GEO`.** It is the combat square engine --
`SQRPACI` descriptor, one byte a square -- pointed at `SQRDATA0n` instead of
a combat arena. `automap/combat.py` reads exactly this shape for a fight;
this module reads the same shape for the three files that make up Pool of
Radiance's wilderness.

A `SQRDATA` file is **648 bytes of grid, then 120 tile entries of 18 bytes
each**: an 18 x 36 grid, one byte a square, indexed `y * 18 + x`, followed by
120 glyphs of nine screen codes then nine colour attributes -- a 3 x 3 block
of characters out of `SECSET0n`. `SQRDATA05` is 648 + 120 x 18 = 2808 bytes
exactly; `SQRDATA04` and `SQRDATA06` carry eight spare bytes after that. All
of this is CONFIRMED (`docs/113-world-map.md`, `docs/137-wilderness-automap.md`)
and pinned against the player's own disks by `tests/areas/test_p3.py`.

**The three files are overlapping windows on one world, thirteen columns
apart, west to east**: `SQRDATA04` (west), `SQRDATA05` (middle), `SQRDATA06`
(east) -- `goldbox/areas.py`'s own order for areas 25, 26 and 27. The game's
own world coordinate is the window-local `x` plus `13 * window_index` --
`docs/137-wilderness-automap.md` §1: "the party marked at (`$49C3` + 13 x k,
`$49C4`)" -- so this module keeps that coordinate system rather than
renormalising it to start at zero. The two windows stitch at world x = 15
and x = 28, and the walkable part of the world is x 2-41, y 2-33: 40 x 32
squares. CONFIRMED: the raw grid overlaps in a five-column band at each
seam (18-13 = 5 columns, all 36 rows), and 179 of those 180 squares agree
between the west and middle windows, 180 of 180 between the middle and east
(`docs/113-world-map.md`); `tests/areas/test_world.py` recomputes both counts
against the disks.

**A terrain code means only what its own window's tables say.** `2E` is
walkable mountain on map `19` and solid on map `1B`
(`docs/113-world-map.md`, `docs/137-wilderness-automap.md`, both "Do not
read a terrain code against another window's table"). So `Window.square`
never crosses into another window's data, and there is deliberately no
global tile-name table here -- only the raw index, which the window it came
from is the sole authority on.

## What this module does not do, and why

`passable(window, x, y)` and `site_at(world_x, y)` are named by
`#11 (Draw the wilderness on the automapper)` and are **not implemented**.
Both need a table that is not in `SQRDATA0n` at all: "each script carries
its site list as four tables (y, count, x, event) and its impassable-terrain
list as one more" (`docs/113-world-map.md`) -- inside `ECL19`/`ECL1A`/`ECL1B`'s
own bytecode, not in the file this module reads. The byte offsets of those
tables were recorded once, in `reports/world-map.md` (scratch, deleted), which is lost
with the scratch directory (`#136 (Thirty-two cited write-ups are gone, because the
knowledge base pointed into gitignored scratch)`) -- confirmed by
`tools/areas/windowsquare.py`'s own docstring: "Passability cannot be read off the
disk: the impassable-terrain table's address was in
`reports/world-map.md`, which is lost (#136), so the running game is
the only authority left." Recovering the offsets means rebuilding an ECL
decoder, and `docs/115-review-the-scripts.md` records that reading the ECL
scripts at all was **closed at Donald's own direction** on 2026-08-31 --
"I don't need to see the ECL scripts. If I decide I want to see them, we can
approach the issue again at that time." Reopening that is his call, not a
default this module can reach for. Both functions raise `NotImplementedError`
naming this rather than guessing at an address or shipping a table that was
never read off anything.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .d64 import D64, load_payload

#: The grid is 18 columns wide and 36 rows tall, one byte a square, indexed
#: `y * STRIDE + x`. This is `$0612 + 1`, read off `GDRIVE00 $C3AF` -- *not*
#: `$0607` = 20, which is `automap/combat.py`'s own corrected note
#: (`docs/113-world-map.md`, "Correction to `docs/101-combat-view.md`").
STRIDE = 18
ROWS = 36
GRID_SIZE = STRIDE * ROWS                        # 648

#: 120 glyph entries, nine screen codes then nine colour attributes -- a
#: 3 x 3 block of characters. CONFIRMED: the game's own travel pane shows
#: these screen codes on 225 of 225 cells checked.
TILE_COUNT = 120
TILE_SIZE = 18
TILE_TABLE_SIZE = TILE_COUNT * TILE_SIZE          # 2160

#: `SQRDATA05` is exactly this size; `SQRDATA04` and `SQRDATA06` carry eight
#: spare bytes after it (`tests/areas/test_p3.py`).
MIN_FILE_SIZE = GRID_SIZE + TILE_TABLE_SIZE       # 2808

#: The walkable part of a window, window-local -- the two-square border is
#: never shown to the player and the game never walks a party into it
#: (`docs/113-world-map.md`: "Walkable is x 2..15, y 2..33 of each window").
PLAYABLE_X = range(2, 16)
PLAYABLE_Y = range(2, 34)

#: Windows are `WINDOW_STEP` world columns apart, west to east -- the game's
#: own arithmetic, `$49C3 + 13 * k` (`docs/137-wilderness-automap.md`).
WINDOW_STEP = 13

#: The three files, in world order: west, middle, east -- `goldbox/areas.py`'s
#: own order for areas 25, 26 and 27.
WINDOW_NAMES = ("SQRDATA04", "SQRDATA05", "SQRDATA06")

#: Where the walkable world starts and how wide/tall it is, in the game's own
#: coordinate system (window-local x plus `13 * window_index`, never
#: renormalised to 0). `docs/113-world-map.md`: "the world's playable area is
#: 40 x 32"; `docs/137-wilderness-automap.md`: "stitched at world x 15 and 28".
WORLD_X_MIN = PLAYABLE_X.start                    # 2
WORLD_WIDTH = 40
WORLD_X_MAX = WORLD_X_MIN + WORLD_WIDTH - 1        # 41
WORLD_Y_MIN = PLAYABLE_Y.start                    # 2
WORLD_HEIGHT = 32
WORLD_Y_MAX = WORLD_Y_MIN + WORLD_HEIGHT - 1       # 33

#: The two seams, in world x -- where window *k* hands off to window *k + 1*.
#: A world x at or past a seam belongs to the eastern window of the pair; the
#: two windows' raw data agree there (179/180 and 180/180, see the module
#: docstring), so which side answers a seam square is a bookkeeping choice,
#: not a correctness one.
SEAM_WEST_MIDDLE = PLAYABLE_X.stop - 1 + WINDOW_STEP * 0    # 15
SEAM_MIDDLE_EAST = PLAYABLE_X.stop - 1 + WINDOW_STEP * 1    # 28

#: Every screen code in every tile the three grids use is `$40` or above, and
#: the set holds 192 glyphs, so this is the offset from code to glyph.
GLYPH_BASE = 0x40
GLYPH_BYTES = 8
CHARSET_GLYPHS = 192

#: A tile is 3 x 3 characters.
TILE_CELLS = 3
TILE_PIXELS = TILE_CELLS * 8

#: The wilderness charsets, one a window, in `WINDOW_NAMES` order.
CHARSET_NAMES = ("SECSET04", "SECSET05", "SECSET06")

#: `$D021`, `$D022`, `$D023` -- the three colours a multicolour cell shares
#: with the whole screen, so no tile can carry them: black, light grey and
#: green. Read off the chip on the travel grid with the party at (8,27) on
#: the middle window (`tools/pool_of_radiance/worldregisters.py`,
#: `docs/217-drawing-the-wilderness.md` measurement B). Change this only
#: against another such reading.
SHARED = (0x00, 0x0F, 0x05)

#: How many of a block's 648 bytes may differ from a window's grid and still
#: name that window. Two windows are at least 532 bytes apart, so a tolerance
#: under 266 can never match two of them; the nearest block that is not a
#: window, over every file on the disks, is 554 bytes away
#: (`docs/217-drawing-the-wilderness.md` §1); the largest difference the game
#: paints over a grid is 3 bytes. How many squares a site entry can paint is
#: not known, so the margin is kept wide rather than set to the 46 squares
#: a full pane could cover.
SITE_PAINT_TOLERANCE = 128


class WorldError(ValueError):
    """A `SQRDATA` payload too short to hold a grid and its glyph table."""


@dataclass(frozen=True)
class Tile:
    """One of a window's 120 glyphs.

    `screen_codes` and `attributes` are nine bytes each: a 3 x 3 block of
    characters out of `SECSET0n` (`docs/113-world-map.md`). This
    module hands the two halves back as measured; `tile_pixels` turns one
    into pixels with a window's `SECSET0n` charset.
    """

    screen_codes: bytes
    attributes: bytes


class Window:
    """One `SQRDATA` file: an 18 x 36 grid of tile indices, plus its 120 tiles.

    A terrain code means only what *this* window's own tables say -- see the
    module docstring. There is no method here that accepts a foreign code or
    reaches into another `Window`.
    """

    def __init__(self, payload: bytes | bytearray, name: str | None = None):
        if len(payload) < MIN_FILE_SIZE:
            raise WorldError(
                f"a SQRDATA file is at least {MIN_FILE_SIZE} bytes "
                f"({GRID_SIZE} grid + {TILE_TABLE_SIZE} tiles), "
                f"got {len(payload)}")
        self._data = bytes(payload)
        self.name = name

    @classmethod
    def from_disk(cls, disk: D64 | str, name: bytes | str) -> "Window":
        decoded = name.decode("latin1") if isinstance(name, (bytes, bytearray)) else name
        return cls(load_payload(disk, name), name=decoded)

    def to_bytes(self) -> bytes:
        return self._data

    # -- the grid ----------------------------------------------------------

    def square(self, x: int, y: int) -> int:
        """The raw tile index at window-local `(x, y)`, 0-119."""
        if not (0 <= x < STRIDE and 0 <= y < ROWS):
            raise IndexError(f"({x}, {y}) is outside the {STRIDE}x{ROWS} grid")
        return self._data[y * STRIDE + x]

    def is_playable(self, x: int, y: int) -> bool:
        """Whether `(x, y)` is in the two-square-deep border the game never
        shows or walks a party into."""
        return x in PLAYABLE_X and y in PLAYABLE_Y

    # -- the glyph table -----------------------------------------------------

    def tile(self, index: int) -> Tile:
        """One of the 120 glyph entries this window's grid indexes into."""
        if not (0 <= index < TILE_COUNT):
            raise IndexError(f"tile {index} is outside 0..{TILE_COUNT - 1}")
        at = GRID_SIZE + index * TILE_SIZE
        block = self._data[at:at + TILE_SIZE]
        return Tile(screen_codes=block[:9], attributes=block[9:])

    def tile_at(self, x: int, y: int) -> Tile:
        """The glyph drawn at window-local `(x, y)` -- `tile(square(x, y))`."""
        return self.tile(self.square(x, y))


def cell_pixels(glyph: bytes, attribute: int,
                shared: tuple[int, int, int] = SHARED) -> list[list[int]]:
    """One character cell as 8 x 8 colour indices, rows top to bottom.

    Bit 3 of `attribute` selects multicolour, which is the whole of the
    difference between the two branches: a multicolour row is four pixel
    pairs out of a four-colour choice, a hi-res row eight pixels out of two.
    """
    colour = attribute & 0x0F
    background, mc1, mc2 = shared
    out = []
    for row in range(8):
        bits = glyph[row]
        line = []
        if colour & 0x08:
            choice = (background, mc1, mc2, colour & 0x07)
            for pair in range(4):
                value = (bits >> (6 - pair * 2)) & 0x03
                line.append(choice[value])
                line.append(choice[value])
        else:
            for bit in range(8):
                line.append(colour if (bits >> (7 - bit)) & 1 else background)
        out.append(line)
    return out


def tile_pixels(tile: Tile, glyphs: bytes,
                shared: tuple[int, int, int] = SHARED) -> list[list[int]]:
    """One tile as 24 x 24 colour indices."""
    rows = [[0] * TILE_PIXELS for _ in range(TILE_PIXELS)]
    for cell in range(9):
        code = tile.screen_codes[cell]
        at = (code - GLYPH_BASE) * GLYPH_BYTES
        glyph = glyphs[at:at + GLYPH_BYTES] if at >= 0 else bytes(8)
        pixels = cell_pixels(glyph, tile.attributes[cell], shared)
        cx, cy = (cell % TILE_CELLS) * 8, (cell // TILE_CELLS) * 8
        for y in range(8):
            for x in range(8):
                rows[cy + y][cx + x] = pixels[y][x]
    return rows


@dataclass(frozen=True)
class World:
    """The three `SQRDATA` windows, addressed by the game's own world
    coordinate: window-local x plus `13 * window_index`, never renormalised.

    `windows` is `(west, middle, east)` -- `SQRDATA04`, `05`, `06` -- matching
    `WINDOW_NAMES` and `goldbox/areas.py`'s order for areas 25, 26 and 27.
    """

    windows: tuple[Window, Window, Window]
    #: `SECSET04`, `05`, `06`, PRG header dropped, or None when a disk set
    #: does not carry all three.
    charsets: tuple[bytes, bytes, bytes] | None = None

    @classmethod
    def from_disks(cls, disks) -> "World":
        """The three windows, found across a set of disks.

        `SQRDATA04`, `05` and `06` are never on the same disk -- they ride
        `POOL6`, `7` and `8` respectively (areas 25-27,
        `goldbox/areas.py`) -- so, unlike `Geo.from_disk`, this cannot open
        one image and read three files out of it. `disks` is any iterable of
        `D64` objects or paths; for each window the first disk that carries
        its file wins, the way `tests/gamedata.py`'s `game_file` does.

        Raises `WorldError` naming whichever window no disk in `disks`
        carried.
        """
        images = [D64.open(d) if isinstance(d, (str, os.PathLike)) else d
                  for d in disks]
        windows = []
        for name in WINDOW_NAMES:
            encoded = name.encode()
            for image in images:
                entry = image.find(encoded)
                if entry is not None:
                    # Through `from_disk`, not a second copy of its three
                    # lines: two ways to build a `Window` drift apart the
                    # first time either changes, and only one of them would
                    # have a test.
                    windows.append(Window.from_disk(image, entry.name))
                    break
            else:
                raise WorldError(f"no disk here carries {name}")
        charsets = []
        for name in CHARSET_NAMES:
            encoded = name.encode()
            for image in images:
                if image.find(encoded) is not None:
                    # The PRG header's load address is not where the game
                    # runs the set, so `load_payload` drops it.
                    payload = load_payload(image, encoded)
                    if len(payload) < CHARSET_GLYPHS * GLYPH_BYTES:
                        raise WorldError(
                            f"{name} is {len(payload)} bytes, short of "
                            f"{CHARSET_GLYPHS * GLYPH_BYTES}")
                    charsets.append(payload)
                    break
        return cls(tuple(windows),
                   tuple(charsets) if len(charsets) == 3 else None)

    def identify(self, block: bytes) -> tuple[int, int] | None:
        """Which window a 648-byte grid block in memory is, and how many
        bytes differ from it, or None.

        None when any byte is `TILE_COUNT` or more (no grid holds one) or
        when even the nearest window is over `SITE_PAINT_TOLERANCE` bytes
        away.
        """
        if len(block) != GRID_SIZE or max(block) >= TILE_COUNT:
            return None
        best = None
        for index, window in enumerate(self.windows):
            grid = window.to_bytes()[:GRID_SIZE]
            distance = sum(a != b for a, b in zip(block, grid))
            if best is None or distance < best[1]:
                best = (index, distance)
        if best[1] > SITE_PAINT_TOLERANCE:
            return None
        return best

    def locate(self, world_x: int) -> tuple[Window, int]:
        """Which window owns `world_x`, and that window's own local x there.

        Raises `IndexError` outside the walkable world (`WORLD_X_MIN` ..
        `WORLD_X_MAX`). At a seam, the eastern window answers -- see
        `SEAM_WEST_MIDDLE` / `SEAM_MIDDLE_EAST`.
        """
        if not (WORLD_X_MIN <= world_x <= WORLD_X_MAX):
            raise IndexError(
                f"world x {world_x} is outside {WORLD_X_MIN}..{WORLD_X_MAX}")
        if world_x < SEAM_WEST_MIDDLE:
            index = 0
        elif world_x < SEAM_MIDDLE_EAST:
            index = 1
        else:
            index = 2
        return self.windows[index], world_x - WINDOW_STEP * index

    def square(self, world_x: int, y: int) -> int:
        """The raw tile index at world `(world_x, y)`.

        `y` is not stitched -- every window shares the same y range, and only
        x moves between them.

        **The int this returns does not carry the window it came from, and a
        terrain code only means anything against its own window's table**:
        `2E` is walkable mountain on map `19` and solid on `1B`. Nothing here
        can be asked what a bare code means -- there is no global code-to-name
        table to misuse -- but a caller that stores this number and decodes it
        later, once `passable` exists, is the way that protection is lost.
        Use `locate` and keep the `Window`, or call `Window.square` directly.
        """
        if y not in PLAYABLE_Y:
            raise IndexError(f"y {y} is outside {WORLD_Y_MIN}..{WORLD_Y_MAX}")
        window, local_x = self.locate(world_x)
        return window.square(local_x, y)

    def tile_at(self, world_x: int, y: int) -> Tile:
        """The glyph drawn at world `(world_x, y)`."""
        window, local_x = self.locate(world_x)
        return window.tile_at(local_x, y)


# -- blocked: see the module docstring ---------------------------------------

_BLOCKED = (
    "the site tables and the impassable-terrain tables live in ECL19/1A/1B's "
    "own bytecode, not in SQRDATA0n; their addresses were in "
    "reports/world-map.md, lost with the scratch directory (#136), and recovering them "
    "means reopening docs/115-review-the-scripts.md, closed at Donald's own "
    "direction -- see the goldbox/world.py module docstring and "
    "#11 (Draw the wilderness on the automapper)")


def passable(window: Window, x: int, y: int) -> bool:
    """Whether the party may walk onto window-local `(x, y)`. **Not
    implemented** -- see the module docstring."""
    raise NotImplementedError(_BLOCKED)


def site_at(world_x: int, y: int) -> str | None:
    """The site at world `(world_x, y)`, or None. **Not implemented** -- see
    the module docstring."""
    raise NotImplementedError(_BLOCKED)
