"""`Session.walk_one` and `leave_move` press nothing at a screen they do not answer.

A Return at an encounter menu or a `YES NO` takes the highlighted choice for
the party.  The fake is a `Session` that keeps the real `walk_one`,
`leave_move`, `walk_stop` and `combat_state`; only the screen, the keyboard
and `select_bar`'s answer are scripted.  The rows are from measured captures:
the temple question and the Curse patrol menu.
"""

from conftest import load_tools_module

S = load_tools_module("session")

SUBBAR = S.MOVE_SUBBAR + ", RETURN OR BUTTON"
WORLD = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"
TEMPLE = ("YES NO", ["YOU ARE WELCOMED BY PRIESTESS JOY OF",
                     "SUNE.' DO YOU SEEK HEALING?'"])
PATROL = ("COMBAT WAIT FLEE ADVANCE", ["A PATROL CONFRONTS YOU"])
FIGHT = ("MOVE VIEW AIM USE CAST QUICK DONE", [])


class Screen:
    def __init__(self, bar, lines=()):
        self.rows = [""] * 25
        for i, line in enumerate(lines):
            self.rows[17 + i] = line
        self.rows[24] = bar

    def row(self, r):
        return self.rows[r]

    def text(self):
        return "\n".join(self.rows)

    def contains(self, needle):
        return needle in self.text()


def screen(spec):
    return Screen(*spec) if isinstance(spec, tuple) else Screen(spec)


class Fake(S.Session):
    """`reads` is the queue of screens (the last one repeats); `after_key`
    replaces the screen once a direction key is sent, and `after_return` once
    a Return is."""

    def __init__(self, monkeypatch, first, after_key=None, after_return=None):
        monkeypatch.setattr(S.time, "sleep", lambda s: None)
        self.current = screen(first)
        self.after_key = after_key
        self.after_return = after_return
        self.keys, self.kernal, self.asked = [], [], []
        self.ticks = 0
        self.here, self.save_disk = "/slot", "/slot/SAVE.D64"
        self._last_prompt = 0.0
        outer = self

        class Kbd:
            def key(kself, name, *timing):
                outer.keys.append(name)
                if name in ("i", "j", "k", "m"):
                    outer.ticks += 1
                    if outer.after_key is not None:
                        outer.current = screen(outer.after_key)
                elif name == "Return" and outer.after_return is not None:
                    outer.current = screen(outer.after_return)

        self.kbd = Kbd()

    def indoors(self):
        return True

    def live_triple(self):
        # `walk_one` reads the live square around the key; a step that
        # leaves the status line alone leaves this alone too.
        return (5, 5, 0)

    def screen(self):
        return self.current

    def status(self):
        return self.ticks

    def log(self, *a):
        pass

    def press_kernal(self, code, *a, **k):
        self.kernal.append(code)

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        self.asked.append(label)
        return S.word_column(self.current.row(24), label) >= 0

    def pressed_return(self):
        return "Return" in self.keys or 0x0D in self.kernal


def test_the_temple_question_after_a_step_is_not_answered(monkeypatch):
    sess = Fake(monkeypatch, SUBBAR, after_key=TEMPLE)
    assert sess.walk_one("I") is True
    assert sess.keys == ["i"] and sess.kernal == []


def test_an_encounter_menu_before_the_key_is_recorded_and_not_answered(monkeypatch):
    sess = Fake(monkeypatch, PATROL)
    assert sess.walk_one("I") is False
    assert sess.keys == [] and sess.kernal == []
    assert "COMBAT WAIT FLEE ADVANCE" in sess.walk_refused
    assert sess.walk_stop_screen[24].strip() == "COMBAT WAIT FLEE ADVANCE"


def test_a_walk_that_was_asked_for_the_fight_takes_it(monkeypatch):
    sess = Fake(monkeypatch, PATROL)
    sess.walk_encounter = S.ENCOUNTER_FIGHT
    assert sess.walk_one("I") is False
    assert sess.asked == ["COMBAT"]
    assert sess.keys == [] and "because the caller asked" in sess.walk_refused


