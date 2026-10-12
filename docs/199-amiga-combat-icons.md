# The Amiga Curse and Silver Blades combat icon, from the routine that draws it

`#396 (Whether an Amiga Curse or Silver Blades record's combat-icon fields
share DOS's own numbering is unmeasured)`. **They do.** An Amiga record's
`icon_head`, `icon_body`, `size`, `icon_dimension` and the six `icon_colours`
bytes are DOS's own fields holding DOS's own numbers, and the art the numbers
name is DOS's own art re-encoded for the Amiga's bitplanes. Nothing has to be
recognised, composed or looked up to convert one: the bytes are already what
the DOS record wants.

Every offset below is a file offset into `/Curse` on Curse of the Azure Bonds
disk 1 or `/Secret` on Secret of the Silver Blades disk 1, read with
`tools/amiga/amiga68k.py`. `tools/icons/amigaicons.py` re-takes all three measurements --
`--tables`, `--art`, `--sweep` -- and `tests/amiga/test_amigaicons.py` pins them.
Every site named below was found with `tools/amiga/amigarecordrefs.py`, which is
what asks "who reads this record byte" on a port where a field is `d16(An)`
off a pointer rather than a global `tools/amiga/amigaglobal.py` could find.

## The routine

| what | Curse (`/Curse`) | Silver Blades (`/Secret`) |
|---|---|---|
| the icon loader and recolour builder | `0x24E42` | `0x266BA` |
| the block loader it calls twice | `0x34E40` | `0x38544` |
| the ICON menu's head wrap | `0x15AE6` | `0xBC46` |
| the ICON menu's body wrap | `0x15A90` | `0xBF44` |
| DOS pixel value -> Amiga palette entry | `g0EE4` | `g2374` |
| the six recoloured parts | `g1BB9` | `g1F76` |
| the size letter | `g1C11` | `g2371` |
| the importer that reads the previous title | `0x25776` (Pool of Radiance) | `0x26FBA` (Curse) |

**The loader is DOS's, translated.** It builds `CBODY%c` and `CHEAD%c` from
the size letter, asks for block `icon_body` into buffer `combat_figure` and
block `icon_head` into buffer `combat_figure + 0x34`, and the block loader adds
`0x40` when the name ends `T` and loads `index + 0x80` as the second pose into
`buffer + 0x1A`. That is the rule
[`168-dos-dax-and-combat-icons.md`](168-dos-dax-and-combat-icons.md) read out
of `GAME.OVR`, instruction for instruction.

**It reads exactly the offsets `goldbox/amiga_later.py`'s shift map predicts**, in
both titles, which is an independent confirmation of five fields of that map:

| field | DOS Curse | Amiga Curse | DOS Silver Blades | Amiga Silver Blades |
|---|---|---|---|---|
| `icon_head` | `0x141` | `0x145` | `0x153` | `0x0EF` |
| `icon_body` | `0x142` | `0x146` | `0x154` | `0x0F0` |
| `combat_figure` | `0x143` | `0x147` | `0x155` | `0x0F1` |
| `size` | `0x144` | `0x148` | `0x156` | `0x0F2` |
| `icon_colours` | `0x145` | `0x149` | `0x157` | `0x0F3` |
| `icon_dimension` | `0x0DE` | `0x0DE` | `0x0E7` | `0x081` |

**The menu offers the same options.** Curse's ICON menu holds
`cmpi.b #$d, $145(a0)` with `clr.b` on the carry and `move.b #$d` on the
wrap-around, and `cmpi.b #$1f` against `$146(a0)`; Silver Blades holds the
same two against `$EF` and `$F0`. **Fourteen heads and thirty-two bodies, 0-13
and 0-31** -- DOS's own counts. CONFIRMED.

**The recolour is DOS's too.** The routine builds a sixteen-entry identity
table, then for each of the six parts writes the low nibble of the record's
colour byte into the entry the part's main colour uses and the high nibble
into the entry its highlight uses, and applies that table to all four loaded
buffers. `g1BB9` and `g1F76` both hold `01 02 03 04 06 07` -- body, arm, leg,
hair, shield, weapon -- which is `goldbox.dos_codec.DOS_PAIR_CLASSES`. The nibbles a
record stores are therefore the same nibbles DOS stores, and are translated to
an Amiga palette entry only at draw time.

