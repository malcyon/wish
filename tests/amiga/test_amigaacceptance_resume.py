"""A route step's screen miss leaves a snapshot, the screen, both disks and a resume record, and frees the lane."""

from __future__ import annotations

import hashlib
import json
import pathlib
import types

import pytest

from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.test_amigaacceptance import _audio_proof
from tests.amiga.test_amigaacceptance_accept import (  # noqa: F401
    AcceptGuest,
    Answer,
    MapGuard,
    _accept,
    _IdentityMap,
    _manifest,
    readings,
)
from tests.amiga.test_amigaacceptance_encounters import FakeSwitch
from tests.amiga.test_amigaacceptance_snapshot import FakePipe, _encounter_guard
from tests.amiga.test_amigaacceptance_title import (
    STATES,
    TitleGuest,
    _keys,
    _run,
    make_title,
    manifest_for,
)
from tools.amiga import acceptance
from tools.amiga.winuaesession import RouteError
from tools.registry import resumerecord

clock = measure.clock  # the fixture that replaces the driver's time and sleep
STATE_BYTES = b"ASF the machine at the miss"
STATE_PATH = "C:\\Amiga\\States\\wish672-test\\resume\\resume"


class ResumeMixin:
    """A guest whose pipe takes a snapshot and whose `get` can copy the state file out."""

    state_bytes = STATE_BYTES
    snapshot_error = None
    change_on_stop = False
    get_seconds = 0
    snapshot_seconds = 0

    def snapshot(self, name, holder):
        self.calls.append(("snapshot", name, holder))
        self.clock.now += self.snapshot_seconds
        if self.snapshot_error:
            raise self.snapshot_error
        return types.SimpleNamespace(tags={
            "file": STATE_PATH, "sha256": hashlib.sha256(self.state_bytes).hexdigest(),
            "count_snapshot": "900", "bytes": str(len(self.state_bytes)), "exe": "winuae.exe"})

    def get(self, remote, local, timeout=None):
        self.clock.now += self.get_seconds
        if remote == STATE_PATH:
            self.calls.append(("get", remote, str(local)))
            local.write_bytes(self.state_bytes)
            return
        super().get(remote, local, timeout)

    def stop(self, holder, timeout=None):
        super().stop(holder, timeout)
        if self.change_on_stop:
            # A game save still in flight when the snapshot was taken.
            self._save("Z")


class ResumeAcceptGuest(ResumeMixin, AcceptGuest):
    pass


class _Drives(tuple):
    """The mounted paths the fake guest keeps, which can also be called as the readback."""

    reply = None

    def __call__(self, holder):
        return self.reply(holder)


class DrivesGuest(ResumeAcceptGuest):
    """The fake guest's `start` keeps its mounted paths in `drives`; this one also answers its readback."""

    reply = None

    def start(self, holder, df0, df1, timeout=None):
        shown = super().start(holder, df0, df1, timeout)
        self.drives = _Drives(self.drives)
        self.drives.reply = self.reply
        return shown


class ResumeTitleGuest(ResumeMixin, TitleGuest):
    pass


def _missing(step, state="sheet"):
    """A guard that never recognises the screen of route step `step`, a strict one by default."""
    return MapGuard(on={state: lambda path: not path.stem.startswith(f"{step:02d}-")})


def _names(guest, *wanted):
    return [c[0] for c in guest.calls if c[0] in wanted]


def _order(guest):
    """The failure capture, the snapshot, the state copy, the stop and the release, as they went."""
    labels = {("capture", "failure"): "failure capture", ("get", STATE_PATH): "state copy"}
    out = []
    for call in guest.calls:
        label = labels.get(call[:2]) or (call[0] if call[0] in ("snapshot", "stop", "release") else None)
        if label:
            out.append(label)
    return out


def _record(result):
    return resumerecord.read(result["resume_record"], "amiga")


def test_an_accept_miss_saves_the_state_the_screen_and_a_record_then_frees_the_lane(
        tmp_path, clock, readings):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    _, result = _accept(tmp_path, clock, guest=guest, guard=_missing(4))
    assert "sheet screen was not recognized" in result["error"]
    assert _order(guest) == ["failure capture", "snapshot", "state copy", "stop", "release"]
    record = _record(result)
    assert record["step"]["n"] == 4 and record["step"]["state"] == "sheet"
    assert len(record["sent"]) == 4
    assert [key for key, _ in record["sent"]] == measure._keys(guest)[:4] == "P L C V".split()
    assert record["step"]["key"] == record["sent"][-1][0]
    assert record["step"]["kind"] == record["sent"][-1][1] == "key"
    assert (tmp_path / "recon1" / "resume" / "state.uss").read_bytes() == STATE_BYTES
    assert record["machine"]["count_snapshot"] == 900 and record["machine"]["exe"] == "winuae.exe"
    assert record["resumable"] is True and result["resumable"] is True
    assert {"df0", "df1"} == set(record["disks"])
    assert all(entry["settled"] for entry in record["disks"].values())
    assert record["holder"] == "wish672-test" and record["attempt"] == "recon1"
    assert record["command"] == "accept" and record["options"]["no_encounters"] is False
    assert result["resume_record"].endswith("resume.json")
    assert (tmp_path / "recon1" / "resume" / "screen.png").is_file()


