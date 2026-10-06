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
  plane-`$200` byte (`$C04F`) and `ONGOTO`s by the result, or by an arm a
  table indexed by it holds.  An exit under one of its arms is a **square**
  exit, and the squares carrying an id that selects that arm in the `GEO`
  are where it fires; an arm picked by area state or the travel grid has
  none (`entry1_squares`).

So this walks each script from each of its five entries, finds the shortest
route to every `NEWECL`, and reports the kind, the `ONGOTO` index and the
squares, and the statements on the route that a player would notice: a
menu, printed text, a `LOADCHAR`, a quest flag, a position write.

Six kinds come out of the 79 exits on the disks here. `edge` is entry 0
gated on `$6DD5` with no `ONGOTO` on the route; `square` is entry 1's
`ONGOTO`; `edge+square` is entry 0, gated *and* carrying an `ONGOTO` -- on
the facing `$C04D` or on a menu answer in `$6E79`, never on a square id, so
its squares are the map-edge squares a step leaves by in the facings that
reach the exit;
`square-via-entry0` is entry 0's `ONGOTO` with no gate;
`entry1-unconditional` is entry 1 with neither. The sixth, `entryN`, is the
other three entries -- 2 before camping, 3 camp interrupted, 4 after loading
-- which reach a `NEWECL` directly, with no edge or square dispatch of their
own: `ECL0B`'s `$A20F` is the one exit only entry 3 reaches, run when camping
is interrupted rather than off any square or edge a walking party can stand
on.

    eclexitkinds.py            every script
    eclexitkinds.py ECL0D      one

No string is printed as text, for the reason `tools/areas/eclwalk.py` gives.
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from goldbox.geo import Geo  # noqa: E402
from tools.areas import eclwalk as W  # noqa: E402

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
    """The `AND` mask applied to `$C04F` on the route, and the variable it
    was written to, or `(0x7F, None)`."""
    for a in path:
        st = script.statements[a]
        if st.op == 0x2F and any(k != 0 and v == ATTR for k, v in st.operands):
            mask, dest = 0x7F, None
            for k, v in st.operands:
                if k == 0:
                    mask = v
                elif v != ATTR:
                    dest = v
            return mask, dest
    return 0x7F, None


#: `IF=` .. `IF>=`, and the operand-order flip a literal-first `COMPARE`
#: needs -- `<` and `>` swap, `=` and `!=` read the same either way.
IF_TESTS = {0x16: "=", 0x17: "!=", 0x18: "<", 0x19: ">", 0x1A: "<=", 0x1B: ">="}
_FLIP = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}


def compare_index(script, path, var):
    """The literal a `COMPARE` on `var` tests against, and the test, or
    `(None, None)`.

    `var` is the destination `mask_before` wrote the masked square id to. A
    route that has masked `$C04F` into `var` and then names it in a `COMPARE`
    against a literal, immediately followed by the `IF` that reads it, names
    the id the same way an `ONGOTO` arm does -- `#255 (tools/areas/eclexitkinds.py
    misses a square exit whose id is tested by COMPARE rather than
    ONGOTO)`.
    """
    if var is None:
        return None, None
    for a, b in zip(path, path[1:]):
        st = script.statements[a]
        if st.op != COMPARE or len(st.operands) != 2:
            continue
        (k0, v0), (k1, v1) = st.operands
        if k0 == 0 and v1 == var:
            literal, flip = v0, True
        elif k1 == 0 and v0 == var:
            literal, flip = v1, False
        else:
            continue
        nxt = script.statements.get(b)
        if nxt is None or nxt.op not in IF_TESTS or nxt.at != st.end:
            continue
        test = IF_TESTS[nxt.op]
        if flip:
            test = _FLIP.get(test, test)
        return literal, test
    return None, None


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


_COMPARE_OK = {
    "=": lambda k, literal: k == literal, "!=": lambda k, literal: k != literal,
    "<": lambda k, literal: k < literal, ">": lambda k, literal: k > literal,
    "<=": lambda k, literal: k <= literal, ">=": lambda k, literal: k >= literal,
}


def squares_for_test(geo, mask, literal, test):
    """The squares `compare_index`'s `(literal, test)` selects, or `None`."""
    if geo is None or literal is None:
        return None
    ok = _COMPARE_OK[test]
    return [(x, y) for y in range(16) for x in range(16)
            if ok(geo.script_id(x, y, mask), literal)]