**A corroboration this hands to the DOS page.**
[`168-dos-dax-and-combat-icons.md`](168-dos-dax-and-combat-icons.md) grades
DOS's own part table PROBABLE, because the six bytes were found by
neighbourhood rather than at a resolved address. Both Amiga binaries hold
exactly those six at an address this document resolves, and Silver Blades'
copy is followed by `00 1E 00 19 00 14` -- the `1E 19 14` the DOS match sits
in front of. The DOS claim stays PROBABLE, since this is the same source
compiled twice rather than a reading of DOS's own segment, but it is the
second independent thing pointing at it.

## `icon_dimension` is the combat footprint here as well -- CONFIRMED

Curse `0x195A8` and `0x25D9C` write 1 into `0xDE` at creation, Silver Blades
`0xF7DE` writes 1 into `0x81`; Curse `0x7E92` reads it as
`cmpi.b #$80` then `andi.w #$7` then `cmpi.w #$1`, and `0x30D28` and `0x30F66`
test it against 1. That is DOS's `> 0x80 or (& 7) > 1` test for a creature
bigger than one square, at the same field, and it is 1 in all 21 specimens.

## The art -- CONFIRMED, 171,604 pixels of 171,696

The Amiga keeps its combat figures in `CHEAD.TLB` and `CBODY.TLB` on the
second disk (`DISKB` for Curse, `DISK2` for Silver Blades). They are `GLIB`
containers, not `.dax`: magic, a `u32` total size, a `u16` block count, a
`u16`, a four-byte tag `TILE`, then `count + 1` big-endian `u32` offsets.
Block 0 is an index of `(art id, block number)` pairs; the rest are tiles --
a `u16` height, two unused `u16`s, a byte of width in eights and a byte, then
**five bitplanes stored one after another**, plane 0 the transparency mask and
planes 1-4 a four-bit colour.

**The block ids are DOS's block ids**, in both titles, with none added and
none missing: 56 `CHEAD` blocks over ids 0-13, 64-77, 128-141, 192-205, and
128 `CBODY` blocks over 0-31, 64-95, 128-159, 192-223. A head is 24 pixels
wide and 10 rows at `size` 1 or 8 rows at `size` 2; a body is 24 by 24 at both.

**And they are DOS's pixels.** Run every DOS block's four-bit pixel value
through the translation table the executable itself reads, and compare:

| | blocks | pixels | agreeing |
|---|---|---|---|
| Curse `CBODY.TLB` | 128 | 73,728 | **73,728** |
| Curse `CHEAD.TLB` | 56 | 12,096 | 12,054 |
| Silver Blades `CBODY.TLB` | 128 | 73,728 | **73,728** |
| Silver Blades `CHEAD.TLB` | 56 | 12,144 | 12,094 |

A tile's pixel number is `2 * entry + transparent`, so the prediction for a
DOS value *v* is `2 * g0EE4[v]`, and `1` for DOS's transparent zero. The
table, at `g0EE4` and `g2374` alike:

| DOS value | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Amiga palette entry | 0 | 7 | 12 | 13 | 2 | 14 | 11 | 9 | 8 | 6 | 5 | 15 | 3 | 10 | 4 | 1 |

The identity is not fitted to the art: swapping two entries of the table, or
reading the planes interleaved by row instead of one after another, turns
`tests/amiga/test_amigaicons.py`'s body test red, and both were watched failing.

**Silver Blades redrew the same four blocks on the Amiga as on DOS** -- head
10 at the large size and body 11 at the small, blocks 74, 202, 11 and 139, and
nothing else. So `tools/icons/iconproposal.yaml`'s Silver Blades override is right
for an Amiga Silver Blades record as much as a DOS one.

### The one difference: the plume highlight

42 pixels in Curse's `CHEAD.TLB` and 50 in Silver Blades' hold palette entry
**0** where the DOS block holds pixel value 13 and the table asks for palette
entry 10, which is tile number 20. They are the hat-and-plume highlight, in
head option 6 at the small size and options 2, 4 and 6 at the large one, and
entry 10 appears nowhere in either library. Neither entry is one a player's
colour choices reach -- the six parts are 1, 2, 3, 4, 6 and 7 and their
highlights, so 0, 5, 8 and 13 keep the identity on DOS and entries 0, 8, 10
and 14 keep it here.

