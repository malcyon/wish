"""The AmigaDOS Hunk reader, `goldbox/amiga_hunks.py`.

The synthetic files are built here, block by block, so `HUNK_NAME`,
`HUNK_SYMBOL` and a hunk that ends without `HUNK_END` are read with no game
data. The disk-backed test reads the registry's Amiga disks and skips without
them.
"""

from __future__ import annotations

import struct

import pytest

from goldbox import amiga_hunks
from tests.support.hunks import u32

#: Block ids from the AmigaDOS Hunk format (`dos/doshunks.h`), written out
#: here so a wrong constant in the module cannot build its own test files.
HUNK_NAME, HUNK_SYMBOL = 0x3E8, 0x3F0

CODE = b"\x4e\x75\x4e\x71" * 2         # rts, nop: two longs
DATA = u32(0) + u32(0x1234)


def _header(*sizes: int) -> bytes:
    """`HUNK_HEADER` with no resident libraries and one table entry per size."""
    out = u32(amiga_hunks.HUNK_HEADER) + u32(0)
    out += u32(len(sizes)) + u32(0) + u32(len(sizes) - 1)
    return out + b"".join(u32(s // 4) for s in sizes)


def _name(text: bytes) -> bytes:
    """A name as the Hunk format stores it: a long count, then padded longs."""
    padded = text + b"\0" * (-len(text) % 4)
    return u32(len(padded) // 4) + padded


def _block(kind: int, body: bytes) -> bytes:
    return u32(kind) + u32(len(body) // 4) + body


def test_hunk_name_is_a_name_block_before_its_hunk():
    data = (_header(len(CODE))
            + u32(HUNK_NAME) + _name(b"main_code")
            + _block(amiga_hunks.HUNK_CODE, CODE)
            + u32(amiga_hunks.HUNK_END))
    hunks, relocs = amiga_hunks.parse(data)
    assert [(h.number, h.kind, h.size) for h in hunks] == [(0, "CODE", len(CODE))]
    assert hunks[0].file_offset == data.index(CODE)
    assert relocs == {}


def test_hunk_symbol_is_name_value_pairs_ended_by_a_zero_length_name():
    symbols = (_name(b"_a") + u32(0)
               + _name(b"_longer_name") + u32(4)
               + u32(0))
    data = (_header(len(CODE), len(DATA))
            + _block(amiga_hunks.HUNK_CODE, CODE)
            + u32(HUNK_SYMBOL) + symbols
            + u32(amiga_hunks.HUNK_END)
            + _block(amiga_hunks.HUNK_DATA, DATA)
            + u32(amiga_hunks.HUNK_RELOC32) + u32(1) + u32(0) + u32(4) + u32(0)
            + u32(HUNK_SYMBOL) + _name(b"_d") + u32(4) + u32(0)
            + u32(amiga_hunks.HUNK_END))
    hunks, relocs = amiga_hunks.parse(data)
    assert [(h.number, h.kind) for h in hunks] == [(0, "CODE"), (1, "DATA")]
    assert relocs == {(1, 4): 0}


def test_a_new_hunk_starts_without_hunk_end():
    data = (_header(len(CODE), 64, 16)
            + _block(amiga_hunks.HUNK_CODE, CODE)
            + u32(amiga_hunks.HUNK_RELOC32) + u32(1) + u32(1) + u32(4) + u32(0)
            + _block(amiga_hunks.HUNK_DATA, DATA)
            + u32(amiga_hunks.HUNK_BSS) + u32(4)
            + u32(amiga_hunks.HUNK_END))
    hunks, relocs = amiga_hunks.parse(data)
    assert [(h.number, h.kind, h.size, h.allocated) for h in hunks] == [
        (0, "CODE", len(CODE), len(CODE)),
        (1, "DATA", len(DATA), 64),
        (2, "BSS", 16, 16)]
    assert hunks[1].file_offset == data.index(DATA)
    assert relocs == {(0, 4): 1}


def test_a_hunk_past_the_header_table_raises_without_hunk_end_too():
    data = (_header(len(CODE))
            + _block(amiga_hunks.HUNK_CODE, CODE)
            + _block(amiga_hunks.HUNK_DATA, DATA)
            + u32(amiga_hunks.HUNK_END))
    with pytest.raises(ValueError, match="past the 1"):
        amiga_hunks.parse(data)


# --- the player's own disks --------------------------------------------------

#: Files the reader used to fail on, or numbered twice, by path on the disk.
SYMBOLS = {"/PtoH", "/c/loop.ago"}
NO_HUNK_END = {"/intro", "/pool-to-hd", "/c/loadwb", "/c/dmouse"}


@pytest.fixture(scope="module")
def disk_programs():
    """`[(label, path, program)]` for the registry files named above."""
    from automap import gamedisks
    from goldbox.amiga_adf import AmigaDisk
    from tools.amiga import amigasaves
    out: list[tuple[str, str, bytes]] = []
    if not gamedisks.candidates("amiga"):
        return out
    for label, image in amigasaves.images():
        try:
            disk = AmigaDisk(bytearray(image))
            entries = list(disk.walk())
        except Exception:
            continue
        for path, _entry in entries:
            if path not in SYMBOLS | NO_HUNK_END:
                continue
            try:
                body = disk.read_file(path)
            except Exception:
                continue
            if body[:4] == u32(amiga_hunks.HUNK_HEADER):
                out.append((label, path, body))
    return out


def _table_size(program: bytes) -> int:
    """The header's hunk count, read here rather than by the parser."""
    assert struct.unpack(">I", program[4:8])[0] == 0, "resident libraries"
    return struct.unpack(">I", program[8:12])[0]


@pytest.mark.parametrize("names", [SYMBOLS, NO_HUNK_END],
                         ids=["hunk_symbol", "no_hunk_end"])
def test_registry_programs_parse_one_number_per_hunk(disk_programs, names):
    found = [(label, path, body) for label, path, body in disk_programs
             if path in names]
    if not found:
        pytest.skip("none of these Amiga programs is in the registry")
    for label, path, program in found:
        hunks, _ = amiga_hunks.parse(program)
        where = f"{label}:{path}"
        assert [h.number for h in hunks] == list(range(_table_size(program))), where
