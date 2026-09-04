from __future__ import annotations

"""Curse of the Azure Bonds' training hall, read out of its own overlays.

`#18 (Measure Curse's trainer so Level Up works there)`. `docs/135-levelling.md`
records Pool of Radiance's trainer at twenty-five addresses and **not one of
them means anything in Curse**, so every table here was found the way
`tools/trainerscan.py` finds them: by the instruction that touches the
character record at `$7C00`, working outwards to the table two instructions
away.

Nothing here is transcribed. Each test either expands one of Curse's own tables
and compares it with what `goldbox/levels.py` and `goldbox/spells.py` claim, or
reproduces a field of a character SSI shipped from the inputs that character
stores. The disk gets to contradict us, which is the whole point.

**The sample for the "reproduces a real character" half is one party of six**,
the pre-generated party in `SAVEAZURE` on side C, all at level 5. That is small
and it is what exists: there are no player saves and no exported characters on
these disks. Where a claim rests on those six it says so.

`GEN` runs at `$0800` whatever its header says. **`ECL65` runs at `$8000`** --
not the `$9900` `docs/50-experiments.md` records for a different overlay --
which is settled by its own `LDA $888D,X` reading the magic-user spell-slot
rows that `tests/test_curselevels.py` reaches at payload offset `0x88D`.

Every test skips when the Curse disks are absent, and none of the game's bytes
is committed: `AGENTS.md` forbids that, test fixture or not.
"""

import pytest

from goldbox import levels, spells
from goldbox.savegame import load_save
from tests import gamedata

CURSE = levels.CURSE_OF_THE_AZURE_BONDS

#: Where the two overlays run, and where the working character sits.
GEN_BASE = 0x0800
ECL65_BASE = 0x8000

#: `GEN`. Found by `tools/trainerscan.py --game curse --file GEN`; the
#: routine that reads each one is named beside it.
SAVE_ROWS = 0x0F49          # $0E9A: level-1 row, 4 classes x 5 columns
SAVE_MASKS = 0x0F5D         # $0EB1: 4 x 5 x 4 bytes, two bits a level
HP_BONUS = 0x11D7           # $126D: indexed by the constitution score
HIT_DIE = 0x161E            # $15FC: sides, by class slot
HIT_DIE_STOP = 0x1626       # $15F2: first level that stops rolling
HIT_DIE_FLAT = 0x162E       # $15F7: what it adds instead
CON_BONUS_STOP = 0x1282     # $125E: last level the constitution bonus counts
THIEF_LEVEL_ROWS = 0x1004   # $0FBA: 9 rows of 8
THIEF_RACE_ROWS = 0x1064    # $0FF7: 8 rows of 8, by race - 1
THIEF_DEX_ROWS = 0x10A4     # $0FDA: 17 rows of 8, by max(0, dexterity - 9)
EXPERIENCE = 0x136E         # $149B: 6 rows x 13 x 3 bytes, big-endian
XP_ROW = 39
MU_SPELL_LEVELS = 0x273F    # $2230: magic-user spell level by id, 9 = never

#: `ECL65`, as payload offsets, because that is how the two rows already in
#: `goldbox/levels.py` are cited. Add `ECL65_BASE` for the address the code uses.
SLOTS_MAGIC_USER = 0x88D
SLOTS_CLERIC = 0x8C4
WISDOM_BONUS = 0x906        # $8902: the spell level each point of wisdom buys

CLASS_SLOTS = ("magic-user", "cleric", "thief", "fighter",
               None, None, "paladin", "ranger")


def _gen() -> bytes:
    return gamedata.curse_file("GEN")[2:]


def _ecl65() -> bytes:
    return gamedata.curse_file("ECL65")[2:]


def _at(payload: bytes, address: int, count: int, base: int = GEN_BASE) -> bytes:
    start = address - base
    assert 0 <= start <= len(payload) - count, (
        f"${address:04X} is outside a {len(payload)}-byte overlay")
    return payload[start:start + count]


def _signed(value: int) -> int:
    return value - 256 if value > 127 else value


def _party():
    """The six characters SSI shipped, out of the whole `SAVEAZURE`."""
    for disk in gamedata.curse_disks(engine_only=False):
        entry = disk.find(b"SAVEAZURE")
        if entry is None:
            continue
        try:
            if len(disk.read_file(entry)) < 7000:
                continue                  # the truncated demo copy on side A
            return load_save(disk)[1].characters
        except Exception:
            continue
    pytest.skip("no Curse side here carries a whole SAVEAZURE")


# --- saving throws -----------------------------------------------------------

def _saves(payload: bytes, class_slot: int, level: int) -> tuple[int, ...]:
    """One class's row, expanded out of `GEN`'s own two tables.

    `$0E7E` starts every column at 20, then per class takes the level-1 row at
    `$0F49` and subtracts, once a level, a **two-bit field** out of the 32-bit
    mask at `$0F5D + class * 20 + column * 4`. The pair is read by
    `LSR $2C9B / ROR / ROR / ROR $2C98 / ROL $B0` twice, so the first bit out
    is the pair's *high* bit -- which is why `(low << 1) | high` below is the
    game's arithmetic and the obvious reading is not.
    """
    rows = _at(payload, SAVE_ROWS, 20)
    masks = _at(payload, SAVE_MASKS, 80)
    out = []
    for column in range(5):
        value = rows[class_slot * 5 + column]
        at = class_slot * 20 + column * 4
        word = int.from_bytes(masks[at:at + 4], "little")
        for _ in range(level):
            low, word = word & 1, word >> 1
            high, word = word & 1, word >> 1
            value -= (low << 1) | high
        out.append(value)
    return tuple(out)


