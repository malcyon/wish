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

**This title alone.** `#470 (Give the project a neutral title beside its
neutral character record, with one port per platform a title shipped on)`'s
stage 10 split `goldbox/amiga_codec.py` by title; Pool of Radiance is in
`goldbox/amiga_por.py`, Curse and Silver Blades in `goldbox/amiga_later.py`,
and what more than one of them needs is in `goldbox/amiga_shared.py`.  Nothing
here imports any of the other three titles' modules at all.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import dos_port, neutral, titles
from .amiga_shared import ABILITY_KEYS, SAVE_KEYS, THIEF_KEYS, _name, u16, u32
from .layout import Confidence
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

#: The head of the running-effect chain, a longword. In memory it is a heap
#: pointer -- BOHLO BART AB's file holds `0x24B946` here and its three ten-byte
#: nodes hold `0x24B950`, `0x24B95A` and 0 at their own `next` -- and the
#: loader only tests it, so a `.pc` may carry anything non-zero for "there are
#: effects".
EFFECT_CHAIN = 0x004
#: The head of the item chain in memory, and **the item count in a file**:
#: `404 + 20 * this + 10 * effects` accounts for every byte of every one of the
#: nineteen `.pc` files on the Amiga disks, with no remainder. The stale cached
#: count is :data:`ITEM_COUNT_CACHE`.
ITEM_CHAIN = 0x008
EXPERIENCE = 0x044           # u32
#: Experience's own high-water mark, and the first of three fields Pools of
#: Darkness has that no earlier title does. `0x015FA4` raises it whenever
#: experience rises -- `move.l $48(a2), d0; cmp.l $44(a2), d0; bgt;
#: move.l $44(a2), $48(a2)` -- and `0x03315E` puts it back into experience,
#: which is the restoration a level drain needs. CONFIRMED from the code; the
#: matching run in the DOS record is `gap_176`. Not a neutral field.
EXPERIENCE_HIGHEST = 0x048   # u32
PLATINUM = 0x04C             # u16 each, in this order
GEMS = 0x04E
JEWELRY = 0x050
AGE = 0x052                  # u16
#: The base experience a creature grants when it is killed, zero for every
#: player character on every port (#254). A word, as DOS's is.
EXPERIENCE_AWARD = 0x054     # u16
ENCUMBRANCE = 0x056          # u16, and see DERIVED: the game recomputes it
RACE = 0x058
CLASS = 0x059
#: The row of the turning matrix, which is a property of what is *being*
#: turned rather than of the cleric. `goldbox.dos.to_neutral` deliberately
#: reads nothing from DOS's own copy (#297) and neither does this module.
TURN_CLASS = 0x05A
#: `field_83_87`'s third byte. The first, at 0x093, is the NPC control byte.
FIELD_83_87_THIRD = 0x05B
SEX = 0x05C
ALIGNMENT = 0x05D
#: The combat block, and **Pools of Darkness splits it in two**, which is why
#: no probe ever separated it from fill: DOS and the two earlier Amiga titles
#: keep `status, active, side, quickfight` as four adjacent bytes, and this
#: title puts two of them here and two at 0x184-0x185.
#:
#: CONFIRMED. The Silver Blades importer at `0x0261BA` copies that title's
#: four bytes into exactly these four addresses, and `status` is corroborated
#: twice over: `tools/amigaenum.py sites` finds `0x05E` indexed into a
#: nine-entry string table at `0x019250` and `0x020A2E`, in the routine that
#: turns 0x058 into a race name and 0x059 into a class name, and the table
#: reads Okay, Animated, tempgone, Running, Unconscious, Dying, Dead,
#: Petrified, Gone -- DOS's own nine, in DOS's own order. `HOSTILE` is
#: compared *between two records* (`move.b $5f(a0), d0; cmp.b $5f(a2), d0`),
#: which is a side test and nothing else.
STATUS = 0x05E
HOSTILE = 0x05F
NAME = 0x060
NAME_LENGTH = 15             # 15 characters, NUL terminator at 0x06F
ABILITIES = 0x070            # six base/current pairs; the sheet draws the 2nd
ABILITY_COUNT = 6
EXCEPTIONAL_STRENGTH = 0x07C  # one more pair, same shape
#: Silver Blades' `gap_069`, the byte before `thac0_base` in DOS's own order.
#: The importer copies it and nothing else names it. UNKNOWN.
UNNAMED_07E = 0x07E
#: The class-and-level THAC0 before anything carried, stored `60 - value`,
#: and the game recomputes it on load -- see :data:`DERIVED`. The twelve pairs
#: of a `.pc` and a DOS record of the same class and level agree on it 12 of
#: 12: 44 for a magic-user 14, 48 for a cleric 14, 50 for a paladin 12, 52 for
#: a ranger 13.
THAC0_BASE = 0x07F
#: A paladin's remaining cure-disease uses. 1 for JORILD and TURBO K, the
#: corpus's two paladins, and 0 for the other seventeen -- which is DOS, where
#: `paladin_cures` is 1 for Guy de Valois and DEMELTINA and 0 for the rest.
PALADIN_CURES = 0x080
#: One byte, not a word: the ramp put 128 at 0x080 and 129 at 0x081 and the
#: sheet said `129`, where a big-endian word would have said 32897.
#: **0x080 is not the high half of it**: it is `paladin_cures`, which is what
#: the two records with 0x080 set are -- both paladins.
HP_MAX = 0x081
#: 1 in 19 of 19 here and in 12 of 12 DOS records. Whether a combat icon is
#: one cell or four.
ICON_DIMENSION = 0x082
MOVEMENT = 0x088
#: The level a dual-classed human left his old class at. The dual-class
#: routine writes `move.b $89(a2), $8a(a2)` at `0x03CD0A` -- former level
#: takes the current one -- and then sets level to 1.
FORMER_LEVEL = 0x08A
CLASS_LEVELS = 0x09D         # seven bytes, one per class slot
CLASS_LEVEL_COUNT = 7
#: Bit 7 says the engine drives this character and the low seven bits are a
#: companion's morale, stored halved (#303). `field_83_87`'s first byte, which
#: is where Silver Blades and Pools of Darkness keep it. Zero in 19 of 19, so
#: every specimen is a character a player made.
NPC_CONTROL = 0x093
FIELD_83_87_SECOND = 0x094
FIELD_83_87_FOURTH = 0x095
#: The class levels' own high-water marks, the second of the three fields
#: this title has and no earlier one does. `0x015F6C` walks the seven slots
#: and raises `0x096[i]` to `0x09D[i]` whenever the current level is higher.
CLASS_LEVELS_HIGHEST = 0x096
#: The class a dual-classed character trained out of, one byte a class slot.
#: `0x03CD06` writes the old level into `0x0A4 + old class` on its way past.
FORMER_CLASS_LEVELS = 0x0A4
#: The eight attack-form bytes, which DOS keeps at its own `attack_forms`: two
#: attack counts, two dice counts, two die sizes, two damage bonuses. The
#: importer copies all eight, one `move.b` each. `ATTACKS_PER_ROUND_HALVES` is
#: byte 0 of it and the damage triple is bytes 2, 4 and 6.
ATTACK_FORMS = 0x0AB
ATTACK_FORM_COUNT = 8
DAMAGE_DICE = 0x0AD          # count, sides, bonus -- stride 2, see below
DAMAGE_STRIDE = 2
ARMOUR_CLASS = 0x0B3         # stored as 60 - AC
#: The strength bonus, and the identity draw used to tell two characters of
#: the same name apart. Both zero in 19 of 19.
STRENGTH_BONUS = 0x0B4
UNNAMED_0AB = 0x0B5
#: Hit points' high-water mark, the third of the level-drain trio: `0x015FB4`
#: raises it to `HP_MAX` whenever the maximum rises.
HP_MAX_HIGHEST = 0x0B6
#: Hit points as rolled, before the constitution bonus. The arithmetic in the
#: corpus is the AD&D table exactly: `hp_max - 0x0B8` is 22 for each
#: magic-user 14 (eleven hit dice at +2), 18 for each cleric 14 (nine at +2),
#: 40 for each ranger 13 (ten at +4), 36 for the paladin 12 and the fighter 14
#: (nine at +4), 20 for the thief 16 (ten at +2) and 15 for HOPE, a fighter 5
#: whose constitution is 17 rather than 18 (five at +3).
HP_ROLLED = 0x0B8
#: The sheet portrait, which this title draws on neither port -- zero in 19 of
#: 19, and `goldbox.dos_port.POOLS_OF_DARKNESS` gives the pair width zero
#: (#451). The bytes are here because Silver Blades has them and the importer
#: copies them; nothing reads them back.
PORTRAIT_HEAD = 0x0B9
#: The combat icon, which is a different thing: `CHEAD.TLB` and `CBODY.TLB`
#: art, a figure slot and the character's size.
ICON_HEAD = 0x0BB
ICON_BODY = 0x0BC
#: Which of eight loaded combat pictures the character draws with (#305). The
#: code compares it against 7 and 8 and writes 0xFF for none.
COMBAT_FIGURE = 0x0BD
#: 1 small, 2 medium -- DOS's own encoding, one greater than the neutral
#: `size_small`. 1 for BOHLO BART AB, the corpus's one dwarf, and 2 for the
#: eighteen humans, elves and half-elves.
SIZE = 0x0BE
ICON_COLOURS = 0x0BF
ICON_COLOUR_COUNT = 6
#: `02 02` in 19 of 19, as DOS's `unnamed_1a4` is in 12 of 12.
UNNAMED_1A4 = 0x0C5
#: A cached item count the save leaves stale: 3 in 17 of 19 against an item
#: region that holds four, five or six. **The count the loader uses is the
#: longword at 0x008**, which `404 + 20 * count + 10 * effects` consumes
#: exactly in 19 of 19.
ITEM_COUNT_CACHE = 0x0C7
#: How many hands the readied weapon takes. 2 in 18 of 19, as DOS's is in 12
#: of 12; the one exception is `?T`, the corpus's thief.
HANDS_USED = 0x0C8
UNNAMED_0C9 = 0x0C9
UNNAMED_0CA = 0x0CA
#: Written from a routine's return value in eight places, one of them
#: immediately after the engine prints `SCROLLS DROPPED!`, so it is a cached
#: count of something rather than a level. UNKNOWN.
UNNAMED_0CB = 0x0CB
#: Memorised spell ids, 141 bytes -- the same width DOS Pools of Darkness
#: gives `spells_memorised`, and the run ends exactly where the spellbook
#: begins. CONFIRMED from the dual-class routine, which clears this region and
#: the spell slots together: `move.w #$8d, -(a7); lea.l $cc(a2), a0` at
#: `0x03CD56` and again at `0x03CE00`, either side of `memset($169, 0, 0x1B)`.
#: Zero in 19 of 19 specimens, which is what nothing-memorised looks like and
#: is why no specimen could have found it.
SPELLS_MEMORISED = 0x0CC
SPELLS_MEMORISED_LENGTH = 141
#: The spellbook, as a bitmask rather than DOS's byte per spell: bit `i` of
#: byte `i >> 3` is DOS array index `i`, which is spell id `i + 1`. Sixteen
#: bytes for 125 ids, bounded above by the cleric's slot array at 0x169.
#:
#: CONFIRMED twice. The importer plants Silver Blades' fifteen packed bytes
#: here (`lea.l $159(a2), a0` at `0x02622C`), and nine of the ten `.pc` files
#: with a DOS record of the same class and levels agree with it id for id --
#: 48 ids for a magic-user 14, 27 for a ranger 13, 15 for a paladin 12. The
#: tenth is the three cleric 14s, which carry the same seventeen extra ids
#: as each other (8-20 and 76-79, the magic-user's and the druid's level-1
#: groups); that is a fact about those three characters and not about the
#: encoding, and it is UNKNOWN.
SPELLBOOK = 0x159
SPELLBOOK_BYTES = 16
#: Spell slots free per level: cleric, druid, magic-user, nine bytes each.
#: The importer's own loop is the proof of the stride -- `muls.w #$9` against
#: `addi.l #$169` for the destination and `muls.w #$7` against `addi.l #$ce`
#: for Silver Blades' source, with `min(d2, 2)` mapping the source index --
#: and Silver Blades' fourth array, the one no shipped character sets a byte
#: of, is skipped by a `cmpi.w #$2, d2; beq`. The ten DOS peers agree on all
#: 27 bytes.
SPELLS_CASTABLE = 0x169
SPELL_SLOT_LEVELS = 9
SPELL_SLOT_CLASSES = ("cleric", "druid", "magic-user")
#: The other half of the combat block -- see :data:`STATUS`. 1 and 0 in 19 of
#: 19, which is DOS's `00 01 00 00` default rearranged, and `0x184` carries 63
#: `tst.b` sites in the code, which is what an in-party flag looks like.
ACTIVE = 0x184
QUICKFIGHT = 0x185
#: The derived combat tail, thirteen bytes the importer copies one for one off
#: Silver Blades' own `thac0_current, armour_class, roster_tail(9),
#: hp_current, movement_current`.
THAC0_CURRENT = 0x186
ARMOUR_CLASS_CURRENT = 0x187
ROSTER_TAIL = 0x188
ROSTER_TAIL_LENGTH = 9
#: **One byte, not the big-endian word at 0x190.** The importer copies Silver
#: Blades' one-byte `hp_current` here, and 0x190 is `roster_tail`'s last byte.
#: The word reading gave the same answer on every record anybody had, because
#: 0x190 is zero in 19 of 19 and in every payload a probe wrote; it is 0x191
#: that equals `HP_MAX` in 19 of 19.
HP_CURRENT = 0x191
MOVEMENT_CURRENT = 0x192

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
ATTACKS_PER_ROUND_HALVES = ATTACK_FORMS
CLASS_BITS = 0x0B7
#: **This said 0x0B8 until #462, and 0x0B8 is `hp_rolled`** -- see
#: :data:`HP_ROLLED`. The portrait pair is 0x0B9-0x0BA, which the Silver
#: Blades importer fills from that title's own `portrait_head` and
#: `portrait_body` and which nothing in this title ever reads back.
PORTRAIT_BODY = PORTRAIT_HEAD + 1

