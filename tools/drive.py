#!/usr/bin/env python3
"""Drive Pool of Radiance running under VICE.

Discovery scaffolding, not part of the packaged library: it talks to a live
emulator and to an X server, so it belongs beside the other tools.

Three things it provides.

**A binary-monitor client** that obeys the two rules the protocol imposes.
Responses are matched by request id, because VICE interleaves unsolicited
events (type ``0x62``, ``rid=0xFFFFFFFF``) into the same stream and a client
that reads one response per request silently returns the *previous* request's
data.  And a connection is opened, used and closed for each burst of work,
because an open connection stops the machine -- nothing advances while the
socket is up.

**Key sending** through XTEST on the nested display.  The game polls the CIA
keyboard matrix directly, so the KERNAL buffer is useless and a press/release
pair faster than the poll interval is missed entirely.  Every key goes down,
holds, comes up, then a gap.

**Screen reading** as screen codes.  The game runs in text mode with its own
character set, so no OCR is needed -- but the screen address moves ($0400 at
boot, $CC00 in game), so it is recomputed from the VIC registers on every
read.  Menu highlighting is a *colour*: the selected row is white (1) against
green (5), and colour RAM is at $D800 whatever the VIC bank.
"""

from __future__ import annotations

import socket
import struct
import subprocess
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
CMD_DUMP = 0x41
CMD_UNDUMP = 0x42
CMD_BANKS_AVAILABLE = 0x82
CMD_PING = 0x81
CMD_EXIT = 0xAA
CMD_QUIT = 0xBB
CMD_RESET = 0xCC

RESP_CHECKPOINT = 0x11

# Timings from docs/70-driving-the-game.md.  Anything faster is dropped.
MENU_HOLD, MENU_GAP = 0.10, 0.14
TEXT_HOLD, TEXT_GAP = 0.15, 0.28


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


# -- screen -----------------------------------------------------------------

SCREEN_COLS, SCREEN_ROWS = 40, 25
COLOUR_RAM = 0xD800


def screen_address(mon: Monitor) -> int:
    """Where the VIC is fetching characters from, right now.

    It moves: $0400 at boot, $CC00 once the game is running.  Computing it
    each time is the difference between reading the screen and reading
    whatever used to be the screen.
    """
    d018 = mon.peek(0xD018)
    dd00 = mon.peek(0xDD00)
    bank = (~dd00 & 3) * 0x4000
    return bank + ((d018 >> 4) & 0xF) * 0x400


def is_bitmap(mon: Monitor) -> bool:
    """Title and credit screens are bitmaps and cannot be read as text."""
    return bool(mon.peek(0xD011) & 0x20)


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


def read_screen(mon: Monitor) -> Screen:
    addr = screen_address(mon)
    codes = mon.read(addr, 1000)
    colours = mon.read(COLOUR_RAM, 1000)
    return Screen(codes, colours, addr)


def grab_screen(**kw) -> Screen:
    """Open a connection, read the screen, close it again."""
    with Monitor(**kw) as mon:
        return read_screen(mon)


# -- keys -------------------------------------------------------------------


class Keyboard:
    """XTEST key delivery to the VICE window on the nested display."""

    def __init__(self, display: str = ":7"):
        self.display = display

    def _xdo(self, *args: str) -> None:
        subprocess.run(
            ["xdotool", *args],
            env={"DISPLAY": self.display, "PATH": "/usr/bin:/bin"},
            check=False,
            capture_output=True,
        )

    def key(self, name: str, hold: float = MENU_HOLD, gap: float = MENU_GAP) -> None:
        self._xdo("keydown", name)
        time.sleep(hold)
        self._xdo("keyup", name)
        time.sleep(gap)

    def keys(self, names, hold: float = MENU_HOLD, gap: float = MENU_GAP) -> None:
        for n in names:
            self.key(n, hold, gap)

    def text(self, s: str, hold: float = TEXT_HOLD, gap: float = TEXT_GAP) -> None:
        """Type a string.

        **Lowercased first, and that is not cosmetic.** `xdotool key W` sends
        Shift+w, which the C64 delivers as PETSCII `$D7`; the name-entry
        routine rejects any byte `>= $5B` and silently restarts the prompt.
        That single detail was the whole character-creation dead end.
        """
        for ch in s.lower():
            name = {" ": "space", "-": "minus", "'": "apostrophe", ".": "period"}.get(
                ch, ch
            )
            self.key(name, hold, gap)

    def screenshot(self, path: str) -> bool:
        r = subprocess.run(
            ["import", "-window", "root", path],
            env={"DISPLAY": self.display, "PATH": "/usr/bin:/bin"},
            capture_output=True,
        )
        return r.returncode == 0


# -- waiting ----------------------------------------------------------------


def wait_for(predicate, timeout: float = 30.0, interval: float = 0.5, **kw):
    """Poll the screen until *predicate* likes it.

    Every input burst after a screen change may be swallowed -- the game is
    not reading yet -- so nothing should be sent on the strength of a single
    read.  Returns the Screen that satisfied the predicate, or None.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            scr = grab_screen(**kw)
        except (OSError, MonitorError):
            time.sleep(interval)
            continue
        if predicate(scr):
            return scr
        time.sleep(interval)
    return None


def wait_for_text(needle: str, timeout: float = 30.0, **kw):
    return wait_for(lambda s: s.contains(needle), timeout=timeout, **kw)


def select_by_colour(kbd: Keyboard, target_row: int, timeout: float = 10.0) -> bool:
    """Move the menu highlight onto *target_row* and press Return.

    Driven by where the white row actually is, not by counting presses from
    an assumed starting point.
    """
    for _ in range(30):
        scr = grab_screen()
        hot = scr.highlighted_rows()
        if not hot:
            return False
        cur = hot[0]
        if cur == target_row:
            kbd.key("Return")
            return True
        kbd.key("Down" if cur < target_row else "Up")
    return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "screen":
        with Monitor() as m:
            if is_bitmap(m):
                print("(bitmap mode -- not readable as text)")
            s = read_screen(m)
        print(f"screen at ${s.address:04X}")
        for r, line in enumerate(s.rows()):
            print(f"{r:2d} {s.row_colour(r):2d} |{line}|")
    elif len(sys.argv) > 1 and sys.argv[1] == "clear-checkpoints":
        with Monitor() as m:
            print("deleted", m.checkpoints_clear())
    else:
        print(__doc__)
