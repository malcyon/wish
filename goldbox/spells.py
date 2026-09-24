"""The spell name table, and what a memorised spell list means.

A character's memorised spells are a packed list of **spell ids** at record
offset `0x020`, and the names live on the game disk. *Where* on the disk is the
one thing that does not transfer between titles, so this module is a table per
title -- the shape `goldbox/c64_port.py` settled on -- and every entry point takes an
optional `game`.

| | Pool of Radiance | Curse of the Azure Bonds | Secret of the Silver Blades |
|---|---|---|---|
| file | `SPELLN00` | `COMBAT2` | `COMBAT2` |
| resident at | `$B000` | `$E000` | `$E000` |
| entries | 128 | 170 | 194 |
| order | 128 low bytes, 128 high bytes, then the strings | the strings, then 170 high bytes, then 170 low bytes | the same as Curse |
| index of spell *n* | *n* | *n - 1* | *n - 1* |
| spells run to | 56 | 100 | 117 |
| spellbook mask | 7 bytes | 13 | 16 |

Neither file's PRG header helps: `SPELLN00` declares `$2710`, which is a
scratch buffer. Curse's base needs no fitting at all -- the pointer for index 0
is `$E000` and the text runs `$E000`-`$E7DA`, exactly the range of high bytes
the array holds. Silver Blades' is the same file in the same shape with a
longer text block: `$E000`-`$E877`, 194 entries, and 193 of its 194 pointers
land on a string start where no neighbouring entry count scores better than
167. **The method was validated on Curse first**, where it recovers the
already-known 170 / `$07DB` / `$0885` exactly.

**Read through the pointers, never by splitting on NULs.** The strings overlap.
`CURE LIGHT WOUNDS` and `CAUSE LIGHT WOUNDS` share one copy of ` LIGHT WOUNDS`
in both games; Curse adds `SHIELD` as the tail of `FIRE SHIELD` and
`INVISIBILITY` as the tail of `DETECT INVISIBILITY`, so splitting its block
yields 150 strings for 169 names and goes wrong from id 11 onward.

**Ids 1-56 are the same spell in both games**, read off Curse's own table
rather than inferred, which is what makes an imported spellbook mean what it
said: bit 20 is `SHOCKING GRASP` either side. Past its own last spell each
table continues with combat message fragments -- `AND MISSES...`,
`POINTS OF DAMAGE` -- which share the mechanism and not the meaning: Pool of
Radiance from 57, Curse from 101, Silver Blades from 118.

**Silver Blades keeps 54 of those 56 and reassigns two**: 36 is `HEAL` where
the other two have `ANIMATE DEAD`, and 56 is `HARM` where they have
`RESTORATION`. That is the game's own doing and not a misread stride -- its
`GEN` spell-grant table sets exactly those two bits, and only those two, when a
cleric reaches level 11 with wisdom 17 or better, which is when and how AD&D
1st edition grants sixth-level clerical spells. An import from another title
therefore carries a spellbook whose bits 36 and 56 change meaning, and nothing
here rewrites them.

**`SPELLN64` is not a spell-name table in either game**, whatever its stem
suggests. It is 1878 bytes of icon-editor menu strings, and both titles ship
it. Curse ships no `SPELLN00` at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import levels
from .d64 import D64, load_payload


@dataclass(frozen=True)
class SpellTable:
    """Where a title keeps its spell names, and what the ids mean.

    All six offsets are *payload* offsets -- the PRG's two-byte load address
    already peeled off. `text_offset` is where the strings begin and
    `text_end` where they stop; the pointer arrays sit on whichever side of
    them the title chose.

    Pairs rather than dicts in `groups`, so the descriptor stays frozen and
    hashable, which is what `goldbox/c64_port.py` does for the same reason.
    """

    key: str
    title: str
    file: bytes
    entries: int
    resident_base: int
    text_offset: int
    low_offset: int
    high_offset: int
    first_id: int                 # the spell id of table index 0
    last_spell: int               # past this the table is combat messages
    #: `(first id, last id, class, spell level)`, in id order.
    groups: tuple[tuple[int, int, str, int], ...] = ()
    #: Ids inside the spell range that are not spells: unused slots, and the
    #: handful of combat messages Curse mixes in among its new spells.
    not_a_spell: tuple[int, ...] = ()
    #: How many bytes of the spellbook bitmask at record `0x078` this title
    #: uses. Measured per title -- the evidence is the comment above
    #: `POOL_OF_RADIANCE` below. **Zero means the title has no such mask**,
    #: which is a title with no C64 port: `spells_known` and `spellbook_bytes`
    #: refuse it rather than reading sixteen unrelated bytes.
    spellbook_size: int = 7
    #: How many spell ids the record records when it keeps **one byte per id**
    #: instead of a bitmask. Pools of Darkness' DOS record has 126 such bytes
    #: at `0x0B3`-`0x130`, so it records every id 1-126;
    #: zero means the title uses the mask and `spellbook_size` answers.
    spellbook_ids: int = 0
    #: Ids that fall in one of the groups above and that the title's **trainer**
    #: never hands out, so a level-up must not either. Pool of Radiance has
    #: none: `GEN $20CF` ORs a whole spell level into the mask rather than
    #: reading a table, so a cleric who can cast a level knows all of it.
    #: Curse replaced that with a per-level table and left three ids out of it,
    #: one of them not a cleric spell at all -- see `CURSE_OF_THE_AZURE_BONDS`
    #: below. CONFIRMED.
    not_granted: tuple[int, ...] = ()
    #: `(class level, spell level)` pairs, lowest first, each naming the class
    #: level at which the trainer's **magic-user menu** starts offering that
    #: spell level. Empty where the title computes it arithmetically, which is
    #: Pool of Radiance's `GEN $215A` and Curse's `$2200`: both are
    #: `LSR A / ADC #$00`, `(level + 1) // 2`. Silver Blades' `$1896` reads a
    #: table instead and the two disagree at levels 11, 13 and 15. CONFIRMED,
    #: `tools/c64/trainerspells.py --check` (#89).
    menu_spell_level: tuple[tuple[int, int], ...] = ()
    #: `(class level, minimum intelligence)` pairs for the same menu: a
    #: magic-user short of the score drops to the highest level it does reach.
    #: The score is the **permanent** one at `0x066`, not the score in force.
    #: Empty where the title asks nothing of intelligence, which is both of
    #: the earlier ones. CONFIRMED, `GEN $18AA LDA $7C66 / CMP $1917,X`.
    menu_intelligence: tuple[tuple[int, int], ...] = ()
    #: `(cleric level, spell level)` pairs for the cleric grant. Empty where
    #: the title's spell-slot tables already say it -- Pool of Radiance and
    #: Curse, where `goldbox.spells.capacity` answers and is checked against
    #: the game's own grant rows. Silver Blades has no slot tables read yet
    #: and its grant table is where the answer is.
    cleric_grant_level: tuple[tuple[int, int], ...] = ()
    #: `(cleric level, minimum wisdom)`: from that level the grant asks for
    #: the score and drops one row short of it otherwise. Silver Blades'
    #: `GEN $0F39 LDA $7C67 / CMP #$11` is the only one in the family, and the
    #: score is again the permanent one, at `0x067`.
    cleric_grant_wisdom: tuple[int, int] = ()
    #: `(paladin level, cleric level)` pairs: a paladin jumps into the
    #: cleric's own grant loop, and this is the cleric level it enters at.
    #: Curse fixes it (`$22FF LDX #$01`), so a paladin of 11 is still on the
    #: cleric's first row and one pair covers the title; Silver Blades enters
    #: at `paladin level - 8` (`$1BF6 SBC #$08 / TAX`), so it climbs a cleric
    #: level a level. Empty for a title with no paladin.
    paladin_cleric_level: tuple[tuple[int, int], ...] = ()
    #: `(ranger level, (druid spell level, magic-user spell level))` pairs.
    #: AD&D 1st edition's ranger exactly: druid spells at 8, magic-user spells
    #: at 9, and in Silver Blades the second of each at 12 and 13. Empty for a
    #: title with no ranger. CONFIRMED in both, `GEN $2305` and `$0EFC`.
    ranger_spell_level: tuple[tuple[int, tuple[int, int]], ...] = ()

    @property
    def text_end(self) -> int | None:
        """Where the strings stop, or None when they run to the file's end."""
        after = [o for o in (self.low_offset, self.high_offset)
                 if o >= self.text_offset]
        return min(after) if after else None

    @property
    def last_spellbook_spell(self) -> int:
        """The highest id the mask has a bit for *and* the title has a spell for.

        Two ceilings, and the lower wins. Pool of Radiance's mask stops one id
        short of its own spell list -- seven bytes is 56 bits, ids 0-55, and id
        56 is RESTORATION, which the game can memorise and cannot record
        knowing. The two later titles have bits to spare instead, and Pools of
        Darkness stops at 125 the same way Pool of Radiance stops at 55: its
        spellbook is a byte an id and its spell list runs to 126.
        """
        if self.spellbook_ids:
            return min(self.spellbook_ids, self.last_spell)
        return min(self.spellbook_size * 8 - 1, self.last_spell)

    def in_spellbook(self, spell_id: int) -> bool:
        """Can this id be in a spellbook at all? Bit 0 is not a spell."""
        return (1 <= spell_id <= self.last_spellbook_spell
                and spell_id not in self.not_a_spell)


