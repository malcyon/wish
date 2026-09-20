"""The Amiga Pools of Darkness saved game, against the routine that writes it.

`tools/amiga/podsavegame.py` reads `Save/SavGam<L>.pty` through the map
`/Pools of Darkness`'s own save and load callbacks lay out, and this is its
proof.

What is tested, hardest evidence first.

* **Every byte is accounted for.** A slot parses, rebuilds byte for byte and
  is 10,828 bytes, with the party region walked by the file's own counts --
  the party count word, each record's item count, each effect node's own
  `next` -- rather than by a table of widths. A wrong stride puts a name in
  the wrong place, so a parse that lands every name in printable ASCII is
  evidence for the walk.
* **The count word agrees with the variable array**, which is two independent
  regions of the file saying the same number.
* **The square block is DOS's, in DOS's order**, checked against
  `goldbox.dos_savegame`'s own Pools of Darkness offsets rather than restated
  here: the Amiga's struct is one byte longer and everything after it shifts
  by one, and the party count is a word where DOS keeps a byte.
* **The strides discriminate.** DOS's own widths -- a five-byte square struct,
  a one-byte count -- are tried against the same files and fail, so the checks
  above are not true of any reading.
* **The engine's own variable census**, read out of the executable, against
  the range `tools/dos/dosptrfields.py` found in `GAME.OVR`.

**The specimens are the `Save/SavGam*.pty` files on the player's own Amiga
disk images**, read at run time through `gamedisks.yaml`'s `amiga` entry.
Everything that needs them skips without them, which is what CI does. The
synthetic container is built here from the documented format and is nobody's
game data.
"""
from __future__ import annotations

import struct

import pytest

from goldbox import dos_savegame
from tools.amiga import podsavegame

POD = dos_savegame.SAVE_POOLS_OF_DARKNESS


def slots() -> list[tuple[str, bytes]]:
    """Every distinct saved game on the disks, skipping when there are none."""
    found = podsavegame.slots()
    if not found:
        pytest.skip("no Amiga Pools of Darkness saved game; set $AMIGA_DISKS")
    return [(f"{name}#{i}" if i else name, blob)
            for name, copies in found.items()
            for i, (_label, blob) in enumerate(copies)]


def build(characters=((2, 0, 0),), square=(3, 4, 2, 5, 137, 0),
          previous_mode=4, mode=2, dungeon_map=6, map_block=0,
          variables=None, pad=b"\xA5") -> bytes:
    """A well-formed container, from the format rather than from a game file.

    `characters` is one `(items, bundled, effects)` per character. Every
    record byte but the two the loader reads -- the item count and the effect
    head -- is filler, and the name is written so a mis-strided parse shows up
    as a name that is not there.
    """
    out = bytearray(podsavegame.VAR_BYTES)
    for index, value in (variables or {}).items():
        out[index - 1] = value
    out += bytes(square) + bytes((previous_mode, mode))
    out += struct.pack(">HHH", dungeon_map, map_block, len(characters))
    for number, (items, bundled, effects) in enumerate(characters):
        record = bytearray(b"\x5A" * podsavegame.RECORD_BYTES)
        struct.pack_into(">I", record, podsavegame.ITEM_COUNT_AT, items)
        struct.pack_into(">I", record, podsavegame.EFFECT_HEAD_AT,
                         0x1234 if effects else 0)
        name = f"WHO{number}".encode()
        record[podsavegame.NAME_AT:podsavegame.NAME_AT + len(name) + 1] = \
            name + b"\x00"
        out += record
        left = bundled
        for item in range(items):
            node = bytearray(b"\x11" * podsavegame.ITEM_BYTES)
            if left and item == 0:
                node[0] = podsavegame.BUNDLE_ID
                node[podsavegame.BUNDLE_COUNT] = left
                out += node + b"\x22" * podsavegame.ITEM_BYTES * left
                left = 0
                continue
            out += node
        for effect in range(effects):
            node = bytearray(b"\x33" * podsavegame.EFFECT_BYTES)
            last = effect == effects - 1
            struct.pack_into(">I", node, podsavegame.EFFECT_NEXT_AT,
                             0 if last else 0x5678)
            out += node
    short = podsavegame.SAVEGAME_SIZE - len(out)
    assert short >= 0, "the synthetic party does not fit the fixed size"
    return bytes(out) + (pad * short)


