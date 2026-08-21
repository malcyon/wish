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

import pytest

from automap.paths import find_disks
from por.d64 import load_payload
from por.geo import (ATTRIBUTES, BARRIERS, GRID, PASSABLE, SOLID,
                     WALLS_NORTH_EAST, WALLS_SOUTH_WEST)


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
