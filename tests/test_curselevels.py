from __future__ import annotations

"""`goldbox/levels.py` and `goldbox/spells.py`, now that both carry two titles.

Everything that needs game data reads it off the player's own disks through
`tests/gamedata.py` and skips when there are none. The tables in those two
modules are transcriptions of AD&D 1st edition or of numbers measured from the
game; the point of this file is that the disk gets to contradict them.

`GEN` is resident at `$0800` in both titles whatever its PRG header says, so
every address below is `payload[address - 0x0800]`.
"""


import pytest

from goldbox import levels, levelup, spells
from goldbox.record import CharacterRecord
from tests import gamedata
from tests.test_curse import _grant_table

GEN_BASE = 0x0800

POOL = levels.POOL_OF_RADIANCE
CURSE = levels.CURSE_OF_THE_AZURE_BONDS

#: Pool of Radiance: class caps, racial limits, THAC0 (`X = class * 9 + level`
#: off a base whose entry 0 is the `RTS` above it), and the spell-slot rows.
POOL_CLASS_CAPS = 0x1E5C
POOL_RACIAL_LIMITS = 0x1E60
POOL_THAC0 = 0x1F1F
POOL_SLOTS_CLERIC = 0x222C
POOL_SLOTS_MAGIC_USER = 0x224C

#: Curse: the same four, plus experience and the hit-dice triple.
CURSE_CLASS_CAPS = 0x15A1
CURSE_RACIAL_LIMITS = 0x15A9
CURSE_EXPERIENCE = 0x136E
CURSE_XP_ROW = 39                  # 13 levels x 3 bytes, big-endian
CURSE_HIT_DIE = 0x161E
CURSE_HIT_DIE_STOP = 0x1626
CURSE_HIT_DIE_FLAT = 0x162E
CURSE_THAC0 = (0x0E2C, 0x0E39, 0x0E46)      # magic-user, cleric, thief
CURSE_LEVEL_1_SAVES = 0x0F49

#: `ECL65` keeps Curse's spell slots, and its payload offset is used directly
#: because that overlay's resident base has not been fixed here.
CURSE_SLOTS = 0x88D


def _pool_gen() -> bytes:
    return gamedata.game_file("GEN")


def _curse_gen() -> bytes:
    return gamedata.curse_file("GEN")[2:]


def _at(payload: bytes, address: int, count: int) -> bytes:
    start = address - GEN_BASE
    assert 0 <= start <= len(payload) - count, (
        f"${address:04X} is outside a {len(payload)}-byte overlay")
    return payload[start:start + count]


# --- the descriptors are consistent with themselves --------------------------

def test_every_title_agrees_with_its_own_ceilings():
    for title in levels.TITLES:
        for name in title.class_names:
            rows = title.table(name)
            assert rows[-1].level == title.ceiling(name), (title.key, name)
            assert [r.level for r in rows] == list(range(1, len(rows) + 1))
            xp = [r.experience for r in rows]
            assert xp[0] == 0 and xp == sorted(xp) and len(set(xp)) == len(xp)


def test_the_class_order_is_class_bit_order():
    """Index n of `class_order` is bit n of `class_bits` and slot n of the
    per-class level array at `0x0C9`, which is what makes it usable as the
    index into a racial-limit row."""
    for title in levels.TITLES:
        assert len(title.class_order) == 8
        assert title.class_order[:4] == ("magic-user", "cleric", "thief",
                                         "fighter")
        assert title.class_order[4:6] == (None, None)
        for name in title.class_names:
            assert name in title.class_order, (title.key, name)


def test_for_game_takes_a_key_a_descriptor_or_nothing():
    assert levels.for_game() is levels.DEFAULT
    assert levels.for_game("curse-of-the-azure-bonds") is CURSE
    assert levels.for_game(CURSE) is CURSE
    assert spells.for_game("curse-of-the-azure-bonds").file == b"COMBAT2"
    # Silver Blades has its own tables now (#187); a title whose progression
    # has genuinely never been read still falls back, which is what a Krynn
    # key gets -- the caller receives Pool of Radiance's tables, the same as
    # before this module knew about any title at all.
    assert (levels.for_game("secret-of-the-silver-blades")
            is levels.SECRET_OF_THE_SILVER_BLADES)
    assert levels.for_game("champions-of-krynn") is levels.DEFAULT


