"""Acting on the running game: the writes, and when each one is legal.

`docs/102-live-actions.md` is the plan; this is the engine half of it. No Qt in
here, the same way `live.py` and `combat.py` have none -- an action takes a
`Target`, decides whether it is legal, and either writes or says why not. The
window wires buttons to these; the tests drive them against `MemoryTarget`.

**Everything is gated on `$6E11`**, the mode flag LINKER dispatches on, and
never on the screen: `2` is COMBAT. An action that is illegal in combat refuses
at `apply` time and not only in its tooltip, because a button's enabled state is
one poll interval stale and a fight can start inside that interval.

**Nothing here writes to a disk.** These change the machine's memory; the player
saves in the game as usual, which is what keeps the losslessness promise intact.

Two facts from `docs/50-experiments.md` bound what is safe to write:

* **The item area at `$5900` is a copy.** Poking `$5A98` to 150 lb was reverted
  by the game, so a write there is fed from a master elsewhere and may not
  stick. `IdentifyItems` writes anyway -- it is one bit and the failure mode is
  "nothing happened" -- but it says so, and it is the one action whose effect
  the caller should verify by looking at the game.
* **`$6B00` is the resident character record** and `$6C00` the resident roster
  block, so the game works on a *copy* of whichever character is in hand. A
  write into the slot area is what the next save writes out; a write into a
  field the game is holding in the resident copy at that moment can be
  overwritten by it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from dataclasses import field as dc_field

from por import items as por_items
from por.layout import Confidence, field_by_name
from por.record import CharacterRecord
from por.savegame import (
    ITEM_AREA_BASE,
    ROSTER_HP_CURRENT,
    ROSTER_STRIDE,
    SAVE1_LOAD_ADDRESS,
    SLOT_AREA_BASE,
    SLOT_STRIDE,
    SaveGame0,
    SaveGame1,
)

from . import live
from .combat import COMBAT, MODE
from .paths import config_dir

# The whole memorised list, as the record stores it: a packed list of spell ids
# at 0x020. Sixteen bytes is exactly enough -- Pool of Radiance caps a cleric at
# 3/3/2 and a magic-user at 4/2/2, so even a multi-class caster at the ceiling
# has sixteen spells prepared and no more.
SPELLS_MEMORISED = field_by_name("spells_memorised")

SPELL_FILE = "spells.json"
UNKNOWN_DISK = "unknown disk"


def mode(target) -> int | None:
    """Which overlay is running, or None if the machine cannot be read."""
    try:
        raw = target.read(MODE, 1)
    except Exception:
        return None
    return raw[0] if raw else None


def in_combat(target) -> bool:
    """True only when the mode flag *says* combat. An unreadable machine is not
    combat -- it is unreadable, and every action refuses on that separately."""
    return mode(target) == COMBAT


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
    """

    slot: int
    record: CharacterRecord
    roster: bytes

    @property
    def name(self) -> str:
        return self.record.name

    @property
    def record_base(self) -> int:
        return SLOT_AREA_BASE + self.slot * SLOT_STRIDE

    @property
    def roster_base(self) -> int:
        return SAVE1_LOAD_ADDRESS + self.slot * ROSTER_STRIDE

    @property
    def item_base(self) -> int:
        return ITEM_AREA_BASE + self.slot * por_items.ITEM_BLOCK_STRIDE

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

    def __iter__(self):
        return iter(self.members)

    def __len__(self) -> int:
        return len(self.members)

    def by_slot(self, slot: int) -> Member | None:
        for m in self.members:
            if m.slot == slot:
                return m
        return None


