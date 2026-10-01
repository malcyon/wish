"""`curseflee.py` reaches its fight through `laterbattle.curse_fight`, not a fixed walk.

`#648 (See THE PARTY RUNS AWAY on a Curse or Silver Blades screen, and confirm
the mercy heal on the losing side of a fight)`: the fixed walk from
`cited/131-m1/CURSEI.D64` never met a fight, and a `poll=1.0` `Session.fight`
misses the flee line, which is up for under half a second. Both are stubbed
here rather than driven live, because this file's job is a pool slot and a
running emulator -- what is checked is that `run()` calls `laterbattle.curse_fight`
to reach the fight and hands `Session.fight` a fast enough poll, not that the
emulator actually produces one.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

sys.path.insert(0, ".")

from tools.c64 import laterbattle  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.curse_of_the_azure_bonds import curseflee  # noqa: E402


class FakeSlot:
    def __init__(self):
        self.n = 1
        self.display = ":1"
        self.dir = "/tmp/fake-slot"

    def teardown(self):
        pass

    def release(self):
        pass


class Machine:
    """The state behind every `FakeMon` connection of one run."""

    def __init__(self):
        self.mem = {curseflee.RESULT: 0, curseflee.MERCY: 0}
        self.status = [1] * 6
        self.checkpoints: dict[int, dict] = {}
        self.hits: dict[int, int] = {}
        self.next_cp = 1
        self.stop_answers = True      # False: wait_stopped times out
        self.stopped_pc = curseflee.LINE_DRAWN
        self.cleared = 0
        self.fight_over = False
        self.calls: list[str] = []    # checkpoint_set and resume, in order
        self.mon_fails = False        # a connection that raises on peek

    def write_result(self, value):
        """POST.COM's `STX $7EC7` under a stop-on-store checkpoint."""
        self.mem[curseflee.RESULT] = value
        self.calls.append("write")
        for n, cp in self.checkpoints.items():
            if cp["store"] and cp["start"] == curseflee.RESULT:
                self.hits[n] = self.hits.get(n, 0) + 1


class FakeMon:
    def __init__(self, machine):
        self.m = machine

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.m.calls.append("exit")
        return False

    def read(self, start, length, bank=0):
        if start == curseflee.ROSTER:
            blob = bytearray(length)
            for i, v in enumerate(self.m.status):
                blob[i * 0x20] = v
            return bytes(blob)
        return bytes(self.m.mem.get(start + i, 0) for i in range(length))

    def peek(self, addr, bank=0):
        if self.m.mon_fails and self.m.fight_over:
            raise OSError("monitor gone")
        return self.read(addr, 1)[0]

    def checkpoint_set(self, start, end=None, *, load=False, store=False,
                       exec_=False, stop=True, temporary=False):
        n = self.m.next_cp
        self.m.next_cp += 1
        self.m.checkpoints[n] = {"start": start, "store": store,
                                 "exec": exec_, "stop": stop,
                                 "temporary": temporary}
        self.m.calls.append("checkpoint_set")
        return n

    def checkpoint_hits(self, n):
        return self.m.hits.get(n, 0)

    def checkpoints_clear(self):
        self.m.cleared += 1
        n = len(self.m.checkpoints)
        self.m.checkpoints.clear()
        return n

    def resume(self):
        self.m.calls.append("resume")

    def hang_up(self):
        self.m.calls.append("hang_up")

    def wait_stopped(self, timeout=20.0):
        return self.m.stopped_pc if self.m.stop_answers else None


class FakeLog:
    def __init__(self):
        self.events = []
        self.said = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def say(self, text):
        self.said.append(text)

    def kinds(self, kind):
        return [kw for k, kw in self.events if k == kind]


class FakeScreen:
    def __init__(self, rows):
        self.rows = rows

    def row(self, r):
        return self.rows[r] if r < len(self.rows) else ""


