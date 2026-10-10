"""`tools/amiga/fasttravelrun.py`, with a fake fast travel, target and screen."""

import json
import pathlib
import signal
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import actions as engine  # noqa: E402
from automap import amigatrip  # noqa: E402
from automap.amigafasttravel import AmigaFastTravel, _Hop  # noqa: E402
from tools.amiga import fasttravelrun as ftr  # noqa: E402
from tools.amiga import tripprobe  # noqa: E402

ROW = SimpleNamespace(key="pool-of-radiance", step_entry=0xAA)
ENTRY_BYTES = 10


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
        assert addr == self.data_base + ROW.step_entry and length == ENTRY_BYTES
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
            self.trip = SimpleNamespace(armed="armed")
        return engine.Outcome(self.applies, "Traveling." if self.applies else "No.",
                              ((0x2000, b"\x01\x02"),))

    def apply_back(self, target):
        self.calls.append("apply_back")
        self.trip = SimpleNamespace(armed="armed")
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
    state.gate_at = 0.0
    monkeypatch.setattr(amigatrip, "gate",
                        lambda t, row: state.clock.now >= 1000.0 + state.gate_at)
    # Arming leaves the fake game holding the trip until `disarm` puts it back.
    state.armed = []
    real_apply = Travel.apply

    def apply(self, target, area=None, **kwargs):
        got = real_apply(self, target, area=area, **kwargs)
        if self.trip is not None:
            state.armed.append(self.trip.armed)
        return got

    monkeypatch.setattr(Travel, "apply", apply)
    monkeypatch.setattr(amigatrip, "disarm",
                        lambda target, armed: state.armed.remove(armed) or True)
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


def test_a_pools_of_darkness_row_with_no_window_pointer_logs_the_after_read(monkeypatch, tmp_path):
    row = amigatrip.row_for("pools-of-darkness")
    assert row.window_pointer is None
    monkeypatch.setattr(amigatrip, "area_id", lambda t, r: 33)
    monkeypatch.setattr(amigatrip, "square", lambda t, r: (8, 15, 0))
    monkeypatch.setattr(amigatrip, "entry_words", lambda t, r: b"\0\1")
    monkeypatch.setattr(amigatrip, "gate", lambda t, r: True)

    class Memory:
        data_base = 0x1000

        def read(self, addr, length):
            assert addr == self.data_base + row.key_buffer
            return b"\0"

    stream = open(tmp_path / "log.jsonl", "w")
    clock = Clock()
    got = ftr.run_trip(Travel(polls=1), Memory(), row, SimpleNamespace(id=33), tmp_path,
                       lambda p: p.write_bytes(b"s"), lambda key: None,
                       ftr.Log(stream, clock), sleep=clock.sleep, clock=clock)
    stream.close()
    lines = [json.loads(x) for x in (tmp_path / "log.jsonl").read_text().splitlines()]
    after = [e for e in lines if e["event"] == "read" and e.get("why") == "after"]
    assert got["result"] == "idle" and after and after[0]["area"] == 33


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
    assert world.clock() - start == pytest.approx(10 * ftr.POLL_SECONDS + ftr.SETTLE_SECONDS)


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


def test_the_final_shot_waits_for_the_gate_and_then_the_settle_time(world):
    world.gate_at = 30.0
    shots = []

    def shot(path):
        shots.append(world.clock.now)
        path.write_bytes(b"arrived" if world.clock.now >= 1000.0 + 30.0 else b"drawing")

    ftr.run_trip(Travel(polls=3), Target(), ROW, SimpleNamespace(id=5), world.out, shot,
                 lambda key: None, world.log, sleep=world.clock.sleep, clock=world.clock)
    assert shots[-1] >= 1000.0 + 30.0 + ftr.SETTLE_SECONDS
    assert world.events()[-3]["event"] == "settle"


def test_a_gate_that_never_passes_ends_at_the_settle_budget(world):
    world.gate_at = 1e9
    world.drive(Travel(polls=1), budget=10.0)
    settle = [e for e in world.events() if e["event"] == "settle"]
    assert settle[0]["gate"] is False and settle[0]["waited"] <= ftr.SETTLE_BUDGET_SECONDS + ftr.POLL_SECONDS


def test_a_gate_that_never_passes_is_reported_unsettled_and_exits_nonzero(world, monkeypatch,
                                                                         tmp_path, capsys):
    world.gate_at = 1e9
    got = world.drive(Travel(polls=1), budget=10.0)
    assert got["result"] == "idle" and got["settled"] is False
    monkeypatch.setattr(ftr, "run_trip", lambda *a, **k: got)
    _run_main(monkeypatch, tmp_path)
    assert _run_main.code != 0
    assert "never became ready for Fast Travel" in capsys.readouterr().err


