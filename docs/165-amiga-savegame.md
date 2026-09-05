# The Amiga saved game, read from the routine that writes it

`#28 (Decode an Amiga saved game, not just a character file)`. Every number
here comes from the save and load routines in the three Amiga executables --
`/Curse` on Curse disk A, `/Secret` on Silver Blades disk A, `/program` on
Pool of Radiance disk 1 -- read with `tools/amiga68k.py` and proved by
`tools/amigasavegame.py`, which parses every saved game on the machine through
this map and checks itself against the signature scan, the variable array and
the file length. Seven specimens, all clean: the three found saves (`CurseA`,
`Secret 1`, `poolgame` slot A) and the four Pool of Radiance slots WinUAE was
watched writing for `#109 (A save slot written onto an Amiga disk is not
offered by the game's picker)`.

**Grades.** A row marked CONFIRMED is what the code writes and reads, which no
edited specimen can poison. Where a value's *meaning* rests on the code beside
its writes it says so; where it rests on a found specimen it is PROBABLE and
says which.

## The file is a sequence of writes

Each save routine is a straight run of `write(fd, buf, len)` with the return
checked against `len`, so the file is exactly this concatenation. The loader
reads the same sequence back into the same globals.

| write | Curse (`/Curse` `0x26af8`) | Silver Blades (`/Secret` `0x27c10`) | Pool of Radiance (`/program` `0x27750`) |
|---|---|---|---|
| container number | 1 | 1 | **none** |
| VM block 1, `$4900`-`$4CFF` | 2048 | 2048 | 2048 |
| VM block 2, real `$6B00`-`$6EFF`, file name `$4D00`-`$50FF` | 2048 | 2048 | 2048 |
| VM block 3, real `$9700`-`$98FF`, file name `$5100`-`$52FF` | 1024 | 1024 | 1024 |
| ECL text buffer | 7680 | **none** | 7680 |
| square struct | 8 | 6 | 10 written, 7 of them the struct |
| mode before / view type | 1 | 1 | 1 |
| game mode | 1 | 1 | 1 |
| wallset table, entries 1-3 | 12 | 12 | none: copied into `$4AFA`-`$4AFF` first |
| party count | `u16be` | `u16be` | one byte |
| party | records, items, effects | records, effects | 8 x 41 filename slots |
| first record or name at | `0x3219` | `0x1417` | 12813 |

CONFIRMED, all three, from the code; the totals land the first record where
`goldbox.amiga.party_in_savegame` found it on every specimen.

**The variable array is three heap blocks, not one**, written from three
pointers (`[g3d00]+$9600`, `[g3dbe]+$f800`, `[g588a]+$f400` on Curse). That is
the same three regions [`163-dos-vm-address-map.md`](163-dos-vm-address-map.md)
derived for DOS from the ECL VM's address classifier, and it means the
contiguous `$4900`-`$52FF` naming is a file artefact on the Amiga exactly as
on DOS. File offset of a word is `header + 2 * (addr - $4900)`, big-endian.

**The party count is the table of contents.** The Curse and Silver Blades
loaders read the word, then loop that many times -- allocate a record
(`0x1ac` = 428, `0x154` = 340), read one block, link it into the party list.
`$503E` is **cleared to zero on load** and rebuilt, so the word in the file
is what says how many characters follow. Pool of Radiance's loader reads its
count byte and then the 328-byte name table, and opens the first `count`
names.

## The square region

### Curse, 24 bytes at `0x3201`

| offset | field | in `savgamA.dat` | evidence |
|---|---|---|---|
| `0x3201` | x, `u16be` | 3 | `g3f5e`; the step routine wraps it at 15; new game writes 7 |
| `0x3203` | y, `u16be` | 14 | `g3f60`; new game writes 13 |
| `0x3205` | facing, doubled: 0 N, 2 E, 4 S, 6 W | 2 | `g3f62`; screen read `3,14 E` |
| `0x3206` | wall in front of the party, `fn(x, y, facing)` | 0 | `g3f63`, rewritten at `0xdb96` on every step -- the field DOS keeps at 12804 |
| `0x3207` | a square property, `fn(x, y)` | 0 | `g3f64`, rewritten at `0xdb7e` on the same step; meaning UNKNOWN |
| `0x3208` | pad | 0 | `g3f65` is referenced nowhere in the code |
| `0x3209` | **game mode before the current one** | 4 | `g5889`: `prev = mode; mode = n` at every mode change, restored after |
| `0x320a` | **game mode** | 2 | `g3d56`, see the enumeration below |
| `0x320b` | wallset entry 1, (WALLDEF block, slot) `u16be` pair | (1, 1) | `g5eaa`; the loader hands each non-zero pair to the `WALLDEF%s` loader, block into 780-byte slot 1-3 |
| `0x320f` | wallset entry 2 | (2, 2) | |
| `0x3213` | wallset entry 3 | (3, 3) | |
| `0x3217` | party count, `u16be` | 4 | the writer walks the list; the loader loops on it |

### Silver Blades, 22 bytes at `0x1401`

Single-byte x, y and facing (`g57a0`-`g57a2`; new game writes 7, 13, 0; facing
written as 0/2/4/6), then the wall in front and the square property from the
same step routine (`g57a3`, `g57a4`), a pad nobody references (`g57a5`), the
mode before (`g74a3`), the mode (`g525c`), the wallset table (`g7be8` + 4) and
the `u16be` count. The shipped save reads `07 0d 00 00 00 00 | 04 00 |
00 00 00 01 ff ff ff ff ff ff ff ff | 00 06`: entry 1 = (block 0, slot 1) and
entries 2-3 empty, **which is exactly what both titles' new-game
initialisation writes** (`0x1d6e8` on Curse, `0x1d8c4` on Silver Blades).

