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
alignment legal for its class. `tests/amiga/test_amiga.py` asserts both halves.

**This title alone.** `#470 (Give the project a neutral title beside its
neutral character record, with one port per platform a title shipped on)`'s
stage 10 split `goldbox/amiga_codec.py` by title; Pool of Radiance is in
`goldbox/amiga_por.py`, Curse and Silver Blades in `goldbox/amiga_later.py`,
and what more than one of them needs is in `goldbox/amiga_shared.py`.  Nothing
here imports any of the other three titles' modules at all.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass, field

from . import amiga_port, dos_port, neutral, titles
from .amiga_shared import ABILITY_KEYS, SAVE_KEYS, THIEF_KEYS, _name, u16, u32
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

#: What the loader reads into the character record itself, and so where the
#: item region begins in a file: `404 + 20 * item_count + 10 * effects`
#: accounts for every byte of all nineteen `.pc` files on the Amiga disks,
#: with no remainder (#462).
RECORD_BYTES = 404
#: One item, as a file holds it: the twenty bytes the loader reads into the
#: heap node at :data:`ITEM_NODE_BASE`.
ITEM_FILE_SIZE = 20
#: Where those twenty bytes land in the node, which is what identifies them:
#: node `0x2E` is `type_index` in the later Amiga titles' own item map, and
#: the loader's scroll test is `cmpi.b #$49, $2e(a2)`.
ITEM_NODE_BASE = 0x02E
#: A scroll's `type_index`, and the one item the file does not hold in a
#: single node: the loader reads the item's own `quantity` further twenty-byte
#: nodes after it, each carrying three more spell ids (§1.16, row 3). No item
#: in the nineteen `.pc` files on the Amiga disks is one -- `type_index` reads
#: 5, 8, 15, 18, 22, 28, 29, 30, 36, 37, 40, 50 and 59 across the 93 -- so the
#: chain is walked to keep the item boundaries right and its spell ids are
#: not converted: the neutral record has nowhere to put them.
SCROLL_TYPE_INDEX = 0x49
#: One effect node, the same ten bytes all three Amiga titles keep: the id at
#: 0, one byte nobody has named at 1, the duration as a big-endian word at 2,
#: DOS's two remaining payload bytes at 4 and 5, and the four-byte `next` at
#: 6. All eleven nodes in the nineteen `.pc` files on the Amiga disks read
#: `<id> ?? 00 00 FF 00`, and `<id> 00 00 FF 00` is
#: `goldbox.dos_codec.INNATE_PAYLOAD` exactly.
EFFECT_FILE_SIZE = 10
EFFECT_DURATION = 2
EFFECT_NEXT = 0x006
#: Non-zero in 7 of the 11 nodes -- 0x2C, 0x5E, 0x80, 0x9A, 0xEC, 0xF8 and
#: 0xFF, one each -- which is the same behaviour the two later Amiga titles'
#: own nodes show, 3 of 5 there. UNKNOWN, and nothing reads it.
EFFECT_UNNAMED = 1
#: The Amiga's own HEAL id, all three titles alike -- DOS Pools of Darkness
#: pushes 109 for the same timer (docs/231-where-lay-on-hands-lives.md).
LAY_ON_HANDS_AMIGA_ID = 140

#: The head of the running-effect chain, a longword. In memory it is a heap
#: pointer -- BOHLO BART AB's file holds `0x24B946` here and its three ten-byte
#: nodes hold `0x24B950`, `0x24B95A` and 0 at their own `next` -- and the
#: loader only tests it, so a `.pc` may carry anything non-zero for "there are
#: effects".
EFFECT_CHAIN = 0x004
#: What this writer puts in the effect chain head, and in a node's own `next`,
#: when another node follows. Any non-zero longword does: the loader allocates
#: each node and overwrites the stored pointer with the address it got back
#: before the read that fills it, so the value is a boolean the loader tests
#: and never an address it follows. 1 cannot be mistaken for an Amiga heap
#: address in a dump, which is why it rather than another number.
POD_CHAIN_PRESENT = 1
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
#: turned rather than of the cleric. `goldbox.dos_codec.to_neutral` deliberately
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
#: twice over: `tools/amiga/amigaenum.py sites` finds `0x05E` indexed into a
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
EXCEPTIONAL_STRENGTH = 0x07C  # one more pair; byte 0 in force, inferred from the later titles
#: Silver Blades' `gap_069`, the byte before `thac0_base` in DOS's own order.
#: The importer copies it and nothing else names it. UNKNOWN.
UNNAMED_07E = 0x07E
#: The class-and-level THAC0 before anything carried, stored `60 - value`,
#: and the game recomputes it on load -- see :data:`DERIVED`. The twelve pairs
#: of a `.pc` and a DOS record of the same class and level agree on it 12 of
#: 12: 44 for a magic-user 14, 48 for a cleric 14, 50 for a paladin 12, 52 for
#: a ranger 13.
THAC0_BASE = 0x07F
#: A paladin's remaining cure-disease uses. 1 for JORILD and TURBO K, the two
#: paladins on the Amiga disks, and 0 for the other seventeen -- which is DOS,
#: where `paladin_cures` is 1 for Guy de Valois and DEMELTINA and 0 for the
#: rest.
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
#: Hit points as rolled, before the constitution bonus. The arithmetic across
#: the nineteen `.pc` files is the AD&D table exactly: `hp_max - 0x0B8` is 22
#: for each
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
#:
#: **Both are menu positions and both have a measured range**: the ICON
#: screen steps `0x0BB` and wraps it to 0 past 13 (`addq.b #$1, $bb(a0)` then
#: `cmpi.b #$d` at `0x00CAC8`), and steps `0x0BC` and wraps it past 31
#: (`cmpi.b #$1f` at `0x00CDF8`), so the head is 0-13 and the body 0-31. The
#: drawing routine at `0x0255F0` builds the library name `CHEAD%c` from
#: :data:`SIZE` and asks it for item `0x0BB`, which is where a value past the
#: end gets `ERROR: INVALID ITEM` from -- the head and body numbers are the
#: index, and the figure slot below is not.
ICON_HEAD = 0x0BB
ICON_BODY = 0x0BC
#: Which of eight loaded combat pictures the character draws with (#305). The
#: code compares it against 7 and 8 and writes 0xFF for none.
#:
#: **The engine assigns it when the character joins the party, whatever the
#: file held**: the join routine at `0x027398` stores `0xFF` here
#: (`move.b #$ff, $bd(a3)`) before it appends the record to the roster chain,
#: then walks the chain marking the slots 0-7 already taken and counts this
#: byte up from 0 to the first free one (`0x0273FE`-`0x027432`). Character
#: creation leaves :data:`NO_PARTY_SLOT` here instead, which is what 17 of
#: the 19 `.pc` files on the disks hold; the other two hold 3 and 4, the
#: marching slots their parties gave them.
COMBAT_FIGURE = 0x0BD
#: 1 small, 2 medium -- DOS's own encoding, one greater than the neutral
#: `size_small`. 1 for BOHLO BART AB, the one dwarf on the Amiga disks, and 2
#: for the eighteen humans, elves and half-elves.
SIZE = 0x0BE
#: The six colour bytes of the combat icon. Character creation fills them
#: in the loop at `0x00FCE6`-`0x00FD1E`, one byte each as `t * 16 + t + 0x80`.
#: That is the fill loop and not the table, which the loop reads through
#: `-$6158(a4)`, so the values t = 1, 2, 3, 4, 6, 7 are inferred from the ten
#: `.pc` files that hold exactly :data:`ICON_COLOURS_DEFAULT`. The other nine
#: were edited on the ICON screen.
ICON_COLOURS = 0x0BF
ICON_COLOUR_COUNT = 6
#: `02 02` in 19 of 19, as DOS's `unnamed_1a4` is in 12 of 12, and character
#: creation writes 2 into both bytes (`0x00FDA2` and `0x00FDAC`). The Silver
#: Blades importer copies that title's own byte into 0x0C5 and then
#: overwrites it with 2 at `0x0262C8`, so 2 is what every record the engine
#: makes holds however it was made. What the pair *is* remains UNKNOWN.
UNNAMED_1A4 = 0x0C5
UNNAMED_1A4_DEFAULT = 2
#: A cached item count the save leaves stale: 3 in 17 of 19 against an item
#: region that holds four, five or six. **The count the loader uses is the
#: longword at 0x008**, which `404 + 20 * count + 10 * effects` consumes
#: exactly in 19 of 19.
#:
#: It is rebuilt with `encumbrance` and :data:`HANDS_USED`: the routine at
#: `0x019428` clears the thirteen readied-item longwords at 0x00C, this byte,
#: 0x0C8 and the encumbrance word, then walks the item chain adding one here
#: per node -- so the writer leaves all three zero and the game fills them.
ITEM_COUNT_CACHE = 0x0C7
#: How many hands the readied items take. 2 in 18 of 19, as DOS's is in 12
#: of 12; the one exception is `?T`, the thief among the nineteen. The same
#: rebuild at `0x019428` sums it out of each item type's own table entry
#: (`g6968[type * 16 + 1]`), so a converted record's zero is filled in by the
#: game rather than left beside a readied weapon.
HANDS_USED = 0x0C8
#: The saving-throw bonus the readied items add, and the third byte the same
#: rebuild fills: :data:`DERIVED_REBUILD` clears it at `0x0195C0` beside the
#: item count and :data:`HANDS_USED`, and `0x01891E` -- called from that
#: routine's own item loop at `0x019638` -- adds an item's `plus_save` into it
#: at `0x0189AC`-`0x0189B8`, **behind a branch**: the item-table entry's
#: byte 6 must have bit 7 set with its low seven bits zero, and the item type
#: must not be 1. The saving-throw routine at `0x012EB0` reads it back
#: (`move.b $c9(a0), d1`, `0x012F10`) into the roll's modifier before it
#: indexes the five throws at :data:`SAVING_THROWS`.
#:
#: CONFIRMED as rebuilt, and **not** as a rule: the sum of `plus_save` over the
#: readied items that qualify is what the files show -- 19 of 19 `.pc` files
#: equal the sum over all their readied items, 2 for the five characters
#: wearing the one type-59 item that carries `plus_save` 2, 0 for the other
#: fourteen, and no other value occurs -- but which items qualify is the
#: branch above and not what nineteen files can settle. The writer leaves it
#: zero and the game fills it in.
UNNAMED_0C9 = 0x0C9
#: 0 in 19 of 19. Written only by the Silver Blades importer and by a field
#: setter at `0x011D90`. UNKNOWN.
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
#:
#: **This port fills the region forwards, from 0x0CC, and DOS fills its own
#: backwards from the end.** CONFIRMED in the engine: the MEMORIZE screen
#: scans up from index 0 for the first zero byte and writes the id there
#: (`0x000A5C`-`0x000A86`), the tidy pass sorts the entries ascending by
#: `id & 0x7f` towards index 0 and closes any hole behind them
#: (`0x000864`-`0x00090C`), the surplus-trimmer keeps the earliest entries of
#: a level and clears the later ones (`0x015CE0`), and every routine that
#: reads the region counts `d2` from 0 to 0x8C. So a converted list belongs at
#: the *front* of the region, and reading it back out in the neutral
#: highest-first order is the same reversal DOS's needs.
#:
#: **Bit 7 is the pending flag, as in DOS**: memorising stores `id + 0x80`
#: (`subi.b #$80` on a byte, at `0x000A76`), and the rest that completes it
#: subtracts the bit back off (`0x002F30`) and prints "has memorized". The
#: byte crosses between the ports unchanged.
SPELLS_MEMORISED = 0x0CC
SPELLS_MEMORISED_LENGTH = 141
#: The memorised byte with its pending bit set. Every reader in the engine
#: masks the entry with `0x7f` before it indexes the spell table.
SPELLS_MEMORISED_PENDING = 0x80


