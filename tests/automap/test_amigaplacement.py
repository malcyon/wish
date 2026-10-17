"""An Amiga memory fix is believed only when the engine has placed the party on the loaded map.

The engine's square is the unstarted party's, or the last area's, until a step
or a turn rewrites the wall-ahead and square-attribute bytes after the facing
from the map that is resident. Each test feeds the engine bytes a measured
FS-UAE poll held, over synthetic maps.
"""
from __future__ import annotations

import pytest
from gamedata import synthetic_geo
from support.amigatarget import BASE, SSB, target

from automap import amiga
from automap.area import RESIDENT_GEO
from automap.state import Automapper
from automap.target import Fix, ReplayTarget
from goldbox.geo import Geo

POD = amiga.MACHINES["pools-of-darkness"]
BLOCK = 0xC40000


def _maps() -> tuple[bytes, bytes]:
    """Two maps that tell apart: the second has every wall and attribute changed."""
    one = bytearray(synthetic_geo())
    two = bytearray(one)
    for i in range(0x300):
        two[i] = (one[i] ^ 0x37) & 0xFF if i >= 0x200 else (one[i] ^ 0x31) & 0xFF
    # Squares the scenarios stand on, with walls and attributes that differ.
    for x, y in ((7, 13), (3, 3), (15, 8), (11, 2), (0, 3), (1, 2)):
        one[0x000 + 16 * y + x] = 0xA5
        one[0x100 + 16 * y + x] = 0x5A
        one[0x200 + 16 * y + x] = 0x80 | x
    return bytes(one), bytes(two)


ONE, TWO = _maps()


def _engine(layout, x, y, doubled, wall, attribute) -> dict[int, bytes]:
    mem = {BASE + layout.party_x: bytes([x]), BASE + layout.party_y: bytes([y]),
           BASE + layout.party_facing: bytes([doubled, wall, attribute])}
    return mem


def _setup(layout, resident, **names):
    mem = _engine(layout, 0, 0, 0, 0, 0)
    mem[BASE + layout.geo_pointer] = BLOCK.to_bytes(4, "big")
    mem[BLOCK] = resident
    t, guest = target(mem, layout=layout)
    if layout.overland_pointer is not None:
        guest.memory[BASE + layout.overland_pointer] = (0xC30000).to_bytes(4, "big")
        guest.memory[0xC30000 + layout.overland_flag] = b"\x00"
    maps = {name: Geo(data) for name, data in names.items()}
    first = next(iter(names))
    return Automapper(t, maps, area=first, title=layout.title), guest


