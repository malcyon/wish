"""`tools/convert/podsaveasdrive.py` writes a disk 3 and the report `prepare_published_disk_three` reads.

The synthetic tests stand in a fake rehearsal for the DOS slot, since a Pools of Darkness
slot is the player's data; the smoke test runs the real rehearsal and skips without the
registry.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

import pytest
from conftest import load_tools_module

from editor import convert
from goldbox import amiga_savegame, dos_codec, dos_port
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


def _fake_rehearsal(report=None):
    """Stands in for `PodDosToAmiga.rehearse`: writes a slot onto the disk it is given."""
    def rehearse(self, source, slot, options, names=None, leave=None,
                 disk_three=None, replace=False):
        savegame = bytes(amiga_savegame.POD_SAVEGAME_SIZE)
        vault = amiga_savegame.pod_vault_to_amiga(dos_codec.EMPTY_POD_VAULT)
        disk = disk_three.copy() if hasattr(disk_three, "copy") else AmigaDisk(disk_three.to_bytes())
        disk.write_file(amiga_savegame.pod_slot_path(slot), savegame)
        disk.write_file(amiga_savegame.pod_vault_path(slot), vault)
        return convert.PodDosAmigaRehearsal(
            report or convert.neutral.Report(), {}, disk.to_bytes(), None, [], slot)
    return rehearse


@pytest.fixture
def staged(tmp_path, monkeypatch):
    specimen = _specimen(tmp_path)
    disk3 = tmp_path / "disk3.adf"
    disk3.write_bytes(_synthetic_disk_three().to_bytes())
    monkeypatch.setattr(
        convert.Source, "detect",
        classmethod(lambda cls, path, party=None, slot=None: convert.Source(
            port="dos", title=dos_port.POOLS_OF_DARKNESS, path=pathlib.Path(path),
            slot=LETTER)))
    monkeypatch.setattr(convert.PodDosToAmiga, "rehearse", _fake_rehearsal())
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
    monkeypatch.setattr(convert.PodDosToAmiga, "rehearse", _fake_rehearsal(report))
    got = podsaveasdrive.run(specimen, disk3, out)
    assert (got["dropped"], got["losses"], got["warnings"]) == (
        ["a dropped field"], ["a cut value"], ["a note"])
    assert got["save_as"]["dropped"] == ["a dropped field"]


def test_a_rehearsal_that_cannot_be_made_writes_a_stopped_report_and_no_image(
        staged, monkeypatch):
    specimen, disk3, out = staged

    def stop(self, *args, **kwargs):
        raise convert.ConvertError("slot D is held")
    monkeypatch.setattr(convert.PodDosToAmiga, "rehearse", stop)
    report = podsaveasdrive.run(specimen, disk3, out)
    assert report["save_as"]["stopped"] == ["ConvertError", "slot D is held"]
    assert report["written"] == []
    assert not list(out.glob("*.adf"))
    assert podsaveasdrive.main(
        ["--specimen", str(specimen), "--disk3", str(disk3), "--out", str(out)]) == 1


def test_replace_is_passed_through(staged, monkeypatch):
    specimen, disk3, out = staged
    seen = []
    inner = _fake_rehearsal()

    def spy(self, *args, **kwargs):
        seen.append(kwargs.get("replace"))
        return inner(self, *args, **kwargs)
    monkeypatch.setattr(convert.PodDosToAmiga, "rehearse", spy)
    podsaveasdrive.run(specimen, disk3, out)
    podsaveasdrive.run(specimen, disk3, out, replace=True)
    assert seen == [False, True]


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
    report = podsaveasdrive.run(specimen, disk3, tmp_path / "out", replace=True)
    assert not report["save_as"].get("stopped"), report
    assert (report["dropped"], report["losses"]) == ([], [])
    image = pathlib.Path(report["written"][0])
    assert AmigaDisk.open(image).read_file(
        amiga_savegame.pod_slot_path(report["save_as"]["slot"]))
    assert disk3.read_bytes() == data
