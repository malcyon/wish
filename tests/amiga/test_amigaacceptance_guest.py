"""`run_recon` drives a WinUAE lane and an FS-UAE lane through one route, and `--emulator` picks which."""

from __future__ import annotations

import pytest

from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.test_amigaacceptance import _audio_proof
from tests.amiga.test_amigaacceptance_accept import (  # noqa: F401
    AcceptGuest,
    Answer,
    MapGuard,
    _IdentityMap,
    _manifest,
    readings,
)
from tools.amiga import acceptance, fsuaesession
from tools.amiga.winuaesession import RouteError, WinGuest

clock = measure.clock  # the fixture that replaces the driver's time and sleep


class FsuaeNamedGuest(AcceptGuest):
    """`AcceptGuest` answering to `FsuaeGuest`'s lane names: bare disk names, and silence without a proof."""

    def __init__(self, clock):
        super().__init__(clock)
        self.lane = fsuaesession.FsuaeGuest()

    remote_path = staticmethod(fsuaesession.FsuaeGuest.remote_path)
    can_snapshot = False

    def silence(self, proof=None):
        return self.lane.silence(proof)


class SnapshotGuest(AcceptGuest):
    def __init__(self, clock):
        super().__init__(clock)
        self.machine = []

    def snapshot(self, name, holder):
        self.machine.append(("snapshot", name, holder))
        return f"snapshot {name}"

    def restore(self, name, holder):
        self.machine.append(("restore", name, holder))
        return f"restore {name}"


def _run(directory, guest, *, proof, **kw):
    directory.mkdir()
    guest.answer = Answer(guest)
    return acceptance.run_recon(
        _manifest(directory), guest=guest, guard=MapGuard(), identity=_IdentityMap(),
        holder="wish672-test", audio_proof=proof, accept=True, answer=guest.answer,
        preflight=lambda python: None, journal_python="python-with-numpy", **kw)


def _events(result):
    """The result's events with the paths dropped, which differ by where each run lived."""
    return [{k: v for k, v in event.items() if k not in ("raw", "crop")} for event in result["events"]]


def test_one_route_gives_the_same_result_events_on_either_lane(tmp_path, clock, readings):  # noqa: F811
    wind = AcceptGuest(clock)
    fs = FsuaeNamedGuest(clock)
    won = _run(tmp_path / "winuae", wind, proof=_audio_proof(tmp_path))
    fsuae = _run(tmp_path / "fsuae", fs, proof=None)
    assert won["error"] == "" and fsuae["error"] == ""
    assert won["success"] is fsuae["success"] is True
    assert _events(won) == _events(fsuae)
    assert measure._keys(wind) == measure._keys(fs)
    # Only the disk names differ: a Windows path for WinUAE, a bare name in the slot for FS-UAE.
    assert won["remote_df0"] == "C:/Amiga/Disks/wish672-wish672-test-df0.adf"
    assert fsuae["remote_df0"] == "wish672-wish672-test-df0.adf"


def test_an_fsuae_run_needs_no_mute_proof_and_a_winuae_run_blocks_without_one(tmp_path, clock):
    fs = FsuaeNamedGuest(clock)
    tmp_path.joinpath("fs").mkdir()
    result = acceptance.run_recon(_manifest(tmp_path / "fs"), guest=fs, holder="wish672-test",
                                  audio_proof=None, measure=True)
    assert "audio mute" not in result["error"]
    with pytest.raises(RouteError, match="audio mute"):
        acceptance.run_recon(_manifest(tmp_path), guest=WinGuest(), holder="wish672-test",
                             audio_proof=None, measure=True)


def test_snapshot_and_restore_go_through_the_guest(tmp_path, clock, readings):  # noqa: F811
    guest = SnapshotGuest(clock)
    marks = {11: (("snapshot", "walk"),), 13: (("restore", "walk"),)}
    result = _run(tmp_path / "run", guest, proof=_audio_proof(tmp_path), marks=marks)
    assert result["error"] == ""
    assert guest.machine == [("snapshot", "walk", "wish672-test"), ("restore", "walk", "wish672-test")]


def test_a_lane_that_cannot_snapshot_stops_a_snapshot_run_before_it_claims(tmp_path, clock, readings):  # noqa: F811
    for kw in ({"marks": {11: (("snapshot", "walk"),), 13: (("restore", "walk"),)}}, {"walk_retry": 1}):
        guest = FsuaeNamedGuest(clock)
        with pytest.raises(RouteError, match="needs a machine snapshot"):
            _run(tmp_path / f"run{len(kw)}{next(iter(kw))}", guest, proof=None, **kw)
        assert guest.calls == []


@pytest.fixture
def recorded(monkeypatch):
    seen = {}

    def run(manifest, **kw):
        seen.update(kw)
        return {"success": True, "error": ""}

    monkeypatch.setattr(acceptance, "run_recon", run)
    monkeypatch.setattr(acceptance, "_summary", lambda *a: "summary")
    return seen


def _measure(tmp_path, *extra):
    return acceptance.main(["measure", "--title", "pool", "--manifest", str(tmp_path / "prepare.json"),
                            "--attempt", "recon1", *extra])


def test_emulator_fsuae_builds_the_fsuae_lane_and_takes_no_audio_proof(tmp_path, recorded):
    assert _measure(tmp_path, "--emulator", "fsuae") == 0
    assert isinstance(recorded["guest"], fsuaesession.FsuaeGuest)
    assert recorded["audio_proof"] is None and recorded["guest"].first_key_after == 42.0
    assert recorded["guest"].game == "amiga-pool"


def test_winuae_stays_the_default_and_still_needs_its_audio_proof(tmp_path, recorded, monkeypatch, capsys):
    monkeypatch.setattr(acceptance, "WinGuest", lambda: "the windows lane")
    assert _measure(tmp_path, "--audio-proof", str(tmp_path / "mute.json")) == 0
    assert recorded["guest"] == "the windows lane" and recorded["audio_proof"] == tmp_path / "mute.json"
    with pytest.raises(SystemExit) as exc:
        _measure(tmp_path)
    assert exc.value.code == 2 and "--audio-proof is required with --emulator winuae" in capsys.readouterr().err


def test_an_fsuae_run_blocks_an_audio_proof_the_rulebook_draws_and_the_journal_answerer(
        tmp_path, recorded, capsys):
    with pytest.raises(SystemExit) as exc:
        _measure(tmp_path, "--emulator", "fsuae", "--audio-proof", str(tmp_path / "mute.json"))
    assert exc.value.code == 2 and "belongs to --emulator winuae" in capsys.readouterr().err
    common = ["accept", "--title", "ssb", "--emulator", "fsuae", "--manifest", str(tmp_path / "p.json"),
              "--guards", "g.json", "--identity", "i.json"]
    for extra, message in ((["--journal-python", "py"], "journal answerer has no FS-UAE route"),
                           (["--journal-python", "py", "--rulebook-draws", "2"], "needs --emulator winuae")):
        assert acceptance.main([*common, *extra]) == 2
        assert message in capsys.readouterr().err
    assert recorded == {}


def test_diagnose_has_no_emulator_choice(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        acceptance.main(["diagnose", "--title", "ssb", "--emulator", "fsuae", "--manifest", "m",
                         "--audio-proof", "a", "--guards", "g"])
    assert exc.value.code == 2 and "unrecognized arguments: --emulator fsuae" in capsys.readouterr().err
