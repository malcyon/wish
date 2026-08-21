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

from por import commissions as book  # noqa: E402
from por.commissions import DONE, LEDGER_BASE, PAID_VALUE  # noqa: E402
from por.savegame import SAVE0_SIZE, SaveGame0  # noqa: E402

# A far-advanced save, kept out of the repository like every other game file.
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
        pytest.skip(f"needs {ADVANCED}, a far-advanced save")
    from por.d64 import load_payload
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
    assert "clear the slums" not in texts
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
    assert lines[0] == "Commissions completed: 0"
    assert "  clear Sokal Keep" in lines


# --- the panel --------------------------------------------------------------

def test_the_panel_shows_the_offers_and_hides_the_empty_groups(app):
    from automap.commissions import CommissionsPanel
    panel = CommissionsPanel()
    panel.update_from(blank())
    assert panel.completed.text() == "Commissions completed: 0"
    assert panel.groups["available"].isVisibleTo(panel)
    assert not panel.groups["paid"].isVisibleTo(panel)
    assert not panel.groups["waiting"].isVisibleTo(panel)
    assert [r.what.text() for r in panel.groups["available"]._rows[:3]] == [
        "clear the slums", "clear Sokal Keep",
        "bring back books, maps and tomes"]


def test_the_panel_splits_done_into_reward_waiting_and_paid(app):
    from automap.commissions import CommissionsPanel
    flags = blank()
    put_ledger(flags, 11, DONE)                   # graveyard, money uncollected
    put_ledger(flags, 1, PAID_VALUE)
    put_ledger(flags, 10, PAID_VALUE)
    panel = CommissionsPanel()
    panel.update_from(flags)
    waiting = panel.groups["waiting"]
    paid = panel.groups["paid"]
    assert [r.what.text() for r in waiting._rows if r.isVisibleTo(waiting)] == [
        "graveyard menace ended"]
    # Sorted by ledger index, which is roughly the plot's own order.
    assert [r.what.text() for r in paid._rows if r.isVisibleTo(paid)] == [
        "Sokal Keep cleared", "Podal Plaza auction"]


def test_the_panel_lists_an_outstanding_summons(app):
    from automap.commissions import CommissionsPanel
    panel = CommissionsPanel()
    panel.update_from(put(blank(), 0x4A97, DONE))
    group = panel.groups["summons"]
    assert group.isVisibleTo(panel)
    row = group._rows[0]
    assert row.what.text() == "Councilman Cadorna's chambers"
    assert row.state.text() == "summoned"


def test_the_panel_takes_a_whole_savedgame0(app):
    from automap.commissions import CommissionsPanel
    panel = CommissionsPanel()
    payload = game_file("SAVEDGAME0")
    before = bytes(payload)
    panel.update_from(payload)
    panel.update_from(SaveGame0.from_bytes(payload))
    assert payload == before
    assert panel.groups["available"]._rows[0].what.text() == "clear the slums"


def test_nothing_in_the_panel_is_editable(app):
    from PyQt6.QtWidgets import (
        QAbstractButton,
        QAbstractSpinBox,
        QComboBox,
        QLineEdit,
        QTextEdit,
    )

    from automap.commissions import CommissionsPanel
    flags = put_ledger(put_ledger(blank(), 1, PAID_VALUE), 11, DONE)
    panel = CommissionsPanel()
    panel.update_from(put(flags, 0x4A97, DONE))
    for kind in (QLineEdit, QTextEdit, QComboBox, QAbstractSpinBox,
                 QAbstractButton):
        assert panel.findChildren(kind) == []


def test_the_panel_says_so_before_it_has_any_bytes(app):
    from automap.commissions import CommissionsPanel
    panel = CommissionsPanel()
    assert panel.heading.text() == "Commissions - waiting for a game"
    panel.update_from(blank())
    assert panel.heading.text() == "Commissions"
