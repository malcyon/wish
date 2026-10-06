"""`tools/c64/fasttravelrun.py` against a fake target, session and Fast Travel.

Nothing here boots VICE. The fakes keep one clock that every sleep advances, so a
bounded wait is measured in the seconds the driver asked for.
"""

from __future__ import annotations

import io
import json

import pytest

from automap import actions as engine
from tools.c64 import fasttravelrun as ftr

DISK_TEXT = "INSERT SIDE # 4 AND PRESS RETURN"


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Screen:
    def __init__(self, row24="", text=""):
        self._row, self._text = row24, text

    def row(self, n):
        assert n == 24
        return self._row

    def text(self):
        return self._text or self._row


class Kbd:
    def __init__(self):
        self.keys, self.shots = [], []

    def key(self, name, *a):
        self.keys.append(name)

    def screenshot(self, path):
        self.shots.append(path)


class Session:
    """Shows `screen_at(clock.now)`; answers a disk prompt once, as the real cooldown does."""

    def __init__(self, clock, screen_at):
        self.clock, self.screen_at = clock, screen_at
        self.kbd = Kbd()
        self.prompts, self.bars = 0, []

    def screen(self):
        return self.screen_at(self.clock.now)

    def wanted_disk(self, screen):
        return "SIDE4.D64" if "INSERT SIDE" in screen.text() else None

    def handle_prompt(self, screen=None):
        if self.prompts == 0 and self.wanted_disk(screen or self.screen()):
            self.prompts += 1
            return True
        return False

    def select_bar(self, label, **kw):
        self.bars.append(label)
        return True


class Memory:
    """A target whose bytes are a function of the clock."""

    def __init__(self, clock, area_at, script_at):
        self.clock, self.area_at, self.script_at = clock, area_at, script_at
        self.writes, self.closed = [], 0

    def read(self, addr, length):
        value = {0x6E1B: self.area_at, 0x49F2: self.script_at}[addr](self.clock.now)
        return bytes([value]) * length

    def write(self, addr, data):
        self.writes.append((addr, bytes(data)))

    def close(self):
        self.closed += 1


class FakeFastTravel:
    def __init__(self, clock, memory, legal_other_at=0.0, busy=0):
        self.clock, self.memory = clock, memory
        self.legal_other_at, self.busy = legal_other_at, busy
        self.pending = None
        self.cancelled = 0
        self.applied = []
        self.continue_error = None
        self.apply_writes = []

    def legality(self, target, area):
        if self.busy:
            self.busy -= 1
            return engine.Verdict(False, engine.FASTTRAVEL_BUSY)
        here = target.read(0x6E1B, 1)[0]
        if here == area.id:
            return engine.Verdict(False, "the party is already in that area")
        if here != 7 and self.clock.now < self.legal_other_at:
            return engine.Verdict(False, engine.FASTTRAVEL_BUSY)
        return engine.Verdict(True)

    def apply(self, target, area=None, **kw):
        self.applied.append(area.id)
        for addr, data in self.apply_writes:
            target.write(addr, data)
        return engine.Outcome(True, "walking out")

    def continue_pending(self, target):
        if self.continue_error:
            raise self.continue_error
        return None

    def cancel_pending(self):
        self.cancelled += 1
        self.pending = None


def build(screen_at=lambda t: Screen(), area_at=None, script_at=None, answer=None,
          budget=60.0, **ft_kw):
    clock = Clock()
    memory = Memory(clock, area_at or (lambda t: 7 if t < 1 else 18),
                    script_at or (lambda t: 7 if t < 1 else 18))
    sess = Session(clock, screen_at)
    ft = FakeFastTravel(clock, memory, **ft_kw)
    stream = io.StringIO()
    log = ftr.Log(stream, clock)
    import pathlib
    import tempfile
    out = pathlib.Path(tempfile.mkdtemp())
    drv = ftr.Driver(sess, lambda: memory, ft, out, log, answer=answer,
                     sleep=clock.sleep, clock=clock, budget=budget)
    return drv, sess, ft, memory, clock, stream