# ---------------------------------------------------------------------------
# The synthetic container, which needs no disks
# ---------------------------------------------------------------------------
def test_a_container_built_from_the_format_round_trips():
    data = build(characters=((3, 0, 2), (0, 0, 0), (1, 4, 1)))
    save = podsavegame.parse(data)
    assert save.count == 3
    assert [c.name for c in save.characters] == ["WHO0", "WHO1", "WHO2"]
    assert [(c.items, c.bundled, c.effects) for c in save.characters] == [
        (3, 0, 2), (0, 0, 0), (1, 4, 1)]
    assert podsavegame.rebuild(save) == data
    assert len(data) == podsavegame.SAVEGAME_SIZE


def test_the_square_and_the_modes_are_read_where_the_writer_puts_them():
    save = podsavegame.parse(build(square=(9, 1, 6, 12, 200, 0),
                                   previous_mode=3, mode=2,
                                   dungeon_map=17, map_block=2))
    assert save.square == {"x": 9, "y": 1, "facing": 6, "wall_ahead": 12,
                           "square_property": 200, "pad": 0}
    assert (save.previous_mode, save.mode) == (3, 2)
    assert (save.dungeon_map, save.map_block) == (17, 2)


def test_a_variable_is_read_by_its_dos_number():
    save = podsavegame.parse(build(variables={
        dos_savegame.POD_PARTY_COUNT: 6, dos_savegame.POD_IN_DUNGEON: 1,
        dos_savegame.POD_CLOCK: 0}))
    assert save.var(dos_savegame.POD_PARTY_COUNT) == 6
    assert save.var(dos_savegame.POD_IN_DUNGEON) == 1
    assert save.data[dos_savegame.POD_PARTY_COUNT - 1] == 6


def test_a_party_count_the_engine_would_not_write_is_refused():
    data = bytearray(build())
    struct.pack_into(">H", data, podsavegame.COUNT_AT,
                     podsavegame.PARTY_MAX + 1)
    with pytest.raises(podsavegame.PodSaveError):
        podsavegame.parse(bytes(data))


@pytest.mark.parametrize("count", [0, podsavegame.PARTY_MAX + 1])
def test_a_party_count_outside_one_to_eight_is_refused_even_when_the_records_are_there(count):
    """Nine well-formed records must be refused for their count and not for
    the filler a one-character buffer would leave where they should be."""
    data = bytearray(build(characters=((0, 0, 0),) * 9))
    struct.pack_into(">H", data, podsavegame.COUNT_AT, count)
    with pytest.raises(podsavegame.PodSaveError, match="party count"):
        podsavegame.parse(bytes(data))


def test_a_buffer_shorter_than_the_header_is_refused_for_its_length():
    with pytest.raises(podsavegame.PodSaveError, match="shorter than the header"):
        podsavegame.parse(bytes(podsavegame.PARTY_AT - 1))


def test_a_bundle_whose_count_overshoots_the_buffer_is_refused():
    """The bundle's sub-items are skipped by count, not read, so nothing
    slices past the end: only the final position check sees the overshoot."""
    data = build(characters=((1, 1, 0),))
    node = podsavegame.PARTY_AT + podsavegame.RECORD_BYTES
    cut = bytearray(data[:node + podsavegame.ITEM_BYTES])
    cut[node] = podsavegame.BUNDLE_ID
    cut[node + podsavegame.BUNDLE_COUNT] = 0xFF
    with pytest.raises(podsavegame.PodSaveError, match="the party ends at"):
        podsavegame.parse(bytes(cut))


def test_an_effect_chain_that_never_ends_runs_off_the_file():
    """The chain is the file's own `next` longs, so a broken one is caught."""
    data = bytearray(build(characters=((0, 0, 1),)))
    at = podsavegame.PARTY_AT + podsavegame.RECORD_BYTES
    struct.pack_into(">I", data, at + podsavegame.EFFECT_NEXT_AT, 0x99)
    # Fill the rest with a chain that keeps saying "one more".
    for off in range(at + podsavegame.EFFECT_BYTES,
                     len(data) - podsavegame.EFFECT_BYTES,
                     podsavegame.EFFECT_BYTES):
        struct.pack_into(">I", data, off + podsavegame.EFFECT_NEXT_AT, 0x99)
    with pytest.raises(podsavegame.PodSaveError):
        podsavegame.parse(bytes(data))


