"""`tools/areas/fasttravelrun.py`'s judgement logic, against a fake monitor rather
than a live emulator.

The tool itself drives a real pool slot end to end -- boot, load a save,
`BEGIN ADVENTURING`, the production `automap.actions.FastTravel().run()`
through a real `automap.target.ViceTarget`, and a live prompt loop -- and
none of that can be exercised here without putting a window on the
maintainer's screen, which this repository's rule forbids. What can be
tested is everything that decides whether a run's own verdict means
anything: `name()`'s byte decoding, `party()`/`area_of()`'s reads against a
fake monitor, and `verdict()`, which is pure and is the part that actually
says pass or fail. The precedent is `tests/areas/test_exitreentry.py`'s own
docstring, word for word on why the split falls where it does.
"""
from __future__ import annotations

import contextlib
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.areas import fasttravelrun as FT  # noqa: E402


class FakeMonitor:
    """`Session.mon()`'s binary-monitor interface, backed by a flat buffer."""

    def __init__(self):
        self.mem = bytearray(0x10000)

    def read(self, addr: int, length: int) -> bytes:
        return bytes(self.mem[addr:addr + length])

    def write(self, addr: int, data) -> None:
        data = bytes(data)
        self.mem[addr:addr + len(data)] = data


class FakeSession:
    def __init__(self, monitor: FakeMonitor):
        self._m = monitor
        self.screens: list[str] = []

    def mon(self, timeout: float = 5):
        return contextlib.nullcontext(self._m)


def make() -> tuple[FakeSession, FakeMonitor]:
    m = FakeMonitor()
    return FakeSession(m), m


def put_name(m: FakeMonitor, slot: int, text: str, status: int = 1) -> None:
    m.write(FT.SLOT_RECORD + slot * 0x100, text.encode("ascii") + b"\x00")
    m.write(FT.SLOT_ROSTER + slot * 0x20, bytes([status]))


# ---------------------------------------------------------------------------
# name() -- the raw-bytes decoder
# ---------------------------------------------------------------------------

def test_name_reads_up_to_the_first_null():
    assert FT.name(b"PRINCESS FATIMA\x00\x00\x00") == "PRINCESS FATIMA"


def test_name_is_empty_for_a_zeroed_slot():
    assert FT.name(b"\x00" * 16) == "<empty>"


def test_name_is_empty_for_an_empty_buffer():
    assert FT.name(b"") == "<empty>"


def test_name_replaces_unprintable_bytes_with_a_dot():
    assert FT.name(bytes([0x41, 0x01, 0x42, 0x00])) == "A.B"


# ---------------------------------------------------------------------------
# party() / area_of() -- reads against a fake monitor
# ---------------------------------------------------------------------------

def test_party_reads_all_eight_slots_by_name_and_status():
    sess, m = make()
    put_name(m, 3, "PRINCESS FATIMA", status=1)
    rows = FT.party(sess)
    assert len(rows) == FT.SLOTS
    assert rows[3] == {"slot": 3, "name": "PRINCESS FATIMA", "status": 1}
    assert rows[0] == {"slot": 0, "name": "<empty>", "status": 0}


def test_area_of_masks_off_the_top_bit():
    """`$6E1B` carries a flag in bit 7 alongside the area id -- the same
    mask `automap.actions.FastTravel.current_area` applies."""
    sess, m = make()
    m.write(FT.AREA_BYTE, bytes([27 | 0x80]))
    assert FT.area_of(sess) == 27


# ---------------------------------------------------------------------------
# has_member()
# ---------------------------------------------------------------------------

def test_has_member_true_when_the_name_contains_the_substring():
    rows = [{"slot": 3, "name": "PRINCESS FATIMA", "status": 1}]
    assert FT.has_member(rows, "FATIMA") is True


def test_has_member_false_when_absent():
    rows = [{"slot": 3, "name": "XAVIER", "status": 1}]
    assert FT.has_member(rows, "FATIMA") is False


def test_has_member_ignores_empty_slots():
    rows = [{"slot": 3, "name": "<empty>", "status": 0}]
    assert FT.has_member(rows, "<empty>") is False


# ---------------------------------------------------------------------------
# verdict() -- the pure judgement, and what proves it a judgement
# ---------------------------------------------------------------------------

WITH_FATIMA = [{"slot": 3, "name": "PRINCESS FATIMA", "status": 1}]
WITHOUT_FATIMA = [{"slot": 3, "name": "<empty>", "status": 0}]
NO_FATIMA_EVER = [{"slot": 3, "name": "XAVIER", "status": 1}]


