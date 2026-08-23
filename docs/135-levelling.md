# Levelling up, as the trainer does it

**Status: solved.** Every field the training hall writes is derived from the
game's own tables, and replaying the twenty-nine measured trainings of
[`119`](119-test-party.md) through `por/levelup.py` reproduces the record the
trainer produced, **byte for byte**, on all thirty-five before/after pairs held
in `work/p18b/` — given the hit die the game rolled. The thirty-fifth is
`rec-kath-t2-*`, driven later for the multi-class clamp below. The five blockers
`automap/actions.py` used to carry are gone, and `level_up_blockers()` is empty.

One field is a die and always will be. `hp_rolled` at `0x0ED` takes a fresh
roll at every training; everything it feeds is arithmetic.

## Where the game keeps it

`GEN`, resident at `$0800`, whatever its PRG header says. `POOL3.D64` carries
the file.

| what | where | shape |
|---|---|---|
| the level-up sequence | `$1B8C` | fourteen `JSR`s, in the order below |
| THAC0 | `$1F1F` | 4 rows x 9, index `class * 9 + level`, stored `60 - THAC0` |
| saving throws | `$1FA2` base, `$1FB6` and `$1FCA` masks | 4 classes x 5 columns each |
| racial save bonus | `$2359`, race flags at `$2380` | `constitution * 2 / 7` |
| experience thresholds | `$1DB4`/`$1DD8`/`$1DFC` | parallel low/mid/high, 9 a class |
| class ceilings | `$1E5C` | 8 bytes, class-bit order |
| racial class limits | `$1E60` | 4 bytes a race |
| thief skills | `$102E` | 9 rows of 8 |
| thief racial modifier | `$1076` | 8 rows of 8, signed |
| hit die | `$20A7` | 4 bytes, class-bit order: d4 d8 d6 d10 |
| constitution hit points | `$247B` fighter, `$2486` everyone else | indexed by the score, consulted from 15 |
| how many classes | `$20AB` | indexed by `char_class` at `0x073` |
| cleric spell slots | `$2228` | index `level * 4` |
| magic-user spell slots | `$2248` | index `level * 4` |
| wisdom bonus spells | `$10AD` | indexed by the score |
| turning level | `$2399` | indexed by cleric level |
| spell level per id | `$268E` | 1-55 |
| cleric-or-magic-user per id | `$226B` | 1 cleric, 0 magic-user |

## The sequence

`GEN $1B8C`, in order. Every one is in `por/levelup.py` beside the field it
fills.

| | routine | what it writes |
|---|---|---|
| 1 | `$1FDE` | the staged per-class levels into `0x0C9`-`0x0D0` |
| 2 | `$2021` | `level` at `0x0A0` = the **maximum** of those |
| 3 | `$1EF3` | `thac0_base`, the **best** row across the classes |
| 4 | `$1F44` | the five saving throws, then `$2359`'s racial bonus |
| 5 | `$2342` | `attack_level` = the fighter level; `attack_forms[0]` to 3 at fighter 7 |
| 6 | `$2388` | `turn_power` at `0x0A4` from the cleric level |
| 7 | `$20BC` | `spells_castable`, and the cleric's new spell level granted whole |
| 8 | `$1FEC` | the eight thief skills |
| 9 | `$2037` | one hit die per class trained, then `hp_max` |
| 10 | `$23D4` | experience, clamped |
| 11 | `$2459` | `levels_drained` reduced by the levels gained |

## The five rules that were missing

**Hit points.** `hp_max = hp_rolled + level x constitution bonus`, recomputed
from scratch at every training (`$2079`). So `hp_rolled` is the stored half and
`hp_max` the derived one, which is the opposite of how the layout used to read.
The roll is one die of the class's own size, divided by how many classes the
character has and never less than 1 — and **never less than 4 for a
single-class fighter**, which is a `CMP #$04` against `class_bits == 8` at
`$205A`. The constitution table is AD&D 1st edition unchanged, including the
cap of +2 for anybody without a fighter bit: MALCYON, an 18-constitution
magic-user, gets 2 and not 4.

**Saving throws.** Not tabulated. Five columns start at 20, and for each class
the game subtracts, per column, the number of set bits among the low
`level - 1` bits of *two* masks, from a level-1 row — keeping whichever class
gives the lower number. Then, for a dwarf, gnome or halfling only, it subtracts
`constitution * 2 / 7` from all five. That is the whole rule and it needs no
modifier stored on the character: MAGNUS reads three lower than SILAS at every
level because `26 // 7` is 3.

**Spell capacity.** `0x0EE`-`0x0F0`, one byte a spell level, cleric in the high
nibble and magic-user in the low one. The cleric's number is the class table
plus the wisdom bonus, and the bonus is only added where the class table
already gives a slot — a level-1 cleric gets no second-level spell however wise
it is. ROLAND, wisdom 16, stores `50 50 20` at cleric 6, which is `3,3,2` plus
`+2,+2,0`.

**Thief skills.** The level row plus the racial row, and **nothing else**.
`docs/119` guessed that dexterity was folded in as well; it is not — `$1FEC`
reads no ability score. LADY KATHERINE's measured ladder is the half-elf row
exactly.

**The magic-user's new spell is a choice, not a roll.** `$215A` collects every
spell id from 1 to 55 the character does not know, whose spell level is at or
below `(new level + 1) // 2`, that is not a cleric spell, and puts them on a
menu. The level-up does not finish until one is picked — which is why a
magic-user's training stalls if the driver presses Return blindly, and why
`LevelUp` refuses without a `spell` rather than choosing one. A **cleric**
needs no choice: it is granted its whole new spell level at once.

