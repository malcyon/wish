"""`tools/genexits.py` re-derives `automap.fasttravel.EXIT_ROUTES` off the
player's own disks; this checks the two agree, the same shape
`tests/test_newecl.py` already holds `automap/fasttravel.py`'s address table
to. A mismatch here means the table was pasted from an older run of the
generator, not a bug in `FastTravel` itself.

`pick_square` and `outward_facings` are pure logic and need no disk, so they
are pinned separately against a small synthetic `Geo` -- `tests/test_geo.py`'s
own precedent for exercising `goldbox.geo.Geo` without a real map.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox.geo import GEO_SIZE, Geo  # noqa: E402
from tests.gamedata import needs_disks  # noqa: E402
from tools import genexits as G  # noqa: E402


def flat_geo(open_dirs: dict[tuple[int, int, int], bool] = None) -> Geo:
    """A 16x16 map with wall art on every edge, open only where told --
    `is_passable` reads "no wall" as open, so this needs wall art everywhere
    to make the closed squares actually closed."""
    data = bytearray(GEO_SIZE)
    data[0:0x100] = bytes([0x11]) * 0x100   # north/east wall art nibble each
    data[0x100:0x200] = bytes([0x11]) * 0x100
    geo = Geo(bytes(data))
    return geo


# ---------------------------------------------------------------------------
# outward_facings -- pure geometry, no disk
# ---------------------------------------------------------------------------

def test_outward_facings_names_every_direction_a_corner_can_leave_by():
    assert set(G.outward_facings(0, 0)) == {0, 3}     # north and west
    assert set(G.outward_facings(15, 15)) == {1, 2}   # east and south


def test_outward_facings_is_empty_off_the_boundary():
    assert G.outward_facings(7, 7) == []


# ---------------------------------------------------------------------------
# pick_square -- against a small synthetic Geo, not the real disks
# ---------------------------------------------------------------------------

def test_pick_square_takes_the_first_candidate_when_not_gated():
    assert G.pick_square(None, [(3, 3), (4, 4)], gated=False) == (3, 3)


def test_pick_square_skips_a_gated_square_with_no_open_outward_wall():
    geo = flat_geo()                        # every edge walled and solid
    assert G.pick_square(geo, [(0, 0), (7, 15)], gated=True) is None


def test_pick_square_finds_the_first_gated_square_that_is_actually_open():
    data = bytearray(GEO_SIZE)
    data[0:0x100] = bytes([0x11]) * 0x100
    data[0x100:0x200] = bytes([0x11]) * 0x100
    # (7, 15) facing south (index 4*7 = 28 in the south/west plane's low
    # nibble... simplest: clear the wall nibble at (7, 15)'s south edge, the
    # high nibble of the south/west plane).
    i = 7 + (15 << 4)
    data[0x100 + i] = data[0x100 + i] & 0x0F   # south nibble = 0: no wall
    geo = Geo(bytes(data))
    assert geo.is_passable(7, 15, 2)           # south is open
    assert G.pick_square(geo, [(0, 0), (7, 15)], gated=True) == (7, 15, 2)


def test_pick_square_returns_none_off_an_empty_route():
    assert G.pick_square(None, [], gated=False) is None


# ---------------------------------------------------------------------------
# build() -- the real disks, compared against the committed table
# ---------------------------------------------------------------------------

@needs_disks
def test_the_committed_table_matches_a_fresh_generation():
    from automap import fasttravel as F

    rows, _skipped = G.build()
    committed = {key: (r.entry, r.square) for key, r in F.EXIT_ROUTES.items()}
    assert rows == committed, (
        "automap/fasttravel.py's EXIT_ROUTES is stale -- rerun "
        "tools/genexits.py and paste its output in")


@needs_disks
def test_the_kobold_caves_exit_is_a_direct_route_to_the_east_window():
    """`#207 (Run an exit's own handler before Fast Travel warps out)`'s own
    motivating case: `ECL0D` (area 13) has a scripted exit straight to area
    27, and it is the one whose handler drops Princess Fatima."""
    rows, _skipped = G.build()
    assert (13, 27) in rows
    entry, square = rows[(13, 27)]
    assert entry == 1                  # dispatched from entry 1, a square exit
    assert len(square) == 2            # not gated: no facing needed