#: The table runs cleric level 1, magic-user level 1, cleric level 2, and so
#: on, each group alphabetical with a reversed spell following the one it
#: reverses (`CURE LIGHT WOUNDS` then `CAUSE LIGHT WOUNDS`). The boundaries are
#: where that alphabetical run restarts, and every spell id observed in a real
#: save falls in the group its caster's class predicts.
_GROUPS_POOL = (
    (1, 8, "cleric", 1),
    (9, 21, "magic-user", 1),
    (22, 28, "cleric", 2),
    (29, 35, "magic-user", 2),
    (36, 44, "cleric", 3),
    (45, 55, "magic-user", 3),
)

#: Curse repeats Pool of Radiance's six groups and adds six. Those six are
#: PROBABLE and no better: they are AD&D's spell levels read off the names, not
#: a table in the game. 58 and 100 sit on their own because combat messages and
#: unused slots landed in the middle of the new spells.
_GROUPS_CURSE = _GROUPS_POOL + (
    (58, 58, "cleric", 4),
    (66, 70, "cleric", 4),
    (71, 76, "cleric", 5),
    (77, 80, "druid", 1),
    (81, 90, "magic-user", 4),
    (91, 94, "magic-user", 5),
    (100, 100, "cleric", 4),
)

#: Ids inside 1-100 that name no spell. 57, 59-62, 98 and 99 are combat
#: messages -- `IS BERSERKING`, `IS DYING` -- sitting among the new spells;
#: 63-65 and 95-97 are unused slots, and an unused slot points at `$E000`, so
#: it reads back as `BLESS`.
#:
#: `docs/116` §10 puts the message tail at 101. It starts at 98: `IS ALIVE` and
#: `IS DYING` are messages, and 100, the one after them, is `BESTOW CURSE`.
_NOT_A_SPELL_CURSE = (57, 59, 60, 61, 62, 63, 64, 65, 95, 96, 97, 98, 99)

#: Silver Blades, and these are **read out of the game's own grant tables**
#: rather than off the names. `GEN` carries three of them, each a (mask byte
#: index, bit mask) pair list walked backwards from a per-level ceiling:
#:
#: * the cleric's, entered on record `0x0CA`, gives 1-8, 22-28, 37-44,
#:   {58, 66-70}, 71-76 at levels 1, 3, 5, 7, 9 -- AD&D's cleric progression
#:   exactly -- and {36, 56} at level 11 behind a wisdom-17 check
#:   (`LDA $7C67 / CMP #$11`, the *second* ability array's wisdom, and a
#:   character below it is clamped back to the level-10 row);
#: * the ranger's, entered on record `0x0D0` and gated at `CPX #$08`, gives
#:   77-80 at level 8 and 9-21 at level 9. A ranger getting druid spells at 8
#:   and magic-user spells at 9 is AD&D 1st edition verbatim, and the shipped
#:   PAINE holds precisely those four druid bits and nothing else. **Curse
#:   does the same thing without a table**, at `$2305`: `LDX #$07` for the
#:   ranger's class slot, `CMP #$08`, then immediate `ORA` constants for the
#:   same ids. `ranger_spell_level` below is the pair of spell levels both
#:   titles reach, which is why neither one's bytes are copied here;
#: * the magic-user's, entered on record `0x0C9`, is a learn-list rather than a
#:   whole level. Its level-9 row is the shipped MORGAINE's spellbook exactly,
#:   id for id -- **which is what a *starting* spellbook looks like, and this
#:   is one.** `$0F7C`'s only caller is the tail of `$0EF3`, reached from
#:   character creation and from the dual-class routine, and the level-up
#:   sequence at `$14FA` never touches it. The trainer's own magic-user step
#:   is the menu at `$1896`, and Curse's `$167F` is the same routine misread
#:   the same way (#89).
#:
#: All three are read mechanically out of `GEN` by
#: `tests/secret_of_the_silver_blades/test_silverblades.py::_grant_table`, which is Curse's extraction with
#: the one difference that Silver Blades indexes `$7C78,X` by *byte number*
#: where Curse indexes `$7C00,X` by record offset. **CONFIRMED**: the cleric
#: and ranger rows are the game's own table, not a reading of the names.
#:
#: The magic-user *levels* below are still the weaker claim -- PROBABLE, read
#: off the names against AD&D as Curse's were. The grant list says which ids a
#: magic-user may learn; it does not say which AD&D spell level each is.
_GROUPS_SILVER_BLADES = (
    (1, 8, "cleric", 1),
    (9, 21, "magic-user", 1),
    (22, 28, "cleric", 2),
    (29, 35, "magic-user", 2),
    (36, 36, "cleric", 6),
    (37, 44, "cleric", 3),
    (45, 55, "magic-user", 3),
    (56, 56, "cleric", 6),
    (58, 58, "cleric", 4),
    (66, 70, "cleric", 4),
    (71, 76, "cleric", 5),
    (77, 80, "druid", 1),
    (81, 89, "magic-user", 4),
    (90, 90, "druid", 2),
    (91, 94, "magic-user", 5),
    # 90 BARKSKIN, 96 CHARM PERSON OR MAMMAL and 98 CURE LIGHT WOUNDS are one
    # group, and the ranger grant table is why: its level-12 row hands out all
    # three together, where 77-80 arrive at 8 and 29-35 at 13. **That much is
    # CONFIRMED** and read out of `GEN` by
    # `tests/secret_of_the_silver_blades/test_silverblades.py::test_the_ranger_grant_reaches_druid_2`.
    # That the level is *2* is PROBABLE and no better: it is AD&D 1st edition's
    # ranger, who gets first-level druid spells at 8 and second-level at 12,
    # read against the table rather than out of it. Curse's `ECL65` spell-slot
    # rows would settle it if Silver Blades' equivalent were found. 96 was read
    # off its name as druid 1 and is corrected here; 98 had no group at all, so
    # `spell_group` called a spell the game itself grants no spell.
    (96, 96, "druid", 2),
    (98, 98, "druid", 2),
    (109, 114, "magic-user", 6),
    (115, 117, "magic-user", 7),
)

#: Ids inside 1-117 that name no spell. Two kinds, and the tail of the table
#: tells them apart: 59-62, 97 and 99 are combat messages -- `IS BERSERKING`,
#: `IS ALIVE`, `IS DYING` -- and the rest are unused slots whose pointer
#: duplicates a real entry's, so they read back as a spell that is already
#: somewhere else. 101-108 are eight consecutive slots all reading `TRIP`.
#: 98 is deliberately **not** here: the ranger grant sets it, so it is the
#: druid's own `CURE LIGHT WOUNDS` and not a duplicate of id 3.
_NOT_A_SPELL_SILVER_BLADES = (57, 59, 60, 61, 62, 63, 64, 65, 95, 97, 99, 100,
                              101, 102, 103, 104, 105, 106, 107, 108)

#: The one id inside a group that the trainer's menu never offers. 109 and 110
#: are both `DEATH SPELL` -- a duplicate the way 105-108 are all `TRIP` -- and
#: `GEN $1896` builds its candidate mask out of `$1936`/`$1942`, whose
#: sixth-level row is byte 13 mask `$C0` and byte 14 mask `$07`: ids 110-114
#: and not 109. So a Silver Blades magic-user reaching level 12 is offered
#: five sixth-level spells rather than six. CONFIRMED,
#: `tools/c64/trainerspells.py --check` (#89).
_NOT_GRANTED_SILVER_BLADES = (109,)

