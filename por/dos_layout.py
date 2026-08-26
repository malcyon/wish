"""Declarative field table for the DOS Pool of Radiance character record.

`por/layout.py` is this module's model and its sibling: same `Field`, same
`Confidence`, same rule that every byte of the record belongs to exactly one
entry so an overlap cannot be introduced silently.  What differs is the
record.  The DOS one is **285 bytes** to the C64's 580, and it is *rearranged
rather than translated*.  Both directions read this table now: `por/dos.py`
decodes a DOS record through it and, since #26, encodes one too -- the
player's own files are still never written to.

Where the offsets come from
---------------------------
Every entry below was measured against **24 real specimens** -- 18 characters
in three played save slots and 6 exported `.CHA` files -- from Donald's Steam
copy of *Forgotten Realms: The Archives*.  `work/reports/dos-saves.md` is the
working, `tests/test_dossave.py` and `tests/test_dosconvert.py` are the
assertions, and `docs/117-save-conversion.md` is the plan the table serves.
Nothing here is transcribed from a hex-editing guide: the community notes in
`work/coab-research/formats/` predicted nine of these fields and were right
about all nine, which is corroboration and is said as much in the notes.

Three shapes worth knowing before reading the table
---------------------------------------------------
* **The name is length-prefixed**, not NUL-padded: one count byte then up to
  15 ASCII.  The C64 spends 20 NUL-padded bytes on the same field, which is
  the whole of the four-byte displacement between the two layouts' early
  fields.
* **The spellbook is one byte per spell**, 56 of them, where the C64 packs 56
  *bits*.  The ordering turns out to be identical -- see `SPELLBOOK`.
* **The per-class level array is indexed by the class number**, where the
  C64's eight slots are indexed by the class *bit*.  Same width, different
  meaning per slot; `por/dos.py` carries the permutation.

Live-only state
---------------
The DOS engine saves its heap with the record.  Several `u16le` values in
`0x0C1`-`0x0FF` and `0x104`-`0x10B` are far pointers that move by 16 bytes
between two saves of the same party, and the item list is a chain through
`0x02A` of each item record.  They are marked `LIVE` in the note and a
converter must ignore them; the C64 has fixed slots and no heap.
"""

from __future__ import annotations

import dataclasses
from typing import Iterable, Iterator, Mapping, Sequence

from .layout import Confidence, Field, Kind

__all__ = [
    "RECORD_SIZE",
    "DosShape",
    "SHAPES",
    "SHAPES_BY_SIZE",
    "POOL_OF_RADIANCE",
    "CURSE_OF_THE_AZURE_BONDS",
    "SECRET_OF_THE_SILVER_BLADES",
    "POOLS_OF_DARKNESS",
    "shape_for",
    "layout_for",
    "DosShapeError",
    "NAME_SIZE",
    "ITEM_SIZE",
    "EFFECT_SIZE",
    "LAYOUT",
    "FIELDS_BY_NAME",
    "ITEM_LAYOUT",
    "ITEM_FIELDS_BY_NAME",
    "CLASS_NUMBERS",
    "RACE_NUMBERS",
    "SPELLBOOK_FIRST_ID",
    "SPELLBOOK_SPELLS",
    "iter_fields",
    "field_by_name",
    "item_field_by_name",
    "coverage",
    "format_table",
]


#: The Pool of Radiance DOS character record.  A save slot (`CHRDAT<slot><n>.SAV`)
#: and an export (`<NAME>.CHA`) are the same 285 bytes in the same order; the
#: only systematic difference is that an export zeroes the item count.
RECORD_SIZE = 285

#: One count byte plus fifteen bytes of ASCII.
NAME_SIZE = 16

#: One item in a `.ITM` file.  Constant across the whole DOS family, Pool of
#: Radiance through Pools of Darkness and into the Savage Frontier pair.
ITEM_SIZE = 63

#: One active effect in a `.SPC` file.  Also constant across the family.
EFFECT_SIZE = 9

#: The DOS spellbook is one byte per spell for spell ids 1..56, and 56 is
#: `RESTORATION`, which the C64's seven-byte bitmask cannot hold.
SPELLBOOK_FIRST_ID = 1
SPELLBOOK_SPELLS = 56

#: Gold Box Companion's class table, and **the C64's own class codes** -- the
#: two agree entry for entry, which is why `char_class` converts by copying.
#: Checked on all 24 specimens against the class bitmask at `0x0B0`.
CLASS_NUMBERS = (
    "cleric", "druid", "fighter", "paladin", "ranger", "mage", "thief",
    "monk", "cleric/fighter", "cleric/fighter/mage", "cleric/ranger",
    "cleric/mage", "cleric/thief", "fighter/mage", "fighter/thief",
    "fighter/mage/thief", "mage/thief", "monster",
)

#: Race codes, again shared with the C64 -- except that the C64 table is
#: 1-based on the same names with `monster` at 0 on both.
RACE_NUMBERS = (
    "monster", "dwarf", "elf", "gnome", "half-elf", "halfling", "half-orc",
    "human",
)


_U8 = Kind.U8
_I8 = Kind.I8
_U16 = Kind.U16LE
_UINT = Kind.UINT_LE
_RAW = Kind.RAW
_OK = Confidence.CONFIRMED
_MAYBE = Confidence.PROBABLE
_GUESS = Confidence.GUESS
_NOPE = Confidence.UNKNOWN


def _f(offset: int, size: int, kind: Kind, name: str, label: str,
       confidence: Confidence, note: str = "", candidate: bool = False) -> Field:
    return Field(offset, size, kind, name, label, confidence, note, candidate)