def test_a_gate_that_passes_is_settled(world):
    assert world.drive(Travel(polls=1))["settled"] is True


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


class _Arrives(Travel):
    """Leaves the starting area at once and shows a question that holds the gate shut."""

    def continue_pending(self, target):
        _Arrives.world.area, _Arrives.world.screen = 26, b"take boat?"
        return super().continue_pending(target)


def _arriving(world, monkeypatch):
    _Arrives.world = world
    world.asked = False

    def gate(target, row):
        return world.pressed != [] or world.asked
    monkeypatch.setattr(amigatrip, "gate", gate)


def test_an_arrival_answer_is_pressed_once_and_settles_the_leg(world, monkeypatch):
    _arriving(world, monkeypatch)
    got = world.drive(_Arrives(polls=1), arrival_answer="y")
    assert world.pressed == ["y"]
    assert got["arrival_answered"] and got["settled"] and got["result"] == "idle"
    assert [e["key"] for e in world.events() if e["event"] == "arrival_answer"] == ["y"]


def test_a_screen_that_keeps_changing_gets_no_arrival_key_and_the_gate_opens_alone(
        world, monkeypatch):
    _arriving(world, monkeypatch)
    redraws = iter(range(10_000))

    def gate(target, row):
        world.screen = b"redraw %d" % next(redraws)
        return world.clock.now >= 1000.0 + 8.0
    monkeypatch.setattr(amigatrip, "gate", gate)
    got = world.drive(_Arrives(polls=1), arrival_answer="y")
    assert world.pressed == [] and not got["arrival_answered"] and got["settled"]
    assert any(e["event"] == "arrival_answer_held" and "changing" in e["reason"]
               for e in world.events())


def test_the_arrival_press_logs_the_gate_and_the_unchanged_polls(world, monkeypatch):
    _arriving(world, monkeypatch)
    world.drive(_Arrives(polls=1), arrival_answer="y")
    (event,) = [e for e in world.events() if e["event"] == "arrival_answer"]
    assert event["gate"] is False and event["unchanged_polls"] >= 1


def test_slow_screenshots_do_not_close_the_arrival_window_before_the_key_goes(
        world, monkeypatch):
    _arriving(world, monkeypatch)
    shots = []

    def slow_shot(path):
        # The screen is still redrawing under the first arrival screenshot, so the
        # unchanged one that lets the key go is the third, past ANSWER_SECONDS.
        world.clock.now += 13.0
        if world.area == 26:
            shots.append(world.clock.now)
        path.write_bytes(b"redrawing" if len(shots) == 1 else world.screen)

    got = ftr.run_trip(_Arrives(polls=1), Target(), ROW, SimpleNamespace(id=5), world.out,
                       slow_shot, lambda key: world.pressed.append(key), world.log,
                       sleep=world.clock.sleep, clock=world.clock, arrival_answer="y")
    world.stream.close()
    assert world.pressed == ["y"] and got["arrival_answered"]


def test_without_an_arrival_answer_the_leg_stays_unsettled(world, monkeypatch):
    _arriving(world, monkeypatch)
    got = world.drive(_Arrives(polls=1))
    assert world.pressed == []
    assert not got["arrival_answered"] and not got["settled"]


def test_an_arrival_answer_is_not_pressed_in_the_starting_area(world, monkeypatch):
    _arriving(world, monkeypatch)

    class Stays(_Arrives):
        def continue_pending(self, target):
            world.screen = b"other"
            return Travel.continue_pending(self, target)

    got = world.drive(Stays(polls=1), arrival_answer="y")
    assert world.pressed == [] and not got["arrival_answered"]


def test_the_arrival_answer_reaches_both_legs(monkeypatch, tmp_path):
    seen = _fake_main(monkeypatch, tmp_path, ["--to", "32", "--back", "--arrival-answer", "y"])
    assert [(c["back"], c["arrival_answer"]) for c in seen["calls"]] == [(False, ("y",)), (True, ("y",))]


def _two_prompts(world, monkeypatch, second_screen):
    """Arrives at a first prompt; the first key shows `second_screen`; the gate opens after the second key."""
    _Arrives.world = world
    world.asked = False

    def press(key):
        world.pressed.append(key)
        world.screen = second_screen if len(world.pressed) == 1 else b"menu"
    world.press = press
    monkeypatch.setattr(amigatrip, "gate", lambda t, row: len(world.pressed) >= 2)


def _drive_with(world, **kwargs):
    got = ftr.run_trip(_Arrives(polls=1), Target(), ROW, SimpleNamespace(id=5), world.out,
                       lambda p: p.write_bytes(world.screen), world.press, world.log,
                       sleep=world.clock.sleep, clock=world.clock, **kwargs)
    world.stream.close()
    return got


