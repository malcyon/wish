# Levelling up, as the trainer does it

**Status: solved.** Every field the training hall writes is derived from the
game's own tables, and replaying the twenty-nine measured trainings of
[`119`](119-test-party.md) through `goldbox/levelup.py` reproduces the record the
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

`GEN $1B8C`, in order. Every one is in `goldbox/levelup.py` beside the field it
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
exactly. **That is Pool of Radiance's rule and not the family's**: Curse's
`$0FAD` adds a dexterity row as well, and the section on Curse below has it.

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
a fighter 8. `goldbox/levels.py` keeps those in `clamp_thresholds`, apart from the
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

**`goldbox/levelup.py` reproduces it, because the promise is that we write what the
trainer writes.** `Plan.experience_lost` and `Plan.classes_disqualified` say
what a training will cost before it is applied, so a caller can warn instead of
silently doing it.

## Where the button is

One per character card, at the right end of the class-and-level line, and
**hidden** rather than disabled unless that character has the experience. The
card is which character it means, so the button needs no label saying so.

**Which class is not a question the player is asked.** Donald's rule: the
button always raises the class with the highest threshold, and the next press
takes the next one. `goldbox.levelup.best_next_class` implements it as the class
whose threshold **after** the level it is about to gain is largest — not the
one it needs now — because the post-level number is the one `$23D4` actually
reads. Ties break in class-bit order (magic-user, cleric, thief, fighter),
which is the order `0x0C9` stores, so repeated presses walk down the order by
themselves.

The two readings are not the same rule. A magic-user 4 / thief 5 needs 22,501
for the magic-user against the thief's 20,001, so comparing what each needs now
picks the magic-user; after the level it is 40,001 against 42,501, so the clamp
will read the thief's. With 42,500 points thief-first reaches magic-user 6 /
thief 6 where magic-user-first stalls at 5 / 6. Across every two- and
three-class combination in the tables the post-level rule never gains fewer
levels than the current-threshold one and in 62 cases gains more.

On LADY KATHERINE, magic-user 1 / thief 1 with 5,002 points, the rule picks the
magic-user, and three presses leave her magic-user 2 / thief 3 on 5,000 — the
measured good order above, taken without her player having to know it.

**The outcome names the class it raised** — `LADY KATHERINE is a magic-user 2`
— because the button no longer says which and that line is the only place the
choice is visible.

**The one case the button does not take silently** is where the plan's
`classes_disqualified` is not empty: the clamp costs a level the character has
already earned, so the window asks first and names what it costs. The auto-rule
makes that rare rather than impossible. Where it is empty there is nothing to
confirm — the clamp is what the trainer always does.

## One title, and it says so

