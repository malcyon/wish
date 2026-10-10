"""`acceptance.py boot` leaves a prepared title's WinUAE running on a lane, and `halt` ends it."""

from __future__ import annotations

import hashlib
import json

import pytest

from tests.amiga.test_amigaacceptance import _audio_proof
from tests.amiga.test_amigaacceptance_title import make_title, manifest_for
from tools.amiga import acceptance
from tools.amiga.winuaesession import RouteError, WinGuest


class LaneGuest:
    """The calls `boot_lane` and `halt_lane` make of `WinGuest`, recorded."""

    remote_path = staticmethod(WinGuest.remote_path)
    silence = staticmethod(WinGuest.silence)

    def __init__(self, *, fail_start=False, fail_stop=False, fail_release=False,
                 fail_get=False):
        self.calls = []
        self.fail_start, self.fail_stop = fail_start, fail_stop
        self.fail_release = fail_release
        self.fail_get = fail_get

    def claim(self, holder, timeout=None, **kw):
        self.calls.append(("claim", holder))
        self.claim_kw = {"timeout": timeout, **kw}
        return f"ok claimed by {holder}"

    def put(self, local, remote, timeout=None):
        self.calls.append(("put", remote))

    def start(self, holder, *drives, timeout=None, options=()):
        self.calls.append(("start", holder, drives, tuple(options)))
        if self.fail_start:
            raise RouteError("WinUAE did not start")
        return "ok pid=1"

    def stop(self, holder, timeout=None):
        self.calls.append(("stop", holder))
        if self.fail_stop:
            raise RouteError("no emulator")
        return "ok stopped"

    def get(self, remote, local, timeout=None):
        self.calls.append(("get", remote))
        if self.fail_get:
            raise RouteError("download failed")
        local.write_bytes(b"disk " + remote.encode())

    def release(self, holder, timeout=None):
        self.calls.append(("release", holder))
        if self.fail_release:
            raise RouteError("lane host unreachable")
        return "ok released"


def _boot(tmp_path, guest, **kw):
    path = manifest_for(tmp_path)
    return acceptance.boot_lane(path, json.loads(path.read_text()), make_title(), guest=guest,
                                holder="wish679-boot", audio_proof=_audio_proof(tmp_path), **kw)


def test_boot_puts_every_disk_on_the_lane_starts_it_and_leaves_it_running(tmp_path):
    guest = LaneGuest()
    result = _boot(tmp_path, guest)
    names = [call[0] for call in guest.calls]
    assert names == ["claim", "put", "put", "put", "start"]
    boot, spare, disk3 = (guest.remote_path("679", "wish679-boot", k)
                          for k in ("boot", "spare", "disk3"))
    assert {call[1] for call in guest.calls if call[0] == "put"} == {boot, spare, disk3}
    assert guest.calls[-1] == ("start", "wish679-boot", (boot, None, disk3),
                               ("nr_floppies=3", "floppy2type=0"))
    assert result["start"] == "ok pid=1" and result["holder"] == "wish679-boot"


def test_boot_without_a_fresh_mute_proof_claims_nothing(tmp_path):
    guest = LaneGuest()
    path = manifest_for(tmp_path)
    with pytest.raises(RouteError, match="audio mute"):
        acceptance.boot_lane(path, json.loads(path.read_text()), make_title(), guest=guest,
                             holder="wish679-boot", audio_proof=tmp_path / "missing.json")
    assert guest.calls == []


def test_a_failed_start_stops_the_emulator_and_releases_the_lane(tmp_path):
    guest = LaneGuest(fail_start=True)
    with pytest.raises(RouteError, match="did not start"):
        _boot(tmp_path, guest)
    assert [c[0] for c in guest.calls][-2:] == ["stop", "release"]


def test_a_failed_start_whose_release_also_fails_names_the_release_failure(tmp_path):
    guest = LaneGuest(fail_start=True, fail_release=True)
    with pytest.raises(RouteError, match="did not start.*release: lane host unreachable"):
        _boot(tmp_path, guest)


def test_boot_with_wait_lane_waits_for_the_claim(tmp_path):
    guest = LaneGuest()
    _boot(tmp_path, guest, wait_lane=60.0)
    assert guest.claim_kw == {"timeout": 30, "wait": 60.0}


