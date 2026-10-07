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


def test_a_gate_that_never_passes_ends_at_the_budget(world):
    world.gate_at = 1e9
    world.drive(Travel(polls=1), budget=10.0)
    settle = [e for e in world.events() if e["event"] == "settle"]
    assert settle[0]["gate"] is False and settle[0]["waited"] <= 10.0 + ftr.POLL_SECONDS


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
