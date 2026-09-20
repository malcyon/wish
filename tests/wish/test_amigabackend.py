from __future__ import annotations

"""The patched FS-UAE as the window's backend: a probe that never connects, one
socket per emulator run, and an Amiga target kept away from C64 addresses.

`FakeSocket` answers the way `barto_gdbserver.cpp` does for the three packets
`FsuaeGdb` sends here (`qSupported`, `vCont;c`, `m`); no emulator is involved.
"""

import os
import socket

import pytest
from gamedata import synthetic_geo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from automap import amiga, live
from automap.area import OURS, RESIDENT_GEO
from automap.state import Automapper
from automap.target import MemoryTarget
from goldbox import c64_port
from goldbox.geo import BARRIERS, GRID, SOLID, WALLS_NORTH_EAST, WALLS_SOUTH_WEST, Geo
from wish import backends as bk
from wish import fsuae

BLADES = amiga.MACHINES["secret-of-the-silver-blades"]
CURSE = amiga.MACHINES["curse-of-the-azure-bonds"]
BASE = 0xC10000
POOL = c64_port.POOL_OF_RADIANCE.title

needs_proc = pytest.mark.skipif(not os.path.exists("/proc/net/tcp"),
                                reason="no /proc/net/tcp on this platform")


@pytest.fixture(autouse=True)
def fresh():
    fsuae.reset()
    yield
    fsuae.reset()


# -- the probe ----------------------------------------------------------------

def _table(tmp_path, tcp="", tcp6=""):
    head = "  sl  local_address rem_address   st tx_queue rx_queue\n"
    (tmp_path / "tcp").write_text(head + tcp)
    (tmp_path / "tcp6").write_text(head + tcp6)
    return str(tmp_path)


def _row(address: str, port: int, state: str) -> str:
    return (f"   0: {address}:{port:04X} 00000000:0000 {state} 00000000:"
            "00000000 00:00000000 00000000  1000 0 1 1 0000000000000000\n")


def test_a_loopback_listener_is_seen_in_the_kernel_table(tmp_path):
    proc = _table(tmp_path, tcp=_row("0100007F", 2345, "0A"))
    assert fsuae.listening(2345, proc=proc) is True


def test_a_listener_on_every_address_is_seen(tmp_path):
    assert fsuae.listening(2345, proc=_table(
        tmp_path, tcp=_row("00000000", 2345, "0A"))) is True
    assert fsuae.listening(2345, proc=_table(
        tmp_path, tcp6=_row("0" * 32, 2345, "0A"))) is True


@pytest.mark.parametrize("row", [
    _row("0100007F", 2345, "01"),           # a connection, not a listener
    _row("0100007F", 2346, "0A"),           # another port
    _row("0A00A8C0", 2345, "0A"),           # a LAN address the fork never binds
])
def test_anything_else_is_not_the_emulator(tmp_path, row):
    assert fsuae.listening(2345, proc=_table(tmp_path, tcp=row)) is False


def test_no_proc_is_a_no_and_not_an_error(tmp_path):
    assert fsuae.listening(2345, proc=str(tmp_path / "nothing")) is False


def test_the_default_port_is_the_transports_own(tmp_path):
    proc = _table(tmp_path, tcp=_row("0100007F", amiga.FSUAE_PORT, "0A"))
    assert fsuae.listening(proc=proc) is True


@needs_proc
def test_a_real_listener_is_seen_and_the_probe_opens_no_socket(monkeypatch):
    """The guard on the whole feature: a probing connect can end the run.

    The fork closes its *listening* socket when a client goes, so the probe has
    to answer from the kernel's table. Every way of making a socket is
    forbidden while it runs.
    """
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]

        def forbidden(*_a, **_k):
            raise AssertionError("the probe opened a socket")

        monkeypatch.setattr(socket, "create_connection", forbidden)
        monkeypatch.setattr(socket, "socket", forbidden)
        assert fsuae.listening(port) is True

    monkeypatch.undo()
    assert fsuae.listening(port) is False


# -- connect() ----------------------------------------------------------------