def read_party(target) -> Party | None:
    """The party, or None when these bytes are not one.

    Same two blocks as `live.read_snapshot` and the same validate-before-trust
    rule: at the title screen, mid-load or in a menu the bytes simply are not
    there, and that is ordinary rather than an error.
    """
    if target is None:
        return None
    try:
        save0_bytes, roster_bytes = live.read_blocks(target)
        save0 = SaveGame0.from_bytes(bytes(save0_bytes))
        save1 = SaveGame1(bytes(roster_bytes[:live.ROSTER_PAGE])
                          + bytes(0x800 - live.ROSTER_PAGE))
        members = tuple(
            Member(slot=s.index, record=s.record, roster=save1.roster(s.index).raw)
            for s in save0.characters)
    except Exception:
        return None
    return Party(members, bytes(save0_bytes)) if members else None


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
    #: False means "refuse while $6E11 is 2".
    combat_legal = False
    #: Non-empty means ask this question before running. There is no in-game
    #: undo for anything that carries one.
    confirm = ""

    def legality(self, target) -> Verdict:
        if target is None:
            return Verdict(False, "no emulator attached")
        state = mode(target)
        if state is None:
            return Verdict(False, "the machine is not readable right now")
        if state == COMBAT and not self.combat_legal:
            return Verdict(False, f"{self.label.lower()} is refused during a "
                                  f"fight ($6E11 is 2)")
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

    The write is the roster block at `$8300 + slot * $20`, byte `+0x19`.
    Current hit points are not in the stored 256 bytes of a record -- record
    `0x119` is export-only -- so this is a live-only address and the roster is
    the only copy a running game has.

    **A character at zero is skipped.** Zero is dead or dying, and whatever else
    the game marks that with is not decoded; raising the hit point byte alone
    would be a half-write, which is the same objection that stops levelling.

    Confirmed live: four wounded characters healed and the game's own party
    list redrew at their maxima, and SILAS went 8 to 9 mid-fight at
    `$6E11 = 2`. See `docs/50-experiments.md`.
    """

    name = "heal"
    label = "Heal the party"
    description = "current hit points to maximum, for every conscious character"
    combat_legal = True

    def run(self, target, **kwargs) -> Outcome:
        party = read_party(target)
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
    label = "Store memorised spells"
    description = "remember the memorised list for every character"

    def __init__(self, store: SpellStore | None = None):
        self.store = store or SpellStore()

    def run(self, target, disk: str = "", **kwargs) -> Outcome:
        party = read_party(target)
        if party is None:
            return Outcome(False, "no party to read")
        for m in party:
            self.store.put(disk, m.name, m.record.get_raw("spells_memorised"))
        return Outcome(True, f"stored spells for {len(party)} character"
                             f"{'s' if len(party) != 1 else ''}")


class RestoreSpells(Action):
    """Write the stored memorised list back, so nobody has to rest for it.

    **Illegal in combat.** The write is record `0x020`, sixteen bytes, in the
    slot area at `$4D00 + slot * $100` -- inside the stored 256 bytes, so it is
    also what the next save writes out.

    Only the memorised list moves. The capacity at `0x0EE` says how many spells
    of each level the character *may* prepare and does not change with resting,
    so restoring it would be writing a field the action has no business in.
    """

    name = "restore-spells"
    label = "Restore memorised spells"
    description = "put back the memorised list stored earlier"

    def __init__(self, store: SpellStore | None = None):
        self.store = store or SpellStore()

    def run(self, target, disk: str = "", **kwargs) -> Outcome:
        party = read_party(target)
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

    **The write may not stick.** `$5900`+ is a copy fed from a master
    elsewhere -- poking an item's weight there was reverted by the game -- so
    this is the one action whose effect is worth checking in the game's own
    item list before believing it.
    """

    name = "identify"
    label = "Identify all items"
    description = "clear the hidden-name bits on every item the party carries"
    confirm = ("Identify every item the party carries? There is no way to undo "
               "this in the game.")

    def run(self, target, **kwargs) -> Outcome:
        party = read_party(target)
        if party is None:
            return Outcome(False, "no party to read")
        writes = []
        for m in party:
            base = m.item_base - live.BLOCKS[0][0]
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

#: What the trainer changes that the level tables do **not** answer for. Each
#: entry is a field the action would have to write and a reason it cannot yet
#: be written. This is the whole of why levelling refuses: a half-levelled
#: character is a corrupt character, and every one of these is a field where
#: writing the table's number would be a guess.
LEVEL_UP_BLOCKERS: tuple[tuple[str, str], ...] = (
    ("hp_max",
     "the trainer rolls a hit die and adds the constitution bonus; the table's "
     "hp_max is the maximum roll, not what the game would give"),
    ("hp_rolled",
     "0x0ED is the rolled total behind hp_max and moves with it; nothing "
     "derives one from the other"),
    ("save_paralysis",
     "por/levels.py carries a BASE saving-throw table and says so: stored "
     "saves differ between two characters of the same class and level, so the "
     "record holds modifiers that are not understood"),
    ("spells_castable",
     "0x0EE is nibble-packed capacity including the wisdom bonus for clerics, "
     "and no bonus table has been checked against a record"),
    ("thief_pick_pockets",
     "there is no per-level thief skill table in the project at all"),
)

#: And the fields the tables *do* answer for, none of which is CONFIRMED. Kept
#: as data so that promoting a field in por/layout.py is what unblocks it,
#: rather than an edit here.
LEVEL_UP_FIELDS: tuple[str, ...] = (
    "level", "thac0_base", "level_cleric", "level_fighter",
    "level_magic_user", "level_thief",
)


