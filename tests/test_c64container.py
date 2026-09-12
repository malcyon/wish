"""`goldbox/c64_save.py`'s merged `C64Container`, and the refusal it inherited.

`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)`'s stage 7 folded
`goldbox.games.Game` -- six titles' disk geometry -- into `Container`, which
held three titles' payload map, so there is now one class with six rows and
three of them carry a payload map nobody has measured.

**The whole risk of that merge is one thing**: a title with no measured
payload map answering with Pool of Radiance's offsets instead of refusing,
which is `#460 (goldbox/games.py has no Pools of Darkness entry, so every
lookup answers with Pool of Radiance's tables for it)` one class over.  Before
the merge the refusal was free, because Champions of Krynn simply was not a
`Container` and `container_for` had nothing to hand back.  Now it is a
`C64Container` with plausible defaults in every payload-map field, so the
refusal is a line of code and this file is what holds it there.

What the rest of the file pins is the duplication the merge did **not** end:
the module constants and the field defaults still say `0x400` twice, and
`goldbox/c64_port.py` re-exports the constants, so each pair is asserted equal
rather than left to drift.
"""

import dataclasses

import pytest

from goldbox import c64_port, c64_save, titles
from goldbox.c64_save import C64Container

MEASURED = ("pool-of-radiance", "curse-of-the-azure-bonds",
            "secret-of-the-silver-blades")
UNMEASURED = ("champions-of-krynn", "death-knights-of-krynn",
              "gateway-to-the-savage-frontier")


# --- the registry -----------------------------------------------------------

def test_the_six_rows_are_one_class_and_one_object_per_title():
    """`goldbox.c64_port.Game` and `c64_save.Container` are the same class now.

    A caller holding either name holds the same six objects -- which is what
    lets `container.game` answer `container`.
    """
    assert c64_port.Game is C64Container
    assert c64_save.Container is C64Container
    assert len(c64_port.GAMES) == 6
    assert all(isinstance(g, C64Container) for g in c64_port.GAMES)
    assert c64_port.POOL_OF_RADIANCE is c64_save.POOL_OF_RADIANCE
    assert c64_port.GATEWAY_TO_THE_SAVAGE_FRONTIER is \
        c64_save.GATEWAY_TO_THE_SAVAGE_FRONTIER


def test_pool_of_radiance_and_curse_are_still_the_first_two():
    """`wish/preferences.py` takes `list(games.GAMES)[:2]`.

    An order dependency on the tuple, so the merge had to keep the order the
    merge could most easily have lost.
    """
    assert [g.key for g in c64_port.GAMES[:2]] == [
        "pool-of-radiance", "curse-of-the-azure-bonds"]
    assert [g.key for g in c64_port.GAMES] == list(MEASURED) + list(UNMEASURED)


def test_a_row_is_its_own_game_and_answers_both_slot_counts():
    for game in c64_port.GAMES:
        assert game.game is game
        assert game.slot_count == game.party_slots == 8


def test_a_game_descriptor_is_still_hashable():
    """The tables are pairs rather than dicts for exactly this reason, and the
    merge added `rules`, which is a frozen dataclass and hashable too."""
    assert len(set(c64_port.GAMES)) == len(c64_port.GAMES)


# --- the refusal ------------------------------------------------------------

@pytest.mark.parametrize("key", UNMEASURED)
def test_an_unmeasured_title_is_refused_by_key_as_it_always_was(key):
    with pytest.raises(KeyError):
        c64_save.container_for(key)
    assert key not in c64_save.CONTAINERS
    assert c64_save.CONTAINERS.get(key) is None


@pytest.mark.parametrize("key", UNMEASURED)
def test_an_unmeasured_title_is_refused_by_its_own_row(key):
    """The door the merge opened, and the one `measured` exists to shut.

    `container_for` short-circuits on anything that is already a container,
    and after the merge Champions of Krynn *is* one -- so without the
    `measured` check it would hand back a row whose every header offset is
    Pool of Radiance's by default.  `tools/carryceiling.py` counts on this
    raise to say a title was not counted.
    """
    row = c64_port.BY_KEY[key]
    assert isinstance(row, C64Container) and not row.measured
    with pytest.raises(KeyError):
        c64_save.container_for(row)


@pytest.mark.parametrize("key", MEASURED)
def test_a_measured_title_answers_its_own_row(key):
    assert c64_save.container_for(key) is c64_port.BY_KEY[key]
    assert c64_save.container_for(c64_port.BY_KEY[key]) is c64_port.BY_KEY[key]
    assert c64_port.BY_KEY[key].measured is True


def test_no_title_at_all_still_means_pool_of_radiance():
    assert c64_save.container_for(None) is c64_save.POOL_OF_RADIANCE


def test_the_measured_set_and_the_flag_cannot_drift_apart():
    assert set(c64_save.CONTAINERS) == set(MEASURED)
    assert {g.key for g in c64_port.GAMES if g.measured} == set(MEASURED)


# --- the title it belongs to ------------------------------------------------

