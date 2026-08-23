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

from . import neutral

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
# C64 -> Amiga: the conversion, through the neutral form
# ---------------------------------------------------------------------------
# The middle is `por/yaml_io.py`'s `entry_for` dictionary -- the same one the
# editor round-trips and the same one `por/dos.py` builds a DOS party into.
# Nothing here reads a `CharacterRecord`: it reads named fields, so a C64
# title's own race and class tables have already been applied and this module
# never has to know which of the six games the character came from.
#
# The direction is one way. `wish` never reads an Amiga record back into a C64
# save, and `docs/124-amiga-port.md` sec 9 says why: there is no C64 Pools of
# Darkness to go back to.


#: Pool of Radiance's races by name -> PoD's own six-entry table. The tables
#: differ per title on the C64 alone (`por/games.py`), which is exactly why
#: the conversion goes by name and not by number.
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

#: C64 class name -> the slot its level occupies in the seven-byte array at
#: 0x09D. The array is indexed by PoD's *single-class* code, which is how it
#: was identified: every single-classed specimen on disk 3 has its one
#: non-zero level in the slot its class code names.
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
#: and 0x80 separately. So the mask is *not* the C64's byte and must not be
#: copied across. PROBABLE: the twelve agree, but no probe has put the byte on
#: screen.
CLASS_BIT: dict[str, int] = {
    "magic-user": 1, "cleric": 2, "thief": 4, "fighter": 8,
    "paladin": 64, "ranger": 64,
}

#: Class combinations -> PoD's class code. Only the combinations both ports
#: have; a C64 pairing PoD's table has no entry for is refused rather than
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

#: `yaml_io.ALIGNMENTS` is already `law * 3 + morality` in PoD's own order, so
#: the index crosses unchanged. Spelled out rather than assumed, because the
#: two lists agreeing is a fact about them and not a rule.
ALIGNMENT_FROM_C64: dict[str, int] = {
    "lawful good": 0, "lawful neutral": 1, "lawful evil": 2,
    "neutral good": 3, "true neutral": 4, "neutral evil": 5,
    "chaotic good": 6, "chaotic neutral": 7, "chaotic evil": 8,
}

SEX_FROM_C64: dict[str, int] = {"male": 0, "female": 1}

#: The six abilities in the order the sheet draws them, which is also the
#: order `yaml_io.EDITABLE` lists them in.
ABILITY_KEYS = ("strength", "intelligence", "wisdom", "dexterity",
                "constitution", "charisma")

SAVE_KEYS = ("save_paralysis", "save_petrification", "save_wands",
             "save_breath", "save_spell")

THIEF_KEYS = ("thief_pick_pockets", "thief_open_locks", "thief_find_traps",
              "thief_move_silently", "thief_hide_in_shadows",
              "thief_hear_noise", "thief_climb_walls",
              "thief_read_languages")

#: What an unarmoured, unarmed character is, and what all twelve genuine
#: records hold: armour class 10 and 1d2. **Not** carried from the C64. The
#: C64's armour class is a cache that already includes worn armour and a
#: dexterity bonus, PoD re-applies dexterity itself, and no item crosses -- so
#: a converted character genuinely arrives with nothing on and 10 is the right
#: answer rather than a lossy one.
UNARMOURED_AC = 10
UNARMED_DAMAGE = (1, 2, 0)

#: AmigaDOS names on disk 3: uppercase, spaces removed, eight characters.
#: `MAGIC JHONSON` is `MAGICJHO.pc` and `TRIPEL TURBO` is `TRIPELTU.pc`.
FILENAME_LENGTH = 8


class ConversionError(ValueError):
    """A C64 character Pools of Darkness has no way to represent."""


