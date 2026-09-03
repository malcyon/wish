"""Inventory: the item area of SAVEDGAME0, and the game's item-name table.

Layout, established by diffing a save before and after the party bought
equipment (the shopping trip, docs/50-experiments.md):

    $5900 + slot * $100      one $100 block per character slot
    16 items of 16 bytes     within each block

An item record:

    +0   name index, usually the same as +3; differs for stacked ammunition
    +2   qualifier name index (e.g. MAIL, ARMOR) -- 0 when there is none
    +3   primary name index -- the reliable one
    +6   bit 7 set = readied / equipped
    +8   weight, 16-bit LE, in **tenths of a pound**
    +10  quantity (used for ammunition)
    +11  cost in gold pieces

Name indices are **1-based** into the table in the game's `ITEMNAMES` file,
with 0 meaning "no component". Names are compound: BANDED (+3) MAIL (+2).

Weights and costs match the AD&D 1st edition tables exactly -- banded mail
90gp/35lb, long sword 15gp/6lb, leather armour 5gp/15lb, dagger 2gp/1lb -- which
is what confirmed the field meanings.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

from .d64 import D64, load_payload, split_load_address
from .savegame import SAVE0_LOAD_ADDRESS
from .spells import LAST_SPELL

ITEM_AREA_BASE = 0x5900
ITEM_BLOCK_STRIDE = 0x100
ITEM_SIZE = 16
ITEMS_PER_CHARACTER = ITEM_BLOCK_STRIDE // ITEM_SIZE      # 16

READIED = 0x80

# The low three bits of +6 hide name words until the item is identified: bit 0
# the noun at +3, bit 1 the qualifier at +2, bit 2 the suffix at +1. Confirmed
# on all 163 items the game disks carry -- BANDED MAIL +1 shows as BANDED MAIL,
# POTION OF HEALING as POTION, and CURSED NECKLACE as plain NECKLACE.
HIDDEN_NAME_MASK = 0x07

# ITEMNAMES opens with 256 pointers to the name strings, stored as two parallel
# arrays -- 256 low bytes, then 256 high bytes -- of **absolute addresses**. The
# file loads at $6F00, so entry 1 points at $7101, which is where the memory map
# records "weapon names" in a running game.
#
# **That address is Pool of Radiance's.** The five later titles load the same
# file at $9E00 and their pointers start at $A001; the value to use lives on the
# `Game` descriptor as `item_names_load_address`, and this constant is only the
# fallback for a caller that has no Game to hand.
NAMES_LOAD_ADDRESS = 0x6F00
NAMES_TABLE_ENTRIES = 256
NAMES_LOW_BYTES = 0x000
NAMES_HIGH_BYTES = 0x100


def load_item_names(disk: D64 | str, game=None) -> dict[int, str]:
    """Read the item-name table out of a game disk's ITEMNAMES file.

    Returns a **1-based** index -> name mapping, keyed by the value an item
    record actually stores.

    Read through the pointer table rather than by splitting the strings in
    order. The two are not equivalent: indices 62, 63 and 168 have no name, and
    a sequential reader silently closes those gaps, shifting every name above
    62 by one and then by three. That put a wrong -- but entirely plausible --
    name on every item above the gap.

    `game` names the title whose load address applies. A title whose address is
    unknown yields no names at all rather than nonsense ones: an item shown by
    its index is an honest failure, a wrongly named one is not.
    """
    base = NAMES_LOAD_ADDRESS if game is None else game.item_names_load_address
    if base is None:
        return {}
    payload = load_payload(disk, b"ITEMNAMES")
    low = payload[NAMES_LOW_BYTES:NAMES_LOW_BYTES + NAMES_TABLE_ENTRIES]
    high = payload[NAMES_HIGH_BYTES:NAMES_HIGH_BYTES + NAMES_TABLE_ENTRIES]
    names: dict[int, str] = {}
    for idx in range(NAMES_TABLE_ENTRIES):
        addr = low[idx] | high[idx] << 8
        if addr < base:                        # unused slot; index 0 and the gaps
            continue
        start = addr - base
        end = payload.find(b"\x00", start)
        if end < 0:
            continue
        text = payload[start:end].decode("latin1")
        if text:
            names[idx] = text
    return names


# ITEMS is a second table on the game disk: 128 fixed records describing item
# *types*. An item record's byte +0 indexes it. Field order was recognised from
# Gold Box Explorer's reading of the FRUA equivalent, and every weapon then
# decoded to its exact AD&D 1st edition damage.
ITEM_TYPES_FILE = b"ITEMS"
ITEM_TYPE_SIZE = 16
ITEM_TYPE_COUNT = 128

TYPE_LOCATION = 0            # where on the body it goes
TYPE_HANDS = 1
TYPE_DAMAGE_LARGE = 2        # three bytes: dice, sides, bonus
TYPE_RATE = 5
TYPE_PROTECTION = 6
TYPE_DAMAGE_MEDIUM = 9       # three bytes: dice, sides, bonus
TYPE_RANGE = 12
TYPE_CLASS_USAGE = 13
TYPE_WEAPON_FLAGS = 14

# Type byte +14, how a weapon is used. Named from `GB_ITM-Base.hexpat`'s
# reading of the DOS table (docs/128-guide-and-scripting.md) and checked
# against the engine for the two bits anything acts on:
#
# * **bit 1, ranged.** LIBRARY $36A0 tests it and, when it is set, adds the
#   character's missile attack adjustment -- record 0x0EC -- to the roster's
#   THAC0. Every bow, crossbow and sling carries it, and so does everything
#   whose only use is thrown: the dart, the javelin, the vial of holy water.
# * **bit 2, add strength.** The block at LIBRARY $36B1 tests it and adds the
#   strength hit bonus instead. The melee weapons carry it, including the five
#   that can also be thrown -- the dagger, hand axe, club, hammer and spear
#   carry bit 2 and bit 4 and a range, and never bit 1.
#
# **They are not alternatives, though they read like them.** Of the 58 POOL1
# type records that carry damage dice, 54 hold one bit or the other; four hold
# **both** -- the HEAVY CROSSBOW, and the DECK, DRUMS and DUST, three magic
# items that reuse the weapon shape -- and four hold neither, BILL-GUISARME,
# GUISARME-VOULGE, BAG and the unnamed record 0. The engine's two blocks each
# add when their own bit is set and neither excludes the other, so a heavy
# crossbow takes both adjustments.
WEAPON_NEEDS_ARROWS = 0x01
WEAPON_RANGED = 0x02
WEAPON_ADDS_STRENGTH = 0x04
WEAPON_MULTI_SHOT = 0x08
WEAPON_THROWABLE = 0x10
WEAPON_NEEDS_BOLTS = 0x80

# The third byte of each damage triple -- type +4 and +11 -- is the flat damage
# bonus and it is **signed two's complement**, so $FF is -1 and not +255.
#
# Read from the engine, not inferred. Readying a weapon copies the type's +11
# into the roster's damage bonus verbatim (LIBRARY $36CC `LDA $6D97 / STA
# $6C17`) and then adds the item's own plus; swapping to the vs-large triple
# adjusts that same byte by `- type+11 + type+4` (COMBAT $17D1). When a blow
# lands, COMBAT $0CC3 reads the roster byte and branches on bit 7: a positive
# bonus is added to the roll, a negative one is negated (`EOR #$FF / ADC #$01`)
# and **subtracted**, and a result at or below zero is clamped to zero at
# $0CEA. The weapon-rating routine at COMBAT $1F8D tests the same bit and
# refuses to add a negative at all. Nothing anywhere compares the byte with
# $FF, so it is an ordinary negative number rather than a marker.
#
# The family stores its other small negative modifiers the same way: LIBRARY's
# strength tables at $3651 and $3670 hold $FD for -3.
#
# Four records in three titles carry $FF, in both triples: Pool of Radiance and
# Curse type 85, the VIAL OF HOLY WATER, and Silver Blades types 54, the
# CANARY, and 85. All four read 1d1-1 -- one die of one side is always 1, so
# they roll exactly zero. No other bit-7 bonus exists on any of the three
# titles' disks; the only other values are 0, 1, 2 and 8.

# Protection, type byte +6. **Bit 7 means the item affects armour class**, and
# the low seven bits carry the family's standard `60 - value` bias -- the same
# one THAC0 and armour class use everywhere else in this format. Body armour
# stores a class ($B4 = 52 = AC 8, leather; $B9 = 57 = AC 3, plate); a shield
# and the magical protective items store a flat bonus instead ($81 = +1).
#
# This was read for a long time as `12 - (byte & 0x0F)` under a $B0 mask, which
# is the same rule in disguise: 60 - (0x30 + n) is 12 - n. The two agree on
# every armour the disks carry and diverge below AC 12 -- $AF is AC 13 under
# the general rule and -3 under the nibble one. The general form is the one to
# keep; see docs/128-guide-and-scripting.md.
PROTECTION_GRANTS = 0x80     # bit 7: this item affects armour class
PROTECTION_BIAS = 60         # the family's 60 - value encoding
PROTECTION_VALUE = 0x7F      # the seven bits that carry it
# Which of the two the low seven bits are is decided by magnitude: a flat bonus
# is small and a biased class is 48 or more (AC 12). Every value the game ships
# is either 0-1 or 52-60, so nothing on the disks is near the line.
#
# The line cannot be drawn to satisfy both ends at once -- a bonus of 47 and an
# armour class of 13 are the same byte, $AF -- and no item in Pool of Radiance
# reaches either. It is drawn at 15 because armour class is what this byte is
# for and a bonus above 15 would be a +16 shield.
PROTECTION_BONUS_MAX = 0x0F

# Same bit order as the character record's class_bits at 0x0EB.
CLASS_USAGE_BITS = ((1, "magic-user"), (2, "cleric"), (4, "thief"), (8, "fighter"))

# Type byte +0, the body location. This is what decides how an item's own
# +13..+15 read: a scroll carries three spell ids, everything else carries
# charges, an effect and a dispatch byte.
LOCATIONS = {0: "weapon", 1: "shield", 2: "body", 3: "hands", 5: "neck",
             7: "back", 8: "feet", 9: "finger", 10: "carried",
             11: "scroll", 12: "scroll"}
LOCATION_USABLE_MAGIC = 14   # and above

# Item byte +14 holds one namespace. Up to LAST_SPELL it is a real spell id;
# from EFFECT_BASE it is an item-only effect stored EFFECT_BIAS above its real
# id, continuing the spell list past RESTORATION (56) as a clean run 57-67.
# Both CAMP and COMBAT do the SBC #$17 that recovers it.
#
# **It is not the same namespace as the record's effect list at 0x0AD**, though
# the two share storage: SPELLE04 $ADD4 copies +14 verbatim into a free slot
# when a passive item is readied. 85 is POTION OF HEALING as an item and "drains
# one level" on a wight. A passive item's +14 is its handler's argument -- the
# gauntlets carry 38, the cloak 89, the ring 61 -- and those land in the same
# slots as monster traits do.
EFFECT_BASE = 80
EFFECT_BIAS = 23

# Item byte +15: bit 7 marks a power applied when the item is readied and
# removed when it is un-readied; the low bits select the handler. The dispatch
# table is in ECL65, relocated to $9900, and covers $80-$88, $8A and $8B.
PASSIVE_POWER = 0x80


@dataclass(frozen=True)
class ItemType:
    """One record of the ITEMS type table: what a kind of item *does*."""

    index: int
    raw: bytes

    @staticmethod
    def _dice(triple: bytes) -> str | None:
        """A damage expression, `1d8+1` or `1d1-1`, or None with no dice.

        The bonus is signed -- see the note beside `TYPE_CLASS_USAGE`. It read
        unsigned until #188, which is why a vial of holy water was exported as
        doing `1d1+255` damage.
        """
        count, sides, bonus = triple
        if not count or not sides:
            return None
        if bonus > 127:
            bonus -= 256
        return f"{count}d{sides}" + (f"{bonus:+d}" if bonus else "")

    @property
    def damage_vs_large(self) -> str | None:
        return self._dice(self.raw[TYPE_DAMAGE_LARGE:TYPE_DAMAGE_LARGE + 3])

    @property
    def damage_vs_medium(self) -> str | None:
        return self._dice(self.raw[TYPE_DAMAGE_MEDIUM:TYPE_DAMAGE_MEDIUM + 3])

    @property
    def is_weapon(self) -> bool:
        return self.damage_vs_medium is not None or self.damage_vs_large is not None

    @property
    def armour_class(self) -> int | None:
        """The AC this armour grants, or None if the item is not armour.

        A shield does not set an armour class, it improves one; `is_shield`
        distinguishes them and the value is then a bonus, not a class.
        """
        p = self.raw[TYPE_PROTECTION]
        if not p & PROTECTION_GRANTS:
            return None
        if self.is_shield:
            return p & PROTECTION_VALUE
        return PROTECTION_BIAS - (p & PROTECTION_VALUE)

    @property
    def is_shield(self) -> bool:
        """True when +6 holds a bonus rather than a class -- a shield, or one
        of the magical protective items that improve an armour class."""
        p = self.raw[TYPE_PROTECTION]
        return bool(p & PROTECTION_GRANTS) and (p & PROTECTION_VALUE) <= PROTECTION_BONUS_MAX

    @property
    def hands(self) -> int:
        return self.raw[TYPE_HANDS]

    @property
    def rate_of_fire(self) -> int:
        return self.raw[TYPE_RATE]

    @property
    def range(self) -> int:
        return self.raw[TYPE_RANGE]

    @property
    def weapon_flags(self) -> int:
        """Type byte +14: how the weapon is used, as a mask."""
        return self.raw[TYPE_WEAPON_FLAGS]

    @property
    def is_ranged(self) -> bool:
        """Bit 1: to hit with it, the game uses the missile adjustment.

        A bow, a crossbow, a sling and everything thrown. `range` is not the
        same question: six records carry a range with the bit clear, the melee
        weapons that can also be thrown.
        """
        return bool(self.weapon_flags & WEAPON_RANGED)

    @property
    def adds_strength(self) -> bool:
        """Bit 2: to hit with it, the game uses the strength bonus."""
        return bool(self.weapon_flags & WEAPON_ADDS_STRENGTH)

    @property
    def usable_by(self) -> list[str]:
        bits = self.raw[TYPE_CLASS_USAGE] & 0x0F
        return [name for bit, name in CLASS_USAGE_BITS if bits & bit]

    def summary(self) -> str:
        """One short line for a person reading a YAML export."""
        parts: list[str] = []
        if self.is_weapon:
            med = self.damage_vs_medium or "-"
            large = self.damage_vs_large or "-"
            parts.append(f"{med} damage ({large} vs large)")
            if self.range:
                parts.append(f"range {self.range}")
        ac = self.armour_class
        if ac is not None:
            parts.append(f"AC {ac:+d}" if self.is_shield else f"AC {ac}")
        who = self.usable_by
        parts.append(", ".join(who) if who else "no class may use it")
        return "; ".join(parts)


def load_item_types(disk: D64 | str) -> dict[int, ItemType]:
    """Read the ITEMS type table off a game disk, keyed by the index an item
    record stores in its byte +0."""
    payload = load_payload(disk, ITEM_TYPES_FILE)
    out: dict[int, ItemType] = {}
    for i in range(min(ITEM_TYPE_COUNT, len(payload) // ITEM_TYPE_SIZE)):
        raw = bytes(payload[i * ITEM_TYPE_SIZE:(i + 1) * ITEM_TYPE_SIZE])
        if any(raw):
            out[i] = ItemType(i, raw)
    return out


@dataclass(frozen=True)
class Item:
    """One 16-byte item record."""

    raw: bytes
    names: dict[int, str] | None = None

    def _nm(self, stored: int) -> str:
        if not stored or self.names is None:
            return ""
        return self.names.get(stored, f"?{stored}")

    @property
    def is_empty(self) -> bool:
        return not any(self.raw)

    @property
    def name(self) -> str:
        """The printed name, assembled from up to three words.

        Byte 3 is the noun, byte 2 the qualifier, byte 1 the suffix -- so
        `CLOAK` + `OF` + `DISPLACEMENT`, or `BANDED` + `MAIL` + `+1`. Byte 1
        was missed until the 1989 BASIC editor on `poolce.d64` supplied 162
        ready-made records, every magic one of which uses all three.
        """
        parts = [p for p in (self._nm(self.raw[3]), self._nm(self.raw[2]),
                             self._nm(self.raw[1])) if p]
        return " ".join(parts)

    @property
    def hidden_words(self) -> int:
        """The hidden-name mask: which name words are concealed until the item
        is identified. Zero for anything mundane."""
        return self.raw[6] & HIDDEN_NAME_MASK

    @property
    def is_identified(self) -> bool:
        return not self.hidden_words

    @property
    def unidentified_name(self) -> str:
        """The name the game shows before the item has been identified."""
        mask = self.hidden_words
        parts = [self._nm(self.raw[3 - i]) for i in range(3)
                 if not mask & (1 << i)]
        return " ".join(p for p in parts if p)

    @property
    def bonus(self) -> int:
        """The numeric plus, signed -- 254 means a cursed -2."""
        b = self.raw[4]
        return b - 256 if b > 127 else b

    @property
    def type_index(self) -> int:
        """Index into the ITEMS type table -- what kind of thing this is.

        Usually equal to the noun word at +3, because the two tables run in
        parallel for ordinary weapons and armour, but not always: bracers are
        noun 79 and type 77.
        """
        return self.raw[0]

    @property
    def effects(self) -> tuple[int, int, int]:
        """Bytes +13, +14, +15 -- what a magical item *does*.

        On a **scroll** these are up to three spell ids: a "CLERICAL SCROLL
        WITH 3 SPELLS" carries three cleric ids, a "MU SCROLL WITH 1 SPELL"
        one arcane id and two zeroes. Confirmed against the game's own spell
        table on every scroll in the game data.

        On everything else they are `charges`, `effect` and `power`. Which
        reading applies is decided by the item's location in the ITEMS type
        table, not by anything in these three bytes.
        """
        return self.raw[13], self.raw[14], self.raw[15]

    @property
    def charges(self) -> int:
        """Byte +13. Decremented on each use; at zero the game spends one of
        the quantity at +10, and when that runs out it zeroes +0 and the item
        is gone."""
        return self.raw[13]

    @property
    def effect(self) -> int | None:
        """Byte +14 resolved to a spell id -- but only when +15 is zero.

        One namespace, two ranges. At or below `LAST_SPELL` the byte is a real
        spell id; from `EFFECT_BASE` it is an item-only effect stored
        `EFFECT_BIAS` above its true id, so 80..90 mean 57..67 -- the SBC #$17
        that both CAMP and COMBAT apply. POTION OF SPEED carries 80 and WAND OF
        MAGIC MISSILES 88, giving 57 and 65.

        **When +15 is non-zero, +14 is that handler's argument and not an
        effect at all**, so None is returned. GAUNTLETS OF OGRE POWER carries
        +15 = $83 with +14 = 38, and TWO-HANDED SWORD +1 +3 VS UNDEAD carries
        +15 = $88 with +14 = 3 -- the 3 is its bonus against undead. Reading
        either as a spell id would be nonsense.
        """
        if self.raw[15]:
            return None
        v = self.raw[14]
        if v == 0:
            return None
        if v <= LAST_SPELL:
            return v
        return v - EFFECT_BIAS if v >= EFFECT_BASE else None

    @property
    def power(self) -> int:
        """Byte +15: which handler runs, 0 for none.

        The dispatch table lives in ECL65, relocated to $9900, and covers $80
        through $88 plus $8A and $8B. Three handlers are named in SPELLE04:
        $83 sets strength to 18/100 (LDX #$12 / LDA #$64) -- the gauntlets;
        $84 is an alignment-locked sword that compares +14's low nibble
        against record 0x0D8 and, on a mismatch, un-readies itself and takes
        +14's high nibble off current hit points; $87 demands strength 19, the
        giant's boulder.

        Two values on the game disks, 34 and 42, fall outside the table and are
        unexplained.
        """
        return self.raw[15]

    @property
    def is_passive(self) -> bool:
        """Byte +15 bit 7: the power is applied when the item is readied and
        removed when it is un-readied, rather than fired on use."""
        return bool(self.raw[15] & PASSIVE_POWER)

    @property
    def saving_throw_bonus(self) -> int:
        """Byte +5, signed.

        The single read of it in the game accumulates it into $6DA7, and $6DA7
        is consumed in exactly one place: added to a d20 saving-throw roll.
        RING OF PROTECTION +1 carries +4 = 1 and +5 = 1 -- the AD&D 1st edition
        ring exactly, one byte for armour class and one for saves. CURSED
        NECKLACE carries -5 in both.
        """
        b = self.raw[5]
        return b - 256 if b > 127 else b

    @property
    def is_cursed(self) -> bool:
        """Bit 7 of +7. The un-ready handler refuses while it is set, and
        SPELLE04 -- remove curse -- is the only thing that clears it. The rest
        of +7 is unused, as are bits 3-6 of +6: the only masks applied to
        either byte anywhere in the game are $80, $7F, $07 and $F8."""
        return bool(self.raw[7] & 0x80)

    @property
    def readied(self) -> bool:
        return bool(self.raw[6] & READIED)

    @property
    def weight_tenths(self) -> int:
        return self.raw[8] | self.raw[9] << 8

    @property
    def weight_lb(self) -> float:
        return self.weight_tenths / 10

    @property
    def quantity(self) -> int:
        return self.raw[10]

    @property
    def cost_gp(self) -> int:
        """Cost in gold pieces, 16-bit little endian.

        Read as one byte until the editor's price list showed magic items at
        3500-25000 gp, every value matching the AD&D 1st edition tables.
        """
        return self.raw[11] | self.raw[12] << 8

    def __repr__(self) -> str:
        if self.is_empty:
            return "<Item empty>"
        r = "*" if self.readied else " "
        return (f"<Item{r}{self.name!r} {self.weight_lb}lb {self.cost_gp}gp"
                + (f" x{self.quantity}" if self.quantity else "") + ">")


# The game's own shop and encounter lists. Each is a PRG holding whole 16-byte
# item records, and between them the eight disks carry 163 distinct items --
# including magical ones no party of ours has ever found. They make better
# templates than a hand-built record, because every byte we do not understand
# already holds whatever the game puts there.
ITEM_FILE_PREFIX = b"ITEMFILE"

# **Secret of the Silver Blades drops the FILE.** Its lists are `ITEM10`,
# `ITEM4A`, `ITEM63` -- the same 16-byte records, the same two-hex-digit id, and
# 38 of them across the six sides. Matching on a bare `ITEM` prefix instead is
# not the fix: `ITEMS` is the 128-entry type table and `ITEMNAMES` the word
# pool, and both would be read as item records and yield nonsense names.
# The pattern is the stem plus exactly two hex digits, which admits both
# spellings and excludes those two.
ITEM_FILE_PATTERN = re.compile(rb"^ITEM(FILE)?[0-9A-F]{2}$")


def is_item_list(name: bytes) -> bool:
    """Is this directory entry one of the game's own item lists?"""
    return ITEM_FILE_PATTERN.match(bytes(name).upper()) is not None


def load_item_templates(disk: D64 | str,
                        names: dict[int, str] | None = None,
                        game=None) -> dict[str, bytes]:
    """Every distinct item record on a game disk, keyed by its printed name.

    Given a path, its sibling disks are scanned too, because the item files are
    spread across all eight sides. `game` chooses which siblings count.
    """
    disks: list[D64] = []
    if isinstance(disk, str):
        here = pathlib.Path(disk).resolve()
        siblings = sorted(here.parent.glob(
            "POOL*.[dD]64" if game is None else game.disk_glob))
        for path in ([here] + [s for s in siblings if s != here]):
            try:
                disks.append(D64.open(str(path)))
            except Exception:
                continue
    else:
        disks.append(disk)

    if names is None and disks:
        try:
            names = load_item_names(disks[0], game)
        except Exception:
            names = None

    out: dict[str, bytes] = {}
    for img in disks:
        for entry in img.directory():
            if not is_item_list(entry.name):
                continue
            try:
                _, payload = split_load_address(img.read_file(entry))
            except Exception:
                continue
            for i in range(len(payload) // ITEM_SIZE):
                raw = bytes(payload[i * ITEM_SIZE:(i + 1) * ITEM_SIZE])
                if not any(raw):
                    continue
                name = Item(raw, names).name
                out.setdefault(name, raw)
    return out


class ItemNameError(ValueError):
    """A word could not be turned into an index the game would recognise."""


def word_index(names: dict[int, str], word) -> int:
    """Turn a name-table word into its index.

    Accepts an index directly, or a word to look up (case-insensitive). Seven
    words appear twice in the table -- RING, CLOAK, JAVELIN, TRIDENT, STONE,
    OINTMENT, MIRROR -- and those are refused rather than guessed at, because
    the two entries are not interchangeable.
    """
    if isinstance(word, int):
        if not 0 <= word <= 0xFF:
            raise ItemNameError(f"word index {word} is out of range 0-255")
        return word
    text = str(word).strip().upper()
    if not text:
        return 0
    hits = [i for i, v in names.items() if v.strip().upper() == text]
    if not hits:
        raise ItemNameError(f"no item word called {word!r}")
    if len(hits) > 1:
        raise ItemNameError(
            f"{word!r} appears at indices {hits}; give the number you mean")
    return hits[0]


def build_item(*, type_index: int = 0, words=(), bonus: int = 0,
               quantity: int = 0, cost_gp: int = 0, weight_tenths: int = 0,
               readied: bool = False, base: bytes | None = None,
               names: dict[int, str] | None = None) -> bytes:
    """Assemble a 16-byte item record.

    `words` is the printed name in reading order -- noun, qualifier, suffix --
    stored at +3, +2, +1. Bytes we do not understand come from `base` when one
    is given, so building on top of a known-good record keeps whatever they
    mean; with no base they are zero, which is only safe for an item whose
    template we already trust.
    """
    raw = bytearray(base if base is not None else bytes(ITEM_SIZE))
    if len(raw) != ITEM_SIZE:
        raise ItemNameError(f"base must be {ITEM_SIZE} bytes, got {len(raw)}")

    resolved = [word_index(names or {}, w) for w in list(words)[:3]]
    resolved += [0] * (3 - len(resolved))
    raw[3], raw[2], raw[1] = resolved            # noun, qualifier, suffix
    raw[0] = int(type_index) & 0xFF
    raw[4] = int(bonus) & 0xFF                   # signed; 254 is a cursed -2
    raw[6] = (raw[6] | READIED) if readied else (raw[6] & ~READIED)
    raw[8] = int(weight_tenths) & 0xFF
    raw[9] = int(weight_tenths) >> 8 & 0xFF
    raw[10] = int(quantity) & 0xFF
    raw[11] = int(cost_gp) & 0xFF
    raw[12] = int(cost_gp) >> 8 & 0xFF
    return bytes(raw)


def items_for_slot(save0_payload: bytes, slot: int,
                   names: dict[int, str] | None = None) -> list[Item]:
    """Every non-empty item belonging to a character slot."""
    base = ITEM_AREA_BASE - SAVE0_LOAD_ADDRESS + slot * ITEM_BLOCK_STRIDE
    out = []
    for n in range(ITEMS_PER_CHARACTER):
        raw = bytes(save0_payload[base + n * ITEM_SIZE: base + (n + 1) * ITEM_SIZE])
        item = Item(raw, names)
        if not item.is_empty:
            out.append(item)
    return out
