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

The writes, the put-back and the tiers are `automap/amigatrip.py`'s. Here:
which trips are offered, the `Waypoint` Return needs, the 3-second wait on the
area byte, and what to say when it does not change.

**Doors.** A trip goes straight to its destination unless an `automap/departures.py`
row for the title and departing area says to walk out of a door. Where the row
names a door in `trips.DOORS_PROVEN` and its party member is present, the trip
stands the party on the door and sends one forward key, and the player answers
whatever the game asks; for a destination that is not the door's own, the
second hop is a script trip made once the party stands in the door's area and
the five entry words have changed. A row that writes script variables adds
them as statements ahead of the trip. Return is always a script trip.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from . import actions as engine
from . import amiga, amigaactions, amigaparty, fasttravel
from . import amigatrip as trips
from .target import NotConnected

_log = logging.getLogger("wish.automap.amigafasttravel")

#: How long the area byte has to change after the trigger. Live it changed
#: within 1.2 s.
FIRE_SECONDS = 3.0

NOT_HAPPENED = engine.FASTTRAVEL_FAILED

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
    #: A door hop, which is taken when the key is, not when the area changes.
    door: bool = False
    #: The second hop a door's first hop leads to, or None.
    hop: _Hop | None = None


@dataclass
class _Hop:
    """The second half of a two-hop trip, waiting for the party to stand in
    `through` with that area's script loaded."""

    from_area: int
    through: int
    #: The destination's own row, and what `run` was given for its square.
    area: object
    arrival: object
    #: The five entry words when the first hop was armed. Only the interpreter's
    #: area-entry writes it, so a different set shows `through`'s script ran.
    entry: bytes = b""
    deadline: float = 0.0
    #: Set once the area byte has read `through`, so a party that came back is
    #: told apart from one that never left.
    been_through: bool = False


#: Both are `NotConnected`; named so that a reader sees what is meant.
_LOST = (NotConnected, amiga.GuestError)


