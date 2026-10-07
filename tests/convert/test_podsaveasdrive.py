"""`tools/convert/podsaveasdrive.py` writes a disk 3 and the report `prepare_published_disk_three` reads.

The synthetic tests stand in a fake Save As for the DOS slot, since a Pools of Darkness
slot is the player's data; the tests that run the editor's real Save As skip without the
registry and the specimen tree.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

import pytest
from conftest import load_tools_module

from editor import convert
from goldbox import amiga_savegame, dos_codec, dos_port, dos_savegame
from goldbox.amiga_adf import AmigaDisk

podsaveasdrive = load_tools_module("podsaveasdrive")

LETTER = "D"


def _synthetic_disk_three() -> AmigaDisk:
    disk = AmigaDisk.blank("POD 3")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    disk.make_dir("/DISK3")
    disk.write_file("/DISK3/GEN.TLB", b"\x03" * 600)
    return disk


def _specimen(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / f"SAVGAM{LETTER}.PTY"
    path.write_bytes(b"\x07" * 64)
    return path


def _fake_save_as(report=None):
    """Stands in for the editor's Save As: publishes disk 3 with a slot written onto it."""
    def save_as(specimen, disk3, folder, to, slot, edits):
        savegame = bytes(amiga_savegame.POD_SAVEGAME_SIZE)
        vault = amiga_savegame.pod_vault_to_amiga(dos_codec.EMPTY_POD_VAULT)
        disk = AmigaDisk(disk3.read_bytes())
        disk.write_file(amiga_savegame.pod_slot_path(LETTER), savegame)
        disk.write_file(amiga_savegame.pod_vault_path(LETTER), vault)
        published = folder / "wish-day" / "POOLSAVE.ADF"
        published.parent.mkdir(parents=True)
        published.write_bytes(disk.to_bytes())
        report_ = report or convert.neutral.Report()
        return {"written": [str(published)], "slot": LETTER, "destination": str(published),
                "dropped": [str(x) for x in report_.dropped],
                "losses": [str(x) for x in report_.losses],
                "warnings": [str(x) for x in report_.warnings]}
    return save_as


def _stop_with(error):
    def save_as(*args, **kwargs):
        raise error
    return save_as


@pytest.fixture
def staged(tmp_path, monkeypatch):
    specimen = _specimen(tmp_path)
    disk3 = tmp_path / "disk3.adf"
    disk3.write_bytes(_synthetic_disk_three().to_bytes())
    monkeypatch.setattr(podsaveasdrive, "_save_as", _fake_save_as())
    return specimen, disk3, tmp_path / "out"


def test_the_report_has_every_key_the_acceptance_prepare_reads(staged):
    specimen, disk3, out = staged
    report = podsaveasdrive.run(specimen, disk3, out)
    image = out / f"disk3-{LETTER}.adf"
    outcome = report["save_as"]
    assert not outcome.get("stopped")
    assert report["specimen"] == str(specimen)
    assert report["specimen_sha256"] == hashlib.sha256(specimen.read_bytes()).hexdigest()
    assert report["amiga_disk3"] == str(disk3)
    assert report["written"] == outcome["written"] == [str(image)]
    assert report["written_sha256"] == {
        image.name: hashlib.sha256(image.read_bytes()).hexdigest()}
    assert (outcome["to"], outcome["slot"], outcome["source"], outcome["destination"]) == (
        "amiga", LETTER, str(specimen), str(image))
    assert (report["dropped"], report["losses"], report["warnings"]) == ([], [], [])
    assert json.loads((out / "saveas-report.json").read_text()) == report


def test_the_image_is_the_disk_with_the_slot_written_and_the_input_untouched(staged):
    specimen, disk3, out = staged
    before = disk3.read_bytes()
    podsaveasdrive.run(specimen, disk3, out)
    written = AmigaDisk.open(out / f"disk3-{LETTER}.adf")
    assert written.read_file(amiga_savegame.pod_slot_path(LETTER))
    assert disk3.read_bytes() == before


def test_losses_dropped_and_warnings_are_reported_as_text(staged, monkeypatch):
    specimen, disk3, out = staged
    report = convert.neutral.Report()
    report.dropped.append("a dropped field")
    report.losses.append("a cut value")
    report.warnings.append("a note")
    monkeypatch.setattr(podsaveasdrive, "_save_as", _fake_save_as(report))
    got = podsaveasdrive.run(specimen, disk3, out)
    assert (got["dropped"], got["losses"], got["warnings"]) == (
        ["a dropped field"], ["a cut value"], ["a note"])
    assert got["save_as"]["dropped"] == ["a dropped field"]


