"""`automap/amigalevelup.py`: Level up as each Amiga trainer does it.

The proof is what WISH-1's live trainings measured at the games' own halls
(comments `9129985e`, `9f0896c0`, `974fd5e0`, `1fe52a55`), held here on
records built byte by byte rather than copied from any game file, and Pool of
Radiance's watched load of a converted party. The replays over records found
on the player's disks (read through `gamedisks.yaml`; they skip without them,
which is what CI does) are consistency with the read: nobody watched those
records being written.
"""

from __future__ import annotations

import re

import pytest

from automap import amigalevelup as lv
from goldbox import levels

POD_SIZE = 0x194


class Dice:
    """An `rng` that hands out the rolls a test names, in order."""

    def __init__(self, *rolls: int):
        self.rolls = list(rolls)

    def randint(self, low: int, high: int) -> int:
        roll = self.rolls.pop(0)
        assert low <= roll <= high, (roll, low, high)
        return roll


def put32(rec: bytearray, at: int, value: int) -> None:
    rec[at:at + 4] = value.to_bytes(4, "big", signed=True)


def get32(rec, at: int) -> int:
    return int.from_bytes(rec[at:at + 4], "big", signed=True)


def pod_xp(name: str, level: int) -> int:
    return levels.POOLS_OF_DARKNESS.at_level(name, level).experience


# --- Pools of Darkness: replayed over the game's own saves --------------------

def _pod_game_saved():
    """Every distinct character block in a `SavGam?.pty` on the Amiga disks:
    `(record, item nodes)`. A `.pty` is a saved game, found on the player's
    disk 3 rather than watched being written."""
    from automap import gamedisks
    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk, AmigaDiskError
    from tools.amiga import amigasaves

    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    seen = {}
    for _label, image in amigasaves.images():
        try:
            disk = AmigaDisk(image)
            entries = list(disk.walk())
        except (AmigaDiskError, ValueError):
            continue
        for path, _entry in entries:
            if not re.fullmatch(r"SavGam.\.pty", path.rsplit("/", 1)[-1], re.I):
                continue
            try:
                data = disk.read_file(path)
                save = amiga_savegame.pod_parse(data)
            except Exception:                       # not a party we can walk
                continue
            for block in save.characters:
                rec = data[block.at:block.at + POD_SIZE]
                nodes = [data[block.at + POD_SIZE + 20 * i:
                              block.at + POD_SIZE + 20 * (i + 1)]
                         for i in range(block.items)]
                seen.setdefault(bytes(rec), nodes)
    if not seen:
        pytest.skip("no Pools of Darkness saved game on the Amiga disks")
    return list(seen.items())


def test_the_pools_of_darkness_recompute_reproduces_every_game_saved_record():
    """THAC0, level, attacks, saves, class mask, ready flag and, for every
    thief, the skills: all of them, byte for byte. Capacity misses only the
    wearers of a readied item of power 0x81, whose doubling the recompute
    does not make and the ready handler does (PROBABLE that training resets
    it; `99d7ea58`)."""
    records = _pod_game_saved()
    capacity_misses = []
    for raw, nodes in records:
        rec = bytearray(raw)
        lv.pod_recompute(rec)
        for at, width in ((0x7F, 1), (0x89, 1), (0xAB, 1), (0x83, 5),
                          (0xB7, 1)):
            assert rec[at:at + width] == raw[at:at + width], hex(at)
        assert lv.pod_ready_flag(raw) == raw[0xCB]
        if raw[0x9D + 6]:
            assert rec[0x8B:0x93] == raw[0x8B:0x93]
        assert all(rec[0x159 + i] | raw[0x159 + i] == raw[0x159 + i]
                   for i in range(16)), "granted a spell the book lacks"
        if rec[0x169:0x184] != raw[0x169:0x184]:
            capacity_misses.append(nodes)
    assert all(any(node[7] and node[19] == 0x81 for node in nodes)
               for nodes in capacity_misses)
    assert len(capacity_misses) < len(records)


# --- Pools of Darkness: the trainer -----------------------------------------

