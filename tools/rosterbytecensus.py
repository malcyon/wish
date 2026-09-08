#!/usr/bin/env python3
"""Census one byte of the C64 roster block across every save disk to hand.

`SAVEDGAME1` keeps a 32-byte block per roster slot, and `goldbox/savegame.py`
names its offsets -- `ROSTER_IN_USE` at +0x00, `ROSTER_COMBAT_SIDE` at +0x0C,
`ROSTER_SLOT_INDEX` at +0x0D, and several with no established meaning at all
(`#365 (Three roster bytes have no established meaning, and a C64 party
converted to DOS is told so with no way to check it)`).  A reading of one of
them is worth what its sample size says it is, and this counts the sample.

    tools/rosterbytecensus.py 0x0D
    tools/rosterbytecensus.py 0x0D --equals-slot
    tools/rosterbytecensus.py 0x03 --disks /path/to/some/disks

`--equals-slot` asks the one question a slot-index candidate needs answering:
in how many occupied slots does the byte equal the index of the slot it sits
in, and where does it not.  Without it the output is a histogram of the values
seen, which is what an unattributed byte wants first.

The disks are read only, never written.  `$POR_DISKS` then
`automap.paths.find_disks()` says where they are, the way every other tool
here finds them.
"""
from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402


def disks_root(given: str | None) -> pathlib.Path:
    if given:
        return pathlib.Path(given)
    if os.environ.get("POR_DISKS"):
        return pathlib.Path(os.environ["POR_DISKS"])
    from automap.paths import find_disks
    return pathlib.Path(find_disks())


def census(root: pathlib.Path, offset: int):
    """`(rows, skipped)`: one row per occupied slot, and the images that had
    no readable save on them."""
    rows = []
    skipped = []
    for path in sorted(root.glob("*.[Dd]64")):
        try:
            img = D64.open(str(path))
            _game, sg0, sg1 = load_save(img)
        except Exception as why:                     # not a save disk
            skipped.append((path.name, str(why).split("\n")[0]))
            continue
        if sg1 is None:
            skipped.append((path.name, "no SAVEDGAME1 on this image"))
            continue
        for slot in sg0.slots:
            if not slot.occupied:
                continue
            block = sg1.roster(slot.index)
            rows.append((path.name, slot.record.name, slot.index,
                         block.raw[offset]))
    return rows, skipped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("offset", help="roster-block offset, e.g. 0x0D or 13")
    ap.add_argument("--disks", help="where the .d64 images are")
    ap.add_argument("--equals-slot", action="store_true",
                    help="count agreement with the slot index instead of "
                         "printing a histogram")
    args = ap.parse_args(argv)

    offset = int(args.offset, 0)
    if not 0 <= offset < 0x20:
        ap.error(f"a roster block is 32 bytes; {offset:#04x} is outside it")

    root = disks_root(args.disks)
    rows, skipped = census(root, offset)
    print(f"{root}: {len(rows)} occupied roster slots, "
          f"{len(skipped)} image(s) with no save to read")

    if args.equals_slot:
        agree = [r for r in rows if r[3] == r[2]]
        print(f"+{offset:#04x} == the slot index in {len(agree)} of "
              f"{len(rows)}")
        for name, who, index, value in rows:
            if value != index:
                print(f"  {name} slot {index} {who}: {value}")
    else:
        counts = collections.Counter(r[3] for r in rows)
        for value, n in sorted(counts.items()):
            print(f"  {value:#04x} ({value:3d}): {n}")

    for name, why in skipped:
        print(f"  skipped {name}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