def test_a_measure_miss_writes_a_record_too(tmp_path, clock):
    guest = ResumeTitleGuest(clock)
    guard = MapGuard(states=STATES, on={"loaded_menu": lambda p: not p.stem.startswith("03-")})
    _, result = _run(tmp_path, clock, guest=guest, accept=False, measure=True, guard=guard)
    record = _record(result)
    assert record["command"] == "measure"
    assert (record["step"]["n"], record["step"]["state"]) == (3, "loaded_menu")
    assert [key for key, _ in record["sent"]] == "P L A".split()
    assert record["start"]["mounted"][0].endswith("-boot.adf")
    assert _names(guest, "snapshot", "stop", "release") == ["snapshot", "stop", "release"]


def test_the_switch_goes_off_before_the_snapshot_and_the_record_says_it_was_on(
        tmp_path, clock, readings):  # noqa: F811
    guest = ResumeTitleGuest(clock)
    # The title's step 7 is a move, whose screen the guard is made to miss.
    title = make_title(strict=make_title().strict | {"world"})
    guard = MapGuard(states=("title", *STATES),
                     on={"world": lambda p: not p.stem.startswith("07-")})
    _, result = _run(tmp_path, clock, guest=guest, title=title, guard=guard,
                     encounters=FakeSwitch(guest))
    calls = [c[:2] for c in guest.calls if c[0] in ("encounters", "snapshot")]
    assert calls[-2:] == [("encounters", "off"), ("snapshot", "resume")]
    record = _record(result)
    assert record["step"]["n"] == 7 and record["step"]["kind"] == "move"
    assert record["options"] == {
        "no_encounters": True, "encounters_on_at_miss": True, "walk_retry": 0}


def test_a_miss_with_the_switch_given_but_not_yet_on_records_it_as_off(
        tmp_path, clock, readings):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    _, result = _accept(tmp_path, clock, guest=guest, guard=_missing(4),
                        encounters=FakeSwitch(guest))
    record = _record(result)
    assert record["options"]["encounters_on_at_miss"] is False
    assert record["options"]["no_encounters"] is True
    assert ("encounters", "off") not in [c[:2] for c in guest.calls]


def test_a_normal_run_writes_no_record_and_takes_no_snapshot(
        tmp_path, clock, readings):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    _, result = _accept(tmp_path, clock, guest=guest)
    assert result["error"] == "" and "resume_record" not in result and "resumable" not in result
    assert _names(guest, "snapshot") == []
    assert not (tmp_path / "recon1" / "resume").exists()


def test_a_title_wait_miss_writes_no_record_and_says_why(tmp_path, clock, readings):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    _, result = _accept(tmp_path, clock, guest=guest,
                        guard=MapGuard(on={"title": lambda path: False}))
    assert "title screen was not recognized" in result["error"]
    assert result["resumable"] is False and "route step" in result["resume_why_not"]
    assert _names(guest, "snapshot") == [] and not (tmp_path / "recon1" / "resume").exists()
    assert _names(guest, "stop", "release") == ["stop", "release"]


def test_an_exhausted_walk_leg_writes_no_record(tmp_path, clock, readings):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    fake = FakePipe(guest)
    guest.restore = fake.restore
    guest.snapshot = fake.snapshot
    _, result = _accept(tmp_path, clock, guest=guest, guard=_encounter_guard(fake, 99),
                        walk_retry=1)
    assert "after 1 walk retries" in result["error"]
    assert "resume_record" not in result and "resumable" not in result
    assert [c[1] for c in fake.calls if c[0] == "snapshot"] == ["walk-leg"]
    assert not (tmp_path / "recon1" / "resume").exists()


def test_a_disk_that_changed_after_the_snapshot_is_not_resumable(
        tmp_path, clock, readings):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    guest.change_on_stop = True
    _, result = _accept(tmp_path, clock, guest=guest, guard=_missing(4))
    record = _record(result)
    assert record["resumable"] is False and result["resumable"] is False
    assert record["disks"]["df0"]["settled"] is False and record["disks"]["df1"]["settled"] is True
    assert "df0" in record["why_not"] and result["resume_why_not"] == record["why_not"]
    assert _names(guest, "release") == ["release"]


def test_a_snapshot_that_raises_leaves_no_record_and_the_run_still_stops(
        tmp_path, clock, readings):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    guest.snapshot_error = RouteError("the guest wrote no state file")
    _, result = _accept(tmp_path, clock, guest=guest, guard=_missing(4))
    assert "the guest wrote no state file" in result["resume_error"]
    assert result["resumable"] is False and "resume_record" not in result
    assert not (tmp_path / "recon1" / "resume" / "resume.json").exists()
    assert _names(guest, "stop", "release") == ["stop", "release"]


