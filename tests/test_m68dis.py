"""The 68000 disassembler, on encodings built here rather than read off a disk.

Every case is assembled by hand from the encoding in the Motorola manual, so
the suite needs no game data and skips nothing.  The cases chosen are the ones
that are easy to get wrong and silent when they are: sign-extended
displacements, a branch that goes backwards, MOVEM's register mask read the
other way round for ``-(An)``, and a word that is not an instruction at all.

The last of those is the point of the tool.  A disassembler that guesses
produces a plausible listing from the middle of a string table, and the guess
is what gets believed.
"""

from tools import m68dis


def text(words, address=0x1000):
    """Disassemble one instruction built from a list of big-endian words."""
    data = b"".join(word.to_bytes(2, "big") for word in words)
    return m68dis.decode(data, 0, address).text


def one(words, address=0x1000):
    data = b"".join(word.to_bytes(2, "big") for word in words)
    return m68dis.decode(data, 0, address)


# --------------------------------------------------------------------------
# Displacements, which are signed and are the commonest thing to get wrong
# --------------------------------------------------------------------------

def test_a_positive_word_displacement_off_an_address_register():
    assert text([0x3C2D, 0x0008]) == "move.w $8(a5),d6"


def test_a_negative_word_displacement_is_sign_extended():
    # 0xce26 is -0x31da, not +0xce26.  Reading it unsigned puts the operand
    # 52 kilobytes the wrong side of a4 and the mistake never announces itself.
    assert text([0x2F2C, 0xCE26]) == "move.l -$31da(a4),-(a7)"


def test_a_negative_link_frame():
    assert text([0x4E55, 0xFFB6]) == "link a5,#-$4a"


def test_a_negative_byte_displacement_in_an_indexed_address():
    assert text([0x1030, 0x10F4]) == "move.b -$c(a0,d1.w),d0"


def test_an_absolute_short_address_keeps_its_raw_word():
    assert text([0x3038, 0xFFE0]) == "move.w $ffe0.w,d0"


def test_an_absolute_long_address():
    assert text([0x4EB9, 0x0002, 0x55B2]) == "jsr $000255b2"


# --------------------------------------------------------------------------
# Branches, resolved to the address they reach
# --------------------------------------------------------------------------

def test_a_forward_short_branch_resolves_to_its_target():
    item = one([0x6704], address=0x25826)
    assert item.text == "beq.b $2582c"
    assert item.target == 0x2582C


def test_a_backward_short_branch_resolves_to_its_target():
    item = one([0x60F0], address=0x1000)
    assert item.text == "bra.b $ff2"
    assert item.target == 0x0FF2


def test_a_forward_word_branch():
    item = one([0x6600, 0x0354], address=0x25832)
    assert item.text == "bne.w $25b88"
    assert item.target == 0x25B88


def test_a_backward_word_branch():
    item = one([0x6000, 0xFF00], address=0x2000)
    assert item.text == "bra.w $1f02"
    assert item.target == 0x1F02


def test_a_backward_dbra():
    item = one([0x51C8, 0xFFFA], address=0x1000)
    assert item.text == "dbra d0,$ffc"
    assert item.target == 0x0FFC


def test_a_pc_relative_load_resolves_to_the_address_it_reaches():
    item = one([0x41FA, 0x0010], address=0x1000)
    assert item.text == "lea $1012(pc),a0"
    assert item.target == 0x1012


def test_a_branch_to_an_odd_address_is_not_an_instruction():
    # 0x6973 is the letters "is" in the middle of a string.  Decoding it as
    # bvs.b would name a target the 68000 cannot branch to.
    assert text([0x6973], address=0x4C4) == "dc.w $6973"


# --------------------------------------------------------------------------
# MOVEM, whose mask is read the other way round for -(An)
# --------------------------------------------------------------------------

