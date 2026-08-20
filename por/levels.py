"""Level progression: what each class needs, and what it gets.

The table is AD&D 1st edition as Pool of Radiance implements it, and the
implementation matters -- the game caps levels well below the rulebook (a
fighter stops at 8, a cleric at 6) because it was written to hand its party on
to *Curse of the Azure Bonds*.

**Checked against the game's own data, not merely transcribed** -- and the check
caught two errors in the source table, which is why it was worth doing. The
record stores base THAC0 at `0x071` as `60 - THAC0`, so every character we hold
votes on its own row.

* **Magic-user and thief level 1 are THAC0 21, not 20.** The published table
  said 20 for both; every specimen says 21, and 21 is what AD&D 1st edition
  gives (magic-users 1-5 and thieves 1-4 all need 21 to hit AC 0). Corrected
  here, and the levels the game confirms are marked below.
* **The saving-throw column is a *base* table and cannot be compared to a
  record.** Stored saves vary between characters of the same class and level --
  a level-1 fighter reads `(14,15,16,17,17)` in one specimen and
  `(11,12,13,14,14)` in another -- so the record carries modifiers on top,
  presumably racial and constitution-based. Those columns are transcribed, not
  verified, and nothing should assert them against a record until the modifiers
  are understood.

One loose end: two different level-4 fighters store THAC0 17 and 18. Unexplained.

Paladin, ranger and monk are here because the tables list them and Gold Box
Companion can create them, but **Pool of Radiance's own creation menu offers
none of the three** -- and the game displays all three as `MAGIC-USER`, because
class-name pointer entries 13, 14 and 15 all hold the same string address.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    """One row: what this level costs and what it confers."""

    level: int
    experience: int              # the threshold to reach it
    hit_dice: str
    hp_max: int
    thac0: int
    attacks: float               # 1.5 is AD&D's 3/2, stored doubled at 0x0D9
    saves: tuple[int, int, int, int, int]   # para, petrify, wand, breath, spell
    spells: tuple[int, ...] = ()            # slots per spell level, if any


CLERIC = (
    Level(1, 0, "1d8", 10, 20, 1, (10, 13, 14, 16, 15), (1,)),   # 20 confirmed
    Level(2, 1501, "2d8", 20, 20, 1, (10, 13, 14, 16, 15), (2,)),
    Level(3, 3001, "3d8", 30, 20, 1, (10, 13, 14, 16, 15), (2, 1)),
    Level(4, 6001, "4d8", 40, 18, 1, (9, 12, 13, 15, 14), (3, 2)),
    Level(5, 13001, "5d8", 50, 18, 1, (9, 12, 13, 15, 14), (3, 3, 1)),
    Level(6, 27501, "6d8", 60, 18, 1, (9, 12, 13, 15, 14), (3, 3, 2)),  # 18 confirmed
)

FIGHTER = (
    Level(1, 0, "1d10", 14, 20, 1, (14, 15, 16, 17, 17)),        # 20 confirmed
    Level(2, 2001, "2d10", 28, 19, 1, (14, 15, 16, 17, 17)),
    Level(3, 4001, "3d10", 42, 18, 1, (13, 14, 15, 16, 16)),
    Level(4, 8001, "4d10", 56, 17, 1, (13, 14, 15, 16, 16)),
    Level(5, 18001, "5d10", 70, 16, 1, (11, 12, 13, 13, 14)),
    Level(6, 35001, "6d10", 84, 15, 1, (11, 12, 13, 13, 14)),
    Level(7, 70001, "7d10", 98, 14, 1.5, (10, 11, 12, 12, 13)),  # 14 confirmed
    Level(8, 125001, "8d10", 112, 13, 1.5, (10, 11, 12, 12, 13)),  # 13 confirmed
)

MAGIC_USER = (
    Level(1, 0, "1d4", 6, 21, 1, (14, 13, 11, 15, 12), (1,)),      # 21 confirmed
    Level(2, 2501, "2d4", 12, 21, 1, (14, 13, 11, 15, 12), (2,)),
    Level(3, 5001, "3d4", 18, 21, 1, (14, 13, 11, 15, 12), (2, 1)),
    Level(4, 10001, "4d4", 24, 21, 1, (14, 13, 11, 15, 12), (3, 2)),
    Level(5, 22501, "5d4", 30, 21, 1, (14, 13, 11, 15, 12), (4, 2, 1)),
    Level(6, 40001, "6d4", 36, 19, 1, (13, 11, 9, 13, 10), (4, 2, 2)),  # 19 confirmed
)

THIEF = (
    Level(1, 0, "1d6", 6, 21, 1, (13, 12, 14, 16, 15)),            # 21 confirmed
    Level(2, 1251, "2d6", 12, 21, 1, (13, 12, 14, 16, 15)),
    Level(3, 2501, "3d6", 18, 21, 1, (13, 12, 14, 16, 15)),
    Level(4, 5001, "4d6", 24, 21, 1, (13, 12, 14, 16, 15)),
    Level(5, 10001, "5d6", 30, 18, 1, (12, 11, 12, 15, 13)),
    Level(6, 20001, "6d6", 36, 18, 1, (12, 11, 12, 15, 13)),
    Level(7, 42501, "7d6", 42, 18, 1, (12, 11, 12, 15, 13)),
    Level(8, 70001, "8d6", 48, 16, 1, (12, 11, 12, 15, 13)),
    Level(9, 110001, "9d6", 54, 16, 1, (11, 10, 10, 14, 11)),
)

TABLES = {
    "cleric": CLERIC,
    "fighter": FIGHTER,
    "magic-user": MAGIC_USER,
    "thief": THIEF,
}


def table(class_name: str) -> tuple[Level, ...]:
    return TABLES[class_name]


def at_level(class_name: str, level: int) -> Level | None:
    for row in TABLES.get(class_name, ()):
        if row.level == level:
            return row
    return None


def next_threshold(class_name: str, level: int) -> int | None:
    """Experience needed for the level after this one.

    None at the class's ceiling -- Pool of Radiance stops a fighter at 8 and a
    cleric at 6, so there genuinely is no next threshold, and an experience bar
    should say "maximum" rather than draw an empty one.
    """
    row = at_level(class_name, level + 1)
    return row.experience if row else None


def progress(class_name: str, level: int, experience: int) -> float | None:
    """How far through the current level, 0.0 to 1.0. None at the ceiling."""
    here = at_level(class_name, level)
    there = next_threshold(class_name, level)
    if here is None or there is None:
        return None
    span = there - here.experience
    if span <= 0:
        return None
    return max(0.0, min(1.0, (experience - here.experience) / span))