def test_a_state_file_that_differs_from_the_guests_hash_leaves_no_record(
        tmp_path, clock, readings):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    guest.state_bytes = b"ASF damaged"
    sent = hashlib.sha256(STATE_BYTES).hexdigest()
    real_snapshot = guest.snapshot

    def snapshot(name, holder):
        receipt = real_snapshot(name, holder)
        receipt.tags["sha256"] = sent
        return receipt

    guest.snapshot = snapshot
    _, result = _accept(tmp_path, clock, guest=guest, guard=_missing(4))
    assert "differs from the one it wrote" in result["resume_error"]
    assert not (tmp_path / "recon1" / "resume" / "resume.json").exists()


def test_a_miss_after_the_route_time_ended_still_saves(tmp_path, clock, readings):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    real_grab = guest.grab

    def late(state, raw, cropped, timeout=None):
        shown = real_grab(state, raw, cropped, timeout)
        if state == "04-sheet":
            # Past the route time (the deadline less its cleanup reserve), inside the deadline.
            clock.now = 1000 + 1510
        return shown

    guest.grab = late
    _, result = _accept(tmp_path, clock, guest=guest, guard=_missing(4))
    assert "sheet screen was not recognized" in result["error"]
    assert _names(guest, "snapshot", "stop", "release") == ["snapshot", "stop", "release"]
    assert _record(result)["step"]["n"] == 4


def test_the_name_resume_is_not_free_for_a_camp_or_mark_snapshot(
        tmp_path, clock, readings):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    with pytest.raises(RouteError, match="resume"):
        _accept(tmp_path, clock, guest=guest, marks={14: (("snapshot", "Resume"),)})
    assert guest.calls == []


def _main(tmp_path, clock, monkeypatch, guest, guard, capsys):
    guest.answer = Answer(guest)
    monkeypatch.setattr(acceptance, "WinGuest", lambda: guest)
    monkeypatch.setattr(acceptance, "PixelGuards", lambda path: guard)
    monkeypatch.setattr(acceptance, "journal_preflight", lambda python: None)
    monkeypatch.setattr(acceptance, "run_journal_answer",
                        lambda python, holder, adf, timeout: guest.answer(holder, adf, timeout))
    code = acceptance.main([
        "accept", "--title", "ssb", "--manifest", str(_manifest(tmp_path)),
        "--guards", "g.json", "--identity", "i.json", "--journal-python", "py",
        "--audio-proof", str(_audio_proof(tmp_path)), "--holder", "wish672-test"])
    return code, capsys.readouterr()


def test_main_exits_with_the_resume_status_and_names_the_record(
        tmp_path, clock, readings, monkeypatch, capsys):  # noqa: F811
    code, seen = _main(tmp_path, clock, monkeypatch, ResumeAcceptGuest(clock), _missing(4), capsys)
    assert code == resumerecord.RESUME_EXIT == 3
    record = tmp_path / "accept1" / "resume" / "resume.json"
    assert (f"acceptance: stopped on an unrecognised screen at step 4; resume with "
            f"--resume-from {record} --at-step 4") in seen.err


def test_main_keeps_exit_one_when_the_record_is_not_resumable(
        tmp_path, clock, readings, monkeypatch, capsys):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    guest.change_on_stop = True
    code, seen = _main(tmp_path, clock, monkeypatch, guest, _missing(4), capsys)
    assert code == 1 and "resume with" not in seen.err


def _slow_cleanup(guest, clock, *, jump):
    """A guest whose miss lands `jump` seconds in, and whose snapshot and every copy take time."""
    real_grab = guest.grab

    def late(state, raw, cropped, timeout=None):
        shown = real_grab(state, raw, cropped, timeout)
        if state == "04-sheet":
            clock.now = 1000 + jump
        return shown

    guest.grab = late


def test_a_snapshot_that_eats_the_cleanup_time_still_leaves_the_lane_released(
        tmp_path, clock, readings):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    # 290 s of the 300 s reserve are left at the miss; the stop, two fetches and the release need 180.
    _slow_cleanup(guest, clock, jump=1510)
    guest.snapshot_seconds, guest.get_seconds = 100, 60
    _, result = _accept(tmp_path, clock, guest=guest, guard=_missing(4))
    assert "too little cleanup time" in result["resume_error"]
    assert result["resumable"] is False and "resume_record" not in result
    assert _names(guest, "stop", "release") == ["stop", "release"]
    assert result["release"] is None and "release_error" not in result


def test_a_miss_with_too_little_cleanup_time_takes_no_snapshot(
        tmp_path, clock, readings):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    # 100 s left at the miss, less than the 180 s the stop, fetches and release need.
    _slow_cleanup(guest, clock, jump=1700)
    _, result = _accept(tmp_path, clock, guest=guest, guard=_missing(4))
    assert _names(guest, "snapshot") == []
    assert result["resumable"] is False and "too little cleanup time" in result["resume_why_not"]
    assert _names(guest, "stop", "release") == ["stop", "release"]


def test_the_drives_readback_is_kept_in_the_record(tmp_path, clock, readings):  # noqa: F811
    guest = DrivesGuest(clock)
    guest.reply = lambda holder: f"ok df0=C:/Amiga/Disks/a.adf rw holder={holder}"
    _, result = _accept(tmp_path, clock, guest=guest, guard=_missing(4))
    start = _record(result)["start"]
    assert start["drives_at_stop"] == "ok df0=C:/Amiga/Disks/a.adf rw holder=wish672-test"
    assert start["drives_error"] is None


