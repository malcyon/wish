"""Spells by name: the spellbook a character knows, and what is memorised.

Two record fields, two shapes, one widget each. Both are promoted in Qt
Designer (`editor.spellwidget`) and both bind by `objectName` like everything
else -- `field_spells_known` at `0x078` and `field_spells_memorised` at
`0x020`.

Both speak the same three methods, `set_names`, `set_bytes` and `to_bytes`, so
the window handles them generically and never has to know which is which.

**Neither consistency rule is enforced.** A memorised spell ought to be one the
character knows, and the count at each level ought to fit what class, level and
Wisdom allow. The CLI reports both and refuses neither, because the point of an
editor is to be able to try what the game has not been shown. So the capacity
sits beside the list and an unknown spell is coloured, and the edit goes
through either way.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyleOptionComboBox,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from por.spells import SpellTable, describe, for_game, spell_group

MEMORISED_SIZE = 16          # the packed list at 0x020

UNKNOWN = QColor("#b03a2e")  # memorised but not in the spellbook

#: What a widget shows before a save is open. Every title's own table arrives
#: with `set_names`, which the window calls as soon as it knows which game this
#: is -- with or without a game disk to read the names off.
DEFAULT_TABLE = for_game(None)

# The Spells box is shown for every character, caster or not, because the
# sheet's boxes may not come and go as the roster moves. So the box has to say
# why it is empty; an empty disabled box with no explanation reads as broken.
NO_SPELLS = "This character casts no spells."


def _spell_text(sid: int, names: dict[int, str] | None,
                table: SpellTable) -> str:
    return describe(sid, names or {}, table)


def fit_to_names(view: QListWidget, texts, checkable: bool) -> None:
    """Make `view` at least as wide as the longest line it can ever show.

    Measured off this style and this font, never written down. Both lists sat
    in a box capped at 520 px and the spellbook came out 70 px wide -- Donald:
    "the spells are not visible in the table because it's so small" -- and a
    pixel count that fixed that here would be wrong on another font, another
    DPI, or the Windows build, where this class of bug keeps being found.

    Three things beyond the text count. The tick box, which only the spellbook
    has; the frame; and the vertical scroll bar, which is included whether it
    is showing or not, because fifty-six spells always overflow and a list
    sized without it loses the last characters the moment it does.

    `texts` is every name the list can hold, not the names in it now: the
    memorised list is usually empty and must still be wide enough for whatever
    is added to it.
    """
    metrics = view.fontMetrics()
    widest = max(texts, key=metrics.horizontalAdvance, default="")
    option = QStyleOptionViewItem()
    option.initFrom(view)
    option.font = view.font()
    option.fontMetrics = metrics
    option.text = widest
    option.features |= QStyleOptionViewItem.ViewItemFeature.HasDisplay
    if checkable:
        option.features |= (
            QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator)
    style = view.style()
    row = style.sizeFromContents(QStyle.ContentsType.CT_ItemViewItem,
                                 option, QSize(), view).width()
    bar = style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None, view)
    view.setMinimumWidth(row + bar + 2 * view.frameWidth())


def _ordered(table: SpellTable) -> list[tuple[str, int, list[int]]]:
    """Every spell id of one title, grouped the way its own table runs.

    The last group is the leftovers -- RESTORATION is a real Pool of Radiance
    spell id that belongs to no class list -- because a spellbook widget that
    cannot show a bit is a spellbook widget that will one day silently clear
    it. Ids the title's name table calls something other than a spell (a combat
    message, an unused slot) are left out: they have no name to show and no
    class to file them under.
    """
    out = []
    seen = set()
    for low, high, cls, level in table.groups:
        ids = [i for i in range(low, high + 1) if i not in table.not_a_spell]
        if not ids:
            continue
        seen.update(ids)
        out.append((cls, level, ids))
    rest = [i for i in range(1, table.last_spell + 1)
            if i not in seen and i not in table.not_a_spell]
    if rest:
        out.append(("no class list", 0, rest))
    return out


def fit_to_choices(combo: QComboBox) -> None:
    """Make `combo` at least as wide as the longest name it offers.

    Same rule as `fit_to_names`, asked of the style rather than counted in
    pixels: the frame and the arrow are whatever this platform draws them as.
    """
    metrics = combo.fontMetrics()
    widest = max((metrics.horizontalAdvance(combo.itemText(i))
                  for i in range(combo.count())), default=0)
    option = QStyleOptionComboBox()
    option.initFrom(combo)
    option.frame = combo.hasFrame()
    option.editable = combo.isEditable()
    size = combo.style().sizeFromContents(
        QStyle.ContentsType.CT_ComboBox, option,
        QSize(widest, combo.sizeHint().height()), combo)
    combo.setMinimumWidth(size.width())


class SpellEditor(QWidget):
    """What the window expects of anything editing a spell field."""

    changed = pyqtSignal()

    def set_names(self, names: dict[int, str] | None,
                  table: SpellTable | None = None) -> None:
        raise NotImplementedError

    def set_bytes(self, raw: bytes) -> None:
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        raise NotImplementedError


class SpellbookEditor(SpellEditor):
    """The bitmask at 0x078, as one named tick box per spell the title has.

    Fifty-five of them on Pool of Radiance, a hundred on Curse, a hundred and
    seventeen on Silver Blades -- `SpellTable.last_spellbook_spell` is the
    ceiling, and it is the lower of what the mask has bits for and what the
    title has spells for.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._names: dict[int, str] | None = None
        self._table = DEFAULT_TABLE
        self._loading = False
        self._raw = bytes(self._table.spellbook_size)
        self.list = QListWidget(self)
        self.list.itemChanged.connect(self._ticked)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list)
        self._rows: dict[int, QListWidgetItem] = {}
        self._fill()

    def _fill(self) -> None:
        self._loading = True
        self.list.clear()
        self._rows.clear()
        for cls, level, ids in _ordered(self._table):
            ids = [i for i in ids if self._table.in_spellbook(i)]
            if not ids:
                continue
            head = QListWidgetItem(f"— {cls} {level} —" if level
                                   else f"— {cls} —")
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(head)
            for sid in ids:
                row = QListWidgetItem(
                    _spell_text(sid, self._names, self._table))
                row.setFlags(Qt.ItemFlag.ItemIsEnabled
                             | Qt.ItemFlag.ItemIsUserCheckable)
                row.setCheckState(Qt.CheckState.Unchecked)
                row.setData(Qt.ItemDataRole.UserRole, sid)
                self.list.addItem(row)
                self._rows[sid] = row
        self._loading = False
        fit_to_names(self.list,
                     [self.list.item(i).text()
                      for i in range(self.list.count())], checkable=True)

    # -- the protocol -----------------------------------------------------

    def set_names(self, names: dict[int, str] | None,
                  table: SpellTable | None = None) -> None:
        self._names = names
        if table is not None:
            self._table = table
        known = self.known()
        self._fill()
        self.set_ids(known)

    def set_bytes(self, raw: bytes) -> None:
        """The mask, as many bytes of it as the caller has.

        A short `raw` is not an error -- a Pool of Radiance record hands over
        seven -- so the ids read are the ones the bytes actually cover.
        """
        self._raw = bytes(raw)
        self.set_ids(i for i in range(1, len(self._raw) * 8)
                     if self._table.in_spellbook(i)
                     and self._raw[i >> 3] & (1 << (i & 7)))

    def to_bytes(self) -> bytes:
        """The mask with only the bits this widget shows rewritten.

        Bit 0, the bits above the title's last spell and every byte past its
        mask are left exactly as they were read: an editor rewriting the file
        it opened must not touch a bit it does not understand. That is what
        keeps a Curse book -- thirteen bytes read, sixteen handed over --
        from clearing whatever the last three hold.
        """
        out = bytearray(self._raw)
        for sid, row in self._rows.items():
            bit = 1 << (sid & 7)
            if row.checkState() == Qt.CheckState.Checked:
                out[sid >> 3] |= bit
            else:
                out[sid >> 3] &= ~bit
        return bytes(out)

    # -- state ------------------------------------------------------------

    def set_ids(self, ids) -> None:
        wanted = set(int(i) for i in ids)
        self._loading = True
        for sid, row in self._rows.items():
            row.setCheckState(Qt.CheckState.Checked if sid in wanted
                              else Qt.CheckState.Unchecked)
        self._loading = False

    def known(self) -> list[int]:
        return [sid for sid, row in self._rows.items()
                if row.checkState() == Qt.CheckState.Checked]

    def _ticked(self, _item) -> None:
        if not self._loading:
            self.changed.emit()


