"""Read `ECL10`'s arm 2 (the `14,11` shop) and `GEO10`'s own map.

Belongs to #334 (The session driver cannot fight in Curse or Silver Blades, and says the party is not in a fight while it is standing on the combat floor).

Static only -- no emulator. Two questions:

1. What does the `YES NO` bar at `$9B20` actually do on each arm, and is
   there anything on the `NO` path that moves the party off `14,11`? A live
   run on 2026-09-17 saw `NO` eject the party back to `13,11` three times
   out of three, which nothing on the thread predicted.
2. Is there any route over `GEO10`'s own passability from the party's
   square to `15,11`/`15,12` that never enters `14,11`?

Prints statement lengths for strings, never their text, the same way
`tools/areas/eclwalk.py` and `tools/areas/eclcensus.py` do.

Run: `.venv/bin/python tools/secret_of_the_silver_blades/ssbarm2route.py [--from HEX] [--to HEX] [--also
LO:HI ...]`. Reads the Silver Blades disks `tools/registry/gamedisks.py` finds and
`$WISH_SPECIMENS/por-c64/WISH-SPEC-ssb-d-engine-resave-walked.D64`
for the party's square; writes nothing.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_port as G  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.geo import Geo  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402
from tools.areas import (  # noqa: E402
    eclcensus,
    eclwalk,
)
from tools.registry import (  # noqa: E402
    gamedisks,
    specimens,
)

SAVE = str(specimens.tree_root() / "por-c64"
            / "WISH-SPEC-ssb-d-engine-resave-walked.D64")
NAMES = dict(eclwalk.NAMES)
NAMES.setdefault(0x2B, "HORIZMENU")
NAMES.setdefault(0x15, "VERTMENU")


def render(machine, body, base, statement) -> str:
    """One statement, operands rendered, strings as their length."""
    parts = []
    i = statement.at + 1
    for kind, value in statement.operands:
        if kind == 0x80:
            parts.append(f"str({value})")
            i += 2 + value
        elif kind == 0x00:
            parts.append(f"#{value}")
            i += 2
        else:
            parts.append(f"[${value:04X}]")
            i += 3
    name = NAMES.get(statement.op, f"OP${statement.op:02X}")
    return (f"+${statement.at:04X}  ${base + statement.at:04X}  "
            f"{name:<10} " + ", ".join(parts))


def listing(machine, body, base, found, lo, hi, label):
    print(f"\n=== {label}: ${lo:04X}-${hi:04X} ===")
    for at in sorted(found):
        addr = base + at
        if lo <= addr <= hi:
            print(render(machine, body, base, found[at]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="lo", default="8796")
    ap.add_argument("--to", dest="hi", default="8AFF")
    ap.add_argument("--also", nargs="*", default=["9B20:9B60", "9638:96FF"])
    args = ap.parse_args(argv)

    game = G.SECRET_OF_THE_SILVER_BLADES
    disks = str(gamedisks.find(game.key))
    machine, base, bodies, sides, _ = eclcensus.load_port(disks, game, None)
    body = bodies["ECL10"]
    found = eclcensus.walk(machine, body, base)
    print(f"ECL10 on side {sides['ECL10']}, {len(body)} bytes, base ${base:04X}, "
          f"{len(found)} statements reached")

    listing(machine, body, base, found, int(args.lo, 16), int(args.hi, 16),
            "arm 2 and what follows")
    for spec in args.also:
        lo, hi = (int(p, 16) for p in spec.split(":"))
        listing(machine, body, base, found, lo, hi, "extra")

    # -- GEO10 -------------------------------------------------------------
    _, save0, _ = load_save(D64.open(SAVE))
    name = save0.area_file
    geo = None
    for side in sorted(pathlib.Path(disks).glob("*.[dD]64")):
        image = D64.open(side)
        entry = image.find(name.encode() if isinstance(name, str) else name)
        if entry is not None:
            geo = Geo.from_bytes(image.read_file(entry))
            break
    print(f"\n=== {name} ===")
    if geo is None:
        print("  not found")
        return 1
    pos = save0.party
    party = (pos.x, pos.y, getattr(pos, "facing", 0))
    print(f"  the save's own square: {party} ({pos})")

    print("\n  attribute (script id) per square, x across 0-15:")
    print("      " + " ".join(f"{x:>3}" for x in range(16)))
    for y in range(16):
        row = []
        for x in range(16):
            row.append(f"{geo.script_id(x, y):>3}")
        print(f"  y{y:<3} " + " ".join(row))

    print("\n  passability out of the squares around the corridor "
          "(N E S W, . = blocked):")
    for y in range(9, 14):
        for x in range(12, 16):
            bits = "".join(d if geo.is_passable(x, y, f) else "."
                           for f, d in ((0, "N"), (1, "E"), (2, "S"), (3, "W")))
            print(f"    ({x:2},{y:2}) attr {geo.script_id(x, y):>3}  {bits}")

    # BFS with 14,11 banned entirely (not just one edge)
    import collections
    STEP = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}

    def bfs(start, banned_squares=()):
        prev = {start: None}
        q = collections.deque([start])
        while q:
            x, y = q.popleft()
            for f, (dx, dy) in STEP.items():
                if not geo.is_passable(x, y, f):
                    continue
                nxt = (x + dx, y + dy)
                if not (0 <= nxt[0] < 16 and 0 <= nxt[1] < 16):
                    continue
                if nxt in prev or nxt in banned_squares:
                    continue
                prev[nxt] = ((x, y), f)
                q.append(nxt)
        return prev

    start = (party[0], party[1])
    for banned, label in (((), "no ban"), (((14, 11),), "14,11 banned")):
        prev = bfs(start, banned)
        print(f"\n  routes from {start}, {label}: "
              f"{len(prev)} squares reachable")
        for target in ((13, 11), (14, 11), (15, 10), (15, 11), (15, 12)):
            if target in prev:
                route, here = [], target
                while prev[here]:
                    (px, py), f = prev[here]
                    route.append((here, f))
                    here = (px, py)
                route.reverse()
                print(f"    {target}: {len(route)} steps  "
                      + " ".join(f"{f}->{sq[0]},{sq[1]}" for sq, f in route))
            else:
                print(f"    {target}: UNREACHABLE")

    # Which squares can reach 15,12 at all -- its in-edges
    print("\n  squares with a passable edge INTO the corridor squares:")
    for target in ((15, 10), (15, 11), (15, 12)):
        ins = []
        for x in range(16):
            for y in range(16):
                for f, (dx, dy) in STEP.items():
                    if (x + dx, y + dy) == target and geo.is_passable(x, y, f):
                        ins.append(((x, y), f))
        print(f"    into {target}: {ins}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