def test_a_drives_readback_that_raises_is_recorded_and_the_save_goes_on(
        tmp_path, clock, readings):  # noqa: F811
    guest = DrivesGuest(clock)

    def unanswered(holder):
        raise RouteError("the pipe did not answer")

    guest.reply = unanswered
    _, result = _accept(tmp_path, clock, guest=guest, guard=_missing(4))
    start = _record(result)["start"]
    assert start["drives_at_stop"] is None and "the pipe did not answer" in start["drives_error"]
    assert result["resumable"] is True


def test_main_does_not_report_a_held_lane_as_resumable(
        tmp_path, clock, readings, monkeypatch, capsys):  # noqa: F811
    guest = ResumeAcceptGuest(clock)

    def release(holder, timeout=None):
        raise RouteError("the lane would not release")

    guest.release = release
    code, seen = _main(tmp_path, clock, monkeypatch, guest, _missing(4), capsys)
    assert code == 1 and "resume with" not in seen.err


def test_a_restore_mark_cuts_the_sent_keys_back_and_the_record_lists_it(
        tmp_path, clock, readings):  # noqa: F811
    guest = ResumeAcceptGuest(clock)
    fake = FakePipe(guest)
    resume_snapshot = guest.snapshot
    guest.snapshot = lambda name, holder: (
        resume_snapshot(name, holder) if name == "resume" else fake.snapshot(name, holder))
    guest.restore = fake.restore
    # Snapshot before step 5, restore before step 8: the machine goes back to before step 5 and
    # step 8's key goes out on that screen, so steps 5 to 7 are not in the machine's history.
    marks = {4: (("snapshot", "walk"),), 7: (("restore", "walk"),)}
    _, result = _accept(tmp_path, clock, guest=guest, marks=marks,
                        guard=_missing(8, "save_picker"))
    record = _record(result)
    keys = "P L C V I E E S".split()
    assert record["step"]["n"] == 8 and record["step"]["key"] == "S"
    assert [key for key, _ in record["sent"]] == keys[:4] + keys[7:]
    assert record["kept"]["restores"] == [{"restore": "walk", "step": 8}]


def test_an_insert_and_a_skipped_step_use_the_routes_own_keys_in_sent(tmp_path, clock):
    guest = ResumeTitleGuest(clock)
    title = make_title(strict=make_title().strict | {"disk_wait"})
    guard = MapGuard(states=("title", *STATES),
                     on={"disk_wait": lambda p: not p.stem.startswith("04-")})
    _, result = _run(tmp_path, clock, guest=guest, title=title, guard=guard)
    record = _record(result)
    # The route's insert step holds a list, the form `route_sha256` hashes; the key pressed is its last.
    assert record["sent"][3] == [[1, "disk3", "SPACE"], "insert"]
    assert record["step"]["key"] == "SPACE" and record["step"]["kind"] == "insert"


# -- resuming from a record -------------------------------------------------------------------

class Readback:
    """What `WinGuest.drives` returns: its `str` is only the status, its paths are in `drive_state`."""

    def __init__(self, paths):
        self.paths = paths

    def drive_state(self):
        return {"paths": self.paths}

    def __str__(self):
        return "ok"


class ResumedGuard(MapGuard):
    """The map guard, reading a crop named `...-resumed` as the screen it is a second look at."""

    def shown(self, path):
        return super().shown(path.with_name(path.name.replace("-resumed", "")))


class StoppedGuest(ResumeTitleGuest):
    """The first boot: its drive readback names what DF0 and DF1 held."""

    def __init__(self, clock):
        super().__init__(clock)
        # The fake's base class keeps an attribute named `drives`, which a method would not replace.
        self.drives = self.readback

    def readback(self, holder):
        return Readback({0: self.mounted[0], 1: self.mounted[1]})


class BackGuest(ResumeTitleGuest):
    """The second boot: a restore brings back the first machine's drives, keys pressed and place."""

    exe = "winuae.exe"
    restored_paths = None

    def __init__(self, clock, stopped):
        super().__init__(clock)
        self.stopped = stopped
        self.drive_override = None
        self.drives = self.readback

    def stage_snapshot(self, name, holder, sha256, count):
        self.calls.append(("stage_snapshot", name, holder, sha256, count))
        return "ok staged"

    def restore(self, name, holder, fresh=False):
        self.calls.append(("restore", name, holder, fresh))
        self.mounted = list(self.stopped.mounted)
        self.presses = self.stopped.presses
        self.place = dict(self.stopped.place)
        return types.SimpleNamespace(tags={"exe": self.exe, "count_after": "905"})

    def readback(self, holder):
        if self.drive_override is not None:
            return Readback(self.drive_override)
        return Readback({0: self.mounted[0], 1: self.mounted[1]})


WORLD_AT_7 = {"world": lambda p: not p.stem.startswith("07-")}


def _title():
    return make_title(strict=make_title().strict | {"world"})


