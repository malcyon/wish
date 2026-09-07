#!/usr/bin/env python3
"""Find every instruction that touches a small-data global, and every caller.

`tools/amiga68k.py refs` searches for **PC-relative** references, which is the
wrong search for the two Amiga titles built by SAS/Lattice.  In `/Curse` and
`/Secret` a global is `d16(a4)` and a far call is `jsr d16(a4)` through a table
of `jmp abs.l` entries, so neither a variable nor a routine has a PC-relative
reference anywhere -- `refs` answers "no PC-relative reference" for both and
says nothing about who reads what.

This is the search that works on those two.  It found the Silver Blades step
routine from the party's x byte in one call, and that routine's only caller
from its jump-table slot in a second
(`#28 (Decode an Amiga saved game, not just a character file)`).

    tools/amigaglobal.py --adf work/copy-of-secret-A.adf --exe /Secret \
        refs 57a0 57a1 57a2
    tools/amigaglobal.py --adf work/copy-of-secret-A.adf --exe /Secret \
        callers 118cc

A global is named the way `amiga68k.py`'s listing names it, `g<offset>` with
the offset into the data hunk, so a name read off a listing can be pasted
straight in.  Addresses printed are file offsets into the executable, which is
what `amiga68k.py disasm` takes.

**Why the raw scan and not a linear disassembly.**  A 300KB code hunk holds
jump tables and string data between routines, so disassembling it from one end
desyncs and silently loses instructions -- run against `/Secret` that way, the
five square globals came back with **0** references between them when there are
191.  Scanning for the displacement word first and decoding a short window
around each hit cannot desync, because every candidate is decoded from its own
start.

Everything is read; nothing is written.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import capstone  # noqa: E402

from tools.amiga68k import SMALL_DATA_BIAS, Executable, load  # noqa: E402

#: `jmp abs.l`, the shape of every entry in the far-call table.
JMP_ABS = b"\x4e\xf9"


def _disassembler() -> "capstone.Cs":
    return capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)


def displacement(global_offset: int) -> int:
    """The 16-bit word an instruction encodes to reach `g<global_offset>`."""
    return (global_offset - SMALL_DATA_BIAS) & 0xFFFF


def operand(global_offset: int) -> str:
    """How capstone prints that operand -- `-$285e(a4)`."""
    d = global_offset - SMALL_DATA_BIAS
    return f"-${-d:x}(a4)" if d < 0 else f"${d:x}(a4)"


def code_range(exe: Executable) -> tuple[int, int]:
    """`(file offset, size)` of the one code hunk."""
    for hunk in exe.hunks:
        if hunk.kind == "CODE" and hunk.file_offset is not None:
            return hunk.file_offset, hunk.size
    raise SystemExit("no code hunk with bytes in it")


def data_range(exe: Executable) -> tuple[int, int]:
    for hunk in exe.hunks:
        if hunk.kind == "DATA" and hunk.file_offset is not None:
            return hunk.file_offset, hunk.size
    raise SystemExit("no data hunk with bytes in it")


def references(exe: Executable, global_offset: int
               ) -> list[tuple[int, str, str]]:
    """`(file offset, mnemonic, operands)` for every touch of the global.

    Every word-aligned occurrence of the displacement is a candidate; the
    window in front of it is decoded and kept only when the decoded operands
    really name it, which throws out the ones that are data or a coincidence
    in the middle of a longer instruction.
    """
    start, size = code_range(exe)
    code = exe.data[start:start + size]
    want = struct.pack(">H", displacement(global_offset))
    text = operand(global_offset)
    md, out, seen = _disassembler(), [], set()
    for at in range(0, len(code) - 1, 2):
        if code[at:at + 2] != want:
            continue
        # The operand word sits one to three words after the opcode: `move.b
        # d16(a4), d0` puts it first, `move.b #$f, d16(a4)` after the
        # immediate. Decode from each and keep the first that names it.
        for back in (2, 4, 6, 8):
            head = at - back
            if head < 0:
                continue
            for ins in md.disasm(code[head:head + 12], start + head):
                if text in ins.op_str and ins.address not in seen:
                    seen.add(ins.address)
                    out.append((ins.address, ins.mnemonic, ins.op_str))
                break
            if seen and out and out[-1][0] == start + head:
                break
    return sorted(out)


def jump_slot(exe: Executable, routine: int) -> int | None:
    """The data-hunk offset of the `jmp abs.l` entry for a code file offset.

    The table holds hunk-relative addresses in the file -- the loader relocates
    them -- so the entry for a routine at file offset `f` holds `f` minus the
    code hunk's own file offset.
    """
    code_at, _ = code_range(exe)
    data_at, data_size = data_range(exe)
    want = JMP_ABS + struct.pack(">I", routine - code_at)
    found = exe.data[data_at:data_at + data_size].find(want)
    return None if found < 0 else found


def callers(exe: Executable, routine: int) -> list[tuple[int, str, str]]:
    """Every `jsr` that reaches a routine through its jump-table slot."""
    slot = jump_slot(exe, routine)
    if slot is None:
        return []
    return [r for r in references(exe, slot) if r[1].startswith("jsr")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adf", help="a disk image holding the executable")
    parser.add_argument("--exe", help="the executable's path on the disk")
    parser.add_argument("--file", help="the executable as a loose file")
    sub = parser.add_subparsers(dest="command", required=True)
    refs = sub.add_parser("refs", help="who touches a global")
    refs.add_argument("globals", nargs="+",
                      help="data-hunk offsets, hex -- the g<nnnn> names")
    call = sub.add_parser("callers", help="who calls a routine")
    call.add_argument("routines", nargs="+", help="code file offsets, hex")
    args = parser.parse_args(argv)

    exe = Executable.parse(load(args))
    if not exe.small_data:
        raise SystemExit(
            "this executable is not a SAS/Lattice small-data program, so it "
            "has no d16(a4) globals; use tools/amiga68k.py refs")
    if args.command == "refs":
        for name in args.globals:
            offset = int(name, 16)
            hits = references(exe, offset)
            print(f"g{offset:04x} ({operand(offset)}): {len(hits)} references")
            for at, mnemonic, ops in hits:
                print(f"  {at:06x}  {mnemonic:8s} {ops}")
    else:
        for name in args.routines:
            routine = int(name, 16)
            slot = jump_slot(exe, routine)
            if slot is None:
                print(f"{routine:06x}: no jump-table entry -- it is called "
                      f"directly, or it is not a routine")
                continue
            hits = callers(exe, routine)
            print(f"{routine:06x} (slot g{slot:04x}): {len(hits)} callers")
            for at, mnemonic, ops in hits:
                print(f"  {at:06x}  {mnemonic:8s} {ops}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
