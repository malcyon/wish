"""The window that asks which items and scrolls stay behind (#432).

Every pack here is composed from the documented item format on neutral
characters and run through `goldbox.dos_codec.pack_overflow`, so the window is
built from what the writer itself reports and no game data is needed. The
spell and item names are made up: the tests are about which rows exist, what
can be ticked and what the window hands back, not about the game's words.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox
from support import packoverflow as packs

import editor.window as ew
from editor import leavebehind
from editor.inventory import HEADERS, Inventory, InventoryModel
from editor.inventory import NAME as ITEMS_NAME
from editor.inventory import QTY as ITEMS_QTY
from editor.inventory import READIED_COL as ITEMS_READIED
from editor.leavebehind import LeaveBehindDialog
from goldbox import c64_port, dos_codec, items
from goldbox.spells import for_game

GAME = c64_port.SECRET_OF_THE_SILVER_BLADES
#: The window's own first column, where the name and the tick are.
NAME = leavebehind.NAME_COLUMN
CHECKABLE = Qt.ItemFlag.ItemIsUserCheckable
SELECTABLE = Qt.ItemFlag.ItemIsSelectable
ACCEPT = "Accept label from the caller"

ITEM_NAMES = {1: "WAND", 2: "MAGE", 3: "SCROLL", 4: "STAFF"}
SPELL_NAMES = {5: "SLEEP", 6: "FIREBALL", 7: "HASTE"}


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


_plain, _scroll, _member, _party = (packs.plain, packs.scroll, packs.member,
                                    packs.party)


def _dialog(party=None, accept=ACCEPT):
    overflow = dos_codec.pack_overflow(party or _party())
    return LeaveBehindDialog(overflow, ITEM_NAMES, SPELL_NAMES, for_game(GAME),
                             accept)


def _rows(dialog):
    """Every row of the tree, depth first."""
    out = []

    def walk(item):
        out.append(item)
        for n in range(item.childCount()):
            walk(item.child(n))

    for n in range(dialog.tree.topLevelItemCount()):
        walk(dialog.tree.topLevelItem(n))
    return out


def _picks(dialog):
    """`{(member, index): row}` for every row that can be ticked."""
    return {row.data(NAME, leavebehind.PICK_ROLE): row for row in _rows(dialog)
            if row.data(NAME, leavebehind.PICK_ROLE) is not None}


def _tick(dialog, member, *indices, on=True):
    picks = _picks(dialog)
    state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
    for index in indices:
        picks[(member, index)].setCheckState(NAME, state)


def _accept(dialog):
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)


def _count(dialog, name):
    row = next(r for r in _rows(dialog) if r.text(NAME) == name)
    return row.text(leavebehind.COUNT_COLUMN)


# --- what the window says ----------------------------------------------------

def test_the_heading_and_explanation_are_donalds_words_exactly(app):
    dialog = _dialog()
    assert dialog.ui.heading_label.text() == "Choose what to leave behind"
    assert dialog.ui.explanation_label.text() == (
        "The C64 has 16 item slots per character. A joined scroll becomes "
        "separate scrolls, each taking one slot. Choose items or scrolls to "
        "leave behind until each pack fits.")


def test_no_word_is_written_that_donald_has_not_settled(app):
    """The window's title and the joined scroll's heading are blank, and the
    headers are the Items tab's own."""
    dialog = _dialog()
    assert dialog.windowTitle() == ""
    headings = [r for r in _rows(dialog)
                if r.parent() is not None and r.parent().parent() is None
                and not r.flags() & CHECKABLE and r.childCount()]
    assert headings, "no joined-scroll heading"
    assert {h.text(NAME) for h in headings} == {""}
    header = dialog.tree.headerItem()
    assert [header.text(c) for c in range(4)] == \
        [HEADERS[ITEMS_NAME], HEADERS[ITEMS_QTY], HEADERS[ITEMS_READIED], ""]


def test_the_accept_button_carries_the_callers_label(app):
    assert _accept(_dialog()).text() == ACCEPT


# --- one window, every character who does not fit ------------------------------

def test_one_window_lists_every_character_who_does_not_fit_and_no_other(app):
    dialog = _dialog()
    names = [dialog.tree.topLevelItem(n).text(NAME)
             for n in range(dialog.tree.topLevelItemCount())]
    assert names == ["ALPHA", "GAMMA"]
    assert {member for member, _index in _picks(dialog)} == {0, 2}


def test_each_character_shows_the_slots_still_to_free(app):
    dialog = _dialog()
    assert (_count(dialog, "ALPHA"), _count(dialog, "GAMMA")) == ("1", "2")
    _tick(dialog, 0, 3)
    assert (_count(dialog, "ALPHA"), _count(dialog, "GAMMA")) == ("0", "2")
    _tick(dialog, 2, 1, 2, 3)
    assert _count(dialog, "GAMMA") == "0"
    _tick(dialog, 2, 1, on=False)
    assert _count(dialog, "GAMMA") == "0"
    _tick(dialog, 2, 2, on=False)
    assert _count(dialog, "GAMMA") == "1"


