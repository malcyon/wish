from __future__ import annotations

"""P20: where a fasttravel lands a party in an area with no arrival square.

Fourteen of the thirty areas have no arrival square harvested from the scripts,
and for those `FastTravel` picks one off the `GEO` with `goldbox.areas.landing_square`.
The rule that used to ship took the first square with any passable edge;
driving the game found what that came to (`reports/p20-arrivals.md`, scratch, deleted), and
what is testable without an emulator is the geometry underneath it, which is
what is asserted here.

The maps come off the player's own disks and these skip without them.
"""


import pytest
from gamedata import game_file

from goldbox import areas
from goldbox.geo import (
    BARRIERS,
    GRID,
    PASSABLE,
    WALLS_NORTH_EAST,
    WALLS_SOUTH_WEST,
    Geo,
)

#: Every map on the disks, once, with the area that loads it.
MAPS = sorted({g for a in areas.AREAS for g in a.geos})

#: The fourteen with no harvested arrival square. Eleven have a map; three do
#: not and get no square at all, which is what the game itself has to cope
#: with. **This said ten and four until 2026-09-07**, when area 30 turned out
#: to load `GEO12` after all -- the same stale count the test two lines below
#: carried, in the same file, missed by the change that fixed the test
#: (`#260 (Area 30 is recorded as having no map, and ECL1E loads GEO12)`).
NO_ARRIVAL = tuple(a.id for a in areas.AREAS if a.arrival is None)

#: Maps where the corner the retired rule picked is walled off from the bulk of
#: the map. Measured, and the reason `landing_square` exists.
POCKETS = {"GEO01": 15, "GEO05": 32, "GEO17": 40, "GEO19": 30, "GEO1A": 16,
           "GEO1B": 48}


def geo(name: str) -> Geo:
    return Geo(game_file(name))


def largest(g: Geo) -> set[tuple[int, int]]:
    return max(areas.components(g), key=len)


def first_passable(g: Geo) -> tuple[int, int, int] | None:
    """The retired rule, kept here because P20 measured it and nothing else
    runs it: the first square, scanning y then x, with any passable edge."""
    for y in range(GRID):
        for x in range(GRID):
            for facing in range(4):
                if g.is_passable(x, y, facing):
                    return (x, y, facing)
    return None


def test_fourteen_areas_have_no_arrival_square():
    """Area 21 used to be the fifteenth: P20 found Sokol Keep's square in
    `ECL15`'s own bytecode and `goldbox/areas.py` carries it now."""
    assert NO_ARRIVAL == (3, 4, 5, 8, 9, 11, 15, 19, 20, 25, 26, 27, 29, 30)
    assert areas.AREAS_BY_ID[21].arrival == areas.Arrival(8, 14, 0)


def test_three_of_them_have_no_map_either():
    """Areas 8, 11 and 19 load no `GEO`, so there is no square to choose.

    Area 30 used to be a fourth: `ECL1E` was believed to issue no `LOADFILES`
    at all, until `#260 (Area 30 is recorded as having no map, and ECL1E loads
    GEO12)` found it loads `GEO12` -- it still has no arrival square, since
    nothing in `ECL1E`'s bytecode names one."""
    assert [i for i in NO_ARRIVAL if not areas.AREAS_BY_ID[i].geos] == \
        [8, 11, 19]


def test_the_retired_fallback_always_picked_the_corner():
    """It scanned from (0,0), and (0,0) is never fully walled in.

    So the rule was not "a walkable square" in any useful sense: it was
    "(0,0)", on all twenty-nine maps. Pinned because it is the thing P20
    measured and the reason the rule was replaced. Every map is read in one
    pass and the ones that disagree are named together.
    """
    disagree = {}
    for name in MAPS:
        picked = first_passable(geo(name))
        if picked is None or picked[:2] != (0, 0):
            disagree[name] = picked
    assert not disagree


