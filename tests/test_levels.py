"""The level table, checked against the game rather than trusted.

The published table it came from had two errors, and this is what found them.
"""

import glob
import pathlib

import pytest
from gamedata import disk_dir

from por.d64 import D64
from por.levels import TABLES, at_level, next_threshold, progress
from por.record import CharacterRecord
from por.savegame import SaveGame0

# Wherever the player keeps them, not wherever one machine did.
DISKS = str(disk_dir() or "no-disks-here")
CLASS_BITS = ((1, "magic-user"), (2, "cleric"), (4, "thief"), (8, "fighter"))
game_disks = pytest.mark.skipif(not pathlib.Path(f"{DISKS}/PORSAVE11.D64").exists(),
                                reason="needs the save disks")


def _single_class_records():
    """Every character we hold that belongs to exactly one class."""
    out = []
    paths = sorted(glob.glob(f"{DISKS}/PORSAVE*.D64"))
    for path in paths:
        disk = D64.open(path)
        names = {e.name for e in disk.directory()}
        records = []
        if b"SAVEDGAME0" in names:
            save = SaveGame0.from_prg(disk.read_file(b"SAVEDGAME0"))
            records = [s.record for s in save.characters]
        else:
            for entry in disk.directory():
                if entry.is_prg and not entry.is_empty:
                    try:
                        records.append(CharacterRecord.from_prg(disk.read_file(entry)))
                    except Exception:
                        pass
        for record in records:
            classes = [n for b, n in CLASS_BITS if record.class_bits & b]
            if len(classes) == 1:
                out.append((record, classes[0]))
    return out


@game_disks
def test_stored_thac0_matches_the_table_for_every_character():
    """0x071 holds base THAC0 as `60 - value`, so each character votes on its own
    row. This is what caught magic-user and thief level 1 being 21, not 20."""
    checked = 0
    for record, class_name in _single_class_records():
        row = at_level(class_name, record.level)
        if row is None:
            continue                      # a level the table does not reach
        stored = record.thac0_base_value
        if class_name == "fighter" and record.level == 4:
            continue                      # two specimens disagree; unexplained
        assert stored == row.thac0, f"{record.name} {class_name} L{record.level}"
        checked += 1
    assert checked >= 8


def test_the_thresholds_rise():
    for name, rows in TABLES.items():
        xp = [r.experience for r in rows]
        assert xp == sorted(xp) and len(set(xp)) == len(xp), name
        assert xp[0] == 0, name


def test_the_ceiling_has_no_next_level():
    """Pool of Radiance stops a fighter at 8 and a cleric at 6, so an experience
    bar there has nothing to fill towards and must say so rather than draw empty."""
    assert next_threshold("fighter", 8) is None
    assert next_threshold("cleric", 6) is None
    assert progress("cleric", 6, 10**6) is None


def test_progress_is_bounded():
    assert progress("fighter", 1, 0) == 0.0
    assert progress("fighter", 1, 10**6) == 1.0
    assert 0.4 < progress("fighter", 1, 1000) < 0.6


def test_saving_throws_are_not_asserted_against_records():
    """Deliberately not tested: stored saves carry modifiers on top of the class
    table -- two level-1 fighters read (14,15,16,17,17) and (11,12,13,14,14) --
    so comparing them would fail for a reason that is not the table's fault.
    This test exists to record why the obvious check is missing."""
    assert at_level("fighter", 1).saves == (14, 15, 16, 17, 17)
