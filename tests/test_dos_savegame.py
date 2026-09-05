"""`goldbox/dos_savegame.py`, the DOS saved game's byte map.

Fixed-offset indexing into a 13137-byte file, which is the shape of bug this
project has actually shipped -- a stride slip, a width read at half, a slice
off by one. So the boundaries are tested from both sides rather than the
middle, and a real specimen is used where one is available.
"""

import pytest

from goldbox import dos_savegame as sg


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


def test_a_pool_of_radiance_position_lands_on_the_module_constants():
    """The default shape a bare `put_position`/`position` infer from a
    13137-byte buffer's own length is Pool of Radiance's, so this must keep
    landing on `POS_X`/`POS_Y`/`POS_FACING` exactly -- the fix for #220 must
    not move Pool of Radiance's own offsets."""
    save = blank()
    sg.put_position(save, 8, 14, 3)
    assert (save[sg.POS_X], save[sg.POS_Y], save[sg.POS_FACING]) == \
        (8, 14, 3 * sg.FACING_SCALE)


@pytest.mark.parametrize("key,x,table", [
    ("curse-of-the-azure-bonds", 12801, 12821),
    ("secret-of-the-silver-blades", 5121, 5141)])
def test_a_later_titles_square_is_where_its_own_writer_puts_it(key, x, table):
    """#253, correcting #220. Curse's square is at Pool of Radiance's own
    12801 and Silver Blades' at 5121 -- the first byte after the variable
    array and the staged script in each -- and the twelve extra bytes those
    two titles carry sit *inside* the block rather than in front of it.

    #220 read them as sitting in front and so moved x twelve bytes on, which
    is what this pins against. Both directions are asserted on purpose: the
    offset is right, and it is specifically not twelve past.
    `tests/test_dossavewritemap.py` has the same claim read out of each
    engine's own `BlockWrite` chain, which is where it is settled.
    """
    shape = sg.save_shape_for(key)
    assert (shape.pos_x, shape.pos_y, shape.pos_facing) == (x, x + 1, x + 2)
    assert shape.unnamed == 12
    # The twelve are between the block's seventh byte and the party size.
    assert shape.pos_x + 7 + shape.unnamed == shape.party_table - 1
    # And the party table did not move with the square.
    assert shape.party_table == table

    save = bytearray(shape.size)
    sg.put_position(save, 8, 14, 3, shape)
    assert sg.position(bytes(save), shape) == (8, 14, 3)
    # Nothing was written twelve bytes on, where #220 put the square.
    assert save[x + 12:x + 15] == b"\x00\x00\x00"


def test_a_curse_square_is_at_pool_of_radiances_own_offset():
    """The finding of #253 in one line: the two titles' squares coincide.

    They coincide because the two regions in front of the block -- the 5120
    bytes of variable array and the 7680 of staged script -- are the same
    size in both engines, not because Curse inherited the constant.
    """
    curse = sg.save_shape_for("curse-of-the-azure-bonds")
    assert (curse.pos_x, curse.pos_y, curse.pos_facing) == \
        (sg.POS_X, sg.POS_Y, sg.POS_FACING)
    assert curse.size != sg.SAVGAM_SIZE, "and yet they are different files"


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
    `goldbox.dos.write_dos_save` catches only `DosSaveError` -- so the whole
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


# --- the outdoor form (#59's outdoor half) -----------------------------------


def test_the_travel_square_round_trips_through_its_vm_words():
    save = blank()
    sg.put_travel_square(save, 7, 29)
    assert sg.travel_square(bytes(save)) == (7, 29)
    assert sg.word(bytes(save), sg.TRAVEL_X) == 7
    assert sg.word(bytes(save), sg.TRAVEL_Y) == 29


def test_an_all_zero_save_reads_as_outdoors_because_49e6_is_zero():
    """The flag is 1 indoors; a blank buffer is 0 everywhere, so outdoors.

    That is the measured meaning (3 of 3 each way, #59), not a default a
    writer may lean on: a conversion writes the flag it means.
    """
    save = blank()
    assert sg.outdoors(bytes(save))
    sg.put_word(save, sg.INDOORS, 1)
    assert not sg.outdoors(bytes(save))


