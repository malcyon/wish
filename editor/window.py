"""Binds editor fields to goldbox record data. Works on any widget tree.

Widgets are found by `objectName` and matched to `goldbox/layout.py` fields,
so the form can be rearranged in Qt Designer -- fields moved between group
boxes, regrouped, relabelled -- without a line of this file changing.
"""

from __future__ import annotations

import logging
import pathlib

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
ICON_MAX_WIDTH = 300
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
LIST_FLOOR = {"box_inventory": 240, "box_traits": 240}
#: What Character may be squeezed to.
HEADER_IDENTITY_MIN_WIDTH = 480
#: Which header boxes are held to a constant, and to what. Keyed by
#: objectName like everything else on the form.
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
                 backups: str | None = None, last_save_folder: str = ""):
        super().__init__(root)
        self.root = root
        self.party: Party | None = None
        self.path: pathlib.Path | None = None
        self.game_disk = game_disk
        self.disks = disks
        self.backups = backups
        self.last_save_folder = last_save_folder
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
        self._fill_combos()
        self._size_fields()
        self._compact()
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
        for name, icon in (("button_open", "folder-open"),
                           ("button_save", "floppy-disk"),
                           ("button_save_as", "floppy-disk"),
                           ("button_preview", "eye")):
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

    def _fill_combos(self, game: por_games.Game | None = None) -> None:
        """Name the codes for the fields whose encoding is known, per title."""
        tables = tables_for(game)
        for name, w in self._widgets.items():
            if isinstance(w, QComboBox) and name in tables:
                w.clear()
                for code, label in sorted(tables[name].items()):
                    w.addItem(f"{code}  {label}", code)
                _size_combo(w)

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

        for name, floor in HEADER_FLOOR.items():
            box = self._child(name)
            if box is None:
                continue
            box.setMinimumWidth(min(floor, box.minimumSizeHint().width()))
        for name in TOOLBAR_BUTTONS:
            button = self._child(name)
            if button is not None:
                button.setMinimumWidth(TOOLBAR_BUTTON_MIN_WIDTH)
        self._pin_identity_columns()

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
            files.open_start_dir(self.last_save_folder, self.path),
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
        """The icon and `ANIMATE00` a conversion needs, or None (#118)."""
        from goldbox import dos
        from goldbox.d64 import load_payload

        from .dosimport import GameFiles

        def read_animate(disk):
            return load_payload(disk, dos.ANIMATE_FILE)

        icon_disk = self._find_disk(IconParts.load)
        animate_disk = self._find_disk(read_animate)
        if icon_disk is None or animate_disk is None:
            return None
        try:
            return GameFiles(icon=IconParts.load(icon_disk).default_icon(),
                             animate=read_animate(animate_disk))
        except Exception:
            _log.exception("could not read the import's game files off "
                           "%s and %s", icon_disk, animate_disk)
            return None

    def import_dos_save(self, folder: str | None = None) -> str:
        """File > Import > DOS Save Folder… Returns what happened, for a test."""
        from goldbox import dos

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
        if not dos.slots_available(folder):
            QMessageBox.warning(self.root, NO_SLOTS_TITLE,
                                NO_SLOTS.format(folder=folder))
            return "no DOS save"
        dialog = DosImportDialog(
            folder, game_files, self.root,
            start_dir=files.open_start_dir(self.last_save_folder, self.path))
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
        view.setMinimumWidth(min(natural, ROSTER_MIN_WIDTH))
        view.setMaximumWidth(natural)
        rows = min(self.model.rowCount(), MAX_ROSTER_ROWS)
        height = (view.horizontalHeader().height()
                  + sum(view.rowHeight(r) for r in range(rows))
                  + 2 * view.frameWidth() + bar)
        view.setMinimumHeight(height + ROSTER_SLACK)
        view.setMaximumHeight(height + ROSTER_SLACK)

    def _disk_candidates(self) -> list[str]:
        """`--game-disk`, then the Game directory setting, then
        $POR_GAME_DISK, then any game disk of the open title beside the save.
        """
        import glob
        import os
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
        """The first candidate `read` succeeds on."""
        for c in self._disk_candidates():
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
        """Write the disk back. Returns what happened, for the status bar."""
        if self.party is None or self.path is None:
            return "nothing open"
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
        path, _ = QFileDialog.getSaveFileName(
            self.root, SAVE_AS_TITLE, str(self.path or ""), DISK_FILTER)
        if not path:
            return
        self.path = pathlib.Path(path)
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
            if isinstance(w, QSpinBox):
                w.setValue(int(value) if isinstance(value, int) else 0)
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
            size = "large" if (member.record.get("size_small") or 0) & 1 else "small"
            icon_widget.set_parts(getattr(self, "icon_parts", None), size)
            icon_widget.setMaximumWidth(ICON_MAX_WIDTH)
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
                    w.setToolTip(f"{name} is preserved verbatim; the editor cannot "
                                 f"write it")
                continue
            if hasattr(w, "setToolTip"):
                w.setToolTip(rule.reason if rule.read_only
                             else f"{rule.field.name} @ {rule.field.offset:#05x} "
                                  f"({rule.field.confidence.value})")
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
        """Called when the window is closing to confirm discarding changes."""
        from PyQt6.QtWidgets import QMessageBox
        if bool(self.dirty):
            # If root has it, but it might not. We should probably track modified explicitly
            pass # We'll just rely on what is accessible.

        # wait, self.root is a QWidget not necessarily a QMainWindow, but let's check
        # actually, how did EditorWindow track dirty?
        # self.isWindowModified() is a QWidget property!
        if bool(self.dirty):
            ans = QMessageBox.question(
                self.root, "Unsaved changes",
                "You have unsaved changes. Discard them?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
            )
            if ans != QMessageBox.StandardButton.Discard:
                return False
        return True
