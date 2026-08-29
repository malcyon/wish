"""Acting on the running game: the writes, and when each one is legal.

`docs/102-live-actions.md` is the plan; this is the engine half of it. No Qt in
here, the same way `live.py` and `combat.py` have none -- an action takes a
`Target`, decides whether it is legal, and either writes or says why not. The
window wires buttons to these; the tests drive them against `MemoryTarget`.

**Everything is gated on the mode flag** the loader dispatches on, and never on
the screen: `2` is COMBAT. An action that is illegal in combat refuses at
`apply` time and not only in its tooltip, because a button's enabled state is
one poll interval stale and a fight can start inside that interval.

**Every address here is per title, and comes from `goldbox.games.Game`** -- the
slot area, the item area and the roster page all follow `save_load_address`,
so Curse and Silver Blades are written at `$4F00`, `$5B00` and `$6700` and not
at Pool of Radiance's `$4D00`, `$5900` and `$8300` (#29).

**The mode flag is the one address that does not follow it.** It is a byte of
`LINKER`'s own resident page, not of the save image, so it had to be read out of
each title's loader: `$6E11` in Pool of Radiance, `$7F11` in Curse and Silver
Blades, and `2` is COMBAT in all three because their overlay name tables are the
same table entry for entry (#29). The three Krynn-era titles have never been
read, so `Game.mode_flag` is None there and every action refuses rather than
write with no way to see a fight -- an unmeasured address answers "not combat"
whatever the machine is doing, which is a gate that is open rather than one that
is missing.

**Nothing here writes to a disk.** These change the machine's memory; the player
saves in the game as usual, which is what keeps the losslessness promise intact.

Two facts from `docs/50-experiments.md` bound what is safe to write:

* **The item area is a copy.** Poking `$5A98` -- Pool of Radiance's -- to
  150 lb was reverted by the game, so a write there is fed from a master
  elsewhere and may not stick. `IdentifyItems` writes anyway -- it is one bit
  and the failure mode is "nothing happened" -- but it says so, and it is the
  one action whose effect the caller should verify by looking at the game.
* **`$6B00` is the resident character record** and `$6C00` the resident roster
  block, so the game works on a *copy* of whichever character is in hand. A
  write into the slot area is what the next save writes out; a write into a
  field the game is holding in the resident copy at that moment can be
  overwritten by it.
"""

from __future__ import annotations

import json
import logging
import struct
import time
from dataclasses import dataclass
from dataclasses import field as dc_field

from goldbox import games, levels, levelup
from goldbox import items as por_items
from goldbox.layout import Confidence, field_by_name
from goldbox.record import CharacterRecord
from goldbox.savegame import (
    ROSTER_HP_CURRENT,
    ROSTER_STRIDE,
    ROSTER_THAC0,
    SLOT_STRIDE,
    SaveGame0,
    SaveGame1,
)

from . import live
from .combat import COMBAT
from .paths import config_dir

# The whole memorised list, as the record stores it: a packed list of spell ids
# at 0x020. Sixteen bytes is exactly enough -- Pool of Radiance caps a cleric at
# 3/3/2 and a magic-user at 4/2/2, so even a multi-class caster at the ceiling
# has sixteen spells prepared and no more.
SPELLS_MEMORISED = field_by_name("spells_memorised")

SPELL_FILE = "spells.json"
UNKNOWN_DISK = "unknown disk"

#: A child of the `wish` logger, so `wish/debuglog.py`'s handler takes these
#: when the log is on and its level swallows them when it is off -- without
#: this module importing `wish`.
_log = logging.getLogger("wish.automap.actions")


def _read(target, addr: int, length: int) -> bytes | None:
    """`target.read`, or None when the machine cannot be read.

    Every caller treats that as "no answer" rather than as an error: at the
    title screen, mid-load or with the emulator gone the bytes simply are not
    there, and each action refuses on that separately. The fault still reaches
    the log, as one line and not a traceback -- these run on the poll, and the
    poll above them writes the traceback once per distinct failure.
    """
    try:
        return target.read(addr, length)
    except Exception as exc:
        _log.debug("could not read %d bytes at $%04X: %s", length, addr, exc)
        return None


#: Donald's wording, approved 2026-08-24. Shown when the running title has no
#: measured combat flag, so we cannot tell a fight from the map and will not
#: write blind. The five actions all use it.
UNSUPPORTED = "ERROR: Action unsupported on {title}."


def mode(target, game: games.Game | None = None) -> int | None:
    """Which overlay is running, or None if that cannot be established.

    Two ways it comes back None and the caller has to separate them itself:
    the machine could not be read, and **this title has no mode flag**.
    `Game.mode_flag` is `LINKER`'s dispatch byte, read out of the loader on
    Pool of Radiance, Curse and Silver Blades and on no other title, so a title
    with None here has no gate at all -- see `Action.legality`, which refuses
    rather than reading somebody else's address and calling whatever it finds
    "not combat".
    """
    game = game or games.DEFAULT
    if game.mode_flag is None:
        return None
    raw = _read(target, game.mode_flag, 1)
    return raw[0] if raw else None


def in_combat(target, game: games.Game | None = None) -> bool:
    """True only when the mode flag *says* combat. An unreadable machine is not
    combat -- it is unreadable, and every action refuses on that separately."""
    return mode(target, game) == COMBAT