class FakeSession:
    """Enough of `CurseSession` for `curseflee.run` to drive without a machine."""

    def __init__(self, machine=None):
        self.fight_calls: list[dict] = []
        self.machine = machine or Machine()

    def mon(self, timeout=5.0):
        return FakeMon(self.machine)

    def fight_hook(self):
        pass

    def screen(self):
        return None

    def combat_state(self, s=None):
        return SimpleNamespace(kind="", text="")

    def press_kernal(self, code):
        pass

    def settle(self, secs):
        pass

    def battle(self):
        return None

    def mode(self):
        return 0

    def fight(self, budget, tactic=None, poll=1.0):
        self.fight_calls.append({"budget": budget, "tactic": tactic,
                                 "poll": poll,
                                 "armed": [dict(cp) for cp in
                                          self.machine.checkpoints.values()]})
        self.fight_hook()
        self.machine.fight_over = True
        return S.FightResult("FLEE", 1, 1.0, {}, [], 0, [])

    class kbd:
        @staticmethod
        def screenshot(path, timeout=None):
            return True

    def close(self):
        pass


def make_args(tmp_path, poll=0.12):
    return SimpleNamespace(
        disks="dummy-disks", save="dummy.d64", slot=None, budget=900.0,
        poll=poll, steps=60, world=240.0, look=8.0, wait=1, accept=False,
        out=str(tmp_path / "out"), quiet=True)


def test_run_reaches_the_fight_through_curse_fight_not_a_fixed_walk(
        tmp_path, monkeypatch):
    """`run()` calls `laterbattle.curse_fight` rather than walking a pattern."""
    sess = FakeSession()
    calls = []

    def fake_curse_fight(battle, args, disks):
        calls.append((battle, args, disks))
        battle.sess = sess
        return 0

    monkeypatch.setattr(laterbattle, "curse_fight", fake_curse_fight)
    monkeypatch.setattr(laterbattle.Battle, "__init__",
                         lambda self, out, quiet: None)
    monkeypatch.setattr(laterbattle.Battle, "log", lambda self, *a, **k: None)
    monkeypatch.setattr(laterbattle.Battle, "dump", lambda self, *a, **k: None)
    monkeypatch.setattr(laterbattle.Battle, "in_combat", lambda self: True)
    monkeypatch.setattr(S, "claim_slot", lambda *a, **k: FakeSlot())

    rc = curseflee.run(make_args(tmp_path))

    assert rc == 0
    assert len(calls) == 1                       # curse_fight reached the fight
    assert calls[0][2] == "dummy-disks"


def test_run_polls_fast_enough_to_catch_the_flee_line(tmp_path, monkeypatch):
    """`Session.fight` is called with `poll=0.12`, not `fight`'s own `1.0` default."""
    sess = FakeSession()

    def fake_curse_fight(battle, args, disks):
        battle.sess = sess
        return 0

    monkeypatch.setattr(laterbattle, "curse_fight", fake_curse_fight)
    monkeypatch.setattr(laterbattle.Battle, "__init__",
                         lambda self, out, quiet: None)
    monkeypatch.setattr(laterbattle.Battle, "log", lambda self, *a, **k: None)
    monkeypatch.setattr(laterbattle.Battle, "dump", lambda self, *a, **k: None)
    monkeypatch.setattr(laterbattle.Battle, "in_combat", lambda self: True)
    monkeypatch.setattr(S, "claim_slot", lambda *a, **k: FakeSlot())

    rc = curseflee.run(make_args(tmp_path))

    assert rc == 0
    assert len(sess.fight_calls) == 1
    assert sess.fight_calls[0]["poll"] == 0.12


