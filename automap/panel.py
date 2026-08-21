"""The live party, drawn beside the map.

Gold Box Companion's HUD is the model and it is the right one: one card per
character carrying everything you glance at mid-fight, so that "who is hurt"
is answered by looking rather than by reading.

**Bars, not just numbers.** `5 / 7` has to be read; a bar a third empty does
not, and mid-fight that is the whole difference. The numbers stay beside the
bar for when the exact value matters.

Everything here is presentation. The decoding is `automap/live.py`, which has no
Qt in it and is tested against captured bytes.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.iconpaint import draw_icon, icon_pixmap

PAPER = QColor("#fbfcfd")
CARD = QColor("#ffffff")
LATTICE = QColor("#dbe3ec")
INK = QColor("#16202b")
MUTED = QColor("#5c6b7a")
PARTY = QColor("#0067c7")

# Hit points, by proportion: comfortable, hurt, in danger.
#
# Both boundaries fall to the worse state -- three quarters exactly is yellow, a
# quarter exactly is red -- and the constants are named `_AT_OR_BELOW` so the
# comparison cannot quietly drift back to `<`.
#
# The old `#c07d18` was an amber at luminance 0.26, dark enough to read as brown
# beside the green; this is a true yellow at 0.56.
#
# Green and red are what collapses under red-green colour blindness: simulated
# deuteranopia leaves them 1.12:1 apart, which is nothing. Nothing was added to
# separate them, because the fill length already does -- a red bar is at most a
# quarter full and a green one more than three quarters -- and the numbers are
# written across the bar.
WELL = QColor("#2f7d4f")
HURT = QColor("#e6c229")
DANGER = QColor("#c0392b")
HURT_AT_OR_BELOW = 0.75
DANGER_AT_OR_BELOW = 0.25

EXPERIENCE = QColor("#5a6ea8")

CARD_WIDTH = 248
BAR_HEIGHT = 15

NOTE = QColor("#b8601f")

# The class icons, beside the class text and never instead of it: the text is
# what a screen reader gets, and what somebody who does not recognise the icon
# gets. Three of the four are ours, because Font Awesome Free has no sword and
# its `hat-wizard` and `mask` failed at 13px -- see `docs/109-icon-choices.md`.
CLASS_ICON = {"magic-user": "wizard-hat", "cleric": "cross",
              "thief": "hood", "fighter": "sword"}
ICON_SIZE = 13


class IconRow(QWidget):
    """A few icons in a line, painted from `automap.icons`.

    Painted rather than assembled from `QLabel` pixmaps so the row costs one
    widget however many icons it holds, and so a multi-class card does not
    rebuild its layout when the classes change.
    """

    def __init__(self, size: int = ICON_SIZE, colour: QColor = MUTED,
                 parent=None):
        super().__init__(parent)
        self.size = size
        self.colour = colour
        self.names: tuple[str, ...] = ()
        self.setFixedHeight(size)
        self.setFixedWidth(0)

    def set_icons(self, names) -> None:
        self.names = tuple(n for n in names if n)
        self.setFixedWidth(len(self.names) * (self.size + 3))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, name in enumerate(self.names):
            draw_icon(p, name, i * (self.size + 3), 0, self.size, self.colour)


def hp_colour(fraction: float) -> QColor:
    if fraction <= DANGER_AT_OR_BELOW:
        return DANGER
    if fraction <= HURT_AT_OR_BELOW:
        return HURT
    return WELL


class Bar(QWidget):
    """A proportion, with its numbers written across it.

    Painted rather than assembled from a `QProgressBar` because the colour
    carries meaning here -- a hit point bar changes colour as it empties -- and
    a styled progress bar fights the platform theme over exactly that.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fraction = 0.0
        self.text = ""
        self.colour = WELL
        self.setFixedHeight(BAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    def set(self, fraction: float, text: str, colour: QColor) -> None:
        self.fraction = max(0.0, min(1.0, fraction))
        self.text, self.colour = text, colour
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(QPen(LATTICE))
        p.setBrush(PAPER)
        p.drawRoundedRect(rect, 3, 3)
        if self.fraction > 0:
            fill = rect.adjusted(1, 1, -1, -1)
            fill.setWidth(int(fill.width() * self.fraction))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.colour)
            p.drawRoundedRect(fill, 2, 2)
        p.setPen(QPen(INK))
        font = QFont()
        font.setPointSize(8)
        p.setFont(font)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text)