def _pod_thief(level: int) -> bytearray:
    """A human thief ready for `level + 1`, dexterity 16, constitution 12."""
    rec = bytearray(POD_SIZE)
    rec[0x58] = 5
    rec[0x77] = 16
    rec[0x79] = 12
    rec[0x9D + 6] = level
    rec[0x89] = level
    put32(rec, 0x44, pod_xp("thief", level + 1))
    rec[0x81] = rec[0x191] = 20
    rec[0x83:0x88] = bytes([12, 11, 12, 15, 13])
    return rec


def test_a_pools_of_darkness_thief_saves_at_zero_on_every_column():
    """The Amiga's save table holds zeros in the thief's slot (`99d7ea58`)."""
    after = lv.apply_to(_pod_thief(4), lv.plan(_pod_thief(4), lv.POOLS_OF_DARKNESS,
                                               rng=Dice(3, 5)))
    assert after[0x9D + 6] == 5
    assert list(after[0x83:0x88]) == [0, 0, 0, 0, 0]
    assert after[0x7F] == 60 - 19              # thief 5's THAC0, stored 60 - x
    assert (after[0x81], after[0x191]) == (25, 25)
    assert after[0xCB] == 0


def test_a_pools_of_darkness_human_thief_takes_the_half_orc_skill_row():
    """Human is race 5 and its row is AD&D's half-orc, -5 +5 +5 0 0 +5 +5
    -10; a negative race value larger than the level value gives 0."""
    after = lv.apply_to(_pod_thief(4), lv.plan(_pod_thief(4), lv.POOLS_OF_DARKNESS,
                                               rng=Dice(3, 5)))
    # level 5 50 42 40 40 31 20 90 25, half-orc row, dexterity 16 0 -5 0 0 0
    assert list(after[0x8B:0x93]) == [45, 42, 45, 40, 31, 25, 95, 15]
    after = lv.apply_to(_pod_thief(1), lv.plan(_pod_thief(1), lv.POOLS_OF_DARKNESS,
                                               rng=Dice(3, 5)))
    # level 2 35 29 25 21 15 10 86 0: read languages 0 against -10 is 0
    assert list(after[0x8B:0x93]) == [30, 29, 30, 21, 15, 15, 91, 0]


def _pod_fighter(level: int, constitution: int = 18) -> bytearray:
    rec = bytearray(POD_SIZE)
    rec[0x58] = 5
    rec[0x79] = constitution
    rec[0x9D + 2] = level
    put32(rec, 0x44, pod_xp("fighter", level + 1))
    rec[0x81] = 80
    rec[0x191] = 50
    return rec


def test_pools_of_darkness_hit_points_keep_the_damage_and_stop_at_the_cap():
    """Below the cap: the higher of two d10s plus the fighter's bonus (+2,
    and +2 more at constitution 18); at it, a flat 3 and no bonus."""
    after = lv.apply_to(_pod_fighter(8), lv.plan(_pod_fighter(8), lv.POOLS_OF_DARKNESS,
                                                 rng=Dice(4, 9)))
    assert (after[0x81], after[0x191], after[0xB8]) == (93, 63, 9)
    after = lv.apply_to(_pod_fighter(9), lv.plan(_pod_fighter(9), lv.POOLS_OF_DARKNESS,
                                                 rng=Dice()))
    assert (after[0x81], after[0x191], after[0xB8]) == (83, 53, 3)


def test_a_pools_of_darkness_press_raises_every_ready_class():
    """A dwarf fighter 3 / thief 3: both rise, the rolls are added and
    divided between the two classes, and so is the bonus."""
    rec = bytearray(POD_SIZE)
    rec[0x58] = 2
    rec[0x77] = rec[0x79] = 15
    rec[0x9D + 2] = rec[0x9D + 6] = 3
    put32(rec, 0x44, 10 ** 6)
    rec[0x81], rec[0x191] = 30, 25
    plan = lv.plan(rec, lv.POOLS_OF_DARKNESS, rng=Dice(7, 2, 1, 4))
    after = lv.apply_to(rec, plan)
    assert plan.classes == ("fighter", "thief")
    assert (after[0x9D + 2], after[0x9D + 6]) == (4, 4)
    # (7 + 4) // 2 = 5 rolled, (1 + 1) // 2 = 1 bonus
    assert (after[0x81], after[0x191], after[0xB8]) == (36, 31, 5)


