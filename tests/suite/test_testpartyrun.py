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


COMMAND = "MOVE VIEW AIM USE QUICK DONE"    # a party member's turn
ENCOUNTER = "COMBAT WAIT FLEE ADVANCE"


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
        # What row 24 shows once a fight is up: the encounter menu until a test
        # says a party member's turn has come.
        self.fight_row = ENCOUNTER

    def indoors(self):
        return True

    def screen(self):
        if self.fighting:
            return Screen(self.fight_row)
        return Screen(ENCOUNTER)

    def status(self):
        return 0

    def log(self, *a):
        pass

    def handle_prompt(self, s=None):
        return False

    def settle(self, seconds=0):
        pass

    # A fight that is up shows a party member's turn, so the combat shot does
    # not wait.  Only a call with no screen is answered here: `settle_step` and
    # `await_slums` pass their scripted rows and get the real classification.
    def combat_state(self, s=None):
        if self.fighting and s is None:
            return S.CombatBar(S.BAR_COMMAND, COMMAND)
        return super().combat_state(s)

    def battle(self):
        return None

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
    # The encounter bar is not the world's, so waiting for the world would time
    # out: a fight already up is returned as it stands.
    sess = PatrolSession(monkeypatch)
    sess.fighting = True
    rows = []
    # The shot itself waits for a command bar, which this menu is not; what is
    # under test is the path taken to it.
    monkeypatch.setattr(T, "photograph_fight",
                        lambda sess_, *a, **k: rows.append(
                            sess_.screen().row(24)))
    got = T.pick_a_fight(sess, Log(), pathlib.Path("."), steps=3)
    assert got["in_combat"] is True and sess.asked == []
    assert rows == [ENCOUNTER]


def test_pick_a_fight_presses_combat_on_an_encounter_menu_the_walk_opens(
        monkeypatch):
    sess = PatrolSession(monkeypatch)
    sess.fight_row = COMMAND     # once COMBAT is taken the fight's first turn
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    # This fake stays on the encounter bar; leaving camp is tested below.
    monkeypatch.setattr(T, "to_world", lambda *a, **k: True)
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


WORLD = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"
SUBBAR = "I,J,K,M, RETURN OR BUTTON"


class WalkSession(PatrolSession):
    """Fights when the party has sent `fight_after` keys; refuses the keys
    numbered in `refuse` (1-based); stands at `start` until `arrive_after`
    keys have been sent, then on the New Phlan exit."""

    def __init__(self, monkeypatch, fight_after=None, area=20, refuse=(),
                 start=(3, 4, 3), arrive_after=None, turns_move=True,
                 turn_lands=True, facing_known=True, coords=True, drift=False,
                 camp=False, camp_exit_works=True, arrival=None,
                 area_before=None):
        super().__init__(monkeypatch)
        self.fight_row = COMMAND
        # `arrival` is row 24 after the edge key, one entry per `screen()`
        # read, the last one repeating: by default one blank read, as the
        # Slums' load from side 2 leaves it, then the world bar.  `STALE` is
        # New Phlan's own world bar still up, with its status line at the
        # exit.  A key sent before the world bar is in `blank_keys`.
        self.arrival = list(arrival) if arrival is not None else ["", WORLD]
        self.arriving, self.blank_keys, self.pressed = False, [], []
        # `area_before`, when set, is the area until the edge key is sent.
        self.area_now, self.area_before = area, area_before
        self.keys, self.fight_after = [], fight_after
        self.refuse, self.start, self.arrive_after = refuse, start, arrive_after
        # `turns_move` False makes `walk_one` say False for a turn, as it may
        # when the status tuple it compares does not change; the live facing
        # letter does change on every turn, and `turn_lands` False leaves it
        # unchanged.
        self.turns_move, self.turn_lands = turns_move, turn_lands
        self.facing_known, self.facing = facing_known, start[2]
        # The status line the party sees: New Phlan's shows the square, the
        # Slums' does not, and `drift` leaves the square where it was.
        self.coords, self.drift, self.square = coords, drift, tuple(start[:2])
        # In camp row 24 is camp's own bar, there is no status line, and
        # `walk_one` presses nothing and says so in `walk_refused`.
        self.camp, self.camp_exit_works = camp, camp_exit_works
        self.camp_refusals, self.exits = [], 0

    @property
    def area(self):
        if self.area_before is not None and not self.arriving:
            return self.area_before
        return self.area_now

    def _arrival_row(self):
        return self.arrival[0] if self.arriving else WORLD

    def screen(self):
        if self.camp:
            return Screen("ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT")
        if not self.arriving:
            return Screen(COMMAND if self.fighting else WORLD)
        row = self.arrival[0]
        if len(self.arrival) > 1:
            self.arrival.pop(0)
        if row == "COMBAT WAIT FLEE ADVANCE" and self.fighting:
            row = ""
        if row == "STALE_SUBBAR":
            return Screen(SUBBAR)
        return Screen(WORLD if row == "STALE" else row)

    def press_kernal(self, code):
        self.pressed.append(code)

    def await_change(self, was, timeout=6.0, interval=0.3):
        return True

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        self.asked.append(label)
        self.exits += label == "EXIT"
        if label == "EXIT" and self.camp_exit_works:
            self.camp = False
        if label == "COMBAT":
            self.fighting = True
        return True

    def walk_one(self, key, *a, **k):
        if self.camp:
            self.camp_refusals.append(key)
            self.walk_refused = "the driver pressed nothing: camp's bar"
            return False
        self.walk_refused = None
        if self._arrival_row() not in (WORLD, SUBBAR):
            self.blank_keys.append(key)
            self.walk_refused = "the driver pressed nothing: row 24 not the world's"
            return False
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
            # The step off the west edge starts the Slums' load.
            self.arriving = self.arriving or self.square[0] < 0
        return moved

    def screen_text(self):
        if self.camp:
            return "HERE / "
        if self.arriving and self.arrival[0] in ("STALE", "STALE_SUBBAR"):
            return "HERE / W 0:47 0,4"
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
          arrive=True, **fake):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: sess.area)
    first, _ = T.plan_fight_route(_geo(), _geo(), start[:2], (12, 4))
    # A route of no keys leaves the party on its start, which is the exit.
    arrive_after = max(1, len(geowalk.keys_for(first, start[2]))) if arrive else None
    sess = WalkSession(monkeypatch, fight_after, area, refuse, start,
                       arrive_after, **fake)
    Clock(monkeypatch)      # after the session, whose init stubs `sleep`
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
    assert ("edge", {"moved": True, "area": 20, "arrived": "world"}) in log.events


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


