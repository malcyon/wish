#!/usr/bin/env python3
"""Which of a DOS part's two colours covers more of it: the main or the highlight?

A DOS character's `icon_colours` keeps two 4-bit colours per part, low nibble
the main colour and high the highlight, and the C64 keeps one colour a part --
a multicolour cell owns its low three bits and shares the other three with the
whole screen.  So a conversion has to pick a nibble, and
`#130 (A converted DOS party arrives with six identical combat figures, not its
own)` picks the low one on the grounds that it is the part's main colour.

This counts the pixels and says whether that is true, per part and per option,
over every block of `CHEAD.DAX` and `CBODY.DAX` at both sizes and both poses.

    tools/dosnibbles.py                 # the totals, per part
    tools/dosnibbles.py --per-option    # one line per CBODY option

It also counts how often the choice makes any difference at all: with the
EGA-to-C64 table in `tools/iconproposal.yaml`, both nibbles of a pair often
land on the same C64 colour, and then there is nothing to choose.

    tools/dosnibbles.py --records <a directory of DOS saves>

The DOS game directory is `--dos`, then `$POR_DOS_GAME`, then the search
`tools/iconcorrespond.py` does.  Nothing is written.
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import iconcorrespond as ic  # noqa: E402

from goldbox.iconparts import DOS_PAIR_CLASSES, dos_icon_tables  # noqa: E402

#: The pixel value each part's main colour is drawn in; the highlight is that
#: value plus eight.  `goldbox/iconparts.py` has where this comes from.
MAIN_VALUE = {"body": 1, "arm": 2, "leg": 3, "hair": 4, "shield": 6,
              "weapon": 7}


def counts(game: pathlib.Path, stem: str, size: str, option: int | None = None,
           ) -> collections.Counter:
    """Every pixel value, over both poses of one option or of all of them."""
    out: collections.Counter = collections.Counter()
    for pose in (0, 1):
        options = ic.dos_options(game, stem, size, pose)
        wanted = [options[option]] if option is not None else options.values()
        for pixels in wanted:
            for row in pixels:
                out.update(row)
    return out


def share(tally: collections.Counter, part: str) -> float | None:
    """What fraction of `part`'s pixels are drawn in the highlight colour."""
    main, high = tally[MAIN_VALUE[part]], tally[MAIN_VALUE[part] + 8]
    return None if main + high == 0 else high / (main + high)


def totals(game: pathlib.Path) -> None:
    tally: collections.Counter = collections.Counter()
    for stem in ("CBODY", "CHEAD"):
        for size in ("small", "large"):
            tally.update(counts(game, stem, size))
    print("every option of both files, both sizes, both poses")
    print(f"{'part':8} {'main':>8} {'highlight':>10} {'highlight share':>16}")
    for part in MAIN_VALUE:
        got = share(tally, part)
        if got is None:
            continue
        print(f"{part:8} {tally[MAIN_VALUE[part]]:>8} "
              f"{tally[MAIN_VALUE[part] + 8]:>10} {got:>15.1%}")


def per_option(game: pathlib.Path, size: str = "large") -> None:
    parts = [p for p in MAIN_VALUE if p != "hair"]
    print(f"per CBODY option, {size}, both poses: the highlight's share")
    print(f"{'body':>4} " + " ".join(f"{p:>8}" for p in parts))
    majority: collections.Counter = collections.Counter()
    for option in sorted(ic.dos_options(game, "CBODY", size, 0)):
        tally = counts(game, "CBODY", size, option)
        cells = []
        for part in parts:
            got = share(tally, part)
            cells.append("       -" if got is None else f"{got:>7.0%}")
            if got is not None and got > 0.5:
                majority[part] += 1
        print(f"{option:>4} " + " ".join(f"{c:>8}" for c in cells))
    print("options where the highlight covers more than half the part: "
          + ", ".join(f"{p} {majority[p]}" for p in parts))


def records(folder: pathlib.Path) -> None:
    """How often the two nibbles land on different C64 colours at all."""
    from goldbox import dos

    ega = dos_icon_tables().ega_to_c64
    agree = disagree = 0
    per: collections.Counter = collections.Counter()
    for path in sorted(folder.rglob("*")):
        if path.suffix.upper() not in (".SAV", ".CHA"):
            continue
        try:
            colours = bytes(dos.read_character(path).get("icon_colours"))
        except Exception:
            continue
        differs = False
        for i, part in enumerate(DOS_PAIR_CLASSES):
            if ega[colours[i] & 0x0F] != ega[colours[i] >> 4]:
                per[part] += 1
                differs = True
        agree += not differs
        disagree += differs
    print(f"{agree + disagree} records: {agree} where every pair's two "
          f"nibbles land on the same C64 colour, {disagree} where at least "
          f"one does not")
    for part in DOS_PAIR_CLASSES:
        print(f"  {part:8} {per[part]}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dos", default=None, help="the DOS game directory")
    p.add_argument("--per-option", action="store_true",
                   help="one line per CBODY option instead of the totals")
    p.add_argument("--size", default="large", choices=("small", "large"))
    p.add_argument("--records", default=None,
                   help="a directory of DOS saves to count instead")
    args = p.parse_args(argv)
    if args.records:
        records(pathlib.Path(args.records))
        return 0
    game = ic.dos_game(args.dos)
    if args.per_option:
        per_option(game, args.size)
    else:
        totals(game)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
