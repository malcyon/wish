# What transfers between Gold Box titles, and what does not

Established by taking Pool of Radiance's decoders to Curse of the Azure Bonds
unchanged and recording what broke.

## The strongest statement available

**Pool of Radiance's own exported character, imported into Curse and exported
again, comes back with 15 of its 580 bytes changed.** That is the game's own
arithmetic rather than a diff of two specimens, and it is why the record layout
should be assumed to transfer until a title disproves it.

The 15:

| Offset | Field | What the import did |
|---|---|---|
| `0x065`-`0x06B` | second ability array | written from `0x014`-`0x01A` |
| `0x073` | `char_class` | zeroed |
| `0x098` | fighting level | set |
| `0x0C1` | gold | zeroed |
| `0x0C3` | platinum | set to 300 |
| `0x0FE`, `0x0FF` | portrait head, body | zeroed |
| `0x10F` | roster armour class | recomputed |

Untouched: experience, level, the per-class array, class bits, hit points,
spellbook, race, age, alignment, sex and the 36-byte combat icon.

The 300 platinum is the same constant the DOS reimplementation carries as
`SetCoins(Money.Platinum, 300)` and the amount every one of SSI's pre-generated
Curse characters ships with. Two independent artefacts agreeing on an arbitrary
number is as close to proof as this work gets.

## Near-certain to transfer

| | Detail |
|---|---|
| Record size | 580 bytes in both |
| Every named field in `por/layout.py` | same offset, same width |
| The four blocks a record splits into | `0x000`-`0x0FF` slot, `0x100`-`0x11F` roster, `0x120`-`0x21F` items, `0x220`-`0x243` icon |
| Save slot | the first 256 bytes of the record |
| Biased encodings | `60 - value` for THAC0, AC and the roster's current pair; `48 + value` for the armour bonus; `12 - AC` for the item protection nibble |
| Race indexing | 1-based, `DWARF=1` … `HUMAN=7 MONSTER=8` |
| Class indexing | 0-based; `class_bits` at `0x0EB` is the field to prefer |
| Per-class level array | eight bytes at `0x0C9`; paladin and ranger are slots 6 and 7 |
| Disk container | D64 |
| Map files | `GEO`, 1024 bytes, four 16×16 planes |
| Item word table | `ITEMNAMES`: 256 low bytes, 256 high bytes, then strings |
| Item type table | `ITEMS`, 128 × 16 |
| Item records | 16 bytes |
| Spell ids | 1-56 identical |
| Saves | verbatim uncompressed memory images, no checksum, no validation |

`por/geo.py` decodes all sixteen Curse `GEO` files with no change. Reciprocity
is 15114/15360 (98.4%) across Curse's sixteen against 28540/28800 (99.1%)
across Pool of Radiance's thirty — same distribution, same decoder.

## Near-certain **not** to transfer

| | Pool of Radiance | Curse |
|---|---|---|
| exported character, load address | `$6B00` | `$7C00` |
| exported character, filename marker byte | `$01` | `$02` |
| save image, load address | `$4900` | `$4B00` |
| save files on the disk | `SAVEDGAME0` + `SAVEDGAME1` | one file, `SAVEAZURE` |
| roster block location | `$8300`, a separate file | `$6700`, in the same file |
| party x, y, facing | `$49C0`-`$49C2` | `$4BC0`-`$4BC2` |
| area id | `$4BC2` | `$4DC2` |
| character slots | `$4D00`, twelve of them | `$4F00`, at most eight |
| name table | none | `$5700`, 16 bytes per character |
| `ITEMNAMES` resident base | `$6F00` | `$9E00` |
| `LIBRARY` `GEO` stem table | `$40FC` (live) | shifted |

Also local to each title, always: **which `GEO` file is which area**; the file
stems that exist at all (Curse has no `SPELLN` — its spell names live in
`COMBAT2` and again in `ECL65`); the screen layout and status-line row; and
every overlay base.

**Everything before the character slots in Curse is Pool of Radiance's layout
plus `$200`.** Try the shift first on a new title; do not assume it holds.

## Two traps this comparison set

* **Two files can share a name.** Curse ships `SAVEAZURE` twice — a 7424-byte
  pre-generated party on side B3 and a 2030-byte truncated image on side A2 that
  ends mid-slot. A reader that takes the first match gets the wrong one.
* **A rip may not be a plain image.** `por/d64.py` refuses a 175531-byte rip:
  35 tracks plus error bytes. Skip it rather than "fixing" the reader.

## Fields a later title uses that an earlier one leaves at zero

Both of Curse's extras land in regions Pool of Radiance marks `UNKNOWN`, so
nothing was displaced. Expect the same shape on any successor: **the new
title's fields are in the old title's gaps**, which is one more reason for a
layout table that tiles the whole record.

| Offset | What | Confidence |
|---|---|---|
| `0x065`-`0x06B` | a second copy of the seven ability scores | CONFIRMED |
| `0x098` | fighting level — the level the attack tables are indexed by | CONFIRMED |
| `0x0A4` | non-zero only for characters who turn undead | PROBABLE |
| `0x0B6` | non-zero only for Curse's paladin and ranger | GUESS |

## The regression test that keeps both honest

`tests/test_second_game.py` runs the *same* invariant checks over both games
through the same code paths: a record decodes and round-trips byte-identically;
`class_bits` is exactly one bit per non-zero slot of the eight-byte array;
the roster block equals record bytes `0x100`-`0x11F`; the save geometry is the
first game's constants plus a known delta; every `GEO` decodes above 92%
reciprocity; `ITEMS` is 128 × 16.

A change made for one game that moved a field, narrowed a region or shifted a
base fails on the other side. **Add a third title to that test rather than
forking the decoders.**
