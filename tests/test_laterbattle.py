"""`ssb_fight`'s `--goto` tour, and the budget arithmetic it keeps.

`#554 (laterbattle.py's --goto tour charges a leg its whole step allowance, so
a run's budget is a fiction and the walk falls through into the pattern
walker)`. `Run.goto` (`tools/cursethac0.py`) returns as soon as it arrives at
its target -- it can take far fewer than the `budget` steps it was given --
and the tour loop used to add the whole `budget` to `spent` regardless, which
both misreports how far the party actually walked and can end the tour before
its real step count is spent.
"""
from __future__ import annotations

import io
import sys
from types import SimpleNamespace

sys.path.insert(0, ".")

from tools import cursethac0, ssbwarp  # noqa: E402
from tools.c64 import laterbattle  # noqa: E402


class FakeGotoRun(laterbattle.Battle):
    """A `Battle` whose machine-facing methods are all stubs.

    Bypasses `Battle.__init__` the way `test_cursethac0.py`'s
    `FakeCombatRun` bypasses `Run.__init__`: nothing here needs a real
    session, a real slot or a real log file.
    """

    def __init__(self, arrives_after: int):
        self.file = io.StringIO()
        self.quiet = True
        self.sess = SimpleNamespace(save_disk=None)
        self.slot = SimpleNamespace(dir="/tmp/fake-slot")
        self.last_goto_steps = 0
        self._arrives_after = arrives_after
        self._goto_calls = 0
        self.goto_budgets: list[int] = []
        self.records: list[dict] = []

    # -- the thing under test: how many steps a leg actually took ---------

    def goto(self, target, budget=60, geo=None, accept=False) -> bool:
        self._goto_calls += 1
        self.goto_budgets.append(budget)
        # Just as the real `Run.goto` does: arrive in fewer steps than the
        # budget allows, and record the real count on the run.
        self.last_goto_steps = min(self._arrives_after, budget)
        return True

    def in_combat(self) -> bool:
        # A fight is "found" the moment the first leg has been walked, so the
        # tour loop stops there rather than falling into the pattern walker
        # this test has no interest in.
        return self._goto_calls >= 1

    # -- everything else ssb_fight touches, all inert ----------------------

    def row24(self) -> str:
        return ""

    def triple(self):
        return (0, 0, 0)

    def dump(self, tag):
        return []

    def probe(self, stage):
        return {}

    def log(self, kind, **kw):
        kw["kind"] = kind
        self.records.append(kw)


def test_ssb_fight_charges_the_real_steps_a_leg_took(monkeypatch):
    """A leg that arrives in 17 of a 45-step allowance charges 17, not 45."""
    monkeypatch.setattr(ssbwarp, "stage", lambda *a, **k: "boot")
    monkeypatch.setattr(
        ssbwarp, "SSBSession",
        lambda *a, **k: SimpleNamespace(save_disk=None, boot=lambda: True))
    monkeypatch.setattr(ssbwarp, "load_party", lambda sess: True)
    monkeypatch.setattr(ssbwarp, "Addresses", lambda *a, **k: None)
    monkeypatch.setattr(ssbwarp, "enter_world", lambda *a, **k: True)
    monkeypatch.setattr(cursethac0, "area_geo",
                        lambda save, disks: ("AREA00", "GEO00"))

    run = FakeGotoRun(arrives_after=17)
    args = SimpleNamespace(save="dummy.d64", world=1.0, goto="5,5",
                           laps=45, steps=60, accept=False,
                           pattern="IIIKIIIJ")

    rc = laterbattle.ssb_fight(run, args, disks="dummy-disks")

    assert rc == 0
    assert run.goto_budgets == [45]          # the leg was still offered 45
    goto_records = [r for r in run.records if r["kind"] == "goto"]
    assert len(goto_records) == 1
    assert goto_records[0]["spent"] == 17    # but only 17 were actually spent