def test_every_curse_saving_throw_row_is_read_out_of_gen():
    """All 45 rows `goldbox/levels.py` carries for Curse, from Curse's bytes.

    The module's own note says Curse *"keeps only the level-1 rows on disk
    (`GEN` `$0F49`) and derives the rest"*, and the rest of every row in that
    file is a transcription of AD&D 1st edition. The improvement masks are on
    disk too, at `$0F5D`, and expanding them reproduces the transcription
    exactly -- so these are the game's numbers now and not a table that happens
    to agree with one.
    """
    payload = _gen()
    checked = 0
    for slot, name in enumerate(CLASS_SLOTS[:4]):
        for level in range(1, CURSE.ceiling(name) + 1):
            row = CURSE.at_level(name, level)
            assert row.saves == _saves(payload, slot, level), (name, level)
            checked += 1
    assert checked == 45, checked


def test_the_paladin_and_ranger_saves_are_the_fighter_rows_the_game_uses():
    """`$0E73` feeds the fighter column with `attack_level` at `0x098`, which
    `$0DF1` sets to the best of fighter, paladin and ranger -- so a paladin and
    a ranger save off the fighter row, and `$0F01` then takes 2 off all five
    columns for a paladin. Both are what `goldbox/levels.py` says, and both are
    now read rather than argued from AD&D.
    """
    payload = _gen()
    assert _at(payload, 0x0DF1, 3) == b"\xAD\xCC\x7C"       # LDA level_fighter
    assert _at(payload, 0x0E04, 3) == b"\x8D\x98\x7C"       # STA attack_level
    assert _at(payload, 0x0E73, 3) == b"\xAD\x98\x7C"       # LDA attack_level
    assert _at(payload, 0x0F01, 5) == b"\xAD\xCF\x7C\xF0\x12"   # LDA paladin
    assert _at(payload, 0x0F0B, 3) == b"\x38\xE9\x02"           # SEC / SBC #$02
    for level in range(1, CURSE.ceiling("paladin") + 1):
        fighter = _saves(payload, 3, level)
        assert CURSE.at_level("paladin", level).saves == tuple(
            max(0, v - 2) for v in fighter), level
    for level in range(1, CURSE.ceiling("ranger") + 1):
        assert CURSE.at_level("ranger", level).saves == _saves(payload, 3, level)


def test_the_racial_saving_throw_bonus_is_three_columns_and_three_races():
    """`GEN $0F19`, and it settles two fields nothing had read for Curse.

    `LDA race / CMP #$06 / BCS out / AND #$01 / BEQ out` admits races 1, 3 and
    5 and nobody else, which is `sturdy_races`. `LDA constitution / ASL A`
    then a divide by 7 is `constitution * 2 // 7`, the same expression Pool of
    Radiance's `$2359` computes. The subtract loop steps `DEX / DEX`, so it
    reaches columns 4, 2 and 0 -- which is `constitution_save_columns`, read
    off the disk instead of inferred from MAGNUS's two records.
    """
    payload = _gen()
    assert _at(payload, 0x0F19, 11) == (
        b"\xAD\x72\x7C"          # LDA race
        b"\xC9\x06\xB0\x28"      # CMP #$06 / BCS out
        b"\x29\x01\xF0\x24")     # AND #$01 / BEQ out
    assert _at(payload, 0x0F24, 4) == b"\xAD\x18\x7C\x0A"   # LDA con / ASL A
    assert _at(payload, 0x0F2E, 2) == b"\xA9\x07"           # LDA #$07, the divisor
    assert _at(payload, 0x0F44, 3) == b"\xCA\xCA\x10"       # DEX / DEX / BPL
    assert CURSE.sturdy_races == (1, 3, 5)
    assert CURSE.constitution_save_columns == (0, 2, 4)


def test_the_shipped_party_stores_the_saves_this_derivation_gives():
    """Six characters, five columns each: 30 of 30.

    None of the six is a sturdy race, so this corroborates the rows and the
    best-column rule and says nothing about the constitution bonus.
    """
    payload = _gen()
    stored = ("save_paralysis", "save_petrification", "save_wands",
              "save_breath", "save_spell")
    checked = 0
    for slot in _party():
        record = slot.record
        rows = []
        for index, name in enumerate(CLASS_SLOTS):
            level = record.get(f"level_{name.replace('-', '_')}") if name else 0
            if not level:
                continue
            row = _saves(payload, min(index, 3), level)
            if name == "paladin":
                row = tuple(max(0, v - 2) for v in row)
            rows.append(row)
        assert rows, record.name
        best = tuple(min(row[c] for row in rows) for c in range(5))
        assert record.get("race") not in CURSE.sturdy_races, record.name
        assert tuple(record.get(f) for f in stored) == best, record.name
        checked += 5
    assert checked == 30, checked


# --- hit points --------------------------------------------------------------

