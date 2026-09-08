"""The screen reader has to find the screen, not assume where it is (#336).

A driven session read forty spaces off row 24 while the display was showing
`INSERT SIDE # 2, AND PRESS ANY KEY.`, so nothing answered the prompt and
every wait built on the screen sat out its whole timeout.  The arithmetic in
`automap/screen.py` was never the fault: it computes the address from `$D018`
and `$DD00` and always did.  What was wrong is **which memory those two reads
came out of**.

The binary monitor's default bank is whatever the CPU can see at that instant,
and this game spends part of every load at `$01 = $30` -- RAM everywhere, no
I/O.  Measured on pool slot 0 on 2026-09-07 over 1,035 polls of one driven
boot: four polls found `$01 = $30`, and in each of those four the default bank
answered `$D018 = $0C` and `$DD00 = $70` -- the screen at `$C000` -- where the
chips held `$79` and `$C4`, which is `$DC00`.  `$D011` read `$36` from RAM
through all four; on the first of them the chip held `$0B`, text mode with the
display blanked, so `is_bitmap` threw a readable screen away.  The other 1,031
polls agreed exactly, which is why the failure is intermittent rather than
total.

`FakeMonitor` below is a C64's banking, not a mock of the reader: `$01`
decides what the default bank shows at `$D000-$DFFF`, the io bank always shows
the chips, and the ram bank always shows RAM.  What is under test is which of
those three the reader asks.
"""

from __future__ import annotations

import pytest
from conftest import load_tools_module

D = load_tools_module("drive")
S = load_tools_module("session")

#: `MON_CMD_BANKS_AVAILABLE`'s answer on the VICE build here, read off pool
#: slot 0 on 2026-09-07.  `default` and `cpu` are the same id.
BANKS = {"default": 0, "cpu": 0, "ram": 1, "rom": 2, "io": 3, "cart": 4}

#: `$01` with the chips banked out -- what four of 1,035 polls found.
CHIPS_OUT = 0x30
#: `$01` as the game runs with the chips in.
CHIPS_IN = 0x36

PROMPT = "INSERT SIDE # 2, AND PRESS ANY KEY."


def _encode_banks(banks: dict[str, int]) -> bytes:
    body = len(banks).to_bytes(2, "little")
    for name, bank in banks.items():
        raw = name.encode("ascii")
        item = bank.to_bytes(2, "little") + bytes([len(raw)]) + raw
        body += bytes([len(item)]) + item
    return body


def _screen_codes(text: str, row: int = 24) -> dict[int, int]:
    """`{offset: screen code}` for *text*, left-aligned on *row*."""
    out = {}
    for i, ch in enumerate(text.upper()):
        code = ord(ch) - 0x40 if "A" <= ch <= "Z" else ord(ch)
        out[row * 40 + i] = code
    return out


class FakeMonitor:
    """A C64's banking over three dictionaries of bytes.

    `chips` is what the VIC, the CIAs and colour RAM answer; `ram` is what is
    underneath them.  Every read records the bank it was asked for, so a test
    can say which memory the reader believed it was reading.
    """

    host = "127.0.0.1"
    port = 6520

    def __init__(self, *, port1: int = CHIPS_IN, chips=None, ram=None,
                 banks: dict[str, int] | None = None):
        self.chips = dict(chips or {})
        self.ram = dict(ram or {})
        self.port1 = port1
        self.banks = BANKS if banks is None else banks
        self.asked: list[tuple[int, int, int]] = []

    # -- the wire ---------------------------------------------------------

    def command(self, cmd: int, body: bytes = b"") -> bytes:
        if cmd == D.CMD_BANKS_AVAILABLE:
            if not self.banks:
                raise D.MonitorError("unsupported")
            return _encode_banks(self.banks)
        raise AssertionError(f"unexpected command {cmd:#04x}")

    def _byte(self, addr: int, bank: int) -> int:
        if addr == 0x01 and bank in (self.banks.get("default", 0),
                                     self.banks.get("cpu", 0)):
            return self.port1
        io_space = 0xD000 <= addr < 0xE000
        if bank == self.banks.get("io"):
            chips = io_space
        elif bank == self.banks.get("ram"):
            chips = False
        else:                                   # default: what the CPU sees
            chips = io_space and (self.port1 & 0x07) in D.IO_IN
        return (self.chips if chips else self.ram).get(addr, 0)

    def read(self, start: int, length: int, bank: int = 0,
             side_effects: int = 0) -> bytes:
        self.asked.append((start, length, bank))
        return bytes(self._byte(start + i, bank) for i in range(length))

    def peek(self, addr: int, bank: int = 0) -> int:
        return self.read(addr, 1, bank)[0]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


