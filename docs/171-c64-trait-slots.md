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
Radiance's; the three C64 titles share the mechanism but not the numbers
(`tools/traitquery.py` derives the predicate for Curse and Silver Blades).

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
`work/issue252/ask11/`, MALCYON with a CLOAK OF DISPLACEMENT staged readied
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
by `tools/traitask.py` while `COMBAT` was resident (`work/issue252/ask1/tables.json`):

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
array, not a slot), 55, 32, 24, 5, 12, 16, 53. An id in a slot is honoured
**where a list names it**, and nowhere else.

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
CONFIRMED, `work/issue252/ask4/`: 98, "regenerates 3 hit points a round",
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

**Watched, `work/issue252/fire9/`:** MALCYON, a level-1 magic-user given
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
(`work/issue285/ring-81/`).

What stood here rested on the **fifth** record, `ITEMFILE17` record 3 on
POOL3 -- `45 cd a7 42 00 00 00 00 01 00 00 88 13 00 00 00`, `+14 = 0` and
`+15 = $00`, with the protection bytes `+4`/`+5` a Ring of Protection uses
zero too. That one does grant nothing, and three READY presses on it moved no
byte at all (`work/issue285/ring-shipped/`). `load_item_templates` handed it
back because it kept the first record it met for a printed name and POOL3
sorts before POOL4.

Templates that set bit 7, with the corrected count: RING OF FIRE RESISTANCE
(`+14` 61, `+15` `$81`), CLOAK OF DISPLACEMENT (89, `$85`), GAUNTLETS OF OGRE
POWER (38, `$83`, which goes to the array through `$AE2D`), TWO-HANDED SWORD
+1 +3 VS UNDEAD (3, `$88`), LONG SWORD +3 (82, `$84`, an alignment lock
rather than an id) and LONG SWORD +2 (240, `$84`, the same lock -- and it too
has a flattened copy in `ITEMFILE17`).

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
   converted item, one byte moving each way (`work/issue285/ring-81/`), so
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

## The runs

`work/issue252/ask1/` (the cloak readied, the fight, the tables), `ask4/`
(the regeneration fight), `ask11/` (the READY toggles from camp), and the
fire runs (`fire9/` is the cast that reached ROLAND; `fire1`-`fire8` are the boot hangs and the driver being found: the spells bar takes CAST before the row, and the target is picked with NEXT and TARGET rather than a cursor), and the runs in between, which are how the READY driver was found: the panel is in
marching order (`ask2`, `ask3`), the item list prints an unidentified item
by its noun (`ask3`), the list's bar takes the verb before the row and the
row's highlight is not white at the name column (`ask4`, `ask5`), no key
on the keyboard or a numpad joystick selects a row from the world's VIEW
(`probe1`, `probe4`), because the toggle refuses a magical item outside
camp (`ask8`-`ask10`). Each holds `traits.jsonl`, `trace.log`,
`asks.json`, and `tools/traitask.py --report` prints the table.