def test_a_save_as_that_cannot_be_made_writes_a_stopped_report_and_no_image(
        staged, monkeypatch):
    specimen, disk3, out = staged
    monkeypatch.setattr(podsaveasdrive, "_save_as",
                        _stop_with(convert.ConvertError("slot D is held")))
    report = podsaveasdrive.run(specimen, disk3, out)
    assert report["save_as"]["stopped"] == ["ConvertError", "slot D is held"]
    assert report["written"] == []
    assert not list(out.glob("*.adf"))
    assert podsaveasdrive.main(
        ["--specimen", str(specimen), "--disk3", str(disk3), "--out", str(out)]) == 1


def test_the_destination_the_slot_and_the_edits_are_passed_to_save_as(staged, monkeypatch):
    specimen, disk3, out = staged
    seen = []
    inner = _fake_save_as()

    def spy(specimen_, disk3_, folder, to, slot, edits):
        seen.append((specimen_, disk3_, to, slot, edits is not None))
        return inner(specimen_, disk3_, folder, to, slot, edits)
    monkeypatch.setattr(podsaveasdrive, "_save_as", spy)
    podsaveasdrive.run(specimen, disk3, out)
    podsaveasdrive.run(specimen, disk3, out, slot="B", sets=("0:strength=17",))
    assert seen == [(specimen, disk3, "amiga", None, False),
                    (specimen, disk3, "amiga", "B", True)]


def test_commit_txt_holds_head_and_the_porcelain_status(staged, tmp_path):
    specimen, disk3, out = staged
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t",
                                  "commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "dirty.txt").write_text("x")
    podsaveasdrive.run(specimen, disk3, out, tree=repo)
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()
    assert (out / "commit.txt").read_text() == f"{head}\n?? dirty.txt\n"


def test_a_missing_input_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit):
        podsaveasdrive.main(["--specimen", str(tmp_path / "none"),
                             "--disk3", str(tmp_path / "none"), "--out", str(tmp_path)])


def test_the_registered_disk_three_takes_a_registered_dos_slot(tmp_path):
    """The real rehearsal on the registered disk 3 and a DOS slot the game wrote."""
    import gamedata

    from tools.amiga import amigasaves, route_darkness
    from tools.registry import specimens
    root = gamedata.specimen_root()
    folder = root / "pod-dos" / "WISH-SPEC-dos-pod-foundation-walked" if root else None
    if folder is None or not folder.is_dir():
        pytest.skip("needs the pod-dos specimen tree; see $WISH_SPECIMENS")
    for name, expected in specimens.read_provenance(
            folder / "provenance.toml").get("sha256", {}).items():
        assert specimens.sha256_file(folder / name) == expected
    for _label, data in amigasaves.images():
        if hashlib.sha256(data).hexdigest() == route_darkness.DARKNESS_DISK3_SHA256:
            break
    else:
        pytest.skip("needs the registered Pools of Darkness disk 3; set $AMIGA_DISKS")
    disk3 = tmp_path / "disk3.adf"
    disk3.write_bytes(data)
    specimen = sorted(folder.glob("SAVGAM?.PTY"))[0]
    report = podsaveasdrive.run(specimen, disk3, tmp_path / "out")
    assert not report["save_as"].get("stopped"), report
    assert (report["dropped"], report["losses"]) == ([], [])
    image = pathlib.Path(report["written"][0])
    assert AmigaDisk.open(image).read_file(
        amiga_savegame.pod_slot_path(report["save_as"]["slot"]))
    assert disk3.read_bytes() == data


