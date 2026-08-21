# The overland travel map — plan

**Status: researched, nothing built. No save has ever reached it**, so every
line below rests on disk files, disassembly and one foreign save. The research
is `work/reports/world-map.md`; this is what to do with it.

The headline: **the overland map is not a `GEO`.** It is the combat square
engine — `SQRPACI` descriptor, one byte a square at `$8C00` — pointed at
`SQRDATA0n` instead of a combat arena. `automap/combat.py` already reads that
shape, which makes this much cheaper than it looks.

---

## What is known, and how sure

| claim | confidence |
|---|---|
| Three travel maps: areas `$19`, `$1A`, `$1B`, scripts `ECL19`/`ECL1A`/`ECL1B` on POOL6/7/8 | CONFIRMED |
| The terrain is `SQRDATA04`/`05`/`06`, **18 x 36, one byte a square**, at `$8C00` | CONFIRMED |
| Its layout is 648 bytes of grid then 120 x 18 bytes of tile glyphs — `SQRDATA05` is 648 + 120x18 = 2808 exactly | CONFIRMED |
| The three are **overlapping windows on one world, 13 columns apart, west to east** | CONFIRMED — 179/180 and 180/180 squares agree, and the edge-crossing arithmetic closes independently |
| Walkable is `x` 2..15, `y` 2..33 of each window; the world's playable area is **40 x 32** | CONFIRMED from the edge tests and the southernmost site |
| The party's travel position is **`$49C3`, `$49C4`** — a separate pair from `$49C0`/`$49C1` | CONFIRMED by `npc_party.d64` |
| Travel is **eight-way**, direction in `$033D` | CONFIRMED |
| `$4A9E` = 0 on the grid, 255 inside that map's own cave (`GEO19`/`1A`/`1B`) | CONFIRMED |
| `$49E6` is `inDungeon` — 0 selects the overhead view, non-zero the 3D one | CONFIRMED against the Azure Bonds reimplementation |
| Each script carries its **site list** as four tables (y, count, x, event) and its **impassable-terrain list** as one more | CONFIRMED — 46 sites read off, all three maps |
| `ECL1A` swaps its terrain table when `$4AB3 >= 254`: clearing the Stojanow pollution **opens the river to travel** | CONFIRMED |
| Sites are hidden by **painting plain terrain over them** until their flag is set, so the map is rebuilt from file + flags and is never saved | CONFIRMED |
| The row stride is `$0612 + 1` = 18, **not** `$0607` = 20 | CONFIRMED from `GDRIVE00 $C3AF` |
| `SECSET0n` is the character set the glyphs are drawn from | PROBABLE |
| The 18-byte glyph entry is nine screen codes then nine attributes | PROBABLE |
| A terrain code means whatever its own map's table says; the three disagree | PROBABLE |
| `GDRIVE00` is the square driver, `GDRIVE01` the 3D one | PROBABLE |

### Correction to `docs/88-map-files.md`

`GEO10` and `GEO11` are **not** wilderness. `ECL10` is the lizardman keep and
`ECL11` the nomad camp, and each loads its own number: they are open-air
*sites*, which is why they read as unroofed. `GEO19`/`GEO1A`/`GEO1B` are the
wilderness **caves** — the "small dark cave" a random encounter can offer — which
is why they are fully roofed with no doors.

### Correction to `docs/101-combat-view.md`

The stride comes from `$0612 + 1`, not `$0607`. For combat both are 56 and
nothing is broken; for the overland map `$0607` is 20 against a true stride of
18, so `automap/combat.py`'s `shape_from_params` would shear it. One-line fix,
and it should be made before the reader is pointed at anything overland.

---

## What is unknown

1. **Whether `$8C00` in memory equals `SQRDATA0n` on disk.** Everything else is
   file archaeology; this is the one link that has never been observed. 648
   bytes read while the party stands outdoors settles it.
2. **`$49FB`**, which is 0 on the grid and 255 in the cave and gates a display
   item next to the clock. What it prints has not been seen.
