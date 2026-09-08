"""What is running on a saved game: the four effect arrays, read and shown.

**This list belongs to the save, not to the character the roster has
selected.** That is the whole point of the panel and the one thing its wording
has to get across: a spell cast on MALCYON is still in the list while BRUTUS
is the one on the sheet, and a Prayer on the whole party is in it with nobody
selected at all. The box title and the owner column carry that; the panel sits
in the top row beside the roster, which is save-wide too, rather than on a
per-character tab where it would read as the selected character's
(`#13 (Edit traits and active effects, in two separate panels)`, D1).

**Read-only, and nothing here reaches `store_save`.** `goldbox/effects.py`
has `write_effect` and `clear_effect`; this module calls neither, and Add and
Remove are a separate issue waiting on a measurement. The reason is not
caution in general: an effect's magnitude is per-id *restore* data -- ENLARGE
on BRUTUS stored his own 18/98 to put back when it lapsed -- so clearing an
id here skips the game's expiry handler and leaves a character at 18/00
strength for ever, and nothing about that is visible until much later.

**No duration is shown.** The duration byte holds a count in its low six bits
and a *unit* in its top two, and which unit each value selects has never been
decoded. A number over a unit nobody can name tells a player something we
cannot stand behind, so `Effect.remaining` and `Effect.unit` are not rendered
here and the raw bits do not go in a tooltip either
(`.claude/rules/gui-text.md`). `docs/136-condition-badges.md` refused the same
number on the condition badge for the same reason.

**The codes are one namespace with the traits at record `0x0AD`**, which is
why the names come from `goldbox/traits.py` here as well -- `LIBRARY $4028`
reads these arrays first and falls back to the character's own ten slots. What
separates the two lists is that an effect expires and a trait never does.
`docs/133-active-effects.md` is the plan for both panels.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QBrush
from PyQt6.QtWidgets import QTableView

from goldbox.effects import active_effects
from goldbox.traits import for_game

# One spelling of "this name is only a guess", shared with the traits box
# rather than copied: the two lists name codes out of the same table and a
# reader meets them on the same screen.
from .effects import UNSURE

# ===========================================================================
# The flag
# ===========================================================================

#: **Off unless `WISH_EXPERIMENTAL_EFFECTS=1`.** With it unset the box is
#: **not built** -- it comes out of the header layout and is destroyed, so
#: there is no greyed-out panel inviting the question of how to un-grey it and
#: no sentence in the interface answering that question
#: (`.claude/rules/feature-flags.md`; `wish/window.py` builds the Export
#: submenu inside the same kind of `if`).
#:
#: Separate from `WISH_EXPERIMENTAL_TRAITS` on purpose (`#13`, D3): that one
#: gates a *write* path and waits on a driven run of the game
#: (`#417 (Prove the game applies a trait Wish wrote, so
#: WISH_EXPERIMENTAL_TRAITS can come off)`). This one gates a panel that only
#: reads, so it must not be held back by a measurement it does not need.
#:
#: **Comes off when Donald has ruled on every string in the block below** and
#: each has lost its `(NOT APPROVED)` marker. That is the whole condition:
#: there is no measurement outstanding, because nothing here writes a byte.
#: Add and Remove on this panel are a different issue again, filed once M2
#: reports which effect ids read their magnitude back on expiry.
ENV = "WISH_EXPERIMENTAL_EFFECTS"

#: Anything else -- an empty string, `0`, `off` -- is off, matching
#: `wish/debugmode.py`. A variable somebody exported once and forgot must not
#: put an unapproved panel in front of them.
TRUE = ("1", "true", "yes", "on")


def enabled() -> bool:
    """Is the active-effects panel built in this run?"""
    return os.environ.get(ENV, "").strip().lower() in TRUE


# ===========================================================================
# Strings.
#
# Every word here is Donald's to word (`.claude/rules/gui-text.md`) and none
# has been ruled on, so every one ends in the literal ` (NOT APPROVED)` and
# the flag above is what keeps them off a player's screen. Never invent a
# sentence outside this block.
#
# The box title and the owner column are doing the work of saying the list is
# the *save's* and not the selected character's, so they are the two to read
# hardest. A title that named the character -- "Active effects" over a panel
# beside the roster -- would put back exactly the confusion `#13` exists to
# end.
# ===========================================================================

#: The group box's title.
BOX_TITLE = "Effects running in this saved game (NOT APPROVED)"

#: The two column headings. No third column for the duration: see the module
#: docstring, and `#13`'s D2.
HEADER_EFFECT = "What is running (NOT APPROVED)"
HEADER_OWNER = "Who it is on (NOT APPROVED)"

#: An effect the owner byte puts on the whole party rather than on one
#: character. The engine writes both shapes and neither can be dropped: Bless
#: writes one row per character and Prayer writes a single row owned by
#: everybody.
OWNER_PARTY = "Everybody in the party (NOT APPROVED)"

#: An owner byte of 8 or more, which is a combatant in a fight rather than a
#: character in the party. It cannot be named: the index means something only
#: inside the fight that wrote it, and that fight is over by the time anybody
#: reads a save.
OWNER_MONSTER = "Something that was in a fight, not one of your characters (NOT APPROVED)"

#: An owner byte in the party's own range with nobody in that slot -- a
#: character who left the party while something was still running on them.
OWNER_ABSENT = "Nobody who is in the party now (NOT APPROVED)"

#: An effect id the trait census does not name. The number is kept because it
#: is what somebody takes away to look it up, and because two unnamed effects
#: still have to be told apart -- `goldbox.traits.describe` makes the same
#: choice for an unnamed trait code.
UNNAMED_EFFECT = "Effect {code}, which nobody has named (NOT APPROVED)"
# ---------------------------------------------------------------------------


def label(code: int, game=None) -> str:
    """What the first column says for one effect id.

    Named through `goldbox/traits.py`, because the effect ids and the trait
    codes are one namespace. Not through `traits.describe`, whose fallback for
    an unnamed code reads `trait 42` -- the right word on the character sheet
    and the wrong one here, where the row is not a trait.
    """
    named = for_game(game).get(code)
    return named[0] if named else UNNAMED_EFFECT.format(code=code)


def owner_label(effect, names: dict[int, str]) -> str:
    """What the second column says: which character, or that it is everybody.

    *names* maps a party slot -- `Member.index`, the number the owner byte
    holds -- to that character's name. A slot nobody fills is a real case:
    `CAMP` renumbers the owner byte when a character changes slot, and a
    character who leaves the party takes no effect with them.
    """
    if effect.party_wide:
        return OWNER_PARTY
    if effect.monster:
        return OWNER_MONSTER
    return names.get(effect.owner) or OWNER_ABSENT


class ActiveEffectsModel(QAbstractTableModel):
    """One row per running effect, and no rows at all when nothing is running.

    Unlike the traits box, which draws its ten slots whether or not anything
    is in them, this one draws only what is there: the traits box shows empty
    rows because the *extent* of that list -- ten, and XAVIER proves the tenth
    is real -- is something the player needs to see, and 64 empty rows say
    nothing at all.

    **The empty state is the two column headings over no rows.** No sentence,
    which is the plan's answer and `.claude/rules/gui-text.md`'s default: a
    line explaining that a list is empty is a line that has to be worded,
    approved and then read by somebody who can already see it.
    """

    HEADERS = (HEADER_EFFECT, HEADER_OWNER)

    def __init__(self, effects=(), names=None, game=None, parent=None):
        # Parented, so the C++ view and its model die together. An unparented
        # model outliving -- or predeceasing -- its view segfaults PyQt in a
        # test run that builds a dozen windows.
        super().__init__(parent)
        self.effects = tuple(effects)
        self.names = dict(names or {})
        self.game = game

    def set_effects(self, effects, names=None, game=None) -> None:
        self.beginResetModel()
        self.effects = tuple(effects)
        if names is not None:
            self.names = dict(names)
        self.game = game
        self.endResetModel()

    def rowCount(self, _parent=QModelIndex()) -> int:
        return len(self.effects)

    def columnCount(self, _parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (orientation is Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole):
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.effects):
            return None
        effect = self.effects[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return label(effect.id, self.game)
            return owner_label(effect, self.names)
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 0:
            named = for_game(self.game).get(effect.id)
            if named is not None and named[1] == "GUESS":
                return QBrush(UNSURE)
        return None


class ActiveEffectsView(QTableView):
    """The panel on the form, promoted in Designer.

    Read-only in the strongest sense the widget has: no edit triggers, no
    selection to act on, and no method that writes a byte anywhere.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = ActiveEffectsModel(parent=self)
        self.setModel(self.model_)
        self.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableView.SelectionMode.NoSelection)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)

    def set_party(self, party) -> None:
        """Show what is running in *party*'s save, or nothing at all.

        A party with no `save0` -- a `.chr` export or a roster disk -- has no
        save image to read the arrays out of, so there is nothing to show.
        `editor/window.py` takes the whole box off the row in that case; this
        empties the model so a window that opened a save and then a roster
        disk is not left holding the first one's effects.
        """
        if party is None or party.save0 is None:
            self.model_.set_effects((), {}, None)
            self._fit()
            return
        names = {m.index: m.name for m in party.members}
        self.model_.set_effects(active_effects(party.save0.to_bytes()),
                                names, party.game)
        self._fit()

    def _fit(self) -> None:
        self.resizeColumnsToContents()
        self.horizontalHeader().setStretchLastSection(True)

    def rows(self) -> list[tuple[str, str]]:
        """What the panel says, row by row -- for tests and for a screenshot
        tool, so neither has to reach into the model's internals."""
        m = self.model_
        return [(m.data(m.index(r, 0)), m.data(m.index(r, 1)))
                for r in range(m.rowCount())]
