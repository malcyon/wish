"""Read a DOS Pool of Radiance save, and turn one into a C64 one.

**One direction only.** `wish` never writes a DOS file: the DOS side of this
module is read-only, so the DOS format has to be decoded only as far as
sourcing what the C64 needs, and any DOS field with no C64 counterpart can be
dropped -- provided it is *reported* rather than dropped silently, which is
what `Report` is for.

    DOS character file  ->  to_neutral  ->  NeutralCharacter
                                          ->  c64_codec.write  ->  C64 record

The middle is `por/neutral.py`'s typed record, and this module is the DOS
*reader* of that pair -- the only half that knows a DOS offset.  Writing the
C64 record is `por/c64_codec.py`'s, and the two never mention each other.
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

import pathlib
import struct
from typing import Any, Sequence

from . import areas, c64_codec, neutral, traits
from .c64_codec import Report
from .dos_layout import (
    EFFECT_SIZE,
    FIELDS_BY_NAME,
    ITEM_FIELDS_BY_NAME,
    ITEM_SIZE,
    RECORD_SIZE,
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
    "apply_file_cache",
    "convert_save",
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
    out.set("name", dos.name, "re-padded from the DOS count byte at 0x000",
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
    out.set("spells_memorised", dos.spells_memorised, "DOS 0x01C reversed",
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
    """Write the party's square and facing into `SAVEDGAME0`.

    The area is **not** written here.  `$4BC2` is slot 2 of the loaded-files
    cache, not a field beside it, so it belongs to `apply_file_cache` with the
    other twenty-four slots and the three bytes that make them findable.
    """
    x, y, facing = position(savgam)
    save0[0x49C0 - SAVGAM_BASE] = x
    save0[0x49C1 - SAVGAM_BASE] = y
    save0[0x49C2 - SAVGAM_BASE] = facing


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
    there = area_id(savgam)
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
    retargeted = save0[at + CACHE_GEO] & ~FILE_CACHE_RELOAD != area_id(savgam)
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


if __name__ == "__main__":  # pragma: no cover - convenience
    import sys

    from .yaml_io import to_yaml

    if len(sys.argv) < 3:
        print("usage: python3 -m por.dos <dos-save-dir> <slot> [game.d64]")
        raise SystemExit(2)
    print(to_yaml(export_party(sys.argv[1], sys.argv[2],
                               sys.argv[3] if len(sys.argv) > 3 else None)))
