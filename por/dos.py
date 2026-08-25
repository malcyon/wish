"""The DOS codec: read a DOS Pool of Radiance save, or write one.

Both directions now (#26).  The player's own DOS files are still opened
read-only and never written -- :func:`write` builds *new* bytes, and
:func:`write_dos_save` writes them into a directory the caller names.

    DOS character file  ->  to_neutral  ->  NeutralCharacter
                                          ->  c64_codec.write  ->  C64 record
    C64 save  ->  c64_codec.read  ->  NeutralCharacter
                                    ->  dos.write  ->  DOS record + .ITM

The middle is `por/neutral.py`'s typed record, and this module is the DOS
codec of that pair -- the only module that knows a DOS offset.  The C64 half
is `por/c64_codec.py`'s, and the two never mention each other.
`por/dos_layout.py` is the field table, in the same declarative style as
`por/layout.py` and with a confidence on every entry, which is the grade the
neutral value carries and a writer refuses to write below.

`export_party` renders the result as the editor's own YAML, so a DOS party
and a C64 party come out in one shape; that is a view, not the interchange.

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
  *number*, the C64 by the class *bit*, and the neutral record names the class
  instead; `CLASS_LEVEL_SLOTS` is this side of it, `c64_codec.LEVEL_FIELDS`
  the other, and druid and monk have no C64 slot at all.
* **The items.** Past its cached display line the 63-byte DOS record *is* the
  C64's sixteen bytes, one field to a byte -- `item_to_c64` is the projection,
  and it reproduces 157 of the 163 distinct C64 item records byte for byte.

Evidence: `work/reports/dos-saves.md`, `work/reports/dos-items.md`,
`docs/117-save-conversion.md`.  Assertions: `tests/test_dosconvert.py`.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Any, Sequence

from . import areas, c64_codec, dos_savegame, neutral, traits
from .c64_codec import Report
from .dos_layout import (
    EFFECT_SIZE,
    FIELDS_BY_NAME,
    ITEM_FIELDS_BY_NAME,
    ITEM_SIZE,
    LAYOUT,
    RECORD_SIZE,
    SPELLBOOK_SPELLS,
)
from .layout import Confidence, Field, Kind
from .neutral import NeutralCharacter, Provenance
from .record import CharacterRecord

__all__ = [
    "DosRecordError",
    "INFRAVISION",
    "to_neutral",
    "DosCharacter",
    "DosItem",
    "Report",
    "item_to_c64",
    "item_from_c64",
    "read_character",
    "read_party",
    "slots_available",
    "to_c64_record",
    "export_party",
    "quest_flags",
    "apply_position",
    "apply_quest_flags",
    "apply_file_cache",
    "convert_save",
    "WriteReport",
    "write",
    "write_field_disposition",
    "write_dos_save",
]


class DosRecordError(ValueError):
    """A file that is not a DOS Pool of Radiance record."""


#: Race -> infravision range.  The table lives with the C64 writer, which is
#: the only port that stores infravision at all; it is re-exported here
#: because this module is where it was first written down.
INFRAVISION = c64_codec.INFRAVISION


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
# What the conversion does with every DOS field
# ---------------------------------------------------------------------------
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
    ("field_10c_10f", "unattributed; 00 01 00 00 in all 24 specimens, inside "
                      "the combat tail"),
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
    dropped, which `docs/117-save-conversion.md` forbids.  The shape is
    `por/neutral.py`'s, so every direction reports its drops the same way.
    """
    return neutral.disposition(DIRECT, TRANSFORMED, DROPPED, "the C64's")


def to_neutral(dos: DosCharacter) -> NeutralCharacter:
    """Read one DOS character into the neutral record.

    The DOS half of the pair `por/neutral.py` describes, and the only half
    that knows a DOS offset.  It names where every value came from and what
    the DOS record holds that no neutral field does; what becomes of them
    afterwards is a writer's business.
    """
    out = NeutralCharacter("DOS", source=dos.source)

    # -- the name: a count byte and fifteen characters -----------------------
    out.set("name", dos.name, "the DOS count byte and text at 0x000",
            FIELDS_BY_NAME["name_text"].confidence, Provenance.RESHAPED)

    # -- everything the two ports encode the same way ------------------------
    for dos_name, _ in DIRECT:
        f = FIELDS_BY_NAME[dos_name]
        out.set(dos_name, dos.get(dos_name),
                f"DOS {dos_name} @{f.offset:#05x} ({f.confidence})",
                f.confidence)

    # -- the spellbook: one byte per spell ------------------------------------
    out.set("spells_known", dos.spells_known,
            "DOS spellbook @0x033, one byte per spell",
            FIELDS_BY_NAME["spellbook"].confidence)

    # -- memorised spells, put into the neutral order: highest first ---------
    out.set("spells_memorised", dos.spells_memorised,
            "DOS 0x01C, reversed into the neutral highest-first order",
            FIELDS_BY_NAME["spells_memorised"].confidence)

    # -- the per-class levels, named rather than numbered --------------------
    raw_levels = dos.raw("class_levels")
    out.set("levels", {name: raw_levels[n] for n, name, _ in CLASS_LEVEL_SLOTS},
            "DOS class_levels @0x096, permuted from class number to class bit",
            FIELDS_BY_NAME["class_levels"].confidence)

    # -- spell slots: two triples, by class ----------------------------------
    out.set("spells_castable",
            {"cleric": tuple(dos.raw("spells_castable_cleric")),
             "magic-user": tuple(dos.raw("spells_castable_magic_user"))},
            "DOS 0x0B2 (cleric) and 0x0B5 (magic-user)",
            FIELDS_BY_NAME["spells_castable_cleric"].confidence)

    # -- size: DOS 1 small / 2 medium, the neutral 0 small / 1 large ---------
    out.set("size_small", max(0, dos.get("size") - 1),
            "DOS size @0x0C0, less one", FIELDS_BY_NAME["size"].confidence)

    out.set("turn_power", dos.get("turn_power"), "DOS 0x076",
            FIELDS_BY_NAME["turn_power"].confidence)
    out.set("attack_forms", dos.raw("attack_forms"), "DOS 0x0A1 (PROBABLE)",
            FIELDS_BY_NAME["attack_forms"].confidence)
    out.set("roster_tail", dos.raw("roster_tail"),
            "DOS 0x112: the armour bonus and the eight running attack-form "
            "bytes, one for one",
            FIELDS_BY_NAME["roster_tail"].confidence)

    # -- the .SPC file splits in two: innate, and running ---------------------
    out.set("innate_effects",
            [e for e in dos.effect_ids if e in INNATE_EFFECTS],
            "the innate ids of the DOS .SPC file; the two ports share one "
            "effect-id namespace (por/traits.py)",
            Confidence.PROBABLE,
            dropped=[f".SPC effect {e} ({traits.describe(e)}): a running "
                     f"effect, not an innate one, and running effects do not "
                     f"survive"
                     for e in dos.effect_ids if e not in INNATE_EFFECTS])

    # -- the .ITM file, projected -------------------------------------------
    out.set("inventory", [it.to_c64() for it in dos.items],
            "the .ITM file, each 63-byte record projected onto sixteen bytes",
            Confidence.CONFIRMED)

    # -- what the DOS record holds and no neutral field does ------------------
    for name, why in DROPPED:
        out.drop(f"DOS {name} @{FIELDS_BY_NAME[name].offset:#05x}: {why}")
    return out