#: How wide the spellbook bitmask at record `0x078` is, per title. **Measured
#: in each game's own code, not carried across from another one.**
#:
#: Every address in this block was written at the overlay's PRG header base
#: until 2026-09-02 and named the wrong bytes -- **five of the seven fell
#: outside the overlay entirely**, measured against each file's real extent.
#: `GEN` and `CAMP` run at `$0800` in all three titles. The findings were
#: right and only the addresses were unusable; `#31 (Cold-read Curse and
#: Silver Blades for the fields the editor shows)` corrected them, and
#: `tests/c64/test_coldread.py` now reads the opcodes off the disks so it cannot
#: happen again.
#:
#: The one thing that looks like proof and is not: Curse's `GEN $220F` copies 32 bytes
#: out of `$7C78` -- and Pool of Radiance's `GEN $216B` copies the identical 32
#: out of `$6B78`, where the mask is seven. A copy that is wider than the field
#: says nothing about the field.
#:
#: What each title's own code does with the mask:
#:
#: * **Pool of Radiance, 7 -- CONFIRMED.** Seven bytes is 56 bits and its spell
#:   list runs to 56, of which id 56 (`RESTORATION`) has no bit. The QUANTUM
#:   LEAPER trainer's LEARN ALL SPELLS writes `$FE` and six `$FF`, which is the
#:   same claim in somebody else's hand, and no character in any Pool of
#:   Radiance save sets `0x07D`, `0x07E` or `0x07F`.
#: * **Curse of the Azure Bonds, 13 -- CONFIRMED.** `CAMP $2A25` builds the
#:   list of spells a character may memorise by walking spell ids from 1 with
#:   `INY / CPY #$65 / BCC`, so it stops after id 100, and it reads the mask as
#:   `TYA / LSR / LSR / LSR / TAX / LDA $7C78,X`. Id 100 puts X at 12, so the
#:   game itself reads `0x078`-`0x084`. `GEN $232A` writes there too, ORing
#:   `$E0` into `$7C81` and `$01` into `$7C82` to grant the four first-level
#:   druid spells 77-80. Curse's `GEN` has no clear loop, so **whether bytes
#:   `0x085`-`0x087` are also the mask is UNKNOWN**; thirteen is what the game
#:   reads, and no more is claimed.
#: * **Secret of the Silver Blades, 16 -- CONFIRMED**, and by three
#:   independent sightings. `GEN $09DC` clears sixteen bytes --
#:   `LDX #$0F / LDA #$00 / STA $7C78,X / DEX / BPL`. `GEN $18C9` walks the
#:   same sixteen. `CAMP $2871` is Curse's memorise loop with the ceiling moved
#:   to `CPY #$76`, id 117, which reads as far as `0x086`.
#:
#: The pattern is ceil(last spell / 8) rounded up to what the title cleared:
#: Curse needs 13 for its 100 and Silver Blades 15 for its 117, and Silver
#: Blades zeroes 16.

POOL_OF_RADIANCE = SpellTable(
    key="pool-of-radiance",
    title="Pool of Radiance",
    file=b"SPELLN00",
    entries=128,
    resident_base=0xB000,
    text_offset=0x100,
    low_offset=0x000,
    high_offset=0x080,
    first_id=0,
    last_spell=56,
    groups=_GROUPS_POOL,
    spellbook_size=7,
)

CURSE_OF_THE_AZURE_BONDS = SpellTable(
    key="curse-of-the-azure-bonds",
    title="Curse of the Azure Bonds",
    file=b"COMBAT2",
    entries=170,
    resident_base=0xE000,
    text_offset=0x000,
    high_offset=0x7DB,
    low_offset=0x885,
    first_id=1,
    last_spell=100,
    groups=_GROUPS_CURSE,
    not_a_spell=_NOT_A_SPELL_CURSE,
    spellbook_size=13,
    # 36 ANIMATE DEAD and 100 BESTOW CURSE. `GEN`'s own cleric grant table --
    # the one `tests/curse_of_the_azure_bonds/test_curse.py::_cleric_grant_table` reads out of the bytes --
    # hands out 1-8, 22-28, 37-44, {58, 66-70} and 71-76 at levels 1, 3, 5, 7
    # and 9, and stops. Both ids are in a cleric group because both are cleric
    # spells; neither is ever granted at a temple, and a player meets them on a
    # scroll. Pool of Radiance grants 36 to any cleric who can cast level 3,
    # which is the difference between ORing a spell level and reading a table.
    #
    # 90, the *magic-user* ANIMATE DEAD, belongs here too and the pattern above
    # did not catch it because it is not a cleric spell. The trainer's own
    # spell-level table at `GEN $273F` gives every id's magic-user spell level,
    # 9 meaning never offer it, and marks id 90 with a 9 the same as the two
    # cleric ids above -- read mechanically by
    # `tests/curse_of_the_azure_bonds/test_cursetrainer.py::test_the_trainers_own_spell_level_table_
    # agrees_with_goldbox_spells` (#18, #223).
    not_granted=(36, 90, 100),
    # `GEN $22F4` and `$2305`, the fourth and fifth steps of Curse's level-up
    # sequence at `$205E`. The paladin's jumps into the cleric's own grant
    # loop with `LDX #$01`, so it never moves off the cleric's first row
    # however high a paladin climbs; the ranger's is two blocks of immediate
    # `ORA` constants, `$2329` for the four first-level druid spells at 8 and
    # `$2318` for the thirteen first-level magic-user spells at 9. Curse's
    # ceilings are 11 for both, so neither table has anywhere further to go.
    # CONFIRMED, `tools/c64/trainerspells.py --check` (#89).
    paladin_cleric_level=((9, 1),),
    ranger_spell_level=((8, (1, 0)), (9, (1, 1))),
)

SECRET_OF_THE_SILVER_BLADES = SpellTable(
    key="secret-of-the-silver-blades",
    title="Secret of the Silver Blades",
    file=b"COMBAT2",
    entries=194,
    resident_base=0xE000,
    text_offset=0x000,
    high_offset=0x878,
    low_offset=0x93A,
    first_id=1,
    last_spell=117,
    groups=_GROUPS_SILVER_BLADES,
    not_a_spell=_NOT_A_SPELL_SILVER_BLADES,
    spellbook_size=16,
    not_granted=_NOT_GRANTED_SILVER_BLADES,
    menu_spell_level=((1, 1), (3, 2), (5, 3), (7, 4), (9, 5), (12, 6),
                      (14, 7)),
    menu_intelligence=((12, 12), (14, 14)),
    cleric_grant_level=((1, 1), (3, 2), (5, 3), (7, 4), (9, 5), (11, 6)),
    cleric_grant_wisdom=(11, 17),
    paladin_cleric_level=((9, 1), (10, 2), (11, 3), (12, 4), (13, 5),
                         (14, 6), (15, 7)),
    ranger_spell_level=((8, (1, 0)), (9, (1, 1)), (12, (2, 1)), (13, (2, 2))),
)

#: Pools of Darkness' own class and level bytes, one entry a spell id, read
#: out of the engine's 16-byte spell table at `DS:651A` in the DOS build by
#: `tools/dos/dospodtables.py spells` -- byte 0 the casting class (0 cleric,
#: 1 druid, 2 magic-user, 3 no class) and byte 1 the spell level. So these
#: are **not** a reading of names against AD&D: they are what the fourth
#: engine itself says each id is, for all 126 ids its builder walks
#: (`cmp byte ptr [bp-5], 0x7e / jne`). CONFIRMED, and
#: `tests/records/test_pod_spells.py` reads them back off the player's own
#: game.
#:
#: Three of them settle what `_GROUPS_SILVER_BLADES` above grades PROBABLE --
#: 36 and 56 are cleric 6, and 115-117 magic-user 7 -- and one corrects a
#: reading: **109 is a druid 3 spell**, not the magic-user 6 duplicate
#: `_NOT_GRANTED_SILVER_BLADES` explains it away as. Silver Blades' trainer
#: was not skipping a magic-user spell; 109 was never a magic-user spell.
_GROUPS_POOLS_OF_DARKNESS = (
    (1, 8, "cleric", 1),
    (9, 21, "magic-user", 1),
    (22, 28, "cleric", 2),
    (29, 35, "magic-user", 2),
    (36, 36, "cleric", 6),
    (37, 44, "cleric", 3),
    (45, 55, "magic-user", 3),
    (56, 56, "cleric", 6),
    (58, 58, "cleric", 4),
    (66, 70, "cleric", 4),
    (71, 76, "cleric", 5),
    (77, 80, "druid", 1),
    (81, 89, "magic-user", 4),
    (90, 90, "druid", 2),
    (91, 94, "magic-user", 5),
    (96, 96, "druid", 2),
    (98, 98, "druid", 2),
    (100, 100, "magic-user", 4),
    (101, 101, "cleric", 6),
    (102, 105, "cleric", 7),
    (106, 109, "druid", 3),
    (110, 114, "magic-user", 6),
    (115, 117, "magic-user", 7),
    (118, 119, "magic-user", 5),
    (120, 123, "magic-user", 8),
    (124, 126, "magic-user", 9),
)

