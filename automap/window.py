"""The PyQt6 map window.

Deliberately thin. All the geometry is in `render.py` and all the knowledge is
in `state.py`; this paints primitives and forwards key presses. Keeping it that
way is what lets the map be developed and tested without a display -- see
`to_svg`, which draws exactly the same primitives.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QAction, QColor, QFont, QKeySequence, QPainter, QPen,
                         QPolygonF)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QGridLayout, QInputDialog,
                             QLabel, QMainWindow, QStackedWidget, QStatusBar,
                             QToolTip, QWidget)

from por.geo import GRID

from . import combat
from .render import (CELL, MARGIN, Label, Line, Poly, Rect, map_primitives,
                     party_marker)
from .config import Settings
from .live import read_snapshot
from .panel import BottomStrip, RosterPanel
from .target import MonitorBusy, NotConnected, monitor_listening

PAPER = QColor("#fbfcfd")
LATTICE = QColor("#dbe3ec")
INK = QColor("#16202b")
ROOF = QColor("#e7ecf2")
PARTY = QColor("#0067c7")
WIZARD = QColor("#9e2b9e")
NOTE = QColor("#b8601f")
ALARM = QColor("#c0392b")       # something is wrong and it is not our doing

# The fight. Party green and enemies red, as Gold Box Companion has them, in the
# shades the roster panel already uses for hit points so that the two halves of
# the tab agree with each other.
FRIEND = QColor("#2f7d4f")
FOE = QColor("#c0392b")
FADED = QColor("#a9b4bf")
BLOCK = QColor("#e7ecf2")


class MapCanvas(QWidget):
    """Paints the current map."""

    def __init__(self, state, host=None):
        super().__init__(host)
        self.state = state
        # Held rather than asked for: the canvas is centred inside a container
        # widget, so `parent()` is that container and not the window.
        self.host = host
        self.setMinimumSize(GRID * CELL + MARGIN * 2, GRID * CELL + MARGIN * 2)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def square_at(self, px: float, py: float) -> tuple[int, int] | None:
        x = int((px - MARGIN) // CELL)
        y = int((py - MARGIN) // CELL)
        return (x, y) if 0 <= x < GRID and 0 <= y < GRID else None

    def mousePressEvent(self, event):
        square = self.square_at(event.position().x(), event.position().y())
        if square:
            self.host.edit_note(*square)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), PAPER)

        p.setPen(QPen(LATTICE, 1))
        span = GRID * CELL
        for i in range(GRID + 1):
            at = MARGIN + i * CELL
            p.drawLine(at, MARGIN, at, MARGIN + span)
            p.drawLine(MARGIN, at, MARGIN + span, at)

        st = self.state
        if st.geo is None:
            # No area yet: before a save is loaded, or while the party is on a
            # map we cannot name. An empty grid and a line of text beats an
            # error dialog -- the game may simply not have started.
            p.setPen(QPen(ALARM if self.host.alarm else INK))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       self.host._waiting or st.area_label)
            return

        visible = None if not st.reveal else st.is_visible
        for prim in map_primitives(st.geo, visible):
            self._draw(p, prim)
        self._draw(p, party_marker(st.x, st.y, st.facing))

        p.setPen(QPen(NOTE))
        p.setFont(QFont("sans", 13, QFont.Weight.Bold))
        for (x, y), text in st.notes.items():
            if text and (visible is None or visible(x, y)):
                p.drawText(QRectF(MARGIN + x * CELL, MARGIN + y * CELL,
                                  CELL, CELL),
                           Qt.AlignmentFlag.AlignCenter, "*")

    def _draw(self, p: QPainter, prim) -> None:
        if isinstance(prim, Rect):
            if prim.kind == "roofed":
                p.fillRect(QRectF(prim.x, prim.y, prim.w, prim.h), ROOF)
                return
            edge = WIZARD if prim.kind == "door-wizard" else INK
            p.setPen(QPen(edge, 2))
            p.setBrush(PAPER)
            p.drawRect(QRectF(prim.x, prim.y, prim.w, prim.h))
            p.setBrush(Qt.BrushStyle.NoBrush)
        elif isinstance(prim, Line):
            width = {"wall": 3, "bar": 2, "star": 2}.get(prim.kind, 2)
            colour = WIZARD if prim.kind == "star" else INK
            pen = QPen(colour, width)
            pen.setCapStyle(Qt.PenCapStyle.SquareCap)
            p.setPen(pen)
            p.drawLine(QPointF(prim.x1, prim.y1), QPointF(prim.x2, prim.y2))
        elif isinstance(prim, Poly):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(PARTY)
            p.drawPolygon(QPolygonF([QPointF(a, b) for a, b in prim.points]))
            p.setBrush(Qt.BrushStyle.NoBrush)


class CombatCanvas(QWidget):
    """Paints the fight, in the area map's own language.

    Same graph paper, same ink, same line art -- a player should not feel they
    have changed program because a fight started. What is new is the colour:
    the party green and the enemy red, with current hit points written in the
    square, because mid-fight that is the number you look for.

    The geometry is `automap/combat.py`, which has no Qt in it; this paints what
    it yields and answers the tooltip.
    """

    def __init__(self, host=None):
        super().__init__(host)
        self.host = host
        self.battle = None
        self.box = (0, 0, combat.LEAST, combat.LEAST)
        self.cell = combat.cell_for(combat.LEAST)
        self._resize()

    def show_battle(self, battle) -> None:
        self.battle = battle
        if battle is not None:
            self.box = combat.extent(battle)
            self.cell = combat.cell_for(self.box[2])
            self._resize()
        self.update()

    def _resize(self) -> None:
        _, _, w, h = self.box
        self.setMinimumSize(w * self.cell + combat.MARGIN * 2,
                            h * self.cell + combat.MARGIN * 2)

    def tooltip_at(self, px: float, py: float) -> str | None:
        """The record of whoever is under this point, or None.

        Split out of `event` so the tooltip can be tested without a display.
        """
        if self.battle is None:
            return None
        square = combat.square_at(px, py, self.box, self.cell, combat.MARGIN)
        if square is None:
            return None
        who = self.battle.at(*square)
        return "\n".join(who.lines()) if who is not None else None

    def event(self, e):
        if e.type() == QEvent.Type.ToolTip:
            pos = e.pos()
            text = self.tooltip_at(pos.x(), pos.y())
            if text:
                QToolTip.showText(e.globalPos(), text, self)
            else:
                QToolTip.hideText()
                e.ignore()
            return True
        return super().event(e)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), PAPER)

        _, _, w, h = self.box
        cell, margin = self.cell, combat.MARGIN
        p.setPen(QPen(LATTICE, 1))
        for i in range(w + 1):
            at = margin + i * cell
            p.drawLine(at, margin, at, margin + h * cell)
        for i in range(h + 1):
            at = margin + i * cell
            p.drawLine(margin, at, margin + w * cell, at)

        if self.battle is None:
            p.setPen(QPen(INK))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "waiting for the fight")
            return
        for prim in combat.battlefield(self.battle, self.box, cell, margin):
            self._draw(p, prim)

    def _draw(self, p: QPainter, prim) -> None:
        if isinstance(prim, Rect):
            rect = QRectF(prim.x, prim.y, prim.w, prim.h)
            if prim.kind == "block":
                p.setPen(QPen(INK, 1))
                p.setBrush(BLOCK)
                p.drawRect(rect)
            elif prim.kind == "ready":
                p.setPen(QPen(INK, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(rect)
            elif prim.kind == "camera":
                # What the game itself is showing, so the two views can be read
                # against each other. Dashed, because it is not terrain.
                pen = QPen(PARTY, 1)
                pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(rect)
            else:
                colour = FRIEND if prim.kind.startswith("party") else FOE
                if prim.kind.endswith("-dim"):
                    colour = QColor(colour)
                    colour.setAlpha(70)
                p.setPen(QPen(INK, 1))
                p.setBrush(colour)
                p.drawRect(rect)
            p.setBrush(Qt.BrushStyle.NoBrush)
        elif isinstance(prim, Label):
            p.setPen(QPen(FADED if prim.kind == "hp-dim" else PAPER))
            font = QFont("sans", max(7, int(self.cell * 0.36)),
                         QFont.Weight.Bold)
            p.setFont(font)
            p.drawText(QRectF(prim.x - self.cell / 2, prim.y - self.cell / 2,
                              self.cell, self.cell),
                       Qt.AlignmentFlag.AlignCenter, prim.text)


class AutomapWindow(QMainWindow):
    """The map, which opens whether or not there is a game to watch.

    Three ordinary states, none of them an error: no emulator yet, an emulator
    with no save loaded, and a live party. The window sits in the first two
    showing an empty grid and saying what it is waiting for, and moves between
    them on its own. Quitting VICE and restarting it is handled the same way --
    the connection is simply re-established on the next tick.
    """

    statusChanged = pyqtSignal(str)     # for a host window's status bar

    #: How many map ticks per read of the live party. See `poll_live`.
    LIVE_EVERY = 5

    def __init__(self, mapper, interval_ms: int = 200, connect=None,
                 settings: Settings | None = None, drive: bool = True):
        """`drive=False` hands the connection and the clock to a host window.

        The merged `wish` window owns one `Target` for every tab, because VICE
        serves exactly one monitor connection and ignores the second in
        silence. So when hosted this window neither connects nor keeps a timer:
        it is asked to `tick()`, and a lost connection is raised for the owner
        to deal with.
        """
        super().__init__()
        self._drive = drive
        self.mapper = mapper
        self.connect_target = connect
        self.state = mapper.state
        self.settings = settings or Settings()
        self.state.reveal = self.settings.reveal
        self.state.exploration.sight = self.settings.sight
        self.setWindowTitle("Pool of Radiance - automap")

        self.canvas = MapCanvas(self.state, self)
        self.battle_canvas = CombatCanvas(self)
        # One tab, two canvases, and only ever one of them true: when the game
        # enters combat the area map becomes the combat map and changes back
        # afterwards. Two tabs would mean the useful one is always the one you
        # are not looking at. The area map's state is untouched by the swap, so
        # the explored squares are still there when the fight ends.
        self.stack = QStackedWidget()
        self.stack.addWidget(self.canvas)
        self.stack.addWidget(self.battle_canvas)
        self.battle = None
        self.roster = RosterPanel()
        self.strip = BottomStrip()
        # Roster left, map right, one strip along the bottom for what is
        # neither. The map used to be centred in the frame because it was alone
        # in the window; with the party beside it, centring only pushes the two
        # apart. The map and the party's state are looked at together.
        centre = QWidget()
        grid = QGridLayout(centre)
        grid.addWidget(self.roster, 0, 0)
        grid.addWidget(self.stack, 0, 1,
                       Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self.strip, 1, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        self.setCentralWidget(centre)
        self.setStatusBar(QStatusBar())
        self._status = QLabel()
        self.statusBar().addWidget(self._status)

        # Both a checkbox and the R key, driving one action so they cannot
        # disagree. Off by default: a map you opened because you were lost is
        # more use showing the whole area.
        reveal = QAction("Fog of war", self, checkable=True,
                         checked=self.settings.reveal,
                         shortcut=QKeySequence("R"))
        reveal.setToolTip("Hide squares the party has not seen (R)")
        reveal.triggered.connect(self._toggle_reveal)
        self.addAction(reveal)
        self._reveal_action = reveal

        self.fog_box = QCheckBox("Fog of war")
        self.fog_box.setToolTip(reveal.toolTip())
        self.fog_box.setChecked(self.settings.reveal)
        self.fog_box.toggled.connect(reveal.setChecked)
        self.fog_box.toggled.connect(self._toggle_reveal)
        self.statusBar().addPermanentWidget(self.fog_box)

        self._waiting = "" if mapper.target is not None else "looking for the game"
        self.alarm = False
        self._live_ticks = 0
        self.snapshot = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        if drive:
            self.timer.start(interval_ms)
        self._refresh()

    def _toggle_reveal(self, checked: bool) -> None:
        self.state.reveal = checked
        if self.fog_box.isChecked() != checked:
            self.fog_box.setChecked(checked)       # keep the key and box in step
        self.settings.reveal = checked
        self.settings.save()
        self._refresh()

    def tick(self) -> None:
        """Read one fix and redraw if anything moved.

        Hosted (`drive=False`), trouble is raised rather than absorbed: the
        host owns the connection and is the only thing that can reattach.
        """
        if self.mapper.target is None:
            if self._drive:
                self._try_connect()
            return
        self._live_ticks += 1
        try:
            if self.poll_battle():
                self._waiting = ""
                return
            changed = self.mapper.poll()
            self.poll_live()
        except NotConnected:
            # VICE went away. Not fatal, and not worth a dialog -- go back to
            # waiting, and pick it up again when it returns.
            if not self._drive:
                raise
            self.mapper.target = None
            self._waiting = "the emulator went away - waiting for it to come back"
            self._refresh()
            return
        except Exception as exc:                      # keep the window alive
            if not self._drive:
                raise
            self._status.setText(f"trouble reading the emulator: {exc}")
            return
        self._waiting = ""
        if changed:
            self._refresh()

    def poll_battle(self) -> bool:
        """Swap to the combat canvas while a fight is running. True if one is.

        **Gated on `$6E11`, never on the screen.** Checked once a second while
        the party is in the world -- one more round trip on the tick that reads
        the party anyway -- and on every tick once a fight has started, because
        that is when the map is worth looking at. The area map is not polled at
        all during a fight: the party is not moving through the world, and its
        explored squares sit untouched until the fight ends.
        """
        if self.battle is None and self._live_ticks % self.LIVE_EVERY:
            return False
        was, self.battle = self.battle, combat.read_battle(self.mapper.target,
                                                           self.battle)
        if self.battle is None:
            if was is not None:
                self.stack.setCurrentWidget(self.canvas)
                self._refresh()
            return False
        self.battle_canvas.show_battle(self.battle)
        self.stack.setCurrentWidget(self.battle_canvas)
        self.poll_live()
        self._say(self._battle_note(self.battle))
        return True

    @staticmethod
    def _battle_note(battle) -> str:
        def standing(side):
            return sum(1 for c in side if c.alive)
        return (f"combat   party {standing(battle.party)}/{len(battle.party)}"
                f"   enemies {standing(battle.enemies)}/{len(battle.enemies)}"
                f"   {battle.shape.width}x{battle.shape.height} squares")

    def poll_live(self) -> None:
        """Refresh the roster and the strip, every `LIVE_EVERY` ticks.

        Not every tick, and the reason is measurable: a poll's cost is the
        round trip, and under VICE each one hands the emulation ~14.3 ms of
        extra emulated time. The map's own fix is one trip; the party is one
        more (two reads inside a single resume, see `ViceTarget.read_blocks`).
        Doing it every fifth tick is once a second at the default interval,
        which is faster than hit points change and a fifth of the disturbance.

        Only the visible tab polls at all -- the host hands the target to
        whichever tab is showing -- so a hidden map costs nothing.
        """
        if self._live_ticks % self.LIVE_EVERY:
            return
        snap = read_snapshot(self.mapper.target)
        if snap is None:
            # In camp, in a menu, mid-load or at the title screen. Hold the
            # last good snapshot and say it is stale rather than blank the
            # cards, which would flicker every time the game opened a menu.
            self.roster.set_stale(True)
            self.strip.show_state(self.state, self.snapshot)
            return
        self.snapshot = snap
        self.roster.show_snapshot(snap)
        self.strip.show_state(self.state, snap)

    def _try_connect(self) -> None:
        """Attach when a monitor appears. Cheap enough to run on the tick."""
        if self.connect_target is None:
            return
        if not monitor_listening():
            self._waiting = ("waiting for the game - start VICE with its binary "
                             "monitor enabled")
            self._refresh()
            return
        try:
            self.mapper.target = self.connect_target()
        except MonitorBusy as exc:
            self._waiting = str(exc)
            self.alarm = True
        except NotConnected as exc:
            self._waiting = f"waiting for the game ({exc})"
            self.alarm = False
        else:
            self._waiting = "connected - waiting for a save to be loaded"
            self.alarm = False
        self._refresh()

    def status_text(self) -> str:
        """The line this window would put in a status bar, right now."""
        return self._status.text()

    def waiting(self, text: str, alarm: bool = False) -> None:
        """Say what is being waited for. The host sets this; alone, we do.

        `alarm` colours it red, for the one case that is not ordinary waiting:
        something else is holding the emulator's monitor, so the game *is*
        running and we cannot read it. Not a dialog -- it clears on its own
        when the other client lets go.
        """
        self._waiting = text
        self.alarm = alarm
        self._refresh()

    def _refresh(self) -> None:
        st = self.state
        self.strip.show_state(st, self.snapshot)
        if self._waiting:
            self._say(self._waiting)
            self.roster.set_message(self._waiting)
            self.canvas.update()
            return
        seen = len(st.exploration)
        mode = "revealing" if st.reveal else "whole map"
        # The area, the square and the clock live in the strip under the map
        # now. Repeating them here only crowded the line until it was elided.
        self._say(f"{seen}/256 seen   {mode}"
                  + (f"   [{st.source}]" if st.source else "")
                  + (f"   {self.mapper.fingerprint.contradictions} contradiction(s)"
                     if self.mapper.fingerprint
                     and self.mapper.fingerprint.contradictions else ""))
        self.canvas.update()

    def _say(self, text: str) -> None:
        self._status.setStyleSheet(f"color: {ALARM.name()}" if self.alarm else "")
        self._status.setText(text)
        self.statusChanged.emit(text)

    def edit_note(self, x: int, y: int) -> None:
        current = self.state.notes.get((x, y), "")
        text, ok = QInputDialog.getText(self, f"Note for ({x},{y})",
                                        "Note:", text=current)
        if ok:
            if text:
                self.state.notes[(x, y)] = text
            else:
                self.state.notes.pop((x, y), None)
            self.state.save_notes()
            self._refresh()

    def shutdown(self) -> None:
        """Save what must survive. Idempotent, and safe with no connection.

        Split out of `closeEvent` because a hosted window is never closed on
        its own -- the host closes, and the notes still have to be written.
        The connection is only ours to close when we opened it.
        """
        self.settings.window_width = self.width()
        self.settings.window_height = self.height()
        self.settings.save()
        self.state.save_notes()
        if self._drive:
            try:
                self.mapper.target.close()
            except Exception:
                pass

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)


def run(mapper, interval_ms: int | None = None, connect=None) -> int:
    app = QApplication([])
    settings = Settings.load()
    win = AutomapWindow(mapper, interval_ms or settings.interval_ms, connect,
                        settings)
    win.resize(settings.window_width, settings.window_height)
    win.show()
    return app.exec()
