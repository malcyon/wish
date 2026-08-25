"""`por/dos_savegame.py`, the DOS saved game's byte map.

Fixed-offset indexing into a 13137-byte file, which is the shape of bug this
project has actually shipped -- a stride slip, a width read at half, a slice
off by one. So the boundaries are tested from both sides rather than the
middle, and a real specimen is used where one is available.
"""

import pytest

from por import dos_savegame as sg


def blank() -> bytearray:
    """A well-formed empty saved game: the right size and nothing in it."""
    return bytearray(sg.SAVGAM_SIZE)


# --- the variable space ------------------------------------------------------


def test_the_variable_space_maps_both_ends_and_refuses_one_past():
    """`1 + 2*(addr - $4900)`, checked at the edges rather than the middle."""
    assert sg.word_offset(sg.VAR_BASE) == sg.VAR_OFFSET
    last = sg.VAR_BASE + sg.VAR_WORDS - 1
    assert last == 0x52FF, "the comment on VAR_WORDS says $52FF; keep it true"
    assert sg.word_offset(last) == sg.VAR_OFFSET + 2 * (sg.VAR_WORDS - 1)
    # The last word ends inside the region and the next one would not.
    assert sg.word_offset(last) + 2 == sg.ECL_BUFFER[0]
    for outside in (sg.VAR_BASE - 1, last + 1):
        with pytest.raises(sg.DosSaveError):
            sg.word_offset(outside)


def test_every_named_address_is_inside_the_variable_space():
    """A named constant nothing can read is a typo waiting to be believed."""
    for name in ("AREA", "CLOCK", "INDOORS", "SCRIPT", "FLAGS_FIRST",
                 "FLAGS_LAST", "WALLSET", "WALLMAP", "PARTY_SIZE", "DISK",
                 "ENCOUNTER_TEXT"):
        sg.word_offset(getattr(sg, name))


def test_the_five_regions_tile_the_file_with_no_gap():
    assert (sg.VAR_OFFSET + 2 * sg.VAR_WORDS) == sg.ECL_BUFFER[0]
    assert sg.ECL_BUFFER[1] == sg.POS_X
    assert sg.PARTY_SIZE_BYTE + 1 == sg.PARTY_TABLE
    used = sg.PARTY_TABLE + sg.PARTY_ENTRIES * sg.PARTY_ENTRY
    assert used <= sg.SAVGAM_SIZE


def test_a_word_is_little_endian():
    save = blank()
    save[sg.word_offset(sg.AREA):sg.word_offset(sg.AREA) + 2] = b"\x34\x12"
    assert sg.word(bytes(save), sg.AREA) == 0x1234


# --- a truncated buffer ------------------------------------------------------


@pytest.mark.parametrize("accessor", ["dax_number", "party_size", "position",
                                      "character_files"])
def test_a_short_buffer_is_refused_rather_than_indexed(accessor):
    """`IndexError` from inside a decode says nothing; this says what is wrong."""
    with pytest.raises(sg.DosSaveError):
        getattr(sg, accessor)(bytes(sg.SAVGAM_SIZE - 1))


def test_a_short_buffer_is_refused_before_a_word_is_unpacked():
    with pytest.raises(sg.DosSaveError):
        sg.word(bytes(10), sg.AREA)


# --- the party's filenames ---------------------------------------------------


def _entry(save: bytearray, n: int, length: int, name: bytes) -> None:
    at = sg.PARTY_TABLE + n * sg.PARTY_ENTRY
    save[at] = length
    save[at + 1:at + 1 + len(name)] = name


def test_a_name_of_the_longest_legal_length_is_read():
    save = blank()
    _entry(save, 0, 8, b"CHRDATA1")
    assert sg.character_files(bytes(save)) == ["CHRDATA1"]


def test_a_length_past_the_name_field_is_not_read_as_a_name():
    """The regression test for the loose bound.

    An entry is one length byte, the name, then 32 bytes of heap scratch. A
    length of nine or more would decode the scratch as filename characters and
    hand back a wrong-but-plausible name -- which is worse than none, because
    the engine loads the party from these.
    """
    for length in (sg.PARTY_NAME_LEN, 12, 40):
        save = blank()
        _entry(save, 0, length, b"CHRDATA1" + b"\x7f" * 32)
        assert sg.character_files(bytes(save)) == [], length