def test_boot_of_the_legacy_silver_blades_route_is_blocked_before_a_claim(tmp_path):
    guest = LaneGuest()
    with pytest.raises(RouteError, match="legacy"):
        acceptance.boot_lane(tmp_path / "x.json", {}, None, guest=guest, holder="h",
                             audio_proof=_audio_proof(tmp_path))
    assert guest.calls == []


def test_halt_stops_then_releases_and_still_releases_when_the_stop_fails():
    guest = LaneGuest()
    assert acceptance.halt_lane(guest, "h") == {"stop": "ok stopped", "release": "ok released"}
    failing = LaneGuest(fail_stop=True)
    with pytest.raises(RouteError, match="stop: no emulator"):
        acceptance.halt_lane(failing, "h")
    assert [c[0] for c in failing.calls] == ["stop", "release"]


def test_the_boot_and_halt_commands_reach_the_lane(tmp_path, monkeypatch, capsys):
    guest = LaneGuest()
    monkeypatch.setattr(acceptance, "WinGuest", lambda: guest)
    path = manifest_for(tmp_path)
    monkeypatch.setitem(acceptance.TITLES, "synthetic", make_title())
    assert acceptance.main(["boot", "--title", "synthetic", "--manifest", str(path),
                            "--audio-proof", str(_audio_proof(tmp_path)),
                            "--holder", "wish679-boot"]) == 0
    assert json.loads(capsys.readouterr().out)["start"] == "ok pid=1"
    assert acceptance.main(["halt", "--holder", "wish679-boot"]) == 0
    assert [c[0] for c in guest.calls][-2:] == ["stop", "release"]
    with pytest.raises(SystemExit):
        acceptance.main(["boot", "--title", "synthetic", "--manifest", str(path),
                         "--audio-proof", str(_audio_proof(tmp_path))])


def _lane_lines(path):
    return [json.loads(line) for line in (path.parent / "lanes.jsonl").read_text().splitlines()]


def test_boot_records_its_command_and_remotes_in_the_run_folder(tmp_path, monkeypatch):
    guest = LaneGuest()
    monkeypatch.setattr(acceptance, "WinGuest", lambda: guest)
    path = manifest_for(tmp_path)
    monkeypatch.setitem(acceptance.TITLES, "synthetic", make_title())
    assert acceptance.main(["boot", "--title", "synthetic", "--manifest", str(path),
                            "--audio-proof", str(_audio_proof(tmp_path)),
                            "--holder", "wish679-boot"]) == 0
    line = _lane_lines(path)[-1]
    assert line["event"] == "boot" and line["holder"] == "wish679-boot"
    assert "boot" in line["command"] and "--holder" in line["command"]
    assert line["remotes"] == {k: guest.remote_path("679", "wish679-boot", k)
                               for k in ("boot", "spare", "disk3")}


def test_halt_with_the_manifest_fetches_every_booted_disk_between_the_stop_and_the_release(tmp_path):
    guest = LaneGuest()
    result = _boot(tmp_path, guest)
    path = manifest_for(tmp_path)
    guest.calls.clear()
    acceptance.halt_lane(guest, "wish679-boot", manifest_path=path)
    assert [c[0] for c in guest.calls] == ["stop", "get", "get", "get", "release"]
    folder = path.parent / "halt-wish679-boot-1"
    halt = _lane_lines(path)[-1]
    assert halt["event"] == "halt"
    for key, remote in result["remotes"].items():
        fetched = folder / f"fetched-{key}.adf"
        assert fetched.read_bytes() == b"disk " + remote.encode()
        assert halt["fetched"][key]["sha256"] == hashlib.sha256(fetched.read_bytes()).hexdigest()


def test_a_halt_whose_stop_fails_fetches_nothing_and_still_releases(tmp_path):
    _boot(tmp_path, LaneGuest())
    failing = LaneGuest(fail_stop=True)
    # The earlier boot's line is in the folder; this guest only sees the halt.
    with pytest.raises(RouteError, match="stop: no emulator"):
        acceptance.halt_lane(failing, "wish679-boot", manifest_path=manifest_for(tmp_path))
    assert [c[0] for c in failing.calls] == ["stop", "release"]
    assert not [c for c in failing.calls if c[0] == "get"]