@dataclass
class Report(neutral.Report):
    """Where every non-zero byte of the `.pc` came from, and what stayed.

    The same bargain `por/dos.py` strikes in the other direction, in the one
    shape `por/neutral.py` gives every direction: a field the Amiga cannot
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


#: Neutral-form field -> the Amiga field it becomes, where the value crosses
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
)

#: Fields converted by a rule rather than by a copy.
TRANSFORMED: tuple[tuple[str, str], ...] = (
    ("name", "truncated from the C64's 20 bytes to the Amiga's 15 at 0x060"),
    ("sex", "name -> index, MALE 0 FEMALE 1"),
    ("race", "name -> PoD's own six-entry table; a race PoD lacks is "
             "substituted and reported"),
    ("alignment", "name -> law * 3 + morality, which is the same index the "
                  "C64 uses"),
    ("classes", "names -> PoD's 17-entry class code at 0x059 and its class "
                "bitmask at 0x0B7, which is not the C64's byte"),
    ("class_code", "recomputed from `classes`; the C64 code and PoD's are "
                   "different tables"),
    ("levels", "spread into the seven-slot array at 0x09D, indexed by PoD's "
               "single-class code"),
    ("hp_max", "the C64 keeps a 16-bit maximum, the Amiga one byte at 0x081; "
               "above 255 it is clamped and reported"),
    ("combat", "only `hp_current` is taken, into the u16 at 0x190. THAC0, "
               "armour class, the damage bonus and the second movement byte "
               "are all recomputed by PoD on load and its copies ignored"),
    *((k, "one of the six abilities at 0x070, written to both halves of its "
          "base/current pair") for k in ABILITY_KEYS),
    *((k, "one of the five saving throws at 0x083, in the same order: the "
          "twelve genuine records decode to the AD&D table for their class "
          "and level in exactly this order") for k in SAVE_KEYS),
    *((k, "one of the eight thief skills at 0x08B, in the same order: hear "
          "noise is low and climb walls high in both") for k in THIEF_KEYS),
)

#: Fields deliberately left behind, and why. Reported, never silent.
DROPPED: tuple[tuple[str, str], ...] = (
    ("slot", "names the output file; not a field of the record"),
    ("copper", "only platinum, gems and jewelry have been located in the "
               "`.pc`; the lighter coins have no known home"),
    ("silver", "no located home -- see `copper`"),
    ("electrum", "no located home -- see `copper`"),
    ("gold", "no located home -- see `copper`"),
    ("infravision", "no located home; PoD derives what it needs from race"),
    ("hp_rolled", "the C64's pre-constitution roll; the Amiga keeps only the "
                  "maximum"),
    ("portrait_head", "PoD's art is `CHEAD.TLB`, a different set with "
                      "different numbering. A copied index is a wrong "
                      "picture, silently"),
    ("portrait_body", "PoD's art is `CBODY.TLB` -- see `portrait_head`"),
    ("icon", "the C64 combat icon is 18 screen codes into `CHARPIC00` plus 18 "
             "colours. It is a C64 character set and the Amiga has nothing of "
             "the kind"),
    ("items", "the appended item region past 484 bytes is undecoded, and a "
              "Silver Blades item id and a Pools of Darkness one are two "
              "different games' tables. The character arrives carrying "
              "nothing"),
    ("spells", "PoD runs cleric spells to level 7 and mage to 9, so its id "
               "space is larger than the C64's 1-56 and the mapping is not "
               "the identity. Re-memorise in game"),
    ("spells_known", "the spellbook's home in the `.pc` is undecoded -- see "
                     "`spells`"),
    ("npc", "a C64 roster flag; PoD decides for itself what it has just "
            "imported"),
)


def field_disposition() -> dict[str, str]:
    """Every neutral-form field and what the conversion does with it.

    The test that keeps this module honest: a field `yaml_io.entry_for`
    produces and this table does not name would be a field silently dropped.
    The shape is `por/neutral.py`'s, so every direction reports the same way.
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


