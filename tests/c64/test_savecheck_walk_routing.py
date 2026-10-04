"""A walked step routes through whatever the game puts up next, always (#275).

`tools/c64/savecheck.py`'s walk loop only ran `answer_bars` -- the function that
presses through a room description, `PRESS <RETURN>`, a load and a `YES NO`
back to the world bar -- when `--route` was passed.  The training hall
answers a step with exactly that sequence and nothing had asked for routing,
so a run under `#257 (A DOS save made in the training hall converts as though
the party were in New Phlan)` read `moved: false, status: null` once every
118 seconds, four tries in a row, on a game that was only waiting for an
answer.

`walk_step_routed` is what the walk loop now calls after every move, with no
flag gating it.  Nothing here needs an emulator: `FakeSession` hands back a
fixed sequence of screens, one call to `.screen()` at a time.
"""

from conftest import load_tools_module

savecheck = load_tools_module("savecheck")
walk_step_routed = savecheck.walk_step_routed
from tools.c64.runlog import Log  # noqa: E402


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


class FakeSession:
    """The training hall's own sequence: a room description already dealt
    with, `PRESS <RETURN>` twice (a slow load), then one `YES NO`, then the
    world bar back."""

    def __init__(self):
        self.rows = [
            "PRESS <RETURN> OR BUTTON TO CONTINUE",
            "PRESS <RETURN> OR BUTTON TO CONTINUE",
            "TRAIN CHARACTER?         YES  NO",
            "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK",
        ]
        self.kbd = FakeKeyboard()
        self.selected: list[str] = []
        self.prompts_handled = 0

    def handle_prompt(self, s=None) -> bool:
        self.prompts_handled += 1
        return False

    def screen(self):
        row = self.rows.pop(0) if len(self.rows) > 1 else self.rows[0]
        return FakeScreen(row)

    def select_bar(self, label, row=24, timeout=30.0):
        self.selected.append(label)
        return True


class FakeLog(Log):
    def __init__(self):
        self.said: list[str] = []

    def say(self, *a) -> None:
        self.said.append(" ".join(str(x) for x in a))


def test_a_walked_step_is_routed_through_press_and_yes_no_to_the_world_bar():
    sess = FakeSession()
    outcome = walk_step_routed(sess, FakeLog(), "NO")
    assert outcome == "world"
    assert sess.selected == ["NO"]
    assert sess.prompts_handled >= 1


# ---------------------------------------------------------------------------
# A square that asks its question when MOVE is taken
# ---------------------------------------------------------------------------

session = load_tools_module("session")
Status = session.Status
SUBBAR_ROW = session.MOVE_SUBBAR + ", RETURN OR BUTTON"

#: The arms shop in New Phlan, as the C64 game draws it when `MOVE` is taken
#: on its front square (9,13): rows 17 and 18 hold the text, row 24 the bar.
SHOP_ROWS = (["$" + " " * 38 + "$"] * 17
             + ["$THE SHOP SPECIALIZES IN ARMS AND      $",
                "$ARMOR. 'CAN I SHOW YOU OUR WARES?'    $"]
             + ["$" + " " * 38 + "$"] * 4
             + ["@" + "[" * 38 + "@", "YES NO"])


class ShopFront:
    """`walk_one` as it behaves on the shop front: the first call takes
    `MOVE`, meets the question and stops with the key unsent; NO brings up
    the move sub-bar; a call made at the sub-bar sends the key and moves.
    `live_square` is `$C04B`-`$C04D`, which moves with the party."""

    combat_state = session.Session.combat_state

    def __init__(self, moved_on_resend=True, status_moves_on_no=False,
                 fighting=False):
        self.calls: list[str] = []
        self.selected: list[str] = []
        self.walk_stop_screen = None
        self.at = Status(2, 27, 9, 13)
        self.subbar = False
        self.moved_on_resend = moved_on_resend
        self.status_moves_on_no = status_moves_on_no
        self.fighting = fighting

    def in_combat(self):
        return self.fighting

    def live_square(self):
        return (self.at.x, self.at.y, self.at.facing)

    def walk_one(self, move):
        self.calls.append(move)
        if not self.subbar:
            self.walk_stop_screen = list(SHOP_ROWS)
            return False
        self.walk_stop_screen = None
        if self.moved_on_resend:
            self.at = Status(2, 28, 9, 14)
        return self.moved_on_resend

    def select_bar(self, label, row=24, timeout=30.0):
        self.selected.append(label)
        self.subbar = True
        if self.status_moves_on_no:
            self.at = Status(2, 28, 9, 14)
        return True

    def screen(self):
        return FakeScreen(SUBBAR_ROW if self.subbar else "YES NO")

    def status(self):
        return self.at


