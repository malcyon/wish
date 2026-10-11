"""The bounded Return intervention on private media and a relocated fake script."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import stat
import struct
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from goldbox import amiga_adf, amiga_savegame, dos_savegame
from tools.amiga import darknessreturn as driver
from tools.amiga import noencounters, route_darkness
from tools.amiga.staging import sha256
from tools.amiga.winuaesession import RouteError


def _synthetic_private_files(monkeypatch, root):
    """Model POSIX metadata only for generated files in source behavior tests."""
    if os.name == "posix":
        return pathlib.Path

    class PrivateStat:
        def __init__(self, actual):
            self.actual = actual
            self.st_uid = 1729
            self.st_mode = (stat.S_IFMT(actual.st_mode)
                            | (0o700 if stat.S_ISDIR(actual.st_mode) else 0o600))

        def __getattr__(self, field):
            return getattr(self.actual, field)

    class PrivatePath(type(pathlib.Path())):
        def stat(self, *args, **kwargs):
            actual = super().stat(*args, **kwargs)
            return PrivateStat(actual) if self.is_relative_to(root) else actual

    class PrivateOS:
        name = "posix"

        @staticmethod
        def getuid():
            return 1729

        def __getattr__(self, field):
            return getattr(os, field)

    class PrivatePaths:
        Path = PrivatePath

        def __getattr__(self, field):
            return getattr(pathlib, field)

    monkeypatch.setattr(driver, "os", PrivateOS())
    monkeypatch.setattr(driver, "pathlib", PrivatePaths())
    return PrivatePath


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


@pytest.mark.parametrize("damage", ["stopped", "wrong opcode"])
def test_reload_step_requires_applied_area17_gate(tmp_path, monkeypatch, damage):
    memory, lane, state, original, entries = _live_gate(tmp_path, monkeypatch)
    if damage == "wrong opcode":
        memory.load(original, entries)
    switch = noencounters.WinuaeEncounters(driver.TITLE, memory, state=state,
                                          lane_check=lambda: lane.lane("proof", 30))
    reply = switch.on()
    assert state.load()["on"]
    if damage == "wrong opcode":
        assert any(row.get("new") == "09" for row in reply["rows"])
        memory.write(memory.buffer + 0x8BC7, b"\x01")
    else:
        assert any(row.get("stopped") for row in reply["rows"])
    with pytest.raises(RouteError, match="reload area-17 gate"):
        driver._verified_reload_gate(memory, state, original, reply)


def test_reload_step_accepts_applied_area17_gate(tmp_path, monkeypatch):
    memory, lane, state, original, entries = _live_gate(tmp_path, monkeypatch)
    memory.load(original, entries)
    switch = noencounters.WinuaeEncounters(driver.TITLE, memory, state=state,
                                          lane_check=lambda: lane.lane("proof", 30))
    proof = driver._verified_reload_gate(memory, state, original, switch.on())
    assert proof["address"] == memory.buffer + 0x8BC7
    assert proof["statement_digest"] == noencounters.digest(b"\x09" + original[1:])
    assert proof["area_digest"] == driver.AREA_DIGEST


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


def _synthetic_members(*, name="TURBO K", slot=0, count=5, short=False):
    nodes = tuple(SimpleNamespace(address=0xC10000 + i * 0x42,
                                  raw=bytes((i * 17 + n) % 256 for n in range(
                                      65 if short and i == 4 else 66))) for i in range(count))
    member = SimpleNamespace(name=name, slot=slot, hp=12, hp_max=20,
                             item_nodes=nodes, items=lambda: tuple((n.address, n.raw) for n in nodes),
                             effects=lambda: ())
    return (member,)


def _synthetic_f(*, damage=None):
    """Build a six-member saved slot from the documented container layout."""
    names = [f"WHO{number}" for number in range(6)]
    data = bytearray(amiga_savegame.POD_SAVEGAME_SIZE)
    for variable, value in ((dos_savegame.POD_PARTY_COUNT, 6),
                            (dos_savegame.POD_WILDERNESS_X, 22),
                            (dos_savegame.POD_WILDERNESS_Y, 3), (0x129, 2)):
        data[variable - 1] = value
    data[amiga_savegame.POD_SQUARE_AT:amiga_savegame.POD_SQUARE_AT + 6] = bytes((7, 15, 0, 0, 0, 0))
    data[amiga_savegame.POD_PREVIOUS_MODE_AT] = dos_savegame.POD_MODE_WILDERNESS
    data[amiga_savegame.POD_MODE_AT] = 2
    struct.pack_into(">H", data, amiga_savegame.POD_COUNT_AT, len(names))
    for index, name in enumerate(names):
        at = (amiga_savegame.POD_PARTY_AT + index * amiga_savegame.POD_RECORD_BYTES
              + amiga_savegame.POD_NAME_AT)
        data[at:at + len(name)] = name.encode("ascii")
    if damage == "wrong-name":
        data[amiga_savegame.POD_PARTY_AT + amiga_savegame.POD_NAME_AT] = ord("X")
    elif damage == "wrong-cell":
        data[dos_savegame.POD_WILDERNESS_X - 1] = 21
    elif damage == "wrong-square":
        data[amiga_savegame.POD_SQUARE_AT] = 8
    elif damage == "wrong-facing":
        data[amiga_savegame.POD_SQUARE_AT + 2] = dos_savegame.FACING_SCALE
    elif damage == "wrong-flag":
        data[0x129 - 1] = 0
    elif damage == "dungeon":
        data[dos_savegame.POD_IN_DUNGEON - 1] = 1
    elif damage == "short":
        return bytes(data[:-1])
    return bytes(data)


def test_live_capture_uses_one_read_and_matches_ordinary_hashes(tmp_path, monkeypatch):
    members = _synthetic_members()
    calls = []
    monkeypatch.setattr(driver.amigaparty, "read_party", lambda target: (calls.append(target), members)[1])
    monkeypatch.setattr(driver.fasttravelrun, "_reading", lambda *args: {})
    monkeypatch.setattr(driver.amigavars, "read_variables", lambda *args: [])
    path = tmp_path / "nodes.json"
    original_open = os.open
    requested = []

    def capture_open(file, flags, mode=0o777):
        requested.append((flags, mode))
        return original_open(file, flags, mode)

    monkeypatch.setattr(driver.os, "open", capture_open)
    reading = driver._live_read(object(), capture=path)
    assert len(calls) == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == reading["capture"]["file_sha256"]
    assert len(requested) == 1
    assert requested[0][0] & (os.O_CREAT | os.O_EXCL) == os.O_CREAT | os.O_EXCL
    assert requested[0][1] == 0o600
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
    items = json.loads(path.read_text())["items"]
    assert [item["chain_index"] for item in items] == list(range(5))
    assert [item["address"] for item in items] == [n.address for n in members[0].item_nodes]
    assert items[0]["raw_hex"] != items[1]["raw_hex"]
    for item in items:
        raw = bytes.fromhex(item["raw_hex"])
        assert len(raw) == item["length"] == 0x42
        assert (item["name"], item["slot"]) == ("TURBO K", 0)
        assert item["sha256"] == reading["party"][0]["items"][item["chain_index"]]
        assert item["tail20_sha256"] == hashlib.sha256(raw[0x2e:0x42]).hexdigest()


@pytest.mark.parametrize("member", [None, _synthetic_members(name="OTHER"),
                                    _synthetic_members(slot=1), _synthetic_members(count=4),
                                    _synthetic_members(short=True)])
def test_capture_blocks_missing_identity_or_nodes(tmp_path, monkeypatch, member):
    monkeypatch.setattr(driver.amigaparty, "read_party", lambda target: member)
    monkeypatch.setattr(driver.fasttravelrun, "_reading", lambda *args: {})
    monkeypatch.setattr(driver.amigavars, "read_variables", lambda *args: [])
    path = tmp_path / "nodes.json"
    with pytest.raises(RouteError):
        driver._live_read(object(), capture=path)
    assert not path.exists()


def _comparison_fixture(tmp_path, *, bundle=False):
    """Generate two members, relocated valid links and a parsed synthetic F."""
    groups = []
    for slot, (name, count) in enumerate((("TURBO K", 5), ("WHO1", 2))):
        tails = []
        for index in range(count):
            tail = bytearray(20)
            tail[0] = 0x49 if bundle and slot == 1 and index == 0 else 0x12
            tail[1], tail[13], tail[16] = 7 + index, 11 + index, 19 + index
            tails.append(bytes(tail))
        groups.append((slot, name, tails))
    saved = bytearray(amiga_savegame.POD_SAVEGAME_SIZE)
    struct.pack_into(">H", saved, amiga_savegame.POD_COUNT_AT, 2)
    at = amiga_savegame.POD_PARTY_AT
    for slot, name, tails in groups:
        saved[at + amiga_savegame.POD_NAME_AT:at + amiga_savegame.POD_NAME_AT + len(name)] = name.encode()
        struct.pack_into(">I", saved, at + amiga_savegame.POD_ITEM_COUNT_AT, len(tails))
        at += amiga_savegame.POD_RECORD_BYTES
        for tail in tails:
            saved[at:at + 20] = tail
            at += 20
    assert amiga_savegame.pod_parse(bytes(saved)).characters[1].name == "WHO1"
    disk = SimpleNamespace(read_file=lambda name: bytes(saved))
    root = tmp_path / "captures"
    root.mkdir()
    entries = []
    readings = []
    for phase in range(2):
        members = []
        for slot, name, tails in groups:
            nodes = []
            for index, tail in enumerate(tails):
                address = 0xC10000 + phase * 0x1000 + slot * 0x200 + index * 0x46
                following = address + 0x46 if index + 1 < len(tails) else 0
                raw = bytearray(66)
                raw[0] = phase + 1
                raw[0x2a:0x2e] = following.to_bytes(4, "big")
                raw[0x2e:0x42] = tail
                nodes.append(SimpleNamespace(address=address, raw=bytes(raw)))
            members.append(SimpleNamespace(slot=slot, name=name, item_nodes=nodes,
                                            items=lambda nodes=nodes: tuple(
                                                (n.address, n.raw) for n in nodes),
                                            effects=lambda: (), hp=1, hp_max=1))
        reading = {"party": [{"slot": m.slot, "name": m.name,
                              "items": [hashlib.sha256(n.raw).hexdigest()
                                        for n in m.item_nodes]} for m in members]}
        path = root / f"{phase}.json"
        proof = driver._capture_nodes(path, tuple(members), reading)
        entries.append({"path": path.name, **proof})
        readings.append(reading)
    return root, entries, readings, disk


def test_comparison_classifies_display_and_relocated_links_without_losing_saved_bytes(tmp_path):
    root, entries, readings, disk = _comparison_fixture(tmp_path)
    report = driver._compare_nodes(entries[0], readings[0], entries[1], readings[1], disk, root)
    assert len(report["items"]) == 7 and report["all_payloads_match_f"]
    assert not report["full_match"] and not report["bundle_inventory_incomplete"]
    assert report["items"][0]["display_offsets"] == [0]
    assert report["items"][0]["link_offsets"] == [0x2c]
    assert not report["items"][0]["payload_offsets"]
    assert "raw_hex" not in json.dumps(report)
    assert report["evidence_status"] == "captured_metadata_differs"
    assert report["provenance"] == "receipt_artifact_consistency_only"
    assert report["independently_authenticated"] is False
    assert report["preservation_established"] is False


def test_coordinated_capture_receipt_hashes_and_f_still_do_not_prove_preservation(tmp_path):
    root, entries, readings, disk = _comparison_fixture(tmp_path)
    saved = bytearray(disk.read_file("F"))
    at = amiga_savegame.POD_PARTY_AT + amiga_savegame.POD_RECORD_BYTES + 1
    saved[at] ^= 1
    for phase in range(2):
        path = root / f"{phase}.json"
        artifact = json.loads(path.read_text())
        record = artifact["items"][0]
        raw = bytearray.fromhex(record["raw_hex"])
        raw[0x2f] ^= 1
        record["raw_hex"] = raw.hex()
        record["sha256"] = hashlib.sha256(raw).hexdigest()
        record["tail20_sha256"] = hashlib.sha256(raw[0x2e:0x42]).hexdigest()
        readings[phase]["party"][0]["items"][0] = record["sha256"]
        path.write_text(json.dumps(artifact))
        entries[phase]["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = driver._compare_nodes(entries[0], readings[0], entries[1], readings[1],
                                   SimpleNamespace(read_file=lambda name: bytes(saved)), root)
    assert report["all_payloads_match_f"] and not report["bundle_inventory_incomplete"]
    assert report["evidence_status"] == "captured_metadata_differs"
    assert report["provenance"] == "receipt_artifact_consistency_only"
    assert report["independently_authenticated"] is False
    assert report["preservation_established"] is False


def test_equal_capture_heads_remain_unauthenticated_and_unproved(tmp_path):
    root, entries, readings, disk = _comparison_fixture(tmp_path)
    first = (root / "0.json").read_bytes()
    (root / "1.json").write_bytes(first)
    entries[1]["file_sha256"] = entries[0]["file_sha256"]
    readings[1] = readings[0]
    report = driver._compare_nodes(entries[0], readings[0], entries[1], readings[1], disk, root)
    assert report["full_match"] and report["evidence_status"] == "captured_heads_equal"
    assert report["provenance"] == "receipt_artifact_consistency_only"
    assert report["independently_authenticated"] is False
    assert report["preservation_established"] is False


@pytest.mark.parametrize("damage", ["missing", "short", "hash", "identity", "link"])
def test_comparison_fails_closed_on_damaged_private_capture(tmp_path, damage):
    root, entries, readings, disk = _comparison_fixture(tmp_path)
    path = root / "1.json"
    if damage == "missing":
        path.unlink()
    else:
        payload = json.loads(path.read_text())
        node = payload["items"][-1]
        if damage == "short":
            node["raw_hex"] = node["raw_hex"][:-2]
        elif damage == "hash":
            node["sha256"] = "0" * 64
        elif damage == "identity":
            node["name"] = "OTHER"
        else:
            node = payload["items"][0]
            raw = bytearray.fromhex(node["raw_hex"])
            raw[0x2d] = 1
            node["raw_hex"] = raw.hex()
            node["sha256"] = hashlib.sha256(raw).hexdigest()
            readings[1]["party"][0]["items"][0] = node["sha256"]
        path.write_text(json.dumps(payload))
        entries[1]["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(RouteError):
        driver._compare_nodes(entries[0], readings[0], entries[1], readings[1], disk, root)


@pytest.mark.parametrize("offset", [0x2f, 0x3b, 0x3e, 0x40])
def test_saved_payload_difference_never_matches_f(tmp_path, offset):
    root, entries, readings, disk = _comparison_fixture(tmp_path)
    path = root / "1.json"
    payload = json.loads(path.read_text())
    node = payload["items"][0]
    raw = bytearray.fromhex(node["raw_hex"])
    raw[offset] ^= 1
    node["raw_hex"] = raw.hex()
    node["sha256"] = hashlib.sha256(raw).hexdigest()
    node["tail20_sha256"] = hashlib.sha256(raw[0x2e:0x42]).hexdigest()
    readings[1]["party"][0]["items"][0] = node["sha256"]
    path.write_text(json.dumps(payload))
    entries[1]["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = driver._compare_nodes(entries[0], readings[0], entries[1], readings[1], disk, root)
    assert not report["all_payloads_match_f"] and not report["full_match"]
    assert offset in report["items"][0]["payload_offsets"]
    assert report["evidence_status"] == "payload_mismatch"
    assert report["preservation_established"] is False


def test_bundle_head_never_claims_complete_inventory(tmp_path):
    root, entries, readings, disk = _comparison_fixture(tmp_path, bundle=True)
    report = driver._compare_nodes(entries[0], readings[0], entries[1], readings[1], disk, root)
    assert report["bundle_inventory_incomplete"] and not report["full_match"]
    assert report["evidence_status"] == "bundle_inventory_incomplete"
    assert report["preservation_established"] is False


class _BundleMemory:
    """Generated Exec MemHeader and separately allocated item nodes."""

    def __init__(self, heads, children):
        self.memory = ((0, driver.amiga.EXEC_PAGE),)
        self.bytes = bytearray(driver.amiga.EXEC_PAGE)
        self.put(0x1000 + driver.amiga.EXEC_CHK_BASE,
                 (~0x1000 & 0xffffffff).to_bytes(4, "big"))
        self.put(0x1000 + driver.amiga.EXEC_MEM_LIST, (0x1100).to_bytes(4, "big"))
        self.put(0x1100, (0x1000 + driver.amiga.EXEC_MEM_LIST + 4).to_bytes(4, "big"))
        self.put(0x1100 + driver.amiga.MEM_LOWER, (0).to_bytes(4, "big"))
        self.put(0x1100 + driver.amiga.MEM_UPPER, driver.amiga.EXEC_PAGE.to_bytes(4, "big"))
        self.bytes[driver.amiga.EXEC_BASE_AT:driver.amiga.EXEC_BASE_AT + 4] = (
            0x1000).to_bytes(4, "big")
        for address, raw in heads + children:
            self.put(address, raw)

    def put(self, address, raw):
        self.bytes[address:address + len(raw)] = raw

    def read(self, address, count):
        return bytes(self.bytes[address:address + count])


def test_public_live_read_captures_full_bundle_head_without_f(tmp_path, monkeypatch):
    heads, nodes = [], []
    for index in range(5):
        address = 0x2000 + index * 0x100
        full = bytearray(70)
        full[0x2e] = 0x49 if index == 0 else 0x12
        full[0x3a] = 0
        heads.append((address, bytes(full)))
        nodes.append(SimpleNamespace(address=address, raw=bytes(full[:66])))
    member = SimpleNamespace(slot=0, name="TURBO K", item_nodes=tuple(nodes), hp=1, hp_max=1,
                             items=lambda: tuple((n.address, n.raw) for n in nodes),
                             effects=lambda: ())
    calls = []
    monkeypatch.setattr(driver.amigaparty, "read_party", lambda target: (
        calls.append(target), (member,))[1])
    monkeypatch.setattr(driver.fasttravelrun, "_reading", lambda *args: {})
    monkeypatch.setattr(driver.amigavars, "read_variables", lambda *args: [])
    path = tmp_path / "full-head.json"
    target = _BundleMemory(heads, [])
    reading = driver._live_read(target, capture=path)
    artifact = json.loads(path.read_text())
    assert calls == [target]
    assert reading["capture"]["bundle_coverage"] == "complete"
    assert len(artifact["items"]) == 5
    assert len(bytes.fromhex(artifact["bundle"]["nodes"][0]["raw_hex"])) == 70
    assert artifact["bundle"]["nodes"][0]["children"] == []


def _bundled_fixture(tmp_path):
    saved = bytearray(amiga_savegame.POD_SAVEGAME_SIZE)
    struct.pack_into(">H", saved, amiga_savegame.POD_COUNT_AT, 1)
    name = b"TURBO K"
    at = amiga_savegame.POD_PARTY_AT
    saved[at + amiga_savegame.POD_NAME_AT:at + amiga_savegame.POD_NAME_AT + len(name)] = name
    struct.pack_into(">I", saved, at + amiga_savegame.POD_ITEM_COUNT_AT, 5)
    tails = [bytearray(20) for _ in range(5)]
    for index, tail in enumerate(tails):
        tail[0], tail[1], tail[13], tail[16] = 0x12, index + 3, index + 7, index + 11
    tails[1][0], tails[1][0x0c] = 0x49, 2
    child_tails = [bytes([0x32 + i, 9 + i, *range(2, 20)]) for i in range(2)]
    cursor = at + amiga_savegame.POD_RECORD_BYTES
    for index, tail in enumerate(tails):
        saved[cursor:cursor + 20] = tail
        cursor += 20
        if index == 1:
            for child in child_tails:
                saved[cursor:cursor + 20] = child
                cursor += 20
    disk = SimpleNamespace(read_file=lambda name: bytes(saved))
    root = tmp_path / "bundles"
    root.mkdir()
    entries, readings = [], []
    for phase in range(2):
        base = 0x2000 + phase * 0x1000
        heads, children, nodes = [], [], []
        for index, tail in enumerate(tails):
            address = base + index * 0x100
            full = bytearray(70)
            full[0] = phase + 1
            full[0x2a:0x2e] = (base + (index + 1) * 0x100 if index < 4 else 0).to_bytes(4, "big")
            full[0x2e:0x42] = tail
            if index == 1:
                full[0x42:0x46] = (base + 0x700).to_bytes(4, "big")
            heads.append((address, bytes(full)))
            nodes.append(SimpleNamespace(address=address, raw=bytes(full[:66])))
        for ordinal, tail in enumerate(child_tails):
            address = base + 0x700 + ordinal * 0x100
            full = bytearray(70)
            full[0x2a:0x2e] = (0x55667788).to_bytes(4, "big")  # Stale JOIN metadata.
            full[0x2e:0x42] = tail
            full[0x42:0x46] = (address + 0x100 if ordinal == 0 else 0).to_bytes(4, "big")
            children.append((address, bytes(full)))
        target = _BundleMemory(heads, children)
        member = SimpleNamespace(slot=0, name="TURBO K", item_nodes=tuple(nodes),
                                 items=lambda nodes=nodes: tuple((n.address, n.raw) for n in nodes),
                                 effects=lambda: (), hp=1, hp_max=1)
        reading = {"party": [{"slot": 0, "name": "TURBO K", "items": [
            hashlib.sha256(node.raw).hexdigest() for node in nodes]}]}
        path = root / f"{phase}.json"
        proof = driver._capture_nodes(path, (member,), reading, target)
        entries.append({"path": path.name, **proof})
        readings.append(reading)
    return root, entries, readings, disk


def test_bundle_capture_aligns_two_ordered_children_and_preserves_stale_join_link(tmp_path):
    root, entries, readings, disk = _bundled_fixture(tmp_path)
    report = driver._compare_nodes(entries[0], readings[0], entries[1], readings[1], disk, root)
    assert report["bundle_coverage"] == "complete"
    assert len(report["bundle_children"]) == 2
    assert report["all_payloads_match_f"] and not report["bundle_inventory_incomplete"]
    assert report["bundle_children"][0]["payload_matches_f"]
    assert report["bundle_heads"][0]["bundle_link_offsets"]
    assert report["preservation_established"] is False
    assert report["independently_authenticated"] is False
    artifact = json.loads((root / "0.json").read_text())
    assert artifact["bundle"]["nodes"][0]["children"][0]["raw_hex"][0x2a * 2:0x2e * 2] == "55667788"
    assert "raw_hex" not in json.dumps(report)


@pytest.mark.parametrize("damage, category", [
    ("unsupported", "bundle_range_unsupported"), ("short", "bundle_short_read"),
    ("odd", "bundle_pointer"), ("overlap", "bundle_overlap"),
    ("cycle", "bundle_overlap"),
    ("null", "bundle_null"), ("extra", "bundle_quantity"),
    ("bounds", "bundle_bounds"), ("stale", "bundle_stale"),
])
def test_bundle_capture_fails_without_publishing_private_artifact(tmp_path, damage, category):
    root, entries, readings, _ = _bundled_fixture(tmp_path)
    artifact = json.loads((root / "0.json").read_text())
    head = artifact["bundle"]["nodes"][0]
    heads = [(item["address"], bytes.fromhex(item["raw_hex"]) + b"\0" * 4)
             for item in artifact["items"]]
    children = [(child["address"], bytes.fromhex(child["raw_hex"]))
                for child in head["children"]]
    target = _BundleMemory(heads, children)
    target.put(head["address"] + 0x42, children[0][0].to_bytes(4, "big"))
    if damage == "unsupported":
        target.put(0x1000 + driver.amiga.EXEC_CHK_BASE, b"\0" * 4)
    elif damage in ("odd", "overlap", "null", "extra"):
        pointer = {"odd": children[0][0] + 1, "overlap": heads[0][0],
                   "null": 0, "extra": children[0][0]}[damage]
        target.put(head["address"] + 0x42, pointer.to_bytes(4, "big"))
        if damage == "extra":
            target.put(head["address"] + 0x3a, b"\0")
    elif damage == "bounds":
        target.put(head["address"] + 0x3a, bytes([121]))
    elif damage == "cycle":
        target.put(children[0][0] + 0x42, children[0][0].to_bytes(4, "big"))
    elif damage == "stale":
        target.put(head["address"], b"\x77")
    else:
        original_read = target.read
        target.read = lambda address, size: (b"\0" * 69 if address == children[0][0]
                                             and size == 70 else original_read(address, size))
    nodes = tuple(SimpleNamespace(address=item["address"], raw=(
        target.read(item["address"], 66) if damage in ("extra", "bounds")
        and item["address"] == head["address"] else bytes.fromhex(item["raw_hex"])))
        for item in artifact["items"])
    if damage in ("extra", "bounds"):
        readings[0]["party"][0]["items"] = [hashlib.sha256(node.raw).hexdigest()
                                            for node in nodes]
    member = SimpleNamespace(slot=0, name="TURBO K", item_nodes=nodes)
    path = tmp_path / "failed.json"
    with pytest.raises(RouteError, match=category):
        driver._capture_nodes(path, (member,), readings[0], target)
    assert not path.exists()


def test_bundle_comparator_reports_child_payload_and_saved_quantity_damage(tmp_path):
    root, entries, readings, disk = _bundled_fixture(tmp_path)
    saved = bytearray(disk.read_file("F"))
    bundle_at = amiga_savegame.POD_PARTY_AT + amiga_savegame.POD_RECORD_BYTES + 20
    saved[bundle_at + 20 + 0x13] ^= 1
    altered = SimpleNamespace(read_file=lambda name: bytes(saved))
    report = driver._compare_nodes(entries[0], readings[0], entries[1], readings[1], altered, root)
    assert report["evidence_status"] == "payload_mismatch"
    assert not report["bundle_children"][0]["payload_matches_f"]
    saved[bundle_at + 20 + 0x13] ^= 1
    saved[bundle_at + 20 + 1] ^= 1  # Unknown saved child byte.
    report = driver._compare_nodes(entries[0], readings[0], entries[1], readings[1],
                                   SimpleNamespace(read_file=lambda name: bytes(saved)), root)
    assert 0x2f in report["bundle_children"][0]["differing_unnamed_saved_offsets"]
    assert not report["all_payloads_match_f"]
    saved[bundle_at + 0x0c] = 1
    with pytest.raises(RouteError, match="bundle_quantity"):
        driver._compare_nodes(entries[0], readings[0], entries[1], readings[1],
                              SimpleNamespace(read_file=lambda name: bytes(saved)), root)


def test_zero_bundle_f_reports_coverage_not_exercised(tmp_path):
    root, entries, readings, disk = _comparison_fixture(tmp_path)
    report = driver._compare_nodes(entries[0], readings[0], entries[1], readings[1], disk, root)
    assert report["bundle_coverage"] == "not_exercised"


def test_bundle_alignment_requires_the_specific_game_written_f_digest(tmp_path):
    root, entries, readings, disk = _bundled_fixture(tmp_path)
    with pytest.raises(RouteError, match="bundle_f_alignment"):
        driver._compare_nodes(entries[0], readings[0], entries[1], readings[1],
                              disk, root, "0" * 64)


@pytest.mark.parametrize("phase", [0, 1])
def test_bundle_comparison_rejects_private_head_with_unmatched_slot(tmp_path, phase):
    root, entries, readings, disk = _bundled_fixture(tmp_path)
    path = root / f"{phase}.json"
    artifact = json.loads(path.read_text())
    artifact["bundle"]["nodes"][0]["slot"] = 99
    path.write_text(json.dumps(artifact))
    entries[phase]["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(RouteError, match="bundle_capture: unmatched slot"):
        driver._compare_nodes(entries[0], readings[0], entries[1], readings[1], disk, root)


def test_bundle_child_old_head_link_is_compared_not_used_as_child_link(tmp_path):
    root, entries, readings, disk = _bundled_fixture(tmp_path)
    path = root / "1.json"
    artifact = json.loads(path.read_text())
    child = artifact["bundle"]["nodes"][0]["children"][1]
    raw = bytearray.fromhex(child["raw_hex"])
    raw[0x2a] ^= 1
    child["raw_hex"] = raw.hex()
    child["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(artifact))
    entries[1]["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = driver._compare_nodes(entries[0], readings[0], entries[1], readings[1], disk, root)
    assert 0x2a in report["bundle_children"][1]["differing_offsets"]
    assert report["all_payloads_match_f"]
    assert report["preservation_established"] is False


def test_bundle_capture_marks_end_of_checkpoint_mutation_stale(tmp_path):
    root, _, readings, _ = _bundled_fixture(tmp_path)
    artifact = json.loads((root / "0.json").read_text())
    head = artifact["bundle"]["nodes"][0]
    heads = [(item["address"], bytes.fromhex(item["raw_hex"]) + b"\0" * 4)
             for item in artifact["items"]]
    children = [(child["address"], bytes.fromhex(child["raw_hex"]))
                for child in head["children"]]
    target = _BundleMemory(heads, children)
    target.put(head["address"] + 0x42, children[0][0].to_bytes(4, "big"))
    original = target.read
    count = 0

    def moving(address, size):
        nonlocal count
        if address == children[0][0] and size == 70:
            count += 1
            if count == 2:
                return b"\x99" + original(address + 1, size - 1)
        return original(address, size)

    target.read = moving
    nodes = tuple(SimpleNamespace(address=item["address"], raw=bytes.fromhex(item["raw_hex"]))
                  for item in artifact["items"])
    member = SimpleNamespace(slot=0, name="TURBO K", item_nodes=nodes)
    path = tmp_path / "stale.json"
    with pytest.raises(RouteError, match="bundle_stale"):
        driver._capture_nodes(path, (member,), readings[0], target)
    assert not path.exists()


def test_payload_mismatch_takes_reporting_priority_over_incomplete_bundle(tmp_path):
    root, entries, readings, disk = _comparison_fixture(tmp_path, bundle=True)
    saved = bytearray(disk.read_file("F"))
    saved[amiga_savegame.POD_PARTY_AT + amiga_savegame.POD_RECORD_BYTES + 1] ^= 1
    report = driver._compare_nodes(entries[0], readings[0], entries[1], readings[1],
                                   SimpleNamespace(read_file=lambda name: bytes(saved)), root)
    assert report["bundle_inventory_incomplete"] is True
    assert report["all_payloads_match_f"] is False
    assert report["evidence_status"] == "payload_mismatch"


@pytest.mark.parametrize("phase", ["p2", "reload"])
@pytest.mark.parametrize("status", ["payload_mismatch", "bundle_inventory_incomplete"])
def test_main_reports_item_status_without_changing_route_success(
        tmp_path, monkeypatch, capsys, phase, status):
    root, entries, readings, disk = _comparison_fixture(tmp_path, bundle=(
        status == "bundle_inventory_incomplete"))
    if status == "payload_mismatch":
        saved = bytearray(disk.read_file("F"))
        saved[amiga_savegame.POD_PARTY_AT + amiga_savegame.POD_RECORD_BYTES + 1] ^= 1
        disk = SimpleNamespace(read_file=lambda name: bytes(saved))
    comparison = driver._compare_nodes(entries[0], readings[0], entries[1], readings[1],
                                       disk, root)
    assert comparison["evidence_status"] == status
    assert comparison["preservation_established"] is False
    receipt = {"checks": {"load": True}, "item_comparison": comparison}
    monkeypatch.setattr(driver, "terminating", nullcontext)
    monkeypatch.setattr(driver, "run_p2", lambda *args: receipt)
    monkeypatch.setattr(driver, "run_reload", lambda *args: receipt)
    argv = [phase, "--run-id", "synthetic", "--holder", "synthetic",
            "--audio-proof", str(tmp_path / "audio"), "--out", str(tmp_path),
            "--budget", "1000"]
    argv.extend(["--previous-return-attempts", "2"] if phase == "p2"
                else ["--receipt", str(tmp_path / "prior")])
    assert driver.main(argv) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True and output["checks"] == receipt["checks"]
    assert output["item_comparison_status"] == status


def test_capture_write_failure_retains_no_published_file(tmp_path, monkeypatch):
    members = _synthetic_members()
    monkeypatch.setattr(driver.amigaparty, "read_party", lambda target: members)
    monkeypatch.setattr(driver.fasttravelrun, "_reading", lambda *args: {})
    monkeypatch.setattr(driver.amigavars, "read_variables", lambda *args: [])
    monkeypatch.setattr(driver.os, "open", lambda *args: (_ for _ in ()).throw(OSError("write failed")))
    with pytest.raises(OSError, match="write failed"):
        driver._live_read(object(), capture=tmp_path / "nodes.json")
    assert list(tmp_path.iterdir()) == []


def test_checkpoint_receipt_is_private_relative_and_carries_screen_order(tmp_path, monkeypatch):
    directory = tmp_path / "run" / "item-nodes"
    directory.mkdir(parents=True)
    members = _synthetic_members()
    monkeypatch.setattr(driver.amigaparty, "read_party", lambda target: members)
    monkeypatch.setattr(driver.fasttravelrun, "_reading", lambda *args: {})
    monkeypatch.setattr(driver.amigavars, "read_variables", lambda *args: [])
    run = SimpleNamespace(events=[{"shot": 9, "time": 123, "screen": "world"}])
    receipt = {"holder": "proof", "phase": "p2", "staged_flag": {"after": "02"}}
    reading = driver._checkpoint(object(), directory, "pre-f", receipt, run,
                                 disk_sha256="disk hash", loaded_slot_sha256="slot hash",
                                 intervention={"before_image_sha256": "old",
                                               "after_image_sha256": "new"})
    entry = receipt["item_nodes"][0]
    assert entry["path"] == "run/item-nodes/pre-f.json"
    assert entry["file_sha256"] == hashlib.sha256((directory / "pre-f.json").read_bytes()).hexdigest()
    assert entry["order"] == 0 and entry["screenshot"] == run.events[0]
    assert (entry["source_disk_sha256"], entry["loaded_slot_sha256"]) == ("disk hash", "slot hash")
    assert "saved_slot_sha256" not in entry
    assert entry["media_intervention"] == {"before_image_sha256": "old",
                                            "after_image_sha256": "new"}
    assert "raw_hex" not in json.dumps(receipt) + json.dumps(reading)


def test_capture_directory_checks_real_owner_and_mode(tmp_path, monkeypatch):
    if os.name != "posix":
        monkeypatch.setattr(driver.pathlib.Path, "home", lambda: tmp_path)
        with pytest.raises(RouteError, match="requires POSIX"):
            driver._capture_dir("first")
        assert not (tmp_path / ".cache/wish/acceptance/WISH-360/first/item-nodes").exists()
        return
    monkeypatch.setattr(driver.pathlib.Path, "home", lambda: tmp_path)
    directory = driver._capture_dir("first")
    assert directory.stat().st_uid == os.getuid()
    assert directory.stat().st_mode & 0o777 == 0o700

    real_mkdir = pathlib.Path.mkdir

    def wrong_mode(path, *args, **kwargs):
        real_mkdir(path, *args, **kwargs)
        if path.name == "item-nodes":
            path.chmod(0o755)

    monkeypatch.setattr(driver.pathlib.Path, "mkdir", wrong_mode)
    with pytest.raises(RouteError, match="wrong owner or mode"):
        driver._capture_dir("wrong-mode")
    assert not list((tmp_path / ".cache/wish/acceptance/WISH-360/wrong-mode/item-nodes").iterdir())
    monkeypatch.setattr(driver.pathlib.Path, "mkdir", real_mkdir)
    monkeypatch.setattr(driver.os, "getuid", lambda: -1)
    with pytest.raises(RouteError, match="wrong owner or mode"):
        driver._capture_dir("wrong-owner")


@pytest.mark.parametrize("owner,mode,private", [
    (100, 0o700, True), (101, 0o700, False), (100, 0o755, False),
])
def test_private_directory_predicate_checks_owner_and_mode(owner, mode, private):
    assert driver._private_directory(SimpleNamespace(st_uid=owner, st_mode=mode), 100) is private


def test_non_posix_capture_stops_before_creating_node_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(driver.pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(driver, "os", SimpleNamespace(name="nt"))
    with pytest.raises(RouteError, match="requires POSIX"):
        driver._capture_dir("first")
    assert not (tmp_path / ".cache/wish/acceptance/WISH-360/first/item-nodes").exists()


@pytest.mark.parametrize("phase", ["p2", "reload"])
def test_non_posix_run_stops_before_boot_or_creating_nodes(tmp_path, monkeypatch, phase):
    monkeypatch.setattr(driver.pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(driver, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(driver, "_check_source", lambda: None)
    monkeypatch.setattr(driver, "_export_guards", lambda out: None)
    monkeypatch.setattr(driver, "_boot", lambda *args: pytest.fail("booted without private capture"))
    monkeypatch.setattr(driver, "_prepare_p2", lambda *args: (
        tmp_path / "manifest", {"encounter_media": {}}))
    monkeypatch.setattr(driver.acceptance, "prepare", lambda *args, **kwargs: tmp_path / "manifest")
    (tmp_path / "manifest").write_text("{}")
    monkeypatch.setattr(driver, "_restored_source", lambda p2: tmp_path / "source")
    receipt = tmp_path / "prior.json"
    receipt.write_text(json.dumps({"combined_deadline": driver.time.time() + 1100,
                                   "cumulative_return_attempts": 3}))
    args = SimpleNamespace(previous_return_attempts=2, budget=1000,
                           out=tmp_path / phase, run_id="first", holder="proof",
                           audio_proof=tmp_path / "audio", receipt=receipt)
    with pytest.raises(RouteError, match="requires POSIX"):
        if phase == "p2":
            driver.run_p2(args, guest=object())
        else:
            driver.run_reload(args, guest=object())
    assert not (tmp_path / ".cache/wish/acceptance/WISH-360/first/item-nodes").exists()


@pytest.mark.parametrize("step_fails, capture_fails, post_save_fails, disk_mismatch, damage", [
    (False, False, False, False, None), (True, False, False, False, None),
    (False, True, False, False, None), (False, False, True, False, None),
    (False, False, False, True, None),
    *[(False, False, False, False, kind) for kind in
      ("short", "wrong-name", "wrong-cell", "wrong-square", "wrong-facing",
       "wrong-flag", "dungeon", "missing")],
])
def test_p2_owns_snapshot_after_return_adoption_before_step_and_discards_it(
        tmp_path, monkeypatch, step_fails, capture_fails, post_save_fails, disk_mismatch, damage):
    events = []
    capture_events = []
    loaded_hashes = []
    require_f = []
    b_bytes = b"generated loaded B"
    f_bytes = _synthetic_f()
    restored_bytes = _synthetic_f(damage=damage) if damage else f_bytes
    b_hash = hashlib.sha256(b_bytes).hexdigest()
    f_hash = hashlib.sha256(restored_bytes).hexdigest() if damage else hashlib.sha256(f_bytes).hexdigest()
    restored_path = tmp_path / "synthetic-restored.adf"
    restored_path.write_bytes(b"wrong F" if disk_mismatch else restored_bytes)
    holder = "proof"
    state = SimpleNamespace(load=lambda: {"on": False, "rows": []})

    class Guest:
        def snapshot(self, name, owner):
            assert owner == holder
            events.append(("snapshot", name))

        def discard(self, name, owner):
            assert owner == holder
            events.append(("discard", name))

    class Run:
        def __init__(self, *args):
            self.events = []

        def load(self, *args):
            pass

        def left(self, *args):
            return 10

        def see(self, *args):
            pass

        def press(self, *args):
            capture_events.append(("key", args[1]))
            self.events.append({"key": args[1]})

    def adoption(*args):
        count = sum(event[0] == "adopt" for event in events)
        events.append(("adopt", count))
        return {}

    def step(*args):
        events.append(("step", "NP8"))
        if step_fails:
            raise RouteError("injected NP8 failure")
        return {"pressed": ["NP8"]}

    manifest = {"encounter_media": {"prepared_image": "unused"}, "names_a": [],
                "disks": {"disk3": {"path": "unused", "sha256": "synthetic"}},
                "loaded_letter": "G"}
    monkeypatch.setattr(driver, "_export_guards", lambda out: None)
    monkeypatch.setattr(driver, "_prepare_p2", lambda *args: (tmp_path / "manifest", manifest))
    monkeypatch.setattr(driver, "_library", lambda disk: b"library")
    monkeypatch.setattr(driver, "_row_from_library", lambda *args: b"original")
    monkeypatch.setattr(driver, "_boot", lambda *args: {"remotes": {}})
    monkeypatch.setattr(driver, "GuardedRun", Run)
    monkeypatch.setattr(driver, "_target", lambda owner: object())
    monkeypatch.setattr(driver, "_capture_dir", lambda run_id: tmp_path / "private")
    def checkpoint(target, directory, name, receipt, run, **kwargs):
        capture_events.append(("capture", name))
        receipt.setdefault("item_nodes", []).append({"checkpoint": name})
        loaded_hashes.append(kwargs.get("loaded_slot_sha256", kwargs.get("slot_sha256")))
        if capture_fails and name == "pre-f":
            raise RouteError("injected private capture failure")
        if post_save_fails and name == "post-save-quit":
            raise RouteError("injected post-save capture failure")
        return {"party": [{"name": f"WHO{i}"} for i in range(6)],
                "trip": {"square": [7, 15, 0]},
                "variables": [{"var": f"${variable:04X}", "value": value}
                              for variable, value in ((0x25, 22), (0x26, 3), (0x129, 2))]}

    monkeypatch.setattr(driver, "_checkpoint", checkpoint)
    monkeypatch.setattr(driver, "_compare_nodes", lambda *args: {"full_match": True})
    monkeypatch.setattr(driver, "_require_world", lambda *args, **kwargs: None)
    monkeypatch.setattr(driver, "_stage_flag", lambda target: {"after": "02"})
    monkeypatch.setattr(driver, "adopt_loaded_media", adoption)
    monkeypatch.setattr(driver, "_trip", lambda *args: [])
    monkeypatch.setattr(driver, "_step_under_switch", step)
    monkeypatch.setattr(driver, "restore_loaded_media", lambda *args: {})
    monkeypatch.setattr(driver, "_original_live", lambda *args: {})
    def halt(*args):
        require_f.append(args[-1])
        return {}, {"restored": {"path": str(restored_path)}, "slot_f_sha256": f_hash}

    monkeypatch.setattr(driver, "_halt", halt)
    monkeypatch.setattr(driver, "_check_source", lambda: None)
    monkeypatch.setattr(driver.amiga_adf.AmigaDisk, "open", lambda path: SimpleNamespace(
        read_file=lambda name: (_ for _ in ()).throw(amiga_adf.AmigaDiskError("missing F"))
        if damage == "missing" and str(path) == str(restored_path)
        else (restored_path.read_bytes() if str(path) == str(restored_path) else b_bytes)))
    monkeypatch.setattr(driver.route_darkness, "DARKNESS", SimpleNamespace(
        read_slot=route_darkness._darkness_read_slot))
    monkeypatch.setattr(driver.noencounters, "WinuaeState", lambda path: state)
    args = SimpleNamespace(previous_return_attempts=2, budget=1200, out=tmp_path / "p2",
                           run_id="proof", holder=holder, audio_proof=tmp_path / "audio")
    if step_fails:
        with pytest.raises(RouteError, match="injected NP8 failure"):
            driver.run_p2(args, guest=Guest())
    elif capture_fails:
        with pytest.raises(RouteError, match="injected private capture failure"):
            driver.run_p2(args, guest=Guest())
        receipt = json.loads((args.out / "p2-receipt.json").read_text())
        assert receipt["checks"].get("save") is not True and receipt["cleanup"] == []
    elif post_save_fails:
        with pytest.raises(RouteError, match="injected post-save capture failure"):
            driver.run_p2(args, guest=Guest())
        receipt = json.loads((args.out / "p2-receipt.json").read_text())
        assert receipt["checks"]["save_ui_acknowledged"] is True
        assert receipt["checks"]["post_save_capture"] is False
        assert receipt["checks"]["save"] is True
        assert receipt["game_written_f_sha256"] == f_hash
        assert receipt["screens"][-1]["key"] == "N"
        assert receipt["success"] is False and receipt["cleanup"] == []
        with pytest.raises(RouteError, match="post-save item capture"):
            driver._restored_source(receipt)
    elif disk_mismatch:
        with pytest.raises(RouteError, match="independent slot read"):
            driver.run_p2(args, guest=Guest())
        receipt = json.loads((args.out / "p2-receipt.json").read_text())
        assert receipt["checks"].get("save") is not True
        assert "game_written_f_sha256" not in receipt
        assert receipt["success"] is False
    elif damage:
        with pytest.raises(RouteError, match="game-written F"):
            driver.run_p2(args, guest=Guest())
        receipt = json.loads((args.out / "p2-receipt.json").read_text())
        assert receipt["checks"]["save_ui_acknowledged"] is True
        assert receipt["disk_restoration"]["slot_f_sha256"] == f_hash
        assert receipt["checks"]["post_save_capture"] is True
        assert receipt["checks"].get("save") is not True
        assert "game_written_f_sha256" not in receipt
        assert receipt["success"] is False and receipt["cleanup"]
    else:
        saved = route_darkness._darkness_read_slot(
            SimpleNamespace(read_file=lambda name: restored_bytes), "F")
        assert len(restored_bytes) == amiga_savegame.POD_SAVEGAME_SIZE == 10828
        assert saved["names"] == [f"WHO{i}" for i in range(6)]
        assert saved["in_dungeon"] is False and saved["wilderness_square"] == [22, 3]
        assert saved["place"] == {"area": 0, "x": 7, "y": 15, "facing": 0}
        assert amiga_savegame.pod_parse(restored_bytes).var(0x129) == 2
        receipt = driver.run_p2(args, guest=Guest())
        assert receipt["success"]
        assert receipt["game_written_f_sha256"] == f_hash
        assert receipt["checks"]["post_save_capture"] is True
        assert b_hash != f_hash
    assert events == [("snapshot", "b0"), ("snapshot", "b1"), ("adopt", 0),
                       ("adopt", 1), ("snapshot", "p2-before-step"), ("step", "NP8"),
                       ("discard", "b0"), ("discard", "b1"),
                       ("discard", "p2-before-step")]
    assert loaded_hashes == [b_hash] * len(loaded_hashes)
    assert require_f == [not step_fails and not capture_fails]
    if step_fails:
        assert capture_events == [("capture", "before-staging"), ("capture", "post-return")]
    elif capture_fails:
        assert capture_events == [("capture", "before-staging"), ("capture", "post-return"),
                                  ("capture", "post-step"), ("key", "E"), ("key", "S"),
                                  ("capture", "pre-f")]
    else:
        assert capture_events == [("capture", "before-staging"), ("capture", "post-return"),
                                  ("capture", "post-step"), ("key", "E"), ("key", "S"),
                                  ("capture", "pre-f"), ("key", "F"), ("key", "N"),
                                  ("capture", "post-save-quit")]


def test_reload_captures_loaded_and_stepped_before_cleanup(tmp_path, monkeypatch):
    events = []
    loaded_hashes = []
    f_hash = hashlib.sha256(b"generated saved F").hexdigest()
    previous = tmp_path / "p2.json"
    previous.write_text(json.dumps({"combined_deadline": driver.time.time() + 1100,
                                     "cumulative_return_attempts": 3,
                                     "item_nodes": [{"checkpoint": "pre-f"}],
                                     "pre_f": {"party": [{"name": "TURBO K"}]},
                                     "stepped": {"party": [{"name": "TURBO K"}]}}))
    manifest = {"disks": {"disk3": {"path": "unused", "sha256": "synthetic"}},
                "loaded_letter": "F"}
    prepared = tmp_path / "prepare.json"
    prepared.write_text(json.dumps(manifest))
    monkeypatch.setattr(driver, "_restored_source", lambda p2: tmp_path / "source")
    monkeypatch.setattr(driver, "sha256", lambda path: "synthetic source hash")
    monkeypatch.setattr(driver, "_check_source", lambda: None)
    monkeypatch.setattr(driver, "_export_guards", lambda out: None)
    monkeypatch.setattr(driver.acceptance, "prepare", lambda *args, **kwargs: prepared)
    monkeypatch.setattr(driver.amiga_adf.AmigaDisk, "open", lambda path: SimpleNamespace(
        read_file=lambda name: b"generated saved F"))
    monkeypatch.setattr(driver, "_library", lambda disk: b"synthetic library")
    monkeypatch.setattr(driver, "_row_from_library", lambda *args: b"original")
    monkeypatch.setattr(driver.route_darkness, "DARKNESS", SimpleNamespace(
        read_slot=lambda *args: {"in_dungeon": False, "names": ["TURBO K"],
                                 "wilderness_square": (22, 3)}))
    monkeypatch.setattr(driver, "_value", lambda reading, var: 22 if var == 0x25 else
                        (2 if reading.get("moved") else 3))
    monkeypatch.setattr(driver, "_boot", lambda *args: {"remotes": {}})
    monkeypatch.setattr(driver, "_target", lambda holder: object())
    monkeypatch.setattr(driver, "_capture_dir", lambda run_id: tmp_path / "private")
    monkeypatch.setattr(driver, "_require_world", lambda *args, **kwargs: None)
    monkeypatch.setattr(driver, "_verified_reload_gate", lambda *args: {})
    monkeypatch.setattr(driver, "_original_live", lambda *args: {})
    monkeypatch.setattr(driver.noencounters, "WinuaeState", lambda path: SimpleNamespace(
        load=lambda: {"on": False, "rows": []}))

    class Run:
        def __init__(self, *args):
            self.events = []

        def load(self, *args, **kwargs):
            events.append("load")

        def see(self, *args):
            events.append("world")

    class Guest:
        def snapshot(self, name, holder):
            events.append("snapshot")

        def discard(self, name, holder):
            events.append("discard")

    class Switch:
        def on(self):
            events.append("on")
            return {}

        def keys(self, keys):
            events.append("NP8")
            return {"pressed": ["NP8"]}

        def off(self):
            events.append("off")
            return {}

    def checkpoint(target, directory, name, receipt, run, **kwargs):
        events.append(name)
        receipt.setdefault("item_nodes", []).append({"checkpoint": name})
        loaded_hashes.append(kwargs["loaded_slot_sha256"])
        return {"party": [{"name": "TURBO K"}], "moved": name == "post-step"}

    monkeypatch.setattr(driver, "GuardedRun", Run)
    monkeypatch.setattr(driver, "_switch", lambda *args: Switch())
    monkeypatch.setattr(driver, "_checkpoint", checkpoint)
    monkeypatch.setattr(driver, "_compare_nodes", lambda *args: {"full_match": True})
    monkeypatch.setattr(driver.acceptance, "halt_lane", lambda *args, **kwargs: events.append(
        "halt") or {})
    args = SimpleNamespace(receipt=previous, budget=1000, out=tmp_path / "reload",
                           run_id="new-run", holder="proof", audio_proof=tmp_path / "audio")
    assert driver.run_reload(args, guest=Guest())["success"]
    assert events == ["load", "f-loaded", "snapshot", "on", "NP8", "world", "post-step",
                      "off", "discard", "halt"]
    assert loaded_hashes == [f_hash, f_hash]


def _seven_source(tmp_path, monkeypatch):
    """Generate all seven records, 64 relocated main heads and four child allocations."""
    saved = bytearray(amiga_savegame.POD_SAVEGAME_SIZE)
    struct.pack_into(">H", saved, amiga_savegame.POD_COUNT_AT, 7)
    heads, children, members = [], [], []
    cursor = amiga_savegame.POD_PARTY_AT
    address = 0x2000
    case_at = None
    for slot, (name, count) in enumerate(zip(driver.BUNDLE_NAMES, driver.BUNDLE_HEADS,
                                              strict=True)):
        name_at = cursor + amiga_savegame.POD_NAME_AT
        saved[name_at:name_at + len(name)] = name.encode()
        struct.pack_into(">I", saved, cursor + amiga_savegame.POD_ITEM_COUNT_AT, count)
        cursor += amiga_savegame.POD_RECORD_BYTES
        nodes = []
        for index in range(count):
            tail = bytearray(20)
            tail[0] = 0x49 if (slot, index) == (4, 2) else 0x12
            tail[1] = (slot * 19 + index) % 256
            tail[13], tail[16] = slot + 7, index + 8
            full = bytearray(70)
            full[0x2a:0x2e] = (address + 0x80 if index + 1 < count else 0).to_bytes(4, "big")
            if (slot, index) == (4, 2):
                case_at = address
                tail[0x0c] = 4
                full[0x42:0x46] = (0x8000).to_bytes(4, "big")
            full[0x2e:0x42] = tail
            heads.append((address, bytes(full)))
            nodes.append(SimpleNamespace(address=address, raw=bytes(full[:66])))
            saved[cursor:cursor + 20] = tail
            cursor += 20
            if (slot, index) == (4, 2):
                for ordinal in range(4):
                    child_at = 0x8000 + ordinal * 0x80
                    child = bytearray(70)
                    child[0x2a:0x2e] = (0x55667788).to_bytes(4, "big")
                    child[0x42:0x46] = (child_at + 0x80 if ordinal < 3 else 0).to_bytes(4, "big")
                    child[0x2e] = 39
                    child[0x2f], child[0x3b], child[0x3e] = ordinal + 1, 20 + ordinal, 40 + ordinal
                    saved[cursor:cursor + 20] = child[0x2e:0x42]
                    cursor += 20
                    children.append((child_at, bytes(child)))
            address += 0x80
        address += 0x100
        members.append(SimpleNamespace(slot=slot, name=name, hp=3, hp_max=9,
                                       address=0xA000 + slot * 0x200,
                                       raw=bytes(amiga_savegame.POD_RECORD_BYTES),
                                       item_nodes=tuple(nodes),
                                       items=lambda nodes=nodes: tuple((n.address, n.raw) for n in nodes),
                                       effects=lambda: ()))
    target = _BundleMemory(heads, children)
    target.anchor_base = target.data_base = 0x1000
    target.locate = lambda memory: target.data_base
    monkeypatch.setattr(driver.amigaparty, "read_party", lambda _target: tuple(members))
    monkeypatch.setattr(driver.fasttravelrun, "_reading", lambda *a: {})
    monkeypatch.setattr(driver.amigavars, "read_variables", lambda *a: [])
    slot = bytes(saved)
    disk = SimpleNamespace(read_file=lambda name: slot)
    root = tmp_path / "run"
    directory = root / "item-nodes"
    directory.mkdir(parents=True)
    path = driver.pathlib.Path(directory / "initial.json")

    def capture():
        reading = driver._live_read(target, capture=path, source=True)
        proof = reading.pop("capture")
        return reading, {"path": "item-nodes/initial.json", "file_sha256": proof["file_sha256"],
                         "heads": 64, "bundle_heads": 1, "bundle_children": 4,
                         "measured_regions": [[0, driver.amiga.EXEC_PAGE]]}

    return SimpleNamespace(saved=slot, disk=disk, target=target, members=members,
                           children=children, case=case_at, root=root, path=path, capture=capture)


def test_seven_member_source_captures_64_heads_four_children_and_specific_f(tmp_path, monkeypatch):
    _synthetic_private_files(monkeypatch, tmp_path)
    generated = _seven_source(tmp_path, monkeypatch)
    reading, entry = generated.capture()
    assert "trip" not in reading and "variables" not in reading
    digest = hashlib.sha256(generated.saved).hexdigest()
    monkeypatch.setattr(driver, "BUNDLE_SOURCE_F_SHA256", digest)
    report = driver._source_compare(entry, reading, generated.disk, "F", digest,
                                    generated.root, role="selected-source")
    assert (report["heads"], report["bundle_heads"], report["bundle_children"]) == (64, 1, 4)
    assert report["all_payloads_match_reference"]
    assert report["independently_authenticated"] is False
    assert report["preservation_established"] is False
    artifact = json.loads(generated.path.read_text())
    assert [(node["slot"], node["chain_index"]) for node in artifact["items"] if
            node["slot"] == 4] == [(4, index) for index in range(10)]
    case = artifact["bundle"]["nodes"][0]
    assert (case["slot"], case["chain_index"], len(case["children"])) == (4, 2, 4)
    assert [bytes.fromhex(child["raw_hex"])[0x2f] for child in case["children"]] == [1, 2, 3, 4]
    assert all(bytes.fromhex(child["raw_hex"])[0x2a:0x2e] == b"\x55\x66\x77\x88"
               for child in case["children"])
    assert "raw_hex" not in json.dumps(report)
    if os.name == "posix":
        assert generated.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("damage", ["name", "slot", "count", "case", "six-members"])
def test_source_capture_blocks_wrong_order_and_case_without_weakening_turbo_guard(
        tmp_path, monkeypatch, damage):
    generated = _seven_source(tmp_path, monkeypatch)
    members = generated.members
    if damage == "name":
        members[4].name = "OTHER"
    elif damage == "slot":
        members[4].slot = 3
    elif damage == "count":
        members[4].item_nodes = members[4].item_nodes[:-1]
    elif damage == "six-members":
        members.pop()
    else:
        case = members[4].item_nodes[2]
        case.raw = case.raw[:0x2e] + b"\x12" + case.raw[0x2f:]
        generated.target.put(generated.case + 0x2e, b"\x12")
    with pytest.raises(RouteError, match="bundle_source_identity"):
        generated.capture()
    assert not generated.path.exists()


def test_both_sources_still_block_the_other_capture_contract(tmp_path, monkeypatch):
    generated = _seven_source(tmp_path, monkeypatch)
    reading = {"party": [{"slot": m.slot, "name": m.name,
                          "items": [hashlib.sha256(n.raw).hexdigest() for n in m.item_nodes]}
                         for m in generated.members]}
    with pytest.raises(RouteError, match="TURBO K"):
        driver._capture_nodes(generated.path, tuple(generated.members), reading)
    with pytest.raises(RouteError, match="bundle_source_identity"):
        driver._capture_nodes(generated.path, _synthetic_members(),
                              {"party": reading["party"][:1]}, generated.target, source=True)
    assert not generated.path.exists()


@pytest.mark.parametrize("damage, category", [
    ("early-null", "bundle_null"), ("extra", "bundle_quantity"),
    ("odd", "bundle_pointer"), ("overlap", "bundle_overlap"),
    ("cycle", "bundle_overlap"), ("out-of-range", "bundle_range_unsupported"),
    ("short", "bundle_short_read"), ("quantity", "bundle_source_identity"),
    ("complement", "bundle_range_unsupported"), ("regions", "bundle_range_unsupported"),
    ("stale-head", "bundle_stale"), ("stale-child", "bundle_stale"),
    ("stale-party", "bundle_source_stale"), ("member-range", "bundle_source_range"),
])
def test_source_capture_blocks_damaged_private_topology_and_late_changes(
        tmp_path, monkeypatch, damage, category):
    generated = _seven_source(tmp_path, monkeypatch)
    target = generated.target
    if damage in ("early-null", "extra", "odd", "overlap", "out-of-range"):
        pointer = {"early-null": 0, "extra": generated.children[0][0],
                   "odd": generated.children[0][0] + 1, "overlap": generated.case,
                   "out-of-range": driver.amiga.EXEC_PAGE + 0x80}[damage]
        address = generated.case + 0x42 if damage != "extra" else generated.children[-1][0] + 0x42
        target.put(address, pointer.to_bytes(4, "big"))
    elif damage == "cycle":
        target.put(generated.children[0][0] + 0x42, generated.children[0][0].to_bytes(4, "big"))
    elif damage == "short":
        original = target.read
        target.read = lambda address, count: (b"\0" * 69 if address == generated.children[0][0]
                                              and count == 70 else original(address, count))
    elif damage == "quantity":
        generated.members[4].item_nodes[2].raw = (generated.members[4].item_nodes[2].raw[:0x3a]
                                                 + b"\x03" + generated.members[4].item_nodes[2].raw[0x3b:])
    elif damage == "complement":
        target.put(0x1000 + driver.amiga.EXEC_CHK_BASE, b"\0" * 4)
    elif damage == "regions":
        target.memory = ((0, driver.amiga.EXEC_PAGE - 1),)
    elif damage == "stale-head":
        target.put(generated.case, b"\x70")
    elif damage == "stale-child":
        original = target.read
        count = 0

        def moving(address, size):
            nonlocal count
            if address == generated.children[0][0] and size == 70:
                count += 1
                if count == 2:
                    return b"\x99" + original(address + 1, size - 1)
            return original(address, size)

        target.read = moving
    elif damage == "member-range":
        generated.members[6].address = driver.amiga.EXEC_PAGE + 0x200
    else:
        original = driver.amigaparty.read_party
        calls = 0

        def changing(target):
            nonlocal calls
            calls += 1
            if calls == 2:
                later = copy.deepcopy(original(target))
                later[6].hp = 4
                return later
            return original(target)

        monkeypatch.setattr(driver.amigaparty, "read_party", changing)
    with pytest.raises(RouteError, match=category):
        generated.capture()
    assert not generated.path.exists()


def test_source_comparison_keeps_unnamed_payload_and_reference_letters_separate(
        tmp_path, monkeypatch):
    _synthetic_private_files(monkeypatch, tmp_path)
    generated = _seven_source(tmp_path, monkeypatch)
    reading, entry = generated.capture()
    digest = hashlib.sha256(generated.saved).hexdigest()
    with pytest.raises(RouteError, match="bundle_source_reference"):
        driver._source_compare(entry, reading, generated.disk, "G", digest,
                               generated.root, role="same-run-F")
    with pytest.raises(RouteError, match="bundle_source_reference"):
        driver._source_compare(entry, reading, generated.disk, "F", digest,
                               generated.root, role="selected-source")
    generated.path.unlink()
    generated.target.put(generated.children[0][0] + 0x2f, b"\x77")
    reading, entry = generated.capture()
    report = driver._source_compare(entry, reading, generated.disk, "F", digest,
                                    generated.root, role="same-run-F")
    assert not report["all_payloads_match_reference"]
    assert report["payload_differences"] == [{"slot": 4, "head": 2, "kind": "child",
                                               "ordinal": 0, "payload_offsets": [0x2f],
                                               "unnamed_saved_offsets": [0x2f]}]
    assert report["preservation_established"] is False


@pytest.mark.parametrize("damage", ["source-as-g", "g-as-f", "missing-g", "short-g",
                                     "saved-quantity", "saved-child"])
def test_source_comparison_binds_each_letter_to_its_own_fetched_slot(
        tmp_path, monkeypatch, damage):
    _synthetic_private_files(monkeypatch, tmp_path)
    generated = _seven_source(tmp_path, monkeypatch)
    reading, entry = generated.capture()
    f_slot = generated.saved
    g_slot = bytearray(f_slot)
    g_slot[-1] ^= 1
    if damage == "short-g":
        g_slot.pop()
    if damage == "saved-quantity":
        # The case's byte 12 lies after 16+12+6+8 earlier heads and HILDE's first two.
        h = amiga_savegame.pod_parse(f_slot).characters[4]
        case_at = h.at + amiga_savegame.POD_RECORD_BYTES + 2 * 20
        g_slot[case_at + 12] = 3
    if damage == "saved-child":
        h = amiga_savegame.pod_parse(f_slot).characters[4]
        case_at = h.at + amiga_savegame.POD_RECORD_BYTES + 2 * 20
        g_slot[case_at + 20] = 0x12
    slots = {"F": f_slot, "G": bytes(g_slot)}

    def read_file(name):
        letter = name[-5].upper()
        if letter == "G" and damage == "missing-g":
            raise amiga_adf.AmigaDiskError("generated G is missing")
        return slots[letter]

    disk = SimpleNamespace(read_file=read_file)
    f_hash = hashlib.sha256(f_slot).hexdigest()
    g_hash = hashlib.sha256(g_slot).hexdigest()
    if damage == "source-as-g":
        with pytest.raises(RouteError, match="digest differs"):
            driver._source_compare(entry, reading, disk, "G", f_hash,
                                   generated.root, role="same-run-G")
    elif damage == "g-as-f":
        with pytest.raises(RouteError, match="digest differs"):
            driver._source_compare(entry, reading, disk, "F", g_hash,
                                   generated.root, role="same-run-F")
    elif damage == "missing-g":
        with pytest.raises(RouteError, match="bundle_source_g"):
            driver._source_compare(entry, reading, disk, "G", g_hash,
                                   generated.root, role="same-run-G")
    elif damage == "short-g":
        with pytest.raises(RouteError, match="bundle_source_g"):
            driver._source_compare(entry, reading, disk, "G", g_hash,
                                   generated.root, role="same-run-G")
    else:
        with pytest.raises(RouteError, match="bundle_source"):
            driver._source_compare(entry, reading, disk, "G", g_hash,
                                   generated.root, role="same-run-G")


@pytest.mark.parametrize("damage", [None, "wrong-variant", "unfiltered", "missing-identity",
                                      "wrong-reader", "wrong-map", "wrong-prepared-digest"])
def test_source_controls_require_one_current_source_variant_per_screen(tmp_path, monkeypatch, damage):
    tmp_path = _synthetic_private_files(monkeypatch, tmp_path)(tmp_path)
    shared = pathlib.Path(driver.guardmaps.__file__).with_name("guards_darkness.json")
    current_bytes = shared.read_bytes()
    if os.name == "nt":
        current_bytes = current_bytes.replace(b"\r\n", b"\n")
    assert hashlib.sha256(current_bytes).hexdigest() == driver.BUNDLE_CURRENT_RULES_SHA256
    current_path = tmp_path / "guards_darkness.json"
    current_path.write_bytes(current_bytes)
    monkeypatch.setattr(driver.guardmaps, "__file__", str(tmp_path / "guardmaps.py"))
    current = json.loads(current_path.read_text())
    manifest = tmp_path / "prepare.json"
    manifest.write_text("Generated prepared manifest\n")
    manifest.chmod(0o600)
    monkeypatch.setattr(driver, "BUNDLE_MANIFEST_SHA256", sha256(manifest))
    specs = {}
    for kind, variants in (("guards", driver.BUNDLE_GUARD_VARIANTS),
                           ("identity", driver.BUNDLE_IDENTITY_VARIANTS)):
        selected = {state: driver.rules_of(current[kind][state])[index]
                    for state, index in variants.items()}
        if damage == "wrong-variant" and kind == "identity":
            selected["camp_items_5"] = driver.rules_of(current[kind]["camp_items_5"])[0]
        elif damage == "unfiltered" and kind == "guards":
            selected["loaded_menu"] = current[kind]["loaded_menu"]
        elif damage == "missing-identity" and kind == "identity":
            del selected["camp_items_5"]
        path = tmp_path / f"{kind}.json"
        path.write_text(json.dumps(selected))
        path.chmod(0o600)
        specs[kind] = {"path": str(path), "sha256": sha256(path), "variants": variants}
    prepared = driver.BUNDLE_PREPARED_SHA256
    validated = {"source_image_sha256": driver.BUNDLE_IMAGE_SHA256,
                 "source_f_sha256": driver.BUNDLE_SOURCE_F_SHA256,
                 "prepared_disk3_sha256": ("0" * 64 if damage == "wrong-prepared-digest"
                                           else prepared),
                 "manifest_sha256": sha256(manifest),
                 "current_rules_sha256": driver.BUNDLE_CURRENT_RULES_SHA256,
                 "screen_reader_sha256": sha256(pathlib.Path(driver.screens.__file__)),
                 "executable_sha256": driver.BUNDLE_EXEC_SHA256,
                 "config_sha256": driver.BUNDLE_CONFIG_SHA256, **specs}
    if damage == "wrong-reader":
        validated["screen_reader_sha256"] = "0" * 64
    controls = tmp_path / "selected.json"
    controls.write_text(json.dumps(validated))
    controls.chmod(0o600)
    if damage == "wrong-map":
        current_path.write_bytes(current_bytes + b"\n")
        assert sha256(current_path) != driver.BUNDLE_CURRENT_RULES_SHA256
    if damage:
        reason = ("current rule map differs" if damage == "wrong-map" else
                  "offline preparation or current reader differs" if damage == "wrong-reader" else
                  "bundle_source_controls")
        with pytest.raises(RouteError, match=reason):
            driver._source_controls(controls, manifest, prepared)
    else:
        guards, identity, _ = driver._source_controls(controls, manifest, prepared)
        assert set(guards.rules) == set(driver.BUNDLE_GUARD_VARIANTS)
        assert set(identity.rules) == set(driver.BUNDLE_IDENTITY_VARIANTS)
        assert all(len(driver.rules_of(v)) == 1 for v in guards.rules.values())


def test_pinned_prepared_b_and_registered_f_have_full_ordered_boundaries_when_available():
    manifest = (pathlib.Path.home() / ".cache/wish/acceptance/WISH-360/"
                "bundle-w4d-source-prep1/prepare.json")
    if not manifest.is_file():
        pytest.skip("private offline W4D preparation is not available on this machine")
    source, prepared = driver._source_contract(manifest, json.loads(manifest.read_text()))
    assert prepared == driver.BUNDLE_PREPARED_SHA256
    assert sha256(source) == driver.BUNDLE_IMAGE_SHA256
    assert sha256(manifest) == driver.BUNDLE_MANIFEST_SHA256


def _source_coordinator(tmp_path, monkeypatch, *, fail=None):
    private_path = _synthetic_private_files(monkeypatch, tmp_path)
    generated = _seven_source(tmp_path, monkeypatch)
    root = private_path(tmp_path / ".cache/wish/acceptance/WISH-360/synthetic-source")
    root.mkdir(parents=True, mode=0o700)
    source = root / "source-input.adf"
    source.write_bytes(b"Generated original disk marker")
    monkeypatch.setattr(driver, "BUNDLE_IMAGE_SHA256", sha256(source))
    source_slot = generated.saved
    f_slot = bytearray(source_slot)
    f_slot[-1] ^= 1
    g_slot = bytearray(f_slot)
    g_slot[-2] ^= 1
    slots = {"F": bytes(f_slot), "G": bytes(g_slot)}
    hashes = {key: hashlib.sha256(value).hexdigest() for key, value in slots.items()}
    monkeypatch.setattr(driver, "BUNDLE_SOURCE_F_SHA256",
                        hashlib.sha256(source_slot).hexdigest())
    fetched = root / "fetched-disk3.adf"
    fetched.write_bytes(b"Generated fetched disk marker")
    prepared = root / "prepare.json"
    disks = {}
    for key in ("disk1", "disk2", "disk3"):
        local = root / f"{key}.adf"
        local.write_bytes(f"Generated {key} disk marker".encode())
        disks[key] = {"path": str(local), "sha256": sha256(local)}
    monkeypatch.setattr(driver, "BUNDLE_PREPARED_SHA256", disks["disk3"]["sha256"])
    monkeypatch.setattr(driver.route_darkness, "DARKNESS_DISK1_SHA256", disks["disk1"]["sha256"])
    monkeypatch.setattr(driver.route_darkness, "DARKNESS_DISK2_SHA256", disks["disk2"]["sha256"])
    prepared.write_text(json.dumps({"disks": disks}))
    prepared.chmod(0o600)
    monkeypatch.setattr(driver, "BUNDLE_MANIFEST_SHA256", sha256(prepared))
    controls = root / "controls.json"
    controls.write_text("{}")
    events = []
    comparisons = []
    clock = {"value": 100.0}
    if fail == "deadline":
        monkeypatch.setattr(driver.time, "monotonic", lambda: clock["value"])

    class Disk:
        def __init__(self, is_source=False):
            self.is_source = is_source

        def verify(self):
            return []

        def read_file(self, name):
            return source_slot if self.is_source else slots[name[-5].upper()]

    class Guest:
        def insert(self, holder, drive, remote, timeout, sha256):
            events.append(("insert", drive))

    class Run:
        def __init__(self, *a, **kw):
            self.events = []

        def see(self, state, limit=None):
            events.append(("screen", state))
            if fail == "identity" and state == "loaded_menu":
                raise RouteError("injected source identity mismatch")
            self.events.append({"screen": state, "shot": len(self.events) + 1, "time": 1.0})

        def title(self):
            self.see("title")

        def press(self, state, key, following=None):
            self.see(state)
            events.append(("key", key))
            self.events.append({"key": key})
            if following is not None:
                self.see(following)

    def checkpoint(target, directory, phase, receipt, run, disk_hash):
        events.append(("checkpoint", phase))
        if fail == phase:
            raise RouteError(f"injected {phase} failure")
        if fail == "deadline" and phase == "initial-pre-f":
            clock["value"] = 1301.0
        receipt.setdefault("item_nodes", []).append({"checkpoint": phase})
        return {"party": [{"name": name} for name in driver.BUNDLE_NAMES]}

    def compare(entry, reading, disk, letter, digest, root, *, role, previous=None):
        comparisons.append((entry["checkpoint"], letter, digest, role))
        match = not (fail == "initial-mismatch" and role == "selected-source" or
                     fail == "pre-g-mismatch" and role == "same-run-F" or
                     fail == "post-g-mismatch" and role == "same-run-G")
        return {"all_payloads_match_reference": match,
                "evidence_status": "capture_coverage_complete" if match else "payload_mismatch",
                "independently_authenticated": False, "preservation_established": False}

    def halt(guest, holder, **kwargs):
        events.append(("halt", holder))
        return {"fetched": {"disk3": {"path": str(fetched), "sha256": sha256(fetched)}}}

    def boot(guest, manifest_path, manifest, holder, proof, deadline, command):
        events.append(("boot", holder))
        return {"holder": holder, "claim": "ok claimed", "start": "ok started",
                "remotes": {"disk2": "remote-disk2", "disk3": "remote-disk3"}}

    monkeypatch.setattr(driver.pathlib.Path, "home", lambda: private_path(tmp_path))
    monkeypatch.setattr(driver, "_source_contract", lambda *a: (source, driver.BUNDLE_PREPARED_SHA256))
    monkeypatch.setattr(driver, "_source_controls", lambda *a: (
        None, None, {"guards": {"sha256": "guards"}, "identity": {"sha256": "identity"}}))
    monkeypatch.setattr(driver, "_capture_dir", lambda *a: root / "item-nodes")
    monkeypatch.setattr(driver, "_target", lambda *a: object())
    monkeypatch.setattr(driver, "_boot", boot)
    monkeypatch.setattr(driver, "SourceGuardedRun", Run)
    monkeypatch.setattr(driver, "_source_checkpoint", checkpoint)
    monkeypatch.setattr(driver, "_source_compare", compare)
    monkeypatch.setattr(driver, "_source_saved_artifact", lambda *a: {})
    monkeypatch.setattr(driver, "_source_fetched", lambda *a: (Disk(), hashes["F"]))
    monkeypatch.setattr(driver.amiga_adf.AmigaDisk, "open", lambda path: Disk(
        pathlib.Path(path) == source))
    monkeypatch.setattr(driver.route_darkness, "DARKNESS", SimpleNamespace(
        slot_letters=lambda disk: [], read_slot=lambda disk, letter: {"place": driver.BUNDLE_PLACE}))
    monkeypatch.setattr(driver.acceptance, "halt_lane", halt)
    args = SimpleNamespace(budget=1800, out=root / "source-output", run_id="synthetic-source",
                           holder="generated-holder", audio_proof=root / "audio.json",
                           manifest=prepared, controls=controls)
    return args, Guest(), events, comparisons, hashes


@pytest.mark.parametrize("stage", ["claim-expired", "upload-expired", "mute-expired",
                                   "start-failure", "cleanup-near-overall"])
def test_source_boot_refreshes_each_operation_deadline_and_keeps_cleanup(
        tmp_path, monkeypatch, stage):
    real_boot = driver._boot
    args, guest, _, _, _ = _source_coordinator(tmp_path, monkeypatch)
    monkeypatch.setattr(driver, "_boot", real_boot)
    disks = {key: pathlib.Path(row["path"]) for key, row in
             json.loads(args.manifest.read_text())["disks"].items()}
    monkeypatch.setattr(driver.route_darkness, "DARKNESS", SimpleNamespace(
        issue="360", disk_keys=tuple(disks), mounted=("disk1", "disk3"), options=(),
        slot_letters=lambda disk: [],
        read_slot=lambda disk, letter: {"place": driver.BUNDLE_PLACE}))
    monkeypatch.setattr(driver.acceptance, "_title_inputs",
                        lambda manifest, title: (disks, {}, "B"))
    monkeypatch.setattr(driver.acceptance.evidence, "git_state",
                        lambda repo: {"sha": "generated"})
    monkeypatch.setattr(driver.acceptance, "_lane_log", lambda *a: None)
    now = {"value": 100.0}
    monkeypatch.setattr(driver.time, "monotonic", lambda: now["value"])
    calls = []
    silence_reads = 0
    uploads = 0

    def silence(proof):
        nonlocal silence_reads
        silence_reads += 1
        calls.append(("silence", now["value"], None))
        if stage == "mute-expired" and silence_reads == 2:
            now["value"] += 90
        return True

    def claim(holder, timeout, **options):
        calls.append(("claim", now["value"], timeout))
        now["value"] += 1201 if stage == "claim-expired" else 250
        return f"ok claimed by {holder}"

    def put(local, remote, timeout):
        nonlocal uploads
        calls.append(("put", now["value"], timeout))
        uploads += 1
        now["value"] += (360 if stage == "upload-expired" and uploads == 3 else
                         300 if stage == "upload-expired" else
                         290 if stage == "mute-expired" else 260)
        return "ok uploaded"

    def start(holder, *drives, timeout, options):
        calls.append(("start", now["value"], timeout))
        now["value"] += 750 if stage == "cleanup-near-overall" else 175
        raise RouteError("injected start failure")

    def stop(holder, timeout):
        calls.append(("stop", now["value"], timeout))
        now["value"] += 10
        return "ok stopped"

    def release(holder, timeout):
        calls.append(("release", now["value"], timeout))
        now["value"] += 10
        return "ok released"

    guest.remote_path = driver.WinGuest.remote_path
    guest.silence = silence
    guest.claim = claim
    guest.put = put
    guest.start = start
    guest.stop = stop
    guest.release = release
    with pytest.raises(RouteError):
        driver.run_bundle_source(args, guest=guest)
    receipt = json.loads((args.out / "bundle-source-receipt.json").read_text())
    assert receipt["success"] is False
    assert ("injected start failure" if stage in ("start-failure", "cleanup-near-overall") else
            "bundle_source_deadline: boot action expired") in receipt["error"]
    assert [call[0] for call in calls if call[0] in ("stop", "release")] == (
        ["stop", "release"] if stage in ("start-failure", "cleanup-near-overall") else
        ["release"])
    cleanup = [call for call in calls if call[0] in ("stop", "release")]
    if stage == "cleanup-near-overall":
        assert cleanup == [("stop", 1880.0, 20.0), ("release", 1890.0, 10.0)]
    else:
        assert all(at >= 1300 and timeout == 30 for _, at, timeout in cleanup)
    assert len([call for call in calls if call[0] == "claim"]) == 1
    assert all(timeout == pytest.approx(min(300, 1300 - at))
               for action, at, timeout in calls if action in ("claim", "put", "start"))
    starts = [call for call in calls if call[0] == "start"]
    if stage in ("start-failure", "cleanup-near-overall"):
        assert starts == [("start", 1130.0, 170.0)]
    else:
        assert not starts
    assert uploads == (0 if stage == "claim-expired" else 3)
    checks = {"claim-expired": [100.0], "upload-expired": [100.0],
              "mute-expired": [100.0, 1220.0],
              "start-failure": [100.0, 1130.0, 1130.0],
              "cleanup-near-overall": [100.0, 1130.0, 1130.0]}[stage]
    assert [at for action, at, _ in calls if action == "silence"] == checks
    assert silence_reads == len(checks) and all(at < 1300 for at in checks)
    action_order = [action for action, _, _ in calls if action not in ("stop", "release")]
    assert action_order == (["silence", "claim"] + ["put"] * uploads
                            + ["silence"] * (len(checks) - 1)
                            + (["start"] if starts else []))


@pytest.mark.parametrize("failure", [None, "identity", "initial-pre-f", "initial-mismatch",
                                     "deadline", "pre-g", "pre-g-mismatch", "post-g",
                                     "post-g-mismatch"])
def test_source_coordinator_never_uses_a_next_save_after_a_failed_checkpoint(
        tmp_path, monkeypatch, failure):
    args, guest, events, comparisons, hashes = _source_coordinator(tmp_path, monkeypatch,
                                                                    fail=failure)
    if failure:
        with pytest.raises(RouteError):
            driver.run_bundle_source(args, guest=guest)
    else:
        result = driver.run_bundle_source(args, guest=guest)
        assert result["success"] and all(result["checks"].values())
        assert result["same_run_f_sha256"] == hashes["F"]
        assert result["same_run_g_sha256"] == hashes["G"]
        assert result["independently_authenticated"] is False
        assert result["preservation_established"] is False
        assert [(e[1], e[2], e[3]) for e in comparisons] == [
            ("F", driver.BUNDLE_SOURCE_F_SHA256, "selected-source"),
            ("F", hashes["F"], "same-run-F"), ("G", hashes["G"], "same-run-G")]
    receipt = json.loads((args.out / "bundle-source-receipt.json").read_text())
    assert receipt["success"] is (failure is None)
    if failure:
        expected = {"identity": "injected source identity mismatch",
                    "initial-pre-f": "injected initial-pre-f failure",
                    "initial-mismatch": "initial payload mismatch before F",
                    "deadline": "bundle_source_deadline: action time expired",
                    "pre-g": "injected pre-g failure",
                    "pre-g-mismatch": "pre-G differs from same-run F",
                    "post-g": "injected post-g failure",
                    "post-g-mismatch": "post-G differs from same-run G"}[failure]
        assert expected in " ".join((receipt.get("error", ""), *receipt["cleanup"]))
    assert events[0] == ("boot", args.holder)
    assert events[-1] == ("halt", args.holder)
    keys = [key for kind, key in events if kind == "key"]
    if failure in ("identity", "initial-pre-f", "initial-mismatch", "deadline"):
        assert "F" not in keys and "G" not in keys
    elif failure in ("pre-g", "pre-g-mismatch"):
        assert "F" in keys and "G" not in keys
    else:
        assert "F" in keys and "G" in keys
    if failure in ("post-g", "post-g-mismatch"):
        assert receipt["checks"]["save_g_ui_acknowledged"] is True
        assert receipt["checks"]["same_run_g_verified"] is True
        assert receipt["success"] is False
    if failure is None:
        assert keys.count("NP8") == keys.count("NP2") == 3
        assert "U" not in keys and "J" not in keys
        assert comparisons[0][0] == "initial-pre-f"
        assert events.index(("checkpoint", "initial-pre-f")) < events.index(("key", "F"))
        assert events.index(("checkpoint", "pre-g")) < events.index(("key", "G"))
        assert receipt["halt"]["fetched"]["disk3"]["path"] == "fetched-disk3.adf"
        assert "raw_hex" not in json.dumps(receipt)


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner/0600 checks require POSIX stat")
def test_source_receipt_keeps_owner_mode(tmp_path):
    receipt = {"phase": "bundle-source", "success": True,
               "independently_authenticated": False, "preservation_established": False}
    path = tmp_path / "private.json"
    driver._write_source_receipt(path, receipt)
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text()) == receipt


def test_source_receipt_blocks_raw_payload_on_every_platform(tmp_path):
    path = tmp_path / "blocked.json"
    with pytest.raises(RouteError, match="raw node bytes"):
        driver._write_source_receipt(path, {"raw_hex": "not a game byte"})
    assert not path.exists()


def test_source_unsupported_platform_fails_before_output_or_game_keys(tmp_path, monkeypatch):
    if os.name == "posix":
        monkeypatch.setattr(driver, "os", SimpleNamespace(name="nt"))
    args = SimpleNamespace(out=tmp_path / "source-output", budget=1800)

    class NoKeys:
        def __getattr__(self, operation):
            pytest.fail(f"unsupported source capture attempted guest {operation}")

    with pytest.raises(RouteError, match="POSIX owner checks are required"):
        driver.run_bundle_source(args, guest=NoKeys())
    assert not args.out.exists()
