"""The bounded Return intervention on private media and a relocated fake script."""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from goldbox import amiga_adf
from tools.amiga import darknessreturn as driver
from tools.amiga import noencounters, route_darkness
from tools.amiga.staging import sha256
from tools.amiga.winuaesession import RouteError


def _source() -> pathlib.Path:
    if not driver.SOURCE.is_file():
        pytest.skip("the player's WISH-338 prepared save is unavailable")
    return driver.SOURCE


def _prepared(tmp_path: pathlib.Path) -> pathlib.Path:
    source = _source()
    if sha256(source) != driver.SOURCE_HASH:
        pytest.skip("the player's WISH-338 prepared save has another hash")
    manifest = route_darkness._prepare_darkness(
        tmp_path / "prepared", None, "B", substitute=source, substitute_letter="G")
    path = tmp_path / "prepared" / "prepare.json"
    path.write_text(json.dumps(manifest))
    return path


def _patched(tmp_path: pathlib.Path) -> tuple[pathlib.Path, dict]:
    path = driver.prepare_media(_source(), tmp_path / "intervention", _prepared(tmp_path))
    manifest = json.loads(path.read_text())
    return path, manifest


def test_private_disk_patch_and_restoration_preserve_game_written_f(tmp_path):
    path, manifest = _patched(tmp_path)
    media = manifest["encounter_media"]
    original = amiga_adf.AmigaDisk.open(media["prepared_image"])
    patched = amiga_adf.AmigaDisk.open(manifest["disks"]["disk3"]["path"])
    before = original.read_file(driver.LIBRARY)
    after = patched.read_file(driver.LIBRARY)
    assert before[:driver.OFFSET] == after[:driver.OFFSET]
    assert before[driver.OFFSET + 1:] == after[driver.OFFSET + 1:]
    assert before[driver.OFFSET] == 8 and after[driver.OFFSET] == 9
    assert sha256(pathlib.Path(media["prepared_image"])) == media["before_image_sha256"]
    assert path.is_file()

    fetched = amiga_adf.AmigaDisk.open(manifest["disks"]["disk3"]["path"])
    payload = b"Generated save marker for the restoration test"
    fetched.write_file("/SAVE/savgamF.pty", payload)
    raw = tmp_path / "fetched-disk3.adf"
    fetched.save(raw)
    restored = tmp_path / "restored-disk3.adf"
    proof = driver.restore_fetched(raw, media, restored)
    disk = amiga_adf.AmigaDisk.open(restored)
    assert disk.verify() == []
    assert disk.read_file(driver.LIBRARY) == before
    assert disk.read_file("/SAVE/savgamF.pty") == payload
    assert proof["raw"]["sha256"] != proof["restored"]["sha256"]
    assert proof["slot_f_sha256"] == hashlib.sha256(payload).hexdigest()


def test_wrong_fetched_library_cannot_produce_reload_seed(tmp_path):
    _, manifest = _patched(tmp_path)
    media = manifest["encounter_media"]
    fetched = amiga_adf.AmigaDisk.open(manifest["disks"]["disk3"]["path"])
    library = bytearray(fetched.read_file(driver.LIBRARY))
    library[driver.OFFSET + 1] ^= 1
    fetched.write_file(driver.LIBRARY, bytes(library))
    raw = tmp_path / "bad.adf"
    fetched.save(raw)
    out = tmp_path / "restored.adf"
    with pytest.raises(RouteError, match="fetched library differs"):
        driver.restore_fetched(raw, media, out, require_f=False)
    assert not out.exists()


