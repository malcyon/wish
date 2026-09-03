"""Level progression: what each class needs, and what it gets.

Two titles, one shape. Pool of Radiance caps a fighter at 8 and a cleric at 6
because it was written to hand its party on to *Curse of the Azure Bonds*;
Curse raises every ceiling, adds paladin and ranger, and carries thirteen
experience rows where Pool of Radiance carries nine. Nothing about that is a
different *kind* of table, so this module is data per title -- the same choice
`goldbox/games.py` made -- and every entry point takes an optional `game`.

**Every number here is either read off the player's own disks or transcribed
from AD&D 1st edition and then checked against them.** The tables the game
carries, and where:

| table | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|
| experience | `GEN` `$1DB5`, parallel low/mid/high arrays, 9 wide | `GEN` `$136E`, 6 rows x 13 entries x 3 bytes **big-endian** | `GEN` `$162D`, 6 rows x 19 entries x 3 bytes big-endian, row stride `0x39` |
| class ceiling | `GEN` `$1E5C`, 8 bytes in class-bit order | `GEN` `$15A1`, same shape | `GEN` `$17D0`, same shape |
| racial class limit | `GEN` `$1E60`, 4 bytes a race | `GEN` `$15A9`, 8 bytes a race | `GEN` `$17E0`, 8 bytes a race, races 1-5 only ($178A refuses 6+) |
| THAC0 | `GEN` `$1F1F`, 4 rows x 9, `LDA $1F1F,X` with `X = class * 9 + level` | `GEN` `$0E2C`/`$0E39`/`$0E46`, 13 wide, indexed by level; the fighter group is arithmetic instead | `GEN` `$106F`/`$107F`/`$108F`, packed (not strided) rows of `ceiling + 1`; the fighter group is `21 - level` at `$1045`, the same rule as Curse |
| hit dice | -- (no class reaches the flat-hit-point rule) | `GEN` `$161E` die, `$1626` first flat level, `$162E` flat amount | `GEN` `$1845` die, `$184D` first flat level, `$1855` flat amount |
| spell slots | `GEN` `$222C` cleric then `$224C` magic-user, 8 rows x 4 | `ECL65` payload `0x88D`, magic-user 11 rows then cleric 10, x 5 | not read (trainer input, #89) |
| saving throws | `GEN` `$1FA2` level-1 row then two per-column bitmasks at `$1FB6` and `$1FCA` | level-1 rows only, `GEN` `$0F49` | `GEN` `$1148` level-1 rows, `$115C` a five-byte two-bit-a-level improvement mask a column, `$11C0` the paladin's -2 (code), `$11D8` the dwarf-only constitution bonus (code) |
| racial save bonus | `GEN` `$2359`, `CON * 2 / 7` for the races flagged at `$2380` | -- | `GEN` `$11D8`, same formula, dwarf (race 3) alone |
| thief skills | `GEN` `$102E`, 9 rows of 8, plus a racial row at `$1076` | -- | `GEN` `$126D`, 17 rows of 8; the level clamps to 17 at `$1213`. Read, not attributed -- see `thief_skills` below |
| hit die | `GEN` `$20A7`, 4 bytes in class-bit order | `GEN` `$161E` | `GEN` `$1845` |
| constitution hit-point bonus | `GEN` `$247B` fighter, `$2486` everyone else, indexed by the score | -- | `GEN` `$0E80`, indexed by the score; not read into this module (trainer input) |
| wisdom bonus spells | `GEN` `$10AD`, indexed by the score | -- | not read (#89) |
| turning level | `GEN` `$2399`, indexed by cleric level | -- | not read (#89) |

`GEN` is resident at `$0800` in all three games whatever its PRG header
claims.

**Not one Pool of Radiance address survives into Curse**, which is the
measurement `TRAINER_MEASURED` rests on. The two files were compared byte for
byte from `$0800` -- Pool of Radiance's 9083 bytes off `POOL3`, Curse's 9455
off `CURSE_A` -- and 8925 of the 9083 common bytes differ. Every address in the
table above and every one in `docs/135-levelling.md` holds something else in
Curse. Two of Pool of Radiance's tables were found elsewhere in Curse's file
and no others: the hit die 2697 bytes earlier at `$161E`, and the thief-skill
rows 42 bytes earlier at `$1004`. So selecting Curse's level tables is not
selecting Curse's trainer, and the rows this table still leaves at `--` --
racial save bonus, constitution hit-point bonus, wisdom bonus spells, turning
level -- are exactly the derivations a level-up needs.

**THAC0 is the game's, not a transcription**, and reading it caught an error
that had been in this file since it was written: **a thief is THAC0 19 at
levels 5-8 and 16 at 9, not 18/18/18/16/16.** The rows are
`LDA $1F1F,X` away from the instruction that uses them, they are AD&D 1st
edition exactly, and no specimen held a thief past level 4 to contradict the
old numbers. Magic-user and thief level 1 are 21, not the 20 the published
table this file came from gave -- that correction is older and is what the
record's own `60 - THAC0` at `0x071` first caught.

**Curse computes the fighter group's THAC0 rather than tabulating it**:
`LDA $7C98 / CLC / ADC #$27 / STA $7C71` is `THAC0 = 21 - fighting level`,
where `0x098` is the fighting level Curse fills and Pool of Radiance leaves at
zero. That reproduces Pool of Radiance's own fighter row and extends it, so a
level-12 fighter needs 9. It is also why a paladin and a ranger need no THAC0
table of their own.

**The saving-throw rule is the game's own, read out of `GEN`** -- `saving_throws`
below implements it:

> A character's five stored saves are the class-table row for its level, taking
> the best number in each column across every class it holds, less the AD&D
> constitution bonus when the character is a dwarf, gnome or halfling.

Pool of Radiance does not tabulate the rows. `GEN $1F44` fills all five columns
with 20, then for each class subtracts, per column, the number of set bits in
the low `level - 1` bits of *two* masks -- `$1FB6` and `$1FCA` -- from the
level-1 row at `$1FA2`, keeping whichever class gives the lower number. The
rows written out below are that encoding expanded, and
`tests/test_levels.py` re-expands it off the player's own `GEN` rather than
trusting the transcription. It is what settles **the fighter's level-4 breath
save at 15**: the fighter's fourth column carries mask `$0C` where the other
four carry `$08`, so that column improves twice by level 4 where the rest
improve once. AD&D 1st edition says 16 there; the game has always written 15.

78 of 79 distinct Pool of Radiance records satisfy that (`docs/127`), and every
Curse record on the player's disks does too. **The two games disagree on one
detail**, which is why the columns are a per-title field: Pool of Radiance
subtracts the bonus from all five columns, Curse from poison, wands and spells
only -- the three the *Players Handbook* actually names. MAGNUS, a dwarf
fighter with constitution 13, reads `11 12 13 14 14` in Pool of Radiance and
`11 15 13 17 14` in Curse, off the same character.

Curse's paladin saves are the fighter row less 2 and its ranger saves are the
fighter row unchanged, both AD&D and both confirmed against SSI's own
pre-generated party at level 5.

Monk is gone from this file. It was here because the published tables list it,
but no C64 title in the family implements one, and a table nothing can produce
is a trap rather than documentation. Pool of Radiance offers no paladin or
ranger either and displays all three as `MAGIC-USER`, because class-name
pointer entries 13, 14 and 15 hold one string address -- so those two rows live
under Curse, which does implement them.
"""