def test_a_turn_with_no_facing_on_the_status_line_is_a_desync(monkeypatch):
    sess, got = _turning_walk(monkeypatch, turns_move=False, turn_lands=False,
                              facing_known=False)
    assert sess.keys == ["K"] and got[1] is None
    assert got[2]["reason"] == "no_status_line" and got[2]["key"] == "k"
    assert got[2]["row24"].startswith("MOVE")


def test_a_turn_the_driver_did_not_press_is_a_not_pressed_desync(monkeypatch):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    sess = WalkSession(monkeypatch, None, 20, (), (9, 13, 0), None, camp=True)
    got = T.walk_route(sess, RecordingLog(), [(9, 13), (9, 14)], 0, "new-phlan")
    assert got[2]["reason"] == "not_pressed" and got[2]["key"] == "k"
    assert "camp" in got[2]["refused"] and sess.camp_refusals == ["K"]


def test_a_forward_key_the_driver_did_not_press_is_a_not_pressed_desync(
        monkeypatch):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    sess = WalkSession(monkeypatch, None, 20, (), (9, 13, 0), None, camp=True)
    got = T.walk_route(sess, RecordingLog(), [(9, 13), (9, 13 - 1)], 0,
                       "new-phlan")
    assert sess.camp_refusals == ["I"]
    assert got[2]["reason"] == "not_pressed" and got[2]["key"] == "i"


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


# -- the game may still be in camp when the walk starts -----------------------

class Clock:
    """A clock the fake `sleep` advances, so a 30-second wait costs nothing."""

    def __init__(self, monkeypatch):
        self.now = 0.0
        monkeypatch.setattr(T.time, "monotonic", lambda: self.now)
        monkeypatch.setattr(T.time, "sleep", self.sleep)

    def sleep(self, seconds):
        self.now += seconds


def _camp_walk(monkeypatch, **fake):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: 20)
    sess = WalkSession(monkeypatch, None, 20, (), (3, 4, 3), 1, camp=True,
                       **fake)
    Clock(monkeypatch)      # after the session, whose init stubs `sleep`
    log = RecordingLog()
    return sess, log


def test_walk_to_fight_leaves_camp_before_its_first_key(monkeypatch):
    sess, log = _camp_walk(monkeypatch)
    got = T.walk_to_fight(sess, log, pathlib.Path("."), (12, 4), _geo(), _geo())
    assert sess.asked == ["EXIT"] and sess.exits == 1
    assert sess.camp_refusals == [] and sess.keys
    assert got["desynced"] is None
    rows = [w["row24"] for kind, w in log.events if kind == "to_world"]
    assert rows[0].startswith("ENCAMP:") and rows[-1].startswith("MOVE")
    assert ("to_world_exit", {"row24": "ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT",
                              "returned": True}) in log.events


def test_walk_to_fight_raises_naming_row_24_when_camp_will_not_go(monkeypatch):
    sess, log = _camp_walk(monkeypatch, camp_exit_works=False)
    with pytest.raises(RuntimeError, match="ENCAMP:SAVE"):
        T.walk_to_fight(sess, log, pathlib.Path("."), (12, 4), _geo(), _geo())
    assert sess.keys == [] and sess.camp_refusals == [] and sess.exits == 1


def test_to_world_presses_nothing_when_the_world_bar_is_already_up(monkeypatch):
    sess = WalkSession(monkeypatch)
    Clock(monkeypatch)
    assert T.to_world(sess, RecordingLog()) is True and sess.asked == []


def test_walk_to_fight_plans_from_the_status_line_not_the_memory_copy(
        monkeypatch):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: 20)
    sess = WalkSession(monkeypatch, None, 20, (), (3, 4, 3), None)
    Clock(monkeypatch)
    # The lagging copy still says the party is elsewhere.
    monkeypatch.setattr(WalkSession, "position", lambda self: (9, 9, 0))
    log = RecordingLog()
    with pytest.raises(RuntimeError, match="planned"):
        T.walk_to_fight(sess, log, pathlib.Path("."), (12, 4), _geo(), _geo())
    plan = next(w for kind, w in log.events if kind == "fight_plan")
    assert plan["start"] == [3, 4]


def test_pick_a_fight_leaves_camp_before_wandering(monkeypatch):
    sess, log = _camp_walk(monkeypatch)
    T.pick_a_fight(sess, log, pathlib.Path("."), steps=1)
    assert sess.asked == ["EXIT"] and sess.camp_refusals == []
    assert sess.keys == ["I"]


def test_pick_a_fight_raises_when_camp_will_not_go(monkeypatch):
    sess, log = _camp_walk(monkeypatch, camp_exit_works=False)
    with pytest.raises(RuntimeError, match="ENCAMP:SAVE"):
        T.pick_a_fight(sess, log, pathlib.Path("."), steps=1)
    assert sess.keys == []


def test_walk_to_fight_waits_for_the_square_after_the_facing_appears(
        monkeypatch):
    class Late(WalkSession):
        reads = 0

        def screen_text(self):
            self.reads += 1
            if self.reads <= 4:
                return "HERE / N 8:07"
            return super().screen_text()

    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: 20)
    sess = Late(monkeypatch, None, 20, (), (3, 4, 3), None)
    Clock(monkeypatch)
    # It gets past the planning read; the arrival check then fails as before.
    with pytest.raises(RuntimeError, match="planned"):
        T.walk_to_fight(sess, RecordingLog(), pathlib.Path("."), (12, 4),
                        _geo(), _geo())
    assert sess.reads > 4


def test_a_status_line_blank_for_one_read_after_a_turn_is_not_a_desync(
        monkeypatch):
    class Blink(WalkSession):
        blank = False

        def walk_one(self, key, *a, **k):
            self.blank = True
            return super().walk_one(key, *a, **k)

        def screen_text(self):
            if self.blank:
                self.blank = False
                return "HERE / "
            return super().screen_text()

    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    sess = Blink(monkeypatch, None, 20, (), (9, 13, 0), None, turns_move=False)
    got = T.walk_route(sess, RecordingLog(), [(9, 13), (9, 14)], 0, "new-phlan")
    assert got == (2, None, None)


def test_to_world_reports_what_the_exit_press_returned(monkeypatch):
    sess = WalkSession(monkeypatch, camp=True, camp_exit_works=False)
    Clock(monkeypatch)
    log = RecordingLog()
    with pytest.raises(RuntimeError, match=r"returned True"):
        T.to_world(sess, log)
    assert ("to_world_exit", {"row24": "ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT",
                              "returned": True}) in log.events