def test_the_window_offsets_cover_the_three_outdoor_areas_and_step_by_13():
    """World x = local x + offset; window 26 was measured on screen (20 = 7
    + 13), 25 and 27 are the C64 seam arithmetic."""
    assert set(sg.WINDOW_X_OFFSET) == {25, 26, 27}
    assert sg.WINDOW_X_OFFSET[26] == 13
    assert [sg.WINDOW_X_OFFSET[a] for a in (25, 26, 27)] == [0, 13, 26]


# --- the tail bytes between the facing and the party size (#59) --------------


def test_put_tail_state_writes_the_measured_values_not_the_templates():
    """The four bytes 12804-12807 are written, not inherited.

    A template's tail belongs to another party in another place, so the test
    starts from values that are all wrong and checks every one of them moves:
    a writer that skipped any byte would leave the stale value visible here.
    """
    save = blank()
    for off in (sg.SCRATCH_BYTE, sg.VM_COPY_BYTE,
                sg.VIEW_MODE_BYTE, sg.TAIL_CONSTANT_BYTE):
        save[off] = 0xEE
    sg.put_word(save, sg.VM_SCRATCH, 26)
    sg.put_tail_state(save, indoors=True)
    assert save[sg.SCRATCH_BYTE] == sg.SCRATCH_INDOORS
    assert save[sg.VM_COPY_BYTE] == 26          # the low byte of $5200
    assert save[sg.VIEW_MODE_BYTE] == sg.VIEW_MODE_INDOORS
    assert save[sg.TAIL_CONSTANT_BYTE] == sg.TAIL_CONSTANT


def test_the_outdoor_tail_is_the_outdoor_measurement_not_the_indoor_one():
    """12804 reads 0 in every indoor specimen and 14 in every outdoor one.

    Both bytes that vary with where the party stands have to vary together.
    Writing the indoor 0 into an outdoor save is inheriting a value measured
    somewhere else, which is the whole thing `put_tail_state` exists to stop --
    and it is invisible, because the engine maintains this byte and the save
    still loads.
    """
    save = blank()
    sg.put_tail_state(save, indoors=False)
    assert save[sg.SCRATCH_BYTE] == sg.SCRATCH_OUTDOORS
    assert save[sg.VIEW_MODE_BYTE] == sg.VIEW_MODE_OUTDOORS
    assert sg.SCRATCH_INDOORS != sg.SCRATCH_OUTDOORS


def test_the_view_mode_byte_follows_the_indoors_argument():
    """1 indoors and 3 outdoors, the only two values twelve specimens hold."""
    for indoors, expected in ((True, 1), (False, 3)):
        save = blank()
        sg.put_tail_state(save, indoors=indoors)
        assert save[sg.VIEW_MODE_BYTE] == expected


def test_the_vm_copy_byte_takes_the_low_byte_of_5200_not_the_whole_word():
    """`$5200` is a word and 12805 is a byte; 13 of 13 files agree on the low
    half. A writer that packed the word would corrupt 12806 beside it."""
    save = blank()
    sg.put_word(save, sg.VM_SCRATCH, 0x1234)
    sg.put_tail_state(save)
    assert save[sg.VM_COPY_BYTE] == 0x34
    assert save[sg.VIEW_MODE_BYTE] == sg.VIEW_MODE_INDOORS


def test_the_shared_ecl_space_stops_at_the_last_quest_flag():
    """Above `$4AF8` the DOS variable array has no C64 counterpart at all, so
    nothing there may be sourced from a C64 save. The boundary is the fact;
    the constant exists so a converter cannot drift past it by accident."""
    assert sg.ECL_SHARED_LAST == 0x4AF8
    for dos_only in (sg.WALLSET, sg.DISK, sg.PARTY_SIZE, sg.VM_SCRATCH,
                     sg.ENCOUNTER_TEXT):
        assert dos_only > sg.ECL_SHARED_LAST


