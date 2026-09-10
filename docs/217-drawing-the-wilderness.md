# Drawing the wilderness — the order of work for `#11 (Draw the wilderness on the automapper)`

The situation: the automapper draws every dungeon and every city block, and
the moment the party takes the boat out of Phlan the map tab goes to a bare
lattice. Since `#205 (A party that walks out onto the travel grid leaves the
automapper's marker behind)` the tab at least says `Outdoors (7,29)` and
`Wilderness` and stops drawing a stale indoor marker; it still draws no
terrain, no party, and nothing the party has seen out there.

This is the plan another agent executes for
`#11 (Draw the wilderness on the automapper)`. Two earlier documents planned
halves of it and both have gone partly stale:
[`113-world-map.md`](113-world-map.md) is the reading half and
[`137-wilderness-automap.md`](137-wilderness-automap.md) the drawing half.
Everything they establish is graded and cited below rather than repeated, and
§6 lists what in them is now wrong. Four briefs on 2026-09-08 sent agents at
work that was already finished, so §0 comes first.

## 0. What exists already

| piece | where | state |
|---|---|---|
| detect the travel grid live: the `OUTDOORS` status line and the `$49E6` = 0 / `$49C3`/`$49C4` fallback, gated on `Title.travel_grid` | `automap/target.py`, `automap/c64.py` | **done**, `#205 (A party that walks out onto the travel grid leaves the automapper's marker behind)` |
| the mapper's third mode, `AutomapState.outdoors`; the strip's `Outdoors (x,y)`, the label `Wilderness`, the status `Outdoors, no map` | `automap/state.py`, `automap/panel.py`, `automap/window.py` | **done**, same issue; the three strings are Donald's |
| read `SQRDATA04`/`05`/`06` off the disks, the 18 x 36 grid, the 120 tile entries, the stitch at world x 15 and 28 | `goldbox/world.py`, `tests/test_world.py` (19 tests) | **done**, commits `4836f23` and `806497c` |
| a party's outdoor state in a save, every port: `outdoors`, `travel`, and `geo` holding the `SQRDATA` number when outdoors | `goldbox/world_state.py` | **done**, `#352 (Handle world state for Amiga saves)` and `#376 (An Amiga party on the travel grid still cannot be converted to the C64 or DOS, because the reader refuses one)` |
| engine-written outdoor C64 saves and the tool that makes more | `work/p190/C64OUT1.D64`, `C64OUT2.D64`; `tools/c64outdoor.py` | exist on this machine; `work/p3/W1.D64`-`W7.D64` are **gone** |
| walking a party on the grid under VICE, one compass step at a time, with a screenshot per press | `tools/session.py` (`savecheck --walk`), `tools/outdoorstep.py`, `tools/windowsquare.py` | **done**, `#189 (The emulator driver cannot move a party on the travel grid, and reads its facing out of the word OUTDOORS)` |
| screenshots of the travel screen | `work/issue178/25-westwindow-arrival.png` (14,29), `25-westwindow.step3.png` (15,29), `26-middlewindow-arrival.png` (7,29) | exist; the "one screenshot" the ticket was waiting on has been on disk since `#178 (Fast Travel to the wilderness leaves the party on whatever overland square it last stood on)` |
| a second generator for a byte-a-square map, painted by the same `kind` dispatch | `automap/combat.py` and `CombatCanvas` in `automap/window.py` | the pattern to copy, not a thing to reuse |
| `passable()` and `site_at()` | `goldbox/world.py` | **stubs that raise**, on purpose: their tables are in `ECL19`/`1A`/`1B` and the script read is closed (`docs/115-review-the-scripts.md`) |

## 1. What is known