3. **Where the travel facing is kept.** `$033D` is page 3 and is not in the
   save. Whether `$49C2` shadows it is untested.
4. **`$4BC0`.** GDRIVE00 carries the square code, GDRIVE01 does not, and all
   fourteen saves read `01`. A travel-grid save should read `00`.
5. **What a travel step costs in game time.** `ECL19 $AEA3` writes
   `$6DD2`/`$6DD3` differently depending on `$49E6`; GUESS that this is the
   step cost.
6. **`SECSET0n`'s bitmaps** and the glyph attribute nibbles — needed only to
   draw the game's own art, not to draw the map.

---

## What the automapper would show

The world, not the window. The game shows seven squares; the value the
automapper adds outdoors is the same one it adds in a dungeon — the shape of the
whole place, and where you have been.

* **One canvas, 40 x 32**, the three files stitched at world `x` 15 and 28, with
  the party marked at (`$49C3` + 13 x k, `$49C4`). The seams should not be
  visible; the player has no idea there are three files.
* **Terrain drawn only where the party has been**, exactly as `Exploration`
  does for a `GEO`. The whole world is sitting on the disk and drawing it
  unvisited would hand the player the map the game sells in its box.
* **Passable and impassable**, from the owning map's own table — so the
  Stojanow shows solid until `$4AB3` says otherwise and then opens, which is a
  thing the game itself never tells you.
* **Sites named where their flag says they are found**: Buccaneer Base, the
  Zhentil outpost, the Cave of Diogenes, the nomad camp, Yarash's pyramid, the
  lizardman keep, the kobold caves, the three ways into Phlan, the two boats.
  Hidden ones drawn as plain terrain, because that is literally what the game
  paints there.
* **Eight-way movement**, so the facing marker needs eight positions, not four.
* **Which disk the next area wants** — `$6E12` is the `POOL` number and is
  CONFIRMED on eight transitions. A line saying "Buccaneer Base — disk 6" is
  free and is the single most irritating thing about playing this game.
* **The cave**, when `$4A9E` is 255, is an ordinary `GEO` and the existing area
  map draws it with no new code at all. Only the label changes.

The commissions panel already reads plot flags out of `SAVEDGAME0`; the site
labels want the same five bytes (`$4A8C`, `$4A9F`, `$4AA0`, `$4AA1`, `$4AB3`),
so there is no new transport.

---

## The saves to take

**This is the part to hand Donald.** He gets outdoors once; an afternoon of play
in this order produces every specimen the work needs. Every one of them is a
`SAVEDGAME0` on a fresh save disk, labelled.

Reaching the wilderness at all: from civilised Phlan, take the boat east
(`ECL00` offers it once the harbour master has sold you one, `$4AC4`), or leave
by a city gate. The first travel square is on map `1A`, near world (24-26,
26-28).

| # | when | why it is needed |
|---|---|---|
| **W1** | **The first step onto the travel grid**, before moving | the baseline. `$49C3`/`$49C4`, `$49E6`, `$4A9E`, `$49FB`, `$4BC0`-`$4BD8`. Settles unknowns 1, 4 and whether saving outdoors is possible at all |
| **W2** | One step later, in a known direction | proves `$49C3`/`$49C4` step, and pins the eight-way encoding. With W1 it also gives the clock delta — unknown 5 |
| **W3** | Same square as W2, **turned to face a different way** | is the travel facing in the save at all, and if so where — unknown 3 |
| **W4** | Standing on the **east edge of map `1A`** (`$49C3` = 15), before crossing | the seam, from the west side |
| **W5** | One step east of W4, i.e. the **first square of map `1B`** | should read `$49C3` = 3 and `$4BC4` = `06`. Confirms the +13 offset against live data, not arithmetic |
| **W6** | On the **west edge of map `1A`** (`$49C3` = 2) and again after crossing to map `19` | the other seam; should read `$49C3` = 14, `$4BC4` = `04` |
| **W7** | **Beside the kobold caves at map `1B` (6,15)** — before entering, after the "TWO CAVES" message | `$4AA0` bit 1 flips here. Pairs with `npc_party.d64` on the same square, which is the only prior specimen |
| **W8** | **Inside a random "small dark cave"** (`$4A9E` = 255) | the only way to see the switched state: `$49E6` = 1, `$49FB` = 255, `$4BC2` = `19`/`1A`/`1B`, and `$49C3`/`$49C4` preserved underneath |
| **W9** | Back on the grid immediately after leaving that cave | proves the travel position survives an excursion, which is the whole reason for the second coordinate pair |
| **W10** | **Before and after clearing the Stojanow pollution** (`$4AB3` reaching 254), both taken on the travel grid near world (19,16) | the terrain-table swap, the only known case of the world changing shape |
| **W11** | Outside **Buccaneer Base** before and after taking the Bivant commission (`$4A8C`) | the hide/reveal stamp — checks that the map really is rebuilt from flags |
| **W12** | Anywhere outdoors, **during a wilderness random encounter** | if the game can be saved there at all; hands the encounter work its own specimen |

