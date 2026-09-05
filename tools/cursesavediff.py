#!/usr/bin/env python3
"""Diff two *Curse of the Azure Bonds* `SAVEAZURE` payloads, region by region.

The engine's own rewrite is the oracle a conversion is checked against
(`#192 (Convert a Curse of the Azure Bonds DOS save into a C64 one, which the
importer refuses today)` step 3): load a save Wish built, take the game's own
`ENCAMP > SAVE`, and every byte where the two disagree is either the engine's
bookkeeping or ours being wrong.  Reading 7424 bytes of `cmp -l` output is not
how anybody tells those apart, so this labels each run of differing bytes with
the region it lands in and, where the project has measured one, the sentence
that says whose byte it is.

    tools/cursesavediff.py ours.D64 engine.D64
    tools/cursesavediff.py ours.D64 engine.D64 --context 32

Either argument may be a `.d64` carrying `SAVEAZURE` or the raw 7424-byte
payload.  Offsets are printed as payload offsets, which is how
`goldbox/c64_save.py` and every `#192` measurement name them; add `$4B00` for
the address the running machine sees.

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
#: The header rows come from `#192` step 0e's census of every absolute operand
#: into `$4B00`-`$4EFF` over 411 files, and the container rows from
#: `goldbox/c64_save.py`.
REGIONS: tuple[tuple[int, int, str, str], ...] = (
    (0x000, 0x0BF, "ours", "active effects"),
    (0x0C0, 0x0C2, "ours", "the party's square and facing"),
    (0x0C3, 0x0C4, "engine", "the travel-grid square, rewritten every step"),
    (0x0C5, 0x0C5, "ours", "the resident GEO"),
    (0x0C6, 0x0CB, "engine", "the six clock digits, which tick as time passes"),
    (0x0CC, 0x0CD, "engine", "the clock's own carry counter, DUNGEON $0D67"),
    (0x0CE, 0x0E5, "engine", "the cached what-is-on-this-square array"),
    (0x0E6, 0x0E6, "ours", "indoors/outdoors"),
    (0x0E7, 0x0E8, "?", "two bytes four area scripts write at their heads"),
    (0x0E9, 0x0ED, "engine", "loader scratch"),
    (0x0EE, 0x0EE, "ours", "the disk hint, CAMP $0C87 and GEN $2008"),
    (0x0EF, 0x0EF, "engine", "loader scratch"),
    (0x0F0, 0x0F1, "ours", "the previous square, read by sixteen scripts"),
    (0x0F2, 0x0F2, "ours", "the script id"),
    (0x0F3, 0x0FC, "engine", "working state the engine refills"),
    (0x0FD, 0x0FE, "engine", "per-area constants the arriving script writes"),
    (0x0FF, 0x0FF, "ours", "the portrait switch, INIT's own $81"),
    (0x100, 0x11F, "ours", "the per-script scratch, zeroed only on an area change"),
    (0x120, 0x1FF, "ours", "the quest-flag page"),
    (0x200, 0x2BF, "engine", "working area"),
    (0x2C0, 0x2D8, "engine", "the loaded-files cache, refilled as files load"),
    (0x2D9, 0x2DF, "engine", "the seven bytes past the cache, named by nothing"),
    (0x2E0, 0x3FF, "ours", "the combat icon table"),
    (0x400, 0xBFF, "ours", "the eight character slots"),
    (0xC00, 0xFFF, "ours", "the name table"),
    (0x1000, 0x17FF, "ours", "the eight item pages"),
    (0x1800, 0x1BFF, "engine",
     "`ANIMATE00`'s picture buffer: the camp scene's current animation "
     "frame at the moment of the save"),
    (0x1C00, 0x1CFF, "ours", "the roster"),
    (0x1D00, 0x1CFF + 0x700, "?", "past the roster"),
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
    return load_payload(path, "SAVEAZURE")


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
