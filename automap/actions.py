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
from por.geo import GRID as GEO_GRID
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


# --- warping between areas ---------------------------------------------------
#
# Debug mode only (`wish/debugmode.py`), and the one thing in this file that
# does more than poke a byte: it hands the CPU a new program counter.
#
# `docs/118-debug-mode.md` is the plan and the evidence. In short: an area exit
# is a script ending in `NEWECL`, whose handler at `DUNGEON $2011` writes five
# things and restarts the overlay. A warp is those writes made from outside,
# with the operand fetch -- which needs a script stream we are not in --
# skipped by entering the handler at its tail.
#
# **Nothing below has ever been run against the game.** The writes are copied
# from the handler; entering it at `$2034` from the key-wait loop is a guess,
# and so is what happens to the party afterwards.

#: Which `POOL` disk the arriving area lives on. `LIBRARY $43A4` reads it and
#: prompts if that disk is not in the drive.
WARP_DISK = 0x6E12
#: The live party square inside `GDRIVE00`, of which `$49C0`-`$49C2` is a
#: lagging copy: x, y, facing. `$1A3C`, called from `$2034`, copies these into
#: the save's own bytes, which is why the arrival square is written before the
#: jump and not after.
WARP_X, WARP_Y, WARP_FACING = 0xC04B, 0xC04C, 0xC04D
#: Where the party came *from*: `$2011`-`$2016` sets it, and the arriving
#: script's entry 4 compares it against its own id.
WARP_FROM = 0x49F2
#: The `ECL` slot of the loaded-files cache. Bit 7 means "reload me".
WARP_SLOT = 0x6E1B
#: Zeroed by `$202A`-`$2032`: the origin of the scratch/persistent split.
WARP_SCRATCH, WARP_SCRATCH_LEN = 0x4A00, 0x20
#: Non-zero indoors, zero on the overland map. Read, never written: it decides
#: whether `LOADFILES` asks for a `GEO` or a `SQRDATA`.
WARP_INDOORS = 0x49E6
#: The tail of `NEWECL`'s handler, past the operand fetch. `$203A` reloads the
#: stack pointer from `$03BF`, so the call depth we interrupt does not matter.
NEWECL_TAIL = 0x2034
#: `$6E11`: DUNGEON is the resident overlay. `$2034` is some other overlay's
#: code when it is not.
DUNGEON = 1
#: `DUNGEON`'s key-wait loop in the world, the one place it is safe to take the
#: PC from -- mid-script or mid-load the stack reset would discard work in
#: flight. `$10C2` is the loop; **the end of this window is a guess**, taken
#: from `$10EE`, the next address in `DUNGEON` anything has been read at. A
#: warp refused with a PC just past the window is this constant being wrong,
#: not the machine being busy.
KEY_WAIT = (0x10C2, 0x10EE)


def area_rows() -> tuple:
    """The area table, or nothing if this build has not got one.

    `por/areas.py` owns it. Imported here rather than at the top of the module
    so that a checkout without it still has the other five actions.
    """
    try:
        from por.areas import AREAS
    except ImportError:                     # pragma: no cover - defensive
        return ()
    return tuple(AREAS)


def walkable_square(geo) -> tuple[int, int, int] | None:
    """A square of this map with at least one passable edge, and a way to face.

    The fallback for the fifteen areas whose arrival square nobody has
    harvested. Carrying the party's *current* square over is the one option to
    avoid: the maps do not line up, and (13,13) in the Slums is a wall in Sokol
    Keep.
    """
    if geo is None:
        return None
    for y in range(GEO_GRID):
        for x in range(GEO_GRID):
            for facing in range(4):
                if geo.is_passable(x, y, facing):
                    return (x, y, facing)
    return None


@dataclass(frozen=True)
class Waypoint:
    """Where the party was before a warp, so that `Warp Back` has an answer."""

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
        writes.append((WARP_DISK, bytes([disk & 0xFF])))
    if arrival is not None:
        writes.append((WARP_X, bytes(int(v) & 0xFF for v in arrival)))
    writes.append((WARP_FROM, bytes([from_area & 0x7F])))
    writes.append((WARP_SLOT, bytes([(to_area & 0x7F) | 0x80])))
    writes.append((WARP_SCRATCH, bytes(WARP_SCRATCH_LEN)))
    return tuple(writes)


#: VICE's `e_PC`, taken on faith. See `program_counter`.
PC_REGISTER = 3


def program_counter(target):
    """The CPU's PC, or None where this backend cannot say.

    The `Target` contract is `read` and `write` and deliberately nothing else,
    so the CPU is reached the two ways there are: a target that offers `pc()`
    of its own (a test's, and whatever a second backend grows), or the VICE
    monitor a `ViceTarget` is holding.

    **The register id is not discoverable.** `CMD_REGISTERS_AVAILABLE` is
    unsupported in this VICE build, so `PC_REGISTER` is VICE's own `e_PC` taken
    on faith -- which is why the value is sanity-checked before anything is
    written to it: a 6502's other registers are eight bits wide, so an id that
    is not the PC cannot hold an address in `DUNGEON`.
    """
    own = getattr(target, "pc", None)
    if callable(own):
        return own()
    mon = getattr(target, "_mon", None)
    if mon is None:
        return None
    try:
        regs = mon.registers()
    except Exception:
        return None
    finally:
        try:
            mon.resume()
        except Exception:
            pass
    return regs.get(PC_REGISTER)


