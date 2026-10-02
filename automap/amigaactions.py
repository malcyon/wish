"""The Action buttons on an Amiga title: the C64 actions, aimed at heap records.

Each class subclasses its C64 twin in `automap/actions.py`, so the name, label,
description, confirmation and every outcome sentence are the approved ones. What
changes is where the bytes are: `automap/amigaparty.py` finds the party's heap
records and the title's row says which field each action writes.

**No Amiga title gets a C64 address.** The classes never read `Action.game`, and
`game` is None on them: `actions.Action` turns None into Pool of Radiance's C64
container, which is the wrong answer for Pools of Darkness (it has no C64 title)
and for every other Amiga title.

`amigaparty` is imported when it is first needed, and its absence reads as an
unbuilt title, so this module can be used before that one exists. Names taken
from its row (`PartyRow`): `confirmed` and `combat_legal` (sets of action names),
`combat_value`, and the field spots `hp`, `memorised`, `quickfight` and
`hidden` (each `offset`, `length`, `mask`, or None). The party is iterable and
its members are `AmigaMember`.
"""

from __future__ import annotations

import importlib

from . import actions as engine

#: Shown while a title, a backend or an action is not built. Today's tooltip
#: text, which stays until the sentence is chosen.
NOT_BUILT = "no emulator attached"

#: Spell lists are stored under this prefix plus the `amiga.MACHINES` key, so a
#: list saved on the C64 is never restored into an Amiga record.
STORE_PREFIX = "amiga/"


def _parties():
    """`automap.amigaparty`, or None while it is not in the tree."""
    try:
        return importlib.import_module("automap.amigaparty")
    except ModuleNotFoundError as exc:
        if exc.name != "automap.amigaparty":
            raise
        return None


def _row(target):
    parties = _parties()
    if parties is None or target is None:
        return None
    return parties.row_for(_unwrap(target))


def _unwrap(target):
    return getattr(target, "target", target)


class _AmigaAction:
    """What the five actions share. Placed before the C64 class in the MRO."""

    def __init__(self, key: str, store: engine.SpellStore | None = None):
        self.key = key
        self.store = store
        self.game = None
        self.flag = None

    @property
    def store_key(self) -> str:
        return STORE_PREFIX + self.key

    @property
    def descriptor(self):
        raise AttributeError("an Amiga action has no C64 container")

    @property
    def combat_legal(self) -> bool:
        # Per title, from the row; `legality` consults the row directly.
        return False

    def legality(self, target) -> engine.Verdict:
        if target is None:
            return engine.Verdict(False, NOT_BUILT)
        parties = _parties()
        row = _row(target)
        if row is None or self.name not in row.confirmed:
            return engine.Verdict(False, NOT_BUILT)
        if (self.name != "store-spells"
                and not getattr(_unwrap(target), "can_write", False)):
            return engine.Verdict(False, NOT_BUILT)
        state = parties.mode(target)
        if state is None:
            return engine.Verdict(False, "the machine is not readable right now")
        if state == row.combat_value and self.name not in row.combat_legal:
            return engine.Verdict(False, f"{self.label} is refused during a fight")
        return engine.Verdict(True)

    def _party(self, target):
        parties = _parties()
        return None if parties is None else parties.read_party(_unwrap(target))

    def _spot(self, target, field: str):
        row = _row(target)
        return None if row is None else getattr(row, field, None)


class AmigaHealParty(_AmigaAction, engine.HealParty):
    """Current hit points to maximum for everyone standing."""

    def run(self, target, **kwargs) -> engine.Outcome:
        party = self._party(target)
        spot = self._spot(target, "hp")
        if party is None or spot is None:
            return engine.Outcome(False, "no party to heal")
        writes, notes, healed = [], [], []
        ceiling = (1 << (8 * spot.length)) - 1
        for m in party:
            if m.hp == 0:
                notes.append(f"{m.name} is at 0 and was left alone: dead or "
                             f"dying is not a hit point count")
                continue
            goal = min(m.hp_max, ceiling)
            if m.hp_max > ceiling:
                notes.append(f"{m.name} has {m.hp_max} maximum hit points and "
                             f"the roster byte holds {ceiling}")
            if m.hp >= goal:
                continue
            writes.append((m.address + spot.offset,
                           goal.to_bytes(spot.length, "big")))
            healed.append(m.name)
        engine._write_all(target, writes)
        if not writes:
            return engine.Outcome(True, "All party members are at full health.",
                                  (), tuple(notes))
        return engine.Outcome(True, f"Healed {', '.join(healed)} up to full.",
                              tuple(writes), tuple(notes))


