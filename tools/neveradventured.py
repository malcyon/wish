#!/usr/bin/env python3
"""Which DOS saved games on this machine were made before the party set out.

A Gold Box party can be saved from the party-formation menu, before
`BEGIN ADVENTURING` -- the menu offers `SAVE CURRENT GAME` between
`REMOVE CHARACTER FROM PARTY` and `BEGIN ADVENTURING` to any party with a
character in it, on DOS and on the C64 alike.  Such a save carries the
initialiser's world state rather than a real one, and
`#301 (A DOS Curse save standing in area 0 is refused by the import, because
no row of the area table names area 0)` is what happens when the import meets
one.

**The area word is 0 in such a save on all three titles, and that is not the
test to key on.**  Pool of Radiance has a real area 0 -- New Phlan, `GEO00`,
side 3, where the game starts and where a player spends much of it -- so a
rule reading "area 0 means the party has not set out" would move a party out
of New Phlan and reset its clock.  Curse of the Azure Bonds and Secret of the
Silver Blades have no area 0 at all.  This tool exists to keep that
distinction measurable rather than remembered.

What it prints, per title: every distinct container, split into the ones whose
world state is the initialiser's and the ones whose is not, with the words
that separate them.  The separation is taken two ways, so a title where one is
unavailable still has the other:

* **the staged area script**, bytes 5121-12800 of the container, all zero or
  not.  A party in the world always has its area's script staged there, so
  this is a mechanism rather than a correlation -- and it is what
  `--by buffer` uses.  Secret of the Silver Blades' 5469-byte container has no
  script buffer (`script_bytes` is 0), so this test cannot be taken there.
* **`$4FE1`**, which is 0 in every never-adventured container and in no
  other, on all three titles -- `--by word`.  Curse's `GAME.OVR:0x832F`
  stores `$FF` into it (`goldbox.dos.LATER_BEGUN_WORD`); what Pool of
  Radiance's 255, 16 and 8 mean there is unread, so for that title this is
  a census result and not a reading of the engine.

`--by rule` is what the import itself applies -- `goldbox.dos.never_adventured`,
the buffer where the shape has one and the word where it does not -- so a
sweep can say whether the rule and either reading ever part company.  They
agreed on all 107 containers where both could be taken on 2026-09-06.

Reading only.  Nothing here writes a saved game or touches the player's disks.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import areas, dos  # noqa: E402
from goldbox import dos_savegame as sg  # noqa: E402
from tools import dossavcensus  # noqa: E402

#: The three titles whose container holds a `u16le` variable array at Pool of
#: Radiance's offsets.  Pools of Darkness' 1364-byte container has a byte-wide
#: array based at 0 and none of these addresses, so it is not swept: a number
#: read there would be a plausible-looking lie
#: (`goldbox/dos_savegame.py`, `SAVE_POOLS_OF_DARKNESS`).
SHAPES = (sg.SAVE_POOL_OF_RADIANCE,
          sg.SAVE_CURSE_OF_THE_AZURE_BONDS,
          sg.SAVE_SECRET_OF_THE_SILVER_BLADES)

#: Where a saved game might be, beyond `dossavcensus`' own archive roots.
#: `~/wish-specimens` is the tree that outlives an emulator slot
#: (`.claude/rules/testing.md`); `work/` is a run's output and half of what is
#: there today will be gone tomorrow, which is the reason this sweep gets
#: written down rather than re-typed.
EXTRA = ("work", "~/wish-specimens", "~/dos_por_play")

#: The words a never-adventured container holds at zero and a played one does
#: not, by the census this tool takes.  `$49F2` and `$49C5` are in the list
#: because they are what the import reads, not because they discriminate --
#: Pool of Radiance holds 0 in both while standing in New Phlan.
WORDS = (("$49C5 map", 0x49C5), ("$49E6 indoors", 0x49E6),
         ("$49F2 area", 0x49F2), ("$49FD", 0x49FD), ("$49FE", 0x49FE),
         ("$4FE1", 0x4FE1), ("$5012 disk", 0x5012), ("$503E party", 0x503E))

#: `$4FE1` = 0 is the never-adventured reading.  `goldbox/dos_savegame.py`'s
#: `SAVGAM_CONSTANTS` says "255 in every specimen" of this address, measured
#: over four Pool of Radiance containers; this sweep sees 255 in 57 played
#: containers, 16 in 41 and 8 in 3, so the constant is what a conversion
#: writes rather than what every save holds.  What survives that correction is
#: the part used here: it is never 0 once the party has been in the world.
NEVER_ADVENTURED_WORD = 0x4FE1


def roots(extra: list[str] | None = None) -> list[pathlib.Path]:
    where = [pathlib.Path(p).expanduser() for p in (extra or EXTRA)]
    repo = pathlib.Path(__file__).resolve().parent.parent
    return [p if p.is_absolute() else repo / p for p in where]


def never_adventured(save: bytes, shape: sg.DosSaveShape,
                     by: str = "buffer") -> bool | None:
    """Was this container saved before the party began adventuring?

    `None` where the chosen test cannot be taken -- Silver Blades has no
    script buffer -- so a caller cannot mistake "cannot tell" for "no".
    """
    if by == "rule":
        return dos.never_adventured(save, shape)
    if by == "word":
        return sg.word(save, NEVER_ADVENTURED_WORD, shape) == 0
    span = shape.script_buffer
    if span is None:
        return None
    return not any(save[span[0]:span[1]])


def describe(path: pathlib.Path, shape: sg.DosSaveShape, by: str) -> dict:
    save = path.read_bytes()
    span = shape.script_buffer
    return {
        "label": dossavcensus._label(path),
        "path": str(path),
        "title": shape.title,
        "never_adventured": never_adventured(save, shape, by),
        "script_bytes": (sum(1 for b in save[span[0]:span[1]] if b)
                         if span else None),
        "square": list(sg.position(save, shape)),
        "clock": list(sg.clock(save)),
        "party_size": sg.party_size(save, shape),
        "words": {name: sg.word(save, addr, shape) for name, addr in WORDS},
        "hand_built": dossavcensus.hand_built(path),
    }


def sweep(shape: sg.DosSaveShape, extra: list[str] | None = None,
          by: str = "buffer") -> list[dict]:
    paths = dossavcensus.find_saves([p for p in roots(extra) if p.exists()],
                                    shape=shape)
    return [describe(p, shape, by) for p in paths]


def _group(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        key = {True: "never adventured", False: "in the world",
               None: "cannot tell"}[row["never_adventured"]]
        groups[key].append(row)
    return groups


def report(shape: sg.DosSaveShape, rows: list[dict], verbose: bool) -> None:
    place = areas.area_in(0, shape.title)
    print(f"=== {shape.title}: {len(rows)} distinct containers; "
          f"area 0 is {place.name if place else 'not an area of this title'}")
    for key, group in _group(rows).items():
        print(f"  -- {key}: {len(group)}")
        for name, _ in WORDS:
            seen = collections.Counter(r["words"][name] for r in group)
            print(f"     {name:<14} "
                  f"{', '.join(f'{v} x{n}' for v, n in seen.most_common())}")
        squares = collections.Counter(tuple(r["square"]) for r in group)
        print(f"     square         "
              f"{', '.join(f'{s} x{n}' for s, n in squares.most_common(4))}")
        zeroed = sum(1 for r in group if not any(r["clock"]))
        print(f"     clock 00:00    {zeroed} of {len(group)}")
        if verbose:
            for r in sorted(group, key=lambda r: r["label"]):
                print(f"       {r['label']:<44} {r['path']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("extra", nargs="*",
                    help="Extra directories to sweep, replacing the defaults")
    ap.add_argument("--by", choices=("buffer", "word", "rule"),
                    default="buffer",
                    help="Which test names a never-adventured save: the "
                         "staged script (default), $4FE1, or the rule the "
                         "import applies (goldbox.dos.never_adventured)")
    ap.add_argument("--title", help="One title's key, e.g. "
                                    "curse-of-the-azure-bonds")
    ap.add_argument("--list", action="store_true",
                    help="Name every container in each group")
    ap.add_argument("--json", action="store_true", help="Machine-readable")
    args = ap.parse_args(argv)

    shapes = SHAPES
    if args.title:
        shapes = tuple(s for s in SHAPES if s.key == args.title)
        if not shapes:
            ap.error(f"no title keyed {args.title!r} has a word array")

    out = {}
    for shape in shapes:
        rows = sweep(shape, args.extra or None, args.by)
        out[shape.key] = rows
        if not args.json:
            report(shape, rows, args.list)
    if args.json:
        json.dump(out, sys.stdout, indent=2)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
