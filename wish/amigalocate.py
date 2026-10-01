"""Which Amiga title is in memory and where, kept between the window's polls.

The title, the base of its data hunk and the time of the last sweep belong
together: a reset inside one emulator run can load another title, or the same
one elsewhere, so the cached title is confirmed with a few bytes at its anchor
on every call and the sweep runs again only when that fails. A sweep reads half
a megabyte a region, so it is rate-limited.
"""

from __future__ import annotations

import time

from automap import amiga


class Locator:
    """One emulator run's cached machine, base and sweep time."""

    #: The soonest a second sweep may start after the last.
    SWEEP_EVERY = 5.0

    def __init__(self, clock=time.monotonic, error=amiga.GuestError):
        self._clock = clock
        self._error = error
        self.machine: amiga.AmigaMachine | None = None
        self.base: int | None = None
        self.swept_at: float | None = None

    def forget(self) -> None:
        self.machine = self.base = self.swept_at = None

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
            if (self.swept_at is not None
                    and now - self.swept_at < self.SWEEP_EVERY):
                raise self._error(
                    f"the last sweep of the Amiga's memory was "
                    f"{now - self.swept_at:.1f}s ago and no more than one is "
                    f"made every {self.SWEEP_EVERY:.0f}s")
            self.swept_at = now
            found = amiga.locate_machines(read_memory, amiga.MACHINES.values(),
                                          sweep_all=True)
            if not found:
                raise self._error(
                    "none of the titles this knows is in the Amiga's memory yet")
            if len(found) > 1:
                raise self._error(
                    "more than one title's anchor is in the Amiga's memory: "
                    + ", ".join(sorted(found)))
            (title, bases), = found.items()
            if len(bases) > 1:
                raise self._error(
                    f"{title}'s anchor appears at more than one place: "
                    + ", ".join(f"{b:#x}" for b in bases))
            self.machine = next(m for m in amiga.MACHINES.values()
                                if m.title == title)
            self.base = bases[0]
        return factory(transport, self.machine, data_base=self.base)
