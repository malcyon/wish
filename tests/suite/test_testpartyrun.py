"""`pick_a_fight` reaches combat when the encounter opens on a menu.

The real `Session.walk_one` presses nothing at an encounter menu unless the
caller sets `walk_encounter`, so a fight-seeking loop that leaves it unset
walks for ever.  Only the screen, the keyboard and `select_bar` are scripted.
"""

import pathlib

import pytest
from conftest import load_tools_module
from gamedata import synthetic_geo

from goldbox.geo import ATTRIBUTES, GRID, Geo
from tools.areas import geowalk
from tools.suite import testpartyrun as T

S = load_tools_module("session")


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
    """Fights when the party has sent `fight_after` keys; refuses the keys
    numbered in `refuse` (1-based); stands at `start` until `arrive_after`
    keys have been sent, then on the New Phlan exit."""

    def __init__(self, monkeypatch, fight_after=None, area=20, refuse=(),
                 start=(3, 4, 3), arrive_after=None, turns_move=True,
                 turn_lands=True, facing_known=True, coords=True, drift=False):
        super().__init__(monkeypatch)
        self.keys, self.fight_after, self.area = [], fight_after, area
        self.refuse, self.start, self.arrive_after = refuse, start, arrive_after
        # New Phlan's status tuple does not change on a turn, so `walk_one`
        # says False for one; `turn_lands` False leaves the facing unchanged.
        self.turns_move, self.turn_lands = turns_move, turn_lands
        self.facing_known, self.facing = facing_known, start[2]
        # The status line the party sees: New Phlan's shows the square, the
        # Slums' does not, and `drift` leaves the square where it was.
        self.coords, self.drift, self.square = coords, drift, tuple(start[:2])

    def walk_one(self, key, *a, **k):
        self.keys.append(key)
        self.fighting = self.fight_after == len(self.keys)
        if key in "KJ":
            if self.turn_lands:
                self.facing = (self.facing + (1 if key == "K" else -1)) % 4
            return self.turns_move and len(self.keys) not in self.refuse
        moved = len(self.keys) not in self.refuse
        if moved and not self.drift:
            dx, dy = geowalk.STEP[self.facing]
            self.square = (self.square[0] + dx, self.square[1] + dy)
        return moved

    def screen_text(self):
        line = "8:07"
        if self.facing_known:
            line = "NESW"[self.facing] + " " + line
            if self.coords and self.square[0] >= 0:
                line += " %d,%d" % self.square
        return "HERE / " + line

    def position(self):
        facing = self.facing if self.facing_known else None
        if self.arrive_after is not None and len(self.keys) >= self.arrive_after:
            return (*T.NEW_PHLAN_EXIT, facing)
        return (*self.start[:2], facing)


class RecordingLog(Log):
    def __init__(self):
        self.events = []

    def emit(self, kind, **what):
        self.events.append((kind, what))


def _walk(monkeypatch, fight_after, area=20, refuse=(), start=(3, 4, 3),
          arrive=True):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: sess.area)
    first, _ = T.plan_fight_route(_geo(), _geo(), start[:2], (12, 4))
    # A route of no keys leaves the party on its start, which is the exit.
    arrive_after = max(1, len(geowalk.keys_for(first, start[2]))) if arrive else None
    sess = WalkSession(monkeypatch, fight_after, area, refuse, start,
                       arrive_after)
    log = RecordingLog()
    got = T.walk_to_fight(sess, log, pathlib.Path("."), (12, 4), _geo(), _geo())
    return sess, log, got


def test_walk_to_fight_reaches_the_target_and_says_so(monkeypatch):
    first, second = T.plan_fight_route(_geo(), _geo(), (3, 4), (12, 4))
    # One key a square (facing west already), one for the edge.
    total = (len(first) - 1) + 1 + (len(second) - 1)
    sess, log, got = _walk(monkeypatch, fight_after=total)
    assert got == {"in_combat": True, "began_at": [12, 4], "at_target": True,
                   "desynced": None}
    assert ("edge", {"moved": True, "area": 20}) in log.events