def _classes_of(entry: dict) -> tuple[list[str], list[str]]:
    """The character's classes as PoD names them, plus any substitutions."""
    warnings: list[str] = []
    out: list[str] = []
    for raw in entry.get("classes") or []:
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


def from_entry(entry: dict) -> tuple[PodWriter, Report]:
    """One `yaml_io.entry_for` dictionary as a `PodWriter` and its report.

    Everything the Amiga cannot hold lands in `Report.dropped`; everything it
    holds differently lands in `Report.warnings`.
    """
    rep = Report()
    # Unconditionally, as `por/dos.py` does in the other direction: the report
    # is the conversion's whole contract, not a list of what this one
    # character happened to be carrying.
    for name, why in DROPPED:
        rep.dropped.append(f"{name}: {why}")

    name = str(entry.get("name", "")).rstrip("\0").strip()
    if not name:
        raise ConversionError("a character with no name cannot be converted")
    if len(name) > NAME_LENGTH:
        rep.warnings.append(
            f"name {name!r} is {len(name)} characters; PoD keeps "
            f"{NAME_LENGTH}, so it arrives as {name[:NAME_LENGTH]!r}")

    race_key = str(entry.get("race", "")).strip().lower()
    if race_key in RACE_SUBSTITUTE:
        replacement, why = RACE_SUBSTITUTE[race_key]
        rep.warnings.append(f"race {race_key} -> {replacement.lower()}: {why}")
        race_name = replacement
    elif race_key in RACE_FROM_C64:
        race_name = RACE_FROM_C64[race_key]
    else:
        raise ConversionError(
            f"race {entry.get('race')!r} has no Pools of Darkness equivalent")

    sex_key = str(entry.get("sex", "")).strip().lower()
    if sex_key not in SEX_FROM_C64:
        raise ConversionError(f"sex {entry.get('sex')!r} is not male or female")

    align_key = str(entry.get("alignment", "")).strip().lower()
    if align_key not in ALIGNMENT_FROM_C64:
        raise ConversionError(
            f"alignment {entry.get('alignment')!r} is not one of "
            f"{', '.join(ALIGNMENT_FROM_C64)}")

    classes, class_warnings = _classes_of(entry)
    rep.warnings.extend(class_warnings)
    combination = frozenset(classes)
    if combination not in CLASS_CODE_FROM_C64:
        raise ConversionError(
            "Pools of Darkness has no class code for "
            + "/".join(sorted(classes))
            + "; its table is: " + ", ".join(sorted(
                v for v in CLASS_CODE_FROM_C64.values())))

    levels = {str(k).strip().lower(): int(v)
              for k, v in (entry.get("levels") or {}).items()}
    slots = [0] * CLASS_LEVEL_COUNT
    for c64_name in classes:
        level = levels.get(c64_name, 0)
        # A knight's level arrives under its own name, not the fighter's.
        if not level:
            for original, (replacement, _) in CLASS_SUBSTITUTE.items():
                if replacement == c64_name:
                    level = levels.get(original, level)
        slots[CLASS_LEVEL_SLOTS.index(CLASS_LEVEL_SLOT[c64_name])] = level

    hp_max = int(entry.get("hp_max") or 0)
    if hp_max > 0xFF:
        rep.warnings.append(
            f"hit points maximum {hp_max} does not fit the Amiga's one byte "
            f"at {HP_MAX:#05x}; clamped to 255")
        hp_max = 0xFF

    combat = entry.get("combat") or {}
    if combat:
        current = int(combat.get("hp_current", hp_max))
        for key in ("thac0", "armour_class", "damage_bonus",
                    "movement_current"):
            if key in combat:
                rep.dropped.append(
                    f"combat.{key}: PoD recomputes it on load from the base "
                    f"values and ignores what the file says")
        if "unknown_03_05" in combat:
            rep.dropped.append(
                "combat.unknown_03_05: three undecoded C64 roster bytes, with "
                "nothing to map them to")
    else:
        current = hp_max
        rep.warnings.append(
            "no party roster in the source, so current hit points are set to "
            "the maximum")
    if current > hp_max:
        current = hp_max

    lighter = sum(int(entry.get(k) or 0)
                  for k in ("copper", "silver", "electrum", "gold"))
    if lighter:
        rep.warnings.append(
            f"{lighter} copper, silver, electrum and gold pieces are left "
            f"behind: only platinum, gems and jewelry have a located home in "
            f"the .pc")

    rep.dropped.append(
        "armour class and damage: the C64's are caches that already include "
        "worn armour and a strength bonus, no item crosses, and PoD "
        "re-applies dexterity itself -- so the record gets an unarmoured "
        f"{UNARMOURED_AC} and {UNARMED_DAMAGE[0]}d{UNARMED_DAMAGE[1]}, which "
        "is what all twelve genuine records hold")

    writer = PodWriter(
        name=name[:NAME_LENGTH],
        race=RACES.index(race_name),
        character_class=CLASSES.index(CLASS_CODE_FROM_C64[combination]),
        sex=SEX_FROM_C64[sex_key],
        alignment=ALIGNMENT_FROM_C64[align_key],
        age=int(entry.get("age") or 0),
        experience=int(entry.get("experience") or 0),
        platinum=int(entry.get("platinum") or 0),
        gems=int(entry.get("gems") or 0),
        jewelry=int(entry.get("jewelry") or 0),
        abilities=tuple(int(entry.get(k) or 0) for k in ABILITY_KEYS),
        exceptional_strength=int(entry.get("exceptional_strength") or 0),
        hit_points_max=hp_max,
        hit_points_current=current,
        movement=int(entry.get("movement") or 0),
        class_levels=tuple(slots),
        damage=UNARMED_DAMAGE,
        armour_class=UNARMOURED_AC,
        level=int(entry.get("level") or max(slots)),
        saving_throws=tuple(int(entry.get(k) or 0) for k in SAVE_KEYS),
        thief_skills=tuple(int(entry.get(k) or 0) for k in THIEF_KEYS),
        class_bits=sum(CLASS_BIT[c] for c in set(classes)),
    )
    return writer, rep