def test_movem_to_predecrement_reads_the_mask_backwards():
    # Bit 0 is a7 here, so 0x3f30 is d2-d7/a2-a3 and not d4-d5/a0-a5.
    assert text([0x48E7, 0x3F30]) == "movem.l d2-d7/a2-a3,-(a7)"


def test_movem_from_postincrement_reads_the_mask_forwards():
    assert text([0x4CDF, 0x0CFC]) == "movem.l (a7)+,d2-d7/a2-a3"


def test_the_same_register_set_has_two_different_masks():
    forwards = one([0x4CDF, 0x0CFC]).operands.split(",", 1)[1]
    backwards = one([0x48E7, 0x3F30]).operands.split(",", 1)[0]
    assert forwards == backwards == "d2-d7/a2-a3"


def test_a_single_register_and_a_split_run():
    assert text([0x48E7, 0x8080]) == "movem.l d0/a0,-(a7)"


# --------------------------------------------------------------------------
# A word that is not an instruction falls through to data
# --------------------------------------------------------------------------

def test_line_a_and_line_f_are_not_instructions():
    assert text([0xA000]) == "dc.w $a000"
    assert text([0xFFFF]) == "dc.w $ffff"


def test_bit_eight_is_not_a_unary_operation():
    # 0x4552 is the letters "ER".  NEGX/CLR/NEG/NOT/TST live in bits 11-8, so
    # a decoder reading only 11-9 calls this neg.w (a2) and means it.  That
    # bug was in this file's first draft and a cross-check caught it.  This
    # assertion is the proof of it: remove the bit-8 guard and it goes red.
    assert text([0x4552]) == "dc.w $4552"
    # 0x4329 is the letters "C)".  A second refusal worth pinning, but not a
    # second proof of the same bug -- the size-3 guard catches it either way.
    assert text([0x4329]) == "dc.w $4329"


def test_a_68020_index_extension_is_not_a_68000_instruction():
    # Bit 8 of the extension word selects the 68020 full format and bits 10-9
    # are its scale.  Neither exists on a 68000.
    assert text([0x1030, 0x110C]) == "dc.w $1030"
    assert text([0x1030, 0x12F4]) == "dc.w $1030"


def test_an_addressing_mode_the_instruction_cannot_take():
    # move.b with an address register source: 0x1008 would be move.b a0,d0.
    assert text([0x1008]) == "dc.w $1008"
    # movea has no byte size.
    assert text([0x1040]) == "dc.w $1040"


def test_an_instruction_cut_off_by_the_end_of_the_buffer():
    assert m68dis.decode(b"\x48\xe7", 0).text == "dc.w $48e7"
    assert m68dis.decode(b"\x48\xe7", 0).known is False


def test_nothing_outside_the_window_is_read():
    # The instruction is four bytes and the caller asked for two.  Reading the
    # other two would be reading bytes nobody asked about -- the next hunk, a
    # relocation table -- and disassembling them as if they had been requested.
    data = bytes.fromhex("4e55ffb6" "4e75")
    assert [item.text for item in m68dis.disassemble(data, 0, 2)] == ["dc.w $4e55"]
    assert [item.text for item in m68dis.disassemble(data, 0, 4)] == ["link a5,#-$4a"]


def test_a_reference_scan_does_not_read_past_its_range():
    # 0x4879 0x0002 0x55b2 is pea $255b2, and it starts two bytes inside a
    # window that stops before its last word.
    data = bytes.fromhex("4e71" "4879000255b2")
    assert m68dis.references_to(data, 0x255B2, 0, 6) == []
    assert [hit.mnemonic for hit in m68dis.references_to(data, 0x255B2, 0, 8)] == ["pea"]


def test_a_decoded_instruction_says_it_is_known():
    assert one([0x4E75]).known is True
    assert one([0x4552]).known is False


# --------------------------------------------------------------------------
# The rest of what a file-loading routine is made of
# --------------------------------------------------------------------------

