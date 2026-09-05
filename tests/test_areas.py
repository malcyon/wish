from __future__ import annotations

"""The area table, and the title key that stops it lying about Curse.

The table's claims are checked against the game's own scripts where those are
present under `work/ecl-scripts/` -- disassemblies produced by this project,
not game data -- and skipped where they are not, exactly as `tests/gamedata.py`
skips when no disk is attached.
"""


import pathlib
import re

import pytest

from automap.state import AREA_NAMES, AutomapState
from goldbox import areas
from goldbox.areas import (
    CURSE_OF_THE_AZURE_BONDS,
    POOL_OF_RADIANCE,
    Arrival,
    Confidence,
)

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "work" / "ecl-scripts"


# -- the shape of the table --------------------------------------------------


def test_thirty_areas_with_one_hole_at_twelve():
    """Thirty scripts and twenty-nine maps. `ECL0C` does not exist."""
    ids = [a.id for a in areas.AREAS]
    assert len(ids) == 30
    assert ids == sorted(ids)
    assert areas.MISSING_ID not in ids
    assert set(ids) == set(range(31)) - {areas.MISSING_ID}
    assert areas.area(areas.MISSING_ID) is None


def test_the_id_is_the_ecl_number_in_hex():
    """Area 21 is `ECL15`, which is why `area_name` can read a `GEO`'s digits."""
    assert areas.area(21).ecl == "ECL15"
    assert areas.area(10).ecl == "ECL0A"
    for a in areas.AREAS:
        assert int(a.ecl[3:], 16) == a.id


def test_twenty_nine_maps_across_thirty_areas_and_none_shared():
    names = [g for a in areas.AREAS for g in a.geos]
    assert len(names) == 29
    assert len(set(names)) == 29


@pytest.mark.parametrize("id", [8, 11, 19, 30])
def test_four_areas_have_no_map_at_all(id):
    """`ECL08`, `ECL0B`, `ECL13` and `ECL1E` issue no `LOADFILES`."""
    a = areas.area(id)
    assert a.geos == ()
    assert a.geo is None
    assert not a.has_map
    assert areas.geos_for_area(id) == ()


@pytest.mark.parametrize("id,pair", [(16, ("GEO10", "GEO1E")),
                                     (24, ("GEO18", "GEO1F")),
                                     (29, ("GEO1D", "GEO20"))])
def test_three_areas_carry_two_maps(id, pair):
    """A caller asking "which GEO is area 29" gets two, not a first guess."""
    a = areas.area(id)
    assert a.geos == pair
    assert a.geo is None, "two maps must not collapse to one"
    assert areas.geos_for_area(id) == pair


def test_the_geo_to_area_direction_is_a_tuple_too():
    """Nothing in the format stops two scripts naming one map -- `ECL07`
    already loads `GEO03` on its way into area 5 -- so the reverse index never
    promises exactly one answer."""
    assert [a.id for a in areas.areas_for_geo("GEO15")] == [21]
    assert [a.id for a in areas.areas_for_geo("GEO20")] == [29]
    assert areas.areas_for_geo("GEO0C") == ()
    assert areas.areas_for_geo("nonsense") == ()
    for name in ("GEO15", "GEO20"):
        assert isinstance(areas.areas_for_geo(name), tuple)


def test_the_three_outdoor_areas_carry_a_sqrdata():
    outdoors = [a for a in areas.AREAS if a.outdoors]
    assert [a.id for a in outdoors] == [25, 26, 27]
    assert [a.sqrdata for a in outdoors] == ["SQRDATA04", "SQRDATA05",
                                             "SQRDATA06"]
    assert all(a.geos for a in outdoors), "they load a GEO as well"
    assert all(not a.outdoors for a in areas.AREAS if a.id not in (25, 26, 27))


def test_the_three_windows_carry_an_overland_square_inside_the_walkable_band():
    """`Area.overland` is `$49C3`/`$49C4`, written by a fast travel to areas
    25-27 (`#178 (Fast Travel to the wilderness leaves the party on whatever
    overland square it last stood on)`), never the `$C04B` `arrival` these
    three do not have. The walkable band is `docs/113-world-map.md`'s: (0, 0)
    is inside the 18x36 grid and outside it, and a fasttraveled party has had
    to walk to the first legal square from there."""
    for a in areas.AREAS:
        if a.id in (25, 26, 27):
            assert a.overland is not None, a.id
            x, y = a.overland
            assert 2 <= x <= 15, a.id
            assert 2 <= y <= 33, a.id
            assert a.arrival is None, "$C04B is not GDRIVE00's square here"
        else:
            assert a.overland is None, a.id


