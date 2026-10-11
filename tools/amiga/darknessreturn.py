#!/usr/bin/env python3
"""Run the bounded Pools of Darkness Return media experiment on a private disk."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import signal
import stat
import subprocess
import sys
import time
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import amiga, amigaparty, amigatrip, amigavars  # noqa: E402
from goldbox import amiga_adf, amiga_savegame  # noqa: E402
from tools.amiga import (  # noqa: E402
    acceptance,
    fasttravelrun,
    guardmaps,
    noencounters,
    route_darkness,
)
from tools.amiga.screens import PixelGuards  # noqa: E402
from tools.amiga.staging import sha256  # noqa: E402
from tools.amiga.winuaesession import RouteError, WinGuest, terminating  # noqa: E402

SOURCE = pathlib.Path.home() / ".cache/wish/acceptance/WISH-338/prep/disk3.adf"
SOURCE_HASH = "113be1f13e96648e2cd17bebfb2b4f5f6d32a88a7eb2b4ca6f49b74e906f9d80"
LIBRARY = "/Disk3/ECL.GLB"
LIBRARY_HASH = "becddc5926af6537e47b61a0c4bda35dc547352460084955c8ccc008fdd45570"
OFFSET = 0x4577
AREA = 17
ROW_SPEC = "*0x6EA6+0x8BC7"
ROW_DIGEST = "b0469054"
AREA_DIGEST = "f90bb419"
TITLE = "pools-of-darkness"
MAX_EXPERIMENT_SECONDS = 3600
SAVE_LETTER = "F"
EXPECTED_START = (22, 4)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise RouteError(reason)


def _write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _files(disk: amiga_adf.AmigaDisk) -> dict[str, bytes]:
    return {name.lower(): disk.read_file(name) for name, _ in disk.walk()}


def _library(disk: amiga_adf.AmigaDisk) -> bytes:
    problems = disk.verify()
    _require(not problems, f"disk 3 fails ADF verification: {problems}")
    return disk.read_file(LIBRARY)


def _row_from_library(library: bytes, opcode: int) -> bytes:
    _require(hashlib.sha256(library).hexdigest() == LIBRARY_HASH if opcode == 0x08
             else len(library) > OFFSET + noencounters.STATEMENT,
             "the English ECL library has an unexpected hash or length")
    row = library[OFFSET:OFFSET + noencounters.STATEMENT]
    _require(len(row) == noencounters.STATEMENT and row[0] == opcode,
             "the area-17 gate opcode does not match its phase")
    original = bytes([0x08]) + row[1:]
    _require(noencounters.digest(original) == ROW_DIGEST,
             "the area-17 statement digest differs")
    script = amiga_savegame.area_script(library, AREA)
    _require(noencounters.digest(script[:noencounters.ENTRY_TABLE]) == AREA_DIGEST,
             "the area-17 entry table differs")
    return row


def prepare_media(source: pathlib.Path, output: pathlib.Path,
                  original_manifest: pathlib.Path) -> pathlib.Path:
    """Copy and change the verified library, publishing a second manifest after readback."""
    manifest = json.loads(original_manifest.read_text())
    before_path = pathlib.Path(manifest["disks"]["disk3"]["path"])
    _require(sha256(source) == SOURCE_HASH, "the pinned substitute source differs")
    _require(sha256(before_path) == manifest["disks"]["disk3"]["sha256"],
             "the prepared image differs from its manifest")
    before = amiga_adf.AmigaDisk.open(before_path)
    before_lib = _library(before)
    _row_from_library(before_lib, 0x08)
    _require(SAVE_LETTER not in route_darkness.DARKNESS.slot_letters(before),
             "slot F is already occupied")
    reading = route_darkness.DARKNESS.read_slot(before, manifest["loaded_letter"])
    _require(reading.get("in_dungeon") is False
             and tuple(reading.get("wilderness_square", ())) == EXPECTED_START
             and len(reading.get("names", ())) == 6
             and reading["names"] == manifest.get("names_a"),
             "the prepared party is not the six recorded members outdoors at 22,4")
    output.mkdir(parents=True, exist_ok=True)
    original_files = _files(before)
    patched_path = output / "disk3-patched.adf"
    new_manifest_path = output / "prepare-patched.json"
    _require(not patched_path.exists() and not new_manifest_path.exists(),
             "the media intervention output already exists")
    intent = {
        "prepared_manifest": str(original_manifest), "prepared_image": str(before_path),
        "source": {"path": str(source), "sha256": SOURCE_HASH},
        "before_image_sha256": sha256(before_path),
        "before_library_sha256": hashlib.sha256(before_lib).hexdigest(),
        "library": LIBRARY, "block": 6, "offset": OFFSET, "area": AREA,
        "row_spec": ROW_SPEC, "row_digest": ROW_DIGEST, "area_digest": AREA_DIGEST,
        "before_opcode": 8, "after_opcode": 9,
    }
    _write_json(output / "media-intent.json", intent)
    patched = bytearray(before_lib)
    patched[OFFSET] = 0x09
    disk = amiga_adf.AmigaDisk.open(before_path)
    disk.write_file(LIBRARY, bytes(patched))
    disk.save(patched_path)
    readback = amiga_adf.AmigaDisk.open(patched_path)
    changed_lib = _library(readback)
    _require(changed_lib == bytes(patched), "the changed library did not read back exactly")
    _row_from_library(changed_lib, 0x09)
    after_files = _files(readback)
    _require(original_files.keys() == after_files.keys(), "the ADF file set changed")
    _require(all(blob == after_files[name] for name, blob in original_files.items()
                 if name != LIBRARY.lower()), "a file other than the library changed")
    intervention = {**intent, "after_image_sha256": sha256(patched_path),
                    "after_library_sha256": hashlib.sha256(changed_lib).hexdigest(),
                    "changed_image": str(patched_path), "changed_manifest": str(new_manifest_path)}
    changed_manifest = {**manifest, "disks": {**manifest["disks"],
                        "disk3": {"path": str(patched_path), "sha256": sha256(patched_path)}},
                        "encounter_media": intervention}
    _write_json(new_manifest_path, changed_manifest)
    return new_manifest_path


def restore_fetched(raw: pathlib.Path, intervention: dict, output: pathlib.Path,
                    *, require_f: bool = True) -> dict:
    """Restore only the fetched library, retaining every game-written save file."""
    original = amiga_adf.AmigaDisk.open(intervention["prepared_image"])
    original_lib = _library(original)
    _row_from_library(original_lib, 0x08)
    _require(hashlib.sha256(original_lib).hexdigest() == intervention["before_library_sha256"],
             "the unmodified prepared library changed")
    fetched = amiga_adf.AmigaDisk.open(raw)
    changed = _library(fetched)
    _require(hashlib.sha256(changed).hexdigest() == intervention["after_library_sha256"],
             "the fetched library differs from the staged change")
    _row_from_library(changed, 0x09)
    before_files = _files(fetched)
    _require(not require_f or "/save/savgamf.pty" in before_files,
             "the game did not write slot F")
    output.parent.mkdir(parents=True, exist_ok=True)
    _require(not output.exists(), "the restored disk output already exists")
    disk = amiga_adf.AmigaDisk.open(raw)
    disk.write_file(LIBRARY, original_lib)
    disk.save(output)
    readback = amiga_adf.AmigaDisk.open(output)
    _require(_library(readback) == original_lib, "the original library did not read back")
    after_files = _files(readback)
    _require(before_files.keys() == after_files.keys(), "restoration changed the fetched file set")
    _require(all(blob == after_files[name] for name, blob in before_files.items()
                 if name != LIBRARY.lower()), "restoration changed a game-written file")
    return {"raw": {"path": str(raw), "sha256": sha256(raw)},
            "restored": {"path": str(output), "sha256": sha256(output)},
            "library_sha256": hashlib.sha256(original_lib).hexdigest(),
            "slot_f_sha256": (hashlib.sha256(after_files["/save/savgamf.pty"]).hexdigest()
                              if "/save/savgamf.pty" in after_files else None)}


def _gate_row() -> noencounters.Row:
    matches = [row for row in noencounters.rows_for(TITLE)
               if row.spec == ROW_SPEC and row.digest == ROW_DIGEST
               and row.area == AREA_DIGEST]
    _require(len(matches) == 1, "the area-17 encounter row is missing or ambiguous")
    return matches[0]


def adopt_loaded_media(holder: str, target: amiga.AmigaTarget,
                       state: noencounters.WinuaeState, original_row: bytes,
                       guest: WinGuest) -> dict:
    """Journal this holder's loaded media change and adopt it through the normal switch."""
    guest.lane(holder, timeout=30)
    row = _gate_row()
    memory = noencounters.PipeMemory(target)
    memory.clear()
    address = memory.resolve(ROW_SPEC)
    script_address = memory.resolve(noencounters.script_spec(row))
    _require(address is not None and script_address is not None,
             "the area-17 script pointer is absent")
    area = memory.read(script_address, noencounters.ENTRY_TABLE)
    statement = memory.read(address, noencounters.STATEMENT)
    _require(noencounters.digest(area) == AREA_DIGEST, "the loaded area is not area 17")
    _require(len(original_row) == noencounters.STATEMENT
             and noencounters.digest(original_row) == ROW_DIGEST
             and statement == bytes([0x09]) + original_row[1:],
             "the loaded gate is not the verified disk-supplied statement")
    saved = state.load()
    _require(saved.get("title") in (None, TITLE), "another title owns the encounter journal")
    _require(not saved["rows"] or saved["on"], "unresolved encounter rows exist while off")
    _require(all(r.get("title") == TITLE for r in saved["rows"]),
             "another title has outstanding encounter rows")
    record = {"kind": noencounters.GATE, "spec": ROW_SPEC, "address": address,
              "digest": ROW_DIGEST, "original": original_row[:1].hex(),
              "changed": statement[:1].hex(), "title": TITLE}
    rows = [r for r in saved["rows"] if not (
        r.get("address") == address and r.get("spec") == ROW_SPEC)]
    rows.append(record)
    state.save({"on": True, "title": TITLE, "speculative": False,
                "anchor_base": target.anchor_base, "data_base": target.data_base,
                "rows": rows})
    fresh = noencounters.WinuaeEncounters(TITLE, target, state=state,
                                         lane_check=lambda: guest.lane(holder, timeout=30))
    reply = fresh.keys([])
    _require("error" not in reply and "stopped" not in reply,
             f"the encounter journal could not adopt the media row: {reply}")
    current = state.load()
    _require(current["on"] and any(r.get("address") == address and r.get("spec") == ROW_SPEC
                                   for r in current["rows"]),
             "the current media change was not retained in the journal")
    memory.clear()
    _require(memory.read(address, noencounters.STATEMENT) == statement,
             "adoption changed the current gate")
    return {"address": address, "row": record, "adoption": reply,
            "state": current}


