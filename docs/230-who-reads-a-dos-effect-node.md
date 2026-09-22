# Who reads a DOS effect node past its duration

A C64 trait slot carries an effect id and nothing else, so a converter that
writes one as a DOS effect node has to choose bytes 3 (the value) and 4 (the
flag) itself. This page answers, from each DOS engine's own code, which ids'
nodes the engine reads past the duration, what a readied magical item writes,
what a strength item's value byte holds, and whether Secret of the Silver
Blades' C64 halfling id 92 is the effect DOS gives a halfling. It is Stage 2
of the plan on
#621 (A C64 character carrying an effect in a trait slot cannot be saved as a DOS or Amiga save, because the writer keeps only the eight ids the game's own importer keeps),
and the DOS column of #600 (The neutral record has no field for an effect's remaining duration or a paladin's cure-disease uses, so a converted character loses both)'s
Stage 4c.

The reader is [`tools/dos/dosaffectreads.py`](../tools/dos/dosaffectreads.py);
[`tests/dos/test_dosaffectreads.py`](../tests/dos/test_dosaffectreads.py) pins
every address and answer below against the player's own `GAME.OVR` and
`START.EXE` from the archives. Everything is static; no emulator was run. The
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
can be written as `5C 00 00 FF 00`. What stays UNKNOWN is whether DOS covers
Ray of Enfeeblement and Feeblemind for a 92 carrier somewhere other than its
handler: the handler names only Fear. Settle it by reading the five
table-driven `find_affect` callers in Silver Blades that take their id from
`ds:0x1B3D` (`0x5BD2`, `0x5ED5`, `0x1CA0A`, `0x1CDC0`, `0x2B0B6`) and the
spell handlers for 29 and 68.

## What this does not settle

* **Whether a C64 trait slot can be dispelled.** DOS's `FF` makes a node
  immune to Dispel Magic. If the C64's Dispel Magic never looks at the ten
  trait slots, `FF` is the faithful choice for a trait id; if it does, it is
  not. UNKNOWN; settle it by reading the C64 Dispel Magic handler (its spell
  row through `tools/c64/traitquery.py --spells`) for a read of `$6BAD`.
* **Code that holds a node in a global.** Every `find_affect` caller stores
  into a local (41, 74 and 82 of them); a routine that copies a node pointer
  into a global and reads it elsewhere would not be seen. None was found, and
  none was searched for beyond that.
