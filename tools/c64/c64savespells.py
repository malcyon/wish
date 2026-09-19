#!/usr/bin/env python3
"""Per-character levels, experience, hit points and spell bytes on named Pool
of Radiance save disks.

Written for `#142 (The party effects line is computed every poll and shown
nowhere)`, as the detail view after `tools/c64/c64savescan.py` had listed which
disks hold a cleric: for each named image, the saved-game area file and every
occupied slot's name, level, cleric and magic-user levels, experience,
`hp_max` and the raw `spells_memorised` and `spells_castable` bytes as hex.
A field the record cannot read prints as `<ErrorName>`.

The disks default to the five `#142` compared (`NEWSAVE6`, `NEWSAVE5`,
`NEWSAVE3`, `PORSAVE13`, `PORSAVE14`); pass others as `NAME.D64` arguments.
They are looked for in `--disks`, else in the folder `automap/gamedisks.py`
finds for `pool-of-radiance` (`$POR_DISKS` wins). Reads only.

    .venv/bin/python -m tools.c64.c64savespells [NAME.D64 ...]
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import gamedisks  # noqa: E402
from goldbox.d64 import D64, load_payload  # noqa: E402
from goldbox.savegame import SaveGame0  # noqa: E402

DEFAULT_DISKS = ("NEWSAVE6.D64", "NEWSAVE5.D64", "NEWSAVE3.D64",
                 "PORSAVE13.D64", "PORSAVE14.D64")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", metavar="NAME.D64",
                    help="images to list (default: the five #142 compared)")
    ap.add_argument("--disks", type=pathlib.Path,
                    help="folder of Pool of Radiance C64 images (default: "
                         "automap/gamedisks.py's pool-of-radiance)")
    args = ap.parse_args(argv)

    folder = args.disks or gamedisks.find("pool-of-radiance")
    if folder is None:
        print("No Pool of Radiance disks. Set $POR_DISKS or pass --disks.",
              file=sys.stderr)
        return 2
    folder = pathlib.Path(folder)

    for nm in args.names or DEFAULT_DISKS:
        p = folder / nm
        sg = SaveGame0.from_bytes(load_payload(D64(p.read_bytes()),
                                               "SAVEDGAME0"))
        print("==", nm, sg.area_file)
        for s in sg.characters:
            r = s.record
            if r is None:
                continue

            def g(f):
                try:
                    return r.get(f)
                except Exception as e:
                    return f"<{type(e).__name__}>"
            mem = g("spells_memorised")
            cast = g("spells_castable")
            print(f"  slot{s.index} {g('name'):16s} lvl {g('level')} "
                  f"C{g('level_cleric')} MU{g('level_magic_user')} "
                  f"xp {g('experience')} hp {g('hp_max')} "
                  f"mem {bytes(mem).hex() if isinstance(mem, (bytes, bytearray)) else mem} "
                  f"castable {bytes(cast).hex() if isinstance(cast, (bytes, bytearray)) else cast}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