def restore_loaded_media(holder: str, target: amiga.AmigaTarget,
                         state: noencounters.WinuaeState, original_row: bytes,
                         guest: WinGuest) -> dict:
    """Turn the journal off and independently read the original loaded gate."""
    adopt_loaded_media(holder, target, state, original_row, guest)
    switch = noencounters.WinuaeEncounters(TITLE, target, state=state,
                                          lane_check=lambda: guest.lane(holder, timeout=30))
    reply = switch.off()
    _require("error" not in reply, f"the RAM gate did not restore: {reply}")
    memory = noencounters.PipeMemory(target)
    memory.clear()
    address = memory.resolve(ROW_SPEC)
    area_address = memory.resolve(noencounters.script_spec(_gate_row()))
    _require(address is not None and area_address is not None, "the script moved during restoration")
    statement = memory.read(address, noencounters.STATEMENT)
    area = memory.read(area_address, noencounters.ENTRY_TABLE)
    remaining = state.load()
    _require(statement == original_row and noencounters.digest(area) == AREA_DIGEST
             and not remaining["on"] and not remaining["rows"],
             "the original gate and area did not read back before save")
    return {"off": reply, "address": address, "statement_digest": noencounters.digest(statement),
            "area_digest": noencounters.digest(area), "journal": remaining}


