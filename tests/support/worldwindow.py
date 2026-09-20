"""Helpers `test_world` shares with the test files that reuse them."""
from __future__ import annotations

from goldbox.world import (
    ROWS,
    STRIDE,
    TILE_COUNT,
    TILE_TABLE_SIZE,
)


def synthetic_window(fill: int = 0) -> bytes:
    """A well-formed `SQRDATA` payload built from the documented format, not
    copied from one: the grid holds `(x + y) % 120` so every square names a
    distinct-ish tile, and each of the 120 glyph entries holds its own index
    twice over, nine times, so `tile(i)` is checkable without reading a real
    file at all."""
    grid = bytes((x + y) % TILE_COUNT for y in range(ROWS) for x in range(STRIDE))
    tiles = bytearray(TILE_TABLE_SIZE)
    for i in range(TILE_COUNT):
        at = i * 18
        tiles[at:at + 9] = bytes([i & 0xFF]) * 9
        tiles[at + 9:at + 18] = bytes([(i + fill) & 0xFF]) * 9
    return grid + bytes(tiles)
