"""`automap.amiga.FsuaeGdb`: reading a patched FS-UAE over its GDB port.

Every test here replaces the one thing that touches an emulator -- the socket
-- with a fake that answers the way `src/barto_gdbserver.cpp` answers, read
off the fork `grahambates/fs-uae`, branch `remote_debugger_barto`:

* a packet is `$<body>#<two hex checksum digits>`, and the server verifies the
  checksum before it looks at the body (`handle_packet`, the `cksum` loop);
* it acks with `+` and never waits for an ack of its own -- the only place it
  reads ours is the loop at the head of `handle_packet` that discards `+` and
  `-`;
* `vCont;c` is acked and **not** answered with a packet, so a client that
  waited for one would hang;
* `m<addr>,<len>` answers hex, or `E01` for the whole read if any byte in the
  range is not readable.

What no fake can stand in for is that the machine keeps running while it
answers. That is a measurement on a live emulator and it is on
`#464 (Can the automapper follow a live FS-UAE game on Linux, so Wish and the
Amiga game run on one machine?)`.
"""

from __future__ import annotations

import pathlib
import re
import socket

import pytest

from automap import amiga

BLADES = amiga.MACHINES["secret-of-the-silver-blades"]
BASE = 0xC10000

#: What this build actually advertises, taken from its own source.
GREETING = ("PacketSize=512;BreakpointCommands+;swbreak+;hwbreak+;"
            "QStartNoAckMode+;vContSupported+;")


class FakeAmiga:
    """The half of the fork's GDB server this transport talks to."""

    def __init__(self, memory: dict[int, bytes] | None = None):
        #: `{base: bytes}`. Anything outside every block reads as zero, which
        #: is what a machine with memory there does.
        self.memory = dict(memory or {})
        #: Addresses the server refuses, so `E01` can be provoked.
        self.unreadable: set[int] = set()
        #: Every packet body the client sent, in order.
        self.received: list[str] = []
        #: Frames the client sent, raw, so a checksum can be checked.
        self.frames: list[bytes] = []
        #: Packets to send *before* the next reply, as the guest's own console
        #: output arrives.
        self.chatter: list[str] = []
        self.closed = False
        #: Made True to answer as a server that has dropped the connection.
        self.gone = False
        #: Made True to hold every reply back, as an emulator paused behind its
        #: own menu does. `arrive()` then delivers them all at once, late.
        self.mute = False
        self._late = bytearray()
        #: Every value the transport gave `settimeout`, in order.
        self.timeouts: list[float] = []
        self._out = bytearray()

    # -- the socket surface ---------------------------------------------

    def settimeout(self, seconds) -> None:
        self.timeouts.append(seconds)

    def arrive(self) -> None:
        """The replies that were held back reach the socket."""
        self._out += self._late
        self._late = bytearray()

    def close(self) -> None:
        self.closed = True

    def sendall(self, data: bytes) -> None:
        self.frames.append(data)
        assert data.startswith(b"$") and data[-3:-2] == b"#", data
        body = data[1:-3].decode("latin-1")
        want = f"{sum(body.encode('latin-1')) & 0xFF:02x}"
        assert data[-2:].decode() == want, f"checksum {data[-2:]!r} != {want}"
        self.received.append(body)
        self._out += b"+"
        for extra in self.chatter:
            self._out += self._frame(extra)
        self.chatter = []
        reply = self.reply(body)
        if reply is not None:
            (self._late if self.mute else self._out).extend(self._frame(reply))

    def recv(self, length: int) -> bytes:
        if self.gone:
            return b""
        if not self._out:
            raise TimeoutError("nothing to read")
        out, self._out = bytes(self._out[:length]), self._out[length:]
        return out

    # -- what the server answers ----------------------------------------

    @staticmethod
    def _frame(body: str) -> bytes:
        return f"${body}#{sum(body.encode('latin-1')) & 0xFF:02x}".encode()

    def peek(self, addr: int, length: int) -> bytes:
        out = bytearray(length)
        for base, blob in self.memory.items():
            for i in range(length):
                if base <= addr + i < base + len(blob):
                    out[i] = blob[addr + i - base]
        return bytes(out)

    def reply(self, body: str) -> str | None:
        if body.startswith("qSupported"):
            return GREETING
        if body == "?":
            return "S05"
        if body.startswith("vCont;c"):
            return None                     # acked, never answered
        if body.startswith("m"):
            addr, _, length = body[1:].partition(",")
            at, size = int(addr, 16), int(length, 16)
            if any(a in self.unreadable for a in range(at, at + size)):
                return "E01"
            return self.peek(at, size).hex()
        return ""                           # the server's "not supported"


def transport(guest: FakeAmiga, **kw) -> amiga.FsuaeGdb:
    return amiga.FsuaeGdb(opener=lambda: guest, **kw)


# -- connecting ---------------------------------------------------------------


def test_connecting_greets_and_starts_the_machine():
    """The emulator sits halted in warp until a client continues it."""
    guest = FakeAmiga()
    gdb = transport(guest)
    assert guest.received == ["qSupported", "vCont;c"]
    assert gdb.greeting == GREETING


def test_resume_can_be_left_to_the_caller():
    guest = FakeAmiga()
    transport(guest, resume=False)
    assert guest.received == ["qSupported"]


def test_a_refused_connection_says_the_door_is_one_shot():
    def refuse():
        raise ConnectionRefusedError(111, "Connection refused")

    with pytest.raises(amiga.FsuaeError) as caught:
        amiga.FsuaeGdb(port=6525, opener=refuse)
    assert "6525" in str(caught.value)
    assert "closes it for good" in str(caught.value)


def test_a_lost_connection_is_not_connected():
    """`NotConnected`, so `automap/window.py` waits rather than falling over."""
    assert issubclass(amiga.FsuaeError, amiga.NotConnected)


def test_the_server_dropping_us_is_reported_as_final():
    guest = FakeAmiga()
    gdb = transport(guest)
    guest.gone = True
    with pytest.raises(amiga.FsuaeError, match="will not listen again"):
        gdb.read_memory(0xC00000, 4)


def test_closing_closes_the_socket_once():
    guest = FakeAmiga()
    gdb = transport(guest)
    gdb.close()
    assert guest.closed and gdb.sock is None
    gdb.close()                             # and again is not an error
    with pytest.raises(amiga.FsuaeError, match="closed"):
        gdb.read_memory(0xC00000, 4)


# -- packets ------------------------------------------------------------------


def test_the_checksum_is_the_low_byte_of_the_sum():
    """Verified by the fake on every frame; this pins the format itself."""
    assert amiga.FsuaeGdb._frame("m c00000,10") == b"$m c00000,10#6d"


def test_console_output_between_a_request_and_its_reply_is_skipped():
    guest = FakeAmiga({0xC00000: bytes(range(8))})
    gdb = transport(guest)
    guest.chatter = ["O48656c6c6f"]         # the guest printing "Hello"
    assert gdb.read_memory(0xC00000, 4) == b"\x00\x01\x02\x03"


def test_a_reply_beginning_with_o_is_not_console_output():
    """`O` plus an odd, non-hex payload is a reply -- `OK` is the one that
    matters, because a client that dropped it would wait for ever."""
    assert amiga._console_output("O48656c6c6f")
    assert not amiga._console_output("OK")
    assert not amiga._console_output("O")
    assert not amiga._console_output("m")