# --- the container in every title (#53) --------------------------------------
#
# Everything above is Pool of Radiance's, synthetic and offline. These read the
# player's own archives and skip without them, which means CI never runs them:
# what stands behind the other three shapes on a machine with no archives is
# the width sum in `DosSaveShape.__post_init__` and
# `test_every_shape_tiles_its_own_container`, and neither says a field is in
# the right place. Say in the commit that you ran these somewhere the archives
# exist.


def _containers():
    """Every distinct DOS saved game the archives hold, by shape key.

    By *shape*, not by title: Treasures of the Savage Frontier writes the same
    1364-byte container Pools of Darkness does, so on this machine its two
    files land in the Pools of Darkness bucket and the assertions below hold
    for them too.  That is a fact about the format rather than a slip -- see
    `save_shape_for`.
    """
    from tools import dossavgam
    found = dossavgam.containers()
    if not found:
        pytest.skip("needs the DOS archives; set FR_ARCHIVES")
    out = {}
    for path in found:
        data = path.read_bytes()
        out.setdefault(sg.save_shape_for(len(data)).key, []).append(
            (path, data))
    return out


def _of(key):
    found = _containers().get(key)
    if not found:
        pytest.skip(f"no DOS {key} saved game here; set FR_ARCHIVES")
    return found


_ALL_SHAPES = pytest.mark.parametrize(
    "key", [s.key for s in sg.SAVE_SHAPES])


def test_a_shape_whose_widths_do_not_add_up_is_refused_at_import():
    """The check that makes a fifth title cheap to try: a region declared too
    wide moves every one after it, and the shape raises rather than reading
    somebody else's bytes.

    Asserting that the *existing* shapes tile was not this check and could
    not fail until #253: `square` was computed backwards from `size`, so
    `party_table + entries + scratch == size` reduced to `size == size` for
    any widths at all.  It is computed forwards now, which makes that a real
    assertion -- see the test below.  Building a wrong shape is still what
    exercises this guard.
    """
    good = dict(key="fifth", title="A Fifth Title",
                size=sg.SAVGAM_SIZE, script_bytes=0, unnamed=0)
    # The real Pool of Radiance widths less its script buffer: too narrow now.
    with pytest.raises(sg.DosSaveError) as raised:
        sg.DosSaveShape(**good)
    assert "add up to" in str(raised.value)
    assert str(sg.SAVGAM_SIZE) in str(raised.value)

    # And the same shape with the missing width put back is accepted.
    width = sg.ECL_BUFFER[1] - sg.ECL_BUFFER[0]
    assert sg.DosSaveShape(**{**good, "script_bytes": width}).size == sg.SAVGAM_SIZE


def test_every_shape_reaches_its_own_end_from_the_front():
    """`square` is measured forwards from the file's start and the character
    table is measured backwards from its end, so the two arithmetics meeting
    is a real check rather than an identity (#253).

    It is what would have caught #220's twelve-byte shift had `square` been
    computed this way then: putting the twelve in front of the block moves
    `party_table` and the count byte off the end of the character table, and
    the shipped containers stop naming six files.
    """
    for shape in sg.SAVE_SHAPES:
        assert (shape.party_table + sg.PARTY_ENTRIES * sg.PARTY_ENTRY
                + sg.UI_SCRATCH) == shape.size, shape.key
        assert shape.square + shape.unnamed + shape.square_bytes == \
            shape.party_table, shape.key
        if shape.script_buffer:
            assert shape.script_buffer[1] == shape.square, shape.key


def test_no_two_shapes_collide_on_the_size_that_selects_them():
    """`save_shape_for` picks a title by the file's size, so two titles of the
    same size would make one of them unreachable."""
    assert len(sg.SAVE_SHAPES_BY_SIZE) == len(sg.SAVE_SHAPES)