class MemorisedEditor(SpellEditor):
    """The packed list at 0x020: what is prepared right now.

    Ids repeat -- two CURE LIGHT WOUNDS is two entries -- so this is a list and
    not a set. A new one is inserted so that the list stays ordered by
    descending spell level, which is the shape `por/layout.py` records the
    game's own lists in.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._names: dict[int, str] | None = None
        self._table = DEFAULT_TABLE
        self._casts = False
        self._known: set[int] = set()
        self._cap: dict[str, tuple[int, ...]] = {}
        self._raw = bytes(MEMORISED_SIZE)

        self.list = QListWidget(self)
        self.choice = QComboBox(self)
        self.add = QPushButton("Add", self)
        self.remove = QPushButton("Remove", self)
        self.capacity = QLabel(self)
        self.capacity.setWordWrap(True)

        self.add.clicked.connect(self._add_chosen)
        self.remove.clicked.connect(self._remove_selected)

        # The drop-down gets a row to itself. Sharing one with the buttons left
        # it 140 px for a 303 px name -- Donald: "the text isn't entirely
        # visible" -- and the two buttons will not shrink to give it back.
        row = QHBoxLayout()
        for w in (self.add, self.remove):
            row.addWidget(w)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list)
        layout.addWidget(self.choice)
        layout.addLayout(row)
        layout.addWidget(self.capacity)
        self._fill_choices()

    def _fill_choices(self) -> None:
        self.choice.clear()
        for _cls, _level, ids in _ordered(self._table):
            for sid in ids:
                self.choice.addItem(
                    _spell_text(sid, self._names, self._table), sid)
        # Any of them can end up in the list, so the list is sized for the
        # longest of them and not for the handful memorised right now.
        fit_to_names(self.list,
                     [self.choice.itemText(i)
                      for i in range(self.choice.count())], checkable=False)
        fit_to_choices(self.choice)

    # -- the protocol -----------------------------------------------------

    def set_names(self, names: dict[int, str] | None,
                  table: SpellTable | None = None) -> None:
        self._names = names
        if table is not None:
            self._table = table
        ids = self.ids()
        self._fill_choices()
        self.set_ids(ids)

    def set_bytes(self, raw: bytes) -> None:
        self._raw = bytes(raw)
        self.set_ids([b for b in raw[:MEMORISED_SIZE] if b])

    def to_bytes(self) -> bytes:
        """The packed list -- or the bytes as read, when nothing moved.

        Repacking is not free: the list ends wherever the game stops reading
        it, and anything after that is residue we cannot account for. An
        untouched field therefore goes back exactly as it came.
        """
        ids = self.ids()[:MEMORISED_SIZE]
        if ids == [b for b in self._raw[:MEMORISED_SIZE] if b]:
            return self._raw
        return bytes(ids) + bytes(MEMORISED_SIZE - len(ids))

    # -- state ------------------------------------------------------------

    def set_ids(self, ids) -> None:
        self.list.clear()
        for sid in ids:
            self.list.addItem(self._row(int(sid)))
        self._describe()

    def ids(self) -> list[int]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list.count())]

    def set_known(self, ids) -> None:
        """Which spells are in the spellbook, so a stray one can be coloured."""
        self._known = set(int(i) for i in ids)
        for i in range(self.list.count()):
            self._paint(self.list.item(i))
        self._describe()

    def set_capacity(self, cap: dict[str, tuple[int, ...]],
                     casts: bool = False) -> None:
        """How many spells of each level may be memorised, and whether any may.

        The two are separate because they disagree: `por.spells.capacity`
        returns nothing for a title whose progression tables have not been
        read, and "we do not know how many" is not "none".
        """
        self._cap = cap
        self._casts = casts
        self._describe()

    # -- editing ----------------------------------------------------------

    def _row(self, sid: int) -> QListWidgetItem:
        row = QListWidgetItem(_spell_text(sid, self._names, self._table))
        row.setData(Qt.ItemDataRole.UserRole, sid)
        self._paint(row)
        return row

    def _paint(self, row: QListWidgetItem) -> None:
        sid = row.data(Qt.ItemDataRole.UserRole)
        stray = bool(self._known) and sid not in self._known
        row.setForeground(QBrush(UNKNOWN) if stray else QBrush())
        row.setToolTip("memorized but not in the spellbook" if stray else "")

    def _add_chosen(self) -> None:
        sid = self.choice.currentData()
        if sid is None:
            return
        self.add_spell(int(sid))

    def _level(self, sid: int) -> int:
        """The spell level of an id in the open title, or 0 for no group."""
        return (spell_group(sid, self._table) or ("", 0))[1]

    def add_spell(self, sid: int) -> bool:
        if self.list.count() >= MEMORISED_SIZE:
            return False
        level = self._level(sid)
        at = self.list.count()
        for i, other in enumerate(self.ids()):
            if self._level(other) < level:
                at = i
                break
        self.list.insertItem(at, self._row(sid))
        self._describe()
        self.changed.emit()
        return True

    def _remove_selected(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.remove_at(row)

    def remove_at(self, row: int) -> bool:
        if not 0 <= row < self.list.count():
            return False
        self.list.takeItem(row)
        self._describe()
        self.changed.emit()
        return True

    # -- the note beside the list -----------------------------------------

    def _describe(self) -> None:
        """The line under the list: how many are prepared against how many fit.

        Three shapes, because there are three things that can be true. A
        capacity to compare against; a caster whose title's progression tables
        we have not read, where the count is all that can honestly be said; and
        a character who casts nothing.

        UNAPPROVED WORDING: the middle case is a new string and Donald has not
        seen it. Before it, a Silver Blades caster was shown Pool of Radiance's
        slot counts, which was worse; after `capacity` learned about titles it
        would have read "This character casts no spells", which is worse still.
        """
        cap = self._cap
        ids = self.ids()
        if cap:
            width = max(len(a) for a in cap.values())
            counts = [sum(1 for s in ids if self._level(s) == lv)
                      for lv in range(1, width + 1)]
            parts = []
            for cls, allowed in cap.items():
                shown = ", ".join(f"L{lv} {counts[lv - 1]}/{allowed[lv - 1]}"
                                  for lv in range(1, len(allowed) + 1))
                parts.append(f"{cls}: {shown}")
            text = "  ".join(parts)
        elif self._casts:
            text = f"{len(ids)} memorized."
        else:
            text = NO_SPELLS if not ids else f"{len(ids)} memorized. {NO_SPELLS}"
        stray = [s for s in ids if self._known and s not in self._known]
        if stray:
            text += f"  ({len(stray)} not in the spellbook)"
        self.capacity.setText(text)
