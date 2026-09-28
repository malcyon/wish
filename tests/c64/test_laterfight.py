"""`laterfight.Run.step` judges a step by two agreeing reads of the triple."""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from tools.c64 import laterfight  # noqa: E402
from tools.c64 import session as S  # noqa: E402


class FakeSend:
    """`peek` answers the script in order, then repeats the last."""

    def __init__(self, peeks):
        self.peeks = list(peeks)

    def __call__(self, *words):
        if words[0] == "peek":
            return (self.peeks.pop(0) if len(self.peeks) > 1
                    else self.peeks[0]) + "\n"
        if words[0] == "screen":
            return "\n".join(f"{r:3d} 0 |{'':40}|" for r in range(25))
        return ""


def make_run(peeks):
    run = laterfight.Run.__new__(laterfight.Run)
    run.send = FakeSend(peeks)
    run.screen = lambda: [" " * 40] * 25
    return run


def test_step_is_not_moved_by_one_displaced_before_read(monkeypatch):
    monkeypatch.setattr(S.time, "sleep", lambda _: None)
    run = make_run(["06 0a 00", "01 01 00", "01 01 00", "01 01 00", "01 01 00"])
    assert run.step("I")["moved"] is False


def fake_clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(S.time, "time", lambda: now[0])
    monkeypatch.setattr(S.time, "sleep",
                        lambda s: now.__setitem__(0, now[0] + s))


def moving_peeks():
    """A square that differs on every read, so no two ever agree."""
    return [f"{n:02x} 0a 00" for n in range(1, 400)]


def test_step_with_a_square_that_never_settles_is_not_moved(monkeypatch):
    fake_clock(monkeypatch)
    step = make_run(moving_peeks()).step("I")
    assert step["moved"] is False
    assert step["unsettled"] is True


def test_walk_stops_when_the_square_never_settles(monkeypatch):
    fake_clock(monkeypatch)
    run = make_run(moving_peeks())
    bar = "".join(laterfight.MOVE_BAR.ljust(40))
    run.screen = lambda: [" " * 40] * 24 + [bar]
    run.note = lambda **kw: None
    presses = []
    send = run.send
    run.send = lambda *w: presses.append(w[0]) or send(*w)
    assert laterfight.walk_to_a_fight(run, 20, "I") is None
    assert presses.count("kernal") == 3


def test_step_moved_on_two_agreeing_reads_each_side(monkeypatch):
    """Guard against over-correction: a genuine move still counts."""
    monkeypatch.setattr(S.time, "sleep", lambda _: None)
    run = make_run(["06 0a 00", "06 0a 00", "07 0a 00", "07 0a 00"])
    got = run.step("I")
    assert got["moved"] is True
