"""The ten trait slots at `0x0AD`, spelled out on the character sheet.

The codes themselves live in `por/traits.py` -- the combat view names the same
ones on a monster's tooltip, and one table cannot be allowed to become two.
This module is the sheet's view of them: ten rows, coloured by confidence.

**A cast spell is not in here.** `P3-EFFECTS.D64` proved it: twenty-six spells
running and every block unchanged. What these slots carry is the racial seed,
a monster's specials and an item's passive power. The live effects are four
64-entry arrays inside `SAVEDGAME0` and nothing shows them yet --
`docs/133-active-effects.md` is the plan for both.

**The list is shown, not edited**, for now, and the plan says what editing it
would have to be careful about.
"""

from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QTableView

# EMPTY is re-exported: the form's tests read it as `effects.EMPTY`.
from por.traits import EMPTY, NAMES, SLOTS, describe  # noqa: F401

FADED = QColor("#808080")
UNSURE = QColor("#7d6608")     # a GUESS, coloured the way an NPC name is


class EffectsModel(QAbstractTableModel):
    """Ten rows whether or not anything is in them.

    Showing the empty slots is how the extent of the list stays visible: it is
    ten, XAVIER proved it by carrying a code in the tenth, and a table that
    shrank to the used ones would hide that.
    """

    # No code column. The number is what the census is indexed by and what a
    # tooltip falls back to for a code nobody has named; on the sheet it is a
    # second spelling of the name beside it.
    HEADERS = ("Slot", "Trait")

    def __init__(self, raw: bytes = b"", parent=None):
        # Parented, so the C++ view and its model die together. An unparented
        # model outliving -- or predeceasing -- its view segfaults PyQt in a
        # test run that builds a dozen windows.
        super().__init__(parent)
        self.raw = bytes(raw)

    def set_bytes(self, raw: bytes) -> None:
        self.beginResetModel()
        self.raw = bytes(raw)
        self.endResetModel()

    def rowCount(self, _parent=QModelIndex()) -> int:
        return SLOTS

    def columnCount(self, _parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (orientation is Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole):
            return self.HEADERS[section]
        return None

    def _code(self, row: int) -> int:
        return self.raw[row] if row < len(self.raw) else 0

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        code = self._code(row)
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return str(row)
            return describe(code)
        if role == Qt.ItemDataRole.ForegroundRole:
            if not code:
                return QBrush(FADED)
            if NAMES.get(code, ("", "GUESS"))[1] == "GUESS":
                return QBrush(UNSURE)
        if role == Qt.ItemDataRole.ToolTipRole and code:
            named = NAMES.get(code)
            if named is None:
                return f"code {code}; the trait census does not name it"
            return f"{named[0]} ({named[1]})"
        return None


class EffectsView(QTableView):
    """The effect list on the form, promoted in Designer.

    Speaks `set_bytes` like the spell widgets do, so the window fills it
    without knowing what it is. There is no `to_bytes`: the window writes back
    only what it can encode, and these bytes reach the disk untouched.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = EffectsModel(parent=self)
        self.setModel(self.model_)
        self.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)

    def set_bytes(self, raw: bytes) -> None:
        self.model_.set_bytes(raw)
        self.resizeColumnsToContents()
        self.horizontalHeader().setStretchLastSection(True)

    def codes(self) -> list[int]:
        return [self.model_._code(n) for n in range(SLOTS)]
