#!/usr/bin/env python3
"""Census the structure offsets reached through a global far pointer.

Gold Box's DOS builds keep most engine state in heap blocks reached through a
far pointer in the global data segment.  Turbo Pascal compiles
``p^.field`` into ``les di, [<global>]`` followed by ``es:[di+<disp>]``, so the
set of displacements that follow a load of one particular global *is* that
structure's field map -- and because the same block is what the save routine
hands to ``BlockWrite``, a displacement is a file offset.

This is how the first 1024 bytes of the Pools of Darkness ``SAVGAM<slot>.PTY``
were read for `#175 (Decode the first 1024 bytes of the Pools of Darkness
saved game)`: the save routine writes 1024 bytes from ``[DS:0x87F8]^``, so
every ``es:[di+N]`` after a ``les di, [0x87F8]`` names byte N of the file.

    tools/dosptrfields.py GAME.OVR --pointer 0x87f8
    tools/dosptrfields.py GAME.OVR --pointer 0x87f8 --offset 0x1f --sites

**What this is evidence of, and what it is not.**

1. It is a *linear* disassembly of a file that is not all code.  An overlay
   file interleaves code, Pascal string literals and relocation tables, so a
   ``les di, [0x87F8]`` found in the middle of a string is a false site.  The
   filter is that the bytes after it decode into plausible instructions; that
   is a filter, not a proof.
2. A field can be reached without a displacement -- a pointer walked with
   ``inc di``, a ``rep movsb`` over the whole block, an index added in.  So an
   offset missing from the census is **not** evidence that nothing reads it.
3. A displacement is only a file offset for the region the save routine
   actually writes.  Check the writer first.

So treat a site as a lead and corroborate it: read the routine around it, or
watch the address in DOSBox-X.
"""

from __future__ import annotations

import argparse
import collections
import pathlib

import capstone

#: `les`/`lds` into a 16-bit register from an absolute `[disp16]`.  The ModRM
#: byte is `mod=00, reg=<dest>, rm=110`, so the low three bits are fixed and
#: the register is bits 3-5.
LOAD_FAR = {0xC4: "es", 0xC5: "ds"}
REGS16 = ["ax", "cx", "dx", "bx", "sp", "bp", "si", "di"]

#: How far past a site to keep reading before giving up on the pointer being
#: live.  Turbo Pascal reloads the pointer for every statement, so field
#: accesses cluster tightly; 96 bytes covers the longest run seen in
#: Pools of Darkness' `GAME.OVR`.
DEFAULT_WINDOW = 96


def find_sites(data: bytes, pointer: int) -> list[tuple[int, str, str]]:
    """Every `les`/`lds <reg>, [pointer]` in *data*, as (offset, seg, reg)."""
    lo, hi = pointer & 0xFF, (pointer >> 8) & 0xFF
    sites = []
    start = 0
    while True:
        i = data.find(bytes([lo, hi]), start)
        if i < 0:
            return sites
        start = i + 1
        if i < 2:
            continue
        opcode, modrm = data[i - 2], data[i - 1]
        if opcode not in LOAD_FAR or (modrm & 0xC7) != 0x06:
            continue
        sites.append((i - 2, LOAD_FAR[opcode], REGS16[(modrm >> 3) & 7]))


def fields_at(data: bytes, site: int, seg: str, reg: str,
              window: int = DEFAULT_WINDOW) -> list[tuple[int, int, str, str]]:
    """Displacements read off the pointer loaded at *site*.

    Returns (address, displacement, mnemonic, operands) for each access whose
    segment override is *seg* and whose base register is *reg*, stopping at
    the first instruction that clobbers either.
    """
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    md.detail = True
    out = []
    first = True
    for insn in md.disasm(data[site:site + window], site):
        if first:                       # the `les`/`lds` itself
            first = False
            continue
        text = f"{insn.mnemonic} {insn.op_str}"
        if insn.mnemonic in ("les", "lds") and f" {reg}," in text:
            break
        if insn.mnemonic in ("retf", "ret", "jmp", "call", "lcall", "ljmp"):
            break
        for op in insn.operands:
            if op.type != capstone.x86.X86_OP_MEM:
                continue
            mem = op.value.mem
            names = {insn.reg_name(mem.base) if mem.base else None,
                     insn.reg_name(mem.index) if mem.index else None}
            if reg not in names:
                continue
            if insn.reg_name(mem.segment) != seg:
                continue
            out.append((insn.address, mem.disp & 0xFFFF, insn.mnemonic,
                        insn.op_str))
        # A write to the base register ends the run.
        if insn.mnemonic == "mov" and insn.op_str.startswith(reg + ","):
            break
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=pathlib.Path, nargs="+",
                    help="overlay or executable file to scan")
    ap.add_argument("--pointer", required=True,
                    type=lambda s: int(s, 0),
                    help="data-segment offset of the far pointer, e.g. 0x87f8")
    ap.add_argument("--offset", type=lambda s: int(s, 0), default=None,
                    help="report only this displacement")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                    help=f"bytes to read past a site (default {DEFAULT_WINDOW})")
    ap.add_argument("--sites", action="store_true",
                    help="list every access rather than counting displacements")
    args = ap.parse_args(argv)

    tally: dict[int, collections.Counter] = collections.defaultdict(
        collections.Counter)
    nsites = 0
    for path in args.image:
        data = path.read_bytes()
        for site, seg, reg in find_sites(data, args.pointer):
            nsites += 1
            for addr, disp, mnem, ops in fields_at(data, site, seg, reg,
                                                   args.window):
                if args.offset is not None and disp != args.offset:
                    continue
                tally[disp][mnem] += 1
                if args.sites:
                    print(f"{path.name}:{addr:#07x}  +{disp:#06x} "
                          f"({disp:5d})  {mnem} {ops}")

    if args.sites:
        return 0
    print(f"{nsites} load sites for pointer {args.pointer:#06x}")
    print(f"{len(tally)} distinct displacements")
    for disp in sorted(tally):
        kinds = " ".join(f"{m}x{n}" for m, n in tally[disp].most_common())
        print(f"  +{disp:#06x} ({disp:5d})  {sum(tally[disp].values()):3d}  {kinds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
