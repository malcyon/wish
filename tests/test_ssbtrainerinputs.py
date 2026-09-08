"""The three trainer inputs `goldbox/levels.py` leaves empty for Silver Blades.

`#89 (Silver Blades' trainer grants spells from a table, and goldbox/levelup.py
offers them from a menu)`. Every number is read off the player's own disks by
`tools/ssbtrainerinputs.py` at run time -- nothing here is transcribed, which is
why the assertions compare Silver Blades' bytes against *Curse's* copies and
against records the game itself wrote rather than against a literal table.

Two records vote:

* the six SSI ships in `SAVEDBASH`, whose provenance is a disk image and
  therefore nobody's;
* `WISH-SPEC-ssb-malachite-trained`, which `#344` made by watching the game's
  own trainer raise MALACHITE to thief 9 and then saving from the party menu.

Skips cleanly with no disks, and the specimen half skips on its own.
"""

from __future__ import annotations

import pytest

from goldbox import games, levels
from tools import ssbtrainerinputs as T

CURSE = levels.CURSE_OF_THE_AZURE_BONDS
POOL = levels.POOL_OF_RADIANCE


def _overlays():
    """`GEN` and `ECL65` off all three titles' disks, or skip."""
    try:
        return {
            "gen": T.overlay("ssb", "GEN"),
            "curse_gen": T.overlay("curse", "GEN"),
            "pool_gen": T.overlay("pool", "GEN"),
            "ecl65": T.overlay("ssb", "ECL65"),
            "curse_ecl65": T.overlay("curse", "ECL65"),
        }
    except SystemExit as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def files():
    return _overlays()


@pytest.fixture(scope="module")
def con(files):
    return T.constitution(files["gen"], files["curse_gen"])


@pytest.fixture(scope="module")
def thief(files):
    return T.thief(files["gen"], files["curse_gen"], files["pool_gen"])


@pytest.fixture(scope="module")
def wis(files):
    return T.wisdom(files["ecl65"], files["curse_ecl65"])


def _thief_of(party):
    return [r for r in party if r.slice(0x0CB, 1)[0]]


# --- the readings are of the routines this tool names ------------------------


def test_every_address_this_tool_reads_carries_the_opcodes_it_claims(files):
    """A different rip must fail loudly rather than print other bytes.

    Six signatures: the constitution lookup `$0E6C`, the ranger's extra bonus
    `$0E9A`, the thief's level clamp `$120E`, its dexterity index `$122D`, its
    racial index `$124D`, and `ECL65`'s wisdom loop at payload `0x9E0`.
    """
    assert T.signatures(files["gen"], files["ecl65"]) == []


# --- hp_bonus_by_score -------------------------------------------------------


def test_the_constitution_hit_point_row_is_curses_twenty_six_bytes(con):
    """`GEN $0E80` against Curse's `GEN $11D7`. Sameness measured, not assumed.

    The two files share no address -- `$0E80` holds something else in Curse --
    so this is a second transcription of one AD&D row rather than a table SSI
    left in place.
    """
    assert con["raw"] == con["curse_raw"]
    assert len(con["raw"]) == 26
    assert con["table"] == CURSE.hp_bonus_by_score


def test_the_cap_and_the_uncapped_slot_are_curses_rule_too(con):
    """`$0E6F CPY #$03 / BCS / $0E73 CPX #$11 / BCC / LDX #$10`.

    Class slots 0-2 -- magic-user, cleric, thief -- read the row at a score
    clamped to 16; slots 3 and up read it whole. Curse's `$126D` is the same
    two compares.
    """
    assert (con["cap"], con["uncapped_from"]) == (
        CURSE.hp_bonus_score_cap, CURSE.hp_bonus_uncapped_from)


def test_every_shipped_hit_point_total_is_that_rows_answer(con):
    """Six of six, and the seventh is the trained specimen below.

    `$0DBA` sums `min(level, roll_to) * bonus(slot)` over the eight class
    slots, adds one more bonus for a ranger (`$0E9A`) and divides by how many
    classes the character holds. The divide rounds up at random, so one more
    hit point is allowed and never needed here.
    """
    party = T.shipped_party()
    if not party:
        pytest.skip("no Silver Blades side here carries a whole SAVEDBASH")
    assert len(party) == 6
    for rec in party:
        want = T.predicted_hp_max(con, rec)
        assert want is not None
        assert rec.get("hp_max") in (want, want + 1), rec.name


