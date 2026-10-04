"""What `tools/c64/turndrive.py` stages into a copy of a save, with no emulator.

The fixture save is the committed `tests/fixtures/savedgame0.bin` party written
as a disk by `dos_codec.save_disk`, as `test_c64acceptance.py` builds one.
"""

from __future__ import annotations

import pathlib
import shutil

import pytest
from conftest import load_tools_module

from goldbox import dos_codec, effects, savegame
from goldbox.c64_port import POOL_OF_RADIANCE
from goldbox.d64 import D64, split_load_address
from goldbox.savegame import SaveGame0, SaveGame1

turndrive = load_tools_module("turndrive")

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
ARRAYS = (effects.EFFECT_ID_OFFSET, effects.EFFECT_OWNER_OFFSET,
          effects.EFFECT_DURATION_OFFSET, effects.EFFECT_MAGNITUDE_OFFSET)


def _disk(tmp_path: pathlib.Path) -> pathlib.Path:
    payload = SaveGame0.from_prg((FIXTURES / "savedgame0.bin").read_bytes()).to_bytes()
    save1 = SaveGame1.from_prg((FIXTURES / "savedgame1.bin").read_bytes()).to_bytes()
    path = tmp_path / "staged.d64"
    path.write_bytes(dos_codec.save_disk(payload, save1, POOL_OF_RADIANCE).to_bytes())
    return path


def _files(path):
    image = D64.open(str(path))
    return (split_load_address(image.read_file(POOL_OF_RADIANCE.save_file))[1],
            split_load_address(image.read_file(b"SAVEDGAME1"))[1])


def _occupied(roster: bytes) -> int:
    return next(i for i in range(savegame.ROSTER_COUNT)
                if any(roster[i * savegame.ROSTER_STRIDE:
                              (i + 1) * savegame.ROSTER_STRIDE]))


def _record(path, index):
    return savegame.load_save(D64.open(str(path)))[1].slot(index).record


def test_a_row_is_written_through_write_effect_as_acceptance_does(tmp_path):
    path = _disk(tmp_path)
    before, _ = _files(path)
    turndrive.stage(path, {}, turndrive.parse_rows(["5=0B:02:00:86"]))
    after, _ = _files(path)
    assert [after[a + 5] for a in ARRAYS] == [0x0B, 2, 0, 0x86]
    expected = bytearray(before)
    effects.write_effect(expected, 5, 0x0B, 2, 0, 0x86)
    assert after == bytes(expected)


def test_a_side_byte_goes_into_the_roster_block_and_nothing_else(tmp_path):
    path = _disk(tmp_path)
    payload, roster = _files(path)
    n = _occupied(roster)
    turndrive.stage(path, {}, (), {n: 0x80})
    payload2, roster2 = _files(path)
    at = n * savegame.ROSTER_STRIDE + savegame.ROSTER_COMBAT_SIDE
    assert roster2[at] == 0x80
    assert roster2[:at] == roster[:at] and roster2[at + 1:] == roster[at + 1:]
    assert payload2 == payload


def test_a_control_side_of_zero_overwrites_a_set_byte(tmp_path):
    path = _disk(tmp_path)
    n = _occupied(_files(path)[1])
    turndrive.stage(path, {}, (), {n: 0xC0})
    turndrive.stage(path, {}, (), {n: 0x00})
    _, roster = _files(path)
    assert roster[n * savegame.ROSTER_STRIDE + savegame.ROSTER_COMBAT_SIDE] == 0


def test_the_turning_byte_stage_is_unchanged(tmp_path):
    path = _disk(tmp_path)
    payload, roster = _files(path)
    sg0 = savegame.load_save(D64.open(str(path)))[1]
    n = next(i for i, s in enumerate(sg0.slots) if s.occupied)
    written = turndrive.stage(path, {n: 0})
    assert _record(path, n).get("turn_power") == 0
    assert written == [(str(_record(path, n).name), 0)]
    payload2, roster2 = _files(path)
    assert roster2 == roster
    assert [payload2[a + s] for a in ARRAYS for s in range(64)] == \
           [payload[a + s] for a in ARRAYS for s in range(64)]


def test_the_options_parse():
    assert turndrive.parse_stage("2=0,4=9") == {2: 0, 4: 9}
    assert turndrive.parse_rows(["5=0B:02:00:86"]) == [(5, 0x0B, 2, 0, 0x86)]


