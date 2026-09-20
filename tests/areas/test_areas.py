from __future__ import annotations

"""The area table, and the title key that stops it lying about Curse.

Rows that need the game's own scripts read them off the disks through the
`ssb_table` and `pool_table` fixtures, and skip when no disk is attached.
"""


import pathlib
import re

import pytest

from automap.state import AREA_NAMES, AutomapState
from goldbox import areas
from goldbox.areas import (
    CURSE_OF_THE_AZURE_BONDS,
    POOL_OF_RADIANCE,
    SECRET_OF_THE_SILVER_BLADES,
    Arrival,
    Confidence,
)

# -- the shape of the table --------------------------------------------------


def test_thirty_areas_with_one_hole_at_twelve():
    """Thirty scripts and twenty-nine maps. `ECL0C` does not exist."""
    ids = [a.id for a in areas.AREAS]
    assert len(ids) == 30
    assert ids == sorted(ids)
    assert areas.MISSING_ID not in ids
    assert set(ids) == set(range(31)) - {areas.MISSING_ID}
    assert areas.area(areas.MISSING_ID) is None


NUMBER_WORDS = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four",
                5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}


def test_the_docstrings_mapless_count_matches_the_table():
    """`goldbox/areas.py`'s module docstring and `Area.geos`' own field comment
    each say in words how many areas have no map -- "three areas have no map"
    and "the three mapless Pool of Radiance areas" -- and a number typed by
    hand goes stale the next time a row changes: `#260 (Area 30 is recorded as
    having no map, and ECL1E loads GEO12)` is exactly that, it used to say
    four. Computed from the table rather than asserted as a literal, so this
    fails the day the two next disagree."""
    mapless = sum(1 for a in areas.AREAS if not a.geos)
    word = NUMBER_WORDS[mapless]
    assert re.search(rf"\b{word} areas have no map\b", areas.__doc__)
    # The `#:` field comment is not part of the dataclass's introspectable
    # metadata, so read the module's own source to check it.
    source = pathlib.Path(areas.__file__).read_text()
    assert re.search(rf"Empty for the {word} mapless Pool of Radiance areas",
                     source)


def test_the_id_is_the_ecl_number_in_hex():
    """Area 21 is `ECL15`, which is why `area_name` can read a `GEO`'s digits."""
    assert areas.area(21).ecl == "ECL15"
    assert areas.area(10).ecl == "ECL0A"
    for a in areas.AREAS:
        assert int(a.ecl[3:], 16) == a.id


def test_twenty_nine_maps_across_thirty_areas_and_one_shared():
    """Thirty `geos` entries, not twenty-nine: area 30's `ECL1E` loads `GEO12`,
    which is already area 18's (`#260 (Area 30 is recorded as having no map,
    and ECL1E loads GEO12)`), so it is the one map two scripts share and the
    twenty-nine distinct names stay the same."""
    names = [g for a in areas.AREAS for g in a.geos]
    assert len(names) == 30
    assert len(set(names)) == 29
    assert names.count("GEO12") == 2


@pytest.mark.parametrize("id", [8, 11, 19])
def test_three_areas_have_no_map_at_all(id):
    """`ECL08`, `ECL0B` and `ECL13` issue no `LOADFILES`. `ECL1E` used to be
    counted here too, until `#260 (Area 30 is recorded as having no map, and
    ECL1E loads GEO12)` found it loads `GEO12`."""
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


def test_geo12_is_two_areas_since_260():
    """`ECL1E` loads Podol Plaza's own map, `GEO12`, which is already area
    18's (`#260 (Area 30 is recorded as having no map, and ECL1E loads
    GEO12)`)."""
    assert [a.id for a in areas.areas_for_geo("GEO12")] == [18, 30]