#: The eleven ids in 1-126 whose class byte is 3, which is the engine's own
#: mark for a combat message or an unused slot. 115 spells and eleven
#: non-spells, and no id is left without a group.
_NOT_A_SPELL_POOLS_OF_DARKNESS = (57, 59, 60, 61, 62, 63, 64, 65, 95, 97, 99)

POOLS_OF_DARKNESS = SpellTable(
    key="pools-of-darkness",
    title="Pools of Darkness",
    # No C64 port: this title shipped for DOS and the Amiga, so there is no
    # `SPELLN`-style name file, no resident base and no pointer array to
    # name, and a zero `spellbook_size` says the record has no bitmask at
    # `0x078` either. `load_spell_names` has nothing to read for it and the
    # two mask helpers refuse it rather than answering from the wrong bytes.
    file=b"",
    entries=0,
    resident_base=0,
    text_offset=0,
    low_offset=0,
    high_offset=0,
    first_id=1,
    last_spell=126,
    groups=_GROUPS_POOLS_OF_DARKNESS,
    not_a_spell=_NOT_A_SPELL_POOLS_OF_DARKNESS,
    spellbook_size=0,
    # The DOS record's own 126 bytes at `0x0B3`-`0x130`, one an id, which the
    # engine writes with `mov byte ptr es:[di + 0xb2], 1`, `di` the spell id,
    # so id 126 lands on `0x130`; every id loop in `GAME.OVR` runs to 126. The
    # Amiga record keeps the same set as a sixteen-byte
    # mask at `0x159` instead, and a conversion has to translate between the
    # two encodings rather than copy either.
    spellbook_ids=126,
)

TITLES: tuple[SpellTable, ...] = (POOL_OF_RADIANCE, CURSE_OF_THE_AZURE_BONDS,
                                  SECRET_OF_THE_SILVER_BLADES,
                                  POOLS_OF_DARKNESS)
BY_KEY = {t.key: t for t in TITLES}

#: What a caller gets when it says nothing. Every caller predates the second
#: game and means this one.
DEFAULT = POOL_OF_RADIANCE


def for_game(game=None) -> SpellTable:
    """The spell table for a title.

    Takes a `goldbox.c64_port.C64Container`, a game key, a `SpellTable`, or None. Duck-typed
    on `.key` rather than importing `goldbox.c64_port`, which would be a whole module
    of coupling for one string.
    """
    if isinstance(game, SpellTable):
        return game
    return BY_KEY.get(getattr(game, "key", game), DEFAULT)


# --- backwards compatibility -------------------------------------------------
# Every caller outside this module predates the second game and means Pool of
# Radiance. These stay so that none of them has to say so.
SPELL_NAMES_FILE = POOL_OF_RADIANCE.file
NAMES_TABLE_ENTRIES = POOL_OF_RADIANCE.entries
NAMES_HIGH_BYTES = POOL_OF_RADIANCE.high_offset
NAMES_TEXT = POOL_OF_RADIANCE.text_offset
NAMES_RESIDENT_BASE = POOL_OF_RADIANCE.resident_base
SPELL_GROUPS = _GROUPS_POOL
#: RESTORATION. A cleric spell far above anything Pool of Radiance grants a
#: player, so it is presumably the temple's, and its level is not worth
#: guessing.
SPELL_RESTORATION = 56
LAST_SPELL = POOL_OF_RADIANCE.last_spell


def load_spell_names(disk: D64 | str, game=None) -> dict[int, str]:
    """Every string in the title's name table, keyed by spell id.

    Includes the non-spell tail: what a caller wants is usually
    `{k: v for k, v in load_spell_names(d).items() if k <= LAST_SPELL}`, but
    the messages are read the same way and there is no reason to hide them.
    """
    table = for_game(game)
    payload = load_payload(disk, table.file)
    end = table.text_end if table.text_end is not None else len(payload)
    out: dict[int, str] = {}
    for index in range(table.entries):
        if table.low_offset + index >= len(payload):
            break
        address = (payload[table.low_offset + index]
                   | payload[table.high_offset + index] << 8)
        start = address - table.resident_base + table.text_offset
        if not table.text_offset <= start < end:
            continue                      # unused slot
        stop = payload.find(b"\x00", start)
        if stop < 0:
            continue
        text = payload[start:stop].decode("latin1")
        if text:
            out[index + table.first_id] = text
    return out


def spell_group(spell_id: int, game=None) -> tuple[str, int] | None:
    """(class, spell level) for a spell id, or None if it is not a spell."""
    table = for_game(game)
    if spell_id in table.not_a_spell:
        return None
    for low, high, cls, level in table.groups:
        if low <= spell_id <= high:
            return cls, level
    return None


def describe(spell_id: int, names: dict[int, str] | None = None,
             game=None) -> str:
    """`SLEEP (magic-user 1)` -- the form a person wants to read."""
    name = (names or {}).get(spell_id) or f"spell {spell_id}"
    group = spell_group(spell_id, game)
    return f"{name} ({group[0]} {group[1]})" if group else name


# --- the spellbook -----------------------------------------------------------
# The bitmask at record 0x078 of the spells a character *knows*, indexed by
# spell id: bit (id & 7) of byte 0x078 + (id >> 3). How many bytes long it is
# is the title's business and is `SpellTable.spellbook_size`; the constants
# here are Pool of Radiance's, for the callers that predate the second title.
#
# Confirmed on every caster we hold. Clerics know every spell of every level
# they can cast -- eight at level 1, twenty-four at level 6 -- and magic-users
# know a subset, which is exactly how AD&D 1st edition works. Every id set for
# a cleric falls in a cleric group and every id set for a magic-user in a
# magic-user group, with no crossover anywhere.
#
# Bit 0 of 0x078 is deliberately unused -- spell id 0 does not exist. The
# QUANTUM LEAPER trainer's LEARN ALL SPELLS writes $FE to 0x078 and $FF to the
# other six, which is that fact in someone else's hand.
SPELLBOOK_OFFSET = 0x078
SPELLBOOK_SIZE = POOL_OF_RADIANCE.spellbook_size                      # 7
LAST_SPELLBOOK_SPELL = POOL_OF_RADIANCE.last_spellbook_spell          # 55

# Spells castable per level, before Wisdom bonuses, from the game's own tables:
# Pool of Radiance `GEN` $222C (cleric) and $224C (magic-user), eight rows of
# four; Curse `ECL65` payload 0x88D, eleven magic-user rows of five then ten
# cleric rows. Index by level - 1.
_MAGIC_USER = [(1, 0, 0), (2, 0, 0), (2, 1, 0), (3, 2, 0), (4, 2, 1),
               (4, 2, 2), (4, 3, 2), (4, 3, 3), (4, 3, 3), (4, 4, 3)]
_CLERIC = [(1, 0, 0), (2, 0, 0), (2, 1, 0), (3, 2, 0), (3, 3, 1),
           (3, 3, 2), (3, 3, 2), (3, 3, 3), (3, 3, 3), (4, 4, 3)]
_MAGIC_USER_CURSE = [(1, 0, 0, 0, 0), (2, 0, 0, 0, 0), (2, 1, 0, 0, 0),
                     (3, 2, 0, 0, 0), (4, 2, 1, 0, 0), (4, 2, 2, 0, 0),
                     (4, 3, 2, 1, 0), (4, 3, 3, 2, 0), (4, 3, 3, 2, 1),
                     (4, 4, 3, 2, 2), (4, 4, 4, 3, 3)]
_CLERIC_CURSE = [(1, 0, 0, 0, 0), (2, 0, 0, 0, 0), (2, 1, 0, 0, 0),
                 (3, 2, 0, 0, 0), (3, 3, 1, 0, 0), (3, 3, 2, 0, 0),
                 (3, 3, 2, 1, 0), (3, 3, 3, 2, 0), (4, 4, 3, 2, 1),
                 (4, 4, 3, 3, 2)]

# --- the two classes that borrow another's array, #548 -----------------------
# Both rows below are **Curse's own slot builder**, `GAME.OVR:0x3AC81` in the
# DOS build: it `FillChar`s the fifteen bytes at record `0x12D` and then, for
# each class slot whose level is above zero, adds that class's table rows
# cumulatively, one row a level.  The tables are *deltas* there; these are the
# running totals, so they read the way `_CLERIC_CURSE` does and the way a
# character sheet does.  `tests/curse_of_the_azure_bonds/test_cursespellslots.py::
# test_the_four_delta_tables_are_the_games_own` reads all four back off the
# player's own image and accumulates them, so a transcription slip here fails
# rather than ships.
#
# The same read reproduces `_CLERIC_CURSE` (`DS:42BC`) and `_MAGIC_USER_CURSE`
# (`DS:44AB`) row for row, for all ten cleric and all eleven magic-user levels
# with no exceptions -- and those two were originally read off the C64's
# `ECL65` payload `0x88D`, which stores the same table as totals rather than
# deltas.  Two ports, two encodings, the same numbers: that is what makes it
# safe to take the paladin's and the ranger's rows from DOS.