def test_a_question_before_the_key_is_answered_and_the_key_sent_at_the_subbar():
    """The arms shop front asks when MOVE is taken; NO brings up the
    sub-bar, and the key is sent there."""
    sess = ShopFront()
    log = FakeLog()
    moved, asked = savecheck.walk_move(sess, log, "I", "NO")
    assert moved is True
    assert sess.calls == ["I", "I"]
    assert sess.selected == ["NO"]
    assert asked == ["THE SHOP SPECIALIZES IN ARMS AND",
                     "ARMOR. 'CAN I SHOW YOU OUR WARES?'"]
    assert sess.status() == Status(2, 28, 9, 14)


def test_a_move_the_question_hid_is_not_sent_twice():
    """A square that asks on arrival puts the question up after the key;
    once it is answered the party stands elsewhere, and the move is not
    sent again."""
    sess = ShopFront(status_moves_on_no=True)
    moved, _asked = savecheck.walk_move(sess, FakeLog(), "I", "NO")
    assert moved is True
    assert sess.calls == ["I"]


def test_a_wall_after_the_question_is_still_reported_unmoved():
    sess = ShopFront(moved_on_resend=False)
    moved, asked = savecheck.walk_move(sess, FakeLog(), "I", "NO")
    assert moved is False
    assert asked
    assert sess.calls == ["I", "I"]


def test_a_stop_that_is_not_a_question_is_left_alone():
    sess = ShopFront()
    rows = list(SHOP_ROWS)
    rows[24] = "COMBAT WAIT FLEE ADVANCE"
    sess.walk_one = lambda move: (setattr(sess, "walk_stop_screen", rows)
                                  or False)
    moved, asked = savecheck.walk_move(sess, FakeLog(), "I", "NO")
    assert (moved, asked) == (False, None)
    assert sess.selected == []


def test_fight_and_no_encounters_together_are_refused(capsys):
    import pytest
    with pytest.raises(SystemExit):
        savecheck.main(["--disk", "X.D64", "--fight", "--no-encounters"])
    assert "--no-encounters" in capsys.readouterr().err


class GateSession:
    def __init__(self, fail=False):
        self.fail = fail

    def restore_encounter_gates(self):
        rows = [{"address": "$4A64", "verified": not self.fail}]
        if self.fail:
            raise savecheck.S.GateRestoreError("not verified", rows)
        return rows


class EmitLog(FakeLog):
    def __init__(self):
        super().__init__()
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, kind, **kw):
        self.emitted.append((kind, kw))


def test_restored_gates_are_recorded_and_an_unverified_one_stops_the_run():
    import pytest
    log = EmitLog()
    assert savecheck.restore_gates(GateSession(), log, "after the walk")
    assert log.emitted[-1][0] == "encounter_gates"
    assert log.emitted[-1][1]["verified"] is True
    with pytest.raises(savecheck.S.GateRestoreError):
        savecheck.restore_gates(GateSession(fail=True), log, "after the walk")
    assert log.emitted[-1][1]["verified"] is False


class ArrivalQuestion(ShopFront):
    """The step from 9,13 to 8,13: the key is read and the party moves, and
    8,13 asks the same question on arrival, before the status line is
    redrawn, so `walk_one` reads the step as unmoved."""

    def walk_one(self, move):
        self.calls.append(move)
        if not self.subbar:
            self.walk_stop_screen = list(SHOP_ROWS)
            return False
        self.at = Status(3, 27, 8, 13)
        self.walk_stop_screen = list(SHOP_ROWS)
        return False

    def status(self):
        return Status(3, 27, 9, 13)


