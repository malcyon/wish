"""The limit under a DOS `thac0_base`, and what a conversion into DOS writes.

The DOS engine's recompute reads entry 0 of every class row the character has
no level in, so the byte it stores is never worse than THAC0 20 --
`docs/224-the-dos-thac0-floor.md`.  `goldbox.levels.dos_engine_thac0` is that
rule and `goldbox.dos_codec.write` stores it for a C64 source; the
best-of-classes number `dos_base_thac0` gives is the C64 engine's, and differs
from it by one point for a Curse or Silver Blades magic-user of level 1-5.

The first block reads only the code and always runs.  The second compares the
level-0 column and the function against the player's own DOS tables through
`tools/records/thac0census.py` and skips without them.  The last converts the
C64 party a specimen DOS save was made from and skips without the specimen tree.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import gamedata  # noqa: E402
from support.neutralrecords import _filled  # noqa: E402

from goldbox import amiga_later, c64_codec, c64_port, dos_codec, items  # noqa: E402
from goldbox import levels as level_tables  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.encoding import COMBAT_BIAS, combat_value  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402

POOL = "pool-of-radiance"
CURSE = "curse-of-the-azure-bonds"
SSB = "secret-of-the-silver-blades"
TITLES = (POOL, CURSE, SSB)
LATER = (CURSE, SSB)


# --- the function, over the code's own rows ---------------------------------
@pytest.mark.parametrize("title", LATER)
@pytest.mark.parametrize("level,want", [(1, 20), (2, 20), (3, 20), (4, 20),
                                        (5, 20), (6, 19)])
def test_a_magic_user_is_held_to_20_until_his_own_row_beats_it(
        title, level, want):
    """The one place the limit shows: the row reads 21 at levels 1-5."""
    assert level_tables.dos_base_thac0({"magic-user": level}, title) == (
        21 if level <= 5 else 19)
    assert level_tables.dos_engine_thac0({"magic-user": level}, title) == want


@pytest.mark.parametrize("title", LATER)
def test_a_fighter_and_a_paladin_are_read_from_their_own_rows(title):
    for name in ("fighter", "paladin"):
        assert level_tables.dos_engine_thac0({name: 1}, title) == 20
        assert level_tables.dos_engine_thac0({name: 5}, title) == 16
        assert level_tables.dos_engine_thac0({name: 9}, title) == 12


@pytest.mark.parametrize("title", LATER)
def test_a_multi_class_character_takes_the_best_row_and_the_limit(title):
    assert level_tables.dos_engine_thac0(
        {"fighter": 4, "thief": 5}, title) == 17
    assert level_tables.dos_engine_thac0(
        {"magic-user": 5, "cleric": 3}, title) == 20
    assert level_tables.dos_engine_thac0(
        {"magic-user": 3, "thief": 5, "cleric": 4}, title) == 18
    # A zero-level slot is a class he does not have, whichever way it is spelt.
    assert level_tables.dos_engine_thac0(
        {"magic-user": 5, "fighter": 0}, title) == 20


def test_pool_of_radiance_is_unaffected_by_the_limit():
    """Its rows never ask for worse than 20, so both rules agree everywhere."""
    for held in ({"magic-user": 1}, {"magic-user": 5}, {"thief": 4},
                 {"cleric": 1}, {"fighter": 1}, {"fighter": 8},
                 {"fighter": 4, "thief": 5}):
        assert (level_tables.dos_engine_thac0(held, POOL)
                == level_tables.dos_base_thac0(held, POOL)), held
    assert level_tables.dos_engine_thac0({"magic-user": 3}, POOL) == 20


@pytest.mark.parametrize("title", TITLES)
def test_nothing_is_written_for_a_character_with_no_class_level(title):
    assert level_tables.dos_engine_thac0({}, title) is None
    assert level_tables.dos_engine_thac0({"fighter": 0}, title) is None


# --- against the player's own DOS tables ------------------------------------
def _rows(title):
    from tools.dos import dosbox
    from tools.records import thac0census

    if not dosbox.ARCHIVES.is_dir():
        pytest.skip("no DOS archives on this machine; set $FR_ARCHIVES")
    try:
        return thac0census, thac0census.dos_rows(title)
    except (SystemExit, KeyError, OSError) as why:
        pytest.skip(f"no readable {title} DOS table here: {why}")


@pytest.mark.parametrize("title", TITLES)
def test_the_level_zero_column_is_what_the_games_own_tables_hold(title):
    _, rows = _rows(title)
    tables = level_tables.for_game(title)
    assert dict(tables.dos_thac0_level0) == {
        name: row[0] for name, row in rows.items()}


@pytest.mark.parametrize("title", TITLES)
def test_the_function_reproduces_the_census_rule_for_every_class_and_level(
        title):
    census, rows = _rows(title)
    tables = level_tables.for_game(title)
    names = [name for name, _row in tables.dos_thac0]
    checked = 0
    for name in names:
        for level in range(1, len(rows[name])):
            held = {name: level}
            assert tables.dos_engine_thac0(held) == census.dos_engine_thac0(
                rows, held), (title, held)
            checked += 1
    for held in ({"fighter": 4, "thief": 5}, {"magic-user": 5, "cleric": 3},
                 {"magic-user": 3, "thief": 5, "cleric": 4},
                 {"magic-user": 1, "thief": 1}, {"fighter": 2, "thief": 2}):
        held = {n: v for n, v in held.items() if n in names}
        assert tables.dos_engine_thac0(held) == census.dos_engine_thac0(
            rows, held), (title, held)
    assert checked > 30


# --- what write puts in the record ------------------------------------------
def _char(title, levels, port):
    char = _filled(c64_port.by_key(title))
    char.port = port
    char.set("levels", levels, "made up")
    return char


def _stored(char, **kwargs):
    rec, _itm, _spc, _rep = dos_codec.write(char, **kwargs)
    return dos_codec.DosCharacter(rec).get("thac0_base")


def _amiga_stored(char):
    built, _rep = amiga_later.write_later(char)
    return built.get("thac0_base")


@pytest.mark.parametrize("title", LATER)
def test_a_c64_magic_user_of_level_five_arrives_holding_40(title):
    """THAC0 20, the number the DOS engine writes for him; 39 was the C64's."""
    char = _char(title, {"magic-user": 5}, "C64")
    assert _stored(char) == COMBAT_BIAS - 20
    assert combat_value(_stored(char)) == 20


