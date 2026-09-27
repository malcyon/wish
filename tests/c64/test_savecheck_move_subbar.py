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
answers, the same pattern `tests/c64/test_session_walk_movebar.py` and
`tests/c64/test_savecheck_walk_routing.py` use.
"""

from conftest import load_tools_module

savecheck = load_tools_module("savecheck")
session = load_tools_module("session")

answer_bars = savecheck.answer_bars
from tools.c64.runlog import Log  # noqa: E402

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


# -- `Session.save_game` from the camp bar (#621) --------------------------

CAMP_BAR_ROW = "ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT"


class FakeCampBarSaveGameSession(Session):
    """A caller that already left its own screen back to the camp bar,
    rather than the world bar.  `ENCAMP` is not a selectable item there --
    it is the bar's own header text -- so `select_bar('ENCAMP')` must never
    be reached; it would fail (or, before the fix, silently return `False`)
    on every one of these fakes."""

    def __init__(self, camp_bar_up: bool = True):
        self.save_disk = "/tmp/does-not-matter.d64"
        self.camp_bar_up = camp_bar_up
        self.select_bar_calls: list[str] = []

    def screen(self):
        return FakeScreen(CAMP_BAR_ROW if self.camp_bar_up else WORLD_BAR)

    def leave_move(self, tries: int = 8) -> bool:
        raise AssertionError("leave_move must not run from the camp bar")

    def select_bar(self, label, row=24, timeout=30.0):
        self.select_bar_calls.append(label)
        if label == "ENCAMP" and self.camp_bar_up:
            raise AssertionError(
                "select_bar('ENCAMP') must never be pointed at the camp "
                "bar; ENCAMP is not a selectable item there (#621)")
        return True

    def settle(self, seconds: float) -> None:
        pass


def test_save_game_skips_encamp_when_the_camp_bar_is_already_up():
    sess = FakeCampBarSaveGameSession(camp_bar_up=True)
    assert sess.save_game() is True
    assert sess.select_bar_calls[0] == "SAVE"
    assert "ENCAMP" not in sess.select_bar_calls


def test_save_game_still_selects_encamp_from_the_world_bar():
    """The guard: an ordinary world-bar start must not skip ENCAMP."""
    sess = FakeCampBarSaveGameSession(camp_bar_up=False)
    assert sess.save_game() is True
    assert sess.select_bar_calls[0] == "ENCAMP"


# -- `Session.save_game`'s EXIT wait after the write (#621) -----------------


class FakeSaveGameTimeoutSession(Session):
    """Records the `timeout` passed to every `select_bar` call, so the wait
    for the camp bar to return after the write can be checked without
    actually waiting: the write on a stock-kernal, no-JiffyDOS instance was
    found not to finish inside the default 30s timeout, which made
    `select_bar("EXIT")` give up and the caller's `copy_closed_disk` fail on
    a directory entry still open."""

    def __init__(self):
        self.save_disk = "/tmp/does-not-matter.d64"
        self.select_bar_calls: list[tuple[str, float]] = []

    def screen(self):
        return FakeScreen(WORLD_BAR)

    def select_bar(self, label, row=24, timeout=30.0):
        self.select_bar_calls.append((label, timeout))
        return True

    def settle(self, seconds: float) -> None:
        pass


def test_save_game_waits_ninety_seconds_for_exit_after_the_write():
    sess = FakeSaveGameTimeoutSession()
    assert sess.save_game() is True
    exit_calls = [t for (label, t) in sess.select_bar_calls if label == "EXIT"]
    assert exit_calls == [90.0]


# -- `Session.save_game` re-reads the screen after `leave_move` -----------


class FakeSubbarThenCampBarSession(Session):
    """A screen that shows the move sub-bar first, then -- once
    `leave_move` has run -- the camp bar rather than the world bar. Nothing
    in `#621` says this sequence occurs in the real game (the two strings
    are mutually exclusive, so no live screen can show both), but the check
    must read whatever `screen()` answers *after* `leave_move`, not
    whatever it answered before, and this is the fake that would catch a
    reintroduced stale read.
    """

    def __init__(self):
        self.save_disk = "/tmp/does-not-matter.d64"
        self.after_leave_move = False
        self.screen_calls = 0
        self.select_bar_calls: list[str] = []

    def screen(self):
        self.screen_calls += 1
        return FakeScreen(CAMP_BAR_ROW if self.after_leave_move
                           else SUBBAR_ROW)

    def leave_move(self, tries: int = 8) -> bool:
        self.after_leave_move = True
        return True

    def select_bar(self, label, row=24, timeout=30.0):
        self.select_bar_calls.append(label)
        return True

    def settle(self, seconds: float) -> None:
        pass


def test_save_game_re_reads_the_screen_after_leaving_the_move_subbar():
    sess = FakeSubbarThenCampBarSession()
    assert sess.save_game() is True
    # Read once for the initial MOVE_SUBBAR check, and again after
    # `leave_move` -- the second read is what `already_on_camp_bar` must
    # test, so ENCAMP is skipped just as it is when the camp bar was up
    # from the start.
    assert sess.screen_calls >= 2
    assert "ENCAMP" not in sess.select_bar_calls
    assert sess.select_bar_calls[0] == "SAVE"