def to_c64_record(dos: DosCharacter, slot: int = 0,
                  icon: bytes | None = None) -> tuple[CharacterRecord, Report]:
    """Build a 580-byte C64 character record from a DOS one.

    A DOS read and a C64 write with the neutral record between them, which is
    all this function is now.  `slot` only names the character in the report.
    `icon` is the 36-byte combat icon; DOS has no equivalent -- its art is a
    different set -- so with none given the field is left zero and reported.
    """
    return c64_codec.write(to_neutral(dos), icon=icon)


# ---------------------------------------------------------------------------
# The writing half: a neutral character becomes a DOS record (#26)
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class WriteReport(neutral.Report):
    """A DOS write's provenance: **every** byte of both outputs explained.

    Offsets 0 to `RECORD_SIZE - 1` are the 285-byte character record;
    `RECORD_SIZE` and up are the `.ITM` payload that goes beside it.  `total`
    is set by :func:`write` once the item count is known.
    """

    total: int = RECORD_SIZE

    @property
    def unaccounted(self) -> list[int]:
        """Offsets this conversion cannot explain. Should be empty."""
        return [i for i in range(self.total) if i not in self.sources]

    def summary_notes(self) -> list[str]:
        if self.unaccounted:
            return [f"  UNACCOUNTED: {len(self.unaccounted)} bytes"]
        return []


@dataclasses.dataclass
class SaveReport(neutral.Report):
    """A whole-save conversion's report: what was carried, and what was not.

    `neutral.Report` says where each byte of a *record* came from; a save
    conversion is coarser than that -- it copies a template and rewrites named
    fields -- so what a reader wants is the list of fields it rewrote.
    `warnings` is still only for what could not be done.
    """

    #: One line per field taken from the C64 save and written into the DOS one.
    carried: list[str] = dataclasses.field(default_factory=list)

    def summary_notes(self) -> list[str]:
        return [f"  carried: {c}" for c in self.carried]


def item_from_c64(record: bytes) -> bytes:
    """Project one C64 sixteen-byte item onto the DOS 63 bytes.

    The inverse of :func:`item_to_c64` for every field the two ports share:
    the C64's two packed bytes come apart into DOS's readied, hidden and
    cursed bytes, everything else is a straight copy.  The 46 bytes the C64
    has no words for are left empty, and each is a documented empty value
    rather than a guess: the rendered line at `0x001` is a cache the game
    rewrites whenever it draws the list, and NULL at `0x02A` is the chain's
    own last-item marker.
    """
    if len(record) != 16:
        raise DosRecordError(f"a C64 item is 16 bytes; got {len(record)}")
    at = {n: ITEM_FIELDS_BY_NAME[n].offset for n in
          ("type_index", "name1", "name2", "name3", "plus", "plus_save",
           "readied", "hidden", "cursed", "weight", "quantity", "value",
           "charges", "effect", "power")}
    r = record
    out = bytearray(ITEM_SIZE)
    out[at["type_index"]] = r[0]
    out[at["name1"]], out[at["name2"]], out[at["name3"]] = r[1], r[2], r[3]
    out[at["plus"]], out[at["plus_save"]] = r[4], r[5]
    out[at["readied"]] = 1 if r[6] & 0x80 else 0
    out[at["hidden"]] = r[6] & 0x07
    out[at["cursed"]] = 1 if r[7] & 0x80 else 0
    out[at["weight"]:at["weight"] + 2] = r[8:10]
    out[at["quantity"]] = r[10]
    out[at["value"]:at["value"] + 2] = r[11:13]
    out[at["charges"]], out[at["effect"]], out[at["power"]] = r[13], r[14], r[15]
    return bytes(out)


#: Neutral field -> the DOS field it becomes, where the value crosses
#: unchanged.  The mirror of the reader's `DIRECT` above: the same fields, in
#: the other direction.
WRITE_DIRECT: tuple[tuple[str, str], ...] = (
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
    # One DOS byte where the C64 has two turning bytes; the C64 *reader*
    # supplies the caster's, which is the pairing `to_neutral` uses too.
    ("turn_power", "turn_power"),
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
    ("thac0_current", "thac0_current"),
    ("armour_class", "armour_class"),
    ("movement_current", "movement_current"),
)

#: Neutral fields the DOS writer takes by a rule rather than by a copy.
WRITE_TRANSFORMED: tuple[tuple[str, str], ...] = (
    ("name", "length-prefixed into one count byte and fifteen ASCII"),
    ("levels", "permuted onto the DOS eight slots, which are indexed by the "
               "class number; a class with no number (knight) is reported"),
    ("spells_known", "unpacked to one byte per spell; the ids are identical, "
                     "and DOS even has the byte for id 56 the C64's mask "
                     "lacks"),
    ("spells_memorised", "reversed: DOS fills its sixteen slots from the "
                         "end, the neutral order is highest first"),
    ("spells_castable", "unpacked from the class map to two three-byte "
                        "runs, cleric at 0x0B2 and magic-user at 0x0B5"),
    ("size_small", "plus one -- DOS stores 1 small / 2 medium"),
    ("attack_forms", "copied as a block to 0x0A1"),
    ("roster_tail", "copied as a block to 0x112, the combat tail the C64 "
                    "roster keeps at -2"),
    ("inventory", "each sixteen-byte record unpacked onto a 63-byte .ITM "
                  "record; the count and the encumbrance are computed from "
                  "it, and an empty inventory writes no .ITM file at all "
                  "rather than an empty one -- ITM_OMITTED_WHEN_EMPTY"),
)