def jump(target, address: int) -> bool:
    """Set the PC and let the machine run. False if this backend cannot.

    The last step of a warp and the only irreversible one: everything before it
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
        mon.set_registers({PC_REGISTER: address})
    except Exception:
        return False
    finally:
        try:
            mon.resume()
        except Exception:
            pass
    return True


class Warp(Action):
    """Put the party in another area, the way the game's own exits do.

    **Unproven.** The writes are `NEWECL`'s (`docs/118-debug-mode.md`), but
    nothing has yet entered its handler from outside, and the first thing to
    try it may find that the key-wait loop is the wrong place to do it from.
    Treat a refusal as information and a crash as the answer to open question 1
    in that document.

    Two guards that are not optional, both re-checked at `apply` time:

    * **`$6E11` must be 1.** `$2034` is some other overlay's code otherwise,
      and jumping there is an immediate crash.
    * **the PC must be in `DUNGEON`'s key-wait loop.** Mid-script or mid-load
      the stack reload at `$203A` throws away work in flight. This doubles as
      the check that `PC_REGISTER` is the register we think it is.

    What it cannot guard: the quest flags. A warp is not the same as having
    played there, the arriving script assumes things the party never did, and
    the honest answer is to say so rather than to pretend otherwise.
    """

    name = "warp"
    label = "Warp To"
    description = ("enter another area the way the game's own exits do -- "
                   "unproven, and it writes to the running machine")
    combat_legal = False
    confirm = ("Warp writes five things into the running game and then hands "
               "the CPU a new program counter.\n\nNothing has ever tried this: "
               "it may crash the game, and the arriving area's script will "
               "assume quest flags the party never set. Use a copy of your "
               "save disk, never the original.\n\nWarp anyway?")

    def __init__(self):
        #: Where the last warp came from. `Warp Back` reads it; None until a
        #: warp has been made, which is why the button starts disabled.
        self.back: Waypoint | None = None

    # -- reading the machine ---------------------------------------------

    @staticmethod
    def current_area(target) -> int | None:
        """The id of the area running now: `$6E1B` without the reload bit."""
        try:
            raw = target.read(WARP_SLOT, 1)
        except Exception:
            return None
        return raw[0] & 0x7F if raw else None

    @staticmethod
    def current_disk(target) -> int | None:
        try:
            raw = target.read(WARP_DISK, 1)
        except Exception:
            return None
        return raw[0] if raw else None

    @staticmethod
    def current_square(target) -> tuple[int, int, int] | None:
        try:
            raw = target.read(WARP_X, 3)
        except Exception:
            return None
        return (raw[0], raw[1], raw[2]) if len(raw) == 3 else None

    def disk_note(self, target, area) -> str:
        """What to say about disks before warping.

        **Which image is actually in drive 8 is not readable** -- the monitor
        does not say and `automap/vice.py` has no attach command -- so this
        reports what the *game* last asked for and leaves the drive to the
        person at the keyboard.
        """
        if area is None:
            return ""
        want = getattr(area, "disk", None)
        if want is None:
            return ""
        now = self.current_disk(target) if target is not None else None
        if now is None:
            return f"needs POOL{want} in drive 8"
        if now == want:
            return f"needs POOL{want}, which is what the game last asked for"
        return (f"needs POOL{want}; the game last asked for POOL{now} "
                "($6E12) -- swap the disk first or the loader will stop and "
                "ask")

    # -- may we -----------------------------------------------------------

    def legality(self, target, area=None) -> Verdict:
        base = super().legality(target)
        if not base:
            return base
        if mode(target) != DUNGEON:
            return Verdict(False, "$6E11 is not 1, so DUNGEON is not the "
                                  "resident overlay and $2034 is not NEWECL")
        pc = program_counter(target)
        if pc is None:
            return Verdict(False, "this backend cannot read the CPU, and a "
                                  "warp has to set the program counter")
        lo, hi = KEY_WAIT
        if not lo <= pc < hi:
            return Verdict(False, f"the PC is ${pc:04X}, outside DUNGEON's "
                                  f"key-wait loop (${lo:04X}-${hi - 1:04X}): "
                                  f"the game is busy, or that window is wrong")
        if area is None:
            return Verdict(False, "choose an area")
        here = self.current_area(target)
        if here is not None and here == getattr(area, "id", None):
            return Verdict(False, "the party is already in that area, and "
                                  "NEWECL skips a same-area transition")
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
        return Outcome(True, f"warped to {name} - watch for the drive light",
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
        """Everything true about this warp that the caller should know first."""
        out = ["the arriving script assumes quest flags the party never set; a "
               "warp is not the same as having played there"]
        if arrival is None:
            out.append("no arrival square is known for this area, so the party "
                       "lands wherever the arriving script leaves it")
        if not getattr(area, "has_map", True):
            out.append(f"{getattr(area, 'ecl', 'this area')} loads no map of "
                       "its own")
        if getattr(area, "outdoors", False):
            out.append("this is an overland area and loads a SQRDATA rather "
                       "than a GEO; nothing here has been tried outdoors")
        try:
            indoors = target.read(WARP_INDOORS, 1)[0]
        except Exception:
            indoors = None
        if indoors is not None:
            outdoors_now = indoors == 0
            if outdoors_now != bool(getattr(area, "outdoors", False)):
                out.append(f"$49E6 is {indoors}, so LOADFILES will ask for a "
                           f"{'SQRDATA' if outdoors_now else 'GEO'}")
        return tuple(out)

    # -- and back again ---------------------------------------------------

    def back_verdict(self, target) -> Verdict:
        if self.back is None:
            return Verdict(False, "nothing to go back to: no warp has been "
                                  "made this session")
        area = area_by_id(self.back.area)
        return self.legality(target, area or self.back)

    def apply_back(self, target) -> Outcome:
        """Warp to where the last warp started, on the square it started on."""
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
        return Outcome(True, f"warped back to area {was.area}", writes)


def area_by_id(id: int):
    """One row of the area table, or None."""
    for row in area_rows():
        if getattr(row, "id", None) == id:
            return row
    return None
