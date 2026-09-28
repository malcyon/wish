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
