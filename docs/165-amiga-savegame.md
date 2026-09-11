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
`goldbox.amiga_codec.party_in_savegame` found it on every specimen.

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
| `0x3206` | the wall type in the facing direction | 0 | `g3f63`, rewritten at `0xdb96` on every step -- the field DOS keeps at 12804. See "The two map bytes" below |
| `0x3207` | the square's attribute byte | 0 | `g3f64`, rewritten at `0xdb7e` on the same step |
| `0x3208` | pad | 0 | `g3f65` is referenced nowhere in the code |
| `0x3209` | **game mode before the current one** | 4 | `g5889`: `prev = mode; mode = n` at every mode change, restored after |
| `0x320a` | **game mode** | 2 | `g3d56`, see the enumeration below |
| `0x320b` | wallset entry 1, (WALLDEF block, slot) `u16be` pair | (1, 1) | `g5eaa`; the loader hands each non-zero pair to the `WALLDEF%s` loader, block into 780-byte slot 1-3 |
| `0x320f` | wallset entry 2 | (2, 2) | |
| `0x3213` | wallset entry 3 | (3, 3) | |
| `0x3217` | party count, `u16be` | 4 | the writer walks the list; the loader loops on it |

### Silver Blades, 22 bytes at `0x1401`

Single-byte x, y and facing (`g57a0`-`g57a2`; new game writes 7, 13, 0; facing
written as 0/2/4/6), then the two map bytes from the same step routine
(`g57a3`, `g57a4`), a pad nobody references (`g57a5`), the
mode before (`g74a3`), the mode (`g525c`), the wallset table (`g7be8` + 4) and
the `u16be` count. The shipped save reads `07 0d 00 00 00 00 | 04 00 |
00 00 00 01 ff ff ff ff ff ff ff ff | 00 06`: entry 1 = (block 0, slot 1) and
entries 2-3 empty, **which is exactly what both titles' new-game
initialisation writes** (`0x1d6e8` on Curse, `0x1d8c4` on Silver Blades).

**Which byte is x is CONFIRMED twice over**, and it used not to be, because the
only in-world specimen stood at `3,3`. The step routine at `0x118cc` reads the
facing and jumps through a table at `0x11924`: north decrements `g57a1`, east
increments `g57a0`, south increments `g57a1`, west decrements `g57a0`, each
wrapping at 15. So `g57a0` is x, `g57a1` is y, and both wrap on a 16 x 16
grid -- which the bounds test at `0x3b612` states directly. And a saved game
edited to `x = 5, y = 9, facing = 6`, three bytes and nothing else, drew
**`5,9 W 00:00`** on the status line (`work/28ssb/shots/06-world.png`; the
specimen is `~/wish-specimens/ssb-amiga/WISH-SPEC-ssb-amiga-moved/`).

**`docs/124-amiga-port.md` §1.14a has the same run's other half**: the engine
resaved that party at that square and changed 23 bytes of 7233, of which 20 are
heap.

### Pool of Radiance, 13 bytes at 12800

The save writes **ten** bytes from `h32+0x176f` and the struct there is
**seven**: x, y, facing (doubled), the wall type in the facing direction
(computed at `0x2ec1c`), the square's attribute byte (computed at `0x2ec54`),
and two bytes nothing references. The wallset table sits at `h32+0x1776`, so the write's last three
bytes are the first three of table entry 0, which is never written. Then
`h32+0xc1`, the **view type** (saved and restored as a (previous, current)
pair the way Curse saves its mode), `h32+0xba`, the game mode, and the count
byte.

**The view type reads 1 indoors and 3 on the travel grid**, measured on
2026-09-07 on the first two Amiga saved games ever made outdoors
(`#321 (An Amiga Pool of Radiance conversion refuses a party standing on the
travel grid, because no outdoor Amiga saved game has ever been read)`). This
page said "1 = 3D, 2 = overland" from the code beside the write until then,
and **2 is not what the engine stores**: no Amiga saved game on this machine
holds it. 3 is what DOS holds at its own 12806 in 10 of 10 outdoor specimens,
so the two ports agree and the enumeration read off the code names a mode
nothing here has reached. The five zeros at 12805-12809 are therefore not
fields, and nothing reads them from the file for any purpose.

**The thirteen bytes are re-derived from the files, on 19 saved games** --
every distinct `savgam*.dat` in the specimen tree, twelve of them the Amiga
engine's own, standing in three different areas and in both view modes. Each
boundary was located by a property of the bytes rather than by this map, so
the agreement is not by construction:

