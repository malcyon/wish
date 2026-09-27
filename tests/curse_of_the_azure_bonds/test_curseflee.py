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


class FakeSession:
    """Enough of `CurseSession` for `curseflee.run` to drive without a machine."""

    def __init__(self):
        self.fight_calls: list[dict] = []

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
                                 "poll": poll})
        return S.FightResult("FLEE", 1, 1.0, {}, [], 0, [])

    class kbd:
        @staticmethod
        def screenshot(path):
            pass

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
    """`run()`'s combat-floor wait mirrors `laterbattle.main`'s own: a
    `waiting-for-combat` line every iteration and a `combat-floor` dump once
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
    assert ("dump", "combat-floor") in calls
    # the dump comes after the waits, matching `laterbattle.main`'s order
    assert calls.index(("dump", "combat-floor")) > calls.index(
        ("waiting-for-combat", waits[-1]))
