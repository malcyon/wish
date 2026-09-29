"""`tools/convert/saveasdrive.save_as` publishes through Save As and can be re-run
into the same output folder. The publishing tests need a DOS save and the
player's own C64 disks and skip cleanly without them.
"""

from __future__ import annotations

import datetime
import pathlib

import pytest
from conftest import load_tools_module
from gamedata import disk_dir
from support.dossave import _save_dir, needs_dos_saves

saveasdrive = load_tools_module("saveasdrive")

needs_disks = pytest.mark.skipif(disk_dir() is None,
                                 reason="needs the game disks")


class _NoGameFiles:
    """A window that finds no game data for any title."""

    @staticmethod
    def game_files_for(_title):
        return None


def test_a_second_destination_the_same_day_is_a_new_folder(tmp_path):
    stem = f"wish-{datetime.date.today().isoformat()}"
    first = saveasdrive.destination_path("dos", tmp_path)
    first.mkdir()
    second = saveasdrive.destination_path("dos", tmp_path)
    assert first.name == stem
    assert second != first and second.parent == tmp_path
    second.mkdir()
    assert saveasdrive.destination_path("c64", tmp_path).parent not in (
        first, second)


@needs_dos_saves
@needs_disks
def test_save_as_twice_into_one_folder_publishes_both_times(tmp_path):
    reports = [
        saveasdrive.save_as(_NoGameFiles(), _save_dir() / "SAVGAMA.DAT", "c64",
                            tmp_path, c64_folder=disk_dir())
        for _ in range(2)]

    assert all("refused" not in r for r in reports), reports
    first, second = ([p for p in r["written"] if p.endswith(".D64")]
                     for r in reports)
    assert first and second and first != second


@needs_dos_saves
def test_a_real_refusal_names_its_class_and_writes_nothing(tmp_path):
    report = saveasdrive.save_as(_NoGameFiles(), _save_dir() / "SAVGAMA.DAT",
                                 "c64", tmp_path)

    assert report["refused"][0] == "MissingAssets"
    assert report["error"].startswith("MissingAssets: ")
    assert "written" not in report
    assert list(tmp_path.rglob("*.D64")) == []


def _patch_save_as(monkeypatch, prepare):
    """Stand in for everything `save_as` reaches that needs a disk."""
    from editor import roster, saveplan
    from editor.convert import Source

    monkeypatch.setattr(Source, "detect", staticmethod(lambda *a, **k: object()))
    monkeypatch.setattr(Source, "of_snapshot", staticmethod(lambda snap: snap))
    monkeypatch.setattr(roster, "Party", lambda detected: object())
    monkeypatch.setattr(saveplan, "prepare", lambda party: object())
    monkeypatch.setattr(saveplan, "resolve_assets", lambda *a, **k: object())
    monkeypatch.setattr(saveplan, "prepare_save_as", prepare)
    monkeypatch.setattr(saveplan, "publish", lambda *a, **k: None)


def test_chosen_names_reach_prepare_save_as(monkeypatch, tmp_path):
    seen = {}

    class _Stop(Exception):
        pass

    def prepare(party, port, path, assets, **kwargs):
        seen.update(kwargs)
        raise _Stop

    _patch_save_as(monkeypatch, prepare)
    saveasdrive.save_as(_NoGameFiles(), "unused", "amiga", tmp_path,
                        names={0: "SHORTNAME"})

    assert seen == {"names": {0: "SHORTNAME"}}


def test_a_name_that_does_not_fit_is_reported_with_its_width(monkeypatch,
                                                              tmp_path):
    from editor import saveplan

    def prepare(*_a, **_k):
        raise saveplan.NamesDoNotFit(((0, "L" * 18),), 15)

    _patch_save_as(monkeypatch, prepare)
    report = saveasdrive.save_as(_NoGameFiles(), "unused", "amiga", tmp_path)

    assert report["refused"][0] == "NamesDoNotFit"
    assert report["unfit"] == [[0, "L" * 18]]
    assert report["width"] == 15
    assert "written" not in report


def _run_dialogdrive(monkeypatch, tmp_path, calls, *name_args):
    """Run `convertdialogdrive.main` with `save_as` and the editor stubbed,
    appending the keywords of each `save_as` call to `calls`."""
    from editor import window

    convertdialogdrive = load_tools_module("convertdialogdrive")
    class _Binding:
        def __init__(self, *_a, **_k):
            pass

        def close(self):
            pass

    def fake_save_as(_window, _specimen, _port, _out, **kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(window, "EditorBinding", _Binding)
    # `main` imports the package path, a different module object from the
    # file-path load at the top of this test module.
    from tools.convert import saveasdrive as imported
    monkeypatch.setattr(imported, "save_as", fake_save_as)
    specimen = tmp_path / "SAVGAMA.DAT"
    specimen.write_bytes(b"x")
    disk = tmp_path / "disk2.adf"
    disk.write_bytes(b"x")
    code = convertdialogdrive.main(
        ["--specimen", str(specimen), "--amiga-disk2", str(disk),
         "--out-dir", str(tmp_path / "out"), "--tree", str(_ROOT), *name_args])
    return code


_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_name_option_reaches_save_as_as_a_position_map(monkeypatch, tmp_path):
    calls = []
    code = _run_dialogdrive(monkeypatch, tmp_path, calls,
                            "--name", "3=A B", "--name", "0=Wren")

    assert code == 0
    assert calls[0]["names"] == {3: "A B", 0: "Wren"}


def test_a_repeated_name_position_exits_before_save_as(monkeypatch, tmp_path):
    calls = []
    with pytest.raises(SystemExit) as stop:
        _run_dialogdrive(monkeypatch, tmp_path, calls, "--name", "1=One",
                         "--name", "1=Two")

    assert stop.value.code != 0
    assert calls == []
