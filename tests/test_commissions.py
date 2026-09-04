
def make_root():
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root

"""The City Council's books: the decoder, and the panel that draws it.

Most of this runs on flag blocks built here, byte by byte, because the states
worth testing -- a reward waiting, a summons outstanding -- are three bytes of
our own making. The two specimen saves are the end-to-end check: the shipped
unplayed disk must produce exactly the three commissions the real game opens
with, and a far-advanced save must produce a coherent late game.
"""

import os
import pathlib

import pytest
from gamedata import game_file

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from goldbox import commissions as book  # noqa: E402
from goldbox.commissions import DONE, LEDGER_BASE, PAID_VALUE  # noqa: E402
from goldbox.savegame import SAVE0_SIZE, SaveGame0  # noqa: E402

# A far-advanced save, kept out of the repository like every other game file.
# No disk on this machine holds it, including every PORSAVE* the player has
# today -- all of them read as completed == 0, the shipped-unplayed state, so
# this state is not merely unlocated but genuinely unplayed by anyone yet
# (#211). It takes a session that reaches six City Hall commissions paid and
# the endgame quests offered, not a tool: nothing short of playing that far
# and visiting City Hall produces it.
ADVANCED = pathlib.Path("work/fields/npc_party.d64")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def blank() -> bytearray:
    """224 flag bytes, all zero: a party that has never been to the City Hall."""
    return bytearray(book.FLAGS_SIZE)


def put(flags: bytearray, address: int, value: int) -> bytearray:
    flags[address - book.FLAGS_BASE] = value
    return flags


def put_ledger(flags: bytearray, index: int, value: int) -> bytearray:
    return put(flags, LEDGER_BASE + index, value)


def advanced_save() -> bytes:
    if not ADVANCED.exists():
        pytest.skip(
            f"needs {ADVANCED}: a save with six City Hall commissions paid "
            "and the endgame quests offered -- only a session played that "
            "far and saved there can produce it")
    from goldbox.d64 import load_payload
    return load_payload(str(ADVANCED), b"SAVEDGAME0")


# --- the flag block ---------------------------------------------------------

def test_the_flag_block_comes_out_of_any_container_it_arrives_in():
    want = bytes(put_ledger(blank(), 1, PAID_VALUE))
    payload = bytearray(SAVE0_SIZE)
    payload[book.FLAGS_BASE - 0x4900:book.FLAGS_END - 0x4900] = want
    page = payload[0x4A00 - 0x4900:0x4B00 - 0x4900]
    for source in (want, bytearray(want), page, bytes(payload),
                   SaveGame0.from_bytes(bytes(payload))):
        assert book.flags(source).to_bytes() == want


def test_a_block_of_the_wrong_length_is_refused():
    with pytest.raises(ValueError):
        book.flags(b"\0" * 12)


def test_reading_copies_and_never_writes_back():
    flags = blank()
    put_ledger(flags, 1, DONE)
    before = bytes(flags)
    state = book.read(flags)
    assert state.reward_waiting[0].index == 1
    assert bytes(flags) == before
    # The block the reader keeps is its own: mutating the caller's array must
    # not reach it.
    held = book.flags(flags)
    flags[0] = 0xFF
    assert held.to_bytes()[0] == 0


# --- the ledger -------------------------------------------------------------

def test_the_ledger_has_the_clerk_s_twenty_six_entries():
    entries = book.ledger(blank())
    assert len(entries) == book.LEDGER_COUNT
    assert [e.address for e in entries][:2] == [0x4AA6, 0x4AA7]
    assert entries[1].name == "Sokal Keep cleared"
    assert entries[20].source == "Valjevo Castle (ECL07)"


def test_the_unnamed_entry_shows_its_index_rather_than_an_invented_name():
    # Index 22's handler in the clerk's speech table is a bare RETURN.
    assert book.ledger_name(22) == "ledger entry 22"
    assert book.LEDGER[22] == (None, None)


def test_the_three_states_are_the_three_values_the_scripts_write():
    flags = blank()
    put_ledger(flags, 0, DONE)
    put_ledger(flags, 1, PAID_VALUE)
    put_ledger(flags, 21, 3)            # an area script's own progress marker
    state = book.read(flags)
    assert [e.index for e in state.reward_waiting] == [0]
    assert [e.index for e in state.paid] == [1]
    assert [(e.index, e.value) for e in state.in_progress] == [(21, 3)]
    assert book.ledger(flags)[2].state == book.NOT_DONE


