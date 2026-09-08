"""Nine driven-run tools' own `Log`, hardened the way `tools/savecheck.py`'s
was hardened after `#380 (The session driver sometimes fails BEGIN
ADVENTURING within 0.2s of the picker loading, well inside its own 30s
wait)`: a second run at the same path keeps the first run's log rather than
truncating it, a dead console cannot take the record down with it, and a
`SIGTERM` unwinds through the run's own cleanup instead of killing it where it
stands. `#442 (Nine driven-run tools lose their log when the console goes,
and two truncate the previous run's)` moved `tools/fightrun.py`,
`tools/outdoorstep.py`, `tools/c64restinterrupt.py`, `tools/defeatdrive.py`,
`tools/statusdrive.py`, `tools/hallmenu.py`, `tools/turndrive.py`,
`tools/traitsave.py` and `tools/traitdrive.py` onto `tools/savecheck.py`'s
`Log`, either directly or as the base of a small subclass.

Every test here proves that against the tool's *own* class -- not against a
copy of the mechanism -- because the wiring is exactly what a tool could get
wrong even after the mechanism is proven once.
"""

from __future__ import annotations

import json
import os
import pathlib
import signal
import threading

import pytest
from conftest import load_tools_module

fightrun = load_tools_module("fightrun")
outdoorstep = load_tools_module("outdoorstep")
c64restinterrupt = load_tools_module("c64restinterrupt")
defeatdrive = load_tools_module("defeatdrive")
statusdrive = load_tools_module("statusdrive")
hallmenu = load_tools_module("hallmenu")
turndrive = load_tools_module("turndrive")
traitsave = load_tools_module("traitsave")
traitdrive = load_tools_module("traitdrive")


def entries(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


# ===========================================================================
# Every module's own `Log`/`Run`: a dead console, and a second run's path.
# ===========================================================================

#: (module, class name, constructor, jsonl file, append?)
#: `ctor(out)` returns an instance built the way the tool itself builds one --
#: some take a `.jsonl` path directly, some take a directory and name their
#: own file inside it, and `quiet` defaults to False throughout so `say`
#: prints -- and can fail -- exactly as it would unattended.
LOGS = [
    ("fightrun", fightrun, lambda out: fightrun.Run(out / "run.jsonl"),
     "run.jsonl", False),
    ("outdoorstep", outdoorstep, lambda out: outdoorstep.Log(out / "run.jsonl"),
     "run.jsonl", False),
    ("c64restinterrupt", c64restinterrupt,
     lambda out: c64restinterrupt.Log(out), "rest.jsonl", False),
    ("defeatdrive", defeatdrive, lambda out: defeatdrive.Log(out),
     "run.jsonl", False),
    ("statusdrive", statusdrive, lambda out: statusdrive.Log(out),
     "roster.jsonl", False),
    ("hallmenu", hallmenu, lambda out: hallmenu.Log(out),
     "hallmenu.jsonl", True),
    ("turndrive", turndrive, lambda out: turndrive.Log(out),
     "turn.jsonl", False),
    ("traitsave", traitsave, lambda out: traitsave.Log(out),
     "traitsave.jsonl", True),
    ("traitdrive", traitdrive, lambda out: traitdrive.Log(out),
     "traits.jsonl", False),
]


@pytest.mark.parametrize("name,module,ctor,fname,append", LOGS,
                         ids=[row[0] for row in LOGS])
def test_a_dead_console_does_not_take_the_log_down(
        name, module, ctor, fname, append, tmp_path, monkeypatch):
    """The exact loss in `#380`: the first `say` after a pipe breaks used to
    raise `BrokenPipeError` out of a bare `print`, which -- called from a
    failure handler -- takes the rest of the handler with it."""
    class DeadPipe:
        def write(self, *a):
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self):
            raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr(module.sys, "stdout", DeadPipe())
    log = ctor(tmp_path)
    log.say("the line nobody hears")           # must not raise
    log.emit("marker")
    log.close()
    assert log.talking is False
    kinds = [e["kind"] for e in entries(tmp_path / fname)]
    assert "console_closed" in kinds, kinds
    assert "marker" in kinds, kinds


