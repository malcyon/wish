"""Curse's Dalelands map turns the Amiga fix into a world-map fix.

Each case is a state read on FS-UAE while a party entered the map from the
Tilverton sewers, travelled a leg, and left again by SEARCH AREA.
"""
from __future__ import annotations

from support.amigatarget import BASE, SSB, target

from automap import amiga
from automap.target import Fix

CURSE = amiga.MACHINES["curse-of-the-azure-bonds"]
WORLD = CURSE.world_map
#: Where the variable words live: the pointer holds the block minus `$9600`,
#: as the game's own allocation does.
WORDS = 0xC20000
POINTER = WORDS - 2 * 0x4B00
#: The sewer exit square the map keeps: 0,15 facing north, wall code 9 ahead.
EXIT = (0, 15, 0, 9)


def _put(mem, address, value):
    mem[POINTER + 2 * address] = value.to_bytes(2, "big")


def _memory(script, area, square, node=0, leg=0, pointer=POINTER):
    x, y, doubled, wall = square
    mem = {BASE + WORLD.script: bytes([script]),
           BASE + WORLD.variables: pointer.to_bytes(4, "big"),
           BASE + CURSE.party_x: x.to_bytes(2, "big"),
           BASE + CURSE.party_y: y.to_bytes(2, "big"),
           BASE + CURSE.party_facing: bytes([doubled, wall])}
    _put(mem, WORLD.area, area)
    _put(mem, WORLD.node, node)
    _put(mem, WORLD.leg, leg)
    return mem


def _world(node=0, leg=0):
    return Fix(0, 0, None, "memory", None, world_map=True,
               world_node=node, world_leg=leg)


def test_the_world_map_offsets_are_the_measured_ones():
    assert (WORLD.script, WORLD.variables, WORLD.areas) == (
        0x5CE1, 0x3D00, (0x50, 0x51))
    assert (WORLD.area, WORLD.node, WORLD.leg) == (0x4BF2, 0x4C9B, 0x4C9C)


def test_a_town_square_gives_the_usual_fix():
    t, _ = target(_memory(1, 1, (3, 14, 2, 0)), layout=CURSE)
    assert t.fix() == Fix(3, 14, 1, "memory")


def test_the_script_byte_names_the_map_before_the_area_id_does():
    # 1.3 s after YES: the area id still says the sewers.
    t, _ = target(_memory(0x50, 3, EXIT), layout=CURSE)
    assert t.fix() == _world()


def test_the_node_and_the_destination_are_read_from_their_words():
    for node, leg in ((0, 1), (1, 1), (0, 0)):
        t, _ = target(_memory(0x50, 0x50, EXIT, node, leg), layout=CURSE)
        assert t.fix() == _world(node, leg)


def test_a_loaded_world_map_save_at_the_party_menu_is_on_the_map():
    # The script byte is 0 until BEGIN ADVENTURING; the area id is loaded.
    t, _ = target(_memory(0, 0x50, EXIT), layout=CURSE)
    assert t.fix() == _world()


def test_leaving_holds_the_map_until_the_arriving_script_moves_the_party():
    t, guest = target(_memory(0x50, 0x50, EXIT), layout=CURSE)
    assert t.fix() == _world()
    # SEARCH AREA's Return: the sewer script is named, its load is running,
    # and the square is still the one the map kept.
    guest.memory.update(_memory(3, 0x50, EXIT))
    assert t.fix() == _world()
    # The sewer script's own SAVEs put the party on 0,0 south.
    guest.memory.update(_memory(3, 0x50, (0, 0, 4, 0)))
    assert t.fix() == Fix(0, 0, 2, "memory")
    # And it stays indoors while the entry message holds the area id.
    guest.memory.update(_memory(3, 0x50, EXIT))
    assert t.fix() == Fix(0, 15, 0, "memory")


def test_a_town_script_that_keeps_the_square_waits_for_the_area_id():
    t, guest = target(_memory(0x50, 0x50, EXIT), layout=CURSE)
    t.fix()
    guest.memory.update(_memory(3, 0x50, EXIT))
    assert t.fix() == _world()
    guest.memory.update(_memory(3, 3, EXIT))
    assert t.fix() == Fix(0, 15, 0, "memory")


def test_a_held_square_from_before_does_not_stop_a_later_town_fix():
    # Never on the map in this session: a script change alone is no map.
    t, _ = target(_memory(3, 0x50, EXIT), layout=CURSE)
    assert t.fix() == Fix(0, 15, 0, "memory")


def test_a_null_or_wild_pointer_gives_the_usual_fix():
    for pointer in (0, 0xF00000):
        mem = _memory(0x50, 0x50, EXIT)
        mem[BASE + WORLD.variables] = pointer.to_bytes(4, "big")
        t, _ = target(mem, layout=CURSE)
        assert t.fix() == Fix(0, 15, 0, "memory")


def test_other_titles_have_no_world_map_row():
    assert SSB.world_map is None
    for key, layout in amiga.MACHINES.items():
        assert (layout.world_map is None) == (key != "curse-of-the-azure-bonds")
