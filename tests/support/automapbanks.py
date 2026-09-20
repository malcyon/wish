"""Helpers `test_automapbanks` shares with the test files that reuse them."""
from __future__ import annotations

#: `CMD_BANKS_AVAILABLE`'s answer on the VICE build here, read off pool slot 0
#: on 2026-09-07.  `default` and `cpu` are the same id.
BANKS = {"default": 0, "cpu": 0, "ram": 1, "rom": 2, "io": 3, "cart": 4}

#: `$01` with the chips banked out -- what four of 1,035 polls found.
CHIPS_OUT = 0x30
#: `$01` as the game runs with the chips in.
CHIPS_IN = 0x36

#: The registers the chips held, and the ones the RAM underneath them did.
TRUE_D018, TRUE_DD00 = 0x35, 0x90          # $CC00
JUNK_D018, JUNK_DD00 = 0x0C, 0x70          # $C000, and the game is not there
TRUE_SCREEN, JUNK_SCREEN = 0xCC00, 0xC000

STATUS_ROW = 14
#: What the game is really showing: east, 16:48, square 5,2.
TRUE_STATUS = "E 16:48  5,2"
#: What the RAM under the wrongly computed screen holds.  Plausible on
#: purpose: a fix that cannot be true is refused by `_plausible` and the
#: reader falls back, where a *believable* wrong square is drawn on the map.
JUNK_STATUS = "N 03:00  9,9"


def codes(text: str) -> bytes:
    """Screen codes for *text*, which for A-Z is the letter minus $40."""
    return bytes(ord(c) - 0x40 if "A" <= c <= "Z" else ord(c)
                 for c in text.upper())


def row_at(base: int, row: int, text: str) -> dict[int, bytes]:
    return {base + row * 40: codes(text.ljust(40))}


class FakeMonitor:
    """A C64's banking over two dictionaries of bytes.

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
        self.commands: list[int] = []
        self.resumes = 0
        self.sock = None

    # -- the wire ---------------------------------------------------------

    def command(self, cmd: int, body: bytes = b"") -> bytes:
        from automap.vice import CMD_BANKS_AVAILABLE, MonitorError
        self.commands.append(cmd)
        if cmd != CMD_BANKS_AVAILABLE:
            return b""
        if not self.banks:
            raise MonitorError("unsupported")
        out = len(self.banks).to_bytes(2, "little")
        for name, bank in self.banks.items():
            raw = name.encode("ascii")
            item = bank.to_bytes(2, "little") + bytes([len(raw)]) + raw
            out += bytes([len(item)]) + item
        return out

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
            chips = io_space and (self.port1 & 0x07) in (5, 6, 7)
        source = self.chips if chips else self.ram
        for base, blob in source.items():
            if base <= addr < base + len(blob):
                return blob[addr - base]
        return 0

    def read(self, start: int, length: int, bank: int = 0,
             side_effects: int = 0) -> bytes:
        self.asked.append((start, length, bank))
        return bytes(self._byte(start + i, bank) for i in range(length))

    def peek(self, addr: int, bank: int = 0) -> int:
        return self.read(addr, 1, bank)[0]

    def write(self, start: int, data: bytes, bank: int = 0,
              side_effects: int = 0) -> None:
        self.ram[start] = bytes(data)

    def ping(self) -> None:
        pass

    def resume(self) -> None:
        self.resumes += 1

    def __enter__(self):
        import socket as _socket
        # Never connected: `ViceTarget._greet` sets a timeout on it and puts
        # it back, which is the only thing anything here asks of a socket.
        self.sock = _socket.socket()
        return self

    def __exit__(self, *exc):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        return False


def a_machine(*, port1: int = CHIPS_OUT, d011: int = 0x1B,
              ram_d011: int = 0x36,
              banks: dict[str, int] | None = None,
              status: bool = True) -> FakeMonitor:
    """The machine `#336` measured: the truth in the chips, junk under it.

    `ram_d011` defaults to the `$36` all four measured polls read out of the
    RAM under the register -- bit 5 set, so the old reader called a readable
    text screen a bitmap and answered nothing at all.
    """
    chips = {0xD011: bytes([d011]),
             0xD018: bytes([TRUE_D018]), 0xDD00: bytes([TRUE_DD00])}
    ram = {0xD011: bytes([ram_d011]), 0xD018: bytes([JUNK_D018]),
           0xDD00: bytes([JUNK_DD00])}
    if status:
        ram.update(row_at(TRUE_SCREEN, STATUS_ROW, TRUE_STATUS))
        ram.update(row_at(JUNK_SCREEN, STATUS_ROW, JUNK_STATUS))
    return FakeMonitor(port1=port1, chips=chips, ram=ram, banks=banks)
