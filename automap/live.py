"""What the running game holds right now, as plain data. No Qt in here.

Two reads cover the whole tab, because the cost of reading a live machine is the
round trip and not the bytes -- 14.3 ms either way under VICE. In Pool of
Radiance those are:

    $4900-$64FF   header, the four effect arrays, every character record, items
    $8300-$83FF   the roster

**and in no other title.** Curse and Silver Blades load the save at `$4B00` and
keep the roster inside it at `$6700`, which is one read rather than two. Every
address here therefore comes from the `goldbox.games.Game` descriptor -- see
`memory_blocks` -- and not from a constant, so a new title costs a table row.
`automap/actions.py` reads through the same `read_blocks`, so the write side
cannot come to disagree with the read side about where a title lives.

Both go into `goldbox/savegame.py` unchanged. `SaveGame0.from_bytes()` takes exactly
the first range, and the roster page is padded out to the length `SaveGame1`
expects rather than being decoded here. That is the payoff of `goldbox/` being
transport-free: a live view needs no new decoding at all, and this module is
testable against a dictionary of bytes -- or against a save file, which *is* a
captured snapshot.

**Read-only, deliberately.** A live poke into the item area was reverted by the
game, so `$5900`+ is a copy fed from a master elsewhere, and the game is heavily
overlaid besides. Editing belongs on the editor tab, where it edits a file.

**Validate before trust.** An overlay swap, a bitmap screen or a disk load can
put anything in these bytes, so `read_snapshot` returns None rather than showing
a party of six dead characters. The caller holds its last good snapshot.
"""

from __future__ import annotations

import functools
import logging
import os
import pathlib
from dataclasses import dataclass

from goldbox import games, levels, traits
from goldbox.derive import CLASS_BITS
from goldbox.items import items_for_slot, load_item_names
from goldbox.record import FieldNotStored
from goldbox.savegame import (
    ROSTER_COUNT,
    ROSTER_STRIDE,
    SaveGame0,
    SaveGame1,
)

#: A child of the `wish` logger, so `wish/debuglog.py`'s handler takes these
#: when the log is on and its level swallows them when it is off.
_log = logging.getLogger("wish.automap.live")

ROSTER_PAGE = ROSTER_COUNT * ROSTER_STRIDE            # $100

# The four parallel 64-slot effect arrays. Four arrays and not one table of
# records, so a slot is read across all four at the same index.
#
# **Payload offsets, not addresses**, which is the form that transfers: in Pool
# of Radiance they are $4900, $4940, $4980 and $4B80, and in Curse the same
# four offsets off $4B00. The arrays have only ever been *read* on Pool of
# Radiance (`docs/139` A16) -- what is fixed here is that they follow the save
# image wherever it loads, not that their contents mean the same thing.
EFFECT_ID_OFFSET = 0x000
EFFECT_OWNER_OFFSET = 0x040
EFFECT_DURATION_OFFSET = 0x080
EFFECT_MAGNITUDE_OFFSET = 0x280
EFFECT_SLOTS = 0x40


def memory_blocks(game: games.Game | None = None):
    """The ranges one poll reads, as (address, length), for this title.

    Two for Pool of Radiance, whose roster is a second file at `$8300`. One for
    every title after it, which folds the roster into the payload's last page:
    asking for that page separately would be a second round trip for bytes
    already in hand, and a round trip is the whole cost of a read.
    """
    game = game or games.DEFAULT
    payload = (game.save_load_address, game.save_size)
    if game.roster_in_payload:
        return (payload,)
    return (payload, (game.roster_base, ROSTER_PAGE))


# Owner encoding: a party member by slot, a monster, or everybody.
FIRST_MONSTER = 8
PARTY_WIDE = 0xFF

# The quickfight bit, in the roster block: byte `+0x0C`, bit 7. CONFIRMED --
# "The quickfight bit is roster `+0x0C`" in `docs/50-experiments.md`, where
# selecting QUICK moved exactly this bit for exactly the character quickfought.
# Kept here rather than in `actions.py` because `actions` imports this module
# and not the other way round; `actions.quickfight_flag` builds its address
# from these two and `Game.roster_base`, so the read side and the write side
# cannot drift apart.
ROSTER_QUICKFIGHT = 0x0C
QUICKFIGHT_BIT = 0x80