def test_the_pool_of_radiance_shape_is_the_offsets_the_module_was_built_on():
    """The generator must reproduce the hand-measured constants exactly.
    Without this the other three shapes would be free to drift the one that
    twelve engine-written specimens stand behind."""
    shape = sg.SAVE_POOL_OF_RADIANCE
    assert shape.size == sg.SAVGAM_SIZE
    assert shape.var_offset == sg.VAR_OFFSET
    assert shape.var_words == sg.VAR_WORDS
    assert shape.script_buffer == sg.ECL_BUFFER
    assert shape.square == sg.POS_X
    assert shape.pos_x == sg.POS_X
    assert shape.pos_y == sg.POS_Y
    assert shape.pos_facing == sg.POS_FACING
    assert shape.party_table == sg.PARTY_TABLE


@_ALL_SHAPES
def test_every_container_names_six_character_files(key):
    """The party table is the anchor the whole per-title map was measured
    backwards from: six length-prefixed `CHRDAT<letter><n>` names, 41 bytes
    apart, ending 82 bytes before the end of the file. A shape whose head
    region is one byte out finds five names, or none."""
    for path, data in _of(key):
        names = sg.character_files(data, sg.save_shape_for(key))
        assert len(names) == sg.PARTY_ENTRIES, path
        slot = path.name[len("SAVGAM")]
        assert names == [f"CHRDAT{slot}{n + 1}" for n in
                         range(sg.PARTY_ENTRIES)], path


@_ALL_SHAPES
def test_the_party_size_byte_is_the_last_of_the_square_block(key):
    """Six in every shipped container of every title, which is what says the
    square block sits immediately before the party table in each of them."""
    for path, data in _of(key):
        assert sg.party_size(data, sg.save_shape_for(key)) == 6, path


@_ALL_SHAPES
def test_a_shipped_container_reads_a_square_and_not_three_empty_markers(key):
    """A facing is 0, 2, 4 or 6 and a square is on a grid, so a reader that
    has slipped is visible without knowing where the party actually stood.

    Curse and Silver Blades read (255, 255, 254) here until #253, which was
    this reader landing on the wallset triple's `$FFFF` empty markers twelve
    bytes past the square. These containers are a download with no chain of
    custody (`.claude/rules/testing.md`) and that does not weaken the check:
    a character editor changes what a field holds and never where the engine
    puts it, and 255 is not a value the writer can produce for any of three.
    """
    for path, data in _of(key):
        shape = sg.save_shape_for(key)
        assert data[shape.pos_facing] % sg.FACING_SCALE == 0, path
        x, y, facing = sg.position(data, shape)
        assert 0 <= facing <= 3, path
        assert 0 <= x < 32 and 0 <= y < 32, path


@pytest.mark.parametrize("key", ["pool-of-radiance", "curse-of-the-azure-bonds",
                                 "secret-of-the-silver-blades"])
def test_the_container_number_is_also_a_variable(key):
    """`$5012` equals byte 0 in all nine containers of the three titles that
    have both -- 3/4/2/2/3 across the five Pool of Radiance ones, 2/2 in
    Curse, 1/1 in Silver Blades. Two independent readings of the same fact
    3620 bytes apart, so a variable array at the wrong offset in Curse or
    Silver Blades could not agree with the header byte by accident."""
    shape = sg.save_shape_for(key)
    for path, data in _of(key):
        assert sg.word(data, sg.DISK, shape) == sg.dax_number(data, shape), \
            path


@pytest.mark.parametrize("key", ["pool-of-radiance", "curse-of-the-azure-bonds",
                                 "secret-of-the-silver-blades"])
def test_the_party_size_is_also_a_variable(key):
    """`$503E` and the square block's last byte hold the same count. The
    second anchor for the shared variable array, 1602 words from the first."""
    shape = sg.save_shape_for(key)
    for path, data in _of(key):
        assert sg.word(data, sg.PARTY_SIZE, shape) == \
            sg.party_size(data, shape), path