def test_the_constitution_hit_point_table_has_no_floor_and_caps_by_score():
    """`GEN $126D`, and the difference from Pool of Radiance is at both ends.

    One row at `$11D7` indexed by the raw score, and the "not a fighter" cap is
    done by clamping the *score*: `CPY #$03 / BCS / CPX #$11 / BCC / LDX #$10`
    reads 16 for any class slot below 3 whose constitution is 17 or more.

    **The table starts at 1, not 15.** Pool of Radiance's `$2471` refuses to
    look below 15 (`CPX #$0F`) and `levels.constitution_hp_bonus` refuses with
    it; Curse indexes straight in, and the first six entries are -2 and -1. So
    a Curse character with a constitution of 6 or less loses hit points a
    level and `goldbox/levels.py` would write that it gains none.
    """
    payload = _gen()
    assert _at(payload, 0x126D, 3) == b"\xAE\x18\x7C"        # LDX constitution
    assert _at(payload, 0x1270, 8) == (
        b"\xC0\x03\xB0\x06"      # CPY #$03 / BCS
        b"\xE0\x11\x90\x02")     # CPX #$11 / BCC
    assert _at(payload, 0x1278, 2) == b"\xA2\x10"            # LDX #$10
    table = _at(payload, HP_BONUS, 26)
    assert [_signed(b) for b in table[1:7]] == [-2, -2, -2, -1, -1, -1]
    assert list(table[7:15]) == [0] * 8                      # 7 to 14
    assert list(table[15:19]) == [1, 2, 3, 4]                # 15 to 18, fighter
    # From 7 up the two titles agree, which is why nothing has been visibly
    # wrong: a non-fighter's score is capped to 16, and 16 is +2 in both.
    for score in range(7, 19):
        assert table[score] == levels.constitution_hp_bonus(score, fighter=True)
        assert table[min(score, 16)] == levels.constitution_hp_bonus(score)
    # Below 7 they do not, and it is `goldbox/levels.py` that is not Curse's.
    for score in range(1, 7):
        assert _signed(table[score]) < 0, score
        assert levels.constitution_hp_bonus(score, fighter=True) == 0, score


def test_the_hit_die_triple_is_the_progression_this_module_already_carries():
    """`$161E`, `$1626`, `$162E`, eight entries each in class-slot order.

    `goldbox/levels.py` builds Curse's rows from `die`, `roll_to` and `flat`,
    and this is where all three came from: `$1626` is `roll_to + 1`, because
    the test is `CMP $1626,X / BCC roll`.
    """
    payload = _gen()
    die = _at(payload, HIT_DIE, 8)
    stop = _at(payload, HIT_DIE_STOP, 8)
    flat = _at(payload, HIT_DIE_FLAT, 8)
    expect = {"magic-user": (4, 12, 1), "cleric": (8, 10, 2),
              "thief": (6, 11, 2), "fighter": (10, 10, 3),
              "paladin": (10, 10, 3), "ranger": (8, 11, 2)}
    for slot, name in enumerate(CLASS_SLOTS):
        if name is None:
            assert die[slot] == stop[slot] == flat[slot] == 0, slot
            continue
        assert (die[slot], stop[slot], flat[slot]) == expect[name], name
        row = CURSE.at_level(name, CURSE.ceiling(name))
        dice, _, tail = row.hit_dice.partition("d")
        sides, _, extra = tail.partition("+")
        assert int(sides) == die[slot], name
        assert int(dice) == stop[slot] - 1, name             # roll_to
        gained = CURSE.ceiling(name) - (stop[slot] - 1)
        assert int(extra or 0) == max(0, gained) * flat[slot], name


def test_the_hit_die_is_rolled_twice_and_the_better_roll_kept():
    """`GEN $15FC`, and Pool of Radiance does not do this.

    Two `LDY $161E,X / JSR $2F6A` in a row, then `CMP $4C / BCS / LDA $4C` --
    the larger of two rolls. Pool of Radiance's `$2037` rolls once and floors a
    *single-class fighter* at 4 (`CMP #$04` against `class_bits == 8`); Curse
    has no such floor and gives every class the better of two dice instead.

    So `levelup.roll_hit_points` is not Curse's rule, and a replay of a Curse
    training has to be handed the roll rather than asked for one.
    """
    payload = _gen()
    assert _at(payload, 0x15FC, 6) == b"\xBC\x1E\x16\x20\x6A\x2F"
    assert _at(payload, 0x1607, 6) == b"\xBC\x1E\x16\x20\x6A\x2F"
    assert _at(payload, 0x160D, 6) == b"\xC5\x4C\xB0\x02\xA5\x4C"
    assert b"\xC9\x04" not in _at(payload, 0x15E1, 0x3D), "a floor of 4"