# Bits 6-7 of the duration byte select the time unit. Which unit each value
# means is NOT decoded, so the count is shown and the unit is not invented.
DURATION_COUNT = 0x3F
DURATION_UNIT = 6

# Which level field goes with which class bit. The bitmask at 0x0EB is the field
# to prefer -- char_class at 0x073 says the same thing a second way and the two
# are allowed to disagree.
CLASS_LEVEL_FIELD = {"magic-user": "level_magic_user", "cleric": "level_cleric",
                     "thief": "level_thief", "fighter": "level_fighter"}

GRID = 16

# The condition badges, in the order a card draws them, and the effect ids each
# one covers. **The groupings are `docs/136-condition-badges.md`'s and the
# glyphs are Donald's** -- neither is this file's to change.
#
# One glyph for eight ids is what makes *warded* worth having: the badge says a
# defence is up and the tooltip says which. Read from the save's effect arrays
# and not from the trait slots at `0x0AD` -- a cast spell never reaches those,
# so a trait-sourced badge would be blank on a party with every spell running
# (`docs/133-active-effects.md`).
#
# **Five of these ids are PROBABLE rather than CONFIRMED** -- 21, 42, 45, 46
# and 49, the ones a spell has to land on the *whole party* to write, which no
# save this project holds does. Donald added them anyway on `#142 (The party
# effects line is computed every poll and shown nowhere)`, because that line is
# what a party-wide spell would otherwise show up on and it would show nothing:
# *"I do agree that protection from evil and good 10ft radius fits well with
# embraced energy."* `PROBABLE_BADGED` below is the list, so a *sixth* PROBABLE
# id cannot join without somebody deciding it.
CONDITION_BADGES: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("running-ninja", (39,)),                            # hasted
    ("healing-shield", (1, 35, 49)),                     # blessed
    ("embrassed-energy", (8, 9, 17, 28, 41, 45, 46, 89)),  # warded
    ("eyelashes", (25,)),                                # invisible
    ("strong", (12, 38)),                                # strengthened
    ("mute", (21,)),                                     # silenced
    ("snail", (42,)),                                    # slowed
)

#: The badged ids `goldbox/traits.py` grades PROBABLE, listed rather than
#: counted: the test that guards this has to read as a set somebody chose and
#: not as a number that drifts upwards. The reason they are drawn anyway is
#: above; what this pins is that a sixth cannot arrive without an edit here.
PROBABLE_BADGED = (21, 42, 45, 46, 49)


def badges(running) -> tuple[tuple[str, str], ...]:
    """`(icon, the spells it stands for)` for every badge `running` lights.

    One function so **a roster card and the party line draw the same picture
    for the same spell**: the only difference between them is whether the
    effect landed on one character or on everybody, and Bless being one glyph
    on a card and another on the strip would be a nonsense (`#142 (The party
    effects line is computed every poll and shown nowhere)`).

    The order is `CONDITION_BADGES`', not the save's, so badges do not
    reshuffle between one poll and the next. An id no badge covers is **not**
    drawn -- there is no glyph for it and inventing one is not this file's to
    do -- so a caller that must not lose it says so itself.

    **Each name opens with a capital**, because each one is a line of a
    tooltip a person reads and `goldbox/traits.py` writes them as fragments --
    `hasted`, `invisible`, `slowed`. Only the first letter: `str.capitalize()`
    would turn "under an allied Prayer" into "under an allied prayer".
    """
    running = set(running)
    out = []
    for glyph, ids in CONDITION_BADGES:
        named = [traits.describe(i) for i in ids if i in running]
        if named:
            out.append((glyph, "\n".join(n[:1].upper() + n[1:] for n in named)))
    return tuple(out)


