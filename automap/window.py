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
    QObject,
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
    QCheckBox,
    QLabel,
    QMenu,
    QToolTip,
    QWidget,
)

from goldbox import strength as strengthmod
from goldbox.geo import GRID
from ui.iconpaint import draw_icon

from . import actions, combat, live, rolls
from . import notes as notemod
from .actionbar import ActionBar, FastTravelBar
from .area import NOT_OURS
from .combatlog import CombatLog, recase
from .commissions import CommissionsPanel
from .config import Settings, remember_geometry
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
# A helpless enemy. Gold rather than a highlighter yellow, because everything
# else on this paper is a muted ink and a pure yellow would be the only thing
# in the window shouting. It is the one combatant fill light enough to need the
# hit points inked instead of papered: 6.9:1 against INK, where white on it is
# 2.3:1 and would disappear.
HELPLESS_FILL = QColor("#d4a017")
FADED = QColor("#a9b4bf")
# Solid rock. The old fill was ROOF's tint, which against paper reads as more
# paper; the pen is ink thinned, never the wall ink. See render.ROCK_FILL.
BLOCK = QColor("#c3d0dd")
HATCH_PEN = QColor("#68809a")

#: How a combatant's square is filled, by `combat.Combatant.kind` with any
#: `-dim` taken off. Unknown kinds fall back to the enemy red, which is what
#: the old `startswith("party")` test did for everything that was not the
#: party.
COMBATANT_FILL = {"party": FRIEND, "enemy": FOE, "helpless": HELPLESS_FILL}

#: And what the hit points inside it are written in. Paper on the dark fills,
#: ink on the light one, `FADED` on a dimmed square whatever colour it was.
HP_INK = {"hp-dim": FADED, "hp-ink": INK}


#: Said on the grid when there are no maps at all. The one failure that used
#: to go to stderr and nowhere else.
NO_MAPS = ("No game disks found, so there are no maps. "
           "File > Preferences… to say where they are.")

#: Said in the Messages panel when the map the machine is drawing is a Gold Box
#: map and none of the configured title's -- so the disks the window is set up
#: for are not the game that is running. Donald's wording, exactly.
#:
#: It names neither game on purpose, and it could not name the second one
#: anyway: the check that fires it validates the title we believe rather than
#: identifying the one that is there. What was believed, and what was seen, go
#: to the debug log -- `Automapper._contradicted`.
WRONG_GAME = ("ERROR: Wrong game disk loaded. Disabling functionality to "
              "protect from corruption.")

#: Everything else this window has to say. A child of the `wish` logger, so
#: `wish/debuglog.py`'s handler takes it when the log is on and its level
#: swallows it when the log is off.
_log = logging.getLogger("wish.automap.window")


def game_named(title: str | None):
    """The `Game` this title is, for the readers that need one."""
    from goldbox import games
    return games.by_title(title)


