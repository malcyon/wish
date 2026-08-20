#!/usr/bin/env python3
"""Generate docs/88-map-files.md from the GEO files on the game disks.

Needs a set of game disks. Point POR_DISKS at them, or pass a directory.
"""

import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from por.geo import (DIRECTIONS, GRID, LOCKED, SOLID, WIZARD_LOCKED,  # noqa: E402
                     Geo, load_geo_files)

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "88-map-files.md")

HEADER = """# The `GEO` map files

**Generated** by `tools/genmaps.py` — do not edit. Decoded in
[GEO is solved](50-experiments.md); the reader is `por/geo.py` and
`tools/geomap.py` renders them.

Four 256-byte planes over a 16×16 grid, indexed `x + (y << 4)` — row-major, y
southward, origin top-left.

| Plane | Offset | Content |
|---|---|---|
| 0 | `$000` | high nibble = wall art **north**, low nibble = **east** |
| 1 | `$100` | high nibble = wall art **south**, low nibble = **west** |
| 2 | `$200` | square attributes; bit 7 = roofed / indoor, bits 0-6 unread |
| 3 | `$300` | passability, two bits per direction: N = 0-1, E = 2-3, S = 4-5, W = 6-7 |

A wall nibble of 0 means no wall; otherwise `wallset = (v-1)/5` and
`slice = (v-1)%5` index `WALLDEF`. The passability field is **only consulted
where there is wall art**, so a wall and a barrier are independent:

| value | meaning |
|---|---|
| 0 | solid |
| 1 | passable — an opening or an open door |
| 2 | locked door |
| 3 | wizard-locked door |

## Inventory

`walls` counts edges carrying art, `doors` those a party can cross, `indoor` the
squares with attribute bit 7 set. `reciprocity` is how many of the 480 shared
edges the two adjacent squares agree about — a parse error shows up here first.

"""

FOOTER = """
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

**Which map a save is on is not yet located** -- but it must be recorded
somewhere, because loading a save puts the party back in the right place. An
earlier claim that no such field exists has been withdrawn: the scan behind it
compared our saves against each other, and every save we hold is in New Phlan,
so it had no negative example to work against.
"""


def main() -> int:
    disks = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "POR_DISKS", "/home/donald/c64/Pool of Radiance Disks")
    found: dict[str, Geo] = {}
    for path in sorted(glob.glob(os.path.join(disks, "POOL*.D64"))):
        for name, geo in load_geo_files(path).items():
            found.setdefault(name, geo)
    if not found:
        print(f"no GEO files under {disks}", file=sys.stderr)
        return 1

    rows = ["| file | walls | doors | locked | indoor | reciprocity |",
            "|---|---|---|---|---|---|"]
    for name, geo in sorted(found.items()):
        walls = doors = locked = indoor = 0
        for y in range(GRID):
            for x in range(GRID):
                indoor += geo.is_indoor(x, y)
                for d in DIRECTIONS:
                    if geo.wall(x, y, d):
                        walls += 1
                        b = geo.barrier(x, y, d)
                        doors += b != SOLID
                        locked += b in (LOCKED, WIZARD_LOCKED)
        agree, total = geo.reciprocity()
        rows.append(f"| `{name}` | {walls} | {doors} | {locked} | "
                    f"{indoor}/256 | {agree}/{total} |")

    with open(OUT, "w") as fh:
        fh.write(HEADER + "\n".join(rows) + "\n" + FOOTER)
    print(f"{len(found)} maps -> {os.path.normpath(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