**Two live captures are worth more than any of these** and cost one session:

* **`$8C00`-`$8E87`, 648 bytes, while standing on the travel grid.** Compare
  byte for byte with `SQRDATA0n`. This is unknown 1 and it is the keystone.
* **`$0600`-`$0613` and `$035F`, `$033D`, `$00FB`, `$00FC` while taking one
  step.** Confirms the descriptor is live and that `$035F` really is the
  terrain code under the party's foot.

A screenshot of the travel screen, and one of the same screen inside a cave,
answers unknown 2 on its own.

---

## The work, in order

1. **Fix the stride** in `automap/combat.py` — `$0612 + 1`, not `$0607` — and
   the note in `docs/101-combat-view.md`. Cheap, and everything downstream
   depends on it.
2. **`por/world.py`**, transport-free, promoted out of `work/analysis9/wild.py`:
   read `SQRDATA0n` off a disk, expose the 18 x 36 grid and the 120 glyph
   entries, stitch the three at 13, carry the site tables and the two terrain
   tables, and answer `passable(map, x, y)` and `site_at(world_x, y)`. It needs
   no emulator and can be tested against the disks today, the way
   `tests/gamedata.py` already reads `GEO04`.
3. **Tests from the disks**, no fixtures: the overlap counts (179/180,
   180/180), the size identity 648 + 120 x 18 = 2808, the site tables' lengths
   against the gaps between their addresses, and the kobold caves landing on
   (6,15) — which `npc_party.d64` independently corroborates.
4. **Detect the state.** `(ECL & $7F) in {$19, $1A, $1B}` says the party is on
   a travel map; `$4A9E` says grid or cave; `$4BC4 & $7F` says which
   `SQRDATA`. Add it to `por/savegame.py` beside `.area`, and to the automapper
   as a third mode alongside area and combat.
5. **Take W1 and the two live captures.** Stop here until they exist. Steps 6
   onward are drawing, and drawing the wrong map is worse than drawing none.
6. **The canvas.** A third page in the automapper's `QStackedWidget`, since
   only one of area / combat / world is ever true. Reuse `Exploration` for the
   visited set — its keys are already `(x, y)` and world coordinates are the
   natural ones to store.
7. **Site labels** from the five plot flags, and the disk number from `$6E12`'s
   table.
8. **The river.** Re-read `passable()` when `$4AB3` crosses 254 and redraw.
   This is the one place the map changes under the player, and getting it right
   is what makes the panel worth more than a scan of the cluebook.

## What not to do

* **Do not draw the unvisited world.** It is all on the disk; showing it is
  giving away the game.
* **Do not read a terrain code against another map's table.** `2E` is walkable
  mountain on map `19` and solid on map `1B`.
* **Do not reuse `GEO` passability logic.** There are no walls, no doors and no
  per-square attribute byte out here — one byte, one terrain, one lookup.
* **Do not assume the site tables are complete.** Map `1B` reserves a stamp at
  (7,23) for a site that does not exist and a flag bit that is never set.
