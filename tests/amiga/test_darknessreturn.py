"""The bounded Return intervention on private media and a relocated fake script."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import struct
from types import SimpleNamespace

import pytest

from goldbox import amiga_adf, amiga_savegame, dos_savegame
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
    assert [item["chain_index"] for item in items] == [3, 4]
    assert [item["address"] for item in items] == [members[0].item_nodes[i].address for i in (3, 4)]
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
        loaded_hashes.append(kwargs["loaded_slot_sha256"])
        return {"party": [{"name": "TURBO K"}], "moved": name == "post-step"}

    monkeypatch.setattr(driver, "GuardedRun", Run)
    monkeypatch.setattr(driver, "_switch", lambda *args: Switch())
    monkeypatch.setattr(driver, "_checkpoint", checkpoint)
    monkeypatch.setattr(driver.acceptance, "halt_lane", lambda *args, **kwargs: events.append(
        "halt") or {})
    args = SimpleNamespace(receipt=previous, budget=1000, out=tmp_path / "reload",
                           run_id="new-run", holder="proof", audio_proof=tmp_path / "audio")
    assert driver.run_reload(args, guest=Guest())["success"]
    assert events == ["load", "f-loaded", "snapshot", "on", "NP8", "world", "post-step",
                      "off", "discard", "halt"]
    assert loaded_hashes == [f_hash, f_hash]
