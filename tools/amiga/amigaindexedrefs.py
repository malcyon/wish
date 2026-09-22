#!/usr/bin/env python3
"""The ways an Amiga executable reaches a record byte that a displacement
search cannot see: the indexed form, a base register set by `lea`, and an
index register carrying the offset.

`tools/amiga/amigarecordrefs.py` finds `d16(An)` -- `move.b $85(a3), d0` --
by its displacement word, and says in its own docstring that an offset can be
reached without one.  Two forms do it on a SAS/Lattice build:

* **`d8(An,Xn)`**, the indexed form, `move.b $84(a3, d0.w), d1`.  Its
  displacement is the low byte of a brief extension word whose high byte
  names the index register, so a word search for `$0084` never matches it.
  This is how an array inside the record is walked.
* **`lea d16(An), Am`** followed by `(Am)`, `(Am)+` or `d(Am)`.  A `memcpy`
  of a run of fields starts this way, and so does an `addq` on a field the
  compiler chose to address through a spare register.  The `lea` names a
  base at or below the byte, and the byte is reached from there.

The 68000's `d8` is **signed**, so from a register holding the record's start
it reaches only `0x00`-`0x7F`.  A byte at `0x80` or above can be reached in
the indexed form only from a base past the start, or through an index
register that carries the offset.  Three searches cover that, each printed
under the byte it reaches:

* **the displacement byte itself**, whatever it decodes to --
  `-$7c(a3, d0.w)` is byte `0x84`, and is what a base at record + `0x100`
  would use;
* **a rebased register**: `lea d16(An), Am` or `adda #imm, Am`, followed in
  the same straight-line run by `(Am)`, `(Am)+`, `-(Am)`, `d16(Am)` or
  `d8(Am,Xn)` whose base plus displacement lands on the byte (an indexed use
  is listed when it lands up to `--reach` below it);
* **an index carrying the offset**: `moveq`, `move #imm`, `movea #imm` or
  `addi #imm` into a register, followed in the same run by `d8(Ax,Rn)`
  indexed by that register, whose immediate plus displacement is the byte.

A run stops at a branch, a return, a call when the register is one a call
may clobber, or a write to the register that is not a constant step.

A fourth list is not indexed at all: a `.w`, `.l` or `movem` access at
`d16(An)` one to three bytes below the byte, which covers it without the
byte's own displacement ever appearing.

This prints every candidate of every kind for each record offset asked for,
across every CODE hunk, decoding each from its own start so a hit is an
instruction and not a byte pair.  A `lea` is listed for bases from `--reach`
below the byte up to the byte itself, and **a `lea` is only a lead**: the
listing after it says how far the copy runs, and that has to be read.

    tools/amiga/amigaindexedrefs.py --adf curse-A.adf --exe /Curse f6 f9 fa
    tools/amiga/amigaindexedrefs.py --file PATH/TO/program 84 87 88 --reach 8

Empty indexed, rebased and index lists and a `lea` list whose spans all
stop short of the byte is what "no site in this executable" looks like once
every form here and `amigarecordrefs.py`'s `d16(An)` have been asked.  Everything is read; nothing is written.
"""

from __future__ import annotations

import argparse
import functools
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

import capstone  # noqa: E402

from tools.amiga.amiga68k import load  # noqa: E402
from tools.amiga.amigarecordrefs import code_ranges, hunk_sites  # noqa: E402

#: capstone's rendering of a 68000 indexed operand: `$2a(a3, d4.w)`,
#: `-$7c(a3, d0.w)` for a displacement byte of 0x84, `(a3, d0.w)` for zero.
INDEXED = re.compile(r"(-?\$[0-9a-f]+)?\((a\d), ([da]\d)\.[wl]\)")

#: How far back from the extension word an instruction may start: the
#: opcode word alone, or one or two extension words of a first operand.
BACK = (2, 4, 6)

#: How many instructions after a setter a run is followed.
WINDOW = 16

