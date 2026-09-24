"""Tests for `goldbox/effects.py`: the port off `automap/live.py`, and the
ECL65 spell-effect table reader, both from `#13 (Edit traits and active
effects, in two separate panels)`.
"""

from __future__ import annotations

import bisect

import pytest
from gamedata import game_disk

from automap import gamedisks
from goldbox import c64_port, effects
from tools.c64 import coldread, d6502, effectcrosswalk

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
    # Pins the flag only. `$40` does count down, a whole unit at a time --
    # `test_a_zero_count_drops_a_unit_rather_than_expiring` has that.
    assert effects.duration_unit(0x00).never_expires
    assert effects.duration_unit(0x00).minutes == 0
    assert not effects.duration_unit(0x40).never_expires


def test_duration_unit_refuses_a_value_that_is_not_a_byte():
    with pytest.raises(ValueError):
        effects.duration_unit(256)


# --- S2a: how much time a duration byte has left at a time of day -----------
#
# The camp ageing routine, written out as the engine runs it, one minute to a
# call: Pool of Radiance `CAMP $1283` ticks the clock and ORs a bit into a
# wrapped-digit mask, then `$12BE` takes the elapsed minutes off a unit-00
# count and one off a coarser count whose digit wrapped. Curse of the Azure
# Bonds (`$1432`, `$146D`) and Secret of the Silver Blades (`$126B`, `$12A6`)
# are the same code at their own addresses. This is the model
# `effects.remaining_minutes` states in closed form, and the point of keeping
# both is that they were written from different ends.
_WRAPS_AT = (None, 10, 60, 1440)


def _age_one_minute(byte: int, clock: int) -> int:
    """The byte a camp call passing one minute leaves behind."""
    count, unit = byte & effects.DURATION_COUNT, byte >> effects.DURATION_UNIT
    if byte == 0:
        return 0                                     # skipped, never aged
    if unit == 0:
        return max(count - 1, 0)
    if (clock + 1) % _WRAPS_AT[unit]:
        return byte                                  # its digit did not wrap
    return 0 if count == 1 else byte - 1             # `$12D6`'s DEX, then DEC


def _minutes_until_gone(byte: int, clock: int) -> int:
    for minute in range(1, 200_000):
        byte, clock = _age_one_minute(byte, clock), (clock + 1) % 1440
        if byte == 0:
            return minute
    raise AssertionError("a running byte that never expired")


@pytest.mark.parametrize("clock", [0, 1, 6, 17, 59, 1439])
@pytest.mark.parametrize("byte", [b for b in range(1, 0x80)
                                  if b & effects.DURATION_COUNT])
def test_the_closed_form_agrees_with_the_camp_sweep_minute_by_minute(byte, clock):
    """Every minute and ten-minute byte, at six times of day."""
    assert effects.remaining_minutes(byte, clock) == _minutes_until_gone(byte, clock)


@pytest.mark.parametrize("clock", [0, 23, 1439])
@pytest.mark.parametrize("byte", [0x81, 0x82, 0x98, 0xBF, 0xC1, 0xC2])
def test_the_closed_form_agrees_on_the_hour_and_day_units(byte, clock):
    assert effects.remaining_minutes(byte, clock) == _minutes_until_gone(byte, clock)


@pytest.mark.parametrize("byte, clock", [(0x40, 0), (0x40, 7), (0x80, 23),
                                         (0xC0, 1439)])
def test_a_zero_count_drops_a_unit_rather_than_expiring(byte, clock):
    """`$12BE` takes the count into X, and `$12D6`'s `DEX` on a zero count
    gives `$FF` rather than zero, so `$12D9` takes one off the whole byte:
    `$40` becomes `$3F` at the next ten-minute boundary. So the byte does run
    out, a unit later than its count says.
    """
    assert effects.remaining_minutes(byte, clock) == _minutes_until_gone(byte, clock)
    assert effects.remaining_minutes(byte, clock) > 0


# The two driven rests again, this time as clock readings: the same four
# slots, the same two rests, read as the time each had left rather than as
# counts. `remaining_minutes` has to lose exactly the minutes that passed.
DRIVEN_RESTS = [
    # before, clock before, after, clock after, minutes rested
    (0x1F, 21 * 60 + 16, 0x01, 21 * 60 + 46, 30),
    (0x60, 21 * 60 + 16, 0x5D, 21 * 60 + 46, 30),
    (0xA0, 21 * 60 + 17, 0x98, 5 * 60 + 17, 480),
    (0xE0, 21 * 60 + 17, 0xDF, 5 * 60 + 17, 480),
]


@pytest.mark.parametrize("before, was, after, now, rested", DRIVEN_RESTS)
def test_the_two_driven_rests_lose_exactly_the_minutes_they_passed(
        before, was, after, now, rested):
    assert effects.remaining_minutes(before, was) - rested == \
        effects.remaining_minutes(after, now)


def test_a_running_bless_of_two_minutes_converts_exactly_at_every_clock():
    """The six `CHRDATJ` records on this machine each hold `01 02 00 01 00`,
    a Bless with two minutes left (asserted, from the player's own saves, by
    `tests/convert/test_runningeffects.py::test_the_six_running_bless_records_in_the_players_saves_come_back_whole`).
    Every DOS duration of 1 to 63 minutes has an exact C64 byte whatever the
    time of day, so the case the conversion actually meets loses nothing.
    """
    for clock in range(1440):
        assert 0x02 in effects.exact_durations(2, clock)
        assert effects.longest_duration_within(2, clock) == 0x02
        assert effects.closest_duration(2, clock) == 0x02


def test_every_duration_up_to_63_minutes_is_exact_and_most_above_it_are_not():
    """At one time of day the four units reach 213 to 216 of the 65,535 values
    a DOS duration word can hold. Counted here over every byte the engine
    writes, independently of `tools/c64/effectcrosswalk.py`'s own census, and
    it agrees with it phase for phase. The ceiling is the DOS word: a count of
    47 days or more outlives anything a DOS record can ask for.
    """
    spread: dict[int, int] = {}
    for clock in range(1440):
        values = {left for left in
                  (effects.remaining_minutes(b, clock)
                   for b in range(1, 0x100) if b & effects.DURATION_COUNT)
                  if left <= 0xFFFF}
        assert set(range(1, 64)) <= values
        spread[len(values)] = spread.get(len(values), 0) + 1
    assert spread == {213: 21, 214: 276, 215: 702, 216: 441}


#: Source durations the two selection rules are measured over: every minute to
#: 4,200, a stride of 37 above it to the DOS word's ceiling, and the two values
#: just under a day-unit boundary that the stride can miss.
COST_MINUTES = (list(range(1, 4201)) + list(range(4201, 0x10000, 37))
                + [5759, 0xFFFF])

#: Bands of source duration, by the coarsest unit that can reach them: the
#: minute unit is exact to 63, the ten-minute unit ends at 630 (less the phase),
#: the hour unit at 3,780, and only the day unit goes past that.
COST_BANDS = ((1, 63), (64, 630), (631, 3780), (3781, 0xFFFF))

#: The most a byte can miss its source by, per band, over every time of day.
#: `longest_duration_within` never outlasts the source and falls short by up to
#: this much; `closest_duration` may err either way and by less. Measured over
#: `COST_MINUTES` at all 1,440 clocks; each is also attained, so it is the
#: worst case and not merely a bound that happens to hold.
FALLS_SHORT_BY = (0, 9, 59, 1439)
CLOSEST_ERR = (0, 9, 59, 720)


def _times_left(clock: int) -> list[int]:
    """Every distinct time a count-bearing duration byte has left at `clock`."""
    return sorted({effects.remaining_minutes(b, clock) for b in range(1, 0x100)
                   if b & effects.DURATION_COUNT})


def _nearest_by_search(minutes: int, times: list[int]) -> int:
    i = bisect.bisect_left(times, minutes)
    return min((times[j] for j in (i - 1, i) if 0 <= j < len(times)),
               key=lambda left: (abs(left - minutes), left))


@pytest.fixture(scope="module")
def cost_by_band():
    """Worst (error, minutes, clock) per band for each rule, over every clock.

    Found from the sorted set of times a byte can have left, so the two rules
    are not run 2 million times; `test_both_rules_pick_what_a_brute_force_picks`
    is what ties this search to the functions themselves.
    """
    short = [(0, 0, 0)] * len(COST_BANDS)
    err = [(0, 0, 0)] * len(COST_BANDS)
    for clock in range(1440):
        times = _times_left(clock)
        for minutes in COST_MINUTES:
            band = next(i for i, (_, hi) in enumerate(COST_BANDS) if minutes <= hi)
            below = times[bisect.bisect_right(times, minutes) - 1]
            lost = minutes - below
            if lost > short[band][0]:
                short[band] = (lost, minutes, clock)
            miss = abs(_nearest_by_search(minutes, times) - minutes)
            if miss > err[band][0]:
                err[band] = (miss, minutes, clock)
    return short, err