#: The game recomputes these on load and ignores what the file holds, so the
#: writer must not fill them in: 0x056 encumbrance (it is the coin count),
#: 0x186 `60 - THAC0` (it is the best of the class levels), 0x187 armour
#: class, 0x18B/0x18D/0x18F damage, 0x192 movement.
DERIVED = (ENCUMBRANCE, THAC0_CURRENT, ARMOUR_CLASS_CURRENT,
           0x18B, 0x18D, 0x18F, MOVEMENT_CURRENT)

#: Ramping 0x0B6-0x0C7 makes the loader reject the file with
#: `ERROR: INVALID ITEM (-1/29)`. That is the GLIB library reader's own
#: message -- `Invalid item (%d/%d)` lives in the `LBI` code beside
#: `LBIBase: Invalid Library File` -- and `Disk3_CHEAD.TLB` holds exactly 29
#: items. So the two numbers are a library item index and the library's item
#: count: PoD asked `CHEAD.TLB` for item -1.
#:
#: **`CHEAD.TLB` is the combat icon's head, not a sheet portrait** -- this
#: note called it "the portrait heads" until #451, and Pools of Darkness has
#: no sheet portrait on either port (#194).
#:
#: **Which byte is which is measured now** (#462), off the engine's own Silver
#: Blades importer: 0x0B6 highest hit points, 0x0B7 class bits, 0x0B8 hit
#: points rolled, 0x0B9-0x0BA the sheet portrait this title never draws,
#: 0x0BB the icon head, 0x0BC the icon body, 0x0BD the combat figure, 0x0BE
#: the size, 0x0BF-0x0C4 the six icon colours, 0x0C5-0x0C6 DOS's own
#: `unnamed_1a4` and 0x0C7 the stale item count. Zero in all of it is still
#: accepted: every payload here has zeros from 0x0B9 up and joins the party.
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
    # **CONFIRMED because the engine's own Silver Blades importer writes it
    # there** (#462), which is proof from the shipped code rather than from a
    # probe: no payload has ever drawn a status other than OKAY, and the
    # sheet's status line indexes a nine-entry table with this byte.
    "status": "CONFIRMED",
    "level": "PROBABLE",
    "saving_throws": "PROBABLE",
    "thief_skills": "PROBABLE",
    "class_bits": "PROBABLE",
    "thac0": "DERIVED",
    "encumbrance": "DERIVED",
    # The rest of what #462 decoded.  Every one of these is the engine's own
    # importer naming the byte, so the *field* is CONFIRMED; whether the game
    # keeps what a writer puts there is :data:`DERIVED`'s question and a
    # different one.
    "thac0_base": "CONFIRMED",
    "thac0_current": "CONFIRMED",
    "hp_rolled": "CONFIRMED",
    "movement_current": "CONFIRMED",
    "encumbrance_stored": "CONFIRMED",
    "combat_figure": "CONFIRMED",
    "hostile": "CONFIRMED",
    "quickfight": "CONFIRMED",
    "unnamed_0ab": "CONFIRMED",
    "experience_award": "CONFIRMED",
    "portrait": "CONFIRMED",
    "attack_forms": "CONFIRMED",
    "roster_tail": "CONFIRMED",
}


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
        return self.raw[HP_CURRENT]

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

    # -- what #462 decoded, off the engine's own Silver Blades importer -----

    @property
    def abilities_permanent(self) -> list[int]:
        """The first byte of each ability pair -- the permanent score.

        `goldbox.dos._ability_pair` read the asymmetry out of the shipped
        overlay for `#401`: byte 0 of an ability pair is the permanent score
        and byte 1 is the one in force, and exceptional strength is the other
        way round.  The importer copies both halves of both shapes across, so
        the Amiga's pairs are DOS's pairs and the same rule applies.
        """
        return [self.raw[ABILITIES + 2 * i] for i in range(ABILITY_COUNT)]

    @property
    def exceptional_strength_permanent(self) -> int:
        return self.raw[EXCEPTIONAL_STRENGTH + 1]

    @property
    def thac0_base(self) -> int:
        """Stored `60 - value`, the family's encoding."""
        return self.raw[THAC0_BASE]

    @property
    def thac0_current(self) -> int:
        return self.raw[THAC0_CURRENT]

    @property
    def hit_points_rolled(self) -> int:
        return self.raw[HP_ROLLED]

    @property
    def former_level(self) -> int:
        return self.raw[FORMER_LEVEL]

    @property
    def former_class_levels(self) -> list[int]:
        return list(self.raw[FORMER_CLASS_LEVELS:
                             FORMER_CLASS_LEVELS + CLASS_LEVEL_COUNT])

    @property
    def attack_forms(self) -> bytes:
        return self.raw[ATTACK_FORMS:ATTACK_FORMS + ATTACK_FORM_COUNT]

    @property
    def roster_tail(self) -> bytes:
        return self.raw[ROSTER_TAIL:ROSTER_TAIL + ROSTER_TAIL_LENGTH]

    @property
    def status(self) -> int:
        return self.raw[STATUS]

    @property
    def active(self) -> bool:
        return bool(self.raw[ACTIVE])

    @property
    def hostile(self) -> bool:
        return bool(self.raw[HOSTILE])

    @property
    def quickfight(self) -> bool:
        return bool(self.raw[QUICKFIGHT])

    @property
    def npc_control_byte(self) -> int:
        return self.raw[NPC_CONTROL]

    @property
    def combat_figure(self) -> int:
        return self.raw[COMBAT_FIGURE]

    @property
    def size(self) -> int:
        """1 small, 2 medium -- DOS's own encoding, not the neutral one."""
        return self.raw[SIZE]

    @property
    def encumbrance(self) -> int:
        return u16(self.raw, ENCUMBRANCE)

    @property
    def experience_award(self) -> int:
        return u16(self.raw, EXPERIENCE_AWARD)

    @property
    def identity(self) -> int:
        return self.raw[UNNAMED_0AB]

    @property
    def movement_current(self) -> int:
        return self.raw[MOVEMENT_CURRENT]

    @property
    def spells_known(self) -> list[int]:
        """Spell ids the sixteen-byte mask at 0x159 has set, ascending.

        Bit `i` of byte `i >> 3` is DOS array index `i`, which is spell id
        `i + 1` -- the same numbering `goldbox.dos.DosCharacter.spells_known`
        hands back, so the two ports' lists compare directly.
        """
        mask = self.raw[SPELLBOOK:SPELLBOOK + SPELLBOOK_BYTES]
        return [byte * 8 + bit + 1
                for byte in range(len(mask)) for bit in range(8)
                if mask[byte] >> bit & 1]

    @property
    def spells_memorised(self) -> list[int]:
        """Memorised spell ids, highest first -- the neutral order.

        Pools of Darkness fills the region from its end backwards, which is
        what DOS does with its own 141 bytes, so reversing is the transpose
        and the zeroes fall out.  **No specimen has a spell in it**: all
        nineteen `.pc` files on the Amiga disks are zero here, so the *order*
        is DOS's rather than something this port has been watched doing.
        """
        raw = self.raw[SPELLS_MEMORISED:
                       SPELLS_MEMORISED + SPELLS_MEMORISED_LENGTH]
        return [b for b in reversed(raw) if b]

    @property
    def spells_castable(self) -> dict[str, tuple[int, ...]]:
        """Class name -> slots free per spell level, ascending."""
        return {
            name: tuple(self.raw[SPELLS_CASTABLE + SPELL_SLOT_LEVELS * i:
                                 SPELLS_CASTABLE + SPELL_SLOT_LEVELS * (i + 1)])
            for i, name in enumerate(SPELL_SLOT_CLASSES)}


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
            (HP_CURRENT, 1, "hit_points_current"),
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
        out[HP_CURRENT] = min(current, 0xFF)
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
#: title (`goldbox/c64_port.py`), which is exactly why the conversion goes by name
#: and not by number: the neutral `race` is an index into the *source title's*
#: table and `goldbox.titles.race_table` is what turns it into a name.
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

