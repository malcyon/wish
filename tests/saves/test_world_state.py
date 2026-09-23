"""`goldbox.world_state.WorldState`, the lift of `goldbox.amiga_savegame.PorSaveState`
into one shape every port's saved-game reader fills
(`#352 (Handle world state for Amiga saves)`).

`tests/amiga/test_amigaporsavegame.py` and `tests/convert/test_toamigapor.py` keep the
Amiga-specific coverage of the three `goldbox.amiga_savegame.por_state_from_*`
wrappers; what belongs here is the general reader itself -- that it agrees
with a title's own C64 and DOS specimens, and the five fields it added
against `PorSaveState`.
"""

from __future__ import annotations

import dataclasses
import pathlib
import struct

import gamedata
import pytest

from goldbox import areas, c64_port, c64_save, dos_codec, dos_savegame, world_state


def _c64_specimen(name: str) -> pathlib.Path:
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    found = sorted((root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs the C64 specimen WISH-SPEC-{name}")
    return found[0]


def _c64_state(name: str, game=None) -> world_state.WorldState:
    from goldbox.d64 import load_payload

    game = game or c64_port.POOL_OF_RADIANCE
    disk = _c64_specimen(name)
    payload = load_payload(str(disk), game.save_file)
    return world_state.from_c64(payload, game, str(disk))


def _dos_savgam(name: str, slot: str) -> bytes:
    where = gamedata.specimen(name)
    savgam = where / f"SAVGAM{slot}.DAT"
    if not savgam.is_file():
        pytest.skip(f"WISH-SPEC-{name} has no {savgam.name}")
    return savgam.read_bytes()


# ---------------------------------------------------------------------------
# The one twin pair this project has: a DOS save, and the C64 engine's own
# resave of the party this project's own converter built from it.
# ---------------------------------------------------------------------------

def test_from_c64_and_from_dos_agree_on_the_projects_one_twin_pair():
    """`WISH-SPEC-por-c64-hall-resave` is the C64 engine's own `ENCAMP >
    SAVE` of `WISH-SPEC-por-party-trained-c2` (DOS slot F), converted by
    this project's own `dos_codec.convert_save` and then loaded and resaved --
    `tests/convert/test_dosconversionarea.py` already cites the pair for `$49C5`
    and `$49F2` alone. `from_c64` and `from_dos` read both files
    independently and agree exactly on area, resident map, square, facing
    and all 217 quest flags.

    The clock does not agree to the digit: the C64 read holds one more
    minute-units digit than the DOS source (5 against 4), which is the
    boot-to-`ENCAMP`-menu time VICE spent between the disk being written and
    the player reaching `SAVE CURRENT GAME` -- a real minute passing, not a
    reader disagreement, so only the four digits time cannot move against
    are asserted exactly.

    The wallset, the per-script scratch and the header words are **not**
    asserted here: area 11 borrows New Phlan's `GEO00` and loads no
    `WALLSET` of its own (`goldbox.dos_codec.c64_wall_triple`'s own docstring),
    and the hall's script runs between the DOS save and the C64 resave, so
    those three are expected to differ and do.
    """
    c64_state = _c64_state("por-c64-hall-resave")
    dos_state = world_state.from_dos(
        _dos_savgam("por-party-trained-c2", "F"))

    assert c64_state.area == dos_state.area == 11
    assert c64_state.geo == dos_state.geo == 0
    assert (c64_state.x, c64_state.y, c64_state.facing) == \
        (dos_state.x, dos_state.y, dos_state.facing) == (5, 0, 3)
    assert c64_state.outdoors is dos_state.outdoors is False
    assert c64_state.set_out is dos_state.set_out is True
    assert c64_state.flags == dos_state.flags
    assert len(c64_state.flags) == len(dos_state.flags) == 217

    sub, c64_minute, minute_tens, hour, day, month = c64_state.clock
    dos_sub, dos_minute, dos_minute_tens, dos_hour, dos_day, dos_month = \
        dos_state.clock
    assert (hour, day, month) == (dos_hour, dos_day, dos_month)
    assert minute_tens == dos_minute_tens
    assert c64_minute - dos_minute in (0, 1)


# ---------------------------------------------------------------------------
# The five fields PorSaveState lacked
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("game,width", [
    (c64_port.CURSE_OF_THE_AZURE_BONDS, 224),
    (c64_port.SECRET_OF_THE_SILVER_BLADES, 224),
])
def test_the_flag_window_is_the_later_titles_own_wider_one(game, width):
    """`PorSaveState` always read Pool of Radiance's 217-byte window, which
    is 7 bytes short of Curse and Secret of the Silver Blades' own 224
    (`c64_save.Container.quest_flags`).  `from_c64` and `from_dos` both
    read the width from that table instead of assuming Pool of Radiance's.
    """
    name = ("curse-dual-classed" if game is c64_port.CURSE_OF_THE_AZURE_BONDS
            else "ssb-malachite-trained")
    state = _c64_state(name, game)
    assert len(state.flags) == width == \
        c64_save.container_for(game).quest_flags[1]


def test_from_dos_reads_the_same_wider_window_for_the_later_titles():
    savgam = _dos_savgam("curse-299-whole-engine-resave", "D")
    state = world_state.from_dos(savgam)
    assert state.title == "Curse of the Azure Bonds"
    assert len(state.flags) == 224


def test_the_later_titles_copied_header_words_are_read():
    """`+$E7`-`+$E9` and `+$FD`-`+$FE`: Pool of Radiance copies none of them,
    Curse of the Azure Bonds copies `+$E7`-`+$E8` and Secret of the Silver
    Blades all five (`c64_save.Container.copied`) -- read here regardless of
    title, so `header` is never a title-shaped lookup for a caller."""
    savgam = _dos_savgam("curse-299-whole-engine-resave", "D")
    state = world_state.from_dos(savgam)
    assert set(state.header) == set(world_state.HEADER_ADDRESSES)


def _fresh_savgam() -> bytes:
    """A party that has never pressed `BEGIN ADVENTURING`: the initialiser's
    own signature (`tests/convert/test_dosconvert.py`'s `_never_adventured_savgam`,
    not imported -- a test module's private helpers are not another's to
    depend on) -- area 0, map 0, `$49E6` = 0, an all-zero staged script."""
    savgam = bytearray(dos_savegame.SAVGAM_SIZE)
    dos_savegame.put_position(savgam, 15, 1, 3)
    return bytes(savgam)


def test_a_party_that_has_never_set_out_is_placed_at_the_start_of_the_story():
    """`set_out` is false and `area`/`x`/`y`/`facing` are already New Phlan's
    arrival square, `areas.STARTS`'s own answer -- not the initialiser's
    `15,1` the raw file happens to hold at the same offset by coincidence,
    and not a refusal (`#301`, `#326`)."""
    state = world_state.from_dos(_fresh_savgam())
    assert state.set_out is False
    assert state.area == 0
    assert (state.x, state.y, state.facing) == (15, 1, 3)
    assert state.outdoors is False


@pytest.mark.parametrize("title, area, set_out, expected", [
    (areas.CURSE_OF_THE_AZURE_BONDS, 0, False, True),
    (areas.SECRET_OF_THE_SILVER_BLADES, 0, False, True),
    (areas.CURSE_OF_THE_AZURE_BONDS, 0, True, False),
    (areas.CURSE_OF_THE_AZURE_BONDS, 1, False, True),
    (areas.POOL_OF_RADIANCE, 0, False, False),
])
def test_has_not_set_out_is_the_placeless_state_of_the_two_later_titles(
        title, area, set_out, expected):
    state = dataclasses.replace(world_state.from_dos(_fresh_savgam()),
                                title=title, area=area, set_out=set_out)
    assert world_state.has_not_set_out(state) is expected


def test_has_not_set_out_ignores_the_area_a_reader_substituted():
    """`from_dos` moves a Silver Blades party from the party menu to area 0x10,
    and `from_c64` leaves a Curse one at raw area 0; both are still parties
    that have not set out.  Pool of Radiance's and a later state are not."""
    shape = dos_savegame.SAVE_SECRET_OF_THE_SILVER_BLADES
    savgam = bytearray(shape.size)
    dos_savegame.put_word(savgam, dos_savegame.INDOORS, 1, shape)
    dos_savegame.put_position(savgam, 7, 13, 0, shape)
    state = world_state.from_dos(bytes(savgam), shape)
    assert state.area == 0x10
    assert world_state.has_not_set_out(state)

    assert not world_state.has_not_set_out(
        world_state.from_dos(_fresh_savgam()))
    assert not world_state.has_not_set_out(
        dataclasses.replace(state, set_out=True))


def test_a_party_standing_in_the_world_is_left_where_it_is():
    savgam = bytearray(dos_savegame.SAVGAM_SIZE)
    dos_savegame.put_word(savgam, dos_savegame.INDOORS, 1)
    dos_savegame.put_position(savgam, 3, 9, 2)
    dos_savegame.put_clock(savgam, (0, 8, 5, 16, 4, 2))
    start, _ = dos_savegame.SAVE_POOL_OF_RADIANCE.script_buffer
    savgam[start] = 0x01
    dos_savegame.put_word(savgam, dos_codec.LATER_BEGUN_WORD, 255)
    state = world_state.from_dos(bytes(savgam))
    assert state.set_out is True
    assert (state.x, state.y, state.facing) == (3, 9, 2)


# ---------------------------------------------------------------------------
# Pool's state compatibility alias is `WorldState`
# ---------------------------------------------------------------------------

def test_amiga_savegame_por_state_is_world_state():
    from goldbox import amiga_savegame

    assert amiga_savegame.PorSaveState is world_state.WorldState


# ---------------------------------------------------------------------------
# Pools of Darkness has its own state: a byte-wide array, not WorldState's words
# ---------------------------------------------------------------------------

def _synthetic_pod_save() -> bytearray:
    """A 1364-byte Pools of Darkness container built from the documented
    layout, with a distinct value in every field under test."""
    box = dos_savegame.SAVE_POOLS_OF_DARKNESS
    save = bytearray(box.size)
    for i in range(box.var_bytes):
        save[i] = (i * 7 + 3) & 0x7F
    for i, digit in enumerate((1, 2, 3, 4, 5, 6, 7)):
        dos_savegame.put_pod_var(save, dos_savegame.POD_CLOCK + i, digit, box)
    dos_savegame.put_pod_var(save, dos_savegame.POD_IN_DUNGEON, 1, box)
    dos_savegame.put_pod_var(save, dos_savegame.POD_WILDERNESS_X, 21, box)
    dos_savegame.put_pod_var(save, dos_savegame.POD_WILDERNESS_Y, 22, box)
    save[box.pos_x], save[box.pos_y], save[box.pos_facing] = 11, 2, 4
    save[box.tail_scratch], save[box.tail_scratch + 1] = 0x5A, 0x6B
    save[dos_savegame.POD_PREVIOUS_MODE] = 2
    save[dos_savegame.POD_MODE] = dos_savegame.POD_MODE_DUNGEON
    save[dos_savegame.POD_MAP:dos_savegame.POD_MAP + 2] = (0x34, 0x12)
    save[dos_savegame.POD_MAP_BLOCK:dos_savegame.POD_MAP_BLOCK + 2] = (0x78, 0x56)
    save[box.party_size_byte] = 6
    return save


def test_a_pools_of_darkness_dos_save_reads_as_its_own_state():
    save = _synthetic_pod_save()
    state = world_state.pod_from_dos(bytes(save), source="synthetic")
    assert isinstance(state, world_state.PodWorldState)
    assert state.title == "Pools of Darkness"
    assert state.variables == bytes(save[:1024])
    assert (state.x, state.y, state.facing) == (11, 2, 2)
    assert (state.wall_ahead, state.square_property) == (0x5A, 0x6B)
    assert (state.previous_mode, state.mode) == (2, dos_savegame.POD_MODE_DUNGEON)
    assert (state.dungeon_map, state.map_block) == (0x1234, 0x5678)
    assert state.count == 6 == save[1035]
    assert state.source == "synthetic"
    assert state.clock == (1, 2, 3, 4, 5, 6, 7)
    assert state.in_dungeon is True
    assert state.wilderness_square == (21, 22)
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.x = 0


def test_the_wilderness_square_is_read_whichever_way_in_dungeon_reads():
    box = dos_savegame.SAVE_POOLS_OF_DARKNESS
    save = _synthetic_pod_save()
    dos_savegame.put_pod_var(save, dos_savegame.POD_IN_DUNGEON, 0, box)
    state = world_state.pod_from_dos(bytes(save))
    assert state.in_dungeon is False
    assert state.wilderness_square == (21, 22)


def test_a_pools_of_darkness_state_takes_an_explicit_container():
    save = bytes(_synthetic_pod_save())
    box = dos_savegame.SAVE_POOLS_OF_DARKNESS
    assert (world_state.pod_from_dos(save, box)
            == world_state.pod_from_dos(save, box.key)
            == world_state.pod_from_dos(save))


def test_pod_from_dos_refuses_a_title_with_no_byte_array():
    with pytest.raises(dos_savegame.DosSaveError, match="no byte-wide"):
        world_state.pod_from_dos(bytes(dos_savegame.SAVGAM_SIZE),
                                 dos_savegame.SAVE_POOL_OF_RADIANCE)


def test_the_shared_world_state_still_refuses_a_pools_of_darkness_save():
    """`WorldState` has no home for a byte-wide array, and the refusal is
    correct: widening it to take this title is the wrong repair, and
    `pod_from_dos` is the reader for these files."""
    with pytest.raises(dos_savegame.DosSaveError,
                       match="holds no ECL variable array"):
        world_state.from_dos(bytes(_synthetic_pod_save()))


def test_the_shared_world_state_keeps_its_six_digit_clock():
    assert dos_savegame.CLOCK_DIGITS == 6
    assert "variables" not in {f.name for f in
                               dataclasses.fields(world_state.WorldState)}


# ---------------------------------------------------------------------------
# The Amiga container reads as the same state
# ---------------------------------------------------------------------------

def _amiga_pod_from_dos(dos: bytes) -> bytes:
    """The Amiga container holding the party a DOS `SAVGAM` holds.

    The regions are the same and in the same order.  The differences are the
    pad byte after the square struct, the two map words big-endian instead of
    little-endian, and a `u16be` count where DOS keeps a byte.  The party
    records are filler with no items and no effects, since the state reads
    none of them.
    """
    from goldbox import amiga_savegame as amiga

    box = dos_savegame.SAVE_POOLS_OF_DARKNESS
    count = dos[box.party_size_byte]
    out = bytearray(dos[:dos_savegame.POD_MAP])
    out.insert(dos_savegame.POD_PREVIOUS_MODE, 0)
    map_word = struct.unpack_from("<H", dos, dos_savegame.POD_MAP)[0]
    block_word = struct.unpack_from("<H", dos, dos_savegame.POD_MAP_BLOCK)[0]
    out += struct.pack(">HHH", map_word, block_word, count)
    out += bytes(amiga.POD_RECORD_BYTES) * count
    return bytes(out) + bytes(amiga.POD_SAVEGAME_SIZE - len(out))


def test_the_two_ports_read_a_synthetic_pools_of_darkness_party_the_same_way():
    from goldbox import amiga_savegame as amiga

    dos = bytes(_synthetic_pod_save())
    amiga_save = _amiga_pod_from_dos(dos)
    assert len(amiga_save) == amiga.POD_SAVEGAME_SIZE
    assert (amiga.pod_from_amiga(amiga_save)
            == world_state.pod_from_dos(dos))


def test_an_amiga_pools_of_darkness_state_halves_the_facing_and_reads_words_big_endian():
    from goldbox import amiga_savegame as amiga

    dos = bytes(_synthetic_pod_save())
    state = amiga.pod_from_amiga(_amiga_pod_from_dos(dos), "slot A")
    assert (state.x, state.y, state.facing) == (11, 2, 2)
    assert (state.dungeon_map, state.map_block) == (0x1234, 0x5678)
    assert state.count == 6
    assert state.source == "slot A"
    assert state.clock == (1, 2, 3, 4, 5, 6, 7)


def test_an_amiga_buffer_that_is_not_a_pools_of_darkness_save_is_refused():
    from goldbox import amiga_savegame as amiga

    with pytest.raises(amiga.PodSaveError):
        amiga.pod_from_amiga(bytes(amiga.POD_SAVEGAME_SIZE))


@pytest.mark.parametrize("size", [1442, 32484, 0x2A4C - 1, 0x2A4C + 1])
def test_an_amiga_saved_game_of_the_wrong_size_is_refused(size):
    """A count-1 party still parses at any of these lengths, so only the size
    check refuses them."""
    from goldbox import amiga_savegame as amiga

    good = _amiga_pod_from_dos(bytes(_synthetic_pod_save()))
    party = bytearray(good[:amiga.POD_PARTY_AT + amiga.POD_RECORD_BYTES])
    struct.pack_into(">H", party, amiga.POD_COUNT_AT, 1)
    blob = bytes(party).ljust(size, b"\0")[:size]
    if size >= len(party):
        amiga.pod_parse(blob)           # the walk alone accepts it
    with pytest.raises(amiga.PodSaveError, match="bytes is not the"):
        amiga.pod_from_amiga(blob)


def test_every_played_amiga_pools_of_darkness_slot_agrees_with_the_tool_and_with_dos():
    """Each slot on the player's disks, read by the library and by
    `tools/amiga/podsavegame.py`, and rewritten as the DOS container the
    same party would make."""
    from goldbox import amiga_savegame as amiga
    from tools.amiga import podsavegame

    found = podsavegame.slots()
    if not found:
        pytest.skip("no Amiga Pools of Darkness saved game; set $AMIGA_DISKS")
    seen = 0
    for name, copies in found.items():
        for _label, blob in copies:
            seen += 1
            tool = podsavegame.parse(blob)
            state = amiga.pod_from_amiga(blob, name)
            assert state.variables == blob[:1024], name
            assert state.count == tool.count, name
            assert (state.x, state.y) == (tool.square["x"],
                                          tool.square["y"]), name
            assert state.facing * 2 == tool.square["facing"], name
            # Read at literal file offsets, not through the map under test:
            # 1024 variables, then x, y, facing, wall, property, pad,
            # previous mode, mode, then the map words.
            assert blob[1024:1026] == bytes((state.x, state.y)), name
            assert blob[1026] % 2 == 0 and state.facing == blob[1026] // 2, name
            assert state.mode == blob[1031], name
            assert state.mode in (0, 2), name
            assert state.dungeon_map == int.from_bytes(blob[1032:1034], "big"), name
            assert state.clock == tool.clock, name
            dos = _dos_pod_from_amiga(blob)
            assert (dataclasses.replace(world_state.pod_from_dos(dos), source=name)
                    == state), name
            assert len(blob) == amiga.POD_SAVEGAME_SIZE, name
    assert seen >= 8


def _dos_pod_from_amiga(blob: bytes) -> bytes:
    """The 1364-byte DOS container holding the same regions as an Amiga slot."""
    box = dos_savegame.SAVE_POOLS_OF_DARKNESS
    save = bytearray(box.size)
    save[:dos_savegame.POD_PREVIOUS_MODE] = blob[:dos_savegame.POD_PREVIOUS_MODE]
    at = dos_savegame.POD_PREVIOUS_MODE + 1      # after the pad byte
    save[dos_savegame.POD_PREVIOUS_MODE] = blob[at]
    save[dos_savegame.POD_MODE] = blob[at + 1]
    dungeon_map, block, count = struct.unpack_from(">HHH", blob, at + 2)
    struct.pack_into("<H", save, dos_savegame.POD_MAP, dungeon_map)
    struct.pack_into("<H", save, dos_savegame.POD_MAP_BLOCK, block)
    save[box.party_size_byte] = count
    return bytes(save)