def test_the_maps_a_title_loads_are_a_set_and_not_a_range():
    """`geos_in` is what a `GEO` number read out of a saved game is checked
    against, and it has to be the union of the rows rather than 0 to the
    largest: `GEO0C` is inside any range anybody would write and is in no row
    (#257).

    Twenty-nine maps for Pool of Radiance, which is the count the module's own
    docstring claims. An unknown title answers nothing at all -- the answer
    that refuses every save rather than the one that validates against
    somebody else's game.
    """
    pool = areas.geos_in(areas.POOL_OF_RADIANCE)
    assert pool == {g for a in areas.AREAS for g in a.geos}
    assert len(pool) == 29
    assert "GEO00" in pool and "GEO0C" not in pool
    assert 12 not in {areas.geo_number(g) for g in pool}
    silver = areas.geos_in(areas.SECRET_OF_THE_SILVER_BLADES)
    assert silver and silver != pool
    curse = areas.geos_in(areas.CURSE_OF_THE_AZURE_BONDS)
    assert len(curse) == 16          # #192 step 0b's sixteen decoded maps
    assert curse != pool and curse != silver
    assert areas.geos_in(None) == frozenset()


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
    """No name and no arrival square, though it does load a map -- `GEO12`,
    Podol Plaza's own (`#260 (Area 30 is recorded as having no map, and ECL1E
    loads GEO12)`)."""
    a = areas.area(30)
    assert a.name is None
    assert a.confidence is Confidence.UNKNOWN
    assert a.geos == ("GEO12",)
    assert a.label == "ECL1E - GEO12, POOL1"


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
    # found in `ECL15`'s own bytecode -- `reports/p20-arrivals.md` in scratch, deleted.
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
    and a Curse party standing in it was labelled "Sokol Keep".

    `#15 (Fast Travel for more than one Gold Box title)` landed Curse's own
    name for its `GEO15` -- "shared blocks: Voonlar, Phlan dungeons" -- so the
    title-keying is now proven by two real names disagreeing rather than by
    one side being blank.
    """
    assert areas.area_name("GEO15", POOL_OF_RADIANCE) == "Sokol Keep"
    assert (areas.area_name("GEO15", CURSE_OF_THE_AZURE_BONDS)
            == "shared blocks: Voonlar, Phlan dungeons")
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
    assert (areas.geo_name("GEO43", CURSE_OF_THE_AZURE_BONDS)
            == "Myth Drannor, Ruined Temple")
    # `GEO01` is two different approved names sharing one file, so
    # `_names_for_curse` leaves it out rather than picking a winner -- see
    # test_geo_names_shared_by_two_curse_areas_are_left_out_of_both.
    assert areas.geo_name("GEO01", CURSE_OF_THE_AZURE_BONDS) is None
    assert areas.geo_name("GEO15", "no such game") is None
    assert areas.geo_name("GEO15", None) is None


def test_geo_names_shared_by_two_curse_areas_are_left_out_of_both():
    """`GEO01` (`$01`/`$02`) and `GEO32` (`$31`/`$32`) are each two different
    approved names on one map file, and `_names_for_curse` leaves both out
    rather than picking a winner (`#15 (Fast Travel for more than one Gold
    Box title)`). Both areas' own `name` stay correct regardless -- this is
    only about the derived, geo-keyed table the automapper's live label
    reads.
    """
    curse = areas.GEO_NAMES[CURSE_OF_THE_AZURE_BONDS]
    assert "GEO01" not in curse
    assert "GEO32" not in curse
    assert areas.area_in(0x01, CURSE_OF_THE_AZURE_BONDS).name \
        == "Tilverton streets"
    assert areas.area_in(0x02, CURSE_OF_THE_AZURE_BONDS).name \
        == "Thieves' Guild under Tilverton"
    assert areas.area_in(0x31, CURSE_OF_THE_AZURE_BONDS).name \
        == "Haptooth streets"
    assert areas.area_in(0x32, CURSE_OF_THE_AZURE_BONDS).name \
        == "Dracolich cave"


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
    assert (AREA_NAMES[CURSE_OF_THE_AZURE_BONDS]["GEO20"]
            == "Zhentil Keep streets")
    assert AREA_NAMES[CURSE_OF_THE_AZURE_BONDS] != AREA_NAMES[POOL_OF_RADIANCE]


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


def test_the_label_names_a_curse_area_with_its_own_name_not_pools():
    """`GEO15` used to have no Curse name at all, so this test proved the
    label refused to borrow Pool of Radiance's "Sokol Keep". `#15 (Fast
    Travel for more than one Gold Box title)` landed Curse's own name for it,
    so the label now shows that instead of either the borrowed name or the
    file stem.
    """
    st = AutomapState(area="GEO15", title=CURSE_OF_THE_AZURE_BONDS)
    assert st.area_label == "shared blocks: Voonlar, Phlan dungeons"
    assert st.area_label != "Sokol Keep"


def test_the_label_still_falls_back_to_the_stem_for_a_shared_curse_map():
    """`GEO01` is `$01`'s streets and `$02`'s Thieves' Guild -- two different
    approved names on one map file -- so `_names_for_curse` leaves it out
    rather than picking a winner, and the label is still the file stem."""
    st = AutomapState(area="GEO01", title=CURSE_OF_THE_AZURE_BONDS)
    assert st.area_label == "GEO01"


def test_the_label_still_falls_back_to_candidates_with_no_area():
    assert AutomapState().area_label == "identifying..."


# -- the seam with goldbox/c64_port.py ---------------------------------------


def test_the_title_strings_match_the_per_game_descriptor():
    """`goldbox/areas.py` takes a title as a plain string on purpose, so that it
    does not have to import the descriptor. This is the one place the two have
    to agree: `areas.GEO_NAMES[game.title]` is how a caller with a `Game` looks
    a name up."""
    from goldbox import c64_port
    for attr, title in (("POOL_OF_RADIANCE", POOL_OF_RADIANCE),
                        ("CURSE_OF_THE_AZURE_BONDS", CURSE_OF_THE_AZURE_BONDS)):
        game = getattr(c64_port, attr, None)
        if game is None or not hasattr(game, "title"):
            pytest.skip(f"goldbox.c64_port has no {attr}.title yet")
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
# merely looking plausible. The disks are found through `automap/gamedisks.py`;
# there are none on a CI runner, so all of these skip there.


@pytest.fixture(scope="module")
def ssb_table():
    """The Silver Blades table read again off the disks, or skip."""
    areatable = pytest.importorskip("tools.areas.areatable")
    gamedisks = pytest.importorskip("automap.gamedisks")
    where = gamedisks.find("secret-of-the-silver-blades")
    if where is None or not where.is_dir():
        pytest.skip("needs the Silver Blades disks; set $SSB_DISKS")
    game = next(g for g in games_module().GAMES
                if g.key == "secret-of-the-silver-blades")
    machine = areatable.Machine(str(where), game)
    base, scripts = areatable.load_scripts(str(where), game, machine)
    return base, scripts, areatable.catalogue(str(where), game)


def games_module():
    from goldbox import c64_port
    return c64_port


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
#: table for Silver Blades)`, `cited/20/land1`-`land9`. `$11` is not in
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