def test_a_fight_bar_stops_the_walk_without_asking_for_move(monkeypatch):
    sess = Fake(monkeypatch, FIGHT)
    assert sess.walk_one("I") is False
    assert "MOVE" not in sess.asked and sess.keys == []
    assert sess.walk_stop_screen is not None


def test_a_bar_caught_half_drawn_does_not_stop_the_walk(monkeypatch):
    sess = Fake(monkeypatch, "MO", after_key=WORLD)
    reads = iter(["MO", SUBBAR])
    real = sess.screen

    def screen_():
        # The first read finds the bar half drawn, every later one complete.
        if sess.ticks == 0:
            return Screen(next(reads, SUBBAR))
        return real()

    sess.screen = screen_
    assert sess.walk_one("I") is True
    assert sess.keys[0] == "i"


def test_leave_move_at_the_world_bar_presses_nothing(monkeypatch):
    sess = Fake(monkeypatch, WORLD)
    assert sess.leave_move() is True
    assert sess.keys == [] and sess.kernal == []


def test_leave_move_at_the_subbar_presses_one_return(monkeypatch):
    sess = Fake(monkeypatch, SUBBAR, after_return=WORLD)
    assert sess.leave_move() is True
    assert sess.keys == ["Return"]


def test_a_blank_row_24_throughout_presses_no_return(monkeypatch):
    sess = Fake(monkeypatch, "")
    assert sess.walk_one("I", tries=2) is False
    assert not sess.pressed_return() and "i" not in sess.keys
    assert "never brought up" in sess.walk_refused


class Machine:
    live_position = 0xC04B


class Squareless(Fake):
    """A status line of facing and time only (`N 4:00`, on row 14); `$C04B` is
    `square`, and becomes `moved_to` once a direction key is sent."""

    machine = Machine()

    def __init__(self, monkeypatch, moves=True, moved_to=(5, 4, 0),
                 line="N 4:00", first=None):
        super().__init__(monkeypatch, first or (SUBBAR, []),
                         after_return=(WORLD, []))
        self.current.rows[14] = line
        self.status = lambda: None
        self.moves = moves
        self.moved_to = moved_to
        self.square = (5, 5, 0)
        self.left = 0

    def steady_triple(self, seconds=1.0):
        if self.ticks and self.moves:
            return self.moved_to
        return self.square

    def leave_move(self, *a, **k):
        self.left += 1
        return True


def test_a_squareless_status_line_judges_the_step_by_the_live_square(monkeypatch):
    sess = Squareless(monkeypatch)
    assert sess.walk_one("I") is True
    assert sess.keys.count("i") == 1


def test_a_squareless_step_that_does_not_move_is_not_resent(monkeypatch):
    sess = Squareless(monkeypatch, moves=False)
    assert sess.walk_one("I") is False
    assert sess.keys.count("i") == 1


def test_a_turn_alone_counts_as_moved(monkeypatch):
    sess = Squareless(monkeypatch, moved_to=(5, 5, 1))
    assert sess.walk_one("J") is True
    assert sess.keys.count("j") == 1


def test_a_squareless_move_leaves_the_sub_bar_like_the_old_path(monkeypatch):
    sess = Squareless(monkeypatch)
    assert sess.walk_one("I") is True
    assert sess.left == 1
    blocked = Squareless(monkeypatch, moves=False)
    assert blocked.walk_one("I") is False
    assert blocked.left == 1


def test_an_unsteady_square_before_the_key_presses_nothing(monkeypatch):
    sess = Squareless(monkeypatch)
    sess.steady_triple = lambda seconds=1.0: None
    assert sess.walk_one("I") is False
    assert sess.keys == []
    assert "never steadied" in sess.walk_refused
    assert "driver error" in sess.walk_refused


def test_no_live_position_keeps_the_old_retries(monkeypatch):
    sess = Squareless(monkeypatch)
    sess.machine = type("M", (), {"live_position": None})()
    assert sess.walk_one("I", tries=3) is False
    assert sess.keys.count("i") == 3


