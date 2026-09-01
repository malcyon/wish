"""The 6502 disassembler, on encodings built here rather than read off a disk.

Every case is assembled by hand from a published 6502 reference (the MOS
MCS6500 opcode table), not from `d6502.T`, which would restate the
implementation. `pytest tests/test_d6502.py` runs with zero skips: this suite
needs no game disk.

The disassembler cannot refuse the way `tools/m68dis.py` can -- on a 6502, 151
of 256 byte values are legal opcodes with no reserved fields, so a string of
text will decode as plausible instructions and no cross-check prevents it (see
the module docstring). What these tests can and do pin is that every opcode
the table knows decodes to the *true* mnemonic, size and addressing mode --
which is exactly the property `$F6` violated: it printed as `SBC $nn,X`, a
real 6502 instruction, and one line was indistinguishable from `$F5`'s.
"""

from tools import d6502


def lines_of(data: bytes, base: int | None = None, start: int = 0, count: int = 1):
    """The `mnemonic operands`/`.byte` text of every line `lines()` prints.

    Every line is `${addr}  {bytes:<9s}  {text}` -- 18 fixed columns before
    the text, on both the decoded and the `.byte` path -- so slicing beats a
    whitespace split, which breaks on a multi-byte operand like `F6 20`.

    `base` defaults to `start`, so `data` is offset 0 in its own image the way
    every test here means it -- "this instruction sits at `$1000`", not "this
    instruction sits at `$1000` inside an image loaded at `$0000`", which
    would need 4096 bytes of padding in front of it.
    """
    if base is None:
        base = start
    return [line[18:].lstrip() for line in d6502.lines(data, base, start, count)]


def text(data: bytes, base: int | None = None, start: int = 0) -> str:
    """The single instruction's mnemonic-and-operand text."""
    out = lines_of(data, base, start, 1)
    assert len(out) == 1
    return out[0]


# --------------------------------------------------------------------------
# The $F6 bug: INC $nn,X printed as SBC $nn,X, indistinguishable from $F5
# --------------------------------------------------------------------------

def test_f6_is_inc_zero_page_x_not_sbc():
    assert text(bytes([0xF6, 0x20])) == "INC $20,X"


def test_f5_is_still_sbc_zero_page_x():
    assert text(bytes([0xF5, 0x20])) == "SBC $20,X"


# --------------------------------------------------------------------------
# One case per addressing mode, all 13
# --------------------------------------------------------------------------

def test_implied():
    assert text(bytes([0xEA])) == "NOP"


def test_accumulator():
    assert text(bytes([0x0A])) == "ASL A"


def test_immediate():
    assert text(bytes([0xA9, 0x41])) == "LDA #$41"


def test_zero_page():
    assert text(bytes([0xA5, 0x20])) == "LDA $20"


def test_zero_page_x():
    assert text(bytes([0xB5, 0x20])) == "LDA $20,X"


def test_zero_page_y():
    assert text(bytes([0xB6, 0x20])) == "LDX $20,Y"


def test_absolute():
    assert text(bytes([0xAD, 0x34, 0x12])) == "LDA $1234"


def test_absolute_x():
    assert text(bytes([0xBD, 0x34, 0x12])) == "LDA $1234,X"


def test_absolute_y():
    assert text(bytes([0xB9, 0x34, 0x12])) == "LDA $1234,Y"


def test_indirect():
    assert text(bytes([0x6C, 0x34, 0x12])) == "JMP ($1234)"


def test_indexed_indirect_zp_x():
    assert text(bytes([0xA1, 0x20])) == "LDA ($20,X)"


def test_indirect_indexed_zp_y():
    assert text(bytes([0xB1, 0x20])) == "LDA ($20),Y"


def test_relative():
    assert text(bytes([0xD0, 0xFE]), start=0x1000) == "BNE $1000"


# --------------------------------------------------------------------------
# Branch arithmetic
# --------------------------------------------------------------------------

def test_largest_forward_branch():
    # $7F is +127: target is pc + 2 + 127.
    assert text(bytes([0xD0, 0x7F]), start=0x1000) == "BNE $1081"


def test_largest_backward_branch():
    # $80 is -128: target is pc + 2 - 128.
    assert text(bytes([0xD0, 0x80]), start=0x1000) == "BNE $0F82"


def test_branch_crossing_a_page_boundary_is_plain_arithmetic():
    # Page crossing changes the 6502's cycle count, never the target: this
    # pins that the target is pc + 2 + offset regardless of what page it
    # lands on.
    assert text(bytes([0xD0, 0x05]), start=0x10FA) == "BNE $1101"


def test_forward_branch_wraps_at_ffff():
    # At $FFFC, pc + 2 + offset is $1007D unmasked; a real 6502 wraps to
    # $007D.
    assert text(bytes([0xD0, 0x7F]), start=0xFFFC) == "BNE $007D"


def test_backward_branch_wraps_at_0000():
    # At $0000, pc + 2 + offset would be negative unmasked; a real 6502
    # wraps to the top of memory.
    assert text(bytes([0xD0, 0x80]), start=0x0000) == "BNE $FF82"


# --------------------------------------------------------------------------
# Unknown opcodes: resynchronise, never guess
# --------------------------------------------------------------------------

def test_an_unknown_opcode_resynchronises_by_one_byte():
    assert lines_of(bytes([0x02, 0xA9, 0x41]), count=2) == [".byte $02", "LDA #$41"]


def test_a_run_of_illegal_opcodes_is_all_data():
    assert lines_of(bytes([0x02, 0x22, 0xFF]), count=3) == [
        ".byte $02", ".byte $22", ".byte $FF",
    ]


def test_brk_is_one_byte():
    # capstone counts BRK's signature byte and reports size 2; most 6502
    # listings, and this tool, do not. Declared exception, not a bug -- see
    # docs/148-d6502.md "What is known".
    assert lines_of(bytes([0x00, 0xEA]), count=2) == ["BRK", "NOP"]


# --------------------------------------------------------------------------
# Edge cases: truncated tail, out-of-range start
# --------------------------------------------------------------------------

def test_a_truncated_instruction_prints_its_bytes():
    # Absolute LDA missing its high byte: the image ends mid-instruction.
    # Today `lines()` silently stops instead of saying anything was there.
    assert lines_of(bytes([0xAD, 0x34]), count=5) == [".byte $AD", ".byte $34"]


def test_a_start_address_outside_the_image_says_so(tmp_path, capsys):
    image = tmp_path / "scratch.bin"
    image.write_bytes(bytes([0xEA]))
    d6502.run(str(image), 0, 0x1000, 5)
    out, err = capsys.readouterr()
    assert out == ""
    assert "$1000" in err
    assert "outside the image" in err