@dataclass(frozen=True)
class Effect:
    """One slot of the effect table.

    **Expiry clears only the id**, so a slot with id 0 is free whatever the
    other three arrays still hold. `active_effects` filters on exactly that,
    and anything that skips it shows effects that ended hours ago.
    """

    slot: int
    id: int
    owner: int
    duration: int
    magnitude: int

    @property
    def party_wide(self) -> bool:
        return self.owner == PARTY_WIDE

    @property
    def monster(self) -> bool:
        return FIRST_MONSTER <= self.owner < PARTY_WIDE

    @property
    def remaining(self) -> int:
        """How much time is left, in whatever unit the top two bits select."""
        return self.duration & DURATION_COUNT

    @property
    def unit(self) -> int:
        return self.duration >> DURATION_UNIT

    @property
    def label(self) -> str:
        """`effect 12` -- there is no id-to-name table anywhere in the project.

        Showing the number is the honest form: it is visibly unknown rather
        than quietly dropped or confidently mislabelled.
        """
        return f"effect {self.id}"

    @property
    def detail(self) -> str:
        who = ("the party" if self.party_wide else
               f"monster {self.owner}" if self.monster else
               f"party slot {self.owner}")
        return (f"id {self.id} on {who}; duration byte ${self.duration:02X} "
                f"= {self.remaining} in unit {self.unit} (the unit's meaning "
                f"is not decoded); magnitude {self.magnitude}")


@dataclass(frozen=True)
class ClassProgress:
    """One of a character's classes, and how far through its level it is.

    `fraction` is None at the class ceiling -- Pool of Radiance stops a fighter
    at 8 and a cleric at 6, so there is genuinely no next threshold and the bar
    should say "maximum" rather than draw empty.
    """

    name: str
    level: int
    experience: int
    fraction: float | None
    next_threshold: int | None

    @property
    def at_ceiling(self) -> bool:
        return self.fraction is None


@dataclass(frozen=True)
class Character:
    """One card's worth: the record, the roster, and this character's effects.

    **AC, THAC0 and current hit points come from the roster, not the record.**
    A save slot stores only the first 256 bytes of a 580-byte record, and those
    three live past it -- `record.get()` raises `FieldNotStored` for them. The
    roster block holds the same bytes and is the only copy a save has.
    """

    slot: int
    name: str
    classes: tuple[ClassProgress, ...]
    level: int
    armour_class: int | None
    thac0: int | None
    hp: int | None
    hp_max: int
    experience: int
    effects: tuple[Effect, ...] = ()
    #: What this character has in hand, by the name the game would print.
    #: Empty with no game disk to read `ITEMNAMES` from -- a card is better
    #: blank than showing the word indices.
    readied: tuple[str, ...] = ()
    #: `0x0A1`, CONFIRMED: how many levels undead have drained. One of the two
    #: conditions the record actually tells us; the other is hit points at 0.
    levels_drained: int = 0
    #: Roster block `+0x0C` bit 7, CONFIRMED. Not a condition: it is a setting
    #: the player made from the combat menu, so the card badges it apart from
    #: the conditions row rather than in the danger red beside the name.
    quickfight: bool = False

    @property
    def down(self) -> bool:
        """At zero hit points: dead or dying, and **which is not decoded**.

        `automap/actions.py` refuses to heal one for the same reason. The card
        marks it and says no more than that.
        """
        return self.hp == 0

    @property
    def conditions(self) -> tuple[tuple[str, str], ...]:
        """`(icon, what it means)` for every condition a card badges.

        Two come from the record -- hit points at zero, and the drain count at
        `0x0A1`. The rest come from the save's four effect arrays at `$4900`,
        already filtered to this character by `characters()`, and are grouped
        into the five badges Donald chose: `CONDITION_BADGES`.

        **A running spell is named, never counted.** The duration byte's unit
        is in bits 6-7 and is not decoded, so "8" could be rounds, turns or
        hours; the badge says the spell is up and says no more than that.

        The order is the table's, not the effect table's, so a card's badges
        do not shuffle between one poll and the next.
        """
        out = []
        if self.down:
            out.append(("death-skull", ""))
        if self.levels_drained:
            out.append(("oppression",
                        f"Drained {self.levels_drained} level"
                        f"{'s' if self.levels_drained != 1 else ''}"))
        return tuple(out) + badges(e.id for e in self.effects)

    @property
    def class_text(self) -> str:
        abbrevs = {"magic-user": "MU", "fighter": "F", "cleric": "C", "thief": "T"}
        return "/".join(abbrevs.get(c.name.lower(), c.name) for c in self.classes) or "?"

    @property
    def level_text(self) -> str:
        levels_ = [c.level for c in self.classes]
        if len(set(levels_)) == 1 and levels_:
            return f"L{levels_[0]}"
        return "/".join(f"L{n}" for n in levels_) or f"L{self.level}"

    @property
    def hurt(self) -> bool:
        return self.hp is not None and self.hp_max and self.hp < self.hp_max

    @property
    def hp_fraction(self) -> float:
        if not self.hp_max or self.hp is None:
            return 0.0
        return max(0.0, min(1.0, self.hp / self.hp_max))


