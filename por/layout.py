"""Declarative field table for the Pool of Radiance (C64) character record.

This module is the *single source of truth* for the on-disk shape of a
character record.  Nothing else in the project may hard-code an offset:
decoders, documentation generators and (later) ImHex pattern emitters all
derive from :data:`LAYOUT`.

The C64 record is 580 bytes, stored uncompressed.  On disk it is preceded by
a 2-byte little-endian PRG load address (``$6B00``); that header is *not* part
of the record and is handled in :mod:`por.record`.

Adding a newly discovered field is a one-line edit: append a ``_field(...)``
entry to :data:`_DECLARED`.  Every byte not covered by a declared entry is
automatically filled in as an ``UNKNOWN`` region at import time, so the record
is always fully accounted for and overlaps are impossible to introduce
silently (:func:`_build` raises on overlap or out-of-range entries).

Confidence levels
-----------------
``CONFIRMED``  Verified against a real specimen (``tests/fixtures/brutus.chr``).
``PROBABLE``   Strong evidence, not yet verified end to end.
``GUESS``      Hypothesis worth testing; treat as unknown for any real purpose.
``UNKNOWN``    Explicitly not understood.  Bytes are preserved verbatim.

Nothing in this table is derived from published Gold Box hex-editing guides;
those describe the DOS record, which has a different layout.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field as _dc_field
from typing import Iterable, Iterator, Sequence

__all__ = [
    "RECORD_SIZE",
    "PRG_SIZE",
    "LOAD_ADDRESS",
    "NAME_SIZE",
    "Confidence",
    "Kind",
    "Field",
    "LAYOUT",
    "FIELDS_BY_NAME",
    "iter_fields",
    "field_by_name",
    "fields_with_confidence",
    "named_fields",
    "unknown_fields",
    "candidate_regions",
    "Coverage",
    "coverage",
    "format_coverage",
    "format_table",
]


#: Size of the character record proper, in bytes.
RECORD_SIZE = 580

#: Size of the record as stored in a PRG file (record + 2-byte load address).
PRG_SIZE = RECORD_SIZE + 2

#: Load address seen in ``brutus.chr``.  Informational only.
LOAD_ADDRESS = 0x6B00

#: Width of the character-name field.
NAME_SIZE = 20


class Confidence(enum.Enum):
    """How much we trust a field definition."""

    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    GUESS = "GUESS"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class Kind(enum.Enum):
    """How the bytes of a field are encoded."""

    #: Unsigned 8-bit integer.
    U8 = "u8"
    #: Unsigned 16-bit little-endian integer.
    U16LE = "u16le"
    #: Fixed-width, NUL-padded ASCII text (see :mod:`por.petscii`).
    ASCII_NUL = "ascii_nul"
    #: Opaque bytes, passed through untouched.
    RAW = "raw"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class Field:
    """One entry in the record layout.

    Attributes:
        offset: Byte offset from the start of the 580-byte record.
        size: Width in bytes.
        kind: Encoding (:class:`Kind`).
        name: Python identifier.  Named fields become attributes on
            :class:`por.record.CharacterRecord`.
        label: Human-readable label for dumps and documentation.
        confidence: :class:`Confidence` level.
        note: Free-form evidence / observation text.
        candidate: True for an explicitly declared unknown region that shows
            structure in a specimen and is worth investigating, as opposed to
            an auto-generated filler gap.
    """

    offset: int
    size: int
    kind: Kind
    name: str
    label: str
    confidence: Confidence
    note: str = ""
    candidate: bool = False

    @property
    def end(self) -> int:
        """Exclusive end offset."""
        return self.offset + self.size

    @property
    def is_known(self) -> bool:
        """True if this field claims a meaning (any confidence but UNKNOWN)."""
        return self.confidence is not Confidence.UNKNOWN

    @property
    def span(self) -> slice:
        return slice(self.offset, self.end)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.offset:#05x}+{self.size} {self.name} ({self.confidence})"


def _field(
    offset: int,
    size: int,
    kind: Kind,
    name: str,
    label: str,
    confidence: Confidence,
    note: str = "",
    candidate: bool = False,
) -> Field:
    return Field(offset, size, kind, name, label, confidence, note, candidate)


# Shorthands so the table below stays readable / one line per field.
_U8 = Kind.U8
_U16 = Kind.U16LE
_TXT = Kind.ASCII_NUL
_RAW = Kind.RAW
_OK = Confidence.CONFIRMED
_MAYBE = Confidence.PROBABLE
_GUESS = Confidence.GUESS
_NOPE = Confidence.UNKNOWN


# ---------------------------------------------------------------------------
# The table.  One line per field.  Everything else derives from this.
# ---------------------------------------------------------------------------
_DECLARED: Sequence[Field] = (
    # --- Confirmed by inspection of tests/fixtures/brutus.chr -------------
    _field(0x000, NAME_SIZE, _TXT, "name", "Name", _OK, "NUL-padded; 'BRUTUS'"),
    _field(0x014, 1, _U8, "strength", "STR", _OK, "18 in specimen"),
    _field(0x015, 1, _U8, "intelligence", "INT", _OK, "16 in specimen"),
    _field(0x016, 1, _U8, "wisdom", "WIS", _OK, "13 in specimen"),
    _field(0x017, 1, _U8, "dexterity", "DEX", _OK, "14 in specimen"),
    _field(0x018, 1, _U8, "constitution", "CON", _OK, "16 in specimen"),
    _field(0x019, 1, _U8, "charisma", "CHA", _OK, "13 in specimen"),
    _field(0x01A, 1, _U8, "exceptional_strength", "STR %", _OK, "98 -> '18/98'"),
    # --- Explicitly unknown, but non-zero in the specimen -----------------
    # These are *candidate regions only*.  No meaning has been established
    # for any byte below; the notes record raw observations, not conclusions.
    # --- Corroborated by an independent C64-native editor ------------------
    # "POR EDITOR V5" (Krulewitz) is a listable BASIC program that POKEs a
    # character file loaded at $6B00, so its offsets are C64-native, not DOS.
    # Every field below both matches that editor AND is independently
    # plausible in our specimen.  Two checks are near-unforgeable:
    #   * 0x9A-0x9E = [14,15,16,17,17], exactly the AD&D 1e L1 fighter
    #     saving-throw table;
    #   * 0xED (9) + CON 16 bonus (+2) = 11 = hp_max at 0x76.
    # Still PROBABLE, not CONFIRMED: none has yet survived our own
    # change-it-in-game-and-observe test.  Promote once an edit test covers them.
    _field(0x020, 16, _RAW, "spells_memorised", "Spells memorised", _MAYBE,
           "a packed list of memorised spell ids, highest spell level first. "
           "Ids are CONFIRMED against the game's own SPELLN00 table and "
           "against spells Donald memorised on purpose: 1 BLESS, 3 CURE LIGHT "
           "WOUNDS, 21 SLEEP. Cleric and magic-user ids fall in disjoint "
           "ranges; see por/spells.py. The roster block at +0x03/+0x04/+0x05 "
           "holds a per-level count that usually equals the number of non-zero "
           "bytes here, but NOT always: in PORSAVE4 the counts read 0/0/0 "
           "while this list is set, because the party memorised and had not "
           "yet rested. Length is unproven: the most seen in use is 13 bytes, "
           "and 0x02D-0x070 is zero in every specimen"),
    _field(0x078, 7, _RAW, "spells_known", "Spellbook", _OK,
           "a bitmask of the spells the character KNOWS, indexed by spell id: "
           "bit (id & 7) of byte 0x078 + (id >> 3). Confirmed on every caster "
           "we hold -- clerics know every spell of every level they can cast "
           "(8 at level 1, 24 at level 6) and magic-users know a subset, which "
           "is how AD&D 1st edition works. No cleric has a magic-user id set "
           "and no magic-user has a cleric one. MALCYON, a starting mage, "
           "knows detect magic, read magic, shield and sleep. Distinct from "
           "spells_memorised at 0x020, which is what is currently prepared"),
    _field(0x071, 1, _U8, "thac0_base", "THAC0 base (60 - value)", _MAYBE,
           "base THAC0, stored as 60 - THAC0, the same encoding the SAVEDGAME1 "
           "roster uses for the current value at +0x0E. Matches the AD&D 1st "
           "edition table for all twelve of Donald's characters and all six "
           "shipped on POOL1; the only three that differ are on the "
           "editor-hacked npc_party.d64. This was retired once as 'not THAC0' "
           "because MALCYON's sheet shows 20 where the byte reads 39 -- but 39 "
           "is 60-21, his base as a level-1 magic-user, and the 20 on screen "
           "is the current value after readying a dart. Base and current are "
           "different fields in different files"),
    _field(0x072, 1, _U8, "race", "Race", _OK,
           "1-based: DWARF=1 ELF=2 GNOME=3 HALF-ELF=4 HALFLING=5 HALF-ORC=6 "
           "HUMAN=7 MONSTER=8. BRUTUS/ZARRADA=7 human, LARA=2 elf. HALF-ORC "
           "is real but NPC-only: it is not on the character-creation menu, "
           "and the only two half-orcs in the game are the named NPCs MACE "
           "and NORRIS THE GRAY. GNOME and HALFLING have never been seen in "
           "any specimen, player or monster"),
    _field(0x073, 1, _U8, "char_class", "Class", _OK,
           "0-based, standard Gold Box order: CLERIC=0 DRUID=1 FIGHTER=2 "
           "PALADIN=3 RANGER=4 MAGIC-USER=5 THIEF=6 MONK=7. 0, 2 and 5 are "
           "verified by saving-throw tables; 6 is verified by the monster "
           "files, which contain NPCs literally named '1ST LVL THIEF' and "
           "'7TH LVL THIEF' carrying code 6. DRUID=1, PALADIN=3, RANGER=4 and "
           "MONK=7 appear in NO character anywhere -- not in twenty player "
           "characters, not in 108 monster records -- and Donald reports that "
           "paladin and ranger were left unfinished in the game data, so "
           "those four names rest on the Gold Box convention alone. "
           "Codes above 7 are multi-class: "
           "8 = cleric/fighter, 9 = cleric/fighter/magic-user, 10 and 11 = "
           "cleric/magic-user, 12 = cleric/thief, 13 = fighter/magic-user, "
           "14 = fighter/thief, 15 = fighter/magic-user/thief, 16 = "
           "magic-user/thief. That enumeration is the table the 1989 BASIC "
           "editor on poolce.d64 displays, and it agrees with all four "
           "multi-class codes we had already read off the bitmask at 0x0EB. "
           "Two caveats: the editor lists 3, 4 and 5 all as MAGIC-USER, which "
           "is its author's gap rather than the game's, and listing both 10 "
           "and 11 as cleric/magic-user looks like a slip in his table. "
           "class_bits stays the field to prefer"),
    _field(0x074, 2, _U16, "age", "Age", _OK,
           "16-bit LE; 21 for two humans, 176 for an elf -- long-lived, as expected"),
    _field(0x076, 1, _U8, "hp_max", "HP max", _MAYBE, "11 = 9 rolled + 2 CON"),
    _field(0x09A, 1, _U8, "save_paralysis", "Save vs para/poison/death", _OK,
           "fighter 14, cleric 10 -- both match the AD&D 1e L1 tables"),
    _field(0x09B, 1, _U8, "save_petrification", "Save vs petrify/polymorph", _OK, "fighter 15, cleric 13"),
    _field(0x09C, 1, _U8, "save_wands", "Save vs rod/staff/wand", _OK, "fighter 16, cleric 14"),
    _field(0x09D, 1, _U8, "save_breath", "Save vs breath weapon", _OK, "fighter 17, cleric 16"),
    _field(0x09E, 1, _U8, "save_spell", "Save vs spell", _OK, "fighter 17, cleric 15"),
    _field(0x09F, 1, _U8, "movement", "Movement", _OK, "12 in all three specimens"),
    _field(0x0A5, 1, _U8, "thief_pick_pockets", "Pick pockets %", _OK, "30 at L1"),
    _field(0x0A6, 1, _U8, "thief_open_locks", "Open locks %", _OK, "25 at L1"),
    _field(0x0A7, 1, _U8, "thief_find_traps", "Find/remove traps %", _OK, "20 at L1"),
    _field(0x0A8, 1, _U8, "thief_move_silently", "Move silently %", _OK, "20 at L1"),
    _field(0x0A9, 1, _U8, "thief_hide_in_shadows", "Hide in shadows %", _OK, "10 at L1"),
    _field(0x0AA, 1, _U8, "thief_hear_noise", "Hear noise %", _OK, "10 at L1"),
    _field(0x0AB, 1, _U8, "thief_climb_walls", "Climb walls %", _OK, "85 at L1"),
    _field(0x0AC, 1, _U8, "thief_read_languages", "Read languages %", _OK, "5 at L1"),
    _field(0x0BB, 2, _U16, "copper", "Copper", _OK,
           "set to 100 in the edit test and shown in the game (the thirteen-field edit)"),
    _field(0x0BD, 2, _U16, "silver", "Silver", _OK,
           "25-26 each after looting orcs, where it was 0 before"),
    _field(0x0BF, 2, _U16, "electrum", "Electrum", _OK,
           "set to 100 in the edit test and shown in the game (the thirteen-field edit)"),
    _field(0x0C1, 2, _U16, "gold", "Gold", _OK,
           "fell for all six when they bought equipment"),
    _field(0x0C3, 2, _U16, "platinum", "Platinum", _OK,
           "changed for three characters across a shopping trip"),
    _field(0x0C5, 2, _U16, "gems", "Gems", _OK,
           "set to 10 in the edit test and shown in the game (the thirteen-field edit)"),
    _field(0x0C7, 2, _U16, "jewelry", "Jewelry", _OK,
           "set to 10 in the edit test and shown in the game (the thirteen-field edit)"),
    _field(0x0E1, 1, _U8, "armour_class_base", "AC base (60 - AC)", _MAYBE,
           "base armour class, stored as 60 - AC, the same encoding used for "
           "THAC0 at 0x071 and for the current AC in the SAVEDGAME1 roster. It "
           "is 10 for every player character ever seen -- unarmoured, before "
           "dexterity -- which is why it looked like a constant. Monsters use "
           "the same record layout and put their real armour class here: "
           "kobold 7, orc 6, troll 4, zombie 8, matching the Monster Manual on "
           "all eight creatures checked"),
    _field(0x0E3, 5, _RAW, "region_0e3", "unknown @0x0E3", _NOPE,
           "between strength_index and experience. 0x0E4-0x0E7 is $FF FF FF "
           "FF in every NPC. Its first two bytes, 0x0E4-0x0E5, are $00 in "
           "every player character and belong to the eight-byte NPC marker -- "
           "0x0B7, 0x0B9, 0x0BA, 0x0D3, 0x0D4, 0x0E4, 0x0E5 and 0x0FB -- "
           "which reads $FF in all five NPCs of npc_party.d64 and $00 in all "
           "twenty known player characters. 0x0E6-0x0E7 are NOT part of it "
           "and were briefly miscounted as such: they hold a non-zero, "
           "high-entropy per-character value in every single player character, "
           "so they are not a 0/$FF pair. Whether one marker byte is the flag "
           "and the rest follow, or all eight are separate 'not applicable' "
           "sentinels, is unproven",
           candidate=True),
    _field(0x0E2, 1, _U8, "strength_index", "Effective STR", _MAYBE,
           "equals STR below 18; 18/80 and 18/81 give 21, 18/98 gives 22 -- the "
           "AD&D exceptional-strength bands collapsed to one number"),
    _field(0x0E8, 3, _RAW, "experience", "XP", _OK,
           "24-bit LE. After one orc fight the party holds 17 each and LADY "
           "KATHERINE 8 -- non-zero and differing, which is what confirms it"),
    _field(0x10F, 1, _U8, "armour_class", "AC current (60 - AC)", _MAYBE,
           "current armour class including armour, shield and dexterity, "
           "stored as 60 - AC. Present only in an exported .chr -- it lies "
           "beyond the 256 bytes a save slot stores -- and it agrees exactly "
           "with the SAVEDGAME1 roster's +0x0F for the same character: BRUTUS "
           "9, MALCYON 8, LADY KATHERINE 8. Base and current again, in "
           "different places"),
    _field(0x0ED, 1, _U8, "hp_rolled", "HP rolled", _MAYBE, "9; +2 CON = hp_max"),
    # --- Explicitly unknown regions (unchanged) ---------------------------
    _field(0x099, 1, _RAW, "region_099", "unknown @0x099", _NOPE,
           "01 0E 0F 10 11 11 0C 01 - six mid-teens values bracketed by 0x01",
           candidate=True),
    _field(0x0A0, 1, _U8, "level", "Level", _MAYBE,
           "character level. Two independent lines of evidence: the 1989 "
           "BASIC editor on poolce.d64 reads and pokes exactly this byte as "
           "LEVEL, and across the eight characters of npc_party.d64 it equals "
           "the character's per-class level at four distinct values (4, 6, 7, "
           "8). Every earlier specimen was level 1, which is why it long read "
           "as a constant 01. Not yet distinguishable from 'the single class's "
           "level' -- no multi-class specimen above level 1 has been seen"),
    # A four-entry level array, indexed in the same order as the class bits at
    # 0x0EB (magic-user, cleric, thief, fighter). Across all twelve specimens a
    # byte here is non-zero exactly when the corresponding class bit is set --
    # 12 for 12, including five multi-class characters.
    #
    # PROBABLE rather than CONFIRMED because every specimen is level 1, so the
    # values are all 1 and "level" is not yet distinguishable from "class
    # present". Donald's Gold Box Companion experience supports level: a human
    # thief changed to fighter became dual-classed, and as he levelled the
    # fighter entry rose while the thief entry stayed at 1.
    _field(0x0C9, 1, _U8, "level_magic_user", "Magic-user level", _MAYBE,
           "1 for every magic-user, 0 otherwise. One entry of the per-class "
           "level array -- how dual-classing keeps an old class frozen "
           "while a new one advances (the per-class levels)"),
    _field(0x0CA, 1, _U8, "level_cleric", "Cleric level", _MAYBE,
           "1 for every cleric, 0 otherwise. One entry of the per-class "
           "level array -- how dual-classing keeps an old class frozen "
           "while a new one advances (the per-class levels)"),
    _field(0x0CB, 1, _U8, "level_thief", "Thief level", _MAYBE,
           "1 for every thief, 0 otherwise. One entry of the per-class "
           "level array -- how dual-classing keeps an old class frozen "
           "while a new one advances (the per-class levels)"),
    _field(0x0CC, 1, _U8, "level_fighter", "Fighter level", _MAYBE,
           "1 for every fighter, 0 otherwise. One entry of the per-class "
           "level array (the per-class levels). Previously guessed to be an "
           "exceptional-strength flag, because the only fighters seen then "
           "were the only characters with exceptional strength"),
    _field(0x0D5, 1, _U8, "infravision", "Infravision (tens of feet)", _OK,
           "6 for every dwarf/elf/half-elf, 0 for every human, across 12 "
           "specimens -- i.e. 60 feet"),
    _field(0x0D6, 1, _U8, "sex", "Sex", _OK,
           "0 = male, 1 = female. LADY KATHERINE is 1 and confirmed female by "
           "Donald; LARA SPELLSWORD and ZARRADA are also 1"),
    _field(0x0D8, 1, _U8, "alignment", "Alignment", _OK,
           "0-based index into the game's own table at $32B3: LAWFUL GOOD=0 "
           "LAWFUL NEUTRAL=1 LAWFUL EVIL=2 NEUTRAL GOOD=3 TRUE NEUTRAL=4 "
           "NEUTRAL EVIL=5 CHAOTIC GOOD=6 CHAOTIC NEUTRAL=7 CHAOTIC EVIL=8. "
           "All six of Donald's characters decode to the alignment he chose"),
    _field(0x0D9, 8, _RAW, "region_0d9", "unknown @0x0D9", _NOPE,
           "03 02 00 01 00 02 00 00 - byte/zero alternation suggests 16-bit LE "
           "words. Shortened by one when 0x0E1 turned out to be the base "
           "armour class", candidate=True),
    _field(0x0EB, 1, _U8, "class_bits", "Class bitmask", _OK,
           "magic-user=1 cleric=2 thief=4 fighter=8, OR-ed together. This is "
           "how multi-class is really represented: LADY KATHERINE is 5 "
           "(magic-user/thief, confirmed by Donald) and LARA SPELLSWORD is 9 "
           "(magic-user/fighter -- her name says so). Far more usable than the "
           "single char_class code at 0x073"),
    _field(0x0FE, 3, _RAW, "region_0fe", "unknown @0x0FE", _NOPE,
           "08 07 01", candidate=True),
    _field(0x0EC, 1, _U8, "region_0ec", "unknown @0x0EC", _NOPE,
           "0 -> 1 after combat for MALCYON and LADY KATHERINE and nobody else "
           "-- exactly the two spellcasters, so probably spell state rather "
           "than damage. Zero in BRUTUS, so not flagged as a candidate region."),
    _field(0x11A, 2, _RAW, "region_11a", "unknown @0x11A", _NOPE,
           "0x11B is 12 in every specimen -- possibly a movement/encumbrance "
           "copy", candidate=True),
    _field(0x119, 1, _U8, "hp_current", "HP now", _MAYBE,
           "UNVERIFIED. Equals hp_max in every specimen, and no wounded "
           "character has ever been seen in an exported .chr, so it may simply "
           "be a second copy of hp_max. Note the hunt for current hit points searched both save files for "
           "a wounded character's current total and found nothing -- but this "
           "byte lies beyond the 256 a save slot stores, so it is only present "
           "in an export and that search does not settle it"),
    _field(0x10D, 2, _RAW, "region_10d", "unknown @0x10D", _NOPE,
           "08 2A - two bytes before the current armour class", candidate=True),
    _field(0x110, 9, _RAW, "region_110", "unknown @0x110", _NOPE,
           "30 00 00 01 00 02 00 05 00 - an ascending 16-bit LE sequence "
           "1,2,5,... in an export; the item area in a save", candidate=True),
    _field(0x220, 36, _RAW, "region_220", "unknown @0x220 (record tail)", _NOPE,
           "E4 A0 02 6B 04 05 06 07 08 20 A0 0B 20 0D E9 06 10 11 00 0F 08 0E"
           " 0E 08 0E 0E 0E 0E 0F 08 0E 0E 00 0E 0E 0E - densest region in the"
           " specimen; runs to the final byte of the record", candidate=True),
)


def _build(declared: Iterable[Field]) -> tuple[Field, ...]:
    """Sort declared fields, validate them, and fill gaps with UNKNOWN entries.

    Raises:
        ValueError: on an out-of-range, zero-width or overlapping declaration.
    """
    ordered = sorted(declared, key=lambda f: f.offset)
    out: list[Field] = []
    cursor = 0
    for f in ordered:
        if f.size <= 0:
            raise ValueError(f"field {f.name!r} has non-positive size {f.size}")
        if f.offset < 0 or f.end > RECORD_SIZE:
            raise ValueError(
                f"field {f.name!r} at {f.offset:#x}+{f.size} escapes the "
                f"{RECORD_SIZE}-byte record"
            )
        if f.offset < cursor:
            raise ValueError(
                f"field {f.name!r} at {f.offset:#x} overlaps the previous field"
            )
        if f.offset > cursor:
            out.append(_gap(cursor, f.offset - cursor))
        out.append(f)
        cursor = f.end
    if cursor < RECORD_SIZE:
        out.append(_gap(cursor, RECORD_SIZE - cursor))
    return tuple(out)


def _gap(offset: int, size: int) -> Field:
    return Field(
        offset=offset,
        size=size,
        kind=Kind.RAW,
        name=f"gap_{offset:03x}",
        label=f"unallocated @{offset:#05x}",
        confidence=Confidence.UNKNOWN,
        note="not yet examined",
        candidate=False,
    )


#: The complete layout: every one of the 580 bytes belongs to exactly one entry.
LAYOUT: tuple[Field, ...] = _build(_DECLARED)

#: Lookup by field name.
FIELDS_BY_NAME: dict[str, Field] = {f.name: f for f in LAYOUT}

assert sum(f.size for f in LAYOUT) == RECORD_SIZE, "layout does not tile the record"
assert len(FIELDS_BY_NAME) == len(LAYOUT), "duplicate field name in layout"


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------
def iter_fields() -> Iterator[Field]:
    """Yield every field in offset order."""
    return iter(LAYOUT)


def field_by_name(name: str) -> Field:
    """Return the field called *name*.

    Raises:
        KeyError: if no such field exists.
    """
    try:
        return FIELDS_BY_NAME[name]
    except KeyError:
        raise KeyError(f"no field named {name!r} in the record layout") from None


def fields_with_confidence(level: Confidence) -> tuple[Field, ...]:
    """All fields at exactly *level*."""
    return tuple(f for f in LAYOUT if f.confidence is level)


def named_fields() -> tuple[Field, ...]:
    """Fields that have a claimed meaning (CONFIRMED / PROBABLE / GUESS)."""
    return tuple(f for f in LAYOUT if f.is_known)


def unknown_fields() -> tuple[Field, ...]:
    """Fields we do not understand."""
    return tuple(f for f in LAYOUT if not f.is_known)


def candidate_regions() -> tuple[Field, ...]:
    """Unknown regions explicitly flagged as worth investigating."""
    return tuple(f for f in LAYOUT if f.candidate)


@dataclass(frozen=True)
class Coverage:
    """Byte counts per confidence level."""

    total: int
    by_confidence: dict[Confidence, int] = _dc_field(default_factory=dict)

    @property
    def confirmed(self) -> int:
        return self.by_confidence.get(Confidence.CONFIRMED, 0)

    @property
    def probable(self) -> int:
        return self.by_confidence.get(Confidence.PROBABLE, 0)

    @property
    def guess(self) -> int:
        return self.by_confidence.get(Confidence.GUESS, 0)

    @property
    def unknown(self) -> int:
        return self.by_confidence.get(Confidence.UNKNOWN, 0)

    @property
    def known(self) -> int:
        return self.total - self.unknown

    def percent(self, level: Confidence) -> float:
        return 100.0 * self.by_confidence.get(level, 0) / self.total


def coverage() -> Coverage:
    """Report how many of the 580 bytes are understood."""
    counts: dict[Confidence, int] = {level: 0 for level in Confidence}
    for f in LAYOUT:
        counts[f.confidence] += f.size
    return Coverage(total=RECORD_SIZE, by_confidence=counts)


def format_coverage() -> str:
    """Human-readable coverage summary."""
    cov = coverage()
    lines = [f"record size: {cov.total} bytes"]
    for level in Confidence:
        n = cov.by_confidence.get(level, 0)
        lines.append(f"  {level.value:<9} {n:4d} bytes  ({cov.percent(level):5.1f}%)")
    lines.append(f"  {'known':<9} {cov.known:4d} bytes  "
                 f"({100.0 * cov.known / cov.total:5.1f}%)")
    return "\n".join(lines)


def format_table(include_gaps: bool = True) -> str:
    """Render the layout as a fixed-width text table (documentation source)."""
    rows = LAYOUT if include_gaps else named_fields() + candidate_regions()
    rows = sorted(rows, key=lambda f: f.offset)
    header = f"{'offset':>7} {'size':>4} {'kind':<9} {'confidence':<10} {'name':<22} label"
    lines = [header, "-" * len(header)]
    for f in rows:
        lines.append(
            f"{f.offset:#07x} {f.size:>4} {f.kind.value:<9} "
            f"{f.confidence.value:<10} {f.name:<22} {f.label}"
        )
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - convenience
    print(format_table())
    print()
    print(format_coverage())
