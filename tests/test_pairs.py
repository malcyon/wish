"""Losslessness for the values the save holds twice.

Every pair we understand turned out to be base-versus-current rather than a
duplicate, so `wish` must never reconcile one half against the other on its own.
The one real bug found so far -- the class fields being forced into agreement --
survived because **no shipped save disagrees**. So these tests do not look for a
pathological state: they build one, in the record and roster bytes directly,
then export, import unchanged and demand a byte-identical disk.

A save slot is 256 bytes, so the record fields at `0x10E`, `0x10F` and `0x119`
are not part of a save at all -- see
`test_the_records_own_current_values_are_not_in_a_save`. The pairs below are the
ones a save can actually hold.
"""

import pathlib
import shutil

import pytest

from por.d64 import D64
from por.record import FieldNotStored
from por.savegame import ROSTER_STRIDE, SaveGame0, SaveGame1
from por.yaml_io import export_save, import_into

DISKS = "/mnt/media/roms/c64/Pool of Radiance Disks"
SAVE = f"{DISKS}/PORSAVE4.D64"
GAME = "work/POOL1.D64.orig"

live = pytest.mark.skipif(not pathlib.Path(SAVE).exists(),
                          reason="needs a real save disk")

MALCYON, KATHERINE, ROLAND = 0, 1, 2


def _construct(tmp_path, name, slot, record=None, roster=None):
    """A save disk carrying a state no real save has been seen in.

    The constructed values are read back off the finished disk, because a field
    a save cannot hold would make every assertion that follows vacuous.
    """
    src = tmp_path / f"{name}.d64"
    shutil.copy(SAVE, src)
    img = D64.open(str(src))
    if record:
        sg = SaveGame0.from_prg(img.read_file(b"SAVEDGAME0"))
        rec = sg.slot(slot).record
        for field, value in record.items():
            rec.set(field, value)
        sg.write_record(slot, rec)
        img.write_file_inplace(b"SAVEDGAME0", sg.to_prg())
    if roster:
        sg1 = SaveGame1.from_prg(img.read_file(b"SAVEDGAME1"))
        payload = bytearray(sg1.to_bytes())
        for offset, value in roster.items():
            payload[slot * ROSTER_STRIDE + offset] = value
        img.write_file_inplace(b"SAVEDGAME1", SaveGame1(bytes(payload)).to_prg())
    img.save(str(src))

    check = D64.open(str(src))
    if record:
        rec = SaveGame0.from_prg(check.read_file(b"SAVEDGAME0")).slot(slot).record
        for field, value in record.items():
            assert rec.get(field) == value, f"{field} did not reach the disk"
    if roster:
        raw = SaveGame1.from_prg(check.read_file(b"SAVEDGAME1")).roster(slot).raw
        for offset, value in roster.items():
            assert raw[offset] == value, f"roster +0x{offset:02X} did not reach the disk"
    return src


def _round_trip(src, tmp_path):
    """Export and import with nothing edited. Returns (changes, new disk)."""
    data = export_save(str(src), GAME)
    out = tmp_path / f"{src.stem}-rt.d64"
    changes = import_into(str(src), data, str(out), game_disk=GAME)
    return changes, out


def _unchanged(src, tmp_path):
    changes, out = _round_trip(src, tmp_path)
    assert changes == []
    assert out.read_bytes() == src.read_bytes()


def _record(disk, slot):
    sg = SaveGame0.from_prg(D64.open(str(disk)).read_file(b"SAVEDGAME0"))
    return sg.slot(slot).record


def _roster(disk, slot):
    return SaveGame1.from_prg(D64.open(str(disk)).read_file(b"SAVEDGAME1")).roster(slot)


# --- the record's own current values are not in a save ----------------------