def test_pools_of_darkness_has_no_word_variable_array_to_read():
    """It has the *other* array -- 1024 one-byte variables from file offset 0
    (#175) -- so a caller that reaches for `$5012` or `$503E` is reaching for
    a word that does not exist here, and gets a refusal rather than two bytes
    out of the byte array."""
    shape = sg.save_shape_for("pools-of-darkness")
    assert shape.var_offset is None
    assert shape.script_buffer is None
    assert shape.var_bytes == sg.POD_VAR_COUNT
    for _, data in _of("pools-of-darkness"):
        with pytest.raises(sg.DosSaveError):
            sg.word(data, sg.PARTY_SIZE, shape)
        with pytest.raises(sg.DosSaveError):
            sg.dax_number(data, shape)


def test_silver_blades_stages_no_script_and_its_scripts_are_no_smaller():
    """The reason a Silver Blades save is less than half a Pool of Radiance
    one is the missing 7680-byte script buffer, and it is not that its
    scripts are small: its largest `ECL<n>.DAX` block is within two bytes of
    Pool of Radiance's. So the engine reloads the script from the container
    rather than carrying it, which is the one thing moving a Pool of Radiance
    save to another area needs the player's own game files for."""
    assert sg.SAVE_SECRET_OF_THE_SILVER_BLADES.script_buffer is None
    assert sg.SAVE_CURSE_OF_THE_AZURE_BONDS.script_buffer == sg.ECL_BUFFER
    assert (sg.SAVE_POOL_OF_RADIANCE.size
            - sg.SAVE_SECRET_OF_THE_SILVER_BLADES.size
            == sg.ECL_BUFFER[1] - sg.ECL_BUFFER[0] - 12)


def test_a_container_of_an_unknown_length_is_refused():
    """A file that is none of the four sizes names no shape, and guessing is
    how a reader hands back a party that is not there."""
    with pytest.raises(sg.DosSaveError):
        sg.save_shape_for(9999)
    with pytest.raises(sg.DosSaveError):
        sg.character_files(bytes(9999))


# --- Pools of Darkness: the byte-wide variable array (#175) -------------------
#
# The first three titles write 2560 `u16le` ECL variables from `$4900`; this
# one writes 1024 of them one byte wide from file offset 0, variable *N* at
# offset *N* - 1. Everything above indexes the word array, so nothing above
# covers a single line of this. The offsets came out of the writer in
# `GAME.OVR` and are checked here against the containers on this machine.


def pty() -> bytearray:
    """A well-formed empty Pools of Darkness container."""
    return bytearray(sg.SAVE_POOLS_OF_DARKNESS.size)


def test_a_byte_variable_is_its_index_less_one_at_both_ends():
    """`GetVar` decrements the index before adding it to the block base, so
    variable 1 is offset 0 and variable 1024 is offset 1023. Tested at the
    edges rather than the middle: an off-by-one here reads the neighbouring
    variable and hands back a plausible number."""
    assert sg.pod_var_offset(sg.POD_VAR_FIRST) == 0
    assert sg.pod_var_offset(sg.POD_VAR_COUNT) == sg.POD_VAR_COUNT - 1
    for outside in (0, -1, sg.POD_VAR_COUNT + 1):
        with pytest.raises(sg.DosSaveError):
            sg.pod_var_offset(outside)


def test_the_byte_array_is_refused_on_a_title_that_has_no_such_thing():
    """Offset `index - 1` in a Pool of Radiance save is the low byte of
    somebody else's word, so answering there would be a lie rather than an
    error."""
    for key in ("pool-of-radiance", "curse-of-the-azure-bonds",
                "secret-of-the-silver-blades"):
        shape = sg.save_shape_for(key)
        assert shape.var_bytes == 0
        with pytest.raises(sg.DosSaveError):
            sg.pod_var_offset(sg.POD_IN_DUNGEON, shape)
    with pytest.raises(sg.DosSaveError):
        sg.pod_var(bytes(sg.SAVGAM_SIZE), sg.POD_IN_DUNGEON)