def test_curse_raises_every_ceiling_and_adds_two_classes():
    assert set(CURSE.class_names) - set(POOL.class_names) == {"paladin",
                                                              "ranger"}
    for name in POOL.class_names:
        assert CURSE.ceiling(name) > POOL.ceiling(name), name


# --- the saving-throw rule ---------------------------------------------------

def test_the_rule_takes_the_best_column_from_each_class():
    """LADY KATHERINE is magic-user 1 / thief 1 and stores neither row."""
    magic_user = POOL.at_level("magic-user", 1).saves
    thief = POOL.at_level("thief", 1).saves
    both = levels.saving_throws({"magic-user": 1, "thief": 1})
    assert magic_user != thief
    assert both == tuple(min(a, b) for a, b in zip(magic_user, thief))
    assert both == (13, 12, 11, 15, 12)


def test_the_constitution_bonus_reaches_all_five_columns_in_pool_of_radiance():
    """MAGNUS, a dwarf fighter 1 with constitution 13, stores `11 12 13 14 14`."""
    assert levels.constitution_save_bonus(13) == 3
    assert levels.saving_throws({"fighter": 1}, race=1,
                                constitution=13) == (11, 12, 13, 14, 14)


def test_the_constitution_bonus_reaches_three_columns_in_curse():
    """The same character, in Curse, stores `11 15 13 17 14`.

    Curse takes the bonus off poison, wands and spells and leaves petrification
    and breath alone, which is the *Players Handbook* rule; Pool of Radiance
    takes it off all five. It is the only place the two games' arithmetic
    differs, and it is why the columns are a field on the descriptor.
    """
    assert CURSE.constitution_save_columns == (0, 2, 4)
    assert CURSE.saving_throws({"fighter": 1}, race=1,
                               constitution=13) == (11, 15, 13, 17, 14)


def test_a_race_with_no_bonus_stores_the_bare_row():
    for title in levels.TITLES:
        assert (title.saving_throws({"fighter": 1}, race=7, constitution=18)
                == title.at_level("fighter", 1).saves)


def test_no_class_means_no_answer():
    assert levels.saving_throws({}) is None
    assert levels.saving_throws({"paladin": 5}) is None      # not in this title


@pytest.mark.parametrize("name,level,expected", [
    ("paladin", 5, (9, 10, 11, 11, 12)),
    ("ranger", 5, (11, 12, 13, 13, 14)),
    ("cleric", 5, (9, 12, 13, 15, 14)),
    ("magic-user", 5, (14, 13, 11, 15, 12)),
])
def test_curse_matches_ssis_own_pregenerated_party(name, level, expected):
    """The six characters in Curse's shipped `SAVEAZURE` are the only evidence
    above level 1 either game offers, and they are the whole reason the paladin
    row is the fighter row less 2."""
    assert CURSE.saving_throws({name: level}) == expected


def test_the_curse_records_on_the_disks_all_satisfy_the_rule():
    """Every Curse character the player holds, against the rule rather than
    against a transcription."""
    checked = 0
    for label, raw in _curse_records():
        bits = raw[0x0EB]
        held = {CURSE.class_order[bit]: raw[0x0C9 + bit]
                for bit in range(8)
                if bits & (1 << bit) and CURSE.class_order[bit]}
        if not held:
            continue
        expected = CURSE.saving_throws(held, race=raw[0x072],
                                       constitution=raw[0x018])
        assert tuple(raw[0x09A:0x09F]) == expected, label
        checked += 1
    assert checked >= 6, "the shipped party alone should give six"