| claim | grade | where it is held |
|---|---|---|
| The overland map is `SQRDATA0n`, not a `GEO`: 648 bytes of 18 x 36 grid indexed `y * 18 + x`, then 120 entries of 18 bytes; resident at `$8C00`, matched 647/648 and 645/648 against the disk with every difference a hidden site | CONFIRMED | `docs/113`, `docs/90-specimens.md` "The wilderness set", `tests/test_p3.py`, `goldbox/world.py` |
| Three windows 13 columns apart, seams at world x 15 and 28, 179/180 and 180/180 seam squares agree; walkable x 2-15, y 2-33; the world is 40 x 32 | CONFIRMED | `goldbox/world.py`, `tests/test_world.py` recomputes the counts |
| The three grids differ from each other in **532, 558 and 595** of 648 bytes; a hidden site changes 1-3 | CONFIRMED, measured 2026-09-08 for this plan | recompute with piece 2's tool |
| Of 121,200 648-byte blocks at 8-byte steps across every other file on the 34 disks, 5,749 have every byte below 120, and the closest of them to any window differs in **554** bytes | CONFIRMED, same measurement | ditto -- this is the margin the identification in piece 2 rests on |
| The travel square is `$49C3`/`$49C4`, window-local; `$49C0`-`$49C2` freeze outdoors | CONFIRMED | `docs/113`, `docs/90`, `automap/target.py` |
| Outdoors the loaded-files cache holds the window twice: slot 3 = `SECSET` number and slot 4 = `SQRDATA` number, both the window's own (`05` and `85` on `1A`), and `$49C5` = the same number | CONFIRMED on the save side, read 2026-09-08 off `C64OUT1.D64`, `C64OUT2.D64` and `OUTC.D64` | `goldbox/savegame.py` `LOADED_FILES`; `docs/140-loaded-files-cache.md` "The outdoor form" |
| The same cache is kept live at `$6E13,X`, so slot 4 is `$6E17` and slot 8 (the `ECL`) is `$6E1B` | PROBABLE -- stated in `goldbox/savegame.py`'s comment on `LOADED_FILES`, never read live on the grid | measurement B |
| The wilderness charset is `SECSET04`/`05`/`06`, 1536 bytes = **192 glyphs**; every screen code in every tile the grids use lies in `$40`-`$FE`, which is exactly 191 codes; so glyph = code - `$40`, and with the set at `$6500` (`docs/140`) the VIC's character base is `$6300` | PROBABLE -- three numbers agreeing, none read off the chip | measurement A checks it against the screenshots; measurement B reads `$D018` |
| A tile entry is nine screen codes then nine attribute bytes | PROBABLE | `docs/113`; the low nibbles read as C64 colours from a vocabulary of seven (`$F`, `$A`, `$5`, `$E`, `$7`, `$9`, `$6`) |
| Most attribute cells have bit 3 set, which on a C64 means a **multicolour** cell whose own colour is the nibble & 7: `$F` draws yellow, `$A` red, `$E` blue, `$D` green; `$5` and `$7` are hi-res green and yellow. Three of a multicolour cell's four colours come from `$D021`-`$D023`, shared by the whole screen | PROBABLE -- hardware rule plus the screenshots, where the plains are light green ground with yellow speckle and the forest a hi-res dark green | measurement A reproduces the screenshots or it does not |
| So `docs/137`'s six "colour buckets" are real but misnamed: "light grey" is the yellow plains speckle on a light-green background, "light blue" is the sea, "green" is forest. What "light red" (`$A`) is -- coast, hills or mountains -- is not known | PROBABLE for the three, UNKNOWN for the fourth | measurement A |
| The high nibble of an attribute byte takes fourteen distinct values. Colour RAM is four bits wide | UNKNOWN what it is | measurement B compares the live `$D800` against the table |
| `SQRPACI00` (640 bytes, identical on POOL6/7/8) is 385 zero bytes, the identity tile remap `01`-`7F`, and then the `$0600` parameter block: `+2` = `$8C00` (`P_MAP`), `+4` = `$8B00`, `+7` = 20 (`P_STRIDE`, not the row stride), `+$12` = 17, `+$13` = 35 | CONFIRMED by matching the tail against `automap/combat.py`'s own offsets | corrects the "structured tail" in the 2026-09-04 comment on `#11 (Draw the wilderness on the automapper)` |
| Travel is eight-way, the compass 1 N, 2 NE, 3 E, 4 SE, 5 S, 6 SW, 7 W, 8 NW; the heading is at `$033D`, outside the save image | CONFIRMED that it is eight-way and unsaved | `docs/113`, `docs/90` (W2 and W3), `tools/windowsquare.py`, `tools/c64outdoor.py` |
| Which value of `$033D` is which direction | UNKNOWN | measurement B |
| The game's travel view is a window of squares around the party whose top-left is `CAMERA` `$037E`; the combat view is 7 across | PROBABLE for combat, UNKNOWN for travel -- the screenshots look narrower than seven tiles | measurement B reads `$037E` and the screen |
| A site is hidden by painting plain terrain over its square until its flag is set; four are known: `1A` (12,11) nomad camp, `1B` (11,8) lizardman keep, (6,15) kobold caves, (7,23) a site that was cut | CONFIRMED | `tests/test_p3.py` `PAINTED`, `docs/90` |
| The full site list (46) and the impassable-terrain tables, including `ECL1A`'s swap when `$4AB3` reaches 254, are in the scripts' own bytecode; their offsets went with `work/` (`#136 (Thirty-two cited write-ups are gone, because the knowledge base pointed into gitignored scratch)`) | UNKNOWN, and closed research | `docs/115-review-the-scripts.md`; `goldbox/world.py`'s docstring |
| `$4A9E` is 0 on the grid and 255 in a random cave, which is `GEO19`/`1A`/`1B` and draws with the existing code | CONFIRMED | `docs/113` |
| Only Pool of Radiance has a travel grid: Curse and Silver Blades ship no `SQRDATA` or `SQRPACI` | CONFIRMED | `goldbox/c64_port.py` `travel_grid`, `docs/121-silver-blades.md` |
| Two candidate looks, both Donald's, 2026-09-04: the game's own tiles read off the player's disk at run time, or game-icons.net icons (`mountain-cave`, `forest`, `grass`, Delapouite). An older ruling (`docs/137` §3) said not to reuse the game's graphics; the later comment reopened it | a decision, not a fact | the 2026-09-04 14:48 comment on `#11 (Draw the wilderness on the automapper)` |