def _stopped(tmp_path, clock, *, miss=7, state="world", **kw):
    """A title accept that misses route step `miss`, and the record it leaves."""
    guest = StoppedGuest(clock)
    guard = MapGuard(states=("title", *STATES, "world"),
                     on={state: lambda p: not p.stem.startswith(f"{miss:02d}-")})
    guest, result = _run(tmp_path, clock, guest=guest, title=_title(), guard=guard, **kw)
    assert result["resumable"] is True, result
    return guest, result


def _resume(tmp_path, clock, stopped, result, *, at_step=7, guest=None, guard=None,
            title=None, holder="wish679-test", attempt="resume1", manifest=None, **kw):
    """The same run again from the record, with its own guest, and the call list before the claim."""
    guest = guest or BackGuest(clock, stopped)
    kw.setdefault("accept", True)
    kw.setdefault("resume_from", pathlib.Path(result["resume_record"]))
    run = acceptance.run_recon(
        manifest or manifest_for(tmp_path), guest=guest,
        guard=guard or ResumedGuard(states=("title", *STATES, "world")),
        identity=_IdentityMap(), holder=holder, audio_proof=_audio_proof(tmp_path),
        title=title or _title(), attempt=attempt, at_step=at_step, **kw)
    return guest, run


def test_a_record_from_a_miss_resumes_at_its_step_and_finishes(tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock)
    guest, result = _resume(tmp_path, clock, stopped, first)
    assert result["error"] == "" and result["success"] is True, result.get("read")
    assert result["completed"] is True
    # Step 7's key went out before the snapshot: only steps 8 to 10 are pressed.
    assert _keys(guest) == ["E", "S", "D"]
    assert [e["step"] for e in result["events"] if "key" in e] == [8, 9, 10]
    assert result["resumed_from"]["step"] == 7
    assert result["resumed_from"]["record"] == first["resume_record"]
    assert result["resumed_from"]["sha256"] == hashlib.sha256(
        pathlib.Path(first["resume_record"]).read_bytes()).hexdigest()
    assert pathlib.Path(result["resumed_from"]["earlier_summary"]).parts[-2:] == ("recon1", "summary.json")
    assert any(e.get("state") == "07-world-resumed" for e in result["events"])
    assert result["read"]["verdicts"][-1].startswith("slot D: moved 1 square")


def test_the_resume_calls_go_claim_disks_state_start_title_restore_drives_then_the_screen(
        tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock)
    guest, _ = _resume(tmp_path, clock, stopped, first)
    seq = []
    for call in guest.calls:
        if call[0] == "put":
            seq.append("put state" if call[2].endswith("-state.uss") else "put disk")
        elif call[0] in ("claim", "stage_snapshot", "start", "restore", "press"):
            seq.append(call[0])
        elif call[0] == "grab" and "start" in seq and "restore" not in seq and "title" not in seq:
            seq.append("title")
    assert seq[:7] == ["claim", "put disk", "put disk", "put disk", "put state", "stage_snapshot",
                       "start"]
    assert seq[7:] == ["title", "restore", "press", "press", "press"] or (
        seq[7:9] == ["title", "restore"] and seq[9:] == ["press"] * 3), seq
    (_, name, holder, fresh), = [c for c in guest.calls if c[0] == "restore"]
    assert (name, holder, fresh) == ("resume", "wish679-test", True)
    staged = [c for c in guest.calls if c[0] == "stage_snapshot"][0]
    assert staged[1:3] == ("resume", "wish679-test") and staged[4] == 900
    assert staged[3] == hashlib.sha256(STATE_BYTES).hexdigest()


def test_the_disks_put_are_the_records_copies_not_the_manifests(tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock)
    guest, _ = _resume(tmp_path, clock, stopped, first)
    folder = pathlib.Path(first["resume_record"]).parent
    puts = {c[2].rsplit("-", 1)[1]: pathlib.Path(c[1]) for c in guest.calls
            if c[0] == "put" and c[2].endswith(".adf")}
    assert {name: path.parent for name, path in puts.items()} == dict.fromkeys(puts, folder)
    manifest_boot = (tmp_path / "boot.adf").read_bytes()
    # The first run's slot C went onto its boot disk, so the record's copy is not the manifest's.
    assert (folder / "boot.adf").read_bytes() != manifest_boot
    assert puts["boot.adf"].name == "boot.adf"
    state = [c for c in guest.calls if c[0] == "put" and c[2].endswith("-state.uss")]
    assert state[0][2] == "C:/Amiga/Disks/wish679-wish679-test-state.uss"
    assert pathlib.Path(state[0][1]).name == "state.uss"


def test_the_start_uses_the_recorded_settings(tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock)
    guest, _ = _resume(tmp_path, clock, stopped, first)
    assert guest.starts == stopped.starts


@pytest.mark.parametrize("why", [
    "manifest", "route_before", "key_changed", "at_step", "holder", "no_encounters",
    "walk_retry", "config", "state_hash", "disk_hash", "later_restore", "not_resumable",
    "command"])
