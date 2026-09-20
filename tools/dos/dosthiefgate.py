#!/usr/bin/env python3
"""Read which byte DOS Pool of Radiance gates its thief abilities on.

    tools/dos/dosthiefgate.py                    # the archives' GAME.OVR
    tools/dos/dosthiefgate.py --game-dir DIR     # a directory holding it
    tools/dos/dosthiefgate.py --check            # exit 1 if a reading is missing

Four readings for `#560 (Does Pool of Radiance grant thief abilities off
class_bits, or off the level array and skill bytes?)`, each found by its
structure rather than by a committed address, so the same run answers for
any build of the overlay.

`backstab` finds the damage multiplier -- the only site that sign-extends
record `0x09C` and shifts it twice before a `mul` -- then the predicate
called immediately before it, and prints the byte that predicate tests.

`commands` finds the party-wide class test (a loop over the party list that
adds a class number to the record pointer and compares `class_levels[n]`
against zero), every menu entry that calls it and with which class number,
and the pick-lock roll that compares a d100 against record `0x078`.

`traps` finds the party aggregate over record `0x079` and the script
address the ECL VM asks for to get it.

`classbits` censuses every instruction that reads or writes record `0x0B0`.

Prints file offsets, short instruction windows and counts; the game's bytes
stay in the player's own directory.  Pool of Radiance's record layout
throughout (`goldbox/dos_port.py`): the per-class level array at `0x096`
with thief at slot 6, the thief skills at `0x077`-`0x07E`, `class_bits` at
`0x0B0`, and the party list's next pointer at `0x104`.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

import capstone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

PROLOGUE = b"\x55\x89\xe5"

#: `mov al, es:[di+0x9C] / cbw / shr ax,1 / shr ax,1 / inc ax / inc ax` --
#: the thief level turned into a damage multiplier.
MULTIPLIER = b"\x26\x8a\x85\x9c\x00\x98\xd1\xe8\xd1\xe8\x40\x40"
#: `mul dx`, which applies it to the rolled damage.
MUL_DX = b"\xf7\xe2"
#: `push cs / call rel16 / or al,al / je` -- a boolean overlay-local call.
BOOL_CALL = b"\x0e\xe8"
#: `cmp byte ptr es:[di+0x9C], 0` -- the thief slot of the level array.
THIEF_LEVEL_TEST = b"\x26\x80\xbd\x9c\x00\x00"
#: `add di, ax / cmp byte ptr es:[di+0x96], 0 / jle` -- one member's
#: `class_levels[n]` for a class number held in ax.
CLASS_SLOT_TEST = b"\x03\xf8\x26\x80\xbd\x96\x00\x00\x7e"
#: `cmp al, byte ptr es:[di+0x78]` -- a roll against Open Locks.
OPEN_LOCKS_TEST = b"\x26\x3a\x45\x78"
#: `mov al, 0x64 / push ax` -- the hundred handed to the die roller.
D100 = b"\xb0\x64\x50"
#: `mov al, byte ptr es:[di+0x79]` -- a read of Find Traps.
FIND_TRAPS_READ = b"\x26\x8a\x45\x79"
#: `mov ax, word ptr es:[di+0x104]` -- the party list's next pointer.
PARTY_NEXT = b"\x26\x8b\x85\x04\x01"

#: every encoding of a `class_bits` access, and what it is doing.
CLASS_BITS_SITES = {
    b"\x26\x22\x85\xb0\x00": "and al, es:[di+0xB0] (item usable by this class)",
    b"\x26\xc6\x85\xb0\x00\x00": "mov es:[di+0xB0], 0 (rebuild starts)",
    b"\x26\x00\x85\xb0\x00": "add es:[di+0xB0], al (rebuild accumulates)",
}

#: the DOS per-class level array's slots (`goldbox/dos_port.py` 0x096).
CLASS_SLOTS = {0: "cleric", 1: "druid", 2: "fighter", 3: "paladin",
               4: "ranger", 5: "magic-user", 6: "thief", 7: "monk"}


def _md() -> capstone.Cs:
    return capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)


def window(ovr: bytes, at: int, count: int = 6) -> list[str]:
    """A few instructions from `at`, as text, for the evidence line."""
    out = []
    for ins in _md().disasm(ovr[at:at + 5 * count], at):
        out.append(f"{ins.address:06x} {ins.mnemonic} {ins.op_str}")
        if len(out) == count:
            break
    return out


def routine_start(ovr: bytes, at: int) -> int:
    """The Turbo Pascal prologue this offset sits in."""
    return ovr.rfind(PROLOGUE, 0, at + 1)


def near_target(ovr: bytes, call: int) -> int:
    """Where the `E8 rel16` at `call` goes."""
    return call + 3 + struct.unpack_from("<h", ovr, call + 1)[0]


def near_callers(ovr: bytes, target: int, lo: int = 0, hi: int | None = None):
    """Every `push cs / call rel16` in the overlay that reaches `target`."""
    hi = len(ovr) if hi is None else hi
    for p in range(lo, hi - 4):
        if ovr[p:p + 2] == BOOL_CALL and near_target(ovr, p + 1) == target:
            yield p + 1


def backstab(ovr: bytes) -> dict:
    """The multiplier site, the predicate it consults and that predicate's gate."""
    at = ovr.find(MULTIPLIER)
    if at < 0:
        return {}
    applied = ovr.find(MUL_DX, at, at + 0x18)
    call = ovr.rfind(BOOL_CALL, at - 0x30, at)
    pred = near_target(ovr, call + 1) if call > 0 else -1
    gate = ovr.find(THIEF_LEVEL_TEST, pred, pred + 0x200) if pred > 0 else -1
    return dict(multiplier=at, mul=applied, predicate=pred, gate=gate,
                gate_branch=ovr[gate + 6] if gate > 0 else None,
                uses=sorted(set(near_callers(ovr, pred))) if pred > 0 else [])


