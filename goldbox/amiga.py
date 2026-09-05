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
from .layout import Confidence, Kind
from .neutral import NeutralCharacter

#: The C64 record's `60 - value` bias turns up here too, on armour class.
COMBAT_BIAS = 60

#: The shortest genuine `.pc` on disk 3 -- but not the shortest PoD's loader
#: will read. The loader reads 404 bytes of character record, then 20 bytes
#: per item and 10 per effect, and stops (`docs/124-amiga-port.md` §1.16, from
#: reading the loader in #148). A record with zero items and zero effects is
#: 404 bytes, not 484: every genuine `.pc` on disk 3 happens to carry at least
#: four items, which is why 484 is the smallest one there. PoD checks no
#: length -- a 582-byte C64 export loads -- but 484 is what its own files
#: look like, so it is what the writer emits, with 80 bytes of item/effect
#: region that PoD never reads because both counts are zero.
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
    ("granted_effects", "what a ring or a girdle granted, whole -- and the "
                        "id inside it is in the earlier game's numbering, so "
                        "it cannot be crossed either. See `innate_effects`"),
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
    ("status", "no located home in the `.pc`. The sheet has a STATUS line and "
               "every payload a probe has put on screen drew OKAY, so the "
               "byte behind it has never been separated from fill -- see "
               "`CONFIDENCE['status']`. The character arrives well"),
    ("active", "see `status`: whether PoD marks a character out of the party "
               "the way DOS and the C64 do is not located either"),
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


def to_neutral(char) -> NeutralCharacter:
    """One Amiga character in the neutral record, whichever title wrote it.

    The Amiga third of `goldbox/neutral.py`'s reader set, beside
    `goldbox.c64_codec.read` and `goldbox.dos.to_neutral`.  It reports what it could
    not carry rather than filling it in: an item file the record's own count
    disagrees with, a name that fills all sixteen bytes, and the unplaced
    window.

    An `AmigaCharacter` -- Curse or Silver Blades -- goes to
    :func:`to_neutral_later`, which reads its own title's field table.  The
    rest of this function is Pool of Radiance's, and re-cuts the record into
    the DOS one so that `goldbox.dos.to_neutral` does the reading.
    """
    if isinstance(char, AmigaCharacter):
        return to_neutral_later(char)
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
    # There is no loop here reporting the effects the neutral record cannot
    # hold, and there should not be one.  `_dos.to_neutral`, called above,
    # now **carries** every non-innate node at duration zero in
    # `granted_effects` -- the same nodes, since `amiga_por_effect_to_dos`
    # recut them on the way in -- so an Amiga-to-Amiga or Amiga-to-DOS
    # conversion writes the ring's record back rather than losing it, and a
    # report line saying it was lost would be untrue.  Only a writer that
    # cannot take the field says so, which is `goldbox/c64_codec.py` and
    # `write_pod` below, each in its own words.  A loop here reported every
    # loss twice while there was one (#238, An Amiga conversion's report
    # shows an uncarried effect twice, once from goldbox.amiga.to_neutral
    # and once from goldbox.dos.to_neutral).
    return out


def describe_uncarried_effect(node: bytes) -> str:
    """One drop line for a `.spc` node a destination cannot hold.

    Names what the character had, from the node's first byte, and leaves the
    caller to add why its own destination could not take it.  Only a writer
    that cannot take `granted_effects` says any of this: the neutral record
    holds the node, so DOS and Amiga write it back, and it is the C64 -- ten
    trait slots of one number each -- that has to explain itself.

    A node with rounds left never reaches here at all.  It was going to
    expire anyway, and Donald ruled on 2026-08-27 that those need no report;
    `goldbox.dos.to_neutral` is where that line is drawn, on the duration.

    **What it says, and what it deliberately does not.** Donald's wording,
    2026-09-04: what the character had, and what it means for them. No
    effect id, no module name, no issue number -- `AGENTS.md` says anything
    a user reads in the interface carries no address or offset, and the
    lines already in this list had been carrying both. He was shown the
    longer form that named `goldbox.dos.INNATE_EFFECTS` and `#232 (An
    item-granted effect is dropped on the way through the neutral record,
    with no report)` and took this one instead; finding the code from the
    effect's name is one grep, and the player is not the one who should be
    paying for it.
    """
    from . import traits

    # `[:1].upper()`, never `str.capitalize()`: `.claude/rules/gui-text.md`
    # bans it because it lower-cases the rest, and effect 61's own name is
    # "wearing a Ring of Fire Resistance" -- `capitalize()` renders that as
    # "Wearing a ring of fire resistance" and takes the item's name with it.
    said = traits.describe(node[0])
    return (f"{said[:1].upper()}{said[1:]}: not carried, so the character "
            f"arrives without it")


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

    The display text is left NUL and the `next` pointer NULL.

    **The chain is CONFIRMED**: the engine relinked one we wrote all-NULL, 17
    nodes of 17, and the last came back NULL (`docs/124-amiga-port.md`
    §1.12a).

    **The display text is PROBABLE and the grade is deliberate.** The line is
    a render, not a source -- everything in it comes from `name1`, `name2`,
    `name3`, `readied`, `quantity` and `value`, which this node carries -- and
    five of the five genuine nodes with a tail show a second, longer render
    underneath the first, so the composer runs more than once and on more than
    one screen. But the engine did **not** compose it on load and did not
    compose it on save: 17 nodes written NUL survived a load, a camp and a
    save still NUL. So "it will be filled in when ITEMS draws" is an argument
    from the bytes, and what would refute it is one screenshot of that screen
    on a party this wrote. Until then this is the one part of the writer that
    might have to change.
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
        # The Amiga keeps the duration big-endian where DOS keeps it little,
        # so the two bytes swap and the value and flag follow unchanged.
        rep.note(at + 2, 2,
                 dosrep.sources.get(dos_at + 1,
                                    f".spc record {n}: duration, byte-swapped"))
        rep.note(at + 4, 2,
                 dosrep.sources.get(dos_at + 3, f".spc record {n}: payload"))
        rep.note(at + 6, 4,
                 dosrep.sources.get(dos_at + 5,
                                    f".spc record {n}: next pointer NULL"))

    return out, amiga_itm, amiga_spc, rep