# ---------------------------------------------------------------------------
# The record.  One line per field; gaps fill themselves in.
# ---------------------------------------------------------------------------
_DECLARED: Sequence[Field] = (
    _f(0x000, 1, _U8, "name_length", "Name length", _OK,
       "1-15 in all 24 specimens; the longest observed is 14 (ORATISI NOMOON, "
       "THRENDER GRONE) and 0x00F is zero in every one, so the field is a "
       "count byte and fifteen of text rather than sixteen of text"),
    _f(0x001, 15, _RAW, "name_text", "Name", _OK,
       "plain ASCII, no PETSCII anywhere in the DOS record. The bytes past "
       "the count are zero in all 24. Converting to the C64 is a re-padding, "
       "not a transliteration: 20 NUL-padded bytes there against 1+15 here, "
       "and that four-byte difference is the whole displacement between the "
       "two layouts up to exceptional strength"),
    _f(0x010, 1, _U8, "strength", "STR", _OK,
       "the six abilities run 0x010-0x015 in the C64's own order -- STR INT "
       "WIS DEX CON CHA -- and every specimen is 3-18. **Pool of Radiance "
       "stores each ability once.** From Curse onwards the DOS record stores "
       "a (base, current) pair per ability and everything after shifts by "
       "0x46, so this offset is per title and does not transfer"),
    _f(0x011, 1, _U8, "intelligence", "INT", _OK),
    _f(0x012, 1, _U8, "wisdom", "WIS", _OK),
    _f(0x013, 1, _U8, "dexterity", "DEX", _OK),
    _f(0x014, 1, _U8, "constitution", "CON", _OK),
    _f(0x015, 1, _U8, "charisma", "CHA", _OK),
    _f(0x016, 1, _U8, "exceptional_strength", "STR %", _OK,
       "nonzero only where strength is 18. Values seen: 17, 65, 68, 90, 100 "
       "-- the Gold Box '18/00 = 100' encoding the C64 uses at 0x01A"),
    _f(0x01C, 16, _RAW, "spells_memorised", "Spells memorised", _MAYBE,
       "spell ids in the shared 1-56 numbering, **filled from the end of the "
       "region backwards**: ROLAND (cleric 3) holds 0x027-0x02B = 3 3 3 3 23, "
       "which read back to front is 23 3 3 3 3 -- descending, and exactly "
       "what the C64 writes forward from its own 0x020. GILES and ASTRID "
       "(mage 3) hold 21 21 34 in the last three, again magic-user ids only. "
       "No specimen has a cleric id in a magic-user's list or the reverse. "
       "**The Curse importer never reads this region** (0x17-0x2C is one of "
       "its seven skipped runs), so nobody else's code corroborates the "
       "width; sixteen is what the C64 declares and what tiles here"),
    _f(0x02D, 1, _U8, "thac0_base", "THAC0 base (60 - value)", _OK,
       "40, 42 and 43 only, giving THAC0 20, 18 and 17. Gold Box Companion's "
       "Levels.txt states thac0_base = 40 for cleric 1 and 42 for cleric 4 "
       "-- the same biased number, in the same encoding, as the C64's 0x071"),
    _f(0x02E, 1, _U8, "race", "Race", _OK,
       "0 monster, 1 dwarf, 2 elf, 3 gnome, 4 half-elf, 5 halfling, 6 "
       "half-orc, 7 human -- the C64's table exactly. Every race/class pair "
       "in the 24 is legal AD&D: both cleric/fighter/mages are half-elves "
       "and the fighter/mage/thief is an elf"),
    _f(0x02F, 1, _U8, "char_class", "Class", _OK,
       "the 18-entry combined-class table, `CLASS_NUMBERS`. **It is the "
       "C64's own table**: 0 cleric, 2 fighter, 5 mage, 6 thief, 8 "
       "cleric/fighter, 9 cleric/fighter/mage, 11 cleric/mage, 12 "
       "cleric/thief, 13 fighter/mage, 14 fighter/thief, 15 "
       "fighter/mage/thief, 16 mage/thief, which is `por/yaml_io.py`'s "
       "CLASS_CODES entry for entry. Checked against the class bitmask at "
       "0x0B0 on all 24 -- BAKSHI 9 against bits 11, RHIANNON 13 against 9, "
       "ORATISI NOMOON 15 against 13. So the class byte converts by copying, "
       "multi-class included"),
    _f(0x030, 2, _U16, "age", "Age", _OK,
       "16-52 for humans, half-elves and dwarves and 180 for both elves. "
       "0x031 is zero in all 24, so the second byte is inferred from the C64 "
       "having two and from 180 fitting in one -- an elf mage over 255 would "
       "settle it. Read big-endian both elves come out 46080, which is one "
       "of the three readings that fixed the byte order"),
    _f(0x032, 1, _U8, "hp_max", "Hit points maximum", _OK,
       "4-70 across the specimens, and **one byte, not two**: 0x033 starts "
       "the spellbook, so there is no room for a high byte. The C64's field "
       "at 0x076 is genuinely wider"),
    _f(0x033, SPELLBOOK_SPELLS, _RAW, "spellbook", "Spellbook", _OK,
       "one byte per spell, 0 or 1, for spell ids 1..56 in order -- **the "
       "same ids the C64 bitmask at 0x078 indexes**, so the conversion is a "
       "pack, not a permutation. Three things say so together. The DOS array "
       "is grouped cleric-1 (8), mage-1 (13), cleric-2 (7), mage-2 (7), "
       "cleric-3 (9), mage-3 (11), which is `por/spells.py`'s "
       "`_GROUPS_POOL` boundaries 1-8, 9-21, 22-28, 29-35, 36-44, 45-55 "
       "byte for byte. Every set byte in all 24 specimens falls in a group "
       "its owner's class can cast, with no crossover: a level-1 cleric sets "
       "exactly bytes 0-7, a level-3 cleric adds bytes 21-27, a level-3 "
       "magic-user sets 8-20 and 28-34. And the memorised list at 0x01C, "
       "which is written as *ids* rather than as a mask, carries the same "
       "numbers -- 3 CURE LIGHT WOUNDS for the cleric, 21 SLEEP for the "
       "mages. **Byte 55 is spell id 56, RESTORATION**, and the C64's "
       "seven-byte mask has no bit for it: 56 bits hold ids 0-55 and id 0 "
       "does not exist. It is zero in all 24; a converter reports it rather "
       "than dropping it silently"),
    _f(0x06B, 1, _U8, "attack_level", "Fighting level", _OK,
       "the fighter class level where there is one and 1 otherwise -- 3 for "
       "a fighter 3, 1 for a cleric 3. The C64 keeps the same value at "
       "0x098, and Curse's importer recomputes it as `SkillLevel(Fighter)` "
       "or 1, which is this rule in the engine's own hand"),
    _f(0x06C, 1, _U8, "icon_dimension", "Icon dimension", _MAYBE,
       "1 in all 24. The C64's 0x099 aligns here but does **not** mean this: "
       "it carries the icon *size* (small/large), which DOS keeps separately "
       "at 0x0C0. Two DOS fields, one C64 byte, and the C64's is the second "
       "of the two, one lower -- see `por/layout.py`'s `size_small`"),
    _f(0x06D, 1, _U8, "save_paralysis", "Save vs paralysis", _OK,
       "the five saving throws in the C64's order, 0x06D-0x071. ROLAND, a "
       "cleric 3, reads 10 13 14 16 15, which is Gold Box Companion's "
       "save_1..save_5 for cleric 1-3 exactly"),
    _f(0x06E, 1, _U8, "save_petrification", "Save vs petrification", _OK),
    _f(0x06F, 1, _U8, "save_wands", "Save vs wands", _OK),
    _f(0x070, 1, _U8, "save_breath", "Save vs breath", _OK),
    _f(0x071, 1, _U8, "save_spell", "Save vs spell", _OK),
    _f(0x072, 1, _U8, "movement", "Base movement", _OK,
       "12 in all 24 -- unencumbered human speed. The encumbered value lives "
       "in the combat tail at 0x11C, where SILAS in plate mail reads 6"),
    _f(0x073, 1, _U8, "level", "Level", _OK,
       "the highest class level: 3 for a cleric 3, 4 for the fighter 4 / "
       "thief 1. Curse's importer calls the same byte hit dice and sets its "
       "own `multiclassLevel` from it, which is why the DOS Curse record has "
       "one byte here that Pool of Radiance does not"),
    _f(0x074, 1, _U8, "levels_drained", "Levels lost", _MAYBE,
       "zero in all 24; named from Curse's importer, which copies it to the "
       "field it calls levels lost, and from the C64's 0x0A1 aligning"),
    _f(0x075, 1, _U8, "hp_lost_to_drain", "Hit points lost", _MAYBE,
       "zero in all 24; same two sources as 0x074"),
    _f(0x076, 1, _U8, "turn_power", "Turn-undead power", _MAYBE,
       "zero in all 24, including for ROLAND, a cleric 3, whose C64 "
       "counterpart would read 1. The C64 has **two** turning bytes here -- "
       "`turn_class` 0x0A3 for the undead's row and `turn_power` 0x0A4 for "
       "the caster's -- and DOS Pool of Radiance has one byte for the pair, "
       "which is where the run's displacement gains its extra byte before "
       "the thief skills. Which of the two this is cannot be told from a "
       "party with no undead in it and no turning cleric above level 3; "
       "PROBABLE, and one specimen either way settles it"),
    _f(0x077, 1, _I8, "thief_pick_pockets", "Pick pockets", _MAYBE,
       "eight percentages, 0x077-0x07E, in the C64's order. Nonzero for the "
       "thief, for the fighter/mage/thief, and for SILAS -- a fighter 4 who "
       "also carries thief level 1 in the per-class array, which reads as a "
       "dual-class human. Signed, as on the C64, where a halfling's "
       "read-languages sits at -5"),
    _f(0x078, 1, _I8, "thief_open_locks", "Open locks", _MAYBE),
    _f(0x079, 1, _I8, "thief_find_traps", "Find traps", _MAYBE),
    _f(0x07A, 1, _I8, "thief_move_silently", "Move silently", _MAYBE),
    _f(0x07B, 1, _I8, "thief_hide_in_shadows", "Hide in shadows", _MAYBE),
    _f(0x07C, 1, _I8, "thief_hear_noise", "Hear noise", _MAYBE),
    _f(0x07D, 1, _I8, "thief_climb_walls", "Climb walls", _MAYBE),
    _f(0x07E, 1, _I8, "thief_read_languages", "Read languages", _MAYBE),
    _f(0x07F, 4, _RAW, "effect_chain", "Effect list pointer (LIVE)", _MAYBE,
       "a four-byte far pointer, and one of the seven runs Curse's importer "
       "refuses to read (0x7F-0x82). The 0x081/0x082 pair moves with the "
       "heap between two saves of the same party; the active effects "
       "themselves are in the sibling `.SPC` file, one node per record, each "
       "carrying the next in its own last four bytes. LIVE, and NULL is the "
       "right thing to write: the engine allocates the nodes on load and "
       "sets this pointer itself, measured under DOSBox-X (#61)"),
    _f(0x083, 5, _RAW, "field_83_87", "unnamed @0x083", _NOPE,
       "zero but for 0x085, which is 1 in all 24. Curse's importer copies "
       "the run verbatim to its own 0xF6-0xFA without naming it either",
       candidate=True),
    _f(0x088, 2, _U16, "copper", "Copper", _OK,
       "seven u16le coin counts, 0x088-0x095, in the C64's order: copper, "
       "silver, electrum, gold, platinum, gems, jewelry. Three independent "
       "checks. A fresh export carries only gold. Between saves B and A all "
       "six party members gained the same amount of every kind, which is "
       "Gold Box splitting treasure evenly. And the encumbrance identity at "
       "0x102 balances only with this reading and only little-endian. "
       "**Curse's importer discards the lot** and writes 300 platinum "
       "instead -- a fact about Curse's import, not about this field"),
    _f(0x08A, 2, _U16, "silver", "Silver", _OK),
    _f(0x08C, 2, _U16, "electrum", "Electrum", _OK),
    _f(0x08E, 2, _U16, "gold", "Gold", _OK),
    _f(0x090, 2, _U16, "platinum", "Platinum", _OK),
    _f(0x092, 2, _U16, "gems", "Gems", _OK),
    _f(0x094, 2, _U16, "jewelry", "Jewelry", _OK),
    _f(0x096, 8, _RAW, "class_levels", "Per-class levels", _OK,
       "eight slots **indexed by the class number**: cleric 0, druid 1, "
       "fighter 2, paladin 3, ranger 4, mage 5, thief 6, monk 7. Confirmed "
       "on the four classes the specimens use -- a cleric 3 sets slot 0, a "
       "mage 3 sets slot 5, a thief 1 sets slot 6, BAKSHI the "
       "cleric/fighter/mage sets 0, 2 and 5 at once. The C64's eight slots "
       "at 0x0C9 are indexed by the class **bit** instead (magic-user, "
       "cleric, thief, fighter, knight, -, paladin, ranger), so this is a "
       "permutation and not a copy. Druid and monk have no C64 slot at all"),
    _f(0x09E, 1, _U8, "sex", "Sex", _MAYBE,
       "1 for ARGORA, ASTRID, RHIANNON, DARKSTAR and FLORENTZ and 0 for the "
       "other nineteen, which is female = 1 on the C64's encoding too. "
       "PROBABLE because no specimen names its own sex on screen here"),
    _f(0x0A0, 1, _U8, "alignment", "Alignment", _MAYBE,
       "0-based on the C64's own table: LAWFUL GOOD 0, LAWFUL NEUTRAL 1, "
       "LAWFUL EVIL 2, NEUTRAL GOOD 3, TRUE NEUTRAL 4, NEUTRAL EVIL 5, "
       "CHAOTIC GOOD 6, CHAOTIC NEUTRAL 7, CHAOTIC EVIL 8. Values 0, 1, 3, "
       "4, 6 and 7 appear across the 24 and nothing outside 0-8 does, which "
       "is what a nine-entry table looks like from a party with no evil "
       "characters in it. The offset is fixed by the run either side: the "
       "eight attack-form bytes follow it and the per-class level array "
       "precedes it, both at the same +0x38 displacement to the C64"),
    _f(0x0A1, 8, _RAW, "attack_forms", "Attack forms", _MAYBE,
       "the C64's four parallel two-entry arrays at 0x0D9 -- attacks per "
       "round doubled, damage dice, die size, signed modifier, each holding "
       "form 0 then form 1. 0x0A1 is 2 in all 24, which is one attack in "
       "the family's halves encoding and is what Gold Box Companion's "
       "Levels.txt writes. A player character uses one form; the monster "
       "records are where the second is visible"),
    _f(0x0A9, 1, _U8, "armour_class_base", "Base AC (60 - value)", _MAYBE,
       "50 in all 24, which on the family's 60 - value encoding is armour "
       "class 10: unarmoured, before dexterity and before any item. Exactly "
       "what the C64's 0x0E1 holds for every player character it has ever "
       "been read from, at the offset this one aligns to"),
    _f(0x0AA, 1, _U8, "strength_bonus", "Strength bonus flag", _MAYBE,
       "1 in all 24. The C64's aligned byte 0x0E2 is a *strength index* "
       "holding 15-22, so the two are different fields and neither should "
       "be copied onto the other"),
    _f(0x0AB, 1, _U8, "unnamed_0ab", "unnamed @0x0AB", _NOPE,
       "one byte, stable per character across the A/B save pair and "
       "different for every character -- 165, 204, 0, 120, 154, 231 for the "
       "party. It is not experience (that starts at 0x0AC and decodes), not "
       "hit points rolled (0x0B1), and not any level. Unattributed",
       candidate=True),
    _f(0x0AC, 3, _UINT, "experience", "Experience", _OK,
       "u24le. 5333 -> 7670 for a fighter whose level byte says 3 and 7349 "
       "-> 9686 for one whose says 4, and all six party members gained the "
       "identical 2337 between saves B and A -- the even experience split. "
       "Read big-endian the same bytes put a level-3 fighter past fourteen "
       "million, which no Pool of Radiance character can reach"),
    _f(0x0B0, 1, _U8, "class_bits", "Class bitmask", _OK,
       "bit 0 magic-user, bit 1 cleric, bit 2 thief, bit 3 fighter -- **the "
       "C64's bit order unchanged**. 24 of 24 decompose to the class byte at "
       "0x02F, the multi-class values 9, 11 and 13 included"),
    _f(0x0B1, 1, _U8, "hp_rolled", "Hit points rolled", _MAYBE,
       "hit points before the constitution bonus: it tracks hit points "
       "maximum across a level gain, offset by a per-character constant"),
    _f(0x0B2, 3, _RAW, "spells_castable_cleric", "Cleric spell slots", _MAYBE,
       "how many spells of each level the character may memorise, one byte "
       "per spell level, cleric here and magic-user at 0x0B5. ROLAND, a "
       "cleric 3 with wisdom 18, reads 4 3 0; GILES, a magic-user 3, reads "
       "0 0 0 here and 2 1 0 at 0x0B5, which is the game's own table for "
       "magic-user 3. **The C64 packs the same six numbers into three "
       "bytes**, cleric in the high nibble and magic-user in the low, at "
       "0x0EE -- so this is an unpack, not a copy"),
    _f(0x0B5, 3, _RAW, "spells_castable_magic_user", "Magic-user spell slots",
       _MAYBE),
    _f(0x0BB, 1, _U8, "portrait_head", "Portrait head", _OK,
       "**the four bytes at 0x0BB were one GUESS field called `icon_choice`; "
       "they are two pairs** (#57). 0x0BB and 0x0BC index the sheet portrait "
       "-- the `HEAD<n>.DAX` and `BODY<n>.DAX` sets -- and 0x0BD and 0x0BE "
       "the small combat icon, `CHEAD.DAX` and `CBODY.DAX`. Three things say "
       "so together. The community's per-title tables in "
       "`work/coab-research/formats/` name exactly this split and only Pool "
       "of Radiance has all four: from Curse onwards the first pair is gone "
       "and Pools of Darkness carries the second alone, which is what a "
       "sheet portrait dropped between titles looks like. The C64 record has "
       "`portrait_head` and `portrait_body` adjacent at 0x0FE and 0x0FF for "
       "the same reason. And the values fit: 1-11 here and 1-10 at 0x0BC "
       "across the 18, against 0-13 and 3-31 for the icon pair, which is two "
       "small sets and one larger one.\n"
       "**CONFIRMED in the running game** (#57), three sheets of one "
       "character in DOSBox: BRUTUS ships as (12, 3) and draws a "
       "dark-haired head on a bare torso; (1, 3) draws a *different head* on "
       "**the same torso**; (1, 1) draws that same head on an armoured "
       "torso. Head and body move independently, and each byte moves its own "
       "half"),
    _f(0x0BC, 1, _U8, "portrait_body", "Portrait body", _OK,
       "see `portrait_head`: the body half of the same experiment"),
    _f(0x0BD, 1, _U8, "icon_head", "Combat icon head", _MAYBE,
       "the combat icon's half of the pair, and the half every title keeps. "
       "0-13 across the 18"),
    _f(0x0BE, 1, _U8, "icon_body", "Combat icon body", _MAYBE,
       "3-31 across the 18. Pools of Darkness reaches 31"),
    _f(0x0BF, 1, _U8, "party_order", "Party order", _OK,
       "0-5 in file order for every six-character slot. Curse's importer "
       "declines to read it, which is a fact about Curse"),
    _f(0x0C0, 1, _U8, "size", "Size", _OK,
       "1 small, 2 medium: 1 for the dwarf and the halfling, 2 for everyone "
       "else, in all 24. The C64 stores the same distinction one lower -- "
       "0 small, 1 large -- at 0x099"),
    _f(0x0C1, 6, _RAW, "icon_colours", "Icon colours", _MAYBE,
       "**six bytes of two 4-bit colour indices each, not heap pointers** "
       "(#57). They were read as far pointers because 0x0C4 and 0x0C6 are "
       "equal for every character in a slot; they are equal for every "
       "character in every slot of every *title*, which is not what a heap "
       "segment does. 42 of the 54 shipped records across the four titles "
       "read `91 A2 B3 C4 E6 F7` -- high nibbles 9 A B C E F, low nibbles "
       "1 2 3 4 6 7 -- and the six that differ are the six **played** Pools "
       "of Darkness characters, each with its own set. The community tables "
       "name the pairs body, arm, leg, hair/face, shield and weapon. "
       "PROBABLE; the confirmation is to change one and look at the icon.\n"
       "**This matters for a conversion.** The engine does *not* rebuild "
       "them: `docs/117` records that its own resave kept our zeros here. So "
       "a converted character written with zeros is one whose combat icon "
       "has no colours, and nobody has looked at one"),
    _f(0x0C7, 1, _U8, "item_count", "Item count", _OK,
       "24 of 24: count x 63 is the exact size of the sibling `.ITM` file. "
       "**Always 0 in an export**, which is the one systematic difference "
       "between a save slot and a `.CHA`"),
    _f(0x0C8, 56, _RAW, "item_chain", "Item pointer block (LIVE)", _NOPE,
       "the item list as the engine holds it: a pointer block at 0x0CC that "
       "Curse's importer copies as 0x34 = 52 raw bytes, and that is the "
       "whole of what it does with items. The C64 has sixteen fixed slots "
       "and no chain, so the pointers go and the order stays. LIVE"),
    _f(0x100, 1, _U8, "hands_used", "Hands used", _MAYBE,
       "first byte of the combat tail Curse's importer names hands used, "
       "weight, health status, in-combat, team, hit bonus, armour class, "
       "attacks left, dice, damage bonuses, current hit points, movement. "
       "2 for the fighters and 1 for the mages here"),
    _f(0x102, 2, _U16, "encumbrance", "Encumbrance", _OK,
       "u16le, and **the single most useful number in the file**:\n"
       "```\n"
       "encumbrance = cp + sp + ep + gp + pp + gems + jewelry\n"
       "                + sum(item weight x quantity)\n"
       "```\n"
       "It balances exactly for 16 of the 18 saved characters and for all "
       "six exports, and the two that miss carry a stack of darts whose "
       "rendered name disagrees with the quantity byte, so one of those two "
       "is stale rather than the identity being wrong. That one sum "
       "confirms the money block, the 63-byte item stride, the weight "
       "offset and the byte order together. **Derived, not stored** -- "
       "Curse's `reclac_player_values` computes it the same way -- so the "
       "C64, which has no such field, loses nothing"),
    _f(0x104, 8, _RAW, "heap_104", "unnamed @0x104 (LIVE)", _NOPE,
       "another of the runs Curse's importer skips; 0x106/0x107 move with "
       "the heap. LIVE"),
    _f(0x10C, 4, _RAW, "field_10c_10f", "unnamed @0x10C", _NOPE,
       "00 01 00 00 in all 24 specimens -- found by the writer's round trip, "
       "which the reader's hand-the-bytes-back check could never catch. "
       "0x10C-0x10E sit inside the combat tail Curse's importer copies "
       "verbatim and 0x10F is one of the bytes it skips; none is named on "
       "either side. The constant 1 at 0x10D is plausibly a health status "
       "('okay'), but nothing corroborates that", candidate=True),
    _f(0x110, 1, _U8, "thac0_current", "THAC0 current (60 - value)", _MAYBE,
       "40-47, one above the base for the fighter with 18/17 strength. "
       "Derived from the readied weapon. The C64's roster keeps the same "
       "number in the same encoding at +0x0E"),
    _f(0x111, 1, _U8, "armour_class", "Armour class current (60 - value)",
       _MAYBE,
       "`60 - AC`, the family's encoding, and a **negative** armour class is "
       "what it is meant to give: SILAS reads 63, which is AC -3, and AD&D "
       "1st edition puts a fighter in plate mail (AC 3) with a shield +1 "
       "(-2) and dexterity 18 (-4) at exactly -3. This was read as "
       "'unsettled bias' while the negative value looked like an error. The "
       "C64 keeps the same number at record 0x10F and roster +0x0F"),
    _f(0x112, 9, _RAW, "roster_tail", "Armour bonus and current attack form",
       _MAYBE,
       "**the C64's nine-byte roster tail, one for one**: the armour bonus at "
       "+0x10 then the eight running attack-form bytes at +0x11 -- two attack "
       "counts, two dice counts, two die sizes, two damage bonuses. The whole "
       "DOS combat tail 0x110-0x11C lines up on the C64's roster block "
       "0x10E-0x11B at a displacement of -2, with the one-byte widening of "
       "hit points at the end accounting for the rest"),
    _f(0x11B, 1, _U8, "hp_current", "Hit points current", _OK,
       "equals hit points maximum for 22 of the 24 and is lower for the two "
       "wounded characters"),
    _f(0x11C, 1, _U8, "movement_current", "Movement current", _MAYBE,
       "12 for everyone unencumbered and 6 for SILAS, who wears plate mail. "
       "Derived from encumbrance; recompute rather than copy"),
)


