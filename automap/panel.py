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

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

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
    """One character: name, class and level, AC and THAC0, two bars, effects."""

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
        self.combat = _label(muted=True, size=8)
        top.addWidget(self.name)
        top.addStretch(1)
        top.addWidget(self.combat)
        box.addLayout(top)

        self.klass = _label(muted=True, size=8)
        box.addWidget(self.klass)

        self.hp = Bar()
        box.addWidget(self.hp)

        # One experience bar per class: a multi-class character levels each
        # class separately, so a single bar would have to pick one and lie
        # about the other. Bars are made once and hidden, never rebuilt, so a
        # poll never re-lays-out the card.
        self.xp = [Bar() for _ in range(3)]
        for bar in self.xp:
            box.addWidget(bar)

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

        self.effects.setText("   ".join(e.label for e in who.effects))
        self.effects.setToolTip("\n".join(e.detail for e in who.effects))


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