def test_walk_to_fight_logs_a_fight_on_the_way_as_not_the_target(monkeypatch):
    sess, log, got = _walk(monkeypatch, fight_after=3)
    assert got["in_combat"] and got["at_target"] is False
    assert got["began_at"] is not None


def test_a_route_that_finishes_with_no_fight_began_nowhere(monkeypatch):
    sess, log, got = _walk(monkeypatch, fight_after=None)
    assert got["in_combat"] is False
    assert got["began_at"] is None and got["at_target"] is False


def test_a_refused_step_stops_the_walk_and_is_never_the_target(monkeypatch):
    first, second = T.plan_fight_route(_geo(), _geo(), (3, 4), (12, 4))
    total = (len(first) - 1) + 1 + (len(second) - 1)
    # Refuse a Slums step, with the fight on the very last key the plan sends:
    # the party never got there, so it is not at the target.
    refused = total - 2
    sess, log, got = _walk(monkeypatch, fight_after=total, refuse={refused})
    assert len(sess.keys) == refused
    assert got["at_target"] is not True and got["desynced"]["leg"] == "slums"
    assert got["desynced"]["to"] == list(second[refused - len(first)])


def test_a_refused_new_phlan_step_never_presses_the_edge(monkeypatch):
    sess, log, got = _walk(monkeypatch, fight_after=None, refuse={1})
    assert sess.keys == ["I"]
    assert got["desynced"]["leg"] == "new-phlan" and got["at_target"] is False
    assert not [e for e in log.events if e[0] == "edge"]


def test_a_fight_after_a_turn_key_is_on_the_square_the_party_left():
    sess = WalkSession(pytest.MonkeyPatch(), fight_after=1)
    # Facing west, the step north turns right first: `K`, then `I`.
    got = T.walk_route(sess, RecordingLog(), [(5, 5), (5, 4)], 3, "slums")
    assert sess.keys == ["K"] and got == (0, (5, 5), None)


def test_the_edge_is_refused_when_the_party_is_not_where_it_planned(monkeypatch):
    with pytest.raises(RuntimeError, match="planned"):
        _walk(monkeypatch, fight_after=None, arrive=False)


def test_the_edge_step_turns_west_first_when_the_last_step_was_not_west(
        monkeypatch):
    # From (0, 5) facing north the one step is north, so the edge needs `J`.
    sess, log, got = _walk(monkeypatch, fight_after=None, start=(0, 5, 0))
    assert sess.keys[:2] == ["I", "J"] and sess.keys[2] == "I"


def test_the_edge_step_turns_about_when_the_party_faces_away_from_it(
        monkeypatch):
    sess, log, got = _walk(monkeypatch, fight_after=None, start=(0, 4, 1))
    assert "M" not in sess.keys and sess.keys[:3] == ["K", "K", "I"]


def test_a_reverse_first_step_turns_twice_rather_than_sending_m(monkeypatch):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    sess = WalkSession(monkeypatch, None, 20, (), (5, 5, 0), None)
    got = T.walk_route(sess, RecordingLog(), [(5, 5), (5, 6)], 0, "slums")
    assert sess.keys == ["K", "K", "I"] and got == (2, None, None)


def test_walk_to_fight_stops_when_the_edge_leaves_the_wrong_area(monkeypatch):
    with pytest.raises(RuntimeError, match="area 20"):
        _walk(monkeypatch, fight_after=None, area=1)


def _turning_walk(monkeypatch, refuse=(), **fake):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    sess = WalkSession(monkeypatch, None, 20, refuse, (9, 13, 0), None, **fake)
    # (9, 14) is behind a party at (9, 13) facing north: two turns, then forward.
    got = T.walk_route(sess, RecordingLog(), [(9, 13), (9, 14)], 0, "new-phlan")
    return sess, got


def test_a_turn_walk_one_reports_unmoved_does_not_desync_the_walk(monkeypatch):
    sess, got = _turning_walk(monkeypatch, turns_move=False)
    assert sess.keys == ["K", "K", "I"] and got == (2, None, None)


def test_a_forward_key_reported_unmoved_still_desyncs_after_turns(monkeypatch):
    sess, got = _turning_walk(monkeypatch, turns_move=False, refuse={3})
    assert got[2]["key"] == "i" and "reason" not in got[2]