# ---------------------------------------------------------------------------
# The item record.  63 bytes, and past its cached display line it *is* the
# C64's sixteen, one field to a byte.
# ---------------------------------------------------------------------------
_ITEM_DECLARED: Sequence[Field] = (
    _f(0x000, 1, _U8, "text_length", "Rendered line length", _OK,
       "the longest observed is 40, '* Magic User Scroll With 3 Spells'"),
    _f(0x001, 41, _RAW, "text", "Rendered inventory line (CACHE)", _OK,
       "the line the game last drew for this item -- readied marker, '*' for "
       "magic, the name. **A cache and never a source.** It goes stale: one "
       "specimen reads '11 Darts' over a quantity byte of 8, which is one of "
       "the two characters whose encumbrance identity misses"),
    _f(0x02A, 4, _RAW, "next", "Next item (LIVE)", _OK,
       "far pointer to the next item in the character's chain, NULL on the "
       "last. The C64 keeps sixteen fixed slots; drop the chain, keep the "
       "order"),
    _f(0x02E, 1, _U8, "type_index", "Item type", _OK,
       "indexes `ITEMS`, the 128 x 16 type table -- **and the DOS `ITEMS` "
       "file is byte-identical to the C64's in 126 of its 128 records**, the "
       "two that differ being dagger and dart differing in range with the "
       "class-usage flags equal. So the class restrictions, which live in "
       "byte +13 of the type record and not in the item, need no conversion "
       "at all. C64 +0"),
    _f(0x02F, 1, _U8, "name1", "Name word 1", _OK,
       "the three name words are **the C64's own ITEMNAMES indices**, not "
       "text: 48 is MAIL, 162 is +1, 208 is CLERICAL SCROLL, on both ports. "
       "C64 +1, +2, +3"),
    _f(0x030, 1, _U8, "name2", "Name word 2", _OK),
    _f(0x031, 1, _U8, "name3", "Name word 3", _OK),
    _f(0x032, 1, _I8, "plus", "Plus", _OK,
       "signed: +1, +2, +3 against the printed names, and -5 in both this "
       "byte and the next on a cursed necklace, which is the C64's +4/+5 "
       "pair exactly. C64 +4"),
    _f(0x033, 1, _I8, "plus_save", "Save bonus", _OK,
       "signed; accumulates into the saving-throw roll. C64 +5"),
    _f(0x034, 1, _U8, "readied", "Readied", _OK,
       "0 or 1. The C64 packs it as bit 7 of its +6, sharing that byte with "
       "the hidden-name mask -- one of the two places where the DOS record "
       "spends a byte on a C64 bit"),
    _f(0x035, 1, _U8, "hidden", "Hidden-name mask", _OK,
       "bit 0 hides name word 3, bit 1 word 2, bit 2 word 1. C64 +6 bits 0-2"),
    _f(0x036, 1, _U8, "cursed", "Cursed", _OK,
       "0 or 1; the C64's +7 bit 7"),
    _f(0x037, 2, _U16, "weight", "Weight", _OK,
       "u16le, tenths of a pound. Confirmed by the encumbrance identity, "
       "which is arithmetic entirely inside the DOS files. C64 +8, +9"),
    _f(0x039, 1, _U8, "quantity", "Quantity", _OK, "C64 +10"),
    _f(0x03A, 2, _U16, "value", "Cost in gold", _OK, "u16le. C64 +11, +12"),
    _f(0x03C, 1, _U8, "charges", "Charges", _OK,
       "the use-item routine spends the quantity byte while it is above one "
       "and then decrements this one, destroying the item at zero. Three "
       "WAND OF MAGIC MISSILES templates differ in this byte alone -- 20, "
       "33, 35. C64 +13"),
    _f(0x03D, 1, _U8, "effect", "Effect", _OK, "C64 +14"),
    _f(0x03E, 1, _U8, "power", "Power", _OK, "C64 +15"),
)


