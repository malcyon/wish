"""`tools/convert/convertrun.py` and `tools/convert/saveasdrive.py` publish through
Save As, so what the emulator boots is what the editor's Save As writes.

Both tests need a DOS save and the player's own C64 disks and skip cleanly
without either.
"""

from __future__ import annotations

import pytest
from conftest import load_tools_module
from gamedata import disk_dir
from support.dossave import _save_dir, needs_dos_saves

from editor import saveplan

convertrun = load_tools_module("convertrun")

needs_disks = pytest.mark.skipif(disk_dir() is None,
                                 reason="needs the game disks")


@needs_dos_saves
@needs_disks
def test_a_c64_conversion_is_the_output_of_save_as(tmp_path, monkeypatch):
    """The `.d64` written is the exact bytes `prepare_save_as` produced, and
    `publish` is what put it down."""
    prepared = []
    real = saveplan.prepare_save_as

    def spy(*args, **kwargs):
        plan = real(*args, **kwargs)
        prepared.append(plan)
        return plan

    monkeypatch.setattr(saveplan, "prepare_save_as", spy)
    out = tmp_path / "out"
    out.mkdir()

    report = convertrun.write_via_save_as(_save_dir() / "SAVGAMA.DAT", "c64",
                                          out, None, disk_dir())

    assert "refused" not in report
    assert len(prepared) == 1
    (written,) = [p for p in report["written"] if p.endswith(".D64")]
    (data,) = prepared[0].files.values()
    assert open(written, "rb").read() == data


@needs_dos_saves
@needs_disks
def test_a_refused_save_as_writes_nothing_and_says_why(tmp_path, monkeypatch):
    """A conversion Save As refuses is reported under `refused`, and nothing
    lands under the output folder."""
    def refuse(*args, **kwargs):
        raise saveplan.DroppedFields(["a field the writer cannot hold"])

    monkeypatch.setattr(saveplan, "prepare_save_as", refuse)
    out = tmp_path / "out"
    out.mkdir()

    report = convertrun.write_via_save_as(_save_dir() / "SAVGAMA.DAT", "c64",
                                          out, None, disk_dir())

    assert report["refused"][0] == "DroppedFields"
    assert "written" not in report
    assert list(out.glob("wish-*")) == []