def is_memorised_byte(value: int) -> bool:
    """Whether `value` is a byte the memorised region can hold: an id of 1-127,
    or one of 129-255, which is the same id with the pending bit set. 0 is an
    empty slot and 128 is the pending bit on one, so neither names a spell."""
    return (0 < value <= 0xFF
            and value & ~SPELLS_MEMORISED_PENDING != 0)
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
#: The armour bonus and the eight running attack-form bytes, in DOS's own
#: order. **Every one of the nine is rebuilt by the engine** and none can come
#: from a source, which is why the writer leaves the block zero:
#:
#: * `0x188`, the armour bonus, is the last thing :data:`DERIVED_REBUILD`
#:   does -- the four accumulated armour terms less 2, at `0x0196E8`;
#: * `0x189` and `0x18A`, the two attack counts, are **not** touched on load.
#:   A fight's setup loop walks every combatant (`0x003972`-`0x003990`)
#:   calling `0x007D5E`, which clears the combat block's `$0A` at `0x007E26`
#:   and then sets `0x189` from :data:`ATTACK_FORMS` (`0x008A4E`, inside
#:   `0x008A34`) and `0x18A` from the byte after it (`0x007E6A`), both
#:   unconditionally. **That order is the evidence**: whatever a record holds
#:   there is overwritten before a fight reads it. Other code does read the
#:   pair -- indexed `adda.w #$188` accesses (index 1 or 2) at `0x0088DA`,
#:   `0x0088F4`, `0x008904`, `0x008F3A` and `0x009122`, `adda.l #$189` at
#:   `0x009142`, `adda.w #$18A` at `0x007F68`, and `0x0088FC`-`0x008908`
#:   writes 1 into a count that is zero -- but the routines around the six
#:   at `0x0088DA`-`0x009142` dereference the combat block at `$40(a2)`,
#:   `0x007F68` is a helper handed the record, and the attack routine
#:   `0x007738` has callers only at `0x0067DA` and `0x00725A`. This is read
#:   from the engine's code and has not been run. The pair is 0 in 19 of 19
#:   `.pc` files, which shows only that the shipped files were saved outside a
#:   fight and is not a second, independent half of the argument;
#: * `0x18B`-`0x190`, the running damage, are copied from `0x0AD`-`0x0B2` by
#:   :data:`DERIVED_REBUILD` (`0x019556`-`0x0195AE`), and then `0x018778`
#:   overwrites `0x18B`, `0x18D` and `0x18F` from the readied weapon's own
#:   item-table entry. That overwrite is visible in the files: `0x18D` is 6 or
#:   8, a weapon's die size, where its copy source `0x0AF` is the unarmed 2 in
#:   19 of 19.
ROSTER_TAIL = 0x188
ROSTER_TAIL_LENGTH = 9
#: The five bytes of :data:`ROSTER_TAIL` that are zero in all 19 `.pc` files,
#: which is what this writer emits for the whole block: the two attack counts
#: and the second half of each damage pair.
ROSTER_TAIL_ZERO = (0x189, 0x18A, 0x18C, 0x18E, 0x190)
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

#: What character creation leaves in :data:`COMBAT_FIGURE` -- `move.b #$d,
#: $bd(a0)` at `0x00FD5A`, past the end of the eight slots the marching order
#: uses, so it reads as "this character is in nobody's line". 17 of the 19
#: `.pc` files hold it.
NO_PARTY_SLOT = 13
#: The six :data:`ICON_COLOURS` character creation writes: `t * 17 + 0x80`
#: for t in 1, 2, 3, 4, 6, 7.
ICON_COLOURS_DEFAULT = bytes(t * 17 + 0x80 for t in (1, 2, 3, 4, 6, 7))
#: What :data:`ICON_DIMENSION` holds in 19 of 19 records, and what creation
#: writes (`move.b #$1, $82(a0)` at `0x00FD50`).
ICON_DIMENSION_DEFAULT = 1


def engine_size_for_race(race: int) -> int:
    """1 or 2 for :data:`SIZE`, the way the engine's own race routine sets it.

    CONFIRMED at `0x00E552`: the routine switches on `0x058` through a
    five-entry jump table at `0x00E648` and writes `1` into `0x0BE` for the
    dwarf, the gnome and the halfling and `2` for the elf, the half-elf and
    the human, granting each race's own effects in the same breath.  It is
    what `BOHLO BART AB`, the one dwarf on the Amiga disks, holds against the
    eighteen others' 2.

    The byte is not decoration: the combat-icon drawing routine at `0x0255F0`
    indexes a table with it to build the library name `CHEAD%c`, so a record
    with zero here asks for a file the game has not got.
    """
    small = (RACES.index("DWARF"), RACES.index("GNOME"),
             RACES.index("HALFLING"))
    return 1 if race in small else 2


def engine_default_icon(race: int, sex: int, size: int,
                        class_levels: Sequence[int]) -> tuple[int, int]:
    """The head and body art the engine itself gives a new character.

    Read off the routine at `0x00C736`, which character creation calls at
    `0x00FD92` once race, sex, size and the class levels are settled.  The
    head is the character's build -- a halfling has his own, and the other
    five races split by sex and by :data:`SIZE` -- and the body is the first
    class slot with a level in it.

    It matches what the player's own disks hold in 15 of 19 records for the
    head and 11 of 19 for the body; the rest were changed on the ICON screen,
    which is the screen this routine supplies the starting position for.
    """
    if race == RACES.index("HALFLING"):
        return 3, _default_body(class_levels)
    medium = size == 2
    if sex == SEXES.index("FEMALE"):
        return (9 if medium else 7), _default_body(class_levels)
    return (5 if medium else 0), _default_body(class_levels)


def _default_body(class_levels: Sequence[int]) -> int:
    """`0x00C79E`: the first class slot with a level, in the engine's order."""
    levels = tuple(class_levels) + (0,) * CLASS_LEVEL_COUNT
    slot = {name: levels[i] for i, name in enumerate(CLASS_LEVEL_SLOTS)}
    if slot["CLERIC"]:
        return 0x17
    if slot["RANGER"]:
        return 1
    if slot["PALADIN"] or slot["FIGHTER"]:
        return 0x18
    if slot["MAGIC-USER"]:
        return 0x1D
    return 5

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
#: The portrait pair is 0x0B9-0x0BA, which the Silver Blades importer fills
#: from that title's own `portrait_head` and `portrait_body` and which nothing
#: in this title ever reads back. The byte in front of it is
#: :data:`HP_ROLLED`.
PORTRAIT_BODY = PORTRAIT_HEAD + 1

#: The routine that rebuilds every derived byte of a record, and the reason
#: :data:`DERIVED` is a claim about the running game rather than about a
#: listing. *Add Character* calls it between the `.pc` loader at `0x025806`
#: and the roster join at `0x027394` (`0x026A34`, `0x026A6C`, `0x026A74`), and
#: the inter-title import path calls it at `0x026326`; §2.3's probe wrote 1234
#: into the encumbrance word and read 233 off the sheet, which is this routine
#: running on load.
DERIVED_REBUILD = 0x019428
#: The game recomputes these on load and ignores what the file holds, so the
#: writer must not fill them in: 0x056 encumbrance (it is the coin count),
#: 0x0C7 the stale item count, 0x0C8 `hands_used`, 0x0C9 the qualifying
#: readied items' saving-throw bonus, 0x186 `60 - THAC0` (it is the best of
#: the class levels), 0x187 armour class, the whole of :data:`ROSTER_TAIL`, and
#: 0x192 movement. :data:`DERIVED_REBUILD` writes all of them but 0x189 and 0x18A,
#: which a fight's own setup loop fills from :data:`ATTACK_FORMS`.
DERIVED = (ENCUMBRANCE, ITEM_COUNT_CACHE, HANDS_USED, UNNAMED_0C9,
           THAC0_CURRENT, ARMOUR_CLASS_CURRENT,
           *range(ROSTER_TAIL, ROSTER_TAIL + ROSTER_TAIL_LENGTH),
           MOVEMENT_CURRENT)
#: The `jsr` *Add Character* makes on the loaded record. The `.pc` loader at
#: `0x025806` is called at `0x026A34`, its return code is tested, and this
#: call at `0x026A6C` follows about a dozen instructions later, one push
#: before the roster join at `0x027394` is called at `0x026A74`. It resolves
#: through the small-data table to :data:`DERIVED_REBUILD`, which is what
#: makes that routine the **load** path's and not merely a routine that exists.
DERIVED_LOAD_CALL = 0x026A6C
#: The same `jsr` on the inter-title import path, which is the second of the
#: two places the game rebuilds a record it has just read.
DERIVED_IMPORT_CALL = 0x026326
#: The instruction, as `(file offset in the Pools of Darkness executable, the
#: instruction)`, that the engine's own rebuild or fight setup uses on each
#: byte of :data:`DERIVED` that no probe has watched -- every one but
#: `encumbrance`, `THAC0_CURRENT`, `ARMOUR_CLASS_CURRENT` and
#: :data:`MOVEMENT_CURRENT`:
#:
#: * `0x0C7`, `0x0C8`: cleared at `0x01944C` and `0x019454`, counted up in the
#:   item chain's loop at `0x01946A` and `0x01952A`;
#: * `0x0C9`: cleared at `0x0195C0`, accumulated at `0x0189B8` by the routine
#:   the item loop calls at `0x019638`, read back at `0x012F10`;
#: * `0x188`: written last, at `0x0196E8`;
#: * `0x189`, `0x18A`: filled from :data:`ATTACK_FORMS` by the fight setup
#:   (`0x008A4E`, `0x007E6A`);
#: * `0x18B`-`0x190`: the copy loop at `0x019556`-`0x0195AE` runs its counter
#:   1 to 2 (`moveq #1`, `cmpi.b #2`) and copies `0x0AC + n`, `0x0AE + n` and
#:   `0x0B0 + n` to `0x18A + n`, `0x18C + n` and `0x18E + n`, so the sources
#:   are `0x0AD`-`0x0B2`; then the weapon routine `0x018778`, called at
#:   `0x019610`, overwrites `0x18B`, `0x18D` and `0x18F` from the item table
#:   (`0x018898`, `0x0188A8`, `0x0187C6`).
DERIVED_SITES: tuple[tuple[int, str], ...] = (
    (0x01944C, "clr.b $c7(a2)"),
    (0x019454, "clr.b $c8(a2)"),
    (0x019466, "lea.l $c7(a2), a0"),
    (0x01946A, "addq.b #$1, (a0)"),
    (0x01952A, "move.b d1, $c8(a2)"),
    (0x0195C0, "clr.b $c9(a2)"),
    (0x019638, "jsr $1891e(pc)"),
    (0x0189B8, "move.b d0, $c9(a0)"),
    (0x012F10, "move.b $c9(a0), d1"),
    (0x0196E8, "move.b d0, $188(a2)"),
    (0x008A4E, "move.b $ab(a0), $189(a1)"),
    (0x007E6A, "move.b d0, $18a(a0)"),
    (0x019556, "moveq #$1, d3"),
    (0x0195AA, "cmpi.b #$2, d3"),
    (0x019560, "adda.w #$ac, a0"),
    (0x01956A, "adda.w #$18a, a1"),
    (0x01956E, "move.b (a0, d0.w), (a1, d1.w)"),
    (0x01957A, "adda.w #$ae, a0"),
    (0x019584, "adda.w #$18c, a1"),
    (0x019588, "move.b (a0, d0.w), (a1, d1.w)"),
    (0x019594, "adda.w #$b0, a0"),
    (0x01959E, "adda.w #$18e, a1"),
    (0x0195A2, "move.b (a0, d0.w), (a1, d1.w)"),
    (0x019610, "jsr $18778(pc)"),
    (0x018898, "move.b $9(a0, d0.l), $18b(a2)"),
    (0x0188A8, "move.b $a(a0, d0.l), $18d(a2)"),
    (0x0187C6, "move.b $b(a0, d0.l), $18f(a2)"),
)

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
    "paladin_cures": "CONFIRMED",
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
    # CONFIRMED as *fields*, off the engine's own Silver Blades importer
    # (`tools/amiga/podimportmap.py`), which copies DOS's own icon_head,
    # icon_body and icon_colours untranslated into these three offsets --
    # not because a probe has drawn a converted figure (#612).
    "icon_head": "CONFIRMED",
    "icon_body": "CONFIRMED",
    "icon_colours": "CONFIRMED",
}


def _item_offset(dos_offset: int) -> int:
    """Where a DOS item field lands in the twenty bytes a `.pc` holds.

    The same three insertions Curse of the Azure Bonds and Secret of the
    Silver Blades have, `goldbox.amiga_port.AMIGA_LATER_ITEM_SHIFTS`, read out
    of those two titles' own item constructors for `#55`; this title's file
    bytes start at :data:`ITEM_NODE_BASE` rather than at the node's top,
    because the loader reads twenty bytes to `+0x2E` and the display text and
    the `next` pointer in front of them are built in memory.
    """
    shift = 0
    for first, amount in amiga_port.AMIGA_LATER_ITEM_SHIFTS:
        if dos_offset >= first:
            shift = amount
    return dos_offset + shift - ITEM_NODE_BASE