@live
def test_the_records_own_current_values_are_not_in_a_save(tmp_path):
    """0x10E, 0x10F and 0x119 lie beyond the 256 bytes a slot stores, so the
    THAC0, armour class and hit point triples reduce to a pair in a save. Written
    here to prove the other tests are not asserting against bytes that were
    silently dropped."""
    src = tmp_path / "beyond.d64"
    shutil.copy(SAVE, src)
    img = D64.open(str(src))
    sg = SaveGame0.from_prg(img.read_file(b"SAVEDGAME0"))
    rec = sg.slot(MALCYON).record
    rec.set("thac0", 60 - 18)
    rec.set("armour_class", 60 - 4)
    rec.set("hp_current", 3)
    sg.write_record(MALCYON, rec)
    img.write_file_inplace(b"SAVEDGAME0", sg.to_prg())
    img.save(str(src))
    after = _record(src, MALCYON)
    # The write went nowhere, and reading it back is now refused outright rather
    # than answering 0 -- which decoded as `60 - 0`, i.e. AC 60, a plausible
    # number that is entirely wrong. Those three offsets are the roster block,
    # which the record and SAVEDGAME1 share.
    for name in ("thac0", "armour_class", "hp_current"):
        assert not after.is_stored(name)
        with pytest.raises(FieldNotStored):
            after.get(name)


# --- THAC0: record 0x071 base, roster +0x0E current -------------------------

@live
def test_a_base_and_current_thac0_that_disagree_survive_a_round_trip(tmp_path):
    """MALCYON already shows 21 base against 20 current with darts readied;
    three points apart is the same thing, further apart than any save holds."""
    src = _construct(tmp_path, "thac0", MALCYON,
                     record={"thac0_base": 60 - 21}, roster={0x0E: 60 - 18})
    _unchanged(src, tmp_path)


# --- armour class: record 0x0E1 base, roster +0x0F total, +0x10 armour-only --

@live
def test_a_base_and_current_armour_class_that_disagree_survive_a_round_trip(tmp_path):
    """Base is 10 for every player character; a monster's real value there,
    against a total the armour-only byte cannot account for."""
    src = _construct(tmp_path, "ac", MALCYON,
                     record={"armour_class_base": 60 - 6},
                     roster={0x0F: 60 - 2, 0x10: 48 + 5})
    _unchanged(src, tmp_path)


@live
def test_the_armour_only_armour_class_is_never_written(tmp_path):
    """+0x10 excludes the shield and has no setter -- editing the total must
    leave it alone rather than guess at the difference."""
    data = export_save(SAVE, GAME)
    next(e for e in data["party"]
         if e["slot"] == MALCYON)["combat"]["armour_class"] = 3
    out = tmp_path / "acedit.d64"
    import_into(SAVE, data, str(out), game_disk=GAME)
    before, after = _roster(pathlib.Path(SAVE), MALCYON), _roster(out, MALCYON)
    assert after.armour_class == 3
    assert after.raw[0x10] == before.raw[0x10]
    assert _record(out, MALCYON).get("armour_class_base") == \
        _record(pathlib.Path(SAVE), MALCYON).get("armour_class_base")


# --- movement: record 0x09F base, roster +0x1B encumbered -------------------

@live
def test_a_base_and_encumbered_movement_that_disagree_survive_a_round_trip(tmp_path):
    src = _construct(tmp_path, "movement", ROLAND,
                     record={"movement": 15}, roster={0x1B: 3})
    _unchanged(src, tmp_path)


@live
def test_editing_the_base_movement_leaves_the_encumbered_figure_alone(tmp_path):
    """0x09F is the unencumbered base and the roster's is what armour left of
    it. One is not derivable from the other, so only the edited byte moves."""
    data = export_save(SAVE, GAME)
    next(e for e in data["party"] if e["slot"] == ROLAND)["movement"] = 6
    out = tmp_path / "mv.d64"
    import_into(SAVE, data, str(out), game_disk=GAME)
    assert _record(out, ROLAND).get("movement") == 6
    assert _roster(out, ROLAND).movement == _roster(pathlib.Path(SAVE), ROLAND).movement


# --- hit points: record 0x076 max, 0x0ED rolled, roster +0x19 current -------