## Money, healing, and the two things `LevelUp` leaves alone

**Money is untouched, and the trainer does take it.** A flat **1000 gold** at
every level, with copper, silver, electrum and gold zeroed and the remainder
written back as platinum — measured across all twenty-nine trainings. That is
what walking into a school costs rather than what gaining a level costs, so
none of the seven coin fields at `0x0BB` is written. **Movement** is left alone
for the same reason: the trainer recomputes it from encumbrance, and nothing
here changes what a character carries.

**Healing is done, because the trainer does it.** MAGNUS went into the school
at 2 of 9 hit points and came out at 13 of 13. The order is the trainer's and
it matters: roll the die, raise `hp_rolled` and `hp_max`, *then* set current
hit points to the **new** maximum — healing first would heal to the old one.

Where current hit points live depends on what you are holding. Record `0x119`
is 16-bit and **export-only**: it lies past the 256 bytes a save slot keeps, so
it exists in a 580-byte export and nowhere else. Live and on disk the only copy
is the roster block's `+0x19`, one byte, capped at 255 — which is the byte
`HealParty` has been writing all along.

**A character at 0 hit points is refused**, not levelled. Zero is dead or dying
and the record does not say which, so healing one to full would produce a
corpse in a state the game never writes. It is the same refusal `HealParty`
makes and it names the reason.

## The experience clamp

After training, `0x0E8` becomes one less than the largest next threshold across
*all* the character's classes, and only ever falls. The threshold arrays are
nine wide a class and each class's tenth entry lands in the next class's unused
slot 0, so the game has a real number one past every ceiling — 60,001 for a
magic-user 6, 55,001 for a cleric 6, **160,001 for a thief 9** and 250,001 for
a fighter 8. `por/levels.py` keeps those in `clamp_thresholds`, apart from the
rows, because `next_threshold` has to stay `None` at a ceiling: an experience
bar there has nothing to fill towards.

**Experience is not divided between classes.** LADY KATHERINE, magic-user 1 /
thief 7 with 70,100 points, was offered thief 8 — whose single-class threshold
is 70,001. Every class is measured against the whole stored number, which is
what the roster's per-class Level Up buttons do too.

**The threshold rows hold the published number plus one, and the comparison is
`>=`.** The magic-user's level-2 row is 2,501 where AD&D prints 2,500, and
`GEN $1BBC` walks the column downwards taking the first row the character is
not below. Both halves were driven at the school: LADY KATHERINE at exactly
2,500 got `LOW EXPERIENCE OR WRONG CLASS` for thief 3 *and* for magic-user 2,
and one point more — 2,501 — got `WILL BE A 3RD LEVEL THIEF` and
`WILL BE A 2ND LEVEL MAGIC-USER`. So `ready_classes` compares `>=` against the
game's own number and nothing here is off by one.

### The clamp is measured on a multi-class character, not extrapolated

Everything else in this file was measured class by class; the clamp was not.
Two of the twenty-nine trainings settle the multi-class rule on their own:

| character, after | classes | clamp | which class it came from |
|---|---|---|---|
| magic-user 1 / thief 2 | both | 2,500 | either — both want 2,501 |
| magic-user 2 / thief 9 | both | 160,000 | the **thief**'s entry past its ceiling, not magic-user 3's 5,001 |

`work/p18/lk-{before,after}.hex` and `work/p18b/rec-kath-m2-*.bin`. The rule is
`max` across the classes, from the game, and it is why the order a multi-class
character trains in changes what it ends up with.

### The order a multi-class character trains in matters

LADY KATHERINE, magic-user 1 / thief 1 with 5,002 points, qualifies for both
magic-user 2 (2,501) and thief 2 (1,251).

* **Thief first.** She becomes thief 2; the clamp takes the larger of
  magic-user 2's 2,501 and thief 3's 2,501 and leaves her at **2,500** — one
  short of both. The magic-user school then refuses her, and she has lost the
  level she had earned. 2,502 points are gone.
* **Magic-user first.** She becomes magic-user 2; the clamp takes the larger of
  magic-user 3's 5,001 and thief 2's 1,251 and leaves her at **5,000**. The
  thief is still offered. **She gets both levels.**

The general rule is that the untrained class survives unless its next threshold
is at or above the trained class's *new* next threshold. Both halves were driven
at the game's own schools; the loss is in `goldbox-bugs.md` as bug 8.

**`por/levelup.py` reproduces it, because the promise is that we write what the
trainer writes.** `Plan.experience_lost` and `Plan.classes_disqualified` say
what a training will cost before it is applied, so a caller can warn instead of
silently doing it.

## Where the button is

One per character card, at the right end of the class-and-level line, and
**hidden** rather than disabled unless that character has the experience. The
card is which character it means, so the button needs no label saying so. A
multi-class character whose classes are both ready gets a menu naming them,
because the trainer asks which school you are standing in and nothing here
should choose for the player — each school teaches exactly one class
(`'WE TRAIN ONLY THIEVES HERE'`), so one class a visit is the game's shape too.

**The one case the button should not take silently is the one above**: where
the plan's `classes_disqualified` is not empty, pressing it costs a level the
character has already earned, and it should say so first. Where it is empty
there is nothing to confirm — the clamp is what the trainer always does.
