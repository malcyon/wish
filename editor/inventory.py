"""The sixteen item slots one character carries, with the names spelled out.

Items are not in the character record at all: they live in `SAVEDGAME0` at
`$5900 + slot * $100`, sixteen 16-byte records per character, so a `.chr`
export has none and a roster disk has none either.

Two things decide the structure of this module.

**The list may have holes.** The game can empty a slot by zeroing its type byte
while leaving the other bytes intact, with live items in later slots. Deleting
an item compacts the remaining live items.

**A template beats a hand-built record.** `goldbox.items.load_item_templates`
gives 163 real records off the game disks, and copying one keeps whatever the
bytes we do not understand are meant to hold. Adding an item therefore means
picking a template, never filling in fields.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QDialog,
)

from goldbox.dos_codec import C64_SCROLL_TYPES
from goldbox.items import (
    ITEM_AREA_BASE,
    ITEM_BLOCK_STRIDE,
    ITEM_SIZE,
    ITEMS_PER_CHARACTER,
    LOCATION_USABLE_MAGIC,
    LOCATIONS,
    PASSIVE_POWER,
    READIED,
    TYPE_LOCATION,
    Item,
    ItemType,
    repair_ring_of_fire_resistance,
)
from goldbox.savegame import SAVE0_LOAD_ADDRESS
from goldbox.spells import (
    CURSE_OF_THE_AZURE_BONDS,
    POOL_OF_RADIANCE,
    SECRET_OF_THE_SILVER_BLADES,
    SpellTable,
)
from goldbox.spells import describe as describe_spell
from goldbox.spells import for_game as spell_table

from .ui_inventory import Ui_AddItemDialog

# The item-only effects of each later title, by the id stored in item byte +14.
# Every name is the one item that stores the id; an id no game item stores is
# absent and shows as its number.
ITEM_ONLY_EFFECT_NAMES: dict[str, dict[int, str]] = {
    CURSE_OF_THE_AZURE_BONDS.key: {
        57: "Potion of Speed",
        59: "Potion of Giant Strength",
        61: "Wand of Paralyzation",
        63: "Dust of Disappearance",
        64: "Necklace of Missiles",
        65: "Wand of Magic Missiles",
        95: "Scroll of Protection from Dragon Breath",
        96: "Scroll of Protection from Paralyzation",
        97: "Potion of Invisibility",
        98: "Wand of Defoliation",
        99: "Potion of Extra Healing",
    },
    SECRET_OF_THE_SILVER_BLADES.key: {
        57: "Potion of Speed",
        59: "Potion of Giant Strength",
        61: "Wand of Paralyzation",
        62: "Potion of Healing",
        63: "Elixir of Youth",
        64: "Necklace of Missiles",
        65: "Wand of Magic Missiles",
        95: "Scroll of Protection from Dragon Breath",
        97: "Potion of Invisibility",
        99: "Potion of Extra Healing",
    },
}

EMPTY = bytes(ITEM_SIZE)

# +6 low three bits hide name words until the item is identified.
HIDDEN_NAME_MASK = 0x07


class Inventory:
    """One character's sixteen slots, editable, and diffable against the disk.

    Holds the bytes as they were read so `changed` can answer honestly: a save
    that changes nothing must write nothing, and an item block nobody touched
    must reach the disk byte for byte as it left it.
    """

    # True only for a DOS Pool character, set by `from_blocks`.
    type_zero_is_an_item = False

    def __init__(self, payload: bytes, slot: int,
                 names: dict[int, str] | None = None):
        self.slot = slot
        self.names = names
        self.base = (ITEM_AREA_BASE - SAVE0_LOAD_ADDRESS
                     + slot * ITEM_BLOCK_STRIDE)
        self._hold([bytes(payload[self.base + n * ITEM_SIZE:
                                  self.base + (n + 1) * ITEM_SIZE])
                    for n in range(ITEMS_PER_CHARACTER)])

    @classmethod
    def from_blocks(cls, raws: Sequence[bytes],
                    names: dict[int, str] | None = None,
                    type_zero_is_an_item: bool = False) -> "Inventory":
        """The sixteen slots from item blocks already in hand, for a party
        opened from a DOS or an Amiga save.

        `type_zero_is_an_item` is for a DOS Pool character: the engine can
        build a real item whose type byte is 0, and `add` and `delete` must
        keep it rather than treat it as the C64's zeroed stale slot.

        Those saves keep no `SAVEDGAME0` payload for `__init__` to slice, so
        the blocks come from the converted character instead. `slot` and
        `base` stay None: there is no payload to write back into, and
        `write_into` says so rather than patching offset zero of something
        else.
        """
        if len(raws) != ITEMS_PER_CHARACTER:
            raise ValueError(f"a character carries {ITEMS_PER_CHARACTER} item "
                             f"slots, got {len(raws)}")
        if any(len(r) != ITEM_SIZE for r in raws):
            raise ValueError(f"an item block is {ITEM_SIZE} bytes")
        self = cls.__new__(cls)
        self.slot = None
        self.names = names
        self.base = None
        self.type_zero_is_an_item = type_zero_is_an_item
        self._hold([bytes(r) for r in raws])
        return self

    def _hold(self, raws: list[bytes]) -> None:
        self.raws = raws
        self.original = list(self.raws)
        # #285 (The C64's Ring of Fire Resistance grants nothing, and Wish
        # should repair it on conversion and on an editor save): repair a
        # broken ring the moment it is read, against `self.original` rather
        # than after it, so `changed` sees the repair like any other edit --
        # a party carrying the ring writes it fixed the next time this
        # character's block is saved, and a party without one writes nothing.
        self.raws = [repair_ring_of_fire_resistance(r) for r in self.raws]

    # -- reading ----------------------------------------------------------

    def __len__(self) -> int:
        return ITEMS_PER_CHARACTER

    def item(self, n: int) -> Item:
        return Item(self.raws[n], self.names)

    def block_is_empty(self, raw: bytes) -> bool:
        """Whether an item block is a free slot: a zero type byte, except
        where type 0 is a real item and any nonzero byte counts."""
        if self.type_zero_is_an_item:
            return not any(raw)
        return Item(raw).is_empty

    def is_empty(self, n: int) -> bool:
        return self.block_is_empty(self.raws[n])

    def holds(self, n: int) -> bool:
        """Whether slot `n` must survive an add or a delete."""
        return not self.is_empty(n)

    @property
    def used(self) -> int:
        return sum(1 for n in range(len(self)) if not self.is_empty(n))

    @property
    def changed(self) -> bool:
        return self.raws != self.original

    def original_item(self, n: int) -> Item:
        return Item(self.original[n], self.names)

    # -- editing ----------------------------------------------------------

    def set_raw(self, n: int, raw: bytes) -> None:
        if len(raw) != ITEM_SIZE:
            raise ValueError(f"an item is {ITEM_SIZE} bytes, got {len(raw)}")
        self.raws[n] = bytes(raw)

    def _patch(self, n: int, offset: int, value: int) -> None:
        raw = bytearray(self.raws[n])
        raw[offset] = value & 0xFF
        self.raws[n] = bytes(raw)

    def set_quantity(self, n: int, value: int) -> None:
        self._patch(n, 10, value)

    def set_bonus(self, n: int, value: int) -> None:
        """The numeric plus, signed -- a cursed -2 is stored as 254."""
        self._patch(n, 4, value)

    def set_weight_tenths(self, n: int, tenths: int) -> None:
        """Weight in tenths of a pound, 16-bit little-endian at +8/+9."""
        self._patch(n, 8, tenths & 0xFF)
        self._patch(n, 9, tenths >> 8)

    def set_readied(self, n: int, on: bool) -> None:
        flags = self.raws[n][6]
        self._patch(n, 6, (flags | READIED) if on else (flags & ~READIED))

    def can_unidentify(self, n: int) -> bool:
        """Only an item that arrived unidentified can be put back that way.

        Which name words to hide is not derivable from an identified record --
        the CLI blocks the same edit for the same reason.
        """
        return bool(self.original[n][6] & HIDDEN_NAME_MASK)

    def set_identified(self, n: int, on: bool) -> None:
        flags = self.raws[n][6]
        if on:
            self._patch(n, 6, flags & ~HIDDEN_NAME_MASK)
        elif self.can_unidentify(n):
            self._patch(n, 6, (flags & ~HIDDEN_NAME_MASK)
                        | (self.original[n][6] & HIDDEN_NAME_MASK))

    def add(self, raw: bytes) -> int | None:
        """Put an item in the first free slot. None when all sixteen are full."""
        for n in range(len(self)):
            if not self.holds(n):
                self.set_raw(n, raw)
                return n
        return None

    def delete(self, n: int) -> None:
        """Remove one item and close the gap, keeping the list a dense prefix."""
        kept = [r for i, r in enumerate(self.raws)
                if i != n and self.holds(i)]
        self.raws = kept + [EMPTY] * (len(self) - len(kept))

    # -- writing back -----------------------------------------------------

    def write_into(self, payload: bytearray) -> None:
        """Patch this character's block into a SAVEDGAME0 payload."""
        if self.base is None:
            raise ValueError("this inventory was built from item blocks and "
                             "has no SAVEDGAME0 slot to write into")
        payload[self.base:self.base + ITEM_BLOCK_STRIDE] = b"".join(self.raws)