#: The paladin's, `DS:43E5`, added from level 9 (`cmp [bp-2], 8 / jg`) into the
#: **cleric** array at `record[0x12C + s]` -- he has no array of his own.
#: Curse's paladin ceiling is 11, so this is the whole progression; the table
#: itself continues `2 2 0 0 0` at 12, which is what Pools of Darkness' shipped
#: GUY DE VALOIS, a paladin 12, holds in his cleric array.
#:
#: **CONFIRMED on both ports.** The C64 computes it arithmetically instead of
#: reading a table -- `ECL65 $884B` is `LDA $7CCF` (the paladin class-level
#: slot) / `LDX #$01` / `CMP #$09 / BCC` past it / `CMP #$0A / BCC` / `INX` /
#: `CMP #$0B / BCC` / `INC $2BBC`, then `TXA / ADC $2BBB` -- and it lands on
#: the same 1, 2, and 2 1.
#:
#: **A paladin gets no Wisdom bonus.** `GAME.OVR:0x3B2E6` is called from the
#: cleric branch alone (`0x3AD4E`); the C64's `ECL65 $88F6` opens
#: `LDA $7CCA / BEQ`, which is the cleric slot. So a paladin of 11 with
#: Wisdom 18 holds `2 1 0 0 0`.
_PALADIN_CURSE = [(0, 0, 0, 0, 0), (0, 0, 0, 0, 0), (0, 0, 0, 0, 0),
                  (0, 0, 0, 0, 0), (0, 0, 0, 0, 0), (0, 0, 0, 0, 0),
                  (0, 0, 0, 0, 0), (0, 0, 0, 0, 0), (1, 0, 0, 0, 0),
                  (2, 0, 0, 0, 0), (2, 1, 0, 0, 0)]

#: The ranger's, `DS:4448`, added from level 8 (`cmp [bp-2], 7 / jg`) -- and
#: one class level fills **two** arrays, so each entry is
#: `(druid run, magic-user run)`.  `GAME.OVR:0x3AEB4` adds the table's columns
#: 1-3 into `record[0x131 + s]`, the druid array, and `0x3AEF5` adds columns
#: 4-5 into `record[0x136 + s - 3]`, the first two levels of the magic-user
#: array.  **The druid array is a ranger's, not a druid character's**: Curse
#: has no druid class at all (`goldbox.classcode.CLASS_CODE_TABLE` gives class
#: code 1 a zero bitmask, and the builder's class loop has no branch for it),
#: which is what `goldbox.dos_port`'s `_DRUID_SLOT_NOTE` already says from six
#: rangers in the two later titles.
#:
#: **The two ports disagree at ranger 11, and only there.** The C64's
#: `ECL65 $8868` is `LDA $7CD0` (the ranger slot) / `CMP #$08 / BCC` past it /
#: `INX` / `CMP #$09 / BCC` / `BEQ` / `INX` / `INY`, then `STX $2BC0` and
#: `TYA / ADC $2BB6`: X is the druid first-level count and Y the magic-user
#: one, and **Y never reaches 2**, so a C64 ranger 11 memorises one
#: first-level magic-user spell where the DOS row below gives two.  AD&D 1st
#: edition gives two, so the C64 is the odd one out.  The DOS numbers are what
#: goes here because this table is only ever read to *write* a DOS-format
#: record -- which the DOS engine then rebuilds from `DS:4448` on load anyway,
#: and which is what an Amiga record is built from.
_RANGER_CURSE = [
    ((0, 0, 0, 0, 0), (0, 0, 0, 0, 0)),          # 1
    ((0, 0, 0, 0, 0), (0, 0, 0, 0, 0)),          # 2
    ((0, 0, 0, 0, 0), (0, 0, 0, 0, 0)),          # 3
    ((0, 0, 0, 0, 0), (0, 0, 0, 0, 0)),          # 4
    ((0, 0, 0, 0, 0), (0, 0, 0, 0, 0)),          # 5
    ((0, 0, 0, 0, 0), (0, 0, 0, 0, 0)),          # 6
    ((0, 0, 0, 0, 0), (0, 0, 0, 0, 0)),          # 7
    ((1, 0, 0, 0, 0), (0, 0, 0, 0, 0)),          # 8
    ((1, 0, 0, 0, 0), (1, 0, 0, 0, 0)),          # 9
    ((2, 0, 0, 0, 0), (1, 0, 0, 0, 0)),          # 10
    ((2, 0, 0, 0, 0), (2, 0, 0, 0, 0)),          # 11
]