def test_ten_entries_count_towards_commissions_completed():
    major = [e.index for e in book.ledger(blank()) if e.major]
    assert major == [0, 1, 10, 11, 12, 13, 15, 16, 17, 21]


def test_commissions_completed_is_the_byte_at_4ac1():
    assert book.read(put(blank(), 0x4AC1, 7)).completed == 7


# --- the offer board --------------------------------------------------------

def test_a_party_that_has_done_nothing_is_offered_the_game_s_opening_three():
    assert [o.text for o in book.offered(blank())] == [
        "clear the slums", "clear Sokal Keep",
        "bring back books, maps and tomes"]


def test_the_clerk_offers_at_most_three_per_visit():
    assert len(book.offered(blank())) == book.OFFER_LIMIT
    assert len(book.offered(blank(), limit=16)) > book.OFFER_LIMIT


def test_paying_for_a_job_takes_it_off_the_board():
    flags = blank()
    put_ledger(flags, 21, PAID_VALUE)             # slums paid
    put_ledger(flags, 1, PAID_VALUE)              # Sokal Keep paid
    texts = [o.text for o in book.offered(flags, limit=16)]
    assert "Clear the Slums" not in texts
    assert "clear Sokal Keep" not in texts
    # Sokal Keep paid is what unlocks Kovel Mansion and the Bishop.
    assert "clean out Kovel Mansion" in texts
    assert "report to the Bishop of Tyr" in texts


def test_the_withdrawn_candidate_is_never_offered():
    for limit in (3, 16):
        assert all(o.order != 9 for o in book.offered(blank(), limit=limit))


def test_every_offer_settles_a_quest_the_clerk_s_speech_table_names():
    for offer in book.BOARD:
        if offer.order == 9:
            continue                    # withdrawn; it settles nothing
        assert offer.ledger
        for index in offer.ledger:
            assert book.LEDGER[index][0], f"offer {offer.order} names index {index}"


def test_the_late_game_offers_need_cadorna_exposed_and_the_gate_taken():
    flags = blank()
    put(flags, 0x4ABE, DONE)                      # Cadorna exposed
    assert "Lord Urslingen: take Stojanow Gate" in [
        o.text for o in book.offered(flags, limit=16)]
    put_ledger(flags, 19, PAID_VALUE)             # the gate is taken and paid
    assert "the special council meeting" in [
        o.text for o in book.offered(flags, limit=16)]


# --- appointments -----------------------------------------------------------

def test_a_summons_is_outstanding_at_254_and_finished_at_255():
    flags = put(blank(), 0x4A9B, DONE)
    summons = {a.address: a for a in book.appointments(flags)}
    assert summons[0x4A9B].state == "summoned"
    assert summons[0x4A9B].outstanding
    put(flags, 0x4A9B, PAID_VALUE)
    after = {a.address: a for a in book.appointments(flags)}
    assert after[0x4A9B].state == "done"
    assert not after[0x4A9B].outstanding


def test_the_finished_book_bounty_is_not_an_outstanding_appointment():
    flags = put(blank(), 0x4AC2, PAID_VALUE)
    state = book.read(flags)
    assert 0x4AC2 not in [a.address for a in state.outstanding]


def test_nothing_is_outstanding_on_an_untouched_block():
    assert book.read(blank()).outstanding == ()


# --- the two specimens ------------------------------------------------------

def test_the_shipped_unplayed_save_opens_with_slums_sokal_keep_and_books():
    state = book.read(game_file("SAVEDGAME0"))
    assert state.completed == 0
    assert state.reward_waiting == () and state.paid == ()
    assert state.in_progress == () and state.outstanding == ()
    assert [o.text for o in state.offers] == [
        "clear the slums", "clear Sokal Keep",
        "bring back books, maps and tomes"]


def test_a_far_advanced_save_reads_as_a_coherent_late_game():
    state = book.read(advanced_save())
    assert state.completed == 6
    assert [e.index for e in state.paid] == [0, 1, 2, 4, 5, 6, 7, 8, 9, 10,
                                             12, 13, 20, 21]
    # Six of the fourteen paid entries are the ones that bump $4AC1, which is
    # what $4AC1 reads. The arithmetic closes.
    assert len([e for e in state.paid if e.major]) == state.completed
    assert [o.text for o in state.offers] == [
        "stop the nomads", "stop the kobolds", "stop the lizardmen"]