#: `$033D`, the party's heading on the travel grid, eight ways clockwise from
#: north; `$49C3`/`$49C4`, its window-local square there
#: (`docs/113-world-map.md`).
TRAVEL_HEADING, GRID_SQUARE = 0x033D, (0x49C3, 0x49C4)
#: `$C04D`, the party's facing in a `GEO` area, 0-3 clockwise from north.
FACING = 0xC04D
#: `$2A` reads `table[index]` into its third operand; `$14` sets the condition
#: when both of its operand pairs are equal. Both read off the step entries of
#: `ECL07` and `ECL10`, whose tables name the only squares `GEO07` and `GEO10`
#: carry those ids on.
TABLE_READ, COMPARE_AND = 0x2A, 0x14
#: Opcodes whose last operand is the variable they write, and the menus, which
#: write their first.
WRITES_LAST = {0x04, 0x05, 0x06, 0x08, 0x09, TABLE_READ, 0x2F}


def _var(operand):
    kind, value = operand
    return None if kind in (0x00, 0x80) else value


def _written(st):
    if st.op in WRITES_LAST and st.operands:
        return _var(st.operands[-1])
    if st.op in MENUS and st.operands:
        return _var(st.operands[0])
    return None


def _compare_literal(st, known):
    """`(var, test, literal)` for a `COMPARE` of a variable in `known` against
    a literal, read as `var test literal`, or None."""
    if st.op != COMPARE or len(st.operands) != 2:
        return None
    (k0, v0), (k1, v1) = st.operands
    if k0 == 0 and k1 not in (0x00, 0x80) and v1 in known:
        return v1, True, v0
    if k1 == 0 and k0 not in (0x00, 0x80) and v0 in known:
        return v0, False, v1
    return None


def _successors_given(script, st, known):
    """`st`'s successors, with an `ON` jump or a `COMPARE`/`IF` pair on a
    variable in `known` decided by its value instead of taking every arm."""
    if st.op in (W.ONGOTO, W.ONGOSUB) and _var(st.operands[0]) in known:
        n = known[_var(st.operands[0])]
        arms = st.operands[W.COUNTED[st.op]:]
        out = []
        if n < len(arms) and _var(arms[n]) is not None:
            out.append(_var(arms[n]) - W.BASE)
        if st.op == W.ONGOSUB or n >= len(arms):
            out.append(st.end)
        return out
    test = _compare_literal(st, known)
    nxt = script.statements.get(st.end)
    if test is not None and nxt is not None and nxt.op in IF_TESTS:
        var, flip, literal = test
        op = IF_TESTS[nxt.op]
        op = _FLIP.get(op, op) if flip else op
        skipped = W.decode(script.machine, script.body, nxt.end)
        if _COMPARE_OK[op](known[var], literal):
            return [nxt.end]
        return [] if skipped is None else [skipped.end]
    return [succ for succ, _ in script._successors(st)]


def _table_value(script, st, known):
    """The byte a `$2A` reads when its index is in `known`, or None."""
    if st.op != TABLE_READ or len(st.operands) != 3:
        return None
    table, index = _var(st.operands[0]), _var(st.operands[1])
    if table is None or index not in known or _var(st.operands[2]) is None:
        return None
    at = table - W.BASE + known[index]
    return script.body[at] if 0 <= at < len(script.body) else None


def reaches(script, start, goal, known):
    """Whether `goal` can run after `start` while each variable in `known`
    holds its value, until something writes it. A `$2A` whose index is known
    gives its destination the byte it reads."""
    seen = set()
    work = [(start, tuple(sorted(known.items())))]
    while work:
        at, items = work.pop()
        if (at, items) in seen:
            continue
        seen.add((at, items))
        if at == goal:
            return True
        st = script.statements.get(at)
        if st is None:
            continue
        values = dict(items)
        succs = _successors_given(script, st, values)
        looked_up = _table_value(script, st, values)
        values.pop(_written(st), None)
        if looked_up is not None:
            values[_written(st)] = looked_up
        after = tuple(sorted(values.items()))
        work.extend((succ, after) for succ in succs)
    return False


def _table_read_into(script, path, before, var):
    """The last `$2A` on `path[:before]` that writes `var`."""
    for a in reversed(path[:before]):
        st = script.statements[a]
        if st.op == TABLE_READ and len(st.operands) == 3 \
                and _var(st.operands[2]) == var:
            return st
    return None


def _row_count(script, counter, heads):
    """N, from the `COMPARE [counter], N` / `IF<` / `GOTO` that jumps back to
    one of `heads`, the statements of the loop before its test."""
    for st in script.ordered():
        test = _compare_literal(st, {counter: 0})
        nxt = script.statements.get(st.end)
        if test is None or test[1] or nxt is None or nxt.op != 0x18:
            continue
        back = script.statements.get(nxt.end)
        if back is not None and back.op == W.GOTO \
                and back.target() is not None \
                and back.target() - W.BASE in heads:
            return test[2]
    return None