def describe(item: Item, names: dict[int, str] | None,
             type_zero_is_an_item: bool = False) -> str:
    """What to print in the name column.

    A DOS Pool item whose type byte is 0 has no name to look up, with or
    without a game disk, so it reads `UNNAMED_ITEM`.

    With no game disk there is no name table, and the honest thing is to show
    the indices that are actually stored rather than a blank -- the tab says
    why they are numbers.
    """
    if type_zero_is_an_item and item.raw[0] == 0:
        return UNNAMED_ITEM
    if names:
        return item.name or "?"
    parts = [item.raw[3], item.raw[2], item.raw[1]]
    return "word " + "/".join(str(p) for p in parts if p)


# --- the table on the form ---------------------------------------------------

EMPTY_TEXT = "—"                      # an em dash, for a free slot
UNNAMED_ITEM = "Unnamed item"         # a DOS Pool item whose type byte is 0
FADED = QColor("#808080")

# The widest of the 163 item names on the eight game disks, from
# docs/87-item-templates.md. The window prefers the real names when a game disk
# is open; this is what the column shows when there is none, and it is a
# known number rather than a guess.
LONGEST_ITEM_NAME = "TWO-HANDED SWORD +1 +3 VS UNDEAD"

NUMBER, NAME, QTY, READIED_COL, IDENTIFIED, BONUS, WEIGHT, COST = range(8)
HEADERS = ("#", "Item", "Qty", "Readied", "Identified", "Bonus", "lb", "gp")
EDITABLE = (QTY, BONUS, WEIGHT)
CHECKABLE = (READIED_COL, IDENTIFIED)


