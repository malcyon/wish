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

    tools/dosiconstage.py --folder work/issue130/dosparty --slot C

This writes four record bytes a character and nothing else: `icon_head`
`0x0BD`, `icon_body` `0x0BE` and the six `icon_colours` pairs at `0x0C1`.
**`size` `0x0C0` is left alone**, because it is the race's and changing it
would move two things at once.

Editing an input and then watching the game compute from it is a valid
experiment -- the engine does not care how a byte got there -- which is what
`.claude/rules/testing.md` distinguishes from reading back a value we wrote
and calling it the game's arithmetic.  The folder is edited in place, so
point it at a copy under `work/`.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos  # noqa: E402

ICON_HEAD = 0x0BD
ICON_BODY = 0x0BE
ICON_COLOURS = 0x0C1

#: Six DOS figures a person can tell apart, in the order the files are read.
#: Chosen for distance rather than meaning: a bow, a sword and shield, a
#: robed staff, a raised axe, a crossbow and a flail, with three of the six
#: repainted so the colour half of the conversion is exercised as well as the
#: shape half.  `91 A2 B3 C4 E6 F7` is the set 42 of the 54 shipped records
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
        data[ICON_HEAD] = head
        data[ICON_BODY] = body
        data[ICON_COLOURS:ICON_COLOURS + 6] = bytes.fromhex(colours)
        path.write_bytes(bytes(data))
        char = dos.read_character(path)
        written.append({"file": path.name, "name": char.name,
                        "icon_head": char.get("icon_head"),
                        "icon_body": char.get("icon_body"),
                        "size": char.get("size"),
                        "icon_colours": bytes(char.get("icon_colours")).hex()})
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--folder", required=True,
                   help="the DOS save directory, edited in place; keep it "
                        "under work/")
    p.add_argument("--slot", required=True, help="the DOS save slot letter")
    args = p.parse_args(argv)
    for row in stage(pathlib.Path(args.folder), args.slot):
        print(f"{row['file']} {row['name']:<12} head {row['icon_head']:>2} "
              f"body {row['icon_body']:>2} size {row['size']} "
              f"colours {row['icon_colours']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
