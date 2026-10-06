"""`tools/generate/genexits.py` re-derives `automap.fasttravel.EXIT_ROUTES` off the
player's own disks; this checks the two agree, the same way
`tests/areas/test_newecl.py` already holds `automap/fasttravel.py`'s address table
to. A mismatch here means the table was pasted from an older run of the
generator, not a bug in `FastTravel` itself.

`pick_square` and `outward_facings` are pure logic and need no disk, so they
are pinned separately against a small synthetic `Geo` -- `tests/areas/test_geo.py`'s
own precedent for exercising `goldbox.geo.Geo` without a real map.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from gamedata import needs_disks  # noqa: E402

from goldbox.geo import GEO_SIZE, Geo  # noqa: E402
from tools.generate import genexits as G  # noqa: E402


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


def test_pick_square_keeps_the_facing_a_script_tests():
    assert G.pick_square(None, [(5, 7, 3), (6, 7, 1)], gated=False) == (5, 7, 3)


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
        "tools/generate/genexits.py and paste its output in")


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


@needs_disks
def test_valjevo_and_lizardman_exits_stand_where_the_script_tests():
    """Entry 0 of `ECL07` leaves only from (5,7) facing W, and `ECL10` only
    from (8,15) facing S; the arm index is not the square id, and the reader's
    table gives both without a per-script override."""
    from automap import fasttravel as F

    assert not hasattr(G, "SCRIPT_SQUARES")
    rows, _skipped = G.build()
    assert rows[(7, 5)] == (0, (5, 7, 3))
    assert rows[(16, 27)] == (0, (8, 15, 2))
    assert F.EXIT_ROUTES[(7, 5)].square == (5, 7, 3)
    assert F.EXIT_ROUTES[(16, 27)].square == (8, 15, 2)


@needs_disks
def test_the_travel_grid_seams_get_no_square_route():
    """The windows' seams leave on the grid column and heading, which a
    `GEO` square cannot stand for, so they get no row."""
    from automap import fasttravel as F

    rows, skipped = G.build()
    seams = {(25, 26), (26, 25), (26, 27), (27, 26)}
    assert seams.isdisjoint(rows)
    assert seams.isdisjoint(F.EXIT_ROUTES)
    grid = {(name, target) for name, _at, target, reason in skipped
            if reason.startswith("a travel-grid edge")}
    assert grid == {("ECL19", 26), ("ECL1A", 27), ("ECL1A", 25),
                    ("ECL1B", 26)}


def test_pick_square_keeps_a_gated_squares_tested_facing_and_no_other():
    open_map = Geo(bytes(GEO_SIZE))          # no walls: every edge is open
    assert G.pick_square(open_map, [(0, 0, 3)], gated=True) == (0, 0, 3)
    assert G.pick_square(open_map, [(0, 0, 1), (15, 4, 1)],
                         gated=True) == (15, 4, 1)


@needs_disks
def test_the_seven_facing_exits_get_the_edge_their_facing_leaves_by():
    """`ECL02` east and west, `ECL0E` south and all four of `ECL12`'s arms
    test the facing; each gets a row standing on its own edge."""
    from automap import fasttravel as F

    expected = {
        (2, 15): (0, (15, 3, 1)), (2, 26): (0, (0, 3, 3)),
        (14, 24): (0, (4, 15, 2)),
        (18, 2): (0, (4, 15, 2)), (18, 9): (0, (4, 0, 0)),
        (18, 26): (0, (0, 4, 3)), (18, 29): (0, (15, 4, 1)),
    }
    rows, _skipped = G.build()
    assert {key: rows.get(key) for key in expected} == expected
    assert {key: (F.EXIT_ROUTES[key].entry, F.EXIT_ROUTES[key].square)
            for key in expected if key in F.EXIT_ROUTES} == expected


@needs_disks
def test_yarashs_pyramid_exits_stand_on_the_squares_their_tables_name():
    """`ECL16` and `ECL17` read the entry-1 arm through a table indexed by
    the square id; the rows stand where the exits run, and the Nomad Camp
    and the travel-grid sites, which no square selects, get no row."""
    from automap import fasttravel as F

    expected = {(22, 23): (1, (14, 7)), (22, 26): (1, (13, 15)),
                (23, 22): (1, (6, 0))}
    rows, skipped = G.build()
    assert {key: rows.get(key) for key in expected} == expected
    assert {key: (F.EXIT_ROUTES[key].entry, F.EXIT_ROUTES[key].square)
            for key in expected if key in F.EXIT_ROUTES} == expected
    assert (17, 26) not in rows and (17, 26) not in F.EXIT_ROUTES
    reasons = {(name, target): reason for name, _at, target, reason in skipped}
    assert reasons[("ECL11", 26)].startswith("entry 1 picks this branch")
    sites = {(name, target) for name, _at, target, reason in skipped
             if reason.startswith("a travel-grid site")}
    assert {("ECL19", 19), ("ECL19", 28), ("ECL1A", 0), ("ECL1B", 0)} <= sites


@needs_disks
def test_the_routes_that_check_a_scratch_byte_are_the_pinned_ones():
    """A route that tests `$4A00`-`$4A1F` can `EXIT` silently, because a
    fast travel arrives with that range zeroed. Read the new row's gate, and
    add an `EXIT_PRESETS` row if it can `EXIT`."""
    from tools.areas.eclexitkinds import analyse

    by_ecl = G.area_by_ecl(G.TITLE)
    machine = G.W.Machine()
    rows, _skipped = G.build()
    scratch = set()
    for name, (side, body) in G.W.scripts().items():
        from_area = by_ecl.get(name)
        if from_area is None:
            continue
        _gside, gbody = G.W._file("GEO" + name[3:])
        geo = Geo.from_bytes(gbody) if gbody is not None else None
        _script, analysed = analyse(machine, name, side, body, geo)
        for r in analysed:
            key = (from_area, r["target"])
            if key in rows and "scratch" in r["features"]:
                scratch.add(key)
    assert scratch == {(0, 8), (0, 11), (0, 21), (0, 26), (0, 27), (1, 25),
                       (21, 0), (28, 25)}
