# What a C64 trait slot is, and what the engine does with an id in one

`#252 (Does a C64 trait slot apply an item-granted effect id, or only the
ones its own READY routine wrote?)` asked whether an effect id written into
one of the ten slots at record `0x0AD` by something other than the game --
a converter, an editor -- does anything. Read out of Pool of Radiance's
overlays and then watched in the running game under VICE.

**The answer, CONFIRMED both ways: a trait slot is one byte of persisted
state meaning "this character has effect N", with no owner, no duration and
no record of who wrote it. The engine applies it wherever it asks "has this
character got N?" through `LIBRARY $4027`, which is every combat check list,
the surprise check and any script that asks -- and never anywhere else. So
the id is the whole of what the game needs.**

One clause of that sentence used to read "and for 61, the Ring of Fire
Resistance, a converted character with the id in a slot resists fire on the
C64 better than any character born there, because the C64's own ring never
grants it". **That is wrong**: four of the five rings on the disks do grant
it, and `docs/183-the-two-rings-of-fire-resistance.md` says why they looked
otherwise.

Grades follow `docs/50-experiments.md`'s scale. Addresses are Pool of
Radiance's; the three C64 titles share the mechanism but not the numbers,
and "The same three tables in the other two titles" below has Curse's and
Silver Blades'. `tools/traitquery.py` derives all of it off the disks --
the predicate on its own, and with `--lists` the check lists as well.

## Two backing stores, one question

The engine keeps a character's effects in two places and asks about them
through two routines in `LIBRARY` (resident at `$2C48`):

| | where | entries | expires | asked through |
|---|---|---|---|---|
| the active-effect array | `SAVEDGAME0` `$4900` (id), `$4940` (owner), `$4980` (duration), `$4B80` (flag) | 64 for the whole save | yes | `$3FE4` (id in A, character in X), `$3FE1` (current character) |
| the trait slots | record `0x0AD`-`0x0B6`, read off the staging copy at `$6BAD` | 10 per character | never | `$4027` -- `JSR $3FE4`, and if the array said no, `LDX #$09 / LDA $6BAD,X / CMP $6E6E` |

The trait scan is three instructions and compares a value. There is no
provenance byte, no flag beside the id, no second field. **A slot READY
wrote and a slot Wish wrote are the same bytes to the same `CMP`.**
CONFIRMED from the code and by `tools/traitdrive.py`, which staged an id and
counted `$403C` -- the `SEC` only a trait match reaches -- going from 0 to 1.

## Who writes a slot

An absolute-operand census over all 564 files (`tools/absrefsweep.py
pool-of-radiance 6BAD 6BB6`) finds every writer:

| writer | what |
|---|---|
| `GEN $0BF3` | the racial seed at creation -- 107 for an elf, 124 for a half-elf |
| `SPELLE04 $ADD4` | **the grant**, when a passive item is readied: item byte `+14` goes into the first free slot scanning 9 down to 0; an equal byte already there means stop; no free slot means `$ADEF`, which writes it into the array instead |
| `SPELLE04 $AE13` | **the revoke**, when it is un-readied: find the id in the ten slots and zero it, else look in the array |
| `ECL64 $9ACD` / `$9AFA` | the same pair for combat |
| `SQRPACI64 $05A5`, `$063A`, `$065A` | clear the slot the predicate just matched -- 32, 31 and 55 on a cure |

The grant writes the id and nothing else. **CONFIRMED in the running game:**
`cited/252/ask11`, MALCYON with a CLOAK OF DISPLACEMENT staged readied
and an empty slot, ENCAMP > VIEW > ITEMS > READY on the cloak three times,
the whole 256-byte record at `$4D00` and the 768 bytes of the effect
arrays at `$4900` read before and after each press:

| press | the cloak | bytes that changed in the record | in the effect arrays |
|---|---|---|---|
| 1 | readied to un-readied | none | none |
| 2 | un-readied to readied | **one**: `$4DB6`, slot 9 of the block, `00` to `59` (89) | none |
| 3 | readied to un-readied | **one**: `$4DB6`, `59` to `00` | none |

The first press had nothing to revoke, because load had not put the id
there. **Five runs before that one pressed READY from the world's VIEW and
nothing moved**: `LIBRARY $4630`, the toggle, refuses a magical item -- bit
7 of `+15` -- with `NOT HERE` unless `$6DE4` is set, and CAMP sets that at
`$0818` on entering the camp menu and clears it at `$0862` on leaving. A
magical item is readied in camp or not at all, and the message is gone
before a screen read sees it.

`$ADD4` is reached only through `CAMP $12F8`, the dispatcher that walks
`ECL65`'s 24-entry table at `$9AD5` (ids 4, 38, 12, 14, 22, 34, 50, the item
power codes `$80`-`$88`, `$8A`, `$8B`, then 7, 43, 44, 57, 62, 15) for a
handler, and `$12F8` has two callers: `$10C7`, the READY/UNREADY toggle,
which enters only when item byte `+15` has bit 7 set (`$10B5 LDA $6D8B /
BPL`), and `$133B`, removing an array entry. Nothing on the load path calls
it. **So a slot is persisted state, not derived**: a character with a CLOAK
OF DISPLACEMENT staged readied and nothing in his slots loads with nothing
in his slots -- `[107, 0, 0, 0, 0, 0, 0, 0, 0, 0]` read off `$4DAD` after
`BEGIN ADVENTURING`, four boots. CONFIRMED.

## Who reads a slot: the check lists the literal census could not see

`tools/traitquery.py` finds the eleven call sites that reach `$4027` with a
literal id and reported 61 asked about nowhere. That was wrong, and the
reason is worth keeping: **the combat engine asks from tables.**

`SQRPACI01` is code and loads at `$0400`. Its `$072E` takes a list number
in X and a combatant in A, skips X zero-terminated lists at `$DB7A` -- RAM
under the I/O area, banked in by `$3AAB` and out by `$3AB1` -- and for each
id on the list stages the combatant and calls `$0776`, which is:

```
$0776  STY $2B23 / PHA
$077A  JSR $28A4          COMBAT: LDX $6DB4 / JMP $4027 -- array, then the ten slots
$077E  BCS $078B
$0780  ...                no: unless it is 21, 45 or 46, done
$078B  LDX $6E6E          yes: handler[id], low byte at $DA63,X, high at $DAEE,X
$07A8  JSR $FFFF          (patched with that address)
```