@dataclass(frozen=True)
class Snapshot:
    """Everything the tab draws that is not the map itself."""

    characters: tuple[Character, ...]
    effects: tuple[Effect, ...]
    x: int
    y: int
    facing: int
    clock_text: str
    area_file: str
    loaded_files: tuple[int, ...] = ()

    @property
    def party_effects(self) -> tuple[Effect, ...]:
        return tuple(e for e in self.effects if e.party_wide)

    @property
    def monster_effects(self) -> tuple[Effect, ...]:
        return tuple(e for e in self.effects if e.monster)

    @property
    def party_badges(self) -> tuple[tuple[str, str], ...]:
        """What the bottom strip draws: one icon row for the whole roster.

        The same `badges` a roster card uses, so Bless is the same picture
        whether it landed on one character or on everybody.
        """
        return badges(e.id for e in self.party_effects)

    @property
    def unbadged_party_effects(self) -> tuple[Effect, ...]:
        """Party-wide effects no glyph covers, so a caller can say they exist.

        Nothing draws these. The badge set is graded from the spell table
        rather than from anything watched: **no save this project holds
        carries a party-wide effect at all** -- checked 2026-08-31, the only
        effect in any fixture is id 73 with owner `0x00`, a character. So an
        id landing here is the signal that the set is short a glyph, and
        `BottomStrip` puts it in the debug log for exactly that reason.
        """
        covered = {i for _, ids in CONDITION_BADGES for i in ids}
        return tuple(e for e in self.party_effects if e.id not in covered)


def active_effects(save0_bytes: bytes) -> tuple[Effect, ...]:
    """Every effect slot whose id is non-zero, read across all four arrays.

    Takes the payload, so it is already title-independent: the offsets are
    inside the save image and follow it wherever the title loads it.
    """
    out = []
    for i in range(EFFECT_SLOTS):
        eid = save0_bytes[EFFECT_ID_OFFSET + i]
        if not eid:
            continue                       # expiry clears only the id
        out.append(Effect(
            slot=i,
            id=eid,
            owner=save0_bytes[EFFECT_OWNER_OFFSET + i],
            duration=save0_bytes[EFFECT_DURATION_OFFSET + i],
            magnitude=save0_bytes[EFFECT_MAGNITUDE_OFFSET + i],
        ))
    return tuple(out)


def _classes(record) -> tuple[ClassProgress, ...]:
    """The character's classes, each with its own experience bar.

    **The multi-class split is not proven.** AD&D divides earned experience
    between a multi-class character's classes, and the record carries one
    24-bit number; whether that number is the total or one class's share is not
    established by anything we hold -- LADY KATHERINE, the only multi-class
    specimen, is level 1 in both classes and so cannot tell the two readings
    apart. Each class's bar is drawn against the same stored number, which is
    right if it is a per-class share and optimistic if it is a total.
    """
    bits = record.get("class_bits")
    experience = record.get("experience")
    out = []
    for bit, name in CLASS_BITS:
        if not bits & bit:
            continue
        level = record.get(CLASS_LEVEL_FIELD[name]) or record.get("level") or 1
        out.append(ClassProgress(
            name=name,
            level=level,
            experience=experience,
            fraction=levels.progress(name, level, experience),
            next_threshold=levels.next_threshold(name, level),
        ))
    return tuple(out)