from __future__ import annotations

from dataclasses import dataclass

#: What the racial-limit tables write for "no limit".
UNLIMITED = 99

#: The one title whose trainer tables have been read byte for byte.
POOL_KEY = "pool-of-radiance"

#: The five columns, in stored order at record offset `0x09A`.
SAVE_COLUMNS = ("paralysis/poison/death", "petrification/polymorph",
                "rod/staff/wand", "breath weapon", "spell")


@dataclass(frozen=True)
class Level:
    """One row: what this level costs and what it confers."""

    level: int
    experience: int              # the threshold to reach it
    hit_dice: str                # "9d10+3" -- dice rolled, then the flat tail
    thac0: int
    attacks: float               # 1.5 is AD&D's 3/2, stored doubled at 0x0D9
    saves: tuple[int, int, int, int, int]   # para, petrify, wand, breath, spell
    spells: tuple[int, ...] = ()            # slots per spell level, if any

    @property
    def hp_max(self) -> int:
        """The most hit points the dice can give.

        Derived rather than stored. The column used to hold 10 a level for a
        cleric, 14 for a fighter and 6 for a magic-user and a thief, which
        matches no rule this project could name and which nothing checked; a
        number computed from `hit_dice` cannot drift away from it.
        """
        dice, _, die = self.hit_dice.partition("d")
        die, _, flat = die.partition("+")
        return int(dice) * int(die) + int(flat or 0)


# --- Pool of Radiance --------------------------------------------------------
# Written out row by row because each row carries its own provenance: `✓`
# marks a THAC0 the stored `60 - value` at `0x071` votes for directly.

CLERIC = (
    Level(1, 0, "1d8", 20, 1, (10, 13, 14, 16, 15), (1,)),   # 20 confirmed
    Level(2, 1501, "2d8", 20, 1, (10, 13, 14, 16, 15), (2,)),
    Level(3, 3001, "3d8", 20, 1, (10, 13, 14, 16, 15), (2, 1)),
    Level(4, 6001, "4d8", 18, 1, (9, 12, 13, 15, 14), (3, 2)),
    Level(5, 13001, "5d8", 18, 1, (9, 12, 13, 15, 14), (3, 3, 1)),
    Level(6, 27501, "6d8", 18, 1, (9, 12, 13, 15, 14), (3, 3, 2)),  # 18 confirmed
)

FIGHTER = (
    Level(1, 0, "1d10", 20, 1, (14, 15, 16, 17, 17)),        # 20 confirmed
    Level(2, 2001, "2d10", 19, 1, (14, 15, 16, 17, 17)),
    Level(3, 4001, "3d10", 18, 1, (13, 14, 15, 16, 16)),
    Level(4, 8001, "4d10", 17, 1, (13, 14, 15, 15, 16)),   # breath 15, not 16
    Level(5, 18001, "5d10", 16, 1, (11, 12, 13, 13, 14)),
    Level(6, 35001, "6d10", 15, 1, (11, 12, 13, 13, 14)),
    Level(7, 70001, "7d10", 14, 1.5, (10, 11, 12, 12, 13)),  # 14 confirmed
    Level(8, 125001, "8d10", 13, 1.5, (10, 11, 12, 12, 13)),  # 13 confirmed
)

MAGIC_USER = (
    Level(1, 0, "1d4", 21, 1, (14, 13, 11, 15, 12), (1,)),      # 21 confirmed
    Level(2, 2501, "2d4", 21, 1, (14, 13, 11, 15, 12), (2,)),
    Level(3, 5001, "3d4", 21, 1, (14, 13, 11, 15, 12), (2, 1)),
    Level(4, 10001, "4d4", 21, 1, (14, 13, 11, 15, 12), (3, 2)),
    Level(5, 22501, "5d4", 21, 1, (14, 13, 11, 15, 12), (4, 2, 1)),
    Level(6, 40001, "6d4", 19, 1, (13, 11, 9, 13, 10), (4, 2, 2)),  # 19 confirmed
)

