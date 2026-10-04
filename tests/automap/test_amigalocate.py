"""Checks that one sweep of the Amiga's memory says which title is running.

`locate_machines` reads each region once for however many titles it is asked
after, and `AmigaTarget.locate` is a caller of it rather than a second
implementation of the search. A read is a callable here; nothing needs an
emulator.
"""

from __future__ import annotations

import pytest

from automap import amiga

BLADES = amiga.MACHINES["secret-of-the-silver-blades"]
CURSE = amiga.MACHINES["curse-of-the-azure-bonds"]
BASE = 0xC10000


class Memory:
    """A machine's memory as `{base: bytes}`, counting the reads it is given."""

    def __init__(self, **blocks: bytes):
        self.blocks = {int(k[1:], 16): v for k, v in blocks.items()}
        self.reads: list[tuple[int, int]] = []

    def __call__(self, addr: int, length: int) -> bytes:
        self.reads.append((addr, length))
        out = bytearray(length)
        for base, blob in self.blocks.items():
            lo, hi = max(addr, base), min(addr + length, base + len(blob))
            if lo < hi:
                out[lo - addr:hi - addr] = blob[lo - base:hi - base]
        return bytes(out)


def loaded(machine: amiga.AmigaMachine) -> bytes:
    """A block with `machine`'s anchor where its executable carries it."""
    data = bytearray(0x8000)
    data[machine.anchor_offset:machine.anchor_offset + len(machine.anchor)] = \
        machine.anchor
    return bytes(data)


def test_the_title_in_memory_is_named_with_its_base():
    memory = Memory(_c10000=loaded(BLADES))
    assert amiga.locate_machines(memory, [BLADES, CURSE]) == {
        BLADES.title: [BASE]}


def test_two_titles_cost_one_sweep():
    """Asked after both titles, each region is still read once."""
    memory = Memory(_c10000=loaded(BLADES))
    amiga.locate_machines(memory, [BLADES, CURSE])
    assert memory.reads == [(0xC00000, 0x80000)]


def test_the_sweep_goes_on_to_chip_memory_only_when_slow_memory_had_nothing():
    memory = Memory(_10000=loaded(CURSE))
    found = amiga.locate_machines(memory, [BLADES, CURSE])
    assert found == {CURSE.title: [0x10000]}
    assert memory.reads == [(0xC00000, 0x80000), (0x000000, 0x80000)]


def test_a_full_sweep_reads_chip_memory_even_after_a_hit_in_slow_memory():
    memory = Memory(_c10000=loaded(BLADES))
    amiga.locate_machines(memory, [BLADES, CURSE], sweep_all=True)
    assert memory.reads == [(0xC00000, 0x80000), (0x000000, 0x80000)]


def test_a_full_sweep_reports_two_titles_in_different_regions():
    memory = Memory(_c10000=loaded(BLADES), _10000=loaded(CURSE))
    assert amiga.locate_machines(memory, [BLADES, CURSE], sweep_all=True) == {
        BLADES.title: [0xC10000], CURSE.title: [0x10000]}


def test_the_default_sweep_stops_at_the_first_region_with_a_hit():
    memory = Memory(_c10000=loaded(BLADES), _10000=loaded(CURSE))
    assert amiga.locate_machines(memory, [BLADES, CURSE]) == {
        BLADES.title: [0xC10000]}


def test_two_titles_in_one_region_are_both_reported():
    both = bytearray(loaded(BLADES))
    both[CURSE.anchor_offset:CURSE.anchor_offset + len(CURSE.anchor)] = \
        CURSE.anchor
    found = amiga.locate_machines(Memory(_c10000=bytes(both)), [BLADES, CURSE])
    assert found.keys() == {BLADES.title, CURSE.title}


def test_no_title_is_an_empty_answer_not_an_error():
    assert amiga.locate_machines(Memory(), [BLADES, CURSE]) == {}