# --- Secret of the Silver Blades ---------------------------------------
# Running totals per class level, one row per level 1-15, padded to the
# record's seven spell levels.  The C64's `ECL65 $886C` builds them: one shared
# row table at `$88F1` and four parameter tables (`$88CD`, `$88D6`, `$88DF`,
# `$88E8`) that a self-modifying loop at `$888B` copies into its own operands,
# one pass per class slot, **adding** each pass's row into its array.  The
# magic-user's rows are seven wide from level 1, the cleric's six wide from
# level 1, the paladin's four wide from level 9 and the ranger's two wide from
# level 9 (magic-user array) and again from level 8 (druid array).
# `tests/records/test_silverslots.py` reads them back off the player's own disk
# and compares, so a transcription slip here fails rather than ships.
#
# The magic-user and cleric rows are AD&D 1st edition's published tables for
# all fifteen levels.  As in Curse the paladin's rows land in the cleric array
# and take no wisdom bonus, and the ranger's one class level fills two arrays,
# so each of his entries is `(druid run, magic-user run)`.
_MAGIC_USER_SSB = [
    (1, 0, 0, 0, 0, 0, 0),  # 1
    (2, 0, 0, 0, 0, 0, 0),  # 2
    (2, 1, 0, 0, 0, 0, 0),  # 3
    (3, 2, 0, 0, 0, 0, 0),  # 4
    (4, 2, 1, 0, 0, 0, 0),  # 5
    (4, 2, 2, 0, 0, 0, 0),  # 6
    (4, 3, 2, 1, 0, 0, 0),  # 7
    (4, 3, 3, 2, 0, 0, 0),  # 8
    (4, 3, 3, 2, 1, 0, 0),  # 9
    (4, 4, 3, 2, 2, 0, 0),  # 10
    (4, 4, 4, 3, 3, 0, 0),  # 11
    (4, 4, 4, 4, 4, 1, 0),  # 12
    (5, 5, 5, 4, 4, 2, 0),  # 13
    (5, 5, 5, 4, 4, 2, 1),  # 14
    (5, 5, 5, 5, 5, 2, 1),  # 15
]
_CLERIC_SSB = [
    (1, 0, 0, 0, 0, 0, 0),  # 1
    (2, 0, 0, 0, 0, 0, 0),  # 2
    (2, 1, 0, 0, 0, 0, 0),  # 3
    (3, 2, 0, 0, 0, 0, 0),  # 4
    (3, 3, 1, 0, 0, 0, 0),  # 5
    (3, 3, 2, 0, 0, 0, 0),  # 6
    (3, 3, 2, 1, 0, 0, 0),  # 7
    (3, 3, 3, 2, 0, 0, 0),  # 8
    (4, 4, 3, 2, 1, 0, 0),  # 9
    (4, 4, 3, 3, 2, 0, 0),  # 10
    (5, 4, 4, 3, 2, 1, 0),  # 11
    (6, 5, 5, 3, 2, 2, 0),  # 12
    (6, 6, 6, 4, 2, 2, 0),  # 13
    (6, 6, 6, 5, 3, 2, 0),  # 14
    (7, 7, 7, 5, 4, 2, 0),  # 15
]
_PALADIN_SSB = [
    (0, 0, 0, 0, 0, 0, 0),  # 1
    (0, 0, 0, 0, 0, 0, 0),  # 2
    (0, 0, 0, 0, 0, 0, 0),  # 3
    (0, 0, 0, 0, 0, 0, 0),  # 4
    (0, 0, 0, 0, 0, 0, 0),  # 5
    (0, 0, 0, 0, 0, 0, 0),  # 6
    (0, 0, 0, 0, 0, 0, 0),  # 7
    (0, 0, 0, 0, 0, 0, 0),  # 8
    (1, 0, 0, 0, 0, 0, 0),  # 9
    (2, 0, 0, 0, 0, 0, 0),  # 10
    (2, 1, 0, 0, 0, 0, 0),  # 11
    (2, 2, 0, 0, 0, 0, 0),  # 12
    (2, 2, 1, 0, 0, 0, 0),  # 13
    (3, 2, 1, 0, 0, 0, 0),  # 14
    (3, 2, 1, 1, 0, 0, 0),  # 15
]
_RANGER_SSB = [
    ((0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0)),  # 1
    ((0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0)),  # 2
    ((0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0)),  # 3
    ((0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0)),  # 4
    ((0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0)),  # 5
    ((0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0)),  # 6
    ((0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0)),  # 7
    ((1, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0)),  # 8
    ((1, 0, 0, 0, 0, 0, 0), (1, 0, 0, 0, 0, 0, 0)),  # 9
    ((2, 0, 0, 0, 0, 0, 0), (1, 0, 0, 0, 0, 0, 0)),  # 10
    ((2, 0, 0, 0, 0, 0, 0), (2, 0, 0, 0, 0, 0, 0)),  # 11
    ((2, 1, 0, 0, 0, 0, 0), (2, 0, 0, 0, 0, 0, 0)),  # 12
    ((2, 1, 0, 0, 0, 0, 0), (2, 1, 0, 0, 0, 0, 0)),  # 13
    ((2, 2, 0, 0, 0, 0, 0), (2, 1, 0, 0, 0, 0, 0)),  # 14
    ((2, 2, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0)),  # 15
]
# --- Pools of Darkness -------------------------------------------------
# Rows per class level 1-29, nine wide, which is the width of each of the
# record's three arrays (`0x17D`, `0x186`, `0x18F` in DOS; `0x169`, `0x172`,
# `0x17B` on the Amiga).  **29 is the engine's own ceiling**: the builder at
# `GAME.OVR:0x03808A` and its cleric helper at `0x03860C` both clamp with
# `cmp byte ptr [bp-2], 0x1d / jbe / mov byte ptr [bp-2], 0x1d`, so a class
# level above 29 reads row 29, and the Amiga does the same twice over
# (`cmpi.b #$1d`, `0x03BEAA` and `0x03C4A6`).
#
# **This title's tables hold running totals where Curse's and Silver Blades'
# hold deltas**, and its cleric branch *assigns* (`mov byte ptr es:[di +
# 0x17c], dl`) where the other three *add*.  So the numbers below are read at
# the class level and not accumulated -- what a character sheet shows.
# `tests/records/test_pod_spells.py` reads all four back off the player's own
# game, so a transcription slip here fails rather than ships.
#
# **Both ports use the same bytes.**  The four tables are one 261-byte run
# each in the Amiga executable, 1043 of 1044 bytes identical to the DOS ones,
# and the byte that differs is the cleric table's column 0 at level 1, which
# neither engine reads (both column loops start at 1).  The Amiga picks
# between them with a class-slot index table holding `0 FF FF 1 2 3 FF`,
# naming the same four classes as DOS' four branches.
#
# **Two gates the engine applies and `capacity_by_class` does not yet.**  The
# cleric helper ends with the wisdom bonus and a wisdom ceiling, and the
# magic-user branch calls a leaf that is nothing but an intelligence ceiling:
#
# * wisdom below 17 zeroes cleric spell level 6 and below 18 level 7;
# * intelligence below 12, 14, 16 and 18 zeroes magic-user levels 6, 7, 8
#   and 9.
#
# Both are the same on the Amiga, on its own record offsets.  Neither is
# applied here, so a row below can be one or two slots wider than the game
# would give a character with a low score -- and the wisdom *bonus* comes out
# of `goldbox.levels`, which has no entry for this title, so
# `capacity_by_class` adds Pool of Radiance's bonus rather than this game's.
# The engine's bonus is Curse's and Silver Blades' table exactly: one spell a
# point from wisdom 13, at levels 1, 1, 2, 2, 3, 4.

#: `DS:77B5`, columns 1-9, added into the magic-user array from level 1.
#: AD&D 1st edition's published magic-user table to level 29.
_MAGIC_USER_POD = [
    (1, 0, 0, 0, 0, 0, 0, 0, 0),  # 1
    (2, 0, 0, 0, 0, 0, 0, 0, 0),  # 2
    (2, 1, 0, 0, 0, 0, 0, 0, 0),  # 3
    (3, 2, 0, 0, 0, 0, 0, 0, 0),  # 4
    (4, 2, 1, 0, 0, 0, 0, 0, 0),  # 5
    (4, 2, 2, 0, 0, 0, 0, 0, 0),  # 6
    (4, 3, 2, 1, 0, 0, 0, 0, 0),  # 7
    (4, 3, 3, 2, 0, 0, 0, 0, 0),  # 8
    (4, 3, 3, 2, 1, 0, 0, 0, 0),  # 9
    (4, 4, 3, 2, 2, 0, 0, 0, 0),  # 10
    (4, 4, 4, 3, 3, 0, 0, 0, 0),  # 11
    (4, 4, 4, 4, 4, 1, 0, 0, 0),  # 12
    (5, 5, 5, 4, 4, 2, 0, 0, 0),  # 13
    (5, 5, 5, 4, 4, 2, 1, 0, 0),  # 14
    (5, 5, 5, 5, 5, 2, 1, 0, 0),  # 15
    (5, 5, 5, 5, 5, 3, 2, 1, 0),  # 16
    (5, 5, 5, 5, 5, 3, 3, 2, 0),  # 17
    (5, 5, 5, 5, 5, 3, 3, 2, 1),  # 18
    (5, 5, 5, 5, 5, 3, 3, 3, 1),  # 19
    (5, 5, 5, 5, 5, 4, 3, 3, 2),  # 20
    (5, 5, 5, 5, 5, 4, 4, 4, 2),  # 21
    (5, 5, 5, 5, 5, 5, 4, 4, 3),  # 22
    (5, 5, 5, 5, 5, 5, 5, 5, 3),  # 23
    (5, 5, 5, 5, 5, 5, 5, 5, 4),  # 24
    (5, 5, 5, 5, 5, 5, 5, 5, 5),  # 25
    (6, 6, 6, 6, 5, 5, 5, 5, 5),  # 26
    (6, 6, 6, 6, 6, 6, 6, 5, 5),  # 27
    (6, 6, 6, 6, 6, 6, 6, 6, 6),  # 28
    (7, 7, 7, 7, 6, 6, 6, 6, 6),  # 29
]

#: `DS:71D4`, columns 1-7, **assigned** into the cleric array from level 1.
#: AD&D 1st edition's cleric table to 29, and its own loop stops at column 7,
#: so cleric spell levels 8 and 9 of the nine-wide array stay zero.
_CLERIC_POD = [
    (1, 0, 0, 0, 0, 0, 0, 0, 0),  # 1
    (2, 0, 0, 0, 0, 0, 0, 0, 0),  # 2
    (2, 1, 0, 0, 0, 0, 0, 0, 0),  # 3
    (3, 2, 0, 0, 0, 0, 0, 0, 0),  # 4
    (3, 3, 1, 0, 0, 0, 0, 0, 0),  # 5
    (3, 3, 2, 0, 0, 0, 0, 0, 0),  # 6
    (3, 3, 2, 1, 0, 0, 0, 0, 0),  # 7
    (3, 3, 3, 2, 0, 0, 0, 0, 0),  # 8
    (4, 4, 3, 2, 1, 0, 0, 0, 0),  # 9
    (4, 4, 3, 3, 2, 0, 0, 0, 0),  # 10
    (5, 4, 4, 3, 2, 1, 0, 0, 0),  # 11
    (6, 5, 5, 3, 2, 2, 0, 0, 0),  # 12
    (6, 6, 6, 4, 2, 2, 0, 0, 0),  # 13
    (6, 6, 6, 5, 3, 2, 0, 0, 0),  # 14
    (7, 7, 7, 5, 4, 2, 0, 0, 0),  # 15
    (7, 7, 7, 6, 5, 3, 1, 0, 0),  # 16
    (8, 8, 8, 6, 5, 3, 1, 0, 0),  # 17
    (8, 8, 8, 7, 6, 4, 1, 0, 0),  # 18
    (9, 9, 9, 7, 6, 4, 2, 0, 0),  # 19
    (9, 9, 9, 8, 7, 5, 2, 0, 0),  # 20
    (9, 9, 9, 9, 8, 6, 2, 0, 0),  # 21
    (9, 9, 9, 9, 9, 6, 3, 0, 0),  # 22
    (9, 9, 9, 9, 9, 7, 3, 0, 0),  # 23
    (9, 9, 9, 9, 9, 8, 3, 0, 0),  # 24
    (9, 9, 9, 9, 9, 8, 4, 0, 0),  # 25
    (9, 9, 9, 9, 9, 9, 4, 0, 0),  # 26
    (9, 9, 9, 9, 9, 9, 5, 0, 0),  # 27
    (9, 9, 9, 9, 9, 9, 6, 0, 0),  # 28
    (9, 9, 9, 9, 9, 9, 7, 0, 0),  # 29
]

