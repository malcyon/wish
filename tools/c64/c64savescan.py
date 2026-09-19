#!/usr/bin/env python3
"""Which characters, at which class levels, does every `*.D64` in the Pool of
Radiance disks folder hold in its `SAVEDGAME0`?

Written for `#142 (The party effects line is computed every poll and shown
nowhere)`, which needed a cleric who can reach a radius spell and wanted to
know whether any party on the machine already had one: one line per image, the
saved-game area file and each occupied slot as `NAME(Cn/MUn/Fn)`. An image
that is not a save disk, or has no `SAVEDGAME0`, prints its error instead.
`tools/c64/livelevel.py` is what raises a level once it is known none does, and
`tools/c64/c64savespells.py` is the per-character detail for named disks.

The folder is `--disks`, else the one `automap/gamedisks.py` finds for
`pool-of-radiance` (`$POR_DISKS` wins). Reads only.

    .venv/bin/python -m tools.c64.c64savescan
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import gamedisks  # noqa: E402
from goldbox.d64 import D64, load_payload  # noqa: E402
from goldbox.savegame import SaveGame0  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--disks", type=pathlib.Path,
                    help="folder of Pool of Radiance C64 images (default: "
                         "automap/gamedisks.py's pool-of-radiance)")
    args = ap.parse_args(argv)

    folder = args.disks or gamedisks.find("pool-of-radiance")
    if folder is None:
        print("No Pool of Radiance disks. Set $POR_DISKS or pass --disks.",
              file=sys.stderr)
        return 2

    for p in sorted(pathlib.Path(folder).glob("*.D64")):
        try:
            d = D64(p.read_bytes())
            sg = SaveGame0.from_bytes(load_payload(d, "SAVEDGAME0"))
        except Exception as e:
            print(f"{p.name:16s} -- {type(e).__name__}: {e}")
            continue
        who = []
        for s in sg.characters:
            r = s.record
            if r is None:
                continue

            def g(f):
                try:
                    return r.get(f)
                except Exception:
                    return None
            who.append(f"{g('name')}(C{g('level_cleric')}"
                       f"/MU{g('level_magic_user')}/F{g('level_fighter')})")
        print(f"{p.name:16s} {sg.area_file} {' '.join(who)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