def class_gate(ovr: bytes) -> dict:
    """The `party has a character of class n` helper, and who asks it what.

    Several routines add a class number to a record pointer and test the
    level array; the one wanted is the one that walks the party list and is
    called with a class number in `al`.
    """
    at = ovr.find(CLASS_SLOT_TEST)
    while at >= 0:
        start = routine_start(ovr, at)
        walks = ovr.find(PARTY_NEXT, start, start + 0x120) > 0
        asked = [(call, ovr[call - 3]) for call in near_callers(ovr, start)
                 if ovr[call - 4] == 0xB0 and ovr[call - 2] == 0x50]
        if walks and asked:
            return dict(routine=start, test=at, walks_party=walks,
                        callers=asked)
        at = ovr.find(CLASS_SLOT_TEST, at + 1)
    return {}


def pick_locks(ovr: bytes) -> dict:
    """The roll the Pick option makes, and what it compares against."""
    at = ovr.find(OPEN_LOCKS_TEST)
    if at < 0:
        return {}
    return dict(test=at, routine=routine_start(ovr, at),
                d100=ovr.rfind(D100, at - 0x20, at),
                branch=ovr[at + 4])


def find_traps(ovr: bytes) -> dict:
    """The party aggregate over record 0x079, and the script address for it."""
    at = ovr.find(FIND_TRAPS_READ)
    if at < 0:
        return {}
    reads = []
    p = at
    while 0 <= p < at + 0x60:
        reads.append(p)
        p = ovr.find(FIND_TRAPS_READ, p + 1, at + 0x60)
    selector = ovr.rfind(b"\x3d", at - 0x20, at)
    script = struct.unpack_from("<H", ovr, selector + 1)[0] if selector > 0 else None
    return dict(reads=reads, selector=selector, script_address=script,
                walks_party=ovr.find(PARTY_NEXT, at, at + 0x60) > 0)


def class_bits(ovr: bytes) -> list[tuple[int, str]]:
    """Every instruction in the overlay that touches record 0x0B0."""
    out = []
    for pattern, meaning in CLASS_BITS_SITES.items():
        p = ovr.find(pattern)
        while p >= 0:
            out.append((p, meaning))
            p = ovr.find(pattern, p + 1)
    return sorted(out)


def _game_dir(arg: str | None) -> pathlib.Path:
    if arg:
        return pathlib.Path(arg)
    from tools.dos import dosbox
    return dosbox.find_game()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game-dir", help="directory holding GAME.OVR")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 unless every reading was found")
    args = ap.parse_args(argv)
    ovr = (_game_dir(args.game_dir) / "GAME.OVR").read_bytes()

    b = backstab(ovr)
    print("backstab")
    if b:
        print(f"  multiplier   GAME.OVR:0x{b['multiplier']:x}"
              f"  thief level >> 2, + 2, applied by mul at 0x{b['mul']:x}")
        print(f"  predicate    GAME.OVR:0x{b['predicate']:x}, called from "
              + ", ".join(f"0x{c:x}" for c in b["uses"]))
        print(f"  its gate     GAME.OVR:0x{b['gate']:x}"
              f"  cmp byte es:[di+0x9C], 0 / "
              f"{'jle' if b['gate_branch'] == 0x7e else hex(b['gate_branch'])}")
        for line in window(ovr, b["multiplier"], 7):
            print("    " + line)
    else:
        print("  not found")

    g = class_gate(ovr)
    print("party class test")
    if g:
        print(f"  routine      GAME.OVR:0x{g['routine']:x}, walks the party "
              f"list: {g['walks_party']}; tests class_levels[n] at "
              f"0x{g['test'] + 2:x}")
        for call, n in g["callers"]:
            print(f"    asked for class {n} ({CLASS_SLOTS.get(n, '?')}) "
                  f"at 0x{call:x}")
    else:
        print("  not found")

    p = pick_locks(ovr)
    print("pick locks")
    if p:
        print(f"  roll         GAME.OVR:0x{p['d100']:x} mov al, 0x64 -> "
              f"cmp al, es:[di+0x78] at 0x{p['test']:x} / "
              f"{'ja' if p['branch'] == 0x77 else hex(p['branch'])}")
        print(f"  routine      GAME.OVR:0x{p['routine']:x}")
    else:
        print("  not found")

    t = find_traps(ovr)
    print("find traps")
    if t:
        print(f"  aggregate    GAME.OVR:0x{t['reads'][0]:x}, {len(t['reads'])}"
              f" reads of record 0x079, walks the party list: "
              f"{t['walks_party']}")
        print(f"  script asks  0x{t['script_address']:04X}"
              f"  (cmp ax, imm16 at 0x{t['selector']:x})")
    else:
        print("  not found")

    sites = class_bits(ovr)
    print(f"class_bits (record 0x0B0): {len(sites)} sites in the overlay")
    for at, meaning in sites:
        print(f"  0x{at:06x}  {meaning}")

    if args.check and not (b and g and p and t and sites):
        print("a reading is missing", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
