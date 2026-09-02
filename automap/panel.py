"""The live party, drawn beside the map.

Gold Box Companion's HUD is the model and it is the right one: one card per
character carrying everything you glance at mid-fight, so that "who is hurt"
is answered by looking rather than by reading.

**Bars, not just numbers.** `5 / 7` has to be read; a bar a third empty does
not, and mid-fight that is the whole difference. The numbers stay beside the
bar for when the exact value matters.

Everything here is presentation. The decoding is `automap/live.py`, which has no
Qt in it and is tested against captured bytes.

`ColumnSplitter` is here rather than in `automap/window.py` because the width
a card is drawn to is one of the widths it divides, and `RosterPanel` reads
it. It is the tab's three columns and not a panel, which is the one thing in
this file that is not.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
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


def child(root: QWidget, kind, name: str):
    """The widget `name` in the form, or `None` and a line saying which.

    Every panel in this file is wired to `wish/window.ui` by `objectName`, and
    every one of them carries on without a widget it cannot find -- which is
    right, because a panel has to survive being built against a smaller form,
    and wrong when nobody is told.

    `strip_effects` is why this exists. It was deleted from the form in
    `72ee9a9` while the layout was being simplified, and for months afterwards
    `BottomStrip` worked out the party's active effects five times a second and
    wrote them into `None`. Nothing errored and nothing was logged, so a player
    who cast Bless saw nothing and no report ever said why -- `#142 (The party
    effects line is computed every poll and shown nowhere)`.

    The debug log and not a dialog: a missing widget is a fault in the build,
    not something the player did or can do anything about.
    """
    found = root.findChild(kind, name)
    if found is None:
        log.warning("No widget named %s (%s) in the form", name, kind.__name__)
    return found


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

BAR_HEIGHT = 15

NOTE = QColor("#b8601f")

# **There are no class icons.** There were, beside the class text; four
# 13-pixel glyphs that nobody could tell apart at that size and that said
# nothing the words "fighter/thief" beside them did not. `IconRow` stays,
# because the conditions row and the quickfight badge use it. How well each of
# Donald's eight glyphs survives 13px is measured in
# `docs/136-condition-badges.md`, from `tools/iconsheet.py`'s magnified column
# and not from the name: `invisible`, the original choice for effect 25, drew
# nothing at all at this size and was replaced by `eyelashes`.
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
        # Width is fixed and height is only capped. The row shares the card's
        # readied line with `ReadiedLabel`, and the whole point of putting it
        # there is that the badges are drawn whole and the words give way, so
        # the width has to hold. The height must not: eight of these, one per
        # party slot, would otherwise each add 13px to what the roster column
        # insists on, which is the shape of `#135` all over again.
        self.setMaximumHeight(size)
        self.setFixedWidth(0)

    def _row_width(self) -> int:
        return len(self.names) * (self.size + 3)

    def sizeHint(self) -> QSize:
        return QSize(self._row_width(), self.size)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._row_width(), 0)

    def set_icons(self, names) -> None:
        self.names = tuple(n for n in names if n)
        self.setFixedWidth(self._row_width())
        self.updateGeometry()
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

    def elided_text(self) -> str:
        """What this label will actually draw in the room it has.

        Split out of `paintEvent` so a test can ask for it: `text()` is the
        whole string whatever the width, and the shortening is otherwise
        visible only in pixels.
        """
        return self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, self.contentsRect().width())

    def paintEvent(self, event):
        elided = self.elided_text()
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


class CardClassLabel(ElidingLabel):
    """The classes and level on a roster card: the second thing to give way.

    `CardNameLabel` yields first and yields everything, which is enough on a
    machine whose fonts are this one's. It was not enough on Windows: CI
    reported the Level up button drawn 99 of 102px inside a 220px column with
    the name already down to `LAD...`, because **the classes and the button
    alone are wider than the column there**. A plain `QLabel` cannot give way,
    so the button was the thing that got cut -- which is the whole of `#168`,
    reappearing on a platform the fix was not measured on.

    So the order is: the name goes to nothing, then the classes shorten, and
    the button is never touched. That is Donald's priority read down --
    `MU/C` is worse than a shortened name and better than a control cut in
    half, and the button is the one thing on the row a player has to be able
    to hit.

    `SQUEEZED = 0` for the same reason as the name's: any floor measured here
    is a floor that cuts the button on a machine with a wider font.
    """

    SQUEEZED = 0


class CardNameLabel(ElidingLabel):
    """The character name on a roster card: the one thing on the top row that
    gives way.

    The row holds the name, the classes and level, and the Level up button
    when the character has earned one, inside a column capped at 220px. The
    classes and the level are the character; the button is a control, and a
    control cut in half reads `Lev` (#168). So the name yields all of the
    width, down to nothing if that is what it takes, and says it has by
    drawing an ellipsis.

    Donald's reasoning, and it is what makes a shortened name the cheap side
    of the trade: *"The level up button will never be there for very long. It
    will be clicked as soon as it appears. So, cutting off the name for a
    little while is fine."* A name is also the one thing on the row still
    recognisable from its first few letters -- `LADY KATH...` is unmistakably
    LADY KATHERINE, where `MU/C` for `MU/C/T  L8` is not.

    `SQUEEZED = 0` rather than a number measured here: the classes label and
    the button are both set in points, so how many pixels they take is the
    machine's business, and any floor big enough on this one is a floor that
    cuts the button on a machine with a wider font.
    """

    #: The widest this name may hold the row open. Zero, deliberately.
    SQUEEZED = 0


class ReadiedLabel(ElidingLabel):
    """The card's line of what is in hand: bounded in both axes.

    Width is the first of the two. The item names are read off the player's
    disk, and a card whose floor was the width of `BANDED MAIL +1, SHIELD +2,
    LONG SWORD +3` would put that string under the whole window (#41). The
    floor is zero rather than `ElidingLabel`'s 44 because the condition
    badges share this row and are drawn at a fixed width: this line takes
    whatever they leave, however little that is. Donald settled the order --
    *"I would rather see active effects than readied items. That is a fine
    trade-off as far as space goes."* (#161)

    Height is the reason for the subclass. There are eight of these, one per
    party slot, in a column that does not scroll, so a line that insisted on
    its own height would add eight of them to the window's floor -- and the
    roster is already the tallest thing on the automapper page with a full
    party. `SHORT = 0` says the line gives way *first*: it is the least
    important row on the card, and it is only ever squeezed by a window
    already pushed to its minimum. Anywhere above that floor the line is
    drawn in full.
    """

    #: The widest this line may hold the row open. Zero: the badges beside it
    #: are drawn whole and this takes the remainder.
    SQUEEZED = 0

    #: The tallest this line may hold the window open. Zero, deliberately.
    SHORT = 0

    def minimumSizeHint(self) -> QSize:
        return shortened(super().minimumSizeHint(), self.SHORT)


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

        self.frame = child(root, QFrame, f"card_{index}")
        if self.frame is not None:
            self.frame.setStyleSheet(
                f"QFrame#card_{index} {{ background: {CARD.name()};"
                f" border: 1px solid {LATTICE.name()}; border-radius: 4px; }}")

        self.name = child(root, QLabel, f"card_{index}_name")
        self.conditions = child(root, IconRow, f"card_{index}_conditions")
        if self.conditions is not None:
            self.conditions.colour = DANGER


        self.klass = child(root, QLabel, f"card_{index}_klass")
        if self.klass is not None:
            self.klass.setStyleSheet(f"color: {MUTED.name()}")
        self.quickfight = child(root, IconRow, f"card_{index}_quickfight")
        self.level_up = child(root, QPushButton, f"card_{index}_level_up")
        if self.level_up is not None:
            self.level_up.clicked.connect(self._level_up_clicked)
            self.level_up.hide()

        self.hp = child(root, Bar, f"card_{index}_hp")
        self.xp = [child(root, Bar, f"card_{index}_xp_{j}") for j in range(3)]

        #: What is in hand, under the bars. Readied only -- the whole
        #: inventory would swamp the card -- and a **blank line** for a
        #: character carrying nothing readied: the absence is the information,
        #: and the word "none" is not. The line stays either way, so the cards
        #: below do not shift when a sword is put away.
        self.readied_items: tuple[str, ...] = ()
        self.readied = child(root, ReadiedLabel, f"card_{index}_readied")
        if self.readied is not None:
            self.readied.setStyleSheet(f"color: {MUTED.name()}")

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
        if self.klass is not None:
            self.klass.setText(f"{who.class_text}  {who.level_text}")

        tooltip_lines = [
            f"{who.name} ({who.class_text} {who.level_text})",
            f"AC {ac}   THAC0 {thac0}"
        ]
        if who.readied:
            tooltip_lines.append("Readied: " + ", ".join(who.readied))
        self.frame.setToolTip("\n".join(tooltip_lines))
        self.ready = self.ready_to_level(who)
        if self.level_up is not None:
            self.level_up.setVisible(bool(self.ready) and self.levelling)
            if self.ready:
                self.level_up.setToolTip(f"level up as {self.chosen_class(who)}")
        conditions = who.conditions
        if self.conditions is not None:
            self.conditions.set_icons(icon for icon, _ in conditions)
            # The skull carries no line -- "dead or dying, and which is not
            # decoded" is what the badge already says -- so the empty ones are
            # dropped rather than joined, or a dead character's tooltip opens
            # with a blank line above whatever else is running.
            self.conditions.setToolTip(
                "\n".join(why for _, why in conditions if why))

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
            self.quickfight.set_icons(
                ("sparkling-sabre",) if who.quickfight else ())
            self.quickfight.setToolTip("Quickfight" if who.quickfight else "")

    def show_readied(self, items) -> None:
        """One line of what is in hand, shortened to the room the card has.

        The label holds the whole string and `ReadiedLabel` draws as much of
        it as fits, so nothing here measures a font: the elide is the
        painter's and the card's floor is a constant. The full list stays
        readable because the label sets no tooltip of its own and so answers
        with the frame's, which already carries it.
        """
        self.readied_items = tuple(items)
        if self.readied is not None:
            self.readied.setText(", ".join(self.readied_items))


class ColumnSplitter(QObject):
    """The automapper's three columns, and the widths a user drags them to.

    The roster, the map and the reading column used to be three cells of a
    grid, two of them capped at a width chosen once. `#162` made the two
    dividers draggable and the widths remembered, and Donald settled both of
    the questions that came with it:

    * *"a dragged width on a column should be remembered when Wish opens
      again"* -- `Settings.automap_columns`, three numbers in the JSON;
    * *"Sure, let the user drag it down to nothing. As long as they can drag
      it back out when they do that."*

    **The second is the whole of the difficulty**, because a column dragged
    shut has no width left to grab: what the user aims at afterwards is the
    divider, and if that went with the column the panel would be gone for
    good and the only way back would be editing the settings file by hand.
    Two things keep it reachable, and both are tested in
    `tests/test_columns.py` against a window built from a settings file that
    already holds a zero:

    * the handle is `HANDLE` wide rather than the style's, and Qt keeps
      drawing it at the edge of a collapsed pane -- measured at
      `QRect(0, 0, 6, h)` with the roster at zero;
    * the width is restored with `QSplitter.setSizes`, which honours a zero
      without hiding anything, so the divider is in the window on the first
      frame of a fresh start.

    A column with a floor -- the roster's is the width of a card, the reading
    column's is `AutomapBinding.SIDE_SQUEEZED` -- is therefore either wider
    than its floor or shut, with nothing in between. That is Qt's own
    collapsing and it is the behaviour Donald asked for: dragging inwards past
    half the floor shuts the column, and dragging outwards opens it at the
    floor again.
    """

    #: Left to right, and the order the widths are written to the settings
    #: file in.
    ROSTER_AT, MAP_AT, SIDE_AT = 0, 1, 2
    COLUMNS = 3

    #: The roster's width before anybody drags it, and the width a card is
    #: drawn to. **Unchanged**: Donald ruled on `#162` that a multiclass
    #: character whose name will not fit is a corner case, that the default
    #: stays where it is, and that dragging is the answer for whoever meets it
    #: (`#168`).
    ROSTER = 220

    #: And the reading column's. The panels hold short rows; past this they
    #: are mostly paper.
    SIDE = 460

    #: The map asks for nothing of its own at startup, because the window has
    #: not been shown yet and there is no width to divide. The stretch factors
    #: below hand it everything the two side columns do not want, on the first
    #: frame and on every resize after.
    MAP_ASKS = 1

    #: How wide the divider is. Qt's style answers 4 here, which is enough
    #: while there is a column beside it to aim at -- but a column dragged
    #: shut leaves the divider as the only thing left to grab, and it is then
    #: the whole of the way back. Set rather than inherited for that one case.
    HANDLE = 6

    def __init__(self, root: QWidget, settings,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.settings = settings
        self.splitter = child(root, QSplitter, "automap_columns")
        if self.splitter is not None and self.splitter.count() != self.COLUMNS:
            # `child` reports a widget the form does not have; it cannot report
            # one that is there with the wrong number of columns, which is the
            # only fault left to say out loud here.
            log.debug("automapper splitter has %d columns, not %d",
                      self.splitter.count(), self.COLUMNS)
            self.splitter = None
        if self.splitter is None:
            return
        self.splitter.setHandleWidth(self.HANDLE)
        # Every pixel the window gains goes to the map. That is what the two
        # width caps in the form used to do, and losing it would spend a wider
        # window on blank paper beside a short note.
        for at in range(self.COLUMNS):
            self.splitter.setStretchFactor(at, 1 if at == self.MAP_AT else 0)
        # The map is the one column that may not be shut. Dragging a divider
        # across it would otherwise leave the automapper tab with no map on
        # it, which is not a state anybody asked to be able to reach.
        self.splitter.setCollapsible(self.MAP_AT, False)
        self.splitter.splitterMoved.connect(self._dragged)
        self.restore()

    def defaults(self) -> list[int]:
        """What the columns open at with nothing remembered."""
        return [self.ROSTER, self.MAP_ASKS, self.SIDE]

    def widths(self) -> list[int]:
        """What the three columns are, left to right, right now."""
        return list(self.splitter.sizes()) if self.splitter else []

    def restore(self) -> None:
        """Open at the remembered widths, or at the defaults.

        Called before the window is shown, which is deliberate: `setSizes`
        records what each column asked for and the splitter divides the real
        width against those the moment there is one, so the first frame the
        user sees is already the right shape rather than the default shape
        corrected afterwards.
        """
        if self.splitter is None:
            return
        remembered = self.settings.column_widths(self.COLUMNS)
        self.splitter.setSizes(remembered
                               if remembered is not None else self.defaults())

    def _dragged(self, _pos: int, _index: int) -> None:
        """Record a divider the user just moved.

        Only a drag writes here, and not a window resize: the widths a
        squeezed window forces on the columns are the window's, and
        overwriting somebody's chosen width with them is how a preference goes
        missing without anybody touching it. The file is written when the
        window closes, by `Settings.save`.
        """
        self.settings.automap_columns = self.widths()


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
        self.heading = child(root, QLabel, "automap_roster_heading")
        #: The column the cards scroll inside, and the column that holds it.
        self.scroll = child(root, QScrollArea, "automap_roster_scroll")
        self.column = child(root, QWidget, "automap_roster")
        self.cards: list[CharacterCard] = [
            CharacterCard(root, i, parent=self) for i in range(8)
        ]
        for card in self.cards:
            card.level_up_requested.connect(self.level_up_requested)
        self.set_message("waiting for a game")
        self.ask_for_room(0)

    def ask_for_room(self, showing: int) -> None:
        """Ask the layout for the width a card needs, once there is one.

        A `QScrollArea` reports a small minimum in *both* axes. Hiding the
        height is the whole point -- eight cards in a column that could not
        scroll put a 944px floor under the window (#135) -- but hiding the
        width is not: with the cards behind the scroll area the roster column
        collapsed to the width of its own heading, and a card was cut off
        somewhere in the middle of the name.

        So the column asks for a card's width, and only while it has something
        to show; an empty roster asks for nothing, which is what the cards
        themselves used to do by being hidden.

        `ColumnSplitter.ROSTER` is where that width lives now. It was the
        column's own `maximumWidth` in the form until `#162` made the divider
        draggable, and a cap is the one thing a draggable column cannot have.
        What it means here is unchanged -- a card is drawn to it -- and it is
        a floor rather than a cap in both directions: the column can be
        dragged wider, and Qt's own collapsing still shuts it altogether.
        """
        if self.scroll is None or self.column is None:
            return
        self.scroll.setMinimumWidth(ColumnSplitter.ROSTER if showing else 0)

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
        self.ask_for_room(len(snap.characters))
        self.set_stale(False)


class BottomStrip(QObject):
    """Where, when, which area, and what is on the party."""

    #: The tallest this strip may hold the window open, whatever the UI font.
    SHORT = 21

    def __init__(self, root: QWidget, parent: QObject | None = None):
        super().__init__(parent)
        self.root = root
        self.where = child(root, QLabel, "strip_where")
        self.area = child(root, QLabel, "strip_area")
        #: One icon row for the **whole roster**, above the square and the area
        #: name. It was a `QLabel` writing out `Bless   Prayer   Protection
        #: from Evil, 10' Radius`, and the width of that is what made it
        #: unaffordable; Donald settled the shape on `#142 (The party effects
        #: line is computed every poll and shown nowhere)`: *"I think we should
        #: have ONE line for the entire roster with party effects... Icons will
        #: take up less space than text-only names of the spells. We can put
        #: the name of the spell in the tooltip of the icon."*
        self.effects = child(root, IconRow, "strip_effects")

        #: Party-wide effect ids already reported as having no badge. Logged
        #: once each rather than five times a second.
        self._unbadged: set[int] = set()

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
        self.show_effects(snap)
        if snap is None:
            return
        loaded = tuple(snap.loaded_files)
        if loaded != self._loaded:
            self._loaded = loaded
            log.info("loaded files: %s",
                     " ".join(f"{b:02X}" for b in loaded) or "none")

    def show_effects(self, snap) -> None:
        """One icon per spell the whole party is under, named in the tooltip.

        **What counts as the whole party is `Snapshot.whole_party_effects`**,
        and it is not only the `$FF` owner byte the decode named: Bless cast
        from the adventure menu writes one row per character and no `$FF` row
        at all, so a rule that read only the owner byte drew nothing for the
        one party spell anybody has watched land.

        **Nothing is drawn when nothing is running.** The old shape was one
        line per character, blank on most of them, and eight blank lines is
        what got it removed; a strip that says "party effects: none" five times
        a second is the same mistake with one line instead of eight.

        **Nothing about the monsters, either.** The row briefly counted them
        -- "2 effects on monsters" under the party's own spells -- and Donald
        cut it on 2026-09-01: hovering the party's row to be told a number
        about the orcs answers a question nobody asked, and it says neither
        which monster nor which spell. It was also unreachable in the one case
        that might have been interesting, because a party with nothing running
        draws no icons and a row no icons wide cannot be hovered at all. The
        combat view is where a monster's effects will mean something.

        **A party effect no badge covers is drawn nowhere**, and that is worth
        saying out loud rather than letting it look like a party with nothing
        running. `automap/live.py`'s badge set is graded from the spell table
        -- no save this project holds carries a party-wide effect at all -- so
        an id turning up here means the set is a glyph short, and it goes to
        the debug log once per id for whoever comes to choose one.
        """
        if self.effects is None:
            return
        if snap is None:
            self.effects.set_icons(())
            self.effects.setToolTip("")
            return
        lit = snap.party_badges
        self.effects.set_icons(icon for icon, _ in lit)
        self.effects.setToolTip("\n".join(why for _, why in lit if why))
        for effect in snap.unbadged_party_effects:
            if effect.id not in self._unbadged:
                self._unbadged.add(effect.id)
                log.warning("The whole party is under %s and no condition "
                            "badge covers it, so nothing on the strip shows "
                            "it", effect.label)


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
        self.heading = child(root, QLabel, "notes_heading")
        self.list = child(root, QListWidget, "notes_list")
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
        self.heading = child(root, QLabel, "messages_heading")
        self.list = child(root, QListWidget, "messages_list")
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


