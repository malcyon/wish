"""Where a DOS Curse thief's seven extra skill points come from (`#437`), and
the conversion fix that stops them crossing a save (`#440`).

Everything here reads the player's own files at run time -- each title's
`GAME.OVR` out of the DOS archives, the specimen tree's Curse saves, the C64
disks -- and skips cleanly on a machine that has none.  No game bytes are
committed; what is asserted is the *shape* of the three engines' shared
routine and the residual the records carry.

The finding: the routine adds a one-byte stack local to every one of the eight
columns, Curse never assigns it before the loop, and the byte it therefore
reads is 7 in every DOS Curse record on this machine.  Silver Blades' copy
opens by zeroing the same local and Pool of Radiance's has no such term, which
is why neither title shows the offset.

The fix: `goldbox.dos.write` and `goldbox.c64_codec.write` both recompute a
Curse thief's eight skills from `goldbox.levels`' shared table rather than
copy whatever the source held, so neither an inflated DOS byte nor a stale
carried-over one reaches the destination.  The tests below build a neutral
character directly rather than reading a specimen, so they exercise the
writers' own logic and do not depend on which specimens happen to be on this
machine.
"""

import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from test_neutral import _filled  # noqa: E402

from goldbox import c64_codec, dos, dos_layout  # noqa: E402
from goldbox import levels as level_tables  # noqa: E402
from tools import cursethiefskills as cts  # noqa: E402
from tools import thiefskillcensus as census  # noqa: E402

CURSE = "curse-of-the-azure-bonds"
POOL = "pool-of-radiance"
BLADES = "secret-of-the-silver-blades"


def _routine(title, stem):
    from tools import dosbox

    if not dosbox.ARCHIVES.is_dir():
        pytest.skip("needs the DOS archives; set FR_ARCHIVES")
    try:
        found = cts.routine(title, stem)
    except (SystemExit, FileNotFoundError) as why:
        pytest.skip(str(why))
    if found["at"] is None:
        pytest.fail(f"{title}: no thief-skill routine found in GAME.OVR")
    return found


def test_curse_reads_the_item_bonus_local_without_ever_setting_it():
    """The defect itself, read out of the shipped `GAME.OVR`.

    `[bp-2]` is added to every column, and Curse's only four assignments to it
    sit inside the loop behind the readied-item test.  A thief carrying no
    such item is scored with whatever the stack held.
    """
    found = _routine(CURSE, "CURSE")
    assert found["reads"], "the local is never read -- the routine moved"
    assert found["sets_before_loop"] == []
    assert [value for _, value in found["sets_in_loop"]] == [0, 5, 0, 5]


def test_silver_blades_zeroes_the_same_local_before_its_loop():
    """The next engine's copy of the routine, which is the control."""
    found = _routine(BLADES, "SECRET")
    assert found["reads"]
    assert [value for _, value in found["sets_before_loop"]] == [0]


def test_pool_of_radiance_has_no_such_term_at_all():
    """The earlier engine never grew the item bonus, so it cannot leak one."""
    found = _routine(POOL, "POOLRAD")
    assert found["reads"] == []
    assert found["sets_before_loop"] == []
    assert found["sets_in_loop"] == []


def test_every_dos_curse_thief_record_is_the_same_constant_high():
    """One number over every DOS Curse record this machine can reach.

    Two of them are this project's own writer's output and read 0, which is
    the control: they are what the tables give with no stack byte added.
    """
    from tools import dosbox

    if not dosbox.ARCHIVES.is_dir():
        pytest.skip("needs the DOS archives; set FR_ARCHIVES")
    try:
        rows = list(cts.residuals(CURSE))
    except (SystemExit, FileNotFoundError, KeyError) as why:
        pytest.skip(str(why))
    if not rows:
        pytest.skip("no DOS Curse thief records on this machine")
    flat = {}
    for _, _, _, _, delta in rows:
        assert len(set(delta)) == 1, f"the residual is not flat: {delta}"
        flat[delta[0]] = flat.get(delta[0], 0) + 1
    assert set(flat) <= {0, 7}, f"an unexpected residual: {sorted(flat)}"
    assert flat.get(7, 0) >= 1, "no record carries the seven-point offset"


