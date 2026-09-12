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
#: **The rule it is set by: under half the gap between the two closest maps in
#: one candidate set.** That is a guarantee rather than a comfortable margin.
#: Two maps both within `NEAR_ENOUGH` of the same block are within
#: `2 * NEAR_ENOUGH` of each other, so a tolerance under half the closest gap
#: makes it impossible for any block to be inside the tolerance of two maps at
#: once -- whatever the running game has done to the page, at most one map is
#: ever eligible and `verdict`'s answer cannot be ambiguous.
#:
#: **It must stay under 80.** MEASURED on the player's own disks, 2026-09-08,
#: over the eight corpora on this machine -- Pool of Radiance's 29 maps on the
#: C64 and in the DOS archives, Curse's 16 on the C64, the Amiga and DOS, and
#: Silver Blades' 17 on all three, 157 maps and 1580 within-set pairs. The
#: closest two *distinct* maps in one candidate set are Silver Blades' `GEO50`
#: and `GEO52` at **80** of 1024 bytes, identical on all three ports: the same
#: maze twice with different decoration, one attribute byte and 79 of wall art
#: apart. Next is Pool of Radiance's `GEO19`/`GEO1B` at 379, and the median
#: pair is about 780. `2 * 32 = 64 < 80`.
#:
#: **It must reach 6.** The widest gap between two ports' copies of one area,
#: also measured over those eight corpora: Pool of Radiance `GEO1A`, C64
#: against DOS. Curse's three C64/Amiga maps differ by 2. That case is real --
#: a player running one port's game against the other port's disks -- and
#: `tests/test_geoports.py` walks all sixteen Curse areas through it.
#:
#: **The case this constant was originally for has never once been observed.**
#: The comment here used to say the running game is allowed to write into the
#: block it is drawing. Two counting VICE checkpoints over `$0400`-`$07FF`,
#: across three driven Pool of Radiance boots, say it does not: the loader
#: writes the page exactly 1024 times when an area loads and nothing writes
#: into it again, over 20 readings that were all byte-for-byte exact, with the
#: load counter climbing past 900 as the engine drew from it. `#37 (Automap
#: the Amiga version, not just the C64)`'s twelve Amiga readings were exact as
#: well. `tools/georesident.py` re-takes it.
#:
#: **It is still not zero**, because an exact test would read a session
#: running the other port's disks as somebody else's game -- and what that
#: costs a player is not a wrong label: two such readings set
#: `Automapper.title_check` to `NOT_OURS`, which stops recording, says the
#: wrong-disk error and takes the target away from every control until one of
#: our own maps turns up at `$0400` again.
#:
#: **Was 128**, fitted before Silver Blades was in the project and never
#: re-derived, which put the tolerance 1.6 times *over* the gap it exists to
#: stay inside -- `#447 (The map tolerance is wider than the gap between two
#: of Silver Blades' own maps)`.
#:
#: **What would move it: a title whose two closest maps are nearer than 64.**
#: The DOS archives hold one already. **Pools of Darkness' `GEO21` and `GEO31`
#: differ in 18 bytes**, the closest pair of Gold Box maps anywhere on this
#: machine, and adding that title to the automapper would force this constant
#: to 8 -- barely over the 6 bytes of port drift it has to reach, with the two
#: bounds nearly meeting. It cannot reach a candidate set today because
#: `goldbox.c64_port` does not know the title, so nothing here is wrong yet, and
#: the collision wants solving before the title arrives rather than after.
#: Treasures of the Savage Frontier is the next nearest at 99, which is
#: outside 64 and would not move this at all.
#: `tools/geoports.py closest` prints all three bounds and exits non-zero when
#: any is violated.
NEAR_ENOUGH = 32

