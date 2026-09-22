"""Pools of Darkness' entry in `goldbox.levels`.

The first half pins the committed entry with no game data, which is what CI
runs. The second reads every table back off the player's own DOS `GAME.OVR`
and `GAME.EXE` through `tools/dos/dospodlevels.py`, and recomputes the
records under the install's `SAVE` directory from the entry; those tests
skip where the archives are not on the machine.

No game bytes are committed here: every number is read at run time or is one
of the integers `goldbox/levels.py` already carries.
"""

from __future__ import annotations

import pytest

from goldbox import levels

POD = "pools-of-darkness"

#: The cleric helper's six compares, `(wisdom from, cleric spell level)`, as
#: `tests/records/test_pod_spells.py` reads them off `GAME.OVR:0x03860C`.
WISDOM_COMPARES = ((13, 1), (14, 1), (15, 2), (16, 2), (17, 3), (18, 4))

CLASSES = ("cleric", "fighter", "paladin", "ranger", "magic-user", "thief")


def _engine_bonus(wisdom, compares=WISDOM_COMPARES, width=4):
    """The helper's compares as a cumulative row, the way `goldbox.levels`
    answers."""
    out = [0] * width
    for score, level in compares:
        if wisdom >= score:
            out[level - 1] += 1
    return tuple(out)


# --- the committed entry, with no game data ---------------------------------

def test_the_title_has_its_own_entry_rather_than_pool_of_radiances():
    assert levels.for_game(POD) is levels.POOLS_OF_DARKNESS
    assert levels.for_game(POD).key == POD
    assert levels.for_game(POD) is not levels.DEFAULT
    assert not levels.trainer_measured(POD)


def test_a_clerics_wisdom_bonus_is_the_engines_and_not_pool_of_radiances():
    """Wisdom 12 gives no bonus and 13 gives one, where Pool of Radiance's
    `$10AD` gives one and two; 18 reaches a fourth-level spell Pool of
    Radiance's three columns cannot hold; 19 gives what 18 gives, because
    the helper has no compare above 17."""
    for wisdom in range(3, 20):
        assert levels.wisdom_bonus_spells(wisdom, POD) == _engine_bonus(
            wisdom), wisdom
    assert levels.wisdom_bonus_spells(12, POD) == (0, 0, 0, 0)
    assert levels.wisdom_bonus_spells(12, levels.POOL_OF_RADIANCE) == (1, 0, 0)
    assert levels.wisdom_bonus_spells(13, POD)[0] == 1
    assert levels.wisdom_bonus_spells(13, levels.POOL_OF_RADIANCE)[0] == 2


def test_every_row_runs_to_the_last_level_the_engine_prices():
    title = levels.POOLS_OF_DARKNESS
    for name in CLASSES:
        rows = title.table(name)
        assert [r.level for r in rows] == list(
            range(1, levels.POD_LAST_LEVEL + 1)), name
        xp = [r.experience for r in rows]
        assert xp[0] == 0 and xp == sorted(xp) and len(set(xp)) == len(xp)
    # Past the clamp every level answers level 21's rows.
    for name in CLASSES:
        top = title.at_level(name, levels.POD_TABLE_CLAMP)
        last = title.at_level(name, levels.POD_LAST_LEVEL)
        assert (last.thac0, last.saves) == (top.thac0, top.saves), name


def test_the_lookups_nobody_has_read_answer_none():
    title = levels.POOLS_OF_DARKNESS
    assert title.ceiling("fighter") is None
    assert title.racial_limit(1, "fighter") is None
    assert title.thief_skill_row(5, 1, dexterity=16) is None
    assert title.dos_thief_skill_row(5, 1, dexterity=16) is None
    assert title.turning_level(5) is None
    assert levels.saving_throws({"fighter": 3}, game=POD) is None


def test_the_constitution_bonus_caps_everyone_but_the_fighter_group():
    title = levels.POOLS_OF_DARKNESS
    assert title.constitution_hp_bonus(18, fighter=True) == 4
    assert title.constitution_hp_bonus(18, fighter=False) == 2
    assert title.constitution_hp_bonus(3, fighter=False) == -2
    # Slots 3, 6 and 7 of the shared layout are the fighter, paladin, ranger.
    for slot, name in enumerate(title.class_order):
        if name is None:
            continue
        want = 4 if name in ("fighter", "paladin", "ranger") else 2
        assert title.constitution_hp_bonus(18, class_slot=slot) == want, name


# --- read off the player's own game -----------------------------------------

@pytest.fixture(scope="module")
def game():
    """`(tool, ovr, image, ds)` for the player's own Pools of Darkness."""
    tool = pytest.importorskip("tools.dos.dospodlevels")
    try:
        return (tool,) + tool.dospodtables.load()
    except FileNotFoundError as exc:
        pytest.skip(f"needs the DOS Pools of Darkness archives: {exc}")


