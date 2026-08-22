"""P20: where a warp lands a party in an area with no arrival square.

Fifteen of the thirty areas have no arrival square harvested from the scripts,
and for those `Warp` picks one off the `GEO` with
`automap.actions.walkable_square`. Driving the game found what that rule
actually does (`work/reports/p20-arrivals.md`); what is testable without an
emulator is the geometry underneath it, and that is what is asserted here.

The maps come off the player's own disks and these skip without them.
"""

from __future__ import annotations

import pytest
from gamedata import game_file

from automap.actions import walkable_square
from por import areas
from por.geo import GRID, Geo

#: Every map on the disks, once, with the area that loads it.
MAPS = sorted({g for a in areas.AREAS for g in a.geos})

#: The fifteen with no harvested arrival square. Eleven have a map; four do not
#: and get no square at all, which is what the game itself has to cope with.
NO_ARRIVAL = tuple(a.id for a in areas.AREAS if a.arrival is None)

#: Maps where the corner square `walkable_square` picks is walled off from the
#: bulk of the map. Measured, and the reason `landing_square` exists.
POCKETS = {"GEO01": 15, "GEO05": 32, "GEO17": 40, "GEO19": 30, "GEO1A": 16,
           "GEO1B": 48}


def geo(name: str) -> Geo:
    return Geo(game_file(name))


def largest(g: Geo) -> set[tuple[int, int]]:
    return max(areas.components(g), key=len)


def test_fifteen_areas_have_no_arrival_square():
    assert NO_ARRIVAL == (3, 4, 5, 8, 9, 11, 15, 19, 20, 21, 25, 26, 27, 29, 30)


def test_four_of_them_have_no_map_either():
    """Areas 8, 11, 19 and 30 load no `GEO`, so there is no square to choose."""
    assert [i for i in NO_ARRIVAL if not areas.AREAS_BY_ID[i].geos] == \
        [8, 11, 19, 30]


@pytest.mark.parametrize("name", MAPS)
def test_the_shipped_fallback_always_picks_the_corner(name):
    """`walkable_square` scans from (0,0) and (0,0) is never fully walled in.

    So the rule is not "a walkable square" in any useful sense: it is "(0,0)",
    on all twenty-nine maps. Pinned because it is the thing P20 measured.
    """
    picked = walkable_square(geo(name))
    assert picked is not None
    assert picked[:2] == (0, 0)


@pytest.mark.parametrize("name", sorted(POCKETS))
def test_the_corner_is_a_pocket_on_six_maps(name):
    """(0,0) is cut off from the bulk of the map, so a party landed there is."""
    g = geo(name)
    corner = next(c for c in areas.components(g) if (0, 0) in c)
    assert len(corner) == POCKETS[name]
    assert len(corner) < len(largest(g))


@pytest.mark.parametrize("name", MAPS)
def test_landing_square_is_in_the_largest_component(name):
    g = geo(name)
    square = areas.landing_square(g)
    assert square is not None
    x, y, facing = square
    assert (x, y) in largest(g)
    assert 0 <= x < GRID and 0 <= y < GRID
    assert g.is_passable(x, y, facing)


@pytest.mark.parametrize("name", MAPS)
def test_landing_square_stays_off_the_outer_ring(name):
    """The edge squares are where the game's own exits live; do not start on one."""
    x, y, _ = areas.landing_square(geo(name))
    assert 0 < x < GRID - 1 and 0 < y < GRID - 1


def test_components_partition_the_grid():
    """Every square belongs to exactly one component, on every map."""
    for name in MAPS:
        comps = areas.components(geo(name))
        seen = [p for c in comps for p in c]
        assert len(seen) == GRID * GRID == len(set(seen))