def test_an_edited_item_quantity_converts_to_the_registered_disk_three(tmp_path, monkeypatch):
    """The load a quantity edit moves is the one Save As expects, on the real slot."""
    import gamedata

    from editor.roster import Party
    from tools.amiga import amigasaves, route_darkness
    root = gamedata.specimen_root()
    folder = root / "pod-dos" / "WISH-SPEC-pod-628-dos-lay-then-rest-1h" if root else None
    if folder is None or not folder.is_dir():
        pytest.skip("needs the pod-dos specimen tree; see $WISH_SPECIMENS")
    for _label, data in amigasaves.images():
        if hashlib.sha256(data).hexdigest() == route_darkness.DARKNESS_DISK3_SHA256:
            break
    else:
        pytest.skip("needs the registered Pools of Darkness disk 3; set $AMIGA_DISKS")
    disk3 = tmp_path / "disk3.adf"
    disk3.write_bytes(data)
    specimen = folder / "SAVGAMC.PTY"
    report = podsaveasdrive.run(specimen, disk3, tmp_path / "out", items=("0:0=3",))
    assert not report["save_as"].get("stopped"), report
    image = pathlib.Path(report["written"][0])
    monkeypatch.setenv("WISH_EXPERIMENTAL_POD_CONVERT", "1")
    party = Party(convert.Source.detect(image, slot="C"))
    assert party.members[0].inventory.item(0).quantity == 3


def test_the_vault_specimen_on_the_registered_disk_three_leaves_f_and_g_free(tmp_path):
    """Every shipped disk 3 holds a vault for A to H; only saved games take a letter.

    This pins the result; it does not prove the old code wrong, since the old parameter defaulted to empty.
    """
    import gamedata

    from tools.amiga import amigasaves, route_darkness
    root = gamedata.specimen_root()
    folder = root / "pod-dos" / "WISH-SPEC-pod-650-savgamb-walked-vault-dos" if root else None
    if folder is None or not folder.is_dir():
        pytest.skip("needs the pod-dos specimen tree; see $WISH_SPECIMENS")
    for _label, data in amigasaves.images():
        if hashlib.sha256(data).hexdigest() == route_darkness.DARKNESS_DISK3_SHA256:
            break
    else:
        pytest.skip("needs the registered Pools of Darkness disk 3; set $AMIGA_DISKS")
    disk3 = tmp_path / "disk3.adf"
    disk3.write_bytes(data)
    report = podsaveasdrive.run(folder / "SAVGAMD.PTY", disk3, tmp_path / "out")
    assert not report["save_as"].get("stopped"), report
    image = AmigaDisk.open(pathlib.Path(report["written"][0]))
    present = route_darkness.DARKNESS.slot_letters(image)
    assert route_darkness.published_letters(report["save_as"]["slot"], present)[:2] == ("F", "G")


@pytest.mark.parametrize("error", [
    dos_savegame.DosSaveError("short save"), dos_codec.WrongTitleError("wrong title", "x"),
    OSError("unreadable"), amiga_savegame.AmigaSaveError("bad slot")])
def test_any_reader_error_becomes_a_stopped_report(staged, monkeypatch, error):
    specimen, disk3, out = staged

    monkeypatch.setattr(podsaveasdrive, "_save_as", _stop_with(error))
    report = podsaveasdrive.run(specimen, disk3, out)
    assert report["save_as"]["stopped"][0] == type(error).__name__
    assert (out / "saveas-report.json").is_file() and (out / "commit.txt").is_file()
    assert not list(out.glob("*.adf"))


def test_a_wrong_size_saved_game_is_a_stopped_report(tmp_path, monkeypatch):
    folder = tmp_path / "slot"
    folder.mkdir()
    specimen = folder / f"SAVGAM{LETTER}.PTY"
    specimen.write_bytes(b"\x00" * 10)
    (folder / f"CHRDAT{LETTER}1.SAV").write_bytes(b"\x00" * 510)
    disk3 = tmp_path / "disk3.adf"
    disk3.write_bytes(_synthetic_disk_three().to_bytes())
    monkeypatch.setattr(
        convert.Source, "detect",
        classmethod(lambda cls, path, party=None, slot=None: convert.Source(
            port="dos", title=dos_port.POOLS_OF_DARKNESS, path=folder, slot=LETTER)))
    report = podsaveasdrive.run(specimen, disk3, tmp_path / "out")
    assert report["save_as"]["stopped"], report
    assert report["written"] == []


def test_an_image_from_an_earlier_run_is_removed(staged, monkeypatch):
    specimen, disk3, out = staged
    out.mkdir()
    (out / "disk3-A.adf").write_bytes(b"old")
    podsaveasdrive.run(specimen, disk3, out)
    assert [p.name for p in out.glob("disk3-*.adf")] == [f"disk3-{LETTER}.adf"]
    monkeypatch.setattr(podsaveasdrive, "_save_as", _stop_with(convert.ConvertError("x")))
    podsaveasdrive.run(specimen, disk3, out)
    assert not list(out.glob("*.adf"))


