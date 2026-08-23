"""The PyQt6 map window.

Deliberately thin. All the geometry is in `render.py` and all the knowledge is
in `state.py`; this paints primitives and forwards key presses. Keeping it that
way is what lets the map be developed and tested without a display -- see
`to_svg`, which draws exactly the same primitives.
"""

from __future__ import annotations

import logging
from functools import partial

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QColor, QFont, QKeySequence, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QWIDGETSIZE_MAX,
    QApplication,
    QCheckBox,
    QGridLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from por import strength as strengthmod
from por.geo import GRID
from ui.iconpaint import draw_icon

from . import actions, combat, live
from . import notes as notemod
from .actionbar import ActionBar, WarpBar
from .combatlog import CombatLog
from .commissions import CommissionsPanel
from .config import Settings, remember_geometry, restore_geometry
from .noteeditor import NotePopover
from .panel import BottomStrip, MessagesPanel, NotesPanel, RosterPanel
from .render import (
    CELL,
    CELL_MIN,
    MARGIN,
    Glyph,
    Hatch,
    Label,
    Line,
    Poly,
    Rect,
    map_primitives,
    note_primitives,
    party_marker,
)
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
# Solid rock. The old fill was ROOF's tint, which against paper reads as more
# paper; the pen is ink thinned, never the wall ink. See render.ROCK_FILL.
BLOCK = QColor("#c3d0dd")
HATCH_PEN = QColor("#68809a")


#: Said on the grid when there are no maps at all. The one failure that used
#: to go to stderr and nowhere else.
NO_MAPS = ("No game disks found, so there are no maps. "
           "File > Preferences… to say where they are.")

_notelog = logging.getLogger("wish.automap.note").info


def game_named(title: str | None):
    """The `Game` this title is, for the readers that need one."""
    from por import games
    return games.by_title(title)


