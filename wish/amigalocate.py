"""Which Amiga title is in memory and where, kept between the window's polls.

The title, the base of its anchor and the time of the last sweep belong
together: a reset inside one emulator run can load another title, or the same
one elsewhere, so the cached title is confirmed with a few bytes at its anchor
on every call and the sweep runs again only when that fails.

**A sweep never holds the window for long.** `target()` runs on the window's
timer, and half a megabyte a region is too much for one tick, so memory is read
in pieces. Once `SWEEP_DEADLINE` seconds are spent the call raises a
`not-connected` error, the pieces already read are kept, and the next call goes
on from there. After a piece times out, the next sweep uses
`SWEEP_SMALL_CHUNK`, so a machine too slow for the big piece still gets
through; a finished sweep goes back to the big one. A call takes about two
seconds at most: the anchor re-read, then pieces within `SWEEP_DEADLINE`.
"""

from __future__ import annotations

import time

from automap import amiga


class Locator:
    """One emulator run's cached machine, anchor base and sweep progress."""

    #: The soonest a second sweep may start after the last one ended.
    SWEEP_EVERY = 5.0

    #: Memory is read in pieces this big, and the small size after a timeout.
    SWEEP_CHUNK = 0x10000
    SWEEP_SMALL_CHUNK = 0x4000

    #: How long one call may spend reading pieces. A piece is started only when
    #: a full `PIECE_TIMEOUT` is left before this, except the first of a call,
    #: so a timeout always means the emulator was slow and never that the
    #: tick's budget ran out. A call takes `SWEEP_DEADLINE` at most.
    SWEEP_DEADLINE = 1.5

    #: What every piece, and the anchor re-read, is given to answer.
    PIECE_TIMEOUT = 0.5

    #: How long an unfinished sweep may go without gaining a piece before what
    #: it holds is thrown away. This catches only a gap in the ticks (the window
    #: not asking for five seconds, say). It does not detect a reboot or a
    #: reload during a sweep whose ticks keep adding pieces; the result of such
    #: a sweep is caught afterwards, by the "more than one place" check and by
    #: the anchor re-read at the next call. A slow machine whose ticks keep
    #: adding pieces is not limited in total time.
    SWEEP_CACHE_AGE = 5.0


    def __init__(self, clock=time.monotonic, error=amiga.GuestError):
        self._clock = clock
        self._error = error
        #: Raised when the time for this tick is spent; the sweep goes on later.
        self.paused = type("SweepPaused", (error,), {})
        self._pieces: dict[int, tuple[float, bytes]] = {}   # when read, bytes
        self._piece = self.SWEEP_CHUNK
        self.machine: amiga.AmigaMachine | None = None
        self.base: int | None = None
        self.swept_at: float | None = None

    def forget(self) -> None:
        self.machine = self.base = self.swept_at = None
        self._pieces.clear()
        self._piece = self.SWEEP_CHUNK

    def _reader(self, read_memory):
        """A `read(addr, length)` for `locate_machines` that stops at the deadline."""
        started = self._clock()
        deadline = started + self.SWEEP_DEADLINE
        fetched = 0
        if self._pieces and started - max(
                when for when, _ in self._pieces.values()) > self.SWEEP_CACHE_AGE:
            self._pieces.clear()

        def read(base: int, length: int) -> bytes:
            nonlocal fetched
            out = bytearray()
            for at in range(base, base + length, self._piece):
                held = self._pieces.get(at)
                if held is None:
                    if fetched and (deadline - self._clock()
                                    < self.PIECE_TIMEOUT):
                        raise self.paused(
                            "Still sweeping the Amiga's memory.")
                    try:
                        blob = read_memory(
                            at, min(self._piece, base + length - at),
                            timeout=self.PIECE_TIMEOUT)
                    except Exception as exc:
                        if getattr(exc, "timed_out", False):
                            self._piece = self.SWEEP_SMALL_CHUNK
                        raise
                    self._pieces[at] = (started, blob)
                    fetched += 1
                else:
                    blob = held[1]
                out += blob
            return bytes(out)

        return read

    def target(self, read_memory, transport,
               factory=amiga.AmigaTarget) -> amiga.AmigaTarget:
        """A target on the title in memory, or the `error` saying what is missing."""
        if self.machine is not None:
            held = read_memory(self.base + self.machine.anchor_offset,
                               len(self.machine.anchor),
                               timeout=self.PIECE_TIMEOUT)
            if held != self.machine.anchor:
                self.machine = self.base = None
        if self.machine is None:
            now = self._clock()
            if (not self._pieces and self.swept_at is not None
                    and now - self.swept_at < self.SWEEP_EVERY):
                raise self._error(
                    f"The last sweep of the Amiga's memory was "
                    f"{now - self.swept_at:.1f}s ago and no more than one is "
                    f"made every {self.SWEEP_EVERY:.0f}s.")
            try:
                found = amiga.locate_machines(
                    self._reader(read_memory), amiga.MACHINES.values(),
                    sweep_all=True)
            except self.paused:
                raise
            except Exception:
                self.swept_at = self._clock()
                self._pieces.clear()
                raise
            self.swept_at = self._clock()
            self._pieces.clear()
            self._piece = self.SWEEP_CHUNK
            if not found:
                raise self._error(
                    "None of the titles this knows is in the Amiga's memory yet.")
            if len(found) > 1:
                raise self._error(
                    "More than one title is in the Amiga's memory: "
                    + ", ".join(sorted(found)) + ".")
            (title, bases), = found.items()
            if len(bases) > 1:
                raise self._error(f"{title} is in the Amiga's memory more than once.")
            self.machine = next(m for m in amiga.MACHINES.values()
                                if m.title == title)
            self.base = bases[0]
        try:
            return factory(transport, self.machine, anchor_base=self.base)
        except amiga.GuestError as exc:
            # An intact anchor with a data hunk that is not where it was: the
            # target's own check fails on every call unless the sweep runs
            # again. A `PipeError` is also a `GuestError` but says only that
            # the pipe failed, so what was found stays.
            if not isinstance(exc, amiga.PipeError):
                self.machine = self.base = None
            raise