def test_an_empty_entry_is_skipped_rather_than_returned_blank():
    save = blank()
    _entry(save, 0, 0, b"")
    _entry(save, 1, 8, b"CHRDATB2")
    assert sg.character_files(bytes(save)) == ["CHRDATB2"]


def test_all_six_entries_are_read_at_their_own_stride():
    save = blank()
    for n in range(sg.PARTY_ENTRIES):
        _entry(save, n, 8, f"CHRDATA{n}".encode())
    assert sg.character_files(bytes(save)) == [
        f"CHRDATA{n}" for n in range(sg.PARTY_ENTRIES)]


# --- position and the clock --------------------------------------------------


def test_facing_comes_back_in_the_c64_s_units():
    """The file stores it doubled; everything else in this project does not."""
    save = blank()
    save[sg.POS_X], save[sg.POS_Y] = 8, 14
    save[sg.POS_FACING] = 3 * sg.FACING_SCALE
    assert sg.position(bytes(save)) == (8, 14, 3)


def test_the_clock_reads_its_six_digit_words_as_one_time():
    save = blank()
    for i, digit in enumerate((0, 3, 2, 10, 21, 6)):    # 10:23, day 21, month 6
        at = sg.word_offset(sg.CLOCK + i)
        save[at:at + 2] = digit.to_bytes(2, "little")
    assert sg.clock(bytes(save)) == (10, 23, 21, 6)


def test_the_retarget_recipe_names_the_addresses_the_map_names():
    """The recipe is formatted from the constants, so it cannot drift."""
    recipe = " ".join(sg.RETARGET_WRITES)
    for address in (sg.AREA, sg.SCRIPT, sg.DISK, sg.WALLSET, sg.WALLMAP,
                    sg.PARTY_SIZE):
        assert f"${address:04X}" in recipe
    # The write #59 recorded as unnecessary and `work/p60` proved is not:
    # the target area's own script.
    assert f"{sg.ECL_BUFFER[0]}-{sg.ECL_BUFFER[1] - 1}" in recipe


# --- writing -----------------------------------------------------------------


def test_the_clock_goes_back_the_way_it_came():
    save = blank()
    sg.put_clock(save, (0, 3, 2, 10, 21, 6))
    assert sg.clock(bytes(save)) == (10, 23, 21, 6)


def test_a_clock_of_the_wrong_length_is_refused():
    with pytest.raises(sg.DosSaveError):
        sg.put_clock(blank(), (0, 3, 2))


def test_the_party_size_is_written_to_both_places_that_carry_it():
    """They move together in the engine's own save, so they do here."""
    save = blank()
    sg.put_party_size(save, 4)
    assert sg.party_size(bytes(save)) == 4
    assert sg.word(bytes(save), sg.PARTY_SIZE) == 4


def test_a_position_is_written_with_the_facing_doubled():
    save = blank()
    sg.put_position(save, 8, 14, 3)
    assert sg.position(bytes(save)) == (8, 14, 3)
    assert save[sg.POS_FACING] == 3 * sg.FACING_SCALE


def test_the_party_filenames_are_rewritten_for_the_slot():
    """The engine loads the party from these, not from the slot letter."""
    save = blank()
    sg.put_character_files(save, "C")
    assert sg.character_files(bytes(save)) == [
        f"CHRDATC{n}" for n in range(1, 7)]


def test_the_wall_map_marks_the_slots_the_triple_fills():
    assert sg.wall_map((2, 4, 1)) == (1, 2, 3)
    assert sg.wall_map((0, sg.EMPTY, sg.EMPTY)) == (1, sg.EMPTY, sg.EMPTY)


def test_a_retarget_writes_the_place_and_stages_the_script():
    save = blank()
    script = bytes([0x88, 0x13]) + bytes(range(256)) * 4
    sg.retarget(save, area=20, dax=2, wallset=(2, 4, 1), script=script)
    save = bytes(save)
    assert save[0] == 2
    assert sg.area_id(save) == 20
    assert sg.word(save, sg.SCRIPT) == 20
    assert sg.word(save, sg.DISK) == 2
    assert sg.wall_triple(save) == (2, 4, 1)
    assert [sg.word(save, sg.WALLMAP + i) for i in range(3)] == [1, 2, 3]
    # The buffer holds the block from byte 2 on -- the `88 13` header stays
    # in the DAX.
    body = script[sg.ECL_HEADER:]
    assert save[sg.ECL_BUFFER[0]:sg.ECL_BUFFER[0] + len(body)] == body


