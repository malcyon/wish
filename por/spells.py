"""The spell name table, and what a memorised spell list means.

A character's memorised spells are a packed list of **spell ids** at record
offset `0x020`, and the names live on the game disk in `SPELLN00`.

`SPELLN00` is a PRG whose load address (`$2710`) is a scratch buffer and tells
you nothing. Its payload is:

    0x000-0x07F   128 low bytes
    0x080-0x0FF   128 high bytes      -- together, absolute addresses
    0x100-        the strings, NUL-terminated

The addresses are where the strings sit when the overlay is resident, at
`$B000`, so a file offset is `addr - $B000 + 0x100`. Reading through the
pointers rather than splitting the strings in order matters here even more than
it did for `ITEMNAMES`: the strings **overlap**. `CURE LIGHT WOUNDS` and
`CAUSE LIGHT WOUNDS` share one copy of ` LIGHT WOUNDS`, and a sequential reader
sees a single run of nonsense.

Only ids 1-56 are spells. From 57 the same table continues with combat message
fragments -- `AND MISSES...`, `POINTS OF DAMAGE` -- which share the mechanism
and not the meaning.
"""

from __future__ import annotations

from .d64 import D64, load_payload, split_load_address

SPELL_NAMES_FILE = b"SPELLN00"
NAMES_TABLE_ENTRIES = 128
NAMES_HIGH_BYTES = 0x080
NAMES_TEXT = 0x100
NAMES_RESIDENT_BASE = 0xB000

# The table runs cleric level 1, magic-user level 1, cleric level 2, and so on,
# each group alphabetical with a reversed spell following the one it reverses
# (CURE LIGHT WOUNDS then CAUSE LIGHT WOUNDS). The boundaries below are where
# that alphabetical run restarts, and every spell id observed in a real save
# falls in the group its caster's class predicts.
SPELL_GROUPS = (
    (1, 8, "cleric", 1),
    (9, 21, "magic-user", 1),
    (22, 28, "cleric", 2),
    (29, 35, "magic-user", 2),
    (36, 44, "cleric", 3),
    (45, 55, "magic-user", 3),
)
# RESTORATION. A cleric spell far above anything Pool of Radiance grants a
# player, so it is presumably the temple's, and its level is not worth guessing.
SPELL_RESTORATION = 56
LAST_SPELL = SPELL_RESTORATION


def load_spell_names(disk: D64 | str) -> dict[int, str]:
    """Every string in `SPELLN00`, keyed by id. Includes the non-spell tail."""
    payload = load_payload(disk, SPELL_NAMES_FILE)
    out: dict[int, str] = {}
    for idx in range(NAMES_TABLE_ENTRIES):
        addr = payload[idx] | payload[NAMES_HIGH_BYTES + idx] << 8
        start = addr - NAMES_RESIDENT_BASE + NAMES_TEXT
        if not NAMES_TEXT <= start < len(payload):
            continue                      # unused slot
        end = payload.find(b"\x00", start)
        if end < 0:
            continue
        text = payload[start:end].decode("latin1")
        if text:
            out[idx] = text
    return out


def spell_group(spell_id: int) -> tuple[str, int] | None:
    """(class, spell level) for a spell id, or None if it is not a spell."""
    for low, high, cls, level in SPELL_GROUPS:
        if low <= spell_id <= high:
            return cls, level
    return None


def describe(spell_id: int, names: dict[int, str] | None = None) -> str:
    """`SLEEP (magic-user 1)` -- the form a person wants to read."""
    name = (names or {}).get(spell_id) or f"spell {spell_id}"
    group = spell_group(spell_id)
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

# The spellbook is seven bytes, so it holds ids 1-55 and stops. Id 56 --
# RESTORATION -- is a **clerical scroll** spell, not one a character learns, and
# bit 56 would land in byte 7, one past the field. Reading to LAST_SPELL here
# was an off-by-one: `spells_known` peeked at 0x07F, which belongs to something
# else, and `spellbook_bytes([56])` raised IndexError. Nothing was ever
# misreported, because 0x07F reads zero in every specimen we hold -- but the
# read was outside the field and the write would have crashed.
LAST_SPELLBOOK_SPELL = SPELLBOOK_SIZE * 8 - 1        # 55

# Spells castable per level, before Wisdom bonuses. Index by level - 1.
_MAGIC_USER = [(1, 0, 0), (2, 0, 0), (2, 1, 0), (3, 2, 0), (4, 2, 1),
               (4, 2, 2), (4, 3, 2), (4, 3, 3), (4, 3, 3), (4, 4, 3)]
_CLERIC = [(1, 0, 0), (2, 0, 0), (2, 1, 0), (3, 2, 0), (3, 3, 1),
           (3, 3, 2), (3, 3, 2), (3, 3, 3), (3, 3, 3), (4, 4, 3)]
# Bonus first-, second- and third-level cleric spells for high Wisdom.
_WISDOM_BONUS = {13: (1, 0, 0), 14: (2, 0, 0), 15: (2, 1, 0), 16: (2, 2, 0),
                 17: (2, 2, 1), 18: (2, 2, 1), 19: (3, 2, 1)}


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


def capacity(class_bits: int, level: int, wisdom: int) -> dict[str, tuple[int, ...]]:
    """How many spells of each level the character may memorise.

    Derived from the AD&D 1st edition tables rather than read from the save --
    no field holding it has been found. Returned per class, because a
    multi-class character memorises from each list separately.
    """
    level = max(1, min(int(level or 1), 10))
    out: dict[str, tuple[int, ...]] = {}
    if class_bits & 1:
        out["magic-user"] = _MAGIC_USER[level - 1]
    if class_bits & 2:
        base = _CLERIC[level - 1]
        bonus = _WISDOM_BONUS.get(min(int(wisdom or 0), 19), (0, 0, 0))
        # A Wisdom bonus only applies at a spell level the cleric can already
        # reach, so a level-1 cleric with WIS 16 gets three first-level spells
        # and no second-level ones.
        out["cleric"] = tuple(b + (x if b else 0) for b, x in zip(base, bonus))
    return out
