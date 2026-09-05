#!/usr/bin/env python3
"""Diff two *Secret of the Silver Blades* `SAVEDBASH` payloads, region by region.

The engine's own rewrite is the oracle a conversion is checked against
(`#193 (Convert a Secret of the Silver Blades DOS save into a C64 one, which
the importer refuses today)` step 3): load a save Wish built, take the game's
own `ENCAMP > SAVE`, and every byte where the two disagree is either the
engine's bookkeeping or ours being wrong.  Reading 7424 bytes of `cmp -l`
output is not how anybody tells those apart, so this labels each run of
differing bytes with the region it lands in and, where the project has
measured one, the sentence that says whose byte it is.

    tools/ssbsavediff.py ours.D64 engine.D64
    tools/ssbsavediff.py ours.D64 engine.D64 --context 32

`tools/cursesavediff.py` is the same tool for Curse of the Azure Bonds and
the two region tables are **not** the same, which is why this is a second
file: five header rows change hands between the titles, each measured on
Silver Blades' own overlays and its own `ECL` bytecode.

Either argument may be a `.d64` carrying `SAVEDBASH` or the raw 7424-byte
payload.  Offsets are printed as payload offsets, which is how
`goldbox/c64_save.py` names them; add `$4B00` for the address the running
machine sees.

Exit status is 1 when a run lands in a region marked `ours`, so a run can be
a check rather than something a person reads.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox.d64 import load_payload  # noqa: E402

#: `(first, last, whose, what)` over the payload, in offset order.
#:
#: `whose` is `engine` for a region the game rewrites for itself, `ours` for
#: one where a difference is a conversion fault, and `?` for one nobody has
#: attributed.  A run that lands in an `ours` region is what the exit status
#: reports.
#:
#: The header rows come from an absolute-operand census over `$4B00`-`$4EFF`
#: across this title's 347 files (`tools/absrefsweep.py`) and from an address
#: census over all twenty-two of its `ECL` scripts on both ports
#: (`tools/eclcensus.py`); the container rows from `goldbox/c64_save.py`.
#:
#: **Where this differs from Curse's table, and why.**  `+$E7`-`+$E9` and
#: `+$FD`-`+$FE` are `ours` here rather than the engine's, because the
#: conversion copies the party's own value into them out of the DOS save --
#: seventeen of this title's scripts write `+$E7`/`+$E8` at their heads and
#: none of the twenty-two ever reads one, so an arriving script refilling
#: them is expected and a difference there is not a fault in itself, but it
#: is a difference worth being told about.  `+$EA` is the engine's here and
#: `ours` in Curse: it is Pool of Radiance's disk hint, and in this title
#: `DUNGEON $0B0E` uses it as its own scratch.
REGIONS: tuple[tuple[int, int, str, str], ...] = (
    (0x000, 0x0BF, "ours", "active effects"),
    (0x0C0, 0x0C2, "ours", "the party's square and facing"),
    (0x0C3, 0x0C4, "engine", "Pool of Radiance's travel-grid square; this "
                             "title has no travel grid"),
    (0x0C5, 0x0C5, "ours", "the resident GEO"),
    (0x0C6, 0x0CB, "engine", "the six clock digits, which tick as time passes"),
    (0x0CC, 0x0CD, "engine", "the clock's own carry counter"),
    (0x0CE, 0x0E5, "engine", "the cached what-is-on-this-square array"),
    (0x0E6, 0x0E6, "ours", "indoors/outdoors"),
    (0x0E7, 0x0E9, "ours", "three per-area bytes copied from the DOS save; "
                           "seventeen scripts write them and none reads one"),
    (0x0EA, 0x0EA, "engine", "DUNGEON $0B0E's own scratch in this title"),
    (0x0EB, 0x0ED, "engine", "loader scratch"),
    (0x0EE, 0x0EE, "ours", "the disk hint, CAMP $0C65 and GEN $228E"),
    (0x0EF, 0x0EF, "engine", "loader scratch"),
    (0x0F0, 0x0F1, "ours", "the previous square, read by sixteen scripts"),
    (0x0F2, 0x0F2, "ours", "the script id"),
    (0x0F3, 0x0FC, "engine", "working state the engine refills"),
    (0x0FD, 0x0FE, "ours", "per-area constants copied from the DOS save; the "
                           "arriving script writes them too"),
    (0x0FF, 0x0FF, "ours", "the portrait switch"),
    (0x100, 0x11F, "ours",
     "the per-script scratch, zeroed only on an area change"),
    (0x120, 0x1FF, "ours", "the quest-flag page"),
    (0x200, 0x2BF, "engine", "working area"),
    (0x2C0, 0x2D8, "engine",
     "the loaded-files cache, refilled as files load"),
    (0x2D9, 0x2DF, "engine", "the seven bytes past the cache"),
    (0x2E0, 0x3FF, "ours", "the combat icon table"),
    (0x400, 0xBFF, "ours", "the eight character slots"),
    (0xC00, 0xFFF, "ours", "the name table"),
    (0x1000, 0x17FF, "ours", "the eight item pages"),
    (0x1800, 0x1BFF, "engine",
     "`ANIMATE00`'s picture buffer: the decoded picture in the view window "
     "at the moment of the save, `PIC3B` in all four specimens here"),
    (0x1C00, 0x1CFF, "ours", "the roster"),
)


def region_of(offset: int) -> tuple[str, str]:
    for first, last, whose, what in REGIONS:
        if first <= offset <= last:
            return whose, what
    return "?", "outside every named region"


def payload(path: str) -> bytes:
    """The 7424 payload bytes, from a `.d64` or from a raw file."""
    raw = pathlib.Path(path).read_bytes()
    if len(raw) == 7424:
        return raw
    return load_payload(path, "SAVEDBASH")


def runs(a: bytes, b: bytes) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for i in range(min(len(a), len(b))):
        if a[i] == b[i]:
            continue
        if out and i == out[-1][1] + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return [(s, e) for s, e in out]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("ours", help="the save Wish wrote (.d64 or raw payload)")
    p.add_argument("engine", help="the save the game wrote (.d64 or raw)")
    p.add_argument("--context", type=int, default=16,
                   help="how many bytes of each run to print (default 16)")
    p.add_argument("--quiet", action="store_true",
                   help="print the per-region summary only")
    args = p.parse_args(argv)

    a, b = payload(args.ours), payload(args.engine)
    if len(a) != len(b):
        print(f"{len(a)} bytes against {len(b)}: these are not the same "
              f"container")
        return 2
    found = runs(a, b)
    total = sum(e - s + 1 for s, e in found)
    print(f"{total} bytes differ in {len(found)} runs, of {len(a)}")

    tally: dict[tuple[str, str], int] = {}
    for s, e in found:
        whose, what = region_of(s)
        tally[(whose, what)] = tally.get((whose, what), 0) + (e - s + 1)
        if not args.quiet:
            n = min(args.context, e - s + 1)
            print(f"  +${s:04X}-+${e:04X} {e - s + 1:5d}  [{whose}] {what}")
            print(f"      ours   {a[s:s + n].hex(' ')}")
            print(f"      engine {b[s:s + n].hex(' ')}")

    print("\n  by region:")
    bad = 0
    for (whose, what), n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"    {n:5d}  [{whose}] {what}")
        if whose == "ours":
            bad += n
    if bad:
        print(f"\n  {bad} bytes differ in a region a conversion writes; "
              f"each is a fault until explained")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