def test_verdict_passes_when_the_member_is_dropped_on_landing():
    ok, message = FT.verdict(WITH_FATIMA, WITHOUT_FATIMA, 13, 27, 13, 27,
                              "FATIMA")
    assert ok is True
    assert "dropped" in message


def test_verdict_fails_when_the_member_is_still_there():
    """The regression case #207 is about: the handler was skipped, so the
    party still carries the member after the warp."""
    ok, message = FT.verdict(WITH_FATIMA, WITH_FATIMA, 13, 27, 13, 27,
                              "FATIMA")
    assert ok is False
    assert "did not drop" in message


def test_verdict_fails_when_the_save_was_not_staged_in_the_expected_area():
    ok, message = FT.verdict(WITH_FATIMA, WITHOUT_FATIMA, 5, 27, 13, 27,
                              "FATIMA")
    assert ok is False
    assert "is not in area 13" in message


def test_verdict_fails_when_the_warp_did_not_land():
    ok, message = FT.verdict(WITH_FATIMA, WITH_FATIMA, 13, 13, 13, 27,
                              "FATIMA")
    assert ok is False
    assert "did not land in area 27" in message


def test_verdict_fails_when_the_member_was_never_there():
    """A mistyped `--member`, not a finding -- and it is checked before the
    "still there" case, so a typo is never misreported as the regression."""
    ok, message = FT.verdict(NO_FATIMA_EVER, NO_FATIMA_EVER, 13, 27, 13, 27,
                              "FATIMA")
    assert ok is False
    assert "was not in the party to begin with" in message


# ---------------------------------------------------------------------------
# second_hop() -- one poll of a two-hop trip through a short-lived target

def test_second_hop_polls_the_engine_and_always_closes_the_target():
    from automap import actions

    opened = []

    class Target:
        closed = False

        def close(self):
            self.closed = True

    def open_target():
        opened.append(Target())
        return opened[-1]

    ft = actions.FastTravel()
    assert FT.second_hop(ft, open_target) is None       # nothing pending
    assert opened[0].closed

    class Boom(actions.FastTravel):
        def continue_pending(self, target):
            raise RuntimeError("monitor went away")

    try:
        FT.second_hop(Boom(), open_target)
    except RuntimeError:
        pass
    assert opened[1].closed


def test_verdict_fails_a_two_hop_that_stopped_at_the_area_its_door_leads_to():
    ok, message = FT.verdict([{"name": "FATIMA", "status": 1}],
                             [{"name": "<empty>", "status": 0}],
                             13, 27, 13, 0, "FATIMA")
    assert not ok
    assert "did not land in area 0" in message


# ---------------------------------------------------------------------------
# timing, screenshots and the walk afterwards -- all against fakes

def test_verdict_fails_a_two_hop_that_was_never_timed():
    """`second_hop_seconds` is the number #207's removal condition asks for; a
    two-hop that reads the destination without one has measured nothing."""
    args = (WITH_FATIMA, WITHOUT_FATIMA, 13, 0, 13, 0, "FATIMA")
    ok, message = FT.verdict(*args, two_hop=True, second_hop_seconds=None)
    assert not ok
    assert "never timed" in message
    ok, _ = FT.verdict(*args, two_hop=True, second_hop_seconds=41.3)
    assert ok
    ok, _ = FT.verdict(*args)                      # a one-hop needs no timing
    assert ok


def test_elapsed_is_none_unless_both_moments_happened():
    assert FT.elapsed(10.0, 52.34) == 42.3
    assert FT.elapsed(10.0, None) is None
    assert FT.elapsed(None, 52.0) is None


def step(ok=True, refused=None):
    """A step that moved changes square; one that did not stays put."""
    return {"move": "1", "ok": ok, "before": (1, 1),
            "after": (1, 0) if ok else (1, 1), "refused": refused}


def test_walk_verdict_passes_a_party_that_moved_and_opened_the_sheet():
    ok, message = FT.walk_verdict([step(), step(ok=False)], True)
    assert ok
    assert "1 of 2" in message


def test_walk_verdict_fails_a_wedged_party():
    ok, message = FT.walk_verdict([step(ok=False)] * 4, True)
    assert not ok and "did not move" in message


def test_walk_verdict_fails_when_the_sheet_never_opens():
    ok, message = FT.walk_verdict([step()], False)
    assert not ok and "character sheet" in message


def test_walk_verdict_fails_a_step_the_driver_refused_to_press():
    ok, message = FT.walk_verdict([step(refused="not a compass digit")], True)
    assert not ok and "refused" in message