class InventoryModel(QAbstractTableModel):
    """Sixteen rows, one per slot, whether or not anything is in it.

    Showing the empty slots is the point: it is how many more the character can
    carry, and it is where an added item lands.

    **Row and slot are different things.**  The game draws its item list from
    the highest filled slot down to slot 0, so the filled slots come first in
    that order and the empty ones after them, lowest first; the `#` column
    keeps the slot's own number.  Every method that acts on an item takes the
    row the player sees and maps it with :meth:`slot_of`; :meth:`row_of` is
    the inverse.
    """

    edited = pyqtSignal()

    def __init__(self, inventory: Inventory | None = None):
        super().__init__()
        self.inventory = inventory
        self.spells: SpellTable = spell_table(None)

    def set_spells(self, spells: SpellTable) -> None:
        """The open title's spell table, which decides how +14 reads."""
        self.spells = spells

    def set_inventory(self, inventory: Inventory | None) -> None:
        self.beginResetModel()
        self.inventory = inventory
        self.endResetModel()

    # -- structure ------------------------------------------------------------

    def slot_of(self, row: int) -> int:
        """The item slot drawn on `row`: the filled slots from the highest
        down, then the empty ones from the lowest up."""
        slots = range(len(self.inventory))
        order = ([n for n in reversed(slots) if not self.inventory.is_empty(n)]
                 + [n for n in slots if self.inventory.is_empty(n)])
        return order[row]

    def row_of(self, slot: int) -> int:
        """The row `slot` is drawn on."""
        return next(r for r in range(len(self.inventory))
                    if self.slot_of(r) == slot)

    def rowCount(self, _parent=QModelIndex()) -> int:
        return len(self.inventory) if self.inventory else 0

    def columnCount(self, _parent=QModelIndex()) -> int:
        return len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (orientation is Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole):
            return HEADERS[section]
        return None

    def flags(self, index):
        base = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if (self.inventory is None
                or self.inventory.is_empty(self.slot_of(index.row()))):
            return base
        if index.column() in EDITABLE:
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    # -- reading ----------------------------------------------------------

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.inventory is None:
            return None
        row, col = self.slot_of(index.row()), index.column()
        empty = self.inventory.is_empty(row)
        item = self.inventory.item(row)


        if role == Qt.ItemDataRole.ForegroundRole and empty:
            return QBrush(FADED)
        if role == Qt.ItemDataRole.ToolTipRole and not empty:
            return self._tooltip(row, item)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == NUMBER:
                return str(row)
            if empty:
                return EMPTY_TEXT if col == NAME else ""
            return self._text(item, col, role)
        return None

    def _text(self, item: Item, col: int, role):
        if col == NAME:
            return describe(item, self.inventory.names,
                            self.inventory.type_zero_is_an_item)
        if col == QTY:
            return item.quantity if role == Qt.ItemDataRole.EditRole \
                else (str(item.quantity) if item.quantity else "")
        if col == BONUS:
            return item.bonus if role == Qt.ItemDataRole.EditRole \
                else (f"{item.bonus:+d}" if item.bonus else "")
        if col == WEIGHT:
            return item.weight_lb if role == Qt.ItemDataRole.EditRole \
                else f"{item.weight_lb:g}"
        if col == COST:
            return str(item.cost_gp)
        if col == READIED_COL:
            return "Yes" if item.readied else "No"
        if col == IDENTIFIED:
            return "Yes" if item.is_identified else "No"
        return ""

    def _tooltip(self, row: int, item: Item) -> str:
        lines = [f"Slot {row}: {item.raw.hex()}"]
        if not item.is_identified and item.unidentified_name:
            lines.append(f"Shows in game as {item.unidentified_name!r} until "
                         f"it is identified")
        if item.is_cursed:
            lines.append("Cursed: the game will not let you un-ready it")
        if item.saving_throw_bonus:
            lines.append(f"Saving throws {item.saving_throw_bonus:+d}")
        if item.type_index in C64_SCROLL_TYPES.get(self.spells.key, ()):
            # +13-+15 are spell ids on a scroll, not charges, effect or power.
            return "\n".join(lines)
        if item.charges:
            lines.append(f"{item.charges} charges")
        effect = item.effect_in(self.spells)
        if effect is not None:
            lines.append(self._effect_line(effect))
        if item.power:
            lines.append(f"Power {item.power:#04x}"
                         + (" (applied while readied)" if item.is_passive else ""))
        return "\n".join(lines)

    def _effect_line(self, effect: int) -> str:
        """The hover line for +14: a real spell, or an item-only effect's name."""
        if self.spells.key == POOL_OF_RADIANCE.key or (
                effect <= self.spells.last_spell
                and effect not in self.spells.not_a_spell):
            return f"Effect: spell {effect}"
        return f"Effect: {item_only_effect(self.spells, effect)}"

    # -- editing ----------------------------------------------------------

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if (self.inventory is None
                or self.inventory.is_empty(self.slot_of(index.row()))):
            return False
        row, col = self.slot_of(index.row()), index.column()
        if role == Qt.ItemDataRole.CheckStateRole and col in CHECKABLE:
            on = Qt.CheckState(value) == Qt.CheckState.Checked
            if col == READIED_COL:
                self.inventory.set_readied(row, on)
            elif on or self.inventory.can_unidentify(row):
                self.inventory.set_identified(row, on)
            else:
                return False
        elif role == Qt.ItemDataRole.EditRole and col == WEIGHT:
            try:
                pounds = float(value)
            except (TypeError, ValueError):
                return False
            tenths = round(pounds * 10)
            if not 0 <= tenths <= 65535:
                return False
            self.inventory.set_weight_tenths(row, tenths)
        elif role == Qt.ItemDataRole.EditRole and col in EDITABLE:
            try:
                n = int(value)
            except (TypeError, ValueError):
                return False
            if col == QTY:
                if not 0 <= n <= 255:
                    return False
                self.inventory.set_quantity(row, n)
            else:
                if not -128 <= n <= 127:
                    return False
                self.inventory.set_bonus(row, n)
        else:
            return False
        self.dataChanged.emit(index, index)
        self.edited.emit()
        return True

    # -- adding and removing ----------------------------------------------

    def add(self, raw: bytes) -> int | None:
        if self.inventory is None:
            return None
        self.beginResetModel()
        where = self.inventory.add(raw)
        self.endResetModel()
        if where is not None:
            self.edited.emit()
        return where

    def delete(self, row: int) -> bool:
        """Delete the item drawn on `row`."""
        if (self.inventory is None
                or self.inventory.is_empty(self.slot_of(row))):
            return False
        slot = self.slot_of(row)
        self.beginResetModel()
        self.inventory.delete(slot)
        self.endResetModel()
        self.edited.emit()
        return True