**Levelling is refused for every title but Pool of Radiance**, with the reason
in the outcome's notes, and the button does not appear on the card at all
(#16). `automap.actions.level_up_blockers` takes the title as well as the
record, and `goldbox.levels.TRAINER_MEASURED` is the list of titles whose trainer
has been read — one entry.

Curse of the Azure Bonds is the case that made this necessary, because it is
the only one that would have failed *quietly*. Its level tables are in
`goldbox/levels.py`, so selecting them looks like enough; the other four titles have
no tables, match no row and produce no button by luck. Selecting Curse's tables
would still have left every derivation around them running on Pool of
Radiance's numbers — the hit-die roll at `$2037`, the saving-throw masks at
`$1F44`, the constitution tables at `$247B`/`$2486`, the spell capacity at
`$20BC`.

**Measured: none of those addresses means anything in Curse.** The two `GEN`
files were compared byte for byte from `$0800` — Pool of Radiance's 9083 bytes
off `POOL3`, Curse's 9455 off `CURSE_A` — and 8925 of the 9083 common bytes
differ. Every address in the table at the top of this file holds something else
in Curse's build. Searching Curse's whole `GEN` for Pool of Radiance's tables
found two and only two: the hit die 2697 bytes earlier at `$161E`, and the
thief-skill rows 42 bytes earlier at `$1004`. `goldbox/levels.py`'s own per-title
table agrees, and the rows it still leaves at `--` for Curse — racial save
bonus, constitution hit-point bonus, wisdom bonus spells, turning level — are
precisely the ones a level-up needs.

So what would unblock Curse is not a decision but the same work again in
Curse's `GEN`: find those four, and the roll and capacity routines, and replay
measured Curse trainings through them. Until then `TRAINER_MEASURED` has one
entry and the refusal says which title it is refusing.

## Curse of the Azure Bonds, table by table

**Every routine above has now been found in Curse's own overlays** (`#18`), and
`tests/test_cursetrainer.py` reads each one off the player's disk rather than
trusting this document. What follows is where they are and, where the rule is
not Pool of Radiance's, what the rule is instead.

**How they were found, which is the transferable part.** Not one Pool of
Radiance address survives, so the way in was the record rather than the code:
Curse keeps the working character at `$7C00`, so a census of every absolute
instruction in the overlay whose operand lands in `$7C00`-`$7DFF`, printed
against `goldbox/layout.py`'s field names, puts every routine within two
instructions of the table it reads. `tools/trainerscan.py` is that census, and
`--callers` walks back up from a routine to the sequence that calls it. None of
this needed the emulator.

`GEN` runs at `$0800`. **`ECL65` runs at `$8000`**, which is settled by its own
`LDA $888D,X` reading the spell-slot rows that sit at payload offset `0x88D`.

### How far to trust each of these

They are not all evidenced the same way, and reading them as though they were
is the mistake this section exists to stop. Everything below was read out of
the bytes; what differs is whether any **byte on a disk** votes for it as well.

| finding | grade | what it rests on |
|---|---|---|
| saving-throw rows, `$0F49` + `$0F5D` | **CONFIRMED** | bit-unpacking reproduces all **45** rows that were previously transcribed, and the rows past Curse's ceilings match Silver Blades' separately measured extensions |
| turning level, `$113F` | **CONFIRMED** | the bytecode, the two shipped characters that store one, and a ladder matching Pool of Radiance's independently read `$2399` digit for digit |
| constitution hit points, `$11D7` + `$126D` | **CONFIRMED** | the table bytes, and `hp_max` reproduced on **6 of 6** shipped characters |
| wisdom bonus spells, `ECL65 $8906` | **CONFIRMED**, and see below | the table bytes plus an exact match to the *Players Handbook* row |
| racial saving-throw bonus, `$0F19` | **PROBABLE** | **the bytecode alone** |
| hit die rolled twice, `$15FC` | **PROBABLE** | the bytecode alone; a roll leaves no trace in a record |
| thief skills including dexterity, `$0FAD` | **CONFIRMED** | the bytecode and the one shipped thief, 8 of 8 columns |
| spell capacity never stored | **CONFIRMED** | no write in any of 411 files, and 6 of 6 characters hold zero |

**The racial saving-throw bonus is PROBABLE and was briefly written up as
confirmed.** It is bytecode and nothing else: none of the six characters SSI
shipped is a dwarf, gnome or halfling, and the disks carry no other Curse
character, so **no stored `save_*` byte anywhere has ever been seen with this
bonus subtracted into it**. That gap is the same shape as the one this section
found for spell capacity — `ECL65 $880D` computes a perfectly correct number
that never reaches the record — so "the routine says so" is a weaker claim than
"a character's byte says so". What would raise it to CONFIRMED: one Curse
dwarf, gnome or halfling whose five stored saves are the class rows less
`constitution * 2 / 7` on columns 0, 2 and 4 and unchanged on 1 and 3. A driven
training would make one.

**The wisdom bonus is CONFIRMED and can never be corroborated against a
character**, which is a different thing from being weakly evidenced. The bonus
lands in `$2BBB`, and nothing copies `$2BBB` back into the record — so there is
no byte on any disk that could agree or disagree. It rests on the table read
plus the independent fact that `0 0 1 1 2 3 4` is AD&D 1st edition's row, which
is two sources and as strong as this one gets without watching the running game
memorise a spell. A reader should not assume the evidentiary shape of the
constitution bonus, which six characters' `hp_max` votes for directly.

**One caveat on the constitution bonus, which is otherwise fully earned.** No
shipped character has a constitution below 14, so the *consequence* of the
table having no floor — a character with constitution 6 or less losing a hit
point a level — is read off the table's own signed bytes and has not been
observed happening to anybody.

### The sequence

`GEN $2041`, the trainer's own, against `$1B8C`'s fourteen `JSR`s in Pool of
Radiance.

| | routine | what it does |
|---|---|---|
| 1 | `$14F8` | raise every qualifying class **by one level**, and roll a hit die (`$15E1`) for each |
| 2 | `$1649` | the cleric's spell grant, from the level table at `$1660` |
| 3 | `$2200` | the magic-user's menu of one new spell |
| 4 | `$22F4` | a paladin's cleric spells, from level 9 |
| 5 | `$2305` | a ranger's druid spells at 8 and magic-user spells at 9 |
| 6 | `$2086` | the experience clamp (`$1458`) |
| 7 | `$0DD0` | recompute everything derived — and this is also what character creation calls |
| 8 | `$20A3` | put a dual-classed human's old class back |

`$0DD0` is the recompute, and its order is `$2515`, `$0DF1` (fighting level),
`$0E08` (THAC0), `$0E5E` (saving throws), `$0FAD` (thief skills), `$113F`
(turning), `$11F1` (hit points), `$1909`, `$1939`, `$112C` (`level` = the
maximum of all **eight** class slots).

### Where each table is

| what | where | shape |
|---|---|---|
| the level-up sequence | `$2041` | eight `JSR`s, above |
| eligible level per class | `$1308` | walks the class's own 13 thresholds upward |
| THAC0 | `$0E2C`/`$0E39`/`$0E46`; fighter group `21 - attack_level` at `$0E08` | indexed by level |
| saving throws | `$0F49` level-1 rows, `$0F5D` masks | 4 x 5 x 4 bytes, **two bits a level** |
| paladin's -2 | `$0F01` | code, all five columns, floored at 0 |
| racial save bonus | `$0F19` | `constitution * 2 / 7`, races 1/3/5, columns 0/2/4 |
| thief skills | `$1004` level, `$10A4` **dexterity**, `$1064` race | 9, 17 and 8 rows of 8 |
| turning level | `$113F` | arithmetic, not a table |
| constitution hit points | `$11D7` | one signed row, indexed by the raw score |
| how far it counts | `$1282` | last level, per class slot — the same `roll_to` |
| `hp_max` | `$11F1` | per slot, summed, then divided by the class count |
| hit die | `$161E` sides, `$1626` first flat level, `$162E` flat amount | 8 entries, class-slot order |
| the roll | `$15E1` | **two dice, keep the higher** |
| experience thresholds | `$136E` | 6 rows x 13 x 3 bytes, big-endian |
| class ceilings | `$15A1` | 8 bytes |
| racial class limits | `$15A9` | 7 rows of 8, adjusted by the prime requisite at `$1599` |
| cleric spell grant | `$1649`, tables `$1660`/`$166B`/`$1675` | level → record offsets and masks |
| magic-user menu | `$2200`, spell levels at `$273F` | `(level + 1) / 2`, 95 ids |
| starting spellbook | `$167F`, tables `$169C`/`$16A8`/`$16AF` | creation only, not the trainer |
| spell slots | `ECL65` `$888D` magic-user, `$88C4` cleric | 11 and 10 rows of 5 |
| spell capacity | `ECL65` `$880D` | built in RAM at `$2BB6`, **never stored** |
| wisdom bonus spells | `ECL65` `$88F6`, table `$8906` | one spell a point, from 13 |

### The six rules that are not Pool of Radiance's

**The hit die is rolled twice and the better roll kept** (`$15FC`), for every
class -- PROBABLE, and it is the one rule here that no stored byte can ever
vote for, because `hp_rolled` is a running total and a roll leaves no trace of
itself. Pool of Radiance rolls once and floors a *single-class fighter* at 4;
Curse has no floor of any kind. A multi-class character's roll is then divided
by how many classes it has, and the division rounds up *probabilistically* —
`$11AB` rolls again against the remainder — so two identical characters can
gain different hit points from the same die.

**`hp_max` is per class slot.** For each slot, `min(level, roll_to) * bonus`,
summed, **plus one extra bonus for a ranger** (`$128A`, because a ranger is 2d8
at level 1), divided by the class count, plus `hp_rolled`, floored at the
character's `level`. Pool of Radiance's is `hp_rolled + level * bonus` with one
row chosen by the fighter bit. On the six characters SSI shipped, Curse's
formula reproduces all six and Pool of Radiance's reproduces three — it is 5
low on the paladin, 8 low on the ranger and 1 high on the fighter/thief.

**The constitution table has no floor and one row.** `$11D7` is indexed by the
raw score and is signed: -2 at 1-3, -1 at 4-6. The "not a fighter" cap is done
by clamping the *score* to 16 for class slots 0-2 (`$126D`), which is why the
two titles agree from 7 to 18 and only Curse takes hit points away.

**Thief skills read dexterity.** `$0FC6 LDA $7C17 / SEC / SBC #$09` indexes a
17-row table at `$10A4`, AD&D 1st edition's adjustment exactly. Curse's racial
rows at `$1064` are also not Pool of Radiance's: dwarf and elf are identical
and gnome, half-elf, halfling and half-orc are not — Curse's are the rulebook
verbatim and Pool of Radiance's carry the same numbers in different columns.

**The turning level is arithmetic**: `max(cleric, paladin - 2)`, stored as it
is below 4 and `+ 1` capped at 10 from 4 up. Over a Curse cleric's whole range
that is `1 2 3 5 6 7 8 9 10 10`, which is Pool of Radiance's `$2399` table
entry for entry — the same numbers by a different mechanism, plus a paladin
branch Pool of Radiance has no class for.

**Spell capacity is never stored.** No instruction in `GEN`, `ECL64` or `ECL65`
writes `0x0EE`-`0x0F3`, and all six shipped characters hold six zero bytes
there. `ECL65 $880D` rebuilds the whole thing in fifteen bytes of workspace at
`$2BB6` — magic-user, cleric, and a third column for what a paladin and a
ranger borrow — every time the sheet is drawn. So a writer must leave that
field alone on this title rather than fill it.

The wisdom bonus is the same shape as Pool of Radiance's and a different table:
`ECL65 $88F6` loops once for **every point of wisdom from 13 up**, each point
buying one spell at the level `$8906` names — `0 0 1 1 2 3 4` at wisdom 13 to
19 — and only where the class row already gives a slot. Pool of Radiance's
`$10AD` starts at wisdom 12, which is `docs/125-bug-notes.md`'s off-by-one;
Curse does not have it.

### Two things that turned out to be the same

**The experience clamp is Pool of Radiance's rule.** `$1458` reads row `level`
of the class's own thresholds, subtracts one, takes the maximum across the
character's classes and writes it only if it lowers `0x0E8`. Curse needs no
`clamp_thresholds` field, though: its rows are thirteen wide and every class
has a real entry one past its ceiling — 750001, 675001, 660001, 1250001,
1400001 and 975001, which are Silver Blades' *next* thresholds, measured
separately off a different file.

**The magic-user picks one spell from a menu**, as in Pool of Radiance and
unlike Silver Blades. `$2200` computes the castable level as `LSR A / ADC #$00`
— `(level + 1) / 2` — copies the 32-byte spellbook mask aside, rotates it a bit
at a time and lists every id the character does not know whose level is at or
below that. Curse *does* have a magic-user grant loop of Silver Blades' shape
at `$167F`, and the trainer never calls it: it is the starting spellbook, and
it is what the two shipped mages hold.

### Two record bytes with names now

`0x0B9` and `0x0BA` are the **dual-classed old class slot** and its **old
level**, and `goldbox/layout.py` now declares them under those names. `$1470`
and `$1321` skip that slot when a human has one, so it counts towards neither
the clamp nor eligibility; `$20A3` writes the old level back into that slot and
ORs the class bit into `class_bits`; `$124F` gives it its own constitution term
in `hp_max`; and `$15E7` uses `0x0BA` to stop the hit-die roll running for a
level already paid for.

**The writer, found on `#224` (`0x0B9` and `0x0BA` are documented both as an NPC
marker and as the dual-class slot).** `GEN $2387` gates on race 7, on a check
that refuses with carry clear, on `0x0BA` still being zero, and on level 2 or
better, then `$23C9` stores the slot and `$23D2` the level. `$18EB` gives the
convention the readers rely on: `LDY #$FF / LDA 0x0BA / BEQ / LDY 0x0B9` --
**zero in `0x0BA` means "not dual-classed"**, so slot 0, the magic-user, is not
ambiguous. Pool of Radiance and the two Krynn titles do not reference either
byte anywhere on their disks; Silver Blades (`GEN $1FB7`/`$1FBD`) and Gateway
(`GEN $23D3`) write the same pair.

### One more racial rule, not needed for a level-up but true

`$1553`'s racial class limit is **adjusted by the prime requisite**. `$1599`
names the ability that governs each class — intelligence for a magic-user,
dexterity for a thief, strength for the fighter group, and `$80` for a cleric,
which means none — and `$15A9` holds the limit a character with 18 in it
reaches. A score of exactly 17 loses one level and anything below 17 loses two.
So `LevelTables.racial_limit` returns the best case for Curse: a dwarf fighter
is capped at 9 with strength 18, 8 with 17 and 7 with anything less.
