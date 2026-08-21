"""The main window: the roster across the top, the character sheet below it.

The form comes from `editor/character.ui`. Widgets are found by `objectName`
and matched to `por/layout.py` fields, so the form can be rearranged in Qt
Designer -- fields moved between group boxes, regrouped, relabelled -- without
a line of this file changing.
"""

from __future__ import annotations

import pathlib

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
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

from por.iconparts import IconParts
from por.icons import load_icon_charset
from por.items import load_item_names, load_item_templates, load_item_types
from por.layout import FIELDS_BY_NAME
from por.spells import capacity, load_spell_names

from . import changes, files, inventory
from .binding import bindings, field_name, value_range, widest_text
from .enums import TABLES
from .inventory import AddItemDialog, InventoryModel, ItemTraitsModel
from .roster import Party
from .spellwidget import MemorisedEditor, SpellbookEditor, SpellEditor


def _size_combo(combo: QComboBox) -> None:
    """As wide as its longest name, and no wider.

    Re-applied whenever an item is added, because `_select` adds one for a code
    the game's table does not name and an elided box would hide the number.
    """
    combo.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow)
    widest = max((combo.fontMetrics().horizontalAdvance(combo.itemText(i))
                  for i in range(combo.count())), default=0)
    # A floor as well as a ceiling. With only a maximum, a box capped to its
    # own size hint squeezed the combo below its text and `magic-user/thief`
    # came out as `magic-user`.
    combo.setMinimumWidth(widest + COMBO_CHROME)
    combo.setMaximumWidth(widest + COMBO_CHROME)


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

NAME_COLUMN = 0
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
WIDE_BOXES = ("box_inventory", "box_traits", "box_effects")
# Left to right: roster and character, the icon and the ability forms, then the
# two columns carrying tables, which are the ones that benefit from width.
COLUMN_STRETCH = (0, 0, 5, 2)
ROSTER_SLACK = 6
ICON_MAX_WIDTH = 300
SPELLS_MAX_WIDTH = 520
STRIP_TABLE_HEIGHT = 150
# Eight is every slot a save disk has and every character a roster disk holds,
# so a roster sized to this never scrolls and never leaves a fifth of the
# window empty.
MAX_ROSTER_ROWS = 8

# Room for the frame and, on a spin box, the two arrows. Measured from the
# style rather than guessed would be better; these are the widths Fusion and
# Breeze both need, and a few pixels spare costs nothing.
SPINBOX_CHROME = 36
LINE_CHROME = 14
COMBO_CHROME = 30

# Cell margins either side of an item name.
ITEM_NAME_PADDING = 16


def _content_height(view) -> int:
    """How tall a table has to be to show every row it has."""
    rows = view.model().rowCount() if view.model() is not None else 0
    return (view.horizontalHeader().height()
            + sum(view.rowHeight(r) for r in range(rows))
            + 2 * view.frameWidth())


def _fit_height(view) -> None:
    """Show every row rather than scrolling. Ten effects and a dozen traits
    are short lists, and a scrollbar over four visible rows hides most of a
    list whose whole point is that you can see it."""
    view.setMinimumHeight(_content_height(view))

