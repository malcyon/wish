#!/usr/bin/env python3
"""Every read of $6DE2, $6DE3 and $6DE6 in Pool of Radiance's POST.COM, with the branch each one gates, for `#445 (The game's third fight outcome, THE PARTY RUNS AWAY, has never been seen on a screen)`.

    .venv/bin/python tools/areas/postcom6dereads.py

The engine side of ECL00's tavern-brawl writes: finds `POST.COM` on the
player's C64 disks (`automap.paths.find_disks()`, so `$POR_DISKS` or the usual
places) with `tools/fleedrive.py`'s `overlay`, searches it for the
little-endian address bytes of $6DE2, $6DE3, $6DE6, $6DC6 and $6DE1, and
prints eight 6502 instructions from each referencing opcode with
`tools/c64/d6502.py`.  Reads the disks and writes nothing.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from tools import fleedrive as F  # noqa: E402
from tools.c64 import d6502  # noqa: E402


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    found = find_disks()
    if found is None:
        raise SystemExit("no Pool of Radiance disks found; set $POR_DISKS")
    root = str(found)
    disk, declared, body = F.overlay("POST.COM", root)
    base = F.DERIVED_BASE if hasattr(F, "DERIVED_BASE") else 0x0800
    print(f"POST.COM on {disk}: header says ${declared:04X}, "
          f"read at ${base:04X}, {len(body)} bytes")

    for addr in (0x6DE2, 0x6DE3, 0x6DE6, 0x6DC6, 0x6DE1):
        pat = bytes((addr & 0xFF, addr >> 8))
        i = body.find(pat)
        while i >= 0:
            op = body[i - 1]
            at = base + i - 1
            print(f"\n  ${addr:04X} referenced by the opcode at ${at:04X} "
                  f"(${op:02X}):")
            for line in d6502.lines(body, base, at, 8):
                print(f"    {line}")
            i = body.find(pat, i + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
