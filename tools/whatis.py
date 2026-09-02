#!/usr/bin/env python3
"""Which game file, if any, a block of captured memory holds.

    tools/whatis.py work/wallart/run2/05-slums.stage.bin 0x8C00

A driven session dumps regions of the machine as `.bin` files, and the first
question about every one of them is the same: **is this a file the loader put
there, and which one?** Answering it by eye means knowing what lives at
`$8C00` this minute, which is exactly what nobody knows -- the staging page
holds whatever the last `LOADFILES` asked for, and the loaded-files cache
names a *slot*, not the bytes.

So this scores every file on all eight sides against the block, each at its
own load address, and prints the best matches. A block that is a file byte for
byte is the answer outright; a block that matches nothing is scratch, or has
been written over since it was loaded, and that is an answer too. A partial
match is the interesting one -- `#156 (Warping from the Slums to New Phlan
draws New Phlan with the Slums' walls)` was a region that matched the arriving
area's file for the first half and the departed area's for the rest.

`--at-base` is for a region the loader relocates: it scores every file at the
block's own address rather than at the address the file declares.

Reads only, and reads the player's own disks; nothing it prints is committed.
"""

from __future__ import annotations

import argparse
import glob
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from automap.paths import disk_globs, find_disks  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402

#: Below this many overlapping bytes a percentage says nothing.
FLOOR = 64


def game_disks(root: str) -> list[str]:
    """Every game disk under `root`, each of them once."""
    seen: dict[str, str] = {}
    for pattern in disk_globs():
        for path in glob.glob(os.path.join(root, pattern)):
            seen.setdefault(os.path.normcase(os.path.abspath(path)), path)
    return sorted(seen.values())


def every_file(root: str) -> dict[str, tuple[int, bytes]]:
    """Name -> (load address, bytes) for every file on every side, once."""
    seen: dict[str, tuple[int, bytes]] = {}
    for path in game_disks(root):
        try:
            image = D64.open(path)
        except Exception:
            continue
        for entry in image.iter_directory():
            name = entry.name.decode("latin1").rstrip("\xa0 ")
            if not name or name in seen:
                continue
            try:
                seen[name] = split_load_address(image.read_file(name))
            except Exception:
                continue
    return seen


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Score every game file against a captured memory block.")
    ap.add_argument("blob", help="the captured block, as a plain .bin")
    ap.add_argument("base", type=lambda s: int(s, 0),
                    help="the address the block was read from")
    ap.add_argument("--top", type=int, default=8, metavar="N",
                    help="how many matches to print (default: %(default)s)")
    ap.add_argument("--at-base", action="store_true",
                    help="score every file at the block's own address, for a "
                         "region the loader relocates")
    ap.add_argument("--disks", default=os.environ.get("POR_DISKS"),
                    metavar="DIR",
                    help="where the game disks are (default: $POR_DISKS, "
                         "then wherever the program looks)")
    args = ap.parse_args(argv[1:])

    root = args.disks or str(find_disks() or "")
    if not root or not os.path.isdir(root):
        print("No game disks. Set $POR_DISKS or pass --disks.",
              file=sys.stderr)
        return 2

    blob = pathlib.Path(args.blob).read_bytes()
    rows = []
    for name, (declared, body) in every_file(root).items():
        load = args.base if args.at_base else declared
        if not (args.base <= load < args.base + len(blob)):
            continue
        off = load - args.base
        n = min(len(body), len(blob) - off)
        if n < FLOOR:
            continue
        same = sum(x == y for x, y in zip(blob[off:off + n], body[:n]))
        rows.append((same / n, same, n, name, load))
    rows.sort(reverse=True)
    if not rows:
        print(f"No file loads inside ${args.base:04X}-"
              f"${args.base + len(blob) - 1:04X}.")
        return 0
    for frac, same, n, name, load in rows[:args.top]:
        print(f"  {frac:6.1%}  {same:5d}/{n:<5d}  {name:12s} @${load:04X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
