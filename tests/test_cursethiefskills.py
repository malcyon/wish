"""Where a DOS Curse thief's seven extra skill points come from (`#437`).

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
"""

import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

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
