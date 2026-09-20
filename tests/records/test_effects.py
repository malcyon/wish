"""Tests for `goldbox/effects.py`: the port off `automap/live.py`, and the
ECL65 spell-effect table reader, both from `#13 (Edit traits and active
effects, in two separate panels)`.
"""

from __future__ import annotations

import pytest
from gamedata import game_disk

from goldbox import effects
from tools.c64 import coldread

# --- S1: the port, and the two new writers -----------------------------------


def test_the_four_offsets_match_the_cold_read_evidence():
    """Ported, not re-derived: the same offsets
    `tests/c64/test_coldread.py::test_the_effect_arrays_sit_where_the_save_image_puts_them`
    measures against the running overlays.
    """
    assert (effects.EFFECT_ID_OFFSET, effects.EFFECT_OWNER_OFFSET,
            effects.EFFECT_DURATION_OFFSET, effects.EFFECT_MAGNITUDE_OFFSET) == \
        tuple(offset for _, offset in coldread.EFFECT_ARRAYS)
    assert effects.EFFECT_SLOTS == coldread.EFFECT_SLOTS


def test_automap_live_reexports_the_same_names():
    """`automap/live.py` imports these back under the same names, so
    `automap/combat.py`, `tools/gui/combatshot.py`, `tools/gui/livestrip.py` and
    `tests/c64/test_coldread.py` still resolve `live.EFFECT_ID_OFFSET` and the
    rest unchanged.
    """
    from automap import live

    for name in ("EFFECT_ID_OFFSET", "EFFECT_OWNER_OFFSET",
                 "EFFECT_DURATION_OFFSET", "EFFECT_MAGNITUDE_OFFSET",
                 "EFFECT_SLOTS", "FIRST_MONSTER", "PARTY_WIDE",
                 "DURATION_COUNT", "DURATION_UNIT"):
        assert getattr(live, name) is getattr(effects, name)
    assert live.Effect is effects.Effect
    assert live.active_effects is effects.active_effects


def _blank_payload() -> bytearray:
    # Long enough to cover the magnitude array, the last of the four and the
    # furthest from $0.
    return bytearray(effects.EFFECT_MAGNITUDE_OFFSET + effects.EFFECT_SLOTS)


def test_write_then_read_round_trips_on_a_synthetic_payload():
    payload = _blank_payload()
    effects.write_effect(payload, 5, id=12, owner=3, duration=0x0A, magnitude=0xE2)
    (found,) = effects.active_effects(bytes(payload))
    assert (found.slot, found.id, found.owner, found.duration, found.magnitude) == \
        (5, 12, 3, 0x0A, 0xE2)


def test_write_effect_refuses_a_slot_out_of_range():
    payload = _blank_payload()
    with pytest.raises(ValueError):
        effects.write_effect(payload, effects.EFFECT_SLOTS,
                             id=1, owner=0, duration=0, magnitude=0)


def test_write_effect_refuses_a_value_that_is_not_a_byte():
    payload = _blank_payload()
    with pytest.raises(ValueError):
        effects.write_effect(payload, 0, id=256, owner=0, duration=0, magnitude=0)


def test_clear_effect_zeroes_all_four_arrays_and_nothing_else():
    payload = bytearray(b"\xAA" * (effects.EFFECT_MAGNITUDE_OFFSET
                                   + effects.EFFECT_SLOTS))
    effects.write_effect(payload, 9, id=1, owner=3, duration=6, magnitude=7)
    before = bytes(payload)

    effects.clear_effect(payload, 9)

    touched = {effects.EFFECT_ID_OFFSET + 9, effects.EFFECT_OWNER_OFFSET + 9,
               effects.EFFECT_DURATION_OFFSET + 9,
               effects.EFFECT_MAGNITUDE_OFFSET + 9}
    for i in touched:
        assert payload[i] == 0
    changed = {i for i in range(len(payload)) if payload[i] != before[i]}
    assert changed == touched