# Levels 5-9 read 19/19/19/19/16 in the game's own table at $1F32, not the
# 18/18/18/16/16 this file used to carry. Nothing contradicted the old numbers
# because no specimen holds a thief past level 4.
THIEF = (
    Level(1, 0, "1d6", 21, 1, (13, 12, 14, 16, 15)),            # 21 confirmed
    Level(2, 1251, "2d6", 21, 1, (13, 12, 14, 16, 15)),
    Level(3, 2501, "3d6", 21, 1, (13, 12, 14, 16, 15)),
    Level(4, 5001, "4d6", 21, 1, (13, 12, 14, 16, 15)),
    Level(5, 10001, "5d6", 19, 1, (12, 11, 12, 15, 13)),
    Level(6, 20001, "6d6", 19, 1, (12, 11, 12, 15, 13)),
    Level(7, 42501, "7d6", 19, 1, (12, 11, 12, 15, 13)),
    Level(8, 70001, "8d6", 19, 1, (12, 11, 12, 15, 13)),
    Level(9, 110001, "9d6", 16, 1, (11, 10, 10, 14, 11)),
)

TABLES = {
    "cleric": CLERIC,
    "fighter": FIGHTER,
    "magic-user": MAGIC_USER,
    "thief": THIEF,
}


# --- Curse of the Azure Bonds ------------------------------------------------
# Built from bands rather than written out row by row, because a band *is* the
# AD&D table -- a thief is THAC0 19 for four levels running -- and sixty-six
# hand-typed rows are sixty-six chances to mistype one.


def _band(bands: tuple[tuple[int, object], ...], level: int):
    for top, value in bands:
        if level <= top:
            return value
    return bands[-1][1]


def _progression(*, ceiling, experience, thac0, saves, die, roll_to, flat,
                 attacks=((99, 1),), spells=()) -> tuple[Level, ...]:
    """One class's rows.

    `roll_to` is the last level that rolls a hit die; past it the class adds a
    flat `flat` hit points a level, which is the rule `GEN`'s `$1626`/`$162E`
    pair encodes and which Pool of Radiance stops short of ever needing.
    """
    rows = []
    for level in range(1, ceiling + 1):
        dice = min(level, roll_to)
        extra = (level - roll_to) * flat if level > roll_to else 0
        rows.append(Level(
            level=level,
            experience=experience[level - 1],
            hit_dice=f"{dice}d{die}" + (f"+{extra}" if extra else ""),
            thac0=_band(thac0, level),
            attacks=_band(attacks, level),
            saves=_band(saves, level),
            spells=spells[level - 1] if level <= len(spells) else (),
        ))
    return tuple(rows)


# AD&D 1st edition saving throws, by the last level of each band. Checked
# against the game where the game has a row: Curse keeps only the level-1 rows
# on disk (`GEN` `$0F49`, four classes of five bytes) and derives the rest.
_SAVES_MAGIC_USER = ((5, (14, 13, 11, 15, 12)), (10, (13, 11, 9, 13, 10)),
                     (15, (11, 9, 7, 11, 8)))
_SAVES_CLERIC = ((3, (10, 13, 14, 16, 15)), (6, (9, 12, 13, 15, 14)),
                 (9, (7, 10, 11, 13, 12)), (12, (6, 9, 10, 12, 11)))
_SAVES_THIEF = ((4, (13, 12, 14, 16, 15)), (8, (12, 11, 12, 15, 13)),
                (12, (11, 10, 10, 14, 11)))
_SAVES_FIGHTER = ((2, (14, 15, 16, 17, 17)), (4, (13, 14, 15, 16, 16)),
                  (6, (11, 12, 13, 13, 14)), (8, (10, 11, 12, 12, 13)),
                  (10, (8, 9, 10, 9, 11)), (12, (7, 8, 9, 8, 10)))
#: A paladin saves two better than a fighter at every level. SSI's own PALADIN,
#: level 5, stores `9 10 11 11 12` against the fighter row's `11 12 13 13 14`.
_SAVES_PALADIN = tuple((top, tuple(v - 2 for v in row))
                       for top, row in _SAVES_FIGHTER)
#: A ranger saves exactly as a fighter. SSI's RANGER, level 5, stores the
#: fighter row unchanged.
_SAVES_RANGER = _SAVES_FIGHTER

#: `$0E2C`, `$0E39`, `$0E46`, indexed by level. The fighter group is
#: `21 - fighting level`, computed at `$0E08`, so its band is written as one.
_THAC0_MAGIC_USER = ((5, 21), (10, 19), (15, 16))
_THAC0_CLERIC = ((3, 20), (6, 18), (9, 16), (12, 14))
_THAC0_THIEF = ((4, 21), (8, 19), (12, 16))
_THAC0_FIGHTER = tuple((level, 21 - level) for level in range(1, 13))

#: A fighter, paladin or ranger reaches two attacks in three rounds at 7.
_ATTACKS_FIGHTER = ((6, 1), (99, 1.5))

#: `ECL65` payload `0x88D`: eleven magic-user rows of five, then ten cleric
#: rows of five. Trailing zeroes are dropped so a row reads the way a character
#: sheet does.
_SLOTS_MAGIC_USER = ((1,), (2,), (2, 1), (3, 2), (4, 2, 1), (4, 2, 2),
                     (4, 3, 2, 1), (4, 3, 3, 2), (4, 3, 3, 2, 1),
                     (4, 4, 3, 2, 2), (4, 4, 4, 3, 3))
_SLOTS_CLERIC = ((1,), (2,), (2, 1), (3, 2), (3, 3, 1), (3, 3, 2),
                 (3, 3, 2, 1), (3, 3, 3, 2), (4, 4, 3, 2, 1), (4, 4, 3, 3, 2))

