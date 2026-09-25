"""`tools/convert/saveasdrive.save_as` publishes through Save As and can be re-run
into the same output folder. The publishing tests need a DOS save and the
player's own C64 disks and skip cleanly without them.
"""

from __future__ import annotations

import datetime

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
