#!/usr/bin/env python3
"""Where the DOS Gold Box engines keep a paladin's lay-on-hands use.

    tools/dos/layonhands.py                  # every DOS title
    tools/dos/layonhands.py --title silver-blades

DOS keeps no lay-on-hands byte in the character record.  The only state is
an effect node on the paladin's chain: HEAL adds it, and the sheet offers
HEAL only while the paladin has no node with that id.  This reads, from each
title's own `GAME.OVR`, by instruction pattern rather than by address:

* the **heal routine** -- the one `add_affect` call whose duration is the
  immediate 1440, with the id, value byte and flag byte it pushes, and every
  write it makes through a far pointer (there are none);
* the **gate** -- the one `find_affect` caller that tests that id, and the
  record bytes it checks first;
* the id's **handler** in the effect table, which is empty, so expiry does
  nothing but remove the node;
* the **cure** the same way, from the `add_affect` whose duration is 10080,
  with the record byte its routine decrements.

Pool of Radiance has no heal routine at all, and `--title pool` says so.
Static throughout; prints addresses and values only, and writes nothing.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from tools.dos import dosaffectreads, dosbox, dosovrmap, dospod, unexepack  # noqa: E402

#: title key -> (archive directory stem, the executable holding the overlay map)
TITLES = {
    "pool": ("POOLRAD", "START.EXE"),
    "curse": ("CURSE", "START.EXE"),
    "silver-blades": ("SECRET", "START.EXE"),
    "pools-of-darkness": ("DARKNESS", "GAME.EXE"),
}

HEAL_MINUTES = 1440     # one day
CURE_MINUTES = 10080    # seven days

#: `mov al, id / push ax / mov ax, minutes / push ax / mov al, value /
#: push ax / mov al, flag / push ax / lcall seg:off` -- an `add_affect` call.
ADD_CALL = re.compile(rb"\xb0(.)\x50\xb8(..)\x50\xb0(.)\x50\xb0(.)\x50\x9a(....)", re.S)


@dataclasses.dataclass(frozen=True)
class Timer:
    """One `add_affect` call with a constant id and duration."""

    site: int           # the `lcall add_affect`, GAME.OVR file offset
    routine: int        # the routine's `push bp / mov bp, sp`
    effect_id: int
    minutes: int
    value: int          # node byte 3
    flag: int           # node byte 4: remove_affect runs the handler if set
    far_writes: tuple   # every write through `es:` in the routine
    decrements: tuple   # record displacements the routine decrements


def find_game(title: str) -> pathlib.Path:
    stem, loader = TITLES[title]
    if loader == "START.EXE":
        return dosbox.find_game(stem)
    return dospod.find_game(stem)


def engine(game: pathlib.Path, title: str) -> dosaffectreads.Engine:
    """`dosaffectreads.load`, with the loader named per title."""
    loader = TITLES[title][1]
    ovr = (game / "GAME.OVR").read_bytes()
    img, _ = unexepack.unpack((game / loader).read_bytes())
    eng = dosaffectreads.Engine(title, ovr, img, dosovrmap.units(img, len(ovr)))
    dosaffectreads._find_dispatch(eng)
    dosaffectreads._find_find_affect(eng)
    dosaffectreads._find_remove_affect(eng)
    dosaffectreads._find_add_affect(eng)
    return eng


def _routine(ovr: bytes, at: int) -> int:
    return ovr.rfind(b"\x55\x89\xe5", 0, at)


def _far_writes(eng, start: int) -> tuple:
    out = []
    for insn in dosaffectreads.body(eng.ovr, start):
        dest = insn.op_str.split(",")[0]
        if insn.mnemonic in dosaffectreads.WRITES and "es:[" in dest:
            out.append((insn.address, f"{insn.mnemonic} {insn.op_str}"))
    return tuple(out)


def _decrements(eng, start: int) -> tuple:
    out = []
    for insn in dosaffectreads.body(eng.ovr, start):
        m = re.fullmatch(r"byte ptr es:\[di \+ (0x[0-9a-f]+)\]", insn.op_str)
        if insn.mnemonic == "dec" and m:
            out.append(int(m.group(1), 0))
    return tuple(out)


def timers(eng, minutes: int) -> list[Timer]:
    """Every `add_affect` call pushing the constant duration `minutes`."""
    out = []
    add = struct.pack("<HH", eng.add_affect[1], eng.add_affect[0])
    for m in ADD_CALL.finditer(eng.ovr):
        if m.group(5) != add or struct.unpack("<H", m.group(2))[0] != minutes:
            continue
        site = m.start(5) - 1
        start = _routine(eng.ovr, site)
        out.append(Timer(site, start, m.group(1)[0], minutes, m.group(3)[0],
                         m.group(4)[0], _far_writes(eng, start),
                         _decrements(eng, start)))
    return out


def _one(found: list, what: str):
    if len(found) != 1:
        raise ValueError(f"{what}: expected one, found {len(found)}")
    return found[0]


def id_sites(eng, eid: int) -> dict[str, list[int]]:
    """Every constant push of `eid` that reaches add/find/remove_affect.

    `mov al, eid / push ax` followed, within 24 bytes and before any other
    far call, by a far call to one of the three.
    """
    named = {eng.add_affect: "add_affect", eng.find_affect: "find_affect",
             eng.remove_affect: "remove_affect"}
    out: dict[str, list[int]] = {}
    for m in re.finditer(re.escape(bytes((0xB0, eid, 0x50))), eng.ovr):
        call = eng.ovr.find(b"\x9a", m.end(), m.end() + 24)
        if call < 0:
            continue
        off, seg = struct.unpack_from("<HH", eng.ovr, call + 1)
        if (seg, off) in named:
            out.setdefault(named[(seg, off)], []).append(m.start())
    return out


def gate(eng, eid: int) -> dict:
    """The one `find_affect(eid)` caller and the record bytes it tests first."""
    sites = [m.start() for m in dosaffectreads.FIND_CALL.finditer(eng.ovr)
             if eng.ovr[m.start() + 1] == eid]
    site = _one(sites, f"find_affect({eid}) callers")
    start = _routine(eng.ovr, site)
    tests = []
    for insn in dosaffectreads.body(eng.ovr, start):
        m = re.fullmatch(r"byte ptr es:\[di \+ (0x[0-9a-f]+)\], (\w+)", insn.op_str)
        if insn.mnemonic == "cmp" and m:
            tests.append(int(m.group(1), 0))
    return {"site": site, "routine": start, "record_tests": tuple(tests)}


def handler_is_empty(eng, eid: int) -> bool:
    """The id's table handler does nothing: `push bp ... retf` and no more."""
    where, at = eng.handlers[eid]
    ins = dosaffectreads.body(eng.code(where), at)
    text = [insn.mnemonic for insn in ins]
    return set(text) <= {"push", "mov", "pop", "retf"} and len(text) <= 5