#: `GEN` `$136E`, measured. Every value is the AD&D 1st edition number plus one
#: -- 2001 to leave fighter 1 -- with two exceptions the disk is emphatic
#: about: the ranger's first threshold is a bare 2250, and the fighter's
#: eleventh reads 749937 where 750001 is expected. That is one bit (`$40`) in
#: the middle byte of `0B 71 B1`. Settled 2026-09-02: Silver Blades' `GEN
#: $162D`, a different file from a different release, carries the same
#: 749937 (`tests/test_coldread.py::
#: test_the_fighters_eleventh_threshold_is_the_same_on_a_second_rip`). It is
#: SSI's own number, not bit rot in one Curse rip.
_XP_MAGIC_USER = (0, 2501, 5001, 10001, 22501, 40001, 60001, 90001, 135001,
                  250001, 375001)
_XP_CLERIC = (0, 1501, 3001, 6001, 13001, 27501, 55001, 110001, 225001, 450001)
_XP_THIEF = (0, 1251, 2501, 5001, 10001, 20001, 42501, 70001, 110001, 160001,
             220001, 440001)
_XP_FIGHTER = (0, 2001, 4001, 8001, 18001, 35001, 70001, 125001, 250001,
               500001, 749937, 1000001)
_XP_PALADIN = (0, 2751, 5501, 12001, 24001, 45001, 95001, 175001, 350001,
               700001, 1050001)
_XP_RANGER = (0, 2250, 4501, 10001, 20001, 40001, 90001, 150001, 225001,
              325001, 650001)

CURSE_MAGIC_USER = _progression(
    ceiling=11, experience=_XP_MAGIC_USER, thac0=_THAC0_MAGIC_USER,
    saves=_SAVES_MAGIC_USER, die=4, roll_to=11, flat=1,
    spells=_SLOTS_MAGIC_USER)
CURSE_CLERIC = _progression(
    ceiling=10, experience=_XP_CLERIC, thac0=_THAC0_CLERIC,
    saves=_SAVES_CLERIC, die=8, roll_to=9, flat=2, spells=_SLOTS_CLERIC)
CURSE_THIEF = _progression(
    ceiling=12, experience=_XP_THIEF, thac0=_THAC0_THIEF,
    saves=_SAVES_THIEF, die=6, roll_to=10, flat=2)
CURSE_FIGHTER = _progression(
    ceiling=12, experience=_XP_FIGHTER, thac0=_THAC0_FIGHTER,
    saves=_SAVES_FIGHTER, die=10, roll_to=9, flat=3, attacks=_ATTACKS_FIGHTER)
# No spell table has been found for either. Curse does carry the ranger's
# druid list -- spell ids 77-80 -- so the slots exist somewhere; they are not
# in `ECL65` beside the other two, and an empty tuple is the honest answer.
CURSE_PALADIN = _progression(
    ceiling=11, experience=_XP_PALADIN, thac0=_THAC0_FIGHTER,
    saves=_SAVES_PALADIN, die=10, roll_to=9, flat=3, attacks=_ATTACKS_FIGHTER)
CURSE_RANGER = _progression(
    ceiling=11, experience=_XP_RANGER, thac0=_THAC0_FIGHTER,
    saves=_SAVES_RANGER, die=8, roll_to=10, flat=2, attacks=_ATTACKS_FIGHTER)


# --- Secret of the Silver Blades ----------------------------------------------
# GEN $162D / $17D0 / $17E0 / $106F-$108F / $1045 / $13EF-$13F7 / $1845-$1855 /
# $1148-$115C / $11C0 / $11D8, all at base $0800, read by tests/test_coldread.py.
#
# The experience rows are Curse's, carried on: all 61 thresholds the two
# titles share are identical, including the fighter's anomalous 749937 at
# level 11 (see `_XP_FIGHTER` above). The saving-throw *encoding* is not
# Curse's -- Curse keeps only level-1 rows and this file transcribes the
# rest, where Silver Blades unpacks a two-bit improvement a level out of
# `$115C` -- but the *rows* it produces are the same AD&D bands extended, and
# the constitution bonus goes to the dwarf alone (race 3) on columns 0, 2 and
# 4 rather than to all five columns for three races the way Pool of Radiance
# does it.
_XP_MAGIC_USER_SSB = _XP_MAGIC_USER + (750001, 1125001, 1500001, 1875001)
_XP_CLERIC_SSB = _XP_CLERIC + (675001, 900001, 1125001, 1350001, 1575001)
_XP_THIEF_SSB = _XP_THIEF + (660001, 880001, 1100001, 1320001, 1540001,
                             1760001)
_XP_FIGHTER_SSB = _XP_FIGHTER + (1250001, 1500001, 1750001)
_XP_PALADIN_SSB = _XP_PALADIN + (1400001, 1750001, 2100001, 2450001)
_XP_RANGER_SSB = _XP_RANGER + (975001, 1300001, 1625001, 1950001)

_SAVES_CLERIC_SSB = _SAVES_CLERIC + ((15, (5, 8, 9, 11, 10)),)
_SAVES_THIEF_SSB = _SAVES_THIEF + ((16, (10, 9, 8, 13, 9)),
                                   (18, (9, 8, 6, 12, 7)))
_SAVES_FIGHTER_SSB = _SAVES_FIGHTER + ((14, (5, 6, 7, 5, 8)),
                                       (15, (4, 5, 6, 4, 7)))
#: `$11C0` is code (`LDA $7CCF / BEQ / LDX #$04 ...`): 2 off every column.
#: GUY DE VALOIS, paladin 8, stores `8 9 10 10 11` against the fighter row's
#: `10 11 12 12 13`.
_SAVES_PALADIN_SSB = tuple((top, tuple(v - 2 for v in row))
                           for top, row in _SAVES_FIGHTER_SSB)

_THAC0_CLERIC_SSB = _THAC0_CLERIC + ((15, 12),)
_THAC0_THIEF_SSB = _THAC0_THIEF + ((16, 14), (18, 12))
#: `$1045`, `21 - fighting level`, the same rule as Curse's fighter group.
_THAC0_FIGHTER_SSB = tuple((level, 21 - level) for level in range(1, 16))