def test_an_unreadable_live_square_falls_back_to_the_old_retries(monkeypatch):
    sess = Squareless(monkeypatch)

    def broken(seconds=1.0):
        raise OSError("monitor gone")

    sess.steady_triple = broken
    assert sess.walk_one("I", tries=3) is False
    assert sess.keys.count("i") == 3


def _not_taken(monkeypatch, **kw):
    sess = Squareless(monkeypatch, moves=False, **kw)

    def forbidden(seconds=1.0):
        raise AssertionError("the squareless branch was taken")

    sess.steady_triple = forbidden
    assert sess.walk_one("I", tries=3) is False
    assert sess.keys.count("i") == 3


def test_a_squared_status_line_does_not_take_the_branch(monkeypatch):
    _not_taken(monkeypatch, line="E 4:00 7,28")


def test_a_letter_and_time_off_the_status_row_do_not_take_the_branch(monkeypatch):
    sess = Squareless(monkeypatch, moves=False, line="")
    sess.current.rows[10] = "N 4:00"
    sess.current.rows[20] = "S 12:30"

    def forbidden(seconds=1.0):
        raise AssertionError("the squareless branch was taken")

    sess.steady_triple = forbidden
    assert sess.walk_one("I", tries=3) is False
    assert sess.keys.count("i") == 3


def test_a_menu_or_combat_screen_does_not_take_the_branch(monkeypatch):
    for bar, lines in ((TEMPLE[0], TEMPLE[1] + ["N 4:00"]),
                       (FIGHT[0], ["E 9:15"])):
        sess = Squareless(monkeypatch, moves=False, line="",
                          first=(SUBBAR, []))
        sess.current = screen((SUBBAR, lines))
        sess.current.rows[15] = bar

        def forbidden(seconds=1.0):
            raise AssertionError("the squareless branch was taken")

        sess.steady_triple = forbidden
        assert sess.walk_one("I", tries=2) is False
        assert sess.keys.count("i") == 2


class Encounter(Fake):
    """The status line and row 24 stay as they were after the key while
    `$C04B` already holds the new square, as an encounter's load does.  With
    `slow` the status line catches up on its third read: a slow line, not an
    encounter."""

    def __init__(self, monkeypatch, live_moves=True, slow=False):
        super().__init__(monkeypatch, SUBBAR)
        self.live_moves, self.slow, self.reads = live_moves, slow, 0
        self.left = 0

    def status(self):
        self.reads += 1
        return 1 if self.slow and self.reads >= 3 else 0

    def live_triple(self):
        return (5, 4, 0) if self.ticks and self.live_moves else (5, 5, 0)

    def leave_move(self, *a, **k):
        self.left += 1
        return True


def test_a_step_that_moves_the_live_square_and_not_the_status_line_is_an_encounter(
        monkeypatch):
    sess = Encounter(monkeypatch)
    assert sess.walk_one("I", tries=1, encounters=True) is True
    assert sess.walk_encounter_started is True
    assert sess.keys == ["i"] and sess.kernal == [] and sess.left == 0


def test_the_same_step_without_the_opt_in_behaves_as_it_always_did(monkeypatch):
    sess = Encounter(monkeypatch)
    assert sess.walk_one("I", tries=1) is False
    assert sess.walk_encounter_started is False and sess.left == 1


def test_a_slow_status_line_is_not_called_an_encounter(monkeypatch):
    sess = Encounter(monkeypatch, slow=True)
    assert sess.walk_one("I", tries=1, encounters=True) is True
    assert sess.walk_encounter_started is False and sess.left == 1


def test_a_step_that_moves_neither_is_not_an_encounter_and_leaves_the_move_bar(
        monkeypatch):
    sess = Encounter(monkeypatch, live_moves=False)
    assert sess.walk_one("I", tries=1, encounters=True) is False
    assert sess.walk_encounter_started is False and sess.left == 1


def test_the_encounter_flag_is_cleared_by_the_next_walk_one(monkeypatch):
    sess = Encounter(monkeypatch)
    sess.walk_one("I", tries=1, encounters=True)
    sess.live_moves = False
    sess.walk_one("I", tries=1, encounters=True)
    assert sess.walk_encounter_started is False


