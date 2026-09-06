# The DOS `.DAX` image block, and how a DOS combat figure is drawn

What `#130 (A converted DOS party arrives with six identical combat figures,
not its own)` had to know before anything could be converted: what is inside
`CHEAD.DAX` and `CBODY.DAX`, and how the engine turns a record's four icon
fields into a figure on the combat screen. Read out of `GAME.OVR` (the 1.3
build, byte-identical between `/home/donald/dos_por_play` and the archives'
`POOLRAD`), with `tools/dosdis16.py` and `tools/dosovrmap.py` against the
unpacked `START.EXE`. Grades are `docs/50-experiments.md`'s. The renders are
under `work/issue130/`, and `tools/daxls.py` lists any container.

The container itself -- the index, the run-length coding -- is documented
beside `goldbox.dos_savegame.dax_index`, and this page does not repeat it.

## The image block -- CONFIRMED over all 184 blocks of both files

| bytes | holds |
|---|---|
| 0 | rows: 24 for every `CBODY` block; 10 for `CHEAD` ids 0-31 and 8 for 64-95 |
| 1 | 0 |
| 2 | width in eights: 3, so 24 pixels |
| 3-7 | 0 |
| 8-16 | `01 12 22 22 23 03 33 32 33` in every block of these two files; `ICON.DAX` and `COMSPR.DAX` hold other values. Nothing read here uses them -- UNKNOWN |
| 17.. | `rows x 12` bytes, two 4-bit pixels a byte, high nibble first |

Every block's length is exactly `17 + rows * 12`, which is the test
`tools/daxls.py` uses to call a block an image.

**A pixel's value is a part number, not a colour.** The census of every
nibble in both files, and what the engine does with each:

| value | in | part |
|---|---|---|
| 0 | both | transparent |
| 1 / 9 | `CBODY` | body, main / highlight |
| 2 / 10 | `CBODY` | arm |
| 3 / 11 | `CBODY` | leg |
| 4 / 12 | both | hair; 12 is also the face, so the hair pair colours the skin |
| 5 / 13 | `CHEAD`, 90 pixels in 56 blocks | a hat or plume; never recoloured, so always magenta |
| 6 / 14 | `CBODY` | shield |
| 7 / 15 | `CBODY` | weapon |
| 8 | both | outline |

## The loader -- CONFIRMED from `GAME.OVR:0x1E481`-`0x1E642`

The routine names `CHEAD` (the string is at `0x1E45C`, `CBODY` beside it),
appends the letter `ds:0x8C5[size]` -- `S` for `size` `@0x0C0` = 1, `T` for 2
(`START.img` offset `0xD085` reads `04 53 54`) -- and calls the block loader
at `0x31C34` with `icon_head` `@0x0BD` and buffer 11; then `CBODY`, the
same letter, `icon_body` `@0x0BE` and the party position `@0x0BF` as the
buffer. The block loader (`0x31CAE`) adds `0x40` to the index when the name
ends in `T`, loads that block as the first pose and `index + 0x80` as the
second (`0x31D03`, `0x31D3F`), then `0x1E315` composites the head buffer
over the body from row 0, once per pose.

So a DOS figure is:

    CBODY.DAX block  icon_body + (64 if size == 2 else 0)        pose 1
    CBODY.DAX block  icon_body + (64 if size == 2 else 0) + 128  pose 2
    CHEAD.DAX block  icon_head + ...                              likewise

The editor at `0x1D553`-`0x1D62B` wraps `icon_head` at 13 and `icon_body`
at 31, so 14 heads and 32 bodies are the engine's own counts, and they match
the block ids in the files.

**Colours.** `0x1E55C`-`0x1E5E6` builds a 16-entry lookup that starts as the
identity, then for `k = 1..6` writes the low nibble of record byte
`0xC0 + k` to `lookup[t[k]]` and the high nibble to `lookup[t[k] + 8]`,
with `t` at `ds:0x3CF5` = `0A 01 02 03 04 06 07`. That is the mechanism
behind the running-game measurement on `#57 (Convert the character portrait
across ports)` that `0x0C1` is the body, `0x0C2` the arm, `0x0C3` the leg,
`0x0C4` hair and skin, `0x0C5` the shield and `0x0C6` the weapon.

## `icon_dimension` `@0x06C` -- CONFIRMED

It is the creature's combat footprint, and a player's is always 1:

