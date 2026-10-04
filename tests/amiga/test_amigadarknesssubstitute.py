"""`route_darkness._prepare_darkness` with a substitute slot, on disks composed here."""

from __future__ import annotations

import hashlib
import json

import pytest

from goldbox import amiga_savegame
from goldbox.amiga_adf import AmigaDisk
from tools.amiga import route_darkness
from tools.amiga.winuaesession import RouteError


def _save(x: int, count: int = 1) -> bytes:
    """A one-member saved game with an empty record, standing at column `x`."""
    data = bytearray(amiga_savegame.POD_SAVEGAME_SIZE)
    data[amiga_savegame.POD_COUNT_AT + 1] = count
    data[amiga_savegame.POD_SQUARE_AT] = x
    return bytes(data)


def _disk(files: dict[str, bytes]) -> AmigaDisk:
    disk = AmigaDisk.blank(route_darkness.DARKNESS_VOLUME)
    disk.make_dir("/Save")
    for name, data in files.items():
        disk.write_file(f"/Save/{name}", data)
    return disk


def _x(disk: AmigaDisk, letter: str) -> int:
    return amiga_savegame.pod_from_amiga(amiga_savegame.pod_read_slot(disk, letter)).x


def test_the_import_replaces_the_one_slot_and_nothing_else():
    dest = _disk({"SavGamA.pty": _save(1), "savgamB.PTY": _save(2), "VaultB.DAT": b"v" * 12})
    source = _disk({"SavGamH.pty": _save(9)})
    written = route_darkness._darkness_import_slot(dest, "B", source, "H")
    assert written == _save(9) and _x(dest, "B") == 9 and _x(dest, "A") == 1
    assert dest.read_file("/Save/VaultB.DAT") == b"v" * 12
    # The file keeps the name the disk gave it.
    names = {e.name for e in dest.entries(dest.lookup("/Save").block)}
    assert names == {"SavGamA.pty", "savgamB.PTY", "VaultB.DAT"}
    assert dest.verify() == []


def test_a_missing_source_slot_or_one_the_reader_rejects_is_refused_and_writes_nothing():
    dest = _disk({"SavGamB.pty": _save(2)})
    source = _disk({"SavGamH.pty": _save(9, count=0), "SavGamG.pty": b"short"})
    for letter in ("H", "G", "F"):
        with pytest.raises((amiga_savegame.AmigaSaveError, amiga_savegame.PodSaveError)):
            route_darkness._darkness_import_slot(dest, "B", source, letter)
    assert _x(dest, "B") == 2


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    """Disk 3 as the registered one for the run: `_find_images` hands back composed disks."""
    disk3 = _disk({"SavGamB.pty": _save(2), "VaultB.DAT": b"v" * 12}).to_bytes()
    images = {"disk1": ("d1", b"one"), "disk2": ("d2", b"two"), "disk3": ("d3", disk3)}
    for key, name in (("disk1", "DARKNESS_DISK1_SHA256"), ("disk2", "DARKNESS_DISK2_SHA256"),
                      ("disk3", "DARKNESS_DISK3_SHA256")):
        monkeypatch.setattr(route_darkness, name, hashlib.sha256(images[key][1]).hexdigest())
    monkeypatch.setattr(route_darkness, "_find_images",
                        lambda wanted: {k: images[k] for k in wanted})
    monkeypatch.setattr(route_darkness.scratch, "ensure", lambda path: path.mkdir(parents=True))
    return tmp_path


def test_prepare_with_a_substitute_records_it_and_the_substituted_party(pinned):
    substitute = pinned / "sub.adf"
    _disk({"SavGamH.pty": _save(9)}).save(substitute)
    manifest = route_darkness._prepare_darkness(
        pinned / "run", None, "B", substitute=substitute, substitute_letter="H")
    working = pinned / "run" / "disk3.adf"
    assert manifest["state_a"]["x"] == 9
    assert manifest["disks"]["disk3"]["sha256"] == hashlib.sha256(
        working.read_bytes()).hexdigest() != route_darkness.DARKNESS_DISK3_SHA256
    assert manifest["substitute"] == {
        "path": str(substitute), "sha256": hashlib.sha256(substitute.read_bytes()).hexdigest(),
        "letter": "H"}
    assert _x(AmigaDisk.open(working), "B") == 9
    json.dumps(manifest)


def test_prepare_without_a_substitute_keeps_the_pinned_disk_3_and_records_none(pinned):
    manifest = route_darkness._prepare_darkness(pinned / "run", None, "B")
    assert "substitute" not in manifest and manifest["state_a"]["x"] == 2
    assert manifest["disks"]["disk3"]["sha256"] == route_darkness.DARKNESS_DISK3_SHA256


def test_prepare_refuses_a_substitute_slot_the_reader_rejects(pinned):
    substitute = pinned / "sub.adf"
    _disk({"SavGamH.pty": _save(9, count=0)}).save(substitute)
    with pytest.raises(RouteError, match="could not be imported"):
        route_darkness._prepare_darkness(
            pinned / "run", None, "B", substitute=substitute, substitute_letter="H")
    with pytest.raises(RouteError, match="is missing"):
        route_darkness._prepare_darkness(
            pinned / "run2", None, "B", substitute=pinned / "none.adf")
