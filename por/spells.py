"""The spell name table, and what a memorised spell list means.

A character's memorised spells are a packed list of **spell ids** at record
offset `0x020`, and the names live on the game disk. *Where* on the disk is the
one thing that does not transfer between titles, so this module is a table per
title -- the shape `por/games.py` settled on -- and every entry point takes an
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
    hashable, which is what `por/games.py` does for the same reason.
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
    #: `POOL_OF_RADIANCE` below.
    spellbook_size: int = 7

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
        knowing. The two later titles have bits to spare instead.
        """
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
#:   PAINE holds precisely those four druid bits and nothing else;
#: * the magic-user's, entered on record `0x0C9`, is a learn-list rather than a
#:   whole level, because magic-users learn by roll. Its level-9 row is the
#:   shipped MORGAINE's spellbook exactly, id for id.
#:
#: All three are read mechanically out of `GEN` by
#: `tests/test_silverblades.py::_grant_table`, which is Curse's extraction with
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
    # group, and the ranger grant is why: it hands out all three at the same
    # level (12), where 77-80 arrive at 8. All three are second-level druid
    # spells in AD&D 1st edition, which is what a ranger gets at 12. 96 was
    # read off its name as druid 1 and is corrected here; 98 had no group at
    # all, so `spell_group` called a spell the game itself grants no spell.
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

#: How wide the spellbook bitmask at record `0x078` is, per title. **Measured
#: in each game's own code, not carried across from another one.** The one
#: thing that looks like proof and is not: Curse's `GEN $2C2F` copies 32 bytes
#: out of `$7C78` -- and Pool of Radiance's `GEN $296B` copies the identical 32
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
#: * **Curse of the Azure Bonds, 13 -- CONFIRMED.** `CAMP $5225` builds the
#:   list of spells a character may memorise by walking spell ids from 1 with
#:   `INY / CPY #$65 / BCC`, so it stops after id 100, and it reads the mask as
#:   `TYA / LSR / LSR / LSR / TAX / LDA $7C78,X`. Id 100 puts X at 12, so the
#:   game itself reads `0x078`-`0x084`. `GEN $2D4A` writes there too, ORing
#:   `$E0` into `$7C81` and `$01` into `$7C82` to grant the four first-level
#:   druid spells 77-80. Curse's `GEN` has no clear loop, so **whether bytes
#:   `0x085`-`0x087` are also the mask is UNKNOWN**; thirteen is what the game
#:   reads, and no more is claimed.
#: * **Secret of the Silver Blades, 16 -- CONFIRMED**, and by three
#:   independent sightings. `GEN $41DC` clears sixteen bytes --
#:   `LDX #$0F / LDA #$00 / STA $7C78,X / DEX / BPL`. `GEN $50C9` walks the
#:   same sixteen. `CAMP $6071` is Curse's memorise loop with the ceiling moved
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
)

TITLES: tuple[SpellTable, ...] = (POOL_OF_RADIANCE, CURSE_OF_THE_AZURE_BONDS,
                                  SECRET_OF_THE_SILVER_BLADES)
BY_KEY = {t.key: t for t in TITLES}

#: What a caller gets when it says nothing. Every caller predates the second
#: game and means this one.
DEFAULT = POOL_OF_RADIANCE


def for_game(game=None) -> SpellTable:
    """The spell table for a title.

    Takes a `por.games.Game`, a game key, a `SpellTable`, or None. Duck-typed
    on `.key` rather than importing `por.games`, which would be a whole module
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
# Bonus first-, second- and third-level cleric spells for high Wisdom. **The
# game's, not AD&D's**: `por.levels.wisdom_bonus_spells` implements `GEN
# $10AD` and the shifts `$2108` puts it through, and the game's first-level
# column starts a point low -- 1 at wisdom 12, where the rulebook gives the
# first bonus spell at 13. See `docs/125-bug-notes.md` N13. Curse's copy has
# not been read and takes Pool of Radiance's until it is.
#
# AD&D gives a fourth-level bonus at 18 and 19 as well; it is left out because
# the record reserves six spell levels and neither game has been seen to grant
# it.

_SLOTS = {
    POOL_OF_RADIANCE.key: (_MAGIC_USER, _CLERIC),
    CURSE_OF_THE_AZURE_BONDS.key: (_MAGIC_USER_CURSE, _CLERIC_CURSE),
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
    return [i for i in range(1, table.last_spellbook_spell + 1)
            if record_bytes[SPELLBOOK_OFFSET + (i >> 3)] & (1 << (i & 7))]


def spellbook_bytes(ids, game=None) -> bytes:
    """The bitmask for a set of spell ids, as wide as the title's mask."""
    table = for_game(game)
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


def capacity(class_bits: int, level: int, wisdom: int,
             game=None) -> dict[str, tuple[int, ...]]:
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
    list separately.
    """
    rows = _SLOTS.get(for_game(game).key)
    if rows is None:
        # Silver Blades' progression tables have not been read off its disks,
        # and neither have the Krynn titles' or Gateway's. Nothing here, so a
        # caller shows no number rather than another game's -- the same rule
        # `por/games.py` applies to a race table it does not have. Issue #31.
        return {}
    magic_user, cleric = rows
    level = max(1, min(int(level or 1), len(magic_user)))
    out: dict[str, tuple[int, ...]] = {}
    if class_bits & 1:
        out["magic-user"] = magic_user[level - 1]
    if class_bits & 2:
        row = cleric[min(level, len(cleric)) - 1]
        bonus = levels.wisdom_bonus_spells(wisdom)
        # A Wisdom bonus only applies at a spell level the cleric can already
        # reach, so a level-1 cleric with WIS 16 gets three first-level spells
        # and no second-level ones.
        out["cleric"] = tuple(
            base + (bonus[i] if base and i < len(bonus) else 0)
            for i, base in enumerate(row))
    return out
