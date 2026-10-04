"""The Amiga's memory is measured from ExecBase, so a machine with fast RAM is found.

Every memory here is a synthetic image; nothing needs an emulator or a disk.
"""

from __future__ import annotations

from support.amigamemory import (
    CHIP_HEADER,
    EXEC_BASE,
    FAST_AT,
    FAST_END,
    header,
    machine_with_fast_ram,
)

from automap import amiga
from wish import amigalocate

BLADES = amiga.MACHINES["secret-of-the-silver-blades"]
BASE = FAST_AT + 0x10000
FAST = (FAST_AT + 0x20, FAST_END - FAST_AT - 0x20)
CHIP = (CHIP_HEADER + 0x20, 0x80000 - CHIP_HEADER - 0x20)


class Memory:
    def __init__(self, blocks: dict[int, bytes]):
        self.blocks = dict(blocks)

    def __call__(self, addr: int, length: int, timeout=None) -> bytes:
        out = bytearray(length)
        for base, blob in self.blocks.items():
            lo, hi = max(addr, base), min(addr + length, base + len(blob))
            if lo < hi:
                out[lo - addr:hi - addr] = blob[lo - base:hi - base]
        return bytes(out)

    def put(self, addr: int, data: bytes) -> None:
        self.blocks[addr] = data


def _fast_game(memory: Memory, geo_at: int | None = None) -> None:
    data = bytearray(0x8000)
    data[BLADES.anchor_offset:BLADES.anchor_offset + len(BLADES.anchor)] = \
        BLADES.anchor
    if geo_at is not None:
        data[BLADES.geo_pointer:BLADES.geo_pointer + 4] = geo_at.to_bytes(4, "big")
    memory.put(BASE, bytes(data))


class Transport:
    halts_machine = False

    def __init__(self, memory: Memory):
        self.read_memory = memory


def test_the_regions_are_the_ones_exec_lists_highest_address_first():
    assert amiga.memory_regions(Memory(machine_with_fast_ram())) == (FAST, CHIP)


def test_zeros_where_exec_base_should_be_fall_back_to_the_a500():
    assert amiga.memory_regions(Memory({})) == amiga.MEMORY


def test_an_exec_base_that_fails_its_complement_falls_back():
    image = machine_with_fast_ram()
    chip = bytearray(image[0])
    chip[EXEC_BASE + 0x26:EXEC_BASE + 0x2A] = bytes(4)
    assert amiga.memory_regions(Memory({**image, 0: bytes(chip)})) == amiga.MEMORY


def test_a_list_that_never_ends_falls_back():
    image = machine_with_fast_ram()
    fast = bytearray(image[FAST_AT])
    fast[0:4] = FAST_AT.to_bytes(4, "big")          # the node points at itself
    assert amiga.memory_regions(Memory({**image, FAST_AT: bytes(fast)})) == amiga.MEMORY


def test_a_node_that_is_not_a_memory_header_falls_back():
    image = machine_with_fast_ram()
    fast = bytearray(image[FAST_AT])
    fast[0x14:0x18], fast[0x18:0x1C] = fast[0x18:0x1C], fast[0x14:0x18]
    assert amiga.memory_regions(Memory({**image, FAST_AT: bytes(fast)})) == amiga.MEMORY


EXTRA_AT = 0x300000


def _with_extra_node(lower: int, upper: int) -> dict[int, bytes]:
    """The fast-RAM machine with a second node after the fast header."""
    image = machine_with_fast_ram()
    fast = bytearray(image[FAST_AT])
    fast[0:4] = EXTRA_AT.to_bytes(4, "big")
    extra = header(CHIP_HEADER, lower, upper)
    return {**image, FAST_AT: bytes(fast), EXTRA_AT: extra}


def test_a_region_listed_twice_is_swept_once():
    image = _with_extra_node(FAST_AT + 0x20, FAST_END)
    assert amiga.memory_regions(Memory(image)) == (FAST, CHIP)


def test_a_list_claiming_more_than_the_address_space_falls_back():
    image = _with_extra_node(0x20, 0x1000000)
    assert amiga.memory_regions(Memory(image)) == amiga.MEMORY


def test_an_anchor_in_fast_ram_is_found_in_the_measured_regions_and_not_in_the_a500s():
    memory = Memory(machine_with_fast_ram())
    _fast_game(memory)
    assert amiga.locate_machines(memory, [BLADES]) == {}
    regions = amiga.memory_regions(memory)
    assert amiga.locate_machines(memory, [BLADES], regions) == {
        BLADES.title: [BASE]}


def test_a_target_on_fast_ram_reads_the_map_the_game_keeps_there():
    memory = Memory(machine_with_fast_ram())
    geo_at = FAST_AT + 0x40000
    _fast_game(memory, geo_at)
    regions = amiga.memory_regions(memory)
    target = amiga.AmigaTarget(Transport(memory), BLADES, anchor_base=BASE,
                               memory=regions)
    assert target.resident_geo_address() == geo_at
    assert amiga.AmigaTarget(Transport(memory), BLADES,
                             anchor_base=BASE).resident_geo_address() is None


def test_the_locator_finds_a_title_that_runs_from_fast_ram():
    memory = Memory(machine_with_fast_ram())
    geo_at = FAST_AT + 0x40000
    _fast_game(memory, geo_at)
    transport = Transport(memory)
    locator = amigalocate.Locator()
    target = locator.target(memory, transport)
    assert target.anchor_base == BASE
    assert target.resident_geo_address() == geo_at


def test_the_locator_still_finds_a_title_on_a_machine_it_cannot_measure():
    memory = Memory({0xC10000: _slow_game()})
    target = amigalocate.Locator().target(memory, Transport(memory))
    assert target.anchor_base == 0xC10000


def _slow_game() -> bytes:
    data = bytearray(0x8000)
    data[BLADES.anchor_offset:BLADES.anchor_offset + len(BLADES.anchor)] = \
        BLADES.anchor
    return bytes(data)