def test_an_arrival_answer_sequence_presses_each_key_on_its_own_screen(world, monkeypatch):
    _two_prompts(world, monkeypatch, b"second page")
    got = _drive_with(world, arrival_answer=("Return", "Return"))
    assert world.pressed == ["Return", "Return"]
    assert got["settled"] and got["arrival_keys"] == ["Return", "Return"]
    assert [e["key"] for e in world.events() if e["event"] == "arrival_answer"] == [
        "Return", "Return"]


def test_the_next_arrival_key_waits_for_the_screen_to_change(world, monkeypatch):
    _two_prompts(world, monkeypatch, b"take boat?")
    got = _drive_with(world, arrival_answer=("Return", "Return"))
    assert world.pressed == ["Return"] and not got["settled"]


def test_arrival_answer_is_repeatable_on_the_command_line(monkeypatch, tmp_path):
    seen = _fake_main(monkeypatch, tmp_path, ["--to", "32", "--arrival-answer", "Return",
                                              "--arrival-answer", "l"])
    assert seen["calls"][0]["arrival_answer"] == ("Return", "l")
    for argv in (["--arrival-answer", "Return", "--arrival-answer", "nonsense-key"],
                 ["--arrival-answer", "nonsense-key", "--arrival-answer", "Return"]):
        with pytest.raises(SystemExit):
            ftr.main(["--holder", "h", "--disks", "D", "--to", "5", "--out", str(tmp_path),
                      *argv])


@pytest.mark.parametrize("areas, hinted", [([16, 51], True), ([16], False)])
def test_an_unsettled_leg_that_reached_another_area_names_arrival_answer(
        monkeypatch, tmp_path, capsys, areas, hinted):
    _back_run(monkeypatch, tmp_path, [{"result": "idle", "settled": False, "areas_seen": areas}])
    err = capsys.readouterr().err
    assert "never became ready" in err
    assert ("--arrival-answer" in err) is hinted


def test_the_second_arrival_key_gets_its_own_full_window(world, monkeypatch):
    _arriving(world, monkeypatch)
    monkeypatch.setattr(amigatrip, "gate", lambda t, row: len(world.pressed) >= 2)
    first, later = [], []

    def shot(path):
        if not world.pressed:
            # The first key goes after ANSWER_SECONDS have passed since arrival.
            world.clock.now += 13.0
            if world.area == 26:
                first.append(world.clock.now)
            path.write_bytes(b"redrawing" if len(first) == 1 else world.screen)
        else:
            # The second screen redraws for three looks, so its key goes on the fourth.
            later.append(world.clock.now)
            path.write_bytes((b"a", b"b", b"c")[min(len(later), 3) - 1])

    got = ftr.run_trip(_Arrives(polls=1), Target(), ROW, SimpleNamespace(id=5), world.out,
                       shot, lambda key: world.pressed.append(key), world.log,
                       sleep=world.clock.sleep, clock=world.clock,
                       arrival_answer=("Return", "Return"))
    world.stream.close()
    assert first[-1] - 1000.0 >= ftr.ANSWER_SECONDS
    assert world.pressed == ["Return", "Return"] and got["settled"]


@pytest.mark.parametrize("keys, hinted", [([], True), (["Return"], False)])
def test_the_arrival_answer_hint_is_not_printed_when_keys_were_pressed(
        monkeypatch, tmp_path, capsys, keys, hinted):
    _back_run(monkeypatch, tmp_path, [{"result": "idle", "settled": False,
                                       "areas_seen": [16, 51], "arrival_keys": keys}])
    err = capsys.readouterr().err
    assert "never became ready" in err
    assert ("--arrival-answer" in err) is hinted


def test_an_unknown_arrival_answer_key_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit):
        ftr.main(["--holder", "h", "--disks", "D", "--to", "5", "--out", str(tmp_path),
                  "--arrival-answer", "nonsense-key"])


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
    assert world.clock() - 1000.0 <= (ftr.ANSWER_SECONDS + 3 * ftr.POLL_SECONDS
                                      + ftr.SETTLE_SECONDS)


def test_back_makes_apply_back_and_not_apply(world):
    travel = Travel(polls=1)
    world.drive(travel, back=True)
    assert travel.calls[:3] == ["back_verdict", "apply_back", "continue"]
    assert "apply" not in travel.calls


@pytest.mark.parametrize("failure", [RuntimeError("boom"), KeyboardInterrupt()])
def test_an_exception_after_apply_leaves_the_trip_disarmed(world, failure):
    class Raises(Travel):
        def continue_pending(self, target):
            raise failure

    travel = Raises()
    with pytest.raises(type(failure)):
        world.drive(travel)
    assert travel.trip is None and travel.pending is None
    assert world.armed == []