def _hp_max(payload: bytes, record) -> int:
    """`hp_max` as `GEN $11F1` computes it, for a character with no dual class.

    Per class slot, `min(level, roll_to) * bonus(constitution, slot)`; summed;
    one extra bonus for a ranger, because a ranger is 2d8 at level 1 (`$128A`);
    divided by how many classes the character has (`$11AB`); plus `hp_rolled`,
    floored at the character's level.

    That is three departures from `levelup.plan`, which uses the character's
    single `level`, one constitution row chosen by the fighter bit, and no
    division at all.
    """
    table = _at(payload, HP_BONUS, 26)
    stop = _at(payload, CON_BONUS_STOP, 8)
    constitution = record.get("constitution")
    total = 0
    classes = 0
    for slot, name in enumerate(CLASS_SLOTS):
        level = record.get(f"level_{name.replace('-', '_')}") if name else 0
        if not level:
            continue
        classes += 1
        score = min(constitution, 16) if slot < 3 else constitution
        total += min(level, stop[slot] - 1) * _signed(table[score])
    if record.get("level_ranger"):
        total += _signed(table[constitution])
    if total >= 0 and classes:
        total //= classes
    return max(record.get("level"), record.get("hp_rolled") + total)


def test_the_shipped_partys_hit_points_come_out_of_this_derivation():
    """6 of 6, against 3 of 6 for what `goldbox/levelup.py` writes today.

    The three it gets wrong are the paladin (+5), the ranger (+8) and the
    multi-class fighter/thief (-1), which are exactly the three cases the
    formula differs in. All six are level 5, so nothing here tests the
    `roll_to` cap or the 200 clamp.
    """
    payload = _gen()
    checked = 0
    for slot in _party():
        record = slot.record
        assert _hp_max(payload, record) == record.get("hp_max"), record.name
        checked += 1
    assert checked == 6, checked


def test_todays_hit_point_formula_disagrees_with_three_of_the_six():
    """The negative half, so the fix cannot land without something going green.

    If `levelup`'s formula is ever made Curse's, this test is what says so --
    it fails, and the count in its name is what has to change.
    """
    wrong = []
    for slot in _party():
        record = slot.record
        bits = record.get("class_bits") or 0
        theirs = record.get("hp_rolled") + record.get("level") * (
            levels.constitution_hp_bonus(record.get("constitution"),
                                         fighter=bool(bits & 8)))
        if theirs != record.get("hp_max"):
            wrong.append((record.name, theirs, record.get("hp_max")))
    assert [w[0] for w in wrong] == ["PALADIN", "RANGER", "F/T"], wrong


# --- the turning level -------------------------------------------------------

def _turn_power(payload: bytes, cleric: int, paladin: int) -> int:
    """`GEN $113F`, which is arithmetic where Pool of Radiance has a table."""
    del payload
    best = max(cleric, max(0, paladin - 2))
    if best < 4:
        return best
    return min(best + 1, 10)


def test_the_turning_level_is_arithmetic_and_agrees_with_pool_of_radiance():
    """`$113F`: `max(cleric, paladin - 2)`, then `+ 1` from 4 up, capped at 10.

    `LDA level_paladin / SEC / SBC #$02`, then the larger of that and the
    cleric level, then `CMP #$04 / BCC store / ADC #$00 / CMP #$0B / BCC store
    / LDA #$0A`. Over a Curse cleric's whole range that is `1 2 3 5 6 7 8 9 10
    10`, which is Pool of Radiance's `$2399` table entry for entry -- a
    different mechanism reaching the same numbers, plus a paladin branch Pool
    of Radiance has no class for.
    """
    payload = _gen()
    assert _at(payload, 0x113F, 6) == b"\xAD\xCF\x7C\x38\xE9\x02"
    assert _at(payload, 0x1149, 6) == b"\xCD\xCA\x7C\xB0\x03\xAD"
    assert _at(payload, 0x1151, 4) == b"\xC9\x04\x90\x08"
    assert _at(payload, 0x1157, 6) == b"\xC9\x0B\x90\x02\xA9\x0A"
    assert _at(payload, 0x115D, 3) == b"\x8D\xA4\x7C"        # STA turn_power
    pool = levels.POOL_OF_RADIANCE.turn_power
    for level in range(1, CURSE.ceiling("cleric") + 1):
        assert _turn_power(payload, level, 0) == pool[level - 1], level


def test_the_shipped_cleric_and_paladin_store_that_turning_level():
    payload = _gen()
    seen = {}
    for slot in _party():
        record = slot.record
        want = _turn_power(payload, record.get("level_cleric"),
                           record.get("level_paladin"))
        assert record.get("turn_power") == want, record.name
        seen[record.name] = want
    assert seen["CLERIC"] == 6 and seen["PALADIN"] == 3, seen


# --- thief skills ------------------------------------------------------------

def _thief_skills(payload: bytes, level: int, race: int, dexterity: int):
    """`GEN $0FAD`: the level row, plus a **dexterity** row, plus a racial row."""
    def row(address: int, index: int):
        return [_signed(b) for b in _at(payload, address + index * 8, 8)]

    out = row(THIEF_LEVEL_ROWS, min(max(level, 1), 9) - 1)
    out = [a + b for a, b in zip(out, row(THIEF_DEX_ROWS, max(0, dexterity - 9)))]
    if race >= 1:
        out = [a + b for a, b in zip(out, row(THIEF_RACE_ROWS, race - 1))]
    return [v & 0xFF for v in out]


