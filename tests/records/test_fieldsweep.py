"""`tools/records/fieldsweep.py`, the parts that do not need a disk.

The tool's own answers are measurements and need the player's disks, so what
is pinned here is the one thing that made an earlier version of the same
sweep lie: which files it reads.  A C64 sweep for Pool of Radiance that globs
`por-c64/WISH-SPEC-*` picks up the six Curse and six Silver Blades disks that
live in that directory too, and those records answer for another game's
layout.  `#527 (A DOS import combines saving throws from classes the character
does not have)` had the count come out six records high that way before the
prefix went in.
"""

import pytest

from tools.records import fieldsweep


def test_the_c64_sweep_picks_specimen_disks_by_title_not_by_directory():
    """`por-c64/` holds all three C64 titles, so the prefix is the title."""
    assert fieldsweep.C64_SPECIMEN_PREFIX["pool-of-radiance"] == "WISH-SPEC-por"
    assert fieldsweep.C64_SPECIMEN_PREFIX["curse-of-the-azure-bonds"] \
        == "WISH-SPEC-curse"
    assert fieldsweep.C64_SPECIMEN_PREFIX["secret-of-the-silver-blades"] \
        == "WISH-SPEC-ssb"
    # Every prefix is distinct and no prefix is a prefix of another, or one
    # title's glob would swallow another's disks the same way the directory
    # glob did.
    prefixes = sorted(fieldsweep.C64_SPECIMEN_PREFIX.values())
    assert len(set(prefixes)) == len(prefixes)
    for one in prefixes:
        for other in prefixes:
            assert one == other or not other.startswith(one + "-")


def test_a_save_disk_prefix_never_matches_a_game_side():
    """`POOL1.D64` is a game side and carries no party."""
    for name in ("POOL1.D64", "POOLBOOT.D64", "POOL8.D64"):
        assert not name.startswith(fieldsweep.SAVE_DISK_PREFIXES)
    for name in ("PORSAVE13.D64", "NEWSAVE4.D64", "TEST_DOS_IMPORT3.D64"):
        assert name.startswith(fieldsweep.SAVE_DISK_PREFIXES)


def test_a_row_reads_its_fighter_level_out_of_the_class_map():
    """The fighter column is what `attack_level` is swept against, and a
    record with no fighter class answers 0 rather than raising."""
    assert fieldsweep.Row("d", "WISHFTR", {"fighter": 7}, 7).fighter == 7
    assert fieldsweep.Row("d", "WISHMAG", {"magic-user": 3}, 1).fighter == 0
    assert fieldsweep.Row("d", "MON00", {}, 0).fighter == 0


def test_the_report_names_its_specimens_and_tallies_every_value(capsys):
    """A count with no specimens beside it is the mistake this tool exists after:
    the sweep that concluded no engine writes 1 was C64-only."""
    rows = [fieldsweep.Row("a", "ONE", {"fighter": 3}, 3),
            fieldsweep.Row("b", "TWO", {"fighter": 3}, 3),
            fieldsweep.Row("c", "THREE", {"magic-user": 3}, 0)]
    fieldsweep.report(rows, "attack_level", "DOS pool-of-radiance", False)
    out = capsys.readouterr().out
    assert out.startswith("3 DOS pool-of-radiance records, attack_level")
    assert "         3        2" in out          # value 3, two records
    assert "         0        1" in out          # value 0, one record
    assert "        3        3        2" in out  # fighter 3, value 3, twice


def test_an_unknown_c64_field_is_blocked_rather_than_guessed_at():
    """A typo in a field name must not read a plausible byte."""
    with pytest.raises(SystemExit):
        list(fieldsweep.monster_rows("attack_levels"))
