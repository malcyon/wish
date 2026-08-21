"""Game data comes from the player's own disks, never from this repository.

`CLAUDE.md` forbids committing the game's code, art or data files, and a test
fixture is not an exception -- a slice of `GEO04` in `tests/fixtures/` is the
same copy the rule forbids, merely renamed. So the tests that need real game
data read it off the player's disks at run time and skip when there are none.

That is a real cost: a bare checkout on a machine without the game verifies
less. It is the right cost. Where a test only needs *a* well-formed file rather
than a specific one, prefer `synthetic_geo` below, which is generated from the
format we documented and belongs to us.

Saved games are different and stay in `tests/fixtures/`: they are the player's
own data, produced by playing, and several of them capture states that no disk
still holds.
"""

from __future__ import annotations

import functools
import pathlib

import pytest

from automap.paths import find_disks
from por.d64 import load_payload
from por.geo import (
    ATTRIBUTES,
    BARRIERS,
    GRID,
    PASSABLE,
    SOLID,
    WALLS_NORTH_EAST,
    WALLS_SOUTH_WEST,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@functools.lru_cache(maxsize=1)
def disk_dir():
    """Where the player keeps their disks, or None."""
    return find_disks()


@functools.lru_cache(maxsize=None)
def _read(disk: str, name: bytes) -> bytes | None:
    try:
        return load_payload(disk, name)
    except Exception:
        return None


def game_file(name: str) -> bytes:
    """One file off whichever `POOL*.D64` carries it.

    Skips rather than fails when the disks are absent: not owning the game is
    not a broken checkout.
    """
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    encoded = name.encode() if isinstance(name, str) else name
    for disk in sorted(where.glob("POOL*.[dD]64")):
        payload = _read(str(disk), encoded)
        if payload is not None:
            return payload
    pytest.skip(f"no POOL disk here carries {name}")


needs_disks = pytest.mark.skipif(disk_dir() is None,
                                 reason="needs the game disks")


def synthetic_geo() -> bytes:
    """A GEO built from the format, not copied from one.

    Four 256-byte planes over a 16x16 grid. Enough structure to exercise the
    decoder without the repository holding a map somebody drew: a walled border,
    one interior room with a door in it, and one edge carrying wall art with no
    barrier, which is the case that separates art from passability.
    """
    planes = bytearray(4 * 0x100)

    def square(x: int, y: int) -> int:
        return y * GRID + x

    def set_wall(x, y, north=None, east=None, south=None, west=None):
        """North and south are the HIGH nibble of their byte, east and west the
        low one -- `Geo.wall` is the authority and this mirrors it exactly."""
        at = square(x, y)
        if north is not None:
            planes[WALLS_NORTH_EAST + at] |= (north & 0x0F) << 4
        if east is not None:
            planes[WALLS_NORTH_EAST + at] |= east & 0x0F
        if south is not None:
            planes[WALLS_SOUTH_WEST + at] |= (south & 0x0F) << 4
        if west is not None:
            planes[WALLS_SOUTH_WEST + at] |= west & 0x0F

    def set_barrier(x, y, north=SOLID, east=SOLID, south=SOLID, west=SOLID):
        """Two bits per edge, shifted by the direction's own number."""
        planes[BARRIERS + square(x, y)] = (
            (west << 6) | (south << 4) | (east << 2) | north)

    for i in range(GRID):
        set_wall(i, 0, north=1)
        set_wall(i, GRID - 1, south=1)
        set_wall(0, i, west=1)
        set_wall(GRID - 1, i, east=1)
    for i in range(GRID):
        set_barrier(i, 0, north=SOLID, east=PASSABLE, south=PASSABLE,
                    west=PASSABLE)

    # A room at (4,4)-(6,6) with a door on the west side of (4,5).
    for x in range(4, 7):
        set_wall(x, 4, north=2)
        set_wall(x, 6, south=2)
    for y in range(4, 7):
        set_wall(4, y, west=2)
        set_wall(6, y, east=2)
    set_barrier(4, 5, north=SOLID, east=PASSABLE, south=SOLID, west=PASSABLE)
    planes[ATTRIBUTES + square(5, 5)] = 0x80        # roofed

    # (9,9): art on every edge, every barrier passable -- four doors.
    set_wall(9, 9, north=3, east=3, south=3, west=3)
    set_barrier(9, 9, north=PASSABLE, east=PASSABLE,
                south=PASSABLE, west=PASSABLE)

    # (10,10): SOLID bits on every edge and NO art. The engine tests art first,
    # so this square is open on all four sides. Five earlier readings of the
    # format got exactly this backwards.
    set_barrier(10, 10, north=SOLID, east=SOLID, south=SOLID, west=SOLID)
    return bytes(planes)


# --- a combat arena, composed rather than captured ---------------------------

COMBAT_MODE = 0x6E11
COMBAT_PARAMS = 0x0600
COMBAT_CAMERA = 0x037E
COMBAT_MAP = 0x8C00
COMBAT_ROSTER = 0x8300
COMBAT_POSITIONS = 0x8B00
COMBAT_INITIATIVE = 0xA380
COMBAT_RECORDS = 0x4D00
ARENA_STRIDE = 56
ARENA_MAX_X, ARENA_MAX_Y = 55, 25
OFF_MAP = 0xFF


def synthetic_arena(fighters=((0, 25, 13), (8, 30, 13))) -> dict[int, bytes]:
    """A fight, built from the player's own saves plus generated structures.

    This replaces a capture of live machine memory. A capture was the quick way
    to get a fixture, but it contains whatever game code happened to be resident
    at the time, which is exactly what the repository must not carry.

    Everything here is either the player's own data -- the character records out
    of `savedgame0.bin` and the roster out of `savedgame1.bin`, both saved games
    that would sit on a save disk -- or generated from the format:

    * the parameter block at `$0600`, which is what the reader must consult
      rather than assuming 56 x 26;
    * the map at `$8C00`, empty floor with bit 7 set under each combatant;
    * the position table at `$8B00`, `$FF $FF` for everyone not fighting.

    `fighters` is `(index, x, y)`, index 0-7 the party and 8 upward monsters.
    The party fighter must be an index the saved roster actually fills --
    `savedgame1.bin` holds one, at 0 -- or it has no record and is skipped.
    """
    from por.encoding import COMBAT_BIAS
    from por.savegame import (
        ROSTER_ARMOUR_CLASS,
        ROSTER_HP_CURRENT,
        ROSTER_MOVEMENT,
        ROSTER_STRIDE,
        ROSTER_THAC0,
        SAVE0_LOAD_ADDRESS,
        SAVE1_LOAD_ADDRESS,
    )
    ROSTER_RECORD_SLOT = 0x0D

    save0 = (FIXTURES / "savedgame0.bin").read_bytes()[2:]
    save1 = (FIXTURES / "savedgame1.bin").read_bytes()[2:]

    params = bytearray(0x14)
    params[0x02] = COMBAT_MAP & 0xFF
    params[0x03] = COMBAT_MAP >> 8
    params[0x04] = COMBAT_POSITIONS & 0xFF
    params[0x05] = COMBAT_POSITIONS >> 8
    params[0x06] = 64                                   # combatant slots
    params[0x07] = ARENA_STRIDE
    params[0x12] = ARENA_MAX_X
    params[0x13] = ARENA_MAX_Y

    squares = ARENA_STRIDE * (ARENA_MAX_Y + 1)
    field = bytearray(squares)
    # A block of impassable terrain in view of the fight, so the renderer has
    # something to draw besides floor. Bit 7 is "a combatant stands here"; the
    # low bits are the square's own kind.
    for y in range(11, 16):
        for x in range(20, 23):
            field[y * ARENA_STRIDE + x] = 0x01
    positions = bytearray([OFF_MAP]) * (64 * 4)
    for index, x, y in fighters:
        at = index * 4
        positions[at:at + 4] = bytes([x, y, (index * 4) & 0xFF, 0])
        field[y * ARENA_STRIDE + x] |= 0x80             # someone stands here

    # The roster runs past $83FF, so take it from the save and lay the
    # generated position table on top at $8B00.
    #
    # A saved game only carries eight roster blocks; index 8 and up land in
    # what was resident code when the range was dumped. So every monster gets a
    # block built here, copied from a real one and pointed at its own record --
    # without that, the slot pointer is garbage and the monster has no name.
    roster = bytearray(save1[:COMBAT_POSITIONS - SAVE1_LOAD_ADDRESS])
    for index, _x, _y in fighters:
        if index < 8:
            continue
        at = index * ROSTER_STRIDE
        block = bytearray(roster[:ROSTER_STRIDE])
        block[ROSTER_RECORD_SLOT] = index
        block[ROSTER_HP_CURRENT] = 5
        # The derived combat numbers come from here, not from the record.
        block[ROSTER_THAC0] = COMBAT_BIAS - 19
        block[ROSTER_ARMOUR_CLASS] = COMBAT_BIAS - 6
        block[ROSTER_MOVEMENT] = 9
        roster[at:at + ROSTER_STRIDE] = block
    roster += positions

    # Descending, so the first fighter listed acts first and the round is
    # plainly not over.
    initiative = bytearray(64)
    for n, (index, _x, _y) in enumerate(fighters):
        initiative[index] = len(fighters) - n

    records_at = COMBAT_RECORDS - SAVE0_LOAD_ADDRESS
    records = bytearray(save0[records_at:records_at + 12 * 0x100])

    # Slot 8 holds no record in a saved game -- combat slots are live-only --
    # so build a monster there. An ORC, with the Monster Manual's numbers, so
    # the tooltip has something real to be checked against.
    orc = bytearray(records[0:0x100])                   # a valid record's shape
    orc[0x000:0x014] = b"ORC".ljust(0x14, b"\x00")
    orc[0x0A0] = 1                                      # one hit die
    orc[0x0E1] = COMBAT_BIAS - 6                        # armour class 6
    orc[0x071] = COMBAT_BIAS - 19                       # THAC0 19
    orc[0x09F] = 9                                      # movement
    orc[0x076:0x078] = (5).to_bytes(2, "little")        # hit points, 16-bit
    orc[0x0D9] = 2                                      # attacks per round, x2
    orc[0x0DA:0x0DE] = bytes([1, 8, 0, 0])              # 1d8
    orc[0x0F7], orc[0x0F8], orc[0x0F9] = 10, 0, 1       # 10 + 1 a hit point
    records[8 * 0x100:9 * 0x100] = orc

    return {
        COMBAT_CAMERA: bytes([max(0, fighters[0][1] - 3),
                              max(0, fighters[0][2] - 3)]),
        COMBAT_PARAMS: bytes(params),
        COMBAT_RECORDS: bytes(records),
        COMBAT_MODE: bytes([2]),
        COMBAT_ROSTER: bytes(roster),
        COMBAT_MAP: bytes(field),
        COMBAT_INITIATIVE: bytes(initiative),
    }


def disk_path(stem: str):
    """The path to a named disk, or None. Never skips.

    Safe at module level, which `game_disk` is not: `pytest.skip` outside a test
    needs `allow_module_level`. Pair this with the `needs_disks` marker so the
    module skips as a whole when there are no disks.
    """
    where = disk_dir()
    if where is None:
        return None
    for name in (f"{stem}.D64", f"{stem}.d64", f"{stem}.D64.orig"):
        candidate = where / name
        if candidate.exists():
            return candidate
    return None


def game_disk(stem: str = "POOL1"):
    """The path to one of the player's game disks, or skip.

    Some readers want a disk to open rather than a payload -- `load_item_names`
    and `load_item_templates` take a path. Prefer `game_file` where a payload
    will do; this is for the rest.

    Several tests used to hardcode `work/POOL1.D64.orig` or an absolute path on
    somebody's machine. Both are invisible on CI, and one of them named a
    directory that no longer exists anywhere.
    """
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    for name in (f"{stem}.D64", f"{stem}.d64", f"{stem}.D64.orig"):
        candidate = where / name
        if candidate.exists():
            return candidate
    pytest.skip(f"no {stem} disk where the game disks are")


def save_disk(stem: str = "PORSAVE"):
    """The path to one of the player's save disks, or skip."""
    where = disk_dir()
    if where is None:
        pytest.skip("needs the save disks; set POR_DISKS to where they are")
    for name in (f"{stem}.D64", f"{stem}.d64"):
        candidate = where / name
        if candidate.exists():
            return candidate
    pytest.skip(f"no {stem} where the disks are")
