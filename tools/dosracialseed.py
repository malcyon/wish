#!/usr/bin/env python3
"""Read what DOS Pool of Radiance seeds a new character with, and what 97 does.

    tools/dosracialseed.py                     # the archives' GAME.OVR, START.EXE
    tools/dosracialseed.py --game-dir DIR      # a directory holding both files

The two readings behind `#247 (Nobody knows whether innate effect 97 is
racial or the constitution bonus)`, taken out of the engine rather than out
of any specimen, so that no edited save can poison them.

`creation_table` finds character creation's switch on the record's race byte
(`GAME.OVR:0x1A12A` in the 1.3 build -- found by its shape, not its address)
and lists, per race, every `add_affect(id, duration, data, flag)` it pushes.
Nothing between the race read and the last call reads any other byte of the
record, so the ids are the race's and nothing else's.

`handlers` follows an effect id through the handler table the engine fills
at start-up -- `lcall [di + table]` in the dispatcher, one far pointer an id,
each entry stored by a `mov ax, off / mov dx, seg / mov [entry], ax /
mov [entry+2], dx` quartet -- to the overlay unit's public-entry stub and on
to the handler's code, and reads what the handler tests and adds: the
save-type gate on `[0x682A]`, the read of the record's constitution byte,
the band table, and the roll accumulator `[0x6816]` it adds to.

Prints tables and file offsets only; the game's bytes stay in the player's
own directory.  Pool of Radiance's layout throughout: race at record `0x2E`,
constitution at `0x14` (`goldbox/dos_layout.py`).
"""

from __future__ import annotations

import argparse
import pathlib
import re
import struct
import sys

import capstone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import dosovrmap, unexepack  # noqa: E402

#: `lcall 0xB0:0x52`, `add_affect` (`docs/162-spc-permanence.md`).
ADD_AFFECT = b"\x9a\x52\x00\xb0\x00"
#: `mov al, byte ptr es:[di + 0x2E]` -- the record's race byte.
RACE_READ = b"\x26\x8a\x45\x2e"
#: `shl di, 1 / shl di, 1 / lcall [di + imm16]` -- the handler dispatch.
DISPATCH = b"\xd1\xe7\xd1\xe7\xff\x9d"
#: `mov ax, imm / mov dx, imm / mov [imm], ax / mov [imm], dx` -- one entry
#: of the handler table being filled.
TABLE_FILL = re.compile(rb"\xb8(..)\xba(..)\xa3(..)\x89\x16(..)", re.S)

RACE_NAMES = {1: "dwarf", 2: "elf", 3: "gnome", 4: "half-elf",
              5: "halfling", 6: "half-orc", 7: "human"}
SAVE_COLUMNS = {0: "paralysis/poison/death", 1: "petrification", 2: "wands",
                3: "breath", 4: "spell"}


def _md() -> capstone.Cs:
    return capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)


def _imm(op_str: str) -> int | None:
    try:
        return int(op_str.rsplit(", ", 1)[-1], 0)
    except ValueError:
        return None


def creation_switch(ovr: bytes) -> int:
    """File offset of the race read that opens the creation switch.

    The anchor is a read of the race byte followed at once by `cmp al, imm`,
    with at least five `add_affect` calls in the 0x200 bytes after it.  The
    other 134 race reads in the overlay index tables or compare classes.
    """
    for m in re.finditer(re.escape(RACE_READ), ovr):
        at = m.start()
        if ovr[at + 4] != 0x3C:
            continue
        if ovr[at:at + 0x200].count(ADD_AFFECT) >= 5:
            return at
    raise ValueError("no creation switch: race read + cmp + add_affect calls")


def creation_table(ovr: bytes) -> dict[int, list[tuple[int, int, int, int]]]:
    """Race byte -> the `(id, duration, data, flag)` tuples creation pushes.

    Walks the switch from `creation_switch` to the join every branch jumps
    to -- the first `jmp` seen names it -- tracking `cmp al, N` as the race
    under test and the immediates pushed before each `lcall 0xB0:0x52` as
    that call's arguments.  Races with no branch are absent from the result.
    """
    start = creation_switch(ovr)
    out: dict[int, list[tuple[int, int, int, int]]] = {}
    race: int | None = None
    pushed: list[int | None] = []
    last: int | None = None
    join: int | None = None
    for insn in _md().disasm(ovr[start:start + 0x200], start):
        if join is not None and insn.address >= join:
            break
        m, ops = insn.mnemonic, insn.op_str
        if m == "cmp" and ops.startswith("al, "):
            race = _imm(ops)
            pushed = []
        elif m == "mov" and ops.startswith("al, "):
            last = _imm(ops)
        elif m == "xor" and ops == "ax, ax":
            last = 0
        elif m == "push" and ops == "ax":
            pushed.append(last)
        elif m == "lcall" and ops == "0xb0, 0x52":
            if race is None or len(pushed) < 4 or None in pushed[-4:]:
                raise ValueError(f"unreadable add_affect at 0x{insn.address:x}")
            eid, duration, data, flag = pushed[-4:]
            out.setdefault(race, []).append((eid, duration, data, flag))
            pushed = []
        elif m == "jmp" and join is None:
            join = _imm(ops)
    return out