def test_the_ordinary_instructions():
    assert text([0x4E75]) == "rts"
    assert text([0x4E71]) == "nop"
    assert text([0x4E5D]) == "unlk a5"
    assert text([0x7001]) == "moveq #$1,d0"
    assert text([0x4A04]) == "tst.b d4"
    assert text([0x422D, 0xFFB7]) == "clr.b -$49(a5)"
    assert text([0x0C40, 0x0194]) == "cmpi.w #$194,d0"
    assert text([0x0C00, 0x0041]) == "cmpi.b #$41,d0"
    assert text([0x504F]) == "addq.w #$8,a7"
    assert text([0x5780]) == "subq.l #$3,d0"
    assert text([0xC151]) == "and.w d0,(a1)"
    assert text([0x86AA, 0x0010]) == "or.l $10(a2),d3"
    assert text([0xB310]) == "eor.b d1,(a0)"
    assert text([0xB081]) == "cmp.l d1,d0"
    assert text([0x4879, 0x0002, 0x55B2]) == "pea $000255b2"
    assert text([0x4EAC, 0x8A9A]) == "jsr -$7566(a4)"
    assert text([0x4ED0]) == "jmp (a0)"


def test_an_immediate_byte_takes_only_the_low_half_of_its_word():
    assert text([0x0C00, 0x0041]) == "cmpi.b #$41,d0"
    assert text([0x0C40, 0x0041]) == "cmpi.w #$41,d0"
    assert text([0x0C80, 0x0000, 0x0041]) == "cmpi.l #$41,d0"


def test_instruction_lengths():
    assert one([0x4E75]).size == 2
    assert one([0x3C2D, 0x0008]).size == 4
    assert one([0x4EB9, 0x0002, 0x55B2]).size == 6
    assert one([0x0C80, 0x0000, 0x0041]).size == 6


# --------------------------------------------------------------------------
# Walking a range, and finding what points at an address
# --------------------------------------------------------------------------

def test_disassemble_walks_by_instruction_length():
    data = bytes.fromhex("4e55ffb6" "48e73f30" "4e75")
    items = m68dis.disassemble(data, 0, len(data))
    assert [item.text for item in items] == [
        "link a5,#-$4a",
        "movem.l d2-d7/a2-a3,-(a7)",
        "rts",
    ]
    assert [item.address for item in items] == [0, 4, 8]


def test_references_to_finds_a_pc_relative_load():
    # lea $10(pc),a0 at offset 0, then filler, with the string at offset 0x12.
    data = bytes.fromhex("41fa0010") + b"\x4e\x71" * 7 + b"pc\x00\x00"
    hits = m68dis.references_to(data, 0x12, 0, len(data))
    assert [(hit.address, hit.text) for hit in hits] == [(0, "lea $12(pc),a0")]


def test_references_to_finds_an_absolute_long_call():
    data = bytes.fromhex("4eb9000255b2")
    hits = m68dis.references_to(data, 0x255B2, 0, len(data))
    assert [hit.mnemonic for hit in hits] == ["jsr"]


def test_a_window_with_no_whole_word_left_is_refused_the_same_way():
    """`decode` is public; `_Undecodable` is private and must not escape it.

    Asking to decode at an offset the window does not reach is the same
    mistake as asking past the end of the buffer, and the two answered
    differently: a short buffer raised `ValueError`, a narrow `end` raised
    `_Undecodable` from inside the cursor. Nothing in the tree reaches it
    today -- `disassemble` and `references_to` both bound `pos + 2 <= end`
    before they call -- but `decode` is exported, and the next caller is the
    one this is for (#148).
    """
    import pytest

    from tools.m68dis import decode

    data = bytes.fromhex("4e754e75")            # rts, rts
    assert decode(data, 2, end=4).mnemonic == "rts"
    with pytest.raises(ValueError):
        decode(data, 2, end=2)                  # no whole word inside it
    with pytest.raises(ValueError):
        decode(data[:2], 2)                     # the same mistake, no window
