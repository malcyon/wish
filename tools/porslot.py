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

The party is read back out of the disk through `read_amiga_por` and
`to_neutral`, so it goes through the same neutral record a converted party
would, and anything that cannot cross is reported rather than dropped.

**The input disk is opened read-only and `--out` is required.** The player's
own disks are not written to; work on a copy.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import amiga  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402


def read_slot(disk: AmigaDisk, slot: str):
    """The characters of one slot, as neutral records, and its saved game.

    `read_amiga_por` wants a path, because a `.sav` is read with its sibling
    `.itm` and `.spc` and the record's own item count decides how much of the
    `.itm` is this character's.  So the three files come off the disk into a
    temporary directory and are read from there, rather than teaching the
    reader a second way in that would then have to be kept in step.
    """
    letter = slot.upper()
    characters = []
    with tempfile.TemporaryDirectory() as tmp:
        for index in range(1, amiga.POR_PARTY_MAX + 1):
            stem = f"/{amiga.POR_SAVE_DRAWER}/" \
                   f"{amiga.por_filename(letter, index, '')}"
            try:
                record = disk.read_file(stem + ".sav")
            except AmigaDiskError:
                break
            here = pathlib.Path(tmp) / f"{letter}{index}.sav"
            here.write_bytes(record)
            for suffix in (".itm", ".spc"):
                try:
                    here.with_suffix(suffix).write_bytes(
                        disk.read_file(stem + suffix))
                except AmigaDiskError:
                    pass
            characters.append(amiga.read_amiga_por(here))
    savegame = disk.read_file(
        f"/{amiga.POR_SAVE_DRAWER}/{amiga.por_savegame_filename(letter)}")
    return characters, savegame


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

    disk = AmigaDisk.open(args.disk)
    print(f"Slot list before: "
          f"{disk.read_file(amiga.POR_SLOT_LIST)!r} "
          f"{amiga.read_slot_list(disk)}")

    characters, savegame = read_slot(disk, args.source)
    if not characters:
        raise SystemExit(f"Slot {args.source.upper()} has no characters on "
                         f"{args.disk}")
    neutral = []
    for char in characters:
        record = amiga.to_neutral(char)
        for line in list(record.warnings) + list(record.dropped):
            print(f"  {char.name}: {line}")
        neutral.append(record)
    print(f"Read {len(neutral)} characters from slot {args.source.upper()}: "
          f"{', '.join(c.name for c in characters)}")

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
