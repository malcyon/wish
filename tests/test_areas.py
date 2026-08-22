"""The area table, and the title key that stops it lying about Curse.

The table's claims are checked against the game's own scripts where those are
present under `work/ecl-scripts/` -- disassemblies produced by this project,
not game data -- and skipped where they are not, exactly as `tests/gamedata.py`
skips when no disk is attached.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from automap.state import AREA_NAMES, AutomapState
from por import areas
from por.areas import (
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
        pytest.skip("no ECL disassemblies under work/ecl-scripts/")
    return found


def test_the_table_names_exactly_the_scripts_on_the_disks(scripts):
    assert set(scripts) == {a.id for a in areas.AREAS}


def test_every_disk_number_matches_the_disk_the_script_is_on(scripts):
    """`Area.disk` is what a warp writes to `$6E12`; getting it wrong makes the
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


# -- the seam with por/games.py ----------------------------------------------


def test_the_title_strings_match_the_per_game_descriptor():
    """`por/areas.py` takes a title as a plain string on purpose, so that it
    does not have to import the descriptor. This is the one place the two have
    to agree: `areas.GEO_NAMES[game.title]` is how a caller with a `Game` looks
    a name up. Skipped while `por/games.py` does not yet exist."""
    games = pytest.importorskip("por.games")
    for attr, title in (("POOL_OF_RADIANCE", POOL_OF_RADIANCE),
                        ("CURSE_OF_THE_AZURE_BONDS", CURSE_OF_THE_AZURE_BONDS)):
        game = getattr(games, attr, None)
        if game is None or not hasattr(game, "title"):
            pytest.skip(f"por.games has no {attr}.title yet")
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
