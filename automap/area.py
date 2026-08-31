"""Which of the game's GEO maps is the party standing on?

Answered twice over, and the module carries both answers.

A *save* says outright: `$4BC2` is the `GEO` file number -- see
`docs/50-experiments.md`, "The area id: `$4BC2`, and it was in the header all
along", and `goldbox.savegame.AREA`.

A *live* game says it even more directly, because the map it is drawing is
resident: `ResidentGeo` reads the 1024 bytes at `$0400` and matches them against
the disk copies, which is an exact identification and follows the game into a
new area as soon as the load finishes.

`Fingerprint` narrows the candidates by what the party can and cannot do. It
needs no addresses at all, so it stays wired up underneath `ResidentGeo` as the
contradiction check: if a strategy names a map the party's own movements
contradict, the strategy is wrong.

**Both take the candidate set as a dict and never enumerate one.** Pool of
Radiance has 29 maps numbered `$00`-`$20`, but Curse's ids are sparse and
chapter-grouped and Silver Blades, Champions and Death Knights have no `GEO00`
at all -- their lowest id is `$10` or `$20` (write-up lost,
`work/reports/goldbox-inventory.md`).
Anything that counted maps, or walked a range, would be wrong for four of the
six titles on the shelf.

`goldbox.areas` carries the names and the area-to-map relation; nothing here
duplicates it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from goldbox.geo import DIRECTIONS, EAST, GEO_SIZE, GRID, OPPOSITE, SOUTH, STEP, Geo

#: A child of the `wish` logger, so `wish/debuglog.py`'s handler takes these
#: when the log is on and its level swallows them when it is off.
_log = logging.getLogger("wish.automap.area")

# Where a loaded GEO block sits: **$0400**, and the game does not relocate it at
# all. The file is a PRG loading at $0400, which is screen memory at boot -- but
# in the world the screen has moved to $CC00, so the page is free and the loader
# simply leaves the map there. CONFIRMED in New Phlan: $0400-$07FF was
# byte-identical to `GEO00` with 480/480 reciprocity, and no copy existed
# anywhere else in the 64K (both the `cpu` and `ram` banks were swept).
#
# This used to read `0x0800`, one page too high, which is why the search that
# was meant to settle the area question kept coming back empty.
RESIDENT_GEO = 0x0400
SEARCH_RANGES = ((RESIDENT_GEO, 0xCFFF),)

# -- is the machine running the title we believe it is? -----------------------
#
# The three answers `ResidentGeo.verdict` gives. Strings rather than an enum
# because they go straight into the debug log and into `Candidates.source`.
OURS = "ours"
NOT_OURS = "not ours"
UNKNOWN = "unknown"

#: How many of the 1024 bytes may differ and the block still be that map.
#:
#: Not zero, because the running game is allowed to write into the block it is
#: drawing and an exact test would then read a legitimate session as somebody
#: else's game -- which disables the controls in front of a player who has done
#: nothing wrong. MEASURED on the player's own disks: the two *closest*
#: distinct maps anywhere in Pool of Radiance and Curse differ in **379** of
#: 1024 bytes, and the median pair differs in about 790, so 128 leaves a
#: factor of three before any tolerance could confuse one map with another.
NEAR_ENOUGH = 128

# What makes 1024 bytes a Gold Box map rather than whatever else the page
# happens to hold. Three clauses, and all three thresholds are MEASURED against
# every 1024-byte window, at 64-byte steps, of every non-`GEO` file on the Pool
# of Radiance and Curse of the Azure Bonds disks -- 19130 blocks of real code,
# graphics, saves and tables:
#
# | | 38 real maps | 19130 other blocks |
# |---|---|---|
# | barrier reciprocity | 0.940 - 1.000 | median 0.292, and 358 reach 0.93 |
# | shared edges walled on both sides | 21 - 270 | the 358 above run 0 - 301 |
# | of those, how many agree | **0.212 - 1.000** | **0.000 - 0.423** |
#
# All three together admit **none** of the 19130 and 32 of the 38 maps. The six
# it turns away -- Pool of Radiance's `GEO02`, `GEO11`, `GEO12`, `GEO15`,
# `GEO20` and Curse's `GEO33` -- carry so much one-sided wall art that their
# own two sides disagree, and they simply read as `UNKNOWN`: no verdict, no
# refusal. That is the direction to be wrong in, and the party walks off them.
MAP_RECIPROCITY = 0.93
MAP_WALLED_EDGES = 20
MAP_WALL_AGREEMENT = 0.5


def _distance(a: bytes, b: bytes) -> int:
    """How many bytes differ. Both blocks are `GEO_SIZE`."""
    return sum(x != y for x, y in zip(a, b))


def looks_like_a_map(geo: Geo) -> bool:
    """Are these 1024 bytes a Gold Box map at all?

    The question `verdict` needs answered before it may say a block is
    *somebody else's* map: the page at `$0400` is a map only while one is
    loaded, and in combat it holds `SQRPACI` instead -- a tile remap, the
    combat parameter block and code, which scores 137/480 = 0.285 read as a map
    (`docs/50-experiments.md`, "`$0400` is not the combat map").

    Reciprocity alone is not enough, and the reason is worth keeping: a page of
    zeroes reciprocates 1.000, because every square agrees with its neighbour
    that there is nothing there. So a map must also actually draw walls, and
    the two sides of a walled edge must mostly agree about which wall it is.
    """
    agree, walled = geo.reciprocity()
    if not walled or agree / walled < MAP_RECIPROCITY:
        return False
    both = agreed = 0
    for y in range(GRID):
        for x in range(GRID):
            for direction in (EAST, SOUTH):
                dx, dy = STEP[direction]
                nx, ny = x + dx, y + dy
                if not (0 <= nx < GRID and 0 <= ny < GRID):
                    continue
                here = geo.wall(x, y, direction)
                there = geo.wall(nx, ny, OPPOSITE[direction])
                if here and there:
                    both += 1
                    agreed += here == there
    return both >= MAP_WALLED_EDGES and agreed / both >= MAP_WALL_AGREEMENT


@dataclass
class Candidates:
    """What we currently believe, and how strongly."""

    names: list[str]
    source: str
    certain: bool = False

    @property
    def best(self) -> str | None:
        return self.names[0] if len(self.names) == 1 else None

    def __str__(self) -> str:
        if self.best:
            return f"{self.best} ({self.source})"
        return f"{len(self.names)} candidates ({self.source})"


class Fingerprint:
    """Narrow the candidates by what the party has been observed to do.

    Every square the party occupies must be walkable on the real map, and every
    step it completes must cross a passable edge. Feed observations in as they
    happen; the set only shrinks.

    A blocked step -- the party tried to move and stayed put -- is the strongest
    single observation available, because it must correspond to an impassable
    edge, and impassable edges are rare.
    """

    def __init__(self, maps: dict[str, Geo]):
        self.maps = dict(maps)
        self.names = list(maps)
        self.occupied: set[tuple[int, int]] = set()
        self.steps: list[tuple[int, int, int]] = []      # x, y, direction
        self.blocked: list[tuple[int, int, int]] = []
        #: observations that would have left no candidate at all. Counted
        #: rather than obeyed -- see `_narrow`.
        self.contradictions = 0

    def saw(self, x: int, y: int) -> None:
        self.occupied.add((x, y))
        self._narrow()

    def moved(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Record a completed step between two adjacent squares."""
        delta = (x1 - x0, y1 - y0)
        for d, step in STEP.items():
            if step == delta:
                self.steps.append((x0, y0, d))
                break
        self.occupied.update({(x0, y0), (x1, y1)})
        self._narrow()

    def refused(self, x: int, y: int, direction: int) -> None:
        """Record a step the game would not let the party take."""
        self.blocked.append((x, y, direction))
        self._narrow()

    def _fits(self, geo: Geo) -> bool:
        for x, y in self.occupied:
            if not any(geo.is_passable(x, y, d) for d in DIRECTIONS):
                return False
        for x, y, d in self.steps:
            if not geo.is_passable(x, y, d):
                return False
        for x, y, d in self.blocked:
            if geo.is_passable(x, y, d):
                return False
        return True

    def _narrow(self) -> None:
        """Keep only the maps that fit -- but never narrow to nothing.

        An observation that eliminates every candidate is not evidence about
        which map this is; it is evidence that the observation was wrong. A
        garbled status line, a step across an area boundary, or a refused step
        inferred from the clock when the party was really bashing a locked door
        all produce one, and obeying it would throw away the true map for good.
        So the last non-empty set is kept and the contradiction is counted,
        which is strictly more informative than "0 candidates".
        """
        fits = [n for n in self.names if self._fits(self.maps[n])]
        if not fits and self.names:
            self.contradictions += 1
            return
        self.names = fits

    @property
    def candidates(self) -> Candidates:
        return Candidates(list(self.names), "fingerprint")


