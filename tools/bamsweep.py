#!/usr/bin/env python3
"""Check the BAM header of every disk image against the layout we documented.

    tools/bamsweep.py                       every disk under $POR_DISKS
    tools/bamsweep.py /path/to/images       every .d64 in a directory
    tools/bamsweep.py A.D64 B.D64           named images
    tools/bamsweep.py --quiet               the tallies only

Track 18 sector 0 is the BAM, and its last 112 bytes are the disk header: name,
id, DOS type and filler. The 1541 User's Guide, September 1982, prints that
table on p. 66 with two byte ranges that cannot both be right -- "166-167" for
the shifted spaces after the `2A`, which overlaps byte 166 with the `2A`
itself, and "177-255" for the nulls, which leaves 168-176 undescribed. This
sweep is what says which reading the drive actually wrote, by counting disks
rather than arguing: on the player's own images the spaces are bytes 167-170
and the nulls run from 171.

It re-takes the count in `docs/10-disk-format.md` ("The BAM -- track 18 sector
0"), so a new disk that disagrees shows up as a disk rather than as a doubt.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from automap.paths import find_disks  # noqa: E402
from goldbox.d64 import D64  # noqa: E402

#: The fixed-value parts of the header as `docs/10-disk-format.md` gives them:
#: (label, first byte, last byte, expected bytes). The name at 144-159 and the
#: id at 162-163 are the disk's own and are reported rather than checked.
FIXED = (
    ("pad", 160, 161, b"\xa0\xa0"),
    ("pad", 164, 164, b"\xa0"),
    ("dos", 165, 166, b"2A"),
    ("pad", 167, 170, b"\xa0" * 4),
    ("nulls", 171, 255, bytes(85)),
)


def images(args: list[str]) -> list[str]:
    """Every image named, or found under a directory, or on the player's disks."""
    if not args:
        root = os.environ.get("POR_DISKS") or str(find_disks() or "")
        args = [root] if root else []
    out: dict[str, str] = {}
    for arg in args:
        found = (sorted(glob.glob(os.path.join(arg, "*.[Dd]64")))
                 if os.path.isdir(arg) else [arg])
        for path in found:
            out.setdefault(os.path.normcase(os.path.abspath(path)), path)
    return sorted(out.values(), key=lambda p: os.path.basename(p).upper())


def header(path: str) -> bytes:
    """Bytes 144-255 of track 18 sector 0, which is the whole disk header."""
    return D64.open(path).read_sector(18, 0)[144:]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*", help="images, or directories of them")
    ap.add_argument("--quiet", action="store_true", help="tallies only")
    opts = ap.parse_args(argv)

    paths = images(opts.paths)
    if not paths:
        print("no disk images found; pass a path or set POR_DISKS",
              file=sys.stderr)
        return 2

    agree = {(first, last): 0 for _, first, last, _ in FIXED}
    read = 0
    for path in paths:
        try:
            head = header(path)
        except Exception as exc:                    # unreadable or an odd size
            print(f"{os.path.basename(path):16s} unreadable: {exc}")
            continue
        read += 1
        odd = []
        for _, first, last, want in FIXED:
            got = head[first - 144:last - 143]
            if got == want:
                agree[first, last] += 1
            else:
                odd.append(f"{first}-{last} is {got.hex()}, not {want.hex()}")
        if not opts.quiet:
            name = head[0:16].rstrip(b"\xa0").decode("latin-1")
            print(f"{os.path.basename(path):16s} {name!r:20s} "
                  f"id={head[18:20].hex()}  "
                  + ("ok" if not odd else "; ".join(odd)))

    print(f"{read} of {len(paths)} images read")
    for label, first, last, want in FIXED:
        shown = want.hex() if len(want) <= 4 else f"{len(want)} nulls"
        print(f"  {first:3d}-{last:3d} {label:5s} == {shown:10s} "
              f"on {agree[first, last]} of {read}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