def test_pools_of_darkness_clamps_experience_before_it_trains():
    rec = _pod_fighter(1)
    put32(rec, 0x44, 10 ** 6)
    plan = lv.plan(rec, lv.POOLS_OF_DARKNESS, rng=Dice(5, 5))
    assert plan.experience == pod_xp("fighter", 3) - 1
    assert get32(lv.apply_to(rec, plan), 0x44) == plan.experience


def test_a_pools_of_darkness_magic_user_picks_from_the_trainers_menu():
    rec = bytearray(POD_SIZE)
    rec[0x58] = 0
    rec[0x73] = 18
    rec[0x79] = 14
    rec[0x9D + 5] = 1
    put32(rec, 0x44, pod_xp("magic-user", 2))
    rec[0x81] = rec[0x191] = 6
    with pytest.raises(lv.NeedsSpell) as asked:
        lv.plan(rec, lv.POOLS_OF_DARKNESS, rng=Dice(2, 3))
    assert asked.value.offers == list(range(9, 22))
    assert lv.offers(rec, lv.POOLS_OF_DARKNESS) == list(range(9, 22))
    after = lv.apply_to(rec, lv.plan(rec, lv.POOLS_OF_DARKNESS, rng=Dice(2, 3),
                                     learn=9))
    assert after[0x159 + (9 - 1) // 8] & 1 << (9 - 1) % 8
    with pytest.raises(lv.CannotLevel):
        lv.plan(rec, lv.POOLS_OF_DARKNESS, rng=Dice(2, 3), learn=29)


@pytest.mark.parametrize("change, why", [
    ({0x5E: 1}, "conscious"),
    ({0x9D + 1: 1}, "druid"),
])
def test_pools_of_darkness_refuses_what_the_trainer_would_not_train(change, why):
    rec = _pod_fighter(3)
    for at, value in change.items():
        rec[at] = value
    with pytest.raises(lv.CannotLevel, match=why):
        lv.plan(rec, lv.POOLS_OF_DARKNESS, rng=Dice(5, 5))


def test_a_regained_former_paladin_needs_the_effect_the_trainer_adds():
    """A human fighter 6 who left paladin at 5: the trainer adds effect 8,
    which a write to the record cannot, unless the character has it."""
    rec = _pod_fighter(6)
    rec[0xA4 + 3] = 5
    rec[0x8A] = 5
    with pytest.raises(lv.CannotLevel, match="effect 0x8"):
        lv.plan(rec, lv.POOLS_OF_DARKNESS, rng=Dice(5, 5))
    assert lv.plan(rec, lv.POOLS_OF_DARKNESS, rng=Dice(5, 5), effects=(8,)).classes


# --- Pool of Radiance --------------------------------------------------------

def test_the_pool_of_radiance_recompute_is_what_the_game_did_on_loading():
    """Slot B of the specimen is Wish's conversion; slot C is what the game
    wrote after loading it. The recompute turns each B into its C."""
    from tools.registry import specimens

    here = (specimens.tree_root() / "por-amiga"
            / "WISH-SPEC-por-amiga-outdoor-converted")
    if not here.is_dir():
        pytest.skip("no WISH-SPEC-por-amiga-outdoor-converted specimen")
    for n in range(1, 7):
        before = (here / f"CHRDATB{n}.sav").read_bytes()
        game = (here / f"CHRDATC{n}.sav").read_bytes()
        rec = bytearray(before)
        lv.por_recompute(rec)
        for at, width in ((0x2D, 1), (0x73, 1), (0xA3, 1), (0x6D, 5),
                          (0xB4, 6), (0x33, 56)):
            assert rec[at:at + width] == game[at:at + width], (n, hex(at))
        assert before[0x2D] != game[0x2D]


def test_pool_of_radiance_trains_garwan_as_the_hall_did():
    """`1fe52a55`: a human fighter 1, constitution 18, at 9000 and 8 hit
    points down: clamped to 4000, THAC0 40 to 41, three rolled and four of
    bonus, 14 to 21 and 6 to 13."""
    rec = bytearray(288)
    rec[0x2E], rec[0x2F], rec[0x14] = 7, 2, 18
    rec[0x98 + 2] = 1
    put32(rec, 0xAE, 9000)
    rec[0x32], rec[0x11D] = 14, 6
    plan = lv.plan(rec, lv.POOL_OF_RADIANCE, rng=Dice(3))
    after = lv.apply_to(rec, plan)
    assert plan.experience == 4000
    assert (after[0x2D], after[0x32], after[0x11D], after[0xB3]) == (41, 21, 13, 3)


def test_pool_of_radiance_thief_skills_add_dexterity():
    """`1fe52a55`: Goldleaf, an elf thief 2 with dexterity 19."""
    rec = bytearray(288)
    rec[0x2E], rec[0x13] = 2, 19
    rec[0x98 + 6] = 2
    lv.por_recompute(rec)
    assert list(rec[0x77:0x7F]) == [55, 44, 35, 38, 37, 15, 86, 0]


def test_pool_of_radiance_trains_one_class_a_press():
    """An elf fighter / magic-user / thief 1/1/1 at 5000 is clamped to 4000,
    as at the fighters' school (`1fe52a55`), and a press raises the one class
    the C64 Level up would pick."""
    rec = bytearray(288)
    rec[0x2E], rec[0x11], rec[0x13], rec[0x14] = 2, 17, 19, 15
    for slot in (2, 5, 6):
        rec[0x98 + slot] = 1
    put32(rec, 0xAE, 5000)
    assert lv.ready_classes(rec, lv.POOL_OF_RADIANCE) == ("magic-user",)
    plan = lv.plan(rec, lv.POOL_OF_RADIANCE, rng=Dice(2), learn=9)
    assert (plan.classes, plan.experience) == (("magic-user",), 4000)


# --- Curse of the Azure Bonds ------------------------------------------------

def test_the_curse_recompute_reproduces_every_record_on_the_game_disk():
    """The eleven pregenerated characters and the shipped saved game on
    Curse disk A: found, not watched, so this is consistency with the read.
    A watched load does not prove it either, since Curse's LOAD SAVED GAME
    left a converted party's derived bytes as they were."""
    from support.amigarecords import curse_characters

    for char in curse_characters():
        rec = bytearray(char.raw)
        lv.curse_recompute(rec, [item.raw for item in char.items])
        for at, width in ((0x73, 1), (0xE5, 1), (0x11D, 1), (0xDF, 5),
                          (0x12E, 18), (0x12C, 1)):
            assert rec[at:at + width] == char.raw[at:at + width], hex(at)


def _curse(race: int, levels_by_slot: dict, experience: int) -> bytearray:
    rec = bytearray(428)
    rec[0x74] = race
    for slot, level in levels_by_slot.items():
        rec[0x10A + slot] = level
    put32(rec, 0x128, experience)
    return rec


def test_curse_keeps_the_class_whose_threshold_is_largest_at_the_last_level():
    """`974fd5e0`: Galain, an elf fighter 4 / magic-user 4 at 23000, trained
    magic-user only; 32 to 35 and 10 to 13, one more rolled."""
    rec = _curse(2, {2: 4, 5: 4}, 23000)
    rec[0x19], rec[0x13], rec[0x78], rec[0x1A9] = 18, 17, 32, 10
    assert lv.ready_classes(rec, lv.CURSE) == ("magic-user",)
    plan = lv.plan(rec, lv.CURSE, rng=Dice(2, 1), learn=9)
    after = lv.apply_to(rec, plan)
    assert plan.experience == 23000
    assert (after[0x78], after[0x1A9], after[0x12D]) == (35, 13, 1)


def test_curses_clamp_reads_the_last_held_level_and_a_thief_is_refused():
    """`974fd5e0`: Sundra, a gnome fighter 4 / thief 5 at 100000, became
    70000, the fighter's level 7 less one, and trained fighter. The thief
    skills that training wrote cannot be copied from a record."""
    rec = _curse(3, {2: 4, 6: 5}, 100000)
    mask, clamp = lv._curse_ready(rec)
    assert clamp == 70000
    assert lv.ready_classes(rec, lv.CURSE) == ("fighter",)
    with pytest.raises(lv.CannotLevel, match="register"):
        lv.plan(rec, lv.CURSE, rng=Dice(5, 5))


# --- Secret of the Silver Blades ---------------------------------------------

def test_the_silver_blades_recompute_reproduces_the_shipped_party():
    """The six characters of the saved game shipped on Silver Blades disk 1:
    found, not watched, so this is consistency with the read."""
    from support.amigarecords import silver_blades_characters

    for char in silver_blades_characters():
        rec = bytearray(char.raw)
        lv.ssb_recompute(rec, [item.raw for item in char.items])
        for at, width in ((0x6A, 1), (0x88, 1), (0xBC, 1), (0x82, 5),
                          (0xCE, 28), (0xCC, 1)):
            assert rec[at:at + width] == char.raw[at:at + width], hex(at)


def test_silver_blades_trains_epona_as_the_hall_did():
    """`9f0896c0`: a human fighter 8, constitution 17, at 900000 and 61
    down: 500000, THAC0 47 to 48, saves to 8 9 10 9 11, seven rolled and
    three of bonus, 91 to 101 and 30 to 40."""
    rec = bytearray(340)
    rec[0x6B], rec[0x19] = 6, 17
    rec[0xAC + 2] = rec[0x88] = 8
    put32(rec, 0xC8, 900000)
    rec[0x70], rec[0x152] = 91, 30
    plan = lv.plan(rec, lv.SILVER_BLADES, rng=Dice(7, 3))
    after = lv.apply_to(rec, plan)
    assert plan.experience == 500000
    assert after[0x6A] == 48
    assert list(after[0x82:0x87]) == [8, 9, 10, 9, 11]
    assert (after[0x70], after[0x152], after[0xCD]) == (101, 40, 7)


def test_silver_blades_saves_read_past_the_table_for_a_former_cleric():
    """`9f0896c0`: a male human who left cleric at 8 for magic-user 1 saves
    1 1 2 3 4, and his THAC0 is 40."""
    rec = bytearray(340)
    rec[0x6B] = 6
    rec[0xAC + 5] = rec[0x88] = 1
    rec[0xB3] = rec[0x89] = 8
    lv.ssb_recompute(rec)
    assert list(rec[0x82:0x87]) == [1, 1, 2, 3, 4]
    assert rec[0x6A] == 40


def test_silver_blades_rolls_a_die_for_every_class_held():
    """An elf fighter 1 / magic-user 5 ready only as a fighter: both classes
    roll (CONFIRMED live, `9f0896c0`), and the sum is halved."""
    rec = bytearray(340)
    rec[0x6B], rec[0x19], rec[0x13] = 1, 14, 16
    rec[0xAC + 2], rec[0xAC + 5] = 1, 5
    put32(rec, 0xC8, 3000)
    rec[0x70], rec[0x152] = 30, 30
    plan = lv.plan(rec, lv.SILVER_BLADES, rng=Dice(6, 8, 2, 4))
    after = lv.apply_to(rec, plan)
    assert plan.classes == ("fighter",)
    assert after[0xCD] == (8 + 4) // 2


def test_silver_blades_refuses_a_thief():
    rec = bytearray(340)
    rec[0x6B] = 3
    rec[0xAC + 2], rec[0xAC + 6] = 7, 8
    put32(rec, 0xC8, 10 ** 6)
    with pytest.raises(lv.CannotLevel, match="dexterity"):
        lv.plan(rec, lv.SILVER_BLADES, rng=Dice(5, 5))


def test_a_title_with_no_copied_trainer_is_refused():
    assert not lv.supported("no-such-title")
    with pytest.raises(lv.CannotLevel):
        lv.plan(bytes(400), "no-such-title")
