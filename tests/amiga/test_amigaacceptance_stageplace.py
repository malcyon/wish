"""`prepare --published-disk-one --stage-place X,Y,F`: the party's square written into working DF0's loaded slot."""

from __future__ import annotations

import json
import pathlib

import pytest

from goldbox import amiga_savegame
from goldbox.amiga_adf import AmigaDisk
from tests.amiga.test_amigaacceptance_camp import CURSE_NAMES, _published_report
from tests.support import amigasavegame as synthetic_amiga
from tools.amiga import acceptance as foundation
from tools.amiga import staging
from tools.amiga.winuaesession import RouteError

KEY = "curse-of-the-azure-bonds"
CURSE = amiga_savegame.CURSE


def _curse(indoors=1, area=1, script=True, names=("ALPHA",)) -> bytes:
    """The synthetic Curse save, made a party that has set out in area 1 (or as told)."""
    data = bytearray(synthetic_amiga.synthetic_curse(names))
    for address, value in ((0x49F2, area), (0x49E6, indoors), (0x49C5, 1)):
        at = CURSE.vm_offset(address)
        data[at:at + 2] = value.to_bytes(2, "big")
    if script:
        data[CURSE.ecl_at + 10] = 1
    return bytes(data)


def _prepare(tmp_path, monkeypatch, save, place=None):
    monkeypatch.setattr(synthetic_amiga, "synthetic_curse", lambda names=(): save)
    report = _published_report(tmp_path, monkeypatch, "curse", "dos", names=CURSE_NAMES)
    return foundation.prepare_published("curse", "staged", report, "628", place=place), report


def test_a_staged_place_changes_only_the_three_square_bytes_and_reads_back():
    data = _curse()
    staged, change = staging.stage_place(data, KEY, 6, 14, 0)
    assert change == {"before": [3, 14, 1], "after": [6, 14, 0]}
    changed = [i for i in range(len(data)) if data[i] != staged[i]]
    x_low, facing = CURSE.square_at + 1, CURSE.square_at + 4
    assert changed == [x_low, facing]
    read = amiga_savegame.parse(staged, KEY)
    assert (read.x, read.y, read.facing) == (6, 14, 0)
    east, _ = staging.stage_place(data, KEY, 15, 0, 1)
    assert amiga_savegame.parse(east, KEY).facing == 2


@pytest.mark.parametrize("place", [(16, 0, 0), (0, 16, 0), (0, 0, 4), (-1, 0, 0), (0, -1, 0), (0, 0, -1)])
def test_a_place_out_of_range_is_refused(place):
    with pytest.raises(staging.StageError, match="x and y are 0 to 15, facing 0 to 3"):
        staging.stage_place(_curse(), KEY, *place)


@pytest.mark.parametrize("data,why", [
    (_curse(indoors=0), "made outdoors"),
    (_curse(script=False), "has not set out"),
    (b"not a saved game", "not a readable"),
], ids=["outdoors", "not-set-out", "unknown"])
def test_an_outdoor_unset_or_unknown_save_is_refused(data, why):
    with pytest.raises(staging.StageError, match=why):
        staging.stage_place(data, KEY, 6, 14, 0)


def test_a_staged_prepare_puts_the_place_in_df0_only_and_records_it(tmp_path, monkeypatch):
    path, _report = _prepare(tmp_path, monkeypatch, _curse(), place=(6, 14, 0))
    manifest, title = foundation._published_manifest(path, "curse")
    assert manifest["state_a"] == {"area": 1, "x": 6, "y": 14, "facing": 0}
    assert manifest["staged_place"] == {"slot": "/save/savgamd.dat",
                                        "before": [3, 14, 1], "after": [6, 14, 0]}
    df0 = AmigaDisk.open(manifest["disks"]["df0"]["path"])
    published = AmigaDisk.open(manifest["registered"]["published"]["path"])
    assert amiga_savegame.read_slot(df0, "D", KEY).x == 6
    assert amiga_savegame.read_slot(published, "D", KEY).x == 3
    assert manifest["disks"]["df0"]["sha256"] != manifest["registered"]["published"]["sha256"]
    assert manifest["published_source"]["sha256"] == manifest["registered"]["published"]["sha256"]
    assert title.route


def test_a_prepare_without_a_place_is_unchanged(tmp_path, monkeypatch):
    path, _report = _prepare(tmp_path, monkeypatch, _curse())
    manifest, _title = foundation._published_manifest(path, "curse")
    assert "staged_place" not in manifest
    assert manifest["disks"]["df0"]["sha256"] == manifest["registered"]["published"]["sha256"]


@pytest.mark.parametrize("save,place,why", [
    (_curse(), (16, 0, 0), "x and y are 0 to 15"),
    (_curse(script=False), (6, 14, 0), "has not set out"),
], ids=["range", "not-set-out"])
def test_a_refused_place_makes_no_run_folder(tmp_path, monkeypatch, save, place, why):
    with pytest.raises(RouteError, match=why):
        _prepare(tmp_path, monkeypatch, save, place=place)
    assert not (tmp_path / "cache").exists()


def test_a_staged_df0_that_differs_by_more_than_the_place_is_refused(tmp_path, monkeypatch):
    path, _report = _prepare(tmp_path, monkeypatch, _curse(), place=(6, 14, 0))
    manifest = json.loads(path.read_text())
    df0_path = manifest["disks"]["df0"]["path"]
    df0 = AmigaDisk.open(df0_path)
    raw = bytearray(df0.read_file("/save/savgamd.dat"))
    raw[CURSE.square_at + 3] ^= 1
    df0.write_file("/save/savgamd.dat", bytes(raw))
    df0.save(df0_path)
    manifest["disks"]["df0"]["sha256"] = foundation.sha256(pathlib.Path(df0_path))
    path.write_text(json.dumps(manifest))
    with pytest.raises(RouteError, match="differs from the published image by more than"):
        foundation._published_manifest(path, "curse")


def test_a_staged_manifest_whose_df0_is_the_published_image_is_refused(tmp_path, monkeypatch):
    path, _report = _prepare(tmp_path, monkeypatch, _curse(), place=(6, 14, 0))
    manifest = json.loads(path.read_text())
    published = manifest["registered"]["published"]
    manifest["disks"]["df0"] = dict(published)
    path.write_text(json.dumps(manifest))
    with pytest.raises(RouteError):
        foundation._published_manifest(path, "curse")


def test_the_cli_refuses_a_bad_place_and_a_place_without_published_disk_one(tmp_path, capsys):
    for extra, why in ((["--published-disk-one", "--saveas-report", "x.json",
                          "--stage-place", "16,0,0"], "x and y are 0 to 15"),
                       (["--stage-place", "6,14,0"], "requires --published-disk-one"),
                       (["--published-disk-one", "--saveas-report", "x.json",
                         "--stage-place", "6,14"], "a place is X,Y,FACING")):
        foundation.main(["prepare", "--title", "curse", "--run-id", "r", *extra])
        assert why in capsys.readouterr().err