class RestoringGuest:
    """Restore the fetched disk 3 library before halt_lane releases this holder."""

    def __init__(self, guest: WinGuest, holder: str, remote: str,
                 intervention: dict, output: pathlib.Path, *, require_f: bool):
        self.guest, self.holder, self.remote = guest, holder, remote
        self.intervention, self.output, self.require_f = intervention, output, require_f
        self.receipt: dict | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.guest, name)

    def get(self, remote: str, local: pathlib.Path, timeout: float) -> Any:
        result = self.guest.get(remote, local, timeout=timeout)
        if remote == self.remote:
            _require(self.guest.holder == self.holder,
                     "disk restoration is attached to another holder")
            self.receipt = restore_fetched(local, self.intervention, self.output,
                                           require_f=self.require_f)
            _write_json(self.output.with_suffix(".restore.json"), self.receipt)
        return result


def _check_source() -> None:
    _require(sha256(SOURCE) == SOURCE_HASH, "the pinned source changed during the run")


def _capture_nodes(path: pathlib.Path, members: tuple, reading: dict) -> dict:
    """Keep exact live nodes private and verify them against this read's hashes."""
    _require(bool(members) and members[0].name == "TURBO K" and members[0].slot == 0,
             "the capture's first member is not TURBO K in slot 0")
    nodes = members[0].item_nodes
    _require(len(nodes) > 4, "the capture is missing first-member items 3 or 4")
    saved = []
    for index in (3, 4):
        node = nodes[index]
        _require(len(node.raw) == 0x42, "the capture item node is not 66 bytes")
        digest = hashlib.sha256(node.raw).hexdigest()
        _require(digest == reading["party"][0]["items"][index],
                 "the captured node differs from the ordinary live receipt")
        saved.append({"slot": members[0].slot, "name": members[0].name,
                      "chain_index": index, "address": node.address, "length": len(node.raw),
                      "raw_hex": node.raw.hex(), "sha256": digest,
                      "tail20_sha256": hashlib.sha256(node.raw[0x2e:0x42]).hexdigest()})
    payload = (json.dumps({"items": saved}, indent=2, sort_keys=True) + "\n").encode()
    temp = path.with_name(path.name + ".tmp")
    try:
        with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
            file.write(payload)
        temp.replace(path)
        _require(hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(payload).hexdigest(),
                 "the private node file did not read back")
    finally:
        temp.unlink(missing_ok=True)
    return {"file_sha256": hashlib.sha256(payload).hexdigest()}


def _live_read(target: amiga.AmigaTarget, *, capture: pathlib.Path | None = None) -> dict:
    row = amigatrip.row_for(TITLE)
    members = amigaparty.read_party(target)
    reading = {"trip": fasttravelrun._reading(target, row),
            "variables": [v.as_log() for v in amigavars.read_variables(
                target, TITLE, (0x25, 0x26, 0x34, 0x35, 0x129, 0xC1, 0xBF))],
            "party": None if members is None else [
                {"name": m.name, "slot": m.slot, "hp": m.hp, "hp_max": m.hp_max,
                 "items": [hashlib.sha256(node).hexdigest() for _, node in m.items()],
                 "effects": [hashlib.sha256(node).hexdigest() for _, node in m.effects()]}
                 for m in members]}
    if capture is not None:
        reading["capture"] = _capture_nodes(capture, members, reading)
    return reading


def _private_directory(actual: os.stat_result, owner: int) -> bool:
    return actual.st_uid == owner and stat.S_IMODE(actual.st_mode) == 0o700


def _capture_dir(run_id: str) -> pathlib.Path:
    _require(run_id not in ("", ".", "..") and pathlib.Path(run_id).name == run_id,
             "the capture run ID must be one path component")
    _require(os.name == "posix", "private node capture requires POSIX owner and mode checks")
    directory = pathlib.Path.home() / ".cache/wish/acceptance/WISH-360" / run_id / "item-nodes"
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    actual = directory.stat()
    _require(_private_directory(actual, os.getuid()),
             "the private node directory has the wrong owner or mode")
    return directory


def _checkpoint(target: amiga.AmigaTarget, directory: pathlib.Path, checkpoint: str,
                 receipt: dict, run: GuardedRun, *, disk_sha256: str,
                 loaded_slot_sha256: str, intervention: dict | None = None) -> dict:
    path = directory / f"{checkpoint}.json"
    reading = _live_read(target, capture=path)
    proof = reading.pop("capture")
    _require(path.is_file(), "the private node capture is missing")
    receipt.setdefault("item_nodes", []).append({
        "checkpoint": checkpoint, "path": path.relative_to(directory.parent.parent).as_posix(),
        "file_sha256": proof["file_sha256"], "order": len(receipt.get("item_nodes", [])),
        "time": time.time(), "holder": receipt["holder"], "phase": receipt["phase"],
        "title": TITLE, "source_disk_sha256": disk_sha256,
        "loaded_slot_sha256": loaded_slot_sha256, "staged_flag": receipt.get("staged_flag"),
        "media_intervention": None if intervention is None else {
            "before_image_sha256": intervention["before_image_sha256"],
            "after_image_sha256": intervention["after_image_sha256"]},
        "screenshot": None if not run.events else {
            "shot": run.events[-1]["shot"], "time": run.events[-1]["time"],
            "screen": run.events[-1]["screen"]},
    })
    return reading