def test_run_logs_each_wait_iteration_and_dumps_the_combat_floor(
        tmp_path, monkeypatch):
    """`run()`'s combat-arena wait mirrors `laterbattle.main`'s own: a
    `waiting-for-combat` line every iteration and a `combat-arena` dump once
    the loop ends, so a run that fails here still says what row 24 and the
    mode byte showed (review finding on `#648`)."""
    sess = FakeSession()

    def fake_curse_fight(battle, args, disks):
        battle.sess = sess
        return 0

    calls = []
    in_combat_after = 2
    state = {"n": 0}

    def fake_in_combat(self):
        state["n"] += 1
        return state["n"] > in_combat_after

    monkeypatch.setattr(laterbattle, "curse_fight", fake_curse_fight)
    monkeypatch.setattr(laterbattle.Battle, "__init__",
                         lambda self, out, quiet: None)
    monkeypatch.setattr(laterbattle.Battle, "log",
                         lambda self, kind, **kw: calls.append((kind, kw)))
    monkeypatch.setattr(laterbattle.Battle, "dump",
                         lambda self, tag: calls.append(("dump", tag)))
    monkeypatch.setattr(laterbattle.Battle, "in_combat", fake_in_combat)
    monkeypatch.setattr(S, "claim_slot", lambda *a, **k: FakeSlot())

    args = make_args(tmp_path)
    args.wait = 5
    rc = curseflee.run(args)

    assert rc == 0
    waits = [kw for kind, kw in calls if kind == "waiting-for-combat"]
    assert len(waits) == in_combat_after
    assert all("mode" in kw and "row24" in kw and "bar" in kw
               and "readable" in kw for kw in waits)
    assert ("dump", "combat-arena") in calls
    # the dump comes after the waits, matching `laterbattle.main`'s order
    assert calls.index(("dump", "combat-arena")) > calls.index(
        ("waiting-for-combat", waits[-1]))


# -- the trap on the result byte (#648) --------------------------------------


def stage(tmp_path, monkeypatch, hook=None, machine=None):
    """Run `curseflee.run` on a fake session whose fight calls `hook`."""
    sess = FakeSession(machine)
    if hook is not None:
        sess.fight_hook = lambda: hook(sess)

    monkeypatch.setattr(laterbattle, "curse_fight",
                        lambda battle, args, disks: setattr(
                            battle, "sess", sess) or 0)
    monkeypatch.setattr(laterbattle.Battle, "__init__",
                        lambda self, out, quiet: None)
    monkeypatch.setattr(laterbattle.Battle, "log", lambda self, *a, **k: None)
    monkeypatch.setattr(laterbattle.Battle, "dump", lambda self, *a, **k: None)
    monkeypatch.setattr(laterbattle.Battle, "in_combat", lambda self: True)
    monkeypatch.setattr(S, "claim_slot", lambda *a, **k: FakeSlot())
    events = []
    monkeypatch.setattr(curseflee.Log, "emit",
                        lambda self, kind, **kw: events.append((kind, kw)))
    return sess, events


def of(events, kind):
    return [kw for k, kw in events if k == kind]


def test_result_and_party_status_are_read_and_logged_after_the_fight(
        tmp_path, monkeypatch):
    m = Machine()
    m.mem[curseflee.RESULT] = 0x80
    m.status = [0x86, 1, 0, 0, 0, 0]
    sess, events = stage(tmp_path, monkeypatch, machine=m)

    assert curseflee.run(make_args(tmp_path)) == 0

    (got,) = of(events, "outcome_bytes")
    assert got == {"result": 0x80, "mercy": 0, "status": [0x86, 1, 0, 0, 0, 0]}


def test_the_write_checkpoint_is_set_before_the_fight_and_cleared_in_finally(
        tmp_path, monkeypatch):
    sess, _ = stage(tmp_path, monkeypatch)

    assert curseflee.run(make_args(tmp_path)) == 0

    armed = sess.fight_calls[0]["armed"]
    assert len(armed) == 1
    assert armed[0]["start"] == curseflee.RESULT
    assert armed[0]["store"] and armed[0]["stop"] and not armed[0]["exec"]
    assert sess.machine.cleared == 1
    assert sess.machine.checkpoints == {}
    assert sess.mon.__func__ is FakeSession.mon      # the wrapper is gone too


def test_the_checkpoint_is_cleared_when_the_fight_raises(tmp_path, monkeypatch):
    def boom(sess):
        raise RuntimeError("fight blew up")

    sess, _ = stage(tmp_path, monkeypatch, hook=boom)

    assert curseflee.run(make_args(tmp_path)) == 1
    assert sess.machine.cleared == 1