def test_ecl1e_is_unidentified_and_says_so():
    a = areas.area(30)
    assert a.name is None
    assert a.confidence is Confidence.UNKNOWN
    assert a.label == "ECL1E - no map, POOL1"


def test_every_row_carries_a_confidence():
    assert all(isinstance(a.confidence, Confidence) for a in areas.AREAS)
    assert {a.confidence for a in areas.AREAS} == {
        Confidence.CONFIRMED, Confidence.PROBABLE, Confidence.UNKNOWN}
    # The five POOL5 castle floors are the PROBABLE ones, plus the lower
    # pyramid: which floor is which has never been read.
    probable = {a.id for a in areas.AREAS
                if a.confidence is Confidence.PROBABLE}
    assert probable == {3, 4, 5, 6, 7, 23}


def test_arrival_squares_where_they_are_known():
    known = {a.id: a.arrival for a in areas.AREAS if a.arrival}
    # Sixteen: fifteen harvested from the scripts, and Sokol Keep's, which P20
    # found in `ECL15`'s own bytecode -- `work/reports/p20-arrivals.md`.
    assert len(known) == 16
    assert known[21] == Arrival(8, 14, 0)
    assert known[0] == Arrival(15, 1, 3)
    assert str(known[0]) == "15,1 W"
    # Area 7 is the one square with no facing recorded.
    assert known[7] == Arrival(5, 7)
    assert str(known[7]) == "5,7"
    assert known[7].facing is None


def test_areas_are_frozen():
    with pytest.raises(Exception):
        areas.AREAS[0].name = "somewhere else"


def test_a_label_names_both_maps_and_the_disk():
    assert areas.area(0).label == "New Phlan - GEO00, POOL3"
    assert areas.area(29).label == "Kuto's Well - GEO1D, GEO20, POOL8"
    assert areas.area(25).label == \
        "Wilderness, West Window - GEO19, SQRDATA04, POOL6"
    assert areas.area(8).label == "Phlan City Hall - no map, POOL3"


# -- names, keyed by title ---------------------------------------------------


def test_geo15_is_sokol_keep_only_in_pool_of_radiance():
    """The bug `docs/120-curse-testing.md` recorded: `GEO15` is in both games,
    and a Curse party standing in it was labelled "Sokol Keep"."""
    assert areas.area_name("GEO15", POOL_OF_RADIANCE) == "Sokol Keep"
    assert areas.area_name("GEO15", CURSE_OF_THE_AZURE_BONDS) == "area 21"
    assert areas.area_name("GEO15", "Secret of the Silver Blades") == "area 21"
    assert areas.area_name("GEO15", None) == "area 21"


def test_an_unknown_map_degrades_to_its_own_number():
    """Sparse ids are the rule after Pool of Radiance -- Curse reaches `$45`
    and Silver Blades `$62`. A name we do not have must not become a name we
    do."""
    assert areas.area_name("GEO45", POOL_OF_RADIANCE) == "area 69"
    assert areas.area_name("GEO62", POOL_OF_RADIANCE) == "area 98"
    assert areas.area_name("SQRDATA04", POOL_OF_RADIANCE) == "SQRDATA04"


def test_geo_number_reads_hex():
    assert areas.geo_number("GEO15") == 21
    assert areas.geo_number("GEO0A") == 10
    assert areas.geo_number("GEO20") == 32
    assert areas.geo_number("SQRDATA04") is None
    assert areas.geo_number("GEOZZ") is None


def test_geo_name_says_nothing_rather_than_something_wrong():
    assert areas.geo_name("GEO15", POOL_OF_RADIANCE) == "Sokol Keep"
    assert areas.geo_name("GEO15", CURSE_OF_THE_AZURE_BONDS) is None
    assert areas.geo_name("GEO15", "no such game") is None
    assert areas.geo_name("GEO15", None) is None


