#!/usr/bin/env python3
"""Set a DOS party's combat-figure bytes, to give a conversion something to say.

`#130 (A converted DOS party arrives with six identical combat figures, not
its own)` needs a DOS party whose six figures are **deliberately different**,
because a party of six identical ones cannot tell "the conversion gave each
character his own figure" apart from "it gave all six the same one".  The one
DOS party this project watched being written -- `WISH-SPEC-por-party-l1`, six
characters rolled in the game's own creation screens -- holds `icon_head` 0
and `icon_body` 0 for all six, because the driver never entered the creation
screens' MODIFY ICON step.  So the figures have to be put there.

    tools/icons/dosiconstage.py --folder path/to/dosparty --slot C

This writes `icon_head`, `icon_body` and the six `icon_colours` bytes of a
character and nothing else, at the offsets of the title the record's size
names (`goldbox.dos_port`; Pool of Radiance `0x0BD`, `0x0BE` and `0x0C1`).
**`size` is left alone**, because it is the race's and changing it would
move two things at once.

Editing an input and then watching the game compute from it is a valid
experiment -- the engine does not care how a byte got there -- which is what
`.claude/rules/testing.md` distinguishes from reading back a value we wrote
and calling it the game's arithmetic.  The folder is edited in place, so
point it at a copy under the temp directory.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos_codec, dos_port  # noqa: E402

#: Six DOS figures a person can tell apart, in the order the files are read.
#: Chosen for distance rather than meaning: a bow, a sword and shield, a
#: robed staff, a raised axe, a crossbow and a flail, with three of the six
#: repainted so the colour half of the conversion is exercised as well as the
#: figure half.  `91 A2 B3 C4 E6 F7` is the set 42 of the 54 shipped records
#: across the four titles carry.
FIGURES = [
    (0, 1, "91a2b3c4e6f7"),      # short hair, bow
    (3, 24, "91a2b3c4e6f7"),     # visored helmet, sword and shield
    (6, 28, "91a2b3c4e6f7"),     # tall pointed hat, robed with a staff
    (2, 9, "2ea2b3c4e6f7"),      # plumed helmet, axe raised, green body
    (13, 16, "91a2b3c4e6f7"),    # crest, crossbow
    (5, 3, "91a2b3c4ef61"),      # long hair, flail, white shield, blue weapon
]


def stage(folder: pathlib.Path, slot: str, figures=FIGURES) -> list[dict]:
    """Write the figures into the party's records.  Returns what it wrote."""
    written = []
    names = sorted(folder.glob(f"CHRDAT{slot}?.SAV"))
    if len(names) != len(figures):
        raise SystemExit(f"{len(names)} records in slot {slot} and "
                         f"{len(figures)} figures to write")
    for path, (head, body, colours) in zip(names, figures):
        data = bytearray(path.read_bytes())
        fields = dos_port.FIELDS_BY_NAME_FOR[dos_port.deltas_for(len(data)).key]
        data[fields["icon_head"].offset] = head
        data[fields["icon_body"].offset] = body
        at = fields["icon_colours"].offset
        data[at:at + 6] = bytes.fromhex(colours)
        path.write_bytes(bytes(data))
        char = dos_codec.read_character(path)
        written.append({"file": path.name, "name": char.name,
                        "icon_head": char.get("icon_head"),
                        "icon_body": char.get("icon_body"),
                        "size": char.get("size"),
                        "icon_colours": bytes(char.get("icon_colours")).hex()})
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--folder", required=True,
                   help="the DOS save directory, edited in place; give it "
                        "a copy, not the original")
    p.add_argument("--slot", required=True, help="the DOS save slot letter")
    args = p.parse_args(argv)
    for row in stage(pathlib.Path(args.folder), args.slot):
        print(f"{row['file']} {row['name']:<12} head {row['icon_head']:>2} "
              f"body {row['icon_body']:>2} size {row['size']} "
              f"colours {row['icon_colours']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