That is Curse's `calc_affect_effect` per `CheckType`, on the C64, and every
ask on every list honours a trait slot. The lists, read out of RAM bank 1
by `tools/traitask.py` while `COMBAT` was resident (`cited/252/ask1/tables.json`):

| list | walked from | for | ids |
|---|---|---|---|
| 1 | COMBAT `$28BA` | target | 126, 63, 37, 25, 71 |
| 2, 3 | | attacker's melee specials | 85, 86, 87, 68, 79, 80, 76, 73, 77; 64-70, 79, 85-87 |
| 4 | `$0CF4` | attacker, weapon damage | 29, 3, 6 |
| 5 | `$0CF9` | target, weapon damage | 28, 41, 104, 120, 101, 115, 116, 117, 119, 123, 96, 94, 60, 122 |
| **6** | ECL64 `$9A69` | **target of spell damage** | 113, **61**, 122, 60, 91, 10, 20, 105, 106, 112, 114, 118, 17, 93, 101, 28 |
| 7 | | restrained | 51, 52, 53, 31 |
| 8 | `$083F` | every combatant, at the start | 99, 81, 82, 89, 72, 56 |
| 9 | ECL64 `$99DB` | target, immunities | 105-112, 124, 125 |
| 10 | `$128C` | attacker, to hit | 1, 2, 33, 36, 49, 3, 6 |
| 11 | `$12B1` | target, to hit | 33, 17, 8, 9, 45, 46, 30 |
| **12** | ECL64 `$99BB` | **target, saving throw** | 8, 9, 10, 17, 20, 33, 36, 45, 46, 49, **61** |
| 13 | `$0DCA` | target, on going down | 99, 100, 103, 75, 74 |
| 14 | SECSET64 `$0AE5` | ranged attack forms | 83, 84, 88, 92, 121 |
| 15 | `$0923`, `$09D4` | attacker, at turn start | 21, 30, 74, 75, 11 |
| 16 | `$1291` | target, miss chance | 25, 71, 37, 89 |
| 17 | `$2145` | | 1, 2, 11 |
| 18 | | movement | 39, 42, 58 |
| 19 | `$0C32` | every combatant, each round | 98, 101, 23, 72, 56, 11 |

Twenty lists, 92 distinct ids. Outside combat, `DUNGEON $1D5F`/`$1D77` ask
about 25 and 21 for the surprise check and `$1D1B` asks about whatever an
`ECL` script names. **Nothing computes armour class, THAC0 or a saving throw
from the block directly, and the character sheet does not draw it**: the
handlers do the work when a list is walked.

The ids on no list at all are the ones a trait slot cannot do anything with
in combat: among them 38 (extra strength -- the gauntlets go through the
array, not a slot), 5, 12, 16, 53. An id in a slot is honoured **where a list
names it, or where an instruction names it**, and nowhere else.

**Three ids reach it by an instruction and by no list: 24, 32 and 55.** The
first of the three was missed until 2026-09-10, and the reason is a shape
this page had not looked for: `SPELLE01 +0x09ec` is `LDA #$18 / JSR $28A4`
and `+0x0e13` is `LDA #$62 / JSR $28A4`, so they ask about 24 and 98 through
the wrapper rather than reaching `$4027` directly, and a census of calls to
`$4027` cannot see either. 98 is on list 19 already; 24 is not on any list.
**So the count of ids a trait slot can do anything with in Pool of Radiance
is 95** -- 92 from the lists, plus 24, 32 and 55.

## The same three tables in the other two titles

**Every C64 title in the family has this architecture and none of them has
the same numbers.** `tools/traitquery.py --lists` follows the call chain out
from the predicate to the wrapper, the ask, the walker and the block, so a
title nobody has mapped either answers or says it did not; its docstring has
the four steps. Run against Pool of Radiance it reproduces the live reading
above byte for byte -- `SPELLE65 +0x0570`, 20 lists, 134 ids, 92 distinct --
which is what licenses the other two rows, since those have no live reading
to check against.

| | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|
| the array-then-traits predicate | `LIBRARY $4027` | `$40E2` | `$387D` |
| the wrapper the lists ask through | `COMBAT +0x20a4` | `ECL64 +0x12c5` | `ECL64 +0x128f` |
| the ask, and the handler dispatch | `SQRPACI01 +0x0376` | `COMBAT +0x0ac3` | `COMBAT +0x0aae` |
| handler address per id | `$DA63`/`$DAEE` | `$EE2A`/`$EEBC` | `$EF90`/`$F001` |
| **ids in the namespace** | **139** | **146** | **113** |
| the check lists | `$DB7A` | `$EF4F` | `$F073` |
| the file they ship in | `SPELLE65 +0x0570` | `COMBAT2 +0x0f4f` | `COMBAT2 +0x1073` |
| which puts that file at | `$D60A` | `$E000` | `$E000` |
| lists, ids, distinct | 20, 134, **92** | 21, 155, **115** | 21, 110, **80** |
| ids named by an instruction and no list | 3 | 5 | 10 |
| **ids a trait slot can do anything with** | **95** | **120** | **90** |

The namespace size is not a guess: it is the gap between the two handler
tables the ask dispatches through, and the lists land at exactly
`<high table> + namespace + 1` in all three titles, which is the layout
checking itself.

**Silver Blades honours 90 ids and `goldbox/traits.py` named six of them until
2026-09-15. It now names all 90, 87 of them CONFIRMED.** That is `#497 (The
trait picker offers a Secret of the Silver Blades character six names, and
nobody has ruled on whether it should offer Pool of Radiance's 129)`, and the
next two sections are how.

**How far Pool of Radiance's names can be trusted for Silver Blades is a
question about the id, not about the title.** The lists are positional -- the
walker takes a list number -- so an id in the same numbered list in two
titles is being asked the same question about the same thing. Of the 64 ids
on a list in both titles, 35 sit in the same numbered list, and the split by
id is sharp:

| id range | on a list in Pool of Radiance | in Silver Blades | on both | in the same list |
|---|---|---|---|---|
| 1-63 | 34 | 45 | 32 | **29** |
| 64-100 | 33 | 28 | 25 | 6 |
| 101-139 | 25 | 7 | 7 | **0** |

