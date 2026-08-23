"""The C64 codec: a neutral character becomes a 580-byte C64 record.

The writing half of the pair `por/neutral.py` describes.  It knows the C64
record and nothing else: which neutral field goes to which entry of
`por/layout.py`, what the C64 stores that no source supplies, and what the
C64 has no room for.  Where a value came from is the reader's business and
reaches this module only as the phrase :class:`por.neutral.Value` carries.

Every byte of the output is justified -- it came from a neutral value, or it
was computed from one by a named rule, or it is a documented constant --
which is what :attr:`Report.unaccounted` asserts.

Evidence for the fields themselves is in `por/layout.py`; for the conversion,
`docs/117-save-conversion.md`.
"""

from __future__ import annotations

import dataclasses

from . import neutral, spells
from .layout import RECORD_SIZE, Field
from .neutral import NeutralCharacter
from .record import CharacterRecord

__all__ = [
    "Report",
    "DIRECT",
    "INFRAVISION",
    "LEVEL_FIELDS",
    "strength_index",
    "write",
]


@dataclasses.dataclass
class Report(neutral.Report):
    """A C64 conversion's provenance: **every** byte has to be explained.

    Not merely the non-zero ones.  A zero the C64 record wants is as much a
    decision as a value copied into it, and `docs/117-save-conversion.md`
    makes accounting for all 580 the test that replaces a round trip.
    """

    total: int = RECORD_SIZE

    @property
    def unaccounted(self) -> list[int]:
        """C64 offsets this conversion cannot explain. Should be empty."""
        return [i for i in range(self.total) if i not in self.sources]

    def summary_notes(self) -> list[str]:
        if self.unaccounted:
            return [f"  UNACCOUNTED: {len(self.unaccounted)} bytes"]
        return []


#: Neutral field -> the C64 field it becomes, where the value crosses
#: unchanged.  The names differ in only two places, and both times because
#: the C64 name is a storage detail: `thac0` and `roster_movement` are what
#: the roster block calls the current THAC0 and the current movement rate.
DIRECT: tuple[tuple[str, str], ...] = (
    ("strength", "strength"),
    ("intelligence", "intelligence"),
    ("wisdom", "wisdom"),
    ("dexterity", "dexterity"),
    ("constitution", "constitution"),
    ("charisma", "charisma"),
    ("exceptional_strength", "exceptional_strength"),
    ("thac0_base", "thac0_base"),
    ("race", "race"),
    ("char_class", "char_class"),
    ("age", "age"),
    ("hp_max", "hp_max"),
    ("attack_level", "attack_level"),
    ("save_paralysis", "save_paralysis"),
    ("save_petrification", "save_petrification"),
    ("save_wands", "save_wands"),
    ("save_breath", "save_breath"),
    ("save_spell", "save_spell"),
    ("movement", "movement"),
    ("level", "level"),
    ("levels_drained", "levels_drained"),
    ("hp_lost_to_drain", "hp_lost_to_drain"),
    ("thief_pick_pockets", "thief_pick_pockets"),
    ("thief_open_locks", "thief_open_locks"),
    ("thief_find_traps", "thief_find_traps"),
    ("thief_move_silently", "thief_move_silently"),
    ("thief_hide_in_shadows", "thief_hide_in_shadows"),
    ("thief_hear_noise", "thief_hear_noise"),
    ("thief_climb_walls", "thief_climb_walls"),
    ("thief_read_languages", "thief_read_languages"),
    ("copper", "copper"),
    ("silver", "silver"),
    ("electrum", "electrum"),
    ("gold", "gold"),
    ("platinum", "platinum"),
    ("gems", "gems"),
    ("jewelry", "jewelry"),
    ("sex", "sex"),
    ("alignment", "alignment"),
    ("armour_class_base", "armour_class_base"),
    ("experience", "experience"),
    ("class_bits", "class_bits"),
    ("hp_rolled", "hp_rolled"),
    ("party_order", "party_order"),
    ("hp_current", "hp_current"),
    ("thac0_current", "thac0"),
    ("armour_class", "armour_class"),
    ("movement_current", "roster_movement"),
)

#: Class name -> the C64 field holding that class's level.  The C64 indexes
#: its eight slots by the class *bit*; a class with no bit has no slot, and a
#: level for one is reported rather than written somewhere plausible.
LEVEL_FIELDS: dict[str, str] = {
    "magic-user": "level_magic_user", "cleric": "level_cleric",
    "thief": "level_thief", "fighter": "level_fighter",
    "knight": "level_knight", "paladin": "level_paladin",
    "ranger": "level_ranger",
}

#: The order the level slots are reported in: the C64's own, bit by bit.
_LEVEL_ORDER = ("level_magic_user", "level_cleric", "level_thief",
                "level_fighter", "level_knight", "level_paladin",
                "level_ranger")

