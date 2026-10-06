"""The window that asks which items and scrolls stay behind (#432).

Every pack here is composed from the documented item format on neutral
characters and run through `goldbox.dos_codec.pack_overflow`, so the window is
built from what the writer itself reports and no game data is needed. The
spell and item names are made up: the tests are about which rows exist, what
can be ticked and what the window hands back, not about the game's words.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QFont
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


_ordinary, _scroll, _member, _party = (packs.ordinary, packs.scroll, packs.member,
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


def test_the_window_title_joined_heading_and_count_are_donalds_words_exactly(
        app):
    dialog = _dialog()
    assert dialog.windowTitle() == "Choose what to leave behind"
    headings = [r for r in _rows(dialog)
                if r.parent() is not None and r.parent().parent() is None
                and not r.flags() & CHECKABLE and r.childCount()]
    assert headings, "no joined-scroll heading"
    assert {h.text(NAME) for h in headings} == {"Joined scroll"}
    assert dialog.ui.items_remaining_label.text() == "Items still to leave: 3"
    # The number is every character's remaining count together.
    _tick(dialog, 0, 3)
    assert dialog.ui.items_remaining_label.text() == "Items still to leave: 2"
    _tick(dialog, 2, 1, 2)
    assert dialog.ui.items_remaining_label.text() == "Items still to leave: 0"
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


def test_a_pool_trident_gets_no_spells_line_and_a_pool_scroll_still_does(app):
    """Type 0x27 is a scroll in Silver Blades and a trident in Pool of
    Radiance, whose own scrolls are 0x3D; the window reads the title's."""
    pool = c64_port.POOL_OF_RADIANCE
    trident = bytearray(_scroll(5))
    trident[0] = dos_codec.SCROLL_TYPES[0]
    pool_scroll = bytearray(_scroll(6))
    pool_scroll[0] = dos_codec.C64_SCROLL_TYPES[pool.key][0]
    char = _member("ALPHA", 15, _scroll(5), _scroll(6))
    char.get("inventory").extend((bytes(trident), bytes(pool_scroll)))
    dialog = LeaveBehindDialog(dos_codec.pack_overflow([char]), ITEM_NAMES,
                               SPELL_NAMES, for_game(pool), ACCEPT)
    picks = _picks(dialog)
    assert picks[(0, 17)].childCount() == 0
    assert "FIREBALL" in picks[(0, 18)].child(0).text(NAME)


def test_an_item_row_reads_as_it_does_on_the_items_tab(app):
    """Name, quantity and readied come out of `InventoryModel` itself, for an
    item with a quantity and readied and for one with neither."""
    with_both = bytearray(_ordinary(0))
    with_both[10] = 7                          # quantity
    with_both[6] = items.READIED               # readied
    party = [_member("ALPHA", 15, _scroll(5), _scroll(6))]
    party[0].get("inventory")[0] = bytes(with_both)
    dialog = _dialog(party)

    blocks = [bytes(with_both), _ordinary(1)] + [bytes(16)] * 14
    model = InventoryModel(Inventory.from_blocks(blocks, ITEM_NAMES))
    for slot in (0, 1):
        row = _picks(dialog)[(0, slot)]
        for theirs, ours in ((leavebehind.NAME_COLUMN, ITEMS_NAME),
                             (leavebehind.QTY_COLUMN, ITEMS_QTY),
                             (leavebehind.READIED_COLUMN, ITEMS_READIED)):
            # The table draws the higher of the two filled slots first.
            assert row.text(theirs) == model.data(
                model.index(1 - slot, ours)), \
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


def _row_texts_asked_for(binding, monkeypatch, **kwargs):
    """The texts of every row of the window `_choose_left_behind` opens."""
    seen = []

    def exec_(dialog):
        seen.extend(r.text(NAME) for r in _rows(dialog))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(LeaveBehindDialog, "exec", exec_)
    overflow = dos_codec.pack_overflow(_party())
    binding._choose_left_behind(overflow, GAME, ACCEPT, **kwargs)
    return seen