def test_curses_thief_skills_read_dexterity_and_pool_of_radiances_do_not():
    """`docs/135-levelling.md` says dexterity is not folded in. That is Pool of
    Radiance's `$1FEC`, which reads no ability score, and it is not Curse's.

    `$0FC6 LDA $7C17 / SEC / SBC #$09` indexes a 17-row table at `$10A4` by
    `max(0, dexterity - 9)`, and it is AD&D 1st edition's thief dexterity
    adjustment: `-15 -10 -10 -20 -10` at 9, nothing from 13 to 15, `+10 +15 +5
    +10 +10` at 18.
    """
    payload = _gen()
    assert _at(payload, 0x0FC6, 6) == b"\xAD\x17\x7C\x38\xE9\x09"
    assert _at(payload, 0x0FDA, 3) == b"\x7D\xA4\x10"        # ADC $10A4,X
    assert _at(payload, 0x0FF7, 3) == b"\x7D\x64\x10"        # ADC $1064,X

    def row(address, index):
        return [_signed(b) for b in _at(payload, address + index * 8, 8)]

    assert row(THIEF_DEX_ROWS, 0) == [-15, -10, -10, -20, -10, 0, 0, 0]
    assert row(THIEF_DEX_ROWS, 4) == [0] * 8                 # dexterity 13
    assert row(THIEF_DEX_ROWS, 9) == [10, 15, 5, 10, 10, 0, 0, 0]   # 18
    # Pool of Radiance's routine reads level and race and stops.
    pool = gamedata.game_file("GEN")
    assert pool[0x1FEC - GEN_BASE:0x1FEC - GEN_BASE + 3] == b"\xAE\xCB\x6B"
    assert b"\x17\x6B" not in pool[0x1FEC - GEN_BASE:0x2020 - GEN_BASE]


def test_curses_racial_thief_rows_are_not_pool_of_radiances():
    """Rows 1 and 2 are identical and rows 3 to 6 are not.

    Curse's are AD&D 1st edition verbatim -- gnome `0 5 10 5 5 10 -15 0`,
    half-elf `10 0 0 0 5 0 0 0`, halfling `5 5 5 10 15 5 -15 -5`, half-orc
    `-5 5 5 0 0 5 5 -10`. Pool of Radiance's carry the same numbers in
    different columns, which is why `thief_skill_race` cannot be shared.
    """
    payload = _gen()

    def row(index):
        return tuple(_signed(b) for b in _at(payload, THIEF_RACE_ROWS + index * 8, 8))

    pool = levels.POOL_OF_RADIANCE.thief_skill_race
    assert row(0) == pool[0] and row(1) == pool[1]
    for index in range(2, 6):
        assert row(index) != pool[index], index
    assert row(2) == (0, 5, 10, 5, 5, 10, -15, 0)            # gnome
    assert row(3) == (10, 0, 0, 0, 5, 0, 0, 0)               # half-elf
    assert row(4) == (5, 5, 5, 10, 15, 5, -15, -5)           # halfling
    assert row(5) == (-5, 5, 5, 0, 0, 5, 5, -10)             # half-orc


def test_the_shipped_thief_stores_the_eight_skills_this_gives():
    """One thief, eight columns, and the level row alone does not reach them.

    F/T is a half-elf thief 5 with dexterity 18 and stores
    `70 57 45 50 46 20 90 25`. `LevelTables.thief_skill_row` has no tables for
    Curse and returns None, and Pool of Radiance's rows applied to the same
    character give `50 42 40 45 31 20 90 30`.
    """
    payload = _gen()
    thieves = 0
    for slot in _party():
        record = slot.record
        level = record.get("level_thief")
        if not level:
            continue
        thieves += 1
        want = _thief_skills(payload, level, record.get("race"),
                             record.get("dexterity"))
        assert want == [record.get(f) & 0xFF for f in (
            "thief_pick_pockets", "thief_open_locks", "thief_find_traps",
            "thief_move_silently", "thief_hide_in_shadows",
            "thief_hear_noise", "thief_climb_walls",
            "thief_read_languages")], record.name
        assert CURSE.thief_skill_row(level, record.get("race")) is None
    assert thieves == 1, thieves


# --- experience --------------------------------------------------------------

def test_the_experience_rows_and_the_clamp_come_out_of_one_table():
    """`$136E`, 6 rows of 13 three-byte big-endian numbers, and `$1458` reads
    row `level` of it -- the threshold for the level *after* the stored one.

    Pool of Radiance needs `clamp_thresholds` as a separate field because its
    rows are nine wide and the tenth entry lands in the next class's slot 0.
    Curse's are thirteen wide and **every class has a real entry one past its
    ceiling**, so the clamp is the same table: 750001, 675001, 660001,
    1250001, 1400001 and 975001. Those six are Silver Blades' *next*
    thresholds, measured separately off a different file.
    """
    payload = _gen()
    rows = {}
    for index, name in enumerate(
            ("magic-user", "cleric", "thief", "fighter", "paladin", "ranger")):
        start = EXPERIENCE + index * XP_ROW
        rows[name] = [int.from_bytes(_at(payload, start + n * 3, 3), "big")
                      for n in range(13)]
        assert rows[name][:CURSE.ceiling(name)] == [
            r.experience for r in CURSE.table(name)], name
    assert [rows[n][CURSE.ceiling(n)] for n in rows] == [
        750001, 675001, 660001, 1250001, 1400001, 975001]
    assert CURSE.clamp_thresholds == (), "still unread by goldbox/levels.py"


