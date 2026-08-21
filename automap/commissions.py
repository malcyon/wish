"""The City Council's books, drawn beside the map.

A quest log the game itself only shows one City Hall visit at a time: what has
been asked for, what is finished, and -- the line worth having -- what is
finished and still owed money.

Read-only, and deliberately. Every byte behind this panel is a plot flag, and
writing one would mean claiming to know what the rest of the script expects
afterwards. Displaying them promises nothing.

All the decoding is `por/commissions.py`, which has no Qt in it and is tested
against saves. This module is presentation: `update_from()` takes the same
bytes that module does -- the 224 flags at `$4A20`, a `SaveGame0`, or a whole
`SAVEDGAME0` image -- so it works from a live read and from a save file alike.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from por import commissions as book

from .panel import CARD, LATTICE, MUTED

PANEL_WIDTH = 248


def _label(text="", *, bold=False, muted=False, size=0) -> QLabel:
    lab = QLabel(text)
    font = lab.font()
    if bold:
        font.setBold(True)
    if size:
        font.setPointSize(size)
    lab.setFont(font)
    if muted:
        lab.setStyleSheet(f"color: {MUTED.name()}")
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    return lab


class Row(QWidget):
    """One line: what it is on the left, where it stands on the right."""

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.what = _label(size=8)
        self.what.setWordWrap(True)
        self.what.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Preferred)
        self.state = _label(size=8, muted=True)
        box.addWidget(self.what, 1)
        box.addWidget(self.state, 0, Qt.AlignmentFlag.AlignTop)

    def show_row(self, what: str, state: str = "", tip: str = "") -> None:
        self.what.setText(what)
        self.state.setText(state)
        self.setToolTip(tip)
        self.show()


class Group(QFrame):
    """A heading and its rows. Hidden entirely when it has none."""

    def __init__(self, heading: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        self.heading = _label(heading, bold=True, size=8)
        box.addWidget(self.heading)
        self._box = box
        self._rows: list[Row] = []

    def _row(self, index: int) -> Row:
        # Rows are made once and reused. A panel that rebuilt its widgets on
        # every poll would drop the scroll position each second.
        while len(self._rows) <= index:
            row = Row()
            self._box.addWidget(row)
            self._rows.append(row)
        return self._rows[index]

    def show_rows(self, rows) -> None:
        """`rows` is (text, state, tooltip) triples."""
        for i, (what, state, tip) in enumerate(rows):
            self._row(i).show_row(what, state, tip)
        for row in self._rows[len(rows):]:
            row.hide()
        self.setVisible(bool(rows))


def _entry_rows(entries):
    return [(e.name, "", _entry_tip(e)) for e in entries]


def _entry_tip(entry) -> str:
    tip = f"ledger {entry.index} at ${entry.address:04X} = {entry.value}"
    if entry.source:
        tip += f"\nfinished by {entry.source}"
    if entry.major:
        tip += "\ncounts towards commissions completed"
    return tip


class CommissionsPanel(QWidget):
    """The whole log: what is on offer, what is under way, what is finished.

    One entry point -- `update_from(source)`. Nothing here writes.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(PANEL_WIDTH + 22)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self.heading = _label("Commissions", bold=True)
        outer.addWidget(self.heading)

        inner = QWidget()
        inner.setStyleSheet(f"background: {CARD.name()};")
        column = QVBoxLayout(inner)
        column.setContentsMargins(8, 6, 8, 6)
        column.setSpacing(8)

        self.completed = _label("", muted=True, size=8)
        self.completed.setToolTip(
            f"${book.COMPLETED:04X}, bumped by the clerk for the ten "
            "commissions that count as major")
        column.addWidget(self.completed)

        self.groups = {
            "available": Group("Available"),
            "progress": Group("In progress"),
            "waiting": Group("Done - reward waiting"),
            "paid": Group("Done - paid"),
            "summons": Group("Summoned to"),
        }
        for group in self.groups.values():
            column.addWidget(group)
        column.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.StyledPanel)
        scroll.setStyleSheet(f"QScrollArea {{ border: 1px solid "
                             f"{LATTICE.name()}; border-radius: 4px; }}")
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        self._flags = None
        self.set_message("waiting for a game")

    def set_message(self, text: str) -> None:
        """No bytes to show, and why."""
        self.heading.setText(f"Commissions - {text}" if text
                             else "Commissions")

    def update_from(self, source) -> None:
        """Redraw from the flag block. Same input as `por.commissions.read`."""
        flags = book.flags(source)
        if self._flags is not None and flags.to_bytes() == self._flags:
            return                      # plot flags move rarely; skip the churn
        self._flags = flags.to_bytes()
        state = book.read(flags)
        self.set_message("")
        self.completed.setText(f"Commissions completed: {state.completed}")

        self.groups["available"].show_rows(
            [(o.text, "", f"offer {o.order} on the board at ECL08 $A84D")
             for o in state.offers]
            or [("the clerk has nothing to offer", "", "")])
        # Sorted by ledger index throughout, which is roughly the plot's order.
        self.groups["progress"].show_rows(
            [(e.name, f"{e.value}", _entry_tip(e)) for e in state.in_progress])
        self.groups["waiting"].show_rows(_entry_rows(state.reward_waiting))
        self.groups["paid"].show_rows(_entry_rows(state.paid))
        self.groups["summons"].show_rows(
            [(a.name, a.state, f"${a.address:04X} = {a.value}")
             for a in state.outstanding])