def _port_readers(monkeypatch, folder, items, spells=None):
    """Make `folder` the only place a DOS reader finds names, and a folder
    of the title."""
    monkeypatch.setattr(ew.titles, "dos_folder_title", lambda f: GAME.key)
    def dos_items(where):
        if str(where) != str(folder):
            raise FileNotFoundError(where)
        return items

    def dos_spells(where, game):
        if str(where) != str(folder) or spells is None:
            raise FileNotFoundError(where)
        return spells

    def no_amiga(where, game):
        raise FileNotFoundError(where)

    monkeypatch.setattr(ew.port_item_names, "load_dos_item_names", dos_items)
    monkeypatch.setattr(ew.port_spell_names, "load_dos_spell_names",
                        dos_spells)
    monkeypatch.setattr(ew.port_item_names, "load_amiga_item_names", no_amiga)
    monkeypatch.setattr(ew.port_spell_names, "load_amiga_spell_names",
                        no_amiga)


def test_without_c64_disks_the_rows_take_names_from_the_dos_game_folder(
        app, tmp_path, monkeypatch):
    binding = _binding(app, tmp_path)
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    binding.disks = str(game_dir)
    monkeypatch.setattr(binding, "_find_disk", lambda *a, **k: None)
    _port_readers(monkeypatch, game_dir, ITEM_NAMES, SPELL_NAMES)
    texts = _row_texts_asked_for(binding, monkeypatch)
    assert "WAND" in texts
    assert not [t for t in texts if t.startswith("word ")]


