"""Shorten the character names a destination cannot hold.

One row for every character whose name is over the destination's width or
holds a character it does not show as typed, built from
`editor.saveplan.NamesDoNotFit.unfit`. Each row shows the character's full
name and a box that starts with that name, without those characters and cut to
the width, selected for editing; the box takes none of those characters.
Nothing is written until the player confirms, and two characters sharing one
long name get a box each.

The accept button's label is the caller's: the Convert or Save As label. The
window shows no column header, hint or count.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QValidator
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLineEdit,
    QTableWidgetItem,
)

from . import saveplan
from .ui_namefit import Ui_NameFitDialog

#: Donald's approved window title and sentence, verbatim.
TITLE = "Choose character names"
LENGTH_SENTENCE = ("The target platform cannot store character names this "
                   "long. Please shorten them to {X} characters.")

#: The columns: the character's full name, then the box holding the new one.
ORIGINAL_COLUMN, BOX_COLUMN = range(2)


class ShownValidator(QValidator):
    """Accepts only text every character of which the destination shows as
    typed (`editor.saveplan.shows_as_typed`)."""

    def __init__(self, shown: frozenset[str], parent=None):
        super().__init__(parent)
        self._shown = shown

    def validate(self, text, pos):
        state = (QValidator.State.Acceptable
                 if all(saveplan.shows_as_typed(ch, self._shown)
                        for ch in text)
                 else QValidator.State.Invalid)
        return state, text, pos


class NameFitDialog(QDialog):
    """Edit each name; `chosen()` is what to hand the writer as `names`, and
    the accept button waits until every box holds a name the writer takes."""

    def __init__(self, unfit: Sequence[tuple[int, str]], width: int,
                 accept_label: str, parent=None, *,
                 shown: "frozenset[str] | None" = None):
        super().__init__(parent)
        self.ui = Ui_NameFitDialog()
        self.ui.setupUi(self)
        self.setWindowTitle(TITLE)
        # With no set given a name is only cut, as before characters were
        # checked, and the box blocks anything unprintable.
        start = ((lambda name: name[:width].rstrip()) if shown is None
                 else (lambda name: saveplan.suggest_name(name, width, shown)))
        shown = saveplan.ALL_PRINTABLE if shown is None else shown
        self.ui.explanation_label.setText(LENGTH_SENTENCE.format(X=width))
        # The sentence is about length, so it is not shown when no name is
        # too long.
        if not any(len(name) > width for _position, name in unfit):
            self.ui.explanation_label.hide()

        self.name_width = width
        self.table = self.ui.names_table
        self.buttons = self.ui.buttons
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            accept_label)

        #: One box per character, in party order, with its position.
        self._boxes: list[tuple[int, QLineEdit]] = []
        self.table.setRowCount(len(unfit))
        for row, (position, name) in enumerate(unfit):
            original = QTableWidgetItem(name)
            original.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, ORIGINAL_COLUMN, original)
            box = QLineEdit(start(name))
            box.setMaxLength(width)
            box.setValidator(ShownValidator(shown, box))
            box.selectAll()
            box.textChanged.connect(self._refresh)
            self.table.setCellWidget(row, BOX_COLUMN, box)
            self._boxes.append((position, box))
        # The full name is what the player compares the box against, so its
        # column takes what the name needs at whatever font is in use.
        self.table.horizontalHeader().setSectionResizeMode(
            ORIGINAL_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        self.table.resizeRowsToContents()
        # A box holds a full-width name of the widest letters without
        # scrolling it, and the window is wide enough for the name beside it.
        box_width = 0
        for _position, box in self._boxes:
            box_width = box.fontMetrics().horizontalAdvance("W" * width)
            box_width += box.minimumSizeHint().width()
            box.setMinimumWidth(box_width)
        self.table.setMinimumWidth(
            self.table.sizeHintForColumn(ORIGINAL_COLUMN) + box_width
            + 2 * self.table.frameWidth())
        # As tall as the rows need and no taller, at the width the form asks.
        wide = max(self.width(), self.minimumSizeHint().width())
        self.resize(wide, self.layout().totalHeightForWidth(wide))
        if self._boxes:
            self._boxes[0][1].setFocus()
        self._refresh()

    def _refresh(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(all(box.text() and box.hasAcceptableInput()
                          for _position, box in self._boxes))

    def chosen(self) -> dict[int, str]:
        """The name in each character's box, keyed by its position."""
        return {position: box.text() for position, box in self._boxes}
