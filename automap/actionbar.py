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

`WarpBar` is the same shape for the one action that is not in that row: it is
gated on debug mode, it says in the row itself that it is unproven, and it asks
before it writes.

The quickfight watcher is a checkbox and off by default: it writes to a running
machine on an edge nobody asked for otherwise, and a setting that acts on its
own has to be turned on deliberately.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from . import actions as engine
from .area import ResidentGeo
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


#: How long to wait for an area change before saying it did not happen.
#: Thirty seconds, not five: an ordinary encounter in New Phlan takes about 25
#: to load, and the four runs that "died" in the training hall were four runs
#: of a timeout that was too short.
VERIFY_SECONDS = 30.0


class WarpBar(QWidget):
    """The Warp row: pick an area, and enter it the way the game's exits do.

    **Debug mode only** (`wish/debugmode.py`), because it writes to a running
    machine on a control one click from the map, and because a feature nobody
    in normal play needs should not be on the screen at all.

    **Nothing here has been proven against the game.** The writes are
    `NEWECL`'s own (`docs/118-debug-mode.md`); entering its handler at `$2034`
    from the key-wait loop has never been tried, so the row says so where it
    can be read without hovering anything, and the button asks before it goes.
    Everything the row refuses, it refuses with the reason -- the same rule
    `ActionBar` follows, and here the reasons are the whole diagnostic.

    The area table is `por/areas.py`, and the row holds no copy of it.
    """

    def __init__(self, parent=None, warp=None, areas=None, say=None,
                 maps=None):
        super().__init__(parent)
        self.say = say or (lambda text, detail="", alarm=False: None)
        self.warp = warp or engine.Warp()
        #: `{GEO name: Geo}`, for choosing a square in an area whose arrival
        #: square nobody has harvested. The window hands its own maps over.
        self.maps = maps if maps is not None else {}
        self.rows = self._sorted(engine.area_rows() if areas is None else areas)
        self.target = None
        self.last: engine.Outcome | None = None
        #: `(GEO names to watch for, when to give up)`, while a warp is in
        #: flight. None the rest of the time, which is when the extra read
        #: costs nothing.
        self._pending: tuple[tuple[str, ...], float] | None = None

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setSpacing(4)

        self.combo = QComboBox()
        for row in self.rows:
            self.combo.addItem(self._label(row))
        self.combo.currentIndexChanged.connect(lambda _i: self.refresh())
        grid.addWidget(self.combo, 0, 0, 1, 2)

        self.button = QPushButton("Warp To")
        self.button.setEnabled(False)
        self.button.clicked.connect(lambda _checked=False: self.run())
        grid.addWidget(self.button, 0, 2)

        self.back_button = QPushButton("Warp Back")
        self.back_button.setEnabled(False)
        self.back_button.clicked.connect(lambda _checked=False: self.run_back())
        grid.addWidget(self.back_button, 0, 3)

        self.disk = self._small(QLabel(""))
        grid.addWidget(self.disk, 1, 0, 1, 4)
        self.note = self._small(QLabel(
            "Debug mode. No warp has ever been tried on a running game: this "
            "may crash it, and the area you arrive in will assume quest flags "
            "your party never set. Use a copy of your save disk."))
        grid.addWidget(self.note, 2, 0, 1, 4)
        # Disabled with the reason in the tooltip from the start, rather than
        # enabled-looking until the first poll attaches something.
        self.refresh()

    @staticmethod
    def _sorted(rows) -> tuple:
        """By name, with the areas nobody has named last."""
        return tuple(sorted(rows, key=lambda r: (getattr(r, "name", None) is None,
                                                 (getattr(r, "name", "") or ""))))

    @staticmethod
    def _label(row) -> str:
        own = getattr(row, "label", None)
        return own if isinstance(own, str) else str(row)

    @staticmethod
    def _small(label: QLabel) -> QLabel:
        font = label.font()
        font.setPointSize(8)
        label.setFont(font)
        label.setStyleSheet(f"color: {MUTED.name()}")
        label.setWordWrap(True)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    # -- what is selected --------------------------------------------------

    def area(self):
        """The row the combo box is showing, or None if the table is empty."""
        i = self.combo.currentIndex()
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def arrival(self):
        """Where to put the party: the area's own square, else one off its map.

        Three cases in the order `docs/118-debug-mode.md` sets them out. The
        third needs the map, which is read from the player's own disks and is
        why this asks the window for them rather than for the emulator.
        """
        area = self.area()
        if area is None:
            return None
        own = self.warp.arrival_of(area)
        if own is not None:
            return own
        geo = getattr(area, "geo", None)
        return engine.walkable_square(self.maps.get(geo)) if geo else None

    # -- the poll ----------------------------------------------------------

    def attach(self, target) -> None:
        self.target = target
        self.refresh()
        self.check_arrival()

    def check_arrival(self) -> str | None:
        """Did the last warp land? An exact 1024-byte match, or nothing yet.

        `ResidentGeo.identify` compares `$0400` against the disk copies byte
        for byte, so a hit is certain and needs no fingerprinting. Checked on
        the ordinary poll rather than in a loop of its own: the window is not
        blocked for the half-minute an area change can take, and the extra
        1024-byte read stops as soon as the map arrives or the clock runs out.

        **Thirty seconds, not five.** Stepping into an ordinary encounter in
        New Phlan takes about 25 -- see "There is no training-hall wedge" in
        `docs/50-experiments.md`, which is four runs of one wrong assumption
        about a timeout.
        """
        if self._pending is None or self.target is None:
            return None
        expect, deadline = self._pending
        name = ResidentGeo(self.target).identify(self.maps) if self.maps else None
        if name is not None and name in expect:
            self._pending = None
            self._said(f"arrived: {name} is loaded at $0400, byte for byte")
            return name
        if time.monotonic() > deadline:
            self._pending = None
            self._said(f"no map from {' or '.join(expect)} at $0400 after "
                       f"{VERIFY_SECONDS:.0f}s; the game is loading, waiting "
                       f"for a disk, or the warp did not take", alarm=True)
        return None

    def _expect(self, area) -> None:
        """Start watching for the map this warp should bring up."""
        geos = tuple(getattr(area, "geos", ()) or ())
        self._pending = ((geos, time.monotonic() + VERIFY_SECONDS)
                         if geos and self.maps else None)

    def refresh(self) -> None:
        area = self.area()
        verdict = self.warp.legality(self.target, area)
        self.button.setEnabled(verdict.ok)
        self.button.setToolTip(verdict.reason or self.warp.description)
        back = self.warp.back_verdict(self.target)
        self.back_button.setEnabled(back.ok)
        self.back_button.setToolTip(
            back.reason or "return to the area the last warp started in")
        self.disk.setText(self.warp.disk_note(self.target, area))

    # -- running one -------------------------------------------------------

    def ask(self, question: str) -> bool:
        """The confirmation. A method so a test can answer it."""
        return QMessageBox.question(
            self, "wish", question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _said(self, line: str, alarm: bool = False) -> None:
        self.note.setText(line)
        self.say(line, alarm=alarm)

    def _report(self, what: str, outcome: engine.Outcome) -> None:
        self.last = outcome
        line = f"{what}: {outcome.message}"
        self.note.setText(line)
        self.note.setToolTip("\n".join(outcome.notes))
        self.say(line, "\n".join(outcome.notes), alarm=not outcome.ok)
        self.refresh()

    def run(self) -> engine.Outcome | None:
        area = self.area()
        if area is None:
            return None
        if self.warp.confirm and not self.ask(self.warp.confirm):
            return None
        outcome = self.warp.apply(self.target, area=area,
                                  arrival=self.arrival())
        if outcome.ok:
            self._expect(area)
        self._report("warp", outcome)
        return outcome

    def run_back(self) -> engine.Outcome | None:
        going = engine.area_by_id(self.warp.back.area) \
            if self.warp.back is not None else None
        outcome = self.warp.apply_back(self.target)
        if outcome.ok and going is not None:
            self._expect(going)
        self._report("warp back", outcome)
        return outcome
