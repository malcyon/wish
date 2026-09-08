"""What a driven run leaves behind when it fails, and what it must not lose.

`#380 (The session driver sometimes fails BEGIN ADVENTURING within 0.2s of the
picker loading, well inside its own 30s wait)` is a failure nobody can
diagnose, and the reason is not the failure: it is that the run's own record of
it went. Two things took it. A retry on the same disk truncated the first run's
log before it had even booted, because `--out` defaults to a path built from
the disk's name and not from `--tag`; and the traceback was written *after* a
screenshot and a screen read, which between them take a fifth of a second and
reach out to two other processes, so a run killed in that window keeps the
picture and loses the exception.

Neither of these needs an emulator to test. Both are about the order and the
naming of what `Log` writes.
"""

import json
import os
import pathlib
import signal
import threading

import pytest
from conftest import load_tools_module

savecheck = load_tools_module("savecheck")


def entries(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_a_retry_on_the_same_disk_keeps_the_failed_runs_log(tmp_path):
    """The exact loss in #380: two runs, one default log path, and the second
    one opens its log before it boots -- so the first run's evidence goes
    minutes before the retry reaches the point it is trying to reproduce."""
    out = tmp_path / "PORSAVEB.jsonl"
    first = savecheck.Log(out)
    first.emit("failed", error="RuntimeError('the one nobody read')")
    first.close()

    second = savecheck.Log(out)
    second.emit("picker", listed=True)
    second.close()

    kept = [p for p in tmp_path.glob("PORSAVEB-*.jsonl")]
    assert len(kept) == 1, f"the first log was not kept: {list(tmp_path.iterdir())}"
    assert entries(kept[0])[0]["error"] == "RuntimeError('the one nobody read')"
    assert [e["kind"] for e in entries(out)] == ["picker"]


def test_two_logs_kept_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    """The kept name is stamped from the old file's mtime, and a second and a
    third run inside one second would otherwise collide with it."""
    out = tmp_path / "NEWJ.jsonl"
    for n in range(3):
        log = savecheck.Log(out)
        log.emit("run", n=n)
        log.close()
    kept = sorted(tmp_path.glob("NEWJ-*.jsonl"))
    assert len(kept) == 2
    assert sorted(entries(p)[0]["n"] for p in kept) == [0, 1]
    assert entries(out)[0]["n"] == 2


class FakeKeyboard:
    def __init__(self, on_shot=None):
        self.on_shot = on_shot

    def screenshot(self, path: str) -> bool:
        if self.on_shot is not None:
            self.on_shot()
        return True


class FakeSession:
    """Only what `run` asks of a session before it gets to `boot`."""

    def __init__(self, disk, slot=None, on_shot=None):
        self.kbd = FakeKeyboard(on_shot)
        self.outdoor_boat = None
        self.closed = False

    def boot(self) -> bool:
        return False            # -> RuntimeError("boot failed")

    def screen(self):
        return None

    def close(self) -> None:
        self.closed = True


class FakeSlot:
    def __init__(self, d: pathlib.Path):
        self.n = 9
        self.display = ":99"
        self.dir = str(d)
        self.torn = self.released = False

    def teardown(self) -> None:
        self.torn = True

    def release(self) -> None:
        self.released = True


def drive_a_failing_run(tmp_path, monkeypatch, on_shot=None) -> pathlib.Path:
    """Run `savecheck.main` far enough to fail, with no emulator anywhere."""
    here = tmp_path / "slot"
    here.mkdir()
    slot = FakeSlot(here)
    disk = tmp_path / "PORSAVEB.D64"
    disk.write_bytes(b"\0" * 16)
    out = tmp_path / "run.jsonl"

    class FakeS:
        Session = staticmethod(
            lambda disk, slot=None: FakeSession(disk, slot, on_shot))

        @staticmethod
        def claim_slot(want=None, note=""):
            return slot

        @staticmethod
        def stage_disks(slot, disks, save=""):
            return str(here / "SIDE1.D64")

    monkeypatch.setattr(savecheck, "S", FakeS)
    assert savecheck.main(["--disk", str(disk), "--disks", str(tmp_path),
                           "--out", str(out)]) == 1
    assert slot.torn and slot.released
    return out


def test_the_traceback_is_written_before_the_photograph(tmp_path, monkeypatch):
    """A run killed while it is photographing the failure keeps the exception.

    The screenshot shells out to `import -window root` and the screen read is
    a monitor round trip; #380 measured the pair at 0.209s. Writing the
    traceback first is what makes that window survivable, and the order in
    the file is the only thing that says it happened.
    """
    out = drive_a_failing_run(tmp_path, monkeypatch)
    kinds = [e["kind"] for e in entries(out)]
    assert "failed" in kinds and "failure_screen" in kinds
    assert kinds.index("failed") < kinds.index("failure_screen"), kinds
    failed = entries(out)[kinds.index("failed")]
    assert failed["error"] == "RuntimeError('boot failed')"
    assert "boot failed" in failed["traceback"]


def test_a_photograph_that_throws_does_not_take_the_traceback_with_it(
        tmp_path, monkeypatch):
    def explode():
        raise OSError("no such display :99")

    out = drive_a_failing_run(tmp_path, monkeypatch, on_shot=explode)
    kinds = [e["kind"] for e in entries(out)]
    assert kinds[-1] == "failed", kinds
    assert "failure_screen" not in kinds


def test_a_signal_stops_the_run_through_its_own_cleanup(tmp_path, monkeypatch):
    """`timeout 200 tools/savecheck.py ...` is how this tool is usually run,
    and an unhandled SIGTERM there kills it mid-statement: no traceback, no
    teardown, and an emulator slot still leased."""
    if threading.current_thread() is not threading.main_thread():
        pytest.skip("signal handlers only install on the main thread")
    old = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        out = drive_a_failing_run(
            tmp_path, monkeypatch,
            on_shot=lambda: os.kill(os.getpid(), signal.SIGTERM))
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)
    kinds = [e["kind"] for e in entries(out)]
    assert kinds[-1] == "failed"
    assert entries(out)[-1]["error"] == "RuntimeError('boot failed')"