def test_the_clamp_skips_a_humans_dual_classed_old_class():
    """`$1470`, and it names two bytes `goldbox/layout.py` calls `gap_0b9`.

    `LDA race / CMP #$07 / BNE / LDA $7CBA / BEQ / CPX $7CB9 / BEQ skip`: for a
    human with a non-zero `0x0BA`, the class slot in `0x0B9` takes no part in
    the maximum. `$20A3` is the other half -- it writes `0x0BA` back into that
    slot's level and ORs the class bit into `class_bits`. So `0x0B9` is the
    **dual-classed old class slot** and `0x0BA` its **old level**.
    """
    payload = _gen()
    assert _at(payload, 0x1470, 15) == (
        b"\xAD\x72\x7C\xC9\x07\xD0\x0A"      # LDA race / CMP #$07 / BNE
        b"\xAD\xBA\x7C\xF0\x05"              # LDA $7CBA / BEQ
        b"\xEC\xB9\x7C")                     # CPX $7CB9
    assert _at(payload, 0x20A3, 3) == b"\xAD\xBA\x7C"
    assert _at(payload, 0x20AD, 6) == b"\xAE\xB9\x7C\x9D\xC9\x7C"
    assert _at(payload, 0x20B3, 9) == (
        b"\xBD\x82\x0B"                      # LDA classbit,X
        b"\x0D\xEB\x7C\x8D\xEB\x7C")         # ORA / STA class_bits


# --- spells ------------------------------------------------------------------

def test_curses_magic_user_trainer_builds_a_menu_and_does_not_grant_a_row():
    """The question `#89 (Silver Blades' trainer grants spells from a table,
    and goldbox/levelup.py offers them from a menu)` left open, answered.

    `GEN $2200` is the magic-user's step of the level-up sequence. It computes
    the castable spell level as `LSR A / ADC #$00`, which is `(level + 1) // 2`
    -- Pool of Radiance's `$215A` rule exactly -- copies the 32-byte spellbook
    mask aside, rotates it a bit at a time, and puts every id the character
    does not know whose level is at or below that on a list at `$7A00`. It
    does not OR a row in. So `levelup.learnable`'s decision to keep treating
    Curse as a menu was right, and Curse is not Silver Blades' shape.
    """
    payload = _gen()
    assert _at(payload, 0x2207, 3) == b"\x4A\x69\x00"        # LSR A / ADC #$00
    assert _at(payload, 0x220D, 8) == (
        b"\xA2\x1F\xBD\x78\x7C\x9D\x18\x27")                 # copy the mask
    assert _at(payload, 0x2220, 8) == (
        b"\xA2\x1F\x7E\x18\x27\xCA\x10\xFA")                 # rotate it
    assert _at(payload, 0x2230, 3) == b"\xDD\x3F\x27"        # CMP $273F,X
    assert _at(payload, 0x223B, 3) == b"\x9D\x00\x7A"        # onto the list


def test_the_trainers_own_spell_level_table_agrees_with_goldbox_spells():
    """`$273F`, 95 bytes: the magic-user spell level of every id, 9 for none.

    93 of the 94 ids from 1 up agree with `goldbox/spells.py`'s Curse groups.
    The one exception is **id 90, the magic-user ANIMATE DEAD**, which the
    trainer marks 9 and so never offers -- the same treatment `spells.py`
    already gives id 36, the cleric ANIMATE DEAD, and id 100 BESTOW CURSE. So
    `not_granted` is short by one for this title.
    """
    payload = _gen()
    table = _at(payload, MU_SPELL_LEVELS, 95)
    curse = spells.CURSE_OF_THE_AZURE_BONDS
    disagree = []
    for spell_id in range(1, 95):
        group = spells.spell_group(spell_id, curse)
        ours = 9 if group is None or group[0] != "magic-user" else group[1]
        if ours != table[spell_id]:
            disagree.append((spell_id, ours, table[spell_id]))
    assert disagree == [(90, 4, 9)], disagree
    assert 90 not in curse.not_granted, "spells.py has caught up with this"


def test_the_menu_stops_at_id_94_and_nothing_is_lost_by_it():
    """`CMP #$5F` ends the walk at 94, where `last_spellbook_spell` is 100.

    A negative result: ids 95 to 99 are `BLESS`, `BLESS`, `BLESS`, `IS ALIVE`
    and `IS DYING` -- duplicates and engine markers that `spell_group` already
    returns nothing for -- and 100 is a cleric spell. So `learnable`'s wider
    walk offers nothing the game would not, and the difference is invisible.
    """
    payload = _gen()
    assert _at(payload, 0x2244, 5) == b"\xAD\x3C\x27\xC9\x5F"
    curse = spells.CURSE_OF_THE_AZURE_BONDS
    assert curse.last_spellbook_spell == 100
    for spell_id in range(95, 101):
        group = spells.spell_group(spell_id, curse)
        assert group is None or group[0] == "cleric", (spell_id, group)


