"""The automapper has to say which memory a screen read means (#421).

The live automapper reads the VIC registers through whatever the processor can
see, so during a load it computes the screen address from a byte of RAM and
reads a screen nothing is displaying.  `tools/drive.py` was fixed for the
driver under `#336 (The screen reader goes blind on the insert-a-side prompt,
and every screen-driven recovery fails with it)`; this is the same defect on
the other side of the same arithmetic.

The measurement is `#336`'s and is not re-derived here.  Pool of Radiance's
loader spends part of every load at `$01 = $30` -- RAM everywhere and no I/O
at all.  Over 1,035 polls of one driven boot on pool slot 0, 2026-09-07, four
polls found it: in all four the processor's own view answered `$D018 = $0C`
and `$DD00 = $70`, which computes `$C000`, where the chips held the pair that
puts the screen at `$DC00`.  `$D011` read `$36` from the RAM underneath --
bit 5 set, a bitmap -- through all four, and on the first of them the chip
held `$0B`, which is text with the display blanked.

`FakeMonitor` below is a C64's banking rather than a mock of the reader:
`$01` decides what the default bank shows at `$D000-$DFFF`, the io bank always
shows the chips and the ram bank always shows RAM.  What is under test is
which of those three the automapper asks.

The shape being pinned is the decision on `#421`: `Target` did **not** grow a
bank argument, because the C64 Ultimate cannot honour one -- its DMA read
follows the processor's banking (`#375`) -- and because thirteen more places
duck-type `read(addr, length)`.  A backend that can tell the two memories
apart says so with an optional `banks()`, found with `getattr` the way `fix`
and `read_blocks` already are.
"""

from __future__ import annotations

import pytest

from automap import combatlog
from automap.screen import Banks, is_bitmap, read_screen, screen_address
from automap.target import MemoryTarget, ReplayTarget, screen_banks
from automap.vice import banked

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


def a_target(monkeypatch, mon: FakeMonitor):
    """A real `ViceTarget` over *mon*, the way `test_automap.py` does it."""
    from automap import target as target_mod
    monkeypatch.setattr(target_mod, "Monitor", lambda **kw: mon)
    return target_mod.ViceTarget()


@pytest.fixture(autouse=True)
def _forget_banks():
    """The bank ids are cached per monitor; each test gets its own machine."""
    from automap import vice
    vice._BANKS.clear()
    yield
    vice._BANKS.clear()


# -- the arithmetic, and which memory it is fed ------------------------------


def test_the_screen_address_comes_from_the_chips():
    """`$D018` and `$DD00` read through the processor's view are bytes of RAM
    for as long as the game holds `$01 = $30`."""
    mon = a_machine()
    assert screen_address(banked(mon)) == TRUE_SCREEN


def test_one_reader_still_means_read_it_both_ways():
    """A plain callable is still accepted and still means the processor's own
    view, which is what `tools/screenblind.py` measures with."""
    mon = a_machine()
    assert screen_address(mon.read) == JUNK_SCREEN
    assert Banks.of(mon.read).io == mon.read


def test_whether_the_screen_is_a_bitmap_is_asked_of_the_chips():
    """`$D011` is a chip register too, and it read `$36` -- bit 5 set, a
    bitmap -- out of RAM through all four polls `#336` caught.  The first of
    them held `$0B` in the chip: text, with the display blanked."""
    blanked = a_machine(d011=0x0B)
    assert is_bitmap(banked(blanked)) is False
    assert is_bitmap(blanked.read) is True          # the RAM underneath
    really = a_machine(d011=0x3B)
    assert is_bitmap(banked(really)) is True


def test_the_screen_matrix_is_read_as_ram_even_where_the_chips_are():
    """In bitmap mode this game's matrix sits at `$DC00`, which is CIA 1.

    The VIC always fetches RAM, so the matrix has to come out of the ram bank
    however the processor is banked -- a read through its view answers the CIA.
    """
    mon = FakeMonitor(
        port1=CHIPS_IN,
        chips={**{0xDC00: bytes(1000)},          # the CIA, mirrored to death
               0xD011: b"\x1B", 0xD018: b"\x75", 0xDD00: b"\x90",
               0xD800: bytes([1]) * 1000},
        ram=row_at(0xDC00, 24, "INSERT SIDE # 2, AND PRESS ANY KEY."),
    )
    screen = read_screen(banked(mon))
    assert screen.address == 0xDC00
    assert screen.row(24).startswith("INSERT SIDE # 2")


def test_colour_ram_comes_out_of_the_chips():
    """`$D800` is I/O like the registers are, and colour is how every menu
    here finds its highlighted row."""
    mon = a_machine()
    mon.chips[0xD800] = bytes([1]) * 1000
    mon.ram[0xD800] = bytes([5]) * 1000
    assert set(read_screen(banked(mon)).colours) == {1}


# -- what the automapper does with it ----------------------------------------