def test_a_step_onto_a_square_that_asks_is_judged_by_the_live_square():
    sess = ArrivalQuestion()
    sess.at = Status(3, 27, 9, 13)
    moved, asked = savecheck.walk_move(sess, FakeLog(), "I", "NO")
    assert moved is True
    assert asked
    assert sess.calls == ["I", "I"]


def _combat_rows(bar):
    rows = list(SHOP_ROWS)
    rows[24] = bar
    return rows


def test_a_fights_yes_no_is_not_answered_by_a_walk():
    import pytest
    for bar, fighting in (("CONTINUE BATTLE : YES NO", False),
                          ("ATTACK ALLY: YES NO", True),
                          ("FLEE: YES NO", True)):
        sess = ShopFront(fighting=fighting)
        rows = _combat_rows(bar)
        sess.walk_one = lambda move, rows=rows, sess=sess: (
            setattr(sess, "walk_stop_screen", rows) or False)
        with pytest.raises(savecheck.WalkStopped):
            savecheck.walk_move(sess, FakeLog(), "I", "NO")
        assert sess.selected == [], bar


def test_without_a_live_square_a_half_drawn_status_line_is_not_a_move(
        monkeypatch):
    """Two reads of the status line that disagree say nothing."""
    monkeypatch.setattr(savecheck.time, "sleep", lambda _s: None)
    reads = iter([Status(2, 27, 9, 13), Status(2, 27, 9, 1)])

    class NoLive:
        def status(self):
            return next(reads)

    assert savecheck.where(NoLive()) is None


def test_the_live_square_is_the_status_lines_when_the_two_agree(monkeypatch):
    monkeypatch.setattr(savecheck.time, "sleep", lambda _s: None)

    class NoLive:
        def status(self):
            return Status(2, 27, 9, 13)

    assert savecheck.where(NoLive()) == (9, 13, 2)


class NoLiveSquare(ShopFront):
    """The shop front with a live square that cannot be read, and a status
    line that is redrawn after the answer."""

    def __init__(self, reads):
        super().__init__()
        self.reads = iter(reads)

    def live_square(self):
        return None

    def status(self):
        return next(self.reads)


def test_without_a_live_square_a_key_is_not_resent_on_a_status_line_that_disagrees(
        monkeypatch):
    import pytest
    monkeypatch.setattr(savecheck.time, "sleep", lambda _s: None)
    here = Status(2, 27, 9, 13)
    sess = NoLiveSquare([here, here, here, Status(2, 27, 9, 1)])
    with pytest.raises(savecheck.WalkStopped, match="not sent again"):
        savecheck.walk_move(sess, FakeLog(), "I", "NO")
    assert sess.calls == ["I"]


def test_without_a_live_square_a_key_is_resent_when_two_reads_agree_and_the_bar_is_up(
        monkeypatch):
    monkeypatch.setattr(savecheck.time, "sleep", lambda _s: None)
    here = Status(2, 27, 9, 13)
    sess = NoLiveSquare([here] * 8)
    moved, asked = savecheck.walk_move(sess, FakeLog(), "I", "NO")
    assert asked and sess.calls == ["I", "I"]


def test_the_answer_and_the_wait_for_the_subbar_stop_when_the_run_has_no_time_left(
        monkeypatch):
    import pytest
    monkeypatch.setattr(savecheck.time, "sleep", lambda _s: None)

    class NeverUp(ShopFront):
        def screen(self):
            return FakeScreen("YES NO")

    sess = NeverUp()
    sess.walk_stop_screen = list(SHOP_ROWS)
    left = iter([5.0, 0.0])
    with pytest.raises(savecheck.WalkStopped, match="no time was left"):
        savecheck.answer_move_question(sess, FakeLog(), "I", "NO",
                                       left=lambda: next(left))
    assert sess.selected == ["NO"]