def test_the_signal_handler_raises_rather_than_killing_the_process():
    if threading.current_thread() is not threading.main_thread():
        pytest.skip("signal handlers only install on the main thread")
    old = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        savecheck.catch_signals()
        with pytest.raises(savecheck.Terminated):
            os.kill(os.getpid(), signal.SIGTERM)
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


class DeadPipe:
    """A stdout whose reader has gone -- `... | head -40`, after `head` exits."""

    def write(self, *a):
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self):
        raise BrokenPipeError(32, "Broken pipe")


def test_a_console_that_has_gone_does_not_take_the_record_with_it(
        tmp_path, monkeypatch, capsys):
    """#380's exact leftovers: a screenshot, a `failure_screen`, and no
    `failed`. That is what the old handler produced when the first `log.say`
    after the photograph raised `BrokenPipeError` -- the inner handler's own
    `say` raised too, and the entry carrying the traceback was never reached.
    """
    monkeypatch.setattr(savecheck.sys, "stdout", DeadPipe())
    out = drive_a_failing_run(tmp_path, monkeypatch)
    kinds = [e["kind"] for e in entries(out)]
    assert "failed" in kinds and "failure_screen" in kinds, kinds
    assert "console_closed" in kinds
    assert entries(out)[kinds.index("failed")]["error"] \
        == "RuntimeError('boot failed')"


class DyingPipe(DeadPipe):
    """A console that goes *during* the run, which is the awkward case.

    `head -40` reads its forty lines and exits while the run is still going,
    so the first writes succeed and a later one raises.
    """

    def __init__(self, good: int):
        self.left = good
        self.said: list[str] = []

    def write(self, s):
        if self.left <= 0:
            raise BrokenPipeError(32, "Broken pipe")
        self.left -= 1
        self.said.append(s)

    def flush(self):
        if self.left <= 0:
            raise BrokenPipeError(32, "Broken pipe")


@pytest.mark.parametrize("good", range(1, 12))
def test_the_traceback_survives_the_console_dying_at_any_point(
        tmp_path, monkeypatch, capsys, good):
    """Wherever the pipe breaks, the `.jsonl` still names the exception.

    The console dying between the photograph and the first `log.say` after it
    is the one that produced #380's leftovers -- a `.png`, a
    `"failure_screen"`, and nothing saying what went wrong.
    """
    monkeypatch.setattr(savecheck.sys, "stdout", DyingPipe(good))
    out = drive_a_failing_run(tmp_path, monkeypatch)
    failed = [e for e in entries(out) if e["kind"] == "failed"]
    assert len(failed) == 1, [e["kind"] for e in entries(out)]
    assert failed[0]["error"] == "RuntimeError('boot failed')"


def test_a_log_that_cannot_be_kept_still_lets_the_new_run_write(
        tmp_path, monkeypatch):
    """Keeping the old log must never cost the new one.

    The old file can vanish between the check and the stat, and its directory
    can be unwritable, and either raised out of `Log.__init__` takes the whole
    run down before a single entry is written -- no `.jsonl` at all, which is
    worse than the truncation `keep_old_log` exists to prevent. So the
    preservation is best effort: it gives up and the run opens the path in
    place.
    """
    out = tmp_path / "PORSAVEB.jsonl"
    out.write_text('{"kind": "the run nobody could keep"}\n')

    def gone(self, target):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(pathlib.Path, "rename", gone)
    log = savecheck.Log(out)
    log.emit("picker", listed=["BEGIN ADVENTURING"])
    log.close()
    assert [e["kind"] for e in entries(out)] == ["picker"]


def test_the_record_going_does_not_raise_out_of_the_failure_handler(
        tmp_path, monkeypatch):
    """The console half is hardened; the file half must not be the new hole.

    `say` catches a dead terminal and writes `console_closed` to the `.jsonl`
    -- and if *that* write raises as well, because the disk is full or the
    descriptor is closed, it comes straight back out of the failure handler,
    which is the shape of the loss #380 is about.
    """
    out = tmp_path / "PORSAVEB.jsonl"
    log = savecheck.Log(out)

    def dead(*a, **kw):
        raise OSError(32, "Broken pipe")

    monkeypatch.setattr("builtins.print", dead)
    log.emit = dead                        # the record has gone too
    log.say("the line nobody hears")       # must not raise
    assert log.talking is False