def _label(text="", *, bold=False, muted=False, size=0) -> QLabel:
    lab = QLabel(text)
    font = lab.font()
    if bold:
        font.setBold(True)
    if size:
        font.setPointSize(size)
    lab.setFont(font)
    if muted:
        lab.setStyleSheet(f"color: {MUTED.name()}")
    return lab


class CharacterCard(QFrame):
    """One character: name, class and level, AC and THAC0, bars, what is in
    hand, and what is on them."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"CharacterCard {{ background: {CARD.name()};"
            f" border: 1px solid {LATTICE.name()}; border-radius: 4px; }}")
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 6)
        box.setSpacing(3)

        top = QHBoxLayout()
        self.name = _label(bold=True)
        # Only the conditions the record really tells us: at 0 hit points, and
        # levels drained. Nothing else on a character is decoded.
        self.conditions = IconRow(colour=DANGER)
        self.combat = _label(muted=True, size=8)
        top.addWidget(self.name)
        top.addWidget(self.conditions)
        top.addStretch(1)
        top.addWidget(self.combat)
        box.addLayout(top)

        klass_row = QHBoxLayout()
        klass_row.setSpacing(4)
        self.class_icons = IconRow()
        self.klass = _label(muted=True, size=8)
        klass_row.addWidget(self.class_icons)
        klass_row.addWidget(self.klass)
        klass_row.addStretch(1)
        box.addLayout(klass_row)

        self.hp = Bar()
        box.addWidget(self.hp)

        # One experience bar per class: a multi-class character levels each
        # class separately, so a single bar would have to pick one and lie
        # about the other. Bars are made once and hidden, never rebuilt, so a
        # poll never re-lays-out the card.
        self.xp = [Bar() for _ in range(3)]
        for bar in self.xp:
            box.addWidget(bar)

        # What is in hand, under the bars. Readied only -- the whole inventory
        # would swamp the card -- one elided line with the full list in the
        # tooltip, and a **blank line** for a character carrying nothing
        # readied: the absence is the information, and the word "none" is not.
        self.readied = _label(size=8, muted=True)
        self.readied.setMinimumHeight(14)
        box.addWidget(self.readied)

        # Always present, even when empty: a strip that appears and disappears
        # would shift every card below it each time a spell expires.
        self.effects = _label(size=8, muted=True)
        self.effects.setMinimumHeight(14)
        self.effects.setWordWrap(True)
        box.addWidget(self.effects)

    def show_character(self, who) -> None:
        self.name.setText(who.name)
        ac = "--" if who.armour_class is None else who.armour_class
        thac0 = "--" if who.thac0 is None else who.thac0
        self.combat.setText(f"AC {ac}   THAC0 {thac0}")
        self.klass.setText(f"{who.class_text}  {who.level_text}")
        self.class_icons.set_icons(CLASS_ICON.get(c.name) for c in who.classes)
        self.class_icons.setToolTip(who.class_text)
        conditions = who.conditions
        self.conditions.set_icons(icon for icon, _ in conditions)
        self.conditions.setToolTip("\n".join(why for _, why in conditions))

        hp = "--" if who.hp is None else who.hp
        self.hp.set(who.hp_fraction, f"{hp} / {who.hp_max} hp",
                    hp_colour(who.hp_fraction))
        self.hp.setToolTip("current hit points from the roster block; the "
                           "maximum from the character record")

        for bar, klass in zip(self.xp, who.classes):
            if klass.at_ceiling:
                # A class at its ceiling has no next threshold, so an empty bar
                # would read as "no progress" when it means the opposite.
                bar.set(1.0, f"{klass.name} maximum", EXPERIENCE)
            else:
                bar.set(klass.fraction or 0.0,
                        f"{klass.experience} / {klass.next_threshold} xp",
                        EXPERIENCE)
            bar.setToolTip(
                f"{klass.name} level {klass.level}. For a multi-class "
                "character the split of experience between classes is not "
                "established, so each bar uses the one stored number")
            bar.show()
        for bar in self.xp[len(who.classes):]:
            bar.hide()

        self.show_readied(who.readied)

        self.effects.setText("   ".join(e.label for e in who.effects))
        self.effects.setToolTip("\n".join(e.detail for e in who.effects))

    def show_readied(self, items) -> None:
        """One line of what is in hand, elided to the card's width.

        Elided here rather than by `QLabel`, because a label that elides is a
        label that has already claimed the width -- and the card is 248px wide
        by design.
        """
        self.readied_items = tuple(items)
        text = ", ".join(self.readied_items)
        metrics = QFontMetrics(self.readied.font())
        self.readied.setText(metrics.elidedText(
            text, Qt.TextElideMode.ElideRight, CARD_WIDTH - 20))
        self.readied.setToolTip("\n".join(self.readied_items))


class RosterPanel(QWidget):
    """The cards, down the left. Scrolls, because eight cards outrun a window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(CARD_WIDTH + 22)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self.heading = _label("Party", bold=True)
        outer.addWidget(self.heading)

        inner = QWidget()
        self.column = QVBoxLayout(inner)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(6)
        self.column.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        self.cards: list[CharacterCard] = []
        self.set_message("waiting for a game")

    def _card(self, index: int) -> CharacterCard:
        while len(self.cards) <= index:
            card = CharacterCard()
            self.column.insertWidget(len(self.cards), card)
            self.cards.append(card)
        return self.cards[index]

    def set_message(self, text: str) -> None:
        """No party to show. Says why rather than showing empty cards."""
        self.heading.setText(f"Party - {text}" if text else "Party")

    def set_stale(self, stale: bool) -> None:
        """The last good snapshot, held while the game is in a menu or loading.

        Saying so beats pretending: during a disk load these numbers are
        seconds old.
        """
        self.set_message("not readable right now" if stale else "")

    def show_snapshot(self, snap) -> None:
        for i, who in enumerate(snap.characters):
            card = self._card(i)
            card.show_character(who)
            card.show()
        for card in self.cards[len(snap.characters):]:
            card.hide()
        self.set_stale(False)


