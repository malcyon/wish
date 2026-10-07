"""`tools/c64/fasttravelrun.py` against a fake target, session and Fast Travel.

Nothing here boots VICE. The fakes keep one clock that every sleep advances, so a
bounded wait is measured in the seconds the driver asked for.
"""

from __future__ import annotations

import io
import json

import pytest

from automap import actions as engine
from tools.c64 import fasttravelrun as ftr

DISK_TEXT = "INSERT SIDE # 4 AND PRESS RETURN"


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Screen:
    def __init__(self, row24="", text=""):
        self._row, self._text = row24, text

    def row(self, n):
        assert n == 24
        return self._row

    def text(self):
        return self._text or self._row


class Kbd:
    def __init__(self):
        self.keys, self.shots = [], []

    def key(self, name, *a):
        self.keys.append(name)

    def screenshot(self, path):
        self.shots.append(path)


class Session:
    """Shows `screen_at(clock.now)`; answers a disk prompt once, as the real cooldown does."""

    def __init__(self, clock, screen_at):
        self.clock, self.screen_at = clock, screen_at
        self.kbd = Kbd()
        self.prompts, self.bars = 0, []
        self.no_encounters = False
        self.calls = []

    def suppress_encounters(self):
        self.calls.append(("suppress", self.no_encounters))

    def restore_encounter_gates(self):
        self.calls.append(("restore",))
        self.no_encounters = False
        return []

    def screen(self):
        return self.screen_at(self.clock.now)

    def wanted_disk(self, screen):
        return "SIDE4.D64" if "INSERT SIDE" in screen.text() else None

    def handle_prompt(self, screen=None):
        if self.prompts == 0 and self.wanted_disk(screen or self.screen()):
            self.prompts += 1
            return True
        return False

    def select_bar(self, label, **kw):
        self.bars.append(label)
        return True


class Memory:
    """A target whose bytes are a function of the clock."""

    def __init__(self, clock, area_at, script_at):
        self.clock, self.area_at, self.script_at = clock, area_at, script_at
        self.writes, self.closed = [], 0
        #: Bytes by address for what the arrival bytes do not cover; the rest read as zero.
        self.other = {}

    def read(self, addr, length):
        if addr in self.other:
            return bytes([self.other[addr]]) * length
        slot = {0x6E1B: self.area_at, 0x49F2: self.script_at}.get(addr)
        return bytes([slot(self.clock.now) if slot else 0]) * length

    def write(self, addr, data):
        self.writes.append((addr, bytes(data)))
        self.other[addr] = data[0]

    def close(self):
        self.closed += 1


class FakeFastTravel:
    def __init__(self, clock, memory, legal_other_at=0.0, busy=0):
        self.clock, self.memory = clock, memory
        self.legal_other_at, self.busy = legal_other_at, busy
        self.pending = None
        self.cancelled = 0
        self.applied = []
        self.continue_error = None
        self.continue_outcome = None
        self.apply_busy = 0
        self.apply_writes = []

    def legality(self, target, area):
        if self.busy:
            self.busy -= 1
            return engine.Verdict(False, engine.FASTTRAVEL_BUSY)
        here = target.read(0x6E1B, 1)[0]
        if here == area.id:
            return engine.Verdict(False, "the party is already in that area")
        if here != 7 and self.clock.now < self.legal_other_at:
            return engine.Verdict(False, engine.FASTTRAVEL_BUSY)
        return engine.Verdict(True)

    def apply(self, target, area=None, **kw):
        if self.apply_busy:
            self.apply_busy -= 1
            return engine.Outcome(False, engine.FASTTRAVEL_BUSY)
        self.applied.append(area.id)
        for addr, data in self.apply_writes:
            target.write(addr, data)
        return engine.Outcome(True, "walking out")

    def continue_pending(self, target):
        if self.continue_error:
            raise self.continue_error
        return self.continue_outcome

    def cancel_pending(self):
        self.cancelled += 1
        self.pending = None


_OUT = {}


@pytest.fixture(autouse=True)
def _out_dir(tmp_path):
    _OUT["dir"] = tmp_path


class Member:
    def __init__(self, name):
        self.name = name


class Party:
    def __init__(self, *names):
        self.members = [Member(n) for n in names]


