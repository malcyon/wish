"""`route_pool.sample` reads all 64 slots of each running-effect array.

A converted running effect can land in either of the last two slots (62/63),
so a reader that only sees the first 16 bytes of a 64-byte array would report
an empty party even while an effect is running.
"""

from __future__ import annotations

from goldbox import effects
from tools.c64 import route_pool as E


class FakeMemory:
    """A flat 64K image, read the way `Session.mon()`'s `m` is read."""

    def __init__(self):
        self.mem = bytearray(0x10000)

    def read(self, addr: int, length: int) -> bytes:
        return bytes(self.mem[addr:addr + length])


def _planted(slot: int) -> FakeMemory:
    m = FakeMemory()
    m.mem[E.SAVE0_LOAD + effects.EFFECT_ID_OFFSET + slot] = 0x11
    m.mem[E.SAVE0_LOAD + effects.EFFECT_OWNER_OFFSET + slot] = 0x22
    m.mem[E.SAVE0_LOAD + effects.EFFECT_DURATION_OFFSET + slot] = 0x33
    m.mem[E.SAVE0_LOAD + effects.EFFECT_MAGNITUDE_OFFSET + slot] = 0x44
    return m


def test_sample_reads_a_converted_effect_in_the_last_two_slots():
    for slot in (62, 63):
        m = _planted(slot)
        result = E.sample(m)
        assert result["id"][slot] == 0x11
        assert result["owner"][slot] == 0x22
        assert result["duration"][slot] == 0x33
        assert result["magnitude"][slot] == 0x44
        assert len(result["id"]) == 0x40
        assert len(result["owner"]) == 0x40
        assert len(result["duration"]) == 0x40
        assert len(result["magnitude"]) == 0x40