class LateMenu(Fake):
    """`MOVE` is taken and its sub-bar never comes: the world bar stays up
    until the square's encounter menu is drawn on the third read after."""

    def __init__(self, monkeypatch, menu=PATROL, draws_at=4):
        super().__init__(monkeypatch, WORLD)
        self.menu, self.taken, self.looks = screen(menu), False, 0
        self.draws_at = draws_at
        self.left = 0

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        self.asked.append(label)
        if label == "MOVE":
            self.taken = True
            return True
        return S.word_column(self.current.row(24), label) >= 0

    def screen(self):
        if self.taken:
            self.looks += 1
            if self.looks >= self.draws_at:
                self.current = self.menu
        return self.current

    def leave_move(self, *a, **k):
        self.left += 1
        return True


def test_a_menu_drawn_while_move_waits_for_its_sub_bar_is_answered(monkeypatch):
    sess = LateMenu(monkeypatch)
    sess.walk_encounter = S.ENCOUNTER_FIGHT
    assert sess.walk_one("I", tries=1, encounters=True) is False
    assert sess.asked == ["MOVE", "COMBAT"]
    assert sess.keys == [] and sess.left == 0
    assert sess.walk_stop_screen[24].strip() == "COMBAT WAIT FLEE ADVANCE"
    assert "because the caller asked" in sess.walk_refused


def test_a_late_yes_no_is_recorded_and_nothing_is_pressed(monkeypatch):
    sess = LateMenu(monkeypatch, menu=TEMPLE)
    sess.walk_encounter = S.ENCOUNTER_FIGHT
    assert sess.walk_one("I", tries=1, encounters=True) is False
    assert sess.asked == ["MOVE"] and sess.keys == [] and sess.left == 0
    assert sess.walk_stop_screen[24].strip() == "YES NO"


def test_without_the_opt_in_a_late_menu_is_not_looked_for(monkeypatch):
    sess = LateMenu(monkeypatch)
    sess.walk_encounter = S.ENCOUNTER_FIGHT
    assert sess.walk_one("I", tries=1) is False
    assert "COMBAT" not in sess.asked and sess.walk_stop_screen is None


class Fighting(S.Session):
    """A fight that only lets its fake clock run, one second a poll."""

    def __init__(self, monkeypatch):
        self.now = 1000.0
        monkeypatch.setattr(S.time, "time", lambda: self.now)
        self.lines = []
        self.reads = 0

    def in_combat(self):
        return True

    def mode(self):
        return S.COMBAT

    def screen(self):
        return Screen("")

    def idle(self, seconds=1.0):
        self.now += seconds

    def handle_prompt(self, s=None):
        return False

    def log(self, *a):
        self.lines.append(" ".join(str(x) for x in a))

    def battle(self):
        self.reads += 1

        class C:
            def __init__(self, name, hp, party):
                self.name, self.hp, self.is_party = name, hp, party

        class B:
            combatants = [C("ASTRA", 12, True), C("SKELETON", 3, False)]

        return B()


def test_a_long_fight_logs_one_line_a_minute_with_the_party_hp(monkeypatch):
    sess = Fighting(monkeypatch)
    result = sess.fight(budget=185.0)
    assert result.outcome == S.BUDGET
    assert len(sess.lines) == 3 and sess.reads == 3
    assert "60 s, 0 turns, party hp ASTRA=12" in sess.lines[0]
    assert "SKELETON" not in sess.lines[0]


def test_a_short_fight_logs_no_progress_line(monkeypatch):
    sess = Fighting(monkeypatch)
    sess.fight(budget=30.0)
    assert sess.lines == [] and sess.reads == 0


def test_a_menu_that_draws_fourteen_seconds_after_the_key_is_still_answered(
        monkeypatch):
    # Reads are 0.3 s apart, so 14 s is read 47; the plain wait ends at 27.
    sess = LateMenu(monkeypatch, draws_at=47)
    sess.walk_encounter = S.ENCOUNTER_FIGHT
    assert sess.walk_one("I", tries=1, encounters=True) is False
    assert sess.asked == ["MOVE", "COMBAT"] and sess.keys == []


