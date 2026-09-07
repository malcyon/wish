#!/usr/bin/env python3
"""Copy an Amiga Pool of Radiance save slot into another slot on the disk.

`goldbox.amiga.write_por_slot` writes a whole slot -- six characters, their
items and effects, the saved game pointed at those files, and `save/save`, the
ten-byte array the picker reads -- and until this there was no way to run it
outside the test suite.  It is what the emulator proof for
`#109 (A save slot written onto an Amiga disk is not offered by the game's
picker)` needs: a slot on a real disk written by our own code rather than by
hand, so the game can be asked whether it offers it.

    tools/porslot.py work/por1.adf --from A --to F --out work/por1-F.adf

The party is read back out of the disk through `goldbox.amiga.read_por_slot`
and `goldbox.dos.to_neutral`, so it goes through the same neutral record a
converted party would, and anything that cannot cross is reported rather than
dropped.

**The input disk is opened read-only and `--out` is required.** The player's
own disks are not written to; work on a copy.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import amiga, dos  # noqa: E402
from goldbox.amiga_adf import AmigaDisk  # noqa: E402


def read_slot(disk: AmigaDisk, slot: str):
    """The characters of one slot, as neutral records, and its saved game.

    Reads through `goldbox.amiga.read_por_slot`, which reads the `.sav`,
    `.itm` and `.spc` blocks straight off the disk -- nothing here is written
    to the host filesystem to read a slot.  `read_por_slot` answers
    `list[goldbox.dos.DosCharacter]`, so each one is turned neutral with
    `dos.to_neutral`.  Raises `amiga.AmigaRecordError` for a slot with no
    characters, and for one with characters and no saved game.
    """
    letter = slot.upper()
    characters, savegame = amiga.read_por_slot(disk, letter)
    return [dos.to_neutral(c) for c in characters], savegame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("disk", help="an Amiga Pool of Radiance disk 1 image")
    parser.add_argument("--from", dest="source", default="A",
                        help="the slot to copy the party out of (default A)")
    parser.add_argument("--to", dest="target", required=True,
                        help="the slot to write, one of A-J")
    parser.add_argument("--out", required=True,
                        help="where to write the result; the input is never "
                             "modified")
    args = parser.parse_args(argv)

    # "The input is never modified" is a promise in `--out`'s own help text,
    # and writing the result back over the source is the one way to break it.
    # The player keeps their disks somewhere this script is pointed at by
    # hand, so the mistake is a typo away.
    if pathlib.Path(args.out).resolve() == pathlib.Path(args.disk).resolve():
        raise SystemExit(
            f"--out is the input disk ({args.disk}); write somewhere else")

    disk = AmigaDisk.open(args.disk)
    print(f"Slot list before: "
          f"{disk.read_file(amiga.POR_SLOT_LIST)!r} "
          f"{amiga.read_slot_list(disk)}")

    try:
        neutral, savegame = read_slot(disk, args.source)
    except amiga.AmigaRecordError as ex:
        raise SystemExit(str(ex)) from None
    for record in neutral:
        for line in list(record.warnings) + list(record.dropped):
            print(f"  {record.get('name')}: {line}")
    print(f"Read {len(neutral)} characters from slot {args.source.upper()}: "
          f"{', '.join(c.get('name') for c in neutral)}")

    written = amiga.write_por_slot(disk, args.target, neutral, savegame)
    print(f"Wrote {len(written)} files:")
    for path in written:
        print(f"  {path}")
    print(f"Slot list after:  "
          f"{disk.read_file(amiga.POR_SLOT_LIST)!r} "
          f"{amiga.read_slot_list(disk)}")
    problems = disk.verify()
    if problems:
        raise SystemExit("The disk does not verify:\n  "
                         + "\n  ".join(problems))
    disk.save(args.out)
    print(f"Saved {args.out}, {disk.free_count()} blocks free")
    return 0


if __name__ == "__main__":
    sys.exit(main())
