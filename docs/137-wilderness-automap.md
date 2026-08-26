# The automapper in the wilderness — a plan

Donald: *"When I load up `work/p3/W1.D64`, I can see that I am in the
wilderness. The automapper does not display anything."*

He is right, and the reason is not one bug. This is the drawing half of
[`113-world-map.md`](113-world-map.md), which planned the *reading* half and
stopped at step 5 — "take W1 and the two live captures, stop here until they
exist". **They exist now** (`docs/90-specimens.md`, the `W1`–`W7` set), so the
block is lifted and the remaining question is what to draw with.

## 1. What the wilderness areas are

Three areas, 25–27, scripts `ECL19`/`ECL1A`/`ECL1B` on POOL6/7/8. CONFIRMED,
and `goldbox/areas.py` already carries them with `sqrdata=` set.

**`SQRDATA` is what an overland map is made of, not `GEO`.** Each of the three
areas names *both* a `GEO` and a `SQRDATA`, and `LOADFILES` picks which to fetch
from `$49E6` rather than from the operand. The `GEO` is the area's **cave** —
the "small dark cave" a random encounter offers — and it is an ordinary dungeon
map the existing renderer already draws. The open world is the `SQRDATA`.

| | |
|---|---|
| what a `SQRDATA` is | 648 bytes of grid — **18 × 36, one byte a square**, indexed `y * 18 + x` — then **120 tile entries of 18 bytes** each |
| a tile entry | nine screen codes then nine colour attributes: a 3 × 3 block of characters out of `SECSET0n` |
| the three files | `SQRDATA04`/`05`/`06`, overlapping windows on one world, 13 columns apart, west to east; the world is 40 × 32 |
| size check | `SQRDATA05` is 648 + 120 × 18 = 2808 exactly; the other two carry eight spare bytes |
| in memory | `$8C00`, matched against the disk in 647 of 648 bytes, every difference a site square the script paints over while its flag is clear |

All CONFIRMED; `tests/test_p3.py` pins the arithmetic against the player's own
disks.

**The three have no arrival square and must not be given one.** Outdoors the
party's position is `$49C3`/`$49C4`, not the `GEO` pair, and every script that
enters an overland area writes the world-map cell rather than a static square —
`work/reports/p20-arrivals.md` §4. A `GEO` square written for one of them is
meaningless at best.

## 2. Why nothing draws

**It fails to identify the area, so it draws the empty grid.** Not a blank
window and not a wrong map: `automap/window.py` paints the 16 × 16 rule, finds
`state.geo is None`, prints `area_label` in the middle and returns before the
party marker. Three independent links in the chain, each of which would do it
alone.

**a. The status line does not match.** `target.RE_STATUS` is
`([NESW]) +(\d+):(\d+) +(\d+),(\d+)` — facing letter, clock, x, y. Outdoors the
game prints **`OUTDOORS 21:32 5,2`**: `$49FB` gates the word `OUTDOORS` into
the slot the facing letter occupies indoors (`docs/90-specimens.md`, the `W1`
set). No match, so the authoritative fix is never read. CONFIRMED.

**b. The memory fallback reads the wrong pair, and it is plausible.**
`party_fix` falls back to `$49C0`/`$49C1`/`$49C2`. In `W1.D64` those hold
**15, 1, 3** — the stale indoor square from before the party left — while the
travel position at `$49C3`/`$49C4` is **5, 2**. `_plausible` passes on 15,1,3,
so the mapper is handed a confident wrong answer rather than nothing. CONFIRMED,
read off the save.

**c. No `GEO` is resident, so `ResidentGeo` never names an area.** It matches
the 1024 bytes at `$0400` against the disk `GEO`s; outdoors the square engine's
descriptor is there instead. Warping into all three overland areas found
`$49E6` = 0 and **no `GEO` resident** (`work/reports/p20-arrivals.md`).
`Fingerprint`, fed the frozen (15,1) fix from (b), never narrows either.
CONFIRMED.