def test_a_ran_away_write_adds_the_line_drawn_stop_and_saves_the_screen(
        tmp_path, monkeypatch):
    seen_rows = [""] * 10 + ["   THE PARTY RUNS AWAY"]
    monkeypatch.setattr(curseflee, "read_screen",
                        lambda m: FakeScreen(seen_rows))
    shots = []

    def flee(sess):
        sess.machine.status = [0x86, 0x86, 0x86, 0x86, 0x86, 0]
        sess.machine.write_result(0x81)
        with sess.mon(5):                    # the fight's next screen read
            pass
        sess.machine.status = [1, 1, 1, 1, 1, 0]      # the drop loop runs

    sess, events = stage(tmp_path, monkeypatch, hook=flee)
    sess.kbd = SimpleNamespace(
        screenshot=lambda path, timeout=None: shots.append(path) or True)
    sess.machine.mem[curseflee.RESULT] = 0x81

    assert curseflee.run(make_args(tmp_path)) == 0

    out = tmp_path / "out"
    assert "THE PARTY RUNS AWAY" in (out / "ran-line.txt").read_text()
    (line,) = of(events, "outcome_line")
    assert line["seen"] and line["pc"] == curseflee.LINE_DRAWN
    assert str(out / "outcome-line.png") in shots
    (flee_ev,) = of(events, "flee")
    assert flee_ev["escaped"] == 5 and flee_ev["escaped_from"] == "write"


def test_the_line_drawn_stop_is_not_set_for_a_result_other_than_81(
        tmp_path, monkeypatch):
    def lose(sess):
        sess.machine.write_result(0x80)
        with sess.mon(5):
            pass

    sess, events = stage(tmp_path, monkeypatch, hook=lose)

    assert curseflee.run(make_args(tmp_path)) == 0

    assert of(events, "result_write")[0]["value"] == 0x80
    assert of(events, "outcome_line") == []
    assert not (tmp_path / "out" / "ran-line.txt").exists()


def test_the_line_drawn_stop_is_not_armed_before_the_write(
        tmp_path, monkeypatch):
    """`$091C` is a `COMBAT` address as well; only a `$81` write may arm it."""
    sess, _ = stage(tmp_path, monkeypatch)

    curseflee.run(make_args(tmp_path))

    assert not any(cp["exec"] for cp in sess.fight_calls[0]["armed"])


def test_the_line_drawn_stop_is_one_shot_and_stops_the_machine(
        tmp_path, monkeypatch):
    monkeypatch.setattr(curseflee, "read_screen", lambda m: FakeScreen([]))
    seen = {}

    def flee(sess):
        sess.machine.write_result(0x81)
        with sess.mon(5):
            seen.update(sess.machine.checkpoints)

    sess, _ = stage(tmp_path, monkeypatch, hook=flee)
    sess.machine.mem[curseflee.RESULT] = 0x81

    curseflee.run(make_args(tmp_path))

    (stop,) = [cp for cp in seen.values() if cp["exec"]]
    assert stop["start"] == curseflee.LINE_DRAWN
    assert stop["stop"] and stop["temporary"]


def test_a_monitor_that_stops_answering_falls_back_to_the_hit_count(
        tmp_path, monkeypatch):
    def flee(sess):
        sess.machine.stop_answers = False
        sess.machine.status = [0x86, 0x86, 0, 0, 0, 0]
        sess.machine.write_result(0x81)
        with sess.mon(5):
            pass

    sess, events = stage(tmp_path, monkeypatch, hook=flee)
    sess.machine.mem[curseflee.RESULT] = 0x81

    assert curseflee.run(make_args(tmp_path)) == 0

    assert not (tmp_path / "out" / "ran-line.txt").exists()
    assert of(events, "trap_failed")
    (proof,) = of(events, "line_printed_not_seen")
    assert proof["hits"] == 1
    assert of(events, "outcome_bytes")               # step 1 still ran