def test_no_reply_at_all_names_the_wait():
    guest = FakeAmiga()
    gdb = transport(guest)
    guest.reply = lambda body: None         # a server that answers nothing
    with pytest.raises(amiga.FsuaeError, match="no reply in"):
        gdb.read_memory(0xC00000, 4)


def test_a_reply_that_arrives_after_its_timeout_is_not_the_next_answer():
    """The player opens the emulator's menu, a poll times out, and on resume
    the late reply is sitting in the socket. GDB-remote has no request ids, so
    without a drain the 0x300-byte read below would be given 0x200's bytes.
    """
    guest = FakeAmiga({0xC00000: bytes(range(256)) * 4})
    gdb = transport(guest)
    guest.mute = True
    with pytest.raises(amiga.FsuaeError, match="no reply in"):
        gdb.read_memory(0xC00000, 0x200)
    guest.mute = False
    guest.arrive()                          # the emulator was only paused
    assert gdb.read_memory(0xC00000, 0x300) == guest.peek(0xC00000, 0x300)


def test_a_late_reply_of_the_same_length_is_not_taken_for_the_next_one():
    """The worse case: the length check cannot catch it, so the stale bytes
    would be returned as if they were the address asked for."""
    guest = FakeAmiga({0xC00000: bytes([1]) * 8, 0xC00100: bytes([2]) * 8})
    gdb = transport(guest)
    guest.mute = True
    with pytest.raises(amiga.FsuaeError):
        gdb.read_memory(0xC00000, 8)
    guest.mute = False
    guest.arrive()
    assert gdb.read_memory(0xC00100, 8) == bytes([2]) * 8


def test_a_timeout_does_not_end_the_connection():
    """`lost` is for a connection that failed; a slow frame is not that."""
    guest = FakeAmiga()
    gdb = transport(guest)
    guest.mute = True
    with pytest.raises(amiga.FsuaeError):
        gdb.read_memory(0xC00000, 4)
    with pytest.raises(amiga.FsuaeError):
        gdb.read_memory(0xC00000, 4)
    assert gdb.lost is False and guest.closed is False


def test_a_late_reply_and_then_a_closed_connection_is_reported_as_lost():
    guest = FakeAmiga()
    gdb = transport(guest)
    guest.mute = True
    with pytest.raises(amiga.FsuaeError):
        gdb.read_memory(0xC00000, 4)
    guest.gone = True
    with pytest.raises(amiga.FsuaeError, match="closed the connection"):
        gdb.read_memory(0xC00000, 4)
    assert gdb.lost is True


def test_a_failing_socket_marks_the_connection_lost():
    guest = FakeAmiga()
    gdb = transport(guest)

    def broken(_length):
        raise ConnectionResetError(104, "Connection reset by peer")

    guest.recv = broken
    with pytest.raises(amiga.FsuaeError, match="connection failed"):
        gdb.read_memory(0xC00000, 4)
    assert gdb.lost is True


def test_a_handshake_that_times_out_closes_the_socket_it_opened():
    """Nobody else holds it: the constructor raised, so no caller can close it."""
    guest = FakeAmiga()
    guest.mute = True
    with pytest.raises(amiga.FsuaeError, match="no reply in"):
        transport(guest)
    assert guest.closed is True


def test_a_poll_sized_read_waits_a_short_time_and_a_sweep_waits_the_long_one():
    """A poll runs on the window's own thread; a paused emulator must not cost
    it twenty seconds."""
    guest = FakeAmiga()
    gdb = transport(guest)
    assert guest.timeouts[0] == amiga.FsuaeGdb.TIMEOUT   # the handshake
    guest.timeouts.clear()
    gdb.read_memory(0xC00000, 0x400)
    assert guest.timeouts == [amiga.FsuaeGdb.POLL_TIMEOUT]
    guest.timeouts.clear()
    gdb.read_memory(0xC00000, 0x80000)
    assert guest.timeouts == [amiga.FsuaeGdb.TIMEOUT]
    assert amiga.FsuaeGdb.POLL_TIMEOUT < amiga.FsuaeGdb.TIMEOUT


def test_the_targets_reads_use_the_poll_timeout():
    guest = FakeAmiga(party_memory())
    tgt = amiga.AmigaTarget(transport(guest), BLADES, data_base=BASE)
    guest.timeouts.clear()
    tgt.fix()
    assert guest.timeouts
    assert set(guest.timeouts) == {amiga.FsuaeGdb.POLL_TIMEOUT}


def test_a_short_transport_timeout_is_never_lengthened_by_the_poll_one():
    guest = FakeAmiga()
    gdb = transport(guest, timeout=0.25)
    guest.timeouts.clear()
    gdb.read_memory(0xC00000, 4)
    assert guest.timeouts == [0.25]


@pytest.mark.parametrize("body", ["k", "D", "s", "S05", "\x03", "vCont;s",
                                  "vCont;t"])
def test_a_packet_that_stops_the_machine_is_refused(body):
    """Each one is a stop or a kill in the server's own dispatch."""
    guest = FakeAmiga()
    gdb = transport(guest)
    before = list(guest.received)
    with pytest.raises(ValueError, match="stops the machine or ends the run"):
        gdb.ask(body)
    assert guest.received == before


# -- reading memory -----------------------------------------------------------


def test_a_read_comes_back_as_the_bytes_asked_for():
    guest = FakeAmiga({0xC05000: b"blades.cfg"})
    gdb = transport(guest)
    assert gdb.read_memory(0xC05000, 10) == b"blades.cfg"
    assert guest.received[-1] == "mc05000,a"


def test_the_length_is_hex_like_the_address():
    guest = FakeAmiga({0: bytes(300)})
    gdb = transport(guest)
    gdb.read_memory(0x100, 256)
    assert guest.received[-1] == "m100,100"


def test_a_read_of_nothing_is_not_a_read():
    gdb = transport(FakeAmiga())
    with pytest.raises(ValueError, match="not a read"):
        gdb.read_memory(0xC00000, 0)


def test_an_unreadable_address_names_the_range():
    guest = FakeAmiga({0xC00000: bytes(16)})
    guest.unreadable = {0xC00008}
    gdb = transport(guest)
    with pytest.raises(amiga.FsuaeError, match="0xc00000"):
        gdb.read_memory(0xC00000, 16)


def test_a_reply_that_is_not_hex_is_reported_with_what_came_back():
    guest = FakeAmiga()
    gdb = transport(guest)
    guest.reply = lambda body: "OK"          # and `OK` is not console output
    with pytest.raises(amiga.FsuaeError, match="not hex"):
        gdb.read_memory(0xC00000, 4)


def test_a_short_reply_is_counted_rather_than_padded():
    guest = FakeAmiga()
    gdb = transport(guest)
    guest.reply = lambda body: "0011"
    with pytest.raises(amiga.FsuaeError, match="asked for 4 bytes"):
        gdb.read_memory(0xC00000, 4)


def test_half_a_megabyte_comes_back_in_one_packet():
    """`PacketSize=512` is what the server advertises, not what it writes."""
    blob = bytes(range(256)) * 2048
    guest = FakeAmiga({0xC00000: blob})
    gdb = transport(guest)
    assert gdb.read_memory(0xC00000, len(blob)) == blob
    assert guest.received[-1] == "mc00000,80000"