class FakeSocket:
    """The three packets the transport sends, answered from `memory`."""

    def __init__(self, memory: dict[int, bytes] | None = None):
        self.memory = dict(memory or {})
        self.received: list[str] = []
        self.gone = False
        #: Replies are held back while this is True, and `release()` delivers
        #: them, late, the way an emulator paused behind its menu does.
        self.mute = False
        self.closed = False
        self._late = bytearray()
        self._out = bytearray()

    def settimeout(self, _seconds): pass

    def close(self): self.closed = True

    def release(self) -> None:
        self._out += self._late
        self._late = bytearray()

    @staticmethod
    def _frame(body: str) -> bytes:
        return f"${body}#{sum(body.encode('latin-1')) & 0xFF:02x}".encode()

    def sendall(self, data: bytes) -> None:
        body = data[1:-3].decode("latin-1")
        self.received.append(body)
        self._out += b"+"
        if body.startswith("vCont"):
            return
        out = self._late if self.mute else self._out
        if body.startswith("qSupported"):
            out += self._frame("PacketSize=512;")
        elif body.startswith("m"):
            addr, _, length = body[1:].partition(",")
            at, size = int(addr, 16), int(length, 16)
            reply = bytearray(size)
            for base, blob in self.memory.items():
                lo, hi = max(at, base), min(at + size, base + len(blob))
                if lo < hi:
                    reply[lo - at:hi - at] = blob[lo - base:hi - base]
            (self._late if self.mute else self._out).extend(
                self._frame(bytes(reply).hex()))

    def recv(self, length: int) -> bytes:
        if self.gone:
            return b""
        if not self._out:
            raise TimeoutError("nothing to read")
        out, self._out = bytes(self._out[:length]), self._out[length:]
        return out

    def sweeps(self) -> int:
        return sum(1 for body in self.received if body.startswith("mc00000,"))


class Opener:
    def __init__(self, sock: FakeSocket):
        self.sock, self.calls = sock, 0

    def __call__(self):
        self.calls += 1
        return self.sock


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def later(self):
        self.now += fsuae.SWEEP_EVERY


def loaded(machine: amiga.AmigaMachine, at: int = BASE) -> dict[int, bytes]:
    data = bytearray(0x8000)
    data[machine.anchor_offset:machine.anchor_offset + len(machine.anchor)] = \
        machine.anchor
    return {at: bytes(data)}


def test_a_running_title_gives_a_target_at_its_own_base():
    opener = Opener(FakeSocket(loaded(BLADES)))
    target = fsuae.connect(opener=opener, clock=Clock())
    assert isinstance(target, amiga.AmigaTarget)
    assert target.layout is BLADES
    assert target.data_base == BASE
    assert target.halts_on_read is False


def test_the_machine_is_told_to_run_before_anything_is_read():
    sock = FakeSocket(loaded(BLADES))
    fsuae.connect(opener=Opener(sock), clock=Clock())
    assert sock.received[:2] == ["qSupported", "vCont;c"]


def test_a_title_that_has_not_loaded_keeps_the_one_socket():
    """The retry that costs one packet, not a second socket."""
    sock, clock = FakeSocket(), Clock()
    opener = Opener(sock)
    with pytest.raises(amiga.FsuaeError, match="none of the titles"):
        fsuae.connect(opener=opener, clock=clock)
    sock.memory = loaded(BLADES)
    clock.later()
    assert fsuae.connect(opener=opener, clock=clock).layout is BLADES
    assert opener.calls == 1


def test_the_sweep_is_not_repeated_inside_its_interval():
    sock, clock = FakeSocket(), Clock()
    opener = Opener(sock)
    with pytest.raises(amiga.FsuaeError):
        fsuae.connect(opener=opener, clock=clock)
    with pytest.raises(amiga.FsuaeError, match="no more than one"):
        fsuae.connect(opener=opener, clock=clock)
    assert sock.sweeps() == 1


def test_a_found_title_is_not_swept_for_again():
    sock, clock = FakeSocket(loaded(BLADES)), Clock()
    opener = Opener(sock)
    fsuae.connect(opener=opener, clock=clock)
    clock.later()
    again = fsuae.connect(opener=opener, clock=clock)
    assert (opener.calls, sock.sweeps()) == (1, 1)
    assert again.data_base == BASE


def test_two_titles_in_memory_are_refused_and_both_are_named():
    memory = loaded(BLADES)
    memory.update(loaded(CURSE, at=0xC30000))
    with pytest.raises(amiga.FsuaeError) as raised:
        fsuae.connect(opener=Opener(FakeSocket(memory)), clock=Clock())
    assert BLADES.title in str(raised.value)
    assert CURSE.title in str(raised.value)


def test_a_read_timeout_does_not_cost_the_socket():
    """One slow frame must not become a second connection, which the fork will
    not accept, and the late reply must not become the next read's answer."""
    sock, clock = FakeSocket(loaded(BLADES)), Clock()
    opener = Opener(sock)
    fsuae.connect(opener=opener, clock=clock)
    sock.mute = True
    with pytest.raises(amiga.FsuaeError):
        fsuae._transport.read_memory(0xC00000, 16)
    sock.mute = False
    sock.release()                  # the emulator was only paused
    clock.later()
    target = fsuae.connect(opener=opener, clock=clock)
    assert opener.calls == 1
    assert fsuae._transport.lost is False and sock.closed is False
    assert target.read(BASE, 32) == sock.memory[BASE][:32]


