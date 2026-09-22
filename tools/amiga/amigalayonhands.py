#!/usr/bin/env python3
"""Where the Amiga Gold Box engines keep a paladin's lay-on-hands use.

    tools/amiga/amigalayonhands.py
    tools/amiga/amigalayonhands.py --title secret-of-the-silver-blades

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
  heal id can be seen to lie inside it or past its end.

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
            "filled": filled}


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
        heal_pushes=pushes(raw, exe, heal.effect_id))
    return result


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", choices=sorted(TITLES), action="append")
    a = ap.parse_args(argv)
    for key in a.title or list(TITLES):
        raw = executable(key)
        if raw is None:
            print(f"{key}: no executable on the registry's Amiga disks")
            continue
        _print(inspect(raw, key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