def test_a_byte_variable_goes_back_the_way_it_came():
    save = pty()
    sg.put_pod_var(save, sg.POD_PARTY_COUNT, 5)
    assert sg.pod_var(bytes(save), sg.POD_PARTY_COUNT) == 5
    assert save[sg.POD_PARTY_COUNT - 1] == 5
    assert sum(save[:sg.POD_VAR_COUNT]) == 5   # and nothing else moved


def test_the_clock_is_seven_digits_with_the_minutes_two_wide():
    """Seven digits at file 4-10 -- one more than Pool of Radiance's six --
    and the minutes are tens above units at file 6 and 5, which is the same
    arithmetic `clock` does over words."""
    save = pty()
    for i, digit in enumerate((9, 3, 5, 21, 17, 11, 42)):
        sg.put_pod_var(save, sg.POD_CLOCK + i, digit)
    assert sg.pod_clock(bytes(save)) == (21, 53, 17, 11, 42)
    assert save[4:11] == bytes((9, 3, 5, 21, 17, 11, 42))


def test_every_clock_digit_has_a_radix_and_the_first_six_are_pool_of_radiances():
    """The seventh radix is the new one: 100, and its overflow is what ages
    every character by a year."""
    assert len(sg.POD_CLOCK_RADIX) == sg.POD_CLOCK_DIGITS
    assert sg.POD_CLOCK_RADIX[:6] == (10, 10, 6, 24, 30, 12)


def test_the_pools_of_darkness_square_block_is_twelve_bytes():
    """It was read as four unnamed bytes and then an eight-byte block until
    #175, which put the square three bytes past where it is. The widths still
    tile the file either way -- that is what makes the error survivable and
    is why the tiling check alone cannot catch it."""
    shape = sg.save_shape_for("pools-of-darkness")
    assert shape.square_bytes == 12
    assert (shape.pos_x, shape.pos_y, shape.pos_facing) == (1024, 1025, 1026)
    assert shape.unnamed == 0
    assert (sg.POD_PREVIOUS_MODE, sg.POD_MODE) == (1029, 1030)
    assert (sg.POD_MAP, sg.POD_MAP_BLOCK) == (1031, 1033)
    assert shape.party_table - 1 == 1035          # the count of names


def test_the_character_table_is_eight_slots_in_every_title():
    """8 x 41 = 328 = six entries plus the 82 bytes this module called UI
    scratch, so no offset moves; what changed in #175 is what the 82 are.

    The second reading is not a guess: Pools of Darkness' own loader seeks to
    5140 in a Silver Blades container and reads 0x148 = 328 bytes there, and
    5140 is that shape's count byte to the byte."""
    assert sg.NAME_SLOTS * sg.PARTY_ENTRY == (sg.PARTY_ENTRIES * sg.PARTY_ENTRY
                                              + sg.UI_SCRATCH)
    silver = sg.save_shape_for("secret-of-the-silver-blades")
    assert silver.party_table - 1 == 5140
    for shape in sg.SAVE_SHAPES:
        assert shape.size - shape.party_table == sg.NAME_SLOTS * sg.PARTY_ENTRY


# --- and against the containers on this machine ------------------------------


def _darkness_only():
    """The shipped Pools of Darkness containers, without the Savage Frontier
    ones that share their size.

    The trap #175 names: a sweep that filters on 1364 bytes finds **four**
    files under two slot letters and calls two titles' specimens one title's.
    Only the directory says which game wrote a file, so that is what is
    filtered on.
    """
    found = [(path, data) for path, data in _of("pools-of-darkness")
             if "Pools of Darkness" in str(path)]
    if not found:
        pytest.skip("no shipped Pools of Darkness container here")
    return found


def test_the_two_titles_that_share_this_shape_are_not_the_same_specimen():
    """Filtering on size alone doubles the apparent corpus. The containers
    differ, so the filter is checkable rather than a matter of taste."""
    darkness = {data for _, data in _darkness_only()}
    others = {data for path, data in _of("pools-of-darkness")
              if "Pools of Darkness" not in str(path)}
    if not others:
        pytest.skip("only one title of this shape is on this machine")
    assert darkness.isdisjoint(others)