def test_a_status_line_is_read_while_the_game_has_the_chips_banked_out(
        monkeypatch):
    """The fix a player sees on the map.

    The RAM under the wrongly computed screen holds a *plausible* status line
    on purpose: `_plausible` cannot refuse `9,9` facing north, so before this
    the marker moved to a square the party was not on.
    """
    mon = a_machine()
    target = a_target(monkeypatch, mon)
    fix = target.fix()
    assert (fix.x, fix.y, fix.facing) == (5, 2, 1)
    assert fix.source == "status"
    assert fix.clock == 16 * 60 + 48


def test_the_reader_as_it_was_threw_a_readable_screen_away():
    """What the automapper did before `#421`, on the registers measured.

    `party_fix` over one reader is the whole of the old path -- `fix()` called
    it with the monitor's default-bank read -- so the defect is still
    reachable and needs nothing reverted to show.  The `$36` under `$D011` has
    bit 5 set, so the reader called a screen it could have read a bitmap and
    answered no fix at all.  On the map that is a marker that stops moving,
    which is the mild end of this and is where the four measured polls sat.
    """
    from automap.target import party_fix

    mon = a_machine()
    assert party_fix(mon.read) is None
    now = party_fix(mon.read, None, banked(mon))
    assert (now.x, now.y, now.facing) == (5, 2, 1)


def test_the_reader_as_it_was_could_answer_a_square_the_party_was_not_on():
    """And the severe end, which is a *believable* wrong square.

    The RAM under `$D011` here is `$1B` rather than the `$36` measured --
    constructed, because nothing about ordinary RAM says which it holds, and
    both bytes are ordinary RAM at that address.  With bit 5 clear the old
    reader reads on, finds `N 03:00  9,9` at the address it computed out of
    RAM, and `_plausible` cannot refuse it: the marker moves to a square the
    party is not on and the explored set is fed from it.
    """
    from automap.target import party_fix

    mon = a_machine(ram_d011=0x1B)
    was = party_fix(mon.read)
    assert (was.x, was.y, was.facing) == (9, 9, 0)
    now = party_fix(mon.read, None, banked(mon))
    assert (now.x, now.y, now.facing) == (5, 2, 1)


def test_the_registers_are_asked_of_the_io_bank_and_the_row_of_ram(monkeypatch):
    """Which bank each read named, rather than only what came back."""
    mon = a_machine()
    a_target(monkeypatch, mon).fix()
    banks = {addr: bank for addr, _, bank in mon.asked}
    assert banks[0xD018] == BANKS["io"]
    assert banks[0xDD00] == BANKS["io"]
    assert banks[0xD011] == BANKS["io"]
    assert banks[TRUE_SCREEN + STATUS_ROW * 40] == BANKS["ram"]


def test_the_whole_poll_still_costs_one_resume(monkeypatch):
    """Each resume hands the emulation ~14.3 ms of extra emulated time, so
    four of them per poll would quadruple the distortion for no extra bytes.
    Asking which memory a read means must not cost a round trip per read."""
    mon = a_machine()
    target = a_target(monkeypatch, mon)
    before = mon.resumes
    target.fix()
    assert mon.resumes == before + 1


def test_the_bank_ids_are_asked_for_once_per_monitor(monkeypatch):
    """One round trip per VICE, not one per poll: the ids are a property of
    the build rather than of the running machine."""
    from automap.vice import CMD_BANKS_AVAILABLE
    mon = a_machine()
    target = a_target(monkeypatch, mon)
    target.fix()
    target.fix()
    assert mon.commands.count(CMD_BANKS_AVAILABLE) == 1


def test_a_transport_failure_asking_for_the_banks_is_not_remembered(
        monkeypatch):
    """One bad moment at attach time must not leave a whole session reading
    the processor's own view.  A monitor that *answers* "unsupported" is a
    property of the build and is kept; a socket that fails is not."""
    from automap import vice
    mon = a_machine()
    broken = {"yes": True}
    real = mon.command

    def sometimes(cmd, body=b""):
        if broken["yes"]:
            raise OSError("timed out")
        return real(cmd, body)

    mon.command = sometimes
    assert vice.bank_ids(mon) == {}
    broken["yes"] = False
    assert vice.bank_ids(mon) == BANKS


# -- the backends that cannot say --------------------------------------------


def test_a_backend_with_one_memory_is_read_the_way_it_always_was():
    """`MemoryTarget` and `ReplayTarget` have one dictionary of bytes, so both
    readers are their `read` and nothing about them changes."""
    for target in (MemoryTarget({0x0400: b"\x01"}), ReplayTarget([])):
        pair = screen_banks(target)
        assert pair.io == target.read and pair.ram == target.read


def test_the_ultimate_does_not_claim_a_capability_it_cannot_have():
    """Its `readmem` is a DMA read on the cartridge bus, decoded through the
    `$01` the 6510 last wrote, so it cannot be told which memory to answer
    from (`#375`).  Not implementing `banks()` is its answer, and it is read
    exactly as it is today rather than being handed an argument it would have
    to ignore."""
    from wish.ultimate import UltimateTarget
    assert getattr(UltimateTarget, "banks", None) is None
    fake = UltimateTarget(host="192.0.2.1")
    pair = screen_banks(fake)
    assert pair.io == fake.read and pair.ram == fake.read