def test_a_two_map_area_can_name_its_second_map_separately():
    """Area 29 is Kuto's Well; `GEO20` under it is the catacombs."""
    assert areas.geo_name("GEO1D") == "Kuto's Well"
    assert areas.geo_name("GEO20") == "Kuto's Well Catacombs"
    assert areas.area(29).name_for("GEO1D") == "Kuto's Well"
    assert areas.area(29).name_for("GEO20") == "Kuto's Well Catacombs"


def test_the_name_table_is_derived_from_the_areas_and_not_a_second_copy():
    pool = areas.GEO_NAMES[POOL_OF_RADIANCE]
    assert set(pool) == {g for a in areas.AREAS for g in a.geos if a.name}
    # `GEO1E` and `GEO1F` belong to named areas, so they inherit those names;
    # only a mapless or nameless area contributes nothing.
    assert pool["GEO1E"] == "The Lizardman Keep"
    assert "GEO0C" not in pool


def test_the_tables_are_read_only_views():
    with pytest.raises(TypeError):
        areas.GEO_NAMES["a new game"] = {}
    with pytest.raises(TypeError):
        areas.GEO_NAMES[POOL_OF_RADIANCE]["GEO15"] = "somewhere else"
    with pytest.raises(TypeError):
        areas.AREAS_BY_ID[99] = None


# -- the automapper's view over it -------------------------------------------


def test_area_names_is_a_view_over_por_areas_and_is_keyed_by_title():
    assert AREA_NAMES is areas.GEO_NAMES
    assert AREA_NAMES[POOL_OF_RADIANCE]["GEO00"] == "New Phlan"
    assert AREA_NAMES[CURSE_OF_THE_AZURE_BONDS] == {}


def test_the_old_hand_written_names_all_survived_the_move():
    """The nine names `automap/state.py` used to carry, unchanged except the
    Slums, which takes the article `docs/118-debug-mode.md` gives it -- and
    which is title-cased with the rest of the table."""
    was = {
        "GEO09": "Stojanow Gate",
        "GEO12": "Podol Plaza",
        "GEO15": "Sokol Keep",
        "GEO20": "Kuto's Well Catacombs",
        "GEO02": "Cadorna Textile House",
        "GEO0F": "Mendor's Library",
        "GEO1D": "Kuto's Well",
        "GEO00": "New Phlan",
    }
    for geo, name in was.items():
        assert areas.geo_name(geo) == name
    assert areas.geo_name("GEO14") == "The Slums"


def test_the_label_names_a_pool_of_radiance_area():
    st = AutomapState(area="GEO15")
    assert st.title == POOL_OF_RADIANCE
    assert st.area_label == "Sokol Keep"


def test_the_label_refuses_to_name_a_curse_area_sokol_keep():
    st = AutomapState(area="GEO15", title=CURSE_OF_THE_AZURE_BONDS)
    assert st.area_label == "GEO15"


def test_the_label_still_falls_back_to_candidates_with_no_area():
    assert AutomapState().area_label == "identifying..."


# -- against the game's own scripts ------------------------------------------


def _script_paths() -> dict[int, pathlib.Path]:
    """`{area id: dis_POOLn__ECLxx.txt}` for whatever is present."""
    out: dict[int, pathlib.Path] = {}
    if not SCRIPTS.is_dir():
        return out
    for path in SCRIPTS.glob("dis_POOL?__ECL??.txt"):
        m = re.fullmatch(r"dis_POOL(\d)__ECL([0-9A-F]{2})\.txt", path.name)
        if m:
            out[int(m.group(2), 16)] = path
    return out


@pytest.fixture(scope="module")
def scripts() -> dict[int, pathlib.Path]:
    found = _script_paths()
    if not found:
        # `tools/eclwalk.py listing` looks like a rebuild -- it prints the
        # same "LOADFILES 5, 5, 0" text these tests parse -- but it walks
        # each script from its five entry points and stops wherever the walk
        # cannot reach, not a linear sweep. Checked directly (#211): on
        # `ECL1E` the walk reaches only 89% of the script and the missed 11%
        # is exactly the `LOADFILES` this file's own
        # `test_a_mapless_area_really_issues_no_loadfiles` checks for, and
        # neither of the two dynamic areas' `[$6Exx]`-addressed `LOADFILES`
        # is in the reached text either -- so it cannot regenerate this file
        # honestly. A full linear ECL disassembler would; `work/analysis6/ecl6.py`
        # was one, reaching 100% of every byte, and was lost with `work/`
        # (#137). Rebuilding it is not this file's call to make: Donald closed
        # that whole effort on 2026-08-31, at his own direction --
        # `docs/115-review-the-scripts.md` -- "I don't need to see the ECL
        # scripts. If I decide I want to see them, we can approach the issue
        # again at that time." These five tests stay skipping until that
        # reopens.
        pytest.skip("no ECL disassemblies under work/ecl-scripts/; the "
                     "decoder that produced them is gone and rebuilding it "
                     "was deliberately shelved -- docs/115-review-the-scripts.md")
    return found