def test_reading_a_save_leaves_its_bytes_alone():
    payload = advanced_save()
    before = bytes(payload)
    book.read(payload)
    book.summary_lines(payload)
    assert payload == before
    assert advanced_save() == before


def test_the_summary_prints_the_lines_the_panel_shows():
    lines = book.summary_lines(game_file("SAVEDGAME0"))
    assert lines[0] == "Quests completed: 0"
    assert "  clear Sokal Keep" in lines


# --- the panel --------------------------------------------------------------

SLUMS = {"Clear the Slums", "Slums cleared"}   # the panel capitalises


def panel_for(app, flags):
    from automap.questlog import QuestLogPanel
    panel = QuestLogPanel(make_root())
    panel.update_from(flags)
    return panel


def rows(panel, group="commissions"):
    """(name, state, sub-line) for every row the group is actually drawing."""
    g = panel.groups[group]
    return [(r.what.text(), r.state.text(), r.note.text())
            for r in g.visible_rows()]


def tips(panel, group="commissions"):
    return [r.toolTip() for r in panel.groups[group].visible_rows()]


@pytest.mark.parametrize("value, state", [
    (0, "offered"),                     # the clerk has it on the board
    (3, "In progress"),                 # the slums' own progress marker
    (DONE, "reward waiting"),
    (PAID_VALUE, "paid"),
])
def test_the_slums_is_one_row_whatever_its_byte_reads(app, value, state):
    """One byte, one row. The board gates candidate 0 on ledger 21 and the
    clerk pays on the same byte; showing the two ends separately made one
    commission look like two, which is the whole reason for this shape."""
    panel = panel_for(app, put_ledger(blank(), 21, value))
    slums = [r for r in rows(panel) if r[0] in SLUMS]
    assert len(slums) == 1
    assert slums[0][1] == state


def test_no_unfinished_row_is_labelled_with_the_clerk_s_completion_speech(app):
    for value in (0, 3):
        panel = panel_for(app, put_ledger(blank(), 21, value))
        assert "Slums cleared" not in [r[0] for r in rows(panel)]
    for value in (DONE, PAID_VALUE):
        panel = panel_for(app, put_ledger(blank(), 21, value))
        assert "Slums cleared" in [r[0] for r in rows(panel)]


def test_a_commission_the_board_never_offers_still_gets_a_neutral_name(app):
    # Ledger 11's only words from the clerk are "Graveyard menace ended".
    panel = panel_for(app, put_ledger(blank(), 11, 2))
    assert ("The graveyard menace", "In progress", "") in rows(panel)


def test_the_marker_value_is_never_the_state_word(app):
    panel = panel_for(app, put_ledger(blank(), 21, 4))
    assert not any("4" in r[1] or "marker" in r[1].lower() for r in rows(panel))


def test_the_slums_tooltip_is_one_sentence_and_nothing_else(app):
    """Donald, 2026-08, with the wording: the row's own number is the only
    thing this tooltip has to settle, and the rest was noise."""
    panel = panel_for(app, put_ledger(blank(), 21, 4))
    slums = [r for r in rows(panel) if r[0] in SLUMS][0]
    assert dict(zip([r[0] for r in rows(panel)], tips(panel)))[slums[0]] == (
        "Counts every fight won in the Slums: 10 set encounters and "
        "15 wandering.")


def test_every_other_row_keeps_its_ledger_and_its_board_candidate(app):
    panel = panel_for(app, put_ledger(blank(), 12, 4))
    tip = [t for t in tips(panel) if t.startswith("clean out Kovel Mansion")][0]
    assert "Ledger 12 = 4" in tip
    assert "$4AB2" not in tip, "a player is being shown a memory address"
    assert "candidate 6 on the clerk's board" in tip
    assert "$A84D" not in tip and "ECL08" not in tip, (
        "a player is being shown an address and a script filename")
    assert 'the clerk pays for it as "Kovel Mansion thieves"' in tip