def test_a_replaced_row_is_reported_with_what_the_slot_held(tmp_path):
    path = _disk(tmp_path)
    before, _ = _files(path)
    replaced = []
    turndrive.stage(path, {}, [(5, 0x0B, 2, 0, 0x86)], (), replaced)
    assert replaced == [{"slot": 5, "was": [before[a + 5] for a in ARRAYS],
                         "now": [0x0B, 2, 0, 0x86]}]


@pytest.mark.parametrize("sides", [{-1: 0x80}, {8: 0x80}, {"n": 300}])
def test_a_bad_side_is_rejected_and_the_disk_is_untouched(tmp_path, sides):
    path = _disk(tmp_path)
    if "n" in sides:
        sides = {_occupied(_files(path)[1]): sides["n"]}
    before = path.read_bytes()
    with pytest.raises(SystemExit):
        turndrive.stage(path, {}, (), sides)
    assert path.read_bytes() == before


def test_a_side_into_an_empty_roster_block_is_rejected(tmp_path):
    path = _disk(tmp_path)
    _, roster = _files(path)
    empty = next(i for i in range(savegame.ROSTER_COUNT)
                 if not any(roster[i * savegame.ROSTER_STRIDE:
                                   (i + 1) * savegame.ROSTER_STRIDE]))
    before = path.read_bytes()
    with pytest.raises(SystemExit, match="empty"):
        turndrive.stage(path, {}, (), {empty: 0x80})
    assert path.read_bytes() == before


@pytest.mark.parametrize("option", [
    ["--stage-side", "2=300"], ["--stage-side=-1=0x80"],
    ["--stage-side", "8=0x80"], ["--stage-side", "2"],
    ["--stage", "2=zz"], ["--stage", "9=0"],
    ["--stage-row", "64=0B:02:00:86"], ["--stage-row", "5=0B:02:00"],
    ["--stage-row", "5=0B:02:00:GG"], ["--stage-row", "5"],
])
def test_a_bad_option_exits_before_any_staging_directory_exists(tmp_path, option):
    out = tmp_path / "run"
    with pytest.raises(SystemExit) as raised:
        turndrive.main(["--disks", str(tmp_path), "--out", str(out), *option])
    assert raised.value.code not in (None, 0)
    assert not out.exists()


def test_a_side_into_an_empty_slot_leaves_no_staging_directory(tmp_path, monkeypatch):
    path = _disk(tmp_path)
    _, roster = _files(path)
    empty = next(i for i in range(savegame.ROSTER_COUNT)
                 if not any(roster[i * savegame.ROSTER_STRIDE:
                                   (i + 1) * savegame.ROSTER_STRIDE]))
    monkeypatch.setattr(turndrive.S, "stage_writable",
                        lambda src, dest: shutil.copy(path, dest))
    out = tmp_path / "run"
    with pytest.raises(SystemExit, match="empty"):
        turndrive.main(["--disks", str(tmp_path), "--out", str(out),
                        "--save", path.name, "--stage-side", f"{empty}=0x80"])
    assert not (out / "disks").exists()


def test_a_rejection_leaves_an_earlier_runs_staging_directory_alone(tmp_path, monkeypatch):
    path = _disk(tmp_path)
    _, roster = _files(path)
    empty = next(i for i in range(savegame.ROSTER_COUNT)
                 if not any(roster[i * savegame.ROSTER_STRIDE:
                                   (i + 1) * savegame.ROSTER_STRIDE]))
    monkeypatch.setattr(turndrive.S, "stage_writable",
                        lambda src, dest: shutil.copy(path, dest))
    out = tmp_path / "run"
    (out / "disks").mkdir(parents=True)
    marker = out / "disks" / "evidence.txt"
    marker.write_text("kept")
    (tmp_path / "POOL1.D64").write_bytes(b"x")
    with pytest.raises(SystemExit, match="empty"):
        turndrive.main(["--disks", str(tmp_path), "--out", str(out),
                        "--save", path.name, "--stage-side", f"{empty}=0x80"])
    assert marker.read_text() == "kept"
    assert not (out / "disks" / "STAGED.D64").exists()
    assert not (out / "disks" / "POOL1.D64").exists()
