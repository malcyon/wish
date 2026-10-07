"""`acceptance.py boot` leaves a prepared title's WinUAE running on a lane, and `halt` ends it."""

from __future__ import annotations

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

    def __init__(self, *, fail_start=False, fail_stop=False, fail_release=False):
        self.calls = []
        self.fail_start, self.fail_stop = fail_start, fail_stop
        self.fail_release = fail_release

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
