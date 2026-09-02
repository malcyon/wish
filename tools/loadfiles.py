#!/usr/bin/env python3
"""Every `LOADFILES` and `LOADPIECES` in a script, with immediate operands.

The dispatch tables are `DUNGEON $15A9` (low) and `$15E7` (high), indexed by
opcode; `$1625` is the operand count. That makes `LOADFILES` opcode `$21` and
`LOADPIECES` opcode `$37`, both with three operands, and `DUNGEON $1663` says
an operand whose kind byte is `00` is an immediate that follows it.

Only the all-immediate form is decoded, which is every one of them in the
thirty area scripts. Anything else is skipped rather than guessed at.

    loadfiles.py ECL00 ECL14

`tools/eclwalk.py` reads the same scripts statement by statement and is the
fuller answer; this one is the quick question, and it needs no `DUNGEON`.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from automap.paths import find_disks  # noqa: E402
from goldbox.d64 import D64  # noqa: E402

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or (find_disks() or ""))
BASE = 0x9900
OPS = {0x21: "LOADFILES", 0x37: "LOADPIECES"}


def load(name):
    """The body of a game file, from whichever `POOL` side carries it."""
    for n in range(1, 9):
        path = DISKS / f"POOL{n}.D64"
        if not path.exists():
            continue
        img = D64.open(path)
        for entry in img.iter_directory():
            if entry.name.decode("latin1").rstrip("\xa0 ") == name:
                return img.read_file(name)[2:]
    return None


def main():
    if not DISKS or not DISKS.exists():
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    for name in sys.argv[1:]:
        body = load(name)
        if body is None:
            print(f"{name}: Not on any side")
            continue
        print(f"{name} ({len(body)} bytes at ${BASE:04X})")
        for i in range(len(body) - 7):
            op = body[i]
            if op not in OPS:
                continue
            if body[i + 1] or body[i + 3] or body[i + 5]:
                continue        # not the three-immediates form
            a, b, c = body[i + 2], body[i + 4], body[i + 6]
            print(f"  ${BASE + i:04X}  {OPS[op]:10s} {a:3d}, {b:3d}, {c:3d}"
                  f"   (${a:02X}, ${b:02X}, ${c:02X})")


if __name__ == "__main__":
    main()