class MenuChain(WalkSession):
    """Row 24 walks through `rows`; each EXIT moves to the next unless
    `stuck`, and the last row is the world bar."""

    def __init__(self, monkeypatch, rows, stuck=False):
        super().__init__(monkeypatch)
        self.rows, self.stuck = list(rows), stuck

    def screen(self):
        return Screen(self.rows[0])

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        self.asked.append(label)
        if not self.stuck and len(self.rows) > 1:
            self.rows.pop(0)
        return True


ITEMS = "VIEW:ITEMS TRADE DROP EXIT"
CAMP = "ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT"


def test_to_world_leaves_the_item_view_and_then_camp(monkeypatch):
    sess = MenuChain(monkeypatch, [ITEMS, CAMP, WORLD])
    Clock(monkeypatch)
    log = RecordingLog()
    assert T.to_world(sess, log) is True
    assert sess.asked == ["EXIT", "EXIT"]
    assert [w["row24"] for k, w in log.events if k == "to_world_exit"] == [
        ITEMS, CAMP]


def test_to_world_presses_exit_once_for_a_row_that_will_not_leave(monkeypatch):
    sess = MenuChain(monkeypatch, [CAMP], stuck=True)
    Clock(monkeypatch)
    with pytest.raises(RuntimeError, match=r"ENCAMP:.*returned True"):
        T.to_world(sess, RecordingLog())
    assert sess.asked == ["EXIT"]


def test_walk_to_fight_returns_at_once_when_a_fight_is_already_up(monkeypatch):
    dumps = []
    monkeypatch.setattr(T, "dump", lambda sess, out, log, name: dumps.append(name))
    sess = WalkSession(monkeypatch, None, 20, (), (3, 4, 3), None)
    clock = Clock(monkeypatch)
    sess.fighting = True
    log = RecordingLog()
    got = T.walk_to_fight(sess, log, pathlib.Path("."), (12, 4), _geo(), _geo())
    assert got == {"in_combat": True, "began_at": [3, 4], "at_target": False,
                   "desynced": None}
    assert sess.keys == [] and sess.asked == [] and clock.now == 0
    assert dumps == ["combat-icon"]
    assert ("walked", {"leg": "start", "in_combat": True, "began_at": [3, 4],
                       "at_target": False, "desynced": None}) in log.events


def test_the_first_slums_key_waits_for_the_world_bar_after_the_edge(
        monkeypatch):
    sess, log, got = _walk(monkeypatch, fight_after=None,
                           arrival=[""] * 5 + [WORLD])
    assert sess.blank_keys == [] and sess.keys[-1] == "I"
    assert got["desynced"] is None
    rows = [w["row24"] for kind, w in log.events if kind == "slums_arrival"]
    assert rows == ["", WORLD]


def test_the_slums_coming_up_on_the_move_sub_bar_is_walked(monkeypatch):
    # Measured: with no fight the load ends on `I,J,K,M, RETURN OR BUTTON`,
    # 55 s after the edge, and the world bar never shows.
    sess, log, got = _walk(monkeypatch, fight_after=None,
                           arrival=["", "", SUBBAR])
    assert sess.blank_keys == [] and sess.keys[-1] == "I"
    assert got["desynced"] is None
    edge = next(w for kind, w in log.events if kind == "edge")
    assert edge["arrived"] == "move"


def test_new_phlans_bar_still_up_after_the_edge_is_not_the_slums(monkeypatch):
    # The area byte already reads the Slums while the old screen is up, so
    # only a blank row 24 says the load has begun.
    sess, log, got = _walk(monkeypatch, fight_after=None,
                           arrival=["STALE", "STALE", "", WORLD])
    assert sess.blank_keys == [] and got["desynced"] is None


def test_a_slums_bar_with_the_area_changed_needs_no_blank_row(monkeypatch):
    # A wait that begins after the load has finished sees no blank row; the
    # area changed from New Phlan's and the status line has left the exit.
    sess, log, got = _walk(monkeypatch, fight_after=None, arrival=[WORLD],
                           area_before=0)
    assert sess.blank_keys == [] and got["desynced"] is None


def test_the_stale_bar_is_not_accepted_on_the_area_byte_alone(monkeypatch):
    dumps = []
    monkeypatch.setattr(T, "dump", lambda sess, out, log, tag: dumps.append(tag))
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: sess.area)
    first, _ = T.plan_fight_route(_geo(), _geo(), (3, 4), (12, 4))
    sess = WalkSession(monkeypatch, None, 20, (), (3, 4, 3),
                       len(geowalk.keys_for(first, 3)), arrival=["STALE"],
                       area_before=0)
    Clock(monkeypatch)
    with pytest.raises(RuntimeError, match="row 24"):
        T.walk_to_fight(sess, RecordingLog(), pathlib.Path("."), (12, 4),
                        _geo(), _geo())
    assert sess.blank_keys == [] and dumps == ["slums-arrival-failed"]


def test_the_stale_move_sub_bar_is_not_accepted_on_the_area_byte_alone(
        monkeypatch):
    dumps = []
    monkeypatch.setattr(T, "dump", lambda sess, out, log, tag: dumps.append(tag))
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: sess.area)
    first, _ = T.plan_fight_route(_geo(), _geo(), (3, 4), (12, 4))
    sess = WalkSession(monkeypatch, None, 20, (), (3, 4, 3),
                       len(geowalk.keys_for(first, 3)),
                       arrival=["STALE_SUBBAR"], area_before=0)
    Clock(monkeypatch)
    with pytest.raises(RuntimeError, match="never seen"):
        T.walk_to_fight(sess, RecordingLog(), pathlib.Path("."), (12, 4),
                        _geo(), _geo())
    assert sess.blank_keys == [] and dumps == ["slums-arrival-failed"]


def test_an_unparsed_status_line_does_not_start_the_load_on_the_area_byte(
        monkeypatch):
    # The area reads the Slums and a stale New Phlan sub-bar is on row 24,
    # but the status line does not parse: nothing says the Slums are up.
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: 20)
    sess = WalkSession(monkeypatch, None, 20, (), (3, 4, 3), None,
                       arrival=[SUBBAR], facing_known=False)
    sess.arriving = True
    Clock(monkeypatch)
    with pytest.raises(RuntimeError, match="never seen"):
        T.await_slums(sess, RecordingLog(), pathlib.Path("."), 0, timeout=20)