CONFIRMED as bytes, on both copies of each disk set on this machine. **They
are drawn, not see-through**: their mask bit is clear, and the blitter draws
every pixel whose mask bit is clear (next section), so the ICON screen shows
them in palette entry 0 -- dark grey in Curse, whose ICON palette exchanges
entries 0 and 8, and black in Silver Blades. That is a code reading, PROBABLE
until a capture of a head 2, 4 or 6 figure shows it; the earlier "UNKNOWN"
here assumed entry 0 might be the background, which the mask rules out. DOS
draws the same pixels magenta. On the combat arena the colour depends on that
screen's palette, which has not been read. Nothing a conversion writes changes
it either way, because a conversion writes indices and never pixels.

## The ICON screen

What a player sees after Camp, Alter, Icon, read from the code and drawn by
`goldbox/amiga_later_icons.py` off the player's own disks
(`tools/icons/amigalatericons.py --palette`, `--compose`, `--capture`;
`tests/amiga/test_amigalatericons.py`). Addresses are file offsets into
`/Curse` and `/Secret`.

| rule | grade | evidence |
|---|---|---|
| A tile's mask plane is set where it is see-through on the disk; the loader inverts it and the blitter draws through it, so an opaque pixel replaces what is under it | CONFIRMED by code | inverter `0x3B6F8` / `0x3F8F8`, hooked for every `TILE` library at `0x3B5BC` / `0x3F7BC`; masked blit `0x3B79A` with minterm `$0FCA` at `0x3F9D8` / `0x4440C`, mask plane on channel A |
| The recolour table is DOS's, translated into palette entries: `t[e[p]] = e[low nibble]`, `t[e[p + 8]] = e[high nibble]` for each part `p`, `e` the DOS-value table | CONFIRMED by code | builder `0x24EDC`-`0x24F82` / `0x26754`-`0x267FA`; applied to all four loaded buffers by `0x3C126`, which skips the mask plane |
| The head **covers** the body: the draw helper blits the body, then the head at the same place | CONFIRMED by code | `0x34F44` / `0x3868A`, both slots through `0x3BD20`; every tile's two offsets are 0 |
| Overwriting differs from DOS's OR in 34 Curse and 30 Silver Blades `(head, body, size, pose)` figures, 40 and 36 pixels, all at size 1 | CONFIRMED, measured | `test_some_small_figures_have_head_pixels_over_body_pixels`; no specimen uses one |
| Every one of the 21 specimens composes to the DOS figure through the entry table, but for the plume highlight (ARIEL 10 pixels, STORMBRINGER 16) | CONFIRMED, measured | `test_every_specimen_is_the_dos_figure_through_the_entry_table` |
| The box behind the ready pose is `COMSPR.TLB` art 25 and behind the action pose art 153, in both titles (DOS Silver Blades uses 25 for both) | CONFIRMED by code | loaded into slot 25 at `0x1D86C`; ICON row drawn by `0x157AA` / `0xB832`; both boxes are opaque |
| Curse's ICON screen shows `ALWAYS.TLB` block 87: block 0's colours with entries 0 and 8 exchanged (and entry 11 changed), so the outline is black and entry 0 dark grey, as on DOS | CONFIRMED by code and by capture: GALAIN, HOLLAND, IILANDA and SUNDRA are pixel-equal in both rows | ICON routine `0x15F04` calls `0x3549E`, which installs block `0x57`; the Alter menu reinstalls block 0 on return (`0x13F8`) |
| Silver Blades loads every figure tile through a table that turns entry 8, the outline, into 0, so the outline is black, as on DOS Silver Blades. The box (`COMSPR` 25) is not translated and keeps entry 8 dark grey. This replaces an earlier reading here that the outline is dark grey: that reading missed the load step | CONFIRMED by code and by capture | block loader `0x38642` passes both loaded slots through `g2FF8` with the recolour routine `0x1CB28`; in all four captures every figure outline pixel is black and every box entry-8 pixel dark grey |
| Silver Blades' ICON screen installs no palette of its own, so it shows `ALWAYS.TLB` block 0 with the camp picture's colours in entries 3, 10, 11, 12 and 14. Camp draws `PIC.TLB` picture 59, and a picture installs exactly those five entries from its own palette block over the screen's. The ICON screen is reached only through camp, so it always shows picture 59's five. The editor reads them from `PIC.TLB` on disk 2. This replaces an earlier row here that left entries 3 and 12 UNKNOWN | CONFIRMED by code, by a memory read and by capture | camp entry `0x1B21E` draws picture `0x3B` at `0x1B26C`; picture install `0x1C9D4`-`0x1CA2C` copies entries 3, 10-12 and 14. Live table `g352E`, read over WinUAE's pipe: block 0 at the title, menu and load; picture colours during the opening scene; block 0 again in the world; block 0 with picture 59's five on entering camp; unchanged at ICON. All eight crops are pixel-equal |
| Silver Blades' `ALWAYS.TLB` is packed (header byte 10 = 5): an LZ77 variant decoded at `0x45524`, which unpacks the file to exactly its header's size | CONFIRMED | `goldbox.amiga_later_icons.unpack_method_5`; `test_silver_blades_packed_library_holds_one_palette_block_0` |
| Poses sit at (32, 56) ready and (104, 56) action on the 320x200 screen; Curse repeats the figure at (32, 104) and (104, 104) as the trial row, Silver Blades draws one row | spacing CONFIRMED by capture (72 pixels across, 48 down); the screen origin PROBABLE | place is `2 * (word - 0x1F40)` (`0x3E548`), word `0x1F44 + 12 * cell` (`0x34F44`), cells from `0x15F3A` / `0xC68E`; labels "ready    action" drawn under each row |

