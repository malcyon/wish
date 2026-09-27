"""The camp transition waits for the camp bar itself, not a fixed settle (#621).

`tools/c64/traitask.py`'s `open_items()` used to select ENCAMP, `sess.settle(2)`,
then try `select_bar("VIEW")` -- at most about 22 seconds before giving up.
`VIEW` is on the world bar as well as the camp bar, so nothing checked whether
CAMP had actually loaded. On a slot with no JiffyDOS the `CAMP` overlay can
take longer than that, and the driver tried `VIEW` on the still-showing world
bar and failed with "VIEW could not be selected in camp" -- a false negative
in the driver, not a game refusal (`~/.cache/wish/acceptance/621/
e5edca2eb2-gauntlets-live/`).

Nothing here needs an emulator: `FakeSession` and `FakeLog` are fixed answers,
the pattern `tests/c64/test_savecheck_move_subbar.py` uses.
"""

from __future__ import annotations

from tools.c64 import session as S
from tools.c64 import traitask
from tools.c64.runlog import Log

WORLD_BAR = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"
CHARACTER = "ROLAND"


class FakeScreen:
    def __init__(self, row24: str):
        self.row24 = row24

    def row(self, r: int) -> str:
        if r == 0:
            return " " * S.PARTY_COLUMN + CHARACTER
        if r == 1:
            return CHARACTER
        if r == 24:
            return self.row24
        return ""

    def rows(self):
        return [self.row(r) for r in range(25)]

    def text(self) -> str:
        return "\n".join(self.rows())

    def contains(self, needle: str) -> bool:
        return needle in self.row24


class FakeLog(Log):
    def __init__(self):
        self.said: list[str] = []
        self.emitted: list[tuple[str, dict]] = []

    def say(self, *a) -> None:
        self.said.append(" ".join(str(x) for x in a))

    def emit(self, kind, **kw) -> None:
        self.emitted.append((kind, kw))


class FakeSession:
    """Answers `select_bar` and `wait_text` the way a real `Session` would,
    with the camp bar's arrival controlled by the test."""

    def __init__(self, camp_appears: bool):
        self.camp_appears = camp_appears
        self.current_bar = WORLD_BAR
        self.select_bar_calls: list[str] = []
        self.wait_text_calls: list[tuple[object, float]] = []
        self.settle_calls = 0

    def select_party(self, at: int) -> bool:
        return True

    def screen(self):
        return FakeScreen(self.current_bar)

    def party_rows(self, s):
        return [0]

    def select_bar(self, label: str, timeout: float = 20.0) -> bool:
        self.select_bar_calls.append(label)
        if label == "VIEW":
            # `wait_sheet_bar` reads the screen directly rather than through
            # `wait_text`, so the fake screen has to show the sheet's own bar
            # once VIEW is chosen, the way the real game would.
            self.current_bar = S.SHEET_BAR + "ITEMS SPELLS TRADE DROP EXIT"
        return True

    def wait_text(self, needle, timeout: float = 180.0):
        self.wait_text_calls.append((needle, timeout))
        if needle == traitask.CAMP_BAR:
            if not self.camp_appears:
                return None, None
            self.current_bar = traitask.CAMP_BAR
            return needle, FakeScreen(self.current_bar)
        # The sheet bar and the item label: always up once the camp bar is.
        return needle, FakeScreen(self.current_bar)

    def settle(self, seconds: float = 6.0) -> None:
        self.settle_calls += 1

    def leave_sheet(self) -> None:
        pass


def test_open_items_waits_for_the_camp_bar_before_trying_view():
    """`VIEW` is only selected after the camp bar has actually appeared."""
    sess = FakeSession(camp_appears=True)
    log = FakeLog()

    ok = traitask.open_items(sess, log, CHARACTER, "CLOAK", "ready")

    assert ok is True
    assert sess.select_bar_calls[0] == "ENCAMP"
    # The camp-bar wait sits strictly between the ENCAMP select and the VIEW
    # select -- proof the driver checks readiness rather than guessing.
    assert sess.select_bar_calls[1] == "VIEW"
    needles = [n for n, _t in sess.wait_text_calls]
    assert traitask.CAMP_BAR in needles
    camp_wait_timeout = next(t for n, t in sess.wait_text_calls
                             if n == traitask.CAMP_BAR)
    assert camp_wait_timeout >= 90