def test_the_longest_byte_within_a_duration_never_outlasts_it_and_falls_short_by_a_bounded_amount(
        cost_by_band):
    """The bound on what a never-lengthen policy costs, and that it is reached.
    Only a duration longer than 63 hours needs the day unit and its 1,439
    minutes, and no spell row in the three titles' own tables can produce one.
    """
    short, _ = cost_by_band
    assert tuple(worst for worst, _, _ in short) == FALLS_SHORT_BY
    for worst, minutes, clock in short[1:]:
        byte = effects.longest_duration_within(minutes, clock)
        assert minutes - effects.remaining_minutes(byte, clock) == worst


def test_the_closest_byte_to_a_duration_errs_by_a_bounded_amount(cost_by_band):
    """The rule Donald chose: at most 9 minutes wrong to 630 minutes, 59 to
    3,780 and 720 beyond, exact to 63, at every time of day, and each reached.
    """
    _, err = cost_by_band
    assert tuple(worst for worst, _, _ in err) == CLOSEST_ERR
    for worst, minutes, clock in err[1:]:
        byte = effects.closest_duration(minutes, clock)
        assert abs(effects.remaining_minutes(byte, clock) - minutes) == worst


def test_the_closest_byte_is_never_further_away_than_the_longest_within():
    for clock in (0, 9, 59, 600, 1439):
        for minutes in list(range(1, 700)) + [3780, 3781, 5000, 5759, 0xFFFF]:
            near = effects.closest_duration(minutes, clock)
            low = effects.longest_duration_within(minutes, clock)
            assert (abs(effects.remaining_minutes(near, clock) - minutes)
                    <= minutes - effects.remaining_minutes(low, clock))


#: Sixteen times of day: midnight, both sides of every unit's boundary, and the
#: two clocks that hit the worst cases above.
SIXTEEN_CLOCKS = [0, 1, 6, 7, 9, 10, 23, 59, 60, 61, 600, 719, 720, 1000, 1439,
                  1438]


@pytest.mark.parametrize("clock", SIXTEEN_CLOCKS)
def test_both_rules_pick_what_a_brute_force_picks(clock):
    """Every byte tried against `remaining_minutes`, nothing else: the byte
    nearest the source, then the shorter time, then the smaller unit; and the
    byte with the most time left that does not outlast it.
    """
    candidates = [(b, effects.remaining_minutes(b, clock))
                  for b in range(1, 0x100) if b & effects.DURATION_COUNT]
    for minutes in (list(range(1, 800)) + list(range(800, 0x10000, 211))
                    + [3780, 3781, 5759, 0xFFFF]):
        nearest = min(candidates, key=lambda c: (abs(c[1] - minutes), c[1],
                                                 c[0] >> effects.DURATION_UNIT))
        assert effects.closest_duration(minutes, clock) == nearest[0]
        under = [c for c in candidates if c[1] <= minutes]
        if under:
            most = max(left for _, left in under)
            byte = effects.longest_duration_within(minutes, clock)
            assert effects.remaining_minutes(byte, clock) == most
        else:
            assert effects.longest_duration_within(minutes, clock) is None


def test_a_tie_in_error_goes_to_the_shorter_time_left():
    # At midnight 75 minutes is 5 from both 70 (`$47`) and 80 (`$48`).
    assert (effects.remaining_minutes(0x47, 0), effects.remaining_minutes(0x48, 0)) \
        == (70, 80)
    assert effects.closest_duration(75, 0) == 0x47


def test_a_tie_in_time_left_goes_to_the_smaller_unit():
    # At midnight 60 minutes is exactly `$3C` (unit 00), `$46` (unit 01) and
    # `$81` (unit 10); the minute unit is the one the engine ages most finely.
    assert {0x3C, 0x46, 0x81} <= set(effects.exact_durations(60, 0))
    assert effects.closest_duration(60, 0) == 0x3C
    assert effects.closest_duration(10, 0) == 0x0A       # not `$41`, also 10


def test_the_closest_byte_is_exact_when_an_exact_byte_exists():
    for clock in SIXTEEN_CLOCKS:
        for minutes in range(1, 700):
            exact = effects.exact_durations(minutes, clock)
            if exact:
                byte = effects.closest_duration(minutes, clock)
                assert effects.remaining_minutes(byte, clock) == minutes
                assert byte in exact


def test_nothing_is_closest_to_a_source_with_less_than_a_minute_left():
    assert effects.closest_duration(0, 0) is None


def test_the_closed_form_is_the_one_the_crosswalk_tool_holds():
    """`tools/c64/effectcrosswalk.py` states the same formula with a stricter
    contract (a zero count raises); the two must not drift apart.
    """
    for clock in range(1440):
        for byte in range(1, 0x100):
            if byte & effects.DURATION_COUNT:
                assert effects.remaining_minutes(byte, clock) == \
                    effectcrosswalk.remaining_minutes(byte, clock)


def test_nothing_fits_a_source_with_less_than_a_minute_left():
    assert effects.longest_duration_within(0, 0) is None


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


# --- S3: the camp ageing routine, read off the player's own disks -------------
#
# `remaining_minutes` above states in closed form what these three routines
# do, so its grade rests on them: the same code at three sets of addresses,
# each read here from the title's own overlay rather than quoted. Every
# address is at load base `$0800` except Silver Blades' clock tick, which its
# `LIBRARY` holds at `$2DC8`. `docs/226-the-c64-running-effect-crosswalk.md`
# is the write-up.

#: Per title: the CAMP sites, then the clock tick's file, base and sites.
#: `id_read` and `dur_read` are the sweep's two skips, `count_mask` and
#: `unit_mask` split the byte, `mask_read` asks whether that unit's digit
#: wrapped, `dex`/`dec` take one off a coarse count and `sub` takes the whole
#: elapsed minutes off a unit-00 one.
CAMP_AGEING = {
    "pool-of-radiance": dict(
        arrays=(0x4900, 0x4980), id_read=0x129E, dur_read=0x12A3,
        dur_store=0x12AE, count_mask=0x12C2, unit_mask=0x12C6,
        mask_read=0x12D1, dex=0x12D6, dec=0x12D9, sub=0x12E2,
        tick_file="CAMP", tick_base=0x0800, tick=0x124A, clock=0x49C6,
        radix_cmp=0x1250, radix=0x127D, bit_ora=0x1269, bits=0x165A),
    "curse-of-the-azure-bonds": dict(
        arrays=(0x4B00, 0x4B80), id_read=0x144D, dur_read=0x1452,
        dur_store=0x145D, count_mask=0x1471, unit_mask=0x1475,
        mask_read=0x1480, dex=0x1485, dec=0x1488, sub=0x1491,
        tick_file="CAMP", tick_base=0x0800, tick=0x13F9, clock=0x4BC6,
        radix_cmp=0x13FF, radix=0x142C, bit_ora=0x1418, bits=0x18AF),
    "secret-of-the-silver-blades": dict(
        arrays=(0x4B00, 0x4B80), id_read=0x1286, dur_read=0x128B,
        dur_store=0x1296, count_mask=0x12AA, unit_mask=0x12AE,
        mask_read=0x12B9, dex=0x12BE, dec=0x12C1, sub=0x12CA,
        tick_file="LIBRARY", tick_base=0x2DC8, tick=0x46B6, clock=0x4BC6,
        radix_cmp=0x46C8, radix=0x46DE, bit_ora=0x46D5, bits=0x46E5),
}

#: The combat round's ageing, which decrements unit `00` and nothing else.
COMBAT_AGEING = {
    "pool-of-radiance": ("COMBAT", 0x0800, 0x4980, 0x2228, 0x222D, 0x2231),
    "curse-of-the-azure-bonds": ("COMBAT2", 0xE000, 0x4B80, 0xFA7C, 0xFA81,
                                 0xFA85),
    "secret-of-the-silver-blades": ("COMBAT2", 0xE000, 0x4B80, 0xF751, 0xF756,
                                    0xF75A),
}


def _disks(title):
    try:
        root = gamedisks.find(title)
    except gamedisks.RegistryMissing:
        root = None
    if root is None:
        pytest.skip(f"Needs the player's {title} disks")
    return str(root)


def _overlay(title, name):
    return coldread.overlay(c64_port.by_key(title), name.encode(), _disks(title))


def _operand(body, base, at, opcode):
    """The operand of the instruction that has to be at `at`, or fail loudly."""
    off = at - base
    assert body[off] == opcode, f"${at:04X} is ${body[off]:02X}, not ${opcode:02X}"
    width = d6502.SZ[d6502.T[opcode][1]]
    return int.from_bytes(body[off + 1:off + width], "little")