def _set(guest, layout, x, y, doubled, geo=None, wall=None, attribute=None):
    """Put the engine at a square; its bytes are the map's unless overridden."""
    g = Geo(geo) if geo is not None else None
    if wall is None:
        wall = g.wall(x, y, doubled // 2)
    if attribute is None:
        attribute = g.attributes(x, y)
    guest.memory.update(_engine(layout, x, y, doubled, wall, attribute))


def test_the_unstarted_partys_square_is_not_recorded_before_the_scripted_placement():
    mapper, guest = _setup(SSB, ONE, GEO10=ONE)
    _set(guest, SSB, 7, 13, 0, wall=0, attribute=0)
    for _ in range(4):
        assert not mapper.poll()
    assert not mapper.state.exploration.seen
    _set(guest, SSB, 3, 3, 4, ONE)
    mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (3, 3)
    assert (7, 13) not in mapper.state.exploration.seen


def test_the_old_areas_square_is_not_recorded_on_the_new_map():
    mapper, guest = _setup(SSB, ONE, GEO10=ONE, GEO20=TWO)
    _set(guest, SSB, 14, 8, 2, ONE)
    mapper.poll()
    assert mapper.state.area == "GEO10"
    guest.memory[BLOCK] = TWO
    _set(guest, SSB, 15, 8, 2, ONE)
    mapper.poll()
    assert mapper.state.area == "GEO20"
    assert (15, 8) not in mapper.state.exploration.seen
    _set(guest, SSB, 15, 8, 2, TWO)
    mapper.poll()
    assert (15, 8) in mapper.state.exploration.seen


def test_a_new_areas_square_is_not_recorded_on_the_old_map():
    """The Aerie to Mulmaster walk: back from the overland with the old block
    still resident, the engine holds the new city's arrival square."""
    mapper, guest = _setup(POD, ONE, GEO21=ONE, GEO13=TWO)
    _set(guest, POD, 1, 2, 2, ONE)
    mapper.poll()
    assert (1, 2) in mapper.state.exploration.seen
    before = set(mapper.state.exploration.seen)
    guest.memory[0xC30000 + POD.overland_flag] = b"\x01"
    mapper.poll()
    guest.memory[0xC30000 + POD.overland_flag] = b"\x00"
    # Mulmaster's arrival square, with the wall byte of the other map.
    _set(guest, POD, 0, 3, 6, TWO, attribute=Geo(ONE).attributes(0, 3))
    for _ in range(6):
        mapper.poll()
    assert mapper.state.exploration.seen == before
    assert (mapper.state.x, mapper.state.y) != (0, 3)


def test_a_step_and_a_turn_are_believed_at_once():
    mapper, guest = _setup(SSB, ONE, GEO10=ONE)
    _set(guest, SSB, 3, 3, 4, ONE)
    mapper.poll()
    _set(guest, SSB, 3, 4, 4, ONE)
    mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (3, 4)
    _set(guest, SSB, 3, 4, 2, ONE)
    mapper.poll()
    assert mapper.state.facing == 1


def test_a_failing_fix_is_asked_again_and_believed_when_the_bytes_agree():
    mapper, guest = _setup(SSB, ONE, GEO10=ONE)
    _set(guest, SSB, 3, 3, 4, ONE, attribute=0)
    mapper.poll()
    assert not mapper.state.exploration.seen
    _set(guest, SSB, 3, 3, 4, ONE)
    mapper.poll()
    assert (3, 3) in mapper.state.exploration.seen


def test_the_arrival_allowance_does_not_let_a_failing_fix_through():
    mapper, guest = _setup(POD, ONE, GEO21=ONE)
    _set(guest, POD, 1, 2, 2, ONE)
    mapper.poll()
    guest.memory[0xC30000 + POD.overland_flag] = b"\x01"
    mapper.poll()
    assert mapper.state.world_map
    guest.memory[0xC30000 + POD.overland_flag] = b"\x00"
    _set(guest, POD, 15, 15, 0, ONE, wall=0x0F, attribute=0x7E)
    for _ in range(6):
        mapper.poll()
    assert (15, 15) not in mapper.state.exploration.seen
    assert (mapper.state.x, mapper.state.y) != (15, 15)


def test_a_target_that_is_a_c64s_memory_is_not_asked():
    class Asked(ReplayTarget):
        asked = 0

        def placement_matches(self, fix):
            Asked.asked += 1
            return False

    t = Asked([Fix(2, 2, 0, "memory", None)] * 3,
              {RESIDENT_GEO: synthetic_geo()})
    mapper = Automapper(t, {"GEO00": Geo(synthetic_geo())}, area="GEO00")
    for _ in range(3):
        mapper.poll()
    assert Asked.asked == 0
    assert (mapper.state.x, mapper.state.y) == (2, 2)


def test_a_steady_poll_costs_one_round_trip_for_the_check():
    _mapper, guest = _setup(SSB, ONE, GEO10=ONE)
    t = _mapper.target
    _set(guest, SSB, 3, 3, 4, ONE)
    fix = t.fix()
    assert t.placement_matches(fix)          # the first asks twice: no address yet
    before = len(guest.calls)
    for _ in range(3):
        assert t.placement_matches(fix)
    assert len(guest.calls) - before == 3


def test_a_pointer_that_moved_is_followed_in_a_second_round_trip():
    mapper, guest = _setup(SSB, ONE, GEO10=ONE)
    t = mapper.target
    _set(guest, SSB, 3, 3, 4, ONE)
    fix = t.fix()
    assert t.placement_matches(fix)
    guest.memory[BASE + SSB.geo_pointer] = (BLOCK + 0x1000).to_bytes(4, "big")
    guest.memory[BLOCK + 0x1000] = ONE
    before = len(guest.calls)
    assert t.placement_matches(fix)
    assert len(guest.calls) - before == 2
    before = len(guest.calls)
    assert t.placement_matches(fix)
    assert len(guest.calls) - before == 1


def test_a_null_pointer_is_not_a_placement():
    mapper, guest = _setup(SSB, ONE, GEO10=ONE)
    t = mapper.target
    _set(guest, SSB, 3, 3, 4, ONE)
    fix = t.fix()
    assert t.placement_matches(fix)
    guest.memory[BASE + SSB.geo_pointer] = bytes(4)
    assert not t.placement_matches(fix)


def test_every_facing_reads_the_wall_the_map_calls_that_facing():
    mapper, guest = _setup(SSB, ONE, GEO10=ONE)
    t = mapper.target
    for doubled in (0, 2, 4, 6):
        _set(guest, SSB, 7, 13, doubled, ONE)
        assert t.placement_matches(t.fix()), doubled
        _set(guest, SSB, 7, 13, doubled, ONE,
             wall=(Geo(ONE).wall(7, 13, doubled // 2) + 1) & 0x0F)
        assert not t.placement_matches(t.fix()), doubled


@pytest.mark.parametrize("x,y", [(0, 3), (5, 7)])
def test_a_new_areas_square_is_not_recorded_on_the_old_map_when_the_block_lands_late(x, y):
    """Mulmaster and the village: the overland return sees the old block, the
    next poll sees the new one, and the area is named from neither."""
    # The old map is open at the arrival square, so the area check that a solid
    # square would trigger on its own does not run.
    one = bytearray(ONE)
    one[0x300 + 16 * y + x] = 0x55
    one = bytes(one)
    mapper, guest = _setup(POD, one, GEO21=one, GEO13=TWO)
    _set(guest, POD, 1, 2, 2, one)
    mapper.poll()
    guest.memory[0xC30000 + POD.overland_flag] = b"\x01"
    mapper.poll()
    guest.memory[0xC30000 + POD.overland_flag] = b"\x00"
    _set(guest, POD, x, y, 2, TWO)
    mapper.poll()                        # fails against ONE
    aerie = mapper.state.exploration
    kept = set(aerie.seen)
    guest.memory[BLOCK] = TWO
    mapper.poll()
    assert mapper.state.area == "GEO13"
    assert (x, y) in mapper.state.exploration.seen
    assert aerie.seen == kept and (x, y) not in kept


def test_after_a_camp_reload_names_the_old_map_the_next_placed_square_is_believed_at_once():
    mapper, guest = _setup(SSB, TWO, GEO20=TWO, GEO10=ONE)
    _set(guest, SSB, 11, 2, 2, TWO)
    mapper.poll()
    assert (mapper.state.x, mapper.state.y) == (11, 2)
    _set(guest, SSB, 7, 13, 0, wall=0, attribute=0)
    mapper.poll()
    guest.memory[BLOCK] = ONE
    mapper.poll()
    _set(guest, SSB, 3, 3, 4, ONE)
    mapper.poll()
    assert mapper.state.area == "GEO10"
    assert (mapper.state.x, mapper.state.y) == (3, 3)
    assert not {(11, 2), (7, 13)} & mapper.state.exploration.seen
