"""Amiga Pools of Darkness character files (`Save/NAME.pc`).

Everything named here was read off the screen: a `.pc` was written onto a copy
of PoD's disk 3, added through `Add Character -> Pools`, and the character
sheet photographed. Two payload shapes did the work. A **ramp** -- every byte
holding its own offset -- makes a number the sheet draws name the offset it
came from, and that found the numeric fields. A ramp cannot find an enum,
because a wrong index draws unrelated game text rather than a number, so the
four enums were found the other way round: the values were predicted from the
twelve genuine `.pc` files on disk 3 (a paladin must be lawful good, a
fighter/magic-user/thief must be a half-elf) and then a **plausible** payload
put the prediction on screen. `docs/124-amiga-port.md` has the runs.

Three things make that possible at all, all measured rather than assumed:
Amiga PoD applies **no length check and no signature check** to a `.pc`; the
`0x00`-`0x5F` longwords that a genuine file fills with Amiga heap addresses
are don't-care on load; and a record whose item region is zero loads and
joins the party.

**Everything is big-endian.** It is a 68000.

**The record holds base values; the game derives the rest on load.** THAC0,
encumbrance and the second copy of movement and armour class are recomputed
and their stored values ignored -- a probe that set encumbrance to 1234 drew
`233`, which is its 200 platinum plus 11 gems plus 22 jewelry, and one that
set the derived movement to 99 drew the base's `12`. So the writer leaves the
derived block alone.

The offsets were also checked a second way: they decode the twelve genuine
`.pc` files on disk 3 to sane values -- every ability 18, one class level
each, armour class 10 and 1d2 damage unequipped, ages 28 to 46, and every
alignment legal for its class. `tests/test_amiga.py` asserts both halves.
"""

from __future__ import annotations

import contextlib
import struct
from dataclasses import dataclass, field
from typing import Sequence

from . import dos_layout, games, neutral
from .amiga_adf import AmigaDiskError
from .layout import Kind
from .neutral import NeutralCharacter

#: The C64 record's `60 - value` bias turns up here too, on armour class.
COMBAT_BIAS = 60

#: The shortest genuine `.pc` on disk 3. Sizes run 484, 504, 514 and 524; the
#: extra bytes are appended item data, and a record with none is 484. PoD
#: checks no length -- a 582-byte C64 export loads -- but 484 is what its own
#: files look like, so it is what the writer emits.
RECORD_LENGTH = 484

EXPERIENCE = 0x044           # u32
PLATINUM = 0x04C             # u16 each, in this order
GEMS = 0x04E
JEWELRY = 0x050
AGE = 0x052                  # u16
RACE = 0x058
CLASS = 0x059
SEX = 0x05C
ALIGNMENT = 0x05D
NAME = 0x060
NAME_LENGTH = 15             # 15 characters, NUL terminator at 0x06F
ABILITIES = 0x070            # six base/current pairs; the sheet draws the 2nd
ABILITY_COUNT = 6
EXCEPTIONAL_STRENGTH = 0x07C  # one more pair, same shape
#: One byte, not a word: the ramp put 128 at 0x080 and 129 at 0x081 and the
#: sheet said `129`, where a big-endian word would have said 32897. Two of the
#: twelve real records have 0x080 set, so where a Pools of Darkness character
#: above 255 hit points keeps them is still UNKNOWN.
HP_MAX = 0x081
MOVEMENT = 0x088
CLASS_LEVELS = 0x09D         # seven bytes, one per class slot
CLASS_LEVEL_COUNT = 7
DAMAGE_DICE = 0x0AD          # count, sides, bonus -- stride 2, see below
DAMAGE_STRIDE = 2
ARMOUR_CLASS = 0x0B3         # stored as 60 - AC
HP_CURRENT = 0x190           # u16

#: Damage and armour class sit on *odd* offsets two apart, which is the same
#: base/current pair shape the abilities use at 0x070: the sheet draws the
#: second byte of each pair. So the damage triple is three pairs at 0x0AC and
#: armour class is a pair at 0x0B2.
PAIR_CURRENT = 1

#: The enum tables, read out of the game binary and then each confirmed by a
#: probe that put a chosen index on screen: `HALF-ELF`, `DWARF`, `THIEF`,
#: `FIGHTER`, `FEMALE`, `MALE`, `CHAOTIC EVIL`, `LAWFUL GOOD`.
RACES = ("ELF", "HALF-ELF", "DWARF", "GNOME", "HALFLING", "HUMAN")
SEXES = ("MALE", "FEMALE")
CLASSES = (
    "CLERIC", "DRUID", "FIGHTER", "PALADIN", "RANGER", "MAGIC-USER",
    "THIEF", "MONK", "CLERIC/FIGHTER", "CLERIC/FIGHTER/M-U", "CLERIC/RANGER",
    "CLERIC/MAGIC-USER", "CLERIC/THIEF", "FIGHTER/MAGIC-USER",
    "FIGHTER/THIEF", "FIGHTER/M-U/THIEF", "MAGIC-USER/THIEF",
)
#: Alignment is one byte, `law * 3 + morality`, drawn from two tables.
LAWS = ("LAWFUL", "NEUTRAL", "CHAOTIC")
MORALITIES = ("GOOD", "NEUTRAL", "EVIL")
ALIGNMENTS = tuple(f"{law} {m}" for law in LAWS for m in MORALITIES)

#: The seven class-level slots are indexed by the single-class code, which is
#: how they were identified: every single-classed specimen on disk 3 has its
#: one non-zero level in the slot its class code names, and the thief `?T`
#: has its 16 in slot 6.
CLASS_LEVEL_SLOTS = CLASSES[:CLASS_LEVEL_COUNT]

#: Read but not written, because no probe has put them on screen. The
#: readings come from the twelve genuine records and are PROBABLE:
#: 0x083-0x087 decode as the five AD&D saving throws for the right class and
#: level; 0x08B-0x092 are non-zero only for the two thieves; 0x0B7 is 13 for
#: the fighter/magic-user/thief and 1, 2, 4, 8 for single-classed ones, which
#: is a class bitmask; 0x089 is the character's level and equals the **highest**
#: of the class levels -- TRIPEL TURBO's 6/6/12 reads 12 there and not 24, so
#: it is a maximum and not a sum; 0x0AB is 4 for a 14th-level fighter and 2 for a
#: magic-user, so it is attacks per round in halves.
SAVING_THROWS = 0x083
SAVING_THROW_COUNT = 5
LEVEL = 0x089
THIEF_SKILLS = 0x08B
THIEF_SKILL_COUNT = 8
ATTACKS_PER_ROUND_HALVES = 0x0AB
CLASS_BITS = 0x0B7
PORTRAIT_BODY = 0x0B8

#: The game recomputes these on load and ignores what the file holds, so the
#: writer must not fill them in: 0x056 encumbrance (it is the coin count),
#: 0x186 `60 - THAC0` (it is the best of the class levels), 0x187 armour
#: class, 0x18B/0x18D/0x18F damage, 0x192 movement.
DERIVED = (0x056, 0x186, 0x187, 0x18B, 0x18D, 0x18F, 0x192)

#: Ramping 0x0B6-0x0C7 makes the loader reject the file with
#: `ERROR: INVALID ITEM (-1/29)`. That is the GLIB library reader's own
#: message -- `Invalid item (%d/%d)` lives in the `LBI` code beside
#: `LBIBase: Invalid Library File` -- and `Disk3_CHEAD.TLB`, the portrait
#: heads, holds exactly 29 items. So the two numbers are a library item index
#: and the library's item count: PoD asked `CHEAD.TLB` for item -1. The
#: region carries a portrait selector, not carried inventory, and **zero in
#: it is accepted**: every payload here has zeros from 0x0B9 up and joins the
#: party.
ITEMS = 0x0B6

#: Which of the fields below a probe has actually put on screen. A field is
#: only CONFIRMED because a number or a word the sheet drew was the one the
#: payload carried.
CONFIDENCE = {
    "name": "CONFIRMED",
    "abilities": "CONFIRMED",
    "exceptional_strength": "PROBABLE",   # shape only; never varied on screen
    "hit_points_max": "CONFIRMED",
    "hit_points_current": "CONFIRMED",
    "movement": "CONFIRMED",
    "class_levels": "CONFIRMED",
    "damage": "CONFIRMED",
    "armour_class": "CONFIRMED",
    "experience": "CONFIRMED",
    "platinum": "CONFIRMED",
    "gems": "CONFIRMED",
    "jewelry": "CONFIRMED",
    "age": "CONFIRMED",
    "race": "CONFIRMED",
    "character_class": "CONFIRMED",
    "sex": "CONFIRMED",
    "alignment": "CONFIRMED",
    "status": "PROBABLE",        # every payload drew OKAY; nothing else tried
    "level": "PROBABLE",
    "saving_throws": "PROBABLE",
    "thief_skills": "PROBABLE",
    "class_bits": "PROBABLE",
    "thac0": "DERIVED",
    "encumbrance": "DERIVED",
}


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


@dataclass(frozen=True)
class PodCharacter:
    """One `Save/NAME.pc`, as far as the character sheet has been read.

    Accepts any buffer long enough for the fields asked of it: PoD itself
    checks no length, and the records on the disks run 484 to 524 bytes while
    the C64 export that loads is 582.
    """

    raw: bytes

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> "PodCharacter":
        if len(data) <= ARMOUR_CLASS:
            raise ValueError(
                f"a .pc must reach at least offset {ARMOUR_CLASS:#05x}, "
                f"got {len(data)} bytes")
        return cls(bytes(data))

    @property
    def name(self) -> str:
        raw = self.raw[NAME:NAME + NAME_LENGTH]
        return raw.split(b"\0")[0].decode("latin1")

    @property
    def abilities(self) -> list[int]:
        """The six scores as the sheet draws them -- the second of each pair."""
        base = ABILITIES + PAIR_CURRENT
        return [self.raw[base + 2 * i] for i in range(ABILITY_COUNT)]

    @property
    def exceptional_strength(self) -> int:
        return self.raw[EXCEPTIONAL_STRENGTH + PAIR_CURRENT]

    @property
    def hit_points_max(self) -> int:
        return self.raw[HP_MAX]

    @property
    def hit_points_current(self) -> int:
        return u16(self.raw, HP_CURRENT)

    @property
    def movement(self) -> int:
        return self.raw[MOVEMENT]

    @property
    def level(self) -> int:
        return self.raw[LEVEL]

    @property
    def class_levels(self) -> list[int]:
        return list(self.raw[CLASS_LEVELS:CLASS_LEVELS + CLASS_LEVEL_COUNT])

    @property
    def saving_throws(self) -> list[int]:
        return list(self.raw[SAVING_THROWS:SAVING_THROWS + SAVING_THROW_COUNT])

    @property
    def thief_skills(self) -> list[int]:
        return list(self.raw[THIEF_SKILLS:THIEF_SKILLS + THIEF_SKILL_COUNT])

    @property
    def class_bits(self) -> int:
        return self.raw[CLASS_BITS]

    @property
    def damage(self) -> tuple[int, int, int]:
        """Dice count, sides and bonus, as `173D175-79` told us they are."""
        return tuple(  # type: ignore[return-value]
            self.raw[DAMAGE_DICE + DAMAGE_STRIDE * i] for i in range(3))

    @property
    def armour_class(self) -> int:
        """The number on the sheet: `60 - stored`, the family's usual bias."""
        return COMBAT_BIAS - self.raw[ARMOUR_CLASS]

    @property
    def experience(self) -> int:
        return u32(self.raw, EXPERIENCE)

    @property
    def platinum(self) -> int:
        return u16(self.raw, PLATINUM)

    @property
    def gems(self) -> int:
        return u16(self.raw, GEMS)

    @property
    def jewelry(self) -> int:
        return u16(self.raw, JEWELRY)

    @property
    def age(self) -> int:
        return u16(self.raw, AGE)

    @property
    def race(self) -> int:
        return self.raw[RACE]

    @property
    def race_name(self) -> str:
        return _name(RACES, self.race)

    @property
    def character_class(self) -> int:
        return self.raw[CLASS]

    @property
    def class_name(self) -> str:
        return _name(CLASSES, self.character_class)

    @property
    def sex(self) -> int:
        return self.raw[SEX]

    @property
    def sex_name(self) -> str:
        return _name(SEXES, self.sex)

    @property
    def alignment(self) -> int:
        return self.raw[ALIGNMENT]

    @property
    def alignment_name(self) -> str:
        return _name(ALIGNMENTS, self.alignment)