So the spell-effect half of the namespace is shared and the monster-special
half is not, which is what the racial seeds said too: Silver Blades gives an
elf 95 where Pool of Radiance gives 107. PROBABLE, on one measurement of
positional agreement and no reading of a Silver Blades handler.

## Naming Silver Blades' ids: five routes, and what each one is worth

Donald ruled on 2026-09-15 that the picker should offer this title's ids named
properly rather than staying at six or borrowing Pool of Radiance's names
unmarked. Four readings off the player's own disks filled 55 of the 90, and a
fifth -- reading the handler each id dispatches -- filled the other 35 and
corrected two of the 55. `tools/traitquery.py` takes all five and the runs are
in `cited/497`.

| route | what it reads | ids named | grade |
|---|---|---|---|
| the spell that writes it | this title's own per-spell record, `COMBAT2 +2937` | **40** of the 90 (and four more the engine ignores in a slot) | CONFIRMED |
| the same numbered check list as Curse | `--compare`, both titles' lists | 7 more | PROBABLE, and 6 of the 7 since CONFIRMED by their handlers |
| the same routine asking in both titles | the literal call sites | 1 (96), **withdrawn** -- the call site names no id | -- |
| the creature carrying it | the 71 `MON*` records on the six sides | 3 more, and **four refusals** | PROBABLE, all 3 since CONFIRMED |
| `GEN`'s racial seed | already in `goldbox/traits.py` | 2 more | PROBABLE, both since CONFIRMED |
| **the handler it dispatches** | `--handlers`, `COMBAT` at `$0800` | **35 more**, and 93 and 96 renamed | CONFIRMED |

### The spell that writes it, which is the strong one

**Every Gold Box title ships a per-spell record the engine copies when a spell
is cast, and one byte of it is the effect id that spell writes.** Pool of
Radiance's is `ECL65 +0`, 67 records of seven bytes, which `goldbox/effects.py`
already reads for their durations and `CAMP $1429` indexes as
`$9900 + (id - 1) * 7`. Curse and Silver Blades keep a nine-byte version in
`COMBAT2`, at `+2732` and `+2937`.

`tools/traitquery.py --spells` prints it. Four things hold the reading up and
no two of them share a source:

1. **Pool of Radiance's copy reproduces what is already known.** Its effect
   byte gives BLESS 1, SLEEP 53, INVISIBILITY 25, HASTE 39, STRENGTH 38 and
   DETECT MAGIC 5 -- six ids this project confirmed by other routes entirely,
   four of them from `P3-EFFECTS.D64` and one from five Sleep-struck orcs.
   Bit 7 of that byte is a flag rather than part of the id there: it is set on
   every cleric spell (1-8, 22-28, 36-44 and 56) and nothing else.
2. **The two later titles agree with each other** on the effect id for 54 of
   the first 56 spells, and on twenty more above 56 where both name tables
   resolve to the same spell.
3. **Every one of Silver Blades' 117 values falls inside its own 113-id
   namespace**, bar one: spell 59, whose value is the namespace size exactly
   and whose own slot in the name table is unused in this title and in Curse.
   Curse's row 59 is the same, at its own namespace size of 146.
4. **The message index beside it resolves.** Byte 1 indexes the combat
   messages that follow the spell names in the same table `goldbox/spells.py`
   reads, at `last spell + 1 + index` -- 57, 101 and 118, which are exactly
   the three "spells run to" boundaries that module already carries. Index 59
   is `IS BLESSED` in all three titles.