class AddItemDialog(QDialog):
    """Pick one of the 163 items the game disks carry.

    Typing filters; there is no free-form item builder, because a record built
    from nothing leaves every byte we have not decoded at zero.
    """

    def __init__(self, templates: dict[str, bytes], parent=None):
        super().__init__(parent)
        self.ui = Ui_AddItemDialog()
        self.ui.setupUi(self)
        self.templates = templates
        self.search = self.ui.search
        self.list = self.ui.list
        
        self.list.addItems(sorted(templates))
        
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        self.search.textChanged.connect(self._filter)
        
        self.resize(420, 480)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _filter(self, text: str) -> None:
        text = text.strip().upper()
        for i in range(self.list.count()):
            row = self.list.item(i)
            row.setHidden(bool(text) and text not in row.text().upper())
        if self.list.currentItem() is None or self.list.currentItem().isHidden():
            for i in range(self.list.count()):
                if not self.list.item(i).isHidden():
                    self.list.setCurrentRow(i)
                    break

    def chosen(self) -> bytes | None:
        row = self.list.currentItem()
        if row is None or row.isHidden():
            return None
        return self.templates.get(row.text())


# --- what the selected item actually does ------------------------------------

# Which reading bytes +13-+15 get is decided by the item's type id against the
# title's own scroll types (`C64_SCROLL_TYPES`), not by the bytes and not by
# the type's location: Silver Blades' scrolls share location 10 with its
# wands. On a scroll they are up to three spell ids, on everything else they
# are charges, an effect and a dispatch byte.