#: DOS item field -> where it is in the twenty bytes. Every field of
#: `goldbox.dos_port.ITEM_LAYOUT` from `type_index` on: the three in front of
#: it are the cached display line and the `next` pointer, which no file holds.
ITEM_FIELDS: dict[str, dos_port.Field] = {
    f.name: f for f in dos_port.ITEM_LAYOUT if f.offset >= ITEM_NODE_BASE}
ITEM_FIELD_AT: dict[str, int] = {
    name: _item_offset(f.offset) for name, f in ITEM_FIELDS.items()}
#: The three bytes of the twenty no DOS item field maps onto -- the
#: insertions -- derived rather than restated. **Zero in 93 of 93 items**,
#: which is the constructor's own `setmem(node, size, 0)` and what an item the
#: game built itself looks like.
ITEM_PADS: tuple[int, ...] = tuple(
    sorted(set(range(ITEM_FILE_SIZE)) - {
        at + i for name, at in ITEM_FIELD_AT.items()
        for i in range(ITEM_FIELDS[name].size)}))


@dataclass(frozen=True)
class PodItem:
    """One item, as the twenty bytes after the 404-byte record hold it.

    **The later Amiga titles' own item node, CONFIRMED** (#462). Four things
    say so and the last is decisive: the loader reads the twenty bytes to node
    `+0x2E`, which is `type_index` in that map, and tests `+0x0C` --
    `quantity` -- for a scroll's chained nodes; 93 of 93 items decode in range,
    with `readied` 0 or 1, `hidden` and `cursed` 0 and the three insertion
    pads zero; `money + sum(weight * max(quantity, 1))` balances the stored
    encumbrance word at record `0x056` in 19 of 19 files at three distinct
    totals; and `404 + 20 * item_count + 10 * effects` consumes every byte of
    every file with no remainder.
    """

    raw: bytes

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> "PodItem":
        if len(data) != ITEM_FILE_SIZE:
            raise ValueError(
                f"a Pools of Darkness .pc item is {ITEM_FILE_SIZE} bytes, "
                f"got {len(data)}")
        return cls(bytes(data))

    def get(self, field_name: str):
        """One field, by its `goldbox/dos_port.py` item-table name."""
        f = ITEM_FIELDS[field_name]
        at = ITEM_FIELD_AT[field_name]
        chunk = self.raw[at:at + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            return int.from_bytes(chunk, "big")
        if f.kind is Kind.I8:
            return int.from_bytes(chunk, "big", signed=True)
        if f.kind is Kind.U8:
            return chunk[0]
        return chunk

    @property
    def type_index(self) -> int:
        return self.get("type_index")

    @property
    def quantity(self) -> int:
        return self.get("quantity")

    @property
    def weight(self) -> int:
        return self.get("weight")

    @property
    def value(self) -> int:
        return self.get("value")

    @property
    def readied(self) -> bool:
        return bool(self.get("readied"))

    @property
    def pads(self) -> tuple[int, ...]:
        """The three insertion bytes, which an item the game built is zero in."""
        return tuple(self.raw[at] for at in ITEM_PADS)

    @property
    def is_scroll(self) -> bool:
        """Whether the loader reads `quantity` further nodes after this one."""
        return self.type_index == SCROLL_TYPE_INDEX

    def to_dos_bytes(self) -> bytes:
        """This item as the 63 bytes `goldbox/dos_port.py` describes.

        The display text becomes DOS's count byte and its 41, empty: what a
        `.pc` holds begins past it, and the buffer is the ITEMS screen's own
        cache on both ports rather than a source. Every `u16` is byte-swapped
        -- it is a 68000 -- and `next` is NULL, because on the Amiga it is a
        live heap address and the DOS engine rebuilds the chain on load.
        """
        out = bytearray(dos_port.ITEM_SIZE)
        for name, f in ITEM_FIELDS.items():
            at = ITEM_FIELD_AT[name]
            chunk = self.raw[at:at + f.size]
            if f.kind in (Kind.U16LE, Kind.UINT_LE):
                chunk = chunk[::-1]
            out[f.offset:f.offset + f.size] = chunk
        return bytes(out)

    @classmethod
    def from_dos_bytes(cls, record: bytes) -> "PodItem":
        """One DOS item record as the twenty bytes a `.pc` holds.

        The inverse of :meth:`to_dos_bytes`: the fields below `0x02E` are the
        rendered display line and the chain pointer, which no file carries and
        the game rebuilds, and every `u16` is byte-swapped back -- it is a
        68000. The three insertion bytes stay zero, which is what the game's
        own item constructor leaves in them.
        """
        if len(record) != dos_port.ITEM_SIZE:
            raise ValueError(
                f"a DOS item is {dos_port.ITEM_SIZE} bytes, got {len(record)}")
        out = bytearray(ITEM_FILE_SIZE)
        for name, f in ITEM_FIELDS.items():
            at = ITEM_FIELD_AT[name]
            chunk = record[f.offset:f.offset + f.size]
            if f.kind in (Kind.U16LE, Kind.UINT_LE):
                chunk = chunk[::-1]
            out[at:at + f.size] = chunk
        return cls(bytes(out))


def pod_effect_to_dos(node: bytes) -> bytes:
    """One ten-byte effect node as the nine bytes a DOS `.EFX` record holds.

    The duration is a `u16` big-endian at 2 where DOS keeps it little-endian
    at 1, the byte at 1 is the one nothing has named, and the four-byte `next`
    is written NULL: it is a live Amiga heap address, and the DOS engine
    rebuilds the chain from the file's length. The same re-cut the Amiga Pool
    of Radiance and the two later titles' readers make, written here rather
    than imported because this module reads no other title's.
    """
    if len(node) != EFFECT_FILE_SIZE:
        raise ValueError(
            f"a Pools of Darkness .pc effect node is {EFFECT_FILE_SIZE} "
            f"bytes, got {len(node)}")
    return bytes((node[0], node[3], node[2], node[4], node[5])) + bytes(4)


def pod_effect_from_dos(node: bytes) -> bytes:
    """One nine-byte DOS `.EFX` record as the ten bytes a `.pc` holds.

    The inverse of :func:`pod_effect_to_dos`: the byte at 1 is the one nothing
    has named and is written zero, the duration is byte-swapped into `0x002`,
    and the four-byte `next` is left NULL for :meth:`PodWriter.to_bytes` to
    set, which is the only place that knows whether a node follows.
    """
    if len(node) != dos_port.EFFECT_SIZE:
        raise ValueError(
            f"a DOS effect record is {dos_port.EFFECT_SIZE} bytes, "
            f"got {len(node)}")
    return bytes((node[0], 0, node[2], node[1], node[3], node[4])) + bytes(4)


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
        """The percentile in force, inferred from the later titles: byte 0 of
        its pair, where the six ability pairs keep it in byte 1.

        `CONFIDENCE` grades it PROBABLE. All 19 specimens hold equal halves,
        so nothing on the Amiga's own disks says which byte is which; the
        rule is the one `goldbox.dos_codec._ability_pair` read out of the
        later titles' overlay.
        """
        return self.raw[EXCEPTIONAL_STRENGTH]

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
    def treasure_share(self) -> int:
        """The raw byte the Silver Blades importer copies from 0x09B."""
        return self.raw[FIELD_83_87_SECOND]

    @property
    def field_83_87_window(self) -> bytes:
        """`field_83_87` reassembled in the shared DOS order: control, share,
        the class a dual-classed human left, and the byte after it -- the
        first three read from their own scattered offsets, the fourth from
        :data:`FIELD_83_87_THIRD`, which the Silver Blades importer's own
        copy places at 0x05B (`docs/229-the-npc-window-bytes.md`)."""
        return bytes((self.raw[NPC_CONTROL], self.raw[FIELD_83_87_SECOND],
                     self.raw[FIELD_83_87_THIRD], self.raw[FIELD_83_87_FOURTH]))

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

        `goldbox.dos_codec._ability_pair` read the asymmetry out of the shipped
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
        `i + 1` -- the same numbering `goldbox.dos_codec.DosCharacter.spells_known`
        hands back, so the two ports' lists compare directly.
        """
        mask = self.raw[SPELLBOOK:SPELLBOOK + SPELLBOOK_BYTES]
        return [byte * 8 + bit + 1
                for byte in range(len(mask)) for bit in range(8)
                if mask[byte] >> bit & 1]

    @property
    def spells_memorised(self) -> list[int]:
        """Memorised spell ids, highest first -- the neutral order.

        **This port fills the region forwards from 0x0CC and sorts it
        ascending by id**, where DOS fills its own 141 bytes backwards from
        the end and so also ends up ascending towards the last byte
        (:data:`SPELLS_MEMORISED` has the four routines that say so).  Either
        way the ids run ascending through memory, so reversing is the
        transpose in both directions and the zeroes fall out.  No specimen
        has a spell in it: all nineteen `.pc` files on the Amiga disks are
        zero here.
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

    # -- the tail: the item region and the effect chain (#462) --------------

    @property
    def item_count(self) -> int:
        """How many items follow the record -- the longword at 0x008.

        **Not the byte at** :data:`ITEM_COUNT_CACHE`, which the save leaves
        stale: it reads 3 in 17 of 19 files whose item region holds four,
        five or six.
        """
        return u32(self.raw, ITEM_CHAIN)

    def _tail(self) -> tuple[tuple["PodItem", ...], tuple[bytes, ...],
                             tuple[bytes, ...]]:
        """The item nodes, any chained scroll nodes, and the effect nodes.

        Walked exactly as the loader walks it (`docs/124-amiga-port.md`
        §1.16): `item_count` items of twenty bytes from
        :data:`RECORD_BYTES`, each scroll followed by its own `quantity`
        further twenty-byte nodes, and then effect nodes of ten bytes while
        the previous one's `next` is non-zero, starting from the chain head at
        0x004. A short buffer stops the walk rather than raising -- this title
        checks no length and a `.pc` with no items and no effects is 404
        bytes, where `PodWriter` emits 484.
        """
        items: list[PodItem] = []
        scrolls: list[bytes] = []
        effects: list[bytes] = []
        at = RECORD_BYTES
        while len(items) < self.item_count and at + ITEM_FILE_SIZE <= len(
                self.raw):
            item = PodItem.from_bytes(self.raw[at:at + ITEM_FILE_SIZE])
            at += ITEM_FILE_SIZE
            items.append(item)
            if item.is_scroll:
                for _ in range(item.quantity):
                    if at + ITEM_FILE_SIZE > len(self.raw):
                        break
                    scrolls.append(self.raw[at:at + ITEM_FILE_SIZE])
                    at += ITEM_FILE_SIZE
        following = u32(self.raw, EFFECT_CHAIN)
        while following and at + EFFECT_FILE_SIZE <= len(self.raw):
            node = self.raw[at:at + EFFECT_FILE_SIZE]
            at += EFFECT_FILE_SIZE
            effects.append(node)
            following = int.from_bytes(
                node[EFFECT_NEXT:EFFECT_NEXT + 4], "big")
        return tuple(items), tuple(scrolls), tuple(effects)

    @property
    def items(self) -> tuple["PodItem", ...]:
        """Everything the character is carrying, in the file's own order."""
        return self._tail()[0]

    @property
    def scroll_nodes(self) -> tuple[bytes, ...]:
        """The twenty-byte nodes chained off a scroll, unconverted.

        Each holds three more spell ids in the bytes the item constructor
        calls `charges`, `effect` and `power`, and the neutral record has
        nowhere to put them. **Empty in 19 of 19 files on the Amiga disks**:
        no item in the nineteen files is a scroll.
        """
        return self._tail()[1]

    @property
    def effects(self) -> tuple[bytes, ...]:
        """The running-effect chain, ten bytes a node, in chain order."""
        return self._tail()[2]


@dataclass
class PodWriter:
    """Build a `Save/NAME.pc` Amiga Pools of Darkness will load.

    Every field the record is decoded for is written. What is left zero is the
    heap pointers at 0x00-0x5F, which the loader overwrites, and the derived
    block the game recomputes on load (:data:`DERIVED`). The combat icon at
    0x0BB-0x0BD and 0x0BF-0x0C4 is not taken from the source at all: it is
    what the engine's own creation routine would have given this character
    (:func:`engine_default_icon`), because the numbers are menu positions in
    this port's own art and a value past the end of `CHEAD.TLB` makes the
    loader refuse the file. `provenance()` says where every non-zero byte of
    the output came from, so nothing lands in the file uncredited.

    The tail past the 404-byte record is built here too: `items` are twenty
    bytes each and the count goes in the longword at 0x008, a scroll is
    followed by its own `quantity` further nodes so the loader's walk stays in
    step, and `effects` are ten bytes each with a chain head and a `next` that
    are non-zero exactly when a node follows.
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
    treasure_share: int | None = None
    #: The combat block, which this title splits between 0x05E-0x05F and
    #: 0x184-0x185. `active` is 1 in 19 of 19 records the game itself wrote and
    #: 0 is the out-of-the-party value on the other two ports, so a record this
    #: writer makes joins the party unless the caller says otherwise.
    status: int = 0
    hostile: bool = False
    active: bool = True
    quickfight: bool = False
    #: The scalars the record is decoded for, written when the caller has one.
    thac0_base: int | None = None
    #: A paladin's cure-disease byte, written only when the source holds one.
    paladin_cures: int | None = None
    hit_points_rolled: int | None = None
    identity: int | None = None
    experience_award: int | None = None
    #: The game's own 1 small / 2 medium, not the neutral 0/1.
    size: int | None = None
    npc_control_byte: int | None = None
    former_level: int | None = None
    former_class_levels: tuple[int, ...] | None = None
    #: `field_83_87`'s third and fourth bytes in the shared DOS order --
    #: the class a dual-classed human left (0x05B) and the byte after it
    #: (0x095) -- neither read by this title's own engine, carried across a
    #: route that has the window on both sides rather than dropped (#614).
    field_83_87_third: int | None = None
    field_83_87_fourth: int | None = None
    #: The permanent half of each pair -- the first byte, where the score in
    #: force is the second. Both halves take `abilities` when this is None,
    #: which is what every record measured on either port holds.
    abilities_permanent: tuple[int, ...] | None = None
    exceptional_strength_permanent: int | None = None
    #: The eight attack-form bytes as a block, which carry the damage triple
    #: at 0x0AD/0x0AF/0x0B1 and so override `damage` when they are given.
    attack_forms: tuple[int, ...] | bytes | None = None
    #: Spell ids for the sixteen-byte mask at 0x159, and slots free per level
    #: for the three nine-byte arrays at 0x169, 0x172 and 0x17B, by class name.
    spells_known: tuple[int, ...] | None = None
    spells_castable: dict[str, tuple[int, ...]] | None = None
    #: Memorised spell ids, highest first as the neutral record keeps them.
    #: They go into 0x0CC ascending from the front, which is the end this
    #: port fills from -- see :data:`SPELLS_MEMORISED`.
    spells_memorised: tuple[int, ...] | None = None
    #: The roster byte at 0x0BD. The engine overwrites it when the character
    #: joins a party, so the default is the :data:`NO_PARTY_SLOT` creation
    #: itself writes rather than a slot taken from the source.
    combat_figure: int = NO_PARTY_SLOT
    #: The combat icon. `None` takes what the engine's own creation routine
    #: would have given this character -- see :func:`engine_default_icon`.
    icon_head: int | None = None
    icon_body: int | None = None
    icon_colours: bytes | None = None
    #: The tail: twenty bytes an item, head items only, and ten an effect.
    items: tuple[bytes, ...] = ()
    effects: tuple[bytes, ...] = ()

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
        # The ICON screen's own wrap points, which are what the art libraries
        # have: a head past 13 or a body past 31 is an item `CHEAD.TLB` has
        # not got, and the loader refuses the whole file for one.
        if self.icon_head is not None and not 0 <= self.icon_head <= 13:
            raise ValueError("the combat icon's head is 0 to 13")
        if self.icon_body is not None and not 0 <= self.icon_body <= 31:
            raise ValueError("the combat icon's body is 0 to 31")
        for spell in self.spells_memorised or ():
            if not is_memorised_byte(spell):
                raise ValueError(
                    f"memorised spell id {spell}: a byte of 1-127, or 129-255 "
                    f"with the pending bit set")
        if self.armour_class > COMBAT_BIAS:
            raise ValueError("armour class is stored as 60 - AC; 60 is the cap")
        if (self.treasure_share is not None
                and not 0 <= self.treasure_share <= 0xFF):
            raise ValueError("treasure share does not fit in one byte")
        if not 0 <= self.status < len(neutral.STATUS_NAMES):
            raise ValueError(
                f"status {self.status} is not one of the game's own "
                f"{len(neutral.STATUS_NAMES)} states")
        if (self.abilities_permanent is not None
                and len(self.abilities_permanent) != ABILITY_COUNT):
            raise ValueError("six permanent abilities, in the sheet's order")
        if (self.former_class_levels is not None
                and len(self.former_class_levels) != CLASS_LEVEL_COUNT):
            raise ValueError(f"{CLASS_LEVEL_COUNT} former class levels")
        if (self.attack_forms is not None
                and len(self.attack_forms) != ATTACK_FORM_COUNT):
            raise ValueError(f"{ATTACK_FORM_COUNT} attack-form bytes")
        for spell in self.spells_known or ():
            if not 1 <= spell <= SPELLBOOK_BYTES * 8:
                raise ValueError(
                    f"spell id {spell} is outside the {SPELLBOOK_BYTES * 8} "
                    f"the mask at {SPELLBOOK:#05x} has room for")
        for class_name, slots in (self.spells_castable or {}).items():
            if len(slots) > SPELL_SLOT_LEVELS:
                raise ValueError(
                    f"{class_name} has {len(slots)} spell levels; this title "
                    f"keeps {SPELL_SLOT_LEVELS}")
        for item in self.items:
            if len(item) != ITEM_FILE_SIZE:
                raise ValueError(
                    f"an item is {ITEM_FILE_SIZE} bytes, got {len(item)}")
        for node in self.effects:
            if len(node) != EFFECT_FILE_SIZE:
                raise ValueError(
                    f"an effect node is {EFFECT_FILE_SIZE} bytes, "
                    f"got {len(node)}")

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
        if self.treasure_share is not None:
            plan.append((FIELD_83_87_SECOND, 1, "treasure_share"))
        plan.extend([(STATUS, 1, "status"), (HOSTILE, 1, "hostile"),
                     (ACTIVE, 1, "active"), (QUICKFIGHT, 1, "quickfight")])
        for value, at, width, what in (
                (self.thac0_base, THAC0_BASE, 1, "thac0_base"),
                (self.paladin_cures, PALADIN_CURES, 1, "paladin_cures"),
                (self.hit_points_rolled, HP_ROLLED, 1, "hit_points_rolled"),
                (self.identity, UNNAMED_0AB, 1, "identity"),
                (self.experience_award, EXPERIENCE_AWARD, 2,
                 "experience_award"),
                (self.npc_control_byte, NPC_CONTROL, 1, "npc_control_byte"),
                (self.former_level, FORMER_LEVEL, 1, "former_level"),
                (self.field_83_87_third, FIELD_83_87_THIRD, 1,
                 "field_83_87_third"),
                (self.field_83_87_fourth, FIELD_83_87_FOURTH, 1,
                 "field_83_87_fourth")):
            if value is not None:
                plan.append((at, width, what))
        if self.former_class_levels is not None:
            plan.append((FORMER_CLASS_LEVELS, CLASS_LEVEL_COUNT,
                         "former_class_levels"))
        if self.abilities_permanent is not None:
            plan.extend((ABILITIES + 2 * i, 1, "abilities_permanent")
                        for i in range(ABILITY_COUNT))
        if self.exceptional_strength_permanent is not None:
            plan.append((EXCEPTIONAL_STRENGTH + 1, 1,
                         "exceptional_strength_permanent"))
        # After `damage`, which it carries at 0x0AD, 0x0AF and 0x0B1.
        if self.attack_forms is not None:
            plan.append((ATTACK_FORMS, ATTACK_FORM_COUNT, "attack_forms"))
        if self.spells_known is not None:
            plan.append((SPELLBOOK, SPELLBOOK_BYTES, "spells_known"))
        if self.spells_castable is not None:
            plan.append((SPELLS_CASTABLE,
                         SPELL_SLOT_LEVELS * len(SPELL_SLOT_CLASSES),
                         "spells_castable"))
        if self.spells_memorised:
            plan.append((SPELLS_MEMORISED,
                         min(len(self.spells_memorised),
                             SPELLS_MEMORISED_LENGTH), "spells_memorised"))
        plan.extend([(SIZE, 1, "size"), (UNNAMED_1A4, 2, "unnamed_1a4"),
                     (ICON_HEAD, 1, "icon_head"), (ICON_BODY, 1, "icon_body"),
                     (ICON_COLOURS, ICON_COLOUR_COUNT, "icon_colours"),
                     (ICON_DIMENSION, 1, "icon_dimension"),
                     (COMBAT_FIGURE, 1, "combat_figure")])
        nodes, effects = self._tail_nodes()
        if self.items:
            plan.append((ITEM_CHAIN, 4, "item_count"))
            carried = 0
            for at, head in nodes:
                plan.append((at, ITEM_FILE_SIZE, f"item {carried}" if head else
                             f"item {carried - 1}'s own spell node"))
                carried += head
        if self.effects:
            plan.append((EFFECT_CHAIN, 4, "effect_chain"))
            for n, at in enumerate(effects):
                plan.append((at, EFFECT_FILE_SIZE, f"effect {n}"))
        return plan

    def _tail_nodes(self) -> tuple[list[tuple[int, bool]], list[int]]:
        """Where each tail node lands, and whether an item node is a head one.

        A scroll is followed by its own `quantity` further twenty-byte nodes,
        which the loader reads before the next item (`docs/124-amiga-port.md`
        §1.16 row 3), so the count at 0x008 and the file's length are two
        different arithmetics and this is the one that knows both.
        """
        items: list[tuple[int, bool]] = []
        at = RECORD_BYTES
        for node in self.items:
            items.append((at, True))
            at += ITEM_FILE_SIZE
            item = PodItem.from_bytes(node)
            if item.is_scroll:
                for _ in range(item.quantity):
                    items.append((at, False))
                    at += ITEM_FILE_SIZE
        effects = []
        for _ in self.effects:
            effects.append(at)
            at += EFFECT_FILE_SIZE
        return items, effects

    def to_bytes(self) -> bytes:
        self._check()
        nodes, effect_at = self._tail_nodes()
        length = max(RECORD_LENGTH,
                     (effect_at[-1] + EFFECT_FILE_SIZE if effect_at else
                      nodes[-1][0] + ITEM_FILE_SIZE if nodes else
                      RECORD_BYTES))
        out = bytearray(length)
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
        if self.treasure_share is not None:
            out[FIELD_83_87_SECOND] = self.treasure_share

        out[STATUS] = self.status
        out[HOSTILE] = int(bool(self.hostile))
        out[ACTIVE] = int(bool(self.active))
        out[QUICKFIGHT] = int(bool(self.quickfight))
        for value, at in ((self.thac0_base, THAC0_BASE),
                          (self.paladin_cures, PALADIN_CURES),
                          (self.hit_points_rolled, HP_ROLLED),
                          (self.identity, UNNAMED_0AB),
                          (self.npc_control_byte, NPC_CONTROL),
                          (self.former_level, FORMER_LEVEL),
                          (self.field_83_87_third, FIELD_83_87_THIRD),
                          (self.field_83_87_fourth, FIELD_83_87_FOURTH)):
            if value is not None:
                out[at] = min(value, 0xFF)
        if self.experience_award is not None:
            struct.pack_into(">H", out, EXPERIENCE_AWARD,
                             min(self.experience_award, 0xFFFF))
        if self.former_class_levels is not None:
            out[FORMER_CLASS_LEVELS:
                FORMER_CLASS_LEVELS + CLASS_LEVEL_COUNT] = bytes(
                    self.former_class_levels)
        if self.abilities_permanent is not None:
            for i, score in enumerate(self.abilities_permanent):
                out[ABILITIES + 2 * i] = score
        if self.exceptional_strength_permanent is not None:
            out[EXCEPTIONAL_STRENGTH + 1] = self.exceptional_strength_permanent
        # After the damage triple, which lives inside these eight bytes.
        if self.attack_forms is not None:
            out[ATTACK_FORMS:ATTACK_FORMS + ATTACK_FORM_COUNT] = bytes(
                self.attack_forms)
        if self.spells_known is not None:
            for spell in self.spells_known:
                index = spell - 1
                out[SPELLBOOK + index // 8] |= 1 << (index % 8)
        if self.spells_castable is not None:
            for i, class_name in enumerate(SPELL_SLOT_CLASSES):
                slots = tuple(self.spells_castable.get(class_name, ()))
                at = SPELLS_CASTABLE + SPELL_SLOT_LEVELS * i
                out[at:at + len(slots)] = bytes(slots)
        # Ascending by id with the pending bit masked off, which is the order
        # the engine's own tidy pass leaves the region in, and from the front,
        # which is the end the MEMORIZE screen fills from.
        if self.spells_memorised:
            ids = sorted(self.spells_memorised,
                         key=lambda i: i & ~SPELLS_MEMORISED_PENDING
                         )[:SPELLS_MEMORISED_LENGTH]
            out[SPELLS_MEMORISED:SPELLS_MEMORISED + len(ids)] = bytes(ids)

        # The combat icon and the roster slot: what the engine's own creation
        # routine writes, for a record it did not create. A source with no
        # size of its own gets the one its race would have been given, which
        # is also what the icon's own art library is chosen by.
        size = self.size if self.size else engine_size_for_race(self.race)
        out[SIZE] = size
        head, body = engine_default_icon(self.race, self.sex, size,
                                         self.class_levels)
        out[ICON_HEAD] = self.icon_head if self.icon_head is not None else head
        out[ICON_BODY] = self.icon_body if self.icon_body is not None else body
        colours = (ICON_COLOURS_DEFAULT if self.icon_colours is None
                   else bytes(self.icon_colours))
        out[ICON_COLOURS:ICON_COLOURS + ICON_COLOUR_COUNT] = colours[
            :ICON_COLOUR_COUNT].ljust(ICON_COLOUR_COUNT, b"\0")
        out[ICON_DIMENSION] = ICON_DIMENSION_DEFAULT
        out[COMBAT_FIGURE] = self.combat_figure
        out[UNNAMED_1A4] = out[UNNAMED_1A4 + 1] = UNNAMED_1A4_DEFAULT

        if self.items:
            struct.pack_into(">I", out, ITEM_CHAIN, len(self.items))
            carried = iter(self.items)
            for at, head in nodes:
                if head:
                    out[at:at + ITEM_FILE_SIZE] = next(carried)
        if self.effects:
            struct.pack_into(">I", out, EFFECT_CHAIN, POD_CHAIN_PRESENT)
            for n, at in enumerate(effect_at):
                node = bytearray(self.effects[n])
                following = POD_CHAIN_PRESENT if n + 1 < len(effect_at) else 0
                struct.pack_into(">I", node, EFFECT_NEXT, following)
                out[at:at + EFFECT_FILE_SIZE] = node
        return bytes(out)


# ---------------------------------------------------------------------------
# Anything -> Amiga: the writing half of the pair `goldbox/neutral.py` describes
# ---------------------------------------------------------------------------
# The middle is a `NeutralCharacter`, the same record `goldbox/dos_codec.py` reads into
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
#: dexterity bonus, so copying it would count the armour twice. The stored
#: base is a constant of the format, and the bonus a worn item gives is
#: recomputed by the game from the item nodes the writer emits. **That last
#: half is argued, not run**: probe P3 built its record with no items, so
#: nothing has shown the sheet's armour class moving for a readied piece of
#: armour.
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
    ("treasure_share", "treasure_share"),
    ("exceptional_strength", "exceptional_strength"),
    ("level", "level"),
    ("sex", "sex"),
    ("alignment", "alignment"),
    ("active", "the byte at 0x184, 1 for a character in the party"),
    ("hostile", "the byte at 0x05F, the combat side"),
    ("quickfight", "the byte at 0x185"),
    ("thac0_base", "the byte at 0x07F, stored 60 - value, which the game "
                   "recomputes from the class levels on load"),
    ("hp_rolled", "the byte at 0x0B8, hit points before the constitution "
                  "bonus"),
    ("unnamed_0ab", "the identity draw, at 0x0B5"),
    ("experience_award", "the word at 0x054"),
    ("attack_forms", "the eight bytes at 0x0AB as a block, which carry the "
                     "damage triple this record keeps unarmed"),
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
    ("status", "one of the game's own nine status words -> the byte at 0x05E, "
               "which indexes DOS's nine in DOS's order"),
    ("size_small", "the neutral 0 small / 1 large -> this port's 1 small / "
                   "2 medium at 0x0BE. A source with no size of its own gets "
                   "the one the engine's race routine would have given him "
                   "(1 for a dwarf, a gnome and a halfling), because the "
                   "byte chooses the combat icon's art library and a zero "
                   "asks for a file the game has not got"),
    ("npc", "bit 7 of the control byte at 0x093: the source's own byte where "
            "it has one, and bit 7 alone where it says `npc` without one"),
    ("spells_known", "the ids packed into the sixteen-byte mask at 0x159: bit "
                     "i of byte i >> 3 is id i + 1, which is the numbering "
                     "the DOS record's own array has"),
    ("spells_castable", "the three nine-byte arrays at 0x169, 0x172 and "
                        "0x17B, by class name: cleric, druid, magic-user. A "
                        "source keeping fewer spell levels fills the low "
                        "ones and the rest stay zero"),
    ("spells_memorised", "the neutral highest-first list reversed into the "
                         "141 bytes at 0x0CC, ascending from the front, "
                         "which is the end this port's own MEMORIZE screen "
                         "fills from and the order its tidy pass leaves. The "
                         "pending bit 7 crosses unchanged: both ports store "
                         "`id + 0x80` until a night's rest takes it off"),
    ("inventory", "the shared sixteen-byte items -> the twenty bytes a `.pc` "
                  "holds, through the DOS record both ports' item nodes are "
                  "cut from. The count goes in the longword at 0x008 and a "
                  "scroll is followed by its own `quantity` further nodes"),
    ("innate_effects", "an id each -> a ten-byte node carrying DOS's own "
                       "innate payload, after the item region. Nothing is "
                       "derived from a race table: what the source's own "
                       "record holds is what is written"),
)

#: Neutral fields this writer converts **when the character has one**, which
#: is why they are not in the two tables above: a reader sets each of these
#: only for the character it belongs to -- `former_levels` for a dual-classed
#: one, `npc_control_byte` for a companion, `granted_effects` for a character
#: with something running on him, `abilities_second` for a port that keeps two
#: copies of each score -- so a table asserting that every source supplies them
#: would be asserting something no port does.
POD_WRITE_WHEN_PRESENT: tuple[tuple[str, str], ...] = (
    ("paladin_cures", "the byte at 0x080 unchanged: 1 for a paladin who may "
                      "still cure, 0 otherwise. Only a source that keeps one "
                      "has a value to give, so a Pool of Radiance record, "
                      "which has none, leaves it 0"),
    ("former_levels", "the seven-slot array at 0x0A4, named the same way as "
                      "the current levels, and the level he left his old "
                      "class at into 0x08A -- which is what the engine's own "
                      "dual-class routine writes there"),
    ("npc_control_byte", "the byte at 0x093 unchanged: bit 7 plus the low "
                         "seven bits of morale, stored halved"),
    ("abilities_second", "the *first* byte of each pair at 0x070, the "
                         "permanent score behind the one in force -- and byte "
                         "1 of the exceptional-strength pair, which stores "
                         "its two the other way round"),
    ("granted_effects", "each whole nine-byte record -> a ten-byte node after "
                        "the item region, the duration byte-swapped, with a "
                        "chain head and a `next` that are non-zero exactly "
                        "when another node follows"),
    ("running_effects", "each whole nine-byte record -> a ten-byte node "
                        "after the granted ones, the time left byte-swapped "
                        "into the big-endian word at 0x002 like a grant's "
                        "duration. That word's byte order is PROBABLE rather "
                        "than CONFIRMED: no node on any Amiga disk holds a "
                        "value there, so the swap has never been read back "
                        "by the game"),
    ("icon_head", "the byte at 0x0BB unchanged, 0-13. Only a source that "
                  "kept a chosen head has one to give; a source with none "
                  "gets the engine's own creation default instead (#612, "
                  "see `engine_default_icon`)"),
    ("icon_body", "the byte at 0x0BC unchanged, 0-31 -- see `icon_head`"),
    ("icon_colours", "the six bytes at 0x0BF unchanged -- see `icon_head`"),
    ("lay_on_hands_minutes", "a ten-byte node after the running effects, id "
                             "140 (this title's own HEAL id on the Amiga, "
                             "not DOS's 109), the minutes big-endian at "
                             "0x002. A value of zero writes no node at all"),
)

#: Neutral fields this writer takes nothing from, and why. Reported, never
#: silent: `neutral.Writer.finish` quotes these for whatever the character
#: carries, and :func:`pod_write_field_disposition` states the whole contract
#: whether or not any one character happens to carry it.
#:
#: Two kinds of row are **not** here, because neither is a loss and counting
#: them as one would tell a player something untrue: a field the game
#: recomputes on load is in :data:`POD_WRITE_DERIVED`, and one that holds the
#: same value in every record anybody has read is in
#: :data:`POD_WRITE_CONSTANTS`.
POD_WRITE_DROPPED: tuple[tuple[str, str], ...] = (
    ("copper", "Pools of Darkness keeps platinum, gems and jewelry and no "
               "other coin, on both of its ports, so a source of this title "
               "has none to give"),
    ("silver", "see `copper`: this title has three money slots"),
    ("electrum", "see `copper`: this title has three money slots"),
    ("gold", "see `copper`: this title has three money slots"),
    ("infravision", "a C64 field; neither this title's `.pc` nor its DOS "
                    "record has one, and PoD takes what it needs from race"),
    ("hp_lost_to_drain", "this title counts level drain the other way round, "
                         "keeping the highest levels reached at 0x096, the "
                         "highest experience at 0x048 and the highest hit "
                         "points at 0x0B6. Its DOS record has no "
                         "drained-level pair either, so a source of this "
                         "title has nothing to give"),
    ("levels_drained", "see `hp_lost_to_drain`: the high-water marks are what "
                       "this title stores instead"),
    ("turn_power", "a cleric's turning strength is worked out from the class "
                   "levels when TURN is pressed, on both ports; the record's "
                   "0x05A is DOS's `turn_class`, which is a property of what "
                   "is being turned, and DOS's own reader takes nothing from "
                   "it either (#297)"),
    ("experience_per_hit_point", "Pools of Darkness' own engine keeps no "
                                 "such byte in any of its records; the "
                                 "later engine adds the base award alone"),
)

#: Neutral fields the game works out for itself on load, which is why writing
#: them would be pointless rather than a loss.  Each row carries the run that
#: demonstrated it in the running game, as
#: `.claude/rules/conversions.md` requires of this category.
POD_WRITE_DERIVED: tuple[tuple[str, str], ...] = (
    ("attack_level", "**this title keeps no such field, and that is read out "
                     "of its own engine** (#462): the two routines that "
                     "derive `thac0_base` -- the derived-fields rebuild at "
                     "0x03C238 and character creation at 0x00EF82 -- index "
                     "one attack table with `22 * class + level` and neither "
                     "reads any other byte of the record. Silver Blades keeps "
                     "an `attack_level` at Amiga 0x080 and this title's "
                     "importer copies nothing into it: 0x080 is "
                     "`paladin_cures` here and 0x082 is `icon_dimension`. So "
                     "there is nothing to write rather than a byte nobody has "
                     "found"),
    ("encumbrance", "the word at 0x056: a probe that set it to 1234 drew 233, "
                    "which is the character's own coins, gems and jewelry"),
    ("thac0_current", "the byte at 0x186: the game recomputes THAC0 from the "
                      "class levels on load and ignores what the file holds"),
    ("armour_class", "the byte at 0x187, the second half of the pair, "
                     "recomputed from what the character is wearing"),
    ("movement_current", "the byte at 0x192: a probe that set it to 99 drew "
                         "the base's 12"),
    ("combat_figure", "the byte at 0x0BD, which the engine assigns when the "
                      "character joins a party and not from the file: the "
                      "join routine at 0x027398 stores 0xFF over whatever "
                      "was there before it appends the record to the roster "
                      "chain, then counts the byte up from 0 to the first of "
                      "the eight marching slots nobody else holds "
                      "(0x0273FE-0x027432). The writer emits the 13 creation "
                      "itself writes, which 17 of the 19 `.pc` files hold. "
                      "**Read out of the engine rather than watched on "
                      "screen**"),
    ("roster_tail", "the nine bytes at 0x188, and no part of them can come "
                    "from a source. The rebuild at 0x019428 -- which *Add "
                    "Character* calls between the `.pc` loader and the roster "
                    "join, and which the encumbrance probe watched run -- "
                    "computes the armour bonus at 0x188 (0x0196E8) and copies "
                    "0x0AD-0x0B2 over 0x18B-0x190 (0x019556-0x0195AE) before "
                    "0x018778 overwrites the damage triple from the readied "
                    "weapon's item-table entry. 0x189 and 0x18A are filled "
                    "from `attack_forms` by a fight's own setup loop "
                    "(0x003972 calling 0x007D5E) and are **0 in 19 of 19** "
                    "`.pc` files, so the zero this writer emits is the zero "
                    "the engine emits"),
)

#: Neutral fields written as a value every record measured holds, rather than
#: from the source.  A Gold Box armour class is a cache that already includes
#: worn armour and a dexterity bonus, and this byte is the one before any of
#: that: 60 - 10 in 19 of 19 `.pc` files -- whose characters all carry items --
#: and in 12 of 12 DOS records.
POD_WRITE_CONSTANTS: tuple[tuple[str, str], ...] = (
    ("armour_class_base", "the unarmoured 60 - 10 at 0x0B3, which is what "
                          "every record on either port holds"),
    ("portrait_head", "Pools of Darkness draws no sheet face on either port "
                      "(#194), but the byte itself is a constant of the "
                      "format rather than a field it has none of: "
                      "`pod_to_neutral` reads it at 0x0B9, the census across "
                      "all nineteen `.pc` files on disk 3 is zero in 19 of "
                      "19, and this writer emits the same zero. `#451` "
                      "(the Amiga Pools of Darkness notes call the combat "
                      "icon a sheet portrait, and describe a menu the title "
                      "has not got) is the confusion this clears up: "
                      "`CHEAD.TLB` and `CBODY.TLB` are the **combat icon** "
                      "(`docs/199-amiga-combat-icons.md`), and the title has "
                      "no sheet portrait at all, CONFIRMED three ways -- "
                      "neither port ships head or body art (52 DOS files and "
                      "55 Amiga ones with no `HEAD*`/`BODY*` among them), "
                      "`goldbox.dos_port.POOLS_OF_DARKNESS` gives the pair a "
                      "width of zero, and the fourteen-and-twelve creation "
                      "menu is cut out of the Amiga engine's own copy of the "
                      "data block that carries it, in 60 bytes otherwise "
                      "byte-identical across four binaries"),
    ("portrait_body", "see `portrait_head`: read at 0x0BA, zero in 19 of 19, "
                      "and written zero here"),
)


def pod_write_field_disposition() -> dict[str, str]:
    """Every neutral field and what this writer does with it.

    The test that keeps this module honest: a field `goldbox/neutral.py` declares
    and this table does not name would be a field silently dropped.  The
    shape is `goldbox/neutral.py`'s, so every direction reports the same way.
    """
    return neutral.disposition(
        POD_WRITE_DIRECT, POD_WRITE_TRANSFORMED + POD_WRITE_WHEN_PRESENT,
        POD_WRITE_DROPPED, "the Amiga's",
        derived=POD_WRITE_DERIVED, constants=POD_WRITE_CONSTANTS)


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
    ("treasure_share", "treasure_share, the .pc's byte at 0x094"),
    ("experience", "experience, the .pc's big-endian longword at 0x044"),
    ("platinum", "platinum, the .pc's big-endian word at 0x04C"),
    ("gems", "gems, the .pc's big-endian word at 0x04E"),
    ("jewelry", "jewelry, the .pc's big-endian word at 0x050"),
    ("movement", "movement, the .pc's byte at 0x088"),
    ("hp_max", "hp_max, the .pc's byte at 0x081"),
    ("hp_current", "hp_current, the .pc's byte at 0x191"),
    ("exceptional_strength",
     "exceptional_strength, the first byte of the pair at 0x07C -- the one "
     "in force, where the six ability pairs keep it in the second"),
    *((k, f"{k}, the current half of its pair at 0x070") for k in ABILITY_KEYS),
    *((k, f"{k}, one of the five saving throws at 0x083") for k in SAVE_KEYS),
    *((k, f"{k}, one of the eight thief skills at 0x08B") for k in THIEF_KEYS),
    # **Two bytes, not one.** The Silver Blades importer copies that title's
    # `armour_class_base` to 0x0B3 and its `armour_class` to 0x187, so a
    # character in plate mail reads the armour class he is wearing and not the
    # unarmoured one every record holds at 0x0B3.
    ("armour_class",
     "armour_class, the .pc's byte at 0x187 in the family's stored "
     "60 - value form -- what the game last computed"),
    ("armour_class_base",
     "armour_class_base, the .pc's byte at 0x0B3, which is the unarmoured "
     "60 - 10 = 50 in 19 of 19 records"),
    ("thac0_base", "thac0_base, the .pc's byte at 0x07F, stored 60 - value"),
    ("paladin_cures", "paladin_cures, the .pc's byte at 0x080: 1 for both "
                      "paladins on the disks and 0 for the other 17"),
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
    ("icon_head", "icon_head, the .pc's byte at 0x0BB, DOS's own numbering "
                  "(#612)"),
    ("icon_body", "icon_body, the .pc's byte at 0x0BC, DOS's own numbering"),
    ("icon_colours", "icon_colours, the six bytes at 0x0BF, DOS's own "
                     "nibble pairs"),
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
    ("inventory", "the twenty-byte item records from 404, read as the later "
                  "Amiga titles' own item node and re-cut to the 63 bytes DOS "
                  "holds, then projected onto the shared sixteen. The count "
                  "is the longword at 0x008, not the stale byte at 0x0C7"),
    ("granted_effects", "the ten-byte effect nodes after the item region, "
                        "chain order, re-cut to the nine a DOS .EFX record "
                        "holds: the id, the duration little-endian, the two "
                        "payload bytes and a NULL next. Everything at "
                        "duration zero goes here whole -- which node is an "
                        "innate property and which a readied item's grant "
                        "cannot be told apart for this title"),
    ("running_effects", "the same nodes when the big-endian duration word at "
                        "0x002 is not zero, re-cut the same way with the "
                        "duration little-endian in game-clock minutes. Its "
                        "byte order is PROBABLE and no node on any disk holds "
                        "a value there"),
    ("lay_on_hands_minutes", "read out of the same chain rather than left in "
                             "running_effects: a node with id 140 holds the "
                             "minutes left in its big-endian duration word, "
                             "and no such node means he may heal now. Every "
                             "Amiga title, this one included, pushes 140 "
                             "for HEAL where DOS Pools of Darkness pushes "
                             "109 (docs/231-where-lay-on-hands-lives.md)"),
)


#: Neutral fields the `.pc` reader takes nothing from, and why.
#:
#: **This is not the writer's :data:`POD_WRITE_DROPPED` and must not be
#: computed from it.**  Reading a byte is free; writing one into a field the
#: loader acts on is a change somebody has to watch in the running game first,
#: so each list says its own.
#:
#: Four kinds of row, and none of them is a decode that has not happened:
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
#:   command is pressed; `goldbox.dos_codec.to_neutral` deliberately reads nothing
#:   from DOS's `turn_class` for the same reason (#297), and this record's own
#:   copy is at 0x05A;
#: * **one field the engine keeps nowhere at all**, and it is `attack_level`:
#:   this title indexes its attack table with the class level and no record
#:   byte takes part, read out of the two routines that fill `thac0_base`
#:   and checked against 19 of 19 records;
#: * **one is a classification rather than a byte.**  `innate_effects` and
#:   `granted_effects` are the same ten-byte nodes, and this title's own list
#:   of built-in effect ids has never been read, so everything that never
#:   expires is converted as a grant and nothing is lost but the label.
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
    ("attack_level", "**this title keeps no such field, and that is read out "
                     "of its own engine** (#462): the two routines that fill "
                     "`thac0_base` -- the derived-fields rebuild at 0x03C238 "
                     "and character creation at 0x00EF82 -- index one attack "
                     "table with `22 * class + level`, where the level is "
                     "`max(class_levels[i], former_class_levels[i])` capped "
                     "at 21, and neither reads any other byte of the record. "
                     "The arithmetic reproduces the stored `thac0_base` of "
                     "19 of 19 `.pc` files. So there is nothing at Amiga "
                     "0x080, where Silver Blades keeps one and this title's "
                     "importer copies nothing: 0x080 is `paladin_cures` here "
                     "and 0x082 is `icon_dimension`. DOS Pools of Darkness "
                     "holds 0 in 52 of 52 of its own, which is the same "
                     "engine keeping no fighting level rather than a field "
                     "nobody has found (#527)"),
    ("innate_effects", "the effect chain is read (#462) and every node that "
                       "never expires goes into `granted_effects` whole, "
                       "because which node is an innate property of the race "
                       "or the class and which a readied item granted cannot "
                       "be told apart for this title: "
                       "`goldbox.dos_codec.INNATE_EFFECTS` is Pool of "
                       "Radiance's id space, and this title's own has never "
                       "been read. The same unknown binds the Curse and "
                       "Silver Blades reader"),
)


def pod_read_dropped() -> tuple[tuple[str, str], ...]:
    """:data:`POD_READ_DROPPED`, as a function so callers need not change."""
    return POD_READ_DROPPED


def pod_field_disposition() -> dict[str, str]:
    """Every neutral field and what the `.pc` **reader** does with it.

    The mirror of :func:`pod_write_field_disposition`, which is the writer's,
    and the test that keeps this half honest: a field `goldbox/neutral.py` declares
    and this names nowhere would be one dropped in silence.

    This reader fills 64 of the 78 neutral fields, and 65 for a character
    with something at duration zero in his chain.  The eleven names it takes nothing from:
    **nine** are fields this *title* stores on neither port, **one** is
    `attack_level`, which its engine works out from the class level rather
    than keeping anywhere, and **one** is `innate_effects`, a label rather
    than a byte, since every effect that never expires is converted as a
    grant.  `docs/124-amiga-port.md` §1 is the map.
    """
    return neutral.disposition(POD_READ_DIRECT, POD_READ_TRANSFORMED,
                               pod_read_dropped(), "the neutral")


def pod_to_neutral(char: PodCharacter | bytes | bytearray) -> NeutralCharacter:
    """One Amiga Pools of Darkness `.pc` in the neutral record.

    The caller `PodCharacter` did not have until 2026-09-08: `write_pod`
    has always turned a neutral character into a `.pc`, and nothing
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
        "treasure_share": (char.treasure_share, FIELD_83_87_SECOND,
                           "treasure_share"),
        "movement": (char.movement, MOVEMENT, "movement"),
        "hp_max": (char.hit_points_max, HP_MAX, "hit_points_max"),
        "hp_current": (char.hit_points_current, HP_CURRENT,
                       "hit_points_current"),
        "exceptional_strength": (char.exceptional_strength,
                                 EXCEPTIONAL_STRENGTH,
                                 "exceptional_strength"),
        # -- what #462 decoded, off the engine's own Silver Blades importer -
        "thac0_base": (char.thac0_base, THAC0_BASE, "thac0_base"),
        "paladin_cures": (char.raw[PALADIN_CURES], PALADIN_CURES,
                          "paladin_cures"),
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
        "icon_head": (char.raw[ICON_HEAD], ICON_HEAD, "icon_head"),
        "icon_body": (char.raw[ICON_BODY], ICON_BODY, "icon_body"),
    }
    for name, (value, offset, key) in scalars.items():
        out.set(name, value, f"Amiga .pc {name} @{offset:#05x} "
                             f"({CONFIDENCE.get(key, 'PROBABLE')})",
                grade(key))

    out.set("icon_colours",
            bytes(char.raw[ICON_COLOURS:ICON_COLOURS + ICON_COLOUR_COUNT]),
            f"Amiga .pc icon_colours @{ICON_COLOURS:#05x} "
            f"({CONFIDENCE.get('icon_colours', 'PROBABLE')})",
            grade("icon_colours"))

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
    # titles, and `goldbox.dos_codec.neutral_class_bits_from` is where it lives).
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
    # **Two bytes, and the Silver Blades importer is what separates them**:
    # that title's `armour_class_base` goes to 0x0B3, which is the unarmoured
    # 50 in every record, and its `armour_class` to 0x187, which is what the
    # character is wearing.
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
            f"highest-first order -- the region fills forwards from its "
            f"first byte and its entries run ascending",
            Confidence.CONFIRMED, neutral.Provenance.RESHAPED)
    out.set("spells_castable", char.spells_castable,
            f"Amiga .pc spell slots @{SPELLS_CASTABLE:#05x}, three "
            f"{SPELL_SLOT_LEVELS}-byte arrays: "
            f"{', '.join(SPELL_SLOT_CLASSES)}",
            Confidence.CONFIRMED, neutral.Provenance.RESHAPED)

    # -- how the character is, and whether the game is still playing them ----
    # A status past the end of the table is not a state the engine can draw,
    # so it is reported rather than turned into the nearest name -- the same
    # rule `goldbox.dos_codec.to_neutral` follows.
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

    # `field_83_87`'s other two bytes -- the class a dual-classed human left
    # (scattered to FIELD_83_87_THIRD) and the byte after it -- have no
    # reader in this title either, so they travel as the window attribute
    # `goldbox.dos_codec.set_window_source` carries for every other port,
    # rather than being dropped over a rewrite (#614).
    _dos.set_window_source(out, char.field_83_87_window)

    # -- size: the Amiga's 1 small / 2 medium, the neutral 0 small / 1 large -
    out.set("size_small", max(0, char.size - 1),
            f"Amiga .pc size @{SIZE:#05x} less one. 1 for the one "
            f"dwarf and 2 for the eighteen humans, elves and half-elves",
            Confidence.PROBABLE, neutral.Provenance.RESHAPED)

    # -- what the character is carrying, and what is running on him ---------
    # The tail past the 404-byte record: twenty bytes an item, ten an effect.
    items, scrolls, effects = char._tail()
    out.set("inventory", [_dos.item_to_c64(it.to_dos_bytes()) for it in items],
            f"the {ITEM_FILE_SIZE}-byte item records from {RECORD_BYTES}, "
            f"read as the later Amiga titles' own item node and re-cut to the "
            f"{dos_port.ITEM_SIZE} DOS holds, projected onto sixteen",
            Confidence.CONFIRMED, neutral.Provenance.RESHAPED)
    if scrolls:
        # A scroll's chained nodes carry three more spell ids each and the
        # neutral record has no field for them. No item in the nineteen
        # genuine files is a scroll, so nothing has ever been dropped here;
        # the line is the accounting rather than a sentence for a player.
        out.drop(f"{len(scrolls)} twenty-byte nodes chained off a scroll: "
                 f"each holds three more spell ids and the neutral record has "
                 f"nowhere to put them")

    # Everything that never expires goes into `granted_effects` whole, and
    # which node is an innate property and which a readied item's grant
    # cannot be told apart for this title: `goldbox.dos_codec.INNATE_EFFECTS`
    # is Pool of Radiance's id space, and this title's own has never been
    # read. The same standing unknown the two later Amiga titles have.
    recut = [pod_effect_to_dos(node) for node in effects]
    granted = [e for e in recut if int.from_bytes(e[1:3], "little") == 0]
    # The paladin's lay-on-hands timer is one more node of the chain, id
    # 140 on the Amiga in every title (docs/231-where-lay-on-hands-lives.md),
    # and it is read into its own field rather than `running_effects`,
    # where a writer would have to remap the id to DOS's 109 rather than
    # copy it.
    heal_node = next((e for e in recut if e[0] == LAY_ON_HANDS_AMIGA_ID
                      and int.from_bytes(e[1:3], "little") != 0), None)
    out.set("lay_on_hands_minutes",
            int.from_bytes(heal_node[1:3], "little") if heal_node else 0,
            (f"a chain node with id {LAY_ON_HANDS_AMIGA_ID}, its duration "
             f"read into game-clock minutes" if heal_node is not None else
             f"no chain node with id {LAY_ON_HANDS_AMIGA_ID}: he may heal "
             f"now"),
            Confidence.CONFIRMED)
    running = [e for e in recut if int.from_bytes(e[1:3], "little") != 0
              and e[0] != LAY_ON_HANDS_AMIGA_ID]
    if running:
        # A node with a duration left is a spell still counting down, kept
        # whole with its time. **No node in the nineteen genuine files has
        # one**: the duration word is zero in 11 of 11, so the byte order of
        # the word at 0x002 has never been read against a value here. It is
        # PROBABLE, from four values elsewhere on the Amiga disks that read
        # as durations big-endian and as 2560 and 1536 little-endian
        # (`docs/124-amiga-port.md`), and unproven.
        out.set("running_effects", running,
                f"the Amiga .pc effect nodes with a duration left, "
                f"{EFFECT_FILE_SIZE} bytes each from the end of the item "
                f"region, re-cut to the nine a DOS .EFX record holds with "
                f"the big-endian word at 0x002 read as game-clock minutes",
                Confidence.PROBABLE, neutral.Provenance.RESHAPED)
    if granted:
        out.set("granted_effects", granted,
                f"the Amiga .pc effect nodes at duration zero, "
                f"{EFFECT_FILE_SIZE} bytes each from the end of the item "
                f"region, re-cut to the nine a DOS .EFX record holds",
                Confidence.PROBABLE, neutral.Provenance.RESHAPED)

    # **No `out.drop` line for a *field*, and that is deliberate rather than
    # an omission.**  `goldbox.dos_codec.to_neutral` and
    # `goldbox.c64_codec.read` each keep a second table --
    # `DROPPED_PLAYER_TEXT`, `READ_DROPPED_PLAYER_TEXT` -- of the sentences a
    # *person* reads, and a name with no sentence in it is shown nothing.
    # This reader has no such table: every sentence a player reads is Donald's
    # to approve (`.claude/rules/gui-text.md`).  The two `out.drop` lines
    # above are the other kind -- a count of records this file holds and the
    # neutral vocabulary has no field for, neither of which any file on the
    # Amiga disks carries -- and they are accounting for the debug log.  The
    # whole contract is stated by :func:`pod_field_disposition` and tested
    # there, so nothing is lost in silence.
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