def _build(declared: Iterable[Field], size: int, what: str) -> tuple[Field, ...]:
    """Sort, validate, and fill the gaps with UNKNOWN entries.

    The same contract as `por.layout._build`: every byte of the record ends up
    in exactly one entry, and an overlap or an out-of-range declaration is an
    import-time error rather than a silently wrong read.
    """
    out: list[Field] = []
    cursor = 0
    for f in sorted(declared, key=lambda f: f.offset):
        if f.size <= 0:
            raise ValueError(f"{what} field {f.name!r} has size {f.size}")
        if f.offset < 0 or f.end > size:
            raise ValueError(
                f"{what} field {f.name!r} at {f.offset:#x}+{f.size} escapes "
                f"the {size}-byte record")
        if f.offset < cursor:
            raise ValueError(
                f"{what} field {f.name!r} at {f.offset:#x} overlaps the "
                f"previous field")
        if f.offset > cursor:
            out.append(_gap(cursor, f.offset - cursor))
        out.append(f)
        cursor = f.end
    if cursor < size:
        out.append(_gap(cursor, size - cursor))
    return tuple(out)


def _gap(offset: int, size: int) -> Field:
    return Field(offset=offset, size=size, kind=Kind.RAW,
                 name=f"gap_{offset:03x}", label=f"unallocated @{offset:#05x}",
                 confidence=Confidence.UNKNOWN,
                 note="zero in every specimen held", candidate=False)


