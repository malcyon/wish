#!/usr/bin/env python3
"""Where a captured `$ED50` block still agrees with `WALLS00`, block by block.

    tools/wallsmap.py work/issue179/01-podol-control.walls.bin
    tools/wallsmap.py work/issue179/*.walls.bin

Reads the `<label>.walls.bin` captures `tools/wallpins.py` writes and prints
one character per 128 bytes: `#` where the whole block matches `WALLS00` as it
is on the disk, `+` where more than half of it does, `.` where it does not.
Underneath, a `^` marks each of the three addresses `DUNGEON $1485` unpacks a
`WALLDEF` piece to -- `$ED50`, `$F05C` and `$F368`, out of the tables at
`$14BF`/`$14C2`.

**This is the picture `cmp -l` cannot draw.** `$ED50` holds either the wall
renderer tables loaded from `WALLS00` (slot 9) or three `WALLDEF` pieces
unpacked over the top of them (slots 18-20), and the two cannot both be
resident -- so the question at an area change is never "did these bytes
change" but *which of the two* is there, and in which thirds. A run of `.`
starting at one of the `^` marks is a piece that was unpacked; a run of `#`
across a `^` is a piece that was not.

That is the reading behind
`#179 (Warping out of Valhingen Graveyard or Valjevo Castle leaves two wall
pieces unrelocated)`, where the party arrives with pieces 0 and 1 still
carrying the previous area's screen codes.

Needs a set of disks for `WALLS00`: `$POR_DISKS`, or
`automap.paths.find_disks()`.
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from automap.paths import find_disks  # noqa: E402
from goldbox.d64 import D64  # noqa: E402

#: Where slot 9 loads, and where a capture of it starts.
BASE = 0xED50

#: One character of the map. 128 bytes is fine enough to separate the three
#: unpack destinations and coarse enough that a whole capture fits a terminal.
BLOCK = 128

#: `DUNGEON $14BF`/`$14C2` -- where `$1485` unpacks the three `WALLDEF` pieces.
UNPACK = (0xED50, 0xF05C, 0xF368)


def walls00(disks: pathlib.Path) -> bytes:
    """`WALLS00` off whichever side carries it, header word stripped."""
    for path in sorted(disks.glob("POOL*.[dD]64")):
        img = D64.open(path)
        for entry in img.iter_directory():
            if entry.name.decode("latin1").rstrip("\xa0 ") == "WALLS00":
                return img.read_file("WALLS00")[2:]
    raise SystemExit(f"no WALLS00 on any disk in {disks}")


def row(blob: bytes, walls: bytes) -> tuple[str, int, int]:
    """One character per `BLOCK` bytes, and the whole-capture agreement."""
    n = min(len(walls), len(blob))
    out = []
    for i in range(0, n, BLOCK):
        a, b = blob[i:i + BLOCK], walls[i:i + BLOCK]
        same = sum(x == y for x, y in zip(a, b))
        out.append("#" if same == len(b) else "+" if same * 2 > len(b) else ".")
    return "".join(out), sum(x == y for x, y in zip(blob, walls)), n


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit(__doc__)
    disks = pathlib.Path(os.environ.get("POR_DISKS") or (find_disks() or ""))
    if not disks.is_dir():
        raise SystemExit("no game disks: set $POR_DISKS")
    walls = walls00(disks)

    width = 0
    for path in argv:
        blob = pathlib.Path(path).read_bytes()
        marks, same, n = row(blob, walls)
        width = max(width, len(marks))
        print(pathlib.Path(path).name)
        print(f"  ${BASE:04X} {marks} ${BASE + n:04X}   {same}/{n} bytes agree")

    legend = [" "] * width
    for addr in UNPACK:
        i = (addr - BASE) // BLOCK
        if i < width:
            legend[i] = "^"
    print(f"  {' ' * 5} {''.join(legend)}   "
          f"^ = a WALLDEF piece unpacks here")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