## 2. What has to be measured first

Two measurements, and the drawing cannot start before the first. The
ticket's own blocker -- "one screenshot of the travel screen" -- is already
met three times over in `work/issue178/`; what those screenshots cannot do is
name a hill, because none of them has one in view.

### A. The tile sheet -- no emulator, an hour or two

Render every one of a window's 120 tiles as the game draws it: nine glyphs
out of `SECSET0n` (glyph = code - `$40`), each cell in hi-res or multicolour
by bit 3 of its attribute, the cell colour the low nibble & 7, the three
shared colours taken from the screenshots (the plains ground is light green,
`$0D`). Do all three windows, label each tile with its index and how many
grid squares use it, and write the PNGs to `work/issue11/` -- they are the
game's art and are never committed; the tool is.

**The check that can fail:** render the 7 x 7 (or whatever B says) around
`SQRDATA04` (14,29), `SQRDATA04` (15,29) and `SQRDATA05` (7,29) and put each
beside its screenshot. If the coastline, the forest edge and the speckle land
where the screenshot has them, the glyph offset, the nibble rule and the
palette are right together; if not, one of the three PROBABLEs above is wrong
and the sheet says which.

What it settles: which tiles are sea, plains, forest, coast, hills,
mountains, marsh, river and road, by looking; whether the `$A` bucket is one
terrain or several; whether 120 pictures reduce to the six-or-so classes look
2 needs. And it **is** the sample for look 1 -- the same renderer at 34 and 20
pixels a square is what Donald picks from.

Read the charset off the disk through `goldbox.d64.load_payload`; the
`SECSET` PRG header's load address is not where it runs (`docs/140`), so
skip the two bytes and index from zero.

### B. One session on the grid -- emulator, one pool slot, about half an hour

Boot `work/p190/C64OUT1.D64` (middle window, (8,27)) the way
`tools/outdoorstep.py` does, and in one stop read:

