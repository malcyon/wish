#!/usr/bin/env python3
"""Find a Gold Box trainer's tables by the instruction that reads the record.

A trainer is a few dozen routines scattered through one overlay, and the
addresses are different in every title -- of the 25 Pool of Radiance addresses
`docs/135-levelling.md` lists, **not one means anything in Curse of the Azure
Bonds**. So the way in is not an address: it is that every one of those
routines has to touch the character record, and the record sits at a fixed
address while the overlay runs.

    $0EE9  DD 9A 7C   CMP $7C9A,X        <- save_paralysis, so this is the
    $0EEC  B0 03      BCS $0EF1             saving-throw builder, and the
    $0EEE  9D 9A 7C   STA $7C9A,X           table it reads is two lines up

`--refs` prints every absolute-mode instruction in the overlay whose operand
lands in the record, against `goldbox/layout.py`'s field names. That census is
what located Curse's saving throws (`$0E5E`), thief skills (`$0FAD`), turning
level (`$113F`), constitution hit points (`$126D`) and hit-die roll (`$15E1`),
none of which shares an address with Pool of Radiance's. `--callers` then walks
back up: who `JSR`s the routine you just found, which is how the level-up
sequence at `$2041` was assembled out of the eight routines it calls.

**The record base is the lever and it is per-title.** Pool of Radiance keeps
the working character at `$6B00` and Curse and Silver Blades at `$7C00`;
`tests/test_curse.py` proves Curse's by round-tripping an exported `\\x02`
character read at that address, and Pool of Radiance's falls out of its own
thief-skill routine, `$1FEC LDX $6BCB / ... / STA $6BA5,Y` -- `level_thief` at
`0x0CB` and the eight skills at `0x0A5`. Pass `--record` for a title nobody has
fixed one for, and a wrong guess shows up immediately as a census with no
`level`, no `experience` and no `class_bits` in it.

**A hit is a claim about bytes, not proof they are code.** `tools/d6502.py`
says the same thing at more length: a run of PETSCII decodes as plausible
instructions, so a lone `STA $7C9A` inside a bitmap is a coincidence, and the
way to tell is that a real routine's hits come in clusters two or three
instructions apart. Scanning all 411 Curse files for `spells_castable` found
two hits, both inside `PIC78` and `BODY41`, which is what a coincidence looks
like.

Nothing here needs an emulator: it reads the overlay off the player's own
disks through `tools/gamedisks.py`.

    tools/trainerscan.py --game curse --file GEN --refs
    tools/trainerscan.py --game curse --file GEN --callers 0x0DD0
    tools/trainerscan.py --game curse --file ECL65 --base 8000 --refs
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import layout  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools import gamedisks  # noqa: E402
from tools.d6502 import M_ABS, M_ABX, M_ABY, T  # noqa: E402

#: Where each title's overlays actually run, whatever their PRG header says,
#: and where the working character record sits while they do.
#:
#: `GEN` and `CAMP` declare four different load addresses between them and all
#: run at `$0800` -- `tools/coldread.py` carries the same constant and the same
#: reason. `ECL65` is the exception and is why `--base` exists: Curse's copy
#: runs at `$8000`, proved by its own `LDA $888D,X` reading the spell-slot rows
#: that sit at payload offset `0x88D`.
TITLES = {
    "pool": ("pool-of-radiance", "POOL*.[dD]64", 0x0800, 0x6B00),
    "curse": ("curse-of-the-azure-bonds", "CURSE*.[dD]64", 0x0800, 0x7C00),
    "ssb": ("secret-of-the-silver-blades", "SILVER*.[dD]64", 0x0800, 0x7C00),
}

#: How far past the record's own 256 bytes to keep looking. A save slot is 256
#: bytes and an export is 580, and the roster block past `0x100` is where
#: `hp_current` and `roster_in_use` live -- both of which a trainer writes.
RECORD_SPAN = 0x200


def _field(offset: int) -> str:
    """`goldbox/layout.py`'s name for a record offset, with `+n` inside a field."""
    for f in layout.LAYOUT:
        if f.offset <= offset < f.offset + f.size:
            if offset == f.offset:
                return f.name
            return f"{f.name}+{offset - f.offset}"
    return "?"


