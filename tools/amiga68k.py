#!/usr/bin/env python3
"""Read a Gold Box Amiga executable: hunks, references, annotated 68000 code.

`#28 (Decode an Amiga saved game, not just a character file)` found the
saved game's shape by reading the save routine out of each title's
executable, and this is the tool that read it -- kept because the next
question about the Amiga port (a loader, a display routine, the item node's
last two bytes) starts the same way.  It needs `capstone`, which the
project's virtual environment carries.

    tools/amiga68k.py --adf work/copy-of-curse-A.adf --exe /Curse refs 274b4
    tools/amiga68k.py --adf work/copy-of-curse-A.adf --exe /Curse disasm 26af8 26d6c
    tools/amiga68k.py --file work/28/exe/program hunks

Two linker layouts are understood, and the tool tells them apart itself:

* **SAS/Lattice small-data** (`/Curse`, `/Secret`): one code hunk, one data
  hunk, `a4` = data + `0x7FFE`, and every far call is `jsr d16(a4)` through a
  table of `jmp abs.l` entries at the start of the data hunk.  The listing
  resolves those to the code-hunk file offset and names `d16(a4)` globals as
  `g<offset>` so a global can be grepped for.
* **Many hunks with absolute references** (Pool of Radiance's `/program`):
  every `abs.l` operand that has a `RELOC32` entry is resolved to
  `h<hunk>+<offset>` and, when it lands on a C string, the string is quoted.

Addresses in the listing are **file offsets into the executable**, which is
what the `refs` search and the hex dumps in `docs/165-amiga-savegame.md` use.
A hunk's load-relative offset is its file offset minus the hunk's data start,
printed by `hunks`.

Everything is read; nothing is written.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox.amiga_adf import AmigaDisk  # noqa: E402

HUNK_HEADER, HUNK_CODE, HUNK_DATA, HUNK_BSS = 0x3F3, 0x3E9, 0x3EA, 0x3EB
HUNK_RELOC32, HUNK_END, HUNK_SYMBOL, HUNK_DEBUG = 0x3EC, 0x3F2, 0x3E8, 0x3F1
KINDS = {HUNK_CODE: "CODE", HUNK_DATA: "DATA", HUNK_BSS: "BSS"}

#: SAS/Lattice's small-data base: `a4` points this far into the data hunk.
SMALL_DATA_BIAS = 0x7FFE
JMP_ABS = b"\x4e\xf9"


@dataclasses.dataclass(frozen=True)
class Hunk:
    number: int
    kind: str
    #: File offset of the hunk's bytes, `None` for BSS.
    file_offset: int | None
    #: Bytes in the file for CODE/DATA; allocated size for BSS.
    size: int
    #: Allocated size from the header table, which can exceed `size`.
    allocated: int

    def holds(self, file_offset: int) -> bool:
        return (self.file_offset is not None
                and self.file_offset <= file_offset < self.file_offset + self.size)


@dataclasses.dataclass
class Executable:
    data: bytes
    hunks: list[Hunk]
    #: `(hunk, offset within hunk)` of a 32-bit field -> hunk it points into.
    relocs: dict[tuple[int, int], int]

    @classmethod
    def parse(cls, data: bytes) -> "Executable":
        def u32(o):
            return struct.unpack(">I", data[o:o + 4])[0]
        if u32(0) != HUNK_HEADER:
            raise ValueError("not a Hunk executable: no HUNK_HEADER")
        off = 4
        while u32(off) != 0:            # resident library names, unused here
            off += 4 + 4 * u32(off)
        off += 4
        table = u32(off)
        off += 12
        allocated = [4 * (u32(off + 4 * i) & 0x3FFFFFFF) for i in range(table)]
        off += 4 * table
        hunks: list[Hunk] = []
        relocs: dict[tuple[int, int], int] = {}
        number = 0
        while off < len(data):
            kind = u32(off) & 0x3FFFFFFF
            if kind in (HUNK_CODE, HUNK_DATA):
                n = u32(off + 4)
                hunks.append(Hunk(number, KINDS[kind], off + 8, 4 * n,
                                  allocated[number]))
                off += 8 + 4 * n
            elif kind == HUNK_BSS:
                n = u32(off + 4)
                hunks.append(Hunk(number, "BSS", None, 4 * n,
                                  allocated[number]))
                off += 8
            elif kind == HUNK_RELOC32:
                off += 4
                while True:
                    n = u32(off)
                    if n == 0:
                        off += 4
                        break
                    target = u32(off + 4)
                    for i in range(n):
                        relocs[(number, u32(off + 8 + 4 * i))] = target
                    off += 8 + 4 * n
            elif kind == HUNK_END:
                off += 4
                number += 1
            elif kind == HUNK_SYMBOL:
                off += 4
                while u32(off) != 0:
                    off += 4 + 4 * (u32(off) & 0xFFFFFF) + 4
                off += 4
            elif kind == HUNK_DEBUG:
                off += 8 + 4 * u32(off + 4)
            else:
                raise ValueError(f"unknown hunk type {kind:#x} at {off:#x}")
        return cls(data, hunks, relocs)

    # -- layout ------------------------------------------------------------
    def hunk_at(self, file_offset: int) -> Hunk | None:
        for h in self.hunks:
            if h.holds(file_offset):
                return h
        return None

    def by_number(self, number: int) -> Hunk:
        for h in self.hunks:
            if h.number == number:
                return h
        raise KeyError(number)

    @property
    def small_data(self) -> Hunk | None:
        """The data hunk of a small-data program, or `None`.

        The tell is a run of `jmp abs.l` entries opening the (single) data
        hunk: SAS/Lattice's far-call table, which `jsr d16(a4)` indexes.
        """
        datas = [h for h in self.hunks if h.kind == "DATA"]
        codes = [h for h in self.hunks if h.kind == "CODE"]
        if len(datas) != 1 or len(codes) != 1:
            return None
        d = datas[0]
        if self.data[d.file_offset:d.file_offset + 2] != JMP_ABS:
            return None
        return d

    def resolve_a4(self, d16: int) -> int | None:
        """File offset a `jsr d16(a4)` lands on, through the jump table."""
        d = self.small_data
        if d is None:
            return None
        at = SMALL_DATA_BIAS + d16
        if not 0 <= at < d.size - 6:
            return None
        entry = self.data[d.file_offset + at:d.file_offset + at + 6]
        if entry[:2] != JMP_ABS:
            return None
        target = self.relocs.get((d.number, at + 2))
        if target is None:
            return None
        return (self.by_number(target).file_offset
                + struct.unpack(">I", entry[2:6])[0])

    def resolve_abs(self, field_file_offset: int) -> tuple[int, int, int | None] | None:
        """For a 32-bit field at this file offset: `(hunk, value, file offset)`."""
        h = self.hunk_at(field_file_offset)
        if h is None:
            return None
        target = self.relocs.get((h.number, field_file_offset - h.file_offset))
        if target is None:
            return None
        value = struct.unpack(">I", self.data[field_file_offset:
                                              field_file_offset + 4])[0]
        t = self.by_number(target)
        return target, value, (None if t.file_offset is None
                               else t.file_offset + value)

    def cstring(self, at: int, limit: int = 64) -> str | None:
        end = self.data.find(b"\0", at, at + limit)
        if end <= at:
            return None
        run = self.data[at:end]
        if all(0x20 <= c < 0x7F for c in run):
            return run.decode()
        return None


# -- searching --------------------------------------------------------------

_PCREL_OPS = {0x41FA, 0x43FA, 0x45FA, 0x47FA, 0x49FA, 0x4BFA, 0x4DFA, 0x4FFA,
              0x487A, 0x4EBA, 0x4EFA, 0x6100}


def _is_move_pcrel(op: int) -> bool:
    return (op & 0xC03F) == 0x003A and (op >> 12) in (1, 2, 3)


def pc_references(data: bytes, target: int, lo: int = 0,
                  hi: int | None = None) -> list[int]:
    """File offsets of instructions whose `(d16,PC)` operand lands on `target`.

    `lea`, `pea`, `jsr`, `jmp`, `bsr.w`, `bsr.s` and `move` from `(d16,PC)`.
    Displacements are relative to the instruction's second word, so a
    string and the code that names it must be in one hunk, which they are in
    the two small-data titles.
    """
    hi = len(data) if hi is None else hi
    out = []
    for p in range(lo, hi - 4, 2):
        op = struct.unpack(">H", data[p:p + 2])[0]
        if op in _PCREL_OPS or _is_move_pcrel(op):
            disp = struct.unpack(">h", data[p + 2:p + 4])[0]
            if p + 2 + disp == target:
                out.append(p)
        elif (op & 0xFF00) == 0x6100 and op != 0x6100:
            disp = op & 0xFF
            if disp >= 0x80:
                disp -= 0x100
            if p + 2 + disp == target:
                out.append(p)
    return out


# -- disassembly ------------------------------------------------------------

def _capstone():
    try:
        import capstone
    except ImportError as ex:        # pragma: no cover - environment
        raise SystemExit("capstone is not installed; it is in the project's "
                         ".venv") from ex
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    md.detail = False
    return md


def _sweep(md, data: bytes, start: int, end: int):
    """Linear sweep that steps two bytes past anything it cannot decode."""
    at = start
    while at < end:
        decoded = False
        for insn in md.disasm(data[at:end], at):
            decoded = True
            yield insn
            at = insn.address + insn.size
        if not decoded:
            at += 2
        elif at < end:
            at += 2


def disassemble(exe: Executable, start: int, end: int) -> list[str]:
    """Annotated lines for the file range `[start, end)`."""
    import re
    md = _capstone()
    small = exe.small_data
    lines = []
    for insn in _sweep(md, exe.data, start, end):
        line = (f"{insn.address:06x}: {insn.bytes.hex():<20} "
                f"{insn.mnemonic:8s} {insn.op_str}")
        notes = []
        if small is not None:
            m = re.search(r"(-?\$[0-9a-f]+)\(a4\)", insn.op_str)
            if m:
                d16 = int(m.group(1).replace("$", "0x"), 16)
                if insn.mnemonic in ("jsr", "jmp"):
                    t = exe.resolve_a4(d16)
                    notes.append(f"-> {t:06x}" if t is not None
                                 else f"-> data+{SMALL_DATA_BIAS + d16:#x}")
                else:
                    notes.append(f"g{SMALL_DATA_BIAS + d16:04x}")
        else:
            for k in range(2, len(insn.bytes) - 3, 2):
                r = exe.resolve_abs(insn.address + k)
                if r:
                    hunk, value, at = r
                    note = f"h{hunk}+{value:#x}"
                    if at is not None:
                        note += f" = {at:06x}"
                        s = exe.cstring(at)
                        if s:
                            note += f' "{s}"'
                    notes.append(note)
        m = re.search(r"\$([0-9a-f]+)\(pc\)", insn.op_str)
        if m and insn.mnemonic in ("pea.l", "pea", "lea.l", "lea"):
            s = exe.cstring(int(m.group(1), 16))
            if s:
                notes.append(f'"{s}"')
        if notes:
            line += "    ; " + "    ; ".join(notes)
        lines.append(line)
    return lines


# -- command line -----------------------------------------------------------

def load(args) -> bytes:
    if args.file:
        return pathlib.Path(args.file).read_bytes()
    if not (args.adf and args.exe):
        raise SystemExit("name --file, or --adf and --exe")
    return AmigaDisk.open(args.adf).read_file(args.exe)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adf", help="a disk image holding the executable")
    parser.add_argument("--exe", help="the executable's path on the disk")
    parser.add_argument("--file", help="the executable as a loose file")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hunks", help="list the hunks and the linker layout")
    refs = sub.add_parser("refs", help="who references a file offset")
    refs.add_argument("targets", nargs="+", help="file offsets, hex")
    dis = sub.add_parser("disasm", help="annotated listing of a range")
    dis.add_argument("start", help="file offset, hex")
    dis.add_argument("end", help="file offset, hex")
    args = parser.parse_args(argv)

    exe = Executable.parse(load(args))
    if args.command == "hunks":
        small = exe.small_data
        print("layout:", "small-data, a4 = data + 0x7ffe, jump table at "
              f"data+0 (hunk {small.number})" if small else
              "absolute references through RELOC32")
        for h in exe.hunks:
            where = "-" if h.file_offset is None else f"{h.file_offset:#x}"
            print(f"  hunk {h.number:2d} {h.kind:4s} file {where:>8} "
                  f"size {h.size:6d} allocated {h.allocated}")
        print(f"  {len(exe.relocs)} 32-bit relocations")
    elif args.command == "refs":
        for t in args.targets:
            target = int(t, 16)
            hits = pc_references(exe.data, target)
            print(f"{target:06x}: " + (" ".join(f"{h:06x}" for h in hits)
                                        or "no PC-relative reference"))
    else:
        print("\n".join(disassemble(exe, int(args.start, 16),
                                    int(args.end, 16))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
