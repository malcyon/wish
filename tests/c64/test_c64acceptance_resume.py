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

    def __init__(self, tmp_path, events, tag=""):
        self.dir = tmp_path / f"slot{tag}"
        self.dir.mkdir()
        self.claimed = False
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

    def adopt_resume_state(self, state):
        self.events.append("adopt")
        self.adopted = state
        self.count = state["done"]

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

    def go(steps, *, checkpoint=(), sess=_Sess, tag="", vice="3.9", digest=None, **more):
        slot = _Slot(tmp_path, events, tag)
        out = tmp_path / f"out{tag}"
        slot.out = out

        def claim(*a, **k):
            slot.claimed = True
            return slot

        monkeypatch.setattr(A.runlog, "catch_signals", lambda: None)
        monkeypatch.setattr(A.S, "claim_slot", claim)
        monkeypatch.setattr(A, "seeded_vicerc_digest", lambda joy=False: digest or A.vicerc_digest(slot.vicerc))
        monkeypatch.setattr(A.S, "stage_disks", lambda *a, **k: "first")
        monkeypatch.setattr(A.S, "stage_writable",
                            lambda src, dest: __import__("shutil").copyfile(src, dest))
        monkeypatch.setattr(A.S, "Session", sess)
        monkeypatch.setattr(A, "PoolRun", _Pool)
        monkeypatch.setattr(A, "vice_version", lambda: vice)
        values = dict(
            title="pool", stage_row=[], stage_trait=[], stage_item=[], stage_only=False,
            checkpoint=list(checkpoint), pool=None, issue="i", run="r", disks=None,
            walk="I", walk_steps=1, max_seconds=1e9, read_at=[], no_encounters=False)
        values.update(more)
        args = types.SimpleNamespace(**values)
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


# --- resuming from a record ------------------------------------------------


class _ResumeSess(_Sess):
    """Adds the two calls a resume makes: `launch` without `boot`, then `restore`."""

    def launch(self):
        self.events.append("launch")

    def restore(self, name):
        self.events.append(f"restore {name}")
        path = pathlib.Path(self.snapshot_path(name))
        self.restored = {"vsf": path.read_bytes(),
                         "attached": pathlib.Path(str(path) + ".attached").read_text(encoding="utf-8")}
        self.attached = self.restored["attached"]


STEPS = ["load", "peek 1000 1", "items NOBODY", "peek 1000 1"]
FIXED = ["load", "peek 1000 1", "items BRUTUS", "peek 1000 1"]


@pytest.fixture
def failed(drive, tmp_path):
    """A first run that fails at step 3, and its record."""
    rc, _, out, _ = drive(STEPS, tag="a")
    assert rc == 3
    return out / "resume" / "resume.json"


def _resume(drive, record, steps=FIXED, at=3, **more):
    return drive(steps, tag="b", sess=_ResumeSess, resume_from=str(record), at_step=at,
                 **more)


def test_a_record_resumes_at_its_step_and_finishes(drive, failed):
    rc, slot, out, events = _resume(drive, failed)
    assert rc == 0 and slot.torn
    assert events[events.index("launch") - 1] != "load"
    after = events[events.index("launch"):]
    assert after[:3] == ["launch", "restore resume-step", "adopt"]
    # Step 3 is run again, then step 4; step 1 and 2 are not.
    assert after[3:] == ["attach", "snapshot resume-step", "items", "attach",
                         "snapshot resume-step", "peek", "teardown"]
    assert events.count("load") == 1            # only the first run's
    summary = _summary(out)
    assert summary["completed"] and [r["step"] for r in summary["results"]] == FIXED
    assert [bool(r.get("resumed")) for r in summary["results"]] == [True, True, False, False]
    assert summary["resumed_from"]["step"] == 3
    assert summary["resumed_from"]["record"] == str(failed)
    assert summary["resumed_from"]["sha256"] == specimens.sha256_file(failed)
    assert summary["resumed_from"]["earlier_summary"] == str(failed.parent.parent / "summary.json")


def test_the_attached_sidecar_is_rewritten_to_the_new_slot(drive, failed, monkeypatch):
    seen = {}
    original = _ResumeSess.restore

    def keep(self, name):
        original(self, name)
        seen.update(self.restored, slot=str(self.slot.dir))

    monkeypatch.setattr(_ResumeSess, "restore", keep)
    old = (failed.parent / "current" / "step.vsf.attached").read_text(encoding="utf-8")
    rc, slot, _, _ = _resume(drive, failed)
    assert rc == 0
    assert "slota" in old and "slotb" not in old
    assert seen["attached"] == str(slot.dir / "SIDE3.D64") == seen["slot"] + "/SIDE3.D64"
    assert seen["vsf"] == b"vsf resume-step 2"          # the step-start machine


