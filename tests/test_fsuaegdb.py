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
        self._out = bytearray()

    # -- the socket surface ---------------------------------------------

    def settimeout(self, _seconds) -> None:
        pass

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
            self._out += self._frame(reply)

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