def test_a_mismatch_stops_before_any_lane_call(tmp_path, clock, monkeypatch, why):
    stopped, first = _stopped(tmp_path, clock)
    folder = pathlib.Path(first["resume_record"]).parent
    guest = BackGuest(clock, stopped)
    kw, title, at_step, holder = {}, _title(), 7, "wish679-test"

    def edited_route(index, key):
        route = list(_title().route)
        route[index] = (key, route[index][1], route[index][2])
        return make_title(route=tuple(route), measure_route=tuple(route), strict=_title().strict)

    if why == "manifest":
        kw["manifest"], message = manifest_for(tmp_path, loaded="B"), "the manifest differs"
    elif why == "route_before":
        title, message = edited_route(1, "Q"), "history at entry 2"
    elif why == "key_changed":
        title, message = edited_route(6, "NP6"), "history at entry 7"
    elif why == "at_step":
        at_step, message = 6, "--at-step 6 is not the record's step 7"
    elif why == "holder":
        holder, message = "wish679-other", "the record's holder is wish679-test"
    elif why == "no_encounters":
        kw["encounters"], message = FakeSwitch(guest), "option no_encounters differs"
    elif why == "walk_retry":
        kw["walk_retry"], message = 1, "option walk_retry differs"
    elif why == "config":
        other = tmp_path / "other.uae"
        other.write_text("changed")
        monkeypatch.setattr(acceptance, "LOCAL_BOOT_CONFIG", other)
        message = "start setting config_sha256 differs"
    elif why == "state_hash":
        (folder / "state.uss").write_bytes(b"ASF another machine")
        message = "state.uss does not match its recorded"
    elif why == "disk_hash":
        (folder / "boot.adf").write_bytes(b"changed")
        message = "boot.adf does not match its recorded"
    elif why == "later_restore":
        # A snapshot taken before step 7 does not exist in the new process.
        kw["marks"] = {5: (("snapshot", "back"),), 8: (("restore", "back"),)}
        message = "restore back goes back to a snapshot taken before step 7"
    elif why == "not_resumable":
        record = pathlib.Path(first["resume_record"])
        data = json.loads(record.read_text())
        data["resumable"], data["why_not"] = False, "the disk changed"
        record.write_text(json.dumps(data))
        message = "the record is not resumable: the disk changed"
    else:
        kw["accept"], kw["measure"] = False, True
        message = "the record is for command 'accept', not 'measure'"
    with pytest.raises(RouteError, match=message):
        _resume(tmp_path, clock, stopped, first, guest=guest, title=title, at_step=at_step,
                holder=holder, **kw)
    assert guest.calls == []


def test_a_resume_needs_both_options(tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock)
    guest = BackGuest(clock, stopped)
    with pytest.raises(RouteError, match="go together"):
        _resume(tmp_path, clock, stopped, first, guest=guest, at_step=None)
    assert guest.calls == []


def test_a_miss_inside_the_walk_leg_cannot_be_resumed(tmp_path, clock, monkeypatch):
    # B1 never records a miss inside a leg, since a retry handles it, so the leg is moved over step 9.
    stopped, first = _stopped(tmp_path, clock, miss=9, state="camp_picker", walk_retry=1)
    monkeypatch.setattr(acceptance, "_walk_leg", lambda steps: (7, 9))
    guest = BackGuest(clock, stopped)
    with pytest.raises(RouteError, match="step 9 is inside the walk leg"):
        _resume(tmp_path, clock, stopped, first, at_step=9, guest=guest, walk_retry=1)
    assert guest.calls == []


def test_a_resume_at_a_miss_before_a_walk_leg_still_takes_the_leg_snapshot(tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock, miss=4, state="disk_wait", walk_retry=1)
    guest, result = _resume(tmp_path, clock, stopped, first, at_step=4, walk_retry=1,
                            guard=ResumedGuard(states=("title", *STATES, "world")))
    assert result["error"] == "" and result["success"] is True
    assert [c[1] for c in guest.calls if c[0] == "snapshot"] == ["walk-leg"]
    assert _keys(guest) == ["C", "NP2", "NP8", "E", "S", "D"]


def _measure_miss(tmp_path, clock):
    """A measure run that misses step 3; its guard knows the title, which a measure run needs to resume."""
    stopped = StoppedGuest(clock)
    guard = MapGuard(states=("title", *STATES), on={
        "title": lambda p: p.stem == "title" or p.stem.startswith("00-boot"),
        "loaded_menu": lambda p: not p.stem.startswith("03-")})
    _, first = _run(tmp_path, clock, guest=stopped, accept=False, measure=True, guard=guard)
    assert first["resumable"] is True
    return stopped, first


def _measure_resume_guard():
    return ResumedGuard(states=("title", *STATES), on={
        "title": lambda p: p.stem == "title" or p.stem.startswith("00-boot")})


def test_a_measure_record_resumes_and_finishes(tmp_path, clock):
    stopped, first = _measure_miss(tmp_path, clock)
    guest, result = _resume(tmp_path, clock, stopped, first, at_step=3, accept=False, measure=True,
                            guard=_measure_resume_guard())
    assert result["error"] == "" and result["resumed_from"]["step"] == 3
    # Steps 1 to 3 were pressed before the snapshot; the measured route ends before the first write.
    assert _keys(guest) == ["SPACE"]
    assert result["route_changed"] is True


