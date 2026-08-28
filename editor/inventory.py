"""The sixteen item slots one character carries, with the names spelled out.

Items are not in the character record at all: they live in `SAVEDGAME0` at
`$5900 + slot * $100`, sixteen 16-byte records per character, so a `.chr`
export has none and a roster disk has none either.

Two things decide the shape of this module.

**The list is a dense prefix.** Every save we hold fills slots from 0 upwards
and leaves the tail zero, so deleting compacts rather than leaving a hole --
the game's own scan almost certainly stops at the first empty record.

**A template beats a hand-built record.** `goldbox.items.load_item_templates`
gives 163 real records off the game disks, and copying one keeps whatever the
bytes we do not understand are meant to hold. Adding an item therefore means
picking a template, never filling in fields.
"""

from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from .ui_inventory import Ui_AddItemDialog
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QListWidget,
    QVBoxLayout,
)

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
)
from goldbox.savegame import SAVE0_LOAD_ADDRESS
from goldbox.spells import POOL_OF_RADIANCE, SpellTable
from goldbox.spells import describe as describe_spell
from goldbox.spells import for_game as spell_table

EMPTY = bytes(ITEM_SIZE)

# +6 low three bits hide name words until the item is identified.
HIDDEN_NAME_MASK = 0x07


class Inventory:
    """One character's sixteen slots, editable, and diffable against the disk.

    Holds the bytes as they were read so `changed` can answer honestly: a save
    that changes nothing must write nothing, and an item block nobody touched
    must reach the disk byte for byte as it left it.
    """

    def __init__(self, payload: bytes, slot: int,
                 names: dict[int, str] | None = None):
        self.slot = slot
        self.names = names
        self.base = (ITEM_AREA_BASE - SAVE0_LOAD_ADDRESS
                     + slot * ITEM_BLOCK_STRIDE)
        self.raws = [bytes(payload[self.base + n * ITEM_SIZE:
                                   self.base + (n + 1) * ITEM_SIZE])
                     for n in range(ITEMS_PER_CHARACTER)]
        self.original = list(self.raws)

    # -- reading ----------------------------------------------------------

    def __len__(self) -> int:
        return ITEMS_PER_CHARACTER

    def item(self, n: int) -> Item:
        return Item(self.raws[n], self.names)

    def is_empty(self, n: int) -> bool:
        return not any(self.raws[n])

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

    def set_readied(self, n: int, on: bool) -> None:
        flags = self.raws[n][6]
        self._patch(n, 6, (flags | READIED) if on else (flags & ~READIED))

    def can_unidentify(self, n: int) -> bool:
        """Only an item that arrived unidentified can be put back that way.

        Which name words to hide is not derivable from an identified record --
        the CLI refuses the same edit for the same reason.
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
            if self.is_empty(n):
                self.set_raw(n, raw)
                return n
        return None

    def delete(self, n: int) -> None:
        """Remove one item and close the gap, keeping the list a dense prefix."""
        kept = [r for i, r in enumerate(self.raws) if i != n and any(r)]
        self.raws = kept + [EMPTY] * (len(self) - len(kept))

    # -- writing back -----------------------------------------------------

    def write_into(self, payload: bytearray) -> None:
        """Patch this character's block into a SAVEDGAME0 payload."""
        payload[self.base:self.base + ITEM_BLOCK_STRIDE] = b"".join(self.raws)


def describe(item: Item, names: dict[int, str] | None) -> str:
    """What to print in the name column.

    With no game disk there is no name table, and the honest thing is to show
    the indices that are actually stored rather than a blank -- the tab says
    why they are numbers.
    """
    if names:
        return item.name or "?"
    parts = [item.raw[3], item.raw[2], item.raw[1]]
    return "word " + "/".join(str(p) for p in parts if p)


# --- the table on the form ---------------------------------------------------

EMPTY_TEXT = "—"                      # an em dash, for a free slot
FADED = QColor("#808080")

# The widest of the 163 item names on the eight game disks, from
# docs/87-item-templates.md. The window prefers the real names when a game disk
# is open; this is what the column is worth when there is none, and it is a
# known number rather than a guess.
LONGEST_ITEM_NAME = "TWO-HANDED SWORD +1 +3 VS UNDEAD"

NUMBER, NAME, QTY, READIED_COL, IDENTIFIED, BONUS, WEIGHT, COST = range(8)
HEADERS = ("#", "Item", "Qty", "Readied", "Identified", "Bonus", "lb", "gp")
EDITABLE = (QTY, BONUS)
CHECKABLE = (READIED_COL, IDENTIFIED)


