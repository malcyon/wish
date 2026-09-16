#!/usr/bin/env python3
"""Every `ADDNPC` in Pool of Radiance's area scripts, and what gates it.

`#533 (A joined NPC has no combat icon, and the editor draws the absence as a
black rectangle)` wanted one thing: which joinable NPC can a driven session
reach most cheaply, so that a *completed* join can be watched in the running
game. The answer had been assumed to be Dirten, whose `ADDNPC` sits behind the
Bishop of Tyr's commission and therefore behind clearing Sokal Keep. It is not.

    eclnpc.py census          every reachable ADDNPC, with the MON record's name
    eclnpc.py gate ECL0B 9FEB every block that reaches one, walking backward
    eclnpc.py gaps            the completeness check on the census

## What `census` does

`tools/eclwalk.py` walks each script from its five entry `GOTO`s, following
both arms of every condition, so a statement it reaches is a statement the
engine can reach. Every `ADDNPC` (opcode `$36`) it reached is listed with:

* the **record id**, resolved through the script's own table when the operand
  is a variable rather than a literal -- `ECL0B $9FEB` takes both its operands
  from a `GETTABLE`, and the table is eight bytes at the tail of the file;
* the **name in that `MON` record**, read off the disk at record offset 0. The
  name is the game's own text, so it prints only here, in a terminal, and not
  into `docs/`, a README, a commit message or an issue;
* the **second operand**, which `DUNGEON $273D-$2759` folds to `(n >> 1) | $80`
  and stores as the joined character's NPC byte at record `0x0B8`. For the
  eight Training Hall hirelings it is `50 + 5n`, which is the share of treasure
  the screen offers -- one share through four.

## Why `gaps` exists

The walk reaches about 98% of all thirty scripts' bytes, the rest being the
data tables opcode `$2A` indexes, so "the walk found no more" is not by itself
a census. `gaps` scans every byte the walk never reached for one that decodes
as an `ADDNPC`, and prints how many it found. As of 2026-09-15 that is **0 of
3,481 unreached bytes**, which is what makes the census complete rather than
merely thorough.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from goldbox.d64 import D64  # noqa: E402
from tools import eclwalk  # noqa: E402

ADDNPC = 0x36
GETTABLE = 0x2A
BASE = eclwalk.BASE

#: An `ADDNPC` whose record id is computed rather than written down, and the
#: `GETTABLE` base and length that resolve it. Keyed by script and address so a
#: second computed site cannot silently inherit this one's table.
COMPUTED = {
    ("ECL0B", 0x9FEB): (0xA23F, 8),
}


def _mon_names() -> dict[int, list[tuple[str, str]]]:
    """Every `MON<id>` on every side, by id, with the side and its name."""
    out: dict[int, list[tuple[str, str]]] = {}
    for side in ["POOLBOOT"] + [f"POOL{n}" for n in range(1, 9)]:
        path = eclwalk.DISKS / f"{side}.D64"
        if not path.exists():
            continue
        image = D64.open(path)
        for entry in image.iter_directory():
            name = entry.name.decode("latin1").rstrip("\xa0 ")
            if not name.startswith("MON"):
                continue
            try:
                ident = int(name[3:], 16)
            except ValueError:
                continue
            body = image.read_file(name)[2:]
            text = bytes(body[:16]).split(b"\x00")[0].decode("latin1")
            out.setdefault(ident, []).append((side, text.strip()))
    return out


def _table(body: bytes, at: int, length: int) -> list[int]:
    start = at - BASE
    return list(body[start:start + length])


def _sites(machine, name, side, body):
    """Every reached `ADDNPC` in one script, with its resolved record ids."""
    script = eclwalk.Script(machine, name, side, body)
    for statement in script.ordered():
        if statement.op != ADDNPC:
            continue
        (kind, ident), (share_kind, share) = statement.operands
        if kind == 0x00:
            yield statement, [ident], share if share_kind == 0x00 else None
            continue
        table = COMPUTED.get((name, statement.address))
        if table is None:
            yield statement, None, None
            continue
        yield statement, _table(body, *table), None


def cmd_census(_args):
    machine = eclwalk.Machine()
    names = _mon_names()
    total = 0
    for name, (side, body) in eclwalk.scripts().items():
        rows = list(_sites(machine, name, side, body))
        if not rows:
            continue
        area = _area_name(name)
        print(f"\n{name} on {side} -- {area}")
        for statement, idents, share in rows:
            total += 1
            print(f"  ${statement.address:04X}  {statement}")
            if idents is None:
                print("      record id computed, and no table is recorded "
                      "for this site")
                continue
            for n, ident in enumerate(idents):
                found = names.get(ident, [])
                shown = "; ".join(f"{s}/MON{ident:02X} {t!r}" for s, t in found)
                stored = "" if share is None else \
                    f"   NPC byte ${(share >> 1) | 0x80:02X} from {share}"
                index = "" if len(idents) == 1 else f"[{n}] "
                print(f"      {index}id {ident:3d}: {shown or '(no MON file)'}"
                      f"{stored}")
    print(f"\n{total} reached ADDNPC statements")


def _area_name(script):
    from goldbox import areas
    try:
        ident = int(script[3:], 16)
    except ValueError:
        return "?"
    for area in areas.AREAS:
        if area.id == ident:
            return area.name or f"area {ident}"
    return f"area {ident}"


def cmd_gaps(_args):
    """Any byte the walk never reached that decodes as an `ADDNPC`."""
    machine = eclwalk.Machine()
    unreached = found = 0
    for name, (side, body) in eclwalk.scripts().items():
        script = eclwalk.Script(machine, name, side, body)
        covered = bytearray(len(body))
        for statement in script.statements.values():
            for i in range(statement.at, statement.end):
                covered[i] = 1
        unreached += sum(1 for c in covered if not c)
        for i, b in enumerate(body):
            if b != ADDNPC or covered[i]:
                continue
            statement = eclwalk.decode(machine, body, i)
            if statement is None or len(statement.operands) != 2:
                continue
            if any(k not in (0x00, 0x01) for k, _ in statement.operands):
                continue
            if eclwalk.decode(machine, body, statement.end) is None:
                continue
            found += 1
            print(f"{name} ${statement.address:04X}  {statement}")
    print(f"{unreached} bytes unreached across the thirty scripts; "
          f"{found} of them decode as an ADDNPC")


def cmd_gate(args):
    """Every block that reaches a statement, walking backward."""
    machine = eclwalk.Machine()
    side, body = eclwalk.scripts()[args.script]
    script = eclwalk.Script(machine, args.script, side, body)
    target = int(args.address, 16) - BASE
    if target not in script.statements:
        raise SystemExit(f"the walk never reached ${BASE + target:04X}")

    predecessors: dict[int, list[int]] = {}
    for statement in script.ordered():
        for successor, _ in script._successors(statement):
            if successor in script.statements:
                predecessors.setdefault(successor, []).append(statement.at)
    entries = {e for e in script.entries if e is not None}

    seen: set[int] = set()
    frontier = [target]
    for level in range(args.depth):
        following = []
        for at in frontier:
            block = script.block_of(script.statements[at])
            head = block[0].at
            if head in seen:
                continue
            seen.add(head)
            print(f"\n-- {level} steps back: "
                  f"${BASE + head:04X}..${BASE + at:04X}")
            for statement in block:
                if statement.at > at:
                    break
                mark = "   <= a script entry" if statement.at in entries else ""
                print(f"   ${statement.address:04X}  {statement}{mark}")
            following.extend(predecessors.get(head, []))
        frontier = following
        if not frontier:
            break


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("census").set_defaults(run=cmd_census)
    sub.add_parser("gaps").set_defaults(run=cmd_gaps)
    gate = sub.add_parser("gate")
    gate.add_argument("script")
    gate.add_argument("address")
    gate.add_argument("--depth", type=int, default=10)
    gate.set_defaults(run=cmd_gate)
    args = parser.parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    main()