@pytest.mark.parametrize("title", sorted(CAMP_AGEING))
def test_the_camp_sweep_skips_a_zero_id_and_a_zero_duration(title):
    site = CAMP_AGEING[title]
    camp = _overlay(title, "CAMP")
    ids, durations = site["arrays"]
    assert _operand(camp, 0x0800, site["id_read"], 0xBD) == ids
    assert _operand(camp, 0x0800, site["dur_read"], 0xBD) == durations
    assert _operand(camp, 0x0800, site["dur_store"], 0x9D) == durations
    for at in (site["id_read"], site["dur_read"]):
        assert camp[at - 0x0800 + 3] == 0xF0          # BEQ past the slot


@pytest.mark.parametrize("title", sorted(CAMP_AGEING))
def test_a_coarse_count_loses_one_per_wrap_and_a_minute_count_the_elapsed(title):
    """The per-slot rule `remaining_minutes` is the closed form of."""
    site = CAMP_AGEING[title]
    camp = _overlay(title, "CAMP")
    assert _operand(camp, 0x0800, site["count_mask"], 0x29) == effects.DURATION_COUNT
    assert _operand(camp, 0x0800, site["unit_mask"], 0x29) == 0xC0
    assert _operand(camp, 0x0800, site["mask_read"], 0x39) == site["bits"]
    assert camp[site["dex"] - 0x0800] == 0xCA         # DEX, then
    assert camp[site["dec"] - 0x0800] == 0xCE         # DEC the whole byte
    assert camp[site["sub"] - 0x0800] == 0xED         # SBC the elapsed minutes


@pytest.mark.parametrize("title", sorted(CAMP_AGEING))
def test_the_clock_radix_is_what_makes_a_wrap_land_on_a_unit_boundary(title):
    """Ten minute-units to a wrap, six tens to an hour, 24 hours to a day, so
    the digit one coarser than a unit wraps on every multiple of that unit.
    """
    site = CAMP_AGEING[title]
    where = _overlay(title, site["tick_file"])
    base = site["tick_base"]
    assert _operand(where, base, site["tick"], 0xFE) == site["clock"]
    radix = _operand(where, base, site["radix_cmp"], 0xDD)
    assert radix == site["radix"]
    at = radix - base
    assert tuple(where[at + 1:at + 6]) == (10, 6, 24, 30, 12)
    bits = _operand(where, base, site["bit_ora"], 0x1D)
    assert bits == site["bits"]
    at = bits - base
    assert tuple(where[at:at + 8]) == (1, 2, 4, 8, 0x10, 0x20, 0x40, 0x80)


@pytest.mark.parametrize("title", sorted(COMBAT_AGEING))
def test_a_combat_round_ages_the_minute_unit_and_nothing_coarser(title):
    """`CMP #$40 / BCS` leaves every ten-minute, hour and day count alone, so
    the camp formula does not describe a fight.
    """
    name, base, durations, read, test, dec = COMBAT_AGEING[title]
    body = _overlay(title, name)
    assert _operand(body, base, read, 0xBD) == durations
    assert _operand(body, base, test, 0xC9) == 0x40
    assert body[test - base + 2] == 0xB0              # BCS past the slot
    assert _operand(body, base, dec, 0xDE) == durations


# --- S6: which slot and owner a converted effect takes -----------------------


def _filled(taken: dict[int, tuple[int, int]]) -> bytes:
    payload = _blank_payload()
    for slot, (eid, owner) in taken.items():
        effects.write_effect(payload, slot, id=eid, owner=owner,
                             duration=0x0A, magnitude=0)
    return bytes(payload)


def test_a_new_effect_takes_the_highest_free_slot():
    """The cast asks the allocator for id 0 and owner `$FF`, and the walk runs
    from slot 63 down, so slot 63 is the one a cast fills first.
    """
    assert effects.free_slot(_filled({})) == effects.EFFECT_SLOTS - 1
    assert effects.free_slot(_filled({63: (1, 0), 62: (1, 1)})) == 61
    every = {slot: (1, slot & 7) for slot in range(effects.EFFECT_SLOTS)}
    assert effects.free_slot(_filled(every)) is None


def test_the_allocator_holds_one_slot_per_id_and_owner():
    payload = _filled({10: (38, 2), 40: (38, 5), 50: (38, effects.PARTY_WIDE)})
    # A negative owner matches every query, and the walk meets slot 50 first.
    assert effects.slot_for(payload, 38, 2) == 50
    assert effects.slot_for(payload, 38, 7) == 50
    payload = _filled({10: (38, 2), 40: (38, 5)})
    assert effects.slot_for(payload, 38, 2) == 10
    assert effects.slot_for(payload, 38, 5) == 40
    assert effects.slot_for(payload, 38, 7) is None
    assert effects.slot_for(payload, 12, 2) is None


@pytest.mark.parametrize("owner", (0x80, 0xC0, 0xFE, effects.PARTY_WIDE))
def test_any_owner_with_bit_7_set_answers_every_query(owner):
    """`LIBRARY $3FFB` is a `BMI`, so the whole top half of the byte matches,
    not `$FF` alone -- `$FF` is only the value the cast happens to write.
    """
    payload = _filled({20: (38, owner)})
    assert effects.slot_for(payload, 38, 2) == 20
    assert effects.slot_for(payload, 38, owner) == 20
    assert effects.slot_for(payload, 38, 0x7F) == 20
    assert effects.slot_for(payload, 12, 2) is None


@pytest.mark.parametrize("old, new, replaced", [
    (0x0A, 0x0A, True),                  # a tie goes to the new cast
    (0x0A, 0x0B, True),
    (0x0B, 0x0A, False),
    (0x3F, 0x41, True),                  # the byte, not the time left
    (0x41, 0x3F, False),
    (0x0A, 0x00, True),                  # a new permanent effect always writes
    (0x00, 0x3F, False),                 # an old permanent one is never lost
    (0x00, 0x00, True),
])
def test_which_of_two_casts_keeps_the_slot(old, new, replaced):
    assert effects.replaces_slot(old, new) is replaced


def test_replaces_slot_refuses_a_value_that_is_not_a_byte():
    with pytest.raises(ValueError):
        effects.replaces_slot(0, 256)


@pytest.mark.parametrize("title", sorted(effectcrosswalk.SLOTS))
def test_the_cast_compares_the_two_duration_bytes_and_not_the_time_left(title):
    """The four tests behind `replaces_slot`, read off the player's disks with
    the address each branch goes to: Pool expires the old slot and allocates a
    fresh one where the later titles overwrite in place, and both reach that
    through the same comparison.
    """
    site = effectcrosswalk.SLOTS[title]
    cast = _overlay(title, site.cast_file)
    went = effectcrosswalk.slot_compare(title, cast)
    assert [target for _at, target in went[:2]] == [site.replace_at,
                                                    site.abandon_at]
    assert {target for _at, target in went} == {site.replace_at, site.abandon_at}
    # The cast reads the old byte from the duration array and compares it with
    # the byte it is about to write, so it sees no clock and no unit.
    assert _operand(cast, site.cast_base, site.compare + 5, 0xBD) == site.durations
    assert _operand(cast, site.cast_base, site.compare + 10, 0xCD) == \
        site.new_duration


@pytest.mark.parametrize("title", sorted(effectcrosswalk.SLOTS))
def test_all_three_engines_allocate_from_the_top_and_match_on_id_and_owner(title):
    """The rule above, read off the player's own disks: one allocator in three
    engines, called twice per cast.
    """
    site = effectcrosswalk.SLOTS[title]
    library = _overlay(title, "LIBRARY")
    cast = _overlay(title, site.cast_file)
    assert effectcrosswalk.confirm_slot_rule(title, library, cast) == (
        "Highest free slot", "One slot per id and owner",
        "A negative owner matches any query",
        "The larger duration byte keeps the slot, and zero is not larger",
        "A zero value becomes the caster's level")
    assert _operand(library, effectcrosswalk.SITES[title].library_base,
                    site.search + 6, 0xA2) == effects.EFFECT_SLOTS - 1


# --- S7: the value a converted effect carries --------------------------------


def _dos_engine(title):
    pytest.importorskip("capstone")
    from tools.dos import dosbox

    try:
        folder = dosbox.find_game(effectcrosswalk.DOS_TITLES[title])
    except FileNotFoundError:
        pytest.skip(f"Needs the player's DOS {title} engine")
    return (folder / "GAME.OVR").read_bytes()


