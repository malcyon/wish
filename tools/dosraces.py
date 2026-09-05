#!/usr/bin/env python3
"""Read each DOS Gold Box title's race-name table out of its own executable.

`goldbox/dos_layout.py` carried one race table for all four titles until #237,
where it turned out to be right for Pool of Radiance and Curse and wrong for
Silver Blades and Pools of Darkness.  The tables the two later games actually
use are in the games, so this reads them rather than guessing:

    tools/dosraces.py            # print all four
    tools/dosraces.py --check    # compare against `DosShape.race_numbers`

**What it looks for.**  Each title's resident executable carries three
enumerations as counted strings -- one length byte then that many ASCII, the
slot padded with NUL to a fixed stride.  They sit in index order and next to
each other: the eighteen class names, then the races, then the nine
alignments.  So the race table is found by anchoring on `Lawful Good`, the
alignment table's entry 0, and walking *backwards* a slot at a time while the
bytes keep looking like a padded counted string.  Nothing is anchored on a
race name, which is the point: a table that named a race this reader had never
heard of would still be read.

**Why the reading can be trusted.**  Run against Pool of Radiance and Curse it
reproduces `RACE_NUMBERS` entry for entry -- a table this project established
independently, from 24 specimens and from the C64 -- so the construct is an
index-ordered enumeration and reading the other two the same way is the same
measurement.  Gold Box Companion's `GBC/Games/<title>/Game.dat` carries the
same four lists at file offset 0x0863c4, which is a second source that agrees.

The executables are the player's, read and never written; with no archives
this prints nothing and exits 0, the way the tests skip.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
# The repository root and nothing else.  Putting `tools/` on `sys.path` as
# well -- which this did, to reach `dosbox` by its bare name -- leaves it
# there for the rest of the process, and `tools/wish.py` then shadows the
# `wish` package for whatever imports it next; that is
# `#259 (A cold test run intermittently loses the wish package to
# tools/wish.py, and a different test fails each time)`, and this file was the
# proven culprit in the batch that reproduced it.  The sibling comes through
# the package instead, which also means `tools.dosbox` here is the same module
# object the tests patch rather than a second copy of it.
sys.path.insert(0, str(ROOT))

from goldbox import dos_layout  # noqa: E402
from tools import dosbox  # noqa: E402

#: Entry 0 of the alignment table, as a counted string.  The race table ends
#: where this begins, in all four titles.
ANCHOR = b"\x0bLawful Good"

#: The strides worth trying.  Pool of Radiance and Curse pad to 10, the two
#: later titles to 9; the search reports whichever gives the longest run so a
#: fifth title would not need this list changed.
STRIDES = range(4, 25)

#: The directory each title's executable lives in, and the file itself.
#: Pools of Darkness is the odd one: it is launched by `START.BAT` and its
#: resident code is `GAME.EXE`, where the other three are `START.EXE`.
TITLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("pool-of-radiance", "POOLRAD", ("START.EXE",)),
    ("curse-of-the-azure-bonds", "CURSE", ("START.EXE",)),
    ("secret-of-the-silver-blades", "SECRET", ("START.EXE",)),
    ("pools-of-darkness", "DARKNESS", ("GAME.EXE", "START.EXE")),
)


def find_executable(stem: str, names: tuple[str, ...]) -> pathlib.Path | None:
    """The resident executable for one title, inside the player's archives.

    `dosbox.find_game` insists on `START.EXE`, which Pools of Darkness does
    not have, so this walks the same `<collection>/games/*/GAME/<stem>` shape
    itself and takes the first of `names` that is there.
    """
    if not dosbox.ARCHIVES.is_dir():
        return None
    for collection in sorted(dosbox.ARCHIVES.iterdir()):
        games = collection / "games"
        if not games.is_dir():
            continue
        for entry in sorted(games.iterdir()):
            inner = entry / "GAME" / stem
            for name in names:
                if (inner / name).is_file():
                    return inner / name
    return None


def _slot(blob: bytes, at: int, stride: int) -> str | None:
    """The counted string in the slot at `at`, or None if that is not one.

    A slot is one length byte, that many bytes of a race name, and NUL to the
    end of the stride.  The name alphabet is deliberately narrow -- letters
    and the hyphen of `Half-Elf` -- because the whole job of this check is to
    stop the walk at the class table above, whose strings are longer than a
    slot and whose slots are a different width.
    """
    if at < 0 or at + stride > len(blob):
        return None
    length = blob[at]
    if not 1 <= length <= stride - 1:
        return None
    text = blob[at + 1:at + 1 + length]
    # `chr(b).isalpha()` is true for Latin-1 bytes above 0x7F -- À, É, Ø --
    # which would pass the guard and then raise UnicodeDecodeError out of
    # the ascii decode below, rather than the LookupError this module
    # promises.  Bound it to ASCII so an unrecognised run is "not a slot".
    if not all(b < 0x80 and (chr(b).isalpha() or b == ord("-"))
               for b in text):
        return None
    if any(blob[at + 1 + length:at + stride]):
        return None
    return text.decode("ascii")


def read_table(blob: bytes) -> tuple[int, int, tuple[str, ...]]:
    """`(offset, stride, names)` for the race table in one executable.

    Raises `LookupError` when the anchor is missing or no stride produces a
    plausible run, rather than handing back a short table that would read as
    a title with fewer races.
    """
    anchor = blob.find(ANCHOR)
    if anchor < 0:
        raise LookupError("no alignment table: this is not a Gold Box "
                          "executable, or its strings are packed")
    if blob.find(ANCHOR, anchor + 1) >= 0:
        raise LookupError("the alignment table's first entry appears twice, "
                          "so the race table's end is ambiguous")
    best: tuple[int, int, tuple[str, ...]] = (0, 0, ())
    for stride in STRIDES:
        # The alignment table does not always start where the race table
        # stops.  Treasures of the Savage Frontier pads one further byte
        # between the two, so the walk has to be allowed to begin short of
        # the anchor or it reads no table at all.
        for slack in range(stride):
            names: list[str] = []
            at = anchor - slack - stride
            while (name := _slot(blob, at, stride)) is not None:
                names.append(name)
                at -= stride
            if len(names) > len(best[2]):
                best = (at + stride, stride, tuple(reversed(names)))
    if len(best[2]) < 5:
        raise LookupError(
            f"only {len(best[2])} entries before the alignment table, which "
            f"is too few to be a race table")
    return best


def tables() -> dict[str, tuple[pathlib.Path, int, int, tuple[str, ...]]]:
    """Every title the archives hold, keyed by `DosShape.key`."""
    found = {}
    for key, stem, names in TITLES:
        path = find_executable(stem, names)
        if path is None:
            continue
        offset, stride, read = read_table(path.read_bytes())
        found[key] = (path, offset, stride, read)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="compare against DosShape.race_numbers and exit "
                             "nonzero on any difference")
    args = parser.parse_args(argv)

    found = tables()
    if not found:
        print("no DOS archives on this machine; set $FR_ARCHIVES",
              file=sys.stderr)
        return 0

    bad = 0
    for key, (path, offset, stride, read) in found.items():
        shape = dos_layout.shape_for(key)
        lower = tuple(n.lower() for n in read)
        print(f"{shape.title}  ({path.name}, entry 0 at 0x{offset:06x}, "
              f"stride {stride}, {len(read)} entries)")
        for i, name in enumerate(read):
            print(f"  {i}  {name}")
        if args.check:
            if lower != tuple(shape.race_numbers):
                bad += 1
                print(f"  MISMATCH: dos_layout says {tuple(shape.race_numbers)}")
            else:
                print("  matches dos_layout")
        print()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
