"""The quest-flag map, and the side-quest table that is keyed on it.

Two things can go wrong and both are silent. The generator can stop finding
what it found -- a walk that reaches less of a script names fewer flags, and
nothing else in the suite would notice, while `goldbox-bugs.md` goes on
quoting a reference count nobody can reproduce. And the side-quest table can
drift away from the bytecode it claims to describe, which is worse, because a
wrong address reads a real byte and produces a confident wrong answer.

So: the counts are pinned, every declared flag is checked against the
instruction that writes it, and the four states of Ohlo's errand are read out
of the player's own saves.
"""
from __future__ import annotations

import pathlib

import pytest

from goldbox import commissions
from goldbox.d64 import D64
from tests.gamedata import disk_dir, needs_disks
from tools import eclflags, eclwalk


@pytest.fixture(scope="module")
def walk():
    if disk_dir() is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    scripts = eclwalk.scripts()
    if len(scripts) < 30:
        pytest.skip(f"only {len(scripts)} area scripts reachable; needs all 30")
    return eclflags.references(eclwalk.Machine(), scripts)


def _persistent(refs):
    return {a: v for a, v in refs.items() if a >= eclflags.PERSISTENT_BASE}


@needs_disks
def test_the_thirty_scripts_still_name_179_of_the_217_persistent_flags(walk):
    """The number `goldbox-bugs.md` and `docs/41` quote, regenerated.

    172 named by an operand plus 7 reached only through a declared table.
    A drop here means the walk is reaching less of some script, not that the
    game changed.
    """
    refs, _named, bases, _reach = walk
    eclflags.check_tables(bases)
    interior = eclflags.table_interiors(refs)
    direct = _persistent(refs)
    assert len(direct) == 172
    assert len(interior) == 7
    assert len(direct) + len(interior) == 179
    span = eclflags.PAGE_END - eclflags.PERSISTENT_BASE + 1
    assert span == 217
    assert span - len(direct) - len(interior) == 38


@needs_disks
def test_the_flag_page_still_carries_1415_operand_references(walk):
    """`goldbox-bugs.md` rests on this count; it has to stay reproducible."""
    refs, _named, _bases, _reach = walk
    direct = _persistent(refs)
    assert sum(len(v) for v in direct.values()) == 1415


@needs_disks
def test_nothing_above_4af8_is_named_by_any_script(walk):
    """The top of the block. `$4AF9`-`$4AFF` is not flag storage."""
    refs, _named, _bases, _reach = walk
    assert max(refs) == eclflags.PAGE_END


@needs_disks
@pytest.mark.parametrize("quest", commissions.SIDE_QUESTS,
                         ids=lambda q: q.key)
def test_every_declared_side_quest_flag_is_written_where_it_says(walk, quest):
    """Each `QuestFlag` names an instruction; that instruction has to exist.

    This is the test that catches a table drifting away from the bytecode.
    It checks the address, the value and the script address in `where`, so a
    transposed digit in any of the three fails.
    """
    refs, _named, _bases, _reach = walk
    for flag in (quest.accept, *quest.progress, quest.finish):
        sites = [r for r in refs.get(flag.address, [])
                 if r.write and r.value == flag.value]
        assert sites, (f"${flag.address:04X} is never written {flag.value} "
                       f"by any script; {quest.key} says {flag.where}")
        assert all(r.script == quest.script for r in sites), (
            f"${flag.address:04X} = {flag.value} is written outside "
            f"{quest.script}")
        for site in sites:
            assert f"${site.address:04X}" in flag.where, (
                f"{quest.key}: ${site.address:04X} writes "
                f"${flag.address:04X} = {flag.value} and `where` does not "
                f"name it -- {flag.where}")


@needs_disks
def test_ohlos_accept_flag_is_in_the_page_an_area_change_wipes(walk):
    """The whole point of #158: the game forgets the acceptance.

    `$4A04` is below `$4A20`, so `DUNGEON $202A`'s `STA $4A00,X` loop reaches
    it, and the durable half of the quest is `$4A81`.
    """
    del walk
    ohlo = commissions.SIDE_QUESTS[0]
    assert ohlo.key == "ohlo"
    assert ohlo.accept.address < commissions.FLAGS_BASE
    assert ohlo.accept.scratch and not ohlo.accept.durable
    assert ohlo.finish.address >= commissions.FLAGS_BASE
    assert ohlo.finish.durable
    assert not ohlo.durable