@live
def test_hit_points_disagreeing_three_ways_survive_a_round_trip(tmp_path):
    """Max above rolled is real -- BRUTUS is 11 and 9 -- and current below both
    is what damage does. All three apart at once is not."""
    src = _construct(tmp_path, "hp", KATHERINE,
                     record={"hp_max": 9, "hp_rolled": 7}, roster={0x19: 2})
    _unchanged(src, tmp_path)


@live
def test_editing_hp_max_leaves_the_rolled_and_current_totals_alone(tmp_path):
    """A character can be at less than full health, and 0x0ED is separately
    editable, so raising the maximum must not drag either with it."""
    data = export_save(SAVE, GAME)
    next(e for e in data["party"] if e["slot"] == KATHERINE)["hp_max"] = 9
    out = tmp_path / "hpmax.d64"
    import_into(SAVE, data, str(out), game_disk=GAME)
    assert _record(out, KATHERINE).get("hp_max") == 9
    assert _record(out, KATHERINE).get("hp_rolled") == \
        _record(pathlib.Path(SAVE), KATHERINE).get("hp_rolled")
    assert _roster(out, KATHERINE).hit_points == \
        _roster(pathlib.Path(SAVE), KATHERINE).hit_points


# --- class: record 0x073 code, 0x0EB bitmask --------------------------------

@live
def test_a_class_code_and_bitmask_that_disagree_survive_a_round_trip(tmp_path):
    """The shape DWARVEN FIGHTER ships in: a fighter's bits, a cleric's code."""
    src = _construct(tmp_path, "class", MALCYON,
                     record={"class_bits": 8, "char_class": 0})
    _unchanged(src, tmp_path)


@live
def test_a_class_combination_with_no_code_at_all_survives_a_round_trip(tmp_path):
    """magic-user/cleric/thief is one of the three the game's code table cannot
    express. Import must not reach for a code it has not got."""
    src = _construct(tmp_path, "nocode", MALCYON,
                     record={"class_bits": 1 | 2 | 4, "char_class": 5})
    _unchanged(src, tmp_path)


# --- level: record 0x0A0, per-class array 0x0C9-0x0CC -----------------------

@live
def test_a_character_level_above_the_per_class_array_survives_a_round_trip(tmp_path):
    """The level-drain shape: 0x0A0 is the level attained, the array the level
    now. If they are base-and-current like every other pair here, a save can
    hold this and an import that edits nothing must not flatten it."""
    src = _construct(tmp_path, "levelhigh", ROLAND, record={"level": 3})
    _unchanged(src, tmp_path)


@live
def test_a_character_level_below_the_per_class_array_survives_a_round_trip(tmp_path):
    src = _construct(tmp_path, "levellow", ROLAND, record={"level_cleric": 4})
    _unchanged(src, tmp_path)


@live
def test_a_multi_class_level_disagreement_survives_a_round_trip(tmp_path):
    """What 0x0A0 holds for a multi-class character is unproven, so the import
    has no business writing the highest of the array over it unasked."""
    src = _construct(tmp_path, "levelmulti", KATHERINE,
                     record={"level_magic_user": 3, "level_thief": 2, "level": 1})
    _unchanged(src, tmp_path)


@live
def test_an_unrelated_edit_leaves_a_disagreeing_level_alone(tmp_path):
    """Editing one character's money must not rewrite another character's
    level. This is the drive-by version of the same fault."""
    src = _construct(tmp_path, "driveby", ROLAND, record={"level": 3})
    data = export_save(str(src), GAME)
    next(e for e in data["party"] if e["slot"] == MALCYON)["platinum"] = 42
    out = tmp_path / "driveby-edit.d64"
    changes = import_into(str(src), data, str(out), game_disk=GAME)
    assert changes == ["slot 0 MALCYON: platinum 100 -> 42"]
    assert _record(out, ROLAND).get("level") == 3


@live
def test_an_empty_per_class_array_leaves_the_character_level_alone(tmp_path):
    """The other side of the same rule, and the case that already works: with
    no per-class level to derive from, 0x0A0 is left as it stands."""
    src = _construct(tmp_path, "zeroarray", ROLAND,
                     record={"level_cleric": 0, "level": 4})
    _unchanged(src, tmp_path)


