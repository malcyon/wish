"""Pool of Radiance's travel grid, read through `AmigaTarget.fix`.

The memory is built from the row's own fields: nothing here is game data.
"""

from __future__ import annotations

import pytest

from automap import amiga
from automap.state import Automapper
from automap.target import Fix
from goldbox.geo import Geo

POOL = amiga.MACHINES["pool-of-radiance"]
GRID = POOL.travel_grid
SEG = POOL.segments
H31, H32, BLOCK, GEO = 0xC10000, 0xC20000, 0xC30000, 0xC40000


class Memory:
    """Sparse memory. A read outside a block raises, so a reader that strays to
    an address nothing here placed (a C64 address, say) fails loudly."""

    def __init__(self):
        self.blocks: dict[int, bytearray] = {}
        self.reads: list[tuple[int, int]] = []

    def put(self, addr: int, data: bytes) -> None:
        for base, blob in self.blocks.items():
            if base <= addr and addr + len(data) <= base + len(blob):
                blob[addr - base:addr - base + len(data)] = data
                return
        raise AssertionError(f"{addr:#x} is in no block")

    def read_memory(self, addr: int, length: int) -> bytes:
        self.reads.append((addr, length))
        for base, blob in self.blocks.items():
            if base <= addr and addr + length <= base + len(blob):
                return bytes(blob[addr - base:addr - base + length])
        raise AssertionError(f"read of {addr:#x}+{length:#x} is in no block")

    halts_machine = False