**And the save-side reader agrees with none of it.** `SaveGame0.area` masks
`$4BC2`, which reads `$80` in `W1.D64` — dirty bit off, **map number 0** — so
`area_file` says `GEO00`, New Phlan. The byte that carries the real answer is
`$4BC4` = `$85` → `SQRDATA05`, and nothing reads it. `$4BC0` reads `00`
outdoors against `01` in all fourteen indoor saves, which is the cheap state
test.

**The fix for (a) and (b) is small and worth doing first**, independent of any
drawing: a second status pattern for `OUTDOORS`, and a memory fallback that
reads `$49C3`/`$49C4` when `$49E6` is 0. Until then the mapper is not merely
silent outdoors, it is holding a wrong square.

## 3. The terrain, and the constraint that shapes everything

Donald: *"We will need to figure out what to use for each terrain's graphic. We
cannot reuse the graphics from the game. Something simple would be ideal, like
black and white icons used in D&D hex maps."*

### What the data actually distinguishes — and it is not a terrain enum

Counted off the player's disks:

| file | distinct codes in the grid | code range |
|---|---|---|
| `SQRDATA04` | 90 | 0–101 |
| `SQRDATA05` | 110 | 0–119 |
| `SQRDATA06` | 111 | 0–119 |

The codes run 0–119 and the tile table has exactly 120 entries, so **the square
byte is the tile index** — it names a *picture*, not a terrain class. Ninety to
a hundred and eleven pictures per window is coastline variants, forest edges,
and one-off art for a site, not a vocabulary anybody wants to draw symbols for.
Worse, a code means whatever its own window's tables say and the three disagree:
`2E` is walkable mountain on map `19` and solid on map `1B`.

**So a code → terrain-class mapping does not exist in the data and has to be
made.** That is the first task and the drawing cannot start before it.

### The cheap handle, measured

Each tile entry carries nine **colour attributes**, and the C64 palette is doing
the same work a legend does. Taking the dominant colour of each tile and
weighting by how many squares carry it:

| window | green | light grey | light red | light blue | yellow | brown/blue |
|---|---|---|---|---|---|---|
| `SQRDATA04` | 53 | 281 | 254 | 59 | — | 1 |
| `SQRDATA05` | 206 | 168 | 140 | 128 | 5 | 1 |
| `SQRDATA06` | 224 | 48 | 182 | 147 | 46 | 1 |

**Six colours cover the whole world**, and the extremes read straight off: tile
75 is nine cells of screen code `$FE` in light blue and is the most common tile
in both eastern windows — that is the **sea**. Tiles 34 and 30 are all-green
3 × 3 blocks; tiles 0 and 2 are all-light-grey. Tile 37 is light grey with two
green cells, which is exactly what "hills with trees on them" looks like as an
attribute pattern.

This is a **PROBABLE** first cut, not a decode: colour narrows 120 pictures to
six buckets and the screen codes separate variants within a bucket, but which
bucket is hills and which is mountains needs one look at the real screen. It
needs no emulator to compute and no game art to ship — the classification is a
table of integers we write, and the pictures stay on the player's disk.

### The symbols, and where they may come from

Traditional cartographic marks, black on paper, the way the rest of the map is
drawn:

| terrain | the mark a person draws | Font Awesome Free |
|---|---|---|
| forest | two or three small conifers | `tree` — has it |
| hills | two nested bumps | **nothing** |
| mountains | open chevrons, one behind another | `mountain`, `mountain-sun` — has it |
| marsh | short horizontal tufts | **nothing** |
| water | parallel wave lines | `water` — has it |
| plains | empty, or a sparse dot | nothing needed |
| road | a dashed line along the square | not an icon; a stroke |
| settlement | a small square block, or a tower | `chess-rook`, `city`, `tower-observation` |

