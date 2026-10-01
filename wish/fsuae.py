"""The patched FS-UAE as the window's live backend: a probe, and one connection.

**The probe never connects.** `automap.target.monitor_listening` is a
`socket.create_connection(...).close()`, which is right for VICE and wrong
here: the patched fork's server closes its *listening* socket when a client
goes, so a probing connect could take the run's only debugging door with it, and
`label_backends()` probes every backend each time File > Preferences opens --
while somebody is playing. `listening` reads the kernel's table of TCP sockets
instead, which asks the question without touching the emulator.

**Wish never connects to the fork itself.** The fork serves one client per run
and closes its door for good when that client leaves, so a Wish that held the
connection would end the player's debugging when it closed. A background helper
(`automap.fsuaehelper`) holds it instead and outlives Wish; `connect()` finds
that helper, or starts one when the fork is listening and none runs, and reads
memory through it. **If the helper itself dies while the game runs, the
connection cannot be remade:** the fork never listens again once its one client
has left, so the player has to restart FS-UAE. Starting is not waited for:
`connect()` raises `FsuaeError` (a `NotConnected`) and the window asks again on
its next tick.

**`connect()` opens the helper's socket once per emulator run.** The window
detaches on any `NotConnected` and attaches again on its next tick, and
`AmigaTarget.close()` leaves the transport alone on purpose. The transport, the
machine found on it and the data hunk's base are cached together, so a retry
after a failed or unfinished locate costs one packet and not a second socket.
The machine and the base are checked against memory on every `connect()`,
because a reset inside the same emulator run can load another title, or the same
one somewhere else, on the same socket.
"""

from __future__ import annotations

import os
import time

from automap import amiga, fsuaehelper

from . import debuglog
from .backends import Backend

#: `/proc/net` is where a Linux kernel lists its TCP sockets. Not a constant of
#: the emulator, so a test can point `listening` at a directory it wrote.
PROC_NET = "/proc/net"

#: `/proc/net/tcp` prints an address as the little-endian hex of the `u32`, so
#: 127.0.0.1 is `0100007F`, and 0.0.0.0 is eight zeros. State `0A` is LISTEN.
LOOPBACK = "0100007F"
ANY = "00000000"
LISTEN = "0A"

#: The same two addresses in `/proc/net/tcp6`'s 32-digit form: `::ffff:127.0.0.1`
#: -- what a dual-stack listener that took a loopback IPv4 client looks like --
#: and `::`. The fork binds an IPv4 loopback address, so this only matters if a
#: build ever changes that.
LOOPBACK6 = "0000000000000000FFFF00000100007F"
ANY6 = "0" * 32

#: The soonest a second sweep of the machine's memory may start after the last.
#: The fork copies a range a byte at a time inside its frame handler, so each
#: 512 KB read makes the emulated machine miss a frame, and the window retries a
#: title that has not loaded yet on every tick.
SWEEP_EVERY = 5.0

#: The soonest a second helper may be started after the last one was. A helper
#: that exits at once (the fork is held by another client, say) would otherwise
#: be started again on every one-second tick.
HELPER_RETRY = 10.0

#: A sweep reads the machine's memory in pieces this big, and stops for the tick
#: once it has spent `SWEEP_DEADLINE` seconds. `connect()` runs on the window's
#: timer, so one call may not hold the window for the twenty seconds a
#: half-megabyte read is allowed; what was read is kept and the next call goes
#: on from there. A piece waits `POLL_TIMEOUT`, so a call takes about the
#: deadline plus that.
SWEEP_CHUNK = 0x10000
SWEEP_DEADLINE = 1.0


def _listeners(path: str, wanted: frozenset[str]) -> set[int]:
    """Ports in state LISTEN on one of `wanted`'s addresses, out of one file."""
    ports: set[int] = set()
    with open(path, encoding="ascii") as table:
        next(table, None)                       # the column headings
        for row in table:
            fields = row.split()
            if len(fields) < 4 or fields[3] != LISTEN:
                continue
            address, _, port = fields[1].rpartition(":")
            if address.upper() in wanted:
                ports.add(int(port, 16))
    return ports


