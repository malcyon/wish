# The Amiga Pool of Radiance combat figure, from the routines that build it

A player who opens an Amiga Pool of Radiance save in the Character Editor sees
an empty combat-figure box, and a player who converts the same party to DOS or
the C64 probably sees some of its figures change. Both come down to one fact
measured here: **Amiga Pool of Radiance does not draw DOS's figures under DOS's
numbers.** Its `icon_head` and `icon_body` index its own art, `/chead.dax` and
`/cbody.dax` on disk 2 (`POOLDATA`); 61 of its 156 blocks are a DOS block pixel
for pixel, only 14 of those under the same id, and the rest are the Amiga
artist's own drawings, many a pixel or two away from a DOS one.

Every address below is a file offset into `/program` on disk 1 (SHA-256
`b1cbbecc…`, the one build on the player's three disk sets), read with
`tools/amiga/amiga68k.py`. `tools/icons/amigaporicons.py` re-takes every
measurement, `goldbox/amiga_por_icons.py` is the decoder, and
`tests/amiga/test_amigaporicons.py` pins both. The later two Amiga titles are
a different case: [`199-amiga-combat-icons.md`](199-amiga-combat-icons.md).

## The block format -- CONFIRMED

Both files are Amiga `.dax` containers (`goldbox/amiga_dax.py`), identical on
all three registered disk 2 images (`chead.dax` SHA-256 `e619f95a…`,
`cbody.dax` `9492b0da…`). Each unpacked block is one image:

| bytes | what | in the files |
|---|---|---|
| 0-1 | rows, big-endian | 10 (small head), 8 (large head), 24 (body) |
| 2-3 | width in eights | 3 in every block |
| 4-7 | unused | 0 in every block |
| 8-9 | not read by anything this page decodes | 1 in all 156 blocks |
| 10-11 | the length of one bitplane in bytes | rows x 4 |
| 12- | four bitplanes, one whole plane after another | |

A row is 4 bytes, so 32 pixels are stored and the first 24 drawn. Plane `p`
holds bit `p` of the pixel value and a byte's top bit is the leftmost pixel.
There is no mask plane; value 0 is the empty one. The remapper at `0x048774`
is the evidence for the plane order: it rotates the top bit of planes 3, 2, 1
and 0 into `d1` in that order, so plane 0 lands in bit 0. The art is the
second, independent proof: 61 blocks reproduce a DOS block exactly through one
value table, which a swapped plane or bit order would not allow.
`tests/amiga/test_amigaporicons.py` checks the decoder on a generated block
that a swapped plane order or a mirrored byte would decode differently.

The ids: `chead.dax` holds 28 blocks, 0-13 and 64-77; `cbody.dax` holds 128,
0-31, 64-95, 128-159 and 192-223.

## Which blocks a figure is made of -- CONFIRMED

The preparer at `0x0262A0` reads the record through the pointer at
`h32+0xAEA`: `+0xBF` `icon_head`, `+0xC0` `icon_body`, `+0xC1` the figure
slot (`combat_figure`), `+0xC2` `size`, `+0xC3`-`+0xC8` the six colour bytes.
Those are DOS's `0x0BD`-`0x0C6` through `goldbox.amiga_por`'s shift of 2, so
the preparer independently confirms that part of the shift map.

It builds `CHEAD` and `CBODY` plus the size letter from the table at
`0x02C713` (`\0`, `S`, `T` for `size` 0, 1, 2), and calls the loader at
`0x036192` for the head into slot 11 and for the body into the figure's slot.
The loader:

* adds `0x40` to the id when the letter, upper-cased, is `T` (`0x036202`-`0x036218`);
* loads that block as the ready pose (`0x036264`);
* for `CBODY`, loads `id + 0x80` as the action pose (`0x03628A`-`0x0362B6`);
* for `CHEAD`, loads the same block again (`0x0362C2`-`0x0362E8`).

So a figure is head `icon_head (+64)` in both poses, body `icon_body (+64)`
ready and `icon_body (+64) + 128` action. This is why the Amiga file has no
head ids above 77: DOS's second-pose heads, 128-141 and 192-205, are
byte-identical to its first-pose heads in all 28 cases, so nothing is lost.
`goldbox.amiga_por_icons.block_ids` is this rule. The ICON menu draws the two
poses from `h32+0xB20 + slot*8 + 0` (ready) and `+4` (action).

## Composition and recolour -- CONFIRMED

The composite at `0x0261E0` ORs every byte of the head's four planes into the
body's at the same byte offset, plus the mask, for the head's plane length.
Both are 4 bytes a row, so the head lands on body rows 0-9 or 0-7. The
preparer composes the head into both body poses (`0x026354`, `0x026378`).

When its flag argument is set, the preparer then builds a sixteen-entry table
(`0x026386`-`0x026402`). It starts as the identity, and for each part `i` from
1 to 6 it reads a source byte `S` from `0x06DD4E + i` and the record's colour
byte `C` from `+0xC2 + i`:

```
table[S & 0xF] = C & 0xF
table[S >> 4]  = C >> 4
```

The six source bytes are `19 2A 3B 76 85 EF`. The remapper at `0x048774` then
replaces every pixel value `v` of both body poses with `table[v]`, across 96
bytes a plane (24 rows of 4). Nothing translates the nibble between the record
and the plane: **a colour nibble is stored as the pixel's new bitplane value**.
Whether the screen the figure is drawn on maps bitplane value `n` to colour
register `n` is PROBABLE and not read here; stage 3 of WISH-378 proves the
palette from captures of the game's own ICON screen.

A record holding the six source bytes draws the art unchanged, and that is
what a fresh Amiga character holds: 6 of the 20 distinct Amiga Pool records on
the player's disks carry exactly `19 2A 3B 76 85 EF`, against DOS's own fresh
`91 A2 B3 C4 E6 F7`.

## The Amiga art against DOS's

Run each DOS Pool `CHEAD.DAX` and `CBODY.DAX` pixel through this table and
compare blocks of the same size:

| DOS value | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Amiga value | 0 | 1 | 2 | 3 | 6 | 9 | 5 | 14 | 4 | 9 | 10 | 11 | 7 | 1 | 8 | 15 |

The table is a measurement, not a reading of code: it is the assignment under
which the 61 blocks below match exactly, and the six pairs it gives the
recoloured parts are exactly the preparer's source pairs. It is not one-to-one -- DOS's plume, 5
and 13, is stored as the body pair 9 and 1, so a body colour choice probably
recolours an Amiga plume where DOS keeps it magenta (SPECULATIVE until stage
3's capture of a plumed head).

| | blocks | a DOS block pixel for pixel | at the same id | no exact DOS block |
|---|---|---|---|---|
| `chead.dax` | 28 | 11 | 4 | 17, every small head among them |
| `cbody.dax` | 128 | 50 | 10 | 78 |

CONFIRMED, 61 matches on one copy of the art, identical on all three. The 95
without an exact match are mostly near ones: 52 of the 78 bodies differ from
the nearest DOS body by 1 or 2 pixels (46 by one), most often a single pixel
of value 12 where DOS has none. The heads are further apart: 2 of the 17 are
within one pixel and the rest 5 to 30. Value 12 is the Amiga art's own: no DOS value maps to it, no colour
choice replaces it, and it appears 103 times in 60 body blocks. What colour it
draws is stage 3's question.

### By menu option

A conversion moves a menu option, not a block, so the comparison that matters
for one is option against option at the same size, with both poses matching.
`tools/icons/amigaporicons.py --table` prints the full table with the nearest
DOS option and pixel count for every option that has no exact equivalent, and
the C64 option each DOS number converts to:

| | options with a DOS option drawing both poses | of which the DOS number differs |
|---|---|---|
| small heads | 0 of 14 | 0 |
| large heads | 11 of 14: 0→0, 1→1, 2→3, 4→7, 5→9, 6→11, 8→4, 10→8, 11→10, 12→12, 13→13 | 7 |
| small bodies | 5 of 32: 0→0, 9→5, 10→6, 21→16, 28→21 | 4 |
| large bodies | 10 of 32: 0→0, 1→1, 2→2, 10→6, 11→7, 20→16, 23→17, 26→20, 27→21, 28→22 | 7 |

The small bodies are DOS's in another order with Amiga-only drawings put in.
Amiga 0 is DOS 0 exactly; nearest by pixel count, Amiga 1-3 are DOS 1-3, 4-7
are DOS 27-30, 8-10 and 12 are DOS 4-7, 11 is
DOS 31, 14-21 are DOS 9-16 and 24-31 are DOS 17-24, each within 7 pixels of
its DOS option over both poses, while Amiga 13, 22 and 23 are 40 to 145 pixels
from anything DOS draws.

## What this means for a conversion -- PROBABLE

`goldbox.iconparts.amiga_combat_icon` and `goldbox.amiga_por.to_dos_record`
copy `icon_head`, `icon_body` and the colour bytes unchanged into a DOS record,
and the C64 composition starts from the same DOS numbers. That rests on the
premise this page measures false: GARWAN, `size` 2 head 10, wears Amiga block
74, which is DOS head 8's drawing, so a converted GARWAN arrives with DOS head
10 instead. The colour bytes do not mean the same thing either. In DOS terms
the Amiga's body, arm, leg and weapon pairs hold the main colour in the high
nibble and the highlight in the low one, the reverse of DOS, while hair and
shield keep DOS's order; and the nibbles are Amiga bitplane values, not EGA
colours. WISH-382 owns the conversion. Grade PROBABLE because nobody has yet
watched a converted figure in the destination game.

**The game's own Pool-to-Curse import probably changes the figure too.** Amiga
Curse's importer at `/Curse` `0x25776` copies a Pool record's `icon_head`,
`icon_body`, `size` and colour bytes unchanged
([`199-amiga-combat-icons.md`](199-amiga-combat-icons.md)), and Amiga Curse's
art is DOS's art under DOS's numbers. SPECULATIVE as to what a player sees.
The experiment: import GARWAN into Amiga Curse and photograph his figure on
Curse's ICON screen beside Pool's; DOS head 10's drawing confirms, DOS head 8's
refutes.

## What is not settled here

* **The colours.** Which RGB each bitplane value draws on the ICON screen and
  in combat, and the background behind the figure. Stage 3 of WISH-378 reads
  them from captures of the game's ICON screen and finds the palette in
  `/program`.
* **Header bytes 8-9.** 1 in all 156 blocks, and nothing on this page reads
  them.
* **The loader's file read** (`0x03A36A`). The ids above are what it is asked
  for; that it opens `chead.dax` and `cbody.dax` on disk 2 rests on those being
  the only files of those names on the player's disks (PROBABLE).