def test_a_curse_label_names_its_lettered_disk_not_a_number():
    """`CURSE_2` under a Curse of the Azure Bonds session would name a disk
    the player does not own -- the six disks are lettered `CURSE_A.D64`
    through `CURSE_F.D64`, and `disk` holds the number the loader prompts
    for and a fast travel writes, not the letter on the label
    (`#427 (Fast Travel's dropdown names Curse's disks CURSE_2 rather than
    CURSE_B, which is not a disk the player has)`).

    `$01`, `$40`, `$22`, `$23` and `$43` all carried this test in turn until
    `#15 (Fast Travel for more than one Gold Box title)` named them, one
    round of the ticket at a time, so it now reads `$1E` -- the one row with
    no approved name at all -- alongside a named row on a different disk, to
    keep this test about the disk letter rather than about which rows are
    still nameless.
    """
    row = areas.area_in(0x1E, areas.CURSE_OF_THE_AZURE_BONDS)
    assert row.disk == 1
    assert row.label == "ECL1E - no map, CURSE_A"
    row = areas.area_in(0x43, areas.CURSE_OF_THE_AZURE_BONDS)
    assert row.disk == 6
    assert row.label == "Myth Drannor, Ruined Temple - GEO43, CURSE_F"
    # The two titles this could regress stay right.
    assert areas.area(0).label == "New Phlan - GEO00, POOL3"
    silver = areas.area_in(0x22, areas.SECRET_OF_THE_SILVER_BLADES)
    assert silver.label == "ECL22 - GEO22, SILVER-2"


def test_fast_travel_is_offered_silver_blades_now_that_one_has_been_driven():
    """Two things had to be true and both are: `#15 (Fast Travel for more than
    one Gold Box title)` moved the addresses off Pool of Radiance's, and a
    party has been fast-travelled into fourteen of these areas on a running
    machine with the map checked byte for byte at every landing."""
    assert len(areas.areas_for_title(areas.SECRET_OF_THE_SILVER_BLADES)) == 22
    assert areas.areas_for_title(areas.SECRET_OF_THE_SILVER_BLADES) \
        == areas.AREAS_SILVER_BLADES
    assert len(areas.areas_for(areas.SECRET_OF_THE_SILVER_BLADES)) == 22
    assert areas.areas_for_title(POOL_OF_RADIANCE) == areas.AREAS
    assert areas.areas_for(POOL_OF_RADIANCE) == areas.AREAS
    assert areas.areas_for_title(None) == ()
    assert areas.areas_for(None) == ()