#: `$13EF`/`$13F7`: level >= n, not level > n -- MALACHITE at exactly
#: fighter 7 stores 3 (3/2, doubled) at `0x0D9`, so the band tops are `n - 1`.
_ATTACKS_FIGHTER_SSB = ((6, 1), (12, 1.5), (99, 2))
_ATTACKS_RANGER_SSB = ((7, 1), (14, 1.5), (99, 2))

SSB_MAGIC_USER = _progression(
    ceiling=15, experience=_XP_MAGIC_USER_SSB, thac0=_THAC0_MAGIC_USER,
    saves=_SAVES_MAGIC_USER, die=4, roll_to=11, flat=1)
SSB_CLERIC = _progression(
    ceiling=15, experience=_XP_CLERIC_SSB, thac0=_THAC0_CLERIC_SSB,
    saves=_SAVES_CLERIC_SSB, die=8, roll_to=9, flat=2)
SSB_THIEF = _progression(
    ceiling=18, experience=_XP_THIEF_SSB, thac0=_THAC0_THIEF_SSB,
    saves=_SAVES_THIEF_SSB, die=6, roll_to=10, flat=2)
SSB_FIGHTER = _progression(
    ceiling=15, experience=_XP_FIGHTER_SSB, thac0=_THAC0_FIGHTER_SSB,
    saves=_SAVES_FIGHTER_SSB, die=10, roll_to=9, flat=3,
    attacks=_ATTACKS_FIGHTER_SSB)
SSB_PALADIN = _progression(
    ceiling=15, experience=_XP_PALADIN_SSB, thac0=_THAC0_FIGHTER_SSB,
    saves=_SAVES_PALADIN_SSB, die=10, roll_to=9, flat=3,
    attacks=_ATTACKS_FIGHTER_SSB)
SSB_RANGER = _progression(
    ceiling=15, experience=_XP_RANGER_SSB, thac0=_THAC0_FIGHTER_SSB,
    saves=_SAVES_FIGHTER_SSB, die=8, roll_to=10, flat=2,
    attacks=_ATTACKS_RANGER_SSB)


# --- what the trainer rolls and looks up --------------------------------------
# Everything below is Pool of Radiance's `GEN`, read byte for byte, and is what
# lets `goldbox/levelup.py` reproduce a training without one. Curse has its own
# copies of all of it and none of them has been read, which is why these are
# fields on the per-title descriptor with an empty default rather than module
# constants that would answer for a title nobody measured.

#: `GEN $102E`, nine rows of eight, indexed by `thief level - 1`. The columns
#: are the stored order at `0x0A5`: pick pockets, open locks, find traps, move
#: silently, hide in shadows, hear noise, climb walls, read languages.
_THIEF_SKILLS_POOL = (
    (30, 25, 20, 15, 10, 10, 85, 0),
    (35, 29, 25, 21, 15, 10, 86, 0),
    (40, 33, 30, 27, 20, 15, 87, 0),
    (45, 37, 35, 33, 25, 15, 88, 20),
    (50, 42, 40, 40, 31, 20, 90, 25),
    (55, 47, 45, 47, 37, 20, 92, 30),
    (60, 52, 50, 55, 43, 25, 94, 35),
    (65, 57, 55, 62, 49, 25, 96, 40),
    (70, 62, 60, 70, 56, 30, 98, 45),
)

#: `GEN $1076`, eight rows of eight, indexed by `race - 1` and added to the row
#: above. **Race is the whole of the adjustment**: `GEN $1FEC` writes the level
#: row and then adds this one, and nothing reads dexterity. LADY KATHERINE's
#: measured ladder (`docs/119-test-party.md`) is the half-elf row exactly.
_THIEF_SKILL_RACE_POOL = (
    (0, 10, 15, 0, 0, 0, -10, -5),      # dwarf
    (5, -5, 0, 5, 10, 5, 0, 0),         # elf
    (0, 5, 10, 5, 5, -5, 0, 10),        # gnome
    (0, 0, 0, 5, 0, 0, 0, 5),           # half-elf
    (5, 5, 10, 15, 5, -15, -5, -5),     # halfling
    (5, 5, 0, 0, 5, 5, -10, 0),         # half-orc
    (0, 0, 0, 0, 0, 0, 0, 0),           # human
    (0, 0, 0, 0, 0, 0, 0, 0),           # monster
)

#: `GEN $2399`, indexed by cleric level, written to `0x0A4`. Not the level: it
#: is the row of the AD&D turning table the cleric reads, which is why it runs
#: `1 2 3 5 6 7` and skips 4. ROLAND's six trainings wrote exactly this.
_TURN_POWER_POOL = (1, 2, 3, 5, 6, 7, 8, 9, 10, 10, 10, 10, 10, 12)

#: `GEN $20A7`, in class-bit order: how many sides the hit die has.
_HIT_DIE_POOL = {"magic-user": 4, "cleric": 8, "thief": 6, "fighter": 10}

#: `GEN $247B` and `$2486`, indexed by the constitution score and consulted
#: only from 15 up (`CPX #$0F`). A character with any fighter bit takes the
#: first row; everybody else the second, which is why an 18-constitution
#: magic-user gets 2 and not 4.
_HP_BONUS_FIGHTER = (1, 2, 3, 4, 5, 5, 6, 6, 6, 7, 7)      # CON 15-25
_HP_BONUS_OTHER = (1, 2, 2, 2, 3, 3, 4, 4, 4, 5, 5)        # CON 15-25
HP_BONUS_FROM = 15


def hit_die(class_name: str, game=None) -> int | None:
    """How many sides the class rolls a level, or None for no such class."""
    tables = for_game(game)
    if tables.key == POOL_KEY:
        return _HIT_DIE_POOL.get(class_name)
    row = tables.at_level(class_name, 1)
    if row is None:
        return None
    _, _, die = row.hit_dice.partition("d")
    die, _, _flat = die.partition("+")
    return int(die)


