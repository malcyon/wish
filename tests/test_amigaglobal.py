"""`tools/amigaglobal.py` on an executable built here, so no game code is needed.

The tool exists because `tools/amiga68k.py refs` cannot answer the question
`#28 (Decode an Amiga saved game, not just a character file)` kept asking of
`/Curse` and `/Secret`: who touches this variable, and who calls this routine.
Both go through `d16(a4)` on a SAS/Lattice small-data program and neither
leaves a PC-relative reference anywhere.

What is pinned here is what the answers rested on -- that a global's
references are found whichever side of the instruction the displacement lands
on, that a routine's callers are found through its jump-table slot, and that a
displacement appearing inside an unrelated immediate is **not** reported.
"""

from __future__ import annotations

import pathlib
import struct
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import amiga68k, amigaglobal  # noqa: E402
from tools.amiga68k import Executable  # noqa: E402

pytest.importorskip("capstone")

from tests.test_amiga68k import hunk_file, pad4, u32  # noqa: E402

#: The Silver Blades party's x byte, so the numbers in the test are the ones
#: in `docs/165-amiga-savegame.md`.
X = 0x57A0
#: What `d16(a4)` encodes to reach it: `0x57a0 - 0x7ffe` as a signed word.
X_DISP = b"\xd7\xa2"

#: Offsets inside the code hunk of the program below.
READ_AT, WRITE_AT, CALL_AT, DECOY_AT, ROUTINE_AT = 0, 4, 10, 14, 20


def small_data_program() -> bytes:
    """A read of `g57a0`, a write of it, a table call, and one decoy.

    The write puts the displacement **after** an immediate rather than
    straight after the opcode, which is the case a fixed "the operand is the
    next word" search gets wrong.  The decoy is `move.l #$d7a2, d1`, where the
    same two bytes are part of a longword immediate and name no global at all.
    """
    code = bytearray()
    code += b"\x10\x2c" + X_DISP                    # 0: move.b g57a0, d0
    code += b"\x19\x7c\x00\x0f" + X_DISP            # 4: move.b #$f, g57a0
    code += b"\x4e\xac\x80\x02"                     # 10: jsr -$7ffe(a4)
    code += b"\x22\x3c\x00\x00" + X_DISP            # 14: move.l #$d7a2, d1
    code += b"\x4e\x75"                             # 20: rts -- the routine
    code += b"\x4e\x75"                             # 22: rts
    code = pad4(bytes(code))
    data = bytearray(b"\x4e\xf9" + u32(ROUTINE_AT))  # jmp abs.l -> code + 20
    data += b"\0" * (0x7FFE + 8 - len(data))
    data = pad4(bytes(data))
    return hunk_file([
        (amiga68k.HUNK_CODE, code, []),
        (amiga68k.HUNK_DATA, data, [(0, [2])]),
    ])


def absolute_program() -> bytes:
    """Two hunks and no small-data base -- Pool of Radiance's layout."""
    code = b"\x48\x79" + u32(4) + b"\x4e\x75"
    return hunk_file([
        (amiga68k.HUNK_CODE, code, [(1, [2])]),
        (amiga68k.HUNK_DATA, pad4(b"\0\0\0\0hello\0"), []),
    ])


def test_the_displacement_and_the_operand_are_the_listings_own():
    assert amigaglobal.displacement(X) == struct.unpack(">H", X_DISP)[0]
    assert amigaglobal.operand(X) == "-$285e(a4)"
    # A global past the small-data base is a positive displacement.
    assert amigaglobal.operand(0x8000) == "$2(a4)"


def test_both_touches_of_the_global_are_found_whichever_word_they_sit_in():
    exe = Executable.parse(small_data_program())
    at = exe.by_number(0).file_offset
    hits = amigaglobal.references(exe, X)
    assert [h[0] for h in hits] == [at + READ_AT, at + WRITE_AT]
    assert [h[1] for h in hits] == ["move.b", "move.b"]
    assert all("-$285e(a4)" in h[2] for h in hits)


def test_a_displacement_inside_an_unrelated_immediate_is_not_reported():
    """The decoy's two bytes match and its decoded operands do not."""
    exe = Executable.parse(small_data_program())
    at = exe.by_number(0).file_offset
    assert at + DECOY_AT not in [h[0] for h in amigaglobal.references(exe, X)]


def test_a_routine_is_found_through_its_jump_table_slot():
    exe = Executable.parse(small_data_program())
    at = exe.by_number(0).file_offset
    assert amigaglobal.jump_slot(exe, at + ROUTINE_AT) == 0
    assert amigaglobal.callers(exe, at + ROUTINE_AT) == [
        (at + CALL_AT, "jsr", "-$7ffe(a4)")]


def test_a_routine_with_no_jump_table_entry_has_no_callers_and_says_so():
    exe = Executable.parse(small_data_program())
    at = exe.by_number(0).file_offset
    assert amigaglobal.jump_slot(exe, at + CALL_AT) is None
    assert amigaglobal.callers(exe, at + CALL_AT) == []


def test_a_program_with_no_small_data_base_is_refused_rather_than_searched(
        tmp_path, capsys):
    """Pool of Radiance's `/program` has no `d16(a4)` globals to look for."""
    exe = tmp_path / "program"
    exe.write_bytes(absolute_program())
    with pytest.raises(SystemExit) as raised:
        amigaglobal.main(["--file", str(exe), "refs", "57a0"])
    assert "small-data" in str(raised.value)


def test_the_command_line_prints_every_reference(tmp_path, capsys):
    exe = tmp_path / "secret"
    exe.write_bytes(small_data_program())
    assert amigaglobal.main(["--file", str(exe), "refs", "57a0"]) == 0
    out = capsys.readouterr().out
    assert "g57a0 (-$285e(a4)): 2 references" in out
    assert out.count("move.b") == 2
