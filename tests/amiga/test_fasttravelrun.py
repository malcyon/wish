"""`tools/amiga/fasttravelrun.py`, with a fake fast travel, target and screen."""

import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import actions as engine  # noqa: E402
from automap import amigatrip  # noqa: E402
from tools.amiga import fasttravelrun as ftr  # noqa: E402
from tools.amiga import tripprobe  # noqa: E402

ROW = SimpleNamespace(step_entry=0xAA)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Target:
    """Memory is never read for real: `read` returns the entry words."""

    data_base = 0x1000

    def __init__(self):
        self.writes = []

    def read(self, addr, length):
        assert addr == self.data_base + ROW.step_entry and length == ftr.ENTRY_BYTES
        return bytes(range(length))

    def write(self, addr, data, verify=True):
        self.writes.append((addr, bytes(data)))


class Travel:
    """A fast travel whose trip ends after `polls` calls of `continue_pending`."""

    def __init__(self, polls=3, legal=True, applies=True):
        self.polls, self.legal, self.applies = polls, legal, applies
        self.trip = None
        self.pending = None
        self.calls = []
        self.cancelled = False

    def legality(self, target, area=None, back=False):
        self.calls.append("legality")
        return engine.Verdict(self.legal, "" if self.legal else "no")

    def back_verdict(self, target):
        self.calls.append("back_verdict")
        return engine.Verdict(True)

    def apply(self, target, area=None, **kwargs):
        self.calls.append("apply")
        if self.applies:
            self.trip = object()
        return engine.Outcome(self.applies, "Traveling." if self.applies else "No.",
                              ((0x2000, b"\x01\x02"),))

    def apply_back(self, target):
        self.calls.append("apply_back")
        self.trip = object()
        return engine.Outcome(True, "back")

    def continue_pending(self, target):
        self.calls.append("continue")
        self.polls -= 1
        if self.polls <= 0:
            self.trip = None
        return None

    def cancel_pending(self):
        self.cancelled = True
        self.trip = None


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Area byte, key state and screen the tests set; the clock a fake one."""
    state = SimpleNamespace(area=7, taken=True, screen=b"world", pressed=[])
    monkeypatch.setattr(amigatrip, "area_id", lambda t, row: state.area)
    monkeypatch.setattr(amigatrip, "square", lambda t, row: (5, 6, 0))
    monkeypatch.setattr(tripprobe, "key_taken", lambda t, row: state.taken)
    state.clock = Clock()
    state.out = tmp_path
    state.stream = open(tmp_path / "log.jsonl", "w")
    state.log = ftr.Log(state.stream, state.clock)

    def drive(travel, **kwargs):
        got = ftr.run_trip(travel, Target(), ROW, SimpleNamespace(id=5), tmp_path,
                           lambda p: p.write_bytes(state.screen),
                           lambda key: state.pressed.append(key), state.log,
                           sleep=state.clock.sleep, clock=state.clock, **kwargs)
        state.stream.close()
        return got

    def events():
        return [json.loads(line) for line in (tmp_path / "log.jsonl").read_text().splitlines()]

    state.drive, state.events = drive, events
    yield state
    state.stream.close()


def test_the_sequence_is_legality_apply_then_polls_until_nothing_is_pending(world):
    travel = Travel(polls=3)
    got = world.drive(travel)
    assert travel.calls == ["legality", "apply", "continue", "continue", "continue"]
    assert got["result"] == "idle"
    kinds = [e["event"] for e in world.events()]
    assert kinds.index("legality") < kinds.index("apply") < kinds.index("read", kinds.index("apply"))


def test_it_waits_for_arrival_at_the_windows_200_ms_pace(world):
    travel = Travel(polls=10)
    start = world.clock()
    world.drive(travel)
    assert travel.calls.count("continue") == 10
    assert world.clock() - start == pytest.approx(10 * ftr.POLL_SECONDS)


def test_a_trip_that_never_ends_is_cancelled_at_the_budget(world):
    travel = Travel(polls=10**9)
    got = world.drive(travel, budget=5.0)
    assert got["result"] == "timeout"
    assert travel.cancelled
    assert world.clock() - 1000.0 <= 5.0 + 2 * ftr.POLL_SECONDS
    assert world.events()[-1]["why"] == "after"
    assert "timeout" in [e["event"] for e in world.events()]


def test_an_illegal_trip_is_logged_and_not_applied(world):
    travel = Travel(legal=False)
    got = world.drive(travel)
    assert got["result"] == "not_legal"
    assert travel.calls == ["legality"]
    assert world.events()[0] == {"t": 0.0, "event": "legality", "ok": False,
                                 "reason": "no", "back": False}


def test_an_apply_that_fails_ends_the_run_without_polling(world):
    travel = Travel(applies=False)
    got = world.drive(travel)
    assert got["result"] == "not_applied"
    assert "continue" not in travel.calls


def test_every_poll_logs_the_area_square_and_five_entry_words(world):
    world.drive(Travel(polls=2))
    polls = [e for e in world.events() if e["event"] == "read" and e["why"] == "poll"]
    assert len(polls) == 2
    for e in polls:
        assert e["area"] == 7 and e["square"] == [5, 6, 0]
        assert e["entry_words"] == bytes(range(10)).hex()
        assert e["key_taken"] is True


def test_a_screenshot_is_kept_only_when_the_screen_changes(world):
    travel = Travel(polls=40)
    world.drive(travel)
    shots = [e for e in world.events() if e["event"] == "screenshot"]
    assert len(shots) >= 3
    assert [e["changed"] for e in shots] == [True] + [False] * (len(shots) - 1)
    assert sorted(p.name for p in world.out.glob("*.png")) == ["001.png"]


def test_the_answer_is_pressed_once_when_the_screen_changes_with_the_key_taken(world):
    class Asking(Travel):
        def continue_pending(self, target):
            if len(self.calls) == 6:
                world.screen = b"question"
            if world.pressed:
                self.trip = None
            self.calls.append("continue")

    got = world.drive(Asking(polls=0), answer="y")
    assert world.pressed == ["y"]
    assert got["answered"] and got["result"] == "idle"


def test_no_answer_is_pressed_when_the_area_byte_changed(world):
    class Leaves(Travel):
        def continue_pending(self, target):
            world.area, world.screen = 5, b"other"
            return super().continue_pending(target)

    got = world.drive(Leaves(polls=20), answer="y")
    assert world.pressed == []
    assert not got["answered"]
    assert any(e["event"] == "answer_held" and "area byte" in e["reason"]
               for e in world.events())


def test_no_answer_is_pressed_before_the_key_is_taken(world):
    world.taken = False

    class Asking(Travel):
        def continue_pending(self, target):
            world.screen = b"question"
            return super().continue_pending(target)

    got = world.drive(Asking(polls=20), answer="y")
    assert world.pressed == []
    assert not got["answered"]


def test_an_answer_never_wanted_waits_only_answer_seconds_once_idle(world):
    got = world.drive(Travel(polls=1), answer="y")
    assert got["result"] == "idle" and not got["answered"]
    assert world.clock() - 1000.0 <= ftr.ANSWER_SECONDS + 3 * ftr.POLL_SECONDS


def test_back_makes_apply_back_and_not_apply(world):
    travel = Travel(polls=1)
    world.drive(travel, back=True)
    assert travel.calls[:3] == ["back_verdict", "apply_back", "continue"]
    assert "apply" not in travel.calls


@pytest.mark.parametrize("addr, size", [(0x03C2, 1), (0x03C8, 1), (0x03C0, 4), (0x03C5, 100)])
def test_the_guard_stops_a_write_in_the_forbidden_range(addr, size):
    target = Target()
    with pytest.raises(ftr.DriverError):
        ftr.WriteGuard(target).write(addr, bytes(size))
    assert target.writes == []


@pytest.mark.parametrize("addr, size", [(0x03C0, 2), (0x03C9, 4), (0x3000, 1)])
def test_the_guard_passes_a_write_outside_it(addr, size):
    target = Target()
    ftr.WriteGuard(target).write(addr, bytes(size))
    assert target.writes == [(addr, bytes(size))]


def test_the_guard_passes_reads_and_attributes_through():
    guard = ftr.WriteGuard(Target())
    assert guard.data_base == 0x1000
    assert guard.target.data_base == 0x1000