def to_pc(entry: dict) -> tuple[bytes, Report]:
    """One neutral-form character as the 484 bytes of a `Save/NAME.pc`."""
    writer, rep = from_entry(entry)
    record = writer.to_bytes()
    for offset, who in writer.provenance().items():
        rep.sources[offset] = f"{who} <- C64 {_SOURCE_OF.get(who, who)}"
    return record, rep


#: Which neutral-form field each written Amiga field came from, for the
#: provenance report. Kept beside the writer's own plan so the two cannot
#: drift apart without a test noticing.
_SOURCE_OF: dict[str, str] = {
    "name": "name",
    "race": "race",
    "character_class": "classes",
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
    "hit_points_current": "combat.hp_current",
    "movement": "movement",
    "class_levels": "levels",
    "damage": "nothing -- unarmed 1d2, the constant all twelve records hold",
    "armour_class": "nothing -- unarmoured 10, the constant all twelve hold",
    "level": "level",
    "saving_throws": "save_paralysis..save_spell",
    "thief_skills": "thief_pick_pockets..thief_read_languages",
    "class_bits": "classes",
}


def export_party(save_path, out_dir, game_disk=None) -> list[tuple]:
    """A whole C64 party from a save disk into a `SAVE` drawer's worth of
    `.pc` files.

    Returns one `(path, Report)` per character. The C64 disk is opened
    read-only; `out_dir` is created if it is not there.
    """
    import pathlib

    from .yaml_io import export_save

    doc = export_save(str(save_path), game_disk)
    root = pathlib.Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    out = []
    for entry in doc["party"]:
        record, rep = to_pc(entry)
        path = root / pc_filename(str(entry["name"]))
        path.write_bytes(record)
        out.append((path, rep))
    return out