def _name(table: tuple[str, ...], index: int) -> str:
    return table[index] if 0 <= index < len(table) else f"?{index}"


@dataclass
class PodWriter:
    """Build a `Save/NAME.pc` Amiga Pools of Darkness will load.

    Only fields a probe has put on the character sheet are written. Everything
    else is left zero, which is what the payloads that loaded had: the heap
    pointers at 0x00-0x5F, the item region from 0x0B6, and the derived block
    the game recomputes anyway. `provenance()` says where every non-zero byte
    of the output came from, so nothing lands in the file uncredited.
    """

    name: str
    race: int = 0
    character_class: int = 0
    sex: int = 0
    alignment: int = 0
    age: int = 0
    experience: int = 0
    platinum: int = 0
    gems: int = 0
    jewelry: int = 0
    abilities: tuple[int, ...] = (10, 10, 10, 10, 10, 10)
    exceptional_strength: int = 0
    hit_points_max: int = 1
    hit_points_current: int | None = None
    movement: int = 12
    class_levels: tuple[int, ...] = field(default=(0,) * CLASS_LEVEL_COUNT)
    damage: tuple[int, int, int] = (1, 2, 0)
    armour_class: int = 10
    #: Written only when the caller asks for them; see CONFIDENCE.
    level: int | None = None
    saving_throws: tuple[int, ...] | None = None
    thief_skills: tuple[int, ...] | None = None
    class_bits: int | None = None

    def _check(self) -> None:
        if not 0 <= self.race < len(RACES):
            raise ValueError(f"race {self.race} is not one of {RACES}")
        if not 0 <= self.character_class < len(CLASSES):
            raise ValueError(f"class {self.character_class} is out of range")
        if not 0 <= self.sex < len(SEXES):
            raise ValueError(f"sex {self.sex} is not 0 or 1")
        if not 0 <= self.alignment < len(ALIGNMENTS):
            raise ValueError(f"alignment {self.alignment} is not 0..8")
        if len(self.abilities) != ABILITY_COUNT:
            raise ValueError("six abilities, in the sheet's own order")
        if len(self.class_levels) != CLASS_LEVEL_COUNT:
            raise ValueError(f"{CLASS_LEVEL_COUNT} class levels")
        if self.armour_class > COMBAT_BIAS:
            raise ValueError("armour class is stored as 60 - AC; 60 is the cap")

    def provenance(self) -> dict[int, str]:
        """Every non-zero byte of the output, and the field that put it there.

        There is deliberately no "template" category: a byte is either a field
        the sheet has shown us or it is zero.
        """
        seen: dict[int, str] = {}
        for offset, width, what in self._plan():
            for i in range(width):
                seen[offset + i] = what
        return seen

    def _plan(self) -> list[tuple[int, int, str]]:
        plan = [
            (NAME, NAME_LENGTH + 1, "name"),
            (RACE, 1, "race"),
            (CLASS, 1, "character_class"),
            (SEX, 1, "sex"),
            (ALIGNMENT, 1, "alignment"),
            (AGE, 2, "age"),
            (EXPERIENCE, 4, "experience"),
            (PLATINUM, 2, "platinum"),
            (GEMS, 2, "gems"),
            (JEWELRY, 2, "jewelry"),
            (ABILITIES, 2 * ABILITY_COUNT, "abilities"),
            (EXCEPTIONAL_STRENGTH, 2, "exceptional_strength"),
            (HP_MAX, 1, "hit_points_max"),
            (HP_CURRENT, 2, "hit_points_current"),
            (MOVEMENT, 1, "movement"),
            (CLASS_LEVELS, CLASS_LEVEL_COUNT, "class_levels"),
            (DAMAGE_DICE, 5, "damage"),
            (ARMOUR_CLASS, 1, "armour_class"),
        ]
        if self.level is not None:
            plan.append((LEVEL, 1, "level"))
        if self.saving_throws is not None:
            plan.append((SAVING_THROWS, SAVING_THROW_COUNT, "saving_throws"))
        if self.thief_skills is not None:
            plan.append((THIEF_SKILLS, THIEF_SKILL_COUNT, "thief_skills"))
        if self.class_bits is not None:
            plan.append((CLASS_BITS, 1, "class_bits"))
        return plan

    def to_bytes(self) -> bytes:
        self._check()
        out = bytearray(RECORD_LENGTH)
        tag = self.name.encode("ascii")[:NAME_LENGTH]
        out[NAME:NAME + NAME_LENGTH] = tag.ljust(NAME_LENGTH, b"\0")
        out[RACE] = self.race
        out[CLASS] = self.character_class
        out[SEX] = self.sex
        out[ALIGNMENT] = self.alignment
        struct.pack_into(">H", out, AGE, self.age)
        struct.pack_into(">I", out, EXPERIENCE, self.experience)
        struct.pack_into(">H", out, PLATINUM, self.platinum)
        struct.pack_into(">H", out, GEMS, self.gems)
        struct.pack_into(">H", out, JEWELRY, self.jewelry)
        for i, score in enumerate(self.abilities):
            out[ABILITIES + 2 * i] = score          # base
            out[ABILITIES + 2 * i + 1] = score      # current, the one drawn
        out[EXCEPTIONAL_STRENGTH] = self.exceptional_strength
        out[EXCEPTIONAL_STRENGTH + 1] = self.exceptional_strength
        out[HP_MAX] = min(self.hit_points_max, 0xFF)
        current = (self.hit_points_max if self.hit_points_current is None
                   else self.hit_points_current)
        struct.pack_into(">H", out, HP_CURRENT, current)
        out[MOVEMENT] = self.movement
        out[CLASS_LEVELS:CLASS_LEVELS + CLASS_LEVEL_COUNT] = bytes(
            self.class_levels)
        for i, part in enumerate(self.damage):
            out[DAMAGE_DICE + DAMAGE_STRIDE * i] = part
        out[ARMOUR_CLASS] = COMBAT_BIAS - self.armour_class
        if self.level is not None:
            out[LEVEL] = self.level
        if self.saving_throws is not None:
            out[SAVING_THROWS:SAVING_THROWS + SAVING_THROW_COUNT] = bytes(
                self.saving_throws)
        if self.thief_skills is not None:
            out[THIEF_SKILLS:THIEF_SKILLS + THIEF_SKILL_COUNT] = bytes(
                self.thief_skills)
        if self.class_bits is not None:
            out[CLASS_BITS] = self.class_bits
        return bytes(out)



# ---------------------------------------------------------------------------
# Anything -> Amiga: the writing half of the pair `goldbox/neutral.py` describes
# ---------------------------------------------------------------------------
# The middle is a `NeutralCharacter`, the same record `goldbox/dos.py` reads into
# and `goldbox/c64_codec.py` writes out of. Nothing here reads a `CharacterRecord`
# and nothing here reads another codec's output: this module is one writer, it
# names neutral fields, and what produced them is somebody else's business.
# That is what makes a fourth format cost one reader rather than a converter
# per pair.
#
# The direction is one way. `wish` never reads an Amiga record back into a C64
# save, and `docs/124-amiga-port.md` sec 9 says why: there is no C64 Pools of
# Darkness to go back to.


#: Gold Box race names -> PoD's own six-entry table. The C64 tables differ per
#: title (`goldbox/games.py`), which is exactly why the conversion goes by name
#: and not by number: the neutral `race` is an index into the *source title's*
#: table and `goldbox.games.race_table` is what turns it into a name.
RACE_FROM_C64: dict[str, str] = {
    "elf": "ELF",
    "half-elf": "HALF-ELF",
    "dwarf": "DWARF",
    "gnome": "GNOME",
    "halfling": "HALFLING",
    "human": "HUMAN",
}

#: Races Pools of Darkness does not have, and the nearest thing it does. Every
#: one of these is a substitution and every one is reported: a half-orc who
#: arrives as a human is a changed character, not a converted one.
RACE_SUBSTITUTE: dict[str, tuple[str, str]] = {
    "half-orc": ("HUMAN", "Pools of Darkness cannot roll a half-orc"),
    "monster": ("HUMAN", "`monster` is a Pool of Radiance NPC marker, not a "
                         "race Pools of Darkness knows"),
    "silvanesti elf": ("ELF", "a Krynn race; Pools of Darkness is the Realms"),
    "qualinesti elf": ("ELF", "a Krynn race; Pools of Darkness is the Realms"),
    "mountain dwarf": ("DWARF", "a Krynn race; Pools of Darkness has one "
                                "dwarf"),
    "hill dwarf": ("DWARF", "a Krynn race; Pools of Darkness has one dwarf"),
    "kender": ("HALFLING", "a Krynn race; halfling is the Realms' nearest"),
}

#: Class name -> the slot its level occupies in the seven-byte array at 0x09D.
#: The array is indexed by PoD's *single-class* code, which is how it was
#: identified: every single-classed specimen on disk 3 has its one non-zero
#: level in the slot its class code names.
CLASS_LEVEL_SLOT: dict[str, str] = {
    "cleric": "CLERIC",
    "fighter": "FIGHTER",
    "paladin": "PALADIN",
    "ranger": "RANGER",
    "magic-user": "MAGIC-USER",
    "thief": "THIEF",
}

#: Classes Pools of Darkness does not have. The Knight of Solamnia is Krynn's
#: and has no Realms equivalent; a knight arrives as a fighter, reported.
CLASS_SUBSTITUTE: dict[str, tuple[str, str]] = {
    "knight": ("fighter", "the Knight of Solamnia is a Krynn class; Pools of "
                          "Darkness has no slot for it"),
}

#: The class bitmask at 0x0B7, read off the twelve genuine records: magic-user
#: 1, cleric 2, thief 4, fighter 8 -- which is the C64's own numbering -- and
#: **64 for both the paladin and the ranger**, where the C64 gives them 0x40
#: and 0x80 separately. So the mask is *not* the neutral `class_bits` byte and
#: must not be copied across. PROBABLE: the twelve agree, but no probe has put
#: the byte on screen.
CLASS_BIT: dict[str, int] = {
    "magic-user": 1, "cleric": 2, "thief": 4, "fighter": 8,
    "paladin": 64, "ranger": 64,
}