# --- what an action answers with ---------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """Whether an action may run now, and the reason when it may not.

    `reason` is written to be shown as-is: it goes in a disabled button's
    tooltip and in the refusal the action returns if it is called anyway.
    """

    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


@dataclass(frozen=True)
class Outcome:
    """What an action did, or why it did nothing.

    `writes` is every `(address, bytes)` that went to the machine, which is what
    makes these testable without one: assert on the addresses, not on a
    screenshot. `notes` carries what was deliberately left alone -- a character
    the heal skipped, an item that was already identified -- because "did
    nothing" and "did nothing to this one, and here is why" are different
    answers.
    """

    ok: bool
    message: str
    writes: tuple[tuple[int, bytes], ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def changed(self) -> int:
        return len(self.writes)


# --- the party, as the actions need it ---------------------------------------


@dataclass(frozen=True)
class Member:
    """One occupied party slot: the record, the roster block, and addresses.

    The record is the stored 256 bytes zero-padded to a full 580, so anything
    the layout places past `0x0FF` reads as zero and must not be written --
    live, the slots are `$100` apart and offset `0x119` of slot 0 is offset
    `0x019` of slot 1.

    **Every address below comes from `game`** and none of them is a constant:
    the three bases were Pool of Radiance's `$4D00`, `$5900` and `$8300`, which
    is what made these actions write into another title's memory (#29). The
    offsets inside the payload are the same in all six titles; only the base
    moves, so a new title costs a row in `goldbox/games.py` and nothing here.
    """

    slot: int
    record: CharacterRecord
    roster: bytes
    game: games.Game = games.DEFAULT

    @property
    def name(self) -> str:
        return self.record.name

    @property
    def record_base(self) -> int:
        return self.game.slot_area_base + self.slot * SLOT_STRIDE

    @property
    def roster_base(self) -> int:
        return self.game.roster_base + self.slot * ROSTER_STRIDE

    @property
    def item_base(self) -> int:
        return self.game.item_area_base + self.slot * por_items.ITEM_BLOCK_STRIDE

    @property
    def hp(self) -> int:
        return self.roster[ROSTER_HP_CURRENT]

    @property
    def hp_max(self) -> int:
        return self.record.get("hp_max")

    def field_address(self, name: str) -> int:
        """Where a record field lives in the running machine.

        Raises for anything past the stored 256 bytes, because that address
        belongs to the *next* character's slot and writing it would corrupt
        them rather than this one.
        """
        f = field_by_name(name)
        if f.end > SLOT_STRIDE:
            raise ValueError(
                f"{name} is at 0x{f.offset:03X}, past the {SLOT_STRIDE} bytes a "
                f"slot holds; live it belongs to slot {self.slot + 1}")
        return self.record_base + f.offset


@dataclass(frozen=True)
class Party:
    """Everyone in the roster, from the same two reads the live view makes."""

    members: tuple[Member, ...]
    save0_bytes: bytes = dc_field(repr=False, default=b"")
    game: games.Game = games.DEFAULT

    def __iter__(self):
        return iter(self.members)

    def __len__(self) -> int:
        return len(self.members)

    def by_slot(self, slot: int) -> Member | None:
        for m in self.members:
            if m.slot == slot:
                return m
        return None


def read_party(target, game: games.Game | None = None) -> Party | None:
    """The party, or None when these bytes are not one.

    Same blocks as `live.read_snapshot`, read through the same
    `live.read_blocks`, and the same validate-before-trust rule: at the title
    screen, mid-load or in a menu the bytes simply are not there, and that is
    ordinary rather than an error. `live.roster_page_plausible` guards a
    fourth case, where the position and the record slots are both fine and
    only the roster page has something else's bytes on it (#82).

    `game` says where to read and how to decode. One read for a title that
    keeps its roster in the payload's last page, two for Pool of Radiance,
    which keeps it in a second file -- `live.read_blocks` hides which, so this
    always sees the pair.
    """
    if target is None:
        return None
    game = game or games.DEFAULT
    try:
        save0_bytes, roster_bytes = live.read_blocks(target, game)
        save0 = SaveGame0.from_bytes(bytes(save0_bytes), game)
        # Pool of Radiance's `SaveGame1` expects its whole `$800` and only the
        # first page of it is the roster; a later title's roster *is* the page,
        # so there is nothing to pad. `live.snapshot_from_bytes` does the same
        # sum for the same reason.
        save1 = SaveGame1(bytes(roster_bytes[:live.ROSTER_PAGE])
                          + bytes(game.roster_size - live.ROSTER_PAGE), game)
        if not live.roster_page_plausible(save0, save1):
            return None
        members = tuple(
            Member(slot=s.index, record=s.record,
                   roster=save1.roster(s.index).raw, game=game)
            for s in save0.characters)
    except Exception as exc:
        _log.debug("these bytes are not a party: %s", exc)
        return None
    return Party(members, bytes(save0_bytes), game) if members else None


# --- the actions -------------------------------------------------------------


class Action:
    """One button's worth of behaviour.

    Subclasses set `name`, `label` and `combat_legal`, and implement `run`.
    `apply` is what a caller uses: it re-checks legality, so an action is safe
    to call from a button whose enabled state is a poll interval old.
    """

    #: Stable identifier, for settings and for wiring.
    name = ""
    #: Button text.
    label = ""
    #: One line, for a tooltip.
    description = ""
    #: False means "refuse while the mode flag is 2".
    combat_legal = False
    #: Non-empty means ask this question before running. There is no in-game
    #: undo for anything that carries one.
    confirm = ""

    def __init__(self, game: games.Game | None = None):
        """Which title this acts on. None is Pool of Radiance.

        Every address an action writes is `Game` geometry now -- the slot
        area, the item area and the roster page all follow
        `save_load_address` -- so the title is the whole of what a subclass
        has to be told (#29).
        """
        self.game = game or games.DEFAULT

    @property
    def descriptor(self) -> games.Game:
        """This action's title, as the descriptor its addresses come from.

        A property rather than the attribute itself because `LevelUp` accepts
        a key or a `LevelTables` as well -- `goldbox/levels.py` is duck-typed on
        `.key` on purpose -- and the addresses need a `Game`.
        """
        return self.game

    def legality(self, target) -> Verdict:
        game = self.descriptor
        if target is None:
            return Verdict(False, "no emulator attached")
        if game.mode_flag is None:
            # No gate, so no writes. `mode` would answer None here and that
            # reads as "unreadable", which is the wrong sentence: the machine
            # is fine and it is the address that is missing. The flag is
            # `LINKER`'s own byte and only three titles' loaders have been
            # read, so on the rest this is a fight we cannot see.
            return Verdict(False, UNSUPPORTED.format(title=game.title))
        state = mode(target, game)
        if state is None:
            return Verdict(False, "the machine is not readable right now")
        if state == COMBAT and not self.combat_legal:
            return Verdict(False, f"{self.label.lower()} is refused during a "
                                  f"fight (${game.mode_flag:04X} is 2)")
        return Verdict(True)

    def apply(self, target, **kwargs) -> Outcome:
        verdict = self.legality(target)
        if not verdict:
            return Outcome(False, verdict.reason)
        return self.run(target, **kwargs)

    def run(self, target, **kwargs) -> Outcome:   # pragma: no cover - abstract
        raise NotImplementedError


def _write_all(target, writes) -> tuple[tuple[int, bytes], ...]:
    for addr, data in writes:
        target.write(addr, data)
    return tuple(writes)


class HealParty(Action):
    """Current hit points to maximum, for everyone standing.

    **Legal anywhere**, including mid-fight: healing is a cheat rather than a
    corruption risk, and nothing the game recomputes would notice.

    The write is the roster block at `Game.roster_base + slot * $20`, byte
    `+0x19`. Current hit points are not in the stored 256 bytes of a record --
    record `0x119` is export-only -- so this is a live-only address and the
    roster is the only copy a running game has.

    **A character at zero is skipped.** Zero is dead or dying, and whatever else
    the game marks that with is not decoded; raising the hit point byte alone
    would be a half-write, which is the same objection that stops levelling.

    Confirmed live: four wounded characters healed and the game's own party
    list redrew at their maxima, and SILAS went 8 to 9 mid-fight at
    `$6E11 = 2`. See `docs/50-experiments.md`.
    """

    name = "heal"
    label = "Heal party"
    description = "current hit points to maximum, for every conscious character"
    combat_legal = True

    def run(self, target, **kwargs) -> Outcome:
        party = read_party(target, self.game)
        if party is None:
            return Outcome(False, "no party to heal")
        writes, notes = [], []
        for m in party:
            if m.hp == 0:
                notes.append(f"{m.name} is at 0 and was left alone: dead or "
                             f"dying is not a hit point count")
                continue
            target_hp = min(m.hp_max, 0xFF)
            if m.hp_max > 0xFF:
                notes.append(f"{m.name} has {m.hp_max} maximum hit points and "
                             f"the roster byte holds 255")
            if m.hp >= target_hp:
                continue
            writes.append((m.roster_base + ROSTER_HP_CURRENT,
                           bytes([target_hp])))
        _write_all(target, writes)
        if not writes:
            return Outcome(True, "nobody needed healing", (), tuple(notes))
        return Outcome(True, f"healed {len(writes)} of {len(party)}",
                       tuple(writes), tuple(notes))


# --- memorised spells --------------------------------------------------------


class SpellStore:
    """Memorised spell lists, kept in a file so they outlive the window.

    Keyed by save disk and character name, because a name is not unique across
    disks and the point of the store is to survive a session. The file is JSON
    under the config directory for the same reason `automap.json` is: small,
    hand-editable, and a corrupt one is treated as empty rather than as an
    error -- losing a stored spell list is not worth refusing to start over.
    """

    def __init__(self, path=None):
        self.path = path or (config_dir() / SPELL_FILE)

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n",
                                 encoding="utf-8")
        except OSError:
            pass                 # a read-only home should not take the tab down

    def put(self, disk: str, name: str, raw: bytes) -> None:
        data = self._load()
        data.setdefault(disk or UNKNOWN_DISK, {})[name] = {
            "memorised": bytes(raw).hex(),
            "stored": time.strftime("%Y-%m-%d %H:%M"),
        }
        self._save(data)

    def get(self, disk: str, name: str) -> bytes | None:
        entry = self._load().get(disk or UNKNOWN_DISK, {}).get(name)
        if not entry:
            return None
        try:
            return bytes.fromhex(entry["memorised"])
        except (KeyError, TypeError, ValueError):
            return None

    def stored_at(self, disk: str, name: str) -> str:
        entry = self._load().get(disk or UNKNOWN_DISK, {}).get(name)
        return (entry or {}).get("stored", "")

    def names(self, disk: str) -> tuple[str, ...]:
        return tuple(sorted(self._load().get(disk or UNKNOWN_DISK, {})))


class StoreSpells(Action):
    """Remember what everyone has memorised, so it can be put back later.

    Reads only, but it is refused in combat with the restore it pairs with: a
    list captured mid-fight is a list with the fight's casting already spent,
    which is not what anybody means by "store my spells".
    """

    name = "store-spells"
    # American spelling on the face of the program, Donald's; the field name
    # `spells_memorised` stays as it is, because it reaches generated docs and
    # saved YAML that has to keep loading.
    label = "Save spells"
    description = "remember the memorised list for every character"

    def __init__(self, store: SpellStore | None = None,
                 game: games.Game | None = None):
        super().__init__(game)
        self.store = store or SpellStore()

    def run(self, target, disk: str = "", **kwargs) -> Outcome:
        party = read_party(target, self.descriptor)
        if party is None:
            return Outcome(False, "no party to read")
        notes = []
        for m in party:
            raw = m.record.get_raw("spells_memorised")
            self.store.put(disk, m.name, raw)
            spells = m.record.spells_memorised
            if spells:
                notes.append(f"{m.name}: {', '.join(str(i) for i in spells)}")
            else:
                notes.append(f"{m.name}: none")
        return Outcome(True, f"stored spells for {len(party)} character"
                             f"{'s' if len(party) != 1 else ''}", notes=tuple(notes))


class RestoreSpells(Action):
    """Write the stored memorised list back, so nobody has to rest for it.

    **Illegal in combat.** The write is record `0x020`, sixteen bytes, in the
    slot area at `Game.slot_area_base + slot * $100` -- inside the stored 256
    bytes, so it is also what the next save writes out.

    Only the memorised list moves. The capacity at `0x0EE` says how many spells
    of each level the character *may* prepare and does not change with resting,
    so restoring it would be writing a field the action has no business in.
    """

    name = "restore-spells"
    label = "Restore spells"
    description = "put back the memorised list stored earlier"

    def __init__(self, store: SpellStore | None = None,
                 game: games.Game | None = None):
        super().__init__(game)
        self.store = store or SpellStore()

    def run(self, target, disk: str = "", **kwargs) -> Outcome:
        party = read_party(target, self.game)
        if party is None:
            return Outcome(False, "no party to restore")
        writes, notes = [], []
        for m in party:
            raw = self.store.get(disk, m.name)
            if raw is None:
                notes.append(f"nothing stored for {m.name}")
                continue
            if len(raw) != SPELLS_MEMORISED.size:
                notes.append(f"the stored list for {m.name} is {len(raw)} "
                             f"bytes, not {SPELLS_MEMORISED.size}")
                continue
            if raw == m.record.get_raw("spells_memorised"):
                continue
            writes.append((m.field_address("spells_memorised"), raw))
        _write_all(target, writes)
        if not writes:
            return Outcome(True, "nothing to restore", (), tuple(notes))
        return Outcome(True, f"restored spells for {len(writes)} character"
                             f"{'s' if len(writes) != 1 else ''}",
                       tuple(writes), tuple(notes))


# --- items -------------------------------------------------------------------


class IdentifyItems(Action):
    """Clear the hidden-name bits on every item the party carries.

    The low three bits of an item's byte `+6` hide its name words until it is
    identified -- bit 0 the noun, bit 1 the qualifier, bit 2 the suffix -- and
    clearing them is the whole of being identified. `+6` bit 7 is readied and
    is never touched.

    **Illegal in combat, and it asks first**: identification is part of the
    game's economy and there is no in-game way to undo it.

    **The write may not stick.** The item area is a copy fed from a master
    elsewhere -- poking an item's weight there was reverted by the game -- so
    this is the one action whose effect is worth checking in the game's own
    item list before believing it.
    """

    name = "identify"
    label = "Identify"
    description = "clear the hidden-name bits on every item the party carries"
    confirm = ("Identify every item the party carries? There is no way to undo "
               "this in the game.")

    def run(self, target, **kwargs) -> Outcome:
        party = read_party(target, self.game)
        if party is None:
            return Outcome(False, "no party to read")
        writes = []
        for m in party:
            # The item block's offset *inside the payload we just read*, which
            # is why the payload's own load address is what comes off it and
            # not Pool of Radiance's `$4900` (#29).
            base = m.item_base - self.game.save_load_address
            block = party.save0_bytes[base:base + por_items.ITEM_BLOCK_STRIDE]
            for n in range(por_items.ITEMS_PER_CHARACTER):
                raw = block[n * por_items.ITEM_SIZE:(n + 1) * por_items.ITEM_SIZE]
                if len(raw) < por_items.ITEM_SIZE or not any(raw):
                    continue
                flags = raw[6]
                if not flags & por_items.HIDDEN_NAME_MASK:
                    continue
                addr = m.item_base + n * por_items.ITEM_SIZE + 6
                writes.append((addr, bytes([flags & ~por_items.HIDDEN_NAME_MASK])))
        _write_all(target, writes)
        if not writes:
            return Outcome(True, "every item was already identified")
        return Outcome(True, f"identified {len(writes)} item"
                             f"{'s' if len(writes) != 1 else ''}", tuple(writes))


# --- levelling ---------------------------------------------------------------

#: Every record field a level-up writes. Each one has to be CONFIRMED in
#: `goldbox/layout.py` before the action will write anything at all: a
#: half-levelled character is a corrupt character, and one field written from a
#: guess is enough to make it one.
LEVEL_UP_FIELDS: tuple[str, ...] = (
    "level", "thac0_base", "hp_max", "hp_rolled", "experience",
    "level_cleric", "level_fighter", "level_magic_user", "level_thief",
    "save_paralysis", "save_petrification", "save_wands", "save_breath",
    "save_spell", "spells_castable", "spells_known", "turn_power",
    "attack_level", "attack_forms",
) + levelup.THIEF_FIELDS


def game_title(game=None) -> str:
    """What to call a title in a refusal. Takes a `Game`, a key, or None."""
    title = getattr(game, "title", None)
    if title:
        return title
    if game is None:
        return levels.DEFAULT.title
    try:
        from goldbox import games
    except ImportError:                     # pragma: no cover - defensive
        return str(game)
    known = games.BY_KEY.get(str(game))
    return known.title if known else str(game)


def level_up_blockers(record: CharacterRecord | None = None,
                      game=None) -> tuple[str, ...]:
    """Every reason levelling refuses, most specific first.

    Empty means every field the trainer touches is both derivable and
    CONFIRMED. **It got there by measurement, not by lowering a bar**: the
    five entries this used to carry were closed by reading the trainer's own
    routines out of `GEN` and replaying twenty-nine measured trainings through
    `goldbox/levelup.py` -- see `docs/135-levelling.md`.

    It takes a record because the remaining refusals are per character: a class
    at its ceiling, a race at its limit, or not enough experience.

    **And it takes a title, because the measurement was of one title.** Curse
    is the case that would corrupt quietly: its level tables are in
    `goldbox/levels.py`, so selecting them looks like enough, and it is not. Every
    derivation around them was read at Pool of Radiance's addresses out of Pool
    of Radiance's `GEN` -- `levels.TRAINER_MEASURED` names them -- so a title
    nobody has measured is refused whatever tables it has.
    """
    out = []
    unsure = [name for name in LEVEL_UP_FIELDS
              if field_by_name(name).confidence is not Confidence.CONFIRMED]
    if unsure:
        out.append("not CONFIRMED, so not written: " + ", ".join(sorted(unsure)))
    if not levels.trainer_measured(game):
        out.append(f"the trainer's tables have not been measured for "
                   f"{game_title(game)}; only {levels.DEFAULT.title}'s have")
    return tuple(out)


class LevelUp(Action):
    """Raise a character a level, writing what the training hall writes.

    **The trainer is the specification and this is a copy of it.** `GEN $1B8C`
    is the sequence a level-up runs; every routine it calls has been read and
    `goldbox/levelup.py` names each one beside the field it fills. Replaying the
    twenty-nine trainings measured in `docs/119-test-party.md` through it
    reproduces the game's own record **byte for byte** on every field, given
    the hit die it rolled.

    **The die is rolled, because the game rolls one.** `hp_rolled` at `0x0ED`
    takes a fresh roll of the class hit die at every training and derives from
    nothing; `hp_max` derives from it exactly. The roll is reported in the
    outcome so the number is never silent.

    **Money is untouched, and the trainer does take it**: a flat 1000 gold at
    every level, with the rest of the character's coin converted to platinum,
    measured across all twenty-nine. That is what walking into a school costs
    rather than what gaining a level costs, so none of the seven coin fields at
    `0x0BB` is written. Movement is not recomputed either -- the trainer does
    that from encumbrance, which nothing here changes.

    **Healing is done, because the trainer does it.** Current hit points end at
    the *new* maximum, after the die is rolled and `hp_max` has risen. A
    character at 0 is refused rather than healed: zero is dead or dying and the
    record does not say which, which is the same refusal `HealParty` makes.

    **A magic-user has to choose.** `GEN $215A` puts every spell it does not
    know, of a level it can now cast, on a menu and does not finish the
    level-up until one is picked -- so `spell` is required for a magic-user
    with anything left to learn, and the action refuses rather than choosing.
    `offers(record)` is that list.

    **Which class is not a question the player is asked.** A multi-class
    character with two classes ready gets the one whose threshold after the
    level is largest -- `levelup.best_next_class`, and `class_for(record)` is
    the answer for a caller that needs it before the write. That keeps the
    experience clamp's ceiling as high as it goes, so the other class usually
    survives; pressing the button again then takes it. An explicit
    `class_name` still overrides.

    **Which title, though, is a question, and it is asked.** `game` is the
    `goldbox.games.Game` the session is, and every table and every derivation is
    taken from it. None means Pool of Radiance, because every caller written
    before there was a second title meant that one. A title whose trainer
    nobody has measured is refused by `level_up_blockers` before a byte is
    written -- see `goldbox.levels.TRAINER_MEASURED`.
    """

    name = "level-up"
    label = "Level up"
    description = "raise a character a level without the trainer"
    confirm = "Level up this character? There is no way to undo this in the game."

    def __init__(self, game=None):
        # Not `super().__init__`: `None` here has to stay `None`. Every table
        # below takes a title-or-None and resolves it itself, and
        # `level_up_blockers` refuses a title whose trainer nobody measured
        # before a byte is written -- so an unnamed title must not be quietly
        # turned into Pool of Radiance's descriptor.
        self.game = game

    @property
    def descriptor(self) -> games.Game:
        """`game` as a `Game`, for the addresses `run` writes to.

        An unknown key falls back to Pool of Radiance's geometry, which costs
        nothing: `level_up_blockers` has already refused every title but the
        one whose trainer was measured.
        """
        if isinstance(self.game, games.Game):
            return self.game
        key = getattr(self.game, "key", self.game)
        if isinstance(key, str) and key in games.BY_KEY:
            return games.BY_KEY[key]
        return games.DEFAULT

    @staticmethod
    def offers(record, game=None) -> list[int]:
        """The spell ids a magic-user would be offered at its next level."""
        return levelup.learnable(
            record, game,
            level=levelup.class_level(record, "magic-user") + 1)

    @staticmethod
    def class_for(record, game=None) -> str | None:
        """Which class the button would raise, or None if none is ready.

        A caller has to know before it writes, because a magic-user needs its
        spell chosen and no other class does.
        """
        return levelup.best_class(record, game)

    @staticmethod
    def preview(record, class_name: str = "", spell: int | None = None,
                game=None) -> levelup.Plan | None:
        """The plan without writing it, or None if it cannot be made.

        Only `experience_lost` and `classes_disqualified` are worth reading off
        it: the hit die is rolled again by `run`, so every number that depends
        on the roll differs.
        """
        try:
            return levelup.plan(record, class_name, game=game, learn=spell)
        except levelup.CannotLevel:
            return None

    def run(self, target, slot: int = 0, class_name: str = "",
            spell: int | None = None, **kwargs) -> Outcome:
        party = read_party(target, self.descriptor)
        if party is None:
            return Outcome(False, "no party to read")
        member = party.by_slot(slot)
        if member is None:
            return Outcome(False, f"no character in slot {slot}")
        record = member.record
        if member.hp == 0:
            # The same refusal `HealParty` makes, and for the same reason: zero
            # is dead or dying and the record does not say which. Levelling
            # ends in a heal to full, and a corpse at full hit points is a
            # character in a state the game never writes.
            return Outcome(False,
                           f"{member.name} is at 0 hit points: dead or dying "
                           f"is not a hit point count, and levelling heals")
        blockers = level_up_blockers(record, self.game)
        if blockers:
            return Outcome(False,
                           f"levelling {member.name} would write fields we "
                           f"cannot derive, so it writes nothing", (), blockers)

        try:
            plan = levelup.plan(record, class_name, game=self.game,
                                learn=spell)
        except levelup.CannotLevel as why:
            return Outcome(False, f"{member.name} cannot level: {why}")

        writes = []
        after = levelup.apply_to(record, plan)
        for name in sorted(plan.fields):
            f = field_by_name(name)
            writes.append((member.field_address(name),
                           after.slice(f.offset, f.size)))
        if plan.spellbook is not None:
            f = field_by_name("spells_known")
            writes.append((member.field_address("spells_known"), plan.spellbook))

        # The roster's cached THAC0 and current hit points. Both live past the
        # 256 bytes a live slot holds, so the roster block is the only copy a
        # save or a running game has -- record `0x119` exists in an export and
        # nowhere else.
        if plan.thac0_delta:
            writes.append((member.roster_base + ROSTER_THAC0,
                           bytes([(member.roster[ROSTER_THAC0]
                                   + plan.thac0_delta) & 0xFF])))
        # Healed to the *new* maximum, and after it rose: the trainer does the
        # same, and healing first would heal to the old number.
        healed = min(plan.hp_max, 0xFF)
        writes.append((member.roster_base + ROSTER_HP_CURRENT, bytes([healed])))

        _write_all(target, writes)
        notes = list(plan.notes)
        notes.append(f"hit die: rolled {plan.hit_points_rolled} on a d"
                     f"{levels.hit_die(plan.class_name, self.game)}")
        if plan.learned_spell is not None:
            notes.append(f"learned spell {plan.learned_spell}")
        notes.append(f"healed to {healed} hit points, as the trainer does")
        notes.append("the trainer also charges 1000 gold and converts the rest "
                     "of the coin to platinum; that is what a school costs, "
                     "not what a level costs, so no money moved")
        # The class is named because the player no longer picks it: the only
        # place the choice is visible is here.
        return Outcome(True,
                       f"{member.name} is a {plan.class_name} {plan.to_level}",
                       tuple(writes), tuple(notes))


# --- quickfight --------------------------------------------------------------


@dataclass(frozen=True)
class QuickfightFlag:
    """Where the per-character quickfight bit lives.

    `base` is the address of character 0's byte, `stride` the distance to the
    next character's, and `mask` the bit.
    """

    base: int
    stride: int
    mask: int

    def address(self, slot: int) -> int:
        return self.base + slot * self.stride


#: **Found**: roster block `+0x0C`, bit 7 -- see "The quickfight bit is roster
#: `+0x0C`" in `docs/50-experiments.md`. Selecting QUICK from the combat menu
#: moved exactly this bit for exactly the character quickfought, and nothing
#: else in 13568 bytes but two of COMBAT's own scratch bytes.
#: The offset and the mask are `live.ROSTER_QUICKFIGHT` / `live.QUICKFIGHT_BIT`,
#: so the roster card's badge and this write cannot come to disagree.
QUICKFIGHT = QuickfightFlag(
    base=games.POOL_OF_RADIANCE.roster_base + live.ROSTER_QUICKFIGHT,
    stride=ROSTER_STRIDE, mask=live.QUICKFIGHT_BIT)


def quickfight_flag(game: games.Game | None = None) -> QuickfightFlag | None:
    """This title's flag, or None while the bit itself is unfound.

    The *offset* is roster `+0x0C` in every title, because the roster block is
    the same block; what moves is where the roster page lives, and
    `Game.roster_base` is that -- `$8300` in Pool of Radiance's second file,
    `$6700` inside the payload in Curse and Silver Blades (#29).

    `QUICKFIGHT` being None is the separate case, and it stays the one that
    means "nobody has found this bit at all": `ClearQuickfight` then refuses
    with `WANTED` rather than writing an offset nothing established.
    """
    if QUICKFIGHT is None:
        return None
    game = game or games.DEFAULT
    return QuickfightFlag(base=game.roster_base + live.ROSTER_QUICKFIGHT,
                          stride=ROSTER_STRIDE, mask=live.QUICKFIGHT_BIT)


WANTED = ("the quickfight flag has not been found -- see 'The quickfight flag "
          "-- WANTED' in docs/80-fields-wanted.md")


class ClearQuickfight(Action):
    """Clear the bit the combat menu's QUICK sets, for everyone.

    The write is the roster block at `Game.roster_base + slot * $20`, byte
    `+0x0C`, bit 7. The roster page is saved with the game, so this bit reaches
    the disk: eight of the player's own save disks carry it set for one
    character and clear for the other seven.

    **What is established and what is not.** That QUICK writes this bit, for
    that character alone, is established -- it is the only byte outside
    COMBAT's own scratch that moved. That it *survives* a fight is established
    from those eight saves. What is **not** established is that clearing it
    hands a character back: setting it out of band mid-fight did not stop the
    game asking that character for orders, so on the evidence so far the bit
    marks "the computer is playing this character's action" rather than a
    sticky quickfight. Clearing it is therefore safe -- it restores the byte
    every clean save has -- and its effect on the next fight is unproven. See
    `docs/80-fields-wanted.md` for the experiment that would settle it.

    Legal anywhere. Clearing it mid-fight is the same write as clearing it
    afterwards.
    """

    name = "clear-quickfight"
    label = "Turn quickfight off"
    description = "clear the combat menu's QUICK bit for every character"
    combat_legal = True

    def __init__(self, flag: QuickfightFlag | None = None,
                 game: games.Game | None = None):
        super().__init__(game)
        self.flag = flag if flag is not None else quickfight_flag(self.game)

    def legality(self, target) -> Verdict:
        if self.flag is None:
            return Verdict(False, WANTED)
        return super().legality(target)

    def run(self, target, **kwargs) -> Outcome:
        party = read_party(target, self.game)
        if party is None:
            return Outcome(False, "no party to read")
        writes = []
        for m in party:
            addr = self.flag.address(m.slot)
            current = target.read(addr, 1)[0]
            if current & self.flag.mask:
                writes.append((addr, bytes([current & ~self.flag.mask])))
        _write_all(target, writes)
        if not writes:
            return Outcome(True, "nobody was on quickfight")
        return Outcome(True, f"took {len(writes)} character"
                             f"{'s' if len(writes) != 1 else ''} off quickfight",
                       tuple(writes))


class QuickfightWatcher:
    """Clear the flag on the tick that combat ends, if the caller wants that.

    Deliberately a plain object with one method: the window already polls the
    mode flag for the combat canvas, so this needs no timer of its own. Feed it
    the mode on every poll and it fires exactly on the 2-to-not-2 edge -- not
    on every tick afterwards, which would fight the player who turned
    quickfight on deliberately in the *next* fight.
    """

    def __init__(self, action: ClearQuickfight | None = None,
                 enabled: bool = False, game: games.Game | None = None):
        self.action = action or ClearQuickfight(game=game)
        self.enabled = enabled
        self.was: int | None = None

    @property
    def game(self) -> games.Game:
        """Whose mode flag to watch: the action's, so the two cannot drift."""
        return self.action.descriptor

    def poll(self, target) -> Outcome | None:
        """One tick. Returns the outcome only on the tick that fires.

        A title with no measured mode flag never fires: `mode` answers None,
        which is the same "no edge" answer an unreadable machine gives, and
        the action underneath would refuse in any case.
        """
        now = mode(target, self.game)
        was, self.was = self.was, now
        if not self.enabled or was != COMBAT or now == COMBAT or now is None:
            return None
        return self.action.apply(target)


# --- the set of them ---------------------------------------------------------


def actions(store: SpellStore | None = None,
            game: games.Game | None = None) -> tuple[Action, ...]:
    """Every action, in the order the bar lays them out.

    The window iterates this: one button per action, `label` on it,
    `description` and the reason from `legality` in its tooltip, and
    `confirm` asked first where it is non-empty.

    **This tuple is the reading order**, and `actionbar.COLUMNS` breaks it into
    rows -- so the three spell-and-healing actions fill the first row and the
    two that stand alone fill the second. Donald chose the grouping; moving an
    entry here moves the button.

    `game` is which title they act on, and it reaches every address each one
    writes. None is Pool of Radiance, which is what every caller written before
    there was a second title meant.
    """
    store = store or SpellStore()
    return (HealParty(game), StoreSpells(store, game),
            RestoreSpells(store, game), IdentifyItems(game),
            ClearQuickfight(game=game))


#: **`LevelUp` is deliberately not in that list.** Every other action here is
#: party-wide, so one button on a bar is the whole of what it needs to be told;
#: levelling is about *one* character and a bar button cannot say which -- the
#: old one silently meant slot 0. It lives on the roster card instead, where
#: the card answers the question, and the window instantiates it directly.


# --- fasttraveling between areas ---------------------------------------------------
#
# "Fast Travel" on the screen; `FastTravel` in here, because `NEWECL` is what the
# game calls it and the names in this file are the game's. The one thing in
# this file that does more than poke a byte: it hands the CPU a new program
# counter. Shown to every user since P20 -- it was debug-mode-only while where
# it landed was unmeasured.
#
# `docs/118-debug-mode.md` is the plan and the evidence. In short: an area exit
# is a script ending in `NEWECL`, whose handler at `DUNGEON $2011` writes five
# things and restarts the overlay. A fasttravel is those writes made from outside,
# with the operand fetch -- which needs a script stream we are not in --
# skipped by entering the handler at its tail.
#
# **Nothing below has ever been run against the game.** The writes are copied
# from the handler; entering it at `$2034` from the key-wait loop is a guess,
# and so is what happens to the party afterwards.

#: Which `POOL` disk the arriving area lives on. `LIBRARY $43A4` reads it and
#: prompts if that disk is not in the drive.
FASTTRAVEL_DISK = 0x6E12
#: The live party square inside `GDRIVE00`, of which `$49C0`-`$49C2` is a
#: lagging copy: x, y, facing. `$1A3C`, called from `$2034`, copies these into
#: the save's own bytes, which is why the arrival square is written before the
#: jump and not after.
FASTTRAVEL_X, FASTTRAVEL_Y, FASTTRAVEL_FACING = 0xC04B, 0xC04C, 0xC04D
#: Where the party came *from*: `$2011`-`$2016` sets it, and the arriving
#: script's entry 4 compares it against its own id.
#:
#: **It survives the overlay restart, and the arriving script does read it.**
#: P43 measured the opposite once and was wrong about why: `$19E1` --
#: `LDX #3 / JSR $19FC / LDA $6E1B / AND #$7F / STA $49F2` -- rewrites it to
#: the *arriving* id once the entry has run, so a snapshot taken after the
#: area settles always shows the current area whatever was written here.
#: Proved by fasttraveling into area 22 with `$49F2` = 23: `ECL16`'s
#: `COMPARE [$49F2], 23 / IF= / EXIT` fired, the script left the square alone,
#: and the party stood where the fasttravel had put it.
FASTTRAVEL_FROM = 0x49F2
#: The `ECL` slot of the loaded-files cache. Bit 7 means "reload me".
FASTTRAVEL_SLOT = 0x6E1B
#: Zeroed by `$202A`-`$2032`: the origin of the scratch/persistent split.
FASTTRAVEL_SCRATCH, FASTTRAVEL_SCRATCH_LEN = 0x4A00, 0x20
#: Non-zero indoors, zero on the overland map. Read, never written: it decides
#: whether `LOADFILES` asks for a `GEO` or a `SQRDATA`.
FASTTRAVEL_INDOORS = 0x49E6
#: The tail of `NEWECL`'s handler, past the operand fetch. `$203A` reloads the
#: stack pointer from `$03BF`, so the call depth we interrupt does not matter.
NEWECL_TAIL = 0x2034
#: `$6E11`: DUNGEON is the resident overlay. `$2034` is some other overlay's
#: code when it is not.
DUNGEON = 1
#: `DUNGEON`'s key-wait loop in the world, the one place it is safe to take the
#: PC from -- mid-script or mid-load the stack reset would discard work in
#: flight.
#:
#: **Measured, not guessed.** 400 PC samples of an idle party landed on exactly
#: `$10C2 $10C5 $10C8 $10CA $10CC $10CF $10D1 $10D3 $10D6` in the loop and
#: nothing above it, and the code agrees: `$10E0` is the `JMP $10C2` that
#: closes it, `$10E3`-`$10EB` is its own exit tail, and `$10EC` starts a
#: different routine (`LDA #$00 / STA $6DD5`). So the window ends at `$10EC`.
KEY_WAIT = (0x10C2, 0x10EC)
#: The key fetcher the loop calls, `$2E4E`-`$2E6A` inclusive: `LDA $DC00` for
#: the CIA row, then the KERNAL buffer, then `RTS`. FastTraveling from inside it is
#: safe for the same reason as the loop -- it is called *from* the loop, so
#: `$203A`'s stack reload discards the same nothing -- and P15 fasttraveled
#: successfully from `$2E4E` before this was written down. Nine idle samples
#: in ten land in one window or the other, so refusing the fetcher made the
#: button fail about half the times it was pressed.
KEY_FETCH = (0x2E4E, 0x2E6B)


#: No title given means "whatever table this build has", which is what every
#: caller written before there was a second title meant. A caller that has a
#: title passes it, and five of the six get nothing.
ANY_TITLE = object()


def area_rows(title=ANY_TITLE) -> tuple:
    """This title's area table, or nothing if there is none.

    `goldbox/areas.py` owns it. Imported here rather than at the top of the module
    so that a checkout without it still has the other five actions.

    **Only Pool of Radiance has one.** A row's disk number and `ECL` id are
    Pool of Radiance's, and `FastTravel` writes both into the running machine, so
    another title's session must be offered nothing rather than these --
    `goldbox.areas.areas_for_title` is where that refusal lives.
    """
    try:
        from goldbox import areas
    except ImportError:                     # pragma: no cover - defensive
        return ()
    if title is ANY_TITLE:
        return tuple(areas.AREAS)
    return tuple(areas.areas_for_title(title))


def landing_square(geo) -> tuple[int, int, int] | None:
    """Where to put a party arriving in an area whose square nobody harvested.

    `goldbox.areas.landing_square` does the work; this is the seam, imported the
    same guarded way as the table for the same reason. It replaces a rule that
    took the first square with any passable edge, which came to `(0, 0)` on all
    twenty-nine maps and left a party walled into a pocket on four of them --
    P20, `work/reports/p20-arrivals.md`.

    Carrying the party's *current* square over remains the one option to avoid:
    the maps do not line up, and (13,13) in the Slums is a wall in Sokol Keep.
    """
    if geo is None:
        return None
    try:
        from goldbox.areas import landing_square as pick
    except ImportError:                     # pragma: no cover - defensive
        return None
    return pick(geo)


def place_name(geo: str) -> str | None:
    """What to call the map now resident, or None if we cannot say.

    `goldbox.areas.geo_name`, imported the same guarded way as the table and for
    the same reason. The name is the one the status line under the map already
    shows -- `AutomapState.area_label` calls the same function -- so the two
    cannot disagree about where the party is.
    """
    try:
        from goldbox.areas import geo_name
    except ImportError:                     # pragma: no cover - defensive
        return None
    return geo_name(geo)


@dataclass(frozen=True)
class Waypoint:
    """Where the party was before a fasttravel, so that `FastTravel Back` has an answer."""

    area: int
    disk: int | None
    square: tuple[int, int, int] | None

    @property
    def id(self) -> int:
        """Spelled the way a row of the area table spells it, so that the same
        `legality` serves both buttons even when the table has no such row."""
        return self.area


def newecl_writes(from_area: int, to_area: int, disk: int | None = None,
                  arrival=None) -> tuple[tuple[int, bytes], ...]:
    """The bytes `NEWECL` writes, in its own order, minus the operand fetch.

    **The whole write sequence lives here**, in one function, because it is a
    guess in the sense that matters: the individual writes are read off
    `DUNGEON $2011`-`$2032`, and that they can be made from outside while the
    game sits in its key-wait loop is not established. Correcting the sequence
    should mean editing this function and nothing else.

    `arrival` is `(x, y, facing)`, or `(x, y)` where the departing script sets
    the square but not the direction, or None to write no square at all and let
    the arriving script's entry 4 place the party.
    """
    writes: list[tuple[int, bytes]] = []
    if disk is not None:
        writes.append((FASTTRAVEL_DISK, bytes([disk & 0xFF])))
    if arrival is not None:
        writes.append((FASTTRAVEL_X, bytes(int(v) & 0xFF for v in arrival)))
    writes.append((FASTTRAVEL_FROM, bytes([from_area & 0x7F])))
    writes.append((FASTTRAVEL_SLOT, bytes([(to_area & 0x7F) | 0x80])))
    writes.append((FASTTRAVEL_SCRATCH, bytes(FASTTRAVEL_SCRATCH_LEN)))
    return tuple(writes)


#: VICE's `e_PC`. The fallback, and no longer a guess: `CMD_REGISTERS_AVAILABLE`
#: **is** served by this build and names id 3 `PC`, 16 bits wide, beside `A`,
#: `X`, `Y`, `SP` and `FL` at 0, 1, 2, 4 and 5. `pc_register` asks anyway,
#: because the id is a property of the emulator and not of the game.
PC_REGISTER = 3
#: `CMD_REGISTERS_AVAILABLE`. Not in `automap/vice.py`'s command table because
#: nothing else needs it.
CMD_REGISTERS_AVAILABLE = 0x83


def pc_register(mon, default: int = PC_REGISTER) -> int:
    """Which register id this VICE calls `PC`, asked rather than assumed.

    One round trip, and only ever one: the answer cannot change under a running
    emulator, so it is cached on the monitor object. A build that does not
    serve `0x83` -- which is what this code believed for months, wrongly --
    falls back to `PC_REGISTER`.
    """
    got = getattr(mon, "_pc_register", None)
    if got is not None:
        return got
    got = default
    try:
        resp = mon.command(CMD_REGISTERS_AVAILABLE, struct.pack("<B", 0))
        count = struct.unpack("<H", resp[:2])[0]
        off = 2
        for _ in range(count):
            size, rid, _bits, length = resp[off:off + 4]
            if resp[off + 4:off + 4 + length] == b"PC":
                got = rid
                break
            off += size + 1
    except Exception as exc:                # pragma: no cover - build-specific
        _log.debug("this build does not list its registers (%s); "
                   "the PC is assumed to be %d", exc, default)
        got = default
    try:
        mon._pc_register = got
    except Exception as exc:
        # A monitor that will not take the attribute costs a round trip on
        # every call and nothing else.
        _log.debug("could not cache the PC register id: %s", exc)
    return got


def program_counter(target):
    """The CPU's PC, or None where this backend cannot say.

    The `Target` contract is `read` and `write` and deliberately nothing else,
    so the CPU is reached the two ways there are: a target that offers `pc()`
    of its own (a test's, and whatever a second backend grows), or the VICE
    monitor a `ViceTarget` is holding.

    The value is still sanity-checked before anything is written to it: a
    6502's other registers are eight bits wide, so an id that is not the PC
    cannot hold an address in `DUNGEON`.
    """
    own = getattr(target, "pc", None)
    if callable(own):
        return own()
    mon = getattr(target, "_mon", None)
    if mon is None:
        return None
    try:
        regs = mon.registers()
    except Exception as exc:
        _log.debug("could not read the registers: %s", exc)
        return None
    finally:
        # The resume matters more than the read did: the monitor holds the
        # CPU, so leaving without it freezes the game.
        try:
            mon.resume()
        except Exception as exc:
            _log.debug("could not resume after reading the registers: %s", exc)
    return regs.get(pc_register(mon))


def jump(target, address: int) -> bool:
    """Set the PC and let the machine run. False if this backend cannot.

    The last step of a fasttravel and the only irreversible one: everything before it
    is bytes in RAM, and this is what makes the game act on them.
    """
    own = getattr(target, "set_pc", None)
    if callable(own):
        own(address)
        return True
    mon = getattr(target, "_mon", None)
    if mon is None:
        return False
    try:
        mon.set_registers({pc_register(mon): address})
    except Exception:
        _log.exception("could not set the PC to $%04X", address)
        return False
    finally:
        try:
            mon.resume()
        except Exception as exc:
            _log.debug("could not resume after setting the PC: %s", exc)
    return True


class FastTravel(Action):
    """Put the party in another area, the way the game's own exits do.

    **"Fast Travel" is what the user calls it.** `FastTravel` is the game's own
    name for the mechanism -- `NEWECL` -- and stays the name in the code.

    **The writes are proven; the arrival is measured.** Entering `NEWECL`'s
    handler at `$2034` from the key-wait loop has been done in the game and the
    party walked afterwards (P15, `docs/118-debug-mode.md`), and P20 fasttraveled
    into all fifteen areas that then had no arrival square and recorded where
    each landed. Fourteen still have none and get a square off the map instead.

    Two guards that are not optional, both re-checked at `apply` time:

    * **`$6E11` must be 1.** `$2034` is some other overlay's code otherwise,
      and jumping there is an immediate crash.
    * **the PC must be in `DUNGEON`'s key-wait loop.** Mid-script or mid-load
      the stack reload at `$203A` throws away work in flight. This doubles as
      the check that `PC_REGISTER` is the register we think it is.

    What it cannot guard: the quest flags. Arriving this way is not the same
    as having played there, the arriving script assumes things the party never
    did, and the honest answer is to say so rather than to pretend otherwise.
    That is what `HELP` is for, and the row keeps it under a help icon.
    """

    name = "fasttravel"
    label = "Fast Travel"
    description = ("travel to another area the way the game's own exits do -- "
                   "it writes to the running game")
    combat_legal = False
    #: What travelling does not guarantee, in Donald's own words, kept where
    #: it can be read rather than dismissed: the row hangs it off a help icon.
    #: It is deliberately not a list of what could go wrong in the machine --
    #: that half has been made in the game and the party walked afterwards
    #: (P15) -- but of what the *game* assumes about a party that arrives
    #: somewhere it never played to.
    #:
    #: **There is no confirmation any more.** It was a dialog in front of every
    #: trip until Donald tested the feature; the game itself asks for the disk
    #: it wants, so the popup asked a question the game was about to ask again.
    HELP = (
        "Fast travel puts the party in another area the way the game's own "
        "exits do. The area you arrive in assumes you got there by playing: "
        "its script can expect quest flags your party never set, people "
        "already spoken to and fights already won. In the fourteen areas "
        "where the game does not place the party itself, wish picks a square "
        "in the largest open part of the map, which need not be where a "
        "player would normally walk in. Nothing here can be undone from "
        "inside the game, so point the emulator at a copy of your save disk, "
        "never the original.")

    def __init__(self):
        # Pool of Radiance, always and explicitly. Every address below is one
        # of this title's overlays -- `NEWECL`'s tail, DUNGEON's key-wait loop,
        # the disk and cache-slot bytes -- and `goldbox/areas.py` has a table for
        # no other title, so the row offers a later title nothing at all (#14).
        super().__init__(games.POOL_OF_RADIANCE)
        #: Where the last fasttravel came from. `FastTravel Back` reads it; None until a
        #: fasttravel has been made, which is why the button starts disabled.
        self.back: Waypoint | None = None

    # -- reading the machine ---------------------------------------------

    @staticmethod
    def current_area(target) -> int | None:
        """The id of the area running now: `$6E1B` without the reload bit."""
        raw = _read(target, FASTTRAVEL_SLOT, 1)
        return raw[0] & 0x7F if raw else None

    @staticmethod
    def current_disk(target) -> int | None:
        raw = _read(target, FASTTRAVEL_DISK, 1)
        return raw[0] if raw else None

    @staticmethod
    def current_square(target) -> tuple[int, int, int] | None:
        raw = _read(target, FASTTRAVEL_X, 3)
        return (raw[0], raw[1], raw[2]) if raw and len(raw) == 3 else None

    # -- may we -----------------------------------------------------------

    def legality(self, target, area=None) -> Verdict:
        base = super().legality(target)
        if not base:
            return base
        if mode(target, self.game) != DUNGEON:
            return Verdict(False, "$6E11 is not 1, so DUNGEON is not the "
                                  "resident overlay and $2034 is not NEWECL")
        pc = program_counter(target)
        if pc is None:
            return Verdict(False, "this backend cannot read the CPU, and "
                                  "fast travel has to set the program counter")
        if not any(lo <= pc < hi for lo, hi in (KEY_WAIT, KEY_FETCH)):
            return Verdict(False, f"the PC is ${pc:04X}, outside DUNGEON's "
                                  f"key-wait loop (${KEY_WAIT[0]:04X}-"
                                  f"${KEY_WAIT[1] - 1:04X}) and the key "
                                  f"fetcher it calls (${KEY_FETCH[0]:04X}-"
                                  f"${KEY_FETCH[1] - 1:04X}): the game is busy")
        if area is None:
            return Verdict(False, "choose an area")
        if not getattr(area, "fasttravelable", True):
            return Verdict(False, self.ATTRACT_TRAP)
        here = self.current_area(target)
        if here is not None and here == getattr(area, "id", None):
            return Verdict(False, "the party is already in that area, and "
                                  "NEWECL skips a same-area transition")
        raw = _read(target, FASTTRAVEL_INDOORS, 1)
        indoors = raw[0] if raw else None
        if indoors == 0 and not getattr(area, "outdoors", False):
            return Verdict(False, self.OUTDOORS_TRAP)
        return Verdict(True)

    def apply(self, target, area=None, arrival=None, **kwargs) -> Outcome:
        verdict = self.legality(target, area)
        if not verdict:
            return Outcome(False, verdict.reason)
        return self.run(target, area=area, arrival=arrival)

    # -- doing it ---------------------------------------------------------

    def run(self, target, area=None, arrival=None, **kwargs) -> Outcome:
        here = self.current_area(target)
        to = getattr(area, "id", area)
        if arrival is None:
            arrival = self.arrival_of(area)
        notes = list(self.warnings(target, area, arrival))
        # Read before writing: the first write is $6E12 and the second is
        # $C04B, so a waypoint taken afterwards would record where we are
        # going rather than where we were.
        was = Waypoint(here, self.current_disk(target),
                       self.current_square(target)) if here is not None else None
        writes = newecl_writes(here or 0, to, getattr(area, "disk", None),
                               arrival)
        _write_all(target, writes)
        if not jump(target, NEWECL_TAIL):
            return Outcome(False,
                           "the writes were made but the program counter could "
                           "not be set, so nothing has happened yet -- $6E1B is "
                           "flagged for reload and the next area change will "
                           "act on it",
                           writes, tuple(notes))
        self.back = was
        name = getattr(area, "name", None) or getattr(area, "ecl", str(to))
        return Outcome(True, f"travelling to {name} - watch for the drive light",
                       writes, tuple(notes))

    @staticmethod
    def arrival_of(area):
        """The area's own arrival square as `(x, y[, facing])`, or None."""
        got = getattr(area, "arrival", None)
        if got is None:
            return None
        if isinstance(got, tuple):
            return got
        if got.facing is None:
            return (got.x, got.y)
        return (got.x, got.y, got.facing)

    def warnings(self, target, area, arrival) -> tuple[str, ...]:
        """Everything true about this fasttravel that the caller should know first."""
        out = ["the arriving script assumes quest flags the party never set; "
               "arriving this way is not the same as having played there"]
        if arrival is None:
            out.append("no arrival square is known for this area, so the party "
                       "lands wherever the arriving script leaves it -- which "
                       "it does: $49F2 survives the restart, so the arriving "
                       "script's entry takes its came-from-elsewhere branch")
        if not getattr(area, "has_map", True):
            out.append(f"{getattr(area, 'ecl', 'this area')} loads no map of "
                       "its own")
        if getattr(area, "outdoors", False):
            out.append("this is an overland area and loads a SQRDATA rather "
                       "than a GEO; an arrival square is pointless there, "
                       "because outdoors the party's position is $49C3/$49C4 "
                       "and $C04B is not even GDRIVE00's any more")
        raw = _read(target, FASTTRAVEL_INDOORS, 1)
        indoors = raw[0] if raw else None
        if indoors is not None:
            outdoors_now = indoors == 0
            if outdoors_now != bool(getattr(area, "outdoors", False)):
                out.append(f"$49E6 is {indoors}, so LOADFILES will ask for a "
                           f"{'SQRDATA' if outdoors_now else 'GEO'}")
        return tuple(out)

    #: `ECL1E` is the attract-mode demo and fasttraveling into it ends the session:
    #: P20 read `$C04B`-`$C04D` as `254, 127, 16` with no `GEO` resident, no
    #: status line and no command bar, and the PC never came back to the
    #: key-wait loop, so nothing could be fasttraveled out again. `FastTravelBar` does not
    #: offer it; this refuses it for a caller that did not come through the
    #: dropdown. `work/reports/p20-arrivals.md`.
    ATTRACT_TRAP = ("this is the attract-mode demo, not a place: travelling "
                    "there leaves the world -- no map, no status line, and the "
                    "program counter never returns to DUNGEON's key-wait loop, "
                    "so there is no way back out of it")

    #: FastTraveling out of an overland area into an indoors one hangs the loader:
    #: it asks for the target's side and goes on asking, and re-attaching,
    #: attaching something else first and poking `$49E6` afterwards all fail.
    #: The other direction is fine -- area 23 to 26 worked, and the arriving
    #: script sets `$49E6` itself. See `docs/50-experiments.md`.
    OUTDOORS_TRAP = ("the party is on the overland map ($49E6 is 0) and this "
                     "area is indoors: travelling that way hangs the loader "
                     "asking for the disk for ever. Walk off the overland map "
                     "first")

    # -- and back again ---------------------------------------------------

    def back_verdict(self, target) -> Verdict:
        if self.back is None:
            return Verdict(False, "nothing to go back to: the party has not "
                                  "travelled anywhere this session")
        area = area_by_id(self.back.area)
        return self.legality(target, area or self.back)

    def apply_back(self, target) -> Outcome:
        """FastTravel to where the last fasttravel started, on the square it started on."""
        verdict = self.back_verdict(target)
        if not verdict:
            return Outcome(False, verdict.reason)
        was, self.back = self.back, None
        here = self.current_area(target)
        writes = newecl_writes(here or 0, was.area, was.disk, was.square)
        _write_all(target, writes)
        if not jump(target, NEWECL_TAIL):
            self.back = was
            return Outcome(False, "the writes were made but the program "
                                  "counter could not be set", writes)
        row = area_by_id(was.area)
        name = getattr(row, "name", None) or f"area {was.area}"
        return Outcome(True, f"travelled back to {name}", writes)


def area_by_id(id: int):
    """One row of the area table, or None."""
    for row in area_rows():
        if getattr(row, "id", None) == id:
            return row
    return None