def test_the_table_names_exactly_the_scripts_on_the_disks(scripts):
    assert set(scripts) == {a.id for a in areas.AREAS}


def test_every_disk_number_matches_the_disk_the_script_is_on(scripts):
    """`Area.disk` is what a fasttravel writes to `$6E12`; getting it wrong makes the
    loader sit at a disk prompt."""
    wrong = {a.id: (a.disk, scripts[a.id].name) for a in areas.AREAS
             if f"POOL{a.disk}__" not in scripts[a.id].name}
    assert wrong == {}


def test_a_mapless_area_really_issues_no_loadfiles(scripts):
    for a in areas.AREAS:
        text = scripts[a.id].read_text()
        assert ("LOADFILES" in text) == a.has_map, a.ecl


def test_every_map_the_table_claims_is_one_its_script_loads(scripts):
    """`LOADFILES`' first operand is the *file number*; whether that number is
    fetched as a `GEO` or a `SQRDATA` is decided at run time by `$49E6`, not by
    the opcode -- `ECL1A` loads its overland data with `LOADFILES 5, 5, 0`.
    So compare numbers, which is all the bytecode actually says. 255 and 127
    mean "leave this slot alone" and a `[$6Exx]` operand is a run-time choice;
    neither is a claim about this area."""
    static = re.compile(r"LOADFILES (\d+), \d+, \d+")
    for a in areas.AREAS:
        if a.dynamic_geo:
            continue
        loaded = {int(n) for n in static.findall(scripts[a.id].read_text())}
        loaded -= {255, 127}
        claimed = {areas.geo_number(g) for g in a.geos}
        if a.sqrdata:
            claimed.add(int(a.sqrdata[-2:]))
        # A script may set *another* area's map up before `NEWECL` -- `ECL07`
        # loads `GEO03` on its way into area 5 -- so this checks the one
        # direction that matters: nothing the table claims is absent.
        missing = claimed - loaded
        assert not missing, f"{a.ecl} never loads {sorted(missing)}"


def test_the_two_dynamic_areas_are_flagged_as_such(scripts):
    """Areas 3 and 5 issue no static `LOADFILES` for their own map: `ECL03`
    and `ECL05` pick it with `GETTABLE ..., mapDir`. Their `GEO03`/`GEO05` is
    inferred from the id, which is why they are PROBABLE."""
    dynamic = {a.id for a in areas.AREAS if a.dynamic_geo}
    assert dynamic == {3, 5}
    for id in dynamic:
        text = scripts[id].read_text()
        assert re.search(r"LOADFILES \[\$6E\w\w\]", text)
        assert f"LOADFILES {id}, " not in text


# -- the seam with goldbox/games.py ----------------------------------------------


def test_the_title_strings_match_the_per_game_descriptor():
    """`goldbox/areas.py` takes a title as a plain string on purpose, so that it
    does not have to import the descriptor. This is the one place the two have
    to agree: `areas.GEO_NAMES[game.title]` is how a caller with a `Game` looks
    a name up. Skipped while `goldbox/games.py` does not yet exist."""
    games = pytest.importorskip("goldbox.games")
    for attr, title in (("POOL_OF_RADIANCE", POOL_OF_RADIANCE),
                        ("CURSE_OF_THE_AZURE_BONDS", CURSE_OF_THE_AZURE_BONDS)):
        game = getattr(games, attr, None)
        if game is None or not hasattr(game, "title"):
            pytest.skip(f"goldbox.games has no {attr}.title yet")
        assert game.title == title
        assert game.title in areas.GEO_NAMES