def test_curse_is_offered_too_now_that_its_table_exists():
    """`#192 (Convert a Curse of the Azure Bonds DOS save into a C64 one,
    which the importer refuses today)` step 0b built `AREAS_CURSE`, and
    `automap.fasttravel`'s addresses for Curse were CONFIRMED by four driven
    warps (`#19`) before this table existed -- so both of
    `automap.actions.area_rows`'s gates are open, the same as Silver Blades'.

    `confidence` grades the name (see `Area.confidence`'s own docstring), so
    it moved off UNKNOWN for 24 rows: the 21 `#15 (Fast Travel for more than
    one Gold Box title)` landed a name for straight off the validation pass,
    plus `$22` and `$43`, whose screens disagreed and were confirmed by a
    later bytecode read, plus `$23`, whose script genuinely holds two arrival
    scenes and got a name covering both. `$1E`, which has no approved name at
    all, is the only row left UNKNOWN.
    """
    assert len(areas.areas_for_title(CURSE_OF_THE_AZURE_BONDS)) == 25
    assert areas.areas_for_title(CURSE_OF_THE_AZURE_BONDS) == areas.AREAS_CURSE
    assert areas.areas_for(CURSE_OF_THE_AZURE_BONDS) == areas.AREAS_CURSE
    unknown = {a.id for a in areas.AREAS_CURSE
               if a.confidence is areas.Confidence.UNKNOWN}
    assert unknown == {0x1E}


#: The fourteen derived arrival squares landed for `#15 (Fast Travel for more
#: than one Gold Box title)`, exactly as `tools/areas/areatable.py
#: curse-of-the-azure-bonds --python` printed them the night they were taken.
#: Pinned here as literals, separately from `goldbox.areas.AREAS_CURSE`, so a
#: change to either one is caught by a comparison rather than by both sides
#: agreeing with themselves.
_CURSE_ARRIVALS = {
    0x01: (7, 13, 1),
    0x02: (8, 0, 1),
    0x10: (0, 8, 3),
    0x11: (0, 0, 1),
    0x12: (15, 14, 2),
    0x15: (8, 12, 1),
    0x20: (14, 1, 0),
    0x21: (3, 8, 2),
    0x22: (12, 7, 3),
    0x31: (3, 0, 2),
    0x32: (6, 15, None),
    0x33: (7, 15, 3),
    0x45: (6, 10, 1),
    0x51: (0, 8, 3),
}


def test_fourteen_curse_arrivals_are_landed_and_probable():
    """`#15 (Fast Travel for more than one Gold Box title)`: the derivation
    was done on `#192`; this is landing it. Fourteen of the twenty-five rows
    now carry the square their own script names, and the other eleven stay
    `None` rather than getting a guess.

    Pinned against the tool's own printed rows rather than re-derived here,
    because re-deriving off the disks is `tests/areas/test_areatable.py`'s job and
    this file's is to prove what got typed into `goldbox/areas.py` is what
    the tool said. `$32` is the one row with no facing -- its script saves
    `x` and `y` and never writes a direction, the same shape as Pool of
    Radiance's area 7.
    """
    table = {a.id: a for a in areas.AREAS_CURSE}
    landed = {id: (a.arrival.x, a.arrival.y, a.arrival.facing)
              for id, a in table.items() if a.arrival is not None}
    assert landed == _CURSE_ARRIVALS
    assert len(landed) == 14

    absent = {id for id, a in table.items() if a.arrival is None}
    assert absent == set(table) - set(_CURSE_ARRIVALS)
    assert len(absent) == 11


