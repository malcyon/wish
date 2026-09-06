from __future__ import annotations

"""`goldbox/levels.py`'s Silver Blades tables, disk-free.

`#187 (Silver Blades characters are shown Pool of Radiance's level
progression)`: `goldbox/levels.py:for_game` used to fall back to Pool of
Radiance for Silver Blades, so a level-9 Silver Blades magic-user was shown
against Pool of Radiance's ceiling of 6. This file pins the built table
without needing the player's own disks -- `tests/test_coldread.py`'s A6/A7
section is what checks the same numbers against `GEN`.
"""

import dataclasses

import pytest

from goldbox import games, levels, levelup
from goldbox.record import CharacterRecord

POOL = levels.POOL_OF_RADIANCE
SSB = levels.SECRET_OF_THE_SILVER_BLADES


def test_a_silver_blades_magic_user_is_shown_a_ceiling_of_15():
    assert levels.ceiling("magic-user", SSB) == 15
    assert levels.for_game(SSB) is SSB


def test_a_level_nine_silver_blades_magic_user_is_not_at_maximum():
    """The card the roster shows -- `automap/live.py:_classes` -- not just
    the table lookup underneath it.

    Through Pool of Radiance's tables (the fallback #187 removed) a level-9
    magic-user is past the ceiling of 6 and reads "maximum"; through Silver
    Blades' own tables it is partway to 15.
    """
    from automap import live

    rec = CharacterRecord.blank()
    rec.set("class_bits", 1)
    rec.set("level_magic_user", 9)
    rec.set("experience", 200000)

    (ssb_progress,) = live._classes(rec, SSB)
    assert ssb_progress.next_threshold == 250001
    assert not ssb_progress.at_ceiling
    assert ssb_progress.fraction == pytest.approx(
        (200000 - 135001) / (250001 - 135001))

    # The control: the same record, with no title (Pool of Radiance's
    # default), reads as a fighter... no, a magic-user past Pool of
    # Radiance's ceiling of 6, which is exactly the wrong answer #187 found.
    (pool_progress,) = live._classes(rec, POOL)
    assert pool_progress.at_ceiling


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_card_shows_a_silver_blades_experience_bar(app):
    """The sibling of
    `tests/test_automap.py::test_a_card_at_a_class_ceiling_says_maximum`,
    for a title where the same record is not at its ceiling."""
    from automap import live
    from automap.panel import CharacterCard
    from tests.test_automap import make_root

    rec = CharacterRecord.blank()
    rec.set("class_bits", 1)
    rec.set("level_magic_user", 9)
    rec.set("experience", 200000)
    (progress,) = live._classes(rec, SSB)

    card = CharacterCard(make_root(), 0)
    card.show_character(live.Character(
        slot=0, name="MORGAINE", classes=(progress,), level=9,
        armour_class=2, thac0=13, hp=60, hp_max=60, experience=200000))
    assert card.xp[0].text == "200000 / 250001 xp"


def test_the_six_shipped_saves_reproduce_without_disks():
    """The literals `tests/test_coldread.py` reproduces off the player's own
    `GEN` -- kept here too so this file's tests need no disks at all.

    MALACHITE and GUY DE VALOIS are the two that discriminate: MALACHITE is
    the dwarf, race 3, so three of his five columns carry the constitution
    bonus; GUY DE VALOIS is the paladin, so his row is the fighter's less
    two. Getting either rule wrong would still fit the other four.
    """
    cases = (
        ("MORGAINE", {"magic-user": 9}, 6, 16, (13, 11, 9, 13, 10)),
        ("MALACHITE", {"thief": 8, "fighter": 7}, 3, 17, (6, 11, 8, 12, 9)),
        ("DOMINIC", {"cleric": 8}, 6, 17, (7, 10, 11, 13, 12)),
        ("PAINE", {"ranger": 8}, 6, 16, (10, 11, 12, 12, 13)),
        ("EPONA", {"fighter": 8}, 6, 17, (10, 11, 12, 12, 13)),
        ("GUY DE VALOIS", {"paladin": 8}, 6, 18, (8, 9, 10, 10, 11)),
    )
    for name, class_levels, race, constitution, expect in cases:
        got = levels.saving_throws(class_levels, race, constitution, game=SSB)
        assert got == expect, name