| bytes | what it settles |
|---|---|
| `$D016`, `$D018`, `$DD00` | multicolour on, and the character base -- the `$6300` inference |
| `$D021`-`$D023` | the three shared colours, so the sheet stops guessing them from a PNG |
| screen RAM and `$D800` colour RAM over the map pane, with `$037E` | the view size, and whether the attribute high nibble reaches the chip at all: colour RAM at a cell should read the table's low nibble and nothing else |
| `$6E13`-`$6E2B`, `$49C5` | the live cache: slot 4 and slot 8 against the save's `$4BC4`/`$4BC8` |
| `$8C00`-`$8E87` | a fourth resident-window match, and the baseline for the tolerance in piece 2 |
| `$033D`, then after pressing each of `1`-`8` in turn and returning | the eight-way encoding. `outdoorstep.py` already presses the digit and reads `$49C3`/`$49C4` around it; add the one byte |

Then a screenshot standing on a `$A` tile if the sheet has not already said
what one is. `tools/outdoorstep.py` and `tools/c64outdoor.py` have the
staging, the pool claim and the monitor reads; this is a `--registers`
option on one of them, not a new driver. Nothing in it writes to the player's
disks; the save is copied into the slot.

### What is not a measurement

The site list and passability are not measured here. Drawing needs neither
(§4, piece 3): the resident block at `$8C00` is the map **as the game has
painted it**, hidden sites and all, so a mapper that records what was resident
when the party saw a square shows exactly what the game showed and consults
no flag.

## 3. What is a decision, and whose

**Donald's**, because a player reads it:

1. **The look** -- the game's tiles at run time, or icons. Not chosen by the
   implementer. The useful form is measurement A's renderer drawing the same
   piece of map both ways at 34 and 20 pixels a square, in `work/issue11/`,
   linked from the issue, and asked. Until it is chosen the world canvas
   draws flat squares in the classes the sheet named, or nothing.
2. **Every string.** The strip already says `Outdoors (x,y)` in the game's
   own window-local pair; whether the canvas's world coordinate should appear
   anywhere is his. A tooltip naming a square's terrain ("Forest", "Sea"), a
   site's label, and any legend are strings this plan needs and does not
   write; name them in the issue as `TERRAIN_NAMES`, `SITE_LABEL`, and wait.
3. **Reopening the script read** for the 46 sites, the river swap and the
   disk line ("Buccaneer Base -- disk 6"). Closed at his direction on
   2026-08-31; nothing below needs it, and piece 7 is the only thing waiting.
4. **Whether a note may be pinned to an outdoor square.** The lattice refuses
   a click outdoors today (`automap/window.py` `mouseReleaseEvent`) because
   there was no square to pin to; once there is, allowing it is a change to
   what he sees.

**Ours**, because it is how the code is arranged:

* reading the resident block live rather than only the disk; storing the
  tile code seen with each explored square; the reveal rule (what the game's
  own view showed, measured in B); the module split (§4); the identification
  tolerance and plausibility clauses, provided each is measured and written
  beside its constant the way `automap/area.py` does; a `Cells` primitive in
  `render.py` for look 1, if look 1 is chosen.

## 4. The order of work

Each piece is one reviewable commit with a test that goes red without it.
Pieces 1 and 2 need no emulator and can start now; 3 to 5 need measurement
B's answers only where marked; 6 waits on Donald.

