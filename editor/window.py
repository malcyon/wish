"""Binds editor fields to goldbox record data. Works on any widget tree.

Widgets are found by `objectName` and matched to `goldbox/layout.py` fields,
so the form can be rearranged in Qt Designer -- fields moved between group
boxes, regrouped, relabelled -- without a line of this file changing.
"""

from __future__ import annotations

import logging
import pathlib
import shutil

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from goldbox import c64_codec, classcode
from goldbox import c64_port as por_games
from goldbox.encoding import combat_byte, combat_value
from goldbox.iconparts import IconParts
from goldbox.icons import load_icon_charset
from goldbox.items import load_item_names, load_item_templates, load_item_types
from goldbox.layout import FIELDS_BY_NAME
from goldbox.savegame import store_save
from goldbox.spells import capacity, load_spell_names
from goldbox.spells import for_game as spell_table

from . import activeeffects, changes, files, inventory
from . import effects as trait_effects
from .binding import COMBAT_FIELDS, bindings, field_name, value_range, widest_text
from .enums import caster_bits, tables_for
from .inventory import AddItemDialog, InventoryModel, ItemTraitsModel
from .roster import Party
from .rosterview import (
    NAME_COLUMN,
    ROSTER_MIN_WIDTH,
)
from .spellwidget import MemorisedEditor, SpellbookEditor, SpellEditor

#: The spellbook bitmask at 0x078, which `goldbox/layout.py` declares as two
#: fields: the seven bytes Pool of Radiance uses, and the nine the titles after
#: it continue into. In record order, because they are read and written as one
#: run of bytes.
SPELLBOOK_FIELDS = ("spells_known", "spells_known_high")

#: A child of the `wish` logger, so `wish/debuglog.py`'s handler takes these
#: when the log is on and its level swallows them when it is off -- and
#: `editor` still imports nothing from `wish`.
_log = logging.getLogger("wish.editor.window")

#: What the Open and Save As pickers offer to filter on. Donald's wording,
#: 2026-08-27: *"These should be described as 'C64 disk image (*.d64 *.D64)'"*
#: -- the file is a Commodore 64 disk image, and "Gold Box" named the games on
#: it rather than the thing being opened.
DISK_FILTER = "C64 disk image (*.d64 *.D64);;All files (*)"
#: The Save As picker's title. `editor/dosimport.py`'s Browse… opens the same
#: picker for the same purpose and reuses this rather than wording it again.
SAVE_AS_TITLE = "Save the disk as"

#: Donald's wording, approved verbatim (#145) -- one line per field that
#: refused, `{label}` filled from the widget's own on-screen label
#: (`_field_label`), never the internal snake_case field name. No reason, no
#: value, no second sentence: he approved this sentence whole.
FIELD_NOT_SAVED = "Error: {label} could not be saved."


def _size_combo(combo: QComboBox) -> None:
    """As wide as its longest name, and no wider.

    Re-applied whenever an item is added, because `_select` adds one for a code
    the game's table does not name and an elided box would hide the number.

    The longest *item*, not the current one: this box exists because
    `magic-user/thief` came out as `magic-user`. It is also the most expensive
    widget in the header -- `15  magic-user/cleric/thief/fighter` is 225px at
    the default UI font here and 423 at ten points more, which is half of what
    Character costs -- and there is nothing to take off it that is not one of
    Donald's words.
    """
    combo.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow)
    widest = max((combo.fontMetrics().horizontalAdvance(combo.itemText(i))
                  for i in range(combo.count())), default=0)
    # A floor as well as a ceiling. With only a maximum, a box capped to its
    # own size hint squeezed the combo below its text and `magic-user/thief`
    # came out as `magic-user`.
    width = widest + _combo_chrome(combo) + CARET
    combo.setMinimumWidth(width)
    combo.setMaximumWidth(width)


class _NoClassCode(int):
    """A `char_class` value the Class combo must not match to a real class,
    even though it is a simple number like any other (#409).

    A regained dual-classed paladin or ranger whose mask Curse's own table
    cannot name stores `dual_class_level` at `0x073`, not a class code, and a
    level such as 5 or 6 is also MAGIC-USER's or THIEF's own code in every
    title's table -- `_select`'s `combo.findData(value)` would find that real
    entry and show it as though it were the character's class, which it is
    not. Subclassing `int` rather than returning something else keeps
    `_char_class_shown` comparing equal to a simple `int` of the same value
    for every caller that only asks what the code is (`tests/test_dualclasscombo.py`,
    `tools/classcombocheck.py`); only `_populate`, which decides *how* to
    show it, tells the two apart.

    `label` carries what the record's own classes actually are, already
    named from `class_bits` by `goldbox.titles.classes_to_names` -- the save
    is correct and holds two classes; the stored byte is merely not one of
    them, so `_select` shows the classes rather than the byte.
    """

    def __new__(cls, raw: int, label: str) -> "_NoClassCode":
        self = super().__new__(cls, raw)
        self.label = label
        return self


def _select(combo: QComboBox, value) -> None:
    """Show `value` in a dropdown, even when the table has no name for it.

    A code outside the game's own table is real data -- monsters carry things
    player characters do not -- so it is added to the list rather than being
    rounded to the nearest thing we recognise.

    A `_NoClassCode` (#409) is shown by its own `label` -- the classes the
    mask actually names -- rather than by `combo.findData(value)`, since a
    coincidental match to a real entry (the byte is `dual_class_level`, not a
    class code) is exactly what it exists to avoid.
    """
    if not isinstance(value, int):
        return
    if isinstance(value, _NoClassCode):
        text = value.label
        at = combo.findText(text)
    else:
        text = f"{value}  — not in the game's table"
        at = combo.findData(value)
    if at < 0:
        combo.addItem(text, int(value))
        at = combo.count() - 1
        _size_combo(combo)
    combo.setCurrentIndex(at)


def _char_class_shown(raw, record, game):
    """0x073, the code the Class combo shows -- `raw` unless the record's own
    classes name a different one (#356).

    Curse of the Azure Bonds' trainer leaves the byte stale: `GEN $1939`
    stores the wrong register, so the code can go on naming a class the
    roster (`editor/roster.py`'s `class_name`) no longer agrees the
    character is. Donald ruled 2026-09-07 that the combo shows the class he
    actually is, so this draws from `class_bits` the same way the roster
    does, through `goldbox.classcode.repair` -- #310's own rule, not a
    second one.

    **Returned as a `_NoClassCode` when Curse's own table has no code at
    all for the record's classes** -- a regained dual-classed paladin or
    ranger, whose mask combines a class Curse's seventeen-entry table never
    paired with him (#409). `GEN $1939` stores `dual_class_level` there
    instead of a code once that happens, and that level can equal a
    different class's real code by coincidence: MATHEW, fighter 7/paladin 6,
    stores 6, THIEF's code; MARK, cleric 6/paladin 5, stores 5, MAGIC-USER's.
    The mask itself is never in doubt, so the `_NoClassCode` carries both
    classes' names, read the same way the C64's own sheet draws them --
    `goldbox.titles.classes_to_names` off `class_bits`, joined "/" -- rather
    than the byte, which was never a class code for this character.

    **Gated on `goldbox.c64_codec.record_shape(game).class_code_repairable`,
    Curse only** -- the same gate the neutral reader uses. Pool of Radiance's
    own disagreements between the two fields are not this bug (a DWARVEN
    FIGHTER-shaped mismatch is legitimate, `docs/50-experiments.md`), and a
    title nobody has measured the overlays of raises out of `record_shape`
    rather than guessing, so that is read as "no known repair" too.
    """
    try:
        repairable = c64_codec.record_shape(game).class_code_repairable
    except KeyError:
        # A title whose overlays nobody has measured. Logged rather than
        # swallowed, because every other handler in this file logs and a
        # silent fallback here draws the stale byte with no trail saying why.
        _log.debug("no record shape for %s; class code not repairable",
                   getattr(game, "key", game))
        repairable = False
    if not repairable or not isinstance(raw, int):
        return raw
    try:
        bits = int(record.get("class_bits") or 0)
    except Exception:
        _log.exception("class_bits unreadable; showing the stored class code")
        return raw
    want = classcode.repair(raw, bits, game=game)
    if want is not None:
        return want
    # `want is None` here for one of two reasons: the code already agreed
    # with the classes (`classcode.code_for` answers `raw`), or Curse's
    # table has no code for this mask at all (`classcode.code_for` answers
    # `None`). Only the second means the byte cannot be trusted.
    if classcode.code_for(bits, game=game) is None:
        names = por_games.classes_to_names(bits, game)
        label = "/".join(names) if names and all(
            isinstance(n, str) for n in names) else str(bits)
        return _NoClassCode(raw, label)
    return raw


WOUNDED = QColor("#b03a2e")
NPC = QColor("#7d6608")

HP_COLUMN = 4
# Whitespace. Qt's defaults are laid out for a settings dialog with ten
# controls; this sheet has sixty-two and they have to be readable together.
FORM_VERTICAL_SPACING = 2
FORM_HORIZONTAL_SPACING = 6
FORM_MARGINS = (8, 6, 8, 6)
TABLE_ROW_HEIGHT = 20
TOOLBAR_ICON = 16
MUTED_INK = QColor("#4a5b6d")
# The tables and the spell lists want the width; the field forms do not.
# `box_active_effects` is here for the same reason the other four are: it is a
# table rather than a form of fields, so it can read a wider window, and
# `_compact` would otherwise hold it to the width it hinted while it was empty
# -- 307px, measured before a save was open, which cut the owner column off
# the right of the panel entirely.
WIDE_BOXES = ("box_inventory", "box_traits", "box_effects", "box_spells",
              "box_active_effects")