#: Every one of the 285 bytes belongs to exactly one entry.
LAYOUT: tuple[Field, ...] = _build(_DECLARED, RECORD_SIZE, "record")
FIELDS_BY_NAME: dict[str, Field] = {f.name: f for f in LAYOUT}

#: Every one of the 63 item bytes, likewise.
ITEM_LAYOUT: tuple[Field, ...] = _build(_ITEM_DECLARED, ITEM_SIZE, "item")
ITEM_FIELDS_BY_NAME: dict[str, Field] = {f.name: f for f in ITEM_LAYOUT}

assert sum(f.size for f in LAYOUT) == RECORD_SIZE
assert sum(f.size for f in ITEM_LAYOUT) == ITEM_SIZE
assert len(FIELDS_BY_NAME) == len(LAYOUT)
assert len(ITEM_FIELDS_BY_NAME) == len(ITEM_LAYOUT)


# ---------------------------------------------------------------------------
# The other three titles.  One row each.
# ---------------------------------------------------------------------------
#: What a title does to the record above.
#:
#: The four DOS Gold Box records this project can reach -- 285, 422, 439 and
#: 510 bytes -- are **the same field sequence at four widths**.  Nothing is
#: reordered and nothing is inserted out of turn: what changes is how wide a
#: field is, whether it is there at all, and how much unnamed space sits
#: between two named ones.  So a title is a row of overrides against the Pool
#: of Radiance table, not a second table and never a branch.
#:
#: `sizes` names a field and gives its width in this title; **zero means the
#: title does not have it**.  `inserts` names a field and gives how many bytes
#: follow it that Pool of Radiance does not have; they come out as gaps,
#: because that is what they are -- space this project has not decoded.
#:
#: Offsets are then whatever accumulation makes them, which is the point: a
#: width that is wrong moves everything after it and the record stops adding
#: up to its own size, so `layout_for` raises rather than reading rubbish.
@dataclasses.dataclass(frozen=True)
class DosShape:
    """One title's DOS character record, as a difference from Pool of
    Radiance's."""

    key: str
    title: str
    record_size: int
    #: The sibling files beside `CHRDAT<slot><n>.SAV`: items, then effects.
    item_suffix: str = ".ITM"
    effect_suffix: str = ".SPC"
    #: Bytes in the byte-per-spell book, which is spell ids 1..n in order.
    spellbook_spells: int = SPELLBOOK_SPELLS
    sizes: Mapping[str, int] = dataclasses.field(default_factory=dict)
    inserts: "Mapping[str, int | Sequence[Field]]" = dataclasses.field(
        default_factory=dict)