def test_every_area_name_is_a_title_and_starts_with_a_capital():
    """Donald read "the Slums" off the dropdown and it was the odd one out.

    The table used to write proper names in capitals and descriptions in lower
    case, so "New Phlan" sat next to "the kobold caves". A dropdown is a list
    of titles; every one of them starts with a capital.
    """
    for a in areas.AREAS:
        if a.name is None:
            continue
        assert a.name[0].isupper(), a.name
    for name in areas.GEO_NAMES[POOL_OF_RADIANCE].values():
        assert name[0].isupper(), name
    assert areas.area(20).name == "The Slums"


def test_area_eleven_is_the_training_hall_not_the_arena():
    """Three ways: `ECL0B` prints THE ROOM IS FILLED WITH DUELING PAIRS. and
    WE TRAIN ONLY <class> HERE., the DOS guide names script 11 *Civilized Area
    (Training Hall)*, and a forum area list names `ECL3` record 11 *Training
    Hall*. It has no map of its own -- the schools are New Phlan's own
    squares, so `ECL0B` reuses `GEO00`."""
    a = areas.area(11)
    assert a.name == "The Training Hall"
    assert "arena" not in (a.name or "").lower()
    assert a.geos == ()
    assert a.disk == 3


# -- Secret of the Silver Blades ---------------------------------------------
#
# `#20 (Build an area table for Silver Blades)`. Every claim in
# `areas.AREAS_SILVER_BLADES` is re-derived here from the player's own six
# sides, so a row that drifts from what the scripts say fails rather than
# merely looking plausible. The disks are found through `tools/gamedisks.py`;
# there are none on a CI runner, so all of these skip there.


@pytest.fixture(scope="module")
def ssb_table():
    """The Silver Blades table read again off the disks, or skip."""
    areatable = pytest.importorskip("tools.areatable")
    gamedisks = pytest.importorskip("tools.gamedisks")
    where = gamedisks.find("secret-of-the-silver-blades")
    if where is None or not where.is_dir():
        pytest.skip("needs the Silver Blades disks; set $SSB_DISKS")
    game = next(g for g in games_module().GAMES
                if g.key == "secret-of-the-silver-blades")
    machine = areatable.Machine(str(where), game)
    base, scripts = areatable.load_scripts(str(where), game, machine)
    return base, scripts, areatable.catalogue(str(where), game)


def games_module():
    from goldbox import games
    return games


def test_the_silver_blades_table_has_a_row_per_script_on_the_disks(ssb_table):
    """Twenty-two area scripts. `ECL64` and `ECL65` are on every one of the six
    sides and are excluded by decoding rather than by name: their first four
    bytes are not the `GOTO` an area script opens with."""
    _, scripts, catalogue = ssb_table
    on_disk = {int(n[3:], 16) for n in scripts}
    assert on_disk == {a.id for a in areas.AREAS_SILVER_BLADES}
    assert len(on_disk) == 22
    assert "ECL64" in catalogue and "ECL65" in catalogue
    assert "ECL64" not in scripts and "ECL65" not in scripts


def test_every_silver_blades_disk_number_is_the_side_the_script_sits_on(
        ssb_table):
    """`Area.disk` is what a fast travel writes to `$7F12`; getting it wrong
    leaves the loader sitting at an `INSERT SIDE #` prompt."""
    _, scripts, _ = ssb_table
    wrong = {a.id: (a.disk, scripts[a.ecl].side)
             for a in areas.AREAS_SILVER_BLADES
             if scripts[a.ecl].side != a.disk}
    assert wrong == {}


def test_the_scripts_own_disk_writes_agree_with_the_side(ssb_table):
    """The other half of the disk column, and it is independent of the
    directory: every static `SAVE <n>, [$7F12]` certain on every path into a
    `NEWECL` names the side the target script is really on. 29 of 29, none
    disagreeing -- if one ever does, the table is reading the wrong byte."""
    _, scripts, _ = ssb_table
    checked = disagreed = 0
    for script in scripts.values():
        for exit_ in script.exits(0x7F12):
            target = scripts.get(f"ECL{exit_.target:02X}")
            if exit_.disk is None or target is None:
                continue
            checked += 1
            if target.side != exit_.disk:
                disagreed += 1
    assert checked >= 29 and disagreed == 0


def test_every_silver_blades_map_is_one_its_script_loads(ssb_table):
    """`LOADFILES`' first operand is the file number, so `LOADFILES 49` is
    `GEO31`. `$FF` and `$7F` mean "leave this slot alone" and are not maps."""
    _, scripts, _ = ssb_table
    for a in areas.AREAS_SILVER_BLADES:
        loaded = [f"GEO{g:02X}" for g in scripts[a.ecl].geos()]
        assert list(a.geos) == loaded, a.ecl


