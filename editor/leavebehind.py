"""Choose which items and scrolls stay behind when a pack does not fit the C64.

**One window for every character whose pack does not fit**, built from
`goldbox.dos_codec.JoinedScrollsDoNotFit.overflow` (`#432 (A joined scroll in
a DOS Silver Blades save shifts everything after it out of the character's
pack)`). Each character gets a row; beneath it every item is a row the player
ticks, a joined scroll is a heading that is neither ticked nor selected, and
each scroll inside it is a row the player ticks, with the spells it holds on a
quieter line under it. Ticking more than the pack needs is allowed.

**Approved by Donald, and exactly these:** `HEADING` and `EXPLANATION`, and
for effects mode `EFFECTS_EXPLANATION` and `EFFECTS_REMAINING`. The window's own
title, the joined scroll's heading and the words around each character's
remaining count are not settled, so this module shows them blank rather than
writing any (`.claude/rules/gui-text.md`). The accept button's
label is the caller's: the existing Convert or Save As label.

**A second mode lists running effects** (`effects=`), built from
`goldbox.dos_codec.EffectsDoNotFit.overflow`: the C64's 64-row table of
running effects is the whole party's, so there is one count for the party and
not one per character. Each character who holds an effect the player can leave
out is a row, with every such effect beneath it on a row of its own, repeats
included. The heading, the explanation, the count beneath the list and the
effect names are Donald's approved ones; every other word of this mode is blank
until he settles it, and the columns that would hold no text are hidden.

The item rows reuse the Items tab: its name (`editor.inventory.describe`), its
`Qty` and `Readied` columns under their own headers, and the spell form its
detail pane draws for a scroll.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTreeWidgetItem,
)

from goldbox.dos_codec import C64_SCROLL_TYPES, EffectOverflow, PackOverflow
from goldbox.items import Item
from goldbox.spells import SpellTable

from .activeeffects import HEADER_EFFECT
from .activeeffects import label as effect_label
from .inventory import HEADERS, NAME, QTY, READIED_COL, ItemTraitsModel, describe
from .ui_leavebehind import Ui_LeaveBehindDialog

#: Donald's approved heading and explanation, verbatim.
HEADING = "Choose what to leave behind"
EXPLANATION = (
    "The C64 has 16 item slots per character. A joined scroll becomes "
    "separate scrolls, each taking one slot. Choose items or scrolls to "
    "leave behind until each pack fits.")
#: Effects mode: the explanation (`{n}` is how many rows the window opened
#: short, and the 64 is the C64 table's fixed size) and the live count beneath
#: the list (`{n}` is how many are still to leave).
EFFECTS_EXPLANATION = ("The C64 save has room for 64 running effects. "
                       "Choose at least {n} to leave behind.")
EFFECTS_REMAINING = "{n} more to leave behind"

#: The columns: the Items tab's own item, quantity and readied columns, and
#: one more that holds a character's remaining count and nothing else.
NAME_COLUMN, QTY_COLUMN, READIED_COLUMN, COUNT_COLUMN = range(4)

#: What a ticked row carries: `(member, inventory index)`.
PICK_ROLE = Qt.ItemDataRole.UserRole

#: Where the spells of a scroll are, in its sixteen bytes.
SPELL_BYTES = slice(13, 16)


class LeaveBehindDialog(QDialog):
    """Tick what stays behind; `chosen()` is what to hand the writer as
    `leave`, and the accept button waits until every pack fits."""

    def __init__(self, overflow: Sequence[PackOverflow],
                 item_names: dict[int, str] | None,
                 spell_names: dict[int, str] | None,
                 spells: SpellTable,
                 accept_label: str,
                 parent=None, *,
                 effects: EffectOverflow | None = None,
                 game=None):
        super().__init__(parent)
        self.ui = Ui_LeaveBehindDialog()
        self.ui.setupUi(self)
        # Blank on purpose: the window's title is not settled.
        self.setWindowTitle("")
        self.ui.heading_label.setText(HEADING)
        self.ui.explanation_label.setText(
            EXPLANATION if effects is None
            else EFFECTS_EXPLANATION.format(n=max(0, effects.over)))

        self.overflow = tuple(overflow)
        self.effects = effects
        self._game = game
        self.item_names = item_names or {}
        # The Items tab's own model reads a spell into words; reusing it keeps
        # one form for a scroll's spells.
        self._spell_reader = ItemTraitsModel()
        self._spell_reader.set_tables({}, spell_names or {}, spells)
        # A scroll's type id is the title's own: 0x27 is a trident in Pool of
        # Radiance and Curse.
        self._scroll_types = C64_SCROLL_TYPES.get(spells.key, ())

        self.tree = self.ui.pack_tree
        self.tree.setHeaderLabels(
            [HEADERS[NAME], HEADERS[QTY], HEADERS[READIED_COL], ""]
            if effects is None else [HEADER_EFFECT, "", "", ""])
        header = self.tree.header()
        header.setSectionResizeMode(NAME_COLUMN,
                                    QHeaderView.ResizeMode.Stretch)
        for column in (QTY_COLUMN, READIED_COLUMN, COUNT_COLUMN):
            header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents)

        self.buttons = self.ui.buttons
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            accept_label)

        #: One entry per character: the overflow, its row, what is ticked.
        self._entries: list[tuple[PackOverflow, QTreeWidgetItem, set[int]]] = []
        #: Effects mode: what is ticked, `{member: indices}`.
        self._ticked_effects: dict[int, set[int]] = {}
        for entry in self.overflow:
            self._fill(entry)
        if effects is not None:
            self._fill_effects(effects)
            # Quantity, Readied and the remaining count have nothing to say
            # about an effect, and no time left is shown.
            for column in (QTY_COLUMN, READIED_COLUMN, COUNT_COLUMN):
                self.tree.setColumnHidden(column, True)
        # The party-wide count is only there in effects mode; pack mode keeps
        # its count on each character's row.
        self.ui.remaining_label.setVisible(effects is not None)
        self.tree.expandAll()
        self.tree.itemChanged.connect(self._changed)
        self._refresh()

    # -- building -----------------------------------------------------------

    def _fill(self, entry: PackOverflow) -> None:
        member = entry.members[0]
        raws = entry.items[0]
        character = QTreeWidgetItem(self.tree, [entry.names[0]])
        character.setFlags(Qt.ItemFlag.ItemIsEnabled)
        font = character.font(NAME_COLUMN)
        font.setBold(True)
        character.setFont(NAME_COLUMN, font)
        character.setTextAlignment(
            COUNT_COLUMN, Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter)
        self._entries.append((entry, character, set()))

        parent = character
        for unit in entry.units:
            if unit.kind == "joined":
                # Heading only: it names the scrolls beneath it. Its text is
                # not settled, so the row is blank.
                parent = QTreeWidgetItem(character, [""])
                parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
                continue
            if unit.kind == "item":
                parent = character
            index = unit.indices[0]
            raw = raws[index]
            row = self._pick_row(parent, member, index, raw)
            if unit.kind == "scroll" or raw[0] in self._scroll_types:
                self._spell_line(row, raw)

    def _fill_effects(self, effects: EffectOverflow) -> None:
        """One row per member who holds an effect that can be left out, and one
        checkable row beneath it for each such effect. The time-left column is
        not shown: no time left is approved."""
        parents: dict[int, QTreeWidgetItem] = {}
        for entry in effects.entries:
            parent = parents.get(entry.member)
            if parent is None:
                parent = QTreeWidgetItem(
                    self.tree, [effects.names[entry.member]])
                parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
                font = parent.font(NAME_COLUMN)
                font.setBold(True)
                parent.setFont(NAME_COLUMN, font)
                parents[entry.member] = parent
            row = QTreeWidgetItem(
                parent, [effect_label(entry.effect_id, self._game), "", "", ""])
            row.setFlags(Qt.ItemFlag.ItemIsEnabled
                         | Qt.ItemFlag.ItemIsSelectable
                         | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(NAME_COLUMN, Qt.CheckState.Unchecked)
            row.setData(NAME_COLUMN, PICK_ROLE, (entry.member, entry.index))

    def _pick_row(self, parent: QTreeWidgetItem, member: int, index: int,
                  raw: bytes) -> QTreeWidgetItem:
        item = Item(raw, self.item_names)
        row = QTreeWidgetItem(parent, [
            describe(item, self.item_names),
            # `InventoryModel._text`'s own rules for these two columns.
            str(item.quantity) if item.quantity else "",
            "Yes" if item.readied else "No", ""])
        row.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                     | Qt.ItemFlag.ItemIsUserCheckable)
        row.setCheckState(NAME_COLUMN, Qt.CheckState.Unchecked)
        row.setData(NAME_COLUMN, PICK_ROLE, (member, index))
        for column in (QTY_COLUMN, READIED_COLUMN):
            row.setTextAlignment(column, Qt.AlignmentFlag.AlignRight
                                 | Qt.AlignmentFlag.AlignVCenter)
        return row

    def _spell_line(self, row: QTreeWidgetItem, raw: bytes) -> None:
        """The spells a scroll holds, one to a line, on a quieter row beneath
        it: three spells with their classes and levels are wider than the
        window, and a row of an item view cuts what does not fit."""
        spells = [self._spell_reader._scroll_spell(s)
                  for s in raw[SPELL_BYTES] if s]
        if not spells:
            return
        line = QTreeWidgetItem(row, ["\n".join(spells)])
        line.setFlags(Qt.ItemFlag.ItemIsEnabled)
        quiet = self.palette().color(QPalette.ColorRole.PlaceholderText)
        line.setForeground(NAME_COLUMN, quiet)

    # -- choosing -----------------------------------------------------------

    def _changed(self, row: QTreeWidgetItem, column: int) -> None:
        if column != NAME_COLUMN:
            return
        pick = row.data(NAME_COLUMN, PICK_ROLE)
        if pick is None:
            return
        member, index = pick
        if self.effects is not None:
            ticked = self._ticked_effects.setdefault(member, set())
            if row.checkState(NAME_COLUMN) == Qt.CheckState.Checked:
                ticked.add(index)
            else:
                ticked.discard(index)
            self._refresh()
            return
        for entry, _character, ticked in self._entries:
            if entry.members[0] != member:
                continue
            if row.checkState(NAME_COLUMN) == Qt.CheckState.Checked:
                ticked.add(index)
            else:
                ticked.discard(index)
        self._refresh()

    @staticmethod
    def _remaining(entry: PackOverflow, ticked: set[int]) -> int:
        """How many more must be left before this pack fits."""
        return max(0, len(entry.items[0]) - len(ticked) - entry.limit)

    def _effects_remaining(self) -> int:
        """How many more effects must be left out before the party fits."""
        ticked = sum(len(v) for v in self._ticked_effects.values())
        return max(0, self.effects.over - ticked)

    def _refresh(self) -> None:
        if self.effects is not None:
            remaining = self._effects_remaining()
            self.ui.remaining_label.setText(
                EFFECTS_REMAINING.format(n=remaining))
            self.buttons.button(QDialogButtonBox.StandardButton.Ok
                                ).setEnabled(remaining == 0)
            return
        for entry, character, ticked in self._entries:
            character.setText(COUNT_COLUMN,
                              str(self._remaining(entry, ticked)))
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(all(self._remaining(entry, ticked) == 0
                          for entry, _character, ticked in self._entries))

    def chosen(self) -> dict[int, frozenset[int]]:
        """Each character's ticked inventory indices; one with nothing ticked
        is left out."""
        return {entry.members[0]: frozenset(ticked)
                for entry, _character, ticked in self._entries if ticked}

    def chosen_effects(self) -> dict[int, frozenset[int]]:
        """Each member's ticked running-effect indices; one with nothing
        ticked is left out."""
        return {member: frozenset(ticked)
                for member, ticked in self._ticked_effects.items() if ticked}