class AmigaFastTravel(engine.FastTravel):
    """Put the party in another area of one Amiga title, and bring it back."""

    #: The sentence `Action.legality` gives for a machine that cannot be read.
    UNREADABLE = "the machine is not readable right now"

    def __init__(self, key: str, disks=None):
        self.key = key
        self.disks = disks
        self._lengths: dict[int, int] | None = None
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

    def lengths(self, row) -> dict[int, int]:
        """The scripts' lengths off the player's disks, read once: it opens
        the images."""
        if self._lengths is None:
            try:
                self._lengths = (trips.script_lengths(row, self.disks)
                                 if self.disks is not None else {})
            except (OSError, ValueError):
                _log.warning("amiga fast travel: reading the disks failed",
                             exc_info=True)
                self._lengths = {}
        return self._lengths

    def _row(self, id: int):
        return engine.area_by_id(id, self.title)

    def _outdoors(self, to: int) -> bool:
        return bool(getattr(self._row(to), "outdoors", False))

    # -- may we -----------------------------------------------------------

    def _leg(self, row, here: int, to: int, back: bool) -> engine.Verdict:
        """Whether the trip `here` to `to` is held, by a difference, by the
        disks or by the room past the departing script."""
        if trips.leg_held(row, here, to, back, self.lengths(row),
                          self._outdoors(to)):
            return engine.Verdict(False, self.not_built)
        return engine.Verdict(True)

    def legality(self, target, area=None, back: bool = False) -> engine.Verdict:
        if target is None:
            return engine.Verdict(False, engine.NO_EMULATOR)
        row = trips.ROWS.get(self.key)
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
        return self._leg(row, here, to, back)

    def apply(self, target, area=None, arrival=None, **kwargs) -> engine.Outcome:
        try:
            verdict = self.legality(target, area)
            if not verdict:
                return engine.Outcome(False, verdict.reason)
            return self.run(target, area=area, arrival=arrival)
        except _LOST:
            return self._lost()

    # -- doing it ---------------------------------------------------------

    def _start(self, target, to: int, name: str, arrival, overland,
               previous_back) -> engine.Outcome | None:
        """Arm the trip and wait on the area byte. None if it was armed.
        `previous_back` is what a trip that does not happen puts back."""
        row = trips.ROWS[self.key]
        here = trips.area_id(target, row)
        lengths = self.lengths(row)
        # The destination decides whether a grid square or an area-file byte
        # is written, so the actual trip is sized, then planned with its tier.
        try:
            prologue = (trips.leave_grid_prologue(row, here, to)
                        + trips.departure_prologue(self.key, here, to,
                                                   self._outdoors(to)))
            tier = trips.free_tail(
                row, here, lengths,
                trips.plan(to, arrival, overland, prologue=prologue))
        except ValueError:
            # The title has no target for a field this trip writes.
            tier = 3
        if tier not in (1, 2):
            return engine.Outcome(False, self.not_built)
        plan = trips.plan(to, arrival, overland, tier, prologue=prologue)
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
        # A new click supersedes a hop still waiting from an old trip.
        self.pending = None
        row = trips.ROWS[self.key]
        to = getattr(area, "id", area)
        door = self._run_door(target, row, area, arrival, to)
        if door is not None:
            return door
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

    def _run_door(self, target, row, area, arrival, to: int
                  ) -> engine.Outcome | None:
        """The trip by a door, or None where it is not one."""
        here = trips.area_id(target, row)
        if not row.door_confirmed or here is None or here in row.grid_areas:
            return None
        departure = trips.departure_for(self.key, here, to,
                                        self._outdoors(to))
        if departure is None or departure.route_to is None:
            return None
        through = departure.route_to
        if (here, through) not in trips.DOORS_PROVEN:
            return None
        if departure.member is not None:
            party = amigaparty.read_party(target)
            if party is None:
                # A party that cannot be read cannot be tested.
                return engine.Outcome(False, NOT_HAPPENED)
            if departure.member not in {m.name for m in party}:
                return None
        # The row's guards test C64 addresses, which an Amiga cannot read: the
        # door is walked whenever the member (if any) is present.
        name = getattr(area, "name", None) or "this area"
        route = fasttravel.EXIT_ROUTES[(here, through)]
        if through == to:
            return self._door_hop(target, row, here, to, route, name, None)
        # Checked before the first hop, so a second leg that is held leaves
        # the party where it is.
        if trips.leg_held(row, through, to, False, self.lengths(row),
                          self._outdoors(to)):
            return engine.Outcome(False, self.not_built)
        return self._door_hop(target, row, here, through, route, name,
                              _Hop(here, through, area, arrival))

    def _door_hop(self, target, row, here: int, hop_to: int, route, name: str,
                  hop: _Hop | None) -> engine.Outcome:
        """Stand the party on `route`'s door and send the key; `hop` is the
        second leg, or None for a door that leads to the destination."""
        stand = trips.stand_for(here, hop_to, route)
        if stand is None:
            return engine.Outcome(False, self.not_built)
        # Read before arming: the writes change the square the trip leaves.
        was = engine.Waypoint(here, None, trips.square(target, row),
                              trips.overland(target, row))
        entry = trips.entry_words(target, row)
        try:
            armed = trips.arm_door(target, row, stand)
        except Exception:
            _log.warning("amiga fast travel: arming a door failed",
                         exc_info=True)
            armed = None
        if armed is None:
            return engine.Outcome(False, NOT_HAPPENED)
        if hop is not None:
            hop.entry = entry
        self.trip = _Trip(armed, row, here, hop_to, name,
                          time.monotonic() + FIRE_SECONDS, self.back,
                          door=True, hop=hop)
        self.back = was
        sentence = (self.WALKING_OUT_DIRECT if hop is None
                    else self.WALKING_OUT_DETOUR)
        return engine.Outcome(True, sentence.format(name=name),
                              tuple(armed.writes))

    def back_verdict(self, target) -> engine.Verdict:
        if self.back is None:
            return engine.Verdict(False, "nothing to go back to: the party has "
                                         "not travelled anywhere this session")
        area = self._row(self.back.area)
        return self.legality(target, area or self.back, back=True)

    def apply_back(self, target) -> engine.Outcome:
        """Travel to where the last trip started, on the square it started on."""
        try:
            return self._apply_back(target)
        except _LOST:
            return self._lost()

    def _lost(self) -> engine.Outcome:
        """The connection dropped between the click and the reads: a slot
        must not raise, so say what `Action.legality` says."""
        _log.warning("amiga fast travel: the machine went away", exc_info=True)
        return engine.Outcome(False, self.UNREADABLE)

    def _apply_back(self, target) -> engine.Outcome:
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
        self.pending = None

    def continue_pending(self, target) -> engine.Outcome | None:
        """Tidy a trip whose area byte changed; put back one that did not.

        None means nothing is waiting or nothing is to be done yet. A trip
        that happened was already reported when it was armed, so it ends
        silently. A door hop is judged by its key being taken, and may leave
        a second hop to make once the party stands in the area it leads to.
        """
        if target is None:
            return None
        trip = self.trip
        if trip is None:
            return None if self.pending is None else self._continue_hop(target)
        try:
            fired = trips.trip_fired(target, trip.armed)
        except Exception:
            _log.warning("amiga fast travel: reading the area failed",
                         exc_info=True)
            fired = None
        if fired:
            self._arrived(target, trip)
            return None
        if time.monotonic() <= trip.deadline:
            return None
        _log.debug("amiga fast travel: area %d did not change to %d in time",
                   trip.from_area, trip.to)
        try:
            put_back = trips.disarm(target, trip.armed)
        except Exception:
            # Still armed as far as Wish knows: keep the trip and try again
            # on the next poll instead of reporting a party that is safe.
            _log.warning("amiga fast travel: disarming failed", exc_info=True)
            return None
        if not put_back:
            # The area changed between the last look and the put-back.
            self._arrived(target, trip)
            return None
        self.trip = None
        self.back = trip.previous_back
        return engine.Outcome(False, NOT_HAPPENED)

    def _in_fight(self, target, row) -> bool:
        party = amigaparty.ROWS.get(self.key)
        if party is None:
            return False
        return target.read(target.data_base + row.mode, 1)[0] == party.combat_value

    def _continue_hop(self, target) -> engine.Outcome | None:
        """The second hop of a two-hop trip, once the party stands in the
        area the door led to, or the sentence for a trip that will not happen."""
        hop = self.pending
        row = trips.ROWS[self.key]
        try:
            now = trips.area_id(target, row)
        except Exception:
            _log.warning("amiga fast travel: reading the area failed",
                         exc_info=True)
            return None
        if now is None:
            return None
        name = getattr(hop.area, "name", None) or "this area"
        if now == hop.through:
            if not hop.been_through:
                # The wait for `through`'s script is bounded from here.
                hop.deadline = time.monotonic() + engine.SECOND_HOP_SECONDS
            hop.been_through = True
        if now == hop.from_area:
            if hop.been_through:
                # The party went through and came back by the game's own
                # route: the trip is over.
                self.pending = None
                return None
            if self._in_fight(target, row):
                hop.deadline = time.monotonic() + engine.SECOND_HOP_SECONDS
                return None
            if time.monotonic() > hop.deadline:
                self.pending = None
                return engine.Outcome(False, self.NEVER_LEFT.format(name=name))
            return None
        if now != hop.through:
            self.pending = None
            if now in (to for to, _ in fasttravel.exits_from(hop.from_area)):
                # The party left by another door: no second hop is right for
                # wherever it now is, and Return has nothing to go back to.
                self.back = None
                return engine.Outcome(
                    False, self.LEFT_ANOTHER_WAY.format(name=name))
            return None
        if not trips.gate(target, row):
            return None
        if trips.entry_words(target, row) == hop.entry:
            if time.monotonic() > hop.deadline:
                self.pending = None
            return None
        arrival, overland = self._square_writes(hop.area, arrival=hop.arrival)
        notes = tuple(self.warnings(target, hop.area, arrival, overland))
        self.pending = None
        failed = self._start(target, getattr(hop.area, "id", hop.area), name,
                             arrival, overland, self.back)
        if failed is not None:
            return failed
        # `back` is the square the first hop left, which Return goes to.
        return engine.Outcome(True, f"Traveling to {name}.",
                              tuple(getattr(self.trip.armed, "writes", ())),
                              notes)

    def _arrived(self, target, trip: _Trip) -> None:
        """The area changed: the trip happened, and what it left is tidied."""
        self.trip = None
        if trip.hop is not None:
            trip.hop.deadline = time.monotonic() + engine.SECOND_HOP_SECONDS
            self.pending = trip.hop
        try:
            trips.tidy(target, trip.armed, trips.area_id(target, trip.row),
                       self.lengths(trip.row))
        except Exception:
            _log.warning("amiga fast travel: tidying failed", exc_info=True)