def test_two_silver_blades_areas_load_no_map_of_their_own(ssb_table):
    """`ECL31` and `ECL32` issue no `LOADFILES` at all, and `ECL11` issues
    none either. The first two still put a map on the screen -- `ECL30`, the
    menu that sends the party to them, loads `GEO30` on the way -- so they are
    `dynamic_geo` rather than mapless, and a caller must not pick a square off
    `geos[0]` for them because there is no `geos[0]`."""
    _, scripts, _ = ssb_table
    mapless = {a.id for a in areas.AREAS_SILVER_BLADES if not a.geos}
    assert mapless == {0x11, 0x31, 0x32}
    assert not any(scripts[f"ECL{i:02X}"].geos() for i in mapless)
    assert {a.id for a in areas.AREAS_SILVER_BLADES if a.dynamic_geo} \
        == {0x31, 0x32}


def test_five_silver_blades_areas_do_not_load_the_map_of_their_own_id(
        ssb_table):
    """Pool of Radiance's rule -- every script's `LOADFILES` first operand is
    its own id -- is false in Silver Blades, and a table built on it would put
    the wrong map against five of the twenty-two rows."""
    odd = {a.id: a.geos[0] for a in areas.AREAS_SILVER_BLADES
           if a.geos and a.geos[0] != f"GEO{a.id:02X}"}
    assert odd == {0x04: "GEO10", 0x30: "GEO31", 0x33: "GEO31",
                   0x34: "GEO32", 0x63: "GEO62"}


def test_silver_blades_arrival_squares_come_from_the_scripts(ssb_table):
    """Twelve of the twenty-two, and every one of them is the area's own
    entry 4 rather than a departing script's write -- the opposite of Pool of
    Radiance, where most were harvested from the departing side."""
    _, scripts, _ = ssb_table
    known = {a.id: a.arrival for a in areas.AREAS_SILVER_BLADES if a.arrival}
    assert len(known) == 12
    for area_id, arrival in known.items():
        x, y, facing = scripts[f"ECL{area_id:02X}"].arrival()
        assert (x, y, facing) == (arrival.x, arrival.y, arrival.facing), \
            f"ECL{area_id:02X}"
    assert known[0x22] == Arrival(14, 14, 0)
    assert str(known[0x63]) == "0,0 S"


def test_area_forty_has_two_candidate_squares_so_it_gets_none(ssb_table):
    """`ECL44` writes 7,15 N before its `NEWECL 64`; `ECL40`'s own entry 4
    writes 12,0 S. Two routes in, two squares, and nothing says which a fast
    travel should imitate."""
    _, scripts, _ = ssb_table
    assert areas.area_in(0x40, areas.SECRET_OF_THE_SILVER_BLADES).arrival \
        is None
    assert scripts["ECL40"].arrival() == (12, 0, 2)
    placed = [e.square for e in scripts["ECL44"].exits(0x7F12)
              if e.target == 0x40 and e.places]
    assert placed == [(7, 15, 0)]


#: The twenty-one Silver Blades areas a party has been **fast-travelled into**
#: on a running machine, with the landing measured -- `#20 (Build an area
#: table for Silver Blades)`, `work/issue20/land1`-`land9`. `$11` is not in
#: the set because nothing warps there: it is where a loaded party starts, and
#: was read where it stood. A row outside both must not claim CONFIRMED.
SILVER_BLADES_WARPED_INTO = {
    0x04, 0x10, 0x20, 0x21, 0x22, 0x30, 0x31, 0x32, 0x33, 0x34, 0x40,
    0x41, 0x42, 0x44, 0x50, 0x51, 0x52, 0x60, 0x61, 0x62, 0x63}


def test_every_silver_blades_row_has_had_a_party_put_in_it():
    """A row is CONFIRMED when a party has been put in that area on a running
    machine and the map at `$0400` matched this table's, byte for byte. All
    twenty-two have: twenty-one by a trip through `automap.actions.FastTravel`
    and `$11`, the prologue, by starting there."""
    table = areas.AREAS_SILVER_BLADES
    assert {a.confidence for a in table} == {Confidence.CONFIRMED}
    assert SILVER_BLADES_WARPED_INTO | {0x11} == {a.id for a in table}
    assert 0x11 not in SILVER_BLADES_WARPED_INTO