#: Class combinations -> PoD's class code. Only the combinations both ports
#: have; a combination PoD's table has no entry for is refused rather than
#: written as something else, which is `yaml_io.class_code_for`'s rule too.
CLASS_CODE_FROM_C64: dict[frozenset[str], str] = {
    frozenset(k.split("+")): v for k, v in {
        "cleric": "CLERIC",
        "fighter": "FIGHTER",
        "paladin": "PALADIN",
        "ranger": "RANGER",
        "magic-user": "MAGIC-USER",
        "thief": "THIEF",
        "cleric+fighter": "CLERIC/FIGHTER",
        "cleric+fighter+magic-user": "CLERIC/FIGHTER/M-U",
        "cleric+ranger": "CLERIC/RANGER",
        "cleric+magic-user": "CLERIC/MAGIC-USER",
        "cleric+thief": "CLERIC/THIEF",
        "fighter+magic-user": "FIGHTER/MAGIC-USER",
        "fighter+thief": "FIGHTER/THIEF",
        "fighter+magic-user+thief": "FIGHTER/M-U/THIEF",
        "magic-user+thief": "MAGIC-USER/THIEF",
    }.items()
}

#: The neutral `alignment` is `law * 3 + morality`, which is PoD's own byte.
#: Spelled out rather than assumed, because the two encodings agreeing is a
#: fact about them and not a rule.
ALIGNMENT_NAMES: tuple[str, ...] = ALIGNMENTS

#: The six abilities in the order the sheet draws them.
ABILITY_KEYS = ("strength", "intelligence", "wisdom", "dexterity",
                "constitution", "charisma")

SAVE_KEYS = ("save_paralysis", "save_petrification", "save_wands",
             "save_breath", "save_spell")

THIEF_KEYS = ("thief_pick_pockets", "thief_open_locks", "thief_find_traps",
              "thief_move_silently", "thief_hide_in_shadows",
              "thief_hear_noise", "thief_climb_walls",
              "thief_read_languages")

#: What an unarmoured, unarmed character is, and what all twelve genuine
#: records hold: armour class 10 and 1d2. **Not** carried from the source. A
#: Gold Box armour class is a cache that already includes worn armour and a
#: dexterity bonus, PoD re-applies dexterity itself, and no item crosses -- so
#: a converted character genuinely arrives with nothing on and 10 is the right
#: answer rather than a lossy one.
UNARMOURED_AC = 10
UNARMED_DAMAGE = (1, 2, 0)

#: AmigaDOS names on disk 3: uppercase, spaces removed, eight characters.
#: `MAGIC JHONSON` is `MAGICJHO.pc` and `TRIPEL TURBO` is `TRIPELTU.pc`.
FILENAME_LENGTH = 8


class ConversionError(ValueError):
    """A character Pools of Darkness has no way to represent."""


@dataclass
class Report(neutral.Report):
    """Where every non-zero byte of the `.pc` came from, and what stayed.

    The same bargain `goldbox/c64_codec.py` strikes in the other direction, in the
    one shape `goldbox/neutral.py` gives every direction: a field the Amiga cannot
    hold is *named*, never dropped quietly.  `unaccounted` is the acceptance
    test -- `docs/124-amiga-port.md` phase 6 asks for a provenance report with
    no "template" category, and a byte is either a field a probe put on the
    character sheet or it is zero.  **Only the non-zero bytes have to be
    explained**, which is where this differs from the C64's report.
    """

    total: int = RECORD_LENGTH

    @property
    def length(self) -> int:
        """What this report calls its size. `docs/124` counts `.pc` bytes."""
        return self.total

    def unaccounted(self, record: bytes) -> list[int]:  # type: ignore[override]
        """Non-zero output bytes this report cannot explain. Always empty."""
        return [i for i, b in enumerate(record)
                if b and i not in self.sources]


#: Neutral field -> the Amiga field it becomes, where the value crosses
#: unchanged.
DIRECT: tuple[tuple[str, str], ...] = (
    ("age", "age"),
    ("movement", "movement"),
    ("experience", "experience"),
    ("platinum", "platinum"),
    ("gems", "gems"),
    ("jewelry", "jewelry"),
    ("exceptional_strength", "exceptional_strength"),
    ("level", "level"),
    ("sex", "sex"),
    ("alignment", "alignment"),
)

#: Neutral fields converted by a rule rather than by a copy.
TRANSFORMED: tuple[tuple[str, str], ...] = (
    ("name", "truncated to the Amiga's fifteen characters at 0x060"),
    ("race", "index -> name in the source title's table -> PoD's own six; a "
             "race PoD lacks is substituted and reported"),
    ("class_bits", "names -> PoD's 17-entry class code at 0x059 and its own "
                   "class bitmask at 0x0B7, which is not this byte"),
    ("char_class", "recomputed from `class_bits`; the two ports' class codes "
                   "are different tables"),
    ("levels", "spread into the seven-slot array at 0x09D, indexed by PoD's "
               "single-class code"),
    ("hp_max", "a Gold Box maximum is 16 bits, the Amiga's one byte at 0x081; "
               "above 255 it is clamped and reported"),
    ("hp_current", "copied to the u16 at 0x190, capped at the maximum the "
                   "Amiga byte could hold"),
    *((k, "one of the six abilities at 0x070, written to both halves of its "
          "base/current pair") for k in ABILITY_KEYS),
    *((k, "one of the five saving throws at 0x083, in the same order: the "
          "twelve genuine records decode to the AD&D table for their class "
          "and level in exactly this order") for k in SAVE_KEYS),
    *((k, "one of the eight thief skills at 0x08B, in the same order: hear "
          "noise is low and climb walls high in both") for k in THIEF_KEYS),
)

#: Neutral fields deliberately left behind, and why. Reported, never silent:
#: `neutral.Writer.finish` quotes these for whatever the character carries,
#: and :func:`field_disposition` states the whole contract whether or not any
#: one character happens to carry it.
DROPPED: tuple[tuple[str, str], ...] = (
    ("copper", "only platinum, gems and jewelry have been located in the "
               "`.pc`; the lighter coins have no known home"),
    ("silver", "no located home -- see `copper`"),
    ("electrum", "no located home -- see `copper`"),
    ("gold", "no located home -- see `copper`"),
    ("infravision", "no located home; PoD derives what it needs from race"),
    ("hp_rolled", "the pre-constitution roll; the Amiga keeps only the "
                  "maximum"),
    ("hp_lost_to_drain", "level drain is bookkeeping the Amiga record has no "
                         "located home for -- see `levels_drained`"),
    ("levels_drained", "no located home; a drained character arrives at the "
                       "levels the record actually holds"),
    ("portrait_head", "PoD's art is `CHEAD.TLB`, a different set with "
                      "different numbering. A copied index is a wrong "
                      "picture, silently"),
    ("portrait_body", "PoD's art is `CBODY.TLB` -- see `portrait_head`"),
    ("inventory", "the appended item region past 484 bytes is undecoded, and "
                  "a Pool of Radiance item id and a Pools of Darkness one are "
                  "two different games' tables. The character arrives "
                  "carrying nothing"),
    ("innate_effects", "racial abilities and item powers share one id "
                       "namespace with the C64's, and PoD's is a third; "
                       "nothing here can be crossed by number"),
    ("spells_memorised", "PoD runs cleric spells to level 7 and mage to 9, so "
                         "its id space is larger than the C64's 1-56 and the "
                         "mapping is not the identity. Re-memorise in game"),
    ("spells_known", "the spellbook's home in the `.pc` is undecoded -- see "
                     "`spells_memorised`"),
    ("spells_castable", "slots free per level follow from class and level, "
                        "which PoD recomputes on load"),
    ("npc", "a roster flag of the source save; PoD decides for itself what it "
            "has just imported"),
    ("party_order", "the marching order of a party the character is leaving"),
    ("encumbrance", "PoD recomputes it: a probe that set it to 1234 drew 233, "
                    "which is the character's own coins, gems and jewelry"),
    ("size_small", "no located home; PoD takes size from race"),
    ("turn_power", "no located home for a cleric's turning strength"),
    ("attack_level", "no located home; PoD reads its attack tables at the "
                     "class level"),
    ("attack_forms", "the running attack-form bytes are combat state, and the "
                     "0x0AD damage triple is written unarmed instead"),
    ("roster_tail", "the source roster's derived block: armour bonus and the "
                    "running attack forms, all of which PoD recomputes"),
    ("thac0_base", "PoD recomputes THAC0 on load from the class levels and "
                   "ignores what the file holds"),
    ("thac0_current", "recomputed on load -- see `thac0_base`"),
    ("armour_class", "recomputed on load; the record gets the unarmoured "
                     "constant instead"),
    ("armour_class_base", "recomputed on load -- see `armour_class`"),
    ("movement_current", "recomputed on load: a probe that set the derived "
                         "movement to 99 drew the base's 12"),
)


def field_disposition() -> dict[str, str]:
    """Every neutral field and what this writer does with it.

    The test that keeps this module honest: a field `goldbox/neutral.py` declares
    and this table does not name would be a field silently dropped.  The
    shape is `goldbox/neutral.py`'s, so every direction reports the same way.
    """
    return neutral.disposition(DIRECT, TRANSFORMED, DROPPED, "the Amiga's")


def pc_filename(name: str) -> str:
    """The AmigaDOS name PoD's picker lists a character under.

    Uppercase, spaces and punctuation removed, eight characters. Read off
    disk 3: `MAGIC JHONSON` is `MAGICJHO.pc`, `TRIPEL TURBO` is `TRIPELTU.pc`
    and `?T` is `T.pc`.
    """
    stem = "".join(c for c in name.upper() if c.isalnum())[:FILENAME_LENGTH]
    if not stem:
        raise ConversionError(f"{name!r} leaves no AmigaDOS file name")
    return f"{stem}.pc"


#: A trailing digit, tried in the eighth character's place, for a name that
#: collides with one already claimed in the same export (#79). The genuine
#: disks have no collision to learn a scheme from, so this one is ours.
_DISAMBIGUATING_DIGITS = "23456789"


def _unique_pc_filename(base: str, used: set[str]) -> str:
    """`base`, if it is not already in `used`; otherwise a variant that is not.

    `LADY KATHERINE` and `LADY KATHRYN` both give the base `LADYKATH.pc`; the
    second one written gets `LADYKAT2.pc` instead of silently overwriting the
    first. The name is shortened rather than the `.pc` extension dropped, so
    the result is still an AmigaDOS name of the length `pc_filename` promises.
    """
    if base not in used:
        return base
    stem = base[:-len(".pc")]
    for digit in _DISAMBIGUATING_DIGITS:
        candidate = f"{stem[:FILENAME_LENGTH - 1]}{digit}.pc"
        if candidate not in used:
            return candidate
    raise ConversionError(
        f"no AmigaDOS file name distinct from {base!r} is left to try")


def _classes_of(names) -> tuple[list[str], list[str]]:
    """The character's classes as PoD names them, plus any substitutions."""
    warnings: list[str] = []
    out: list[str] = []
    for raw in names or []:
        if not isinstance(raw, str):
            raise ConversionError(
                f"class {raw!r} is a raw bitmask -- this title's class table "
                f"is not known, so there is nothing to convert by name")
        key = raw.strip().lower()
        if key in CLASS_SUBSTITUTE:
            replacement, why = CLASS_SUBSTITUTE[key]
            warnings.append(f"Class {key} -> {replacement}: {why}")
            key = replacement
        if key not in CLASS_LEVEL_SLOT:
            raise ConversionError(
                f"Pools of Darkness has no class matching {raw!r}")
        out.append(key)
    if not out:
        raise ConversionError("a character with no class cannot be converted")
    return out, warnings


