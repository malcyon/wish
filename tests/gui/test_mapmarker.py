"""`tools/gui/mapmarker.py`'s live-walk logic, over fakes for the session and the map.

The stage 6 boots of #11 ended at an outdoor encounter's `COMBAT WAIT FLEE
PARLAY` bar the driver could not answer, and logged neither `$033D` nor the
mapper's window and heading.  Nothing here boots an emulator: the fakes give
the screens, the bytes and the fight, and the tests check what the driver does
with them.
"""

from __future__ import annotations

import argparse
import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tools.c64 import session as S
from tools.gui import mapmarker as M

ENCOUNTER = "COMBAT WAIT FLEE PARLAY"
GRID = "1-8, RETURN OR BUTTON"


class Screen:
    def __init__(self, row24):
        self.row24 = row24

    def row(self, n):
        return self.row24 if n == 24 else ""


class Mon:
    def __init__(self, mem):
        self.mem = mem

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, addr, length):
        return bytes(self.mem.get(addr + i, 0) for i in range(length))


class Log:
    def __init__(self):
        self.events = []

    def say(self, text):
        pass

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def of(self, kind):
        return [f for k, f in self.events if k == kind]


class Sess:
    """`bars` maps the number of presses so far to the row 24 then showing."""

    def __init__(self, encounter_on=(), fight_outcome=S.WON):
        self.mem = {0x033D: 0xFF, 0x49C3: 4, 0x49C4: 27}
        self.presses = []
        self.encounter_on = set(encounter_on)
        self.fight_outcome = fight_outcome
        self.fights = []
        self.selected = []
        self.row = GRID
        self.inside = False

    def mon(self, timeout=5.0):
        return Mon(self.mem)

    def screen(self):
        return Screen(self.row)

    def walk_one(self, move):
        self.presses.append(move)
        self.mem[0x033D] = int(move) - 1
        self.mem[0x49C3] -= 1
        self.row = ENCOUNTER if len(self.presses) in self.encounter_on else GRID
        return True

    def select_bar(self, label, timeout=8):
        self.selected.append(label)
        self.row = "COMBAT"
        return True

    def in_combat(self):
        return True

    def fight(self, budget, tactic):
        self.fights.append((budget, tactic))
        self.row = GRID
        self.mem[0x033D] = 8
        return SimpleNamespace(outcome=self.fight_outcome, turns=3, blows=2,
                               seconds=1.0, bars=["a"])

    def handle_prompt(self, s=None):
        return False

    def indoors(self):
        return self.inside


def args(**kw):
    base = dict(on_encounter="fight", fight_budget=123.0, encounter_wait=5.0,
                encounters=0, stopped=False)
    base.update(kw)
    return argparse.Namespace(**base)


def no_sleep(monkeypatch):
    monkeypatch.setattr(M.time, "sleep", lambda s: None)


def test_encounter_is_fought_with_a_bound_and_the_walk_resumes(monkeypatch):
    no_sleep(monkeypatch)
    sess, log, seen = Sess(encounter_on={2}), Log(), []
    step = M.walk_moves(args(), sess, log, "7777", 0, seen.append)
    assert sess.presses == ["7", "7", "7", "7"]
    assert sess.selected == [S.ENCOUNTER_FIGHT]
    assert sess.fights == [(123.0, S.Session.melee_turn)]
    enc = log.of("encounter")[0]
    assert enc["step"] == 2 and enc["move"] == "7" and enc["bar"] == ENCOUNTER
    assert log.of("encounter_outcome")[0]["outcome"] == S.WON
    # A look after the fight, before the next key, carries its own step number.
    assert seen == [1, 3, 4, 5] and step == 5


def test_stop_leaves_the_bar_alone_and_ends_the_walk(monkeypatch):
    no_sleep(monkeypatch)
    sess, log = Sess(encounter_on={2}), Log()
    M.walk_moves(args(on_encounter="stop"), sess, log, "7777", 0, lambda n: None)
    assert sess.presses == ["7", "7"]
    assert sess.selected == [] and sess.fights == []
    assert log.of("encounter")[0]["handled"] == "stop"


