"""Pools of Darkness' spell-slot rows and spell groups in `goldbox.spells`.

Two halves, and the split is deliberate. The disk-backed tests read the rows,
the spell table and the creation menus back out of the player's own DOS
`GAME.OVR` and `GAME.EXE` through `tools/dos/dospodtables.py`, so a
transcription slip in `goldbox/spells.py` fails rather than ships; they skip
where the archives are not on the machine. The rest pin the committed table
with no game data at all, which is what CI runs.

No game bytes are committed here: every number is read at run time or is the
handful of integers `goldbox/spells.py` already carries.
"""

from __future__ import annotations

import pytest

from goldbox import levels, spells

POD = "pools-of-darkness"

#: The record's three arrays are nine bytes each, so the committed rows are.
WIDTH = 9

#: The engine's own clamp, `cmp byte ptr [bp-2], 0x1d`.
CEILING = 29


@pytest.fixture(scope="module")
def game():
    """The player's own Pools of Darkness, or a skip."""
    tables = pytest.importorskip("tools.dos.dospodtables")
    try:
        return (tables,) + tables.load()
    except FileNotFoundError as exc:
        pytest.skip(f"needs the DOS Pools of Darkness archives: {exc}")


# --- the committed table, with no game data ---------------------------------

def test_the_title_has_its_own_table_rather_than_pool_of_radiances():
    assert POD in spells.BY_KEY
    assert spells.for_game(POD) is spells.POOLS_OF_DARKNESS
    assert spells.for_game(POD) is not spells.DEFAULT
    assert set(spells._SLOTS[POD]) == {
        "cleric", "druid", "magic-user", "paladin", "ranger"} - {"druid"}


def test_every_row_is_nine_wide_and_stops_at_the_engines_clamp():
    rows = spells._SLOTS[POD]
    for name in ("cleric", "magic-user", "paladin"):
        assert len(rows[name]) == CEILING, name
        assert {len(row) for row in rows[name]} == {WIDTH}, name
    assert len(rows["ranger"]) == CEILING
    for druid, magic_user in rows["ranger"]:
        assert len(druid) == len(magic_user) == WIDTH


def test_the_ceiling_rows_are_the_published_ad_and_d_numbers():
    """Class level 29, before any wisdom bonus and before either ceiling."""
    assert spells.capacity_by_class({"magic-user": 29}, 11, POD) == {
        "magic-user": (7, 7, 7, 7, 6, 6, 6, 6, 6)}
    assert spells.capacity_by_class({"cleric": 29}, 11, POD) == {
        "cleric": (9, 9, 9, 9, 9, 9, 7, 0, 0)}


def test_a_class_level_above_the_clamp_answers_the_clamped_row():
    """The engine reads row 29 for anything higher, so this must too."""
    top = spells.capacity_by_class({"magic-user": CEILING}, 11, POD)
    assert spells.capacity_by_class({"magic-user": 99}, 11, POD) == top


def test_a_cleric_reaches_spell_level_7_and_never_8_or_9():
    """The cleric loop stops at column 7, so the array's last two stay zero."""
    rows = spells._SLOTS[POD]["cleric"]
    assert [row[6] for row in rows].count(0) == 15      # levels 1-15
    assert rows[15][6] == 1                             # level 16, the first
    assert {row[7] for row in rows} == {0}
    assert {row[8] for row in rows} == {0}


def test_a_magic_user_reaches_spell_level_9_at_18():
    rows = spells._SLOTS[POD]["magic-user"]
    assert rows[17][8] == 1
    assert {row[8] for row in rows[:17]} == {0}


def test_a_paladin_adds_to_the_cleric_array_without_a_wisdom_bonus():
    """Slot 3's rows land in the cleric array, and the bonus runs in slot 0."""
    assert spells.capacity_by_class({"paladin": 20}, 18, POD) == {
        "cleric": (3, 3, 3, 3, 0, 0, 0, 0, 0)}
    assert spells.capacity_by_class({"paladin": 8}, 18, POD) == {
        "cleric": (0,) * WIDTH}