def _value(reading: dict, variable: int) -> int:
    match = [v for v in reading["variables"] if v["var"] == f"${variable:04X}"]
    _require(len(match) == 1 and match[0]["value"] is not None,
             f"the live variable ${variable:04X} is unreadable")
    return match[0]["value"]


def _require_world(reading: dict, names: list[str], *, area: int,
                   cell: tuple[int, int] | None = None) -> None:
    _require(reading["trip"]["area"] == area, f"the party is not in area {area}")
    _require(reading["party"] is not None and
             [m["name"] for m in reading["party"]] == names,
             "the live party names differ from the prepared save")
    if cell is not None:
        _require((_value(reading, 0x25), _value(reading, 0x26)) == cell,
                 f"the wilderness cell is not {cell}")


class GuardedRun:
    """Issue the fixed game's keys only from states in the measured Darkness guard map."""

    def __init__(self, guest: WinGuest, holder: str, out: pathlib.Path,
                 guards: PixelGuards, deadline: float):
        self.guest, self.holder, self.out = guest, holder, out
        self.guards, self.deadline = guards, deadline
        self.shot = 0
        self.events: list[dict] = []
        self.out.mkdir(parents=True, exist_ok=True)

    def left(self, cap: float) -> float:
        remaining = min(cap, self.deadline - time.monotonic())
        _require(remaining > 0, "the combined experiment deadline expired")
        return remaining

    def see(self, state: str, limit: float | None = None) -> pathlib.Path:
        _require(state in self.guards, f"the required {state} screen has no existing guard")
        start = time.monotonic()
        wait = self.left(limit or route_darkness.DARKNESS.min_waits.get(state, 30) + 15)
        while time.monotonic() - start < wait:
            self.shot += 1
            raw = self.out / f"{self.shot:03d}-{state}-raw.png"
            crop = self.out / f"{self.shot:03d}-{state}.png"
            if self.guest.grab(state, raw, crop, self.left(20)) and self.guards(state, crop):
                self.events.append({"screen": state, "crop": str(crop),
                                    "time": time.time(), "shot": self.shot})
                return crop
            time.sleep(min(1, self.left(1)))
        raise RouteError(f"{state} did not match its existing guard within {wait:.0f}s")

    def press(self, state: str, key: str, following: str | None = None) -> None:
        self.see(state)
        self.guest.press(self.holder, key, timeout=self.left(30))
        self.events.append({"key": key, "from": state, "time": time.time()})
        if following is not None:
            self.see(following)

    def title(self) -> None:
        beginning = time.monotonic()
        for attempt in range(4):
            try:
                self.see("title", min(120, self.left(420 - (time.monotonic() - beginning))))
                return
            except RouteError:
                if attempt == 3 or time.monotonic() - beginning < route_darkness.DARKNESS.boot_span:
                    if attempt == 3:
                        raise
                    continue
                self.see("intro", 10)
                self.guest.press(self.holder, "ESC", timeout=self.left(30))
                self.events.append({"key": "ESC", "from": "intro", "time": time.time()})

    def load(self, manifest: dict, remotes: dict, *, view_sheet: bool = False) -> None:
        self.title()
        self.press("title", "P", "party_menu")
        self.press("party_menu", "L", "load_from")
        self.press("load_from", "P", "load_picker")
        self.press("load_picker", manifest["loaded_letter"], "disk2_prompt")
        self.guest.insert(self.holder, 0, remotes["disk2"],
                          timeout=self.left(60), sha256=manifest["disks"]["disk2"]["sha256"])
        self.press("disk2_prompt", "SPACE", "loaded_menu")
        if view_sheet:
            self.press("loaded_menu", "V", "sheet")
            self.press("sheet", "E", "loaded_menu")
        self.press("loaded_menu", "B", "journal")
        self.press("journal", "X", "journal_answer")
        self.press("journal_answer", "RET")
        try:
            self.see("world", 60)
        except RouteError:
            for _ in range(3):
                self.press("continue", "RET")
                try:
                    self.see("world", 60)
                    return
                except RouteError:
                    pass
            raise RouteError("the world did not follow the bounded journal Continue") from None


def _export_guards(out: pathlib.Path) -> PixelGuards:
    directory = out / "guards-export"
    _require(not directory.exists(), "guard export already exists")
    _require(guardmaps.main(["--maps", str(pathlib.Path(guardmaps.__file__).parent),
                             "export", "--title", "darkness", "--out", str(directory)]) == 0,
             "the Darkness guard export failed")
    guard = PixelGuards(directory / "guards.json")
    required = {"title", "intro", "party_menu", "load_from", "load_picker",
                "disk2_prompt", "loaded_menu", "journal", "journal_answer",
                "world", "continue", "sheet", "camp", "camp_save_picker", "exit_game"}
    _require(required <= guard.rules.keys(),
             f"required guards are missing: {sorted(required - guard.rules.keys())}")
    return guard


def _original_live(target: amiga.AmigaTarget, original: bytes) -> dict:
    memory = noencounters.PipeMemory(target)
    memory.clear()
    address = memory.resolve(ROW_SPEC)
    script_address = memory.resolve(noencounters.script_spec(_gate_row()))
    _require(address is not None and script_address is not None, "the area-17 pointer is absent")
    actual = memory.read(address, noencounters.STATEMENT)
    area = memory.read(script_address, noencounters.ENTRY_TABLE)
    _require(actual == original and noencounters.digest(area) == AREA_DIGEST,
             "the gate was changed again before the save letter")
    return {"address": address, "statement_digest": noencounters.digest(actual),
            "area_digest": noencounters.digest(area)}


