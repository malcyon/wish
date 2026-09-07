#!/usr/bin/env python3
"""Every instruction in an Amiga executable that touches a record byte.

`tools/amigaglobal.py` answers "who reads this **global**", which on the two
SAS/Lattice builds is `d16(a4)`.  A character record is not a global: the
engine holds a pointer to the selected character and reaches a field as
`d16(An)` off it -- `move.b $145(a0), d0` for Curse's `icon_head` -- so a
displacement search is the way to ask "who reads this **field**", and there was
no tool for it until `#396 (Whether an Amiga Curse or Silver Blades record's
combat-icon fields share DOS's own numbering is unmeasured)` needed one.

    tools/amigarecordrefs.py --adf work/copy-of-curse-A.adf --exe /Curse \
        145 146 148 149
    tools/amigarecordrefs.py --file work/396/Curse de

Give it Amiga record offsets in hex; it prints the file offset and the
instruction for every site.  Feed a file offset straight to
`tools/amiga68k.py disasm` to read the routine around it.  That is how the
Amiga ICON menu (`cmpi.b #$d` against `icon_head`), the two shipped
inter-title importers and `icon_dimension`'s combat test were all found.

**Why the candidate-and-decode shape, and what it costs.**  A linear
disassembly of a 300KB code hunk desyncs on the jump tables and string data
between routines, so this finds every occurrence of the displacement word at
an even offset first and decodes a short window ending at each one -- which
cannot desync, because every candidate is decoded from its own start.  The
price is that a displacement is only two bytes and matches by luck as well as
by design, so **a hit is a candidate until the listing is read**: an
`ori.b`, a `movep.l` or a `dc.w` in the output is a coincidence rather than a
field access.  The instruction is printed for exactly that reason.

Everything is read; nothing is written.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import capstone  # noqa: E402

from tools.amiga68k import Executable, load  # noqa: E402

#: How far back from the displacement word an instruction may start.  A
#: `move.b d16(a0), d16(a1)` puts the second displacement six bytes in, and
#: `cmpi.b #imm, d16(a0)` four; eight covers every shape either binary uses.
BACK = (2, 4, 6, 8)


def sites(data: bytes, displacement: int,
          start: int = 0, end: int | None = None) -> list[tuple[int, str]]:
    """`(file offset, instruction)` for every `d16(An)` reaching `d16`."""
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    target = struct.pack(">H", displacement)
    end = len(data) if end is None else end
    found, at = [], start - 1
    while True:
        at = data.find(target, at + 1, end)
        if at < 0:
            return found
        if at % 2:
            continue
        for back in BACK:
            begin = at - back
            if begin < start:
                continue
            try:
                one = next(md.disasm(data[begin:begin + 12], begin, count=1))
            except StopIteration:
                continue
            if f"${displacement:x}(" in one.op_str and one.size >= back + 2:
                found.append((begin, f"{one.mnemonic} {one.op_str}"))
                break


def code_range(data: bytes) -> tuple[int, int]:
    """The first CODE hunk's file offsets, so a match in the data hunk -- a
    constant, a string, a relocation -- is never decoded as an instruction."""
    for hunk in Executable.parse(data).hunks:
        if hunk.kind == "CODE" and hunk.file_offset is not None:
            return hunk.file_offset, hunk.file_offset + hunk.size
    return 0, len(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adf", help="a disk image holding the executable")
    parser.add_argument("--exe", help="the executable's path on the disk")
    parser.add_argument("--file", help="the executable as a loose file")
    parser.add_argument("offsets", nargs="+",
                        help="record offsets, hex")
    args = parser.parse_args(argv)
    data = load(args)
    start, end = code_range(data)
    for text in args.offsets:
        displacement = int(text, 16)
        print(f"--- record +0x{displacement:X}")
        for where, instruction in sites(data, displacement, start, end):
            print(f"  {where:06x}: {instruction}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