# What makes 1024 bytes a Gold Box map rather than whatever else the page
# happens to hold. Four clauses. All four thresholds are MEASURED, on
# 2026-09-08, against two corpora read off the player's own disks:
#
# * **95 maps** -- Pool of Radiance's 29 `GEO` files, Curse's 16 and Silver
#   Blades' 17 on the C64, and the same two titles' `GEO.GLB` libraries on the
#   Amiga. 65 of the 95 are distinct: every Silver Blades map is byte-identical
#   across the two ports and 13 of Curse's 16 are.
# * **65383 blocks that are not maps** -- every 1024-byte window, at 64-byte
#   steps, of every non-`GEO` file on those five disk sets. Any window holding
#   a verbatim copy of a known map is excluded, which matters: the Amiga's
#   `/SAVE/spindisk` is a library of all sixteen Curse maps and a sweep that
#   goes by filename reads slices of it as false alarms.
#
# `tools/geoplausible.py` re-takes both.
#
# 144 of the 65383 reach 0.90 reciprocity with 20 walled edges, which is as far
# as anything that is not a map gets. Across the four quantities:
#
# | | the 95 maps | those 144 |
# |---|---|---|
# | barrier reciprocity | 0.923 - 1.000 | 0.900 - 1.000 |
# | shared edges walled on both sides | 21 - 299 | 20 - 363 |
# | wall-art agreement over all 480 shared edges | **0.600 - 1.000** | **0.054 - 0.815** |
# | both-walled edges per distinct pair of art numbers | **4.20 - 122.50** | **1.11 - 10.05** |
#
# All four together admit **95 of 95** maps and **none** of the 65383.
#
# `tools/geoplausible.py thresholds` prints, for each of the four, the worst
# real map beside the best non-map that clears the *other* three -- which is
# the number the threshold has to hold off on its own, and the only honest way
# to state a margin.
#
# Nothing on either disk set clears the other three clauses with fewer than 20
# walled edges, so `MAP_WALLED_EDGES` is doing no work against real game data.
# It stays because a **page of zeroes** has no walled edges at all and agrees
# with itself perfectly about the wall art it does not have, which is the case
# it was put there for -- a booting machine, and the ordinary state at `$0400`
# mid-load.
#
# **Two limits, stated here because this is the file the check lives in.**
#
# * **There is no DOS negative corpus.** The sweep is C64 and Amiga only, so
#   nothing here has been measured against the bytes a DOS disk holds around
#   its maps. The DOS *positives* exist and pass: `#443 (Three of Curse's
#   sixteen maps differ between the C64 and the Amiga, and nobody has looked
#   at how)` read 62 DOS maps out of `GEO<n>.DAX` -- each block the same 1024
#   bytes behind the C64 PRG's own `00 04` load address -- and all 62 are
#   plausible by these four clauses. An earlier note here said DOS stored its
#   maps differently and had no positives to weigh against; that was wrong.
# * **None of this is safe against data from outside this family of games.**
#   Swept across `Bubble Bobble.adf`'s 6275 windows the old check admitted 9
#   and this one admits 6 -- Atari ST tile graphics, repetitive enough to reuse
#   wall-art pairs the way a map does. What the four clauses separate is a Gold
#   Box map from the rest of a Gold Box disk, which is what `ResidentGeo` asks
#   them, and not a map from anything whatever.
#   `tools/geoplausible.py sweep --include-other-games` re-takes it.
#
# And one thing the sweep cannot exclude: a raw disk image holds
# **sector-shifted fragments** of the maps on it, and a 64-byte run of a map is
# mostly zeros and matches everywhere, so those cannot be filtered out by
# content the way the `/SAVE/spindisk` copies above are. They are counted among
# the 65383, which makes the negative corpus harder than it looks rather than
# easier.

#: How often the two sides of a shared edge hold the same raw barrier field.
#:
#: Was 0.93, which was fitted before Silver Blades was in the project and threw
#: out its `GEO40` -- Amiga id 64 -- at 0.9229 (#436). MEASURED: the worst real
#: map is that one at 0.923, and the best non-map clearing the other three
#: clauses is `CURSE_A.D64:ITEMS+192` at 0.854.
MAP_RECIPROCITY = 0.90

#: How many shared edges must be walled from both sides.
MAP_WALLED_EDGES = 20

#: The quantity that separates a map from a page of something else, and the
#: reason `MAP_WALL_AGREEMENT` had to go (#436).
#:
#: Of the 480 edges the 16x16 grid shares internally, the fraction where the
#: two sides carry the **same** wall-art number -- an edge with no art on
#: either side counting as agreement. `goldbox.geo` already documents this at
#: 0.960 across Pool of Radiance's 29 files.
#:
#: MEASURED: the worst real map is Pool of Radiance's `GEO1E` at 0.600, a
#: wilderness plan whose walls are mostly drawn from one side only. The best
#: block that is not a map is `COMSPR.TLB+5824` on both Amiga disk As, at
#: 0.535. The threshold sits between them with 5.3% of headroom above the map
#: and 6.5% of margin below the block, and that margin is the whole of what
#: this constant is worth -- moving it and `MAP_WALL_PAIR_REUSE` down together
#: by 11% lets `COMSPR.TLB` in.
MAP_WALL_ART_AGREEMENT = 0.57

#: How many times a map reuses the same pair of wall pictures.
#:
#: Group the edges walled on both sides by the unordered pair of art numbers
#: the two sides carry, and divide: edges / distinct pairs. A map draws from a
#: small vocabulary and uses each entry over and over -- `GEO20` puts 116 of
#: its 123 *disagreeing* edges into just two pairs, art 7 against art 1 and art
#: 1 against art 6, which is a wall with a different picture on each face. A
#: page of something else pairs nibbles arbitrarily.
#:
#: MEASURED: the worst real map is Pool of Radiance's `GEO07` at 4.20, with
#: only 21 both-walled edges over 5 distinct pairs. The best block that clears
#: the other three clauses is `/Secret+324672` on the Amiga at 2.71, so this
#: one has a margin of 47% under it and 5% of headroom above `GEO07`.
MAP_WALL_PAIR_REUSE = 4.0