def _fills(ovr: bytes, base: int) -> dict[int, tuple[int, int]]:
    out: dict[int, tuple[int, int]] = {}
    for m in TABLE_FILL.finditer(ovr):
        off, seg, lo, hi = (struct.unpack("<H", g)[0] for g in m.groups())
        if hi != lo + 2 or lo < base or (lo - base) % 4 or (lo - base) // 4 > 255:
            continue
        out[(lo - base) // 4] = (seg, off)
    return out


def dispatch_table(ovr: bytes) -> int:
    """The data-segment address of the handler table.

    The overlay has more than one `shl di, 1 x2 / lcall [di + imm]`
    dispatcher; the handler table is the one whose entries the fill
    quartets store into (180 of them in the 1.3 build, against far fewer for the
    others).
    """
    best = None
    for m in re.finditer(re.escape(DISPATCH), ovr):
        base = struct.unpack_from("<H", ovr, m.end())[0]
        n = len(_fills(ovr, base))
        if best is None or n > best[0]:
            best = (n, base)
    if best is None or best[0] == 0:
        raise ValueError("no handler dispatch with a code-filled table")
    return best[1]


def handler_pointers(ovr: bytes) -> dict[int, tuple[int, int]]:
    """Effect id -> `(seg, off)` far pointer, from the table-fill code."""
    return _fills(ovr, dispatch_table(ovr))


def handler_offset(ovr: bytes, image: bytes, eid: int) -> int:
    """`GAME.OVR` file offset of the handler for `eid`."""
    seg, off = handler_pointers(ovr)[eid]
    where, fileoff = dosovrmap.resolve(dosovrmap.units(image, len(ovr)), seg, off)
    if where != "GAME.OVR" or fileoff is None:
        raise ValueError(f"handler {eid} at {seg:04x}:{off:04x} is not an overlay entry")
    return fileoff


def read_band_handler(ovr: bytes, at: int) -> dict:
    """What a constitution-band handler tests and adds, read from `at`.

    Returns `save_types` (the values `[0x682A]` is compared with before the
    record is read), `reads_constitution`, `bands` as `(low, high, bonus)`
    and `adds_to_roll` (a store to `[0x6816]`).
    """
    types: list[int] = []
    bands: list[tuple[int, int, int]] = []
    reads = adds = False
    low = high = None
    for insn in _md().disasm(ovr[at:at + 0x100], at):
        m, ops = insn.mnemonic, insn.op_str
        if m == "retf":
            break
        if m == "cmp" and ops.startswith("byte ptr [0x682a], "):
            types.append(_imm(ops))
        elif m == "mov" and ops == "al, byte ptr es:[di + 0x14]":
            reads = True
        elif m == "cmp" and ops.startswith("al, ") and reads:
            if low is None:
                low = _imm(ops)
            else:
                high = _imm(ops)
        elif m == "mov" and ops.startswith("byte ptr [bp - 1], ") and low is not None:
            bands.append((low, high if high is not None else low, _imm(ops)))
            low = high = None
        elif m == "mov" and ops == "byte ptr [0x6816], al":
            adds = True
    return dict(file=at, save_types=types, reads_constitution=reads,
                bands=bands, adds_to_roll=adds)


def handlers(ovr: bytes, image: bytes, ids=(90, 97)) -> dict[int, dict]:
    return {eid: read_band_handler(ovr, handler_offset(ovr, image, eid))
            for eid in ids}


def _game_dir(arg: str | None) -> pathlib.Path:
    if arg:
        return pathlib.Path(arg)
    from tools import dosbox
    return dosbox.find_game()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game-dir", help="directory holding GAME.OVR and START.EXE")
    ap.add_argument("--ids", default="90,97",
                    help="effect ids whose handlers to read (default 90,97)")
    args = ap.parse_args(argv)
    game = _game_dir(args.game_dir)
    ovr = (game / "GAME.OVR").read_bytes()
    image, _ = unexepack.unpack((game / "START.EXE").read_bytes())

    at = creation_switch(ovr)
    print(f"creation switch on record 0x2E at GAME.OVR:0x{at:x}")
    for race, calls in sorted(creation_table(ovr).items()):
        ids = ", ".join(f"{c[0]} ({c[1]}, 0x{c[2]:02x}, {c[3]})" for c in calls)
        print(f"  race {race} {RACE_NAMES.get(race, '?'):9s} {ids}")
    base = dispatch_table(ovr)
    print(f"handler table at ds:0x{base:04x}, {len(handler_pointers(ovr))} entries filled")
    for eid, h in handlers(ovr, image, [int(x) for x in args.ids.split(",")]).items():
        cols = ", ".join(SAVE_COLUMNS.get(t, str(t)) for t in h["save_types"])
        print(f"  effect {eid}: GAME.OVR:0x{h['file']:x}; save types {h['save_types']}"
              f" ({cols}); reads constitution {h['reads_constitution']};"
              f" adds to roll {h['adds_to_roll']}")
        for lo, hi, bonus in h["bands"]:
            print(f"    constitution {lo:2d}-{hi:2d}: +{bonus}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