The check lists then corroborate it from the other direction, and they were
read through a different chain entirely (the walker's own operand): BARKSKIN's
13 sits on lists 11 and 12, "target, to hit" and "target, saving throw", where
an armour-class spell belongs; FIRE SHIELD's 112 on list 5, "target, weapon
damage"; FAERIE FIRE's 71 on list 11; INVISIBILITY TO ANIMALS' 69 on lists 1
and 16, the two miss-chance lists; PRAYER's 49 on lists 10 and 12; and the two
globes, 57 and 63, are the two ids `COMBAT` asks about by instruction,
seventeen bytes apart at `$15DC` and `$15ED`.

### Positional agreement got three of twenty-eight wrong

Both routes reach 28 of the same ids and they agree on 25. The three they
disagree on are all ids the later titles spent on a spell Pool of Radiance
does not have, and the spell table wins because it reads the write:

| id | what the check lists offered | what Silver Blades' own table says |
|---|---|---|
| 4 | starting to train with a Manual of Bodily Health | DISPEL EVIL |
| 27 | feather falling | FUMBLE |
| 35 | under an allied Prayer | CONFUSION |

**That is the calibration on the PROBABLE grade** -- roughly one in nine --
and it is why a name is taken from list agreement only when the check the list
performs makes sense of it. 31 "helpless" on list 7 beside hold, sleep and
snake charm does; 50 "mummy rot, blocking healing" on the two saving-throw
lists does not.

### The monster census refused four that agreement offered

The route Pool of Radiance's own table was built on, over the 71 `MON*`
records on the six Silver Blades sides. It named three -- 64 lands on this
title's eight poisoners, the same creature set that carries it in Pool of
Radiance, and BASILISK, MEDUSA and SARGATHA carry the pair 58/59 where Pool of
Radiance's basilisk and medusa carry 83/127 -- and it refused four more:

| id | the name agreement offered | the creature carrying it here |
|---|---|---|
| 60 | unused | IRON GOLEM |
| 65 | melee poison, +4 to save | COCKATRICE, which has no poison |
| 73 | rear claw rake | ANCIENT DRAGON, RED DRAGON, RED HATCHLING, WHITE DRAGON |
| 83 | petrifying gaze | ANCIENT DRAGON, WHITE DRAGON -- and this title's basilisk and medusa carry 58 and 59 instead |

### A spell row is not evidence until its name is its own

**73 reads like a 45th spell-named id and it is not**, and it is the one place
`--spells` has to be read with its other two columns rather than off the id
column alone. A code review raised it on 2026-09-15 and the answer is no.

`COMBAT2`'s name table gives **one string to a spell granted at two levels**,
so a shared pointer is the ordinary case rather than a fault: DETECT MAGIC
covers spells 5, 11 and 77 and all three write 5; HOLD PERSON covers 23 and 49
and both write 52. Fifteen names are shared between rows in Silver Blades,
**eleven have every row writing the same id, and each of the other four
contains a row that is in no spell group.**

Spell rows 95 and 96 both point at `$E471`, `CHARM PERSON OR MAMMAL`, and they
are the exception: **95 writes 73 with the message `IS PROTECTED`, 96 writes 11
with `IS CHARMED`.** Four things say 96 is the spell and 95 is a row whose
pointer was never set:

* `goldbox/spells.py`'s group table puts spell 96 in druid level 2 and **95 in
  no group at all** -- it falls in the gap between magic-user level 5 (91-94)
  and that druid entry;
* 11 is already this table's `charmed`, from CHARM PERSON at spell 10, so 96
  agrees with a name the table had before any of this;
* **Curse's row 95 writes the same 73 and the same `IS PROTECTED`**, under a
  pointer to `$E000` -- the first string in its table, which seven of its rows
  share and which is its unused-slot marker;
* ANCIENT DRAGON, RED DRAGON, RED HATCHLING and WHITE DRAGON carry 73 innately,
  and it is on list 6, where a resistance to spell damage is asked about. A
  druid's charm is neither.

**Two names already in the table depend on reading it this way**: 39 is taken
from HASTE at spell 48 and not from row 57, which shares CURE SERIOUS WOUNDS'
pointer and writes 39 as well, and 25 comes from INVISIBILITY and not from row
97, whose name reads `IS ALIVE`. Naming 73 from row 95 would be doing the
opposite of what those two do.

So the rule for `--spells`: **a row names an id only when the row's own message
fits the name and the row is in a spell group.** Silver Blades has twenty rows
in no group (57, 59-65, 95, 97, 99-108), and they are where a name goes wrong.

## The handler, read one id at a time

The 35 the four routes left -- 6, 7, 32, 50, 54, 56, 60, 65, 66, 67, 70, 72,
73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 86, 88, 90, 92, 98, 99, 103, 104,
105, 107, 108 and 110 -- were named on 2026-09-16 by reading the routine each
one dispatches, `docs/189-effect-97-from-the-code.md`'s method. Every reading
is CONFIRMED from the code; where a creature, an item template or a spell
routine carries the id as well, the table says so, and that second line is
what the *Monster Manual* would have predicted in every case it applies.
`tools/traitquery.py secret-of-the-silver-blades --handlers` prints all 90
and `cited/497/ssb-handlers.txt` is that run.

### The dispatch, and the anchors every reading stands on

The ask at `COMBAT $12AE` (the file runs at `$0800`, scored by
`entry_point` and pinned by the walker's list base landing at
`$F001 + 113 + 1`) dispatches a matched id with

```
$12C3  LDX $7F6E          the id the predicate parked
$12C6  LDA $EF90,X        low byte
$12CC  LDA $F001,X        high byte
$12D2  LDA $A928          Y as the walker passed it, 0 from a list
$12D5  JSR $FFFF          patched with the pair
```

so **the table index is the id itself** and every address lands inside
`COMBAT` ($16C5-$186B and $2430-$299C). Twenty ids that no list reaches
share `$2430`, which is Bless's handler and the table's filler, so a shared
address is not evidence about an id that only an instruction asks about. The
variables the handlers touch, each pinned by a handler whose meaning was
already CONFIRMED by the spell route:

| where | what | pinned by |
|---|---|---|
| `$A904` | damage type: bit 0 fire, 1 cold, 2 electricity, 3 magic, 4 acid, 5 a breath weapon, 6 a spell | `COMBAT $107A` picks the message "FROM FIRE" .. "FROM ACID" by the lowest set bit; Resist Fire (20) tests bit 0 and Resist Cold (10) bit 1; both breath handlers store `$A1`/`$A2` |
| `$945F` | the damage | Resist Fire halves it with `LSR $945F` |
| `$14EF` | zero the damage and the effect being applied | the tail every immunity ends in |
| `$14EA` | the same, only when the effect being applied is A | 18 and 95 cancel 53 and 11 behind a d100 |
| `$A903` | the saving-throw d20; list 12 is walked from inside `$0FAA` after the roll | Resist Fire on list 12 adds 3, the ring (61) adds 4: the AD&D numbers |
| `$A93B` | the save byte: bits 2-4 the column, bits 5-7 the modifier (1-4 a bonus, 5-7 a penalty of `n & 3`), bits 0-1 what a made save does | `$0FAA`, and the breath cone's `$0E`: column 3, half on a save |
| `$A915` | the attack d20 (100 on a natural 20) | `ECL64 $8506` stores it, then walks list 10; Bless increments it |
| `$7C00` | the staged record, slots at `$7CAD`, level `$7CA0`, hit points `$7D19`/`$7C76`, side `$7D0C` | `$138D` writes a granted id into the first free slot from 9 down |
| `$D4`/`$D5` | two creature-type bytes of the record, read from the *other* combatant through `$152A` (target) or `$1503` (attacker) | 47 tests `$D4` bit 2 and every giant and the OGRE have it; the LONG SWORD VS. GIANTS tests `$D5` bit 0 and only the giants have it |
| `$7E8C` | the attacker's weapon's `ITEMS` type entry, staged by `$909B` beside the item at `$7E7C` | `$23C9` reads the plus at `$7E80`; 90 reads `+7` bit 7, set on the mace, hammer, morning star, staff, flail and sling types |
| `$1649`, `$1675`, `$F2A6..$F2D5` | pick a target within range A, then fire ranged form X from six parallel six-entry tables: message, damage, save byte, duration, effect, damage type | form 4 is "TURNS TO STONE", form 2 "IS CONFUSED" with effect 35 |

Messages are the combat message table `goldbox/spells.py` already reads,
entry `118 + n` for `$137A` with X = n and entry n itself for `$136E`.

### The 35, by what the handler does

| id | handler | what it does | carried by |
|---|---|---|---|
| 6 | `$2927` | electricity: zero the damage | STORM GIANT, DREADLORD |
| 73 | `$292C` | `$A904` bit 5, a breath weapon: zero the damage | ANCIENT DRAGON, RED DRAGON, RED HATCHLING, WHITE DRAGON |
| 98 | `$2930` | cold: zero the damage | FROST GIANT, DREADLORD |
| 50 | `$27DC` | fire doubles the damage; cold halves it and adds 2 on the save | nothing shipped |
| 54 | `$27E2` | the same with the elements swapped | nothing shipped |
| 60 | `$2819` | weapon plus under 3: zero the damage | IRON GOLEM |
| 90 | `$28F1` | weapon type byte `+7` bit 7 (blunt): zero the damage | GIANT SLUG |
| 103 | `$294F` | weapon plus 0: zero the damage | GARGOYLE, MARGOYLE, DREADLORD |
| 76 | `$2861` | cancel 34 (Cause Disease) | PERIAPT OF HEALTH, `+14` |
| 92 | `$28FF` | cancel 29, 68 and 111 | DREADLORD; the halfling's seed |
| 99 | `$293B` | cancel 55, 30, 31 and 52 | DREADLORD |
| 65 | `$1705` | the gaze's tail without range or mirror: form 4, "TURNS TO STONE" | COCKATRICE |
| 86 | `$1810` | 64's poison with save byte `$C1`: -2 on the save | PHASE SPIDER |
| 88 | `$184D` | save on the paralysis column or 52, held, "IS PARALYZED" | DREADLORD, DRIDER |
| 66 | `$170B` | on an attack d20 of 20 (`ECL64 $84F9` stores it), damage = hit points + 10, "IS SWALLOWED!" | REMORHAZ |
| 75 | `$2849` | target has `$D5` bit 0: +1 on the attack d20, +1d12+1 damage | LONG SWORD VS. GIANTS, `+14` |
| 105 | `$2957` | target has `$D4` bit 3, melee only: + ranger level (`$7CD0`) damage | the ranger's seed |
| 67 | `$1726` | while the attack number is within the head count: form 0, "BREATHES...", 8 fire, range 3 | 12HD PYROHYDRA |
| 80 | `$1755` | half the time: form 1, "BREATHES...", 7 fire, range 2, then the turn ends | HELL HOUND |
| 70 | `$173F` | "GAZES...", form 2: "IS CONFUSED", effect 35 for 3d4, range 7 | UMBER HULK |
| 81 | `$176E` | "SPITS A STREAM OF ACID": range 7, hits 50% + 10% a square under six, 4d8, form 3 | GIANT SLUG |
| 83 | `$17D5` | the breath cone with `$A904 = $A2`: hit points of damage, cold, range 8, save vs. breath for half | WHITE DRAGON, the 10HD ANCIENT DRAGON |
| 104 | `$186B` | the same with `$A1`, fire, range 9 | RED DRAGON, RED HATCHLING, the 15HD ANCIENT DRAGON |
| 79 | `$28B0` | on a spell: fire heals the damage instead, electricity applies 42 "IS SLOWED", then zero the damage and effect | IRON GOLEM |
| 56 | `$2810` | at the start of combat apply 25, invisible, duration 12 | RING OF INVISIBILITY, `+14`; DREADLORD |
| 108 | `$2970` | apply 25 to itself, silently, no duration | nothing shipped |
| 82 | `$17A2` | combatants 0-7 alive and below level 5: afraid, "IS TERRIFIED BY A LICH" | nothing shipped |
| 77 | `$286B` | "IS BERSERKING", then target the nearest creature on its own side and change sides | nothing shipped |
| 107 | `$2866` | the same without the message; CONFUSION's outcome table at `$26E8` writes it on 50-69 of d100 | CONFUSION |
| 74 | `$2840` | double the movement being computed, as haste does | BOOTS OF SPEED, `+14` |
| 78 | `$249B` | `INC $A903`: +1 on every saving throw | STONE OF GOOD LUCK, `+14` |
| 72 | asked at `$16E0` | the gaze is reflected, "REFLECTS IT", when the gazer has 59 and the target has 72 | MIRROR and SILVER SHIELD +5, `+14` |
| 7 | `$2469` | target has `$D5` bit 2: +1 on the attack d20 | the gnome's seed; only the BUGBEAR has the bit |
| 32 | `$263D` | target has `$D4` bit 0: form 5, "DISAPPEARS!", and the caster's 4 ends | DISPEL EVIL's routine at `$1F96` writes it beside 4 |
| 110 | `$24EE` | re-instate at expiry; the meaning is in camp | the paladin's cure disease, `ECL65 $871D` |

**Two names the earlier routes gave are wrong and are corrected.** 93 was
"half damage from fire" by agreement with Curse and the FIRE GIANT; `$290E`
is `LDA #$01 / AND $A904 / BEQ / JSR $14EF`, which zeroes the damage, so it
is "immune to fire" -- what a fire giant is. 96 was "hit only by silver or
magical weapons" on the strength of `COMBAT $1191` asking about 96 in both
titles; the instruction there is `LDA $A902 / LDX $945D / JSR $3854`, the
effect being applied, and the 96 was `immediate_before` decoding backwards
through the wrong alignment. `$291D` cancels 53 and 11: immune to sleep and
charm, and the DREADLORD carries it. Ten PROBABLE entries whose handlers say
what the name says were promoted at the same time (18, 26, 31, 47, 48, 58,
59, 61, 64, 95); 43, 44 and 89 stay PROBABLE.

**110 is the one id whose meaning is not in `COMBAT`.** Its combat handler is
the one 15, 34, 43 and 44 share, which puts the effect back when it expires.
It is asked about in camp only, at `ECL65 $8730` (`ECL65` runs at `$8000`,
co-resident with `CAMP`; `tools/traitquery.py --sites` prints the site as
`$0F30` because it assumes `$0800`). `CAMP $1045`-`$1056` dispatches three
paladin actions into `ECL65`: `$8751` heals twice the paladin level at
`$7CCF` and spends record `$013` (lay on hands), `$871D` strips 31, 34, 43
and 44 from the target and restores the hit points the disease took, spends
record `$012`, and if the paladin has no 110 gives him one with duration
`$C7`. `GEN $0C6E` sets `$013` to 1 and `$012` to one per five levels at
creation; `LIBRARY $4383` hides the camp entries when either is 0; and the
camp's own handler table at `ECL65 $9496` -- twelve ids, `113 38 12 14 22
34 109 110 43 44 62 15`, with addresses at `$94A3`/`$94AF` -- sends 110 at
expiry to `$8657`, which recomputes `$012`, and 109 (lay on hands' twin,
duration `$C1`) to `$8650`, which sets `$013` back to 1. So a paladin with
110 in a slot has spent his cure disease and the uses come back when it
expires -- and a slot never expires, which is why the name says so.

### What the lists are for, from their call sites

The 2026-09-10 comment left this unread. Each numbered list is walked by one
`LDX #n / JSR` site, and the site says what is being asked:

| list | walked from | for | ids |
|---|---|---|---|
| 1 | `ECL64 $897F` | target, whether it can be seen | 37, 25, 69 |
| 2, 3 | `ECL64 $845E`, `LDX $9457 / INX / INX` | attacker's melee specials, one list per attack form | 64, 65, 86, 88; 65, 86, 88 |
| 4 | `ECL64 $85B1` | attacker, weapon damage | 29, 32, 66, 75, 105 |
| 5 | `ECL64 $85B6` | target, weapon damage | 28, 41, 60, 90, 103, 112 |
| 6 | `COMBAT $1019`, `$29DD` | target of spell damage | 6, 10, 17, 20, 28, 61, 73, 79, 93, 98 |
| 7 | `COMBAT $132C` | restrained | 31, 51, 52, 53 |
| 8 | `COMBAT2 $F549` | every combatant, at the start | 56, 82, 108 |
| 9 | `COMBAT $1134`, `$1595` | target, immunities, as an effect is about to be applied | 18, 28, 76, 79, 92, 95, 96, 99 |
| 10 | `ECL64 $850B` | attacker, to hit, with the d20 in `$A915` | 1, 2, 7, 26, 33, 36, 49, 75 |
| 11 | `ECL64 $853D` | target, to hit | 4, 8, 9, 13, 17, 30, 33, 45, 46, 47, 48, 71 |
| 12 | `COMBAT $0FF2`, inside the saving throw | target, saving throw, with the d20 in `$A903` | 8, 9, 10, 13, 17, 20, 33, 36, 45, 46, 49, 50, 54, 61, 78 |
| 13 | `ECL64 $868C` | target, on going down | (empty) |
| 14 | `SECSET64 $BA9D` | the monster's turn, choosing a ranged form | 58, 67, 70, 80, 81, 83, 104 |
| 15 | `ECL64 $903D`, `COMBAT2 $F63F` | attacker, at turn start | 3, 21, 27, 30, 35, 77, 106, 107, 5 |
| 16 | `ECL64 $8510` | target, miss chance, right after the attack d20 | 37, 89, 25, 69 |
| 17 | `SECSET64 $BC5A` | attacker, in the monster's choice | 1, 2 |
| 18 | `COMBAT $1438` | movement | 39, 42, 74 |
| 19 | `COMBAT2 $F6C3` | every combatant, each round | 23, 56 |
| 20 | `COMBAT $1026`, after a failed save | target, damage after a failed save | 50, 54 |

### Negative results from the handler pass

* **No shipped creature, item or spell carries 50, 54, 77, 82 or 108**, so
  those five rest on the handler alone. 82's message names a lich and the
  71 `MON*` records have none.
* **Dispel Evil's dismissal removes the wrong effect.** `$263D` ends with
  `LDA #$04 / JSR $2405` and `LDA #$23 / JMP $2405` -- 4 and 35 stripped
  from the caster, where 35 is CONFUSION and the id the touch should strip
  is its own, 32. A player sees the touch keep working after the first
  dismissal until the spell's duration runs out; not chased.
* **`immediate_before` can name an id that is not there.** `COMBAT $1191`
  and Curse's `$1194` are `LDA $A902`, and the tool reported 96 from a
  decode that entered the bytes mid-instruction. A literal it reports for
  a call whose preceding instruction is a three-byte absolute load is to be
  read by hand before it is believed.
* **`--handlers` cannot say which file holds Pool of Radiance's handlers.**
  `SPELLE00`, `SPELLE01`, `SPELLE04` and `SPELLE65` all score a load address
  near `$A700` that covers the table, so it prints the candidates rather
  than choosing; `SPELLE01` at `$A700` is the answer, from "What 61 does"
  above. The later two titles keep them in the ask's own file and need no
  choice.
* **`$953A` in `ECL65` is not an effect table.** It reads like one -- a run
  of `$41`-`$46` bytes indexed by something -- and it is the spell-to-class
  and level table `$8701` uses for memorising, indexed by spell id off the
  record's `$1B` list. An hour went on it.

**Curse of the Azure Bonds does not fully share Pool of Radiance's table
either, and `goldbox/traits.py` still says it does.** Its own spell-effect
table gives 3 to STICKS TO SNAKES, 4 to DISPEL EVIL, 7 to FAERIE FIRE, 27 to
FUMBLE, 35 to CONFUSION, 63 to MINOR GLOBE OF INVULNERABILITY, 68 to
FEEBLEMIND and 69 to INVISIBILITY TO ANIMALS, where the shared table reads
those eight as a Manual of Bodily Health, feather falling, an allied Prayer,
an unimplemented handler and two melee paralysis grades. So a Curse character
carrying one of the eight is named wrongly today. `tools/traitquery.py
curse-of-the-azure-bonds --spells` is the run; nothing has been changed for
that title here, because `#497 (The trait picker offers a Secret of the Silver
Blades character six names, and nobody has ruled on whether it should offer
Pool of Radiance's 129)` is about Silver Blades.

## Watching the asks

`tools/traitask.py` arms VICE text-monitor tracepoints (`tr exec`) on
`$3FE4`, `$402D` and `$403C`, which print the registers on every hit without
stopping the machine, so `tools/session.py` walks the party into the Slums
ambush and fights it normally. One boot, 21,850 trace lines, 34 turns, won.
Per id, *asked / reached the trait scan / matched*:

| id | walk | fight | why |
|---|---|---|---|
| 89 displaced | 14 / 14 / 0 | 58 / 50 / 0 | lists 8 and 16 |
| 98 regenerates | -- | 92 / 84 / 0 | list 19, once a combatant a round |
| 21 silence | 136 / 8 / 0 | 6370 / 98 / 0 | the surprise check, then list 15; the rest is `$07AE` scanning the array for a radius effect |
| 61 ring | -- | 8 / 0 / 0 | only an every-id sweep through `$3FE4` at the end; list 6 was never walked because nobody cast a spell |

Every id on a list reached the trait scan when its list was walked. No slot
matched, which is right: nobody had anything in one but 107 and 124, which
are on no list.

**And a slot that has an id something asks about changes the game.**
CONFIRMED, `cited/252/ask4`: 98, "regenerates 3 hit points a round",
written by `tools/traitask.py` into slot 9 of ROLAND's block with his
current hit points set to 1, and SILAS beside him at 1 with nothing in his
block. The roster's hit points (`$8300 + slot * $20 + $19`) read once a
turn through the fight:

| turn | ROLAND (98 in a slot) | SILAS (control) |
|---|---|---|
| 0 | 1 | 1 |
| 7 | 5 | 1 |
| 10 | 1 (hit) | 1 |
| 13 | 4 | 1 |
| 19 | 7 (his maximum) | 1 |
| 24 | 1 (hit) | 1 |
| 25 | 4 | 1 |
| 29 | 7 | 1 |
| 37 | 7 | 1 |

Up by three a round and capped at his maximum, which is handler 98 at
`SPELLE01 $ACA4` to the instruction (`LDA #$03 / ADC $6C19 / CMP $6B76 /
BCC / LDA $6B76 / STA $6C19` -- the `ADC` has no `CLC` in front of it, which is
the 1 to 5 on turn 7). SILAS never moved. Neither character had ever had the
effect from the game: the byte was ours, and the engine ran the handler.

## What 61 does, and what the C64's own ring does not

The handlers live in `SPELLE01` at `$A700`. `$2AFF` is the damage type:
bit 0 fire, bit 1 cold, bit 2 electricity, bit 3 set by a creature's attack
form (79's fire touch writes `$09` at `$ABEF`), bit 4 acid. Handler 61 at
`$A9EE`:

```
$A9EE  JSR $ADB0          113's handler: if fire, one point per die off $A4F7, never below the dice count
$A9F1  BEQ $AA06          not fire: nothing
$A9F3  JSR $ADB0          and again
$A9FC  LDA $2AFF / AND #$08 / BNE $AA06
$AA03  JSR $A705          a fire spell: $A4F7, the damage, becomes 0
```

Handler 20, the Resist Fire spell, at `$A873` only halves.

**Watched, `cited/252/fire9`:** MALCYON, a level-1 magic-user given
three memorised Burning Hands, cast one at ROLAND, who had 61 written into
slot 9 by `tools/traitask.py` and no ring. The trace, in list 6's order:

```
.C:3fe4  A:71 X:02          113 asked about, for character 2
.C:402d  A:71               the array said no; the ten slots
.C:3fe4  A:3D X:02          61 asked about
.C:402d  A:3D               the array said no; the ten slots
.C:403c  A:3D X:09          matched, slot 9 -- handler 61 dispatched
.C:3fe4  A:7A X:02          122, and on down the list
```

and the screen: `ROLAND IS HIT FOR 1 POINTS OF DAMAGE FROM FIRE`. So a
fire spell's damage path asks the slots about 61, finds the byte we wrote,
and runs the handler -- CONFIRMED. What the handler then did to one die of
damage is not visible: `$ADB0` never takes the damage below the dice count,
so one point stays one point, and the `$A705` branch that would have made
it zero was **not** taken, which refutes the reading of bit 3 as "a
creature's attack form" -- Burning Hands had it set, or `$A705` does
something else. What bit 3 means is UNKNOWN. **The experiment that shows
the magnitude** is Fireball (spell 47, 5d6 at level 5) at a 61-carrier
against a control: expect two per die off, or zero, against the control's
full roll. The ring-wearing control of that run (LADY KATHERINE, the C64
RING OF FIRE RESISTANCE readied) was never reached: the driver's fight
ran out its budget after the first cast.

**This paragraph said the C64's ring is inert. It is not**, and the
correction is `docs/183-the-two-rings-of-fire-resistance.md`. The disks carry
five RING OF FIRE RESISTANCE records and four of them grant: `ITEMFILE1D` on
POOL4 and three readied on monsters in `MON32` and `MON56`, all

```
45 cd a7 42 03 00 06 00 00 00 00 88 13 00 3d 81
```

-- `+14 = 61`, `+15 = $81`, which `ECL65`'s table sends to `$ADD4` like
`$80`. Readying `ITEMFILE1D`'s ring in camp writes 61 into a trait slot and
un-readying it takes 61 back out, one byte each way, watched
(`cited/285/ring-81`).

What stood here rested on the **fifth** record, `ITEMFILE17` record 3 on
POOL3 -- `45 cd a7 42 00 00 00 00 01 00 00 88 13 00 00 00`, `+14 = 0` and
`+15 = $00`, with the protection bytes `+4`/`+5` a Ring of Protection uses
zero too. That one does grant nothing, and three READY presses on it moved no
byte at all (`cited/285/ring-shipped`). `load_item_templates` handed it
back because it kept the first record it met for a printed name and POOL3
sorts before POOL4.

Templates that set bit 7, with the corrected count: RING OF FIRE RESISTANCE
(`+14` 61, `+15` `$81`), CLOAK OF DISPLACEMENT (89, `$85`), GAUNTLETS OF OGRE
POWER (38, `$83`, which goes to the array through `$AE2D`), TWO-HANDED SWORD
+1 +3 VS UNDEAD (3, `$88`), LONG SWORD +3 (82, `$84`, an alignment lock
rather than an id) and LONG SWORD +2 (240, `$84`, the same lock -- and it too
has a flattened copy in `ITEMFILE17`).

## A trait the editor wrote, from the Add button to the handler

Everything above was measured on bytes `tools/traitdrive.py` and
`tools/traitask.py` poked into a `.d64`. That proves the engine reads a slot
and says nothing about **Wish's own write path**, which is what
`WISH_EXPERIMENTAL_TRAITS` guards -- so `#417 (Prove the game applies a trait
Wish wrote, so WISH_EXPERIMENTAL_TRAITS can come off)` took the same
measurement again with the byte written by the editor: the real `WishWindow`,
the real `button_trait_add`, the real `TraitPicker`, the real `File > Save`.
`tools/traitsave.py` drives it and replaces only `TraitPicker.exec`, which is
the modal wait for a person.

**Resist Fire, id 20, added to ROLAND on `PORSAVE13.D64`.** CONFIRMED at every
step:

| step | what came back |
|---|---|
| `File > Save` | **one** differing byte in the 174,848-byte image -- `SAVEDGAME0` offset 1709, save slot 2, field `0x0AD`, `0` -> `20` |
| loaded in the game | `$4D00 + 2 * $100 + $AD` reads `[20, 0, ...]` after `BEGIN ADVENTURING` |
| a fire spell at him | `.C:3fe4 A:14 X:02` asked, `.C:402d` the array said no, `.C:403c A:14 X:00` **matched slot 0**, handler 20 dispatched |
| the damage | 7 hit points before, 7 after, against 7 -> 6 in a control run one byte apart |
| `ENCAMP > SAVE` | the disk the game wrote carries `2: [20, 0, ...]` |
| that disk booted again | live block `[20, 0, ...]`, and `ENCAMP > REST` for eight game hours (21:00 to 05:00 the next day) left all three occupied blocks unchanged |

The control is the same save without the edit, driven with identical arguments.
Over more than 21,000 asks each, the two runs' per-id tables are identical on
every id, including id 20's 12 asks and 1 that reached the trait scan. The only
difference anywhere is the match: 1 in the edited run, 0 in the control, whose
`trace.log` holds no `$403C` line at all.

**Slot 0 rather than slot 9**, because `EffectsView.add` fills the first free
slot while `SPELLE04 $ADD4` scans from the ninth down. `LIBRARY $402D` reads
all ten with `LDX #$09` and counts down, so the position changes nothing --
which this run is the measurement of, since `#252 (Does a C64 trait
slot apply an item-granted effect id, or only the ones its own READY routine
wrote?)`'s ids all sat in slot 9.

## What this means for a conversion

For `#232 (An item-granted effect is dropped on the way through the neutral
record, with no report)`, whose C64 writer drops `granted_effects` with a
reason that is now wrong on both clauses:

1. **Write the id into a free trait slot.** That is what READY writes, all of
   it, and the engine applies it wherever a list names it. Scan 9 down to 0
   for a zero the way `$ADD4` does; a full block means the array, which is
   `$ADEF`'s own answer to `#236 (A character converted to the C64 with more
   than ten innate effects loses the extra ones with no report)`.
2. **Give the converted item the power bytes the C64 grants and revokes
   by.** DOS keys the grant on item byte `0x3D` with bit 7 of `0x3E`; the C64
   keys it on `+14` with bit 7 of `+15`. Same design, two bytes each. A
   converted ring with `+14 = 61`, `+15 = $81` -- the bytes both ports use
   for this ring -- is granted by `$ADD4` when it goes on and un-granted by
   `$AE13` when it comes off; a ring with `00 00` grants nothing and, if 61
   is in the slot from somewhere else, leaves it there for ever. That
   experiment has now been run: READY, UNREADY and READY again on the
   converted item, one byte moving each way (`cited/285/ring-81`), so
   `$81` reaching `$ADD4` is CONFIRMED in the running machine rather than
   only from `ECL65`'s table. Whether any code reads the low bits of `+15`
   for anything but the dispatch is still UNKNOWN, and nothing in the record
   or the effect arrays moved on either press.
3. **The DOS payload bytes have no C64 home and need none.** `0C 00` on a
   ring is what the DOS ready path writes for every item grant; the C64
   handler holds the magnitude. The one grant that has a value of its own, a
   strength item's `26 00 00 vv 01`, is the C64's `$83` power and the array,
   not a slot -- a separate case for the writer.
4. **The reverse trip** (C64 to DOS) can rebuild `id 00 00 0C 00` from a slot
   id that is not racial, since the DOS record for an item grant is that
   shape for every item.

## Negative results

* **`LIBRARY $402D` is the only reader of the block's contents**, absolute
  and indirect: `tools/recordsweep.py --indirect` for `0xAD`-`0xB6` finds
  four hits, all in picture and wall files.
* **The world's copy of `$DA63`-`$DC62` is not the tables**: the region holds
  something else until `COMBAT` loads. Read them in a fight.
* **`SQRPACI64 $05A5`, `$063A` and `$065A` zero `$6BAD,X` with whatever X the
  predicate left**, and on an array match X is the array index, 0-63. If 32,
  31 or 55 ever sits in the array rather than a slot, the cure writes a zero
  up to 54 bytes past the block. Not a reader's error -- the three
  instructions are quoted above -- but no character in any specimen has one
  of the three in the array, so what a player sees is UNKNOWN.
* **`CAMP $12EA`**, the "if he has it, dispatch it" entry, is named by no
  file. Its neighbour `$12F8` is the live one.
* **The character sheet does not list a trait**, so the "boot, `VIEW`, confirm
  the game lists it" of `#417 (Prove the game applies a trait Wish wrote, so
  WISH_EXPERIMENTAL_TRAITS can come off)` cannot be done in Pool of Radiance: ROLAND's
  sheet with 20 in his first slot is the same twenty-two rows as any other
  character's -- name, race, alignment, class, six abilities, money, level,
  experience, hit points, armour class, the two items in hand and `THACO`.
  The live record read and the handler dispatch above are what replaced it,
  and both say more than a listing would.

## The runs

`cited/252/ask1` (the cloak readied, the fight, the tables), `ask4/`
(the regeneration fight), `ask11/` (the READY toggles from camp), and the
fire runs (`fire9/` is the cast that reached ROLAND; `fire1`-`fire8` are the boot hangs and the driver being found: the spells bar takes CAST before the row, and the target is picked with NEXT and TARGET rather than a cursor), and the runs in between, which are how the READY driver was found: the panel is in
marching order (`ask2`, `ask3`), the item list prints an unidentified item
by its noun (`ask3`), the list's bar takes the verb before the row and the
row's highlight is not white at the name column (`ask4`, `ask5`), no key
on the keyboard or a numpad joystick selects a row from the world's VIEW
(`probe1`, `probe4`), because the toggle refuses a magical item outside
camp (`ask8`-`ask10`). Each holds `traits.jsonl`, `trace.log`,
`asks.json`, and `tools/traitask.py --report` prints the table.

`cited/417` holds the editor half: `write1/` (the copy, the disk File >
Save wrote, and the one-byte diff), `cast-edited/` and `cast-control/` (the
differential pair), `boot1/` and `reload/` (the engine's own save, the reload
and the eight-hour rest, with ROLAND's sheet in `sheet.txt`).

`cited/497` holds the naming runs, all of them from the disks and none
of them needing an emulator: the three `--lists` runs of 2026-09-10, then
`ssb-vs-curse-lists.txt` and `ssb-vs-por-lists.txt` (`--compare`), `por-`,
`curse-` and `ssb-spell-effects.txt` (`--spells`), and `ssb-handlers.txt`
(`--handlers`, all 90). Each is one `tools/traitquery.py` invocation and
re-running it reproduces the file.