#: Neutral fields the DOS writer takes nothing from, and why.  Reported by
#: `Writer.finish` for any character that carries one, never silent.
WRITE_DROPPED: tuple[tuple[str, str], ...] = (
    ("infravision", "DOS does not store it; the DOS engine derives what it "
                    "needs from the race byte"),
    ("innate_effects", "the 9-byte .SPC effect record is decoded only to its "
                       "id byte, so writing one would be a guess at the "
                       "other eight; no .SPC file is written"),
    ("npc", "no attributed DOS field holds it"),
    ("encumbrance", "recomputed from money and item weight -- the identity "
                    "the DOS engine itself uses -- rather than copied"),
    ("portrait_head", "the DOS icon_choice indexes the DOS art set, which "
                      "no other port numbers; left zero"),
    ("portrait_body", "see portrait_head"),
)

#: **A character carrying nothing gets no `.ITM` file at all**, and an empty
#: file is not the same thing as no file.  Measured, #62: the engine's own
#: save of a character whose items were all dropped in play writes no
#: `CHRDAT<slot><n>.ITM`, and handing it a zero-length one instead -- the same
#: 285 record bytes either way -- is what produced `WEAPON 254 PASSS`,
#: `DAMAGE 0D8-128`, `THAC0 148` and a phantom item in the next save.  The
#: only difference between the clean run and the garbage one is this file's
#: existence: `docs/50-experiments.md`, "A converted character who owns
#: nothing (#62)".
ITM_OMITTED_WHEN_EMPTY = True

#: DOS bytes with no source in any neutral field: live heap the engine
#: rebuilds, and the unattributed.  Zeroed and reported -- and **measured
#: survivable**: a slot whose records differ from the game's own only in
#: these regions loads and plays under DOSBox, and the game's own resave
#: keeps most of the zeroes (`docs/117-save-conversion.md`, the reverse
#: direction).  The round-trip test masks exactly this list rather than
#: whatever happened to differ.
#:
#: Each entry says which characters the zero has been measured against.  #62
#: is why that is written down: the whole list was measured on characters
#: *carrying items* and read as proven, and "a character carrying none" was a
#: case nobody had run.  Four entries have now been measured both ways --
#: the engine's own record for a character who dropped everything in play,
#: `work/p62/truth/CHRDATD1.SAV`.
WRITE_UNSOURCED: tuple[tuple[str, str], ...] = (
    ("effect_chain", "live heap pointer; NULL, which is also what an empty "
                     "effect list looks like. NULL in the engine's own "
                     "record with items and without"),
    ("unnamed_0ab", "unattributed, and different for every DOS character. "
                    "The engine neither reads nor rewrites it: it carries "
                    "our zero through a resave, and keeps its own A5 when a "
                    "character empties his pack. Measured both ways"),
    ("icon_choice", "indexes the DOS art set, which no other port numbers; "
                    "zero leaves the sheet portrait blank. Cosmetic, and the "
                    "same with items and without"),
    ("heap_0c1", "live heap pointers. Carried through a resave unread, with "
                 "items and without"),
    ("item_chain", "live heap pointer block; the items themselves are in "
                   "the .ITM file. **Zero is what the engine itself writes "
                   "for a character carrying nothing** -- measured, #62 -- "
                   "so the empty case is now right by value, not by luck"),
    ("hands_used", "live combat state with no attributed source. The engine "
                   "writes 2 for a fighter holding a weapon and **0 for the "
                   "same fighter after he drops everything**, so zero is "
                   "correct for exactly the character we could not source, "
                   "and #62's prime suspect is refuted"),
    ("heap_104", "live heap. Carried through a resave unread, with items and "
                 "without"),
)

#: DOS fields written as documented constants: `(name, bytes, why)`.  Each is
#: the one value all 24 specimens hold.
WRITE_CONSTANTS: tuple[tuple[str, bytes, str], ...] = (
    ("icon_dimension", b"\x01", "1 in all 24 DOS specimens"),
    ("field_83_87", b"\x00\x00\x01\x00\x00",
     "00 00 01 00 00 in all 24 DOS specimens"),
    ("strength_bonus", b"\x01", "1 in all 24 DOS specimens"),
    ("field_10c_10f", b"\x00\x01\x00\x00",
     "00 01 00 00 in all 24 DOS specimens"),
)

#: What :func:`write` does with every field `por/dos_layout.py` declares --
#: the *output-side* account, over DOS field names, where
#: :func:`write_field_disposition` accounts over the neutral vocabulary.
#: `tests/test_doswriter.py` fails if a field is declared in the layout and
#: named nowhere here, so a new field cannot be skipped in silence.
WRITE_TARGETS: dict[str, str] = (
    {dos_name: f"from neutral {n}" for n, dos_name in WRITE_DIRECT}
    | {"name_length": "from neutral name, the count byte",
       "name_text": "from neutral name, fifteen ASCII",
       "spells_memorised": "from neutral spells_memorised, reversed",
       "spellbook": "from neutral spells_known, one byte per id",
       "class_levels": "from neutral levels, permuted to class numbers",
       "spells_castable_cleric": "from neutral spells_castable['cleric']",
       "spells_castable_magic_user":
           "from neutral spells_castable['magic-user']",
       "size": "from neutral size_small, plus one",
       "attack_forms": "from neutral attack_forms, as a block",
       "roster_tail": "from neutral roster_tail, as a block",
       "item_count": "computed: the number of .ITM records written",
       "encumbrance": "computed: money plus item weight x quantity"}
    | {name: f"constant: {why}" for name, _, why in WRITE_CONSTANTS}
    | {name: f"zero: {why}" for name, why in WRITE_UNSOURCED}
)


#: Class name -> the DOS level slot with that number.  All eight have one --
#: DOS can hold the druid and monk levels the C64 cannot -- and only the
#: C64-only knight is left with nowhere to go.
_DOS_CLASS_SLOT: dict[str, int] = {name: n for n, name, _ in CLASS_LEVEL_SLOTS}

_COINS = ("copper", "silver", "electrum", "gold", "platinum", "gems",
          "jewelry")


def _encode(f: Field, rec: bytearray, value: Any) -> None:
    """The inverse of `_decode`, onto a mutable record."""
    if f.kind in (Kind.U8, Kind.I8):
        rec[f.offset] = int(value) & 0xFF
    elif f.kind in (Kind.U16LE, Kind.UINT_LE):
        rec[f.offset:f.end] = int(value).to_bytes(f.size, "little")
    else:
        data = bytes(value)
        if len(data) != f.size:
            raise DosRecordError(
                f"DOS field {f.name!r} is {f.size} bytes; got {len(data)}")
        rec[f.offset:f.end] = data


