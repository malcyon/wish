"""An area edge on a walk's last forward move, and a Dispel Magic the game
resists, driven on fakes with keys alone: nothing here writes memory."""

from __future__ import annotations

import pytest

from goldbox.c64_port import POOL_OF_RADIANCE
from tools.c64 import acceptance as A

PROMPT = "INSERT SIDE # 7, AND PRESS ANY KEY."
OTHER = "PRESS RETURN TO CONTINUE"


class _Screen:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text

    def row(self, r):
        return self._text if r == 24 else ""


class _Monitor:
    def __init__(self, sess):
        self.sess = sess

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, address, length):
        if address == A.AREA_AT:
            return bytes([self.sess.area])
        return bytes([0]) * length

    def resume(self):
        pass


class _Session:
    """The screen shows PROMPT until it is answered, and the area changes
    `after` reads later, as the game's load does."""

    def __init__(self, prompt=PROMPT, after=2, second=None):
        self.prompt, self.after, self.second = prompt, after, second
        self.area, self.answered, self.reads, self.attached = 24, 0, 0, []

    def screen(self):
        self.reads += 1
        if self.answered and self.reads - self.answered >= self.after:
            self.area = 26
            return _Screen(self.second) if self.second else _Screen("")
        return _Screen(self.prompt)

    def wanted_disk(self, screen):
        return "SIDE" in screen.text() and "INSERT" in screen.text()

    def handle_prompt(self, screen=None):
        self.answered = self.reads
        self.attached.append(screen.text())
        return True

    def mon(self, seconds):
        return _Monitor(self)