# --- the rows ------------------------------------------------------------------

def test_a_joined_scroll_is_a_heading_nobody_can_tick_or_select(app):
    dialog = _dialog()
    heading = next(r for r in _rows(dialog)
                   if r.parent() is not None and r.parent().parent() is None
                   and r.childCount() and not r.flags() & CHECKABLE)
    assert not heading.flags() & CHECKABLE
    assert not heading.flags() & SELECTABLE
    assert heading.data(NAME, leavebehind.PICK_ROLE) is None
    # Its scrolls sit beneath it and can be ticked and selected.
    scrolls = [heading.child(n) for n in range(heading.childCount())]
    assert len(scrolls) == 2
    for scroll in scrolls:
        assert scroll.flags() & CHECKABLE and scroll.flags() & SELECTABLE


def test_a_scroll_shows_the_spells_it_holds_on_a_quieter_line(app):
    dialog = _dialog()
    picks = _picks(dialog)
    # Item 16 of ALPHA is the second scroll, holding two spells.
    scroll = picks[(0, 16)]
    line = scroll.child(0)
    assert "FIREBALL" in line.text(NAME) and "HASTE" in line.text(NAME)
    assert "SLEEP" not in line.text(NAME)
    assert not line.flags() & CHECKABLE and not line.flags() & SELECTABLE
    assert line.data(NAME, leavebehind.PICK_ROLE) is None
    # The colour is the palette's own quiet one.
    assert line.foreground(NAME).color() == \
        dialog.palette().color(dialog.palette().ColorRole.PlaceholderText)


def test_a_scroll_with_no_spells_and_an_item_that_is_not_a_scroll_have_no_line(
        app):
    party = [_member("ALPHA", 15, _scroll(), _scroll(5))]
    dialog = _dialog(party)
    picks = _picks(dialog)
    assert picks[(0, 15)].childCount() == 0
    assert picks[(0, 0)].childCount() == 0
    assert picks[(0, 16)].childCount() == 1


def test_a_scroll_carried_loose_is_a_row_with_its_spells_too(app):
    """A joined scroll's own scrolls are not the only ones the player can
    leave: a loose scroll shows its spells the same way."""
    char = _member("ALPHA", 15, _scroll(5), _scroll(6))
    char.get("inventory").append(_scroll(7))
    dialog = _dialog([char])
    loose = _picks(dialog)[(0, 17)]
    assert loose.parent().text(NAME) == "ALPHA"
    assert "HASTE" in loose.child(0).text(NAME)


def test_an_item_row_reads_as_it_does_on_the_items_tab(app):
    """Name, quantity and readied come out of `InventoryModel` itself, for an
    item with a quantity and readied and for one with neither."""
    with_both = bytearray(_plain(0))
    with_both[10] = 7                          # quantity
    with_both[6] = items.READIED               # readied
    party = [_member("ALPHA", 15, _scroll(5), _scroll(6))]
    party[0].get("inventory")[0] = bytes(with_both)
    dialog = _dialog(party)

    blocks = [bytes(with_both), _plain(1)] + [bytes(16)] * 14
    model = InventoryModel(Inventory.from_blocks(blocks, ITEM_NAMES))
    for slot in (0, 1):
        row = _picks(dialog)[(0, slot)]
        for theirs, ours in ((leavebehind.NAME_COLUMN, ITEMS_NAME),
                             (leavebehind.QTY_COLUMN, ITEMS_QTY),
                             (leavebehind.READIED_COLUMN, ITEMS_READIED)):
            assert row.text(theirs) == model.data(model.index(slot, ours)), \
                (slot, ours)
    assert _picks(dialog)[(0, 0)].text(leavebehind.QTY_COLUMN) == "7"
    assert _picks(dialog)[(0, 0)].text(leavebehind.READIED_COLUMN) == "Yes"


# --- accepting -------------------------------------------------------------------

def test_accept_waits_for_every_pack_to_fit_and_allows_leaving_more(app):
    dialog = _dialog()
    assert not _accept(dialog).isEnabled()
    _tick(dialog, 0, 3)                       # ALPHA fits, GAMMA does not
    assert not _accept(dialog).isEnabled()
    _tick(dialog, 2, 1, 2)                    # exactly enough for GAMMA
    assert _accept(dialog).isEnabled()
    _tick(dialog, 0, 4, 5, 6)                 # far more than ALPHA needs
    _tick(dialog, 2, 15)
    assert _accept(dialog).isEnabled()
    _tick(dialog, 2, 1, 2, 15, on=False)      # GAMMA short again
    assert not _accept(dialog).isEnabled()


def test_leaving_the_whole_joined_scroll_is_enough(app):
    dialog = _dialog([_member("ALPHA", 15, _scroll(5), _scroll(6))])
    _tick(dialog, 0, 15, 16)
    assert _accept(dialog).isEnabled()