#: The neutral fields `PodWriter.to_bytes` writes through a `min(...)`, and the
#: largest value each holds.
_POD_CLAMPED_SCALARS = (
    ("thac0_base", 0xFF), ("paladin_cures", 0xFF), ("hp_rolled", 0xFF),
    ("unnamed_0ab", 0xFF), ("npc_control_byte", 0xFF),
    ("experience_award", 0xFFFF),
)


def write_pod(char: NeutralCharacter) -> tuple[PodWriter, Report]:
    """Build a `Save/NAME.pc` writer from a neutral character, and its report.

    Everything the Amiga cannot hold lands in `Report.dropped`; everything it
    holds differently lands in `Report.warnings`.
    A value cut or clamped to fit lands in `Report.losses` as well as in
    `Report.warnings`.
    """
    # The heavier module, for the item and effect re-cuts; this is its only
    # caller on this side.
    from . import dos_codec as _dos

    rep = Report()
    w = neutral.Writer(char, rep, into="Amiga", dropped=POD_WRITE_DROPPED,
                       derived=POD_WRITE_DERIVED, constants=POD_WRITE_CONSTANTS)

    def num(name: str, default: int = 0) -> int:
        """One neutral field as a number, taken and counted as consumed."""
        v = w.use(name)
        return default if v is None else int(v.value)

    def opt(name: str) -> int | None:
        """One neutral field as a number, or None where the source has none."""
        v = w.use(name)
        return None if v is None else int(v.value)

    def flag(name: str, default: bool = False) -> bool:
        v = w.use(name)
        return default if v is None else bool(v.value)

    def raw_opt(name: str) -> bytes | None:
        """One neutral field as bytes, or None where the source has none."""
        v = w.use(name)
        return None if v is None else bytes(v.value)

    name_value = w.use("name")
    name = str(name_value.value if name_value else "").rstrip("\0").strip()
    if not name:
        raise ConversionError("a character with no name cannot be converted")
    if len(name) > NAME_LENGTH:
        rep.lost(
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
    # **A class the character only *was* is not one the class code can hold.**
    # The neutral mask carries a dual-classed character's old class as well
    # as his current one -- `goldbox.dos_codec.neutral_class_bits_from` unions the
    # former level array in, because the C64 needs it -- so the code at 0x059
    # names the class he *is* and the old class's level goes into the former
    # array at 0x0A4, which is where this engine's own dual-class routine
    # puts it.
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
        rep.lost(
            f"Hit points maximum {hp_max} does not fit the Amiga's one byte "
            f"at {HP_MAX:#05x}; clamped to 255")
        hp_max = 0xFF

    lighter = sum(int(w.get(k) or 0)
                  for k in ("copper", "silver", "electrum", "gold"))
    if lighter:
        rep.lost(
            f"{lighter} copper, silver, electrum and gold pieces are left "
            f"behind: only platinum, gems and jewelry have a located home in "
            f"the .pc")

    # Armour class needs no line of its own here: `armour_class_base` is a
    # row of :data:`POD_WRITE_CONSTANTS` and `armour_class` one of
    # :data:`POD_WRITE_DERIVED`, and `neutral.Writer.finish` quotes both --
    # both are now reported as derived rather than dropped.
    #
    # **The guard that keeps the constant honest.** Every source measured --
    # an Amiga source and a DOS Pools of Darkness record alike -- holds
    # `COMBAT_BIAS - UNARMOURED_AC` (50) here, which is what this writer
    # emits regardless of the source. If a source ever holds something else,
    # writing the constant would silently replace the player's own value, so
    # that case is reported as a loss rather than folded into "derived".
    base = w.get("armour_class_base")
    if base is not None and int(base) != COMBAT_BIAS - UNARMOURED_AC:
        rep.lost(
            f"armour_class_base {int(base)} is not the "
            f"{COMBAT_BIAS - UNARMOURED_AC} every record measured holds; "
            f"the .pc's unarmoured base at {ARMOUR_CLASS:#05x} is written "
            f"{COMBAT_BIAS - UNARMOURED_AC} regardless")

    # **The same guard for the portrait pair.** Zero in 19 of 19 `.pc` files
    # on disk 3, and this writer emits zero at both offsets; a source
    # carrying anything else is reported rather than silently replaced.
    for portrait_field, offset in (("portrait_head", PORTRAIT_HEAD),
                                   ("portrait_body", PORTRAIT_BODY)):
        value = w.get(portrait_field)
        if value is not None and int(value) != 0:
            rep.lost(
                f"{portrait_field} {int(value)} is not the 0 every record "
                f"measured holds; the .pc's byte at {offset:#05x} is "
                f"written 0 regardless")

    current = w.use("hp_current")
    if current is None:
        hp_current = hp_max
        rep.warnings.append(
            "No current hit points in the source, so they are set to the "
            "maximum")
    else:
        hp_current = min(int(current.value), hp_max)
        if int(current.value) > hp_current:
            rep.lost(
                f"Hit points current {int(current.value)} is above the "
                f"maximum this record keeps, {hp_max}; written as {hp_current}")

    treasure_share = w.use("treasure_share")

    # -- how the character is, and whether the game is still playing him ----
    # `active` defaults to in the party: 19 of 19 records the game itself
    # wrote hold 1 at 0x184, and 0 is the value the other two ports draw a
    # name red for.
    status_value = w.use("status")
    status = 0
    if status_value is not None:
        word = str(status_value.value).strip().lower()
        if word in neutral.STATUS_NAMES:
            status = neutral.STATUS_NAMES.index(word)
        else:
            rep.dropped.append(
                f"status {word!r}: not one of the game's own "
                f"{len(neutral.STATUS_NAMES)} states, so the record says "
                f"{neutral.STATUS_NAMES[0]}")

    # The neutral 0 small / 1 large is this port's 1 small / 2 medium.
    size_small = opt("size_small")

    # -- the class a dual-classed character left, and the level he left at --
    # The engine's own dual-class routine writes the character level into
    # 0x08A on its way past (`move.b $89(a2), $8a(a2)` at 0x03CD0A), so the
    # highest former class level is what belongs there.
    former_value = w.use("former_levels")
    former = {str(k).strip().lower(): int(v)
              for k, v in (former_value.value if former_value else {}).items()
              if v}
    former_slots: tuple[int, ...] | None = None
    former_level: int | None = None
    if former:
        slots_was = [0] * CLASS_LEVEL_COUNT
        for class_name, level in former.items():
            slot = CLASS_LEVEL_SLOT.get(class_name)
            if slot is None:
                rep.dropped.append(
                    f"the former class {class_name}: Pools of Darkness has no "
                    f"slot for it in the array at {FORMER_CLASS_LEVELS:#05x}")
                continue
            if level > 0xFF:
                rep.lost(
                    f"the former {class_name} level {level} does not fit the "
                    f"Amiga's one byte; clamped to 255")
            slots_was[CLASS_LEVEL_SLOTS.index(slot)] = min(level, 0xFF)
        former_slots = tuple(slots_was)
        former_level = max(slots_was)

    # -- the companion's control byte, bit 7 plus morale --------------------
    npc = flag("npc")
    control = opt("npc_control_byte")
    if control is None and npc:
        control = 0x80

    # `field_83_87`'s third and fourth bytes: read by no site in this
    # title's own engine, so a source that carries its own window (a DOS or
    # Amiga record) gets them back unchanged, rather than the writer's
    # zero -- the same rule every other port follows (#614). Pools of
    # Darkness has no C64 release, so there is no source here with no
    # window at all to fall back on.
    window = _dos.window_source(char)
    field_83_87_third = window[2] if window is not None else None
    field_83_87_fourth = window[3] if window is not None else None

    # -- the permanent half of each ability pair ----------------------------
    second_value = w.use("abilities_second")
    second = dict(second_value.value or {}) if second_value else {}
    permanent = (tuple(int(second.get(k, w.get(k) or 0))
                       for k in ABILITY_KEYS) if second else None)
    permanent_exceptional = (int(second["exceptional_strength"])
                             if "exceptional_strength" in second else None)

    # -- the eight attack-form bytes, which carry the damage triple ---------
    forms_value = w.use("attack_forms")
    forms: tuple[int, ...] | None = None
    if forms_value is not None:
        block = bytes(forms_value.value or b"")
        if len(block) != ATTACK_FORM_COUNT:
            rep.lost(
                f"The source's attack forms are {len(block)} bytes and this "
                f"record keeps {ATTACK_FORM_COUNT}, so it is cut to fit")
        forms = tuple(block[:ATTACK_FORM_COUNT].ljust(ATTACK_FORM_COUNT, b"\0"))

    # -- magic ---------------------------------------------------------------
    book_value = w.use("spells_known")
    book: tuple[int, ...] | None = None
    if book_value is not None:
        ids = sorted({int(i) for i in (book_value.value or ())})
        over = [i for i in ids if not 1 <= i <= SPELLBOOK_BYTES * 8]
        if over:
            rep.dropped.append(
                f"{len(over)} spell ids outside 1-{SPELLBOOK_BYTES * 8}, "
                f"which is what the mask at {SPELLBOOK:#05x} has room for: "
                f"{', '.join(str(i) for i in over)}")
        book = tuple(i for i in ids if i not in over)

    slots_value = w.use("spells_castable")
    castable: dict[str, tuple[int, ...]] | None = None
    if slots_value is not None:
        castable = {}
        for class_name, levels_free in (slots_value.value or {}).items():
            key = str(class_name).strip().lower()
            free = tuple(int(n) for n in levels_free)
            if key not in SPELL_SLOT_CLASSES:
                if any(free):
                    rep.dropped.append(
                        f"{key}'s free spell slots: this record keeps three "
                        f"arrays, {', '.join(SPELL_SLOT_CLASSES)}")
                continue
            if len(free) > SPELL_SLOT_LEVELS:
                rep.dropped.append(
                    f"{key}'s spell levels past {SPELL_SLOT_LEVELS}, which is "
                    f"what this title's array at {SPELLS_CASTABLE:#05x} holds")
                free = free[:SPELL_SLOT_LEVELS]
            castable[key] = free

    memorised_value = w.use("spells_memorised")
    memorised: tuple[int, ...] | None = None
    if memorised_value is not None:
        ids = [int(i) for i in (memorised_value.value or ())]
        over = [i for i in ids if not is_memorised_byte(i)]
        if over:
            rep.dropped.append(
                f"{len(over)} memorised spell ids the region at "
                f"{SPELLS_MEMORISED:#05x} has no room for -- its byte is the "
                f"id with bit 7 as the pending flag, so 1-127 is what fits, "
                f"or 129-255 with the flag set: "
                f"{', '.join(str(i) for i in over)}")
        ids = [i for i in ids if is_memorised_byte(i)]
        if len(ids) > SPELLS_MEMORISED_LENGTH:
            rep.dropped.append(
                f"{len(ids) - SPELLS_MEMORISED_LENGTH} memorised spells past "
                f"the {SPELLS_MEMORISED_LENGTH} the region holds")
            ids = ids[:SPELLS_MEMORISED_LENGTH]
        memorised = tuple(ids)

    # -- what he is carrying, and what is running on him --------------------
    carried_value = w.use("inventory")
    carried: list[bytes] = []
    for entry in (carried_value.value if carried_value else None) or ():
        carried.append(PodItem.from_dos_bytes(
            _dos.item_from_c64(bytes(entry), dos_port.ITEM_SIZE)).raw)
    scrolls = sum(PodItem.from_bytes(node).quantity for node in carried
                  if PodItem.from_bytes(node).is_scroll)
    if scrolls:
        rep.dropped.append(
            f"the spell ids on {scrolls} scroll nodes: the neutral record has "
            f"nowhere to hold them, so the nodes the loader reads after the "
            f"scroll are written empty")

    nodes = _pod_effect_nodes(char, w, rep)

    # `PodWriter.to_bytes` clamps each of these to its width without a word.
    for scalar, top in _POD_CLAMPED_SCALARS:
        held = w.get(scalar)
        if held is not None and int(held) > top:
            rep.lost(
                f"{scalar}: {int(held)} does not fit the Amiga's field, which "
                f"holds up to {top}; clamped")

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
        treasure_share=(None if treasure_share is None
                        else int(treasure_share.value)),
        status=status,
        hostile=flag("hostile"),
        active=flag("active", True),
        quickfight=flag("quickfight"),
        thac0_base=opt("thac0_base"),
        paladin_cures=opt("paladin_cures"),
        hit_points_rolled=opt("hp_rolled"),
        identity=opt("unnamed_0ab"),
        experience_award=opt("experience_award"),
        icon_head=opt("icon_head"),
        icon_body=opt("icon_body"),
        icon_colours=raw_opt("icon_colours"),
        size=(None if size_small is None else size_small + 1),
        npc_control_byte=control,
        former_level=former_level,
        former_class_levels=former_slots,
        field_83_87_third=field_83_87_third,
        field_83_87_fourth=field_83_87_fourth,
        abilities_permanent=permanent,
        exceptional_strength_permanent=permanent_exceptional,
        attack_forms=forms,
        spells_known=book,
        spells_castable=castable,
        spells_memorised=memorised,
        items=tuple(carried),
        effects=tuple(nodes),
    )
    w.finish()
    return writer, rep