#: Instructions that end a straight-line run.
_BRANCHES = {"bra", "bhi", "bls", "bcc", "bcs", "bne", "beq", "bvc", "bvs",
             "bpl", "bmi", "bge", "blt", "bgt", "ble", "jmp", "rts", "rte",
             "rtr", "trap", "illegal", "stop"}

#: Calls, and the registers a SAS/Lattice call may clobber.
_CALLS = {"jsr", "bsr"}
_SCRATCH = {"d0", "d1", "a0", "a1"}

#: Mnemonics whose last operand is read, not written.
_READS_ONLY = {"cmp", "cmpa", "cmpi", "cmpm", "tst", "btst", "pea", "chk"}

_SIZE = {"b": 1, "w": 2, "l": 4}


def _signed(text: str | None) -> int:
    """`-$7c` -> -0x7C; `$84` -> 0x84; an absent displacement -> 0."""
    if not text:
        return 0
    return -int(text[2:], 16) if text.startswith("-") else int(text[1:], 16)


def indexed_sites(data: bytes, displacement: int) -> list[tuple[int, int, str]]:
    """`(file offset, hunk, instruction)` for every `d8(An,Xn)` whose
    displacement byte is `displacement`, over every CODE hunk.

    The byte is compared, not the signed value capstone prints, so 0x84
    matches `-$7c(a3, d0.w)`."""
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    found: list[tuple[int, int, str]] = []
    for number, start, end in code_ranges(data):
        for at in range(start, end - 1, 2):
            # A 68000 brief extension word: D/A, register, size in the high
            # byte with bits 10-8 clear; the displacement in the low byte.
            if data[at + 1] != displacement or data[at] & 0x07:
                continue
            for back in BACK:
                begin = at - back
                if begin < start:
                    continue
                decoded = next(iter(md.disasm(data[begin:at + 10], begin)), None)
                if decoded is None or begin + decoded.size < at + 2:
                    continue
                if any(_signed(m.group(1)) & 0xFF == displacement
                       for m in INDEXED.finditer(decoded.op_str)):
                    found.append((begin, number,
                                  f"{decoded.mnemonic} {decoded.op_str}"))
                    break
    return found


def lea_bases(data: bytes, displacement: int,
              reach: int) -> list[tuple[int, int, int, str]]:
    """`(file offset, hunk, base, instruction)` for every `lea d16(An), Am`
    whose base lies within `reach` bytes below `displacement`."""
    found = []
    for base in range(max(displacement - reach, 0), displacement + 1):
        for offset, number, text in hunk_sites(data, base):
            if text.startswith("lea"):
                found.append((offset, number, base, text))
    return sorted(found)


def _operands(op_str: str) -> list[str]:
    """Split an operand string at the commas outside parentheses."""
    parts, depth, current = [], 0, ""
    for char in op_str:
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
            continue
        depth += char == "("
        depth -= char == ")"
        current += char
    if current.strip():
        parts.append(current.strip())
    return parts


def _setters(data: bytes, start: int, end: int):
    """`(offset, kind, register, value)` for every opcode word in the range
    that loads a constant base or index: kind is `lea`, `adda`, `move`,
    `moveq`, `movea` or `addi`; register is `a0`-`a7` or `d0`-`d7`."""
    for at in range(start, end - 3, 2):
        word, = struct.unpack_from(">H", data, at)
        high = (word >> 9) & 7
        s16, = struct.unpack_from(">h", data, at + 2)
        s32 = (struct.unpack_from(">i", data, at + 2)[0]
               if at + 6 <= end else None)
        if word & 0xF1F8 == 0x41E8:
            yield at, "lea", f"a{high}", s16
        elif word & 0xF1FF == 0xD0FC:
            yield at, "adda", f"a{high}", s16
        elif word & 0xF1FF == 0xD1FC and s32 is not None:
            yield at, "adda", f"a{high}", s32
        elif word & 0xF1FF == 0x303C:
            yield at, "move", f"d{high}", s16
        elif word & 0xF1FF == 0x203C and s32 is not None:
            yield at, "move", f"d{high}", s32
        elif word & 0xF100 == 0x7000:
            yield at, "moveq", f"d{high}", (word & 0xFF) - ((word & 0x80) << 1)
        elif word & 0xF1FF == 0x307C:
            yield at, "movea", f"a{high}", s16
        elif word & 0xF1FF == 0x207C and s32 is not None:
            yield at, "movea", f"a{high}", s32
        elif word & 0xFFF8 == 0x0640:
            yield at, "addi", f"d{word & 7}", s16
        elif word & 0xFFF8 == 0x0680 and s32 is not None:
            yield at, "addi", f"d{word & 7}", s32


