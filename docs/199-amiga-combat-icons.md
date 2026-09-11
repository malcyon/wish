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
`tools/amiga68k.py`. `tools/amigaicons.py` re-takes all three measurements --
`--tables`, `--art`, `--census` -- and `tests/test_amigaicons.py` pins them.
Every site named below was found with `tools/amigarecordrefs.py`, which is
what asks "who reads this record byte" on a port where a field is `d16(An)`
off a pointer rather than a global `tools/amigaglobal.py` could find.

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

**It reads exactly the offsets `goldbox/amiga_codec.py`'s shift map predicts**, in
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
`tests/test_amigaicons.py`'s body test red, and both were watched failing.

**Silver Blades redrew the same four blocks on the Amiga as on DOS** -- head
10 at the large size and body 11 at the small, blocks 74, 202, 11 and 139, and
nothing else. So `tools/iconproposal.yaml`'s Silver Blades override is right
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

CONFIRMED as bytes, on both copies of each disk set on this machine. **What a
player sees is UNKNOWN**: entry 0 is the Amiga screen's background colour
unless the combat screen's palette says otherwise, and DOS draws the same
pixels magenta. The experiment: boot Amiga Curse, give a character head 6, and
photograph his figure on the combat floor beside the DOS one. Nothing a
conversion writes changes it either way, because a conversion writes indices
and never pixels.

## What this means for a conversion

**An Amiga Curse or Silver Blades figure converts to the DOS one by copying
ten bytes** -- `icon_head`, `icon_body`, `size`, `icon_dimension` and the six
colour bytes. The engines say so themselves: the Amiga's own importer at
Curse `0x25776` copies a Pool of Radiance record's `icon_head`, `icon_body`
and `size` into Curse's, then `movmem`s the six colour bytes, skipping only
`combat_figure`, which the loader reallocates; Silver Blades' at `0x26FBA`
does the same with a Curse record, byte by byte. A port that had renumbered
its art could not do that -- the same argument
[`168-dos-dax-and-combat-icons.md`](168-dos-dax-and-combat-icons.md) makes for
the three DOS titles.

**And to the C64 through the machinery that already exists.**
`goldbox.iconparts.IconParts.dos_icon(head, body, size, colours)` composes a
C64 figure from exactly these four values and is what `goldbox.dos_codec._icon_for`
already calls; the Amiga's numbers are its arguments unchanged.

So the four names on `goldbox.amiga_codec.LATER_DROPPED` are three transformations
and one silent constant, mirroring what `goldbox/dos_codec.py` already does with the
same fields:

| field | what it should do | where DOS's own reader puts it |
|---|---|---|
| `icon_head` | converted -- the same number | `TRANSFORMED` |
| `icon_body` | converted -- the same number | `TRANSFORMED` |
| `icon_colours` | converted -- the same six pairs | `TRANSFORMED` |
| `icon_dimension` | 1 for every player character, and the C64 has one size byte where DOS has two | `DROPPED`, with **no player text** -- Donald, 2026-09-06: *"All PCs are the same size, so it doesn't matter. Just leave that line out during conversions."* |

`editor/convert.py`'s `amiga_combat_icon` is the shape of the first three, and
was written for Amiga Pool of Radiance on exactly this reasoning
(`#354 (Convert an Amiga Pool of Radiance save to DOS, so a party standing in
the Slums on the Amiga arrives there under DOSBox)`); this page is what says
the later two titles are the same case.

## The specimens

All 21 Amiga Curse and Silver Blades records, read with
`tools/amigaicons.py --census`: `icon_head` 0-9, `icon_body` 0-31,
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
