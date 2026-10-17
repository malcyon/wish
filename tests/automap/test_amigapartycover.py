"""`amigaparty.read_party` reads each level of the party's lists with one covering read.

The counting fake lays out a party like the one measured on Pools of Darkness:
six records, 91 items and 31 effects. On FS-UAE each block is a packet that
waits for an emulator frame, so the number of blocks is the cost.
"""

import pytest

from automap import amiga, amigaparty

KEY = "pools-of-darkness"
SLOW = 0xC00000
BASE = 0xC01000
HEAP = 0xC10000
ITEMS = 0xC30000
EFFECTS = 0xC50000
ITEM_COUNTS = [16, 16, 16, 16, 13, 14]
EFFECT_COUNTS = [6, 6, 2, 5, 6, 6]


class Counting:
    """An Amiga target that logs every block it is asked for."""

    def __init__(self, memory=None, with_blocks=True):
        self.layout = amiga.MACHINES[KEY]
        self.covering_reads = True
        self.data_base = BASE
        self.ram = bytearray(0x80000)
        self.blocks = []
        self.memory = memory if memory is not None else amiga.MEMORY
        if not with_blocks:
            self.read_blocks = None

    def put(self, addr, data):
        self.ram[addr - SLOW:addr - SLOW + len(data)] = data

    def read(self, addr, length):
        self.blocks.append((addr, length))
        return bytes(self.ram[addr - SLOW:addr - SLOW + length])

    def read_blocks(self, blocks):
        return [self.read(a, n) for a, n in blocks]


def lay(target, items=ITEM_COUNTS, effects=EFFECT_COUNTS, item_at=None,
        effect_at=None):
    """Records contiguous at HEAP; each member's nodes contiguous after the last."""
    row = amigaparty.ROWS[KEY]
    item_at = item_at or [ITEMS + sum(items[:i]) * 0x46 for i in range(len(items))]
    effect_at = effect_at or [EFFECTS + sum(effects[:i]) * 0xA
                              for i in range(len(effects))]
    addrs = [HEAP + row.record_size * i for i in range(len(items))]
    for i, address in enumerate(addrs):
        raw = bytearray(row.record_size)
        raw[row.name:row.name + 6] = b"MEMBER"
        raw[row.hp.offset] = 3
        raw[row.hp_max.offset] = 9
        raw[row.slot] = i
        nxt = addrs[i + 1] if i + 1 < len(addrs) else 0
        raw[row.next_offset:row.next_offset + 4] = nxt.to_bytes(4, "big")
        first = item_at[i] if items[i] else 0
        raw[row.items.head:row.items.head + 4] = first.to_bytes(4, "big")
        first = effect_at[i] if effects[i] else 0
        raw[row.effects.head:row.effects.head + 4] = first.to_bytes(4, "big")
        target.put(address, bytes(raw))
    for chain, counts, at, stride in ((row.items, items, item_at, 0x46),
                                      (row.effects, effects, effect_at, 0xA)):
        for i, count in enumerate(counts):
            for n in range(count):
                node = bytearray(((i * 31 + n * 7 + b) & 0xFF
                                  for b in range(chain.size)))
                nxt = at[i] + (n + 1) * stride if n + 1 < count else 0
                node[chain.link:chain.link + 4] = nxt.to_bytes(4, "big")
                target.put(at[i] + n * stride, bytes(node))
    target.put(BASE + row.head, addrs[0].to_bytes(4, "big"))


def per_node(target):
    """The same walk with no batch, one read per node."""
    row = amigaparty.ROWS[KEY]
    return amigaparty.walk(lambda a, n: target.read(a, n), row, BASE)


def test_a_darkness_party_costs_four_reads_and_is_the_same_as_node_by_node():
    target = Counting()
    lay(target)
    party = amigaparty.read_party(target)
    assert len(target.blocks) <= 4, target.blocks
    assert [len(m.item_nodes) for m in party] == ITEM_COUNTS
    assert [len(m.effect_nodes) for m in party] == EFFECT_COUNTS
    node_by_node = Counting()
    node_by_node.ram = target.ram
    expected = per_node(node_by_node)
    assert len(node_by_node.blocks) == 1 + 6 + 91 + 31
    assert tuple(m for m in expected if m.in_party) == party