@pytest.mark.parametrize("title", sorted(effectcrosswalk.ABILITIES))
def test_the_later_titles_keep_the_image_count_in_the_upper_nibble(title):
    """Both later casts roll `1d4` and shift it up four, so the count is the
    top nibble on both ports even though the C64 magnitude is only the count.
    """
    assert effects.mirror_image_count(0x43, later=True) == 4
    assert effects.mirror_image_count(0x43, later=False) == 0x43
    assert effectcrosswalk.mirror_image_value(title, 0x43) == 4
    site = effectcrosswalk.ABILITIES[title]
    ovr = _dos_engine(title)
    assert ovr[site.dos_mirror_shift:site.dos_mirror_shift + 5] == \
        bytes.fromhex("b90400d3e0")                   # mov cx, 4 / shl ax, cl
    ecl = _overlay(title, "ECL65")
    assert _operand(ecl, 0x8000, site.mirror, 0xA9) == 1      # one d4
    assert _operand(ecl, 0x8000, site.mirror + 5, 0x8D) == site.magnitude


@pytest.mark.parametrize("bonus", range(1, 9))
@pytest.mark.parametrize("level", (0, 1, 10, 15))
def test_a_later_ability_magnitude_is_the_bonus_less_one_and_the_level(bonus, level):
    """What the cast packs and what the recompute reads back, as one round
    trip: the bonus one less than itself in the top nibble, the caster's level
    in the low one and bit 7 set.
    """
    magnitude = effects.later_ability_magnitude(bonus, level)
    assert magnitude & effects.MAGNITUDE_RESTORE_FLAG
    assert magnitude & 0x0F == level
    assert effects.later_ability_bonus(magnitude) == bonus


def test_the_strength_ladder_is_the_recomputes_own_steps():
    """One step is `+1` below 18 and `+10` percentile at it, stopping at
    18/100 -- and the DOS cast's own `(new - 18) * 10 + old` arrives at the
    same score.
    """
    assert effects.raise_strength(15, 0, 3) == (18, 0)
    assert effects.raise_strength(18, 0, 1) == (18, 10)
    assert effects.raise_strength(18, 90, 1) == (18, 100)
    assert effects.raise_strength(18, 100, 4) == (18, 100)
    with pytest.raises(ValueError, match="negative"):
        effects.raise_strength(18, 0, -1)
    # The DOS cast's arithmetic for an arrival past 18, from one at 18/00.
    for steps in range(1, 9):
        assert effects.raise_strength(18, 0, steps) == (18, min(steps * 10, 100))


def test_a_boosted_score_does_not_say_what_the_base_was():
    """The whole grid, counted: 34 of 176 base-and-boost pairs arrive at
    18/100, so a boosted score cannot be walked back down -- which is why both
    ports keep the permanent score beside the one in force and no conversion
    needs an inverse.
    """
    bases = [(strength, 0) for strength in range(3, 18)]
    bases += [(18, percentile) for percentile in (0, 10, 51, 76, 90, 91, 100)]
    tried = capped = 0
    for steps in range(1, 9):
        reached: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for base in bases:
            tried += 1
            reached.setdefault(effects.raise_strength(*base, steps),
                               []).append(base)
        capped += len(reached[effects.STRENGTH_CAP])
        # Knowing the boost, only the cap leaves two bases indistinguishable.
        assert [score for score, from_ in reached.items()
                if len(from_) > 1] == [effects.STRENGTH_CAP]
    assert (tried, capped) == (176, 34)


@pytest.mark.parametrize("title", sorted(effectcrosswalk.ABILITIES))
def test_the_recompute_climbs_one_more_step_than_the_nibble_holds(title):
    """The ladder and its loop, off the player's own disks: the count is the
    operand of an `LDA #` the routine writes to itself, so a nibble of 3
    climbs four steps.
    """
    ecl = _overlay(title, "ECL65")
    effectcrosswalk.strength_ladder(title, ecl)      # raises on a different build
    effectcrosswalk.strength_cast_steps(title, ecl)
    at = effectcrosswalk.ABILITIES[title].strength_recompute
    assert _operand(ecl, 0x8000, at + 7, 0x8D) == at + 66
    assert _operand(ecl, 0x8000, at + 62, 0xCE) == at + 66
    assert _operand(ecl, 0x8000, at + 49, 0xC9) == 90      # 90..99 becomes 100
    assert _operand(ecl, 0x8000, at + 57, 0x69) == 10
    assert effects.later_ability_bonus(0x80 | 3 << 4) == 4


@pytest.mark.parametrize("title", sorted(effectcrosswalk.ABILITIES))
def test_the_dos_cast_clamps_the_arrival_at_18_100(title):
    """The clamp throws the steps away and the node keeps the die roll, so the
    score in force says nothing about the base. Both ports keep the base.
    """
    ovr = _dos_engine(title)
    effectcrosswalk.dos_strength_arrival(title, ovr)
    # Two bases and two rolls that leave the record holding the same thing.
    assert effects.raise_strength(18, 50, 6) == effects.raise_strength(18, 90, 2)
    assert effectcrosswalk.confirm_later_ability_pair(title, ovr)[2].startswith(
        "The recompute derives the in-force bytes")


#: What Enlarge sets a character's strength to, by caster level, with no
#: engine read in front of it: the ten entries both ports write.
ENLARGE_BY_LEVEL = ((1, 18, 0), (2, 18, 1), (3, 18, 51), (4, 18, 76),
                    (5, 18, 91), (6, 18, 100), (7, 19, 0), (8, 20, 0),
                    (9, 21, 0), (10, 22, 0))


@pytest.mark.parametrize("level, strength, percentile", ENLARGE_BY_LEVEL)
def test_every_enlarge_level_reads_back_off_the_score_it_wrote(
        level, strength, percentile):
    """A DOS node exists only where the spell raised the score, so the level a
    converted Enlarge needs is the table entry the record's strength is.
    """
    assert effects.ENLARGE_STRENGTHS[level - 1] == (strength, percentile)
    assert effects.enlarge_level(strength, percentile) == level


@pytest.mark.parametrize("strength, percentile", [
    (18, 2), (18, 50), (17, 0), (23, 0), (22, 1)])
def test_a_score_no_enlarge_writes_has_no_caster_level(strength, percentile):
    assert effects.enlarge_level(strength, percentile) is None


@pytest.mark.parametrize("title", sorted(effectcrosswalk.ABILITIES))
def test_both_ports_enlarge_to_the_same_score_by_caster_level(title):
    """The C64 table and the DOS ladder hold the same ten entries, so the
    level a converted node needs reads straight off the record's own strength.
    """
    site = effectcrosswalk.ABILITIES[title]
    ecl = _overlay(title, "ECL65")
    strengths = ecl[site.strengths - 0x8000:site.strengths - 0x8000 + 12]
    percentiles = ecl[site.percentiles - 0x8000:site.percentiles - 0x8000 + 12]
    assert tuple(zip(strengths, percentiles))[:len(effects.ENLARGE_STRENGTHS)] == \
        effects.ENLARGE_STRENGTHS
    ovr = _dos_engine(title)
    assert effectcrosswalk.dos_enlarge_ladder(title, ovr) == \
        effects.ENLARGE_STRENGTHS
    assert effects.enlarge_level(18, 51) == 3
    assert effects.enlarge_level(22, 0) == 10
    assert effects.enlarge_level(18, 2) is None


@pytest.mark.parametrize("title", sorted(effectcrosswalk.ABILITIES))
def test_a_zero_mirror_image_count_absorbs_nothing_on_both_ports(title):
    """A DOS Curse node whose count nibble has run down to zero converts to
    C64 magnitude 0: neither port's roll absorbs a hit with it, and the C64
    row still expires on its duration.
    """
    combat, library = _overlay(title, "COMBAT"), _overlay(title, "LIBRARY")
    roll = effectcrosswalk.mirror_zero_roll(title, combat, library)
    assert library[roll - 0x2DC8] == 0x98             # TYA, the count into A
    assert effects.mirror_image_count(0x0F, later=True) == 0
    assert effects.mirror_image_count(0x4F, later=True) == 4


@pytest.mark.parametrize("title", sorted(effectcrosswalk.ABILITIES))
def test_the_later_engines_pack_a_bonus_and_a_level_where_dos_packs_neither(title):
    """Every operand behind the three mappings, off the player's own disks."""
    ovr = _dos_engine(title)
    assert effectcrosswalk.confirm_later_ability_values(
        title, _overlay(title, "ECL65"), ovr) == (
        "Strength bonus in the top nibble", "Friends bonus in the top nibble",
        "Enlarge level in the low nibble", "Mirror Image count alone",
        "The two ports' Enlarge tables agree")
    site = effectcrosswalk.ABILITIES[title]
    # DOS's Strength node carries 100 plus the steps, so the bonus comes back
    # as `data - 100` and the C64 magnitude one less than that in the nibble.
    assert ovr[site.dos_strength_add:site.dos_strength_add + 3] == \
        bytes.fromhex("056400")                       # add ax, 0x64
    assert effects.later_ability_magnitude(104 - 100, 6) == 0xB6


@pytest.mark.parametrize("bonus, level, magnitude", [
    (1, 0, 0x80), (1, 15, 0x8F), (4, 6, 0xB6), (8, 1, 0xF1), (8, 15, 0xFF)])
