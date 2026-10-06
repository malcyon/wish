"""A route step's screen miss leaves a snapshot, the screen, both disks and a resume record, and frees the lane."""

from __future__ import annotations

import hashlib
import types

import pytest

from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.test_amigaacceptance import _audio_proof
from tests.amiga.test_amigaacceptance_accept import (  # noqa: F401
    AcceptGuest,
    Answer,
    MapGuard,
    _accept,
    _manifest,
    readings,
)
from tests.amiga.test_amigaacceptance_encounters import FakeSwitch
from tests.amiga.test_amigaacceptance_snapshot import FakePipe, _encounter_guard
from tests.amiga.test_amigaacceptance_title import STATES, TitleGuest, _run, make_title
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
