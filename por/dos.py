"""Read a DOS Pool of Radiance save, and turn one into a C64 one.

**One direction only.** `wish` never writes a DOS file: the DOS side of this
module is read-only, so the DOS format has to be decoded only as far as
sourcing what the C64 needs, and any DOS field with no C64 counterpart can be
dropped -- provided it is *reported* rather than dropped silently, which is
what `Report` is for.

    DOS character file  ->  decode  ->  named fields  ->  encode  ->  C64 record

No new interchange format is invented: the middle is `por/yaml_io.py`'s, the
one the editor already uses.  `por/dos_layout.py` is the field table, in the
same declarative style as `por/layout.py` and with a confidence on every
entry.

What the conversion promises
----------------------------
* the DOS files are opened read-only and never written;
* **every byte of the C64 record is justified** -- it came from the DOS save,
  or it was computed from it by a named rule, or it is a documented constant.
  `Report.sources` says which, for every offset;
* every DOS field with no C64 home is named in `Report.dropped`;
* the encumbrance identity balances, and `Report` says when it does not.

The three places the formats diverge in kind
--------------------------------------------
* **The spellbook.** DOS spends one byte per spell across `0x033`-`0x06A`;
  the C64 packs 56 bits at `0x078`.  The *ordering* turns out to be identical
  -- DOS byte *n* is spell id *n + 1*, the same id `por/spells.py` uses -- so
  the transpose is a pack and not a permutation.  See `dos_layout.spellbook`.
  Spell 56, `RESTORATION`, is the one id with no C64 bit and is reported.
* **The per-class level array.** Eight wide on both.  DOS indexes by the class
  *number*, the C64 by the class *bit*; `CLASS_LEVEL_SLOTS` is the
  permutation, and druid and monk have no C64 slot at all.
* **The items.** Past its cached display line the 63-byte DOS record *is* the
  C64's sixteen bytes, one field to a byte -- `item_to_c64` is the projection,
  and it reproduces 157 of the 163 distinct C64 item records byte for byte.

Evidence: `work/reports/dos-saves.md`, `work/reports/dos-items.md`,
`docs/117-save-conversion.md`.  Assertions: `tests/test_dosconvert.py`.
"""

from __future__ import annotations

import dataclasses
import pathlib
import struct
from typing import Any, Sequence

from . import spells, traits
from .dos_layout import (
    EFFECT_SIZE,
    FIELDS_BY_NAME,
    ITEM_FIELDS_BY_NAME,
    ITEM_SIZE,
    RECORD_SIZE,
)
from .layout import RECORD_SIZE as C64_RECORD_SIZE
from .layout import Field, Kind
from .record import CharacterRecord

__all__ = [
    "DosRecordError",
    "DosCharacter",
    "DosItem",
    "Report",
    "item_to_c64",
    "read_character",
    "read_party",
    "slots_available",
    "to_c64_record",
    "export_party",
    "savgam_word",
    "quest_flags",
    "position",
    "area_id",
    "area_file",
    "apply_position",
    "apply_quest_flags",
]


class DosRecordError(ValueError):
    """A file that is not a DOS Pool of Radiance record."""


# ---------------------------------------------------------------------------
# Decoding one record
# ---------------------------------------------------------------------------
def _decode(f: Field, raw: bytes) -> Any:
    if f.kind is Kind.U8:
        return raw[0]
    if f.kind is Kind.I8:
        return raw[0] - 256 if raw[0] > 127 else raw[0]
    if f.kind in (Kind.U16LE, Kind.UINT_LE):
        return int.from_bytes(raw, "little")
    return bytes(raw)


class _Fielded:
    """Read-only field access driven by a layout table."""

    _TABLE: dict[str, Field] = {}

    def __init__(self, data: bytes, size: int, what: str) -> None:
        if len(data) != size:
            raise DosRecordError(
                f"a DOS {what} is {size} bytes; got {len(data)}")
        self._data = bytes(data)

    def to_bytes(self) -> bytes:
        """The record exactly as it was read. Nothing here ever rewrites it."""
        return self._data

    def __bytes__(self) -> bytes:
        return self._data

    def __len__(self) -> int:
        return len(self._data)

    def get(self, name: str) -> Any:
        f = self._TABLE[name]
        return _decode(f, self._data[f.span])

    def raw(self, name: str) -> bytes:
        return self._data[self._TABLE[name].span]

    def __getattr__(self, name: str) -> Any:
        table = type(self)._TABLE
        if name in table:
            return self.get(name)
        raise AttributeError(name)


class DosItem(_Fielded):
    """One 63-byte record of a `.ITM` file."""

    _TABLE = ITEM_FIELDS_BY_NAME

    def __init__(self, data: bytes) -> None:
        super().__init__(data, ITEM_SIZE, "item")

    @property
    def display_line(self) -> str:
        """The cached line the game last drew. **Never a source** -- it goes
        stale, and one specimen reads `11 Darts` over a quantity of 8."""
        n = min(self._data[0], ITEM_FIELDS_BY_NAME["text"].size)
        return self._data[1:1 + n].decode("ascii", "replace")

    def to_c64(self) -> bytes:
        """This item as the C64's sixteen bytes."""
        return item_to_c64(self._data)