def test_walk_verdict_fails_a_walk_whose_steps_never_change_square():
    """A turn changes the status line and `walk_one` calls that ok; the square
    is what says the party walked."""
    turned = step()
    turned["after"] = turned["before"]
    ok, message = FT.walk_verdict([turned, turned], True)
    assert not ok and "square" in message


def test_walk_verdict_ignores_fight_steps_when_counting_moves():
    ok, _ = FT.walk_verdict([{"fight": "won", "row": "", "world": True},
                             step()], True)
    assert ok


def test_walk_verdict_fails_with_no_steps():
    ok, message = FT.walk_verdict([], True)
    assert not ok and "no step" in message


class FakeKbd:
    def __init__(self, works=True):
        self.works = works
        self.paths = []

    def screenshot(self, path):
        self.paths.append(path)
        return self.works


class FakeScreen:
    def __init__(self, row24):
        self._row = row24

    def row(self, n):
        return self._row


class WalkSession(FakeSession):
    """A session whose party moves on every step but the ones in `blocked`."""

    def __init__(self, monitor, indoors=False, blocked=(), sheet=True):
        super().__init__(monitor)
        self._indoors, self._blocked, self._sheet = indoors, blocked, sheet
        self.x = 5
        self.pressed = []
        self.walk_refused = None
        self.kbd = FakeKbd()
        self.sheets = []
        self.row = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"
        self.combat = False
        self.fights = []
        self.settled = True

    def screen(self):
        return FakeScreen(self.row)

    def in_combat(self):
        return self.combat

    def fight(self, budget, tactic):
        self.fights.append((budget, tactic))
        self.combat = False
        return types.SimpleNamespace(outcome="won")

    def wait_for_world(self, timeout=240.0):
        return self.settled

    def indoors(self):
        return self._indoors

    def square(self):
        return (self.x, 5)

    def walk_one(self, move):
        self.pressed.append(move)
        if move in self._blocked:
            return False
        self.x += 1
        return True

    def character_sheet(self, index=None):
        self.sheets.append(index)
        return ["NAME"] if self._sheet else None


def test_the_walk_goes_each_way_then_opens_the_sheet_and_records_each_step():
    sess, m = make()
    sess = WalkSession(m, indoors=False)
    steps, sheet = FT.walk_afterwards(sess)
    assert "".join(sess.pressed) == FT.WALK_OUTDOORS
    assert set(FT.WALK_OUTDOORS) == {"1", "3", "5", "7"}   # N, E, S, W
    assert sheet and sess.sheets == [0]
    assert steps[0] == {"move": "1", "ok": True, "before": (5, 5),
                        "after": (6, 5), "refused": None,
                        "row": sess.row}
    assert len(steps) == len(FT.WALK_OUTDOORS)


def test_the_walk_indoors_uses_the_dungeons_own_keys():
    sess, m = make()
    sess = WalkSession(m, indoors=True)
    FT.walk_afterwards(sess)
    assert "".join(sess.pressed) == FT.WALK_INDOORS
    assert set(FT.WALK_INDOORS) <= set("IJKM")


def test_the_walk_refuses_to_guess_a_world_it_could_not_read():
    sess, m = make()
    sess = WalkSession(m, indoors=None)
    assert FT.walk_afterwards(sess) == ([], False)
    assert sess.pressed == []


def test_a_walked_party_that_never_moves_is_a_failed_walk():
    sess, m = make()
    sess = WalkSession(m, blocked=set(FT.WALK_OUTDOORS))
    steps, sheet = FT.walk_afterwards(sess)
    ok, _ = FT.walk_verdict(steps, sheet)
    assert not ok


def test_a_blocked_step_tries_the_other_three_directions_and_records_each():
    sess, m = make()
    sess = WalkSession(m, indoors=True, blocked={"I", "K", "M"})
    steps, sheet = FT.walk_afterwards(sess)
    ok, _ = FT.walk_verdict(steps, sheet)
    assert ok
    assert sess.pressed[:2] == ["I", "J"]
    blocked = WalkSession(m, indoors=True, blocked={"I", "K"})
    steps, _ = FT.walk_afterwards(blocked)
    assert [a["move"] for a in steps[0]["attempts"]] == ["I", "J"]
    assert steps[0]["before"] != steps[0]["after"]


def test_a_step_blocked_on_every_side_records_four_attempts_and_fails():
    sess, m = make()
    sess = WalkSession(m, indoors=True, blocked=set("IJKM"))
    steps, sheet = FT.walk_afterwards(sess)
    assert [a["move"] for a in steps[0]["attempts"]] == ["I", "J", "M", "K"]
    assert all(set(a) == {"move", "ok", "row", "before", "after"}
               and a["before"] == a["after"] for a in steps[0]["attempts"])
    assert len(sess.pressed) == FT.WALK_ATTEMPTS
    ok, _ = FT.walk_verdict(steps, sheet)
    assert not ok


