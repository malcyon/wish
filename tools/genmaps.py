#!/usr/bin/env python3
"""Generate docs/88-map-files.md from the GEO files on the game disks.

Needs a set of game disks. Point POR_DISKS at them, or pass a directory.
"""

import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from automap.paths import disk_globs, find_disks  # noqa: E402
from goldbox.geo import (  # noqa: E402
    DIRECTIONS,
    GRID,
    LOCKED,
    SOLID,
    WIZARD_LOCKED,
    Geo,
    load_geo_files,
)

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "88-map-files.md")

HEADER = """# The `GEO` map files

**Generated** by `tools/genmaps.py` — do not edit. Decoded in
[GEO is solved](50-experiments.md); the reader is `goldbox/geo.py`, `tools/geomap.py`
renders them, and [`goldbox/areas.py`](../goldbox/areas.py) says which area loads which
file and what it is called.

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

`goldbox/geo.py` still spells value 3 `WIZARD_LOCKED`, and that name is ours alone:
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

"""

FOOTER = """
**Reading the table.** The counts are a parse check, not an identification. A
file at 256/256 is entirely under a roof and one at 0/256 entirely open, and it
is tempting to read that as dungeon against city block — but the two most
roofed, doorless files here, `GEO19` and `GEO1B`, are the **wilderness
windows**, areas 25 and 27, each drawn over its own `SQRDATA`; and the two least
roofed, `GEO10` and `GEO11`, are the **Lizardman Keep** and the **Nomad Camp**,
which are outdoor but not wilderness. Both pairs were guessed the other way
round from these columns alone. What a file *is* comes from the script that
loads it, and that table is `goldbox/areas.py`.

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

**Which map a save is on is `$4BC2`**, the `GEO` file number, in slot 2 of the
loader's twenty-five-slot "what is currently loaded" cache at `$4BC0`-`$4BD8`
— [the loaded-files cache](140-loaded-files-cache.md), which is where the other
twenty-four slots are. Bit 7 is a reload marker and must be masked off.
`goldbox/savegame.py` exposes it as `SaveGame0.area` and `.area_file`.
"""


def game_disks(root: str) -> list[str]:
    """Every game disk under `root`, each of them once.

    `disk_globs` gives an upper- and a lower-cased pattern, and on a
    case-insensitive filesystem both match the same file -- so dedupe, or every
    disk is read twice.
    """
    seen: dict[str, str] = {}
    for pattern in disk_globs():
        for path in glob.glob(os.path.join(root, pattern)):
            seen.setdefault(os.path.normcase(os.path.abspath(path)), path)
    return sorted(seen.values())


def main() -> int:
    disks = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "POR_DISKS", str(find_disks() or ""))
    found: dict[str, Geo] = {}
    for path in game_disks(disks):
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

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(HEADER + "\n".join(rows) + "\n" + FOOTER)
    print(f"{len(found)} maps -> {os.path.normpath(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
