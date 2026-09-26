"""`tools/amiga/amigadrivecheck.py`, the floppy-change probe, against a fake guest and pipe.

Nothing here starts an emulator: the guest and the pipe are stand-ins that keep two
drives, so what is tested is the probe's own step order, its controls, its refusals
before the lane is touched, and its cleanup. What the real binary answers is what
the probe measures when it is run.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import pytest

from automap import amiga
from tools.amiga import amigadrivecheck as check
from tools.amiga.amigasecretsave import RouteError, sha256

HOLDER = "wish679-0123456789ab"


def write_proof(path: pathlib.Path, age_seconds: float = 0) -> pathlib.Path:
    observed = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - age_seconds,
                                      timezone.utc)
    path.write_text(json.dumps({
        "vm": "WIN11-DEV", "muted": True, "readback": True,
        "method": "Windows Core Audio endpoint mute readback",
        "endpoint_id": "{0.0.0.00000000}.{abc}",
        "observed_utc": observed.isoformat().replace("+00:00", "Z")}))
    return path


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Receipt:
    def __init__(self, paths, modes=("rw", "rw"), already=False, labels=("q0", "q1", "dbg")):
        self.paths, self.modes, self.already = dict(paths), modes, already
        self.labels = labels

    def drive_state(self):
        return {"paths": dict(self.paths), "modes": {0: self.modes[0], 1: self.modes[1]}}

    def as_dict(self):
        return {"replies": [{"label": label} for label in self.labels], "already": self.already}


class FakeGuest:
    """A guest with a lane, a disks folder and two drives."""

    def __init__(self, clock, script_sha):
        self.clock = clock
        self.script_sha = script_sha
        self.calls: list[tuple] = []
        self.staged: set[str] = set()
        self.remote: dict[str, bytes] = {}
        self.drives = {0: None, 1: None}
        self.fail: dict[str, Exception] = {}
        self.setters: list[tuple] = []

    def _do(self, name, *info):
        self.calls.append((name, *info))
        if name in self.fail:
            raise self.fail[name]

    def deployed(self, timeout):
        self._do("deployed")
        return {"winuae64_sha256": "F3E5", "winuae64_version": "6.0.3.0",
                "winuae_ps1_sha256": self.script_sha.upper()}

    def claim(self, holder, timeout):
        self._do("claim", holder)
        return f"ok claimed by {holder}"

    def put(self, local, remote, timeout):
        self._do("put", remote)
        self.remote[remote] = pathlib.Path(local).read_bytes()
        self.staged.add(remote.replace("/", "\\"))
        return "ok"

    def start(self, holder, *drives, timeout, options=()):
        self._do("start", *drives)
        self.drives = {0: drives[0].replace("/", "\\"), 1: drives[1].replace("/", "\\")}
        return "ok pid=1 session=1"

    def stop(self, holder, timeout):
        self._do("stop")
        return "ok stopped"

    def get(self, remote, local, timeout):
        self._do("get", remote)
        pathlib.Path(local).write_bytes(self.remote[remote])
        return "ok"

    def release(self, holder, timeout):
        self._do("release")
        return f"ok released by {holder}"

    def lane_is_free(self, timeout):
        self._do("lane")
        return "free"


class FakePipe:
    def __init__(self, guest, timeout):
        self.guest = guest

    def drives(self, holder):
        self.guest._do("drives")
        return Receipt(self.guest.drives)

    def insert_floppy(self, drive, path, holder, sha, token=None, staged=None):
        amiga.refuse_floppy_change(drive, path, holder, sha)
        if staged is not None and path not in staged:
            raise ValueError(f"Floppy path {path!r} is not a disk this run staged for {holder}")
        self.guest._do("insert", drive, path)
        if self.guest.drives[drive] == path:
            return Receipt(self.guest.drives, already=True, labels=("q0", "q1", "dbg"))
        self.guest.setters.append((drive, path))
        self.guest.drives[drive] = path
        return Receipt(self.guest.drives, labels=("q0", "q1", "dbg", "set"))

    def lane_verb(self, verb, holder, token, args):
        self.guest._do("lane_verb", holder, args[1])
        if holder != HOLDER:
            raise amiga.FloppyError(f"The guest refused the floppy change: the WinUAE lane is "
                                    f"claimed by {HOLDER} since t, not by {holder}")
        if "intruder" in args[1]:
            raise amiga.FloppyError(f"The guest refused the floppy change: {args[1]} is not "
                                    f"staged for {holder}")
        raise amiga.FloppyError(f"The guest refused the floppy change: {args[1]} does not exist")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def proof(tmp_path):
    return write_proof(tmp_path / "audio.json")


def run(tmp_path, clock, proof, *, guest=None, script_sha=None, pipe=FakePipe, run_dir=None):
    script_sha = script_sha or sha256(check.REPO_SCRIPT)
    guest = guest or FakeGuest(clock, script_sha)
    result = check.run_drivecheck(
        guest=guest, run_dir=run_dir or tmp_path / "run", holder=HOLDER, audio_proof=proof,
        pipe_factory=lambda timeout: pipe(guest, timeout), clock=clock, sleep=clock.sleep, argv=["--x"])
    return guest, result


def names(result):
    return [s["step"] for s in result["steps"]]


def test_the_probe_runs_its_steps_in_order_and_passes(tmp_path, clock, proof):
    guest, result = run(tmp_path, clock, proof)
    assert result["passed"] is True and result["error"] == ""
    assert names(result) == [
        "claim", "stage", "start", "ready", "baseline",
        "swap DF0 to B", "swap DF0 to B: readback",
        "restore DF0 to A", "restore DF0 to A: readback",
        "control: another holder's claim", "control: another holder's claim leaves both drives",
        "control: another holder's path, refused in Python",
        "control: another holder's path, refused in the guest",
        "control: another holder's path leaves both drives",
        "control: a file never staged, refused in Python",
        "control: a file never staged, refused in the guest",
        "control: a file never staged leaves both drives",
        "control: the same path twice", "control: the same path leaves both drives"]
    assert {s["verdict"] for s in result["steps"]} == {"pass"}
    assert [(d, p.rsplit("-", 1)[1]) for d, p in guest.setters] == [(0, "probeB.adf"), (0, "probeA.adf")]
    assert guest.drives[1].endswith("probeC.adf")


def test_the_emulator_starts_with_a_in_df0_and_c_in_df1(tmp_path, clock, proof):
    guest, _ = run(tmp_path, clock, proof)
    start = next(c for c in guest.calls if c[0] == "start")
    assert [p.rsplit("-", 1)[1] for p in start[1:]] == ["probeA.adf", "probeC.adf"]


def test_the_probe_writes_its_run_log_and_summary(tmp_path, clock, proof):
    _, result = run(tmp_path, clock, proof)
    summary = json.loads((tmp_path / "run" / "summary.json").read_text())
    assert summary["passed"] is True and summary["holder"] == HOLDER
    assert summary["deployed"]["winuae64_version"] == "6.0.3.0"
    assert summary["deployed"]["winuae_ps1_sha256"].lower() == summary["repository_winuae_ps1_sha256"]
    events = [json.loads(line) for line in (tmp_path / "run" / "run.jsonl").read_text().splitlines()]
    assert events[0]["event"] == "step" and events[0]["step"] == "claim"
    assert [e["event"] for e in events][-5:] == ["stop", "fetch", "fetch", "fetch", "release"]
    assert all("t" in e for e in events)


def test_the_generated_disks_are_blank_marked_and_distinct(tmp_path, clock, proof):
    _, result = run(tmp_path, clock, proof)
    seen = set()
    for key in "ABC":
        data = pathlib.Path(result["generated"][key]["path"]).read_bytes()
        assert len(data) == 901120
        assert data[0x400:0x400 + 12] == f"WISH PROBE {key}".encode()
        assert not any(data[:0x400]) and not any(data[0x40C:])
        seen.add(result["generated"][key]["sha256"])
    assert len(seen) == 3


def test_every_staged_disk_is_fetched_and_hashed_after_the_run(tmp_path, clock, proof):
    guest, result = run(tmp_path, clock, proof)
    assert result["unchanged"] == {"A": True, "B": True, "C": True}
    order = [c[0] for c in guest.calls]
    assert order[-6:] == ["stop", "get", "get", "get", "release", "lane"]
    assert result["cleaned_up"] is True and result["lane"] == "free"


def test_a_stale_audio_proof_refuses_before_the_guest_is_touched(tmp_path, clock):
    guest = FakeGuest(clock, sha256(check.REPO_SCRIPT))
    with pytest.raises(RouteError, match="audio mute has not been verified"):
        run(tmp_path, clock, write_proof(tmp_path / "old.json", age_seconds=600), guest=guest)
    assert guest.calls == [] and not (tmp_path / "run").exists()


def test_a_missing_audio_proof_refuses_before_the_guest_is_touched(tmp_path, clock):
    guest = FakeGuest(clock, sha256(check.REPO_SCRIPT))
    with pytest.raises(RouteError, match="audio mute has not been verified"):
        run(tmp_path, clock, tmp_path / "absent.json", guest=guest)
    assert guest.calls == []


def test_an_audio_proof_that_expires_before_the_start_stops_the_run_and_cleans_up(
        tmp_path, clock, proof, monkeypatch):
    calls = iter([True, False])
    monkeypatch.setattr(check, "_mute_proof", lambda path: next(calls))
    guest, result = run(tmp_path, clock, proof)
    assert result["passed"] is False and "proof expired before WinUAE start" in result["error"]
    order = [c[0] for c in guest.calls]
    assert "start" not in order and "release" in order and order.count("get") == 3


def test_a_deployed_lane_script_that_differs_from_this_one_refuses_before_a_claim(tmp_path, clock, proof):
    guest = FakeGuest(clock, "0" * 64)
    with pytest.raises(RouteError, match="not this repository's"):
        run(tmp_path, clock, proof, guest=guest)
    assert [c[0] for c in guest.calls] == ["deployed"]


def test_an_existing_run_directory_is_refused(tmp_path, clock, proof):
    (tmp_path / "run").mkdir()
    with pytest.raises(RouteError, match="already exists"):
        run(tmp_path, clock, proof)


def test_a_failed_change_stops_the_probe_and_still_cleans_up(tmp_path, clock, proof):
    class Failing(FakePipe):
        def insert_floppy(self, drive, path, holder, sha, token=None, staged=None):
            raise amiga.FloppyError("DF0 never took it")

    guest, result = run(tmp_path, clock, proof, pipe=Failing)
    assert result["passed"] is False and "DF0 never took it" in result["error"]
    assert names(result)[-1] == "stopped"
    order = [c[0] for c in guest.calls]
    assert order[-6:] == ["stop", "get", "get", "get", "release", "lane"]


def test_a_control_that_is_accepted_fails_the_probe(tmp_path, clock, proof):
    class Lax(FakePipe):
        def lane_verb(self, verb, holder, token, args):
            return ("ok", 0.0)

    guest, result = run(tmp_path, clock, proof, pipe=Lax)
    assert result["passed"] is False
    assert "the request was accepted" in result["error"]
    assert result["steps"][-2]["verdict"] == "fail"
    assert "release" in [c[0] for c in guest.calls]


def test_a_control_refused_for_the_wrong_reason_fails_the_probe(tmp_path, clock, proof):
    class Wrong(FakePipe):
        def lane_verb(self, verb, holder, token, args):
            raise amiga.FloppyError("The guest refused the floppy change: something else")

    _, result = run(tmp_path, clock, proof, pipe=Wrong)
    assert result["passed"] is False and "not for the expected reason" in result["error"]


def test_df1_changing_during_a_step_fails_the_probe(tmp_path, clock, proof):
    class Meddling(FakePipe):
        def insert_floppy(self, drive, path, holder, sha, token=None, staged=None):
            receipt = super().insert_floppy(drive, path, holder, sha, token, staged)
            self.guest.drives[1] = path
            return receipt

    _, result = run(tmp_path, clock, proof, pipe=Meddling)
    assert result["passed"] is False and "the drives are not as expected" in result["error"]
    assert result["steps"][-2]["step"] == "swap DF0 to B: readback"


def test_a_refused_control_leaves_both_drives_checked(tmp_path, clock, proof):
    class Disturbing(FakePipe):
        def lane_verb(self, verb, holder, token, args):
            self.guest.drives[0] = "C:\\Amiga\\Disks\\somewhere-else.adf"
            return super().lane_verb(verb, holder, token, args)

    _, result = run(tmp_path, clock, proof, pipe=Disturbing)
    assert result["passed"] is False
    assert names(result)[-1] == "stopped"
    assert "control: another holder's claim leaves both drives" in names(result)


def test_the_same_path_twice_must_send_no_setter(tmp_path, clock, proof):
    class Resending(FakePipe):
        def insert_floppy(self, drive, path, holder, sha, token=None, staged=None):
            receipt = super().insert_floppy(drive, path, holder, sha, token, staged)
            if receipt.already:
                receipt.labels = ("q0", "q1", "dbg", "set")
            return receipt

    _, result = run(tmp_path, clock, proof, pipe=Resending)
    assert result["passed"] is False
    assert "sent a setter or was not reported" in result["error"]


def test_a_pipe_that_never_answers_ends_the_run_after_thirty_seconds(tmp_path, clock, proof):
    class Silent(FakePipe):
        def drives(self, holder):
            raise amiga.GuestError("winvm ssh did not answer in 30s")

    guest, result = run(tmp_path, clock, proof, pipe=Silent)
    assert result["passed"] is False and "never answered `drives`" in result["error"]
    assert 28 <= clock.now - 1000 <= 70
    assert "stop" in [c[0] for c in guest.calls]


def test_the_probing_budget_ends_the_run_and_cleanup_still_happens(tmp_path, clock, proof):
    class Slow(FakePipe):
        def insert_floppy(self, *a, **k):
            clock.now += 175
            return super().insert_floppy(*a, **k)

    guest, result = run(tmp_path, clock, proof, pipe=Slow)
    assert result["passed"] is False and "budget" in result["error"]
    assert [c[0] for c in guest.calls][-6:] == ["stop", "get", "get", "get", "release", "lane"]


def test_a_claim_that_is_not_new_ends_the_run_without_starting_or_releasing_anything(tmp_path, clock, proof):
    class Reclaimed(FakeGuest):
        def claim(self, holder, timeout):
            super().claim(holder, timeout)
            return f"ok claimed by {holder} (already yours since t)"

    guest = Reclaimed(clock, sha256(check.REPO_SCRIPT))
    guest_, result = run(tmp_path, clock, proof, guest=guest)
    assert result["passed"] is False and "The claim was not new" in result["error"]
    order = [c[0] for c in guest.calls]
    assert order == ["deployed", "claim"]


def test_a_stop_that_fails_leaves_the_claim_held_and_the_run_failed(tmp_path, clock, proof):
    guest = FakeGuest(clock, sha256(check.REPO_SCRIPT))
    guest.fail["stop"] = RouteError("winvm ssh failed")
    _, result = run(tmp_path, clock, proof, guest=guest)
    assert result["passed"] is False and "stop_error" in result
    assert "release" not in [c[0] for c in guest.calls]
    assert result["cleaned_up"] is False


def test_a_fetched_disk_that_differs_fails_the_run(tmp_path, clock, proof):
    class Scribbling(FakeGuest):
        def get(self, remote, local, timeout):
            super().get(remote, local, timeout)
            if remote.endswith("probeB.adf"):
                pathlib.Path(local).write_bytes(b"changed")

    _, result = run(tmp_path, clock, proof, guest=Scribbling(clock, sha256(check.REPO_SCRIPT)))
    assert result["passed"] is False and result["unchanged"]["B"] is False


def test_a_drive_that_reads_ro_at_the_baseline_fails_the_probe(tmp_path, clock, proof):
    class ReadOnly(FakePipe):
        def drives(self, holder):
            self.guest._do("drives")
            return Receipt(self.guest.drives, modes=("ro", "rw"))

    guest, result = run(tmp_path, clock, proof, pipe=ReadOnly)
    assert result["passed"] is False and "the drives are not as expected" in result["error"]
    assert result["steps"][-2]["step"] == "baseline" and "release" in [c[0] for c in guest.calls]


def test_a_drive_that_reads_ro_after_a_change_fails_the_probe(tmp_path, clock, proof):
    class Empties(FakePipe):
        def drives(self, holder):
            self.guest._do("drives")
            done = any(c[0] == "insert" for c in self.guest.calls)
            return Receipt(self.guest.drives, modes=("ro", "rw") if done else ("rw", "rw"))

    _, result = run(tmp_path, clock, proof, pipe=Empties)
    assert result["passed"] is False
    assert result["steps"][-2]["step"] == "swap DF0 to B: readback"


def test_a_clock_past_the_probing_deadline_raises_and_cleans_up(tmp_path, clock, proof):
    class Late(FakePipe):
        def drives(self, holder):
            clock.now += 181
            return super().drives(holder)

    guest, result = run(tmp_path, clock, proof, pipe=Late)
    assert result["passed"] is False and "probing budget is spent" in result["error"]
    assert [c[0] for c in guest.calls][-6:] == ["stop", "get", "get", "get", "release", "lane"]


def test_less_than_twenty_seconds_left_refuses_a_floppy_change(tmp_path, clock, proof):
    class Nearly(FakePipe):
        def drives(self, holder):
            clock.now += 165
            return super().drives(holder)

    guest, result = run(tmp_path, clock, proof, pipe=Nearly)
    assert result["passed"] is False and "Less than 20 s" in result["error"]
    assert not guest.setters and "release" in [c[0] for c in guest.calls]


def test_the_command_line_needs_an_audio_proof(capsys):
    with pytest.raises(SystemExit):
        check.main([])
    assert "--audio-proof" in capsys.readouterr().err


def test_the_command_line_refuses_a_stale_proof_with_a_capitalised_line(tmp_path, capsys, monkeypatch):
    class Untouchable:
        def __getattr__(self, name):
            pytest.fail(f"touched the guest: {name}")

    monkeypatch.setattr(check, "ProbeGuest", Untouchable)
    assert check.main(["--audio-proof", str(tmp_path / "none.json")]) == 2
    assert capsys.readouterr().err.startswith("Amigadrivecheck: The Windows VM audio mute")


# -- WinGuest.insert, which the driver's insert steps go through -----------------

def test_winguest_insert_keeps_the_raw_replies_of_a_refused_change(monkeypatch):
    from tools.amiga import amigasecretsave as drive

    class Pipe:
        def __init__(self, timeout=None, **kw):
            pass

        def insert_floppy(self, number, path, holder, sha256, staged=None):
            raise amiga.FloppyError("DF0 never took it", {"replies": ["x"]})

    monkeypatch.setattr(amiga, "WinuaePipe", Pipe)
    guest = drive.WinGuest()
    guest.staged.add("C:\\Amiga\\Disks\\wish679-h-disk2.adf")
    with pytest.raises(drive.RouteError, match="never took it") as caught:
        guest.insert("h", 0, "C:/Amiga/Disks/wish679-h-disk2.adf", 30, "ab" * 32)
    assert caught.value.receipt == {"replies": ["x"]}


def test_winguest_insert_refuses_a_disk_it_did_not_stage_before_anything_is_sent():
    from tools.amiga import amigasecretsave as drive

    ran = []
    guest = drive.WinGuest()
    guest._run = lambda *a, **k: ran.append(a)
    with pytest.raises(ValueError, match="is not a disk this run staged for h"):
        guest.insert("h", 0, "C:/Amiga/Disks/wish679-h-disk2.adf", 30, "ab" * 32)
    assert ran == []
