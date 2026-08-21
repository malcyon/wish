"""What the automapper knows, with no Qt anywhere in it.

The game does not save which squares you have seen -- `SAVEDGAME1` past `$83FF`
turned out to be resident code and a graphics buffer, so there is no explored
bitmap to read. The mapper therefore tracks exploration itself, which is why
`Exploration` exists and why it is persisted alongside the notes.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

from por.geo import GRID, STEP, Geo

from .area import Candidates, Fingerprint, ResidentGeo
from .paths import data_dir as _data_dir
from .target import Fix, read_fix

AREA_NAMES = {
    "GEO14": "Slums",
    "GEO09": "Stojanow Gate",
    "GEO12": "Podol Plaza",
    "GEO15": "Sokol Keep",
    "GEO20": "Kuto's Well Catacombs",
    "GEO02": "Cadorna Textile House",
    "GEO0F": "Mendor's Library",
    "GEO1D": "Kuto's Well",
    "GEO00": "New Phlan",
}


def data_dir() -> pathlib.Path:
    return _data_dir() / "maps"


# How far down an open corridor the party can see. The game's own 3D view shows
# several squares ahead, so revealing only the square you stand on would lag
# badly behind what the player has actually looked at.
SIGHT = 4


def can_see_through(geo: Geo, x: int, y: int, direction: int) -> bool:
    """Does sight pass through this edge? Only where there is no wall art.

    Deliberately **not** `Geo.is_passable`, which movement still needs: that is
    true for `LOCKED` and `WIZARD_LOCKED` and for any ordinary door, so the fog
    used to lift off rooms behind doors the party had never opened.

    Measured over every square of `GEO00` before choosing: `is_passable`
    reveals 7.27 squares per stand, a locked-door-only rule reveals 7.27 as
    well -- `GEO00` has no locked edges at all, so that rule fixes nothing --
    and blocking on wall art reveals 5.49. Locked doors are a strict subset of
    "has art", so they block too; ordinary doors were what did the damage.

    A doorway you have walked through does not re-open to view. That is the
    honest loss: the map has no idea whether a door was left open.
    """
    return geo.wall(x, y, direction) == 0


class Exploration:
    """The squares the party has seen this campaign.

    **Sight stops at walls, and at doors.** An earlier version revealed all four
    neighbours of every square the party stood on, which drew the far wall of a
    corridor you had never entered and could not see -- you were looking at the
    near side of the wall between you and it.

    So: your own square, then outwards in each direction only while the edge you
    are looking through has no wall art, up to `SIGHT` squares. That is corridor
    line-of-sight, and it never reveals anything behind a wall or a shut door --
    see `can_see_through`.

    Without a map -- before the area is known -- only the square itself is
    revealed, because the edges cannot be checked.
    """

    def __init__(self, seen: set[tuple[int, int]] | None = None,
                 sight: int = SIGHT):
        self.seen: set[tuple[int, int]] = set(seen or ())
        self.trail: list[tuple[int, int]] = []
        self.sight = sight

    def visit(self, x: int, y: int, geo=None) -> None:
        if not self.trail or self.trail[-1] != (x, y):
            self.trail.append((x, y))
        self.seen.add((x, y))
        if geo is None:
            return
        for direction, (dx, dy) in STEP.items():
            cx, cy = x, y
            for _ in range(self.sight):
                if not can_see_through(geo, cx, cy, direction):
                    break
                cx, cy = cx + dx, cy + dy
                if not (0 <= cx < GRID and 0 <= cy < GRID):
                    break
                self.seen.add((cx, cy))

    def __contains__(self, square) -> bool:
        return square in self.seen

    def __len__(self) -> int:
        return len(self.seen)


@dataclass
class AutomapState:
    """Everything the view draws from.

    `geo` is None until the area is identified; the window shows an empty grid
    and the candidate count until then, which is honest about what is known.
    """

    geo: Geo | None = None
    area: str | None = None
    x: int = 0
    y: int = 0
    facing: int = 0
    source: str = ""
    candidates: Candidates | None = None
    reveal: bool = False
    exploration: Exploration = field(default_factory=Exploration)
    notes: dict[tuple[int, int], str] = field(default_factory=dict)

    @property
    def area_label(self) -> str:
        if not self.area:
            return str(self.candidates) if self.candidates else "identifying..."
        name = AREA_NAMES.get(self.area)
        return f"{self.area} - {name}" if name else self.area

    @property
    def facing_letter(self) -> str:
        return "NESW"[self.facing] if 0 <= self.facing < 4 else "?"

    def is_visible(self, x: int, y: int) -> bool:
        return (not self.reveal) or ((x, y) in self.exploration)

    # -- notes, persisted per area ---------------------------------------

    def notes_path(self) -> pathlib.Path:
        return data_dir() / f"{self.area or 'unknown'}.json"

    def save_notes(self) -> None:
        path = self.notes_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "notes": {f"{x},{y}": t for (x, y), t in self.notes.items() if t},
            "seen": sorted(f"{x},{y}" for x, y in self.exploration.seen),
        }
        path.write_text(json.dumps(payload, indent=1))

    def load_notes(self) -> None:
        path = self.notes_path()
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError):
            return

        def square(key: str) -> tuple[int, int]:
            a, b = key.split(",")
            return int(a), int(b)

        self.notes = {square(k): v for k, v in payload.get("notes", {}).items()}
        self.exploration.seen |= {square(k) for k in payload.get("seen", [])}


class Automapper:
    """Drives the state from a `Target`. One `poll()` per tick.

    Movement is inferred by comparing successive fixes, which is also how the
    fingerprint learns: a step between adjacent squares proves an edge is
    passable, and a fix that does not change after the party tried to move
    proves one is not.

    **The second of those is now available too**, from data already read every
    poll. The mapper cannot see key presses, but the status line carries the
    game clock, and the clock only moves when the party acts. So *clock advanced
    by one minute + square unchanged + facing unchanged* is a step the game
    refused -- and one refused step is worth about a hundred successful ones,
    because positive evidence needs 111 steps to get New Phlan down to one
    candidate and impassable edges are rare. See `_refused`.
    """

    # How often to re-read the resident map block. The block is only 1024 bytes
    # and reading costs nothing measurable -- the whole cost of a monitor round
    # trip is the resume, not the bytes -- but each read is its own resume, so
    # doing it every tick would double the poller's disturbance. Every tenth
    # poll is two seconds at the default interval, which is well inside the
    # time it takes the game to load a new area off disk.
    RESIDENT_EVERY = 10

    def __init__(self, target, maps: dict[str, Geo] | None = None,
                 area: str | None = None):
        self.target = target
        self.state = AutomapState()
        self.fingerprint = Fingerprint(maps) if maps else None
        self._maps = maps or {}
        self.resident = ResidentGeo(target) if maps else None
        self._ticks = 0
        self._pending: tuple[int, int] | None = None
        self._started = False       # no "last position" to be adjacent to yet
        self._last: Fix | None = None       # the previous fix, for _refused
        if area:
            self.set_area(area)

    def set_area(self, name: str) -> None:
        if name == self.state.area:
            return
        if self.state.area:
            self.state.save_notes()
        self.state.area = name
        self.state.geo = self._maps.get(name)
        self.state.exploration = Exploration()
        self.state.notes = {}
        self.state.load_notes()

    def poll(self) -> bool:
        """Read one fix. Returns True if anything the view draws changed.

        `target` may be None -- the window opens before the game does and
        attaches later -- in which case there is simply nothing to read yet.

        **A position that is not adjacent to the last one is not believed on
        sight.** Two different things produce one: the party crossed into
        another area, or the status line was read while the screen was half
        redrawn. Both used to be taken at face value, and both did damage --
        a garbled read moved the marker across the map and back, and an area
        change recorded the new area's squares onto the old area's map until
        the periodic check caught up. Slums coordinates ended up drawn on New
        Phlan.

        So a jump triggers an immediate area check, and if the area really did
        change the fix is accepted into the new one. Otherwise the fix is held
        until a second poll agrees with it -- a garbled read never survives
        that, and a genuine long move inside one area costs one extra tick.
        """
        if self.target is None:
            return False
        if self.resident is not None:
            self.resident.target = self.target
        fix = read_fix(self.target)
        if fix is None:
            return False

        moved = (fix.x, fix.y) != (self.state.x, self.state.y)
        changed_area = False
        if moved and self._started and not self._adjacent(fix.x, fix.y):
            changed_area = self._check_resident()
            if not changed_area:
                if self._pending != (fix.x, fix.y):
                    self._pending = (fix.x, fix.y)
                    return False            # wait for a second opinion
                # confirmed twice: believe it after all
            self._pending = None
        else:
            self._pending = None
            self._ticks += 1
            if self._ticks % self.RESIDENT_EVERY == 0:
                changed_area = self._check_resident()

        changed = moved or fix.facing != self.state.facing or changed_area

        if self.fingerprint and not changed_area:
            if moved and self._adjacent(fix.x, fix.y):
                self.fingerprint.moved(self.state.x, self.state.y, fix.x, fix.y)
            else:
                self.fingerprint.saw(fix.x, fix.y)
                if self._refused(fix):
                    self.fingerprint.refused(fix.x, fix.y, fix.facing)
            if not self.state.candidates or not self.state.candidates.certain:
                self.state.candidates = self.fingerprint.candidates
            if self.state.candidates.best and not self.state.area:
                self.set_area(self.state.candidates.best)
                changed = True

        self.state.x, self.state.y = fix.x, fix.y
        self.state.facing, self.state.source = fix.facing, fix.source
        self._started = True
        self._last = fix
        self.state.exploration.visit(fix.x, fix.y, self.state.geo)
        return changed

    def _adjacent(self, x: int, y: int) -> bool:
        return abs(x - self.state.x) + abs(y - self.state.y) == 1

    # A step costs the party one minute: PORSAVE12 and PORSAVE13 are 16:58 and
    # 16:59, one step apart. Anything longer is another action entirely --
    # searching, camping, resting -- and must not be read as a bump.
    STEP_MINUTES = 1

    def _refused(self, fix: Fix) -> bool:
        """Did the party just try to walk into something and fail?

        Three guards, each of them a way this would otherwise lie:

        * **Both fixes must come from the status line.** The memory copy at
          `$49C0` lags a move, so a successful step read from memory looks like
          a square that did not change while the clock advanced -- which is
          exactly the pattern being tested for.
        * **Exactly one minute.** Longer means the party did something else.
          Zero means it did nothing at all, which is the ordinary case: the
          clock does not run while you stand still, so "the party never tried
          to move" reads as no elapsed time and is not counted.
        * **Same square and same facing.** Turning on the spot changes the
          facing, so a turn is never mistaken for a bump.

        **The clock cost of a refused step is not confirmed.** A move costs a
        minute; whether walking into a wall costs the same minute is inferred,
        not measured -- nobody has watched the clock during a bump. If it turns
        out to cost nothing, this simply never fires and the fingerprint is no
        worse off than before. If bashing a locked door costs a minute, this
        would record a false blocked edge, which is what the contradiction
        guard in `Fingerprint._narrow` is there to absorb.
        """
        before = self._last
        if before is None or fix.source != "status" or before.source != "status":
            return False
        if before.clock is None or fix.clock is None:
            return False
        if (fix.x, fix.y, fix.facing) != (before.x, before.y, before.facing):
            return False
        elapsed = (fix.clock - before.clock) % (24 * 60)
        return elapsed == self.STEP_MINUTES

    def _check_resident(self) -> bool:
        """Name the area from the map block the game itself has loaded.

        The game leaves the `GEO` file where it loads, at `$0400`, so an exact
        byte match against the disk copies settles the area outright -- no
        walking, no inference, and it follows the game into a new area as soon
        as the load finishes. `Fingerprint` stays wired up underneath as the
        check on this: if the party walks through an edge the named map says is
        solid, the two disagree and the name is wrong.
        """
        if self.resident is None:
            return False
        self._ticks += 1
        if self._ticks % self.RESIDENT_EVERY != 1:
            return False
        name = self.resident.identify(self._maps)
        if name is None:
            return False
        self.state.candidates = Candidates([name], "resident $0400", certain=True)
        if name != self.state.area:
            self.set_area(name)
            return True
        return False
