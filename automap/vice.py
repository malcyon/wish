"""VICE binary-monitor client.

Extracted from `tools/drive.py`, which still re-exports it so the discovery
scaffolding keeps working. The protocol imposes two rules and both are obeyed
here:

**Match responses by request id.** VICE interleaves unsolicited events (type
``0x62``, ``rid=0xFFFFFFFF``) into the same stream, and a client that reads one
response per request silently returns the *previous* request's data.

**An open connection stops the machine.** Nothing advances while the socket is
up. `Monitor` is a context manager for that reason -- open it, do a burst of
work, close it. For a long-running poller that would stutter the game, so use
`resume()` instead and keep one connection for the session; see
`automap/target.py`.

Screen reading lives in `screen.py` now, over a plain `read` callable, because
none of it is VICE-specific. The wrappers at the foot of this file keep the
Monitor-shaped spelling `tools/` uses.
"""

from __future__ import annotations

import socket
import struct
import time

MON_HOST = "127.0.0.1"
MON_PORT = 6502

# Command types
CMD_MEM_GET = 0x01
CMD_MEM_SET = 0x02
CMD_CHECKPOINT_GET = 0x11
CMD_CHECKPOINT_SET = 0x12
CMD_CHECKPOINT_DELETE = 0x13
CMD_CHECKPOINT_LIST = 0x14
CMD_REGISTERS_GET = 0x31
CMD_REGISTERS_SET = 0x32
CMD_DUMP = 0x41
CMD_UNDUMP = 0x42
CMD_BANKS_AVAILABLE = 0x82
CMD_PING = 0x81
CMD_EXIT = 0xAA
CMD_QUIT = 0xBB
CMD_RESET = 0xCC

RESP_CHECKPOINT = 0x11

# Timings from docs/70-driving-the-game.md.  Anything faster is dropped.


class MonitorError(RuntimeError):
    pass