@pytest.mark.parametrize("name,module,ctor,fname,append", LOGS,
                         ids=[row[0] for row in LOGS])
def test_a_second_run_at_the_same_path(
        name, module, ctor, fname, append, tmp_path):
    """Truncating tools keep the failing run's log under a new name;
    appending tools (`hallmenu`, `traitsave`) grow one shared file by
    design -- both are `#442`'s point: neither destroys what was there."""
    first = ctor(tmp_path)
    first.emit("first_run", note="the one nobody must lose")
    first.close()

    second = ctor(tmp_path)
    second.emit("second_run")
    second.close()

    out = tmp_path / fname
    if append:
        kinds = [e["kind"] for e in entries(out)]
        assert kinds == ["first_run", "second_run"], kinds
        assert not list(tmp_path.glob(f"{out.stem}-*{out.suffix}"))
    else:
        kept = list(tmp_path.glob(f"{out.stem}-*{out.suffix}"))
        assert len(kept) == 1, f"the first log was not kept: {list(tmp_path.iterdir())}"
        assert entries(kept[0])[0]["note"] == "the one nobody must lose"
        assert [e["kind"] for e in entries(out)] == ["second_run"]


# ===========================================================================
# End to end: a `SIGTERM` mid-boot unwinds through the run's own cleanup.
#
# `catch_signals()` turns SIGTERM into `Terminated` -- proven once, generically,
# in `tests/test_savecheck_log.py` -- but *calling* it is each tool's own line,
# added by `#442`, and a tool that forgot it would fail exactly this way: the
# process dies where `sess.boot()` stood, no slot torn down, no `.jsonl`
# closed. Driving each tool's own `main()` all the way to a real `SIGTERM` is
# what tests that line rather than the mechanism behind it.
# ===========================================================================

class FakeKeyboard:
    def screenshot(self, path: str) -> bool:
        return True

    def key(self, *a, **kw) -> None:
        pass


class FakeSession:
    """Only what a driver asks of a session on the way to `boot()` failing."""

    def __init__(self, disk, slot=None, on_boot=None):
        self.kbd = FakeKeyboard()
        self.slot = slot
        self.save_disk = str(pathlib.Path(str(disk)).with_name("no-such.d64"))
        self.outdoor_boat = None
        self._on_boot = on_boot

    def boot(self) -> bool:
        if self._on_boot is not None:
            self._on_boot()
        return False                # -> every caller raises "boot failed"

    def screen(self):
        return None

    def close(self) -> None:
        pass

    def terminate(self) -> None:
        """`Session.terminate()`: tears its own slot down and releases it."""
        if self.slot is not None:
            self.slot.teardown()
            self.slot.release()


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


def make_fake_s(slot: FakeSlot, on_boot=None):
    class FakeS:
        @staticmethod
        def claim_slot(want=None, note=""):
            return slot

        @staticmethod
        def stage_disks(slot_, disks, save=""):
            return str(pathlib.Path(slot_.dir) / "SIDE0.D64")

        @staticmethod
        def Session(disk, slot=None):
            return FakeSession(disk, slot=slot, on_boot=on_boot)

    return FakeS


@pytest.fixture
def real_session_patched(monkeypatch):
    """Patch `tools.session` itself, for the two tools that `import` it
    *inside* their driving function rather than at module scope --
    `c64restinterrupt.py`'s `drive` and `traitsave.py`'s `boot`. A module-level
    `from tools import session as S` can be overridden by replacing `S` on the
    tool's own module; a fresh `from tools import session as S` executed every
    call cannot, because it re-reads the real package each time.
    """
    import tools.session as real_session

    def patch(fake_s):
        monkeypatch.setattr(real_session, "claim_slot", fake_s.claim_slot)
        monkeypatch.setattr(real_session, "stage_disks", fake_s.stage_disks)
        monkeypatch.setattr(real_session, "Session", fake_s.Session)

    return patch