@needs_disks
def test_ohlos_potion_is_the_only_thing_that_writes_its_two_flags(walk):
    """No other script touches `$4A81`, and `$4A04` is reused by six.

    The second half is why the accept flag cannot be read from a save made
    anywhere else: `$4A04` means something different in `ECL01`, `ECL08`,
    `ECL0D`, `ECL0F` and `ECL12`.
    """
    refs, _named, _bases, _reach = walk
    assert {r.script for r in refs[0x4A81]} == {"ECL14"}
    assert len({r.script for r in refs[0x4A04]}) >= 6


# --- against the player's own saves -----------------------------------------

#: Every state of Ohlo's errand that a save on this machine reaches, and the
#: disk that reaches it. `#157` established the same table by hand.
SAVE_STATES = {
    "NEWSAVE1": commissions.QUEST_UNSEEN,
    "NEWSAVE2": commissions.QUEST_UNSEEN,
    "NEWSAVE3": commissions.QUEST_ACCEPTED,
    "NEWSAVE4": commissions.QUEST_ACCEPTED,
    "NEWSAVE5": commissions.QUEST_IN_HAND,
    "NEWSAVE6": commissions.QUEST_FINISHED,
    "POOL1": commissions.QUEST_UNSEEN,
    "PORSAVE": commissions.QUEST_UNSEEN,
    "PORSAVE13": commissions.QUEST_UNSEEN,
}


def _savedgame0(stem: str) -> bytes | None:
    where = disk_dir()
    if where is None:
        return None
    path = pathlib.Path(where) / f"{stem}.D64"
    if not path.exists():
        return None
    image = D64.open(path)
    names = [e.name.decode("latin1").rstrip("\xa0 ")
             for e in image.iter_directory()]
    if "SAVEDGAME0" not in names:
        return None
    return image.read_file("SAVEDGAME0")[2:]


@needs_disks
@pytest.mark.parametrize("stem,expected", sorted(SAVE_STATES.items()))
def test_ohlos_errand_reads_the_same_state_the_save_was_left_in(stem, expected):
    payload = _savedgame0(stem)
    if payload is None:
        pytest.skip(f"no {stem}.D64 with a SAVEDGAME0 here")
    state = commissions.side_quests(payload)[0]
    assert state.state == expected


@needs_disks
def test_a_save_made_outside_the_slums_cannot_say_the_errand_was_accepted():
    """The defect #158 exists to work round, stated as a measurement.

    Every save on the machine that never met Ohlo reads exactly like a party
    that accepted the errand and walked out, because the byte that would tell
    them apart has been zeroed by then. Count them, do not round them away.
    """
    ambiguous = 0
    for stem in SAVE_STATES:
        payload = _savedgame0(stem)
        if payload is None:
            continue
        state = commissions.side_quests(payload)[0]
        if state.ambiguous:
            ambiguous += 1
            assert state.accept_value == 0
    assert ambiguous >= 4, "expected the unseen saves to read as ambiguous"


# --- the scratch page -------------------------------------------------------

def test_the_persistent_block_reader_still_refuses_the_scratch_page():
    """`flags()` slices `$4A00`-`$4A1F` off, and must go on doing so.

    A quest whose acceptance is a scratch byte is exactly the thing that must
    not be mixed into the block that survives an area change.
    """
    page = bytes(range(256))
    block = commissions.flags(page)
    assert block[commissions.FLAGS_BASE] == page[0x20]
    with pytest.raises(IndexError):
        block[commissions.SCRATCH_BASE]


def test_the_scratch_page_comes_back_only_from_a_source_that_carries_it():
    page = bytes(range(256))
    assert commissions.scratch(page).to_bytes() == page[:32]
    assert commissions.scratch(commissions.flags(page)) is None
    assert commissions.scratch(bytes(commissions.FLAGS_SIZE)) is None
    whole = bytes(0x100) + page + bytes(0x100)          # $4900 onwards
    assert commissions.scratch(whole).to_bytes() == page[:32]


