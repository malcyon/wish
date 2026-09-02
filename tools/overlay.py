#!/usr/bin/env python3
"""Read one of the game's overlays at the addresses it runs at.

An overlay on the disk is a PRG: a two-byte load address and then the bytes.
Everything this project writes about one -- an issue, a `docs/` page, a note
in `goldbox/` -- names a **run-time** address, and every answer therefore
starts with the same two chores: find which of the eight sides carries the
file, and subtract the base. This does both, so a finding can be checked
without extracting anything first.

    tools/overlay.py hex DUNGEON 0x0B30 0x0BB0
    tools/overlay.py refs DUNGEON 0x28DC
    tools/overlay.py dis DUNGEON 0x2005 0x2060

**The base is a parameter and the default is a trap avoided.** `DUNGEON` runs
at `$0800` though its PRG header says `$1000` (`docs/118-debug-mode.md`), so
the header cannot be believed; `--base` defaults to `$0800`, which is where
`LINKER` puts every overlay it calls, and `--base header` uses whatever the
file claims for the ones that are not called that way.

`refs` is the one worth having a name for: it finds every place inside the
overlay that mentions an address, with the byte in front of it, so a `JSR`
into a routine is one command rather than a read of the whole file. That is
how the wall-art handlers were found for `#156 (Warping from the Slums to New
Phlan draws New Phlan with the Slums' walls)`.

Nothing here writes, and nothing it prints is committed: the game's bytes stay
on the player's own disks.
"""

from __future__ import annotations

import argparse
import glob
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import d6502  # noqa: E402

from automap.paths import disk_globs, find_disks  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402

#: `LINKER` loads every overlay it dispatches to at `$0800`.
LINKER_BASE = 0x0800


def game_disks(root: str) -> list[str]:
    """Every game disk under `root`, each of them once."""
    seen: dict[str, str] = {}
    for pattern in disk_globs():
        for path in glob.glob(os.path.join(root, pattern)):
            seen.setdefault(os.path.normcase(os.path.abspath(path)), path)
    return sorted(seen.values())


def load(name: str, root: str) -> tuple[int, bytes]:
    """The named file's declared load address and its bytes, off any side."""
    for path in game_disks(root):
        try:
            image = D64.open(path)
        except Exception as exc:
            print(f"  ({path}: {exc})", file=sys.stderr)
            continue
        for entry in image.iter_directory():
            if entry.name.decode("latin1").rstrip("\xa0 ") == name:
                # A broken sector chain is one bad side, not the end of the
                # search -- the same file is usually on several.  Saying so
                # keeps "the disk is unreadable" from looking like "the file
                # is not here", which is the message below.
                try:
                    return split_load_address(image.read_file(name))
                except Exception as exc:
                    print(f"  ({path}: {name}: {exc})", file=sys.stderr)
                    break
    raise SystemExit(f"No file called {name} on any disk under {root}")


def number(text: str) -> int:
    return int(text, 0)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Read a game overlay at the addresses it runs at.")
    ap.add_argument("what", choices=("hex", "refs", "dis"),
                    help="hex dumps a range, refs finds every mention of one "
                         "address, dis disassembles a range")
    ap.add_argument("file", help="the file's name on the disk, e.g. DUNGEON")
    ap.add_argument("start", type=number,
                    help="run-time address: the range's start, or the address "
                         "to find references to")
    ap.add_argument("end", type=number, nargs="?",
                    help="run-time address the range ends at (hex and dis)")
    ap.add_argument("--base", default=hex(LINKER_BASE), metavar="ADDR",
                    help="the address the file runs at (default: "
                         "%(default)s, where LINKER puts an overlay), or "
                         "'header' to believe the PRG's own load address")
    ap.add_argument("--disks", default=os.environ.get("POR_DISKS"),
                    metavar="DIR", help="where the game disks are (default: "
                                        "$POR_DISKS, then wherever the "
                                        "program looks)")
    args = ap.parse_args(argv[1:])

    root = args.disks or str(find_disks() or "")
    if not root or not os.path.isdir(root):
        print("No game disks. Set $POR_DISKS or pass --disks.",
              file=sys.stderr)
        return 2

    declared, body = load(args.file, root)
    base = declared if args.base == "header" else number(args.base)

    if args.what == "refs":
        want = bytes([args.start & 0xFF, args.start >> 8])
        found = 0
        at = body.find(want)
        while at >= 0:
            before = body[at - 1] if at else 0
            how = {0x20: "  (JSR)", 0x4C: "  (JMP)"}.get(before, "")
            print(f"${base + at:04X}  preceded by ${before:02X}{how}")
            found += 1
            at = body.find(want, at + 1)
        print(f"{found} mention{'' if found == 1 else 's'} of "
              f"${args.start:04X} in {args.file} (loaded at ${base:04X})")
        return 0

    if args.end is None:
        print(f"{args.what} wants an end address as well as a start.",
              file=sys.stderr)
        return 2
    lo, hi = args.start - base, args.end - base
    if lo < 0 or lo >= len(body):
        print(f"${args.start:04X} is outside {args.file}, which covers "
              f"${base:04X}-${base + len(body) - 1:04X}.", file=sys.stderr)
        return 2

    if args.what == "hex":
        for addr in range(args.start, args.end, 16):
            row = body[addr - base:min(addr - base + 16, hi)]
            print(f"${addr:04X}  " + " ".join(f"{b:02x}" for b in row))
        return 0

    # `dis` counts instructions rather than bytes, so ask for more than the
    # range can hold and stop when the addresses run past it.
    for line in d6502.lines(body, base, args.start, args.end - args.start):
        if int(line[1:5], 16) >= args.end:
            break
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