def test_levelling_still_refuses_silver_blades_even_with_thief_skills_filled():
    """Proves the guard in `goldbox/levelup.py:_tables_for` asks
    `levels.trainer_measured` and not `tables.thief_skills` -- an empty tuple
    that would stop refusing the moment somebody attributes `$126D`.

    Filling `thief_skills` from Pool of Radiance's table (a stand-in for "the
    field is no longer empty") must still be refused: the old guard let this
    straight through, because it only asked whether the tuple was empty.
    """
    filled = dataclasses.replace(SSB, thief_skills=POOL.thief_skills)
    assert filled.thief_skills            # the old guard would now say yes
    assert not levels.trainer_measured(filled)   # the new guard still says no

    rec = CharacterRecord.blank()
    rec.set("class_bits", 8)
    rec.set("level_fighter", 5)
    rec.set("experience", 1_000_000)
    rec.set("wisdom", 12)
    rec.set("constitution", 12)
    rec.set("thac0_base", 40)

    with pytest.raises(levelup.CannotLevel) as exc:
        levelup.plan(rec, "fighter", game=filled)
    assert filled.title in str(exc.value)


def test_a_few_more_rows_off_the_top_of_each_table():
    assert levels.hit_die("paladin", SSB) == 10
    assert levels.hit_die("ranger", SSB) == 8
    assert levels.at_level("thief", 18, SSB).thac0 == 12
    assert levels.at_level("fighter", 15, SSB).attacks == 2
    assert levels.at_level("cleric", 15, SSB).spells == ()


def test_silver_blades_is_among_the_titles_a_race_with_no_bonus_covers():
    """`levels.TITLES` now has three entries; a test that loops it (in
    `tests/test_curselevels.py` and `tests/test_levels.py`) covers Silver
    Blades for free. This is the version of that check that lives beside the
    new title's own tests."""
    assert SSB in levels.TITLES
    assert games.SECRET_OF_THE_SILVER_BLADES.key == SSB.key


#: What Silver Blades' own trainer wrote at `0x09A`-`0x09E` for MALACHITE --
#: thief 8 / fighter 7, constitution 17 -- raised to thief 9 five times on
#: one boot (VICE pool slot 0, 2026-09-06, `tools/ssbtrain.py`,
#: `work/issue344/m1..m6`), with only the race byte poked between presses and
#: the five stored saves poked to 14 first so each row is a write and not a
#: keep. The DOS values he arrived with were `10 7 5 9 6`.
MALACHITE_PRESSES = (
    (3, (6, 10, 6, 12, 7)),       # dwarf, from the DOS row
    (4, (10, 10, 10, 12, 11)),    # gnome, from 14s
    (5, (10, 10, 10, 12, 11)),    # halfling, from 14s
    (6, (10, 10, 10, 12, 11)),    # human, from 14s
    (3, (6, 10, 6, 12, 7)),       # dwarf again, from 14s
)


def test_the_trainer_gave_the_bonus_to_the_dwarf_and_to_nobody_else():
    """`#344 (A converted Silver Blades dwarf, gnome or halfling keeps DOS's
    saving throws, because that title's racial bonus has never been watched
    in the game)`: `GEN $11D8` is `LDA $7C72 / CMP #$03 / BNE rts`, an
    equality test on race 3, where Pool of Radiance and Curse give the bonus
    to three races. This is the five rows the engine wrote against what
    `saving_throws` computes, and it is what put the title into
    `RACIAL_SAVE_BONUS_MEASURED`.

    Give the gnome the bonus too -- `sturdy_races=(3, 4, 5)`, Pool of
    Radiance's shape under this title's numbering -- and rows 2 and 3 fail.
    """
    for race, wrote in MALACHITE_PRESSES:
        got = levels.saving_throws({"thief": 9, "fighter": 7}, race, 17,
                                   game=SSB)
        assert got == wrote, (race, got, wrote)
    # The discriminating half: the dwarf's row is not the others', so a
    # table that gave everybody the bonus, or nobody, cannot pass.
    assert MALACHITE_PRESSES[0][1] != MALACHITE_PRESSES[1][1]
    assert levels.racial_save_bonus_measured(SSB)
    assert levels.racial_save_bonus_measured(games.SECRET_OF_THE_SILVER_BLADES)