def build(screen_at=lambda t: Screen(), area_at=None, script_at=None, answer=None,
          budget=60.0, connect=None, party_at=lambda t: None, game=None, peeks=None,
          stages=None, **ft_kw):
    clock = Clock()
    memory = Memory(clock, area_at or (lambda t: 7 if t < 1 else 18),
                    script_at or (lambda t: 7 if t < 1 else 18))
    sess = Session(clock, screen_at)
    ft = FakeFastTravel(clock, memory, **ft_kw)
    stream = io.StringIO()
    log = ftr.Log(stream, clock)
    drv = ftr.Driver(sess, connect or (lambda: memory), ft, _OUT["dir"], log, answer=answer,
                     sleep=clock.sleep, clock=clock, budget=budget, game=game, peeks=peeks,
                     stages=stages, party_reader=lambda target, game: party_at(clock.now))
    return drv, sess, ft, memory, clock, stream


def test_no_encounters_is_off_by_default():
    drv, sess, *_ = build()
    drv.run([18])
    assert sess.calls == [] and sess.no_encounters is False


def test_no_encounters_is_set_before_each_leg_and_restored_at_the_end():
    drv, sess, _ft, _mem, _clock, stream = build(budget=5.0)
    drv.no_encounters = True
    drv.run([18, 2])
    held = [(e["tag"], e["area"]) for e in events(stream) if e["event"] == "no_encounters"]
    # Leg 0 starts in 7 and loads 18; leg 1 starts in 18 and never leaves it.
    assert held == [("t0-to18", 7), ("t0-to18", 18), ("t1-to2", 18)]
    assert sess.calls == [("suppress", True)] * 3 + [("restore",)]
    assert [e["event"] for e in events(stream)][-1] == "encounter-gates"


def test_the_switch_follows_each_area_a_two_hop_trip_loads():
    # Through area 30 at 1 s (slot first, came-from a poll later), then 18 at 3 s.
    drv, sess, _ft, _mem, _clock, stream = build(
        area_at=lambda t: 7 if t < 1 else 30 if t < 3 else 18,
        script_at=lambda t: 7 if t < 1.5 else 30 if t < 3.5 else 18)
    drv.no_encounters = True
    assert drv.trip(18, "t")["result"] == "arrived"
    held = [e for e in events(stream) if e["event"] == "no_encounters"]
    assert [e["area"] for e in held] == [7, 7, 30, 30, 18]
    assert all(c == ("suppress", True) for c in sess.calls)
    # Each came-from/slot pair is held once, and the arrival one before arrival.
    arrived = next(e["t"] for e in events(stream) if e["event"] == "arrival-check")
    assert held[-1]["t"] <= arrived


def test_without_the_switch_no_hop_is_followed():
    drv, sess, *_ = build(area_at=lambda t: 7 if t < 1 else 30 if t < 3 else 18,
                          script_at=lambda t: 7 if t < 1 else 30 if t < 3 else 18)
    drv.trip(18, "t")
    assert sess.calls == []


def test_an_area_with_no_gate_is_logged_as_live():
    drv, _sess, _ft, _mem, _clock, stream = build()
    drv.no_encounters = True
    drv.gates = {(drv.game.key, 7): object()}
    drv.trip(18, "t")
    live = [e for e in events(stream) if e["event"] == "encounters-live"]
    assert [e["area"] for e in live] == [18]


def test_the_gate_table_defaults_to_the_sessions():
    from tools.c64 import session
    drv, *_ = build()
    assert drv._gate_table() is session.ENCOUNTER_GATES


def test_gates_are_restored_when_cancel_pending_raises():
    drv, sess, ft, *_ = build()
    drv.no_encounters = True

    def boom():
        raise RuntimeError("cancel failed")

    ft.cancel_pending = boom
    with pytest.raises(RuntimeError, match="cancel failed"):
        drv.run([18])
    assert sess.calls[-1] == ("restore",)


def test_a_failed_restore_is_noted_on_the_legs_own_error():
    drv, sess, ft, _mem, _clock, stream = build()
    drv.no_encounters = True

    def leg_boom(*a, **k):
        raise RuntimeError("leg failed")

    def restore_boom():
        sess.calls.append(("restore",))
        raise RuntimeError("gate unverified")

    ft.legality = leg_boom
    sess.restore_encounter_gates = restore_boom
    with pytest.raises(RuntimeError, match="leg failed") as raised:
        drv.run([18])
    assert any("gate unverified" in note for note in raised.value.__notes__)
    assert ft.cancelled == 1
    gates = [e for e in events(stream) if e["event"] == "encounter-gates"]
    assert gates and gates[-1]["verified"] is False


