"""The step-start snapshot and the resume record of `tools/c64/acceptance.py`.

A fake session and pool stand in for VICE: the checks are which files a step
start saves, what `resumerecord.read` finds in the record a failed step
leaves, and that the slot is released before the run exits with
`RESUME_EXIT`.
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import types
from types import SimpleNamespace

import pytest

from goldbox.c64_port import POOL_OF_RADIANCE
from tools.c64 import acceptance as A
from tools.registry import resumerecord, specimens

REAL_POOL_RUN = A.PoolRun   # `drive` replaces `A.PoolRun` with a fake
FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


def _fixture_disk(tmp_path: pathlib.Path) -> pathlib.Path:
    from goldbox import dos_codec
    from goldbox.savegame import SaveGame0, SaveGame1

    payload = SaveGame0.from_prg((FIXTURES / "savedgame0.bin").read_bytes()).to_bytes()
    save1 = SaveGame1.from_prg((FIXTURES / "savedgame1.bin").read_bytes()).to_bytes()
    path = tmp_path / "fixture-source.d64"
    path.write_bytes(dos_codec.save_disk(payload, save1, POOL_OF_RADIANCE).to_bytes())
    return path


class _Slot:
    n, display = 1, ":99"

    def __init__(self, tmp_path, events):
        self.dir = tmp_path / "slot"
        self.dir.mkdir()
        (self.dir / "vicerc").write_text("rc", encoding="utf-8")
        self.vicerc = self.dir / "vicerc"
        self.torn = False
        self.events = events
        self.record_at_teardown = None
        self.out = None

    def teardown(self):
        self.torn = True
        self.events.append("teardown")
        self.record_at_teardown = (self.out / "resume" / "resume.json").is_file()


class _Sess:
    """Writes a snapshot file whose bytes name the call, so a copy can be told apart.

    Writes the game makes to the attached disk reach its host file only when
    `attach` is called, as VICE writes a changed track back on detach.
    """

    snapshot_error_at = None
    terminate_error = False

    def __init__(self, first, slot=None):
        self.slot = slot
        self.save_disk = str(slot.dir / "SIDE0.D64")
        self.attached = str(slot.dir / "SIDE3.D64")
        pathlib.Path(self.attached).write_bytes(b"side three")
        self.snapshots = 0
        self.events = slot.events
        self.pending = b""

    def watching_dialogs(self):
        return contextlib.nullcontext()

    def terminate(self):
        if self.terminate_error:
            raise RuntimeError("terminate failed")

    def attach(self, path):
        self.events.append("attach")
        with open(path, "ab") as host:
            host.write(self.pending)
        self.pending = b""

    def snapshot_path(self, name):
        return str(self.slot.dir / "snapshots" / f"{name}.vsf")

    def snapshot(self, name):
        self.events.append(f"snapshot {name}")
        self.snapshots += 1
        if self.snapshots == self.snapshot_error_at:
            raise OSError("monitor gone")
        path = pathlib.Path(self.snapshot_path(name))
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(f"vsf {name} {self.snapshots}".encode())
        for suffix, text in ((".attached", self.attached), (".pokes", "0"), (".gates", "{}")):
            pathlib.Path(str(path) + suffix).write_text(text, encoding="utf-8")
        return str(path)


class _Pool:
    def __init__(self, sess, log, out, game, points):
        self.sess, self.out, self.shots, self.count = sess, out, 0, 0
        self.events = sess.events

    def _step(self, name):
        self.events.append(name)
        self.count += 1
        return {}

    def resume_state(self):
        return {"done": self.count}

    def capture(self, tag):
        self.shots += 1
        (self.out / f"{self.shots:02d}-{tag}.png").write_bytes(b"png")
        (self.out / f"{self.shots:02d}-{tag}.txt").write_text("rows\n", encoding="utf-8")

    def load(self):
        return self._step("load")

    def peek(self, arg):
        with open(self.sess.save_disk, "ab") as disk:
            disk.write(b"+")
        self.sess.pending += b"+"
        return self._step("peek")

    def snapshot(self, name):
        self.sess.snapshot(name)
        return self._step("snapshot")

    def items(self, who):
        if who == "NOBODY":
            # The failing step changes both disks before it raises.
            with open(self.sess.save_disk, "ab") as disk:
                disk.write(b"!")
            self.sess.pending += b"!"
            self.sess.attach(self.sess.attached)
            self.capture("lost-items")
            raise A.StepFailed("NOBODY is not in the party")
        return self._step("items")

    def reading(self):
        return {}


@pytest.fixture
def drive(tmp_path, monkeypatch):
    events = []

    def go(steps, *, checkpoint=(), sess=_Sess):
        slot = _Slot(tmp_path, events)
        out = tmp_path / "out"
        slot.out = out
        monkeypatch.setattr(A.runlog, "catch_signals", lambda: None)
        monkeypatch.setattr(A.S, "claim_slot", lambda *a, **k: slot)
        monkeypatch.setattr(A.S, "stage_disks", lambda *a, **k: "first")
        monkeypatch.setattr(A.S, "stage_writable",
                            lambda src, dest: __import__("shutil").copyfile(src, dest))
        monkeypatch.setattr(A.S, "Session", sess)
        monkeypatch.setattr(A, "PoolRun", _Pool)
        monkeypatch.setattr(A, "vice_version", lambda: "3.9")
        args = types.SimpleNamespace(
            title="pool", stage_row=[], stage_trait=[], stage_item=[], stage_only=False,
            checkpoint=list(checkpoint), pool=None, issue="i", run="r", disks=None,
            walk="I", walk_steps=1, max_seconds=1e9, read_at=[], no_encounters=False)
        rc = A.run(args, A.parse_steps(steps), out, _fixture_disk(tmp_path))
        return rc, slot, out, events

    return go


def _summary(out):
    return json.loads((out / "summary.json").read_text(encoding="utf-8"))


def test_a_snapshot_is_taken_at_each_step_start_after_the_load(drive):
    rc, _, out, events = drive(["load", "peek 1000 1", "peek 1000 1"])
    assert rc == 0
    assert events == ["load", "attach", "snapshot resume-step", "peek",
                      "attach", "snapshot resume-step", "peek", "teardown"]


def test_a_normal_run_leaves_no_record(drive):
    rc, _, out, _ = drive(["load", "peek 1000 1"])
    assert rc == 0 and not (out / "resume").exists()
    assert _summary(out)["resume"]["record"] is None


def test_a_failed_step_writes_a_record_that_read_accepts(drive):
    rc, slot, out, events = drive(["load", "peek 1000 1", "items NOBODY", "peek 1000 1"])
    assert rc == resumerecord.RESUME_EXIT == 3
    record = resumerecord.read(out / "resume" / "resume.json", "c64")
    assert record["step"] == {"n": 3, "text": "items NOBODY"}
    assert record["sent"] == ["load", "peek 1000 1"]
    assert record["command"] == "steps" and "holder" not in record
    assert [r["step"] for r in record["results"]] == ["load", "peek 1000 1"]
    assert record["run_state"] == {"done": 2}
    assert record["options"]["no_encounters"] is False
    assert record["vice"] == {"version": "3.9", "vicerc_sha256": specimens.sha256_file(slot.vicerc)}
    assert record["error"] == "StepFailed: NOBODY is not in the party"
    assert (out / "resume" / "screen.png").read_bytes() == b"png"
    assert record["screen"]["file"] == "screen.png"
    assert _summary(out)["resume"]["record"] == str(out / "resume" / "resume.json")


def test_the_record_holds_the_machine_and_disks_as_step_three_began(drive):
    _, _, out, _ = drive(["load", "peek 1000 1", "items NOBODY"])
    record = resumerecord.read(out / "resume" / "resume.json", "c64")
    folder = out / "resume"
    # The second snapshot, taken as step 3 began.
    assert (folder / record["machine"]["file"]).read_bytes() == b"vsf resume-step 2"
    assert [pathlib.Path(s["file"]).name for s in record["machine"]["sidecars"]] == [
        "step.vsf.attached", "step.vsf.pokes", "step.vsf.gates"]
    # `peek` wrote "+" to the attached disk, which only the attach before the
    # snapshot put on the host file; the failing step's "!" is in neither copy.
    assert (folder / record["machine"]["attached"]["file"]).read_bytes() == b"side three+"
    save = (folder / record["disks"]["save"]["file"]).read_bytes()
    assert save == (out / "staged.D64").read_bytes() + b"+"
    assert b"!" not in (folder / record["machine"]["attached"]["file"]).read_bytes()
    assert record["disks"]["staged"]["sha256"] == specimens.sha256_file(out / "staged.D64")
    assert list(record["disks"]["sides"]) == ["SIDE3.D64"]
    assert record["disks"]["source"]["sha256"] == specimens.sha256_file(
        out.parent / "fixture-source.d64")


def test_the_slot_is_released_after_the_record_is_written(drive):
    rc, slot, _, events = drive(["load", "items NOBODY"])
    assert rc == 3 and slot.torn and slot.record_at_teardown
    assert events[-1] == "teardown"


def test_a_failure_in_the_load_writes_no_record(drive, monkeypatch):
    def broken(self):
        raise A.StepFailed("the game did not load the save")

    monkeypatch.setattr(_Pool, "load", broken)
    rc, slot, out, _ = drive(["load", "peek 1000 1"])
    assert rc == 1 and slot.torn and not (out / "resume").exists()


def test_an_error_that_is_not_a_step_failure_writes_no_record(drive, monkeypatch):
    def broken(self, who):
        raise RuntimeError("monitor gone")

    monkeypatch.setattr(_Pool, "items", broken)
    rc, _, out, _ = drive(["load", "items NOBODY"])
    assert rc == 1 and not (out / "resume").exists()


def test_a_named_snapshot_still_live_is_kept_with_its_sidecars(drive):
    _, _, out, _ = drive(["load", "snapshot a", "peek 1000 1", "items NOBODY"])
    record = resumerecord.read(out / "resume" / "resume.json", "c64")
    assert [n["name"] for n in record["named"]] == ["a"]
    folder = out / "resume"
    assert (folder / record["named"][0]["file"]).read_bytes() == b"vsf a 2"
    assert len(record["named"][0]["sidecars"]) == 3


def test_a_checkpoint_run_takes_no_snapshot_and_says_why(drive):
    rc, _, out, events = drive(["load", "peek 1000 1", "items NOBODY"],
                               checkpoint=["408F=x"])
    assert rc == 1 and "snapshot resume-step" not in events
    assert _summary(out)["resume"] == {"snapshots": False, "why_not": "--checkpoint",
                                       "record": None}
    assert not (out / "resume").exists()


@pytest.mark.parametrize("flag, name", [
    ("read_at", "--read-at"), ("checkpoint", "--checkpoint"),
    ("capture_ready", "--capture-ready"), ("preserve_specimen", "--preserve-specimen"),
    ("attack_by", "--attack-by"), ("fast_flee", "--fast-flee")])
def test_each_option_a_snapshot_cannot_carry_is_named(flag, name):
    args = SimpleNamespace(**{flag: ["x"] if flag in ("read_at", "checkpoint") else "BRUTUS"})
    assert A.resume_blocker(args, A.parse_steps(["load"])) == name
    assert A.resume_blocker(SimpleNamespace(), A.parse_steps(["load"])) is None


def test_temple_mode_is_named_as_blocking():
    steps = A.parse_steps(["load", "temple-probe BRUTUS"])
    assert A.resume_blocker(SimpleNamespace(), steps) == "temple-probe"


def test_a_snapshot_that_fails_is_reported_and_the_run_goes_on_without_a_record(drive):
    class Failing(_Sess):
        snapshot_error_at = 2

    rc, _, out, events = drive(["load", "peek 1000 1", "items NOBODY"], sess=Failing)
    assert rc == 1 and not (out / "resume").exists()
    assert "step-start snapshot failed at step 3" in _summary(out)["resume"]["why_not"]
    assert events.count("snapshot resume-step") == 2   # none after the first failure


@pytest.mark.parametrize("steps", [["load", "snapshot resume-step"],
                                   ["load", "snapshot a", "restore resume-step"]])
def test_the_driver_snapshot_name_is_not_a_step_name(steps):
    with pytest.raises(ValueError, match="step-start snapshot"):
        A.parse_steps(steps)


def test_the_pool_run_state_round_trips_and_keeps_the_summary_list():
    def pool():
        return A.PoolRun(SimpleNamespace(), SimpleNamespace(emit=lambda *a, **k: None),
                         pathlib.Path("."), POOL_OF_RADIANCE, {})

    first = pool()
    first.removes, first.scribing, first.shots = 2, True, 9
    first.scribe_square = [3, 4, 0]
    first.directory = [{"name": "A"}]
    first.gate_reports = [{"verified": True}]
    state = first.resume_state()
    assert json.loads(json.dumps(state)) == state
    second = pool()
    reports = second.gate_reports = []
    second.adopt_resume_state(state)
    assert (second.removes, second.scribing, second.shots) == (2, True, 9)
    assert second.scribe_square == [3, 4, 0] and second.directory == [{"name": "A"}]
    assert second.gate_reports is reports and reports == [{"verified": True}]


def test_curse_and_silver_blades_save_what_pool_saves_and_more():
    assert set(A.PoolRun.RESUME_ATTRS) < set(A.CurseRun.RESUME_ATTRS)
    assert set(A.CurseRun.RESUME_ATTRS) < set(A.SilverRun.RESUME_ATTRS)
    assert "first_bar_done" in A.CurseRun.RESUME_ATTRS


def test_a_state_value_json_would_change_stops_the_snapshot_and_is_named(drive, monkeypatch):
    monkeypatch.setattr(_Pool, "resume_state", lambda self: REAL_POOL_RUN.resume_state(
        SimpleNamespace(RESUME_ATTRS=("scribe_square",), scribe_square=(3, 4),
                        gate_reports=None)))
    rc, _, out, _ = drive(["load", "peek 1000 1", "items NOBODY"])
    assert rc == 1 and not (out / "resume").exists()
    assert "scribe_square does not survive a JSON round trip" in _summary(out)["resume"]["why_not"]


def test_every_saved_attribute_round_trips_exactly():
    values = {"at_menu": False, "directory": [{"name": "A", "size": 3}], "removes": 2,
              "scribing": True, "scribe_square": [3, 4, 0], "mercy_before": 7,
              "lost_reading": {"step": "fight", "after": {"counts": {"a": 1}}},
              "returns_sent": 1, "flee_escaped": None, "shots": 9,
              "first_bar_done": True, "attack_evidence": {"row": [25, 1, 2]},
              "quit_evidence": None, "first_effect_loss": {"phase": "x", "last_present": [1, 2]},
              "last_effect_row": [1, 2], "_saving_is_proof": False, "gen_reads": 3}
    assert set(values) == set(A.SilverRun.RESUME_ATTRS)
    holder = SimpleNamespace(RESUME_ATTRS=A.SilverRun.RESUME_ATTRS, gate_reports=[{"verified": True}],
                             **values)
    state = A.PoolRun.resume_state(holder)
    assert json.loads(json.dumps(state)) == state
    assert {k: state[k] for k in values} == values


def test_a_cleanup_error_still_removes_the_snapshot_folder(drive, tmp_path):
    class Broken(_Sess):
        terminate_error = True

    with pytest.raises(RuntimeError, match="terminate failed"):
        drive(["load", "peek 1000 1"], sess=Broken)
    assert (tmp_path / "out" / "summary.json").is_file()
    assert not (tmp_path / "out" / "resume").exists()
