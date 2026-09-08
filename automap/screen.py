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

**Three reads of this screen are not ordinary memory, and saying which is
`Banks`.** `$D011`, `$D018`, `$DD00` and colour RAM at `$D800` are the chips,
and the screen matrix is RAM the VIC fetches -- and on a C64 those are two
different memories at the same addresses, chosen by `$01`. Pool of Radiance's
loader spends part of every load at `$01 = $30`, RAM everywhere and no I/O at
all, so a register read that goes through the processor's own view answers a
byte of RAM and this file computes an address nothing is displaying (`#336`,
`#421`). The arithmetic below was never the fault; which memory it was fed
was.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

SCREEN_COLS, SCREEN_ROWS = 40, 25
COLOUR_RAM = 0xD800

# addr, length -> bytes.
Read = Callable[[int, int], bytes]


@dataclass(frozen=True)
class Banks:
    """Two readers: the chips, and the RAM the VIC fetches from.

    `io` answers the VIC and CIA registers and colour RAM however the
    processor is banked. `ram` answers the screen matrix, which the VIC always
    fetches out of RAM -- in bitmap mode this game's matrix sits at `$DC00`,
    where a read through the processor's view answers CIA 1 rather than the
    screen.

    A backend that has only one memory -- a dictionary of bytes in a test, a
    machine read over a bus that cannot be told which memory to answer from --
    passes the same reader in twice, which is what `of` does for it and is
    exactly the behaviour every caller had before this existed.
    """

    io: Read
    ram: Read

    @classmethod
    def of(cls, source) -> "Banks":
        """A pair from a pair, or from one reader used for both.

        **Deliberately not from a target.** A backend says it can tell the two
        memories apart with an optional `banks()` method -- found with
        `getattr`, the way `read_fix` finds `fix` and `_burst` finds
        `read_blocks`, rather than by a wider `Target.read` that would make
        every backend pretend. Asking it is `automap.target.screen_banks`,
        which can also answer None for "I cannot locate the screen at all",
        and that answer must not quietly become a pair pointed at the wrong
        memory -- which is what this function would have to do with it.
        """
        if isinstance(source, cls):
            return source
        return cls(source, source)


def _peek(read: Read, addr: int) -> int:
    return read(addr, 1)[0]


def screen_address(banks) -> int:
    """Where the VIC is fetching characters from, right now.

    It moves: $0400 at boot, $CC00 once the game is running. Computing it each
    time is the difference between reading the screen and reading whatever used
    to be the screen.

    The two registers come out of `Banks.io`, because a read of them through
    the processor's view is a byte of RAM whenever the game has the chips
    banked out.
    """
    banks = Banks.of(banks)
    d018 = _peek(banks.io, 0xD018)
    dd00 = _peek(banks.io, 0xDD00)
    bank = (~dd00 & 3) * 0x4000
    return bank + ((d018 >> 4) & 0xF) * 0x400


def is_bitmap(banks) -> bool:
    """Title and credit screens are bitmaps and cannot be read as text.

    `$D011` is a chip register like the two above: read through the processor's
    view with the chips out it was `$36` in every instance measured on `#336`,
    bit 5 set, so a readable text screen was thrown away as a bitmap.
    """
    return bool(_peek(Banks.of(banks).io, 0xD011) & 0x20)


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


def band(codes: bytes, left: int, right: int) -> list[str]:
    """A column band, out of a block read as whole screen rows.

    The game draws in windows -- combat's messages are columns 23 to 38 of rows
    10 to 22 -- and a window is not contiguous in memory, so it is read as whole
    rows and sliced here. `right` is one past the last column, which is how the
    game itself holds it at `$03F3`.
    """
    return [codes_to_text(codes[at:at + SCREEN_COLS])[left:right]
            for at in range(0, len(codes) - SCREEN_COLS + 1, SCREEN_COLS)]


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

    def highlighted_rows(self, colour: int = 1, column: int | None = None) -> list[int]:
        """Rows drawn in the menu highlight colour (white by default)."""
        if column is not None:
            rows = []
            for r in range(SCREEN_ROWS):
                base = r * SCREEN_COLS
                if self.colours[base + column] == colour:
                    if column >= 2 and self.colours[base + column - 2] == colour:
                        continue
                    rows.append(r)
            return rows
        return [r for r in range(SCREEN_ROWS) if self.row_colour(r) == colour]


def read_screen(banks) -> Screen:
    """The whole screen: the matrix out of RAM, the colour out of the chips.

    Colour is how every menu here finds its highlighted row, and `$D800` is
    I/O like the registers are.
    """
    banks = Banks.of(banks)
    addr = screen_address(banks)
    return Screen(banks.ram(addr, 1000), banks.io(COLOUR_RAM, 1000), addr)


def screen_row(banks, row: int) -> str:
    """One row as text. Two reads instead of three, which matters on a
    backend where a round trip is a network hop."""
    banks = Banks.of(banks)
    base = screen_address(banks)
    return codes_to_text(banks.ram(base + row * SCREEN_COLS, SCREEN_COLS))