def _curse_records():
    """Every Curse character record on the player's disks, labelled."""
    from goldbox.d64 import D64
    out = []
    for disk in gamedata.curse_disks(engine_only=False):
        for entry in disk.directory():
            name = bytes(entry.name)
            try:
                data = disk.read_file(entry)
            except Exception:
                continue
            if name == b"SAVEAZURE" and len(data) > 7000:
                payload = data[2:]
                for slot in range(12):
                    at = 0x400 + slot * 0x100
                    raw = payload[at:at + 0x244]
                    if raw[0] not in (0, 0xFF) and raw[0x0EB]:
                        out.append((f"SAVEAZURE#{slot}", raw))
            elif name.startswith(b"\x02") and len(data) == 582:
                out.append((name.decode("latin1"), data[2:]))
    assert isinstance(disk, D64)
    if not out:
        pytest.skip("no Curse character records on the disks here")
    return out


# --- the tables, against the disks -------------------------------------------

def test_pool_of_radiance_ceilings_are_the_games_own():
    caps = _at(_pool_gen(), POOL_CLASS_CAPS, 8)
    assert list(caps) == [6, 6, 9, 8, 0, 0, 0, 0]
    for bit, name in enumerate(POOL.class_order):
        if name:
            assert POOL.ceiling(name) == caps[bit], name


def test_curse_ceilings_are_the_games_own():
    caps = _at(_curse_gen(), CURSE_CLASS_CAPS, 8)
    assert list(caps) == [11, 10, 12, 12, 0, 0, 11, 11]
    for bit, name in enumerate(CURSE.class_order):
        if name:
            assert CURSE.ceiling(name) == caps[bit], name


def test_pool_of_radiance_racial_limits_are_the_games_own():
    gen = _pool_gen()
    for race, row in POOL.racial_limits:
        disk = list(_at(gen, POOL_RACIAL_LIMITS + race * 4, 4))
        assert disk == list(row), race


def test_curse_racial_limits_are_the_games_own():
    gen = _curse_gen()
    for race, row in CURSE.racial_limits:
        disk = list(_at(gen, CURSE_RACIAL_LIMITS + (race - 1) * 8, 8))
        assert disk == list(row), race


def test_curse_zeroes_the_cleric_column_pool_of_radiance_filled():
    """Dwarf, elf and gnome clerics are *Dungeon Master's Guide* NPCs, not
    *Players Handbook* characters, so Curse is the stricter reading."""
    for race in (1, 2, 3):
        assert POOL.racial_limit(race, "cleric") > 0
        assert CURSE.racial_limit(race, "cleric") == 0
    assert POOL.racial_limit(6, "thief") == 8          # half-orc, AD&D exactly
    assert CURSE.racial_limit(7, "ranger") == levels.UNLIMITED
    assert POOL.racial_limit(7, "ranger") is None      # no such class here


def test_pool_of_radiance_thac0_is_the_games_own_table():
    """`LDA $1F1F,X` with `X = class * 9 + level`, stored `60 - THAC0` like
    every other to-hit number here. Entry 0 of the first row is never read --
    it is the `RTS` that ends the routine the table is glued to.

    This is the check that caught a thief being THAC0 19 at levels 5-8, where
    this file used to say 18. No specimen holds a thief past level 4.
    """
    gen = _pool_gen()
    table = _at(gen, POOL_THAC0, 4 * 9 + 1)
    for index, name in enumerate(POOL.class_order[:4]):
        for row in POOL.table(name):
            stored = table[index * 9 + row.level]
            assert row.thac0 == 60 - stored, (name, row.level)
    assert 60 - table[2 * 9 + 5] == 19     # the thief row, spelled out


def test_curse_thac0_is_the_games_own_table_for_the_casters():
    """`LDA $0E2C,X` and friends, indexed by the class's own level."""
    gen = _curse_gen()
    for address, name in zip(CURSE_THAC0, ("magic-user", "cleric", "thief")):
        table = _at(gen, address, 13)
        assert table[0] == 0, name         # level 0 is nobody
        for row in CURSE.table(name):
            assert row.thac0 == 60 - table[row.level], (name, row.level)


def test_curse_computes_the_fighter_groups_thac0_instead():
    """`LDA $7C98 / CLC / ADC #$27 / STA $7C71` -- the fighting level at record
    offset `0x098`, biased by the same `60 - value` as everything else, so
    THAC0 is `21 - level` and needs no table."""
    gen = _curse_gen()
    assert bytes([0xAD, 0x98, 0x7C, 0x18, 0x69, 0x27, 0x8D, 0x71, 0x7C]) in gen
    for name in ("fighter", "paladin", "ranger"):
        for row in CURSE.table(name):
            assert row.thac0 == 21 - row.level, (name, row.level)