def test_a_second_port_gets_its_own_socket():
    first, second = FakeSocket(loaded(BLADES)), FakeSocket(loaded(BLADES))
    clock = Clock()
    fsuae.connect(port=2345, opener=Opener(first), clock=clock)
    other = Opener(second)
    fsuae.connect(port=6525, opener=other, clock=clock)
    assert other.calls == 1
    assert first.closed is True
    assert fsuae._port == 6525


def test_the_default_port_and_its_own_number_are_one_connection():
    sock, clock = FakeSocket(loaded(BLADES)), Clock()
    opener = Opener(sock)
    fsuae.connect(opener=opener, clock=clock)
    fsuae.connect(port=amiga.FSUAE_PORT, opener=opener, clock=clock)
    assert opener.calls == 1


def test_a_reset_that_loads_another_title_is_noticed():
    """The same socket, a different game in memory."""
    sock, clock = FakeSocket(loaded(BLADES)), Clock()
    opener = Opener(sock)
    assert fsuae.connect(opener=opener, clock=clock).layout is BLADES
    sock.memory = loaded(CURSE, at=0xC30000)
    clock.later()
    target = fsuae.connect(opener=opener, clock=clock)
    assert (target.layout, target.data_base) == (CURSE, 0xC30000)
    assert opener.calls == 1 and sock.closed is False


def test_the_same_title_at_another_base_is_noticed():
    sock, clock = FakeSocket(loaded(BLADES)), Clock()
    opener = Opener(sock)
    fsuae.connect(opener=opener, clock=clock)
    sock.memory = loaded(BLADES, at=0xC30000)
    clock.later()
    assert fsuae.connect(opener=opener, clock=clock).data_base == 0xC30000


def test_a_title_that_has_gone_from_memory_keeps_the_transport():
    """The player quit to the shell: wait for the next game, on this socket."""
    sock, clock = FakeSocket(loaded(BLADES)), Clock()
    opener = Opener(sock)
    fsuae.connect(opener=opener, clock=clock)
    sock.memory = {}
    clock.later()
    with pytest.raises(amiga.FsuaeError, match="none of the titles"):
        fsuae.connect(opener=opener, clock=clock)
    assert sock.closed is False
    sock.memory = loaded(CURSE)
    clock.later()
    assert fsuae.connect(opener=opener, clock=clock).layout is CURSE
    assert opener.calls == 1


def test_a_title_that_is_still_there_costs_one_small_read_and_no_sweep():
    sock, clock = FakeSocket(loaded(BLADES)), Clock()
    opener = Opener(sock)
    fsuae.connect(opener=opener, clock=clock)
    before = len(sock.received)
    fsuae.connect(opener=opener, clock=clock)
    assert len(sock.received) == before + 1
    assert sock.sweeps() == 1


def test_one_title_at_two_bases_is_refused_and_both_are_named():
    memory = loaded(BLADES)
    memory.update(loaded(BLADES, at=0xC30000))
    with pytest.raises(amiga.FsuaeError,
                       match="more than one place") as raised:
        fsuae.connect(opener=Opener(FakeSocket(memory)), clock=Clock())
    assert "0xc10000" in str(raised.value)
    assert "0xc30000" in str(raised.value)


def test_a_connection_the_emulator_dropped_is_replaced():
    sock, clock = FakeSocket(loaded(BLADES)), Clock()
    opener = Opener(sock)
    fsuae.connect(opener=opener, clock=clock)
    sock.gone = True
    with pytest.raises(amiga.FsuaeError):
        fsuae._transport.read_memory(0xC00000, 16)
    assert fsuae._transport.lost is True

    sock.gone = False
    sock._out.clear()              # a new connection has nothing pending
    fsuae.connect(opener=opener, clock=clock)
    assert opener.calls == 2


def test_a_refused_socket_leaves_nothing_cached():
    def refuse():
        raise ConnectionRefusedError("nothing is listening")

    with pytest.raises(amiga.FsuaeError):
        fsuae.connect(opener=refuse, clock=Clock())
    assert fsuae._transport is None


# -- a target that is not a C64 is never handed to the C64's readers ----------

def walled_geo() -> Geo:
    planes = bytearray(synthetic_geo())
    for y in range(GRID):
        for x in range(GRID):
            at = y * GRID + x
            if x % 4 == 0 and x:
                planes[WALLS_SOUTH_WEST + at] |= 1
                planes[WALLS_NORTH_EAST + at - 1] |= 1
                planes[BARRIERS + at] |= SOLID << 6
    return Geo(bytes(planes))