| boundary | found by | result |
|---|---|---|
| the name table's first byte | searching for `CHRDAT` | **12813 in 19 of 19** |
| the script buffer's first byte | matching 5120 onwards against every unpacked `ecl.dax` block from its byte 2 | **19 of 19** |
| the variable array's base | reading `$4FE1`, `$506D` and `$50F6` at `2 * (addr - $4900)` | **(255, 16, 1) in 19 of 19** |
| the count byte | `$503E` against byte 12812 | **equal in 19 of 19** |
| the five pad bytes | 12805-12809 | **zero in 19 of 19** |

A name table at 12813 makes the tail thirteen bytes where DOS's is eight, and
the Amiga writes no container byte at the front: 5 − 1 = 4, which is the whole
of the difference between DOS's 13,137 and the Amiga's 13,141
([`196-the-amiga-saved-game-built.md`](196-the-amiga-saved-game-built.md) §1).
CONFIRMED, `#316 (Write the Amiga Pool of Radiance saved game from the source
save, so a converted party arrives where it was standing)`.

The Pool of Radiance wallset table is copied into the VM array before the
write, entry *i* to `$4AF9+i` and `$4AFC+i` for *i* = 1..3 -- which is
[`141-dos-savegame.md`](141-dos-savegame.md)'s wallset triple and its (1, 2, 3)
index map. Curse and Silver Blades write the table as its own twelve bytes
instead.

### The two map bytes, and what they read

**CONFIRMED, three titles from the code and two squares against the map on the
disk.** Both bytes come out of the loaded 1024-byte `GEO` block, which holds a
**16 x 16 map**:

| offset in the block | one byte a square | what |
|---|---|---|
| `0x000`-`0x0FF` | high nibble | **north** wall |
| | low nibble | **east** wall |
| `0x100`-`0x1FF` | high nibble | **south** wall |
| | low nibble | **west** wall |
| `0x200`-`0x2FF` | the whole byte | the square's attribute |
| `0x300`-`0x3FF` | | **UNKNOWN**; neither routine touches it |

The attribute routine is the same on all three -- Silver Blades `0x3b8a6`,
Curse `0x37b3c`, Pool of Radiance `0x3e176`: bounds-check x and y against 0-15,
then return `map[0x200 + 16*y + x]`. Its sibling (Silver Blades `0x3b78c`)
switches on the doubled facing through a jump table at `0x3b880` and returns
the matching nibble, which is why the field's old name here -- "the wall in
front of the party" -- was wrong and has been corrected: it is a wall **type**,
0 to 15, and it reads 0 at both `3,3 S` and `5,9 W` where the view draws a wall.

**Outdoors it is 14 and stops tracking the square**, in both engine-written
outdoor Amiga saved games -- unmoved across a step that changed the travel
square and the facing, where indoors the same byte is recomputed on every
step. It is the same 14 DOS holds at `goldbox.dos_savegame.SCRATCH_BYTE` in
its own engine-written outdoor saves, and the value
`goldbox.amiga_codec.POR_WALL_OUTDOORS` now writes (`#321 (An Amiga Pool of
Radiance conversion refuses a party standing on the travel grid, because no
outdoor Amiga saved game has ever been read)`).

**The map on the disk agrees with the saved games.** `/DISK2/GEO.GLB` on Silver
Blades disk B is a `GLIB` of 18 blocks: block 0 is a 70-byte index holding a
`u16be` count of 17 and then 17 `(id, block)` pairs, the first of which is
`(16, 1)`. The two saved games both carry `$49C5` = 16:

| square | the save's attribute byte | `GEO.GLB` block 1 at `0x200 + 16y + x` |
|---|---|---|
| 3,3 | 135 | **135** |
| 5,9 | 128 | **128** |

Block 1 is the only one of the seventeen matching both. And the engine
**recomputed** the byte when it resaved a party we had moved -- handed 135 at
square 5,9, it wrote 128 -- so a converted save need not get either byte right.

#### DOS's third name for the attribute byte is not the Amiga's

[`141-dos-savegame.md`](141-dos-savegame.md) grades `$5082` **CONFIRMED as a
copy**: it equals `$5200`, and both equal the attribute byte in the tail, in
21 of 21 engine-written DOS specimens, including a pair that moved together
across the boat. **That is a fact about the DOS engine's code path and does
not hold here.** Over the twelve engine-written Amiga Pool of Radiance saved
games on this machine the three agree in five and disagree in seven, and the
only agreement at a non-zero value is the shipped slot A's 25, 25, 25.