* creation writes it: `0x19F98 mov byte es:[di+0x6C], 1`;
* combat reads it masked, `and al, 7` at `0xE22A`, `and al, 0x7F` at
  `0x31805` and `0xFE81`, into the per-combatant table at `[0x5F2A + 4n]`;
  `0x13D0B` tests `> 0x80` or `(& 7) > 1` to pick out anything bigger than
  one ordinary square;
* the 172 monster records in `MON1CHA.DAX`-`MON7CHA.DAX` (285 bytes, one a
  block, `goldbox.dos_savegame.dax_blocks`) hold 1 for every man-sized
  creature, 2 for GNOLL, `0x81` BUGBEAR, `0x82` for OGRE, TROLL, HILL GIANT,
  FIRE GIANT, ETTIN, GIANT SKELETON and EFREETI, 3 for BASILISK, WOLF, the
  scorpions and WILD BOAR, `0x83` for GIANT SNAKE, AHNKHEG, CENTAUR, GIANT
  MANTIS and TIGER, and `0x84` for TYRANITHRAXUS.

PROBABLE: 2 is two squares tall, 3 two wide, 4 two by two, and bit 7 the
big-creature flag. The experiment: one DOS fight with a player's `0x06C` set
to `0x82`, photographed. Not needed for a conversion, which writes 1.

The same monster records hold `size` `@0x0C0` = 0 and `icon_head` =
`icon_body` = 0 throughout, so those three fields are player-only.

## What the C64 has instead

Fully measured in `goldbox/icons.py` and `goldbox/iconparts.py`: 18
`CHARPIC00` screen codes as two 3x3 multicolour poses plus 18 colour
nibbles, composed from `SPELLE64`'s option tables -- 28 weapons and 14 heads
small, 35 and 23 large. A multicolour cell is 4 double-wide pixels a row
with one colour of its own (0-7) and three shared ones `COM.PREP` sets: the
ground, light red for face and hands, black for the outline.

| | DOS | C64 |
|---|---|---|
| pixels per pose | 24 x 24, 16 values | 12 x 24 double-wide, 4 per cell |
| colours chosen by the character | 6 parts x 2 nibbles of 16 | 7 parts x 1 of 8 |
| face | the hair pair's highlight | fixed light red |
| hat or plume | fixed magenta | the `CAP` part, any of 8 |

The C64's small weapon list is the large list's first 28 designs redrawn for
the shorter body (18 of 28 share their weapon glyphs exactly; the other ten
differ only in the shield glyph), and the DOS small lists are the same 32
and 14 designs with the head drawn eight rows tall instead of ten. So one
body table and one head table serve both sizes, and a DOS small character
whose body maps to a C64 option at or above 28 is composed as a large weapon
under a small head, which the game accepts -- HOGARTH on the player's disks
is such a mix.

## What is a judgement rather than a measurement

The figure sets are the same vocabulary in a different order: both have a
bow, a crossbow, a flail, a sling, spears, axes, hammers, the shield set and
a robed set. No index corresponds (`tools/iconcorrespond.py` measured that),
and the mapping is a look. `tools/iconproposal.py` holds the proposed tables
-- 32 body rows, 14 head rows, a 16-to-8 colour table -- and draws each DOS
figure beside its proposed C64 one; the decision is Donald's and is tracked
on the issue.

## The same numbering in all three titles -- CONFIRMED