#: Shared by three titles, so it is written once.
_FORMER_NOTE = (
    "the per-class level array again, indexed by class number the same way, "
    "holding what a dual-classed character *was*. ABAGAIL in Pools of "
    "Darkness is a magic-user 12 whose slot 0 here reads cleric 11, and her "
    "class bitmask carries both bits; PAINE is a magic-user 13 who was a "
    "ranger 9. CONFIRMED on those two; Pool of Radiance has no such array")

_DRUID_SLOT_NOTE = (
    "the slot array between the cleric's and the magic-user's, one byte per "
    "spell level. **CONFIRMED by the rangers**, six of them across two "
    "titles: Silver Blades' PAINE, ARGORA and RWELLYN are level 8 and each "
    "holds 1 here and nothing in the other arrays, which is AD&D's ranger "
    "getting his first *druid* spell at 8; Pools of Darkness' CLARISSA, "
    "ARGORA and RWELLYN are level 13 and hold 2 1 here **and** 2 1 in the "
    "magic-user array, which is the same ranger at 13. Both match "
    "`por/spells.py`'s ranger grant table, read out of the C64 `GEN`. "
    "Paladins do **not** use this array -- Pools of Darkness' Guy de Valois, "
    "a paladin 12, holds 2 2 in the *cleric* array")