| what the engine wrote | byte 12804 | `$5082` | `$5200` | files |
|---|---|---|---|---|
| the shipped slot A | 25 | 25 | 25 | 1 |
| indoors, New Phlan at 9,13 | 150 | 0 | 0 | 5 |
| outdoors, the travel grid | 1 | **0** | **1** | 2 |
| indoors, all three zero | 0 | 0 | 0 | 4 |

**The outdoor pair is what makes this CONFIRMED rather than an artefact of our
own zeroes.** Most of these parties were loaded out of a container this
project built with all three at zero, so the engine had nothing to copy -- but
the outdoor pair's ancestor went in holding three *different* values (`$5082`
25, `$5200` 0, byte 12804 0) and the engine rewrote all three when the party
bought a passage and landed on the travel grid: 25 → 0, 0 → 1, 0 → 1. It
touched them and still left `$5082` unequal to the other two.

Nothing rests on this. `goldbox.amiga_codec.POR_SAVGAM_UNSOURCED` and
`goldbox.dos_codec.SAVGAM_UNSOURCED` both name the two words engine-rebuilt and
write zero, which both WinUAE runs of `#316 (Write the Amiga Pool of Radiance
saved game from the source save, so a converted party arrives where it was
standing)` showed the Amiga engine accepting. The reason to record it is that
deriving either word from the tail byte, on the grounds that DOS does, would
write a value the Amiga engine itself does not.

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
are the view type and the game mode of this same source. **CONFIRMED for the
Amiga as well since 2026-09-07**: its own byte reads 1 indoors in ten saved
games and 3 in the two made outdoors, which is DOS's pair exactly. Whether
`GAME.OVR`'s own routine names the same values is still read off the Amiga
port rather than out of DOS.

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

### What an in-world Silver Blades save holds, against the DOS map

The shipped `savgamA.sav` and the game's own save of the same party a minute
into the world differ by **62 bytes of 7233**, and the array half of that is
fourteen words. Every one lands where
[`141-dos-savegame.md`](141-dos-savegame.md) says, which is the first time a
*later* title's array has been checked from inside the world -- every earlier
specimen was written before the game started.

| address | real VM name | shipped | in the world | what `docs/141` calls it |
|---|---|---|---|---|
| `$49C5` | `$49C5` | 0 | **16** | the resident `GEO` block |
| `$49E7`-`$49E9` | | 0, 0, 0 | **1, 1, 1** | **named on no port** |
| `$49F2` | `$49F2` | 0 | **16** | the area the party is in |
| `$49FD`, `$49FE` | | 0, 0 | **11, 9** | the area's own ECL prologue constants |
| `$4A04` | | 0 | **1** | the per-script scratch `$4A00`-`$4A1F` |
| `$4A36`, `$4A3C` | | 0, 0 | **1, 1** | the quest flags `$4A20`-`$4AF8` |
| `$4AFD` | | 0 | **255** | DOS's wall-index map -- see below |
| `$4FC6` | **`$6DC6`** | 0 | **80** | live and unnamed |
| `$4FE1` | **`$6DE1`** | 0 | **255** | the documented constant 255 |
| `$5079` | **`$6E79`** | 0 | **7** | a script register |

Twenty words in 2560 are non-zero in the in-world save and six in the shipped
one -- and those six (`$49E6`, `$49FC`, `$49FF`, `$4AF4`, `$5012`, `$503E`) are
exactly the six the **DOS** shipped Silver Blades save holds, value for value.
With the square reading `7,13,0`, which is what new-game initialisation writes,
**the shipped Amiga `savgamA.sav` is a party that has never entered the world**.

Two cautions. `$4AFD` = 255 is **not** DOS's wall-index map: `$4AFA`-`$4AFC`
are zero in all three files because Silver Blades writes its wallset table as
its own twelve bytes in the square region instead of copying it into the array,
so there is no triple beside it to index. UNKNOWN. And `$4FD2`/`$4FD3` --
DOS's rest-interruption pair, which `docs/141` says the file holds *because a
save is taken inside ENCAMP* -- are **zero** in a save that was taken inside
ENCAMP. UNKNOWN, one specimen.

**The party region moved nothing but `experience`, on all six characters**:
200,000 to 202,750 on the five single-classed and 100,000 to 101,250 on the
multi-classed one, which carries half. The opening scene awards it; there was
no fight (`work/331run/shots/07-after.png` through `09-adventuring.png` are the
scene) and the clock never left `00:00`. That is an independent corroboration
of the field's offset -- it is the one thing the engine moved, by an amount a
Gold Box award has the shape of. The other 42 bytes are `effect_chain` and
`heap_104` pointers.

