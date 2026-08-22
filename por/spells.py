"""The spell name table, and what a memorised spell list means.

A character's memorised spells are a packed list of **spell ids** at record
offset `0x020`, and the names live on the game disk. *Where* on the disk is the
one thing that does not transfer between titles, so this module is a table per
title -- the shape `por/games.py` settled on -- and every entry point takes an
optional `game`.

| | Pool of Radiance | Curse of the Azure Bonds |
|---|---|---|
| file | `SPELLN00` | `COMBAT2` |
| resident at | `$B000` | `$E000` |
| entries | 128 | 170 |
| order | 128 low bytes, 128 high bytes, then the strings | the strings, then 170 high bytes, then 170 low bytes |
| index of spell *n* | *n* | *n - 1* |
| spells run to | 56 | 100 |

Neither file's PRG header helps: `SPELLN00` declares `$2710`, which is a
scratch buffer. Curse's base needs no fitting at all -- the pointer for index 0
is `$E000` and the text runs `$E000`-`$E7DA`, exactly the range of high bytes
the array holds.

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
Radiance from 57, Curse from 101.

**`SPELLN64` is not a spell-name table in either game**, whatever its stem
suggests. It is 1878 bytes of icon-editor menu strings, and both titles ship
it. Curse ships no `SPELLN00` at all.
"""

from __future__ import annotations

from dataclasses import dataclass

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

    @property
    def text_end(self) -> int | None:
        """Where the strings stop, or None when they run to the file's end."""
        after = [o for o in (self.low_offset, self.high_offset)
                 if o >= self.text_offset]
        return min(after) if after else None


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
)

TITLES: tuple[SpellTable, ...] = (POOL_OF_RADIANCE, CURSE_OF_THE_AZURE_BONDS)
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
# Record offsets 0x078-0x07E are a bitmask of the spells a character *knows*,
# indexed by spell id: bit (id & 7) of byte 0x078 + (id >> 3).
#
# Confirmed on every caster we hold. Clerics know every spell of every level
# they can cast -- eight at level 1, twenty-four at level 6 -- and magic-users
# know a subset, which is exactly how AD&D 1st edition works. Every id set for
# a cleric falls in a cleric group and every id set for a magic-user in a
# magic-user group, with no crossover anywhere.
SPELLBOOK_OFFSET = 0x078
SPELLBOOK_SIZE = 7

# Bit 0 of 0x078 is deliberately unused -- spell id 0 does not exist. The
# QUANTUM LEAPER trainer's LEARN ALL SPELLS writes $FE to 0x078 and $FF to the
# other six, which is that fact in someone else's hand.
#
# Seven bytes is *this game's* width, and it is 56 bits, which is exactly Pool
# of Radiance's spell count. Silver Blades and Death Knights casters set
# 0x07D-0x07F, four of them holding 0x07F = 0x04, so on the later engine the
# mask is at least eight bytes -- see work/reports/goldbox-inventory.md.
#
# **Curse is the open case and it is not settled here.** Its spell list runs to
# 100, which would need thirteen bytes, but the highest bit any Curse specimen
# on the player's disks sets is id 44 -- SSI's own level-5 CLERIC -- so seven
# bytes has never been exceeded and nothing has been observed that a wider mask
# would explain. `por/layout.py` declares the field 7 wide for that reason and
# a Curse caster carrying a fourth-level spell would settle it in one read.
LAST_SPELLBOOK_SPELL = SPELLBOOK_SIZE * 8 - 1        # 55

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
# Bonus first-, second- and third-level cleric spells for high Wisdom. AD&D
# gives a fourth-level bonus at 18 and 19 as well; it is left out because the
# record reserves six spell levels and neither game has been seen to grant it.
_WISDOM_BONUS = {13: (1, 0, 0), 14: (2, 0, 0), 15: (2, 1, 0), 16: (2, 2, 0),
                 17: (2, 2, 1), 18: (2, 2, 1), 19: (3, 2, 1)}

_SLOTS = {
    POOL_OF_RADIANCE.key: (_MAGIC_USER, _CLERIC),
    CURSE_OF_THE_AZURE_BONDS.key: (_MAGIC_USER_CURSE, _CLERIC_CURSE),
}


def spells_known(record_bytes: bytes) -> list[int]:
    """Every spell id the bitmask at 0x078 has set. Ids 1-55."""
    return [i for i in range(1, LAST_SPELLBOOK_SPELL + 1)
            if record_bytes[SPELLBOOK_OFFSET + (i >> 3)] & (1 << (i & 7))]


def spellbook_bytes(ids) -> bytes:
    """The 7-byte bitmask for a set of spell ids."""
    out = bytearray(SPELLBOOK_SIZE)
    for i in ids:
        i = int(i)
        if not 1 <= i <= LAST_SPELLBOOK_SPELL:
            raise ValueError(
                f"{i} cannot be in a spellbook (1-{LAST_SPELLBOOK_SPELL}); "
                f"56 is RESTORATION, which is a scroll spell")
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
    magic_user, cleric = _SLOTS[for_game(game).key]
    level = max(1, min(int(level or 1), len(magic_user)))
    out: dict[str, tuple[int, ...]] = {}
    if class_bits & 1:
        out["magic-user"] = magic_user[level - 1]
    if class_bits & 2:
        row = cleric[min(level, len(cleric)) - 1]
        bonus = _WISDOM_BONUS.get(min(int(wisdom or 0), 19), (0, 0, 0))
        # A Wisdom bonus only applies at a spell level the cleric can already
        # reach, so a level-1 cleric with WIS 16 gets three first-level spells
        # and no second-level ones.
        out["cleric"] = tuple(
            base + (bonus[i] if base and i < len(bonus) else 0)
            for i, base in enumerate(row))
    return out