# Which item in a horizontal row is allowed to grow. `header_row` is the
# roster, Character and the active-effects panel, and the roster is the only
# one of the three that can use a wider window: every field in Character is
# sized to the widest value its bytes can hold, and the effects panel is two
# columns of text sized to their own contents, so a pixel more in either is a
# pixel of nothing.
#
# Four entries: the loop below pads with 0, so the trailing spacer takes no
# stretch.
ROW_STRETCH = {"header_row": (1, 0, 0, 0), "form_identity": (0, 0)}
#: The Stats tab is a grid and not five independent columns, because a row of
#: a grid has one top edge and five `QVBoxLayout`s have five. Donald asked for
#: `Combat` and the combat icon to start on the same line with the icon in the
#: roster's column; stacked columns put them 29px apart, since `Money` is 232
#: tall and `Roster` 203, and matching them with a spacer is arithmetic that
#: comes apart the first time either box gains a field.
#:
#: Character Traits is the only box on the tab that can use spare width -- it
#: is a table and every other box is fields sized to the widest value their
#: bytes can hold -- so it takes the one stretching column and spans both
#: rows. Shared four ways -- round six -- the slack came out as a gap beside
#: every column.
STATS_COLUMN_STRETCH = (0, 0, 0, 0, 1)
#: The spare *height* goes to row 2, which holds nothing. Nothing on the tab
#: can use it: Character Traits is ten fixed effect slots and `_fit_height`
#: caps its table at them, so height given to that box only floats the table
#: in the middle of its own frame. An empty stretching row keeps the two rows
#: of boxes as tall as their own contents and puts the slack underneath.
STATS_ROW_STRETCH = (0, 0, 1)
ROSTER_SLACK = 6
#: The old 300 cap scaled by the same half the icon itself shrank by (`ZOOM`
#: 6 to 3), which leaves six pixels over `IconEditor`'s own 144px minimum.
#: A cap it can take a little of a wide column without the art smearing:
#: `IconEditor._geometry` only zooms in whole steps, so the next step up is
#: four times the area and does not fit here.
ICON_MAX_WIDTH = 300
STRIP_TABLE_HEIGHT = 150
# Eight is every slot a save disk has and every character a roster disk holds,
# so a roster sized to this never scrolls and never leaves a fifth of the
# window empty.
MAX_ROSTER_ROWS = 8
#: What the active-effects panel keeps when the window has nothing to spare,
#: in pixels. Above this it grows with the window, up to its own two columns
#: at their contents, and below it the owner line elides.
#:
#: A constant for the reason `ROSTER_MIN_WIDTH` is one: the header does not
#: scroll, so anything standing in it is a floor under the whole window, and
#: this panel's widest line is a *sentence* rather than a field -- it says who
#: an effect is on, and "everybody in the party" is longer than any name. Sized
#: from what it can cost rather than from what it would like: with the widest
#: party a save can hold the editor's floor is 958px without the panel, and
#: Donald's screen is 1366, so 260 leaves 148px of margin. Its two column
#: headings alone want 430, which is what a panel sized to its own contents
#: would have put in the way of a 1366 screen.
#:
#: What moves it is a wider Character or a longer heading, and either shows up
#: in `test_the_effects_panel_is_not_a_floor_under_the_window`, which asserts
#: the outcome -- the window fits the screen -- rather than this number.
#:
#: This clamps the table (`_size_active_effects`), not the `QGroupBox` around
#: it -- and the box has a floor of its own that the table's clamp cannot
#: reach: `QGroupBox.minimumSizeHint()` grows to fit its own *title* text
#: (`Effects running in this saved game...`), in the same font the table's
#: two columns are measured in, so it grows exactly like they do and was
#: never brought down by clamping the table. CI's Windows runners have a
#: wider default UI font than this machine's, and that is what turned a
#: 12px-over-budget title (`docstring` above, at this machine's font) into
#: 198px over `SMALL_LAPTOP` there -- the panel was never the widest thing
#: in the row, its own box's title was. `_size_active_effects` now gives the
#: box the same explicit `setMinimumWidth`, which is what makes its
#: contribution to the layout answer this constant rather than the title's
#: own width -- Qt's `QWidgetItem::minimumSize()` prefers an explicit
#: `minimumSize` over `minimumSizeHint()` once one is set at all.
ACTIVE_EFFECTS_MIN_WIDTH = 260
#: Fields whose widest possible value is not worth the width it costs. `name`
#: is twenty bytes and so twenty capital Ws -- 318px at three points of extra
#: UI font, and it sits in the header, which does not scroll and is therefore a
#: floor under the whole window. Donald asked for 30% off. A twenty-character
#: name still fits the bytes and still edits; it scrolls inside the box.
TRIMMED = {"name": 0.7}
#: Boxes that must not be squeezed below a readable list. Stated here and not
#: in `character.ui` because a Qt Designer round-trip silently drops
#: `minimumHeight` from the form -- Designer does not treat it as designable,
#: and five of them were lost that way once and had to be put back.
LIST_FLOOR = {"box_inventory": 240, "box_traits": 240}
#: What Character may be squeezed to.
HEADER_IDENTITY_MIN_WIDTH = 480
#: Which header boxes are held to a constant, and to what. Keyed by
#: objectName like everything else on the form. `box_active_effects` is not
#: here, though it wants the same treatment: `_size_active_effects` sets its
#: floor beside the panel's own, from the one `natural`/`floor` pair both are
#: measured from (see `ACTIVE_EFFECTS_MIN_WIDTH`), rather than duplicating
#: that arithmetic here.
HEADER_FLOOR = {"box_identity": HEADER_IDENTITY_MIN_WIDTH}
#: And the row of buttons above the header, which does not scroll either.
TOOLBAR_BUTTON_MIN_WIDTH = 80
TOOLBAR_BUTTONS = ("button_open", "button_save", "button_save_as",
                   "button_preview")

# Room for the frame and, on a spin box, the two arrows. A guess at this was
# the bug: 36 px is what Fusion and Breeze want, and Windows draws its up/down
# buttons wider, so a box sized to fit "255" plus 36 came out as two arrows and
# no number. `_spin_width` and `_line_width` below ask the style instead and
# these are floors under the answer.
SPINBOX_CHROME = 36
LINE_CHROME = 14
COMBO_CHROME = 30
# Space for the caret and a little air, on top of the widest value. Without it
# a box exactly as wide as its text hides the last digit while you type.
CARET = 6
# Any width answers: the chrome a style spends is a constant, so it falls out
# of one measurement at whatever size.
PROBE_WIDTH = 400

# The hex digits, for `_widest_drawing`.
HEX_DIGITS = "0123456789abcdef"

# Cell margins either side of an item name.
ITEM_NAME_PADDING = 16

#: How a selected row looks, stated rather than left to the platform.
TABLE_SELECTION = (
    "QTableView { outline: none; }"
    " QTableView::item:selected,"
    " QTableView::item:selected:!active"
    " { background: #cddff5; color: #10243a; }"
)


def _combo_chrome(combo) -> int:
    """The arrow and the frame, as this style draws them, not as Fusion does."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QStyle, QStyleOptionComboBox

    option = QStyleOptionComboBox()
    option.initFrom(combo)
    option.frame = combo.hasFrame()
    option.editable = combo.isEditable()
    option.rect = QRect(0, 0, PROBE_WIDTH, combo.sizeHint().height())
    field = combo.style().subControlRect(
        QStyle.ComplexControl.CC_ComboBox, option,
        QStyle.SubControl.SC_ComboBoxEditField, combo)
    return max(PROBE_WIDTH - field.width(), COMBO_CHROME)


def _spin_chrome(box) -> int:
    """How much of a spin box this style spends on what is not the value."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QStyle, QStyleOptionSpinBox

    option = QStyleOptionSpinBox()
    option.initFrom(box)
    option.subControls = (QStyle.SubControl.SC_SpinBoxUp
                          | QStyle.SubControl.SC_SpinBoxDown
                          | QStyle.SubControl.SC_SpinBoxFrame
                          | QStyle.SubControl.SC_SpinBoxEditField)
    option.buttonSymbols = box.buttonSymbols()
    option.frame = box.hasFrame()
    option.rect = QRect(0, 0, PROBE_WIDTH, box.sizeHint().height())
    field = box.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox, option,
        QStyle.SubControl.SC_SpinBoxEditField, box)
    return max(PROBE_WIDTH - field.width(), SPINBOX_CHROME)


def _spin_width(box, text: str) -> int:
    """Wide enough for `text` beside whatever arrows this style draws."""
    return max(box.fontMetrics().horizontalAdvance(text) + _spin_chrome(box)
               + CARET,
               box.sizeHint().width())


def _widest_drawing(fm, text: str) -> str:
    """`text` with every hex digit swapped for the widest this font draws."""
    widest = max(HEX_DIGITS, key=fm.horizontalAdvance)
    return "".join(widest if c in HEX_DIGITS else c for c in text)


def _line_width(edit, text: str) -> int:
    """The same for a line edit, where the chrome is the frame and margins."""
    from PyQt6.QtCore import QSize
    from PyQt6.QtWidgets import QStyle, QStyleOptionFrame

    wanted = edit.fontMetrics().horizontalAdvance(text) + CARET
    option = QStyleOptionFrame()
    option.initFrom(edit)
    option.lineWidth = (edit.style().pixelMetric(
        QStyle.PixelMetric.PM_DefaultFrameWidth, option, edit)
        if edit.hasFrame() else 0)
    full = edit.style().sizeFromContents(
        QStyle.ContentsType.CT_LineEdit, option,
        QSize(wanted, edit.sizeHint().height()), edit).width()
    return max(full, wanted + LINE_CHROME)


def _content_height(view) -> int:
    """How tall a table has to be to show every row it has."""
    rows = view.model().rowCount() if view.model() is not None else 0
    return (view.horizontalHeader().height()
            + sum(view.rowHeight(r) for r in range(rows))
            + 2 * view.frameWidth())


def _fit_height(view, fixed: bool = False) -> None:
    """Show every row rather than scrolling."""
    height = _content_height(view)
    view.setMinimumHeight(height)
    if fixed:
        view.setMaximumHeight(height)


#: 0x0EB bit 2. The one class bit this file still names for itself; magic-user
#: and cleric were named here too, as the whole of the spellbook's gate, and
#: that is what `enums.caster_bits` replaced (#86).
CLASS_THIEF = 4


def boxes_needing_class(game=None) -> dict[str, tuple[int, str]]:
    """Which class bits a group box applies to, and what to say when it does
    not: `{objectName: (bits, why)}`.
    """
    return {
        "box_thief_skills": (CLASS_THIEF,
                             "Thief skills belong to a thief; this character "
                             "is not one, and the game never reads these "
                             "bytes."),
        "box_spells": (caster_bits(game),
                       "This character casts no spells, so there is no "
                       "spellbook and nothing to memorize."),
    }


