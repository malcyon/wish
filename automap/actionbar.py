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

`WarpBar` is the same shape for the one action that is not in that row: the
Fast Travel row. It asks nothing before it writes: the game itself stops and
asks for the disk it wants, so the confirmation was a question the game was
about to ask again. What travelling does not guarantee is under a help icon
beside the buttons.

The quickfight watcher is a checkbox and off by default: it writes to a running
machine on an edge nobody asked for otherwise, and a setting that acts on its
own has to be turned on deliberately.
"""

from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QToolButton,
    QWidget,
)

from ui.iconpaint import icon_pixmap

from . import actions as engine
from .area import ResidentGeo
from .panel import MUTED
from .state import visited_geos

#: Which map was found at `$0400`, and which was not, goes here rather than on
#: the face of the window: it is the evidence a bug report needs and nothing a
#: player asked for. A child of `wish`, so `wish/debuglog.py`'s handler picks
#: it up when the log is on and its level swallows it when the log is off --
#: and this module still imports nothing from `wish`.
_log = logging.getLogger("wish.automap.warp").info


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

#: The side of the help icon, in pixels. Half of it is the corner radius, so
#: the border draws a circle rather than a rounded square.
HELP_SIZE = 16


class WarpBar(QWidget):
    """The Fast Travel row: pick an area, and enter it the way the exits do.

    **`Warp` in the code, "Fast Travel" on the screen.** `NEWECL` is the game's
    own name for the mechanism and the classes keep it; the label is what a
    player is being offered.

    **Shown to everybody**, no longer only in debug mode: P20 warped into every
    area that had no arrival square and recorded where the party landed
    (`work/reports/p20-arrivals.md`), which is what the gate was waiting for.
    The one area that turned out not to be a place is not offered at all.

    **The writes are proven; the arrival is chosen.** The writes are `NEWECL`'s
    own and entering its handler at `$2034` from the key-wait loop was made
    twice in the game, the party walking afterwards (`docs/118-debug-mode.md`,
    P15). Fourteen areas have no arrival square of their own, so one is chosen
    off the map, and every area's script assumes quest flags the party never
    set. `Warp.HELP` says so, under the help icon at the end of the row.

    **Nothing is confirmed and no disk is named.** Both were dialogs and rows
    of small print in front of a feature Donald has now tested: the game stops
    and prints `INSERT SIDE # n, AND PRESS ANY KEY.` for the disk it wants,
    exactly as it does when a player walks through the same door, so warning
    about a disk beforehand told the player only what the game was about to.

    **Area 30 is not listed.** `ECL1E` is the attract-mode demo: a warp there
    leaves the world and no later warp can be started, so the session is over
    (P20). `Warp.legality` refuses it as well, for a caller that does not come
    through this dropdown; a control that offers a session-ending choice and
    then argues about it is worse than one that does not offer it.
    Everything the row refuses, it refuses with the reason -- the same rule
    `ActionBar` follows, and here the reasons are the whole diagnostic.

    **The dropdown offers what we have watched the party walk in.** Donald's
    reasoning is that travelling somewhere you have already been is a safer
    thing to offer and a purer one to play. The record is ours -- one
    `GEO*.json` under the map folder, written by the automapper -- because the
    game has none: thirty area scripts were walked from their
    area-initialisation entry and exactly one writes a persistent flag merely
    because the party arrived, `ECL00`'s first-entry-to-Phlan flag, which is
    where every game starts. See `automap/state.py::visited_geos` and
    `docs/50-experiments.md`.

    That makes the filter a convenience, not a fact about the save, so it is a
    checkbox and not a rule: empty record, no filter and the reason in its
    tooltip. **It does not narrow what a warp may do** -- `Warp.legality` and
    the arrival-square logic are unchanged, and `HELP` still says what
    arriving somewhere the party never played to costs.

    The area table is `por/areas.py`, and the row holds no copy of it.
    """

    def __init__(self, parent=None, warp=None, areas=None, say=None,
                 maps=None, visited=None):
        super().__init__(parent)
        self.say = say or (lambda text, detail="", alarm=False: None)
        self.warp = warp or engine.Warp()
        #: `{GEO name: Geo}`, for choosing a square in an area whose arrival
        #: square nobody has harvested. The window hands its own maps over.
        self.maps = maps if maps is not None else {}
        rows = engine.area_rows() if areas is None else areas
        #: Every area a warp is allowed to name, in display order. `rows` is
        #: what the dropdown is currently showing, which is a subset of this
        #: whenever the visited filter is on.
        self.all_rows = self._sorted(r for r in rows
                                     if getattr(r, "warpable", True))
        self.rows = self.all_rows
        #: Where the visited record is read from; a test points it elsewhere.
        self.visited_dir = visited
        self._visited: set[str] = set()
        self._visited_read = 0.0
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
        self.combo.currentIndexChanged.connect(lambda _i: self.refresh())
        grid.addWidget(self.combo, 0, 0, 1, 2)

        self.button = QPushButton("Fast Travel")
        self.button.setEnabled(False)
        self.button.clicked.connect(lambda _checked=False: self.run())
        grid.addWidget(self.button, 0, 2)

        self.back_button = QPushButton("Travel Back")
        self.back_button.setEnabled(False)
        self.back_button.clicked.connect(lambda _checked=False: self.run_back())
        grid.addWidget(self.back_button, 0, 3)

        self.help_icon = self._help_button(engine.Warp.HELP)
        grid.addWidget(self.help_icon, 0, 4)

        #: Show only the areas we have watched the party walk in. On by
        #: default where there is a record and off, disabled and explained
        #: where there is not -- see `set_visited_only`.
        self.visited_only = QCheckBox("Only areas I have mapped")
        self.visited_only.setFont(self.note_font())
        self.visited_only.toggled.connect(lambda _on: self.repopulate())
        grid.addWidget(self.visited_only, 1, 0, 1, 5)

        #: What the last trip did. Empty until something has been clicked --
        #: the standing warning that used to sit here is under the help icon.
        self.note = self._small(QLabel(""))
        grid.addWidget(self.note, 2, 0, 1, 5)
        self.read_visited(force=True)
        self.visited_only.setChecked(bool(self._visited))
        self.repopulate()
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
        """What the dropdown shows: the area's name, and nothing else."""
        name = getattr(row, "name", None)
        if name:
            return name
        return getattr(row, "ecl", None) or str(row)

    @staticmethod
    def _detail(row) -> str:
        """The maps and the disk, for the item's tooltip."""
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

    def note_font(self):
        """The 8-point face the row's small print uses."""
        font = self.font()
        font.setPointSize(8)
        return font

    @staticmethod
    def _help_button(text: str) -> QToolButton:
        """Font Awesome's `circle-info`, on a button whose tooltip is `text`.

        **A button rather than a label**, which is Donald's call and the right
        one: a drawn glyph on the face of a window is furniture, and nothing
        about it says there is anything to point at. `autoRaise` gives it the
        frame-on-hover every other tool button has, so the affordance is the
        style's rather than something invented here.

        **It does nothing when clicked.** The tooltip is the whole content, and
        a button that opens a dialog saying what the tooltip said is the dialog
        this row already got rid of.

        **Rich text, because that is what makes a tooltip wrap.** `QTipLabel`
        turns word wrap on only when the text might be rich text; a paragraph
        of plain text becomes one line as wide as the screen, which is no
        better than the dialog it replaced.
        """
        button = QToolButton()
        button.setIcon(QIcon(icon_pixmap("circle-info", HELP_SIZE, MUTED)))
        button.setIconSize(QSize(HELP_SIZE, HELP_SIZE))
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.WhatsThisCursor)
        # Not in the tab order: there is nothing to activate, so stopping here
        # on the way to the Fast Travel button would be a dead end.
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolTip(f"<p>{text}</p>")
        button.setAccessibleName("About fast travel")
        return button

    # -- which areas are offered -------------------------------------------

    #: How often the visited record is re-read off disk while the row is up.
    #: The party maps a new area every few minutes at best, and `refresh` runs
    #: on every poll.
    VISITED_EVERY = 5.0

    def read_visited(self, force: bool = False) -> set[str]:
        """The `GEO` names our own map files record squares for.

        Re-read rather than cached for the session: the whole point is that the
        list grows while the player walks, and a dropdown that only learns at
        startup would be wrong within the first minute.
        """
        now = time.monotonic()
        if force or now - self._visited_read >= self.VISITED_EVERY:
            self._visited = visited_geos(self.visited_dir)
            self._visited_read = now
        return self._visited

    def visited_rows(self) -> tuple:
        """The areas whose maps we have watched the party stand on.

        An area counts when **any** of its `GEO` files does: the two-map areas
        -- Kuto's Well, the lizardman keep, the Temple district -- are one
        place to a player.
        """
        seen = self.read_visited()
        return tuple(r for r in self.all_rows
                     if seen & set(getattr(r, "geos", ()) or ()))

    def set_visited_only(self, on: bool) -> None:
        self.visited_only.setChecked(bool(on))

    def repopulate(self) -> None:
        """Rebuild the dropdown, keeping the area that was selected if it
        survives the filter.

        **The filter can be empty and that is not a failure.** A player who
        installed wish after a year of play has no record at all, and an empty
        dropdown with a disabled Fast Travel button would look like a broken
        feature rather than an honest one. So an empty record turns the filter
        off, disables it, and says why in its tooltip: the full list is what is
        offered, exactly as before.
        """
        record = self.read_visited()
        wanted = self.visited_rows() if self.visited_only.isChecked() \
            else self.all_rows
        if self.visited_only.isChecked() and not wanted:
            self.visited_only.blockSignals(True)
            self.visited_only.setChecked(False)
            self.visited_only.blockSignals(False)
            wanted = self.all_rows
        self.visited_only.setEnabled(bool(record))
        self.visited_only.setToolTip(
            "wish's own record of where it has watched the party walk, one "
            "file per area under its map folder. **It is not the game's**: "
            "Pool of Radiance keeps no list of the areas a party has been "
            "in, so an area you played before installing wish, or on another "
            "machine, is not in here."
            if record else
            "Nothing mapped yet. wish records the areas it watches the party "
            "walk in, and the game itself keeps no such list, so until the "
            "mapper has seen somewhere there is nothing to filter by.")

        keeping = self.area()
        self.rows = tuple(wanted)
        self.combo.blockSignals(True)
        self.combo.clear()
        for i, row in enumerate(self.rows):
            # Names only. The map files and the disk are what this row is
            # built on and neither is anything to ask a player to read past:
            # the whole `New Phlan - GEO00, POOL3` string is the item's
            # tooltip for whoever wants it.
            self.combo.addItem(self._label(row))
            self.combo.setItemData(i, self._detail(row),
                                   Qt.ItemDataRole.ToolTipRole)
        if keeping is not None and keeping in self.rows:
            self.combo.setCurrentIndex(self.rows.index(keeping))
        self.combo.blockSignals(False)
        self.refresh()

    # -- what is selected --------------------------------------------------

    def area(self):
        """The row the combo box is showing, or None if the table is empty."""
        i = self.combo.currentIndex()
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def arrival(self):
        """Where to put the party: the area's own square, else one off its map.

        The cases `docs/118-debug-mode.md` sets out, in order. The last needs
        the map, which is read from the player's own disks and is why this asks
        the window for them rather than for the emulator.

        **Two kinds of area get no square at all**, and both are P20's findings
        (`work/reports/p20-arrivals.md`):

        * **overland** -- outdoors the party's position is `$49C3`/`$49C4` and
          every script entering one writes `[$4A18]`/`[$4A19]`, the world-map
          cell. A `GEO` square in `$C04B` there is meaningless;
        * **`dynamic_geo`** -- areas 3 and 5 choose their map at run time and
          the run caught them loading `GEO05` and `GEO04`, neither of which is
          the map `geos` names, so any square off `geos[0]` is off the wrong
          map. The arriving script places the party in any case.
        """
        area = self.area()
        if area is None:
            return None
        own = self.warp.arrival_of(area)
        if own is not None:
            return own
        if getattr(area, "outdoors", False) or getattr(area, "dynamic_geo",
                                                       False):
            return None
        geo = getattr(area, "geo", None)
        return engine.landing_square(self.maps.get(geo)) if geo else None

    # -- the poll ----------------------------------------------------------

    def attach(self, target) -> None:
        self.target = target
        self.read_visited(force=True)
        self.repopulate()
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
            place = engine.place_name(name)
            self._said(f"Arrived: {place}" if place else "Arrived.")
            _log("arrived: %s is loaded at $0400, byte for byte", name)
            return name
        if time.monotonic() > deadline:
            self._pending = None
            self._said("The area has not loaded after "
                       f"{VERIFY_SECONDS:.0f}s; the game may still be loading, "
                       "waiting for a disk, or the trip may not have taken",
                       alarm=True)
            _log("no map from %s at $0400 after %.0fs", " or ".join(expect),
                 VERIFY_SECONDS)
        return None

    def _expect(self, area) -> None:
        """Start watching for the map this warp should bring up."""
        geos = tuple(getattr(area, "geos", ()) or ())
        self._pending = ((geos, time.monotonic() + VERIFY_SECONDS)
                         if geos and self.maps else None)

    def refresh(self) -> None:
        # The record grows while the player walks, so the dropdown has to
        # notice. `read_visited` is rate-limited; `repopulate` ends by calling
        # this again, and the second pass finds nothing changed.
        before = set(self._visited)
        if self.read_visited() != before:
            self.repopulate()
            return
        area = self.area()
        verdict = self.warp.legality(self.target, area)
        self.button.setEnabled(verdict.ok)
        self.button.setToolTip(verdict.reason or self.warp.description)
        back = self.warp.back_verdict(self.target)
        self.back_button.setEnabled(back.ok)
        self.back_button.setToolTip(
            back.reason or "return to the area the last trip started in")

    # -- running one -------------------------------------------------------

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
        outcome = self.warp.apply(self.target, area=area,
                                  arrival=self.arrival())
        if outcome.ok:
            self._expect(area)
        self._report("fast travel", outcome)
        return outcome

    def run_back(self) -> engine.Outcome | None:
        going = engine.area_by_id(self.warp.back.area) \
            if self.warp.back is not None else None
        outcome = self.warp.apply_back(self.target)
        if outcome.ok and going is not None:
            self._expect(going)
        self._report("travel back", outcome)
        return outcome
