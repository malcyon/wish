#!/usr/bin/env python3
"""The loader's own twenty-five file slots, read out of `LIBRARY`.

    tools/libslots.py

Prints the table `docs/140-loaded-files-cache.md` carries, off the disks
rather than from memory of it: for each of the twenty-five slots, the
filename stem the slot index picks, the address a file in it loads at, and
whether the overwrite scan is allowed to mark it dirty.

Nothing is hardcoded but the addresses. `LIBRARY` loads at `$2C48` and holds
four tables indexed by slot -- `$41BE`/`$41D7` the load address low and high,
`$41F0` the overwrite-scan flag, `$4209` the stem number -- and the stems
themselves are counted strings at `$4196`/`$41AA` with their lengths at
`$4182`. Every one of those is `docs/140-loaded-files-cache.md`'s, CONFIRMED
there.

The `$41F0` column is the one that is hard to get any other way. `$00` exempts
a slot from the scan that marks a slot dirty when another load has overwritten
its memory -- the three `WALLDEF` slots, which live in the staging buffer --
and that exemption is the mechanism behind
`#179 (Warping out of Valhingen Graveyard or Valjevo Castle leaves two wall
pieces unrelocated)`.

A stem comes back with a `00` on the end -- the stored string carries the
two hex digits as a placeholder and the loader overwrites them with the file
number the slot holds, which is why slot 2 holding `$14` means `GEO14`.

The stem numbers are not the slot numbers, and that is the reason to read them
rather than write them down: `WALLSET` is stem 11 across slots 15-17,
`WALLDEF` stem 12 across 18-20, and `ANIMATE` is stem 13 at slot 11.

Needs a set of disks: `$POR_DISKS`, or `automap.paths.find_disks()`.
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from automap.paths import find_disks  # noqa: E402
from goldbox.d64 import D64  # noqa: E402

#: `LIBRARY`'s load address, so a run address becomes an offset in the file.
BASE = 0x2C48

SLOTS = 25

#: The four per-slot tables, and the stem string tables behind `$4209`.
LOAD_LO, LOAD_HI, SCAN, STEM_OF = 0x41BE, 0x41D7, 0x41F0, 0x4209
STEM_LEN, STEM_PTR_LO, STEM_PTR_HI = 0x4182, 0x4196, 0x41AA


def read_library(disks: pathlib.Path) -> bytes:
    """`LIBRARY` off whichever side carries it, header word stripped."""
    for path in sorted(disks.glob("POOL*.[dD]64")):
        img = D64.open(path)
        for entry in img.iter_directory():
            if entry.name.decode("latin1").rstrip("\xa0 ") == "LIBRARY":
                return img.read_file("LIBRARY")[2:]
    raise SystemExit(f"no LIBRARY on any disk in {disks}")


def stems(body: bytes) -> list[str]:
    """The stem strings, in stem-number order, read out of the file."""

    def at(addr: int, n: int) -> bytes:
        return body[addr - BASE:addr - BASE + n]

    lengths = at(STEM_LEN, SLOTS)
    lo, hi = at(STEM_PTR_LO, SLOTS), at(STEM_PTR_HI, SLOTS)
    out = []
    for i in range(SLOTS):
        addr = lo[i] | (hi[i] << 8)
        if not (BASE <= addr < BASE + len(body)) or not 0 < lengths[i] <= 16:
            out.append("")
            continue
        out.append(at(addr, lengths[i]).decode("latin1"))
    return out


def main() -> int:
    disks = pathlib.Path(os.environ.get("POR_DISKS") or (find_disks() or ""))
    if not disks.is_dir():
        raise SystemExit("no game disks: set $POR_DISKS")
    body = read_library(disks)

    def at(addr: int, n: int) -> bytes:
        return body[addr - BASE:addr - BASE + n]

    lo, hi = at(LOAD_LO, SLOTS), at(LOAD_HI, SLOTS)
    scan, stem_of, names = at(SCAN, SLOTS), at(STEM_OF, SLOTS), stems(body)

    print(f"{'slot':>4} {'stem':<10} {'loads at':<9} {'$41F0':<6} "
          f"{'stem #':>6}  the overwrite scan")
    for i in range(SLOTS):
        flag = scan[i]
        says = ("exempt -- the scan may not mark it" if flag == 0x00 else
                "end of table" if flag & 0x80 else "may mark it dirty")
        n = stem_of[i]
        name = names[n] if n < len(names) else "?"
        print(f"{i:>4} {name:<10} ${hi[i]:02X}{lo[i]:02X}     ${flag:02X}   "
              f"{n:>6}  {says}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
