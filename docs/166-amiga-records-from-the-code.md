# The Amiga Curse and Silver Blades records, read from the routines that build them

`#55 (Decode the Amiga Curse and Silver Blades records)`. Both titles keep
their characters, monsters and items on disk in the **DOS layout** and expand
each into the Amiga one at load time. That expander is the shift map, written
by the people who wrote the port, and it settles the four measurements `#55 (Decode the Amiga Curse and Silver Blades records)`
was holding open for specimens nobody has.

Every offset here is a file offset into `/Curse` on Curse of the Azure Bonds
disk 1 or `/Secret` on Secret of the Silver Blades disk 1, read with
`tools/amiga68k.py`. `tools/amigaunpack.py` prints each map, and
`tests/test_amiga.py` runs it against `goldbox/amiga.py`'s shapes, so the two
cannot drift.

## What changed, and what it corrects

| open measurement | answer | grade |
|---|---|---|
| Curse's druid slot array starts at `0x133`, `0x134` or `0x135` | **`0x134`.** The three arrays are **six bytes each** where DOS spends five, at `0x12E`, `0x134` and `0x13A` | CONFIRMED, four indexing sites in two executables |
| Curse item node `0x03B` = 52 and `0x03E` = 47: pad plus `charges`, or two pads? | **Two pads.** `charges` is at `0x03F`, `effect` `0x040`, `power` `0x041`, and all three read zero on the nine specimens | CONFIRMED, the constructor writes them by name |
| The Amiga Silver Blades item node, never measured | **70 bytes**: Curse's 66 exactly, plus a `u32be` at `0x042` that heads a scroll's extra spell nodes | CONFIRMED, the same constructor and unpacker in both binaries |
| Curse windows `0x0F9`-`0x0FB` and `0x13F`-`0x142` | `field_83_87` is `0x0F6`-`0x0FA` at shift 0 and the pad is **`0x0FB`**; `0x13F` is the magic-user array's sixth byte and DOS's `gap_13c` is **`0x140`-`0x142`** | CONFIRMED |

Two things that were not on the list came with them:

* **`sex` and `alignment` are located.** Reading GALAIN's sheet on screen
  could not place either, because one character cannot separate a byte from
  its neighbours. Curse keeps them at `0x11A` and `0x11C`, Silver Blades at
  `0x0BA` and `0x0BB` — three and two single-byte copies, named by their DOS
  source offsets. CONFIRMED.
* **Silver Blades' `0x0FD` pad**, PROBABLE because nothing carries an item,
  is measured: the unpacker copies DOS `0x14E`+19 to `0x0EA` and DOS
  `0x161`+69 to `0x0FE`, so the byte between them is written by nothing.

## The routines

| what | Curse (`/Curse`) | Silver Blades (`/Secret`) |
|---|---|---|
| record unpacker, packed DOS record -> Amiga record | `0x270A6` | `0x281A2` |
| its opening `setmem(record, size, 0)` | `0x1AC` = 428 | `0x154` = 340 |
| item unpacker, 63 packed bytes -> the node | `0x26EF8` | `0x27FE6` |
| item constructor, fifteen arguments | `0x1C1EA` | `0x1B862` |
| `ITEM<n>` template loader, stride `0x3F` = 63 | `0x1F2D6` | `0x1F7D8` |
| monster loader, decompresses `MON<n>CHA` to `0x1A6` = 422 | `0x26306` | — |
| slot-array indexing | `0x288`, `0x482`, `0x9F4` | `0x5D4` |

**The packed source is the DOS record, and that is measured rather than
assumed.** Curse's monster loader hands the decompressor `0x1A6` = 422, which
is the DOS Curse record size, and **all 26 of the unpacker's copy boundaries
land on a `goldbox/dos_layout.py` Curse field boundary**; Silver Blades' 22
land on its own. A copy that ended one byte inside a field would show up
immediately, and none does.

## Curse: the map the unpacker writes

