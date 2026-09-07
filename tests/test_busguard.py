"""The `$DD00` bus guard, with no hardware anywhere near it.

For `#375 (Wish has to work around the Ultimate freezing the C64 mid-load,
which hangs the game while the automapper follows along)`. Every value of
`$DD00` used here was read off Donald's own unit and is cited in
`automap/busguard.py`; the fake device is `MemoryTarget` with the one
attribute the real backend sets.

What these prove is narrow and said so: that the guard reads one byte first,
that a busy bus stops the tick there, and that no rest state can stop it for
ever. **No test here can show the hang is prevented** -- the hazard is of
order one read in a thousand, and a run that does not hang proves nothing.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gamedata import synthetic_arena  # noqa: E402

from automap import busguard  # noqa: E402
from automap.busguard import BusGuard, bus_released  # noqa: E402
from automap.live import memory_blocks  # noqa: E402
from automap.target import MemoryTarget, NotConnected  # noqa: E402
from goldbox import games  # noqa: E402
from tests.test_automap import captured, make_window  # noqa: E402


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# `$DD00` as this machine reads it (hex), with where each came from.
RELEASED = 0xC7      # KERNAL rest after a load, bank 0; `$C4` is the bank-3 form
FASTLOADER_REST = 0x13   # `$10` on 2026-09-04, idle in the Slums; bank 0 form
LOAD_STATES = (0x87, 0x47, 0x27, 0x07, 0x67, 0x4F)   # one 40 s load, 1792 samples
PROMPT = 0x97        # BASIC `READY.`, disk mounted, no traffic yet


def guarded_machine(dd00: int, **more) -> MemoryTarget:
    """One tick of memory, as `tests/test_issue286a2.py` lays it out, on a
    target that says its reads stop the processor."""
    save0, save1 = captured()
    screen = bytearray(b" " * 1024)
    status = "E 16:48  5,2".ljust(40)
    screen[560:600] = bytes(
        ord(c) - ord("A") + 1 if "A" <= c <= "Z" else ord(c) for c in status)
    machine = MemoryTarget({
        0xD011: b"\x1b", 0xD018: b"\x15", 0xDD00: bytes([dd00]),
        0x0400: bytes(screen), 0x4900: save0, 0x8300: save1,
        0x6E11: b"\x00", **more})
    machine.halts_on_read = True
    return machine


class FakeClock:
    """A clock a test moves by hand, in seconds, so a forty-second load does
    not cost the suite forty seconds. `BusGuard(clock=...)` takes one of
    these in place of `time.monotonic`."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# -- the byte -----------------------------------------------------------------

@pytest.mark.parametrize("value", [0xC4, 0xC7, 0xC0, 0xC3])
def test_nothing_driven_and_both_lines_released_is_idle(value):
    assert bus_released(value)


@pytest.mark.parametrize("value", LOAD_STATES + (FASTLOADER_REST, PROMPT,
                                                 0x4C, 0x24, 0x84, 0x44, 0x04))
def test_every_other_measured_state_is_not_trusted_on_one_reading(value):
    assert not bus_released(value)


def test_the_vic_bank_and_the_rs232_bit_say_nothing_about_the_bus():
    for low in range(8):
        assert bus_released(0xC0 | low)
        assert not bus_released(0x80 | low)


# -- the guard, on a table --------------------------------------------------

def test_a_bus_cycling_through_its_load_states_never_settles():
    guard = BusGuard()
    for i in range(60):
        assert not guard.allow(LOAD_STATES[i % len(LOAD_STATES)])
    assert (guard.skipped, guard.passed, guard.settled) == (60, 0, 0)


def test_a_busy_looking_value_that_holds_still_is_a_rest_state():
    """`$10` for ten minutes with the party idle: the fastloader's rest. A
    guard that never let it through would never tick again."""
    guard = BusGuard()
    verdicts = [guard.allow(FASTLOADER_REST) for _ in range(5)]
    assert verdicts == [False] * (busguard.SETTLE - 1) + [True] * 3
    assert guard.settled == 3


def test_a_released_reading_resets_the_settle_count():
    guard = BusGuard()
    guard.allow(FASTLOADER_REST)
    guard.allow(FASTLOADER_REST)
    assert guard.allow(RELEASED)
    assert not guard.allow(FASTLOADER_REST)
    assert not guard.allow(FASTLOADER_REST)
    assert guard.allow(FASTLOADER_REST)


