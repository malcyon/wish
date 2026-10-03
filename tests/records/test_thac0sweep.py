from __future__ import annotations

"""`tools/records/thac0sweep.py`, and the minimum the DOS engine puts under `thac0_base`.

Everything here reads the player's own files -- the EXEPACK-expanded
`START.EXE` of each DOS title and every character record in the specimen tree
and the archives -- and skips when they are not on this machine. The claim
being pinned is `docs/224-the-dos-thac0-lower-limit.md`: a DOS row's entry 0 is not
a zero sentinel, the recompute that runs on load reads it for every class the
character has no level in, and so no DOS record the engine writes holds a
THAC0 worse than 20.
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import gamedata  # noqa: E402

from goldbox import levels  # noqa: E402
from tools.dos import dosbox  # noqa: E402
from tools.records import thac0sweep  # noqa: E402

TITLES = ("pool-of-radiance", "curse-of-the-azure-bonds",
          "secret-of-the-silver-blades")

#: The records on this machine that the engine's own rule does not account
#: for, and why each is not a counter-example.
CURSE_EXCEPTIONS = {
    # Written by `goldbox/dos_codec.py` rather than by the game: the two
    # magic-users `#608` is about, holding the table's own 21.
    "WISH-SPEC-curse-551-party-as-converted/CHRDATA1.SAV": 21,
    "WISH-SPEC-curse-551-party-as-converted/CHRDATA2.SAV": 21,
}


def _rows(title: str) -> dict[str, list[int]]:
    if not dosbox.ARCHIVES.is_dir():
        pytest.skip("no DOS archives on this machine; set $FR_ARCHIVES")
    try:
        return thac0sweep.dos_rows(title)
    except (SystemExit, KeyError, OSError) as why:
        pytest.skip(f"no readable {title} DOS table here: {why}")


def _records(title: str) -> list[tuple]:
    if gamedata.specimen_root() is None:
        pytest.skip("needs the specimen tree; the exceptions name specimens")
    return list(thac0sweep.dos_records(title, former=True))


@pytest.mark.parametrize("title", TITLES)
def test_no_dos_row_holds_a_zero_where_the_c64_holds_a_sentinel(title):
    """Entry 0 of every DOS row is a THAC0, which is what makes it a minimum.

    The C64's own three tables start `$00` (`GEN $0E2C`, `$0E39`, `$0E46` in
    Curse), so a class with no level contributes nothing there. No DOS row in
    any of the three titles does: every entry 0 is 39 or 40 stored, THAC0 21
    or 20.
    """
    rows = _rows(title)
    zeroth = {name: row[0] for name, row in rows.items()}
    assert set(zeroth.values()) <= {20, 21}, zeroth
    assert min(zeroth.values()) == 20, zeroth


@pytest.mark.parametrize("title", TITLES)
def test_the_engine_never_writes_a_thac0_worse_than_twenty(title):
    """Whatever the classes, the recompute cannot leave more than 20 behind.

    A character is at most three classes, so at least one of the six rows
    whose entry 0 is 40 is always read.
    """
    rows = _rows(title)
    names = sorted(rows)
    for name in names:
        for level in range(1, len(rows[name])):
            got = thac0sweep.dos_engine_thac0(rows, {name: level})
            assert got <= 20, (name, level, got)
    assert thac0sweep.dos_engine_thac0(rows, {}) == 20


def test_a_curse_magic_user_of_level_five_comes_out_one_better_than_the_row():
    """The one place the minimum shows, and the whole of `#608`.

    The magic-user row reads 21 at levels 1-5 in both later titles and the
    engine stores 20 there; `goldbox.levels.dos_base_thac0` reads the row and
    so returns the 21.
    """
    for title in ("curse-of-the-azure-bonds", "secret-of-the-silver-blades"):
        rows = _rows(title)
        assert rows["magic-user"][1:6] == [21] * 5
        for level in range(1, 6):
            assert thac0sweep.dos_engine_thac0(
                rows, {"magic-user": level}) == 20
            assert levels.dos_base_thac0({"magic-user": level}, title) == 21
        assert thac0sweep.dos_engine_thac0(rows, {"magic-user": 6}) == 19


def test_a_regained_former_class_improves_the_byte():
    """A cleric 6 who was a paladin 5 hits as the paladin does, THAC0 16."""
    rows = _rows("curse-of-the-azure-bonds")
    assert thac0sweep.dos_engine_thac0(rows, {"cleric": 6}) == 18
    assert thac0sweep.dos_engine_thac0(
        rows, {"cleric": 6}, {"paladin": 5}) == 16


def test_a_character_with_no_former_class_is_unchanged():
    rows = _rows("curse-of-the-azure-bonds")
    for held in ({"cleric": 6}, {"magic-user": 5}, {"fighter": 3, "thief": 4}):
        alone = thac0sweep.dos_engine_thac0(rows, held)
        assert thac0sweep.dos_engine_thac0(rows, held, {}) == alone
        assert thac0sweep.dos_engine_thac0(rows, held, None) == alone


def test_a_former_level_not_yet_passed_changes_nothing():
    """The engine's test is strict: former 5 against level 5 is not regained."""
    rows = _rows("curse-of-the-azure-bonds")
    alone = thac0sweep.dos_engine_thac0(rows, {"cleric": 5})
    assert thac0sweep.dos_engine_thac0(
        rows, {"cleric": 5}, {"paladin": 5}) == alone


def test_pool_of_radiance_is_untouched_by_the_floor():
    """Its rows never go above 20 at any level, so nothing is floored."""
    rows = _rows("pool-of-radiance")
    assert max(max(row) for row in rows.values()) == 20


@pytest.mark.parametrize("title,exceptions", [
    ("pool-of-radiance", {}),
    ("curse-of-the-azure-bonds", CURSE_EXCEPTIONS),
    ("secret-of-the-silver-blades", {}),
])
def test_every_dos_record_on_this_machine_reproduces_from_the_engine_rule(
        title, exceptions):
    """The sweep, with each exception named rather than counted away.

    A record whose stored byte the rule does not give is a failure unless it
    is one of the records listed above; a listed exception that has started
    agreeing is a failure too, because the table it documents would have
    moved.
    """
    rows = _rows(title)
    records = _records(title)
    if not records:
        pytest.skip(f"no {title} DOS records on this machine")
    missed = {}
    for source, _name, held, stored, old in records:
        want = thac0sweep.dos_engine_thac0(rows, held, old)
        if want != stored:
            missed[source] = stored
    assert missed == exceptions
    assert len(records) >= 80


def test_the_table_alone_misses_what_the_engine_rule_reaches():
    """The count that says the minimum is doing work rather than agreeing anyway.

    `_best` over the classes the character has -- which is what
    `goldbox.levels.dos_base_thac0` computes -- disagrees with the stored byte
    on every low-level magic-user the engine has written.
    """
    rows = _rows("curse-of-the-azure-bonds")
    table = {name: row[1:] for name, row in rows.items()}
    records = _records("curse-of-the-azure-bonds")
    if not records:
        pytest.skip("no Curse DOS records on this machine")
    engine = sum(thac0sweep.dos_engine_thac0(rows, held, old) == stored
                 for _s, _n, held, stored, old in records)
    alone = sum(thac0sweep._best(table, held) == stored
                for _s, _n, held, stored, _old in records)
    assert engine > alone
