"""Helpers `test_combatlog` shares with the tool that photographs the message panel."""
from __future__ import annotations

from automap import combatlog
from automap.screen import SCREEN_COLS
from automap.target import MemoryTarget

SCREEN = 0xCC00
LEFT, RIGHT, TOP, BOTTOM = combatlog.COMBAT_WINDOW


def codes(text: str) -> bytes:
    """ASCII to screen codes: the inverse of `screen._SCREEN_TO_ASCII`."""
    out = bytearray()
    for ch in text.upper():
        out.append(ord(ch) - 64 if "A" <= ch <= "Z" else ord(ch))
    return bytes(out)


def painted(rows, top: int = combatlog.MESSAGE_TOP) -> bytes:
    """Rows 10-22 of a screen, with `rows` in the message window's columns."""
    height = BOTTOM - combatlog.MESSAGE_TOP
    grid = [bytearray(b" " * SCREEN_COLS) for _ in range(height)]
    for i, line in enumerate(rows):
        at = top - combatlog.MESSAGE_TOP + i
        if 0 <= at < height:
            grid[at][LEFT:LEFT + len(line)] = codes(line)
    return b"".join(bytes(r) for r in grid)


def machine(rows=(), top: int = combatlog.MESSAGE_TOP, mode: int = 2,
            d011: int = 0x1B, delay: int = 2) -> MemoryTarget:
    return MemoryTarget({
        0xD011: bytes([d011]),
        0xD018: b"\x34",                       # screen page 3 of the bank...
        0xDD00: b"\x00",                       # ...and bank 3, so $CC00
        combatlog.MODE: bytes([mode]),
        # `INIT $09AC`'s own starting value, so a synthetic machine is a
        # machine nobody has touched the SPEED command on.
        combatlog.DELAY: bytes([delay]),
        combatlog.WINDOW: bytes([LEFT, RIGHT, top, BOTTOM]),
        combatlog.CURSOR: bytes([LEFT, top]),
        SCREEN + combatlog.MESSAGE_TOP * SCREEN_COLS: painted(rows, top),
    })
