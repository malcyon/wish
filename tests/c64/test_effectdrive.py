"""`route_pool.sample` reads all 64 slots of each running-effect array, and
`route_pool.rest` drives each title's own rest-time bar.

A converted running effect can land in either of the last two slots (62/63),
so a reader that only sees the first 16 bytes of a 64-byte array would report
an empty party even while an effect is running.
"""

from __future__ import annotations

import pytest

from goldbox import c64_port, effects
from tools.c64 import route_pool as E


class FakeMemory:
    """A flat 64K image, read the way `Session.mon()`'s `m` is read."""

    def __init__(self):
        self.mem = bytearray(0x10000)

    def read(self, addr: int, length: int) -> bytes:
        return bytes(self.mem[addr:addr + length])


def _planted(slot: int) -> FakeMemory:
    m = FakeMemory()
    m.mem[E.SAVE0_LOAD + effects.EFFECT_ID_OFFSET + slot] = 0x11
    m.mem[E.SAVE0_LOAD + effects.EFFECT_OWNER_OFFSET + slot] = 0x22
    m.mem[E.SAVE0_LOAD + effects.EFFECT_DURATION_OFFSET + slot] = 0x33
    m.mem[E.SAVE0_LOAD + effects.EFFECT_MAGNITUDE_OFFSET + slot] = 0x44
    return m


def test_sample_reads_a_converted_effect_in_the_last_two_slots():
    for slot in (62, 63):
        m = _planted(slot)
        result = E.sample(m)
        assert result["id"][slot] == 0x11
        assert result["owner"][slot] == 0x22
        assert result["duration"][slot] == 0x33
        assert result["magnitude"][slot] == 0x44
        assert len(result["id"]) == 0x40
        assert len(result["owner"]) == 0x40
        assert len(result["duration"]) == 0x40
        assert len(result["magnitude"]) == 0x40


# -- `route_pool.rest` on each title's rest-time bar -------------------------

CAMP_ROW = "SAVE VIEW MAGIC REST ALTER FIX EXIT"
LATER_REST_ROW = "REST  ADD  SUBTRACT  EXIT"
POOL_REST_ROW = "REST INCREASE DECREASE EXIT"


class FakeScreen:
    def __init__(self, bar: str):
        self._rows = [""] * 24 + [bar]

    def row(self, n: int) -> str:
        return self._rows[n]

    def rows(self) -> list[str]:
        return list(self._rows)


class FakeMon(FakeMemory):
    """A 64K image with the monitor's write, resume and checkpoint count."""

    def write(self, addr: int, data: bytes) -> None:
        self.mem[addr:addr + len(data)] = data

    def resume(self) -> None:
        pass

    def checkpoint_hits(self, number: int) -> int:
        return number