class MapCanvas(QWidget):
    """Paints the current map."""

    def __init__(self, state, host=None):
        super().__init__(host)
        self.state = state
        # Held rather than asked for: the canvas is centred inside a container
        # widget, so `parent()` is that container and not the window.
        self.host = host
        #: The square a notes-panel row asked to be pointed at, until the next
        #: click anywhere. Not a selection -- nothing here is selectable.
        self.flash: tuple[int, int] | None = None
        # The floor, not `CELL`. A 596px square that could never give way was
        # a 596px floor under the whole window, and on Donald's 1080p Windows
        # desktop that put the menu bar off the top of the screen.
        self.setMinimumSize(GRID * CELL_MIN + MARGIN * 2,
                            GRID * CELL_MIN + MARGIN * 2)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def sizeHint(self):
        """What it asks for: the full-size map, so nothing changes where there
        is room for it."""
        return QSize(GRID * CELL + MARGIN * 2, GRID * CELL + MARGIN * 2)

    @property
    def cell(self) -> int:
        """How big a square is drawn, for the room the widget has been given.

        Derived from the size rather than remembered from a resize event,
        because a widget that is not on screen is not sent one until it is
        shown -- and a click, a tooltip and a note anchor all have to agree
        with what was painted whether that event has arrived or not.
        """
        room = (min(self.width(), self.height()) - MARGIN * 2) // GRID
        return max(CELL_MIN, min(CELL, room))

    @property
    def origin(self) -> tuple[int, int]:
        """Where the grid's top-left corner sits in the widget.

        The grid stays square and centred: a widget wider than it is tall
        spends the difference on paper, not on rectangles for squares.
        """
        span = GRID * self.cell
        return (self.width() - span) // 2, (self.height() - span) // 2

    def corner_of(self, x: int, y: int) -> QPoint:
        """The bottom-left corner of a square, for hanging the popover off."""
        ox, oy = self.origin
        return QPoint(ox + x * self.cell, oy + (y + 1) * self.cell)

    def square_at(self, px: float, py: float) -> tuple[int, int] | None:
        ox, oy = self.origin
        cell = self.cell
        x = int((px - ox) // cell)
        y = int((py - oy) // cell)
        return (x, y) if 0 <= x < GRID and 0 <= y < GRID else None

    def tooltip_at(self, px: float, py: float) -> str | None:
        """Every note on the square under this point, one per line.

        Split out of `event` so the tooltip can be tested without a display --
        the combat canvas does the same, and for the same reason.
        """
        square = self.square_at(px, py)
        if square is None:
            return None
        items = self.state.notes_at(*square)
        return notemod.summary(items) if items else None

    def event(self, e):
        if e.type() == QEvent.Type.ToolTip:
            pos = e.pos()
            text = self.tooltip_at(pos.x(), pos.y())
            # Never over an open popover. A tooltip is a window of its own,
            # and on Windows one appearing or closing behind a `Qt::Popup`
            # deactivates it -- which is the popover vanishing the instant it
            # opened. See `mousePressEvent`.
            if text and getattr(self.host, "_popover", None) is None:
                QToolTip.showText(e.globalPos(), text, self)
            else:
                QToolTip.hideText()
                e.ignore()
            return True
        return super().event(e)

    def mousePressEvent(self, event):
        # **Before anything opens.** Only a square with a note has a tooltip,
        # and only a square with a note failed to open its popover on Windows:
        # it appeared and closed again immediately, where a blank square was
        # fine. Qt hides the tooltip itself on a click, but it does it after
        # the popover is up, and the window closing behind the popup takes the
        # popup with it. Hiding it first leaves nothing to close.
        QToolTip.hideText()
        square = self.square_at(event.position().x(), event.position().y())
        self.flash = None
        if square is None:
            return
        at = event.globalPosition().toPoint()
        if event.button() == Qt.MouseButton.RightButton and \
                self.state.notes_at(*square):
            self.host.note_menu(*square, at)
        else:
            self.host.edit_note(*square)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), PAPER)

        cell = self.cell
        ox, oy = self.origin
        p.setPen(QPen(LATTICE, 1))
        span = GRID * cell
        for i in range(GRID + 1):
            at = i * cell
            p.drawLine(ox + at, oy, ox + at, oy + span)
            p.drawLine(ox, oy + at, ox + span, oy + at)

        st = self.state
        if st.geo is None:
            # No area yet: before a save is loaded, or while the party is on a
            # map we cannot name. An empty grid and a line of text beats an
            # error dialog -- the game may simply not have started.
            p.setPen(QPen(ALARM if self.host.alarm else INK))
            # Wrapped: "no game disks, open File > Preferences" is a sentence,
            # not a word, and an unwrapped one is clipped by the grid.
            p.drawText(self.rect(),
                       int(Qt.AlignmentFlag.AlignCenter
                           | Qt.TextFlag.TextWordWrap),
                       self.host.waiting_text() or st.area_label)
            return

        # The primitives are asked for at margin zero and the painter is moved
        # to the grid's corner instead, because the corner is not `MARGIN` in
        # both axes once the widget is not square.
        p.translate(ox, oy)
        visible = None if not st.reveal else st.is_visible
        for prim in map_primitives(st.geo, visible, cell, 0):
            self._draw(p, prim)
        # Notes are drawn **regardless of fog**: a note is something you know,
        # and hiding it because the square is currently fogged would be
        # perverse.
        #
        # **Before the party marker, not after.** At `NOTE_SIZE` 13 the note
        # sat in the corner and the two never met; at 22 the note is most of
        # the square, so on the one square that has both, something has to be
        # underneath. It is the note: where the party is standing is the one
        # thing on this map that must never be in doubt.
        for prim in note_primitives(st.notes, cell, 0):
            self._draw(p, prim)
        self._draw(p, party_marker(st.x, st.y, st.facing, cell, 0))

        if self.flash is not None:
            x, y = self.flash
            p.setPen(QPen(NOTE, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(x * cell + 1, y * cell + 1, cell - 2, cell - 2))

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
        elif isinstance(prim, Glyph):
            draw_icon(p, prim.name, prim.x, prim.y, prim.size, NOTE)


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
        # The minimum comes off `CELL_MIN`, not off the cell this fight would
        # like: the map canvas shares a stack with this one, and a stack is as
        # tall as its tallest page whichever page is showing. A minimum of
        # `cell` here would put a 600px floor back under the window the moment
        # a fight started.
        _, _, w, h = self.box
        self.setMinimumSize(w * combat.CELL_MIN + combat.MARGIN * 2,
                            h * combat.CELL_MIN + combat.MARGIN * 2)
        self.updateGeometry()

    def sizeHint(self):
        _, _, w, h = self.box
        return QSize(w * self.cell + combat.MARGIN * 2,
                     h * self.cell + combat.MARGIN * 2)

    @property
    def drawn_cell(self) -> int:
        """The cell actually painted: `self.cell` where there is room for it.

        Derived from the widget's size rather than remembered from a resize
        event, for the reason `MapCanvas.cell` gives.
        """
        _, _, w, h = self.box
        room = min((self.width() - combat.MARGIN * 2) // max(1, w),
                   (self.height() - combat.MARGIN * 2) // max(1, h))
        return max(combat.CELL_MIN, min(self.cell, room))

    def tooltip_at(self, px: float, py: float) -> str | None:
        """The record of whoever is under this point, or None.

        Split out of `event` so the tooltip can be tested without a display.
        """
        if self.battle is None:
            return None
        square = combat.square_at(px, py, self.box, self.drawn_cell,
                                  combat.MARGIN)
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
        cell, margin = self.drawn_cell, combat.MARGIN
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
        # Hatch first: it is a Rect, and the Rect branch would swallow it. When
        # the cell is too small `lines` is empty and this is a plain fill --
        # the heavy rock-edge below still carries the shape.
        if isinstance(prim, Hatch):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(BLOCK)
            p.drawRect(QRectF(prim.x, prim.y, prim.w, prim.h))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(HATCH_PEN, 1))
            for x1, y1, x2, y2 in prim.lines:
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            return
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
        elif isinstance(prim, Line):
            p.setPen(QPen(INK, 2.5 if prim.kind == "rock-edge" else 1))
            p.drawLine(QPointF(prim.x1, prim.y1), QPointF(prim.x2, prim.y2))
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

    #: Keep the combat messages the game paints over. One extra burst per tick
    #: while a fight is running and nothing at all outside one.
    COMBAT_LOG = True
    #: How many combat ticks per read of the message panel. **One is a starting
    #: point, not an answer**: a message lives about a second of emulated time
    #: (`COMBAT $28C3`, delay `$49FC`, default 2), so there is room to poll less
    #: often if the extra ~14.3 ms a tick turns out to stutter the fight. Left
    #: here rather than in `Settings` so it can be raised without a release;
    #: it belongs in the settings file once the measurement says what it costs.
    COMBAT_LOG_EVERY = 1

    #: The widest the notes, commissions and messages column may get. The
    #: panels hold short rows; past this they are mostly paper.
    SIDE_WIDTH = 460

    #: And the narrowest. A squeezed window still shows enough of a note or a
    #: commission to say which one it is; without a floor here the column was
    #: 270px of fixed width whatever the screen was (#41).
    SIDE_SQUEEZED = 160

    def __init__(self, mapper, interval_ms: int = 200, connect=None,
                 settings: Settings | None = None, drive: bool = True,
                 disks: str | None = None):
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
        self.roster.level_up_requested.connect(self._level_up)
        #: Spell names, read off the player's disks the first time a wizard is
        #: levelled and kept after. A magic-user picks its new spell by name.
        self._spell_names: dict[int, str] | None = None
        self.strip = BottomStrip()
        self.notes_panel = NotesPanel()
        self.notes_panel.chosen.connect(self.point_at)
        self.commissions = CommissionsPanel()
        # `CommissionsPanel` fixes its own width for a window where it is the
        # only thing beside the map. Here it shares a column with the notes, so
        # the cap comes off and the column decides -- otherwise every pixel the
        # window gains lands as blank paper beside a fixed 270px panel.
        self.commissions.setMaximumWidth(QWIDGETSIZE_MAX)
        # And the floor comes off with it, for the same reason in the other
        # direction: a fixed 270px was the whole of this column's minimum
        # width, and the rows inside it scroll and wrap already (#41).
        self.commissions.setMinimumWidth(self.SIDE_SQUEEZED)
        self.messages = MessagesPanel()
        self.combat_log = CombatLog()
        # Party strength, live. Nothing stores it -- `PARTYSTRENGTH` recomputes
        # it from the roster every time an area script asks -- so it is
        # recomputed here too, from the two blocks the poll already reads, and
        # it moves the moment somebody readies a weapon. It sits under the strip
        # rather than in the status bar because the one-window host hides that
        # status bar, and this is a fact about the party, not about the app.
        self.strength_label = QLabel("party strength --")
        self.strength_label.setStyleSheet("color: #5c6b7a")
        _font = self.strength_label.font()
        _font.setPointSize(8)
        self.strength_label.setFont(_font)
        self.strength_label.setToolTip(
            "How big a random encounter is. Not readable yet.")
        self.actions_bar = ActionBar(say=self.messages.say)
        # `_maps` is what the automapper loaded off the player's disks; the
        # Fast Travel row needs them to pick a landing square for the fourteen
        # areas whose arrival square nobody has harvested. Built for every
        # session since P20 measured where those landings put the party: it
        # was behind `WISH_DEBUG` for as long as that was unknown.
        # `settings` is what says which areas the dropdown offers: the player
        # ticks them in Preferences, and there is no other filter.
        # `title` is what says whether there is an area table at all: five of
        # the six titles have none, and offering Pool of Radiance's would write
        # Pool of Radiance's disk numbers into another game (#14).
        self.warp_bar = WarpBar(say=self.messages.say,
                                maps=getattr(self.mapper, "_maps", {}),
                                settings=self.settings,
                                title=self.state.title,
                                game=game_named(self.state.title))

        # Roster left, map centre, the two reading panels right, the actions
        # under the map and one strip along the bottom for what is none of
        # those. The map asks for a 596px square and takes no more, so the
        # stretch goes to the right-hand column: it is the one thing here that
        # is worth more with more room, and giving it to the map's column only
        # makes whitespace. Below 596 the map gives way -- see `MapCanvas.cell`
        # -- because that square was a floor under the whole window.
        side = QWidget()
        column = QVBoxLayout(side)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.notes_panel)
        splitter.addWidget(self.commissions)
        splitter.addWidget(self.messages)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        column.addWidget(splitter)
        # Capped, because a quest log a quarter of the window wide is a quarter
        # of the window spent on two-word rows. What the cap leaves over goes
        # to the map's column, which centres the map in it.
        side.setMaximumWidth(self.SIDE_WIDTH)
        self.side = side

        # The actions live in the map's own column, directly under the map,
        # rather than in a row of their own: they act on what is drawn above
        # them, and a grid row of their own left 180px of blank paper between
        # the two.
        middle = QWidget()
        under = QVBoxLayout(middle)
        under.setContentsMargins(0, 0, 0, 0)
        under.setSpacing(4)
        under.addWidget(self.stack, 0, Qt.AlignmentFlag.AlignHCenter)
        under.addWidget(self.actions_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        under.addWidget(self.warp_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        under.addStretch(1)
        self.map_column = middle

        centre = QWidget()
        grid = QGridLayout(centre)
        grid.addWidget(self.roster, 0, 0)
        grid.addWidget(middle, 0, 1, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(side, 0, 2)
        grid.addWidget(self.strip, 1, 0, 1, 3)
        grid.addWidget(self.strength_label, 2, 0, 1, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
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

        # A note on the square the party is standing in, without the mouse:
        # the common case while playing, with the game in the other window.
        here = QAction("Note here", self, shortcut=QKeySequence("N"))
        here.setToolTip("Put a note on the party's square (N)")
        here.triggered.connect(self.note_here)
        self.addAction(here)
        self._note_action = here

        self.fog_box = QCheckBox("Fog of war")
        self.fog_box.setToolTip(reveal.toolTip())
        self.fog_box.setChecked(self.settings.reveal)
        self.fog_box.toggled.connect(reveal.setChecked)
        self.fog_box.toggled.connect(self._toggle_reveal)
        self.statusBar().addPermanentWidget(self.fog_box)

        # Read once: the item names come off a game disk, and a card without
        # one shows nothing rather than word indices. `disks` is the resolved
        # Game directory -- the roster used to run its own search here, which
        # was the third of the three orders this application had.
        self.disks = disks
        self.item_names = live.item_names(disks, game_named(self.state.title))
        #: No maps at all is its own state, and not the same as no emulator:
        #: an emulator will not fill the grid either. Said on the grid, where
        #: the map would be, because that is where somebody is looking.
        self.no_maps = not getattr(mapper, "_maps", None)
        self._popover: NotePopover | None = None
        self._waiting = "" if mapper.target is not None else "looking for the game"
        self.alarm = False
        self._live_ticks = 0
        self.snapshot = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        if drive:
            self.timer.start(interval_ms)
        self._apply_title()
        self._refresh()

    def set_maps(self, maps: dict, title: str | None = None,
                 disks: str | None = None) -> None:
        """New game disks: draw their maps instead, without a restart.

        Reaching into the mapper's fields rather than building a new one keeps
        the explored squares, the notes and the connection -- everything the
        window is holding open -- and the four attributes below are the whole
        of what a map set is to it.
        """
        from .state import Fingerprint, ResidentGeo
        self.mapper._maps = maps
        self.mapper.fingerprint = Fingerprint(maps) if maps else None
        self.mapper.resident = (ResidentGeo(self.mapper.target)
                                if maps and self.mapper.target is not None
                                else None)
        if title:
            self.state.title = title
        self._apply_title()
        if self.state.area:
            self.state.geo = maps.get(self.state.area)
        self.no_maps = not maps
        self.disks = disks
        self.item_names = live.item_names(disks, game_named(self.state.title))
        self._refresh()

    def _apply_title(self) -> None:
        """Tell the per-title controls which game this is.

        Two of them, and both would otherwise run on Pool of Radiance's data in
        another title's session: the Fast Travel row's area list (#14) and the
        roster card's Level up button (#16).
        """
        game = game_named(self.state.title)
        # The mapper reads the party position at an address that is per title
        # too, and it is holding the descriptor the title resolved to.
        self.mapper.game = game
        self.warp_bar.set_title(self.state.title, game)
        self.roster.set_levelling(not actions.level_up_blockers(game=game))

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
            self.messages.say(f"trouble reading the emulator: {exc}",
                              alarm=True)
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
                # The last message of a fight is never painted over -- COMBAT
                # returns to LINKER with it still on screen -- so without this
                # it would be the one message the log lost.
                self.log_combat(self.combat_log.flush())
                self.stack.setCurrentWidget(self.canvas)
                self._refresh()
            return False
        self.battle_canvas.show_battle(self.battle)
        self.stack.setCurrentWidget(self.battle_canvas)
        self.poll_live()
        self.poll_combat_log()
        self._say(self._battle_note(self.battle))
        return True

    def poll_combat_log(self) -> None:
        """Read the message panel and keep whatever it finished saying."""
        if not self.COMBAT_LOG or self.battle is None:
            return
        if self._live_ticks % self.COMBAT_LOG_EVERY:
            return
        self.combat_log.note_round([c.initiative
                                    for c in self.battle.combatants])
        self.log_combat(self.combat_log.poll(self.mapper.target))

    def log_combat(self, messages) -> None:
        """Combat lines into the Messages panel.

        **Passes `dedup=False`**, and that is the whole point of the feature:
        `MessagesPanel.say` drops a line identical to the one before it, which
        is right for "waiting for the game" on every tick and wrong for two
        "MAGNUS MISSES." in a row. The log has already deduplicated, on
        consecutive identical *frames*, which is the only rule that can tell
        the two apart.
        """
        for msg in messages:
            tag = f"round {msg.round}   " if msg.round else ""
            self.messages.say(f"{tag}{msg.text}", detail="\n".join(msg.lines),
                              dedup=False)

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
        self._refresh_roster()

    def _refresh_roster(self) -> None:
        """Re-read the party and redraw the cards. Called by the poll, and
        straight after a write that changes what a card shows."""
        target = self.mapper.target
        # The buttons follow the mode flag, and the watcher gets its tick here
        # rather than from a timer of its own -- the edge it fires on is the
        # same `$6E11` this poll already reads.
        self.actions_bar.attach(target)
        self.actions_bar.watch(target)
        self.warp_bar.attach(target)

        # Every address in that read comes from the title's descriptor: Pool
        # of Radiance is $4900 plus a roster file at $8300, Curse and Silver
        # Blades are $4B00 with the roster folded in at $6700 (#29).
        game = game_named(self.state.title)
        save0_bytes, roster_bytes = live.read_blocks(target, game)
        snap = live.snapshot_from_bytes(save0_bytes, roster_bytes,
                                        self.item_names, game)
        if snap is None:
            # In camp, in a menu, mid-load or at the title screen. Hold the
            # last good snapshot and say it is stale rather than blank the
            # cards, which would flicker every time the game opened a menu.
            # The commissions panel is left alone for the same reason, and a
            # better one: plot flags do not move while the game is in a menu.
            self.roster.set_stale(True)
            self.strip.show_state(self.state, self.snapshot)
            return
        self.snapshot = snap
        self.roster.show_snapshot(snap)
        self.strip.show_state(self.state, snap)
        self.commissions.update_from(save0_bytes)
        self.show_strength(save0_bytes, roster_bytes)

    def show_strength(self, save0_bytes: bytes, roster_bytes: bytes) -> None:
        """Recompute party strength and show it under the strip.

        Live data only, and deliberately: the number is what the *running*
        game would compute, so a save file on disk would be the wrong answer
        the moment anybody readied anything. Same two blocks as the poll.

        The slums count comes with it because it is the one scaled encounter
        watched end to end -- `(strength / 3) * 2`, `ECL14 $B1B0` -- and a bare
        13 says nothing about what it costs. See `docs/114-party-strength.md`.
        """
        try:
            party = strengthmod.from_bytes(save0_bytes, roster_bytes)
        except ValueError:
            return
        self.strength_label.setText(
            f"party strength {party.value}   "
            f"slums encounter {party.slums_count} monsters")
        self.strength_label.setToolTip(
            party.detail
            + f"\n\nA slums random encounter is ({party.value} / 3) * 2 = "
              f"{party.slums_count} monsters.")

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
        # The busy-monitor line is the one that matters, and it is the one that
        # used to be red text in a status bar and nothing else. It is a message
        # like any other now, and repeats are dropped by the panel.
        self.messages.say(text, alarm=alarm)
        self._refresh()

    def waiting_text(self) -> str:
        """What the empty grid says: what is being waited for, and why.

        With no maps loaded that comes first, because the emulator is beside
        the point while there is nothing to draw -- and because this is the one
        failure that used to be reported only to a stderr that a desktop
        launcher throws away. It is said on the grid rather than in the status
        bar: the grid is where somebody looking for a map is looking, and the
        status line still belongs to the connection.
        """
        if not self.no_maps:
            return self._waiting
        return NO_MAPS + (f"  ({self._waiting})" if self._waiting else "")

    def _refresh(self) -> None:
        st = self.state
        self.strip.show_state(st, self.snapshot)
        # Cheap: the panel compares the notes to what it drew and returns.
        self.notes_panel.show_notes(st.notes)
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

    # -- notes -----------------------------------------------------------

    def edit_note(self, x: int, y: int, index: int | None = None) -> None:
        """Open the popover on a square. `index` edits an existing note.

        A popover and not a dialog: notes are made while playing, and a modal
        box in front of the map is an interruption for something that should
        cost one keystroke.
        """
        pop = NotePopover(self.state, x, y, index, self)
        pop.changed.connect(self.notes_changed)
        corner = self.canvas.mapToGlobal(self.canvas.corner_of(x, y))
        pop.move(corner)
        # A popup with no reference is collected; the reference goes when the
        # popover destroys itself, so a closed one is not kept alive here.
        pop.destroyed.connect(self._popover_gone)
        # **Before `show()`, not after.** Showing a popup pumps the platform's
        # message queue, so anything that asks "is a popover open?" during the
        # show -- the canvas suppressing its tooltip, for one -- was answered
        # "no" and acted on it.
        self._popover = pop
        pop.show()
        pop.field.setFocus()
        _notelog("popover open at %s: %s, %s notes on the square",
                 (x, y), pop.geometry().getRect(),
                 len(self.state.notes_at(x, y)))

    def _popover_gone(self, _obj=None) -> None:
        self._popover = None

    def note_here(self) -> None:
        """`N`: a note on the party's own square, if we know where that is."""
        if self.state.source or self.snapshot is not None:
            self.edit_note(self.state.x, self.state.y)

    def note_menu_entries(self, x: int, y: int):
        """What a right-click on a square with notes offers, as data.

        Data rather than a `QMenu` so the offer can be tested without a display
        -- `note_menu` is four lines on top of this.

        **No "add another".** A square holds one note. It still lists whatever
        is on the square rather than assuming one, because a file written by a
        build that allowed several has to stay editable and deletable.
        """
        entries = []
        for i, note in enumerate(self.state.notes_at(x, y)):
            entries.append((f"Edit  {note.label}",
                            partial(self.edit_note, x, y, i)))
            entries.append((f"Delete  {note.label}",
                            partial(self.delete_note, x, y, i)))
        return entries

    def note_menu(self, x: int, y: int, at: QPoint) -> None:
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        for text, call in self.note_menu_entries(x, y):
            action = menu.addAction(text)
            action.triggered.connect(lambda _checked=False, f=call: f())
        menu.exec(at)

    def delete_note(self, x: int, y: int, index: int) -> None:
        items = list(self.state.notes_at(x, y))
        if 0 <= index < len(items):
            items.pop(index)
            self.state.set_notes(x, y, items)
            self.notes_changed(x, y)

    def notes_changed(self, x: int = -1, y: int = -1) -> None:
        """Persist and redraw. Every edit goes through here."""
        self.state.save_notes()
        self.notes_panel.show_notes(self.state.notes)
        self.canvas.update()

    # -- levelling -------------------------------------------------------

    def _names_for_spells(self) -> dict[int, str]:
        """The spell-name table, or an empty one when the disks are absent.

        Absent disks are not an error here any more than they are for the item
        names: the dialog falls back to numbering the offers, which is worse
        but is not a refusal.
        """
        if self._spell_names is None:
            # `find_disks` returns the *directory*, not a list of images -- the
            # same shape `live.item_names` walks with `_disk_names`. Iterating
            # it directly crashed the window the first time a wizard levelled.
            from .live import _disk_images
            from .paths import find_disks

            self._spell_names = {}
            game = game_named(self.state.title)
            root = find_disks(game)
            for path in (_disk_images(root, game) if root else ()):
                try:
                    from por.spells import load_spell_names
                    found = load_spell_names(str(path), game)
                except Exception:                       # not the right disk
                    continue
                if found:
                    self._spell_names = found
                    break
        return self._spell_names

    def ask(self, question: str) -> bool:
        """A yes/no the player has to answer. A method so a test can answer
        it, the same way `ActionBar.ask` is."""
        from PyQt6.QtWidgets import QMessageBox
        return QMessageBox.question(
            self, "wish", question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _chosen_spell(self, record, name: str, game=None) -> int | None:
        """Which spell a magic-user learns, or None if the player backed out.

        The trainer asks, so we ask. `$215A` builds this same list and the
        level-up does not finish until one is picked -- `docs/135-levelling.md`.
        """
        from PyQt6.QtWidgets import QInputDialog
        offers = actions.LevelUp.offers(record, game)
        if not offers:
            return 0                        # nothing to learn is not a refusal
        names = self._names_for_spells()
        labels = [f"{names.get(i) or f'spell {i}'}" for i in offers]
        pick, ok = QInputDialog.getItem(
            self, "wish", f"{name} learns one new spell:", labels, 0, False)
        if not ok:
            return None
        return offers[labels.index(pick)]

    def _level_up(self, slot: int) -> None:
        """The roster card's button. The card knows which character it is.

        **The class is not asked for.** `LevelUp.class_for` picks the one whose
        threshold after the level is highest, which is the one the trainer's
        experience clamp reads -- so the ceiling stays as high as it can and
        the other class usually survives to be taken on the next press. The
        order of the questions follows from that: the class first, because only
        then is it known whether a spell has to be chosen at all.
        """
        game = game_named(self.state.title)
        action = actions.LevelUp(game)
        target = self.mapper.target
        party = actions.read_party(target)
        member = party.by_slot(slot) if party else None
        if member is None:
            self.messages.say(f"level up: no character in slot {slot}",
                              alarm=True)
            return
        blockers = actions.level_up_blockers(member.record, game)
        if blockers:
            self.messages.say(f"level up: nothing written for "
                              f"{member.name}; {actions.game_title(game)}'s "
                              f"trainer has not been measured",
                              "\n".join(blockers), alarm=True)
            return
        class_name = actions.LevelUp.class_for(member.record, game) or ""
        spell = 0
        if class_name == "magic-user":
            spell = self._chosen_spell(member.record, member.name, game)
            if spell is None:
                return                      # the player closed the dialog
        # No confirmation in the ordinary case: the button only appears on a
        # character who can level, and a save disk is a copy. The exception is
        # the clamp taking a class below a threshold it had already passed --
        # that costs a level the character earned, so it is asked about.
        plan = actions.LevelUp.preview(member.record, class_name,
                                       spell or None, game)
        if plan is not None and plan.classes_disqualified:
            lost = ", ".join(plan.classes_disqualified)
            if not self.ask(
                    f"{member.name} as a {class_name} {plan.to_level} drops "
                    f"{plan.experience_lost} experience, which takes {lost} "
                    f"below the next threshold and costs a level already "
                    f"earned. Go ahead?"):
                return
        outcome = action.apply(target, slot=slot, class_name=class_name,
                               spell=spell or None)
        self.messages.say(f"level up: {outcome.message}",
                          "\n".join(outcome.notes), alarm=not outcome.ok)
        if outcome.ok:
            # The card caches what it drew. A level-up changes the experience
            # bar, the level, and whether the button belongs there at all --
            # and a multi-class character usually still has a class to raise.
            self._refresh_roster()

    def point_at(self, x: int, y: int) -> None:
        """Flash a square, because a row in the notes list was clicked."""
        self.canvas.flash = (x, y)
        self.canvas.update()

    def shutdown(self) -> None:
        """Save what must survive. Idempotent, and safe with no connection.

        Split out of `closeEvent` because a hosted window is never closed on
        its own -- the host closes, and the notes still have to be written.
        The connection is only ours to close when we opened it.
        """
        # Only when this window is the window. Hosted, it is a page inside a
        # tab and its size is the tab's, not anything worth remembering -- and
        # writing it here is what used to overwrite the real one.
        if self._drive:
            remember_geometry(self, self.settings)
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


def run(mapper, interval_ms: int | None = None, connect=None,
        disks: str | None = None) -> int:
    app = QApplication([])
    settings = Settings.load()
    win = AutomapWindow(mapper, interval_ms or settings.interval_ms or 200,
                        connect, settings, disks=disks)
    restore_geometry(win, settings)
    win.show()
    return app.exec()
