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

# `por/levels.py` says the fighter's breath save is 16 at level 4.  The game
# writes 15, on two independent characters -- SILAS 16 -> 15 and the dwarf
# MAGNUS 13 -> 12, at that level and no other.  Recorded rather than fixed
# because the table is another file; delete the entry when it is corrected.
KNOWN_DIVERGENCES = {("fighter", 4)}

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


def test_the_one_known_divergence_is_still_there():
    """Fails the day `por/levels.py` is corrected, which is the point."""
    for class_name, level in KNOWN_DIVERGENCES:
        table = _levels(class_name)
        assert tuple(table[level].saves) != MEASURED_SAVES[class_name][level]


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