def _verified_reload_gate(target: amiga.AmigaTarget, state: noencounters.WinuaeState,
                          original: bytes, reply: dict) -> dict:
    """Require the reload switch to have changed this area-17 gate before NP8."""
    saved = state.load()
    memory = noencounters.PipeMemory(target)
    memory.clear()
    address = memory.resolve(ROW_SPEC)
    script_address = memory.resolve(noencounters.script_spec(_gate_row()))
    _require(address is not None and script_address is not None,
             "reload area-17 gate pointer is absent")
    applied = [row for row in reply.get("rows", [])
               if row.get("row") == ROW_SPEC and row.get("address") == address
               and row.get("new") == "09" and "stopped" not in row
               and "error" not in row]
    journalled = [row for row in saved["rows"]
                  if row.get("spec") == ROW_SPEC and row.get("address") == address
                  and row.get("digest") == ROW_DIGEST
                  and row.get("original") == "08" and row.get("changed") == "09"]
    _require(saved["on"] and len(applied) == 1 and len(journalled) == 1,
             "reload area-17 gate was not applied and journalled")
    actual = memory.read(address, noencounters.STATEMENT)
    area = memory.read(script_address, noencounters.ENTRY_TABLE)
    _require(noencounters.digest(original) == ROW_DIGEST
             and actual == b"\x09" + original[1:]
             and noencounters.digest(area) == AREA_DIGEST,
             "reload area-17 gate readback differs from the prepared library")
    return {"address": address, "statement_digest": noencounters.digest(actual),
            "area_digest": noencounters.digest(area)}