A palette byte becomes the nibble `(byte + 8) // 17` (`0x3F2FE`) and the
screen shows nibble `n` as `17 * n`. The ICON screen's keys: `E` is Exit in
both titles (gadget key `$45`), and Alter is left with its own Exit.

The captures put the poses at Amiga pixel (61, 72) and (133, 72) of the
canonical crop, with Curse's trial row at y 120: the screen's (32, 56)
places, 29 and 16 pixels into the crop. Still open: a plume-highlight figure
(no captured party member has head 2, 4 or 6 at size 2, or 6 at size 1).

Silver Blades' packed libraries inside `PIC.TLB` are stored at even lengths,
so a pad byte follows the last chunk; the unpacker stops at the header's
size rather than at the end of the block.

## Pools of Darkness

What a player sees after camp, Alt, Icon in Amiga Pools of Darkness, read
from the code and drawn by `goldbox/amiga_pod_icons.py` off the player's own
disks (`tools/icons/amigapodicons.py --palette`, `--dos`, `--sweep`,
`--compose`, `--capture`; `tests/icons/test_amigapodicons.py`). The art is
the tile system Curse and Silver Blades use, on a 32-colour screen, so the
shared rules stay in `goldbox/amiga_later_icons.py`; the screen is the
title's own. Addresses are file offsets into the English
`/Pools of Darkness` on disk 1, a small-data executable like `/Curse`
(`a4` = data hunk + `0x7FFE`). Every registered image holds the same five
figure files byte for byte.

