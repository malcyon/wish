"""What `tools/testparty.py` generates, checked against what the engine wrote.

The generator's whole risk is the circle `docs/119-test-party.md` §2 names: a
test that reads back the bytes the generator wrote through the same tables the
generator wrote them from passes whether or not the game agrees.  So the
checks here are in two groups, and only the second is evidence about the game.

* **Shape and ceilings.**  The party is six, every record round-trips, and each
  character reaches the thing `docs/119-test-party.md` says it exists to
  reach.  These catch a generator that stopped working; they say nothing about
  the format.
* **Against records the engine wrote.**  `WISH-SPEC-por-party-l1-rolled` is six
  DOS characters driven through Pool of Radiance's own creation screens for
  `#249 (Build a DOS party from creation and level it ourselves, so DOS
  measurements rest on records we watched being written)`, and
  `test_a_generated_level_one_matches_the_six_the_engine_rolled` rebuilds each
  of them from its own inputs and compares.  It skips where the specimen tree
  is absent, which is CI.
"""
from __future__ import annotations

import hashlib

import gamedata
import pytest

from goldbox import derive, games, levels, levelup, savegame
from goldbox.games import CLASS_BITS_CLASSIC
from goldbox.record import CharacterRecord
from tools import testparty

GAME = games.by_key("pool-of-radiance")

#: One party, generated once. Every check below reads it rather than paying
#: for six characters' worth of level-ups per test.
@pytest.fixture(scope="module")
def built():
    return testparty.party(rolls="max")


def _by_name(built):
    return {str(one.record.name): one for one in built}


# --- shape ------------------------------------------------------------------

def test_the_party_is_six_and_every_record_is_a_whole_one(built):
    assert len(built) == 6
    for one in built:
        raw = one.record.to_bytes()
        assert len(raw) == 580
        assert CharacterRecord.from_bytes(raw).to_bytes() == raw


def test_the_combat_icon_is_the_only_thing_the_generator_cannot_make():
    """580 of 580 bytes accounted for, and one reported gap, no more.

    **The byte count is the weaker half and it is easy to over-read.**
    `goldbox.c64_codec.write` accounts for a byte it *decided* to leave zero
    as much as one it copied, so withholding a whole input -- `movement`,
    say -- still leaves 0 unaccounted and adds nothing to the dropped list;
    it only makes the value wrong, which is what
    `test_a_generated_level_one_matches_the_six_the_engine_rolled` is for.

    What this pins is the **gap list**: exactly one entry, the combat icon,
    for every character. A second entry means the generator stopped supplying
    something it used to, and the module docstring's "what it does not do" has
    gone out of date.
    """
    for spec in testparty.PARTY:
        _, report = testparty.level_one(spec, GAME, testparty.rolls_for("max"))
        assert report.unaccounted == [], f"{spec.name}: {report.summary()}"
        assert len(report.dropped) == 1, f"{spec.name}: {report.dropped}"
        assert "combat icon" in report.dropped[0], report.dropped[0]


def test_a_generated_party_is_the_same_party_every_time():
    first = [one.record.to_bytes() for one in testparty.party(rolls="max")]
    again = [one.record.to_bytes() for one in testparty.party(rolls="max")]
    assert first == again


def test_the_smallest_rolls_give_a_smaller_party_than_the_largest():
    low = {str(o.record.name): o.record.get("hp_max")
           for o in testparty.party(rolls="min")}
    high = {str(o.record.name): o.record.get("hp_max")
            for o in testparty.party(rolls="max")}
    assert all(low[n] < high[n] for n in high), (low, high)


# --- the ceilings docs/119-test-party.md asks for ---------------------------

def test_bulwark_reaches_the_fighter_ceiling_and_arrives_wounded(built):
    """THAC0 13, 112 hit points and 3/2 attacks -- and hurt, which the
    trainer cannot leave a character."""
    rec = _by_name(built)["BULWARK"].record
    assert rec.get("level_fighter") == 8
    assert rec.thac0_base_value == 13
    assert rec.get("hp_max") == 112
    assert rec.get_raw("attack_forms")[0] == 3
    assert rec.get("hp_current") < rec.get("hp_max")


def test_pilfer_is_the_highest_level_the_games_tables_hold(built):
    """Thief 9, with every skill off its level-1 value and read-languages
    crossing zero from below -- a halfling's is -5 at level 1."""
    tables = levels.for_game(GAME)
    rec = _by_name(built)["PILFER"].record
    assert rec.get("level_thief") == 9 == tables.ceiling("thief")
    at_one = tables.thief_skill_row(1, rec.get("race"), rec.get("dexterity"))
    now = [rec.get(n) for n in levelup.THIEF_FIELDS]
    assert at_one[-1] < 0 < now[-1], (at_one, now)
    assert all(a != b for a, b in zip(at_one, now))