#: Race code -> infravision range in feet.  The C64 stores this at `0x0D5`
#: and it is a property of the race, not of any save: DOS does not store it,
#: the Amiga derives what it needs, so the C64 writer computes it.  6 for
#: every dwarf, elf and half-elf and 0 for every human across the twelve C64
#: specimens that carry it; gnome, halfling and half-orc are PROBABLE, on
#: AD&D 1st edition giving all three the same 60 feet.
INFRAVISION = {0: 0, 1: 6, 2: 6, 3: 6, 4: 6, 5: 6, 6: 6, 7: 0}

#: How many item slots the C64 record has.
ITEM_SLOTS = 16
ITEM_SIZE = 16


def strength_index(strength: int, percentile: int) -> int:
    """The C64's `strength_index`: STR below 18, else 18 plus the band.

    Equals strength below 18; 18/01-18/50 give 19 and 20, 18/80 and 18/81 give
    21, 18/98 gives 22 -- the AD&D exceptional-strength bands collapsed to one
    number.  PROBABLE, and it is computed rather than copied because no source
    port has been found to store it.
    """
    if strength != 18 or not percentile:
        return strength
    for bound, value in ((50, 19), (75, 20), (90, 21), (99, 22)):
        if percentile <= bound:
            return value
    return 23


def _clamp_nibble(n: int) -> int:
    return min(int(n), 0x0F)


def _field(name: str) -> Field:
    from . import layout as _l
    return _l.FIELDS_BY_NAME[name]


def _layout():
    from . import layout as _l
    return _l.LAYOUT


