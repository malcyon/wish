"""The `snapshot` and `restore` console commands of `tools/curse_of_the_azure_bonds/doscurse.py`.

The DOSBox-X session is faked: the assertions are about which name reaches
`SnapshotSession`, what the console logs, and how `--snapshots` chooses the
DOSBox-X lease and session class.
"""

from __future__ import annotations

import contextlib
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.curse_of_the_azure_bonds import doscurse  # noqa: E402
from tools.dos import dossnapshot  # noqa: E402


class FakeSnapshots:
    """What the console calls on a `SnapshotSession`."""

    def __init__(self, changed=()):
        self.calls: list[tuple[str, str]] = []
        self.changed = list(changed)
        self.settled = 0

    def snapshot(self, name):
        self.calls.append(("snapshot", name))
        return pathlib.Path(f"/snapshots/{name}.sav")

    def restore(self, name):
        self.calls.append(("restore", name))
        return self.changed

    def settle(self, *args, **kwargs):
        self.settled += 1


class FakePlain:
    """A DOSBox 0.74 session: no `snapshot`."""


def _console(tmp_path, session, monkeypatch):
    con = doscurse.Console(session, tmp_path / "c.cmd", tmp_path / "c.log")
    monkeypatch.setattr(con, "shoot", lambda name="last": None)
    monkeypatch.setattr(con, "describe", lambda: None)
    return con


def _log(tmp_path):
    return (tmp_path / "c.log").read_text()


def test_snapshot_and_restore_pass_the_name(tmp_path, monkeypatch):
    s = FakeSnapshots()
    con = _console(tmp_path, s, monkeypatch)
    assert con.do("snapshot wm") is True
    assert con.do("restore wm") is True
    assert s.calls == [("snapshot", "wm"), ("restore", "wm")]
    assert s.settled == 1
    log = _log(tmp_path)
    assert f"snapshot wm -> {pathlib.Path('/snapshots') / 'wm.sav'}" in log
    assert "restored wm" in log
    assert "no SAVE file changed since the snapshot" in log


def test_restore_logs_saves_that_stay_on_disk(tmp_path, monkeypatch):
    s = FakeSnapshots(changed=["CHRDATA1.SAV", "SAVGAMA.DAT"])
    con = _console(tmp_path, s, monkeypatch)
    con.do("snapshot wm")
    con.do("restore wm")
    assert ("SAVE files changed since the snapshot stay on disk: "
            "CHRDATA1.SAV, SAVGAMA.DAT") in _log(tmp_path)


def test_restore_needs_a_snapshot_taken_in_this_console(tmp_path, monkeypatch):
    s = FakeSnapshots()
    con = _console(tmp_path, s, monkeypatch)
    con.do("restore wm")
    assert s.calls == []
    assert "no snapshot 'wm' in this console" in _log(tmp_path)


@pytest.mark.parametrize("line", ["snapshot", "snapshot a/b", "restore ../x"])
def test_a_bad_name_is_not_passed_on(tmp_path, monkeypatch, line):
    s = FakeSnapshots()
    con = _console(tmp_path, s, monkeypatch)
    con.do(line)
    assert s.calls == []
    assert "needs a name" in _log(tmp_path)


@pytest.mark.parametrize("word", ["snapshot", "restore"])
def test_a_plain_dosbox_console_says_it_needs_snapshots(tmp_path, monkeypatch, word):
    con = _console(tmp_path, FakePlain(), monkeypatch)
    assert con.do(f"{word} wm") is True
    assert f"{word} needs DOSBox-X: start the console with --snapshots" in _log(tmp_path)


def test_the_commands_are_not_unknown(tmp_path, monkeypatch):
    con = _console(tmp_path, FakeSnapshots(), monkeypatch)
    con.do("snapshot wm")
    con.do("restore wm")
    assert "unknown command" not in _log(tmp_path)


class _Slot:
    def __init__(self, d):
        self.n, self.display, self.dir = 3, ":93", d


def _record_console(monkeypatch, tmp_path):
    seen = {}

    def lease(kind):
        def claim(note):
            seen["lease"] = kind
            return contextlib.nullcontext(_Slot(tmp_path))
        return claim

    class FakeSession:
        def __init__(self, slot, game, exe):
            seen["session"] = type(self).__name__

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class FakeSnapshotSession(FakeSession):
        pass

    monkeypatch.setattr(doscurse, "claim", lease("dosbox"))
    monkeypatch.setattr(doscurse.dosboxx, "claim", lease("dosbox-x"))
    monkeypatch.setattr(doscurse.dosboxx, "unavailable", lambda: None)
    monkeypatch.setattr(doscurse, "Session", FakeSession)
    monkeypatch.setattr(dossnapshot, "SnapshotSession", FakeSnapshotSession)
    monkeypatch.setattr(doscurse, "find_game", lambda game: tmp_path / game)
    monkeypatch.setattr(doscurse.Console, "run", lambda self, minutes: None)
    return seen


def test_snapshots_flag_boots_dosbox_x(tmp_path, monkeypatch):
    seen = _record_console(monkeypatch, tmp_path)
    assert doscurse.main(["console", "--snapshots", "--minutes", "0"]) == 0
    assert seen == {"lease": "dosbox-x", "session": "FakeSnapshotSession"}


def test_without_the_flag_the_console_stays_on_dosbox(tmp_path, monkeypatch):
    seen = _record_console(monkeypatch, tmp_path)
    assert doscurse.main(["console", "--minutes", "0"]) == 0
    assert seen == {"lease": "dosbox", "session": "FakeSession"}
