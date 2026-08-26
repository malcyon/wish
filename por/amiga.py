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

import struct
from dataclasses import dataclass, field

from . import games, neutral
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
# Anything -> Amiga: the writing half of the pair `por/neutral.py` describes
# ---------------------------------------------------------------------------
# The middle is a `NeutralCharacter`, the same record `por/dos.py` reads into
# and `por/c64_codec.py` writes out of. Nothing here reads a `CharacterRecord`
# and nothing here reads another codec's output: this module is one writer, it
# names neutral fields, and what produced them is somebody else's business.
# That is what makes a fourth format cost one reader rather than a converter
# per pair.
#
# The direction is one way. `wish` never reads an Amiga record back into a C64
# save, and `docs/124-amiga-port.md` sec 9 says why: there is no C64 Pools of
# Darkness to go back to.


#: Gold Box race names -> PoD's own six-entry table. The C64 tables differ per
#: title (`por/games.py`), which is exactly why the conversion goes by name
#: and not by number: the neutral `race` is an index into the *source title's*
#: table and `por.games.race_table` is what turns it into a name.
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

    The same bargain `por/c64_codec.py` strikes in the other direction, in the
    one shape `por/neutral.py` gives every direction: a field the Amiga cannot
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

    The test that keeps this module honest: a field `por/neutral.py` declares
    and this table does not name would be a field silently dropped.  The
    shape is `por/neutral.py`'s, so every direction reports the same way.
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
            warnings.append(f"class {key} -> {replacement}: {why}")
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
            f"name {name!r} is {len(name)} characters; PoD keeps "
            f"{NAME_LENGTH}, so it arrives as {name[:NAME_LENGTH]!r}")

    race_value = w.use("race")
    race_key = str(_races(char).get(
        race_value.value if race_value else None, "")).strip().lower()
    if race_key in RACE_SUBSTITUTE:
        replacement, why = RACE_SUBSTITUTE[race_key]
        rep.warnings.append(f"race {race_key} -> {replacement.lower()}: {why}")
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
            f"hit points maximum {hp_max} does not fit the Amiga's one byte "
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
            "no current hit points in the source, so they are set to the "
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
                f"the file name {base!r} is already used by another "
                f"character in this export; written instead as {filename!r}")
        used.add(filename)
        path = root / filename
        path.write_bytes(record)
        out.append((path, rep))
    return out