def test_a_change_of_busy_state_resets_it_too():
    guard = BusGuard()
    guard.allow(0x87)
    guard.allow(0x87)
    assert not guard.allow(0x47)
    assert not guard.allow(0x47)
    assert guard.allow(0x47)


def test_the_bank_bits_do_not_count_as_a_change():
    """`$4C` and `$4F` are one bus state under two VIC banks."""
    guard = BusGuard()
    guard.allow(0x4C)
    guard.allow(0x4F)
    assert guard.allow(0x4C)


# -- the back-off, on a table -------------------------------------------------

def test_each_busy_verdict_grows_the_wait_before_the_next_read():
    guard = BusGuard()
    assert guard.wait_seconds == 0.0
    guard.allow(LOAD_STATES[0])
    assert guard.wait_seconds == busguard.BACKOFF_START
    guard.allow(LOAD_STATES[1])
    assert guard.wait_seconds == busguard.BACKOFF_START * 2
    guard.allow(LOAD_STATES[2])
    assert guard.wait_seconds == busguard.BACKOFF_CAP


def test_the_wait_stops_growing_at_the_cap_however_long_the_run_goes_on():
    guard = BusGuard()
    for i in range(60):
        guard.allow(LOAD_STATES[i % len(LOAD_STATES)])
    assert guard.wait_seconds == busguard.BACKOFF_CAP


def test_a_released_reading_resets_the_wait_to_zero_at_once():
    guard = BusGuard()
    guard.allow(LOAD_STATES[0])
    guard.allow(LOAD_STATES[1])
    assert guard.wait_seconds > 0
    assert guard.allow(RELEASED)
    assert guard.wait_seconds == 0.0


def test_a_settled_reading_resets_the_wait_to_zero_too():
    """A rest state reached after a busy run that already capped the wait --
    the guard has just let the tick through, so it has no reason left to
    hold its own next look back."""
    guard = BusGuard()
    for i in range(10):
        guard.allow(LOAD_STATES[i % len(LOAD_STATES)])
    assert guard.wait_seconds == busguard.BACKOFF_CAP
    settled = None
    for _ in range(busguard.SETTLE):
        settled = guard.allow(FASTLOADER_REST)
    assert settled
    assert guard.wait_seconds == 0.0


# -- the back-off, honoured by `clear()` --------------------------------------

def test_clear_does_not_read_the_bus_again_before_the_wait_elapses():
    clock = FakeClock()
    guard = BusGuard(clock=clock)
    machine = guarded_machine(LOAD_STATES[0])
    assert guard.clear(machine) is False
    assert machine.reads == [(busguard.CIA2_PORT_A, 1)]
    machine.reads.clear()
    assert guard.clear(machine) is False
    assert machine.reads == [], "held off: the wait has not elapsed yet"
    assert guard.held_off == 1
    clock.advance(busguard.BACKOFF_START)
    assert guard.clear(machine) is False
    assert machine.reads == [(busguard.CIA2_PORT_A, 1)], "the wait elapsed"


def test_a_released_reading_lets_clear_read_again_at_once():
    clock = FakeClock()
    guard = BusGuard(clock=clock)
    machine = guarded_machine(LOAD_STATES[0])
    guard.clear(machine)                       # 1st busy read, wait -> 1 s
    clock.advance(busguard.BACKOFF_START)
    guard.clear(machine)                       # 2nd busy read, wait -> 2 s
    machine.memory[0xDD00] = bytes([RELEASED])
    clock.advance(busguard.BACKOFF_START * 2)
    assert guard.clear(machine) is True
    machine.reads.clear()
    assert guard.clear(machine) is True, "no wait left after a released reading"
    assert machine.reads == [(busguard.CIA2_PORT_A, 1)]


def test_a_forty_second_load_costs_far_fewer_guard_reads_than_before():
    """`#375 (Wish has to work around the Ultimate freezing the C64
    mid-load, which hangs the game while the automapper follows along)` step
    3. Before this change, the fixed 500 ms tick read `$DD00` on every one of
    them for the whole load -- eighty reads over forty seconds. The back-off
    cuts that to twelve on the same load."""
    clock = FakeClock()
    guard = BusGuard(clock=clock)
    machine = guarded_machine(LOAD_STATES[0])
    old_style_reads = 0
    new_reads = 0
    i = 0
    while clock.now < 40.0:
        machine.memory[0xDD00] = bytes([LOAD_STATES[i % len(LOAD_STATES)]])
        i += 1
        old_style_reads += 1        # what the fixed 500 ms tick would have done
        before = len(machine.reads)
        guard.clear(machine)
        new_reads += len(machine.reads) - before
        clock.advance(0.5)
    assert old_style_reads == 80
    assert new_reads == 12
    assert guard.wait_seconds == busguard.BACKOFF_CAP