def test_the_c64_trainer_writes_the_row_its_own_tables_give():
    """`WISH-SPEC-curse-train-input` to `-trained-party`, one training apart.

    TRAVIS goes in at thief 5 holding the DOS engine's inflated row and comes
    out at thief 6 holding exactly what the C64's own level, race and
    dexterity tables give.  So the C64 engine does not share the defect, and
    it does not inherit it either once the trainer runs.
    """
    tree = pathlib.Path(os.environ.get("WISH_SPECIMENS",
                                       pathlib.Path.home() / "wish-specimens"))
    # The two Curse disks live under `por-c64/`, which is the tree's own
    # legacy name for the C64 side rather than a claim about the title.
    before = tree / "por-c64" / "WISH-SPEC-curse-train-input.D64"
    after = tree / "por-c64" / "WISH-SPEC-curse-trained-party.D64"
    if not (before.is_file() and after.is_file()):
        pytest.skip("needs WISH-SPEC-curse-train-input and -trained-party")
    try:
        tables = census.c64_tables(CURSE)
    except SystemExit as why:
        pytest.skip(str(why))
    records = list(census.c64_records(CURSE))

    def travis(disk):
        for source, name, race, level, dexterity, stored in records:
            if source == disk.name and name.strip() == "TRAVIS":
                return race, level, dexterity, stored
        pytest.skip(f"no TRAVIS on {disk.name}")

    race, level, dexterity, stored = travis(before)
    want = census.expected(tables, level, race, dexterity, True)
    assert [a - b for a, b in zip(stored, want)] == [7] * 8

    race, level, dexterity, stored = travis(after)
    want = census.expected(tables, level, race, dexterity, True)
    assert stored == want, "the C64 trainer did not write its own tables' row"


# --- the conversion fix: recompute at the destination (#440) ----------------

def _expected_row(char):
    return level_tables.thief_skills(
        char.get("levels")["thief"], char.get("race"), char.game,
        dexterity=char.get("dexterity"))


def test_a_dos_curse_thief_converted_to_the_c64_gets_the_table_row():
    """A Curse thief's stored eight bytes are not trusted going to the C64,
    whatever they hold -- the destination's own clean table wins.

    `_filled` puts an arbitrary, distinct value in every neutral field
    (`goldbox.c64_codec.DIRECT`'s own position), so the thief-skill columns
    start out holding numbers the table does not give either -- standing in
    for a stored DOS byte inflated by the stack leftover `#437` found. If
    `c64_codec.write` ever went back to copying them, this is what would
    reach the C64 record.
    """
    char = _filled(game=CURSE)
    char.port = "DOS"
    want = _expected_row(char)
    stored = tuple(char.get(field) for field, _ in c64_codec._THIEF_SKILL_COLUMNS)
    assert want != stored, "the test's made-up row already matches the table"

    rec, _ = c64_codec.write(char)
    got = tuple(rec.get(c64) for _, c64 in c64_codec._THIEF_SKILL_COLUMNS)
    assert got == want


def test_a_c64_curse_thief_converted_to_dos_gets_the_same_clean_sum():
    """The same recompute, the other way -- a converted DOS record holds
    the table row a copy of the C64's own stored bytes might not.

    Costs nothing when the C64 source is already clean, since the two
    ports' tables agree (#437); this proves the DOS writer does not merely
    rely on that agreement holding by accident, the same way the C64 writer
    above does not trust its own source either.
    """
    char = _filled(game=CURSE)
    char.port = "C64"
    want = _expected_row(char)
    stored = tuple(char.get(field) for field, _ in c64_codec._THIEF_SKILL_COLUMNS)
    assert want != stored, "the test's made-up row already matches the table"

    rec, _, _, _ = dos.write(char)
    table = dos_layout.FIELDS_BY_NAME_FOR[CURSE]
    got = tuple(rec[table[dos_name].offset]
                for _, dos_name in c64_codec._THIEF_SKILL_COLUMNS)
    # The raw stored byte, unsigned -- a negative column (a race's
    # read-languages penalty can outweigh the row, #437) is the same `ADC`
    # wraparound either port's `LevelTables.thief_skill_row` leaves behind.
    assert got == tuple(v & 0xFF for v in want)


def test_pool_of_radiances_gate_is_unwidened():
    """`#440`'s fix is a second gate beside `#431`'s, not a wider one:
    Curse's two ports agree on their tables, so it must never appear on
    `THIEF_SKILL_RACE_DIFFERS_BY_PORT`, and Pool of Radiance -- which has no
    stack-leftover defect -- must never appear on the new one."""
    assert level_tables.thief_skill_race_differs_by_port(POOL)
    assert not level_tables.thief_skill_race_differs_by_port(CURSE)
    assert not level_tables.thief_skill_dos_storage_inflated(POOL)


def test_silver_blades_is_on_neither_gate():
    """Its DOS routine zeroes the stack local (`test_silver_blades_zeroes_
    the_same_local_before_its_loop` above) and its per-port table agreement
    has never been measured, so it is not a case for either gate yet."""
    assert not level_tables.thief_skill_race_differs_by_port(BLADES)
    assert not level_tables.thief_skill_dos_storage_inflated(BLADES)