def test_the_packed_magnitude_is_the_byte_the_cast_writes(bonus, level, magnitude):
    assert effects.later_ability_magnitude(bonus, level) == magnitude
    assert effects.later_ability_bonus(magnitude) == bonus


@pytest.mark.parametrize("bonus, level", [(0, 1), (9, 1), (-1, 1), (1, 16)])
def test_a_magnitude_outside_the_nibbles_is_refused(bonus, level):
    with pytest.raises(ValueError):
        effects.later_ability_magnitude(bonus, level)


# --- S8: what the destination does with a slot a writer staged ---------------


def test_pool_expires_each_slot_on_its_own_for_that_slots_owner():
    """The other half of "the cast refuses a second strength node": the sweep
    and the handler read one slot at a time, so the arrays hold as many
    strength restores as a writer stages, each with its own timer.
    """
    camp = _overlay("pool-of-radiance", "CAMP")
    spells = _overlay("pool-of-radiance", "SPELLE04")
    ecl = _overlay("pool-of-radiance", "ECL65")
    assert effectcrosswalk.confirm_pool_expiry(camp, spells, ecl) == (
        "One expiry call per slot", "The slot's own owner and magnitude",
        "Ids 38 and 12 share the restore handler")
    # The sweep runs from the top, so two slots expiring in one camp call
    # restore in slot order and the lower-numbered one writes last.
    assert _operand(camp, 0x0800, 0x1299, 0xA2) == effects.EFFECT_SLOTS - 1
    assert _operand(camp, 0x0800, 0x12BB, 0x10) == 0xDE       # BPL, back up
    # The handler takes the magnitude of the slot that expired, and the owner
    # of that same slot chooses the character it restores.
    assert _operand(camp, 0x0800, 0x132A, 0xBD) == 0x4B80
    assert _operand(camp, 0x0800, 0x1332, 0xBD) == 0x4940
    assert _operand(camp, 0x0800, 0x0FC8, 0x8D) == 0x6DB4


def test_pools_expiry_table_sends_both_strength_ids_to_one_restore():
    """Ids 38 and 12 share `$AD0B`, so a converted pair can use both without
    the allocator's search ever seeing two rows of one id.
    """
    ecl = _overlay("pool-of-radiance", "ECL65")
    handlers = effectcrosswalk.pool_expiry_handlers(ecl)
    assert len(handlers) == effectcrosswalk.POOL_EXPIRY_ENTRIES == 24
    assert handlers[38] == handlers[12] == 0xAD0B
    assert handlers[14] == 0xAD27                    # charisma, its own handler
    # Neither Prayer id is in it: an effect with nothing to put back expires
    # with no handler call at all.
    assert 35 not in handlers and 49 not in handlers


def _saved_games():
    """Every `SAVEDGAME0` image on the registered C64 disks of all three
    titles, as `(title, disk, payload)`."""
    out = []
    for title in sorted(effectcrosswalk.SITES):
        game = c64_port.by_key(title)
        for image in coldread.disks(game, _disks(title)):
            for entry in image.directory():
                if not entry.name.startswith(b"SAVEDGAME0"):
                    continue
                out.append((title, image, image.read_file(entry)[2:]))
    return out


def test_no_saved_game_on_these_disks_corroborates_the_allocation_order():
    """A negative result, and the reason the slot rule rests on the code: not
    one save carries a nonzero effect id in any of its 64 slots.
    """
    saves = _saved_games()
    if not saves:
        pytest.skip("Needs the player's C64 disks")
    nonzero = [(title, slot) for title, _image, payload in saves
               for slot in range(effects.EFFECT_SLOTS)
               if payload[effects.EFFECT_ID_OFFSET + slot]]
    assert nonzero == []
    assert len(saves) >= 1


# --- the neutral running effect -----------------------------------------------

_NULL = bytes(4)


def test_a_nine_byte_record_reads_as_id_minutes_data_and_flag():
    record = bytes((1, 2, 0, 1, 0)) + _NULL
    assert effects.RunningEffect.from_record(record) == \
        effects.RunningEffect(1, 2, 1, 0)
    assert effects.RunningEffect(1, 2, 1, 0).to_record() == record


def test_the_two_minute_bytes_are_little_endian():
    found = effects.RunningEffect.from_record(bytes((1, 0x02, 0x01, 1, 0)) + _NULL)
    assert found.minutes == 0x0102
    assert found.to_record() == bytes((1, 0x02, 0x01, 1, 0)) + _NULL


def test_the_longest_time_left_is_0xffff_and_round_trips():
    record = bytes((38, 0xFF, 0xFF, 0xE2, 1)) + _NULL
    found = effects.RunningEffect.from_record(record)
    assert (found.id, found.minutes, found.data, found.flag) == \
        (38, 65535, 0xE2, 1)
    assert found.to_record() == record


def test_a_record_at_zero_minutes_is_refused():
    with pytest.raises(ValueError, match="never expires"):
        effects.RunningEffect.from_record(bytes((1, 0, 0, 1, 0)) + _NULL)
    with pytest.raises(ValueError, match="never expires"):
        effects.RunningEffect(1, 0, 1, 0)


def test_a_record_that_is_not_nine_bytes_is_refused():
    with pytest.raises(ValueError, match="9 bytes, got 8"):
        effects.RunningEffect.from_record(bytes((1, 2, 0, 1, 0, 0, 0, 0)))
    with pytest.raises(ValueError, match="9 bytes, got 10"):
        effects.RunningEffect.from_record(bytes((1, 2, 0, 1, 0)) + _NULL + b"\0")


def test_a_running_effect_refuses_a_value_that_does_not_fit_its_bytes():
    for args in ((256, 2, 1, 0), (1, 2, 256, 0), (1, 2, 1, 256),
                 (1, 65536, 1, 0), (-1, 2, 1, 0)):
        with pytest.raises(ValueError):
            effects.RunningEffect(*args)


# --- the DOS -> C64 rule for a running effect --------------------------------


def test_a_pool_caster_level_bless_becomes_id_and_level():
    node = effects.RunningEffect(1, 2, 1, 0)
    assert effects.c64_row("pool-of-radiance", node) == (1, 1)


@pytest.mark.parametrize("title, node", [
    ("pool-of-radiance", effects.RunningEffect(1, 2, 1, 1)),
    ("pool-of-radiance", effects.RunningEffect(1, 2, 0, 0)),
    ("pool-of-radiance", effects.RunningEffect(1, 2, 0x80, 0)),
    ("pool-of-radiance", effects.RunningEffect(13, 2, 1, 0)),
    ("pool-of-radiance", effects.RunningEffect(49, 2, 1, 0)),
    ("curse-of-the-azure-bonds", effects.RunningEffect(25, 2, 0xFF, 0)),
    ("curse-of-the-azure-bonds", effects.RunningEffect(49, 2, 1, 0)),
    ("curse-of-the-azure-bonds", effects.RunningEffect(1, 2, 1, 1)),
    ("curse-of-the-azure-bonds", effects.RunningEffect(1, 2, 0x80, 0)),
    ("curse-of-the-azure-bonds", effects.RunningEffect(57, 2, 1, 0)),
    ("secret-of-the-silver-blades", effects.RunningEffect(25, 2, 0xFF, 0)),
    ("secret-of-the-silver-blades", effects.RunningEffect(49, 2, 1, 0)),
    ("secret-of-the-silver-blades", effects.RunningEffect(1, 2, 0, 0)),
])
def test_a_node_the_table_has_no_rule_for_is_unconverted(title, node):
    got = effects.c64_row(title, node)
    assert isinstance(got, effects.Unconverted)
    assert got.reason


@pytest.mark.parametrize("title, eid", [
    ("curse-of-the-azure-bonds", 1), ("curse-of-the-azure-bonds", 17),
    ("curse-of-the-azure-bonds", 45), ("secret-of-the-silver-blades", 17),
    ("secret-of-the-silver-blades", 45), ("secret-of-the-silver-blades", 57),
])
def test_a_later_title_caster_level_effect_becomes_id_and_level(title, eid):
    node = effects.RunningEffect(eid, 47, 10, 0)
    assert effects.c64_row(title, node) == (eid, 10)


def test_silver_blades_has_one_caster_level_id_curse_lacks():
    curse = effects.LATER_CASTER_LEVEL_IDS["curse-of-the-azure-bonds"]
    blades = effects.LATER_CASTER_LEVEL_IDS["secret-of-the-silver-blades"]
    assert blades - curse == {57} and curse < blades


_ALL = ("pool-of-radiance", "curse-of-the-azure-bonds",
        "secret-of-the-silver-blades")
_LATER = _ALL[1:]
_BLADES = "secret-of-the-silver-blades"