@live
def test_editing_a_per_class_level_moves_the_character_level_deliberately(tmp_path):
    """The edit path, which is allowed to reconcile: ask for a level and both
    halves move, and the change list says so."""
    src = _construct(tmp_path, "leveledit", ROLAND, record={"level": 3})
    data = export_save(str(src), GAME)
    next(e for e in data["party"] if e["slot"] == ROLAND)["levels"]["cleric"] = 5
    out = tmp_path / "leveledit-out.d64"
    changes = import_into(str(src), data, str(out), game_disk=GAME)
    assert _record(out, ROLAND).get("level_cleric") == 5
    assert _record(out, ROLAND).get("level") == 5
    assert any("level 3 -> 5" in c for c in changes)


# --- strength: record 0x014 plus 0x01A percentile, 0x0E2 effective ----------

@live
def test_an_effective_strength_that_does_not_match_the_score_survives(tmp_path):
    """0x0E2 collapses the exceptional bands to one number and the game refills
    it in its own time -- MALCYON's sat at his pre-edit 15 for eight saves. So
    a save really does hold this state, and it must survive."""
    src = _construct(tmp_path, "strength", ROLAND,
                     record={"strength": 18, "exceptional_strength": 90,
                             "strength_index": 15})
    _unchanged(src, tmp_path)


@live
def test_editing_strength_leaves_the_effective_strength_untouched(tmp_path):
    """wish does not export 0x0E2, so an edited score leaves it stale. The
    cached combat numbers that depend on strength are flagged; 0x0E2 is not."""
    data = export_save(SAVE, GAME)
    who = next(e for e in data["party"] if e["slot"] == ROLAND)
    who["strength"], who["exceptional_strength"] = 18, 90
    out = tmp_path / "str.d64"
    import_into(SAVE, data, str(out), game_disk=GAME)
    assert _record(out, ROLAND).get("strength_index") == 15      # was 15 for STR 15
    warnings = next(e for e in export_save(str(out), GAME)["party"]
                    if e["slot"] == ROLAND)["_warnings"]
    assert any("damage bonus is cached as" in w for w in warnings)


# --- the roster's own copy of which slot it describes, at +0x0D -------------

@live
def test_a_roster_block_naming_the_wrong_slot_survives_a_round_trip(tmp_path):
    """+0x0D equals the block's own position in every save, which is exactly
    the evidence that proves nothing: wish keys off the position, so a block
    that names another slot must come through untouched, not corrected."""
    src = _construct(tmp_path, "slotindex", ROLAND, roster={0x0D: 7})
    _unchanged(src, tmp_path)


@live
def test_an_occupied_slot_with_an_empty_roster_block_survives_a_round_trip(tmp_path):
    """Occupancy is recorded twice -- a character record in SAVEDGAME0 and a
    non-zero block in SAVEDGAME1. A slot with no roster block is a state the
    game never writes, so nothing has ever exercised the export of one."""
    src = _construct(tmp_path, "noroster", ROLAND,
                     roster={n: 0 for n in range(ROSTER_STRIDE)})
    assert not _roster(src, ROLAND).occupied
    _unchanged(src, tmp_path)


# --- spells: record 0x078 known, 0x020 memorised ----------------------------

@live
def test_a_memorised_spell_outside_the_spellbook_survives_a_round_trip(tmp_path):
    """The two lists are different sets of different sizes, and the check that
    every memorised spell is known is reported, never enforced."""
    src = tmp_path / "spells.d64"
    shutil.copy(SAVE, src)
    img = D64.open(str(src))
    sg = SaveGame0.from_prg(img.read_file(b"SAVEDGAME0"))
    rec = sg.slot(MALCYON).record
    rec.set_raw("spells_memorised", bytes([44]) + bytes(15))   # not in his book
    sg.write_record(MALCYON, rec)
    img.write_file_inplace(b"SAVEDGAME0", sg.to_prg())
    img.save(str(src))
    assert _record(src, MALCYON).get_raw("spells_memorised")[0] == 44
    _unchanged(src, tmp_path)