def test_the_six_library_books_are_one_row_that_says_how_many_are_in(app):
    flags = blank()
    for index in (4, 5, 6):
        put_ledger(flags, index, PAID_VALUE)
    panel = panel_for(app, flags)
    books = [r for r in rows(panel) if r[0].startswith("Bring back books")]
    assert books == [("Bring back books, maps and tomes", "In progress",
                      "3 of 6 books recovered")]
    tip = [t for t in tips(panel) if t.startswith("bring back books")][0]
    for index in range(4, 10):
        assert f"Ledger {index} =" in tip
        assert f"${LEDGER_BASE + index:04X}" not in tip, (
            "a player is being shown a memory address")
    # Its gate is not the six entries, and the tooltip says which byte it is.
    assert "gated on the book bounty" in tip
    assert "$4AC2" not in tip, "a player is being shown a memory address"


def test_all_six_books_paid_is_one_paid_row_with_no_count(app):
    flags = blank()
    for index in range(4, 10):
        put_ledger(flags, index, PAID_VALUE)
    panel = panel_for(app, flags)
    assert [r for r in rows(panel) if "books" in r[0]] == [
        ("Bring back books, maps and tomes", "paid", "")]


def test_a_party_that_has_done_nothing_sees_the_opening_three(app):
    panel = panel_for(app, blank())
    assert panel.completed.text() == "Quests completed: 0"
    assert rows(panel) == [
        ("Clear Sokal Keep", "offered", ""),
        ("Bring back books, maps and tomes", "offered", ""),
        ("Clear the Slums", "offered", "")]


def test_a_commission_the_party_has_not_met_is_not_shown(app):
    # The clerk offers three a visit; the rest of the open gates are not the
    # party's business yet, and the tooltip of a shown row says so.
    panel = panel_for(app, blank())
    assert all("nomads" not in r[0] for r in rows(panel))


def test_the_rows_run_in_the_ledger_s_order_which_is_roughly_the_plot_s(app):
    flags = blank()
    put_ledger(flags, 11, DONE)                   # graveyard, money uncollected
    put_ledger(flags, 1, PAID_VALUE)
    put_ledger(flags, 10, PAID_VALUE)
    panel = panel_for(app, flags)
    assert [r[0] for r in rows(panel) if r[1] != "offered"] == [
        "Sokal Keep cleared", "Podal Plaza auction", "Graveyard menace ended"]
    assert [r[1] for r in rows(panel) if r[0] == "Graveyard menace ended"] == [
        "reward waiting"]


def test_a_paid_row_is_drawn_muted_so_live_work_stands_out(app):
    panel = panel_for(app, put_ledger(blank(), 1, PAID_VALUE))
    drawn = {r.what.text(): bool(r.what.styleSheet())
             for r in panel.groups["commissions"].visible_rows()}
    assert drawn["Sokal Keep cleared"]
    assert not drawn["Clear the Slums"]


def test_the_panel_lists_an_outstanding_summons(app):
    panel = panel_for(app, put(blank(), 0x4A97, DONE))
    group = panel.groups["summons"]
    assert group.isVisibleTo(panel.root)
    row = group.visible_rows()[0]
    assert row.what.text() == "Councilman Cadorna's chambers"
    assert row.state.text() == "summoned"


def test_the_panel_hides_the_summonses_when_there_are_none(app):
    panel = panel_for(app, blank())
    assert not panel.groups["summons"].isVisibleTo(panel.root)


def test_the_panel_takes_a_whole_savedgame0(app):
    from automap.questlog import QuestLogPanel
    panel = QuestLogPanel(make_root())
    payload = game_file("SAVEDGAME0")
    before = bytes(payload)
    panel.update_from(payload)
    panel.update_from(SaveGame0.from_bytes(payload))
    assert payload == before
    assert "Clear the Slums" in [r[0] for r in rows(panel)]


def test_a_far_advanced_save_draws_one_row_for_each_commission(app):
    panel = panel_for(app, advanced_save())
    names = [r[0] for r in rows(panel)]
    assert len(names) == len(set(names))
    assert len([n for n in names if n in SLUMS]) == 1
    assert "Slums cleared" in names
    assert ("Bring back books, maps and tomes", "paid", "") in rows(panel)


def test_nothing_in_the_panel_is_editable(app):
    from PyQt6.QtWidgets import (
        QAbstractButton,
        QAbstractSpinBox,
        QComboBox,
        QLineEdit,
        QTextEdit,
    )

    flags = put_ledger(put_ledger(blank(), 1, PAID_VALUE), 11, DONE)
    panel = panel_for(app, put(flags, 0x4A97, DONE))
    for kind in (QLineEdit, QTextEdit, QComboBox, QAbstractSpinBox,
                 QAbstractButton):
        assert panel.findChildren(kind) == []


