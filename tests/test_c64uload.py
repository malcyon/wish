"""`tools/c64uload.py` without a C64 Ultimate on the network.

The 2026-09-06 runs on `#286 (Pool of Radiance on the C64 Ultimate sometimes
hangs on a disk load)` were lost because their verdicts were string matches --
a run was "hung" when `$DD00` read `$C4`, which is the commonest healthy value.
So what is under test here is the verdict: that only a jiffy clock that does
not move means hung, that the control sends nothing, that a failed request is
a record rather than an exit, and that the wall-to-jiffy fit puts a freeze
where it happened.  Nothing in this file opens a socket.
"""

import os
import sys
import time as real_time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import c64uload  # noqa: E402


class FakeTime:
    """A clock that only moves when something sleeps."""

    def __init__(self, start=1_000_000.0):
        self.now = start

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    strftime = staticmethod(real_time.strftime)
    localtime = staticmethod(real_time.localtime)


class Quiet:
    def write(self, kind, **fields):
        return {"kind": kind, **fields}


class FakeDevice(c64uload.Device):
    """Serves reads from a memory table; the jiffy follows the fake clock."""

    def __init__(self, clock, memory=None, jiffy_hz=60.0, frozen_at=None,
                 fail=False):
        super().__init__("nowhere", 80, Quiet())
        self.clock, self.memory = clock, dict(memory or {})
        self.jiffy_hz, self.frozen_at, self.fail = jiffy_hz, frozen_at, fail
        self.reads = []

    def jiffy(self):
        t = self.clock.now
        if self.frozen_at is not None:
            t = min(t, self.frozen_at)
        return int(t * self.jiffy_hz) & 0xFFFFFF

    def request(self, route, params=None, method="GET", body=None,
                timeout=None):
        record = {"route": route, "method": method, "send": self.clock.now,
                  "size": int(params.get("length", 0)) if params else 0}
        self.clock.sleep(0.02)
        record["reply"] = self.clock.now
        self.requests += 1
        if self.fail:
            record.update(status=None, error="<urlopen error refused>")
            self.failed_count += 1
            self.last_error = record
            if self.failed is None:
                self.failed = record
            self.log.write("request", **record)
            return record, b""
        data = b""
        if route == "/machine:readmem":
            address, length = int(params["address"], 16), record["size"]
            self.reads.append((address, length))
            if address == 0x00A0:
                j = self.jiffy()
                data = bytes([(j >> 16) & 0xFF, (j >> 8) & 0xFF, j & 0xFF])
            else:
                data = bytes(self.memory.get(address, b"\x00" * length))[:length]
                data = data.ljust(length, b"\x00")
        record.update(status=200, error=None)
        self.log.write("request", **record)
        return record, data


GAME = {0xD018: b"\x35", 0xDD00: b"\xc4", 0x0288: b"\xcc", 0x0314: b"\x00\x80"}
CRASHED = {0xD018: b"\x15", 0xDD00: b"\x97", 0x0288: b"\xcc",
           0x0314: b"\x31\xea"}


def patch_clock(monkeypatch):
    clock = FakeTime()
    monkeypatch.setattr(c64uload, "time", clock)
    return clock


def test_a_moving_jiffy_with_the_games_registers_is_the_game_running(
        monkeypatch):
    dev = FakeDevice(patch_clock(monkeypatch), GAME)
    check = c64uload.endcheck(dev, gap=10.0)
    assert check["verdict"] == "game-running"
    # Ten seconds at 60 Hz, plus the requests' own fake 20 ms each.
    assert 600 <= check["jiffy_moved"] <= 640


def test_a_frozen_jiffy_is_hung_whatever_dd00_says(monkeypatch):
    clock = patch_clock(monkeypatch)
    dev = FakeDevice(clock, GAME, frozen_at=clock.now - 5)
    check = c64uload.endcheck(dev, gap=10.0)
    assert check["verdict"] == "hung"
    assert check["jiffy_moved"] == 0
    assert check["first"]["dd00"] == 0xC4


def test_dd00_at_c4_with_the_jiffy_moving_is_not_a_hang(monkeypatch):
    dev = FakeDevice(patch_clock(monkeypatch), GAME)
    assert c64uload.endcheck(dev, gap=10.0)["verdict"] != "hung"


def test_the_kernal_vectors_back_with_the_games_screen_page_is_the_crash(
        monkeypatch):
    dev = FakeDevice(patch_clock(monkeypatch), CRASHED)
    assert c64uload.endcheck(dev, gap=10.0)["verdict"] == "crashed-to-basic"


