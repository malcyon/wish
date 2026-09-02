"""The ten trait slots at `0x0AD`, spelled out on the character sheet.

The codes themselves live in `goldbox/traits.py` -- the combat view names the same
ones on a monster's tooltip, and one table cannot be allowed to become two.
This module is the sheet's view of them: ten rows, coloured by confidence.

**A cast spell is not in here.** `P3-EFFECTS.D64` proved it: twenty-six spells
running and every block unchanged. What these slots carry is the racial seed,
a monster's specials and an item's passive power. The live effects are four
64-entry arrays inside `SAVEDGAME0` and nothing shows them yet --
`docs/133-active-effects.md` is the plan for both.

**The list is shown, not edited**, for now, and the plan says what editing it
would have to be careful about.

**The codes are per title**, which is why the model carries the game and not
just the bytes: Secret of the Silver Blades gives an elf 95 where Pool of
Radiance gives 107, and 95 is Pool of Radiance's "fights on from -6 to 0 hit
points". Reading every save through one table put that sentence on the sheet
of an elf who has the ordinary elf's resistance to sleep and charm (#186).
`goldbox.traits.for_game` is the one place that chooses.
"""

from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QTableView

# EMPTY is re-exported: the form's tests read it as `effects.EMPTY`.
from goldbox.traits import EMPTY, NAMES, SLOTS, describe, for_game  # noqa: F401

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

    def __init__(self, raw: bytes = b"", game=None, parent=None):
        # Parented, so the C++ view and its model die together. An unparented
        # model outliving -- or predeceasing -- its view segfaults PyQt in a
        # test run that builds a dozen windows.
        super().__init__(parent)
        self.raw = bytes(raw)
        self.names = for_game(game)

    def set_bytes(self, raw: bytes) -> None:
        self.beginResetModel()
        self.raw = bytes(raw)
        self.endResetModel()

    def set_game(self, game) -> None:
        """Name the codes the way the open title does."""
        self.beginResetModel()
        self.names = for_game(game)
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
            return describe(code, self.names)
        if role == Qt.ItemDataRole.ForegroundRole:
            if not code:
                return QBrush(FADED)
            if self.names.get(code, ("", "GUESS"))[1] == "GUESS":
                return QBrush(UNSURE)
        if role == Qt.ItemDataRole.ToolTipRole and code:
            named = self.names.get(code)
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

    def set_game(self, game) -> None:
        """The open title changed, so the names may have. `editor/window.py`
        calls this from `_fill_combos`, beside the other per-title tables."""
        self.model_.set_game(game)
        self.resizeColumnsToContents()
        self.horizontalHeader().setStretchLastSection(True)

    def codes(self) -> list[int]:
        return [self.model_._code(n) for n in range(SLOTS)]
