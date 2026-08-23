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

import logging
import pathlib
import traceback

from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
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

_log = logging.getLogger("wish.automap.note").info

#: The events that can take a popover down, in the order Qt would send them.
#: Logged because the popover closes itself on Windows the instant it opens on
#: a square that already has a note, and nothing in the debug log said why --
#: two guesses at the mechanism from Linux were both wrong, so the next run
#: says which event arrived rather than being reasoned about.
_CLOSERS = {
    QEvent.Type.Close: "Close",
    QEvent.Type.Hide: "Hide",
    QEvent.Type.WindowDeactivate: "WindowDeactivate",
    QEvent.Type.FocusOut: "FocusOut",
    QEvent.Type.MouseButtonPress: "MouseButtonPress",
    QEvent.Type.MouseButtonRelease: "MouseButtonRelease",
}


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
        # The state every branch below turns on, said out loud. A popover that
        # opened on a noted square arrived empty and half-painted, and the one
        # thing no log had yet was what it was holding when it did.
        _log("popover %s building: %d existing, index=%r, type=%r, text=%r, "
             "chosen=%r, label=%r", (x, y), len(existing), index,
             getattr(note, "type", None), getattr(note, "text", None),
             self.chosen, getattr(note, "label", None))

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
        self.remove = QPushButton(QIcon(icon_pixmap("trash-can", ICON, MUTED)),
                                  "Delete")
        self.remove.setFont(small)
        self.remove.setToolTip("remove this note from the square")
        self.remove.setVisible(note is not None)
        self.remove.clicked.connect(lambda _checked=False: self.delete())
        buttons.addWidget(self.remove)
        buttons.addStretch(1)
        buttons.addWidget(self.keep)
        box.addLayout(buttons)

        hint = QLabel("Enter keeps it, Escape leaves it alone")
        hint.setFont(small)
        box.addWidget(hint)
        # `isHidden`, not `isVisible`: nothing is "visible" yet, because the
        # popover itself has not been shown.
        _log("popover %s built: %d widgets, delete shown=%s",
             (x, y), len(self.findChildren(QWidget)), not self.remove.isHidden())

    # -- editing ---------------------------------------------------------

    def event(self, e):
        kind = _CLOSERS.get(e.type())
        if kind is not None:
            _log("popover %s: %s (visible=%s, active=%s)",
                 self.square, kind, self.isVisible(), self.isActiveWindow())
        if e.type() == QEvent.Type.Close:
            # **Who called `close()`.** Three fixes have been reasoned from
            # Linux and all three were wrong, because `Close` arrives here
            # bare -- no mouse event, no focus change, the popover still
            # active. This says whether Python called it, and from where: our
            # own frames mean `accept` or `delete` fired; nothing but the event
            # loop means Qt dismissed the popup itself, and the two want
            # completely different fixes.
            frames = [f for f in traceback.extract_stack()[:-1]
                      if "noteeditor" not in f.filename or f.name != "event"]
            _log("popover %s: closed from %s", self.square,
                 " <- ".join(f"{pathlib.Path(f.filename).name}:{f.lineno} "
                             f"{f.name}" for f in frames[-6:]) or "the event loop")
        return super().event(e)


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
        _log("popover %s: key %r", self.square, event.text())
        # A popup already closes on Escape; typing a type's letter picks it,
        # which is what makes the whole thing usable one-handed.
        letter = event.text().upper()
        for kind in notemod.TYPES:
            if kind.key and letter == kind.key and not self.field.hasFocus():
                self.choose(kind.name)
                return
        super().keyPressEvent(event)