**1. `tools/worldtiles.py`, measurement A.** `sheet` writes the three
sheets; `view WINDOW X Y` writes the game's own pane around a square; `sample
X Y --cell 34` writes the two looks side by side once piece 5 exists. Reads
the disks through `automap.paths.find_disks`, writes only under `--out`.
*Test:* `tests/test_worldtiles.py` renders a synthetic tile (one glyph, one
attribute) and asserts the pixel colours -- hi-res cell, multicolour cell,
and that bit 3 selects between them. Fails if the nibble & 7 rule or the
`$40` offset is dropped. The comparison with the screenshots is done by eye
and reported on the issue, not asserted in a test, because the screenshots
cannot be fixtures.

**2. `World.identify(block)` in `goldbox/world.py`.** Match 648 bytes against
the three windows; answer `(index, distance)` or None. Two clauses, both
measured: every byte below 120 (the grid's own invariant, 0 of 1944 violate
it) and distance at most `SITE_PAINT_TOLERANCE`, set from the measurements
above -- 16 leaves a factor of thirty under the 532-byte spread between
windows and the 554-byte closest impostor. Add `tools/geoplausible.py`-style
`worldplausible` reporting to `worldtiles.py` or its own tool so the numbers
are re-takeable. *Test:* each disk window identifies itself at 0; each with
its `PAINTED` squares altered still identifies; a page of zeroes and a real
`GEO` block do not. Fails if the tolerance goes to 0 (the painted case) or if
the byte-below-120 clause is removed (zeroes pass, since a zero page is
inside any tolerance of nothing -- it differs in every non-zero byte, so this
clause is what refuses a *sparse* impostor; measure it rather than trust this
sentence).

**3. Identify and record outdoors, in `automap/state.py`.** `_poll_outdoors`
gains a resident check on the `RESIDENT_EVERY` cadence and on the first
outdoor tick: read `$8C00` through `Target.read` (one resume; the cost is the
round trip, not the 648 bytes), `World.identify`, and set `state.window`. The
fix becomes a world coordinate, `fix.x + 13 * window`, and the square is
recorded into a world exploration keyed by world `(x, y)` holding `(window,
code)` -- the code from the resident block, which is the painted form the
game showed. The world is loaded beside the maps in `automap/maps.py`
(`World.from_disks` over the same disk globs; absent disks mean no world, not
an error). This also closes the residual from `#205 (A party that walks out
onto the travel grid leaves the automapper's marker behind)`: a window opened
on a camped outdoor party stops reading `identifying...`, because the
resident window is the proof a game is running. *Test:* `ReplayTarget` whose
`read` answers a disk window's bytes at `$8C00` -- the mapper sets `window`,
records world squares, and a step from `1A` (15,y) to `1B` (3,y) records
world x 28 then 29, adjacent. A target answering zeroes records nothing. Fails
without the identify, and the seam test fails without the `13 * window`
shift. Reveal only the square itself until measurement B gives the view
size; then the view.

**4. Persist it.** `save_notes`/`load_notes` write the world set under a
fixed name beside the per-area files, `{data dir}/maps/{title}/wilderness.json`,
each entry `"28,10": [1, 34]`. *Test:* round trip; a file from before this
piece (no `world` key) loads with an empty world set.

**5. Draw it.** `world_primitives(world_seen, cell, margin)` in
`automap/render.py`, Qt-free like everything else there: one `Rect` per
recorded square with `kind` `terrain-<class>` (flat, until the look is
chosen), the party marker, and nothing else -- no walls, no doors, no edge
merging. `party_marker` takes eight facings, and a facing of None draws no
nose; the heading itself comes from `$033D` once B has the encoding, read in
`read_fix` for a `travel_grid` title only. A `WorldCanvas` is the third page
of `map_stack`, 40 x 32 with the same `cell`/`origin` arithmetic as
`MapCanvas`, and `poll` picks the page: outdoors with a window drawn, outdoors
without one bare, indoors as today. *Tests:* primitive count equals recorded
squares; no primitive is emitted for a square the party has not seen (the
"do not draw the unvisited world" rule, as an assertion); `to_svg` of a world
renders; eight facings give eight distinct polygons; an offscreen binding
handed outdoor fixes shows the world page and, back indoors, the map page.
Fails without the page switch, and the unvisited-world test fails the moment
somebody draws the disk instead of the record.

**6. The look, once chosen.** Look 1: a `Cells` primitive (a small colour
grid) painted by `QImage` in the canvas and as `<rect>`s in SVG, filled from
`SECSET0n` and the tile entry at draw time, off the player's own disk;
nothing committed. Look 2: a per-window `tile -> class` table proposed from
the sheet and confirmed by a human, six or seven `kind` rows in `SVG_STYLE`,
the icons Donald named through `wish/licenses.py`'s attribution, and hills
and marsh left as plain squares until a person draws two marks
(`.claude/rules/art.md`: nothing generated, nothing nudged). *Test:* look 1 --
a synthetic tile round-trips to known pixels; look 2 -- every class in the
table has a style row, and every tile a window's grid uses has a class.