def _distance(a: bytes, b: bytes) -> int:
    """How many bytes differ. Both blocks are `GEO_SIZE`."""
    return sum(x != y for x, y in zip(a, b))


@dataclass(frozen=True)
class MapEvidence:
    """The four numbers `looks_like_a_map` decides on, so a tool can print them.

    `tools/geoplausible.py` is the tool, and it imports this rather than
    recomputing the quantities -- a measurement taken beside the code it
    justifies is a measurement that can disagree with it.
    """

    reciprocity: float
    walled_edges: int
    art_agreement: float
    pair_reuse: float

    @property
    def plausible(self) -> bool:
        return (self.reciprocity >= MAP_RECIPROCITY
                and self.walled_edges >= MAP_WALLED_EDGES
                and self.art_agreement >= MAP_WALL_ART_AGREEMENT
                and self.pair_reuse >= MAP_WALL_PAIR_REUSE)


def map_evidence(geo: Geo) -> MapEvidence:
    """Measure the four quantities over one block's 480 shared edges."""
    agree, edges = geo.reciprocity()
    both = art_agree = 0
    pairs: set[tuple[int, int]] = set()
    for y in range(GRID):
        for x in range(GRID):
            for direction in (EAST, SOUTH):
                dx, dy = STEP[direction]
                nx, ny = x + dx, y + dy
                if not (0 <= nx < GRID and 0 <= ny < GRID):
                    continue
                here = geo.wall(x, y, direction)
                there = geo.wall(nx, ny, OPPOSITE[direction])
                art_agree += here == there
                if here and there:
                    both += 1
                    pairs.add((min(here, there), max(here, there)))
    return MapEvidence(
        reciprocity=agree / edges if edges else 0.0,
        walled_edges=both,
        art_agreement=art_agree / edges if edges else 0.0,
        pair_reuse=both / len(pairs) if pairs else 0.0)


def looks_like_a_map(geo: Geo) -> bool:
    """Are these 1024 bytes a Gold Box map at all?

    The question `verdict` needs answered before it may say a block is
    *somebody else's* map: the page at `$0400` is a map only while one is
    loaded, and in combat it holds `SQRPACI01` instead -- a tile remap, the
    combat parameter block and code, which reciprocates 137/480 = 0.285 read as
    a map (`docs/50-experiments.md`, "`$0400` is not the combat map").

    **What separates a map from rubbish is `MAP_WALL_ART_AGREEMENT`**, and no
    single quantity does it alone. Reciprocity is not enough, because a page of
    zeroes reciprocates 1.000 -- every square agrees with its neighbour that
    there is nothing there -- so a map must also actually draw walls. Walls are
    not enough either, because the barrier plane of a sparse data block is all
    zeros and reciprocates trivially too, and 144 of the 65383 blocks measured
    get that far. Of those 144, none agrees about its wall art better than
    0.815 *and* reuses its wall pairs more than 10.05 times; every real map
    clears 0.600 and 4.20. The margin at the tightest point is **6.5%**, and
    the block that sets it is `COMSPR.TLB+5824` on the Amiga.

    This used to ask instead that the two sides of a walled edge agree about
    **which wall art number** it is, at 0.5, and that is not something the
    format promises: a wall may be a different picture from each side. It threw
    out 31 of the 95 maps measured, `GEO20` among them at 0.212 (#436).
    """
    return map_evidence(geo).plausible


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

    **The address is fixed only where the machine makes it so**, which is the
    C64 and not the Amiga -- see `address_now`.
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

    def address_now(self) -> int | None:
        """Where this machine's block is, this poll.

        `$0400` on the C64, where the loader leaves the `GEO` file it read and
        never moves it -- so the address is a constant and this answers the one
        it was built with.

        **A backend may know better, and one does.** The Amiga's loader
        allocates the buffer, so nothing is at a fixed address at all: the
        engine's own map-indexing routines dereference a global holding its
        address, and `automap/amiga.py`'s `resident_geo_address()` reads that
        global. It is asked **every time** rather than once, because an area
        change is exactly when the pointer is allowed to move -- and returns
        None while no area is loaded, which is the same "no map right now" the
        C64 reports by holding a page of something else.

        The optional-capability shape `read_fix` and `screen_banks` already
        use: found with `getattr`, and a backend without one keeps the
        behaviour every backend had before this existed.
        """
        own = getattr(self.target, "resident_geo_address", None)
        return self.address if own is None else own()

    def read(self) -> Geo | None:
        try:
            address = self.address_now()
            if address is None:
                return None
            return Geo(self.target.read(address, GEO_SIZE))
        except Exception as exc:
            # Read on every poll, and the map moves out from under us on every
            # area change, so one line and no traceback.
            _log.debug("no map at $%04X any more: %s", self.address or 0, exc)
            return None