def test_the_rangers_extra_constitution_bonus_is_what_paines_total_needs(con):
    """PAINE is ranger 8 with constitution 16, `hp_rolled` 56, `hp_max` 74.

    Eight levels at +2 is 16, and 56 + 16 is 72. `$0E9A` adds the bonus a
    second time for a ranger, which is the two points between them.
    """
    party = T.shipped_party()
    if not party:
        pytest.skip("no Silver Blades side here carries a whole SAVEDBASH")
    rangers = [r for r in party if r.slice(0x0D0, 1)[0]]
    assert rangers, "the shipped party should include a ranger"
    for rec in rangers:
        slots = list(rec.slice(0x0C9, 8))
        once = sum(min(level, con["roll_to"][slot]) *
                   T.hp_bonus(con, slot, rec.get("constitution"))
                   for slot, level in enumerate(slots) if level)
        assert rec.get("hp_max") != rec.get("hp_rolled") + once
        assert rec.get("hp_max") == T.predicted_hp_max(con, rec)


# --- thief_skills, thief_skill_race, and the dexterity row --------------------


def test_the_thief_level_rows_are_seventeen_and_the_first_nine_are_curses(thief):
    """`GEN $126D`, and `$1213 CPX #$11 / LDX #$11` is why there are 17.

    Rows 1-9 are the same 72 bytes as Curse's `$1004` and Pool of Radiance's
    `$102E`; rows 10-17 are new in this title, which is the first of the three
    to reach a thief past level 9.
    """
    assert len(thief["levels"]) == 17
    assert thief["levels"][:9] == tuple(
        tuple(thief["curse_levels"][n * 8:n * 8 + 8]) for n in range(9))
    assert thief["curse_levels"] == thief["pool_levels"]
    for column in range(8):
        seen = [row[column] for row in thief["levels"]]
        assert seen == sorted(seen), column


def test_the_dexterity_rows_are_curses_hundred_and_thirty_six_bytes(thief):
    """`GEN $131D` against Curse's `$10A4`, and both start at a dexterity of 9.

    Pool of Radiance's thief routine reads no ability score at all, so this is
    a rule Curse introduced and Silver Blades kept.
    """
    assert len(thief["dexterity"]) == 17
    assert thief["dexterity"] == tuple(
        tuple(b - 256 if b > 127 else b
              for b in thief["curse_dexterity"][n * 8:n * 8 + 8])
        for n in range(17))
    assert T.THIEF_DEX_FROM == CURSE.thief_skill_dexterity_from
    assert not POOL.thief_skill_dexterity


def test_the_racial_rows_are_curses_five_in_silver_blades_own_race_order(thief):
    """`GEN $12F5` holds the same five AD&D rows Curse's `$1064` does.

    Curse lays them out dwarf, elf, gnome, half-elf, halfling, half-orc, which
    is `games.RACES_CURSE`; Silver Blades lays out elf, half-elf, dwarf, gnome,
    halfling, which is `games.RACES_SILVER_BLADES` codes 1-5. Same numbers,
    re-ordered -- so the table is a permutation and not a new measurement.
    """
    curse_by_name = {name: thief["curse_race"][code - 1]
                     for code, name in games.RACES_CURSE if code <= 6}
    for code, name in games.RACES_SILVER_BLADES:
        if code > 5:
            continue
        assert thief["race_table"][code - 1] == curse_by_name[name], name


def test_the_racial_index_runs_one_row_past_the_row_it_wants(thief, files):
    """`GEN $124D` has no decrement, and the two controls are in the same family.

    `LDA race / BEQ / CMP #$06 / BCS / ASL / ASL / ASL` indexes `race * 8`
    into a table whose row 0 is the elf's -- so race 1, the elf, reads the
    half-elf's row. Pool of Radiance's `$2005` is `LDY race / DEY` and Curse's
    `$0FE6` is `LDX race / DEX`; Silver Blades' own `$17B1`, for the racial
    class limits in the same overlay, is `LDX race / DEX` as well.
    """
    gen, curse, pool = files["gen"], files["curse_gen"], files["pool_gen"]
    assert T._at(gen, T.GEN_BASE, 0x124D, 6) == bytes.fromhex("AD727CF01AC9")
    assert T._at(gen, T.GEN_BASE, 0x1256, 4) == bytes.fromhex("0A0A0AAA")
    assert T._at(gen, T.GEN_BASE, 0x17B1, 4) == bytes.fromhex("AE727CCA")
    assert T._at(curse, T.GEN_BASE, 0x0FE6, 4) == bytes.fromhex("AE727CCA")
    assert T._at(pool, T.GEN_BASE, 0x2005, 4) == bytes.fromhex("AC726B88")
    # The halfling, race 5, runs off the end into the dexterity table's row 0.
    assert thief["effective"][5] == thief["dexterity"][0]
    assert thief["race_table"][5] == thief["dexterity"][0]