def test_a_measure_resume_without_a_title_guard_is_blocked(tmp_path, clock):
    stopped, first = _measure_miss(tmp_path, clock)
    guest = BackGuest(clock, stopped)
    with pytest.raises(RouteError, match="needs a title screen guard"):
        _resume(tmp_path, clock, stopped, first, at_step=3, accept=False, measure=True,
                guest=guest, guard=MapGuard(states=STATES))
    assert guest.calls == []


def test_a_restore_that_fails_presses_no_key_and_still_frees_the_lane(tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock)
    guest = BackGuest(clock, stopped)

    def failed(name, holder, fresh=False):
        guest.calls.append(("restore", name, holder, fresh))
        raise RouteError("the fresh machine has run longer than the snapshot; restore earlier")

    guest.restore = failed
    _, result = _resume(tmp_path, clock, stopped, first, guest=guest)
    assert "restore earlier" in result["error"] and result["success"] is False
    assert _keys(guest) == []
    assert _names(guest, "stop", "release") == ["stop", "release"]


def test_drives_that_differ_from_the_recorded_ones_stop_the_run_before_any_key(tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock)
    guest = BackGuest(clock, stopped)
    guest.drive_override = {0: stopped.mounted[0], 1: "C:/Amiga/Disks/wish679-other-disk3.adf"}
    _, result = _resume(tmp_path, clock, stopped, first, guest=guest)
    assert "after the restore DF1 holds" in result["error"] and result["success"] is False
    assert _keys(guest) == [] and _names(guest, "stop", "release") == ["stop", "release"]


def test_the_drive_paths_compare_without_regard_to_slashes_or_case(tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock)
    guest = BackGuest(clock, stopped)
    guest.drive_override = {n: p.replace("/", "\\").upper() for n, p in
                            {0: stopped.mounted[0], 1: stopped.mounted[1]}.items()}
    _, result = _resume(tmp_path, clock, stopped, first, guest=guest)
    assert result["error"] == "" and _keys(guest) == ["E", "S", "D"]


def test_an_executable_that_differs_from_the_snapshots_stops_the_run(tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock)
    guest = BackGuest(clock, stopped)
    guest.exe = "another.exe"
    _, result = _resume(tmp_path, clock, stopped, first, guest=guest)
    assert "the snapshot was taken in 'winuae.exe'" in result["error"]
    assert _keys(guest) == []


def _switch_calls_after_the_restore(guest):
    """The switch changes and key presses from the restore on, in order."""
    start = [c[0] for c in guest.calls].index("restore")
    return [c[2] if c[0] == "press" else f"switch {c[1]}"
            for c in guest.calls[start:] if c[0] in ("press", "encounters")]


def test_the_switch_is_put_back_on_when_it_was_on_at_the_miss(tmp_path, clock, readings):  # noqa: F811
    stopped = StoppedGuest(clock)
    guard = MapGuard(states=("title", *STATES, "world"), on=WORLD_AT_7)
    _, first = _run(tmp_path, clock, guest=stopped, title=_title(), guard=guard,
                    encounters=FakeSwitch(stopped))
    assert first["resumable"] is True
    guest = BackGuest(clock, stopped)
    _, result = _resume(tmp_path, clock, stopped, first, guest=guest, encounters=FakeSwitch(guest))
    # On for the walk step's screen, as at the miss, before the screen is looked at; off for the camp step.
    assert _switch_calls_after_the_restore(guest) == ["switch on", "switch off", "E", "S", "D"]
    assert result["error"] == "" and result["success"] is True


def test_the_switch_stays_off_when_it_was_off_at_the_miss(tmp_path, clock, readings):  # noqa: F811
    stopped = StoppedGuest(clock)
    guard = MapGuard(states=("title", *STATES, "world"),
                     on={"disk_wait": lambda p: not p.stem.startswith("04-")})
    _, first = _run(tmp_path, clock, guest=stopped, title=_title(), guard=guard,
                    encounters=FakeSwitch(stopped))
    assert first["resumable"] is True
    guest = BackGuest(clock, stopped)
    _, result = _resume(tmp_path, clock, stopped, first, at_step=4, guest=guest,
                        encounters=FakeSwitch(guest))
    # Step 4 is an insert: nothing is turned on until each walk step's own gate.
    assert _switch_calls_after_the_restore(guest) == [
        "C", "switch on", "NP2", "switch on", "NP8", "switch off", "E", "S", "D"]
    assert result["error"] == "" and result["success"] is True


def test_a_resumed_run_that_misses_again_writes_a_record_covering_every_step(tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock)
    guest = BackGuest(clock, stopped)
    again = ResumedGuard(states=("title", *STATES, "world"),
                         on={"camp_picker": lambda p: not p.stem.startswith("09-")})
    _, result = _resume(tmp_path, clock, stopped, first, guest=guest, guard=again)
    assert result["resumable"] is True
    record = resumerecord.read(result["resume_record"], "amiga")
    assert record["step"]["n"] == 9 and len(record["sent"]) == 9
    assert [key for key, _ in record["sent"]] == [
        "P", "L", "A", [1, "disk3", "SPACE"], "C", "NP2", "NP8", "E", "S"]
    assert pathlib.Path(result["resume_record"]).parts[-3:] == ("resume1", "resume", "resume.json")
    # One resume can follow another.
    third = BackGuest(clock, guest)
    _, final = _resume(tmp_path, clock, guest, result, at_step=9, guest=third, attempt="resume2")
    assert final["error"] == "" and _keys(third) == ["D"]