_STEP = re.compile(r"#\$([0-9a-f]+), (a\d)$")


def _run(md, data: bytes, at: int, end: int, register: str):
    """The setter at `at` and the straight-line run after it, as capstone
    instructions, the setter first; stops as the module docstring says."""
    decoded = list(md.disasm(data[at:min(at + 6 * (WINDOW + 1) + 6, end)], at,
                             count=WINDOW + 1))
    if not decoded:
        return
    yield decoded[0]
    for one in decoded[1:]:
        name = one.mnemonic.split(".")[0]
        yield one
        if name in _BRANCHES or name.startswith("db"):
            return
        if name in _CALLS and register in _SCRATCH:
            return
        operands = _operands(one.op_str)
        if (operands and operands[-1] == register and name not in _READS_ONLY
                and not (name in ("addq", "subq", "adda", "suba")
                         and _STEP.search(one.op_str))):
            return


def _uses(one, register: str, base: int):
    """`(effective offset, indexed, base after)` for each operand of `one`
    that reaches memory through `register` holding `base`."""
    size = _SIZE.get(one.mnemonic.rpartition(".")[2], 1)
    found = []
    for operand in _operands(one.op_str):
        if operand == f"({register})":
            found.append((base, False))
        elif operand == f"({register})+":
            found.append((base, False))
            base += size
        elif operand == f"-({register})":
            base -= size
            found.append((base, False))
        else:
            match = re.fullmatch(r"(-?\$[0-9a-f]+)?\(" + register +
                                 r"(, [da]\d\.[wl])?\)", operand)
            if match:
                found.append((base + _signed(match.group(1)),
                              bool(match.group(2))))
    step = _STEP.search(one.op_str)
    name = one.mnemonic.split(".")[0]
    if step and step.group(2) == register and name in ("addq", "adda",
                                                       "subq", "suba"):
        delta = int(step.group(1), 16)
        base += -delta if name.startswith("sub") else delta
    return found, base


@functools.lru_cache(maxsize=4)
def _all_rebased(data: bytes) -> tuple:
    """Every use of a register set by `lea d16(An)` or `adda #imm`, as
    `(setter offset, hunk, setter, use offset, use, effective, indexed)`."""
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    found = []
    for number, start, end in code_ranges(data):
        for at, kind, register, value in _setters(data, start, end):
            if kind not in ("lea", "adda"):
                continue
            run = iter(_run(md, data, at, end, register))
            setter = next(run, None)
            if setter is None or not setter.mnemonic.startswith(kind) \
                    or not setter.op_str.endswith(register):
                continue
            base = value
            for one in run:
                uses, base = _uses(one, register, base)
                for effective, indexed in uses:
                    found.append((at, number,
                                  f"{setter.mnemonic} {setter.op_str}",
                                  one.address,
                                  f"{one.mnemonic} {one.op_str}",
                                  effective, indexed))
    return tuple(found)