def item_to_c64(record: bytes) -> bytes:
    """Project one 63-byte DOS item onto the C64's sixteen bytes.

    Not a guess at a conversion: it *is* the evidence.  Applied to every item
    in the eight `ITEM*.DAX` files it reproduces **157 of the 163 distinct
    item records on the C64 game disks byte for byte**, which is what fixes
    every offset -- including that readied and the hidden-name mask share the
    C64's byte +6 where DOS spends a byte on each, and that cursed is bit 7 of
    +7.  The six that do not match are items the two ports hand out in
    different places, not near misses.  `work/reports/dos-items.md`.
    """
    if len(record) != ITEM_SIZE:
        raise DosRecordError(f"a DOS item is {ITEM_SIZE} bytes; got {len(record)}")
    at = {n: ITEM_FIELDS_BY_NAME[n].offset for n in
          ("type_index", "name1", "name2", "name3", "plus", "plus_save",
           "readied", "hidden", "cursed", "weight", "quantity", "value",
           "charges", "effect", "power")}
    r = record
    return bytes((
        r[at["type_index"]], r[at["name1"]], r[at["name2"]], r[at["name3"]],
        r[at["plus"]], r[at["plus_save"]],
        (0x80 if r[at["readied"]] else 0) | (r[at["hidden"]] & 0x07),
        0x80 if r[at["cursed"]] else 0,
        r[at["weight"]], r[at["weight"] + 1],
        r[at["quantity"]],
        r[at["value"]], r[at["value"] + 1],
        r[at["charges"]], r[at["effect"]], r[at["power"]],
    ))


#: Effect ids that are innate rather than temporary, and so belong in the
#: C64's ten trait slots at `0x0AD` rather than being dropped with the running
#: spells.  Seven of them are **Curse of the Azure Bonds' own filter**: its
#: importer reads a Pool of Radiance `.spc` file and keeps exactly 18, 26, 47,
#: 48, 97, 107 and 124, every one a racial or constitutional bonus.  90 is
#: added here because the DOS party carries it on the dwarf and on the
#: halfling and `por/traits.py` names it the same kind of thing -- a racial
#: constitution bonus to poison and death saves.  PROBABLE.
INNATE_EFFECTS = frozenset({18, 26, 47, 48, 90, 97, 107, 124})

#: DOS class number -> the C64 record field holding that class's level.  DOS
#: indexes its eight slots by the class *number* and the C64 by the class
#: *bit*, so this is the permutation between them.  Druid and monk have no C64
#: slot: the game names both classes and instantiates neither.
CLASS_LEVEL_SLOTS: tuple[tuple[int, str, str | None], ...] = (
    (0, "cleric", "level_cleric"),
    (1, "druid", None),
    (2, "fighter", "level_fighter"),
    (3, "paladin", "level_paladin"),
    (4, "ranger", "level_ranger"),
    (5, "magic-user", "level_magic_user"),
    (6, "thief", "level_thief"),
    (7, "monk", None),
)

#: Race code -> infravision range in feet.  The C64 stores this at `0x0D5` and
#: **DOS does not store it at all** -- there is no byte at the aligned offset
#: and the Curse importer sources it from nothing either, because it is a
#: property of the race.  Computed rather than copied, and reported as such.
#: 6 for every dwarf, elf and half-elf and 0 for every human across the twelve
#: C64 specimens that carry it; gnome, halfling and half-orc are PROBABLE, on
#: AD&D 1st edition giving all three the same 60 feet.
INFRAVISION = {0: 0, 1: 6, 2: 6, 3: 6, 4: 6, 5: 6, 6: 6, 7: 0}


class DosCharacter(_Fielded):
    """One 285-byte DOS Pool of Radiance character, saved or exported.

    A save slot and a `.CHA` export are the same record in the same order;
    the only systematic difference is that an export zeroes the item count,
    so one reader serves both.
    """

    _TABLE = FIELDS_BY_NAME

    def __init__(self, data: bytes, items: Sequence[DosItem] = (),
                 effects: Sequence[bytes] = (), source: str | None = None):
        super().__init__(data, RECORD_SIZE, "character record")
        self.items = tuple(items)
        self.effects = tuple(effects)
        self.source = source

    @property
    def name(self) -> str:
        n = self.get("name_length")
        if not 0 <= n <= 15:
            raise DosRecordError(f"name length {n} is not 0-15")
        return self.raw("name_text")[:n].decode("ascii", "replace")

    @property
    def spells_known(self) -> list[int]:
        """The spell ids the byte-per-spell book at `0x033` has set.

        DOS byte *n* is spell id *n + 1*, and the ids are the C64's own --
        `por/spells.py`'s group boundaries 1-8, 9-21, 22-28, 29-35, 36-44,
        45-55 are the DOS array's cleric-1 / mage-1 / cleric-2 / mage-2 /
        cleric-3 / mage-3 runs exactly.
        """
        book = self.raw("spellbook")
        return [i + 1 for i, b in enumerate(book) if b]

    @property
    def spells_memorised(self) -> list[int]:
        """Memorised spell ids, highest first -- the C64's own order.

        DOS fills its sixteen slots **backwards from the end**; the C64 fills
        its own forwards in descending id.  Reversing is the whole transpose.
        """
        return [b for b in reversed(self.raw("spells_memorised")) if b]

    @property
    def class_levels(self) -> dict[str, int]:
        """Class name -> level, for the classes that carry one."""
        raw = self.raw("class_levels")
        return {name: raw[n] for n, name, _ in CLASS_LEVEL_SLOTS if raw[n]}

    @property
    def money(self) -> dict[str, int]:
        return {k: self.get(k) for k in
                ("copper", "silver", "electrum", "gold", "platinum", "gems",
                 "jewelry")}

    @property
    def effect_ids(self) -> list[int]:
        """The first byte of each 9-byte `.SPC` record."""
        return [e[0] for e in self.effects]

    def expected_encumbrance(self) -> int:
        """`money + sum(item weight x quantity)`, the identity worth keeping.

        Self-contained arithmetic across three structures -- the money block,
        the item file and one derived field -- so it confirms the money
        offsets, the 63-byte item stride, the weight offset and the byte order
        together.  It balances for 16 of the 18 saved characters and all six
        exports; the two that miss carry a stack of darts whose cached name
        disagrees with the quantity byte.
        """
        total = sum(self.money.values())
        for it in self.items:
            # A quantity of zero means one: the field counts *extra* copies
            # for anything that does not stack, and the identity only balances
            # this way round.
            total += it.get("weight") * (it.get("quantity") or 1)
        return total


