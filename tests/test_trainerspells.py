"""The trainer's spell step, per class and per title (#89).

Two halves. The disk-backed ones read each title's own `GEN` through
`tools/trainerspells.py` and diff it against `goldbox/levelup.py`, so the
model cannot drift from the game. The disk-free ones pin the two claims that
took this ticket apart: that Curse grants a ranger and a paladin, which the
model gave them nothing for, and that Silver Blades' magic-user is offered a
menu rather than a whole row.

`tools/trainerspells.py` is the tool; `docs/135-levelling.md` is the prose.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import c64_port, levelup, spells  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402
from tools import gamedisks, trainerspells  # noqa: E402

POOL = c64_port.POOL_OF_RADIANCE
CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS
SSB = c64_port.SECRET_OF_THE_SILVER_BLADES

KEYS = {"pool": "pool-of-radiance", "curse": "curse-of-the-azure-bonds",
        "ssb": "secret-of-the-silver-blades"}


def _steps(title: str):
    """Every trainer spell step of one title, or skip for want of a disk."""
    if gamedisks.find(KEYS[title]) is None:
        variable = gamedisks.entry(KEYS[title]).get(gamedisks.ENV, "?")
        pytest.skip(f"needs the {KEYS[title]} disks; set ${variable}")
    return trainerspells.read(title)


def _caster(level_field: str, level: int, intelligence: int = 18,
            wisdom: int = 18) -> CharacterRecord:
    rec = CharacterRecord.blank()
    rec.set(level_field, level)
    rec.set("intelligence", intelligence)
    rec.set("wisdom", wisdom)
    rec.set_raw("abilities_second",
                bytes((9, intelligence, wisdom, 9, 9, 9, 0)))
    return rec


# --- the whole model against the three disks --------------------------------

@pytest.mark.parametrize("title", sorted(KEYS))
def test_every_class_of_every_title_matches_its_own_overlay(title):
    """`tools/trainerspells.py --check`, run as a test.

    Every class, every level its own ceiling reaches, and -- where the title
    asks for one -- four intelligences and both sides of the Wisdom gate.
    """
    if gamedisks.find(KEYS[title]) is None:
        pytest.skip(f"needs the {KEYS[title]} disks")
    assert trainerspells.check(title) == []


def test_the_steps_are_the_ones_the_sequence_calls():
    """The claim the tool exists to make: a routine is a trainer step only
    when the title's own level-up sequence `JSR`s it.

    Silver Blades' `$0F7C` and Curse's `$167F` are grant loops of exactly the
    trainer's shape and neither is in a sequence, which is how both came to be
    read as trainer steps in the first place.
    """
    for title in sorted(KEYS):
        if gamedisks.find(KEYS[title]) is None:
            pytest.skip(f"needs the {KEYS[title]} disks")
        data = trainerspells.overlay(title, "GEN")
        called = trainerspells._sequence_calls(data, title)
        for name, _, at, shape in trainerspells.STEPS:
            if name == title:
                assert at in called, f"{title} ${at:04X} ({shape})"
        if title == "ssb":
            assert 0x0F7C not in called, "the starting spellbook is in the "\
                "sequence after all"
        if title == "curse":
            assert 0x167F not in called, "the starting spellbook is in the "\
                "sequence after all"


def test_silver_blades_magic_user_step_is_a_menu():
    """`$1896` builds a list to choose from: it clears sixteen scratch bytes,
    ORs the candidate rows into them, masks off what the character already
    knows, and walks the result storing one id a slot."""
    step = _steps("ssb")["magic-user"]
    assert step["shape"] == "menu_blades"
    assert step["at"] == 0x1896
    # The permanent intelligence at `0x066`, not the score in force at 0x015.
    assert step["score"] == 0x066
    assert step["last"] == 0x76               # ids 0-117


def test_curse_grants_the_ranger_and_the_paladin():
    """Both were absent from the model until 2026-09-08, and both are steps
    four and five of Curse's own sequence."""
    steps = _steps("curse")
    assert steps["ranger"]["at"] == 0x2305
    assert steps["ranger"]["rows"][8] == {77, 78, 79, 80}
    assert steps["ranger"]["rows"][9] == {77, 78, 79, 80} | set(range(9, 22))
    assert steps["paladin"]["at"] == 0x22F4
    assert steps["paladin"]["gate"] == 9
    # The row never moves: a Curse paladin of 11 knows the same eight spells
    # as one of 9.
    assert {steps["paladin"]["rows"][lv] for lv in (9, 10, 11)} == {1}


def test_silver_blades_paladin_climbs_where_curses_does_not():
    """`$1BF6 SBC #$08 / TAX` against Curse's `$22FF LDX #$01`."""
    rows = _steps("ssb")["paladin"]["rows"]
    assert [rows[lv] for lv in range(9, 16)] == [1, 2, 3, 4, 5, 6, 7]


