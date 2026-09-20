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