def test_a_flag_block_alone_cannot_answer_whether_the_errand_was_accepted():
    """`side_quests()` says `unknown` rather than guessing.

    A caller holding the 224 persistent bytes has no scratch page, and
    answering `not seen` there would be a claim the data does not support.
    """
    block = commissions.flags(bytes(commissions.FLAGS_SIZE))
    state = commissions.side_quests(block)[0]
    assert state.state == commissions.QUEST_UNKNOWN
    assert state.accept_value is None


# --- the durable-only reading, #158's 2026-09-04 decision -------------------

@pytest.mark.parametrize("value, expected", [
    (0, commissions.QUEST_UNSEEN),
    (250, commissions.QUEST_IN_HAND),
    (255, commissions.QUEST_FINISHED),
])
def test_durable_state_reads_4a81_alone_from_a_224_byte_block(value, expected):
    """No scratch page in sight: a `Flags` alone is what the panel gets."""
    flags = bytearray(commissions.FLAGS_SIZE)
    flags[0x4A81 - commissions.FLAGS_BASE] = value
    state = commissions.side_quests(commissions.flags(bytes(flags)))[0]
    assert state.durable_state == expected


def test_durable_state_ignores_the_accepted_flag_the_game_itself_forgets():
    """The decision, pinned: `$4A04` = 250 reads `accepted` in `state` and
    `not seen` in `durable_state`, because `$4A04` is scratch an area change
    wipes and the game keeps no durable record of having merely talked to
    Ohlo."""
    page = bytearray(0x100)                     # the $4A00 page, then flags
    page[0x4A04 - commissions.SCRATCH_BASE] = 250
    state = commissions.side_quests(bytes(page))[0]
    assert state.state == commissions.QUEST_ACCEPTED
    assert state.durable_state == commissions.QUEST_UNSEEN


@needs_disks
@pytest.mark.parametrize("stem,expected", [
    ("NEWSAVE3", commissions.QUEST_UNSEEN),
    ("NEWSAVE4", commissions.QUEST_UNSEEN),
    ("NEWSAVE5", commissions.QUEST_IN_HAND),
    ("NEWSAVE6", commissions.QUEST_FINISHED),
])
def test_durable_state_on_real_saves_never_shows_accepted(stem, expected):
    """`NEWSAVE3`/`NEWSAVE4` read `accepted` in `state` (`SAVE_STATES` above)
    and `not seen` here -- the accept flag they carry is scratch."""
    payload = _savedgame0(stem)
    if payload is None:
        pytest.skip(f"no {stem}.D64 with a SAVEDGAME0 here")
    state = commissions.side_quests(payload)[0]
    assert state.durable_state == expected


# --- the panel, against real saves -------------------------------------------

@needs_disks
@pytest.mark.parametrize("stem,drawn,dim", [
    ("NEWSAVE1", False, None),
    ("NEWSAVE2", False, None),
    ("NEWSAVE3", False, None),
    ("NEWSAVE4", False, None),
    ("NEWSAVE5", True, False),
    ("NEWSAVE6", True, True),
    ("POOL1", False, None),
    ("PORSAVE", False, None),
    ("PORSAVE13", False, None),
])
def test_the_side_quest_row_appears_on_the_saves_that_earn_it(stem, drawn, dim):
    """Every save in `SAVE_STATES`, through the actual panel this time.

    The side-quest row, when there is one, is appended to the commissions
    group rather than drawn in a group of its own (#158) -- so the row is
    whatever visible row comes after however many commission rows
    `commission_rows` alone produces for this save.
    """
    from PyQt6.QtWidgets import QApplication, QMainWindow

    from automap import questlog
    from wish.ui_window import Ui_WishWindow

    payload = _savedgame0(stem)
    if payload is None:
        pytest.skip(f"no {stem}.D64 with a SAVEDGAME0 here")
    QApplication.instance() or QApplication([])

    base_count = len(questlog.commission_rows(commissions.flags(payload)))

    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    panel = questlog.QuestLogPanel(root)
    panel.update_from(payload)
    all_rows = panel.groups["commissions"].visible_rows()
    rows = all_rows[base_count:]
    assert len(rows) == (1 if drawn else 0), stem
    if drawn:
        assert bool(rows[0].what.styleSheet()) == dim, stem