@pytest.mark.parametrize("name", sorted(POCKETS))
def test_the_corner_is_a_pocket_on_six_maps(name):
    """(0,0) is cut off from the bulk of the map, so a party landed there is."""
    g = geo(name)
    corner = next(c for c in areas.components(g) if (0, 0) in c)
    assert len(corner) == POCKETS[name]
    assert len(corner) < len(largest(g))


#: The six maps where the retired rule's corner is walled off, plus the first
#: two others in `MAPS` order. Computed from `POCKETS` and `MAPS`, so it stays
#: right when either changes. On every other map `landing_square` takes the same
#: branch and covers the same lines, so these are the ones that differ in
#: structure.
LANDING_MAPS = sorted(POCKETS) + [m for m in MAPS if m not in POCKETS][:2]


@pytest.mark.parametrize(
    "name", [pytest.param(m, id=m) for m in LANDING_MAPS])
def test_landing_square_is_in_the_largest_component_off_the_outer_ring(name):
    """The edge squares are where the game's own exits live; do not start on one."""
    g = geo(name)
    square = areas.landing_square(g)
    assert square is not None
    x, y, facing = square
    assert (x, y) in largest(g), "the square is not in the largest component"
    assert g.is_passable(x, y, facing), "the facing is not a passable edge"
    assert 0 < x < GRID - 1 and 0 < y < GRID - 1, \
        "the square is on the outer ring"


def test_landing_square_falls_back_to_the_ring_when_the_component_has_no_inner_square():
    """The largest component is the top row, so every square in it is on the
    outer ring, and the rule has to take one of those rather than nothing.
    No map on the disks is like this, so this is the only test that runs the
    fallback."""
    planes = bytearray(4 * 0x100)
    for i in range(GRID * GRID):
        planes[WALLS_NORTH_EAST + i] = 0x11         # art on north and east
        planes[WALLS_SOUTH_WEST + i] = 0x11         # art on south and west
    # Every barrier is SOLID except the top row's east and west edges, which
    # join it into one corridor of sixteen squares.
    for x in range(GRID):
        planes[BARRIERS + x] = (
            (PASSABLE << 2 if x < GRID - 1 else 0)
            | (PASSABLE << 6 if x > 0 else 0))
    g = Geo(bytes(planes))
    assert areas.landing_square(g) is not None
    x, y, facing = areas.landing_square(g)
    assert (x, y) in largest(g)
    assert len(largest(g)) == GRID
    assert g.is_passable(x, y, facing)


def test_components_partition_the_grid():
    """Every square belongs to exactly one component, on every map."""
    for name in MAPS:
        comps = areas.components(geo(name))
        seen = [p for c in comps for p in c]
        assert len(seen) == GRID * GRID == len(set(seen))


def test_only_area_30_is_closed_to_a_fasttravel():
    """`ECL1E` is the attract-mode demo. FastTraveled into, `$C04B`-`$C04D` read
    254,127,16, no map was resident and the PC never came back to the key-wait
    loop, so no later fasttravel could be started -- the session was over."""
    assert [a.id for a in areas.AREAS if not a.fasttravelable] == [30]


def test_the_fasttravel_action_refuses_the_attract_mode_demo():
    """Refused in the engine as well as absent from the dropdown, because the
    refusal is what protects a caller that did not come through the row."""
    from test_debugmode import IN_THE_LOOP, machine

    from automap.actions import FastTravel

    target = machine(area=0)
    target._pc = IN_THE_LOOP
    verdict = FastTravel().legality(target, areas.AREAS_BY_ID[30])
    assert not verdict
    assert "attract-mode demo" in verdict.reason
    assert not FastTravel().apply(target, area=areas.AREAS_BY_ID[30]).ok


def test_the_engine_picks_its_landing_square_from_por_areas():
    """One rule, not two: `automap.actions` is a seam onto this module."""
    from automap import actions
    g = geo(MAPS[0])
    assert actions.landing_square(g) == areas.landing_square(g)
    assert actions.landing_square(None) is None
