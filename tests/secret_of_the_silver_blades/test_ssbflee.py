"""`ssbflee.fight` swaps `Flight` in for `melee_turn` behind `--flee`, at a fast poll.

The flee line is up for under half a second, so `Session.fight` has to poll at
0.12 rather than its own 1.0. The session is a fake that records what `fight`
was called with, and `reach_fight` runs against fakes of the session and run.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from tools.c64 import session as S  # noqa: E402
from tools.pool_of_radiance.fleedrive import Flight  # noqa: E402
from tools.secret_of_the_silver_blades import ssbarm16fight as arm16  # noqa: E402
from tools.secret_of_the_silver_blades import ssbflee  # noqa: E402


class FakeSession:
    def __init__(self):
        self.calls = []

    def fight(self, budget, tactic=None, poll=1.0):
        self.calls.append({"budget": budget, "tactic": tactic, "poll": poll})
        return S.FightResult("FLEE", 1, 1.0, [], [], 0, [])


class FakeRun:
    def log(self, *a, **k):
        pass


class FakeLog:
    pass


def parsed(*argv):
    return ssbflee.build_parser().parse_args(list(argv))


def test_flee_hands_fight_a_flight_at_the_fast_poll_by_default():
    sess = FakeSession()
    ssbflee.fight(sess, FakeRun(), parsed("--flee"), FakeLog())
    call = sess.calls[0]
    assert isinstance(call["tactic"], Flight)
    assert call["poll"] == 0.12


def test_without_flee_it_is_the_melee_fight_at_the_melee_poll():
    sess = FakeSession()
    ssbflee.fight(sess, FakeRun(), parsed(), FakeLog())
    call = sess.calls[0]
    assert call["tactic"] is S.Session.melee_turn
    assert call["poll"] == ssbflee.MELEE_POLL
    assert call["budget"] == 300.0


def test_poll_is_honoured_on_both_branches():
    for flags in (("--flee",), ()):
        sess = FakeSession()
        ssbflee.fight(sess, FakeRun(), parsed(*flags, "--poll", "0.5"), FakeLog())
        assert sess.calls[0]["poll"] == 0.5


class Mon:
    def __init__(self, back):
        self.back = back

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def write(self, addr, data):
        pass

    def read(self, addr, n):
        return self.back

    def resume(self):
        pass


class ReachSession:
    def __init__(self, back):
        self.back = back

    def mon(self, timeout):
        return Mon(self.back)

    def mode(self):
        return 1


class ReachRun:
    """A run whose triple after the step and whose combat state are scripted."""

    def __init__(self, after, combat):
        self.after = after
        self.combat = combat
        self.events = []

    def log(self, kind, **k):
        self.events.append(kind)

    def triple(self):
        return self.after

    def press(self, key):
        return True

    def peek(self, addr, n):
        return bytes([0x90])

    def row24(self):
        return ""

    def dump(self, name):
        pass

    def in_combat(self):
        return self.combat


def test_reach_fight_reports_none_when_the_teleport_did_not_take():
    run = ReachRun(arm16.TARGET + (2,), True)
    assert arm16.reach_fight(run, ReachSession(bytes([0, 0, 0]))) is None
    assert run.events[-1] == "escape-hatch"


def test_reach_fight_reports_none_when_the_step_missed_the_square():
    run = ReachRun((15, 11, 2), True)
    assert arm16.reach_fight(run, ReachSession(bytes(arm16.STAGE))) is None
    assert run.events[-1] == "escape-hatch"


def test_reach_fight_reports_true_when_the_floor_is_up():
    run = ReachRun(arm16.TARGET + (2,), True)
    assert arm16.reach_fight(run, ReachSession(bytes(arm16.STAGE))) is True
    assert run.events[-1] == "fight-triggered"


def test_reach_fight_gives_up_after_the_ninety_second_bound(monkeypatch):
    clock = iter(range(0, 10_000, 40))
    monkeypatch.setattr(arm16.time, "time", lambda: next(clock))
    monkeypatch.setattr(arm16.time, "sleep", lambda s: None)
    run = ReachRun(arm16.TARGET + (2,), False)
    assert arm16.reach_fight(run, ReachSession(bytes(arm16.STAGE))) is False
    assert "watch" in run.events
    assert run.events[-1] == "fight-triggered"