def test_without_c64_disks_the_rows_take_names_from_the_save_as_amiga_disks(
        app, tmp_path, monkeypatch):
    from types import SimpleNamespace
    binding = _binding(app, tmp_path)
    monkeypatch.setattr(binding, "_find_disk", lambda *a, **k: None)
    disk = tmp_path / "disk.adf"
    asked = []

    def amiga_items(where, game):
        asked.append(where)
        return ITEM_NAMES

    def never(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(ew.port_item_names, "load_amiga_item_names",
                        amiga_items)
    monkeypatch.setattr(ew.port_spell_names, "load_amiga_spell_names", never)
    monkeypatch.setattr(ew.port_item_names, "load_dos_item_names", never)
    monkeypatch.setattr(ew.port_spell_names, "load_dos_spell_names", never)
    assets = SimpleNamespace(dos_folder=None, amiga_disk=disk,
                             amiga_disk_one=None)
    texts = _row_texts_asked_for(binding, monkeypatch, assets=assets)
    assert asked[0] == [disk]
    assert "WAND" in texts


def test_c64_names_win_over_the_dos_folder_when_a_c64_disk_gives_them(
        app, tmp_path, monkeypatch):
    binding = _binding(app, tmp_path)
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    binding.disks = str(game_dir)
    monkeypatch.setattr(binding, "_find_disk", lambda *a, **k: "a.d64")
    monkeypatch.setattr(ew, "load_item_names",
                        lambda disk, game: {1: "C64WAND", 2: "C64MAGE",
                                            3: "C64SCROLL", 4: "C64STAFF"})
    monkeypatch.setattr(ew, "load_spell_names",
                        lambda disk, game: {5: "C64SLEEP", 6: "C64BALL",
                                            7: "C64HASTE"})
    _port_readers(monkeypatch, game_dir, ITEM_NAMES, SPELL_NAMES)
    texts = _row_texts_asked_for(binding, monkeypatch)
    assert "C64WAND" in texts
    assert "WAND" not in texts


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


# --- running effects -------------------------------------------------------------
#
# The second mode: the C64's 64 effect rows are the whole party's, so one count
# for the party, one row per effect with repeats, and no word Donald has not
# settled.

def _overflow(per_member=(11, 11), ids=None, over=None):
    entries = tuple(
        dos_codec.EffectEntry(member, index,
                              (ids or {}).get((member, index), 1), 6)
        for member, held in enumerate(per_member) for index in range(held))
    limit = 64
    needed = limit + (over if over is not None else 2)
    return dos_codec.EffectOverflow(
        limit, needed, tuple(f"MEMBER{n}" for n in range(len(per_member))),
        entries)


def _effects_dialog(overflow=None, accept=ACCEPT):
    return LeaveBehindDialog((), None, None, for_game(c64_port.POOL_OF_RADIANCE),
                             accept, effects=overflow or _overflow(),
                             game=c64_port.POOL_OF_RADIANCE)


def test_effects_mode_writes_only_the_words_donald_approved(app):
    from editor import activeeffects
    dialog = _effects_dialog()
    assert dialog.ui.heading_label.text() == "Choose what to leave behind"
    assert dialog.ui.explanation_label.text() == (
        "The C64 save has room for 64 running effects. "
        "Choose at least 2 to leave behind.")
    assert dialog.windowTitle() == "Choose what to leave behind"
    header = dialog.tree.headerItem()
    assert [header.text(c) for c in range(4)] == [
        activeeffects.HEADER_EFFECT, "", "", ""]
    assert _accept(dialog).text() == ACCEPT
    # No duration is shown on an effect row.
    for row in _picks(dialog).values():
        assert [row.text(c) for c in (1, 2, 3)] == ["", "", ""]


def test_the_explanation_names_the_rows_the_window_opened_short(app):
    one = _effects_dialog(_overflow(over=1))
    assert one.ui.explanation_label.text() == (
        "The C64 save has room for 64 running effects. "
        "Choose at least 1 to leave behind.")
    assert one.ui.remaining_label.text() == "1 more to leave behind"
    # Ticking does not change what the window opened short by.
    _tick(one, 0, 0)
    assert one.ui.explanation_label.text().endswith(
        "Choose at least 1 to leave behind.")
    assert one.ui.remaining_label.text() == "0 more to leave behind"


def test_effects_mode_hides_the_columns_with_no_text_and_items_mode_shows_them(
        app):
    effects = _effects_dialog()
    hidden = {c: effects.tree.isColumnHidden(c) for c in range(4)}
    assert hidden == {leavebehind.NAME_COLUMN: False,
                      leavebehind.QTY_COLUMN: True,
                      leavebehind.READIED_COLUMN: True,
                      leavebehind.COUNT_COLUMN: True}
    items = _dialog()
    assert not any(items.tree.isColumnHidden(c) for c in range(4))


def test_effects_mode_has_one_row_per_effect_repeats_included(app):
    from editor import activeeffects
    dialog = _effects_dialog(_overflow((11, 3), ids={(1, 2): 200}))
    picks = _picks(dialog)
    assert sorted(picks) == [(0, n) for n in range(11)] + [(1, n)
                                                           for n in range(3)]
    assert all(picks[(0, n)].text(NAME) == activeeffects.label(
        1, c64_port.POOL_OF_RADIANCE) for n in range(11))
    assert picks[(1, 2)].text(NAME) == activeeffects.UNNAMED_EFFECT
    top = [dialog.tree.topLevelItem(n).text(NAME)
           for n in range(dialog.tree.topLevelItemCount())]
    assert top == ["MEMBER0", "MEMBER1"]
    assert all(r.flags() & CHECKABLE for r in picks.values())


def test_a_member_with_nothing_to_leave_out_has_no_row(app):
    dialog = _effects_dialog(_overflow((0, 3)))
    assert dialog.tree.topLevelItemCount() == 1
    assert dialog.tree.topLevelItem(0).text(NAME) == "MEMBER1"


def test_effects_accept_waits_for_the_party_count_and_allows_more(app):
    dialog = _effects_dialog()
    assert dialog.ui.remaining_label.text() == "2 more to leave behind"
    assert not _accept(dialog).isEnabled()
    _tick(dialog, 0, 0)
    assert dialog.ui.remaining_label.text() == "1 more to leave behind"
    assert not _accept(dialog).isEnabled()
    # The count is the party's: a tick on another member counts.
    _tick(dialog, 1, 4)
    assert dialog.ui.remaining_label.text() == "0 more to leave behind"
    assert _accept(dialog).isEnabled()
    _tick(dialog, 1, 5)
    assert dialog.ui.remaining_label.text() == "0 more to leave behind"
    assert _accept(dialog).isEnabled()
    _tick(dialog, 1, 5, on=False)
    _tick(dialog, 1, 4, on=False)
    assert not _accept(dialog).isEnabled()


def test_pack_mode_shows_the_item_count_and_effects_mode_its_own_count(app):
    dialog = _dialog()
    assert dialog.ui.items_remaining_label.isVisibleTo(dialog)
    assert not dialog.ui.remaining_label.isVisibleTo(dialog)
    effects = _effects_dialog()
    assert effects.ui.remaining_label.isVisibleTo(effects)
    assert not effects.ui.items_remaining_label.isVisibleTo(effects)


@pytest.mark.parametrize("offset", range(0, 11))
def test_the_item_count_shares_a_row_with_the_buttons_aligned_left(app, offset):
    """The count is level with Convert and Cancel, to their left, at the
    window's left edge, below the list, at every font a person uses."""
    base = app.font()
    bigger = QFont(base)
    bigger.setPointSizeF(base.pointSizeF() + offset)
    app.setFont(bigger)
    try:
        dialog = _dialog()
        dialog.show()
        app.processEvents()
        label = dialog.ui.items_remaining_label
        label_box = QRect(label.mapTo(dialog, QPoint(0, 0)), label.size())
        buttons = dialog.buttons
        buttons_box = QRect(buttons.mapTo(dialog, QPoint(0, 0)), buttons.size())
        tree = dialog.tree
        tree_box = QRect(tree.mapTo(dialog, QPoint(0, 0)), tree.size())
        assert label.alignment() & Qt.AlignmentFlag.AlignLeft
        margin = dialog.layout().contentsMargins().left()
        assert label_box.left() == margin
        assert label_box.right() < buttons_box.left()
        assert label_box.top() < buttons_box.bottom()
        assert buttons_box.top() < label_box.bottom()
        assert label_box.top() >= tree_box.bottom()
        # Its words fit whole.
        assert label_box.width() >= label.fontMetrics().horizontalAdvance(
            label.text())
        dialog.close()
    finally:
        app.setFont(base)


def test_chosen_effects_is_exactly_what_is_ticked(app):
    dialog = _effects_dialog(_overflow((11, 11, 11), over=3))
    assert dialog.chosen_effects() == {}
    _tick(dialog, 0, 0, 7)
    _tick(dialog, 2, 10)
    _tick(dialog, 0, 7, on=False)
    assert dialog.chosen_effects() == {0: frozenset({0}), 2: frozenset({10})}


def test_the_editor_asks_for_effects_and_returns_the_ticks(
        app, tmp_path, monkeypatch):
    binding = _binding(app, tmp_path)
    seen = {}

    def exec_(dialog):
        seen["label"] = _accept(dialog).text()
        _tick(dialog, 0, 3)
        _tick(dialog, 1, 1)
        return seen["result"]

    monkeypatch.setattr(LeaveBehindDialog, "exec", exec_)
    overflow = _overflow()
    seen["result"] = QDialog.DialogCode.Rejected
    assert binding._choose_effects_left(
        overflow, c64_port.POOL_OF_RADIANCE, ACCEPT) is None
    seen["result"] = QDialog.DialogCode.Accepted
    assert binding._choose_effects_left(
        overflow, c64_port.POOL_OF_RADIANCE, ACCEPT) == {
        0: frozenset({3}), 1: frozenset({1})}
    assert seen["label"] == ACCEPT


# --- a limit the whole party shares (the Amiga's joined scrolls) ---------------

def _party_overflow():
    """Specimen L's pack for one member and a second member with a joined
    scroll of two and loose items: 122 scrolls, no unjoin reaches 120."""
    inventory, bundles = packs.specimen_l_pack()
    other = packs.member("OTHER", 2, packs.scroll(5), packs.scroll(6))
    first = packs.member("PAINE", 0)
    first.set("inventory", inventory, "made up")
    first.set("scroll_bundles", bundles, "made up")
    (over,) = dos_codec.pack_overflow([first, other], "amiga")
    return over


def _party_dialog():
    return LeaveBehindDialog((_party_overflow(),), ITEM_NAMES, SPELL_NAMES,
                             for_game(GAME), ACCEPT)


def test_a_party_wide_overflow_reuses_the_approved_words_and_hides_the_c64_explanation(app):
    dialog = _party_dialog()
    assert dialog.windowTitle() == "Choose what to leave behind"
    assert dialog.ui.explanation_label.isHidden()
    assert dialog.ui.items_remaining_label.text() == "Items still to leave: 1"
    assert {r.text(NAME) for r in _rows(dialog) if r.childCount()
            and r.parent() is not None and not r.flags() & CHECKABLE} \
        == {"Joined scroll"}
    names = [dialog.tree.topLevelItem(n).text(NAME)
             for n in range(dialog.tree.topLevelItemCount())]
    assert names == ["PAINE", "OTHER"]


def test_the_party_count_falls_when_an_ordinary_item_frees_the_row_for_an_unjoin(app):
    dialog = _party_dialog()
    assert not _accept(dialog).isEnabled()
    _tick(dialog, 0, 124)
    assert dialog.ui.items_remaining_label.text() == "Items still to leave: 0"
    assert _accept(dialog).isEnabled()
    assert dialog.chosen() == {0: frozenset({124})}
    _tick(dialog, 0, 124, on=False)
    assert not _accept(dialog).isEnabled()
    assert dialog.chosen() == {}


# --- names for the Convert window and the readers' failures ------------------

def test_convert_asks_with_the_dialogs_own_dos_folder_and_amiga_disk(
        app, tmp_path, monkeypatch):
    """No C64 disk and nothing in Preferences: the Convert dialog's own
    rows name the items."""
    from types import SimpleNamespace
    binding = _binding(app, tmp_path)
    monkeypatch.setattr(binding, "_find_disk", lambda *a, **k: None)
    binding.disks = None
    game_dir = tmp_path / "picked"
    game_dir.mkdir()
    _port_readers(monkeypatch, game_dir, ITEM_NAMES, SPELL_NAMES)
    assets = SimpleNamespace(dos_folder=game_dir, amiga_disk=None,
                             amiga_disk_one=None)
    source = SimpleNamespace(path=tmp_path / "elsewhere" / "SAVE")
    assert "WAND" not in _row_texts_asked_for(binding, monkeypatch)
    texts = _row_texts_asked_for(binding, monkeypatch, source=source,
                                 assets=assets)
    assert "WAND" in texts


def test_a_dos_folder_of_another_title_names_nothing(
        app, tmp_path, monkeypatch):
    binding = _binding(app, tmp_path)
    monkeypatch.setattr(binding, "_find_disk", lambda *a, **k: None)
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    binding.disks = str(game_dir)
    _port_readers(monkeypatch, game_dir, ITEM_NAMES, SPELL_NAMES)
    monkeypatch.setattr(ew.titles, "dos_folder_title", lambda f: "other")
    assert "WAND" not in _row_texts_asked_for(binding, monkeypatch)
    monkeypatch.setattr(ew.titles, "dos_folder_title", lambda f: GAME.key)
    assert "WAND" in _row_texts_asked_for(binding, monkeypatch)


def test_a_guessed_folder_that_cannot_be_identified_is_skipped(
        app, tmp_path, monkeypatch):
    binding = _binding(app, tmp_path)
    monkeypatch.setattr(binding, "_find_disk", lambda *a, **k: None)
    bad = tmp_path / "loop"
    bad.mkdir()
    binding.disks = str(bad)
    good = ew.files.source_folder(binding.path)
    _port_readers(monkeypatch, good, ITEM_NAMES, SPELL_NAMES)

    def title(folder):
        if folder == bad:
            raise RuntimeError("Symlink loop from " + str(folder))
        return GAME.key

    monkeypatch.setattr(ew.titles, "dos_folder_title", title)
    assert "WAND" in _row_texts_asked_for(binding, monkeypatch)


def test_a_reader_failure_is_a_warning_and_a_missing_file_is_not(
        app, tmp_path, monkeypatch, caplog):
    import logging
    binding = _binding(app, tmp_path)
    monkeypatch.setattr(binding, "_find_disk", lambda *a, **k: None)
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    binding.disks = str(game_dir)

    def broken(where, *a):
        raise ew.port_item_names.ItemNameError("table is empty")

    _port_readers(monkeypatch, game_dir, ITEM_NAMES)
    monkeypatch.setattr(ew.port_item_names, "load_dos_item_names", broken)
    with caplog.at_level(logging.DEBUG, logger=ew._log.name):
        _row_texts_asked_for(binding, monkeypatch)
    warned = [r.getMessage() for r in caplog.records
              if r.levelno == logging.WARNING and "names off" in r.getMessage()]
    assert warned and "table is empty" in warned[0]

    def missing(where, *a):
        raise FileNotFoundError(where)

    caplog.clear()
    monkeypatch.setattr(ew.port_item_names, "load_dos_item_names", missing)
    with caplog.at_level(logging.DEBUG, logger=ew._log.name):
        _row_texts_asked_for(binding, monkeypatch)
    assert not [r for r in caplog.records
                if r.levelno >= logging.WARNING
                and "names off" in r.getMessage()]