class ResidentGeo:
    """Read the loaded map block out of RAM, at `RESIDENT_GEO`.

    The best strategy available live: no disks, no inference, and it tracks the
    game the instant it loads a new area. `search` remains for the case where
    the address is wrong for some title or version -- sweep memory for a block
    that decodes as a plausible GEO, and check it against the map we already
    believe we are on.
    """

    def __init__(self, target, address: int | None = RESIDENT_GEO):
        self.target = target
        self.address = address

    def identify(self, maps: dict[str, Geo]) -> str | None:
        """The name of the map the game currently has loaded, or None.

        An exact byte match against the disk copies, so a hit is certain -- no
        fingerprint, no filename, and it changes the instant the game loads a
        new area.
        """
        geo = self.read()
        if geo is None:
            return None
        raw = geo.to_bytes()
        for name, known in maps.items():
            if known.to_bytes() == raw:
                return name
        return None

    def verdict(self, maps: dict[str, Geo]) -> tuple[str, str | None]:
        """Is the machine running the title these maps came off? Three answers.

        `(OURS, name)` -- the block is one of these maps, near enough.
        `(NOT_OURS, None)` -- it is somebody else's map.
        `(UNKNOWN, None)` -- the block is not a map at all, so it says nothing.

        The three-way answer is the point. Asking "which title is this?" needs
        every title's disks and fails *open* when it has not got them; asking
        "is this ours?" needs only the disks we already have and fails
        *closed*, and that is the difference #21 turns on.

        `UNKNOWN` is the ordinary state whenever no map is loaded -- at the
        title screen, mid-load, and in combat, where `SQRPACI` occupies the
        same page. It is not evidence of anything and must never disable a
        control.
        """
        geo = self.read()
        if geo is None or not maps:
            return UNKNOWN, None
        raw = geo.to_bytes()
        for name, known in maps.items():
            if known.to_bytes() == raw:
                return OURS, name
        # Only now is the expensive question worth asking, and asking it in
        # this order matters twice over: the exact match is a C-speed compare
        # and the common case, and `NEAR_ENOUGH` must never be reached by a
        # page that is not a map at all. A booted machine reads 1024 zeroes at
        # `$0400`, which is within a stone's throw of any sparse map and is
        # not a map.
        if not looks_like_a_map(geo):
            return UNKNOWN, None
        distance, name = min((_distance(raw, known.to_bytes()), name)
                             for name, known in maps.items())
        return (OURS, name) if distance <= NEAR_ENOUGH else (NOT_OURS, None)

    def search(self, expect: Geo | None = None,
               ranges=SEARCH_RANGES) -> int | None:
        """Sweep RAM for a resident copy of the map.

        With `expect` this is an exact-match hunt and the answer is certain.
        Without it, look for any 1024 bytes whose barrier plane is highly
        reciprocal -- that is the self-check `goldbox.geo` already relies on, and
        random memory does not pass it.
        """
        needle = expect.to_bytes() if expect else None
        for lo, hi in ranges:
            blob = self.target.read(lo, hi - lo + 1)
            if needle:
                at = blob.find(needle)
                if at != -1:
                    self.address = lo + at
                    return self.address
                continue
            for off in range(0, len(blob) - GEO_SIZE, 0x100):
                chunk = blob[off:off + GEO_SIZE]
                try:
                    geo = Geo(chunk)
                except Exception:
                    # Not logged, and the one handler here that is not: this
                    # sweeps hundreds of kilobytes a step at a time and "these
                    # bytes are not a map" is the loop's ordinary answer, not a
                    # fault. A line each would be the whole log.
                    continue
                agree, total = geo.reciprocity()
                if total and agree / total > 0.98:
                    self.address = lo + off
                    return self.address
        return None

    def read(self) -> Geo | None:
        if self.address is None:
            return None
        try:
            return Geo(self.target.read(self.address, GEO_SIZE))
        except Exception as exc:
            # Read on every poll, and the map moves out from under us on every
            # area change, so one line and no traceback.
            _log.debug("no map at $%04X any more: %s", self.address, exc)
            return None
