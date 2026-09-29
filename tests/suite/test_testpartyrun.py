"""`pick_a_fight` reaches combat when the encounter opens on a menu.

The real `Session.walk_one` presses nothing at an encounter menu unless the
caller sets `walk_encounter`, so a fight-seeking loop that leaves it unset
walks for ever.  Only the screen, the keyboard and `select_bar` are scripted.
"""

import pathlib

from conftest import load_tools_module

S = load_tools_module("session")
from tools.suite import testpartyrun as T  # noqa: E402


class Screen:
    def __init__(self, bar):
        self.bar = bar

    def row(self, r):
        return self.bar if r == 24 else ""

    def text(self):
        return self.bar

    def contains(self, needle):
        return needle in self.bar


class PatrolSession(S.Session):
    """Standing on a square whose encounter opens on `COMBAT WAIT FLEE ADVANCE`."""

    def __init__(self, monkeypatch):
        monkeypatch.setattr(S.time, "sleep", lambda s: None)
        self.fighting = False
        self.asked = []
        self.here, self.save_disk = "/slot", "/slot/SAVE.D64"
        self._last_prompt = 0.0

    def indoors(self):
        return True

    def screen(self):
        return Screen("COMBAT WAIT FLEE ADVANCE")

    def status(self):
        return 0

    def log(self, *a):
        pass

    def handle_prompt(self, s=None):
        return False

    def settle(self, seconds=0):
        pass

    def position(self):
        return (0, 0, 0)

    def in_combat(self):
        return self.fighting

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        self.asked.append(label)
        self.fighting = label == "COMBAT"
        return True


class Log:
    def emit(self, *a, **k):
        pass

    def say(self, *a):
        pass


def test_pick_a_fight_takes_an_encounter_menu_as_the_fight(monkeypatch):
    sess = PatrolSession(monkeypatch)
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    got = T.pick_a_fight(sess, Log(), pathlib.Path("."), steps=3)
    assert got["in_combat"] is True and sess.asked == ["COMBAT"]
