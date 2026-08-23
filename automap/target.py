"""Where live bytes come from.

`docs/96-live-memory-automapper.md` fixes the contract at two methods, and
deliberately no more: breakpoints and stepping are VICE-only luxuries, and
keeping them out means a second backend -- a Commodore 64 Ultimate over its
network interface -- does not have to pretend it has them.

`ViceTarget` holds **one** connection for the whole session and calls
`resume()` after each burst, rather than reconnecting per poll like
`tools/session.py` does.

The reason turned out to be the opposite of the one this was designed for.
Polling does **not** stall the machine — measured against the KERNAL jiffy clock,
each `fix()` hands the emulation about **14.3 ms of extra emulated time**, so at
the default 200 ms the game runs about **7% fast**. The cost is per `resume()`,
not per byte: a 7168-byte read costs the same as one `peek`, and four peeks with
four resumes cost 45.9 ms against 14.4 ms batched. So batch reads and keep
resumes rare -- right advice, wrong reason.

Two hazards from `docs/70-driving-the-game.md` shape what is *not* here:

* **No checkpoints.** Closing a socket while one is armed leaves VICE re-entering
  the monitor on a socket that no longer exists, and only a kill recovers it.
  Polling needs none, so none are offered.
* **Validate before trust.** The game is heavily overlaid, so an address means
  what we think only while its overlay is resident. `PartyFix` refuses a reading
  that cannot be true rather than drawing nonsense.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from typing import Protocol

from por import games

from .screen import SCREEN_COLS, codes_to_text, is_bitmap, screen_address
from .vice import Monitor, monitor_address

#: A child of the `wish` logger, so `wish/debuglog.py`'s handler takes these
#: when the log is on and its level swallows them when it is off.
_log = logging.getLogger("wish.automap.target")

# Pool of Radiance's save image, as names, because tests and documents cite
# them and because they are what the *save* holds. They are NOT what the memory
# fallback reads: `$49C0` is refreshed only when `$1A3C` flushes `$C04B` into
# it, so it lags a move -- and in a running Curse the same address is engine
# code (`tests/test_curselive.py`).
PARTY_BASE = 0x4900
PARTY_X, PARTY_Y, PARTY_FACING = 0x49C0, 0x49C1, 0x49C2
PARTY_CLOCK = 0x49C7

#: The position triple, and the clock: three bytes each. Two reads rather than
#: one ten-byte read, because the live triple is outside the save image and the
#: clock is inside it, so they no longer sit next to each other. That costs
#: nothing measurable -- `ViceTarget.fix` puts both inside one resume, and the
#: cost of a monitor round trip is the resume and not the bytes.
POSITION_BYTES = 3
CLOCK_BYTES = 3

# The game's own status line, e.g. "E 16:48  5,2" -- facing, clock, x, y. It is
# correct the moment the screen settles, where the memory copy at $49C0 lags a
# move. Taken from tools/session.py, which learned this the hard way.
STATUS_ROW = 14
RE_STATUS = re.compile(r"([NESW]) +(\d+):(\d+) +(\d+),(\d+)")
FACING_LETTERS = {"N": 0, "E": 1, "S": 2, "W": 3}

GRID = 16


class Target(Protocol):
    """The whole backend contract."""

    def read(self, addr: int, length: int) -> bytes: ...
    def write(self, addr: int, data: bytes) -> None: ...


@dataclass(frozen=True)
class Fix:
    """One reading of where the party is.

    `source` is "status" or "memory". A status-line fix is authoritative and is
    what the map runs on; a memory fix is the engine's own live triple, read
    only when the status line is not on screen -- in camp, in combat, in a
    menu. It used to be the save image's copy, which lagged a move; it is not
    that any more (#29), which is why "a move behind" no longer appears here.

    `clock` is the game clock in minutes since midnight, or None where it could
    not be read. It costs nothing -- the status line already carries it and the
    memory fallback reads it in the same ten bytes -- and it is what lets a
    *refused* step be spotted: see `Automapper.poll`.
    """

    x: int
    y: int
    facing: int
    source: str
    clock: int | None = None

    @property
    def square(self) -> tuple[int, int]:
        return self.x, self.y


def _plausible(x: int, y: int, facing: int) -> bool:
    return 0 <= x < GRID and 0 <= y < GRID and 0 <= facing < 4


def party_fix(read, game: games.Game | None = None) -> Fix | None:
    """Where the party is, read through any backend's `read(addr, length)`.

    Tries the game's own status line first and falls back to the engine's live
    position triple. Returns None on a bitmap screen (title, credits), in camp,
    in a menu, or before a save is loaded -- all ordinary states, not errors.
    The caller holds its last good fix rather than drawing garbage.

    **The status line is title-independent and the fallback is not.** Every
    title draws `E 16:48  5,2` on the same row 14 of the same screen, so the
    preferred source needed no change at all; the memory copy is at an address
    that was measured per title and is `Game.live_position`.

    **A title whose triple has never been measured gets no fallback**, and says
    so by having none: `live_position` is None, this returns None, and the map
    simply waits for a status line. Falling back to another title's address
    would answer with a square the party is not on, which is worse than not
    answering -- `test_curselive.py::test_the_memory_fallback_would_misread_a_
    curse_machine` is what that looks like.

    Nothing here is VICE-specific, which is the point: reading the status line
    is four reads of ordinary memory, so a second backend gets it for free and
    a test gets it against a dictionary of bytes.
    """
    game = game or games.DEFAULT
    if is_bitmap(read):
        return None
    base = screen_address(read)
    row = read(base + STATUS_ROW * SCREEN_COLS, SCREEN_COLS)
    m = RE_STATUS.search(codes_to_text(row))
    if m:
        facing = FACING_LETTERS[m.group(1)]
        x, y = int(m.group(4)), int(m.group(5))
        if _plausible(x, y, facing):
            clock = int(m.group(2)) * 60 + int(m.group(3))
            return Fix(x, y, facing, "status", clock)
    if game.live_position is None:
        return None
    x, y, facing = read(game.live_position, POSITION_BYTES)[:POSITION_BYTES]
    if _plausible(x, y, facing):
        c = read(game.clock_base, CLOCK_BYTES)
        clock = c[2] * 60 + c[1] * 10 + c[0]
        return Fix(x, y, facing, "memory", clock)
    return None


def read_fix(target, game: games.Game | None = None) -> Fix | None:
    """One fix from whatever this target is.

    A target may answer for itself -- `ViceTarget` does, to keep its burst of
    reads inside a single resume, and `ReplayTarget` does because it has canned
    fixes and no memory to read. Anything else is read the neutral way, so a
    backend only has to supply `read`.
    """
    own = getattr(target, "fix", None)
    if own is not None:
        return own(game)
    return party_fix(target.read, game)


class NotConnected(RuntimeError):
    """No emulator to talk to. Expected, and recoverable -- wait and retry."""


def who_holds_hint(port: int | None = None) -> str:
    """The command that names the process holding a port, on this platform.

    `ss` is Linux-only, and it was in the message a Windows user is most
    likely to see -- the one about another client already having the monitor.

    Defaults to `$POR_MONITOR`'s port rather than the literal `6502`: with `$POR_MONITOR`
    set, naming 6502 would send the reader after the wrong process -- and under
    the instance pool 6502 is a *human's* game, which is the one thing nobody
    should be told to go and look at.
    """
    if port is None:
        port = monitor_address()[1]
    if sys.platform == "win32":
        return f"`netstat -ano | findstr {port}` names it"
    if sys.platform == "darwin":
        return f"`lsof -nP -iTCP:{port}` names it"
    return f"`ss -tnp | grep {port}` names it"


class MonitorBusy(NotConnected):
    """The connection was made and then never served: somebody else has it.

    **VICE serves exactly one binary-monitor connection and silently ignores a
    second.** The two cases look identical from the outside unless they are
    separated here: with another client attached the connect *succeeds* and the
    connection is then never answered. `ViceTarget` pings on attach to tell
    them apart, because "waiting for a game" is the wrong thing to say about a
    game that is running.

    **What separates them is the ping, not the connect.** An earlier version
    read any timeout as busy, on the assumption that with nothing listening the
    connect is *refused* at once. That holds on Linux and does not hold on
    Windows, where a packet filter drops the SYN rather than answering it and
    the connect times out instead -- so wish told a Windows user with no
    emulator running that something else was attached to it. Only a timeout on
    the greeting means busy now; a timeout on the connect means absent.

    A subclass of `NotConnected` so every caller that already retries keeps
    doing so -- when the other client goes away the next retry attaches.
    """

    def __init__(self, message: str = ""):
        super().__init__(message or (
            "something else is attached to the emulator's monitor - VICE "
            f"serves one connection at a time. {who_holds_hint()}"))


def monitor_listening(host: str | None = None, port: int | None = None,
                      timeout: float = 0.25) -> bool:
    """Is a binary monitor accepting connections?

    Cheap enough to call on a timer, so the map can sit waiting for the game to
    start rather than refusing to open without it.

    Defaults to the same address `Monitor` connects to, resolved at call
    time so pointing a running window at a pooled instance works.
    They were the literals `"127.0.0.1"` and `6502` until `$POR_MONITOR`
    existed, at which point the probe would have tested one port and the
    connect used another.
    """
    default_host, default_port = monitor_address()
    if host is None:
        host = default_host
    if port is None:
        port = default_port
    import socket
    try:
        socket.create_connection((host, port), timeout).close()
        return True
    except OSError:
        return False


class ViceTarget:
    """A live VICE session, held open.

    Not a context manager on purpose -- the point is that it outlives any one
    read. Call `close()` when done.
    """

    #: How long to wait for the greeting ping. Short on purpose: a busy monitor
    #: never answers at all, and this runs on the retry timer.
    GREETING = 1.0

    def __init__(self, host: str | None = None, port: int | None = None,
                 timeout: float = 5.0):
        kw = {}
        if host is not None:
            kw["host"] = host
        if port is not None:
            kw["port"] = port
        # Two stages, and they mean different things. Nothing there at all is a
        # failure to *connect*, however the platform spells it -- refused on
        # Linux, usually a timed-out SYN behind the Windows firewall. Only a
        # connection that is made and then not answered is a busy monitor.
        try:
            self._mon = Monitor(timeout=timeout, **kw)
            self._mon.__enter__()      # connecting stops the machine...
        except OSError as exc:
            self._shut()
            raise NotConnected(str(exc)) from exc
        try:
            self._greet()              # ...and this proves it is ours...
            self._mon.resume()         # ...and this lets it run again
        except TimeoutError as exc:
            self._shut()
            raise MonitorBusy() from exc
        except OSError as exc:
            self._shut()
            raise NotConnected(str(exc)) from exc
        self._open = True

    def _greet(self) -> None:
        """One ping, with a short deadline. Times out iff somebody else has it.

        The socket's own timeout is what expires -- `Monitor.__enter__` only
        connects, so without this the first *read* would be where a busy
        monitor showed up, minutes later and as a bad read rather than as the
        plain fact that another client holds it.
        """
        sock = self._mon.sock
        was = sock.gettimeout()
        sock.settimeout(self.GREETING)
        try:
            self._mon.ping()
        finally:
            sock.settimeout(was)

    def _shut(self) -> None:
        """Close a half-made connection. Never raises; there is nothing to
        report that the exception on its way out does not already say."""
        try:
            if getattr(self, "_mon", None) is not None:
                self._mon.__exit__(None, None, None)
        except Exception as exc:
            _log.debug("could not close a half-made connection: %s", exc)

    def close(self) -> None:
        if self._open:
            self._open = False
            self._mon.__exit__(None, None, None)

    def __del__(self):                  # pragma: no cover - best effort
        try:
            self.close()
        except Exception:
            # Deliberately the one handler here that says nothing. A `__del__`
            # can run during interpreter shutdown, where the logging machinery
            # may already be torn down and a log call is itself what raises;
            # anything raised here goes to `sys.unraisablehook`, which
            # `wish/debuglog.py` installs, so it is not lost either way.
            pass

    # -- Target ----------------------------------------------------------

    def read(self, addr: int, length: int) -> bytes:
        data = self._mon.read(addr, length)
        self._mon.resume()
        return data

    def write(self, addr: int, data: bytes) -> None:
        self._mon.write(addr, data)
        self._mon.resume()

    # -- what the automapper actually asks for ---------------------------

    def fix(self, game: games.Game | None = None) -> Fix | None:
        """`party_fix` over this connection, with exactly one resume.

        The reads go through the monitor directly rather than through
        `self.read`, which resumes after every call: each resume hands the
        emulation ~14.3 ms of extra emulated time, so four of them per poll
        would quadruple the distortion for no extra bytes.

        Raises `NotConnected` if the emulator has gone away, which is how the
        window knows to go back to waiting for it.
        """
        try:
            return party_fix(self._mon.read, game)
        except OSError as exc:
            self._open = False
            raise NotConnected(str(exc)) from exc
        finally:
            try:
                self._mon.resume()
            except OSError:
                pass

    def read_blocks(self, blocks) -> list[bytes]:
        """Several ranges, stopping the machine once and resuming once.

        The live panel wants `$4900`-`$64FF` and the roster page every time it
        polls. Through `read` that would be two resumes and ~28.6 ms of extra
        emulated time; batched it is one resume, the same as a single `peek`.
        """
        try:
            return [self._mon.read(addr, length) for addr, length in blocks]
        except OSError as exc:
            self._open = False
            raise NotConnected(str(exc)) from exc
        finally:
            try:
                self._mon.resume()
            except OSError:
                pass

    def screen(self):
        """A full screen snapshot, for debugging what the mapper is seeing."""
        from .screen import read_screen
        try:
            return read_screen(self._mon.read)
        finally:
            self._mon.resume()


class ReplayTarget:
    """A fake `Target` that walks a fixed list of fixes.

    Lets the model and the window be exercised with no emulator, which is what
    the tests use and what makes the drawing code developable offline.
    """

    def __init__(self, fixes: list[Fix], memory: dict[int, bytes] | None = None):
        self._fixes = list(fixes)
        self._memory = memory or {}
        self._i = 0

    def read(self, addr: int, length: int) -> bytes:
        for base, blob in self._memory.items():
            if base <= addr and addr + length <= base + len(blob):
                off = addr - base
                return blob[off:off + length]
        return bytes(length)

    def write(self, addr: int, data: bytes) -> None:
        raise NotImplementedError("ReplayTarget is read-only")

    def close(self) -> None:
        pass

    def fix(self, game: games.Game | None = None) -> Fix | None:
        if self._i >= len(self._fixes):
            return self._fixes[-1] if self._fixes else None
        f = self._fixes[self._i]
        self._i += 1
        return f


class MemoryTarget:
    """A `Target` over a dictionary of {address: bytes}.

    Everything the live code needs can be exercised against this -- including
    `party_fix`, which is the point of it being a free function. Reads outside
    the supplied blocks come back as zeros, which is what unwritten RAM would
    look like anyway.
    """

    def __init__(self, memory: dict[int, bytes] | None = None):
        self.memory: dict[int, bytes] = dict(memory or {})
        self.reads: list[tuple[int, int]] = []

    def read(self, addr: int, length: int) -> bytes:
        self.reads.append((addr, length))
        out = bytearray(length)
        for base, blob in self.memory.items():
            for i in range(length):
                if base <= addr + i < base + len(blob):
                    out[i] = blob[addr + i - base]
        return bytes(out)

    def write(self, addr: int, data: bytes) -> None:
        self.memory[addr] = bytes(data)

    def close(self) -> None:
        pass
