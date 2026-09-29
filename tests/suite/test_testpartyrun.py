"""`pick_a_fight` reaches combat when the encounter opens on a menu.

The real `Session.walk_one` presses nothing at an encounter menu unless the
caller sets `walk_encounter`, so a fight-seeking loop that leaves it unset
walks for ever.  Only the screen, the keyboard and `select_bar` are scripted.
"""

import pathlib

import pytest
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


# -- `--fight-at`: the route is planned from the map files -------------------

from gamedata import synthetic_geo  # noqa: E402

from goldbox.geo import ATTRIBUTES, GRID, Geo  # noqa: E402


def _geo(ids=None):
    raw = bytearray(synthetic_geo())
    for (x, y), value in (ids or {}).items():
        raw[ATTRIBUTES + y * GRID + x] = value
    return Geo.from_bytes(bytes(raw))


def test_plan_keeps_new_phlan_off_scripted_squares_and_the_slums_to_plain_ids():
    # Synthetic maps have no wall at x = 0 to the west, so the exits fall in
    # open floor; the point is which squares the planner may step on.
    new_phlan = _geo({(1, 4): 7, (2, 4): 7, (1, 3): 7, (1, 5): 7})
    slums = _geo({(14, 4): 9, (14, 3): 4, (13, 4): 0})
    first, second = T.plan_fight_route(new_phlan, slums, (3, 4), (12, 4))
    assert first[-1] == T.NEW_PHLAN_EXIT
    assert not {q for q in first if new_phlan.script_id(*q)}
    assert second[0] == T.SLUMS_ENTRY and second[-1] == (12, 4)
    assert (14, 4) not in second


def test_plan_refuses_when_a_scripted_column_cuts_off_the_goal():
    slums = _geo({(13, y): 9 for y in range(16)})
    with pytest.raises(SystemExit):
        T.plan_fight_route(_geo(), slums, (3, 4), (12, 4))


class WalkSession(PatrolSession):
    """Fights when the party has sent `fight_after` keys."""

    def __init__(self, monkeypatch, fight_after=None, area=20):
        super().__init__(monkeypatch)
        self.keys, self.fight_after, self.area = [], fight_after, area

    def walk_one(self, key, *a, **k):
        self.keys.append(key)
        self.fighting = self.fight_after == len(self.keys)
        return True

    def position(self):
        return (3, 4, 3)


class RecordingLog(Log):
    def __init__(self):
        self.events = []

    def emit(self, kind, **what):
        self.events.append((kind, what))


def _walk(monkeypatch, fight_after, area=20):
    from tools.c64 import hallmenu
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: sess.area)
    sess = WalkSession(monkeypatch, fight_after, area)
    log = RecordingLog()
    assert hallmenu  # imported by the module under test
    got = T.walk_to_fight(sess, log, pathlib.Path("."), (12, 4), _geo(), _geo())
    return sess, log, got


def test_walk_to_fight_reaches_the_target_and_says_so(monkeypatch):
    first, second = T.plan_fight_route(_geo(), _geo(), (3, 4), (12, 4))
    # One key a square (facing west already), one for the edge.
    total = (len(first) - 1) + 1 + (len(second) - 1)
    sess, log, got = _walk(monkeypatch, fight_after=total)
    assert got == {"in_combat": True, "began_at": [12, 4], "at_target": True}
    assert ("edge", {"moved": True, "area": 20}) in log.events


def test_walk_to_fight_logs_a_fight_on_the_way_as_not_the_target(monkeypatch):
    sess, log, got = _walk(monkeypatch, fight_after=3)
    assert got["in_combat"] and got["at_target"] is False
    assert got["began_at"] is not None


def test_walk_to_fight_stops_when_the_edge_leaves_the_wrong_area(monkeypatch):
    with pytest.raises(RuntimeError, match="area 20"):
        _walk(monkeypatch, fight_after=None, area=1)
