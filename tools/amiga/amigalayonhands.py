#!/usr/bin/env python3
"""Where the Amiga Gold Box engines keep a paladin's lay-on-hands use.

    tools/amiga/amigalayonhands.py
    tools/amiga/amigalayonhands.py --title secret-of-the-silver-blades
    tools/amiga/amigalayonhands.py --dispatch --title pools-of-darkness

The Amiga port keeps no lay-on-hands byte, exactly as DOS does: HEAL adds a
ten-byte effect node to the paladin's chain, and the sheet offers HEAL only
while he has no node with that id.  **All three later Amiga titles push id
140**, Curse's number -- where DOS Silver Blades and DOS Pools of Darkness
push 109 -- so the id is not the same across ports of one title.

Read from each executable by instruction pattern, not by address:

* the **heal call** -- `clr.w -(a7) / clr.w -(a7) / move.w #1440, -(a7) /
  move.w #id, -(a7) / move.l An, -(a7) / jsr add_affect`, value 0 and flag 0,
  and the routine it sits in, with every store it makes through an address
  register other than the frame and the stack (there are none);
* **add_affect** itself, checked to store the id at node `+0` and the
  duration word at `+2`;
* the **gate** -- the one `find_affect(id)` call before the heal, with its
  callee checked to walk the chain comparing node byte 0;
* the **cure** the same way, from the call pushing 10080, and the record
  byte its routine decrements;
* the effect **handler table** -- the dispatcher `remove_affect` calls when
  a node's flag is set, and the ids the start-up code fills in it -- so the
  heal id can be seen to lie inside it or past its end;
* the **expiry routine** -- the clock's scale table, `10, 10, 6, 24, ...`
  as in DOS, and the `sub.w` that takes the elapsed count off node `+2`.

`--dispatch` also classifies every caller of the handler dispatcher by
where the id it passes comes from: a constant, a routine argument whose
callers all pass constants, a node whose flag byte is tested first, or the
item path that the dispatcher sends to another routine without touching the
table.  Anything else prints as unread.

Pool of Radiance has no heal call and no `Heal whom` prompt.  Executables
come from the registry's `amiga` disks, read-only; nothing is written.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from tools.amiga import amiga68k, amigabackstab  # noqa: E402

TITLES = amigabackstab.TITLES
LATER = ("curse-of-the-azure-bonds", "secret-of-the-silver-blades",
         "pools-of-darkness")

HEAL_MINUTES = 1440
CURE_MINUTES = 10080

#: `<value push> <flag push> move.w #minutes, -(a7) / move.w #id, -(a7) /
#: move.l a2|a3, -(a7) / jsr d16(a4)`.  A push is `clr.w -(a7)` (0) or
#: `move.w #n, -(a7)`; the first pushed is the flag, the second the value.
_PUSH = rb"(\x42\x67|\x3f\x3c..)"
_CALL = re.compile(_PUSH + _PUSH + rb"\x3f\x3c(..)\x3f\x3c\x00(.)\x2f([\x0a\x0b])\x4e\xac(..)", re.S)

#: `pea -4(a5) / move.w #id, -(a7) / move.l An, -(a7) / jsr d16(a4)`: a
#: `find_affect(record, id, &node)` call.
_FIND = re.compile(rb"\x48\x6d\xff[\xf8\xfc]\x3f\x3c\x00(.)\x2f[\x0a\x0b]\x4e\xac(..)", re.S)

#: `tst.b 5(a2) / beq / move.w #1, -(a7) / move.l a2 / move.l Rn / moveq #0, d0
#: / move.b Dn, d0 / move.w d0, -(a7) / jsr d16(pc)`: remove_affect handing a
#: node whose flag is set to the dispatcher.
_REMOVE = re.compile(rb"\x4a\x2a\x00\x05\x67\x16\x3f\x3c\x00\x01\x2f\x0a\x2f."
                     rb"\x70\x00\x10.\x3f\x00\x4e\xba(..)", re.S)

#: `asl.l #2, d0 / lea d16(a4), a0 / movea.l (a0, d0.l), a0 / jsr (a0)`.
_TABLE = re.compile(rb"\xe5\x80\x41\xec(..)\x20\x70\x08\x00\x4e\x90", re.S)

#: `lea d16(pc), a0 / move.l a0, d16(a4)`: a start-up table fill.
_FILL = re.compile(rb"\x41\xfa(..)\x29\x48", re.S)

#: add_affect's stores: `move.b $d(a5), (a0)` (the id) and
#: `move.w $e(a5), $2(a0)` (the duration).
_STORE_ID = bytes.fromhex("10ad000d")
_STORE_DURATION = bytes.fromhex("316d000e0002")


@dataclasses.dataclass(frozen=True)
class Call:
    site: int           # the `jsr add_affect`
    routine: int        # the routine's `link.w a5`
    effect_id: int
    minutes: int
    value: int          # node +4
    flag: int           # node +5
    add_affect: int
    stores: tuple       # stores through a0-a3 or a6 in the routine
    decrements: tuple   # record displacements the routine decrements


def _s16(raw: bytes) -> int:
    return struct.unpack(">h", raw)[0]


def _push(raw: bytes) -> int:
    return 0 if raw == b"\x42\x67" else struct.unpack(">H", raw[2:])[0]


def _code(exe) -> amiga68k.Hunk:
    return next(h for h in exe.hunks if h.kind == "CODE")


def _aligned(raw: bytes, word: bytes, at: int, back: bool = False, lo: int = 0) -> int:
    find = (lambda i: raw.rfind(word, lo, i)) if back else (lambda i: raw.find(word, i))
    hit = find(at)
    while hit % 2:
        hit = find(hit if back else hit + 1)
    return hit


def _routine(raw: bytes, code, at: int) -> tuple[int, int]:
    """The routine around `at`: its `link`, to the first `rts` or `bra` after
    `at` or the next `link`, whichever comes first -- a routine's strings
    follow its last jump and must not be swept as code."""
    start = _aligned(raw, b"\x4e\x55", at, back=True, lo=code.file_offset)
    end = _aligned(raw, b"\x4e\x55", at)
    for insn in amiga68k._sweep(amiga68k._capstone(), raw, at, end):
        if insn.mnemonic.split(".")[0] in ("rts", "bra", "jmp"):
            return start, insn.address + insn.size
    return start, end


def _insns(raw: bytes, start: int, end: int):
    return list(amiga68k._sweep(amiga68k._capstone(), raw, start, end))


def _stores(raw: bytes, start: int, end: int) -> tuple:
    out = []
    for insn in _insns(raw, start, end):
        dest = insn.op_str.split(", ")[-1]
        if (insn.mnemonic.split(".")[0] in ("move", "clr", "addq", "subq", "st", "sf")
                and re.search(r"\(a[0-36]\)", dest)
                and "(a7)" not in dest):
            out.append((insn.address, f"{insn.mnemonic} {insn.op_str}"))
    return tuple(out)


def _decrements(raw: bytes, start: int, end: int) -> tuple:
    """`lea $d(An), a0 / ... / subq.w #1, d0 / move.b d0, (a0)`: the record byte."""
    ins = _insns(raw, start, end)
    out = []
    for k, insn in enumerate(ins):
        m = re.fullmatch(r"\$([0-9a-f]+)\(a[23]\), a0", insn.op_str)
        if insn.mnemonic.startswith("lea") and m and any(
                i.mnemonic.startswith("subq") for i in ins[k:k + 4]):
            out.append(int(m.group(1), 16))
    return tuple(out)


def calls(raw: bytes, exe, minutes: int) -> list[Call]:
    code = _code(exe)
    out = []
    for m in _CALL.finditer(raw):
        if m.start() % 2 or not code.holds(m.start()):
            continue
        if struct.unpack(">H", m.group(3))[0] != minutes:
            continue
        site = m.end() - 4
        start, end = _routine(raw, code, site)
        out.append(Call(site, start, m.group(4)[0], minutes, _push(m.group(2)),
                        _push(m.group(1)), exe.resolve_a4(_s16(m.group(6))),
                        _stores(raw, start, end), _decrements(raw, start, end)))
    return out


def _one(found: list, what: str):
    if len(found) != 1:
        raise ValueError(f"{what}: expected one, found {len(found)}")
    return found[0]


def gate(raw: bytes, exe, eid: int) -> dict:
    """The one `find_affect(eid)` call, and what its callee compares."""
    code = _code(exe)
    hits = [m for m in _FIND.finditer(raw)
            if m.start() % 2 == 0 and code.holds(m.start()) and m.group(1)[0] == eid]
    m = _one(hits, f"find_affect({eid}) calls")
    callee = exe.resolve_a4(_s16(m.group(2)))
    body = raw[callee:callee + 0x40]
    # `move.b (a0), d0 / cmp.b d3, d0`: node byte 0 against the id.
    walks = bytes.fromhex("1010b003") in body
    return {"site": m.start() + 2, "find_affect": callee, "compares_byte_0": walks}


def handler_table(raw: bytes, exe) -> dict:
    """remove_affect's dispatcher, its table, and the ids filled at start-up."""
    code = _code(exe)
    # Silver Blades has two copies of remove_affect; both call one dispatcher.
    targets = {m.end() - 2 + _s16(m.group(1)) for m in _REMOVE.finditer(raw)
               if code.holds(m.start())}
    dispatcher = _one(sorted(targets), "remove_affect's dispatcher")
    t = _TABLE.search(raw, dispatcher, dispatcher + 0x80)
    if t is None:
        raise ValueError("dispatcher has no table index")
    table = amiga68k.SMALL_DATA_BIAS + _s16(t.group(1))
    filled: dict[int, int] = {}
    for f in _FILL.finditer(raw):
        if f.start() % 2 or not code.holds(f.start()):
            continue
        target = f.start() + 2 + _s16(f.group(1))
        at = f.start() + 4
        # one `lea` may be stored into several slots: `move.l a0, d16(a4)` x n
        while raw[at:at + 2] == b"\x29\x48":
            slot = amiga68k.SMALL_DATA_BIAS + _s16(raw[at + 2:at + 4]) - table
            if slot > 0 and slot % 4 == 0 and slot // 4 < 256:
                filled[slot // 4] = target
            at += 4
    top = max(filled)
    return {"dispatcher": dispatcher, "table": table, "highest": top,
            "unfilled": tuple(e for e in range(1, top) if e not in filled),
            "filled": filled, "indexers": indexers(raw, exe, table)}


def indexers(raw: bytes, exe, table: int) -> tuple:
    """Every `lea table(a4), An` in the code: the places that can index it."""
    code = _code(exe)
    d16 = struct.pack(">h", table - amiga68k.SMALL_DATA_BIAS)
    return tuple(m.start() for m in re.finditer(rb"[\x41\x43\x45\x47\x49\x4b\x4d]\xec"
                                                + re.escape(d16), raw)
                 if m.start() % 2 == 0 and code.holds(m.start()))


#: `lea d16(a4), a0 / mulu.w (a0, d0.l), Dn`: the expiry routine scaling the
#: elapsed count by the clock's table.
#: Pools of Darkness clears the count's high word first (`swap / clr.w / swap`).
_SCALE = re.compile(rb"\x41\xec(..)(?:\x48[\x40-\x47]\x42[\x40-\x47]\x48[\x40-\x47])?[\xc0-\xcf]\xf0\x08\x00",
                    re.S)


def expiry(raw: bytes, exe) -> dict:
    """The expiry routine's scale table and its subtract from node `+2`.

    The routine multiplies the elapsed count by table words 1 to unit - 1,
    then takes at most ten off each node's duration word per pass: so with
    the table `10, 10, 6, 24` a count in unit 3 reaches the node as 60 times
    itself and one in unit 4 as 1440 times -- an hour and a day in minutes.
    """
    code, data = _code(exe), exe.small_data
    for m in _SCALE.finditer(raw):
        if m.start() % 2 or not code.holds(m.start()):
            continue
        g = amiga68k.SMALL_DATA_BIAS + _s16(m.group(1))
        lea = raw.find(b"\x41\xea\x00\x02", m.end(), m.end() + 0x100)
        sub = raw.find(b"\x91\x50", lea, lea + 10) if lea > 0 else -1
        if sub < 0:
            continue
        table = struct.unpack(">7H", raw[data.file_offset + g:data.file_offset + g + 14])
        minutes = [1]
        for word in table[1:4]:
            minutes.append(minutes[-1] * word)
        return {"scale_site": m.start(), "table": table, "table_global": g,
                "subtract_site": sub, "unit_minutes": tuple(minutes)}
    raise ValueError("no expiry routine")


# -- who hands the dispatcher an id -----------------------------------------

#: `moveq #0, d0 / move.b Dn, d0 / move.w d0, -(a7)`: a byte register pushed.
_REG_PUSH = re.compile(rb"\x70\x00\x10([\x00-\x07])\x3f\x00\Z", re.S)

#: remove_affect: `tst.b 5(a2) / beq.b / move.w #1, -(a7) / move.l a2, -(a7) /
#: move.l Rn, -(a7)`, then the id register pushed as above.
_GATED = re.compile(rb"\x4a\x2a\x00\x05\x67.\x3f\x3c\x00\x01\x2f\x0a\x2f."
                    rb"\x70\x00\x10.\x3f\x00\Z", re.S)


#: `moveq #0, d0 / move.b $40(An), d0 / move.w d0, -(a7)`: an item's effect
#: byte pushed as the id.
_ITEM_ID = re.compile(rb"\x70\x00\x10[\x28-\x2f]\x00\x40\x3f\x00\Z", re.S)


@dataclasses.dataclass(frozen=True)
class Dispatch:
    site: int           # the `jsr`/`bsr` to the dispatcher
    kind: str           # constant | argument | flag-tested | item | item-id | unread
    ids: tuple          # the ids it can pass, where they are constants
    via: int | None     # the wrapper routine, for `argument`


def call_sites(raw: bytes, exe, target: int) -> list[int]:
    """Every `jsr`/`bsr` to `target`, direct or through the a4 jump table."""
    code = _code(exe)
    lo, hi = code.file_offset, code.file_offset + code.size
    out = [p for p in amiga68k.pc_references(raw, target, lo, hi)
           if raw[p:p + 2] == b"\x4e\xba" or raw[p] == 0x61]
    for p in range(lo, hi - 4, 2):
        if raw[p:p + 2] == b"\x4e\xac" and exe.resolve_a4(_s16(raw[p + 2:p + 4])) == target:
            out.append(p)
    return sorted(out)


def _routine_span(raw: bytes, code, at: int) -> tuple[int, int]:
    """From the nearest `link.w a5` or `movem.l ..., -(a7)` at or before `at`
    to the next one after it: the routine, with any strings behind it."""
    lo = code.file_offset
    start = max(_aligned(raw, b"\x4e\x55", at + 2, back=True, lo=lo),
                _aligned(raw, b"\x48\xe7", at + 2, back=True, lo=lo))
    ends = [e for e in (_aligned(raw, b"\x4e\x55", at + 2), _aligned(raw, b"\x48\xe7", at + 2))
            if e > at]
    return start, min(ends) if ends else code.file_offset + code.size


def branches(raw: bytes, start: int, end: int) -> set[tuple[int, int]]:
    """`(source, target)` of every branch and jump-table entry in a stretch."""
    ins = _insns(raw, start, end)
    out = set()
    for k, i in enumerate(ins):
        op = i.mnemonic.split(".")[0]
        if (op.startswith("b") and op not in ("btst", "bset", "bclr", "bchg")) \
                or op.startswith("db"):
            m = re.search(r"\$([0-9a-f]+)$", i.op_str)
            if m:
                out.add((i.address, int(m.group(1), 16)))
        elif op == "jmp" and re.fullmatch(r"\$[0-9a-f]+\(pc,d0\.w\)", i.op_str) and k >= 3:
            base = int(i.op_str[1:].split("(")[0], 16)
            load = re.fullmatch(r"\$([0-9a-f]+)\(pc, d0\.w\), d0", ins[k - 1].op_str)
            bound = next((re.fullmatch(r"#\$([0-9a-f]+), d0", j.op_str)
                          for j in ins[k - 4:k - 1] if j.mnemonic == "cmpi.w"), None)
            if load and bound:
                table = int(load.group(1), 16)
                for e in range(int(bound.group(1), 16)):
                    out.add((i.address, base + _s16(raw[table + 2 * e:table + 2 * e + 2])))
    return out


def _constant_id(raw: bytes, site: int) -> int | None:
    """The id of `move.w #id, -(a7) / jsr`, the push nearest the call."""
    if raw[site - 4:site - 2] == b"\x3f\x3c":
        return struct.unpack(">H", raw[site - 2:site])[0]
    return None


def _argument_register(raw: bytes, code, site: int, reg: int) -> int | None:
    """The routine around `site` if `reg` is its byte argument `$d(a5)` and
    nothing else in the routine writes it; else None."""
    start = _aligned(raw, b"\x4e\x55", site, back=True, lo=code.file_offset)
    load = bytes((0x10 | reg << 1, 0x2D, 0x00, 0x0D))
    at = raw.find(load, start, start + 0x20)
    if at < 0:
        return None
    for i in _insns(raw, at + 4, site):
        if i.op_str.split(", ")[-1] == f"d{reg}" and not i.mnemonic.startswith(("cmp", "tst")):
            return None
    return start


def dispatch_callers(raw: bytes, exe, table: dict) -> list[Dispatch]:
    """Every caller of the handler dispatcher, by where its id comes from."""
    code = _code(exe)
    d = table["dispatcher"]
    head = raw[d:d + 0x14]
    at = head.find(b"\x4a\x2c")
    item_flag = raw[d + at + 2:d + at + 4]
    set_flag = b"\x19\x7c\x00\x01" + item_flag
    out = []
    for s in call_sites(raw, exe, d):
        before = raw[s - 0x20:s]
        eid = _constant_id(raw, s)
        p = raw.rfind(set_flag, s - 0x30, s)
        # The flag set reaches the call only if nothing in the routine
        # outside the stretch between them jumps into it.
        if p >= 0 and not any(p < t <= s and not p <= f < s for f, t in
                              branches(raw, *_routine_span(raw, code, p))):
            out.append(Dispatch(s, "item", (), None))
        elif _ITEM_ID.search(before):
            out.append(Dispatch(s, "item-id", (), None))
        elif eid is not None:
            out.append(Dispatch(s, "constant", (eid,), None))
        elif _GATED.search(before):
            out.append(Dispatch(s, "flag-tested", (), None))
        elif (m := _REG_PUSH.search(before)) and (
                wrapper := _argument_register(raw, code, s, m.group(1)[0])) is not None:
            # `move.w #id, -(a7) / move.l a2|a3, -(a7) / jsr wrapper`
            ids = [struct.unpack(">H", raw[c - 4:c - 2])[0] if raw[c - 6:c - 4] == b"\x3f\x3c"
                   and raw[c - 2:c] in (b"\x2f\x0a", b"\x2f\x0b") else None
                   for c in call_sites(raw, exe, wrapper)]
            kind = "argument" if ids and None not in ids else "unread"
            out.append(Dispatch(s, kind, tuple(sorted(set(i for i in ids if i is not None))),
                                wrapper))
        else:
            out.append(Dispatch(s, "unread", (), None))
    return out


def inspect(raw: bytes, key: str) -> dict:
    exe = amiga68k.Executable.parse(raw)
    heals = calls(raw, exe, HEAL_MINUTES)
    result = {"title": key, "heal": None,
              "heal_strings": bool(re.search(rb"(?i)heal whom", raw))}
    if not heals and not result["heal_strings"]:
        return result
    heal = _one(heals, "heal add_affect")
    cure = _one(calls(raw, exe, CURE_MINUTES), "cure add_affect")
    add = raw[heal.add_affect:heal.add_affect + 0x80]
    table = handler_table(raw, exe)
    handler = table["filled"].get(heal.effect_id)
    result.update(
        heal=heal, cure=cure, gate=gate(raw, exe, heal.effect_id),
        add_affect_stores=(_STORE_ID in add, _STORE_DURATION in add),
        table=table, heal_handler=handler,
        heal_handler_empty=(handler is not None and raw[handler:handler + 2] == b"\x4e\x75"),
        heal_pushes=pushes(raw, exe, heal.effect_id),
        expiry=expiry(raw, exe), item_slot=item_slot(raw, table))
    return result


def item_slot(raw: bytes, table: dict) -> int:
    """The table slot the dispatcher's item path jumps through.

    `tst.b flag(a4) / beq / ... / movea.l d16(a4), a0 / jsr (a0)`: with the
    flag set, the dispatcher calls the routine stored here and never indexes
    the table, so this slot is a pointer the start-up code fills like a
    handler but no effect id selects.
    """
    d = table["dispatcher"]
    at = raw.find(b"\x20\x6c", d, d + 0x30)
    return (amiga68k.SMALL_DATA_BIAS + _s16(raw[at + 2:at + 4]) - table["table"]) // 4


def pushes(raw: bytes, exe, eid: int) -> tuple:
    """`(site, callee)` of every `move.w #eid, -(a7)` and the call after it.

    The callee is the first `jsr d16(a4)` within the next ten bytes, or None.
    """
    code = _code(exe)
    out = []
    for m in re.finditer(re.escape(bytes((0x3F, 0x3C, 0, eid))), raw):
        if m.start() % 2 or not code.holds(m.start()):
            continue
        callee = None
        for at in range(m.end(), m.end() + 10, 2):
            if raw[at:at + 2] == b"\x4e\xac":
                callee = exe.resolve_a4(_s16(raw[at + 2:at + 4]))
                break
        out.append((m.start(), callee))
    return tuple(out)


def executable(key: str) -> bytes | None:
    return amigabackstab.executable(TITLES[key])


def _print(f: dict) -> None:
    print(f"== {f['title']}")
    if f["heal"] is None:
        print("   no heal call: no 1440-minute add_affect and no 'Heal whom' prompt")
        return
    h, c, g, t = f["heal"], f["cure"], f["gate"], f["table"]
    print(f"   heal routine {h.routine:06x}: add_affect {h.add_affect:06x} at {h.site:06x}, "
          f"id {h.effect_id} for {h.minutes} min, value {h.value}, flag {h.flag}; "
          f"record stores {list(h.stores) or 'none'}")
    print(f"   add_affect stores id at +0 and duration at +2: {all(f['add_affect_stores'])}")
    print(f"   every push of {h.effect_id}: " + ", ".join(
        f"{at:06x} -> {'?' if to is None else format(to, '06x')}" for at, to in f["heal_pushes"]))
    print(f"   gate: find_affect {g['find_affect']:06x}({h.effect_id}) at {g['site']:06x},"
          f" walks node byte 0: {g['compares_byte_0']}")
    where = (f"handler {f['heal_handler']:06x} "
             f"{'empty (rts)' if f['heal_handler_empty'] else 'not empty'}"
             if f["heal_handler"] is not None else "no handler: past the table's end")
    print(f"   effect table g{t['table']:04x} (dispatcher {t['dispatcher']:06x}): slots filled "
          f"up to {t['highest']}, unfilled below it {list(t['unfilled'])}; id {h.effect_id}: {where}")
    print(f"   cure routine {c.routine:06x}: id {c.effect_id} for {c.minutes} min, value "
          f"{c.value}, flag {c.flag}; decrements record "
          + (", ".join(f"0x{b:x}" for b in c.decrements) or "nothing"))
    e = f["expiry"]
    print(f"   expiry: scale table g{e['table_global']:04x} = {list(e['table'])} at "
          f"{e['scale_site']:06x}, node +2 decremented at {e['subtract_site']:06x}; "
          f"units 1-4 reach the node as {list(e['unit_minutes'])} minutes")
    print(f"   slot {f['item_slot']} is the dispatcher's item path, not an effect handler")
    print(f"   the table's base is loaded at {', '.join(f'{a:06x}' for a in t['indexers'])} only")


def _print_dispatch(raw: bytes, key: str, f: dict) -> None:
    exe = amiga68k.Executable.parse(raw)
    found = dispatch_callers(raw, exe, f["table"])
    heal = f["heal"].effect_id
    print(f"   {len(found)} callers of dispatcher {f['table']['dispatcher']:06x}:")
    for c in found:
        via = f" via {c.via:06x}" if c.via is not None else ""
        ids = (f" ids {c.ids[0]}" if len(c.ids) == 1 else
               f" {len(c.ids)} ids {min(c.ids)}-{max(c.ids)}" if c.ids else "")
        print(f"     {c.site:06x} {c.kind}{via}{ids}"
              + ("  <-- can pass the heal id" if heal in c.ids or c.kind == "unread" else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", choices=sorted(TITLES), action="append")
    ap.add_argument("--dispatch", action="store_true",
                    help="also classify every caller of the handler dispatcher")
    a = ap.parse_args(argv)
    for key in a.title or list(TITLES):
        raw = executable(key)
        if raw is None:
            print(f"{key}: no executable on the registry's Amiga disks")
            continue
        f = inspect(raw, key)
        _print(f)
        if a.dispatch and f["heal"] is not None:
            _print_dispatch(raw, key, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