**7. Sites, the river and the disk line.** Waits on decision 3. If reopened:
`tools/eclwalk.py` already decodes 98% of every script by walking from the
five entry points and reports the data tables it stops at -- the site tables
and the impassable list are those tables, so the offsets are a matter of
reading `eclwalk.py list`'s unreached ranges for `ECL19`/`1A`/`1B`, not of
rebuilding a decoder. Until then, sites appear exactly when the game paints
them, which piece 3 already gives.

## 5. What this shares with the other map work

**`#436 (The map plausibility check throws out five of Pool of Radiance's own
maps)`.** `looks_like_a_map` judges a `GEO` by its barrier plane -- reciprocity,
walled edges, wall-art agreement, wall-pair reuse. A `SQRDATA` has no barrier
plane and no edges, so none of that machinery can judge it, and piece 2 does
not try. What transfers is the **method**: measure the worst real specimen
and the best impostor over everything on the disks and put the constant
between them with the two numbers beside it. The wilderness's own invariant
is stronger than a map's: 648 indices, every one below 120, and a 532-byte
minimum spread between the only three real specimens. The sweep above is the
first take; piece 2 re-takes it with a committed tool.

**`#443 (Three of Curse's sixteen maps differ between the C64 and the Amiga,
and nobody has looked at how)`.** An exact match against one port's disk copy
is fragile when another port ships different bytes. For the wilderness the
question does not arise yet -- the C64 is the only port whose overland data
has been located -- but piece 2's tolerance is per measured site paint, not a
port allowance, and must not be widened to absorb another port's file.

**`#37 (Automap the Amiga version, not just the C64)`.** Pieces 3 to 5 read
through `Target.read` and nothing VICE-specific, which is what let the Amiga
backend reuse `ResidentGeo` unchanged; keep it so and the world identifies
the same way there. Three things are not shared and are not this plan's:
Amiga Pool of Radiance has no `MACHINES` row (a many-hunk executable, per
that issue's 2026-09-08 comment), its overland data file has not been
located (DOS's is `BACPAC.DAX`, 40 tiles at 24 x 24 per
`docs/145-dos-decode-kit.md`, and the C64's 120-entry vocabulary is not that
-- so look 1 is per port, and look 2's class table is per port too), and a
15-22 second poll suits a canvas that redraws on a move, which the world
canvas is.

## 6. Corrections to the two earlier plans

For whoever next edits them; this document does not.

* `docs/113` "What is unknown" 2: `$49FB` prints `OUTDOORS` -- settled in
  `docs/90` and `#205 (A party that walks out onto the travel grid leaves the automapper's marker behind)`. 4: `$4BC0` reads `00` outdoors -- settled the same
  way. Step 4's save-side half is done in `goldbox/world_state.py`. Step 5,
  "take W1 and the two live captures", was done and the captures then lost
  with `work/p3/`; `work/p190/` is what replaces them.
* `docs/113` "The saves to take" is a list Donald was to play through; every
  save in it that still matters is now made by `tools/c64outdoor.py` without
  him, and the W8/W12 cave-and-encounter cases are the only ones nobody has.
* `docs/137` §2 is done and says so; §3's colour table names the raw nibble
  and is wrong about what the colours are (§1 above); §5's first row is met
  by `work/issue178/` and its "not needed" row -- the `SECSET0n` glyph -- is
  now measurement A. §4's canvas and third page are piece 5.
* The 2026-09-04 comment on `#11 (Draw the wilderness on the automapper)` calls `SQRPACI00`'s tail "a ~20-byte
  structured tail"; it is the `$0600` parameter block, and the "DOS names
  transfer" refutation stands.

## 7. Kept from the earlier plans

* **Do not draw the unvisited world.** Piece 5 asserts it.
* **Do not read a tile code against another window's table.** The record
  stores the window with the code; `goldbox/world.py` already has no path
  that takes a bare code.
* **Do not reuse `GEO` passability or sight.** One byte, one picture, no
  edges; the reveal rule is the game's own view, not corridor sight.
* **Do not draw a site the game has not drawn.** Recording the resident block
  does this without a flag table.