#: Every loaded copy of `tools/drive.py`.  `conftest.load_tools_module`
#: imports it by path as top-level `drive`, and `tools/session.py` imports the
#: same file as `tools.drive`, so there are two module objects with two bank
#: caches -- and clearing one leaves the other holding this file's answers.
_DRIVE_COPIES = [m for m in (D, __import__("sys").modules.get("tools.drive"))
                 if m is not None]


@pytest.fixture(autouse=True)
def _forget_banks():
    """The bank ids are cached per monitor; each test gets its own machine."""
    for copy in _DRIVE_COPIES:
        copy._BANKS.clear()
    yield
    for copy in _DRIVE_COPIES:
        copy._BANKS.clear()


def registers(d018: int, dd00: int, d011: int = 0x1B) -> dict[int, int]:
    return {0xD018: d018, 0xDD00: dd00, 0xD011: d011}


# -- the arithmetic, pinned without an emulator ------------------------------
#
# This one passes before the fix as well as after it, and is here to keep the
# arithmetic from drifting rather than to demonstrate the bug.  `$DD00` bits
# 1-0 select the VIC bank *inverted*, so `%11` is bank 0 and `%00` is bank 3;
# `$D018` bits 7-4 are the offset within that bank in units of 1024.


@pytest.mark.parametrize("bank", range(4))
@pytest.mark.parametrize("offset", range(16))
def test_the_screen_address_is_computed_for_every_bank_and_every_offset(
        bank, offset):
    dd00 = 0x90 | (3 - bank)            # the high bits are somebody else's
    mon = FakeMonitor(chips=registers((offset << 4) | 0x05, dd00))
    assert D.screen_address(mon) == bank * 0x4000 + offset * 0x400


def test_the_registers_tonights_hardware_held_put_the_screen_at_cc00():
    """`$DD00 = $90`, `$D018 = $35`, read off the C64 Ultimate on 2026-09-07
    while `$0400` was being sampled and reported as a frozen screen."""
    mon = FakeMonitor(chips=registers(0x35, 0x90))
    assert D.screen_address(mon) == 0xCC00


# -- the bug -----------------------------------------------------------------


def test_the_reader_finds_the_screen_while_the_chips_are_banked_out():
    """`$01 = $30`, the state four of 1,035 polls caught.

    The junk in RAM under the registers is the pair the default bank actually
    answered on slot 0 -- `$0C` and `$70`, which computes `$C000`.
    """
    mon = FakeMonitor(
        port1=CHIPS_OUT,
        chips=registers(0x35, 0x90),                 # the truth: $CC00
        ram={0xD018: 0x0C, 0xDD00: 0x70,             # what RAM happens to hold
             **{0xCC00 + k: v for k, v in _screen_codes(PROMPT).items()}},
    )
    screen = D.read_screen(mon)
    assert screen.address == 0xCC00
    assert screen.row(24).startswith(PROMPT)
    assert screen.contains("INSERT SIDE")


def test_whether_the_screen_is_a_bitmap_is_asked_of_the_chips():
    """`$D011` is a byte of RAM in that state too, and it read `$36` -- bit 5
    set, so a bitmap -- through all four polls.

    On the first of the four the chip held `$0B`: text mode with the display
    blanked.  `Session.screen()` answers None for a bitmap, so a reading the
    driver could have used was thrown away instead.
    """
    out = FakeMonitor(port1=CHIPS_OUT,
                      chips=registers(0x15, 0xC7, d011=0x0B),
                      ram={0xD011: 0x36})
    assert D.is_bitmap(out) is False
    inn = FakeMonitor(port1=CHIPS_IN, chips=registers(0x35, 0x90, d011=0x1B))
    assert D.is_bitmap(inn) is False
    real = FakeMonitor(port1=CHIPS_OUT, chips=registers(0x79, 0xC4, d011=0x3B),
                       ram={0xD011: 0x1B})
    assert D.is_bitmap(real) is True