def test_open_items_fails_cleanly_when_the_camp_bar_never_appears():
    """No camp bar within the timeout: `VIEW` is never tried, and the driver
    reports why instead of pressing on against the wrong screen."""
    sess = FakeSession(camp_appears=False)
    log = FakeLog()

    ok = traitask.open_items(sess, log, CHARACTER, "CLOAK", "ready")

    assert ok is False
    assert "ENCAMP" in sess.select_bar_calls
    assert "VIEW" not in sess.select_bar_calls
    assert any("camp bar never appeared" in s for s in log.said)


def test_ready_capture_keeps_the_first_blank_row_and_the_returned_list(monkeypatch):
    """One fire can blank the target row before the unchanged list returns."""
    monkeypatch.setattr(traitask.time, "sleep", lambda _: None)

    class ItemScreen:
        def __init__(self, target):
            self.target = target
            self.colours = bytearray([5] * 1000)
            self.colours[6 * 40 + traitask.ITEM_NAME_COLUMN] = 1

        def row(self, n):
            return {5: " NO CLOAK", 6: self.target, 7: " NO BOOTS",
                    24: "READY TRADE DROP EXIT"}.get(n, "")

        def rows(self):
            return [self.row(n) for n in range(25)]

    listed = ItemScreen("YES GAUNTLETS OF OGRE POWER")
    blank = ItemScreen("")

    class Session:
        def __init__(self):
            self.keys = []
            self.kbd = self
            self.screens = iter((listed, None, blank, listed, listed))

        def screen(self):
            return listed

        def key(self, name, *timing):
            self.keys.append(name)

    sess = Session()
    checkpoints = []

    def sample(stage, predicate):
        screen = next(sess.screens)
        if stage is not None and predicate(screen):
            checkpoints.append((stage, screen.row(6), tuple(sess.keys)))
        return screen

    log = FakeLog()
    flipped = traitask.toggle_item(
        sess, log, "GAUNTLETS", "ready", sample=sample)

    assert flipped is True  # Existing screen-change report; no state claim.
    assert next(kw for kind, kw in log.emitted if kind == "screen"
                and kw["tag"] == "ready-after")["screen_changed"] is True
    assert sess.keys == ["KP_0"]
    assert [(stage, row) for stage, row, _ in checkpoints] == [
        ("before", "YES GAUNTLETS OF OGRE POWER"),
        ("change", ""),
        ("stable", "YES GAUNTLETS OF OGRE POWER"),
    ]
    assert checkpoints[0][2] == ()
    assert all(keys == ("KP_0",) for _, _, keys in checkpoints[1:])

    stuck = Session()
    stuck.screens = iter([listed, *([blank] * 20), blank])
    stuck_stages = []

    def stuck_sample(stage, predicate):
        screen = next(stuck.screens)
        if stage is not None and predicate(screen):
            stuck_stages.append(stage)
        return screen

    assert traitask.toggle_item(
        stuck, FakeLog(), "GAUNTLETS", "ready", sample=stuck_sample) is True
    assert stuck.keys == ["KP_0"]
    assert stuck_stages == ["before", "change", "timeout"]

    changed = ItemScreen(" NO GAUNTLETS OF OGRE POWER")

    class NormalSession(Session):
        def __init__(self):
            super().__init__()
            self.screens = iter((listed, listed, changed))

        def screen(self):
            return next(self.screens, changed)

    normal = NormalSession()
    assert traitask.toggle_item(normal, FakeLog(), "GAUNTLETS", "ready") is True
    assert normal.keys == ["KP_0"]