def constitution_hp_bonus(constitution: int, fighter: bool = False) -> int:
    """Hit points a level from constitution. `GEN $2471`.

    **Pool of Radiance's, and taken to answer for Curse** until somebody reads
    Curse's copy: it is the AD&D 1st edition table unchanged, including the cap
    of +2 for anybody who is not a fighter.
    """
    score = int(constitution or 0)
    if score < HP_BONUS_FROM:
        return 0
    row = _HP_BONUS_FIGHTER if fighter else _HP_BONUS_OTHER
    return row[min(score - HP_BONUS_FROM, len(row) - 1)]


#: `GEN $10AD`, indexed by the wisdom score. One number, which `GEN $2108`
#: then halves its way down for the second and third spell levels.
_WISDOM_BONUS_BASE = 12


def wisdom_bonus_spells(wisdom: int) -> tuple[int, int, int]:
    """Bonus cleric spells at the first three spell levels. `GEN $2108`.

    **The game's table starts one point low.** AD&D 1st edition gives the first
    bonus spell at wisdom 13 and the second at 14; `$10AD` holds 1 at 12 and 2
    from 13 up, so a wisdom-12 cleric memorises a first-level spell the rules
    do not give it. The second- and third-level columns are AD&D exactly --
    they are gated on `CPY #$0F`, `#$10` and `#$11`. See `docs/125-bug-notes.md`.

    The bonus is only granted where the class table already gives a slot at
    that spell level (`GEN $210A` skips a zero), so a level-1 cleric gets no
    second-level spell however wise it is.
    """
    score = int(wisdom or 0)
    if score < _WISDOM_BONUS_BASE:
        return (0, 0, 0)
    base = 1 if score == _WISDOM_BONUS_BASE else 2
    second = 0 if score < 15 else (base >> 1 if score < 16 else base)
    third = 0
    if score >= 15:
        third = base >> 1 if score < 16 else base
        third >>= 1
        if score < 17:
            third >>= 1
    return (base, second, third)


# --- the per-title descriptor ------------------------------------------------

@dataclass(frozen=True)
class LevelTables:
    """One title's progression, as data.

    Pairs rather than dicts so the descriptor stays hashable and frozen, which
    is the shape `goldbox/games.py` settled on for the same reason.

    `class_order` is **class-bit order** -- index `n` is bit `n` of
    `class_bits` at `0x0EB` and slot `n` of the per-class level array at
    `0x0C9` -- so it is the index the game's own tables use, and `None` marks a
    bit this title has no class for. `racial_limits` rows are in that order.
    """

    key: str
    title: str
    class_order: tuple[str | None, ...]
    classes: tuple[tuple[str, tuple[Level, ...]], ...]
    ceilings: tuple[tuple[str, int], ...]
    racial_limits: tuple[tuple[int, tuple[int, ...]], ...]
    #: Which of the five save columns the racial constitution bonus reaches.
    constitution_save_columns: tuple[int, ...]
    #: Race codes that take it at all. The default, `(1, 3, 5)`, is Pool of
    #: Radiance's dwarf, gnome and halfling; Silver Blades overrides it to the
    #: dwarf alone (`(3,)` -- race 3 there, not the gnome it is in Pool of
    #: Radiance). Derivable from `games.Game.races` and would live better
    #: there; it is here because nothing else needs it yet and this module
    #: does not import that one.
    sturdy_races: tuple[int, ...] = (1, 3, 5)
    #: The trainer's own tables, read out of the title's `GEN`. Empty means
    #: nobody has read this title's copy, and every caller treats that as
    #: "cannot answer" rather than as a zero.
    thief_skills: tuple[tuple[int, ...], ...] = ()
    thief_skill_race: tuple[tuple[int, ...], ...] = ()
    turn_power: tuple[int, ...] = ()
    #: What the trainer clamps experience to at the class ceiling. The game's
    #: threshold arrays are nine wide a class and each class's tenth entry
    #: falls in the next class's unused slot 0, so `GEN $23D4` reads a real
    #: number one past every ceiling: 60,001 for a magic-user 6, 55,001 for a
    #: cleric 6, 160,001 for a thief 9 and 250,001 for a fighter 8. Kept apart
    #: from the rows because `next_threshold` must stay None at the ceiling --
    #: an experience bar there has nothing to fill towards.
    clamp_thresholds: tuple[tuple[str, int], ...] = ()

    def thief_skill_row(self, level: int, race: int) -> tuple[int, ...] | None:
        """The eight percentages a thief of that level and race stores.

        The level row plus the racial row, which is the whole rule: `GEN $1FEC`
        writes one and adds the other and reads nothing else.
        """
        if not self.thief_skills:
            return None
        level = max(1, min(int(level or 1), len(self.thief_skills)))
        row = self.thief_skills[level - 1]
        index = int(race or 0) - 1
        if 0 <= index < len(self.thief_skill_race):
            row = tuple(a + b for a, b in
                        zip(row, self.thief_skill_race[index]))
        return tuple(row)

    def clamp_threshold(self, class_name: str, level: int) -> int | None:
        """What `GEN $23D4` reads for a class at that level, ceiling included."""
        want = self.at_level(class_name, level + 1)
        if want is not None:
            return want.experience
        if level == self.ceiling(class_name):
            return dict(self.clamp_thresholds).get(class_name)
        return None

    def turning_level(self, cleric_level: int) -> int | None:
        """What `0x0A4` holds for a cleric of that level, or None."""
        if not self.turn_power or not cleric_level:
            return None
        level = max(1, min(int(cleric_level), len(self.turn_power)))
        return self.turn_power[level - 1]

    @property
    def tables(self) -> dict[str, tuple[Level, ...]]:
        return dict(self.classes)

    @property
    def class_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.classes)

    def table(self, class_name: str) -> tuple[Level, ...]:
        return self.tables[class_name]

    def at_level(self, class_name: str, level: int) -> Level | None:
        for row in self.tables.get(class_name, ()):
            if row.level == level:
                return row
        return None

    def ceiling(self, class_name: str) -> int | None:
        """The last level this title lets the class reach, or None if unknown."""
        return dict(self.ceilings).get(class_name)

    def racial_limit(self, race: int, class_name: str) -> int | None:
        """How far a race of that class may go. `UNLIMITED` is 99.

        None means the title says nothing -- race 7 and above skip the check in
        both games, and so does a class this title does not implement. Zero
        means the race may not take the class at all.
        """
        row = dict(self.racial_limits).get(race)
        if row is None or class_name not in self.class_order:
            return None
        index = self.class_order.index(class_name)
        return row[index] if index < len(row) else None

    def saving_throws(self, class_levels, race: int = 0,
                      constitution: int = 0) -> tuple[int, ...] | None:
        """The five saves a record should store, or None for no known class.

        `class_levels` maps a class name to its level -- the per-class array at
        `0x0C9`, not the single level byte at `0x0A0`, because a multi-class
        character takes the best column from each of its classes.
        """
        rows = [row.saves for row in
                (self.at_level(name, max(int(level), 1))
                 for name, level in dict(class_levels).items())
                if row is not None]
        if not rows:
            return None
        best = [min(row[column] for row in rows) for column in range(5)]
        if race in self.sturdy_races:
            bonus = constitution_save_bonus(constitution)
            for column in self.constitution_save_columns:
                best[column] -= bonus
        return tuple(best)