def test_a_ranger_fills_the_druid_and_magic_user_arrays_from_8_and_9():
    assert spells.capacity_by_class({"ranger": 8}, 18, POD) == {
        "druid": (1, 0, 0, 0, 0, 0, 0, 0, 0), "magic-user": (0,) * WIDTH}
    assert spells.capacity_by_class({"ranger": 17}, 18, POD) == {
        "druid": (2, 2, 2, 0, 0, 0, 0, 0, 0),
        "magic-user": (2, 2, 0, 0, 0, 0, 0, 0, 0)}


def test_a_cleric_paladin_sums_into_one_array_as_the_builder_does():
    """The builder clears the block once and adds every class slot into it."""
    got = spells.capacity_by_class({"cleric": 9, "paladin": 9}, 11, POD)
    assert got == {"cleric": (5, 4, 3, 2, 1, 0, 0, 0, 0)}


def test_the_spell_groups_cover_every_id_and_stop_at_126():
    table = spells.for_game(POD)
    assert table.last_spell == 126
    grouped = {i for first, last, _, _ in table.groups
               for i in range(first, last + 1)}
    assert grouped | set(table.not_a_spell) == set(range(1, 127))
    assert not grouped & set(table.not_a_spell)
    assert len(grouped) == 115 and len(table.not_a_spell) == 11


def test_109_is_a_druid_spell_which_corrects_silver_blades_reading():
    """Silver Blades' trainer was not skipping a magic-user spell."""
    assert spells.spell_group(109, POD) == ("druid", 3)
    assert 109 in spells._NOT_GRANTED_SILVER_BLADES
    assert spells.spell_group(109, "secret-of-the-silver-blades") == (
        "magic-user", 6)


def test_the_three_probable_silver_blades_groups_are_confirmed_here():
    """36, 56 and 115-117, out of the fourth engine's own class bytes."""
    assert spells.spell_group(36, POD) == ("cleric", 6)
    assert spells.spell_group(56, POD) == ("cleric", 6)
    for spell_id in (115, 116, 117):
        assert spells.spell_group(spell_id, POD) == ("magic-user", 7)


def test_the_spellbook_records_ids_1_to_126():
    """126 bytes from record `0x0B3`, one an id, against a 126-spell list."""
    table = spells.for_game(POD)
    assert table.spellbook_ids == 126
    assert table.last_spellbook_spell == 126
    assert table.in_spellbook(126)
    assert not table.in_spellbook(127)
    assert spells.spell_group(126, POD) == ("magic-user", 9)


def test_the_two_mask_helpers_refuse_a_title_with_no_mask():
    """This title has no C64 port, so `0x078` is not its spellbook."""
    assert spells.for_game(POD).spellbook_size == 0
    with pytest.raises(ValueError, match="no spellbook bitmask"):
        spells.spellbook_bytes([1], POD)
    with pytest.raises(ValueError, match="no spellbook bitmask"):
        spells.spells_known(bytes(512), POD)


# --- the same rows, read back off the player's own game ----------------------

def test_the_rows_are_the_games_own(game):
    """All four tables, every level to the engine's own clamp of 29."""
    tables, ovr, image, ds = game
    read = tables.slot_tables(ovr, image, ds)
    assert {0: "cleric", 3: "paladin", 4: "ranger", 5: "magic-user"}.keys() \
        == read.keys()
    rows = spells._SLOTS[POD]
    for level in range(1, CEILING + 1):
        assert rows["cleric"][level - 1] == read[0]["cleric"][level - 1], (
            "cleric", level)
        assert rows["magic-user"][level - 1] == (
            read[5]["magic-user"][level - 1]), ("magic-user", level)
        assert rows["paladin"][level - 1] == read[3]["cleric"][level - 1], (
            "paladin", level)
        druid, magic_user = rows["ranger"][level - 1]
        assert druid == read[4]["druid"][level - 1], ("ranger druid", level)
        assert magic_user == read[4]["magic-user"][level - 1], (
            "ranger magic-user", level)