# -- the target over it -------------------------------------------------------


def party_memory(x: int = 5, y: int = 9, facing: int = 6) -> dict[int, bytes]:
    """A machine with Silver Blades loaded at `BASE` and a party standing."""
    data = bytearray(0x8000)
    data[BLADES.anchor_offset:BLADES.anchor_offset + len(BLADES.anchor)] = \
        BLADES.anchor
    data[BLADES.party_x] = x
    data[BLADES.party_y] = y
    data[BLADES.party_facing] = facing
    data[BLADES.geo_pointer:BLADES.geo_pointer + 4] = (
        (0xC07000).to_bytes(4, "big"))
    return {BASE: bytes(data), 0xC07000: bytes(0x400)}


def test_the_target_takes_the_transport_s_word_that_nothing_halts():
    guest = FakeAmiga()
    tgt = amiga.AmigaTarget(transport(guest), BLADES)
    assert amiga.FsuaeGdb.halts_machine is False
    assert tgt.halts_on_read is False


def test_read_blocks_asks_for_the_memory_and_names_no_file():
    """The shape difference: GDB-remote answers memory in the reply.

    So there is no `S <file> <addr> <n>`, no dump file and no token -- and the
    check for that is that neither ever goes out on the wire.
    """
    guest = FakeAmiga({0xC00000: b"first", 0xC01000: b"second"})
    tgt = amiga.AmigaTarget(transport(guest), BLADES)
    assert tgt.read_blocks([(0xC00000, 5), (0xC01000, 6)]) == [b"first",
                                                               b"second"]
    assert guest.received[-2:] == ["mc00000,5", "mc01000,6"]
    assert not any(body.startswith("S") for body in guest.received)


def test_read_blocks_still_refuses_a_read_of_nothing():
    guest = FakeAmiga({0xC00000: b"first"})
    tgt = amiga.AmigaTarget(transport(guest), BLADES)
    with pytest.raises(ValueError, match="not a read"):
        tgt.read_blocks([(0xC00000, 5), (0xC01000, 0)])


def test_a_block_naming_a_memory_is_read_the_same_way():
    """The C64's callers pass `(addr, length, "io")`; there is one memory."""
    guest = FakeAmiga({0xC00000: b"first"})
    tgt = amiga.AmigaTarget(transport(guest), BLADES)
    assert tgt.read_blocks([(0xC00000, 5, "io")]) == [b"first"]


def test_the_capability_is_not_the_pipe_s_capped_reader():
    """`WinuaePipe.memory` must not be mistaken for this.

    It reads through the debugger's `m`, is capped at 3 KB, and stops printing
    for good after about 500 lines. A capability check that matched it would
    route every Amiga poll through the one reader that runs out.
    """
    assert not hasattr(amiga.WinuaePipe, "read_memory")
    assert not hasattr(amiga.WinuaeDebugger, "read_memory")
    assert hasattr(amiga.FsuaeGdb, "read_memory")


def test_writing_says_the_build_has_no_write_packet():
    guest = FakeAmiga()
    tgt = amiga.AmigaTarget(transport(guest), BLADES)
    with pytest.raises(amiga.GuestError, match="no memory-write packet"):
        tgt.write(0xC00000, b"\x01")
    assert not any(body.startswith("W") for body in guest.received)


def test_locate_finds_the_data_hunk_through_the_socket():
    guest = FakeAmiga(party_memory())
    tgt = amiga.AmigaTarget(transport(guest), BLADES)
    assert tgt.locate() == BASE
    # The slow-memory region is swept first and the anchor is in it, so the
    # chip region is never asked for.
    assert guest.received[-1] == "mc00000,80000"


def test_a_fix_comes_off_the_party_globals():
    guest = FakeAmiga(party_memory(x=5, y=9, facing=6))
    tgt = amiga.AmigaTarget(transport(guest), BLADES, data_base=BASE)
    got = tgt.fix()
    assert (got.x, got.y, got.facing, got.source) == (5, 9, 3, "memory")


def test_no_fix_when_the_engine_holds_nothing_a_party_could_be_at():
    guest = FakeAmiga(party_memory(x=99, y=99, facing=0))
    tgt = amiga.AmigaTarget(transport(guest), BLADES, data_base=BASE)
    assert tgt.fix() is None


def test_the_resident_map_pointer_is_dereferenced():
    guest = FakeAmiga(party_memory())
    tgt = amiga.AmigaTarget(transport(guest), BLADES, data_base=BASE)
    assert tgt.resident_geo_address() == 0xC07000
    assert len(tgt.geo()) == 0x400


def test_no_map_is_resident_before_an_area_loads():
    memory = party_memory()
    data = bytearray(memory[BASE])
    data[BLADES.geo_pointer:BLADES.geo_pointer + 4] = bytes(4)
    memory[BASE] = bytes(data)
    tgt = amiga.AmigaTarget(transport(FakeAmiga(memory)), BLADES,
                            data_base=BASE)
    assert tgt.resident_geo_address() is None
    assert tgt.geo() is None


# -- the socket the tool opens ------------------------------------------------


def test_the_default_port_is_the_fork_s_own():
    """`#define DEFAULT_PORT 2345` in `barto_gdbserver.cpp`."""
    assert amiga.FSUAE_PORT == 2345


def test_the_real_opener_is_a_loopback_socket(monkeypatch):
    """The server binds 127.0.0.1 and nothing else, so nothing else is tried."""
    asked = []

    def fake_create_connection(address, timeout=None):
        asked.append((address, timeout))
        return FakeAmiga()

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    amiga.FsuaeGdb(port=6525)
    assert asked == [(("127.0.0.1", 6525), amiga.FsuaeGdb.CONNECT_TIMEOUT)]


# -- the command line ---------------------------------------------------------

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

from goldbox.geo import Geo  # noqa: E402
from tests.gamedata import synthetic_geo  # noqa: E402
from tools.amiga import fsuaegdb  # noqa: E402

POD = amiga.MACHINES["pools-of-darkness"]


def pod_memory(pointer_at: int, target: int, payload: dict[int, bytes]
               ) -> dict[int, bytes]:
    """A machine with a 32-bit pointer at data-hunk offset `pointer_at`."""
    data = bytearray(0x8000)
    data[POD.anchor_offset:POD.anchor_offset + len(POD.anchor)] = POD.anchor
    data[pointer_at:pointer_at + 4] = target.to_bytes(4, "big")
    memory = {BASE: bytes(data)}
    memory.update(payload)
    return memory


def located(memory: dict[int, bytes]):
    guest = FakeAmiga(memory)
    return guest, amiga.AmigaTarget(transport(guest), POD, data_base=BASE)


# peek


def test_peek_at_a_data_hunk_offset():
    memory = pod_memory(0x57AC, 0, {})
    memory[BASE] = memory[BASE][:0x5B12] + b"\x04" + memory[BASE][0x5B13:]
    guest, tgt = located(memory)
    assert fsuaegdb.read_spec(tgt, "+0x5B12", 1) == b"\x04"
    assert guest.received[-1] == f"m{BASE + 0x5B12:x},1"