def test_curse_experience_is_the_games_own_table():
    """Six rows of thirteen, three bytes each, **big-endian** -- the only
    big-endian number in the family."""
    gen = _curse_gen()
    order = ("magic-user", "cleric", "thief", "fighter", "paladin", "ranger")
    for index, name in enumerate(order):
        at = CURSE_EXPERIENCE - GEN_BASE + index * CURSE_XP_ROW
        for row in CURSE.table(name):
            k = at + (row.level - 1) * 3
            disk = int.from_bytes(gen[k:k + 3], "big")
            assert row.experience == disk, (name, row.level)


def test_the_fighters_eleventh_threshold_is_short_by_one_bit():
    """750001 would fit the row's `AD&D + 1` rule; the disk holds 749937,
    which is `0B 71 71` where `0B 71 B1` is expected. Only one of the player's
    Curse rips carries `GEN`, so a damaged image is not excluded -- the number
    kept is the number the disk holds, and a second rip would settle it."""
    assert CURSE.at_level("fighter", 11).experience == 749937
    assert CURSE.at_level("fighter", 11).experience == 750001 - 0x40


def test_curse_hit_dice_come_from_the_games_three_arrays():
    """`$161E` the die, `$1626` the first level that stops rolling it, `$162E`
    the flat hit points a level adds from then on."""
    gen = _curse_gen()
    die = _at(gen, CURSE_HIT_DIE, 8)
    stop = _at(gen, CURSE_HIT_DIE_STOP, 8)
    flat = _at(gen, CURSE_HIT_DIE_FLAT, 8)
    assert list(die) == [4, 8, 6, 10, 0, 0, 10, 8]
    for bit, name in enumerate(CURSE.class_order):
        if not name:
            continue
        for row in CURSE.table(name):
            dice = min(row.level, stop[bit] - 1)
            extra = max(0, row.level - (stop[bit] - 1)) * flat[bit]
            assert row.hp_max == dice * die[bit] + extra, (name, row.level)


def test_only_the_level_one_saves_are_on_the_disk():
    """Both games keep four five-byte rows and derive every other level, so the
    higher rows in `goldbox/levels.py` are AD&D transcription checked against
    stored records rather than against a table."""
    for gen, address in ((_pool_gen(), 0x1FA2),
                         (_curse_gen(), CURSE_LEVEL_1_SAVES)):
        rows = _at(gen, address, 20)
        for index, name in enumerate(("magic-user", "cleric", "thief",
                                      "fighter")):
            assert tuple(rows[index * 5:index * 5 + 5]) == \
                POOL.at_level(name, 1).saves, name


def test_pool_of_radiance_spell_slots_are_the_games_own():
    gen = _pool_gen()
    for address, name in ((POOL_SLOTS_CLERIC, "cleric"),
                          (POOL_SLOTS_MAGIC_USER, "magic-user")):
        rows = _at(gen, address, 8 * 4)
        for level in range(1, 7):          # the ceiling this game allows
            disk = tuple(rows[(level - 1) * 4:(level - 1) * 4 + 4])
            want = spells.capacity(1 if name == "magic-user" else 2,
                                   level, 0)[name]
            assert disk[:len(want)] == want, (name, level)


def test_curse_spell_slots_are_the_games_own():
    """`ECL65`, eleven magic-user rows of five then ten cleric rows."""
    ecl = gamedata.curse_file("ECL65")[2:]
    for start, count, name, bit in ((CURSE_SLOTS, 11, "magic-user", 1),
                                    (CURSE_SLOTS + 11 * 5, 10, "cleric", 2)):
        for level in range(1, count + 1):
            at = start + (level - 1) * 5
            disk = tuple(ecl[at:at + 5])
            want = spells.capacity(bit, level, 0,
                                   "curse-of-the-azure-bonds")[name]
            assert disk == want + (0,) * (5 - len(want)), (name, level)


# --- spell names -------------------------------------------------------------