# ---------------------------------------------------------------------------
# A whole Amiga Pool of Radiance save slot, and the list the picker reads (#109)
# ---------------------------------------------------------------------------
#
# `save/save` is **the slot list**, not a note about which slot is current.
# Ten bytes, one per slot, indexed by letter: `A` is byte 0 and `J` is byte 9,
# and a slot that does not exist is a space.  `"A         "` on the shipped
# disk, `"AB        "` after the game saved to B (#36), and `"AB D      "`
# after it was made to save to D and then to B (#109) -- the gap at byte 2 is
# where `C` would go, and it is what says this is an array and not a list.
# A disk carrying a complete slot B that does not name B here is offered only
# `A` at the picker -- measured, one run wasted on it -- so a writer that puts
# the files down and leaves this alone has written a slot the player cannot
# load and reported success.
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
    """The slots the picker will offer.

    A disk with no `save/save` returns an empty list: the file is what the
    picker reads, so a disk without one offers nothing whatever else is in
    the drawer.

    Any letter counts wherever it sits, rather than only in its own byte.
    The game writes each letter at its own index (:func:`slot_list_bytes`), so
    on a disk the game wrote the two readings agree; a letter out of place is
    a file somebody else made badly, and reading it as present and writing it
    back in its proper place is a repair rather than a loss.
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
    """The ten bytes for a set of slots: each letter in its own place.

    **The file is a ten-slot array indexed by letter, not a list**, so the
    order the letters are given in cannot matter: `A` is byte 0 and `J` is
    byte 9, and a slot that does not exist is a space.  Measured in the
    running game on 2026-09-01 (#109) -- Amiga Pool of Radiance was made to
    save to `D` and then to `B` from one loaded party, and `save/save` came
    back `"AB D      "`, with the gap at byte 2 where `C` would go.  That is
    neither the sorted `ABD` nor the creation-order `ADB` this module used to
    guess between; both would have closed the gap.

    So a compacted list is wrong even though the picker would still draw the
    same four letters from it: the game reads this array back into memory and
    stores the next save's letter at that letter's own index, which in a
    compacted list is somebody else's entry.
    """
    out = bytearray(b" " * POR_SLOT_LIST_SIZE)
    for slot in slots:
        letter = _por_slot_letter(slot)
        out[POR_SLOT_LETTERS.index(letter)] = ord(letter)
    return bytes(out)


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


# ---------------------------------------------------------------------------
# Amiga Curse of the Azure Bonds and Secret of the Silver Blades (#55)
# ---------------------------------------------------------------------------
#
# Two more ports of the same record, and neither is a second field table:
# each reads `goldbox/dos_layout.py`'s own shape for its title through a shift
# map, big-endian, exactly as the Amiga Pool of Radiance reader above does.
# `AmigaShape` is that map as data, so a third title is a row rather than a
# module.
#
# **Silver Blades is where the evidence is strongest, because the two ports
# ship the same six characters.**  `SAVE/savgamA.sav` on Amiga disk 1 carries
# Guy de Valois, PAINE, EPONA, MALACHITE, DOMINIC and MORGAINE, and the DOS
# archives ship `CHRDATA1`-`CHRDATA6` with those same six names.  Read through
# the map below, **every one of the 85 fields in the DOS Silver Blades table
# decodes to the byte-for-byte value its DOS twin holds, in 6 of 6
# characters**, with three groups of exceptions and no others:
#
#   * `effect_chain` and `heap_104`, which are live pointers -- an Amiga heap
#     address against a DOS far pointer.  They cannot agree and must not be
#     carried;
#   * MALACHITE's four saving throws and eight thief percentages, where the
#     two ports' shipped copies of that character genuinely differ.  One
#     specimen of six; the other five agree on both groups.
#
# That is what makes the Silver Blades offsets CONFIRMED rather than
# consistent: a wrong offset anywhere would have shown up as a mismatch in a
# field whose value is not zero, and 6 x 85 comparisons produced twenty
# mismatches, all of them named above.
#
# **Curse has no such twin** -- the eleven `SAVE/*.guy` pregens on Amiga disk 1
# are ARIEL, BJORN DARKSTONE, GALAIN and so on, and the DOS archives ship
# MATHEW, MARK, TRAVIS and so on.  So its map rests on three things instead:
# fields whose value is forced (a dwarf's `size` of 1, a level-5 magic-user's
# `4 2 1` spell slots, 25 000 experience split between a character's classes),
# the arithmetic identity `money + sum(weight x quantity) = encumbrance` on
# 15 of 15 specimens, and **23 constants that hold across all 12 DOS records
# and all 15 Amiga ones and agree byte for byte at the mapped offsets** --
# including `attack_forms`' eight-byte `02 00 01 00 02 00 00 00` and
# `field_10c_10f`' four-byte `00 01 00 00`.
#
# The five rules the shift maps are made of, all three titles:
#
#   1. **The name is 16 NUL-padded bytes** where DOS spends a count byte and
#      fifteen.  Same width, so nothing after it moves.
#   2. **Every `u16` and `u32` is big-endian.**  It is a 68000.
#   3. **A `u16` or `u32` field is even-aligned**, and a pad byte goes in
#      ahead of it when the DOS offset is odd.  That is where every insertion
#      in all three titles comes from, and two of Silver Blades' three are
#      located to the byte because the field either side of them is non-zero.
#   4. **The record is padded to an even length.**  Curse's 422 + 5 = 427 is
#      odd and the record is 428; Silver Blades' 340 is even and there is no
#      trailing byte.  Pool of Radiance's 285 + 2 = 287 pads to 288.
#   5. **Silver Blades, and only Silver Blades, packs the spellbook into
#      bits** -- see `AMIGA_SSB_SPELLBOOK_BYTES`.
#
#: The name field, all three titles: 16 bytes, NUL-padded, no count byte.
AMIGA_NAME_SIZE = 16


@dataclass(frozen=True)
class AmigaShape:
    """One title's Amiga record, as a difference from its DOS record.

    Everything here is a *map onto* `goldbox/dos_layout.py`, never a copy of
    it: `offset` turns a DOS offset into an Amiga one and `AmigaCharacter`
    reads the DOS field table through it, so a correction to the DOS side
    reaches the Amiga side with no second edit.
    """

    key: str
    title: str
    dos: dos_layout.DosShape
    record_size: int
    #: `(first DOS offset, bytes inserted before it)`, ascending.
    shifts: tuple[tuple[int, int], ...]
    #: DOS offsets whose Amiga counterpart cannot be placed, because an
    #: insertion sits somewhere inside a run that reads zero on both ports.
    unplaced: tuple[range, ...] = ()
    #: Bytes the spellbook takes on the Amiga when it is a bitmask rather
    #: than DOS's one byte per spell.  `None` means it is DOS's shape.
    spellbook_bytes: int | None = None
    #: One item node.  `None` where no specimen carries an item.
    item_size: int | None = None
    item_shifts: tuple[tuple[int, int], ...] = ()
    item_unplaced: tuple[range, ...] = ()
    #: Bytes of NUL-separated display text before the item's `next` pointer.
    item_text: int = 0x02A
    #: One effect node: DOS's nine plus a pad byte at offset 1.
    effect_size: int = AMIGA_POR_EFFECT_SIZE
    #: The byte past the last field, present only to make the record even.
    trailing_pad: int | None = None

    def offset(self, dos_offset: int) -> int:
        """Where a DOS record offset lands in this title's Amiga record.

        Raises rather than guessing for an offset inside an unplaced window,
        or inside a re-encoded spellbook, so a caller that wants those bytes
        has to say so and read them raw.
        """
        if self.spellbook_bytes is not None:
            book = self.dos_field("spellbook")
            if book.offset <= dos_offset < book.offset + book.size:
                raise AmigaRecordError(
                    f"DOS offset {dos_offset:#05x} is inside the "
                    f"{self.title} spellbook, which the Amiga packs into "
                    f"{self.spellbook_bytes} bytes of bitmask; there is no "
                    f"one-to-one Amiga offset for it")
        for window in self.unplaced:
            if dos_offset in window:
                raise AmigaRecordError(
                    f"DOS offset {dos_offset:#05x} is inside "
                    f"{window.start:#05x}-{window.stop - 1:#05x}, where an "
                    f"insertion has not been located; there is no Amiga "
                    f"offset to give")
        shift = 0
        for first, amount in self.shifts:
            if dos_offset >= first:
                shift = amount
        return dos_offset + shift

    def item_offset(self, dos_offset: int) -> int:
        """Where a DOS item offset lands in this title's Amiga item node."""
        if self.item_size is None:
            raise AmigaRecordError(
                f"no Amiga {self.title} item node has been measured: no "
                f"specimen on this machine carries an item")
        for window in self.item_unplaced:
            if dos_offset in window:
                raise AmigaRecordError(
                    f"DOS item offset {dos_offset:#05x} is inside "
                    f"{window.start:#05x}-{window.stop - 1:#05x}, where the "
                    f"insertion has not been located")
        shift = 0
        for first, amount in self.item_shifts:
            if dos_offset >= first:
                shift = amount
        return dos_offset + shift

    def dos_field(self, name: str):
        """One `goldbox/dos_layout.py` field of this title's DOS record."""
        for f in dos_layout.layout_for(self.dos):
            if f.name == name:
                return f
        raise AmigaRecordError(
            f"no field called {name!r} in the DOS {self.title} record")


# ---------------------------------------------------------------------------
# The item node of the two later Amiga titles, read from the constructor
# ---------------------------------------------------------------------------
#
# Curse's node is **66 bytes** and Silver Blades' **70**, and the first 66 of
# each are the same layout.  It is not argued from specimens: each executable
# carries a constructor that allocates the node, clears it and then writes
# fifteen named arguments into it, one field at a time -- `/Curse` at file
# offset `0x1C1EA`, `/Secret` at `0x1B862`, instruction for instruction the
# same routine.  The arguments arrive in `goldbox/dos_layout.py`'s own item
# order, so the two tables can be laid beside each other:
#
#     type_index -> 0x2E   name1..3 -> 0x30 0x31 0x32   plus -> 0x33
#     plus_save  -> 0x34   readied  -> 0x35   hidden -> 0x36  cursed -> 0x37
#     weight (u16be) -> 0x38   quantity -> 0x3A   value (u16be) -> 0x3C
#     charges -> 0x3F   effect -> 0x40   power -> 0x41
#
# **Nothing is written at `0x2F`, `0x3B` or `0x3E`.**  Those three are the
# insertions, and the constructor's `setmem(node, size, 0)` is why an item the
# game builds itself reads zero in all three.  The nine nodes in
# `SAVE/savgamA.dat` read `0x7F`, 52 and 47 there instead because they came
# through the other path -- the `ITEM<n>` template loader at `/Curse`
# `0x1F2D6`, which unpacks each 63-byte template into a stack struct it never
# clears and copies all 66 bytes into the node.  Uninitialised stack, copied
# nine times.
#
# This **refutes** the reading `#55 (Decode the Amiga Curse and Silver Blades
# records)` carried until 2026-09-05, that `0x3E` was `charges` and 47 was a
# Chain Mail's charge count.  `charges` is at `0x3F` and reads zero, which is
# what a Chain Mail should hold.
#
# Silver Blades adds a **fourth pointer at `0x42`**, `u32` big-endian, which
# the unpacker clears (`/Secret` `0x28194`) and which is non-NULL only on a
# scroll: an item whose `type_index` is `0x49` chains `quantity` further
# 70-byte nodes through it, each carrying three more spell ids in the bytes
# the constructor calls `charges`, `effect` and `power`.  `/Secret` `0xDE`
# walks it, and the vault writer at `0x3D6D2` writes those nodes out after
# the item itself.  Curse has no such field and no room for one.
#
#: `(first DOS item offset, bytes inserted before it)`, ascending -- the same
#: three insertions in both later Amiga titles.
AMIGA_LATER_ITEM_SHIFTS = ((0x000, 0), (0x02F, 1), (0x03A, 2), (0x03C, 3))

#: Silver Blades only: a `u32be` at the end of the 70-byte node, NULL except
#: on a scroll, where it heads a chain of further nodes holding the rest of
#: the scroll's spell ids.
AMIGA_SSB_SCROLL_CHAIN = 0x042

#: Curse of the Azure Bonds: the 422-byte DOS record, 428 bytes on the Amiga.
#:
#: Five insertions, and only two of them are located to the byte.
#:
#: **Every insertion is located to the byte, and none of it rests on a
#: specimen.**  `/Curse` carries a routine at file offset `0x270A6` that
#: expands a packed 422-byte record -- the DOS layout, byte for byte -- into
#: the 428-byte Amiga one, field group by field group, and its 26 copy
#: boundaries all land on a `goldbox/dos_layout.py` Curse field boundary.  It
#: opens `setmem(record, 0x1AC, 0)`, which is 428, and the monster loader at
#: `0x26306` calls it after decompressing `MON<n>CHA` to `0x1A6` = 422 bytes.
#: `tools/amigaunpack.py` prints the map; `docs/166-amiga-records-from-the-code.md`
#: has the working.
#:
#:   * the pad is at Amiga **`0x0FB`**, not anywhere in `0x0F9`-`0x0FB`: the
#:     routine copies DOS `0x0F6`-`0x0F8` to `0x0F6`, DOS `0x0F9` and `0x0FA`
#:     one byte each to the same offsets, and then the fourteen money bytes
#:     from DOS `0x0FB` to Amiga `0x0FC`.  So `field_83_87` is at
#:     `0x0F6`-`0x0FA` at shift 0 and is readable;
#:   * **each of the three spell-slot arrays is six bytes on the Amiga where
#:     DOS spends five**, and that is the whole of the three-byte insertion
#:     between `hp_rolled` and `gap_13c`.  Three routines index them as
#:     `record[0x12E + 6 * class + (level - 1)]` -- `/Curse` `0x288`, `0x482`
#:     and `0x9F4`, with `class` read from byte 0 of a 16-byte spell-table
#:     entry (0 cleric, 1 druid, 2 magic-user) and `level` from byte 1.  So
#:     the cleric array is `0x12E`-`0x133`, the **druid array `0x134`-`0x139`**
#:     and the magic-user array `0x13A`-`0x13F`, and the sixth byte of each
#:     has no DOS counterpart.  `/Secret`'s Curse-import routine at `0x26F64`
#:     reads the same three bases out of a Curse record, which is a second
#:     binary agreeing;
#:   * DOS's three-byte `gap_13c` is therefore at Amiga `0x140`-`0x142`, and
#:     its first two bytes are a `u16`: the unpacker byte-swaps the word at
#:     Amiga `0x140` the way it swaps age, the money block and experience;
#:   * one at Amiga `0x151`, between `item_count` and the item pointer array.
#:     The count is at `0x150` -- forced by `428 + 66 x count + 10 x effects`
#:     matching the block length in 4 of 4 played characters -- and the
#:     pointers are at `0x152`, which is where `/Curse`'s saved-game writer
#:     starts the item chain (`docs/165-amiga-savegame.md`);
#:   * the trailing byte at `0x1AB`, which makes 427 into 428.
#:
#: **`sex` is at Amiga `0x11A` and `alignment` at `0x11C`** -- the two fields
#: reading GALAIN's sheet on screen could not place, because one sheet cannot
#: separate a byte from its neighbours.  The unpacker copies DOS `0x119`,
#: `0x11A` and `0x11B` to those three offsets, one byte at a time.
#:
#: Thirteen of these offsets were also **read off the game's own character
#: sheet** under WinUAE, on GALAIN in `SAVE/savgamA.dat` -- race at `0x074`,
#: age at `0x076`, class at `0x075`, the class levels at `0x10A`, the money
#: block at `0x0FC`, experience at `0x128`, hit points at `0x078` and
#: `0x1A9`, armour class at `0x19F` stored `60 - AC`, THAC0 base at `0x073`,
#: encumbrance at `0x18C` and movement at `0x0E4` and `0x1AA`.
#: `docs/124-amiga-port.md` §1.11 has the sheet beside the record. That is
#: the instrument reading this map's other anchors could not be: a number a
#: person read on a screen, not an arithmetic identity between two files.
CURSE_SHAPE = AmigaShape(
    key="curse-of-the-azure-bonds",
    title="Curse of the Azure Bonds",
    dos=dos_layout.CURSE_OF_THE_AZURE_BONDS,
    record_size=428,
    shifts=((0x000, 0), (0x0FB, 1), (0x132, 2), (0x137, 3), (0x13C, 4),
            (0x14D, 5)),
    item_size=66,
    item_shifts=AMIGA_LATER_ITEM_SHIFTS,
    trailing_pad=0x1AB,
)

#: Secret of the Silver Blades: the 439-byte DOS record, 340 on the Amiga.
#:
#: The spellbook is the whole of the difference in size, and the three
#: insertions are what is left.  Two are located to the byte:
#:
#:   * Amiga `0x095`, ahead of the `u32` effect chain at `0x096` -- the eight
#:     thief percentages fill `0x08D`-`0x094` on MALACHITE and the chain is
#:     non-zero on four of the six, so the pad has nowhere else to be;
#:   * Amiga `0x0C7`, ahead of the `u32` experience at `0x0C8` -- `0x0C6` is
#:     `unnamed_0ab`, distinct in all six, and `0x0C8` reads 200 000 or
#:     100 000 big-endian, which is what the DOS twin holds;
#:   * Amiga `0x0FD`, between `item_count` at `0x0FC` and the item pointer
#:     array at `0x0FE`.
#:
#: All three are now **CONFIRMED from the code rather than from the six
#: specimens**: `/Secret` expands a packed 439-byte record -- the DOS layout
#: -- into this one at file offset `0x281A2`, opening with
#: `setmem(record, 0x154, 0)`, and its 22 copy boundaries all land on a
#: `goldbox/dos_layout.py` Silver Blades field boundary.  It copies DOS
#: `0x0F3`+8 to Amiga `0x08D`, skips DOS's four-byte `effect_chain`, and
#: resumes at Amiga `0x09A`, which puts the pad at `0x095`; it copies DOS
#: `0x121`+11 to `0x0BC` and DOS `0x12C`+13 to `0x0C8`, which puts the pad at
#: `0x0C7`; and it copies DOS `0x14E`+19 to `0x0EA` and DOS `0x161`+69 to
#: `0x0FE`, which puts the pad at `0x0FD`.  The last of those was PROBABLE
#: and is now measured.  `docs/166-amiga-records-from-the-code.md`.
#:
#: **`sex` is at Amiga `0x0BA` and `alignment` at `0x0BB`**, from the two
#: single-byte copies of DOS `0x11F` and `0x120`.
#:
#: The **four spell-slot arrays are seven bytes each and are not widened**,
#: unlike Curse's: `/Secret` `0x5D4` indexes them as
#: `record[0x0CE + 7 * class + (level - 1)]`, and the unpacker copies each of
#: the four as its own seven bytes.
SILVER_BLADES_SHAPE = AmigaShape(
    key="secret-of-the-silver-blades",
    title="Secret of the Silver Blades",
    dos=dos_layout.SECRET_OF_THE_SILVER_BLADES,
    record_size=340,
    shifts=((0x000, 0), (0x0E6, -102), (0x0FB, -101), (0x12C, -100),
            (0x161, -99)),
    spellbook_bytes=15,
    item_size=70,
    item_shifts=AMIGA_LATER_ITEM_SHIFTS,
)

#: Every Amiga shape this module reads, and the size that names each.  The
#: three sizes are distinct, as the DOS four are, so a reader handed a
#: nameless file can say which title it belongs to.
AMIGA_SHAPES = (CURSE_SHAPE, SILVER_BLADES_SHAPE)
AMIGA_SHAPES_BY_SIZE = {s.record_size: s for s in AMIGA_SHAPES}

#: Silver Blades' spellbook: 15 bytes of bitmask at `0x071`, **LSB first**
#: within each byte, where DOS spends one byte per spell for ids 1..117.
#:
#: CONFIRMED from the code: `/Secret`'s record unpacker at file offset
#: `0x28260` walks the packed record's 117 one-byte flags and, for each,
#: sets or clears bit `i mod 8` of `record[0x71 + i / 8]` through a mask
#: table at `g234e` that reads `01 02 04 08 10 20 40 80` -- least
#: significant bit first, by the table's own contents.
#:
#: CONFIRMED on 6 of 6 specimens and 62 set bits as well: PAINE's `77 78 79 80`,
#: DOMINIC's 29 ids and MORGAINE's 29 come out of the mask exactly as the DOS
#: twin's byte array holds them, and MSB-first reproduces none of the three.
#: The other three characters have an empty book on both ports.
#:
#: Curse does **not** do this: its Amiga spellbook is 100 bytes of 0 and 1 at
#: `0x079`, DOS's own shape, and the ids that come out of the eleven pregens
#: are clean class-coherent sets -- KAROLYN the cleric holds 1-8, 22-28 and
#: 37-44, ARIEL the magic-user holds 10, 11, 12, 15, 18, 21, 31, 34.  So this
#: is a per-title decision rather than a property of the port.
AMIGA_SSB_SPELLBOOK_BYTES = 15
AMIGA_SSB_SPELLBOOK_AT = 0x071


# ---------------------------------------------------------------------------
# The status word, named from the routine that draws it (#28, step 3)
# ---------------------------------------------------------------------------
#
# **Both later Amiga titles number the nine states the way DOS does**, so
# `goldbox/neutral.py`'s `STATUS_NAMES` is their table as well and `status`
# crosses by name with nothing to translate.  That is not an assumption from
# the shift map: it is two string tables in two binaries, each reached by the
# routine that paints the party panel.
#
#   * `/Secret` `0x196EA`: `tst.b $144(a2)`, and where that is zero
#     `move.b $143(a2), d0; ext.w; ext.l; asl.l #2; lea g30fc, a0;
#     move.l (a0, d0.l), -(a7)` -- a nine-entry `char *` table at file offset
#     `0x4F9B8` pointing at `Okay`, `Animated`, `tempgone`, `Running`,
#     `Unconscious`, `Dying`, `Dead`, `Petrified`, `Gone`.  The same table is
#     indexed a second time at `0x2208C`, off the current character.
#   * `/Curse` `0x1A38E`: `tst.b $19b(a2)`, and where that is zero
#     `move.w $19a(a2)` into a helper at `0x352E8` that fetches block
#     `status + 0x2C` of text library `0x13`.  That library is
#     `DISKA/STRINGS.GLB`, and its blocks 44 to 52 read `Okay`, `Animated`,
#     `tempgone`, `Running`, `Unconscious`, `Dying`, `Dead`, `Stoned`,
#     `Gone` -- DOS's own ninth word where `/Secret` says `Petrified`.
#
# Amiga `0x143` is DOS `0x1A6` under `SILVER_BLADES_SHAPE` and Amiga `0x19A`
# is DOS `0x195` under `CURSE_SHAPE`, and both are the **first byte of
# `field_10c_10f`** -- the same field DOS Pool of Radiance keeps the status in
# at `0x10C` (#235).  Each title's unpacker copies those bytes one at a time
# rather than as a run, which is a third routine agreeing that they are three
# separate fields.
#
#: The DOS field whose first byte is the status the party panel draws.
AMIGA_LATER_STATUS_FIELD = "field_10c_10f"

#: The byte after the status, and **it is not DOS Pool of Radiance's `active`
#: flag on the evidence there is.**  Where it is non-zero the panel draws
#: `(Helpless)` or `(Casting)` in place of the status word, which is combat
#: state rather than "the game has taken this character out of the party".
#: UNKNOWN, and not carried.  What would settle it: knock a character down in
#: an Amiga Curse fight, save, and read the byte; and put a character in the
#: state that draws the name red and read it again.
AMIGA_LATER_STATUS_GATE = 1

# ---------------------------------------------------------------------------
# What the loader needs of a block it did not write (#28, step 4)
# ---------------------------------------------------------------------------
#
# The saved game's per-character loader -- `/Curse` `0x25056`, `/Secret`
# `0x268C0` -- reads the record and then **decides whether an item node
# follows by testing the pointer the record itself carries**:
#
#     read(fd, record, 0x1AC)              ; 0x154 in /Secret
#     tst.l   $152(a0)                     ; $fe(a0) in /Secret
#     beq     no items
#     alloc(&record[0x152], 0x42)          ; overwrites the tested value
#     read(fd, record[0x152], 0x42)
#     a3 = record[0x152]
#   loop:
#     tst.l   $2a(a3)                      ; the node's own next pointer
#     beq     done
#     alloc(&a3[0x2a], 0x42); read(...); a3 = a3->next
#
# and the effect chain the same way from `$f2(a0)` / `$96(a0)`, ten bytes a
# node, next at node offset 6.  **The stored pointer is a boolean.**  Its
# value is never dereferenced: `alloc` overwrites it with the address it
# returns before the `read` that fills the node.  `item_count` is not
# consulted by the loader at all.
#
# So a saved game we write must carry a **non-zero** head where nodes follow
# and a **zero** one where they do not, and a wrong answer is not a cosmetic
# fault: every character is read from one file descriptor in sequence, so a
# head left NULL in front of a node that is really there leaves the stream
# mid-block and every later character in the party reads rubbish.
#
# That is the opposite of the Pool of Radiance rule, where `.itm` and `.spc`
# are separate files and the chain is rebuilt from the file's length -- which
# is why `write_por` writes NULL and this must not.
#
# Corroborated on **21 of 21 records** off the shipped disks, independently of
# the code: the eleven Curse `.guy` pregens, the four characters in
# `SAVE/savgamA.dat` and the six in `SAVE/savgamA.sav` all carry a non-zero
# head exactly when a node follows, a non-zero `next` on every node but the
# last, and zero on the last.  The addresses step by 66 along an item chain
# and by 10 along an effect chain, which is what a heap of those node sizes
# looks like.
#
#: What to put in a chain field when a node follows and the record's own value
#: cannot be kept.  Any non-zero longword does; 1 is chosen because it cannot
#: be mistaken for an Amiga heap address in a dump.
AMIGA_LATER_CHAIN_PRESENT = 1
#: The item node's own next pointer, and the effect node's.
AMIGA_LATER_ITEM_NEXT = 0x02A
AMIGA_LATER_EFFECT_NEXT = 0x006


def _chain_bytes(present: bool, current: int) -> bytes:
    """Four big-endian bytes for a chain field, keeping what is there.

    A value whose truth already matches what follows is left alone, so a
    saved game read and written back is byte for byte the file it came from;
    only a field that would lie to the loader is changed.
    """
    if bool(current) == present:
        return current.to_bytes(4, "big")
    return (AMIGA_LATER_CHAIN_PRESENT if present else 0).to_bytes(4, "big")


@dataclass(frozen=True)
class AmigaItem:
    """One item node of a later Amiga Gold Box title.

    Curse's is **66 bytes** where DOS spends 63, Silver Blades' is **70**,
    and the first 66 of each are the same layout -- see
    `AMIGA_LATER_ITEM_SHIFTS` for the constructor both titles build one with.
    The insertion Amiga Pool of Radiance does not have is the pad at `0x02F`,
    ahead of `name1`: the same Chain Mail reads `37 00 30 37` at `0x02E`
    there and `37 00 00 30 37` here.

    `charges` is at **`0x03F`**, not `0x03E`.  The nine nodes in
    `SAVE/savgamA.dat` read 52 at `0x03B` and 47 at `0x03E` in 9 of 9, which
    looked like a field; the constructor writes neither, and both are
    uninitialised stack copied out of the `ITEM<n>` template loader.
    """

    raw: bytes
    shape: AmigaShape

    @classmethod
    def from_bytes(cls, data: bytes | bytearray,
                   shape: AmigaShape = CURSE_SHAPE) -> "AmigaItem":
        if shape.item_size is None or len(data) != shape.item_size:
            raise AmigaRecordError(
                f"an Amiga {shape.title} item node is {shape.item_size} "
                f"bytes, got {len(data)}")
        return cls(bytes(data), shape)

    @property
    def text(self) -> str:
        """The cached display line: the first NUL-terminated run.

        **Never a source.**  It is whatever the ITEMS screen last painted --
        one specimen reads `" Yes  Shield "` with the READY column baked in
        and the other eight do not -- and `goldbox/dos.py` says the same of
        the DOS buffer, which goes stale the same way.
        """
        return self.raw[:self.shape.item_text].split(b"\0")[0].decode("latin1")

    @property
    def words(self) -> list[str]:
        """Every NUL-separated run in the text buffer, display line first."""
        block = self.raw[:self.shape.item_text].rstrip(b"\0")
        return [p.decode("latin1") for p in block.split(b"\0")]

    @property
    def next(self) -> int:
        """The next node's Amiga heap address, `u32` big-endian, 0 at the
        end of a character's chain."""
        at = self.shape.item_text
        return int.from_bytes(self.raw[at:at + 4], "big")

    def get(self, field_name: str):
        """One field, by its `goldbox/dos_layout.py` item-table name."""
        f = dos_layout.item_field_by_name(field_name)
        at = self.shape.item_offset(f.offset)
        chunk = self.raw[at:at + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            return int.from_bytes(chunk, "big")
        if f.kind is Kind.I8:
            return int.from_bytes(chunk, "big", signed=True)
        if f.kind is Kind.U8:
            return chunk[0]
        return chunk

    def to_dos_bytes(self) -> bytes:
        """This node as the 63 bytes `goldbox/dos_layout.py` describes.

        The same re-cut :meth:`AmigaPorItem.to_dos_bytes` makes, through this
        title's own item shift map: the display text becomes DOS's count byte
        and 41, every `u16` is byte-swapped, and the `next` far pointer is
        written NULL because it is a live Amiga heap address.

        **Silver Blades' node is 70 bytes and the last four are not carried.**
        `AMIGA_SSB_SCROLL_CHAIN` heads a scroll's extra spell nodes, and the
        63 bytes DOS's shared item table describes have no room for it; DOS
        Silver Blades' own item is 67 bytes and `#254` is where its last four
        are being read.
        """
        out = bytearray(dos_layout.ITEM_SIZE)
        text = self.raw[:self.shape.item_text]
        line = text.split(b"\0")[0]
        size = dos_layout.ITEM_FIELDS_BY_NAME["text"].size
        out[0] = min(len(line), size)
        out[1:1 + size] = text[:size].ljust(size, b"\0")
        for f in dos_layout.ITEM_LAYOUT:
            if f.name in ("text_length", "text", "next"):
                continue
            at = self.shape.item_offset(f.offset)
            chunk = self.raw[at:at + f.size]
            if f.kind in (Kind.U16LE, Kind.UINT_LE):
                chunk = chunk[::-1]
            out[f.offset:f.offset + f.size] = chunk
        return bytes(out)


@dataclass(frozen=True)
class AmigaCharacter:
    """One Amiga Curse or Silver Blades character, read through the DOS table.

    `items` and `effects` are the nodes that follow the record -- inside the
    saved game for a played character, and after the record in a `.guy` file
    for a pregenerated one.  Neither title keeps them in sibling files the
    way Pool of Radiance's `.itm` and `.spc` do.

    An effect node is the same ten bytes in all three Amiga titles, so
    `amiga_por_effect_to_dos` reads one of these too.  **The id space is
    per-title**: 107 is an elf in Curse and PAINE's ranger effect in Silver
    Blades is 105, so an id must never be carried from one title to another.
    """

    raw: bytes
    shape: AmigaShape
    source: str = ""
    items: tuple[AmigaItem, ...] = ()
    effects: tuple[bytes, ...] = ()

    @classmethod
    def from_bytes(cls, data: bytes | bytearray,
                   shape: AmigaShape | int | None = None,
                   source: str = "",
                   items: Sequence[AmigaItem] = (),
                   effects: Sequence[bytes] = ()) -> "AmigaCharacter":
        if shape is None:
            shape = len(data)
        if isinstance(shape, int):
            got = AMIGA_SHAPES_BY_SIZE.get(shape)
            if got is None:
                raise AmigaRecordError(
                    f"{shape} bytes names no Amiga Gold Box record: Curse is "
                    f"{CURSE_SHAPE.record_size}, Silver Blades "
                    f"{SILVER_BLADES_SHAPE.record_size}, Pool of Radiance "
                    f"{AMIGA_POR_RECORD_SIZE} and Pools of Darkness's .pc "
                    f"{RECORD_LENGTH}")
            shape = got
        if len(data) != shape.record_size:
            raise AmigaRecordError(
                f"an Amiga {shape.title} record is {shape.record_size} "
                f"bytes, got {len(data)}")
        return cls(bytes(data), shape, source, tuple(items), tuple(effects))

    @property
    def name(self) -> str:
        return self.raw[:AMIGA_NAME_SIZE].split(b"\0")[0].decode("latin1")

    def get(self, field_name: str):
        """One field, by its `goldbox/dos_layout.py` name.

        `U16LE` and `UINT_LE` are read big-endian, which -- outside the name,
        the shifts and Silver Blades' spellbook -- is the whole of the
        difference between the two ports.
        """
        f = self.shape.dos_field(field_name)
        at = self.shape.offset(f.offset)
        # Every byte, not just the first: `field_83_87` straddles the window
        # its own insertion is in, and a field half of which is placed is a
        # field nobody has read.
        for i in range(1, f.size):
            self.shape.offset(f.offset + i)
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
        """The six scores.  Both later titles store `(current, maximum)`
        pairs where Pool of Radiance stores one byte; this is the current."""
        return [self.get(k)[0] for k in ABILITY_KEYS]

    @property
    def money(self) -> dict[str, int]:
        return {k: self.get(k) for k in
                ("copper", "silver", "electrum", "gold", "platinum", "gems",
                 "jewelry")}

    @property
    def experience(self) -> int:
        return self.get("experience")

    @property
    def spellbook(self) -> list[int]:
        """The spell ids the character has in the book, ascending.

        Curse reads DOS's byte array straight; Silver Blades unpacks
        `AMIGA_SSB_SPELLBOOK_BYTES` of bitmask, LSB first, id = bit + 1.
        """
        book = self.shape.dos_field("spellbook")
        if self.shape.spellbook_bytes is None:
            at = self.shape.offset(book.offset)
            raw = self.raw[at:at + book.size]
            return [i + dos_layout.SPELLBOOK_FIRST_ID
                    for i, v in enumerate(raw) if v]
        at = book.offset            # shift is zero where the book begins
        mask = self.raw[at:at + self.shape.spellbook_bytes]
        return [i + dos_layout.SPELLBOOK_FIRST_ID
                for i in range(8 * len(mask))
                if mask[i // 8] >> (i % 8) & 1]

    @property
    def effect_chain(self) -> int:
        """The effect list head, `u32` big-endian, where DOS keeps an offset
        word and a segment word."""
        return int.from_bytes(self.get("effect_chain"), "big")

    @property
    def item_chain(self) -> int:
        """The item list head, `u32` big-endian: the first slot of the DOS
        record's 56-byte pointer array, which is what the saved game's writer
        walks and its loader tests."""
        return int.from_bytes(self.get("item_chain")[:4], "big")

    @property
    def status(self) -> int:
        """The state the party panel puts into words, 0 to 8.

        `AMIGA_LATER_STATUS_FIELD`'s first byte, indexing
        `goldbox.neutral.STATUS_NAMES` -- **DOS's own numbering**, read out of
        the string table each title's panel routine indexes.
        """
        return self.get(AMIGA_LATER_STATUS_FIELD)[0]

    @property
    def spell_slots(self) -> dict[str, tuple[int, ...]]:
        """Each spell-slot array, at the width the Amiga record gives it.

        Curse widens all three arrays to **six** bytes where DOS spends five
        and Silver Blades keeps DOS's seven, so the width is taken from the
        shift map -- the distance from one array's Amiga base to the next
        field's -- rather than from the DOS field's own size.  The key is the
        class the array belongs to, or the DOS field's name where nobody has
        attributed it.
        """
        table = dos_layout.layout_for(self.shape.dos)
        out: dict[str, tuple[int, ...]] = {}
        for n, f in enumerate(table):
            if not f.name.startswith("spells_castable"):
                continue
            at = self.shape.offset(f.offset)
            end = (self.shape.offset(table[n + 1].offset)
                   if n + 1 < len(table) else self.shape.record_size)
            out[f.name[len("spells_castable_"):].replace("_", "-")] = tuple(
                self.raw[at:end])
        return out

    def block_bytes(self) -> bytes:
        """The record, its item nodes and its effect chain, as a saved game
        holds them -- and as the loader will accept them.

        The three chain fields the loader tests are made to match what
        actually follows (`_chain_bytes`), and `item_count` is set to the
        number of nodes there really are; everything else is the bytes this
        object was read from.  A block read out of a saved game and written
        back through here is byte for byte the block that came in, because
        `_amiga_block` read the nodes by that same count and a chain field
        whose truth already matches is left alone.
        """
        record = bytearray(self.raw)
        record[self.shape.offset(
            self.shape.dos_field("item_count").offset)] = len(self.items)
        at = self.shape.offset(self.shape.dos_field("item_chain").offset)
        record[at:at + 4] = _chain_bytes(bool(self.items), self.item_chain)
        at = self.shape.offset(self.shape.dos_field("effect_chain").offset)
        record[at:at + 4] = _chain_bytes(bool(self.effects), self.effect_chain)

        items = []
        for n, item in enumerate(self.items):
            raw = bytearray(item.raw)
            here = AMIGA_LATER_ITEM_NEXT
            raw[here:here + 4] = _chain_bytes(n + 1 < len(self.items),
                                              item.next)
            items.append(bytes(raw))
        effects = []
        for n, node in enumerate(self.effects):
            raw = bytearray(node)
            here = AMIGA_LATER_EFFECT_NEXT
            raw[here:here + 4] = _chain_bytes(
                n + 1 < len(self.effects),
                int.from_bytes(node[here:here + 4], "big"))
            effects.append(bytes(raw))
        return bytes(record) + b"".join(items) + b"".join(effects)


def party_block_bytes(characters: Sequence[AmigaCharacter]) -> bytes:
    """A saved game's whole character region, in marching order.

    The party is a plain concatenation of :meth:`AmigaCharacter.block_bytes`
    with no separator and no index: the loader reads the party-count word and
    then reads one block after another off the same file descriptor, so the
    blocks' own lengths are what tell it where each begins.
    """
    return b"".join(c.block_bytes() for c in characters)


def _amiga_block(data: bytes, at: int, shape: AmigaShape,
                 source: str = "") -> "tuple[AmigaCharacter, int]":
    """One character and everything hanging off it, and where it ends.

    The layout is **record, then `item_count` item nodes, then the effect
    chain**, and it is the same inside a saved game as it is in a `.guy`
    file.  CONFIRMED on the four played Curse characters, whose blocks are
    570, 590, 636 and 600 bytes: `428 + 66 x items + 10 x effects` is exact
    in 4 of 4, and the effect count is what the chain's own NULL terminator
    says it is.
    """
    end = at + shape.record_size
    if end > len(data):
        raise AmigaRecordError(
            f"a {shape.title} record wants {shape.record_size} bytes at "
            f"{at:#x} and only {len(data) - at} are there")
    record = data[at:end]
    count = record[shape.offset(shape.dos_field("item_count").offset)]
    items = []
    for _ in range(count):
        if shape.item_size is None:
            raise AmigaRecordError(
                f"{shape.title} carries {count} items and no Amiga item node "
                f"of that title has ever been measured")
        items.append(AmigaItem.from_bytes(data[end:end + shape.item_size],
                                          shape))
        end += shape.item_size
    effects = []
    if int.from_bytes(record[shape.offset(shape.dos_field(
            "effect_chain").offset):][:4], "big"):
        while end + shape.effect_size <= len(data):
            node = data[end:end + shape.effect_size]
            end += shape.effect_size
            effects.append(node)
            if not int.from_bytes(node[6:10], "big"):
                break
        else:
            raise AmigaRecordError(
                f"the effect chain of the {shape.title} record at {at:#x} "
                f"runs off the end of the data without a NULL next pointer")
    return AmigaCharacter.from_bytes(record, shape, source, items,
                                     effects), end


def read_amiga_guy(path) -> AmigaCharacter:
    """One `SAVE/<NAME>.guy` -- an Amiga Curse pregenerated character.

    The eleven on Amiga Curse disk 1 are 428, 438, 458 and 468 bytes, which
    is 0, 1, 3 and 4 effect nodes, and the ids land on the right race in 11
    of 11: 107 for the two elves, 124 for the two half-elves, the dwarves'
    97/26/47, the gnome's 97/18/47/48 and 8 for the paladin.
    """
    import pathlib
    p = pathlib.Path(path)
    char, end = _amiga_block(p.read_bytes(), 0, CURSE_SHAPE, str(p))
    if end != p.stat().st_size:
        raise AmigaRecordError(
            f"{p.name} is {p.stat().st_size} bytes and its record, items and "
            f"effects account for {end}")
    return char


def looks_like_amiga_record(data: bytes, at: int, shape: AmigaShape) -> bool:
    """Whether a character record plausibly starts here.

    Two things a saved game's other bytes do not do together: **16 bytes of
    printable ASCII terminated and padded with NUL**, and **six
    `(current, maximum)` ability pairs of equal, legal bytes** at `0x010`.
    On the two saved games this project has, it finds the four Curse
    characters at `0x3219`, `0x3453`, `0x36A1` and `0x391D` and the six
    Silver Blades ones at `0x1417` onwards, and nothing else in 22 454 bytes.

    **It would miss a character whose abilities have been drained**, because
    the pair test wants current and maximum equal and a drained score is
    below its maximum.  Every specimen this project has is undrained, so the
    looser test has never been needed; a saved game taken after a shadow or
    a wight is what would need it.
    """
    if at < 0 or at + shape.record_size > len(data):
        return False
    name = data[at:at + AMIGA_NAME_SIZE]
    stop = name.find(b"\0")
    if stop < 1 or any(name[stop:]):
        return False
    if not all(0x20 <= b < 0x7F for b in name[:stop]):
        return False
    for i in range(6):
        low, high = data[at + 0x10 + 2 * i], data[at + 0x11 + 2 * i]
        if low != high or not 1 <= low <= 25:
            return False
    return True


def party_in_savegame(data: bytes, shape: AmigaShape) -> list[AmigaCharacter]:
    """Every character block in an Amiga `savgam<slot>.dat` or `.sav`.

    A scan rather than a parse: the saved game's own table of contents is
    `#28 (Decode an Amiga saved game, not just a character file)`'s to find,
    and this needs only the character blocks.  `looks_like_amiga_record` says
    what the signature is and what it found.
    """
    found: list[AmigaCharacter] = []
    at = 0
    while at + shape.record_size <= len(data):
        if looks_like_amiga_record(data, at, shape):
            char, at = _amiga_block(data, at, shape, "savegame")
            found.append(char)
        else:
            at += 1
    return found


# ---------------------------------------------------------------------------
# Amiga Curse and Silver Blades -> the neutral record (#28, step 3)
# ---------------------------------------------------------------------------
#
# The third and fourth readers in `goldbox/neutral.py`'s set, beside
# `goldbox.c64_codec.read`, `goldbox.dos.to_neutral` and `to_neutral` above.
#
# **It does not go through `goldbox.dos.to_neutral` the way the Amiga Pool of
# Radiance reader does, and that is not a choice.**  That reader re-cuts its
# record into the 285-byte DOS one and hands it over, so every grade and every
# provenance line the DOS side earned carries across.  `goldbox.dos.to_neutral`
# raises `WrongTitleError` for anything but Pool of Radiance -- no other pair
# of ports has been measured against each other yet (#53) -- so there is
# nothing here to hand a Curse record to.  What this reader shares with it
# instead is the **field table**: every value below is read through
# `goldbox/dos_layout.py`'s own table for the title, at that field's own
# confidence, so a correction there reaches here with no second edit.
#
# Two conventions come from what landed for the DOS side on 2026-09-04 and are
# followed rather than reinvented:
#
#   * `granted_effects` carries **whole nine-byte effect records** -- the id,
#     a little-endian duration of zero, the value the effect carries and the
#     flag the engine reads when the item comes off -- because what a ring is
#     worth is in the record rather than in the id (#232);
#   * `status` is carried as a **name** (#235).  Here the name costs nothing:
#     both later Amiga titles index `neutral.STATUS_NAMES` in DOS's own order,
#     which is measured rather than assumed -- see
#     `AMIGA_LATER_STATUS_FIELD` above for the two string tables.
#
#: Fields of the title's DOS table with a neutral home of the same name.
#: Taken from `goldbox.dos.DIRECT` at call time rather than copied, because a
#: field that changes meaning there must not go on meaning the old thing here.
#: Every one of the fifty is in both later titles' tables.
#:
#: What is **not** here and is carried by a rule below: the name, the
#: spellbook, the memorised spells, the level arrays, the spell-slot arrays,
#: size, turn power, the status and its flag, the attack forms, the roster
#: tail, the effect records and the items.
LATER_TRANSFORMED: tuple[tuple[str, str], ...] = (
    ("name_length", "there is no count byte: the Amiga name is 16 bytes "
                    "terminated and padded with NUL"),
    ("name_text", "the sixteen NUL-padded bytes, as the neutral name"),
    ("spellbook", "the spell ids in the book, ascending; Silver Blades' 15 "
                  "bytes of bitmask are unpacked and Curse's 100 flags read "
                  "straight"),
    ("spells_memorised", "reversed, the way the DOS reader reads its own: "
                         "highest first"),
    ("class_levels", "named rather than numbered, into the neutral levels "
                     "map"),
    ("spells_castable_cleric", "into the neutral spells_castable map, at the "
                               "Amiga's own array width"),
    ("spells_castable_druid", "into the same map"),
    ("spells_castable_magic_user", "into the same map"),
    ("size", "1/2 on DOS becomes 0/1 in the neutral size_small"),
    ("turn_power", "copied, as the DOS reader copies it"),
    ("attack_forms", "copied as a block"),
    ("roster_tail", "copied as a block"),
    ("field_10c_10f", "its first byte becomes the neutral status, by name, "
                      "and its second the active flag; the last two are not "
                      "carried"),
    ("encumbrance", "copied, and it is money plus item weight -- a writer "
                    "that recomputes it should"),
)

#: Fields the read leaves behind, and why.  Every one is reported: a drop that
#: nobody names is what `docs/117-save-conversion.md` forbids.
LATER_DROPPED: tuple[tuple[str, str], ...] = (
    ("former_class_levels", "what each class was before the character dual-"
                            "classed. **There is no neutral field for it**: "
                            "`goldbox/neutral.py` has `levels` and nothing "
                            "beside it, and adding one obliges every writer "
                            "to declare what it does with the name -- three "
                            "modules, which is why this is #256 rather than "
                            "half a change"),
    ("item_chain", "live heap state: the head of the Amiga's item list, "
                   "which the loader overwrites with the address it "
                   "allocates. The items themselves are carried"),
    ("item_count", "implied by the inventory that is carried"),
    ("effect_chain", "live heap state, the same way; the effect records "
                     "themselves are carried"),
    ("heap_104", "live heap pointers -- two longwords the saved game's own "
                 "loader clears outright"),
    ("hands_used", "live combat state"),
    ("unnamed_0ab", "one unattributed byte, stable per character"),
    ("strength_bonus", "a boolean on DOS, derived from strength"),
    ("icon_colours", "the combat icon's colour pairs, which are art"),
    ("icon_head", "combat icon art, an index into this port's own library"),
    ("icon_body", "combat icon art, likewise"),
    ("icon_dimension", "the combat icon's size"),
    ("portrait_head", "the sheet portrait's head: a position in the Amiga's "
                      "own creation menu, and nobody has read that menu's "
                      "tables out of the Amiga executables. Reading them is "
                      "what would let the portrait cross, exactly as it did "
                      "for DOS"),
    ("portrait_body", "see portrait_head; the body half of the same pair"),
    ("field_83_87", "five bytes DOS calls unknown and every specimen of "
                    "either title reads zero"),
    ("spells_castable_unattributed", "Silver Blades' fourth spell-slot "
                                     "array, which no character of either "
                                     "port sets a byte of and no class has "
                                     "been shown to use"),
)

#: The plain-English half of `LATER_DROPPED`, and the only one a person ever
#: reads.  `.claude/rules/gui-text.md` keeps a memory address, a file offset
#: and a bare issue number out of anything shown in the interface, and the
#: entries above carry all three kinds of detail on purpose -- so the reader
#: composes its report from this table and never from those.  A name with no
#: entry here is a drop the report stays silent about; only the fields whose
#: loss a player could notice have one, which is the same line
#: `goldbox/dos.py` draws with `UNREPORTED_DROPS`.
LATER_DROPPED_PLAYER_TEXT: dict[str, str] = {
    "former_class_levels": "The levels a dual-classed character reached in "
                           "the class they gave up: the conversion has "
                           "nowhere to put them yet",
    "item_chain": "Item list bookkeeping: the list's own internal links, "
                  "which the game rebuilds when it loads the party",
    "effect_chain": "The running-effects list's own internal link; the "
                    "effects themselves are carried separately",
    "heap_104": "Internal game state kept only while the game is running, "
                "not shown to the player",
    "hands_used": "Which hand is holding a weapon right now; set again the "
                  "next time the character fights",
    "unnamed_0ab": "One byte in the character record nobody has identified "
                   "yet",
    "icon_colours": "Combat icon colours: this conversion does not carry the "
                    "combat icon",
    "icon_head": "Combat icon (head): this conversion does not carry the "
                 "combat icon",
    "icon_body": "Combat icon (body): this conversion does not carry the "
                 "combat icon",
    "icon_dimension": "Combat icon size: this conversion does not carry the "
                      "combat icon",
    "portrait_head": "Character portrait (head): the character-creation art "
                     "this game chooses portraits from has not been read, so "
                     "the portrait cannot be matched",
    "portrait_body": "Character portrait (body): the character-creation art "
                     "this game chooses portraits from has not been read, so "
                     "the portrait cannot be matched",
    "field_83_87": "Five bytes that make no difference to the character "
                   "sheet, whatever they hold",
    "spells_castable_unattributed": "A fourth list of spell slots that no "
                                    "character of this game uses and no "
                                    "class has been shown to own",
}

#: The one thing the neutral record cannot say about these two titles, and it
#: is a classification rather than a byte: which effect records are **innate**
#: -- a property of the race or the class -- and which an item granted.
#: `goldbox.dos.INNATE_EFFECTS` is Pool of Radiance's id space and must not be
#: applied here: 107 is an elf in Curse where Silver Blades' PAINE carries 105
#: for a ranger, so the two titles do not even share one namespace with each
#: other.  Everything at duration zero therefore goes into `granted_effects`
#: whole, and this warning says so.
LATER_EFFECT_SPLIT_UNKNOWN = (
    "The effects that never expire are all carried together: which of them "
    "are racial or class properties and which came from an item cannot be "
    "told apart yet for this game, because the list of built-in effects has "
    "only ever been read for Pool of Radiance")


def later_field_disposition(shape: AmigaShape) -> dict[str, str]:
    """Every field of this title's DOS table, and what the read does with it.

    The test that keeps the reader honest, and the same shape
    `goldbox.dos.field_disposition` returns: a field the table declares and
    this names nowhere would be a field dropped in silence.  `gap_` fields are
    the bytes no field of the DOS table claims and are accounted for here as a
    group rather than one at a time.
    """
    from . import dos as _dos

    declared = {f.name for f in dos_layout.layout_for(shape.dos)}
    direct = [(n, n) for n, _ in _dos.DIRECT if n in declared]
    transformed = [(n, why) for n, why in LATER_TRANSFORMED if n in declared]
    dropped = [(n, why) for n, why in LATER_DROPPED if n in declared]
    dropped += [(n, "bytes no field of the DOS table for this title claims")
                for n in sorted(declared) if n.startswith("gap_")]
    return neutral.disposition(direct, transformed, dropped, "the neutral")


def to_neutral_later(char: AmigaCharacter) -> NeutralCharacter:
    """One Amiga Curse or Silver Blades character in the neutral record.

    Every value is read through `goldbox/dos_layout.py`'s table for the
    title, at that field's own confidence, so a writer asking for a grade it
    will stand behind gets the same answer it would get from a DOS record of
    the same title.  What the record holds and no neutral field does is named
    on the way past rather than lost -- `LATER_DROPPED` is the whole list and
    :func:`later_field_disposition` is the test that it is.
    """
    from . import dos as _dos

    shape = char.shape
    table = dos_layout.FIELDS_BY_NAME_FOR[shape.dos.key]
    out = NeutralCharacter("Amiga", source=char.source,
                           game=games.by_key(shape.key))

    def grade(name: str) -> Confidence:
        return table[name].confidence

    out.set("name", char.name,
            f"the Amiga {AMIGA_NAME_SIZE}-byte NUL-padded name at 0x000",
            grade("name_text"), neutral.Provenance.RESHAPED)

    for name, _ in _dos.DIRECT:
        f = table[name]
        out.set(name, char.get(name),
                f"Amiga {shape.title} {name} @{shape.offset(f.offset):#05x} "
                f"({f.confidence}), read big-endian through the DOS table",
                f.confidence)

    out.set("spells_known", char.spellbook,
            "the Amiga spellbook, "
            + ("15 bytes of bitmask unpacked least significant bit first"
               if shape.spellbook_bytes else "one byte per spell"),
            grade("spellbook"))

    memorised = [b for b in reversed(char.get("spells_memorised")) if b]
    out.set("spells_memorised", memorised,
            "the Amiga memorised region, reversed into the neutral "
            "highest-first order",
            grade("spells_memorised"))
    if not memorised:
        out.warnings.append(
            "No character of this game on any disk here has a spell "
            "memorised, so the order they are stored in has not been checked "
            "for it; the order the other games use was assumed")

    slots = table["class_levels"].size
    named = _dos.CLASS_LEVEL_SLOTS[:slots]
    raw = char.get("class_levels")
    out.set("levels", {name: raw[n] for n, name, _ in named},
            f"Amiga class_levels @"
            f"{shape.offset(table['class_levels'].offset):#05x}, permuted "
            f"from class number to class name",
            grade("class_levels"))

    castable = dict(char.spell_slots)
    castable.pop("unattributed", None)
    out.set("spells_castable", castable,
            "the Amiga spell-slot arrays, "
            + ("six bytes each where DOS spends five"
               if shape is CURSE_SHAPE else "seven bytes each, as DOS"),
            grade("spells_castable_cleric"))

    out.set("size_small", max(0, char.get("size") - 1),
            "the Amiga size byte, less one", grade("size"))
    out.set("turn_power", char.get("turn_power"),
            f"Amiga turn_power @{shape.offset(table['turn_power'].offset):#05x}",
            grade("turn_power"))
    out.set("attack_forms", char.get("attack_forms"),
            f"Amiga attack_forms @"
            f"{shape.offset(table['attack_forms'].offset):#05x}",
            grade("attack_forms"))
    out.set("roster_tail", char.get("roster_tail"),
            f"Amiga roster_tail @"
            f"{shape.offset(table['roster_tail'].offset):#05x}",
            grade("roster_tail"))
    out.set("encumbrance", char.get("encumbrance"),
            f"Amiga encumbrance @"
            f"{shape.offset(table['encumbrance'].offset):#05x}",
            grade("encumbrance"))

    tail = char.get(AMIGA_LATER_STATUS_FIELD)
    at = shape.offset(table[AMIGA_LATER_STATUS_FIELD].offset)
    if tail[0] < len(neutral.STATUS_NAMES):
        out.set("status", neutral.STATUS_NAMES[tail[0]],
                f"Amiga status @{at:#05x} = {tail[0]}, the same "
                f"{len(neutral.STATUS_NAMES)} status words in the same order "
                f"the DOS record indexes",
                Confidence.CONFIRMED, neutral.Provenance.RESHAPED)
    else:
        out.drop(f"The character's status: this save holds {tail[0]} there "
                 f"and the game has only {len(neutral.STATUS_NAMES)} states")
    out.set("active", bool(tail[AMIGA_LATER_STATUS_GATE]),
            f"Amiga @{at + AMIGA_LATER_STATUS_GATE:#05x}: the flag the engine "
            f"clears whenever the status leaves okay or animated",
            Confidence.PROBABLE)

    granted = [amiga_por_effect_to_dos(e) for e in char.effects]
    granted = [e for e in granted if int.from_bytes(e[1:3], "little") == 0]
    if granted:
        out.set("granted_effects", granted,
                "the Amiga effect nodes that never expire, each re-cut to "
                "the nine bytes the DOS .SPC record holds",
                Confidence.PROBABLE)
        out.warnings.append(LATER_EFFECT_SPLIT_UNKNOWN)

    out.set("inventory", [_dos.item_to_c64(it.to_dos_bytes())
                          for it in char.items],
            f"the {shape.item_size}-byte Amiga item nodes, each re-cut to the "
            f"63 DOS holds and projected onto sixteen",
            Confidence.CONFIRMED)

    declared = {f.name for f in dos_layout.layout_for(shape.dos)}
    for name, _why in LATER_DROPPED:
        if name in declared and name in LATER_DROPPED_PLAYER_TEXT:
            out.drop(LATER_DROPPED_PLAYER_TEXT[name])
    return out