def test_a_curse_arrival_square_is_still_not_what_confidence_grades():
    """This used to assert `confidence` UNKNOWN for every arrival-carrying
    row, back when UNKNOWN was every row's only state. `confidence` grades
    the **name** (`Area.confidence`'s own docstring: "What this grades is the
    `name`, and only the name" -- the same convention `AREAS` uses), and
    landing the 23 approved names
    (`test_the_approved_curse_names_are_landed_and_graded` below) moved all
    fourteen arrival rows off UNKNOWN, `$22` last of them -- its screen
    disagreed with its approved name and held it back until a bytecode read
    confirmed the name separately (`#15 (Fast Travel for more than one Gold
    Box title)`). That is the name's grade, not the arrival's: the
    derived-arrival calibration is `tests/areas/test_areatable.py::
    test_a_derived_arrival_square_is_right_ten_times_in_eleven` (ten of
    eleven, never eleven of eleven) and this landing did not touch it.
    """
    table = {a.id: a for a in areas.AREAS_CURSE}
    assert all(table[id].confidence is not areas.Confidence.UNKNOWN
               for id in _CURSE_ARRIVALS)


#: The 24 names Donald approved on `#15 (Fast Travel for more than one Gold
#: Box title)`, 2026-09-15, off the forum table he named
#: (`docs/126-forum-findings.md`, topic 1048). 21 were graded CONFIRMED or
#: PROBABLE the next day by an emulator-runner's validation pass against the
#: first screen the game drew on arrival; `$22`, `$23` and `$43` disagreed
#: with that screen and were held back. A bytecode read the day after
#: confirmed `$22` and `$43` were capture artefacts rather than wrong names,
#: landed CONFIRMED; `$23`'s script genuinely holds two arrival scenes and
#: Donald renamed the row to cover both, landed PROBABLE. `$1E` has no
#: approved name at all.
_CURSE_NAMES = {
    0x01: ("Tilverton streets", areas.Confidence.PROBABLE),
    0x02: ("Thieves' Guild under Tilverton", areas.Confidence.CONFIRMED),
    0x03: ("Tilverton sewers", areas.Confidence.CONFIRMED),
    0x04: ("Fire Knife hideout", areas.Confidence.PROBABLE),
    0x10: ("Yulash streets", areas.Confidence.PROBABLE),
    0x11: ("Pit of Moander", areas.Confidence.CONFIRMED),
    0x12: ("Pit of Moander, second level", areas.Confidence.PROBABLE),
    0x15: ("shared blocks: Voonlar, Phlan dungeons", areas.Confidence.PROBABLE),
    0x20: ("Zhentil Keep streets", areas.Confidence.CONFIRMED),
    0x21: ("Temple of Bane", areas.Confidence.CONFIRMED),
    0x22: ("Cave of the Beholder", areas.Confidence.CONFIRMED),
    0x23: ("Zhentil Keep courtroom/tavern", areas.Confidence.PROBABLE),
    0x25: ("Dagger Falls Dungeon (Oxam's Tower)", areas.Confidence.PROBABLE),
    0x30: ("outside Haptooth", areas.Confidence.CONFIRMED),
    0x31: ("Haptooth streets", areas.Confidence.CONFIRMED),
    0x32: ("Dracolich cave", areas.Confidence.CONFIRMED),
    0x33: ("Dracandros' Tower", areas.Confidence.CONFIRMED),
    0x35: ("shared blocks: Ashabenford, Essembra, Shadowdale dungeons",
           areas.Confidence.PROBABLE),
    0x40: ("Myth Drannor, Burial Glen", areas.Confidence.PROBABLE),
    0x42: ("Ruins of Myth Drannor", areas.Confidence.PROBABLE),
    0x43: ("Myth Drannor, Ruined Temple", areas.Confidence.CONFIRMED),
    0x45: ("shared blocks: Hillsfar, Teshwave dungeons", areas.Confidence.PROBABLE),
    0x50: ("world map", areas.Confidence.CONFIRMED),
    0x51: ("world map", areas.Confidence.CONFIRMED),
}


def test_the_approved_curse_names_are_landed_and_graded():
    """`#15 (Fast Travel for more than one Gold Box title)`: Donald's ruling
    approved names for 24 of the 25 rows (`$1E` has none at all). An
    emulator-runner's validation pass graded 21 of them against the first
    screen the game drew on arrival, landed here as CONFIRMED or PROBABLE.
    `$22`, `$23` and `$43` disagreed with that screen. A follow-up bytecode
    read of the scripts (`ECL22`, `ECL43`, and `ECL42`'s own naming of `$43`)
    found `$22` and `$43`'s disagreements were capture artefacts -- `$22`'s
    screen was page 1 of a three-page arrival that names the beholder on
    page 2, and `$43`'s screen was one door's own narration rather than the
    place's -- so both land here CONFIRMED. `$23`'s script genuinely holds
    two arrival scenes, chosen by a quest flag: a courtroom/arena pair the
    original approved name covered, and a tavern it did not -- the scene a
    fast-travelling party actually lands in. Donald renamed the row
    "Zhentil Keep courtroom/tavern" to cover both, landed here PROBABLE:
    exactly right for two of the script's scenes, only adjacent for the
    third.

    Pinned against the ruling and the grading pass as literals, separately
    from `goldbox/areas.py`, so a change to either side is caught rather than
    both agreeing with themselves.
    """
    table = {a.id: a for a in areas.AREAS_CURSE}
    landed = {id: (a.name, a.confidence)
              for id, a in table.items() if a.name is not None}
    assert landed == _CURSE_NAMES
    assert len(landed) == 24

    unnamed = {id for id, a in table.items() if a.name is None}
    assert unnamed == {0x1E}