| finding | grade | evidence |
|---|---|---|
| The files: `DISK1/COMSPR.TLB` and `DISK1/ALWAYS.TLB` beside `/Pools of Darkness` on disk 1, `Disk3/CHEAD.TLB` (28 tiles) and `Disk3/CBODY.TLB` (128) on disk 3. All four are `GLIB` tile libraries packed with method 5; the three figure ones are indexed by art id | CONFIRMED, measured | `amiga_later_icons.library` reads all four; the loader builds `CHEAD%c` and `CBODY%c` at `0x25620` and `0x25662` |
| A tile whose type byte is `E1` is a mask plane then **five** colour planes; `E0` is five planes and no mask. The mask is inverted on load, as in Curse | CONFIRMED by code, and by length for all 200 tiles of the three figure libraries | the draw routine `0x40276` takes 5 planes for a high nibble of `E` and 4 for 0 (`0x402C0`-`0x402EA`); the colour translator `0x40A58` takes its five-plane path (`0x4574A`, plane 0 = bit 0) when the screen is five deep and the type's high nibble is `E` (`0x40AE6`-`0x40AF4`); start-up sets the five-plane flag unconditionally (`0x17414` calls `0x42D5C` with 1); the `TILE` hook `0x3FEC6` inverts the first plane of a type-1 tile (`0x3FED8`) |
| Block ids: an option, plus 64 for size 2 (the library name ending `T`); a body's action pose is `+ 128`; the **same head tile** goes into both poses | CONFIRMED by code | block loader `0x36D12`: `addi.b #$40` on `T` at `0x36D7A`; `CHEAD` loads id into slot and slot + 37 (`0x36EAA`-`0x36ED8`), anything else id + 128 into slot + 37 (`0x36EE2`-`0x36F02`). `CHEAD.TLB` holds ids 0-13 and 64-77 only. A size other than 2 (including 0, which two NPC records hold) draws small |
| The recolour is the Curse rule over 32 entries: identity over 0-31, then `t[e[p]] = e[low]`, `t[e[p + 8]] = e[high]` for the six parts `01 02 03 04 06 07` (`g1EA6`), `e` the sixteen-entry table `g234E`. It is applied to all four loaded tiles, mask plane skipped. No load table | CONFIRMED by code | builder `0x2567E`-`0x25724`, applied by `0x1C80C` to slots `+0`, `+0x25`, `+0x4A`, `+0x6F` (`0x25728`-`0x25790`); `0x36D12` calls no table. `e` holds entries up to 31: `00 11 05 1F 19 0D 13 06 04 12 0B 0A 1C 1B 09 0F` in every registered executable, the German one (crunched, unpacked by `goldbox/stonecracker.py`) included, whose builder reads its counter off the stack |
| The head covers the body: the slot draw blits the body, then the head at the same place | CONFIRMED by code that the head is drawn second at the same place; PROBABLE that the blit goes through the mask, as Curse's does | `0x36F5A`: body at `pose * 37 + slot` (`0x3705A`), head at `+ 0x4A` when the slot has one (`0x37090`); the masked blit sets minterm `$CA` (`0x445DE`), and the path from `0x40276` to it was not read. It matters in 37 `(head, body, size, pose)` figures, 64 pixels, at both sizes; none of the six capture members uses one |
| The record fields are `0x0BB` head, `0x0BC` body, `0x0BD` figure slot, `0x0BE` size, `0x0BF`-`0x0C4` colours (`goldbox/amiga_pod.py`) | CONFIRMED by code | loader `0x255EA` reads exactly these |
| The ICON screen draws slot 15, with the record's slot byte set to 15 while it is open | CONFIRMED by code | ICON entry `0x0D9CC` saves `0x0BD`, stores 15 (`0x0D9EA`) and reloads the figure through `0x0CF20`; the exit puts the byte back (`0x0DA88`) |
| Boxes: `COMSPR.TLB` art 15 behind the ready pose and art 16 behind the action pose, both 24x24 and opaque. DOS Pools of Darkness uses its block 15 for both | CONFIRMED by code that start-up loads them and the ICON screen draws them; PROBABLE that nothing reloads slots 30 and 31 before camp | start-up loads art `n - 15` into slot `n` for 15-36 (`0x1DB54`-`0x1DBAA`); the ICON draw `0x0C81C` draws slot 30 and slot 31, pose 0 each, at the two places |
| Places: one row, ready at (32, 56) and action at (104, 56) on the 320x200 screen | CONFIRMED by code; the screen origin in a capture PROBABLE | `0x0C81C` is called with cell (1, 2) and draws the action pose 3 cells right; a cell's word is `0x1F44 + 12 * cell` (`0x36F5A`), a pixel `2 * (word - 0x1F40)` (`0x4A38A`) |
| The palette: `ALWAYS.TLB` block 0, all 32 entries (type byte `E8`, 96 colour bytes). Start-up opens `always` as library 0 and installs its block 0; the ICON screen clears the current picture, and with no picture the flush installs library 0's block 0 whole. A channel byte becomes the nibble `(byte + 8) // 17` | CONFIRMED by code for the camp route, which sets a picture first; PROBABLE until captured | `0x1D8F2`-`0x1D904`; `0x0D27E` calls `0x1C5A6` with none, which marks the palette changed; flush `0x1C610` reaches `0x408B8(0, 0, ...)` at `0x1C6C4` / `0x1C704`; setter `0x43E50`. With a picture, entries 1-3 and 19-31 come from the picture and 0 and 4-18 from block 0 (`0x1C654`-`0x1C6A2`) |
| The art is DOS's re-encoded, but for three values: 110 of 156 tiles equal DOS Pools of Darkness's block of the same id through `e`; the other 46 differ only where DOS has 4 in a body (149 pixels, the tile holds `e[13]`), 13 in a head (23, `e[4]`) or 15 in a head (8, entry 0) | CONFIRMED, measured | `amigapodicons.py --dos`; `test_the_tiles_are_dos_s_blocks_through_the_entry_table_but_for_three_values` |

Because `e[13]` is never recoloured, a body pixel DOS draws in the hair
colour stays one fixed colour on the Amiga, and the head's 23 pixels that
DOS never recolours follow the hair colour here. The capture of members with
body 65 (jimmi hendrixs, DONALD DUCK) shows which the screen does.