def listening(port: int | None = None, proc: str = PROC_NET) -> bool:
    """Is a helper alive for `port`, or something listening there for TCP?

    The second half asks about loopback (or every address). **Opens no
    socket**, which is what this function is for -- see the module docstring.
    False on any `OSError` and on a machine with no `/proc/net`, and it never
    raises: it runs on a timer with no emulator present most of the
    time. Where there is no `/proc` the backend is simply never offered, which
    is right, because the emulator is a Linux x86-64 binary.
    """
    port = amiga.FSUAE_PORT if port is None else port
    try:
        if fsuaehelper.find(port, fsuaehelper.runtime_dir()) is not None:
            return True
        return (port in _listeners(os.path.join(proc, "tcp"),
                                   frozenset({LOOPBACK, ANY}))
                or port in _listeners(os.path.join(proc, "tcp6"),
                                      frozenset({LOOPBACK6, ANY6})))
    except (OSError, ValueError):
        return False


#: What `connect()` keeps, together, for the life of one emulator run.
_transport: amiga.FsuaeGdb | None = None
_port: int | None = None
_machine: amiga.AmigaMachine | None = None
_base: int | None = None
_swept_at: float | None = None


#: The helper this process started, and when. The `Popen` is kept so that it is
#: reaped and its exit code reaches the debug log; `reset()` leaves both, so a
#: dropped connection does not start a helper at once.
_helper = None
_helper_at: float | None = None


#: The pieces of an unfinished sweep, `{address: bytes}`.
_sweep_cache: dict[int, bytes] = {}


class SweepPaused(amiga.FsuaeError):
    """The sweep spent its time for this tick and goes on at the next."""


def _chunked_read(transport, now, deadline_clock):
    """A `read(addr, length)` for `locate_machines` that stops at the deadline."""
    deadline = deadline_clock() + SWEEP_DEADLINE
    fetched = 0

    def read(base: int, length: int) -> bytes:
        nonlocal fetched
        out = bytearray()
        for at in range(base, base + length, SWEEP_CHUNK):
            blob = _sweep_cache.get(at)
            if blob is None:
                # At least one piece per call, so a slow machine still finishes.
                if fetched and deadline_clock() >= deadline:
                    raise SweepPaused("still sweeping the Amiga's memory")
                blob = transport.read_memory(
                    at, min(SWEEP_CHUNK, base + length - at),
                    timeout=amiga.FsuaeGdb.POLL_TIMEOUT)
                _sweep_cache[at] = blob
                fetched += 1
            out += blob
        return bytes(out)

    return read


def reset() -> None:
    """Forget the connection to the helper, so the next `connect()` opens a new one.

    Costs nothing: the helper keeps the emulator's connection.
    """
    global _transport, _port, _machine, _base, _swept_at
    if _transport is not None:
        _transport.close()
    _transport = _port = _machine = _base = _swept_at = None
    _sweep_cache.clear()


def forget_helper() -> None:
    """Forget the helper this process started. For tests; the helper itself runs on."""
    global _helper, _helper_at
    _helper = _helper_at = None


def _ensure_helper(port: int, clock, starter) -> None:
    """Start a helper for `port` unless this process has one running or just tried."""
    global _helper, _helper_at
    if _helper is not None:
        code = _helper.poll()
        if code is None:
            return                              # still starting, or running
        debuglog.note("the Amiga connection helper exited with %s", code)
        _helper = None
    now = clock()
    if _helper_at is not None and now - _helper_at < HELPER_RETRY:
        return
    _helper_at = now
    try:
        _helper = starter(port, fsuaehelper.runtime_dir())
    except OSError as exc:
        debuglog.note("the Amiga connection helper would not start: %s", exc)


def _open_transport(wanted: int, port, opener, clock, starter) -> amiga.FsuaeGdb:
    """A transport through the helper, or through `opener` when one is given."""
    if opener is not None:
        return amiga.FsuaeGdb(port=port, opener=opener)
    info = fsuaehelper.find(wanted, fsuaehelper.runtime_dir())
    if info is not None:
        # This runs on the window's timer, so neither the connect nor the
        # greeting may wait the transport's usual twenty seconds; a timeout is
        # a FsuaeError and the window asks again on its next tick.
        short = amiga.FsuaeGdb.POLL_TIMEOUT
        gdb = amiga.FsuaeGdb(
            port=wanted, timeout=short,
            opener=lambda: fsuaehelper.PLATFORM.connect(info, short))
        gdb.timeout = amiga.FsuaeGdb.TIMEOUT    # the sweep's reads need it
        return gdb
    if listening(wanted):
        _ensure_helper(wanted, clock, starter)
        raise amiga.FsuaeError("starting the connection helper")
    raise amiga.FsuaeError(f"nothing is listening on port {wanted}")