def test_a_halt_with_no_boot_record_stops_releases_and_says_why(tmp_path):
    guest = LaneGuest()
    with pytest.raises(RouteError, match="no boot record"):
        acceptance.halt_lane(guest, "wish679-boot", manifest_path=manifest_for(tmp_path))
    assert [c[0] for c in guest.calls] == ["stop", "release"]


def test_the_halt_command_takes_the_manifest(tmp_path, monkeypatch):
    guest = LaneGuest()
    monkeypatch.setattr(acceptance, "WinGuest", lambda: guest)
    _boot(tmp_path, guest)
    path = manifest_for(tmp_path)
    guest.calls.clear()
    assert acceptance.main(["halt", "--holder", "wish679-boot", "--manifest", str(path)]) == 0
    assert [c[0] for c in guest.calls] == ["stop", "get", "get", "get", "release"]


def test_a_failed_fetch_still_releases_the_lane(tmp_path):
    _boot(tmp_path, LaneGuest())
    guest = LaneGuest(fail_get=True)
    with pytest.raises(RouteError, match="fetch boot: download failed"):
        acceptance.halt_lane(guest, "wish679-boot", manifest_path=manifest_for(tmp_path))
    assert [c[0] for c in guest.calls][-1] == "release"


def test_a_failed_boot_writes_an_error_line_and_halt_fetches_from_the_last_good_boot(tmp_path):
    path = manifest_for(tmp_path)
    good = _boot(tmp_path, LaneGuest())
    with pytest.raises(RouteError, match="did not start"):
        _boot(tmp_path, LaneGuest(fail_start=True))
    lines = _lane_lines(path)
    assert "error" not in lines[0] and "did not start" in lines[1]["error"]
    guest = LaneGuest()
    acceptance.halt_lane(guest, "wish679-boot", manifest_path=path)
    assert {c[1] for c in guest.calls if c[0] == "get"} == set(good["remotes"].values())


def test_an_unwritable_lane_log_at_boot_still_releases_the_lane(tmp_path):
    (manifest_for(tmp_path).parent / "lanes.jsonl").mkdir()
    guest = LaneGuest(fail_start=True)
    with pytest.raises(RouteError, match="did not start.*log:"):
        _boot(tmp_path, guest)
    assert [c[0] for c in guest.calls][-2:] == ["stop", "release"]


def test_an_unwritable_lane_log_after_a_good_boot_leaves_the_run_going(tmp_path):
    (manifest_for(tmp_path).parent / "lanes.jsonl").mkdir()
    guest = LaneGuest()
    result = _boot(tmp_path, guest)
    assert result["start"] == "ok pid=1" and "log_error" in result
    assert [c[0] for c in guest.calls][-1] == "start"


def test_a_corrupt_lane_log_at_halt_still_stops_and_releases(tmp_path):
    path = manifest_for(tmp_path)
    (path.parent / "lanes.jsonl").write_text("not json\n", encoding="utf-8")
    guest = LaneGuest()
    with pytest.raises(RouteError, match="read lanes.jsonl"):
        acceptance.halt_lane(guest, "wish679-boot", manifest_path=path)
    assert [c[0] for c in guest.calls] == ["stop", "release"]


def test_a_plain_halt_creates_no_lane_log_and_no_halt_folder(tmp_path):
    path = manifest_for(tmp_path)
    acceptance.halt_lane(LaneGuest(), "wish679-boot")
    assert not (path.parent / "lanes.jsonl").exists()
    assert not list(path.parent.glob("halt-*"))


def test_a_boot_line_without_remotes_still_stops_and_releases_and_reports_it(tmp_path):
    path = manifest_for(tmp_path)
    line = json.dumps({"event": "boot", "holder": "wish679-boot"})
    (path.parent / "lanes.jsonl").write_text(line + "\n", encoding="utf-8")
    guest = LaneGuest()
    with pytest.raises(RouteError, match="boot record has no remotes"):
        acceptance.halt_lane(guest, "wish679-boot", manifest_path=path)
    assert [c[0] for c in guest.calls] == ["stop", "release"]