def test_astra_is_the_only_record_with_both_spell_nibbles_at_once(built):
    """Cleric capacity in the high nibble and magic-user capacity in the low
    one, in the same byte -- which no single-class character can show."""
    both = []
    for one in built:
        raw = one.record.get_raw("spells_castable")
        if any(b >> 4 for b in raw) and any(b & 0x0F for b in raw):
            both.append(str(one.record.name))
    assert both == ["ASTRA"]


def test_grimstone_holds_two_different_non_zero_class_levels(built):
    """The only thing that separates `level` at 0x0A0 from a single class's
    level is a record where the per-class array holds two different ones."""
    rec = _by_name(built)["GRIMSTONE"].record
    array = [rec.get(f) for f in levelup.CLASS_LEVEL_FIELD.values()
             if rec.is_stored(f)]
    non_zero = sorted(v for v in array if v)
    assert non_zero == [7, 8]
    assert rec.get("level") == 8


def test_wardens_cleric_slots_are_above_the_class_table(built):
    """A WIS 18 bonus, visible because the stored capacity beats the row."""
    rec = _by_name(built)["WARDEN"].record
    row = levels.at_level("cleric", 6, GAME).spells
    stored = [b >> 4 for b in rec.get_raw("spells_castable")]
    assert rec.get("wisdom") == 18
    assert stored[:len(row)] > list(row)


def test_the_half_elf_carries_the_only_trait_the_c64_seeds_her(built):
    """`GEN $0BF3` seeds 107 for an elf and 124 for a half-elf and nothing for
    anybody else, so ASTRA has one trait and the dwarf has none."""
    names = _by_name(built)
    assert [b for b in names["ASTRA"].record.get_raw("item_effects") if b] \
        == [124]
    assert not any(names["GRIMSTONE"].record.get_raw("item_effects"))


def test_a_half_elf_cleric_six_is_refused_by_the_racial_limit():
    """`docs/119-test-party.md` §1 asks for ASTRA at cleric 6 and the game's
    own table stops a half-elf at 5, so the generator must refuse rather than
    write a character the trainer would never have made."""
    spec = _by_name(testparty.party(rolls="max"))["ASTRA"].spec
    over = testparty.Spec(**{**spec.__dict__,
                            "levels": {**spec.levels, "cleric": 6}})
    with pytest.raises(levelup.CannotLevel):
        testparty.build(over, GAME)


def test_the_generated_party_agrees_with_what_the_rules_derive(built):
    """`goldbox.derive.check` against each character's own roster block, which
    is `docs/119-test-party.md` §6's second gate: it catches a stale cache,
    which is the failure mode of a hand-built save."""
    roster = bytearray(GAME.roster_size)
    for index, one in enumerate(built):
        at = index * savegame.ROSTER_STRIDE
        roster[at:at + savegame.ROSTER_STRIDE] = one.record.slice(0x100, 32)
    save1 = savegame.SaveGame1(bytes(roster), GAME)
    for index, one in enumerate(built):
        assert derive.check(one.record, save1.roster(index), []) == [], \
            str(one.record.name)


# --- against the records the engine wrote -----------------------------------

#: The neutral `size_small` is 0 for a small race and 1 for a large one; DOS
#: stores 1 and 2. One is the other plus one, in all six.
DOS_SIZE_BIAS = 1


def _spec_from(record, name: str) -> testparty.Spec:
    """The inputs creation was given, read back off what it wrote.

    The hit die comes in as `hit_points_rolled` rather than through the rng,
    because it is the one number nothing derives -- and because creation's
    own multi-class rule is not the trainer's, which is what
    `tools/testparty._seed_hit_points` records.
    """
    get = record.get
    bits = get("class_bits")
    abilities = {a: get(a) for a in
                 ("strength", "intelligence", "wisdom", "dexterity",
                  "constitution", "charisma")}
    abilities["exceptional_strength"] = get("exceptional_strength") or 0
    return testparty.Spec(
        name=name, race=get("race"), sex=get("sex"),
        levels={n: 1 for b, n in CLASS_BITS_CLASSIC if bits & b},
        abilities=abilities, alignment=get("alignment"), age=get("age"),
        experience=0, portrait=(0, 0), gold=get("gold"),
        hit_points_rolled=get("hp_rolled"))