def test_a_trip_that_times_out_is_disarmed_in_the_game(world):
    travel = Travel(polls=10**9)
    world.drive(travel, budget=1.0)
    assert travel.trip is None
    assert world.armed == []


def test_a_log_that_fails_right_after_apply_still_leaves_the_trip_disarmed(world):
    travel = Travel()
    real = world.log

    def log(event, **fields):
        if event == "apply":
            raise OSError("disk full")
        return real(event, **fields)

    with pytest.raises(OSError):
        ftr.run_trip(travel, Target(), ROW, SimpleNamespace(id=5), world.out,
                     lambda p: p.write_bytes(world.screen), lambda key: None, log,
                     sleep=world.clock.sleep, clock=world.clock)
    assert travel.trip is None and world.armed == []


def test_a_disarm_that_fails_is_reported_and_the_first_exception_still_raised(
        world, monkeypatch, capsys):
    def broken(target, armed):
        raise ValueError("no memory")

    monkeypatch.setattr(amigatrip, "disarm", broken)

    class Raises(Travel):
        def continue_pending(self, target):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        world.drive(Raises())
    assert "disarm failed" in capsys.readouterr().err


# -- --title, areas_seen, the party and the entry words ------------------------


def test_areas_seen_lists_the_start_then_each_new_area_byte(world, monkeypatch):
    class Hops(Travel):
        def continue_pending(self, target):
            world.area = {2: 8, 4: 5}.get(len(self.calls) - 2, world.area)
            return super().continue_pending(target)

    got = world.drive(Hops(polls=8))
    assert got["areas_seen"] == [7, 8, 5]


def test_an_area_read_inside_continue_pending_is_recorded(world):
    class Inside(Travel):
        def continue_pending(self, target):
            if len(self.calls) == 2:
                world.area = 27
                amigatrip.area_id(target, ROW)
                world.area = 0
            return super().continue_pending(target)

    world.area = 13
    assert world.drive(Inside(polls=4))["areas_seen"] == [13, 27, 0]


def test_the_wrapper_records_the_area_the_real_continue_pending_reads(monkeypatch):
    target = object()
    monkeypatch.setattr(amigatrip, "ROWS", {"pool-of-radiance": ROW})
    monkeypatch.setattr(amigatrip, "area_id", lambda t, row: 9)
    travel = AmigaFastTravel("pool-of-radiance", None)
    travel._repaired = target
    travel.pending = _Hop(7, 5, SimpleNamespace(id=1, name="Far place"), None, b"")
    seen = []
    with ftr._watching_area(seen.append):
        travel.continue_pending(target)
    assert seen == [9]


def test_a_trip_that_never_leaves_sees_one_area(world):
    assert world.drive(Travel(polls=3))["areas_seen"] == [7]


def test_the_party_names_are_logged_and_returned_before_and_after(world):
    names = iter([["A", "B"], ["A"]])
    got = world.drive(Travel(polls=1), party=lambda t: [SimpleNamespace(name=n) for n in next(names)])
    assert got["party_before"] == ["A", "B"] and got["party_after"] == ["A"]
    assert [(e["why"], e["names"]) for e in world.events() if e["event"] == "party"] == [
        ("before", ["A", "B"]), ("after", ["A"])]


def test_an_unreadable_party_is_none(world):
    got = world.drive(Travel(polls=1), party=lambda t: None)
    assert got["party_before"] is None and got["party_after"] is None


@pytest.mark.parametrize("key,words", [("pool-of-radiance", 5), ("pools-of-darkness", 1),
                                       ("curse-of-the-azure-bonds", 1)])
def test_the_entry_words_come_from_the_titles_row(key, words, monkeypatch):
    seen = []

    class T:
        data_base = 0x1000

        def read(self, addr, length):
            seen.append(length)
            return bytes(length)

    monkeypatch.setattr(amigatrip, "area_id", lambda t, row: 1)
    monkeypatch.setattr(amigatrip, "square", lambda t, row: (0, 0, 0))
    got = ftr._reading(T(), amigatrip.row_for(key))
    assert seen == [2 * words] and len(got["entry_words"]) == 4 * words


def _run_main(monkeypatch, tmp_path):
    from automap import amiga, amigafasttravel
    from tools.amiga import amigadrive

    class T:
        def __init__(self, pipe, machine):
            pass

        def locate(self):
            return 1

    monkeypatch.setattr(amiga, "WinuaePipe", _Pipe)
    monkeypatch.setattr(amiga, "AmigaTarget", T)
    monkeypatch.setattr(amigafasttravel, "AmigaFastTravel", lambda key, disks: None)
    monkeypatch.setattr(amigadrive, "shot", lambda *a: None)
    monkeypatch.setattr(ftr.engine, "area_by_id", lambda i, t: SimpleNamespace(id=i, title=t))
    _run_main.code = ftr.main(["--holder", "h", "--disks", "D", "--to", "3",
                               "--out", str(tmp_path)])


