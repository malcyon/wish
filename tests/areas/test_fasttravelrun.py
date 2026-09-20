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
    return {"move": "1", "ok": ok, "before": (1, 1), "after": (1, 0),
            "refused": refused}


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
                        "after": (6, 5), "refused": None}
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
