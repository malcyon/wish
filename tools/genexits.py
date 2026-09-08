#!/usr/bin/env python3
"""Generate the direct-exit table `automap/fasttravel.py` needs to run a
departing script's own handler before Fast Travel warps out.

`#207 (Run an exit's own handler before Fast Travel warps out)` is the
ticket. Walking out of the Kobold Caves runs `ECL0D $9A9D`, which asks the
player and, if they agree, removes Princess Fatima from the party; Fast
Travel used to enter `NEWECL` at its own tail and skip that script entirely,
so a party that fast-travelled out kept her. `tools/exitreentry.py` proved
across three live sessions that the game's own dispatch can be re-entered
from outside and runs the handler exactly the way a step would
(`docs/150-departing-prologues.md`); this tool is what turns
`tools/eclexitkinds.py`'s per-exit analysis into the one fact `FastTravel`
needs at each departure: which square to stand on and which of `DUNGEON`'s
two dispatch points to re-enter at.

**Only exits Fast Travel can use without a second hop.** A row exists for
`(from_area, to_area)` only where one of `from_area`'s own scripted exits
already leads to `to_area` -- the same neighbour a walking party would
reach. A Fast Travel to anywhere else still enters `NEWECL` at its tail, the
way it always has; running a handler that leads somewhere else and then
warping the rest of the way needs a wait for the game to go idle again
between the two, which is a different piece of work (`#207`'s own thread,
"a two-hop trip with a wait between hops").

**Which square, where an exit's route lists several.** Every square on a
route triggers the *same* handler -- `#207`'s analysis: `ECL0D`'s two
`NEWECL 27`s are one handler reached from two squares, the branch inside it
is the party's own contents and the player's `YES`/`NO` -- so picking among
several is not a functional choice. This takes the first the route lists,
for a determinstic table; for a gated exit (entry 0, `$10EC`'s wall test)
that also has to be the first square `Geo.is_passable` confirms open on the
side that leaves the map, since `$6DD5` never sets for a step through a
wall (measured against a live machine, `#207`).

    genexits.py                          the table, as automap/fasttravel.py
                                          would carry it
    genexits.py --report PATH.md         the same, plus a report of the
                                          exits it could not place a row for

Reads the scripts off the player's own disks, the way `tools/eclwalk.py` and
`tools/eclexitkinds.py` do; nothing here is committed game data, only the
few integers -- an area id, an entry number, a square -- that the generated
table carries, the same shape `automap/fasttravel.py`'s address rows already
are.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from goldbox import areas as A  # noqa: E402
from goldbox.geo import Geo  # noqa: E402
from tools import eclwalk as W  # noqa: E402
from tools.eclexitkinds import analyse  # noqa: E402

TITLE = "Pool of Radiance"

#: Which of `tools/eclexitkinds.py`'s kinds carry a concrete departure
#: square, and how `DUNGEON` dispatches each: entry 0 (the forward key,
#: `$0978`) or entry 1 (the per-square check that runs after every step
#: lands, `$0957`). `gated` marks the two kinds whose route passes through
#: `$10EC`'s wall test, so the square chosen for them must be one
#: `Geo.is_passable` confirms open in the direction that leaves the map.
#: `entryN`, `entry1-unconditional` and any kind with no `ONGOTO` index are
#: left out: the first has no square or edge a walking party can stand on
#: at all (`ECL0B $A20F`, camping interrupted), and the second fires from
#: every square in the area, which is not a departure Fast Travel chooses by
#: standing anywhere in particular.
KINDS = {
    "edge": (0, True),
    "edge+square": (0, True),
    "square-via-entry0": (0, False),
    "square": (1, False),
}


def area_by_ecl(title: str = TITLE) -> dict[str, int]:
    return {row.ecl: row.id for row in A.areas_for_title(title)}


def outward_facings(x: int, y: int) -> list[int]:
    """Which directions actually leave the 16x16 grid from `(x, y)`.

    `goldbox.geo`'s own `NORTH, EAST, SOUTH, WEST = 0, 1, 2, 3`. A corner
    square can leave two ways; either is fine, so both are offered in a
    fixed order and the first `Geo.is_passable` confirms open wins.
    """
    out = []
    if y == 0:
        out.append(0)
    if x == 15:
        out.append(1)
    if y == 15:
        out.append(2)
    if x == 0:
        out.append(3)
    return out


def pick_square(geo: Geo | None, squares, gated: bool):
    """One square from a route's candidates, or None if none will do.

    Every square on the route triggers the same handler (see the module
    docstring), so the first is as good as any -- except for a gated exit,
    where it also has to be a square `Geo.is_passable` says is open on the
    side that leaves the map, since `$10EC` never sets `$6DD5` for a step
    through a wall.
    """
    for x, y in squares:
        if not gated:
            return (x, y)
        if geo is None:
            continue
        for facing in outward_facings(x, y):
            if geo.is_passable(x, y, facing):
                return (x, y, facing)
    return None


def build(title: str = TITLE):
    """`{(from_area, to_area): (entry, square)}`, and the exits left out and
    why, as `(script, address, target, reason)`."""
    if not W.DISKS or not W.DISKS.exists():
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    by_ecl = area_by_ecl(title)
    machine = W.Machine()
    rows: dict[tuple[int, int], tuple[int, tuple]] = {}
    skipped: list[tuple[str, str, object, str]] = []
    for name, (side, body) in W.scripts().items():
        from_area = by_ecl.get(name)
        if from_area is None:
            skipped.append((name, "-", None, "no area table row for this script"))
            continue
        geo = None
        _gside, gbody = W._file("GEO" + name[3:])
        if gbody is not None:
            try:
                geo = Geo.from_bytes(gbody)
            except Exception:                   # noqa: BLE001
                geo = None
        _script, analysed = analyse(machine, name, side, body, geo)
        for r in analysed:
            at = f"${r['at']:04X}"
            if r["target"] is None:
                skipped.append((name, at, r["target"], "computed target"))
                continue
            if r["kind"] not in KINDS:
                skipped.append((name, at, r["target"], f"kind {r['kind']}"))
                continue
            if not r["squares"]:
                skipped.append((name, at, r["target"], "no square on the route"))
                continue
            key = (from_area, r["target"])
            if key in rows:
                continue  # a second route to the same pair; see the docstring
            entry, gated = KINDS[r["kind"]]
            square = pick_square(geo, r["squares"], gated)
            if square is None:
                skipped.append((name, at, r["target"],
                                "no square is open on the side that leaves "
                                "the map"))
                continue
            rows[key] = (entry, square)
    return rows, skipped


def render(rows) -> str:
    lines = [
        "#: Generated by `tools/genexits.py` from the game's own scripts and "
        "maps.",
        "#: Pool of Radiance only -- the re-entry addresses this rests on "
        "(`after_step`,",
        "#: `forward_key`, `redraw`, `saved_sp`, `main_loop_return`) have "
        "been measured",
        "#: only there. One row per `(from_area, to_area)` pair reachable by "
        "one of",
        "#: `from_area`'s own scripted exits -- see this module's docstring "
        "for what a",
        "#: destination with no row here still does.",
        "EXIT_ROUTES: Mapping[tuple[int, int], ExitRoute] = MappingProxyType({",
    ]
    for (frm, to), (entry, square) in sorted(rows.items()):
        lines.append(f"    ({frm}, {to}): ExitRoute({entry}, {square!r}),")
    lines.append("})")
    return "\n".join(lines)


def render_report(rows, skipped) -> str:
    lines = [f"# `tools/genexits.py`, {len(rows)} direct routes", ""]
    lines.append("| from | to | entry | square |")
    lines.append("|---|---|---|---|")
    for (frm, to), (entry, square) in sorted(rows.items()):
        lines.append(f"| {frm} | {to} | {entry} | {square} |")
    lines.append("")
    lines.append(f"## {len(skipped)} exits with no row, and why")
    lines.append("")
    lines.append("| script | at | target | reason |")
    lines.append("|---|---|---|---|")
    for name, at, target, reason in skipped:
        lines.append(f"| {name} | {at} | {target} | {reason} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--report", default=None,
                   help="write the routes and the skipped exits to this path")
    args = p.parse_args(argv)
    rows, skipped = build()
    print(render(rows))
    print(f"# {len(rows)} direct routes, {len(skipped)} exits left out",
          file=sys.stderr)
    if args.report:
        out = pathlib.Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_report(rows, skipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