def test_the_silent_control_sends_nothing(monkeypatch):
    clock = patch_clock(monkeypatch)
    dev = FakeDevice(clock, GAME)

    class Args:
        treatment, minutes, sample, still, interval = "silent", 1.0, 10.0, 30.0, 2.0
        size = at = None
        blip = 0.0

    summary = c64uload.apply(dev, dev.log, Args)
    assert summary["why"] == "time"
    assert dev.requests == 0
    assert dev.reads == []


def test_a_polled_run_stops_on_a_jiffy_that_stops(monkeypatch):
    clock = patch_clock(monkeypatch)
    dev = FakeDevice(clock, GAME, frozen_at=clock.now + 25)

    class Args:
        treatment, minutes, sample, still, interval = "readmem", 10.0, 10.0, 30.0, 5.0
        size, at = 7168, 0x4900
        blip = 0.0

    summary = c64uload.apply(dev, dev.log, Args)
    assert summary["why"] == "hang"
    # Stopped within a sample or two of `still` seconds after the freeze,
    # not at the ten-minute deadline.
    assert clock.now - 1_000_000.0 < 25 + 30 + 2 * 10 + 1
    assert (0x4900, 7168) in dev.reads


def test_a_failed_request_is_a_record_and_not_an_exit(monkeypatch):
    clock = patch_clock(monkeypatch)
    dev = FakeDevice(clock, GAME, fail=True)
    assert dev.readmem(0x00A0, 3) is None
    assert dev.failed["error"].startswith("<urlopen error")

    class Args:
        treatment, minutes, sample, still, interval = "readmem", 10.0, 10.0, 30.0, 5.0
        size, at = 7168, 0x4900
        blip = 0.0

    assert c64uload.apply(dev, dev.log, Args)["why"] == "device"


def test_a_lost_request_is_a_blip_when_the_device_still_answers(monkeypatch):
    clock = patch_clock(monkeypatch)
    dev = FakeDevice(clock, GAME)
    dev.fail = True
    calls = {"n": 0}
    real = dev.request

    def flaky(route, params=None, method="GET", body=None, timeout=None):
        calls["n"] += 1
        dev.fail = calls["n"] == 3   # the third request is lost, nothing else
        return real(route, params, method, body, timeout)

    dev.request = flaky
    dev.fail = False

    class Args:
        treatment, minutes, sample, still, interval = "readmem", 1.0, 0.0, 30.0, 5.0
        size, at = 7168, 0x4900
        blip = 60.0

    summary = c64uload.apply(dev, dev.log, Args)
    assert summary["why"] == "time"
    assert summary["failed_requests"] == 1


def synthetic_log(freeze_at, request_every=5.0, hz=59.94, minutes=15.0,
                  start=2_000_000.0):
    """Samples every ten seconds and requests every `request_every`, with
    the jiffy stopping at `freeze_at` seconds after `start`."""
    samples, requests = [], []
    t = 0.0
    while t < minutes * 60:
        j = int(min(t, freeze_at) * hz) + 12345
        samples.append({"kind": "sample", "t": start + t + 0.003, "jiffy": j})
        t += 10.0
    t = 0.0
    while t < minutes * 60:
        requests.append({"kind": "request", "route": "/machine:readmem",
                         "size": 7168, "send": start + t,
                         "reply": start + t + 0.048})
        t += request_every
    frozen = int(freeze_at * hz) + 12345
    return samples, requests, frozen


def test_the_fit_puts_a_freeze_inside_the_request_that_caused_it():
    # The freeze lands 30 ms after the send of the request at t = 305 s.
    samples, requests, frozen = synthetic_log(freeze_at=305.030)
    fit = c64uload.fit_freeze(samples, requests, frozen)
    assert "error" not in fit
    assert abs(fit["slope_hz"] - 59.94) < 0.01
    assert fit["residual_rms_ms"] < 20
    nearest = fit["nearest_request"]
    assert nearest["send"] == 2_000_000.0 + 305.0
    assert abs(nearest["offset_ms"] - 30) < 20   # one jiffy tick is 16.7 ms
    assert nearest["within_100ms"]


def test_the_fit_does_not_blame_a_request_two_seconds_away():
    samples, requests, frozen = synthetic_log(freeze_at=307.5)
    fit = c64uload.fit_freeze(samples, requests, frozen)
    nearest = fit["nearest_request"]
    assert not nearest["within_100ms"]
    assert not nearest["inside_window"]
    assert abs(abs(nearest["offset_ms"]) - 2500) < 30


def test_the_fit_refuses_with_too_few_moving_samples():
    samples, requests, frozen = synthetic_log(freeze_at=15.0, minutes=1.0)
    assert "error" in c64uload.fit_freeze(samples, requests, frozen)


def test_screen_address_follows_d018_and_the_vic_bank():
    assert c64uload.screen_address(0x15, 0x97) == 0x0400
    assert c64uload.screen_address(0x35, 0xC4) == 0xCC00