`tools/amigaunpack.py --shape curse-of-the-azure-bonds --size 0x1ac 270a6 273ea`.

| DOS | Amiga | bytes | shift | what |
|---|---|---|---|---|
| `0x001` | `0x000` | 15 | −1 | the name, then a NUL at the count byte's index |
| `0x010` | `0x010` | 100 | 0 | abilities through `thac0_base` |
| `0x074`, `0x075` | same | 1, 1 | 0 | race, class |
| `0x076` | `0x076` | 2 | 0 | age, byte-swapped |
| `0x079` | `0x079` | 108 | 0 | spellbook, attack level, saving throws, movement |
| `0x0E5`-`0x0E9` | same | 1 each | 0 | level, drain, turn power |
| `0x0EA` | `0x0EA` | 8 | 0 | the thief percentages |
| — | `0x0F2` | 4 | | the effect chain, rebuilt |
| `0x0F6`, `0x0F9`, `0x0FA` | same | 3, 1, 1 | 0 | `field_83_87`, in three pieces |
| — | **`0x0FB`** | 1 | | **pad** |
| `0x0FB` | `0x0FC` | 14 | +1 | the money block, seven words byte-swapped |
| `0x109` | `0x10A` | 16 | +1 | class levels and former class levels, a byte loop |
| `0x119`, `0x11A`, `0x11B` | `0x11A`, `0x11B`, `0x11C` | 1 each | +1 | **sex**, `gap_11a`, **alignment** |
| `0x11C` | `0x11D` | 11 | +1 | attack forms, AC base, strength bonus |
| `0x127` | `0x128` | 21 | +1 | experience (swapped), class bits, hit dice, **and the three slot arrays — see below** |
| `0x13C` | `0x140` | 9 | +4 | `gap_13c`, whose first word is byte-swapped; portrait, icon, party order, size |
| `0x145` | `0x149` | 8 | +4 | icon colours, `gap_14b`, item count at `0x150` |
| — | `0x151` | 1 | | **pad** |
| — | `0x152`-`0x189` | 56 | | the item pointer array and the heap pointers, rebuilt |
| `0x185` | `0x18A` | 4 | +5 | hands used, encumbrance at `0x18C`, byte-swapped |
| `0x191` | `0x196` | 4 | +5 | `gap_191` |
| `0x195`-`0x197` | `0x19A`-`0x19C` | 1 each | +5 | `field_10c_10f` |
| `0x198` | `0x19D` | 14 | +5 | THAC0, AC at `0x19F`, roster tail, hit points at `0x1A9` |
| — | `0x1AB` | 1 | | trailing pad; 422 + 5 = 427 is odd |

`field_83_87` was refused as unplaceable before this. Placed, it reads
`00 00 01 00 00` in all four played characters — **`goldbox/dos.py`'s DOS
constant, byte for byte, in 24 of 24 DOS records** — and five zeros in all
eleven pregens. That third byte is the "party flag at `0x0F8`" earlier work
named without knowing what field it belonged to.

## The three spell-slot arrays are six bytes on the Amiga and five on DOS

Three routines in `/Curse` read a slot count as

```
0000284 movea.l  -$4302(a4), a0        ; the selected character
0000288 adda.w   #$12e, a0
000028c move.b   (a0, d0.l), d4        ; d0 = 6 * class + (level - 1)
```

with `class` taken from byte 0 of a 16-byte spell-table entry and `level`
from byte 1 (`/Curse` `0x288`, `0x482`, `0x9F4`). The table at `g1ede`
assigns Curse's ids 1..100 to class 0 (36 spells, cleric), class 1 (**77, 78,
79, 80** — the druid four a ranger gets), class 2 (45, magic-user) and class
3 (15, levels 5-7, cast by nothing that memorises). So:

| array | Amiga | DOS |
|---|---|---|
| cleric | `0x12E`-`0x133` | `0x12D`-`0x131` |
| **druid** | **`0x134`-`0x139`** | `0x132`-`0x136` |
| magic-user | `0x13A`-`0x13F` | `0x137`-`0x13B` |

