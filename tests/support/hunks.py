"""Helpers `test_amiga68k` shares with the test files that reuse them."""
from __future__ import annotations

import struct

from tools.amiga import amiga68k  # noqa: E402


def u32(n: int) -> bytes:
    return struct.pack(">I", n)


def hunk_file(hunks: list[tuple[int, bytes, list[tuple[int, list[int]]]]]) -> bytes:
    """A Hunk executable from `(kind, body, relocs)` triples.

    `relocs` is `[(target hunk, [offsets])]`.  BSS bodies are given as the
    allocated size in a four-byte body.
    """
    out = bytearray(u32(amiga68k.HUNK_HEADER) + u32(0))
    out += u32(len(hunks)) + u32(0) + u32(len(hunks) - 1)
    for kind, body, _ in hunks:
        size = (struct.unpack(">I", body)[0] if kind == amiga68k.HUNK_BSS
                else len(body))
        out += u32(size // 4)
    for kind, body, relocs in hunks:
        if kind == amiga68k.HUNK_BSS:
            out += u32(kind) + body
        else:
            out += u32(kind) + u32(len(body) // 4) + body
        if relocs:
            out += u32(amiga68k.HUNK_RELOC32)
            for target, offsets in relocs:
                out += u32(len(offsets)) + u32(target)
                out += b"".join(u32(o) for o in offsets)
            out += u32(0)
        out += u32(amiga68k.HUNK_END)
    return bytes(out)


def pad4(b: bytes) -> bytes:
    return b + b"\0" * (-len(b) % 4)