def test_one_parsed_poll_is_not_enough_to_start_the_load(monkeypatch):
    # The status line parses on the first poll and not on the second, then
    # parses again: only two parsed polls running count.
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: 20)
    reads = iter([("N", (5, 5)), (None, None), ("N", (5, 5)),
                  ("N", (5, 5))])
    monkeypatch.setattr(T, "_status_line", lambda sess: next(reads))
    sess = WalkSession(monkeypatch, None, 20, (), (3, 4, 3), None,
                       arrival=[SUBBAR])
    sess.arriving = True
    Clock(monkeypatch)
    polls = []
    real = sess.screen
    sess.screen = lambda: polls.append(1) or real()
    assert T.await_slums(sess, RecordingLog(), pathlib.Path("."), 0) == "move"
    assert len(polls) == 4


class CombatIgnored(WalkSession):
    """`select_bar` answers `landed` but the fight never comes up."""

    landed = True

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        self.asked.append(label)
        return self.landed


@pytest.mark.parametrize("landed, words", [
    (True, "COMBAT was pressed"),
    (False, "COMBAT was attempted and did not land")])
def test_combat_is_pressed_at_most_once_however_long_the_bar_stays(
        monkeypatch, landed, words):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: 20)
    sess = CombatIgnored(monkeypatch, None, 20, (), (3, 4, 3), None,
                         arrival=["", "COMBAT WAIT FLEE ADVANCE"])
    sess.landed = landed
    sess.arriving = True
    Clock(monkeypatch)
    with pytest.raises(RuntimeError, match=words):
        T.await_slums(sess, RecordingLog(), pathlib.Path("."), 0, timeout=20)
    assert sess.asked == ["COMBAT"]


def test_the_combat_icon_is_read_every_two_seconds_not_every_poll(monkeypatch):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: 20)
    sess = WalkSession(monkeypatch, None, 20, (), (3, 4, 3), None,
                       arrival=[""])
    sess.arriving = True
    reads = []
    sess.in_combat = lambda: reads.append(1) or False
    clock = Clock(monkeypatch)
    with pytest.raises(RuntimeError):
        T.await_slums(sess, RecordingLog(), pathlib.Path("."), 0, timeout=20)
    assert clock.now >= 20 and len(reads) == 10


def test_an_area_load_that_never_ends_is_refused_with_a_screenshot(
        monkeypatch):
    dumps = []
    monkeypatch.setattr(T, "dump", lambda sess, out, log, tag: dumps.append(tag))
    first, _ = T.plan_fight_route(_geo(), _geo(), (3, 4), (12, 4))
    monkeypatch.setattr(T, "resident_area", lambda sess, log=None: sess.area)
    sess = WalkSession(monkeypatch, None, 20, (), (3, 4, 3),
                       len(geowalk.keys_for(first, 3)), arrival=[""])
    clock = Clock(monkeypatch)
    log = RecordingLog()
    with pytest.raises(RuntimeError, match=r"row 24 reads '', area 20"):
        T.walk_to_fight(sess, log, pathlib.Path("."), (12, 4), _geo(), _geo())
    assert dumps == ["slums-arrival-failed"]
    failed = [w for kind, w in log.events if kind == "slums_arrival_failed"]
    assert failed == [{"row24": "", "area": 20, "started": True,
                       "fight_taken": False}]
    assert T.SLUMS_ARRIVAL_WAIT <= clock.now < T.SLUMS_ARRIVAL_WAIT + 5
    assert sess.blank_keys == []


def test_a_fight_rolled_on_arrival_is_the_fight(monkeypatch):
    # Measured: `COMBAT WAIT FLEE ADVANCE` over `YOU SPY A GROUP OF
    # SEEDY-LOOKING GOBLINS.` 64 s after the edge key.
    sess, log, got = _walk(monkeypatch, fight_after=None,
                           arrival=["", "", "COMBAT WAIT FLEE ADVANCE"])
    assert sess.asked == ["COMBAT"] and sess.blank_keys == []
    assert got == {"in_combat": True, "began_at": list(T.SLUMS_ENTRY),
                   "at_target": False, "desynced": None}
    edge = next(w for kind, w in log.events if kind == "edge")
    assert edge["arrived"] == "fight"


def test_a_fight_on_arrival_is_returned_although_the_area_reads_the_fights_script(
        monkeypatch):
    # During a fight the area slot reads 100, not the Slums' 20.
    sess, log, got = _walk(monkeypatch, fight_after=None, area=100,
                           arrival=["", "", "COMBAT WAIT FLEE ADVANCE"])
    assert got == {"in_combat": True, "began_at": list(T.SLUMS_ENTRY),
                   "at_target": False, "desynced": None}
    edge = next(w for kind, w in log.events if kind == "edge")
    assert edge["arrived"] == "fight" and edge["area"] == 100


def test_a_press_bar_during_the_load_is_answered(monkeypatch):
    sess, log, got = _walk(monkeypatch, fight_after=None,
                           arrival=["", "PRESS RETURN OR BUTTON TO CONTINUE",
                                    WORLD])
    assert sess.pressed == [0x0D] and sess.blank_keys == []
    assert got["desynced"] is None


def test_every_slums_step_logs_the_status_line(monkeypatch):
    sess, log, got = _walk(monkeypatch, fight_after=None)
    seen = [e for e in log.events if e[0] == "slums_status"]
    assert seen and seen[0][1]["facing"] is not None


# -- what a square's script leaves on screen after a step ---------------------

PRESS = "PRESS <RETURN> OR BUTTON TO CONTINUE"
ENCOUNTER = "COMBAT WAIT FLEE ADVANCE"


class StepScript(WalkSession):
    """A Slums walk south from (5,5) whose square script runs after key
    `after_key`: row 24 reads `rows`, one entry per `screen()` read, the last
    repeating.  `on_press` replaces them when Return is pressed, and a
    `"<fight>"` entry brings the fight up.  A key sent while the script's row
    is not a walkable bar is refused, as `walk_one` refuses it."""

    def __init__(self, monkeypatch, after_key, rows, on_press=None,
                 on_combat=None):
        super().__init__(monkeypatch, None, 20, (), (5, 5, 2), None)
        self.after_key, self.script = after_key, list(rows)
        self.on_press, self.on_combat = on_press, on_combat

    def _live(self):
        return len(self.keys) >= self.after_key and bool(self.script)

    def _arrival_row(self):
        return self.script[0] if self._live() else WORLD

    def screen(self):
        if self.fighting:
            return Screen("")
        if not self._live():
            return Screen(WORLD)
        row = self.script[0]
        if len(self.script) > 1:
            self.script.pop(0)
        if row == "<fight>":
            self.fighting = True
            return Screen("")
        return Screen(row)

    def press_kernal(self, code):
        super().press_kernal(code)
        if self.on_press is not None:
            self.script = list(self.on_press)

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        if label == "COMBAT" and self.on_combat is not None:
            self.asked.append(label)
            self.script = list(self.on_combat)
            return True
        return super().select_bar(label, row, timeout, answer_prompts)

    def walk_one(self, key, *a, **k):
        # `_stop_walk`: at an encounter menu nothing is pressed for the key,
        # and the caller's word is taken.
        self.walk_stop_screen = None
        row = self._arrival_row()
        if (self._live() and self.walk_encounter
                and S.word_column(row, self.walk_encounter) >= 0):
            self.blank_keys.append(key)
            self.walk_stop_screen = ("",) * 24 + (row,)
            self.select_bar(self.walk_encounter)
            self.walk_refused = ("the driver pressed nothing: an encounter "
                                 "menu; it answered COMBAT")
            return False
        return super().walk_one(key, *a, **k)