def test_the_magic_user_grant_row_is_character_creation_and_not_the_trainer():
    """`GEN $167F` is a grant loop of Silver Blades' shape, and the trainer
    never calls it. `$23DB` and `$1646` do, and both are on the path from
    `$09B8`, which builds a character.

    It is what the two shipped magic-users hold: DETECT MAGIC, MAGIC MISSILE,
    READ MAGIC, SHIELD and SLEEP at 1, then CHARM PERSON, STINKING CLOUD,
    KNOCK, FIREBALL, and HOLD PERSON with LIGHTNING BOLT from 6 up. Both
    shipped mages are level 5 and hold exactly those nine.
    """
    payload = _gen()
    assert _at(payload, 0x167F, 5) == b"\xAE\xC9\x7C\xF0\x18"
    assert _at(payload, 0x1687, 6) == b"\xC0\x06\x90\x02\xA0\x06"   # cap at 6
    levels_row = _at(payload, 0x169C, 12)
    offsets = _at(payload, 0x16A8, 7)
    masks = _at(payload, 0x16AF, 7)

    def granted(level):
        ids = set()
        for y in range(min(levels_row[level], 6) + 1):
            byte = offsets[y] - 0x078
            ids |= {byte * 8 + bit for bit in range(8) if masks[y] & (1 << bit)}
        return ids

    assert granted(1) == {11, 15, 18, 19, 21}
    assert granted(5) == {10, 11, 15, 18, 19, 21, 31, 34, 47}
    assert granted(6) - granted(5) == {49, 51}
    mages = 0
    for slot in _party():
        record = slot.record
        level = record.get("level_magic_user")
        if not level:
            continue
        mages += 1
        mask = record.slice(0x078, 13)
        held = {i for i in range(1, 104) if mask[i >> 3] & (1 << (i & 7))}
        assert held == granted(level), record.name
    assert mages == 2, mages


def test_curse_never_stores_spell_capacity_in_the_record():
    """`0x0EE` is dead in this title, and `levelup.plan` writes it.

    `ECL65 $880D` rebuilds the whole capacity in fifteen bytes of workspace at
    `$2BB6` every time it is asked -- magic-user, cleric and a third column for
    the ranger's and paladin's borrowed spells -- and nothing copies it back
    into the character. No instruction in `GEN`, `ECL64` or `ECL65` writes
    `$7CEE` to `$7CF3`, and all six shipped characters hold six zero bytes
    there, the level-5 cleric with wisdom 18 included.
    """
    for payload, base in ((_gen(), GEN_BASE), (_ecl65(), ECL65_BASE),
                          (gamedata.curse_file("ECL64")[2:], ECL65_BASE)):
        del base
        for offset in range(0x0EE, 0x0F4):
            assert bytes((offset, 0x7C)) not in payload, hex(offset)
    for slot in _party():
        assert slot.record.get_raw("spells_castable") == bytes(6), slot.record.name


def test_the_spell_slot_rows_sit_where_ecl65s_own_code_reads_them():
    """This is what fixes `ECL65`'s resident base at `$8000`.

    `tests/test_curselevels.py` reaches the slot rows at payload offset
    `0x88D` and says the overlay's base *"has not been fixed here"*. `$8817`
    reads them with `LDA $888D,X` and `$8831` reads the cleric's with
    `LDA $88C4,X`, and `$88C4 - $888D` is 55, which is the eleven magic-user
    rows of five. `0x88D + 0x8000` is `$888D`, so the base is `$8000`.
    """
    payload = _ecl65()
    assert _at(payload, 0x8825, 3, ECL65_BASE) == b"\xBD\x8D\x88"
    assert _at(payload, 0x883F, 3, ECL65_BASE) == b"\xBD\xC4\x88"
    assert SLOTS_CLERIC - SLOTS_MAGIC_USER == 11 * 5
    magic_user = [list(payload[SLOTS_MAGIC_USER + n * 5:
                               SLOTS_MAGIC_USER + n * 5 + 5]) for n in range(11)]
    cleric = [list(payload[SLOTS_CLERIC + n * 5:
                           SLOTS_CLERIC + n * 5 + 5]) for n in range(10)]
    assert magic_user[0] == [1, 0, 0, 0, 0]
    assert magic_user[10] == [4, 4, 4, 3, 3]
    assert cleric[9] == [4, 4, 3, 3, 2]
    for name, rows in (("magic-user", magic_user), ("cleric", cleric)):
        for level, row in enumerate(rows, 1):
            declared = list(CURSE.at_level(name, level).spells)
            assert row[:len(declared)] == declared, (name, level)
            assert set(row[len(declared):]) <= {0}, (name, level)


