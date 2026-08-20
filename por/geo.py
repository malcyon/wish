"""GEO map geometry for Pool of Radiance (C64).

A `GEO` file is **four 256-byte planes over a 16x16 grid**, not an array of
per-square records. Every square is indexed `x + (y << 4)` in each plane --
row-major, y increasing southward, origin top-left.

    $000  high nibble = wall art north, low nibble = wall art east
    $100  high nibble = wall art south, low nibble = wall art west
    $200  square attributes; bit 7 = roofed / indoor
    $300  passability, two bits per direction: N=0-1, E=2-3, S=4-5, W=6-7

**A wall and a barrier are two independent fields.** Five readings of GEO failed
because they conflated them. Wall art says what to *draw*; the two-bit field
says whether you can *walk through*, and the game consults it only when there is
wall art on that edge -- an edge with no art is passable whatever its bits say.

Confirmed against `simeonpilgrim/coab`, a C# reimplementation of Curse of the
Azure Bonds reversed from the DOS overlays, and verified on our own 29 files:
adjacent squares agree about their shared edge 13793 times in 13920 (0.991).
`reciprocity()` recomputes that, so a mis-parsed file fails loudly.

On disk these are PRG files loading at $0400, so the payload is 1024 bytes after
the two-byte load address.
"""

from __future__ import annotations

from .d64 import D64, load_payload, split_load_address

GRID = 16
PLANE = 0x100
GEO_SIZE = 4 * PLANE

WALLS_NORTH_EAST = 0x000
WALLS_SOUTH_WEST = 0x100
ATTRIBUTES = 0x200
BARRIERS = 0x300

# Plane $200, bit by bit.
#
# Bit 7 is roofed/indoor. The rest is a **per-square script id**: the area's own
# ECL script does `AND <mask>, ATTR, [v]` then `ONGOTO idx=[v]`, so the id
# indexes a jump table. GEO00 square (6,2) holds $8A; masked with $7F that is
# 10; ECL00's table entry 10 runs `NEWECL 11`; and ECL0B prints
# "THE ROOM IS FILLED WITH DUELING PAIRS." -- which is exactly what the game does
# when you step there. 14 of 22 GEO/ECL pairs have a table exactly `max id + 1`
# long, covering 0..max with nothing spare.
INDOOR = 0x80
SCRIPT_ID = 0x7F

# **The mask is the area's, not ours.** Eighteen scripts mask $7F, the
# dungeon-floor family masks $1F, and ECL17 masks $3F. Only in the $1F family do
# the two freed bits mean anything, and there they control wandering monsters:
# byte-identical code in ECL03/04/06/09, immediately before the zone dispatch,
# tests bit 6 to suppress a random encounter on that square and bit 5 to double
# the RNG range, halving the rate. Elsewhere those bits are part of the id.
# So read them only when you know the area's mask. Across all 29 files bit 6 is
# set on 114 squares and bit 5 on 517, of 7424.
NO_ENCOUNTER = 0x40
HALF_ENCOUNTER_RATE = 0x20
DUNGEON_FLOOR_MASK = 0x1F

NORTH, EAST, SOUTH, WEST = 0, 1, 2, 3
DIRECTIONS = (NORTH, EAST, SOUTH, WEST)
DIRECTION_NAMES = {NORTH: "north", EAST: "east", SOUTH: "south", WEST: "west"}

# Matches FACING_STEP in por/savegame.py: y increases southward.
STEP = {NORTH: (0, -1), EAST: (1, 0), SOUTH: (0, 1), WEST: (-1, 0)}
OPPOSITE = {NORTH: SOUTH, EAST: WEST, SOUTH: NORTH, WEST: EAST}

# The two-bit barrier field, and what the game does with each value.
SOLID = 0
PASSABLE = 1          # an opening, or a door already open
LOCKED = 2            # prompts bash / pick / knock
WIZARD_LOCKED = 3     # the same, against the tougher bash table
BARRIER_NAMES = {SOLID: "solid", PASSABLE: "passable",
                 LOCKED: "locked", WIZARD_LOCKED: "wizard-locked"}

# A wall nibble of 0 means no wall. Otherwise it selects a slice of one of three
# wall sets loaded for the area, which is what WALLDEF holds.
SLICES_PER_WALLSET = 5


class GeoError(ValueError):
    """A GEO payload that is not 1024 bytes."""


