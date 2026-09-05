#!/usr/bin/env python3
"""Print the statements a party walks through on its way to one exit.

`#207 (Run an exit's own handler before Fast Travel warps out)` asks Fast
Travel to run the exit's own handler instead of jumping past it, and the
question that decides whether that is safe for a given exit is not what the
handler's last block writes -- `tools/eclwalk.py exits` already prints that --
but **what the whole route does**, from the entry the game dispatches through
down to the `NEWECL`.  `ECL07 $A904`'s last block is six `SAVE`s and a
`NEWECL 0`; its route is the endgame battle with Tyranthraxus.

`tools/eclexitkinds.py` classifies all 79 exits and counts the features on
each route.  This prints the route itself, so a feature count of `combat` can
be read rather than believed.

    exitroute.py ECL07 A904      one exit, by script and address
    exitroute.py ECL0D           every exit in one script

The route is the **shortest** one from the entry to the `NEWECL`, which is
what makes the feature counts a lower bound: a longer route through the same
handler may do more.  Where several entries reach the exit the lowest is
used, the same rule `eclexitkinds.py` applies, and the entry is named in the
header line.

**A condition's polarity is not shown, and reading one off a route is how to
get it backwards.**  `eclwalk` gives an `IF` two successors -- the statement
it guards and the one after that -- and the walk takes whichever reaches the
exit first, so a printed `IF= / GOTO` may be the arm the player does *not*
take.  `ECL00`'s edge gate is the worked example: the route prints
`COMPARE [$6DD5], 0 / IF=` and then the statements that leave the area, which
reads as "leave when the step stays on the map".  The listing has
`$9941 GOTO [$9965]` between them, jumping *past* the exit, so the area is
left when `$6DD5` is **non**-zero.  Read `eclwalk.py listing` before
concluding anything about which way a test goes.

No string operand is printed as text, for the reason `tools/eclwalk.py`
gives: the game's words are its own.  Lengths are printed instead.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from goldbox.geo import Geo  # noqa: E402
from tools import eclexitkinds as K  # noqa: E402
from tools import eclwalk as W  # noqa: E402


#: What each statement on a route would look like to a player, using the same
#: opcode sets `eclexitkinds.py` counts with so the two cannot drift.
def marker(statement) -> str:
    op = statement.op
    if op in K.MENUS:
        return "menu"
    if op in K.TEXT:
        return "text"
    if op == K.LOADCHAR:
        return "loadchar"
    if op == 0x24:
        return "COMBAT"
    if op == W.NEWECL:
        return "exit"
    if op == K.SAVE and len(statement.operands) == 2:
        kind, value = statement.operands[1]
        if kind != 0:
            if value in K.POSITION:
                return "position"
            if value in K.FLAGS:
                return "flag"
            if value in K.MEMBERSHIP:
                return "membership"
    return ""


def geo_for(name: str):
    _, body = W._file("GEO" + name[3:])
    if body is None:
        return None
    try:
        return Geo.from_bytes(body)
    except Exception:                           # noqa: BLE001
        return None


def route_for(script, row):
    """The shortest route to `row`'s exit, and the entry it starts from."""
    entries = {e: off for e, off in enumerate(script.entries)
               if off is not None}
    for e in row["entries"]:
        parent = K.routes(script, entries[e])
        at = (row["at"] - W.BASE)
        if at in parent:
            return e, K.route_to(parent, at)
    return None, []


def report(machine, name: str, wanted: str | None) -> int:
    side, body = W._file(name)
    if body is None:
        print(f"{name}: not on the disks", file=sys.stderr)
        return 1
    script, rows = K.analyse(machine, name, side, body, geo_for(name))
    found = 0
    for row in rows:
        label = f"{row['at']:04X}"
        if wanted and label.upper() != wanted.upper().lstrip("$"):
            continue
        found += 1
        entry, path = route_for(script, row)
        where = f"area {row['target']}" if row["target"] is not None \
            else "a computed area"
        squares = "" if row["squares"] is None \
            else f", squares {row['squares']}"
        print(f"{name} ${row['at']:04X} -> {where}: {row['kind']}, "
              f"entry {entry}, {len(path)} statements{squares}")
        for at in path:
            st = script.statements[at]
            tag = marker(st)
            print(f"  ${W.BASE + at:04X}  {str(st):46s} {tag}")
        print()
    if wanted and not found:
        print(f"{name} has no NEWECL at ${wanted.lstrip('$')}",
              file=sys.stderr)
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("script", help="ECL00 ... ECL1E")
    parser.add_argument("address", nargs="?",
                        help="the NEWECL's address, e.g. A904; default all")
    args = parser.parse_args(argv)
    if not W.DISKS or not W.DISKS.exists():
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    return report(W.Machine(), args.script, args.address)


if __name__ == "__main__":
    raise SystemExit(main())