def test_peek_dereferences_a_pointer_first():
    guest, tgt = located(pod_memory(
        0x57AC, 0xC20000, {0xC20024: bytes([1, 34, 14])}))
    assert fsuaegdb.read_spec(tgt, "*0x57AC+0x24", 3) == bytes([1, 34, 14])
    assert guest.received[-2:] == [f"m{BASE + 0x57AC:x},4", "mc20024,3"]


def test_peek_through_a_null_pointer_reports_it_without_raising():
    guest, tgt = located(pod_memory(0x57AC, 0, {}))
    assert fsuaegdb.read_spec(tgt, "*0x57AC+0x24", 3) is None
    assert fsuaegdb.peek_row(tgt, "*0x57AC+0x24", 3)["null_pointer"] is True
    # Only the pointer was read, once per call; nothing was read through it.
    assert guest.received[2:] == [f"m{BASE + 0x57AC:x},4"] * 2


def test_peek_is_refused_before_locate():
    guest = FakeAmiga()
    tgt = amiga.AmigaTarget(transport(guest), POD)
    before = list(guest.received)
    with pytest.raises(amiga.GuestError, match="locate"):
        fsuaegdb.read_spec(tgt, "+0x10", 1)
    row = fsuaegdb.peek_row(tgt, "+0x10", 1)
    assert row["hex"] is None and "locate" in row["error"]
    assert guest.received == before


@pytest.mark.parametrize("spec", ["0x10", "-0x10", "*0x10", "+0x10 +1", "w+0x10"])
def test_peek_has_no_form_but_the_two(spec):
    _, tgt = located(pod_memory(0x57AC, 0, {}))
    with pytest.raises(ValueError, match="neither"):
        fsuaegdb.read_spec(tgt, spec, 1)


def test_peeks_option_splits_a_spec_from_its_length():
    assert fsuaegdb.parse_peeks(["+0x5B12 1", "*0x57AC+0x24 3"]) == [
        ("+0x5B12", 1), ("*0x57AC+0x24", 3)]


# swap


def test_swap_sends_exactly_the_given_sequence_with_a_wait_between_keys():
    events = []
    keys = fsuaegdb.insert_floppy(
        "F12 Down*{index} Return", 2, lambda k: events.append(("key", k)),
        lambda label: events.append(("still", label)))
    assert keys == ["F12", "Down", "Down", "Return"]
    assert events == [("key", "F12"), ("still", "swap2-0"),
                      ("key", "Down"), ("still", "swap2-1"),
                      ("key", "Down"), ("still", "swap2-2"),
                      ("key", "Return"), ("still", "swap2-3")]


def test_swap_without_a_sequence_names_the_pending_measurement():
    pressed = []
    with pytest.raises(NotImplementedError, match="still being measured"):
        fsuaegdb.insert_floppy(None, 0, pressed.append, pressed.append)
    assert pressed == []


def test_swap_logs_only_the_disk_change_lines_written_during_it(tmp_path):
    log = tmp_path / "fs-uae.log"
    log.write_text("boot\ngui_disk_image_change early\n")
    since = log.stat().st_size
    with log.open("a") as out:
        out.write("noise\nperform disk_swap 1\nmore noise\n"
                  "gui_disk_image_change 2\n")
    assert fsuaegdb.swap_log_lines(log, since) == [
        "perform disk_swap 1", "gui_disk_image_change 2"]
    assert fsuaegdb.swap_log_lines(tmp_path / "missing.log", 0) == []
    assert fsuaegdb.swap_log_lines(None, 0) == []


# launch


class FakeProc:
    started: list = []

    def __init__(self, argv, **kw):
        self.argv, self.kw, self.signals = argv, kw, []
        self.done = False
        FakeProc.started.append(self)

    pid = 1

    def poll(self):
        return 0 if self.done else None

    def wait(self, timeout=None):
        self.done = True
        return 0

    def send_signal(self, sig):
        self.signals.append(sig)
        self.done = True

    def kill(self):
        self.done = True


def launch_args(tmp_path, **kw):
    binary = tmp_path / "fs-uae"
    binary.write_text("")
    base = dict(fs_uae=str(binary), out=str(tmp_path / "run"), display=":77",
                kickstart=None, floppy=None, swap=None, foreground=False,
                wait=1, port=6525, extra=None)
    return argparse.Namespace(**{**base, **kw})