# ---------------------------------------------------------------------------
# The Amiga's own layout against DOS's, which needs no disks either
# ---------------------------------------------------------------------------
def test_the_variable_array_is_the_same_array_dos_writes():
    assert podsavegame.VAR_BYTES == POD.var_bytes == 1024
    assert podsavegame.SQUARE_AT == POD.square == 1024


def test_the_square_block_is_dos_field_order_with_one_more_byte():
    """DOS's twelve bytes, in the same order, with a pad DOS does not write.

    So every offset after the struct is DOS's plus one, and the party count
    is a `u16be` where DOS keeps a byte -- which is the whole of the
    difference between a 1364-byte DOS container and this one's tail.
    """
    assert (POD.pos_x, POD.pos_y, POD.pos_facing) == (1024, 1025, 1026)
    assert podsavegame.SQUARE[:3] == ("x", "y", "facing")
    # DOS's struct runs from the square to the previous-mode byte: five
    # bytes. The Amiga's is those five and one pad.
    assert dos_savegame.POD_PREVIOUS_MODE - POD.square == 5
    assert len(podsavegame.SQUARE) == 5 + 1
    assert podsavegame.SQUARE[-1] == "pad"
    assert podsavegame.PREVIOUS_MODE_AT == dos_savegame.POD_PREVIOUS_MODE + 1
    assert podsavegame.MODE_AT == dos_savegame.POD_MODE + 1
    assert podsavegame.MAP_AT == dos_savegame.POD_MAP + 1
    assert podsavegame.MAP_BLOCK_AT == dos_savegame.POD_MAP_BLOCK + 1
    assert podsavegame.COUNT_AT == POD.party_size_byte + 1


def test_the_vault_is_two_hundred_item_slots():
    assert podsavegame.VAULT_SIZE == 4016


# ---------------------------------------------------------------------------
# The player's own disks
# ---------------------------------------------------------------------------
def test_every_saved_game_on_the_disks_parses_and_round_trips():
    found = slots()
    for name, blob in found:
        save = podsavegame.parse(blob)
        assert len(blob) == podsavegame.SAVEGAME_SIZE, name
        assert podsavegame.rebuild(save) == blob, name
        assert save.end <= len(blob), name
    assert len(found) >= 8, "eight slots ship in disk 3's Save drawer"


def test_every_character_block_lands_on_a_printable_name():
    for name, blob in slots():
        save = podsavegame.parse(blob)
        for character in save.characters:
            assert character.name, f"{name}: an empty name at {character.at}"
            assert character.name.isprintable(), f"{name}: {character.name!r}"
            assert character.items <= 16, name


def test_the_count_word_agrees_with_the_party_count_variable():
    for name, blob in slots():
        save = podsavegame.parse(blob)
        assert save.count == save.var(dos_savegame.POD_PARTY_COUNT), name


def test_the_clock_is_legal_against_the_radices_dos_reads():
    for name, blob in slots():
        save = podsavegame.parse(blob)
        assert save.clock_legal, f"{name}: {save.clock}"


def test_the_mode_byte_is_camp_or_the_value_a_load_leaves():
    """2 in every save the game made, and 0 in a party never taken into the
    world -- the same pair `docs/165-amiga-savegame.md` reads on Curse and
    Silver Blades."""
    modes = {}
    for name, blob in slots():
        modes[name] = podsavegame.parse(blob).mode
    assert set(modes.values()) <= {0, 2}, modes
    assert 2 in modes.values(), modes


def test_the_previous_mode_tracks_the_in_dungeon_variable():
    """3 wilderness, 4 dungeon -- `goldbox.dos_savegame`'s own enumeration,
    against a variable in a different region of the same file."""
    seen = []
    for name, blob in slots():
        save = podsavegame.parse(blob)
        if save.mode == 0:            # never entered the world
            continue
        want = (dos_savegame.POD_MODE_DUNGEON
                if save.var(dos_savegame.POD_IN_DUNGEON)
                else dos_savegame.POD_MODE_WILDERNESS)
        assert save.previous_mode == want, name
        seen.append(save.var(dos_savegame.POD_IN_DUNGEON))
    assert 0 in seen and 1 in seen, "both modes have to appear to mean this"


def test_the_unreferenced_square_byte_is_zero_in_every_one():
    for name, blob in slots():
        assert podsavegame.parse(blob).square["pad"] == 0, name