class MapCanvas(QWidget):
    """Paints the current map."""

    def __init__(self, state, parent=None, host=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.state = state
        # Held rather than asked for: the canvas is centred inside a container
        # widget, so `parent()` is that container and not the window.
        self.host = host
        #: The square a notes-panel row asked to be pointed at, until the next
        #: click anywhere. Not a selection -- nothing here is selectable.
        self.flash: tuple[int, int] | None = None
        #: The square the mouse went down on, so the release can check it is
        #: still the same one. See `mousePressEvent` for why nothing opens
        #: until the button comes back up.
        self._pressed: tuple[int, int] | None = None
        self._pressed_button = None
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
        return max(CELL_MIN, room)

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
            open_already = getattr(self.host, "_popover", None) is not None
            if text and not open_already:
                QToolTip.showText(e.globalPos(), text, self)
            elif not open_already:
                # Only when there is no popover. Touching QToolTip at all
                # while a popup is up is exactly the sort of thing that has
                # been closing it, and there is nothing to hide anyway.
                QToolTip.hideText()
                e.ignore()
            return True
        return super().event(e)

    def mousePressEvent(self, event):
        """Note where the press landed. **Nothing opens here.**

        The popover used to open on the press, while the button was still
        down, and on Windows it closed itself the instant it appeared: the
        debug log showed it receiving a bare `Close` while still visible and
        still the active window, with no mouse event, no `FocusOut` and no
        `WindowDeactivate` before it. That is Qt dismissing a popup, and the
        only thing left for it to be dismissed by is the release of the very
        click that opened it -- a popup grabs the mouse, so the release lands
        on a popup that was not there when the button went down.

        Opening on the release instead means no button is down by the time
        the popup exists, and there is nothing left to straddle it.
        """
        QToolTip.hideText()
        self.flash = None
        self._pressed = self.square_at(event.position().x(),
                                       event.position().y())
        self._pressed_button = event.button()

    def mouseReleaseEvent(self, event):
        square = self.square_at(event.position().x(), event.position().y())
        pressed, self._pressed = getattr(self, "_pressed", None), None
        # Both ends on the same square, or it was a drag and not a click.
        if square is None or square != pressed:
            return
        at = event.globalPosition().toPoint()
        # **Let the tooltip finish dying first.** `QToolTip.hideText()` does
        # not destroy the tip window, it queues a `deleteLater` on it -- so on
        # a square that *has* a note, and therefore has a tooltip up, a
        # top-level window was being destroyed one turn of the event loop
        # after the popover appeared. On Windows that takes the popup with it:
        # the popover arrived half-painted and empty and was gone, with a bare
        # `Close` and no mouse or focus event before it, which is exactly what
        # the debug log showed. Only a noted square has a tooltip to destroy,
        # which is the whole of why a blank one was always fine.
        #
        # Hiding it earlier did not help, because the deletion still landed
        # after the popup. Queueing our own open *behind* it does: both go on
        # the same queue, and it went on first.
        QToolTip.hideText()
        if event.button() == Qt.MouseButton.RightButton and \
                self.state.notes_at(*square):
            QTimer.singleShot(0, partial(self.host.note_menu, *square, at))
        else:
            QTimer.singleShot(0, partial(self.host.edit_note, *square))

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
    the party green, the enemy red and a helpless enemy gold, with current hit
    points written in the square, because mid-fight that is the number you look
    for.

    The geometry is `automap/combat.py`, which has no Qt in it; this paints what
    it yields and answers the tooltip.
    """

    def __init__(self, parent=None, host=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        return max(combat.CELL_MIN, room)

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
                base = prim.kind.removesuffix("-dim")
                colour = COMBATANT_FILL.get(base, FOE)
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
            p.setPen(QPen(HP_INK.get(prim.kind, PAPER)))
            font = QFont("sans", max(7, int(self.cell * 0.36)),
                         QFont.Weight.Bold)
            p.setFont(font)
            p.drawText(QRectF(prim.x - self.cell / 2, prim.y - self.cell / 2,
                              self.cell, self.cell),
                       Qt.AlignmentFlag.AlignCenter, prim.text)


class AutomapBinding(QObject):
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

    def __init__(self, root, mapper, interval_ms: int = 200, connect=None,
                 settings: Settings | None = None, drive: bool = True,
                 disks: str | None = None):
        super().__init__()
        self.root = root
        self.ui = root.ui if hasattr(root, "ui") else root
        self._drive = drive
        self.mapper = mapper
        self.connect_target = connect
        self.state = mapper.state
        self.settings = settings or Settings()
        self.state.reveal = self.settings.reveal
        self.state.exploration.sight = self.settings.sight

        self.canvas = MapCanvas(self.state, parent=self.root, host=self)
        self.battle_canvas = CombatCanvas(parent=self.root, host=self)
        # One tab, two canvases, and only ever one of them true: when the game
        # enters combat the area map becomes the combat map and changes back
        # afterwards. Two tabs would mean the useful one is always the one you
        # are not looking at. The area map's state is untouched by the swap, so
        # the explored squares are still there when the fight ends.
        self.stack = getattr(self.ui, "map_stack", None) or self.root.findChild(QWidget, "map_stack")
        self.stack.addWidget(self.canvas)
        self.stack.addWidget(self.battle_canvas)
        self.battle = None
        self.roster = RosterPanel(self.root)
        self.roster.level_up_requested.connect(self._level_up)
        #: Spell names, read off the player's disks the first time a wizard is
        #: levelled and kept after. A magic-user picks its new spell by name.
        self._spell_names: dict[int, str] | None = None
        self.strip = BottomStrip(self.root)
        self.notes_panel = NotesPanel(self.root)
        self.notes_panel.chosen.connect(self.point_at)
        self.commissions = CommissionsPanel(self.root)
        # `CommissionsPanel` fixes its own width for a window where it is the
        # only thing beside the map. Here it shares a column with the notes, so
        # the cap comes off and the column decides -- otherwise every pixel the
        # window gains lands as blank paper beside a fixed 270px panel.
        if hasattr(self.commissions, 'scroll') and self.commissions.scroll:
            self.commissions.scroll.setMaximumWidth(QWIDGETSIZE_MAX)
        # And the floor comes off with it, for the same reason in the other
        # direction: a fixed 270px was the whole of this column's minimum
        # width, and the rows inside it scroll and wrap already (#41).
        if hasattr(self.commissions, 'scroll') and self.commissions.scroll:
            self.commissions.scroll.setMinimumWidth(self.SIDE_SQUEEZED)
        self.messages = MessagesPanel(self.root)
        self.combat_log = CombatLog()
        self.strength_label = self.root.findChild(QLabel, "strength_label")
        self.actions_bar = ActionBar(self.root, say=self.messages.say, game=game_named(self.state.title), settings=self.settings)
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
        self.fasttravel_bar = FastTravelBar(self.root, say=self.messages.say,
                                maps=getattr(self.mapper, "_maps", {}),
                                settings=self.settings,
                                title=self.state.title,
                                game=game_named(self.state.title))


        
        self._status = QLabel()

        # Both a checkbox and the R key, driving one action so they cannot
        # disagree. Off by default: a map you opened because you were lost is
        # more use showing the whole area.
        reveal = QAction("Fog of war", self, checkable=True,
                         checked=self.settings.reveal,
                         shortcut=QKeySequence("R"))
        reveal.setToolTip("Hide squares the party has not seen (R)")
        reveal.triggered.connect(self._toggle_reveal)
        if hasattr(self.root, "addAction"):
            self.root.addAction(reveal)
        self._reveal_action = reveal

        # A note on the square the party is standing in, without the mouse:
        # the common case while playing, with the game in the other window.
        here = QAction("Note here", self, shortcut=QKeySequence("N"))
        here.setToolTip("Put a note on the party's square (N)")
        here.triggered.connect(self.note_here)
        if hasattr(self.root, "addAction"):
            self.root.addAction(here)
        self._note_action = here

        self.fog_box = QCheckBox("Fog of war")
        self.fog_box.setToolTip(reveal.toolTip())
        self.fog_box.setChecked(self.settings.reveal)
        self.fog_box.toggled.connect(reveal.setChecked)
        self.fog_box.toggled.connect(self._toggle_reveal)


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
        self._waiting = "" if mapper.target is not None else "Waiting to connect..."
        #: The last swallowed poll failure, so its traceback is written once
        #: rather than on every tick.
        self._trouble = ""
        #: Whether the Messages panel has already carried `WRONG_GAME`. The
        #: refusal latches in the mapper, so without this the same line would
        #: be said on every tick for the rest of the session.
        self._said_wrong_game = False
        self.alarm = False
        self._live_ticks = 0
        self.snapshot = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        if drive:
            self.timer.start(interval_ms)
        self._apply_title()
        self._refresh()

    @staticmethod
    def _replace(placeholder: QWidget, real: QWidget) -> None:
        """Swap a .ui placeholder for a widget that needed a constructor."""
        layout = placeholder.parentWidget().layout()
        if layout is not None:
            layout.replaceWidget(placeholder, real)
        placeholder.setParent(None)

    def set_maps(self, maps: dict, title: str | None = None,
                 disks: str | None = None) -> None:
        """New game disks: draw their maps instead, without a restart.

        These maps are also the signature the running game is checked against
        (#21), so changing them takes the window's verdict on the title back to
        "no idea" -- see `Automapper.use_maps`.
        """
        self.mapper.use_maps(maps, title=title)
        self._said_wrong_game = False
        self._apply_title()
        self.no_maps = not self.mapper._maps
        self.disks = disks
        self.item_names = live.item_names(disks, game_named(self.state.title))
        self._refresh()

    def _apply_title(self) -> None:
        """Tell the per-title controls which game this is.

        Three of them, and every one would otherwise run on Pool of Radiance's
        data in another title's session: the Fast Travel row's area list (#14),
        the roster card's Level up button (#16), and the five live action
        buttons, whose every write address comes off the descriptor (#29).
        """
        game = game_named(self.state.title)
        # The mapper reads the party position at an address that is per title
        # too, and it is holding the descriptor the title resolved to.
        self.mapper.game = game
        self.fasttravel_bar.set_title(self.state.title, game)
        self.actions_bar.set_game(game)
        self.roster.set_levelling(not actions.level_up_blockers(game=game))

    def _check_the_game(self) -> None:
        """The machine is not running the title the window is set up for.

        **Said out loud, never silently.** The two per-title safeguards -- the
        Fast Travel list (#14) and the Level up button (#16) -- were built on a
        title that was only ever a preference, so believing the wrong one made
        both of them fail open and write Pool of Radiance's data into another
        game (#21). They come off here, along with everything else on the tab
        that writes to the machine: see `_refresh_roster`, which stops handing
        the emulator to the buttons the moment this is true.

        Level up is hidden rather than merely disabled, which is what
        `set_levelling(False)` already does for a title with no trainer tables.

        **It comes back**, without a word, when the machine goes on to draw a
        map that *is* ours -- a player who loads the right game into the
        emulator they already had open has fixed the problem, and only a
        positive identification lifts this. "Cannot tell" never does.
        """
        wrong = self.mapper.title_check is NOT_OURS
        if wrong == self._said_wrong_game:
            return
        self._said_wrong_game = wrong
        if wrong:
            self.roster.set_levelling(False)
            self.messages.say(WRONG_GAME, alarm=True)
        else:
            self._apply_title()

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
            self._waiting = "Game disconnected."
            self._refresh()
            return
        except Exception as exc:                      # keep the window alive
            if not self._drive:
                raise
            trouble = f"trouble reading the emulator: {exc}"
            # Once per distinct failure. The window survives a poll that throws
            # on every tick, and five tracebacks a second would bury the log it
            # is meant to leave behind.
            if trouble != self._trouble:
                self._trouble = trouble
                _log.exception("the poll raised, and was swallowed")
            self._status.setText(trouble)
            self.messages.say(trouble, alarm=True)
            return
        self._waiting = ""
        self._check_the_game()
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
                self.log_combat(self.combat_log.flush(), was)
                # ...and then forget the fight. `CombatLog` is built once a
                # session, so the round counter went on climbing from one
                # fight to the next and reached 50 in an evening. After the
                # flush, so that last message keeps its own round number.
                self.combat_log.reset_fight()
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

    def log_combat(self, messages, battle=None) -> None:
        """Combat lines into the Messages panel, each with its dice under it.

        **Passes `dedup=False`**, and that is the whole point of the feature:
        `MessagesPanel.say` drops a line identical to the one before it, which
        is right for "waiting for the game" on every tick and wrong for two
        "MAGNUS MISSES." in a row -- and just as wrong for the identical roll
        line under each of them. The log has already deduplicated, on
        consecutive identical *frames*, which is the only rule that can tell
        the two apart.

        `battle` is who was in the fight; it is passed explicitly because the
        last flush of a fight happens after `self.battle` has already gone to
        None, and without it the last message of every fight would lose its
        dice.

        **This is also where the shouting stops.** The game prints in capitals
        because the C64's character set is capitals; `combatlog.recase` turns
        the line into ordinary prose with the combatants' names capitalised,
        and the combatant list is what says which words those are. It runs
        here rather than in the log because `Message.text` is the evidence of
        what the game actually printed. The tooltip keeps the rows verbatim
        for the same reason.
        """
        battle = self.battle if battle is None else battle
        names = ({c.index: c.name for c in battle.combatants}
                 if battle is not None else {})
        for msg in messages:
            tag = f"round {msg.round}   " if msg.round else ""
            self.messages.say(f"{tag}{recase(msg.text, names.values())}",
                              detail="\n".join(msg.lines), dedup=False)
            dice = rolls.roll_line(msg, names)
            if dice:
                self.messages.say(recase(dice, names.values()), dedup=False)
            # Rolls the poll rate lost. Not shown: the roll line says the roll
            # and no more (#139). Here so the loss is measurable when somebody
            # doubts the feature, and nowhere a player will read it.
            if msg.roll is not None and msg.roll.missed:
                _log.debug("%d roll(s) resolved between two polls, unseen",
                           msg.roll.missed)

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
        if self.mapper.title_check is NOT_OURS:
            # The machine is running a different game, so every address below
            # and in every button underneath it is the wrong one (#21).
            # Withholding the target is the whole disable: each control already
            # refuses, with the reason in its tooltip, when it has nothing to
            # act on, so nothing here has to invent a sentence. Nor is the
            # party re-read: at these addresses it would be another game's
            # bytes decoded as this one's characters.
            self.actions_bar.attach(None)
            self.fasttravel_bar.attach(None)
            self.roster.set_stale(True)
            self.strip.show_state(self.state, self.snapshot)
            return
        # The buttons follow the mode flag, and the watcher gets its tick here
        # rather than from a timer of its own -- the edge it fires on is the
        # same `$6E11` this poll already reads.
        self.actions_bar.attach(target)
        self.actions_bar.watch(target)
        self.fasttravel_bar.attach(target)

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
            f"party strength {party.value}")
        self.strength_label.setToolTip(party.detail)

    def _try_connect(self) -> None:
        """Attach when a monitor appears. Cheap enough to run on the tick."""
        if self.connect_target is None:
            return
        if not monitor_listening():
            self._waiting = "Waiting to connect..."
            self._refresh()
            return
        try:
            self.mapper.target = self.connect_target()
        except MonitorBusy as exc:
            self._waiting = str(exc)
            self.alarm = True
        except NotConnected:
            self._waiting = "Waiting to connect..."
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
        pop = NotePopover(self.state, x, y, index, self.root)
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
                    from goldbox.spells import load_spell_names
                    found = load_spell_names(str(path), game)
                except Exception as exc:                # not the right disk
                    _log.debug("no spell names on %s: %s", path.name, exc)
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
            self.root, "wish", question,
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
            self.root, "wish", f"{name} learns one new spell:", labels, 0, False)
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
        party = actions.read_party(target, game)
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
                # The window is closing either way; a connection that will not
                # hang up cleanly must not stop the notes being written.
                _log.exception("closing the connection raised on shutdown")

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
