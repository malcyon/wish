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
from support.automapbanks import CHIPS_OUT, a_machine

from tools.c64 import session as S
from tools.gui import mapmarker as M


@pytest.fixture(autouse=True)
def _forget_banks():
    """Bank ids are cached per monitor; each test gets its own machine."""
    from automap import vice
    vice._BANKS.clear()
    yield
    vice._BANKS.clear()


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

    def wanted_disk(self, s):
        return None

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


def test_a_failed_indoors_read_is_logged_and_is_no_encounter():
    sess, log = Sess(), Log()
    sess.row = ENCOUNTER

    def boom():
        raise RuntimeError("boot failed")
    sess.indoors = boom
    assert M.encounter_bar(sess, log) is None
    assert "boot failed" in log.of("indoors_read_failed")[0]["error"]


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
    base = dict(disk="x.d64", disks=str(tmp_path), slot=None, tag="t",
                out=str(tmp_path), answer="NO", arrive=1.0, turn="",
                turns=1, walk="7777", travel=26, after="1", home=20,
                place=None, start=None, arrival=None, linger=2)
    base.update(kw)
    return args(**base)


def test_a_stopped_walk_skips_travel_after_home_and_linger(monkeypatch, tmp_path):
    no_sleep(monkeypatch)
    sess, called, looks = RunSess(encounter_on={2}), [], []
    slot = MagicMock(n=1, display=":1", dir=str(tmp_path))
    monkeypatch.setattr(M.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(M.S, "stage_disks", lambda *a, **k: None)
    monkeypatch.setattr(M.S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(M.S, "Session", lambda *a, **k: sess)
    monkeypatch.setattr(M, "answer_bars", lambda *a, **k: "world")
    monkeypatch.setattr(M, "SessionTarget", lambda s, **k: MagicMock())
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


def test_a_stop_during_the_after_walk_ends_the_run_before_home(monkeypatch, tmp_path):
    no_sleep(monkeypatch)
    sess, called, looks = RunSess(encounter_on={1}), [], []
    slot = MagicMock(n=1, display=":1", dir=str(tmp_path))
    monkeypatch.setattr(M.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(M.S, "stage_disks", lambda *a, **k: None)
    monkeypatch.setattr(M.S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(M.S, "Session", lambda *a, **k: sess)
    monkeypatch.setattr(M, "answer_bars", lambda *a, **k: "world")
    monkeypatch.setattr(M, "clear_bars", lambda *a, **k: "world")
    monkeypatch.setattr(M, "SessionTarget", lambda s, **k: MagicMock())
    monkeypatch.setattr(M, "build_window",
                        lambda *a: (MagicMock(), MagicMock(), MagicMock(), []))
    monkeypatch.setattr(M, "look", lambda app, b, tag, *a: looks.append(tag))
    monkeypatch.setattr(M, "come_home", lambda *a, **k: called.append("home"))

    def travel():
        called.append("travel")
        return MagicMock(apply=lambda *a, **k: SimpleNamespace(ok=True, message=""))
    monkeypatch.setattr(M.actions, "FastTravel", travel)
    log = Log()
    a = run_args(tmp_path, on_encounter="stop", walk="")
    assert M.run(a, log) == 1
    assert called == ["travel"]
    assert sess.presses == ["1"]
    assert log.of("walk_stopped")[0]["reason"] == "--on-encounter stop"
    assert looks[-1] == "t-step3"        # step0, the trip's look, the press, then the stop


class FleeSess(Sess):
    """An outdoor bar that offers FLEE; `flee_works` says whether the bar's own FLEE escapes."""

    def __init__(self, offers_flee=True, flee_works=True, **kw):
        super().__init__(**kw)
        self.offers_flee, self.flee_works = offers_flee, flee_works
        self.combat = False

    def select_bar(self, label, timeout=8):
        self.selected.append(label)
        if label == "FLEE" and not self.offers_flee:
            return False
        self.combat = label != "FLEE" or not self.flee_works
        self.row = GRID if not self.combat else "COMBAT"
        return True

    def in_combat(self):
        return self.combat


def fake_clock(monkeypatch):
    """A clock that moves one second per reading, so a timed wait costs no real time."""
    ticks = iter(range(10**6))
    monkeypatch.setattr(M, "time", SimpleNamespace(time=lambda: float(next(ticks)),
                                                   sleep=lambda s: None))


def test_flee_is_selected_when_the_bar_offers_it_and_the_walk_resumes(monkeypatch):
    fake_clock(monkeypatch)
    sess, log, seen = FleeSess(encounter_on={2}), Log(), []
    a = args(on_encounter="flee")
    M.walk_moves(a, sess, log, "7777", 0, seen.append)
    assert sess.selected == ["FLEE"] and sess.fights == []
    assert sess.presses == ["7", "7", "7", "7"] and not a.stopped
    assert log.of("encounter_choice")[0]["choice"] == "flee"
    assert log.of("encounter_outcome")[0]["outcome"] == S.RAN


def test_a_flee_that_leaves_no_travel_prompt_stops_the_walk(monkeypatch):
    fake_clock(monkeypatch)
    sess = FleeSess(encounter_on={1})
    select = sess.select_bar

    def select_then_blank(label, timeout=8):
        select(label, timeout)
        sess.row = ""                # neither a combat grid nor a travel prompt
        return True
    sess.select_bar = select_then_blank
    a, log = args(on_encounter="flee"), Log()
    M.walk_moves(a, sess, log, "777", 0, lambda n: None)
    assert log.of("encounter_grid")[0]["outcome"] == "stuck"
    assert "stuck" in a.stopped and sess.presses == ["7"]


def test_a_flee_that_fails_fights_with_flight_in_budget_and_a_lost_one_stops(monkeypatch):
    no_sleep(monkeypatch)
    sess = FleeSess(flee_works=False, encounter_on={1}, fight_outcome=S.BUDGET)
    a = args(on_encounter="flee")
    M.walk_moves(a, sess, Log(), "777", 0, lambda n: None)
    assert sess.presses == ["7"] and S.BUDGET in a.stopped
    budget, tactic = sess.fights[0]
    assert budget == 123.0 and isinstance(tactic, M.Flight)


def test_flee_falls_back_to_a_flight_fight_when_the_bar_has_no_flee(monkeypatch):
    no_sleep(monkeypatch)
    sess, log = FleeSess(offers_flee=False, encounter_on={1}, fight_outcome=S.RAN), Log()
    a = args(on_encounter="flee")
    M.walk_moves(a, sess, log, "777", 0, lambda n: None)
    assert sess.selected == ["FLEE", S.ENCOUNTER_FIGHT]
    assert isinstance(sess.fights[0][1], M.Flight)
    assert log.of("encounter_choice")[0]["choice"] == "flee-unavailable"
    assert sess.presses == ["7", "7", "7"] and not a.stopped


def test_the_default_encounter_answer_is_still_fight(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["x", "--disk", "a.d64", "--disks", str(tmp_path)])
    seen = {}
    monkeypatch.setattr(M, "run", lambda a, log: seen.update(v=a.on_encounter) or 0)
    M.main(["--disk", "a.d64", "--disks", str(tmp_path), "--out", str(tmp_path)])
    assert seen["v"] == "fight"


class BankSession:
    def __init__(self, mon):
        self._mon = mon

    def mon(self, timeout=5.0):
        return self._mon


def test_read_blocks_reads_the_bank_a_block_names():
    mon = a_machine(port1=CHIPS_OUT)
    target = M.SessionTarget(BankSession(mon))
    out = target.read_blocks([(0xD018, 1, "io"), (0xD018, 1, "ram"), (0x0400, 1)])
    assert out[0] != out[1]
    banks = [bank for addr, _n, bank in mon.asked if addr == 0xD018]
    assert 3 in banks and 1 in banks


PROMPT = "INSERT SIDE # 6, AND PRESS ANY KEY."


class DiskSess(Sess):
    """The second press raises a disk prompt; `handle_prompt` swaps the side."""

    def __init__(self, side, moves_on_prompt=True, attach_raises=False,
                 finishes_on_answer=False):
        super().__init__()
        self.finishes_on_answer = finishes_on_answer
        self.side = side
        self.moves_on_prompt = moves_on_prompt
        self.attach_raises = attach_raises
        self.answered = 0

    def walk_one(self, move):
        self.presses.append(move)
        if len(self.presses) == 2 and self.answered == 0:
            self.row = PROMPT
            if self.moves_on_prompt:
                self.mem[0x49C3] = 14
            return True
        self.mem[0x49C3] -= 1
        self.row = GRID
        return True

    def wanted_disk(self, s):
        return str(self.side) if PROMPT in s.row(24) else None

    def handle_prompt(self, s=None):
        if PROMPT not in self.row:
            return False
        if self.attach_raises:
            raise AssertionError("refusing to attach")
        self.answered += 1
        self.row = GRID
        if self.finishes_on_answer:
            self.mem[0x49C3] -= 1                   # the interrupted step completes
        return True


def test_a_disk_prompt_is_answered_and_the_walk_resumes(monkeypatch, tmp_path):
    no_sleep(monkeypatch)
    side = tmp_path / "SIDE6.D64"
    side.write_bytes(b"")
    sess, log, seen = DiskSess(side), Log(), []
    a = args()
    M.walk_moves(a, sess, log, "777", 0, seen.append)
    assert sess.answered == 1 and not a.stopped
    assert sess.presses == ["7", "7", "7"]          # the party moved: no repeat
    event = log.of("disk_prompt")[0]
    assert event["side"] == "SIDE6.D64" and event["outcome"] == "world"
    assert event["moved"] is True
    assert seen == [1, 2, 3]                        # a look after the swap


class EncounterAfterDiskSess(DiskSess):
    """Answering the prompt leaves `after` on row 24 instead of the grid."""

    def __init__(self, side, after=ENCOUNTER, **kw):
        super().__init__(side, **kw)
        self.after = after

    def handle_prompt(self, s=None):
        answered = super().handle_prompt(s)
        if answered:
            self.row = self.after
        return answered


def test_an_encounter_after_a_disk_answer_is_fought_and_the_walk_resumes(monkeypatch, tmp_path):
    fake_clock(monkeypatch)
    side = tmp_path / "SIDE6.D64"
    side.write_bytes(b"")
    sess, log, seen = EncounterAfterDiskSess(side), Log(), []
    a = args()
    M.walk_moves(a, sess, log, "777", 0, seen.append)
    assert not a.stopped and sess.answered == 1
    assert len(sess.fights) == 1 and sess.fights[0][0] == 123.0
    assert sess.presses == ["7", "7", "7"] and a.encounters == 1
    assert log.of("disk_prompt")[0]["outcome"] == "encounter"
    assert log.of("encounter")[0]["bar"] == ENCOUNTER
    assert log.of("encounter_outcome")[0]["outcome"] == S.WON
    assert log.of("encounter_grid")[0]["outcome"] == "world"
    assert seen == [1, 2, 3]                        # a look once the walk resumes


def test_a_stop_after_a_disk_answer_leaves_the_encounter_alone(monkeypatch, tmp_path):
    fake_clock(monkeypatch)
    side = tmp_path / "SIDE6.D64"
    side.write_bytes(b"")
    sess, a = EncounterAfterDiskSess(side), args(on_encounter="stop")
    M.walk_moves(a, sess, Log(), "777", 0, lambda n: None)
    assert sess.fights == [] and a.stopped == "--on-encounter stop"


def test_another_stuck_row_after_a_disk_answer_still_stops_the_walk(monkeypatch, tmp_path):
    fake_clock(monkeypatch)
    side = tmp_path / "SIDE6.D64"
    side.write_bytes(b"")
    sess, log = EncounterAfterDiskSess(side, after="SOMETHING ELSE"), Log()
    a = args()
    M.walk_moves(a, sess, log, "777", 0, lambda n: None)
    assert "no travel prompt after SIDE6.D64 (stuck)" in a.stopped
    assert sess.fights == [] and sess.presses == ["7", "7"]


def test_a_press_the_prompt_ate_is_pressed_once_more(monkeypatch, tmp_path):
    no_sleep(monkeypatch)
    side = tmp_path / "SIDE6.D64"
    side.write_bytes(b"")
    sess, log = DiskSess(side, moves_on_prompt=False), Log()
    M.walk_moves(args(), sess, log, "77", 0, lambda n: None)
    assert sess.presses == ["7", "7", "7"]
    assert log.of("walk_repeated")


def test_a_side_that_is_not_in_the_slot_stops_the_walk(monkeypatch, tmp_path):
    no_sleep(monkeypatch)
    sess, log = DiskSess(tmp_path / "SIDE6.D64"), Log()
    a = args()
    M.walk_moves(a, sess, log, "777", 0, lambda n: None)
    assert "SIDE6.D64" in a.stopped and sess.presses == ["7", "7"]
    assert sess.answered == 0
    assert log.of("disk_prompt")[0]["outcome"] == "no-such-disk"


def test_a_side_that_cannot_be_attached_stops_the_walk(monkeypatch, tmp_path):
    no_sleep(monkeypatch)
    side = tmp_path / "SIDE6.D64"
    side.write_bytes(b"")
    sess, log = DiskSess(side, attach_raises=True), Log()
    a = args()
    M.walk_moves(a, sess, log, "777", 0, lambda n: None)
    assert "could not be attached" in a.stopped and sess.presses == ["7", "7"]
    assert log.of("disk_prompt")[0]["outcome"].startswith("attach-failed")


def test_a_step_the_game_finishes_after_the_answer_is_not_repeated(monkeypatch, tmp_path):
    no_sleep(monkeypatch)
    side = tmp_path / "SIDE6.D64"
    side.write_bytes(b"")
    sess, log = DiskSess(side, moves_on_prompt=False, finishes_on_answer=True), Log()
    M.walk_moves(args(), sess, log, "77", 0, lambda n: None)
    assert sess.answered == 1 and sess.presses == ["7", "7"]
    assert not log.of("walk_repeated")


def test_a_failed_read_after_the_answer_does_not_repeat_the_press(monkeypatch, tmp_path):
    no_sleep(monkeypatch)
    side = tmp_path / "SIDE6.D64"
    side.write_bytes(b"")
    sess, log = DiskSess(side, moves_on_prompt=False), Log()
    real = M.press_state

    def flaky(s):
        return real(s) if s.answered == 0 else {"travel_49C3": None, "error": "timeout"}
    monkeypatch.setattr(M, "press_state", flaky)
    M.walk_moves(args(), sess, log, "77", 0, lambda n: None)
    assert sess.presses == ["7", "7"] and not log.of("walk_repeated")
    assert log.of("walk_repeat_unread")[0]["error"] == "timeout"


def test_a_prompt_that_vanishes_while_retrying_is_no_prompt(monkeypatch, tmp_path):
    no_sleep(monkeypatch)
    side = tmp_path / "SIDE6.D64"
    side.write_bytes(b"")
    sess, log = DiskSess(side), Log()
    sess.row = PROMPT
    tries = []

    def refuse(s=None):
        tries.append(1)
        sess.row = GRID                             # gone by the next look
        return False
    sess.handle_prompt = refuse
    assert M.answer_disk_prompt(args(), sess, log, 1) == (False, None)
    assert len(tries) == 1 and not log.of("disk_prompt")


def start_run(monkeypatch, tmp_path, events, code=0, sess=None, corrupt=False, **kw):
    no_sleep(monkeypatch)
    sess = sess or RunSess()
    real_press = sess.walk_one
    sess.walk_one = lambda m: events.append(("press", m)) or real_press(m)
    slot = MagicMock(n=1, display=":1", dir=str(tmp_path))
    monkeypatch.setattr(M.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(M.S, "stage_disks", lambda *a, **k: None)
    monkeypatch.setattr(M.S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(M.S, "Session", lambda *a, **k: sess)
    monkeypatch.setattr(M, "answer_bars", lambda *a, **k: "world")

    class Target:
        def write(self, addr, data):
            events.append(("write", addr, bytes(data)))
            self.mem = bytes(data)

        def read(self, addr, n):
            return bytes(b ^ 1 for b in self.mem) if corrupt else self.mem

    monkeypatch.setattr(M, "SessionTarget", lambda s, **k: Target())
    monkeypatch.setattr(M, "build_window",
                        lambda *a: (MagicMock(), MagicMock(), MagicMock(), []))
    monkeypatch.setattr(M, "look",
                        lambda app, b, tag, *a: events.append(("look", tag)))
    log = Log()
    a = run_args(tmp_path, travel=None, after="", home=None, linger=0, **kw)
    assert M.run(a, log) == code
    return log


def test_start_writes_the_square_before_the_first_press_and_looks_after(monkeypatch, tmp_path):
    events = []
    log = start_run(monkeypatch, tmp_path, events, start=(3, 27), walk="77")
    assert events == [("look", "t-step0"), ("write", 0x49C3, bytes([3, 27])),
                      ("look", "t-step1"), ("press", "7"), ("look", "t-step2"),
                      ("press", "7"), ("look", "t-step3")]
    assert log.of("start") == [{"x": 3, "y": 27, "read_back": "031b"}]


def test_no_start_writes_nothing(monkeypatch, tmp_path):
    events = []
    start_run(monkeypatch, tmp_path, events, start=None, walk="7")
    assert not [e for e in events if e[0] == "write"]


@pytest.mark.parametrize("bad", ["3", "1,2,3", "256,1", "-1,4", "x,1"])
def test_start_refuses_a_square_that_is_not_two_bytes(monkeypatch, tmp_path, bad):
    with pytest.raises(SystemExit):
        parse(monkeypatch, tmp_path, "--start", bad)


def test_start_parses_a_square(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(M, "run", lambda a, log: seen.append(a.start) or 0)
    monkeypatch.setattr(M, "_offscreen", lambda: None)
    monkeypatch.setattr(M, "Log", lambda path: LogClose())
    M.main(["--disk", "x.d64", "--disks", "/d", "--out", str(tmp_path),
            "--start", "3,27"])
    assert seen == [(3, 27)]


def test_start_indoors_writes_nothing_and_stops_the_run(monkeypatch, tmp_path):
    events = []
    sess = RunSess()
    sess.inside = True
    log = start_run(monkeypatch, tmp_path, events, code=1, sess=sess,
                    start=(3, 27), walk="77")
    assert not [e for e in events if e[0] in ("write", "press")]
    assert "indoors" in log.of("start_refused")[0]["reason"]
    assert not log.of("start")


def test_start_with_an_unreadable_indoors_flag_writes_nothing(monkeypatch, tmp_path):
    events = []
    sess = RunSess()
    sess.indoors = lambda: None
    log = start_run(monkeypatch, tmp_path, events, code=1, sess=sess,
                    start=(3, 27), walk="77")
    assert not [e for e in events if e[0] in ("write", "press")]
    assert log.of("start_refused")


def test_start_read_back_mismatch_stops_the_run(monkeypatch, tmp_path):
    events = []
    log = start_run(monkeypatch, tmp_path, events, code=1, corrupt=True,
                    start=(3, 27), walk="77")
    assert log.of("start_mismatch") == [{"wrote": "031b", "read_back": "021a"}]
    assert not [e for e in events if e[0] == "press"]


class LateGridSess(Sess):
    """A session whose combat grid is up only once the fake clock passes `appears`."""

    def __init__(self, appears, **kw):
        super().__init__(**kw)
        self.appears = appears
        self.grid_seen_at = None

    def in_combat(self):
        up = M.time.time() >= self.appears
        if up and self.grid_seen_at is None:
            self.grid_seen_at = M.time.time()
        return up

    def fight(self, budget, tactic):
        assert self.grid_seen_at is not None, "fight asked before the grid was up"
        return super().fight(budget, tactic)


def test_a_grid_that_draws_after_thirty_seconds_is_waited_for_before_fighting(monkeypatch):
    fake_clock(monkeypatch)
    # The clock ticks once per reading, so the deadline is its first reading + 60.
    sess, log = LateGridSess(appears=40, encounter_on={1}), Log()
    a = args()
    M.walk_moves(a, sess, log, "77", 0, lambda n: None)
    assert len(sess.fights) == 1 and not a.stopped
    assert not log.of("fight_not_begun")


def test_a_grid_that_never_draws_stops_the_walk_with_fight_not_begun(monkeypatch):
    fake_clock(monkeypatch)
    sess, log = LateGridSess(appears=10**9, encounter_on={1}), Log()
    a = args()
    M.walk_moves(a, sess, log, "77", 0, lambda n: None)
    assert sess.fights == [] and a.stopped
    assert log.of("fight_not_begun")[0]["waited"] == M.FIGHT_GRID_WAIT