#: `DS:755B`, columns 1-4, added into the **cleric** array from level 9
#: (`cmp byte ptr [bp-2], 8 / ja`) -- a paladin has no array of his own, as
#: in the two titles before this one, and takes no wisdom bonus because the
#: bonus lives in the cleric branch, which runs first. The table plateaus at
#: level 20 and the rows to 29 repeat it.
_PALADIN_POD = [
    (0, 0, 0, 0, 0, 0, 0, 0, 0),  # 1
    (0, 0, 0, 0, 0, 0, 0, 0, 0),  # 2
    (0, 0, 0, 0, 0, 0, 0, 0, 0),  # 3
    (0, 0, 0, 0, 0, 0, 0, 0, 0),  # 4
    (0, 0, 0, 0, 0, 0, 0, 0, 0),  # 5
    (0, 0, 0, 0, 0, 0, 0, 0, 0),  # 6
    (0, 0, 0, 0, 0, 0, 0, 0, 0),  # 7
    (0, 0, 0, 0, 0, 0, 0, 0, 0),  # 8
    (1, 0, 0, 0, 0, 0, 0, 0, 0),  # 9
    (2, 0, 0, 0, 0, 0, 0, 0, 0),  # 10
    (2, 1, 0, 0, 0, 0, 0, 0, 0),  # 11
    (2, 2, 0, 0, 0, 0, 0, 0, 0),  # 12
    (2, 2, 1, 0, 0, 0, 0, 0, 0),  # 13
    (3, 2, 1, 0, 0, 0, 0, 0, 0),  # 14
    (3, 2, 1, 1, 0, 0, 0, 0, 0),  # 15
    (3, 3, 1, 1, 0, 0, 0, 0, 0),  # 16
    (3, 3, 2, 1, 0, 0, 0, 0, 0),  # 17
    (3, 3, 3, 1, 0, 0, 0, 0, 0),  # 18
    (3, 3, 3, 2, 0, 0, 0, 0, 0),  # 19
    (3, 3, 3, 3, 0, 0, 0, 0, 0),  # 20
    (3, 3, 3, 3, 0, 0, 0, 0, 0),  # 21
    (3, 3, 3, 3, 0, 0, 0, 0, 0),  # 22
    (3, 3, 3, 3, 0, 0, 0, 0, 0),  # 23
    (3, 3, 3, 3, 0, 0, 0, 0, 0),  # 24
    (3, 3, 3, 3, 0, 0, 0, 0, 0),  # 25
    (3, 3, 3, 3, 0, 0, 0, 0, 0),  # 26
    (3, 3, 3, 3, 0, 0, 0, 0, 0),  # 27
    (3, 3, 3, 3, 0, 0, 0, 0, 0),  # 28
    (3, 3, 3, 3, 0, 0, 0, 0, 0),  # 29
]

