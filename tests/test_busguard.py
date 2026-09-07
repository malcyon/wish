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


def test_ticks_are_skipped_for_as_long_as_a_load_runs(
        app, tmp_path, monkeypatch):
    machine = guarded_machine(LOAD_STATES[0])
    window = make_window(app, tmp_path, monkeypatch, machine)
    for i in range(30):
        machine.memory[0xDD00] = bytes([LOAD_STATES[i % len(LOAD_STATES)]])
        window.tick()
    assert len(machine.reads) == 30
    assert all(r == (busguard.CIA2_PORT_A, 1) for r in machine.reads)
    assert window.bus_guard.skipped == 30


def test_a_skipped_tick_does_not_spend_the_roster_cadence(
        app, tmp_path, monkeypatch):
    """Four ticks at rest, a load on the fifth, and the roster read lands on
    the next tick that runs rather than five ticks later."""
    machine = guarded_machine(RELEASED)
    window = make_window(app, tmp_path, monkeypatch, machine)
    for _ in range(4):
        window.tick()
    machine.memory[0xDD00] = bytes([LOAD_STATES[1]])
    machine.reads.clear()
    window.tick()
    assert len(machine.reads) == 1
    machine.memory[0xDD00] = bytes([RELEASED])
    machine.reads.clear()
    window.tick()
    assert len(machine.reads) == 13


def test_the_fastloaders_rest_state_costs_settle_ticks_and_no_more(
        app, tmp_path, monkeypatch):
    machine = guarded_machine(FASTLOADER_REST)
    window = make_window(app, tmp_path, monkeypatch, machine)
    sizes = []
    for _ in range(busguard.SETTLE + 2):
        machine.reads.clear()
        window.tick()
        sizes.append(len(machine.reads))
    assert sizes == [1] * (busguard.SETTLE - 1) + [5, 5, 5]


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