SOUTH = [(5, 5), (5, 6), (5, 7), (5, 8)]


def _script_walk(monkeypatch, rows, on_press=None, after_key=1,
                 on_combat=None):
    dumps = []
    monkeypatch.setattr(T, "dump", lambda sess, out, log, tag: dumps.append(tag))
    sess = StepScript(monkeypatch, after_key, rows, on_press, on_combat)
    sess.walk_encounter = S.ENCOUNTER_FIGHT
    clock = Clock(monkeypatch)
    log = RecordingLog()
    got = T.walk_route(sess, log, SOUTH, 2, "slums", pathlib.Path("."))
    return sess, log, got, dumps, clock


def test_a_surprise_after_a_step_is_answered_and_is_the_fight(monkeypatch):
    # `ECL14`'s surprise: the monster loads with row 24 blank, its line prints
    # over a PRESS bar, and the fight loads after the Return.
    sess, log, got, dumps, _ = _script_walk(
        monkeypatch, ["", "", PRESS], on_press=["", "", "<fight>"])
    assert sess.pressed == [0x0D] and sess.blank_keys == []
    assert sess.keys == ["I"] and got == (2, (5, 6), None)


def test_an_encounter_menu_after_a_step_takes_combat_once(monkeypatch):
    sess, log, got, dumps, _ = _script_walk(
        monkeypatch, ["", ENCOUNTER, ENCOUNTER, ENCOUNTER, "<fight>"])
    assert sess.asked == ["COMBAT"] and sess.blank_keys == []
    assert got == (2, (5, 6), None)


def test_a_message_that_clears_back_to_the_bar_lets_the_walk_go_on(
        monkeypatch):
    sess, log, got, dumps, _ = _script_walk(monkeypatch, ["", "", "", WORLD])
    assert sess.keys == ["I", "I", "I"] and sess.blank_keys == []
    assert got == (2, None, None) and sess.pressed == []


def test_a_choice_after_a_step_stops_the_walk_and_presses_nothing(
        monkeypatch):
    sess, log, got, dumps, _ = _script_walk(monkeypatch,
                                            ["", "LEAVE TALK ATTACK"])
    assert sess.keys == ["I"] and sess.blank_keys == []
    assert sess.asked == [] and sess.pressed == []
    assert got[1] is None and got[2]["reason"] == "choice"
    assert got[2]["row24"] == "LEAVE TALK ATTACK" and got[2]["to"] == [5, 6]
    assert dumps == ["slums-choice-5-6"]


def test_a_screen_that_never_clears_stops_the_walk_within_the_limit(
        monkeypatch):
    sess, log, got, dumps, clock = _script_walk(monkeypatch, [""])
    assert sess.keys == ["I"] and sess.blank_keys == []
    assert got[2]["reason"] == "unsettled" and got[2]["row24"] == ""
    assert T.STEP_SETTLE_WAIT <= clock.now < T.STEP_SETTLE_WAIT + 5
    assert dumps == ["slums-unsettled-5-6"]


def test_a_script_after_a_turn_is_waited_out_before_the_step(monkeypatch):
    # Facing west, the step south turns left first: `J`, then `I`.
    dumps = []
    monkeypatch.setattr(T, "dump", lambda sess, out, log, tag: dumps.append(tag))
    sess = StepScript(monkeypatch, 1, ["", "", WORLD])
    sess.facing = 3
    Clock(monkeypatch)
    got = T.walk_route(sess, RecordingLog(), [(5, 5), (5, 6)], 3, "slums")
    assert sess.keys == ["J", "I"] and sess.blank_keys == []
    assert got == (2, None, None)


def test_a_key_refused_after_a_stale_bar_is_sent_again_once_the_bar_is_back(
        monkeypatch):
    # The bar from before the script is still up when the step's wait reads
    # it, and the script blanks row 24 only afterwards (`full13`, (14,7)).
    sess, log, got, dumps, _ = _script_walk(
        monkeypatch, [WORLD, WORLD, "", "", "", WORLD])
    assert sess.blank_keys == ["I"] and sess.keys == ["I", "I", "I"]
    assert got == (2, None, None)
    retries = [w for kind, w in log.events if kind == "route_retry"]
    assert len(retries) == 1 and retries[0]["to"] == [5, 7]


def test_an_encounter_the_refused_key_met_is_waited_into_the_fight(
        monkeypatch):
    # `full14`, (14,4): the next key met `COMBAT WAIT FLEE PARLAY`, `walk_one`
    # took COMBAT, and the fight was still loading when it returned.
    sess, log, got, dumps, _ = _script_walk(
        monkeypatch, [WORLD, WORLD, "COMBAT WAIT FLEE PARLAY"],
        on_combat=["", "", "<fight>"])
    assert sess.asked == ["COMBAT"] and sess.keys == ["I"]
    assert got == (2, (5, 6), None)


def test_a_refused_key_at_a_choice_keeps_its_refusal_and_names_the_choice(
        monkeypatch):
    sess, log, got, dumps, _ = _script_walk(
        monkeypatch, [WORLD, WORLD, "", "LEAVE TALK ATTACK"])
    assert sess.keys == ["I"] and sess.asked == [] and sess.pressed == []
    assert got[2]["reason"] == "not_pressed" and got[2]["after"] == "choice"
    assert got[2]["row24"] == "LEAVE TALK ATTACK"
    assert dumps == ["slums-choice-5-7"]


def test_a_press_bar_that_return_never_clears_is_given_up_on(monkeypatch):
    sess, log, got, dumps, clock = _script_walk(
        monkeypatch, ["", PRESS], on_press=[PRESS])
    assert got[1] is None and got[2]["reason"] == "unsettled"
    assert sess.pressed == [0x0D] * T.MAX_PRESSES
    assert clock.now < T.STEP_SETTLE_WAIT + 5