def _term(*a) -> None:
    os.kill(os.getpid(), signal.SIGTERM)


@pytest.fixture
def restore_signals():
    old = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    yield
    for sig, handler in old.items():
        signal.signal(sig, handler)


def _skip_off_main_thread():
    if threading.current_thread() is not threading.main_thread():
        pytest.skip("signal handlers only install on the main thread")


def test_fightrun_sigterm_mid_boot_tears_the_slot_down(
        tmp_path, monkeypatch, restore_signals):
    _skip_off_main_thread()
    slot = FakeSlot(tmp_path / "slot")
    fake_s = make_fake_s(slot, on_boot=_term)
    monkeypatch.setattr(fightrun, "S", fake_s)
    monkeypatch.setattr(fightrun, "claim_slot", fake_s.claim_slot)
    out = tmp_path / "run.jsonl"
    rc = fightrun.main(["--save", "PORSAVEB.D64", "--disks", str(tmp_path),
                        "--out", str(out), "--slot", "1"])
    assert rc == 1
    assert slot.torn and slot.released
    kinds = [e["kind"] for e in entries(out)]
    assert kinds[-1] == "failed", kinds
    assert "signal" in entries(out)[kinds.index("failed")]["error"]


def test_outdoorstep_sigterm_mid_boot_tears_the_slot_down(
        tmp_path, monkeypatch, restore_signals):
    _skip_off_main_thread()
    (tmp_path / "slot").mkdir()
    slot = FakeSlot(tmp_path / "slot")
    fake_s = make_fake_s(slot, on_boot=_term)
    monkeypatch.setattr(outdoorstep, "S", fake_s)
    disk = tmp_path / "PORSAVEB.D64"
    disk.write_bytes(b"\0" * 16)
    out = tmp_path / "run.jsonl"
    rc = outdoorstep.main(["--disk", str(disk), "--disks", str(tmp_path),
                           "--out", str(out)])
    assert rc == 2
    assert slot.torn and slot.released
    kinds = [e["kind"] for e in entries(out)]
    assert kinds[-1] == "failed", kinds


def test_c64restinterrupt_sigterm_mid_boot_tears_the_slot_down(
        tmp_path, real_session_patched, restore_signals):
    _skip_off_main_thread()
    slot = FakeSlot(tmp_path / "slot")
    real_session_patched(make_fake_s(slot, on_boot=_term))
    out = tmp_path / "run"
    rc = c64restinterrupt.main(["--disks", str(tmp_path),
                                "drive", "--save", "PORSAVEB.D64",
                                "--out", str(out)])
    assert rc == 1
    assert slot.torn or slot.released       # `sess.terminate()` -> both
    kinds = [e["kind"] for e in entries(out / "rest.jsonl")]
    assert kinds[-1] == "failed", kinds


def test_defeatdrive_sigterm_mid_boot_tears_the_slot_down(
        tmp_path, monkeypatch, restore_signals):
    _skip_off_main_thread()
    slot = FakeSlot(tmp_path / "slot")
    fake_s = make_fake_s(slot, on_boot=_term)
    monkeypatch.setattr(defeatdrive, "S", fake_s)
    out = tmp_path / "run"
    rc = defeatdrive.main(["--save", "PORSAVEB.D64", "--disks", str(tmp_path),
                           "--out", str(out)])
    assert rc == 1
    assert slot.torn and slot.released
    kinds = [e["kind"] for e in entries(out / "run.jsonl")]
    assert kinds[-1] == "failed", kinds


def test_statusdrive_sigterm_mid_boot_tears_the_slot_down(
        tmp_path, monkeypatch, restore_signals):
    _skip_off_main_thread()
    slot = FakeSlot(tmp_path / "slot")
    fake_s = make_fake_s(slot, on_boot=_term)
    monkeypatch.setattr(statusdrive, "S", fake_s)
    out = tmp_path / "run"
    rc = statusdrive.main(["--save", "PORSAVEB.D64", "--disks", str(tmp_path),
                           "--out", str(out)])
    assert rc == 1
    assert slot.torn and slot.released
    kinds = [e["kind"] for e in entries(out / "roster.jsonl")]
    assert kinds[-1] == "failed", kinds