The ICON screen's keys: camp `Alt` is `A` (bar `View Magic Rest Alt Fix Load
Save Exit`), Alter's `Icon` is `I` (`Order Drop Speed Icon Level Exit`), and
the ICON bar is `Body Pick Head Pick Undo Done Exit`. On leaving, the screen
puts back the record it copied on entry when `g6E82` is set
(`0x0DA6A`-`0x0DA80`), and no question was found on that path (PROBABLE;
the key that sets `g6E82`, `0x0CFA6`, was not matched to its gadget).
Still open: a capture of the ICON screen, which settles the palette, the
boxes and the places.

## What this means for a conversion

**An Amiga Curse or Silver Blades figure converts to the DOS one by copying
ten bytes** -- `icon_head`, `icon_body`, `size`, `icon_dimension` and the six
colour bytes. The engines say so themselves: the Amiga's own importer at
Curse `0x25776` copies a Pool of Radiance record's `icon_head`, `icon_body`
and `size` into Curse's, then `movmem`s the six colour bytes, skipping only
`combat_figure`, which the loader reallocates; Silver Blades' at `0x26FBA`
does the same with a Curse record, byte by byte. Between Curse and Silver
Blades that copy is right, because both number their art as DOS does -- the
same argument [`168-dos-dax-and-combat-icons.md`](168-dos-dax-and-combat-icons.md)
makes for the three DOS titles. It does not show that Amiga Pool of Radiance
numbers its art the same way: it does not, and Curse's import of a Pool
record probably changes the figure
([`240-amiga-pool-combat-figure.md`](240-amiga-pool-combat-figure.md)). The
importer is not evidence that no Amiga title renumbered its art: Pool's own
art, measured, is renumbered.

**And to the C64 through the machinery that already exists.**
`goldbox.iconparts.IconParts.dos_icon(head, body, size, colours)` composes a
C64 figure from exactly these four values and is what `goldbox.dos_codec._icon_for`
already calls; the Amiga's numbers are its arguments unchanged.

So the four names on `goldbox.amiga_later.LATER_DROPPED` are three transformations
and one silent constant, mirroring what `goldbox/dos_codec.py` already does with the
same fields:

| field | what it should do | where DOS's own reader puts it |
|---|---|---|
| `icon_head` | converted -- the same number | `TRANSFORMED` |
| `icon_body` | converted -- the same number | `TRANSFORMED` |
| `icon_colours` | converted -- the same six pairs | `TRANSFORMED` |
| `icon_dimension` | 1 for every player character, and the C64 has one size byte where DOS has two | `DROPPED`, with **no player text** -- Donald, 2026-09-06: *"All PCs are the same size, so it doesn't matter. Just leave that line out during conversions."* |

`goldbox/iconparts.py`'s `amiga_combat_icon` is the pattern of the first three
for the later two titles. It was written for Amiga Pool of Radiance first, on
the belief that Pool is the same case, and it is not: Amiga Pool numbers and
draws its figures differently from DOS, so copying its `icon_head`,
`icon_body` and colour bytes changes most figures
([`240-amiga-pool-combat-figure.md`](240-amiga-pool-combat-figure.md)). Pool is a
different case because its own `chead.dax` and `cbody.dax`, measured, are
renumbered.

## The specimens

All 21 Amiga Curse and Silver Blades records, read with
`tools/icons/amigaicons.py --sweep`: `icon_head` 0-9, `icon_body` 0-31,
`icon_dimension` 1 in 21 of 21, `size` 1 or 2, and **every `(head, body,
size)` triple names four blocks the libraries actually hold**. Twelve of the
21 carry `91 A2 B3 C4 E6 F7`, `goldbox.dos_codec`'s own DOS default -- the eleven
`.guy` pregens contribute three of them and Silver Blades' whole party the
other six. (`#396 (Whether an Amiga Curse or Silver Blades record's
combat-icon fields share DOS's own numbering is unmeasured)`'s own body says
eleven of 21; twelve is what a re-count gives, and the difference is a count
rather than a reading.)

## What was looked for and is not there

The default `91 A2 B3 C4 E6 F7` is **not** a literal in either executable's
data hunk, so where the Amiga seeds a fresh character's colours has not been
located. It does not matter to a conversion, which writes the source record's
own six bytes.
