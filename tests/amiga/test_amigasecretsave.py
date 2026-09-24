"""The standalone Amiga save stays exact while a failed reconnaissance keeps evidence."""

from __future__ import annotations

import hashlib
import json

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

    def claim(self, holder):
        self.calls.append(("claim", holder))

    def put(self, local, remote):
        self.calls.append(("put", str(local), remote))
        self.remote[remote] = local.read_bytes()

    def start(self, holder, df0, df1):
        self.calls.append(("start", holder, df0, df1))
        self.drives = (df0, df1)
        return "ok pid=123 session=1"

    def capture(self, state, raw, cropped):
        self.calls.append(("capture", state))
        raw.write_bytes(b"raw " + state.encode())
        cropped.write_bytes(b"crop " + state.encode())

    def press(self, holder, key):
        self.calls.append(("press", holder, key))
        if key == "B":
            disk = AmigaDisk(self.remote[self.drives[1]])
            disk.write_file("/SAVE/savgamB.sav", b"engine wrote B")
            self.remote[self.drives[1]] = disk.to_bytes()
            raise RuntimeError("save prompt after B")

    def stop(self, holder):
        self.calls.append(("stop", holder))

    def get(self, remote, local):
        self.calls.append(("get", remote, str(local)))
        local.write_bytes(self.remote[remote])

    def release(self, holder):
        self.calls.append(("release", holder))


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
        holder="wish672-test", mute_verified=True,
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
            mute_verified=False,
        )

    assert guest.calls == []
    assert not (tmp_path / "recon1").exists()


def test_accept_and_dependency_control_stay_unavailable():
    assert amigasecretsave.main(["accept"]) == 2
    assert amigasecretsave.main(["spindisk-control"]) == 2