def write(char: NeutralCharacter) -> tuple[PodWriter, Report]:
    """Build a `Save/NAME.pc` writer from a neutral character, and its report.

    Everything the Amiga cannot hold lands in `Report.dropped`; everything it
    holds differently lands in `Report.warnings`.
    """
    rep = Report()
    w = neutral.Writer(char, rep, into="Amiga", dropped=DROPPED)

    def num(name: str, default: int = 0) -> int:
        """One neutral field as a number, taken and counted as consumed."""
        v = w.use(name)
        return default if v is None else int(v.value)

    name_value = w.use("name")
    name = str(name_value.value if name_value else "").rstrip("\0").strip()
    if not name:
        raise ConversionError("a character with no name cannot be converted")
    if len(name) > NAME_LENGTH:
        rep.warnings.append(
            f"Name {name!r} is {len(name)} characters; PoD keeps "
            f"{NAME_LENGTH}, so it arrives as {name[:NAME_LENGTH]!r}")

    race_value = w.use("race")
    race_key = str(_races(char).get(
        race_value.value if race_value else None, "")).strip().lower()
    if race_key in RACE_SUBSTITUTE:
        replacement, why = RACE_SUBSTITUTE[race_key]
        rep.warnings.append(f"Race {race_key} -> {replacement.lower()}: {why}")
        race_name = replacement
    elif race_key in RACE_FROM_C64:
        race_name = RACE_FROM_C64[race_key]
    else:
        raise ConversionError(
            f"race {race_value.value if race_value else None!r} has no Pools "
            f"of Darkness equivalent")

    sex = w.use("sex")
    if sex is None or sex.value not in (0, 1):
        raise ConversionError(
            f"sex {sex.value if sex else None!r} is not male or female")

    align = w.use("alignment")
    if align is None or not 0 <= align.value < len(ALIGNMENT_NAMES):
        raise ConversionError(
            f"alignment {align.value if align else None!r} is not one of "
            f"{', '.join(ALIGNMENT_NAMES)}")

    bits = w.use("class_bits")
    classes, class_warnings = _classes_of(
        games.classes_to_names(bits.value if bits else 0, char.game))
    rep.warnings.extend(class_warnings)
    w.use("char_class")
    combination = frozenset(classes)
    if combination not in CLASS_CODE_FROM_C64:
        raise ConversionError(
            "Pools of Darkness has no class code for "
            + "/".join(sorted(classes))
            + "; its table is: " + ", ".join(sorted(
                v for v in CLASS_CODE_FROM_C64.values())))

    level_value = w.use("levels")
    levels = {str(k).strip().lower(): int(v)
              for k, v in (level_value.value if level_value else {}).items()}
    slots = [0] * CLASS_LEVEL_COUNT
    for class_name in classes:
        level = levels.get(class_name, 0)
        # A knight's level arrives under its own name, not the fighter's.
        if not level:
            for original, (replacement, _) in CLASS_SUBSTITUTE.items():
                if replacement == class_name:
                    level = levels.get(original, level)
        slots[CLASS_LEVEL_SLOTS.index(CLASS_LEVEL_SLOT[class_name])] = level

    max_hp = w.use("hp_max")
    hp_max = int(max_hp.value if max_hp else 0)
    if hp_max > 0xFF:
        rep.warnings.append(
            f"Hit points maximum {hp_max} does not fit the Amiga's one byte "
            f"at {HP_MAX:#05x}; clamped to 255")
        hp_max = 0xFF

    lighter = sum(int(w.get(k) or 0)
                  for k in ("copper", "silver", "electrum", "gold"))
    if lighter:
        rep.warnings.append(
            f"{lighter} copper, silver, electrum and gold pieces are left "
            f"behind: only platinum, gems and jewelry have a located home in "
            f"the .pc")

    rep.dropped.append(
        "armour class and damage: a Gold Box armour class is a cache that "
        "already includes worn armour and a strength bonus, no item crosses, "
        "and PoD re-applies dexterity itself -- so the record gets an "
        f"unarmoured {UNARMOURED_AC} and "
        f"{UNARMED_DAMAGE[0]}d{UNARMED_DAMAGE[1]}, which is what all twelve "
        "genuine records hold")

    current = w.use("hp_current")
    if current is None:
        hp_current = hp_max
        rep.warnings.append(
            "No current hit points in the source, so they are set to the "
            "maximum")
    else:
        hp_current = min(int(current.value), hp_max)

    writer = PodWriter(
        name=name[:NAME_LENGTH],
        race=RACES.index(race_name),
        character_class=CLASSES.index(CLASS_CODE_FROM_C64[combination]),
        sex=int(sex.value),
        alignment=int(align.value),
        age=num("age"),
        experience=num("experience"),
        platinum=num("platinum"),
        gems=num("gems"),
        jewelry=num("jewelry"),
        abilities=tuple(num(k) for k in ABILITY_KEYS),
        exceptional_strength=num("exceptional_strength"),
        hit_points_max=hp_max,
        hit_points_current=hp_current,
        movement=num("movement"),
        class_levels=tuple(slots),
        damage=UNARMED_DAMAGE,
        armour_class=UNARMOURED_AC,
        level=num("level") or max(slots),
        saving_throws=tuple(num(k) for k in SAVE_KEYS),
        thief_skills=tuple(num(k) for k in THIEF_KEYS),
        class_bits=sum(CLASS_BIT[c] for c in set(classes)),
    )
    w.finish()
    return writer, rep


def _races(char: NeutralCharacter) -> dict[int, str]:
    """The source title's race table, so an index can be named."""
    return games.race_table(char.game)


def to_pc(char: NeutralCharacter) -> tuple[bytes, Report]:
    """One neutral character as the 484 bytes of a `Save/NAME.pc`."""
    writer, rep = write(char)
    record = writer.to_bytes()
    for offset, who in writer.provenance().items():
        rep.sources[offset] = f"{who} <- {char.port} {_SOURCE_OF.get(who, who)}"
    return record, rep


#: Which neutral field each written Amiga field came from, for the provenance
#: report. Kept beside the writer's own plan so the two cannot drift apart
#: without a test noticing.
_SOURCE_OF: dict[str, str] = {
    "name": "name",
    "race": "race",
    "character_class": "class_bits",
    "sex": "sex",
    "alignment": "alignment",
    "age": "age",
    "experience": "experience",
    "platinum": "platinum",
    "gems": "gems",
    "jewelry": "jewelry",
    "abilities": "strength/intelligence/wisdom/dexterity/constitution/charisma",
    "exceptional_strength": "exceptional_strength",
    "hit_points_max": "hp_max",
    "hit_points_current": "hp_current",
    "movement": "movement",
    "class_levels": "levels",
    "damage": "nothing -- unarmed 1d2, the constant all twelve records hold",
    "armour_class": "nothing -- unarmoured 10, the constant all twelve hold",
    "level": "level",
    "saving_throws": "save_paralysis..save_spell",
    "thief_skills": "thief_pick_pockets..thief_read_languages",
    "class_bits": "class_bits",
}


def export_party(save_path, out_dir, game_disk=None) -> list[tuple]:
    """A whole C64 party from a save disk into a `SAVE` drawer's worth of
    `.pc` files.

    Returns one `(path, Report)` per character. The C64 disk is opened
    read-only; `out_dir` is created if it is not there.  `game_disk` is
    accepted and unused: it names items, and no item crosses.
    """
    import pathlib

    from . import c64_codec
    from .d64 import D64
    from .savegame import load_save

    img = D64.open(str(save_path))
    game, sg0, sg1 = load_save(img)
    root = pathlib.Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)

    # Every name in the party is decided before anything is written, so a
    # collision is disambiguated rather than the second character silently
    # overwriting the first one's file (#79).
    used: set[str] = set()
    out = []
    for slot in sg0.characters:
        char = c64_codec.read(
            slot.record,
            roster=sg1.roster(slot.index) if sg1 is not None else None,
            game=game, source=str(save_path))
        record, rep = to_pc(char)
        base = pc_filename(str(char.get("name")))
        filename = _unique_pc_filename(base, used)
        if filename != base:
            rep.warnings.append(
                f"The file name {base!r} is already used by another "
                f"character in this export; written instead as {filename!r}")
        used.add(filename)
        path = root / filename
        path.write_bytes(record)
        out.append((path, rep))
    return out


# ---------------------------------------------------------------------------
# Amiga Pool of Radiance: the same record as DOS, big-endian, three bytes wider
# ---------------------------------------------------------------------------
#
# `CHRDATA<n>.sav` on an Amiga Pool of Radiance save disk, and `<NAME>.cha`
# where a party has been exported, is **288 bytes**: the 285-byte DOS record
# of `goldbox/dos_layout.py` with the multi-byte fields byte-swapped, the name
# re-encoded, and three insertions.  Nothing here is a second field table --
# the DOS one is read through a shift map, so the two cannot drift apart.
#
# The three insertions, measured on fourteen specimens (#27):
#
#   * `0x07F` -- one pad byte, zero in 14 of 14, ahead of the effect-chain
#     pointer.  DOS keeps an offset word and a segment word there; the Amiga
#     keeps one `u32` and a 68000 compiler even-aligns it.
#   * somewhere in DOS `0x083`-`0x087` -- **located to a window, not a byte**.
#     That region is zero in 12 of the 14, so no file differential can place
#     it; what would is a ramp probe under the emulator.  The money block
#     that follows is `u16`, so alignment says the pad is at the end of the
#     window, but that is inference and is not graded.
#   * `0x11F`, the last byte -- 285 + 2 is odd, and the struct is padded to an
#     even size.  Junk in 3 of 14 and zero in the rest, which is what an
#     uninitialised pad looks like.
#
# So a DOS offset maps to an Amiga offset by adding 0 below `0x07F`, 1 through
# the effect pointer, and 2 from the money block on.
AMIGA_POR_RECORD_SIZE = 288
AMIGA_POR_NAME_SIZE = 16          # NUL-padded, where DOS has a count byte
AMIGA_POR_PAD = 0x07F             # the first insertion
AMIGA_POR_TAIL_PAD = 0x11F        # the third
#: `(first DOS offset, bytes inserted before it)`, ascending.
AMIGA_POR_SHIFTS = ((0x000, 0), (0x07F, 1), (0x088, 2))
#: DOS offsets whose Amiga counterpart cannot be placed: the second insertion
#: is somewhere inside this run, so every byte of it is suspect.
AMIGA_POR_UNPLACED = range(0x083, 0x088)


class AmigaRecordError(ValueError):
    """A buffer that is not an Amiga Pool of Radiance character record."""


def amiga_por_offset(dos_offset: int) -> int:
    """Where a DOS record offset lands in the Amiga one.

    Raises for the unplaced window rather than guessing: a caller that wants
    those bytes has to say so and read them raw.
    """
    if dos_offset in AMIGA_POR_UNPLACED:
        raise AmigaRecordError(
            f"DOS offset {dos_offset:#05x} is inside {AMIGA_POR_UNPLACED.start:#05x}"
            f"-{AMIGA_POR_UNPLACED.stop - 1:#05x}, where the second insertion "
            f"has not been located; there is no Amiga offset to give")
    shift = 0
    for first, amount in AMIGA_POR_SHIFTS:
        if dos_offset >= first:
            shift = amount
    return dos_offset + shift