def test_gates_are_restored_when_a_leg_raises():
    drv, sess, ft, *_ = build()
    drv.no_encounters = True

    def boom(*a, **k):
        raise RuntimeError("stop")

    ft.legality = boom
    with pytest.raises(RuntimeError):
        drv.run([18])
    assert sess.calls[-1] == ("restore",)


def events(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_arrival_waits_for_both_bytes_and_for_legality():
    # $6E1B reaches 18 at 1 s, $49F2 at 3 s, and legality toward another area at 5 s.
    drv, _, _, _, clock, stream = build(
        area_at=lambda t: 7 if t < 1 else 18,
        script_at=lambda t: 7 if t < 3 else 18,
        legal_other_at=5.0)
    result = drv.trip(18, "t")
    assert result["result"] == "arrived"
    checks = [e for e in events(stream) if e["event"] == "arrival-check"]
    assert checks, "the bytes matched, so legality must have been asked"
    assert all(c["t"] >= 3.0 for c in checks)
    assert [c["legality"] for c in checks][:-1] == [False] * (len(checks) - 1)
    assert checks[-1]["legality"] is True and checks[-1]["t"] >= 5.0


def test_area_byte_alone_is_not_arrival():
    drv, _, _, _, _, stream = build(script_at=lambda t: 7, budget=10.0)
    assert drv.trip(18, "t")["result"] == "timeout"
    assert not [e for e in events(stream) if e["event"] == "arrival-check"]


def test_legality_is_asked_toward_a_different_area():
    asked = []
    drv, _, ft, _, _, _ = build()
    real = ft.legality
    ft.legality = lambda target, area: (asked.append(area.id), real(target, area))[1]
    drv.trip(18, "t")
    assert asked[-1] == 2
    assert ftr.other_area(2) == 18


def test_legality_toward_a_window_is_asked_about_another_window():
    windows = {25, 26, 27}
    assert ftr.other_area(27) in windows - {27}
    assert ftr.other_area(25) in windows - {25}
    assert ftr.other_area(26) in windows - {26}


def test_a_trip_to_a_window_arrives_under_the_grid_rule():
    # From the travel grid an indoor area is always illegal, so only another window can answer.
    drv, _, ft, _, _, _ = build(
        area_at=lambda t: 26 if t < 1 else 27, script_at=lambda t: 26 if t < 1 else 27)

    def legality(target, area):
        if not area.outdoors:
            return engine.Verdict(False, engine.FastTravel.OUTDOORS_TRAP)
        return engine.Verdict(True)
    ft.legality = legality
    assert drv.trip(27, "t")["result"] == "arrived"


def test_disk_prompt_is_answered_and_return_is_never_pressed():
    drv, sess, _, _, _, _ = build(
        screen_at=lambda t: Screen("PRESS RETURN", DISK_TEXT) if t < 5 else Screen(),
        area_at=lambda t: 7 if t < 6 else 18, script_at=lambda t: 7 if t < 6 else 18)
    assert drv.trip(18, "t")["result"] == "arrived"
    assert sess.prompts == 1
    assert sess.kbd.keys == []


def test_return_message_is_pressed():
    drv, sess, _, _, _, _ = build(
        screen_at=lambda t: Screen("PRESS BUTTON OR RETURN TO CONTINUE.") if t < 2 else Screen())
    drv.trip(18, "t")
    assert sess.kbd.keys and set(sess.kbd.keys) == {"Return"}


def test_move_sub_bar_is_recognised_and_left_alone():
    drv, sess, _, _, _, stream = build(
        screen_at=lambda t: Screen("I,J,K,M, RETURN OR BUTTON"), answer="RETURN")
    assert drv.trip(18, "t")["result"] == "arrived"
    assert sess.kbd.keys == [] and sess.bars == []
    assert all(e["did"] is None for e in events(stream) if e["event"] == "poll")


def test_answer_selects_the_bar_word_a_bounded_number_of_times():
    drv, sess, _, _, _, _ = build(
        screen_at=lambda t: Screen("YES NO"), answer="YES",
        script_at=lambda t: 7, budget=30.0)
    result = drv.trip(18, "t")
    assert sess.bars == ["YES"] * ftr.ANSWERS_PER_TRIP
    assert result["questions"] == ftr.ANSWERS_PER_TRIP


def test_no_answer_given_leaves_a_question_bar_alone():
    drv, sess, _, _, _, _ = build(screen_at=lambda t: Screen("YES NO"))
    drv.trip(18, "t")
    assert sess.bars == [] and sess.kbd.keys == []


def test_cannot_act_right_now_is_retried_half_a_second_later():
    drv, _, ft, _, clock, _ = build(
        busy=2, area_at=lambda t: 7 if t < 3 else 18, script_at=lambda t: 7 if t < 3 else 18)
    assert drv.trip(18, "t")["result"] == "arrived"
    assert ft.applied == [18]
    assert clock.sleeps[:2] == [ftr.BUSY_SECONDS, ftr.BUSY_SECONDS]
    assert ftr.BUSY_SECONDS == 0.5


def test_cannot_act_right_now_is_bounded():
    drv, _, ft, _, _, _ = build(busy=10_000)
    assert drv.trip(18, "t")["result"] == "not_legal"
    assert ft.busy == 10_000 - ftr.BUSY_TRIES
    assert ft.applied == []


def test_trip_that_never_arrives_times_out_and_is_disarmed():
    drv, _, ft, _, _, stream = build(area_at=lambda t: 7, script_at=lambda t: 7, budget=5.0)
    assert drv.trip(18, "t")["result"] == "timeout"
    assert ft.cancelled >= 1
    assert any(e["event"] == "timeout" for e in events(stream))


def test_disarm_on_exception():
    drv, _, ft, memory, _, _ = build()
    ft.continue_error = RuntimeError("monitor gone")
    with pytest.raises(RuntimeError):
        drv.run([18, 2])
    assert ft.cancelled >= 1
    assert memory.closed > 0, "every connection is closed, error or not"


def test_second_leg_runs_after_the_first_and_stops_at_a_failure():
    drv, _, ft, memory, _, _ = build(
        area_at=lambda t: 7 if t < 1 else 18, script_at=lambda t: 7 if t < 1 else 18)
    results = drv.run([18, 2, 15])
    assert [r["dest"] for r in results] == [18, 2]
    assert [r["result"] for r in results] == ["arrived", "timeout"]
    assert ft.applied == [18, 2]


def test_no_write_reaches_the_generator():
    target = ftr.GuardedTarget(Memory(Clock(), lambda t: 0, lambda t: 0))
    for addr, length in ((0x03C2, 1), (0x03C8, 1), (0x03C0, 4), (0x03C5, 9), (0x03C2, 7)):
        with pytest.raises(ftr.DriverError):
            target.write(addr, bytes(length))
    target.write(0x03C1, b"\x00")
    target.write(0x03C9, b"\x00" * 4)
    assert [a for a, _ in target._target.writes] == [0x03C1, 0x03C9]


def test_fast_travel_write_to_the_generator_stops_the_leg_and_disarms():
    drv, _, ft, memory, _, _ = build()
    ft.apply_writes = [(0x03C4, b"\x01")]
    with pytest.raises(ftr.DriverError):
        drv.trip(18, "t")
    assert memory.writes == []
    assert ft.cancelled >= 1, "trip() itself disarms when apply raises"


def test_source_never_names_a_generator_write():
    from pathlib import Path
    source = Path(ftr.__file__).read_text()
    assert ".write(0x03C" not in source


def test_bad_destination_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        ftr.main(["--save", "x.D64", "--to", "9999"])
    assert exc.value.code == 2


def test_cannot_act_right_now_is_retried_on_apply_too():
    drv, _, ft, _, clock, _ = build(
        area_at=lambda t: 7 if t < 3 else 18, script_at=lambda t: 7 if t < 3 else 18)
    ft.apply_busy = 2
    assert drv.trip(18, "t")["result"] == "arrived"
    assert ft.applied == [18]
    assert clock.sleeps[:2] == [ftr.BUSY_SECONDS, ftr.BUSY_SECONDS]


def test_cannot_act_right_now_on_apply_is_bounded():
    drv, _, ft, _, _, _ = build()
    ft.apply_busy = 10_000
    assert drv.trip(18, "t")["result"] == "not_applied"
    assert ft.apply_busy == 10_000 - ftr.BUSY_TRIES


def test_a_failed_continue_ends_the_leg_with_its_reason():
    drv, _, ft, _, clock, stream = build(
        area_at=lambda t: 7, script_at=lambda t: 7, budget=100.0)
    ft.continue_outcome = engine.Outcome(False, "the party never left")
    result = drv.trip(18, "t")
    assert result["result"] == "failed"
    assert result["reason"] == "the party never left"
    assert clock.now < 10.0, "the leg did not wait out its budget"
    assert ft.cancelled >= 1


def test_a_transient_connect_error_is_retried():
    calls = []

    def connect():
        calls.append(1)
        if len(calls) <= 2:
            raise ftr.NotConnected("monitor not up")
        return memory

    drv, _, _, memory, clock, stream = build(
        connect=connect, area_at=lambda t: 7 if t < 3 else 18,
        script_at=lambda t: 7 if t < 3 else 18)
    assert drv.trip(18, "t")["result"] == "arrived"
    assert [e["event"] for e in events(stream)].count("connect-retry") == 2


def test_connect_retry_is_bounded():
    calls = []

    def connect():
        calls.append(1)
        raise ftr.NotConnected("monitor not up")

    drv, *_ = build(connect=connect)
    with pytest.raises(ftr.NotConnected):
        drv.trip(18, "t")
    assert len(calls) == ftr.CONNECT_TRIES


def test_main_logs_a_failure_and_still_releases_the_slot(tmp_path, monkeypatch, capsys):
    from tools.c64 import session as S

    class Slot:
        dir = tmp_path
        released = torn = False

        def teardown(self):
            self.torn = True

        def release(self):
            self.released = True

    slot = Slot()
    monkeypatch.setattr(S, "claim_slot", lambda *a, **k: slot)

    def no_disks(*a, **k):
        raise ftr.DriverError("no disks staged")

    monkeypatch.setattr(S, "stage_disks", no_disks)
    with pytest.raises(SystemExit) as exc:
        ftr.main(["--save", "x.D64", "--to", "18", "--disks", str(tmp_path),
                  "--out", str(tmp_path / "out")])
    assert str(exc.value) == "no disks staged"
    logged = [json.loads(x) for x in (tmp_path / "out" / "run.jsonl").read_text().splitlines()]
    assert logged[-1]["event"] == "error" and "no disks staged" in logged[-1]["error"]
    assert slot.released and slot.torn


def walking(*areas):
    """An `area_at` that shows each area for one second, in order, then the last."""
    return lambda t: areas[min(int(t), len(areas) - 1)]


def test_areas_seen_records_every_area_change_between_screen_looks():
    # The middle area is on screen for under a second; the 2 s screen look never sees it.
    drv, _, _, _, _, stream = build(
        area_at=walking(13, 27, 0, 0), script_at=walking(13, 27, 0, 0))
    result = drv.trip(0, "t")
    assert result["result"] == "arrived"
    assert result["areas_seen"] == [13, 27, 0]
    assert [e["areas_seen"] for e in events(stream) if e["event"] == "areas-seen"] == [[13, 27, 0]]


def test_areas_seen_drops_the_reload_bit_and_repeats():
    drv, *_ = build(area_at=walking(7, 0x92, 18, 18), script_at=walking(7, 18, 18, 18))
    assert drv.trip(18, "t")["areas_seen"] == [7, 18]


def test_square_after_apply_is_logged():
    drv, _, _, memory, _, stream = build()
    memory.other.update({0xC04B: 4, 0xC04C: 5, 0xC04D: 6})
    drv.trip(18, "t")
    logged = [e for e in events(stream) if e["event"] == "square-after-apply"]
    assert len(logged) == 1 and logged[0]["square"] is not None


def test_peeks_are_logged_before_and_after_each_leg():
    drv, _, _, memory, _, stream = build(peeks=[(0x4A62, 3), (0x4AA9, 1)])
    memory.other[0x4AA9] = 9
    drv.trip(18, "t")
    peeks = [(e["when"], e["addr"], e["length"], e["bytes"])
             for e in events(stream) if e["event"] == "peek"]
    assert peeks == [("before", "$4A62", 3, "00 00 00"), ("before", "$4AA9", 1, "09"),
                     ("after", "$4A62", 3, "00 00 00"), ("after", "$4AA9", 1, "09")]


def test_party_names_are_logged_before_and_after_each_leg():
    drv, _, _, _, _, stream = build(
        party_at=lambda t: Party("ALIAS", "DRAGONBAIT") if t < 1 else Party("ALIAS"))
    drv.trip(18, "t")
    party = [(e["when"], e["names"]) for e in events(stream) if e["event"] == "party"]
    assert party == [("before", ["ALIAS", "DRAGONBAIT"]), ("after", ["ALIAS"])]


def test_an_unreadable_party_is_logged_as_none():
    drv, _, _, _, _, stream = build()
    drv.trip(18, "t")
    assert [e["names"] for e in events(stream) if e["event"] == "party"] == [None, None]


def test_stage_is_written_before_its_leg_only_and_logged_with_a_read_back():
    drv, _, ft, memory, _, stream = build(stages=[(1, 0x4AA9, 1)])
    drv.run([18, 2])
    staged = [e for e in events(stream) if e["event"] == "stage"]
    assert [(e["tag"], e["addr"], e["was"], e["value"], e["read_back"]) for e in staged] == [
        ("t1-to2", "$4AA9", 0, 1, 1)]
    assert memory.writes == [(0x4AA9, b"\x01")]
    log = [e["event"] for e in events(stream)]
    assert log.index("stage") < len(log) - log[::-1].index("apply")


def test_stage_goes_through_the_generator_guard():
    drv, *_ = build(stages=[(0, 0x03C4, 1)])
    with pytest.raises(ftr.DriverError):
        drv.trip(18, "t")


def test_stage_and_peek_arguments_parse():
    assert ftr.parse_peek("4A62:3") == (0x4A62, 3)
    assert ftr.parse_peek("$C059:2") == (0xC059, 2)
    assert ftr.parse_peek("4AA9") == (0x4AA9, 1)
    assert ftr.parse_stage("1:4AA9=1") == (1, 0x4AA9, 1)
    assert ftr.parse_stage("0:$4C5B=255") == (0, 0x4C5B, 255)
    assert ftr.parse_stage("2:4CD9=$FF") == (2, 0x4CD9, 255)
    for bad in ("4AA9=1", "1:4AA9=256", "1:4AA9", "1:03C4=1", "x:4AA9=1"):
        with pytest.raises(ftr.DriverError):
            ftr.parse_stage(bad)


def test_title_picks_the_addresses_the_table_and_the_other_area():
    from goldbox import c64_save
    silver = c64_save.SECRET_OF_THE_SILVER_BLADES
    memory_area = {0x7F1B: lambda t: 0x10 if t < 1 else 0x20,
                   0x4BF2: lambda t: 0x10 if t < 1 else 0x20}
    clock = Clock()
    memory = Memory(clock, memory_area[0x7F1B], memory_area[0x4BF2])
    memory.read = lambda addr, length, real=memory.read: (
        bytes([memory_area[addr](clock.now)]) * length if addr in memory_area
        else real(addr, length))
    stream = io.StringIO()
    ft = FakeFastTravel(clock, memory)
    drv = ftr.Driver(Session(clock, lambda t: Screen()), lambda: memory, ft, _OUT["dir"],
                     ftr.Log(stream, clock), sleep=clock.sleep, clock=clock, budget=60.0,
                     game=silver, party_reader=lambda target, game: None)
    result = drv.trip(0x20, "t")
    assert result["result"] == "arrived" and result["areas_seen"] == [0x10, 0x20]
    assert [e["area6E1B"] for e in events(stream) if e["event"] == "pre-apply"] == [0x10]
    assert engine.area_by_id(ftr.other_area(0x20, silver.title), silver.title) is not None
    assert ftr.other_area(0x20, silver.title) != 0x20


def test_a_title_has_a_container_and_an_unknown_one_is_an_error():
    assert ftr.container_for("curse-of-the-azure-bonds").key == "curse-of-the-azure-bonds"
    with pytest.raises(ftr.DriverError):
        ftr.container_for("champions-of-krynn")


def test_a_destination_is_checked_against_the_chosen_titles_table():
    # Area 9999 is in no title; the usage error names the title picked.
    with pytest.raises(SystemExit) as exc:
        ftr.main(["--title", "secret-of-the-silver-blades", "--save", "x.D64", "--to", "9999"])
    assert exc.value.code == 2


def test_a_stage_for_a_leg_that_does_not_exist_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        ftr.main(["--save", "x.D64", "--to", "18", "--stage", "1:4AA9=1"])
    assert exc.value.code == 2


def test_stage_on_the_generator_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        ftr.main(["--save", "x.D64", "--to", "18", "--stage", "0:03C4=1"])
    assert exc.value.code == 2