def test_a_turn_that_leaves_the_wrong_facing_desyncs_as_turn_not_seen(
        monkeypatch):
    sess, got = _turning_walk(monkeypatch, turns_move=False, turn_lands=False)
    assert sess.keys == ["K"] and got[1] is None
    assert got[2]["reason"] == "turn_not_seen" and got[2]["key"] == "k"


def test_a_turn_with_no_facing_on_the_status_line_is_logged_and_goes_on(
        monkeypatch):
    sess, got = _turning_walk(monkeypatch, turns_move=False, turn_lands=False,
                              facing_known=False)
    assert sess.keys == ["K", "K", "I"] and got[2] is None


def test_the_edge_turn_desyncs_as_turn_not_seen(monkeypatch):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: 20)
    sess = WalkSession(monkeypatch, None, 20, (), (0, 4, 1), 1,
                       turns_move=False, turn_lands=False)
    got = T.walk_to_fight(sess, RecordingLog(), pathlib.Path("."), (12, 4),
                          _geo(), _geo())
    assert got["desynced"]["reason"] == "turn_not_seen"
    assert got["at_target"] is False and sess.keys == ["K"]


def test_a_status_line_without_coordinates_still_gives_the_facing(monkeypatch):
    # The Slums' line reads `S 8:07`; the memory copy behind `position()` lags,
    # so the check must not ask it, in the walk or after it.
    def refuse():
        raise AssertionError("position() is the lagging copy")

    monkeypatch.setattr(WalkSession, "position", lambda self: refuse())
    sess, got = _turning_walk(monkeypatch, turns_move=False, coords=False)
    assert sess.keys == ["K", "K", "I"] and got == (2, None, None)
    log = RecordingLog()
    assert T._turn_key(sess, log, "k", (sess.facing + 1) % 4, "slums",
                       (9, 13), (9, 14)) is None


def test_the_status_row_wins_over_an_earlier_message_row_that_looks_like_it():
    class Sess:
        def screen_text(self):
            return "A E 1:30 / HERE / S 8:07 4,9"

    assert T._status_line(Sess()) == (2, (4, 9))


def test_a_status_line_with_no_facing_is_logged_as_none(monkeypatch):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    sess = WalkSession(monkeypatch, None, 20, (), (9, 13, 0), None,
                       turns_move=False, facing_known=False)
    log = RecordingLog()
    T.walk_route(sess, log, [(9, 13), (9, 14)], 0, "new-phlan")
    turns = [w for kind, w in log.events if kind == "route_key" and w.get("turn")]
    assert turns and all(w["facing"] is None for w in turns)


def test_a_fight_found_by_a_turn_is_at_the_square_the_party_stood_on(
        monkeypatch):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    sess = WalkSession(monkeypatch, 1, 20, (), (9, 13, 0), None,
                       turns_move=False)
    got = T.walk_route(sess, RecordingLog(), [(9, 13), (9, 14)], 0, "new-phlan")
    assert got[1:] == ((9, 13), None) and sess.keys == ["K"]


def test_a_forward_key_that_lands_on_another_square_desyncs_in_new_phlan(
        monkeypatch):
    sess, got = _turning_walk(monkeypatch, turns_move=False, drift=True)
    assert got[1] is None and got[2]["reason"] == "square_not_reached"
    assert got[2]["square"] == [9, 13] and got[2]["to"] == [9, 14]


def test_the_slums_forward_key_is_not_checked_against_a_square(monkeypatch):
    sess, got = _turning_walk(monkeypatch, turns_move=False, drift=True,
                              coords=False)
    assert got == (2, None, None)


def test_a_fight_found_by_the_edge_turn_stops_before_the_edge_step(monkeypatch):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: 20)
    sess = WalkSession(monkeypatch, 1, 20, (), (0, 4, 1), 1, turns_move=False)
    got = T.walk_to_fight(sess, RecordingLog(), pathlib.Path("."), (12, 4),
                          _geo(), _geo())
    assert sess.keys == ["K"] and got["in_combat"] is True
    assert got["began_at"] == [0, 4] and got["at_target"] is False