class BottomStrip(QWidget):
    """Where, when, which area, what is on the party, and what is loaded."""

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 4, 0, 0)
        box.setSpacing(2)

        row = QHBoxLayout()
        row.setSpacing(16)
        self.where = _label("-")
        self.clock = _label("-")
        self.area = _label("-")
        self.effects = _label("-", muted=True, size=8)
        for widget in (self.where, self.clock, self.area):
            row.addWidget(widget)
        row.addWidget(self.effects, 1)

        # Collapsed by default. The loader's cache is of interest while reverse
        # engineering and of none at all while playing.
        self.toggle = QToolButton()
        self.toggle.setText("Loaded files")
        self.toggle.setCheckable(True)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.toggled.connect(self._toggled)
        row.addWidget(self.toggle)
        box.addLayout(row)

        self.loaded = _label("", muted=True, size=8)
        self.loaded.setWordWrap(True)
        self.loaded.hide()
        box.addWidget(self.loaded)

    def _toggled(self, on: bool) -> None:
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if on
                                 else Qt.ArrowType.RightArrow)
        self.loaded.setVisible(on)

    def show_state(self, state, snap=None) -> None:
        """The map's own state answers "where"; the snapshot answers the rest.

        The square and facing come from `AutomapState` on purpose: it prefers
        the game's own status line, which is right the moment the screen
        settles, where the memory copy at `$49C0` lags a move.
        """
        # `source` is empty until the first fix lands. Before that (0,0) facing
        # north is not where the party is; it is the dataclass's defaults.
        self.where.setText(
            f"({state.x},{state.y}) facing {state.facing_letter}"
            if state.source else "square --")
        self.area.setText(state.area_label)
        if snap is None:
            self.clock.setText("clock --:--")
            self.effects.setText("party effects: not readable right now")
            return
        self.clock.setText(snap.clock_text)
        party = snap.party_effects
        text = "party effects: " + ("   ".join(e.label for e in party)
                                    if party else "none")
        # Monster effects are counted rather than listed: they belong to
        # whatever is being fought, and the combat view is where they will mean
        # something. Counting them at least says the table is not empty.
        monsters = snap.monster_effects
        if monsters:
            text += f"   (+{len(monsters)} on monsters)"
        self.effects.setText(text)
        self.effects.setToolTip("\n".join(e.detail for e in party + monsters))
        self.loaded.setText("loaded files: " + " ".join(
            f"{b:02X}" for b in snap.loaded_files))