class AmigaStoreSpells(_AmigaAction, engine.StoreSpells):
    """Remember each character's raw memorised span, reading only."""

    def run(self, target, disk: str = "", **kwargs) -> engine.Outcome:
        party = self._party(target)
        if party is None:
            return engine.Outcome(False, "no party to read")
        for m in party:
            self.store.put(self.store_key, m.name, m.memorised())
        return engine.Outcome(True, "Saved spell state.")


class AmigaRestoreSpells(_AmigaAction, engine.RestoreSpells):
    """Write the stored raw span back where this title keeps it."""

    def run(self, target, disk: str = "", **kwargs) -> engine.Outcome:
        party = self._party(target)
        spot = self._spot(target, "memorised")
        if party is None or spot is None:
            return engine.Outcome(False, "no party to restore")
        writes, notes = [], []
        for m in party:
            raw = self.store.get(self.store_key, m.name)
            if raw is None:
                notes.append(f"nothing stored for {m.name}")
                continue
            if len(raw) > spot.length:
                notes.append(f"the stored list for {m.name} is {len(raw)} "
                             f"bytes, more than the {spot.length} this title's "
                             f"record holds")
                continue
            if raw == m.memorised()[:len(raw)]:
                continue
            writes.append((m.address + spot.offset, raw))
        engine._write_all(target, writes)
        if not writes:
            return engine.Outcome(True, "Spellcasters have already memorized "
                                        "their spells.", (), tuple(notes))
        return engine.Outcome(True, "Restored spell state.", tuple(writes),
                              tuple(notes))


class AmigaIdentifyItems(_AmigaAction, engine.IdentifyItems):
    """Clear the hidden-name bits on every item node, and no other bit."""

    def run(self, target, **kwargs) -> engine.Outcome:
        party = self._party(target)
        spot = self._spot(target, "hidden")
        if party is None or spot is None:
            return engine.Outcome(False, "no party to read")
        writes = []
        for m in party:
            for address, node in m.items():
                flags = node[spot.offset]
                if flags & spot.mask:
                    writes.append((address + spot.offset,
                                   bytes([flags & ~spot.mask & 0xFF])))
        engine._write_all(target, writes)
        if not writes:
            return engine.Outcome(True, "No items to identify.")
        return engine.Outcome(True, f"Identified {len(writes)} item"
                                    f"{'s' if len(writes) != 1 else ''}.",
                              tuple(writes))


class AmigaClearQuickfight(_AmigaAction, engine.ClearQuickfight):
    """Clear the quickfight bit on every member."""

    def run(self, target, **kwargs) -> engine.Outcome:
        party = self._party(target)
        spot = self._spot(target, "quickfight")
        if party is None or spot is None:
            return engine.Outcome(False, "no party to read")
        writes = []
        for m in party:
            if m.quickfight:
                addr = m.address + spot.offset
                current = target.read(addr, 1)[0]
                writes.append((addr, bytes([current & ~spot.mask & 0xFF])))
        engine._write_all(target, writes)
        if not writes:
            return engine.Outcome(True, "No party member had quickfight enabled.")
        return engine.Outcome(True, f"Removed quickfight from {len(writes)} "
                                    f"character{'s' if len(writes) != 1 else ''}.",
                              tuple(writes))


class AmigaQuickfightWatcher(engine.QuickfightWatcher):
    """Fire on the tick combat ends, reading the mode from `amigaparty`."""

    def __init__(self, action: AmigaClearQuickfight, enabled: bool = False):
        self.action = action
        self.enabled = enabled
        self.was: int | None = None

    @property
    def game(self):
        return None

    def poll(self, target) -> engine.Outcome | None:
        parties = _parties()
        row = _row(target)
        now = None if parties is None or row is None else parties.mode(target)
        was, self.was = self.was, now
        combat = None if row is None else row.combat_value
        if not self.enabled or was != combat or now == combat or now is None:
            return None
        return self.action.apply(target)


def actions(store: engine.SpellStore | None, key: str) -> tuple:
    """The five Amiga actions for one `amiga.MACHINES` key, in the C64 order."""
    store = store or engine.SpellStore()
    return (AmigaHealParty(key), AmigaStoreSpells(key, store),
            AmigaRestoreSpells(key, store), AmigaIdentifyItems(key),
            AmigaClearQuickfight(key))