def test_the_new_game_initialiser_accounts_for_every_byte_of_the_array():
    """`FillChar(block, 1024, 0)` and then six assignments is the whole of
    what a shipped container holds -- offsets 17, 31, 33, 38 and 56, which
    are variables 18, 32, 34, 39 and 57.

    So the containers are not merely unplayed; they are the initialiser's
    output, and that is why no amount of reading them names a field."""
    initialised = {17: 4, 31: 6, 33: 1, 38: 3, 56: 10}
    for path, data in _darkness_only():
        nonzero = {i: data[i] for i in range(sg.POD_VAR_COUNT) if data[i]}
        assert nonzero == initialised, path


def test_a_shipped_container_reads_as_a_party_of_six_in_a_dungeon():
    for path, data in _darkness_only():
        assert sg.pod_var(data, sg.POD_PARTY_COUNT) == 6, path
        assert sg.pod_var(data, sg.POD_PARTY_COUNT) == sg.party_size(data), path
        assert sg.pod_in_dungeon(data), path
        assert sg.pod_clock(data) == (0, 0, 0, 0, 0), path
        assert data[sg.POD_PREVIOUS_MODE] == sg.POD_MODE_DUNGEON, path


# --- the engine-written containers, if a drive has left any ------------------
#
# `tools/dospod.py` drives the game and snapshots its `SAVE` directory into
# `work/p175/`, which is gitignored: these run where a drive has been done and
# skip everywhere else, CI included. What stands behind the offsets without
# them is the writer in `GAME.OVR`, and #175's comment carries the byte tables
# these assertions were read off so they can be re-taken after `work/` is
# cleared.


