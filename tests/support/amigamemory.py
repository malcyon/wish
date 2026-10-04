"""A synthetic Amiga memory image with an ExecBase and its `MemHeader` list."""
from __future__ import annotations

EXEC_BASE = 0x800
CHIP_HEADER = 0xA00
FAST_AT = 0x200000
FAST_END = 0x400000


def _long(value: int) -> bytes:
    return value.to_bytes(4, "big")


def header(succ: int, lower: int, upper: int) -> bytes:
    """A `MemHeader`: `ln_Succ` first, `mh_Lower` at `+0x14`, `mh_Upper` at `+0x18`."""
    out = bytearray(0x20)
    out[0:4] = _long(succ)
    out[0x14:0x18] = _long(lower)
    out[0x18:0x1C] = _long(upper)
    return bytes(out)


def machine_with_fast_ram() -> dict[int, bytes]:
    """Chip RAM at 0 and fast RAM at `$200000`, no slow RAM, as `{base: bytes}`.

    ExecBase is at `$800`, its complement beside it, and its `MemList` names
    the fast header first and the chip header second, as Exec orders them.
    """
    chip = bytearray(0x2000)
    chip[4:8] = _long(EXEC_BASE)
    chip[EXEC_BASE + 0x26:EXEC_BASE + 0x2A] = _long(~EXEC_BASE & 0xFFFFFFFF)
    list_at = EXEC_BASE + 0x142
    chip[list_at:list_at + 4] = _long(FAST_AT)
    chip[list_at + 4:list_at + 8] = _long(0)
    chip[list_at + 8:list_at + 12] = _long(CHIP_HEADER)
    chip[CHIP_HEADER:CHIP_HEADER + 0x20] = header(list_at + 4, CHIP_HEADER + 0x20,
                                                   0x80000)
    fast = header(CHIP_HEADER, FAST_AT + 0x20, FAST_END)
    return {0: bytes(chip), FAST_AT: fast}