def _back_run(monkeypatch, tmp_path, legs):
    calls = []

    def fake(*a, **k):
        calls.append(k.get("back", False))
        return legs[len(calls) - 1]

    monkeypatch.setattr(ftr, "run_trip", fake)
    from automap import amiga, amigafasttravel
    from tools.amiga import amigadrive

    class T:
        def __init__(self, pipe, machine):
            pass

        def locate(self):
            return 1

    monkeypatch.setattr(amiga, "WinuaePipe", _Pipe)
    monkeypatch.setattr(amiga, "AmigaTarget", T)
    monkeypatch.setattr(amigafasttravel, "AmigaFastTravel", lambda key, disks: None)
    monkeypatch.setattr(amigadrive, "shot", lambda *a: None)
    monkeypatch.setattr(ftr.engine, "area_by_id", lambda i, t: SimpleNamespace(id=i, title=t))
    code = ftr.main(["--holder", "h", "--disks", "D", "--to", "3", "--back",
                     "--out", str(tmp_path)])
    return code, calls


def test_an_unsettled_first_leg_skips_the_way_back_and_exits_nonzero(monkeypatch, tmp_path,
                                                                    capsys):
    code, calls = _back_run(monkeypatch, tmp_path, [{"result": "idle", "settled": False}])
    out = capsys.readouterr()
    assert code == 1 and calls == [False]
    assert '"result": "skipped"' in out.out
    assert "Leg 1 (the trip) never became ready" in out.err


def test_an_unsettled_way_back_exits_nonzero_naming_leg_two(monkeypatch, tmp_path, capsys):
    code, calls = _back_run(monkeypatch, tmp_path, [{"result": "idle", "settled": True},
                                                    {"result": "idle", "settled": False}])
    assert code == 1 and calls == [False, True]
    assert "Leg 2 (the way back) never became ready" in capsys.readouterr().err


class _Pipe:
    def __init__(self, holder):
        pass


@pytest.mark.parametrize("title", ["curse-of-the-azure-bonds", "secret-of-the-silver-blades",
                                   "pools-of-darkness"])
def test_title_picks_the_machine_row_and_fast_travel(monkeypatch, tmp_path, title):
    from automap import amiga, amigafasttravel
    from tools.amiga import amigadrive

    built = {}

    class T:
        def __init__(self, pipe, machine):
            built["machine"] = machine

        def locate(self):
            return 1

    class F:
        def __init__(self, key, disks):
            built["fasttravel"] = (key, disks)

    def run_trip(fasttravel, target, row, area, *args, **kwargs):
        built.update(row=row, area=area, party=kwargs["party"])
        return {"result": "idle"}

    monkeypatch.setattr(amiga, "WinuaePipe", _Pipe)
    monkeypatch.setattr(amiga, "AmigaTarget", T)
    monkeypatch.setattr(amigafasttravel, "AmigaFastTravel", F)
    monkeypatch.setattr(ftr, "run_trip", run_trip)
    monkeypatch.setattr(amigadrive, "shot", lambda *a: None)
    monkeypatch.setattr(ftr.engine, "area_by_id", lambda i, t: SimpleNamespace(id=i, title=t))
    assert ftr.main(["--holder", "h", "--disks", "D", "--title", title, "--to", "3",
                     "--out", str(tmp_path)]) == 0
    assert built["machine"] is amiga.MACHINES[title]
    assert built["fasttravel"] == (title, "D")
    assert built["row"] is amigatrip.row_for(title)
    assert built["area"].title == amiga.MACHINES[title].title
    assert built["party"] is ftr.amigaparty.read_party


@pytest.mark.parametrize("to", [84, 82])
def test_pools_of_darkness_destinations_come_from_its_amiga_table(monkeypatch, tmp_path, to):
    from automap import amiga, amigafasttravel
    from tools.amiga import amigadrive

    seen = {}

    class T:
        def __init__(self, pipe, machine):
            pass

        def locate(self):
            return 1

    def run_trip(fasttravel, target, row, area, *args, **kwargs):
        seen["area"] = area
        return {"result": "idle"}

    monkeypatch.setattr(amiga, "WinuaePipe", _Pipe)
    monkeypatch.setattr(amiga, "AmigaTarget", T)
    monkeypatch.setattr(amigafasttravel, "AmigaFastTravel", lambda key, disks: None)
    monkeypatch.setattr(ftr, "run_trip", run_trip)
    monkeypatch.setattr(amigadrive, "shot", lambda *a: None)
    assert ftr.main(["--holder", "h", "--disks", "D", "--title", "pools-of-darkness",
                     "--to", str(to), "--out", str(tmp_path)]) == 0
    assert seen["area"].id == to


