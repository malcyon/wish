"""A walk that crosses an area boundary is not left `stuck` (#545).

`tools/c64/savecheck.py`'s `answer_bars` recognises the world bar, the boat bar,
`PRESS` and `YES NO` -- not the dungeon's own move sub-bar, `I,J,K,M, RETURN
OR BUTTON`, which `walk_one`'s own docstring (`tools/c64/session.py`) says a
scripted area crossing can leave row 24 showing instead of the world bar.
Nothing on that row matches any of the four checks `answer_bars` already had,
so it spun its full retry budget and reported the walk `stuck`.

`Session.save_game` had the same gap the other way round: asked to resave
right after such a crossing, it pointed `select_bar("ENCAMP")` at the same
sub-bar, which `docs/70-driving-the-game.md` says must never be done, and
timed out.

Nothing here needs an emulator. `FakeScreen` and `FakeSession` are fixed
answers, the same pattern `tests/test_session_walk_movebar.py` and
`tests/test_savecheck_walk_routing.py` use.
"""

from conftest import load_tools_module

savecheck = load_tools_module("savecheck")
session = load_tools_module("session")

answer_bars = savecheck.answer_bars
Log = savecheck.Log
Session = session.Session
MOVE_SUBBAR = session.MOVE_SUBBAR

WORLD_BAR = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"
SUBBAR_ROW = MOVE_SUBBAR + ", RETURN OR BUTTON"


class FakeScreen:
    def __init__(self, row24: str):
        self.row24 = row24

    def row(self, r: int) -> str:
        return self.row24 if r == 24 else ""

    def contains(self, needle: str) -> bool:
        return needle in self.row24


class FakeKeyboard:
    def __init__(self):
        self.sent: list[str] = []

    def key(self, name, hold=0.0, gap=0.0):
        self.sent.append(name)


class FakeLog(Log):
    def __init__(self):
        self.said: list[str] = []

    def say(self, *a) -> None:
        self.said.append(" ".join(str(x) for x in a))


class FakeAnswerBarsSession:
    """A walk that landed on the move sub-bar instead of the world bar.

    `select_bar` raises if it is ever called: the whole bug is that the old
    code had no branch for this row and fell through to the ones that call
    it, over and over, for the whole retry budget.
    """

    def __init__(self, rows):
        self.rows = list(rows)
        self.kbd = FakeKeyboard()
        self.leave_move_calls = 0

    def handle_prompt(self, s=None) -> bool:
        return False

    def screen(self):
        return FakeScreen(self.rows.pop(0) if len(self.rows) > 1
                           else self.rows[0])

    def leave_move(self, tries: int = 8) -> bool:
        self.leave_move_calls += 1
        self.rows = [WORLD_BAR]
        return True

    def select_bar(self, label, row=24, timeout=30.0):
        raise AssertionError(
            "select_bar must never be pointed at the move sub-bar "
            "(docs/70-driving-the-game.md:315)")


def test_answer_bars_leaves_the_move_subbar_instead_of_spinning():
    sess = FakeAnswerBarsSession([SUBBAR_ROW])
    outcome = answer_bars(sess, FakeLog())
    assert outcome == "world"
    assert sess.leave_move_calls == 1


def test_answer_bars_still_recognises_the_world_bar_directly():
    """The guard: a walk that lands cleanly must not go anywhere near
    `leave_move` at all."""
    sess = FakeAnswerBarsSession([WORLD_BAR])
    outcome = answer_bars(sess, FakeLog())
    assert outcome == "world"
    assert sess.leave_move_calls == 0


# -- `Session.save_game` --------------------------------------------------


class FakeSaveGameSession(Session):
    """A `Session` asked to resave right after a crossing left the move
    sub-bar up.  `select_bar` raises for `ENCAMP`, the same guard as above,
    so the test fails loudly if the guard in `save_game` is ever removed."""

    def __init__(self, subbar_up: bool = True):
        self.save_disk = "/tmp/does-not-matter.d64"
        self.subbar_up = subbar_up
        self.leave_move_calls = 0
        self.select_bar_calls: list[str] = []

    def screen(self):
        return FakeScreen(SUBBAR_ROW if self.subbar_up else WORLD_BAR)

    def leave_move(self, tries: int = 8) -> bool:
        self.leave_move_calls += 1
        self.subbar_up = False
        return True

    def select_bar(self, label, row=24, timeout=30.0):
        self.select_bar_calls.append(label)
        if label == "ENCAMP" and self.subbar_up:
            raise AssertionError(
                "select_bar('ENCAMP') must never be pointed at the move "
                "sub-bar (docs/70-driving-the-game.md:315)")
        return True

    def settle(self, seconds: float) -> None:
        pass


def test_save_game_leaves_the_move_subbar_before_asking_for_encamp():
    sess = FakeSaveGameSession(subbar_up=True)
    assert sess.save_game() is True
    assert sess.leave_move_calls == 1
    assert sess.select_bar_calls[0] == "ENCAMP"


def test_save_game_does_not_call_leave_move_when_the_world_bar_is_already_up():
    sess = FakeSaveGameSession(subbar_up=False)
    assert sess.save_game() is True
    assert sess.leave_move_calls == 0
