"""The ten trait slots at `0x0AD`, spelled out on the character sheet.

The codes themselves live in `goldbox/traits.py` -- the combat view names the same
ones on a monster's tooltip, and one table cannot be allowed to become two.
This module is the sheet's view of them: ten rows, coloured by confidence.

**A cast spell is not in here.** `P3-EFFECTS.D64` proved it: twenty-six spells
running and every block unchanged. What these slots carry is the racial seed,
a monster's specials and an item's passive power. The live effects are four
64-entry arrays inside `SAVEDGAME0` and nothing shows them yet --
`docs/133-active-effects.md` is the plan for both.

**The list is editable only behind `WISH_EXPERIMENTAL_TRAITS`**, and the flag
block below says what takes the flag off. With the flag unset the two buttons
are never built and the table keeps `NoEditTriggers`, so the block reaches the
disk exactly as it was read.

**The codes are per title**, which is why the model carries the game and not
just the bytes: Secret of the Silver Blades gives an elf 95 where Pool of
Radiance gives 107, and 95 is Pool of Radiance's "fights on from -6 to 0 hit
points". Reading every save through one table put that sentence on the sheet
of an elf who has the ordinary elf's resistance to sleep and charm (#186).
`goldbox.traits.for_game` is the one place that chooses.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QTableView

# EMPTY is re-exported: the form's tests read it as `effects.EMPTY`.
from goldbox.traits import (  # noqa: F401
    EMPTY,
    FILL,
    NAMES,
    SLOTS,
    confidence,
    describe,
    for_game,
)

FADED = QColor("#808080")
UNSURE = QColor("#7d6608")     # a GUESS, coloured the way an NPC name is
#: A code the sheet will write and `docs/133-active-effects.md` has a reason to
#: doubt -- a monster's attack form on a character, a code with no handler, a
#: code nobody has named, the same code twice. Not a refusal: the editor writes
#: what is picked, the way the spellbook does, and says what it is not refusing.
WARN = QColor("#8b3a1a")


# ===========================================================================
# The flag
# ===========================================================================

#: **Off unless `WISH_EXPERIMENTAL_TRAITS=1`.** The Add and Remove buttons are
#: **not built** when it is unset -- not greyed out, because a greyed button
#: invites the question of how to un-grey it and the answer would be a
#: sentence in the interface (`.claude/rules/feature-flags.md`). The table
#: itself stays where it has always been, showing the ten slots and editing
#: nothing.
#:
#: **Comes off when both are true:**
#:
#: 1. **M3 reports** -- a trait this editor wrote is applied by the running
#:    game and never expires. `#417 (Prove the game applies a trait Wish
#:    wrote, so WISH_EXPERIMENTAL_TRAITS can come off)` is the measurement:
#:    write 20 Resist Fire into a free slot through File > Save, boot, VIEW
#:    the character, confirm the game lists it, save and reload, confirm it
#:    survives. **Taken, 2026-09-08, and CONFIRMED on all three claims**: the
#:    byte survives four cold boots and the game's own save; `LIBRARY $403C`
#:    executes with the trait's id in the accumulator, once per edited run
#:    and never in a control; and a fire spell does 1 damage where the
#:    control takes 2, reproduced over two pairs of boots whose event streams
#:    are identical for their first 681 events. One step of the plan is
#:    refuted rather than met: `VIEW` never lists a trait, for any character,
#:    because Pool of Radiance cannot do it. `#252 (Does a C64 trait slot apply an
#:    item-granted effect id, or only the ones its own READY routine wrote?)`
#:    already CONFIRMED the general claim for ids this project staged -- 98
#:    regenerated a wounded character three a round and a fire spell asked
#:    the slots about 61 and honoured the byte we put there -- so what is
#:    left is narrow: the same thing through the editor's own write path.
#: 2. **Every string in the block below loses its `(NOT APPROVED)` marker**,
#:    because Donald has ruled on it (`.claude/rules/gui-text.md`). **Ruled
#:    on, 2026-09-08**: he was shown the box, the picker and a warning, and
#:    approved every string as it stood, against three alternatives for the
#:    warnings -- one sentence for all four, a mark with the explanation in a
#:    tooltip, or his own words.
#:
#: **So both are met and this flag is due to be deleted**, along with the
#: `if` around the buttons -- which is the next commit rather than this one.
#:
#: An environment variable and no preference, the same shape as `WISH_DEBUG`
#: and `editor/convert.py`: a checkbox would need a label, and a label saying
#: "experimental" would need a sentence saying what that meant for the
#: player's save disk.
ENV = "WISH_EXPERIMENTAL_TRAITS"

#: Anything else -- an empty string, `0`, `off` -- is off, matching
#: `wish/debugmode.py`. A variable somebody exported once and forgot must not
#: put an unapproved button in front of them.
TRUE = ("1", "true", "yes", "on")


def enabled() -> bool:
    """Are Add and Remove offered on the traits box in this run?"""
    return os.environ.get(ENV, "").strip().lower() in TRUE


# ===========================================================================
# Strings.
#
# Every one of these is Donald's to word (`.claude/rules/gui-text.md`), and
# **he ruled on all of them on 2026-09-08**, shown the box, the picker and a
# warning as pictures. He took them as they stood, against three alternatives
# for the four warnings: one sentence covering all four, a mark with the
# explanation in a tooltip, or his own words. So the markers are off.
#
# Never invent a sentence outside this block. A new string here is unapproved
# again, whatever the ones around it say, and carries `(NOT APPROVED)` until
# he has seen it.
#
# `BOX_TITLE` never carried a marker: `wish/window.ui` has read
# `Character Traits` since 2026-08-22 and is on screen for every user with no
# flag set, so appending one would have put those two words in front of
# everybody -- the trade `editor/convert.py`'s `SOURCE_FILTER` comment
# describes from the other side. It was on the list he ruled on all the same.
# ===========================================================================

#: The traits box's title, as `wish/window.ui` carries it. Approved
#: 2026-09-08 with the rest of this block.
BOX_TITLE = "Character Traits"

#: The two buttons inside the box.
BUTTON_ADD = "Add…"
BUTTON_REMOVE = "Remove"

#: The picker's title bar and its filter line.
PICKER_TITLE = "Choose a trait"
PICKER_FILTER = "Type to narrow the list"

#: The picker's two sections. A **provenance** statement rather than a
#: confidence grade: a player can act on where a name came from and cannot act
#: on how sure somebody was. `SECTION_SEEN` holds the codes something on the
#: player's own disks carries, or the game's own code was read for;
#: `SECTION_TABLE` holds the ones only the DOS guide's table names.
SECTION_SEEN = "Seen in this game"
SECTION_TABLE = "From the DOS table"

#: Why a code is coloured, on the picker row and on the sheet. The four cases
#: `docs/133-active-effects.md` sets out under "What a nonsense combination
#: could do". None of them refuses the write.
REASON_MONSTER = ("A monster's way of attacking. A character has none of the "
                  "parts it reads, so nobody knows what it would do.")
REASON_NO_HANDLER = ("The game has no answer for this one, so nothing is "
                     "known about what asking it would do.")
REASON_UNNAMED = ("Nobody has named this one. One creature in the game "
                  "carries it and what it does is unknown.")
REASON_DUPLICATE = ("This character already has this in another slot. Whether "
                    "it counts twice has never been tested.")
# ---------------------------------------------------------------------------


# ===========================================================================
# Which codes carry a warning
# ===========================================================================

#: Ids from here up are monster attack forms -- poison bites, gazes, breath
#: weapons -- and belong on a monster rather than a character
#: (`docs/107-roster-and-notes.md` section 8).
MONSTER_FIRST = 64

#: The exceptions: ids at or above that cut which the **game itself** writes
#: onto a player character, so a warning about them would be false.
#:
#: * 89, the one passive item power above the cut -- the player's own CLOAK OF
#:   DISPLACEMENT grants it, and `#252` watched READY write exactly this byte.
#: * 90 and 97, the dwarf/gnome/halfling constitution bonuses, written by race
#:   at creation (`#247`).
#: * 92, 95 and 105, three of the nine Secret of the Silver Blades seeds.
#: * 107 and 124, the elf's and half-elf's resistance to sleep and charm,
#:   which `GEN` seeds at creation.
BORN_WITH = frozenset({89, 90, 92, 95, 97, 105, 107, 124})

#: Codes `goldbox/traits.py` records as having no handler in the game.
NO_HANDLER = frozenset({54, 63})


def warning(code: int, others: tuple[int, ...] = (), game=None) -> str:
    """Why this code is doubtful in a character's slot, or `""`.

    *others* is the rest of the block, so the duplicate case can be seen. The
    order is the order a reader wants: the code's own trouble first, and "you
    already have this" only when there is nothing worse to say.
    """
    if not code or code == FILL:
        return ""
    if code in NO_HANDLER:
        return REASON_NO_HANDLER
    if confidence(code, game) == "UNKNOWN":
        return REASON_UNNAMED
    if code >= MONSTER_FIRST and code not in BORN_WITH:
        return REASON_MONSTER
    if code in others:
        return REASON_DUPLICATE
    return ""


def offered(game=None) -> list[tuple[int, str, bool]]:
    """Every code the picker offers: `(code, name, seen_in_this_game)`.

    All of the open title's table bar 255, which is a fill byte in the last
    slot and not a trait at all -- `goldbox/traits.py` measured it as 38 of
    108 monster records, every one of them slot 9, and the combat tooltip
    already drops it rather than printing "fill". Offering it as something to
    add would be offering a hole.

    `seen_in_this_game` is `goldbox/traits.py`'s own PROBABLE grade read as
    provenance, which is what that grade means: PROBABLE is "the guide names
    it and nothing on the C64 exercises it and no overlay code has been read
    for it". Everything else has a carrier on the player's disks or a routine
    somebody read.
    """
    names = for_game(game)
    return [(code, names[code][0], names[code][1] != "PROBABLE")
            for code in sorted(names) if code != FILL]


def compact(raw: bytes) -> bytes:
    """The block with its holes closed, packed from slot 0.

    A 255 in slot 9 is a fill byte rather than a code and **stays in slot 9**:
    38 of the 108 monster records on the disks carry one, every one of them in
    the last slot, and no record has a real code after it. Moving it would
    make a block no record has ever looked like.
    """
    codes = list(raw[:SLOTS]) + [0] * SLOTS
    fill = codes[SLOTS - 1] == FILL
    room = SLOTS - 1 if fill else SLOTS
    body = [c for c in codes[:room] if c][:room]
    out = (body + [0] * SLOTS)[:SLOTS]
    if fill:
        out[SLOTS - 1] = FILL
    return bytes(out)


def room(raw: bytes) -> int:
    """How many more codes this block can hold: nine if a fill holds the tenth."""
    codes = list(raw[:SLOTS]) + [0] * SLOTS
    fill = codes[SLOTS - 1] == FILL
    limit = SLOTS - 1 if fill else SLOTS
    return limit - sum(1 for c in codes[:limit] if c)


class EffectsModel(QAbstractTableModel):
    """Ten rows whether or not anything is in them.

    Showing the empty slots is how the extent of the list stays visible: it is
    ten, XAVIER proved it by carrying a code in the tenth, and a table that
    shrank to the used ones would hide that.
    """

    # No code column. The number is what the census is indexed by and what a
    # tooltip falls back to for a code nobody has named; on the sheet it is a
    # second spelling of the name beside it.
    HEADERS = ("Slot", "Trait")

    def __init__(self, raw: bytes = b"", game=None, parent=None):
        # Parented, so the C++ view and its model die together. An unparented
        # model outliving -- or predeceasing -- its view segfaults PyQt in a
        # test run that builds a dozen windows.
        super().__init__(parent)
        self.raw = bytes(raw)
        self.game = game
        self.names = for_game(game)

    def set_bytes(self, raw: bytes) -> None:
        self.beginResetModel()
        self.raw = bytes(raw)
        self.endResetModel()

    def set_game(self, game) -> None:
        """Name the codes the way the open title does."""
        self.beginResetModel()
        self.game = game
        self.names = for_game(game)
        self.endResetModel()

    def to_bytes(self) -> bytes:
        """**Exactly what was set, until something is added or removed.**

        Not a normalised ten bytes: a block that arrives short, or with a hole
        in it, is a block the game wrote and the editor has no business
        tidying. `editor/window.py` writes this back only when it differs from
        the record, so an untouched save reaches the disk byte for byte and
        that is what `test_the_editor_writes_a_save_back_unchanged_with_traits_on`
        holds. Only :meth:`add` and :meth:`remove` replace it, and they replace
        it with a compacted ten.
        """
        return self.raw

    def rowCount(self, _parent=QModelIndex()) -> int:
        return SLOTS

    def columnCount(self, _parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (orientation is Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole):
            return self.HEADERS[section]
        return None

    def _code(self, row: int) -> int:
        return self.raw[row] if row < len(self.raw) else 0

    def _others(self, row: int) -> tuple[int, ...]:
        return tuple(self._code(n) for n in range(SLOTS) if n != row)

    def warning_at(self, row: int) -> str:
        """Why this slot's code is doubtful, or `""` -- `docs/133`'s table.

        **Silent unless the flag is on**, and for the same reason the buttons
        are not built: every reason above is a placeholder Donald has not
        ruled on, and a character who happens to carry a monster's code would
        otherwise be handed one in a tooltip with no flag set. There is also
        nothing to explain when there is no Add button to explain.
        """
        if not enabled():
            return ""
        return warning(self._code(row), self._others(row), self.game)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        code = self._code(row)
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return str(row)
            return describe(code, self.names)
        if role == Qt.ItemDataRole.ForegroundRole:
            if not code:
                return QBrush(FADED)
            if self.warning_at(row):
                return QBrush(WARN)
            if self.names.get(code, ("", "GUESS"))[1] == "GUESS":
                return QBrush(UNSURE)
        if role == Qt.ItemDataRole.ToolTipRole and code:
            why = self.warning_at(row)
            named = self.names.get(code)
            if named is None:
                said = f"code {code}; the trait census does not name it"
            else:
                said = f"{named[0]} ({named[1]})"
            return f"{said}\n{why}" if why else said
        return None


class EffectsView(QTableView):
    """The effect list on the form, promoted in Designer.

    Speaks `set_bytes` like the spell widgets do, so the window fills it
    without knowing what it is, and `to_bytes` the way the spell widgets do
    too -- but `to_bytes` hands back what it was given until :meth:`add` or
    :meth:`remove` is called, so a run with `WISH_EXPERIMENTAL_TRAITS` unset
    writes the block back untouched.
    """

    #: Something was added or removed, so the window's dirty flag should move.
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = EffectsModel(parent=self)
        self.setModel(self.model_)
        self.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)

    def set_bytes(self, raw: bytes) -> None:
        self.model_.set_bytes(raw)
        self.resizeColumnsToContents()
        self.horizontalHeader().setStretchLastSection(True)

    def to_bytes(self) -> bytes:
        return self.model_.to_bytes()

    def set_game(self, game) -> None:
        """The open title changed, so the names may have. `editor/window.py`
        calls this from `_fill_combos`, beside the other per-title tables."""
        self.model_.set_game(game)
        self.resizeColumnsToContents()
        self.horizontalHeader().setStretchLastSection(True)

    def codes(self) -> list[int]:
        return [self.model_._code(n) for n in range(SLOTS)]

    # -- editing, behind the flag ------------------------------------------

    def room(self) -> int:
        """How many more codes fit. Zero is what disables Add."""
        return room(bytes(self.codes()))

    def selected_row(self) -> int:
        """The slot the user has picked, or -1. Remove needs one with a code
        in it: removing an empty slot is a button that does nothing."""
        rows = self.selectionModel().selectedRows() if self.selectionModel() else []
        return rows[0].row() if rows else -1

    def can_remove(self) -> bool:
        row = self.selected_row()
        return 0 <= row < SLOTS and bool(self.model_._code(row))

    def _replace(self, raw: bytes) -> None:
        if bytes(raw) == self.model_.raw:
            return
        self.set_bytes(bytes(raw))
        self.changed.emit()

    def add(self, code: int) -> None:
        """Put *code* in the first free slot, closing any holes on the way."""
        if not code or not self.room():
            return
        codes = list(compact(bytes(self.codes())))
        limit = SLOTS - 1 if codes[SLOTS - 1] == FILL else SLOTS
        for i in range(limit):
            if not codes[i]:
                codes[i] = code
                break
        self._replace(bytes(codes))

    def remove(self, row: int) -> None:
        """Clear that slot and close the gap behind it."""
        if not 0 <= row < SLOTS or not self.model_._code(row):
            return
        codes = list(bytes(self.codes()))
        codes[row] = 0
        self._replace(compact(bytes(codes)))