def test_a_fight_that_is_not_won_back_to_the_grid_stops_the_walk(monkeypatch):
    no_sleep(monkeypatch)
    sess = Sess(encounter_on={1}, fight_outcome=S.NOT_FIGHTING)
    M.walk_moves(args(), sess, Log(), "777", 0, lambda n: None)
    assert sess.presses == ["7"]


def test_each_press_logs_the_heading_byte_before_and_after(monkeypatch):
    no_sleep(monkeypatch)
    sess, log = Sess(), Log()
    M.walk_moves(args(), sess, log, "7", 0, lambda n: None)
    walk = log.of("walk")[0]
    assert walk["before"]["heading_033D"] == "ff"
    assert walk["after"]["heading_033D"] == "06"
    assert walk["before"]["travel_49C3"] == "041b"
    assert walk["after"]["travel_49C3"] == "031b"


def test_the_look_records_033d_and_the_mappers_window_and_heading():
    log, sess = Log(), Sess()
    binding = MagicMock()
    binding.LIVE_EVERY = 0
    binding.state.window, binding.state.heading = 1, 6
    binding.status_text.return_value = ""
    app = MagicMock()
    sess.kbd = MagicMock()
    sess.mem[0x033D] = 6
    seen = M.look(app, binding, "t", pathlib.Path("/nonexistent"), log, sess)
    assert seen["heading_033D"] == "06"
    assert seen["mapper_window"] == 1 and seen["mapper_heading"] == 6
    assert log.of("look")[0]["mapper_heading"] == 6


def test_turn_options_parse(monkeypatch, tmp_path):
    got = {}

    def fake_run(args_, log):
        got["a"] = args_
        return 0
    monkeypatch.setattr(M, "run", fake_run)
    monkeypatch.setattr(M, "_offscreen", lambda: None)
    monkeypatch.setattr(M, "Log", lambda path: LogClose())
    M.main(["--disk", "x.d64", "--disks", "/d", "--out", str(tmp_path),
            "--turn", "7", "--turns", "3", "--walk", "12"])
    assert got["a"].turn == "7" and got["a"].turns == 3
    assert got["a"].on_encounter == "fight"


class LogClose(Log):
    def close(self):
        pass


def test_turn_presses_log_the_heading_and_square_each_time(monkeypatch):
    no_sleep(monkeypatch)
    sess, log = Sess(), Log()
    M.walk_moves(args(), sess, log, "777", 0, lambda n: None)
    assert sess.presses == ["7", "7", "7"]
    walks = log.of("walk")
    assert [w["after"]["heading_033D"] for w in walks] == ["06"] * 3
    assert [w["after"]["travel_49C3"] for w in walks] == ["031b", "021b", "011b"]


def parse(monkeypatch, tmp_path, *extra):
    monkeypatch.setattr(M, "run", lambda a, log: 0)
    monkeypatch.setattr(M, "_offscreen", lambda: None)
    monkeypatch.setattr(M, "Log", lambda path: LogClose())
    return M.main(["--disk", "x.d64", "--disks", "/d", "--out", str(tmp_path),
                   *extra])


@pytest.mark.parametrize("bad", ["12", "9", "0", "x"])
def test_turn_takes_one_compass_digit(monkeypatch, tmp_path, bad):
    with pytest.raises(SystemExit):
        parse(monkeypatch, tmp_path, "--turn", bad)


@pytest.mark.parametrize("outcome", [S.LOST, S.BUDGET, S.NOT_FIGHTING])
def test_a_fight_that_ends_badly_stops_the_walk_even_on_the_grid(monkeypatch, outcome):
    no_sleep(monkeypatch)
    sess = Sess(encounter_on={1}, fight_outcome=outcome)
    a = args()
    M.walk_moves(a, sess, Log(), "777", 0, lambda n: None)
    assert sess.presses == ["7"]
    assert outcome in a.stopped