@pytest.mark.skipif(not gamedata.have_specimen("por-party-l1-rolled"),
                    reason="needs WISH-SPEC-por-party-l1-rolled")
def test_a_generated_level_one_matches_the_six_the_engine_rolled():
    """Rebuild each engine-rolled character from its own inputs and compare.

    The hit die is handed in rather than rolled -- it is the one field nothing
    derives -- and everything the engine computed from it is compared.

    **Three fields are left out and each is a known difference between the two
    ports rather than a generator fault**, so leaving them in would make this
    test fail for a reason it is not about:

    * `thac0_base` for a magic-user or a thief. DOS gives THAC0 20 in the
      lowest band where the C64 gives 21 -- `#318 (DOS gives a low-level
      magic-user or thief THAC0 20 where the C64 gives 21, and our table holds
      only the C64's)`, `docs/210-the-later-titles-dos-thac0.md` -- and the
      C64's own level-1 records hold the 21. The other four classes are
      compared.
    * the five saving throws of a dwarf, gnome or halfling. The C64 subtracts
      the constitution bonus into the stored bytes and DOS applies it when the
      die is rolled (`goldbox/c64_codec.py`, `#311`), so the plain class row is
      what DOS holds and the comparison uses that.
    * the eight thief skills. DOS's own level-1 row is five, ten and five
      higher in three columns than the C64's, over two engine-rolled thieves,
      and no C64 halfling or dwarf thief exists here to say which racial row
      each port keeps. `#10 (Finish the high-level test party)` carries the
      numbers.
    """
    from goldbox import dos

    directory = gamedata.specimen("por-party-l1-rolled")
    tables = levels.for_game(GAME)
    files = sorted(directory.glob("*.CHA"))
    assert len(files) == 6, files
    compared = 0
    for path in files:
        engine = dos.DosCharacter(path.read_bytes())
        spec = _spec_from(engine, str(engine.name))
        rolled = engine.get("hp_rolled")
        record, _ = testparty.level_one(spec, GAME,
                                        testparty.rolls_for("max"))
        where = f"{path.name} ({spec.race}, {sorted(spec.levels)})"

        assert record.get("experience") == engine.get("experience") == 0, where
        assert record.get("level") == engine.get("level") == 1, where
        assert record.get("hp_rolled") == rolled, where
        assert record.get("hp_max") == engine.get("hp_max"), where
        assert record.get("movement") == engine.get("movement") == 12, where
        assert record.get("attack_level") == engine.get("attack_level") == 1, \
            where
        assert record.get_raw("attack_forms") == engine.get("attack_forms"), \
            where
        assert record.get("armour_class_base") \
            == engine.get("armour_class_base") == 50, where
        assert record.get("armour_class") == engine.get("armour_class"), where
        assert record.get("size_small") + DOS_SIZE_BIAS == engine.get("size"), \
            where

        if not {"magic-user", "thief"} & set(spec.levels):
            assert record.get("thac0_base") == engine.get("thac0_base"), where

        plain = tables.saving_throws(spec.levels, race=7, constitution=0)
        for column, field in enumerate(testparty.SAVE_FIELDS):
            assert plain[column] == engine.get(field), f"{where} {field}"
        compared += 1
    assert compared == 6


# --- the disk writer --------------------------------------------------------

@gamedata.needs_disks
def test_writing_a_disk_never_touches_the_one_it_copies(tmp_path, built):
    """The player's disk is read and never written, which is the promise the
    whole project makes about that directory."""
    base = gamedata.save_disk("PORSAVE")
    before = hashlib.sha256(base.read_bytes()).hexdigest()
    out = testparty.write_disk(built, base, tmp_path / "TESTPARTY.D64")
    assert hashlib.sha256(base.read_bytes()).hexdigest() == before
    assert out.exists()


@gamedata.needs_disks
def test_the_written_disk_reads_back_as_the_party_that_was_generated(
        tmp_path, built):
    """Six slots, six roster blocks, and each block the record's own tail."""
    from goldbox.d64 import D64

    base = gamedata.save_disk("PORSAVE")
    out = testparty.write_disk(built, base, tmp_path / "TESTPARTY.D64")
    _, save0, save1 = savegame.load_save(D64.open(str(out)))
    slots = [s for s in save0.slots if s.occupied]
    assert [str(s.record.name) for s in slots] == \
        [str(one.record.name) for one in built]
    for index, one in enumerate(built):
        assert save1.roster(index).raw == one.record.slice(0x100, 32)
        assert derive.check(one.record, save1.roster(index), []) == []
    for index in range(len(built), savegame.ROSTER_COUNT):
        assert not save1.roster(index).occupied