# Which class bits a group box needs before it is worth showing. A fighter
# shown eight thief-skill zeros invites somebody to type in them, and a page of
# zeros reads as data when it is really "does not apply". Keyed by objectName
# like everything else on the form, so the boxes can be moved in Designer.
CLASS_MAGIC_USER, CLASS_CLERIC, CLASS_THIEF = 1, 2, 4
BOX_NEEDS_CLASS = {
    "box_thief_skills": CLASS_THIEF,
    "box_spells": CLASS_MAGIC_USER | CLASS_CLERIC,
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
    def __init__(self, path: str | None = None, game_disk: str | None = None):
        super().__init__()
        from .ui_character import Ui_CharacterWindow
        self.ui = Ui_CharacterWindow()
        self.ui.setupUi(self)

        self.party: Party | None = None
        self.path: pathlib.Path | None = None
        self.game_disk = game_disk
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
                    f"por/layout.py")
            found[name] = widget
        return found

    def _fill_combos(self) -> None:
        """Name the codes for the fields whose encoding is known.

        `char_class` and `class_bits` get one box each and are never
        reconciled: they say the same thing two ways, a record is allowed to
        disagree with itself, and forcing them into agreement is where a
        losslessness bug came from once already.
        """
        for name, w in self._widgets.items():
            if isinstance(w, QComboBox) and name in TABLES:
                for code, label in sorted(TABLES[name].items()):
                    w.addItem(f"{code}  {label}", code)

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
        for box in self.findChildren(QGroupBox):
            box.setFlat(True)
            # Stop a box widening past its own fields. Left to stretch, the
            # form puts the labels and values at the left and the rest of the
            # box is empty, which is where most of the whitespace came from.
            # `minimumSizeHint` and not `sizeHint`: the latter is computed
            # before the combo boxes have been sized and clipped their text.
            if box.objectName() == "box_spells":
                # Three lists side by side ask for 690 pixels, which starves
                # the inventory table beside it into a horizontal scroll bar.
                box.setMaximumWidth(SPELLS_MAX_WIDTH)
            elif box.objectName() not in WIDE_BOXES:
                box.setMaximumWidth(max(box.sizeHint().width(),
                                        box.minimumSizeHint().width()))
        # A box narrower than its column would otherwise sit in the middle of
        # it, which trades whitespace on the right for whitespace on both sides.

        for table in self.findChildren(QAbstractItemView):
            head = getattr(table, "verticalHeader", lambda: None)()
            if head is not None:
                head.setDefaultSectionSize(TABLE_ROW_HEIGHT)
                head.setMinimumSectionSize(TABLE_ROW_HEIGHT)

    def _weight_columns(self) -> None:
        """Spare width goes to the columns holding tables.

        The field columns are capped to their contents and cannot use it; the
        inventory, the traits and the spell lists can always take more.
        """
        # A layout is not a QWidget, so `_child` cannot find it.
        from PyQt6.QtWidgets import QHBoxLayout
        columns = self.findChild(QHBoxLayout, "sheet_columns")
        if columns is None:
            return
        for i in range(columns.count()):
            columns.setStretch(i, COLUMN_STRETCH[i] if i < len(COLUMN_STRETCH)
                               else 0)

    def _size_fields(self) -> None:
        """Give every box the width of the widest value its bytes can hold.

        A name is twenty characters, an ability score three digits and a coin
        count five, and `por/layout.py` knows which is which. Nothing here is
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
                chrome = SPINBOX_CHROME if isinstance(w, QSpinBox) else LINE_CHROME
                w.setMaximumWidth(
                    w.fontMetrics().horizontalAdvance(widest_text(field)) + chrome)

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
            self, "Open a save disk", str(self.path.parent if self.path else ""),
            "Pool of Radiance disks (*.d64 *.D64);;All files (*)")
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        try:
            party = Party(path)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot open", str(exc))
            return
        self.party, self.path = party, pathlib.Path(path)
        self.dirty.clear()
        self.current_row = -1
        self._load_game_disk()
        self.model.beginResetModel()
        self.model.party = party
        self.model.endResetModel()
        self._size_roster()
        if len(party):
            self.ui.roster.selectRow(0)
        self._apply_read_only()
        self.status(f"{party.describe()}"
                    + ("" if self.charset else
                       "  -- no game disk, so no item names and no icons"))
        self._retitle()

    def _size_roster(self) -> None:
        """Give the roster exactly the width and height its rows need.

        There is no splitter any more. The roster, the icon and the sheet are
        all one scrolling page, because a fixed top over a scrolling bottom
        squeezed the fields into a sixty-pixel strip whenever the window was
        anything short of enormous.
        """
        view = self.ui.roster
        view.resizeColumnsToContents()
        # Name absorbs the slack. Sized to contents alone the five columns come
        # to about a third of the window and the rest of the strip is empty,
        # which is most of what "the table takes the whole top" was about.
        header = view.horizontalHeader()
        for column in range(self.model.columnCount()):
            header.setSectionResizeMode(column,
                                        header.ResizeMode.ResizeToContents)
        # No width cap: the table lives in a column now, and the column
        # already constrains it. Capping as well produced a horizontal scroll
        # bar inside the table, which then ate a row off the bottom.
        rows = min(self.model.rowCount(), MAX_ROSTER_ROWS)
        height = (view.horizontalHeader().height()
                  + sum(view.rowHeight(r) for r in range(rows))
                  + 2 * view.frameWidth())
        # The table stops at its rows rather than stretching, or a six-character
        # party leaves 300 pixels of empty grid at the top of the window.
        #
        # Height only, and no scroll-bar accessor. Capping a table's size and
        # reaching for its scroll bar in the same breath segfaults PyQt inside a
        # later `findChild` -- the editor work hit this once already with
        # `setMaximumWidth`, and it reproduces about two runs in three.
        # A floor as well as a ceiling. Selecting a fighter hides the spell
        # box, the column reflows, and a table with only a maximum collapses to
        # the 60-pixel minimum the form gives it -- two rows visible out of six.
        view.setMinimumHeight(height + ROSTER_SLACK)
        view.setMaximumHeight(height + ROSTER_SLACK)


    def _disk_candidates(self) -> list[str]:
        """`--game-disk`, then $POR_GAME_DISK, then any POOL*.D64 beside the
        save. Everything the save cannot name itself comes from one of these."""
        import glob
        import os
        import pathlib
        candidates = []
        if self.game_disk:
            candidates.append(self.game_disk)
        env = os.environ.get("POR_GAME_DISK")
        if env:
            candidates.append(env)
        if self.path:
            candidates += sorted(glob.glob(str(self.path.parent / "POOL*.[dD]64")))
        # The disks come as a set. Being told POOL1.D64 says where the other
        # seven are, and they are not interchangeable -- the icon charset and
        # the icon option tables live on different ones.
        for named in (self.game_disk, os.environ.get("POR_GAME_DISK")):
            if named:
                beside = pathlib.Path(named).parent
                candidates += sorted(glob.glob(str(beside / "POOL*.[dD]64")))
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
            except Exception:
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
        if found is None:
            self.traits.set_tables({}, {})
            return
        for attr, read in (("charset", load_icon_charset),
                           ("item_names", load_item_names),
                           ("templates", load_item_templates),
                           ("item_types", load_item_types),
                           ("spell_names", load_spell_names)):
            try:
                setattr(self, attr, read(found))
            except Exception:
                pass
        # Damage, protection and the class mask are in the ITEMS type table,
        # not in the item record, so the traits table needs the game disk too.
        self.traits.set_tables(self.item_types, self.spell_names)
        for member in (self.party.members if self.party else []):
            if member.inventory is not None:
                member.inventory.names = self.item_names
        for w in self._widgets.values():
            if isinstance(w, SpellEditor):
                w.set_names(self.spell_names)

    def _load_icon_parts(self) -> None:
        """The icon editor's option tables, from whichever disk carries them.

        `SPELLE64` and `SPELLN64` are on the character-creation disk only, which
        is usually not the one the charset came from. Missing them costs the
        ability to *change* an icon, not to draw one.
        """
        self.icon_parts = None
        disk = self._find_disk(IconParts.load)
        if disk is None:
            return
        try:
            self.icon_parts = IconParts.load(disk)
        except Exception:
            self.icon_parts = None

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
            note = files.save_disk(self.party.disk, self.path)
        except Exception as exc:
            if interactive:
                QMessageBox.critical(self, "Cannot save", str(exc))
                return "failed"
            raise
        self.dirty.clear()
        self.status(note)
        self._retitle()
        return note

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
            "Pool of Radiance disks (*.d64 *.D64);;All files (*)")
        if not path:
            return
        self.path = pathlib.Path(path)
        self.save()

    def _write_back(self) -> None:
        """Push edited records into the disk image."""
        party = self.party
        if party.save0 is not None:
            for m in party.members:
                party.save0.write_record(m.index, m.record)
            party.write_items()
            party.write_icons()
            party.disk.write_file_inplace(b"SAVEDGAME0", party.save0.to_prg())
            if party.save1 is not None:
                party.disk.write_file_inplace(b"SAVEDGAME1", party.save1.to_prg())
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
                elif isinstance(w, SpellEditor):
                    if record.get_raw(name) != w.to_bytes():
                        record.set_raw(name, w.to_bytes())
            except Exception:
                pass
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
            except Exception:
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
                w.set_bytes(record.get_raw(name))
                if hasattr(w, "codes"):
                    _fit_height(w)
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
        """Hide the boxes this character has no use for.

        A box that Designer no longer has is simply not there -- the same rule
        as every other optional widget on the form.
        """
        try:
            bits = int(record.get("class_bits") or 0)
        except Exception:
            bits = 0
        for name, needed in BOX_NEEDS_CLASS.items():
            box = self._child(name)
            if box is not None:
                box.setVisible(bool(bits & needed))

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
        memorised.set_capacity(capacity(record.class_bits, record.get("level"),
                                        record.get("wisdom")))

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
            text = ("Items live in SAVEDGAME0, so this file has none -- a "
                    "roster disk and a .chr export both carry the character "
                    "only")
        elif not self.item_names:
            text = (f"{member.inventory.used} of 16 slots used. No game disk "
                    f"found, so items show as name-table indices: pass "
                    f"--game-disk, set $POR_GAME_DISK, or put a POOL*.D64 "
                    f"beside the save")
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
                           "163 records; without a game disk there are none")
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
        self.setWindowTitle(f"wish - {name}{mark}")

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