@pytest.mark.parametrize("title", _ALL)
@pytest.mark.parametrize("eid", [21, 29, 36])
def test_silence_enfeeblement_and_bestow_curse_become_id_and_level(title, eid):
    for level in (1, 9, 0x7F):
        assert effects.c64_row(title, effects.RunningEffect(eid, 47, level, 0)) \
            == (eid, level)
    for node in (effects.RunningEffect(eid, 47, 5, 1),
                 effects.RunningEffect(eid, 47, 0, 0),
                 effects.RunningEffect(eid, 47, 0x80, 0)):
        assert isinstance(effects.c64_row(title, node), effects.Unconverted)


@pytest.mark.parametrize("title", _LATER)
def test_a_later_title_invisible_node_becomes_id_and_level(title):
    assert effects.c64_row(title, effects.RunningEffect(25, 1, 0x0C, 0)) \
        == (25, 0x0C)
    assert effects.c64_row(title, effects.RunningEffect(25, 1, 0x7F, 0)) \
        == (25, 0x7F)
    for node in (effects.RunningEffect(25, 1, 0xFF, 0),
                 effects.RunningEffect(25, 1, 0, 0),
                 effects.RunningEffect(25, 1, 0x0C, 1)):
        assert isinstance(effects.c64_row(title, node), effects.Unconverted)


@pytest.mark.parametrize("title", _ALL)
@pytest.mark.parametrize("data", [0x01, 0x0C, 0x10, 0x1C, 0x1F])
def test_a_haste_node_is_copied_to_the_magnitude_and_back(title, data):
    assert effects.c64_row(title, effects.RunningEffect(39, 6, data, 0)) \
        == (39, data)
    row = effects.Effect(63, 39, 0, 0x06, data)
    assert effects.dos_record(title, row, 0) == effects.RunningEffect(
        39, 6, data, 0)


@pytest.mark.parametrize("title", _ALL)
def test_a_haste_byte_no_engine_writes_stays_unconverted(title):
    for node in (effects.RunningEffect(39, 6, 0x20, 0),
                 effects.RunningEffect(39, 6, 0x0C, 1),
                 effects.RunningEffect(39, 6, 0x80, 0),
                 effects.RunningEffect(39, 6, 0, 0)):
        assert isinstance(effects.c64_row(title, node), effects.Unconverted)
    for magnitude in (0, 0x20, 0x90):
        row = effects.Effect(63, 39, 0, 0x06, magnitude)
        assert isinstance(effects.dos_record(title, row, 0),
                          effects.Unconverted)


def test_silver_blades_id_113_is_the_dos_node_and_the_c64s_own_magnitude():
    node = effects.RunningEffect(113, 10, 0x79, 1)
    assert effects.c64_row(_BLADES, node) == (113, 0xBC)
    row = effects.Effect(63, 113, 0, 0x0A, 0xBC)
    assert effects.dos_record(_BLADES, row, 0) == node


@pytest.mark.parametrize("node", [effects.RunningEffect(113, 10, 0x79, 0),
                                  effects.RunningEffect(113, 10, 0x7B, 1)])
def test_an_id_113_node_other_than_spell_59s_stays_unconverted(node):
    assert isinstance(effects.c64_row(_BLADES, node), effects.Unconverted)


@pytest.mark.parametrize("magnitude", [0xDB, 0x80, 0x00])
def test_an_id_113_magnitude_other_than_the_c64s_own_stays_unconverted(
        magnitude):
    """A magnitude with upper nibble 5 (strength 23) is a C64 magnitude that is not converted."""
    row = effects.Effect(63, 113, 0, 0x0A, magnitude)
    assert isinstance(effects.dos_record(_BLADES, row, 0), effects.Unconverted)


@pytest.mark.parametrize("title", ["pool-of-radiance",
                                   "curse-of-the-azure-bonds"])
def test_id_113_is_a_silver_blades_id_only(title):
    assert isinstance(effects.c64_row(title, effects.RunningEffect(
        113, 10, 0x79, 1)), effects.Unconverted)


@pytest.mark.parametrize("title", _ALL)
def test_id_13_stays_refused_and_the_reason_says_no_dos_engine_writes_it(title):
    """DOS Reduce removes id 12 and writes no id-13 node, in any title, so no
    save a game wrote reaches this refusal (`docs/226`)."""
    got = effects.c64_row(title, effects.RunningEffect(13, 2, 1, 0))
    assert isinstance(got, effects.Unconverted)
    assert got.reason == "no DOS engine writes a running id-13 node"


# --- dos_record, the inverse of c64_row --------------------------------------


def test_dos_record_reads_a_pool_bless_row_and_ages_it_by_the_clock():
    row = effects.Effect(63, 1, 2, 0x02, 0x01)
    assert effects.dos_record("pool-of-radiance", row, 0) \
        == effects.RunningEffect(1, 2, 1, 0)
    aged = effects.Effect(63, 1, 2, 0x41, 0x01)
    assert effects.dos_record("pool-of-radiance", aged, 6).minutes == 4


def test_dos_record_converts_the_later_titles_own_ids():
    curse = "curse-of-the-azure-bonds"
    assert effects.dos_record(curse, effects.Effect(63, 45, 0, 0x2F, 0x0A),
                              0) == effects.RunningEffect(45, 47, 0x0A, 0)
    row57 = effects.Effect(63, 57, 0, 0x02, 0x01)
    assert isinstance(effects.dos_record("secret-of-the-silver-blades", row57,
                                         0), effects.RunningEffect)
    assert isinstance(effects.dos_record(curse, row57, 0),
                      effects.Unconverted)
    assert isinstance(effects.dos_record(
        "pool-of-radiance", effects.Effect(63, 63, 0, 0x02, 0x01), 0),
        effects.Unconverted)


@pytest.mark.parametrize("eid,magnitude", [(13, 1), (49, 1), (1, 0),
                                           (1, 0x80)])
def test_dos_record_refuses_what_has_no_rule(eid, magnitude):
    row = effects.Effect(63, eid, 0, 0x02, magnitude)
    assert isinstance(effects.dos_record("pool-of-radiance", row, 0),
                      effects.Unconverted)


@pytest.mark.parametrize("byte", [0xEE, 0xFF])
def test_dos_record_clamps_a_day_count_to_sixteen_bits(byte):
    row = effects.Effect(63, 1, 0, byte, 1)
    assert effects.dos_record("pool-of-radiance", row, 0).minutes == 0xFFFF


def test_dos_record_refuses_a_never_expiring_row_by_raising():
    with pytest.raises(ValueError):
        effects.dos_record("pool-of-radiance", effects.Effect(63, 1, 0, 0, 1),
                           0)


@pytest.mark.parametrize("title", ["pool-of-radiance",
                                   "curse-of-the-azure-bonds",
                                   "secret-of-the-silver-blades"])
def test_dos_record_inverts_c64_row(title):
    for eid in effects._caster_level_ids(title):
        for data in (1, 0x7F):
            for minutes in (1, 2, 47, 63):
                for clock in (0, 725):
                    node = effects.RunningEffect(eid, minutes, data, 0)
                    byte = effects.closest_duration(minutes, clock)
                    _, magnitude = effects.c64_row(title, node)
                    row = effects.Effect(63, eid, 0, byte, magnitude)
                    assert effects.dos_record(title, row, clock) == node


# --- party-wide Detect Magic rows ---------------------------------------------

_TITLES = ("pool-of-radiance", "curse-of-the-azure-bonds",
           "secret-of-the-silver-blades")


@pytest.mark.parametrize("title", _TITLES)
@pytest.mark.parametrize("owner", [0xFF, 0x80])
def test_party_row_record_converts_detect_magic(title, owner):
    row = effects.Effect(63, 5, owner, 0x0A, 0x03)
    assert effects.party_row_record(title, row, 0) == \
        effects.RunningEffect(5, 10, 3, 0)


def test_party_row_record_counts_the_clock():
    row = effects.Effect(63, 5, 0xFF, 0x41, 0x03)
    got = effects.party_row_record("pool-of-radiance", row, 6)
    assert got.minutes == 4


@pytest.mark.parametrize("magnitude", [0x00, 0x85, 0xFF])
def test_party_row_record_copies_any_magnitude(magnitude):
    row = effects.Effect(63, 5, 0xFF, 0x0A, magnitude)
    got = effects.party_row_record("pool-of-radiance", row, 0)
    assert got.data == magnitude


@pytest.mark.parametrize("title, row", [
    ("pool-of-radiance", effects.Effect(63, 1, 0xFF, 0x0A, 0x01)),
    ("curse-of-the-azure-bonds", effects.Effect(63, 35, 0xFF, 0x0A, 0x03)),
])
def test_party_row_record_leaves_the_rest_unconverted(title, row):
    assert isinstance(effects.party_row_record(title, row, 0),
                      effects.Unconverted)


