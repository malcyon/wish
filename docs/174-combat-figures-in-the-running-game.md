# Reading a combat figure off the running C64

What a party's combat figures are on the screen, how to compare them against
the eighteen screen codes a save holds, and what 405 readings of one fight
established. Taken for
`#184 (A converted combat icon's colours are proven in the game and its shapes
are not)`; the file-level side of the icon is `goldbox/icons.py` and the DOS
side is `docs/168-dos-dax-and-combat-icons.md`.

## What is on the screen

A combatant is a **3x3 block of nine consecutive screen codes**, and the codes
are not the icon's own. The engine copies each combatant's glyph bitmaps into a
combat character set and hands out sequential codes as it goes: in the fights
read here the six party members were drawn from `$5E`, `$67`, `$70`, `$79`,
`$82` and `$8B` -- six runs of nine, nine apart -- while all six icons in the
save named the same eighteen codes. So searching the screen for an icon's own
codes finds nothing, which is what a first pass reported.

**The window puts square `(x, y)` at row `1 + 3 * (y - y0)`, column
`1 + 3 * (x - x0)`** for a camera at `(x0, y0)`, which `$037E` holds. CONFIRMED
on six party members in each of three fights; `tools/savecheck.py`'s
`where_drawn` is the one definition.

**The combat character set is at `$D000`**, computed from `$D018` and `$DD00`,
which is RAM *under* the VIC's I/O registers. A binary-monitor read there
answers the registers unless it goes through the bank named `ram` --
`#265 (The combat-icon glyph check reads VIC registers instead of the character
set, and half of it passes anyway)`, and `tools/vicebankcheck.py` re-measures
the bank numbering. Colour RAM at `$D800` is only reachable *through* I/O, so
that read stays on the default bank. One read wants each bank and they are
eight bytes apart.

## What to compare against

An icon's screen codes index **`CHARPIC00`**, not the C64's ROM character set.
`CHARPIC00[code * 8]` is the eight bitmap bytes the engine copies, so the
comparison is: read the nine glyphs the figure was drawn from, and check them
against `CHARPIC00[code * 8]` for the nine codes that character's own save slot
holds.

**`$A0` is not the reversed space here.** In the ROM charset it is eight `$FF`s;
in `CHARPIC00` glyph 160 is `003cfcf4d4f4dc90`, the top of a figure's head, and
that is what the engine copies. `#184 (A converted combat icon's colours are proven in the game and its shapes are not)` proposed checking for `$FF`s and the
check could never have passed. Its companion, glyph 32, is eight zero bytes in
both, which is why half of the proposed check passed by coincidence twice over.

Monster figures come from other art: the two enemy glyphs read in these fights,
`30171f5555150526` and `0000080808080888`, appear nowhere in `CHARPIC00`'s 253
glyphs. That makes the enemies a free negative control, and they scored at best
1 of 9 cells against every icon in the save, 606 readings.

## What 405 readings said

One fight, 80 turns, a party of six deliberately different icons written by
`tools/iconpoke.py`. Every party figure was scored against 32 candidates --
both poses of all eight save slots, plain and mirrored -- and **every one of
the 405 named exactly one**.

| what was drawn | readings | matched, 9 of 9 |
|---|---|---|
| a party member whose pose byte is 0 | 360 | its own slot's first pose |
| a party member whose pose byte is 2 | 45 | its own slot's first pose, mirrored |
| an enemy | 606 | nothing, best 1 of 9 |

The pose byte is the low two bits of the position table's third byte,
`slot << 2 \| pose`, which `automap/combat.py` already reads.

**Mirroring is per cell and by the cell's own colour byte.** Bit 3 set means
multicolour -- four double-width pixels, so turning the cell over reverses the
four bit pairs -- and clear means hi-res, where it reverses all eight bits. The
cells also swap left to right within each row. Reversing every cell as
multicolour scores 8 of 9 for an icon with one hi-res cell, in every reading of
it, and that reads exactly like a fault in the game.

**A converted party is drawn from the bytes the conversion wrote.** The same
run on a disk `tools/dosdisk.py` had just built: 6 of 6 party figures, 9 of 9
glyphs, against the eighteen codes `IconParts.default_icon` composed. Which
slot cannot be told there and never will be, because the conversion writes one
icon into all six --
`#130 (A converted DOS party arrives with six identical combat figures, not its
own)`.

## What is not established here

**An icon's second nine codes are not on the combat floor when the game stops
to ask for a command.** Each combatant's run in the combat character set is
nine codes long, so the charset holds one pose at a time, and the pose byte
selected handedness rather than the second pose in all 405 readings.

The driver passed every turn here -- the run's own summary is *"A party member
struck on 0 of 80 driven turns"* -- so the attacking frame was the obvious
candidate. **That experiment has since been run and it is not the answer at
this granularity**: a party that struck 35 blows on 42 turns still read as the
first pose at all 178 of its command-bar readings.

Where the second nine *are* drawn, what the game calls them, and the table
`COM.PREP` expands both poses into is
[`186-ready-and-action.md`](186-ready-and-action.md). The short version is that
they are the ACTION pose, a player sees them in the icon editor in camp, and
the engine fetches them once per turn for whichever character is acting.

## Reproducing it

```sh
tools/iconpoke.py --disk work/issue184/SIX.D64        # six different figures
POR_HEADLESS=1 tools/savecheck.py --disk work/issue184/SIX.D64 --fight --icon
```

`--icon` reads the disk's own eight icon entries and `CHARPIC00` off the
player's disks, scores every figure on the floor before the first blow and
again on every command bar, and writes the drawn bitmaps into its `.jsonl` --
so a comparison can be re-run offline without spending another emulator slot.