def test_curse_reads_its_names_out_of_combat2():
    names = spells.load_spell_names(gamedata.curse_disks()[0],
                                    "curse-of-the-azure-bonds")
    assert len(names) >= 165
    assert names[1] == "BLESS"
    assert names[19] == "SHIELD"
    assert names[85] == "FIRE SHIELD"


def test_the_curse_pointers_are_mandatory_because_the_strings_overlap():
    """`SHIELD` is the last six bytes of `FIRE SHIELD`, so it is not a string
    start; splitting the block on NULs loses it and every id after it."""
    combat2 = gamedata.curse_file("COMBAT2")[2:]
    text = combat2[:spells.CURSE_OF_THE_AZURE_BONDS.text_end]
    at = text.find(b"SHIELD\x00")
    assert at > 0 and text[at - 1] != 0
    assert text.count(b"\x00") < spells.CURSE_OF_THE_AZURE_BONDS.entries - 15


def test_the_first_fifty_six_ids_are_the_same_spell_in_both_games():
    mine = spells.load_spell_names(gamedata.curse_disks()[0],
                                   "curse-of-the-azure-bonds")
    theirs = spells.load_spell_names(str(gamedata.game_disk("POOL1")))
    for spell_id in range(1, spells.LAST_SPELL + 1):
        assert mine.get(spell_id) == theirs.get(spell_id), spell_id


def test_the_curse_message_tail_starts_at_ninety_eight_not_a_hundred_and_one():
    """`IS ALIVE` and `IS DYING` are messages, and 100 -- after them -- is
    `BESTOW CURSE`, a real spell. `docs/116` §10 puts the boundary at 101."""
    names = spells.load_spell_names(gamedata.curse_disks()[0],
                                    "curse-of-the-azure-bonds")
    assert names[98] == "IS ALIVE" and names[99] == "IS DYING"
    assert names[100] == "BESTOW CURSE"
    assert spells.spell_group(100, "curse-of-the-azure-bonds") == ("cleric", 4)
    assert spells.spell_group(99, "curse-of-the-azure-bonds") is None


def test_an_unused_curse_slot_points_at_the_first_string():
    """63-65 and 95-97 point at `$E000`, so they read back as `BLESS` rather
    than as nothing, which is why `not_a_spell` has to be a list."""
    names = spells.load_spell_names(gamedata.curse_disks()[0],
                                    "curse-of-the-azure-bonds")
    for spell_id in (63, 64, 65, 95, 96, 97):
        assert names[spell_id] == "BLESS"
        assert spells.spell_group(spell_id, "curse-of-the-azure-bonds") is None


def test_spelln64_is_the_icon_editor_menu_in_both_games():
    for payload in (gamedata.game_file("SPELLN64"),
                    gamedata.curse_file("SPELLN64")[2:]):
        assert b"BLESS" not in payload and b"FIREBALL" not in payload
        assert b"WEAPON" in payload


# --- levelling, per title ----------------------------------------------------
# Issue #87. `goldbox/levelup.py` walked the spellbook to `spells.LAST_SPELLBOOK_
# SPELL`, which is 55 because that is Pool of Radiance's, so a Curse caster was
# offered about half its own list. The records below are built rather than read
# off a disk: what is being checked is the arithmetic, and a blank record with
# a class and a level in it is the whole input.

CURSE_KEY = "curse-of-the-azure-bonds"
POOL_KEY = "pool-of-radiance"
SSB_KEY = "secret-of-the-silver-blades"


def _caster(class_bits: int, level: int, experience: int = 1_000_000,
            wisdom: int = 12):
    """A blank record with just enough in it to level."""
    rec = CharacterRecord.blank()
    rec.set("name", "TESTER")
    rec.set("class_bits", class_bits)
    if class_bits & 1:
        rec.set("level_magic_user", level)
    if class_bits & 2:
        rec.set("level_cleric", level)
    rec.set("level", level)
    rec.set("experience", experience)
    rec.set("wisdom", wisdom)
    rec.set("constitution", 12)
    rec.set("thac0_base", 40)
    return rec