def write(char: NeutralCharacter) -> tuple[bytes, bytes, WriteReport]:
    """Build a 285-byte DOS record and its `.ITM` payload from a neutral
    character.

    The reverse of :func:`to_neutral`, and the writer #26 asked for: with it,
    C64 to DOS is `c64_codec.read` plus this, and nothing else.  Returns
    `(record, itm, report)`; the `.SPC` effects file is never written, because
    its 9-byte record is decoded only to the id byte -- see `WRITE_DROPPED`.

    Every byte of both outputs is justified in the report: it came from a
    neutral value, it was computed by a named rule, it is a documented
    constant, or it is a zero the report names as having no source --
    the live heap and the three unattributed runs, which the round-trip test
    masks *by this same list* rather than by whatever happened to differ.
    """
    rec = bytearray(RECORD_SIZE)
    rep = WriteReport()
    port = char.port
    w = neutral.Writer(char, rep, into="DOS", dropped=WRITE_DROPPED)
    use, emit = w.use, w.emit

    def put(v: neutral.Value, dos_name: str, extra: str = "",
            value: Any = None) -> None:
        f = FIELDS_BY_NAME[dos_name]
        val = v.value if value is None else value
        if f.kind is Kind.U8 and not 0 <= int(val) <= 0xFF:
            rep.warnings.append(
                f"{dos_name}: {val} does not fit the DOS one-byte field; "
                f"clamped")
            val = max(0, min(int(val), 0xFF))
        _encode(f, rec, val)
        emit(v, dos_name, f.offset, f.size, extra)

    # -- the name: one count byte, fifteen of ASCII --------------------------
    name = use("name")
    if name is not None:
        text = str(name.value)[:15].encode("ascii", "replace")
        if len(str(name.value)) > 15:
            rep.warnings.append(
                f"name {str(name.value)!r} is longer than the DOS fifteen "
                f"characters; truncated")
        rec[0x000] = len(text)
        rec[0x001:0x001 + len(text)] = text
        emit(name, "name_length/name_text", 0x000, 16,
             ", length-prefixed into one count byte and fifteen ASCII")

    # -- everything the two ports encode the same way ------------------------
    for neutral_name, dos_name in WRITE_DIRECT:
        v = use(neutral_name)
        if v is not None:
            put(v, dos_name)

    # -- the spellbook: one byte per spell, ids 1..56 -------------------------
    known = use("spells_known")
    if known is not None:
        book = bytearray(SPELLBOOK_SPELLS)
        for sid in known.value:
            if 1 <= int(sid) <= SPELLBOOK_SPELLS:
                book[int(sid) - 1] = 1
            else:
                rep.warnings.append(
                    f"spell id {sid} is outside the DOS book's ids 1-56")
        put(known, "spellbook", ", unpacked to one byte per spell",
            value=bytes(book))

    # -- memorised spells: sixteen slots, filled from the end ----------------
    memorised = use("spells_memorised")
    if memorised is not None:
        ids = [int(i) for i in memorised.value][:16]
        if len(memorised.value) > 16:
            rep.warnings.append(
                f"{len(memorised.value)} spells memorised and DOS has "
                f"sixteen slots; the rest dropped")
        put(memorised, "spells_memorised",
            " reversed -- DOS fills its sixteen slots from the end",
            value=bytes(16 - len(ids)) + bytes(reversed(ids)))

    # -- the per-class level array: indexed by the class number --------------
    levels = use("levels")
    if levels is not None:
        raw = bytearray(8)
        for cname, lv in levels.value.items():
            n = _DOS_CLASS_SLOT.get(cname)
            if n is None:
                if lv:
                    rep.warnings.append(
                        f"{port} carries {cname} level {lv}, and the DOS "
                        f"eight-slot array has no {cname} slot")
                continue
            raw[n] = min(int(lv), 0xFF)
        put(levels, "class_levels",
            ", permuted from class name to class number", value=bytes(raw))

    # -- spell slots: two three-byte runs ------------------------------------
    castable = use("spells_castable")
    if castable is not None:
        for school, dos_name in (
                ("cleric", "spells_castable_cleric"),
                ("magic-user", "spells_castable_magic_user")):
            triple = (tuple(castable.value.get(school, ())) + (0, 0, 0))[:3]
            put(castable, dos_name, f", the {school} run",
                value=bytes(min(int(n), 0xFF) for n in triple))

    # -- size: neutral 0 small / 1 large, DOS 1 small / 2 medium -------------
    size = use("size_small")
    if size is not None:
        put(size, "size", " plus one -- DOS stores 1 small / 2 medium",
            value=int(size.value) + 1)

    # -- two blocks the ports share byte for byte ----------------------------
    forms = use("attack_forms")
    if forms is not None:
        put(forms, "attack_forms", " copied as a block")
    tail = use("roster_tail")
    if tail is not None:
        put(tail, "roster_tail", " copied as a block")

    # -- the inventory becomes the .ITM file ---------------------------------
    itm = b""
    projected: list[bytes] = []
    inventory = use("inventory")
    if inventory is not None:
        projected = [bytes(i) for i in inventory.value]
        itm = b"".join(item_from_c64(i) for i in projected)
        if projected:
            emit(inventory, "the .ITM file", RECORD_SIZE, len(itm),
                 ", each sixteen-byte record unpacked onto the DOS 63")
            for n in range(len(projected)):
                base = RECORD_SIZE + n * ITEM_SIZE
                rep.note(base, 0x02A,
                         f"item {n}: the rendered-line cache, left empty -- "
                         f"the game rewrites it whenever it draws the list")
                rep.note(base + 0x02A, 4,
                         f"item {n}: next pointer left NULL -- the loader "
                         f"rebuilds the chain, measured by its own resave")

    # -- computed, not copied ------------------------------------------------
    count = min(len(projected), 0xFF)
    rec[FIELDS_BY_NAME["item_count"].offset] = count
    rep.note(FIELDS_BY_NAME["item_count"].offset, 1,
             f"item_count: computed -- the {count} records of the .ITM file")
    money = sum(int(w.get(k, 0)) for k in _COINS)
    weight = sum(int.from_bytes(i[8:10], "little") * (i[10] or 1)
                 for i in projected)
    _encode(FIELDS_BY_NAME["encumbrance"], rec,
            min(money + weight, 0xFFFF))
    rep.note(FIELDS_BY_NAME["encumbrance"].offset, 2,
             "encumbrance: computed -- money plus item weight x quantity, "
             "the identity the DOS engine itself uses")

    # -- documented constants ------------------------------------------------
    for cname, data, why in WRITE_CONSTANTS:
        f = FIELDS_BY_NAME[cname]
        rec[f.offset:f.end] = data
        rep.note(f.offset, f.size, f"{cname}: {why}")

    # -- bytes with no source: live heap and the unattributed ----------------
    for uname, why in WRITE_UNSOURCED:
        f = FIELDS_BY_NAME[uname]
        rep.note(f.offset, f.size, f"{uname}: zero -- {why}")

    # -- the gaps, zero in every specimen held -------------------------------
    for f in LAYOUT:
        if f.name.startswith("gap_"):
            rep.note(f.offset, f.size, f"{f.name}: zero ({f.note})")

    # -- the closing sweep: unwritten fields, then the reader's own drops ----
    w.finish()
    rep.total = RECORD_SIZE + len(itm)
    return bytes(rec), itm, rep


