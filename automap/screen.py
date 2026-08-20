"""Reading the C64's text screen, from anything that can read memory.

Split out of `vice.py` because none of it is VICE-specific. The screen is
40x25 screen codes wherever the VIC is currently pointed, and finding it costs
three reads of the I/O registers -- so any backend with a
`read(addr, length) -> bytes` can do it, and so can a dictionary of bytes in a
test.

`read` is passed as a callable rather than an object with a method, so a
backend that has to batch, resume or rate-limit around a burst of reads keeps
that decision to itself: `ViceTarget` hands in its monitor's raw read and
resumes once at the end, where its public `Target.read` resumes every time.
"""

from __future__ import annotations

from typing import Callable

SCREEN_COLS, SCREEN_ROWS = 40, 25
COLOUR_RAM = 0xD800

# addr, length -> bytes.
Read = Callable[[int, int], bytes]


def _peek(read: Read, addr: int) -> int:
    return read(addr, 1)[0]


def screen_address(read: Read) -> int:
    """Where the VIC is fetching characters from, right now.

    It moves: $0400 at boot, $CC00 once the game is running. Computing it each
    time is the difference between reading the screen and reading whatever used
    to be the screen.
    """
    d018 = _peek(read, 0xD018)
    dd00 = _peek(read, 0xDD00)
    bank = (~dd00 & 3) * 0x4000
    return bank + ((d018 >> 4) & 0xF) * 0x400


def is_bitmap(read: Read) -> bool:
    """Title and credit screens are bitmaps and cannot be read as text."""
    return bool(_peek(read, 0xD011) & 0x20)


_SCREEN_TO_ASCII = {}
for _c in range(256):
    _b = _c & 0x7F
    if _b == 0:
        _SCREEN_TO_ASCII[_c] = "@"
    elif 1 <= _b <= 26:
        _SCREEN_TO_ASCII[_c] = chr(ord("A") + _b - 1)
    elif 27 <= _b <= 31:
        _SCREEN_TO_ASCII[_c] = "[£]^_"[_b - 27]
    elif 32 <= _b <= 63:
        _SCREEN_TO_ASCII[_c] = chr(_b)
    else:
        _SCREEN_TO_ASCII[_c] = "."


def codes_to_text(codes: bytes) -> str:
    return "".join(_SCREEN_TO_ASCII[c] for c in codes)


class Screen:
    """One snapshot: 1000 screen codes and 1000 colour nybbles."""

    def __init__(self, codes: bytes, colours: bytes, address: int):
        self.codes = codes
        self.colours = bytes(c & 0x0F for c in colours)
        self.address = address

    def row(self, r: int) -> str:
        return codes_to_text(self.codes[r * SCREEN_COLS : (r + 1) * SCREEN_COLS])

    def rows(self) -> list[str]:
        return [self.row(r) for r in range(SCREEN_ROWS)]

    def text(self) -> str:
        return "\n".join(self.rows())

    def find(self, needle: str) -> tuple[int, int] | None:
        needle = needle.upper()
        for r, line in enumerate(self.rows()):
            c = line.find(needle)
            if c >= 0:
                return r, c
        return None

    def contains(self, needle: str) -> bool:
        return self.find(needle) is not None

    def row_colour(self, r: int) -> int:
        """The dominant colour of the non-blank characters on a row."""
        counts: dict[int, int] = {}
        for i in range(r * SCREEN_COLS, (r + 1) * SCREEN_COLS):
            if self.codes[i] not in (0x20, 0x00):
                counts[self.colours[i]] = counts.get(self.colours[i], 0) + 1
        if not counts:
            return -1
        return max(counts, key=counts.__getitem__)

    def highlighted_rows(self, colour: int = 1) -> list[int]:
        """Rows drawn in the menu highlight colour (white by default)."""
        return [r for r in range(SCREEN_ROWS) if self.row_colour(r) == colour]


def read_screen(read: Read) -> Screen:
    addr = screen_address(read)
    return Screen(read(addr, 1000), read(COLOUR_RAM, 1000), addr)


def screen_row(read: Read, row: int) -> str:
    """One row as text. Two reads instead of three, which matters on a
    backend where a round trip is a network hop."""
    base = screen_address(read)
    return codes_to_text(read(base + row * SCREEN_COLS, SCREEN_COLS))
