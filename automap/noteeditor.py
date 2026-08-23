"""Adding, editing and deleting a note, without stopping playing.

The dialog this replaces was wrong in one specific way: it made adding a note a
modal interruption, and notes are made *while playing*, with the game in the
other window and a fight probably waiting. So this is a popover at the square --
nine icons, one line of text, Enter to keep, Escape to cancel -- and it goes
away by itself when it loses focus.

**Clicking a square that already has a note opens that note**, with its type
picked and its words in the field, and a **Delete** button beside them. The
first version opened blank and offered no way to remove anything, which made a
note something you could create and not undo.

**A square holds one note.** A file written by a build that allowed several
still loads, and the right-click menu lists every one of them so the extras
can be edited and deleted -- but nothing here makes a second.

The window owns the click that opens this; everything here is the popover.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.iconpaint import icon_pixmap

from . import notes as notemod
from .notes import Note
from .panel import CARD, INK, LATTICE, MUTED, NOTE

BUTTON = 26
ICON = 15

class NotePopover(QWidget):
    """The type picker, the text field, and what is already on the square.

    `changed` fires when the square's notes have been rewritten -- the window
    saves and repaints on it, and nothing here touches a file.
    """

    changed = pyqtSignal(int, int)

    def __init__(self, state, x: int, y: int, index: int | None = None,
                 parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        # A popover is transient: closing it should destroy it, not leave a
        # hidden window parented to the map for the rest of the session.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.state = state
        self.square = (x, y)
        existing = state.notes_at(x, y)
        # No index and something already here means "open what is here" -- a
        # click on a marked square is a request to see the note, not to start a
        # second one blank.
        if index is None and existing:
            index = 0
        self.index = index
        note = (existing[index] if index is not None and index < len(existing)
                else None)
        self.chosen = note.type if note else notemod.DEFAULT

        self.setStyleSheet(
            f"NotePopover {{ background: {CARD.name()}; border: 1px solid "
            f"{LATTICE.name()}; border-radius: 4px; }}"
            f" QLabel {{ color: {MUTED.name()}; }}")
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 6)
        box.setSpacing(4)

        small = self.font()
        small.setPointSize(8)

        head = QLabel(f"({x},{y})" + ("" if note is None else "  editing"))
        head.setFont(small)
        box.addWidget(head)

        picker = QHBoxLayout()
        picker.setSpacing(2)
        self.buttons: dict[str, QToolButton] = {}
        for kind in notemod.TYPES:
            button = QToolButton()
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setIcon(QIcon(icon_pixmap(kind.icon, ICON, NOTE)))
            button.setIconSize(QSize(ICON, ICON))
            button.setFixedSize(BUTTON, BUTTON)
            button.setToolTip(f"{kind.label} - {kind.hint}")
            button.setChecked(kind.name == self.chosen)
            button.clicked.connect(
                lambda _checked=False, name=kind.name: self.choose(name))
            picker.addWidget(button)
            self.buttons[kind.name] = button
        box.addLayout(picker)

        self.field = QLineEdit(note.text if note else "")
        self.field.setPlaceholderText("a few words, or none")
        self.field.setStyleSheet(f"color: {INK.name()}")
        self.field.returnPressed.connect(self.accept)
        box.addWidget(self.field)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        self.keep = QPushButton("Keep")
        self.keep.setFont(small)
        self.keep.setDefault(True)
        self.keep.clicked.connect(self.accept)
        # Only where there is something to delete. A Delete button on a note
        # that does not exist yet would be furniture.
        # **Parented here, in the constructor**, and not left to the layout.
        # A widget with no parent that is made visible *is a top-level
        # window*: Qt creates it, Windows activates it and takes focus off the
        # main window, and parenting it a moment later destroys it again. The
        # popover was being built inside that storm -- and only on a square
        # that already had a note, because only then is this made visible --
        # and Qt dismissed the popup on the way out. What the user saw was a
        # small empty window half-painting and vanishing.
        #
        # `addWidget` is not enough on its own: `buttons` is not installed on
        # anything until `box.addLayout(buttons)` further down, so a widget
        # added to it has no parent yet either. Naming the parent is the only
        # version that does not depend on the order of the lines below.
        # `Keep` never had the bug because it never sets its own visibility.
        self.remove = QPushButton(QIcon(icon_pixmap("trash-can", ICON, MUTED)),
                                  "Delete", self)
        self.remove.setFont(small)
        self.remove.setToolTip("remove this note from the square")
        self.remove.clicked.connect(lambda _checked=False: self.delete())
        self.remove.setVisible(note is not None)
        buttons.addWidget(self.remove)
        buttons.addStretch(1)
        buttons.addWidget(self.keep)
        box.addLayout(buttons)

        hint = QLabel("Enter keeps it, Escape leaves it alone")
        hint.setFont(small)
        box.addWidget(hint)

    # -- editing ---------------------------------------------------------



    def choose(self, name: str) -> None:
        self.chosen = name
        button = self.buttons.get(name)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def delete(self, index: int | None = None) -> None:
        """Remove one note. Defaults to the one being edited."""
        at = self.index if index is None else index
        items = list(self.state.notes_at(*self.square))
        if at is None or not (0 <= at < len(items)):
            return
        items.pop(at)
        self.state.set_notes(*self.square, items)
        self.changed.emit(*self.square)
        self.close()

    def accept(self) -> None:
        """Write the note back into the state and close.

        An empty note of the default type is not a note -- it would draw a
        marker that says nothing -- so it deletes instead of adding.
        """
        text = self.field.text().strip()
        items = list(self.state.notes_at(*self.square))
        note = Note(text=text, type=self.chosen, at=notemod.stamp())
        if self.index is None:
            if text or self.chosen != notemod.DEFAULT:
                items.append(note)
        elif self.index < len(items):
            if text or self.chosen != notemod.DEFAULT:
                items[self.index] = note
            else:
                items.pop(self.index)
        self.state.set_notes(*self.square, items)
        self.changed.emit(*self.square)
        self.close()

    def keyPressEvent(self, event):
        # A popup already closes on Escape; typing a type's letter picks it,
        # which is what makes the whole thing usable one-handed.
        letter = event.text().upper()
        for kind in notemod.TYPES:
            if kind.key and letter == kind.key and not self.field.hasFocus():
                self.choose(kind.name)
                return
        super().keyPressEvent(event)
