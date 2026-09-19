#!/usr/bin/env python3
"""Weigh a DOS Gold Box character against its stored encumbrance.

The identity `money + sum(weight x quantity)` is this project's strongest
self-check on a DOS record -- it confirms the money block, the item stride,
the weight offset and the byte order in one sum.  This tool prints both sides
of it, coin by coin and item by item, so a discrepancy can be attributed to a
term rather than guessed at.  Point it at a directory of saves per step of a
driven run and one purchase's effect on the stored number is a diff of two
lines.

`--census` sweeps every `.SAV` and `.CHA` the machine has -- the specimen
tree, the DOS archives and the played DOS game directory, all three by
`tools/dos/dostailcensus.py`'s own root list -- deduplicates on the record bytes
together with its items', and reports how the discrepancy is distributed.
That is what makes a claim about the identity a count rather than an anecdote.
On 2026-09-18, over 331 distinct records: **272 balance exactly**, 48 of the
59 that miss are `#249`'s own training ladder missing by an exact multiple of
1000 gp -- the training fee -- and the two Pool of Radiance characters at
`-65` and `-20`, GILES and ASTRID, are PROBABLY edited: their cached line and stored
total agree with each other against a round quantity byte, which is what an
edit leaves, where the engine itself keeps the quantity byte and the stored
total in step and lets only the cached line go stale
(`docs/125-bug-notes.md` N19).  Six at `-18001` are `#323`'s deliberately
spoiled specimen, and `+109` is the hand-axe purchase of
`docs/213-the-dos-shopping-trip.md`.

The 2026-09-04 reading was 264 records over the archives and the scratch
directory, and the six Curse characters `#225` found at `+3` were in that
directory.  It has been deleted (scratch was lost twice), so it is no longer a
default root (#575): the two counts are not counts of the same files, and
neither number can be read as the other moving.

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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import dos_codec  # noqa: E402


def characters(folder: pathlib.Path) -> list[tuple[str, dos_codec.DosCharacter]]:
    """Every readable `CHRDAT<slot><n>.SAV` in one directory, in name order."""
    out = []
    for path in sorted(folder.glob("CHRDAT*.SAV")):
        try:
            out.append((path.name, dos_codec.read_character(path)))
        except dos_codec.DosRecordError as e:
            print(f"  {path.name}: {e}", file=sys.stderr)
    return out


def carried(char: dos_codec.DosCharacter) -> int:
    """The item half of the identity: sum(weight x quantity or 1)."""
    return sum(it.get("weight") * (it.get("quantity") or 1) for it in char.items)


def coins(char: dos_codec.DosCharacter) -> int:
    return sum(char.money.values())


def delta(char: dos_codec.DosCharacter) -> int:
    """Stored encumbrance minus what the record's own parts add up to."""
    return char.get("encumbrance") - coins(char) - carried(char)


def report(name: str, char: dos_codec.DosCharacter, verbose: bool = True) -> None:
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
    """Every directory the project knows of that may hold DOS records.

    `tools/dos/dostailcensus.py`'s list, so this sweep and every other DOS census
    on this machine cover the same corpus (#575): the specimen tree, the
    archives and the played DOS game directory.
    """
    from tools.dos import dostailcensus
    return dostailcensus.dos_record_roots()


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
                char = dos_codec.read_character(path)
            except (dos_codec.DosRecordError, OSError, ValueError):
                continue
            key = bytes(char) + b"".join(bytes(it) for it in char.items)
            if key in seen:
                continue
            seen.add(key)
            rows.append((delta(char), char.deltas.key, char.name,
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
        roots = census_roots() + [p for p in args.paths if p.is_dir()]
        if not roots:
            from tools.dos import dostailcensus
            print(dostailcensus.NO_RECORDS, file=sys.stderr)
            return 1
        census(roots)
        return 0
    for path in args.paths:
        pairs = ([(path.name, dos_codec.read_character(path))] if path.is_file()
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