def test_no_silver_blades_area_has_a_name_yet():
    """Five arriving scripts name their own place on the first screen a
    driven party sees, but naming is the other half of this ticket and takes
    a systematic pass rather than four rows out of twenty-two: a dropdown
    with five names and seventeen `ECLxx` reads worse than one with none."""
    table = areas.AREAS_SILVER_BLADES
    assert all(a.name is None for a in table)
    assert areas.GEO_NAMES[areas.SECRET_OF_THE_SILVER_BLADES] == {}


def test_the_silver_blades_arrival_column_is_not_what_confidence_grades():
    """Five of ten measured arrival squares differ from the static reading,
    because an arriving script can compute the square off `$4BF2` and a fast
    travel supplies a came-from it may have no branch for. `$60` was entered
    twice, from `$50` and from `$42`, and landed in two different places. So
    a CONFIRMED row is a claim about the id, the side and the map, and this
    pins the five rows whose square a driven arrival did *not* reproduce."""
    by_id = {a.id: a for a in areas.AREAS_SILVER_BLADES}
    reproduced = {0x30: (3, 3, 1), 0x41: (13, 9, 1), 0x44: (7, 15, 0),
                  0x50: (1, 11, 1), 0x62: (0, 15, 1)}
    for id, square in reproduced.items():
        got = by_id[id].arrival
        assert (got.x, got.y, got.facing) == square
    # Measured and different: the party landed at 3,3 S in `$10`, 0,7 W in
    # `$42`, 0,7 E and then 15,9 W in `$60` from two different came-froms,
    # 0,15 E in `$61`, 9,8 W in `$04`, and in `$63` it stayed on the
    # deliberately wrong square because `ECL63` wrote none.
    for id in (0x04, 0x10, 0x42, 0x60, 0x61, 0x63):
        assert by_id[id].arrival is not None
        assert by_id[id].confidence is Confidence.CONFIRMED


def test_the_two_silver_blades_areas_that_load_no_map_say_so():
    """`$31` and `$32` issue no `LOADFILES` and nothing else loads one for
    them, so a party fast-travelled in walks on whatever map the area it came
    from was showing -- driven in from `$33`, `$0400` stayed `GEO31` through
    both. `dynamic_geo` is what stops a caller picking a landing square off a
    map the game was never going to draw."""
    by_id = {a.id: a for a in areas.AREAS_SILVER_BLADES}
    for id in (0x31, 0x32):
        assert by_id[id].geos == ()
        assert by_id[id].dynamic_geo
        assert not by_id[id].has_map
    assert not any(a.dynamic_geo for a in areas.AREAS_SILVER_BLADES
                   if a.id not in (0x31, 0x32))


def test_a_silver_blades_label_names_its_own_disk_not_a_pool_one():
    """`POOL3` under a Silver Blades session would name a disk the player does
    not own."""
    row = areas.area_in(0x22, areas.SECRET_OF_THE_SILVER_BLADES)
    assert row.label == "ECL22 - GEO22, SILVER-2"
    assert areas.area(0).label == "New Phlan - GEO00, POOL3"


def test_fast_travel_is_offered_silver_blades_now_that_one_has_been_driven():
    """Two things had to be true and both are: `#15 (Fast Travel for more than
    one Gold Box title)` moved the addresses off Pool of Radiance's, and a
    party has been fast-travelled into fourteen of these areas on a running
    machine with the map checked byte for byte at every landing. Curse still
    answers nothing, for the older reason that nobody has built its table."""
    assert len(areas.areas_for_title(areas.SECRET_OF_THE_SILVER_BLADES)) == 22
    assert areas.areas_for_title(areas.SECRET_OF_THE_SILVER_BLADES) \
        == areas.AREAS_SILVER_BLADES
    assert len(areas.areas_for(areas.SECRET_OF_THE_SILVER_BLADES)) == 22
    assert areas.areas_for_title(POOL_OF_RADIANCE) == areas.AREAS
    assert areas.areas_for(POOL_OF_RADIANCE) == areas.AREAS
    assert areas.areas_for_title(CURSE_OF_THE_AZURE_BONDS) == ()
    assert areas.areas_for(CURSE_OF_THE_AZURE_BONDS) == ()
    assert areas.areas_for_title(None) == ()
    assert areas.areas_for(None) == ()


