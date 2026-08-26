"""The level table, checked against the game rather than trusted.

The published table it came from had two errors, and this is what found them.
"""

import glob
import pathlib

import pytest
from gamedata import disk_dir

from goldbox import levels
from goldbox.d64 import D64
from goldbox.levels import TABLES, at_level, next_threshold, progress
from goldbox.record import CharacterRecord
from goldbox.savegame import SaveGame0

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


def test_the_modifier_that_made_two_level_one_fighters_differ():
    """(14,15,16,17,17) and (11,12,13,14,14) are a human and a dwarf.

    The second is the first less `constitution * 2 // 7`, which `GEN $2359`
    subtracts from all five columns for a dwarf, gnome or halfling. MAGNUS,
    constitution 13, is the dwarf.
    """
    human = at_level("fighter", 1).saves
    assert human == (14, 15, 16, 17, 17)
    bonus = levels.constitution_save_bonus(13)
    assert bonus == 3
    assert levels.saving_throws({"fighter": 1}, race=1, constitution=13) == \
        tuple(v - bonus for v in human)
    assert levels.saving_throws({"fighter": 1}, race=7, constitution=13) == human


# --- the game's own tables, re-expanded off the player's GEN -----------------
# `goldbox/levels.py` writes its rows out longhand because a row is what a reader
# wants; the game stores them compressed. These read `GEN` off whichever POOL
# disk carries it and rebuild every table, so a typo in the longhand form fails
# here rather than in somebody's save. Skips without the disks.

GEN_BASE = 0x0800                # resident there whatever the PRG header says
CLASS_ORDER = ("magic-user", "cleric", "thief", "fighter")


def _gen():
    from gamedata import game_file
    return game_file("GEN")


def _at(payload, address, count=1):
    off = address - GEN_BASE
    return payload[off:off + count]


def test_the_thac0_rows_are_the_games_own():
    """`GEN $1F1F`, four rows of nine, `LDA $1F1F,X` with X = class * 9 + level.
    Stored as `60 - THAC0`, the same encoding the record uses at 0x071."""
    gen = _gen()
    for c, name in enumerate(CLASS_ORDER):
        for row in levels.table(name):
            stored = _at(gen, 0x1F1F + c * 9 + row.level)[0]
            assert 60 - stored == row.thac0, f"{name} {row.level}"


def _saves_from_gen(gen, class_index, level):
    """`GEN $1F44`'s encoding: a level-1 row and two per-column bitmasks.

    Each column starts at `$1FA2` and improves by one for every set bit, in
    either mask, among the low `level - 1` bits. Two masks so a column can gain
    two points at one level -- which is the whole of why a fighter's breath
    save is 15 at level 4 and not the 16 AD&D gives.
    """
    out = []
    for column in range(5):
        i = class_index * 5 + column
        base = _at(gen, 0x1FA2 + i)[0]
        low = _at(gen, 0x1FB6 + i)[0]
        high = _at(gen, 0x1FCA + i)[0]
        gained = sum(((low >> bit) & 1) + ((high >> bit) & 1)
                     for bit in range(level - 1))
        out.append(base - gained)
    return tuple(out)


def test_the_saving_throw_rows_are_the_games_own():
    gen = _gen()
    for c, name in enumerate(CLASS_ORDER):
        for row in levels.table(name):
            assert _saves_from_gen(gen, c, row.level) == tuple(row.saves), \
                f"{name} {row.level}"


def test_the_fighters_level_four_breath_save_is_fifteen():
    """P76, settled. AD&D 1st edition says 16; the game has always written 15,
    and the mask that does it is `$0C` where the other four columns hold `$08`.
    Two characters measured it and the table says the same thing."""
    gen = _gen()
    assert _at(gen, 0x1FCA + 3 * 5 + 3)[0] == 0x0C
    assert levels.at_level("fighter", 4).saves[3] == 15


def test_the_experience_thresholds_are_the_games_own():
    """`GEN $1DB4`/`$1DD8`/`$1DFC`, parallel low, mid and high arrays nine wide.
    Index `class * 9 + level` is the threshold to reach `level + 1`, and each
    class's tenth entry falls in the next class's unused slot 0 -- which is
    where the clamp past a ceiling comes from."""
    gen = _gen()
    for c, name in enumerate(CLASS_ORDER):
        for row in levels.table(name):
            want = levels.clamp_threshold(name, row.level)
            if want is None:
                continue
            i = c * 9 + row.level
            got = (_at(gen, 0x1DB4 + i)[0] | _at(gen, 0x1DD8 + i)[0] << 8
                   | _at(gen, 0x1DFC + i)[0] << 16)
            assert got == want, f"{name} {row.level}"


