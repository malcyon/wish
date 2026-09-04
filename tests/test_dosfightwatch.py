"""`walk_to_encounter`'s patience for a bar it does not recognise.

`#217 (The DOS walk-to-an-encounter gives up on one mid-redraw frame)`: one
captured frame landing on `blank` -- the bar row caught mid-redraw -- gave up
the whole run, where `PoolOfRadiance.fight()` beside it waits for the bar to
become something it knows.  No emulator is needed: `walk_to_encounter` and
`_await_bar` talk to a `PoolOfRadiance` through `step`, `status`, `turn_right`,
`bar_kind` and `s`, so a stand-in for those is enough.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import dosbox, dosfightwatch  # noqa: E402


class _Screen:
    def glyphs(self, rect=None) -> str:
        return "blank-digest"


class _FakeSession:
    def __init__(self):
        self.shots: list[str] = []
        self.pressed: list[str] = []

    def capture(self) -> _Screen:
        return _Screen()

    def shot(self, name: str, allow_blank: bool = False):
        self.shots.append(name)
        return None

    def key(self, *keys, gap=0.0) -> None:
        self.pressed.extend(keys)

    def wait_until_ink(self, rect, same, timeout=30.0) -> bool:
        return True


class _FakePoR:
    """A party that never moves: every step is blocked by whatever bar_kind gives."""

    COMBAT_KEYS = dosbox.PoolOfRadiance.COMBAT_KEYS

    def __init__(self, kinds):
        self._kinds = iter(kinds)
        self._last: str | None = None
        self.s = _FakeSession()
        self.world_bar = "world"

    def status(self) -> str:
        return "status"

    def step(self) -> bool:
        return False

    def turn_right(self) -> bool:
        return True

    def bar_kind(self, screen=None) -> str | None:
        try:
            self._last = next(self._kinds)
        except StopIteration:
            pass
        return self._last


def test_a_frame_caught_mid_redraw_is_not_the_end_of_the_walk():
    """The regression: `blank` seen once and gone is a frame, not a defeat."""
    por = _FakePoR(["blank", "encounter"])
    result = dosfightwatch.walk_to_encounter(por, steps=5, patience=5.0)
    assert result["met"] is True
    assert result["bar"] == "encounter"


def test_a_bar_that_never_resolves_gives_up_after_its_patience():
    """`blank` for ever is a stuck game, and the walk must not sit there long."""
    por = _FakePoR(["blank"] * 10_000)
    started = __import__("time").time()
    result = dosfightwatch.walk_to_encounter(por, steps=5, patience=0.3)
    elapsed = __import__("time").time() - started
    assert result["met"] is False
    assert "blank" in result["why"]
    assert elapsed < 5.0
    assert por.s.shots == ["walk_unknown_bar_blank-digest"]


def test_a_bar_nobody_has_labelled_at_all_still_gives_up_by_its_digest():
    """`bar_kind` returning `None` is a bar not in `COMBAT_BARS` at all."""
    por = _FakePoR([None] * 10)
    result = dosfightwatch.walk_to_encounter(por, steps=5, patience=0.2)
    assert result["met"] is False
    assert result["why"] == "a bar nobody has labelled (None)"
