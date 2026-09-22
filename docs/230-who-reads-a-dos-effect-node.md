# Who reads a DOS effect node past its duration

A C64 trait slot carries an effect id and nothing else, so a converter that
writes one as a DOS effect node has to choose bytes 3 (the value) and 4 (the
flag) itself. This page answers, from each DOS engine's own code, which ids'
nodes the engine reads past the duration, what a readied magical item writes,
what a strength item's value byte holds, whether Secret of the Silver
Blades' C64 halfling id 92 is the effect DOS gives a halfling and what DOS's
own 92 protects against, and whether any C64 title's Dispel Magic can remove
an effect held in a trait slot. It is Stage 2 of the plan on
#621 (A C64 character carrying an effect in a trait slot cannot be saved as a DOS or Amiga save, because the writer keeps only the eight ids the game's own importer keeps),
and the DOS column of #600 (The neutral record has no field for an effect's remaining duration or a paladin's cure-disease uses, so a converted character loses both)'s
Stage 4c.

The reader is [`tools/dos/dosaffectreads.py`](../tools/dos/dosaffectreads.py);
[`tests/dos/test_dosaffectreads.py`](../tests/dos/test_dosaffectreads.py) pins
every address and answer below against the player's own `GAME.OVR` and
`START.EXE` from the archives. The C64 half is
[`tools/c64/dispelread.py`](../tools/c64/dispelread.py), pinned by the same
test file against the player's C64 disks. Everything is static; no emulator
was run. The
node layout is `docs/162-spc-permanence.md`'s: id, duration `u16`, value,
flag, next pointer.

## The answers

| question | Pool of Radiance | Curse of the Azure Bonds | Secret of the Silver Blades | grade |
|---|---|---|---|---|
| ids whose value or flag byte an id-specific reader touches | 25 of 127 | 29 of 146 | 21 of 113 | CONFIRMED |
| readers of byte 3 and byte 4 for **every** node | Dispel Magic `0x2940E`, `remove_affect` `0x2AF70` | `0x3120B`, `0x3518D` | `0x2F9EF`, `0x35EE9` | CONFIRMED |
| what a readied magical item writes | `id 00 00 0C 00`, for eight power bytes | `id 00 00 FF 01`, for power `0x80` only | `id 00 00 FF 01`, for power `0x80` only | CONFIRMED |
| a strength item's node | `26 00 00 vv 01`, `vv` the pre-item strength encoded | none: no power other than `0x80` writes a node | none | CONFIRMED |
| C64 halfling 92 against DOS halfling 97 | -- | -- | two different effects | CONFIRMED |
| what a DOS 92 node cancels when a spell's effect is applied | -- | -- | Fear (111) only; no DOS effect cancels Ray of Enfeeblement (29) or Feeblemind (68) | CONFIRMED |
| can the **C64** Dispel Magic remove an effect held in a trait slot | no | no | no | CONFIRMED |

## How it was read