def item_only_effect(spells: SpellTable, sid: int) -> str:
    """An item-only effect's item name in the later titles, else its number."""
    return ITEM_ONLY_EFFECT_NAMES.get(spells.key, {}).get(sid, str(sid))


def _location_name(kind: ItemType | None) -> str:
    if kind is None:
        return ""
    where = kind.raw[TYPE_LOCATION]
    if where in LOCATIONS:
        return LOCATIONS[where]
    if where >= LOCATION_USABLE_MAGIC:
        return f"usable magic (location {where})"
    return f"location {where}"


class ItemTraitsModel(QAbstractTableModel):
    """The traits of one item, as trait-and-value rows.

    All of this was decoded long ago and none of it was visible: the
    saving-throw bonus at `+5`, the charges at `+13`, what the item carries at
    `+14`, the handler at `+15`, the curse bit in `+7`, and -- through byte `+0`
    -- the damage, protection, hands, range and class mask its type record
    holds.

    A trait that does not apply shows an em dash rather than vanishing, so the
    table does not reshuffle every time another item is clicked.
    """

    HEADERS = ("Trait", "Value")

    def __init__(self):
        super().__init__()
        self.rows: list[tuple[str, str]] = []
        self.types: dict[int, ItemType] = {}
        self.spell_names: dict[int, str] = {}
        self.spells: SpellTable = spell_table(None)

    def set_tables(self, types: dict[int, ItemType],
                   spell_names: dict[int, str],
                   spells: SpellTable | None = None) -> None:
        self.types = types or {}
        self.spell_names = spell_names or {}
        if spells is not None:
            self.spells = spells

    def set_item(self, item: Item | None) -> None:
        self.beginResetModel()
        self.rows = [] if item is None or item.is_empty else self._describe(item)
        self.endResetModel()

    # -- structure ------------------------------------------------------------

    def rowCount(self, _parent=QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (orientation is Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole):
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.rows[index.row()][index.column()]
        if role == Qt.ItemDataRole.ForegroundRole:
            if self.rows[index.row()][1] == EMPTY_TEXT:
                return QBrush(FADED)
        return None

    # -- the readings -----------------------------------------------------

    def _spell(self, sid: int, *, item_names: bool = True) -> str:
        """A real spell by name; an item-only effect by its item's name or number.

        A scroll's spell slot holds spell ids, never an item's effect, so it
        asks for the number only.

        Past a title's real spells the name table holds combat messages rather
        than effect names, so an item-only id never goes through it. Pool of
        Radiance's wording is Donald's and is kept exactly, because
        RESTORATION is the name of its last spell.
        """
        if sid <= self.spells.last_spell and sid not in self.spells.not_a_spell:
            return describe_spell(sid, self.spell_names, self.spells)
        if self.spells.key == POOL_OF_RADIANCE.key:
            return f"effect {sid} — the item-only range past RESTORATION"
        return item_only_effect(self.spells, sid) if item_names else str(sid)

    def _scroll_spell(self, sid: int) -> str:
        """A scroll's spell id, named by its real spell when the scribe mark is on.

        DOS and Amiga add 128 to a scroll's spell while it is being scribed
        and a camp save can keep it. Only a real spell's mark is read that
        way; a byte whose low seven bits are past the title's last spell is
        left to :meth:`_spell`, as a number.
        """
        if sid > 0x80 and sid & 0x7F <= self.spells.last_spell:
            sid &= 0x7F
        return self._spell(sid, item_names=False)

    def _describe(self, item: Item) -> list[tuple[str, str]]:
        kind = self.types.get(item.type_index)
        where = _location_name(kind)
        rows = [("Type", f"{item.type_index}"
                         + (f" — {where}" if where else " — no type record"))]
        rows += self._type_rows(kind)
        rows.append(("Saving throws",
                     f"{item.saving_throw_bonus:+d}" if item.saving_throw_bonus
                     else EMPTY_TEXT))
        rows += self._power_rows(item, kind)
        rows.append(("Cursed", "yes — only remove curse clears it"
                     if item.is_cursed else EMPTY_TEXT))
        return rows

    def _type_rows(self, kind: ItemType | None) -> list[tuple[str, str]]:
        if kind is None:
            return [(label, EMPTY_TEXT) for label in
                    ("Damage vs medium", "Damage vs large", "Protection",
                     "Hands", "Range", "Usable by")]
        ac = kind.armour_class
        if ac is None:
            protection = EMPTY_TEXT
        elif kind.is_shield:
            # The $80 family improves an armour class rather than setting one,
            # and it covers rings and cloaks as well as shields.
            protection = f"AC {ac:+d}"
        else:
            protection = f"AC {ac}"
        usable = kind.usable_by
        return [
            ("Damage vs medium", kind.damage_vs_medium or EMPTY_TEXT),
            ("Damage vs large", kind.damage_vs_large or EMPTY_TEXT),
            ("Protection", protection),
            ("Hands", str(kind.hands) if kind.hands else EMPTY_TEXT),
            ("Range", str(kind.range) if kind.range else EMPTY_TEXT),
            ("Usable by", ", ".join(usable) if usable
             else "no class may use it"),
        ]

    def _power_rows(self, item: Item, kind: ItemType | None) -> list[tuple[str, str]]:
        """Bytes +13, +14 and +15, read the way the item's type says.

        A scroll carries three spell ids in them; everything else carries
        charges, what the item does, and which handler does it.
        """
        charges, effect, power = item.effects
        if (kind is not None
                and item.type_index in C64_SCROLL_TYPES.get(self.spells.key, ())):
            spells = [self._scroll_spell(s) for s in (charges, effect, power) if s]
            return [("Spells", ", ".join(spells) if spells else EMPTY_TEXT)]
        rows = [("Charges", str(charges) if charges else EMPTY_TEXT)]
        effect_id = item.effect_in(self.spells)
        if effect_id is not None:
            rows.append(("Effect", self._spell(effect_id)))
        elif effect:
            # +15 is set, so +14 is that handler's argument -- the gauntlets'
            # 38, the undead sword's 3 -- and reading it as a spell is nonsense.
            rows.append(("Effect", f"{effect} — argument to the power below"))
        else:
            rows.append(("Effect", EMPTY_TEXT))
        rows.append(("Power", EMPTY_TEXT if not power else
                     f"{power:#04x}" + (" — passive, applied when readied"
                                        if power & PASSIVE_POWER else "")))
        return rows