@pytest.mark.parametrize("key", MEASURED + UNMEASURED)
def test_a_row_holds_its_titles_own_object(key):
    """`rules` is the composition `#470` was built to make visible.

    By identity rather than equality: a row carrying an equal-but-separate
    `Title` would be a second copy of the races and class bits, which is the
    duplication stage 1 removed.
    """
    row = c64_port.BY_KEY[key]
    assert row.rules is titles.BY_KEY[key]
    assert row.key == row.rules.key and row.title == row.rules.title
    assert row.races is row.rules.races
    assert row.class_bits is row.rules.class_bits


def test_only_pool_of_radiance_has_a_travel_grid():
    assert [g.key for g in c64_port.GAMES if g.travel_grid] == ["pool-of-radiance"]
    assert c64_port.POOL_OF_RADIANCE.indoors_flag_base == 0x49E6
    assert c64_port.CURSE_OF_THE_AZURE_BONDS.indoors_flag_base is None


def test_a_row_built_outside_the_registry_gets_a_title_with_no_tables():
    """The same answer `automap.c64._machine` has given such a row since
    stage 6: a `Title` of its own, and `None` races meaning "we do not know"
    rather than Pool of Radiance's list."""
    made_up = C64Container(key="untabled", title="Untabled",
                           save_file=b"SAVEX", save_load_address=0x4000,
                           save_size=0x1C00)
    assert made_up.rules.key == "untabled" and made_up.rules.title == "Untabled"
    assert made_up.rules.races is None and made_up.rules.class_bits is None
    assert made_up.rules.travel_grid is False
    assert made_up.race_names is None
    assert not made_up.measured


def test_replacing_a_rows_tables_leaves_the_row_answering_none():
    """`dataclasses.replace(row, races=None)` is how `tests/test_gametables.py`
    builds the designed failure -- no names at all rather than wrong ones --
    and it has to keep working now that `rules` sits beside `races`."""
    blank = dataclasses.replace(c64_port.POOL_OF_RADIANCE, races=None,
                                class_bits=None)
    assert blank.race_names is None and blank.class_bit_names is None
    assert blank.rules is titles.POOL_OF_RADIANCE


# --- what the merge did not deduplicate -------------------------------------

@pytest.mark.parametrize("constant,field", [
    ("HEADER_SIZE", "slot_area"),
    ("SLOT_STRIDE", "slot_stride"),
    ("ITEM_AREA_OFFSET", "item_area"),
    ("ICON_TABLE_OFFSET", "icon_table"),
    ("ROSTER_PAGE", "roster_size"),
    ("POSITION_OFFSET", "position"),
    ("INDOORS_FLAG_OFFSET", "indoors"),
    ("TRAVEL_POSITION_OFFSET", "travel_position"),
])
def test_each_module_constant_is_the_field_default_it_names(constant, field):
    """Two names for one offset, so the pair is asserted rather than trusted.

    The constants are what `automap/c64.py` reads for a title with no measured
    payload map, and the fields are what every measured row answers; they said
    the same number in two places before the merge and still do.
    """
    assert getattr(c64_save, constant) == getattr(C64Container, field)
    assert getattr(c64_port, constant) is getattr(c64_save, constant)


@pytest.mark.parametrize("key", MEASURED)
def test_a_measured_row_agrees_with_the_constants_it_could_have_moved(key):
    row = c64_port.BY_KEY[key]
    assert row.slot_area == c64_save.HEADER_SIZE
    assert row.item_area == c64_save.ITEM_AREA_OFFSET
    assert row.icon_table == c64_save.ICON_TABLE_OFFSET
    assert row.position == c64_save.POSITION_OFFSET
    assert row.indoors == c64_save.INDOORS_FLAG_OFFSET
    assert row.travel_position == c64_save.TRAVEL_POSITION_OFFSET


@pytest.mark.parametrize("key", MEASURED + UNMEASURED)
def test_the_shown_clock_is_one_past_the_six_digits_the_row_names(key):
    """`clock` is six digits from `+$C6` and the status line draws three of
    them from `+$C7`; `clock_base` is the second fact and computes from the
    first, so the two cannot come apart."""
    row = c64_port.BY_KEY[key]
    assert c64_save.SHOWN_CLOCK_OFFSET == row.clock + 1
    assert row.clock_base == row.save_load_address + c64_save.SHOWN_CLOCK_OFFSET


# --- the roster, which was two fields and is one ----------------------------

def test_the_roster_offset_says_where_the_roster_is_in_one_field():
    """`Game.roster_offset` was an int and `Container.roster_offset` an int or
    None, with Pool of Radiance the row where they disagreed.  One field now,
    and `roster_in_payload` is the question both callers were asking."""
    pool = c64_port.POOL_OF_RADIANCE
    assert pool.roster_file == b"SAVEDGAME1" and not pool.roster_in_payload
    assert pool.roster_offset == 0 and pool.roster_size == 0x800
    for game in c64_port.GAMES:
        if game is pool:
            continue
        assert game.roster_in_payload and game.roster_offset == 0x1C00
        assert game.roster_file is None and game.roster_size == 0x100
