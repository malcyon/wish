"""Choose a trait to write into one of a character's ten slots.

**Every name the open title's table has, in two sections that say where the
name came from.** Donald ruled on 2026-09-07 (`#13 (Edit traits and active
effects, in two separate panels)`): the whole table, not the half a player
character can plausibly carry. The alternative on offer was
`docs/107-roster-and-notes.md` section 8's cut at id 64, which hides exactly
the codes somebody would most want to try, and the spellbook picker set the
precedent -- offer everything, colour what is doubtful, say why in a tooltip,
and write what is picked.

**The two sections are provenance, not confidence.** "Seen in this game" is
the codes something on the player's own disks carries, or the game's own
routine was read for; "From the DOS table" is the ones only the third-party
guide names. A player can act on where a name came from. A grade -- PROBABLE,
CONFIRMED -- is a statement about how sure this project is, which is nobody
else's business.

Every string here is `editor/effects.py`'s, and Donald ruled on all of them
on 2026-09-08.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QTreeWidgetItem

from . import effects
from .ui_traitpicker import Ui_TraitPicker

#: Which section an item belongs to, stashed on the row so the filter can put
#: a heading back without rebuilding the tree.
CODE_ROLE = Qt.ItemDataRole.UserRole


class TraitPicker(QDialog):
    """Pick one code. `chosen` is it, or None if the dialog was cancelled."""

    def __init__(self, game=None, already: tuple[int, ...] = (), parent=None):
        super().__init__(parent)
        self.ui = Ui_TraitPicker()
        self.ui.setupUi(self)
        self.setWindowTitle(effects.PICKER_TITLE)
        self.already = tuple(already)
        self.game = game

        self.filter_line = self.ui.filter_line
        self.filter_line.setPlaceholderText(effects.PICKER_FILTER)
        self.filter_line.textChanged.connect(self._filter)

        self.list = self.ui.trait_list
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(self._double_clicked)

        self.buttons = self.ui.buttons
        self._fill()
        self._selection_changed()

    # -- building ---------------------------------------------------------

    def _fill(self) -> None:
        self.list.clear()
        self.sections: dict[bool, QTreeWidgetItem] = {}
        for seen, label in ((True, effects.SECTION_SEEN),
                            (False, effects.SECTION_TABLE)):
            head = QTreeWidgetItem(self.list, [label])
            # A heading is not a choice. Without this the OK button lights up
            # on a row that has no code behind it.
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = head.font(0)
            font.setBold(True)
            head.setFont(0, font)
            head.setExpanded(True)
            self.sections[seen] = head

        for code, name, seen in effects.offered(self.game):
            row = QTreeWidgetItem(self.sections[seen], [name])
            row.setData(0, CODE_ROLE, code)
            why = effects.warning(code, self.already, self.game)
            tip = f"{name} ({effects.confidence(code, self.game)})"
            if why:
                row.setForeground(0, QBrush(effects.WARN))
                tip = f"{tip}\n{why}"
            row.setToolTip(0, tip)
        for head in self.sections.values():
            head.setExpanded(True)

    # -- choosing ---------------------------------------------------------

    @property
    def chosen(self) -> int | None:
        items = self.list.selectedItems()
        if not items:
            return None
        return items[0].data(0, CODE_ROLE)

    def _selection_changed(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setEnabled(self.chosen is not None)

    def _double_clicked(self, item, _column) -> None:
        if item.data(0, CODE_ROLE) is not None:
            self.accept()

    # -- filtering --------------------------------------------------------

    def _filter(self, text: str) -> None:
        """Narrow to what matches, and drop a section that has nothing left.

        An empty section left behind reads as "there are none of these", which
        is a claim about the table rather than about what was typed.
        """
        want = text.strip().lower()
        for head in self.sections.values():
            shown = 0
            for n in range(head.childCount()):
                child = head.child(n)
                hit = not want or want in child.text(0).lower()
                child.setHidden(not hit)
                shown += hit
            head.setHidden(not shown)
            head.setExpanded(True)
