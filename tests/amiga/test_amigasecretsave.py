"""The standalone Amiga save stays exact while a failed reconnaissance keeps evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from goldbox.amiga_adf import AmigaDisk
from tools.amiga import amigasecretsave


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _disk(path, volume, slot=None):
    disk = AmigaDisk.blank(volume)
    if slot:
        disk.make_dir("/SAVE")
        disk.write_file(f"/SAVE/savgam{slot}.sav", b"composed save")
    disk.save(path)


class FailedPostWriteGuest:
    def __init__(self):
        self.calls = []
        self.remote = {}
        self.drives = None

    def claim(self, holder, timeout=None):
        self.calls.append(("claim", holder))
        return f"ok claimed by {holder}"

    def put(self, local, remote, timeout=None):
        self.calls.append(("put", str(local), remote))
        self.remote[remote] = local.read_bytes()

    def start(self, holder, df0, df1, timeout=None):
        self.calls.append(("start", holder, df0, df1))
        self.drives = (df0, df1)
        return "ok pid=123 session=1"

    def capture(self, state, raw, cropped, timeout=None):
        self.calls.append(("capture", state))
        raw.write_bytes(b"raw " + state.encode())
        cropped.write_bytes(b"crop " + state.encode())

    def press(self, holder, key, timeout=None):
        self.calls.append(("press", holder, key))
        if key == "B":
            disk = AmigaDisk(self.remote[self.drives[1]])
            disk.write_file("/SAVE/savgamB.sav", b"engine wrote B")
            self.remote[self.drives[1]] = disk.to_bytes()
            raise RuntimeError("save prompt after B")

    def stop(self, holder, timeout=None):
        self.calls.append(("stop", holder))

    def get(self, remote, local, timeout=None):
        self.calls.append(("get", remote, str(local)))
        local.write_bytes(self.remote[remote])

    def release(self, holder, timeout=None):
        self.calls.append(("release", holder))


def _prepared(tmp_path):
    df0 = tmp_path / "boot.adf"
    published = tmp_path / "SECRETSAVE-published.adf"
    working = tmp_path / "SECRETSAVE-working.adf"
    _disk(df0, "Secret 1")
    _disk(published, "SECRETSAVE", "A")
    working.write_bytes(published.read_bytes())
    manifest = tmp_path / "prepare.json"
    manifest.write_text(json.dumps({
        "df0": {"path": str(df0), "sha256": _sha(df0)},
        "published_df1": {"path": str(published), "sha256": _sha(published)},
        "working_df1": {"path": str(working), "sha256": _sha(working)},
    }))
    return manifest


def _audio_proof(tmp_path):
    proof = tmp_path / "mute.json"
    proof.write_text(json.dumps({
        "vm": "WIN11-DEV", "muted": True,
        "method": "Windows Core Audio endpoint mute readback",
        "endpoint_id": "synthetic-endpoint", "readback": True,
        "observed_utc": datetime.now(timezone.utc).isoformat(),
    }))
    return proof


def test_exact_df1_is_preserved_and_failed_save_is_fetched(tmp_path):
    df0 = tmp_path / "boot.adf"
    published = tmp_path / "SECRETSAVE-published.adf"
    working = tmp_path / "SECRETSAVE-working.adf"
    _disk(df0, "Secret 1")
    _disk(published, "SECRETSAVE", "A")
    working.write_bytes(published.read_bytes())
    original_df0 = _sha(df0)
    original_df1 = _sha(published)
    manifest = tmp_path / "prepare.json"
    manifest.write_text(json.dumps({
        "df0": {"path": str(df0), "sha256": original_df0},
        "published_df1": {"path": str(published), "sha256": original_df1},
        "working_df1": {"path": str(working), "sha256": original_df1},
    }))
    guest = FailedPostWriteGuest()

    result = amigasecretsave.run_recon(
        manifest, guest=guest, guard=lambda state, shot: True,
        holder="wish672-test", audio_proof=_audio_proof(tmp_path),
    )

    assert result["success"] is False
    assert "save prompt after B" in result["error"]
    assert _sha(published) == original_df1
    assert _sha(working) == original_df1
    assert _sha(df0) == original_df0
    attempt = tmp_path / "recon1"
    assert (attempt / "fetched-df0.adf").read_bytes() == df0.read_bytes()
    fetched_df1 = AmigaDisk.open(attempt / "fetched-df1.adf")
    assert fetched_df1.read_file("/SAVE/savgamA.sav") == b"composed save"
    assert fetched_df1.read_file("/SAVE/savgamB.sav") == b"engine wrote B"
    assert (attempt / "shots" / "failure.raw.png").read_bytes()
    assert (attempt / "shots" / "failure.png").read_bytes()
    starts = [call for call in guest.calls if call[0] == "start"]
    assert len(starts) == 1
    assert starts[0][1] == "wish672-test"
    assert starts[0][2].endswith("-df0.adf")
    assert starts[0][3].endswith("-df1.adf")
    assert starts[0][2] != starts[0][3]
    assert [call for call in guest.calls if call[0] in ("stop", "release")] == [
        ("stop", "wish672-test"), ("release", "wish672-test"),
    ]


def test_unverified_mute_refuses_before_claim_or_boot(tmp_path):
    guest = FailedPostWriteGuest()

    with pytest.raises(amigasecretsave.RouteError, match="audio mute"):
        amigasecretsave.run_recon(
            tmp_path / "missing-manifest.json", guest=guest,
            guard=lambda state, shot: True, holder="wish672-test",
            audio_proof=tmp_path / "missing-mute.json",
        )

    assert guest.calls == []
    assert not (tmp_path / "recon1").exists()


def test_existing_same_holder_claim_never_touches_the_prior_lane(tmp_path):
    class ExistingClaimGuest(FailedPostWriteGuest):
        def claim(self, holder, timeout=None):
            self.calls.append(("claim", holder))
            return f"ok claimed by {holder} (already yours since 09:14)"

    guest = ExistingClaimGuest()
    result = amigasecretsave.run_recon(
        _prepared(tmp_path), guest=guest, guard=lambda state, shot: True,
        holder="wish672-test", audio_proof=_audio_proof(tmp_path),
    )

    assert result["success"] is False
    assert "already yours" in result["error"]
    assert guest.calls == [("claim", "wish672-test")]
    assert not (tmp_path / "recon1" / "fetched-df0.adf").exists()


def test_stale_or_unmeasured_audio_mute_proof_is_refused(tmp_path):
    proof = tmp_path / "mute.json"
    now = datetime.now(timezone.utc)
    measured = {
        "vm": "WIN11-DEV", "muted": True,
        "method": "Windows Core Audio endpoint mute readback",
        "endpoint_id": "synthetic-endpoint", "readback": True,
        "observed_utc": (now - timedelta(hours=1)).isoformat(),
    }
    proof.write_text(json.dumps(measured))
    assert not amigasecretsave._mute_proof(proof)

    measured["observed_utc"] = "yesterday"
    proof.write_text(json.dumps(measured))
    assert not amigasecretsave._mute_proof(proof)

    measured["observed_utc"] = now.isoformat()
    measured["readback"] = False
    proof.write_text(json.dumps(measured))
    assert not amigasecretsave._mute_proof(proof)

    measured["readback"] = True
    proof.write_text(json.dumps(measured))
    assert amigasecretsave._mute_proof(proof)


def test_mute_proof_expiring_during_transfer_refuses_before_start(
        tmp_path, monkeypatch):
    class ClockedDateTime:
        now_utc = datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz):
            return cls.now_utc.astimezone(tz)

        @staticmethod
        def fromisoformat(value):
            return datetime.fromisoformat(value)

    proof = tmp_path / "mute.json"
    proof.write_text(json.dumps({
        "vm": "WIN11-DEV", "muted": True,
        "method": "Windows Core Audio endpoint mute readback",
        "endpoint_id": "synthetic-endpoint", "readback": True,
        "observed_utc": (ClockedDateTime.now_utc
                         - timedelta(minutes=4, seconds=59)).isoformat(),
    }))
    monkeypatch.setattr(amigasecretsave, "datetime", ClockedDateTime)

    class TransferOutlivesProof(FailedPostWriteGuest):
        def put(self, local, remote, timeout=None):
            super().put(local, remote, timeout=timeout)
            if len([call for call in self.calls if call[0] == "put"]) == 1:
                ClockedDateTime.now_utc += timedelta(seconds=2)

    guest = TransferOutlivesProof()
    monkeypatch.setattr(amigasecretsave, "WinGuest", lambda: guest)
    monkeypatch.setattr(amigasecretsave, "PixelGuards", lambda path: lambda state, shot: True)
    manifest = _prepared(tmp_path)

    assert amigasecretsave.main([
        "recon", "--manifest", str(manifest), "--guards", str(tmp_path / "guards.json"),
        "--audio-proof", str(proof), "--holder", "wish672-test",
    ]) == 1

    summary = json.loads((tmp_path / "recon1" / "summary.json").read_text())
    assert summary["success"] is False
    assert "audio mute proof expired" in summary["error"]
    assert [call[0] for call in guest.calls] == [
        "claim", "put", "put", "get", "get", "release",
    ]
    assert set(summary["fetched"]) == {"df0", "df1"}


def test_deadline_stops_before_boot_when_transfer_exhausts_route_time(
        tmp_path, monkeypatch):
    class Clock:
        now = 100.0

        def monotonic(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(amigasecretsave.time, "monotonic", clock.monotonic)

    class SlowTransfer(FailedPostWriteGuest):
        def put(self, local, remote, timeout=None):
            super().put(local, remote, timeout=timeout)
            clock.now += 50

    guest = SlowTransfer()
    result = amigasecretsave.run_recon(
        _prepared(tmp_path), guest=guest, guard=lambda state, shot: True,
        holder="wish672-test", audio_proof=_audio_proof(tmp_path),
        deadline_seconds=60,
    )

    assert result["success"] is False
    assert "deadline" in result["error"]
    assert [call[0] for call in guest.calls] == ["claim", "put", "release"]


def test_deadline_bounds_capture_and_cleanup_calls(tmp_path, monkeypatch):
    class Clock:
        now = 100.0

        def monotonic(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(amigasecretsave.time, "monotonic", clock.monotonic)

    class TimedGuest(FailedPostWriteGuest):
        def __init__(self):
            super().__init__()
            self.timeouts = []

        def capture(self, state, raw, cropped, timeout=None):
            self.timeouts.append(("capture", timeout, clock.now))
            super().capture(state, raw, cropped, timeout=timeout)
            clock.now += 2

        def stop(self, holder, timeout=None):
            self.timeouts.append(("stop", timeout, clock.now))
            super().stop(holder, timeout=timeout)
            clock.now += 3

        def get(self, remote, local, timeout=None):
            self.timeouts.append(("get", timeout, clock.now))
            super().get(remote, local, timeout=timeout)
            clock.now += 4

        def release(self, holder, timeout=None):
            self.timeouts.append(("release", timeout, clock.now))
            super().release(holder, timeout=timeout)
            clock.now += 1

    guest = TimedGuest()
    result = amigasecretsave.run_recon(
        _prepared(tmp_path), guest=guest, guard=lambda state, shot: True,
        holder="wish672-test", audio_proof=_audio_proof(tmp_path),
        deadline_seconds=300,
    )

    assert result["success"] is False
    assert [name for name, _, _ in guest.timeouts].count("get") == 2
    assert {name for name, _, _ in guest.timeouts} == {
        "capture", "stop", "get", "release",
    }
    assert all(isinstance(limit, (int, float))
               and 0 < limit <= 300 - (at - 100)
               for _, limit, at in guest.timeouts)
    assert result["elapsed_seconds"] <= 300


def test_accept_and_dependency_control_stay_unavailable():
    assert amigasecretsave.main(["accept"]) == 2
    assert amigasecretsave.main(["spindisk-control"]) == 2