#: What an unarmoured, unarmed character is, and what all twelve genuine
#: records hold: armour class 10 and 1d2. **Not** converted from the source. A
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
POD_WRITE_DIRECT: tuple[tuple[str, str], ...] = (
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
POD_WRITE_TRANSFORMED: tuple[tuple[str, str], ...] = (
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
    ("hp_current", "copied to the byte at 0x191, capped at the maximum the "
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
#: and :func:`pod_write_field_disposition` states the whole contract whether
#: or not any
#: one character happens to carry it.
#:
#: **Most of these said "no located home" until #462 and had one all along.**
#: The record is decoded now -- `tools/podimportmap.py` reads the engine's own
#: Silver Blades importer and every offset is named -- so what is left is a
#: writer that has not been extended to fill them, which is a different and
#: smaller thing than a decode that has not happened. Each row below says
#: which it is, and #475 is the ticket for the writer.
POD_WRITE_DROPPED: tuple[tuple[str, str], ...] = (
    ("abilities_second", "the *first* byte of each ability pair at 0x070 "
                         "(#462), which the reader takes; the writer puts the "
                         "one score it is given in both halves of the pair, "
                         "so nothing here differs from what it writes"),
    ("former_levels", "the seven bytes at 0x0A4 (#462), which the writer does "
                      "not fill yet. `to_pc` reports each class left behind "
                      "by name instead"),
    ("copper", "Pools of Darkness keeps platinum, gems and jewelry and no "
               "other coin, on both of its ports, so a source of this title "
               "has none to give"),
    ("silver", "see `copper`: this title has three money slots"),
    ("electrum", "see `copper`: this title has three money slots"),
    ("gold", "see `copper`: this title has three money slots"),
    ("infravision", "a C64 field; neither this title's `.pc` nor its DOS "
                    "record has one, and PoD takes what it needs from race"),
    ("hp_rolled", "the byte at 0x0B8 (#462), which the writer does not fill "
                  "yet -- this row said the Amiga kept only the maximum, and "
                  "the record keeps the pre-constitution roll as well"),
    ("hp_lost_to_drain", "this title counts level drain the other way round, "
                         "keeping the highest levels reached at 0x096, the "
                         "highest experience at 0x048 and the highest hit "
                         "points at 0x0B6 (#462). Its DOS record has no "
                         "drained-level pair either, so a source of this "
                         "title has nothing to give"),
    ("levels_drained", "see `hp_lost_to_drain`: the high-water marks are what "
                       "this title stores instead"),
    # #451 (The Amiga Pools of Darkness notes call the combat icon a sheet
    # portrait, and describe a menu the title has not got).  These two rows
    # used to say PoD's portrait art is `CHEAD.TLB` with a numbering of its
    # own, and both halves were wrong: `CHEAD.TLB`/`CBODY.TLB` are the
    # **combat icon** (`docs/199-amiga-combat-icons.md`), and the title has
    # no sheet portrait at all.  CONFIRMED three ways (#194): neither port
    # ships head or body art -- 52 DOS files and 55 Amiga ones with no
    # `HEAD*`/`BODY*` among them; `goldbox.dos_port.POOLS_OF_DARKNESS`
    # gives the pair a width of zero; and the fourteen-and-twelve creation
    # menu is cut out of the Amiga engine's own copy of the data block that
    # carries it, in 60 bytes otherwise byte-identical across four binaries.
    #
    # The rows stay, because `pod_write_field_disposition` is the whole
    # contract and a
    # neutral field this writer takes nothing from has to be named whether or
    # not a Pools of Darkness source could hold one.  What changed is what
    # they say.
    ("portrait_head", "Pools of Darkness has no character-sheet portrait on "
                      "either of its ports -- neither ships the art and its "
                      "own DOS record has no such field -- so a source of "
                      "this title never holds one"),
    ("portrait_body", "see `portrait_head`: the title draws no sheet face"),
    ("inventory", "the item region past 404 bytes is decoded -- twenty bytes "
                  "a record, the later Amiga titles' own item node (#462) -- "
                  "and the writer does not build one yet. The character "
                  "arrives carrying nothing"),
    ("innate_effects", "the effect chain past the item region is decoded, ten "
                       "bytes a node (#462), and the writer does not build "
                       "one yet"),
    ("granted_effects", "see `innate_effects`. Which node is innate and which "
                        "a readied item granted cannot be told apart for this "
                        "title, the same `LATER_EFFECT_SPLIT_UNKNOWN` that "
                        "binds Curse and Silver Blades"),
    ("spells_memorised", "the 141 bytes at 0x0CC (#462), which the writer does "
                         "not fill yet. **The fill direction is not "
                         "confirmed**: DOS fills its own region from the end "
                         "backwards and nothing has watched this port do it, "
                         "so writing one wrong way round would hand a "
                         "character somebody else's spells"),
    ("spells_known", "the sixteen-byte mask at 0x159 (#462), which the writer "
                     "does not fill yet. The ids are the DOS record's own, so "
                     "the conversion is a repack rather than a lookup"),
    ("spells_castable", "the three nine-byte arrays at 0x169, 0x172 and 0x17B "
                        "(#462), which the writer does not fill yet. Slots "
                        "free per level follow from class and level, which "
                        "PoD recomputes on load"),
    ("npc", "bit 7 of the control byte at 0x093 (#462), which the writer does "
            "not fill yet"),
    ("npc_control_byte", "the whole byte at 0x093 -- see `npc`"),
    ("combat_figure", "the byte at 0x0BD (#462), which the writer does not "
                      "fill yet: PoD allocates its own slot of eight on "
                      "import, and a source value out of that range is one "
                      "the engine's own compares at 7 and 8 would not expect"),
    ("encumbrance", "the word at 0x056, which PoD recomputes: a probe that "
                    "set it to 1234 drew 233, which is the character's own "
                    "coins, gems and jewelry"),
    ("size_small", "the byte at 0x0BE (#462), which the writer does not fill "
                   "yet; PoD takes size from race"),
    ("turn_power", "a cleric's turning strength is worked out from the class "
                   "levels when TURN is pressed, on both ports; the record's "
                   "0x05A is DOS's `turn_class`, which is a property of what "
                   "is being turned, and DOS's own reader takes nothing from "
                   "it either (#297)"),
    ("attack_level", "**the one field of the record still unlocated** (#462): "
                     "Silver Blades keeps it at Amiga 0x080 and this title's "
                     "importer does not copy it. PoD reads its attack tables "
                     "at the class level, and DOS Pools of Darkness holds 0 "
                     "in 12 of 12"),
    ("attack_forms", "the eight bytes at 0x0AB (#462), which the writer does "
                     "not fill yet; the 0x0AD damage triple inside it is "
                     "written unarmed instead"),
    ("roster_tail", "the nine bytes at 0x188 (#462): the armour bonus and the "
                    "running attack forms, all of which PoD recomputes"),
    ("thac0_base", "the byte at 0x07F (#462). PoD recomputes THAC0 on load "
                   "from the class levels and ignores what the file holds"),
    ("thac0_current", "the byte at 0x186, recomputed on load -- see "
                      "`thac0_base`"),
    ("armour_class", "the byte at 0x187, recomputed on load; the record gets "
                     "the unarmoured constant at 0x0B3 instead"),
    ("armour_class_base", "recomputed on load -- see `armour_class`"),
    ("movement_current", "the byte at 0x192, recomputed on load: a probe that "
                         "set it to 99 drew the base's 12"),
    ("status", "the byte at 0x05E (#462), which the writer does not fill yet, "
               "so a converted character arrives Okay -- which is what the "
               "zero there means. The sheet's STATUS line indexes a "
               "nine-entry table with this byte and the table is DOS's own "
               "nine in DOS's own order"),
    ("active", "the byte at 0x184 (#462), which the writer does not fill "
               "yet. **19 of 19 records the game wrote hold 1 there and this "
               "writer leaves 0**, which is the flag's out-of-the-party "
               "value on the other two ports"),
    ("hostile", "the byte at 0x05F (#462), which the writer does not fill "
                "yet. A player character is never on the enemy's side, so 0 "
                "is the right value in any case -- see "
                "`docs/169-dos-combat-side.md`"),
    ("quickfight", "the byte at 0x185 (#462), which the writer does not fill "
                   "yet"),
    ("unnamed_0ab", "the identity draw, at 0x0B5 (#462), which the writer "
                    "does not fill yet. Zero in 19 of 19 records the game "
                    "wrote, where DOS holds 0, 47, 85, 138 and 249"),
    # #254: a creature's own field, zero in every player record measured on
    # any port.  `experience_per_hit_point` is narrower: the later engine
    # drops the byte outright, so DOS Pools of Darkness has nowhere for it
    # either (`goldbox/dos_port.py`'s 510-byte shape declares
    # `experience_award` alone) and the `.pc` has nothing to hold.
    ("experience_award", "the word at 0x054 (#462), which the writer does not "
                         "fill yet; it is zero in every player record on "
                         "either port"),
    ("experience_per_hit_point", "Pools of Darkness' own engine keeps no "
                                 "such byte in any of its records; the "
                                 "later engine adds the base award alone"),
)


def pod_write_field_disposition() -> dict[str, str]:
    """Every neutral field and what this writer does with it.

    The test that keeps this module honest: a field `goldbox/neutral.py` declares
    and this table does not name would be a field silently dropped.  The
    shape is `goldbox/neutral.py`'s, so every direction reports the same way.
    """
    return neutral.disposition(POD_WRITE_DIRECT, POD_WRITE_TRANSFORMED,
                               POD_WRITE_DROPPED, "the Amiga's")


# ---------------------------------------------------------------------------
# The other direction: a `.pc` becomes a neutral character (#194)
# ---------------------------------------------------------------------------
#: Neutral fields :func:`pod_to_neutral` takes straight out of the `.pc`,
#: with where each one is.  **The tables the two ports index are the same
#: tables**, which is what makes a copy right rather than a guess:
#:
#: * `RACES` here is `('ELF', 'HALF-ELF', 'DWARF', 'GNOME', 'HALFLING',
#:   'HUMAN')` and `goldbox.dos_port.POOLS_OF_DARKNESS_RACE_NUMBERS` is the
#:   same six names in the same order with `monster` after them, so race 5 is
#:   the human on both ports;
#: * `CLASSES` here is seventeen entries and DOS Pools of Darkness' class
#:   codes land in it: its BINKY reads 14 with fighter and thief levels
#:   (`FIGHTER/THIEF`) and this disk's TRIPEL TURBO reads 15 with fighter,
#:   magic-user and thief levels (`FIGHTER/M-U/THIEF`);
#: * `ALIGNMENTS` is `law * 3 + morality` on both, and every paladin on
#:   either port reads 0.
#:
#: So this is a same-title conversion where the numbering is shared, and
#: nothing here is a lookup between two tables.
POD_READ_DIRECT: tuple[tuple[str, str], ...] = (
    ("race", "race, the .pc's own byte at 0x058"),
    ("char_class", "char_class, the .pc's own byte at 0x059"),
    ("sex", "sex, the .pc's own byte at 0x05C"),
    ("alignment", "alignment, the .pc's own byte at 0x05D"),
    ("age", "age, the .pc's big-endian word at 0x052"),
    ("level", "level, the .pc's byte at 0x089"),
    ("experience", "experience, the .pc's big-endian longword at 0x044"),
    ("platinum", "platinum, the .pc's big-endian word at 0x04C"),
    ("gems", "gems, the .pc's big-endian word at 0x04E"),
    ("jewelry", "jewelry, the .pc's big-endian word at 0x050"),
    ("movement", "movement, the .pc's byte at 0x088"),
    ("hp_max", "hp_max, the .pc's byte at 0x081"),
    ("hp_current", "hp_current, the .pc's byte at 0x191"),
    ("exceptional_strength",
     "exceptional_strength, the current half of the pair at 0x07C"),
    *((k, f"{k}, the current half of its pair at 0x070") for k in ABILITY_KEYS),
    *((k, f"{k}, one of the five saving throws at 0x083") for k in SAVE_KEYS),
    *((k, f"{k}, one of the eight thief skills at 0x08B") for k in THIEF_KEYS),
    # **These were one byte until #462 and are two.** Both used to be read
    # from 0x0B3, because that was the only armour class anybody had located;
    # the Silver Blades importer copies that title's `armour_class_base` to
    # 0x0B3 and its `armour_class` to 0x187, so the pair is separated now and
    # an Amiga character in plate mail no longer converts as unarmoured.
    ("armour_class",
     "armour_class, the .pc's byte at 0x187 in the family's stored "
     "60 - value form -- what the game last computed"),
    ("armour_class_base",
     "armour_class_base, the .pc's byte at 0x0B3, which is the unarmoured "
     "60 - 10 = 50 in 19 of 19 records"),
    ("thac0_base", "thac0_base, the .pc's byte at 0x07F, stored 60 - value"),
    ("thac0_current", "thac0_current, the .pc's byte at 0x186"),
    ("hp_rolled", "hp_rolled, the .pc's byte at 0x0B8"),
    ("movement_current", "movement_current, the .pc's byte at 0x192"),
    ("encumbrance", "encumbrance, the .pc's big-endian word at 0x056"),
    ("attack_forms", "attack_forms, the eight bytes at 0x0AB"),
    ("roster_tail", "roster_tail, the nine bytes at 0x188"),
    ("combat_figure", "combat_figure, the .pc's byte at 0x0BD"),
    ("hostile", "hostile, the .pc's byte at 0x05F"),
    ("quickfight", "quickfight, the .pc's byte at 0x185"),
    ("unnamed_0ab", "unnamed_0ab, the .pc's byte at 0x0B5"),
    ("experience_award", "experience_award, the .pc's word at 0x054"),
    ("portrait_head", "portrait_head, the .pc's byte at 0x0B9 -- zero in 19 "
                      "of 19, since this title draws no sheet face"),
    ("portrait_body", "portrait_body, the .pc's byte at 0x0BA"),
    ("spells_castable", "spells_castable, the three nine-byte arrays at "
                        "0x169, 0x172 and 0x17B"),
)

#: Neutral fields the reader builds by a rule rather than a copy.
POD_READ_TRANSFORMED: tuple[tuple[str, str], ...] = (
    ("name", "the fifteen bytes at 0x060, cut at the first NUL"),
    ("class_bits", "the mask at 0x0B7 with bit 6 reread from the level "
                   "array: this port stores DOS's own byte, where the "
                   "paladin and the ranger share bit 6, and the neutral "
                   "record gives the ranger bit 7"),
    ("levels", "the seven-slot array at 0x09D, named by "
               "`CLASS_LEVEL_SLOTS`, which is the same seven slots in the "
               "same order as this title's DOS record"),
    ("former_levels", "the seven-slot array at 0x0A4, named the same way, "
                      "non-zero entries only"),
    ("abilities_second", "the *first* byte of each ability pair at 0x070, "
                         "which is the permanent score behind the one in "
                         "force -- and byte 1 of the exceptional-strength "
                         "pair, which stores its two the other way round "
                         "(#401)"),
    ("spells_known", "the sixteen-byte mask at 0x159 unpacked to ids: bit i "
                     "of byte i >> 3 is spell id i + 1, the same numbering "
                     "the DOS record's byte-per-spell array has"),
    ("spells_memorised", "the 141 bytes at 0x0CC reversed into the neutral "
                         "highest-first order, zeroes dropped"),
    ("status", "the byte at 0x05E turned into one of the game's own nine "
               "status words, which are DOS's nine in DOS's order"),
    ("active", "the byte at 0x184, which is 1 for a character in the party"),
    ("npc", "bit 7 of the control byte at 0x093"),
    ("npc_control_byte", "the whole control byte at 0x093, when bit 7 is set"),
    ("size_small", "the byte at 0x0BE less one: this port stores DOS's 1 "
                   "small / 2 medium and the neutral record keeps 0 small / "
                   "1 large"),
)


#: Neutral fields the `.pc` reader takes nothing from, and why.
#:
#: **This was computed from the writer's :data:`POD_WRITE_DROPPED` until #462**, on the
#: reasoning that a home nobody has found is missing in both directions.  That
#: stopped being true the day the record was decoded: reading a byte is free
#: and writing one into a field the loader acts on is a change that has to be
#: watched in the running game first, so the two lists now say different
#: things and each says its own.
#:
#: What is left is three kinds of row, and none of them is a decode that has
#: not happened:
#:
#: * **this title has no such field, on either port.**  Pools of Darkness
#:   keeps three money slots rather than seven, replaces `levels_drained` and
#:   `hp_lost_to_drain` with high-water marks of the levels, the experience
#:   and the hit points (0x096, 0x048, 0x0B6), and drops
#:   `experience_per_hit_point` outright.  `infravision` is a C64 field and
#:   `goldbox.dos_port.POOLS_OF_DARKNESS` declares none either.  A
#:   same-title conversion can never be handed one of these, so there is
#:   nothing to lose;
#: * **neither port stores it.**  `turn_power` is the cleric's own turning
#:   strength, which both engines work out from the class levels when the
#:   command is pressed; `goldbox.dos.to_neutral` deliberately reads nothing
#:   from DOS's `turn_class` for the same reason (#297), and this record's own
#:   copy is at 0x05A;
#: * **one field is genuinely still unlocated**, and it is `attack_level`.
POD_READ_DROPPED: tuple[tuple[str, str], ...] = (
    ("copper", "Pools of Darkness keeps platinum, gems and jewelry and no "
               "other coin, on both of its ports, so no character of this "
               "title has any of the lighter coins to convert"),
    ("silver", "see `copper`: this title has three money slots"),
    ("electrum", "see `copper`: this title has three money slots"),
    ("gold", "see `copper`: this title has three money slots"),
    ("levels_drained", "this title counts level drain the other way round: "
                       "it keeps the *highest* levels reached at 0x096, the "
                       "highest experience at 0x048 and the highest hit "
                       "points at 0x0B6, and restores from those. Its DOS "
                       "record has no drained-level pair either"),
    ("hp_lost_to_drain", "see `levels_drained`: the high-water marks are "
                         "what this title stores instead"),
    ("experience_per_hit_point", "the later engine keeps no such byte in any "
                                 "of its records, on either port"),
    ("infravision", "a C64 field; neither this title's `.pc` nor its DOS "
                    "record has one, and the game takes what it needs from "
                    "race"),
    ("turn_power", "a cleric's turning strength is worked out from the class "
                   "levels when TURN is pressed, on both ports. The record's "
                   "0x05A is DOS's `turn_class`, which is a property of what "
                   "is being turned, and DOS's own reader takes nothing from "
                   "it either (#297)"),
    ("attack_level", "**the one field still unlocated** (#462). Silver "
                     "Blades keeps it at Amiga 0x080 and this title's "
                     "importer does not copy it; 0x080 is `paladin_cures` "
                     "here and 0x082 is `icon_dimension`, so it is not "
                     "merely displaced. DOS Pools of Darkness holds 0 in 12 "
                     "of 12, so nothing observable is lost"),
    ("inventory", "the item region past 404 bytes is decoded and this reader "
                  "does not read it yet -- `tools/podpcregions.py` does. A "
                  "converted character still arrives carrying nothing"),
    ("innate_effects", "the effect chain past the item region is decoded and "
                       "this reader does not read it yet -- see `inventory`"),
    ("granted_effects", "see `innate_effects`. Which node is innate and which "
                        "was granted by a readied item cannot be told apart "
                        "for this title, the same `LATER_EFFECT_SPLIT_UNKNOWN` "
                        "that binds Curse and Silver Blades"),
)


def pod_read_dropped() -> tuple[tuple[str, str], ...]:
    """:data:`POD_READ_DROPPED`, as a function so callers need not change."""
    return POD_READ_DROPPED


def pod_field_disposition() -> dict[str, str]:
    """Every neutral field and what the `.pc` **reader** does with it.

    The mirror of :func:`pod_write_field_disposition`, which is the writer's,
    and the test that keeps this half honest: a field `goldbox/neutral.py` declares
    and this names nowhere would be one dropped in silence.

    **It was a short account of a long record and is not any more.** 38 of
    the 75 neutral fields were filled when this reader was written and 37
    were not; `#462` decoded the rest of the record off the engine's own
    Silver Blades importer, and what is left is thirteen names of which nine
    are fields this *title* has on neither port, three are the item and
    effect regions this reader has not been taught to walk yet, and one --
    `attack_level` -- is the only field in the record still unlocated.
    `docs/124-amiga-port.md` §1 is the map.
    """
    return neutral.disposition(POD_READ_DIRECT, POD_READ_TRANSFORMED,
                               pod_read_dropped(), "the neutral")


def pod_to_neutral(char: PodCharacter | bytes | bytearray) -> NeutralCharacter:
    """One Amiga Pools of Darkness `.pc` in the neutral record.

    The caller `PodCharacter` did not have until 2026-09-08: `goldbox.amiga
    .write` has always turned a neutral character into a `.pc`, and nothing
    turned a `.pc` back into one, so the Amiga end of
    `#194 (Import and export a Pools of Darkness save between DOS and the
    Amiga)` had one direction of two.

    Every value is graded from :data:`CONFIDENCE`, which records **which
    fields a probe actually put on a character sheet** rather than which ones
    decode plausibly -- so a writer asking for a grade it will stand behind
    gets the honest answer.  A field whose home in the record is undecoded is
    named by :func:`pod_read_dropped` and never guessed.

    `char` may be the record's bytes, for a caller that has just read a file
    off an `.adf`.
    """
    # The heavier module, and this is its only caller here.
    from . import dos_codec as _dos

    if not isinstance(char, PodCharacter):
        char = PodCharacter.from_bytes(char)
    out = NeutralCharacter("Amiga", source=getattr(char, "source", ""),
                           game=dos_port.POOLS_OF_DARKNESS.key)

    def grade(name: str) -> Confidence:
        return Confidence[CONFIDENCE.get(name, "PROBABLE")]

    out.set("name", char.name, "the .pc's fifteen bytes at 0x060, cut at the "
            "first NUL", grade("name"), neutral.Provenance.RESHAPED)

    scalars = {
        "race": (char.race, RACE, "race"),
        "char_class": (char.character_class, CLASS, "character_class"),
        "sex": (char.sex, SEX, "sex"),
        "alignment": (char.alignment, ALIGNMENT, "alignment"),
        "age": (char.age, AGE, "age"),
        "level": (char.level, LEVEL, "level"),
        "experience": (char.experience, EXPERIENCE, "experience"),
        "platinum": (char.platinum, PLATINUM, "platinum"),
        "gems": (char.gems, GEMS, "gems"),
        "jewelry": (char.jewelry, JEWELRY, "jewelry"),
        "movement": (char.movement, MOVEMENT, "movement"),
        "hp_max": (char.hit_points_max, HP_MAX, "hit_points_max"),
        "hp_current": (char.hit_points_current, HP_CURRENT,
                       "hit_points_current"),
        "exceptional_strength": (char.exceptional_strength,
                                 EXCEPTIONAL_STRENGTH,
                                 "exceptional_strength"),
        # -- what #462 decoded, off the engine's own Silver Blades importer -
        "thac0_base": (char.thac0_base, THAC0_BASE, "thac0_base"),
        "thac0_current": (char.thac0_current, THAC0_CURRENT,
                          "thac0_current"),
        "hp_rolled": (char.hit_points_rolled, HP_ROLLED, "hp_rolled"),
        "movement_current": (char.movement_current, MOVEMENT_CURRENT,
                             "movement_current"),
        "encumbrance": (char.encumbrance, ENCUMBRANCE,
                        "encumbrance_stored"),
        "combat_figure": (char.combat_figure, COMBAT_FIGURE, "combat_figure"),
        "hostile": (char.hostile, HOSTILE, "hostile"),
        "quickfight": (char.quickfight, QUICKFIGHT, "quickfight"),
        "unnamed_0ab": (char.identity, UNNAMED_0AB, "unnamed_0ab"),
        "experience_award": (char.experience_award, EXPERIENCE_AWARD,
                             "experience_award"),
        "portrait_head": (char.raw[PORTRAIT_HEAD], PORTRAIT_HEAD,
                          "portrait"),
        "portrait_body": (char.raw[PORTRAIT_BODY], PORTRAIT_BODY, "portrait"),
        "attack_forms": (char.attack_forms, ATTACK_FORMS, "attack_forms"),
        "roster_tail": (char.roster_tail, ROSTER_TAIL, "roster_tail"),
    }
    for name, (value, offset, key) in scalars.items():
        out.set(name, value, f"Amiga .pc {name} @{offset:#05x} "
                             f"({CONFIDENCE.get(key, 'PROBABLE')})",
                grade(key))

    for key, value in zip(ABILITY_KEYS, char.abilities):
        out.set(key, value,
                f"Amiga .pc abilities @{ABILITIES:#05x}, the second byte of "
                f"this ability's pair -- the one the sheet draws",
                grade("abilities"))
    for key, value in zip(SAVE_KEYS, char.saving_throws):
        out.set(key, value, f"Amiga .pc saving throws @{SAVING_THROWS:#05x}",
                grade("saving_throws"))
    for key, value in zip(THIEF_KEYS, char.thief_skills):
        out.set(key, value, f"Amiga .pc thief skills @{THIEF_SKILLS:#05x}",
                grade("thief_skills"))

    levels = {name.lower(): level
              for name, level in zip(CLASS_LEVEL_SLOTS, char.class_levels)}
    out.set("levels", levels,
            f"Amiga .pc class levels @{CLASS_LEVELS:#05x}, named by the "
            f"seven slots this title's DOS record keeps in the same order",
            grade("class_levels"), neutral.Provenance.RESHAPED)

    # The ranger and the paladin share bit 6 in this byte, exactly as they do
    # in the DOS record -- the two ports store the same mask -- so the same
    # disambiguation applies, out of the level array (#292 for the later
    # titles, and `goldbox.dos.neutral_class_bits_from` is where it lives).
    out.set("class_bits",
            _dos.neutral_class_bits_from(char.class_bits, char.class_levels),
            f"Amiga .pc class mask @{CLASS_BITS:#05x}, with bit 6 reread "
            f"from the level array because this port gives the paladin and "
            f"the ranger one bit between them",
            grade("class_bits"), neutral.Provenance.RESHAPED)

    # **The stored byte, not the number on the sheet.**  `PodCharacter
    # .armour_class` subtracts the bias for a person to read; the neutral
    # record keeps the family's stored `60 - value` form, which is what
    # every other codec sets.
    #
    # **Both of these came from 0x0B3 until #462**, so an Amiga character in
    # plate mail converted as though he were unarmoured.  The Silver Blades
    # importer separates them: that title's `armour_class_base` goes to 0x0B3
    # and its `armour_class` to 0x187.
    out.set("armour_class_base", char.raw[ARMOUR_CLASS],
            f"Amiga .pc armour class base @{ARMOUR_CLASS:#05x}, stored "
            f"60 - value, and the unarmoured "
            f"{COMBAT_BIAS - UNARMOURED_AC} in 19 of 19 records",
            grade("armour_class"))
    out.set("armour_class", char.raw[ARMOUR_CLASS_CURRENT],
            f"Amiga .pc armour class @{ARMOUR_CLASS_CURRENT:#05x}, stored "
            f"60 - value -- what the game last computed from what the "
            f"character is wearing. Pools of Darkness recomputes it on load",
            grade("armour_class"))

    # -- the second copy of each ability, which is the permanent score -------
    second = dict(zip(ABILITY_KEYS, char.abilities_permanent))
    second["exceptional_strength"] = char.exceptional_strength_permanent
    out.set("abilities_second", second,
            f"Amiga .pc ability pairs @{ABILITIES:#05x}, the *first* byte of "
            f"each -- and byte 1 of the exceptional-strength pair at "
            f"{EXCEPTIONAL_STRENGTH:#05x}, which stores its two the other "
            f"way round (#401)",
            Confidence.PROBABLE, neutral.Provenance.RESHAPED)

    # -- the class a dual-classed human left, non-zero entries only ---------
    former = {name.lower(): level
              for name, level in zip(CLASS_LEVEL_SLOTS,
                                     char.former_class_levels) if level}
    out.set("former_levels", former,
            f"Amiga .pc former class levels @{FORMER_CLASS_LEVELS:#05x}, "
            f"named the same way as the current array. The dual-class "
            f"routine writes the old level into this array and the old "
            f"character level into {FORMER_LEVEL:#05x}",
            Confidence.CONFIRMED, neutral.Provenance.RESHAPED)

    # -- magic ---------------------------------------------------------------
    out.set("spells_known", char.spells_known,
            f"Amiga .pc spellbook mask @{SPELLBOOK:#05x}, "
            f"{SPELLBOOK_BYTES} bytes unpacked to ids",
            Confidence.CONFIRMED, neutral.Provenance.RESHAPED)
    out.set("spells_memorised", char.spells_memorised,
            f"Amiga .pc memorised list @{SPELLS_MEMORISED:#05x}, "
            f"{SPELLS_MEMORISED_LENGTH} bytes reversed into the neutral "
            f"highest-first order",
            Confidence.PROBABLE, neutral.Provenance.RESHAPED)
    out.set("spells_castable", char.spells_castable,
            f"Amiga .pc spell slots @{SPELLS_CASTABLE:#05x}, three "
            f"{SPELL_SLOT_LEVELS}-byte arrays: "
            f"{', '.join(SPELL_SLOT_CLASSES)}",
            Confidence.CONFIRMED, neutral.Provenance.RESHAPED)

    # -- how the character is, and whether the game is still playing them ----
    # A status past the end of the table is not a state the engine can draw,
    # so it is reported rather than turned into the nearest name -- the same
    # rule `goldbox.dos.to_neutral` follows.
    if char.status < len(neutral.STATUS_NAMES):
        out.set("status", neutral.STATUS_NAMES[char.status],
                f"Amiga .pc status @{STATUS:#05x} = {char.status}, the "
                f"game's own {len(neutral.STATUS_NAMES)} status words in "
                f"order -- read out of the table the character sheet indexes",
                Confidence.CONFIRMED, neutral.Provenance.RESHAPED)
    else:
        out.drop(f"The character's status: this file holds {char.status} "
                 f"there and the game has only "
                 f"{len(neutral.STATUS_NAMES)} states")
    out.set("active", char.active,
            f"Amiga .pc @{ACTIVE:#05x}: 1 for a character in the party, in "
            f"19 of 19 records",
            Confidence.CONFIRMED)

    # -- the NPC control byte: bit 7 says the engine drives this character ---
    control = char.npc_control_byte
    out.set("npc", bool(control & 0x80),
            f"bit 7 of the control byte at {NPC_CONTROL:#05x}, which is "
            f"`field_83_87`'s first byte -- where this title and Silver "
            f"Blades keep it (#303)",
            Confidence.PROBABLE)
    if control & 0x80:
        out.set("npc_control_byte", control,
                f"Amiga .pc @{NPC_CONTROL:#05x}, unchanged -- bit 7 plus the "
                f"low seven bits of morale, stored halved",
                Confidence.PROBABLE)

    # -- size: the Amiga's 1 small / 2 medium, the neutral 0 small / 1 large -
    out.set("size_small", max(0, char.size - 1),
            f"Amiga .pc size @{SIZE:#05x} less one. 1 for the corpus's one "
            f"dwarf and 2 for the eighteen humans, elves and half-elves",
            Confidence.PROBABLE, neutral.Provenance.RESHAPED)

    # One sentence rather than a dozen, because a character read out of a
    # `.pc` today still arrives carrying nothing and with no running magic:
    # `#462` decoded the item and effect regions and this reader has not been
    # taught to walk them.  **The wording is not approved**: every sentence a
    # player reads is Donald's (`.claude/rules/gui-text.md`), and this is a
    # placeholder that names the loss rather than a line anybody has signed
    # off.
    out.warnings.append(
        "This character was read from an Amiga Pools of Darkness file. The "
        "part of that file holding possessions and running magic has not "
        "been read yet, so the character arrives without them. "
        "(NOT APPROVED)")

    # **No `out.drop` line here, and that is deliberate rather than an
    # omission.**  `goldbox.dos.to_neutral` and `goldbox.c64_codec.read` each
    # keep a second table -- `DROPPED_PLAYER_TEXT`, `READ_DROPPED_PLAYER_TEXT`
    # -- of the sentences a *person* reads, and a name with no sentence in it
    # is shown nothing.  This reader has 37 names and no such table: every
    # sentence a player reads is Donald's to approve
    # (`.claude/rules/gui-text.md`), and thirty-seven at once written by an
    # agent is the opposite of that.  The whole contract is stated by
    # :func:`pod_field_disposition` and tested there, so nothing is lost in
    # silence; what is missing is the pane, and #194 says so.
    return out


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


def write_pod(char: NeutralCharacter) -> tuple[PodWriter, Report]:
    """Build a `Save/NAME.pc` writer from a neutral character, and its report.

    Everything the Amiga cannot hold lands in `Report.dropped`; everything it
    holds differently lands in `Report.warnings`.
    """
    rep = Report()
    w = neutral.Writer(char, rep, into="Amiga", dropped=POD_WRITE_DROPPED)

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
    named = _class_names(char, bits.value if bits else 0)
    # **A class the character only *was* is not one this record can hold.**
    # The neutral mask carries a dual-classed character's old class as well
    # as his current one -- `goldbox.dos.neutral_class_bits_from` unions the
    # former level array in, because the C64 needs it -- and `former_levels`
    # is on `POD_WRITE_DROPPED` here, so the `.pc` keeps the class he *is*.
    #
    # Measured on the two dual-classed characters in DOS Pools of Darkness'
    # shipped party (#194): ABAGAIL is a magic-user 12 who was a cleric 11
    # and PAINE a magic-user 13 who was a ranger 9. Before this, ABAGAIL was
    # written as `CLERIC/MAGIC-USER`, a class she is not, and PAINE was
    # refused outright -- Pools of Darkness has no magic-user/ranger code,
    # and nor should it: no character can be both at once.
    #
    # A class he *regained* -- non-zero in both arrays -- stays, since he
    # holds it now.
    held = {str(k).strip().lower(): int(v)
            for k, v in (char.get("levels") or {}).items()}
    was = {str(k).strip().lower(): int(v)
           for k, v in (char.get("former_levels") or {}).items()}
    left_behind = sorted(c for c in was
                         if was[c] and not held.get(str(c).strip().lower()))
    if left_behind and len(named) > 1:
        keep = [n for n in named
                if str(n).strip().lower() not in left_behind]
        if keep:
            # Only a class the mask actually offered. `neutral_class_bits_from`
            # unions the former class in first, so on every record measured
            # `left_behind` is a subset of `named` -- but an edited record
            # whose `class_bits` has lost that bit would otherwise be told a
            # class was left behind that was never on the sheet.
            for gone in (c for c in left_behind if c in named):
                rep.warnings.append(
                    f"Class {gone} was left behind at level {was[gone]}: "
                    f"Pools of Darkness' record on this port keeps the class "
                    f"the character is, so the class trained out of is not "
                    f"converted")
            named = keep
    classes, class_warnings = _classes_of(named)
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


def _class_names(char: NeutralCharacter, bits: int) -> list[str]:
    """The classes a neutral mask holds, named for the source's own title.

    `NeutralCharacter.game` holds a `goldbox.c64_port.C64Container`, a bare key, or
    `None`, and `titles.classes_to_names` is duck-typed on `.key` to take all
    three -- a DOS source used to raise `AttributeError: 'str' object has no
    attribute 'class_bits'` here, which nothing reached until Pools of
    Darkness became convertible (#194).

    **Pools of Darkness is a `Title` now**, so a bare `"pools-of-darkness"`
    key resolves through `titles.BY_KEY` to its own six classes rather than
    falling through to `games`' Pool of Radiance default, which names
    neither the paladin nor the ranger -- every Pools of Darkness paladin
    used to arrive as an unnameable raw `64` and was refused
    (`#460 (goldbox/games.py has no Pools of Darkness entry, so every lookup
    answers with Pool of Radiance's tables for it)`).
    """
    return titles.classes_to_names(bits, char.game)


def _races(char: NeutralCharacter) -> dict[int, str]:
    """The source title's race table, so an index can be named.

    **`NeutralCharacter.game` is a `goldbox.c64_port.C64Container`, its key, or `None`,
    and all three arrive here.** `titles.race_table` is duck-typed on `.key`
    to take all three, including a bare `"pools-of-darkness"` key, which
    `titles.BY_KEY` answers directly -- it used to fall through to
    `goldbox/games.py`, which has never heard of the title, and land on Pool
    of Radiance's numbering, under which this title's race 5 -- the human --
    read as a halfling (`#460 (goldbox/games.py has no Pools of Darkness
    entry, so every lookup answers with Pool of Radiance's tables for it)`).
    """
    return titles.race_table(char.game)


def to_pc(char: NeutralCharacter) -> tuple[bytes, Report]:
    """One neutral character as the 484 bytes of a `Save/NAME.pc`."""
    writer, rep = write_pod(char)
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
    """A whole C64 party from a save disk into a `SAVE` drawer full of
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