def test_nodes_in_two_regions_each_get_a_read_clipped_to_their_own_region():
    memory = ((SLOW, 0x30000), (SLOW + 0x30000, 0x50000))
    target = Counting(memory)
    # Member 0's items end the first region, member 1's start the second.
    lay(target, items=[2, 2, 0, 0, 0, 0], effects=[0] * 6,
        item_at=[SLOW + 0x30000 - 0x8C, SLOW + 0x30000 + 0x100] + [0] * 4)
    party = amigaparty.read_party(target)
    assert [len(m.item_nodes) for m in party] == [2, 2, 0, 0, 0, 0]
    for addr, length in target.blocks:
        assert any(base <= addr and addr + length <= base + size
                   for base, size in memory), (addr, length)
    other = Counting(memory)
    other.ram = target.ram
    assert tuple(m for m in per_node(other) if m.in_party) == party


def test_a_wide_read_that_comes_back_short_is_replaced_by_node_reads():
    class Short(Counting):
        def read(self, addr, length):
            raw = super().read(addr, length)
            return raw[:-1] if length > 0x1000 else raw

    target = Short()
    lay(target)
    party = amigaparty.read_party(target)
    other = Counting()
    other.ram = target.ram
    assert tuple(m for m in per_node(other) if m.in_party) == party
    assert [len(m.item_nodes) for m in party] == ITEM_COUNTS


def test_a_level_spanning_more_than_the_cap_is_read_in_windows_within_it():
    target = Counting()
    lay(target, items=[1, 1, 0, 0, 0, 0], effects=[0] * 6,
        item_at=[ITEMS, ITEMS + amigaparty.COVER_LIMIT + 0x100] + [0] * 4)
    party = amigaparty.read_party(target)
    assert [len(m.item_nodes) for m in party] == [1, 1, 0, 0, 0, 0]
    assert max(n for _, n in target.blocks) <= amigaparty.COVER_LIMIT
    assert any(a <= ITEMS < a + n for a, n in target.blocks)


def test_a_source_without_read_blocks_is_read_node_by_node():
    target = Counting(with_blocks=False)
    lay(target)
    party = amigaparty.read_party(target)
    assert len(target.blocks) == 1 + 6 + 91 + 31
    assert [len(m.item_nodes) for m in party] == ITEM_COUNTS


def test_the_mode_byte_is_read_once_inside_one_mode_read_and_afresh_outside():
    target = Counting()
    lay(target)
    mode_at = BASE + amigaparty.ROWS[KEY].mode
    with amigaparty.one_mode_read():
        values = {amigaparty.mode(target) for _ in range(3)}
    assert values == {0}
    assert target.blocks.count((mode_at, 1)) == 1
    amigaparty.mode(target)
    amigaparty.mode(target)
    assert target.blocks.count((mode_at, 1)) == 3


def test_one_mode_read_does_not_outlive_its_block_even_on_an_error():
    target = Counting()
    lay(target)
    with pytest.raises(RuntimeError):
        with amigaparty.one_mode_read():
            amigaparty.mode(target)
            raise RuntimeError
    mode_at = BASE + amigaparty.ROWS[KEY].mode
    target.blocks.clear()
    amigaparty.mode(target)
    amigaparty.mode(target)
    assert target.blocks.count((mode_at, 1)) == 2


def test_a_source_that_does_not_ask_for_wide_reads_is_read_a_level_at_a_time():
    target = Counting()
    target.covering_reads = False
    lay(target)
    party = amigaparty.read_party(target)
    assert [len(m.item_nodes) for m in party] == ITEM_COUNTS
    assert len(target.blocks) > 4
    assert not any(n > 0x1000 for _, n in target.blocks)