Three of the seven exist in Font Awesome Free, three do not, and two of the
marks — road and marsh tufts — are strokes across a square rather than glyphs at
all, which the renderer draws directly the way `hatch_lines` already draws rock.

**Under `CLAUDE.md`'s Art rule the answer for the rest is Font Awesome, another
set with a licence we can honour, or a human being. Never generated, not even
as a placeholder "until we find a real one", and never a Font Awesome path
nudged until it fits.** A hills symbol is two arcs; it is exactly the kind of
thing a person draws in a minute and an assistant must not draw at all. The
honest interim is to ship the terrain classes the renderer *can* mark —
water, forest, mountain, settlement — and leave hills and marsh as plain
squares with the class in the tooltip until a human draws two marks.

## 4. What `automap/render.py` needs

**One module, a second generator — not a second renderer and not a mode flag
on the existing one.** The precedent is already in the tree:
`automap/combat.py` reads a byte-per-square map of exactly this shape and emits
`Rect`, `Hatch`, `Line` and `Label` from `render.py`, and `window.py` paints
them by `kind` without knowing which map it is looking at.

| what | why |
|---|---|
| `map_primitives` stays as it is | it loops `range(GRID)` twice and merges wall edges from both sides; none of that means anything outdoors |
| a new `world_primitives(world, visible, cell, margin)` | one `Rect` per square for the terrain class, a `Glyph` for the mark, and nothing else. No walls, no doors, no edge merging, no reciprocity |
| new `kind` values and `SVG_STYLE` rows | `terrain-water`, `terrain-forest`, … one line each, and the Qt painter picks them up through the same dispatch |
| the party marker | `party_marker` already takes a facing; **travel is eight-way** (`$033D`), so it needs eight positions rather than four |
| the canvas | 40 × 32, not 16 × 16. `CELL` and `MARGIN` are already parameters; `GRID` is imported from `goldbox.geo` and is the one hard 16 in the file |
| a third page in the `QStackedWidget` | only one of area / combat / world is ever true |

`goldbox/world.py` is the reading half and is specified in
[`113-world-map.md`](113-world-map.md) §"The work, in order" step 2. It is
transport-free, testable against the disks today, and nothing here duplicates
it.

## 5. What is unknown, and the experiment that settles it

| unknown | the experiment |
|---|---|
| **which colour bucket is which terrain** | one screenshot of the travel screen, next to a rendering of the tile table's colours. Half an hour, no code. This is the blocker on everything downstream |
| whether the buckets are even the right partition | render all 120 tiles of one window as coloured 3 × 3 blocks, offscreen, and look at them as a sheet. Same rig as `tools/iconsheet.py`. **The sheet is a working file and is not committed** — it is the game's art |
| the eight-way facing encoding | `$033D` is page 3 and is not in the save; W2/W3 proved the travel facing is not saved at all. A live read while turning |
| whether the impassable lists are per-window complete | `ECL19`/`1A`/`1B` each carry one; map `1B` reserves a stamp for a site that does not exist |
| what a `SECSET0n` glyph looks like | **not needed.** Drawing the game's own art is what this plan exists to avoid |

**Do not start drawing before the first row is answered.** A map that calls the
hills mountains is worse than no map, because it looks right.

## 6. What not to do

Carried forward from [`113-world-map.md`](113-world-map.md), because they apply
to the drawing as much as the reading:

* **Do not draw the unvisited world.** The whole 40 × 32 is sitting on the disk;
  showing it hands the player the map the game sold in its box. Terrain is drawn
  where `Exploration` says the party has been, exactly as a `GEO` is.
* **Do not read a terrain code against another window's table.**
* **Do not reuse `GEO` passability logic.** One byte, one terrain, one lookup —
  there are no walls, no doors and no per-square attribute byte out here.
* **Do not draw a site the flags say is still hidden.** The game paints plain
  terrain over it, and the map should show what the player has been shown.