#: `DS:7688` from level 8 (`cmp byte ptr [bp-2], 7 / ja`), one table into two
#: arrays: columns 1-3 into the druid array and columns 5-6 into the first
#: two levels of the magic-user array (`sub ax, 4` is the shift). So each
#: entry is `(druid run, magic-user run)`, as Curse's and Silver Blades'
#: rangers are. It plateaus at level 17.
_RANGER_POD = [
    ((0, 0, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0, 0, 0)),  # 1
    ((0, 0, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0, 0, 0)),  # 2
    ((0, 0, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0, 0, 0)),  # 3
    ((0, 0, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0, 0, 0)),  # 4
    ((0, 0, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0, 0, 0)),  # 5
    ((0, 0, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0, 0, 0)),  # 6
    ((0, 0, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0, 0, 0)),  # 7
    ((1, 0, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0, 0, 0)),  # 8
    ((1, 0, 0, 0, 0, 0, 0, 0, 0), (1, 0, 0, 0, 0, 0, 0, 0, 0)),  # 9
    ((2, 0, 0, 0, 0, 0, 0, 0, 0), (1, 0, 0, 0, 0, 0, 0, 0, 0)),  # 10
    ((2, 0, 0, 0, 0, 0, 0, 0, 0), (2, 0, 0, 0, 0, 0, 0, 0, 0)),  # 11
    ((2, 1, 0, 0, 0, 0, 0, 0, 0), (2, 0, 0, 0, 0, 0, 0, 0, 0)),  # 12
    ((2, 1, 0, 0, 0, 0, 0, 0, 0), (2, 1, 0, 0, 0, 0, 0, 0, 0)),  # 13
    ((2, 2, 0, 0, 0, 0, 0, 0, 0), (2, 1, 0, 0, 0, 0, 0, 0, 0)),  # 14
    ((2, 2, 0, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 15
    ((2, 2, 1, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 16
    ((2, 2, 2, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 17
    ((2, 2, 2, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 18
    ((2, 2, 2, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 19
    ((2, 2, 2, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 20
    ((2, 2, 2, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 21
    ((2, 2, 2, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 22
    ((2, 2, 2, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 23
    ((2, 2, 2, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 24
    ((2, 2, 2, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 25
    ((2, 2, 2, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 26
    ((2, 2, 2, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 27
    ((2, 2, 2, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 28
    ((2, 2, 2, 0, 0, 0, 0, 0, 0), (2, 2, 0, 0, 0, 0, 0, 0, 0)),  # 29
]

# Bonus first-, second- and third-level cleric spells for high Wisdom. **The
# game's, not AD&D's**: `goldbox.levels.wisdom_bonus_spells` implements `GEN
# $10AD` and the shifts `$2108` puts it through, and the game's first-level
# column starts a point low -- 1 at wisdom 12, where the rulebook gives the
# first bonus spell at 13. See `docs/125-bug-notes.md` N13. Curse's own copy
# is `ECL65 $8906`, read and CONFIRMED, and reaches it through `capacity`'s
# `game` argument below.
#
# AD&D gives a fourth-level bonus at 18 and 19 as well; it is left out because
# the record reserves six spell levels and neither game has been seen to grant
# it.

#: Per title, the rows tables keyed by the **class** that owns them -- not by
#: the array they are written into, because a paladin's rows go in the cleric
#: array and a ranger's in two arrays at once. Pool of Radiance has neither
#: class, so it keeps exactly the two it always had.
_SLOTS: dict[str, dict[str, list]] = {
    POOL_OF_RADIANCE.key: {"magic-user": _MAGIC_USER, "cleric": _CLERIC},
    CURSE_OF_THE_AZURE_BONDS.key: {"magic-user": _MAGIC_USER_CURSE,
                                   "cleric": _CLERIC_CURSE,
                                   "paladin": _PALADIN_CURSE,
                                   "ranger": _RANGER_CURSE},
    SECRET_OF_THE_SILVER_BLADES.key: {"magic-user": _MAGIC_USER_SSB,
                                      "cleric": _CLERIC_SSB,
                                      "paladin": _PALADIN_SSB,
                                      "ranger": _RANGER_SSB},
    POOLS_OF_DARKNESS.key: {"magic-user": _MAGIC_USER_POD,
                            "cleric": _CLERIC_POD,
                            "paladin": _PALADIN_POD,
                            "ranger": _RANGER_POD},
}


def spells_known(record_bytes: bytes, game=None) -> list[int]:
    """Every spell id the bitmask at 0x078 has set, for one title.

    How far this reads is the title's mask width: ids 1-55 on Pool of Radiance,
    1-100 on Curse, 1-117 on Silver Blades. Reading a Silver Blades caster with
    no `game` costs five of MORGAINE's twenty-nine spells, which is issue #81.

    Ids the title's name table calls something other than a spell -- a combat
    message, an unused slot -- are still reported. A bit that is set is set,
    and hiding it would lose it on a rewrite.
    """
    table = for_game(game)
    _needs_mask(table)
    return [i for i in range(1, table.last_spellbook_spell + 1)
            if record_bytes[SPELLBOOK_OFFSET + (i >> 3)] & (1 << (i & 7))]


def _needs_mask(table: SpellTable) -> None:
    """Refuse a title whose record keeps no bitmask at `0x078`.

    The three functions around this one read and write the C64 and neutral
    record's mask. A title with no C64 port has no such field -- Pools of
    Darkness keeps a byte an id at `0x0B3` in DOS and a mask at `0x159` on
    the Amiga -- and answering from `0x078` would report sixteen bytes of
    some other field as a spellbook.
    """
    if not table.spellbook_size:
        raise ValueError(
            f"{table.title} keeps no spellbook bitmask at "
            f"{SPELLBOOK_OFFSET:#05x}: read the record's own spellbook field "
            f"instead ({table.spellbook_ids} ids, one byte each, in DOS)")


def spellbook_bytes(ids, game=None) -> bytes:
    """The bitmask for a set of spell ids, as wide as the title's mask."""
    table = for_game(game)
    _needs_mask(table)
    out = bytearray(table.spellbook_size)
    for i in ids:
        i = int(i)
        if not 1 <= i <= table.last_spellbook_spell:
            raise ValueError(
                f"{i} cannot be in a {table.title} spellbook "
                f"(1-{table.last_spellbook_spell})"
                + ("; 56 is RESTORATION, which is a scroll spell"
                   if table is POOL_OF_RADIANCE else ""))
        out[i >> 3] |= 1 << (i & 7)
    return bytes(out)


#: The two `goldbox/layout.py` fields the mask is declared as, in record order:
#: the seven bytes Pool of Radiance uses, and the nine `0x07F`-`0x087` the
#: titles after it continue into. Two fields rather than one sixteen-byte one
#: because seven is a fact about *this* game and the split is where that fact
#: is recorded. Nothing should read or write either half on its own: the three
#: functions below are how the mask is reached, and they cross the boundary
#: because the title decides where the mask ends, not the layout.
SPELLBOOK_FIELDS = ("spells_known", "spells_known_high")


def spellbook_raw(record) -> bytes:
    """Both declared fields of the mask, as one run of bytes."""
    return b"".join(record.get_raw(f) for f in SPELLBOOK_FIELDS)


def set_spellbook_raw(record, raw: bytes) -> bool:
    """Write `raw` over the front of the mask. True if any byte moved.

    A short `raw` writes only as far as it reaches: thirteen bytes leave
    `0x085`-`0x087` exactly as they were, which is what a Curse writer must do
    -- whether those three are mask at all in Curse is UNKNOWN, its `GEN`
    having no clear loop, and a writer that does not know must not write.
    """
    before = spellbook_raw(record)
    after = bytearray(before)
    after[:len(raw)] = raw
    if bytes(after) == before:
        return False
    at = 0
    for name in SPELLBOOK_FIELDS:
        size = len(record.get_raw(name))
        record.set_raw(name, bytes(after[at:at + size]))
        at += size
    return True


def write_spellbook(record, ids, game=None) -> bool:
    """Set a record's spellbook to exactly `ids`, as wide as the title's mask."""
    return set_spellbook_raw(record, spellbook_bytes(ids, game))


def _row_at(rows: list, level: int):
    """One table's row for a class level, clamped to the table's own ends."""
    return rows[max(1, min(int(level), len(rows))) - 1]


def _accumulate(out: dict[str, tuple[int, ...]], school: str,
                run) -> None:
    """Add one class's run into an array, creating it if nothing filled it.

    The engine's own arithmetic: `GAME.OVR:0x3AC81` clears the fifteen bytes
    once and then walks all eight class slots **adding** each one's rows, so
    two classes that reach the same array sum rather than one winning.
    """
    have = out.get(school)
    if have is None:
        out[school] = tuple(run)
        return
    width = max(len(have), len(run))
    out[school] = tuple((have[i] if i < len(have) else 0)
                        + (run[i] if i < len(run) else 0)
                        for i in range(width))


def capacity_by_class(class_levels: dict[str, int], wisdom: int,
                       game=None,
                       port: str | None = None) -> dict[str, tuple[int, ...]]:
    """How many spells of each level the character may memorise, one row per
    **array** in the record, at each contributing class's own level.

    `capacity`, below, cannot answer this for a character split across two
    spell-casting classes: it takes one `level` for both, where Curse of the
    Azure Bonds' LEDERA, a fighter 4 / magic-user 4, needs her magic-user row
    read at 4 rather than at her fighter level or some combined total. This
    is the same table `capacity` reads, `_SLOTS[key]`, keyed by class name
    instead of by bit mask.

    A class absent from `class_levels`, or present at 0, gets no row -- the
    class is not held, the same as a bit `capacity` was not given.

    `port` says which build's cleric wisdom-bonus table to read -- passed
    straight to `goldbox.levels.wisdom_bonus_spells`, whose own docstring has
    the difference. With none given, this answers with the C64's table,
    which is what every caller written before there was a per-port table
    means (#557).

    **The key is the array, not the class**, because two of Curse's classes
    have no array of their own: a paladin's slots go in the cleric array and
    a ranger's in the druid array and the magic-user array at once. So a
    paladin 9 comes back as `{"cleric": (1, 0, 0, 0, 0)}` and a ranger 9 as
    `{"druid": ..., "magic-user": ...}`. `#548 (What do Curse's spell-slot
    arrays hold for a paladin, a ranger or a druid, which nothing on this
    machine can reach?)` has the read; there is no druid *class* in Curse, so
    a `"druid"` class level contributes nothing.

    The order below is the engine's own: the class loop walks slot 0, the
    cleric, and applies the Wisdom bonus inside that branch, before it
    reaches slot 3, the paladin. That is why a paladin's rows are added
    *after* the bonus and so never receive it.
    """
    rows = _SLOTS.get(for_game(game).key)
    if rows is None:
        # The Krynn titles' and Gateway's progression tables have not been
        # read off their disks. Nothing here, so a caller shows no number
        # rather than another game's -- the same rule `goldbox/c64_port.py`
        # applies to a race table it does not have.
        return {}
    out: dict[str, tuple[int, ...]] = {}
    mu_level = int(class_levels.get("magic-user") or 0)
    if mu_level and "magic-user" in rows:
        _accumulate(out, "magic-user", _row_at(rows["magic-user"], mu_level))
    cleric_level = int(class_levels.get("cleric") or 0)
    if cleric_level and "cleric" in rows:
        row = _row_at(rows["cleric"], cleric_level)
        bonus = levels.wisdom_bonus_spells(wisdom, game, port=port)
        # A Wisdom bonus only applies at a spell level the cleric can already
        # reach, so a level-1 cleric with WIS 16 gets three first-level spells
        # and no second-level ones.
        _accumulate(out, "cleric", tuple(
            base + (bonus[i] if base and i < len(bonus) else 0)
            for i, base in enumerate(row)))
    paladin_level = int(class_levels.get("paladin") or 0)
    if paladin_level and "paladin" in rows:
        _accumulate(out, "cleric", _row_at(rows["paladin"], paladin_level))
    ranger_level = int(class_levels.get("ranger") or 0)
    if ranger_level and "ranger" in rows:
        druid_run, magic_user_run = _row_at(rows["ranger"], ranger_level)
        _accumulate(out, "druid", druid_run)
        _accumulate(out, "magic-user", magic_user_run)
    return out


def capacity(class_bits: int, level: int, wisdom: int,
             game=None, port: str | None = None) -> dict[str, tuple[int, ...]]:
    """How many spells of each level the character may memorise.

    Read off the game's own tables, not derived. **The record also carries this
    number** -- `spells_castable` at `0x0EE`-`0x0F0`, nibble-packed magic-user
    low / cleric high, one byte per spell level -- so what this function
    computes can be checked against the save rather than trusted. Two
    independent readings agree on the packing: the project's own (ROLAND, a
    level-1 cleric with WIS 16, reads `$30`) and the QUANTUM LEAPER trainer,
    which prints `AND #$0F` under MAGIC-USER SPELLS and four `LSR`s under
    CLERIC SPELLS on those same three bytes, clamps each nibble to 14 and
    labels the field `LEVELS (0-14)`. It exposes three spell levels where the
    layout reserves six, which is Pool of Radiance's real ceiling; Curse
    reaches five, and the record has room for it.

    Returned per class, because a multi-class character memorises from each
    list separately. One `level` for both classes, unlike
    :func:`capacity_by_class` -- this is Pool of Radiance's own single-class
    shape, and a multi-class caller wants that function instead.
    """
    class_levels: dict[str, int] = {}
    if class_bits & 1:
        class_levels["magic-user"] = level or 1
    if class_bits & 2:
        class_levels["cleric"] = level or 1
    return capacity_by_class(class_levels, wisdom, game, port=port)
