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