#: Pool of Radiance offers four classes and no paladin or ranger, so bits 6 and
#: 7 name nothing. Its racial rows are four bytes wide, which is why they stop
#: at fighter.
POOL_OF_RADIANCE = LevelTables(
    key="pool-of-radiance",
    title="Pool of Radiance",
    class_order=("magic-user", "cleric", "thief", "fighter",
                 None, None, None, None),
    classes=(("magic-user", MAGIC_USER), ("cleric", CLERIC),
             ("thief", THIEF), ("fighter", FIGHTER)),
    ceilings=(("magic-user", 6), ("cleric", 6), ("thief", 9), ("fighter", 8)),
    racial_limits=((1, (0, 8, UNLIMITED, 9)), (2, (11, 7, UNLIMITED, 7)),
                   (3, (0, 7, UNLIMITED, 6)), (4, (8, 5, UNLIMITED, 8)),
                   (5, (0, 0, UNLIMITED, 6)), (6, (0, 4, 8, 10)),
                   (7, (UNLIMITED,) * 4)),
    constitution_save_columns=(0, 1, 2, 3, 4),
    thief_skills=_THIEF_SKILLS_POOL,
    thief_skill_race=_THIEF_SKILL_RACE_POOL,
    turn_power=_TURN_POWER_POOL,
    clamp_thresholds=(("magic-user", 60001), ("cleric", 55001),
                      ("thief", 160001), ("fighter", 250001)),
)

#: Curse zeroes the cleric column for dwarf, elf and gnome where Pool of
#: Radiance carried 8, 7 and 7 -- those three are the *Dungeon Master's Guide*
#: NPC limits and the *Players Handbook* has no such player clerics, so Curse
#: is the stricter reading of the same rule rather than a different one.
CURSE_OF_THE_AZURE_BONDS = LevelTables(
    key="curse-of-the-azure-bonds",
    title="Curse of the Azure Bonds",
    class_order=("magic-user", "cleric", "thief", "fighter",
                 None, None, "paladin", "ranger"),
    classes=(("magic-user", CURSE_MAGIC_USER), ("cleric", CURSE_CLERIC),
             ("thief", CURSE_THIEF), ("fighter", CURSE_FIGHTER),
             ("paladin", CURSE_PALADIN), ("ranger", CURSE_RANGER)),
    ceilings=(("magic-user", 11), ("cleric", 10), ("thief", 12),
              ("fighter", 12), ("paladin", 11), ("ranger", 11)),
    racial_limits=(
        (1, (0, 0, UNLIMITED, 9, 0, 0, 0, 0)),
        (2, (11, 0, UNLIMITED, 7, 0, 0, 0, 0)),
        (3, (0, 0, UNLIMITED, 6, 0, 0, 0, 0)),
        (4, (8, 5, UNLIMITED, 8, 0, 0, 0, 8)),
        (5, (0, 0, UNLIMITED, 6, 0, 0, 0, 0)),
        (6, (0, 4, 8, 10, 0, 0, 0, 0)),
        (7, (UNLIMITED, UNLIMITED, UNLIMITED, UNLIMITED, 0, 0,
             UNLIMITED, UNLIMITED)),
    ),
    constitution_save_columns=(0, 2, 4),
)