def inspect(game: pathlib.Path, title: str) -> dict:
    """Every reading for one title, as addresses and values."""
    eng = engine(game, title)
    heals = timers(eng, HEAL_MINUTES)
    text = eng.ovr + eng.img
    result = {"title": title, "heal_strings": bool(re.search(rb"(?i)heal whom", text)),
              "table_ids": (min(eng.handlers), max(eng.handlers)),
              "chain": eng.chain, "heal": None}
    if not heals and not result["heal_strings"]:
        return result
    heal = _one(heals, "heal add_affect")
    cure = _one(timers(eng, CURE_MINUTES), "cure add_affect")
    result.update(
        heal=heal, cure=cure,
        heal_gate=gate(eng, heal.effect_id),
        heal_sites=id_sites(eng, heal.effect_id),
        heal_handler=eng.handlers.get(heal.effect_id),
        heal_handler_empty=(heal.effect_id in eng.handlers
                            and handler_is_empty(eng, heal.effect_id)),
        add_affect=eng.add_affect_at, find_affect=eng.find_affect_at)
    return result


def _print(f: dict) -> None:
    lo, hi = f["table_ids"]
    print(f"== {f['title']}: effect table ids {lo}-{hi}, chain head at record 0x{f['chain']:x}")
    if f["heal"] is None:
        print("   no heal routine: no 1440-minute add_affect and no 'Heal whom' prompt")
        return
    h, c, g = f["heal"], f["cure"], f["heal_gate"]
    print(f"   heal routine GAME.OVR:0x{h.routine:x}: add_affect at 0x{h.site:x} "
          f"id {h.effect_id} for {h.minutes} min, value {h.value}, flag {h.flag}; "
          f"far writes {list(h.far_writes) or 'none'}")
    print(f"   gate GAME.OVR:0x{g['routine']:x}: find_affect({h.effect_id}) at 0x{g['site']:x}, "
          f"after testing record " + ", ".join(f"0x{b:x}" for b in g["record_tests"]))
    where, at = f["heal_handler"]
    print(f"   handler {h.effect_id} {where}:0x{at:x} "
          f"{'empty' if f['heal_handler_empty'] else 'NOT empty'}; "
          f"constant uses {', '.join(f'{k} x{len(v)}' for k, v in sorted(f['heal_sites'].items()))}")
    print(f"   cure routine GAME.OVR:0x{c.routine:x}: id {c.effect_id} for {c.minutes} min, "
          f"value {c.value}, flag {c.flag}; decrements record "
          + (", ".join(f"0x{b:x}" for b in c.decrements) or "nothing"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", choices=sorted(TITLES), action="append")
    ap.add_argument("--game-dir", help="a directory holding GAME.OVR and its loader")
    a = ap.parse_args(argv)
    for title in a.title or list(TITLES):
        try:
            game = pathlib.Path(a.game_dir) if a.game_dir else find_game(title)
            _print(inspect(game, title))
        except FileNotFoundError as exc:
            print(f"{title}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