def test_a_never_expiring_prayer_row_still_becomes_the_longest_node():
    row = effects.Effect(63, 49, 0xFF, 0x00, 0x03)
    assert effects.party_row_record("pool-of-radiance", row, 0) == \
        effects.RunningEffect(49, effects.DOS_MINUTES_MAX, 0x13, 0)


@pytest.mark.parametrize("title", _TITLES)
def test_a_never_expiring_detect_magic_row_is_a_granted_record(title):
    row = effects.Effect(63, 5, 0xFF, 0x00, 0x03)
    assert effects.party_row_granted(title, row) == \
        bytes((5, 0, 0, 3, 0)) + bytes(4)
    with pytest.raises(ValueError):
        effects.party_row_record(title, row, 0)
    assert effects.party_row_granted(
        title, effects.Effect(63, 5, 0xFF, 0x0A, 0x03)) is None
    assert effects.party_row_granted(
        title, effects.Effect(63, 49, 0xFF, 0x00, 0x03)) is None


@pytest.mark.parametrize("title", _TITLES)
@pytest.mark.parametrize("flag", [0, 1, 0xFF])
def test_c64_party_row_ignores_detect_magics_flag_byte(title, flag):
    assert effects.c64_party_row(
        title, effects.RunningEffect(5, 10, 3, flag)) == (5, 3)


@pytest.mark.parametrize("first, second, kept", [(0x04, 0x00, 2),
                                                 (0x00, 0x04, 1)])
def test_write_party_row_lets_a_never_expiring_row_win_in_either_order(
        first, second, kept):
    p = bytearray(0x1C00)
    assert effects.write_party_row(p, 5, first, 1, 0)
    assert effects.write_party_row(p, 5, second, 2, 0)
    rows = _party_slots(p)
    assert rows[63] == (5, 0xFF, 0x00, kept)
    assert rows[62] == (0, 0, 0, 0)


def test_c64_party_row_keeps_the_data_byte():
    node = effects.RunningEffect(5, 10, 0x85, 0)
    assert effects.c64_party_row("pool-of-radiance", node) == (5, 0x85)
    assert isinstance(effects.c64_party_row(
        "pool-of-radiance", effects.RunningEffect(35, 10, 3, 1)),
        effects.Unconverted)
    assert isinstance(effects.c64_party_row(
        "curse-of-the-azure-bonds", effects.RunningEffect(35, 10, 3, 0)),
        effects.Unconverted)


def _party_slots(payload):
    return {s: (payload[effects.EFFECT_ID_OFFSET + s],
                payload[effects.EFFECT_OWNER_OFFSET + s],
                payload[effects.EFFECT_DURATION_OFFSET + s],
                payload[effects.EFFECT_MAGNITUDE_OFFSET + s])
            for s in range(effects.EFFECT_SLOTS)}


@pytest.mark.parametrize("first, second, kept", [(0x04, 0x0A, 2),
                                                 (0x0A, 0x04, 1)])
def test_write_party_row_keeps_the_longer_row(first, second, kept):
    p = bytearray(0x1C00)
    assert effects.write_party_row(p, 5, first, 1, 0)
    assert effects.write_party_row(p, 5, second, 2, 0)
    rows = _party_slots(p)
    assert rows[63] == (5, 0xFF, 0x0A, kept)
    assert rows[62] == (0, 0, 0, 0)


# --- party-wide Prayer rows -----------------------------------------------------

_POOL = "pool-of-radiance"
_LATER = ("curse-of-the-azure-bonds", "secret-of-the-silver-blades")


def test_prayer_dos_data_inverts_the_side_bit_for_pool_only():
    assert effects.prayer_dos_data(_POOL, 0x43) == 0x03
    assert effects.prayer_dos_data(_POOL, 0x03) == 0x13
    for title in _LATER:
        assert effects.prayer_dos_data(title, 0x03) == 0x03
        assert effects.prayer_dos_data(title, 0x43) == 0x13


def test_prayer_c64_magnitude_inverts_the_side_bit_for_pool_only():
    assert effects.prayer_c64_magnitude(_POOL, 0x03) == 0x43
    assert effects.prayer_c64_magnitude(_POOL, 0x13) == 0x03
    for title in _LATER:
        assert effects.prayer_c64_magnitude(title, 0x03) == 0x03
        assert effects.prayer_c64_magnitude(title, 0x13) == 0x43


@pytest.mark.parametrize("title", _TITLES)
def test_prayer_data_round_trips_and_the_side_matches_the_crosswalk(title):
    for d in range(256):
        m = effects.prayer_c64_magnitude(title, d)
        assert effects.prayer_dos_data(title, m) == d & 0x1F
        assert m & 0x40 == effectcrosswalk.prayer_allegiance(d, title=title)


def test_party_row_record_converts_prayer():
    assert effects.party_row_record(
        _POOL, effects.Effect(63, 35, 0xFF, 0x0A, 0x03), 0) == \
        effects.RunningEffect(35, 10, 3, 0)
    assert effects.party_row_record(
        _POOL, effects.Effect(63, 49, 0xFF, 0x0A, 0x43), 0) == \
        effects.RunningEffect(49, 10, 0x03, 0)
    assert effects.party_row_record(
        _POOL, effects.Effect(63, 49, 0xFF, 0x0A, 0x03), 0).data == 0x13
    for title in _LATER:
        assert effects.party_row_record(
            title, effects.Effect(63, 49, 0xFF, 0x0A, 0x03), 0) == \
            effects.RunningEffect(49, 10, 0x03, 0)


def test_c64_party_row_converts_prayer():
    assert effects.c64_party_row(
        _POOL, effects.RunningEffect(49, 10, 0x03, 0)) == (49, 0x43)
    assert effects.c64_party_row(
        _LATER[0], effects.RunningEffect(49, 10, 0x03, 0)) == (49, 0x03)
    assert effects.c64_party_row(
        _POOL, effects.RunningEffect(35, 10, 3, 0)) == (35, 3)
    assert isinstance(effects.c64_party_row(
        _POOL, effects.RunningEffect(49, 10, 3, 1)), effects.Unconverted)


# --- Enlarge, Friends, Mirror Image and Strength ------------------------------

_P = "pool-of-radiance"
_C = "curse-of-the-azure-bonds"
_S = "secret-of-the-silver-blades"
_RE = effects.RunningEffect
_VALUE_ROWS = [
    (_P, _RE(12, 10, 0x63, 1), (12, 0xE2)),
    (_P, _RE(38, 10, 0x73, 1), (38, 0xF3)),
    (_P, _RE(38, 10, 0x65, 1), (38, 0xE4)),
    (_P, _RE(38, 10, 0x66, 1), (38, 0xE6)),
    (_P, _RE(38, 10, 0x73, 0), (38, 0x73)),
    (_P, _RE(14, 10, 0x0C, 1), (14, 0x8C)),
    (_P, _RE(14, 10, 0x0C, 0), (14, 0x0C)),
    (_P, _RE(28, 10, 0x03, 0), (28, 0x03)),
    (_C, _RE(38, 10, 0x68, 1), (38, 0xB8)),
    (_C, _RE(38, 10, 0x66, 1), (38, 0x96)),
    (_S, _RE(14, 10, 0x05, 1), (14, 0xC5)),
    (_S, _RE(14, 10, 0x05, 0), (14, 0xC5)),
    (_C, _RE(12, 10, 0x34, 1), (12, 0x83)),
    (_S, _RE(12, 10, 0x7A, 0), (12, 0x8A)),
    (_C, _RE(12, 10, 0x01, 1), (12, 0x81)),
    (_C, _RE(28, 10, 0x4F, 0), (28, 4)),
    (_C, _RE(28, 10, 0x1A, 0), (28, 1)),
    (_C, _RE(28, 10, 0x0F, 0), (28, 0)),
]


@pytest.mark.parametrize("title, node, want", _VALUE_ROWS)
def test_c64_row_converts_enlarge_friends_mirror_image_and_strength(
        title, node, want):
    assert effects.c64_row(title, node) == want


@pytest.mark.parametrize("title, node, kwargs", [
    (_P, _RE(28, 10, 3, 1), {}),
    (_P, _RE(38, 10, 0x73, 1), {"strength_nodes": 2}),
    (_P, _RE(12, 10, 0xE3, 1), {}),
    (_C, _RE(38, 10, 0x65, 1), {}),
    (_C, _RE(12, 10, 0x70, 1), {}),
    (_C, _RE(28, 10, 0x50, 0), {}),
    (_S, _RE(28, 10, 0xFF, 0), {}),
])
def test_c64_row_leaves_only_states_no_engine_writes_or_waiting_on_a_run(
        title, node, kwargs):
    got = effects.c64_row(title, node, **kwargs)
    assert isinstance(got, effects.Unconverted) and got.reason