class InventoryModel(QAbstractTableModel):
    """Sixteen rows, one per slot, whether or not anything is in it.

    Showing the empty slots is the point: it is how many more the character can
    carry, and it is where an added item lands.
    """

    edited = pyqtSignal()

    def __init__(self, inventory: Inventory | None = None):
        super().__init__()
        self.inventory = inventory

    def set_inventory(self, inventory: Inventory | None) -> None:
        self.beginResetModel()
        self.inventory = inventory
        self.endResetModel()

    # -- shape ------------------------------------------------------------

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
        if self.inventory is None or self.inventory.is_empty(index.row()):
            return base
        if index.column() in EDITABLE:
            return base | Qt.ItemFlag.ItemIsEditable
        if index.column() == READIED_COL:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        if index.column() == IDENTIFIED:
            # An identified item cannot be un-identified: which name words to
            # hide is not recoverable once they are shown.
            item = self.inventory.item(index.row())
            if item.is_identified and not self.inventory.can_unidentify(index.row()):
                return base
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    # -- reading ----------------------------------------------------------

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.inventory is None:
            return None
        row, col = index.row(), index.column()
        empty = self.inventory.is_empty(row)
        item = self.inventory.item(row)

        if role == Qt.ItemDataRole.CheckStateRole and col in CHECKABLE and not empty:
            on = item.readied if col == READIED_COL else item.is_identified
            return (Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
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
            return describe(item, self.inventory.names)
        if col == QTY:
            return item.quantity if role == Qt.ItemDataRole.EditRole \
                else (str(item.quantity) if item.quantity else "")
        if col == BONUS:
            return item.bonus if role == Qt.ItemDataRole.EditRole \
                else (f"{item.bonus:+d}" if item.bonus else "")
        if col == WEIGHT:
            return f"{item.weight_lb:g}"
        if col == COST:
            return str(item.cost_gp)
        return ""

    def _tooltip(self, row: int, item: Item) -> str:
        lines = [f"slot {row}: {item.raw.hex()}"]
        if not item.is_identified:
            lines.append(f"shows in game as {item.unidentified_name!r} until "
                         f"it is identified")
        if item.is_cursed:
            lines.append("cursed: the game refuses to un-ready it")
        if item.saving_throw_bonus:
            lines.append(f"saving throws {item.saving_throw_bonus:+d}")
        if item.charges:
            lines.append(f"{item.charges} charges")
        if item.effect is not None:
            lines.append(f"effect: spell {item.effect}")
        if item.power:
            lines.append(f"power {item.power:#04x}"
                         + (" (applied while readied)" if item.is_passive else ""))
        return "\n".join(lines)

    # -- editing ----------------------------------------------------------

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if self.inventory is None or self.inventory.is_empty(index.row()):
            return False
        row, col = index.row(), index.column()
        if role == Qt.ItemDataRole.CheckStateRole and col in CHECKABLE:
            on = Qt.CheckState(value) == Qt.CheckState.Checked
            if col == READIED_COL:
                self.inventory.set_readied(row, on)
            elif on or self.inventory.can_unidentify(row):
                self.inventory.set_identified(row, on)
            else:
                return False
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
        if self.inventory is None or self.inventory.is_empty(row):
            return False
        self.beginResetModel()
        self.inventory.delete(row)
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

# Which reading byte +13-+15 get. The ITEMS type table decides it, not the
# bytes: on a scroll they are up to three spell ids, on everything else they
# are charges, an effect and a dispatch byte.
SCROLL_LOCATIONS = {11, 12}


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

    # -- shape ------------------------------------------------------------

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

    def _spell(self, sid: int) -> str:
        """A real spell by name; an item-only effect by number.

        Past the title's last spell the ids continue as an item-only run, and
        the name table has combat messages at those indices rather than effect
        names. Naming POTION OF HEALING's 62 "IS POISONED" would be worse than
        a number -- and where that starts is the title's, 56 on Pool of
        Radiance and 117 on Silver Blades.

        UNAPPROVED WORDING for the second line: the Pool of Radiance one is
        Donald's and is kept exactly, because RESTORATION is the name of its
        last spell and a number is worse. The later titles have no such
        landmark, so they get the number.
        """
        if sid <= self.spells.last_spell:
            return describe_spell(sid, self.spell_names, self.spells)
        if self.spells.last_spell == POOL_OF_RADIANCE.last_spell:
            return f"effect {sid} — the item-only range past RESTORATION"
        return (f"effect {sid} — the item-only range past spell "
                f"{self.spells.last_spell}")

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
        """Bytes +13, +14 and +15, read the way the item's location says.

        A scroll carries three spell ids in them; everything else carries
        charges, what the item does, and which handler does it.
        """
        charges, effect, power = item.effects
        if kind is not None and kind.raw[TYPE_LOCATION] in SCROLL_LOCATIONS:
            spells = [self._spell(s) for s in (charges, effect, power) if s]
            return [("Spells", ", ".join(spells) if spells else EMPTY_TEXT)]
        rows = [("Charges", str(charges) if charges else EMPTY_TEXT)]
        if item.effect is not None:
            rows.append(("Effect", self._spell(item.effect)))
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