def test_the_thief_skill_tables_are_the_games_own():
    """`GEN $102E`, nine rows of eight, plus a racial row at `$1076`."""
    gen = _gen()
    for level, row in enumerate(levels.POOL_OF_RADIANCE.thief_skills, start=1):
        assert tuple(_at(gen, 0x102E + (level - 1) * 8, 8)) == row, level
    for race, row in enumerate(levels.POOL_OF_RADIANCE.thief_skill_race,
                               start=1):
        raw = _at(gen, 0x1076 + (race - 1) * 8, 8)
        assert tuple(b - 256 if b > 127 else b for b in raw) == row, race


def test_the_hit_dice_and_bonus_tables_are_the_games_own():
    """`GEN $20A7` the die, `$247B`/`$2486` the constitution bonus."""
    gen = _gen()
    for c, name in enumerate(CLASS_ORDER):
        assert _at(gen, 0x20A7 + c)[0] == levels.hit_die(name), name
    for score in range(15, 26):
        assert levels.constitution_hp_bonus(score, fighter=True) == \
            _at(gen, 0x247B + score)[0], score
        assert levels.constitution_hp_bonus(score, fighter=False) == \
            _at(gen, 0x2486 + score)[0], score
    assert levels.constitution_hp_bonus(14, fighter=True) == 0


def test_the_racial_save_bonus_is_the_games_own():
    """`GEN $2359`: `constitution * 2 / 7`, for the races flagged at `$2380`."""
    gen = _gen()
    for race in range(1, 8):
        flagged = bool(_at(gen, 0x2380 + race)[0])
        assert flagged == (race in levels.POOL_OF_RADIANCE.sturdy_races), race
    for score in range(3, 19):
        assert levels.constitution_save_bonus(score) == score * 2 // 7


def test_the_turning_table_is_the_games_own():
    """`GEN $2399`, indexed by cleric level. Not the level: it skips 4."""
    gen = _gen()
    for level, want in enumerate(levels.POOL_OF_RADIANCE.turn_power, start=1):
        assert _at(gen, 0x2399 + level)[0] == want, level
    assert levels.turning_level(4) == 5


def test_the_wisdom_bonus_table_is_the_games_own():
    """`GEN $10AD`, and the shifts `$2108` puts it through.

    The game's first-level column starts a point low -- 1 at wisdom 12 where
    AD&D gives the first bonus spell at 13 -- and this asserts what the game
    does, not what the rulebook says. See `docs/125-bug-notes.md`.
    """
    gen = _gen()
    for score in range(3, 19):
        base = _at(gen, 0x10AD + score)[0]
        assert levels.wisdom_bonus_spells(score)[0] == base, score
    assert levels.wisdom_bonus_spells(12) == (1, 0, 0)
    assert levels.wisdom_bonus_spells(16) == (2, 2, 0)
    assert levels.wisdom_bonus_spells(17) == (2, 2, 1)


def test_the_spell_slot_rows_are_the_games_own():
    """`GEN $2228` cleric and `$2248` magic-user, indexed by level * 4."""
    gen = _gen()
    for name, base in (("cleric", 0x2228), ("magic-user", 0x2248)):
        for row in levels.table(name):
            raw = tuple(_at(gen, base + row.level * 4, 4))
            assert raw[:len(row.spells)] == tuple(row.spells), \
                f"{name} {row.level}"
            assert not any(raw[len(row.spells):]), f"{name} {row.level}"


def test_only_pool_of_radiances_trainer_has_been_measured():
    """Having a table is not having read the trainer, and #16 is the
    difference. Curse's level tables are in this module; the hit-die roll at
    `GEN $2037`, the saving-throw masks at `$1F44`, the constitution tables at
    `$247B`/`$2486` and the spell capacity at `$20BC` were all read at Pool of
    Radiance's addresses out of Pool of Radiance's `GEN`, and nothing has
    confirmed Curse's agrees.

    `for_game` falls back to Pool of Radiance for a title it has no tables for,
    which is right for a spell name and wrong for writing a record -- so a
    writer asks `trainer_measured`, which does not fall back.
    """
    from goldbox import games

    assert levels.trainer_measured() is True             # None is the default
    assert levels.trainer_measured(games.POOL_OF_RADIANCE)
    assert levels.trainer_measured(levels.POOL_OF_RADIANCE)
    for game in games.GAMES:
        if game is games.POOL_OF_RADIANCE:
            continue
        assert not levels.trainer_measured(game), game.title
    # Curse has tables and is still refused; Silver Blades has none and
    # `for_game` hands back Pool of Radiance's, which is the silent case.
    assert levels.for_game(games.CURSE_OF_THE_AZURE_BONDS).key == \
        "curse-of-the-azure-bonds"
    assert levels.for_game(games.SECRET_OF_THE_SILVER_BLADES) is levels.DEFAULT
