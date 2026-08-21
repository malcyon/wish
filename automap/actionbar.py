"""The live actions, as a row of buttons under the map.

`automap/actions.py` is the engine and has no Qt in it; this is the row. Each
button carries one action, is **disabled with the reason in its tooltip** when
the mode flag says the action is illegal, and asks first where the action
carries a `confirm` -- there is no in-game undo for anything that does.

**A stale button is safe.** `apply` re-checks legality itself, so a fight that
starts inside the poll interval is caught by the action rather than by the
button's enabled state.

**Results go to the messages panel, not to a pop-up.** What an action did is
something the player asked for; a modal box in front of the map interrupts the
game in the other window and has to be dismissed before the map is usable
again. The only dialog left is the confirmation an irreversible action asks
first, because that one needs an answer.

The quickfight watcher is a checkbox and off by default: it writes to a running
machine on an edge nobody asked for otherwise, and a setting that acts on its
own has to be turned on deliberately.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from . import actions as engine
from .panel import MUTED


class _OnePoll:
    """A target that reads each address once, for the length of one refresh.

    Six actions asking `legality` is six reads of `$6E11`, and under VICE each
    round trip hands the emulation ~14.3 ms of extra emulated time. They all
    want the same byte, so they get the same answer. Writes are not proxied:
    this is only ever handed to `legality`, and `apply` gets the real target.
    """

    def __init__(self, target):
        self.target = target
        self.seen: dict[tuple[int, int], bytes] = {}

    def read(self, addr: int, length: int) -> bytes:
        key = (addr, length)
        if key not in self.seen:
            self.seen[key] = self.target.read(addr, length)
        return self.seen[key]


#: Buttons per row. Three keeps the block no wider than the 596px map above
#: it -- one long row made the map's column 900px wide and put 300px of blank
#: paper beside a map that cannot use it.
COLUMNS = 3


class ActionBar(QWidget):
    """One button per action, and the watcher's checkbox."""

    def __init__(self, parent=None, actions=None, watcher=None, say=None):
        super().__init__(parent)
        #: Where results are reported. `MessagesPanel.say` in the window; a
        #: no-op alone, so the bar is usable without one.
        self.say = say or (lambda text, detail="", alarm=False: None)
        self.actions = tuple(actions if actions is not None else engine.actions())
        self.watcher = watcher or engine.QuickfightWatcher()
        self.last: engine.Outcome | None = None
        self.target = None          # what the window last attached
        self.disk = ""              # and which save it is, for SpellStore

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 4, 0, 2)
        grid.setSpacing(4)
        self.buttons: dict[str, QPushButton] = {}
        for i, action in enumerate(self.actions):
            button = QPushButton(action.label)
            button.setToolTip(action.description)
            button.setEnabled(False)          # nothing attached yet
            button.clicked.connect(
                lambda _checked=False, a=action: self.run(a))
            grid.addWidget(button, i // COLUMNS, i % COLUMNS)
            self.buttons[action.name] = button
        rows = (len(self.actions) + COLUMNS - 1) // COLUMNS

        self.watch_box = QCheckBox("Clear quickfight after a fight")
        self.watch_box.setToolTip(
            "When a fight ends, take everyone off quickfight. Off by default: "
            "it writes to the running game on an edge you did not ask for")
        self.watch_box.setChecked(self.watcher.enabled)
        self.watch_box.toggled.connect(self._watch_toggled)
        grid.addWidget(self.watch_box, rows, 0)

        self.note = QLabel("")
        font = self.note.font()
        font.setPointSize(8)
        self.note.setFont(font)
        self.note.setStyleSheet(f"color: {MUTED.name()}")
        self.note.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.note.setWordWrap(True)
        grid.addWidget(self.note, rows, 1, 1, COLUMNS - 1)

    def _watch_toggled(self, on: bool) -> None:
        self.watcher.enabled = on

    # -- the poll --------------------------------------------------------

    def refresh(self, target) -> None:
        """Enabled where the action is legal, and the reason where it is not.

        With no target attached every verdict is False with a reason, so the
        buttons are disabled rather than merely inert.
        """
        once = None if target is None else _OnePoll(target)
        for action in self.actions:
            verdict = action.legality(once)
            button = self.buttons[action.name]
            button.setEnabled(verdict.ok)
            button.setToolTip(verdict.reason or action.description)

    def watch(self, target) -> engine.Outcome | None:
        """One tick of the quickfight watcher. Fires on the 2-to-not-2 edge."""
        outcome = self.watcher.poll(target)
        if outcome is not None:
            self._report("quickfight", outcome)
        return outcome

    # -- running one -----------------------------------------------------

    def ask(self, question: str) -> bool:
        """The confirmation. A method so a test can answer it."""
        return QMessageBox.question(
            self, "wish", question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _report(self, what: str, outcome: engine.Outcome) -> None:
        """One line in the panel, and the same line under the buttons."""
        self.last = outcome
        line = f"{what}: {outcome.message}"
        detail = "\n".join(outcome.notes)
        self.note.setText(line)
        self.note.setToolTip(detail)
        self.say(line, detail, alarm=not outcome.ok)

    def run(self, action) -> engine.Outcome | None:
        """Ask if the action wants asking, apply it, and say what happened."""
        if action.confirm and not self.ask(action.confirm):
            return None
        outcome = action.apply(self.target, disk=self.disk)
        self._report(action.label.lower(), outcome)
        return outcome

    def attach(self, target, disk: str = "") -> None:
        """The target and the save these buttons act on, each poll.

        `disk` keys the stored spell lists. The map does not open a file, so it
        is empty unless a host tells us better, and `SpellStore` keys that as
        the unknown disk rather than refusing.
        """
        self.target = target
        self.disk = disk
        self.refresh(target)