The sixth byte of each Amiga array — spell level 6 — has no DOS counterpart.
A second binary agrees: `/Secret`'s Curse-import routine at `0x26F64` reads a
Curse record's arrays at exactly `0x12E`, `0x134` and `0x13A`.

**The DOS side is five, from DOS's own code.** `tools/dosspellslots.py sites
--game CURSE` finds three `FillChar(record + 0x12D, 15, 0)` in Curse's
`GAME.OVR` — 15 = 3 × 5 — which is the same evidence
[`164-ssb-spell-slot-block.md`](164-ssb-spell-slot-block.md) used for Silver
Blades' 28 = 4 × 7. And Silver Blades' Amiga arrays are **not** widened:
`/Secret` `0x5D4` indexes them as `record[0x0CE + 7 * class + level - 1]`,
seven each, and the unpacker copies each of the four as its own seven bytes.
So the widening is Curse's alone.

### A defect in the port: the monster loader copies them flat

The unpacker's fifth-from-last copy is 21 bytes from DOS `0x127` to Amiga
`0x128`: experience, class bits, hit dice **and all fifteen packed slot
bytes in one run**. Into six-byte arrays. So a monster loaded from
`MON<n>CHA` gets

* its cleric slots right, at `0x12E`-`0x132`;
* its **druid slots one byte early** — `0x134` holds what the packed record
  has for druid level 2;
* its **magic-user slots two bytes early** — `0x13A` holds packed level 3;
* **nothing at all** in `0x13D`-`0x13F`, the top of the magic-user array.

CONFIRMED from the two routines; what a player sees is UNKNOWN, and settling
that means watching a spellcasting monster in Amiga Curse combat and counting
what it casts. It is recorded here rather than in `goldbox-bugs.md` for that
reason. `tests/test_amiga.py::test_the_curse_monster_loader_misplaces_two_of_the_slot_arrays`
pins it so it is not smoothed back into the shift map.

## Silver Blades: the map, and the spellbook

`tools/amigaunpack.py --shape secret-of-the-silver-blades --size 0x154 281a2 285b0`.
The four shift steps `goldbox/amiga.py` already carried — 0, −102, −101,
−100, −99 — all reproduce, and the three pads are located to the byte at
`0x095`, `0x0C7` and `0x0FD`. `sex` and `alignment` are the single-byte
copies of DOS `0x11F` and `0x120`, landing at `0x0BA` and `0x0BB`.

**The spellbook's bit order is no longer an inference from six specimens.**
The unpacker walks the packed record's 117 one-byte flags and, for each,
sets or clears one bit of `record[0x71 + i / 8]` using a mask table at
`g234e`, which reads

```
01 02 04 08 10 20 40 80
```

— least significant bit first, by the table's own contents. The mask table
is the answer; the specimens were the corroboration.

## The item node, from the constructor

Both titles build an item with the same routine compiled twice — `/Curse`
`0x1C1EA`, `/Secret` `0x1B862`. It allocates the node, clears it, and writes
fifteen arguments in `goldbox/dos_layout.py`'s own item order:

| Amiga | field | Amiga | field |
|---|---|---|---|
| `0x00`-`0x29` | display text, NUL-separated | `0x37` | cursed |
| `0x2A`-`0x2D` | next item, `u32be` | `0x38`-`0x39` | weight, `u16be` |
| `0x2E` | type index | `0x3A` | quantity |
| `0x2F` | **pad** | `0x3B` | **pad** |
| `0x30`-`0x32` | name1, name2, name3 | `0x3C`-`0x3D` | value, `u16be` |
| `0x33` | plus | `0x3E` | **pad** |
| `0x34` | plus save | `0x3F` | **charges** |
| `0x35` | readied | `0x40` | effect |
| `0x36` | hidden | `0x41` | power |

and Silver Blades adds `0x42`-`0x45`, a `u32be` the unpacker clears
(`/Secret` `0x28194`).

**The nine specimens read `0x7F` at `0x28`, 52 at `0x3B` and 47 at `0x3E`,
and none of those is a field.** The constructor writes none of them and its
`setmem` would leave all three zero; the items in `SAVE/savgamA.dat` came
through the other path, the `ITEM<n>` template loader, which unpacks each
63-byte template into a stack struct it never clears and copies all 66 bytes
into the node. Nine identical values from one uninitialised stack frame.

This refutes the reading `#55 (Decode the Amiga Curse and Silver Blades records)` carried from 2026-08-26 to 2026-09-05, that
`0x3E` was `charges` and 47 was a Chain Mail's charge count. **A constant
across nine specimens is not a constant; it is nine specimens** — the third
time this corpus has taught that lesson, after `readied` and
`movement_current`.