def test_silver_blades_and_pool_of_radiance_tables_are_untouched():
    """`#15`'s Curse work must not move either sibling table."""
    assert len(areas.AREAS_SILVER_BLADES) == 22
    assert len(areas.AREAS) == 30
    silver_arrivals = sum(1 for a in areas.AREAS_SILVER_BLADES
                           if a.arrival is not None)
    assert silver_arrivals == 12


def test_curse_has_no_area_zero_and_the_table_is_not_missing_it():
    """A Curse save whose area word is 0 is a party that has not pressed
    `BEGIN ADVENTURING` -- 0 is the initialiser's value, not a place.

    No `ECL00` is on any of the six C64 sides and no `ECL` or `GEO` container
    holds a block 0, so a row here would be a place the game does not have.
    Adding one would move `goldbox.dos_codec`'s refusal from `area_in` to
    `_resident_geo` rather than remove it, and a C64 save naming area 0 sends
    the loader after `GEO00`, which is on none of the sides
    (`#301 (A DOS Curse save standing in area 0 is refused by the import,
    because no row of the area table names area 0)`,
    `docs/185-a-party-that-has-not-set-out.md`).

    This guards against the row rather than a defect: it is here so that the
    next reader of the refusal message reads the reason before writing one.
    """
    assert areas.area_in(0, CURSE_OF_THE_AZURE_BONDS) is None
    assert min(a.id for a in areas.AREAS_CURSE) == 0x01
    assert "GEO00" not in areas.geos_in(CURSE_OF_THE_AZURE_BONDS)
    # Pool of Radiance is the contrast, and the reason this is not a rule
    # about Gold Box area tables in general: its area 0 is New Phlan.
    assert areas.area_in(0, POOL_OF_RADIANCE) is not None


def test_a_party_that_has_not_set_out_starts_where_its_own_title_says():
    """`STARTS` is per title, and the row it names is one of that title's own.

    A DOS save made from the party-formation menu holds area 0 on all three
    titles, and 0 means two different things: New Phlan in Pool of Radiance,
    and nowhere at all in Curse. So the conversion asks the title rather than
    reading the word (`#301 (A DOS Curse save standing in area 0 is refused
    by the import, because no row of the area table names area 0)`).
    """
    curse = areas.start_of(CURSE_OF_THE_AZURE_BONDS)
    assert curse.area == 0x01
    assert (curse.arrival.x, curse.arrival.y) == (7, 13)
    assert curse.arrival.facing_letter == "E"
    row = areas.start_area(CURSE_OF_THE_AZURE_BONDS)
    assert row.ecl == "ECL01" and row.geos == ("GEO01",) and row.disk == 2

    # Pool of Radiance's start really is area 0, so a conversion that read the
    # word instead of asking would be right here and wrong in Curse.
    pool = areas.start_of(POOL_OF_RADIANCE)
    assert pool.area == 0
    assert areas.start_area(POOL_OF_RADIANCE).name == "New Phlan"


def test_pool_of_radiances_start_square_is_the_one_its_area_row_already_holds():
    """Two independent readings of the same square, and the reason the Pool of
    Radiance row is graded CONFIRMED.

    `AREAS`' New Phlan arrival came from a driven fast travel; `STARTS`' came
    from the seven never-adventured containers on this machine, which all hold
    `15,1` facing west. Neither was derived from the other, so if a later
    measurement moves one it must move the other, and this fails until it
    does.
    """
    start = areas.start_of(POOL_OF_RADIANCE)
    assert start.arrival == areas.area(0).arrival