def entry0_table(script, path, og, id_var):
    """The `(row, id, facing, action)` table entry 0 loops over before its
    `ONGOTO`, or None where the route does not read one.

    The step entries of `ECL07` and `ECL10` mask the square id out of `$C04F`,
    then walk a row counter over three tables -- id, facing, action -- and
    stop at the first row whose id is the square's and whose facing is
    `$C04D`, under `$14`. Only then does the `ONGOTO` run, on that row's
    action: the arm number is an action, never a square id.
    """
    selector = _var(og.operands[0])
    pos = path.index(og.at)
    action = _table_read_into(script, path, pos, selector)
    if selector is None or action is None or id_var is None:
        return None
    counter = _var(action.operands[1])
    tests = [i for i in range(pos) if script.statements[path[i]].op
             == COMPARE_AND and len(script.statements[path[i]].operands) == 4]
    if counter is None or not tests:
        return None
    at = tests[-1]
    operands = script.statements[path[at]].operands
    tables = {}
    for a, b in ((0, 1), (2, 3)):
        for key, loaded in ((operands[a], operands[b]),
                            (operands[b], operands[a])):
            rd = _table_read_into(script, path, at, _var(loaded))
            if rd is not None and _var(rd.operands[1]) == counter:
                tables[_var(key)] = _var(rd.operands[0])
    count = _row_count(script, counter, set(path[:at]))
    if id_var not in tables or FACING not in tables or count is None:
        return None
    body = script.body

    def column(table):
        start = table - W.BASE
        return None if start < 0 or start + count > len(body) \
            else body[start:start + count]
    ids, facings, actions = (column(tables[id_var]), column(tables[FACING]),
                             column(_var(action.operands[0])))
    if ids is None or facings is None or actions is None:
        return None
    return {"selector": selector, "counter": counter,
            "rows": list(zip(range(count), ids, facings, actions))}


def grid_tests(script, path):
    """`(var, test, literal)` for each `COMPARE` of the travel-grid square
    against a literal whose `IF` the route takes on its true side."""
    out = []
    for a, b in zip(path, path[1:]):
        st = script.statements[a]
        test = _compare_literal(st, dict.fromkeys(GRID_SQUARE, 0))
        nxt = script.statements.get(st.end)
        if test is None or nxt is None or nxt.op not in IF_TESTS \
                or b != nxt.at:
            continue
        var, flip, literal = test
        after = path[path.index(b) + 1] if path.index(b) + 1 < len(path) \
            else None
        if after == nxt.end:
            op = IF_TESTS[nxt.op]
            out.append((var, _FLIP.get(op, op) if flip else op, literal))
    return out


def entry0_squares(script, path, og, exit_at, geo, row):
    """Fill `row` for an ungated `ONGOTO` on entry 0's route.

    Three dispatches reach one. A table of `(id, facing, action)` rows gives
    `squares` as `(x, y, facing)`, row by row, for each row whose action
    reaches this exit -- `row["table"]` lists those rows. An `ONGOTO` on the
    travel-grid heading gives no squares: the grid scripts test `$49C3` and
    the heading, which `row["grid"]` and `row["headings"]` carry, and no `GEO`
    square. An `ONGOTO` on the masked square id itself takes the arm as the id.
    """
    mask, var = mask_before(script, path)
    selector = _var(og.operands[0])
    table = entry0_table(script, path, og, var)
    if table is not None:
        leaving, seen = [], set()
        for n, sid, facing, action in table["rows"]:
            if (sid, facing) in seen:
                continue  # the loop stops at the first row that matches
            seen.add((sid, facing))
            if reaches(script, og.at, exit_at,
                       {table["selector"]: action, table["counter"]: n}):
                leaving.append((n, sid, facing, action))
        row["table"] = leaving
        if geo is not None:
            row["squares"] = [(x, y, facing) for _n, sid, facing, _a in leaving
                              for x, y in squares_with(geo, mask, sid)]
        return
    if selector == TRAVEL_HEADING:
        start = script.entries[0]
        row["headings"] = [d for d in range(8) if reaches(
            script, start, exit_at, {TRAVEL_HEADING: d})]
        row["grid"] = grid_tests(script, path)
        return
    if selector is not None and selector == var:
        row["squares"] = squares_with(geo, mask, row["index"])


def _mask_at(script, path):
    """Where on `path` the `AND` that masks `$C04F` sits, or None."""
    for i, a in enumerate(path):
        st = script.statements[a]
        if st.op == 0x2F and any(k != 0 and v == ATTR for k, v in st.operands):
            return i
    return None


def _equal_on_route(script, path, var, other):
    """Whether `path` takes the true side of a `COMPARE [var], [other]` and
    its `IF=`, so `var` holds `other`'s value where the route goes on."""
    for a, b, c in zip(path, path[1:], path[2:]):
        st = script.statements[a]
        if st.op != COMPARE or len(st.operands) != 2:
            continue
        if {_var(st.operands[0]), _var(st.operands[1])} != {var, other}:
            continue
        nxt = script.statements[b]
        if nxt.op == 0x16 and nxt.at == st.end and c == nxt.end:
            return True
    return False


