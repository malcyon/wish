"""`tools/amiga/amiga68k.py` on executables built here, so no game code is needed.

The two linker layouts the tool understands are each built from scratch as a
Hunk file: a SAS/Lattice small-data program with a `jmp` table opening its
data hunk, and a program of two hunks that reaches its string through a
`RELOC32` entry.  What the tests pin is what `#28 (Decode an Amiga saved game,
not just a character file)` leaned on: the jump-table resolution, the
PC-relative reference search and the annotation of a reloc'd operand.
"""

from __future__ import annotations

import pathlib
import struct
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from support.hunks import hunk_file, pad4, u32

from tools.amiga import amiga68k  # noqa: E402
from tools.amiga.amiga68k import Executable, pc_references  # noqa: E402

pytest.importorskip("capstone")


def small_data_program() -> bytes:
    """`jsr -$7ffe(a4)` through a one-entry jump table, and a `pea` of a string."""
    string = b"savgam\0"
    code = bytearray()
    code += b"\x4e\xac\x80\x02"          # 0: jsr -$7ffe(a4)
    code += b"\x48\x7a\x00\x00"          # 4: pea <string>(pc), patched below
    code += b"\x4e\x75"                  # 8: rts
    code += b"\x4e\x75"                  # 10: rts  (the jump table's target)
    code += b"\x4e\x71"                  # 12: nop
    string_at = len(code) + 2            # after a nop, keep it even
    code += b"\x4e\x71" + string
    disp = string_at - (4 + 2)
    code[6:8] = struct.pack(">h", disp)
    code = pad4(bytes(code))
    data = bytearray(b"\x4e\xf9" + u32(10))   # jmp abs.l -> code + 10
    data += b"\0" * (0x7FFE + 8 - len(data))  # room for a4 = data + 0x7ffe
    data = pad4(bytes(data))
    return hunk_file([
        (amiga68k.HUNK_CODE, code, []),
        (amiga68k.HUNK_DATA, data, [(0, [2])]),
        (amiga68k.HUNK_BSS, u32(4), []),
    ])


def test_a_small_data_program_is_recognised_and_its_jump_table_resolves():
    exe = Executable.parse(small_data_program())
    assert [h.kind for h in exe.hunks] == ["CODE", "DATA", "BSS"]
    code = exe.by_number(0)
    assert exe.small_data is exe.by_number(1)
    # -$7ffe(a4) is data+0, the first jump-table entry, which jumps to code+10
    assert exe.resolve_a4(-0x7FFE) == code.file_offset + 10
    assert exe.resolve_a4(-0x7FF8) is None      # past the table


def test_the_reference_search_finds_the_pea_that_names_the_string():
    exe = Executable.parse(small_data_program())
    code = exe.by_number(0)
    string_at = exe.data.find(b"savgam\0")
    assert pc_references(exe.data, string_at) == [code.file_offset + 4]
    assert exe.cstring(string_at) == "savgam"


def test_the_listing_annotates_the_call_and_quotes_the_string():
    exe = Executable.parse(small_data_program())
    code = exe.by_number(0)
    lines = amiga68k.disassemble(exe, code.file_offset, code.file_offset + 10)
    assert any("jsr" in ln and f"-> {code.file_offset + 10:06x}" in ln
               for ln in lines), lines
    assert any('"savgam"' in ln for ln in lines), lines


def absolute_program() -> bytes:
    """`pea abs.l` into a second hunk, reached through a RELOC32 entry."""
    code = b"\x48\x79" + u32(4) + b"\x4e\x75"     # pea $4.l ; rts
    data = pad4(b"\0\0\0\0Loading...\0")
    return hunk_file([
        (amiga68k.HUNK_CODE, code, [(1, [2])]),
        (amiga68k.HUNK_DATA, data, []),
    ])


def test_an_absolute_reference_resolves_through_the_reloc_table():
    exe = Executable.parse(absolute_program())
    assert exe.small_data is None
    code, data = exe.by_number(0), exe.by_number(1)
    assert exe.resolve_abs(code.file_offset + 2) == (1, 4, data.file_offset + 4)
    lines = amiga68k.disassemble(exe, code.file_offset, code.file_offset + 8)
    assert any("h1+0x4" in ln and '"Loading..."' in ln for ln in lines), lines


def test_a_file_without_a_hunk_header_is_refused():
    with pytest.raises(ValueError):
        Executable.parse(b"DOS\0" + bytes(60))