@dataclass(frozen=True)
class AmigaPorCharacter:
    """One Amiga Pool of Radiance character, read through the DOS table.

    `items` and `effects` are the sibling `.itm` and `.spc` files when there
    are any; an exported `.cha` normally has neither, and the record's own
    `item_count` is what says how much of a `.itm` belongs here.
    """

    raw: bytes
    source: str = ""
    items: tuple["AmigaPorItem", ...] = ()
    effects: tuple[bytes, ...] = ()

    @classmethod
    def from_bytes(cls, data: bytes | bytearray, source: str = "",
                   items: Sequence["AmigaPorItem"] = (),
                   effects: Sequence[bytes] = ()) -> "AmigaPorCharacter":
        if len(data) != AMIGA_POR_RECORD_SIZE:
            raise AmigaRecordError(
                f"an Amiga Pool of Radiance record is "
                f"{AMIGA_POR_RECORD_SIZE} bytes, got {len(data)}; the Amiga "
                f"Curse record is 428 and Pools of Darkness's .pc is 484")
        return cls(bytes(data), source, tuple(items), tuple(effects))

    @property
    def name(self) -> str:
        raw = self.raw[:AMIGA_POR_NAME_SIZE]
        return raw.split(b"\0")[0].decode("latin1")

    def get(self, field_name: str):
        """One field, by its `goldbox/dos_layout.py` name.

        `U16LE` and `UINT_LE` fields are read big-endian, which is the whole
        of the difference outside the name and the shifts.
        """
        f = dos_layout.FIELDS_BY_NAME.get(field_name)
        if f is None:
            raise AmigaRecordError(f"no field called {field_name!r}")
        at = amiga_por_offset(f.offset)
        chunk = self.raw[at:at + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            return int.from_bytes(chunk, "big")
        if f.kind is Kind.I8:
            return int.from_bytes(chunk, "big", signed=True)
        if f.kind is Kind.U8:
            return chunk[0]
        return chunk

    @property
    def abilities(self) -> list[int]:
        return [self.get(k) for k in ("strength", "intelligence", "wisdom",
                                      "dexterity", "constitution", "charisma")]

    @property
    def experience(self) -> int:
        """Four bytes big-endian, spanning DOS's 24-bit field and `gap_0af`.

        The Amiga's field is `u32`, and the shift stays at +2 across it -- so
        DOS's unexplained `gap_0af` is experience's fourth byte and the DOS
        field is a `u32le`.  PROBABLE: 14 of 14 Amiga specimens decode to
        experience totals in their class's band or just past a level cap.
        """
        at = amiga_por_offset(dos_experience_offset())
        return int.from_bytes(self.raw[at:at + 4], "big")

    @property
    def effect_chain(self) -> int:
        """The `.spc` chain head, `u32` big-endian where DOS keeps two words."""
        return int.from_bytes(self.raw[0x080:0x084], "big")

    @property
    def money(self) -> dict[str, int]:
        return {k: self.get(k) for k in
                ("copper", "silver", "electrum", "gold", "platinum", "gems",
                 "jewelry")}


def dos_experience_offset() -> int:
    return dos_layout.FIELDS_BY_NAME["experience"].offset


def read_amiga_por(path) -> AmigaPorCharacter:
    """One Amiga Pool of Radiance `.cha` or `CHRDATA<n>.sav`.

    The sibling `.itm` and `.spc` are read too where they are there.  The
    record's own `item_count` is what says how many of the `.itm` belong to
    this character -- an export zeroes it, and a stale `.itm` left beside one
    would otherwise hand it somebody else's gear.  `goldbox/dos.py` reads the DOS
    files the same way and for the same reason.
    """
    import pathlib

    path = pathlib.Path(path)
    data = path.read_bytes()
    char = AmigaPorCharacter.from_bytes(data, source=str(path))
    itm = _sibling_bytes(path, ".itm")
    spc = _sibling_bytes(path, ".spc")
    count = min(char.get("item_count"), len(itm) // AMIGA_POR_ITEM_SIZE)
    items = [AmigaPorItem.from_bytes(
        itm[i * AMIGA_POR_ITEM_SIZE:(i + 1) * AMIGA_POR_ITEM_SIZE])
        for i in range(count)]
    effects = [spc[i:i + AMIGA_POR_EFFECT_SIZE]
               for i in range(0, len(spc), AMIGA_POR_EFFECT_SIZE)
               if len(spc[i:i + AMIGA_POR_EFFECT_SIZE]) == AMIGA_POR_EFFECT_SIZE]
    return AmigaPorCharacter.from_bytes(data, str(path), items, effects)


def _sibling_bytes(path, suffix: str) -> bytes:
    """A `.itm` or `.spc` beside the record, on either case of the name."""
    for candidate in (path.with_suffix(suffix), path.with_suffix(suffix.upper())):
        if candidate.exists() and candidate != path:
            return candidate.read_bytes()
    return b""


# ---------------------------------------------------------------------------
# The Amiga Pool of Radiance item file: 65 bytes where DOS spends 63
# ---------------------------------------------------------------------------
#
# `CHRDATA<n>.itm` beside the record, one 65-byte node per item, and the
# record's own `item_count` says how many belong to that character -- 3, 3, 3,
# 3, 3 and 2 against files of 195, 195, 195, 195, 195 and 130 bytes on the
# party shipped on Amiga disk 1, which is 6 of 6 exact.
#
# It is the DOS 63-byte record with **two insertions**, and the whole of the
# decode is one arithmetic identity that cannot be satisfied by accident:
# `money + sum(weight x quantity)` equals the record's own derived
# encumbrance word for **all six characters**, which fixes the money offsets,
# the 65-byte stride, the weight and quantity offsets and the byte order
# together.  Seventeen item nodes, nine distinct items; every weight is the
# published AD&D one (Long Sword 60, Chain Mail 300, Shield 100, Darts 5) and
# every value matches the price the item's own cached display line carries.
#
#   * DOS's count byte is gone.  The Amiga writes **NUL-separated text** from
#     offset 0 -- `Chain Mail\0Mail\0          75\0` -- so the display line is
#     the first NUL-terminated run, and 42 bytes serve where DOS spends a
#     length byte and 41.
#   * One pad in DOS `0x035`-`0x037`, which even-aligns the `u16` weight at
#     Amiga `0x038`.  Zero in all 17, so which of the three is UNKNOWN.
#   * One pad at Amiga `0x03B`, and this one **is** located to the byte:
#     quantity is measured at `0x03A` (60, on the only stack in the corpus,
#     against a display line reading `60 Darts`) and value at `0x03C`.
#
# `readied` at `0x034` is the flag `#55 (Decode the Amiga Curse and Silver
# Blades records)` could not confirm on Curse, where every specimen was
# readied: the un-readied darts read 0 here and their display line reads
# ` No `, and every other item reads 1 and draws ` Yes `.
AMIGA_POR_ITEM_SIZE = 65
#: Bytes of NUL-separated display text before the `next` pointer.
AMIGA_POR_ITEM_TEXT = 0x02A
#: `(first DOS item offset, bytes inserted before it)`, ascending.
AMIGA_POR_ITEM_SHIFTS = ((0x000, 0), (0x037, 1), (0x03A, 2))
#: The first insertion is one byte somewhere in here; all three read zero.
AMIGA_POR_ITEM_PAD_WINDOW = range(0x035, 0x038)
#: The second insertion, located to the byte between quantity and value.
AMIGA_POR_ITEM_PAD = 0x03B


def amiga_por_item_offset(dos_offset: int) -> int:
    """Where a DOS item offset lands in the Amiga one.

    Unlike the record's map this one never refuses: both insertions sit past
    the last field a caller reads by DOS offset, and the text field is
    re-cut rather than shifted.
    """
    shift = 0
    for first, amount in AMIGA_POR_ITEM_SHIFTS:
        if dos_offset >= first:
            shift = amount
    return dos_offset + shift


@dataclass(frozen=True)
class AmigaPorItem:
    """One 65-byte node of an Amiga Pool of Radiance `.itm` file."""

    raw: bytes

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> "AmigaPorItem":
        if len(data) != AMIGA_POR_ITEM_SIZE:
            raise AmigaRecordError(
                f"an Amiga Pool of Radiance item is {AMIGA_POR_ITEM_SIZE} "
                f"bytes, got {len(data)}; the Amiga Curse item is 66 and the "
                f"DOS item is {dos_layout.ITEM_SIZE}")
        return cls(bytes(data))

    def get(self, field_name: str):
        """One field, by its `goldbox/dos_layout.py` item name, big-endian."""
        f = dos_layout.ITEM_FIELDS_BY_NAME.get(field_name)
        if f is None:
            raise AmigaRecordError(f"no item field called {field_name!r}")
        at = amiga_por_item_offset(f.offset)
        chunk = self.raw[at:at + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            return int.from_bytes(chunk, "big")
        if f.kind is Kind.I8:
            return int.from_bytes(chunk, "big", signed=True)
        if f.kind is Kind.U8:
            return chunk[0]
        return chunk

    @property
    def display_line(self) -> str:
        """The line the game last drew -- **never a source**.

        Stale by construction on both ports: the buffer is written over in
        place, so `Chain Mail\\0Mail\\0` is a short name sitting on the tail of
        a longer one, and the ` Yes `/` No ` column appears only on the items
        the ITEMS screen last painted it onto.  `goldbox/dos.py` records the same
        of the DOS buffer, where a stack of darts reads `11 Darts` over a
        quantity of 8.
        """
        return self.raw[:AMIGA_POR_ITEM_TEXT].split(b"\0")[0].decode(
            "ascii", "replace")

    @property
    def next_node(self) -> int:
        """The heap address of the next item, `u32` big-endian, NULL last."""
        return int.from_bytes(self.raw[0x02A:0x02E], "big")

    def to_dos_bytes(self) -> bytes:
        """This item as the 63 bytes `goldbox/dos_layout.py` describes.

        The `next` far pointer is written NULL rather than carried: it is a
        live Amiga heap address, and the DOS engine rebuilds its own chain
        from the file's length regardless (`goldbox/dos.py`, `EFFECT_NEXT_NULL`
        records the same measurement for the effect chain).
        """
        out = bytearray(dos_layout.ITEM_SIZE)
        text = self.raw[:AMIGA_POR_ITEM_TEXT]
        line = text.split(b"\0")[0]
        size = dos_layout.ITEM_FIELDS_BY_NAME["text"].size
        out[0] = min(len(line), size)
        out[1:1 + size] = text[:size].ljust(size, b"\0")
        for f in dos_layout.ITEM_LAYOUT:
            if f.name in ("text_length", "text", "next"):
                continue
            at = amiga_por_item_offset(f.offset)
            chunk = self.raw[at:at + f.size]
            if f.kind in (Kind.U16LE, Kind.UINT_LE):
                chunk = chunk[::-1]
            out[f.offset:f.offset + f.size] = chunk
        return bytes(out)


# ---------------------------------------------------------------------------
# The Amiga Pool of Radiance effect file: 10 bytes where DOS spends 9
# ---------------------------------------------------------------------------
#: One `.spc` node.  `#55` located the extra byte at offset 1, on 62 records;
#: the party shipped on Amiga disk 1 agrees on 6 more, and its payload bytes
#: 2-5 read `00 00 FF 00` -- `goldbox/dos.py`'s `INNATE_PAYLOAD` exactly, which is
#: DOS's bytes 1-4.  So the pad is at 1 and everything after it is DOS's four
#: payload bytes and four pointer bytes in order.
AMIGA_POR_EFFECT_SIZE = 10
AMIGA_POR_EFFECT_PAD = 1


def amiga_por_effect_to_dos(node: bytes) -> bytes:
    """One 10-byte Amiga `.spc` node as DOS's nine bytes.

    The duration is a `u16` big-endian at 2 where DOS keeps it little-endian
    at 1, and the four-byte next pointer is written NULL: it is a live heap
    address, and the DOS engine rebuilds the chain from the file's length --
    measured three ways under DOSBox-X, `goldbox/dos.py`'s `EFFECT_NEXT_NULL`.
    """
    if len(node) != AMIGA_POR_EFFECT_SIZE:
        raise AmigaRecordError(
            f"an Amiga effect node is {AMIGA_POR_EFFECT_SIZE} bytes, "
            f"got {len(node)}")
    return bytes((node[0], node[3], node[2], node[4], node[5])) + bytes(4)


# ---------------------------------------------------------------------------
# Amiga Pool of Radiance -> the neutral record (#27)
# ---------------------------------------------------------------------------
#
# The reader's last mile, and it is a transposition rather than a second
# codec.  `to_dos_record` re-cuts the 288 bytes into the 285 `goldbox/dos.py`
# already knows how to read, and `goldbox.dos.to_neutral` does the rest -- so
# every grade, every drop and every provenance line the DOS side earned on 24
# specimens carries over, and there is no second neutral bridge to drift.
#
# What the re-cut has to do, and nothing else:
#
#   * the name -- 16 NUL-padded bytes become DOS's count byte and fifteen;
#   * the `u16` and `u32` fields -- big-endian becomes little-endian;
#   * experience -- one `u32` on the Amiga, spanning DOS's 24-bit field *and*
#     the byte `goldbox/dos_layout.py` calls `gap_0af`.  PROBABLE: the DOS field
#     is a `u32le` and the gap is its fourth byte.  Written that way, which
#     is lossless either way round because the fourth byte is zero below
#     16 777 216 experience and no Gold Box character reaches it;
#   * the two live pointers -- the effect chain and each item's `next` -- are
#     written NULL rather than carried.  They are Amiga heap addresses.
#
# Two regions are **not** transposed and are reported instead of guessed:
#
#   * DOS `0x083`-`0x087`, where the second insertion has not been located.
#     Those five bytes are written zero, which is what the Amiga's own six
#     read in 11 of the 14 that could show anything.  DOS's own specimens
#     hold `00 00 01 00 00` in 24 of 24, and copying that constant in would
#     be putting a DOS value into a record built from an Amiga one --
#     inheriting rather than measuring.  `goldbox/dos.py` drops the field anyway;
#   * the Amiga's trailing byte at `0x11F`, which DOS does not have.
DOS_RECORD_SIZE = dos_layout.RECORD_SIZE


def _amiga_por_name(raw: bytes) -> tuple[int, bytes]:
    """The 16 NUL-padded bytes as DOS's count byte and fifteen."""
    text = raw[:AMIGA_POR_NAME_SIZE]
    line = text.split(b"\0")[0]
    size = dos_layout.FIELDS_BY_NAME["name_text"].size
    return min(len(line), size), text[:size].ljust(size, b"\0")


def to_dos_record(char: AmigaPorCharacter) -> bytes:
    """The 288-byte Amiga record re-cut as the 285-byte DOS one.

    Not a conversion between games -- the same record in the other port's
    shape, so that `goldbox/dos.py` can read it.  Every byte written came from a
    named Amiga field or is a documented zero; see the note above this
    function for the four rules and the two regions left blank.
    """
    out = bytearray(DOS_RECORD_SIZE)
    count, text = _amiga_por_name(char.raw)
    out[0] = count
    out[1:1 + len(text)] = text

    exp = dos_layout.FIELDS_BY_NAME["experience"]
    at = amiga_por_offset(exp.offset)
    out[exp.offset:exp.offset + 4] = int.from_bytes(
        char.raw[at:at + 4], "big").to_bytes(4, "little")

    skip = {"name_length", "name_text", "experience", "gap_0af",
            "field_83_87", "effect_chain"}
    for f in dos_layout.LAYOUT:
        if f.name in skip:
            continue
        at = amiga_por_offset(f.offset)
        chunk = char.raw[at:at + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            chunk = chunk[::-1]
        out[f.offset:f.offset + f.size] = chunk
    return bytes(out)


def to_neutral(char: AmigaPorCharacter) -> NeutralCharacter:
    """One Amiga Pool of Radiance character in the neutral record.

    The Amiga third of `goldbox/neutral.py`'s reader set, beside
    `goldbox.c64_codec.read` and `goldbox.dos.to_neutral`.  It reports what it could
    not carry rather than filling it in: an item file the record's own count
    disagrees with, a name that fills all sixteen bytes, and the unplaced
    window.
    """
    # Deferred: `goldbox.dos` is the heavier module and this is its only caller.
    from . import dos as _dos

    record = to_dos_record(char)
    items = [_dos.DosItem(it.to_dos_bytes()) for it in char.items]
    effects = [amiga_por_effect_to_dos(e) for e in char.effects]
    out = _dos.to_neutral(
        _dos.DosCharacter(record, items, effects, source=char.source))
    out.port = "Amiga"
    out.source = char.source
    out.warnings.append(
        "Read from a 288-byte Amiga Pool of Radiance record re-cut to the "
        "285-byte DOS one by goldbox.amiga.to_dos_record; the provenance lines "
        "name the DOS field table, which is the table both ports share")

    line, _ = _amiga_por_name(char.raw)
    if line >= dos_layout.FIELDS_BY_NAME["name_text"].size:
        out.warnings.append(
            f"The Amiga name fills all {AMIGA_POR_NAME_SIZE} bytes with no "
            f"terminator; DOS holds fifteen, so it was truncated")
    stored = char.get("item_count")
    if stored != len(char.items):
        out.warnings.append(
            f"The record counts {stored} items and {len(char.items)} were "
            f"read from the .itm file; the shorter of the two was used")
    out.drop("Amiga 0x083-0x087: the second insertion is not located, so "
             "those bytes were written zero rather than guessed")
    out.drop("Amiga 0x11F: the trailing pad, which the DOS record has no "
             "room for")
    return out


# ---------------------------------------------------------------------------
# The neutral record -> Amiga Pool of Radiance (#105)
# ---------------------------------------------------------------------------
#
# The writing half of the reader above, and the same transposition run
# backwards: `goldbox.dos.write` builds the 285-byte DOS record, its `.ITM` and
# its `.SPC` out of the neutral character, and everything here re-cuts those
# three into the Amiga's 288, 65 and 10.  There is no second field table and
# no second set of conversion rules -- a field DOS drops is dropped here for
# DOS's reason, and a field DOS derives is derived here by DOS's rule.
#
# The four rules `to_dos_record` names are simply reversed:
#
#   * the name -- DOS's count byte and fifteen become 16 NUL-padded bytes.
#     Composed rather than copied: the count says how much of the fifteen is
#     the name, and the rest is NUL.  Measured: all twenty genuine specimens
#     are NUL to the end of the sixteen, with nothing past the terminator;
#   * `u16` and `u32` fields -- little-endian becomes big-endian;
#   * experience -- DOS's 24-bit field and `gap_0af` become one Amiga `u32be`
#     at `0x0AE`;
#   * the two live pointers -- the effect chain at `0x080` and each item's
#     `next` at `0x02A` -- are written NULL.  The receiving engine allocates a
#     node per `.spc` record and per `.itm` record on load and relinks them
#     itself, which is what the reader measured in the other direction.
#
# Three bytes have no DOS source and are written rather than carried:
#
#   * `0x07F`, the first insertion: zero in 20 of 20 specimens;
#   * `0x089`ish, the second: see AMIGA_POR_FIELD_83_87 below;
#   * `0x11F`, the trailing pad: junk in 5 of 20 and zero in 15, which is what
#     an uninitialised pad looks like.  Zero is the value fifteen specimens
#     hold and it is what the writer emits.

#: Amiga `0x084`-`0x089`: DOS's `field_83_87` under the `+1` shift, plus the
#: second insertion, whichever of the last three bytes it is.
#:
#: **This narrows the unplaced insertion and the measurement is new.**  DOS
#: holds `00 00 01 00 00` at `0x083`-`0x087` in 24 of 24 specimens.  On the
#: Amiga the `01` reads at `0x086` in **8 of 20** -- all six `CHRDATA<n>.sav`
#: the game itself wrote on disk 1, and two of the fourteen `.cha` exports --
#: and `0x086` is `amiga_por_offset(0x085)`, which is where DOS's `01` lands
#: if the insertion is *after* it.  A pad at `0x084`, `0x085` or `0x086` would
#: put the `01` at `0x087`, and no specimen reads 1 there.  So the insertion
#: is one of `0x087`, `0x088` and `0x089`; the other twelve specimens read six
#: zeros and say nothing either way.  All three candidates are zero in all
#: twenty, so these six bytes are right whichever of them it turns out to be.
AMIGA_POR_FIELD_83_87 = b"\x00\x00\x01\x00\x00\x00"
AMIGA_POR_FIELD_83_87_AT = 0x084
#: Where DOS's `01` lands in that window, and so the last Amiga offset the
#: shift map is now *measured* to place rather than merely to assume.
AMIGA_POR_INSERTION_AFTER = 0x086
#: What is left of the second insertion: one of these three, all zero in all
#: twenty specimens, which is why a writer does not have to know which.
#: `AMIGA_POR_UNPLACED` is deliberately **not** narrowed to match -- the
#: reader's refusal is a guard against guessing and this reading is PROBABLE,
#: resting on the DOS constant being the same field on both ports.
AMIGA_POR_INSERTION_CANDIDATES = (0x087, 0x088, 0x089)
#: The Amiga offset of the `u32be` experience total.
AMIGA_POR_EXPERIENCE = 0x0AE

#: Amiga record bytes with no DOS source: the three insertions and the live
#: heap pointer.  The round-trip test masks **this list** plus `goldbox.dos`'s own
#: `WRITE_UNSOURCED`, `WRITE_CONSTANTS` and computed fields, rather than
#: whatever happens to differ -- so a new difference fails instead of being
#: absorbed.  `(first offset, size, why)`.
POR_WRITE_UNSOURCED: tuple[tuple[int, int, str], ...] = (
    (AMIGA_POR_PAD, 1,
     "the first insertion, a pad ahead of the effect pointer; zero in 20 of "
     "20 specimens, so zero is the value and not a guess"),
    (0x080, 4,
     "the effect chain: a live Amiga heap address. The engine allocates a "
     "node per .spc record on load and writes the head itself, which is what "
     "goldbox.dos.WRITE_UNSOURCED records for the DOS field it maps onto"),
    (AMIGA_POR_FIELD_83_87_AT, len(AMIGA_POR_FIELD_83_87),
     "DOS's field_83_87 plus the second insertion, written as the six bytes "
     "all six of the game's own disk-1 records hold; twelve of the fourteen "
     "exported .cha files hold six zeros instead, so this one is written "
     "rather than carried"),
    (AMIGA_POR_TAIL_PAD, 1,
     "the trailing pad, which the 285-byte DOS record has no room for; zero "
     "in 15 of 20 and uninitialised junk in the other five"),
)

#: DOS fields the record writer places itself rather than through the shift
#: map: the name is re-cut, experience spans two DOS fields, and the unplaced
#: window has no per-byte map to shift through.
_POR_SPECIAL = frozenset(
    {"name_length", "name_text", "experience", "gap_0af", "field_83_87"})


def _por_special(f) -> bool:
    """True for a DOS field `from_dos_record` writes by hand.

    A function rather than a bare `in` so the shift-map guard in
    `tests/test_amiga.py` asks the writer what it special-cases instead of
    keeping its own copy of the list and drifting from it.
    """
    return f.name in _POR_SPECIAL


#: The AmigaDOS drawer a Pool of Radiance save slot lives in, and the file
#: names inside it: `CHRDAT<slot><n>.sav` with `.itm` and `.spc` beside it,
#: read off disk 1 and confirmed by the game's own save to slot B (#28).
POR_SAVE_DRAWER = "save"
POR_PARTY_MAX = 6


def por_filename(slot: str, index: int, suffix: str = ".sav") -> str:
    """`CHRDATA1.sav` and its siblings, for slot `A` and index 1.

    The engine loads a party from the names in the saved game's character
    table rather than from the slot letter, but it writes them in this shape
    and the shipped disk carries them in it -- so anything we write uses it
    too.
    """
    if len(slot) != 1 or not slot.isalpha():
        raise AmigaRecordError(f"a save slot is one letter; got {slot!r}")
    if not 1 <= index <= POR_PARTY_MAX:
        raise AmigaRecordError(
            f"a Pool of Radiance party is 1 to {POR_PARTY_MAX}; got {index}")
    return f"CHRDAT{slot.upper()}{index}{suffix}"


@dataclass
class PorWriteReport(neutral.Report):
    """Where every byte of an Amiga Pool of Radiance write came from.

    Offsets `0` to `AMIGA_POR_RECORD_SIZE - 1` are the record;
    `AMIGA_POR_RECORD_SIZE` and up are the `.itm` payload and then the `.spc`.
    **Every** byte has to be explained, not only the non-zero ones -- which is
    where this differs from `Report` above and agrees with
    `goldbox.dos.WriteReport`, because unlike the Pools of Darkness `.pc` this
    record's zeroes are fields rather than untouched heap.
    """

    total: int = AMIGA_POR_RECORD_SIZE

    @property
    def unaccounted(self) -> list[int]:  # type: ignore[override]
        """Offsets this conversion cannot explain. Should be empty."""
        return [i for i in range(self.total) if i not in self.sources]

    def summary_notes(self) -> list[str]:
        if self.unaccounted:
            return [f"  UNACCOUNTED: {len(self.unaccounted)} bytes"]
        return []


def _por_name_bytes(record: bytes) -> bytes:
    """DOS's count byte and fifteen as the Amiga's sixteen NUL-padded."""
    size = dos_layout.FIELDS_BY_NAME["name_text"].size
    count = min(record[0], size)
    return record[1:1 + count].ljust(AMIGA_POR_NAME_SIZE, b"\0")


def from_dos_record(record: bytes) -> bytes:
    """The 285-byte DOS record re-cut as the 288-byte Amiga one.

    The exact inverse of :func:`to_dos_record` for every byte either port
    sources, and the note above this function says what happens to the three
    the Amiga has and DOS does not.
    """
    if len(record) != DOS_RECORD_SIZE:
        raise AmigaRecordError(
            f"a DOS Pool of Radiance record is {DOS_RECORD_SIZE} bytes, "
            f"got {len(record)}")
    out = bytearray(AMIGA_POR_RECORD_SIZE)
    out[:AMIGA_POR_NAME_SIZE] = _por_name_bytes(record)

    exp = dos_layout.FIELDS_BY_NAME["experience"]
    assert amiga_por_offset(exp.offset) == AMIGA_POR_EXPERIENCE
    out[AMIGA_POR_EXPERIENCE:AMIGA_POR_EXPERIENCE + 4] = int.from_bytes(
        record[exp.offset:exp.offset + 4], "little").to_bytes(4, "big")

    out[AMIGA_POR_FIELD_83_87_AT:
        AMIGA_POR_FIELD_83_87_AT + len(AMIGA_POR_FIELD_83_87)] = \
        AMIGA_POR_FIELD_83_87

    for f in dos_layout.LAYOUT:
        if _por_special(f):
            continue
        at = amiga_por_offset(f.offset)
        chunk = record[f.offset:f.offset + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            chunk = chunk[::-1]
        out[at:at + f.size] = chunk
    # The effect chain is a live Amiga heap address; the engine rebuilds it.
    out[0x080:0x084] = bytes(4)
    return bytes(out)


def amiga_por_item_from_dos(item: bytes) -> bytes:
    """One DOS 63-byte item node as the Amiga's 65.

    The display text is left NUL and the `next` pointer NULL, for the two
    reasons `goldbox/dos.py` gives on its own side: the line is a cache the game
    rewrites whenever it draws the ITEMS screen -- stale by construction on
    both ports, `docs/124-amiga-port.md` §1.9 -- and the chain is heap the
    loader relinks from the file's own length.
    """
    if len(item) != dos_layout.ITEM_SIZE:
        raise AmigaRecordError(
            f"a DOS Pool of Radiance item is {dos_layout.ITEM_SIZE} bytes, "
            f"got {len(item)}")
    out = bytearray(AMIGA_POR_ITEM_SIZE)
    for f in dos_layout.ITEM_LAYOUT:
        if f.name in ("text_length", "text", "next"):
            continue
        at = amiga_por_item_offset(f.offset)
        chunk = item[f.offset:f.offset + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            chunk = chunk[::-1]
        out[at:at + f.size] = chunk
    return bytes(out)


def amiga_por_effect_from_dos(node: bytes) -> bytes:
    """One DOS 9-byte `.SPC` record as the Amiga's 10.

    The inverse of :func:`amiga_por_effect_to_dos`: a pad at offset 1, the
    duration byte-swapped into `0x02`, and the four-byte next pointer NULL.
    """
    if len(node) != dos_layout.EFFECT_SIZE:
        raise AmigaRecordError(
            f"a DOS effect record is {dos_layout.EFFECT_SIZE} bytes, "
            f"got {len(node)}")
    return bytes((node[0], 0, node[2], node[1], node[3], node[4])) + bytes(4)


def write_por(char: NeutralCharacter) -> tuple[bytes, bytes, bytes,
                                               PorWriteReport]:
    """Build an Amiga Pool of Radiance record and its `.itm` and `.spc`.

    Returns `(record, itm, spc, report)`, the same shape `goldbox.dos.write`
    returns -- and it is `goldbox.dos.write` that does the conversion, because
    the Amiga record *is* the DOS record in another shape.  So every drop,
    every warning and every provenance line this report carries was earned on
    the DOS side against 24 DOS specimens, and the only lines added here are
    the three bytes the Amiga has and DOS does not.

    **A character carrying nothing gets no `.itm` file**, and an empty file is
    not the same thing as no file: `goldbox.dos.ITM_OMITTED_WHEN_EMPTY` records
    what handing the DOS engine a zero-length one did (#62).  The caller sees
    `b""` and must not write a file for it.
    """
    from . import dos as _dos

    record, itm, spc, dosrep = _dos.write(char)
    out = from_dos_record(record)

    items = [amiga_por_item_from_dos(
        itm[n * dos_layout.ITEM_SIZE:(n + 1) * dos_layout.ITEM_SIZE])
        for n in range(len(itm) // dos_layout.ITEM_SIZE)]
    effects = [amiga_por_effect_from_dos(
        spc[n * dos_layout.EFFECT_SIZE:(n + 1) * dos_layout.EFFECT_SIZE])
        for n in range(len(spc) // dos_layout.EFFECT_SIZE)]
    amiga_itm = b"".join(items)
    amiga_spc = b"".join(effects)

    rep = PorWriteReport()
    rep.dropped = list(dosrep.dropped)
    rep.warnings = list(dosrep.warnings)
    rep.warnings.append(
        "Written as a 288-byte Amiga Pool of Radiance record by re-cutting "
        "the 285-byte DOS one built by goldbox.dos.write; the provenance lines "
        "name the DOS field each byte was transposed from, which is the "
        "field table both ports share")
    rep.total = AMIGA_POR_RECORD_SIZE + len(amiga_itm) + len(amiga_spc)

    def carried(name: str) -> str:
        f = dos_layout.FIELDS_BY_NAME[name]
        return dosrep.sources.get(f.offset, f"{name}: no DOS provenance")

    rep.note(0, AMIGA_POR_NAME_SIZE,
             f"name: {AMIGA_POR_NAME_SIZE} NUL-padded bytes composed from "
             f"DOS's count byte and fifteen -- {carried('name_length')}")
    rep.note(AMIGA_POR_EXPERIENCE, 4,
             f"experience: one u32 big-endian spanning DOS's 24-bit field and "
             f"gap_0af -- {carried('experience')}")
    rep.note(AMIGA_POR_PAD, 1,
             "0x07F: the first insertion, a pad ahead of the effect pointer. "
             "Zero in 20 of 20 Amiga specimens")
    rep.note(AMIGA_POR_FIELD_83_87_AT, len(AMIGA_POR_FIELD_83_87),
             "0x084-0x089: DOS's field_83_87 constant plus the second "
             "insertion. 00 00 01 00 00 00 in all six records Amiga Pool of "
             "Radiance itself wrote on disk 1; the insertion is one of the "
             "last three bytes and all three are zero in all twenty")
    rep.note(AMIGA_POR_TAIL_PAD, 1,
             "0x11F: the trailing pad DOS has no room for. Zero in 15 of 20 "
             "specimens and uninitialised junk in the other five")

    for f in dos_layout.LAYOUT:
        if _por_special(f):
            continue
        rep.note(amiga_por_offset(f.offset), f.size, carried(f.name))

    for n in range(len(items)):
        base = AMIGA_POR_RECORD_SIZE + n * AMIGA_POR_ITEM_SIZE
        dos_base = _dos.RECORD_SIZE + n * dos_layout.ITEM_SIZE
        rep.note(base, AMIGA_POR_ITEM_TEXT,
                 f"item {n}: the rendered-line cache, left NUL -- the game "
                 f"rewrites it whenever it draws the list")
        rep.note(base + 0x02A, 4,
                 f"item {n}: next pointer left NULL -- the loader rebuilds "
                 f"the chain")
        for f in dos_layout.ITEM_LAYOUT:
            if f.name in ("text_length", "text", "next"):
                continue
            rep.note(base + amiga_por_item_offset(f.offset), f.size,
                     dosrep.sources.get(dos_base + f.offset,
                                        f"item {n}: {f.name}"))
        for pad in list(AMIGA_POR_ITEM_PAD_WINDOW) + [AMIGA_POR_ITEM_PAD]:
            if base + pad not in rep.sources:
                rep.sources[base + pad] = (
                    f"item {n}: pad at {pad:#05x}, zero in all 17 nodes read")

    base = AMIGA_POR_RECORD_SIZE + len(amiga_itm)
    dos_base = _dos.RECORD_SIZE + len(itm)
    for n in range(len(effects)):
        at = base + n * AMIGA_POR_EFFECT_SIZE
        dos_at = dos_base + n * dos_layout.EFFECT_SIZE
        rep.note(at, 1, dosrep.sources.get(dos_at, f".spc record {n}: id"))
        rep.note(at + AMIGA_POR_EFFECT_PAD, 1,
                 f".spc record {n}: the extra byte, a pad. Zero in every "
                 f"Pool of Radiance and Curse record read (68)")
        rep.note(at + 2, 4,
                 dosrep.sources.get(dos_at + 1, f".spc record {n}: payload"))
        rep.note(at + 6, 4,
                 dosrep.sources.get(dos_at + 5,
                                    f".spc record {n}: next pointer NULL"))

    return out, amiga_itm, amiga_spc, rep


# ---------------------------------------------------------------------------
# A whole Amiga Pool of Radiance save slot, and the list the picker reads (#109)
# ---------------------------------------------------------------------------
#
# `save/save` is **the slot list**, not a note about which slot is current.
# Ten bytes: `"A         "` on the shipped disk and `"AB        "` after the
# game itself saved to B (#36).  A disk carrying a complete slot B that does
# not name B here is offered only `A` at the picker -- measured, one run wasted
# on it -- so a writer that puts the files down and leaves this alone has
# written a slot the player cannot load and reported success.
#
# Hence the rule this module enforces: **a slot that cannot be listed is not
# written.**  The feasibility check runs before anything touches the disk, and
# the list is read back afterwards, because a silent failure here is invisible
# until somebody boots the game.
#
# The saved game names its own party.  Six 41-byte entries at 12813 hold
# `CHRDATA1`...`CHRDATA6` as eight plain bytes with no count byte, and the
# engine loads from *those* names rather than from the slot letter -- which is
# why saving to slot B rewrote all six to `CHRDATB<n>` (#28, §1.9b).  So a
# saved game moved to another slot has to be pointed at the files it will
# actually find, or the party that loads is the one it came from.
POR_SLOT_LIST = f"/{POR_SAVE_DRAWER}/save"
POR_SLOT_LIST_SIZE = 10
#: Ten legal slots, which is exactly what the ten-byte list holds.
POR_SLOT_LETTERS = "ABCDEFGHIJ"
POR_SAVEGAME_SIZE = 13141
POR_CHARACTER_TABLE = 12813
POR_CHARACTER_TABLE_STRIDE = 41
POR_CHARACTER_TABLE_NAME = 8


def _por_slot_letter(slot: str) -> str:
    """One of the ten letters the list can hold, upper-cased, or a refusal.

    `len` first: `"AB" in "ABCDEFGHIJ"` is true, and a membership test on its
    own would accept a two-letter slot and write files nobody can load.
    """
    letter = slot.upper()
    if len(letter) != 1 or letter not in POR_SLOT_LETTERS:
        raise AmigaRecordError(
            f"a Pool of Radiance save slot is one of {POR_SLOT_LETTERS}; "
            f"got {slot!r}")
    return letter


def por_savegame_filename(slot: str) -> str:
    """`savgamA.dat`, the case the shipped disk uses."""
    return f"savgam{_por_slot_letter(slot)}.dat"


def _remove_if_there(disk, path: str) -> bool:
    """Delete `path` if the disk has one, and say whether it did.

    Narrow on purpose, and that is the whole reason it exists: the only thing
    it swallows is the file not being there, which is the ordinary case when a
    slot is written over a shorter party.  A blind `except Exception` around
    `remove_file` would also swallow a looping hash chain and a drawer where a
    file was expected, and leave the disk half rewritten with nothing said.
    """
    try:
        entry = disk.lookup(path)
    except AmigaDiskError:
        return False
    if entry.is_dir:
        raise AmigaRecordError(
            f"{path!r} is a drawer on this disk, not a save file; refusing to "
            f"remove it")
    disk.remove_file(path)
    return True


@contextlib.contextmanager
def _all_or_nothing(disk):
    """Put the disk back exactly as it was if anything inside raises.

    `AmigaDisk.write_file` allocates the replacement before it frees the
    original (§1.10), so a write that runs the disk out of blocks stops part
    way through and leaves a filesystem that is neither what it was nor what
    it meant to be.  A slot is several files, so the window is several writes
    wide: three characters of six on the disk is exactly the state
    :func:`write_por_slot` exists to refuse.

    The snapshot is the whole image and the undo is `AmigaDisk.restore`, which
    is cheap enough at 880K not to be worth being clever about.
    """
    snapshot = disk.to_bytes()
    try:
        yield
    except BaseException:
        disk.restore(snapshot)
        raise


def read_slot_list(disk) -> list[str]:
    """The slots the picker will offer, in the order the file names them.

    A disk with no `save/save` returns an empty list: the file is what the
    picker reads, so a disk without one offers nothing whatever else is in
    the drawer.
    """
    try:
        raw = disk.read_file(POR_SLOT_LIST)
    except AmigaDiskError:
        return []
    out: list[str] = []
    for byte in raw[:POR_SLOT_LIST_SIZE]:
        letter = chr(byte).upper()
        if letter in POR_SLOT_LETTERS and letter not in out:
            out.append(letter)
    return out


def slot_list_bytes(slots: Sequence[str]) -> bytes:
    """The ten bytes for a set of slots, space-padded, in the order given.

    **Nothing is sorted.**  Whether the game sorts the list or appends to it
    is UNKNOWN: the two specimens are `"A         "` and `"AB        "`, and
    A before B is both the sorted order and the order they were created in,
    so they cannot tell the two apart.  Writing the list back in the order it
    was found leaves slots we did not write exactly where they were, which is
    the only choice that cannot be wrong about a slot somebody else made.
    Saving to a later letter and then an earlier one settles it in one run --
    `ABD` is sorted, `ADB` is creation order.
    """
    wanted: list[str] = []
    for slot in slots:
        letter = _por_slot_letter(slot)
        if letter not in wanted:
            wanted.append(letter)
    if len(wanted) > POR_SLOT_LIST_SIZE:
        raise AmigaRecordError(
            f"{len(wanted)} slots will not fit in {POR_SLOT_LIST_SIZE} bytes")
    return "".join(wanted).ljust(POR_SLOT_LIST_SIZE, " ").encode("ascii")


def retarget_savegame(save: bytes, slot: str) -> bytes:
    """Point a saved game's character table at another slot's files.

    Six entries of eight plain bytes at 12813, stride 41: `CHRDATA1` becomes
    `CHRDATB1` and so on.  The engine loads the party named here rather than
    the party named by the slot letter, so a saved game copied to another slot
    without this loads the party it came from -- measured the other way round,
    by the game's own save to slot B rewriting all six (#28 §1.9b).
    """
    letter = _por_slot_letter(slot)
    if len(save) != POR_SAVEGAME_SIZE:
        raise AmigaRecordError(
            f"an Amiga Pool of Radiance saved game is {POR_SAVEGAME_SIZE} "
            f"bytes, got {len(save)}")
    out = bytearray(save)
    for n in range(POR_PARTY_MAX):
        at = POR_CHARACTER_TABLE + n * POR_CHARACTER_TABLE_STRIDE
        name = out[at:at + POR_CHARACTER_TABLE_NAME]
        if not name.startswith(b"CHRDAT"):
            raise AmigaRecordError(
                f"entry {n} of the character table at {at} reads {name!r}, "
                f"not a CHRDAT<slot><n> name; this is not the saved game "
                f"this function knows how to point at another slot")
        out[at + 6] = ord(letter)
    return bytes(out)


def write_por_slot(disk, slot: str, characters: Sequence[NeutralCharacter],
                   savegame: bytes | None = None) -> list[str]:
    """Write a whole save slot onto an Amiga disk, slot list and all.

    Returns the paths written, in the order they were written.  `disk` is an
    open `goldbox.amiga_adf.AmigaDisk`, which is mutated in place -- the caller
    decides whether to `save()` it, so a run that raises leaves the caller's
    file untouched.

    **It refuses a slot it cannot list.**  The check runs before anything is
    written, and the list is read back off the disk afterwards; a slot the
    picker will not offer is a slot the player cannot load, so writing one and
    reporting success is worse than refusing (#109).

    **And it is all or nothing.**  Every write happens inside
    :func:`_all_or_nothing`, so a disk that runs out of blocks half way
    through a six-character party comes back byte for byte as it was.

    `savegame` is pointed at this slot's own character files if it is given.
    Without one the character files land in the drawer and the slot still
    cannot be loaded, so it is required unless the slot already has a saved
    game of its own.
    """
    letter = _por_slot_letter(slot)
    if not 1 <= len(characters) <= POR_PARTY_MAX:
        raise AmigaRecordError(
            f"a Pool of Radiance party is 1 to {POR_PARTY_MAX} characters; "
            f"got {len(characters)}")

    with _all_or_nothing(disk):
        # Feasibility first: nothing is written for a slot the picker will not
        # be told about.
        wanted = slot_list_bytes(read_slot_list(disk) + [letter])

        savegame_path = f"/{POR_SAVE_DRAWER}/{por_savegame_filename(letter)}"
        if savegame is None:
            try:
                disk.lookup(savegame_path)
            except AmigaDiskError:
                raise AmigaRecordError(
                    f"slot {letter} has no {savegame_path} on this disk and "
                    f"none was given; the character files alone are not a "
                    f"slot the game can load") from None

        written: list[str] = []
        for index, char in enumerate(characters, start=1):
            record, itm, spc, rep = write_por(char)
            if rep.unaccounted:
                raise AmigaRecordError(
                    f"{len(rep.unaccounted)} bytes of character {index} have "
                    f"no provenance; refusing to write an unexplained record")
            stem = f"/{POR_SAVE_DRAWER}/{por_filename(letter, index, '')}"
            disk.write_file(stem + ".sav", record)
            written.append(stem + ".sav")
            for suffix, payload in ((".itm", itm), (".spc", spc)):
                if payload:
                    disk.write_file(stem + suffix, payload)
                    written.append(stem + suffix)
                else:
                    # A character carrying nothing gets no file, and a stale
                    # one from whoever held this slot before would hand him
                    # somebody else's gear -- the engine reads the record's
                    # own count, but the file is what the count indexes into.
                    _remove_if_there(disk, stem + suffix)

        # Any file the previous occupant of this slot left for a character
        # this party does not have. A six-character save followed by a
        # four-character one would otherwise leave CHRDAT?5 and CHRDAT?6 on
        # the disk, loadable and belonging to somebody else.
        for index in range(len(characters) + 1, POR_PARTY_MAX + 1):
            stem = f"/{POR_SAVE_DRAWER}/{por_filename(letter, index, '')}"
            for suffix in (".sav", ".itm", ".spc"):
                _remove_if_there(disk, stem + suffix)

        if savegame is not None:
            disk.write_file(savegame_path,
                            retarget_savegame(savegame, letter))
            written.append(savegame_path)

        disk.write_file(POR_SLOT_LIST, wanted)
        written.append(POR_SLOT_LIST)
        if letter not in read_slot_list(disk):
            raise AmigaRecordError(
                f"slot {letter} is still not in {POR_SLOT_LIST} after writing "
                f"it; the picker would not offer it")
        return written
