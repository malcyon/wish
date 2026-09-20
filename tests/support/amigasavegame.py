"""Helpers `test_amigasavegame` shares with the test files that reuse them."""
from __future__ import annotations

from goldbox import amiga_port, amiga_savegame
from goldbox.amiga_savegame import (
    CURSE,
    SILVER_BLADES,
)


def fake_record(shape: amiga_port.AmigaDeltas, name: str) -> bytes:
    """A record the signature scan accepts, carrying no items or effects."""
    raw = bytearray(shape.record_size)
    raw[:len(name)] = name.encode()
    for i in range(6):
        raw[0x10 + 2 * i] = raw[0x11 + 2 * i] = 12
    return bytes(raw)


def vm_with(shape, **words) -> bytearray:
    vm = bytearray(amiga_savegame.VM_BYTES)
    for name, value in words.items():
        at = shape.vm_offset(int(name, 16)) - shape.vm_at
        vm[at:at + 2] = value.to_bytes(2, "big")
    return vm


def synthetic_curse(names=("ALPHA", "BETA")) -> bytes:
    out = bytearray([2])
    out += vm_with(CURSE, **{"0x5012": 2, "0x503E": len(names),
                             "0x49C9": 1, "0x49C8": 1, "0x49C7": 5})
    out += bytes(amiga_savegame.ECL_BYTES)
    out += (3).to_bytes(2, "big") + (14).to_bytes(2, "big") + bytes([2, 0, 0, 0])
    out += bytes([4, 2])
    for block, slot in ((1, 1), (2, 2), (3, 3)):
        out += block.to_bytes(2, "big") + slot.to_bytes(2, "big")
    out += len(names).to_bytes(2, "big")
    for n in names:
        out += fake_record(amiga_port.CURSE_DELTAS, n)
    return bytes(out)


def synthetic_silver_blades(names=("GAMMA",)) -> bytes:
    out = bytearray([1])
    out += vm_with(SILVER_BLADES, **{"0x5012": 1, "0x503E": len(names)})
    out += bytes([7, 13, 0, 0, 0, 0])
    out += bytes([4, 0])
    out += bytes.fromhex("00000001ffffffffffffffff")
    out += len(names).to_bytes(2, "big")
    for n in names:
        out += fake_record(amiga_port.SILVER_BLADES_DELTAS, n)
    return bytes(out)