def test_an_unknown_title_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit):
        ftr.main(["--holder", "h", "--disks", "D", "--title", "nope", "--to", "3",
                  "--out", str(tmp_path)])


class PeekTarget:
    """Memory whose Pools of Darkness variable $0010 changes when the trip has run."""

    data_base = 0x1000

    def __init__(self, travel):
        self.travel = travel

    def read(self, addr, length):
        if addr == self.data_base + 0x57AC:
            return (0x4000).to_bytes(4, "big")
        if addr == 0x4010:
            return bytes([9 if self.travel.calls.count("continue") else 1])
        if addr == self.data_base + ROW.step_entry:
            return bytes(length)
        raise AssertionError(hex(addr))

    def write(self, addr, data, verify=True):
        raise AssertionError("a peek must not write")


def test_peek_var_logs_values_before_and_after_and_reports_unreadable(world):
    travel = Travel(polls=2)
    ftr.run_trip(travel, PeekTarget(travel), ROW, SimpleNamespace(id=5), world.out,
                 lambda p: p.write_bytes(world.screen), lambda key: None, world.log,
                 sleep=world.clock.sleep, clock=world.clock,
                 peek_vars=[0x10, 0x401], title="pools-of-darkness")
    world.stream.close()
    peeks = [e for e in world.events() if e["event"] == "peek"]
    assert [e["why"] for e in peeks] == ["before", "after"]
    assert [v["value"] for v in (p["variables"][0] for p in peeks)] == [1, 9]
    assert all("not readable" in p["variables"][1]["unreadable"] for p in peeks)


def test_without_peek_var_nothing_is_peeked(world):
    world.drive(Travel(polls=1))
    assert "peek" not in [e["event"] for e in world.events()]


def test_legality_lists_each_area_with_its_verdict_and_makes_no_trip(monkeypatch, tmp_path, capsys):
    from automap import amiga, amigafasttravel
    from tools.amiga import amigadrive

    asked = []

    class T:
        def __init__(self, pipe, machine):
            pass

        def locate(self):
            return 1

    class F:
        def __init__(self, key, disks):
            pass

        def legality(self, target, area=None, back=False):
            asked.append(area.id)
            return engine.Verdict(area.id == 1, "" if area.id == 1 else "held")

        def apply(self, *args, **kwargs):
            raise AssertionError("a legality run makes no trip")

    rows = [SimpleNamespace(id=1, name="Alpha"), SimpleNamespace(id=2, name="Beta")]
    monkeypatch.setattr(amiga, "WinuaePipe", _Pipe)
    monkeypatch.setattr(amiga, "AmigaTarget", T)
    monkeypatch.setattr(amigafasttravel, "AmigaFastTravel", F)
    monkeypatch.setattr(amigadrive, "shot", lambda *a: None)
    monkeypatch.setattr(ftr, "candidate_areas", lambda title: rows)
    assert ftr.main(["--holder", "h", "--disks", "D", "--legality"]) == 0
    assert asked == [1, 2]
    assert capsys.readouterr().out.splitlines() == ["1\tAlpha\toffered", "2\tBeta\twithheld\theld"]


def test_legality_with_measure_row_reports_what_the_measured_row_allows(monkeypatch, capsys):
    from automap import amiga, amigafasttravel
    from tools.amiga import amigadrive

    key = "secret-of-the-silver-blades"

    class T:
        def __init__(self, pipe, machine):
            pass

        def locate(self):
            return 1

    class F:
        def __init__(self, title, disks):
            pass

        def legality(self, target, area=None, back=False):
            confirmed = amigatrip.ROWS[key].confirmed
            return engine.Verdict(confirmed, "" if confirmed else "unconfirmed")

    monkeypatch.setattr(amiga, "WinuaePipe", _Pipe)
    monkeypatch.setattr(amiga, "AmigaTarget", T)
    monkeypatch.setattr(amigafasttravel, "AmigaFastTravel", F)
    monkeypatch.setattr(amigadrive, "shot", lambda *a: None)
    monkeypatch.setattr(ftr, "candidate_areas", lambda title: [SimpleNamespace(id=1, name="A")])
    before = amigatrip.ROWS[key]
    args = ["--holder", "h", "--disks", "D", "--title", key, "--legality"]
    assert ftr.main(args + ["--measure-row"]) == 0
    assert capsys.readouterr().out.splitlines() == ["1\tA\toffered"]
    assert amigatrip.ROWS[key] is before
    assert ftr.main(args) == 0
    assert capsys.readouterr().out.splitlines() == ["1\tA\twithheld\tunconfirmed"]


def test_without_legality_to_and_out_are_required():
    with pytest.raises(SystemExit):
        ftr.main(["--holder", "h", "--disks", "D"])