### Silver Blades' `0x42`: a scroll's extra spells

An item whose type index is `0x49` is a scroll, and it carries three spell
ids in the bytes the constructor calls `charges`, `effect` and `power`. A
scroll with more than three chains further 70-byte nodes through `0x42`,
`quantity` of them: `/Secret` `0xDE` walks the chain reading `node[0x3F]`
through `node[0x41]` with the top bit as a "scribed" flag, and the vault
writer at `0x3D6D2` writes each sub-node out after the item.

**The main item chain is `0x2A` on both titles, not `0x42`.** `#28 (Decode an
Amiga saved game, not just a character file)` recorded the vault writer
stepping through `0x42`; that is the scroll sub-chain, and the writer's outer
loop advances through `0x2A` (`/Secret` `0x3D768`). Corrected here.

**PROBABLE, and it belongs to the DOS table:** DOS Silver Blades' item is 67
bytes with four unexplained bytes at `0x3F`-`0x42` that are zero in 12 of 12.
Four bytes is a DOS far pointer, and the Amiga's counterpart of exactly that
region is a pointer. Settling it: a DOS Silver Blades save holding a scroll
of more than three spells.

## Two hand-offs to the DOS field tables

* **DOS Curse `gap_13c` and DOS Silver Blades `gap_14e` begin with a 16-bit
  field.** Both unpackers byte-swap the word at its Amiga counterpart —
  Curse `0x140`, Silver Blades `0x0EA` — alongside age, the money block,
  experience and encumbrance, and they swap nothing that is not a `u16` or
  `u32`. PROBABLE that the DOS field is a `u16le`; what it means is UNKNOWN
  and it reads zero in every specimen of either title.
* **A second defect, PROBABLE.** `/Secret`'s Curse-import routine reads the
  incoming Curse spellbook at `record[0x79 + i]` for `i` = 1..100 and sets
  bit `i` of the Silver Blades mask. Curse's spellbook is 100 bytes at
  `0x79` and `attack_level` is at `0x0DD`, so the last read is
  `attack_level` rather than a spell flag, and the first byte of the book is
  never read. A character imported from Amiga Curse should therefore arrive
  missing the lowest spell in his book and holding a spurious one at the top.
  Not reproduced in the running game; settling it means importing a Curse
  cleric into Amiga Silver Blades and opening the spellbook.

## Method, so it can be repeated

The unpacker is found from the loader that calls it. `tools/amiga68k.py refs`
on the `MON%s%s` or `ITEM%s` string finds the loader; the loader hands a
decompressed buffer, a base offset and a destination to one routine, and that
routine is the unpacker. `tools/amigaunpack.py` then reads it: `movmem` is
SAS/C's `(source, destination, length)`, `setmem` is `(pointer, size,
value)`, and the byte swappers are the two globals a `u16` and a `u32` are
handed to on the way out.

A **gap** in that tool's output is three different things and has to be read
in the routine before it is called an insertion: a genuine alignment pad, a
pointer the loader rebuilds, or a region copied by a byte-at-a-time loop the
tool does not follow. Curse's `0x10A`+16 is the third kind.