def _run(tmp_path, monkeypatch, sess):
    run = A.PoolRun(sess, A.Log(tmp_path), tmp_path, POOL_OF_RADIANCE, {})
    now = [0.0]
    run.clock = lambda: now[0]
    monkeypatch.setattr(A.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    run.budget = lambda *a, **k: 1
    run.capture = lambda *a, **k: []
    run.to_world = lambda: True
    run.bar = lambda: ""
    run.position = lambda: [15, 4, 2]
    run.crossed_position = lambda: [14, 27, None]
    run.edge_crossing = True
    run.walk_side_prompts, run.walk_side_open = [], set()
    run.walk_verb, run.walk_crossed = "walk-fight", None
    return run


def test_the_last_forward_move_answers_the_side_the_prompt_names(tmp_path, monkeypatch):
    sess = _Session()
    run = _run(tmp_path, monkeypatch, sess)
    assert run.answer_side_prompt("KKII", (3, "I", [15, 4, 1]), "ran", crossing=True)
    assert run.walk_crossed["side"] == "7"
    assert (run.walk_crossed["area_before"], run.walk_crossed["area_after"]) == (24, 26)
    assert sess.attached == [PROMPT]


def test_a_side_outside_the_encounters_fails_when_it_is_not_the_crossing(tmp_path, monkeypatch):
    sess = _Session()
    run = _run(tmp_path, monkeypatch, sess)
    with pytest.raises(A.StepFailed, match="side 7 mid-walk"):
        run.answer_side_prompt("KKII", (2, "I", [14, 4, 1]), "ran")
    assert sess.attached == []


def test_side_two_on_the_last_move_is_still_the_encounters(tmp_path, monkeypatch):
    sess = _Session("INSERT SIDE # 2, AND PRESS ANY KEY.")
    run = _run(tmp_path, monkeypatch, sess)
    run.answer_side_prompt("KKII", (3, "I", [15, 4, 1]), "ran", crossing=True)
    assert run.walk_crossed is None and run.walk_side_prompts[0]["side"] == "2"


def test_a_second_disk_prompt_after_the_crossing_fails_the_step(tmp_path, monkeypatch):
    sess = _Session(after=1, second="INSERT SIDE # 3, AND PRESS ANY KEY.")
    sess.area = 24
    run = _run(tmp_path, monkeypatch, sess)
    # The area stays put while the second prompt is up.
    monkeypatch.setattr(_Session, "screen", lambda self: (
        setattr(self, "reads", self.reads + 1) or _Screen(
            PROMPT if not self.answered
            else "INSERT SIDE # 3, AND PRESS ANY KEY." if self.reads - self.answered > 1
            else "")))
    with pytest.raises(A.StepFailed, match="second disk prompt"):
        run.answer_side_prompt("KKII", (3, "I", [15, 4, 1]), "ran", crossing=True)


def test_an_unchanged_area_after_the_answer_fails_the_step(tmp_path, monkeypatch):
    sess = _Session()
    run = _run(tmp_path, monkeypatch, sess)
    sess.area = 26
    monkeypatch.setattr(_Session, "screen", lambda self: (
        setattr(self, "reads", self.reads + 1) or _Screen(
            PROMPT if not self.answered else "")))
    with pytest.raises(A.StepFailed, match="area is still 26"):
        run.answer_side_prompt("KKII", (3, "I", [15, 4, 1]), "ran", crossing=True)


def test_without_the_option_no_move_is_a_crossing(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, _Session())
    run.edge_crossing = False
    assert not run.crossing_move("KKII", 3, "I")
    assert not run.cross_if_prompt("KKII", (3, "I", [15, 4, 1]))


def test_walk_crosses_only_on_its_last_forward_move(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, _Session())
    assert not run.cross_if_prompt("KKII", (2, "I", [14, 4, 1]))
    assert not run.cross_if_prompt("KKII", (1, "K", [14, 4, 1]))
    assert run.cross_if_prompt("KKII", (3, "I", [15, 4, 1]))
    assert run.walk_crossed["side"] == "7"


def test_walk_fight_does_not_judge_the_crossing_move_as_an_exit(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, _Session(prompt=""))
    run.position = lambda: [15, 4, 1]
    run.leave_arrival = lambda *a: None

    def key(route, n, move, before, last, *rest, **kw):
        run.walk_crossed = {"side": "7", "at_move": n, "area_before": 24,
                            "area_after": 26, "position": [14, 27, None]}
        return False

    run._walk_fight_key = key
    got = run._walk_fight("I", None)
    assert got["position"] == [14, 27, None] and got["crossing"]["side"] == "7"
    assert got["moves"][-1]["crossed"] is True


class _FightSession(_Session):
    """Ends every wait loop once the prompt is answered, as a fight does."""

    walk_encounter = None

    def in_combat(self):
        return bool(self.answered)

    def mode(self):
        return A.S.COMBAT if self.answered else 1

    def walk_stop(self, wait=0.0):
        return None


def _crossing_site(tmp_path, monkeypatch):
    sess = _FightSession()
    return sess, _run(tmp_path, monkeypatch, sess)


LAST = (3, "I", [15, 4, 1])


def test_a_prompt_before_the_last_forward_move_is_the_crossing(tmp_path, monkeypatch):
    sess, run = _crossing_site(tmp_path, monkeypatch)
    run.leave_arrival = lambda *a: None
    run.position = lambda: [15, 4, 1]
    run._walk_fight_key = lambda *a, **k: False
    run._walk_fight("I", None)
    assert run.walk_crossed["side"] == "7"


def test_a_prompt_while_the_encounter_loads_is_the_crossing(tmp_path, monkeypatch):
    sess, run = _crossing_site(tmp_path, monkeypatch)
    run._await_side_encounter("KKII", *LAST[:2], LAST[2])
    assert run.walk_crossed["side"] == "7"


def test_a_prompt_while_an_encounter_is_drawn_is_the_crossing(tmp_path, monkeypatch):
    sess, run = _crossing_site(tmp_path, monkeypatch)
    run._await_encounter("KKII", LAST, "FIGHT")
    assert run.walk_crossed["side"] == "7"


def test_a_prompt_after_a_press_bar_is_the_crossing(tmp_path, monkeypatch):
    sess, run = _crossing_site(tmp_path, monkeypatch)
    run._await_fight_after_press("KKII", LAST, 3, "I", LAST[2], "FIGHT")
    assert run.walk_crossed["side"] == "7"


def test_a_prompt_while_looking_for_a_fight_is_the_crossing(tmp_path, monkeypatch):
    sess, run = _crossing_site(tmp_path, monkeypatch)
    run._look_for_fight("KKII", LAST)
    assert run.walk_crossed["side"] == "7"


class _QuietSession(_Session):
    """No fight ever opens, so a wait that goes on after the crossing runs
    to its timeout and fails."""

    walk_encounter = None
    prep = False

    def in_combat(self):
        return False

    def mode(self):
        return A.COMBAT_PREP if self.prep else 1

    def walk_stop(self, wait=0.0):
        return None


def _quiet_site(tmp_path, monkeypatch, prep=False):
    sess = _QuietSession()
    sess.prep = prep
    return sess, _run(tmp_path, monkeypatch, sess)


def test_the_crossing_move_key_is_not_sent_again_into_the_new_area(tmp_path, monkeypatch):
    sess, run = _quiet_site(tmp_path, monkeypatch)
    run.leave_arrival = lambda *a: None
    run.position = lambda: [15, 4, 1]
    sent = []
    run._walk_fight_key = lambda *a, **k: sent.append("I") or False
    got = run._walk_fight("I", None)
    assert sent == [] and got["moves"][-1]["crossed"] is True
    assert got["position"] == [14, 27, None]


def test_the_wait_for_a_loading_encounter_ends_at_a_crossing(tmp_path, monkeypatch):
    sess, run = _quiet_site(tmp_path, monkeypatch)
    assert run._await_side_encounter("KKII", *LAST[:2], LAST[2]) is None
    assert run.walk_crossed["side"] == "7"


def test_the_wait_for_an_encounter_to_draw_ends_at_a_crossing(tmp_path, monkeypatch):
    sess, run = _quiet_site(tmp_path, monkeypatch)
    assert run._await_encounter("KKII", LAST, "FIGHT") == (None, False, True)
    assert run.walk_crossed["side"] == "7"


def test_the_wait_after_a_press_bar_ends_at_a_crossing(tmp_path, monkeypatch):
    sess, run = _quiet_site(tmp_path, monkeypatch)
    assert run._await_fight_after_press("KKII", LAST, 3, "I", LAST[2], "FIGHT") is None
    assert run.walk_crossed["side"] == "7"


def test_the_look_for_a_fight_ends_at_a_crossing(tmp_path, monkeypatch):
    sess, run = _quiet_site(tmp_path, monkeypatch, prep=True)
    run._look_for_fight("KKII", LAST)
    assert run.walk_crossed["side"] == "7"


def test_the_waits_still_fail_a_foreign_side_off_the_last_move(tmp_path, monkeypatch):
    sess, run = _crossing_site(tmp_path, monkeypatch)
    with pytest.raises(A.StepFailed, match="side 7 mid-walk"):
        run._look_for_fight("KKII", (1, "I", [14, 4, 1]))


# -- a Dispel Magic the game resists ----------------------------------------------

def _readings():
    party = [{"slot": 1, "name": "ROLAND", "memorised": [41, 42]},
             {"slot": 5, "name": "BRUTUS", "status": 3}]
    rows = [[n, 0, 0, 0, 0] for n in range(64)]
    rows[63] = [63, 32, 5, 0, 5]
    before = {"party": party, "effect_rows": rows}
    spent = [dict(party[0], memorised=[42]), party[1]]
    return before, {"party": spent, "effect_rows": [r[:] for r in rows]}


def test_a_resisted_cast_spent_one_dispel_and_changed_nothing_else():
    before, after = _readings()
    assert A.PoolRun._dispel_resisted(before, after, "ROLAND", 5)
    after["effect_rows"][63][1] = 0
    assert not A.PoolRun._dispel_resisted(before, after, "ROLAND", 5)
    before, after = _readings()
    after["party"][0]["memorised"] = [41, 42]
    assert not A.PoolRun._dispel_resisted(before, after, "ROLAND", 5)
    before, after = _readings()
    after["party"][1] = dict(after["party"][1], status=1)
    assert not A.PoolRun._dispel_resisted(before, after, "ROLAND", 5)


def _retrying(tmp_path, tries, outcomes):
    run = A.PoolRun(object(), A.Log(tmp_path), tmp_path, POOL_OF_RADIANCE, {})
    run.dispel_tries = tries
    calls, flags = [], []
    run.to_world = lambda: calls.append("world") or True
    run.memorize = lambda arg: calls.append(("memorize", arg))
    run.rest_offered = lambda: calls.append("rest")

    def once(arg, resist_ok=False):
        calls.append("cast")
        flags.append(resist_ok)
        return {"outcome": outcomes.pop(0)} if outcomes[0] == "resisted" else {
            "row_after": [63, 0, 5, 0, 5]}

    run._cast_once = once
    return run, calls, flags


def test_a_resisted_cast_memorizes_rests_and_casts_again_in_the_same_boot(tmp_path):
    run, calls, flags = _retrying(tmp_path, 3, ["resisted", "resisted", "done"])
    got = run.cast("ROLAND:DISPEL MAGIC>BRUTUS")
    assert calls == ["cast", "world", ("memorize", "ROLAND>DISPEL MAGIC"), "rest",
                     "cast", "world", ("memorize", "ROLAND>DISPEL MAGIC"), "rest",
                     "cast"]
    assert flags == [True, True, False]
    assert got["tries"] == 3 and len(got["attempts"]) == 2


def test_one_try_casts_once_and_fails_on_a_resisted_roll_as_before(tmp_path):
    run, calls, flags = _retrying(tmp_path, 1, ["done"])
    run.cast("ROLAND:DISPEL MAGIC>BRUTUS")
    assert calls == ["cast"] and flags == [False]


def test_the_last_try_does_not_record_a_resist_as_an_outcome(tmp_path):
    run, calls, flags = _retrying(tmp_path, 2, ["resisted", "resisted"])
    run._cast_once = lambda arg, resist_ok=False: (
        flags.append(resist_ok) or {"outcome": "resisted"} if resist_ok
        else (_ for _ in ()).throw(A.StepFailed("dispel-roll")))
    with pytest.raises(A.StepFailed, match="dispel-roll"):
        run.cast("ROLAND:DISPEL MAGIC>BRUTUS")
    assert flags == [True]


def _resisting_run(tmp_path):
    """The real `_cast_once` on the camp fake, with the game's roll failing:
    the Dispel Magic is spent and row 63 never clears."""
    from test_c64acceptance_rest_cast import CampFake, _dispel_run

    sess = CampFake([1, 3, 28, 41, 42])
    run = _dispel_run(tmp_path, sess)
    cleared = run.reading

    def reading():
        got = cleared()
        got["effect_rows"][63][1] = 32
        return got

    run.reading = reading
    return run


def test_cast_once_reports_a_resisted_dispel_when_resisting_is_allowed(tmp_path):
    run = _resisting_run(tmp_path)
    got = run._cast_once("DIRTEN:DISPEL MAGIC>BRUTUS", resist_ok=True)
    assert got["outcome"] == "resisted" and got["slot"] == 5
    assert got["row"] == [63, 32, 5, 0, 5]
    assert got["memorised_before"] == [1, 3, 28, 41, 42]
    assert got["memorised_after"] == [1, 3, 28, 42]


def test_cast_once_fails_a_resisted_dispel_when_resisting_is_not_allowed(tmp_path):
    run = _resisting_run(tmp_path)
    with pytest.raises(A.StepFailed, match="unsuccessful roll"):
        run._cast_once("DIRTEN:DISPEL MAGIC>BRUTUS")


def test_a_walk_failure_names_the_area_edge_only_when_crossing_is_on(tmp_path, monkeypatch):
    for crossing, wanted in ((False, False), (True, True)):
        run = _run(tmp_path, monkeypatch, _Session())
        run.edge_crossing = crossing
        with pytest.raises(A.StepFailed, match="side 7 mid-walk") as caught:
            run.answer_side_prompt("KKII", (2, "I", [14, 4, 1]), "ran")
        assert ("area edge" in str(caught.value)) is wanted