def test_the_screen_matrix_is_read_as_ram_even_where_the_chips_are():
    """In bitmap mode this game's matrix sits at `$DC00`, which is CIA 1.

    The VIC always fetches RAM, so the matrix has to be read from the ram bank
    however the CPU is banked -- a default-bank read there answers the CIA.
    """
    mon = FakeMonitor(
        port1=CHIPS_IN,
        # The CIA fill first: `$DD00` is inside it, and a screen matrix at
        # `$DC00` runs right over the register the bank comes from.
        chips={**{0xDC00 + k: 0x2A for k in range(1000)},
               **registers(0x75, 0x90)},
        ram={0xDC00 + k: v for k, v in _screen_codes(PROMPT).items()},
    )
    screen = D.read_screen(mon)
    assert screen.address == 0xDC00
    assert screen.row(24).startswith(PROMPT)


def test_colour_ram_comes_out_of_the_chips():
    """Colour is how every menu here finds its highlighted row, and `$D800`
    is I/O like the registers are."""
    mon = FakeMonitor(port1=CHIPS_OUT,
                      chips={**registers(0x35, 0x90),
                             **{0xD800 + i: 1 for i in range(40)}},
                      ram={0xD800 + i: 5 for i in range(40)})
    assert set(D.colour_ram(mon, 0)) == {1}
    assert len(D.colour_ram(mon)) == 1000


def test_the_reader_refuses_rather_than_answering_a_screen_it_cannot_locate():
    """With no named banks and the chips out, there is no honest answer.

    Forty spaces is the answer that caused `#336`: every caller reads it as
    "the game is showing nothing" and none of them can tell that from "I am
    pointed at the wrong memory".
    """
    mon = FakeMonitor(port1=CHIPS_OUT, banks={},
                      chips=registers(0x35, 0x90))
    with pytest.raises(D.ScreenUnreadable):
        D.read_screen(mon)
    # ...and it is still readable when the CPU can see the chips, so the
    # refusal is about the banking rather than about the missing command.
    ok = FakeMonitor(port1=CHIPS_IN, banks={}, chips=registers(0x35, 0x90))
    assert D.read_screen(ok).address == 0xCC00


def test_the_bank_ids_are_asked_for_once_per_monitor():
    """One round trip per process, not one per screen read: the ids are a
    property of the VICE build rather than of the running machine."""
    mon = FakeMonitor(chips=registers(0x35, 0x90))
    calls = []
    real = mon.command
    mon.command = lambda cmd, body=b"": (calls.append(cmd), real(cmd, body))[1]
    D.read_screen(mon)
    D.read_screen(mon)
    assert calls.count(D.CMD_BANKS_AVAILABLE) == 1


# -- what the driver does with it --------------------------------------------


class FakeSession(S.Session):
    """A `Session` whose only real part is `screen()` and what it reads."""

    def __init__(self, mon: FakeMonitor):
        self._mon = mon
        self.said: list[str] = []

    def mon(self, timeout: float = 5.0):
        return self._mon

    def log(self, *a) -> None:
        self.said.append(" ".join(str(x) for x in a))


def test_a_session_reads_the_side_prompt_with_the_chips_banked_out():
    """The screen `#336` is named for: `handle_prompt` needs to see it."""
    mon = FakeMonitor(
        port1=CHIPS_OUT,
        chips=registers(0x35, 0x90),
        ram={0xD018: 0x0C, 0xDD00: 0x70,
             **{0xCC00 + k: v for k, v in _screen_codes(PROMPT).items()}},
    )
    sess = FakeSession(mon)
    screen = sess.screen()
    assert screen is not None
    assert S.RE_GAME_SIDE.search(screen.text()) is not None
    assert S.RE_GAME_SIDE.search(screen.text()).group(1) == "2"


def test_a_session_that_cannot_locate_the_screen_says_so_and_answers_none():
    mon = FakeMonitor(port1=CHIPS_OUT, banks={}, chips=registers(0x35, 0x90))
    sess = FakeSession(mon)
    assert sess.screen() is None
    assert any("could not be located" in line for line in sess.said)
