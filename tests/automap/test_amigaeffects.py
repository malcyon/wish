"""`automap/amigaeffects.py`, and the Amiga Level up that uses it.

A regained ranger or paladin in Silver Blades or Pools of Darkness gets an
effect node from the trainer, which the game allocates from its own pool.
These tests hold the allocation to the allocator's rule on a machine built
here, byte by byte, and the pool's constants to the executables on the
player's disks (skipped without them).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from automap import amiga, amigaparty
from automap import amigaeffects as fx
from automap import amigalevelup as lv

SSB = lv.SILVER_BLADES
POD = lv.POOLS_OF_DARKNESS
SLOW = 0xC00000
DATA = 0xC40000
POOL = 0xC60000
RECORD = 0xC20000


class Machine:
    """512K of slow memory, read and written the way `AmigaTarget` is."""

    def __init__(self):
        self.ram = bytearray(0x80000)
        self.data_base = DATA
        self.memory = amiga.MEMORY
        self.written: list[tuple[int, bytes]] = []

    def read(self, addr: int, length: int) -> bytes:
        return bytes(self.ram[addr - SLOW:addr - SLOW + length])

    def write(self, addr: int, data: bytes) -> None:
        self.written.append((addr, bytes(data)))
        self.put(addr, data)

    def put(self, addr: int, data: bytes) -> None:
        self.ram[addr - SLOW:addr - SLOW + len(data)] = data

    def u32(self, addr: int) -> int:
        return int.from_bytes(self.read(addr, 4), "big")


def machine(key: str, bitmap: bytes = b"", nodes=(), count=None,
            size: int = 10) -> Machine:
    """A pool for `key` with `bitmap` at the start of its bitmap, and a
    record at `RECORD` whose effect list is the pool slots `nodes`."""
    pool = fx.POOLS[key]
    m = Machine()
    at = DATA + pool.descriptor
    m.put(at, (pool.count if count is None else count).to_bytes(2, "big")
          + size.to_bytes(2, "big") + POOL.to_bytes(4, "big") + bitmap)
    # The pool's memory is not cleared: every slot starts as stale bytes.
    m.put(POOL, bytes([0x5A]) * pool.count * 10)
    link = RECORD + amigaparty.ROWS[key].effects.head
    m.put(link, bytes(4))
    for slot in nodes:
        node = POOL + slot * 10
        m.put(link, node.to_bytes(4, "big"))
        m.put(node, bytes([0x2F, 0x5A, 0, 0, 0xFF, 0, 0, 0, 0, 0]))
        link = node + 6
    return m


@pytest.mark.parametrize("key", [SSB, POD])
def test_a_node_takes_the_first_clear_bit_of_the_first_byte_not_full(key):
    """Bits 0, 1 and 3 of the second byte are taken, so the allocator hands
    out slot 10; the constructor appends it after the last node and writes
    every byte but +1, which the pool leaves as it found it."""
    m = machine(key, bytes([0xFF, 0x0B]), nodes=(0, 9))
    made = fx.add(m, key, RECORD, [fx.NewEffect(0x69)])
    node = POOL + 10 * 10
    assert m.read(node, 10) == bytes([0x69, 0x5A, 0, 0, 0xFF, 0, 0, 0, 0, 0])
    assert m.read(DATA + fx.POOLS[key].descriptor + 9, 1) == bytes([0x0F])
    assert m.u32(POOL + 9 * 10 + 6) == node
    assert made[-1] == (POOL + 9 * 10 + 6, node.to_bytes(4, "big"))
    assert made == tuple(m.written)
    bitmap = DATA + fx.POOLS[key].descriptor + 8 + 1
    assert [at for at, _ in made] == [node, node + 2, bitmap, POOL + 9 * 10 + 6]


def test_an_empty_list_gets_the_node_as_its_head():
    m = machine(SSB, bytes([0x00]))
    fx.add(m, SSB, RECORD, [fx.NewEffect(8)])
    assert m.u32(RECORD + 0x96) == POOL
    assert m.read(POOL, 1) == b"\x08"
    assert m.read(DATA + 0x7618 + 8, 1) == b"\x01"


def test_two_nodes_take_two_slots_in_the_trainers_order():
    m = machine(POD, bytes([0x07]), nodes=(0, 1, 2))
    fx.add(m, POD, RECORD, [fx.NewEffect(0x69), fx.NewEffect(8)])
    ids = [n.raw[0] for n in amigaparty.chain(
        m, m.u32(RECORD + 0x04), 6, 10, "list")]
    assert ids == [0x2F, 0x2F, 0x2F, 0x69, 8]
    assert m.u32(POOL + 30 + 6) == POOL + 40
    assert m.read(DATA + 0x75A2 + 8, 1) == bytes([0x1F])


@pytest.mark.parametrize("change, why", [
    (dict(bitmap=bytes([0xFF]) * 27), "full"),
    (dict(count=0xD3), "slots"),
    (dict(size=12), "slots"),
    (dict(bitmap=bytes([0x01]), nodes=(0, 1)), "not a slot"),
])
def test_nothing_is_written_when_the_pool_or_list_reads_wrong(change, why):
    m = machine(SSB, **change)
    with pytest.raises(fx.EffectError, match=why):
        fx.add(m, SSB, RECORD, [fx.NewEffect(0x69)])
    assert m.written == []


def _ssb_regaining(former_ranger: int = 5) -> bytearray:
    """A human fighter 5 who left ranger at 5, with the experience for
    fighter 6: training regains the ranger."""
    rec = bytearray(340)
    rec[0x6B], rec[0x19] = 6, 16
    rec[0xAC + 2] = rec[0x88] = 5
    rec[0xB3 + 4] = former_ranger
    rec[0x89] = 5
    rec[0xC8:0xCC] = (70000).to_bytes(4, "big")
    rec[0x70], rec[0x152] = 40, 40
    return rec


class Dice:
    def randint(self, low: int, high: int) -> int:
        return high


def test_silver_blades_regaining_the_ranger_adds_0x69_and_nothing_else():
    """`0xE74A`: only once the fighter's level passes `0x089`, and only for a
    former level above 0 (`ble`, signed)."""
    plan = lv.plan(_ssb_regaining(), SSB, rng=Dice())
    assert plan.added_effects == (fx.NewEffect(0x69, 0, 0xFF, 0),)
    assert lv.plan(_ssb_regaining(), SSB, rng=Dice(),
                   effects=(0x69,)).added_effects == ()
    rec = _ssb_regaining()
    rec[0x89] = 6
    assert lv.plan(rec, SSB, rng=Dice()).added_effects == ()


def test_write_plan_adds_the_node_then_writes_the_record():
    rec = _ssb_regaining()
    m = machine(SSB, bytes([0x03]), nodes=(0, 1))
    m.put(RECORD, bytes(rec[:0x96]) + m.read(RECORD + 0x96, 4)
          + bytes(rec[0x9A:]))
    member = SimpleNamespace(address=RECORD, raw=m.read(RECORD, 340),
                             effect_nodes=(), item_nodes=())
    plan = lv.plan_member(member, SSB, rng=Dice())
    made = lv.write_plan(m, member, plan)
    assert m.read(RECORD, 340) == lv.apply_to(member.raw, plan)
    assert m.read(POOL + 20, 1) == b"\x69"
    assert m.u32(POOL + 10 + 6) == POOL + 20
    assert made[3] == (POOL + 16, (POOL + 20).to_bytes(4, "big"))


def test_write_plan_writes_nothing_over_a_record_that_changed():
    rec = _ssb_regaining()
    m = machine(SSB, bytes([0x00]))
    m.put(RECORD, bytes(rec))
    member = SimpleNamespace(address=RECORD, raw=bytes(rec),
                             effect_nodes=(), item_nodes=())
    plan = lv.plan_member(member, SSB, rng=Dice())
    m.put(RECORD + 0xAC + 2, b"\x06")
    with pytest.raises(lv.CannotLevel, match="changed"):
        lv.write_plan(m, member, plan)
    assert m.written == []


@pytest.mark.parametrize("change, why", [
    (dict(bitmap=bytes([0xFF]) * 27), "full"),
    (dict(bitmap=bytes([0x01]), nodes=(0, 1)), "not a slot"),
])
def test_write_plan_writes_nothing_when_the_pool_or_list_reads_wrong(change, why):
    rec = _ssb_regaining()
    m = machine(SSB, **change)
    m.put(RECORD + 0x96, m.read(RECORD + 0x96, 4))
    m.put(RECORD, bytes(rec[:0x96]) + m.read(RECORD + 0x96, 4)
          + bytes(rec[0x9A:]))
    member = SimpleNamespace(address=RECORD, raw=m.read(RECORD, 340),
                             effect_nodes=(), item_nodes=())
    plan = lv.plan_member(member, SSB, rng=Dice())
    assert plan.added_effects
    with pytest.raises(lv.CannotLevel, match=why):
        lv.write_plan(m, member, plan)
    assert m.written == []


def test_write_plan_drops_an_effect_already_on_the_live_chain():
    """A plan read before another press made the node must not add a second."""
    rec = _ssb_regaining()
    m = machine(SSB, bytes([0x01]), nodes=(0,))
    m.put(POOL, bytes([0x69]) + m.read(POOL + 1, 9))
    m.put(RECORD, bytes(rec[:0x96]) + m.read(RECORD + 0x96, 4)
          + bytes(rec[0x9A:]))
    member = SimpleNamespace(address=RECORD, raw=m.read(RECORD, 340),
                             effect_nodes=(), item_nodes=())
    plan = lv.plan_member(member, SSB, rng=Dice())
    assert plan.added_effects == (fx.NewEffect(0x69, 0, 0xFF, 0),)
    made = lv.write_plan(m, member, plan)
    assert made == tuple(m.written)
    assert [at for at, _ in made] == [RECORD + o for o, _ in plan.writes]
    assert m.read(DATA + 0x7618 + 8, 1) == b"\x01"


#: File offset, then the bytes there, of each instruction the pools and the
#: trainers' calls are read from: the set-up's two stores (`move.w d2,
#: g<descriptor>` and `move.w #10, g<descriptor + 2>`), the count pushed to
#: it, the constructor's `pea g<descriptor>`, and each trainer call's
#: arguments after the record (`0, 0xFF, 0` and the id) pushed in reverse.
INSTRUCTIONS = {
    SSB: ((0x1BF9C, "3942f61a397c000af61c"), (0x1D6C8, "3f3c00d4"),
          (0x12DB8, "486cf61a"),
          (0xE762, "42673f3c00ff42673f3c0069"),
          (0xE79C, "42673f3c00ff42673f3c0008")),
    POD: ((0x1BAF4, "3942f5a4397c000af5a6"), (0x1D89A, "3f3c0190"),
          (0x12FE0, "486cf5a4"),
          (0x3D8B4, "42673f3c00ff42673f3c0069"),
          (0x3D8EE, "42673f3c00ff42673f3c0008")),
}


@pytest.mark.parametrize("key", [SSB, POD])
def test_the_pools_are_where_the_executables_set_them_up(key):
    from automap import gamedisks
    from tools.amiga import amigabackstab

    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    raw = amigabackstab.executable(amigabackstab.TITLES[key])
    if raw is None:
        pytest.skip(f"no {key} executable on the Amiga disks")
    pool = fx.POOLS[key]
    disp = ((pool.descriptor - 0x7FFE) & 0xFFFF).to_bytes(2, "big").hex()
    for at, want in INSTRUCTIONS[key]:
        assert raw[at:at + len(want) // 2].hex() == want, hex(at)
    assert disp in INSTRUCTIONS[key][0][1]
    assert INSTRUCTIONS[key][1][1] == f"3f3c{pool.count:04x}"