def _trip(holder: str, disks: pathlib.Path, out: pathlib.Path, left: float) -> list[dict]:
    command = [sys.executable, str(pathlib.Path(fasttravelrun.__file__)),
               "--holder", holder, "--disks", str(disks), "--title", TITLE,
               "--budget", "900", "--to", "22", "--back", "--arrival-answer", "RET",
               "--peek-var", "25,26,34,35,129,C1,BF", "--out", str(out)]
    out.mkdir(parents=True, exist_ok=False)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    try:
        stdout, stderr = process.communicate(timeout=left)
    except subprocess.TimeoutExpired as exc:
        process.send_signal(signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        (out / "driver-stdout.txt").write_text(stdout)
        (out / "driver-stderr.txt").write_text(stderr)
        raise RouteError("the two-leg trip exceeded the combined deadline") from exc
    (out / "driver-stdout.txt").write_text(stdout)
    (out / "driver-stderr.txt").write_text(stderr)
    _require(process.returncode == 0,
             f"the guarded trip stopped with code {process.returncode}: {stderr[-500:]}")
    try:
        legs = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
    except json.JSONDecodeError as exc:
        raise RouteError("the trip returned an unreadable leg receipt") from exc
    _require(len(legs) == 2 and all(leg.get("result") == "idle"
                                   and leg.get("settled") for leg in legs),
             "the trip did not finish two settled legs")
    _require(17 in legs[0].get("areas_seen", []) and 22 in legs[0]["areas_seen"]
             and 22 in legs[1].get("areas_seen", []) and 17 in legs[1]["areas_seen"],
             "the trip did not travel 17 to 22 and Return to 17")
    _require(legs[0].get("arrival_keys") == ["RET"]
             and legs[1].get("arrival_keys") == [],
             "the trip answered a prompt other than the one guarded Return bar")
    return legs


def _stage_flag(target: amiga.AmigaTarget) -> dict:
    address, rng = amigavars.resolve(target, TITLE, 0x129)
    old = target.read(address, rng.size)
    _require(old == b"\0", "the staged giants flag is not initially 00")
    target.write(address, bytes([old[0] | 2]))
    _require(target.read(address, rng.size) == b"\x02", "the staged giants flag did not read back")
    return {"var": "0x129", "address": address, "before": old.hex(), "after": "02"}


def _switch(holder: str, target: amiga.AmigaTarget, guest: WinGuest,
            state: noencounters.WinuaeState) -> noencounters.WinuaeEncounters:
    return noencounters.WinuaeEncounters(
        TITLE, target, state=state, lane_check=lambda: guest.lane(holder, timeout=30),
        press=lambda key: guest.press(holder, key, timeout=30))


def _step_under_switch(holder: str, target: amiga.AmigaTarget, guest: WinGuest,
                       state: noencounters.WinuaeState, original: bytes) -> dict:
    adopted = adopt_loaded_media(holder, target, state, original, guest)
    response = _switch(holder, target, guest, state).keys(["NP8"])
    _require(response.get("pressed") == ["NP8"] and "error" not in response
             and "stopped" not in response, f"the guarded NP8 did not land: {response}")
    return {"adopted": adopted, "key": response}


def _restored_source(receipt: dict) -> pathlib.Path:
    checks = receipt.get("checks", {})
    _require(not checks.get("save_ui_acknowledged") or checks.get("post_save_capture") is True,
             "P2 post-save item capture is missing or failed")
    required = {"legs", "step", "save", "post_save_capture", "ram_restored",
                "disk_restored", "source_unchanged"}
    _require(receipt.get("success") is True and required <= checks.keys()
             and all(checks[key] is True for key in required),
             "P2 has a failed or missing prerequisite check")
    restored = receipt.get("disk_restoration", {}).get("restored", {})
    path = pathlib.Path(restored.get("path", ""))
    _require(path.is_file() and sha256(path) == restored.get("sha256"),
             "the restored disk named by P2 does not match its receipt")
    disk = amiga_adf.AmigaDisk.open(path)
    _require(hashlib.sha256(_library(disk)).hexdigest() == LIBRARY_HASH,
             "the reload seed does not hold the original English library")
    _require("/save/savgamf.pty" in _files(disk), "the restored disk has no game-written F")
    return path


def _prepare_p2(run_id: str, out: pathlib.Path) -> tuple[pathlib.Path, dict]:
    _check_source()
    manifest_path = acceptance.prepare(route_darkness.DARKNESS, run_id,
                                       substitute=SOURCE, substitute_letter="G", issue="360")
    changed_path = prepare_media(SOURCE, out, manifest_path)
    return changed_path, json.loads(changed_path.read_text())


def _target(holder: str) -> amiga.AmigaTarget:
    target = amiga.AmigaTarget(amiga.WinuaePipe(holder=holder), amiga.MACHINES[TITLE])
    target.locate()
    return target


def _boot(guest: WinGuest, manifest_path: pathlib.Path, manifest: dict,
          holder: str, proof: pathlib.Path, deadline: float, command: list[str]) -> dict:
    _require(deadline - time.monotonic() > 600,
             "less than a ten-minute boot and load allowance remains")
    return acceptance.boot_lane(manifest_path, manifest, route_darkness.DARKNESS,
                                guest=guest, holder=holder, audio_proof=proof,
                                wait_lane=0, timeout=min(300, deadline - time.monotonic()),
                                command=command)


def _halt(guest: WinGuest, holder: str, manifest_path: pathlib.Path,
           command: list[str], intervention: dict | None,
           output: pathlib.Path | None, require_f: bool) -> tuple[dict, dict | None]:
    if intervention is not None and output is not None:
        remote = WinGuest.remote_path(route_darkness.DARKNESS.issue, holder, "disk3")
        wrapped = RestoringGuest(guest, holder, remote, intervention, output,
                                  require_f=require_f)
    else:
        wrapped = guest
    halted = acceptance.halt_lane(wrapped, holder, manifest_path=manifest_path,
                                  command=command)
    if isinstance(wrapped, RestoringGuest):
        _require(wrapped.receipt is not None,
                 "halt released the lane without a disk-3 restoration receipt")
        return halted, wrapped.receipt
    return halted, None


def run_p2(args: argparse.Namespace, *, guest: WinGuest | None = None) -> dict:
    """One prepared boot, one guarded Return trip, one save and restored fetch."""
    _require(args.previous_return_attempts == 2,
             "P2 must retain the two previous failed Return attempts")
    _require(0 < args.budget <= MAX_EXPERIMENT_SECONDS, "P2 budget exceeds one hour")
    out = args.out
    _require(not out.exists(), "the P2 output directory already exists")
    out.mkdir(parents=True)
    began = time.time()
    deadline_wall = began + args.budget
    deadline = time.monotonic() + args.budget
    receipt: dict[str, Any] = {"phase": "p2", "run_id": args.run_id,
                               "holder": args.holder, "previous_return_attempts": 2,
                               "cumulative_return_attempts": 3,
                               "began": began, "combined_deadline": deadline_wall,
                               "checks": {"post_save_capture": False},
                               "success": False, "cleanup": []}
    manifest_path = None
    manifest = None
    capture_dir = None
    booted = False
    target = None
    run = None
    state = noencounters.WinuaeState(noencounters.winuae_state_path(args.holder))
    snapshots: list[str] = []
    guest = guest or WinGuest()
    command = [str(pathlib.Path(__file__)), "p2", "--run-id", args.run_id,
               "--holder", args.holder]
    try:
        guards = _export_guards(out)
        manifest_path, manifest = _prepare_p2(args.run_id, out)
        intervention = manifest["encounter_media"]
        capture_dir = _capture_dir(args.run_id)
        disk_hash = SOURCE_HASH
        slot_hash = hashlib.sha256(amiga_adf.AmigaDisk.open(
            manifest["disks"]["disk3"]["path"]).read_file(
                f"/SAVE/savgam{manifest['loaded_letter']}.pty")).hexdigest()
        original = _row_from_library(_library(amiga_adf.AmigaDisk.open(
            intervention["prepared_image"])), 0x08)
        boot = _boot(guest, manifest_path, manifest, args.holder, args.audio_proof,
                     deadline, command)
        booted = True
        receipt["boot"] = boot
        run = GuardedRun(guest, args.holder, out / "screens", guards, deadline)
        run.load(manifest, boot["remotes"])
        target = _target(args.holder)
        before = _checkpoint(target, capture_dir, "before-staging", receipt, run,
                             disk_sha256=disk_hash, loaded_slot_sha256=slot_hash,
                             intervention=intervention)
        _require_world(before, manifest["names_a"], area=AREA, cell=EXPECTED_START)
        receipt["before"] = before
        guest.snapshot("b0", args.holder)
        snapshots.append("b0")
        receipt["staged_flag"] = _stage_flag(target)
        guest.snapshot("b1", args.holder)
        snapshots.append("b1")
        receipt["first_adoption"] = adopt_loaded_media(args.holder, target, state,
                                                          original, guest)
        legs = _trip(args.holder, manifest_path.parent, out / "trip",
                     run.left(2000))
        receipt["legs"] = legs
        receipt["checks"]["legs"] = True
        run.see("world", 60)
        target = _target(args.holder)
        returned = _checkpoint(target, capture_dir, "post-return", receipt, run,
                               disk_sha256=disk_hash, loaded_slot_sha256=slot_hash,
                               intervention=intervention)
        _require_world(returned, manifest["names_a"], area=AREA, cell=EXPECTED_START)
        receipt["returned"] = returned
        receipt["post_return_adoption"] = adopt_loaded_media(args.holder, target,
                                                               state, original, guest)
        guest.snapshot("p2-before-step", args.holder)
        snapshots.append("p2-before-step")
        receipt["step_command"] = _step_under_switch(args.holder, target, guest,
                                                       state, original)
        run.see("world", 60)
        stepped = _checkpoint(target, capture_dir, "post-step", receipt, run,
                              disk_sha256=disk_hash, loaded_slot_sha256=slot_hash,
                              intervention=intervention)
        _require_world(stepped, manifest["names_a"], area=AREA)
        _require((_value(stepped, 0x25), _value(stepped, 0x26)) != EXPECTED_START,
                 "NP8 did not move the wilderness marker")
        receipt["stepped"] = stepped
        receipt["checks"]["step"] = True
        receipt["ram_restoration"] = restore_loaded_media(args.holder, target,
                                                            state, original, guest)
        receipt["checks"]["ram_restored"] = True
        run.press("world", "E", "camp")
        run.press("camp", "S", "camp_save_picker")
        receipt["pre_save_gate"] = _original_live(target, original)
        _require(not state.load()["on"] and not state.load()["rows"],
                  "the encounter journal is not off before F")
        _checkpoint(target, capture_dir, "pre-f", receipt, run,
                    disk_sha256=disk_hash, loaded_slot_sha256=slot_hash,
                    intervention=intervention)
        run.press("camp_save_picker", SAVE_LETTER, "exit_game")
        run.press("exit_game", "N", "camp")
        receipt["checks"]["save_ui_acknowledged"] = True
        _checkpoint(target, capture_dir, "post-save-quit", receipt, run,
                    disk_sha256=disk_hash, loaded_slot_sha256=slot_hash,
                    intervention=intervention)
        receipt["checks"]["post_save_capture"] = True
        receipt["screens"] = run.events
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if run is not None:
            receipt["screens"] = run.events
        if booted and target is not None:
            try:
                needs_restore = state.load().get("on")
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append(f"read RAM journal: {exc}")
                needs_restore = False
            if needs_restore:
                try:
                    receipt["failure_ram_restoration"] = _switch(args.holder, target,
                                                                    guest, state).off()
                except Exception as exc:  # noqa: BLE001 - preserve each failed cleanup
                    receipt["cleanup"].append(f"RAM restore: {exc}")
        if booted:
            for name in snapshots:
                try:
                    guest.discard(name, args.holder)
                except Exception as exc:  # noqa: BLE001
                    receipt["cleanup"].append(f"discard {name}: {exc}")
            try:
                halted, restored = _halt(
                    guest, args.holder, manifest_path, command,
                    manifest["encounter_media"], out / "disk3-restored.adf",
                    receipt["checks"].get("save_ui_acknowledged", False))
                receipt["halt"] = halted
                receipt["disk_restoration"] = restored
                receipt["checks"]["disk_restored"] = restored is not None
                if receipt["checks"].get("save_ui_acknowledged") and restored is not None:
                    slot_f_hash = restored["slot_f_sha256"]
                    saved_disk = amiga_adf.AmigaDisk.open(restored["restored"]["path"])
                    saved_reading = route_darkness.DARKNESS.read_slot(saved_disk, SAVE_LETTER)
                    _require(slot_f_hash is not None and saved_reading.get("sha256") == slot_f_hash,
                             "the restored game-written F does not match its independent slot read")
                    _require(not saved_reading.get("missing") and not saved_reading.get("decode_error"),
                             f"the restored game-written F does not decode: {saved_reading.get('decode_error')}")
                    stepped = receipt["stepped"]
                    names = [member["name"] for member in stepped["party"]]
                    _require(len(names) == 6 and saved_reading.get("names") == names,
                             "the restored game-written F does not hold the stepped party")
                    _require(saved_reading.get("in_dungeon") is False and
                             tuple(saved_reading.get("wilderness_square") or ()) ==
                             (_value(stepped, 0x25), _value(stepped, 0x26)),
                             "the restored game-written F is not at the stepped outdoor cell")
                    place = saved_reading.get("place") or {}
                    _require(tuple(place.get(field) for field in ("x", "y", "facing")) ==
                             tuple(stepped["trip"]["square"]),
                             "the restored game-written F has another square or facing")
                    saved_flag = amiga_savegame.pod_parse(
                        amiga_savegame.pod_read_slot(saved_disk, SAVE_LETTER)).var(0x129)
                    _require(saved_flag == _value(stepped, 0x129) ==
                             int(receipt["staged_flag"]["after"], 16),
                             "the restored game-written F lost the staged flag")
                    receipt["game_written_f_sha256"] = slot_f_hash
                    receipt["checks"]["save"] = True
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append(f"halt and restore: {exc}")
        try:
            _check_source()
            receipt["checks"]["source_unchanged"] = True
        except Exception as exc:  # noqa: BLE001
            receipt["cleanup"].append(f"source hash: {exc}")
        receipt["success"] = ("error" not in receipt and not receipt["cleanup"] and
                              all(receipt["checks"].get(key) is True for key in
                                  ("legs", "step", "save", "post_save_capture", "ram_restored",
                                   "disk_restored", "source_unchanged")))
        _write_json(out / "p2-receipt.json", receipt)
    if not receipt["success"]:
        raise RouteError(receipt.get("error") or "; ".join(receipt["cleanup"]))
    return receipt


def run_reload(args: argparse.Namespace, *, guest: WinGuest | None = None) -> dict:
    """Load the restored game-written F and prove an ordinary RAM switch can step it."""
    receipt_path = args.receipt
    p2 = json.loads(receipt_path.read_text())
    source = _restored_source(p2)
    _check_source()
    _require(0 < args.budget <= 1200, "reload has at most 1,200 seconds")
    allowed = min(args.budget, p2["combined_deadline"] - time.time())
    _require(allowed > 600, "less than a ten-minute load allowance remains")
    out = args.out
    _require(not out.exists(), "the reload output directory already exists")
    out.mkdir(parents=True)
    deadline = time.monotonic() + allowed
    receipt: dict[str, Any] = {"phase": "reload", "run_id": args.run_id,
                               "holder": args.holder, "p2_receipt": str(receipt_path),
                               "combined_deadline": p2["combined_deadline"],
                               "previous_return_attempts": p2["cumulative_return_attempts"],
                               "checks": {}, "success": False, "cleanup": []}
    guest = guest or WinGuest()
    state = noencounters.WinuaeState(noencounters.winuae_state_path(args.holder))
    manifest_path = None
    booted = False
    target = None
    snapshots: list[str] = []
    capture_dir = None
    command = [str(pathlib.Path(__file__)), "reload", "--run-id", args.run_id,
               "--holder", args.holder]
    try:
        guards = _export_guards(out)
        manifest_path = acceptance.prepare(route_darkness.DARKNESS, args.run_id,
                                           substitute=source, substitute_letter=SAVE_LETTER,
                                           issue="360")
        manifest = json.loads(manifest_path.read_text())
        capture_dir = _capture_dir(args.run_id)
        disk_hash = sha256(source)
        slot_hash = hashlib.sha256(amiga_adf.AmigaDisk.open(
            manifest["disks"]["disk3"]["path"]).read_file(
                f"/SAVE/savgam{manifest['loaded_letter']}.pty")).hexdigest()
        prepared = amiga_adf.AmigaDisk.open(manifest["disks"]["disk3"]["path"])
        original = _row_from_library(_library(prepared), 0x08)
        reading = route_darkness.DARKNESS.read_slot(prepared, manifest["loaded_letter"])
        _require(reading.get("in_dungeon") is False and reading.get("names") ==
                 [m["name"] for m in p2["stepped"]["party"]],
                 "the restored F party did not prepare for reload")
        saved_cell = tuple(reading.get("wilderness_square", ()))
        _require(saved_cell == (_value(p2["stepped"], 0x25),
                                _value(p2["stepped"], 0x26)),
                 "the game-written F did not retain the moved wilderness marker")
        receipt["saved"] = reading
        boot = _boot(guest, manifest_path, manifest, args.holder, args.audio_proof,
                     deadline, command)
        booted = True
        receipt["boot"] = boot
        run = GuardedRun(guest, args.holder, out / "screens", guards, deadline)
        run.load(manifest, boot["remotes"], view_sheet=True)
        target = _target(args.holder)
        before = _checkpoint(target, capture_dir, "f-loaded", receipt, run,
                             disk_sha256=disk_hash, loaded_slot_sha256=slot_hash)
        _require_world(before, reading["names"], area=AREA, cell=saved_cell)
        receipt["loaded"] = before
        receipt["checks"]["load"] = True
        guest.snapshot("reload-before-step", args.holder)
        snapshots.append("reload-before-step")
        switched = _switch(args.holder, target, guest, state)
        receipt["on"] = switched.on()
        receipt["verified_gate"] = _verified_reload_gate(
            target, state, original, receipt["on"])
        response = _switch(args.holder, target, guest, state).keys(["NP8"])
        _require(response.get("pressed") == ["NP8"] and "error" not in response
                 and "stopped" not in response, "reload NP8 did not land")
        receipt["step_command"] = response
        run.see("world", 60)
        after = _checkpoint(target, capture_dir, "post-step", receipt, run,
                            disk_sha256=disk_hash, loaded_slot_sha256=slot_hash)
        _require_world(after, reading["names"], area=AREA)
        _require((_value(after, 0x25), _value(after, 0x26)) != saved_cell,
                 "reload NP8 did not move the wilderness marker")
        receipt["stepped"] = after
        receipt["checks"]["step"] = True
        response = _switch(args.holder, target, guest, state).off()
        receipt["off"] = response
        _require("error" not in response and not state.load()["on"]
                 and not state.load()["rows"], "the ordinary RAM switch did not restore")
        receipt["gate"] = _original_live(target, original)
        receipt["checks"]["ram_restored"] = True
        receipt["screens"] = run.events
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if booted and target is not None:
            try:
                if state.load().get("on"):
                    reply = _switch(args.holder, target, guest, state).off()
                    if "error" in reply:
                        receipt["cleanup"].append(f"RAM restore: {reply}")
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append(f"RAM restore: {exc}")
        if booted:
            for name in snapshots:
                try:
                    guest.discard(name, args.holder)
                except Exception as exc:  # noqa: BLE001
                    receipt["cleanup"].append(f"discard {name}: {exc}")
            try:
                receipt["halt"] = acceptance.halt_lane(guest, args.holder,
                                                          manifest_path=manifest_path,
                                                          command=command)
                receipt["checks"]["halt"] = True
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append(f"halt: {exc}")
        try:
            _check_source()
            _restored_source(p2)
            receipt["checks"]["sources_unchanged"] = True
        except Exception as exc:  # noqa: BLE001
            receipt["cleanup"].append(f"source hash: {exc}")
        receipt["success"] = ("error" not in receipt and not receipt["cleanup"] and
                              all(receipt["checks"].get(key) is True for key in
                                  ("load", "step", "ram_restored", "halt",
                                   "sources_unchanged")))
        _write_json(out / "reload-receipt.json", receipt)
    if not receipt["success"]:
        raise RouteError(receipt.get("error") or "; ".join(receipt["cleanup"]))
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    phases = parser.add_subparsers(dest="phase", required=True)
    for name in ("p2", "reload"):
        phase = phases.add_parser(name)
        phase.add_argument("--run-id", required=True)
        phase.add_argument("--holder", required=True)
        phase.add_argument("--audio-proof", type=pathlib.Path, required=True)
        phase.add_argument("--out", type=pathlib.Path, required=True)
        phase.add_argument("--budget", type=float, required=True)
        if name == "p2":
            phase.add_argument("--previous-return-attempts", type=int, required=True)
        else:
            phase.add_argument("--receipt", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    try:
        with terminating():
            result = run_p2(args) if args.phase == "p2" else run_reload(args)
    except (RouteError, OSError, ValueError, KeyError) as exc:
        print(f"darknessreturn: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"success": True, "receipt": str(args.out / f"{args.phase}-receipt.json"),
                      "checks": result["checks"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