# ---------------------------------------------------------------------------
# Reading the files
# ---------------------------------------------------------------------------
def _sibling(path: pathlib.Path, suffix: str) -> bytes:
    other = path.with_suffix(suffix)
    return other.read_bytes() if other.exists() else b""


def read_character(path: str | pathlib.Path) -> DosCharacter:
    """One character from a `CHRDAT<slot><n>.SAV` or a `<NAME>.CHA`.

    The sibling `.ITM` and `.SPC` are read too when they are there; an export
    normally has neither.
    """
    path = pathlib.Path(path)
    data = path.read_bytes()
    if len(data) != RECORD_SIZE:
        raise DosRecordError(
            f"{path.name} is {len(data)} bytes, not a {RECORD_SIZE}-byte Pool "
            f"of Radiance record. Curse is 422, Silver Blades 439, Pools of "
            f"Darkness 510, and each needs its own table")
    itm = _sibling(path, ".ITM")
    spc = _sibling(path, ".SPC")
    # The record's own item count is what says how many of the `.ITM` file
    # belong to this character. It is zeroed in an export, and an export that
    # sits beside a stale `.ITM` from an earlier save would otherwise be given
    # items it does not carry -- which is exactly what the archives hold.
    count = data[FIELDS_BY_NAME["item_count"].offset]
    items = [DosItem(itm[i * ITEM_SIZE:(i + 1) * ITEM_SIZE])
             for i in range(min(count, len(itm) // ITEM_SIZE))]
    effects = [spc[i:i + EFFECT_SIZE] for i in range(0, len(spc), EFFECT_SIZE)
               if len(spc[i:i + EFFECT_SIZE]) == EFFECT_SIZE]
    return DosCharacter(data, items, effects, source=str(path))


def slots_available(folder: str | pathlib.Path) -> list[str]:
    """The save slot letters present in a DOS save directory."""
    folder = pathlib.Path(folder)
    return sorted(p.name[6] for p in folder.glob("SAVGAM?.DAT"))


def read_party(folder: str | pathlib.Path, slot: str) -> list[DosCharacter]:
    """The six characters of one save slot, in file order."""
    folder = pathlib.Path(folder)
    out = []
    for n in range(1, 7):
        path = folder / f"CHRDAT{slot}{n}.SAV"
        if path.exists():
            out.append(read_character(path))
    if not out:
        raise DosRecordError(f"no CHRDAT{slot}?.SAV in {folder}")
    return out


# ---------------------------------------------------------------------------
# The conversion report -- what became of every byte
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class Report:
    """Where each byte of the C64 record came from, and what was left behind.

    `docs/117-save-conversion.md` makes this the test that replaces a round
    trip: for any offset in the output, say where that byte came from.
    """

    #: How many bytes the provenance covers: one 580-byte record by default,
    #: or a whole `SAVEDGAME0` payload when `convert_save` builds it.
    total: int = C64_RECORD_SIZE
    #: Offset -> a one-line provenance.
    sources: dict[int, str] = dataclasses.field(default_factory=dict)
    #: DOS fields with no C64 home, said out loud rather than dropped.
    dropped: list[str] = dataclasses.field(default_factory=list)
    #: Anything the conversion could not do faithfully.
    warnings: list[str] = dataclasses.field(default_factory=list)

    def note(self, offset: int, size: int, why: str) -> None:
        for i in range(offset, offset + size):
            self.sources[i] = why

    @property
    def unaccounted(self) -> list[int]:
        """C64 offsets this conversion cannot explain. Should be empty."""
        return [i for i in range(self.total) if i not in self.sources]

    def summary(self) -> str:
        lines = [f"{len(self.sources)}/{self.total} bytes accounted for"]
        if self.unaccounted:
            lines.append(f"  UNACCOUNTED: {len(self.unaccounted)} bytes")
        for w in self.warnings:
            lines.append(f"  warning: {w}")
        for d in self.dropped:
            lines.append(f"  dropped: {d}")
        return "\n".join(lines)


#: DOS field -> C64 field, where the conversion is a straight copy of a value
#: the two ports encode the same way.  Everything not in this table needs work
#: and gets it below.
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
    # The class byte copies because the two ports share one 18-entry table:
    # por/yaml_io.py's CLASS_CODES is Gold Box Companion's list entry for
    # entry, checked against the class bitmask on all 24 specimens.
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

#: DOS fields deliberately left behind, and why.  Reported, never silent.
DROPPED: tuple[tuple[str, str], ...] = (
    ("encumbrance", "derived -- money plus item weight; the C64 has no such "
                    "field and recomputes what it needs"),
    ("item_chain", "live heap state: the DOS item list is a chain of far "
                   "pointers, the C64 has sixteen fixed slots"),
    ("heap_0c1", "live heap pointers"),
    ("heap_104", "live heap pointers"),
    ("effect_chain", "live pointer to the effect list; the effects "
                     "themselves come from the .SPC file"),
    ("item_count", "implied by the C64's sixteen fixed slots"),
    ("icon_choice", "DOS art: a different set from CHARPIC00 and "
                    "HEADnn/BODYnn, with different numbering"),
    ("icon_dimension", "the C64 has one size byte where DOS has two fields; "
                       "the C64's carries the other one"),
    ("strength_bonus", "a boolean on DOS; the C64's aligned byte is a "
                       "strength *index* and is computed instead"),
    ("hands_used", "live combat state"),
    ("unnamed_0ab", "one unattributed byte, stable per character"),
    ("field_83_87", "unattributed; Curse's importer copies it without naming "
                    "it either"),
)


#: DOS fields converted by a rule rather than by a copy.  Named here so the
#: disposition check below can see them; the rules themselves are in
#: `to_c64_record`.
TRANSFORMED: tuple[tuple[str, str], ...] = (
    ("name_length", "folded into the C64's 20-byte NUL-padded name"),
    ("name_text", "re-padded into the C64's 20-byte name"),
    ("spellbook", "56 bytes packed into 56 bits; the ids are identical"),
    ("spells_memorised", "reversed: DOS fills from the end, the C64 from the "
                         "start"),
    ("class_levels", "permuted from class number to class bit"),
    ("spells_castable_cleric", "packed into the C64's high nibbles"),
    ("spells_castable_magic_user", "packed into the C64's low nibbles"),
    ("size", "1/2 on DOS becomes 0/1 on the C64"),
    ("turn_power", "one DOS byte for the C64's two turning bytes"),
    ("attack_forms", "copied as a block"),
    ("roster_tail", "copied as a block into the C64's roster tail"),
)


def field_disposition() -> dict[str, str]:
    """Every declared DOS field and what the conversion does with it.

    The test that keeps this module honest: a field declared in
    `por/dos_layout.py` and named nowhere here would be a field silently
    dropped, which `docs/117-save-conversion.md` forbids.
    """
    out: dict[str, str] = {}
    for name, c64 in DIRECT:
        out[name] = f"copied to the C64's {c64}"
    for name, why in TRANSFORMED:
        out[name] = why
    for name, why in DROPPED:
        out[name] = f"dropped: {why}"
    return out


def _clamp_nibble(n: int) -> int:
    return min(int(n), 0x0F)


def to_c64_record(dos: DosCharacter, slot: int = 0,
                  icon: bytes | None = None) -> tuple[CharacterRecord, Report]:
    """Build a 580-byte C64 character record from a DOS one.

    `slot` only names the character in the report.  `icon` is the 36-byte
    combat icon; DOS has no equivalent -- its art is a different set -- so
    with none given the field is left zero and reported.
    """
    rec = CharacterRecord.blank()
    rep = Report()

    # -- the name: length-prefixed ASCII becomes 20 NUL-padded bytes --------
    rec.set("name", dos.name)
    rep.note(0x000, 20, "name, re-padded from the DOS count byte at 0x000")

    for dos_name, c64_name in DIRECT:
        src = FIELDS_BY_NAME[dos_name]
        dst = rec_field(c64_name)
        rec.set(c64_name, dos.get(dos_name))
        rep.note(dst.offset, dst.size,
                 f"{c64_name} <- DOS {dos_name} @{src.offset:#05x} "
                 f"({src.confidence})")

    # -- the second ability array -------------------------------------------
    # Seven zeroes in every Pool of Radiance specimen, and Curse's importer
    # writes both halves of every (base, current) pair. Zero is what a Pool of
    # Radiance C64 record holds, so zero is what we write.
    rep.note(0x065, 7, "abilities_second: zero, as in every C64 Pool of "
                       "Radiance specimen")

    # -- the spellbook: 56 bytes become 56 bits ------------------------------
    known = dos.spells_known
    carried = [i for i in known if i <= spells.LAST_SPELLBOOK_SPELL]
    rec.set("spells_known", spells.spellbook_bytes(carried))
    rep.note(0x078, 7, "spells_known <- DOS spellbook @0x033, one byte per "
                       "spell packed to one bit; ids are identical")
    for i in known:
        if i > spells.LAST_SPELLBOOK_SPELL:
            rep.warnings.append(
                f"spell id {i} is set in the DOS spellbook and the C64's "
                f"seven-byte mask has no bit for it (56 bits hold ids 0-55 "
                f"and id 0 does not exist); id 56 is RESTORATION")

    # -- memorised spells: DOS fills backwards, the C64 forwards -------------
    mem = dos.spells_memorised[:16]
    rec.set_raw("spells_memorised", bytes(mem) + bytes(16 - len(mem)))
    rep.note(0x020, 16, "spells_memorised <- DOS 0x01C reversed (DOS fills "
                        "its slots from the end; the C64 from the start)")

    # -- the per-class level array: indexed by number, not by bit ------------
    raw_levels = dos.raw("class_levels")
    for n, name, field in CLASS_LEVEL_SLOTS:
        if field is None:
            if raw_levels[n]:
                rep.warnings.append(
                    f"DOS carries {name} level {raw_levels[n]}, and the C64's "
                    f"eight-slot array has no {name} slot")
            continue
        rec.set(field, raw_levels[n])
    for f in ("level_magic_user", "level_cleric", "level_thief",
              "level_fighter", "level_knight", "level_paladin",
              "level_ranger"):
        dst = rec_field(f)
        rep.note(dst.offset, dst.size,
                 f"{f} <- DOS class_levels @0x096, permuted from class number "
                 f"to class bit")
    rep.note(0x0CE, 1, "the C64's unused sixth level slot: zero")

    # -- spell slots: two DOS triples become three packed nibbles -----------
    cleric = dos.raw("spells_castable_cleric")
    mage = dos.raw("spells_castable_magic_user")
    packed = bytes((_clamp_nibble(cleric[i]) << 4) | _clamp_nibble(mage[i])
                   for i in range(3)) + bytes(3)
    rec.set_raw("spells_castable", packed)
    rep.note(0x0EE, 6, "spells_castable <- DOS 0x0B2 (cleric) and 0x0B5 "
                       "(magic-user), repacked cleric-high/magic-user-low")

    # -- size: DOS 1 small / 2 medium, the C64 0 small / 1 large ------------
    rec.set("size_small", max(0, dos.get("size") - 1))
    rep.note(0x099, 1, "size_small <- DOS size @0x0C0, less one")

    # -- turning: the C64 has two bytes where DOS Pool of Radiance has one ---
    rec.set("turn_power", dos.get("turn_power"))
    rep.note(0x0A3, 1, "turn_class: zero -- no player character is undead")
    rep.note(0x0A4, 1, "turn_power <- DOS 0x076 (PROBABLE: which of the C64's "
                       "two turning bytes this is cannot be told from a party "
                       "with no turning cleric above level 3)")

    # -- attack forms: eight bytes, same shape ------------------------------
    rec.set_raw("attack_forms", dos.raw("attack_forms"))
    rep.note(0x0D9, 8, "attack_forms <- DOS 0x0A1 (PROBABLE)")

    # -- computed, not copied ------------------------------------------------
    rec.set("infravision", INFRAVISION.get(dos.get("race"), 0))
    rep.note(0x0D5, 1, "infravision: computed from race; DOS does not store it")
    rec.set("strength_index", _strength_index(dos.get("strength"),
                                              dos.get("exceptional_strength")))
    rep.note(0x0E2, 1, "strength_index: computed from strength and the "
                       "percentile; the DOS byte at the aligned offset is a "
                       "different field")

    # -- innate effects: the racial half of the .SPC file --------------------
    innate = [e for e in dos.effect_ids if e in INNATE_EFFECTS][:10]
    rec.set_raw("item_effects", bytes(innate) + bytes(10 - len(innate)))
    rep.note(0x0AD, 10,
             "item_effects <- the innate ids of the DOS .SPC file; the two "
             "ports share one effect-id namespace (por/traits.py)")
    for e in dos.effect_ids:
        if e not in INNATE_EFFECTS:
            rep.dropped.append(
                f".SPC effect {e} ({traits.describe(e)}): a running effect, "
                f"not an innate one, and running effects do not survive")

    # -- the inventory: sixteen fixed slots ---------------------------------
    inv = bytearray(256)
    for n, it in enumerate(dos.items[:16]):
        inv[n * 16:(n + 1) * 16] = it.to_c64()
    rec.set_raw("inventory", bytes(inv))
    rep.note(0x120, 256, "inventory <- the .ITM file, each 63-byte record "
                         "projected onto sixteen bytes")
    if len(dos.items) > 16:
        rep.warnings.append(
            f"{len(dos.items)} items and the C64 has sixteen slots; "
            f"{len(dos.items) - 16} dropped from the end")

    # -- the combat icon: DOS has none --------------------------------------
    if icon is not None:
        rec.set_raw("region_220", bytes(icon))
        rep.note(0x220, 36, "combat icon: supplied")
    else:
        rep.note(0x220, 36, "combat icon: zero. DOS has no C64 charset icon; "
                            "por/iconparts.py can compose a legal one")
        rep.dropped.append("the combat icon: C64 icons are 18 CHARPIC00 "
                           "screen codes plus 18 colours and DOS has no "
                           "equivalent")

    # -- fields with no DOS source, written as documented constants ---------
    rep.note(0x0B8, 1, "flags_0b8: zero -- a player character, bit 7 clear")
    rep.note(0x0FE, 2, "portrait_head/body: zero. HEADnn/BODYnn name C64 disk "
                       "files; the DOS art is a different set")
    rep.dropped.append("portrait ids: the DOS art has different numbering")
    rep.note(0x100, 1, "roster status: 1 (OK)")
    rec.set("roster_in_use", 1)
    rec.set_raw("roster_tail", dos.raw("roster_tail"))
    rep.note(0x110, 9, "roster_tail <- DOS 0x112: the armour bonus and the "
                       "eight running attack-form bytes, one for one")

    for name, why in DROPPED:
        rep.dropped.append(f"DOS {name} @{FIELDS_BY_NAME[name].offset:#05x}: {why}")

    # Everything still unnamed is a byte the C64 record does not use: the
    # unknown gaps of por/layout.py, which are zero in every specimen we hold.
    for f in _c64_layout():
        for i in range(f.offset, f.end):
            rep.sources.setdefault(
                i, f"{f.name}: zero (UNKNOWN on the C64 side and zero in "
                   f"every specimen)" if not f.is_known
                   else f"{f.name}: zero (no DOS source)")
    return rec, rep


def _strength_index(strength: int, percentile: int) -> int:
    """The C64's `strength_index`: STR below 18, else 18 plus the band.

    Equals strength below 18; 18/01-18/50 give 19 and 20, 18/80 and 18/81 give
    21, 18/98 gives 22 -- the AD&D exceptional-strength bands collapsed to one
    number.  PROBABLE, and it is computed rather than copied because the DOS
    byte at the aligned offset is a boolean.
    """
    if strength != 18 or not percentile:
        return strength
    for bound, value in ((50, 19), (75, 20), (90, 21), (99, 22)):
        if percentile <= bound:
            return value
    return 23


def _c64_layout():
    from . import layout as _l
    return _l.LAYOUT


def rec_field(name: str) -> Field:
    from . import layout as _l
    return _l.FIELDS_BY_NAME[name]


# ---------------------------------------------------------------------------
# The YAML interchange -- the same shape `por/yaml_io.export_save` produces
# ---------------------------------------------------------------------------
def export_party(folder: str | pathlib.Path, slot: str,
                 game_disk: str | None = None) -> dict[str, Any]:
    """A DOS save slot as the same plain data a C64 export produces.

    The record is converted first and the entry built by `yaml_io.entry_for`,
    so a DOS party and a C64 party render through one code path and come out
    in one shape -- which is what `docs/117` means by keeping the existing
    YAML as the interchange rather than inventing a second one.  It makes the
    reader a DOS character viewer, which is worth having on its own.

    Everything DOS keeps and the C64 does not is carried as a `_`-prefixed
    annotation: `strip_annotations` drops those on import, so the document
    still describes exactly what a C64 save can hold.
    """
    from .icons import Icon
    from .items import ITEM_SIZE as C64_ITEM_SIZE
    from .items import Item, load_item_names, load_item_types
    from .spells import load_spell_names
    from .yaml_io import entry_for

    names = types = spell_names = None
    if game_disk:
        for loader in (load_item_names, load_item_types, load_spell_names):
            try:
                value = loader(game_disk)
            except Exception:
                value = None
            if loader is load_item_names:
                names = value
            elif loader is load_item_types:
                types = value
            else:
                spell_names = value

    party = []
    for index, char in enumerate(read_party(folder, slot)):
        rec, rep = to_c64_record(char, slot=index)
        inv = rec.get_raw("inventory")
        items = [Item(inv[n * C64_ITEM_SIZE:(n + 1) * C64_ITEM_SIZE], names)
                 for n in range(len(inv) // C64_ITEM_SIZE)]
        items = [i for i in items if not i.is_empty]
        entry = entry_for(rec, index, items=items,
                          icon=Icon(rec.get_raw("region_220")),
                          names=names, types=types, spell_names=spell_names)
        # What DOS keeps and the C64 does not. Reported, not dropped.
        entry["_dos_encumbrance"] = char.get("encumbrance")
        entry["_dos_encumbrance_expected"] = char.expected_encumbrance()
        entry["_dos_effects"] = [f"{e}: {traits.describe(e)}"
                                 for e in char.effect_ids]
        entry["_dos_item_weights_lb"] = [it.get("weight") / 10.0
                                         for it in char.items]
        entry["_dropped"] = list(rep.dropped)
        if rep.warnings:
            entry.setdefault("_warnings", []).extend(rep.warnings)
        party.append(entry)

    return {
        "source_path": str(pathlib.Path(folder).resolve()),
        "source_slot": slot,
        "game": "pool-of-radiance",
        "port": "dos",
        "party": party,
    }


# ---------------------------------------------------------------------------
# `SAVGAM<slot>.DAT` -- the saved game
# ---------------------------------------------------------------------------
#: One header byte, then the engine's whole variable space as u16le, indexed
#: by the address the ECL bytecode itself uses:
#:
#:     file offset of ECL address A = 1 + 2 * (A - $4900)
#:
#: The mechanism is Curse's `vm_SetMemoryValue`, which ends in
#: `field_6A00_Set(0x6A00 + location * 2, value)` -- the operand address
#: doubled -- and `ovr021.cs` annotates the array `// as WORD[]`.
SAVGAM_SIZE = 13137
SAVGAM_BASE = 0x4900
SAVGAM_WORDS = 2560

#: The persistent quest flags. `work/reports/quest-flags.md` gives all 352
#: bytes of $4A20-$4B7F a disposition; $4AF9 upwards is provably not flag
#: storage, so only this window transfers.
FLAGS_FIRST = 0x4A20
FLAGS_LAST = 0x4AF8

#: The party's square. Not in the variable array -- $49C0-$49C2 read zero in
#: every DOS save -- so these were found by driving the game and diffing saves
#: one action apart.
POS_X, POS_Y, POS_FACING = 12801, 12802, 12803

#: Facing is the C64's value doubled: 0 N, 2 E, 4 S, 6 W.
FACING_SCALE = 2

#: The current area, as the entry for $49C5, in `por/areas.py`'s own
#: numbering; and again at the entry for $49F2.
AREA_ID = 395
AREA_ID_ALT = 485
#: Byte 0 is the `GEO`/`ECL` `.DAX` file number, 1-8 -- the *container*, not
#: the map: GEO3.DAX holds areas 0 and 14, so it narrows the area and no more.
AREA_FILE = 0


def savgam_word(save: bytes, address: int) -> int:
    """The engine variable at an ECL address."""
    off = 1 + 2 * (address - SAVGAM_BASE)
    if not 0 <= off <= len(save) - 2:
        raise DosRecordError(f"{address:#06x} is outside this saved game")
    return struct.unpack_from("<H", save, off)[0]


def quest_flags(save: bytes) -> bytes:
    """`$4A20`-`$4AF8` as the C64's 217 bytes: read the word, keep the byte.

    Every nonzero word in the window is 1, 2, 3 or 255 across three saves of
    two parties -- the flag alphabet, nothing wider -- and the runs the
    quest-flag report names are set and clear together.  A base off by one
    would straddle them.
    """
    out = bytearray()
    for addr in range(FLAGS_FIRST, FLAGS_LAST + 1):
        word = savgam_word(save, addr)
        out.append(word & 0xFF)
    return bytes(out)


def position(save: bytes) -> tuple[int, int, int]:
    """`(x, y, facing)` with facing in the C64's 0-3, not the DOS 0-6."""
    facing = save[POS_FACING]
    return save[POS_X], save[POS_Y], facing // FACING_SCALE


def area_id(save: bytes) -> int:
    """The current area, in `por/areas.py`'s numbering."""
    return savgam_word(save, 0x49C5)


def area_file(save: bytes) -> int:
    """Which `GEO`/`ECL` `.DAX` file holds that area, 1-8."""
    return save[AREA_FILE]


def apply_quest_flags(save0: bytearray, savgam: bytes) -> int:
    """Copy the flags into a C64 `SAVEDGAME0` payload. Returns bytes changed.

    `SAVEDGAME0` is a verbatim image of `$4900`-`$64FF`, so the C64 offset of
    an address is the address less `$4900`.
    """
    flags = quest_flags(savgam)
    base = FLAGS_FIRST - SAVGAM_BASE
    changed = sum(1 for i, b in enumerate(flags) if save0[base + i] != b)
    save0[base:base + len(flags)] = flags
    return changed


def apply_position(save0: bytearray, savgam: bytes) -> None:
    """Write the party's square, facing and current area into `SAVEDGAME0`."""
    x, y, facing = position(savgam)
    save0[0x49C0 - SAVGAM_BASE] = x
    save0[0x49C1 - SAVGAM_BASE] = y
    save0[0x49C2 - SAVGAM_BASE] = facing
    save0[0x4BC2 - SAVGAM_BASE] = area_id(savgam)


# ---------------------------------------------------------------------------
# The whole save
# ---------------------------------------------------------------------------
#: `SAVEDGAME0` is a verbatim image of `$4900`-`$64FF` and `SAVEDGAME1` of
#: `$8300`-`$8AFF`. Every offset below is an address less `$4900` (or `$8300`).
SAVE0_BASE = 0x4900
SAVE1_BASE = 0x8300
SLOT_AREA = 0x4D00
SLOT_STRIDE = 0x100
ITEM_AREA = 0x5900
ICON_TABLE = 0x4BE0
ICON_SIZE = 36
ROSTER_STRIDE = 0x20
#: The four 64-entry active-effect arrays. Zero is "no effects running", which
#: is a legal state, and it is what a converted save should carry: every
#: temporary effect is lost in the trip and dropping them is the honest form
#: of that. `docs/133-active-effects.md`.
EFFECT_ARRAYS = ((0x4900, 0xC0), (0x4B80, 0x40))
#: Per-script scratch. `DUNGEON $202A` zeroes it on every area change anyway.
SCRIPT_SCRATCH = (0x4A00, 0x20)
#: The loaded-files cache: one entry per data-file type, saying which `GEO`,
#: `ECL`, `MON` and `PIC` the engine believes are resident, and **bit 7 is a
#: reload marker** (`docs/41-memory-regions.md`).  `$4BC2` is entry 2 and is
#: the current area, which is why the two are one region and not two.
#:
#: **Leave it alone, and take the template from the DOS save's own area.**
#: Two experiments, both on a template standing in the Slums against a DOS
#: party in New Phlan: zeroing the region hangs the game in `OUTWARD BOUND
#: ...` asking for a disk forever, because entry 2 reads `$00` -- area 0 with
#: the reload bit *clear*, which says the map it has not got is resident.
#: Setting bit 7 on every entry hangs it too: the low bits are still the
#: *template's* file numbers, so the engine reloads the wrong files for the
#: new area.  Filling it correctly needs the entry-to-file mapping decoded,
#: and until that is done `convert_save` refuses a template from a different
#: area rather than writing a save that loads and then hangs.
FILE_CACHE = (0x4BC0, 0x19)
FILE_CACHE_RELOAD = 0x80


class AreaMismatch(DosRecordError):
    """The template save stands somewhere the DOS party does not."""


def convert_save(folder: str | pathlib.Path, slot: str,
                 save0: bytearray, save1: bytearray | None = None,
                 keep_icons: bool = True,
                 allow_area_change: bool = False) -> Report:
    """Write a DOS save into C64 `SAVEDGAME0` / `SAVEDGAME1` payloads.

    `save0` and `save1` come from an existing C64 save, which supplies the
    regions a DOS save cannot: `$8400`-`$8AFF` is `ANIMATE00` and a bitmap
    buffer and is not save data at all, and the combat icons are a C64 charset
    DOS has no equivalent of.  Everything else is replaced.

    Both payloads are modified in place.  The DOS files are only ever read.
    """
    party = read_party(folder, slot)
    savgam = pathlib.Path(folder).joinpath(f"SAVGAM{slot}.DAT").read_bytes()
    report = Report(total=len(save0))
    here = save0[0x4BC2 - SAVE0_BASE] & ~FILE_CACHE_RELOAD
    there = area_id(savgam)
    if here != there and not allow_area_change:
        raise AreaMismatch(
            f"the template save is in area {here} and the DOS party is in "
            f"area {there}. The loaded-files cache at $4BC0 names the files "
            f"for the template's area and nothing in a DOS save can refill "
            f"it, so the converted save loads and then hangs. Use a template "
            f"saved in area {there}, or pass allow_area_change=True and "
            f"expect it not to work")

    for index, char in enumerate(party):
        icon = None
        if keep_icons:
            at = ICON_TABLE - SAVE0_BASE + index * ICON_SIZE
            icon = bytes(save0[at:at + ICON_SIZE])
        rec, one = to_c64_record(char, slot=index, icon=icon)
        raw = rec.to_bytes()
        at = SLOT_AREA - SAVE0_BASE + index * SLOT_STRIDE
        save0[at:at + SLOT_STRIDE] = raw[:SLOT_STRIDE]
        report.note(at, SLOT_STRIDE, f"slot {index}: the converted record")
        at = ITEM_AREA - SAVE0_BASE + index * SLOT_STRIDE
        save0[at:at + SLOT_STRIDE] = raw[0x120:0x220]
        report.note(at, SLOT_STRIDE, f"slot {index}: the converted inventory")
        at = ICON_TABLE - SAVE0_BASE + index * ICON_SIZE
        if keep_icons:
            report.note(at, ICON_SIZE, f"slot {index}: the template's icon")
        else:
            save0[at:at + ICON_SIZE] = raw[0x220:0x244]
            report.note(at, ICON_SIZE, f"slot {index}: icon from the record")
        if save1 is not None:
            at = index * ROSTER_STRIDE
            save1[at:at + ROSTER_STRIDE] = raw[0x100:0x120]
        report.dropped.extend(d for d in one.dropped if d not in report.dropped)
        report.warnings.extend(f"{char.name}: {w}" for w in one.warnings)

    for base, size in EFFECT_ARRAYS:
        at = base - SAVE0_BASE
        save0[at:at + size] = bytes(size)
        report.note(at, size, "active effects: zeroed, which is 'none running'")
    at = SCRIPT_SCRATCH[0] - SAVE0_BASE
    save0[at:at + SCRIPT_SCRATCH[1]] = bytes(SCRIPT_SCRATCH[1])
    report.note(at, SCRIPT_SCRATCH[1],
                "per-script scratch: zeroed, as DUNGEON $202A does on every "
                "area change")
    at = FILE_CACHE[0] - SAVE0_BASE
    report.note(at, FILE_CACHE[1],
                "loaded-files cache: the template's, unchanged -- it names "
                "the files for the area, and the template is in the DOS "
                "party's area")

    here_bit = save0[0x4BC2 - SAVE0_BASE] & FILE_CACHE_RELOAD
    changed = apply_quest_flags(save0, savgam)
    report.note(FLAGS_FIRST - SAVE0_BASE, FLAGS_LAST - FLAGS_FIRST + 1,
                "quest flags: the DOS word array, narrowed to bytes")
    apply_position(save0, savgam)
    # $4BC2 is entry 2 of the cache above, so `apply_position` has just
    # cleared its reload bit; put back whatever the template had.
    save0[0x4BC2 - SAVE0_BASE] |= here_bit
    for address, what in ((0x49C0, "party x"), (0x49C1, "party y"),
                          (0x49C2, "facing, the DOS value halved"),
                          (0x4BC2, "current area, keeping the template's "
                                   "reload bit")):
        report.note(address - SAVE0_BASE, 1, what + ", from SAVGAM")
    report.warnings.append(
        f"{changed} of {FLAGS_LAST - FLAGS_FIRST + 1} quest-flag bytes "
        f"differed from the template's")
    if keep_icons:
        report.dropped.append(
            "the combat icons: kept from the template save, because DOS has "
            "no C64 charset icon to convert")
    # Everything not written above stays as the template save had it, and
    # that is a provenance too -- an honest one, and the reason a template is
    # required at all.
    for i in range(len(save0)):
        report.sources.setdefault(i, "carried through from the template save")
    return report


if __name__ == "__main__":  # pragma: no cover - convenience
    import sys

    from .yaml_io import to_yaml

    if len(sys.argv) < 3:
        print("usage: python3 -m por.dos <dos-save-dir> <slot> [game.d64]")
        raise SystemExit(2)
    print(to_yaml(export_party(sys.argv[1], sys.argv[2],
                               sys.argv[3] if len(sys.argv) > 3 else None)))