def test_a_menu_that_never_draws_ends_with_the_old_message_after_the_long_wait(
        monkeypatch):
    sess = LateMenu(monkeypatch, draws_at=10 ** 6)
    sess.walk_encounter = S.ENCOUNTER_FIGHT
    assert sess.walk_one("I", tries=1, encounters=True) is False
    assert sess.looks == S.Session.ENCOUNTER_MENU_LOOKS + 1
    assert "never brought up" in sess.walk_refused


def test_without_the_opt_in_the_sub_bar_wait_is_the_usual_length(monkeypatch):
    sess = LateMenu(monkeypatch, draws_at=10 ** 6)
    assert sess.walk_one("I", tries=1) is False
    assert sess.looks == S.Session.MOVE_SUBBAR_LOOKS


def test_a_menu_after_the_callers_time_ran_out_is_not_answered(monkeypatch):
    sess = LateMenu(monkeypatch, draws_at=2)
    sess.walk_encounter = S.ENCOUNTER_FIGHT
    expired = iter([False])
    sess.walk_expired = lambda: next(expired, True)
    assert sess.walk_one("I", tries=1, encounters=True) is False
    assert sess.asked == ["MOVE"] and sess.keys == []
    assert sess.walk_stop_screen is None
    assert "time ran out" in sess.walk_refused


def test_a_fight_on_an_object_without_a_log_still_reports_nothing_and_runs(
        monkeypatch):
    sess = Fighting(monkeypatch)
    sess.log = None
    assert sess.fight(budget=100.0).outcome == S.BUDGET
    assert sess.reads == 1


class Wiped(Fighting):
    """A party wiped out: the loss line is up and row 24 stays blank."""

    def screen(self):
        return Screen("", ["THE PARTY HAS LOST"])

    def idle(self, seconds=1.0):
        raise AssertionError("a lost fight must not wait for anything")


def test_a_lost_fight_with_a_blank_row_24_returns_lost_at_once(monkeypatch):
    sess = Wiped(monkeypatch)
    result = sess.fight(budget=3000.0)
    assert result.outcome == S.LOST
    assert sess.now == 1000.0


class PressPrompt(Fighting):
    """One `PRESS <RETURN>` prompt, up until Return has been pressed."""

    def __init__(self, monkeypatch):
        super().__init__(monkeypatch)
        self.pressed = 0

    def screen(self):
        s = Screen("PRESS <RETURN> OR BUTTON TO CONTINUE")
        s.colours = [0] * 1000      # no highlight span on row 24
        s.codes = [0x20] * 1000
        return s

    def press_kernal(self, code):
        self.pressed += 1

    def await_change(self, text, timeout=0):
        self.now += timeout


def test_an_encounter_press_prompt_is_logged_once(monkeypatch):
    sess = PressPrompt(monkeypatch)
    sess.fight(budget=20.0)
    logged = [x for x in sess.lines if "PRESS" in x]
    assert sess.pressed > 1 and len(logged) == 1
    assert "Fight prompt" in logged[0]


def test_an_unanswered_encounter_menu_is_logged(monkeypatch):
    sess = LateMenu(monkeypatch)
    sess.lines = []
    sess.log = sess.lines.append
    sess._stop_walk("I", [""] * 24 + ["COMBAT WAIT FLEE ADVANCE"])
    assert any("COMBAT WAIT FLEE ADVANCE" in x for x in sess.lines)


class WonThenLost(Fighting):
    """The first fight-end line is `first`; a loss line follows on the next
    read, as a stale redraw would."""

    def __init__(self, monkeypatch, first):
        super().__init__(monkeypatch)
        self.first, self.n = first, 0

    def screen(self):
        self.n += 1
        return Screen("", [self.first if self.n == 1 else S.LOST_TEXT])


def test_a_later_lost_line_does_not_replace_an_earlier_won_or_ran_outcome(
        monkeypatch):
    for line, want in ((S.WON_TEXT, S.WON), (S.RAN_TEXT, S.RAN)):
        sess = WonThenLost(monkeypatch, line)
        assert sess.fight(budget=5.0).outcome == want