def write(char: NeutralCharacter, icon: bytes | None = None,
          ) -> tuple[CharacterRecord, Report]:
    """Build a 580-byte C64 character record from a neutral one.

    `icon` is the 36-byte combat icon.  No port outside the C64 has one -- it
    is a C64 character set -- so with none given the field is left zero and
    reported.
    """
    rec = CharacterRecord.blank()
    rep = Report()
    port = char.port
    taken: list[str] = []

    def use(name: str) -> neutral.Value | None:
        """The value, if the reader stands behind it. A field graded UNKNOWN
        comes back as nothing to write and something to report."""
        taken.append(name)
        v = char.take(name)
        if v is None and name in char:
            rep.dropped.append(
                f"{port} {name}: read at {char.value(name).confidence}, "
                f"which is not a grade this conversion will write")
        return v

    def emit(v: neutral.Value, destination: str, offset: int, size: int,
             extra: str = "") -> None:
        rep.note(offset, size, v.line(destination, extra))
        rep.dropped.extend(v.dropped)

    # -- the name: 20 NUL-padded bytes ---------------------------------------
    name = use("name")
    if name is not None:
        rec.set("name", name.value)
        emit(name, "name", 0x000, 20)

    for field, c64_name in DIRECT:
        v = use(field)
        if v is None:
            continue
        dst = _field(c64_name)
        rec.set(c64_name, v.value)
        emit(v, c64_name, dst.offset, dst.size)

    # -- the second ability array -------------------------------------------
    # Seven zeroes in every Pool of Radiance specimen, and Curse's importer
    # writes both halves of every (base, current) pair. Zero is what a Pool of
    # Radiance C64 record holds, so zero is what we write.
    rep.note(0x065, 7, "abilities_second: zero, as in every C64 Pool of "
                       "Radiance specimen")

    # -- the spellbook: 56 bits, ids 1-55 ------------------------------------
    known = use("spells_known")
    if known is not None:
        carried = [i for i in known.value if i <= spells.LAST_SPELLBOOK_SPELL]
        rec.set("spells_known", spells.spellbook_bytes(carried))
        emit(known, "spells_known", 0x078, 7,
             " packed to one bit; ids are identical")
        for i in known.value:
            if i > spells.LAST_SPELLBOOK_SPELL:
                rep.warnings.append(
                    f"spell id {i} is set in the {port} spellbook and the "
                    f"C64's seven-byte mask has no bit for it (56 bits hold "
                    f"ids 0-55 and id 0 does not exist); id 56 is RESTORATION")

    # -- memorised spells: sixteen slots, filled from the start --------------
    memorised = use("spells_memorised")
    if memorised is not None:
        mem = list(memorised.value)[:16]
        rec.set_raw("spells_memorised", bytes(mem) + bytes(16 - len(mem)))
        emit(memorised, "spells_memorised", 0x020, 16,
             f" ({port} fills its slots from the end; the C64 from the start)")

    # -- the per-class level array: indexed by the class bit -----------------
    levels = use("levels")
    if levels is not None:
        for name_, level in levels.value.items():
            field = LEVEL_FIELDS.get(name_)
            if field is None:
                if level:
                    rep.warnings.append(
                        f"{port} carries {name_} level {level}, and the C64's "
                        f"eight-slot array has no {name_} slot")
                continue
            rec.set(field, level)
        for f in _LEVEL_ORDER:
            dst = _field(f)
            emit(levels, f, dst.offset, dst.size)
    rep.note(0x0CE, 1, "the C64's unused sixth level slot: zero")

    # -- spell slots: three packed nibbles, cleric high, magic-user low ------
    castable = use("spells_castable")
    if castable is not None:
        cleric = castable.value.get("cleric", (0, 0, 0))
        mage = castable.value.get("magic-user", (0, 0, 0))
        packed = bytes((_clamp_nibble(cleric[i]) << 4) | _clamp_nibble(mage[i])
                       for i in range(3)) + bytes(3)
        rec.set_raw("spells_castable", packed)
        emit(castable, "spells_castable", 0x0EE, 6,
             ", repacked cleric-high/magic-user-low")

    # -- size ----------------------------------------------------------------
    size = use("size_small")
    if size is not None:
        rec.set("size_small", size.value)
        emit(size, "size_small", 0x099, 1)

    # -- turning: the C64 has two bytes --------------------------------------
    rep.note(0x0A3, 1, "turn_class: zero -- no player character is undead")
    turning = use("turn_power")
    if turning is not None:
        rec.set("turn_power", turning.value)
        emit(turning, "turn_power", 0x0A4, 1,
             " (PROBABLE: which of the C64's two turning bytes this is cannot "
             "be told from a party with no turning cleric above level 3)")

    # -- attack forms: eight bytes -------------------------------------------
    forms = use("attack_forms")
    if forms is not None:
        rec.set_raw("attack_forms", bytes(forms.value))
        emit(forms, "attack_forms", 0x0D9, 8)

    # -- computed, not copied ------------------------------------------------
    rec.set("infravision", INFRAVISION.get(char.get("race", 0), 0))
    rep.note(0x0D5, 1,
             f"infravision: computed from race; {port} does not store it")
    rec.set("strength_index", strength_index(char.get("strength", 0),
                                             char.get("exceptional_strength",
                                                      0)))
    rep.note(0x0E2, 1, f"strength_index: computed from strength and the "
                       f"percentile; the {port} byte at the aligned offset is "
                       f"a different field")

    # -- innate effects: ten slots -------------------------------------------
    innate = use("innate_effects")
    if innate is not None:
        ids = list(innate.value)[:10]
        rec.set_raw("item_effects", bytes(ids) + bytes(10 - len(ids)))
        emit(innate, "item_effects", 0x0AD, 10)

    # -- the inventory: sixteen fixed slots ----------------------------------
    inventory = use("inventory")
    if inventory is not None:
        carried = list(inventory.value)
        inv = bytearray(ITEM_SLOTS * ITEM_SIZE)
        for n, item in enumerate(carried[:ITEM_SLOTS]):
            inv[n * ITEM_SIZE:(n + 1) * ITEM_SIZE] = item
        rec.set_raw("inventory", bytes(inv))
        emit(inventory, "inventory", 0x120, 256)
        if len(carried) > ITEM_SLOTS:
            rep.warnings.append(
                f"{len(carried)} items and the C64 has sixteen slots; "
                f"{len(carried) - ITEM_SLOTS} dropped from the end")

    # -- the combat icon: only the C64 has one -------------------------------
    if icon is not None:
        rec.set_raw("region_220", bytes(icon))
        rep.note(0x220, 36, "combat icon: supplied")
    else:
        rep.note(0x220, 36, f"combat icon: zero. {port} has no C64 charset "
                            f"icon; por/iconparts.py can compose a legal one")
        rep.dropped.append("the combat icon: C64 icons are 18 CHARPIC00 "
                           "screen codes plus 18 colours and "
                           f"{port} has no equivalent")

    # -- fields with no source, written as documented constants --------------
    rep.note(0x0B8, 1, "flags_0b8: zero -- a player character, bit 7 clear")
    rep.note(0x0FE, 2, f"portrait_head/body: zero. HEADnn/BODYnn name C64 "
                       f"disk files; the {port} art is a different set")
    rep.dropped.append(f"portrait ids: the {port} art has different numbering")
    rep.note(0x100, 1, "roster status: 1 (OK)")
    rec.set("roster_in_use", 1)
    tail = use("roster_tail")
    if tail is not None:
        rec.set_raw("roster_tail", bytes(tail.value))
        emit(tail, "roster_tail", 0x110, 9)

    # -- what this writer took nothing from ----------------------------------
    for name in char.unwritten(taken):
        rep.dropped.append(
            f"{name}: the neutral record carries it and the C64 conversion "
            f"takes nothing from it")

    # -- what the reader itself could not carry ------------------------------
    rep.dropped.extend(char.dropped)
    rep.warnings.extend(char.warnings)

    # Everything still unnamed is a byte the C64 record does not use: the
    # unknown gaps of por/layout.py, which are zero in every specimen we hold.
    for f in _layout():
        for i in range(f.offset, f.end):
            rep.sources.setdefault(
                i, f"{f.name}: zero (UNKNOWN on the C64 side and zero in "
                   f"every specimen)" if not f.is_known
                   else f"{f.name}: zero (no {port} source)")
    return rec, rep