class RowSplitter(QObject):
    """The character editor's two rows, and the heights a user drags them to.

    The roster and Character sat above the Stats / Inventory / Spells tabs in
    one column that shared its height by rule: the tabs took every spare
    pixel and the top row took exactly what its fields asked for. At a large
    UI font that is a lot -- eleven rows of combo and spin boxes is 456px at
    25pt against 202 at 9 -- and Donald, running his desktop at 25pt, could
    see the stats table and neither the roster nor Character: *"Maybe the top
    row of the Character Editor should be resizable?"* (#97).

    So it is a divider now, and the person looking at the screen decides how
    the height is shared. It is the answer `#162` gave for the map page's
    three columns, and `ColumnSplitter` there is its twin -- named rather than
    imported, because this package reads nothing from the live-reading side
    and `tests/test_wish.py` greps for it. The same two rulings settle both:

    * *"a dragged width on a column should be remembered when Wish opens
      again"* -- `Settings.editor_rows`, two numbers in the JSON;
    * *"Sure, let the user drag it down to nothing. As long as they can drag
      it back out when they do that."*

    **The second is the whole of the difficulty**, because a row dragged shut
    has no height left to grab. The handle is `HANDLE` tall rather than the
    style's four pixels, Qt goes on drawing it against the edge of a collapsed
    pane, and the heights are restored with `QSplitter.setSizes`, which
    honours a zero without hiding anything -- so a window opened from a
    settings file that already holds a zero still has a divider in it on the
    first frame.
    """

    #: Top to bottom, and the order the heights are written to the settings
    #: file in.
    HEADER_AT, SHEET_AT = 0, 1
    ROWS = 2

    #: How tall the divider is. Qt's style answers four, which is enough while
    #: there is a pane beside it to aim at; a pane dragged shut leaves the
    #: divider as the whole of the way back, so it is set rather than
    #: inherited for that one case. `ColumnSplitter.HANDLE` is the same number
    #: for the same reason.
    HANDLE = 6

    #: What the top row may be squeezed to when the window has no height to
    #: spare, in lines of the user's own font. Not zero: a pane with no height
    #: is one nobody can see is there, and the window would open looking as
    #: though the roster had gone. Not the height of what is in it either --
    #: that is the 456px at 25pt this exists to stop putting a floor under the
    #: window. Two lines is enough to read the roster's headings and to aim
    #: the divider at, and it is measured from the font rather than written
    #: down, so it means the same on a machine whose text is bigger.
    HEADER_LINES = 2

    def __init__(self, root: QWidget, settings,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.settings = settings
        from PyQt6.QtWidgets import QSplitter
        self.splitter = root.findChild(QSplitter, "editor_split")
        self.header = root.findChild(QWidget, "editor_header")
        if self.splitter is None or self.splitter.count() != self.ROWS:
            _log.debug("no character editor row splitter to manage")
            self.splitter = None
            return
        self.splitter.setHandleWidth(self.HANDLE)
        # Spare height goes to the sheet, which is what the column layout did
        # before there was a divider: every box in the top row is sized to the
        # widest value its bytes can hold, so a pixel more there is a pixel of
        # nothing.
        self.splitter.setStretchFactor(self.HEADER_AT, 0)
        self.splitter.setStretchFactor(self.SHEET_AT, 1)
        if self.header is not None:
            self.header.setMinimumHeight(
                self.HEADER_LINES * self.header.fontMetrics().height())
        self.splitter.splitterMoved.connect(self._dragged)
        self.restore()

    def defaults(self) -> list[int]:
        """What the two rows open at with nothing remembered: the top row as
        tall as its fields, and the sheet asking for nothing, because the
        stretch factors above hand it everything the top row does not want.
        """
        wanted = self.header.sizeHint().height() if self.header else 1
        return [wanted, 1]

    def heights(self) -> list[int]:
        """What the two rows are, top to bottom, right now."""
        return list(self.splitter.sizes()) if self.splitter else []

    def restore(self) -> None:
        """Open at the remembered heights, or at the defaults.

        Before the window is shown, deliberately: `setSizes` records what each
        row asked for and the splitter divides the real height against those
        the moment there is one, so the first frame is already the right shape
        rather than the default shape corrected afterwards.
        """
        if self.splitter is None:
            return
        remembered = self.settings.row_heights(self.ROWS)
        self.splitter.setSizes(remembered
                               if remembered is not None else self.defaults())

    def _dragged(self, _pos: int, _index: int) -> None:
        """Record a divider the user just moved.

        Only a drag writes here, and not a window resize: the heights a
        squeezed window forces on the rows are the window's, and overwriting
        somebody's chosen height with them is how a preference goes missing
        without anybody touching it. The file is written when the window
        closes, by `Settings.save`.
        """
        self.settings.editor_rows = self.heights()


class RosterModel(QAbstractTableModel):
    """Name, race, class, AC, HP.

    The game's own party list prints only name, AC and HP, and mirroring it was
    right for recognising the party. An editor is a different job: you are
    picking who to work on, and "the dwarf fighter" is how you think of them.
    Race and class come from the record; AC and HP from the SAVEDGAME1 roster,
    which is the only place a save keeps them.
    """

    HEADERS = ("Name", "Race", "Class", "AC", "HP")

    party: Party | None = None

    def __init__(self, party: Party | None = None):
        super().__init__()
        self.party = party

    def rowCount(self, _parent=QModelIndex()) -> int:
        return len(self.party) if self.party else 0

    def columnCount(self, _parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (orientation is Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole):
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.party is None:
            return None
        m = self.party.member(index.row())
        if role == Qt.ItemDataRole.DisplayRole:
            return (m.name, m.race_name, m.class_name,
                    "" if m.armour_class is None else str(m.armour_class),
                    m.hp_text)[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole:
            if index.column() == HP_COLUMN and m.wounded:
                return QBrush(WOUNDED)
            if index.column() == 0 and m.is_npc:
                return QBrush(NPC)
        if role == Qt.ItemDataRole.ToolTipRole and m.is_npc:
            return "NPC (0x0B8 bit 7)"
        return None


class EditorBinding(QObject):
    """Binds editor fields to goldbox record data. Works on any widget tree."""

    #: A save was opened, or Save As pointed the window at another file.
    opened = pyqtSignal(str)

    def __init__(self, root: QWidget, path: str | None = None,
                 game_disk: str | None = None, disks: str | None = None,
                 backups: str | None = None, last_save_folder: str = "",
                 saves_folder: str = "",
                 game_folders: dict[str, str] | None = None):
        super().__init__(root)
        self.root = root
        self.party: Party | None = None
        self.path: pathlib.Path | None = None
        self.game_disk = game_disk
        self.disks = disks
        self.backups = backups
        self.last_save_folder = last_save_folder
        self.saves_folder = saves_folder
        # `Settings.game_folders` (`#22 (A disk folder setting per game, not
        # one shared by all six)`), handed in by the caller rather than read
        # here: `editor/` may not import `automap` (`INDEX.md`), so whoever
        # constructs this binding -- `wish.window.WishWindow`, which already
        # imports `automap.config` -- passes the mapping on.
        self.game_folders = game_folders or {}
        self.game_disk_found: str | None = None
        self.icon_parts_disk: str | None = None
        self.charset: bytes = b""
        self.item_names: dict[int, str] = {}
        self.templates: dict[str, bytes] = {}
        self.item_types: dict[int, object] = {}
        self.spell_names: dict[int, str] = {}
        self.current_row = -1
        self.dirty: set[int] = set()
        self._loading = False
        self._sized = False

        self.model = RosterModel()
        self.roster = self._child("roster")
        if self.roster is not None:
            self.roster.setModel(self.model)
            self.roster.setSelectionBehavior(
                self.roster.SelectionBehavior.SelectRows)
            self.roster.setStyleSheet(TABLE_SELECTION)
            sel = self.roster.selectionModel()
            if sel is not None:
                sel.currentRowChanged.connect(self._row_changed)

        self.items = InventoryModel()
        self.items.edited.connect(self._edited)
        self.traits = ItemTraitsModel()
        traits = self._child("traits")
        if traits is not None:
            traits.setModel(self.traits)
            traits.horizontalHeader().setStretchLastSection(True)
            traits.verticalHeader().setVisible(False)
        table = self._child("inventory")
        if table is not None:
            table.setModel(self.items)
            table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
            table.setStyleSheet(TABLE_SELECTION)
            table.selectionModel().currentRowChanged.connect(self._show_traits)
        self._preview: QDialog | None = None
        self._connect("button_preview", self.preview)
        self._connect("button_item_add", self.add_item)
        self._connect("button_item_delete", self.delete_item)

        self._connect("button_open", self.open_file)
        self._connect("button_save", self.save)
        self._connect("button_save_as", self.save_as)
        self._toolbar_icons()

        self._widgets = self._find_field_widgets()
        self._build_trait_buttons()
        self._build_active_effects()
        self._fill_combos()
        self._size_fields()
        self._compact()
        # `_compact` already measures `columns_identity` with no rows to
        # show, through `_pin_identity_columns`; the roster wants the same
        # pass, or it keeps the width Designer's layout gives it until a
        # save arrives and `_size_roster` is called again from `_adopt`.
        self._size_roster()
        self._weight_columns()
        self._wire_dirty()

        self._game_label = self._child("label_game")
        if self._game_label is None:
            self._game_label = QLabel("")
            self._game_label.setObjectName("label_game")
            if hasattr(self.root, "statusBar") and self.root.statusBar() is not None:
                self.root.statusBar().addPermanentWidget(self._game_label)

        if path:
            self.load(path)
        else:
            self.status("Open a save disk to begin")

    def _toolbar_icons(self) -> None:
        """Icons beside the button text, never instead of it."""
        from ui.iconpaint import icon_pixmap
        for name, icon in (("button_open", "open-folder"),
                           ("button_save", "save"),
                           ("button_save_as", "save"),
                           ("button_preview", "brass-eye")):
            button = self._child(name)
            if button is not None:
                button.setIcon(QIcon(icon_pixmap(icon, TOOLBAR_ICON, MUTED_INK)))

    def _child(self, name: str) -> QWidget | None:
        """A widget by objectName, or None if Designer no longer has one."""
        return self.root.findChild(QWidget, name)

    def _connect(self, name: str, slot) -> None:
        button = self._child(name)
        if button is not None:
            button.clicked.connect(lambda _checked=False: slot())

    # -- the traits box's two buttons -------------------------------------

    def _build_trait_buttons(self) -> None:
        """Wire Add and Remove to the traits box.

        Designer keeps the container so the box can be rearranged. The box
        still comes off the form if `item_effects` was never promoted to
        `EffectsView` -- a defensive fallback, not a feature gate.
        """
        box = self._child("traits_buttons")
        view = self._widgets.get("item_effects")
        if box is None:
            return
        if not hasattr(view, "add"):
            parent = box.parentWidget()
            layout = parent.layout() if parent is not None else None
            if layout is not None:
                layout.removeWidget(box)
            box.setParent(None)
            box.deleteLater()
            return
        for name, text, slot in (
                ("button_trait_add", trait_effects.BUTTON_ADD, self.add_trait),
                ("button_trait_remove", trait_effects.BUTTON_REMOVE,
                 self.remove_trait)):
            button = self._child(name)
            if button is not None:
                button.setText(text)
            self._connect(name, slot)
        model = view.selectionModel()
        if model is not None:
            model.selectionChanged.connect(lambda *_: self._show_trait_buttons())
        view.changed.connect(self._show_trait_buttons)
        self._show_trait_buttons()

    # -- the active-effects panel -----------------------------------------

    def _build_active_effects(self) -> None:
        """The read-only panel beside the roster.

        The title is set from the module rather than left in `wish/window.ui`,
        because `BOX_TITLE` is Donald's own wording
        (`.claude/rules/gui-text.md`) and the form is not where an approved
        string is kept.
        """
        box = self._child("box_active_effects")
        if box is None:
            return
        box.setTitle(activeeffects.BOX_TITLE)

    def _active_effects_view(self):
        view = self._child("active_effects")
        return view if hasattr(view, "set_party") else None

    def _show_active_effects(self) -> None:
        """Fill the panel from the open save, and hide the box when there is
        no save to fill it from.

        **Hidden and not disabled**, so a `.chr` export or a roster disk shows
        no panel at all rather than an empty one somebody has to be told the
        meaning of -- `party.save0 is None` is the case, and it is what
        `docs/133-active-effects.md` asks for. Hidden and not destroyed
        because the same window opens a save next, and a deleted box cannot
        come back.
        """
        view = self._active_effects_view()
        if view is None:
            return
        view.set_party(self.party)
        box = self._child("box_active_effects")
        if box is not None:
            box.setVisible(self.party is not None
                           and self.party.save0 is not None)

    def _show_trait_buttons(self) -> None:
        """Add is off when the ten slots are full -- nine, if a fill byte holds
        the tenth -- and Remove is off until a slot with something in it is
        picked. A button that would do nothing is a button that says nothing.
        """
        view = self._widgets.get("item_effects")
        if view is None or not hasattr(view, "room"):
            return
        add, remove = (self._child("button_trait_add"),
                       self._child("button_trait_remove"))
        if add is not None:
            add.setEnabled(self.party is not None and bool(view.room()))
        if remove is not None:
            remove.setEnabled(self.party is not None and view.can_remove())

    def add_trait(self) -> None:
        """Pick a code and put it in the first free slot."""
        view = self._widgets.get("item_effects")
        if view is None or self.party is None or not view.room():
            return
        from .traitpicker import TraitPicker
        dialog = TraitPicker(self._game(), tuple(view.codes()), self.root)
        try:
            if dialog.exec() and dialog.chosen:
                view.add(dialog.chosen)
        finally:
            dialog.deleteLater()

    def remove_trait(self) -> None:
        """Clear the selected slot and close the gap behind it."""
        view = self._widgets.get("item_effects")
        if view is None or self.party is None:
            return
        view.remove(view.selected_row())

    # -- binding ----------------------------------------------------------

    def _find_field_widgets(self) -> dict[str, QWidget | SpellEditor]:
        """Every `field_*` widget on the form, whatever tab it ended up on.

        An unmatched name is a hard error: a typo in Designer should be loud,
        not a field that silently never loads.
        """
        found: dict[str, QWidget | SpellEditor] = {}
        known = set(bindings(in_save=True))
        for widget in self.root.findChildren(QWidget):
            name = field_name(widget.objectName())
            if name is None:
                continue
            if name == "icon":
                found["icon"] = widget
                continue
            if name == "spells_known":
                continue
            if name.startswith("spells_memorised_"):
                continue
            if name not in known:
                raise KeyError(
                    f"{widget.objectName()!r} on the form matches no field in "
                    f"goldbox/layout.py")
            found[name] = widget
        if self.root.findChild(QWidget, "field_spells_known") is not None:
            found["spells_known"] = SpellbookEditor(self.root)
        if self.root.findChild(QWidget, "field_spells_memorised_list") is not None:
            found["spells_memorised"] = MemorisedEditor(self.root)
        elif isinstance(self.root.findChild(QWidget, "field_spells_memorised"), MemorisedEditor):
            found["spells_memorised"] = self.root.findChild(QWidget, "field_spells_memorised")
        return found

    def _fill_combos(self, game: por_games.C64Container | None = None) -> None:
        """Name the codes for the fields whose encoding is known, per title."""
        tables = tables_for(game)
        for name, w in self._widgets.items():
            if isinstance(w, QComboBox) and name in tables:
                w.clear()
                for code, label in sorted(tables[name].items()):
                    w.addItem(f"{code}  {label}", code)
                _size_combo(w)
            elif hasattr(w, "set_game"):
                # The Character Traits list, whose codes are per title too:
                # Silver Blades gives an elf 95 where Pool of Radiance gives
                # 107, and 95 is another ability entirely (#186).
                w.set_game(game)

    def _compact(self) -> None:
        """Squeeze the whitespace out of every form and table on the sheet."""
        for form in self.root.findChildren(QFormLayout):
            form.setVerticalSpacing(FORM_VERTICAL_SPACING)
            form.setHorizontalSpacing(FORM_HORIZONTAL_SPACING)
            form.setContentsMargins(*FORM_MARGINS)
            form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        for box in self.root.findChildren(QGroupBox):
            box.setFlat(True)
            inner = box.layout()
            if inner is not None and inner.count() and all(
                    inner.itemAt(i).layout() is not None
                    or type(inner.itemAt(i).widget()) is QWidget
                    for i in range(inner.count())):
                inner.setContentsMargins(0, 0, 0, 0)
            if box.objectName() not in WIDE_BOXES:
                box.setMaximumWidth(max(box.sizeHint().width(),
                                        box.minimumSizeHint().width()))

        for name, floor in LIST_FLOOR.items():
            box = self._child(name)
            if box is not None:
                box.setMinimumHeight(floor)

        # Before the loop below and not after it, because the loop reads
        # `box_identity.minimumSizeHint()` and that number can be stale. A
        # `QSplitter` measures a pane the moment it is given one, which is in
        # `setupUi` -- before the dropdowns have anything in them -- and Qt
        # caches what it measured against `columns_identity`'s layout item.
        # Read cold, Character asks for 218px rather than 495 and is then held
        # to a 200px floor it was never meant to have: the whole point of
        # `HEADER_FLOOR` is that it may be squeezed to 480 and no further.
        # `_pin_identity_columns` sets a minimum on `columns_identity`, and
        # setting one is what throws the cache away.
        self._pin_identity_columns()
        for name, floor in HEADER_FLOOR.items():
            box = self._child(name)
            if box is None:
                continue
            box.setMinimumWidth(min(floor, box.minimumSizeHint().width()))
        for name in TOOLBAR_BUTTONS:
            button = self._child(name)
            if button is not None:
                button.setMinimumWidth(TOOLBAR_BUTTON_MIN_WIDTH)

        for table in self.root.findChildren(QAbstractItemView):
            head = getattr(table, "verticalHeader", lambda: None)()
            if head is not None:
                head.setDefaultSectionSize(TABLE_ROW_HEIGHT)
                head.setMinimumSectionSize(TABLE_ROW_HEIGHT)

    def _pin_identity_columns(self) -> None:
        """Hold Character's two columns to what they need, and let the box clip."""
        columns = self._child("columns_identity")
        if columns is None or columns.layout() is None:
            return
        columns.layout().setContentsMargins(0, 0, 0, 0)
        columns.setMinimumWidth(0)
        wanted = columns.layout().minimumSize().width()
        columns.setMinimumWidth(wanted)
        box = self._child("box_identity")
        if box is not None and box.layout() is not None:
            margins = box.layout().contentsMargins()
            box.setMaximumWidth(max(box.sizeHint().width(),
                                    wanted + margins.left() + margins.right()))

    def _weight_columns(self) -> None:
        """Spare width goes where something can use it."""
        grid = self.root.findChild(QGridLayout, "sheet_columns")
        if grid is None and hasattr(self.root, "ui"):
            grid = getattr(self.root.ui, "sheet_columns", None)
        if grid is not None:
            traits = self._child("box_effects")
            if traits is not None:
                grid.setAlignment(traits, Qt.AlignmentFlag.AlignTop)
            for i, stretch in enumerate(STATS_COLUMN_STRETCH):
                grid.setColumnStretch(i, stretch)
            for i, stretch in enumerate(STATS_ROW_STRETCH):
                grid.setRowStretch(i, stretch)

        for name, stretch in ROW_STRETCH.items():
            row = self.root.findChild(QLayout, name)
            if row is None and hasattr(self.root, "ui"):
                row = getattr(self.root.ui, name, None)
            if row is None:
                continue
            for i in range(row.count()):
                row.setStretch(i, stretch[i] if i < len(stretch) else 0)

        # The active-effects panel takes the slack as well: it is a table of
        # two sentences, and it and the roster are the only things in the
        # header that can read a wider window. Its own maximum width -- its
        # two columns at their contents -- is where it stops, and what
        # neither can use still ends in the spacer.
        #
        # Set by widget and not by a position in `ROW_STRETCH`, so a rearrange
        # of the row in Designer cannot silently hand the slack to the wrong
        # item.
        panel = self._child("box_active_effects")
        if panel is not None:
            row = self.root.findChild(QLayout, "header_row")
            if row is not None and row.indexOf(panel) >= 0:
                row.setStretch(row.indexOf(panel), 1)

    def _size_fields(self) -> None:
        """Give every box the width of the widest value its bytes can hold."""
        for name, w in self._widgets.items():
            if isinstance(w, QComboBox):
                _size_combo(w)
                continue
            field = FIELDS_BY_NAME.get(name)
            if field is None:
                continue
            span = value_range(field)
            if isinstance(w, QSpinBox) and span is not None:
                w.setRange(*span)
            if isinstance(w, (QSpinBox, QLineEdit)):
                text = _widest_drawing(w.fontMetrics(), widest_text(field))
                width = (_spin_width(w, text) if isinstance(w, QSpinBox)
                         else _line_width(w, text))
                if name in TRIMMED:
                    width = round(width * TRIMMED[name])
                w.setMinimumWidth(width)
                w.setMaximumWidth(width)

    def _wire_dirty(self) -> None:
        for name, w in self._widgets.items():
            if isinstance(w, QSpinBox):
                w.valueChanged.connect(self._edited)
            elif isinstance(w, QLineEdit):
                w.textEdited.connect(self._edited)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self._edited)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._edited)
            elif isinstance(w, SpellEditor):
                w.changed.connect(self._edited)
            elif isinstance(w, trait_effects.EffectsView):
                # Only Add and Remove emit this, so a run with the flag off
                # can never mark the sheet dirty from the traits box.
                w.changed.connect(self._edited)
            elif hasattr(w, "iconChanged"):
                w.iconChanged.connect(self._edited)
        book, memorised = self._spell_widgets()
        if book is not None and memorised is not None:
            book.changed.connect(
                lambda: memorised.set_known(book.known()))

    def _spellbook_raw(self, record) -> bytes:
        """The whole mask at 0x078, both declared fields of it."""
        return b"".join(record.get_raw(f) for f in SPELLBOOK_FIELDS)

    def _set_spellbook_raw(self, record, raw: bytes) -> None:
        """The inverse, writing back only the halves that actually moved."""
        at = 0
        for name in SPELLBOOK_FIELDS:
            size = FIELDS_BY_NAME[name].size
            chunk = raw[at:at + size]
            if len(chunk) == size and chunk != record.get_raw(name):
                record.set_raw(name, chunk)
            at += size

    def _memorised_raw(self, record) -> bytes:
        """The memorised-spell list, as wide as the open title reads it.

        Not `record.get_raw("spells_memorised")`: the declared field is the 69
        bytes every measured title agrees about, and Pool of Radiance's own
        list is 81 from `0x020` while Silver Blades' is 74 from `0x01B`. A
        character with more than the declared width memorised lost the rest
        the moment the sheet was saved (#268).
        """
        return c64_codec.get_memorised(record, self._game())

    def _set_memorised_raw(self, record, raw: bytes) -> None:
        """The inverse, over the same span, and only when it moved."""
        if raw != c64_codec.get_memorised(record, self._game()):
            c64_codec.set_memorised(record, raw, self._game())

    def _game(self):
        """The open title, or None before a save is open."""
        return self.party.game if self.party is not None else None

    def _spell_widgets(self) -> tuple[SpellbookEditor | None, MemorisedEditor | None]:
        book = self._widgets.get("spells_known")
        memorised = self._widgets.get("spells_memorised")
        return (book if isinstance(book, SpellbookEditor) else None,
                memorised if isinstance(memorised, MemorisedEditor) else None)

    def _edited(self, *_a) -> None:
        if self._loading or self.current_row < 0:
            return
        self.dirty.add(self.current_row)
        self._retitle()

    # -- files ------------------------------------------------------------

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.root, "Open a save disk",
            files.open_start_dir(self.last_save_folder, self.path,
                                 self.saves_folder),
            DISK_FILTER)
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        try:
            party = Party(path)
        except Exception as exc:
            _log.exception("could not open %s", path)
            QMessageBox.critical(self.root, "Cannot open", str(exc))
            return
        self._adopt(party, path)

    def _adopt(self, party: Party, path: str | None, note: str | None = None,
               dirty: bool = False) -> None:
        """Show a party that is already built, from wherever it came."""
        self.party = party
        self.path = pathlib.Path(path) if path else None
        self.dirty = set(range(len(party))) if dirty else set()
        self.current_row = -1
        self._fill_combos(party.game)
        self._load_game_disk()
        self.model.beginResetModel()
        self.model.party = party
        self.model.endResetModel()
        self._show_active_effects()
        self._size_roster()
        self._pin_identity_columns()
        roster = self._child("roster")
        if roster is not None and len(party):
            roster.selectRow(0)
        self._apply_read_only()
        if self._game_label is not None:
            self._game_label.setText(party.game.title if party.is_save else "")
        self.status(note if note is not None else
                    f"{party.describe()}"
                    + ("" if self.charset else
                       "  -- no game disk, so no item names and no icons"))
        self._retitle()
        if self.path is not None:
            self.opened.emit(str(self.path))

    # -- importing --------------------------------------------------------

    def game_files_for_import(self):
        """The icon, `ANIMATE00` and the creation menu a conversion needs, or
        None for the first two (#118).

        The creation menu's two tables (#57) come off the same disks
        directory, through `goldbox.portraits.tables_from_disks`. Unlike the
        icon and `ANIMATE00`, a conversion needs no disk for them: a
        directory with no side carrying `GEN` leaves `portraits` `None`, and
        `goldbox.dos_codec.to_neutral` falls back to the stored menu -- twenty-six
        numbers read out of `GEN` once and committed, so every character
        still arrives with his own face. Reading the player's own disks is
        kept because it is the check that the stored numbers are still
        right, not because a conversion depends on it (#131).

        The open party's own title -- or the default title with none open --
        says which folder in Preferences (`Settings.game_folders`,
        `#22 (A disk folder setting per game, not one shared by all six)`) to
        try beside the shared one, the way `game_files_for` below already
        does for the destination (`#342 (A Curse or Silver Blades save
        cannot be converted unless its C64 sides sit in the Pool of
        Radiance disk folder)`).
        """
        from goldbox import dos_codec
        from goldbox.d64 import load_payload
        from goldbox.portraits import PortraitError, tables_from_disks

        from .dosimport import GameFiles

        def read_animate(disk):
            return load_payload(disk, dos_codec.ANIMATE_FILE)

        game = self.party.game if self.party is not None else por_games.DEFAULT
        icon_disk = self._find_disk(IconParts.load, game=game)
        animate_disk = self._find_disk(read_animate, game=game)
        if icon_disk is None or animate_disk is None:
            return None
        own = self._own_disk_folder(game)
        portraits = None
        for candidate in (self.disks, own):
            if not candidate:
                continue
            try:
                portraits = tables_from_disks(candidate)
                break
            except (PortraitError, OSError) as exc:
                _log.debug("no creation menu off %s: %s", candidate, exc)
        try:
            return GameFiles(icon=IconParts.load(icon_disk),
                             animate=read_animate(animate_disk),
                             portraits=portraits)
        except Exception:
            _log.exception("could not read the import's game files off "
                           "%s and %s", icon_disk, animate_disk)
            return None

    def game_files_for(self, game):
        """The icon, `ANIMATE00` and the creation menu a conversion into
        `game` needs, or `None` for the first two.

        `game_files_for_import` above answers the same question for the
        *open* party's title; this is `#52 (File ▸ Import and File ▸ Export
        for every direction the library supports)`'s `ConvertDialog`'s own
        version, which asks for the **destination**'s disks instead. Three
        C64 titles convert now (`editor.convert.DIRECTIONS`), so a Curse DOS
        save converted with a Pool of Radiance party open -- or none open at
        all -- has to read `ANIMATE00` off a `CURSE*` disk, not a `POOL*`
        one; `_disk_candidates`'s `pattern` argument is what makes that
        possible without it caring what, if anything, is open.

        Portrait tables are asked for only when `game` is Pool of Radiance:
        `#300 (A Curse or Silver Blades party imported to the C64 arrives
        with no sheet portrait, because the creation menu is read only off a
        POOL<n>.D64)` established that Curse and Silver Blades draw no sheet
        face at all, so `portraits=None` is the right answer for them and
        not a loss.

        `game` also says which folder in Preferences (`Settings.game_folders`,
        `#22 (A disk folder setting per game, not one shared by all six)`) to
        try beside the one shared folder -- `#342 (A Curse or Silver Blades
        save cannot be converted unless its C64 sides sit in the Pool of
        Radiance disk folder)`: a player with each title in its own folder
        had already set Curse's and Silver Blades' own, and this asked only
        the shared one.
        """
        from goldbox import c64_port, dos_codec
        from goldbox.d64 import load_payload
        from goldbox.portraits import PortraitError, tables_from_disks

        from .dosimport import GameFiles

        def read_animate(disk):
            return load_payload(disk, dos_codec.ANIMATE_FILE)

        pattern = game.disk_glob
        icon_disk = self._find_disk(IconParts.load, pattern, game)
        animate_disk = self._find_disk(read_animate, pattern, game)
        if icon_disk is None or animate_disk is None:
            return None
        portraits = None
        if game.key == c64_port.POOL_OF_RADIANCE.key:
            for candidate in (self.disks, self._own_disk_folder(game)):
                if not candidate:
                    continue
                try:
                    portraits = tables_from_disks(candidate)
                    break
                except (PortraitError, OSError) as exc:
                    _log.debug("no creation menu off %s: %s", candidate, exc)
        try:
            return GameFiles(icon=IconParts.load(icon_disk),
                             animate=read_animate(animate_disk),
                             portraits=portraits)
        except Exception:
            _log.exception("could not read the conversion's game files off "
                           "%s and %s", icon_disk, animate_disk)
            return None

    def import_dos_save(self, folder: str | None = None) -> str:
        """File > Import > DOS Save Folder… Returns what happened, for a test."""
        from goldbox import dos_codec

        from .dosimport import (
            FOLDER_TITLE,
            NO_DISKS,
            NO_DISKS_TITLE,
            NO_SLOTS,
            NO_SLOTS_TITLE,
            DosImportDialog,
        )

        game_files = self.game_files_for_import()
        if game_files is None:
            QMessageBox.critical(self.root, NO_DISKS_TITLE, NO_DISKS)
            return "no game disks"
        if folder is None:
            folder = QFileDialog.getExistingDirectory(
                self.root, FOLDER_TITLE,
                str(self.path.parent if self.path else ""))
        if not folder:
            return "cancelled"
        if not dos_codec.slots_available(folder):
            QMessageBox.warning(self.root, NO_SLOTS_TITLE,
                                NO_SLOTS.format(folder=folder))
            return "no DOS save"
        dialog = DosImportDialog(
            folder, game_files, self.root,
            start_dir=files.open_start_dir(self.last_save_folder, self.path,
                                           self.saves_folder))
        while True:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return "cancelled"
            if dialog.conversion is None:
                return "cancelled"
            self.adopt_conversion(dialog.conversion, dialog.target())
            try:
                return self.save(interactive=False)
            except Exception as exc:
                dialog.refuse(str(exc))

    def adopt_conversion(self, conversion, path: str | None = None) -> str:
        """Show a converted save. Separate so a test can call it."""
        from .dosimport import CONVERTED

        if conversion is None:
            return "cancelled"
        note = CONVERTED.format(slot=conversion.slot) if path is None else None
        party = Party("", game=conversion.game, disk=conversion.disk)
        self._adopt(party, path, note=note, dirty=True)
        return note or ""

    # -- converting ---------------------------------------------------------

    def convert(self, source: str | None = None, destination: str | None = None,
               folder: str | None = None, game: str | None = None,
               disk: str | None = None) -> str:
        """File ▸ Convert… Returns what happened, for a test.

        `source`, `destination`, `folder`, `game` and `disk` pre-fill the
        dialog's rows the way `import_dos_save(folder=...)` pre-fills its
        one row -- given every argument, no picker ever opens, which is how
        a test drives the whole path (`#52 (File ▸ Import and File ▸ Export
        for every direction the library supports)`'s plan comment step C).
        `disk` is the player's own Amiga disk 2, the twin of `game` for an
        Amiga destination (`#36 (Write an Amiga disk image, not just the
        character files)`). With no `source`, the dialog opens with an
        empty `From` row rather than a picker in front of it (`#412 (File ▸
        Convert demands a save in a file picker before it will show you the
        Convert window)`) -- the row's own `Choose` button is the picker
        now. The write itself happens here rather than inside
        `ConvertDialog`, the same split `import_dos_save` keeps between
        rehearsing (the dialog) and committing (this method): `fresh_folder`
        names a folder and `mkdir()`s it immediately afterwards (the review
        of `a60e829`: it names a folder, it does not reserve one), then
        `Direction.write` puts the files in it. A C64 destination is opened
        afterwards the same way `File ▸ Open` opens anything; a DOS or
        Amiga destination is not something the editor can show, so it only
        gets a status line. **Flushes the open party first**, the same as
        `export_source`: without it the dialog reads the disk image as it
        was when the file was opened, not the edits on screen (`#478 (File
        ▸ Convert converts the save as it was opened, not as it is on
        screen, because it never flushes the editor's own edits)`). Guarded
        on `self.party`, since Convert -- unlike Export -- still opens with
        nothing open, to let the picker choose a source.
        """
        from editor import convert as convert_mod

        if self.party is not None:
            self._report_flush_failures(self._flush())
            self._write_back()

        dialog = convert_mod.ConvertDialog(
            source or "", self.party, self.game_files_for,
            destination=destination, game=game, disk=disk, folder=folder,
            # `#413 (The Convert window changes shape depending on which
            # platforms you are converting between)` built the prefilled C64
            # row and nothing passed this, so the row was blank however the
            # player had set Preferences. `_own_disk_folder` is the function
            # it wants, and reads only `Settings.game_folders` -- not
            # `resolve_disks`' full precedence, which would start a search
            # of the machine when no folder is set for either title.
            game_folder=self._own_disk_folder,
            parent=self.root,
            start_dir=files.open_start_dir(self.last_save_folder, self.path,
                                           self.saves_folder))
        while True:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return "cancelled"
            if dialog.rehearsal is None:
                return "cancelled"
            destination_root = pathlib.Path(dialog.folder)
            fresh = convert_mod.fresh_folder(destination_root)
            fresh.mkdir(parents=True)
            try:
                written = dialog.direction.write(dialog.rehearsal, fresh)
            except Exception:
                _log.exception("could not write a conversion into %s", fresh)
                #: `rmtree`, not `rmdir`: a direction's `write` puts several
                #: files in the folder, so a writer that fails partway leaves
                #: it non-empty, where `rmdir` raises and the old handler
                #: swallowed it.  What survived would sit in the player's own
                #: destination under a `wish-YYYY-MM-DD` name, indis-
                #: tinguishable from a conversion that worked.
                shutil.rmtree(fresh, ignore_errors=True)
                dialog.refuse(convert_mod.CANNOT_CONVERT)
                continue
            if dialog.direction.destination_port == "c64":
                self.load(str(written[0]))
                result = f"converted into {fresh}"
            elif dialog.direction.destination_port == "amiga":
                note = convert_mod.CONVERTED_AMIGA.format(
                    slot=dialog.slot or "", folder=fresh)
                self.status(note)
                result = note
            else:
                note = convert_mod.CONVERTED_DOS.format(
                    slot=dialog.slot or "", folder=fresh)
                self.status(note)
                result = note
            #: `dialog` is already closed by this point -- `buttons.accepted`
            #: is wired straight to `QDialog.accept` and fires the instant
            #: Convert is clicked, before this method ever runs. So this
            #: pop-up replaces silence after that close, not the close
            #: itself: the destination's own slot, where one exists, is
            #: still `self.status(note)` above -- Donald's own wording names
            #: only the folder.
            QMessageBox.information(
                self.root, convert_mod.DIALOG_TITLE,
                convert_mod.CONVERT_SUCCESS.format(folder=fresh))
            return result

    # -- exports ----------------------------------------------------------

    def export_source(self):
        """The open save as it stands, edits on screen included."""
        from .exports import NOTHING_OPEN, ExportError, Source

        if self.party is None:
            raise ExportError(NOTHING_OPEN)
        self._flush()
        self._write_back()
        return Source.from_party(self.party, self.path)

    def export_dos_save(self, destination: str | None = None) -> str:
        """File > Export > DOS… Returns what happened, for a test."""
        from .exports import DosExportDialog

        return self._export(DosExportDialog, destination)

    def export_amiga_party(self, destination: str | None = None) -> str:
        """File > Export > Amiga… Returns what happened."""
        from .exports import AmigaExportDialog

        return self._export(AmigaExportDialog, destination)

    def _export(self, dialog_class, destination: str | None) -> str:
        from .exports import FAILED_TITLE, ExportError

        try:
            source = self.export_source()
        except ExportError as exc:
            QMessageBox.warning(self.root, FAILED_TITLE, str(exc))
            return "nothing open"
        dialog = dialog_class(source, destination=destination, parent=self.root)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return "cancelled"
        return self.commit_export(dialog.plan)

    def commit_export(self, plan) -> str:
        """Write a rehearsed export. Separate so a test can call it."""
        from .exports import FAILED_TITLE

        if plan is None:
            return "cancelled"
        try:
            note = plan.write()
        except Exception as exc:
            _log.exception("could not export into %s", plan.destination)
            QMessageBox.critical(self.root, FAILED_TITLE, str(exc))
            return "failed"
        self.status(note)
        return note

    def _size_roster(self) -> None:
        """Measure the roster: the height its rows need, and the width they
        would like, which is not the same as the width it can survive on.
        """
        view = self._child("roster")
        if view is None:
            return
        header = view.horizontalHeader()
        for column in range(self.model.columnCount()):
            header.setSectionResizeMode(column,
                                        header.ResizeMode.ResizeToContents)
        view.resizeColumnsToContents()
        from PyQt6.QtWidgets import QStyle
        bar = view.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        natural = (header.length() + view.verticalHeader().width()
                   + 2 * view.frameWidth() + bar)
        header.setSectionResizeMode(NAME_COLUMN,
                                    header.ResizeMode.Interactive)
        view.measure(natural, header.sectionSize(NAME_COLUMN))
        # With no rows -- an empty window, or a roster disk with nothing on it
        # -- `natural` is the five headings alone, and it is font-derived, so
        # `min(natural, ROSTER_MIN_WIDTH)` would set the window's floor to the
        # headings' own width and bring back #41, which
        # `test_the_windows_minimum_does_not_follow_the_ui_font` caught. The
        # *maximum* still wants setting either way, or the table keeps
        # spreading into whatever the layout has spare (#471).
        #
        # **This gate covers the empty case and nothing more, and the loaded
        # case is not sound.** `ROSTER_MIN_WIDTH` is not a floor a party is
        # always above: an ordinary six-character party measures `natural` at
        # 219 against the constant's 440, so `min` picks the font-derived
        # number here too and the whole window's floor runs 727, 784, 844, 916
        # at +0, +3, +6 and +10 points of UI font. #474 has the measurement
        # and the three ways out; `gamedata.synthetic_party`'s widest-of-
        # everything shape is the one party that stays above 440, which is why
        # `test_the_windows_minimum_does_not_follow_the_ui_font_with_a_save_
        # open` reads a flat 948 and cannot see this.
        if self.model.rowCount():
            view.setMinimumWidth(min(natural, ROSTER_MIN_WIDTH))
        view.setMaximumWidth(natural)
        rows = min(self.model.rowCount(), MAX_ROSTER_ROWS)
        height = (view.horizontalHeader().height()
                  + sum(view.rowHeight(r) for r in range(rows))
                  + 2 * view.frameWidth() + bar)
        view.setMinimumHeight(height + ROSTER_SLACK)
        view.setMaximumHeight(height + ROSTER_SLACK)
        self._size_active_effects(view.maximumHeight())

    def _size_active_effects(self, cap: int) -> None:
        """Hold the effects panel to the roster's height and to a width a
        1366-wide screen can spare, and let it scroll past both.

        The roster is capped at the eight rows a save disk can hold, so it
        never scrolls. This one has 64 slots to draw and cannot be sized to
        them: the header does not scroll, so a table as tall as its contents
        there would be a floor under the whole window that grew with the
        number of spells the party happened to have running.
        """
        panel = self._active_effects_view()
        if panel is None:
            return
        panel.setMaximumHeight(cap)
        from PyQt6.QtWidgets import QStyle
        bar = panel.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        # From what the columns want, not from `QHeaderView.length()`: the
        # last section stretches to the viewport, so its length is a
        # measurement of how wide the panel already is and reading it here
        # would pin the panel to whatever width it happened to open at.
        head = panel.horizontalHeader()
        # The heading's own width where the column has no rows to measure:
        # `sizeHintForColumn` answers -1 on an empty model, and the panel is
        # sized once on load, when a save with nothing running has none.
        columns = sum(max(panel.sizeHintForColumn(c), head.sectionSizeHint(c))
                      for c in range(panel.model().columnCount()))
        natural = columns + 2 * panel.frameWidth() + bar
        floor = min(natural, ACTIVE_EFFECTS_MIN_WIDTH)
        panel.setMinimumWidth(floor)
        panel.setMaximumWidth(max(natural, ACTIVE_EFFECTS_MIN_WIDTH))
        # The box that holds it, not just the table: a `QGroupBox` reserves
        # room for its own title whether or not anything in its layout asks
        # for that much -- an unset minimum width lets `BOX_TITLE` alone set
        # the floor, and that string is 51 characters read by a font this
        # machine does not have. Measured here: an unconstrained box with
        # this title wants 307px at this machine's own font and 505px six
        # points larger, while an explicit `setMinimumWidth` holds the box's
        # contribution to the layout at what was asked for, flat across every
        # font tried. Matching `floor` and not `ACTIVE_EFFECTS_MIN_WIDTH`
        # keeps a narrow panel (an empty save, before it has ever been sized)
        # from being handed more room than its own columns want.
        box = self._child("box_active_effects")
        if box is not None:
            # The constant, not `floor`. `floor` is `min(natural, ...)`, and
            # once Donald's shorter headings of 2026-09-08 made `natural`
            # smaller than the constant, `floor` became the columns' own
            # width -- which grows with the UI font, and took the window's
            # own minimum with it: 1052px at +0pt against 1131px at +10pt,
            # caught by `test_the_effects_panel_is_not_a_floor_under_the_
            # window`. The box's contribution has to be flat across fonts,
            # and a narrow panel being handed the constant costs nothing.
            box.setMinimumWidth(ACTIVE_EFFECTS_MIN_WIDTH)
            # The width fix above stopped the box widening the window, and
            # left its title to be clipped by the box's own frame instead --
            # `QGroupBox` does not cut its title with an ellipsis on its own,
            # it draws past its edge and paints nothing to say a word is
            # missing. `floor` is the box's *guaranteed* width -- it never
            # gets any narrower once opened, whatever the window is resized
            # to afterwards -- so cutting the title to fit `floor` now is
            # never wrong later, only sometimes shorter than it had to be.
            # No title at all. Donald, 2026-09-08: *"I think you actually
            # don't need the `Party Effects` title. You could just change the
            # table column header `Effect` to `Party Effect`."* So the column
            # heading says what the box is, the box says nothing, and the
            # eliding this title used to need went with it.
            box.setTitle(activeeffects.BOX_TITLE)

    def _own_disk_folder(self, game: por_games.C64Container) -> str | None:
        """`game`'s own folder out of `self.game_folders` -- the constructor
        argument sourced from Preferences (`Settings.game_folders`,
        `#22 (A disk folder setting per game, not one shared by all six)`) --
        or `None` with no entry for it.

        Reads only that one mapping, not `automap.paths.resolve_disks`'s full
        precedence -- which also falls back to the shared `disks` setting,
        `$POR_DISKS` and finally a search of common directories when nothing
        is set. Every caller here already has `self.disks` and the rest of
        its own candidates to fall back to, so pulling in the search as well
        would mean a conversion with no folder set for either title quietly
        starts scanning the whole machine.
        """
        own = (self.game_folders.get(game.key, "") or "").strip()
        return own or None

    def _disk_candidates(self, pattern: str | None = None,
                        game: por_games.C64Container | None = None) -> list[str]:
        """`--game-disk`, then that title's own folder in Preferences, then
        the shared Game directory setting, then $POR_GAME_DISK, then any
        game disk of the open title beside the save.

        `pattern` overrides the title the glob searches for -- Pool of
        Radiance's `disk_glob` by default, or the open party's own when one
        is open. `editor.convert.ConvertDialog` passes the *destination*
        title's pattern instead, because a Curse DOS save converted with a
        Pool of Radiance party open needs Curse's own disks, not the open
        party's (`#52`'s plan, "three C64 titles means the disks are chosen
        by the destination title").

        `game` says which title that is, so its own folder in
        `Settings.game_folders` (`#22`) is tried before the one shared
        folder -- without it, a per-title folder the player has already set
        in Preferences is never consulted, only the shared one
        (`#342 (A Curse or Silver Blades save cannot be converted unless its
        C64 sides sit in the Pool of Radiance disk folder)`). A caller with
        no particular title in mind passes nothing, and this candidate is
        skipped exactly as before. This is only the one setting, not
        `automap.paths.resolve_disks`'s full precedence -- that also falls
        back to searching common directories when nothing is set, which is
        right for a caller with nothing else to try and wrong here: this
        method already has `self.disks` and the rest, and must not have a
        filesystem-wide search sprung on it underneath them.
        """
        import glob
        import os
        pattern = pattern or (self.party.game.disk_glob
                              if self.party is not None
                              else por_games.DEFAULT.disk_glob)
        candidates = []
        if self.game_disk:
            candidates.append(self.game_disk)
        own = self._own_disk_folder(game) if game is not None else None
        if own:
            candidates += sorted(glob.glob(str(pathlib.Path(own) / pattern)))
        if self.disks:
            candidates += sorted(glob.glob(str(pathlib.Path(self.disks)
                                               / pattern)))
        env = os.environ.get("POR_GAME_DISK")
        if env:
            candidates.append(env)
        if self.path:
            candidates += sorted(glob.glob(str(self.path.parent / pattern)))
        for named in (self.game_disk, os.environ.get("POR_GAME_DISK")):
            if named:
                beside = pathlib.Path(named).parent
                candidates += sorted(glob.glob(str(beside / pattern)))
        seen, unique = set(), []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    def _find_disk(self, read, pattern: str | None = None,
                  game: por_games.C64Container | None = None) -> str | None:
        """The first candidate `read` succeeds on."""
        for c in self._disk_candidates(pattern, game):
            try:
                read(c)
            except Exception as exc:
                _log.debug("%s does not carry it: %s", c, exc)
                continue
            return c
        return None

    def _find_game_disk(self) -> str | None:
        return self._find_disk(load_icon_charset)

    def _load_game_disk(self) -> None:
        self.charset, self.item_names, self.templates = b"", {}, {}
        self.spell_names, self.item_types = {}, {}
        self._load_icon_parts()
        found = self._find_game_disk()
        self.game_disk_found = found
        if found is None:
            self._apply_spell_table()
            self.traits.set_tables({}, {}, self._spell_table())
            return
        game = self.party.game if self.party is not None else None
        for attr, read in (("charset", load_icon_charset),
                           ("item_names",
                            lambda d: load_item_names(d, game)),
                           ("templates",
                            lambda d: load_item_templates(d, game=game)),
                           ("item_types", load_item_types),
                           ("spell_names",
                            lambda d: load_spell_names(d, game))):
            try:
                setattr(self, attr, read(found))
            except Exception:
                _log.exception("could not read %s off %s", attr, found)
        self.traits.set_tables(self.item_types, self.spell_names,
                               self._spell_table())
        for member in (self.party.members if self.party else []):
            if member.inventory is not None:
                member.inventory.names = self.item_names
        self._apply_spell_table()

    def _spell_table(self):
        """The open title's spell table -- names, groups and mask width."""
        return spell_table(self.party.game if self.party is not None else None)

    def _apply_spell_table(self) -> None:
        """Give every spell widget the open title's names and its own table."""
        table = self._spell_table()
        for w in self._widgets.values():
            if isinstance(w, SpellEditor):
                w.set_names(self.spell_names, table)

    def set_backup_folder(self, folder: str | None) -> None:
        """Where a copy of the save goes before it is overwritten."""
        self.backups = folder

    def set_saves_folder(self, folder: str | None) -> None:
        """Where `File > Open` should start, if the player has chosen one (#66)."""
        self.saves_folder = folder

    def set_disks(self, disks: str | None) -> None:
        """The Game directory changed. Re-read, and redraw what it feeds."""
        if (disks or None) == (self.disks or None):
            return
        self.disks = disks
        self._load_game_disk()
        self._populate()
        if self.party is not None:
            self.status(f"{self.party.describe()}"
                        + ("" if self.charset else
                           "  -- no game disk, so no item names and no icons"))

    def _load_icon_parts(self) -> None:
        """The icon editor's option tables, from whichever disk carries them."""
        self.icon_parts = None
        self.icon_parts_disk = None
        disk = self._find_disk(IconParts.load)
        if disk is None:
            return
        try:
            self.icon_parts = IconParts.load(disk)
        except Exception:
            _log.exception("could not read the icon parts off %s", disk)
            self.icon_parts = None
        else:
            self.icon_parts_disk = disk

    def save(self, interactive: bool = True) -> str:
        """Write the disk back. Returns what happened, for the status bar.

        The two ways there is nothing to write are kept apart on purpose
        (#514): `self.party is None` is an editor with nothing open at all,
        which `close()` never even reaches -- it returns before calling this
        when `self.dirty` is empty, and an empty editor is never dirty.
        `self.path is None` with a party that *is* dirty is the one state a
        converted-but-unnamed party (`adopt_conversion` with no destination)
        can be in. When `interactive`, that opens the same chooser
        `save_as()` opens (#515) -- cancelling it still answers
        `"no destination"`, which is not a successful save: `close()` below
        has to tell the two apart from `"failed"` rather than read either as
        "done". When not `interactive` (`import_dos_save`'s own call), no
        chooser opens and an unnamed party is simply left unwritten.
        """
        if self.party is None:
            return "nothing open"
        if self.path is None:
            if not interactive or not self._choose_save_path():
                return "no destination"
        failures = self._flush()
        if failures and interactive:
            self._report_flush_failures(failures)
        try:
            self._write_back()
            note = files.save_disk(self.party.disk, self.path, self.backup_dir())
        except Exception as exc:
            _log.exception("could not save %s", self.path)
            if interactive:
                QMessageBox.critical(self.root, "Cannot save", str(exc))
                return "failed"
            raise
        self.dirty.clear()
        self.status(note)
        self._retitle()
        return note

    def backup_dir(self) -> str | pathlib.Path:
        """The folder this window would back a save up into."""
        if self.backups is None:
            return files.automatic_dir(self.path)
        return self.backups

    def preview_text(self) -> str:
        """What a save would write, in the form `wish --dry-run` prints it."""
        if self.party is None:
            return "nothing open"
        self._flush()
        return changes.preview(self.party, self.path.name if self.path else "?")

    def preview(self) -> str:
        """Show that report in a window that does not block anything."""
        text = self.preview_text()
        if self._preview is None:
            self._preview = QDialog(self.root)
            self._preview.setWindowTitle("Changes")
            self._preview.resize(640, 420)
            box = QPlainTextEdit(self._preview)
            box.setReadOnly(True)
            box.setObjectName("preview_text")
            QVBoxLayout(self._preview).addWidget(box)
        self._preview.findChild(QPlainTextEdit).setPlainText(text)
        self._preview.show()
        self._preview.raise_()
        return text

    def save_as(self) -> None:
        if self.party is None:
            return
        if self._choose_save_path():
            self.save()

    def _choose_save_path(self) -> bool:
        """Open the `Save As` chooser and adopt what it picks.

        Shared by `save_as()` and by `save()` when a converted-but-unnamed
        party (#515) needs somewhere to go before it can write. False means
        the chooser was cancelled and `self.path` is untouched.
        """
        path, _ = QFileDialog.getSaveFileName(
            self.root, SAVE_AS_TITLE, str(self.path or ""), DISK_FILTER)
        if not path:
            return False
        self.path = pathlib.Path(path)
        self.opened.emit(str(self.path))
        return True

    def _write_back(self) -> None:
        """Push edited records into the disk image."""
        party = self.party
        if party.save0 is not None:
            for m in party.members:
                party.save0.write_record(m.index, m.record)
            party.write_items()
            party.write_icons()
            store_save(party.disk, party.save0, party.save1, party.game)
        else:
            for m in party.members:
                if m.source:
                    party.disk.write_file_inplace(m.source, m.record.to_prg())

    # -- the sheet --------------------------------------------------------

    def _row_changed(self, current, previous) -> None:
        if previous is not None and previous.isValid():
            self._report_flush_failures(self._flush(previous.row()))
        self.current_row = current.row() if current is not None and current.isValid() else -1
        self._populate()

    def _flush(self, row: int | None = None) -> list[str]:
        """Copy what is on screen into the record, before we leave it.

        Returns the on-screen label of every field the user changed whose new
        value could not be written back -- the record keeps what it already
        held for that field. Every editable widget is bounded to what its
        field can hold (a spin box's range, a combo box's own entries, a
        spell widget's fixed-width bytes), so this is expected to come back
        empty -- but a caller must not assume that and drop the return: a
        refusal nobody is told about is what #145 was.
        """
        row = self.current_row if row is None else row
        if self.party is None or not 0 <= row < len(self.party):
            return []
        record = self.party.member(row).record
        icon_widget = self._widgets.get("icon")
        if icon_widget is not None and getattr(icon_widget, "icon", None) is not None:
            self.party.member(row).icon = icon_widget.icon
        failures: list[str] = []
        for name, w in self._widgets.items():
            if name == "icon" or not w.isEnabled():
                continue
            try:
                if isinstance(w, QSpinBox):
                    stored = (combat_byte(w.value()) if name in COMBAT_FIELDS
                              else w.value())
                    if record.get(name) != stored:
                        record.set(name, stored)
                elif isinstance(w, QLineEdit) and name == "name":
                    if record.name != w.text():
                        record.name = w.text()
                elif isinstance(w, QComboBox):
                    # **What was shown, not what is stored.**  For
                    # `char_class` those differ by design since #356: the
                    # combo draws the class the character actually is, and
                    # the record keeps the stale byte Curse's trainer left.
                    # Comparing against the record would make merely opening
                    # a trained Curse save a change, so File > Save would
                    # rewrite a byte the player never touched and
                    # `test_the_editor_writes_a_curse_save_back_unchanged`
                    # would be right to fail.  Comparing against what was
                    # drawn means the repair is a display and a real choice
                    # by the player is still an edit.
                    shown = record.get(name)
                    if name == "char_class":
                        shown = _char_class_shown(
                            shown, record, self.party.member(row).game)
                    if shown != w.currentData():
                        record.set(name, w.currentData())
                elif isinstance(w, SpellbookEditor):
                    self._set_spellbook_raw(record, w.to_bytes())
                elif isinstance(w, MemorisedEditor):
                    self._set_memorised_raw(record, w.to_bytes())
                elif isinstance(w, SpellEditor):
                    if record.get_raw(name) != w.to_bytes():
                        record.set_raw(name, w.to_bytes())
                elif isinstance(w, trait_effects.EffectsView):
                    # **Only when it differs.** `to_bytes` hands back the
                    # bytes it was given until Add or Remove has replaced
                    # them, so an untouched block compares equal and never
                    # reaches `set_raw`. That is what keeps opening and
                    # saving a save with no trait edits byte-identical.
                    if record.get_raw(name) != w.to_bytes():
                        record.set_raw(name, w.to_bytes())
            except Exception:
                _log.exception("could not flush %s", name)
                failures.append(self._field_label(name))
        self.party.member(row).name = record.name
        return failures

    def _field_label(self, name: str) -> str:
        """The text beside `field_<name>` on the sheet, read live so a
        message to the user never falls behind a rename in Designer -- a
        hardcoded name -> label table is exactly the kind of drift #142 was.

        A trailing colon is stripped so a sentence built around this does not
        read "Error: HP rolled: could not be saved." A field with no label of
        its own -- a table cell, something in a group box -- falls back to a
        phrase that says nothing false rather than the internal field name.
        """
        label = self._child(f"label_{name}")
        text = label.text().strip() if isinstance(label, QLabel) else ""
        if text.endswith(":"):
            text = text[:-1].rstrip()
        return text or "a field"

    def _report_flush_failures(self, failures: list[str]) -> None:
        """Pop up Donald's sentence, once per field that refused (#145).

        One dialog for the whole flush, not one pop-up per field -- several
        of those in a row would be worse than the silent failure they
        replace. `failures` only ever holds a field the user actually
        changed: `_flush` assigns a record field, and only reaches that
        assignment, only raises, when the new value differs from what was
        already stored.
        """
        if not failures:
            return
        text = "\n".join(FIELD_NOT_SAVED.format(label=label) for label in failures)
        QMessageBox.critical(self.root, "Cannot save", text)

    def _populate(self) -> None:
        if self.party is None or self.current_row < 0:
            return
        self._loading = True
        member = self.party.member(self.current_row)
        record = member.record
        for name, w in self._widgets.items():
            if name == "icon":
                continue
            try:
                value = record.get(name)
            except Exception as exc:
                _log.debug("no %s on this record: %s", name, exc)
                value = None
            if name == "char_class":
                value = _char_class_shown(value, record, member.game)
            if isinstance(w, QSpinBox):
                if name in COMBAT_FIELDS and isinstance(value, int):
                    value = combat_value(value)
                field = FIELDS_BY_NAME.get(name)
                span = value_range(field) if field is not None else None
                if isinstance(value, int) or span is None:
                    if span is not None:
                        w.setSpecialValueText("")
                        w.setRange(*span)
                    w.setValue(value if isinstance(value, int) else 0)
                else:
                    # A save slot holds only the first 256 of the 580 bytes a
                    # record carries, so this byte is not in the file at all
                    # -- draw blank, not a fabricated zero (#150). The
                    # sentinel sits one below the field's real floor, and
                    # only while there is nothing to show: whenever this
                    # field genuinely holds its lowest legal value the range
                    # above is what applies, so that value still reads as
                    # itself rather than blank.
                    low, high = span
                    w.setRange(low - 1, high)
                    w.setSpecialValueText(" ")
                    w.setValue(low - 1)
            elif isinstance(w, QLineEdit):
                if name == "name":
                    w.setText(record.name)
                elif isinstance(value, (bytes, bytearray)):
                    w.setText(value.hex(" "))
                else:
                    w.setText(str(value or ""))
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(value))
            elif isinstance(w, QComboBox):
                _select(w, value)
            elif hasattr(w, "set_bytes"):
                if isinstance(w, SpellbookEditor):
                    w.set_bytes(self._spellbook_raw(record))
                elif isinstance(w, MemorisedEditor):
                    w.set_bytes(self._memorised_raw(record))
                else:
                    w.set_bytes(record.get_raw(name))
                if hasattr(w, "codes"):
                    _fit_height(w, fixed=True)
        self._show_boxes(record)
        self._describe_spells(record)
        self.items.set_inventory(member.inventory)
        self._size_item_columns()
        self._show_traits()
        self._describe_inventory(member)
        icon_widget = self._widgets.get("icon")
        if icon_widget is not None:
            icon_widget.set_icon(member.icon if self.charset else None,
                                 self.charset)
            size = "large" if (member.record.get("size_small") or 0) & 1 else "small"
            icon_widget.set_parts(getattr(self, "icon_parts", None), size)
            icon_widget.setMaximumWidth(ICON_MAX_WIDTH)
        self._show_trait_buttons()
        self._loading = False

    def _show_boxes(self, record) -> None:
        """Grey the boxes this character has no use for. Hide none of them."""
        try:
            bits = int(record.get("class_bits") or 0)
        except Exception as exc:
            _log.debug("no class_bits, so every class box is greyed: %s", exc)
            bits = 0
        game = self.party.game if self.party is not None else None
        for name, (needed, why) in boxes_needing_class(game).items():
            box = self._child(name)
            if box is None:
                continue
            applies = bool(bits & needed)
            box.setEnabled(applies)
            box.setToolTip("" if applies else why)

    def _apply_read_only(self) -> None:
        """Grey what must not be edited, and say why in the tooltip."""
        if self.party is None:
            return
        rules = bindings(in_save=self.party.in_save)
        for name, w in self._widgets.items():
            if name == "icon":
                w.setEnabled(self.party.save0 is not None)
                continue
            if name == "name":
                # Disabled in wish/window.ui and left alone here -- #145 made
                # the name unreachable everywhere rather than guarding it, and
                # this loop would otherwise re-enable it every load, since a
                # name is not `rule.read_only` by any of binding_for()'s three
                # reasons.
                continue
            rule = rules.get(name)
            if rule is None:
                continue
            passthrough = isinstance(w, QLineEdit)
            if hasattr(w, "setEnabled"):
                w.setEnabled(not rule.read_only and not passthrough)
            if passthrough and not rule.read_only:
                if hasattr(w, "setToolTip"):
                    w.setToolTip("preserved verbatim; the editor cannot write it")
                continue
            if hasattr(w, "setToolTip"):
                # `rule.reason` is a sentence written for a person, e.g. "the
                # game recomputes this from abilities and equipment". An
                # editable field gets no tooltip at all -- the label beside it
                # already names it, and the field's offset, internal name and
                # confidence grade are a developer's note that used to leak
                # here (#419). `goldbox/layout.py` stays the reference for
                # anybody debugging the binding; nothing here duplicates it.
                w.setToolTip(rule.reason if rule.read_only else "")
            label = self._child(f"label_{name}")
            if label is not None:
                label.setEnabled(not rule.read_only)

    def _describe_spells(self, record) -> None:
        """Show what the spellbook holds and how much the class may memorise."""
        book, memorised = self._spell_widgets()
        if memorised is None:
            return
        if book is not None:
            memorised.set_known(book.known())
        game = self.party.game if self.party is not None else None
        memorised.set_capacity(
            capacity(record.class_bits, record.get("level"),
                     record.get("wisdom"), game),
            casts=bool(record.class_bits & caster_bits(game)))

    # -- items ------------------------------------------------------------

    def _size_item_columns(self) -> None:
        """The item column, as wide as the longest name and no wider."""
        table = self._child("inventory")
        if table is None:
            return
        table.resizeColumnsToContents()
        widest = max(self.templates, key=len,
                     default=inventory.LONGEST_ITEM_NAME)
        table.setColumnWidth(
            inventory.NAME,
            table.fontMetrics().horizontalAdvance(widest) + ITEM_NAME_PADDING)

    def _show_traits(self, *_a) -> str:
        """Fill the traits table from whichever item is selected."""
        table = self._child("inventory")
        item = None
        if table is not None and self.items.inventory is not None:
            index = table.currentIndex()
            if index.isValid() and not self.items.inventory.is_empty(index.row()):
                item = self.items.inventory.item(index.row())
        self.traits.set_item(item)
        traits = self._child("traits")
        if traits is not None:
            traits.resizeColumnsToContents()
            _fit_height(traits)
        text = ("Select an item" if item is None
                else inventory.describe(item, self.item_names))
        label = self.root.findChild(QLabel, "label_traits")
        if label is not None:
            label.setText(text)
        return text

    def _describe_inventory(self, member) -> str:
        """The line above the table. Says why names are numbers, when they are."""
        if member.inventory is None:
            text = ("Items live in the save game, so this file has none -- a "
                    "roster disk and a .chr export both carry the character "
                    "only")
        elif not self.item_names:
            text = (f"{member.inventory.used} of 16 slots used. No game disk "
                    f"found, so items show as name-table indices: "
                    f"File > Preferences… to say where the disks are")
        else:
            text = f"{member.inventory.used} of 16 slots used"
        label = self.root.findChild(QLabel, "label_inventory")
        if label is not None:
            label.setText(text)
        for name in ("button_item_add", "button_item_delete"):
            button = self._child(name)
            if button is not None:
                button.setEnabled(member.inventory is not None)
        add = self._child("button_item_add")
        if add is not None and not self.templates:
            add.setEnabled(False)
            add.setToolTip("adding an item copies one of the game disks' own "
                           "163 records; without a game disk there are none. "
                           "File > Preferences… to say where they are")
        return text

    def add_item(self, name: str | None = None) -> str:
        """Copy one of the game's own item records into a free slot."""
        if self.items.inventory is None:
            return "no inventory here"
        if not self.templates:
            return "no game disk, so no items to copy"
        if name is None:
            dialog = AddItemDialog(self.templates, self.root)
            if dialog.exec() != dialog.DialogCode.Accepted.value:
                return "cancelled"
            raw = dialog.chosen()
        else:
            raw = self.templates.get(name)
        if raw is None:
            return f"no item called {name!r}"
        where = self.items.add(raw)
        if where is None:
            return "all sixteen slots are full"
        self._describe_inventory(self.party.member(self.current_row))
        note = f"added {name or 'item'} in slot {where}"
        self.status(note)
        return note

    def delete_item(self, row: int | None = None) -> str:
        if self.items.inventory is None:
            return "no inventory here"
        if row is None:
            table = self._child("inventory")
            index = table.currentIndex() if table is not None else None
            if index is None or not index.isValid():
                return "nothing selected"
            row = index.row()
        if not self.items.delete(row):
            return "that slot is empty"
        self._describe_inventory(self.party.member(self.current_row))
        note = f"deleted the item in slot {row}"
        self.status(note)
        return note

    # -- chrome -----------------------------------------------------------

    def status(self, text: str) -> None:
        if hasattr(self.root, "statusBar") and self.root.statusBar() is not None:
            self.root.statusBar().showMessage(text)
        elif hasattr(self.root, "status"):
            self.root.status(text)
        else:
            sb = self.root.findChild(QWidget, "statusbar")
            if sb is not None and hasattr(sb, "showMessage"):
                sb.showMessage(text)

    def _retitle(self) -> None:
        name = self.path.name if self.path else "no file"
        mark = " *" if self.dirty else ""
        if hasattr(self.root, "setWindowTitle"):
            self.root.setWindowTitle(f"Wish - {name}{mark}")

    def close(self) -> bool:
        """Called when the window is closing, to ask about unsaved edits.

        Checks `self.dirty` rather than Qt's own `isWindowModified()`
        because nothing here ever calls `setWindowModified` -- that flag
        would just read the widget's inherited default of `False`.
        `self.dirty` is this binding's own record of which rows changed,
        added to by `_edited` -- which `_wire_dirty` connects to every
        bound widget's changed signal -- and cleared by `save`.
        """
        if not self.dirty:
            return True
        box = QMessageBox(self.root)
        box.setWindowTitle("Unsaved changes")
        box.setText("Save your changes before closing?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        box.button(QMessageBox.StandardButton.Discard).setText("Don't Save")
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        ans = box.exec()
        if ans == QMessageBox.StandardButton.Cancel:
            return False
        if ans == QMessageBox.StandardButton.Discard:
            return True
        # Not `!= "failed"`: a converted party with no destination
        # (`adopt_conversion`, no path) answers `"no destination"` here,
        # neither an exception nor a written file, and treating that as
        # success closed the window and threw the party away (#505, #514).
        return self.save() not in ("failed", "no destination")
