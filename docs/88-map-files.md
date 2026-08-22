# The `GEO` map files

**Generated** by `tools/genmaps.py` — do not edit. Decoded in
[GEO is solved](50-experiments.md); the reader is `por/geo.py` and
`tools/geomap.py` renders them.

Four 256-byte planes over a 16×16 grid, indexed `x + (y << 4)` — row-major, y
southward, origin top-left.

| Plane | Offset | Content |
|---|---|---|
| 0 | `$000` | high nibble = wall art **north**, low nibble = **east** |
| 1 | `$100` | high nibble = wall art **south**, low nibble = **west** |
| 2 | `$200` | square attributes; bit 7 = roofed / indoor, the rest a **script id** |
| 3 | `$300` | passability, two bits per direction: N = 0-1, E = 2-3, S = 4-5, W = 6-7 |

A wall nibble of 0 means no wall; otherwise `wallset = (v-1)/5` and
`slice = (v-1)%5` index `WALLDEF`. The passability field is **only consulted
where there is wall art**, so a wall and a barrier are independent:

| value | meaning |
|---|---|
| 0 | solid |
| 1 | passable — an opening or an open door |
| 2 | locked door |
| 3 | barred door — locked and unpickable, bashed against a tougher table |

`por/geo.py` still spells value 3 `WIZARD_LOCKED`, and that name is ours alone:
the Gold Box guide calls it a "hard-to-open barred door" and
`GB_GEO.hexpat` "locked, unpickable". Neither connects it to the spell. See
[the community formats](128-guide-and-scripting.md).

**The script id.** Plane 2's low bits are a per-square id into the area's own
ECL jump table — `AND <mask>, ATTR, [v]` then `ONGOTO idx=[v]` — so stepping on
the square runs a script. The mask is the area's, not a constant: eighteen
scripts mask `$7F`, `ECL17` masks `$3F`, and the dungeon-floor family masks
`$1F` and uses the two bits that frees for wandering monsters (bit 6 suppresses
an encounter, bit 5 halves the rate). `Geo.script_id` takes the mask as an
argument for that reason.

## Inventory

`walls` counts edges carrying art, `doors` those a party can cross, `indoor` the
squares with attribute bit 7 set. `reciprocity` is how many of the 480 shared
edges the two adjacent squares agree about — a parse error shows up here first.

| file | walls | doors | locked | indoor | reciprocity |
|---|---|---|---|---|---|
| `GEO00` | 482 | 121 | 0 | 82/256 | 480/480 |
| `GEO01` | 338 | 49 | 17 | 47/256 | 478/480 |
| `GEO02` | 566 | 182 | 19 | 107/256 | 476/480 |
| `GEO03` | 482 | 75 | 2 | 76/256 | 475/480 |
| `GEO04` | 444 | 54 | 1 | 57/256 | 479/480 |
| `GEO05` | 467 | 62 | 2 | 77/256 | 478/480 |
| `GEO06` | 446 | 62 | 0 | 60/256 | 480/480 |
| `GEO07` | 116 | 19 | 1 | 76/256 | 472/480 |
| `GEO09` | 442 | 82 | 29 | 111/256 | 451/480 |
| `GEO0A` | 580 | 303 | 1 | 49/256 | 474/480 |
| `GEO0D` | 527 | 109 | 3 | 256/256 | 473/480 |
| `GEO0E` | 426 | 88 | 47 | 170/256 | 479/480 |
| `GEO0F` | 444 | 102 | 6 | 127/256 | 478/480 |
| `GEO10` | 488 | 336 | 0 | 0/256 | 480/480 |
| `GEO11` | 377 | 222 | 0 | 13/256 | 480/480 |
| `GEO12` | 426 | 121 | 2 | 120/256 | 477/480 |
| `GEO14` | 522 | 117 | 11 | 157/256 | 469/480 |
| `GEO15` | 434 | 73 | 0 | 72/256 | 459/480 |
| `GEO16` | 599 | 141 | 0 | 256/256 | 479/480 |
| `GEO17` | 388 | 22 | 1 | 256/256 | 479/480 |
| `GEO18` | 419 | 58 | 0 | 166/256 | 480/480 |
| `GEO19` | 550 | 0 | 0 | 255/256 | 480/480 |
| `GEO1A` | 404 | 250 | 0 | 10/256 | 461/480 |
| `GEO1B` | 506 | 0 | 0 | 256/256 | 480/480 |
| `GEO1C` | 436 | 81 | 0 | 105/256 | 477/480 |
| `GEO1D` | 480 | 159 | 0 | 61/256 | 479/480 |
| `GEO1E` | 270 | 10 | 0 | 183/256 | 480/480 |
| `GEO1F` | 426 | 90 | 0 | 168/256 | 480/480 |
| `GEO20` | 313 | 30 | 0 | 92/256 | 480/480 |

**Reading the table.** `indoor` separates dungeons from city blocks at a glance:
a file at 256/256 is entirely under a roof, one at 0/256 entirely open. Phlan has
nine city blocks and the game has dungeons besides, which is roughly the shape of
the 29.

## The nine Phlan city blocks

CONFIRMED by matching every file against a transcription of the fan-drawn NES
block maps: nine blocks, nine files, each a mutual best match, with nothing else
in the matrix scoring above 0.316. See
[every Phlan city block, matched](50-experiments.md).

| Block | File | φ | Disk |
|---|---|---|---|
| Slums | `GEO14` | 0.992 | POOL2 |
| Stojanow Gate | `GEO09` | 0.965 | POOL2 |
| Podol Plaza | `GEO12` | 0.924 | POOL1 |
| Sokol Keep | `GEO15` | 0.912 | POOL4 |
| Kuto's Well Catacombs | `GEO20` | 0.869 | POOL8 |
| Cadorna Textile House | `GEO02` | 0.818 | POOL4 |
| Mendor's Library | `GEO0F` | 0.768 | POOL2 |
| Kuto's Well | `GEO1D` | 0.762 | POOL8 |
| New Phlan | `GEO00` | 0.733 | POOL3 |

`GEO19` and `GEO1B` are PROBABLE dungeon mazes — fully roofed, no doors at all.
`GEO10` and `GEO11` are PROBABLE wilderness — barely roofed, hundreds of
walk-through edges.

**Which map a save is on is `$4BC2`**, the `GEO` file number, inside the
loader's "what is currently loaded" cache at `$4BC0`-`$4BD8`. Bit 7 is a reload
marker and must be masked off. `por/savegame.py` exposes it as `SaveGame0.area`
and `.area_file`.