def test_hallmenu_sigterm_mid_boot_tears_the_slot_down(
        tmp_path, monkeypatch, restore_signals):
    """`hallmenu.py`'s `run` has no `except`, so `Terminated` reaches `main`
    uncaught -- but the `finally` blocks still tear the slot down and close
    the log, which is the guarantee this is proving. `#442` did not add a
    failure handler here; it only stopped the signal from killing the
    process outright."""
    _skip_off_main_thread()
    (tmp_path / "slot").mkdir()
    slot = FakeSlot(tmp_path / "slot")
    fake_s = make_fake_s(slot, on_boot=_term)
    monkeypatch.setattr(hallmenu, "S", fake_s)
    disk = tmp_path / "PORSAVEB.D64"
    disk.write_bytes(b"\0" * 16)
    out = tmp_path / "run"
    with pytest.raises(hallmenu.SC.Terminated):
        hallmenu.main(["--disk", str(disk), "--disks", str(tmp_path),
                       "--out", str(out)])
    assert slot.torn and slot.released
    assert (out / "hallmenu.jsonl").exists()


def test_turndrive_sigterm_mid_boot_tears_the_slot_down(
        tmp_path, monkeypatch, restore_signals):
    _skip_off_main_thread()
    slot = FakeSlot(tmp_path / "slot")
    fake_s = make_fake_s(slot, on_boot=_term)
    monkeypatch.setattr(turndrive, "S", fake_s)
    out = tmp_path / "run"
    rc = turndrive.main(["--save", "PORSAVEB.D64", "--disks", str(tmp_path),
                         "--out", str(out)])
    assert rc == 1
    assert slot.torn and slot.released
    kinds = [e["kind"] for e in entries(out / "turn.jsonl")]
    assert kinds[-1] == "failed", kinds


def test_traitsave_boot_sigterm_mid_boot_tears_the_slot_down(
        tmp_path, real_session_patched, monkeypatch, restore_signals):
    _skip_off_main_thread()
    monkeypatch.setattr(traitsave, "trait_blocks", lambda path: {})
    slot = FakeSlot(tmp_path / "slot")
    real_session_patched(make_fake_s(slot, on_boot=_term))
    disk = tmp_path / "PORSAVEB.D64"
    disk.write_bytes(b"\0" * 16)
    out = tmp_path / "run"
    rc = traitsave.main(["--out", str(out), "--disks", str(tmp_path),
                         "boot", "--disk", str(disk)])
    assert rc == 1
    assert slot.torn and slot.released
    kinds = [e["kind"] for e in entries(out / "traitsave.jsonl")]
    assert kinds[-1] == "failed", kinds


def test_traitdrive_sigterm_mid_boot_tears_the_slot_down(
        tmp_path, monkeypatch, restore_signals):
    _skip_off_main_thread()
    slot = FakeSlot(tmp_path / "slot")
    fake_s = make_fake_s(slot, on_boot=_term)
    monkeypatch.setattr(traitdrive, "S", fake_s)
    monkeypatch.setattr(traitdrive, "trait_blocks", lambda path: {})

    class FakePredicate:
        base = 0x1000
        entry = 0x1010
        array = 0x1020
        trait_scan = 0x1030

    monkeypatch.setattr(traitdrive, "predicate_for",
                        lambda title, disks: FakePredicate())
    monkeypatch.setattr(traitdrive.gamedisks, "find", lambda name: None)
    save = tmp_path / "PORSAVEB.D64"
    save.write_bytes(b"\0" * 16)
    out = tmp_path / "run"
    rc = traitdrive.main(["--save", "PORSAVEB.D64", "--disks", str(tmp_path),
                          "--out", str(out)])
    assert rc == 1
    assert slot.torn and slot.released
    kinds = [e["kind"] for e in entries(out / "traits.jsonl")]
    assert kinds[-1] == "failed", kinds