def test_the_floor_leaves_a_c64_pool_magic_user_unchanged():
    char = _char(POOL, {"magic-user": 5}, "C64")
    assert _stored(char) == _stored(char, thac0_floor=False)
    assert _stored(char) == COMBAT_BIAS - 20


@pytest.mark.parametrize("title", LATER)
def test_a_c64_magic_user_of_level_five_arrives_at_an_amiga_holding_40(title):
    """The later Amiga import/training loop reads every level-zero row."""
    char = _char(title, {"magic-user": 5}, "C64")
    assert _amiga_stored(char) == COMBAT_BIAS - 20
    assert combat_value(_amiga_stored(char)) == 20


@pytest.mark.parametrize("title", LATER)
@pytest.mark.parametrize("levels,want", [
    ({"magic-user": 6}, 19), ({"fighter": 5}, 16), ({"paladin": 5}, 16),
    ({"fighter": 4, "thief": 5}, 17), ({"cleric": 5}, 18)])
def test_the_limit_changes_no_other_class(title, levels, want):
    assert combat_value(_stored(_char(title, levels, "C64"))) == want


@pytest.mark.parametrize("title", LATER)
@pytest.mark.parametrize("port", ["DOS", "Amiga"])
def test_a_source_that_is_not_the_c64_keeps_its_own_byte(title, port):
    char = _char(title, {"magic-user": 5}, port)
    char.set("thac0_base", COMBAT_BIAS - 21, "the source's own byte")
    assert combat_value(_stored(char)) == 21
    assert combat_value(_amiga_stored(char)) == 21


# --- the specimen this was found on -----------------------------------------
_C64_DISK = "coab-c64/WISH-SPEC-curse-551-paladin11-ranger11.D64"
_DOS_DIR = "coab-dos/WISH-SPEC-curse-551-party-as-converted"


def test_the_551_party_converts_to_what_the_engine_wrote_for_it():
    """Converting the C64 party the DOS specimen was made from again.

    The specimen's two magic-users hold 39 because the writer of the day used
    the C64's rule; DOS Curse rewrote both to 40 when the same party was loaded
    and saved (`docs/224-the-dos-thac0-floor.md`).  The other four characters
    hold what the engine left and are unchanged.
    """
    root = gamedata.specimen_root()
    disk = root / _C64_DISK if root else None
    where = root / _DOS_DIR if root else None
    if disk is None or not disk.is_file() or not where.is_dir():
        pytest.skip(f"needs {_C64_DISK} and {_DOS_DIR} from the specimen tree")
    game, sg0, sg1 = load_save(D64.open(str(disk)))
    held = {}
    for path in sorted(where.glob("CHRDATA?.SAV")):
        held[dos_codec.read_character(path).name.strip()] = path
    seen = {}
    for slot in sg0.characters:
        block = sg1.roster(slot.index) if sg1 is not None else None
        inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(), slot.index)]
        char = c64_codec.read(slot.record, roster=block, inventory=inv,
                              game=game, source=disk.name)
        name = slot.record.name.strip()
        rec = dos_codec.write(char)[0]
        seen[name] = (held[name].read_bytes()[0x073], rec[0x073])
    assert seen == {
        "MALE ELF MAGE": (COMBAT_BIAS - 21, COMBAT_BIAS - 20),
        "FEMALE MAGE": (COMBAT_BIAS - 21, COMBAT_BIAS - 20),
        "CLERIC": (0x2A, 0x2A), "F/T": (0x2B, 0x2B),
        "RANGER": (0x32, 0x32), "PALADIN": (0x32, 0x32),
    }
