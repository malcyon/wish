"""Level progression: what each class needs, and what it gets.

Two titles, one shape. Pool of Radiance caps a fighter at 8 and a cleric at 6
because it was written to hand its party on to *Curse of the Azure Bonds*;
Curse raises every ceiling, adds paladin and ranger, and carries thirteen
experience rows where Pool of Radiance carries nine. Nothing about that is a
different *kind* of table, so this module is data per title -- the same choice
`goldbox/c64_port.py` made -- and every entry point takes an optional `game`.

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
| spell slots | `GEN` `$222C` cleric then `$224C` magic-user, 8 rows x 4 | `ECL65` `$888D` magic-user 11 rows then `$88C4` cleric 10, x 5 -- that overlay runs at `$8000`, so those are payload `0x88D` and `0x8C4` | not read (trainer input, #89) |
| saving throws | `GEN` `$1FA2` level-1 row then two per-column bitmasks at `$1FB6` and `$1FCA` | `GEN` `$0F49` level-1 rows, `$0F5D` a four-byte two-bit-a-level improvement mask a column, `$0F01` the paladin's -2 (code) | `GEN` `$1148` level-1 rows, `$115C` a five-byte two-bit-a-level improvement mask a column, `$11C0` the paladin's -2 (code), `$11D8` the dwarf-only constitution bonus (code) |
| racial save bonus | `GEN` `$2359`, `CON * 2 / 7` for the races flagged at `$2380` | `GEN` `$0F19`, same formula, races 1, 3 and 5 (`CMP #$06` then `AND #$01`), columns 0, 2 and 4 only (`DEX / DEX`) | `GEN` `$11D8`, same formula, dwarf (race 3) alone |
| thief skills | `GEN` `$102E`, 9 rows of 8, plus a racial row at `$1076` | `GEN` `$1004`, 9 rows of 8, plus **a dexterity row at `$10A4`** (17 rows, `max(0, DEX - 9)`) and a racial row at `$1064` whose gnome, half-elf, halfling and half-orc rows are not Pool of Radiance's | `GEN` `$126D`, 17 rows of 8, the level clamps to 17 at `$1213`; a dexterity row at `$131D`, Curse's own 136 bytes; a racial row at `$12F5` read at `race * 8` with **no decrement** (`$124D`), so every race reads the row laid out for the *next* one -- `goldbox-bugs.md` entry 13 |
| hit die | `GEN` `$20A7`, 4 bytes in class-bit order | `GEN` `$161E` | `GEN` `$1845` |
| constitution hit-point bonus | `GEN` `$247B` fighter, `$2486` everyone else, indexed by the score, consulted from 15 | `GEN` `$11D7`, **one** row indexed by the score with no floor, signed; `$126D` caps a non-fighter's *score* at 16 instead of keeping a second row | `GEN` `$0E80`, the same 26 bytes as Curse's `$11D7`; `$0E6F`/`$0E73` cap the score at 16 below class slot 3 the same way |
| wisdom bonus spells | `GEN` `$10AD`, indexed by the score | `ECL65` `$8906` (payload `0x906`), the spell level each point of wisdom from 13 up buys; the loop is `$88F6` | `ECL65` `$89F0` (payload `0x9F0`), Curse's `$8906` seven bytes exactly; the loop is `$89E0` |
| turning level | `GEN` `$2399`, indexed by cleric level | `GEN` `$113F`, arithmetic rather than a table: `max(cleric, paladin - 2)`, `+ 1` from 4 up, capped at 10 -- the same ten numbers | `GEN` `$13A5`, Curse's arithmetic with a tail: `+ 1` from 4 up, 10 from 10 to 14, and **12** from 15 -- which is Pool of Radiance's fourteen numbers exactly |

`GEN` is resident at `$0800` in all three games whatever its PRG header
claims.

**Pools of Darkness has an entry too, read off its DOS `GAME.OVR` rather than
a `GEN`**, because it never shipped on the C64. `POOLS_OF_DARKNESS` says which
of its tables are read, where, and what every lookup answers for the ones
that are not.

**One of those tables is not the same on the DOS side.** Everything above is
the C64's, and for every table but one the DOS build agrees. The exception is
THAC0, and the three titles do not disagree with the C64 in the same way.
Pool of Radiance's DOS build ships 40 -- THAC0 20 -- where the C64's `$1F1F`
ships 39, in the magic-user's rows 1-5 and the thief's rows 1-4, so a
low-level DOS caster or thief hits one point better than the same character
on the C64. Curse and Silver Blades ship the C64's own 39 for a low-level
magic-user and instead disagree on the thief's low levels, a level-2
fighter/paladin/ranger and the magic-user's third band -- see
`_DOS_THAC0_POOL` for both halves' provenance. `dos_thac0` carries all three
titles' tables now.

**Not one Pool of Radiance address survives into Curse**, which is the
measurement `TRAINER_MEASURED` rests on. The two files were compared byte for
byte from `$0800` -- Pool of Radiance's 9083 bytes off `POOL3`, Curse's 9455
off `CURSE_A` -- and 8925 of the 9083 common bytes differ. Every address in the
table above and every one in `docs/135-levelling.md` holds something else in
Curse. Two of Pool of Radiance's tables were found elsewhere in Curse's file
and no others: the hit die 2697 bytes earlier at `$161E`, and the thief-skill
rows 42 bytes earlier at `$1004`. So selecting Curse's level tables is not
selecting Curse's trainer.

**Curse's column of that table is now filled in, and the four gaps it used to
leave at `--` are what `tests/curse_of_the_azure_bonds/test_cursetrainer.py` reads off the disk**
(`#18`). Finding them needed no emulator and no address from this file: Curse's
working character sits at `$7C00`, so a census of every absolute instruction
whose operand lands in the record puts each routine within two instructions of
the table it reads, which is what `tools/c64/trainerscan.py` prints. **Locating
them is not the same as being able to write a Curse record**, and four of the
readings are a different *rule* rather than the same rule at a new address:

* **the hit die is rolled twice and the better roll kept** (`$15FC`), where
  Pool of Radiance rolls once and floors a single-class fighter at 4;
* **`hp_max` is per class slot**, `min(level, roll_to) * bonus` summed over the
  slots, one extra bonus for a ranger, then divided by how many classes the
  character has -- against `hp_rolled + level * bonus` here. It disagrees with
  three of the six characters SSI shipped;
* **thief skills read dexterity** (`$0FC6`), and `thief_skill_row` has no term
  for it;
* **spell capacity is never stored.** Nothing in `GEN`, `ECL64` or `ECL65`
  writes `0x0EE`-`0x0F3`; `ECL65 $880D` rebuilds it in fifteen bytes of
  workspace whenever the sheet is drawn, and all six shipped characters hold
  zero there.

**Curse's tables are now in this file, and the four shapes that could not
carry them have been widened** (`#18`): `thief_skill_row` takes a dexterity,
`constitution_hp_bonus` takes a class slot, `wisdom_bonus_spells` takes a title
and returns as many spell levels as that title reaches, and `turning_level`
takes a paladin. Each carries its own grade, because they are not evidenced
alike -- what separates them is whether a byte on a disk votes for the reading
or only the code does:

| Curse table | grade | what votes for it |
|---|---|---|
| saving-throw rows, `$0F49` + `$0F5D` | CONFIRMED | 45 of 45 rows re-expanded, and 30 of 30 stored saves across six characters |
| constitution hit points, `$11D7` | CONFIRMED | 6 of 6 shipped `hp_max` |
| turning level, `$113F` | CONFIRMED | 2 of 2 shipped `turn_power`, and the same ten numbers Pool of Radiance tabulates |
| thief skills, `$1004`/`$10A4`/`$1064` | CONFIRMED | 8 of 8 columns on the one shipped thief |
| experience clamp, `$136E` entry 13 | CONFIRMED | the same table the 78 thresholds came from |
| wisdom bonus spells, `ECL65 $8906` | CONFIRMED, and **no record can ever agree** | the table read, plus the *Players Handbook* row; the bonus lands in RAM at `$2BBB` and is never stored |
| racial saving-throw bonus, `$0F19` | **CONFIRMED** | TRAVIS, a dwarf, had the trainer rewrite his five saves to exactly the class rows less `constitution * 2 // 7` on columns 0, 2 and 4 (2026-09-05, `WISH-SPEC-curse-trained-party`) |
| hit die rolled twice, `$15FC` | **PROBABLE** | the bytecode alone; a roll leaves no trace in a record |
| hit-die/constitution divide round-up rule, `$11AB` | CONFIRMED | 40 engine-written divides on 2026-09-05: 0 round-ups in 14 at two classes remainder 1, 0 in 12 at three classes remainder 1, 5 in 14 at three classes remainder 2 -- the `<` reading, and `goldbox/levelup.py`'s `divide_between_classes` now applies it per title through `divide_rounds_up` |
| one press raises every ready class, `$14F8` | CONFIRMED | watched: TRAVIS (thief/fighter) and LEDERA (magic-user/fighter) each raised both classes on one `TRAIN CHARACTER`, and `goldbox/levelup.py`'s `plan_all` reproduces the same order |

**`goldbox/levelup.py` now consumes both of these, and `TRAINER_MEASURED`
gains Curse.** Five Curse level-ups were driven and diffed on 2026-09-05: 75
derived fields and 5 spellbooks come back out of this module and
`goldbox/levelup.py` with no mismatches, the racial saving-throw bonus above
moved from PROBABLE to CONFIRMED on the strength of it, and 40 further
engine-written divides settled the hit-die/constitution round-up rule.
`divide_between_classes` asks `divide_rounds_up` for the comparison instead of
always applying Pool of Radiance's `<=`, and the new `plan_all` raises every
ready class in `$14F8`'s own slot order rather than one at a time -- both
proven against `WISH-SPEC-curse-train-input` and
`WISH-SPEC-curse-trained-party`, the same pair that measured them
(`tests/curse_of_the_azure_bonds/test_cursetrainer.py`). **`plan_all` now has a caller**:
`automap/actions.py`'s `LevelUp.run` asks `trains_all_ready_classes` and calls
`plan_all` instead of `plan` with no class named, whose `best_next_class`
picked the *opposite* order from `$14F8`'s for both TRAVIS and LEDERA
(`#18`). That reached the write; the last gap was one file further over, in
`automap/window.py`'s own decision of *when* to ask for a spell, closed on
`#415 (automap/window.py picks the level-up spell dialog's class the same
wrong way plan would have, blocking Curse's trainer)` -- `TRAINER_MEASURED`'s
own comment, below, has what it was and how it was fixed.

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

Curse and Silver Blades read one class differently: fighter, paladin and
ranger fold into a single fighter row at the best of those three levels
*before* that column-wise best is taken, and only once the best across all
the character's classes is settled does a paladin's -2 come off it
(`$0F01`/`$11C0`). A paladin who holds no other class gets the same answer
either way, which is why `paladin_save_after_best` exists as a per-title flag
rather than a change to the rule above.

**"Every class it holds" is every slot of the array at `0x0C9` with a level in
it**, and `$1F57 BEQ $1F9B` is where the engine says so: a slot holding zero is
skipped, not read as a level-1 class. It is also the level array rather than
the `class_bits` mask that the walk reads.

Pool of Radiance does not tabulate the rows. `GEN $1F44` fills all five columns
with 20, then for each class subtracts, per column, the number of set bits in
the low `level - 1` bits of *two* masks -- `$1FB6` and `$1FCA` -- from the
level-1 row at `$1FA2`, keeping whichever class gives the lower number. The
rows written out below are that encoding expanded, and
`tests/records/test_levels.py` re-expands it off the player's own `GEN` rather than
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

#: **The DOS build ships a different THAC0 table, and that is the whole of the
#: difference between the two ports.** Both engines run the same routine -- zero
#: the field, then walk the eight class slots and keep the best row -- so
#: neither clamps and neither leaves the value stale:
#:
#: * C64 `GEN $1EF3`: `LDA $6BC9,X` (`class_levels[X]`), `X = class * 9 + level`,
#:   `LDA $1F1F,X`, then `$1F17` stores it only if it beats what is there.
#:   `SPELLE04 $0CFF` writes the zero this starts from.
#: * DOS `GAME.OVR:0x1A659`: `mov es:[di+0x2D], 0`, then per class
#:   `mov dx, 0xB / mul dx / add di, cx / mov al, [di+0x3C7C]` and the same
#:   store-if-better. `DS:0x3C7C` is the table: **8 rows of 11**, class in the
#:   class-number order `cleric druid fighter paladin ranger magic-user thief
#:   monk`, indexed by level 1-10 with entry 0 unused, exactly the shape the
#:   C64's own `$1F1F` has.
#:
#: The cleric and fighter rows are byte for byte the C64's over every level both
#: reach. The magic-user's and the thief's are not: DOS stores 40 where the C64
#: stores 39, so a DOS magic-user is THAC0 20 for levels 1-5 and a DOS thief is
#: 20 for levels 1-4, where the C64 gives both 21. Rows below are THAC0, not the
#: stored `60 - THAC0`, and run level 1 to 10 whatever this title's ceiling is,
#: because that is what the table holds. `#318 (DOS gives a low-level magic-user
#: or thief THAC0 20 where the C64 gives 21, and our table holds only the
#: C64's)`.
#:
#: CONFIRMED: 178 of 178 DOS Pool of Radiance records this machine can reach
#: reproduce from these rows by best-of-classes, with no exceptions -- the nine
#: `WISH-SPEC-por-party-ladder-rung*` specimens the trainer was watched writing,
#: the play saves, and the archives. `tools/records/thac0census.py` is the sweep and
#: `tests/records/test_levels.py` re-reads the rows out of the player's own `START.EXE`.
#:
#: **Curse and Silver Blades are filled in too, from the same read, in
#: `_DOS_THAC0_CURSE` and `_DOS_THAC0_SSB` below.** Their DOS tables sit at
#: `DS:0x3E3A` (Curse, 8 rows of 13) and `DS:0x4C0C` (Silver Blades, 7 rows of
#: 19, dropping the monk) -- located by `tools/c64/laterthac0.py` without
#: anchoring on a THAC0 number at all, because their class-bit array is a
#: different permutation from Pool of Radiance's and `tools/records/thac0census.py`
#: cannot find either. `docs/210-the-later-titles-dos-thac0.md` has the whole
#: of it.
#:
#: **A low-level magic-user is not where the later titles' shipped rows
#: disagree with the C64.** Both DOS mage rows read 21 at levels 1-5, agreeing
#: with their own C64 side -- Pool of Radiance is the odd title in its rows.
#: What the later DOS engines *store* for such a magic-user is 20 all the
#: same, because every row's entry 0 holds a THAC0 rather than the C64's `$00`
#: sentinel and the recompute that runs on load reads it for every class the
#: character has no level in: `docs/224-the-dos-thac0-floor.md`, and `#608`.
#: What disagrees in the rows themselves, in both later titles, CONFIRMED from
#: the shipped bytes and the records below:
#:
#: * thief 1-4: DOS 20, C64 21;
#: * the magic-user's third band: DOS 17, C64 16 (Curse 11-12, Silver Blades
#:   11-15);
#: * fighter, paladin and ranger at level 2: DOS 20, C64 19 -- the whole row
#:   is `39 + level` at every other index. CONFIRMED in both titles' images;
#:   the *consequence* is PROBABLE, because no record here holds a level-2
#:   fighter, paladin or ranger in either title.
#:
#: **No clamp exists anywhere.** None of the three engines compares the field
#: against a constant; the floor a DOS record never goes below is the level-0
#: column of these same rows, read by a loop that does not test the level --
#: `tools/c64/laterthac0.py writers` has every site that touches the byte.
#:
#: CONFIRMED: 250 of 250 Pool of Radiance, 101 of 104 Curse and 86 of 86
#: Silver Blades records reproduce from these rows by the engine's own rule,
#: against 250, 92 and 84 by best-of-classes; the three Curse records left
#: over are one regained dual-class record and the two magic-users our own
#: writer produced. `tools/records/thac0census.py dos --title <key>` is the
#: sweep and `docs/224-the-dos-thac0-floor.md` the reasoning.
_DOS_THAC0_POOL = (
    ("magic-user", (20, 20, 20, 20, 20, 19, 19, 19, 19, 19)),
    ("cleric",     (20, 20, 20, 18, 18, 18, 16, 16, 16, 14)),
    ("thief",      (20, 20, 20, 20, 19, 19, 19, 19, 16, 16)),
    ("fighter",    (20, 19, 18, 17, 16, 15, 14, 13, 12, 11)),
)

#: **Entry 0 of every DOS row, as THAC0, which the recompute that runs when a
#: party loads reads for each class the character has no level in.** The loop
#: at Pool of Radiance `GAME.OVR:0x02AA87`, Curse `0x03B026` and Silver Blades
#: `0x03C1B1` walks every class slot without testing the level, so a slot
#: holding zero indexes the row's entry 0, and `dos_engine_thac0` keeps the best
#: of all of them. Class-number order, the classes each title's table has:
#: `tools/records/thac0census.py`'s `dos_rows` reads the same column out of the
#: player's own `START.EXE`, and `tests/convert/test_dosthac0floor.py` compares.
#: Every entry is 20 but the fighter's and the magic-user's in the later two
#: titles, which is 21 -- so no character is ever worse than THAC0 20, and only
#: a magic-user of level 1-5 (row value 21) is lifted by it. `docs/224-the-dos-thac0-floor.md`.
_DOS_THAC0_LEVEL0_POOL = (
    ("cleric", 20), ("druid", 20), ("fighter", 20), ("paladin", 20),
    ("ranger", 20), ("magic-user", 20), ("thief", 20), ("monk", 20),
)
_DOS_THAC0_LEVEL0_CURSE = (
    ("cleric", 20), ("druid", 20), ("fighter", 21), ("paladin", 20),
    ("ranger", 20), ("magic-user", 21), ("thief", 20), ("monk", 20),
)
#: Silver Blades' table has seven rows and no monk.
_DOS_THAC0_LEVEL0_SSB = _DOS_THAC0_LEVEL0_CURSE[:-1]


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


# AD&D 1st edition saving throws, by the last level of each band -- and **every
# row below is now Curse's own**, not a transcription that agrees with one.
# `GEN $0F49` holds the level-1 rows, four classes of five bytes, and `$0F5D`
# holds 80 bytes more: a four-byte mask a column, two bits a level for sixteen
# levels, which `$0E7E` subtracts a level at a time. Expanding it reproduces
# all 45 rows here (`tests/curse_of_the_azure_bonds/test_cursetrainer.py`), and its rows past Curse's
# ceilings are Silver Blades' measured extensions exactly.
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

#: `GEN $1909` writes 2 or 3 into `attack_forms` by comparing every class
#: slot's level with the row at `$191E`, which reads `63 63 63 07 63 63 07 08`
#: -- 99, 99, 99, **7**, 99, 99, **7**, **8** in class-slot order. So a fighter
#: and a paladin reach two attacks in three rounds at 7 and a **ranger at 8**.
#:
#: This file said 7 for the ranger until `#18` read `$191E`; the row was a
#: transcription of the fighter's, and Silver Blades' separately measured
#: `_ATTACKS_RANGER_SSB` had said 8 all along, which is the corroboration.
_ATTACKS_FIGHTER = ((6, 1), (99, 1.5))
_ATTACKS_RANGER = ((7, 1), (99, 1.5))

#: `ECL65` payload `0x88D`: eleven magic-user rows of five, then ten cleric
#: rows of five. Trailing zeroes are dropped so a row reads the way a character
#: sheet does.
_SLOTS_MAGIC_USER = ((1,), (2,), (2, 1), (3, 2), (4, 2, 1), (4, 2, 2),
                     (4, 3, 2, 1), (4, 3, 3, 2), (4, 3, 3, 2, 1),
                     (4, 4, 3, 2, 2), (4, 4, 4, 3, 3))
_SLOTS_CLERIC = ((1,), (2,), (2, 1), (3, 2), (3, 3, 1), (3, 3, 2),
                 (3, 3, 2, 1), (3, 3, 3, 2), (4, 4, 3, 2, 1), (4, 4, 3, 3, 2))

#: The paladin's cleric slots, from level 9. Curse's DOS slot builder,
#: `GAME.OVR:0x3AC81`, reads them out of `DS:43E5` and **adds them into the
#: cleric array** at record `0x12D` -- a paladin has no array of his own. The
#: C64 computes the same three rows arithmetically rather than from a table
#: (`ECL65 $884B`: `LDA $7CCF` for the paladin's class-level slot, then three
#: compares against 9, 10 and 11), so both ports agree. `goldbox.spells.
#: _PALADIN_CURSE` is the same progression written out to the record's full
#: five columns, and `tests/curse_of_the_azure_bonds/test_cursespellslots.py` reads `DS:43E5` back off
#: the player's own image (#548).
_SLOTS_PALADIN = ((), (), (), (), (), (), (), (), (1,), (2,), (2, 1))

#: `GEN` `$136E`, measured. Every value is the AD&D 1st edition number plus one
#: -- 2001 to leave fighter 1 -- with two exceptions the disk is emphatic
#: about: the ranger's first threshold is a bare 2250, and the fighter's
#: eleventh reads 749937 where 750001 is expected. That is one bit (`$40`) in
#: the middle byte of `0B 71 B1`. Settled 2026-09-02: Silver Blades' `GEN
#: $162D`, a different file from a different release, carries the same
#: 749937 (`tests/c64/test_coldread.py::
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
# **Both tables are found, and neither is in `ECL65`.** This comment used to
# say no spell table existed for either class; what it should have said is
# that neither is in `ECL65` beside the cleric's and the magic-user's, which
# is where somebody had looked. They are in the DOS build, read out of
# `GAME.OVR:0x3AC81`'s own delta tables -- the paladin's at `DS:43E5` and the
# ranger's at `DS:4448` -- and the same read reproduces `_SLOTS_CLERIC` and
# `_SLOTS_MAGIC_USER` row for row off `DS:42BC` and `DS:44AB`, which is the
# corroboration that makes the other two safe to take from DOS (#548).
#
# **The ranger's stay empty here, and that is the field rather than the
# reading.** `Level.spells` is one tuple and a ranger fills two arrays from
# one class level: druid spells from 8 and magic-user spells from 9. Putting
# either run in this field alone would say the other did not exist.
# `goldbox.spells._RANGER_CURSE` carries the pair, and `goldbox.spells.
# capacity_by_class` is what a caller wanting a ranger's slots asks.
CURSE_PALADIN = _progression(
    ceiling=11, experience=_XP_PALADIN, thac0=_THAC0_FIGHTER,
    saves=_SAVES_PALADIN, die=10, roll_to=9, flat=3, attacks=_ATTACKS_FIGHTER,
    spells=_SLOTS_PALADIN)
CURSE_RANGER = _progression(
    ceiling=11, experience=_XP_RANGER, thac0=_THAC0_FIGHTER,
    saves=_SAVES_RANGER, die=8, roll_to=10, flat=2, attacks=_ATTACKS_RANGER)


# --- Secret of the Silver Blades ----------------------------------------------
# GEN $162D / $17D0 / $17E0 / $106F-$108F / $1045 / $13EF-$13F7 / $1845-$1855 /
# $1148-$115C / $11C0 / $11D8, all at base $0800, read by tests/c64/test_coldread.py.
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
#:
#: **This is the C64's own table, and DOS does not ship the same one**
#: (`#431`, A converted halfling thief keeps the other port's skill
#: percentages, because the two ports ship different halfling rows).
#: `tools/records/thiefskillcensus.py tables` reads both off the player's own files:
#: the two agree for 21 bytes and from there the C64's stream is the DOS
#: stream one byte short, so the gnome's hear-noise and climb-walls columns
#: collapse to a single `-5` and every race after the gnome reads the row
#: laid out for the *next* one. CONFIRMED. `_DOS_THIEF_SKILL_RACE_POOL`
#: below is DOS's own, undisplaced, copy.
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

#: DOS Pool of Radiance's own racial row, `START.EXE` at the offset
#: `tools/records/thiefskillcensus.py tables --title pool-of-radiance` prints,
#: located by the C64's own 72 bytes of level table so the read cannot agree
#: with this module by construction. Seven rows -- DOS has no eighth
#: (monster) row, and `thief_skill_row`'s bounds check leaves an index past
#: the end unmodified, which is the same as a row of zeros. `#431`.
_DOS_THIEF_SKILL_RACE_POOL = (
    (0, 10, 15, 0, 0, 0, -10, -5),      # dwarf -- same as the C64
    (5, -5, 0, 5, 10, 5, 0, 0),         # elf -- same as the C64
    (0, 5, 10, 5, 5, 10, -15, 0),       # gnome
    (10, 0, 0, 0, 5, 0, 0, 0),          # half-elf
    (5, 5, 5, 10, 15, 5, -15, -5),      # halfling
    (-5, 5, 5, 0, 0, 5, 5, -10),        # half-orc
    (0, 0, 0, 0, 0, 0, 0, 0),           # human
)

#: DOS Pool of Radiance's dexterity block, same file, eleven rows of five
#: columns from a dexterity of 9 -- pick pockets, open locks, find traps,
#: move silently, hide in shadows. Padded to eight columns with three
#: trailing zeros so it can share `thief_skill_row`'s zip-based sum the way
#: `_THIEF_SKILL_DEX_CURSE` already does: the C64 build of this title never
#: reads dexterity at all (`GEN $1FEC`), which is the bug `#431` is about.
#: **DOS also clamps the final sum at zero on every column**, which this
#: table alone does not capture -- `dos_thief_skill_row` applies it.
_DOS_THIEF_SKILL_DEX_POOL = (
    (-15, -10, -10, -20, -10, 0, 0, 0),     # dexterity 9 and below
    (-19, -5, -10, -15, -5, 0, 0, 0),       # 10
    (-5, 0, -5, -10, 0, 0, 0, 0),           # 11
    (0, 0, 0, -5, 0, 0, 0, 0),              # 12
    (0, 0, 0, 0, 0, 0, 0, 0),               # 13
    (0, 0, 0, 0, 0, 0, 0, 0),               # 14
    (0, 0, 0, 0, 0, 0, 0, 0),               # 15
    (0, -5, 0, 0, 0, 0, 0, 0),              # 16
    (5, 10, 0, 5, 5, 0, 0, 0),              # 17
    (10, 15, 5, 10, 10, 0, 0, 0),           # 18
    (15, 20, 10, 12, 12, 0, 0, 0),          # 19
)
DOS_THIEF_SKILL_DEX_FROM_POOL = 9

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


# --- what Curse's trainer rolls and looks up ---------------------------------
# Read off `CURSE_A.D64`'s own `GEN` and `ECL65` (`#18`), by the instruction
# that touches the character record at `$7C00` -- `tools/c64/trainerscan.py`.
# `tests/curse_of_the_azure_bonds/test_cursetrainer.py` re-reads every one of these off the player's
# disk, so a wrong number here fails rather than sits.

#: `GEN $1004`, nine rows of eight, indexed by `thief level - 1`. **The same
#: 72 bytes as Pool of Radiance's `$102E`**, 42 bytes earlier in the file --
#: one of only two Pool of Radiance tables that survive into Curse at all --
#: so this is an alias rather than a second transcription, and
#: `test_curses_thief_level_rows_are_pool_of_radiances_own_bytes` is what
#: would notice if one moved.
_THIEF_SKILLS_CURSE = _THIEF_SKILLS_POOL

#: `GEN $1064`, eight rows of eight, indexed by `race - 1`. **Not Pool of
#: Radiance's.** Dwarf and elf are identical; gnome, half-elf, halfling and
#: half-orc are AD&D 1st edition verbatim where Pool of Radiance's carry the
#: same numbers in different columns.
_THIEF_SKILL_RACE_CURSE = (
    (0, 10, 15, 0, 0, 0, -10, -5),      # dwarf
    (5, -5, 0, 5, 10, 5, 0, 0),         # elf
    (0, 5, 10, 5, 5, 10, -15, 0),       # gnome
    (10, 0, 0, 0, 5, 0, 0, 0),          # half-elf
    (5, 5, 5, 10, 15, 5, -15, -5),      # halfling
    (-5, 5, 5, 0, 0, 5, 5, -10),        # half-orc
    (0, 0, 0, 0, 0, 0, 0, 0),           # human
    (0, 0, 0, 0, 0, 0, 0, 0),           # monster
)

#: `GEN $10A4`, seventeen rows of eight, and Pool of Radiance has nothing like
#: it: `$0FC6 LDA $7C17 / SEC / SBC #$09` indexes this by
#: `max(0, dexterity - 9)`, so row 0 answers for any dexterity of 9 or less and
#: row 16 for 25. AD&D 1st edition's thief dexterity adjustment exactly.
_THIEF_SKILL_DEX_CURSE = (
    (-15, -10, -10, -20, -10, 0, 0, 0),     # dexterity 9 and below
    (-10, -5, -10, -15, -5, 0, 0, 0),       # 10
    (-5, 0, -5, -10, 0, 0, 0, 0),           # 11
    (0, 0, 0, -5, 0, 0, 0, 0),              # 12
    (0, 0, 0, 0, 0, 0, 0, 0),               # 13
    (0, 0, 0, 0, 0, 0, 0, 0),               # 14
    (0, 0, 0, 0, 0, 0, 0, 0),               # 15
    (0, 5, 0, 0, 0, 0, 0, 0),               # 16
    (5, 10, 0, 5, 5, 0, 0, 0),              # 17
    (10, 15, 5, 10, 10, 0, 0, 0),           # 18
    (15, 20, 10, 12, 12, 0, 0, 0),          # 19
    (20, 25, 15, 15, 15, 0, 0, 0),          # 20
    (25, 30, 20, 18, 18, 0, 0, 0),          # 21
    (30, 35, 25, 20, 20, 0, 0, 0),          # 22
    (35, 40, 30, 23, 23, 0, 0, 0),          # 23
    (40, 45, 35, 25, 25, 0, 0, 0),          # 24
    (45, 50, 40, 30, 30, 0, 0, 0),          # 25
)
THIEF_SKILL_DEX_FROM_CURSE = 9

#: `GEN $11D7`, twenty-six **signed** bytes indexed by the raw constitution
#: score, which is the whole of Curse's constitution rule. Two things Pool of
#: Radiance's pair of banded rows does not do:
#:
#: * it has **no floor** -- a score of 1 to 3 is -2 and 4 to 6 is -1, so a
#:   Curse character that frail loses a hit point a level where Pool of
#:   Radiance's `CPX #$0F` refuses to look below 15 and gives zero;
#: * there is no second row for a non-fighter. `$126D` clamps the *score* to
#:   16 for class slots 0-2 instead (`CPY #$03 / BCS / CPX #$11 / BCC / LDX
#:   #$10`), which reaches the same +2 ceiling from the other direction.
#:
#: From 7 to 18 the two titles agree on both rows, which is why nothing has
#: been visibly wrong for an ordinary character. Above 18 they do not: Pool of
#: Radiance gives a non-fighter up to +5, and Curse's score clamp holds it at
#: +2 for ever. No score above 18 is reachable in play.
_HP_BONUS_CURSE = (0, -2, -2, -2, -1, -1, -1, 0, 0, 0, 0, 0, 0, 0, 0,
                   1, 2, 3, 4, 5, 5, 6, 6, 6, 7, 7)
#: `$126D CPX #$11 / LDX #$10`, and the slot the test turns on.
HP_BONUS_SCORE_CAP_CURSE = 16
HP_BONUS_UNCAPPED_FROM_CURSE = 3

#: `ECL65 $8906` at wisdom 13 to 19: which spell level -- 0 for the first --
#: each point of wisdom from 13 up buys. `$88F6` loops `DEY / CPY #$0D / BCS`,
#: so a cleric with wisdom 16 runs the loop four times and collects one spell
#: at each of levels 1, 1, 2 and 2.
#:
#: **The range is the reachable one.** Below 13 the routine never enters
#: (`CPY #$0D / BCC`); above 19 `LDX $8906,Y` would read past this table into
#: the next one, and no character can hold a wisdom above 18.
_WISDOM_BONUS_CURSE = (0, 0, 1, 1, 2, 3, 4)
WISDOM_BONUS_FROM_CURSE = 13

#: `GEN $113F` expanded over a Curse cleric's whole range, because Curse
#: **computes** this where Pool of Radiance tabulates it: `max(cleric,
#: paladin - 2)`, stored as it is below 4 and `+ 1` capped at 10 from 4 up.
#: Over cleric 1 to 10 that is Pool of Radiance's `$2399` entry for entry, and
#: `paladin_turn_offset` carries the branch Pool of Radiance has no class for.
_TURN_POWER_CURSE = (1, 2, 3, 5, 6, 7, 8, 9, 10, 10)

#: `GEN $13A5` expanded over a Silver Blades cleric's whole range. The routine
#: is Curse's `$113F` with one branch more on the end: `max(cleric, paladin -
#: 2)`, stored as it is below 4, `+ 1` from 4 up, then `CMP #$0A / BCC store`,
#: `CMP #$0F / BCC` a `LDA #$0A`, and `LDA #$0C` past that. So a cleric 9 to 13
#: stores 10 and a cleric 14 or 15 stores 12, which is Pool of Radiance's
#: `$2399` table entry for entry -- a third mechanism reaching the same
#: fourteen numbers. Kept as its own tuple rather than shared with
#: `_TURN_POWER_POOL` because the two are read out of different code (#288).
_TURN_POWER_SILVER = (1, 2, 3, 5, 6, 7, 8, 9, 10, 10, 10, 10, 10, 12)

#: The three trainer inputs `#89`'s 2026-09-08 measurement found, read off
#: `SILVER*.D64`'s own `GEN` and `ECL65` with `tools/secret_of_the_silver_blades/ssbtrainerinputs.py`.
#: `--rows` reprints every number below from the disk at run time; these are a
#: transcription of what it printed, not a decoding done here.

#: `GEN $0E80`, twenty-six signed bytes, the same 26 as Curse's `$11D7` byte
#: for byte -- so this is an alias rather than a second transcription, the way
#: `_THIEF_SKILLS_CURSE = _THIEF_SKILLS_POOL` is above.
_HP_BONUS_SSB = _HP_BONUS_CURSE

#: `GEN $126D`, seventeen rows of eight, clamped at 17 (`$1213 CPX #$11 / LDX
#: #$11`). Rows 1-9 are `_THIEF_SKILLS_POOL`'s own 72 bytes; rows 10-17 are
#: Silver Blades' own, AD&D 1st edition verbatim -- the first title in the
#: family to reach a thief level that high.
_THIEF_SKILLS_SSB = _THIEF_SKILLS_POOL + (
    (80, 67, 65, 78, 63, 30, 99, 50),
    (90, 72, 70, 86, 70, 35, 99, 55),
    (100, 77, 75, 94, 77, 35, 99, 60),
    (105, 82, 80, 99, 85, 40, 99, 65),
    (110, 87, 85, 99, 93, 40, 99, 70),
    (115, 92, 90, 99, 99, 50, 99, 75),
    (125, 97, 95, 99, 99, 50, 99, 80),
    (125, 99, 99, 99, 99, 55, 99, 80),
)

#: `GEN $131D`, seventeen rows of eight from a dexterity of 9, the same 136
#: bytes as Curse's `$10A4`.
_THIEF_SKILL_DEX_SSB = _THIEF_SKILL_DEX_CURSE

#: `GEN $12F5`, six rows of eight, **not** indexed `race - 1`: `$124D` reads
#: it at `race * 8` with no decrement, so row 0 (laid out for the elf) is
#: dead data and every race reads the row laid out for the *next* one --
#: `thief_skill_race_index_from=0` on the title below reproduces that. The
#: five rows that are read are Curse's `_THIEF_SKILL_RACE_CURSE` rows
#: re-ordered into `c64_port.RACES_SILVER_BLADES`; row 5 is not a racial row at
#: all but the first row of `_THIEF_SKILL_DEX_SSB`, which is what the
#: halfling (race 5) actually reads.
_THIEF_SKILL_RACE_SSB = (
    (5, -5, 0, 5, 10, 5, 0, 0),          # row 0, laid out for the elf -- dead
    (10, 0, 0, 0, 5, 0, 0, 0),           # row 1, laid out for the half-elf
    (0, 10, 15, 0, 0, 0, -10, -5),       # row 2, laid out for the dwarf
    (0, 5, 10, 5, 5, 10, -15, 0),        # row 3, laid out for the gnome
    (5, 5, 5, 10, 15, 5, -15, -5),       # row 4, laid out for the halfling
    (-15, -10, -10, -20, -10, 0, 0, 0),  # row 5, the dexterity table's own
)

#: `ECL65 $89F0`, wisdom 13 to 19, the same seven bytes as Curse's `$8906`.
_WISDOM_BONUS_SSB = _WISDOM_BONUS_CURSE


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


def constitution_hp_bonus(constitution: int, fighter: bool = False,
                          game=None, class_slot: int | None = None) -> int:
    """Hit points a level from constitution. `GEN $2471`, or Curse's `$126D`.

    **The default is Pool of Radiance's**, the AD&D 1st edition pair of banded
    rows unchanged, including the cap of +2 for anybody who is not a fighter,
    and every caller written before there was a second title means that one.

    **Curse's is one signed row and no floor** -- `_HP_BONUS_CURSE` says how
    they differ. `class_slot` is Curse's own selector: `$126D` clamps the score
    for slots 0-2 and reads the whole row for 3 and up, which is not the same
    question as `fighter`, because a fighter/magic-user's *magic-user* slot is
    capped and its fighter slot is not. Pass one when summing a Curse
    character's slots; `fighter` still answers for a caller that has only the
    class bits, and picks the capped reading for a non-fighter.
    """
    return for_game(game).constitution_hp_bonus(
        constitution, fighter=fighter, class_slot=class_slot)


#: `GEN $10AD`, indexed by the wisdom score. One number, which `GEN $2108`
#: then halves its way down for the second and third spell levels.
_WISDOM_BONUS_BASE = 12


def wisdom_bonus_spells(wisdom: int, game=None,
                        port: str | None = None) -> tuple[int, ...]:
    """Bonus cleric spells, by spell level. `GEN $2108`, or Curse's `$88F6`.

    **Three numbers for Pool of Radiance and five for Curse**, because the
    width is how many spell levels the title's cleric rows reach. A caller
    that passes no title gets Pool of Radiance's three, which is what every
    caller written before there was a second title means.

    **Curse's is a different table and a different rule** -- `ECL65 $88F6`
    loops once for every point of wisdom from 13 up, each point buying one
    spell at the level `$8906` names -- and the one visible difference is at
    wisdom 12, where Pool of Radiance grants a spell AD&D does not and Curse
    does not (`docs/125-bug-notes.md`). Curse's branch returns before `port`
    is consulted, so this argument makes no difference to it: both builds
    run the same row table (#547).

    **The C64 build's table starts one point low.** AD&D 1st edition gives
    the first bonus spell at wisdom 13 and the second at 14; `$10AD` holds 1
    at 12 and 2 from 13 up, so a wisdom-12 cleric memorises a first-level
    spell the rules do not give it. The second- and third-level columns are
    AD&D exactly -- they are gated on `CPY #$0F`, `#$10` and `#$11`. See
    `docs/125-bug-notes.md`.

    **`port="DOS"` shifts the first column to the title's own
    `dos_wisdom_bonus_from`**, when the title has read one (Pool of
    Radiance's is 13, from `START.EXE 0x00F6B0` and two engine-written
    specimens, #557). Only the exact string `"DOS"` selects it: an Amiga
    record keeps the C64's numbers, because nobody has read Amiga Pool of
    Radiance's own table, and a port nobody has measured keeps what it had
    rather than being corrected by a table never checked against it.  A
    title with no `dos_wisdom_bonus_from` (0) answers exactly as it would
    with no port at all.

    The bonus is only granted where the class table already gives a slot at
    that spell level (`GEN $210A` skips a zero), so a level-1 cleric gets no
    second-level spell however wise it is. That last clause is Curse's too.
    """
    tables = for_game(game)
    if tables.wisdom_bonus_level:
        return tables.wisdom_bonus_spells(wisdom)
    base_from = _WISDOM_BONUS_BASE
    if port == "DOS" and tables.dos_wisdom_bonus_from:
        base_from = tables.dos_wisdom_bonus_from
    score = int(wisdom or 0)
    if score < base_from:
        return (0, 0, 0)
    base = 1 if score == base_from else 2
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
    is the shape `goldbox/c64_port.py` settled on for the same reason.

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
    #: Radiance). Derivable from `c64_port.C64Container.races` and would live better
    #: there; it is here because nothing else needs it yet and this module
    #: does not import that one.
    sturdy_races: tuple[int, ...] = (1, 3, 5)
    #: The trainer's own tables, read out of the title's `GEN`. Empty means
    #: nobody has read this title's copy, and every caller treats that as
    #: "cannot answer" rather than as a zero.
    thief_skills: tuple[tuple[int, ...], ...] = ()
    thief_skill_race: tuple[tuple[int, ...], ...] = ()
    #: The race code row 0 of `thief_skill_race` answers for. 1 for Pool of
    #: Radiance (`$2005 LDY race / DEY`) and Curse (`$0FE6 LDX race / DEX`),
    #: whose racial tables are laid out `race - 1`. Silver Blades' `GEN
    #: $124D` is `LDA race / CMP #$06 / BCS / ASL / ASL / ASL` with **no**
    #: decrement, so its table is read at `race * 8` and every thief gets
    #: the *next* race's adjustments -- a bug in the shipped game, recorded
    #: as `goldbox-bugs.md` entry 13, that Wish reproduces here (0) rather
    #: than the row the table's own layout suggests.
    thief_skill_race_index_from: int = 1
    turn_power: tuple[int, ...] = ()
    #: What the trainer clamps experience to at the class ceiling. The game's
    #: threshold arrays are nine wide a class and each class's tenth entry
    #: falls in the next class's unused slot 0, so `GEN $23D4` reads a real
    #: number one past every ceiling: 60,001 for a magic-user 6, 55,001 for a
    #: cleric 6, 160,001 for a thief 9 and 250,001 for a fighter 8. Kept apart
    #: from the rows because `next_threshold` must stay None at the ceiling --
    #: an experience bar there has nothing to fill towards.
    #:
    #: Curse's rows are thirteen wide and every class has a real entry one past
    #: its ceiling, so its six numbers come out of the same table the 78
    #: thresholds did rather than out of a neighbouring class's slot 0. The
    #: field is still needed: `at_level` stops at the ceiling, so nothing else
    #: in here can reach that thirteenth entry.
    clamp_thresholds: tuple[tuple[str, int], ...] = ()
    #: `GEN $10A4`, added to the level row alongside the racial one. Empty
    #: where the title's thief routine reads no ability score at all, which is
    #: Pool of Radiance (`$1FEC`). A title that has this table **cannot answer
    #: without a dexterity** and `thief_skill_row` returns None rather than
    #: reading row 0, which would be the adjustment for a dexterity of 9.
    thief_skill_dexterity: tuple[tuple[int, ...], ...] = ()
    #: The score row 0 answers for; `$0FC6 SBC #$09`.
    thief_skill_dexterity_from: int = 0
    #: **DOS's own racial row, where it differs from the C64's** (`#431`).
    #: Empty means nobody has measured a per-port difference for this title
    #: -- Curse ships the same 56 racial bytes on both ports, and Silver
    #: Blades' agreement is unmeasured, so neither sets this. Consulted only
    #: by :meth:`dos_thief_skill_row`, which nothing in this codebase calls
    #: yet: the DOS write path that would (`goldbox/dos_codec.py`) has not been
    #: wired up.
    dos_thief_skill_race: tuple[tuple[int, ...], ...] = ()
    dos_thief_skill_dexterity: tuple[tuple[int, ...], ...] = ()
    dos_thief_skill_dexterity_from: int = 0
    #: `GEN $11D7`: hit points a level from constitution, indexed by the raw
    #: score and **signed**. Empty means the title uses the two banded rows in
    #: `_HP_BONUS_FIGHTER` and `_HP_BONUS_OTHER` from `HP_BONUS_FROM` up, which
    #: is Pool of Radiance's shape.
    hp_bonus_by_score: tuple[int, ...] = ()
    #: What a capped score is clamped to, and the first class slot that is not
    #: capped. `$126D CPY #$03 / BCS / CPX #$11 / BCC / LDX #$10`.
    hp_bonus_score_cap: int = 0
    hp_bonus_uncapped_from: int = 0
    #: `ECL65 $8906`: which spell level each point of wisdom from
    #: `wisdom_bonus_from` up buys a cleric. Empty means the title uses Pool of
    #: Radiance's `$10AD` arithmetic in `wisdom_bonus_spells`.
    wisdom_bonus_level: tuple[int, ...] = ()
    wisdom_bonus_from: int = 0
    #: How many levels behind a cleric a paladin turns undead, or None where
    #: the title has no paladin at all. Curse's `$113F SBC #$02`.
    paladin_turn_offset: int | None = None
    #: How many hit dice the trainer rolls, keeping the best. Pool of Radiance
    #: rolls one (`$2037`) and Curse rolls two (`$15FC`). Only a title in
    #: `TRAINER_MEASURED` may lean on this: an unread title keeps the default
    #: because something has to be the default, not because anybody looked.
    hit_die_rolls: int = 1
    #: The floor a *single-class fighter*'s roll takes -- Pool of Radiance's
    #: `CMP #$04`. None where the title has no floor of any kind, which is
    #: Curse: `$15E1` has no `CMP #$04` in its 61 bytes.
    hit_die_fighter_floor: int | None = 4
    #: What a divided roll is floored at. Pool of Radiance's `$20A2 BNE / LDA
    #: #$01`; Curse's `$11CC` is a bare `LDA $4C / RTS`, so a Curse
    #: multi-class character can gain nothing from a die.
    hit_die_divide_floor: int = 1
    #: Whether a roll **equal to** the remainder rounds a divided hit-die or
    #: constitution total up, in `divide_between_classes`. Both titles roll
    #: `1..class_count` out of the same `LIBRARY` routine (`$2F46` in Curse,
    #: `$2DBC` in Pool of Radiance) and compare it with the remainder; Pool of
    #: Radiance's `$208D` is `CMP $6E3F / BEQ inc / BCS out`, so a tied roll
    #: takes the `BEQ` and rounds up -- "roll <= remainder". Curse's `$11AB`
    #: is `CMP $7F3F / BCS out` with no `BEQ` in front of it, so a tie falls
    #: through -- "roll < remainder", which is **never** for a two-class
    #: character, whose remainder can only be 0 or 1. CONFIRMED from the
    #: bytecode and from 40 engine-written divides on 2026-09-05: 0 round-ups
    #: in 14 at two classes with remainder 1, 0 in 12 at three classes with
    #: remainder 1, and 5 in 14 at three classes with remainder 2 (predicting
    #: 1 in 3 once the tie is excluded, against the 2 in 3 a `<=` reading
    #: gives). `goldbox/levelup.py`'s `divide_between_classes` asks
    #: `divide_rounds_up`, below, for this comparison (#18).
    hit_die_divide_round_up_on_tie: bool = True
    #: Whether one training-hall press raises **every** class the character
    #: is ready for, rather than the one the player picks. Pool of Radiance's
    #: `$1B8C` raises a single class a visit; Curse's `$14F8` and Silver
    #: Blades' `$156F` both walk class slots 7 down to 0 and raise every
    #: qualifying one in the same press, each read directly off that title's
    #: own `GEN` and watched: five Curse trainings on 2026-09-05 raised two
    #: classes together for the two multi-class characters in the party
    #: (`WISH-SPEC-curse-trained-party`). CONFIRMED for both.
    #: `goldbox/levelup.py`'s `plan_all` loops over `ready_classes` in this
    #: same slot order to use it (#18).
    trains_all_ready_classes: bool = False
    #: Whether the recompute writes `attack_forms` outright or only raises it.
    #: Pool of Radiance's `$2342` refuses to lower (`LDX #$03 / CPX $6BD9 /
    #: BCC skip`) and never writes anything but 3; Curse's `$1909` stores what
    #: it computed, 2 or 3, whatever was there before.
    attack_forms_overwritten: bool = False
    #: Whether `spells_castable` at `0x0EE` is a field this title writes at
    #: all. False for Curse, where nothing in `GEN`, `ECL64` or `ECL65` writes
    #: those six bytes and all six shipped characters hold zero -- `ECL65
    #: $880D` rebuilds the number in RAM whenever the sheet is drawn.
    stores_spell_capacity: bool = True
    #: This title's **DOS** THAC0 rows, where the DOS build does not ship the
    #: C64's table -- class name to THAC0 by level, index `level - 1`. See
    #: `_DOS_THAC0_POOL` for the two routines and the provenance. Empty means
    #: nobody has read this title's DOS copy, and every caller treats that as
    #: "cannot answer" rather than as agreement with the C64.
    dos_thac0: tuple[tuple[str, tuple[int, ...]], ...] = ()
    #: Entry 0 of each of this title's DOS THAC0 rows, class to THAC0 -- the
    #: value the engine reads for a class the character has no level in. See
    #: `_DOS_THAC0_LEVEL0_POOL`. Empty where `dos_thac0` is.
    dos_thac0_level0: tuple[tuple[str, int], ...] = ()
    #: The wisdom score at which the DOS build's first bonus first-level
    #: cleric spell arrives, where it differs from the C64 build's `$10AD`.
    #: 0 means nobody has read this title's DOS table. `13` on Pool of
    #: Radiance, from `START.EXE 0x00F6B0`'s `01 02 02 02 02 02` and two
    #: engine-written specimens, `WISH-SPEC-human7` (wisdom 12) and
    #: `WISH-SPEC-halfe8` (wisdom 13). Left at 0 for Curse and Silver
    #: Blades, which is right rather than merely unread for Curse --
    #: `wisdom_bonus_level` already starts at 13 on both builds (#547).
    dos_wisdom_bonus_from: int = 0
    #: Whether :meth:`saving_throws` may answer from the class rows, the racial
    #: columns and nothing else. False where the title's recompute adjusts a
    #: column by a rule nobody has read closely enough to reproduce, so the
    #: method answers None -- "write nothing" -- rather than a row the engine
    #: would not store. Pools of Darkness' `GAME.OVR:0x0387B0` is the case:
    #: see `POOLS_OF_DARKNESS`.
    saving_throw_rule_read: bool = True
    #: Whether the paladin's -2 comes off the best row across *all* the
    #: character's classes, rather than off a paladin row of its own. Curse's
    #: `GEN $0E5E` folds fighter, paladin and ranger into one fighter row at
    #: the best of those three levels, takes the best of that row and every
    #: other class the character holds, and only then runs `JSR $0F01`
    #: (`LDA $7CCF / BEQ / SBC #$02`, floored at 0) if the character is a
    #: paladin. Silver Blades does the same at `$10A2`/`$11C0`. Both set this
    #: True (`#633`); Pool of Radiance has no paladin and leaves it False.
    paladin_save_after_best: bool = False
    #: `(class, level) -> row` for the cells this title's DOS save table holds
    #: differently from the C64's rows. Curse's (`DS:0x45BE`, read by
    #: `GAME.OVR:0x3B45B`) and Silver Blades' both read paladin 5 and 6 as
    #: `9 9 11 11 12` where the C64 reads `9 10 11 11 12`, and paladin 8 as
    #: `9 9 10 10 11` where the C64 reads `8 9 10 10 11`. A level-0 cell is
    #: the one :attr:`dos_save_trailing_slot` reads. Empty means nobody has
    #: read this title's DOS table -- see :attr:`dos_save_rule_read`.
    dos_save_overrides: tuple[tuple[tuple[str, int], tuple[int, ...]], ...] = ()
    #: Whether :meth:`dos_engine_saving_throws` may answer at all. False means
    #: this title's DOS load-time save rebuild has not been read, so the
    #: method returns None rather than guessing the C64's rows apply unchanged.
    dos_save_rule_read: bool = False
    #: DOS race bytes whose column 0 takes the racial constitution step in
    #: :meth:`dos_engine_saving_throws`, as a readied constitution booster
    #: always does. Curse's `0x3B45B` tests race 1 and 5, its dwarf and
    #: halfling; Silver Blades' `0x3C644` has no race test at all.
    dos_save_constitution_races: tuple[int, ...] = ()
    #: The class slot the DOS save rebuild's loop variable is left on after
    #: its last pass, which one more comparison then reads: when the current
    #: level there is above the former level, every column is lowered to the
    #: table cell at the *former* level (`dos_save_overrides` holds a level-0
    #: cell). Silver Blades' last slot is the thief (`GAME.OVR:0x3C768`).
    #: Curse's is the monk, which no character holds, so None there.
    dos_save_trailing_slot: str | None = None

    def divide_rounds_up(self, remainder: int, roll: int) -> bool:
        """Whether a divided hit-die or constitution total's leftover point
        goes to the quotient, this title's way.

        `roll` is `1..class_count`, the range `LIBRARY`'s own random routine
        returns (read for #18); `remainder` is what `divmod` left over. See
        `hit_die_divide_round_up_on_tie` for the comparison and its
        provenance. Called from `goldbox/levelup.py`'s `divide_between_classes`.
        """
        if not remainder:
            return False
        return roll < remainder or (
            roll == remainder and self.hit_die_divide_round_up_on_tie)

    def constitution_hp_bonus(self, constitution: int, *,
                              fighter: bool = False,
                              class_slot: int | None = None) -> int:
        """Hit points a level from constitution, this title's way.

        `class_slot` is Curse's selector and `fighter` is Pool of Radiance's;
        see the module-level function of the same name for why they are not
        the same question.
        """
        score = int(constitution or 0)
        if self.hp_bonus_by_score:
            capped = (class_slot < self.hp_bonus_uncapped_from
                      if class_slot is not None else not fighter)
            if capped and score > self.hp_bonus_score_cap:
                score = self.hp_bonus_score_cap
            return self.hp_bonus_by_score[
                max(0, min(score, len(self.hp_bonus_by_score) - 1))]
        if score < HP_BONUS_FROM:
            return 0
        row = _HP_BONUS_FIGHTER if fighter else _HP_BONUS_OTHER
        return row[min(score - HP_BONUS_FROM, len(row) - 1)]

    def wisdom_bonus_spells(self, wisdom: int) -> tuple[int, ...]:
        """Bonus cleric spells by spell level, for a title that tabulates it.

        One spell for every point of wisdom from `wisdom_bonus_from` up, at
        the level `wisdom_bonus_level` names for that point -- `ECL65 $88F6`,
        which loops `DEY / CPY #$0D / BCS`. Returns as many spell levels as
        the table can name.
        """
        table = self.wisdom_bonus_level
        if not table:
            return ()
        out = [0] * (max(table) + 1)
        top = min(int(wisdom or 0), self.wisdom_bonus_from + len(table) - 1)
        for score in range(self.wisdom_bonus_from, top + 1):
            out[table[score - self.wisdom_bonus_from]] += 1
        return tuple(out)

    def hit_dice_rolled(self, class_name: str, level: int) -> int | None:
        """How many dice the class has rolled by `level` -- `min(level,
        roll_to)`, which is the dice count `_progression` wrote into the row.

        This is the same `roll_to` the trainer keeps at `GEN $1282`, and it is
        what stops a Curse constitution bonus counting past the level the dice
        stop at.
        """
        row = self.at_level(class_name, level)
        if row is None:
            return None
        return int(row.hit_dice.partition("d")[0])

    def flat_hit_points(self, class_name: str, level: int) -> int | None:
        """What this level adds instead of rolling, or None if it rolls.

        `GEN $15F2 CMP $1626,X / BCC roll`: past `roll_to` the class stops
        rolling and adds a flat number a level (`$162E`). Pool of Radiance
        caps every class below the level this starts at, so it is None there
        for every class and every level it has a row for.
        """
        here, before = (self.at_level(class_name, level),
                        self.at_level(class_name, level - 1))
        if here is None or before is None:
            return None
        if self.hit_dice_rolled(class_name, level) != \
                self.hit_dice_rolled(class_name, level - 1):
            return None
        return here.hp_max - before.hp_max

    def thief_skill_row(self, level: int, race: int,
                        dexterity: int = 0) -> tuple[int, ...] | None:
        """The eight percentages a thief of that level and race stores.

        **Pool of Radiance's rule is the level row plus the racial row and
        nothing else** -- `GEN $1FEC` writes one, adds the other, and reads no
        ability score. **Curse adds a dexterity row** between them (`$0FAD`),
        so a title with `thief_skill_dexterity` returns None when it is not
        given one rather than silently reading the row for a dexterity of 9.

        Sums are left as they come out, including the negative ones: a
        dwarf thief's read-languages column is 0 - 5, and -5 is the byte the
        game's own `ADC` leaves behind as `$FB`.
        """
        if not self.thief_skills:
            return None
        level = max(1, min(int(level or 1), len(self.thief_skills)))
        row = self.thief_skills[level - 1]
        if self.thief_skill_dexterity:
            if not dexterity:
                return None
            at = max(0, min(int(dexterity) - self.thief_skill_dexterity_from,
                            len(self.thief_skill_dexterity) - 1))
            row = tuple(a + b for a, b in
                        zip(row, self.thief_skill_dexterity[at]))
        index = int(race or 0) - self.thief_skill_race_index_from
        if 0 <= index < len(self.thief_skill_race):
            row = tuple(a + b for a, b in
                        zip(row, self.thief_skill_race[index]))
        return tuple(row)

    def dos_thief_skill_row(self, level: int, race: int,
                            dexterity: int = 0) -> tuple[int, ...] | None:
        """The eight percentages DOS stores, where that differs from the C64.

        **Not the same rule as** :meth:`thief_skill_row`: DOS clamps every
        column at zero, where the C64 stores the negative byte (`#431`,
        `tools/records/thiefskillcensus.py --rule`). Returns `None` when this title
        has no `dos_thief_skill_race` -- either because both ports agree, or
        because nobody has measured that yet, and a caller must not read
        `thief_skill_row`'s answer as DOS's in that case.
        """
        if not self.dos_thief_skill_race or not self.thief_skills:
            return None
        level = max(1, min(int(level or 1), len(self.thief_skills)))
        row = self.thief_skills[level - 1]
        if self.dos_thief_skill_dexterity:
            if not dexterity:
                return None
            at = max(0, min(int(dexterity) - self.dos_thief_skill_dexterity_from,
                            len(self.dos_thief_skill_dexterity) - 1))
            row = tuple(a + b for a, b in
                        zip(row, self.dos_thief_skill_dexterity[at]))
        index = int(race or 0) - self.thief_skill_race_index_from
        if 0 <= index < len(self.dos_thief_skill_race):
            row = tuple(a + b for a, b in
                        zip(row, self.dos_thief_skill_race[index]))
        return tuple(max(0, v) for v in row)

    def dos_thac0_at(self, class_name: str, level: int) -> int | None:
        """What the **DOS** build's own table gives one class at one level.

        None where this title's DOS table has not been read, so a caller that
        needs the DOS number can tell "we have not looked" from "it is the same
        as the C64's". Levels below 1 and above the row clamp to its ends, the
        way `mov al, [di+0x3C7C]` does with whatever `class_levels` holds.
        """
        row = dict(self.dos_thac0).get(class_name)
        if not row:
            return None
        return row[max(0, min(int(level or 1), len(row)) - 1)]

    def dos_base_thac0(self, class_levels) -> int | None:
        """The DOS table's best row among the classes the character has.

        The record stores `60 - THAC0`; this returns the THAC0 itself. None
        where the title's DOS table is unread or the character has no class
        with a level, which is what `GAME.OVR:0x1A659` leaves as the zero it
        started from.

        **Not what the DOS engine leaves in the byte**, and the difference is
        one point for a Curse or Silver Blades magic-user at levels 1-5:
        the engine's own loop holds him to THAC0 20 or better, and
        :meth:`dos_engine_thac0`, which applies that, is what a writer into DOS
        stores.
        """
        best = None
        for name, level in dict(class_levels or {}).items():
            if not level:
                continue
            got = self.dos_thac0_at(name, level)
            if got is not None:
                best = got if best is None else min(best, got)
        return best

    def dos_engine_thac0(self, class_levels) -> int | None:
        """What the **DOS engine's own recompute** leaves in `thac0_base`.

        The record stores `60 - THAC0`; this returns the THAC0 itself. The loop
        that runs when a party loads walks every class slot without testing
        whether the level is zero, so a class the character has no level in
        contributes its row's entry 0 (:attr:`dos_thac0_level0`). That holds
        the result to THAC0 20 or better, which :meth:`dos_base_thac0` -- the best of the
        classes the character has -- does not: a Curse or Silver Blades
        magic-user of level 1-5 is 21 there and 20 here.

        None where the title's DOS table is unread or the character has no
        class with a level, so a caller can keep the source's own byte.
        `docs/224-the-dos-thac0-floor.md` has the listing;
        `tools/records/thac0census.py`'s `dos_engine_thac0` is the rule written
        out over the player's own tables and `tests/convert/test_dosthac0floor.py`
        compares the two.
        """
        best = self.dos_base_thac0(class_levels)
        if best is None or not self.dos_thac0_level0:
            return None
        held = dict(class_levels or {})
        for name, entry0 in self.dos_thac0_level0:
            if not held.get(name):
                best = min(best, entry0)
        return best

    def base_thac0(self, class_levels) -> int | None:
        """`thac0_base` as **this title's C64 engine** computes it, best of
        the classes -- the mirror of :meth:`dos_base_thac0`, over `self.classes`
        rather than `self.dos_thac0`.

        `GEN $1EF3` clears the byte, walks the per-class level array at
        `0x0C9` and keeps the best row; this is that recompute, and it is
        CONFIRMED for all three titles' C64 sides (`self.classes` is read
        off each title's own `GEN`). A level past this title's own table
        contributes nothing, the same floor :meth:`saving_throws` applies --
        a character cannot hold a level the game itself never lets him
        reach. None where no class has a level the table reaches, which is
        what the C64 engine leaves as the zero it started from.

        `#366 (A converted magic-user or thief arrives with the other
        port's THAC0, because the two ports ship different tables and the
        conversion copies the byte)`: DOS's magic-user rows 1-5 and thief
        rows 1-4 hold one worse than this table's, so a value copied
        straight from a DOS source is the wrong port's number.
        """
        rows = [self.at_level(name, max(int(level), 1))
                for name, level in dict(class_levels or {}).items() if level]
        best = [row.thac0 for row in rows if row is not None]
        return min(best) if best else None

    def clamp_threshold(self, class_name: str, level: int) -> int | None:
        """What `GEN $23D4` reads for a class at that level, ceiling included."""
        want = self.at_level(class_name, level + 1)
        if want is not None:
            return want.experience
        if level == self.ceiling(class_name):
            return dict(self.clamp_thresholds).get(class_name)
        return None

    def turning_level(self, cleric_level: int,
                      paladin_level: int = 0) -> int | None:
        """What `0x0A4` holds, or None where this title has no answer.

        **Pool of Radiance never writes the byte for a non-cleric**: `GEN
        $2388` is `LDX level_cleric / BEQ` straight to the `RTS`, so None here
        means "leave it alone" rather than "zero".

        **Curse writes it for everybody**, `$113F` ending in an unconditional
        `STA $7CA4`, and a paladin turns as a cleric `paladin_turn_offset`
        levels weaker -- so a title with that offset answers 0 for a character
        who turns nothing, which is the byte the game stores.
        """
        if not self.turn_power:
            return None
        effective = int(cleric_level or 0)
        if self.paladin_turn_offset is not None:
            effective = max(effective,
                            int(paladin_level or 0) - self.paladin_turn_offset)
            if effective <= 0:
                return 0
        elif not effective:
            return None
        level = max(1, min(effective, len(self.turn_power)))
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

        **A class whose level is zero is not a class.**  Pool of Radiance's
        `GEN $1F44` fills all five columns with 20, then walks the four-slot
        array at `0x0C9` from slot 3 down to slot 0 and `$1F57 BEQ $1F9B`
        branches straight past any slot holding zero; only a slot with a level
        reaches the row lookup and the per-column minimum at `$1F8D`.  Until
        `#527 (A DOS import combines saving throws from classes the character
        does not have)` this read `max(int(level), 1)` and turned every unused
        slot into a level-1 class, so a record arriving with the whole
        eight-slot array -- which is what `goldbox.dos_codec.to_neutral`
        builds, zeros and all -- came out holding the field-wise best of
        magic-user, cleric, thief and fighter at level 1.  A human fighter 3
        stored `10 12 11 15 12` instead of `13 14 15 16 16`.
        `LevelTables.base_thac0` has read `GEN $1EF3`'s equivalent walk
        correctly since it was written; this method was the outlier.

        One deliberate divergence from `$1F44` remains: where no class has a
        level the engine leaves all five columns at 20 and this answers None,
        which every caller reads as "write nothing".  Writing 20 over a row we
        could not compute would be worse than leaving the stored one alone.
        A title whose `saving_throw_rule_read` is False answers None for the
        same reason, whatever the levels.

        Where `paladin_save_after_best` is set, fighter, paladin and ranger
        are folded into one fighter row at the best of those three levels
        before the column-wise best is taken across classes, and the
        paladin's -2 is subtracted from that best afterwards -- see the
        field's own docstring. Pool of Radiance leaves the flag False and
        this method behaves exactly as it always has.
        """
        if not self.saving_throw_rule_read:
            return None
        levels = {name: int(level) for name, level in dict(class_levels).items()
                  if int(level)}
        if not levels:
            return None
        if self.paladin_save_after_best:
            fighter_group = ("fighter", "paladin", "ranger")
            group_level = max((levels[name] for name in fighter_group
                               if name in levels), default=0)
            rows = []
            if group_level:
                row = self.at_level("fighter", group_level)
                if row is not None:
                    rows.append(row.saves)
            rows += [row.saves for row in
                     (self.at_level(name, level)
                      for name, level in levels.items()
                      if name not in fighter_group)
                     if row is not None]
            if not rows:
                return None
            best = [min(row[column] for row in rows) for column in range(5)]
            if levels.get("paladin"):
                best = [max(0, v - 2) for v in best]
            if race in self.sturdy_races:
                bonus = constitution_save_bonus(constitution)
                for column in self.constitution_save_columns:
                    best[column] = max(0, best[column] - bonus)
            return tuple(best)
        rows = [row.saves for row in
                (self.at_level(name, level)
                 for name, level in levels.items())
                if row is not None]
        if not rows:
            return None
        best = [min(row[column] for row in rows) for column in range(5)]
        if race in self.sturdy_races:
            bonus = constitution_save_bonus(constitution)
            for column in self.constitution_save_columns:
                best[column] -= bonus
        return tuple(best)

    def dos_engine_saving_throws(self, class_levels, race: int = 0,
                                 constitution: int = 0,
                                 bonus_item: bool = False,
                                 former_levels=None,
                                 ) -> tuple[int, ...] | None:
        """The five saves the DOS engine's own load-time rebuild leaves in the
        record.

        Curse's `GAME.OVR:0x3B45B` and Silver Blades' `0x3C644`: each column
        starts at 20, then for every class slot with a level in
        `class_levels` the column is lowered to that class's row in the DOS
        table (Curse `DS:0x45BE`, Silver Blades `DS:0x5592`), with
        :attr:`dos_save_overrides` standing in for the cells the DOS table
        holds differently from the C64's. A regained class contributes
        nothing -- the caller is expected to have zeroed its current slot. A
        class this title's table has no row for contributes nothing either.

        After the loop, :attr:`dos_save_trailing_slot` names the one slot
        compared again: if its level in `class_levels` is above its level in
        `former_levels`, the columns are lowered to the cell at the former
        level. That is how a Silver Blades thief who never left the class
        gets the thief "level 0" cell, magic-user level 18's `10 7 5 9 6`.

        Column 0 alone then takes two more additions, both from the
        constitution score at the in-force byte `0x019`:

        * a race in :attr:`dos_save_constitution_races`, or a character
          wearing an item whose readied power counts as a constitution
          booster (`bonus_item`), adds a step that runs 4-6 +1, 7-10 +2,
          11-13 +3, 14-17 +4, 18 +5;
        * every race then adds another step for constitution 19-20 (+1),
          21-22 (+2), 23-24 (+3) and 25 (+4).

        None where :attr:`dos_save_rule_read` is False, or no class in
        `class_levels` has both a level and a row this title's table reaches.
        """
        if not self.dos_save_rule_read:
            return None
        overrides = dict(self.dos_save_overrides)

        def row_at(name, level):
            row = overrides.get((name, level))
            if row is None and level:
                entry = self.at_level(name, level)
                row = entry.saves if entry is not None else None
            return row

        best = [20, 20, 20, 20, 20]
        found = False
        levels_now = dict(class_levels or {})
        for name, level in levels_now.items():
            level = int(level or 0)
            if not level:
                continue
            row = row_at(name, level)
            if row is None:
                continue
            found = True
            best = [min(best[i], row[i]) for i in range(5)]
        if not found:
            return None
        trailing = self.dos_save_trailing_slot
        if trailing is not None:
            now = int(levels_now.get(trailing) or 0)
            was = int(dict(former_levels or {}).get(trailing) or 0)
            row = row_at(trailing, was) if now > was else None
            if row is not None:
                best = [min(best[i], row[i]) for i in range(5)]
        con = int(constitution or 0)
        if race in self.dos_save_constitution_races or bonus_item:
            best[0] += _dos_con_save_racial_step(con)
        best[0] += _dos_con_save_high_step(con)
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
    dos_thief_skill_race=_DOS_THIEF_SKILL_RACE_POOL,
    dos_thief_skill_dexterity=_DOS_THIEF_SKILL_DEX_POOL,
    dos_thief_skill_dexterity_from=DOS_THIEF_SKILL_DEX_FROM_POOL,
    turn_power=_TURN_POWER_POOL,
    clamp_thresholds=(("magic-user", 60001), ("cleric", 55001),
                      ("thief", 160001), ("fighter", 250001)),
    dos_thac0=_DOS_THAC0_POOL,
    dos_thac0_level0=_DOS_THAC0_LEVEL0_POOL,
    dos_wisdom_bonus_from=13,
)

#: `DS:0x3E3A`, 8 rows of 13, transcribed from `tools/c64/laterthac0.py table
#: --title curse-of-the-azure-bonds`. THAC0, not the stored `60 - THAC0`,
#: level 1 first. See `_DOS_THAC0_POOL`'s docstring for the grades and the
#: sweep this reproduces (77 of 86).
_DOS_THAC0_CURSE = (
    ("cleric",     (20, 20, 20, 18, 18, 18, 16, 16, 16, 14, 14, 14)),
    ("fighter",    (20, 20, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9)),
    ("paladin",    (20, 20, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9)),
    ("ranger",     (20, 20, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9)),
    ("magic-user", (21, 21, 21, 21, 21, 19, 19, 19, 19, 19, 17, 17)),
    ("thief",      (20, 20, 20, 20, 19, 19, 19, 19, 16, 16, 16, 16)),
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
    thief_skills=_THIEF_SKILLS_CURSE,
    thief_skill_race=_THIEF_SKILL_RACE_CURSE,
    thief_skill_dexterity=_THIEF_SKILL_DEX_CURSE,
    thief_skill_dexterity_from=THIEF_SKILL_DEX_FROM_CURSE,
    turn_power=_TURN_POWER_CURSE,
    paladin_turn_offset=2,
    hp_bonus_by_score=_HP_BONUS_CURSE,
    hp_bonus_score_cap=HP_BONUS_SCORE_CAP_CURSE,
    hp_bonus_uncapped_from=HP_BONUS_UNCAPPED_FROM_CURSE,
    wisdom_bonus_level=_WISDOM_BONUS_CURSE,
    wisdom_bonus_from=WISDOM_BONUS_FROM_CURSE,
    hit_die_rolls=2,
    hit_die_fighter_floor=None,
    hit_die_divide_floor=0,
    hit_die_divide_round_up_on_tie=False,
    trains_all_ready_classes=True,
    attack_forms_overwritten=True,
    stores_spell_capacity=False,
    #: `GEN $136E`, entry thirteen of each class's own row -- the same table
    #: the 78 thresholds above came from, read one past each ceiling. They are
    #: Silver Blades' *next* thresholds, measured separately off another file.
    clamp_thresholds=(("magic-user", 750001), ("cleric", 675001),
                      ("thief", 660001), ("fighter", 1250001),
                      ("paladin", 1400001), ("ranger", 975001)),
    dos_thac0=_DOS_THAC0_CURSE,
    dos_thac0_level0=_DOS_THAC0_LEVEL0_CURSE,
    paladin_save_after_best=True,   # `GEN $0E5E`/`$0F01`
    dos_save_overrides=(
        (("paladin", 5), (9, 9, 11, 11, 12)),
        (("paladin", 6), (9, 9, 11, 11, 12)),
        (("paladin", 8), (9, 9, 10, 10, 11)),
    ),
    dos_save_rule_read=True,
    dos_save_constitution_races=(1, 5),     # `0x3B63A`: dwarf, halfling
)

#: `DS:0x4C0C`, 7 rows of 19 -- no monk -- transcribed from
#: `tools/c64/laterthac0.py table --title secret-of-the-silver-blades`. THAC0, not
#: the stored `60 - THAC0`, level 1 first. See `_DOS_THAC0_POOL`'s docstring
#: for the grades and the sweep this reproduces (72 of 74).
_DOS_THAC0_SSB = (
    ("cleric",     (20, 20, 20, 18, 18, 18, 16, 16, 16, 14, 14, 14, 12, 12,
                    12, 10, 10, 10)),
    ("fighter",    (20, 20, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6,
                    5, 4, 3)),
    ("paladin",    (20, 20, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6,
                    5, 4, 3)),
    ("ranger",     (20, 20, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6,
                    5, 4, 3)),
    ("magic-user", (21, 21, 21, 21, 21, 19, 19, 19, 19, 19, 17, 17, 17, 17,
                    17, 14, 14, 14)),
    ("thief",      (20, 20, 20, 20, 19, 19, 19, 19, 16, 16, 16, 16, 14, 14,
                    14, 14, 12, 12)),
)

#: Race 3 is the dwarf in this title (`c64_port.RACES_SILVER_BLADES`), not the
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
    thief_skills=_THIEF_SKILLS_SSB,
    thief_skill_race=_THIEF_SKILL_RACE_SSB,
    thief_skill_race_index_from=0,   # `$124D` has no decrement -- see the field
    thief_skill_dexterity=_THIEF_SKILL_DEX_SSB,
    thief_skill_dexterity_from=THIEF_SKILL_DEX_FROM_CURSE,
    hp_bonus_by_score=_HP_BONUS_SSB,
    hp_bonus_score_cap=HP_BONUS_SCORE_CAP_CURSE,
    hp_bonus_uncapped_from=HP_BONUS_UNCAPPED_FROM_CURSE,
    wisdom_bonus_level=_WISDOM_BONUS_SSB,
    wisdom_bonus_from=WISDOM_BONUS_FROM_CURSE,
    turn_power=_TURN_POWER_SILVER,
    paladin_turn_offset=2,      # `$13A5 LDA level_paladin / SEC / SBC #$02`
    #: The remaining seven, read off `SILVER*.D64`'s own `GEN` for `#89` on
    #: 2026-09-05: `$1808` is Curse's `$15E1` instruction for instruction (the
    #: hit die, two rolls kept the higher); `$0D96` is Curse's `$11AB` byte for
    #: byte, sharing the remainder byte `$7F3F` (the divide, no floor, the
    #: same round-up-at-random #18 grades PROBABLE in both titles); `$156F`
    #: walks class slots 7 down to 0 in one press, Curse's `$14F8` shape;
    #: `$13EB STY $7CD9` stores outright, Curse's `$1909` shape; and
    #: `tools/c64/absrefsweep.py secret-of-the-silver-blades 7CEE 7CF3` over 347
    #: files finds no reference to `spells_castable`, Curse's own census result.
    #: So Silver Blades takes Curse's values on all seven, not Pool of
    #: Radiance's defaults.
    hit_die_rolls=2,
    hit_die_fighter_floor=None,
    hit_die_divide_floor=0,
    hit_die_divide_round_up_on_tie=False,
    trains_all_ready_classes=True,
    attack_forms_overwritten=True,
    stores_spell_capacity=False,
    dos_thac0=_DOS_THAC0_SSB,
    dos_thac0_level0=_DOS_THAC0_LEVEL0_SSB,
    paladin_save_after_best=True,   # `$10A2`/`$11C0`
    #: `GAME.OVR:0x3C644` (`164:34`) reads `DS:0x5592`, 7 classes of 18
    #: levels indexed `slot * 90 + level * 5`. Its cells are the C64's rows
    #: except Curse's same three paladin cells, and the thief's level-0 cell
    #: -- which is magic-user level 18's row -- that the trailing thief
    #: comparison reads (`tests/secret_of_the_silver_blades/
    #: test_ssbdossaves.py` re-reads all of them off `START.EXE`).
    dos_save_overrides=(
        (("paladin", 5), (9, 9, 11, 11, 12)),
        (("paladin", 6), (9, 9, 11, 11, 12)),
        (("paladin", 8), (9, 9, 10, 10, 11)),
        (("thief", 0), (10, 7, 5, 9, 6)),
    ),
    dos_save_rule_read=True,
    dos_save_trailing_slot="thief",     # `0x3C768`
)

# --- Pools of Darkness --------------------------------------------------------
# DOS only: the title never shipped on the C64. Every number below is read out
# of the player's own `GAME.OVR` and the expanded `GAME.EXE` by
# `tools/dos/dospodlevels.py`, which finds each table through the instruction
# that indexes it, and `tests/records/test_pod_levels.py` reads them back off
# the disk. The engine numbers its classes cleric 0, druid 1, fighter 2,
# paladin 3, ranger 4, magic-user 5, thief 6; every table is indexed that way.
#
# The authority for every number is the instruction that reads it. As a
# check on the reading -- strides, clamps, the dual-class level -- THAC0
# (`0xAC`), the five saves (`0x132`) and `attack_forms` (`0x168`) recompute
# from these rows for 12 of the 12 records under the archive install's
# `SAVE` directory (`dospodlevels.py check`). Those records were found, not
# watched being written, so they corroborate the reader and prove nothing
# about the game on their own.

#: `GAME.OVR:0x039349` answers a threshold by class and level: levels 2-11 out
#: of `DS:71AE + class * 0x12D + level * 4`, and from 12 on entry 11 plus
#: `DS:6EDB[class]` for every level past 11. **Level 41 and above answer
#: 0x7FFFFFFF**, so no class goes past 40 by experience. Entries 0 and 1 of
#: each row overlap the neighbouring tables' bytes and are never a threshold;
#: level 1's 0 is the definition of a new character, not a read.
#:
#: Two readings differ from Curse and Silver Blades: the ranger's second level
#: is 2251 (Curse 2250), and the paladin's and ranger's eleventh are 1050000
#: and 650000 -- one short of Curse's 1050001 and 650001, which carries into
#: every threshold past it (paladin 12 is 1400000, Silver Blades 1400001).
#: The fighter's eleventh is 750001, not Curse's 749937. Druid's row holds
#: 0xFFFFFFFF throughout: a druid in this engine never earns a level.
_XP_POD = {
    "cleric": ((1501, 3001, 6001, 13001, 27501, 55001, 110001, 225001,
                450001, 675001), 225000),
    "fighter": ((2001, 4001, 8001, 18001, 35001, 70001, 125001, 250001,
                 500001, 750001), 250000),
    "paladin": ((2751, 5501, 12001, 24001, 45001, 95001, 175001, 350001,
                 700001, 1050000), 350000),
    "ranger": ((2251, 4501, 10001, 20001, 40001, 90001, 150001, 225001,
                325001, 650000), 325000),
    "magic-user": ((2501, 5001, 10001, 22501, 40001, 60001, 90001, 135001,
                    250001, 375001), 375000),
    "thief": ((1251, 2501, 5001, 10001, 20001, 42501, 70001, 110001, 160001,
               220001), 220000),
}
#: The last level `0x039349` gives a threshold for (`cmp byte ptr [bp+8],
#: 0x29 / jae` returns 0x7FFFFFFF). Not a class ceiling: the racial and class
#: limits the trainer applies are unread, which is why `ceilings` is empty.
POD_LAST_LEVEL = 40

#: `GAME.OVR:0x03836D` clamps every class level at 21 (`cmp byte ptr [bp-4],
#: 0x15`) before it reads THAC0, and `0x0387B0` clamps the same way before it
#: reads a save row, so level 22 and above answer level 21's rows.
POD_TABLE_CLAMP = 21

#: `DS:6D18 + class * 22 + level`, as THAC0 rather than the stored
#: `60 - THAC0`, levels 1 to 21; entry 0 is `_DOS_THAC0_LEVEL0_POD`. The
#: recompute keeps the best over all seven class slots without testing the
#: level, the loop `dos_engine_thac0` reproduces. A magic-user of level 1-5 is
#: 20 here, as in DOS Pool of Radiance and not 21 as in Curse, and the fighter
#: group improves two points every two levels -- AD&D 1st edition's table,
#: not Curse's `21 - level`.
_DOS_THAC0_POD = (
    ("cleric",     (20, 20, 20, 18, 18, 18, 16, 16, 16, 14, 14, 14, 12, 12,
                    12, 10, 10, 10, 9, 9, 9)),
    ("fighter",    (20, 20, 18, 18, 16, 16, 14, 14, 12, 12, 10, 10, 8, 8, 6,
                    6, 4, 4, 4, 4, 4)),
    ("paladin",    (20, 20, 18, 18, 16, 16, 14, 14, 12, 12, 10, 10, 8, 8, 6,
                    6, 4, 4, 4, 4, 4)),
    ("ranger",     (20, 20, 18, 18, 16, 16, 14, 14, 12, 12, 10, 10, 8, 8, 6,
                    6, 4, 4, 4, 4, 4)),
    ("magic-user", (20, 20, 20, 20, 20, 19, 19, 19, 19, 19, 16, 16, 16, 16,
                    16, 13, 13, 13, 13, 13, 11)),
    ("thief",      (20, 20, 20, 20, 19, 19, 19, 19, 16, 16, 16, 16, 14, 14,
                    14, 14, 12, 12, 12, 12, 10)),
)
#: Entry 0 of each of the seven rows, in class-number order: Silver Blades'
#: seven numbers exactly.
_DOS_THAC0_LEVEL0_POD = _DOS_THAC0_LEVEL0_SSB

#: `DS:79FA + class * 105 + level * 5 + column`, by the last level of each
#: band, levels 1 to 21. Three bands are not the AD&D table and are the
#: engine's own bytes, read at the index the routine computes: a paladin 5-6
#: stores 9 rather than 10 for petrification and a paladin 8 stores 9 rather
#: than 8 for poison, a thief 19 reverts to the thief 13-16 row, and a cleric
#: keeps the 16th-level row to 19 where AD&D improves it at 19. No record
#: read here holds a character at any of those levels.
_SAVES_POD = {
    "cleric": ((3, (10, 13, 14, 16, 15)), (6, (9, 12, 13, 15, 14)),
               (9, (7, 10, 11, 13, 12)), (12, (6, 9, 10, 12, 11)),
               (15, (5, 8, 9, 11, 10)), (19, (4, 7, 8, 10, 9)),
               (21, (2, 5, 6, 8, 7))),
    "fighter": _SAVES_FIGHTER_SSB[:-1] + ((16, (4, 5, 6, 4, 7)),
                                          (21, (3, 4, 5, 4, 6))),
    "paladin": ((2, (12, 13, 14, 15, 15)), (4, (11, 12, 13, 14, 14)),
                (6, (9, 9, 11, 11, 12)), (7, (8, 9, 10, 10, 11)),
                (8, (9, 9, 10, 10, 11)), (10, (6, 7, 8, 7, 9)),
                (12, (5, 6, 7, 6, 8)), (14, (3, 4, 5, 3, 6)),
                (16, (2, 3, 4, 2, 5)), (21, (1, 2, 3, 2, 4))),
    "magic-user": _SAVES_MAGIC_USER + ((20, (10, 7, 5, 9, 6)),
                                       (21, (8, 5, 3, 7, 4))),
    "thief": _SAVES_THIEF_SSB[:-1] + ((18, (9, 8, 6, 12, 7)),
                                      (19, (10, 9, 8, 13, 9)),
                                      (20, (9, 8, 6, 12, 7)),
                                      (21, (8, 7, 4, 11, 5))),
}
_SAVES_POD["ranger"] = _SAVES_POD["fighter"]

#: `GAME.OVR:0x026F4B`: `(sides, last level that rolls, flat a level after,
#: dice at level 1)`. The sides are `DS:6DD7[class]`; a class rolls while its
#: level is below `DS:6DC9[class]`, `DS:6DD0[class]` dice at level 1 (2 for
#: the ranger, 1 for everyone else) and one a level after; past that the flat
#: amount is set in code by class number. Every die is rolled twice and the
#: higher kept, Curse's rule.
_HIT_DICE_POD = {
    "cleric": (8, 9, 2, 1),
    "fighter": (10, 9, 3, 1),
    "paladin": (10, 9, 3, 1),
    "ranger": (8, 10, 2, 2),
    "magic-user": (4, 11, 1, 1),
    "thief": (6, 10, 2, 1),
}

#: The loop in `0x03836D` that writes `attack_forms` at `0x168`: 3 (3/2,
#: doubled) above fighter or paladin 6 and 4 above 12; the ranger's bands are
#: 7 and 14. Silver Blades' bands exactly. It writes nothing for any other
#: class, and 4 of 4 records here without a fighter-group class hold 2.
_ATTACKS_POD = {"fighter": _ATTACKS_FIGHTER_SSB,
                "paladin": _ATTACKS_FIGHTER_SSB,
                "ranger": _ATTACKS_RANGER_SSB}

#: `GAME.OVR:0x026ECC` (and its copy at `0x01848C`): `DS:719C[constitution]`,
#: signed, plus for class numbers 2, 3 and 4 -- fighter, paladin, ranger -- 1
#: at 17, 2 at 18, 3 at 19-20, 4 at 21-23 and 5 at 24-25, written in code.
#: Laid out as Curse's row (the uncapped sum) with the score clamped at 16 for
#: everyone else, which gives the table's own +2 from 16 up. It is Curse's
#: `_HP_BONUS_CURSE` from 3 up; entries 1 and 2 read 0 and entry 0 is the
#: preceding table's byte, all three below any race's minimum.
_HP_BONUS_POD = (8, 0, 0, -2, -1, -1, -1, 0, 0, 0, 0, 0, 0, 0, 0,
                 1, 2, 3, 4, 5, 5, 6, 6, 6, 7, 7)

#: The cleric helper's six compares (`GAME.OVR:0x03860C`): wisdom above 12,
#: 13, 14, 15, 16 and 17 each add one slot at cleric spell levels 1, 1, 2, 2,
#: 3 and 4 -- read by `tools/dos/dospodtables.py` and
#: `docs/228-pools-of-darkness-spells-and-creation.md`. Curse's
#: `_WISDOM_BONUS_CURSE` less its seventh entry: there is no compare above
#: 17, so wisdom 19 gives what 18 gives.
_WISDOM_BONUS_POD = (0, 0, 1, 1, 2, 3)


def _pod_progression(name: str) -> tuple[Level, ...]:
    """One class's rows, level 1 to `POD_LAST_LEVEL`, out of the tables above.

    `spells` is left empty: `goldbox.spells.POOLS_OF_DARKNESS` carries this
    title's slot rows, nine wide and read off the same engine.
    """
    direct, step = _XP_POD[name]
    thac0 = dict(_DOS_THAC0_POD)[name]
    die, roll_to, flat, first = _HIT_DICE_POD[name]
    rows = []
    for level in range(1, POD_LAST_LEVEL + 1):
        if level == 1:
            experience = 0
        elif level <= len(direct) + 1:
            experience = direct[level - 2]
        else:
            experience = direct[-1] + step * (level - len(direct) - 1)
        dice = min(level, roll_to) + first - 1
        extra = (level - roll_to) * flat if level > roll_to else 0
        at = min(level, POD_TABLE_CLAMP)
        rows.append(Level(
            level=level,
            experience=experience,
            hit_dice=f"{dice}d{die}" + (f"+{extra}" if extra else ""),
            thac0=thac0[at - 1],
            attacks=_band(_ATTACKS_POD.get(name, ((99, 1),)), level),
            saves=_band(_SAVES_POD[name], at),
        ))
    return tuple(rows)


#: **What this entry does not carry, and what each lookup answers instead:**
#:
#: * `ceilings` and `racial_limits` are unread, so `ceiling` and
#:   `racial_limit` answer None;
#: * the thief skill tables (the routine is near `GAME.OVR:0x038A4F`) are
#:   unread, so `thief_skill_row` answers None;
#: * `turn_power` is empty and `turning_level` answers None -- the DOS record
#:   keeps no caster-side turning byte (`goldbox.derive.turning_level`);
#: * `saving_throws` answers None: after the class rows, `0x0387B0` adjusts
#:   column 0 alone by constitution -- from 19 up for everyone, and by a
#:   banded amount from 4 up when a walk of the item list finds a flag --
#:   and that rule is not read closely enough to reproduce
#:   (`saving_throw_rule_read`);
#: * the trainer's own rules -- whether one press raises every ready class,
#:   the divide's round-up (`0x027084` divides and floors at 1 with no
#:   round-up at all, which neither setting of
#:   `hit_die_divide_round_up_on_tie` says), whether `attack_forms` is
#:   overwritten -- keep the defaults, and `trainer_measured` is False, so
#:   `goldbox/levelup.py` refuses the title before it reads any of them.
#:
#: `class_order` is the layout Curse and Silver Blades share. This title has
#: no C64 record for it to describe; it is there so that `class_slot` and
#: `hp_bonus_uncapped_from=3` mean what they mean in Curse, which is the
#: fighter, paladin and ranger -- the three classes `0x026ECC` pays more.
POOLS_OF_DARKNESS = LevelTables(
    key="pools-of-darkness",
    title="Pools of Darkness",
    class_order=("magic-user", "cleric", "thief", "fighter",
                 None, None, "paladin", "ranger"),
    classes=tuple((name, _pod_progression(name))
                  for name in ("magic-user", "cleric", "thief", "fighter",
                               "paladin", "ranger")),
    ceilings=(),
    racial_limits=(),
    constitution_save_columns=(),
    sturdy_races=(),
    saving_throw_rule_read=False,
    hp_bonus_by_score=_HP_BONUS_POD,
    hp_bonus_score_cap=HP_BONUS_SCORE_CAP_CURSE,
    hp_bonus_uncapped_from=HP_BONUS_UNCAPPED_FROM_CURSE,
    wisdom_bonus_level=_WISDOM_BONUS_POD,
    wisdom_bonus_from=WISDOM_BONUS_FROM_CURSE,
    hit_die_rolls=2,
    hit_die_fighter_floor=None,     # no `cmp 4` in `0x026F4B`'s class loop
    hit_die_divide_floor=1,         # `0x027084 cmp byte ptr [bp-3], 1 / jae`
    #: The slot builder `GAME.OVR:0x03808A` writes the record's own three
    #: nine-byte arrays (`docs/228-pools-of-darkness-spells-and-creation.md`).
    stores_spell_capacity=True,
    dos_thac0=_DOS_THAC0_POD,
    dos_thac0_level0=_DOS_THAC0_LEVEL0_POD,
)

TITLES: tuple[LevelTables, ...] = (POOL_OF_RADIANCE, CURSE_OF_THE_AZURE_BONDS,
                                   SECRET_OF_THE_SILVER_BLADES)

#: Titles with an entry of their own whose ceilings and racial limits are
#: unread, kept out of `TITLES` because the checks that loop it hold every
#: title's rows to its ceilings and its class order to a C64 record. Every
#: lookup against them answers from their own tables or answers None.
PARTLY_READ: tuple[LevelTables, ...] = (POOLS_OF_DARKNESS,)

BY_KEY = {t.key: t for t in TITLES + PARTLY_READ}

#: What a caller gets when it says nothing. Every caller predates the second
#: game and means this one.
DEFAULT = POOL_OF_RADIANCE

#: The titles whose **trainer** has been read. A stricter claim than having a
#: table, and the distinction is the whole of issue #18: Curse's level tables
#: went into this module before its trainer was proven, and the table alone
#: was not enough to level a Curse character.
#:
#: **Curse's own copies were located, read and written into this module**
#: (`tests/curse_of_the_azure_bonds/test_cursetrainer.py` and `tests/curse_of_the_azure_bonds/test_curselevels.py`), and
#: `goldbox/levelup.py` was taught every rule of Curse's that is not Pool of
#: Radiance's. **Five Curse trainings were driven and diffed on 2026-09-05**,
#: and 75 derived fields plus 5 spellbooks came back out of this module and
#: `goldbox/levelup.py` with no mismatches. What was then still open --
#: `goldbox/levelup.py` reading `hit_die_divide_round_up_on_tie`/
#: `divide_rounds_up` and `trains_all_ready_classes` from this module without
#: acting on either -- is closed inside that module: `divide_between_classes`
#: asks `divide_rounds_up` for the round-up rule, and the new `plan_all` raises
#: every ready class in the engine's own slot order, both proven against the
#: same two specimens that measured them, `WISH-SPEC-curse-train-input` and
#: `WISH-SPEC-curse-trained-party`
#: (`test_plan_all_raises_travis_and_ledera_in_the_engines_own_order`).
#:
#: **Curse gained this set on `#415` (automap/window.py picks the level-up
#: spell dialog's class the same wrong way plan would have, blocking Curse's
#: trainer), the third and last place the wrong-first answer reached.**
#: `automap/actions.py`'s `LevelUp.run` asks `trains_all_ready_classes` and
#: calls `plan_all` for a title that has it, rather than `plan` with no class
#: named -- which fell to `best_next_class`, a rule built for Pool of
#: Radiance's one-class-a-press design. Asked of TRAVIS (thief 5 / fighter 4)
#: and LEDERA (magic-user 4 / fighter 4), the two characters the engine
#: trained on 2026-09-05, `best_next_class` answers "thief" and "magic-user"
#: -- the *opposite* of `$14F8`'s own fighter-first walk for both -- and
#: `LevelUp.run` no longer asks it: `plan_all` walks `ready_classes` itself,
#: in the engine's own order, proven against both specimens through the
#: action rather than through `plan_all` directly
#: (`tests/curse_of_the_azure_bonds/test_cursetrainer.py::test_a_curse_level_up_action_raises_travis_and_ledera_through_plan_all`).
#:
#: **The remaining gap was one file further over, in `automap/window.py`.**
#: `AutomapBinding._level_up` used to decide, *before* calling `run`, whether
#: to open the spell-choice dialog by asking `LevelUp.class_for` -- `best_class`,
#: the same wrong-first answer above -- for a single "primary" class. If that
#: class was not the magic-user, and the magic-user was one of the classes
#: `plan_all` would raise this visit, no dialog opened and `run` then reached
#: `plan`'s own magic-user step with `learn=None`, found spells on offer, and
#: refused with "picks one new spell", which nothing had shown a menu for --
#: watched happening on a magic-user 1 / fighter 2 character carrying only
#: 4,001 experience, where `best_class` names the fighter (its post-level
#: threshold, 4,001, beats the magic-user's 2,501) while `$14F8` still trains
#: both this visit
#: (`tests/curse_of_the_azure_bonds/test_cursetrainer.py::test_the_level_up_button_asks_for_a_spell_through_the_window_when_class_for_would_have_named_the_fighter`).
#: **`_level_up` now gates on `LevelUp.offers`** -- which itself now asks
#: `ready_classes` rather than `best_class` for a `trains_all_ready_classes`
#: title, answering "is the magic-user one of the classes this visit trains"
#: correctly for both shapes of trainer -- instead of `class_for`'s single
#: answer.
#:
#: One of the readings behind Curse's tables is PROBABLE rather than
#: CONFIRMED -- the double hit-die roll at `$15FC`, because a roll leaves no
#: trace in a record and the bytecode is the whole of its evidence. The module
#: docstring's grade table says why. It did not hold Curse out of this set;
#: the `automap/window.py` gap above did.
#:
#: **Left open by `#415`, and not this set's concern**: the confirmation
#: dialog `_level_up` shows before a press that would cost an already-earned
#: level still previews one training step (`LevelUp.preview`, still `plan`
#: rather than `plan_all`), not the whole chain a `trains_all_ready_classes`
#: title's trainer runs in one visit. No specimen on hand shows it actually
#: disagreeing with the chain, and the fix needs wording for a press that
#: raises several classes at once, which is not this module's or that
#: ticket's to write -- see `#418 (The level-up confirmation dialog previews
#: one step of a Curse dual-training press, not the whole chain)`.
#:
#: **Silver Blades joined on 2026-09-16, and a driven session is what put it
#: here.** All the trainer inputs `#89 (Silver Blades' trainer grants spells
#: from a table, and goldbox/levelup.py offers them from a menu)` was calling
#: unread or unattributed had already reached
#: `SECRET_OF_THE_SILVER_BLADES`, CONFIRMED: the
#: constitution hit-point bonus and the thief dexterity and wisdom rows are
#: Curse's own bytes at different addresses; the thief level rows share their
#: first 72 bytes with Curse and Pool of Radiance and add eight of Silver
#: Blades' own; the thief racial row is read at `race * 8` with **no**
#: decrement (`thief_skill_race_index_from=0`), a bug in the shipped game
#: (`goldbox-bugs.md` entry 13) that MALACHITE's own trained record
#: corroborates on all eight columns, twice; and the seven remaining fields
#: (the hit die, its divide, whether one press raises every ready class,
#: whether `attack_forms` and `spells_castable` are written outright) are all
#: read byte-identical to Curse's own routines. Its **turning table is read**
#: too, at `GEN $13A5` (#288), CONFIRMED against DOMINIC and GUY DE VALOIS.
#:
#: **What had never happened was the press.** `#89`'s own 2026-09-08 comment
#: named two blockers and both are closed. The `automap/window.py`
#: spell-dialog gate `#415 (automap/window.py picks the level-up spell
#: dialog's class the same wrong way plan would have, blocking Curse's
#: trainer)` closed for Curse needed no second fix here: `LevelUp.offers`
#: branches on `trains_all_ready_classes`, which this title has set, so it
#: takes Curse's own branch by construction --
#: `tests/secret_of_the_silver_blades/test_ssbtrainer.py::test_the_level_up_button_asks_for_a_spell_through_the_window`
#: drives it through the window all the same. And the training was driven:
#: **fourteen presses over two boots, 2026-09-16**, on SSI's shipped party off
#: `SILVER-6.D64` with the hall opened by poking `$7EA8` to `$7F`, covering
#: every class this trainer has a spell step for -- DOMINIC cleric 8 to 9 and
#: 10 to 11 at both sides of the `$0F35` Wisdom gate, MORGAINE magic-user
#: 10 to 11, 11 to 12, 12 to 13 and 13 to 14 at four permanent intelligences,
#: GUY DE VALOIS paladin 8 to 9 and 11 to 12, PAINE ranger 8 to 9, 11 to 12
#: and 12 to 13. `goldbox/levelup.py` reproduced **196 of 196 derived fields,
#: 70 of 70 saving-throw columns and 224 of 224 spellbook bytes**
#: (`tools/secret_of_the_silver_blades/ssbtrain.py diff`).
#:
#: **The spellbook is the half nothing had ever compared**, in this title or
#: in Curse: `Plan.spellbook` is a separate attribute from `Plan.fields`, so
#: every earlier replay looped the fields and left the sixteen bytes at
#: `0x078` alone. The menu the engine builds was read the same way --
#: `$18DA STY $1C10` counts it and `$18EB STA $7A00,X` holds the ids -- and
#: `levelup.learnable` gives the same list id for id, 113 ids over six menus.
#: Two of those six are what discriminate `SpellTable.menu_spell_level` from
#: the `(level + 1) // 2` the other two titles compute: the two rules agree
#: at magic-user 12 and 14 and differ at 11 and 13, and at both the engine
#: offered the table's answer.
#: `WISH-SPEC-ssb-89-train-input` and `WISH-SPEC-ssb-89-trained-party` are
#: four of those presses saved by the game itself, and
#: `tests/secret_of_the_silver_blades/test_ssbtrainer.py` replays them.
#:
#: `for_game` deliberately falls back to Pool of Radiance for a title it has no
#: tables for, which is right for reading a spell name and wrong for writing a
#: character record. A writer asks this instead.
TRAINER_MEASURED: frozenset[str] = frozenset(
    {POOL_OF_RADIANCE.key, CURSE_OF_THE_AZURE_BONDS.key,
     SECRET_OF_THE_SILVER_BLADES.key})

#: Titles whose **racial saving-throw bonus** is confirmed, which is a
#: narrower question than :data:`TRAINER_MEASURED` and the only one
#: `goldbox/c64_codec.py` needs when it recomputes the five save columns for
#: a converted character (#311).
#:
#: Pool of Radiance's whole trainer is measured. Curse's `$0F19` was graded
#: PROBABLE while the module docstring said *"no dwarf, gnome or halfling
#: Curse character exists to check it against"* -- **TRAVIS refuted that on
#: 2026-09-04**, and five driven Curse level-ups on 2026-09-05 agreed with
#: the engine on 75 of 75 derived fields including the five saving throws
#: (`#18 (Measure Curse's trainer so Level Up works there)`,
#: `tools/curse_of_the_azure_bonds/cursetrain.py`). Curse now belongs in `TRAINER_MEASURED` too, once
#: `#415 (automap/window.py picks the level-up spell dialog's class the same
#: wrong way plan would have, blocking Curse's trainer)` closed the gap that
#: held it out -- `TRAINER_MEASURED`'s own comment has the history.
#:
#: Silver Blades' `$11D8` was watched on 2026-09-06 (`#344 (A converted
#: Silver Blades dwarf, gnome or halfling keeps DOS's saving throws, because
#: that title's racial bonus has never been watched in the game)`,
#: `tools/secret_of_the_silver_blades/ssbtrain.py`): MALACHITE, thief 8 / fighter 7 with constitution
#: 17, was trained to thief 9 five times on one boot with only the race byte
#: changed between presses, and the engine wrote `6 10 6 12 7` for the dwarf
#: (twice) and `10 10 10 12 11` for the gnome, the halfling and the human --
#: 25 of 25 columns what `saving_throws` computes. So the reading that
#: **only the dwarf** takes the bonus in this title is measured, not read,
#: and `tests/secret_of_the_silver_blades/test_ssblevels.py` pins the five rows.
RACIAL_SAVE_BONUS_MEASURED: frozenset[str] = frozenset(
    {POOL_OF_RADIANCE.key, CURSE_OF_THE_AZURE_BONDS.key,
     SECRET_OF_THE_SILVER_BLADES.key})


#: Titles whose C64 thief-skill racial table is confirmed to differ from the
#: DOS one, and so the only ones `goldbox/c64_codec.py` recomputes a
#: converted thief's eight skills for rather than copying the neutral
#: record's stored percentages (`#431`, A converted halfling thief keeps the
#: other port's skill percentages, because the two ports ship different
#: halfling rows).
#:
#: **Pool of Radiance alone.** Its C64 racial row (`GEN $1076`) is the DOS
#: row one byte short from the gnome's hear-noise column on, CONFIRMED by
#: `tools/records/thiefskillcensus.py rows`, and the C64 build never applies a
#: dexterity adjustment DOS does. Curse ships the same 56 racial bytes on
#: both ports -- a copy is already right for it, and its own reason to
#: recompute is `THIEF_SKILL_DOS_STORAGE_INFLATED` below, a different defect
#: `#437 (A Curse thief's stored skills sit seven points above the rows the
#: engine's own tables give)` found: both Curse engines write +7 over what
#: their own tables give, which is not a racial-row disagreement and so does
#: not belong on this gate. Silver Blades' per-port agreement has not been
#: measured.
THIEF_SKILL_RACE_DIFFERS_BY_PORT: frozenset[str] = frozenset(
    {POOL_OF_RADIANCE.key})


def thief_skill_race_differs_by_port(game=None) -> bool:
    """Recompute this title's C64 thief skills rather than copy them (#431)?"""
    if game is None:
        return DEFAULT.key in THIEF_SKILL_RACE_DIFFERS_BY_PORT
    key = game.key if isinstance(game, LevelTables) else getattr(game, "key",
                                                                 game)
    return key in THIEF_SKILL_RACE_DIFFERS_BY_PORT


#: Titles whose DOS engine stores a thief's eight skill percentages above
#: what any table -- its own or the C64's -- produces, so a copied value
#: carries the defect into whichever port it lands on next
#: (`#440 (A Curse thief converted between DOS and the C64 arrives seven
#: points off, because DOS stores a stack leftover in all eight skill
#: columns)`).
#:
#: **Curse of the Azure Bonds alone.** `#437 (A Curse thief's stored skills
#: sit seven points above the rows the engine's own tables give)` found DOS
#: Curse's `GAME.OVR 0x03B74A` adding an uninitialised stack local,
#: `[bp-2]`, to all eight columns after the level, racial and dexterity
#: rows -- exactly the three terms `thief_skill_row` above computes. Pool of
#: Radiance's DOS routine has no such term, and that title's reason to
#: recompute is a different one, already covered by
#: `THIEF_SKILL_RACE_DIFFERS_BY_PORT`: its C64 racial row genuinely differs
#: from its DOS one. Silver Blades' copy of the routine zeroes the local
#: before the loop, so it never reads it.
#:
#: **Not a case for widening the other gate.** Curse's two ports agree on
#: their tables -- `THIEF_SKILL_RACE_DIFFERS_BY_PORT` would be a lie if it
#: named Curse -- the byte a DOS Curse record stores is simply not what
#: either table gives, on either port.
THIEF_SKILL_DOS_STORAGE_INFLATED: frozenset[str] = frozenset(
    {CURSE_OF_THE_AZURE_BONDS.key})


def thief_skill_dos_storage_inflated(game=None) -> bool:
    """Does this title's DOS engine store an inflated thief-skill row (#440)?"""
    if game is None:
        return DEFAULT.key in THIEF_SKILL_DOS_STORAGE_INFLATED
    key = game.key if isinstance(game, LevelTables) else getattr(game, "key",
                                                                 game)
    return key in THIEF_SKILL_DOS_STORAGE_INFLATED


def racial_save_bonus_measured(game=None) -> bool:
    """Is this title's racial saving-throw bonus confirmed in the game?"""
    if game is None:
        return DEFAULT.key in RACIAL_SAVE_BONUS_MEASURED
    key = game.key if isinstance(game, LevelTables) else getattr(game, "key",
                                                                 game)
    return key in RACIAL_SAVE_BONUS_MEASURED


def trainer_measured(game=None) -> bool:
    """Has this title's trainer been measured? None means the default title."""
    if game is None:
        return DEFAULT.key in TRAINER_MEASURED
    key = game.key if isinstance(game, LevelTables) else getattr(game, "key",
                                                                 game)
    return key in TRAINER_MEASURED


def for_game(game=None) -> LevelTables:
    """The tables for a title.

    Takes a `goldbox.c64_port.C64Container`, a game key, a `LevelTables`, or None. Deliberately
    duck-typed on `.key` rather than importing `goldbox.c64_port`: this module needs
    one string from that one, and a title it has no tables for falls back to
    Pool of Radiance rather than raising, because every geometry-only title in
    `goldbox/c64_port.py` runs an engine whose progression has not been read.
    Pools of Darkness has an entry of its own (`PARTLY_READ`), so its key
    no longer falls back.
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


def _dos_con_save_racial_step(constitution: int) -> int:
    """The DOS racial/bonus-item column-0 addition, Curse and Silver Blades.

    Curse's `GAME.OVR:0x3B45B` and Silver Blades' `0x3C644`, reading the
    in-force constitution at `0x019`: 4-6 is +1, 7-10 +2, 11-13 +3, 14-17 +4,
    and exactly 18 +5. The last test is `cmp al, 0x12 / jne` in both
    (`0x3B6BE`, `0x3C885`), so 19 and above take nothing from this step and
    only :func:`_dos_con_save_high_step`'s addition.
    """
    con = int(constitution or 0)
    if con > 18:
        return 0
    if con == 18:
        return 5
    if con >= 14:
        return 4
    if con >= 11:
        return 3
    if con >= 7:
        return 2
    if con >= 4:
        return 1
    return 0


def _dos_con_save_high_step(constitution: int) -> int:
    """The high-constitution column-0 addition every race gets, same routine.

    19-20 is +1, 21-22 +2, 23-24 +3, 25 +4; the last test is `cmp al, 0x19 /
    jne` (Curse `0x3B728`, Silver Blades `0x3C8EF`), so nothing above 25
    takes a step.
    """
    con = int(constitution or 0)
    if con > 25:
        return 0
    if con == 25:
        return 4
    if con >= 23:
        return 3
    if con >= 21:
        return 2
    if con >= 19:
        return 1
    return 0


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


def thief_skills(level: int, race: int, game=None,
                 dexterity: int = 0) -> tuple[int, ...] | None:
    return for_game(game).thief_skill_row(level, race, dexterity)


def dos_thief_skills(level: int, race: int, game=None,
                     dexterity: int = 0) -> tuple[int, ...] | None:
    """DOS's own eight percentages, where they differ from the C64 (#431)."""
    return for_game(game).dos_thief_skill_row(level, race, dexterity)


def turning_level(cleric_level: int, game=None,
                  paladin_level: int = 0) -> int | None:
    return for_game(game).turning_level(cleric_level, paladin_level)


def clamp_threshold(class_name: str, level: int, game=None) -> int | None:
    return for_game(game).clamp_threshold(class_name, level)


def dos_thac0_at(class_name: str, level: int, game=None) -> int | None:
    return for_game(game).dos_thac0_at(class_name, level)


def dos_base_thac0(class_levels, game=None) -> int | None:
    return for_game(game).dos_base_thac0(class_levels)


def dos_engine_thac0(class_levels, game=None) -> int | None:
    return for_game(game).dos_engine_thac0(class_levels)


def dos_engine_saving_throws(class_levels, race: int = 0, constitution: int = 0,
                             bonus_item: bool = False, game=None,
                             former_levels=None,
                             ) -> tuple[int, ...] | None:
    return for_game(game).dos_engine_saving_throws(
        class_levels, race, constitution, bonus_item, former_levels)


def base_thac0(class_levels, game=None) -> int | None:
    return for_game(game).base_thac0(class_levels)


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