def test_settling_cold_now_takes_three_seconds_against_a_second_and_a_half():
    """No load beforehand: the guard's own busy streak starts from the first
    reading of the rest state, so the three readings that confirm it land at
    zero, one and three seconds rather than every 500 ms -- three seconds
    end to end, against the `SETTLE` * 500 ms = 1.5 s this cost before."""
    clock = FakeClock()
    guard = BusGuard(clock=clock)
    machine = guarded_machine(FASTLOADER_REST)
    first_read = settled_at = None
    while True:
        before = len(machine.reads)
        guard.clear(machine)
        if len(machine.reads) > before:
            if first_read is None:
                first_read = clock.now
            if guard.settled:
                settled_at = clock.now
                break
        clock.advance(guard.wait_seconds or 0.5)
    assert settled_at - first_read == 3.0


def test_settling_straight_out_of_a_load_takes_about_eight_seconds():
    """The back-off is already capped at four seconds by the time a
    forty-second load ends, so the readings that confirm the rest state that
    follows are four seconds apart rather than growing from one -- eight
    seconds for `SETTLE` = 3 to agree, not the 1.5 s of the fixed tick, and up
    to about twelve seconds of staleness counted from the load's own last
    busy reading to the tick that finally goes ahead."""
    clock = FakeClock()
    guard = BusGuard(clock=clock)
    machine = guarded_machine(LOAD_STATES[0])
    i = 0
    while clock.now < 40.0:
        machine.memory[0xDD00] = bytes([LOAD_STATES[i % len(LOAD_STATES)]])
        i += 1
        guard.clear(machine)
        clock.advance(0.5)
    assert guard.wait_seconds == busguard.BACKOFF_CAP

    machine.memory[0xDD00] = bytes([FASTLOADER_REST])
    first_rest_read = settled_at = None
    while True:
        before = len(machine.reads)
        guard.clear(machine)
        if len(machine.reads) > before:
            if first_rest_read is None:
                first_rest_read = clock.now
            if guard.settled:
                settled_at = clock.now
                break
        clock.advance(guard.wait_seconds or 0.01)
    assert settled_at - first_rest_read == 8.0


# -- the guard, in the tick ---------------------------------------------------

def test_the_guard_reads_the_bus_first_and_nothing_else_when_it_is_busy(
        app, tmp_path, monkeypatch):
    machine = guarded_machine(LOAD_STATES[0])
    window = make_window(app, tmp_path, monkeypatch, machine)
    window.tick()
    assert machine.reads == [(busguard.CIA2_PORT_A, 1)]
    assert sum(n for _, n in machine.reads) == 1, "the guard costs one byte"


def test_a_released_bus_lets_the_whole_tick_through_after_the_byte(
        app, tmp_path, monkeypatch):
    machine = guarded_machine(RELEASED)
    window = make_window(app, tmp_path, monkeypatch, machine)
    counts = []
    for _ in range(10):
        machine.reads.clear()
        window.tick()
        assert machine.reads[0] == (busguard.CIA2_PORT_A, 1)
        counts.append(len(machine.reads))
    # `tests/test_issue286a2.py`'s four and twelve, plus the guard byte.
    assert counts == [5, 5, 5, 5, 13] * 2


def test_a_target_that_does_not_stop_the_processor_is_never_guarded(
        app, tmp_path, monkeypatch):
    machine = guarded_machine(LOAD_STATES[0])
    del machine.halts_on_read
    window = make_window(app, tmp_path, monkeypatch, machine)
    for _ in range(5):
        window.tick()
    assert (window.bus_guard.passed, window.bus_guard.skipped) == (0, 0)
    assert machine.reads[0] != (busguard.CIA2_PORT_A, 1)


