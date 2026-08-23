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

from por import areas, games
from por.areas import POOL_OF_RADIANCE
from por.geo import DIRECTIONS, GRID, STEP, Geo

from . import notes as notemod
from .area import Candidates, Fingerprint, ResidentGeo
from .notes import Note
from .paths import data_dir as _data_dir
from .target import Fix, read_fix

#: A read-only view over `por/areas.py`, keyed **by game title first**. This
#: used to be a flat `GEO -> name` dictionary, which was a Pool of Radiance
#: table with nothing saying so: `GEO15` exists in Curse of the Azure Bonds too
#: (`docs/120-curse-testing.md`), and a Curse party standing in it was labelled
#: "Sokol Keep". Use `por.areas.area_name`, which degrades an unknown title to
#: "area 21" instead of guessing.
AREA_NAMES = areas.GEO_NAMES


def data_dir() -> pathlib.Path:
    return _data_dir() / "maps"


def title_dir(title: str | None) -> str:
    """The sub-directory one title's notes live in.

    The `Game.key` where there is one -- `pool-of-radiance` -- because that is
    already the stable identifier this project writes into YAML, and it is
    filesystem-safe in every locale. An unrecognised title still gets a
    directory of its own rather than sharing anyone else's; the point of the
    split is that `GEO15` is a different place in every game, and that is true
    of a game we do not have a descriptor for as well.
    """
    game = games.by_title(title)
    if game is not None:
        return game.key
    slug = "".join(c if c.isalnum() else "-" for c in (title or "").lower())
    return slug.strip("-") or "unknown"


def _pool_of_radiance_maps() -> frozenset[str]:
    """Every `GEO` stem Pool of Radiance actually ships, from `por/areas.py`."""
    out = set(areas.GEO_NAMES.get(POOL_OF_RADIANCE, {}))
    for area_ in areas.AREAS:
        out |= set(area_.geos)
    return frozenset(out)