def test_the_panel_says_so_before_it_has_any_bytes(app):
    from automap.questlog import QuestLogPanel
    panel = QuestLogPanel(make_root())
    assert panel.heading.text() == "Quest Log - waiting for a game"
    panel.update_from(blank())
    assert panel.heading.text() == "Quest Log"


def test_every_board_candidate_and_ledger_entry_is_in_exactly_one_row():
    from automap.questlog import COMMISSIONS
    seen = [i for c in COMMISSIONS for i in c.ledger]
    assert sorted(seen) == list(range(book.LEDGER_COUNT))
    orders = [c.order for c in COMMISSIONS if c.order is not None]
    assert sorted(orders) == [o.order for o in book.BOARD if o.ledger]


def test_the_slums_says_how_many_encounters_are_cleared(app):
    """`marker 4` used to be the whole story a player got. `$4ABB` counts slum
    encounters cleared, of 25 -- `docs/134-commissions.md`."""
    flags = bytearray(book.FLAGS_SIZE)
    flags[book.LEDGER_BASE - book.FLAGS_BASE + 21] = 4
    from automap.questlog import commission_rows
    rows = [r for r in commission_rows(bytes(flags)) if r[0] == "Clear the Slums"]
    assert len(rows) == 1
    assert rows[0][3] == "4 of 25 encounters cleared"
    assert "marker" not in rows[0][0] and "marker" not in rows[0][3]
    # The 25 is set and wandering fights together. A PC walkthrough quotes 15,
    # which is `$4A80`'s cap on the wandering half, and a reader who has seen
    # it needs the tooltip to say which number this row is.
    assert "10 set encounters and 15 wandering" in rows[0][2]


def test_no_quest_log_tooltip_shows_a_memory_address():
    """Donald, 2026-08-31: *"we shouldn't be presenting memory addresses to
    players"* -- of the tooltip that read `$4AC1, bumped by the clerk for the
    ten commissions that count as major`.

    Every string this panel builds goes into a tooltip or a visible column, so
    a `$XXXX` anywhere in one is a developer's note that reached a player. The
    addresses themselves have not gone anywhere: `goldbox/commissions.py` is
    the authority for them and its docstrings still carry them, which is where
    somebody reading the code will look.
    """
    import re

    from automap import questlog

    address = re.compile(r"\$[0-9A-F]{4}\b")
    shown = [*questlog.GATE_NOTES.values(), *questlog.TOOLTIPS.values()]
    for text in shown:
        assert not address.search(text), f"a memory address reaches a player: {text!r}"


# --- side quests, #158, behind WISH_EXPERIMENTAL_QUESTS ---------------------

def _flags_4a81(value) -> bytearray:
    return put(blank(), 0x4A81, value)


def _page_4a04(value) -> bytearray:
    """A full `$4A00` page -- scratch and flags both -- with only `$4A04` set."""
    page = bytearray(0x100)
    page[0x4A04 - 0x4A00] = value
    return page


def test_no_quest_log_tooltip_shows_a_memory_address_side_quests(monkeypatch):
    """The same guarantee as the test above, for the side-quest rows.

    `QuestFlag.where` is a script address for developers -- `goldbox/
    commissions.py` is the authority for it -- and must never reach a tooltip.
    """
    import re

    from automap import questlog
    from goldbox import commissions as book

    monkeypatch.setenv(questlog.ENV, "1")
    address = re.compile(r"\$[0-9A-F]{4}\b")
    quest = book.SIDE_QUESTS[0]
    for value in (0, 250, 255):
        rows = questlog.side_quest_rows(book.flags(_flags_4a81(value)))
        for what, state, tip, note, _dim in rows:
            for text in (what, state, tip, note):
                assert not address.search(text), (
                    f"a memory address reaches a player: {text!r}")
                for flag in (quest.accept, *quest.progress, quest.finish):
                    assert flag.where not in text