class NotesPanel(QWidget):
    """Every note in this area, with its square.

    This is what makes notes useful for *finding* something again, which the
    icons on the map alone do not solve: the map answers "what is here", the
    list answers "where was that trainer".

    Clicking a row emits `chosen`; the window flashes the square. The list is
    rebuilt only when the notes actually change, so a poll does not throw away
    the row you were about to click.
    """

    chosen = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self.heading = _label("Notes", bold=True)
        outer.addWidget(self.heading)

        self.list = QListWidget()
        self.list.setFrameShape(QFrame.Shape.StyledPanel)
        self.list.setStyleSheet(
            f"QListWidget {{ background: {CARD.name()}; border: 1px solid "
            f"{LATTICE.name()}; border-radius: 4px; }}")
        self.list.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.list.setWordWrap(True)
        self.list.itemClicked.connect(self._clicked)
        outer.addWidget(self.list, 1)
        self._shown: tuple = ()

    def _clicked(self, item: QListWidgetItem) -> None:
        square = item.data(Qt.ItemDataRole.UserRole)
        if square:
            self.chosen.emit(*square)

    @staticmethod
    def _signature(notes) -> tuple:
        return tuple((square, tuple((n.type, n.text) for n in items))
                     for square, items in sorted(notes.items()))

    def show_notes(self, notes) -> None:
        signature = self._signature(notes)
        if signature == self._shown:
            return
        self._shown = signature
        self.list.clear()
        count = 0
        for square, items in sorted(notes.items()):
            for note in items:
                row = QListWidgetItem(QIcon(icon_pixmap(note.icon, ICON_SIZE,
                                                        NOTE)),
                                      f"({square[0]},{square[1]})  "
                                      f"{note.label}")
                row.setData(Qt.ItemDataRole.UserRole, square)
                row.setToolTip(note.at and f"{note.label}\nmade {note.at}"
                               or note.label)
                font = row.font()
                font.setPointSize(9)
                row.setFont(font)
                self.list.addItem(row)
                count += 1
        self.heading.setText(f"Notes ({count})" if count else "Notes")


class MessagesPanel(QWidget):
    """What the tab has done, and what it is waiting for.

    **Not a pop-up.** An action's result is something you asked for; putting it
    behind a modal box interrupts the game in the other window to tell you what
    you already wanted to know, and has to be dismissed before the map is usable
    again. It belongs on the page. Only a genuinely irreversible action still
    asks first, and that question is a dialog because it needs an answer.

    The connection's own state feeds the same panel, so "something else is
    attached to the emulator" is one more line here rather than a second
    mechanism in the status bar.
    """

    #: Kept lines. Long enough for a session's worth of actions, short enough
    #: that the panel never becomes the reason the window is slow.
    LIMIT = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self.heading = _label("Messages", bold=True)
        outer.addWidget(self.heading)

        self.list = QListWidget()
        self.list.setFrameShape(QFrame.Shape.StyledPanel)
        self.list.setStyleSheet(
            f"QListWidget {{ background: {CARD.name()}; border: 1px solid "
            f"{LATTICE.name()}; border-radius: 4px; }}")
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        outer.addWidget(self.list, 1)
        self._last = ""

    def say(self, text: str, detail: str = "", alarm: bool = False,
            dedup: bool = True) -> None:
        """One line, timestamped. Repeats of the last line are dropped.

        The connection says the same thing on every tick while it waits, and a
        panel that wrote "waiting for the game" five times a second would bury
        the line you wanted.

        **The combat log passes `dedup=False`**, because there the repeat is the
        point: "MAGNUS MISSES." twice running is two misses, and swallowing the
        second would defeat the feature that exists to catch them.
        """
        text = (text or "").strip()
        if not text or (dedup and text == self._last):
            return
        self._last = text
        row = QListWidgetItem(f"{datetime.now():%H:%M:%S}  {text}")
        font = row.font()
        font.setPointSize(9)
        row.setFont(font)
        if alarm:
            row.setForeground(DANGER)
        if detail:
            row.setToolTip(detail)
        self.list.addItem(row)
        while self.list.count() > self.LIMIT:
            self.list.takeItem(0)
        self.list.scrollToBottom()

    def lines(self) -> list[str]:
        """Every line, oldest first. What a test reads."""
        return [self.list.item(i).text() for i in range(self.list.count())]
