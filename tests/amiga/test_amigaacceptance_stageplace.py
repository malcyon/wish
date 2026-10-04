"""`prepare --published-disk-one --stage-place X,Y,F`: the party's square written into working DF0's loaded slot."""

from __future__ import annotations

import json
import pathlib

import pytest

from goldbox import amiga_adf, amiga_savegame
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
def test_a_place_out_of_range_is_blocked(place):
    with pytest.raises(staging.StageError, match="x and y are 0 to 15, facing 0 to 3"):
        staging.stage_place(_curse(), KEY, *place)


@pytest.mark.parametrize("data,why", [
    (_curse(indoors=0), "made outdoors"),
    (_curse(script=False), "has not set out"),
    (b"not a saved game", "not a readable"),
], ids=["outdoors", "not-set-out", "unknown"])
def test_an_outdoor_unset_or_unknown_save_is_blocked(data, why):
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
def test_a_blocked_place_makes_no_run_folder(tmp_path, monkeypatch, save, place, why):
    with pytest.raises(RouteError, match=why):
        _prepare(tmp_path, monkeypatch, save, place=place)
    assert not (tmp_path / "cache").exists()


def test_a_staged_df0_that_differs_by_more_than_the_place_is_blocked(tmp_path, monkeypatch):
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


def test_a_staged_manifest_whose_df0_is_the_published_image_is_blocked(tmp_path, monkeypatch):
    path, _report = _prepare(tmp_path, monkeypatch, _curse(), place=(6, 14, 0))
    manifest = json.loads(path.read_text())
    published = manifest["registered"]["published"]
    manifest["disks"]["df0"] = dict(published)
    path.write_text(json.dumps(manifest))
    with pytest.raises(RouteError):
        foundation._published_manifest(path, "curse")


def test_the_cli_blocks_a_bad_place_and_a_place_without_published_disk_one(tmp_path, capsys):
    for extra, why in ((["--published-disk-one", "--saveas-report", "x.json",
                          "--stage-place", "16,0,0"], "x and y are 0 to 15"),
                       (["--stage-place", "6,14,0"], "requires --published-disk-one"),
                       (["--published-disk-one", "--saveas-report", "x.json",
                         "--stage-place", "6,14"], "a place is X,Y,FACING")):
        foundation.main(["prepare", "--title", "curse", "--run-id", "r", *extra])
        assert why in capsys.readouterr().err


def _silver_blades() -> bytes:
    """The synthetic Silver Blades save, made a party that has set out in area 4."""
    container = amiga_savegame.SILVER_BLADES
    data = bytearray(synthetic_amiga.synthetic_silver_blades(("ALPHA",)))
    for address, value in ((0x49F2, 4), (0x49E6, 1), (0x49C5, 16), (0x4FE1, 255)):
        at = container.vm_offset(address)
        data[at:at + 2] = value.to_bytes(2, "big")
    return bytes(data)


def test_a_silver_blades_place_changes_one_byte_each_for_x_y_and_facing():
    data = _silver_blades()
    staged, change = staging.stage_place(data, "secret-of-the-silver-blades", 6, 14, 1)
    assert change == {"before": [7, 13, 0], "after": [6, 14, 1]}
    at = amiga_savegame.SILVER_BLADES.square_at
    assert [i for i in range(len(data)) if data[i] != staged[i]] == [at, at + 1, at + 2]
    assert list(staged[at:at + 3]) == [6, 14, 2]


def _staged(tmp_path, monkeypatch):
    path, _report = _prepare(tmp_path, monkeypatch, _curse(), place=(6, 14, 0))
    return path, json.loads(path.read_text())


def test_a_staged_df0_with_a_changed_free_sector_is_blocked(tmp_path, monkeypatch):
    path, manifest = _staged(tmp_path, monkeypatch)
    df0 = pathlib.Path(manifest["disks"]["df0"]["path"])
    image = AmigaDisk.open(df0)
    free = next(n for n in range(image.block_count - 1, 2, -1) if image.is_free(n))
    raw = bytearray(image.to_bytes())
    raw[free * 512] ^= 0xFF
    df0.write_bytes(bytes(raw))
    manifest["disks"]["df0"]["sha256"] = foundation.sha256(df0)
    path.write_text(json.dumps(manifest))
    with pytest.raises(RouteError, match="byte for byte"):
        foundation._published_manifest(path, "curse")


def test_the_staged_image_is_the_same_bytes_every_time_it_is_built(tmp_path, monkeypatch):
    _path, manifest = _staged(tmp_path, monkeypatch)
    published = AmigaDisk.open(manifest["registered"]["published"]["path"])
    built = AmigaDisk(published.to_bytes())
    staging.replace_file_in_place(
        built, "/save/savgamd.dat",
        staging.stage_place(published.read_file("/save/savgamd.dat"), KEY, 6, 14, 0)[0])
    assert built.to_bytes() == pathlib.Path(manifest["disks"]["df0"]["path"]).read_bytes()


def _fetched_after_a_run(manifest):
    """The fetched DF0 of a run: the loaded DF0 plus the game's two saves."""
    disk = AmigaDisk.open(manifest["disks"]["df0"]["path"])
    disk.write_file("/save/savgamC.dat", _curse())
    disk.write_file("/save/savgamF.dat", _curse())
    return disk


