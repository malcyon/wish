"""The main window: the roster and Character across the top, the sheet on
tabs below them.

The form comes from `editor/character.ui`. Widgets are found by `objectName`
and matched to `goldbox/layout.py` fields, so the form can be rearranged in Qt
Designer -- fields moved between group boxes, regrouped, relabelled -- without
a line of this file changing.
"""

from __future__ import annotations

import logging
import pathlib

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from goldbox import games as por_games
from goldbox.iconparts import IconParts
from goldbox.icons import load_icon_charset
from goldbox.items import load_item_names, load_item_templates, load_item_types
from goldbox.layout import FIELDS_BY_NAME
from goldbox.savegame import store_save
from goldbox.spells import capacity, load_spell_names
from goldbox.spells import for_game as spell_table

from . import changes, files, inventory
from .binding import bindings, field_name, value_range, widest_text
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


def _select(combo: QComboBox, value) -> None:
    """Show `value` in a dropdown, even when the table has no name for it.

    A code outside the game's own table is real data -- monsters carry things
    player characters do not -- so it is added to the list rather than being
    rounded to the nearest thing we recognise.
    """
    if not isinstance(value, int):
        return
    at = combo.findData(value)
    if at < 0:
        combo.addItem(f"{value}  — not in the game's table", value)
        at = combo.count() - 1
        _size_combo(combo)
    combo.setCurrentIndex(at)


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
WIDE_BOXES = ("box_inventory", "box_traits", "box_effects", "box_spells")
# Which item in a horizontal row is allowed to grow. `header_row` is the
# roster and Character, and the roster is the one of the two that can use a
# wider window: every field in Character is sized to the widest value its bytes
# can hold, so a pixel more there is a pixel of nothing.
#
# Round six gave it to Character anyway. Shared 1:1 between its two form
# columns it came out as a gutter down the middle of Character and a gap beside
# it, both of which Donald marked; handed to the fields instead it came out as
# a drop-down 890px wide with `2  ELF` in it.
#
# So the roster takes it, and `header_slack` -- the spacer after Character --
# takes only what the roster cannot use, its maximum being its own five
# columns. That order is #71's fix at the layout level. A `QBoxLayout` short of
# room shrinks every item that has anything to give, in proportion, so while
# the roster hinted its contents Character was squeezed alongside it and drew
# one form column over the other; the roster hints its *floor* and grows from
# there (`RosterView.sizeHint`), which keeps the row in the layout's expanding
# case at every width worth having and leaves Character at its own size until
# the roster has given everything it has.
#
# Giving the spacer a share of the stretch as well was measured and is worse:
# at 1280 with the base font the two split the slack, and the roster came out
# 147px short of its own contents -- eliding names beside 250px of empty
# header.
ROW_STRETCH = {"header_row": (1, 0, 0), "form_identity": (0, 0)}
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
ICON_MAX_WIDTH = 150
STRIP_TABLE_HEIGHT = 150
# Eight is every slot a save disk has and every character a roster disk holds,
# so a roster sized to this never scrolls and never leaves a fifth of the
# window empty.
MAX_ROSTER_ROWS = 8
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
#:
#: Only these two. Measured with every floor taken off: `box_effects` comes to
#: 277px from its ten fixed effect slots and so never reaches a 240 floor;
#: `box_spells` measures 235 and is five pixels shorter than its old floor
#: made it, which nothing can see, and being the only box on its tab it cannot
#: be squeezed below that; and the roster's was overwritten by `_size_roster`
#: on every open, empty party included. These two share the Inventory tab and
#: are the two that lose: without a floor the page stops scrolling and squeezes
#: them instead, which at a 600px window is 2 of 16 item rows and no trait
#: rows, against 5 and 7 with it.
LIST_FLOOR = {"box_inventory": 240, "box_traits": 240}
#: What Character may be squeezed to.
#:
#: Eleven fields, eleven labels and four combo boxes are every one of them
#: sized from font metrics, and they sit in a header that does not scroll, so
#: the box's own minimum *is* the window's floor and it *is* a font-metric
#: number. Measured here in round seven, with the Armour class pair gone to
#: `Combat`: 491px at the default UI font, 608 at three points more, 819 at
#: eight and 880 at ten -- against 521, 648, 874 and 939 in round six. On
#: Windows CI the round-five box took the whole window from 1036 to 1304 --
#: #41's guarantee broken twice over, because the floor followed the font and
#: because 1304 does not fit a 1280 screen either.
#:
#: 480 is written down as a constant on purpose: the floor has to be the same
#: number on every machine, and no measurement taken here is true of Windows.
#: It sits eleven pixels under what the two columns come to at the default UI
#: font here, because the floor is applied as `min(this, what the box wants)`
#: and a constant *above* the hint on some other machine's default font would
#: start following the font again. Round six left itself one pixel of that
#: margin.
#:
#: The cost is that a window dragged narrower than Character really wants
#: squeezes its columns -- #71. That is the trade #41 asks for, and the
#: squeeze is what `_pin_identity_columns` below makes survivable.
HEADER_IDENTITY_MIN_WIDTH = 480
#: Which header boxes are held to a constant, and to what. Keyed by
#: objectName like everything else on the form.
#:
#: One box, since round eight. The combat icon was the other, capped at 166
#: because a `QGroupBox` will not report a minimum narrower than its own title
#: and "Combat icon" passes 166px somewhere past eight points of extra font --
#: 166px of floor at every font size on every platform, and pure floor,
#: because `IconEditor` is `FRAME_WIDE * ZOOM` and cannot read a wider window.
#: It sits beside `Combat` on the Stats tab now, where the page scrolls and a
#: group box wider than its contents costs the window nothing.
HEADER_FLOOR = {"box_identity": HEADER_IDENTITY_MIN_WIDTH}
#: And the row of buttons above the header, which does not scroll either.
#:
#: Each button is as wide as its own text and icon: the four come to 403px at
#: the default UI font here and 971 at twenty-four points more. That is under
#: the capped header at every font this machine can be made to draw, so it
#: never binds here -- but Windows' base font measures like eight or ten
#: points more than this one, and the whole point of a cap is that it holds
#: without a measurement to lean on.
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

