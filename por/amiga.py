"""Amiga Pools of Darkness character files (`Save/NAME.pc`).

Everything here was read off the screen: a `.pc` was written onto a copy of
PoD's disk 3, added through `Add Character -> Pools`, and the character sheet
photographed. The payload is a 582-byte C64 export with a window of bytes
replaced by a ramp whose value *is* the file offset, so a number the sheet
draws names the offset it came from. `docs/124-amiga-port.md` has the runs.

Two things make that possible at all, both measured rather than assumed:
Amiga PoD applies **no length check and no signature check** to a `.pc`, and
the `0x00`-`0x5F` longwords that a genuine file fills with Amiga heap
addresses are don't-care on load.

**Everything is big-endian.** It is a 68000.

The offsets were found by watching PoD *misread* a C64 record, so they were
checked a second way: they decode the twelve genuine `.pc` files on disk 3 to
sane values -- every ability 18, one class level each, armour class 10 and 1d2
damage unequipped, ages 28 to 46 -- and TROND's 138 here is the `HP 138` the
roster drew when TROND was added. `tests/test_amiga.py` asserts both halves.

This module is deliberately read-only and deliberately partial. It names the
offsets the sheet has confirmed and nothing else; a writer needs the item
region at `0xB6` onwards, which is still `UNKNOWN` and which the game does
parse -- garbage there gives `ERROR: INVALID ITEM`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

#: The C64 record's `60 - value` bias turns up here too, on armour class.
COMBAT_BIAS = 60

NAME = 0x060
NAME_LENGTH = 15             # 15 characters, NUL terminator at 0x06F
ABILITIES = 0x070            # six base/current pairs; the sheet draws the 2nd
ABILITY_COUNT = 6
EXCEPTIONAL_STRENGTH = 0x07C  # one more pair, same shape
#: One byte, not a word: the ramp put 128 at 0x080 and 129 at 0x081 and the
#: sheet said `129`, where a big-endian word would have said 32897. Every one
#: of the twelve real records has 0x080 zero, so where a Pools of Darkness
#: character above 255 hit points keeps them is still UNKNOWN.
HP_MAX = 0x081
MOVEMENT = 0x088
CLASS_LEVELS = 0x09D         # six bytes, one per class slot
CLASS_LEVEL_COUNT = 6
DAMAGE_DICE = 0x0AD          # count, sides, bonus -- stride 2, see below
DAMAGE_STRIDE = 2
ARMOUR_CLASS = 0x0B3         # stored as 60 - AC
EXPERIENCE = 0x044           # u32
PLATINUM = 0x04C             # u16 each, in this order
GEMS = 0x04E
JEWELRY = 0x050
AGE = 0x052                  # u16

#: Damage and armour class sit on *odd* offsets two apart, which is the same
#: base/current pair shape the abilities use at 0x070: the sheet draws the
#: second byte of each pair. So the damage triple is three pairs at 0x0AC and
#: armour class is a pair at 0x0B2.
PAIR_CURRENT = 1

#: Ramping 0x0B6-0x0C7 makes the loader reject the file with
#: `ERROR: INVALID ITEM (-1/29)`, so the carried-item region begins there.
#: Its encoding is UNKNOWN and a writer cannot be built without it.
ITEMS = 0x0B6

#: Sex, alignment, class and status are indices into the game's string table --
#: a ramp makes the sheet print unrelated game text where they belong. Both
#: probes that covered 0x054-0x05F printed the *same* wrong strings for these
#: four, so all four are in that span; race printed a *different* string in the
#: two runs, so its byte is below 0x054. Exact offsets UNKNOWN.
ENUM_REGION = (0x054, 0x060)
RACE_REGION = (0x030, 0x054)

#: Every window from 0x030 to 0x0B5 left THAC0 reading 4, so it is either
#: derived from class and level or lives in a region not yet probed
#: (0x000-0x02F, or past 0x0C8). Current hit points and encumbrance are in the
#: same position.
UNLOCATED = ("thac0", "hit_points_current", "encumbrance")

#: Which of the fields below a probe has actually put on screen. A field is
#: only here because a number the sheet drew equalled the offset.
CONFIDENCE = {
    "name": "CONFIRMED",
    "abilities": "CONFIRMED",
    "exceptional_strength": "PROBABLE",   # shape only; never varied on screen
    "hit_points_max": "CONFIRMED",
    "movement": "CONFIRMED",
    "class_levels": "CONFIRMED",
    "damage": "CONFIRMED",
    "armour_class": "CONFIRMED",
    "experience": "CONFIRMED",
    "platinum": "CONFIRMED",
    "gems": "CONFIRMED",
    "jewelry": "CONFIRMED",
    "age": "CONFIRMED",
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
    def movement(self) -> int:
        return self.raw[MOVEMENT]

    @property
    def class_levels(self) -> list[int]:
        return list(self.raw[CLASS_LEVELS:CLASS_LEVELS + CLASS_LEVEL_COUNT])

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
