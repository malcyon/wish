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


#: Save disks that are **not** the C64 engine's own writing, and why.
#:
#: `PORSAVEA.D64` and `PORSAVEB.D64` are Wish's conversions of DOS save slots A
#: and B out of the player's DOS game folder -- same six names, same classes,
#: same levels, and `thac0_base` copied byte for byte off the DOS record. So
#: they hold the *DOS* build's THAC0, which is 20 for a low-level magic-user
#: where the C64's is 21, and voting them into a test about the C64's table
#: would be voting with our own writer's output twice over
#: (`.claude/rules/testing.md`, "A specimen is only evidence if we know who
#: wrote it"). `test_the_wish_converted_disks_carry_the_dos_number` below is
#: what keeps this from being a way of not looking.
CONVERTED_DISKS = ("PORSAVEA.D64", "PORSAVEB.D64")

#: One field a class, the array `GEN $1EF3` walks as `LDA $6BC9,X`. `level` at
#: `0x0BA` is a different field and is not what the THAC0 loop reads.
LEVEL_FIELDS = (("magic-user", "level_magic_user"), ("cleric", "level_cleric"),
                ("thief", "level_thief"), ("fighter", "level_fighter"))


def _class_levels(record):
    """The per-class levels, out of the array the engine's own loop reads."""
    return {name: record.get(field) for name, field in LEVEL_FIELDS
            if record.get(field)}


def _single_class_records(skip=CONVERTED_DISKS):
    """Every character we hold that belongs to exactly one class."""
    out = []
    paths = [p for p in sorted(glob.glob(f"{DISKS}/PORSAVE*.D64"))
             if pathlib.Path(p).name.upper() not in skip]
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
    row. This is what caught magic-user and thief level 1 being 21, not 20.

    **No exceptions.** It used to skip fighter 4 as "two specimens disagree;
    unexplained", and re-run on 2026-09-07 there are none: SILAS and MAGNUS are
    the only fighter 4s on the disks and both store 17, which is the row. The
    exception was for something that is not there.

    Levels come from the per-class array at `0x0C9`, which is the array
    `GEN $1EF3` walks; `level` at `0x0BA` is a different field and disagrees
    with it on an edited record.
    """
    checked = 0
    for record, class_name in _single_class_records():
        level = _class_levels(record).get(class_name) or record.level
        row = at_level(class_name, level)
        if row is None:
            continue                      # a level the table does not reach
        stored = record.thac0_base_value
        assert stored == row.thac0, f"{record.name} {class_name} L{level}"
        checked += 1
    assert checked >= 8


@game_disks
def test_the_wish_converted_disks_carry_the_dos_number():
    """The two disks the test above leaves out, and what is on them instead.

    `PORSAVEA.D64` and `PORSAVEB.D64` are Wish's conversions of the player's
    DOS slots A and B. Every one of their twelve records reproduces from the
    **DOS** build's table rather than the C64's, which is what makes leaving
    them out of the C64 vote a statement rather than a way of not looking --
    and it is the failure `#366 (A converted magic-user or thief arrives with
    the other port's THAC0, because the two ports ship different tables and the
    conversion copies the byte)` is about, so this test changes when that one
    is fixed.
    """
    seen = 0
    for path in sorted(glob.glob(f"{DISKS}/PORSAVE*.D64")):
        if pathlib.Path(path).name.upper() not in CONVERTED_DISKS:
            continue
        save = SaveGame0.from_prg(D64.open(path).read_file(b"SAVEDGAME0"))
        for slot in save.characters:
            record = slot.record
            want = levels.dos_base_thac0(_class_levels(record))
            assert record.thac0_base_value == want, \
                f"{pathlib.Path(path).name} {record.name}"
            seen += 1
    if not seen:
        pytest.skip("neither converted disk is on this machine")
    assert seen == 12, f"{seen} records across the two converted disks"


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


def test_pool_of_radiance_and_curses_trainers_are_measured():
    """Having a table is not having read the trainer, and #16 is the
    difference. Curse's level tables are in this module, and as of #18
    `goldbox/levelup.py` consumes every one of them -- `divide_between_classes`
    and `plan_all` are proven against real trainings
    (`tests/test_cursetrainer.py`), and `automap/actions.py`'s `LevelUp`
    action calls `plan_all` for it too
    (`tests/test_cursetrainer.py::test_a_curse_level_up_action_raises_travis_and_ledera_through_plan_all`).
    `automap/window.py`'s own `_level_up` was the last file to ask the
    question the same wrong way, and closing that on `#415
    (automap/window.py picks the level-up spell dialog's class the same
    wrong way plan would have, blocking Curse's trainer)` is what let Curse
    join `TRAINER_MEASURED` --
    `tests/test_cursetrainer.py::test_curse_is_now_in_trainer_measured` has
    the history.

    `for_game` falls back to Pool of Radiance for a title it has no tables for,
    which is right for a spell name and wrong for writing a record -- so a
    writer asks `trainer_measured`, which does not fall back.
    """
    from goldbox import games

    assert levels.trainer_measured() is True             # None is the default
    assert levels.trainer_measured(games.POOL_OF_RADIANCE)
    assert levels.trainer_measured(levels.POOL_OF_RADIANCE)
    assert levels.trainer_measured(games.CURSE_OF_THE_AZURE_BONDS)
    for game in games.GAMES:
        if game in (games.POOL_OF_RADIANCE, games.CURSE_OF_THE_AZURE_BONDS):
            continue
        assert not levels.trainer_measured(game), game.title
    # Silver Blades has tables too (#187) and is still refused: having a
    # table is not having read the trainer.
    assert levels.for_game(games.CURSE_OF_THE_AZURE_BONDS).key == \
        "curse-of-the-azure-bonds"
    assert levels.for_game(games.SECRET_OF_THE_SILVER_BLADES).key == \
        "secret-of-the-silver-blades"


# --- the DOS build's own THAC0 table -----------------------------------------
# `goldbox/levels.py`'s rows are the C64's, expanded from `GEN $1F1F`. The DOS
# build of Pool of Radiance ships a *different* table -- 40, THAC0 20, in the
# magic-user's rows 1-5 and the thief's rows 1-4, where the C64 ships 39 -- and
# `dos_thac0` carries it. These read that table back off the player's own
# `START.EXE` and vote every DOS record on this machine on it, the same way the
# `GEN` tests above do for the C64.
#
# The anchor is deliberately not a THAC0 number: `tools/thac0census.py` locates
# the table by the **class-bit run** that sits immediately after it, so the read
# cannot agree with `goldbox/levels.py` by construction.

def _thac0census():
    return pytest.importorskip("tools.thac0census")


def _dos_tables():
    """The DOS table, or a skip when the player's archives are not here."""
    census = _thac0census()
    try:
        return census.dos_table("pool-of-radiance")
    except FileNotFoundError as e:
        pytest.skip(f"needs the DOS archives: {e}")


