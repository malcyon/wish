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
def test_duration_unit_splits_count_and_unit_and_minutes_is_at_most(
        byte, count, unit, minutes):
    d = effects.duration_unit(byte)
    assert (d.count, d.unit, d.minutes) == (count, unit, minutes)
    assert not d.never_expires


def test_the_four_units_are_minute_ten_minutes_hour_and_day():
    """The mapping two driven rests measured, in order of bits 6-7."""
    assert effects.DURATION_UNIT_NAMES == ("minute", "ten minutes", "hour", "day")
    assert effects.DURATION_UNIT_MINUTES == (1, 10, 60, 1440)
    assert len(effects.DURATION_UNIT_NAMES) == 4     # two bits, so no month


# The duration bytes of the two driven rests, typed in rather than read off a
# disk: four slots staged at count 32, one per unit, and the bytes they read
# back as. Each count fell by the number of clock boundaries the rest crossed.
THIRTY_MINUTE_REST = [
    # before, after, unit, boundaries crossed between 21:16 and 21:46
    (0x1F, 0x01, "minute", 30),          # 30 minutes
    (0x60, 0x5D, "ten minutes", 3),      # the wraps at :20, :30 and :40
    (0xA0, 0xA0, "hour", 0),
    (0xE0, 0xE0, "day", 0),
]
EIGHT_HOUR_REST = [
    # before, after, unit, boundaries crossed between 21:17 and 05:17
    (0xA0, 0x98, "hour", 8),
    (0xE0, 0xDF, "day", 1),
]


@pytest.mark.parametrize("before, after, unit, boundaries",
                         THIRTY_MINUTE_REST + EIGHT_HOUR_REST)
def test_a_rest_takes_one_count_per_boundary_crossed(before, after, unit,
                                                     boundaries):
    was, now = effects.duration_unit(before), effects.duration_unit(after)
    assert (was.unit, now.unit) == (unit, unit)
    assert was.count - now.count == boundaries


def test_the_ten_minute_unit_loses_its_first_count_before_ten_minutes_pass():
    """`minutes` is an upper bound rather than the time left: staged at 21:16,
    the unit-01 count lost its first ten-minute unit at 21:20, four minutes in.
    """
    staged = effects.duration_unit(0x60)
    assert (staged.count, staged.minutes) == (32, 320)
    assert staged.count - effects.duration_unit(0x5D).count == 3


def test_an_expired_slot_is_dropped_and_a_never_expiring_one_is_kept():
    """What the eight-hour rest left behind: an expired slot reads id 0 with a
    duration byte of 0, and a slot staged with a duration byte of 0 keeps its
    id and is still running.
    """
    payload = _blank_payload()
    effects.write_effect(payload, 3, id=0, owner=5, duration=0, magnitude=0xE2)
    effects.write_effect(payload, 4, id=1, owner=5, duration=0, magnitude=0)

    listed = effects.active_effects(bytes(payload))

    assert [e.slot for e in listed] == [4]
    assert effects.duration_unit(listed[0].duration).never_expires


def test_only_a_duration_byte_of_exactly_zero_is_marked_never_expires():
    # Pins the flag only: what the ageing routines do to `$40` is not established.
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


@pytest.mark.parametrize("eid, in_combat, expected", [
    (13, False, False),
    (13, True, True),
    (12, False, True),
    (12, True, True),
    (14, False, True),
    (14, True, True),
    (38, False, True),
    (38, True, True),
    (1, True, False),      # outside the combat lower bound as well
])
def test_restores_a_statistic_in_asks_out_of_combat_and_in_it(
        eid, in_combat, expected):
    e = effects.Effect(slot=0, id=eid, owner=0, duration=1, magnitude=0xE2)
    assert e.restores_a_statistic_in(in_combat=in_combat) is expected


def test_restores_a_statistic_in_still_needs_bit_7_in_combat():
    e = effects.Effect(slot=0, id=13, owner=0, duration=1, magnitude=0x62)
    assert e.restores_a_statistic_in(in_combat=True) is False


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
