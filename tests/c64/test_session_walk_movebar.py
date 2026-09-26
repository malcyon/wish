"""A step into a scripted square is not reported as blocked (#275).

`Session.walk_one` insisted on selecting `MOVE` on row 24 before it would
send a direction key.  A square with a script on it -- the training hall was
the one that found this -- answers a step by putting the game back on its
own move sub-bar, `I,J,K,M, RETURN OR BUTTON`, where `MOVE` is already
selected and the word `MOVE` is not on the row at all.  `select_bar("MOVE")`
spent every one of `walk_one`'s four tries failing to find it, and the step
came back `moved: false` on a game that was only waiting for a key.

Nothing here needs an emulator: `FakeSession` is a `Session` whose `screen`,
`status`, `select_bar` and `leave_move` are all fixed answers, so the only
thing under test is `walk_one`'s own choice of what to do with row 24.
"""

from conftest import load_tools_module

S = load_tools_module("session")
Session = S.Session
MOVE_SUBBAR = S.MOVE_SUBBAR


class FakeScreen:
    def __init__(self, row24: str):
        self.row24 = row24

    def row(self, r: int) -> str:
        return self.row24 if r == 24 else ""


class FakeKeyboard:
    def __init__(self):
        self.sent: list[str] = []

    def key(self, name, hold=0.0, gap=0.0):
        self.sent.append(name)


class FakeSession(Session):
    """A `Session` standing at the move sub-bar after a script-interrupted step.

    `select_bar` answers as it would against this exact row -- `False`,
    because `MOVE` is not on it -- so a caller that still asks for it pays the
    same cost the live game did.  `status` changes on the second reading,
    which is what a move that actually lands looks like.
    """

    def __init__(self, row24: str = MOVE_SUBBAR + ", RETURN OR BUTTON"):
        self.kbd = FakeKeyboard()
        self._row24 = row24
        self._statuses = iter([(1, 100, 5, 5), (1, 100, 5, 4)])
        self.select_bar_calls = 0
        self.leave_move_calls = 0

    def indoors(self):
        return True

    def screen(self):
        return FakeScreen(self._row24)

    def status(self):
        return next(self._statuses)

    def select_bar(self, label, row=24, timeout=30.0):
        self.select_bar_calls += 1
        return False

    def leave_move(self, tries=8):
        self.leave_move_calls += 1
        return True


def test_the_move_key_goes_straight_at_an_already_selected_move_bar():
    sess = FakeSession()
    moved = sess.walk_one("I")
    assert moved is True
    assert sess.kbd.sent == ["i"]
    assert sess.select_bar_calls == 0


class NeverSubbarSession(FakeSession):
    """`select_bar` reports `MOVE` taken while row 24 stays the world's bar."""

    def __init__(self):
        super().__init__(row24="MOVE VIEW CAST AREA ENCAMP SEARCH LOOK")

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        return True


def test_walk_one_sends_no_direction_key_before_the_move_subbar(monkeypatch):
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    sess = NeverSubbarSession()
    assert sess.walk_one("K", tries=1) is False
    assert "k" not in sess.kbd.sent
    assert "pressed nothing" in sess.walk_refused


class _Clocked(FakeSession):
    """`select_bar` succeeds; row 24 shows the world bar for `subbar_after`
    reads and `I,J,K,M` after, on a clock only `sleep` moves."""

    def __init__(self, monkeypatch, subbar_after=3, prompt_at=None):
        super().__init__(row24="MOVE VIEW CAST AREA ENCAMP SEARCH LOOK")
        self.now = 0.0
        monkeypatch.setattr(S.time, "sleep", lambda s: setattr(self, "now", self.now + s))
        self.selected = False
        self.reads = 0
        self.subbar_after = subbar_after
        self.prompt_at = prompt_at
        self.seen_at = None
        self.keyed_at = None
        self.attached = []
        self.kbd.key = self._key
        self._statuses = iter([(1, 100, 5, 5), (1, 100, 5, 4)])

    def _key(self, name, hold=0.0, gap=0.0):
        self.kbd.sent.append(name)
        self.keyed_at = self.now

    def wanted_disk(self, s):
        return "SIDE2" if "INSERT SIDE" in s.row(24) else None

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        self.selected = True
        return True

    def screen(self):
        if not self.selected:
            return FakeScreen(self._row24)
        self.reads += 1
        if self.prompt_at is not None and self.reads >= self.prompt_at:
            return FakeScreen("INSERT SIDE # 2, AND PRESS ANY KEY.")
        if self.reads > self.subbar_after:
            if self.seen_at is None:
                self.seen_at = self.now
            return FakeScreen(MOVE_SUBBAR)
        return FakeScreen(self._row24)


def test_a_disk_prompt_that_opens_while_waiting_for_the_subbar_presses_and_answers_nothing(
        monkeypatch):
    sess = _Clocked(monkeypatch, subbar_after=10, prompt_at=4)
    assert sess.walk_one("I", tries=1, answer_prompts=False) is False
    assert sess.kbd.sent == [] and sess.attached == []
    assert sess.walk_prompt == "INSERT SIDE # 2, AND PRESS ANY KEY."
    assert sess.leave_move_calls == 0


def test_the_direction_key_waits_0_6_seconds_after_the_subbar_is_seen(monkeypatch):
    sess = _Clocked(monkeypatch)
    sess.walk_one("I", tries=1)
    assert sess.kbd.sent == ["i"]
    assert sess.keyed_at - sess.seen_at >= 0.6


def test_a_wait_past_the_callers_deadline_presses_nothing_and_says_why(monkeypatch):
    sess = _Clocked(monkeypatch, subbar_after=1000)
    sess.walk_expired = lambda: sess.now >= 1.0
    assert sess.walk_one("I", tries=1) is False
    assert sess.kbd.sent == [] and sess.now < 2.0
    assert "time ran out" in sess.walk_refused