def test_the_silver_blades_ids_are_sparse_and_must_not_be_enumerated():
    """Blocked by side, with `ECL04` the one id whose high nibble is not its
    side. Anything walking `range(...)` over these invents twenty-six areas
    that do not exist."""
    ids = [a.id for a in areas.AREAS_SILVER_BLADES]
    assert ids == sorted(ids)
    assert ids[0] == 0x04 and ids[-1] == 0x63
    assert len(set(range(ids[0], ids[-1] + 1)) - set(ids)) == 74
    wrong_nibble = [a.id for a in areas.AREAS_SILVER_BLADES
                    if a.id >> 4 != a.disk]
    assert wrong_nibble == [0x04]


# -- the same reading, run against Pool of Radiance as a control -------------
#
# The five tests above that check `AREAS` against the scripts have skipped
# since `work/ecl-scripts/` was lost with the rest of `work/` (#137). These
# three ask the same questions of the disks directly, through the reader that
# built the Silver Blades table -- so the Silver Blades rows are not the only
# thing that reader has ever been believed about.


@pytest.fixture(scope="module")
def pool_table():
    """Pool of Radiance's scripts read by `tools/areatable.py`, or skip."""
    areatable = pytest.importorskip("tools.areatable")
    gamedisks = pytest.importorskip("tools.gamedisks")
    where = gamedisks.find("pool-of-radiance")
    if where is None or not where.is_dir():
        pytest.skip("needs the Pool of Radiance disks; set $POR_DISKS")
    game = next(g for g in games_module().GAMES if g.key == "pool-of-radiance")
    machine = areatable.Machine(str(where), game)
    _, scripts = areatable.load_scripts(str(where), game, machine)
    return scripts


def test_the_pool_table_names_exactly_the_scripts_on_the_disks(pool_table):
    assert {int(n[3:], 16) for n in pool_table} == {a.id for a in areas.AREAS}


def test_every_pool_disk_number_is_the_side_the_script_sits_on(pool_table):
    wrong = {a.id: (a.disk, pool_table[a.ecl].side) for a in areas.AREAS
             if pool_table[a.ecl].side != a.disk}
    assert wrong == {}


def test_every_pool_map_the_table_claims_is_one_its_script_loads(pool_table):
    """`LOADFILES`' first operand is a *file number*; whether it is fetched as
    a `GEO` or as a `SQRDATA` is decided at run time by `$49E6` and not by the
    opcode, so `ECL19` loading 4 covers both `GEO04` and `SQRDATA04` and the
    comparison is between numbers. Areas 3 and 5 are excluded: they are
    `dynamic_geo`, their scripts issue no static `LOADFILES` at all, and their
    `geos` is an inference from the id that is known to be wrong for both.

    **Two exceptions in the remaining twenty-eight**, and they are different
    in kind.

    `ECL07` loads file 3 as well as its own 7, on its way into area 3, and the
    table gives `GEO03` to area 3 rather than to area 7. That is deliberate,
    and Silver Blades' `ECL30` does the same thing for areas `$31` and `$32`,
    so a script loading the *next* area's map is a shape both titles have.

    `ECL1E` is a defect in this table rather than a modelling choice: it
    carries `LOADFILES 18, 2, 255` at `$9A54` -- `GEO12`, Podol Plaza, which
    is what the attract-mode demo walks a party around -- so the docstring's
    "four areas have no map" is three, and area 30's `geos` should hold
    `GEO12`. Nothing a player can reach depends on it: area 30 is
    `fasttravelable=False` and is offered nowhere. Pinned here rather than
    corrected, because the correction moves `areas_for_geo("GEO12")`,
    `has_map` and four other test modules --
    `#20 (Build an area table for Silver Blades)` found it and is not the
    ticket that fixes it."""
    exceptions = {}
    for a in areas.AREAS:
        if a.dynamic_geo:
            continue
        claimed = {areas.geo_number(g) for g in a.geos}
        if a.sqrdata:
            claimed.add(int(a.sqrdata[-2:], 16))
        loaded = set(pool_table[a.ecl].geos())
        if claimed != loaded:
            exceptions[a.ecl] = (sorted(claimed), sorted(loaded))
    assert exceptions == {"ECL07": ([7], [3, 7]),
                          "ECL1E": ([], [18])}