def test_the_recorded_disks_replace_the_staged_ones(drive, failed):
    rc, slot, _, _ = _resume(drive, failed)
    assert rc == 0
    # The record's step-start copy had the "+" the first run's step 2 wrote;
    # the new slot's own `side three` did not.  The run then appends more.
    assert (slot.dir / "SIDE3.D64").read_bytes().startswith(b"side three+")
    assert (slot.dir / "SIDE0.D64").read_bytes().startswith(
        (failed.parent.parent / "staged.D64").read_bytes() + b"+")


def test_run_state_is_adopted_before_the_step_runs(drive, failed, monkeypatch):
    adopted = []
    monkeypatch.setattr(_Pool, "adopt_resume_state",
                        lambda self, state: (adopted.append(dict(state)),
                                             self.events.append("adopt")))
    rc, *_ = _resume(drive, failed)
    assert rc == 0 and adopted == [{"done": 2}]


def test_the_kept_results_reach_validate_walks(drive, failed, monkeypatch):
    seen = []
    monkeypatch.setattr(A, "validate_walks", lambda results: seen.append(list(results)))
    rc, *_ = _resume(drive, failed)
    assert rc == 0
    assert [r["step"] for r in seen[0]] == FIXED and seen[0][0]["resumed"]


def test_step_n_may_differ_from_the_failed_run(drive, failed):
    rc, *_ = _resume(drive, failed, steps=["load", "peek 1000 1", "peek 2000 1"])
    assert rc == 0


def test_a_second_failure_leaves_a_record_covering_every_earlier_step(drive, failed):
    rc, _, out, _ = drive(["load", "peek 1000 1", "items BRUTUS", "items NOBODY"], tag="b",
                          sess=_ResumeSess, resume_from=str(failed), at_step=3)
    assert rc == 3
    record = resumerecord.read(out / "resume" / "resume.json", "c64")
    assert record["step"]["n"] == 4
    assert record["sent"] == ["load", "peek 1000 1", "items BRUTUS"]
    assert [r["step"] for r in record["results"]] == record["sent"]
    assert record["results"][0]["resumed"] is True


@pytest.mark.parametrize("what, steps, at, more", [
    ("a step before N changed", ["load", "peek 2000 1", "items BRUTUS"], 3, {}),
    ("a wrong --at-step", FIXED, 4, {}),
    ("--no-encounters differs", FIXED, 3, {"no_encounters": True}),
    ("a --read-at", FIXED, 3, {"read_at": ["09DD=CD782B:2B78:2"]}),
    ("a --checkpoint", FIXED, 3, {"checkpoint": ["408F=x"]}),
    ("steps ending before N", ["load", "peek 1000 1"], 3, {}),
])
def test_a_mismatch_stops_before_a_slot_is_claimed(drive, failed, what, steps, at, more):
    rc, slot, out, events = drive(steps, tag="b", sess=_ResumeSess, resume_from=str(failed),
                                  at_step=at, **more)
    assert rc == 1 and not slot.claimed and not slot.torn, what
    assert "launch" not in events
    assert _summary(out)["lost"].startswith("not resumed: ")


@pytest.mark.parametrize("more, fragment", [
    ({"vice": "3.10"}, "VICE is 3.10"),
    ({"digest": "0" * 64}, "vicerc"),
])
def test_a_changed_emulator_or_configuration_stops_before_the_claim(drive, failed, more, fragment):
    rc, slot, out, _ = _resume(drive, failed, **more)
    assert rc == 1 and not slot.claimed
    assert fragment in _summary(out)["lost"]


def test_another_save_stops_before_the_claim(drive, failed):
    record = json.loads(failed.read_text(encoding="utf-8"))
    record["disks"]["source"]["sha256"] = "0" * 64
    failed.write_text(json.dumps(record), encoding="utf-8")
    rc, slot, out, _ = _resume(drive, failed)
    assert rc == 1 and not slot.claimed
    assert "is not the save the record started from" in _summary(out)["lost"]


def test_a_different_staged_disk_stops_before_the_claim(drive, failed, monkeypatch):
    real = A.stage

    def stage(source, target, *a, **k):
        done = real(source, target, *a, **k)
        with open(target, "ab") as disk:
            disk.write(b"x")
        return done

    monkeypatch.setattr(A, "stage", stage)
    rc, slot, out, _ = _resume(drive, failed)
    assert rc == 1 and not slot.claimed
    assert "staging this save again" in _summary(out)["lost"]