def test_ticks_are_held_off_for_as_long_as_a_load_runs(
        app, tmp_path, monkeypatch):
    """Superseded by the back-off: thirty ticks at the ordinary 500 ms
    cadence over a fifteen-second load used to read `$DD00` all thirty
    times, one skip each. Now most of those ticks are held off before the
    guard even reads the bus, and only five reads happen."""
    machine = guarded_machine(LOAD_STATES[0])
    window = make_window(app, tmp_path, monkeypatch, machine)
    clock = FakeClock()
    window.bus_guard._clock = clock
    for i in range(30):
        machine.memory[0xDD00] = bytes([LOAD_STATES[i % len(LOAD_STATES)]])
        machine.reads.clear()
        window.tick()
        clock.advance(0.5)
    assert window.bus_guard.skipped == 5
    assert window.bus_guard.held_off == 25
    assert window.bus_guard.wait_seconds == busguard.BACKOFF_CAP


def test_a_held_off_tick_does_not_spend_the_roster_cadence(
        app, tmp_path, monkeypatch):
    """Four ticks at rest, a load on the fifth, and the roster read lands on
    the next tick that runs rather than five ticks later -- whether that
    tick reads the bus itself or is held off by the back-off from an earlier
    one still counted as busy."""
    machine = guarded_machine(RELEASED)
    window = make_window(app, tmp_path, monkeypatch, machine)
    clock = FakeClock()
    window.bus_guard._clock = clock
    for _ in range(4):
        window.tick()
        clock.advance(0.5)
    machine.memory[0xDD00] = bytes([LOAD_STATES[1]])
    machine.reads.clear()
    window.tick()
    assert len(machine.reads) == 1
    clock.advance(window.bus_guard.wait_seconds)
    machine.memory[0xDD00] = bytes([RELEASED])
    machine.reads.clear()
    window.tick()
    assert len(machine.reads) == 13


def test_the_fastloaders_rest_state_now_costs_settle_seconds_and_no_more(
        app, tmp_path, monkeypatch):
    """Cold, with no load before it: the shape of the cost is unchanged --
    `SETTLE - 1` guard-byte-only ticks, then the tick that settles, then
    ordinary ticks -- but reaching it now takes three seconds rather than
    the `SETTLE` * 500 ms = 1.5 s of the fixed tick, because the two ticks
    before the settle are a second and two seconds apart rather than half a
    second."""
    machine = guarded_machine(FASTLOADER_REST)
    window = make_window(app, tmp_path, monkeypatch, machine)
    clock = FakeClock()
    window.bus_guard._clock = clock
    sizes = []
    settled_at = None
    for _ in range(busguard.SETTLE + 2):
        machine.reads.clear()
        window.tick()
        sizes.append(len(machine.reads))
        if settled_at is None and window.bus_guard.settled:
            settled_at = clock.now
        clock.advance(window.bus_guard.wait_seconds or 0.5)
    assert sizes == [1] * (busguard.SETTLE - 1) + [5, 5, 5]
    assert settled_at == 3.0


def test_a_device_that_vanishes_under_the_guard_read_is_a_disconnection(
        app, tmp_path, monkeypatch):
    class Gone(MemoryTarget):
        def read(self, addr, length):
            raise NotConnected("gone")
    machine = Gone()
    machine.halts_on_read = True
    window = make_window(app, tmp_path, monkeypatch, machine)
    with pytest.raises(NotConnected):      # hosted: the host reattaches
        window.tick()


# -- the size ceiling ---------------------------------------------------------

def test_no_poll_block_on_any_title_passes_the_ceiling():
    for game in games.GAMES:
        for _, length in memory_blocks(game):
            assert length <= busguard.READ_CEILING, game.key


def test_no_read_in_a_walking_or_roster_tick_passes_the_ceiling(
        app, tmp_path, monkeypatch):
    machine = guarded_machine(RELEASED)
    window = make_window(app, tmp_path, monkeypatch, machine)
    for _ in range(20):
        window.tick()
    assert machine.reads, "nothing was read"
    assert max(n for _, n in machine.reads) <= busguard.READ_CEILING


def test_no_read_in_a_combat_tick_passes_the_ceiling(
        app, tmp_path, monkeypatch):
    machine = MemoryTarget(synthetic_arena())
    machine.halts_on_read = True
    machine.memory[0xDD00] = bytes([RELEASED])
    window = make_window(app, tmp_path, monkeypatch, machine)
    for _ in range(window.LIVE_EVERY * 2):
        window.tick()
    assert window.battle is not None, "the fight was not read"
    assert max(n for _, n in machine.reads) <= busguard.READ_CEILING
