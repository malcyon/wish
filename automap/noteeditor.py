"""Adding, editing and deleting a note, without stopping playing.

The dialog this replaces was wrong in one specific way: it made adding a note a
modal interruption, and notes are made *while playing*, with the game in the
other window and a fight probably waiting. So this is a popover at the square --
a grid of icons, one line of text, Enter to keep, Escape to cancel -- and it
goes away by itself when it loses focus. It stayed a popover when the kinds
went from nine to twenty-five (`#166`); a dialog would have been the easy
answer and the wrong one.

**The picker is `notemod.TYPES` laid out `PICKER_COLUMNS` to a row**, because
the order in that table is a grouping -- marks, what the square holds, a
fight, a person, a place -- and five rows of five is that grouping made
visible. There are no words on the buttons: twenty-five wordless pictures are
scannable only if where a picture sits tells you something, so the layout
comes from the table rather than the table being poured into whatever width
fits.

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
    QToolButton,
    QWidget,
)

from ui.iconpaint import icon_pixmap

from . import notes as notemod
from .notes import Note
from .panel import CARD, INK, LATTICE, MUTED, NOTE
from .ui_noteeditor import Ui_NotePopover

#: Where the rows break. `automap.notes` groups the kinds five to a row, so
#: this is that table's number, not a width chosen here.
COLUMNS = notemod.PICKER_COLUMNS

#: The picker's buttons. Bigger than they were for nine kinds -- Donald's
#: *"you can make the picker bigger"* on `#166` -- because a wordless picture
#: is the whole of what a button says, and 15px was as small as the notes
#: panel draws them. Five to a row makes the grid narrower than the old
#: single row of nine even so.
BUTTON = 32
ICON = 22


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
        self.ui = Ui_NotePopover()
        self.ui.setupUi(self)

        self.head = self.ui.head
        self.head.setText(f"({x},{y})" + ("" if note is None else "  editing"))

        self.buttons: dict[str, QToolButton] = {}
        for n, kind in enumerate(notemod.TYPES):
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
            self.ui.picker.addWidget(button, *divmod(n, COLUMNS))
            self.buttons[kind.name] = button

        self.field = self.ui.field
        self.field.setText(note.text if note else "")
        self.field.setStyleSheet(f"color: {INK.name()}")
        self.field.returnPressed.connect(self.accept)

        self.keep = self.ui.keep
        self.keep.clicked.connect(self.accept)

        # Only where there is something to delete. A Delete button on a note
        # that does not exist yet would be furniture.
        self.remove = self.ui.remove
        self.remove.setIcon(QIcon(icon_pixmap("trash-can", ICON, MUTED)))
        self.remove.clicked.connect(lambda _checked=False: self.delete())
        self.remove.setVisible(note is not None)

        self.hint = self.ui.hint

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