def test_the_last_steps_encounter_behind_a_stale_bar_is_the_fight(monkeypatch):
    # The bar from before the script stays up for 1.5 s (three reads) and the
    # last step's encounter menu opens behind it.
    sess, log, got, dumps, _ = _script_walk(
        monkeypatch, [WORLD] * 3 + [ENCOUNTER] * 3, after_key=3)
    assert sess.asked == ["COMBAT"] and sess.keys == ["I", "I", "I"]
    assert got == (2, (5, 8), None)


def test_an_encounter_menu_that_outlasts_combat_is_a_choice(monkeypatch):
    sess, log, got, dumps, clock = _script_walk(
        monkeypatch, ["", ENCOUNTER], on_combat=[ENCOUNTER])
    assert sess.asked == ["COMBAT"] and sess.pressed == []
    assert got[1] is None and got[2]["reason"] == "choice"
    assert clock.now < T.STEP_SETTLE_WAIT


def test_a_fight_loading_behind_the_drawn_menu_after_combat_is_the_fight(
        monkeypatch):
    dumps = []
    monkeypatch.setattr(T, "dump", lambda sess, out, log, tag: dumps.append(tag))
    sess = StepScript(monkeypatch, 1, ["", ENCOUNTER], None, [ENCOUNTER])
    sess.walk_encounter = S.ENCOUNTER_FIGHT
    clock = Clock(monkeypatch)
    sess.in_combat = lambda: clock.now >= 3.0
    got = T.walk_route(sess, RecordingLog(), SOUTH, 2, "slums")
    assert sess.asked == ["COMBAT"]
    assert got == (2, (5, 6), None)


def test_the_retry_after_a_refused_key_keeps_the_last_steps_quiet_hold(
        monkeypatch):
    quiets = []
    real = T.settle_step

    def spy(sess, log, key, there, **kw):
        quiets.append(kw.get("quiet"))
        return real(sess, log, key, there, **kw)

    monkeypatch.setattr(T, "settle_step", spy)
    # The last step's key is refused behind a stale bar, then goes.
    _script_walk(monkeypatch, [WORLD, WORLD, "", "", WORLD], after_key=2)
    assert quiets[-2:] == [T.FINAL_QUIET, T.FINAL_QUIET]


def test_a_fight_before_the_load_is_seen_is_new_phlans_not_the_slums(
        monkeypatch):
    # The edge step rolled a fight in New Phlan: combat is up on the first
    # poll, row 24 never blank, no disk prompt, the area unchanged.
    first, _ = T.plan_fight_route(_geo(), _geo(), (3, 4), (12, 4))
    edge_key = (len(first) - 1) + 1
    sess, log, got = _walk(monkeypatch, fight_after=edge_key, area_before=20,
                           arrival=["STALE"])
    assert got == {"in_combat": True, "began_at": list(T.NEW_PHLAN_EXIT),
                   "at_target": False, "desynced": None}
    edge = next(w for kind, w in log.events if kind == "edge")
    assert edge["arrived"] == "fight_before_edge"
    assert sess.asked == []


# -- the combat screenshot waits for a party member's command bar -------------

class FightScreen(PatrolSession):
    """`combat_state` answers the scripted kinds one poll at a time, the last
    repeating; `battle()` returns `party` as combatants.  After a Return a
    PRESS bar stays up for `fade` more polls unless `await_change` is called,
    as the real prompt does; `disk` is the wanted-disk answer."""

    def __init__(self, monkeypatch, kinds, party=(), fade=0, disk=None):
        super().__init__(monkeypatch)
        self.kinds, self.polls, self.pressed = list(kinds), 0, []
        self.party, self.fade, self.disk = party, fade, disk
        self.fading, self.handled, self.waited = 0, [], 0

    def screen(self):
        return Screen("row")

    def wanted_disk(self, s):
        return self.disk

    def handle_prompt(self, s=None):
        self.handled.append(s)
        self.disk = None
        return True

    def await_change(self, was, timeout=6.0, interval=0.4):
        self.waited += 1
        self.fading = 0

    def combat_state(self, s=None):
        self.polls += 1
        if self.fading:
            self.fading -= 1
            return S.CombatBar(S.BAR_PRESS, "row " + S.BAR_PRESS)
        kind = self.kinds[0]
        if len(self.kinds) > 1:
            self.kinds.pop(0)
        return S.CombatBar(kind, "row " + kind)

    def press_kernal(self, code):
        self.pressed.append(code)
        self.fading = self.fade

    def battle(self):
        class _Who:
            def __init__(self, name, square):
                self.name, self.square = name, square

        class _Battle:
            party = tuple(_Who(n, q) for n, q in self.party)

        return _Battle()


def _photograph(monkeypatch, kinds, **kw):
    sess = FightScreen(monkeypatch, kinds, **kw)
    seen = []
    monkeypatch.setattr(
        T, "dump", lambda sess_, out, log, name: seen.append((name, sess_.polls)))
    clock = Clock(monkeypatch)
    log = RecordingLog()
    got = T.photograph_fight(sess, pathlib.Path("."), log)
    return sess, log, seen, clock, got


def test_the_combat_shot_waits_for_the_command_bar(monkeypatch):
    sess, log, seen, clock, got = _photograph(
        monkeypatch, [S.BAR_NONE, S.BAR_MESSAGE, S.BAR_COMMAND],
        party=[("BULWARK", (3, 4)), ("PILFER", (4, 4))])
    assert got is True
    assert seen == [("combat-icon", 3)]
    assert clock.now < T.FIGHT_WAIT
    assert ("fight_screen", {"battlefield": True, "presses": 0, "party": [
        {"name": "BULWARK", "square": [3, 4]},
        {"name": "PILFER", "square": [4, 4]}]}) in log.events


def test_a_press_prompt_on_the_way_gets_a_return(monkeypatch):
    sess, log, seen, clock, got = _photograph(
        monkeypatch, [S.BAR_PRESS, S.BAR_MOVE])
    assert sess.pressed == [13]
    assert seen == [("combat-icon", 2)] and got is True


def test_no_command_bar_is_recorded_and_the_shot_is_still_taken(monkeypatch):
    sess, log, seen, clock, got = _photograph(monkeypatch, [S.BAR_NONE])
    assert got is False
    assert [n for n, _ in seen] == ["combat-icon"]
    assert T.FIGHT_WAIT <= clock.now < T.FIGHT_WAIT + 5
    (kind, what), = [e for e in log.events if e[0] == "fight_screen"]
    assert what["battlefield"] is False and what["row24"] == "row " + S.BAR_NONE