def test_paths_in_the_report_are_absolute(staged, monkeypatch):
    specimen, disk3, out = staged
    monkeypatch.chdir(specimen.parent)
    report = podsaveasdrive.run(pathlib.Path(specimen.name), pathlib.Path(disk3.name),
                                pathlib.Path("out"))
    paths = [report["specimen"], report["amiga_disk3"], report["written"][0],
             report["save_as"]["source"], report["save_as"]["destination"]]
    assert all(pathlib.Path(p).is_absolute() for p in paths)
    assert report["save_as"]["source"] == report["specimen"]


def test_out_holding_the_inputs_under_a_stale_name_does_not_delete_them(staged):
    specimen, disk3, out = staged
    folder = disk3.parent
    kept = folder / "disk3-input.adf"
    kept.write_bytes(disk3.read_bytes())
    (folder / "disk3-dir.adf").mkdir()
    (folder / "disk3-old.adf").write_bytes(b"old")
    report = podsaveasdrive.run(specimen, kept, folder)
    assert kept.is_file() and not (folder / "disk3-old.adf").exists()
    assert (folder / "disk3-dir.adf").is_dir()
    assert not report["save_as"].get("stopped"), report
    assert (folder / "saveas-report.json").is_file()


def test_an_unreadable_disk_three_is_a_stopped_report_with_a_traceback(
        tmp_path, monkeypatch, capsys):
    specimen = _specimen(tmp_path)
    monkeypatch.setattr(
        convert.Source, "detect",
        classmethod(lambda cls, path, party=None, slot=None: convert.Source(
            port="dos", title=dos_port.POOLS_OF_DARKNESS, path=pathlib.Path(path),
            slot=LETTER)))
    monkeypatch.setattr(podsaveasdrive, "_save_as", _fake_save_as())
    disk3 = tmp_path / "disk3.adf"
    disk3.mkdir()
    report = podsaveasdrive.run(specimen, disk3, tmp_path / "out")
    assert report["save_as"]["stopped"][0] in ("IsADirectoryError", "PermissionError")
    assert "Traceback" in capsys.readouterr().err
    assert not list((tmp_path / "out").glob("*.adf"))


def _stopped_without_image(report, out):
    assert report["save_as"]["stopped"], report
    assert report["written"] == []
    assert (out / "saveas-report.json").is_file()


def test_a_link_at_the_image_path_to_the_disk_three_is_not_written_through(staged):
    specimen, disk3, out = staged
    out.mkdir()
    before = disk3.read_bytes()
    (out / f"disk3-{LETTER}.adf").symlink_to(disk3)
    report = podsaveasdrive.run(specimen, disk3, out)
    _stopped_without_image(report, out)
    assert disk3.read_bytes() == before


def test_a_link_at_the_image_path_to_elsewhere_is_replaced_not_followed(staged, tmp_path):
    specimen, disk3, out = staged
    out.mkdir()
    other = tmp_path / "other.adf"
    other.write_bytes(b"keep")
    (out / f"disk3-{LETTER}.adf").symlink_to(other)
    report = podsaveasdrive.run(specimen, disk3, out)
    assert not report["save_as"].get("stopped"), report
    assert other.read_bytes() == b"keep"
    assert not (out / f"disk3-{LETTER}.adf").is_symlink()


def test_a_directory_at_the_image_path_is_a_stopped_report(staged):
    specimen, disk3, out = staged
    (out / f"disk3-{LETTER}.adf").mkdir(parents=True)
    _stopped_without_image(podsaveasdrive.run(specimen, disk3, out), out)


def test_the_disk_three_named_as_the_image_is_not_overwritten(staged):
    specimen, _disk3, out = staged
    out.mkdir()
    same = out / f"disk3-{LETTER}.adf"
    same.write_bytes(_synthetic_disk_three().to_bytes())
    before = same.read_bytes()
    _stopped_without_image(podsaveasdrive.run(specimen, same, out), out)
    assert same.read_bytes() == before
    assert not list(out.glob(".disk3-*"))


# The editor's real Save As, on the player's own specimens.

SLOT_C = "pod-dos/WISH-SPEC-pod-628-dos-lay-then-rest-1h/SAVGAMC.PTY"