def _x(size: int, name: str, label: str, confidence: Confidence,
       note: str = "") -> Field:
    """A field a later title has and Pool of Radiance does not.  The offset
    is filled in by `layout_for`, which is the only thing that knows it."""
    return Field(0, size, Kind.RAW, name, label, confidence, note, False)


#: Pool of Radiance itself: the table above, unchanged.  Present so callers
#: can treat all four alike.
POOL_OF_RADIANCE = DosShape(
    key="pool-of-radiance", title="Pool of Radiance", record_size=285)

#: Curse of the Azure Bonds, 422 bytes.  Three things move it: every ability
#: becomes a (base, current) pair, the memorised-spell region grows from 21
#: bytes to 84, and the spellbook grows from 56 entries to 100 -- which is
#: `por/spells.py`'s Curse id space, 1..100, exactly.  Then the record gains
#: the fields a second title needs: a multi-class level beside the level, a
#: former-level array beside the class-level one, a druid spell-slot array
#: between the cleric's and the magic-user's, and four bytes of its own
#: before the combat tail.
CURSE_OF_THE_AZURE_BONDS = DosShape(
    key="curse-of-the-azure-bonds", title="Curse of the Azure Bonds",
    record_size=422, item_suffix=".ITM", effect_suffix=".FX",
    spellbook_spells=100,
    sizes={"strength": 2, "intelligence": 2, "wisdom": 2, "dexterity": 2,
           "constitution": 2, "charisma": 2, "exceptional_strength": 2,
           "gap_017": 0, "spells_memorised": 84, "spellbook": 100,
           "experience": 4, "gap_0af": 0,
           "spells_castable_cleric": 5, "spells_castable_magic_user": 5},
    inserts={"level": 1,
             "class_levels": (_x(8, "former_class_levels",
                                 "Former class levels", _MAYBE, _FORMER_NOTE),),
             "spells_castable_cleric": (
                 _x(5, "spells_castable_druid", "Druid spell slots", _MAYBE,
                    _DRUID_SLOT_NOTE),),
             "icon_colours": 1, "heap_104": 4})

#: Secret of the Silver Blades, 439 bytes.  Curse's record plus a spellbook
#: of 117 -- `por/spells.py`'s Silver Blades id space, 1..117 -- seven spell
#: slot levels rather than five, and **two** undecoded slot arrays between the
#: cleric's and the magic-user's rather than one.  It drops the monk level
#: slot and the `type` byte, and its memorised region is *smaller* than
#: Curse's at 75 bytes.
SECRET_OF_THE_SILVER_BLADES = DosShape(
    key="secret-of-the-silver-blades", title="Secret of the Silver Blades",
    record_size=439, item_suffix=".ITM", effect_suffix=".SFX",
    spellbook_spells=117,
    sizes={"strength": 2, "intelligence": 2, "wisdom": 2, "dexterity": 2,
           "constitution": 2, "charisma": 2, "exceptional_strength": 2,
           "gap_017": 0, "spells_memorised": 75, "spellbook": 117,
           "field_83_87": 4, "class_levels": 7, "gap_09f": 0,
           "experience": 4, "gap_0af": 0,
           "spells_castable_cleric": 7, "spells_castable_magic_user": 7},
    inserts={"char_class": 1, "level": 1,
             "class_levels": (_x(7, "former_class_levels",
                                 "Former class levels", _MAYBE, _FORMER_NOTE),),
             "spells_castable_cleric": (
                 _x(7, "spells_castable_druid", "Druid spell slots", _MAYBE,
                    _DRUID_SLOT_NOTE),
                 _x(7, "spells_castable_unattributed",
                    "A fourth spell-slot array", _NOPE,
                    "Silver Blades is the only title of the four with a "
                    "**fourth** slot array -- 28 bytes where Curse has 15 and "
                    "Pools of Darkness 27 -- and no shipped character sets a "
                    "byte of it. Cleric, druid and magic-user account for the "
                    "other three, and it is **not the paladin's**: Pools of "
                    "Darkness puts a paladin's spells in the cleric array. "
                    "UNKNOWN. A played Silver Blades save with a caster the "
                    "shipped party does not have would settle it")),
             "icon_colours": 3, "heap_104": 1})

#: Pools of Darkness, 510 bytes, and the one with no C64 counterpart at all.
#: It is the later engine: no drained-level pair, no `modified` byte, no
#: `type`, no monk, no experience-per-hit-point award -- and **only three
#: money slots**, platinum, gems and jewelry, where every earlier title has
#: seven.  It gains a highest-level array and a highest-experience field
#: beside the current ones, which is what a title with level drain that
#: matters looks like.
POOLS_OF_DARKNESS = DosShape(
    key="pools-of-darkness", title="Pools of Darkness", record_size=510,
    item_suffix=".THG", effect_suffix=".EFX", spellbook_spells=125,
    sizes={"strength": 2, "intelligence": 2, "wisdom": 2, "dexterity": 2,
           "constitution": 2, "charisma": 2, "exceptional_strength": 2,
           "gap_017": 0, "spells_memorised": 141, "spellbook": 125,
           "levels_drained": 0, "hp_lost_to_drain": 0, "field_83_87": 4,
           "copper": 0, "silver": 0, "electrum": 0, "gold": 0,
           "class_levels": 7, "gap_09f": 0, "strength_bonus": 0,
           "experience": 4, "gap_0af": 0,
           "spells_castable_cleric": 9, "spells_castable_magic_user": 9,
           "gap_0b8": 2, "portrait_head": 0, "portrait_body": 0},
    inserts={"char_class": 1, "level": 1,
             "class_levels": (
                 _x(7, "former_class_levels", "Former class levels", _MAYBE,
                    _FORMER_NOTE),
                 _x(7, "highest_class_levels", "Highest class levels", _MAYBE,
                    "a third copy of the level array, and what a title with "
                    "level drain that matters needs: the level to restore to. "
                    "Zero in every shipped record, so PROBABLE from its "
                    "position and from the highest-experience field that sits "
                    "beside experience for the same reason")),
             "experience": 5, "spells_castable_cleric": (
                 _x(9, "spells_castable_druid", "Druid spell slots", _MAYBE,
                    _DRUID_SLOT_NOTE),),
             "icon_colours": 2, "heap_104": 2})