# --- the model on its own, with no disk -------------------------------------

def test_a_ranger_gets_nothing_in_pool_of_radiance():
    """There is no ranger to give it to: Pool of Radiance has four classes."""
    assert levelup._ranger_spell_ids(9, POOL) == []
    assert levelup._paladin_spell_ids(9, POOL) == []


def test_a_curse_ranger_gets_the_druid_and_magic_user_first_levels():
    assert levelup._ranger_spell_ids(7, CURSE) == []
    assert levelup._ranger_spell_ids(8, CURSE) == [77, 78, 79, 80]
    assert levelup._ranger_spell_ids(9, CURSE) == list(range(9, 22)) + \
        [77, 78, 79, 80]
    # Curse's ceiling is 11, so it never reaches what Silver Blades adds at 12.
    assert levelup._ranger_spell_ids(11, CURSE) == \
        levelup._ranger_spell_ids(9, CURSE)
    assert 90 in levelup._ranger_spell_ids(12, SSB)


def test_a_paladin_gets_cleric_spells_from_nine_in_both_later_titles():
    assert levelup._paladin_spell_ids(8, CURSE) == []
    assert levelup._paladin_spell_ids(9, CURSE) == list(range(1, 9))
    assert levelup._paladin_spell_ids(11, CURSE) == list(range(1, 9))
    assert levelup._paladin_spell_ids(11, SSB) == \
        list(range(1, 9)) + list(range(22, 29))


def test_the_silver_blades_menu_is_not_the_arithmetic_one():
    """Levels 11, 13 and 15 are where the table and `(level + 1) // 2` part."""
    for level in (11, 13, 15):
        assert levelup.menu_spell_level(level, 18, SSB) == (level + 1) // 2 - 1
    for level in (1, 5, 9, 12, 14):
        assert levelup.menu_spell_level(level, 18, SSB) == (level + 1) // 2


def test_intelligence_gates_only_silver_blades():
    """A score of 11 costs a magic-user of 12 its sixth-level spells, and
    neither earlier title reads the score at all."""
    assert levelup.menu_spell_level(12, 11, SSB) == 5
    assert levelup.menu_spell_level(12, 12, SSB) == 6
    assert levelup.menu_spell_level(14, 13, SSB) == 6
    assert levelup.menu_spell_level(14, 14, SSB) == 7
    for game in (POOL, CURSE):
        assert levelup.menu_spell_level(11, 3, game) == 6


def test_the_permanent_score_is_what_the_later_trainers_read():
    """`$7C66` and `$7C67` are `abilities_second`, so a drained magic-user is
    offered what its rolled score allows."""
    rec = _caster("level_magic_user", 12, intelligence=12)
    rec.set("intelligence", 3)                 # drained to nothing in force
    assert 110 in levelup.learnable(rec, SSB, level=12)
    rec.set_raw("abilities_second", bytes((9, 3, 18, 9, 9, 9, 0)))
    assert 110 not in levelup.learnable(rec, SSB, level=12)


def test_a_record_with_no_second_array_falls_back_to_the_score_in_force():
    """Every Pool of Radiance record leaves `0x065` zero, and a record built
    by hand may as well. Reading 0 there would silently cap a caster."""
    rec = CharacterRecord.blank()
    rec.set("level_magic_user", 12)
    rec.set("intelligence", 18)
    assert levelup._permanent(rec, 1, "intelligence") == 18


def test_the_menu_never_offers_the_duplicate_death_spell():
    """109 and 110 are both DEATH SPELL and `$1896`'s mask has only 110."""
    assert 109 in {i for low, high, who, lv in
                   spells.SECRET_OF_THE_SILVER_BLADES.groups
                   if who == "magic-user" for i in range(low, high + 1)}
    assert spells.SECRET_OF_THE_SILVER_BLADES.not_granted == (109,)
    rec = _caster("level_magic_user", 14)
    offered = levelup.learnable(rec, SSB, level=14)
    assert 110 in offered and 109 not in offered


def test_a_silver_blades_cleric_needs_wisdom_seventeen_for_the_sixth_level():
    """`$0F39 LDA $7C67 / CMP #$11`, and the two ids behind it are 36 ANIMATE
    DEAD and 56 RAISE DEAD."""
    assert 36 not in levelup._cleric_spell_ids(11, SSB, 16)
    assert 36 in levelup._cleric_spell_ids(11, SSB, 17)
    assert 56 in levelup._cleric_spell_ids(11, SSB, 17)
    assert levelup._cleric_spell_ids(11, SSB, 16) == \
        levelup._cleric_spell_ids(10, SSB, 16)
