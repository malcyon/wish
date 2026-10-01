"""Pools of Darkness' overland flag turns the fix into a world-map fix."""
from __future__ import annotations

from support.amigatarget import BASE, SSB, target

from automap import amiga
from automap.state import Automapper
from automap.target import Fix

POD = amiga.MACHINES["pools-of-darkness"]
CURSE = amiga.MACHINES["curse-of-the-azure-bonds"]
RECORD = 0xC30000


def _memory(layout, flag=None, pointer=RECORD, x=0, y=3, doubled=2):
    mem = {}
    for offset, value in ((layout.party_x, x), (layout.party_y, y),
                          (layout.party_facing, doubled)):
        mem[BASE + offset] = value.to_bytes(layout.width, "big")
    if layout.overland_pointer is not None:
        mem[BASE + layout.overland_pointer] = pointer.to_bytes(4, "big")
    if flag is not None:
        mem[RECORD + layout.overland_flag] = bytes([flag])
    return mem


def test_the_flag_set_gives_a_world_map_fix_over_a_valid_indoor_square():
    t, _ = target(_memory(POD, flag=1), layout=POD)
    fix = t.fix()
    assert fix.world_map and fix.world_node is None


def test_any_flag_value_but_one_gives_the_usual_fix():
    # The flag measured 1 on the overland and 0 indoors (boot M, #804 comment
    # 5933933062); other values are unmeasured, so only 1 is the world map.
    for flag in (2, 0xFF):
        t, _ = target(_memory(POD, flag=flag), layout=POD)
        assert t.fix() == Fix(0, 3, 1, "memory")


def test_the_overland_offsets_are_the_measured_ones():
    # From the same boot M measurement; a changed table entry must be re-measured.
    assert POD.overland_pointer == 0x57AC
    assert POD.overland_flag == 0x24


def test_the_flag_clear_gives_the_usual_fix():
    t, _ = target(_memory(POD, flag=0), layout=POD)
    assert t.fix() == Fix(0, 3, 1, "memory")


def test_a_pointer_of_zero_or_outside_memory_gives_the_usual_fix():
    for pointer in (0, 0xF00000):
        mem = _memory(POD, flag=1, pointer=pointer)
        mem[pointer + POD.overland_flag] = b"\x01"
        t, _ = target(mem, layout=POD)
        assert t.fix() == Fix(0, 3, 1, "memory")


def test_other_titles_never_read_the_overland_pointer():
    for layout in (SSB, CURSE):
        t, _ = target(_memory(layout), layout=layout)
        reads = []
        real = t.read
        t.read = lambda addr, n, real=real: (reads.append(addr),
                                             real(addr, n))[1]
        assert t.fix() is not None
        assert BASE + 0x57AC not in reads
        assert all(not (BASE + 0x57AC <= a < BASE + 0x57B0) for a in reads)


def test_the_state_goes_to_the_world_map_and_back_on_an_indoor_fix():
    from gamedata import synthetic_geo

    from goldbox.geo import Geo
    block = synthetic_geo()
    mem = _memory(POD, flag=0)
    mem[BASE + POD.geo_pointer] = (0xC40000).to_bytes(4, "big")
    mem[0xC40000] = block
    t, guest = target(mem, layout=POD)
    mapper = Automapper(t, {"GEO21": Geo(block)}, area="GEO21", title=POD.title)
    mapper.poll()
    state = mapper.state
    seen = len(state.exploration)
    guest.memory[RECORD + POD.overland_flag] = b"\x01"
    mapper.poll()
    assert state.world_map
    assert (state.area, state.x, state.y) == ("GEO21", 0, 3)
    assert len(state.exploration) == seen
    guest.memory[RECORD + POD.overland_flag] = b"\x00"
    guest.memory.update(_memory(POD, flag=0, x=1, y=2, doubled=0))
    mapper.poll()
    assert not state.world_map
    assert (state.x, state.y) == (1, 2)