def _played():
    """Every distinct engine-written Pools of Darkness container under
    `work/p175`, which is where `tools/dospod.py` leaves them.

    A file byte-identical to a shipped container is one `Session.stage`
    copied in rather than one the engine wrote, so it is dropped: counting it
    would put the initialiser's own output in a corpus of played saves.

    That makes this need the archives as well as the drive output, which is
    not a real limitation -- the drive stages the game out of the archives, so
    a machine with `work/p175` and no archives is a machine where somebody
    deleted them afterwards.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "work" / "p175"
    if not root.is_dir():
        pytest.skip("no Pools of Darkness drive here; run tools/dospod.py")
    shipped = {data for _, data in _of("pools-of-darkness")}
    out = {}
    for path in sorted(root.rglob("*.PTY")):
        data = path.read_bytes()
        if len(data) != sg.SAVE_POOLS_OF_DARKNESS.size or data in shipped:
            continue
        out.setdefault(data, path)
    if not out:
        pytest.skip("work/p175 holds no engine-written container")
    return [(path, data) for data, path in out.items()]


def test_every_played_container_reads_as_a_six_strong_party_in_a_dungeon():
    """Eight distinct containers on this machine when #175 was written. The
    party size agrees in both places it is carried -- variable 32 and the
    count byte the writer emits after the loop -- which is what says the
    twelve-byte block ends where this module puts it."""
    played = _played()
    for path, data in played:
        assert sg.pod_var(data, sg.POD_PARTY_COUNT) == 6, path
        assert sg.party_size(data) == 6, path
        assert sg.pod_in_dungeon(data), path
        assert len(sg.character_files(data)) == sg.PARTY_ENTRIES, path
    assert len(played) >= 1


def test_a_played_square_is_on_the_grid_and_the_facing_is_doubled():
    """The facing is stored doubled -- 0 N, 2 E, 4 S, 6 W -- so an odd byte
    there would mean the square block had slipped. Read against the game's
    own status line, `11,2 S 00:04` and `8,2 W 00:07`."""
    for path, data in _played():
        x, y, facing = sg.position(data)
        assert data[sg.SAVE_POOLS_OF_DARKNESS.pos_facing] % sg.FACING_SCALE == 0, path
        assert 0 <= facing <= 3, path
        assert 0 <= x < 16 and 0 <= y < 16, path


def test_a_played_clock_is_a_time_and_not_seven_arbitrary_bytes():
    """Every digit under its own radix. A block read one byte out would put
    the party-count byte or a script variable in the clock, and those go
    past 24 and 30 as digits never do."""
    for path, data in _played():
        digits = [sg.pod_var(data, sg.POD_CLOCK + i)
                  for i in range(sg.POD_CLOCK_DIGITS)]
        for digit, radix in zip(digits, sg.POD_CLOCK_RADIX):
            assert 0 <= digit < radix, (path, digits)


# --- the area, and the map it runs on (#257) --------------------------------

#: The two engine-written Pool of Radiance saves made inside the training
#: hall, and the one made on the street outside it as a control.  All three
#: were written by the game's own SAVE CURRENT GAME in `#249`'s driven runs.
#: The two hall saves are flagged EDITED because experience and gold were
#: poked into their **character records** before the run and the square into
#: bytes 12801-12803; `tools/dostrain.py` writes no VM variable at all, so
#: the two words this section is about are the engine's.
HALL_SPECIMENS = (("por-party-trained-c2", "F"), ("por-train-clamp", "F"))
STREET_SPECIMEN = ("por-party-l1-intown", "E")


def _savgam(name: str, slot: str) -> bytes:
    from gamedata import specimen
    return (specimen(name) / f"SAVGAM{slot}.DAT").read_bytes()


def _ecl_container(n: int) -> bytes:
    """`ECL<n>.DAX` out of the player's own DOS game directory.

    Read, never written, and never copied into the repository. Skips where
    the archives are not on this machine, which is what CI does.
    """
    from tools import dosbox

    try:
        return (dosbox.find_game("POOLRAD") / f"ECL{n}.DAX").read_bytes()
    except (FileNotFoundError, OSError) as e:
        pytest.skip(f"needs the DOS game files: {e}")


def test_a_save_made_in_the_training_hall_reads_area_eleven():
    """The regression `#257 (A DOS save made in the training hall converts as
    though the party were in New Phlan)` is about.

    `current_area` read `$49C5` indoors, on the belief that the two words
    always agree there. They do not: area 11 has no map of its own -- there
    is no `LOADFILES` anywhere in `ECL0B` -- so it runs on New Phlan's
    `GEO00`, `$49C5` stays 0 and only `$49F2` says where the party is. A
    conversion keyed on `$49C5` puts them in New Phlan.

    Two of two hall specimens, against a street save from the same party as
    the control.
    """
    for name, slot in HALL_SPECIMENS:
        save = _savgam(name, slot)
        assert sg.outdoors(save) is False, name
        assert sg.geo_block(save) == 0, name          # New Phlan's GEO00
        assert sg.current_area(save) == 11, name      # the training hall
    street = _savgam(*STREET_SPECIMEN)
    assert sg.geo_block(street) == sg.current_area(street) == 0


def test_the_hall_saves_carry_the_hall_script_and_the_street_save_does_not():
    """What makes 11 the party's area rather than a stray word: the ECL text
    buffer is a verbatim copy of the running script, and in the two hall
    saves it is area 11's block byte for byte.

    Read against `ECL3.DAX` off the player's own DOS files, which carries
    blocks 0, 8, 11 and 14 -- so the same container answers for the control.
    """
    dax = _ecl_container(3)
    start, end = sg.ECL_BUFFER
    for name, slot, block in [(n, s, 11) for n, s in HALL_SPECIMENS] + \
            [(STREET_SPECIMEN[0], STREET_SPECIMEN[1], 0)]:
        body = sg.dax_block(dax, block)[sg.ECL_HEADER:]
        buffer = _savgam(name, slot)[start:end]
        assert buffer[:len(body)] == body, name
        assert set(buffer[len(body):]) <= {0}, name
