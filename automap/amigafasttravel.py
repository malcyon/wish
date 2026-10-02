"""Fast Travel and Return on an Amiga title: the C64 action, aimed at script writes.

`AmigaFastTravel` subclasses `actions.FastTravel`, so the name, label, help and
every outcome sentence are the approved ones. What changes is the route: the C64
sets the program counter, which no Amiga backend lets Wish do, so the trip is
armed through `automap/amigatrip.py` (script statements written past the loaded
area script and one key) and finished from the window's poll.

**No Amiga title gets a C64 address.** `game` and `addresses` are None, nothing
here reads the program counter or a C64 container, and the parent's
`__init__` (which would hand Pool of Radiance's container to Pools of Darkness)
is not run.

`amigatrip` is imported when first needed, like `amigaparty` in
`automap/amigaactions.py`, so this module works before that one exists. Names
taken from it:

* `ROWS`: `amiga.MACHINES` key to a `TripRow`. A row has `confirmed` (bool) and
  `differences`, a tuple of objects with `offered` (False until Donald decides)
  and `covers(here, to, back) -> bool` for the Return landing, Tilverton,
  leaving Pool's wilderness, Pool's doors and Pool's weaker check.
* `gate(target, row)`: the menu is up and the party is idle.
* `area_id(target, row)`, `square(target, row)`, `overland(target, row)`:
  where the party is, as the parent's `Waypoint` wants them.
* `free_tail(row, area, disks)`: 1 or 2 when a trip can be armed from `area`,
  anything else when it cannot.
* `plan(area, square, overland, tier)`, `arm(target, row, plan)` (an `Armed`,
  or None when nothing was left written), `fired(target, armed)` (True once the
  area has changed, None before), `disarm(target, armed)` and
  `tidy(target, armed, new_area)`.
"""

from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass

from . import actions as engine
from . import amiga, amigaactions

_log = logging.getLogger("wish.automap.amigafasttravel")

#: How long the area byte has to change after the trigger. Live it changed
#: within 1.2 s.
FIRE_SECONDS = 3.0

NOT_HAPPENED = engine.FASTTRAVEL_FAILED

_UNSET = object()
_cached = _UNSET


def _trips():
    """`automap.amigatrip`, or None while it is not in the tree. The answer is
    kept, the absent case included; any other import failure is raised."""
    global _cached
    if _cached is _UNSET:
        try:
            _cached = importlib.import_module("automap.amigatrip")
        except ModuleNotFoundError as exc:
            if exc.name != "automap.amigatrip":
                raise
            _cached = None
    return _cached


@dataclass
class _Trip:
    """A trip armed and waiting for the area byte to change."""

    armed: object
    row: object
    from_area: int
    to: int
    name: str
    deadline: float
    #: `back` as it was before the trip, for a trip that does not happen.
    previous_back: engine.Waypoint | None