@pytest.mark.parametrize("value, has_row, state, dim", [
    (0, False, None, None),
    (250, True, "In progress", False),
    (255, True, "Finished", True),
])
def test_a_side_quest_row_appears_once_the_potion_is_in_hand(app, monkeypatch,
                                                              value, has_row,
                                                              state, dim):
    """`$4A81` alone decides the row: 0 draws nothing, 250 and 255 draw one.

    Donald's decision of 2026-09-04: the log shows the errand once the potion
    is in hand, never merely for having talked to Ohlo. The row lands in the
    commissions group, appended after the commission rows (#158), so this
    also pins the order: the same commission rows come first, unchanged,
    whichever way the flag goes.
    """
    from automap import questlog

    monkeypatch.delenv(questlog.ENV, raising=False)
    commissions_only = rows(panel_for(app, _flags_4a81(value)), "commissions")

    monkeypatch.setenv(questlog.ENV, "1")
    panel = panel_for(app, _flags_4a81(value))
    everything = rows(panel, "commissions")
    assert everything[:len(commissions_only)] == commissions_only
    drawn = everything[len(commissions_only):]
    if not has_row:
        assert drawn == []
        return
    assert len(drawn) == 1
    assert drawn[0][1] == state
    dimmed = panel.groups["commissions"].visible_rows()[len(commissions_only)]
    assert bool(dimmed.what.styleSheet()) == dim


def test_a_side_quest_row_never_appears_from_the_accepted_flag_alone(app,
                                                                      monkeypatch):
    """The decision, pinned at the panel: a full `$4A00` page with `$4A04` =
    250 and `$4A81` = 0 appends no row to the commissions group, even though
    `side_quests()` itself reads `accepted` from the same bytes."""
    from automap import questlog

    monkeypatch.delenv(questlog.ENV, raising=False)
    commissions_only = rows(panel_for(app, _page_4a04(250)), "commissions")

    monkeypatch.setenv(questlog.ENV, "1")
    panel = panel_for(app, _page_4a04(250))
    assert rows(panel, "commissions") == commissions_only


def test_the_side_quest_rows_are_not_appended_unless_the_flag_says_so(app,
                                                                       monkeypatch):
    """The gate, three ways -- `tests/test_dosimport.py` does the DOS import
    flag the same way. Force it on and watch the other two fail first.

    The rows now share a container with the commissions, which are always
    drawn, so the thing worth pinning is that the flag governs only the
    side-quest tail of the list and leaves the commissions list itself
    byte-for-byte the same either way (#158).
    """
    from automap.questlog import ENV

    flags = _flags_4a81(250)            # would draw a row if the flag allowed it
    monkeypatch.delenv(ENV, raising=False)
    commissions_only = rows(panel_for(app, flags), "commissions")

    for value in (None, "", "0", "off", "no"):
        if value is None:
            monkeypatch.delenv(ENV, raising=False)
        else:
            monkeypatch.setenv(ENV, value)
        panel = panel_for(app, flags)
        assert rows(panel, "commissions") == commissions_only, value

    monkeypatch.setenv(ENV, "1")
    panel = panel_for(app, flags)
    assert rows(panel, "commissions") != commissions_only



def test_a_side_quest_state_with_no_approved_word_draws_no_row(caplog):
    """And does not take the rest of the Quest Log down with it.

    `SIDE_QUEST_WORDS` is deliberately partial -- no word has been proposed
    for `QUEST_ACCEPTED`, because Ohlo's accept flag is not durable and the
    state cannot arise yet. A bare subscript raised `KeyError` here, and
    `tick()`'s broad handler turned that into `trouble reading the emulator:
    'accepted'` on the alarm line: a raw internal word, blamed on the
    emulator. `update_from` caches the flag bytes *before* this runs, so the
    whole log stopped redrawing from then on -- commissions and summonses
    too, not just the side quest (#158).
    """
    import logging

    from automap import questlog

    class _State:
        durable_state = "accepted"
        quest = questlog.book.SIDE_QUESTS[0]

    assert "accepted" not in questlog.SIDE_QUEST_WORDS, (
        "the fixture is a state with no approved word; give it one and this "
        "test needs a different unworded state")

    real = questlog.book.side_quests
    questlog.book.side_quests = lambda flags: [_State()]
    try:
        with caplog.at_level(logging.WARNING, logger="wish.automap.questlog"):
            rows = questlog.side_quest_rows(object())
    finally:
        questlog.book.side_quests = real

    assert rows == []
    assert "accepted" in caplog.text, caplog.text
