"""What the game's own training hall wrote, checked against `por/levels.py`.

Twenty-nine level-ups were driven through the training school in area 11 on
2026-08-22 and the 580-byte record read before and after each one
(`work/reports/p18-party.md`).  The numbers below are what the *game* wrote, so
where they and `por/levels.py` disagree it is the table that is wrong.

Nothing here touches a disk or an emulator: the measurements are a handful of
integers, and the point of the file is that a future edit to `por/levels.py`
cannot quietly contradict them.
"""
from __future__ import annotations

import pytest

from por import levels

# --- what the trainer wrote ------------------------------------------------

# THAC0 per class per level, read off `0x071` as `60 - stored`.
MEASURED_THAC0 = {
    "fighter": {1: 20, 2: 19, 3: 18, 4: 17, 5: 16, 6: 15, 7: 14, 8: 13},
    "cleric": {1: 20, 2: 20, 3: 20, 4: 18, 5: 18, 6: 18},
    "magic-user": {1: 21, 2: 21, 3: 21, 4: 21, 5: 21, 6: 19},
    "thief": {1: 21, 2: 21, 3: 21, 4: 21, 5: 19, 6: 19, 7: 19, 8: 19, 9: 16},
}

# The five saving throws at `0x09A`-`0x09E`, from characters with no racial
# modifier -- SILAS (human fighter), ROLAND (human cleric), MALCYON (elf
# magic-user) and, for the thief column, LADY KATHERINE's rows reconstructed
# from the class minimum.  MAGNUS, a dwarf, reads three lower on all five at
# every level, which is why the race matters and is asserted separately.
MEASURED_SAVES = {
    "fighter": {
        1: (14, 15, 16, 17, 17), 2: (14, 15, 16, 17, 17),
        3: (13, 14, 15, 16, 16), 4: (13, 14, 15, 15, 16),
        5: (11, 12, 13, 13, 14), 6: (11, 12, 13, 13, 14),
        7: (10, 11, 12, 12, 13), 8: (10, 11, 12, 12, 13),
    },
    "cleric": {
        1: (10, 13, 14, 16, 15), 2: (10, 13, 14, 16, 15),
        3: (10, 13, 14, 16, 15), 4: (9, 12, 13, 15, 14),
        5: (9, 12, 13, 15, 14), 6: (9, 12, 13, 15, 14),
    },
    "magic-user": {
        1: (14, 13, 11, 15, 12), 2: (14, 13, 11, 15, 12),
        3: (14, 13, 11, 15, 12), 4: (14, 13, 11, 15, 12),
        5: (14, 13, 11, 15, 12), 6: (13, 11, 9, 13, 10),
    },
}

# `por/levels.py` used to give the fighter's breath save as 16 at level 4 and
# the game writes 15, on two independent characters -- SILAS 16 -> 15 and the
# dwarf MAGNUS 13 -> 12, at that level and no other.  **Settled (P76): the
# table was wrong.**  `GEN $1FCA + 18` holds mask `$0C` where the fighter's
# other four columns hold `$08`, so that column improves twice by level 4; AD&D
# 1st edition says 16 and the game has never agreed.  Nothing diverges now.
KNOWN_DIVERGENCES: set[tuple[str, int]] = set()

# What `0x0E8` held after training, per class per level reached.  The trainer
# clamps experience to one less than the *next* level's threshold, so each of
# these is an independent reading of a threshold -- including thresholds past
# the game's own ceilings, which its tables still carry.
MEASURED_CLAMP = {
    "thief": {2: 2500, 3: 5000, 4: 10000, 5: 20000, 6: 42500, 7: 70000,
              9: 160000},
    "cleric": {2: 3000, 3: 6000, 4: 13000, 5: 27500, 6: 55000},
    "magic-user": {2: 5000, 3: 10000, 4: 22500, 5: 40000, 6: 60000},
    "fighter": {2: 4000, 3: 8000, 4: 18000, 5: 35000, 6: 70000, 7: 125000,
                8: 250000},
}

# Thresholds the clamp read that lie past the class ceiling, so `por/levels.py`
# has no row for them.  The game's own tables do.
PAST_THE_CEILING = {("thief", 9): 160001, ("cleric", 6): 55001,
                    ("magic-user", 6): 60001, ("fighter", 8): 250001}

# The dwarf MAGNUS against the human SILAS, level for level.
DWARF_SAVE_MODIFIER = -3
MEASURED_DWARF_SAVES = {
    1: (11, 12, 13, 14, 14), 3: (10, 11, 12, 13, 13),
    4: (10, 11, 12, 12, 13), 5: (8, 9, 10, 10, 11),
}


def _levels(class_name):
    return {lv.level: lv for lv in levels.table(class_name)}


@pytest.mark.parametrize("class_name", sorted(MEASURED_THAC0))
def test_thac0_matches_the_trainer(class_name):
    table = _levels(class_name)
    for level, thac0 in MEASURED_THAC0[class_name].items():
        assert table[level].thac0 == thac0, f"{class_name} {level}"


@pytest.mark.parametrize("class_name", sorted(MEASURED_SAVES))
def test_saving_throws_match_the_trainer(class_name):
    table = _levels(class_name)
    for level, saves in MEASURED_SAVES[class_name].items():
        if (class_name, level) in KNOWN_DIVERGENCES:
            continue
        assert tuple(table[level].saves) == saves, f"{class_name} {level}"


