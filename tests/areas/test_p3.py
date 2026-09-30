from __future__ import annotations

"""The disk half of the P3 wilderness finding, so it cannot rot silently.

`reports/p3-saves.md` (scratch, deleted) §4 reported that 648 bytes read live at `$8C00`
matched `SQRDATA05` in 647 of 648 bytes and `SQRDATA06` in 645 of 648, and that
**every byte that differed was a site square the scripts paint over while its
flag is clear** -- `reports/world-map.md` (scratch, deleted) §7's table, value for value.

The live half needs an emulator and is not testable here. The disk half is:
the four squares must hold the *unpainted* artwork the comparison found, at the
offsets the `y * 18 + x` index puts them, and no other square may hold the paint
value at those coordinates. If a future change to the index arithmetic or to
the disk reader moves any of this, the finding stops meaning what it says.

Nothing is committed: the bytes come off the player's own disks through
`game_file`, which skips when there are none.
"""


import pytest
from gamedata import game_file

from goldbox.world import UNDISCOVERED_PAINT, WINDOW_NAMES

#: The grid is 18 wide and 36 tall, one byte a square, indexed `y * 18 + x`.
#: That is `$0612 + 1`, read off `GDRIVE00 $C3AF`, and *not* `$0607` = 20.
STRIDE = 18
GRID = STRIDE * 36

PAINTED = [(WINDOW_NAMES[window], x, y, disk, paint)
           for window, x, y, disk, paint in UNDISCOVERED_PAINT]


@pytest.mark.parametrize("name,x,y,disk,paint", PAINTED)
def test_the_site_squares_hold_their_undiscovered_artwork(name, x, y, disk, paint):
    grid = game_file(name)[:GRID]
    assert len(grid) == GRID
    assert grid[y * STRIDE + x] == disk
    assert disk != paint


def test_the_three_windows_are_the_documented_sizes():
    """648 bytes of grid, then 120 glyph entries of 18 bytes each.

    `SQRDATA05` is 2808 exactly; the other two carry eight spare bytes. The
    arithmetic closing on the nose is what fixed the layout in the first place.
    """
    assert len(game_file("SQRDATA05")) == GRID + 120 * 18
    for name in ("SQRDATA04", "SQRDATA06"):
        assert len(game_file(name)) == GRID + 120 * 18 + 8