SHAPES: tuple[DosShape, ...] = (POOL_OF_RADIANCE, CURSE_OF_THE_AZURE_BONDS,
                                SECRET_OF_THE_SILVER_BLADES,
                                POOLS_OF_DARKNESS)
SHAPES_BY_KEY: dict[str, DosShape] = {s.key: s for s in SHAPES}
#: The record size identifies the title on its own: 285, 422, 439, 510.
SHAPES_BY_SIZE: dict[int, DosShape] = {s.record_size: s for s in SHAPES}


class DosShapeError(ValueError):
    """A record size or title key that names no DOS Gold Box record."""


def shape_for(what: "int | str | DosShape") -> DosShape:
    """The shape for a record size, a key, or a shape.

    The size is enough on its own -- no two of the four are the same length --
    which is what lets a reader identify a file it was handed with no title.
    """
    if isinstance(what, DosShape):
        return what
    if isinstance(what, int):
        try:
            return SHAPES_BY_SIZE[what]
        except KeyError:
            raise DosShapeError(
                f"{what} bytes is no DOS Gold Box character record; the four "
                f"this project reads are "
                f"{', '.join(str(n) for n in sorted(SHAPES_BY_SIZE))}"
            ) from None
    try:
        return SHAPES_BY_KEY[what]
    except KeyError:
        raise DosShapeError(f"no DOS title keyed {what!r}") from None


def layout_for(what: "int | str | DosShape") -> tuple[Field, ...]:
    """The field table for one title, built from Pool of Radiance's.

    Every field keeps its name, its meaning and its note; what a title moves
    is where it lands.  A shape whose widths do not add up to its own record
    size raises here rather than handing back a table that reads the wrong
    bytes -- which is the check that makes a new title cheap to try.

    **What that check does not catch, and what does.**  It is a sum, so two
    compensating mistakes in one shape -- a field short by *n* and a later one
    long by *n* -- add up correctly and pass, mis-placing every field between
    them.  What catches that is the per-specimen work in
    `tests/test_dosconvert.py`: every record rebuilding byte for byte, the
    encumbrance identity balancing, and the class bitmask agreeing with the
    level arrays, all 54 of 54 today.

    **Those tests need the player's own archives and skip without them, so CI
    does not run them.**  On a machine with no `FR_ARCHIVES` the only thing
    standing behind Curse, Silver Blades and Pools of Darkness is this sum and
    `test_each_shape_tiles_its_own_record`, which checks total width and that
    offsets increase -- not that any field is in the right place.  So an edit
    to one of those three shapes is only really tested where the archives are.
    Say in the commit that you ran it somewhere they exist.
    """
    shape = shape_for(what)
    declared: list[Field] = []
    cursor = 0
    for f in LAYOUT:
        size = shape.sizes.get(f.name, f.size)
        if size < 0:
            raise DosShapeError(
                f"{shape.key}: field {f.name!r} cannot be {size} bytes")
        if size:
            if not f.name.startswith("gap_"):
                kind = f.kind
                if size != f.size and kind in (Kind.U8, Kind.I8):
                    # A byte that became a pair is no longer a byte: read it
                    # raw rather than silently handing back half of it.
                    kind = Kind.RAW
                declared.append(dataclasses.replace(
                    f, offset=cursor, size=size, kind=kind))
            cursor += size
        extra = shape.inserts.get(f.name, 0)
        if isinstance(extra, int):
            cursor += extra
        else:
            for e in extra:
                declared.append(dataclasses.replace(e, offset=cursor))
                cursor += e.size
    if cursor != shape.record_size:
        raise DosShapeError(
            f"{shape.key}: the field widths add up to {cursor} bytes, not "
            f"the {shape.record_size} the record is")
    return _build(declared, shape.record_size, f"{shape.key} record")


#: Every title's table, by key.  Pool of Radiance's is `LAYOUT` itself.
LAYOUTS: dict[str, tuple[Field, ...]] = {s.key: layout_for(s) for s in SHAPES}
FIELDS_BY_NAME_FOR: dict[str, dict[str, Field]] = {
    key: {f.name: f for f in table} for key, table in LAYOUTS.items()}

assert LAYOUTS[POOL_OF_RADIANCE.key] == LAYOUT, (
    "the Pool of Radiance shape must reproduce the table it was read from")


def iter_fields() -> Iterator[Field]:
    """Every record field in offset order."""
    return iter(LAYOUT)


def field_by_name(name: str) -> Field:
    try:
        return FIELDS_BY_NAME[name]
    except KeyError:
        raise KeyError(f"no field named {name!r} in the DOS record") from None


def item_field_by_name(name: str) -> Field:
    try:
        return ITEM_FIELDS_BY_NAME[name]
    except KeyError:
        raise KeyError(f"no field named {name!r} in the DOS item") from None


def coverage() -> dict[Confidence, int]:
    """Bytes of the 285 at each confidence level."""
    counts = {level: 0 for level in Confidence}
    for f in LAYOUT:
        counts[f.confidence] += f.size
    return counts


def format_table(include_gaps: bool = True) -> str:
    """The layout as a fixed-width table."""
    rows = LAYOUT if include_gaps else tuple(f for f in LAYOUT if f.is_known)
    header = (f"{'offset':>7} {'size':>4} {'kind':<9} {'confidence':<10} "
              f"{'name':<26} label")
    lines = [header, "-" * len(header)]
    for f in rows:
        lines.append(f"{f.offset:#07x} {f.size:>4} {f.kind.value:<9} "
                     f"{f.confidence.value:<10} {f.name:<26} {f.label}")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - convenience
    print(format_table())
    print()
    for level, n in coverage().items():
        print(f"  {level.value:<9} {n:4d} bytes  ({100.0 * n / RECORD_SIZE:5.1f}%)")
