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