class Geo:
    """One GEO file: a 16x16 grid of walls, doors and square attributes."""

    def __init__(self, payload: bytes | bytearray):
        if len(payload) != GEO_SIZE:
            raise GeoError(
                f"a GEO file is {GEO_SIZE} bytes, got {len(payload)}")
        self._data = bytes(payload)

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> "Geo":
        """Accept either the bare 1024 bytes or the PRG with its load address."""
        if len(data) == GEO_SIZE + 2:
            _, payload = split_load_address(bytes(data))
            return cls(payload)
        return cls(data)

    @classmethod
    def from_disk(cls, disk: D64 | str, name: bytes | str) -> "Geo":
        return cls(load_payload(disk, name))

    def to_bytes(self) -> bytes:
        return self._data

    # -- squares ---------------------------------------------------------

    def attributes(self, x: int, y: int) -> int:
        return self._data[ATTRIBUTES + self._index(x, y)]

    def is_indoor(self, x: int, y: int) -> bool:
        return bool(self.attributes(x, y) & INDOOR)

    def script_id(self, x: int, y: int, mask: int = SCRIPT_ID) -> int:
        """Which entry of the area's ECL jump table this square runs, if any.

        0 means no script. Pass the area's own mask -- `DUNGEON_FLOOR_MASK` for
        the dungeon-floor family, whose scripts use the two freed bits for
        encounter control instead.
        """
        return self.attributes(x, y) & mask

    # -- edges -----------------------------------------------------------

    def wall(self, x: int, y: int, direction: int) -> int:
        """The wall-art nibble on one edge. 0 means no wall."""
        i = self._index(x, y)
        if direction == NORTH:
            return self._data[WALLS_NORTH_EAST + i] >> 4
        if direction == EAST:
            return self._data[WALLS_NORTH_EAST + i] & 0x0F
        if direction == SOUTH:
            return self._data[WALLS_SOUTH_WEST + i] >> 4
        if direction == WEST:
            return self._data[WALLS_SOUTH_WEST + i] & 0x0F
        raise ValueError(f"{direction} is not a direction")

    def wallset(self, x: int, y: int, direction: int) -> tuple[int, int] | None:
        """`(wallset, slice)` into WALLDEF, or None where there is no wall."""
        v = self.wall(x, y, direction)
        if v == 0:
            return None
        return (v - 1) // SLICES_PER_WALLSET, (v - 1) % SLICES_PER_WALLSET

    def barrier(self, x: int, y: int, direction: int) -> int:
        """The raw two-bit field. Meaningless where there is no wall art."""
        b = self._data[BARRIERS + self._index(x, y)]
        return (b >> (2 * direction)) & 0x03

    def is_passable(self, x: int, y: int, direction: int) -> bool:
        """Can the party step this way?

        No wall art means yes, whatever the bits hold -- that is the engine's
        own order of tests, and getting it backwards is what sank the earlier
        readings.
        """
        if self.wall(x, y, direction) == 0:
            return True
        return self.barrier(x, y, direction) != SOLID

    def door(self, x: int, y: int, direction: int) -> int | None:
        """`PASSABLE`, `LOCKED` or `WIZARD_LOCKED` for a door; None otherwise."""
        if self.wall(x, y, direction) == 0:
            return None
        b = self.barrier(x, y, direction)
        return None if b == SOLID else b

    # -- whole-file checks ------------------------------------------------

    def reciprocity(self) -> tuple[int, int]:
        """`(agreements, edges)` on the raw barrier field between neighbours.

        Needs no ground truth: the east edge of a square *is* the west edge of
        its neighbour. Across all 29 files a correct parse scores 13793/13920 =
        0.991; the readings that were tried and abandoned scored about 0.3. Run
        it before trusting anything else a file says.

        It is deliberately the *raw* field and not `is_passable`. Wall art is
        only 0.960 reciprocal, so the two sides of an edge genuinely disagree
        about whether a wall is drawn there -- and that drags passability to
        0.958. Those are one-way edges, not parse errors, and folding them in
        would blunt the diagnostic.
        """
        agree = total = 0
        for y in range(GRID):
            for x in range(GRID):
                for direction in (EAST, SOUTH):
                    dx, dy = STEP[direction]
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < GRID and 0 <= ny < GRID):
                        continue
                    total += 1
                    agree += (self.barrier(x, y, direction)
                              == self.barrier(nx, ny, OPPOSITE[direction]))
        return agree, total

    def walkable_route(self, squares) -> bool:
        """True if every consecutive pair in `squares` is one legal step."""
        squares = list(squares)
        for (x0, y0), (x1, y1) in zip(squares, squares[1:]):
            step = (x1 - x0, y1 - y0)
            for direction, delta in STEP.items():
                if delta == step:
                    break
            else:
                return False
            if not self.is_passable(x0, y0, direction):
                return False
        return True

    # -- rendering --------------------------------------------------------

    def to_text(self, mark: dict[tuple[int, int], str] | None = None) -> str:
        """An ASCII floor plan.

        `---` a wall, `-.-` an opening, `-+-` a locked door, `-*-` wizard-locked;
        the same characters singly on vertical edges. `mark` puts a character in
        the middle of named squares, for the party or a route.
        """
        mark = mark or {}
        glyph = {PASSABLE: ".", LOCKED: "+", WIZARD_LOCKED: "*"}
        out = []
        for y in range(GRID):
            top = []
            body = []
            for x in range(GRID):
                top.append("+")
                d = self.door(x, y, NORTH)
                if self.wall(x, y, NORTH) == 0:
                    top.append("   ")
                else:
                    top.append("---" if d is None else f"-{glyph[d]}-")
                d = self.door(x, y, WEST)
                if self.wall(x, y, WEST) == 0:
                    body.append(" ")
                else:
                    body.append("|" if d is None else glyph[d])
                body.append(f" {mark.get((x, y), ' ')} ")
            top.append("+")
            d = self.door(GRID - 1, y, EAST)
            if self.wall(GRID - 1, y, EAST) == 0:
                body.append(" ")
            else:
                body.append("|" if d is None else glyph[d])
            out.append("".join(top))
            out.append("".join(body))
        bottom = []
        for x in range(GRID):
            bottom.append("+")
            d = self.door(x, GRID - 1, SOUTH)
            if self.wall(x, GRID - 1, SOUTH) == 0:
                bottom.append("   ")
            else:
                bottom.append("---" if d is None else f"-{glyph[d]}-")
        bottom.append("+")
        out.append("".join(bottom))
        return "\n".join(out)

    @staticmethod
    def _index(x: int, y: int) -> int:
        if not (0 <= x < GRID and 0 <= y < GRID):
            raise IndexError(f"({x}, {y}) is outside the {GRID}x{GRID} grid")
        return x + (y << 4)


def load_geo_files(disk: D64 | str) -> dict[str, Geo]:
    """Every GEO file on one game disk, keyed by its PETSCII name."""
    img = D64.open(disk) if isinstance(disk, str) else disk
    maps = {}
    for entry in img.directory():
        if entry.name.startswith(b"GEO"):
            maps[entry.name.decode("latin1")] = Geo.from_bytes(
                img.read_file(entry))
    return maps