def test_a_staged_run_finds_the_published_files_preserved(tmp_path, monkeypatch):
    path, manifest = _staged(tmp_path, monkeypatch)
    _, title = foundation._published_manifest(path, "curse")
    fetched = _fetched_after_a_run(manifest)
    assert foundation._published_files_preserved(manifest, title, fetched) is True
    # The same disk against an unstaged manifest differs in the loaded slot, as a real change would.
    unstaged = {k: v for k, v in manifest.items() if k != "staged_place"}
    assert foundation._published_files_preserved(unstaged, title, fetched) is False


def test_a_staged_run_whose_loaded_slot_is_overwritten_is_not_preserved(tmp_path, monkeypatch):
    path, manifest = _staged(tmp_path, monkeypatch)
    _, title = foundation._published_manifest(path, "curse")
    fetched = _fetched_after_a_run(manifest)
    fetched.write_file("/save/savgamD.dat", _curse())
    assert foundation._published_files_preserved(manifest, title, fetched) is False


def test_the_preserved_specimen_says_the_loaded_slot_was_staged(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(foundation, "_register_fetched",
                        lambda *args: seen.append(args[3]) or {})
    run = tmp_path / "run1" / "prepare.json"
    staged = {"slot": "/save/savgamd.dat", "before": [3, 14, 1], "after": [6, 14, 0]}
    foundation._preserve_published(run, "accept1", "curse", tmp_path / "f.adf", "628", staged)
    foundation._preserve_published(run, "accept1", "curse", tmp_path / "f.adf", "628")
    assert "staged the loaded slot /save/savgamd.dat" in seen[0]
    assert "[3, 14, 1] to [6, 14, 0]" in seen[0]
    assert "staged" not in seen[1]


def test_an_in_place_overwrite_blocks_a_missing_path_and_a_drawer():
    disk = AmigaDisk(amiga_savegame.make_save_disk(KEY, "D", _curse()).to_bytes())
    with pytest.raises(staging.StageError, match="not on the disk"):
        staging.replace_file_in_place(disk, "/save/savgamZ.dat", b"x")
    with pytest.raises(staging.StageError, match="drawer"):
        staging.replace_file_in_place(disk, "/save", b"x")


def test_a_prepare_whose_slot_is_missing_is_a_route_error(tmp_path, monkeypatch):
    real = AmigaDisk.read_file

    def missing(self, path):
        if path == "/save/savgamd.dat" and getattr(missing, "on", False):
            raise amiga_adf.AmigaDiskError("no such file")
        return real(self, path)

    save = _curse()
    monkeypatch.setattr(AmigaDisk, "read_file", missing)
    monkeypatch.setattr(synthetic_amiga, "synthetic_curse", lambda names=(): save)
    report = _published_report(tmp_path, monkeypatch, "curse", "dos", names=CURSE_NAMES)
    missing.on = True
    with pytest.raises(RouteError, match="--stage-place"):
        foundation.prepare_published("curse", "staged", report, "628", place=(6, 14, 0))


def test_the_slack_after_the_files_end_is_zeroed_and_a_mutation_there_is_blocked(
        tmp_path, monkeypatch):
    path, manifest = _staged(tmp_path, monkeypatch)
    df0 = pathlib.Path(manifest["disks"]["df0"]["path"])
    image = AmigaDisk.open(df0)
    blocks = image._file_blocks(image.lookup("/save/savgamd.dat").block)
    last = blocks[-2]
    size = len(image.read_file("/save/savgamd.dat"))
    slack = size % 488
    assert slack, "the synthetic slot fills its last block exactly"
    raw = bytearray(image.to_bytes())
    at = last * 512 + 24 + slack
    assert raw[at:last * 512 + 512] == bytes(488 - slack)
    # Put the byte in the slack and keep the checksum right, so only the rebuild can see it.
    raw[at] = 0x5A
    image = AmigaDisk(bytes(raw))
    image._fix(last, 20)
    df0.write_bytes(image.to_bytes())
    manifest["disks"]["df0"]["sha256"] = foundation.sha256(df0)
    path.write_text(json.dumps(manifest))
    with pytest.raises(RouteError, match="byte for byte"):
        foundation._published_manifest(path, "curse")


def test_read_title_finds_a_staged_runs_published_files_preserved(tmp_path, monkeypatch):
    path, manifest = _staged(tmp_path, monkeypatch)
    _, title = foundation._published_manifest(path, "curse")
    out = tmp_path / "out"
    out.mkdir()
    _fetched_after_a_run(manifest).save(out / f"fetched-{title.save_disk}.adf")
    disks, registered, letter = foundation._title_inputs(manifest, title)
    result = {"fetched": {title.save_disk: {"sha256": "0" * 64}}, "error": "",
              "completed": True, "unguarded": []}
    foundation._read_title(title, manifest, result, out, disks, registered, {}, letter,
                           True, False, (), False)
    assert "fetched_save_error" not in result
    assert result["published_files_preserved"] is True
