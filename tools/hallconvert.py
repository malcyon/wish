#!/usr/bin/env python3
"""Convert a DOS save twice -- once keyed on `$49C5`, once on `$49F2` -- and
diff the two C64 save disks.

`#257 (A DOS save made in the training hall converts as though the party were
in New Phlan)` is the ticket.  `goldbox.dos_savegame.current_area` used to
read `$49C5` indoors and now reads `$49F2` always, and the question this
answers is what a player actually gets from each.  For every area that loads
its own map the two words hold the same number and the two disks are
identical; where they part -- the training hall and Phlan City Hall, whose
scripts contain no `LOADFILES` at all -- the difference is the whole defect.

    tools/hallconvert.py --folder ~/wish-specimens/por-dos/WISH-SPEC-... \
        --slot F --out work/issue257

The `geo` disk is built by monkeypatching `current_area` back to
``word(save, AREA)``, which is the expression this module carried before
`#257`.  That is deliberate: it reproduces the shipped defect from the
shipped code rather than from a hand-built file, so the disk can be booted
and the player's own experience of the bug read off the screen.  The
`script` disk is what the fixed reader builds, and it may legitimately
**refuse** -- a location `goldbox/areas.py` cannot name a map for is refused
rather than guessed at, which is the point.

The DOS folder is `--folder`, the C64 game disks are `$POR_DISKS` then
`automap.paths.find_disks()`, and both are read and never written.  Output
goes wherever `--out` says, which should be under `work/`.
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from goldbox import areas, dos  # noqa: E402
from goldbox import dos_savegame as sg  # noqa: E402
from tools import dosdisk  # noqa: E402

#: Where the player keeps the C64 game disks.  Read only.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: The two readers, by the word each keys on.  `geo` is what
#: `current_area` did before `#257` -- `$49F2` outdoors, `$49C5` indoors --
#: and `script` is what it does now.
READERS = {
    "geo": lambda save: (sg.word(save, sg.SCRIPT) if sg.outdoors(save)
                         else sg.word(save, sg.AREA)),
    "script": lambda save: sg.word(save, sg.SCRIPT),
}


def convert(folder: pathlib.Path, slot: str, disks: pathlib.Path,
            out: pathlib.Path, reader: str,
            borrow: str | None = None) -> tuple[int, str]:
    """Build one disk with one of the two readers.  Returns (area, note).

    `borrow` names the `GEO` a mapless area runs on -- `GEO00` for both of
    Pool of Radiance's, since `ECL00` is the only script that `NEWECL`s into
    either.  It is a **prototype of the fix, not the fix**: the shipped
    version of it would be a field on `goldbox.areas.Area`, and this patches
    `areas.area` for the length of one call so the resulting disk can be
    booted before anybody commits to a shape.
    """
    savgam = (folder / f"SAVGAM{slot}.DAT").read_bytes()
    there = READERS[reader](savgam)
    where = areas.area(there)
    name = where.name if where and where.name else f"area {there}"
    was, was_area = sg.current_area, areas.area_in
    sg.current_area = READERS[reader]
    if borrow and where is not None and not where.geos:
        lent = dataclasses.replace(where, geos=(borrow,))
        areas.area_in = (lambda id, title, _w=was_area:
                         lent if id == there else _w(id, title))
        name = f"{name} on {borrow}"
    try:
        dosdisk.build(folder, slot, disks, out)
    except dos.DosRecordError as e:
        return there, f"{name}: REFUSED -- {e}"
    finally:
        sg.current_area, areas.area_in = was, was_area
    return there, f"{name}: wrote {out}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--folder", required=True, help="the DOS save folder")
    p.add_argument("--slot", default="F", help="the DOS save slot letter")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the C64 game disks are; read only")
    p.add_argument("--out", required=True, help="a directory for the disks")
    p.add_argument("--borrow", default=None,
                   help="the GEO a mapless area runs on, e.g. GEO00; "
                        "prototypes the fix without touching goldbox/areas.py")
    args = p.parse_args(argv)

    folder = pathlib.Path(args.folder).expanduser()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    savgam = (folder / f"SAVGAM{args.slot}.DAT").read_bytes()
    print(f"$49C5 = {sg.word(savgam, sg.AREA)}  "
          f"$49F2 = {sg.word(savgam, sg.SCRIPT)}  "
          f"$49E6 = {sg.word(savgam, sg.INDOORS)}")
    for reader in READERS:
        area, note = convert(folder, args.slot, pathlib.Path(args.disks),
                             out / f"{reader}.d64", reader, args.borrow)
        print(f"  {reader:6s} -> {area:3d}  {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
