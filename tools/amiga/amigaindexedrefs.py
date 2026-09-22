#!/usr/bin/env python3
"""The two ways an Amiga executable reaches a record byte that a displacement
search cannot see: the indexed form and a base register set by `lea`.

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

This prints every candidate of both kinds for each record offset asked for,
across every CODE hunk, decoding each from its own start so a hit is an
instruction and not a byte pair.  A `lea` is listed for bases from `--reach`
below the byte up to the byte itself, and **a `lea` is only a lead**: the
listing after it says how far the copy runs, and that has to be read.

    tools/amiga/amigaindexedrefs.py --adf curse-A.adf --exe /Curse f6 f9 fa
    tools/amiga/amigaindexedrefs.py --file PATH/TO/program 84 87 88 --reach 8

An empty indexed list and a `lea` list whose spans all stop short of the byte
is what "no site in this executable" looks like once all three forms have
been asked.  Everything is read; nothing is written.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

import capstone  # noqa: E402

from tools.amiga.amiga68k import load  # noqa: E402
from tools.amiga.amigarecordrefs import code_ranges, hunk_sites  # noqa: E402

#: capstone's rendering of a 68000 indexed operand: `$2a(a3, d4.w)`.
INDEXED = re.compile(r"\$([0-9a-f]+)\(a\d, [da]\d\.[wl]\)")

#: How far back from the extension word an instruction may start: the
#: opcode word alone, or one or two extension words of a first operand.
BACK = (2, 4, 6)


def indexed_sites(data: bytes, displacement: int) -> list[tuple[int, int, str]]:
    """`(file offset, hunk, instruction)` for every `d8(An,Xn)` whose
    displacement byte is `displacement`, over every CODE hunk."""
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
                match = INDEXED.search(decoded.op_str)
                if match and int(match.group(1), 16) == displacement:
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