#: How a selected row looks, stated rather than left to the platform. The
#: Windows style highlights only the text of each cell and then draws a dotted
#: focus rectangle around the current one, which Donald read -- correctly -- as
#: "a highlighted space before the contents of every cell". `::item:selected`
#: fills the whole cell on every style, `outline: none` takes the focus
#: rectangle away, and `:!active` keeps the row visible when the table has not
#: got the focus. Both colours are given: a rule that set only the ink would be
#: dark on dark under a dark desktop theme.
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
    """How much of a spin box this style spends on what is not the value.

    Measured from the style, not guessed. Windows draws its up/down buttons
    about half as wide again as Fusion does, which is why the ability and
    experience boxes showed Donald arrows and no number on the Windows build
    and were fine on Linux. `subControlRect` is linear in the rect it is given,
    so one probe answers for every width.
    """
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
    """`text` with every hex digit swapped for the widest this font draws.

    `widest_text` answers "the longest string", and for a RAW field every
    string is the same length, so it picks `ff ff ff ff ff ff`. Length is not
    width: in a proportional UI font an `f` is barely half a digit, and the
    box that came out of it was 85px for the 98px `01 00 00 00 00 00` it had
    to show. QLineEdit scrolls to the cursor, which `setText` leaves at the
    end, so what was on screen was the tail -- five groups of `00`, for a
    caster with slots and a fighter without alike (#42).
    """
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
    """Show every row rather than scrolling. Ten effects and a dozen traits
    are short lists, and a scrollbar over four visible rows hides most of a
    list whose whole point is that you can see it.

    `fixed` makes it a ceiling as well, for a table whose row count never
    changes. Character Traits is always its ten slots -- XAVIER proved the
    tenth is real -- and left free it stretched to nearly twice that in the
    column that takes the Stats tab's spare height: empty space in the middle
    of a box, which is the thing Donald asked for none of.

    The item traits table is not fixed and must not be: its row count is
    whatever the selected item carries, and a ceiling there would make the
    Inventory page jump every time you clicked a different item.
    """
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

    These two used to be hidden for a character without the class, and Donald:
    "The layout of the form should not change when we navigate the roster. It
    should stay the same, so people know where to look for things at all
    times." So they are always on the sheet and greyed instead -- a fighter's
    eight thief-skill zeros still must not read as data somebody should type
    in. Keyed by objectName like everything else on the form, so the boxes can
    be moved in Designer.

    **The masks are the open title's, not one game's.** `box_spells` was gated
    on magic-user and cleric as a module constant, which are the only two
    classes in Pool of Radiance that cast -- so a Silver Blades ranger, who has
    a spellbook and whose shipped PAINE knows four spells, was greyed out as if
    he cast nothing (#86). `editor/enums.py::caster_bits` is where the evidence
    for each class lives. Thief skills are the thief's in every title.

    One answer for both jobs it has: greying a box is also what keeps `_flush`
    off it, since a child of a disabled box is itself disabled, so a box that
    is wrongly greyed is a box whose bytes are silently read-only.
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


class RosterModel(QAbstractTableModel):
    """Name, race, class, AC, HP.

    The game's own party list prints only name, AC and HP, and mirroring it was
    right for recognising the party. An editor is a different job: you are
    picking who to work on, and "the dwarf fighter" is how you think of them.
    Race and class come from the record; AC and HP from the SAVEDGAME1 roster,
    which is the only place a save keeps them.
    """

    HEADERS = ("Name", "Race", "Class", "AC", "HP")

    #: On the class as well as on the instance, and that is load bearing.
    #: Destroying the window hides the table, which asks the header for a
    #: column width, which asks the model for `rowCount` -- and by then the
    #: garbage collector may have emptied the model's `__dict__`, because the
    #: window, the view and the model are collected as one cycle. An
    #: `AttributeError` raised inside a Qt virtual is a `qFatal`, so the
    #: process aborts. Falling back to the class attribute answers 0 instead.
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


class EditorWindow(QMainWindow):
    #: A save was opened, or Save As pointed the window at another file. What
    #: the backup folder follows while nobody has chosen one of their own --
    #: which is a preference, so the window over in `wish/` is what listens.
    opened = pyqtSignal(str)

    def __init__(self, path: str | None = None, game_disk: str | None = None,
                 disks: str | None = None, backups: str | None = None,
                 last_save_folder: str = ""):
        """`disks` is the Game directory, already resolved by the caller.

        Handed in rather than looked up, exactly as `game_disk` is: this
        package may not import the live half of the application, and the
        setting lives over there. `tests/test_wish.py` greps this directory for
        the fact.

        `backups` is the same arrangement for where a copy of the save goes.
        **None means nobody is managing it** -- `python -m editor`, with no
        preferences anywhere -- and the copy lands in `backups/` beside the
        save, which is the rule the preference itself starts on. An empty
        string is a caller saying it has no folder to give, and a save then
        refuses rather than going through without a copy.

        `last_save_folder` is the same arrangement again, for where
        `File > Open` should start (#66) -- the setting lives over in the live
        half, so the caller resolves it and hands over a plain string.
        """
        super().__init__()
        from .ui_character import Ui_CharacterWindow
        self.ui = Ui_CharacterWindow()
        self.ui.setupUi(self)

        self.party: Party | None = None
        self.path: pathlib.Path | None = None
        self.game_disk = game_disk
        self.disks = disks
        self.backups = backups
        self.last_save_folder = last_save_folder
        #: Which image each thing was actually read off, for a report that can
        #: say so. They are not always the same disk.
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
        self.ui.roster.setModel(self.model)
        self.ui.roster.setSelectionBehavior(
            self.ui.roster.SelectionBehavior.SelectRows)
        self.ui.roster.setStyleSheet(TABLE_SELECTION)
        sel = self.ui.roster.selectionModel()
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

        self.ui.button_open.clicked.connect(self.open_file)
        self.ui.button_save.clicked.connect(self.save)
        self.ui.button_save_as.clicked.connect(self.save_as)
        self._toolbar_icons()

        self._widgets = self._find_field_widgets()
        self._fill_combos()
        self._size_fields()
        self._compact()
        self._weight_columns()
        self._wire_dirty()
        # Which title is open, kept in the permanent corner of the status bar.
        # The message beside it is transient and the window title belongs to
        # the file; this is the one thing that must stay on screen, because a
        # Curse save and a Pool of Radiance save look alike from outside.
        self._game_label = QLabel("")
        self._game_label.setObjectName("label_game")
        self.statusBar().addPermanentWidget(self._game_label)
        if path:
            self.load(path)
        else:
            self.status("Open a save disk to begin")

    def _toolbar_icons(self) -> None:
        """Icons beside the button text, never instead of it.

        Save and Save As share a glyph on purpose: the icon says the family and
        the label says which member, the same division of labour the class
        icons use in the roster.
        """
        from ui.iconpaint import icon_pixmap
        for name, icon in (("button_open", "folder-open"),
                           ("button_save", "floppy-disk"),
                           ("button_save_as", "floppy-disk"),
                           ("button_preview", "eye")):
            button = self._child(name)
            if button is not None:
                button.setIcon(QIcon(icon_pixmap(icon, TOOLBAR_ICON, MUTED_INK)))

    def _child(self, name: str) -> QWidget | None:
        """A widget by objectName, or None if Designer no longer has one.

        Everything optional on the form is reached this way, so deleting a
        panel in Designer disables the feature rather than crashing the editor.
        """
        return self.findChild(QWidget, name)

    def _connect(self, name: str, slot) -> None:
        button = self._child(name)
        if button is not None:
            button.clicked.connect(lambda _checked=False: slot())

    # -- binding ----------------------------------------------------------

    def _find_field_widgets(self) -> dict[str, QWidget]:
        """Every `field_*` widget on the form, whatever tab it ended up on.

        An unmatched name is a hard error: a typo in Designer should be loud,
        not a field that silently never loads.
        """
        found: dict[str, QWidget] = {}
        known = set(bindings(in_save=True))
        for widget in self.findChildren(QWidget):
            name = field_name(widget.objectName())
            if name is None:
                continue
            if name == "icon":
                found["icon"] = widget
                continue
            if name not in known:
                raise KeyError(
                    f"{widget.objectName()!r} on the form matches no field in "
                    f"goldbox/layout.py")
            found[name] = widget
        return found

    def _fill_combos(self, game: por_games.Game | None = None) -> None:
        """Name the codes for the fields whose encoding is known, per title.

        Refilled on every open, because race and class are not the same list in
        every title -- Silver Blades' human is 6 where Pool of Radiance's is 7 --
        and a stale list would put a wrong name on a real byte. A title whose
        list we do not have leaves the box empty and `_select` shows the number.

        `char_class` and `class_bits` get one box each and are never
        reconciled: they say the same thing two ways, a record is allowed to
        disagree with itself, and forcing them into agreement is where a
        losslessness bug came from once already.
        """
        tables = tables_for(game)
        for name, w in self._widgets.items():
            if isinstance(w, QComboBox) and name in tables:
                w.clear()
                for code, label in sorted(tables[name].items()):
                    w.addItem(f"{code}  {label}", code)
                _size_combo(w)

    def _compact(self) -> None:
        """Squeeze the whitespace out of every form and table on the sheet.

        Done here rather than in the `.ui` so that a box added in Designer is
        compacted too, and so there is one number to change rather than eleven.
        """
        from PyQt6.QtWidgets import QAbstractItemView, QFormLayout, QGroupBox

        for form in self.findChildren(QFormLayout):
            form.setVerticalSpacing(FORM_VERTICAL_SPACING)
            form.setHorizontalSpacing(FORM_HORIZONTAL_SPACING)
            form.setContentsMargins(*FORM_MARGINS)
            # No field on this sheet can use a pixel more than the widest
            # value its bytes can hold, so none of them is allowed to take
            # one. Spare width goes to the roster and to Character Traits,
            # which are the two things on the form that can read it.
            form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        for box in self.findChildren(QGroupBox):
            box.setFlat(True)
            # Character is two form layouts side by side inside a bare
            # container widget, so its own layout holds nothing that draws.
            # Left alone it pays Qt's 9px margins on top of the forms' own,
            # which is 18px of the header's width and height spent on nothing.
            # A bare `QWidget` counts and a `QGroupBox` or a table does not:
            # those have a frame of their own that the margin is there for.
            inner = box.layout()
            if inner is not None and inner.count() and all(
                    inner.itemAt(i).layout() is not None
                    or type(inner.itemAt(i).widget()) is QWidget
                    for i in range(inner.count())):
                inner.setContentsMargins(0, 0, 0, 0)
            # Stop a box widening past its own fields. Left to stretch, the
            # form puts the labels and values at the left and the rest of the
            # box is empty, which is where most of the whitespace came from.
            # `minimumSizeHint` and not `sizeHint`: the latter is computed
            # before the combo boxes have been sized and clipped their text.
            if box.objectName() not in WIDE_BOXES:
                box.setMaximumWidth(max(box.sizeHint().width(),
                                        box.minimumSizeHint().width()))
        # A box narrower than its column would otherwise sit in the middle of
        # it, which trades whitespace on the right for whitespace on both sides.

        for name, floor in LIST_FLOOR.items():
            box = self._child(name)
            if box is not None:
                box.setMinimumHeight(floor)

        # The header does not scroll, so its boxes are the window's floor.
        # `qSmartMinSize` takes an explicit minimum over the hint, so this is
        # the cap being enforced rather than assumed -- without it the floor
        # is whatever the platform's font metrics happen to come to.
        for name, floor in HEADER_FLOOR.items():
            box = self._child(name)
            if box is None:
                continue
            # Never above what the box wants: under a smaller font than this
            # one, a floor of 520 would be a minimum above its own maximum.
            box.setMinimumWidth(min(floor, box.minimumSizeHint().width()))
        for name in TOOLBAR_BUTTONS:
            button = self._child(name)
            if button is not None:
                button.setMinimumWidth(TOOLBAR_BUTTON_MIN_WIDTH)
        self._pin_identity_columns()

        for table in self.findChildren(QAbstractItemView):
            head = getattr(table, "verticalHeader", lambda: None)()
            if head is not None:
                head.setDefaultSectionSize(TABLE_ROW_HEIGHT)
                head.setMinimumSectionSize(TABLE_ROW_HEIGHT)

    def _pin_identity_columns(self) -> None:
        """Hold Character's two columns to what they need, and let the box clip.

        #71: the header is capped at `HEADER_IDENTITY_MIN_WIDTH` so the
        window's floor stops following the UI font, and at a Windows-sized
        font Character wants nearly twice that. A layout given less than the
        sum of its items' minimums does not refuse -- it shrinks them below
        their minimums, in proportion -- so both form columns were squeezed,
        the labels went first because the fields are pinned to their own text,
        and the right column's labels ended up drawn over the left column's
        fields.

        The two columns sit in one bare container instead. `QWidget.setGeometry`
        clamps to the widget's own minimum size, so a container with an
        explicit minimum cannot be squeezed by the layout above it; it
        overflows the group box and Qt clips it at the box's edge. The left
        column stays whole and the right one is cut off, which is a window
        that is too narrow rather than a form drawn on top of itself.

        **Cut off means gone, not shortened**, and that is worth knowing before
        anyone calls this a fix. Measured on `box_identity` at the default font
        plus five points, the right column's labels are sliced to a first
        letter; **at plus eight and plus ten -- roughly a Windows base font --
        `Hp current`, `Sex`, `Age` and `Size` draw zero pixels**, with no
        ellipsis and no scroll bar to say they exist. It is better than a form
        drawn over itself and it is not a form a user can read. The header
        still does not fit 1280 at a Windows font and only the roster giving up
        width closes that -- see issue 71.

        Called again after a save is opened, because `_fill_combos` is what
        gives the race and class drop-downs their real widths -- the six games
        do not share a class table, and a title whose longest name is longer
        than Pool of Radiance's would otherwise be clipped by the ceiling
        `_compact` put on the box before the disk was read.
        """
        columns = self._child("columns_identity")
        if columns is None or columns.layout() is None:
            return
        columns.layout().setContentsMargins(0, 0, 0, 0)
        # Cleared first: `minimumSize` of the layout is computed from the
        # items, but the widget's own explicit minimum from the last call
        # would otherwise be a floor under the answer and could only grow.
        columns.setMinimumWidth(0)
        wanted = columns.layout().minimumSize().width()
        columns.setMinimumWidth(wanted)
        box = self._child("box_identity")
        if box is not None:
            margins = box.layout().contentsMargins()
            # The ceiling is the box's own hint, or what the columns need if
            # that is more -- and it is recomputed rather than only ever
            # raised. `max(box.maximumWidth(), ...)` kept whichever number was
            # largest across every call, which left the box 18px wider than it
            # wants; harmless while nothing in the header could grow into a
            # wider window, and 18px of Character sliding right the moment the
            # roster took the row's stretch (#71).
            box.setMaximumWidth(max(box.sizeHint().width(),
                                    wanted + margins.left() + margins.right()))

    def _weight_columns(self) -> None:
        """Spare width goes where something can use it.

        Above the tabs, Character is sized to the widest value each of its
        fields can hold, so the roster is the one of the two that can read a
        wider window -- its `Name` column stretches. Round six gave the slack
        to Character instead and it came out as the gutter and the gap Donald
        marked.

        On the Stats tab, Character Traits is the only box that can use spare
        width, so it has a column of its own at the right and all of the
        stretch. Sharing it four ways -- round six -- put a gap beside every
        column instead of one 490px hole beside Money.

        The tab is a `QGridLayout` since round nine, so this sets column and
        row stretches rather than item stretches. Nothing here lines two boxes
        up: a grid row has one top edge, which is what Donald asked for and
        what five stacked columns could not give.
        """
        # A layout is not a QWidget, so `_child` cannot find it. `pyuic6`
        # names every layout on the Ui object, which is cheaper and steadier
        # than a `findChild` walk of the whole form.
        grid = getattr(self.ui, "sheet_columns", None)
        if grid is not None:
            # Character Traits spans both rows, so its cell is taller than its
            # ten capped slots. `AlignTop` is it declining the difference
            # rather than centring the table in it -- not alignment holding
            # anything together, which on this tab is the grid's job alone.
            traits = self._child("box_effects")
            if traits is not None:
                grid.setAlignment(traits, Qt.AlignmentFlag.AlignTop)
            for i, stretch in enumerate(STATS_COLUMN_STRETCH):
                grid.setColumnStretch(i, stretch)
            for i, stretch in enumerate(STATS_ROW_STRETCH):
                grid.setRowStretch(i, stretch)

        for name, stretch in ROW_STRETCH.items():
            row = getattr(self.ui, name, None)
            if row is None:
                continue
            for i in range(row.count()):
                row.setStretch(i, stretch[i] if i < len(stretch) else 0)

    def _size_fields(self) -> None:
        """Give every box the width of the widest value its bytes can hold.

        A name is twenty characters, an ability score three digits and a coin
        count five, and `goldbox/layout.py` knows which is which. Nothing here is
        per-field, so a field added to the form later comes out right.
        """
        for name, w in self._widgets.items():
            if isinstance(w, QComboBox):
                _size_combo(w)
                continue
            field = FIELDS_BY_NAME.get(name)
            if field is None:
                continue
            span = value_range(field)
            if isinstance(w, QSpinBox) and span is not None:
                # The range belongs to the bytes too. A u8 box offering 65535
                # invites a value `record.set` would refuse.
                w.setRange(*span)
            if isinstance(w, (QSpinBox, QLineEdit)):
                text = _widest_drawing(w.fontMetrics(), widest_text(field))
                width = (_spin_width(w, text) if isinstance(w, QSpinBox)
                         else _line_width(w, text))
                if name in TRIMMED:
                    width = round(width * TRIMMED[name])
                # A floor as well as a ceiling. With only a maximum the layout
                # is free to squeeze the box below its own text, and a spin box
                # squeezed that far is two arrows and nothing else -- which is
                # exactly what the Windows build showed.
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
            elif hasattr(w, "iconChanged"):
                w.iconChanged.connect(self._edited)
        book, memorised = self._spell_widgets()
        if book is not None and memorised is not None:
            # The spellbook decides which memorised spells are strays, so the
            # colouring has to follow a tick, not just a change of character.
            book.changed.connect(
                lambda: memorised.set_known(book.known()))

    def _spellbook_raw(self, record) -> bytes:
        """The whole mask at 0x078, both declared fields of it.

        `goldbox/layout.py` splits it: `spells_known` is the seven bytes Pool of
        Radiance uses and every writer in the project encodes, and
        `spells_known_high` is the nine the later titles continue into. The
        widget wants one run of bytes and decides for itself how far its title
        reaches into them.
        """
        return b"".join(record.get_raw(f) for f in SPELLBOOK_FIELDS)

    def _set_spellbook_raw(self, record, raw: bytes) -> None:
        """The inverse, writing back only the halves that actually moved.

        A short `raw` writes only the fields it fills, so a widget that was
        never given the high bytes cannot zero them.
        """
        at = 0
        for name in SPELLBOOK_FIELDS:
            size = FIELDS_BY_NAME[name].size
            chunk = raw[at:at + size]
            if len(chunk) == size and chunk != record.get_raw(name):
                record.set_raw(name, chunk)
            at += size

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
            self, "Open a save disk",
            files.open_start_dir(self.last_save_folder, self.path),
            "Gold Box disks (*.d64 *.D64);;All files (*)")
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        try:
            party = Party(path)
        except Exception as exc:
            # The user is told; the log gets the traceback, which is the half a
            # bug report needs and a dialog cannot carry.
            _log.exception("could not open %s", path)
            QMessageBox.critical(self, "Cannot open", str(exc))
            return
        self._adopt(party, path)

    def _adopt(self, party: Party, path: str, note: str | None = None,
               dirty: bool = False) -> None:
        """Show a party that is already built, from wherever it came.

        `load` reads one off a disk; the DOS import converts one in memory and
        has nothing on disk to read it back from. `dirty` marks every row
        changed, which is how an import arrives: on screen, in the title bar,
        and not yet written anywhere.
        """
        self.party, self.path = party, pathlib.Path(path)
        self.dirty = set(range(len(party))) if dirty else set()
        self.current_row = -1
        # Before the first row is selected, and while `current_row` is -1 so
        # that clearing a combo does not read as an edit.
        self._fill_combos(party.game)
        self._load_game_disk()
        self.model.beginResetModel()
        self.model.party = party
        self.model.endResetModel()
        self._size_roster()
        # The race and class drop-downs only get their real widths from
        # `_fill_combos` above, so what Character's columns need is not known
        # until a save is open.
        self._pin_identity_columns()
        if len(party):
            self.ui.roster.selectRow(0)
        self._apply_read_only()
        self._game_label.setText(party.game.title if party.is_save else "")
        self.status(note if note is not None else
                    f"{party.describe()}"
                    + ("" if self.charset else
                       "  -- no game disk, so no item names and no icons"))
        self._retitle()
        self.opened.emit(str(self.path))

    # -- importing --------------------------------------------------------

    def import_dos_save(self, folder: str | None = None) -> str:
        """File > Import > DOS… Returns what happened, for a test.

        Two pickers and a window, and no write: what the conversion costs is
        on screen before the button that commits it exists to press, and what
        it commits is a party in this window that Save has yet to write. The
        editor's own Save is what reaches the disk, so the backup in
        `editor/files.py` covers an import like any other edit.
        """
        from goldbox import dos

        from .dosimport import (
            FOLDER_TITLE,
            NO_SLOTS,
            NO_SLOTS_TITLE,
            DosImportDialog,
        )

        if folder is None:
            folder = QFileDialog.getExistingDirectory(
                self, FOLDER_TITLE,
                str(self.path.parent if self.path else ""))
        if not folder:
            return "cancelled"
        if not dos.slots_available(folder):
            QMessageBox.warning(self, NO_SLOTS_TITLE,
                                NO_SLOTS.format(folder=folder))
            return "no DOS save"
        dialog = DosImportDialog(folder, self.path, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return "cancelled"
        return self.adopt_conversion(dialog.conversion)

    def adopt_conversion(self, conversion) -> str:
        """Show a converted save, unwritten. Separate so a test can call it."""
        from .dosimport import CONVERTED

        if conversion is None:
            return "cancelled"
        note = CONVERTED.format(slot=conversion.slot)
        party = Party(str(conversion.template), game=conversion.game,
                      disk=conversion.disk)
        self._adopt(party, str(conversion.template), note=note, dirty=True)
        return note

    # -- exports ----------------------------------------------------------
    #
    # An import lands in this window and reaches a disk through Save, which is
    # what keeps `editor/files.py`'s backup covering it. An export writes into
    # a folder we do not own, so the guarantee is the other one
    # `editor/exports.py` describes: nothing is written until the pane has
    # named every file the write would replace or remove.

    def export_source(self):
        """The open save as it stands, edits on screen included.

        `_flush` and `_write_back` are exactly what Save does before it writes,
        and they touch no file -- so an export carries the same party the
        window is showing rather than the one last written.
        """
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
            QMessageBox.warning(self, FAILED_TITLE, str(exc))
            return "nothing open"
        dialog = dialog_class(source, destination=destination, parent=self)
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
            QMessageBox.critical(self, FAILED_TITLE, str(exc))
            return "failed"
        self.status(note)
        return note

    def _size_roster(self) -> None:
        """Measure the roster: the height its rows need, and the width they
        would like, which is not the same as the width it can survive on.

        There is no splitter any more. The roster and Character sit above the
        tabs and the sheet scrolls inside whichever tab is showing, because a
        fixed top over a scrolling bottom squeezed the fields into a
        sixty-pixel strip whenever the window was anything short of enormous.

        The width is two numbers since #71 and used to be one. `RosterView` has
        the rest of it and the reasons.
        """
        view = self.ui.roster
        header = view.horizontalHeader()
        # Measured with every column at its contents, and `Name` among them:
        # what the five come to here is the natural width the table asks for
        # and is capped at, and it is read before `Name` is made interactive
        # below, because an interactive section keeps whatever it was last
        # dragged to rather than reporting its text.
        for column in range(self.model.columnCount()):
            header.setSectionResizeMode(column,
                                        header.ResizeMode.ResizeToContents)
        view.resizeColumnsToContents()
        # `header.length()` is what the columns actually came to; the vertical
        # bar's width is reserved whether or not it is up, because a table a
        # few pixels short grows a horizontal bar, which costs a row off the
        # bottom, which brings the vertical bar up as well, which takes another
        # 14px of width.
        #
        # The width is asked of the style rather than of `verticalScrollBar()`:
        # capping a table's size and reaching for its scroll bar in the same
        # breath segfaults PyQt inside a later `findChild`, which the editor
        # work hit once already.
        from PyQt6.QtWidgets import QStyle
        bar = view.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        natural = (header.length() + view.verticalHeader().width()
                   + 2 * view.frameWidth() + bar)
        # **No column stretches.** `Name` used to, and a stretching section
        # takes the whole viewport: on a wide window it drew several times the
        # longest name the game can hold. Capping it did not work either --
        # `QHeaderView` ignores `maximumSectionSize` for a section in `Stretch`
        # mode, reproduced on a bare `QTableView` with none of this in it (#90).
        #
        # It is interactive instead, and `RosterView` sets its width from the
        # width the table was given: its contents when there is room, and the
        # shortfall taken out of it when there is not (#71). The slack above
        # the natural width still leaves the table altogether -- `header_slack`
        # in `character.ui` is a spacer at the **end** of `header_row`, so a
        # wider window grows the empty space to the right of Character and
        # nothing else. It sits after Character rather than between the two
        # boxes: they are one group and should read as one, and a gap that
        # opens down the middle of the header pulls them apart.
        header.setSectionResizeMode(NAME_COLUMN,
                                    header.ResizeMode.Interactive)
        view.measure(natural, header.sectionSize(NAME_COLUMN))
        # The floor is a constant and the ceiling is the contents. This pair
        # used to be one number -- `minimumWidth == maximumWidth == natural` --
        # which is how the roster came to be the last thing in the header whose
        # minimum was a font metric, and so the last thing putting the window's
        # own floor under the UI font (#71, #41).
        view.setMinimumWidth(min(natural, ROSTER_MIN_WIDTH))
        view.setMaximumWidth(natural)
        rows = min(self.model.rowCount(), MAX_ROSTER_ROWS)
        # The horizontal bar's height is reserved whether or not it is up, for
        # the same reason and out of the same metric as the vertical bar's
        # width above: a table pinned to exactly its rows draws the bar *inside*
        # that, so the last character lost most of a row, the table then found
        # it could not show all its rows and brought the vertical bar up too,
        # and that took another 14px of width and made the overflow worse (#92).
        #
        # Reserved unconditionally because whether the bar is up depends on the
        # width the roster is given, and a height that moved with the width
        # would make `WishWindow.minimumSizeHint()` depend on when it was asked
        # -- three tests measure it on an unshown window. The cost is `bar`
        # pixels of empty grid under the last row when no bar is up, which is
        # what `ROSTER_SLACK` already spends six of.
        height = (view.horizontalHeader().height()
                  + sum(view.rowHeight(r) for r in range(rows))
                  + 2 * view.frameWidth() + bar)
        # The table stops at its rows rather than stretching, or a six-character
        # party leaves 300 pixels of empty grid at the top of the window.
        #
        # A floor as well as a ceiling. Selecting a fighter hides the spell
        # box, the column reflows, and a table with only a maximum collapses to
        # the 60-pixel minimum the form gives it -- two rows visible out of six.
        view.setMinimumHeight(height + ROSTER_SLACK)
        view.setMaximumHeight(height + ROSTER_SLACK)


    def _disk_candidates(self) -> list[str]:
        """`--game-disk`, then the Game directory setting, then
        $POR_GAME_DISK, then any game disk of the open title beside the save --
        `POOL*.D64` for Pool of Radiance, `CURSE*.D64` for Curse. Everything
        the save cannot name itself comes from one of these.

        The order is the application's one rule: a command-line option beats
        the setting for one run, the setting beats everything else, and the
        environment variable is left working for the tests and the tools
        without being anybody's interface.
        """
        import glob
        import os
        import pathlib
        pattern = (self.party.game.disk_glob if self.party is not None
                   else por_games.DEFAULT.disk_glob)
        candidates = []
        if self.game_disk:
            candidates.append(self.game_disk)
        if self.disks:
            candidates += sorted(glob.glob(str(pathlib.Path(self.disks)
                                               / pattern)))
        env = os.environ.get("POR_GAME_DISK")
        if env:
            candidates.append(env)
        if self.path:
            candidates += sorted(glob.glob(str(self.path.parent / pattern)))
        # The disks come as a set. Being told POOL1.D64 says where the other
        # seven are, and they are not interchangeable -- the icon charset and
        # the icon option tables live on different ones.
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

    def _find_disk(self, read) -> str | None:
        """The first candidate `read` succeeds on.

        Which disk holds what is not uniform -- the icon charset and the icon
        *option tables* are on different disks -- so each thing we need is
        searched for by trying to read it rather than by assuming a disk number.
        """
        for c in self._disk_candidates():
            try:
                read(c)
            except Exception as exc:
                # A candidate that has not got the thing is the search working.
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
            # Which title this is does not depend on having a disk to read the
            # names off, and the widgets need it either way: without it a
            # Silver Blades spellbook is offered Pool of Radiance's spell list
            # and stops at 55.
            self._apply_spell_table()
            self.traits.set_tables({}, {}, self._spell_table())
            return
        # Item names live at $6F00 on Pool of Radiance and $9E00 on every
        # title after it, so the reader needs to be told which save is open --
        # without it a Curse item comes out as its word index.
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
                # Each table is optional on its own: missing item names cost
                # numbered items, not a window that will not open.
                _log.exception("could not read %s off %s", attr, found)
        # Damage, protection and the class mask are in the ITEMS type table,
        # not in the item record, so the traits table needs the game disk too.
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
        """Where a copy of the save goes before it is overwritten.

        Empty is not "somewhere sensible": it is a window that cannot save,
        and `files.save_disk` says so rather than writing anyway.
        """
        self.backups = folder

    def set_disks(self, disks: str | None) -> None:
        """The Game directory changed. Re-read, and redraw what it feeds.

        Item names, the icon charset, the icon option tables and the traits
        table all come off a game disk, so the open character has to be drawn
        again -- otherwise the preference appears to have done nothing until
        the next time a row is clicked.
        """
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
        """The icon editor's option tables, from whichever disk carries them.

        `SPELLE64` and `SPELLN64` are on the character-creation disk only, which
        is usually not the one the charset came from. Missing them costs the
        ability to *change* an icon, not to draw one.
        """
        self.icon_parts = None
        self.icon_parts_disk = None
        disk = self._find_disk(IconParts.load)
        if disk is None:
            return
        try:
            self.icon_parts = IconParts.load(disk)
        except Exception:
            # `_find_disk` already loaded these off this disk, so a failure
            # here is surprising and worth the traceback.
            _log.exception("could not read the icon parts off %s", disk)
            self.icon_parts = None
        else:
            self.icon_parts_disk = disk

    def save(self, interactive: bool = True) -> str:
        """Write the disk back. Returns what happened, for the status bar.

        `interactive=False` lets a test drive this without a modal dialog
        blocking forever on failure.
        """
        if self.party is None or self.path is None:
            return "nothing open"
        self._flush()
        try:
            self._write_back()
            note = files.save_disk(self.party.disk, self.path, self.backup_dir())
        except Exception as exc:
            _log.exception("could not save %s", self.path)
            if interactive:
                QMessageBox.critical(self, "Cannot save", str(exc))
                return "failed"
            raise
        self.dirty.clear()
        self.status(note)
        self._retitle()
        return note

    def backup_dir(self) -> str | pathlib.Path:
        """The folder this window would back a save up into.

        Beside the save when nobody is managing the setting; whatever was
        handed in otherwise, empty included -- see `__init__`.
        """
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
        """Show that report in a window that does not block anything.

        Non-modal on purpose, and separate from Save on purpose: an editor that
        interrogates you every time you press Ctrl+S is an editor you stop
        pressing Ctrl+S in.
        """
        text = self.preview_text()
        if self._preview is None:
            self._preview = QDialog(self)
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
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the disk as", str(self.path or ""),
            "Gold Box disks (*.d64 *.D64);;All files (*)")
        if not path:
            return
        self.path = pathlib.Path(path)
        # Before the write, so an automatic backup folder is already following
        # the new location by the time the copy is taken.
        self.opened.emit(str(self.path))
        self.save()

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
        if previous.isValid():
            self._flush(previous.row())
        self.current_row = current.row() if current.isValid() else -1
        self._populate()

    def _flush(self, row: int | None = None) -> None:
        """Copy what is on screen into the record, before we leave it.

        Without this an edit made and not tabbed out of vanishes when you click
        another character, which is the easiest bug in an editor like this to
        ship by accident.
        """
        row = self.current_row if row is None else row
        if self.party is None or not 0 <= row < len(self.party):
            return
        record = self.party.member(row).record
        icon_widget = self._widgets.get("icon")
        if icon_widget is not None and icon_widget.icon is not None:
            self.party.member(row).icon = icon_widget.icon
        for name, w in self._widgets.items():
            if name == "icon" or not w.isEnabled():
                continue
            # Write only what actually changed. Assigning a field its own value
            # is not always a no-op: `name` is a 20-byte NUL-padded field, and
            # re-setting it re-pads, wiping residue from a longer previous name.
            # That residue is meaningless to the game and byte-visible to us, and
            # an editor that rewrites the file it opened must not touch it.
            try:
                if isinstance(w, QSpinBox):
                    if record.get(name) != w.value():
                        record.set(name, w.value())
                elif isinstance(w, QLineEdit) and name == "name":
                    if record.name != w.text():
                        record.name = w.text()
                elif isinstance(w, QComboBox):
                    if record.get(name) != w.currentData():
                        record.set(name, w.currentData())
                elif isinstance(w, SpellbookEditor):
                    self._set_spellbook_raw(record, w.to_bytes())
                elif isinstance(w, SpellEditor):
                    if record.get_raw(name) != w.to_bytes():
                        record.set_raw(name, w.to_bytes())
            except Exception:
                # A field that will not take the value is one field, not the
                # whole flush -- but it is an edit the user made and did not
                # get, so it is logged with its traceback rather than dropped.
                _log.exception("could not flush %s", name)
        self.party.member(row).name = record.name

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
                # A field this title does not store, most often. The box shows
                # its empty value rather than the form failing to fill.
                _log.debug("no %s on this record: %s", name, exc)
                value = None
            if isinstance(w, QSpinBox):
                w.setValue(int(value) if isinstance(value, int) else 0)
            elif isinstance(w, QLineEdit):
                if name == "name":
                    w.setText(record.name)
                elif isinstance(value, (bytes, bytearray)):
                    # A field we hold as raw bytes. Hex is the honest showing;
                    # a Python repr -- b'V\x00\x00' for 86 XP -- is not.
                    w.setText(value.hex(" "))
                else:
                    w.setText(str(value or ""))
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(value))
            elif isinstance(w, QComboBox):
                _select(w, value)
            elif hasattr(w, "set_bytes"):
                w.set_bytes(self._spellbook_raw(record)
                            if isinstance(w, SpellbookEditor)
                            else record.get_raw(name))
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
            # Record 0x099 bit 0 picks which pair of option tables the icon
            # editor offers -- SPELLN64 $AF24 reads it and never writes it back.
            size = "large" if (member.record.get("size_small") or 0) & 1 else "small"
            icon_widget.set_parts(getattr(self, "icon_parts", None), size)
            icon_widget.setMaximumWidth(ICON_MAX_WIDTH)
        self._loading = False

    def _show_boxes(self, record) -> None:
        """Grey the boxes this character has no use for. Hide none of them.

        Every box is on the sheet for every character, so nothing below one
        moves when the selection does. A box the class cannot use is disabled
        -- which also keeps `_flush` off it, so a fighter's spell bytes go
        back exactly as they were read -- and says why in its tooltip.

        A box that Designer no longer has is simply not there -- the same rule
        as every other optional widget on the form.

        Which classes a box applies to is the **open title's** answer: a
        ranger casts and Pool of Radiance has no ranger (#86).
        """
        try:
            bits = int(record.get("class_bits") or 0)
        except Exception as exc:
            # No class bits greys every class-gated box, which is the safe way
            # round: a box `_flush` cannot reach cannot corrupt a record.
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
            rule = rules.get(name)
            if rule is None:
                continue
            # A QLineEdit that is not the name is showing a RAW field as hex.
            # `_flush` cannot write those back, so leaving it enabled would let
            # someone type into a box that silently discards what they typed --
            # which is exactly what `experience` did before it became a real
            # 24-bit integer field.
            passthrough = isinstance(w, QLineEdit) and name != "name"
            w.setEnabled(not rule.read_only and not passthrough)
            if passthrough and not rule.read_only:
                w.setToolTip(f"{name} is preserved verbatim; the editor cannot "
                             f"write it")
                continue
            w.setToolTip(rule.reason if rule.read_only
                         else f"{rule.field.name} @ {rule.field.offset:#05x} "
                              f"({rule.field.confidence.value})")
            label = self.findChild(QLabel, f"label_{name}")
            if label is not None:
                label.setEnabled(not rule.read_only)

    def _describe_spells(self, record) -> None:
        """Show what the spellbook holds and how much the class may memorise.

        Reported, never enforced: the same two rules the CLI declines to police.
        """
        book, memorised = self._spell_widgets()
        if memorised is None:
            return
        if book is not None:
            memorised.set_known(book.known())
        game = self.party.game if self.party is not None else None
        # The same mask that greys the box, so the line under the list and the
        # box itself cannot disagree about whether this character casts (#86).
        memorised.set_capacity(
            capacity(record.class_bits, record.get("level"),
                     record.get("wisdom"), game),
            casts=bool(record.class_bits & caster_bits(game)))

    # -- items ------------------------------------------------------------

    def _size_item_columns(self) -> None:
        """The item column, as wide as the longest name and no wider.

        It used to stretch to whatever the window had left, which on a wide
        screen was several times the widest of the 163 names the game disks
        carry. With a game disk open the number comes from those names; without
        one it comes from `docs/87-item-templates.md`, which lists them all.
        """
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
        """Fill the traits table from whichever item is selected.

        Returns what the caption says, which is what a test can assert on.
        """
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
        label = self.findChild(QLabel, "label_traits")
        if label is not None:
            label.setText(text)
        return text

    def _describe_inventory(self, member) -> str:
        """The line above the table. Says why names are numbers, when they are.

        A save opened without a game disk shows item words as indices, and that
        must not look like a bug.
        """
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
        label = self.findChild(QLabel, "label_inventory")
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
        """Copy one of the game's own item records into a free slot.

        `name` skips the dialog, which is what a test wants -- a modal dialog
        in a headless run waits for a click that never comes.
        """
        if self.items.inventory is None:
            return "no inventory here"
        if not self.templates:
            return "no game disk, so no items to copy"
        if name is None:
            dialog = AddItemDialog(self.templates, self)
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
        self.statusBar().showMessage(text)

    def _retitle(self) -> None:
        name = self.path.name if self.path else "no file"
        mark = " *" if self.dirty else ""
        # "Wish" capitalised: the product name in prose and in a title
        # bar, as against the command `wish`, which stays lower case.
        self.setWindowTitle(f"Wish - {name}{mark}")

    def showEvent(self, event) -> None:
        """Size the roster once the window has a height to divide.

        A table asked for its row heights before it has been shown gives the
        load time -- before the window is on screen -- left the roster its old
        quarter of the window. Once only: after that the divider is the user's.
        """
        super().showEvent(event)
        if not self._sized:
            self._sized = True
            self._size_roster()

    def closeEvent(self, event) -> None:
        if self.dirty:
            answer = QMessageBox.question(
                self, "Unsaved changes",
                "Save before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Save:
                self.save()
        super().closeEvent(event)