class RedrawSession(WalkSession):
    """Row 24 reads from `rows` one read at a time, then holds the last."""

    def __init__(self, monitor, rows):
        super().__init__(monitor)
        self.rows = list(rows)
        self.reads = 0

    def screen(self):
        self.reads += 1
        row = self.rows.pop(0) if len(self.rows) > 1 else self.rows[0]
        return FakeScreen(row)


def test_an_empty_row_after_a_disk_prompt_is_waited_out_then_walked():
    sess, m = make()
    sess = RedrawSession(m, ["", "", FT.S.OUTDOOR_PROMPT])
    steps, sheet = FT.walk_afterwards(sess)
    ok, _ = FT.walk_verdict(steps, sheet)
    assert ok and steps[0]["before"] != steps[0]["after"]
    assert steps[0]["row"] == FT.S.OUTDOOR_PROMPT


def test_a_row_that_stays_empty_is_refused_with_the_row_recorded(monkeypatch):
    sess, m = make()
    sess = RedrawSession(m, [""])
    now = [0.0]
    monkeypatch.setattr(FT.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(FT.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    steps, sheet = FT.walk_afterwards(sess, timeout=5.0)
    assert sess.pressed == [] and not sheet
    assert steps[0]["row"] == "" and "refused" in steps[0]
    assert now[0] >= 5.0


def test_shoot_saves_under_the_fixed_name_and_survives_a_failed_capture(tmp_path):
    sess, m = make()
    sess = WalkSession(m)
    shots = {}
    FT.shoot(sess, tmp_path, "before", shots)
    assert shots["before"] == str(tmp_path / "1-before.png")
    assert sess.kbd.paths == [str(tmp_path / "1-before.png")]
    sess.kbd.works = False
    FT.shoot(sess, tmp_path, "question", shots)
    assert shots["question"] is None
    assert sorted(FT.SHOTS.values()) == [
        "1-before.png", "2-question.png", "3-after-second-hop.png",
        "4-after-walk.png"]


class AskingSession(FakeSession):
    """Shows `YES NO` once, then lets the area byte move to the destination."""

    def __init__(self, monitor, to_area):
        super().__init__(monitor)
        self.to_area, self.bar = to_area, "YES NO"
        self.chosen = []

    def screen(self):
        return FakeScreen(self.bar)

    def select_bar(self, label, timeout=0):
        self.chosen.append(label)
        self.bar = ""
        self._m.write(FT.AREA_BYTE, bytes([self.to_area]))
        return True


def test_answer_and_wait_calls_on_question_then_stamps_the_landing(monkeypatch):
    monkeypatch.setattr(FT.time, "sleep", lambda s: None)
    sess, m = make()
    sess = AskingSession(m, 0)
    ticks = iter([142.5])
    marks, order = {}, []
    hop = FT.answer_and_wait(sess, 0, deadline_s=30.0,
                             on_question=lambda: order.append("question"),
                             marks=marks, clock=lambda: next(ticks))
    assert hop is None
    assert order == ["question"] and sess.chosen == ["YES"]
    assert marks["landed"] == 142.5


class _RunSession:
    mon_port = 6521

    def __init__(self, *a, **k):
        self.terminated = False

    def boot(self):
        return True

    load_save = boot

    def wait_for_world(self, timeout):
        return True

    def select_row(self, label):
        return True

    def settle(self, n):
        pass

    def terminate(self):
        self.terminated = True


def test_a_result_that_cannot_be_written_still_tears_the_slot_down(
        monkeypatch, tmp_path):
    events = []
    slot = types.SimpleNamespace(
        n=1, display=":1", dir=str(tmp_path),
        teardown=lambda: events.append("teardown"),
        release=lambda: events.append("release"))
    sess = _RunSession()
    monkeypatch.setattr(FT.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(FT.S, "stage_disks", lambda *a, **k: "boot")
    monkeypatch.setattr(FT.S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(FT.S, "Session", lambda *a, **k: sess)
    monkeypatch.setattr(FT, "party", lambda s: [])
    monkeypatch.setattr(FT, "area_of", lambda s: 13)
    monkeypatch.setattr(FT, "shoot", lambda *a, **k: None)
    monkeypatch.setattr(FT, "ViceTarget", lambda **k: types.SimpleNamespace(
        close=lambda: None))

    class Trip:
        pending = None

        def run(self, target, area):
            # A message that is not JSON, so `result` cannot be serialised.
            return types.SimpleNamespace(ok=False, message=object())

    monkeypatch.setattr(FT, "A", types.SimpleNamespace(
        FastTravel=Trip, area_by_id=lambda n: n))
    args = types.SimpleNamespace(
        out=str(tmp_path / "out"), slot=None, disks=str(tmp_path),
        save=str(tmp_path / "save.d64"), from_area=13, to_area=27,
        member="FATIMA", arrive=1.0, answer_timeout=1.0)
    assert FT.run(args) == 1
    assert sess.terminated and events == ["teardown", "release"]


def test_run_attaches_the_target_to_the_slots_monitor_port(monkeypatch, tmp_path):
    ports = []

    class Target:
        def __init__(self, host=None, port=None):
            ports.append(port)

        def close(self):
            pass

    slot = types.SimpleNamespace(
        n=1, display=":1", dir=str(tmp_path),
        teardown=lambda: None, release=lambda: None)
    sess = _RunSession()
    sess.mon_port = 6531
    monkeypatch.setattr(FT.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(FT.S, "stage_disks", lambda *a, **k: "boot")
    monkeypatch.setattr(FT.S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(FT.S, "Session", lambda *a, **k: sess)
    monkeypatch.setattr(FT, "party", lambda s: [])
    monkeypatch.setattr(FT, "area_of", lambda s: 13)
    monkeypatch.setattr(FT, "shoot", lambda *a, **k: None)
    monkeypatch.setattr(FT, "ViceTarget", Target)

    class Trip:
        pending = types.SimpleNamespace(through=27)

        def run(self, target, area):
            return types.SimpleNamespace(ok=True, message="")

        def continue_pending(self, target):
            return None

    monkeypatch.setattr(FT, "A", types.SimpleNamespace(
        FastTravel=Trip, area_by_id=lambda n: n))

    def answer(sess, to_area, deadline_s, between, on_question, marks):
        between()
        return None

    monkeypatch.setattr(FT, "answer_and_wait", answer)
    args = types.SimpleNamespace(
        out=str(tmp_path / "out"), slot=None, disks=str(tmp_path),
        save=str(tmp_path / "save.d64"), from_area=13, to_area=27,
        member="FATIMA", arrive=1.0, answer_timeout=1.0)
    FT.run(args)
    assert ports == [6531, 6531]


# ---------------------------------------------------------------------------
# The arrival menu, the per-poll diagnostics and the second hop's own timing

class MenuSession(FakeSession):
    """Shows `YES NO`, then the arrival menu, then lets the area byte move once
    the arrival menu has been answered."""

    def __init__(self, monitor, to_area, rows=("YES NO", "LARGE SMALL LEAVE")):
        super().__init__(monitor)
        self.to_area, self.rows = to_area, list(rows)
        self.chosen = []

    def screen(self):
        return FakeScreen(self.rows[0] if self.rows else "")

    def select_bar(self, label, timeout=0):
        self.chosen.append(label)
        self.rows.pop(0)
        if not self.rows:
            self._m.write(FT.AREA_BYTE, bytes([self.to_area]))
        return True


def test_choice_for_answers_only_the_menus_it_knows():
    assert FT.choice_for("YES NO") == "YES"
    assert FT.choice_for("LARGE SMALL LEAVE") == "LEAVE"
    assert FT.choice_for("MOVE VIEW CAST AREA") is None
    assert FT.choice_for("LARGE SMALL") is None
    assert FT.choice_for("") is None


def test_answer_and_wait_selects_leave_on_the_arrival_menu(monkeypatch):
    monkeypatch.setattr(FT.time, "sleep", lambda s: None)
    sess, m = make()
    sess = MenuSession(m, 0)
    questions = []
    FT.answer_and_wait(sess, 0, deadline_s=30.0,
                       on_question=lambda: questions.append(1),
                       clock=lambda: 1.0)
    assert sess.chosen == ["YES", "LEAVE"]
    assert questions == [1]


def test_answer_and_wait_never_picks_large_or_small(monkeypatch):
    monkeypatch.setattr(FT.time, "sleep", lambda s: None)
    sess, m = make()
    sess = MenuSession(m, 0, rows=("LARGE SMALL LEAVE",))
    FT.answer_and_wait(sess, 0, deadline_s=30.0, clock=lambda: 1.0)
    assert sess.chosen == ["LEAVE"]


class _PollTarget:
    def __init__(self, area_byte, pc=0x10C2):
        self.area_byte, self._pc = area_byte, pc

    def read(self, addr, length):
        return bytes([self.area_byte]) * length

    def pc(self):
        return self._pc

    def close(self):
        pass


def _pending_ft(through=27, from_area=13):
    class Ft:
        pending = types.SimpleNamespace(through=through, from_area=from_area)

        def continue_pending(self, target):
            return None

    return Ft()


def test_second_hop_prints_the_raw_area_byte_mode_and_pc_each_poll(capsys):
    FT.second_hop(_pending_ft(), lambda: _PollTarget(0x9B, pc=0x1919))
    out = capsys.readouterr().out
    assert "$6E1B=9b" in out and "pc=6425" in out and "mode=" in out


def test_second_hop_prints_nothing_when_no_hop_is_pending(capsys):
    from automap import actions

    FT.second_hop(actions.FastTravel(), lambda: _PollTarget(13))
    assert capsys.readouterr().out == ""


def test_second_hop_marks_the_first_poll_that_reads_the_through_area():
    marks, ticks = {}, iter([10.0, 20.0, 30.0])
    ft = _pending_ft()
    FT.second_hop(ft, lambda: _PollTarget(13), marks, clock=lambda: next(ticks))
    assert marks == {}
    # Bit 7 set: the loader is mid-change, so the party has not arrived yet.
    FT.second_hop(ft, lambda: _PollTarget(27 | 0x80), marks,
                  clock=lambda: next(ticks))
    assert marks == {}
    FT.second_hop(ft, lambda: _PollTarget(27), marks, clock=lambda: next(ticks))
    FT.second_hop(ft, lambda: _PollTarget(27), marks, clock=lambda: next(ticks))
    assert marks == {"through": 10.0}


def test_enable_debug_logging_routes_automap_debug_lines_to_stdout(capsys):
    import logging

    logger = logging.getLogger("wish.automap")
    old_level, old_handlers = logger.level, list(logger.handlers)
    try:
        FT.enable_debug_logging()
        FT.enable_debug_logging()
        logging.getLogger("wish.automap.actions").debug("refused: pc $1234")
        out = capsys.readouterr().out
        assert out.count("refused: pc $1234") == 1
    finally:
        logger.setLevel(old_level)
        logger.handlers[:] = old_handlers


def test_run_reports_second_hop_seconds_from_the_through_mark(monkeypatch,
                                                              tmp_path):
    import json

    slot = types.SimpleNamespace(
        n=1, display=":1", dir=str(tmp_path),
        teardown=lambda: None, release=lambda: None)
    sess = _RunSession()
    monkeypatch.setattr(FT.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(FT.S, "stage_disks", lambda *a, **k: "boot")
    monkeypatch.setattr(FT.S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(FT.S, "Session", lambda *a, **k: sess)
    monkeypatch.setattr(FT, "party", lambda s: [])
    monkeypatch.setattr(FT, "area_of", lambda s: 13)
    monkeypatch.setattr(FT, "shoot", lambda *a, **k: None)
    monkeypatch.setattr(FT, "ViceTarget", lambda **k: types.SimpleNamespace(
        close=lambda: None))

    class Trip:
        pending = object()

        def run(self, target, area):
            return types.SimpleNamespace(ok=True, message="")

    monkeypatch.setattr(FT, "A", types.SimpleNamespace(
        FastTravel=Trip, area_by_id=lambda n: n))

    def answer(sess, to_area, deadline_s, between, on_question, marks):
        marks["through"], marks["landed"] = 1000.0, 1007.5
        return None

    monkeypatch.setattr(FT, "answer_and_wait", answer)
    args = types.SimpleNamespace(
        out=str(tmp_path / "out"), slot=None, disks=str(tmp_path),
        save=str(tmp_path / "save.d64"), from_area=13, to_area=27,
        member="FATIMA", arrive=1.0, answer_timeout=1.0)
    FT.run(args)
    result = json.loads((tmp_path / "out" / "result.json").read_text())
    assert result["second_hop_seconds"] == 7.5


def test_a_fight_before_a_step_is_fought_with_melee_and_recorded():
    sess, m = make()
    sess = WalkSession(m)
    sess.combat = True
    steps, sheet = FT.walk_afterwards(sess)
    assert sess.fights == [(300, FT.S.Session.melee_turn)]
    assert steps[0]["fight"] == "won" and steps[0]["world"] is True
    assert "".join(sess.pressed) == FT.WALK_OUTDOORS   # walking carried on
    assert sheet


def test_an_unknown_row_stops_the_walk_before_any_key_is_pressed():
    sess, m = make()
    sess = WalkSession(m)
    sess.row = "LARGE SMALL LEAVE"
    steps, sheet = FT.walk_afterwards(sess)
    assert sess.pressed == [] and sess.sheets == [] and not sheet
    assert "LARGE SMALL LEAVE" in steps[0]["refused"]
    assert steps[0]["row"] == "LARGE SMALL LEAVE"
    assert not FT.walk_verdict(steps, sheet)[0]


def test_the_move_sub_bar_is_a_row_the_walk_may_press_into():
    sess, m = make()
    sess = WalkSession(m)
    sess.row = FT.S.MOVE_SUBBAR + ", RETURN OR BUTTON"
    FT.walk_afterwards(sess)
    assert "".join(sess.pressed) == FT.WALK_OUTDOORS


def test_settle_accepts_the_travel_grid_direction_prompt(tmp_path):
    sess, m = make()
    sess = WalkSession(m)
    sess.settled, sess.row = False, "1-8, RETURN OR BUTTON"
    assert FT.settle_world(sess, tmp_path, {}) == (True, "")
    assert sess.kbd.paths == []


def test_a_walk_on_the_direction_prompt_changes_square_and_passes():
    sess, m = make()
    sess = WalkSession(m)
    sess.row = "1-8, RETURN OR BUTTON"
    steps, sheet = FT.walk_afterwards(sess)
    assert "".join(sess.pressed) == FT.WALK_OUTDOORS
    assert steps[0]["before"] != steps[0]["after"]
    assert FT.walk_verdict(steps, sheet)[0]


def test_settle_world_fails_with_the_row_text_and_a_screenshot(tmp_path):
    sess, m = make()
    sess = WalkSession(m)
    sess.settled, sess.row = False, "PRESS RETURN"
    shots = {}
    ok, message = FT.settle_world(sess, tmp_path, shots)
    assert not ok and "PRESS RETURN" in message
    assert sess.kbd.paths == [str(tmp_path / "4-after-walk.png")]
    sess.settled = True
    assert FT.settle_world(sess, tmp_path, shots) == (True, "")


def test_the_default_out_is_under_the_cache_not_the_temp_directory(monkeypatch):
    seen = {}
    monkeypatch.setattr(FT, "run", lambda args: seen.update(out=args.out) or 0)
    monkeypatch.setattr(FT, "disks_of", lambda args: pathlib.Path("."))
    FT.main([])
    assert pathlib.Path(seen["out"]).is_relative_to(
        pathlib.Path.home() / ".cache")


def test_a_failing_load_writes_the_screen_and_names_it_in_result_json(
        monkeypatch, tmp_path):
    import json
    slot = types.SimpleNamespace(
        n=1, display=":1", dir=str(tmp_path),
        teardown=lambda: None, release=lambda: None)

    class Failing(_RunSession):
        kbd = FakeKbd()

        def load_save(self):
            return False

        def screen(self):
            return FakeScreen("NOT THE PARTY MENU")

    sess = Failing()
    monkeypatch.setattr(FT.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(FT.S, "stage_disks", lambda *a, **k: "boot")
    monkeypatch.setattr(FT.S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(FT.S, "Session", lambda *a, **k: sess)
    out = tmp_path / "out"
    args = types.SimpleNamespace(
        out=str(out), slot=None, disks=str(tmp_path),
        save=str(tmp_path / "save.d64"), from_area=13, to_area=27,
        member="FATIMA", arrive=1.0, answer_timeout=1.0)
    try:
        FT.run(args)
    except RuntimeError:
        pass
    else:
        raise AssertionError("run should still raise")
    text = (out / "failure-screen.txt").read_text()
    assert "NOT THE PARTY MENU" in text and text.count("\n") == 25
    message = json.loads((out / "result.json").read_text())["message"]
    assert str(out / "failure-screen.txt") in message
    assert Failing.kbd.paths == [str(out / "failure.png")]


def _late_failure_run(monkeypatch, tmp_path, error):
    """Run to the trip with a party read, then have the trip raise *error*."""
    slot = types.SimpleNamespace(
        n=1, display=":1", dir=str(tmp_path),
        teardown=lambda: None, release=lambda: None)

    class Session(_RunSession):
        kbd = FakeKbd()

        def screen(self):
            return FakeScreen("LATE")

    class Target:
        def __init__(self, host=None, port=None):
            pass

        def close(self):
            pass

    class Trip:
        pending = None

        def run(self, target, area):
            raise error

    sess = Session()
    monkeypatch.setattr(FT.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(FT.S, "stage_disks", lambda *a, **k: "boot")
    monkeypatch.setattr(FT.S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(FT.S, "Session", lambda *a, **k: sess)
    monkeypatch.setattr(FT, "party", lambda s: [{"name": "FATIMA"}])
    monkeypatch.setattr(FT, "area_of", lambda s: 13)
    monkeypatch.setattr(FT, "shoot", lambda *a, **k: None)
    monkeypatch.setattr(FT, "ViceTarget", Target)
    monkeypatch.setattr(FT, "A", types.SimpleNamespace(
        FastTravel=Trip, area_by_id=lambda n: n))
    out = tmp_path / "out"
    args = types.SimpleNamespace(
        out=str(out), slot=None, disks=str(tmp_path),
        save=str(tmp_path / "save.d64"), from_area=13, to_area=27,
        member="FATIMA", arrive=1.0, answer_timeout=1.0)
    try:
        FT.run(args)
    except type(error):
        pass
    else:
        raise AssertionError("run should still raise")
    return out


def test_a_non_runtime_error_mid_run_still_writes_the_failure_screen(
        monkeypatch, tmp_path):
    out = _late_failure_run(monkeypatch, tmp_path, OSError("monitor gone"))
    assert "LATE" in (out / "failure-screen.txt").read_text()


def test_result_json_keeps_the_party_read_before_a_late_failure(
        monkeypatch, tmp_path):
    import json
    out = _late_failure_run(monkeypatch, tmp_path, TimeoutError("slow"))
    saved = json.loads((out / "result.json").read_text())
    assert saved["ok"] is False
    assert saved["before"] == [{"name": "FATIMA"}]
    assert saved["area_before"] == 13


def test_capture_failure_gives_up_on_a_screenshot_that_hangs(tmp_path):
    import threading
    release = threading.Event()

    class Hung(FakeSession):
        class kbd:                                       # noqa: N801
            @staticmethod
            def screenshot(path):
                release.wait(30)
                return True

        def screen(self):
            return None

    try:
        said = FT.capture_failure(Hung(FakeMonitor()), tmp_path,
                                  screenshot_timeout=0.2)
    finally:
        release.set()
    assert "timed out" in said


class _Clocked(RedrawSession):
    """Counts `wait_for_world` calls and raises past a cap, so a loop that no
    longer ends fails the test instead of hanging it."""

    def __init__(self, monitor, rows, answers=None):
        super().__init__(monitor, rows)
        self.waits = 0
        self.answers = answers

    def wait_for_world(self, timeout=240.0):
        self.waits += 1
        assert self.waits < 1000, "settle_row is busy-looping"
        if self.answers:
            self.answers(self)
        return True


def _fake_clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(FT.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(FT.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    return now


def test_a_fight_bar_goes_to_the_fight_without_waiting_for_the_world(monkeypatch):
    now = _fake_clock(monkeypatch)
    sess, m = make()
    sess = _Clocked(m, ["ENEMY DONE  CONTINUE BATTLE"])
    sess.combat = True
    fight = sess.fight

    def won(budget, tactic):
        sess.rows = ["MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"]
        return fight(budget, tactic)
    sess.fight = won
    steps, _ = FT.walk_afterwards(sess)
    assert sess.fights and sess.waits == 1          # only the one after the fight
    assert steps[0]["fight"] == "won"
    assert now[0] < 5.0


def test_an_unrecognised_row_is_handed_to_wait_for_world():
    sess, m = make()
    sess = _Clocked(m, ["INSERT DISK", FT.S.OUTDOOR_PROMPT])
    steps, sheet = FT.walk_afterwards(sess)
    assert sess.waits >= 1 and FT.walk_verdict(steps, sheet)[0]


def test_a_disk_prompt_answered_by_the_wait_is_then_walked():
    sess, m = make()
    sess = _Clocked(m, ["INSERT DISK", "INSERT DISK"])

    def answer(s):
        s.rows = [FT.S.OUTDOOR_PROMPT]
    sess.answers = answer
    steps, sheet = FT.walk_afterwards(sess)
    assert steps[0]["row"] == FT.S.OUTDOOR_PROMPT
    assert "".join(sess.pressed) == FT.WALK_OUTDOORS and sheet


def test_a_non_empty_row_that_never_settles_is_refused_and_recorded(monkeypatch):
    now = _fake_clock(monkeypatch)
    sess, m = make()
    sess = _Clocked(m, ["PRESS RETURN"])
    steps, sheet = FT.walk_afterwards(sess, timeout=5.0)
    assert sess.pressed == [] and not sheet
    assert steps[0]["row"] == "PRESS RETURN" and "refused" in steps[0]
    assert now[0] >= 5.0
