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

import logging
from datetime import datetime

from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QStyleOptionComboBox,
    QStylePainter,
    QWidget,
)

from goldbox.levelup import best_next_class
from ui.iconpaint import draw_icon, icon_pixmap

#: A child of the `wish` logger, so `wish/debuglog.py`'s handler takes these
#: when the log is on and the level swallows them when it is off -- without
#: `automap` importing `wish`.
log = logging.getLogger("wish.automap.panel")

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

# **There are no class icons.** There were, beside the class text; four
# 13-pixel glyphs that nobody could tell apart at that size and that said
# nothing the words "fighter/thief" beside them did not. `IconRow` stays,
# because the conditions row and the quickfight badge use it, and a skull or a
# running figure at 13px does read.
ICON_SIZE = 13


class IconRow(QWidget):
    """A few icons in a line, painted from `automap.icons`.

    Painted rather than assembled from `QLabel` pixmaps so the row costs one
    widget however many icons it holds, and so a card whose conditions change
    does not rebuild its layout.
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


# --- widgets that can be squeezed narrower than their own text ---------------
#
# The window's minimum width was the sum of the widest strings its panels
# happened to be holding, so a wider UI font dragged the window out with it:
# Windows answered 1546px where Linux answered 1071px, and a 1366px laptop
# could not show the window at all (#41).
#
# Each of these asks for exactly the width it always did -- `sizeHint` is
# untouched, so nothing about the full-size layout moves -- and elides only
# once it has been given less room than its text needs. `minimumSizeHint` is
# what a layout reads for the floor, and it is the only thing that changes.


def _squeezed(hint: QSize, floor: int) -> QSize:
    """`hint` with its width capped at `floor`. Never widens anything."""
    return QSize(min(floor, hint.width()), hint.height())


def shortened(hint: QSize, floor: int) -> QSize:
    """`hint` with its height capped at `floor`. Never heightens anything.

    The height twin of `_squeezed`, and the same argument in the other axis:
    the window's minimum *height* was the sum of the row heights its bars
    happened to want, so a larger UI font dragged the window down past a
    720-high screen with nothing open at all -- 662 at the base font here and
    805 at ten points more (#77).

    A row that is given less height than its font wants clips rather than
    eliding, so unlike the width caps this one is only ever reached by a
    window squeezed to its floor. Everything above the floor lays out exactly
    as it did.
    """
    return QSize(hint.width(), min(floor, hint.height()))


def _let_it_shrink(widget) -> None:
    """Let a layout squeeze this widget down to its `minimumSizeHint`.

    Buttons and checkboxes ship with `QSizePolicy.Minimum`, which is not a
    minimum at all: without the shrink flag a layout takes the widget's
    *`sizeHint`* as its floor, so overriding `minimumSizeHint` alone changes
    nothing. `Preferred` is the same policy with the shrink flag on -- it
    still asks for `sizeHint` and neither policy expands, so the full-size
    layout is unmoved.
    """
    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
    widget.setSizePolicy(policy)


class ElidingButton(QPushButton):
    """A push button that gives way instead of holding the window open."""

    #: A word and an ellipsis. Below this a button is a smear, and the row of
    #: them says nothing at all.
    SQUEEZED = 64

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _let_it_shrink(self)

    def minimumSizeHint(self) -> QSize:
        return _squeezed(super().minimumSizeHint(), self.SQUEEZED)

    def paintEvent(self, _event):
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        # The style's own text rect, not the widget's: eliding to anything
        # wider would cut a label that still fits, and the full-size render
        # has to come out byte for byte as it did.
        room = self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, option, self).width()
        option.text = self.fontMetrics().elidedText(
            option.text, Qt.TextElideMode.ElideRight, room)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)


class ElidingCheckBox(QCheckBox):
    """The same, for a checkbox whose label is a sentence."""

    #: Wider than a button's floor because the box itself eats the first 20.
    SQUEEZED = 96

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _let_it_shrink(self)

    def minimumSizeHint(self) -> QSize:
        return _squeezed(super().minimumSizeHint(), self.SQUEEZED)

    def paintEvent(self, _event):
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        room = self.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxContents, option, self).width()
        option.text = self.fontMetrics().elidedText(
            option.text, Qt.TextElideMode.ElideRight, room)
        painter.drawControl(QStyle.ControlElement.CE_CheckBox, option)


class ElidingComboBox(QComboBox):
    """A dropdown whose floor is not the length of the area it is showing."""

    #: Enough for a short area name. The whole row -- maps and disk -- is the
    #: item's tooltip whatever width the box is.
    SQUEEZED = 110

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _let_it_shrink(self)

    def minimumSizeHint(self) -> QSize:
        return _squeezed(super().minimumSizeHint(), self.SQUEEZED)

    def paintEvent(self, _event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        room = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, option,
            QStyle.SubControl.SC_ComboBoxEditField, self).width()
        option.currentText = self.fontMetrics().elidedText(
            option.currentText, Qt.TextElideMode.ElideRight, room)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)


class ElidingLabel(QLabel):
    """A read-out that shortens rather than setting a floor under the window.

    The text a label is holding changes while the program runs -- the bottom
    strip's party effects line grows as spells land on the party -- so a label
    that sets the window's minimum width moves that minimum under the player.
    """

    SQUEEZED = 44

    def minimumSizeHint(self) -> QSize:
        return _squeezed(super().minimumSizeHint(), self.SQUEEZED)

    def paintEvent(self, event):
        room = self.contentsRect().width()
        elided = self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, room)
        if elided == self.text():
            super().paintEvent(event)   # nothing to elide: paint it as always
            return
        painter = QPainter(self)
        # `drawItemText` rather than `drawText`, because the style sheet's
        # colour is applied by the style and not by the palette.
        self.style().drawItemText(painter, self.contentsRect(),
                                  int(self.alignment()), self.palette(),
                                  self.isEnabled(), elided,
                                  self.foregroundRole())


def _label(text="", *, bold=False, muted=False, size=0,
           elide=False) -> QLabel:
    lab = ElidingLabel(text) if elide else QLabel(text)
    font = lab.font()
    if bold:
        font.setBold(True)
    if size:
        font.setPointSize(size)
    lab.setFont(font)
    if muted:
        lab.setStyleSheet(f"color: {MUTED.name()}")
    return lab



class CharacterCard(QObject):
    """One character: name, class and level, AC and THAC0, bars, what is in
    hand, what is on them, and whether they are on quickfight.

    **The Level Up button lives here and nowhere else.** It sits at the right
    end of the class-and-level line, and it is *hidden* -- not disabled --
    unless that character has the experience for another level. A button that
    is there only when it can be used needs no label saying which character it
    means: the card is the answer.

    **And it is hidden for a title whose trainer nobody has measured**, which
    is every title but Pool of Radiance -- `levelling`, set from the window.
    The refusal is `automap.actions.level_up_blockers` and it is enforced at
    the write as well; hiding the button is so that the feature is not offered
    and then withdrawn (#16).
    """

    #: The slot, and nothing else. **The player is not asked which class.** A
    #: multi-class character with two ready gets the one whose threshold after
    #: the level is highest, which keeps the trainer's experience clamp as high
    #: as it goes and so usually leaves the other class still qualified;
    #: pressing again takes that one. `goldbox.levelup.best_next_class` is the rule
    #: and `docs/135-levelling.md` is why.
    level_up_requested = pyqtSignal(int)

    def __init__(self, root: QWidget, index: int, parent: QObject | None = None):
        super().__init__(parent)
        self.root = root
        self.index = index
        self.slot = index
        self.ready: tuple[str, ...] = ()
        #: Whether levelling is possible in this title at all. True until the
        #: window says otherwise, because a card built without one is Pool of
        #: Radiance's -- the same default every other per-title reader takes.
        self.levelling = True

        self.frame = root.findChild(QFrame, f"card_{index}")
        if self.frame is not None:
            self.frame.setStyleSheet(
                f"QFrame#card_{index} {{ background: {CARD.name()};"
                f" border: 1px solid {LATTICE.name()}; border-radius: 4px; }}")

        self.name = root.findChild(QLabel, f"card_{index}_name")
        self.conditions = root.findChild(IconRow, f"card_{index}_conditions")
        if self.conditions is not None:
            self.conditions.colour = DANGER
        self.combat = root.findChild(QLabel, f"card_{index}_combat")
        if self.combat is not None:
            self.combat.setStyleSheet(f"color: {MUTED.name()}")

        self.klass = root.findChild(QLabel, f"card_{index}_klass")
        if self.klass is not None:
            self.klass.setStyleSheet(f"color: {MUTED.name()}")
        self.quickfight = root.findChild(IconRow, f"card_{index}_quickfight")
        self.level_up = root.findChild(QPushButton, f"card_{index}_level_up")
        if self.level_up is not None:
            self.level_up.clicked.connect(self._level_up_clicked)
            self.level_up.hide()

        self.hp = root.findChild(Bar, f"card_{index}_hp")
        self.xp = [root.findChild(Bar, f"card_{index}_xp_{j}") for j in range(3)]

        # What is in hand, under the bars. Readied only -- the whole inventory
        # would swamp the card -- one elided line with the full list in the
        # tooltip, and a **blank line** for a character carrying nothing
        # readied: the absence is the information, and the word "none" is not.
        self.readied = root.findChild(QLabel, f"card_{index}_readied")
        if self.readied is not None:
            self.readied.setStyleSheet(f"color: {MUTED.name()}")

        # Always present, even when empty: a strip that appears and disappears
        # would shift every card below it each time a spell expires.
        self.effects = root.findChild(QLabel, f"card_{index}_effects")
        if self.effects is not None:
            self.effects.setStyleSheet(f"color: {MUTED.name()}")

    @staticmethod
    def ready_to_level(who) -> tuple[str, ...]:
        """Which of this character's classes have the experience for a level.

        **Every class is measured against the whole stored number.** The
        trainer does not divide experience between a multi-class character's
        classes -- LADY KATHERINE, magic-user 1 / thief 7 with 70,100 points,
        was offered thief 8, whose threshold is 70,001 -- so this asks each
        class the same question the school does.
        """
        return tuple(c.name for c in who.classes
                     if c.next_threshold is not None
                     and c.experience >= c.next_threshold)

    @classmethod
    def chosen_class(cls, who) -> str | None:
        """Which class the button will raise. For the tooltip only -- the
        window asks the record the same question before it writes."""
        return best_next_class(cls.ready_to_level(who),
                               {c.name: c.level for c in who.classes})

    def _level_up_clicked(self) -> None:
        self.level_up_requested.emit(self.slot)

    def show_character(self, who) -> None:
        self.slot = who.slot
        if self.name is not None:
            self.name.setText(who.name)
        ac = "--" if who.armour_class is None else who.armour_class
        thac0 = "--" if who.thac0 is None else who.thac0
        if self.combat is not None:
            self.combat.setText(f"AC {ac}   THAC0 {thac0}")
        if self.klass is not None:
            self.klass.setText(f"{who.class_text}  {who.level_text}")
        self.ready = self.ready_to_level(who)
        if self.level_up is not None:
            self.level_up.setVisible(bool(self.ready) and self.levelling)
            if self.ready:
                self.level_up.setToolTip(f"level up as {self.chosen_class(who)}")
        conditions = who.conditions
        if self.conditions is not None:
            self.conditions.set_icons(icon for icon, _ in conditions)
            self.conditions.setToolTip("\n".join(why for _, why in conditions))

        hp = "--" if who.hp is None else who.hp
        if self.hp is not None:
            self.hp.set(who.hp_fraction, f"{hp} / {who.hp_max} hp",
                        hp_colour(who.hp_fraction))
            self.hp.setToolTip("current hit points from the roster block; the "
                               "maximum from the character record")

        for bar, klass in zip(self.xp, who.classes):
            if bar is None:
                continue
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
            if bar is not None:
                bar.hide()

        self.show_readied(who.readied)

        if self.quickfight is not None:
            self.quickfight.set_icons(("person-running",) if who.quickfight else ())
            self.quickfight.setToolTip("Quickfight" if who.quickfight else "")

        if self.effects is not None:
            self.effects.setText("   ".join(e.label for e in who.effects))
            self.effects.setToolTip("\n".join(e.detail for e in who.effects))

    def show_readied(self, items) -> None:
        """One line of what is in hand, elided to the card's width.

        Elided here rather than by `QLabel`, because a label that elides is a
        label that has already claimed the width -- and the card is 248px wide
        by design.
        """
        self.readied_items = tuple(items)
        if self.readied is not None:
            text = ", ".join(self.readied_items)
            metrics = QFontMetrics(self.readied.font())
            self.readied.setText(metrics.elidedText(
                text, Qt.TextElideMode.ElideRight, CARD_WIDTH - 20))
            self.readied.setToolTip("\n".join(self.readied_items))


class RosterPanel(QObject):
    """The cards, down the left. Manages the 8 pre-created cards in the unified form.

    `level_up_requested` carries the slot up from whichever card was clicked,
    and nothing else: which class gets the level is decided from the record.
    The panel does not run the action itself -- it has no target and no
    confirmation dialog, and both belong to the window.
    """

    level_up_requested = pyqtSignal(int)

    def __init__(self, root: QWidget, parent: QObject | None = None):
        super().__init__(parent)
        self.root = root
        self.levelling = True
        self.heading = root.findChild(QLabel, "automap_roster_heading")
        self.cards: list[CharacterCard] = [
            CharacterCard(root, i, parent=self) for i in range(8)
        ]
        for card in self.cards:
            card.level_up_requested.connect(self.level_up_requested)
        self.set_message("waiting for a game")

    def set_levelling(self, allowed: bool) -> None:
        """Whether this title can be levelled at all, and so whether the Level
        up button belongs on a card. Held for cards not built yet."""
        self.levelling = allowed
        for card in self.cards:
            card.levelling = allowed
            if not allowed and card.level_up is not None:
                card.level_up.hide()

    def set_message(self, text: str) -> None:
        """No party to show. Says why rather than showing empty cards."""
        if self.heading is not None:
            self.heading.setText(f"Party - {text}" if text else "Party")

    def set_stale(self, stale: bool) -> None:
        """The last good snapshot, held while the game is in a menu or loading.

        Saying so beats pretending: during a disk load these numbers are
        seconds old.
        """
        self.set_message("not readable right now" if stale else "")

    def show_snapshot(self, snap) -> None:
        for i, who in enumerate(snap.characters):
            if i < len(self.cards):
                card = self.cards[i]
                card.show_character(who)
                if card.frame is not None:
                    card.frame.show()
        for card in self.cards[len(snap.characters):]:
            if card.frame is not None:
                card.frame.hide()
        self.set_stale(False)


class BottomStrip(QObject):
    """Where, when, which area, and what is on the party."""

    #: The tallest this strip may hold the window open, whatever the UI font.
    SHORT = 21

    def __init__(self, root: QWidget, parent: QObject | None = None):
        super().__init__(parent)
        self.root = root
        self.where = root.findChild(QLabel, "strip_where")
        self.clock = root.findChild(QLabel, "strip_clock")
        self.area = root.findChild(QLabel, "strip_area")
        self.effects = root.findChild(QLabel, "strip_effects")
        if self.effects is not None:
            self.effects.setStyleSheet(f"color: {MUTED.name()}")

        #: The loader's cache, last time it changed. It used to be a collapsed
        #: readout on this strip, which is a reverse-engineering number in a
        #: window somebody is playing a game in; it goes to the debug log now,
        #: and only when it moves -- twenty-five bytes five times a second
        #: would drown the file.
        self._loaded: tuple[int, ...] = ()

    def show_state(self, state, snap=None) -> None:
        """The map's own state answers "where"; the snapshot answers the rest.

        The square and facing come from `AutomapState` on purpose: it prefers
        the game's own status line, which is right the moment the screen
        settles, where the memory copy at `$49C0` lags a move.
        """
        # `source` is empty until the first fix lands. Before that (0,0) facing
        # north is not where the party is; it is the dataclass's defaults.
        if self.where is not None:
            self.where.setText(
                f"({state.x},{state.y}) facing {state.facing_letter}"
                if state.source else "square --")
        if self.area is not None:
            self.area.setText(state.area_label)
        if snap is None:
            if self.clock is not None:
                self.clock.setText("clock --:--")
            if self.effects is not None:
                self.effects.setText("party effects: not readable right now")
            return
        if self.clock is not None:
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
        if self.effects is not None:
            self.effects.setText(text)
            self.effects.setToolTip("\n".join(e.detail for e in party + monsters))
        loaded = tuple(snap.loaded_files)
        if loaded != self._loaded:
            self._loaded = loaded
            log.info("loaded files: %s",
                     " ".join(f"{b:02X}" for b in loaded) or "none")


class NotesPanel(QObject):
    """Every note in this area, with its square.

    This is what makes notes useful for *finding* something again, which the
    icons on the map alone do not solve: the map answers "what is here", the
    list answers "where was that trainer".

    Clicking a row emits `chosen`; the window flashes the square. The list is
    rebuilt only when the notes actually change, so a poll does not throw away
    the row you were about to click.
    """

    chosen = pyqtSignal(int, int)

    def __init__(self, root: QWidget, parent: QObject | None = None):
        super().__init__(parent)
        self.root = root
        self.heading = root.findChild(QLabel, "notes_heading")
        self.list = root.findChild(QListWidget, "notes_list")
        if self.list is not None:
            self.list.setStyleSheet(
                f"QListWidget {{ background: {CARD.name()}; border: 1px solid "
                f"{LATTICE.name()}; border-radius: 4px; }}")
            self.list.itemClicked.connect(self._clicked)
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
        if self.list is not None:
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
                if self.list is not None:
                    self.list.addItem(row)
                count += 1
        if self.heading is not None:
            self.heading.setText(f"Notes ({count})" if count else "Notes")


class MessagesPanel(QObject):
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

    def __init__(self, root: QWidget, parent: QObject | None = None):
        super().__init__(parent)
        self.root = root
        self.heading = root.findChild(QLabel, "messages_heading")
        self.list = root.findChild(QListWidget, "messages_list")
        if self.list is not None:
            self.list.setStyleSheet(
                f"QListWidget {{ background: {CARD.name()}; border: 1px solid "
                f"{LATTICE.name()}; border-radius: 4px; }}")
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
        if self.list is not None:
            self.list.addItem(row)
            while self.list.count() > self.LIMIT:
                self.list.takeItem(0)
            self.list.scrollToBottom()

    def lines(self) -> list[str]:
        """Every line, oldest first. What a test reads."""
        if self.list is None:
            return []
        return [self.list.item(i).text() for i in range(self.list.count())]