def test_the_wisdom_compares_are_the_ones_this_file_pins(game):
    tool, ovr, _image, _ds = game
    tables = tool.dospodtables
    block = tables.dosspellslots.block_of(tables.RECORD_SIZE)[0]
    site = tables.dosspellslots.builder_site(ovr, block)
    cleric = next(b for b in tables.branches(ovr, site) if b.number == 0)
    bonus, _ceilings = tables.branch_gates(ovr, cleric)
    read = tuple((score + 1, slot - block + 1) for _, score, _, slot in bonus)
    assert read == WISDOM_COMPARES
    for wisdom in range(3, 20):
        assert levels.wisdom_bonus_spells(wisdom, POD) == _engine_bonus(
            wisdom, read), wisdom


def test_the_experience_thresholds_are_the_games_own(game):
    tool, ovr, image, ds = game
    read = tool.experience(ovr, image, ds)
    assert read["unreachable_from"] == levels.POD_LAST_LEVEL + 1
    for name in CLASSES:
        for level, want in read["rows"][name].items():
            assert levels.at_level(name, level, POD).experience == want, (
                name, level)
    # The druid's row prices no level at all.
    assert all(v >= 0xFFFFFFFF for v in read["rows"]["druid"].values())


def test_the_thac0_rows_are_the_games_own(game):
    tool, ovr, image, ds = game
    read = tool.thac0(ovr, image, ds)
    assert read["clamp"] == levels.POD_TABLE_CLAMP
    title = levels.POOLS_OF_DARKNESS
    for name in CLASSES:
        row = tuple(60 - v for v in read["rows"][name])
        assert dict(title.dos_thac0)[name] == row[1:], name
        for level in range(1, levels.POD_TABLE_CLAMP + 1):
            assert title.at_level(name, level).thac0 == row[level], (
                name, level)
    assert dict(title.dos_thac0_level0) == {
        name: 60 - row[0] for name, row in read["rows"].items()}


def test_the_saving_throw_rows_are_the_games_own(game):
    tool, ovr, image, ds = game
    read = tool.saves(ovr, image, ds)
    assert read["clamp"] == levels.POD_TABLE_CLAMP
    for name in CLASSES:
        for level in range(1, levels.POD_TABLE_CLAMP + 1):
            assert (levels.at_level(name, level, POD).saves
                    == read["rows"][name][level]), (name, level)


def test_the_hit_dice_are_the_games_own(game):
    tool, ovr, image, ds = game
    read = tool.hit_dice(ovr, image, ds)
    title = levels.POOLS_OF_DARKNESS
    assert read["rolls"] == title.hit_die_rolls
    for name in CLASSES:
        flat_from, first, sides, flat = read["rows"][name]
        roll_to = flat_from - 1
        assert levels.hit_die(name, POD) == sides, name
        assert title.hit_dice_rolled(name, 1) == first, name
        assert title.hit_dice_rolled(name, roll_to) == roll_to + first - 1
        assert title.flat_hit_points(name, roll_to) is None, name
        assert title.flat_hit_points(name, roll_to + 1) == flat, name


def test_the_attack_bands_are_the_games_own(game):
    tool, ovr, _image, _ds = game
    read = tool.attacks(ovr)
    for name in CLASSES:
        bands = read["bands"].get(name, ())
        for level in range(1, levels.POD_LAST_LEVEL + 1):
            want = 2
            for above, value in bands:
                if level > above:
                    want = max(want, value)
            got = levels.at_level(name, level, POD).attacks
            assert int(got * 2) == want, (name, level)


def test_the_constitution_bonus_is_the_games_own(game):
    tool, ovr, image, ds = game
    read = tool.constitution(ovr, image, ds)
    title = levels.POOLS_OF_DARKNESS
    assert read["extra_for"] == {"fighter", "paladin", "ranger"}
    for score in range(3, 26):
        assert title.constitution_hp_bonus(score, fighter=True) == (
            read["fighter"][score]), score
        assert title.constitution_hp_bonus(score, fighter=False) == (
            read["other"][score]), score


def test_the_found_records_recompute_from_the_entry(game):
    """THAC0, the five saves and `attack_forms` of every record under the
    archive install's `SAVE` directory, out of `goldbox.levels` rather than
    the tool: best THAC0 over the classes with the level-0 entry for the
    rest, the lowest save per column over the classes held, the best attack
    band. None of these records reaches the column-0 constitution
    adjustment the entry leaves unread (constitution 19 up, or the
    item-list flag).

    The records were found in the archives and nobody watched them being
    written, so this checks our strides, clamps and dual-class level against
    twelve independent characters; it is not evidence about the game."""
    tool = game[0]
    found = tool.records()
    if not found:
        pytest.skip("no Pools of Darkness records under the install")
    order = tool.CLASSES
    title = levels.POOLS_OF_DARKNESS
    for path in found:
        record = path.read_bytes()
        held = {name: level for name, level in
                zip(order, tool.effective_levels(record)) if level}
        thac0 = title.dos_engine_thac0(held)
        assert record[0xAC] == 60 - thac0, path.name
        rows = [title.at_level(name, level).saves
                for name, level in held.items()]
        saves = tuple(min(column) for column in zip(*rows))
        assert tuple(record[0x132:0x137]) == saves, path.name
        attacks = max(title.at_level(name, level).attacks
                      for name, level in held.items())
        assert record[0x168] == int(attacks * 2), path.name