def test_the_builder_clamps_at_29_and_the_cleric_assigns(game):
    """The two facts that make these rows readable as totals."""
    tables, ovr, image, ds = game
    assert tables.CEILING == CEILING
    site = tables.dosspellslots.builder_site(
        ovr, tables.dosspellslots.block_of(tables.RECORD_SIZE)[0])
    found = {b.number: b for b in tables.branches(ovr, site)}
    assert all(run.assigns for run in found[0].runs)
    for number in (3, 4, 5):
        assert not any(run.assigns for run in found[number].runs)
    assert {n: b.from_level for n, b in found.items()} == {
        0: 1, 3: 9, 4: 8, 5: 1}


def test_the_spell_groups_are_the_games_own(game):
    """Every id's class and level byte, out of the engine's own table."""
    tables, ovr, image, ds = game
    table, last = tables.spell_table(ovr, image, ds)
    read = tables.spell_groups(image, ds, table, last)
    committed = spells.for_game(POD)
    assert last == committed.last_spell
    for spell_id in range(1, last + 1):
        want = read[spell_id]
        if want[0] is None:
            assert spell_id in committed.not_a_spell, spell_id
            continue
        assert spells.spell_group(spell_id, POD) == want, spell_id


def test_the_wisdom_bonus_is_curses_table_and_not_pool_of_radiances(game):
    """Read off the cleric helper's own six compares.

    What the engine does is Curse's and Silver Blades' table point for
    point, which is the tuple this checks against.
    """
    tables, ovr, image, ds = game
    site = tables.dosspellslots.builder_site(
        ovr, tables.dosspellslots.block_of(tables.RECORD_SIZE)[0])
    cleric = next(b for b in tables.branches(ovr, site) if b.number == 0)
    bonus, ceilings = tables.branch_gates(ovr, cleric)
    block = tables.dosspellslots.block_of(tables.RECORD_SIZE)[0]
    # (the score the compare is above, the cleric spell level incremented)
    got = tuple((score + 1, slot - block + 1) for _, score, _, slot in bonus)
    assert got == ((13, 1), (14, 1), (15, 2), (16, 2), (17, 3), (18, 4))

    def engine(wisdom, width=5):
        """The engine's compares as a cumulative row, the way the
        `goldbox.levels` tables answer."""
        out = [0] * width
        for score, level in got:
            if wisdom >= score:
                out[level - 1] += 1
        return tuple(out)

    curse = levels.BY_KEY["curse-of-the-azure-bonds"]
    for wisdom in range(3, 19):
        assert engine(wisdom) == curse.wisdom_bonus_spells(wisdom), wisdom
    # Curse's table has one more row, at wisdom 19, and this engine has no
    # compare above 18 -- a score no race's own maximum reaches anyway.
    assert engine(19) != curse.wisdom_bonus_spells(19)
    assert engine(19) == engine(18)
    # And the ceiling that follows: wisdom under 17 and 18 zero levels 6 and 7
    assert [(score, slot - block + 1) for _, score, slot in ceilings] == [
        (17, 6), (18, 7)]


def test_the_creation_menu_offers_six_races_and_a_fifteen_character_name(game):
    """The menus, for the boundary work: what a player can actually make."""
    tables, ovr, image, ds = game
    found = tables.menus(ovr, image, ds)
    assert found["races"] == ["Elf", "Half-Elf", "Dwarf", "Gnome", "Halfling",
                              "Human"]
    assert found["race_names_held"][len(found["races"]):] == ["Monster"]
    assert [len(row) for row in found["classes_by_race"]] == [7, 13, 3, 3, 3, 6]
    offered = {found["class_names"][c]
               for row in found["classes_by_race"] for c in row}
    assert "Druid" not in offered and "Monk" not in offered
    assert found["name_max"] == found["name_copy_max"] == 15
    # Human, the race with no ability restriction of its own
    human = found["ability_limits"][found["races"].index("Human")]
    assert human[:4] == (3, 3, 18, 18)
    assert human[6:] == (3, 18) * 5
    # A paladin's minima, which are AD&D 1st edition's own
    paladin = found["class_minimums"][found["class_names"].index("Paladin")]
    assert paladin == (12, 9, 13, 0, 9, 17)