def readied(payload: bytes, slot: int,
            names: dict[int, str] | None) -> tuple[str, ...]:
    """What one character has in hand, named.

    **Readied only.** The whole inventory would swamp a roster card; what
    matters mid-crawl is what is in hand. An unidentified item is shown the way
    the game shows it, which is a shorter name and not a different item.

    With no `names` table -- no game disk to read `ITEMNAMES` from -- this is
    empty rather than a list of word indices.
    """
    if names is None:
        return ()
    out = []
    for item in items_for_slot(payload, slot, names):
        if not item.readied:
            continue
        label = item.name if item.is_identified else item.unidentified_name
        out.append(label or "unidentified item")
    return tuple(out)


@functools.lru_cache(maxsize=4)
def item_names(disks=None, game=None) -> dict[int, str] | None:
    """The item-name table off a title's game disks, or None if there is none.

    Not an error: the map runs without the disks, and the roster simply leaves
    the readied line blank. Cached, because every window that opens would
    otherwise re-read a D64 for a table that does not change.

    `game` picks both the disks and where the name table loads -- $6F00 for
    Pool of Radiance, $9E00 for every title after it -- and no game means Pool
    of Radiance, as everywhere else.
    """
    from .paths import find_disks

    root = pathlib.Path(disks) if disks else find_disks(game)
    if root is None:
        return None
    for path in _disk_images(root, game):
        try:
            return load_item_names(str(path), game)
        except Exception as exc:
            # Which disk carries the table is not fixed, so a miss is the
            # search working. Bounded by the number of images in the folder.
            _log.debug("no item names on %s: %s", path.name, exc)
            continue
    return None


def _disk_images(root: pathlib.Path, game=None) -> list[pathlib.Path]:
    """Every disk image of a title under `root`, each of them once.

    The upper- and lower-cased patterns both match on a case-insensitive
    filesystem, so a naive loop over `disk_globs` opens every disk twice.
    """
    from .paths import disk_globs

    seen: dict[str, pathlib.Path] = {}
    for pattern in disk_globs(game):
        for path in root.glob(pattern):
            seen.setdefault(os.path.normcase(os.path.abspath(path)), path)
    return sorted(seen.values())


def characters(save0: SaveGame0, save1: SaveGame1,
               effects: tuple[Effect, ...] = (),
               names: dict[int, str] | None = None) -> tuple[Character, ...]:
    """The party in the game's own marching order -- highest occupied slot
    first, via `SaveGame0.marching_order` (`#160`)."""
    payload = save0.to_bytes()
    out = []
    for slot in save0.marching_order:
        record = slot.record
        block = save1.roster(slot.index)
        live = block.occupied
        out.append(Character(
            slot=slot.index,
            name=record.name,
            classes=_classes(record),
            level=record.get("level"),
            armour_class=block.armour_class if live else None,
            thac0=block.thac0 if live else None,
            hp=block.hit_points if live else None,
            hp_max=record.get("hp_max"),
            experience=record.get("experience"),
            effects=tuple(e for e in effects if e.owner == slot.index),
            readied=readied(payload, slot.index, names),
            levels_drained=record.get("levels_drained") or 0,
            quickfight=live and bool(block.raw[ROSTER_QUICKFIGHT]
                                     & QUICKFIGHT_BIT),
        ))
    return tuple(out)


