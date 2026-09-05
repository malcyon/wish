#!/usr/bin/env python3
"""Say how each exit is reached -- off an edge, or by stepping on a square --
and what a player would notice if its handler ran.

`#207 (Run an exit's own handler before Fast Travel warps out)` needs an
answer to "which handler" before anything can run one, and the area pair does
not give it: `ECL0D` has two `NEWECL 27`s.  What does give it is the way
`DUNGEON` reaches a script (`docs/150-departing-prologues.md`):

* **entry 0** runs on the forward key, after `$10EC` has counted into `$6DD5`
  whether the step would leave the 16x16 map.  An exit guarded by
  `COMPARE [$6DD5], 0` is an **edge** exit: any edge square, facing out.
* **entry 1** runs after every step lands and on LOOK, masks the square's
  plane-`$200` byte (`$C04F`) and `ONGOTO`s by the result.  An exit under one
  of its indices is a **square** exit, and the squares carrying that id in
  the `GEO` are where it fires.

So this walks each script from each of its five entries, finds the shortest
route to every `NEWECL`, and reports the kind, the `ONGOTO` index and the
squares, and the statements on the route that a player would notice: a
menu, printed text, a `LOADCHAR`, a quest flag, a position write.

Six kinds come out of the 79 exits on the disks here. `edge` is entry 0
gated on `$6DD5` with no `ONGOTO` on the route; `square` is entry 1's
`ONGOTO`; `edge+square` is entry 0, gated *and* carrying an `ONGOTO`;
`square-via-entry0` is entry 0's `ONGOTO` with no gate;
`entry1-unconditional` is entry 1 with neither. The sixth, `entryN`, is the
other three entries -- 2 before camping, 3 camp interrupted, 4 after loading
-- which reach a `NEWECL` directly, with no edge or square dispatch of their
own: `ECL0B`'s `$A20F` is the one exit only entry 3 reaches, run when camping
is interrupted rather than off any square or edge a walking party can stand
on.

    eclexitkinds.py            every script
    eclexitkinds.py ECL0D      one

No string is printed as text, for the reason `tools/eclwalk.py` gives.
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from goldbox.geo import Geo  # noqa: E402
from tools import eclwalk as W  # noqa: E402

#: The two menus, and the text printers, by opcode.  `$2B` and `$15` carry a
#: count operand (`W.COUNTED`); `$12` prints an inline string; `$0E` prints
#: a numbered message and `$0F` a numbered menu line -- both PROBABLE, from
#: where they sit in the exits' routes, and named here only as "text".
MENUS = {0x2B, 0x15, 0x29}
TEXT = {0x12, 0x0E}
EDGE_FLAG, ATTR, ONCHOICE = 0x6DD5, 0xC04F, 0x6E79
SAVE, LOADCHAR, CALL, COMPARE = 0x09, 0x0A, 0x2D, 0x03
#: `$24 COMBAT`, `docs/128-guide-and-scripting.md`; `eclwalk` names it but
#: does not export a constant.
POSITION = {0xC04B, 0xC04C, 0xC04D, 0x49C3, 0x49C4}
FLAGS = range(0x4A20, 0x4B00)
MEMBERSHIP = {0x6B00, 0x6C00}


def routes(script, entry_offset):
    """Shortest route from `entry_offset` to every statement it reaches."""
    parent = {entry_offset: None}
    queue = collections.deque([entry_offset])
    while queue:
        at = queue.popleft()
        st = script.statements.get(at)
        if st is None:
            continue
        for succ, _ in script._successors(st):
            if succ in script.statements and succ not in parent:
                parent[succ] = at
                queue.append(succ)
    return parent


def route_to(parent, at):
    out = []
    while at is not None:
        out.append(at)
        at = parent[at]
    return list(reversed(out))


def ongoto_index(script, path):
    """The `ONGOTO`/`ONGOSUB` on the route and which of its arms was taken."""
    for a, b in zip(path, path[1:]):
        st = script.statements[a]
        if st.op in (W.ONGOTO, W.ONGOSUB):
            fixed = W.COUNTED[st.op]
            for n in range(fixed, len(st.operands)):
                if st.target(n) is not None and st.target(n) - W.BASE == b:
                    return st, n - fixed
    return None, None


def mask_before(script, path):
    """The `AND` mask applied to `$C04F` on the route, or `$7F`."""
    for a in path:
        st = script.statements[a]
        if st.op == 0x2F and any(k != 0 and v == ATTR for k, v in st.operands):
            for k, v in st.operands:
                if k == 0:
                    return v
    return 0x7F


def features(script, path, exit_at):
    seen = set()
    for a in path:
        st = script.statements[a]
        if st.op in MENUS:
            seen.add("menu")
        elif st.op in TEXT:
            seen.add("text")
        elif st.op == LOADCHAR:
            seen.add("loadchar")
        elif st.op == CALL:
            seen.add("call")
        elif st.op == SAVE and len(st.operands) == 2:
            k, v = st.operands[1]
            if k != 0:
                if v in POSITION:
                    seen.add("position")
                elif v in FLAGS:
                    seen.add("flag")
                elif v in MEMBERSHIP:
                    seen.add("membership")
        elif st.op == 0x24:
            seen.add("combat")
    return sorted(seen)


def squares_with(geo, mask, k):
    if geo is None:
        return None
    return [(x, y) for y in range(16) for x in range(16)
            if geo.script_id(x, y, mask) == k]


def analyse(machine, name, side, body, geo):
    script = W.Script(machine, name, side, body)
    entries = script.entries
    parents = {e: routes(script, off) for e, off in enumerate(entries)
               if off is not None}
    rows = []
    for st in script.ordered():
        if st.op != W.NEWECL:
            continue
        target = st.operands[0][1] if st.operands[0][0] == 0 else None
        reach = {e: p for e, p in parents.items() if st.at in p}
        row = {"at": st.address, "target": target, "entries": sorted(reach),
               "kind": "?", "index": None, "squares": None, "features": []}
        if 1 in reach:
            path = route_to(reach[1], st.at)
            og, k = ongoto_index(script, path)
            row["features"] = features(script, path, st.at)
            if og is not None:
                row["kind"] = "square"
                row["index"] = k
                row["squares"] = squares_with(geo, mask_before(script, path), k)
            else:
                row["kind"] = "entry1-unconditional"
        elif 0 in reach:
            path = route_to(reach[0], st.at)
            row["features"] = features(script, path, st.at)
            gated = any(script.statements[a].op == COMPARE and
                        any(k != 0 and v == EDGE_FLAG
                            for k, v in script.statements[a].operands)
                        for a in path)
            og, k = ongoto_index(script, path)
            if gated and og is None:
                row["kind"] = "edge"
            elif og is not None:
                row["kind"] = "edge+square" if gated else "square-via-entry0"
                row["index"] = k
                row["squares"] = squares_with(geo, mask_before(script, path), k)
            else:
                row["kind"] = "entry0-unconditional"
        elif reach:
            e = min(reach)
            path = route_to(reach[e], st.at)
            row["features"] = features(script, path, st.at)
            row["kind"] = f"entry{e}"
        rows.append(row)
    return script, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("script", nargs="*")
    args = parser.parse_args()
    if not W.DISKS or not W.DISKS.exists():
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    every = W.scripts()
    chosen = {k: v for k, v in every.items()
              if not args.script or k in args.script}
    machine = W.Machine()
    totals = collections.Counter()
    feature_totals = collections.Counter()
    for name, (side, body) in chosen.items():
        geo = None
        gside, gbody = W._file("GEO" + name[3:])
        if gbody is not None:
            try:
                geo = Geo.from_bytes(gbody)
            except Exception:                   # noqa: BLE001
                geo = None
        script, rows = analyse(machine, name, side, body, geo)
        print(f"{name} on {side}, GEO {'yes' if geo else 'none'}")
        for r in rows:
            where = f"area {r['target']}" if r["target"] is not None \
                else "computed"
            sq = ""
            if r["squares"] is not None:
                sq = f" squares={len(r['squares'])} {r['squares'][:6]}"
                if len(r["squares"]) > 6:
                    sq += "..."
            idx = f" index={r['index']}" if r["index"] is not None else ""
            print(f"  ${r['at']:04X} -> {where:10s} {r['kind']:22s} "
                  f"entries={r['entries']}{idx}{sq} "
                  f"{','.join(r['features']) or '-'}")
            totals[r["kind"]] += 1
            for f in r["features"]:
                feature_totals[f] += 1
    print("kinds:", dict(totals))
    print("features:", dict(feature_totals))


if __name__ == "__main__":
    main()