#: Race 3 is the dwarf in this title (`games.RACES_SILVER_BLADES`), not the
#: gnome it is in Pool of Radiance. Row 6, the human, is not on disk -- `$178A`
#: refuses to look one up for race 6 or above, which is "no limit" -- and is
#: synthesised the same way Curse's row 7 is.
SECRET_OF_THE_SILVER_BLADES = LevelTables(
    key="secret-of-the-silver-blades",
    title="Secret of the Silver Blades",
    class_order=("magic-user", "cleric", "thief", "fighter",
                 None, None, "paladin", "ranger"),
    classes=(("magic-user", SSB_MAGIC_USER), ("cleric", SSB_CLERIC),
             ("thief", SSB_THIEF), ("fighter", SSB_FIGHTER),
             ("paladin", SSB_PALADIN), ("ranger", SSB_RANGER)),
    ceilings=(("magic-user", 15), ("cleric", 15), ("thief", 18),
              ("fighter", 15), ("paladin", 15), ("ranger", 15)),
    racial_limits=(
        (1, (11, 0, UNLIMITED, 7, 0, 0, 0, 0)),      # elf
        (2, (8, 5, UNLIMITED, 8, 0, 0, 0, 8)),       # half-elf
        (3, (0, 0, UNLIMITED, 9, 0, 0, 0, 0)),       # dwarf
        (4, (0, 0, UNLIMITED, 6, 0, 0, 0, 0)),       # gnome
        (5, (0, 0, UNLIMITED, 6, 0, 0, 0, 0)),       # halfling
        (6, (UNLIMITED, UNLIMITED, UNLIMITED, UNLIMITED, 0, 0,
             UNLIMITED, UNLIMITED)),                  # human -- synthesised
    ),
    constitution_save_columns=(0, 2, 4),
    sturdy_races=(3,),          # the dwarf alone, and 3 is the dwarf here
)

TITLES: tuple[LevelTables, ...] = (POOL_OF_RADIANCE, CURSE_OF_THE_AZURE_BONDS,
                                   SECRET_OF_THE_SILVER_BLADES)
BY_KEY = {t.key: t for t in TITLES}

#: What a caller gets when it says nothing. Every caller predates the second
#: game and means this one.
DEFAULT = POOL_OF_RADIANCE

#: The titles whose **trainer** has been read. A stricter claim than having a
#: table, and the distinction is the whole of issue #16: Curse's level tables
#: are in this module, and they are still not enough to level a Curse
#: character. Everything around them was read at Pool of Radiance's addresses
#: out of Pool of Radiance's `GEN` -- the hit-die roll at `$2037`, the
#: saving-throw masks at `$1F44`, the constitution tables at `$247B`/`$2486`,
#: the spell capacity at `$20BC` -- and nothing has confirmed Curse's `GEN`
#: agrees. Measuring it is what would move a key into this set.
#:
#: Silver Blades is the same case: its level tables are in this module now
#: (#187), and its trainer's own inputs -- the constitution hit-point bonus,
#: thief-skill racial adjustment, wisdom bonus spells, turning table -- are
#: either unread or unattributed (`docs/121-silver-blades.md`). Reading them
#: is what would move it into this set; nothing here does that.
#:
#: `for_game` deliberately falls back to Pool of Radiance for a title it has no
#: tables for, which is right for reading a spell name and wrong for writing a
#: character record. A writer asks this instead.
TRAINER_MEASURED: frozenset[str] = frozenset({POOL_OF_RADIANCE.key})


def trainer_measured(game=None) -> bool:
    """Has this title's trainer been measured? None means the default title."""
    if game is None:
        return DEFAULT.key in TRAINER_MEASURED
    key = game.key if isinstance(game, LevelTables) else getattr(game, "key",
                                                                 game)
    return key in TRAINER_MEASURED


def for_game(game=None) -> LevelTables:
    """The tables for a title.

    Takes a `goldbox.games.Game`, a game key, a `LevelTables`, or None. Deliberately
    duck-typed on `.key` rather than importing `goldbox.games`: this module needs
    one string from that one, and a title it has no tables for falls back to
    Pool of Radiance rather than raising, because every geometry-only title in
    `goldbox/games.py` runs an engine whose progression has not been read.
    """
    if isinstance(game, LevelTables):
        return game
    key = getattr(game, "key", game)
    return BY_KEY.get(key, DEFAULT)


def constitution_save_bonus(constitution: int) -> int:
    """+1 saving throw per 3.5 points of constitution. `GEN $2359`.

    Not a band table and not a transcription: the game divides `constitution *
    2` by 7 and subtracts the quotient, which is this expression exactly. Only
    the races flagged at `GEN $2380` -- dwarf, gnome and halfling -- take it.
    MAGNUS, a dwarf with constitution 13, reads three lower than the human
    SILAS on all five columns at every level, and `26 // 7` is 3.
    """
    return int(constitution or 0) * 2 // 7


def table(class_name: str, game=None) -> tuple[Level, ...]:
    return for_game(game).table(class_name)


def at_level(class_name: str, level: int, game=None) -> Level | None:
    return for_game(game).at_level(class_name, level)


def ceiling(class_name: str, game=None) -> int | None:
    return for_game(game).ceiling(class_name)


def racial_limit(race: int, class_name: str, game=None) -> int | None:
    return for_game(game).racial_limit(race, class_name)


def saving_throws(class_levels, race: int = 0, constitution: int = 0,
                  game=None) -> tuple[int, ...] | None:
    return for_game(game).saving_throws(class_levels, race, constitution)


def thief_skills(level: int, race: int, game=None) -> tuple[int, ...] | None:
    return for_game(game).thief_skill_row(level, race)


def turning_level(cleric_level: int, game=None) -> int | None:
    return for_game(game).turning_level(cleric_level)


def clamp_threshold(class_name: str, level: int, game=None) -> int | None:
    return for_game(game).clamp_threshold(class_name, level)


def next_threshold(class_name: str, level: int, game=None) -> int | None:
    """Experience needed for the level after this one.

    None at the class's ceiling -- Pool of Radiance stops a fighter at 8 and a
    cleric at 6, so there genuinely is no next threshold, and an experience bar
    should say "maximum" rather than draw an empty one.
    """
    row = at_level(class_name, level + 1, game)
    return row.experience if row else None


def progress(class_name: str, level: int, experience: int,
             game=None) -> float | None:
    """How far through the current level, 0.0 to 1.0. None at the ceiling."""
    here = at_level(class_name, level, game)
    there = next_threshold(class_name, level, game)
    if here is None or there is None:
        return None
    span = there - here.experience
    if span <= 0:
        return None
    return max(0.0, min(1.0, (experience - here.experience) / span))