def dos_reads_a_party(blob: bytes) -> bool:
    """Whether DOS's own reading of the party finds one in `blob`.

    DOS keeps the party size in one byte at `party_size_byte` and its first
    party entry, a length byte then a `CHRDAT` name, at `party_table`. The
    Amiga's count is the word that starts at `party_table`, so DOS's length
    byte is that word's high half and DOS's count byte is the low half of the
    map-block word before it.
    """
    size = blob[POD.party_size_byte]
    length = blob[POD.party_table]
    return (1 <= size <= podsavegame.PARTY_MAX
            and 0 < length < dos_savegame.PARTY_NAME_LEN)


def test_dos_strides_do_not_read_these_files():
    """The discriminator: DOS's own offsets against the same bytes.

    The count byte and the first entry's length byte are read where DOS reads
    them, and the entry's is always 0 here because the Amiga's count is a word
    of at most 8. If a slot ever reads as a party under DOS's offsets, the
    checks above are true of any reading and prove nothing.
    """
    found = slots()
    assert not [name for name, blob in found if dos_reads_a_party(blob)]


def test_dos_offsets_do_not_read_a_synthetic_party_either():
    """Not only because the map-block word is 0: a map block of 3 puts a legal
    count in DOS's count byte, and the entry length still refuses it."""
    blob = build(map_block=3, characters=((0, 0, 0),) * 3)
    assert 1 <= blob[POD.party_size_byte] <= podsavegame.PARTY_MAX
    assert not dos_reads_a_party(blob)


def test_every_vault_is_the_size_its_own_writer_makes_it():
    found = podsavegame.vaults()
    if not found:
        pytest.skip("no Amiga Pools of Darkness Vault<L>.DAT; set $AMIGA_DISKS")
    total = 0
    for name, copies in found.items():
        for _label, blob in copies:
            total += 1
            assert len(blob) == podsavegame.VAULT_SIZE, name
            marker, count = struct.unpack_from(">HH", blob,
                                               podsavegame.VAULT_HEADER)
            assert marker == podsavegame.VAULT_MARKER, name
            assert count <= podsavegame.VAULT_ITEMS, f"{name}: {count}"
    assert total >= 8


# ---------------------------------------------------------------------------
# The executable's own census
# ---------------------------------------------------------------------------
def test_the_engine_names_the_same_variable_range_as_the_dos_build():
    pytest.importorskip("capstone")
    found = podsavegame.slots()
    if not found:
        pytest.skip("no Amiga Pools of Darkness disks; set $AMIGA_DISKS")
    sites = podsavegame.variable_sites(podsavegame.executable(quiet=True))
    low = [v for v in sites if v <= dos_savegame.POD_ENGINE_VARS]
    high = [v for v in sites if v > dos_savegame.POD_ENGINE_VARS]
    assert len(low) >= 45, sorted(low)
    assert max(low) == dos_savegame.POD_ENGINE_VARS
    # 198 is in DOS's own 196-198; 418 is this port's and nothing else is.
    assert set(high) == {198, 418}, sorted(high)
    assert sites[dos_savegame.POD_PARTY_COUNT]
    assert sites[dos_savegame.POD_IN_DUNGEON]
    assert sites[dos_savegame.POD_DUNGEON_MAP]
    assert sites[dos_savegame.POD_WILDERNESS_REGION]


# ---------------------------------------------------------------------------
# The container map lives in the library; this tool re-exports it
# ---------------------------------------------------------------------------
def test_the_tool_reads_through_the_librarys_container_map():
    from goldbox import amiga_savegame

    assert podsavegame.parse is amiga_savegame.pod_parse
    assert podsavegame.rebuild is amiga_savegame.pod_rebuild
    assert podsavegame.PodSaveError is amiga_savegame.PodSaveError
    assert podsavegame.SAVEGAME_SIZE == amiga_savegame.POD_SAVEGAME_SIZE == 0x2A4C
    assert (podsavegame.SQUARE_AT, podsavegame.PREVIOUS_MODE_AT,
            podsavegame.MODE_AT, podsavegame.MAP_AT,
            podsavegame.MAP_BLOCK_AT, podsavegame.COUNT_AT) == (
        1024, 1030, 1031, 1032, 1034, 1036)
    assert podsavegame.PARTY_AT == 1038