def _fake_main(monkeypatch, tmp_path, argv, title="secret-of-the-silver-blades"):
    """Run `main` over fakes; returns what `run_trip` saw and the fast travel built."""
    from automap import amiga, amigafasttravel
    from tools.amiga import amigadrive

    seen = {"calls": []}

    class T:
        def __init__(self, pipe, machine):
            pass

        def locate(self):
            return 1

    class F:
        back = None

        def __init__(self, key, disks):
            seen["fasttravel"] = self

    def run_trip(fasttravel, target, row, area, *args, **kwargs):
        seen["calls"].append({"area": area, "back": kwargs.get("back", False),
                              "row": row, "staged": fasttravel.back,
                              "answer": kwargs.get("answer"),
                              "arrival_answer": kwargs.get("arrival_answer")})
        return {"result": "idle", "settled": True}

    monkeypatch.setattr(amiga, "WinuaePipe", _Pipe)
    monkeypatch.setattr(amiga, "AmigaTarget", T)
    monkeypatch.setattr(amigafasttravel, "AmigaFastTravel", F)
    monkeypatch.setattr(ftr, "run_trip", run_trip)
    monkeypatch.setattr(amigadrive, "shot", lambda *a: None)
    monkeypatch.setattr(ftr.engine, "area_by_id", lambda i, t: SimpleNamespace(id=i, title=t))
    seen["code"] = ftr.main(["--holder", "h", "--disks", "D", "--title", title,
                             "--out", str(tmp_path), *argv])
    return seen


def test_measure_row_confirms_the_row_for_the_run_and_puts_it_back(monkeypatch, tmp_path):
    key = "secret-of-the-silver-blades"
    before = amigatrip.ROWS[key]
    assert not before.confirmed
    seen = _fake_main(monkeypatch, tmp_path, ["--to", "32", "--measure-row"])
    row = seen["calls"][0]["row"]
    assert row.confirmed and all(d.offered for d in row.differences)
    assert amigatrip.ROWS[key] is before and not before.confirmed
    logged = [json.loads(line) for line in (tmp_path / "fasttravel.jsonl").read_text().splitlines()]
    assert [e["title"] for e in logged if e["event"] == "measure_row"] == [key]


def test_without_measure_row_the_row_is_the_tables(monkeypatch, tmp_path):
    seen = _fake_main(monkeypatch, tmp_path, ["--to", "32"])
    assert seen["calls"][0]["row"] is amigatrip.ROWS["secret-of-the-silver-blades"]


@pytest.mark.parametrize("failure, outcome", [(ftr.DriverError("no"), SystemExit),
                                              (KeyboardInterrupt(), KeyboardInterrupt)])
def test_measure_row_is_put_back_when_the_run_fails(monkeypatch, tmp_path, failure, outcome):
    key = "secret-of-the-silver-blades"
    before = amigatrip.ROWS[key]

    def boom(*a, **k):
        raise failure

    monkeypatch.setattr(ftr, "run_trip", boom)
    from automap import amiga, amigafasttravel
    from tools.amiga import amigadrive

    class T:
        def __init__(self, *a):
            pass

        def locate(self):
            return 1

    monkeypatch.setattr(amiga, "WinuaePipe", _Pipe)
    monkeypatch.setattr(amiga, "AmigaTarget", T)
    monkeypatch.setattr(amigafasttravel, "AmigaFastTravel", lambda key, disks: None)
    monkeypatch.setattr(amigadrive, "shot", lambda *a: None)
    monkeypatch.setattr(ftr.engine, "area_by_id", lambda i, t: SimpleNamespace(id=i, title=t))
    with pytest.raises(outcome):
        ftr.main(["--holder", "h", "--disks", "D", "--title", key, "--to", "32",
                  "--measure-row", "--out", str(tmp_path)])
    assert amigatrip.ROWS[key] is before


def test_measure_row_is_put_back_when_the_log_call_fails():
    key = "secret-of-the-silver-blades"
    before = amigatrip.ROWS[key]

    def log(*a, **k):
        raise OSError("disk full")

    with pytest.raises(OSError), ftr.measuring_row(key, log):
        pass
    assert amigatrip.ROWS[key] is before


def test_waypoint_with_back_makes_apply_back_alone_from_the_staged_square(monkeypatch, tmp_path):
    seen = _fake_main(monkeypatch, tmp_path, ["--waypoint", "0,9,13,0", "--back"],
                      title="pool-of-radiance")
    assert [(c["area"], c["back"]) for c in seen["calls"]] == [(None, True)]
    assert seen["calls"][0]["staged"] == engine.Waypoint(0, None, (9, 13, 0))
    assert seen["code"] == 0