def roster_page_plausible(save0: SaveGame0, save1: SaveGame1) -> bool:
    """Whether the roster page still holds a roster, and not something else
    that happens to be sitting on its address.

    #82: a full-screen picture on Silver Blades leaves the roster page
    reading as graphics data, and `SaveGame1` decodes it anyway -- `_get`
    does not know what put the bytes there, only that they are there. The
    record slots this page is checked against come from a different page and
    are unaffected, so the two can be compared. Either check below is enough
    to refuse:

    * `RosterBlock.slot_index` is the game's own back-reference to the slot
      it lives in, and is always that slot's index on every save read so far
      (`tests/test_savegame.py`, `tests/test_silverblades.py`, `tests/
      test_curse.py`) -- a picture's bytes have no reason to land on that
      pattern.
    * no living character's current hit points can exceed the maximum the
      record side of the same slot carries.

    Called before a card is drawn from the page; the caller holds its last
    good snapshot rather than redraw from this one.
    """
    for slot in save0.characters:
        block = save1.roster(slot.index)
        if not block.occupied:
            continue
        if block.slot_index != slot.index:
            return False
        record = slot.record
        try:
            hp_max = record.get("hp_max") if record else None
        except FieldNotStored:
            hp_max = None
        if hp_max is not None and block.hit_points > hp_max:
            return False
    return True


def snapshot_from_bytes(save0_bytes: bytes, roster_bytes: bytes,
                        names: dict[int, str] | None = None,
                        game: games.Game | None = None) -> Snapshot | None:
    """Decode one snapshot, or None if these bytes are not a live party.

    The checks are the ones `docs/100-live-view.md` asks for: a position inside
    the grid, a plausible party, records that decode. All three fail routinely
    and none of them is an error -- at the title screen, mid-load, in a menu,
    the bytes simply are not there yet. `roster_page_plausible` is a fourth,
    for when the position and the records are fine and only the roster page
    itself is scrap (#82).
    """
    game = game or games.DEFAULT
    if len(save0_bytes) != game.save_size or len(roster_bytes) < ROSTER_PAGE:
        return None
    try:
        save0 = SaveGame0.from_bytes(bytes(save0_bytes), game)
        # Pool of Radiance's SaveGame1 expects its whole $800; only the first
        # page is the roster and the rest is resident code that a live read has
        # no reason to pull. A later title's roster is exactly the one page, so
        # there is nothing to pad.
        save1 = SaveGame1(bytes(roster_bytes[:ROSTER_PAGE])
                          + bytes(game.roster_size - ROSTER_PAGE), game)
        position = save0.party
        if not (0 <= position.x < GRID and 0 <= position.y < GRID
                and 0 <= position.facing < 4):
            return None
        if not roster_page_plausible(save0, save1):
            return None
        effects = active_effects(bytes(save0_bytes))
        people = characters(save0, save1, effects, names)
    except (ValueError, KeyError, IndexError, FieldNotStored):
        return None
    if not people:
        return None                      # no save loaded yet, or all zeros
    return Snapshot(
        characters=people,
        effects=effects,
        x=position.x,
        y=position.y,
        facing=position.facing,
        clock_text=position.clock_text,
        area_file=save0.area_file,
        loaded_files=tuple(save0.loaded_files),
    )


def read_blocks(target, game: games.Game | None = None) -> list[bytes]:
    """The save image and the roster page, in one burst where the backend can.

    Always a pair, whichever shape the title stores them in: a title that keeps
    its roster inside the payload is read once and sliced, so every caller
    downstream sees `(save0_bytes, roster_bytes)` and none of them has to know
    which shape this title is.

    `ViceTarget.read_blocks` stops the machine once and resumes once, because
    each resume hands the emulation ~14.3 ms of extra emulated time. A backend
    without it gets one round trip per block, which is what `read` alone can
    promise.
    """
    game = game or games.DEFAULT
    ranges = memory_blocks(game)
    burst = getattr(target, "read_blocks", None)
    if burst is not None:
        data = list(burst(ranges))
    else:
        data = [target.read(addr, length) for addr, length in ranges]
    if len(data) == 1:
        payload = data[0]
        at = game.roster_offset
        return [payload, payload[at:at + ROSTER_PAGE]]
    return data


def read_snapshot(target, names: dict[int, str] | None = None,
                  game: games.Game | None = None) -> Snapshot | None:
    """Two reads, whole tab. None when there is nothing sane to show."""
    if target is None:
        return None
    game = game or games.DEFAULT
    save0_bytes, roster_bytes = read_blocks(target, game)
    return snapshot_from_bytes(save0_bytes, roster_bytes, names, game)