def test_the_dos_thac0_rows_are_the_games_own():
    """`goldbox.levels`' `dos_thac0` against the bytes in `START.EXE`.

    The geometry is the engine's, not a guess: `GAME.OVR:0x01A68D` reaches the
    table with `mov dx, 0xB / mul dx / mov di, ax / add di, cx /
    mov al, [di+0x3C7C]`, so the rows are 11 wide and indexed by level with
    entry 0 unused. `tools/thac0census.py code` prints every site of that shape
    and all four Pool of Radiance ones carry the same stride and offset.
    """
    table = _dos_tables()
    rows = dict(levels.POOL_OF_RADIANCE.dos_thac0)
    assert set(rows) == set(TABLES), "a class is missing from dos_thac0"
    for name, row in rows.items():
        assert list(row) == table[name][:len(row)], name
    # The half that matters: the two ports disagree exactly here and nowhere
    # else, so a change to either table fails this rather than passing quietly.
    for name in ("cleric", "fighter"):
        c64 = [r.thac0 for r in levels.table(name)]
        assert rows[name][:len(c64)] == tuple(c64), f"{name} should agree"
    for name, last in (("magic-user", 5), ("thief", 4)):
        c64 = [r.thac0 for r in levels.table(name)]
        assert all(v == 21 for v in c64[:last]), name
        assert all(v == 20 for v in rows[name][:last]), name
        assert rows[name][last:len(c64)] == tuple(c64[last:]), \
            f"{name} should agree above level {last}"


def test_every_dos_record_reproduces_from_the_dos_table():
    """The sample is the finding: every DOS Pool of Radiance record on this
    machine, against the DOS table, best-of-classes and nothing else.

    That is the whole rule `GAME.OVR:0x1A659` implements -- clear the byte,
    walk the eight class slots, keep the row that beats what is there -- so a
    record that does not reproduce would mean a clamp, a stale cache or a
    second table, and none of the three is there. 190 of 190 on 2026-09-07,
    including the nine `WISH-SPEC-por-party-ladder-rung*` specimens the trainer
    was watched writing one level at a time.
    """
    census = _thac0census()
    table = _dos_tables()
    total = 0
    for source, name, held, stored in census.dos_records("pool-of-radiance"):
        want = census._best(table, held)
        if want is None:
            continue
        total += 1
        assert stored == want, f"{source} {name} {held}"
    if total < 60:
        pytest.skip(f"only {total} DOS records reachable; needs the specimen "
                    "tree or the archives")
