"""Which Amiga title is in memory and where, kept between the window's polls.

The title, the base of its anchor and the time of the last sweep belong
together: a reset inside one emulator run can load another title, or the same
one elsewhere, so the cached title is confirmed with a few bytes at its anchor
on every call and the sweep runs again only when that fails.

**A sweep never holds the window for long.** `target()` runs on the window's
timer, and half a megabyte a region is too much for one tick, so memory is read
in pieces. Once `SWEEP_DEADLINE` seconds are spent the call raises a
`not-connected` error, the pieces already read are kept for `SWEEP_CACHE_AGE`
seconds, and the next call goes on from there. After a piece fails, the next
sweep uses `SWEEP_SMALL_CHUNK`, so a machine too slow for the big piece still
gets through.
"""

from __future__ import annotations

import time

from automap import amiga


class Locator:
    """One emulator run's cached machine, anchor base and sweep progress."""

    #: The soonest a second sweep may start after the last one ended.
    SWEEP_EVERY = 5.0

    #: Memory is read in pieces this big, and the small size after a failure.
    SWEEP_CHUNK = 0x10000
    SWEEP_SMALL_CHUNK = 0x4000

    #: How long one call may spend reading pieces (one piece is always read).
    SWEEP_DEADLINE = 1.0

    #: How long a piece read for an unfinished sweep stays usable. A game that
    #: reboots between two ticks must not be searched as one memory made of old
    #: and new pieces.
    SWEEP_CACHE_AGE = 5.0

    def __init__(self, clock=time.monotonic, error=amiga.GuestError):
        self._clock = clock
        self._error = error
        #: Raised when the time for this tick is spent; the sweep goes on later.
        self.paused = type("SweepPaused", (error,), {})
        self._pieces: dict[int, tuple[float, bytes]] = {}
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
        for at in [a for a, (when, _) in self._pieces.items()
                   if started - when > self.SWEEP_CACHE_AGE]:
            del self._pieces[at]

        def read(base: int, length: int) -> bytes:
            nonlocal fetched
            out = bytearray()
            for at in range(base, base + length, self._piece):
                held = self._pieces.get(at)
                if held is None:
                    if fetched and self._clock() >= deadline:
                        raise self.paused(
                            "Still sweeping the Amiga's memory.")
                    blob = read_memory(at, min(self._piece, base + length - at))
                    self._pieces[at] = (self._clock(), blob)
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
                               len(self.machine.anchor))
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
                self._piece = self.SWEEP_SMALL_CHUNK
                raise
            self.swept_at = self._clock()
            self._pieces.clear()
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
        return factory(transport, self.machine, anchor_base=self.base)