def test_chosen_is_exactly_what_is_ticked_and_leaves_out_an_untouched_member(
        app):
    dialog = _dialog()
    assert dialog.chosen() == {}
    _tick(dialog, 0, 3, 16)
    assert dialog.chosen() == {0: frozenset({3, 16})}
    _tick(dialog, 2, 1, 2)
    _tick(dialog, 0, 3, on=False)
    assert dialog.chosen() == {0: frozenset({16}), 2: frozenset({1, 2})}


@pytest.mark.parametrize("ticks", [
    {},
    {0: (3,)},
    {0: (3,), 2: (1,)},
    {0: (3,), 2: (1, 2)},
    {0: (15, 16), 2: (14, 15)},
    {0: (0, 1, 2), 2: (0, 1, 2, 3, 4)},
    {2: (1, 2)},
])
def test_accept_is_enabled_exactly_when_the_writer_would_take_the_choice(
        app, ticks):
    """The button and `dos_codec.pack_overflow` agree, for whatever is ticked."""
    party = _party()
    dialog = _dialog(party)
    for member, indices in ticks.items():
        _tick(dialog, member, *indices)
    fits = dos_codec.pack_overflow(party, leave=dialog.chosen()) == ()
    assert _accept(dialog).isEnabled() is fits


# --- asking, from the editor ---------------------------------------------------------

def _binding(app, tmp_path):
    from gamedata import synthetic_save
    from support.editorwindow import make_root
    return ew.EditorBinding(make_root(), str(synthetic_save(tmp_path)))


def test_rejecting_the_window_gives_no_choice_and_accepting_gives_the_ticks(
        app, tmp_path, monkeypatch):
    binding = _binding(app, tmp_path)
    overflow = dos_codec.pack_overflow(_party())
    monkeypatch.setattr(binding, "_find_disk", lambda *a, **k: None)
    seen = {}

    def exec_(dialog):
        seen["label"] = _accept(dialog).text()
        _tick(dialog, 0, 3)
        _tick(dialog, 2, 1, 2)
        return seen["result"]

    monkeypatch.setattr(LeaveBehindDialog, "exec", exec_)
    seen["result"] = QDialog.DialogCode.Rejected
    assert binding._choose_left_behind(overflow, GAME, ACCEPT) is None
    seen["result"] = QDialog.DialogCode.Accepted
    assert binding._choose_left_behind(overflow, GAME, ACCEPT) == \
        {0: frozenset({3}), 2: frozenset({1, 2})}
    assert seen["label"] == ACCEPT


# --- the keyboard --------------------------------------------------------------

def _shown(dialog):
    """Put the window up and active, so keys go where a player's would."""
    dialog.show()
    dialog.activateWindow()
    QTest.qWaitForWindowActive(dialog)
    return dialog


def _cancel(dialog):
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel)


def test_tab_reaches_the_buttons_from_the_list(app):
    """Tab leaves the tree and lands on the accept button when it is enabled
    and on Cancel when it is not; a disabled button takes no focus."""
    dialog = _shown(_dialog())
    try:
        dialog.tree.setFocus()
        assert QApplication.focusWidget() is dialog.tree
        assert not _accept(dialog).isEnabled()
        QTest.keyClick(dialog, Qt.Key.Key_Tab)
        assert QApplication.focusWidget() is _cancel(dialog)

        _tick(dialog, 0, 3)
        _tick(dialog, 2, 1, 2)
        assert _accept(dialog).isEnabled()
        dialog.tree.setFocus()
        QTest.keyClick(dialog, Qt.Key.Key_Tab)
        assert QApplication.focusWidget() is _accept(dialog)
        QTest.keyClick(dialog, Qt.Key.Key_Tab)
        assert QApplication.focusWidget() is _cancel(dialog)
    finally:
        dialog.close()


def test_escape_cancels_the_window(app):
    dialog = _shown(_dialog())
    try:
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert not dialog.isVisible()
        assert dialog.chosen() == {}
    finally:
        dialog.close()


def test_enter_accepts_only_when_every_pack_fits(app):
    dialog = _shown(_dialog())
    try:
        dialog.tree.setFocus()
        assert not _accept(dialog).isEnabled()
        QTest.keyClick(dialog, Qt.Key.Key_Return)
        QTest.keyClick(dialog, Qt.Key.Key_Enter)
        assert dialog.isVisible()
        assert dialog.result() != QDialog.DialogCode.Accepted

        _tick(dialog, 0, 3)
        _tick(dialog, 2, 1, 2)
        assert _accept(dialog).isEnabled()
        dialog.tree.setFocus()
        QTest.keyClick(dialog, Qt.Key.Key_Return)
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.chosen() == {0: frozenset({3}), 2: frozenset({1, 2})}
    finally:
        dialog.close()