def _pod_effect_nodes(char: NeutralCharacter, w: neutral.Writer,
                      rep: Report) -> list[bytes]:
    """The effect chain for this character, one ten-byte node each.

    What the character's own record holds and nothing else: `granted_effects`
    whole, then `innate_effects` as DOS's own `id + INNATE_PAYLOAD` for any id
    the grants do not already carry. **Nothing is derived from a race table**
    -- `goldbox.dos_codec.RACE_COMBAT_EFFECTS` is Pool of Radiance's, and
    writing a dwarf's infravision from it as well as from his own record would
    put the node in the chain twice, which is what `goldbox.dos_codec.write`
    does to an Amiga source (`amiga_later.LATER_EFFECTS_FROM_NEUTRAL`).

    An id already in the chain is skipped rather than written twice, and the
    skip is reported: every reader in the tree fills the two lists as disjoint
    sets, so it has never fired, and a node vanishing in silence is what the
    report line is against.
    """
    from . import dos_codec as _dos

    nodes: list[bytes] = []
    seen: set[int] = set()
    granted = w.use("granted_effects")
    for record in (granted.value if granted else None) or ():
        payload = bytes(record)[:dos_port.EFFECT_SIZE].ljust(
            dos_port.EFFECT_SIZE, b"\0")
        seen.add(payload[0])
        nodes.append(pod_effect_from_dos(payload))
    counting = w.use("running_effects")
    for record in (counting.value if counting else None) or ():
        payload = bytes(record)[:dos_port.EFFECT_SIZE].ljust(
            dos_port.EFFECT_SIZE, b"\0")
        seen.add(payload[0])
        nodes.append(pod_effect_from_dos(payload))
    # The paladin's lay-on-hands timer, id 140 on the Amiga rather than
    # DOS's 109 (docs/231-where-lay-on-hands-lives.md).  Zero minutes writes
    # no node at all, which is what the engine's own HEAL removes.
    heal = w.use("lay_on_hands_minutes")
    if heal is not None and int(heal.value) > 0:
        minutes = int(heal.value)
        payload = (bytes((LAY_ON_HANDS_AMIGA_ID,))
                  + minutes.to_bytes(2, "little") + bytes(2) + bytes(4))
        seen.add(LAY_ON_HANDS_AMIGA_ID)
        nodes.append(pod_effect_from_dos(payload))
    innate = w.use("innate_effects")
    for effect_id in (innate.value if innate else None) or ():
        if int(effect_id) in seen:
            rep.dropped.append(
                f"innate effect {int(effect_id)}: already in the chain as a "
                f"grant, and the engine would apply it twice")
            continue
        seen.add(int(effect_id))
        nodes.append(pod_effect_from_dos(
            bytes((int(effect_id),)) + _dos.INNATE_PAYLOAD + bytes(4)))
    return nodes


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
    """One neutral character as the bytes of a `Save/NAME.pc`.

    404 bytes of record, then twenty a carried item and ten a running effect,
    which is what the loader reads -- and never fewer than the 484 the game's
    own shortest file is, since a record with nothing after it is padded
    rather than cut.
    """
    writer, rep = write_pod(char)
    record = writer.to_bytes()
    rep.total = len(record)
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
    "damage": "nothing -- unarmed 1d2 where the source has no attack forms",
    "armour_class": "nothing -- the unarmoured 10 every record on either "
                    "port holds",
    "level": "level",
    "saving_throws": "save_paralysis..save_spell",
    "thief_skills": "thief_pick_pockets..thief_read_languages",
    "class_bits": "class_bits",
    "treasure_share": "treasure_share",
    "status": "status",
    "hostile": "hostile",
    "active": "active",
    "quickfight": "quickfight",
    "thac0_base": "thac0_base",
    "paladin_cures": "paladin_cures",
    "hit_points_rolled": "hp_rolled",
    "identity": "unnamed_0ab",
    "experience_award": "experience_award",
    "size": "size_small",
    "npc_control_byte": "npc_control_byte",
    "former_level": "former_levels, the highest of them",
    "former_class_levels": "former_levels",
    "abilities_permanent": "abilities_second",
    "exceptional_strength_permanent": "abilities_second",
    "attack_forms": "attack_forms",
    "spells_known": "spells_known",
    "spells_castable": "spells_castable",
    "item_count": "inventory, how many items follow",
    "effect_chain": "granted_effects and innate_effects, non-zero when a "
                    "node follows",
    "icon_head": "icon_head",
    "icon_body": "icon_body",
    "icon_colours": "icon_colours",
}


def export_party(save_path, out_dir, game_disk=None) -> list[tuple]:
    """A whole C64 party from a save disk into a `SAVE` drawer full of
    `.pc` files.

    Returns one `(path, Report)` per character. The C64 disk is opened
    read-only; `out_dir` is created if it is not there.  `game_disk` is
    accepted and unused: it names items, and this route reads none from
    the C64 disk (`c64_codec.read` is called without an `inventory`), so the
    writer is given none to emit.
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