def test_escapes_are_counted_from_the_status_byte_not_from_got_away(
        tmp_path, monkeypatch):
    def flee(sess):
        sess.machine.status = [0x86, 0x86, 0x86, 0, 0, 0]
        sess.machine.write_result(0x81)
        with sess.mon(5):
            pass
        sess.machine.status = [1, 1, 1, 0, 0, 0]      # the drop loop

    monkeypatch.setattr(curseflee, "read_screen", lambda m: FakeScreen([]))
    sess, events = stage(tmp_path, monkeypatch, hook=flee)
    sess.machine.mem[curseflee.RESULT] = 0x81
    # Flight saw one `GOT AWAY`; the bytes say three.
    monkeypatch.setattr(curseflee, "Flight",
                        lambda log: SimpleNamespace(
                            attempts=1, got_away={"MATHEW": 1},
                            failed={}))

    assert curseflee.run(make_args(tmp_path)) == 0

    (ev,) = of(events, "flee")
    assert ev["escaped"] == 3 and ev["got_away"] == {"MATHEW": 1}


def calls_after_write(machine):
    return machine.calls[machine.calls.index("write") + 1:]


def test_the_screenshot_is_grabbed_inside_capture_with_a_timeout(
        tmp_path, monkeypatch):
    monkeypatch.setattr(curseflee, "read_screen", lambda m: FakeScreen([]))
    grabs = []

    def flee(sess):
        sess.machine.write_result(0x81)
        with sess.mon(5):
            pass

    sess, events = stage(tmp_path, monkeypatch, hook=flee)
    sess.machine.mem[curseflee.RESULT] = 0x81
    sess.kbd = SimpleNamespace(screenshot=lambda path, timeout=None: (
        sess.machine.calls.append("shot"), grabs.append(timeout), True)[-1])

    assert curseflee.run(make_args(tmp_path)) == 0

    after = calls_after_write(sess.machine)
    assert after.index("shot") < after.index("hang_up")   # not after the hang-up
    assert grabs[0] == 10          # the capture grab; outcome.png follows
    assert of(events, "shot_failed") == []


def test_a_refused_screenshot_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(curseflee, "read_screen", lambda m: FakeScreen([]))

    def flee(sess):
        sess.machine.write_result(0x81)
        with sess.mon(5):
            pass

    sess, events = stage(tmp_path, monkeypatch, hook=flee)
    sess.machine.mem[curseflee.RESULT] = 0x81
    sess.kbd = SimpleNamespace(screenshot=lambda path, timeout=None: False)

    assert curseflee.run(make_args(tmp_path)) == 0

    assert of(events, "shot_failed")
    assert of(events, "outcome_line")


def test_a_stop_away_from_the_line_drawn_address_is_a_wrong_stop(
        tmp_path, monkeypatch):
    monkeypatch.setattr(curseflee, "read_screen",
                        lambda m: FakeScreen(["THE PARTY RUNS AWAY"]))

    def flee(sess):
        sess.machine.write_result(0x81)
        with sess.mon(5):
            pass

    m = Machine()
    m.stopped_pc = 0x0909
    sess, events = stage(tmp_path, monkeypatch, hook=flee, machine=m)
    m.mem[curseflee.RESULT] = 0x81

    assert curseflee.run(make_args(tmp_path)) == 0

    (wrong,) = of(events, "wrong_stop")
    assert wrong["pc"] == 0x0909
    assert of(events, "outcome_line") == []
    assert not (tmp_path / "out" / "ran-line.txt").exists()
    assert of(events, "line_printed_not_seen")


def test_every_checkpoint_set_and_every_stop_is_followed_by_a_resume(
        tmp_path, monkeypatch):
    monkeypatch.setattr(curseflee, "read_screen", lambda m: FakeScreen([]))

    def flee(sess):
        sess.machine.write_result(0x81)
        with sess.mon(5):
            pass

    sess, _ = stage(tmp_path, monkeypatch, hook=flee)
    sess.machine.mem[curseflee.RESULT] = 0x81

    assert curseflee.run(make_args(tmp_path)) == 0

    calls = [c for c in sess.machine.calls
             if c in ("checkpoint_set", "resume", "hang_up")]
    # arm: set, hang up.  the `$81` hit: set the `$091C` stop, resume, then
    # (stopped there) resume again.
    assert calls[:2] == ["checkpoint_set", "hang_up"]
    after = calls_after_write(sess.machine)
    # stopped at `$091C`: a resume is issued before the connection closes
    assert after[:4] == ["checkpoint_set", "resume", "resume", "hang_up"]
    for i, c in enumerate(calls[2:], 2):
        if c == "checkpoint_set":
            assert calls[i + 1] == "resume"


