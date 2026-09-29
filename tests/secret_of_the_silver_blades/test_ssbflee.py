"""`ssbflee.fight` swaps `Flight` in for `melee_turn` behind `--flee`, at a fast poll.

`#648 (See THE PARTY RUNS AWAY on a Curse or Silver Blades screen, and confirm
the mercy heal on the losing side of a fight)`: the flee line is up for under
half a second, so `Session.fight` has to poll at 0.12 rather than its own 1.0.
The session is a fake that records what `fight` was called with.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

sys.path.insert(0, ".")

from tools.c64 import session as S  # noqa: E402
from tools.pool_of_radiance.fleedrive import Flight  # noqa: E402
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


def args(flee, poll=ssbflee.FLEE_POLL):
    return SimpleNamespace(flee=flee, poll=poll, budget=300.0)


def test_flee_hands_fight_a_flight_at_the_fast_poll():
    sess = FakeSession()
    ssbflee.fight(sess, FakeRun(), args(True), FakeLog())
    call = sess.calls[0]
    assert isinstance(call["tactic"], Flight)
    assert call["poll"] == 0.12


def test_without_flee_it_is_the_melee_fight_at_the_default_poll():
    sess = FakeSession()
    ssbflee.fight(sess, FakeRun(), args(False), FakeLog())
    call = sess.calls[0]
    assert call["tactic"] is S.Session.melee_turn
    assert call["poll"] == 1.0
    assert call["budget"] == 300.0