def guest(view=3, area=26, x=7, y=29, facing=2, indoors=0, lagging=26,
          pointer=BLOCK, geo=GEO) -> Memory:
    mem = Memory()
    mem.blocks[H31 - 8] = bytearray(0x4000)
    mem.blocks[H32 - 8] = bytearray(0x3000)
    mem.blocks[BLOCK] = bytearray(0x200)
    # Not a map, and not the one the automapper holds.
    mem.blocks[GEO] = bytearray(bytes(range(256)) * 4)
    mem.put(H31 - 8, (SEG.anchor_size + 8).to_bytes(4, "big"))
    mem.put(H31 - 4, ((H32 - 4) // 4).to_bytes(4, "big"))
    mem.put(H31 + POOL.anchor_offset, POOL.anchor)
    mem.put(H32 - 8, (SEG.data_size + 8).to_bytes(4, "big"))
    mem.put(H32 + GRID.view, bytes([view]))
    mem.put(H32 + GRID.area, bytes([area]))
    mem.put(H32 + GRID.block_pointer, pointer.to_bytes(4, "big"))
    mem.put(H32 + POOL.geo_pointer, geo.to_bytes(4, "big"))
    mem.put(BLOCK + GRID.x, x.to_bytes(2, "big"))
    mem.put(BLOCK + GRID.y, y.to_bytes(2, "big"))
    mem.put(BLOCK + GRID.indoors, indoors.to_bytes(2, "big"))
    mem.put(BLOCK + 0x1E4, lagging.to_bytes(2, "big"))
    mem.put(H32 + POOL.party_x, bytes([9, 13, facing]))
    return mem


def target(mem: Memory) -> amiga.AmigaTarget:
    t = amiga.AmigaTarget(mem, POOL, anchor_base=H31)
    mem.reads.clear()
    return t


def test_the_hop_lands_on_the_data_hunk():
    assert target(guest()).data_base == H32


@pytest.mark.parametrize("view,area,window", [(2, 25, 0), (3, 26, 1), (4, 27, 2)])
def test_the_view_byte_names_the_window(view, area, window):
    fix = target(guest(view=view, area=area)).fix()
    assert fix == Fix(7, 29, None, "memory", None, outdoors=True,
                      window=window, heading=2)


def test_the_blocks_lagging_area_word_is_never_read():
    """View 2 and area 25 agree and the block's own word still says 26. Reading
    that word would give window 1 (or none)."""
    mem = guest(view=2, area=25, lagging=26)
    fix = target(mem).fix()
    assert fix is not None and fix.window == 0
    assert all(not (BLOCK + 0x1E4 <= a < BLOCK + 0x1E6 or
                    a <= BLOCK + 0x1E4 < a + n) for a, n in mem.reads)


def test_a_view_and_an_area_that_disagree_give_no_fix():
    assert target(guest(view=3, area=25)).fix() is None


def test_an_indoors_word_that_is_set_gives_no_fix_and_reads_no_indoor_square():
    mem = guest(indoors=1)
    assert target(mem).fix() is None
    stale = H32 + POOL.party_x
    assert all(not (a <= stale < a + n) for a, n in mem.reads)


def test_the_3d_view_takes_the_indoor_path():
    assert target(guest(view=1, facing=0)).fix() == Fix(9, 13, 0, "memory")


def test_a_view_of_zero_takes_the_indoor_path():
    assert target(guest(view=0, facing=4)).fix() == Fix(9, 13, 2, "memory")


def test_a_null_block_pointer_gives_no_fix():
    assert target(guest(pointer=0)).fix() is None


def test_a_block_pointer_outside_memory_gives_no_fix():
    assert target(guest(pointer=0x00DEAD00)).fix() is None


@pytest.mark.parametrize("x,y", [(18, 29), (7, 36)])
def test_a_square_off_the_window_gives_no_fix(x, y):
    assert target(guest(x=x, y=y)).fix() is None


def test_a_heading_the_engine_writes_is_the_byte():
    assert target(guest(facing=6)).fix().heading == 6


def test_a_heading_it_does_not_write_is_none_and_the_fix_stands():
    fix = target(guest(facing=9)).fix()
    assert fix is not None and fix.heading is None and fix.x == 7


def test_an_indoor_poll_reads_twice_and_an_outdoor_one_five_times():
    mem = guest(view=1, facing=0)
    target(mem).fix()
    assert len(mem.reads) == 5          # the four fixed reads, then the party
    mem = guest()
    target(mem).fix()
    assert len(mem.reads) == 5          # the four fixed reads, then the block


def test_the_four_fixed_offset_reads_go_in_one_batch():
    mem = guest()
    t = target(mem)
    calls = []
    real = t.read_blocks
    t.read_blocks = lambda blocks: (calls.append(len(blocks)), real(blocks))[1]
    t.fix()
    assert calls[0] == 4


# -- the shipped automapper over it -------------------------------------------


def mapper(mem: Memory) -> Automapper:
    # A block that is not a map: the GEO pointer on the grid points at one.
    return Automapper(target(mem), {"GEO01": Geo(bytes(0x400))},
                      title="Pool of Radiance")


def test_travel_fixes_are_followed_past_the_proof_without_a_map():
    """`_running` would stop believing them after `PROVEN_FOR` ticks, because
    the block on the grid is no map."""
    mem = guest()
    m = mapper(mem)
    for _ in range(m.PROVEN_FOR + 5):
        m.poll()
    assert m.state.outdoors and (m.state.x, m.state.y) == (7, 29)
    assert m.state.window == 1 and m.state.heading == 2
    mem.put(BLOCK + GRID.x, (8).to_bytes(2, "big"))
    assert m.poll() is True
    assert m.state.x == 8


def test_a_seam_is_accepted_on_the_next_poll_and_reads_no_c64_address():
    from automap.window import WINDOW_STEP
    mem = guest(view=3, area=26, x=2, y=28)
    m = mapper(mem)
    m.poll()
    s = m.state
    assert s.x + WINDOW_STEP * s.window == 15
    mem.put(H32 + GRID.view, bytes([2]))
    mem.put(H32 + GRID.area, bytes([25]))
    mem.put(BLOCK + GRID.x, (14).to_bytes(2, "big"))
    assert m.poll() is True
    assert (s.window, s.x, s.y) == (0, 14, 28)
    assert s.x + WINDOW_STEP * s.window == 14
    assert s.area is None and not s.exploration.seen


def test_a_block_pointer_whose_span_runs_past_the_end_of_memory_gives_no_fix():
    """The pointer is inside slow memory and the 0x48-byte span is not. The
    fake raises on any read outside its blocks, so none is made."""
    assert target(guest(pointer=0xC80000 - 0x20)).fix() is None


def test_a_link_to_a_regions_first_byte_is_refused_before_it_is_read():
    """The guard sits eight bytes before the hunk, outside memory here."""
    mem = guest()
    mem.put(H31 - 4, ((0xC00000 - 4) // 4).to_bytes(4, "big"))
    with pytest.raises(amiga.GuestError, match="outside the Amiga's memory"):
        amiga.AmigaTarget(mem, POOL, anchor_base=H31)


def test_an_anchor_at_a_regions_first_byte_is_refused_before_it_is_read():
    with pytest.raises(amiga.GuestError, match="outside the Amiga's memory"):
        amiga.AmigaTarget(guest(), POOL, anchor_base=0xC00000)


def test_indoors_to_the_grid_and_back_is_followed_both_ways():
    from gamedata import synthetic_geo
    block = synthetic_geo()
    mem = guest(view=1, facing=0)
    mem.put(GEO, block)
    m = Automapper(target(mem), {"GEO01": Geo(block)},
                   title="Pool of Radiance")
    m.poll()
    assert not m.state.outdoors and m.state.area == "GEO01"
    assert (m.state.x, m.state.y) == (9, 13)
    mem.put(H32 + GRID.view, bytes([3]))
    mem.put(H32 + GRID.area, bytes([26]))
    m.poll()
    assert m.state.outdoors and (m.state.window, m.state.x) == (1, 7)
    mem.put(H32 + GRID.view, bytes([1]))
    mem.put(H32 + POOL.party_x, bytes([9, 14, 0]))
    m.poll()
    assert not m.state.outdoors and (m.state.x, m.state.y) == (9, 14)


def test_the_grids_block_is_unknown_to_the_title_check_and_not_ours():
    """`looks_like_a_map` is False for it, so `verdict` is UNKNOWN and the grid
    can never latch a rejection of its own."""
    from automap.area import UNKNOWN
    m = mapper(guest())
    assert m.resident.verdict(m._maps) == (UNKNOWN, None)
    for _ in range(m.PROVEN_FOR + 5):
        m.poll()
    assert m.title_check is UNKNOWN and m.state.outdoors


def test_a_rejection_latched_earlier_still_drops_grid_fixes():
    """A title check that has already said NOT_OURS means the machine is
    running another game, and its bytes are not recorded on the grid either;
    only one of our maps turning up resident lifts it."""
    from automap.area import NOT_OURS
    m = mapper(guest())
    m.poll()
    m.title_check = NOT_OURS
    m.state.outdoors = False
    assert m.poll() is False and not m.state.outdoors