def test_a_changed_record_file_stops_before_the_claim(drive, failed):
    (failed.parent / "current" / "step.vsf").write_bytes(b"x" * 17)
    rc, slot, out, _ = _resume(drive, failed)
    assert rc == 1 and not slot.claimed
    assert "SHA-256" in _summary(out)["lost"]


def test_a_game_side_that_is_not_the_recorded_one_releases_the_slot_before_launch(
        drive, failed):
    class OtherSide(_ResumeSess):
        def __init__(self, first, slot=None):
            super().__init__(first, slot)
            (slot.dir / "SIDE2.D64").write_bytes(b"not the side")

    record = json.loads(failed.read_text(encoding="utf-8"))
    record["disks"]["sides"]["SIDE2.D64"] = "0" * 64
    failed.write_text(json.dumps(record), encoding="utf-8")
    rc, slot, out, events = drive(FIXED, tag="b", sess=OtherSide, resume_from=str(failed),
                                  at_step=3)
    assert rc == 1 and slot.torn and "launch" not in events
    assert "SIDE2.D64" in _summary(out)["lost"]


def test_resume_from_and_at_step_go_together():
    with pytest.raises(SystemExit):
        A.main(["--resume-from", "resume.json"])
    with pytest.raises(SystemExit):
        A.main(["--at-step", "3"])


def test_a_vicerc_digest_ignores_the_slot_ports(tmp_path, monkeypatch):
    template = tmp_path / "template"
    template.write_text("[C64SC]\nWarpMode=0\n", encoding="utf-8")
    monkeypatch.setenv("POR_VICERC_TEMPLATE", str(template))

    def seeded(port, where):
        folder = tmp_path / where
        slot = SimpleNamespace(port=port, text_port=port + 1, dir=folder, vicerc=folder / "vicerc")
        return A.vicerc_digest(A.S.instance.seed_vicerc(slot))

    assert seeded(6510, "one") == seeded(6540, "two") == A.seeded_vicerc_digest()
    first = A.seeded_vicerc_digest()
    template.write_text("[C64SC]\nWarpMode=1\n", encoding="utf-8")
    assert A.seeded_vicerc_digest() != first


def test_the_seeded_digest_after_the_joystick_edit_matches_a_joy_slot(tmp_path, monkeypatch):
    template = tmp_path / "template"
    template.write_text("[C64SC]\nWarpMode=0\n", encoding="utf-8")
    monkeypatch.setenv("POR_VICERC_TEMPLATE", str(template))
    folder = tmp_path / "slot"
    slot = SimpleNamespace(port=6520, text_port=6521, dir=folder, vicerc=folder / "vicerc")
    A.give_joystick(A.S.instance.seed_vicerc(slot))
    made = A.vicerc_digest(slot.vicerc)
    assert A.seeded_vicerc_digest(joy=True) == made
    assert A.seeded_vicerc_digest() != made


def test_port_lines_are_stripped_only_in_the_c64sc_section(tmp_path):
    def digest(text):
        path = tmp_path / "rc"
        path.write_text(text, encoding="utf-8")
        return A.vicerc_digest(path)

    assert digest("[C64SC]\nMonitorServerAddress=1\n") == digest("[C64SC]\nMonitorServerAddress=2\n")
    assert digest("[Other]\nMonitorServerAddress=1\n") != digest("[Other]\nMonitorServerAddress=2\n")


@pytest.mark.parametrize("version", [None, "3.9"])
def test_an_unreadable_vice_version_stops_before_the_claim(drive, tmp_path, version):
    rc, _, out, _ = drive(STEPS, tag="a")
    record = out / "resume" / "resume.json"
    if version is None:                       # the record's side
        data = json.loads(record.read_text(encoding="utf-8"))
        data["vice"]["version"] = None
        record.write_text(json.dumps(data), encoding="utf-8")
    rc, slot, out_b, _ = _resume(drive, record, vice=None if version else "3.9")
    assert rc == 1 and not slot.claimed
    assert "cannot be read" in _summary(out_b)["lost"]


def test_a_side_that_changed_since_the_step_began_is_named(drive, failed):
    class OtherSide(_ResumeSess):
        def __init__(self, first, slot=None):
            super().__init__(first, slot)
            (slot.dir / "SIDE2.D64").write_bytes(b"not the side")

    record = json.loads(failed.read_text(encoding="utf-8"))
    record["disks"]["sides"]["SIDE2.D64"] = "0" * 64
    failed.write_text(json.dumps(record), encoding="utf-8")
    _, _, out, _ = drive(FIXED, tag="b", sess=OtherSide, resume_from=str(failed), at_step=3)
    assert "SIDE2.D64 staged on this slot differs" in _summary(out)["lost"]
    assert "changed since step 3 began" in _summary(out)["lost"]