## The container number

Byte 0 is `g5858` on Curse: 1 for disk A, 2 for disk B, chosen by the disk
prompt at `0x13e4e`, and it feeds every `GEO%s` and `WALLDEF%s` load through a
`%d` path builder (`0x2c36a`). Silver Blades' `g5191` is set to 5 by the
new-game code and to 1 or 2 elsewhere, so it is an area group rather than a
disk; the shipped save holds 1. Pool of Radiance has no byte and keeps the
number in `$5012` alone.

## What the running game did with one

**CONFIRMED, one WinUAE run each on 2026-09-05**, holder `wish28`, screenshots
in `work/28run/shots/`. Until then every claim on this page was a statement
about what the save routine writes, and no Curse or Silver Blades saved game
this project wrote had ever been loaded by the game.

Five slots were written onto copies of the two game disks with
`tools/amigalaterslot.py`, each one edit of the shipped save, and every one
loaded and drew the party it holds:

| title | slot | the edit | bytes | the party panel |
|---|---|---|---|---|
| Curse | B | character 0's sixteen-byte name field rewritten | 15221 | four rows, **ZEPHYRA** first, AC 1/2/0/1, HP 32/48/38/48 |
| Curse | C | the party one character shorter | **14621** | **three rows**, right AC and HP |
| Curse | D | one character's item chain emptied | **15023** | four rows, and that character's AC drawn **6** where the record still says 0 |
| Silver Blades | B | six characters cut to four, character 0 renamed | **6553** | four rows, **TALWYN** first, AC 6/6/7/7, HP 95/74/91/58 |

Slot C is the structural one: dropping a character moves the party-count word
and every block boundary after it, and a loader reading a block length wrong
comes apart on the character following. Curse's slot D then went adventuring
at `3,14 E 01:15` -- its own file's square, facing and clock -- and drew a
character sheet reproducing `docs/124-amiga-port.md` §1.11 line for line, and
an ITEMS screen listing that character's two item nodes.

### The engine's own resave, which is the strongest of it

Each party was saved back through the game, and the file the engine wrote is
compared with the one we wrote:

| | Curse: our D against the engine's E | Silver Blades: our B against the engine's C |
|---|---|---|
| length | **15023 both** | **6553 both** |
| bytes differing | 70 | 27 |
| of those, outside the party region | **2** | **1** |
| heap pointers, of the rest | 48 | 26 |

The **whole variable array bar one word, the whole 7680-byte staged script,
the square, the facing, the clock, the wallset table and the party count are
byte for byte identical** on Curse; on Silver Blades, which stages no script,
the whole array is identical. The two header bytes that moved are `$5079`
(35 to 11), which `docs/141-dos-savegame.md` already lists among the words the
engine rebuilds, and the mode-before byte.

Both engine-written files parse through this page's map with every claim in
`tools/amigasavegame.py`'s `check` clean, including `rebuild(parse(f)) == f`.

### The derived fields are recomputed from the item chain

The only differences that are not heap belong to the one character whose items
were removed, and every one is a consequence of having none:

| record offset | field | ours | the engine's |
|---|---|---|---|
| `0x19F` | `armour_class` | 60, i.e. AC 0 | **54, i.e. AC 6** |
| `0x18C` | `encumbrance`, `u16be` | 782 | **282** |
| `0x1AA` | `movement_current` | 9 | **12** |
| `0x18A` | `hands_used` | 2 | **0** |
| `0x1A0`, `0x1A5`, `0x1A7` | `roster_tail` | 53, 6, 2 | 48, 2, 1 |

AC 6 was already on the party panel **at load**, before any save, so the
recompute happens on the way in. The three characters whose items were left
alone differ in none of these. **CONFIRMED, one character, differential**:
Amiga Curse derives armour class, encumbrance, current movement and hands used
from the item chain rather than trusting the stored bytes. It does not license
writing them wrong -- the panel draws the recomputed value and a player would
see it -- but a writer that gets them wrong is corrected rather than believed.

The same character's stale `item_chain` slots past the head -- `0x157`,
`0x15B`, `0x15F`, inherited from the save we edited -- were **cleared to zero
by the engine**. Those slots are live heap and the loader does not read them.

### And the load picker enumerates the drawer

`LOAD WHICH GAME:` offers **the letters it found**: `A B C D` on the Curse disk
carrying our three, `A B` on the Silver Blades one carrying our one.
`SAVE WHICH GAME:` offers ten letters regardless. Amiga Pool of Radiance is not
like this -- it asks a path and then a free-text letter, which is
`#109 (A save slot written onto an Amiga disk is not offered by the game's
picker)`. A fourth per-title difference.

