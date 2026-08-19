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

from dataclasses import dataclass

import pathlib

from .d64 import D64, split_load_address
from .savegame import SAVE0_LOAD_ADDRESS

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
NAMES_LOAD_ADDRESS = 0x6F00
NAMES_TABLE_ENTRIES = 256
NAMES_LOW_BYTES = 0x000
NAMES_HIGH_BYTES = 0x100


def load_item_names(disk: D64 | str) -> dict[int, str]:
    """Read the item-name table out of a game disk's ITEMNAMES file.

    Returns a **1-based** index -> name mapping, keyed by the value an item
    record actually stores.

    Read through the pointer table rather than by splitting the strings in
    order. The two are not equivalent: indices 62, 63 and 168 have no name, and
    a sequential reader silently closes those gaps, shifting every name above
    62 by one and then by three. That put a wrong -- but entirely plausible --
    name on every item above the gap.
    """
    img = D64.open(disk) if isinstance(disk, str) else disk
    _, payload = split_load_address(img.read_file(b"ITEMNAMES"))
    low = payload[NAMES_LOW_BYTES:NAMES_LOW_BYTES + NAMES_TABLE_ENTRIES]
    high = payload[NAMES_HIGH_BYTES:NAMES_HIGH_BYTES + NAMES_TABLE_ENTRIES]
    names: dict[int, str] = {}
    for idx in range(NAMES_TABLE_ENTRIES):
        addr = low[idx] | high[idx] << 8
        if addr < NAMES_LOAD_ADDRESS:          # unused slot; index 0 and the gaps
            continue
        start = addr - NAMES_LOAD_ADDRESS
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

TYPE_HANDS = 1
TYPE_DAMAGE_LARGE = 2        # three bytes: dice, sides, bonus
TYPE_RATE = 5
TYPE_PROTECTION = 6
TYPE_DAMAGE_MEDIUM = 9       # three bytes: dice, sides, bonus
TYPE_RANGE = 12
TYPE_CLASS_USAGE = 13

# Protection: body armour reads $B0 in the high nibble with (12 - AC) in the
# low one; a shield reads $80 with its AC bonus in the low nibble.
PROTECTION_ARMOUR = 0xB0
PROTECTION_SHIELD = 0x80
PROTECTION_AC_BASE = 12

# Same bit order as the character record's class_bits at 0x0EB.
CLASS_USAGE_BITS = ((1, "magic-user"), (2, "cleric"), (4, "thief"), (8, "fighter"))


@dataclass(frozen=True)
class ItemType:
    """One record of the ITEMS type table: what a kind of item *does*."""

    index: int
    raw: bytes

    @staticmethod
    def _dice(triple: bytes) -> str | None:
        count, sides, bonus = triple
        if not count or not sides:
            return None
        return f"{count}d{sides}" + (f"+{bonus}" if bonus else "")

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
        if not p:
            return None
        if p & 0xF0 == PROTECTION_SHIELD:
            return p & 0x0F
        return PROTECTION_AC_BASE - (p & 0x0F)

    @property
    def is_shield(self) -> bool:
        return self.raw[TYPE_PROTECTION] & 0xF0 == PROTECTION_SHIELD

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
    img = D64.open(disk) if isinstance(disk, str) else disk
    _, payload = split_load_address(img.read_file(ITEM_TYPES_FILE))
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

        On a scroll these are up to three **spell ids**: a "CLERICAL SCROLL
        WITH 3 SPELLS" carries three cleric ids, a "MU SCROLL WITH 1 SPELL"
        one arcane id and two zeroes. Confirmed against the game's own spell
        table on every scroll in the game data.

        On a wand or potion they mean something else -- +13 varies between
        copies of the same wand and looks like charges, while +14 stays
        constant per wand type. Not settled; see docs/50-experiments.md.
        """
        return self.raw[13], self.raw[14], self.raw[15]

    @property
    def is_cursed(self) -> bool:
        """Bit 7 of +13's neighbour at +7. PROBABLE: set on both cursed items
        in the 1989 editor's list and on nothing else, but no cursed item has
        ever been seen in one of our own saves."""
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


def load_item_templates(disk: D64 | str,
                        names: dict[int, str] | None = None
                        ) -> dict[str, bytes]:
    """Every distinct item record on a game disk, keyed by its printed name.

    Given a path, its sibling `POOL*.D64` files are scanned too, because the
    item files are spread across all eight sides.
    """
    disks: list[D64] = []
    if isinstance(disk, str):
        here = pathlib.Path(disk).resolve()
        siblings = sorted(here.parent.glob("POOL*.[dD]64"))
        for path in ([here] + [s for s in siblings if s != here]):
            try:
                disks.append(D64.open(str(path)))
            except Exception:
                continue
    else:
        disks.append(disk)

    if names is None and disks:
        try:
            names = load_item_names(disks[0])
        except Exception:
            names = None

    out: dict[str, bytes] = {}
    for img in disks:
        for entry in img.directory():
            if not bytes(entry.name).upper().startswith(ITEM_FILE_PREFIX):
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
