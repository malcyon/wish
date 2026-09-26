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

    def grab(self, state, raw, cropped, timeout=None):
        self.calls.append(("grab", state))
        raw.write_bytes(b"raw " + state.encode())
        cropped.write_bytes(b"crop " + state.encode())
        return True

    def press(self, holder, key, timeout=None):
        self.calls.append(("press", holder, key))
        if key == "B":
            # The game saves to the boot disk whose SAVE drawer it found.
            disk = AmigaDisk(self.remote[self.drives[0]])
            disk.write_file("/SAVE/savgamB.sav", b"engine wrote B")
            self.remote[self.drives[0]] = disk.to_bytes()
            raise RuntimeError("save prompt after B")

    def stop(self, holder, timeout=None):
        self.calls.append(("stop", holder))

    def get(self, remote, local, timeout=None):
        self.calls.append(("get", remote, str(local)))
        local.write_bytes(self.remote[remote])

    def release(self, holder, timeout=None):
        self.calls.append(("release", holder))


def _prepared(tmp_path):
    """A manifest for DF0 (Secret 1 with slots A and C) and DF1 (Secret 2)."""
    df0, df1 = tmp_path / "boot.adf", tmp_path / "disk-b-working.adf"
    published = tmp_path / "SECRETSAVE-published.adf"
    disk_b = tmp_path / "disk-b-source.adf"
    _disk(published, "SECRETSAVE", "A")
    boot = AmigaDisk.blank("Secret 1")
    boot.make_dir("/SAVE")
    boot.write_file("/SAVE/savgamA.sav", b"shipped party")
    boot.write_file("/SAVE/savgamC.sav", b"composed save")
    boot.save(df0)
    _disk(disk_b, "Secret 2")
    df1.write_bytes(disk_b.read_bytes())
    manifest = tmp_path / "prepare.json"
    manifest.write_text(json.dumps({
        "df0": {"path": str(df0), "sha256": _sha(df0)},
        "published_df1": {"path": str(published), "sha256": _sha(published)},
        "disk_b_source": {"path": str(disk_b), "sha256": _sha(disk_b)},
        "df1": {"path": str(df1), "sha256": _sha(df1)},
        "slot_letter": "C",
        "slot_sha256": hashlib.sha256(b"composed save").hexdigest(),
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
    manifest = _prepared(tmp_path)
    df0, df1 = tmp_path / "boot.adf", tmp_path / "disk-b-working.adf"
    published = tmp_path / "SECRETSAVE-published.adf"
    original_df0, original_df1 = _sha(df0), _sha(df1)
    original_published = _sha(published)
    guest = FailedPostWriteGuest()

    result = amigasecretsave.run_recon(
        manifest, guest=guest, guard=lambda state, shot: True,
        holder="wish672-test", audio_proof=_audio_proof(tmp_path),
    )

    assert result["success"] is False
    assert "save prompt after B" in result["error"]
    assert _sha(published) == original_published
    assert _sha(df1) == original_df1
    assert _sha(df0) == original_df0
    attempt = tmp_path / "recon1"
    fetched_df0 = AmigaDisk.open(attempt / "fetched-df0.adf")
    assert fetched_df0.read_file("/SAVE/savgamC.sav") == b"composed save"
    assert fetched_df0.read_file("/SAVE/savgamB.sav") == b"engine wrote B"
    assert (attempt / "fetched-df1.adf").read_bytes() == df1.read_bytes()
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


def test_the_dependency_control_stays_unavailable():
    assert amigasecretsave.main(["spindisk-control"]) == 2


class _Desktop:
    """A fake `winvm shot`: a desktop whose own corner changes on every grab."""

    def __init__(self, monkeypatch, clock, *, client_colours, seconds=6.0,
                 windowless=0):
        self.clock, self.seconds = clock, seconds
        self.colours = list(client_colours)
        self.windowless = windowless
        self.timeouts, self.shots = [], 0
        monkeypatch.setattr(amigasecretsave.WinGuest, "_run",
                            staticmethod(self._run))

    def _run(self, *args, timeout):
        assert args[0] == "shot"
        self.timeouts.append(timeout)
        if timeout < self.seconds:
            raise amigasecretsave.RouteError(
                f"winvm shot exceeded its {timeout:.1f}s limit")
        from PIL import Image
        self.shots += 1
        self.clock.now += self.seconds
        image = Image.new("RGB", (1024, 768), (30, 60, 90))
        # One desktop pixel outside the client and its status bar: a clock.
        image.putpixel((1000, 700), (self.shots % 256, 0, 0))
        if self.shots > self.windowless:
            colour = self.colours[min(self.shots - self.windowless, len(self.colours)) - 1]
            image.paste(colour, (10, 27, 730, 595))
            image.paste((240, 240, 240), (10, 595, 730, 617))
        image.save(args[1])
        return ""


@pytest.fixture
def desktop_clock(monkeypatch):
    class Clock:
        now = 500.0

    clock = Clock()
    monkeypatch.setattr(amigasecretsave.time, "monotonic", lambda: clock.now)

    def sleep(seconds):
        clock.now += seconds

    monkeypatch.setattr(amigasecretsave.time, "sleep", sleep)
    return clock


def test_capture_settles_on_the_emulator_screen_while_the_desktop_changes(
        tmp_path, monkeypatch, desktop_clock):
    from PIL import Image

    desktop = _Desktop(monkeypatch, desktop_clock, client_colours=[(9, 9, 9)])
    raw, cropped = tmp_path / "s.raw.png", tmp_path / "s.png"

    amigasecretsave.WinGuest().capture("boot", raw, cropped, timeout=60)

    assert desktop.shots == 2
    assert Image.open(cropped).size == (720, 568)
    assert Image.open(cropped).getpixel((5, 5)) == (9, 9, 9)


def test_capture_that_never_settles_says_so_without_a_cut_short_shot(
        tmp_path, monkeypatch, desktop_clock):
    desktop = _Desktop(monkeypatch, desktop_clock,
                       client_colours=[(n, 9, 9) for n in range(1, 40)])

    with pytest.raises(amigasecretsave.RouteError, match="did not settle inside 60s"):
        amigasecretsave.WinGuest().capture(
            "boot", tmp_path / "s.raw.png", tmp_path / "s.png", timeout=60)

    assert desktop.shots >= 2
    assert min(desktop.timeouts) >= amigasecretsave.SHOT_SECONDS
    assert (tmp_path / "s.png").exists()


def test_capture_waits_for_the_emulator_window(tmp_path, monkeypatch, desktop_clock):
    desktop = _Desktop(monkeypatch, desktop_clock, client_colours=[(9, 9, 9)],
                       windowless=1)

    amigasecretsave.WinGuest().capture(
        "boot", tmp_path / "s.raw.png", tmp_path / "s.png", timeout=60)

    assert desktop.shots == 3


def test_capture_with_little_time_left_still_takes_one_shot(
        tmp_path, monkeypatch, desktop_clock):
    desktop = _Desktop(monkeypatch, desktop_clock, client_colours=[(9, 9, 9)])

    with pytest.raises(amigasecretsave.RouteError, match="did not settle inside 10s"):
        amigasecretsave.WinGuest().capture(
            "boot", tmp_path / "s.raw.png", tmp_path / "s.png", timeout=10)

    assert desktop.shots == 1
    assert desktop.timeouts == [10]
    assert (tmp_path / "s.png").exists()


def test_capture_with_no_time_left_takes_no_shot(tmp_path, monkeypatch, desktop_clock):
    desktop = _Desktop(monkeypatch, desktop_clock, client_colours=[(9, 9, 9)])

    with pytest.raises(amigasecretsave.RouteError, match="did not settle"):
        amigasecretsave.WinGuest().capture(
            "boot", tmp_path / "s.raw.png", tmp_path / "s.png", timeout=0)

    assert desktop.shots == 0


def test_grab_takes_one_shot_of_a_screen_that_never_holds_still(
        tmp_path, monkeypatch, desktop_clock):
    from PIL import Image

    # The intro's story text changes between every two grabs, as it did on boot 2.
    desktop = _Desktop(monkeypatch, desktop_clock,
                       client_colours=[(n, 9, 9) for n in range(1, 40)])

    made = amigasecretsave.WinGuest().grab(
        "title", tmp_path / "s.raw.png", tmp_path / "s.png", timeout=120)

    assert made is True
    assert desktop.shots == 1
    assert desktop.timeouts == [amigasecretsave.SHOT_SECONDS]
    assert Image.open(tmp_path / "s.png").getpixel((5, 5)) == (1, 9, 9)


def test_grab_without_the_emulator_window_makes_no_crop(
        tmp_path, monkeypatch, desktop_clock):
    desktop = _Desktop(monkeypatch, desktop_clock, client_colours=[(9, 9, 9)],
                       windowless=1)

    made = amigasecretsave.WinGuest().grab(
        "title", tmp_path / "s.raw.png", tmp_path / "s.png", timeout=120)

    assert made is False
    assert desktop.shots == 1
    assert (tmp_path / "s.raw.png").exists() and not (tmp_path / "s.png").exists()


def test_grab_with_no_time_left_takes_no_shot(tmp_path, monkeypatch, desktop_clock):
    desktop = _Desktop(monkeypatch, desktop_clock, client_colours=[(9, 9, 9)])

    with pytest.raises(amigasecretsave.RouteError, match="no time left"):
        amigasecretsave.WinGuest().grab(
            "title", tmp_path / "s.raw.png", tmp_path / "s.png", timeout=0)

    assert desktop.shots == 0


def _manifest_with(tmp_path, mutate):
    path = _prepared(tmp_path)
    manifest = json.loads(path.read_text())
    mutate(manifest, tmp_path)
    path.write_text(json.dumps(manifest))
    return path


def _refused(tmp_path, mutate, match):
    path = _manifest_with(tmp_path, mutate)
    guest = FailedPostWriteGuest()
    with pytest.raises(amigasecretsave.RouteError, match=match):
        amigasecretsave.run_recon(
            path, guest=guest, guard=lambda s, p: True, holder="wish672-test",
            audio_proof=_audio_proof(tmp_path))
    assert guest.calls == []


def test_recon_refuses_a_published_slot_that_differs_from_the_manifest(tmp_path):
    _refused(tmp_path, lambda m, t: m.update(slot_sha256="0" * 64),
             "published slot differs")


def test_recon_refuses_a_boot_disk_slot_that_is_not_the_published_one(tmp_path):
    def mutate(manifest, root):
        boot = AmigaDisk.open(root / "boot.adf")
        boot.write_file("/SAVE/savgamC.sav", b"another save")
        boot.save(root / "boot.adf")
        manifest["df0"]["sha256"] = _sha(root / "boot.adf")

    _refused(tmp_path, mutate, "not Wish's published slot")


def test_recon_refuses_a_working_df1_that_is_not_disk_b(tmp_path):
    def mutate(manifest, root):
        _disk(root / "disk-b-working.adf", "Other")
        manifest["df1"]["sha256"] = _sha(root / "disk-b-working.adf")

    _refused(tmp_path, mutate, "volume 'Secret 2'")


def test_recon_refuses_a_working_df1_that_differs_from_the_registered_disk_b(tmp_path):
    def mutate(manifest, root):
        disk = AmigaDisk.open(root / "disk-b-working.adf")
        disk.make_dir("/EXTRA")
        disk.save(root / "disk-b-working.adf")
        manifest["df1"]["sha256"] = _sha(root / "disk-b-working.adf")

    _refused(tmp_path, mutate, "differs from the registered disk B")


def test_start_opens_no_log_console(monkeypatch):
    sent = []
    guest = amigasecretsave.WinGuest()
    monkeypatch.setattr(guest, "_lane", lambda holder, command, timeout:
                        sent.append(command) or "ok")

    guest.start("h", "C:/A/df0.adf", "C:/A/df1.adf", timeout=60)

    assert "-log" not in sent[0].split()
    assert "floppy0=C:\\A\\df0.adf" in sent[0] and "floppy1=C:\\A\\df1.adf" in sent[0]