def test_a_second_copy_of_an_anchor_is_reported_rather_than_resolved():
    data = bytearray(0x20000)
    data[BLADES.anchor_offset:BLADES.anchor_offset + len(BLADES.anchor)] = \
        BLADES.anchor
    data[0x10000 + BLADES.anchor_offset:
         0x10000 + BLADES.anchor_offset + len(BLADES.anchor)] = BLADES.anchor
    found = amiga.locate_machines(Memory(_c00000=bytes(data)), [BLADES])
    assert found == {BLADES.title: [0xC00000, 0xC10000]}


# -- the target's own locate() is one caller of it ---------------------------

class Reader:
    """Just enough transport for `AmigaTarget.read` to be the direct kind."""

    halts_machine = False

    def __init__(self, memory: Memory):
        self.read_memory = memory


def test_locate_is_the_shared_sweep_and_keeps_its_messages():
    memory = Memory(_c10000=loaded(BLADES))
    target = amiga.AmigaTarget(Reader(memory), BLADES)
    assert target.locate() == BASE
    assert memory.reads == [(0xC00000, 0x80000)]

    with pytest.raises(amiga.GuestError, match="is nowhere in the Amiga's"):
        amiga.AmigaTarget(Reader(Memory()), BLADES).locate()

    data = bytearray(0x20000)
    for at in (0, 0x10000):
        start = at + BLADES.anchor_offset
        data[start:start + len(BLADES.anchor)] = BLADES.anchor
    with pytest.raises(amiga.GuestError, match="more than one place"):
        amiga.AmigaTarget(Reader(Memory(_c00000=bytes(data))), BLADES).locate()


def test_an_amiga_target_says_its_memory_is_not_a_c64s():
    assert amiga.AmigaTarget.c64_memory is False


# -- a title whose data is in another hunk than its anchor -------------------

POOL_ROW = amiga.MACHINES["pool-of-radiance"]
SEG = POOL_ROW.segments
H31, H32 = 0xC10000, 0xC20000


def hunks(*, anchor_guard=None, data_guard=None, link=None) -> Memory:
    """Hunk 31 with the row's anchor and hunk 32, joined by `LoadSeg`'s BPTR."""
    data = bytearray(0x4000)
    data[8 + POOL_ROW.anchor_offset:8 + POOL_ROW.anchor_offset
         + len(POOL_ROW.anchor)] = POOL_ROW.anchor
    data[0:4] = (anchor_guard or SEG.anchor_size + 8).to_bytes(4, "big")
    data[4:8] = (((H32 - 4) // 4) if link is None else link).to_bytes(4, "big")
    after = bytearray(8)
    after[0:4] = (data_guard or SEG.data_size + 8).to_bytes(4, "big")
    return Memory(_c0fff8=bytes(data), _c1fff8=bytes(after))


def test_locate_hops_from_the_anchors_hunk_to_the_data_hunk():
    target = amiga.AmigaTarget(Reader(hunks()), POOL_ROW)
    assert target.locate() == H32
    assert target.anchor_base == H31


def test_a_wrong_guard_a_zero_link_and_a_link_outside_memory_are_blocked():
    for memory, expected in [
            (hunks(data_guard=0x2F84 + 4), "expected 0x2f8c"),
            (hunks(anchor_guard=0x351C), "expected 0x3524"),
            (hunks(link=0xFFFFFF), "not the next hunk"),
    ]:
        with pytest.raises(amiga.GuestError, match=expected):
            amiga.AmigaTarget(Reader(memory), POOL_ROW).locate()
    with pytest.raises(amiga.GuestError, match="not the next hunk"):
        amiga.AmigaTarget(Reader(hunks(link=0)), POOL_ROW).locate()


@pytest.mark.parametrize("machine", [BLADES, CURSE,
                                     amiga.MACHINES["pools-of-darkness"]])
def test_a_title_without_segments_makes_no_read_in_the_hop(machine):
    reads = []
    assert amiga.data_base_for(lambda a, n: reads.append(a), machine,
                               0xC10000) == 0xC10000
    assert reads == []
