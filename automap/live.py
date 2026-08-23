"""What the running game holds right now, as plain data. No Qt in here.

Two reads cover the whole tab, because the cost of reading a live machine is the
round trip and not the bytes -- 14.3 ms either way under VICE:

    $4900-$64FF   header, the four effect arrays, every character record, items
    $8300-$83FF   the roster

Both go into `por/savegame.py` unchanged. `SaveGame0.from_bytes()` takes exactly
the first range, and the roster page is padded out to the length `SaveGame1`
expects rather than being decoded here. That is the payoff of `por/` being
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
import os
import pathlib
from dataclasses import dataclass

from por import levels
from por.derive import CLASS_BITS
from por.items import items_for_slot, load_item_names
from por.record import FieldNotStored
from por.savegame import (
    ROSTER_COUNT,
    ROSTER_STRIDE,
    SAVE0_LOAD_ADDRESS,
    SAVE0_SIZE,
    SAVE1_LOAD_ADDRESS,
    SAVE1_SIZE,
    SaveGame0,
    SaveGame1,
)

# The two blocks, as (address, length). Whole-tab, per poll.
ROSTER_PAGE = ROSTER_COUNT * ROSTER_STRIDE            # $100
BLOCKS = ((SAVE0_LOAD_ADDRESS, SAVE0_SIZE), (SAVE1_LOAD_ADDRESS, ROSTER_PAGE))

# The four parallel 64-slot effect arrays. Four arrays and not one table of
# records, so a slot is read across all four at the same index.
EFFECT_ID = 0x4900
EFFECT_OWNER = 0x4940
EFFECT_DURATION = 0x4980
EFFECT_MAGNITUDE = 0x4B80
EFFECT_SLOTS = 0x40

# Owner encoding: a party member by slot, a monster, or everybody.
FIRST_MONSTER = 8
PARTY_WIDE = 0xFF

# The quickfight bit, in the roster block: byte `+0x0C`, bit 7. CONFIRMED --
# "The quickfight bit is roster `+0x0C`" in `docs/50-experiments.md`, where
# selecting QUICK moved exactly this bit for exactly the character quickfought.
# Kept here rather than in `actions.py` because `actions` imports this module
# and not the other way round; `actions.QUICKFIGHT` builds its address from
# these two, so the read side and the write side cannot drift apart.
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
        """`(icon, what it means)` for every condition we can actually read.

        Still two, and no longer for the old reason. The effect ids at `$4900`
        and the trait codes at `0x0AD` are **one namespace**, not two:
        `LIBRARY $4028` reads the arrays first and falls back to the
        character's own slots (`docs/133-active-effects.md`), so
        `por/traits.py` names both and a badge would not be invented. 66 of
        its 129 names are CONFIRMED, 21 of them things that can be true of a
        player character.

        What is missing is a chosen glyph for each, not a name. The candidates
        and their verdicts at 13px are the table in
        `docs/107-roster-and-notes.md`; Donald picks from it, and nothing is
        badged until he has.
        """
        out = []
        if self.down:
            out.append(("skull", "at 0 hit points: dead or dying, and the "
                                 "record does not say which"))
        if self.levels_drained:
            out.append(("arrow-down-long",
                        f"drained {self.levels_drained} level"
                        f"{'s' if self.levels_drained != 1 else ''} "
                        f"(record 0x0A1)"))
        return tuple(out)

    @property
    def class_text(self) -> str:
        return "/".join(c.name for c in self.classes) or "?"

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


def active_effects(save0_bytes: bytes) -> tuple[Effect, ...]:
    """Every effect slot whose id is non-zero, read across all four arrays."""
    base = SAVE0_LOAD_ADDRESS
    out = []
    for i in range(EFFECT_SLOTS):
        eid = save0_bytes[EFFECT_ID - base + i]
        if not eid:
            continue                       # expiry clears only the id
        out.append(Effect(
            slot=i,
            id=eid,
            owner=save0_bytes[EFFECT_OWNER - base + i],
            duration=save0_bytes[EFFECT_DURATION - base + i],
            magnitude=save0_bytes[EFFECT_MAGNITUDE - base + i],
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
        except Exception:
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
    payload = save0.to_bytes()
    out = []
    for slot in save0.characters:
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


def snapshot_from_bytes(save0_bytes: bytes, roster_bytes: bytes,
                        names: dict[int, str] | None = None) -> Snapshot | None:
    """Decode one snapshot, or None if these bytes are not a live party.

    The checks are the ones `docs/100-live-view.md` asks for: a position inside
    the grid, a plausible party, records that decode. All three fail routinely
    and none of them is an error -- at the title screen, mid-load, in a menu,
    the bytes simply are not there yet.
    """
    if len(save0_bytes) != SAVE0_SIZE or len(roster_bytes) < ROSTER_PAGE:
        return None
    try:
        save0 = SaveGame0.from_bytes(bytes(save0_bytes))
        # SaveGame1 expects its whole $800; only the first page is the roster
        # and the rest is resident code that a live read has no reason to pull.
        save1 = SaveGame1(bytes(roster_bytes[:ROSTER_PAGE])
                          + bytes(SAVE1_SIZE - ROSTER_PAGE))
        position = save0.party
        if not (0 <= position.x < GRID and 0 <= position.y < GRID
                and 0 <= position.facing < 4):
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


def read_blocks(target, blocks=BLOCKS) -> list[bytes]:
    """Read several ranges, in one burst where the backend can do that.

    `ViceTarget.read_blocks` stops the machine once and resumes once, because
    each resume hands the emulation ~14.3 ms of extra emulated time. A backend
    without it gets one round trip per block, which is what `read` alone can
    promise.
    """
    burst = getattr(target, "read_blocks", None)
    if burst is not None:
        return list(burst(blocks))
    return [target.read(addr, length) for addr, length in blocks]


def read_snapshot(target, names: dict[int, str] | None = None) -> Snapshot | None:
    """Two reads, whole tab. None when there is nothing sane to show."""
    if target is None:
        return None
    save0_bytes, roster_bytes = read_blocks(target)
    return snapshot_from_bytes(save0_bytes, roster_bytes, names)