class NotAC64(MemoryTarget):
    """A machine carrying the right map at the C64's resident address, so the
    title check says OURS -- the case in which nothing else stops the window."""

    c64_memory = False


def window_on(target):
    from PyQt6.QtWidgets import QApplication, QMainWindow
    QApplication.instance() or QApplication([])

    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    maps = {"GEO00": walled_geo()}
    return AutomapBinding(root, Automapper(target, maps, title=POOL))


def machine(cls):
    from automap import c64
    return cls({0xD011: bytes([0x1B]), 0xD018: bytes([0x15]),
                0xDD00: bytes([0x17]), c64.DEFAULT.live_position: bytes((4, 5, 0)),
                RESIDENT_GEO: walled_geo().to_bytes()})


@pytest.fixture
def notes_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))


def ticked(window, times: int = 24):
    for _ in range(times):
        window.tick()
    return window


def test_a_c64_still_gets_the_bars_and_the_roster_read(notes_elsewhere,
                                                       monkeypatch):
    """The control: without it the two tests below would pass for a gate that
    is always shut."""
    reads = []
    monkeypatch.setattr(live, "read_blocks",
                        lambda *a, **k: reads.append(a) or (b"", b""))
    target = machine(MemoryTarget)
    window = ticked(window_on(target))
    assert window.fasttravel_bar.target is target
    assert reads


def test_an_amiga_is_not_handed_to_the_roster_or_the_bars(notes_elsewhere,
                                                          monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("the C64's roster was read off a 68000")

    monkeypatch.setattr(live, "read_blocks", forbidden)
    window = ticked(window_on(machine(NotAC64)))

    assert window.mapper.title_check is OURS
    assert window.fasttravel_bar.target is None
    assert window.actions_bar.target is None
    assert not any(button.isEnabled()
                   for button in window.actions_bar.buttons.values())
    assert window.fasttravel_bar.button.isEnabled() is False


def test_an_amiga_is_never_read_for_a_fight(notes_elsewhere, monkeypatch):
    from automap import combat

    def forbidden(*_a, **_k):
        raise AssertionError("a fight was read off a 68000")

    monkeypatch.setattr(combat, "read_battle", forbidden)
    window = window_on(machine(NotAC64))
    assert window.poll_battle() is False
    assert window.battle is None


# -- the row, behind WISH_EXPERIMENTAL_AMIGA_FSUAE ----------------------------

def test_the_amiga_row_is_absent_by_default(monkeypatch):
    """Unset is the shipped state: no entry in the list, not merely one that
    cannot connect."""
    monkeypatch.delenv(bk.AMIGA_FSUAE_ENV, raising=False)
    assert bk.amiga_fsuae_enabled() is False
    assert [b.name for b in bk.backends()] == ["VICE"]


@pytest.mark.parametrize("value", ["0", "off", "false", "no", "", "junk"])
def test_a_forgotten_setting_does_not_turn_the_amiga_row_on(monkeypatch, value):
    monkeypatch.setenv(bk.AMIGA_FSUAE_ENV, value)
    assert bk.amiga_fsuae_enabled() is False
    assert [b.name for b in bk.backends()] == ["VICE"]


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_the_amiga_row_appears_when_the_flag_is_set(monkeypatch, value):
    monkeypatch.setenv(bk.AMIGA_FSUAE_ENV, value)
    assert bk.amiga_fsuae_enabled() is True
    row, = [b for b in bk.backends() if b.name != "VICE"]
    assert row.name == "Amiga (FS-UAE)"
    assert row.setup_hint == ("Run the game in grahambates' fork of FS-UAE, "
                              "not stock FS-UAE.")


def test_the_amiga_row_probes_without_connecting_and_opens_the_cached_socket(
        monkeypatch):
    monkeypatch.setenv(bk.AMIGA_FSUAE_ENV, "1")
    row = bk.backends()[-1]
    assert row.probe is fsuae.listening
    assert row.connect is fsuae.connect
    assert row.disturbs is False
    assert row.verified is True


def test_the_two_flags_are_independent(monkeypatch):
    monkeypatch.setenv(bk.AMIGA_FSUAE_ENV, "1")
    monkeypatch.delenv(bk.ULTIMATE_ENV, raising=False)
    assert [b.name for b in bk.backends()] == ["VICE", "Amiga (FS-UAE)"]
    monkeypatch.setenv(bk.ULTIMATE_ENV, "1")
    assert [b.name for b in bk.backends()] == ["VICE", "Ultimate",
                                               "Amiga (FS-UAE)"]