## Still open

* **The wall nibbles' values.** 0 to 15 in each of the four directions, and 0
  is what both measured squares hold in the direction the 3D view draws a wall.
  Naming them needs the drawing routine or a party that can walk, which is
  `#361 (An Amiga party cannot be made to walk, because the WinUAE driver sends
  only keystrokes)`.
* **`$49FC` and `$49FF`'s sources** `g3d3e`, `g63d0`, `g63d1`. Named as
  globals, not as meanings. `docs/141` records the two ports disagreeing on
  these words; this is why -- they are engine bytes mirrored into the array.
* **Silver Blades' mode 0** in the shipped save, above. The run adds one fact
  and does not settle it: `SAVE CURRENT GAME` on the party menu writes **0 in
  both mode bytes**, where the shipped save holds 4 and 0. So the shipped file
  was not written from the party menu either, and what leaves a 4 in front of a
  0 is still UNKNOWN.
* **A party on the travel grid, and a party in combat**, on either later title.
  Every specimen here was saved indoors, from camp or from the party menu, and
  reaching either needs `#361 (An Amiga party cannot be made to walk, because
  the WinUAE driver sends only keystrokes)`.
* **What the variable array holds in an area nobody has been to.** Pool of
  Radiance's saved games here stand in three of the game's 29 areas -- The
  Slums, New Phlan and one wilderness window -- and **108 of the 2560 words
  are non-zero in at least one of the nineteen**. The rest are written zero by
  `goldbox.amiga_codec.new_por_savegame` on the strength of that sweep, and the
  sweep is only as wide as the places the party has stood:

  | `$5012` | files | words non-zero | a corpus of this one alone would have missed |
  |---|---|---|---|
  | 2, The Slums | 6 | 29 | 79 |
  | 3, New Phlan | 9 | 95 | 13 |
  | 7, the wilderness | 4 | 101 | 7 |
  | all three | 19 | **108** | -- |

  The ten saved games of the 2026-09-05 census, all in New Phlan, gave 92.
  Two more areas found sixteen more live words, so **read "zero in every Amiga
  saved game here" as "in three areas of 29"**. One engine-written saved game
  from Valjevo Castle or the Temple of Bane, swept the same way, is what
  narrows it: no new non-zero word makes the argument much stronger, and ten
  new ones are ten words the writer is zeroing for no measured reason.

**Amiga Silver Blades past its party menu is no longer open.**
`tools/amigabladesjournal.py` answers the `BEGIN ADVENTURING` prompt and the
game has accepted it three times out of three, on three different challenges --
`#331 (Amiga Silver Blades asks a journal word before it will adventure, so the
title cannot be driven past its party menu)`. It needs `/usr/bin/python3`
rather than this project's virtual environment, which has no `numpy`.

## What this does not need

**A second later-title save one step apart.** This page kept that experiment on
its list for weeks. Everything it was going to settle is settled by other
means: which
byte is x by the step routine's own jump table, the two map bytes by the
routines that compute them and by the map on the disk, and the engine's
willingness to stand a party where the file says by the moved save above. Pool
of Radiance's step diff (`docs/124` §1.9b) already shows the same engine moving
y, facing and both map bytes on one step.

**And it could not be run anyway.** Nothing this project can do moves an Amiga
Curse or Silver Blades party: twenty virtual keys were pressed at the Silver
Blades adventuring bar on 2026-09-07 and not one changed the square or the
facing, and `tools/winuae.ps1` sends nothing but keystrokes.
`#361 (An Amiga party cannot be made to walk, because the WinUAE driver sends
only keystrokes)` is what has to land first, and what a step would then buy is
the wall nibbles' values and an outdoor save.

## Method, so it can be repeated

The `savgam` string is referenced three times in each executable (load,
picker, save); `tools/amiga68k.py refs` finds the referencing instructions and
`disasm` reads the routine. Curse and Silver Blades are SAS/Lattice small-data
programs: `a4` = data hunk + `0x7FFE`, and `jsr d16(a4)` goes through a table
of `jmp abs.l` entries at the start of the data hunk, which the tool resolves.
Pool of Radiance is 41 hunks with absolute references, resolved through the
`RELOC32` tables. The write wrappers are `0x40e44` (Curse), `0x459c6` (Silver
Blades) and `0x2b520` (Pool of Radiance, `fwrite`-style).