def migrate_flat_notes(root: pathlib.Path | None = None) -> list[pathlib.Path]:
    """Move the pre-title notes files under the title that wrote them.

    Until the notes file was keyed by title it was `{data dir}/maps/GEO15.json`
    for every game, so a note pinned in Sokol Keep turned up on whatever Curse's
    `GEO15` is. Everything written before that fix is Pool of Radiance's in
    practice, because it is the only title anyone has mapped.

    **Attributed, not assumed**, because losing somebody's notes is worse than
    the bug. A flat file is moved only when its stem is one of the twenty-nine
    maps Pool of Radiance actually ships; anything else -- another title's map
    id, `unknown.json`, a file somebody put there by hand -- is left exactly
    where it is, under no title at all. And a move never overwrites: where the
    per-title file already exists the flat one stays put too, so a partly
    migrated directory cannot lose the half that was already moved.

    Returns the files it moved, which is what a test asserts on.
    """
    root = pathlib.Path(root) if root is not None else data_dir()
    try:
        flat = sorted(path for path in root.glob("*.json") if path.is_file())
    except OSError:
        return []
    known = _pool_of_radiance_maps()
    into = root / title_dir(POOL_OF_RADIANCE)
    moved = []
    for path in flat:
        if path.stem not in known:
            continue
        destination = into / path.name
        if destination.exists():
            continue
        try:
            into.mkdir(parents=True, exist_ok=True)
            path.rename(destination)
        except OSError:
            continue
        moved.append(destination)
    return moved


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
    #: Which game's map names to use. A plain string, deliberately: the
    #: per-game descriptor lives in `por/games.py` and this module only needs
    #: its title. An unrecognised one is not an error -- `area_label` falls
    #: back to "area 21" rather than naming a Pool of Radiance place.
    title: str | None = POOL_OF_RADIANCE
    x: int = 0
    y: int = 0
    facing: int = 0
    source: str = ""
    candidates: Candidates | None = None
    reveal: bool = False
    exploration: Exploration = field(default_factory=Exploration)
    #: Square -> the notes on it, in the order they were made. A list because
    #: squares genuinely hold two things -- a fight and the treasure it guards.
    notes: dict[tuple[int, int], list[Note]] = field(default_factory=dict)

    @property
    def area_label(self) -> str:
        """Where the party is, in the words the game itself uses.

        The name, and only the name: "New Phlan", "The Slums", "Kuto's Well".
        The map's file stem is an implementation detail, it used to lead this
        label, and 29 of Pool of Radiance's 30 areas have a real name to show
        instead. `area` still carries the stem for anything that wants it.

        The stem is the fallback, not the format: a title whose maps we have no
        names for shows `GEO15` and never another game's "Sokol Keep", which is
        what `geo_name` rather than `area_name` buys -- `area_name`'s own
        fallback, "area 21", says no more than the stem does and looks like a
        name.
        """
        if not self.area:
            return str(self.candidates) if self.candidates else "identifying..."
        return areas.geo_name(self.area, self.title) or self.area

    @property
    def facing_letter(self) -> str:
        return "NESW"[self.facing] if 0 <= self.facing < 4 else "?"

    def is_visible(self, x: int, y: int) -> bool:
        return (not self.reveal) or ((x, y) in self.exploration)

    # -- notes, persisted per area ---------------------------------------

    def notes_path(self) -> pathlib.Path:
        """`{data dir}/maps/{title}/{GEO id}.json`.

        The title is in the path because `GEO15` is Sokol Keep in Pool of
        Radiance and somewhere else entirely in Curse, and the file holds the
        explored squares as well as the notes -- so without it a Curse map the
        player had never entered opened partly revealed with somebody else's
        notes on it.
        """
        return (data_dir() / title_dir(self.title)
                / f"{self.area or 'unknown'}.json")

    def save_notes(self) -> None:
        migrate_flat_notes()
        path = self.notes_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "notes": notemod.dump_notes(self.notes),
            "seen": sorted(f"{x},{y}" for x, y in self.exploration.seen),
        }
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    def load_notes(self) -> None:
        migrate_flat_notes()
        path = self.notes_path()
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return

        def square(key: str) -> tuple[int, int]:
            a, b = key.split(",")
            return int(a), int(b)

        self.notes = notemod.load_notes(payload.get("notes", {}))
        self.exploration.seen |= {square(k) for k in payload.get("seen", [])}

    # -- editing them ----------------------------------------------------

    def notes_at(self, x: int, y: int) -> list[Note]:
        return self.notes.get((x, y), [])

    def add_note(self, x: int, y: int, note: Note) -> None:
        self.notes.setdefault((x, y), []).append(note)

    def set_notes(self, x: int, y: int, items) -> None:
        """Replace a square's notes. An empty list removes the square."""
        items = [n for n in items if n.text or n.type != notemod.DEFAULT]
        if items:
            self.notes[(x, y)] = list(items)
        else:
            self.notes.pop((x, y), None)


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

    # How often to re-read the resident map block *when nothing suggests it
    # changed*. The block is only 1024 bytes and reading costs nothing
    # measurable -- the whole cost of a monitor round trip is the resume, not
    # the bytes -- but each read is its own resume, so doing it every tick would
    # double the poller's disturbance.
    #
    # **This is a floor, not the only time the block is read.** It used to be
    # the only time, including on the paths that exist precisely because the
    # area may just have changed, and that is what put slums squares on New
    # Phlan: see `_area_may_have_changed`.
    RESIDENT_EVERY = 10

    #: How many polls one proof that a Gold Box game is in memory stands for.
    #: Every status line renews it, so it only ever runs out while the fix is
    #: coming from the memory fallback -- camp, a menu -- and renewing it there
    #: costs one read of the resident block, on the cadence `RESIDENT_EVERY`
    #: already sets. It expires at all so that a machine reset under a
    #: connection that stays open cannot go on being believed.
    PROVEN_FOR = 10

    def __init__(self, target, maps: dict[str, Geo] | None = None,
                 area: str | None = None, title: str | None = POOL_OF_RADIANCE):
        self.target = target
        self.state = AutomapState(title=title)
        #: The descriptor behind `title`, for the readers that need addresses.
        #: None for a title with no descriptor, which `party_fix` reads as
        #: "assume the default" -- it is only ever reached from a window that
        #: has already resolved the title from the disks.
        self.game = games.by_title(title)
        self.fingerprint = Fingerprint(maps) if maps else None
        self._maps = maps or {}
        self.resident = ResidentGeo(target) if maps else None
        self._ticks = 0
        self._pending: tuple[int, int] | None = None
        self._started = False       # no "last position" to be adjacent to yet
        self._last: Fix | None = None       # the previous fix, for _refused
        #: The target the rest of this state belongs to. A strong reference on
        #: purpose: `is` against an object that has been freed could be true of
        #: a different object allocated at the same address, and holding it
        #: alive makes that impossible.
        self._attached = None
        #: The tick a Gold Box game was last proved to be in memory on, or None
        #: for a connection that has never proved it. See `_running`.
        self._proved: int | None = None
        if area:
            self.set_area(area)

    def set_area(self, name: str) -> None:
        if name == self.state.area:
            return
        if self.state.area:
            self.state.save_notes()
        self.state.area = name
        self.state.geo = self._maps.get(name)
        # The sight radius is a setting, not a property of the area: building a
        # plain `Exploration()` here quietly put it back to `SIGHT` the first
        # time the party crossed a boundary.
        self.state.exploration = Exploration(sight=self.state.exploration.sight)
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

        **The area is named before the fix is recorded, never after.** That
        ordering is the whole of the fix for the bug above, and the check that
        settles it has to actually run: it used to be rate-limited even on the
        jump path, so nine crossings in ten fell through to the ordinary
        every-tenth-poll check and leaked squares for up to two seconds.

        **And nothing at all is recorded until the game has been proved to be
        in memory** -- see `_running`, which is what the second-opinion guard
        above cannot do for itself.
        """
        if self.target is None:
            self._attached = None      # reattaching is starting again
            return False
        if self.target is not self._attached:
            self._new_connection()
        if self.resident is not None:
            self.resident.target = self.target
        fix = read_fix(self.target, self.game)
        if fix is None:
            return False

        self._ticks += 1
        if not self._running(fix):
            return False

        moved = (fix.x, fix.y) != (self.state.x, self.state.y)
        jumped = moved and self._started and not self._adjacent(fix.x, fix.y)
        changed_area = False
        if (jumped or self._ticks % self.RESIDENT_EVERY == 0
                or self._area_may_have_changed(fix)):
            changed_area = self._check_resident()
        if jumped and not changed_area:
            if self._pending != (fix.x, fix.y):
                self._pending = (fix.x, fix.y)
                return False                # wait for a second opinion
            # confirmed twice: believe it after all
        self._pending = None

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

    def _new_connection(self) -> None:
        """A new target, which is a new machine until it proves otherwise.

        The window hands the mapper a fresh `Target` when the emulator goes
        away and comes back, and everything the old session left behind is
        about a machine that no longer exists: the last position, the fix the
        clock is measured against, and above all the proof that a game was
        running. Donald quit VICE mid-encounter and started it again, wish
        reattached on its own, and the *booting* machine's zeroed position
        triple was recorded as square (0,0) -- with the previous area's map
        still loaded, so its sight lines drew a corridor the party had never
        walked. Keeping the old proof is what let that first fix through.

        Exploration and the area are deliberately kept: they are the player's
        map, not this connection's state.
        """
        self._attached = self.target
        self._proved = None
        self._started = False
        self._pending = None
        self._last = None

    def _running(self, fix: Fix) -> bool:
        """Is a Gold Box game actually in memory? Nothing is recorded until it is.

        The second-opinion guard in `poll` cannot answer this, and that is the
        point of a separate one: it refuses a position until a second poll
        agrees with it, and a machine sitting at the BASIC prompt reads the
        same bytes every time. Garbage that never changes agrees with itself.

        Two things prove a game and neither can be faked by unloaded RAM:

        * **the game's own status line.** `E 16:48  5,2` on row 14, which is
          what a `status` fix *is*; the odds of forty bytes of cold RAM
          decoding to that pattern with a square inside the grid are nil.
        * **the resident map block.** An exact 1024-byte match at `$0400`
          against a map off the player's disks -- `_check_resident`, which
          stamps `_proved` when it matches.

        A memory fix on its own proves nothing: `$C04B` is ordinary RAM, and on
        a freshly booted machine it reads `$00 $00 $00`, which is a perfectly
        plausible square (0,0). So it is believed only under a proof that still
        stands, and `PROVEN_FOR` is how long one stands for.

        With no maps loaded -- no disks -- the status line is the only proof
        available, so a long spell in camp stops being recorded until the party
        is back in the 3D view. That costs nothing: the party does not move in
        camp.
        """
        if fix.source == "status":
            self._proved = self._ticks
            return True
        standing = self._proved is not None
        if standing and self._ticks - self._proved < self.PROVEN_FOR:
            return True
        # `_check_resident` stamps `_proved` with this tick, and only when the
        # block at $0400 was a map we hold. Nothing else can stamp it here.
        self._check_resident()
        return self._proved == self._ticks

    def _adjacent(self, x: int, y: int) -> bool:
        return abs(x - self.state.x) + abs(y - self.state.y) == 1

    # A step costs the party one minute: PORSAVE12 and PORSAVE13 are 16:58 and
    # 16:59, one step apart. Anything longer is another action entirely --
    # searching, camping, resting -- and must not be read as a bump.
    STEP_MINUTES = 1

    def _refused(self, fix: Fix) -> bool:
        """Did the party just try to walk into something and fail?

        Three guards, each of them a way this would otherwise lie:

        * **Both fixes must come from the status line.** The reason has
          changed and the guard has not: the fallback used to read `$49C0`,
          which lags a move, so a successful step looked exactly like this
          pattern. It now reads the engine's own triple and does not lag -- but
          it is only reached when the status line is *absent*, which is camp,
          combat and menus, where an advancing clock is not a step at all.
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

        **Rate-limiting belongs to the caller.** This used to carry its own
        `% RESIDENT_EVERY` guard, so `poll`'s deliberate immediate check --
        the one that exists because the party may just have crossed a boundary
        -- did nothing nine times in ten and the crossing was noticed by the
        ordinary periodic check instead, up to two seconds late.
        """
        if self.resident is None:
            return False
        name = self.resident.identify(self._maps)
        if name is None:
            return False
        # A map we hold, byte for byte, at the address the loader leaves it:
        # this is also the proof `_running` needs that a game is running.
        self._proved = self._ticks
        self.state.candidates = Candidates([name], "resident $0400", certain=True)
        if name != self.state.area:
            self.set_area(name)
            return True
        return False

    def _area_may_have_changed(self, fix: Fix) -> bool:
        """Does this fix contradict the map we believe we are on?

        The other half of the crossing guard, and it costs no monitor traffic
        at all -- two questions the loaded `Geo` answers, both of them ones
        `Fingerprint._fits` already asks of every observation:

        * **an impossible square.** No passable edge at all means the square
          cannot be occupied, so a party reported on it is on another map.
        * **a step through a wall.** The party appearing next door across an
          edge this map calls solid is the same proof.

        Between them they cover the crossing that lands the party *beside*
        where it left, which has no jump to notice it by and would otherwise
        wait for the every-tenth-poll check -- two seconds during which the new
        area's squares are drawn on the old area's map, which is the bug this
        whole guard exists for.

        A false positive costs one extra read of `$0400` and names the area we
        already had.
        """
        geo = self.state.geo
        if geo is None:
            return False
        if not any(geo.is_passable(fix.x, fix.y, d) for d in DIRECTIONS):
            return True
        if not self._started or not self._adjacent(fix.x, fix.y):
            return False
        delta = (fix.x - self.state.x, fix.y - self.state.y)
        for direction, step in STEP.items():
            if step == delta:
                return not geo.is_passable(self.state.x, self.state.y, direction)
        return False