def test_a_vice_that_cannot_be_asked_answers_no_fix_rather_than_a_wrong_one(
        monkeypatch):
    """With no named banks and the chips out there is no honest answer.

    A plausible wrong square is worse than none: the map holds its last fix
    the way it does for a bitmap screen and for a menu, where a believable
    `9,9` would have been drawn and believed.
    """
    mon = a_machine(banks={})
    assert banked(mon) is None
    assert a_target(monkeypatch, mon).fix() is None


def test_a_vice_that_cannot_be_asked_still_reads_a_screen_the_cpu_can_see(
        monkeypatch):
    """The refusal is about the banking rather than about the missing
    command, so an old VICE with the chips banked in reads as it always did."""
    mon = a_machine(port1=CHIPS_IN, banks={})
    assert banked(mon) is not None
    fix = a_target(monkeypatch, mon).fix()
    assert (fix.x, fix.y) == (5, 2)


# -- the combat log ----------------------------------------------------------

LEFT, RIGHT, BOTTOM = 23, 39, 23


def a_fight(monkeypatch, message: str, *, port1: int = CHIPS_OUT,
            d011: int = 0x1B):
    """A machine in combat with one message in the panel."""
    mon = a_machine(port1=port1, d011=d011, status=False)
    mon.ram[combatlog.MODE] = bytes([combatlog.COMBAT])
    mon.ram[combatlog.WINDOW] = bytes([LEFT, RIGHT, combatlog.MESSAGE_TOP,
                                       BOTTOM])
    mon.ram[combatlog.CURSOR] = bytes([LEFT, combatlog.MESSAGE_TOP])
    band = bytearray(codes(" " * 40) * 15)
    band[LEFT:LEFT + len(message)] = codes(message)
    mon.ram[TRUE_SCREEN + combatlog.MESSAGE_TOP * 40] = bytes(band)
    # And the junk screen carries a different message, so a frame read from
    # the wrong memory cannot pass for the right one.
    junk = bytearray(codes(" " * 40) * 15)
    junk[LEFT:LEFT + 6] = codes("XXXXXX")
    mon.ram[JUNK_SCREEN + combatlog.MESSAGE_TOP * 40] = bytes(junk)
    return mon, a_target(monkeypatch, mon)


def test_the_combat_log_reads_the_band_out_of_the_screen_the_vic_shows(
        monkeypatch):
    """A first poll taken while the game had the chips out used to point the
    message band at `$C000`."""
    mon, target = a_fight(monkeypatch, "MAGNUS MISSES.")
    log = combatlog.CombatLog()
    assert log.poll(target) == []               # the locating poll
    assert log._address == TRUE_SCREEN
    log.poll(target)
    log.flush()                                 # a message is kept when the
    assert [m.text for m in log.messages] == ["MAGNUS MISSES."]  # game paints



def test_the_combat_log_asks_for_the_registers_and_the_band_by_name(
        monkeypatch):
    """Both in one burst: splitting them out would be a second resume, which
    is the cost the burst exists to avoid."""
    mon, target = a_fight(monkeypatch, "MAGNUS MISSES.")
    log = combatlog.CombatLog()
    log.poll(target)
    before = mon.resumes
    mon.asked.clear()
    log.poll(target)
    assert mon.resumes == before + 1
    banks = {addr: bank for addr, _, bank in mon.asked}
    assert banks[0xD011] == BANKS["io"]
    assert banks[TRUE_SCREEN + combatlog.MESSAGE_TOP * 40] == BANKS["ram"]


def test_the_combat_log_keeps_asking_until_it_can_locate_the_screen(
        monkeypatch):
    """`_locate` runs on the first poll and on every poll after it that
    answers None, because None leaves `_address` unset.  A title screen is
    the ordinary way in: it is a bitmap, and there is no text to read."""
    mon, target = a_fight(monkeypatch, "MAGNUS MISSES.", d011=0x3B)
    log = combatlog.CombatLog()
    log.poll(target)
    assert log._address is None
    mon.chips[0xD011] = b"\x1B"                 # the fight paints over it
    log.poll(target)
    assert log._address == TRUE_SCREEN


def test_a_screen_that_moves_is_followed_rather_than_remembered():
    """This passes before `#421` as well as after it, and is here because the
    ticket describes `_locate`'s answer as kept for the whole fight.  It is
    not: `poll` re-derives the address from its own burst every frame and
    adopts it when it has moved, at the cost of that one frame.
    """
    target = MemoryTarget({
        0xD011: b"\x1B", 0xD018: b"\x34", 0xDD00: b"\x00",   # $CC00
        combatlog.MODE: bytes([combatlog.COMBAT]),
        combatlog.WINDOW: bytes([LEFT, RIGHT, combatlog.MESSAGE_TOP, BOTTOM]),
        combatlog.CURSOR: bytes([LEFT, combatlog.MESSAGE_TOP]),
    })
    log = combatlog.CombatLog()
    log.poll(target)
    assert log._address == 0xCC00
    target.memory[0xD018] = b"\x14"                           # the screen moved
    assert log.poll(target) == []
    assert log._address == 0xC400