class Memory:
    """The current area script and its data-hunk pointer in Amiga slow memory."""

    def __init__(self, statement: bytes, area: bytes):
        self.data_base = 0xC00000
        self.anchor_base = self.data_base
        self.memory = ((self.data_base, 0x80000),)
        self.bytes = bytearray(0x80000)
        self.buffer = 0xC10000
        self.point(self.buffer)
        self.load(statement, area)

    def point(self, address):
        self.write(self.data_base + 0x6EA6, address.to_bytes(4, "big"))
        self.buffer = address

    def load(self, statement, area):
        self.write(self.buffer + 0x8000, area)
        self.write(self.buffer + 0x8BC7, statement)

    def read(self, address, count):
        offset = address - self.data_base
        assert 0 <= offset and offset + count <= len(self.bytes)
        return bytes(self.bytes[offset:offset + count])

    def read_blocks(self, blocks):
        return [self.read(address, count) for address, count in blocks]

    def write(self, address, data):
        offset = address - self.data_base
        assert 0 <= offset and offset + len(data) <= len(self.bytes)
        self.bytes[offset:offset + len(data)] = data


class Lane:
    def __init__(self):
        self.owned = True
        self.checked = 0

    def lane(self, holder, timeout):
        assert holder == "proof" and self.owned
        self.checked += 1
        return 1


def _live_gate(tmp_path, monkeypatch):
    _, manifest = _patched(tmp_path)
    library = amiga_adf.AmigaDisk.open(
        manifest["encounter_media"]["prepared_image"]).read_file(driver.LIBRARY)
    original = driver._row_from_library(library, 8)
    area = noencounters.digest
    script = library
    from goldbox.amiga_savegame import area_script  # noqa: PLC0415
    entries = area_script(script, driver.AREA)[:noencounters.ENTRY_TABLE]
    assert area(entries) == driver.AREA_DIGEST
    memory = Memory(b"\x09" + original[1:], entries)
    lane = Lane()
    state = noencounters.WinuaeState(tmp_path / "holder.json")
    row = driver._gate_row()
    monkeypatch.setattr(noencounters, "rows_for", lambda title: [row] if title == driver.TITLE else [])
    return memory, lane, state, original, entries


def test_media_gate_survives_reload_and_is_restored_before_save_and_release(tmp_path, monkeypatch):
    memory, lane, state, original, entries = _live_gate(tmp_path, monkeypatch)
    first = driver.adopt_loaded_media("proof", memory, state, original, lane)
    assert first["address"] == 0xC18BC7 and state.load()["on"]
    memory.point(0xC20000)
    memory.load(b"\x09" + original[1:], entries)
    second = driver.adopt_loaded_media("proof", memory, state, original, lane)
    assert second["address"] == 0xC28BC7
    assert state.load()["rows"][-1]["address"] == second["address"]
    assert memory.read(second["address"], 1) == b"\x09"
    # A save key is blocked while the reloaded row remains changed.
    switch = noencounters.WinuaeEncounters(driver.TITLE, memory, state=state,
                                          lane_check=lambda: lane.lane("proof", 30))
    assert switch.keys(["S"])["pressed"] == []
    restored = driver.restore_loaded_media("proof", memory, state, original, lane)
    assert restored["statement_digest"] == driver.ROW_DIGEST
    assert driver._original_live(memory, original)["area_digest"] == driver.AREA_DIGEST
    assert memory.read(second["address"], 6) == original
    assert not state.load()["on"] and state.load()["rows"] == []
    lane.owned = False
    assert lane.checked >= 3


@pytest.mark.parametrize("damage", ["wrong statement", "wrong area", "lost pointer"])
def test_media_adoption_blocks_wrong_loaded_gate(tmp_path, monkeypatch, damage):
    memory, lane, state, original, entries = _live_gate(tmp_path, monkeypatch)
    if damage == "wrong statement":
        memory.write(memory.buffer + 0x8BC7, b"\x01")
    elif damage == "wrong area":
        memory.write(memory.buffer + 0x8000, b"\x00")
    else:
        memory.point(0)
    with pytest.raises(RouteError):
        driver.adopt_loaded_media("proof", memory, state, original, lane)
    assert not state.load()["on"] and not state.load()["rows"]


def test_failed_p2_receipt_cannot_start_reload(tmp_path):
    receipt = {"success": True, "checks": {"legs": True, "step": True, "save": True,
                                           "ram_restored": True, "disk_restored": False,
                                           "source_unchanged": True}}
    with pytest.raises(RouteError, match="failed or missing"):
        driver._restored_source(receipt)
