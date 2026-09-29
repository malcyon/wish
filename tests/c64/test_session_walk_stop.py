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
