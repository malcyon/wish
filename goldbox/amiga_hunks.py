"""The AmigaDOS Hunk executable format: its hunk table and relocations.

The app reads `/program` through this module and `tools/amiga/amiga68k.py`
builds its `Executable` on it, because the app may not import `tools/`.
"""

from __future__ import annotations

import dataclasses
import struct

HUNK_HEADER, HUNK_CODE, HUNK_DATA, HUNK_BSS = 0x3F3, 0x3E9, 0x3EA, 0x3EB
HUNK_RELOC32, HUNK_END, HUNK_SYMBOL, HUNK_DEBUG = 0x3EC, 0x3F2, 0x3E8, 0x3F1
KINDS = {HUNK_CODE: "CODE", HUNK_DATA: "DATA", HUNK_BSS: "BSS"}


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


def parse(data: bytes) -> tuple[list[Hunk], dict[tuple[int, int], int]]:
    """`(hunks, relocs)` of a Hunk executable.

    `relocs` maps `(hunk, offset within hunk)` of a 32-bit field to the hunk it
    points into. Raises `ValueError` for a file that is not a Hunk executable.
    """
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
    return hunks, relocs