def test_nothing_diverges_from_the_trainer_any_more():
    """P76 closed the last one. A new entry here means a new disagreement."""
    assert KNOWN_DIVERGENCES == set()


def test_the_dwarf_pays_three_on_every_column():
    fighter = MEASURED_SAVES["fighter"]
    for level, saves in MEASURED_DWARF_SAVES.items():
        expected = tuple(s + DWARF_SAVE_MODIFIER for s in fighter[level])
        assert saves == expected, f"dwarf fighter {level}"


@pytest.mark.parametrize("class_name", sorted(MEASURED_CLAMP))
def test_the_experience_clamp_reads_the_next_threshold(class_name):
    """Training leaves the character one point short of the level after."""
    for level, clamp in MEASURED_CLAMP[class_name].items():
        past = PAST_THE_CEILING.get((class_name, level))
        if past is not None:
            assert levels.next_threshold(class_name, level) is None
            assert clamp + 1 == past
            continue
        assert levels.next_threshold(class_name, level) == clamp + 1, \
            f"{class_name} {level}"


def test_attacks_step_at_fighter_seven():
    """`0x0D9` went 2 -> 3 there and at no other level in eight trainings."""
    table = _levels("fighter")
    assert table[6].attacks == 1
    assert table[7].attacks == 1.5
    assert table[8].attacks == 1.5


def test_the_ceilings_are_where_training_stopped():
    """`NO MORE ADVANCEMENT POSSIBLE` was seen at exactly these levels."""
    assert levels.ceiling("fighter") == 8
    assert levels.ceiling("cleric") == 6
    assert levels.ceiling("magic-user") == 6
    assert levels.ceiling("thief") == 9


# --- what the trainer wrote that the old tables had no column for -----------

# LADY KATHERINE, half-elf (race 4), levels 1-9. Her numbers, not the base
# table: race is in them, and nothing else is -- `GEN $1FEC` writes the level
# row and adds the racial row and reads no ability score at all.
MEASURED_THIEF_SKILLS = {
    1: (30, 25, 20, 20, 10, 10, 85, 5),
    2: (35, 29, 25, 26, 15, 10, 86, 5),
    3: (40, 33, 30, 32, 20, 15, 87, 5),
    4: (45, 37, 35, 38, 25, 15, 88, 25),
    5: (50, 42, 40, 45, 31, 20, 90, 30),
    6: (55, 47, 45, 52, 37, 20, 92, 35),
    7: (60, 52, 50, 60, 43, 25, 94, 40),
    8: (65, 57, 55, 67, 49, 25, 96, 45),
    9: (70, 62, 60, 75, 56, 30, 98, 50),
}
HALF_ELF = 4

# ROLAND, cleric 1-6: `0x0A4` at every training. It is not the level.
MEASURED_TURN_POWER = {1: 1, 2: 2, 3: 3, 4: 5, 5: 6, 6: 7}

# ROLAND again, wisdom 16: `0x0EE`-`0x0F0`, cleric in the high nibble.
# `3 / 4 / 4,3 / 5,4 / 5,5,1 / 5,5,2` is the class table plus +2 first-level
# and +2 second-level spells.
MEASURED_CLERIC_CAPACITY = {
    1: (3,), 2: (4,), 3: (4, 3), 4: (5, 4), 5: (5, 5, 1), 6: (5, 5, 2),
}
ROLAND_WISDOM = 16

# MALCYON, elf magic-user, constitution 18 -- and 2, not 4, because the
# fighter column of the constitution table is for fighters.
# Level 1 is the record as it arrived -- `hp_max` 4 with `hp_rolled` 4, which
# the arithmetic does not fit because the constitution 18 on his sheet is an
# edit the trainer had not yet been asked to reconcile. The first training put
# it right, so the rows start at 2.
MEASURED_MAGIC_USER_HP = {2: (7, 11), 3: (8, 14), 4: (10, 18),
                          5: (12, 22), 6: (16, 28)}
MALCYON_CONSTITUTION = 18


def test_the_thief_skills_match_the_trainer():
    for level, want in MEASURED_THIEF_SKILLS.items():
        assert levels.thief_skills(level, HALF_ELF) == want, level


def test_the_turning_level_matches_the_trainer():
    for level, want in MEASURED_TURN_POWER.items():
        assert levels.turning_level(level) == want, level


def test_the_cleric_spell_capacity_matches_the_trainer():
    bonus = levels.wisdom_bonus_spells(ROLAND_WISDOM)
    assert bonus == (2, 2, 0)
    for level, want in MEASURED_CLERIC_CAPACITY.items():
        row = levels.at_level("cleric", level).spells
        got = tuple(n + bonus[i] for i, n in enumerate(row))
        assert got == want, level


def test_hit_points_are_the_rolls_plus_the_constitution_bonus():
    """`hp_max = hp_rolled + level * bonus`, recomputed at every training."""
    bonus = levels.constitution_hp_bonus(MALCYON_CONSTITUTION, fighter=False)
    assert bonus == 2
    assert levels.constitution_hp_bonus(MALCYON_CONSTITUTION, fighter=True) == 4
    for level, (rolled, hp_max) in MEASURED_MAGIC_USER_HP.items():
        assert rolled + level * bonus == hp_max, level


def test_the_clamp_past_a_ceiling_has_a_number():
    """The game's threshold arrays run one entry past every ceiling, so the
    trainer clamps a thief 9 to 160,000 rather than to nothing."""
    for (class_name, level), want in PAST_THE_CEILING.items():
        assert levels.clamp_threshold(class_name, level) == want