`IconParts.dos_icon` takes no title, and the correspondence table it reads
was built from Pool of Radiance's art, so `#330 (A converted Curse or Silver
Blades figure is composed through Pool of Radiance's icon table, which nobody
has checked transfers)` asked whether a Curse of the Azure Bonds or Secret of
the Silver Blades record numbers its own art the same way. It does.
`tools/dosicontitles.py` is the measurement, run against the archives'
`POOLRAD`, `CURSE` and `SECRET` game directories.

**The art.** Both containers hold the same block ids in all three titles --
128 `CBODY` blocks over 32 options and 56 `CHEAD` blocks over 14, none added
and none missing -- and the blocks themselves are the same bytes:

| | `CHEAD.DAX` | `CBODY.DAX` | file |
|---|---|---|---|
| Curse of the Azure Bonds | 56 of 56 identical | 128 of 128 identical | byte-identical to Pool of Radiance's, both files |
| Secret of the Silver Blades | 54 of 56 | 126 of 128 | 3428 and 23889 bytes against 3442 and 23978 |

**The code.** Each title's ICON menu wraps the head at 13 and the body at 31,
at that title's own record displacement -- Pool of Radiance `0x0BD`/`0x0BE`,
Curse `0x141`/`0x142`, Silver Blades `0x153`/`0x154` -- so all three offer
the same 14 heads and 32 bodies. The loader that appends `S` or `T` to the
file name and asks for the block is the same routine in all three overlays,
differing only in the displacements; its prologue is at Pool of Radiance
`GAME.OVR:0x1E468`, Curse `0x1C1C1` and Silver Blades `0x242B7`, eleven bytes
past each overlay's own `CHEAD`/`CBODY` string pair, and all three read
`55 89 E5 81 EC 2A 02`. So is the recolour builder --
Pool of Radiance `0x1E55C`, Curse `0x1C2B5`, Silver Blades `0x24413` -- which
reads its own record's six colour bytes after `size` and indexes a seven-byte
part table in the resident data segment, at `ds:0x3CF5`, `ds:0x3EC2` and
`ds:0x4CAF`.

**PROBABLE, and it is the one claim here that is not CONFIRMED:** that table
holds `01 02 03 04 06 07` in all three -- body, arm, leg, hair, shield,
weapon, which is `DOS_PAIR_CLASSES`. The six bytes occur exactly once in each
title's `START.EXE` and nowhere else in any `.EXE`, `.OVR` or `.COM` of the
three game directories, in the same run of constant tables each time
(`0A 0F 0A 0A 0B 0C 0B` before, `1E 19 14 0F` after) -- but the `ds` base
has not been resolved. In Pool of Radiance no single base puts both that hit
at `ds:0x3CF5` and the size-letter table `04 53 54` at `ds:0x8C5`, so
`START.EXE`'s data is not one flat run at a fixed offset and the match here
is by neighbourhood rather than by address. The
experiment that settles it: boot Curse under DOSBox, break at
`GAME.OVR:0x1C301`, and read the seven bytes at `ds:0x3EC2`. Anything but
`?? 01 02 03 04 06 07` refutes it.

**And the shipped engines say it themselves.** Curse's own importer reads a
Pool of Radiance record's `icon_head` `0x0BD`, `icon_body` `0x0BE` and `size`
`0x0C0` and writes them into its `0x141`, `0x142` and `0x144`, then block-
copies the six `icon_colours` from `0x0C1` to `0x145` --
`GAME.OVR:0x1D477`-`0x1D4CD`, no table in between. Silver Blades' importer
does the same with a Curse record at `0x2533C`-`0x253A2`. A title that had
renumbered its art could not copy those bytes straight across.

## Silver Blades re-drew two options -- CONFIRMED

Four blocks of the 184 differ, and they are two options in both poses:

| file | option | size | blocks | what changed |
|---|---|---|---|---|
| `CHEAD.DAX` | head 10 | large (`size` 2) | 74, 202 | Pool of Radiance draws hair, outline and face; Silver Blades adds pixel values 5 and 13, which the recolour lookup never touches -- a hat or plume. 32 of 192 pixels, and the block is 9 rows where every other `CHEAD` block is 8 or 10 |
| `CBODY.DAX` | body 11 | small (`size` 1) | 11, 139 | Pool of Radiance draws weapon pixels 7 and 15; Silver Blades draws neither. 27 of 576 pixels in pose 1 and 79 in pose 2 |

Two things say these were re-authored rather than mis-read here. Every other
block in both files of all three titles carries `01 12 22 22 23 03 33 32 33`
at block offset 8; exactly these four carry zeroes there. And the sibling
size of each is untouched -- Silver Blades' *small* head 10 and *large* body
11 are Pool of Radiance's bytes exactly -- so within Silver Blades the two
sizes of those options now draw different things.

**What that costs a converted character.** `tools/iconproposal.yaml` has one
row per DOS option, serving both sizes, and both rows were chosen against
Pool of Radiance's drawing. So a Silver Blades character at `size` 2 with
head 10 loses a hat the C64 head option does not have, and one at `size` 1
with body 11 gains a weapon his DOS figure does not hold. Nothing else in
either table is affected, and no record in the 54 shipped DOS saves across
the four titles holds either combination -- though a player reaches both from
the ICON menu, and those saves have no chain of custody.

## Silver Blades re-drew the C64 art too -- CONFIRMED, and it refutes a PROBABLE

Everything above is about the **DOS** art. The C64 half of every proposal
document was drawn off `POOL3.D64` whatever title the document was for, on a
claim graded PROBABLE: that `SPELLE64`'s four option tables are the identical
bytes in all three titles, so one disk draws the C64 figure for any of them.

**The bytes half of that claim is right and the picture half is wrong.**
`SPELLE64` really is the same 1882 bytes -- md5 `1bcb496323493628e047a4ac46077f33`
on all thirteen sides of the three titles that carry it -- so the *screen
codes* a figure composes to are identical. But a figure is those codes drawn
through `CHARPIC00`, and Silver Blades' `CHARPIC00` is not Pool of Radiance's.
It redraws three of its 253 glyphs, and all three are used:

| glyph | class | which C64 options place it |
|---|---|---|
| 132 | weapon | weapon 13, small and large |
| 133 | weapon | weapon 13, small and large |
| 207 | hair | head 8 and head 13, large only |

So **three of the C64's 100 options draw a different picture on a Silver
Blades disk**: weapon 13 at both sizes, and large heads 8 and 13. The other 97
are pixel for pixel what Pool of Radiance draws, and Curse of the Azure Bonds
redraws none of the 100.

The measurement is `tools/iconproposal.py --compare-c64`, and it compares
**rendered pixels** rather than composed shapes -- which is what the earlier
grade got wrong, because the shapes agree and the pictures do not. Sample:
each of the 100 options composed alone on an empty figure, both poses, at both
sizes where the option exists, off each title's own disk; and separately all
1610 `(size, weapon, head)` combinations per title, where Curse differs in 0
and Silver Blades in 114 -- weapon 13 against all 23 heads at each size (46)
plus heads 8 and 13 against the other 34 weapons at the large size (68).

The three differing glyphs were already known and pinned:
`tests/test_silverblades.py::test_the_combat_icon_charset_is_pool_of_radiances_but_for_three_glyphs`
has asserted the set `{132, 133, 207}` all along. What was not known is that
combat figures use them.

**Within each title the icon files are one set.** `CHARPIC00` is the same 2030
bytes on all 8 Pool of Radiance sides, all 6 Curse sides and all 6 Silver
Blades sides; `SPELLE64` is the same 1882 bytes on every side that carries it,
in all three titles. So "the title's disk" is well defined and any side of it
will do -- what a document needs is the side carrying `SPELLE64`, `SPELLN64`
and `CHARPIC00` together, which is `POOL3.D64`, `CURSE_A.D64` and
`SILVER-1.D64`.

**Which rows of Donald's table this reaches.** DOS body 19 names C64 weapon
13, and DOS head 12 names C64 head 13, so both were judged against a Pool of
Radiance drawing that a Silver Blades player never sees. C64 head 8 is in
nobody's row today and is reachable if a row moves to it.

**What it does *not* mean: the conversion needs no per-title dimension for
this.** The composed thirty-six bytes are the same in every title, and the
figure is drawn by whichever game owns the disk the record was written to --
`editor/window.py`'s `game_files_for_import` loads `IconParts` off the
destination title's own disks, and the engine draws the codes through its own
`CHARPIC00`. A Silver Blades character converted onto a Silver Blades disk
already gets Silver Blades' weapon 13. What changes is only what a *document*
must show, and that is `tools/iconproposal.py --title`, which now draws both
sides off the named title's own art.

**Negative result worth keeping.** Curse of the Azure Bonds' C64 icon art is
Pool of Radiance's in every respect measured: `SPELLE64` byte-identical,
`CHARPIC00` byte-identical, 0 of 100 options redrawn, 0 of 1610 composed
figures differing. Only the load address moves, `$A700` to `$8E00`, which
`IconParts` fits from the pointers rather than assuming.

## The override reaches a document and not yet a conversion

`tools/iconproposal.yaml` grew an `overrides:` section for `#335 (Two
combat-figure rows describe Pool of Radiance's art, and Silver Blades draws
those two options differently)`, and Donald picked its first row on
2026-09-05: Secret of the Silver Blades' DOS head 10
becomes C64 head 2 rather than the base table's 15. The body half of that pair
is still open.

**That row does not reach a converted character today.**
`goldbox.iconparts.dos_icon_tables` applies an override only when it is given
a `title`, and `goldbox.dos._icon_for` calls `IconParts.dos_icon` with no
`tables` argument at all, so the no-title reading is what a conversion gets:

    dos_icon_tables().heads[10]                              -> 15
    dos_icon_tables(title="secret-of-the-silver-blades")     -> 2

Passing the title down from `to_c64_record` is the rest of `#335 (Two
combat-figure rows describe Pool of Radiance's art, and Silver Blades draws
those two options differently)`.
