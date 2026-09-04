"""`tools/recordsweep.py`'s hit-finding, on bytes built here rather than off a
disk -- `hits()` and `indirect_hits()` are pure byte matching and need no
game specimen to exercise. `pytest tests/test_recordsweep.py` runs with zero
skips.

`indirect_hits()` is the other half of the negative that settled
`#224 (0x0B9 and 0x0BA are documented both as an NPC marker and as the
dual-class slot)`: a record offset reached through `(pointer),Y` or
`(pointer,X)` rather than an absolute operand, which `hits()` cannot see.
That scan was run once by a script nobody kept -- `#230 (The indirect half of
a record-offset census cannot be rerun, because its script was never kept)`.
"""

from tools.d6502 import M_IZX, M_IZY
from tools.recordsweep import hits, indirect_hits

# --------------------------------------------------------------------------
# hits() -- absolute-mode census, previously untested
# --------------------------------------------------------------------------

def test_hits_finds_an_absolute_mode_reference():
    # LDA $6BB9
    data = bytes([0xAD, 0xB9, 0x6B])
    found = list(hits(data, {0x6BB9}))
    assert found == [(0, "LDA", "", 0x6BB9)]


def test_hits_ignores_an_address_not_in_want():
    data = bytes([0xAD, 0xB9, 0x6B])
    assert list(hits(data, {0x6BBA})) == []


# --------------------------------------------------------------------------
# indirect_hits() -- the half #230 restores
# --------------------------------------------------------------------------

def test_indirect_hits_finds_ldy_then_indirect_indexed_y():
    # LDY #$B9 ; NOP NOP ; LDA ($1A),Y
    data = bytes([0xA0, 0xB9, 0xEA, 0xEA, 0xB1, 0x1A])
    found = list(indirect_hits(data, {0xB9}))
    assert found == [(0, "Y", 0xB9, 4, "LDA", M_IZY)]


def test_indirect_hits_finds_ldx_then_indexed_indirect_x():
    # LDX #$BA ; NOP ; STA ($20,X)
    data = bytes([0xA2, 0xBA, 0xEA, 0x81, 0x20])
    found = list(indirect_hits(data, {0xBA}))
    assert found == [(0, "X", 0xBA, 3, "STA", M_IZX)]


def test_indirect_hits_requires_the_matching_mode_not_any_indirect_opcode():
    # LDY #$B9 followed only by an (zp,X) access -- the wrong mode for Y.
    data = bytes([0xA0, 0xB9, 0xA1, 0x20])
    assert list(indirect_hits(data, {0xB9})) == []


def test_indirect_hits_ignores_a_low_byte_not_in_want():
    data = bytes([0xA0, 0xB8, 0xB1, 0x1A])
    assert list(indirect_hits(data, {0xB9})) == []


def test_indirect_hits_respects_the_window():
    # Matching opcode two bytes past the operand: outside a window of 2,
    # inside a window of 3.
    data = bytes([0xA0, 0xB9, 0xEA, 0xEA, 0xB1, 0x1A])
    assert list(indirect_hits(data, {0xB9}, window=2)) == []
    found = list(indirect_hits(data, {0xB9}, window=3))
    assert found == [(0, "Y", 0xB9, 4, "LDA", M_IZY)]


def test_indirect_hits_takes_the_first_match_in_the_window():
    # Two candidate (zp),Y opcodes in range: only the nearer one is reported,
    # the same way one LDY only sets up one access.
    data = bytes([0xA0, 0xB9, 0xB1, 0x10, 0xB1, 0x20])
    found = list(indirect_hits(data, {0xB9}))
    assert found == [(0, "Y", 0xB9, 2, "LDA", M_IZY)]


def test_indirect_hits_is_byte_level_like_hits():
    # The match starts one byte into a run that is not itself a real
    # instruction stream -- the same "claim about bytes" guarantee hits()
    # gives, exercised here rather than merely asserted in the docstring.
    data = bytes([0x00, 0xA0, 0xB9, 0xB1, 0x1A])
    found = list(indirect_hits(data, {0xB9}))
    assert found == [(1, "Y", 0xB9, 3, "LDA", M_IZY)]


def test_indirect_hits_ignores_a_match_with_no_operand_byte():
    """A `(zp),Y` opcode as a file's last byte is a truncated instruction.

    `main` prints the pointer byte after the opcode, so reporting a match
    with nothing after it raised `IndexError` and aborted the whole census
    partway through -- a traceback instead of a result, on any offset or
    title where a file happened to end that way. Found by review on
    `#230 (The indirect half of a record-offset census cannot be rerun,
    because its script was never kept)`; the two real hits land three and
    four bytes past their load, nowhere near a tail, so no reported figure
    ever depended on it.
    """
    data = bytes([0xA0, 0xB9]) + bytes([0xEA] * 7) + bytes([0xB1])
    assert data[-1] == 0xB1 and len(data) == 10
    assert list(indirect_hits(data, {0xB9})) == []
    # One byte further from the tail and it is a hit again, so the guard
    # rejects the truncation rather than the whole window.
    assert list(indirect_hits(data + b"\x1a", {0xB9})) == [
        (0, "Y", 0xB9, 9, "LDA", M_IZY)]