def test_a_script_too_long_for_the_buffer_is_refused():
    room = sg.ECL_BUFFER[1] - sg.ECL_BUFFER[0]
    with pytest.raises(sg.DosSaveError):
        sg.retarget(blank(), area=20, dax=2, wallset=(2, 4, 1),
                    script=bytes(room + sg.ECL_HEADER + 1))


# --- the .DAX container ------------------------------------------------------


def _dax(blocks: dict[int, bytes]) -> bytes:
    """A `.DAX` with each block stored as literal runs."""
    import struct
    index, data = bytearray(), bytearray()
    for bid, raw in sorted(blocks.items()):
        packed = bytearray()
        for i in range(0, len(raw), 128):
            piece = raw[i:i + 128]
            packed += bytes([len(piece) - 1]) + piece
        index += struct.pack("<BIHH", bid, len(data), len(raw), len(packed))
        data += packed
    return struct.pack("<H", len(index)) + bytes(index) + bytes(data)


def test_a_dax_block_comes_back_at_its_stated_size():
    raw = bytes(range(256)) * 3
    assert sg.dax_block(_dax({20: raw, 0: b"other"}), 20) == raw


def test_a_run_length_repeat_expands():
    """A lead byte at or above 128 repeats; 128 is the longest run it can ask
    for, which is where an off-by-one in `256 - n` would show."""
    import struct
    body = bytes([256 - 128, 0])
    index = struct.pack("<BIHH", 1, 0, 128, len(body))
    data = struct.pack("<H", len(index)) + index + body
    assert sg.dax_block(data, 1) == bytes(128)


def test_a_block_that_is_not_there_is_named_rather_than_returned_empty():
    with pytest.raises(sg.DosSaveError):
        sg.dax_block(_dax({0: b"only this one"}), 20)


def test_a_block_that_unpacks_short_is_refused():
    """A truncated container would otherwise hand back a plausible prefix."""
    import struct
    body = bytes([1, 0x41, 0x42])
    index = struct.pack("<BIHH", 3, 0, 99, len(body))
    with pytest.raises(sg.DosSaveError):
        sg.dax_block(struct.pack("<H", len(index)) + index + body, 3)

# --- what a damaged .DAX does ------------------------------------------------


def _damaged_dax(body: bytes, block_id: int = 7, raw: int = 64) -> bytes:
    """A one-block `.DAX` whose block body is exactly `body`.

    Distinct from `_dax` above, which builds a well-formed archive from whole
    blocks; this one exists to hand the unpacker a body that is wrong.
    """
    import struct
    entry = struct.pack("<BIHH", block_id, 0, raw, len(body))
    return struct.pack("<H", len(entry)) + entry + body


def test_a_block_ending_on_a_dangling_run_is_named_not_indexed():
    """A truncated archive must reach `write_dos_save` as a refusal.

    The run branch of the unpacker indexes `chunk[i + 1]`, where the copy
    branch beside it takes a slice and degrades to something the length check
    catches. A half-copied `.DAX` used to raise `IndexError` from inside, and
    `por.dos.write_dos_save` catches only `DosSaveError` -- so the whole
    conversion came down with a traceback instead of keeping the template's
    square and saying why.
    """
    with pytest.raises(sg.DosSaveError) as caught:
        sg.dax_block(_damaged_dax(bytes([200])), 7)
    assert "operand is missing" in str(caught.value)


def test_a_block_that_unpacks_short_is_still_caught_by_the_length_check():
    """The copy branch's own failure mode, so the guard above did not replace
    it with a narrower one.

    The wording is the harness decoder's, which is now the only one (#76); the
    behaviour asserted is what it always was.
    """
    with pytest.raises(sg.DosSaveError) as caught:
        sg.dax_block(_damaged_dax(bytes([2, 1, 2, 3])), 7)
    assert "not the 64 the index states" in str(caught.value)


@pytest.mark.parametrize("call", [
    lambda save: sg.put_word(save, sg.AREA, 5),
    lambda save: sg.put_clock(save, [0, 0, 0, 0, 0, 0]),
])
def test_the_writers_refuse_a_short_buffer_like_the_readers_do(call):
    """`put_word` and `put_clock` skipped `_whole`, so a short buffer reached
    `struct.pack_into` and came back as `struct.error` -- the unhelpful raw
    error the guard exists to replace."""
    with pytest.raises(sg.DosSaveError):
        call(bytearray(10))