class RestingSession:
    """Camp bar, then the title's rest-time bar on REST, then a rest the
    fake game runs five minutes at a time out of the field `field` into the
    clock at `base + $C6` -- up to `stop_after` passes, when it stops and
    puts `stop_bar` on row 24, zeroing the field first if `clear_on_stop`."""

    def __init__(self, game, field: int, base: int, rest_row: str,
                 stop_after: int | None = None,
                 stop_bar: str = "THE PARTY IS ATTACKED",
                 clear_on_stop: bool = False):
        self.game = game
        self.field, self.base, self.rest_row = field, base, rest_row
        self.stop_after = stop_after
        self.stop_bar, self.clear_on_stop = stop_bar, clear_on_stop
        self.bar = CAMP_ROW
        self.m = FakeMon()
        self.m.write(E.CAMP_TICK, E.CAMP_TICK_BYTES)
        self.pressed: list[str] = []
        self.written: bytes | None = None
        self.resting = False
        self.passes = 0
        #: Rows the stopping screen draws above `stop_bar`, by row number.
        self.stop_text: dict[int, str] = {}

    def _select(self, label: str, **_) -> bool:
        self.pressed.append(label)
        if label != "REST" or "REST" not in self.bar:
            return False
        if self.bar == CAMP_ROW:
            self.bar = self.rest_row
        else:
            self.written = bytes(self.m.read(self.field, 3))
            self.resting, self.bar = True, ""
        return True

    select_bar = _select

    def screen(self):
        screen = FakeScreen(self.bar)
        if self.bar == self.stop_bar:
            for row, line in self.stop_text.items():
                screen._rows[row] = line
        return screen

    def wait_text(self, needle: str, timeout: float = 0):
        s = self.screen()
        return (s, 0) if needle in s.row(24) else (None, None)

    def _pass(self) -> None:
        if self.bar == self.stop_bar:
            return
        mins, hours, days = self.m.read(self.field, 3)
        left = (days * 24 + hours) * 60 + mins
        if not left:
            self.resting, self.bar = False, CAMP_ROW
            return
        if self.stop_after is not None and self.passes >= self.stop_after:
            if self.clear_on_stop:
                self.m.write(self.field, bytes(3))
            self.bar = self.stop_bar
            return
        self.passes += 1
        left = max(0, left - 5)
        self.m.write(self.field, bytes((left % 60, left // 60 % 24, left // 1440)))
        clock = self.base + E.CLOCK - E.SAVE0_LOAD
        _, units, tens, hour, day, month = self.m.read(clock, 6)
        now = (day * 24 + hour) * 60 + tens * 10 + units + 5
        self.m.write(clock, bytes((0, now % 10, now % 60 // 10, now // 60 % 24,
                                   now // 1440, month)))

    def mon(self, timeout: float = 0):
        sess = self

        class Stop:
            def __enter__(self):
                if sess.resting:
                    sess._pass()
                return sess.m

            def __exit__(self, *exc):
                return False

        return Stop()


class LaterPressSession(RestingSession):
    """A later title's session, which has `press_bar` as well."""

    def press_bar(self, label: str, **kw) -> bool:
        return self._select(label, **kw)


class RestLog:
    def __init__(self):
        self.said, self.events = [], []

    def say(self, text: str) -> None:
        self.said.append(text)

    def emit(self, kind: str, **kw) -> None:
        self.events.append((kind, kw))


def _clock_minutes(clock: list[int]) -> int:
    _, units, tens, hour, day, _ = clock
    return (day * 24 + hour) * 60 + tens * 10 + units


def _rest(monkeypatch, sess, minutes: int, hours: int) -> dict:
    monkeypatch.setattr(E.time, "sleep", lambda _: None)
    return E.rest(sess, RestLog(), minutes, hours, {"sweep": 7})


def test_a_silver_blades_rest_writes_its_own_field_and_runs_ten_hours(monkeypatch):
    """The Silver Blades bar is `REST ADD SUBTRACT EXIT`, with no `INCREASE`."""
    sess = LaterPressSession(c64_port.SECRET_OF_THE_SILVER_BLADES, 0x2A8E,
                             E.LATER_LOAD, LATER_REST_ROW)
    got = _rest(monkeypatch, sess, 0, 10)
    assert "failed" not in got, got
    assert sess.written == bytes((0, 10, 0))
    assert sess.pressed == ["REST", "REST"]
    assert sess.passes == 120
    assert _clock_minutes(got["after"]["clock"]) - _clock_minutes(
        got["before"]["clock"]) == 600
    assert got["ended"] == "completed" and got["interrupted"] is False
    assert got["rest_left"] == [0, 0, 0] and "still_reads" not in got
    assert got["sweep"] == 7
    assert "staging_str" not in got["before"]


def test_a_curse_rest_carries_hours_past_a_day_into_the_days_byte(monkeypatch):
    sess = LaterPressSession(c64_port.CURSE_OF_THE_AZURE_BONDS, 0x2C1B,
                             E.LATER_LOAD, LATER_REST_ROW)
    got = _rest(monkeypatch, sess, 30, 25)
    assert sess.written == bytes((30, 1, 1))
    assert _clock_minutes(got["after"]["clock"]) - _clock_minutes(
        got["before"]["clock"]) == 25 * 60 + 30
    assert got["interrupted"] is False


def test_a_later_rest_the_game_stops_is_reported_with_the_time_left(monkeypatch):
    sess = LaterPressSession(c64_port.SECRET_OF_THE_SILVER_BLADES, 0x2A8E,
                             E.LATER_LOAD, LATER_REST_ROW, stop_after=3)
    got = _rest(monkeypatch, sess, 0, 1)
    assert got["ended"] == "interrupted" and got["interrupted"] is True
    assert got["still_reads"] == E.LATER_REST_STILL
    assert got["rest_left"] == [45, 0, 0]
    assert got["bar"] == "THE PARTY IS ATTACKED"
    assert _clock_minutes(got["after"]["clock"]) - _clock_minutes(
        got["before"]["clock"]) == 15


def test_a_later_rest_an_event_stops_reports_the_events_text(monkeypatch):
    """Silver Blades' Black Circle event stops a rest over its PRESS bar; the
    result carries the words, without the frame, and the bar."""
    sess = LaterPressSession(c64_port.SECRET_OF_THE_SILVER_BLADES, 0x2A8E,
                             E.LATER_LOAD, LATER_REST_ROW, stop_after=96,
                             stop_bar="PRESS BUTTON OR RETURN TO CONTINUE.")
    sess.stop_text = {17: "$THE BLACK CIRCLE SENDS MONSTERS       $",
                      18: "%AGAINST THE TOWN. TOWNSMEN RUSH TO    %",
                      19: "%YOUR AID.                             %",
                      20: "%                                      %"}
    got = _rest(monkeypatch, sess, 0, 10)
    assert got["ended"] == "interrupted" and got["interrupted"] is True
    assert got["bar"] == "PRESS BUTTON OR RETURN TO CONTINUE."
    assert got["text"] == ["THE BLACK CIRCLE SENDS MONSTERS",
                           "AGAINST THE TOWN. TOWNSMEN RUSH TO", "YOUR AID."]
    assert got["rest_left"] == [0, 2, 0]


def test_a_later_rest_that_clears_the_field_off_the_camp_bar_is_not_completed(
        monkeypatch):
    """A zero field is not the end of a rest unless the camp bar is back."""
    sess = LaterPressSession(c64_port.SECRET_OF_THE_SILVER_BLADES, 0x2A8E,
                             E.LATER_LOAD, LATER_REST_ROW, stop_after=3,
                             stop_bar="PRESS RETURN TO CONTINUE",
                             clear_on_stop=True)
    got = _rest(monkeypatch, sess, 0, 1)
    assert got["rest_left"] == [0, 0, 0]
    assert got["ended"] == "interrupted" and got["interrupted"] is True
    assert got["bar"] == "PRESS RETURN TO CONTINUE"


def test_a_later_rest_that_stops_on_its_own_bar_is_stalled_not_interrupted(
        monkeypatch):
    sess = LaterPressSession(c64_port.SECRET_OF_THE_SILVER_BLADES, 0x2A8E,
                             E.LATER_LOAD, LATER_REST_ROW, stop_after=3,
                             stop_bar=LATER_REST_ROW)
    got = _rest(monkeypatch, sess, 0, 1)
    assert got["ended"] == "stalled" and got["interrupted"] is False
    assert got["still_reads"] == E.LATER_REST_STILL


def test_a_later_rest_that_outlasts_its_time_ends_at_the_deadline(monkeypatch):
    """A 25 h rest is 300 passes; with 100 s going by per read the time runs
    out first, and that is reported apart from anything the game did."""
    sess = LaterPressSession(c64_port.CURSE_OF_THE_AZURE_BONDS, 0x2C1B,
                             E.LATER_LOAD, LATER_REST_ROW)
    now = [0.0]

    def tick():
        now[0] += 100.0
        return now[0]

    monkeypatch.setattr(E.time, "time", tick)
    got = _rest(monkeypatch, sess, 0, 25)
    assert got["ended"] == "deadline" and got["interrupted"] is False
    assert got["rest_left"] != [0, 0, 0] and "still_reads" not in got
    assert 0 < sess.passes < 300


def test_a_long_later_rest_is_given_time_for_every_pass(monkeypatch):
    """255 h is 3060 passes; at one pass per read and half a second a read it
    needs about 1530 s, past `LATER_REST_DEADLINE`, and still completes."""
    sess = LaterPressSession(c64_port.SECRET_OF_THE_SILVER_BLADES, 0x2A8E,
                             E.LATER_LOAD, LATER_REST_ROW)
    now = [0.0]

    def tick():
        now[0] += 0.5
        return now[0]

    monkeypatch.setattr(E.time, "time", tick)
    got = _rest(monkeypatch, sess, 0, 255)
    assert sess.written == bytes((0, 15, 10))
    assert got["ended"] == "completed" and sess.passes == 3060


def test_a_later_rest_of_no_time_is_refused_before_anything_is_pressed(
        monkeypatch):
    sess = LaterPressSession(c64_port.SECRET_OF_THE_SILVER_BLADES, 0x2A8E,
                             E.LATER_LOAD, LATER_REST_ROW)
    assert _rest(monkeypatch, sess, 0, 0) == {"failed": "a rest of no time"}
    assert sess.pressed == []


def test_a_later_rest_too_long_for_the_field_is_refused_before_anything_is_pressed(
        monkeypatch):
    """Minutes or days past a byte cannot be written, so nothing is pressed."""
    for minutes, hours in ((300, 0), (0, 256 * 24)):
        sess = LaterPressSession(c64_port.SECRET_OF_THE_SILVER_BLADES, 0x2A8E,
                                 E.LATER_LOAD, LATER_REST_ROW)
        got = _rest(monkeypatch, sess, minutes, hours)
        assert "does not fit" in got["failed"]
        assert sess.pressed == []


def test_a_later_rest_reads_the_arrays_at_4b00():
    m = FakeMemory()
    m.mem[E.LATER_LOAD + effects.EFFECT_ID_OFFSET + 63] = 22
    m.mem[E.LATER_LOAD + effects.EFFECT_MAGNITUDE_OFFSET + 63] = 0x7F
    m.mem[E.LATER_LOAD + 0xC6 + 3] = 9
    got = E.sample(m, E.LATER_LOAD)
    assert got["id"][63] == 22 and got["magnitude"][63] == 0x7F
    assert got["clock"][3] == 9


def test_a_pool_rest_still_waits_for_increase_and_writes_2898(monkeypatch):
    """A Pool session keeps its own bar, field and third byte of zero, and
    its sample keeps the staging page's strength bytes."""
    sess = RestingSession(c64_port.POOL_OF_RADIANCE, E.REST_TIME,
                          E.SAVE0_LOAD, POOL_REST_ROW)
    got = _rest(monkeypatch, sess, 30, 1)
    assert "failed" not in got, got
    assert sess.written == bytes((30, 1, 0))
    assert _clock_minutes(got["after"]["clock"]) - _clock_minutes(
        got["before"]["clock"]) == 90
    assert "staging_str" in got["before"] and "records" in got
    assert "interrupted" not in got


class PoolInterruptedSession(RestingSession):
    """Pool's rest stopped by the area's check.  `left_camp` false: `$FF` in
    `$6DD3` with `CAMP` still at `$0800`.  True: the live New Phlan reading,
    `CAMP` replaced and `$6DD3` back at 0 while the rest-time bar is still
    drawn."""

    left_camp = False

    def _pass(self) -> None:
        super()._pass()
        if self.bar == self.stop_bar:
            if self.left_camp:
                self.m.write(E.CAMP_TICK, bytes((0xA8, 0x03, 0xCA, 0x10, 0xFA)))
                self.m.write(E.REST_MARKER, bytes(1))
            else:
                self.m.write(E.REST_MARKER, bytes((E.REST_INTERRUPTED,)))


@pytest.mark.parametrize("left_camp", [False, True])
def test_a_pool_rest_the_check_interrupts_is_reported_with_its_bar(
        monkeypatch, left_camp):
    sess = PoolInterruptedSession(c64_port.POOL_OF_RADIANCE, E.REST_TIME,
                                  E.SAVE0_LOAD, POOL_REST_ROW, stop_after=1,
                                  stop_bar=POOL_REST_ROW)
    sess.left_camp = left_camp
    got = _rest(monkeypatch, sess, 0, 1)
    assert got["ended"] == "interrupted" and got["interrupted"] is True
    assert got["bar"] == POOL_REST_ROW
    assert got["rest_marker"] == (0 if left_camp else E.REST_INTERRUPTED)
    assert got["camp_resident"] is (not left_camp)
    assert sess.pressed == ["REST", "REST"]
    assert _clock_minutes(got["after"]["clock"]) - _clock_minutes(
        got["before"]["clock"]) == 5


def test_a_pool_rest_refuses_the_later_titles_bar(monkeypatch):
    sess = RestingSession(c64_port.POOL_OF_RADIANCE, E.REST_TIME,
                          E.SAVE0_LOAD, LATER_REST_ROW)
    assert _rest(monkeypatch, sess, 0, 1) == {"failed": "no rest-time bar"}