def test_the_shipped_dwarf_thief_stores_the_gnomes_row_not_the_dwarfs(thief):
    """MALACHITE, race 3, thief 8, dexterity 17: eight of eight columns.

    The differential is what makes this a measurement rather than a reading:
    adding the row at `race * 8` reproduces all eight stored numbers, and
    adding the row at `(race - 1) * 8` -- the dwarf's own -- reproduces none of
    the five columns the two rows disagree on.
    """
    party = T.shipped_party()
    if not party:
        pytest.skip("no Silver Blades side here carries a whole SAVEDBASH")
    thieves = _thief_of(party)
    assert thieves, "the shipped party should include a thief"
    for rec in thieves:
        stored = tuple(rec.get(f"thief_{n.replace(' ', '_')}") for n in T.SKILLS)
        want = T.skill_row(thief, rec.slice(0x0CB, 1)[0], rec.get("race"),
                           rec.get("dexterity"))
        assert stored == want, rec.name
        intended = dict(thief["effective"])
        intended[rec.get("race")] = thief["race_table"][rec.get("race") - 1]
        other = T.skill_row({**thief, "effective": intended},
                            rec.slice(0x0CB, 1)[0], rec.get("race"),
                            rec.get("dexterity"))
        assert stored != other, rec.name


def test_the_trainer_wrote_the_same_rows_when_it_raised_malachite(thief, con):
    """`WISH-SPEC-ssb-malachite-trained`: thief 9, dwarf, written by the game.

    This is the corroboration the shipped party cannot give, because a record
    on a disk image has no chain of custody and this one was watched being
    written (`#344`, VICE pool slot 0, 2026-09-06). Eight of eight skill
    columns and the recomputed `hp_max` both come out of the tables above.
    """
    party = T.specimen_party()
    if not party:
        pytest.skip("WISH-SPEC-ssb-malachite-trained is not on this machine")
    thieves = _thief_of(party)
    assert thieves, "the specimen should carry the trained thief"
    for rec in thieves:
        assert rec.slice(0x0CB, 1)[0] == 9, "MALACHITE was trained to thief 9"
        stored = tuple(rec.get(f"thief_{n.replace(' ', '_')}") for n in T.SKILLS)
        assert stored == T.skill_row(thief, 9, rec.get("race"),
                                     rec.get("dexterity")), rec.name
    for rec in party:
        want = T.predicted_hp_max(con, rec)
        assert rec.get("hp_max") in (want, want + 1), rec.name


# --- wisdom_bonus_level ------------------------------------------------------


def test_the_wisdom_bonus_row_is_curses_seven_bytes(wis):
    """`ECL65 $89F0` at wisdom 13-19 against Curse's `$8906`.

    `$89E0` is Curse's `$88F6` instruction for instruction against a different
    workspace -- `$2A1E` here, `$2BBB` there -- so a cleric buys one spell a
    point of wisdom from 13 up, at the level this row names.
    """
    assert wis["table"] == wis["curse"]
    assert wis["table"] == CURSE.wisdom_bonus_level
    assert T.WISDOM_BONUS_FROM == CURSE.wisdom_bonus_from


def test_counting_the_loop_out_gives_curses_answers(wis):
    """`levels.wisdom_bonus_spells` for Curse already implements this loop, so
    Silver Blades' own table has to give it the same answers at every score.

    **No record can ever corroborate it.** The bonus lands in `$2A1E` and
    nothing copies it back: `#89`'s census of `0x0EE`-`0x0F3` found 0 code
    references in 347 Silver Blades files, so there is no byte on any disk
    that could agree or disagree.
    """
    for score in range(3, 20):
        assert T.bonus_spells(wis["table"], score) == \
            levels.wisdom_bonus_spells(score, CURSE), score
    assert T.bonus_spells(wis["table"], 18) == (2, 2, 1, 1, 0)
    assert T.bonus_spells(wis["table"], 12) == (0, 0, 0, 0, 0)


def test_pool_of_radiances_wisdom_rule_would_answer_differently(wis):
    """The control: Pool of Radiance gives a wisdom-12 cleric a bonus spell.

    `GEN $10AD` there is the off-by-one in `docs/125-bug-notes.md`, and Silver
    Blades tabulates the *Players Handbook* row like Curse instead. So this is
    a title-shaped rule and `wisdom_bonus_spells` must not answer Pool of
    Radiance's for it.
    """
    assert levels.wisdom_bonus_spells(12) == (1, 0, 0)
    assert T.bonus_spells(wis["table"], 12) != (1, 0, 0)