def write_field_disposition() -> dict[str, str]:
    """Every neutral field and what :func:`write` does with it.

    The DOS writer's twin of `por.c64_codec.field_disposition`, over the
    neutral vocabulary; `WRITE_TARGETS` is the same account over the DOS
    layout's own names, and the tests hold both complete.
    """
    return neutral.disposition(WRITE_DIRECT, WRITE_TRANSFORMED, WRITE_DROPPED,
                               "the DOS record's")


# ---------------------------------------------------------------------------
# The conversion, previewed as the plain data `por/yaml_io.py` writes
# ---------------------------------------------------------------------------
def export_party(folder: str | pathlib.Path, slot: str,
                 game_disk: str | None = None) -> dict[str, Any]:
    """A DOS save slot as the same plain data a C64 export produces.

    A **preview of the conversion**, not a raw view of the DOS files: the
    record is converted to the C64 first and the entry built off that, so what
    the document shows is what would land on the C64 disk, and each entry
    carries the conversion's own `_dropped` beside it.  That is why the extra
    hop through `por/c64_codec.py` is there and is not a detour.

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
        entry = entry_for(c64_codec.read(rec, source=str(folder)),
                          index, items=items,
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
#: **The byte map is `por/dos_savegame.py`'s and only its** (#64). This module
#: used to restate the base, the stride, the word accessor and the position
#: offsets, and the two copies had already begun to disagree about bounds
#: checking within one commit of the second existing. `dos_savegame` depends on
#: nothing but `struct`, so the edge runs this way and not the other.
#:
#: The persistent quest flags. `work/reports/quest-flags.md` gives all 352
#: bytes of $4A20-$4B7F a disposition; $4AF9 upwards is provably not flag
#: storage, so only this window transfers.
FLAGS_FIRST = dos_savegame.FLAGS_FIRST
FLAGS_LAST = dos_savegame.FLAGS_LAST


def quest_flags(save: bytes) -> bytes:
    """`$4A20`-`$4AF8` as the C64's 217 bytes: read the word, keep the byte.

    Every nonzero word in the window is 1, 2, 3 or 255 across three saves of
    two parties -- the flag alphabet, nothing wider -- and the runs the
    quest-flag report names are set and clear together.  A base off by one
    would straddle them.
    """
    out = bytearray()
    for addr in range(FLAGS_FIRST, FLAGS_LAST + 1):
        out.append(dos_savegame.word(save, addr) & 0xFF)
    return bytes(out)


def apply_quest_flags(save0: bytearray, savgam: bytes) -> int:
    """Copy the flags into a C64 `SAVEDGAME0` payload. Returns bytes changed.

    `SAVEDGAME0` is a verbatim image of `$4900`-`$64FF`, so the C64 offset of
    an address is the address less `$4900`.
    """
    flags = quest_flags(savgam)
    base = FLAGS_FIRST - SAVE0_BASE
    changed = sum(1 for i, b in enumerate(flags) if save0[base + i] != b)
    save0[base:base + len(flags)] = flags
    return changed


def apply_position(save0: bytearray, savgam: bytes) -> None:
    """Write the party's square and facing into `SAVEDGAME0`.

    The area is **not** written here.  `$4BC2` is slot 2 of the loaded-files
    cache, not a field beside it, so it belongs to `apply_file_cache` with the
    other twenty-four slots and the three bytes that make them findable.
    """
    x, y, facing = dos_savegame.position(savgam)
    save0[PARTY_X - SAVE0_BASE] = x
    save0[PARTY_Y - SAVE0_BASE] = y
    save0[PARTY_FACING - SAVE0_BASE] = facing


# ---------------------------------------------------------------------------
# The whole save
# ---------------------------------------------------------------------------
#: `SAVEDGAME0` is a verbatim image of `$4900`-`$64FF` and `SAVEDGAME1` of
#: `$8300`-`$8AFF`. Every offset below is an address less `$4900` (or `$8300`).
SAVE0_BASE = 0x4900
SAVE1_BASE = 0x8300
#: Where the C64 keeps the party's square -- `por/savegame.py`'s own names for
#: these, read here as offsets into a raw payload.
PARTY_X, PARTY_Y, PARTY_FACING = 0x49C0, 0x49C1, 0x49C2
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
#: The loaded-files cache: twenty-five slots, one per **file kind**, each
#: holding the two hex digits of the file of that kind the engine believes is
#: resident.  Slot 2 is `GEO`, which is why `$4BC2` is the area, and slot 8 is
#: `ECL`.  `docs/140-loaded-files-cache.md` has the whole table.
#:
#: `$FF` is "empty" and is the only value the load path leaves alone.  Bit 7 is
#: not data: `GEN $25DE` reads `LDA $4BC0,X / ORA #$80 / STA $6E13,X` for all
#: twenty-five, so whatever bit a save carries is discarded and set again.
#:
#: **Two slots are enough.**  `$FF` everywhere else, slot 2 = the area's `GEO`
#: number and slot 8 = the area id, and the arriving script's entry 4 refills
#: the rest -- CONFIRMED twice in the running game, once retargeting a New
#: Phlan save into Sokol Keep.  That is what lets a converted save stand
#: somewhere the template never did.
FILE_CACHE = (0x4BC0, 0x19)
FILE_CACHE_EMPTY = 0xFF
FILE_CACHE_RELOAD = 0x80
#: Which slot is which kind, for the two a converted save writes.
CACHE_GEO = 2
CACHE_ECL = 8
#: And the three a *DOS* save needs: slots 15-17 are the `WALLSET` pieces, and
#: the same three numbers are the DOS save's wallset triple at `$4AFA` -- the
#: Slums is (2,4,1) on both ports and Sokol Keep (1,5,9).  So the C64 save
#: being converted is the source, and no DOS table is needed.
CACHE_WALLSET = 15
CACHE_WALLSET_PIECES = 3
#: A masked slot reading `$7F` is empty -- `$FF` and `$7F` both mean "nothing
#: loaded" to `LIBRARY $4225`.
CACHE_UNSET = 0x7F

#: The disk hint.  `GEN $08BD` is `LDA $49EA / STA $6E12`, and `$6E12` is the
#: `POOL` side the loader asks for by number.  It is not part of the cache but
#: it is what makes the cache's entries findable: a save naming an area on
#: another disk and carrying the template's hint sits on `INSERT SIDE # N`
#: hunting a file that is not on the side it asked for.
DISK_HINT = 0x49EA
#: The map `LOADFILES` reloads into slot 2 indoors.
CURRENT_GEO = 0x49C5
#: The script id.  `CAMP $0D0B` copies it into cache slot 8 when it saves.
CURRENT_SCRIPT = 0x49F2
#: 1 indoors, 0 on the travel grid: `LOADFILES` picks the file *type* from it.
INDOORS = 0x49E6


#: The three refusals `apply_file_cache` raises, which reach the player through
#: the import dialog's generic handler. Donald's wording, approved 2026-08-24.
#: Each fires on where the *DOS* party stood, not on the C64 template -- and
#: none of them fires at all when the template already stands in that same
#: area, because then its own cache is real and is kept.
NOT_AN_AREA = ("the DOS party is in area {area}, which is not an area of Pool "
               "of Radiance, so there is no map file and no disk to name")
WILDERNESS = "Saves from wilderness locations are not yet supported."
UNSUPPORTED_LOCATION = "Saves from this location are not supported."


def apply_file_cache(save0: bytearray, savgam: bytes) -> str:
    """Point a `SAVEDGAME0` payload at the area the DOS party is standing in.

    Returns the one line the report puts against the cache, because which of
    the two things happened is exactly what a reader of the report wants to
    know:

    * the template already stands in that area, and its own cache -- a real
      one, written by the game -- is kept untouched;
    * or it does not, and the cache is rewritten to `$FF` in all twenty-five
      slots with slot 2 = the area's `GEO` number and slot 8 = the area id,
      plus the three bytes outside the cache that make those two findable:
      the disk hint `$49EA`, the map `$49C5` and the script id `$49F2`.

    The second is `docs/140-loaded-files-cache.md`'s recipe and is the shape
    both live tests used.  It refuses rather than guesses for three kinds of
    area: one this project has no row for, one whose script picks its map at
    run time or loads none at all, and the travel grid, where the cache uses
    slot 4 for `SQRDATA` in place of slot 2 and nothing has tested it.
    """
    at = FILE_CACHE[0] - SAVE0_BASE
    there = dos_savegame.area_id(savgam)
    here = save0[at + CACHE_GEO] & ~FILE_CACHE_RELOAD
    if here == there:
        return ("loaded-files cache: the template's own, untouched -- it "
                "stands where the DOS party stands, so it already names the "
                "right files")

    where = areas.area(there)
    if where is None:
        raise DosRecordError(NOT_AN_AREA.format(area=there))
    if where.outdoors:
        raise DosRecordError(WILDERNESS)
    if where.dynamic_geo or len(where.geos) < 1:
        raise DosRecordError(UNSUPPORTED_LOCATION)

    geo = areas.geo_number(where.geos[0])
    save0[at:at + FILE_CACHE[1]] = bytes([FILE_CACHE_EMPTY]) * FILE_CACHE[1]
    save0[at + CACHE_GEO] = geo
    save0[at + CACHE_ECL] = there
    save0[DISK_HINT - SAVE0_BASE] = where.disk
    save0[CURRENT_GEO - SAVE0_BASE] = geo
    save0[CURRENT_SCRIPT - SAVE0_BASE] = there
    save0[INDOORS - SAVE0_BASE] = 1
    return (f"loaded-files cache: $FF in all twenty-five, then slot 2 = "
            f"{where.geos[0]} and slot 8 = {where.ecl}; the arriving script "
            f"refills the rest")


def convert_save(folder: str | pathlib.Path, slot: str,
                 save0: bytearray, save1: bytearray | None = None,
                 keep_icons: bool = True) -> Report:
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
    there = dos_savegame.area_id(savgam)
    retargeted = save0[at + CACHE_GEO] & ~FILE_CACHE_RELOAD != there
    report.note(at, FILE_CACHE[1], apply_file_cache(save0, savgam))
    if retargeted:
        for address, what in (
                (DISK_HINT, "the POOL side the loader will ask for"),
                (CURRENT_GEO, "the map LOADFILES reloads"),
                (CURRENT_SCRIPT, "the script id"),
                (INDOORS, "indoors, which is where every convertible area is")):
            report.note(address - SAVE0_BASE, 1,
                        f"{what}, from the area the DOS party is in")

    changed = apply_quest_flags(save0, savgam)
    report.note(FLAGS_FIRST - SAVE0_BASE, FLAGS_LAST - FLAGS_FIRST + 1,
                "quest flags: the DOS word array, narrowed to bytes")
    apply_position(save0, savgam)
    for address, what in ((0x49C0, "party x"), (0x49C1, "party y"),
                          (0x49C2, "facing, the DOS value halved")):
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


# ---------------------------------------------------------------------------
# The whole save, the other way: a C64 save becomes DOS files (#26)
# ---------------------------------------------------------------------------
#: Where a retarget looks for `ECL<n>.DAX` when the caller names no game
#: directory: the save directory itself, then its parent, which is where the
#: archives keep it (`GAME/POOLRAD/SAVE` inside `GAME/POOLRAD`).
ECL_DAX = "ECL{dax}.DAX"


def c64_wall_triple(save0: bytes) -> tuple[int, int, int]:
    """The wallset triple a DOS save wants, out of the C64 loaded-files cache.

    Cache slots 15-17 hold the three `WALLSET` pieces, and the DOS save holds
    the same three numbers as words -- PORSAVE13's Slums (2,4,1) is DOS slot
    J's, PORSAVE's Sokol Keep (1,5,9) is slot B's.  An empty C64 slot becomes
    an empty DOS word.

    **New Phlan is the exception**: the C64 loads no `WALLSET` there at all
    and every slot reads `$FF`, where DOS slot A holds `(0, $FFFF, $FFFF)`.
    So this returns three empties for a New Phlan save, which is not what the
    DOS engine's own save says -- and is measured to draw the identical view
    anyway, `work/p60/run3` Z0.
    """
    at = FILE_CACHE[0] - SAVE0_BASE + CACHE_WALLSET
    out = []
    for b in save0[at:at + CACHE_WALLSET_PIECES]:
        v = b & ~FILE_CACHE_RELOAD & 0xFF
        out.append(dos_savegame.EMPTY if v == CACHE_UNSET else v)
    return tuple(out)


def retarget_reason(area: int) -> str | None:
    """Why this area cannot be a retarget target, or `None` if it can.

    The same three kinds the C64 converter refuses in the other direction: an
    area this project has no row for, one whose script picks its map at run
    time or loads none at all, and the travel grid, where no DOS specimen
    exists at all.  Unapproved wording, except `WILDERNESS`, which is
    Donald's and is reused verbatim.

    **An empty wallset triple is not a reason.**  New Phlan is the one area
    the C64 loads no `WALLSET` for, and a save retargeted there with all
    three words empty draws a view pixel-identical to one carrying DOS's own
    `(0, $FFFF, $FFFF)` -- `work/p60/run3`, Z0 against `run2`'s X3.
    """
    where = areas.area(area)
    if where is None:
        return (f"area {area} is not an area of Pool of Radiance, so there is "
                f"no map file and no script to name")
    if where.outdoors:
        return WILDERNESS
    if where.dynamic_geo or not where.geos:
        return UNSUPPORTED_LOCATION
    return None


def write_dos_save(save0: bytes, save1: bytes | None,
                   template: str | pathlib.Path, out: str | pathlib.Path,
                   slot: str = "A",
                   game: str | pathlib.Path | None = None) -> "SaveReport":
    """Write a C64 save into a DOS save directory.

    `save0` and `save1` are the C64 `SAVEDGAME0`/`SAVEDGAME1` payloads;
    `template` is an existing DOS save directory whose `SAVGAM<slot>.DAT`
    supplies the 8016 resident-state bytes nothing has attributed; `out` is
    where the new files go, and it must not be the player's own save
    directory -- the template is only ever read.  `game` is the DOS game
    directory, the one holding `ECL<n>.DAX`; with none given the template
    directory and its parent are tried, which is where the archives keep it.

    **The slot is cleared first.**  `CHRDAT<slot>1`-`6` and their `.ITM` and
    `.SPC` are removed from `out` before anything is written, so a party
    smaller than the one converted here last time does not arrive with the
    remainder of that one still in it (#68).  Only those eighteen names are
    touched; whatever else `out` holds is the user's.

    What is then written: `CHRDAT<slot><n>.SAV` for each character and its
    `.ITM` **only when the character carries something** -- a zero-length
    `.ITM` is not how the engine says "no items", it is how it says "one item,
    from whatever the heap held" (`ITM_OMITTED_WHEN_EMPTY`, #62) -- a `.SPC`
    never, and `SAVGAM<slot>.DAT` copied from the template and rewritten:

    * the quest flags, from the C64 bytes -- the two ports index them by the
      same ECL address;
    * **the clock** (#67), the same unconditional copy: six digit words at
      `$49C6`-`$49CB`, which are the C64's own six bytes at its own addresses;
    * **the party size** (#67), into both the word at `$503E` and byte 12808;
    * **the area** (#60), when the C64 party stands somewhere the template's
      party does not: every write `dos_savegame.RETARGET_WRITES` lists,
      including the target area's script lifted out of `ECL<n>.DAX`.  Without
      a game directory to lift it from, or for an area with no legal answer,
      the party keeps the template's square and the report says why.
    """
    from .items import items_for_slot
    from .savegame import SaveGame0, SaveGame1

    template = pathlib.Path(template)
    out = pathlib.Path(out)
    if out.resolve() == template.resolve():
        raise DosRecordError(
            "the output directory is the template; the template is read-only")
    out.mkdir(parents=True, exist_ok=True)

    # `slot` is interpolated straight into filenames and into the paths this
    # function *deletes*, and `pathlib`'s `/` splits an embedded separator into
    # components -- so a slot of `../../x` would unlink outside `out` entirely.
    # It is also written into the save as `slot.upper()` while the files on
    # disk take it verbatim, which on a case-insensitive filesystem produces a
    # save naming `CHRDATA1` beside a file called `CHRDATa1`. One check closes
    # both: the engine's own slots are a single letter.
    if len(str(slot)) != 1 or not str(slot).isalpha():
        raise DosRecordError(
            f"a save slot is a single letter, not {slot!r}")

    sg = SaveGame0.from_bytes(bytes(save0))
    sg1 = SaveGame1(bytes(save1)) if save1 is not None else None
    party = sg.characters
    if len(party) > 6:
        raise DosRecordError(
            f"a DOS save holds six characters; this save has {len(party)}")

    # Read the template's save before anything in `out` is touched: a missing
    # `SAVGAM<slot>.DAT` must fail with the slot still as the last conversion
    # left it, not half cleared.
    savgam = bytearray((template / f"SAVGAM{slot}.DAT").read_bytes())

    # The unit a conversion overwrites is the *slot*, not the characters this
    # party happens to fill.  Converting one character into a directory that
    # held six left `CHRDAT<slot>2`-`6` behind, and the engine loads the party
    # from the six filenames in `SAVGAM<slot>.DAT` (#59), so it read five
    # strangers back (#68).  Only the engine's own six names are removed, by
    # enumeration rather than by glob: nothing else in `out` is ours to touch.
    # **Every character is converted before anything in `out` is touched.**
    # The clear below removes the slot's six names, and a `write()` that
    # raises partway through the party -- `_encode` refuses a field whose
    # length is wrong -- would otherwise leave characters 1..N-1 replaced,
    # N..6 deleted and gone, and `SAVGAM<slot>.DAT` still naming all six. That
    # is #68's own failure reached through the write path instead of the
    # leftover path, and it is worse, because the save then names files that
    # are not there.
    report = SaveReport(total=0)
    built = []
    for char_slot in party:
        block = sg1.roster(char_slot.index) if sg1 is not None else None
        inv = [i.raw for i in items_for_slot(bytes(save0), char_slot.index)]
        char = c64_codec.read(char_slot.record, roster=block, inventory=inv,
                              source=f"C64 slot {char_slot.index}")
        rec, itm, one = write(char)
        built.append((char, rec, itm, one, char_slot))

    # The unit a conversion overwrites is the *slot*, not the characters this
    # party happens to fill.  Converting one character into a directory that
    # held six left `CHRDAT<slot>2`-`6` behind, and the engine loads the party
    # from the six filenames in `SAVGAM<slot>.DAT` (#59), so it read five
    # strangers back (#68).  Only the engine's own six names are removed, by
    # enumeration rather than by glob: nothing else in `out` is ours to touch.
    cleared = 0
    for n in range(1, dos_savegame.PARTY_ENTRIES + 1):
        stale = out / f"CHRDAT{slot}{n}"
        for suffix in (".SAV", ".ITM", ".SPC"):
            path = stale.with_suffix(suffix)
            if path.exists():
                path.unlink()
                cleared += 1

    if cleared:
        report.carried.append(
            f"slot {slot} was already written here: {cleared} stale "
            f"CHRDAT{slot}<n> file(s) from the previous party removed")
    for n, (char, rec, itm, one, char_slot) in enumerate(built, start=1):
        stem = out / f"CHRDAT{slot}{n}"
        stem.with_suffix(".SAV").write_bytes(rec)
        # A character carrying nothing gets **no `.ITM` file at all**, and an
        # empty one is not the same thing: the engine reads a zero-length
        # `.ITM` as one item of whatever the heap held, draws it on the sheet
        # (`WEAPON 254 PASSS`), and writes it into the save on the next resave.
        # See ITM_OMITTED_WHEN_EMPTY.  Nothing is unlinked here: the slot was
        # cleared above, so "not written" and "not present" are the same.
        if itm:
            stem.with_suffix(".ITM").write_bytes(itm)
        who = char.get("name", f"slot {char_slot.index}")
        report.dropped.extend(d for d in one.dropped
                              if d not in report.dropped)
        report.warnings.extend(f"{who}: {w}" for w in one.warnings)

    # The engine loads the party from the filenames in the save, not from the
    # slot letter it was loaded under (#59), so the save has to name the files
    # this call actually wrote.  A template whose `SAVGAM` was copied from
    # another slot carries that slot's letters and would load its party.
    dos_savegame.put_character_files(savgam, slot)
    report.carried.append(
        f"the party's filenames: CHRDAT{slot.upper()}1-"
        f"{dos_savegame.PARTY_ENTRIES}, which is what the engine loads from")
    for addr in range(FLAGS_FIRST, FLAGS_LAST + 1):
        dos_savegame.put_word(savgam, addr, save0[addr - SAVE0_BASE])
    report.carried.append(
        f"quest flags: {FLAGS_LAST - FLAGS_FIRST + 1} C64 bytes widened to "
        f"words at the same ECL addresses")

    # The clock and the party size are unconditional copies, like the flags.
    digits = [save0[dos_savegame.CLOCK + i - SAVE0_BASE]
              for i in range(dos_savegame.CLOCK_DIGITS)]
    dos_savegame.put_clock(savgam, digits)
    hour, minute, day, month = dos_savegame.clock(bytes(savgam))
    report.carried.append(
        f"the clock: {hour}:{minute:02d}, day {day} month {month} -- the "
        f"C64's own six digit bytes at $49C6-$49CB")
    dos_savegame.put_party_size(savgam, len(party))
    report.carried.append(
        f"the party size, {len(party)}, into both $503E and byte "
        f"{dos_savegame.PARTY_SIZE_BYTE}")

    x, y, facing = (save0[PARTY_X - SAVE0_BASE], save0[PARTY_Y - SAVE0_BASE],
                    save0[PARTY_FACING - SAVE0_BASE])
    c64_area = save0[CURRENT_SCRIPT - SAVE0_BASE]
    here = dos_savegame.area_id(bytes(savgam))
    if c64_area == here:
        dos_savegame.put_position(savgam, x, y, facing)
        report.carried.append(
            f"the square ({x},{y}) facing {facing}: both parties stand in "
            f"area {c64_area}, so nothing had to be retargeted")
    else:
        why = retarget_reason(c64_area)
        where = areas.area(c64_area)
        script = None
        if why is None:
            data = _read_ecl_dax(template, game, where.disk)
            if data is None:
                why = (f"no {ECL_DAX.format(dax=where.disk)} beside the "
                       f"template; a retarget needs the target area's own "
                       f"script and the game's files are the only copy")
            else:
                # A container that does not hold the block, or that unpacks
                # short, is a broken install rather than a bad conversion --
                # report it and leave the party where the template had it.
                try:
                    script = dos_savegame.dax_block(data, c64_area)
                except dos_savegame.DosSaveError as e:
                    why = f"{ECL_DAX.format(dax=where.disk)} is unreadable: {e}"
        if why is None:
            dos_savegame.retarget(savgam, area=c64_area, dax=where.disk,
                                  wallset=c64_wall_triple(save0),
                                  script=script)
            dos_savegame.put_position(savgam, x, y, facing)
            report.carried.append(
                f"the area: retargeted from {here} to {c64_area}, "
                f"{where.name}, at ({x},{y}) facing {facing}")
        else:
            report.warnings.append(
                f"the C64 party stands in area {c64_area} and the template's "
                f"DOS party in area {here}, and {why}; so the party will "
                f"stand on the template's square")
    (out / f"SAVGAM{slot}.DAT").write_bytes(bytes(savgam))
    return report


def _read_ecl_dax(template: pathlib.Path,
                  game: str | pathlib.Path | None, dax: int) -> bytes | None:
    """`ECL<n>.DAX` from the game directory, or from beside the template."""
    name = ECL_DAX.format(dax=dax)
    roots = [pathlib.Path(game)] if game else [template, template.parent]
    for root in roots:
        path = root / name
        if path.is_file():
            return path.read_bytes()
    return None


if __name__ == "__main__":  # pragma: no cover - convenience
    import sys

    from .yaml_io import to_yaml

    if len(sys.argv) < 3:
        print("usage: python3 -m por.dos <dos-save-dir> <slot> [game.d64]")
        raise SystemExit(2)
    print(to_yaml(export_party(sys.argv[1], sys.argv[2],
                               sys.argv[3] if len(sys.argv) > 3 else None)))