def test_a_store_hit_that_is_not_81_resumes_the_machine(tmp_path, monkeypatch):
    def lose(sess):
        sess.machine.write_result(0x80)
        with sess.mon(5):
            pass

    sess, _ = stage(tmp_path, monkeypatch, hook=lose)

    assert curseflee.run(make_args(tmp_path)) == 0

    after = calls_after_write(sess.machine)
    assert after.index("resume") < after.index("hang_up")


def test_an_81_already_in_the_byte_without_a_store_hit_does_not_capture(
        tmp_path, monkeypatch):
    def idle(sess):
        with sess.mon(5):
            pass

    sess, events = stage(tmp_path, monkeypatch, hook=idle)
    sess.machine.mem[curseflee.RESULT] = 0x81      # left by an earlier fight

    assert curseflee.run(make_args(tmp_path)) == 0

    assert of(events, "result_write") == []
    assert not any(cp["exec"] for cp in sess.fight_calls[0]["armed"])
    assert [c for c in sess.machine.calls if c == "checkpoint_set"] == [
        "checkpoint_set"]                          # only the arming store


def test_a_degraded_trap_says_the_store_checkpoint_stays_armed(
        tmp_path, monkeypatch):
    said = []
    monkeypatch.setattr(curseflee.Log, "say",
                        lambda self, text, *a, **k: said.append(text))

    def flee(sess):
        sess.machine.stop_answers = False
        sess.machine.write_result(0x81)
        with sess.mon(5):
            pass

    sess, events = stage(tmp_path, monkeypatch, hook=flee)
    sess.machine.mem[curseflee.RESULT] = 0x81

    assert curseflee.run(make_args(tmp_path)) == 0

    assert any("stays armed" in t for t in said)


def test_a_monitor_failure_after_the_fight_falls_back_to_the_write_status(
        tmp_path, monkeypatch):
    monkeypatch.setattr(curseflee, "read_screen", lambda m: FakeScreen([]))

    def flee(sess):
        sess.machine.status = [0x86, 0x86, 0x86, 0x86, 0, 0]
        sess.machine.write_result(0x81)
        with sess.mon(5):
            pass

    m = Machine()
    m.mon_fails = True
    sess, events = stage(tmp_path, monkeypatch, hook=flee, machine=m)
    m.mem[curseflee.RESULT] = 0x81

    assert curseflee.run(make_args(tmp_path)) == 0

    assert of(events, "outcome_failed")
    assert of(events, "outcome_bytes") == []
    (ev,) = of(events, "flee")
    assert ev["escaped"] == 4 and ev["escaped_from"] == "write"


def test_a_store_that_lands_during_a_connection_is_read_before_its_exit(tmp_path):
    sess = FakeSession()
    trap = curseflee.Trap(sess, FakeLog(), tmp_path)
    trap.arm()
    with sess.mon(5):
        sess.machine.write_result(0x80)
    assert trap.result == 0x80
    # Handled with the machine still stopped: no resume between write and the hang-up.
    assert sess.machine.calls[-2:] == ["write", "hang_up"]


def test_a_check_that_fails_resumes_the_machine_before_the_hang_up(tmp_path):
    sess = FakeSession()
    trap = curseflee.Trap(sess, FakeLog(), tmp_path)
    trap.arm()
    sess.machine.mon_fails = sess.machine.fight_over = True
    sess.machine.write_result(0x80)
    with sess.mon(5):
        pass
    assert trap.degraded
    assert sess.machine.calls[-2:] == ["resume", "hang_up"]