### Pool of Radiance, 13 bytes at 12800

The save writes **ten** bytes from `h32+0x176f` and the struct there is
**seven**: x, y, facing (doubled), the wall in front (`fn(x, y, facing)` at
`0x2ec1c`), a square property (`fn(x, y)` at `0x2ec54`), and two bytes nothing
references. The wallset table sits at `h32+0x1776`, so the write's last three
bytes are the first three of table entry 0, which is never written. Then
`h32+0xc1`, the **view type** (1 = 3D, 2 = overland; saved and restored as a
(previous, current) pair the way Curse saves its mode), `h32+0xba`, the game
mode, and the count byte. The five zeros at 12805-12809 are therefore not
fields, and nothing reads them from the file for any purpose.

The Pool of Radiance wallset table is copied into the VM array before the
write, entry *i* to `$4AF9+i` and `$4AFC+i` for *i* = 1..3 -- which is
[`141-dos-savegame.md`](141-dos-savegame.md)'s wallset triple and its (1, 2, 3)
index map. Curse and Silver Blades write the table as its own twelve bytes
instead.

### The game mode, one enumeration on all three titles

From the code beside each write of the byte: **2 camp** (the camp handler
saves the old mode, sets 2, restores on exit), **3 overland**, **4 3D
adventuring** (new game, and after combat), **5 combat** ("A battle
begins..." follows the write on Curse), **7 the ending**. A save is made from
camp, so the byte reads 2 in every save the game writes. The Silver Blades
shipped save reads **0**, the value a load leaves in it (`prev = mode; mode =
0`), so that file was not written from camp by a player -- PROBABLE, one
specimen, and a fact about the specimen rather than the format.

**Hand-off to DOS.** DOS's 12806 (1 indoors, 3 outdoors) and 12807 (always 2)
are the view type and the game mode of this same source. PROBABLE for DOS --
read off the Amiga port, not off `GAME.OVR`; the same routine there settles
it.

## Variable words the code names

| address | Curse code | what |
|---|---|---|
| `$49C5` | `[block1]+$978a` | geo block id, handed to the `GEO%s` loader, which wants 1024 bytes |
| `$49E6` | `+$97cc` | indoors |
| `$49FC` | `+$97f8` | low byte written from `g3d3e` at save; read back into it at load |
| `$49FF` | `+$97fe` | `2 * g63d1 + g63d0` at save; split back at load |
| `$5012` | `[block2]+$fe24` | the container number, written from the same byte the file opens with |
| `$503E` | `+$fe7c` | party size; **cleared on load** |

The clock at `$49C6`-`$49CB` is read through the map by `tools/amigasavegame.py`
and agrees with the status line on the two saves that were read on screen.

## The container number

Byte 0 is `g5858` on Curse: 1 for disk A, 2 for disk B, chosen by the disk
prompt at `0x13e4e`, and it feeds every `GEO%s` and `WALLDEF%s` load through a
`%d` path builder (`0x2c36a`). Silver Blades' `g5191` is set to 5 by the
new-game code and to 1 or 2 elsewhere, so it is an area group rather than a
disk; the shipped save holds 1. Pool of Radiance has no byte and keeps the
number in `$5012` alone.

## Still open

* **The square property, `fn(x, y)`.** Rewritten on every step on all three
  titles; 25 on Pool of Radiance's slot A square, 0 after one step, and the
  same number DOS keeps in `$5200`. What the function reads is not settled.
  Settling it: read `0x33312` in `/program` (the function that computes it).
* **`$49FC` and `$49FF`'s sources** `g3d3e`, `g63d0`, `g63d1`. Named as
  globals, not as meanings. `docs/141` records the two ports disagreeing on
  these words; this is why -- they are engine bytes mirrored into the array.
* **Silver Blades' mode 0** in the shipped save, above.
* **Whether the game accepts a save it did not write.** The loader trusts the
  count word and the block sizes with no checksum, so nothing in the format
  stops it; unproven in the running game.

## What this does not need

A second Curse save one step apart was the experiment this issue carried for
weeks, and the WinUAE route to it is open (`docs/143-winuae-debugger.md`,
`#108 (Amiga Curse asks its code wheel, so the title cannot be driven
unattended)` closed). It would now confirm a map already read out of the
writer, and Pool of Radiance's step diff (`docs/124` §1.9b) already shows the
same engine moving y, facing, the wall byte and the square property on one
step. It is worth running only when the square property's meaning is chased.

## Method, so it can be repeated

The `savgam` string is referenced three times in each executable (load,
picker, save); `tools/amiga68k.py refs` finds the referencing instructions and
`disasm` reads the routine. Curse and Silver Blades are SAS/Lattice small-data
programs: `a4` = data hunk + `0x7FFE`, and `jsr d16(a4)` goes through a table
of `jmp abs.l` entries at the start of the data hunk, which the tool resolves.
Pool of Radiance is 41 hunks with absolute references, resolved through the
`RELOC32` tables. The write wrappers are `0x40e44` (Curse), `0x459c6` (Silver
Blades) and `0x2b520` (Pool of Radiance, `fwrite`-style).
