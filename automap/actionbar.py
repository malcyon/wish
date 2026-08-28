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

`FastTravelBar` is the same shape for the one action that is not in that row: the
Fast Travel row. It asks nothing before it writes: the game itself stops and
asks for the disk it wants, so the confirmation was a question the game was
about to ask again. What travelling costs is the Fast Travel button's own
tooltip, and the same sentence is a framed box in Preferences.

The quickfight watcher is a checkbox and off by default: it writes to a running
machine on an edge nobody asked for otherwise, and a setting that acts on its
own has to be turned on deliberately.
"""

from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import (
    QLabel,
    QMessageBox,
    QWidget,
)

from . import actions as engine
from .area import ResidentGeo
from .config import Settings
from .panel import (
    MUTED,
    ElidingButton,
    ElidingCheckBox,
    ElidingComboBox,
)

#: Which map was found at `$0400`, and which was not, goes here rather than on
#: the face of the window: it is the evidence a bug report needs and nothing a
#: player asked for. A child of `wish`, so `wish/debuglog.py`'s handler picks
#: it up when the log is on and its level swallows it when the log is off --
#: and this module still imports nothing from `wish`.
_log = logging.getLogger("wish.automap.fasttravel").info


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


class ActionBar(QObject):
    """One button per action, and the watcher's checkbox."""

    SHORT = 86
    BUTTON_NAMES = ("action_heal", "action_store", "action_restore",
                    "action_identify", "action_clear_qf")

    def __init__(self, root: QWidget, *, actions=None, watcher=None, say=None,
                 game=None, parent: QObject | None = None):
        super().__init__(parent)
        self.root = root
        #: Where results are reported. `MessagesPanel.say` in the window; a
        #: no-op alone, so the bar is usable without one.
        self.say = say or (lambda text, detail="", alarm=False: None)
        #: Whose addresses the buttons write to. **None is Pool of Radiance**,
        #: which is what a bar built without a window means; the window tells
        #: it the title it resolved off the disks, and again whenever those
        #: change -- `set_game`.
        self.game = game
        #: Whether the actions were handed to us wholesale. A caller that
        #: passes its own means them, so a title change does not replace them.
        self._own_actions = actions is not None
        self.actions = tuple(actions if actions is not None
                             else engine.actions(game=game))
        self.watcher = watcher or engine.QuickfightWatcher(game=game)
        self.last: engine.Outcome | None = None
        self.target = None          # what the window last attached
        self.disk = ""              # and which save it is, for SpellStore

        self.buttons: dict[str, ElidingButton] = {}
        for action, name in zip(self.actions, self.BUTTON_NAMES):
            button = root.findChild(ElidingButton, name)
            if button is not None:
                button.setText(action.label)
                button.setToolTip(action.description)
                button.setEnabled(False)          # nothing attached yet
                button.clicked.connect(
                    lambda _checked=False, a=action: self.run(a))
                self.buttons[action.name] = button

        self.watch_box = root.findChild(ElidingCheckBox, "watch_box")
        if self.watch_box is not None:
            self.watch_box.setChecked(self.watcher.enabled)
            self.watch_box.toggled.connect(self._watch_toggled)

        self.note = root.findChild(QLabel, "actions_note")
        if self.note is not None:
            self.note.setStyleSheet(f"color: {MUTED.name()}")

    def _watch_toggled(self, on: bool) -> None:
        self.watcher.enabled = on

    def set_game(self, game) -> None:
        """The session is this title now: rebuild the actions around it.

        Every address the five buttons write comes off the descriptor, so a
        title change is a new set of actions rather than a setting on the old
        ones. The watcher goes with them, and keeps whether it was ticked --
        that is the player's choice and has nothing to do with which game.
        """
        if game is self.game:
            return
        self.game = game
        if not self._own_actions:
            self.actions = tuple(engine.actions(game=game))
            for action in self.actions:
                button = self.buttons.get(action.name)
                if button is not None:
                    try:
                        button.clicked.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    button.clicked.connect(
                        lambda _checked=False, a=action: self.run(a))
        self.watcher = engine.QuickfightWatcher(
            engine.ClearQuickfight(game=game), enabled=self.watcher.enabled)
        self.refresh(self.target)

    # -- the poll --------------------------------------------------------

    def refresh(self, target) -> None:
        """Enabled where the action is legal, and the reason where it is not.

        With no target attached every verdict is False with a reason, so the
        buttons are disabled rather than merely inert.
        """
        once = None if target is None else _OnePoll(target)
        for action in self.actions:
            verdict = action.legality(once)
            button = self.buttons.get(action.name)
            if button is not None:
                button.setEnabled(verdict.ok)
                button.setToolTip(verdict.reason or action.description)

    def watch(self, target) -> engine.Outcome | None:
        """One tick of the quickfight watcher. Fires on the 2-to-not-2 edge."""
        outcome = self.watcher.poll(target)
        if outcome is not None:
            if outcome.message != "nobody was on quickfight":
                self._report("quickfight", outcome)
        return outcome

    # -- running one -----------------------------------------------------

    def ask(self, question: str) -> bool:
        """The confirmation. A method so a test can answer it."""
        parent_widget = self.root if isinstance(self.root, QWidget) else None
        return QMessageBox.question(
            parent_widget, "wish", question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _report(self, what: str, outcome: engine.Outcome) -> None:
        """One line in the panel, and the same line under the buttons."""
        self.last = outcome
        line = f"{what}: {outcome.message}"
        detail = "\n".join(outcome.notes)
        if self.note is not None and "quickfight" not in what:
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

#: The Fast Travel button's own help text, and Donald's wording exactly. The
#: same sentence is a framed box in the Preferences dialog's Fast travel
#: section, because a tooltip is only read by somebody who already suspects
#: there is something to read.
DANGER = ("Fast travel to areas you haven't been to is dangerous and can "
          "break the game.")

#: What the row says when the player has ticked nothing.
NOTHING_TICKED = "No areas ticked — Preferences ▸ Fast travel"


def no_areas(title: str | None) -> str:
    """What the row says for a title `goldbox/areas.py` has no table for.

    Five of the six titles, and the sentence is the whole feature for them.
    **It must never be Pool of Radiance's list instead**: a trip writes a
    `POOL` disk number and an `ECL` id into the running machine, and Curse's
    disks are not numbered like Pool of Radiance's -- `docs/138-multiple-games.md`
    §§6, 7.
    """
    return f"No areas are known for {title or 'this game'}."


class FastTravelBar(QObject):
    """The Fast Travel row: pick an area, and enter it the way the exits do.

    **`FastTravel` in the code, "Fast Travel" on the screen.** `NEWECL` is the game's
    own name for the mechanism and the classes keep it; the label is what a
    player is being offered.

    **Shown to everybody**, no longer only in debug mode: P20 fasttraveled into every
    area that had no arrival square and recorded where the party landed
    (`work/reports/p20-arrivals.md`), which is what the gate was waiting for.
    The one area that turned out not to be a place is not offered at all.

    **The writes are proven; the arrival is chosen.** The writes are `NEWECL`'s
    own and entering its handler at `$2034` from the key-wait loop was made
    twice in the game, the party walking afterwards (`docs/118-debug-mode.md`,
    P15). Fourteen areas have no arrival square of their own, so one is chosen
    off the map, and every area's script assumes quest flags the party never
    set. `DANGER` is the short version of that, and it is the Fast Travel
    button's own tooltip while the button is usable.

    **Nothing is confirmed and no disk is named.** Both were dialogs and rows
    of small print in front of a feature Donald has now tested: the game stops
    and prints `INSERT SIDE # n, AND PRESS ANY KEY.` for the disk it wants,
    exactly as it does when a player walks through the same door, so warning
    about a disk beforehand told the player only what the game was about to.

    **Area 30 is not listed.** `ECL1E` is the attract-mode demo: a fasttravel there
    leaves the world and no later fasttravel can be started, so the session is over
    (P20). `FastTravel.legality` refuses it as well, for a caller that does not come
    through this dropdown; a control that offers a session-ending choice and
    then argues about it is worse than one that does not offer it.
    Everything the row refuses, it refuses with the reason -- the same rule
    `ActionBar` follows, and here the reasons are the whole diagnostic.

    **The player chooses which areas are offered, in Preferences.** The row
    tried filtering by what the automapper had watched the party walk in;
    Donald threw that out -- *"I don't think we can trust our visited-areas
    record. The player might visit areas while the automapper isn't open"* --
    and he is right, because the record was only ever ours. The game keeps
    none: thirty area scripts were walked from their area-initialisation entry
    and exactly one writes a persistent flag merely because the party arrived,
    `ECL00`'s first-entry-to-Phlan flag, which is where every game starts
    (`docs/50-experiments.md`). So the list is an explicit setting --
    `Settings.chosen_areas`, ticked in Preferences ▸ Fast travel, New Phlan,
    The Slums and Sokol Keep on a fresh config.

    **Nothing ticked is an answer, not a fault.** The dropdown then says so
    and the button is disabled with the same reason, rather than looking like
    a feature that failed to load.

    **The choice narrows what is offered, never what is legal.**
    `FastTravel.legality` and the arrival-square logic are untouched.

    **One title has areas and the other five have none.** `AREAS` is Pool of
    Radiance's -- `POOL` disk numbers and `ECL` ids, both of which a trip
    writes into the machine -- so a session of any other title is offered
    nothing and told which game it is that nothing is known for. The row used
    to offer Pool of Radiance's thirty in a Curse session and fasttraveling on one
    wrote Pool of Radiance's numbers into Curse (#14); falling back to that
    list is the one answer that corrupts, so the title is asked for at
    construction and again whenever the disks change.

    The area table is `goldbox/areas.py`, and the row holds no copy of it.
    """

    SHORT = 48

    def __init__(self, root: QWidget, *, fasttravel=None, areas=None, say=None,
                 maps=None, settings: Settings | None = None,
                 title: str | None = None, game=None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.root = root
        self.say = say or (lambda text, detail="", alarm=False: None)
        self.fasttravel = fasttravel or engine.FastTravel()
        #: `{GEO name: Geo}`, for choosing a square in an area whose arrival
        #: square nobody has harvested. The window hands its own maps over.
        self.maps = maps if maps is not None else {}
        #: Which title this session is, as `AutomapState.title` spells it, and
        #: the `goldbox.games.Game` that names for the settings key. **None is
        #: Pool of Radiance**, which is what a row built without a window means
        #: and what every caller written before there was a second title meant.
        self.title = title
        self.game = game
        rows = self._rows_for_title() if areas is None else areas
        #: Every area a fasttravel is allowed to name, in display order. `rows` is
        #: what the dropdown is currently showing, which is the ticked subset
        #: of this whenever there are settings to read.
        self.all_rows = self._sorted(r for r in rows
                                     if getattr(r, "fasttravelable", True))
        #: Whose choice to honour. **None means every fasttravelable area**, which
        #: is a row built without a window -- the one construction site in the
        #: program passes the window's settings, so this is the tests' case
        #: and not a fallback anybody plays with.
        self.settings = settings
        #: Whether the areas were given to us wholesale. A caller that passes
        #: its own table means it, so a title change does not throw it away.
        self._own_areas = areas is not None
        self.rows = self.all_rows
        self.target = None
        self.last: engine.Outcome | None = None
        #: `(GEO names to watch for, when to give up)`, while a fasttravel is in
        #: flight. None the rest of the time, which is when the extra read
        #: costs nothing.
        self._pending: tuple[tuple[str, ...], float] | None = None

        self.combo = root.findChild(ElidingComboBox, "ft_combo")
        if self.combo is not None:
            self.combo.currentIndexChanged.connect(lambda _i: self.refresh())

        self.button = root.findChild(ElidingButton, "ft_button")
        if self.button is not None:
            self.button.clicked.connect(lambda _checked=False: self.run())

        self.back_button = root.findChild(ElidingButton, "ft_back_button")
        if self.back_button is not None:
            self.back_button.clicked.connect(lambda _checked=False: self.run_back())

        #: What the last trip did. Empty until something has been clicked --
        #: the standing warning is the Fast Travel button's own tooltip.
        self.note = root.findChild(QLabel, "ft_note")
        if self.note is not None:
            self.note.setStyleSheet(f"color: {MUTED.name()}")

        self.repopulate()
        # Disabled with the reason in the tooltip from the start, rather than
        # enabled-looking until the first poll attaches something.
        self.refresh()

    def _rows_for_title(self) -> tuple:
        """This title's areas, which is nothing for every title but one."""
        if self.title is None:
            return engine.area_rows()
        return engine.area_rows(self.title)

    def set_title(self, title: str | None, game=None) -> None:
        """The session is this title now. Rebuilds the dropdown.

        The window calls it when the disks change, which is the one place the
        title can change while the row is on the screen.
        """
        if (title, game) == (self.title, self.game):
            return
        self.title, self.game = title, game
        if not self._own_areas:
            self.all_rows = self._sorted(
                r for r in self._rows_for_title()
                if getattr(r, "fasttravelable", True))
        self.repopulate()

    @property
    def has_areas(self) -> bool:
        """Whether this title has an area table at all."""
        return bool(self.all_rows)

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

    # -- which areas are offered -------------------------------------------

    def chosen_rows(self) -> tuple:
        """The areas the player has ticked, in display order.

        With no settings -- a row built without a window -- every fasttravelable
        area, because there is nobody to have made a choice.
        """
        if self.settings is None:
            return self.all_rows
        wanted = set(self.settings.chosen_areas(self.game))
        return tuple(r for r in self.all_rows if getattr(r, "id", None) in wanted)

    def reload_areas(self) -> None:
        """The setting changed. Called by the Preferences dialog's table."""
        self.repopulate()

    def repopulate(self) -> None:
        """Rebuild the dropdown, keeping the selected area where it survives.

        **Nothing ticked is an answer.** The player unticked everything, so
        the dropdown says which setting to go and look at rather than sitting
        there empty, and `refresh` disables the button with the same reason.
        """
        keeping = self.area()
        self.rows = self.chosen_rows()
        if self.combo is None:
            return
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
        if not self.rows:
            # Two different empties. Nothing ticked is the player's own doing
            # and names the setting; no table at all is ours, and says which
            # game it has nothing for.
            self.combo.addItem(NOTHING_TICKED if self.has_areas
                               else no_areas(self.title))
        self.combo.setEnabled(bool(self.rows))
        if keeping is not None and keeping in self.rows:
            self.combo.setCurrentIndex(self.rows.index(keeping))
        self.combo.blockSignals(False)
        self.refresh()

    # -- what is selected --------------------------------------------------

    def area(self):
        """The row the combo box is showing, or None if the table is empty."""
        if self.combo is None:
            return None
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
        own = self.fasttravel.arrival_of(area)
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
        self.refresh()
        self.check_arrival()

    def check_arrival(self) -> str | None:
        """Did the last fasttravel land? An exact 1024-byte match, or nothing yet.

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
            # Stop watching, and say nothing. The explanation that used to go
            # here named three things that might have happened and could not
            # tell you which -- a paragraph of GUI apologising for itself, and
            # Donald had it removed. The debug log still records it.
            self._pending = None
            _log("no map from %s at $0400 after %.0fs", " or ".join(expect),
                 VERIFY_SECONDS)
        return None

    def _expect(self, area) -> None:
        """Start watching for the map this fasttravel should bring up."""
        geos = tuple(getattr(area, "geos", ()) or ())
        self._pending = ((geos, time.monotonic() + VERIFY_SECONDS)
                         if geos and self.maps else None)

    def refresh(self) -> None:
        area = self.area()
        if self.button is not None:
            if area is None and not self.rows:
                # Nothing ticked, or nothing to tick. Say that rather than the
                # emulator's verdict: there is nothing to be legal or illegal
                # about.
                self.button.setEnabled(False)
                self.button.setToolTip(
                    "No areas are ticked in Preferences ▸ Fast travel, so there "
                    "is nowhere to travel to." if self.has_areas else
                    f"{no_areas(self.title)} Its areas have not been tabulated, "
                    f"and Pool of Radiance's disk numbers and area ids would be "
                    f"the wrong thing to write here.")
            else:
                verdict = self.fasttravel.legality(self.target, area)
                self.button.setEnabled(verdict.ok)
                # `DANGER` when it is enabled, the refusal when it is not: the
                # warning is about making a trip, and a disabled button is not
                # about to make one.
                self.button.setToolTip(verdict.reason or DANGER)
        if self.back_button is not None:
            back = self.fasttravel.back_verdict(self.target)
            self.back_button.setEnabled(back.ok)
            self.back_button.setToolTip(
                back.reason or "return to the area the last trip started in")

    # -- running one -------------------------------------------------------

    def _said(self, line: str, alarm: bool = False) -> None:
        if self.note is not None:
            self.note.setText(line)
        self.say(line, alarm=alarm)

    def _report(self, what: str, outcome: engine.Outcome) -> None:
        self.last = outcome
        line = f"{what}: {outcome.message}"
        if self.note is not None:
            self.note.setText(line)
            self.note.setToolTip("\n".join(outcome.notes))
        self.say(line, "\n".join(outcome.notes), alarm=not outcome.ok)
        self.refresh()

    def run(self) -> engine.Outcome | None:
        area = self.area()
        if area is None:
            return None
        outcome = self.fasttravel.apply(self.target, area=area,
                                  arrival=self.arrival())
        if outcome.ok:
            self._expect(area)
        self._report("fast travel", outcome)
        return outcome

    def run_back(self) -> engine.Outcome | None:
        going = engine.area_by_id(self.fasttravel.back.area) \
            if self.fasttravel.back is not None else None
        outcome = self.fasttravel.apply_back(self.target)
        if outcome.ok and going is not None:
            self._expect(going)
        self._report("travel back", outcome)
        return outcome