class AmigaFastTravel(engine.FastTravel):
    """Put the party in another area of one Amiga title, and bring it back."""

    def __init__(self, key: str, disks=None):
        self.key = key
        self.disks = disks
        self.game = None
        self.addresses = None
        self.back: engine.Waypoint | None = None
        self.pending = None
        self.trip: _Trip | None = None

    @property
    def descriptor(self):
        raise AttributeError("an Amiga action has no C64 container")

    @property
    def title(self) -> str:
        return amiga.MACHINES[self.key].title

    @property
    def not_built(self) -> str:
        return amigaactions.unsupported(self.title)

    def _row(self, id: int):
        return engine.area_by_id(id, self.title)

    # -- may we -----------------------------------------------------------

    def legality(self, target, area=None, back: bool = False) -> engine.Verdict:
        if target is None:
            return engine.Verdict(False, engine.NO_EMULATOR)
        trips = _trips()
        row = None if trips is None else trips.ROWS.get(self.key)
        if row is None or not row.confirmed:
            return engine.Verdict(False, self.not_built)
        if not getattr(amigaactions._unwrap(target), "can_write", False):
            return engine.Verdict(False, self.not_built)
        if not trips.gate(target, row):
            return engine.Verdict(False, engine.FASTTRAVEL_BUSY)
        if self.trip is not None:
            # A second trip would be armed over the first one's statements
            # before the area byte has said whether the first fired.
            return engine.Verdict(False, engine.FASTTRAVEL_BUSY)
        if area is None:
            return engine.Verdict(False, "choose an area")
        if not getattr(area, "fasttravelable", True):
            return engine.Verdict(False, self.ATTRACT_TRAP)
        here = trips.area_id(target, row)
        if here is None:
            return engine.Verdict(False, self.not_built)
        to = getattr(area, "id", None)
        if to is None:
            to = getattr(area, "area", None)
        if here == to:
            return engine.Verdict(False, "the party is already in that area")
        if any(d.covers(here, to, back) and not d.offered
               for d in row.differences):
            return engine.Verdict(False, self.not_built)
        if here is not None and trips.free_tail(
                row, here, self.disks) not in (1, 2):
            return engine.Verdict(False, self.not_built)
        return engine.Verdict(True)

    def apply(self, target, area=None, arrival=None, **kwargs) -> engine.Outcome:
        verdict = self.legality(target, area)
        if not verdict:
            return engine.Outcome(False, verdict.reason)
        return self.run(target, area=area, arrival=arrival)

    # -- doing it ---------------------------------------------------------

    def _start(self, target, to: int, name: str, arrival, overland,
               previous_back) -> engine.Outcome | None:
        """Arm the trip and wait on the area byte. None if it was armed.
        `previous_back` is what a trip that does not happen puts back."""
        trips = _trips()
        row = trips.ROWS[self.key]
        here = trips.area_id(target, row)
        tier = trips.free_tail(row, here, self.disks)
        plan = trips.plan(to, arrival, overland, tier)
        try:
            armed = trips.arm(target, row, plan)
        except Exception:
            _log.warning("amiga fast travel: arming failed", exc_info=True)
            armed = None
        if armed is None:
            return engine.Outcome(False, NOT_HAPPENED)
        self.trip = _Trip(armed, row, here, to, name,
                          time.monotonic() + FIRE_SECONDS, previous_back)
        return None

    def run(self, target, area=None, arrival=None, **kwargs) -> engine.Outcome:
        if self.trip is not None:
            return engine.Outcome(False, engine.FASTTRAVEL_BUSY)
        trips = _trips()
        row = trips.ROWS[self.key]
        to = getattr(area, "id", area)
        arrival, overland = self._square_writes(area, arrival=arrival)
        notes = tuple(self.warnings(target, area, arrival, overland))
        # Read before arming: the writes change the square the trip leaves.
        here = trips.area_id(target, row)
        was = engine.Waypoint(here, None, trips.square(target, row),
                              trips.overland(target, row)) \
            if here is not None else None
        name = getattr(area, "name", None) or "this area"
        failed = self._start(target, to, name, arrival, overland, self.back)
        if failed is not None:
            return failed
        self.back = was
        return engine.Outcome(True, f"Traveling to {name}.",
                              tuple(getattr(self.trip.armed, "writes", ())),
                              notes)

    def back_verdict(self, target) -> engine.Verdict:
        if self.back is None:
            return engine.Verdict(False, "nothing to go back to: the party has "
                                         "not travelled anywhere this session")
        area = self._row(self.back.area)
        return self.legality(target, area or self.back, back=True)

    def apply_back(self, target) -> engine.Outcome:
        """Travel to where the last trip started, on the square it started on."""
        verdict = self.back_verdict(target)
        if not verdict:
            return engine.Outcome(False, verdict.reason)
        was = self.back
        area = self._row(was.area)
        arrival, overland = self._square_writes(
            area or was, arrival=was.square, overland=was.overland)
        name = getattr(area, "name", None) or f"area {was.area}"
        failed = self._start(target, was.area, name, arrival, overland, was)
        if failed is not None:
            return failed
        self.back = None
        return engine.Outcome(
            True, f"travelled back to {name}",
            tuple(getattr(self.trip.armed, "writes", ())))

    # -- finishing it, from the poll --------------------------------------

    def cancel_pending(self) -> None:
        self.trip = None

    def continue_pending(self, target) -> engine.Outcome | None:
        """Tidy a trip whose area byte changed; put back one that did not.

        None means nothing is waiting or nothing is to be done yet. A trip
        that happened was already reported when it was armed, so it ends
        silently.
        """
        trip = self.trip
        trips = _trips()
        if trip is None or target is None or trips is None:
            return None
        try:
            fired = trips.fired(target, trip.armed)
        except Exception:
            _log.warning("amiga fast travel: reading the area failed",
                         exc_info=True)
            fired = None
        if fired:
            self.trip = None
            try:
                trips.tidy(target, trip.armed, trips.area_id(target, trip.row))
            except Exception:
                _log.warning("amiga fast travel: tidying failed",
                             exc_info=True)
            return None
        if time.monotonic() <= trip.deadline:
            return None
        _log.debug("amiga fast travel: area %d did not change to %d in time",
                   trip.from_area, trip.to)
        try:
            trips.disarm(target, trip.armed)
        except Exception:
            # Still armed as far as Wish knows: keep the trip and try again
            # on the next poll instead of reporting a party that is safe.
            _log.warning("amiga fast travel: disarming failed", exc_info=True)
            return None
        self.trip = None
        self.back = trip.previous_back
        return engine.Outcome(False, NOT_HAPPENED)