def entry1_squares(script, path, og, exit_at, geo, row):
    """Fill `row` for entry 1's `ONGOTO`, by what its selector holds.

    `row["selector"]` names it. `id`: the masked square id itself, or a
    variable the route has just found equal to it (`ECL00`'s loop counter), so
    the arm number is the id. `id-table`: a `$2A` reads the arm out of a table
    indexed by the masked id (`ECL03`, `ECL16`, `ECL17`); `row["ids"]` lists
    the ids from which the exit runs, each followed through the tables and
    tests between the mask and the exit, and `squares` the squares carrying
    them. `table`: a table indexed by anything else -- the travel-grid
    windows look the party's grid square up -- and `state`: a variable set
    from area state (`ECL11`'s flags and hour). Neither names a `GEO` square,
    so both leave `squares` None; `row["grid"]` is True where the route reads
    the grid square `$49C3`/`$49C4`.
    """
    mask, var = mask_before(script, path)
    selector = _var(og.operands[0])
    pos = path.index(og.at)
    if selector is not None and var is not None and (
            selector == var or _equal_on_route(script, path[:pos + 1],
                                               selector, var)):
        row["selector"] = "id"
        row["squares"] = squares_with(geo, mask, row["index"])
        return
    read = _table_read_into(script, path, pos, selector)
    masked = _mask_at(script, path)
    if read is not None and var is not None and masked is not None \
            and _var(read.operands[1]) == var:
        start = path[masked + 1]
        ids = [i for i in range(mask + 1)
               if reaches(script, start, exit_at, {var: i})]
        row["selector"] = "id-table"
        row["ids"] = ids
        row["squares"] = None if geo is None else [
            (x, y) for y in range(16) for x in range(16)
            if geo.script_id(x, y, mask) in ids]
        return
    row["selector"] = "table" if read is not None else "state"
    row["grid"] = any(_var(operand) in GRID_SQUARE
                      for a in path[:pos]
                      for operand in script.statements[a].operands)
    row["squares"] = None


def outward_facings(x: int, y: int) -> list[int]:
    """Which directions leave the 16x16 grid from `(x, y)`, in `goldbox.geo`'s
    order `NORTH, EAST, SOUTH, WEST = 0, 1, 2, 3`; a corner square has two."""
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


def edge_squares(geo, facings):
    """`(x, y, facing)` for every square a step in one of `facings` leaves the
    map from, open on that side: `$10EC` sets `$6DD5` for no other step."""
    if geo is None:
        return None
    return [(x, y, d) for y in range(16) for x in range(16)
            for d in outward_facings(x, y)
            if d in facings and geo.is_passable(x, y, d)]


def edge_dispatch(script, path, og, exit_at, geo, row):
    """Fill `row` for an `ONGOTO` behind entry 0's `$6DD5` gate.

    The edge scripts switch on the facing `$C04D` (`ECL02`, `ECL0E`, `ECL12`)
    or on the answer `$6E79` to a menu the route has just shown (`ECL15`).
    `row["facings"]` is each facing from which the exit runs, and
    `row["choice"]` the `(variable, answers)` a menu selector needs. An
    `ONGOTO` on the masked square id takes the arm as the id.
    """
    selector = _var(og.operands[0])
    mask, var = mask_before(script, path)
    if selector is not None and selector == var:
        row["squares"] = squares_with(geo, mask, row["index"])
        return
    if selector is None:
        return
    arms = len(og.operands) - W.COUNTED[og.op]
    answers = [n for n in range(arms)
               if reaches(script, og.at, exit_at, {selector: n})]
    if selector == FACING:
        facings = [d for d in answers if d < 4]
    else:
        row["choice"] = (selector, answers)
        facings = [d for d in range(4) if reaches(
            script, script.entries[0], exit_at, {FACING: d})]
    row["facings"] = facings
    row["squares"] = edge_squares(geo, facings)


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
            mask, var = mask_before(script, path)
            if og is not None:
                row["kind"] = "square"
                row["index"] = k
                entry1_squares(script, path, og, st.at, geo, row)
            else:
                literal, test = compare_index(script, path, var)
                if literal is not None:
                    row["index"] = literal if test == "=" else (test, literal)
                    row["squares"] = squares_for_test(geo, mask, literal, test)
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
            elif og is not None and gated:
                row["kind"] = "edge+square"
                row["index"] = k
                edge_dispatch(script, path, og, st.at, geo, row)
            elif og is not None:
                row["kind"] = "square-via-entry0"
                row["index"] = k
                entry0_squares(script, path, og, st.at, geo, row)
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
            if r.get("facings") is not None:
                idx += f" facings={r['facings']}"
            if r.get("choice") is not None:
                idx += f" ${r['choice'][0]:04X} in {r['choice'][1]}"
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