def test_main_resumes_with_the_recorded_holder_and_passes_the_record_on(
        tmp_path, clock, monkeypatch, capsys):
    record = tmp_path / "resume.json"
    record.write_text(json.dumps({"holder": "wish2-a2"}))
    seen = {}

    def fake_run(manifest, **kw):
        seen.update(kw)
        raise RouteError("stop here")

    monkeypatch.setattr(acceptance, "run_recon", fake_run)
    monkeypatch.setattr(acceptance, "WinGuest", lambda: object())
    monkeypatch.setattr(acceptance, "PixelGuards", lambda path: None)
    args = ["measure", "--title", "pool", "--manifest", str(tmp_path / "prepare.json"),
            "--attempt", "resume1", "--audio-proof", str(_audio_proof(tmp_path)),
            "--resume-from", str(record), "--at-step", "13"]
    assert acceptance.main(args) == 2
    assert seen["holder"] == "wish2-a2"
    assert seen["resume_from"] == record and seen["at_step"] == 13
    seen.clear()
    assert acceptance.main([*args, "--holder", "wish2-b"]) == 2
    assert seen["holder"] == "wish2-b"
    seen.clear()
    assert acceptance.main(args[:-2]) == 2
    assert seen["resume_from"] == record and seen["at_step"] is None


def test_main_without_the_options_passes_no_resume(tmp_path, clock, monkeypatch):
    seen = {}

    def fake_run(manifest, **kw):
        seen.update(kw)
        raise RouteError("stop here")

    monkeypatch.setattr(acceptance, "run_recon", fake_run)
    monkeypatch.setattr(acceptance, "WinGuest", lambda: object())
    monkeypatch.setattr(acceptance, "PixelGuards", lambda path: None)
    assert acceptance.main(["measure", "--title", "pool", "--manifest",
                            str(tmp_path / "prepare.json"), "--attempt", "a",
                            "--audio-proof", str(_audio_proof(tmp_path))]) == 2
    assert "resume_from" not in seen and seen["holder"].startswith("wish")


def test_a_mismatch_leaves_no_attempt_folder_and_the_same_attempt_can_be_retried(tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock)
    guest = BackGuest(clock, stopped)
    with pytest.raises(RouteError, match="--at-step 6"):
        _resume(tmp_path, clock, stopped, first, guest=guest, at_step=6)
    assert not (tmp_path / "resume1").exists()
    _, result = _resume(tmp_path, clock, stopped, first)
    assert result["error"] == "" and result["success"] is True


@pytest.mark.parametrize("edit, message", [
    (lambda d: d["machine"].pop("exe"), "machine entry has no exe"),
    (lambda d: d["machine"].update(exe=None), "machine entry has no exe"),
    (lambda d: d["kept"].pop("previous_state"), "kept entry has no previous_state"),
    (lambda d: d["kept"].pop("previous_world"), "kept entry has no previous_world")])
def test_a_record_missing_what_the_resume_reads_stops_before_the_claim(
        tmp_path, clock, edit, message):
    stopped, first = _stopped(tmp_path, clock)
    path = pathlib.Path(first["resume_record"])
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))
    guest = BackGuest(clock, stopped)
    with pytest.raises(RouteError, match=message):
        _resume(tmp_path, clock, stopped, first, guest=guest)
    assert guest.calls == [] and not (tmp_path / "resume1").exists()


class DroppingBackGuest(BackGuest):
    """The resumed machine loses its first key press."""

    dropped = False

    def press(self, holder, key, timeout=None):
        if not self.dropped:
            self.dropped = True
            self.calls.append(("press", holder, key))
            return
        super().press(holder, key, timeout)


def _equal_to_the_at_step_screen(first, stopped):
    """Make the record's `previous_digest` the digest of the screen step 7 shows."""
    path = pathlib.Path(first["resume_record"])
    record = json.loads(path.read_text())
    record["kept"]["previous_digest"] = hashlib.sha256(
        f"frame {stopped.presses}".encode()).hexdigest()
    path.write_text(json.dumps(record))


def test_a_resumed_step_is_not_checked_against_the_record_s_digest(tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock)
    _equal_to_the_at_step_screen(first, stopped)
    guest, result = _resume(tmp_path, clock, stopped, first)
    assert result["error"] == "" and result["completed"] is True
    assert _keys(guest) == ["E", "S", "D"]


def test_the_step_after_a_resumed_one_is_checked(tmp_path, clock):
    stopped, first = _stopped(tmp_path, clock)
    guest, result = _resume(tmp_path, clock, stopped, first,
                            guest=DroppingBackGuest(clock, stopped))
    assert result["completed"] is False
    assert result["error"].startswith("KeyUnchanged: step 8 (camp): E left the screen unchanged")
    assert _keys(guest) == ["E"]
