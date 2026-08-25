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

No offset in this table comes from a published Gold Box hex-editing guide.
Those describe the DOS record, which is a different record -- 285 bytes for
Pool of Radiance against the C64's 580, growing to 510 by *Pools of Darkness*.
Where a note below cites the DOS layout it is as **corroboration of a reading
we measured ourselves**, never as the source of an offset:
`docs/127-community-formats.md` works out where the two records line up and
where they do not, and says which claims the community documentation earned.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from dataclasses import field as _dc_field
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
    #: Signed 8-bit integer, two's complement. Thief skills use it: a
    #: halfling's read-languages sits at -5, stored as 251.
    I8 = "i8"
    #: Unsigned 16-bit little-endian integer.
    U16LE = "u16le"
    #: Unsigned little-endian integer of whatever width the field declares.
    #: `U16LE` was always width-generic in the codec -- it encodes with
    #: `f.size` -- so this is the same machinery under an honest name, for the
    #: 24-bit experience total.
    UINT_LE = "uint_le"
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
_I8 = Kind.I8
_U16 = Kind.U16LE
_UINT = Kind.UINT_LE
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
    _field(0x020, 16, _RAW, "spells_memorised", "Spells memorized", _MAYBE,
           "a packed list of memorised spell ids, highest spell level first. "
           "Ids are CONFIRMED against the game's own SPELLN00 table and "
           "against spells Donald memorised on purpose: 1 BLESS, 3 CURE LIGHT "
           "WOUNDS, 21 SLEEP. Cleric and magic-user ids fall in disjoint "
           "ranges; see por/spells.py. The roster block's +0x03/+0x04/+0x05 "
           "were read as a per-level count of this list, because they matched "
           "it for all eight characters of npc_party.d64. That reading is "
           "RETRACTED: in PORSAVE4 they read 0/0/0 while this list is set, on "
           "a save taken after resting. Length is unproven: the most seen in "
           "use is 13 bytes, and 0x02D-0x070 is zero in every specimen.\n"
           "**Sixteen is probably five short.** The DOS record allots 21 "
           "slots for the same list, and 21 is also this game's ceiling: a "
           "cleric 6 with wisdom 18 has 13 and a magic-user 6 has 8, and one "
           "character can be both. The C64 packs the list **forward** from "
           "0x020 in descending spell id where DOS fills its 21 in reverse. "
           "SIMON (cleric 6, slots 5/5/3) fills 0x020-0x02C with three "
           "third-level ids, five second and five first, every one in a "
           "cleric range; XAVIER (magic-user 6, 4/2/2) fills eight bytes with "
           "magic-user ids only. Nothing we hold contradicts 16 and nothing "
           "supports stopping there -- PROBABLE at 21. Settle it with a "
           "cleric/magic-user carrying more than sixteen memorised spells. "
           "docs/127-community-formats.md"),
    _field(0x078, 7, _RAW, "spells_known", "Spellbook", _OK,
           "a bitmask of the spells the character KNOWS, indexed by spell id: "
           "bit (id & 7) of byte 0x078 + (id >> 3). Confirmed on every caster "
           "we hold -- clerics know every spell of every level they can cast "
           "(8 at level 1, 24 at level 6) and magic-users know a subset, which "
           "is how AD&D 1st edition works. No cleric has a magic-user id set "
           "and no magic-user has a cleric one. MALCYON, a starting mage, "
           "knows detect magic, read magic, shield and sleep. Distinct from "
           "spells_memorised at 0x020, which is what is currently prepared. "
           "Bit 0 of 0x078 is deliberately unused: the QUANTUM LEAPER "
           "trainer's LEARN ALL SPELLS writes $FE here and $FF to the other "
           "six, i.e. spell id 0 does not exist.\n"
           "**Seven bytes is Pool of Radiance's width, not the engine's**, and "
           "the field stops here because seven is what this game reads and "
           "what por/spells.py encodes. The later titles continue into "
           "spells_known_high at 0x07F; each title's width is "
           "por.spells.SpellTable.spellbook_size, measured in that title's "
           "own code. docs/127-community-formats.md"),
    _field(0x07F, 9, _RAW, "spells_known_high", "Spellbook (high ids)", _OK,
           "the rest of the spellbook bitmask, for the titles whose spell list "
           "outgrew 56. The same indexing continued -- byte 0x078 + (id >> 3) "
           "-- so 0x07F carries ids 56-63 and 0x087 ids 120-127. **Zero "
           "throughout Pool of Radiance**: no character in any Pool of "
           "Radiance save sets even 0x07F, which is why this read as a gap for "
           "so long. It is declared beside spells_known rather than folded "
           "into it so that the seven bytes this game uses stay their own "
           "field: every writer in the project encodes seven, and widening "
           "the field would silently change what they write.\n"
           "Per title, each measured in that game's own code and not carried "
           "across from another: **Pool of Radiance 7 (CONFIRMED)** -- 56 bits "
           "for a 56-spell list, of which id 56 RESTORATION has no bit, and "
           "the QUANTUM LEAPER trainer writes exactly seven. **Curse of the "
           "Azure Bonds 13 (CONFIRMED)** -- CAMP $5225 builds the memorise "
           "list by walking spell ids from 1 with INY / CPY #$65 / BCC, so it "
           "stops after id 100, and reads the mask as TYA / LSR x3 / TAX / "
           "LDA $7C78,X; id 100 puts X at 12, so the game itself reads "
           "0x078-0x084. GEN $2D4A writes there too, ORing $E0 into $7C81 and "
           "$01 into $7C82 to grant the four first-level druid spells 77-80. "
           "Whether 0x085-0x087 are also mask in Curse is UNKNOWN -- its GEN "
           "has no clear loop. **Secret of the Silver Blades 16 (CONFIRMED)** "
           "-- GEN $41DC clears sixteen bytes (LDX #$0F / LDA #$00 / "
           "STA $7C78,X / DEX / BPL), GEN $50C9 walks the same sixteen, and "
           "CAMP $6071 is Curse's memorise loop with its ceiling moved to "
           "CPY #$76, id 117, reaching 0x086.\n"
           "**The near-miss, written down so it is not walked into twice**: "
           "Curse's GEN $2C2F copies 32 bytes out of $7C78 and looks like "
           "proof of a sixteen-byte mask. Pool of Radiance's GEN $296B copies "
           "the identical 32 out of $6B78, where the mask is seven. A copy "
           "wider than the field says nothing about the field. "
           "tests/test_curse.py and tests/test_silverblades.py pin all three "
           "readings."),
    _field(0x071, 1, _U8, "thac0_base", "THAC0 base (60 - value)", _OK,
           "base THAC0, stored as 60 - THAC0, the same encoding the SAVEDGAME1 "
           "roster uses for the current value at +0x0E. Matches the AD&D 1st "
           "edition table for all twelve of Donald's characters and all six "
           "shipped on POOL1; the only three that differ are on the "
           "editor-hacked npc_party.d64. This was retired once as 'not THAC0' "
           "because MALCYON's sheet shows 20 where the byte reads 39 -- but 39 "
           "is 60-21, his base as a level-1 magic-user, and the 20 on screen "
           "is the current value after readying a dart. Base and current are "
           "different fields in different files.\n"
           "**CONFIRMED**: the trainer rewrote it at every one of twenty-nine "
           "level-ups, always to the row of the game's own table at GEN $1F1F "
           "and, for a multi-class character, to the best of its classes -- "
           "GEN $1EF3 keeps a value only when it beats what is already there. "
           "docs/119-test-party.md"),
    _field(0x072, 1, _U8, "race", "Race", _OK,
           "1-based: DWARF=1 ELF=2 GNOME=3 HALF-ELF=4 HALFLING=5 HALF-ORC=6 "
           "HUMAN=7 MONSTER=8. BRUTUS/ZARRADA=7 human, LARA=2 elf. HALF-ORC "
           "is real but NPC-only: it is not on the character-creation menu, "
           "and the only two half-orcs in the game are the named NPCs MACE "
           "and NORRIS THE GRAY. Two values outside that list matter. **0 is "
           "the commonest race in the game**, carried by 75 of the 135 "
           "distinct monster records -- every generic creature and some "
           "humanoid NPCs -- so it reads as 'not applicable' rather than as a "
           "race, and a 0 is not evidence that a record was tampered with. "
           "**8 (MONSTER) is used by nothing anywhere**, player or monster: "
           "the table enumerates it and the game never instantiates it, the "
           "same way it names DRUID, PALADIN, RANGER and MONK"),
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
    _field(0x076, 2, _U16, "hp_max", "HP max", _OK,
           "16-bit LE. 11 = 9 rolled + 2 CON. The high byte was long read as filler because no character has yet exceeded 255 hit points; the drain routine in SPELLE02 decrements the pair, which is what settles the width"),
    _field(0x09A, 1, _U8, "save_paralysis", "Save vs para/poison/death", _OK,
           "fighter 14, cleric 10 -- both match the AD&D 1e L1 tables.\n"
           "All five saves at 0x09A-0x09E are now **derivable**, which "
           "por/levels.py's docstring says they were not: the stored number is "
           "the class table row for the character's level in that class, taking "
           "the **best number in each column** across every class it holds, "
           "minus the AD&D constitution bonus (+1 per 3.5 points) when the "
           "character is a **dwarf, gnome or halfling**. 78 of the 79 distinct "
           "records on this machine satisfy that exactly; the one miss is MAD "
           "MAN, a level-8 NPC carrying the level-1 fighter row. The multi-class "
           "rule shows on its own: LADY KATHERINE (magic-user 1 / thief 1) reads "
           "13 12 11 15 12, which is neither class's row but the column-wise "
           "minimum of the two. The racial adjustment shows as a uniform shift "
           "-- MAGNUS the dwarf (CON 13) is 3 lower than an identical human "
           "fighter in Donald's own party, and HOGARTH and TANARAKIS on "
           "SSI's shipped demo party agree with no adjustment at all. Only "
           "the +3/+4/+5 bands are exercised and the high-level cases all "
           "come from npc_party.d64, whose values this project treats as "
           "worthless (docs/90), so tests/test_communityformats.py asserts "
           "the rule on the fixtures alone, which are clean. "
           "docs/127-community-formats.md"),
    _field(0x09B, 1, _U8, "save_petrification", "Save vs petrify/polymorph", _OK, "fighter 15, cleric 13"),
    _field(0x09C, 1, _U8, "save_wands", "Save vs rod/staff/wand", _OK, "fighter 16, cleric 14"),
    _field(0x09D, 1, _U8, "save_breath", "Save vs breath weapon", _OK, "fighter 17, cleric 16"),
    _field(0x09E, 1, _U8, "save_spell", "Save vs spell", _OK, "fighter 17, cleric 15"),
    _field(0x09F, 1, _U8, "movement", "Movement", _OK, "12 in all three specimens"),
    _field(0x0A5, 1, _I8, "thief_pick_pockets", "Pick pockets %", _OK,
           "30 at L1. The eight percentages at 0x0A5-0x0AC come from a "
           "nine-level table of eight columns in the engine, in this order, "
           "plus a racial row: HOGARTH, a dwarf thief 1, matches the base row "
           "plus the AD&D dwarf adjustments in all eight columns, including "
           "read languages -5 stored as $FB, and takes no dexterity adjustment "
           "at dexterity 17. The half-elf, gnome and halfling specimens do not "
           "match their published racial rows, so **how the C64 applies the "
           "racial modifier is UNKNOWN**; the per-level progression is not. "
           "docs/127-community-formats.md"),
    _field(0x0A6, 1, _I8, "thief_open_locks", "Open locks %", _OK, "25 at L1"),
    _field(0x0A7, 1, _I8, "thief_find_traps", "Find/remove traps %", _OK, "20 at L1"),
    _field(0x0A8, 1, _I8, "thief_move_silently", "Move silently %", _OK, "20 at L1"),
    _field(0x0A9, 1, _I8, "thief_hide_in_shadows", "Hide in shadows %", _OK, "10 at L1"),
    _field(0x0AA, 1, _I8, "thief_hear_noise", "Hear noise %", _OK, "10 at L1"),
    _field(0x0AB, 1, _I8, "thief_climb_walls", "Climb walls %", _OK, "85 at L1"),
    _field(0x0AC, 1, _I8, "thief_read_languages", "Read languages %", _OK, "5 at L1"),
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
    _field(0x0B8, 1, _U8, "flags_0b8", "Flags", _OK,
           "bit 7 is the real 'this is an NPC or a monster' flag, and bit 0 "
           "records that an ability score was altered at the trainer. "
           "npc_party.d64 splits three players from five NPCs exactly on bit "
           "7; the code counts player characters with it and enforces CMP #$06, "
           "which is the six-PC party limit in code rather than in anecdote; "
           "NPC money is zeroed by it. Bit 0 is set by GEN $155D straight "
           "after INC/DEC $6B14,X and cleared again if the change is "
           "cancelled. **Nothing anywhere reads bit 0 back**, so the forum "
           "rumour that altering a score carries a penalty in play has no code "
           "behind it on this port"),
    _field(0x0E1, 1, _U8, "armour_class_base", "AC base (60 - AC)", _MAYBE,
           "base armour class, stored as 60 - AC, the same encoding used for "
           "THAC0 at 0x071 and for the current AC in the SAVEDGAME1 roster. It "
           "is 10 for every player character ever seen -- unarmoured, before "
           "dexterity -- which is why it looked like a constant. Monsters use "
           "the same record layout and put their real armour class here: "
           "kobold 7, orc 6, troll 4, zombie 8, matching the Monster Manual on "
           "all eight creatures checked. The DOS record names AC_Base at the "
           "offset this one aligns to, between the eight attack-form bytes and "
           "the per-character value that precedes experience -- corroboration, "
           "not proof, and the Monster Manual check is the stronger of the "
           "two"),
    _field(0x0E3, 5, _RAW, "region_0e3", "unknown @0x0E3", _NOPE,
           "between strength_index and experience. 0x0E4-0x0E7 is $FF FF FF "
           "FF in every NPC. Its first two bytes, 0x0E4-0x0E5, are $00 in "
           "every player character and belong to the eight-byte NPC marker -- "
           "0x0B7, 0x0B9, 0x0BA, 0x0D3, 0x0D4, 0x0E4, 0x0E5 and 0x0FB -- "
           "which reads $FF in all five NPCs of npc_party.d64 and $00 in all "
           "twenty known player characters. 0x0E6-0x0E7 are NOT part of it "
           "and were briefly miscounted as such: they hold a non-zero, "
           "high-entropy per-character value in every single player character, "
           "so they are not a 0/$FF pair. The DOS record has a single "
           "high-entropy per-character byte in the same place, immediately "
           "before experience, which its community documentation calls "
           "MON_Index -- so whatever the pair is, both ports carry it. Whether one marker byte is the flag "
           "and the rest follow, or all eight are separate 'not applicable' "
           "sentinels, is unproven",
           candidate=True),
    _field(0x0E2, 1, _U8, "strength_index", "Effective STR", _MAYBE,
           "equals STR below 18; 18/80 and 18/81 give 21, 18/98 gives 22 -- the "
           "AD&D exceptional-strength bands collapsed to one number. The DOS "
           "record has a boolean STR_Bonus at the aligned offset, reading 1 in "
           "all 66 DOS specimens; this byte holds 15-22 across ours, so they "
           "are two different fields and this reading stands"),
    _field(0x0E8, 3, _UINT, "experience", "XP", _OK,
           "24-bit LE. After one orc fight the party holds 17 each and LADY "
           "KATHERINE 8 -- non-zero and differing, which is what confirms it"),
    _field(0x10F, 1, _U8, "armour_class", "AC current (60 - AC)", _MAYBE,
           "current armour class including armour, shield and dexterity, "
           "stored as 60 - AC. Present only in an exported .chr -- it lies "
           "beyond the 256 bytes a save slot stores -- and it agrees exactly "
           "with the SAVEDGAME1 roster's +0x0F for the same character: BRUTUS "
           "9, MALCYON 8, LADY KATHERINE 8. Base and current again, in "
           "different places"),
    _field(0x0ED, 1, _U8, "hp_rolled", "HP rolled", _OK,
           "the accumulated hit-die rolls, without the constitution bonus. "
           "hp_max at 0x076 is this plus level x the bonus, recomputed from "
           "here at every training -- so this is the stored half and hp_max "
           "the derived one, not the other way round. GEN $2037 adds one roll "
           "of the class hit die (GEN $20A7: d4, d8, d6, d10 in class-bit "
           "order) and GEN $2079 writes hp_max from it. Confirmed on "
           "twenty-nine trainings across four classes and three constitution "
           "scores; the roll itself is a die and derives from nothing"),
    # --- Explicitly unknown regions (unchanged) ---------------------------
    _field(0x099, 1, _U8, "size_small", "Size", _MAYBE,
           "0 small, 1 large -- the only two the game offers, and the two its "
           "ALTER > ICON > SIZE menu shows. The only byte in the "
           "stored 256 that separates dwarves, gnomes and halflings from "
           "humans, elves and half-elves -- the AD&D size categories exactly. "
           "This is the icon large/small flag the Gold Box Companion exposes. "
           "Donald confirmed MAGNUS, a dwarf, shows as small in game, and that "
           "the visible difference is the head: a small character's body is "
           "the same size and its head is smaller, which is why the icon looks "
           "small without being smaller. 0 for every dwarf, gnome and halfling "
           "and 1 for every elf, half-elf and human in all 79 records we hold. "
           "The DOS record splits this in two -- an icon *dimension* (1 = one "
           "square) at the offset this one aligns to and an icon *size* "
           "(1 small, 2 medium) much later -- and the C64 byte sits at the "
           "first offset carrying the second meaning, one lower. Which is why "
           "the DOS documentation cannot be transcribed onto this byte"),
    _field(0x0A0, 1, _U8, "level", "Level", _OK,
           "character level. Promoted from PROBABLE on the game's own data: "
           "**twenty-one shipped MON* records state their level in their "
           "name**, and 0x0A0 agrees with the name in nineteen of them -- 1ST "
           "LVL THIEF 1, 2ND LVL CLERIC 2, LEVEL 3 MU 3, 4TH LVL FIGHTER 4, "
           "LEVEL 5 CLERIC 5, 6TH LVL FIGHTER 6, 7TH LVL DW FIGHTER 7, 8TH LVL "
           "FIGHTER 8. The two that differ are both 6TH LVL THIEF (MON33, "
           "MON5D), where the byte reads 7 **and so does the per-class array**, "
           "so the disagreement is between the designer's label and his data "
           "rather than between two fields. Corroborated three further ways: "
           "the 1989 BASIC editor on poolce.d64 and the QUANTUM LEAPER machine-"
           "code trainer both poke exactly this byte as LEVEL; across the eight "
           "characters of npc_party.d64 it equals the per-class level at four "
           "distinct values; and docs/80 reads the drain routine writing it "
           "down from the per-class array. Every early specimen was level 1, "
           "which is why it long read as a constant 01. Still not "
           "distinguishable from 'the single class's level' -- no multi-class "
           "specimen above level 1 has been seen"),
    _field(0x0A1, 1, _U8, "levels_drained", "Levels drained", _OK,
           "how many levels undead have drained, not a second copy of the "
           "level. The pair is current-plus-delta, which is why no 'true "
           "level' was ever found. SPELLE02 computes hp_max / total levels, "
           "loops that many times doing DEC $6B76 / DEC $6BED / INC $6BA2 / "
           "DEC $6C19, then INC $6BA1 and DEC $6BC9,X. RESTORATION in "
           "SPELLE04 reverses it exactly and prints string 94, which "
           "SPELLN00 gives as IS RESTORED"),
    _field(0x0A2, 1, _U8, "hp_lost_to_drain", "HP lost to drain", _OK,
           "hit points removed by level drain, restored alongside 0x0A1"),
    _field(0x0A3, 1, _U8, "turn_class", "Undead turning class", _OK,
           "which row of the AD&D 1e turning table a creature answers to. "
           "Non-zero in exactly twelve of the 121 distinct MON* records, every "
           "one undead, and it matches the published table on all of them: "
           "skeleton 1, zombie 2, ghoul 3, wight 5, wraith 7, mummy 8, "
           "spectre 9, vampire 10, with giant skeleton 8 and juju zombie 9. "
           "Eleven are named creatures; the twelfth is FERRAN MARTINEZ "
           "(MON13), an NPC carrying 9, the spectre row. **This offset was "
           "challenged and it survived.** "
           "docs/116 read the neighbouring 0x0A4 as the turning field because "
           "0x0A3 is zero in every *player* specimen of either game -- which it "
           "is, because no player character is undead. Across the monster "
           "records the two are disjoint: 0x0A3 is non-zero only on undead and "
           "0x0A4 only on clerics, and no record sets both. They are two "
           "fields, one per side of the same rule"),
    _field(0x0A4, 1, _U8, "turn_power", "Turn undead (caster side)", _OK,
           "the caster's half of turning, sitting beside the undead's half at "
           "0x0A3. Non-zero in eight of the eleven records carrying the cleric "
           "class bit and in nothing else -- ACOLYTE and 1ST LVL CLERIC 1, 2ND "
           "LVL CLERIC 2, MACE 4, CURATE and WILLIAM D'OR and DIRTEN 6 -- plus "
           "the player cleric ROLAND at 1. docs/116 sees the same population in "
           "Curse: 6 for its level-5 cleric, 3 for its level-5 paladin, zero "
           "for everyone else. What the *number* means is not settled and is "
           "not the cleric's level: three level-5 clerics read 1, 4 and 6, and "
           "7TH LVL CLERIC reads 0.\n"
           "**CONFIRMED, and the value is a table lookup rather than the "
           "level.** GEN $2388 writes it from the fourteen bytes at $2399, "
           "indexed by the cleric level: 1 2 3 5 6 7 8 9 10 10 10 10 10 12. "
           "That is the row of the AD&D turning table the cleric reads, which "
           "is why it skips 4. ROLAND's six cleric trainings moved this byte "
           "every time and never moved 0x0A3, which is what separates the two "
           "fields. docs/119-test-party.md"),
    _field(0x0AD, 10, _RAW, "item_effects", "Character Traits", _MAYBE,
           "ten trait slots -- racial abilities and readied passive items. "
           "**Not the save's active effects**, which is what this field was "
           "called until P3-EFFECTS.D64 was saved with twenty-six spells "
           "running and every character's ten slots came out exactly as they "
           "went in. Nothing here has a duration and nothing here expires; "
           "the running effects are four 64-entry arrays in SAVEDGAME0 "
           "(docs/133-active-effects.md). The two share one code namespace, "
           "which is why one table names both. **The namespace is named**: "
           "the DOS guide enumerates ids 1-127 and por/traits.py carries the "
           "whole table, 44 of them CONFIRMED because a MON* record or a saved "
           "item carries the id on exactly the creature or item its meaning "
           "demands -- AHNKHEG 121 'anhkheg acid squirt', TROLL 100 and 101, "
           "WIGHT 96 'silver or magic' against WRAITH 123 'silver does half', "
           "which is the Monster Manual distinction between them. The rest are "
           "PROBABLE: the guide names them and no C64 record exercises them. "
           "Three overlays loop LDX #$09 "
           "over it, and XAVIER carrying 107 in the first slot and 89 in the "
           "tenth proves the extent. GEN $0BF3 seeds it per race from the "
           "table [1, 0, 107, 0, 124, 0, 0, 0], **indexed by the race byte "
           "itself**: race is 1-based, so elf (2) is born with 107 and half-elf "
           "(4) with 124, and the leading 1 sits at index 0 where no created "
           "character reaches it. That retires the old reading of the 1 as a "
           "dwarf's seed -- MAGNUS, a dwarf, has an empty trait block.\n"
           "It shares storage with item byte +14 -- SPELLE04 $ADD4 copies a "
           "readied passive item's +14 verbatim into a free slot -- and shares "
           "its meaning only for **passive** items, which item byte +15 bit 7 "
           "marks. CLOAK OF DISPLACEMENT reads +14 89 / +15 $85 and 89 is "
           "'displaced'; TWO-HANDED SWORD +1 +3 VS UNDEAD reads 3 / $88 and 3 "
           "is 'wielding an undead-slaying weapon'. A consumable's +14 is a "
           "spell id instead: POTION OF HEALING reads 85 / $00 and 85 is a "
           "level drain only in the effect table"),
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
    _field(0x0C9, 1, _U8, "level_magic_user", "Magic-user level", _OK,
           "1 for every magic-user, 0 otherwise. One entry of the per-class "
           "level array -- how dual-classing keeps an old class frozen "
           "while a new one advances (the per-class levels).\n"
           "**The array is permuted between the ports and a save converter "
           "must permute it back.** The C64 indexes 0x0C9-0x0D0 by the bit "
           "number in class_bits -- magic-user, cleric, thief, fighter, druid, "
           "monk, paladin, ranger -- and DOS indexes the same eight bytes by "
           "the class number at 0x073: cleric, druid, fighter, paladin, "
           "ranger, magic-user, thief, monk. Six specimens settle the C64 "
           "side: MALCYON (class 5, magic-user) fills slot 0, ROLAND (class 0, "
           "cleric) slot 1, BRUTUS (class 2, fighter) slot 3, and LADY "
           "KATHERINE (class 16, magic-user/thief) slots 0 and 2. A converter "
           "that copies the array straight across turns every cleric into a "
           "druid.\n"
           "**CONFIRMED**: twenty-nine trainings raised exactly the entry of "
           "the class trained and no other, and LADY KATHERINE ended "
           "magic-user 6 / thief 9 with two different non-zero entries -- "
           "which is what separates this array from 'the single class's "
           "level'. docs/119-test-party.md"),
    _field(0x0CA, 1, _U8, "level_cleric", "Cleric level", _OK,
           "1 for every cleric, 0 otherwise. One entry of the per-class "
           "level array -- how dual-classing keeps an old class frozen "
           "while a new one advances (the per-class levels)"),
    _field(0x0CB, 1, _U8, "level_thief", "Thief level", _OK,
           "1 for every thief, 0 otherwise. One entry of the per-class "
           "level array -- how dual-classing keeps an old class frozen "
           "while a new one advances (the per-class levels)"),
    _field(0x0CC, 1, _U8, "level_fighter", "Fighter level", _OK,
           "1 for every fighter, 0 otherwise. One entry of the per-class "
           "level array (the per-class levels). Previously guessed to be an "
           "exceptional-strength flag, because the only fighters seen then "
           "were the only characters with exceptional strength"),
    # The array is eight slots, not four: 0x0C9-0x0D0, indexed by the bit
    # number in class_bits. Pool of Radiance uses slots 0-3 and leaves the rest
    # zero in every specimen, which is why they read as a gap for so long.
    _field(0x0CD, 1, _U8, "level_knight",
           "Class-level slot 4 (druid; knight in the Krynn titles)", _MAYBE,
           "slot 4 of the per-class level array, i.e. class_bits bit 4 (16). "
           "**In the Realms titles this is the druid slot.** The engine's own "
           "item-restriction bit array -- the same bit order this array is "
           "indexed by -- reads 0 magic-user, 1 cleric, 2 thief, 3 fighter, 4 "
           "druid, 5 monk, 6 paladin, 7 ranger. Bits 0-3 are CONFIRMED here "
           "from six specimens and bits 6-7 from Curse's pre-generated paladin "
           "and ranger, so six of the eight positions are checked and the two "
           "left over are druid and monk in that order. Pool of Radiance never "
           "instantiates a druid, so the byte is zero in every specimen we "
           "hold; the name of the slot is PROBABLE and the *ordering* that "
           "puts druid in it is CONFIRMED.\n"
           "The field keeps the name `level_knight` because the Death Knights "
           "of Krynn editor calls it that -- it cycles nine class names over "
           "the eight-byte array at 0x0C9 as MAGE, CLERIC, THIEF, FIGHTER, "
           "KNIGHT, -, PALADIN, RANGER, and bounds the array with CPY #$08. "
           "Knights of Solamnia are a Krynn class in a world with no druids, "
           "so the Krynn games reuse the slot. The shipped Champions and Death "
           "Knights parties carry class_bits 0x10 with the whole array zero, "
           "so no record has yet shown a value in this byte on any title"),
    _field(0x0CF, 1, _U8, "level_paladin", "Paladin level", _OK,
           "slot 6 of the per-class level array, class_bits bit 6 (64). "
           "CONFIRMED on SSI's own pre-generated Curse party, whose paladin "
           "holds 0x0CF = 5 with class_bits = 64 (docs/116 sec 2.3). Zero in "
           "every Pool of Radiance specimen -- the game names PALADIN in its "
           "class table and never instantiates one"),
    _field(0x0D0, 1, _U8, "level_ranger", "Ranger level", _OK,
           "slot 7 of the per-class level array, class_bits bit 7 (128). "
           "CONFIRMED on Curse's pre-generated ranger, 0x0D0 = 5 with "
           "class_bits = 128. Silver Blades and Death Knights use both this "
           "slot and the paladin one; Pool of Radiance leaves both zero"),
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
    _field(0x0D9, 8, _RAW, "attack_forms", "Attack forms", _OK,
           "the two attack forms, as four parallel two-entry arrays: attacks "
           "per round **doubled** at 0x0D9, damage dice at 0x0DB, die at "
           "0x0DD, signed modifier at 0x0DF, each holding form 0 then form 1. "
           "COMBAT $0CAD rolls damage through LDA $6C13,Y / LDX $6C15,Y with a "
           "stride of 2, which is what proves there are exactly two forms, and "
           "twenty creatures match the Monster Manual: GHOUL 04 02 / 01 01 / "
           "03 06 is two 1d3 claws and a 1d6 bite, TROLL 04 02 / 01 02 / 04 06 "
           "/ 04 00 is two 1d4+4 claws and a 2d6 bite. A form with no damage "
           "dice is not an attack. Decoded in por/monster.py; kept as one raw "
           "block here because the character sheet has no use for eight "
           "separate monster fields.\n"
           "This region read UNKNOWN for a long while on a note recording the "
           "specimen as '03 02 00 01 00 02 00 00', which was said to contradict "
           "the attacks reading because BRUTUS, a one-attack level-1 fighter, "
           "appeared to hold 3. **That note was off by one**: it was a dump of "
           "0x0D8-0x0E0, and the leading 03 is the alignment byte at 0x0D8. "
           "BRUTUS reads 02 00 01 00 02 00 00 00 -- one attack per round for "
           "1d2 unarmed, exactly what GEN $0BBE writes and what the reading "
           "predicts. The contradiction never existed.\n"
           "Independently corroborated: the DOS record spells the same eight "
           "bytes out in the same order at the offset this one aligns to -- "
           "attack count, dice count, die, modifier, each as a two-entry array "
           "of form 0 then form 1 -- and every C64 player character reads "
           "02 00 01 00 02 00 00 00"),
    _field(0x0EB, 1, _U8, "class_bits", "Class bitmask", _OK,
           "magic-user=1 cleric=2 thief=4 fighter=8, OR-ed together. This is "
           "how multi-class is really represented: LADY KATHERINE is 5 "
           "(magic-user/thief, confirmed by Donald) and LARA SPELLSWORD is 9 "
           "(magic-user/fighter -- her name says so). Far more usable than the "
           "single char_class code at 0x073"),
    _field(0x0EE, 6, _RAW, "spells_castable", "Spells castable", _OK,
           "how many spells of each level the character may memorise, one byte "
           "per spell level, **nibble-packed**: cleric in the high nibble, "
           "magic-user in the low. ROLAND, a level-1 cleric with wisdom 16, "
           "reads $30 -- three first-level spells, one base plus two for "
           "wisdom, which is exactly what his sheet allows. MALCYON and LADY "
           "KATHERINE, both level-1 magic-users, read $01. The three fighters "
           "read zero throughout. Found while surveying Curse of the Azure "
           "Bonds, which uses the same offsets; the docs had this down as not "
           "stored anywhere.\n"
           "Promoted from PROBABLE on three further lines (docs/127). "
           "**Multi-class specimens set both nibbles at once**, which no "
           "single-class specimen can distinguish from two separate bytes: "
           "TANARAKIS (cleric 1 / magic-user 1) and DELILIA (cleric 1 / "
           "fighter 1 / magic-user 1) both read $31. The wisdom bonus is exact "
           "at level 6, where the base row is no longer 1: DIRTEN, cleric 6 "
           "with wisdom 16, reads 5/5/2 -- AD&D's 3/3/2 plus +2/+2/+0 -- and "
           "SIMON, cleric 6 with wisdom 18, reads 5/5/3. Fifteen casters "
           "across nine parties agree; the one exception is DELILIA, wisdom 13 "
           "with three first-level slots where the rule gives two, which is "
           "what a cache not recomputed on an ability change looks like. And "
           "the DOS record carries the same six quantities as six separate "
           "bytes -- SPL_Count_CL_1..3 then SPL_Count_MU_1..3 at DOS 0x0B2 -- "
           "in the position this offset aligns to; 66 real DOS records agree. "
           "0x0F1-0x0F3 are spell levels 4-6 and are zero in all 79 C64 "
           "records, which is what a game that stops at third-level spells "
           "should look like"),
    _field(0x0FE, 1, _U8, "portrait_head", "Portrait head", _OK,
           "index into the HEAD* files on the game disks, in hex: 0x2D is "
           "HEAD2D. All eleven values across our exports name a file that "
           "exists, and the odds of that happening by chance are negligible -- "
           "the ids used include $2D, $43, $44 and $67, not just small numbers. "
           "BRUTUS carries the same pair on two unrelated disks, and the two "
           "female half-elves share a portrait"),
    _field(0x0FF, 1, _U8, "portrait_body", "Portrait body", _OK,
           "index into the BODY* files, the same way. Head and body are "
           "adjacent and independent"),
    _field(0x100, 1, _U8, "roster_in_use", "Roster in use", _MAYBE,
           "record 0x100-0x11F **is** the SAVEDGAME1 roster block. An exported "
           ".chr and the roster page agree in 31 of those 32 bytes for every "
           "character, differing only at 0x10D. Two agents reached that "
           "independently -- one from LIBRARY $3189/$319A, which copies "
           "$8300 + N*$20 in and out, the other from matching exports against "
           "saves by name. So a record is four blocks the game saves "
           "separately: 256 + 32 + 256 + 36 = 580.\n"
           "This byte is roster +0x00, and the combat research saw it go $01 "
           "-> $84 when a monster died.\n"
           "All three of 'the sir' editors -- for Curse, Silver Blades and "
           "Death Knights -- make this byte their first field and call it "
           "**STATUS**, cycling 1 OK, 2 GONE, 3 DEAD, 4 DYING, 5 UNCONSCIOUS, "
           "6 RUNNING, 7 STONED. Every specimen of either game reads 01, which "
           "is consistent, and the enumeration gives the combat observation a "
           "reading at last: $84 & 0x0F = 4 = DYING, with bit 7 as a separate "
           "flag. The name here stays roster_in_use until a specimen reads "
           "something other than 1 or the game is watched writing one, because "
           "three tools sharing one author's table is one source, not three.\n"
           "A fourth source **weakens** the case rather than strengthening it. "
           "The community format documentation for the DOS games carries a "
           "CharacterStatus enumeration -- 0 Okay, 1 Animated, 2 tempgone, "
           "3 Running, 4 Unconscious, 5 Dying, 6 Dead, 7 Stoned, 8 Gone -- "
           "and puts it at DOS 0x10C, which is roster +0x0A, not +0x00. Its "
           "numbering is 0-based where the sir editors' cycle is 1-based, and "
           "the two orders differ. So the enum is real and its position on the "
           "C64 is not settled by anything outside. Still PROBABLE"),
    _field(0x0EC, 1, _U8, "region_0ec", "unknown @0x0EC", _NOPE,
           "0 -> 1 after combat for MALCYON and LADY KATHERINE and nobody else "
           "-- exactly the two spellcasters, so probably spell state rather "
           "than damage. Went 1 -> 3 for MALCYON alone in PORSAVE11, where "
           "LADY KATHERINE also cast a spell and hers did not move, so it is "
           "not simply a count of spells cast. Zero in BRUTUS, so not flagged "
           "as a candidate region."),
    _field(0x11B, 1, _U8, "roster_movement", "Movement (roster)", _MAYBE,
           "roster +0x1B, the movement rate as encumbered. Long recorded as "
           "'12 in every specimen', which held only because every specimen was "
           "the same six characters: PORSAVE10's exports read 9 in banded "
           "mail"),
    _field(0x119, 2, _U16, "hp_current", "HP now", _OK,
           "16-bit LE, and genuinely current hit points rather than a second "
           "copy of the maximum: GEN $0BD0 initialises it from hp_max, and "
           "both the trainer and the drain routine move it independently "
           "afterwards. It equals hp_max in every specimen only because no "
           "wounded character has yet been exported. Note it lies beyond the "
           "256 bytes a save slot holds, so it exists in an export and not in "
           "a save"),
    _field(0x10D, 1, _U8, "party_order", "Party order", _MAYBE,
           "the only byte where an export and the roster block disagree, and "
           "across a six-character party the export values form a complete 0-5 "
           "permutation -- so it is marching order at the moment of export. In "
           "a roster block the same byte is the record slot index, which is "
           "how the combat code finds a combatant's record; 8 means not in a "
           "party"),
    _field(0x10E, 1, _U8, "thac0", "THAC0 current (60 - value)", _MAYBE,
           "current THAC0 including strength and the readied weapon, stored as "
           "60 - THAC0, sitting immediately before the current armour class at "
           "0x10F. Matches the AD&D table on all eleven exports we hold. Like "
           "0x10F it exists only in an export, and it agrees with the "
           "SAVEDGAME1 roster's +0x0E for the same character -- so an exported "
           ".chr does carry both combat numbers after all, which is worth "
           "knowing given the 1989 editor's author reported he could never "
           "find either"),
    _field(0x110, 9, _RAW, "roster_tail", "Roster +0x10..+0x18", _MAYBE,
           "roster +0x10 the armour bonus, then +0x11 to +0x18 the **current "
           "attack form** -- the running copy of attack_forms at 0x0D9, in the "
           "engine's own order: two attack counts, two dice counts, two die "
           "sizes, two damage bonuses. All decoded in por/savegame.py, and "
           "kept RAW here because the roster is the place to read them.\n"
           "The die-size byte is +0x15, which this project called EQUIPMENT "
           "for a long time because it 'rises with what is readied'. It does: "
           "across thirteen of Donald's save disks it reads 3 for MALCYON's "
           "dart, 6 for LADY KATHERINE's short sword, 6 for ROLAND's mace, 8 "
           "for three long swords and 2 for every character with nothing "
           "readied -- 1d3, 1d6, 1d6+1, 1d8 and the unarmed 1d2, matched to "
           "the ITEMS table entry of the item each of them had equipped.\n"
           "The first byte does NOT line up with DOS: DOS spends it on armour "
           "class from behind and the C64 on the armour bonus, 48 + bonus, "
           "which por/savegame.py established by putting armour on (none 48, "
           "leather 50, banded 54, the AD&D bonuses exactly, and unmoved by a "
           "shield). Read the C64 byte the DOS way and those become 12, 10 and "
           "6, two worse than each armour's real class and meaning nothing. "
           "docs/127-community-formats.md"),
    # --- Declared from the later games, zero throughout this one -----------
    _field(0x065, 7, _RAW, "abilities_second", "Abilities (second copy)", _OK,
           "a second copy of the seven ability scores -- STR, INT, WIS, DEX, "
           "CON, CHA, exceptional STR -- mirroring 0x014-0x01A. CONFIRMED in "
           "Curse: all six of SSI's pre-generated characters carry it and the "
           "import routine writes it (docs/116 sec 2.2). Death Knights moved "
           "its editor's ability fields here rather than to 0x014. Seven zeroes "
           "in every Pool of Radiance specimen. **Which of the two arrays the "
           "game treats as current is not established** -- they are equal in "
           "every specimen, and MacGyver's Curse trainer writes both because he "
           "did not know either"),
    _field(0x098, 1, _U8, "attack_level", "Fighting level", _OK,
           "the level the attack tables are indexed by, which is not always "
           "the character level: 5 for Curse's level-5 paladin and ranger, 4 "
           "for its level-5 fighter/thief, 0 for pure casters, 1 for an "
           "imported level-1 fighter. CONFIRMED in docs/116 sec 2.2, and it "
           "matches the DOS record's attackLevel at the same place in the "
           "cluster, where the community documentation calls it LVL_Sweep -- "
           "the AD&D rule that lets a fighter make one attack per level "
           "against creatures under one hit die, which is what a separate "
           "'level the attack tables are indexed by' is for. It reads the "
           "fighter level on every high-level fighter we hold (MAD MAN 8, GRON "
           "7, two others 4) and zero on every level-1 one. Zero in every "
           "Pool of Radiance player specimen"),
    _field(0x120, 256, _RAW, "inventory", "Items carried", _OK,
           "sixteen item slots of sixteen bytes, which is por/items.py's "
           "ITEM_SIZE and ITEMS_PER_CHARACTER and the same 16 x 16 page the "
           "save file gives each character at $5900 + slot * $100. The "
           "shopping trip decoded the slot format field by field; slot +0 zero "
           "means empty, +4 is the plus and +10 the quantity. Pinning the "
           "extent here matters because it leaves 0x11C-0x11F **outside** the "
           "item area and outside the roster block, which ends at 0x11B -- four "
           "bytes still unaccounted for. Kept RAW because por/items.py is where "
           "an item is read"),
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
