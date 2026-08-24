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
