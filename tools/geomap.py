#!/usr/bin/env python3
"""Render the GEO map files, and place a party on one.

    tools/geomap.py --list                       every GEO file and its stats
    tools/geomap.py GEO04                        one floor plan
    tools/geomap.py GEO04 --save PORSAVE11.D64   with the party marked
    tools/geomap.py --find PORSAVE11.D64         which maps the party could be on

`--find` is the anchor problem: we know where the party is standing but not which
map it is standing on. It reports every GEO file where that square exists and the
party is not inside a wall, which narrows 29 files to a handful.
"""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from automap.paths import disk_globs, find_disks  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.geo import (  # noqa: E402
    DIRECTIONS,
    GRID,
    LOCKED,
    SOLID,
    WIZARD_LOCKED,
    Geo,
    load_geo_files,
)
from goldbox.savegame import SaveGame0  # noqa: E402

DISKS = os.environ.get("POR_DISKS", str(find_disks() or ""))


def game_disks(root: str = DISKS) -> list[str]:
    """Every game disk under `root`, each of them once.

    `disk_globs` gives an upper- and a lower-cased pattern, and on a
    case-insensitive filesystem both match the same file -- so dedupe, or every
    disk is read twice.
    """
    seen: dict[str, str] = {}
    for pattern in disk_globs():
        for path in glob.glob(os.path.join(root, pattern)):
            seen.setdefault(os.path.normcase(os.path.abspath(path)), path)
    return sorted(seen.values())


def all_maps(pattern: str | None = None) -> dict[str, Geo]:
    found: dict[str, Geo] = {}
    for path in game_disks():
        for name, geo in load_geo_files(path).items():
            found.setdefault(name, geo)
    if pattern:
        found = {k: v for k, v in found.items() if pattern.upper() in k}
    return dict(sorted(found.items()))


def stats(geo: Geo) -> str:
    walls = doors = locked = indoor = 0
    for y in range(GRID):
        for x in range(GRID):
            indoor += geo.is_indoor(x, y)
            for d in DIRECTIONS:
                if geo.wall(x, y, d):
                    walls += 1
                    b = geo.barrier(x, y, d)
                    doors += b not in (SOLID,)
                    locked += b in (LOCKED, WIZARD_LOCKED)
    agree, total = geo.reciprocity()
    return (f"walls {walls:4d}  doors {doors:3d}  locked {locked:3d}  "
            f"indoor {indoor:3d}/256  reciprocity {agree}/{total}")


def party_of(save_path: str) -> tuple[int, int, int]:
    disk = D64.open(save_path)
    sg = SaveGame0.from_prg(disk.read_file(b"SAVEDGAME0"))
    p = sg.party
    return p.x, p.y, p.facing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?", help="a GEO file name, or part of one")
    ap.add_argument("--list", action="store_true", help="list every map")
    ap.add_argument("--save", help="mark this save's party position")
    ap.add_argument("--find", help="report which maps this save could be on")
    args = ap.parse_args()

    if args.find:
        x, y, facing = party_of(args.find)
        print(f"party at ({x}, {y}) facing {facing}")
        for name, geo in all_maps().items():
            if not (0 <= x < GRID and 0 <= y < GRID):
                print(f"({x}, {y}) is outside a {GRID}x{GRID} grid")
                return 1
            open_sides = sum(geo.is_passable(x, y, d) for d in DIRECTIONS)
            if open_sides:
                print(f"  {name}  {open_sides} ways out  "
                      f"{'indoor' if geo.is_indoor(x, y) else 'outdoor'}")
        return 0

    maps = all_maps(args.name)
    if not maps:
        print(f"no GEO file matching {args.name!r} under {DISKS}", file=sys.stderr)
        return 1

    if args.list or not args.name:
        for name, geo in maps.items():
            print(f"{name:8s} {stats(geo)}")
        return 0

    mark = {}
    if args.save:
        x, y, facing = party_of(args.save)
        mark[(x, y)] = "NESW"[facing] if 0 <= facing < 4 else "@"
        print(f"party at ({x}, {y}) facing {'NESW'[facing]}")
    for name, geo in maps.items():
        print(f"\n{name}  {stats(geo)}\n")
        print(geo.to_text(mark=mark))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
