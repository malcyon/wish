#!/usr/bin/env python3
"""Weigh a DOS Gold Box character against its stored encumbrance.

The identity `money + sum(weight x quantity)` is this project's strongest
self-check on a DOS record -- it confirms the money block, the item stride,
the weight offset and the byte order in one sum.  This tool prints both sides
of it, coin by coin and item by item, so a discrepancy can be attributed to a
term rather than guessed at.  Point it at a directory of saves per step of a
driven run and one purchase's effect on the stored number is a diff of two
lines.

`--census` sweeps every `.SAV` and `.CHA` the machine has -- the DOS archives
by `gamedisks.toml` and everything under `work/` -- deduplicates on the record
bytes together with its items', and reports how the discrepancy is
distributed.  That is what makes a claim about the identity a count rather
than an anecdote.  On 2026-09-04: **264 distinct records, 214 balancing
exactly, and every one of the six that miss by `+3` is a Curse character
freshly out of the Tilverton shop.**  Two caveats on the rest of that
distribution, because the sweep is deliberately unfiltered -- the large
positives are our own `BUILT-`/`ENGINE-` seeds under `work/`, which have no
item file for the sum to find, and the two Pool of Radiance characters at
`-65` and `-20` are the stale dart stacks `goldbox/dos_layout.py` already
names.

Written for `#225 (A shopped Curse character's stored encumbrance is three
tenths above the sum)`, where the answer turned out to be that a purchase
recomputes the total and *then* takes the coins, so the stored number leads the
truth by the price of the last purchase until anything else recomputes it --
`docs/125-bug-notes.md` N19.  Weights are tenths of a pound throughout, and
`enc` is the record's own stored field (`0x102` in Pool of Radiance, `0x187`
in Curse) against our `coins + items`.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos  # noqa: E402


def characters(folder: pathlib.Path) -> list[tuple[str, dos.DosCharacter]]:
    """Every readable `CHRDAT<slot><n>.SAV` in one directory, in name order."""
    out = []
    for path in sorted(folder.glob("CHRDAT*.SAV")):
        try:
            out.append((path.name, dos.read_character(path)))
        except dos.DosRecordError as e:
            print(f"  {path.name}: {e}", file=sys.stderr)
    return out


def carried(char: dos.DosCharacter) -> int:
    """The item half of the identity: sum(weight x quantity or 1)."""
    return sum(it.get("weight") * (it.get("quantity") or 1) for it in char.items)


def coins(char: dos.DosCharacter) -> int:
    return sum(char.money.values())


def delta(char: dos.DosCharacter) -> int:
    """Stored encumbrance minus what the record's own parts add up to."""
    return char.get("encumbrance") - coins(char) - carried(char)


def report(name: str, char: dos.DosCharacter, verbose: bool = True) -> None:
    d = delta(char)
    print(f"{name:14s} {char.name:10s} enc={char.get('encumbrance'):6d} "
          f"coins={coins(char):5d} items={carried(char):5d} "
          f"delta={d:+d}  ({len(char.items)} items)")
    if not verbose:
        return
    money = {k: v for k, v in char.money.items() if v}
    if money:
        print("    coins: " + ", ".join(f"{k} {v}" for k, v in money.items()))
    for i, it in enumerate(char.items):
        print(f"    [{i}] w={it.get('weight'):5d} q={it.get('quantity'):3d} "
              f"rdy={it.get('readied')} val={it.get('value'):5d} "
              f"type={it.get('type_index'):3d} "
              f"{it.display_line!r}")


def census_roots() -> list[pathlib.Path]:
    """Every directory the project knows of that may hold DOS records."""
    from tools import gamedisks
    roots = [p for p in gamedisks.candidates("dos-archives") if p.is_dir()]
    work = pathlib.Path(__file__).resolve().parent.parent / "work"
    if work.is_dir():
        roots.append(work)
    return roots


def census(roots: list[pathlib.Path]) -> None:
    """Delta distribution over every DOS character record found.

    Deduplicated on the record bytes together with its items', because the
    archives ship most save directories twice and a driven run copies its
    whole directory forward at every step; counting those again would inflate
    a corpus without adding a specimen.
    """
    seen: set[bytes] = set()
    rows: list[tuple[int, str, str, int, int, int, int, pathlib.Path]] = []
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.suffix.upper() not in (".SAV", ".CHA") or not path.is_file():
                continue
            try:
                char = dos.read_character(path)
            except (dos.DosRecordError, OSError, ValueError):
                continue
            key = bytes(char) + b"".join(bytes(it) for it in char.items)
            if key in seen:
                continue
            seen.add(key)
            rows.append((delta(char), char.shape.key, char.name,
                         char.get("encumbrance"), coins(char), carried(char),
                         len(char.items), path))
    counts: dict[int, int] = {}
    for row in rows:
        counts[row[0]] = counts.get(row[0], 0) + 1
    print(f"{len(rows)} distinct character records over {len(roots)} roots")
    for d in sorted(counts):
        print(f"  delta {d:+6d}: {counts[d]} record(s)")
    print()
    for d, title, name, enc, cn, it, n, path in sorted(rows, key=lambda r: -abs(r[0])):
        if d:
            print(f"  {d:+6d}  {title:18s} {name:14s} enc={enc:6d} "
                  f"coins={cn:6d} items={it:5d} n={n}  {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="*", type=pathlib.Path,
                    help="save directories, or single CHRDAT*.SAV files")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="one line per character, no item breakdown")
    ap.add_argument("--only", default="",
                    help="only characters whose name starts with this")
    ap.add_argument("--nonzero", action="store_true",
                    help="only characters whose delta is not zero")
    ap.add_argument("--census", action="store_true",
                    help="sweep every DOS record on this machine instead")
    args = ap.parse_args(argv)

    if args.census:
        census(census_roots() + [p for p in args.paths if p.is_dir()])
        return 0
    for path in args.paths:
        pairs = ([(path.name, dos.read_character(path))] if path.is_file()
                 else characters(path))
        print(f"== {path}")
        for name, char in pairs:
            if args.only and not char.name.upper().startswith(args.only.upper()):
                continue
            if args.nonzero and delta(char) == 0:
                continue
            report(name, char, verbose=not args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