def test_a_fight_already_up_is_photographed_only_once_its_command_bar_is(
        monkeypatch):
    sess = FightScreen(monkeypatch, [S.BAR_NONE, S.BAR_NONE, S.BAR_COMMAND])
    sess.fighting = True
    seen = []
    monkeypatch.setattr(
        T, "dump", lambda sess_, out, log, name: seen.append((name, sess_.polls)))
    Clock(monkeypatch)
    got = T.pick_a_fight(sess, RecordingLog(), pathlib.Path("."), steps=3)
    assert got["in_combat"] is True
    assert seen == [("combat-icon", 3)]


def test_a_monsters_turn_does_not_count_as_the_battlefield(monkeypatch):
    sess, log, seen, clock, got = _photograph(
        monkeypatch, [S.BAR_BLANK, S.BAR_BLANK, S.BAR_MOVE])
    assert got is True and seen == [("combat-icon", 3)]


def test_return_is_pressed_at_most_the_limit_and_the_shot_still_comes(
        monkeypatch):
    sess, log, seen, clock, got = _photograph(monkeypatch, [S.BAR_PRESS])
    assert got is False
    assert sess.pressed == [13] * T.FIGHT_PRESS_LIMIT
    assert [n for n, _ in seen] == ["combat-icon"]


def test_a_prompt_that_fades_slowly_gets_one_return(monkeypatch):
    sess, log, seen, clock, got = _photograph(
        monkeypatch, [S.BAR_PRESS, S.BAR_COMMAND], fade=2)
    assert sess.pressed == [13] and sess.waited == 1 and got is True


def test_a_disk_prompt_goes_to_the_disk_handler_not_return(monkeypatch):
    # A PRESS row that is also a disk prompt: only `wanted_disk` tells them apart.
    sess, log, seen, clock, got = _photograph(
        monkeypatch, [S.BAR_PRESS, S.BAR_COMMAND], disk="SIDE 3")
    assert sess.pressed == [] and len(sess.handled) == 1 and got is True


# -- a locked door on the way -------------------------------------------------

DOOR = "BASH PICKLOCK QUIT"


class DoorScript(StepScript):
    """`StepScript` whose script is a locked door until QUIT is taken, when the
    world bar comes back (or `after_quit`).  `asked` lists every bar word
    selected.  With `doors`, the bar comes up instead after each of those
    numbered keys (1-based) and QUIT clears it."""

    def __init__(self, monkeypatch, rows, after_quit=None, doors=None,
                 after_key=None):
        super().__init__(monkeypatch,
                         after_key if after_key is not None
                         else 0 if doors else 1, rows)
        self.after_quit = [WORLD] if after_quit is None else after_quit
        self.doors, self.at_door = set(doors or ()), False

    def _arrival_row(self):
        if self.doors:
            return DOOR if self.at_door else WORLD
        return super()._arrival_row()

    def screen(self):
        if self.doors and not self.fighting:
            return Screen(DOOR if self.at_door else WORLD)
        return super().screen()

    def walk_one(self, key, *a, **k):
        moved = super().walk_one(key, *a, **k)
        if self.doors and len(self.keys) in self.doors and \
                key not in "JK" and moved:
            self.at_door = True
        return moved

    def select_bar(self, label, row=24, timeout=30.0, answer_prompts=True):
        if label == "QUIT":
            self.asked.append(label)
            self.at_door = False
            self.script = list(self.after_quit)
            return True
        return super().select_bar(label, row, timeout, answer_prompts)


def _door_walk(monkeypatch, replan, rows=("", DOOR), path=SOUTH, facing=2,
               **fake):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    sess = DoorScript(monkeypatch, list(rows), **fake)
    sess.coords = False      # the Slums' status line has no square
    sess.facing = facing
    sess.walk_encounter = S.ENCOUNTER_FIGHT
    Clock(monkeypatch)
    log = RecordingLog()
    got = T.walk_route(sess, log, path, facing, "slums", pathlib.Path("."),
                       replan)
    return sess, log, got


def test_a_locked_door_is_answered_with_quit_once_and_never_bash_or_picklock(
        monkeypatch):
    sess, log, got = _door_walk(
        monkeypatch, lambda here, square: [here, (6, 5), (6, 6)])
    assert sess.asked == ["QUIT"] and sess.pressed == []
    doors = [w for kind, w in log.events if kind == "locked_door"]
    assert len(doors) == 1 and doors[0]["square"] == [5, 6]
    assert got[1] is None and got[2] is None


def test_the_replanned_route_keeps_off_the_locked_square(monkeypatch):
    asked = []

    def replan(here, square):
        asked.append((here, square))
        return T.geowalk.route(_geo(), here, (5, 8), avoid={square})

    sess, log, got = _door_walk(monkeypatch, replan)
    assert asked == [((5, 5), (5, 6))]
    path = next(w["path"] for kind, w in log.events
                if kind == "route_replanned")
    assert path[0] == [5, 5] and path[-1] == [5, 8] and [5, 6] not in path
    assert got == (2, None, None)


def test_a_locked_door_with_no_route_round_it_records_the_refused_square(
        monkeypatch):
    sess, log, got = _door_walk(monkeypatch, lambda here, square: None)
    assert sess.asked == ["QUIT"]
    assert got[1] is None and got[2]["reason"] == "locked_door"
    assert got[2]["square"] == [5, 6] and got[2]["from"] == [5, 5]
    assert "(5, 6)" in got[2]["refused"]
    assert sess.keys == ["I"]


def test_the_keys_after_a_replan_match_the_partys_real_facing(monkeypatch):
    # Facing south at the door; the detour goes east then south.
    sess, log, got = _door_walk(
        monkeypatch, lambda here, square: [here, (6, 5), (6, 6)])
    assert sess.keys == ["I", "J", "I", "K", "I"]
    assert sess.facing == 2 and got == (2, None, None)


def test_a_fight_after_quit_is_the_fight_not_a_desync(monkeypatch):
    sess, log, got = _door_walk(monkeypatch, lambda here, square: SOUTH,
                                after_quit=["<fight>"])
    assert sess.asked == ["QUIT"]
    assert got == (2, (5, 5), None)