@pytest.fixture
def procs(monkeypatch):
    FakeProc.started = []
    monkeypatch.setattr(fsuaegdb.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(fsuaegdb.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        fsuaegdb.subprocess, "run",
        lambda *a, **k: argparse.Namespace(stdout=":6525 LISTEN"))
    return FakeProc.started


def test_launch_without_the_new_options_builds_the_command_it_always_did(
        tmp_path, procs):
    args = launch_args(tmp_path, floppy=["a.adf", "b.adf"])
    assert fsuaegdb.launch(args) == 0
    xvfb, emulator = procs
    run = (tmp_path / "run").resolve()
    assert emulator.argv == [
        str((tmp_path / "fs-uae").resolve()), f"--base_dir={run / 'base'}",
        "--fullscreen=0", "--remote_debugger=1", "--remote_debugger_port=6525",
        f"--floppy_drive_0={pathlib.Path('a.adf').resolve()}",
        f"--floppy_drive_1={pathlib.Path('b.adf').resolve()}"]
    assert emulator.kw["start_new_session"] is True
    assert xvfb.kw["start_new_session"] is True


def test_swap_images_follow_the_drives_in_the_swap_list(tmp_path, procs):
    args = launch_args(tmp_path, floppy=["a.adf", "b.adf"], swap=["c.adf"])
    fsuaegdb.launch(args)
    argv = procs[1].argv
    names = [pathlib.Path(a.split("=", 1)[1]).name for a in argv
             if a.startswith("--floppy_image_")]
    assert [a.split("=")[0] for a in argv if "floppy_image_" in a] == [
        "--floppy_image_0", "--floppy_image_1", "--floppy_image_2"]
    assert names == ["a.adf", "b.adf", "c.adf"]
    assert "--joystick_port_1=none" not in argv


def test_foreground_waits_stays_in_the_callers_group_and_takes_xvfb_down(
        tmp_path, procs):
    args = launch_args(tmp_path, foreground=True)
    assert fsuaegdb.launch(args) == 0
    xvfb, emulator = procs
    assert "--joystick_port_1=none" in emulator.argv
    assert emulator.kw["start_new_session"] is False
    assert xvfb.kw["start_new_session"] is False
    assert emulator.done and xvfb.done and xvfb.signals    # nothing left behind


def test_foreground_signals_both_when_the_emulator_wait_raises(tmp_path, procs,
                                                               monkeypatch):
    real_wait = FakeProc.wait

    def interrupted(self, timeout=None):
        if timeout is None:
            raise KeyboardInterrupt
        return real_wait(self, timeout)

    monkeypatch.setattr(FakeProc, "wait", interrupted)
    with pytest.raises(KeyboardInterrupt):
        fsuaegdb.launch(launch_args(tmp_path, foreground=True))
    xvfb, emulator = procs
    assert xvfb.signals and emulator.signals


def test_foreground_takes_xvfb_down_when_the_emulator_will_not_start(
        tmp_path, procs, monkeypatch):
    def popen(argv, **kw):
        if argv[0] != "Xvfb":
            raise OSError("cannot exec")
        return FakeProc(argv, **kw)

    monkeypatch.setattr(fsuaegdb.subprocess, "Popen", popen)
    with pytest.raises(OSError):
        fsuaegdb.launch(launch_args(tmp_path, foreground=True))
    assert procs[0].signals


def test_foreground_takes_xvfb_down_when_interrupted_while_it_settles(
        tmp_path, procs, monkeypatch):
    def interrupted(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(fsuaegdb.time, "sleep", interrupted)
    with pytest.raises(KeyboardInterrupt):
        fsuaegdb.launch(launch_args(tmp_path, foreground=True))
    assert procs[0].signals


def test_detached_takes_xvfb_down_when_the_emulator_will_not_start(
        tmp_path, procs, monkeypatch):
    def popen(argv, **kw):
        if argv[0] != "Xvfb":
            raise OSError("cannot exec")
        return FakeProc(argv, **kw)

    monkeypatch.setattr(fsuaegdb.subprocess, "Popen", popen)
    with pytest.raises(OSError):
        fsuaegdb.launch(launch_args(tmp_path))
    assert procs[0].signals


def test_detached_takes_xvfb_down_when_interrupted_while_it_settles(
        tmp_path, procs, monkeypatch):
    def interrupted(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(fsuaegdb.time, "sleep", interrupted)
    with pytest.raises(KeyboardInterrupt):
        fsuaegdb.launch(launch_args(tmp_path))
    assert procs[0].signals


def test_detached_leaves_both_running_when_the_port_never_opens(
        tmp_path, procs, monkeypatch):
    monkeypatch.setattr(fsuaegdb.subprocess, "run",
                        lambda *a, **k: argparse.Namespace(stdout=""))
    assert fsuaegdb.launch(launch_args(tmp_path)) == 1
    assert not any(p.signals for p in procs)


def test_the_joystick_option_appears_only_under_foreground(tmp_path, procs):
    fsuaegdb.launch(launch_args(tmp_path))
    assert "--joystick_port_1=none" not in procs[1].argv


# session


def session_args(tmp_path, **kw):
    base = dict(out=str(tmp_path / "run"), commands=str(tmp_path / "cmds"),
                maps=None, display=":77", settle=0.0, interval=0.0,
                seconds=30.0, at=0xC00000, hold=0.12, window=False,
                peeks=None, swap_sequence=None, fs_uae_log=None,
                title="pools-of-darkness", host="127.0.0.1", port=6525,
                timeout=None)
    return argparse.Namespace(**{**base, **kw})


@pytest.fixture
def driven(monkeypatch, tmp_path):
    """`session` over a fake machine, with keys, screenshots and waits recorded."""
    block = synthetic_geo()
    memory = pod_memory(0x57AC, 0xC20000, {0xC20024: bytes([1, 34, 14])})
    data = bytearray(memory[BASE])
    data[POD.geo_pointer:POD.geo_pointer + 4] = (0xC07000).to_bytes(4, "big")
    memory[BASE] = bytes(data)
    memory[0xC07000] = block
    guest = FakeAmiga(memory)
    log = {"keys": [], "shots": [], "still": []}
    from tools.amiga import amigatarget, fsuaepor
    monkeypatch.setattr(fsuaegdb, "connect", lambda args: transport(guest))
    monkeypatch.setattr(amigatarget, "find_maps", lambda layout, where: (
        {"GEO24": Geo(block), "GEO25": Geo(bytes(len(block)))},
        tmp_path / "pod3.adf"))
    monkeypatch.setattr(fsuaepor, "keys", lambda a: log["keys"].append(
        (a.key, a.hold)))
    monkeypatch.setattr(fsuaepor, "_wait_until_still",
                        lambda display, label, take: log["still"].append(label))
    monkeypatch.setattr(fsuaegdb, "shot", lambda display, path: log["shots"]
                        .append(path.name))
    monkeypatch.setattr(fsuaegdb.time, "sleep", lambda s: None)
    return guest, log


def run_session(tmp_path, lines, **kw):
    args = session_args(tmp_path, **kw)
    pathlib.Path(args.commands).write_text("\n".join([*lines, "quit"]) + "\n")
    assert fsuaegdb.session(args) == 0
    rows = [json.loads(line) for line in
            (tmp_path / "run" / "session.jsonl").read_text().splitlines()]
    return {r["event"]: r for r in rows}, rows


def test_session_keys_are_held_through_fsuaepors_implementation(driven, tmp_path):
    _, log = driven
    run_session(tmp_path, ["key KP_Up p"])
    assert log["keys"] == [(["KP_Up"], 0.12), (["p"], 0.12)]


def test_session_still_and_wait_are_logged(driven, tmp_path):
    _, log = driven
    events, _ = run_session(tmp_path, ["still title", "wait 0.5"])
    assert log["still"] == ["title"]
    assert events["still"]["label"] == "title"
    assert events["wait"]["seconds"] == 0.5


def test_session_peek_before_locate_is_logged_as_a_refusal(driven, tmp_path):
    events, _ = run_session(tmp_path, ["peek +0x10 1"])
    assert events["peek"]["hex"] is None and "locate" in events["peek"]["error"]


def test_session_peek_after_locate_returns_the_bytes(driven, tmp_path):
    events, _ = run_session(tmp_path, ["locate", "peek *0x57AC+0x24 3"])
    assert events["peek"]["hex"] == "01220e"


@pytest.mark.parametrize("line, event", [
    ("swap 2", "swap"), ("swap abc", "swap"), ("wait x", "wait"),
    ("peek +0x10 zz", "peek")])
def test_a_bad_or_unconfigured_command_is_an_error_row_and_the_session_goes_on(
        driven, tmp_path, line, event):
    _, rows = run_session(tmp_path, [line, "wait 0.5"])
    assert [r["event"] for r in rows if r.get("error")] == [event]
    assert {"event": "wait", "seconds": 0.5}.items() <= next(
        r for r in reversed(rows) if r["event"] == "wait").items()


def test_swap_without_a_sequence_names_the_missing_option(driven, tmp_path):
    events, _ = run_session(tmp_path, ["swap 2"])
    assert "--swap-sequence" in events["swap"]["error"]


@pytest.mark.parametrize("line", ["wait x", "peek +0x10 zz"])
def test_an_error_row_names_the_exception_type(driven, tmp_path, line):
    _, rows = run_session(tmp_path, [line])
    assert next(r for r in rows if r.get("error"))["error"].startswith(
        "ValueError: ")


def _swap_row(tmp_path, **kw):
    events, _ = run_session(tmp_path, ["swap 2"], **kw)
    return events["swap"]


def test_a_swap_on_the_default_sequence_without_a_log_is_marked_unchecked(
        driven, tmp_path):
    row = _swap_row(tmp_path, swap_sequence=fsuaegdb.DEFAULT_SWAP_SEQUENCE)
    assert row["default_sequence"] is True and row["unchecked"] is True


def test_a_swap_with_a_log_or_a_chosen_sequence_is_not_marked(driven, tmp_path):
    fs_log = tmp_path / "fs-uae.log"
    fs_log.write_text("")
    with_log = _swap_row(tmp_path, swap_sequence=fsuaegdb.DEFAULT_SWAP_SEQUENCE,
                         fs_uae_log=str(fs_log))
    chosen = _swap_row(tmp_path, swap_sequence="F12 Return")
    assert "unchecked" not in with_log and "unchecked" not in chosen


def test_the_cli_default_swap_sequence_is_the_measured_menu_walk():
    assert fsuaegdb.expand_sequence(fsuaegdb.DEFAULT_SWAP_SEQUENCE, 2) == [
        "F12", "Down", "Down", "Down", "Return", "Down", "Down", "Return", "F12"]


def test_a_window_that_fails_to_open_still_restores_the_data_dir_and_closes(
        driven, tmp_path, monkeypatch):
    from automap import state as mapstate

    was = mapstate._data_dir                            # noqa: SLF001
    closed = []
    real_close = fsuaegdb.amiga.FsuaeGdb.close
    monkeypatch.setattr(fsuaegdb.amiga.FsuaeGdb, "close",
                        lambda self: (closed.append(1), real_close(self)))

    def refuse(*a, **k):
        raise SystemExit("no maps")

    monkeypatch.setattr(fsuaegdb, "open_window", refuse)
    args = session_args(tmp_path, window=True, maps=str(tmp_path))
    pathlib.Path(args.commands).write_text("quit\n")
    with pytest.raises(SystemExit):
        fsuaegdb.session(args)
    assert mapstate._data_dir is was                    # noqa: SLF001
    assert closed


def test_session_swap_takes_a_screenshot_either_side_and_logs_the_index(
        driven, tmp_path):
    _, log = driven
    fs_log = tmp_path / "fs-uae.log"
    fs_log.write_text("old gui_disk_image_change\n")
    real_still = fsuaegdb.still

    def writing_still(args, out, label):
        with fs_log.open("a") as f:
            f.write("perform disk_swap 2\n")
        real_still(args, out, label)

    fsuaegdb.still = writing_still
    try:
        events, _ = run_session(tmp_path, ["swap 2"], swap_sequence="F12 Return",
                                fs_uae_log=str(fs_log))
    finally:
        fsuaegdb.still = real_still
    assert events["swap"]["index"] == 2
    assert events["swap"]["keys"] == ["F12", "Return"]
    assert events["swap"]["log"] == ["perform disk_swap 2"] * 2
    assert log["keys"] == [(["F12"], 0.12), (["Return"], 0.12)]
    assert log["shots"] == ["swap2-before.png", "swap2-after.png"]


def test_observe_records_the_peeks_the_raw_fix_and_which_block_is_resident(
        driven, tmp_path):
    _, log = driven
    events, _ = run_session(
        tmp_path, ["locate", "observe first"],
        peeks=["+0x57AC 4", "*0x57AC+0x24 3"])
    row = events["observe"]
    assert row["name"] == "first" and row["error"] is None
    assert [p["hex"] for p in row["peeks"]] == ["00c20000", "01220e"]
    assert row["block"]["resident"] == ["GEO24"]
    assert row["geo_pointer"] == 0xC07000
    assert "first.png" in log["shots"]


def test_observe_records_a_tick_that_raises_instead_of_ending_the_run(
        driven, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("tick failed")

    monkeypatch.setattr(fsuaegdb.amiga.AmigaTarget, "fix", boom)
    events, _ = run_session(tmp_path, ["locate", "observe x"])
    assert "tick failed" in events["observe"]["error"]


def test_observe_with_a_window_ticks_the_tab_and_saves_both_pictures(
        driven, tmp_path, monkeypatch):
    from tools.gui import mapmarker

    ticks, grabs = [], []

    class Binding:
        LIVE_EVERY = 5
        root, canvas = "root", "canvas"
        state = argparse.Namespace(geo=None)

        def tick(self):
            ticks.append(1)

    app = argparse.Namespace(processEvents=lambda: None)
    monkeypatch.setattr(fsuaegdb, "open_window",
                        lambda tgt, disks, out: (app, None, Binding(), {}))
    monkeypatch.setattr(mapmarker, "reading",
                        lambda binding, tag: {"tag": tag, "area": "GEO24"})
    monkeypatch.setattr(mapmarker, "shot",
                        lambda app, widget, path: grabs.append(
                            (widget, path.name)))
    events, _ = run_session(tmp_path, ["locate", "observe walk1"], window=True, maps=str(tmp_path))
    assert len(ticks) == Binding.LIVE_EVERY + 1
    assert grabs == [("root", "walk1-window.png"), ("canvas", "walk1-map.png")]
    assert events["observe"]["tab"]["area"] == "GEO24"


def test_window_mode_needs_the_folder_of_disks():
    with pytest.raises(SystemExit, match="folder"):
        fsuaegdb.open_window(None, None, pathlib.Path("."))


def test_the_window_loads_maps_the_way_a_players_does(monkeypatch, tmp_path):
    from tools.gui import mapmarker

    asked = []
    monkeypatch.setattr(mapmarker, "_offscreen", lambda: None)
    monkeypatch.setattr(mapmarker, "build_window", lambda *a, **k: asked.append(
        (a, k)))
    fsuaegdb.open_window("target", str(tmp_path), tmp_path)
    assert asked == [(("target", str(tmp_path), tmp_path),
                      {"amiga_only": True})]


# window lookup


def test_key_presses_find_the_window_under_either_of_its_names(monkeypatch):
    from tools.amiga import fsuaepor

    seen = []

    def run(argv, **kw):
        seen.append(argv)
        return argparse.Namespace(stdout="42\n", stderr="")

    monkeypatch.setattr(fsuaepor.subprocess, "run", run)
    monkeypatch.setattr(fsuaegdb.subprocess, "run", run)
    monkeypatch.setattr(fsuaegdb.time, "sleep", lambda s: None)
    monkeypatch.setattr(fsuaepor.time, "sleep", lambda s: None)
    fsuaegdb.press(":77", "Return", 0)
    fsuaepor.keys(argparse.Namespace(display=":77", key=["Return"], hold=0,
                                     settle=0))
    searches = [a[a.index("--name") + 1] for a in seen if "search" in a]
    assert len(searches) == 2
    for pattern in searches:
        assert re.search(pattern, "Amiga Emulator")
        assert re.search(pattern, "FS-UAE")
    assert ["xdotool", "windowfocus", "42"] in seen


def test_keys_with_no_emulator_window_say_which_names_were_tried(monkeypatch):
    from tools.amiga import fsuaepor

    monkeypatch.setattr(fsuaepor.subprocess, "run",
                        lambda *a, **k: argparse.Namespace(stdout=""))
    with pytest.raises(SystemExit, match="Amiga Emulator"):
        fsuaepor.keys(argparse.Namespace(display=":77", key=["x"], hold=0,
                                         settle=0))


# the title, argument checks before the connection, stop, focus


def two_titles_memory():
    memory = pod_memory(0x57AC, 0, {})
    data = bytearray(memory[BASE])
    data[0x100:0x100 + len(BLADES.anchor)] = BLADES.anchor
    memory[BASE] = bytes(data)
    return memory


def test_the_title_is_not_defaulted_on_the_command_line():
    parser_args = []
    real = fsuaegdb.locate
    try:
        fsuaegdb.locate = lambda a: parser_args.append(a) or 0
        assert fsuaegdb.main(["locate"]) == 0
    finally:
        fsuaegdb.locate = real
    assert parser_args[0].title is None


def test_a_session_without_a_title_detects_the_one_that_is_running(
        driven, tmp_path, capsys):
    events, _ = run_session(tmp_path, ["locate", "fix"], title=None)
    assert "Pools of Darkness" in capsys.readouterr().out
    assert events["locate"]["base"] == BASE


def test_detection_names_every_title_when_none_matches():
    guest = FakeAmiga({})
    with pytest.raises(SystemExit, match="pools-of-darkness") as err:
        fsuaegdb.detect_layout(transport(guest))
    for key in amiga.MACHINES:
        assert key in str(err.value)


def test_detection_names_the_titles_when_several_match():
    guest = FakeAmiga(two_titles_memory())
    with pytest.raises(SystemExit, match="more than one") as err:
        fsuaegdb.detect_layout(transport(guest))
    assert "Pools of Darkness" in str(err.value)
    assert "Secret of the Silver Blades" in str(err.value)


def test_a_command_without_a_title_uses_the_detected_one(monkeypatch, capsys):
    guest = FakeAmiga(pod_memory(0x57AC, 0, {}))
    monkeypatch.setattr(fsuaegdb, "connect", lambda args: transport(guest))
    args = argparse.Namespace(title=None, host="h", port=1, timeout=None)
    assert fsuaegdb.target(args).layout is POD


def test_automap_needs_a_title_before_it_connects(monkeypatch, tmp_path):
    monkeypatch.setattr(fsuaegdb, "connect", lambda args: pytest.fail("connected"))
    with pytest.raises(SystemExit, match="--title"):
        fsuaegdb.automap(argparse.Namespace(title=None, out=str(tmp_path),
                                            maps=None))


def test_commands_already_in_the_file_when_the_session_starts_are_run(
        driven, tmp_path):
    _, log = driven
    run_session(tmp_path, ["key KP_Up"])
    assert log["keys"] == [(["KP_Up"], 0.12)]


@pytest.fixture
def refusing(monkeypatch):
    seen = []
    monkeypatch.setattr(fsuaegdb, "connect", lambda args: seen.append(1))
    return seen


@pytest.mark.parametrize("kw, text", [
    (dict(maps="/nonexistent/disk3.adf"), "--maps"),
    (dict(window=True), "--window"),
    (dict(swap_sequence="F12 Down*x"), "--swap-sequence"),
    (dict(peeks=["+0x10 zz"]), "--peeks"),
    (dict(peeks=["nolength"]), "--peeks")])
def test_session_refuses_a_bad_argument_before_connecting(
        refusing, tmp_path, kw, text):
    with pytest.raises(SystemExit, match=text):
        fsuaegdb.session(session_args(tmp_path, **kw))
    assert refusing == []


def test_an_image_given_to_the_window_means_its_folder(monkeypatch, tmp_path):
    from tools.gui import mapmarker

    image = tmp_path / "disk3.adf"
    image.write_bytes(b"")
    asked = []
    monkeypatch.setattr(mapmarker, "_offscreen", lambda: None)
    monkeypatch.setattr(mapmarker, "build_window", lambda *a, **k: asked.append(a))
    fsuaegdb.open_window("target", str(image), tmp_path)
    assert asked == [("target", str(tmp_path), tmp_path)]


def test_a_session_with_a_window_and_an_image_connects(driven, tmp_path,
                                                        monkeypatch):
    image = tmp_path / "disk3.adf"
    image.write_bytes(b"")
    monkeypatch.setattr(fsuaegdb, "open_window", lambda *a: None)
    run_session(tmp_path, [], maps=str(image), window=True)


# session: dump, and a session with no title


def test_session_dump_writes_the_range_and_a_row_before_locate(driven, tmp_path):
    guest, _ = driven
    events, _ = run_session(tmp_path, ["dump first 0xC00000 0x40"])
    blob = guest.peek(0xC00000, 0x40)
    assert (tmp_path / "run" / "dumps" / "first.bin").read_bytes() == blob
    row = events["dump"]
    assert (row["name"], row["address"], row["length"], row["sha256"]) == (
        "first", 0xC00000, 0x40, hashlib.sha256(blob).hexdigest())


def test_session_dump_refuses_more_than_half_a_megabyte(driven, tmp_path):
    _, rows = run_session(tmp_path, ["dump big 0x0 0x80001", "wait 0.5"])
    row = next(r for r in rows if r["event"] == "dump")
    assert row["error"].startswith("ValueError: ") and "0x80000" in row["error"]
    assert not (tmp_path / "run" / "dumps" / "big.bin").exists()
    assert rows[-1]["event"] != "unknown" and any(r["event"] == "wait" for r in rows)


def test_session_dump_takes_half_a_megabyte_exactly(driven, tmp_path):
    events, _ = run_session(tmp_path, ["dump chip 0x0 0x80000"])
    assert events["dump"]["length"] == 0x80000 and "error" not in events["dump"]


@pytest.mark.parametrize("line", [
    "dump", "dump a 0x0", "dump ../a 0x0 4", "dump a zz 4", "dump a 0x0 0"])
def test_a_bad_dump_is_an_error_row_and_writes_nothing(driven, tmp_path, line):
    _, rows = run_session(tmp_path, [line])
    assert next(r for r in rows if r["event"] == "dump")["error"].startswith(
        "ValueError: ")
    assert not (tmp_path / "run" / "dumps").exists() or not list(
        (tmp_path / "run" / "dumps").iterdir())


def test_a_dump_the_server_refuses_is_an_error_row_not_the_end(driven, tmp_path):
    guest, _ = driven
    guest.unreadable.add(0x10)
    _, rows = run_session(tmp_path, ["dump bad 0x0 0x20", "wait 0.5"])
    row = next(r for r in rows if r["event"] == "dump")
    assert row["error"].startswith("FsuaeError: ")
    assert any(r["event"] == "wait" for r in rows)


@pytest.fixture
def untitled(driven, monkeypatch):
    """A session with `--title none`, over a machine that does carry a title.

    Detection would find Pools of Darkness here, so a session that still
    detects, or loads maps, is caught.
    """
    monkeypatch.setattr(fsuaegdb, "detect_layout",
                        lambda gdb: pytest.fail("detected a title"))
    from tools.amiga import amigatarget
    monkeypatch.setattr(amigatarget, "find_maps",
                        lambda *a: pytest.fail("looked for maps"))
    return driven


@pytest.mark.parametrize("line, event", [
    ("locate", "locate"), ("fix", "fix"), ("peek +0x10 1", "peek"),
    ("observe a", "observe"), ("poll", "poll")])
def test_a_titled_command_without_a_title_is_an_error_row_and_the_session_goes_on(
        untitled, tmp_path, line, event):
    _, rows = run_session(tmp_path, [line, "wait 0.5"], title="none")
    assert [r["event"] for r in rows if r.get("error")] == [event]
    assert "no title" in next(r for r in rows if r.get("error"))["error"]
    assert any(r["event"] == "wait" for r in rows)


def test_a_session_without_a_title_still_dumps_and_keys(untitled, tmp_path):
    _, log = untitled
    events, _ = run_session(tmp_path, ["key p", "dump x 0xC00000 8"],
                            title="none")
    assert log["keys"] == [(["p"], 0.12)]
    assert events["dump"]["length"] == 8


def test_a_window_needs_a_title_and_is_refused_before_connecting(
        refusing, tmp_path):
    with pytest.raises(SystemExit, match="--window"):
        fsuaegdb.session(session_args(tmp_path, title="none", window=True,
                                      maps=str(tmp_path)))
    assert refusing == []


def test_maps_need_a_title_and_are_refused_before_connecting(
        refusing, tmp_path):
    with pytest.raises(SystemExit, match="--maps"):
        fsuaegdb.session(session_args(tmp_path, title="none",
                                      maps=str(tmp_path)))
    assert refusing == []


def test_a_session_without_a_title_logs_no_image(untitled, tmp_path):
    _, rows = run_session(tmp_path, [], title="none")
    assert next(r for r in rows if r["event"] == "session")["image"] is None


def test_title_none_is_a_choice_on_the_command_line():
    seen = []
    real = fsuaegdb.session
    try:
        fsuaegdb.session = lambda a: seen.append(a.title) or 0
        assert fsuaegdb.main(["--title", "none", "session", "--out", "o",
                              "--commands", "c"]) == 0
    finally:
        fsuaegdb.session = real
    assert seen == ["none"]


def test_a_command_that_needs_a_layout_refuses_title_none(monkeypatch):
    monkeypatch.setattr(fsuaegdb, "connect", lambda args: pytest.fail("connected"))
    args = argparse.Namespace(title="none", host="h", port=1, timeout=None)
    with pytest.raises(SystemExit, match="none"):
        fsuaegdb.target(args)


def stop_args(**kw):
    return argparse.Namespace(**{**dict(pid=[5], wait=1.0), **kw})


def test_stop_waits_until_the_process_is_gone_and_says_so(monkeypatch, capsys):
    states = iter([True, True, False, False])
    monkeypatch.setattr(fsuaegdb.os, "killpg", lambda pid, sig: None)
    monkeypatch.setattr(fsuaegdb, "alive", lambda pid: next(states))
    monkeypatch.setattr(fsuaegdb.time, "sleep", lambda s: None)
    assert fsuaegdb.stop(stop_args()) == 0
    assert "5 stopped" in capsys.readouterr().out


def test_stop_reports_a_process_that_outlives_the_wait(monkeypatch, capsys):
    clock = iter(range(0, 100))
    monkeypatch.setattr(fsuaegdb.os, "killpg", lambda pid, sig: None)
    monkeypatch.setattr(fsuaegdb, "alive", lambda pid: True)
    monkeypatch.setattr(fsuaegdb.time, "sleep", lambda s: None)
    monkeypatch.setattr(fsuaegdb.time, "monotonic", lambda: next(clock))
    assert fsuaegdb.stop(stop_args(wait=3)) == 1
    assert "still running" in capsys.readouterr().out


def test_stop_does_not_call_a_live_pid_without_a_group_not_running(
        monkeypatch, capsys):
    def no_group(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(fsuaegdb.os, "killpg", no_group)
    monkeypatch.setattr(fsuaegdb, "alive", lambda pid: True)
    assert fsuaegdb.stop(stop_args()) == 1
    assert capsys.readouterr().out == (
        "5 is running but leads no process group, so nothing was signalled; a "
        "--foreground launch ends with the process that holds its lease\n")


def test_stop_says_not_running_for_a_pid_that_is_gone(monkeypatch, capsys):
    def no_group(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(fsuaegdb.os, "killpg", no_group)
    monkeypatch.setattr(fsuaegdb, "alive", lambda pid: False)
    assert fsuaegdb.stop(stop_args()) == 0
    assert "5 is not running" in capsys.readouterr().out


def test_alive_is_true_for_this_process():
    assert fsuaegdb.alive(os.getpid())


BAD_MATCH = ("X Error of failed request:  BadMatch (invalid parameter "
             "attributes)\n  Major opcode of failed request:  42 "
             "(X_SetInputFocus)\n")


def test_the_known_focus_error_is_hidden_and_any_other_is_not(
        monkeypatch, capsys):
    from tools.amiga import fsuaepor

    err = []
    monkeypatch.setattr(fsuaepor.subprocess, "run",
                        lambda *a, **k: argparse.Namespace(
                            stdout="", stderr=err[0]))
    err.append(BAD_MATCH)
    fsuaepor.focus(":77", "42")
    err[0] = "Can't open display :77\n"
    fsuaepor.focus(":77", "42")
    err[0] = "X Error of failed request:  BadWindow\n"
    fsuaepor.focus(":77", "42")
    shown = capsys.readouterr().err
    assert "BadMatch" not in shown
    assert "Can't open display" in shown and "BadWindow" in shown


def test_a_known_focus_error_beside_another_error_hides_only_itself(
        monkeypatch, capsys):
    from tools.amiga import fsuaepor

    other = ("X Error of failed request:  BadWindow (invalid Window "
             "parameter)\n  Major opcode of failed request:  42 "
             "(X_SetInputFocus)\n")
    err = BAD_MATCH + other
    monkeypatch.setattr(fsuaepor.subprocess, "run",
                        lambda *a, **k: argparse.Namespace(stdout="", stderr=err))
    fsuaepor.focus(":77", "42")
    shown = capsys.readouterr().err
    assert "BadMatch" not in shown
    assert shown == other


def test_target_closes_the_connection_when_no_title_can_be_chosen(monkeypatch):
    guest = FakeAmiga({})
    monkeypatch.setattr(fsuaegdb, "connect", lambda args: transport(guest))
    args = argparse.Namespace(title=None, host="h", port=1, timeout=None)
    with pytest.raises(SystemExit, match="no known title"):
        fsuaegdb.target(args)
    assert guest.closed


def test_a_session_that_cannot_detect_its_title_closes_the_connection(
        driven, tmp_path, monkeypatch):
    guest, _ = driven
    monkeypatch.setattr(fsuaegdb, "detect_layout",
                        lambda gdb: (_ for _ in ()).throw(SystemExit("none")))
    with pytest.raises(SystemExit):
        run_session(tmp_path, [], title=None)
    assert guest.closed


@pytest.mark.parametrize("kw, text", [
    (dict(maps="DISK"), "--maps"), (dict(window=True, maps="DISK"), "--title")])
def test_maps_without_a_title_are_refused_before_connecting(
        refusing, tmp_path, kw, text):
    disk = tmp_path / "DISK"
    disk.mkdir()
    kw = {**kw, "maps": str(disk)}
    with pytest.raises(SystemExit, match=text):
        fsuaegdb.session(session_args(tmp_path, title=None, **kw))
    assert refusing == []


def test_detection_names_two_titles_loaded_in_different_regions():
    memory = pod_memory(0x57AC, 0, {})
    data = bytearray(0x8000)
    data[BLADES.anchor_offset:BLADES.anchor_offset + len(BLADES.anchor)] = \
        BLADES.anchor
    memory[0x10000] = bytes(data)
    with pytest.raises(SystemExit, match="more than one") as err:
        fsuaegdb.detect_layout(transport(FakeAmiga(memory)))
    assert "Pools of Darkness" in str(err.value)
    assert "Secret of the Silver Blades" in str(err.value)