def level_up_blockers(record: CharacterRecord | None = None) -> tuple[str, ...]:
    """Every reason levelling refuses, most specific first.

    Returns an empty tuple only when every field the trainer touches is both
    known and CONFIRMED, which no field currently is. It takes a record so that
    a class-specific blocker -- thief skills for a thief -- can be dropped for
    a character it cannot apply to, once the rest are gone.
    """
    out = [f"{name}: {why}" for name, why in LEVEL_UP_BLOCKERS]
    unsure = [name for name in LEVEL_UP_FIELDS
              if field_by_name(name).confidence is not Confidence.CONFIRMED]
    if unsure:
        out.append("not CONFIRMED, so not written: " + ", ".join(sorted(unsure)))
    out.append(
        "and what else the trainer touches is unmeasured -- see 'What the "
        "trainer changes when an ability score is altered' in "
        "docs/80-fields-wanted.md")
    return tuple(out)


class LevelUp(Action):
    """Raise a character a level without walking to the training hall.

    **It refuses, and that is the implementation.** The level tables in
    `por/levels.py` are verified, but they answer for six fields and the
    trainer touches more than six: hit points are rolled, saving throws carry
    modifiers nobody has measured, spell capacity is packed with a wisdom bonus
    that has never been checked, and there is no thief skill table at all.
    Writing the six we know and leaving the rest stale is exactly the corrupt
    character this action exists to avoid, so it writes nothing and names every
    field standing in the way.

    `level_up_blockers()` is that list, and it empties itself as
    `por/layout.py` promotes fields -- so this becomes an action rather than a
    refusal by making the fields CONFIRMED, not by editing it.
    """

    name = "level-up"
    label = "Level up"
    description = "raise a character a level without the trainer"
    confirm = "Level up this character? There is no way to undo this in the game."

    def run(self, target, slot: int = 0, **kwargs) -> Outcome:
        party = read_party(target)
        if party is None:
            return Outcome(False, "no party to read")
        member = party.by_slot(slot)
        if member is None:
            return Outcome(False, f"no character in slot {slot}")
        blockers = level_up_blockers(member.record)
        if blockers:
            return Outcome(False,
                           f"levelling {member.name} would write fields we "
                           f"cannot derive, so it writes nothing",
                           (), blockers)
        # No path here yet, deliberately: when the blockers empty, the writes
        # go in with a test that levels a real character.
        return Outcome(False, "no levelling path is implemented", (), blockers)


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
QUICKFIGHT = QuickfightFlag(base=SAVE1_LOAD_ADDRESS + 0x0C,
                            stride=ROSTER_STRIDE, mask=0x80)

WANTED = ("the quickfight flag has not been found -- see 'The quickfight flag "
          "-- WANTED' in docs/80-fields-wanted.md")


class ClearQuickfight(Action):
    """Clear the bit the combat menu's QUICK sets, for everyone.

    The write is the roster block at `$8300 + slot * $20`, byte `+0x0C`, bit 7.
    The roster page is saved in `SAVEDGAME1`, so this bit reaches the disk:
    eight of the player's own save disks carry it set for one character and
    clear for the other seven.

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

    def __init__(self, flag: QuickfightFlag | None = None):
        self.flag = flag if flag is not None else QUICKFIGHT

    def legality(self, target) -> Verdict:
        if self.flag is None:
            return Verdict(False, WANTED)
        return super().legality(target)

    def run(self, target, **kwargs) -> Outcome:
        party = read_party(target)
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

    Deliberately a plain object with one method: the window already polls
    `$6E11` for the combat canvas, so this needs no timer of its own. Feed it
    the mode on every poll and it fires exactly on the 2-to-not-2 edge -- not
    on every tick afterwards, which would fight the player who turned
    quickfight on deliberately in the *next* fight.
    """

    def __init__(self, action: ClearQuickfight | None = None, enabled: bool = False):
        self.action = action or ClearQuickfight()
        self.enabled = enabled
        self.was: int | None = None

    def poll(self, target) -> Outcome | None:
        """One tick. Returns the outcome only on the tick that fires."""
        now = mode(target)
        was, self.was = self.was, now
        if not self.enabled or was != COMBAT or now == COMBAT or now is None:
            return None
        return self.action.apply(target)


# --- the set of them ---------------------------------------------------------


def actions(store: SpellStore | None = None) -> tuple[Action, ...]:
    """Every action, in the order `docs/102-live-actions.md` builds them.

    The window iterates this: one button per action, `label` on it,
    `description` and the reason from `legality` in its tooltip, and
    `confirm` asked first where it is non-empty.
    """
    store = store or SpellStore()
    return (HealParty(), IdentifyItems(), StoreSpells(store),
            RestoreSpells(store), ClearQuickfight(), LevelUp())
