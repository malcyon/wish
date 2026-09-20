"""`tools/convert/convertrun.py`'s own stubs for the three `QMessageBox` calls
`EditorBinding.convert` can reach once its `exec()` is stubbed to accept.

`#542 (tools/convert/convertrun.py hangs forever on any successful C64 write,
because it never patches EditorBinding.convert's post-write QMessageBox.
information)`. A separate file from `tests/test_convert.py` on purpose:
that file's autouse `_no_real_modals` fixture (line 928 there) already
silences all three `QMessageBox` methods for every test in it, which would
hide exactly what these two tests are meant to catch -- a real box reaching
past `tools/convert/convertrun.py`'s own stubs. Both need a DOS save and the
player's own C64 disks and skip cleanly without either, matching how
`tests/test_convert.py`'s C64-branch tests behave.
"""

from __future__ import annotations

import datetime

import pytest
from conftest import load_tools_module
from gamedata import disk_dir
from support.dossave import _save_dir, needs_dos_saves

from editor import convert

convertrun = load_tools_module("convertrun")

needs_disks = pytest.mark.skipif(disk_dir() is None,
                                 reason="needs the game disks")


def _sentinel(name: str):
    def _raise(*args, **kwargs):
        raise AssertionError(f"a real QMessageBox.{name} was reached")
    return _raise


@pytest.fixture
def _guarded(monkeypatch):
    """The three boxes, pre-set to fail fast rather than hang -- the state
    `write_via_dialog` finds them in before its own stubs go in, and what
    should be back in place once it returns (`write_via_dialog` only ever
    restores what it found there, which by then is these sentinels, not
    whatever PyQt6 shipped). Without the fix in `tools/convert/convertrun.py`,
    `write_via_dialog` never touches these at all, so the first one
    `window.convert` reaches raises immediately instead of the test
    hanging."""
    guards = {}
    for name in ("information", "warning", "critical"):
        guard = _sentinel(name)
        monkeypatch.setattr(convert.QMessageBox, name, guard)
        guards[name] = guard
    return guards


@needs_dos_saves
@needs_disks
def test_a_successful_c64_write_returns_instead_of_waiting_on_the_success_box(
        tmp_path, _guarded):
    """Without the fix this hangs on the real success box, which
    `_guarded` replaces with a sentinel that fails in under a second
    instead. With the fix, `write_via_dialog` puts its own recording stub
    in front of that sentinel for the one call it makes, and the sentinel
    is back in place once it returns."""
    source = _save_dir() / "SAVGAMA.DAT"
    out = tmp_path / "out"
    out.mkdir()

    report = convertrun.write_via_dialog(source, "c64", out, None,
                                         disk_dir())

    today = datetime.date.today().isoformat()
    fresh = out / f"wish-{today}"
    assert report["written"]
    assert any(p.endswith(".D64") for p in report["written"])
    assert report["popups"] == [
        ["information", convert.DIALOG_TITLE,
         convert.CONVERT_SUCCESS.format(folder=fresh)]]
    for name, guard in _guarded.items():
        assert getattr(convert.QMessageBox, name) is guard


@needs_dos_saves
@needs_disks
def test_a_refused_write_stops_after_one_attempt_instead_of_looping(
        tmp_path, monkeypatch, _guarded):
    """`Direction.write` raising is what a player's own disk-full or
    permissions refusal looks like. Without the fix this hangs on the real
    refusal box (or, with a no-op `critical` instead of one that raises,
    spins `EditorBinding.convert`'s `while True` at full CPU forever --
    `exec` is stubbed to always accept, so nothing but the box itself ever
    stopped a second attempt). With the fix, `critical` raises `Refused`,
    which reaches here after exactly one write attempt."""
    calls = []

    def _fail(self, rehearsal, folder):
        calls.append(folder)
        raise OSError("disk full")

    monkeypatch.setattr(convert.DosToC64, "write", _fail)

    source = _save_dir() / "SAVGAMA.DAT"
    out = tmp_path / "out"
    out.mkdir()

    report = convertrun.write_via_dialog(source, "c64", out, None,
                                         disk_dir())

    assert report["refused"] == [convert.DIALOG_TITLE,
                                 convert.CANNOT_CONVERT]
    assert "written" not in report
    assert len(calls) == 1
    assert list(out.glob("wish-*")) == []
    for name, guard in _guarded.items():
        assert getattr(convert.QMessageBox, name) is guard