def test_silver_blades_starts_in_area_0x10_at_3_3_facing_south():
    """`STARTS` now carries Silver Blades' row (`#535 (A Secret of the Silver
    Blades save made before the party set out is refused by Convert, because
    nobody has measured where that title begins)`), measured the same way
    Curse's was: one boot, a character created, `SAVE CURRENT GAME` at the
    party menu, then `BEGIN ADVENTURING` with the party standing still. The
    second save read area `$10`, square `3,3` facing south, clock 00:00.

    Its two never-adventured containers hold the same area 0 and `7,13`
    facing north that Curse's do, and its table has no area 0 -- so before
    this the case existed and the answer had not been measured, and a caller
    had to refuse rather than convert to whichever area looked likeliest.
    """
    start = areas.start_of(SECRET_OF_THE_SILVER_BLADES)
    assert start.area == 0x10
    assert (start.arrival.x, start.arrival.y) == (3, 3)
    assert start.arrival.facing_letter == "S"
    assert start.confidence == Confidence.CONFIRMED
    row = areas.start_area(SECRET_OF_THE_SILVER_BLADES)
    assert row.ecl == "ECL10" and row.geos == ("GEO10",) and row.disk == 1
    assert areas.area_in(0, SECRET_OF_THE_SILVER_BLADES) is None


def test_every_start_names_a_row_of_its_own_titles_table():
    """A `STARTS` entry pointing at an id its title does not have would send a
    conversion after a script that is on none of the sides, which is the
    failure `#301 (A DOS Curse save standing in area 0 is refused by the
    import, because no row of the area table names area 0)` measured on the
    C64: the loader asked for `GEO00` for ever."""
    for title, start in areas.STARTS.items():
        row = areas.area_in(start.area, title)
        assert row is not None, f"{title} starts in {start.area}, no such row"
        # The conversion has to name a map and a disk side, so a start whose
        # row loads no map is one it cannot write.
        assert row.geos, f"{title} starts in {row.ecl}, which loads no map"
        # And exactly one: `goldbox.dos_codec.apply_file_cache` writes `row.geo`
        # for a party that has not set out, since the save's own `$49C5` is
        # the initialiser's 0 there, and `geo` is None for two maps.
        assert row.geo is not None, f"{title} starts in {row.ecl}: {row.geos}"
        assert start.confidence is areas.Confidence.CONFIRMED


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
# These tests ask of the Pool of Radiance disks the questions the Silver Blades
# tests ask of theirs, through the reader that built the Silver Blades table, so
# that reader is checked against a second game.


@pytest.fixture(scope="module")
def pool_table():
    """Pool of Radiance's scripts read by `tools/areas/areatable.py`, or skip."""
    areatable = pytest.importorskip("tools.areas.areatable")
    gamedisks = pytest.importorskip("automap.gamedisks")
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

    **One exception in the remaining twenty-eight.** `ECL07` loads file 3 as
    well as its own 7, on its way into area 3, and the table gives `GEO03` to
    area 3 rather than to area 7. That is deliberate, and Silver Blades'
    `ECL30` does the same thing for areas `$31` and `$32`, so a script loading
    the *next* area's map is a shape both titles have.

    `ECL1E` used to be a second, unintended exception here: the table gave it
    no map at all, and its script actually carries `LOADFILES 18, 2, 255` at
    `$9A54` -- `GEO12`, Podol Plaza, which is what the attract-mode demo walks
    a party around. `#260 (Area 30 is recorded as having no map, and ECL1E
    loads GEO12)` gave area 30's `geos` `GEO12`, so it agrees with the script
    now and drops out of this dict.

    `Script.geos()` and `Script.sqrdatas()` are unioned back into one set of
    file numbers, because a set of numbers is what this test compares. The
    tool tells the two apart now -- it propagates `$49E6` to every load and
    puts the outdoor ones in `sqrdatas()` -- and which load is which is
    asserted in `tests/areas/test_areatable.py` rather than here."""
    exceptions = {}
    for a in areas.AREAS:
        if a.dynamic_geo:
            continue
        claimed = {areas.geo_number(g) for g in a.geos}
        if a.sqrdata:
            claimed.add(int(a.sqrdata[-2:], 16))
        loaded = (set(pool_table[a.ecl].geos())
                  | set(pool_table[a.ecl].sqrdatas()))
        if claimed != loaded:
            exceptions[a.ecl] = (sorted(claimed), sorted(loaded))
    assert exceptions == {"ECL07": ([7], [3, 7])}