def test_the_wisdom_bonus_starts_at_thirteen_and_is_one_spell_a_point():
    """`ECL65 $88F6`, and it is not Pool of Radiance's shape.

    `LDA level_cleric / BEQ / LDY wisdom / CPY #$0D / BCC` and then a loop that
    runs once for **every point of wisdom from 13 up**, each point buying one
    spell at the level the table at `$8906` names, and only where the class row
    already gives a slot there (`LDA $2BBB,X / BEQ / INC $2BBB,X`).

    The table reads `0 0 1 1 2 3 4` at wisdom 13 to 19 -- one extra first-level
    spell at 13 and another at 14, second-level at 15 and 16, third at 17,
    fourth at 18. That is AD&D 1st edition exactly, where Pool of Radiance's
    `$10AD` holds 1 at wisdom **12** and is the off-by-one in
    `docs/125-bug-notes.md`. `levels.wisdom_bonus_spells` implements Pool of
    Radiance's and must not answer for this title.
    """
    payload = _ecl65()
    assert _at(payload, 0x88F6, 10, ECL65_BASE) == (
        b"\xAD\xCA\x7C\xF0\x17"          # LDA level_cleric / BEQ
        b"\xAC\x16\x7C\xC0\x0D")         # LDY wisdom / CPY #$0D
    assert _at(payload, 0x8902, 3, ECL65_BASE) == b"\xBE\x06\x89"   # LDX $8906,Y
    assert _at(payload, 0x8905, 8, ECL65_BASE) == (
        b"\xBD\xBB\x2B\xF0\x03\xFE\xBB\x2B")
    table = payload[WISDOM_BONUS:WISDOM_BONUS + 20]
    assert list(table[13:20]) == [0, 0, 1, 1, 2, 3, 4]
    # Pool of Radiance gives a wisdom-12 cleric a bonus spell; Curse does not.
    assert levels.wisdom_bonus_spells(12) == (1, 0, 0)


# --- the sequence, and one rule that is not a level-up ------------------------

def test_the_level_up_sequence_is_eight_routines_at_2041():
    """`GEN $2041`, against Pool of Radiance's fourteen `JSR`s at `$1B8C`.

    Raise every qualifying class by one and roll its die (`$14F8`); the cleric
    grant (`$1649`); the magic-user's menu (`$2200`); a paladin's cleric spells
    (`$22F4`); a ranger's (`$2305`); the experience clamp (`$2086`); the whole
    derived-stat recompute (`$0DD0`), which character creation calls too; and
    the dual-class restore (`$20A3`).
    """
    payload = _gen()
    assert _at(payload, 0x204E, 3) == b"\x20\xF8\x14"
    assert _at(payload, 0x205E, 21) == (
        b"\x20\x49\x16"      # JSR $1649  cleric grant
        b"\x20\x00\x22"      # JSR $2200  magic-user menu
        b"\x20\xF4\x22"      # JSR $22F4  paladin
        b"\x20\x05\x23"      # JSR $2305  ranger
        b"\x20\x86\x20"      # JSR $2086  experience clamp
        b"\x20\xD0\x0D"      # JSR $0DD0  recompute
        b"\x20\xA3\x20")     # JSR $20A3  dual class
    assert _at(payload, 0x0DD0, 33) == (
        b"\x20\x15\x25\x20\xF1\x0D\x20\x08\x0E\x20\x5E\x0E\x20\xAD\x0F"
        b"\x20\x3F\x11\x20\xB6\x3F\x20\xF1\x11\x20\x09\x19\x20\x39\x19"
        b"\x4C\x2C\x11")
    # $14F8 raises one level per class per visit: INC, then straight to the die.
    assert _at(payload, 0x153B, 12) == (
        b"\xFE\xC9\x7C"      # INC $7CC9,X
        b"\xEE\xAD\x2C\xFE\xE3\x2C"
        b"\x20\xE1\x15")     # JSR $15E1  the hit die


def test_the_racial_class_limit_is_adjusted_by_the_prime_requisite():
    """`$1553`, and `LevelTables.racial_limit` returns only its best case.

    `$1599` names the ability each class's limit turns on -- `$80` for a cleric,
    meaning none -- and `$15A9` holds the limit for a score of 18. `CMP #$12 /
    BCS` leaves the adjustment at 0, `CMP #$11 / BCS` at 1, and anything below
    17 at 2, and the limit has that subtracted. So a dwarf fighter reaches 9
    with strength 18, 8 with 17 and 7 with less, and `racial_limit` says 9 for
    all three.
    """
    payload = _gen()
    assert _at(payload, 0x1553, 6) == b"\xBD\xC9\x7C\xDD\xA1\x15"   # vs ceiling
    assert _at(payload, 0x155B, 5) == b"\xAD\x72\x7C\xC9\x07"       # race >= 7
    assert _at(payload, 0x1566, 3) == b"\xBC\x99\x15"               # LDY $1599,X
    assert _at(payload, 0x156B, 3) == b"\xB9\x65\x7C"               # the score
    assert _at(payload, 0x1586, 6) == b"\xBD\xA9\x15\x38\xE5\xB0"   # limit - adj
    governs = _at(payload, 0x1599, 8)
    assert [governs[s] for s in (0, 2, 3, 6, 7)] == [1, 3, 0, 0, 0]
    assert governs[1] & 0x80, "a cleric's limit turns on no ability"
    rows = [list(_at(payload, 0x15A9 + r * 8, 8)) for r in range(7)]
    assert rows[0][3] == 9 and rows[6] == [99, 99, 99, 99, 0, 0, 99, 99]
    for race, row in enumerate(rows, 1):
        for slot, name in enumerate(CLASS_SLOTS):
            if name is None:
                continue
            assert CURSE.racial_limit(race, name) == row[slot], (race, name)


def test_the_class_ceilings_are_the_games_own_eight_bytes():
    """`$15A1`, the other half of the same check, and it is `ceilings`."""
    payload = _gen()
    ceilings = _at(payload, 0x15A1, 8)
    for slot, name in enumerate(CLASS_SLOTS):
        want = 0 if name is None else CURSE.ceiling(name)
        assert ceilings[slot] == want, (slot, name)