def test_a_fight_the_party_ran_from_resumes_the_walk(monkeypatch):
    no_sleep(monkeypatch)
    sess = Sess(encounter_on={1}, fight_outcome=S.RAN)
    a = args()
    M.walk_moves(a, sess, Log(), "777", 0, lambda n: None)
    assert sess.presses == ["7", "7", "7"] and not a.stopped


def test_the_sixth_encounter_is_logged_and_not_fought(monkeypatch):
    no_sleep(monkeypatch)
    sess = Sess(encounter_on=set(range(1, 10)))
    a = args()
    M.walk_moves(a, sess, Log(), "7" * 9, 0, lambda n: None)
    assert len(sess.fights) == M.MAX_ENCOUNTERS
    assert len(sess.presses) == M.MAX_ENCOUNTERS + 1
    assert "limit" in a.stopped


@pytest.mark.parametrize("row", ["THE PARTY MEETS COMBAT ORDERS", GRID,
                                 "COMBAT WAIT", ""])
def test_a_row_that_is_not_the_encounter_menu_is_not_one(row):
    sess = Sess()
    sess.row = row
    assert M.encounter_bar(sess) is None


def test_the_encounter_menu_is_not_taken_for_one_indoors():
    sess = Sess()
    sess.row = ENCOUNTER
    sess.inside = True
    assert M.encounter_bar(sess) is None
    sess.inside = False
    assert M.encounter_bar(sess) == ENCOUNTER


def test_a_step_that_lands_on_the_grid_takes_one_look_not_three(monkeypatch):
    slept = []
    monkeypatch.setattr(M.time, "sleep", slept.append)
    looks = []
    sess = Sess()
    real = sess.screen
    sess.screen = lambda: looks.append(1) or real()
    assert M.encounter_after_press(sess) is None
    assert len(looks) == 1 and slept == []


def test_press_state_reads_only_the_two_bytes_it_logs():
    sess, asked = Sess(), []
    real = Mon.read
    Mon.read = lambda self, addr, n: asked.append(addr) or real(self, addr, n)
    try:
        M.press_state(sess)
    finally:
        Mon.read = real
    assert sorted(asked) == [0x033D, 0x49C3]


class RunSess(Sess):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.kbd = MagicMock()

    def boot(self):
        return True

    def load_save(self):
        return True

    def select_row(self, label):
        return True

    def status(self):
        return None

    def settle(self, n):
        pass

    def close(self):
        pass


def run_args(tmp_path, **kw):
    return args(disk="x.d64", disks=str(tmp_path), slot=None, tag="t",
                out=str(tmp_path), answer="NO", arrive=1.0, turn="",
                turns=1, walk="7777", travel=26, after="1", home=20,
                place=None, arrival=None, linger=2, **kw)


def test_a_stopped_walk_skips_travel_after_home_and_linger(monkeypatch, tmp_path):
    no_sleep(monkeypatch)
    sess, called, looks = RunSess(encounter_on={2}), [], []
    slot = MagicMock(n=1, display=":1", dir=str(tmp_path))
    monkeypatch.setattr(M.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(M.S, "stage_disks", lambda *a, **k: None)
    monkeypatch.setattr(M.S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(M.S, "Session", lambda *a, **k: sess)
    monkeypatch.setattr(M, "answer_bars", lambda *a, **k: "world")
    monkeypatch.setattr(M, "SessionTarget", lambda s: MagicMock())
    monkeypatch.setattr(M, "build_window",
                        lambda *a: (MagicMock(), MagicMock(), MagicMock(), []))
    monkeypatch.setattr(M, "look", lambda app, b, tag, *a: looks.append(tag))
    monkeypatch.setattr(M, "come_home", lambda *a, **k: called.append("home"))
    monkeypatch.setattr(M.actions, "FastTravel",
                        lambda: called.append("travel") or MagicMock())
    log = Log()
    a = run_args(tmp_path, on_encounter="stop")
    assert M.run(a, log) == 1
    assert called == []
    assert log.of("walk_stopped")[0]["reason"] == "--on-encounter stop"
    assert sess.presses == ["7", "7"]
    assert looks[-1] == "t-step3"                # one last look, no lingering