def test_a_second_door_on_the_replanned_route_is_avoided_too(monkeypatch):
    # Key 1 is the first door; key 3 is the first step of the detour.  The
    # synthetic map has one way round, so the second replan finds none: what
    # matters is that it ran once each, with both squares in `avoid`.
    avoids = []
    real = T.geowalk.route

    def route(geo, start, goal, avoid=frozenset()):
        avoids.append(set(avoid))
        return real(geo, start, goal, avoid=avoid)

    monkeypatch.setattr(T.geowalk, "route", route)
    sess, log, got = _door_walk(
        monkeypatch, T.slums_replanner(_geo(), (5, 8)), doors={1, 3})
    assert sess.asked == ["QUIT", "QUIT"] and len(avoids) == 2
    assert {(5, 6)} <= avoids[0] and not {(4, 5)} & avoids[0]
    assert {(5, 6), (4, 5)} <= avoids[1]
    assert got[2]["reason"] == "locked_door" and got[2]["square"] == [4, 5]


def test_a_locked_target_square_has_no_route_and_is_refused(monkeypatch):
    # The door is on the last step, onto the target itself.
    sess, log, got = _door_walk(
        monkeypatch, T.slums_replanner(_geo(), (5, 8)), doors={3})
    assert sess.asked == ["QUIT"]
    assert got[1] is None and got[2]["reason"] == "locked_door"
    assert got[2]["square"] == [5, 8] and "(5, 8)" in got[2]["refused"]


def test_a_locked_door_after_a_refused_key_is_answered_with_quit(
        monkeypatch):
    sess, log, got = _door_walk(
        monkeypatch,
        lambda here, square: [here, (here[0] + 1, here[1]),
                              (here[0] + 1, here[1] + 1)],
        rows=(WORLD, WORLD, "", DOOR))
    assert sess.blank_keys == ["I"] and sess.asked == ["QUIT"]
    assert got[1] is None and got[2] is None


def test_a_door_bar_after_a_refused_turn_is_not_answered(monkeypatch):
    # No turn was made, so the walk cannot plan from the facing it assumed.
    sess, log, got = _door_walk(
        monkeypatch, lambda here, square: [here, (6, 5)],
        rows=(DOOR,), path=[(5, 5), (5, 6)], facing=3, after_key=0)
    assert sess.asked == [] and sess.keys == []
    assert got[2]["reason"] == "not_pressed" and got[2]["after"] == "choice"


def test_a_bar_missing_a_door_word_is_not_answered_with_quit(monkeypatch):
    sess, log, got = _door_walk(
        monkeypatch, lambda here, square: [here, (6, 5)],
        rows=("", "BASH QUIT"))
    assert sess.asked == [] and got[2]["reason"] == "choice"


class EncounterAfterKey(WalkSession):
    """The first `I` is sent and the square's script puts up `bar` after
    `walk_one` has left: it says the party did not move and refuses nothing
    (`full18`, (14,4)).  `triple` is what the live square reads."""

    def __init__(self, monkeypatch, bar=ENCOUNTER, triple=(5, 5, 2)):
        super().__init__(monkeypatch, None, 20, (), (5, 5, 2), None)
        self.coords, self.encounter = False, False
        self.bar, self.triple = bar, triple

    def walk_one(self, key, *a, **k):
        self.walk_refused = None
        self.keys.append(key)
        self.encounter = True
        return False

    def steady_triple(self, seconds=None):
        if isinstance(self.triple, Exception):
            raise self.triple
        return self.triple

    def screen(self):
        if self.encounter and not self.fighting:
            return Screen(self.bar)
        return super().screen()


def _unmoved(monkeypatch, **fake):
    monkeypatch.setattr(T, "dump", lambda *a, **k: None)
    sess = EncounterAfterKey(monkeypatch, **fake)
    sess.walk_encounter = S.ENCOUNTER_FIGHT
    clock = Clock(monkeypatch)
    log = RecordingLog()
    return sess, log, T.walk_route(sess, log, SOUTH, 2, "slums"), clock


def test_an_encounter_menu_after_a_key_that_did_not_move_is_the_fight(
        monkeypatch):
    sess, log, got, _ = _unmoved(monkeypatch)
    assert got == (2, (5, 5), None)
    assert sess.asked == ["COMBAT"] and sess.keys == ["I"]


def test_the_fight_after_an_unmoved_key_is_on_the_live_square(monkeypatch):
    # An encounter rolled on arrival: the status did not change, but the
    # party stands on the next square.
    sess, log, got, _ = _unmoved(monkeypatch, triple=(5, 6, 2))
    assert got == (2, (5, 6), None)
    assert not [k for k, _ in log.events if k == "fight_square_assumed"]


def test_an_unreadable_live_square_is_assumed_and_logged(monkeypatch):
    for triple in (None, OSError("monitor gone")):
        sess, log, got, _ = _unmoved(monkeypatch, triple=triple)
        assert got == (2, (5, 5), None)
        assumed = [w for k, w in log.events if k == "fight_square_assumed"]
        assert len(assumed) == 1 and assumed[0]["square"] == [5, 5]


def test_a_wall_after_a_sent_key_keeps_its_desync_and_presses_nothing(
        monkeypatch):
    sess, log, got, _ = _unmoved(monkeypatch, bar=WORLD)
    assert got == (2, None, {"leg": "slums", "key": "i", "from": [5, 5],
                             "to": [5, 6]})
    assert sess.asked == [] and sess.pressed == []


def test_a_choice_after_an_unmoved_key_is_left_alone(monkeypatch):
    sess, log, got, _ = _unmoved(monkeypatch, bar="LEAVE TALK ATTACK")
    assert got[1] is None and got[2]["key"] == "i" and "reason" not in got[2]
    assert sess.asked == [] and sess.pressed == []


def test_a_press_bar_after_an_unmoved_key_is_left_to_the_wait(monkeypatch):
    # A PRESS bar is answered by the wait, as after any key; a bar that stays
    # gives up with the desync once the short limit runs out.
    sess, log, got, clock = _unmoved(monkeypatch, bar=PRESS)
    assert got[1] is None and "reason" not in got[2]
    assert sess.asked == []
    assert clock.now < T.UNMOVED_SETTLE_WAIT + 5


def test_an_unsettled_unmoved_key_gives_up_within_the_short_limit(monkeypatch):
    sess, log, got, clock = _unmoved(monkeypatch, bar="")
    assert got[1] is None and "reason" not in got[2]
    assert clock.now < T.UNMOVED_SETTLE_WAIT + 5 < T.STEP_SETTLE_WAIT
    logged = [w for k, w in log.events if k == "unmoved_key_unsettled"]
    assert len(logged) == 1 and logged[0]["outcome"] == "unsettled"