def rebased_sites(data: bytes, displacement: int, reach: int = 0) -> list:
    """`(setter offset, hunk, setter, use offset, use)` for every use of a
    rebased register that lands on `displacement`, or, for an indexed use,
    up to `reach` bytes below it."""
    return [(at, number, setter, where, use)
            for at, number, setter, where, use, effective, indexed
            in _all_rebased(data)
            if effective == displacement
            or (indexed and displacement - reach <= effective < displacement)]


@functools.lru_cache(maxsize=4)
def _all_indexes(data: bytes) -> tuple:
    """Every `d8(Ax,Rn)` indexed by a register just loaded with a constant,
    as `(setter offset, hunk, setter, use offset, use, constant + d8)`."""
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    found = []
    for number, start, end in code_ranges(data):
        for at, kind, register, value in _setters(data, start, end):
            if kind in ("lea", "adda"):
                continue
            run = iter(_run(md, data, at, end, register))
            setter = next(run, None)
            if setter is None or not setter.mnemonic.startswith(kind) \
                    or not setter.op_str.endswith(register):
                continue
            for one in run:
                for match in INDEXED.finditer(one.op_str):
                    if match.group(3) == register:
                        found.append((at, number,
                                      f"{setter.mnemonic} {setter.op_str}",
                                      one.address,
                                      f"{one.mnemonic} {one.op_str}",
                                      value + _signed(match.group(1))))
    return tuple(found)


def index_sites(data: bytes, displacement: int) -> list:
    """`(setter offset, hunk, setter, use offset, use)` for every indexed
    access whose index constant plus displacement is `displacement`."""
    return [(at, number, setter, where, use)
            for at, number, setter, where, use, effective
            in _all_indexes(data) if effective == displacement]


def wide_sites(data: bytes, displacement: int) -> list[tuple[int, int, str]]:
    """`(file offset, hunk, instruction)` for every `d16(An)` access one to
    three bytes below `displacement` whose operand size reaches it."""
    found = []
    for back in (1, 2, 3):
        for offset, number, text in hunk_sites(data, displacement - back):
            name = text.split()[0]
            if name.startswith(("lea", "pea")):
                continue
            size = 4 if name.startswith("movem") else \
                _SIZE.get(name.rpartition(".")[2], 1)
            if size > back:
                found.append((offset, number, text))
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adf", help="a disk image holding the executable")
    parser.add_argument("--exe", help="the executable's path on the disk")
    parser.add_argument("--file", help="the executable as a loose file")
    parser.add_argument("--reach", type=lambda s: int(s, 0), default=16,
                        help="how far below the byte a lea base may sit "
                             "(default 16)")
    parser.add_argument("offsets", nargs="+",
                        help="record offsets, hex, one per byte asked about")
    args = parser.parse_args(argv)
    data = load(args)
    for text in args.offsets:
        offset = int(text, 16)
        indexed = indexed_sites(data, offset)
        print(f"0x{offset:03X}: {len(indexed)} indexed site(s)")
        for at, number, instruction in indexed:
            print(f"  {at:06x}  hunk {number:2d}  {instruction}")
        bases = lea_bases(data, offset, args.reach)
        print(f"        {len(bases)} lea base(s) within 0x{args.reach:X} below")
        for at, number, base, instruction in bases:
            print(f"  {at:06x}  hunk {number:2d}  base 0x{base:03X}  {instruction}")
        rebased = rebased_sites(data, offset, args.reach)
        print(f"        {len(rebased)} rebased use(s)")
        for at, number, setter, where, use in rebased:
            print(f"  {at:06x}  hunk {number:2d}  {setter}  ->  {where:06x}  {use}")
        wide = wide_sites(data, offset)
        print(f"        {len(wide)} wider access(es) from below")
        for at, number, instruction in wide:
            print(f"  {at:06x}  hunk {number:2d}  {instruction}")
        indexes = index_sites(data, offset)
        print(f"        {len(indexes)} constant-index use(s)")
        for at, number, setter, where, use in indexes:
            print(f"  {at:06x}  hunk {number:2d}  {setter}  ->  {where:06x}  {use}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