def overlay(title: str, name: str) -> bytes:
    """One overlay's payload off whichever side carries it, longest copy first.

    Longest wins for the reason `tests/gamedata.py::curse_file` gives: the
    sides disagree, and a truncated copy of a file is still a copy of it.
    """
    key, glob, _, _ = TITLES[title]
    where = gamedisks.find(key)
    if where is None:
        variable = gamedisks.entry(key).get(gamedisks.ENV, "?")
        raise SystemExit(f"trainerscan.py: no {key} disks here; set ${variable}")
    want = name.encode() if isinstance(name, str) else name
    best = None
    for path in sorted(pathlib.Path(where).glob(glob)):
        try:
            disk = D64.open(str(path))
            entry = disk.find(want)
            if entry is None:
                continue
            data = split_load_address(disk.read_file(entry))[1]
        except Exception:
            continue                     # a broken chain is not a candidate
        if best is None or len(data) > len(best):
            best = data
    if best is None:
        raise SystemExit(f"trainerscan.py: no {title} side carries {name}")
    return best


def references(data: bytes, base: int, record: int):
    """Every absolute-mode instruction whose operand lands in the record.

    Yields `(address, mnemonic, suffix, record offset)`, in address order.
    The scan is one pass over every byte rather than a decode from an entry
    point: a trainer's tables sit between its routines, so a linear decode
    desynchronises and skips exactly the code being looked for.
    """
    suffix = {M_ABS: "", M_ABX: ",X", M_ABY: ",Y"}
    for i in range(len(data) - 2):
        op = data[i]
        if op not in T:
            continue
        mnemonic, mode = T[op]
        if mode not in suffix:
            continue
        target = data[i + 1] | data[i + 2] << 8
        if record <= target < record + RECORD_SPAN:
            yield base + i, mnemonic, suffix[mode], target - record


def callers(data: bytes, base: int, target: int):
    """Every `JSR` and `JMP` to an address. Yields `(address, mnemonic)`."""
    for opcode, mnemonic in ((0x20, "JSR"), (0x4C, "JMP")):
        want = bytes((opcode, target & 0xFF, target >> 8))
        start = 0
        while True:
            at = data.find(want, start)
            if at < 0:
                break
            yield base + at, mnemonic
            start = at + 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", default="curse", choices=sorted(TITLES))
    ap.add_argument("--file", default="GEN", help="overlay name, e.g. GEN")
    ap.add_argument("--base", help="where it runs, hex; default per title")
    ap.add_argument("--record", help="the record's address, hex")
    ap.add_argument("--refs", action="store_true",
                    help="census of record references (the default)")
    ap.add_argument("--callers", help="who JSRs or JMPs to this address, hex")
    ap.add_argument("--field", help="only this record field")
    args = ap.parse_args(argv)

    _, _, base, record = TITLES[args.game]
    if args.base:
        base = int(args.base.lstrip("$"), 16)
    if args.record:
        record = int(args.record.lstrip("$"), 16)
    data = overlay(args.game, args.file)
    print(f"{args.file}: {len(data)} bytes at ${base:04X}-${base + len(data):04X}, "
          f"record at ${record:04X}")

    if args.callers:
        target = int(args.callers.lstrip("$"), 16)
        found = list(callers(data, base, target))
        for at, mnemonic in found:
            print(f"  ${at:04X}  {mnemonic} ${target:04X}")
        if not found:
            print(f"  nothing reaches ${target:04X}")
        return 0

    grouped: dict[int, list[str]] = {}
    for at, mnemonic, suffix, offset in references(data, base, record):
        grouped.setdefault(offset, []).append(f"{mnemonic}{suffix}@${at:04X}")
    for offset in sorted(grouped):
        name = _field(offset)
        if args.field and not name.startswith(args.field):
            continue
        print(f"  0x{offset:03X} {name:26s} {' '.join(grouped[offset])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
