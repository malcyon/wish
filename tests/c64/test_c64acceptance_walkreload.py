"""Pool `walk-fight` bar ownership under `--fight-watch`, and `--walk-reload` /
`--reload-lost-fights`, which pass an encounter by restoring the snapshot
taken before its key and sending the key again with the area's gate held."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from goldbox.c64_port import POOL_OF_RADIANCE
from tools.c64 import acceptance as A

SLUMS = 0x14


def _rows(panel: str, bar: str = "MOVE VIEW AIM QUICK DONE") -> list[str]:
    """A combat screen whose right-hand panel shows PANEL, drawn as the game
    draws it: the frame at column 22, the name inside it on row 2."""
    rows = ["$" + " " * 21 + "$" + " " * 16 + "$"] * 25
    rows = list(rows)
    rows[0] = "%" + "[" * 21 + "%" + "[" * 16 + "$"
    rows[2] = "$" + " " * 21 + "$" + panel.ljust(16) + "$"
    rows[4] = "$" + " " * 21 + "$" + ("HIT POINTS 7" if panel else "").ljust(16) + "$"
    rows[24] = bar
    return rows


class _Screen:
    def __init__(self, rows):
        self.rows = rows

    def row(self, r):
        return self.rows[r]


class _Monitor:
    def __init__(self, memory):
        self.memory = memory

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, address, length):
        return bytes(self.memory.get(address + i, 0) for i in range(length))

    def resume(self):
        pass


class _Keyboard:
    def screenshot(self, path):
        open(path, "wb").close()


def _who(name, index):
    return SimpleNamespace(name=name, index=index, x=index, y=2, slot=index,
                           on_map=True, hp=6, side=0, is_party=True)


class _Session:
    """BARS is a list of (panel at the bar, [panels shown before the next
    bar]); the battle read names whoever's name the panel shows, unless
    `acting_override` says otherwise."""

    def __init__(self, bars, party, outcome=A.S.WON, area=SLUMS):
        self.bars, self.party, self.outcome = bars, party, outcome
        self.kbd = _Keyboard()
        self.shown = None
        self.memory = {A.S.AREA_BYTE[POOL_OF_RADIANCE.key].addr: area}
        self.acting_override = {}
        self.calls = []
        self.no_encounters = self.draw_keeping_gates = False
        self.fought = 0

    def screen(self):
        return self.shown

    def battle(self):
        return SimpleNamespace(combatants=self.party, characters=self.party)

    def acting(self, battle, s=None):
        panel = A.panel_name([s.row(r) for r in range(25)])
        if panel in self.acting_override:
            return self.acting_override[panel]
        return next((c for c in battle.characters if c.name == panel), None)

    def mon(self, timeout):
        return _Monitor(self.memory)

    def fight(self, budget, tactic, stop=None, poll=1.0):
        self.fought += 1
        for panel, between in self.bars:
            self.shown = _Screen(_rows(panel))
            tactic(self, A.S.CombatBar(A.S.BAR_COMMAND, "MOVE VIEW AIM QUICK DONE"))
            for other in between:
                stop(self, _Screen(_rows(other, bar="")))
        return A.S.FightResult(self.outcome, len(self.bars), 1.0, [], [])

    def in_combat(self):
        return False

    def snapshot(self, name):
        self.calls.append(("snapshot", name))
        return name

    def restore(self, name):
        self.calls.append(("restore", name))

    def discard_snapshot(self, name):
        self.calls.append(("discard", name))

    def attach(self, path):
        self.calls.append(("attach", path))

    attached = "staged.D64"

    def suppress_encounters(self):
        self.calls.append(("suppress", self.no_encounters))

    def restore_encounter_gates(self):
        # As the real one: it turns the switch off itself.
        self.calls.append(("gates-restored", self.draw_keeping_gates))
        self.no_encounters = False
        return [{"address": "$9B65", "verified": True}]


def _run(tmp_path, monkeypatch, sess, watch="EVOKER"):
    run = A.PoolRun(sess, A.Log(tmp_path), tmp_path, POOL_OF_RADIANCE, {})
    run.fight_watch = watch
    run.to_world = lambda: True
    run.position = lambda: [8, 3, 3]
    run.walk_side_prompts, run.walk_side_open = [], set()
    run.walk_crossed = None
    run.watch_reads = lambda name: {}
    monkeypatch.setattr(A.S.Session, "melee_turn", lambda s, bar: "MOVE")
    return run


def _events(run, tmp_path):
    run.log.close()
    return [json.loads(line) for line in (tmp_path / "run.jsonl").read_text().splitlines()]


PARTY = [_who("EVOKER", 0), _who("WISHHEL", 1), _who("WISHFTR", 6)]


# -- bar ownership ------------------------------------------------------------

def test_panel_name_reads_the_name_inside_the_frame_and_nothing_else():
    assert A.panel_name(_rows("WISHHEL")) == "WISHHEL"
    assert A.panel_name(_rows("GOBLIN GUARD")) == "GOBLIN GUARD"
    assert A.panel_name(_rows("")) == ""
    assert A.panel_name([]) == ""


def test_each_bar_names_its_owner_and_the_fight_counts_them(tmp_path, monkeypatch):
    sess = _Session([("WISHHEL", ["EVOKER", "EVOKER", "GOBLIN"]),
                     ("WISHFTR", []), ("WISHHEL", [])], PARTY)
    run = _run(tmp_path, monkeypatch, sess)
    fights = []
    run._fight_out(0, fights, [], False, A.S.ENCOUNTER_FIGHT, 0)
    events = _events(run, tmp_path)
    bars = [e for e in events if e.get("kind") == "fight-watch"]
    assert [(b["shown"], b["owner_read"], b["watched_owner"]) for b in bars] == [
        ("WISHHEL", True, False), ("WISHFTR", True, False), ("WISHHEL", True, False)]
    (end,) = [e for e in events if e.get("kind") == "fight-watch-end"]
    assert end["bar_owners"] == {"WISHHEL": 2, "WISHFTR": 1}
    assert (end["watched_bars"], end["unread_bars"]) == (0, 0)
    # A turn the engine runs shows its name once however many reads it lasts.
    assert end["panel_names_between_bars"] == {"EVOKER": 1, "GOBLIN": 1}
    assert fights[0]["bar_owners"] == {"WISHHEL": 2, "WISHFTR": 1}
    assert run.bar_ownership == {
        "name": "EVOKER", "fights": 1, "bars": 3, "watched_bars": 0,
        "unread_bars": 0, "owners": {"WISHHEL": 2, "WISHFTR": 1},
        "panel_names_between_bars": {"EVOKER": 1, "GOBLIN": 1},
        "established": True}


def test_a_bar_the_watched_member_owns_is_counted_as_his(tmp_path, monkeypatch):
    sess = _Session([("WISHHEL", []), ("EVOKER", [])], PARTY)
    run = _run(tmp_path, monkeypatch, sess)
    run._fight_out(0, [], [], False, A.S.ENCOUNTER_FIGHT, 0)
    assert run.bar_ownership["watched_bars"] == 1
    assert run.bar_ownership["established"] is True


def test_a_blank_panel_or_a_battle_read_that_disagrees_leaves_it_unestablished(
        tmp_path, monkeypatch):
    sess = _Session([("WISHHEL", []), ("", []), ("WISHFTR", [])], PARTY)
    sess.acting_override = {"WISHFTR": PARTY[1]}
    run = _run(tmp_path, monkeypatch, sess)
    run._fight_out(0, [], [], False, A.S.ENCOUNTER_FIGHT, 0)
    bars = [e for e in _events(run, tmp_path) if e.get("kind") == "fight-watch"]
    assert [b["owner_read"] for b in bars] == [True, False, False]
    assert run.bar_ownership["unread_bars"] == 2
    assert run.bar_ownership["established"] is False


def test_two_fights_add_up_and_a_lost_one_counts_too(tmp_path, monkeypatch):
    sess = _Session([("WISHHEL", [])], PARTY)
    run = _run(tmp_path, monkeypatch, sess)
    fights = []
    run._fight_out(0, fights, [], False, A.S.ENCOUNTER_FIGHT, 0)
    sess.outcome = A.S.LOST
    sess.bars = [("WISHFTR", []), ("WISHHEL", [])]
    with pytest.raises(A.StepFailed):
        run._fight_out(5, fights, [], False, A.S.ENCOUNTER_FIGHT, 0)
    assert run.bar_ownership["fights"] == 2 and run.bar_ownership["bars"] == 3
    assert run.bar_ownership["owners"] == {"WISHHEL": 2, "WISHFTR": 1}


# -- reloads ------------------------------------------------------------------

def _armed(run, n=3, move="I"):
    run.walk_reload_armed = (n, move, [13, 7, 2], 0)


def test_an_armed_encounter_is_reloaded_and_recorded(tmp_path, monkeypatch):
    sess = _Session([], PARTY)
    run = _run(tmp_path, monkeypatch, sess)
    run.walk_reload = 2
    _armed(run)
    with pytest.raises(A.WalkReloaded):
        run.reload_if_armed("encounter", 3, [])
    assert sess.calls == [("restore", A.WALK_RELOAD_SNAPSHOT), ("attach", "staged.D64")]
    assert run.walk_reloads == [{
        "reload": "encounter", "step": "walk-fight", "at_move": 3, "move": "I",
        "square": [13, 7, 2], "area": SLUMS, "screen": ""}]
    assert run.walk_reload_counts == {"encounter": 1}
    assert run.walk_reload_armed is None
    assert [e["kind"] for e in _events(run, tmp_path)] == ["walk-reload"]


@pytest.mark.parametrize("why", ["off", "other move", "cap used", "side prompt",
                                 "crossed"])
def test_no_reload_without_a_snapshot_for_this_move_or_reloads_left(
        tmp_path, monkeypatch, why):
    sess = _Session([], PARTY)
    run = _run(tmp_path, monkeypatch, sess)
    run.walk_reload = 0 if why == "off" else 1
    _armed(run, n=4 if why == "other move" else 3)
    if why == "cap used":
        run.walk_reload_counts = {"encounter": 1}
    if why == "side prompt":
        run.walk_side_prompts = [{"side": "2"}]
    if why == "crossed":
        run.walk_crossed = {"position": [0, 0, 0]}
    run.reload_if_armed("encounter", 3, [])
    assert sess.calls == [] and run.walk_reloads is None


@pytest.mark.parametrize("area", [0x7E, 0x06])
def test_an_area_with_no_draw_keeping_gate_stops_the_step_rather_than_replay(
        tmp_path, monkeypatch, area):
    # 0x06's alarm gate skips the roll's draw, so a reload could not pass it.
    sess = _Session([], PARTY, area=area)
    run = _run(tmp_path, monkeypatch, sess)
    run.walk_reload = 1
    _armed(run)
    with pytest.raises(A.StepFailed,
                       match=rf"area \${area:02X}, which has no encounter gate that lets"):
        run.reload_if_armed("encounter", 3, [])
    assert sess.calls == []


def test_the_encounter_reload_comes_before_the_fight_is_fought(tmp_path, monkeypatch):
    sess = _Session([("WISHHEL", [])], PARTY)
    run = _run(tmp_path, monkeypatch, sess)
    run.walk_reload = 1
    _armed(run)
    with pytest.raises(A.WalkReloaded):
        run._fight_out(3, [], [], False, A.S.ENCOUNTER_FIGHT, 0)
    assert sess.fought == 0


def test_a_lost_fight_is_kept_then_reloaded(tmp_path, monkeypatch):
    sess = _Session([("WISHHEL", []), ("WISHFTR", [])], PARTY, outcome=A.S.LOST)
    run = _run(tmp_path, monkeypatch, sess)
    run.reload_lost_fights = 1
    _armed(run)
    fights = []
    with pytest.raises(A.WalkReloaded):
        run._fight_out(3, fights, [], False, A.S.ENCOUNTER_FIGHT, 0)
    assert sess.fought == 1
    (lost,) = fights
    assert lost["reloaded"] is True and lost["outcome"] == A.S.LOST
    assert lost["bar_owners"] == {"WISHHEL": 1, "WISHFTR": 1}
    assert run.walk_reloads[0]["reload"] == "lost"


def test_an_encounter_menu_is_reloaded_before_it_is_answered_and_a_question_is_not(
        tmp_path, monkeypatch):
    sess = _Session([], PARTY)
    run = _run(tmp_path, monkeypatch, sess)
    run.walk_reload = 1
    answered = []
    run._answer_stop = lambda *a: answered.append(a[4][24])
    run._fight_opens = lambda: True
    question = [""] * 24 + ["YES NO"]
    _armed(run)
    run._take_stop("I", 3, "I", [13, 7, 2], question, False, None,
                   A.S.ENCOUNTER_FIGHT, [])
    assert answered == ["YES NO"] and sess.calls == []
    menu = [""] * 24 + ["COMBAT WAIT FLEE ADVANCE"]
    with pytest.raises(A.WalkReloaded):
        run._take_stop("I", 3, "I", [13, 7, 2], menu, False, None,
                       A.S.ENCOUNTER_FIGHT, [])
    assert answered == ["YES NO"]


def test_a_pass_is_snapshotted_only_when_a_reload_option_is_on(tmp_path, monkeypatch):
    sess = _Session([], PARTY)
    run = _run(tmp_path, monkeypatch, sess)
    seen = []
    run._walk_fight_key = lambda *a: seen.append(run.walk_reload_armed) or False
    run._walk_fight_pass(False, "I", 3, "I", [13, 7, 2], None, None, [])
    assert sess.calls == [] and seen == [None]
    run.reload_lost_fights = 1
    run._walk_fight_pass(False, "I", 3, "I", [13, 7, 2], None, None, [])
    assert sess.calls == [("snapshot", A.WALK_RELOAD_SNAPSHOT)]
    assert seen[-1] == (3, "I", [13, 7, 2], 0) and run.walk_reload_armed is None


def test_a_held_pass_holds_the_gate_for_its_key_and_verifies_it_after(
        tmp_path, monkeypatch):
    sess = _Session([], PARTY)
    run = _run(tmp_path, monkeypatch, sess)
    run.walk_reload = 1
    run._walk_fight_key = lambda *a: sess.calls.append(
        ("key", sess.no_encounters, sess.draw_keeping_gates)) or False
    run._walk_fight_pass(True, "I", 3, "I", [13, 7, 2], None, None, [])
    assert sess.calls == [("suppress", True), ("key", True, True), ("gates-restored", False)]
    assert sess.no_encounters is False and sess.draw_keeping_gates is False
    assert run.gate_reports[-1]["verified"] is True


@pytest.mark.parametrize("fails", [False, True])
def test_a_held_pass_leaves_an_outer_no_encounters_switch_on(tmp_path, monkeypatch, fails):
    sess = _Session([], PARTY)
    sess.no_encounters = True
    run = _run(tmp_path, monkeypatch, sess)
    run.walk_reload = 1

    def key(*a):
        if fails:
            raise A.StepFailed("blocked")
        return False

    run._walk_fight_key = key
    try:
        run._walk_fight_pass(True, "I", 3, "I", [13, 7, 2], None, None, [])
    except A.StepFailed:
        assert fails
    assert sess.no_encounters is True and sess.draw_keeping_gates is False


def test_a_held_key_logs_the_gate_readback_and_whether_the_generator_drew(
        tmp_path, monkeypatch):
    sess = _Session([], PARTY)
    limit = A.S.POOL_SLUMS_ROLL_AT + A.S.POOL_SLUMS_ROLL_LIMIT
    sess.memory.update({limit: 0x0C, **{0x03C2 + i: i for i in range(7)}})
    sess.suppress_encounters = lambda: sess.memory.update({limit: 0xFF})
    run = _run(tmp_path, monkeypatch, sess)
    run.walk_reload = 1
    run.walk_reloads = [{"reload": "encounter", "at_move": 3}]
    run._walk_fight_key = lambda *a: sess.memory.update({0x03C8: 0x63}) or False
    run._walk_fight_pass(True, "I", 3, "I", [13, 7, 2], None, None, [])
    (held,) = [e for e in _events(run, tmp_path) if e.get("kind") == "walk-reload-held"]
    assert held["gate_bytes"] == [{"address": f"${limit:04X}", "written": 0xFF, "read": 0xFF}]
    assert held["generator_before"] == "00 01 02 03 04 05 06"
    assert held["generator_after"] == "00 01 02 03 04 05 63"
    assert held["drew"] is True and held["gates_restored"][0]["verified"] is True
    assert run.walk_reloads[-1]["held"]["drew"] is True


def test_a_held_key_that_leaves_the_generator_alone_says_it_did_not_draw(
        tmp_path, monkeypatch):
    sess = _Session([], PARTY)
    run = _run(tmp_path, monkeypatch, sess)
    run._walk_fight_key = lambda *a: False
    run._walk_fight_pass(True, "I", 3, "I", [13, 7, 2], None, None, [])
    (held,) = [e for e in _events(run, tmp_path) if e.get("kind") == "walk-reload-held"]
    assert held["drew"] is False


def test_a_held_pass_puts_the_gate_back_when_its_key_fails(tmp_path, monkeypatch):
    sess = _Session([], PARTY)
    run = _run(tmp_path, monkeypatch, sess)

    def boom(*a):
        raise A.StepFailed("blocked")

    run._walk_fight_key = boom
    with pytest.raises(A.StepFailed, match="blocked"):
        run._walk_fight_pass(True, "I", 3, "I", [13, 7, 2], None, None, [])
    assert sess.calls[-1] == ("gates-restored", False) and sess.no_encounters is False
    assert sess.draw_keeping_gates is False
    held = [e for e in _events(run, tmp_path) if e.get("kind") == "walk-reload-held"]
    assert len(held) == 1 and held[0]["drew"] is None


def test_the_walk_sends_a_reloaded_key_again_held_and_counts_one_send(
        tmp_path, monkeypatch):
    sess = _Session([], PARTY)
    run = _run(tmp_path, monkeypatch, sess)
    run.walk_reload = 1
    squares = iter([[13, 7, 2], [13, 8, 2], [13, 8, 2], [13, 8, 2]])
    run.position = lambda: next(squares)
    run.budget = lambda *a: None
    run.answer_side_prompt = lambda *a, **k: False
    run.crossing_move = lambda *a: False
    run.bar = lambda: "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"
    run.capture = lambda *a, **k: []
    judged = []
    run._judge_walk_fight = lambda *a: judged.append(a)
    held = []

    def key(route, n, move, before, *rest):
        held.append(sess.no_encounters)
        if len(held) == 1:
            run.reload_if_armed("encounter", n, [])
        return False

    run._walk_fight_key = key
    got = run._walk_fight("I", None)
    assert held == [False, True]
    assert got["moves"] == [{"move": "I", "before": [13, 7, 2], "after": [13, 8, 2],
                             "moved": True, "resent": False}]
    assert [r["reload"] for r in run.walk_reloads] == ["encounter"]
    assert judged and judged[0][5] is False  # not resent


@pytest.mark.parametrize("option", ["--walk-reload", "--reload-lost-fights"])
def test_the_reload_options_need_a_pool_walk_fight_and_a_count(tmp_path, capsys, option):
    for argv, message in (
            (["--title", "pool", "--steps", "load", "walk I", option, "1"],
             "requires --title pool and a walk-fight"),
            (["--title", "curse", "--steps", "load", "fight 60", option, "1"],
             "requires --title pool and a walk-fight"),
            (["--title", "pool", "--steps", "load", "walk-fight I", option, "-1"],
             "cannot be negative")):
        with pytest.raises(SystemExit) as info:
            A.main(["--save", str(tmp_path / "x.d64"), "--out", str(tmp_path / "o"),
                    *argv])
        assert info.value.code == 2
        assert message in capsys.readouterr().err