_VALUE_NODES = [
    (_P, 12, 0xE2, (0x63, 1)),
    (_P, 38, 0xF3, (0x73, 1)),
    (_P, 38, 0xE4, (0x65, 1)),
    (_P, 38, 0xE5, (0x65, 1)),
    (_P, 38, 0x73, (0x73, 0)),
    (_P, 14, 0x8C, (0x0C, 1)),
    (_P, 28, 0x03, (0x03, 0)),
    (_C, 38, 0xB8, (0x68, 1)),
    (_S, 14, 0xC5, (0x05, 1)),
    (_C, 12, 0x83, (0x34, 1)),
    (_S, 12, 0x83, (0x34, 0)),
    (_S, 12, 0x8C, (0x7A, 0)),
    (_C, 28, 0x04, (0x44, 0)),
    (_C, 28, 0x00, (0x00, 0)),
]


@pytest.mark.parametrize("title, eid, m, want", _VALUE_NODES)
def test_dos_record_converts_enlarge_friends_mirror_image_and_strength(
        title, eid, m, want):
    got = effects.dos_record(title, effects.Effect(63, eid, 2, 0x0A, m), 0)
    assert got == _RE(eid, 10, *want)


@pytest.mark.parametrize("title, eid, m", [
    (_P, 28, 0x83), (_C, 38, 0x85), (_C, 38, 0x38), (_C, 12, 0x80),
    (_C, 28, 0x05), (_S, 28, 0x0F),
])
def test_dos_record_leaves_only_what_waits_on_a_read_or_a_run(title, eid, m):
    got = effects.dos_record(title, effects.Effect(63, eid, 2, 0x0A, m), 0)
    assert isinstance(got, effects.Unconverted) and got.reason


def _round_trip(title, node):
    for clock in (0, 725):
        for minutes in (1, 47, 63):
            n = _RE(node.id, minutes, node.data, node.flag)
            byte = effects.closest_duration(minutes, clock)
            got = effects.c64_row(title, n)
            assert not isinstance(got, effects.Unconverted), (node, got)
            row = effects.Effect(63, n.id, 2, byte, got[1])
            assert effects.dos_record(title, row, clock) == n


def test_pool_enlarge_strength_and_friends_survive_every_data_byte():
    for eid in (12, 38, 14):
        for data in range(1, 0x80):
            for flag in (0, 1):
                # 101 is DOS's own collision (a strength of 1 and 18/100 both
                # encode to it), and the row holds 100 for both.
                _round_trip(_P, _RE(eid, 1, data, flag))
    for data in range(0, 0x80):
        _round_trip(_P, _RE(28, 1, data, 0))


def test_later_strength_and_friends_survive_every_bonus():
    for title in (_C, _S):
        for data in range(102, 109):
            _round_trip(title, _RE(38, 1, data, 1))
        for data in range(1, 9):
            _round_trip(title, _RE(14, 1, data, 1))


@pytest.mark.parametrize("title", [_C, _S])
def test_later_enlarge_survives_each_of_its_ten_scores(title):
    flag = effects.LATER_CAST_FLAGS[title][12]
    for score in effects.ENLARGE_STRENGTHS:
        _round_trip(title, _RE(12, 1, effects.later_node_data(*score), flag))


@pytest.mark.parametrize("title", [_C, _S])
def test_a_later_mirror_image_count_survives_and_its_level_becomes_the_count(
        title):
    for count in range(5):
        _round_trip(title, _RE(28, 1, count << 4 | count, 0))
    # The C64 row holds no caster level, so the level nibble comes back as the
    # count.
    for data, back in ((0x4F, 0x44), (0x0F, 0x00)):
        _, m = effects.c64_row(title, _RE(28, 5, data, 0))
        row = effects.Effect(63, 28, 2, effects.closest_duration(5, 0), m)
        assert effects.dos_record(title, row, 0).data == back


def test_the_two_node_score_helpers_live_in_goldbox_and_the_crosswalk_uses_them():
    assert effectcrosswalk.later_node_score is effects.later_node_score
    assert effectcrosswalk.later_node_data is effects.later_node_data
    assert effects.later_node_score(0x7B) == (23, 0)
    assert effects.later_node_data(23, 0) == 0x7B


def test_silver_blades_enlarge_23_converts_to_the_c64s_enlarge_at_22():
    node = _RE(12, 10, 0x7B, 0)
    assert effects.c64_row(_S, node) == effects.c64_row(
        _S, _RE(12, 10, effects.later_node_data(22, 0), 0)) == (12, 0x8A)
    assert effects.enlarge_capped(_S, node)
    assert not effects.enlarge_capped(_S, _RE(12, 10, 0x7A, 0))
    # The way back is the DOS node for 22: the fighter returns with 22.
    back = effects.dos_record(_S, effects.Effect(63, 12, 0, 0x0A, 0x8A), 0)
    assert (back.data, back.flag) == (effects.later_node_data(22, 0), 0)


def test_curse_never_writes_enlarge_23_and_refuses_it():
    assert isinstance(effects.c64_row(_C, _RE(12, 10, 0x7B, 1)),
                      effects.Unconverted)
    assert not effects.enlarge_capped(_C, _RE(12, 10, 0x7B, 1))


@pytest.mark.parametrize("title", [_C, _S])
def test_a_mirror_image_count_above_4_is_refused_in_both_directions(title):
    assert effects.c64_row(title, _RE(28, 10, 0x4F, 0)) == (28, 4)
    for count in (5, 15):
        assert isinstance(effects.c64_row(title, _RE(28, 10, count << 4, 0)),
                          effects.Unconverted)


# --- spells DOS writes at duration 0 ------------------------------------------

_P, _C, _S = ("pool-of-radiance", "curse-of-the-azure-bonds",
              "secret-of-the-silver-blades")


def _node(hexstr):
    return bytes.fromhex(hexstr)


@pytest.mark.parametrize("title,node,row", [
    (_C, "19 00 00 05 00", (25, 0x05)),
    (_P, "19 00 00 05 00", (25, 0x05)),
    (_S, "21 00 00 07 00", (33, 0x07)),
    (_P, "22 00 00 05 01", (34, 0x85)),
    (_C, "22 00 00 0A 01", (34, 0x8A)),
    (_P, "47 00 00 0C 00", (71, 0x0C)),
    (_C, "6D 00 00 0C 00", (109, 0x0C)),
    (_S, "33 00 00 03 00", (51, 0x03)),
])
def test_a_spell_written_at_duration_zero_is_a_row(title, node, row):
    assert effects.never_expiring_spell_row(title, _node(node)) == row


@pytest.mark.parametrize("title,node", [
    (_C, "19 00 00 FF 00"), (_C, "19 00 00 FF 01"), (_C, "19 00 00 05 01"),
    (_P, "22 00 00 05 00"), (_C, "19 00 00 00 00"), (_C, "19 01 00 05 00"),
    (_S, "22 00 00 05 01"), (_C, "44 00 00 05 00"), (_P, "49 00 00 05 00"),
    (_P, "3D 00 00 0C 00"),
])
def test_other_duration_zero_forms_stay_in_a_trait_slot(title, node):
    assert effects.never_expiring_spell_row(title, _node(node)) is None


def test_a_spell_row_reads_back_as_the_record_it_came_from():
    assert effects.never_expiring_spell_record(
        _C, effects.Effect(63, 25, 2, 0x00, 0x05)) == \
        _node("19 00 00 05 00") + effects._RUNNING_EFFECT_NEXT
    assert effects.never_expiring_spell_record(
        _P, effects.Effect(63, 34, 2, 0x00, 0x85)) == \
        _node("22 00 00 05 01") + effects._RUNNING_EFFECT_NEXT
    for title, row in [
            (_C, effects.Effect(63, 25, 2, 0x0A, 0x05)),
            (_C, effects.Effect(63, 25, 2, 0x00, 0x85)),
            (_P, effects.Effect(63, 34, 2, 0x00, 0x05)),
            (_C, effects.Effect(63, 25, 2, 0x00, 0x00)),
            (_C, effects.Effect(63, 45, 2, 0x00, 0x01))]:
        assert effects.never_expiring_spell_record(title, row) is None


@pytest.mark.parametrize("title", sorted(effects.NEVER_EXPIRING_SPELL_IDS))
def test_every_spell_id_round_trips_at_every_level(title):
    for spell in effects.NEVER_EXPIRING_SPELL_IDS[title]:
        flag = effects.NEVER_EXPIRING_SPELL_FLAGS.get(spell, 0)
        for level in range(1, 0x80):
            node = bytes((spell, 0, 0, level, flag))
            id_, magnitude = effects.never_expiring_spell_row(title, node)
            back = effects.never_expiring_spell_record(
                title, effects.Effect(63, id_, 2, 0, magnitude))
            assert back == node + effects._RUNNING_EFFECT_NEXT
