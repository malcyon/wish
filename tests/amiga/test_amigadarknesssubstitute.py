"""`route_darkness._prepare_darkness` with a substitute slot, on disks composed here."""

from __future__ import annotations

import hashlib
import json

import pytest

from goldbox import amiga_savegame, dos_codec
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


def test_a_missing_source_slot_or_one_the_reader_rejects_is_blocked_and_writes_nothing():
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


def test_prepare_blocks_a_substitute_slot_the_reader_rejects(pinned):
    substitute = pinned / "sub.adf"
    _disk({"SavGamH.pty": _save(9, count=0)}).save(substitute)
    with pytest.raises(RouteError, match="could not be imported"):
        route_darkness._prepare_darkness(
            pinned / "run", None, "B", substitute=substitute, substitute_letter="H")
    with pytest.raises(RouteError, match="is missing"):
        route_darkness._prepare_darkness(
            pinned / "run2", None, "B", substitute=pinned / "none.adf")


#: A vault of two items and some coins, as the converter writes it.
_HELD = dos_codec.PodVault(1750, 495, 82, (bytes(63), bytes([1]) + bytes(62)))
_HELD_BYTES = amiga_savegame.pod_vault_to_amiga(_HELD)


def test_a_vault_prepare_copies_the_substitutes_vault_into_the_loaded_slot_and_records_it(pinned):
    substitute = pinned / "sub.adf"
    _disk({"SavGamH.pty": _save(9), "VaultH.DAT": _HELD_BYTES}).save(substitute)
    manifest = route_darkness._prepare_darkness(
        pinned / "run", None, "B", substitute=substitute, substitute_letter="H", vault=True)
    working = AmigaDisk.open(pinned / "run" / "disk3.adf")
    assert working.read_file("/Save/VaultB.DAT") == _HELD_BYTES
    assert manifest["vault"] == {"items": 2, "coins": [1750, 495, 82],
                                 "sha256": hashlib.sha256(_HELD_BYTES).hexdigest()}
    assert working.verify() == []
    json.dumps(manifest)


def test_a_vault_prepare_whose_staged_vault_is_empty_stops_before_any_disk_is_written(pinned):
    substitute = pinned / "sub.adf"
    empty = amiga_savegame.pod_vault_to_amiga(dos_codec.EMPTY_POD_VAULT)
    _disk({"SavGamH.pty": _save(9), "VaultH.DAT": empty}).save(substitute)
    with pytest.raises(RouteError, match="holds no items"):
        route_darkness._prepare_darkness(
            pinned / "run", None, "B", substitute=substitute, substitute_letter="H", vault=True)
    assert not (pinned / "run").exists()
    # With no substitute the pinned disk's own vault is the stub, which is as empty.
    with pytest.raises(RouteError, match="cannot be read|holds no items"):
        route_darkness._prepare_darkness(pinned / "run", None, "B", vault=True)
    assert not (pinned / "run").exists()


def test_a_vault_prepare_blocks_a_substitute_with_no_vault_file(pinned):
    substitute = pinned / "sub.adf"
    _disk({"SavGamH.pty": _save(9)}).save(substitute)
    with pytest.raises(RouteError, match="holds no vault H"):
        route_darkness._prepare_darkness(
            pinned / "run", None, "B", substitute=substitute, substitute_letter="H", vault=True)
    assert not (pinned / "run").exists()


def test_a_prepare_without_the_vault_switch_leaves_the_loaded_vault_and_records_none(pinned):
    substitute = pinned / "sub.adf"
    _disk({"SavGamH.pty": _save(9), "VaultH.DAT": _HELD_BYTES}).save(substitute)
    manifest = route_darkness._prepare_darkness(
        pinned / "run", None, "B", substitute=substitute, substitute_letter="H")
    assert AmigaDisk.open(pinned / "run" / "disk3.adf").read_file("/Save/VaultB.DAT") == b"v" * 12
    assert "vault" not in manifest


def test_the_vault_import_replaces_the_one_vault_and_keeps_its_name_case():
    dest = _disk({"SavGamB.pty": _save(2), "vaultB.dat": b"v" * 12, "VaultC.DAT": b"c" * 12})
    source = _disk({"VaultH.DAT": _HELD_BYTES})
    assert route_darkness._darkness_import_vault(dest, "B", source, "H") == _HELD_BYTES
    assert dest.read_file("/Save/vaultB.dat") == _HELD_BYTES
    assert dest.read_file("/Save/VaultC.DAT") == b"c" * 12
    assert {e.name for e in dest.entries(dest.lookup("/Save").block)} == {
        "SavGamB.pty", "vaultB.dat", "VaultC.DAT"}