def _registered_disk_three(tmp_path):
    from tools.amiga import amigasaves, route_darkness
    for _label, data in amigasaves.images():
        if hashlib.sha256(data).hexdigest() == route_darkness.DARKNESS_DISK3_SHA256:
            path = tmp_path / "disk3.adf"
            path.write_bytes(data)
            return path
    pytest.skip("needs the registered Pools of Darkness disk 3; set $AMIGA_DISKS")


def _slot_c(tmp_path):
    import gamedata
    root = gamedata.specimen_root()
    specimen = root / SLOT_C if root else None
    if specimen is None or not specimen.is_file():
        pytest.skip("needs the pod-dos specimen tree; see $WISH_SPECIMENS")
    return specimen, _registered_disk_three(tmp_path)


def _open_slot(path, slot):
    from editor.roster import Party
    with podsaveasdrive._pod_flag():
        return Party(convert.Source.detect(path, slot=slot))


def test_the_run_goes_through_the_editors_prepare_save_as(tmp_path, monkeypatch):
    from editor import saveplan
    specimen, disk3 = _slot_c(tmp_path)

    def stop(*args, **kwargs):
        raise RuntimeError("prepare_save_as was reached")
    monkeypatch.setattr(saveplan, "prepare_save_as", stop)
    report = podsaveasdrive.run(specimen, disk3, tmp_path / "out")
    assert report["save_as"]["stopped"] == ["RuntimeError", "prepare_save_as was reached"]
    assert report["written"] == []


def test_a_set_stat_reads_back_from_the_written_slot_and_the_others_are_unchanged(tmp_path):
    specimen, disk3 = _slot_c(tmp_path)
    before = _open_slot(specimen, "C")
    report = podsaveasdrive.run(specimen, disk3, tmp_path / "out", sets=("0:strength=17",))
    assert not report["save_as"].get("stopped"), report
    after = _open_slot(pathlib.Path(report["written"][0]), report["save_as"]["slot"])
    assert before.members[0].record.get("strength") != 17
    assert after.members[0].record.get("strength") == 17
    for old, new in zip(before.members[1:], after.members[1:], strict=True):
        assert new.record.get("strength") == old.record.get("strength")
    assert report["save_as"]["to"] == "amiga" and report["save_as"]["written"] == report["written"]


def test_an_item_edit_is_on_the_party_prepare_save_as_receives(tmp_path, monkeypatch):
    from editor import saveplan
    specimen, disk3 = _slot_c(tmp_path)
    seen = []
    inner = saveplan.prepare_save_as

    def spy(party, *args, **kwargs):
        seen.append(party.members[0].inventory.raws[1][10])
        return inner(party, *args, **kwargs)
    monkeypatch.setattr(saveplan, "prepare_save_as", spy)
    podsaveasdrive.run(specimen, disk3, tmp_path / "out", items=("0:1=5",))
    assert seen == [5]


def test_a_dos_destination_from_an_amiga_slot_writes_the_vault_with_its_items(tmp_path):
    from tools.amiga import amigasaves
    for _label, data in amigasaves.images():
        try:
            amiga_vault = amiga_savegame.pod_vault_from_amiga(
                AmigaDisk(data).read_file(amiga_savegame.pod_vault_path("H")))
        except Exception:
            continue
        if len(amiga_vault.items) == 40:
            break
    else:
        pytest.skip("needs an Amiga disk 3 whose slot H holds a vault of 40 items; set $AMIGA_DISKS")
    disk = tmp_path / "source.adf"
    disk.write_bytes(data)
    report = podsaveasdrive.run(disk, None, tmp_path / "out", to="dos", slot="H")
    assert not report["save_as"].get("stopped"), report
    written = {pathlib.Path(p).name: pathlib.Path(p) for p in report["written"]}
    letter = report["save_as"]["slot"]
    assert f"SAVGAM{letter}.PTY" in written
    vault_file = written[f"VAULT{letter}.DAT"]
    dos_vault = dos_codec.pod_vault_from_dos(vault_file.read_bytes())
    assert len(dos_vault.items) == 40
    assert dos_vault.platinum == amiga_vault.platinum == 1750
    assert report["written_sha256"][vault_file.name] == hashlib.sha256(
        vault_file.read_bytes()).hexdigest()


def test_an_edit_that_is_not_member_key_value_is_a_stopped_report(staged):
    specimen, disk3, out = staged
    report = podsaveasdrive.run(specimen, disk3, out, sets=("strength",))
    assert "MEMBER:KEY=VALUE" in report["save_as"]["stopped"][1]
    assert report["written"] == []