def events(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_arrival_waits_for_both_bytes_and_for_legality():
    # $6E1B reaches 18 at 1 s, $49F2 at 3 s, and legality toward another area at 5 s.
    drv, _, _, _, clock, stream = build(
        area_at=lambda t: 7 if t < 1 else 18,
        script_at=lambda t: 7 if t < 3 else 18,
        legal_other_at=5.0)
    result = drv.trip(18, "t")
    assert result["result"] == "arrived"
    checks = [e for e in events(stream) if e["event"] == "arrival-check"]
    assert checks, "the bytes matched, so legality must have been asked"
    assert all(c["t"] >= 3.0 for c in checks)
    assert [c["legality"] for c in checks][:-1] == [False] * (len(checks) - 1)
    assert checks[-1]["legality"] is True and checks[-1]["t"] >= 5.0


def test_area_byte_alone_is_not_arrival():
    drv, _, _, _, _, stream = build(script_at=lambda t: 7, budget=10.0)
    assert drv.trip(18, "t")["result"] == "timeout"
    assert not [e for e in events(stream) if e["event"] == "arrival-check"]


def test_legality_is_asked_toward_a_different_area():
    asked = []
    drv, _, ft, _, _, _ = build()
    real = ft.legality
    ft.legality = lambda target, area: (asked.append(area.id), real(target, area))[1]
    drv.trip(18, "t")
    assert asked[-1] == 2
    assert ftr.other_area(2) == 18


def test_disk_prompt_is_answered_and_return_is_never_pressed():
    drv, sess, _, _, _, _ = build(
        screen_at=lambda t: Screen("PRESS RETURN", DISK_TEXT) if t < 5 else Screen(),
        area_at=lambda t: 7 if t < 6 else 18, script_at=lambda t: 7 if t < 6 else 18)
    assert drv.trip(18, "t")["result"] == "arrived"
    assert sess.prompts == 1
    assert sess.kbd.keys == []


def test_return_message_is_pressed():
    drv, sess, _, _, _, _ = build(
        screen_at=lambda t: Screen("PRESS BUTTON OR RETURN TO CONTINUE.") if t < 2 else Screen())
    drv.trip(18, "t")
    assert sess.kbd.keys and set(sess.kbd.keys) == {"Return"}


def test_move_sub_bar_is_recognised_and_left_alone():
    drv, sess, _, _, _, stream = build(
        screen_at=lambda t: Screen("I,J,K,M, RETURN OR BUTTON"), answer="RETURN")
    assert drv.trip(18, "t")["result"] == "arrived"
    assert sess.kbd.keys == [] and sess.bars == []
    assert all(e["did"] is None for e in events(stream) if e["event"] == "poll")


def test_answer_selects_the_bar_word_a_bounded_number_of_times():
    drv, sess, _, _, _, _ = build(
        screen_at=lambda t: Screen("YES NO"), answer="YES",
        script_at=lambda t: 7, budget=30.0)
    result = drv.trip(18, "t")
    assert sess.bars == ["YES"] * ftr.ANSWERS_PER_TRIP
    assert result["questions"] == ftr.ANSWERS_PER_TRIP


def test_no_answer_given_leaves_a_question_bar_alone():
    drv, sess, _, _, _, _ = build(screen_at=lambda t: Screen("YES NO"))
    drv.trip(18, "t")
    assert sess.bars == [] and sess.kbd.keys == []


def test_cannot_act_right_now_is_retried_half_a_second_later():
    drv, _, ft, _, clock, _ = build(
        busy=2, area_at=lambda t: 7 if t < 3 else 18, script_at=lambda t: 7 if t < 3 else 18)
    assert drv.trip(18, "t")["result"] == "arrived"
    assert ft.applied == [18]
    assert clock.sleeps[:2] == [ftr.BUSY_SECONDS, ftr.BUSY_SECONDS]
    assert ftr.BUSY_SECONDS == 0.5


def test_cannot_act_right_now_is_bounded():
    drv, _, ft, _, _, _ = build(busy=10_000)
    assert drv.trip(18, "t")["result"] == "not_legal"
    assert ft.busy == 10_000 - ftr.BUSY_TRIES
    assert ft.applied == []


def test_trip_that_never_arrives_times_out_and_is_disarmed():
    drv, _, ft, _, _, stream = build(area_at=lambda t: 7, script_at=lambda t: 7, budget=5.0)
    assert drv.trip(18, "t")["result"] == "timeout"
    assert ft.cancelled >= 1
    assert any(e["event"] == "timeout" for e in events(stream))


def test_disarm_on_exception():
    drv, _, ft, memory, _, _ = build()
    ft.continue_error = RuntimeError("monitor gone")
    with pytest.raises(RuntimeError):
        drv.run([18, 2])
    assert ft.cancelled >= 1
    assert memory.closed > 0, "every connection is closed, error or not"


def test_second_leg_runs_after_the_first_and_stops_at_a_failure():
    drv, _, ft, memory, _, _ = build(
        area_at=lambda t: 7 if t < 1 else 18, script_at=lambda t: 7 if t < 1 else 18)
    results = drv.run([18, 2, 15])
    assert [r["dest"] for r in results] == [18, 2]
    assert [r["result"] for r in results] == ["arrived", "timeout"]
    assert ft.applied == [18, 2]


def test_no_write_reaches_the_generator():
    target = ftr.GuardedTarget(Memory(Clock(), lambda t: 0, lambda t: 0))
    for addr, length in ((0x03C2, 1), (0x03C8, 1), (0x03C0, 4), (0x03C5, 9), (0x03C2, 7)):
        with pytest.raises(ftr.DriverError):
            target.write(addr, bytes(length))
    target.write(0x03C1, b"\x00")
    target.write(0x03C9, b"\x00" * 4)
    assert [a for a, _ in target._target.writes] == [0x03C1, 0x03C9]


def test_fast_travel_write_to_the_generator_stops_the_leg_and_disarms():
    drv, _, ft, memory, _, _ = build()
    ft.apply_writes = [(0x03C4, b"\x01")]
    with pytest.raises(ftr.DriverError):
        drv.trip(18, "t")
    assert memory.writes == []


def test_source_never_names_a_generator_write():
    from pathlib import Path
    source = Path(ftr.__file__).read_text()
    assert ".write(0x03C" not in source


def test_bad_destination_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        ftr.main(["--save", "x.D64", "--to", "9999"])
    assert exc.value.code == 2