def test_clear_effect_refuses_a_slot_out_of_range():
    payload = _blank_payload()
    with pytest.raises(ValueError):
        effects.clear_effect(payload, -1)


# --- the duration byte and the restore flag ---------------------------------


@pytest.mark.parametrize("byte, count, unit, minutes", [
    (0x05, 5, "minute", 5),
    (0x45, 5, "ten minutes", 50),
    (0x85, 5, "hour", 300),
    (0xC5, 5, "day", 7200),
    (0x3F, 63, "minute", 63),
])
def test_duration_unit_splits_count_and_unit(byte, count, unit, minutes):
    d = effects.duration_unit(byte)
    assert (d.count, d.unit, d.minutes) == (count, unit, minutes)
    assert not d.never_expires


def test_a_duration_byte_of_zero_never_expires_but_a_zero_count_in_a_unit_does():
    assert effects.duration_unit(0x00).never_expires
    assert effects.duration_unit(0x00).minutes == 0
    assert not effects.duration_unit(0x40).never_expires


def test_duration_unit_refuses_a_value_that_is_not_a_byte():
    with pytest.raises(ValueError):
        effects.duration_unit(256)


def test_the_ids_that_read_their_magnitude_back():
    assert effects.MAGNITUDE_VALUE_IDS == {12, 14, 38}
    assert effects.MAGNITUDE_BRANCH_IDS == {131, 132}
    assert effects.MAGNITUDE_READ_IDS == {12, 14, 38, 131, 132}


def test_id_13_restores_a_statistic_in_combat_only():
    assert effects.COMBAT_MAGNITUDE_VALUE_IDS == {12, 13, 14, 38}
    assert effects.MAGNITUDE_VALUE_IDS < effects.COMBAT_MAGNITUDE_VALUE_IDS
    assert 13 not in effects.MAGNITUDE_VALUE_IDS
    e = effects.Effect(slot=0, id=13, owner=0, duration=1, magnitude=0xE2)
    assert e.restores_a_statistic is False


@pytest.mark.parametrize("eid, magnitude, expected", [
    (12, 0xE2, True),      # ENLARGE with a strength to put back
    (38, 0x80, True),
    (14, 0xF4, True),
    (12, 0x62, False),     # bit 7 clear: nothing to restore
    (131, 0xE2, False),    # reads bit 7 only as a branch, no statistic
    (1, 0xFF, False),      # not in the handler list at all
])
def test_restores_a_statistic_needs_bit_7_and_a_value_reading_id(
        eid, magnitude, expected):
    e = effects.Effect(slot=0, id=eid, owner=0, duration=1, magnitude=magnitude)
    assert e.restores_a_statistic is expected


def test_the_detail_line_names_the_unit_and_the_never_expires_case():
    timed = effects.Effect(slot=0, id=1, owner=0, duration=0x85, magnitude=0)
    assert "5 x hour" in timed.detail
    forever = effects.Effect(slot=0, id=1, owner=0, duration=0, magnitude=0)
    assert "never expires" in forever.detail


# --- S2: the ECL65 spell-effect table -----------------------------------------
#
# `docs/50-experiments.md` confirms record 1's duration byte live as BLESS's
# $06. Record 12 (ENLARGE) is the specimen this project has for a spell whose
# *whole* duration scales with caster level: the table's own duration byte is
# 0 and `per_level` is $0A, matching the $0A a level-1 cast wrote to the save
# (`$4980`, `docs/50-experiments.md`).


@pytest.fixture(scope="module")
def table():
    return effects.load_effect_table(str(game_disk("POOL1")))


def test_the_table_has_one_entry_per_position_1_through_67(table):
    assert sorted(table) == list(range(1, effects.EFFECT_TABLE_RECORD_COUNT + 1))


def test_record_1_is_bless(table):
    assert table[1].duration == 0x06


def test_record_12_is_enlarge_and_scales_entirely_by_level(table):
    assert table[12].duration == 0
    assert table[12].per_level == 0x0A
