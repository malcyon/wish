"""The patched FS-UAE as the window's live backend: a probe, and one connection.

**The probe never connects.** `automap.target.monitor_listening` is a
`socket.create_connection(...).close()`, which is right for VICE and wrong
here: the patched fork's server closes its *listening* socket when a client
goes, so a probing connect could take the run's only debugging door with it, and
`label_backends()` probes every backend each time File > Preferences opens --
while somebody is playing. `listening` reads the kernel's table of TCP sockets
instead, which asks the question without touching the emulator.

**`connect()` opens the socket once per emulator run.** The window detaches on
any `NotConnected` and attaches again on its next tick, and
`AmigaTarget.close()` leaves the transport alone on purpose, so a `connect()`
that built a fresh `FsuaeGdb` every time would find nothing listening the moment
the first one had been dropped -- and the player would have to restart the
emulator, and with it the game. The transport, the machine found on it and the
data hunk's base are cached together, so a retry after a failed or unfinished
locate costs one packet and not a second socket. The machine and the base are
checked against memory on every `connect()`, because a reset inside the same
emulator run can load another title, or the same one somewhere else, on the same
socket.
"""

from __future__ import annotations

import os
import time

from automap import amiga

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
    """Is something listening for TCP on loopback (or every address) at `port`?

    **Opens no socket**, which is what this function is for -- see the module
    docstring. False on any `OSError` and on a machine with no `/proc/net`, and
    it never raises: it runs on a timer with no emulator present most of the
    time. Where there is no `/proc` the backend is simply never offered, which
    is right, because the emulator is a Linux x86-64 binary.
    """
    port = amiga.FSUAE_PORT if port is None else port
    try:
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


def reset() -> None:
    """Forget the connection, so the next `connect()` opens a new socket.

    The emulator side of that is only useful when the emulator has been
    restarted: the fork does not listen again after a client leaves.
    """
    global _transport, _port, _machine, _base, _swept_at
    if _transport is not None:
        _transport.close()
    _transport = _port = _machine = _base = _swept_at = None


def connect(port: int | None = None, opener=None,
            clock=time.monotonic) -> amiga.AmigaTarget:
    """A target on the running Amiga, or a `NotConnected` saying what is missing.

    `opener` and `clock` are injected so the tests need no emulator and no
    waiting. Raises `amiga.FsuaeError` -- a `NotConnected`, so the window goes
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
        # Sends `vCont;c`: the fork sits halted in warp until a client does.
        _transport = amiga.FsuaeGdb(port=port, opener=opener)
        _port = wanted
    if _machine is not None:
        held = _transport.read_memory(_base + _machine.anchor_offset,
                                      len(_machine.anchor))
        if held != _machine.anchor:
            _machine = _base = None
    if _machine is None:
        now = clock()
        if _swept_at is not None and now - _swept_at < SWEEP_EVERY:
            raise amiga.FsuaeError(
                f"the last sweep of the Amiga's memory was {now - _swept_at:.1f}"
                f"s ago and no more than one is made every {SWEEP_EVERY:.0f}s")
        _swept_at = now
        found = amiga.locate_machines(_transport.read_memory,
                                      amiga.MACHINES.values())
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