def connect(port: int | None = None, opener=None,
            clock=time.monotonic, starter=fsuaehelper.start,
            deadline_clock=time.monotonic) -> amiga.AmigaTarget:
    """A target on the running Amiga, or a `NotConnected` saying what is missing.

    `opener`, `clock`, `starter` and `deadline_clock` are injected so the tests need no emulator,
    no waiting and no helper process. With an `opener` the helper is not
    consulted. Raises `amiga.FsuaeError` -- a `NotConnected`, so the window goes
    back to waiting -- when nothing is listening, when no title with a row in
    `amiga.MACHINES` is in memory yet, and when the sweep is being rate-limited.
    A raise after the socket has opened leaves the transport cached.

    The cached transport belongs to one `port`; another port replaces it. A
    cached title is confirmed by reading its anchor at the cached base -- a few
    bytes, one packet -- and when the anchor is not there the title and base are
    forgotten and the sweep runs again. The **transport is kept**: closing it
    would end the run's debugging, so an unloaded game is waited out and not
    reconnected to.
    """
    global _transport, _port, _machine, _base, _swept_at
    wanted = amiga.FSUAE_PORT if port is None else port
    if _transport is not None and (_transport.lost or _transport.sock is None
                                   or _port != wanted):
        reset()
    if _transport is None:
        _transport = _open_transport(wanted, port, opener, clock, starter)
        _port = wanted
    if _machine is not None:
        held = _transport.read_memory(_base + _machine.anchor_offset,
                                      len(_machine.anchor))
        if held != _machine.anchor:
            _machine = _base = None
    if _machine is None:
        now = clock()
        if (not _sweep_cache and _swept_at is not None
                and now - _swept_at < SWEEP_EVERY):
            raise amiga.FsuaeError(
                f"the last sweep of the Amiga's memory was {now - _swept_at:.1f}"
                f"s ago and no more than one is made every {SWEEP_EVERY:.0f}s")
        try:
            found = amiga.locate_machines(
                _chunked_read(_transport, clock, deadline_clock),
                amiga.MACHINES.values(), sweep_all=True)
        except SweepPaused:
            raise
        except BaseException:
            _swept_at = clock()
            _sweep_cache.clear()
            raise
        _swept_at = clock()
        _sweep_cache.clear()
        if not found:
            raise amiga.FsuaeError(
                "none of the titles this knows is in the Amiga's memory yet")
        if len(found) > 1:
            raise amiga.FsuaeError(
                "more than one title's anchor is in the Amiga's memory: "
                + ", ".join(sorted(found)))
        (title, bases), = found.items()
        if len(bases) > 1:
            raise amiga.FsuaeError(
                f"{title}'s anchor appears at more than one place: "
                + ", ".join(f"{b:#x}" for b in bases))
        _machine = next(m for m in amiga.MACHINES.values()
                        if m.title == title)
        _base = bases[0]
    return amiga.AmigaTarget(_transport, _machine, data_base=_base)


#: The row `wish.backends._amiga_fsuae()` offers behind its flag. The probe reads
#: the kernel's socket table and the opener is the cached `connect`, so neither
#: opens a second socket on the emulator's only debugging door. A poll of about
#: 20 ms is served from the running machine's frame handler, hence `disturbs`
#: False and the same 200 ms as VICE. The port is the fork's default and stays
#: out of the hint.
AMIGA_FSUAE = Backend(
    name="Amiga (FS-UAE)",
    probe=listening,
    connect=connect,
    setup_hint="Run the game in grahambates' fork of FS-UAE, not stock FS-UAE.",
    default_interval_ms=200,
    disturbs=False,
    verified=True,
)
