"""Which of the 29 GEO maps is the party standing on?

This is the project's open question -- `docs/50-experiments.md`, "The area id
must exist, and the search for it was invalid". The save file does not obviously
say, and the scan that once reported no such field had no negative example to
work against.

A *live* mapper has a route a save reader does not: the map the game is drawing
must be resident in RAM. So there are three strategies, tried in order of how
much they would settle:

1. `ResidentGeo` -- find the loaded 1024-byte block in memory and read it
   directly. Needs no game disks and works in areas nobody has matched.
2. `FilenameDigits` -- `LIBRARY` holds the stem table with `GEO00` at `$24B4`,
   so the two patched digits sit at `$24B7`/`$24B8`. Cheap if the relocation is
   what we think.
3. `Fingerprint` -- narrow the 29 candidates by what the party can and cannot
   do. Always available, needs the game disks, and converges in a few steps.

`Fingerprint` is the fallback that makes the feature ship regardless, and it
doubles as a running check on the other two: if a strategy names a map the
party's own movements contradict, the strategy is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

from por.geo import DIRECTIONS, GEO_SIZE, STEP, Geo

# LIBRARY's data-file stem table: "GDRIVE00 SQRPACI00 GEO00 SECSET00 ...".
# GEO00 occupies $24B4-$24B8, so the digits are the last two bytes.
# UNVERIFIED against a running game: reports put LIBRARY's resident base at
# $2C48 or $2CFA, both *above* $24B4, so the relocation is not yet pinned down.
GEO_STEM = 0x24B4
GEO_DIGITS = 0x24B7

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


class FilenameDigits:
    """Read the two digits the loader patches into the `GEO00` stem.

    If this works it is the whole answer in one two-byte read. It is unproven,
    so it must be corroborated by `Fingerprint` before being trusted -- a wrong
    relocation would return two plausible-looking digits from unrelated memory.
    """

    def __init__(self, target, address: int = GEO_DIGITS):
        self.target = target
        self.address = address

    def read(self) -> str | None:
        raw = self.target.read(self.address, 2)
        try:
            text = bytes(b & 0x7F for b in raw).decode("ascii")
        except UnicodeDecodeError:
            return None
        if len(text) == 2 and all(c in "0123456789ABCDEFabcdef" for c in text):
            return f"GEO{text.upper()}"
        return None


class ResidentGeo:
    """Find the loaded map block in RAM, and thereafter read it from there.

    Once the address is known this is the best of the three: no disks, no
    filename, no inference, and it tracks the game the instant it loads a new
    area. Finding it is a one-off experiment -- stand somewhere known, sweep
    memory for a block that decodes as a plausible GEO, and check it against the
    map we already believe we are on.
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

    def search(self, expect: Geo | None = None,
               ranges=SEARCH_RANGES) -> int | None:
        """Sweep RAM for a resident copy of the map.

        With `expect` this is an exact-match hunt and the answer is certain.
        Without it, look for any 1024 bytes whose barrier plane is highly
        reciprocal -- that is the self-check `por.geo` already relies on, and
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
        except Exception:
            return None