class Monitor:
    """One connect/read/close cycle.  Use as a context manager.

    The machine is stopped for as long as this is open, so keep the block
    short and do the waiting outside it.
    """

    def __init__(self, host: str = MON_HOST, port: int = MON_PORT, timeout: float = 5.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock: socket.socket | None = None
        self._rid = 0

    def __enter__(self) -> "Monitor":
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self.sock is not None:
                # EXIT resumes the emulator; closing does too, but saying so
                # explicitly means a lingering socket cannot freeze the game.
                self._send(CMD_EXIT, b"")
        except Exception:
            pass
        finally:
            if self.sock is not None:
                self.sock.close()
                self.sock = None

    # -- wire -------------------------------------------------------------

    def _recv_exactly(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise MonitorError("monitor closed the connection")
            buf += chunk
        return buf

    def _send(self, cmd: int, body: bytes) -> int:
        self._rid += 1
        rid = self._rid
        hdr = struct.pack("<BBIIB", 0x02, 0x02, len(body), rid, cmd)
        self.sock.sendall(hdr + body)
        return rid

    def _read_response(self, rid: int) -> tuple[int, int, bytes]:
        """Read until the reply carrying *rid* arrives, discarding events."""
        deadline = time.time() + self.timeout
        while True:
            head = self._recv_exactly(12)
            if head[0] != 0x02:
                raise MonitorError(f"bad response magic {head[0]:#04x}")
            length, rtype, err = struct.unpack("<IBB", head[2:8])
            got_rid = struct.unpack("<I", head[8:12])[0]
            body = self._recv_exactly(length) if length else b""
            if got_rid == rid:
                if err:
                    raise MonitorError(f"monitor error {err:#04x} on type {rtype:#04x}")
                return rtype, err, body
            if time.time() > deadline:
                raise MonitorError(f"no response for request {rid}")

    def command(self, cmd: int, body: bytes = b"") -> bytes:
        return self._read_response(self._send(cmd, body))[2]

    def ping(self) -> None:
        """Ask for a reply and wait for it. Nothing else about the machine.

        The one command whose answer proves this connection is *served*: VICE
        accepts a second TCP connection and then silently ignores it, so a
        socket that is up says nothing until something asks. See
        `automap.target.MonitorBusy`.
        """
        self.command(CMD_PING)

    # -- running while connected -----------------------------------------

    def resume(self) -> None:
        """Let the machine run again without dropping the connection.

        Needed whenever a checkpoint is armed: VICE re-enters the monitor on
        a hit and talks to **the connection that was open when it stopped**.
        Closing the socket and reconnecting after the hit leaves VICE wedged
        with the old half-closed socket -- the emulator freezes and the new
        connection is never read.  Verified the hard way.
        """
        self._send(CMD_EXIT, b"")

    def wait_stopped(self, timeout: float = 20.0) -> int | None:
        """Block until VICE reports it has stopped; returns the PC."""
        old = self.timeout
        self.sock.settimeout(timeout)
        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                head = self._recv_exactly(12)
                length, rtype, _ = struct.unpack("<IBB", head[2:8])
                body = self._recv_exactly(length) if length else b""
                if rtype == 0x62 and length >= 2:  # STOPPED
                    return struct.unpack("<H", body[:2])[0]
            return None
        except (TimeoutError, socket.timeout):
            return None
        finally:
            self.sock.settimeout(old)

    # -- memory -----------------------------------------------------------

    def read(self, start: int, length: int, bank: int = 0, side_effects: int = 0) -> bytes:
        end = start + length - 1
        body = struct.pack("<BHHBH", side_effects, start, end, 0, bank)
        rid = self._send(CMD_MEM_GET, body)
        _, _, resp = self._read_response(rid)
        n = struct.unpack("<H", resp[:2])[0]
        data = resp[2 : 2 + n]
        if len(data) != length:
            raise MonitorError(f"asked {length} bytes at ${start:04X}, got {len(data)}")
        return data

    def peek(self, addr: int, bank: int = 0) -> int:
        return self.read(addr, 1, bank)[0]

    def write(self, start: int, data: bytes, bank: int = 0, side_effects: int = 0) -> None:
        end = start + len(data) - 1
        body = struct.pack("<BHHBH", side_effects, start, end, 0, bank) + bytes(data)
        self.command(CMD_MEM_SET, body)

    # -- checkpoints ------------------------------------------------------

    def checkpoint_set(
        self,
        start: int,
        end: int | None = None,
        *,
        load: bool = False,
        store: bool = False,
        exec_: bool = False,
        stop: bool = True,
        temporary: bool = False,
    ) -> int:
        end = start if end is None else end
        op = (0x01 if load else 0) | (0x02 if store else 0) | (0x04 if exec_ else 0)
        body = struct.pack(
            "<HHBBBB", start, end, 1 if stop else 0, 1, op, 1 if temporary else 0
        )
        rid = self._send(CMD_CHECKPOINT_SET, body)
        _, _, resp = self._read_response(rid)
        return struct.unpack("<I", resp[:4])[0]

    def checkpoint_delete(self, number: int) -> None:
        self.command(CMD_CHECKPOINT_DELETE, struct.pack("<I", number))

    def checkpoint_list(self) -> list[int]:
        """Numbers of every checkpoint VICE currently holds."""
        rid = self._send(CMD_CHECKPOINT_LIST, b"")
        nums = []
        while True:
            head = self._recv_exactly(12)
            length, rtype, err = struct.unpack("<IBB", head[2:8])
            got_rid = struct.unpack("<I", head[8:12])[0]
            body = self._recv_exactly(length) if length else b""
            if got_rid != rid:
                continue
            if rtype == RESP_CHECKPOINT:
                nums.append(struct.unpack("<I", body[:4])[0])
                continue
            return nums  # the CHECKPOINT_LIST response itself ends the run

    def checkpoints_clear(self) -> int:
        n = 0
        for num in self.checkpoint_list():
            self.checkpoint_delete(num)
            n += 1
        return n

    # -- registers --------------------------------------------------------

    def registers(self) -> dict[int, int]:
        resp = self.command(CMD_REGISTERS_GET, struct.pack("<B", 0))
        count = struct.unpack("<H", resp[:2])[0]
        out, off = {}, 2
        for _ in range(count):
            size = resp[off]
            rid_ = resp[off + 1]
            val = struct.unpack("<H", resp[off + 2 : off + 4])[0]
            out[rid_] = val
            off += size + 1
        return out

    def set_registers(self, values: dict[int, int]) -> None:
        """Write CPU registers, keyed by the ids `registers()` returns.

        The body needs the same leading memspace byte as `REGISTERS_GET`,
        which the protocol document does not say: without it VICE answers
        error `0x80` (invalid parameter) and changes nothing. And the ids
        cannot be assumed -- `CMD_REGISTERS_AVAILABLE` (`0x83`) is
        unsupported in this VICE build, so read `registers()` once and match
        by the ids it hands back.
        """
        body = struct.pack("<BH", 0, len(values))
        for rid_, val in values.items():
            body += struct.pack("<BBH", 3, rid_, val & 0xFFFF)
        self.command(CMD_REGISTERS_SET, body)


# -- screen -----------------------------------------------------------------
# The decoding moved to `screen.py`, which works over any `read` callable.
# These wrappers keep the Monitor-shaped spelling `tools/` already uses.

from . import screen as _screen  # noqa: E402
from .screen import (  # noqa: E402,F401
    COLOUR_RAM,
    SCREEN_COLS,
    SCREEN_ROWS,
    Screen,
    codes_to_text,
)


def screen_address(mon: Monitor) -> int:
    return _screen.screen_address(mon.read)


def is_bitmap(mon: Monitor) -> bool:
    return _screen.is_bitmap(mon.read)


def read_screen(mon: Monitor) -> Screen:
    return _screen.read_screen(mon.read)


def grab_screen(**kw) -> Screen:
    """Open a connection, read the screen, close it again."""
    with Monitor(**kw) as mon:
        return read_screen(mon)


# -- keys -------------------------------------------------------------------