def test_a_waypoint_return_gets_the_answer(monkeypatch, tmp_path):
    seen = _fake_main(monkeypatch, tmp_path,
                      ["--waypoint", "0,9,13,0", "--back", "--answer", "y"],
                      title="pool-of-radiance")
    assert [(c["back"], c["answer"]) for c in seen["calls"]] == [(True, "y")]


def test_a_forward_trip_and_its_return_each_get_the_answer(monkeypatch, tmp_path):
    seen = _fake_main(monkeypatch, tmp_path, ["--to", "32", "--back", "--answer", "y"])
    assert [(c["back"], c["answer"]) for c in seen["calls"]] == [(False, "y"), (True, "y")]


def test_waypoint_accepts_hex_numbers(monkeypatch):
    assert ftr.parse_waypoint("0x1F,3,0xa,2") == engine.Waypoint(0x1F, None, (3, 10, 2))


def test_waypoint_without_back_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit) as exc:
        ftr.main(["--holder", "h", "--disks", "D", "--waypoint", "0,9,13,0",
                  "--out", str(tmp_path)])
    assert exc.value.code == 2


@pytest.mark.parametrize("text", ["0,9,13", "0,9,13,x", "a,b,c,d"])
def test_a_malformed_waypoint_is_a_usage_error(tmp_path, text):
    with pytest.raises(SystemExit) as exc:
        ftr.main(["--holder", "h", "--disks", "D", "--waypoint", text, "--back",
                  "--out", str(tmp_path)])
    assert exc.value.code == 2


def test_waypoint_with_a_destination_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit) as exc:
        ftr.main(["--holder", "h", "--disks", "D", "--waypoint", "0,9,13,0", "--back",
                  "--to", "3", "--out", str(tmp_path)])
    assert exc.value.code == 2


def test_the_settle_wait_is_bounded_by_its_own_budget_not_the_runs(world):
    world.gate_at = 1e9
    world.drive(Travel(polls=1), budget=1200.0)
    settle = [e for e in world.events() if e["event"] == "settle"]
    assert settle[0]["waited"] <= ftr.SETTLE_BUDGET_SECONDS + ftr.POLL_SECONDS


def test_the_settle_wait_is_the_full_budget_when_the_run_budget_is_smaller(world):
    world.gate_at = 1e9
    world.drive(Travel(polls=1), budget=60.0)
    settle = [e for e in world.events() if e["event"] == "settle"]
    assert settle[0]["waited"] >= ftr.SETTLE_BUDGET_SECONDS


def test_settle_start_is_logged_before_the_wait_ends(world):
    world.drive(Travel(polls=1))
    names = [e["event"] for e in world.events()]
    assert names.index("settle_start") < names.index("settle")


def _interrupted_run(monkeypatch, tmp_path, second):
    calls = []

    def fake(*a, **k):
        calls.append(k.get("back", False))
        if len(calls) == 2:
            return second()
        return {"result": "idle", "settled": True}

    monkeypatch.setattr(ftr, "run_trip", fake)
    from automap import amiga, amigafasttravel
    from tools.amiga import amigadrive

    class T:
        def __init__(self, pipe, machine):
            pass

        def locate(self):
            return 1

    monkeypatch.setattr(amiga, "WinuaePipe", _Pipe)
    monkeypatch.setattr(amiga, "AmigaTarget", T)
    monkeypatch.setattr(amigafasttravel, "AmigaFastTravel", lambda key, disks: None)
    monkeypatch.setattr(amigadrive, "shot", lambda *a: None)
    monkeypatch.setattr(ftr.engine, "area_by_id", lambda i, t: SimpleNamespace(id=i, title=t))
    return ["--holder", "h", "--disks", "D", "--to", "3", "--back", "--out", str(tmp_path)]


def test_a_leg_is_printed_when_it_ends_and_an_interrupt_is_logged(monkeypatch, tmp_path, capsys):
    def second():
        raise KeyboardInterrupt

    argv = _interrupted_run(monkeypatch, tmp_path, second)
    with pytest.raises(KeyboardInterrupt):
        ftr.main(argv)
    assert '"result": "idle"' in capsys.readouterr().out
    last = json.loads((tmp_path / "fasttravel.jsonl").read_text().splitlines()[-1])
    assert last["event"] == "interrupted" and last["leg"] == 2


def test_sigterm_exits_143_and_the_old_handler_comes_back(monkeypatch, tmp_path):
    seen = {}

    def second():
        handler = signal.getsignal(signal.SIGTERM)
        seen["installed"] = handler is not signal.SIG_DFL
        handler(signal.SIGTERM, None)

    argv = _interrupted_run(monkeypatch, tmp_path, second)
    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as caught:
        ftr.main(argv)
    assert caught.value.code == 143 and seen["installed"]
    assert signal.getsignal(signal.SIGTERM) is before
