"""The overland travel map — `SQRDATA0n`, read and stitched into one world.

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
and pinned against the player's own disks by `tests/test_p3.py`.

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
(`docs/113-world-map.md`); `tests/test_world.py` recomputes both counts
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
tables were recorded once, in `work/reports/world-map.md`, which is lost
with `work/` (`#136 (Thirty-two cited write-ups are gone, because the
knowledge base pointed into gitignored scratch)`) -- confirmed by
`tools/windowsquare.py`'s own docstring: "Passability cannot be read off the
disk: the impassable-terrain table's address was in
`work/reports/world-map.md`, which is lost (#136), so the running game is
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
#: 3 x 3 block of characters. PROBABLE (`docs/113-world-map.md`): the split
#: between the two halves is measured from the file's own arithmetic, but
#: which set the codes are drawn from is not independently confirmed.
TILE_COUNT = 120
TILE_SIZE = 18
TILE_TABLE_SIZE = TILE_COUNT * TILE_SIZE          # 2160

#: `SQRDATA05` is exactly this size; `SQRDATA04` and `SQRDATA06` carry eight
#: spare bytes after it (`tests/test_p3.py`).
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


class WorldError(ValueError):
    """A `SQRDATA` payload too short to hold a grid and its glyph table."""


@dataclass(frozen=True)
class Tile:
    """One of a window's 120 glyphs.

    `screen_codes` and `attributes` are nine bytes each, PROBABLE as "a 3 x 3
    block of characters out of `SECSET0n`" (`docs/113-world-map.md`) -- this
    module hands the two halves back as measured and decodes no further,
    since drawing the game's own art is not what any of this is for
    (`docs/137-wilderness-automap.md` §5: "what a `SECSET0n` glyph looks
    like -- not needed").
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


@dataclass(frozen=True)
class World:
    """The three `SQRDATA` windows, addressed by the game's own world
    coordinate: window-local x plus `13 * window_index`, never renormalised.

    `windows` is `(west, middle, east)` -- `SQRDATA04`, `05`, `06` -- matching
    `WINDOW_NAMES` and `goldbox/areas.py`'s order for areas 25, 26 and 27.
    """

    windows: tuple[Window, Window, Window]

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
                    windows.append(Window(load_payload(image, entry.name), name=name))
                    break
            else:
                raise WorldError(f"no disk here carries {name}")
        return cls(tuple(windows))

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
    "work/reports/world-map.md, lost with work/ (#136), and recovering them "
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