Each engine calls an effect's handler through one dispatcher, `handler(effect,
node, player)` with the node at the handler's `[bp + 8]`, indexed by the node's
id in a table of far pointers the engine fills at start-up. The reader finds
the dispatcher, the table, `find_affect`, `remove_affect` and `add_affect` by
instruction pattern (the module docstring says which), then follows the node
pointer through every handler, every `find_affect` caller and every routine
that reads a character's chain head: every `es:[di + n]` made through it,
every copy into a local, every call it is handed to at the matching argument
slot. A hand-off to an indirect call raises rather than being skipped; none
occurs in the three engines.

| | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|
| dispatcher | `GAME.OVR:0x2AEEA` | `0x350E9` | `0x3620B` |
| handler table | `ds:0x6828`, ids 1-139 | `ds:0x6FC0`, ids 1-146 | `ds:0x87E6`, ids 1-113 |
| hook the dispatcher calls instead while a flag is set | none | `[0x720C]` -> `0x125BA`, flag `[0x759C]` | `[0x89C6]` -> `0x145D3`, flag `[0x8DB8]` |
| `find_affect` | `0xBA:0x2199`, `START.img:0x2D39`, 41 callers | `0xED:0x9D`, `0x399EA`, 74 | `0x151:0xAC`, `0x3AA19`, 82 |
| `remove_affect` | `0x2AF10` | `0x3512C` | `0x35E8E` |
| `add_affect` | `0xB0:0x52` | `0xE3:0x57` | `0x145:0x4D` |
| chain head in the record | `0x7F` | `0xF2` | `0xFB` |

**Pool of Radiance's table slots `0x80`-`0x8B` are item powers, not effects**:
readying an item dispatches on its byte `0x3E` directly (`0x2269D`, add;
`0x2257D`, remove), so a node whose id is 128 or more would reach an item
handler with the node where the item should be. Its effect ids are 1-127.
Curse's slot 147 and Silver Blades' slot 120 are the hook pointer, which sits
past each table's end. **A converter must never write a node whose id is
outside these ranges.** CONFIRMED.

Two negative results bound the method. Reading each `find_affect` caller's
whole routine as well as the code after the call, for the locals only one id
owns, found nothing the forward read had not; and switching off the
recursion into callees loses exactly Pool 34, Curse 12, 34, 38 and 146 and
Silver Blades 12, 34 and 38, so the sets the test pins fail without it.

## (a) The ids whose value or flag byte is read

Every id not listed has a handler, `find_affect` callers and id-testing chain
walkers that never touch bytes 3 or 4. **CONFIRMED** for the handlers and the
constant-id `find_affect` callers; the chain-walker attribution is by the ids
each walker tests at byte 0.

| title | ids read past the duration |
|---|---|
| Pool of Radiance | 11, 12, 14, 15, 28, 32, 34, 38, 39, 40, 43, 44, 49, 50, 57, 62, 74, 75, 78, 88, 89, 95, 99, 102, 103 |
| Curse | 3, 11, 12, 13, 14, 15, 28, 32, 34, 38, 39, 40, 43, 44, 49, 62, 78, 88, 89, 90, 91, 95, 99, 102, 128, 137, 139, 144, 146 |
| Silver Blades | 3, 11, 12, 14, 15, 28, 34, 38, 39, 40, 43, 44, 49, 62, 64, 83, 89, 91, 100, 104, 107 |

`tools/dos/dosaffectreads.py --title T --ids ...` prints which reader and which
byte for each. The ids the plan named, all CONFIRMED:

| id | Pool | Curse | Silver Blades |
|---|---|---|---|
| 5 Detect Magic | `0x11DF6`, empty | `0x129B8`, empty | `0x145CA`, reads nothing |
| 45 Protection from Evil, 10' Radius | `0xEFD2`, the attacker only | `0x1010B` | `0x110DE` |
| 8 Protection from Evil | the same handler as 45 | the same as 45 | the same as 45 |
| 61 | `0x100EB`, never the node | -- | -- |
| 89 displacement | `0x110EB` reads **and writes** byte 3 | reads 3 | reads 3 |
| 7, 95 (Silver Blades gnome, elf) | -- | -- | nothing read |
| 92, 97 (Silver Blades halfling) | -- | -- | nothing read |
| racial 18, 26, 47, 48, 90, 97, 107, 124 | nothing read | nothing read (90 is not racial here and reads 3) | nothing read (107 reads 3) |
| class 8, 105, 134 | -- | nothing read | nothing read |

The writes are real per-effect state. In Pool of Radiance 89 keeps
displacement's per-round flag in bit 4 of byte 3; 32, 74, 75, 95, 99 and 103
store 0 into the flag byte, 74, 75 and 99 just before removing their own node;
and 12 and 38 keep the strength they replaced.

**Every node's bytes 3 and 4 are read by two routines whatever the id**, and
that is the part a converter's choice of bytes shows up in:

* **Dispel Magic** (Pool `0x2939D`, Curse `0x31199`, Silver Blades
  `0x2F982`) walks every node of every target. A node whose byte 3 is `0xFF`
  is passed over; any other has its low nibble taken as the level the dispel
  roll is made against. So `INNATE_PAYLOAD`'s `FF` makes a node permanent
  against Dispel Magic as well as against the clock, and Pool of Radiance's
  item grant, `0C`, is dispelled as a twelfth-level effect. CONFIRMED in all
  three. Curse also compares the high nibble for ids 40 and 91, Silver Blades
  for 40, 91 and 100 -- which is why those ids are on the list.
* **`remove_affect`** runs the node's handler with "remove" only when byte 4
  is non-zero (`cmp byte ptr es:[di + 4], 0` at the addresses in the table
  above). A flag of 0 means that taking the node off does not run the
  handler's remove path. CONFIRMED.

A `find_affect` caller whose id is computed reads bytes 1-2 (the duration,
the spell-apply replacement test) and nothing past them, in all three titles.

## (b) A readied magical item

**Pool of Radiance**: the power byte is the handler id. CONFIRMED.

| power | handler | writes |
|---|---|---|
| `0x80`, `0x81`, `0x82`, `0x85`, `0x86`, `0x88`, `0x8A`, `0x8B` | `0x11B35` | `add_affect(item[0x3D], 0, 0x0C, 0)`: **`id 00 00 0C 00`** |
| `0x83` | `0x11BB2` | `add_affect(38, 0, vv, 1)`, section (c) |
| `0x84` | `0x11D00` | no node: the item's low nibble is compared with the wearer's alignment |
| `0x87` | `0x11D8F` | no node: unreadies below strength 19 |
| `0x89` | `0x11DD5` | no node: on removal, removes effect 23 |

The four C64 passive-power items agree with this reading of their power byte:
the cloak `$85` and sword `$88` land on the grant, the gauntlets `$83` on the
strength handler (and carry 38 at `+14`, the id the DOS handler writes as a
constant), and the alignment-locked `$84` on the alignment check
(`goldbox/traits.py`). PROBABLE that the two ports' power bytes are one
encoding: four of four agree, and the C64 side was not read here.

After the grant `0x11B35` dispatches "add" to the granted id's own handler
with a **null node** (`0x11B92`-`0x11B9B`). Handler 89 dereferences its node
unconditionally, so readying the Cloak of Displacement reads, and may write,
byte 3 of `0000:0003`, the divide-error interrupt vector. PROBABLE from the
code; settle it in DOSBox-X by breaking at the runtime address of
`GAME.OVR:0x110FC` while readying the cloak and reading `ES:DI`.

**Curse and Silver Blades** route an item whose power's low seven bits are
zero through the hook, which writes `add_affect(item[0x3D], 0, 0xFF, 1)`:
**`id 00 00 FF 01`**, not `0C 00` (Curse `0x12609`, Silver Blades `0x14629`).
The switch that handles every other power (Curse `0x28B61`, powers 0-6 and
8-13; Silver Blades `0x28B84`, powers 0, 1, 3, 5 and 9) reaches no
`add_affect` within three levels of calls, 32 and 11 routines walked. So in
these two titles power `0x80` is the only item grant, and its node is
undispellable and runs its handler on removal. CONFIRMED.

## (c) Pool of Radiance's strength item

`0x11BB2` calls the set-strength routine (`0xB0:0x7A`, `0x2C046`) with 18/00
and then `add_affect(38, 0, vv, 1)`. `vv` is the character's strength before
the item, in the engine's one-byte encoding (`0x2BFCE`): **score + 100, or
percentile + 1 when the score is 18**, where 18/00 is percentile 100 and
encodes as 101. CONFIRMED. ADDERLY's girdle node, `26 00 00 5C 01`, is 18/91.

Two cases change `vv`, both CONFIRMED from `0x2C046`:

* if a strength node (id 12 or 38) with byte 3 below `0x80` is already on
  the chain, `vv` is **that** node's saved value, and that node's byte 3
  becomes `0x80` + the current strength's encoding;
* a character already stronger than 18/00 is not changed, and `vv` is
  `0x80 | 101`, `0xE5`.

Curse and Silver Blades write no strength-item node at all: the girdle and the
gauntlets act through the recompute (`docs/204-the-dos-ability-pair.md`), so
there is nothing to write for them.

## (d) Silver Blades' halfling: C64 92, DOS 97

**They are two effects.** CONFIRMED from both ports' code.

| | C64 Silver Blades | DOS Silver Blades |
|---|---|---|
| 92 | `COMBAT $28FF`: cancels effects 29, 68 and 111 (Ray of Enfeeblement, Feeblemind, Fear) through `$14EA` | `0x13B81`: on "add", cancels 111 through `0x10D4A`, the same "cancel if this is the effect being applied" helper; effect 82's handler (`0x13701`), which puts Fear on a target, also skips one that has 92 |
| 97 | `$2430`, the filler handler twenty ids share | `0x13C8F`: the constitution saving-throw bonus, bands 4-6 +1 to 18-20 +5 on record `0x19`, the same bands as Pool of Radiance's 97 |

So a C64 halfling's 92 is not DOS's 97 renamed. DOS's 92 is the same kind of
effect -- an immunity -- and nothing reads its node past the duration, so it
can be written as `5C 00 00 FF 00`.

### What DOS Silver Blades' 92 protects against

**Fear, and nothing else.** CONFIRMED from the code; this section used to leave
Ray of Enfeeblement and Feeblemind UNKNOWN, and reading the one route an
immunity can take settled it.

Every title applies a spell's effect through one routine that parks the id in
a global, walks check list 9 over the target, and adds the node only if the
global is still set; a handler cancels by handing one helper the id it blocks,
or 0 for whatever is parked (`dosaffectreads.apply_walk`, `cancels`):

| | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|
| apply routine, global | `0x2C540`, `[0x6817]` | `0x37303`, `[0x6FAD]` | `0x37EB0`, `[0x87D3]` |
| cancel helper | `0xEC5B` | `0xFF00` | `0x10D4A` |
| list 9 | 105-112, 124, 125 | 105-112, 124, 125, 63, 129 | 18, 28, 63, 76, 79, **92**, 95, 96, 99 |

In Silver Blades 92 is on list 9 and its handler hands the helper 111 and
nothing else. **No handler of the 113 hands it 29 or 68**: the fourteen that
call it cancel 0, 11, 52, 53, 55 or 111. Nothing else compares the global
with 29 or 68 either: its seven reads are in the helper, the apply routine,
the list walk's prologue at `0x35FC9` (which compares it with 82 and 91) and
one test for 64 at `0x30A7C`. The rest of what the plan asked to read:

* the only `find_affect` naming 92 as a constant is `0x13755`, inside effect
  82's handler, which skips a target that has 92;
* the five callers that take their id from `ds:0x1B3D` (`0x5BD2`, `0x5ED5`,
  `0x1CA0A`, `0x1CDC0`, `0x2B0B6`) index bytes 1-4 of that array, which hold
  **31, 34, 43 and 44** -- helpless and the three disease ids -- and each hands
  the same id to `remove_affect`. They are cures, the list `docs/171` found in
  the C64's own cure disease, and none of them is a protection.

Curse is the control that the reader sees such a handler when one exists: its
133 cancels 29, 68 and 142. So a converted C64 Silver Blades halfling written
with `5C 00 00 FF 00` keeps his immunity to Fear and to effect 82, and **no
DOS Silver Blades node exists that keeps his immunity to Ray of Enfeeblement
or Feeblemind** -- the engine has none to give. A DOS-born halfling has
neither immunity and has 97's constitution bonus on his saving throws, which
the C64's 97 does not give. That is a difference between the two engines,
read from both, and not a gap in our reading.

## (e) The C64's Dispel Magic never reaches a trait slot

**CONFIRMED for all three C64 titles, from the code.** Each title's spell
table sends both DISPEL MAGIC spells (41 and 46 in all three) to one routine
per route, and every one of them finds an effect through the **array-only**
predicate, so an effect held only in a trait slot is never found and never
removed:

| | Pool of Radiance, combat | Pool of Radiance, camp | Curse | Silver Blades |
|---|---|---|---|---|
| table | `SPELLE65 +0x211`, 9 bytes, routine at +7 | `ECL65 +0`, 7 bytes, +5 | `COMBAT2 +2732`, 9 bytes, +2 | `COMBAT2 +2937`, 9 bytes, +2 |
| routine | `SPELLE00 $ABCE` | `SPELLE04 $AA5B` | `COMBAT $18BD` | `COMBAT $1C7C` |
| ids tried | 63 down to 1 | 63 down to 1 | 48, from `$F10A` | 35, from `$F213` |
| predicate | `$3FE1` (array only) | `$3FE1` | `$409C` (array only) | `$3851` (array only) |
| removal | `$A82F`, asks `$3FE4` | `CAMP $131F` on the index `$3FE1` returned | `$11DB`, asks `$409F` | `$11D0`, asks `$3854` |
| caster's level | `$2B05` | `$2878` | `$A90A` | `$A90A` |

For each id the array holds for the target, a magnitude of `$FF` is skipped
and any other has its low nibble taken as the effect's level; the chance is
50% plus 5% for every level the caster is above it, or less 2% for every
level below (`$AC10` and its three twins), and the routine compares it with
the random routine's result for `Y = $63`. **No
instruction in the four routines, their chance routines or their removals
names the trait block** (`$6BAD` in Pool of Radiance, `$7CAD` in the later
two). In Pool of Radiance the census of the block's 17 absolute references
finds only the predicate, the racial seed, the item grant and revoke, the
slot `SPELLE04 $AA18` writes 32 into and the cures; the later titles' 20 and
21 were not each attributed, and none of them lies in a dispel routine.

So the C64's own rule is that a trait-slot effect cannot be dispelled, and
DOS's `FF` value byte, which its Dispel Magic passes over, is the faithful
one. `tools/c64/dispelread.py` prints the table above.

Three things were seen on the way, none of them about a trait slot:

* **Curse and Silver Blades never test their list's first entry.** The loop
  counts X down from 48 (35) and stops at 1, and the byte at index 0 is 1,
  Bless, in both. CONFIRMED that the routine never reads it; PROBABLE that a
  player on those two C64 titles cannot dispel Bless, since no second dispel
  routine exists (the chance routine's bytes occur once in each title). Cast
  Bless on the enemy side and Dispel Magic over it in a C64 Curse fight to
  settle it.
* **The C64 ranges are narrower than DOS's.** Pool of Radiance dispels array
  ids 1-63 only and the later titles only their lists; DOS walks every node.
  That is the concern of
  #600 (The neutral record has no field for an effect's remaining duration or a paladin's cure-disease uses, so a converted character loses both)
  -- a running effect's value byte -- and not this page's.
* **One removal can clear a slot indirectly.** Removing an effect whose
  magnitude has bit 7 set dispatches its handler, and Pool of Radiance's
  handler for 22 and 32 (`SPELLE01 $A889`) revokes 55 through the combat
  revoke, which looks in the ten slots before the array. So dispelling a
  flagged Slow Poison can clear a poison held in a slot. PROBABLE, from the
  code only; it touches 55 and no id this page's converter writes.

## The value and flag bytes a converted trait slot gets

The rule follows from (a), (b) and (e). **CONFIRMED** for every row but the
last:

| a C64 trait-slot id that is | DOS bytes 3-4 | why |
|---|---|---|
| unread past the duration in this title ((a)'s complement), not an item grant | `FF 00` | undispellable, as on the C64; no remove path runs, as when the C64 clears a slot |
| Pool of Radiance, the `+14` of a readied item with power `0x80`-`0x82`, `0x85`, `0x86`, `0x88`, `0x8A`, `0x8B` | `0C 00` | what DOS itself writes for that item ((b)) |
| Curse or Silver Blades, the `+14` of a readied item with power `0x80` | `FF 01` | the same ((b)) |
| on (a)'s list for this title and no item grant | none known | a reader of that byte needs its own value; read per id |

A readied Pool of Radiance item's `0C` is dispellable at level 12 on DOS and
not on the C64. That is how DOS treats the same item on a DOS-born character,
so the row writes the destination's own form; whether that is acceptable is a
decision for the conversion, not a reading.

## What this does not settle

* **Code that holds a node in a global.** Every `find_affect` caller stores
  into a local (41, 74 and 82 of them); a routine that copies a node pointer
  into a global and reads it elsewhere would not be seen. None was found, and
  none was searched for beyond that.