def test_a_curse_magic_user_reaching_seven_is_offered_fourth_level_spells():
    """81-90, `CHARM MONSTERS` upward, which Pool of Radiance does not have.

    The control matters more than the claim: the same record read as Pool of
    Radiance is offered nothing above 55, because 55 is where its list stops.
    """
    rec = _caster(0x01, 6)
    curse = levelup.learnable(rec, CURSE_KEY, level=7)
    assert set(range(81, 91)) <= set(curse)
    assert max(curse) == 90

    pool = levelup.learnable(rec, POOL_KEY, level=7)
    assert max(pool) == 55
    assert [s for s in curse if s <= 55] == pool


def test_a_curse_magic_user_below_seven_is_offered_no_fourth_level_spell():
    """The ceiling is still `(level + 1) // 2`, which is what makes 81-90
    a level-7 offer rather than something a level-5 mage sees."""
    rec = _caster(0x01, 4)
    assert max(levelup.learnable(rec, CURSE_KEY, level=5)) == 55


def test_the_cleric_grant_is_curses_own_table_at_every_level_it_reaches():
    """`goldbox/levelup.py`'s derivation against `GEN`'s bytes, id for id.

    The derivation is "every cleric spell of a level the title's slot table
    says it can cast, minus the ids that table never grants". This asserts it
    equals what the game's own grant routine would OR into the mask, which is
    the only check worth having: two independent readings of one fact.
    """
    grants = _grant_table(_curse_gen(), 0xCA)
    for level in sorted(grants):
        assert set(levelup._cleric_spell_ids(level, CURSE_KEY)) == grants[level], (
            level, sorted(set(levelup._cleric_spell_ids(level, CURSE_KEY))
                          ^ grants[level]))
    assert {58, 66, 67, 68, 69, 70} <= grants[7]
    assert 36 not in grants[9] and 100 not in grants[9]


def test_pool_of_radiances_cleric_grant_still_ors_whole_spell_levels():
    """The control, and the difference between the two titles.

    Pool of Radiance has no grant table: `GEN $20CF` ORs a whole spell level
    in, so 36 ANIMATE DEAD arrives with the rest of cleric 3. Curse replaced
    the routine with a table and left 36 out of it.
    """
    pool = set(levelup._cleric_spell_ids(5, POOL_KEY))
    assert 36 in pool
    assert pool == set(range(1, 9)) | set(range(22, 29)) | set(range(36, 45))
    assert 36 not in set(levelup._cleric_spell_ids(9, CURSE_KEY))


def test_the_castable_row_reaches_curses_fifth_spell_level():
    """`spells_castable` is six bytes and Pool of Radiance fills three.

    Curse's cleric 9 row is (4, 4, 3, 2, 1), so the fourth and fifth bytes
    stop being zero -- and they were, because the writer looped three times.
    """
    rec = _caster(0x02, 9, wisdom=9)
    row = levelup._spells_castable(rec, {"cleric": 9}, CURSE_KEY)
    assert [b >> 4 for b in row] == [4, 4, 3, 2, 1, 0]

    pool = levelup._spells_castable(rec, {"cleric": 6}, POOL_KEY)
    assert [b >> 4 for b in pool] == [3, 3, 2, 0, 0, 0]


def test_levelling_a_title_with_an_unread_trainer_refuses():
    """Silver Blades has its own `goldbox/levels.py` entry now (#187), and
    `plan` still refuses it: the trainer's own inputs -- the constitution
    hit-point bonus, the thief-skill racial adjustment, the wisdom bonus
    spells, the turning table -- remain unread or unattributed, so
    `levels.trainer_measured` is still False and `_tables_for` names the
    title in its refusal."""
    rec = _caster(0x02, 5)
    with pytest.raises(levelup.CannotLevel) as exc:
        levelup.plan(rec, "cleric", game=SSB_KEY)
    assert levels.SECRET_OF_THE_SILVER_BLADES.title in str(exc.value)

    # And the same rule read from the other end: nothing is claimed about how
    # many spells a Silver Blades cleric may memorise either.
    assert spells.capacity(0x02, 9, 18, SSB_KEY) == {}
    assert levelup._cleric_spell_ids(9, SSB_KEY) == []
