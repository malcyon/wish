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

from automap import (  # noqa: E402
    amiga,
    amigafasttravel,
    amigaparty,
    amigatrip,
    amigavars,
)
from goldbox import amiga_adf, amiga_pod, amiga_savegame, areas  # noqa: E402
from tools.amiga import (  # noqa: E402
    acceptance,
    fasttravelrun,
    guardmaps,
    noencounters,
    route_camp,
    route_darkness,
    screens,
)
from tools.amiga.screens import PixelGuards, rules_of  # noqa: E402
from tools.amiga.staging import sha256  # noqa: E402
from tools.amiga.winuaesession import RouteError, WinGuest, terminating  # noqa: E402
from tools.registry import specimens  # noqa: E402

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

# This contract applies to one registered source, never to P2's TURBO K party.
BUNDLE_SPECIMEN = "wish2-w4d-case-used-disk3"
BUNDLE_IMAGE_SHA256 = "bf0dba2bb2f66981c6ae80e6aaf7c7dbb358fc0cbaaec0db61cc69a0910fcb1c"
BUNDLE_SOURCE_F_SHA256 = "4f95c1e81158fcceed47f7497e8301dae8f98327bfa082808b9031960a5b48cd"
BUNDLE_NAMES = ("TROND AAGE L", "YVONNE", "MARIT", "INA", "HILDE", "RENATE", "STORM")
BUNDLE_HEADS = (16, 12, 6, 8, 10, 6, 6)
BUNDLE_PLACE = {"area": 5, "x": 3, "y": 10, "facing": 3}
BUNDLE_EXEC_SHA256 = "6f8fee2dd8ea035b156cb0eb1c1d16e9172aa450a4f2b9e54e6d0018cf65c4d4"
BUNDLE_CONFIG_SHA256 = "f8c66a210efc8fbcec4eaa0cac50f6354964a6d7818418b0e8113a7010605ca2"
BUNDLE_PREPARED_SHA256 = "55d4a3fa960ec96884b5e9f9e9265124dee480d2015ccc84dcdf461eebe076de"
BUNDLE_MANIFEST_SHA256 = "5b28297f1432ebced6812be75f516ade3a9f221f36a8bdee46a79e2ccf4e77fe"
BUNDLE_CURRENT_RULES_SHA256 = "f5350cad62ff1971575e64ddfa37e02bb27ef3dbbaf9c2fc0713556c3babab5a"
# Exact source-specific selectors established on retained W4D frames, not generic alternatives.
BUNDLE_GUARD_VARIANTS = {"title": 0, "party_menu": 0, "load_from": 0,
                         "load_picker": 0, "disk2_prompt": 0, "loaded_menu": 1,
                         "sheet": 2, "save_picker": 1, "journal": 1,
                         "journal_answer": 0, "world": 2, "camp": 2,
                         "camp_sheet_items_5": 1, "camp_items_5": 0,
                         "camp_items_5_row3": 0, "camp_save_picker": 2,
                         "exit_game": 2}
BUNDLE_IDENTITY_VARIANTS = {"loaded_menu": 6, "sheet": 6,
                            "camp_sheet_items_5": 1, "camp_items_5": 1}
BUNDLE_IDENTITY_STATES = tuple(BUNDLE_IDENTITY_VARIANTS)

ORIGIN_SPECIMEN = "wish360-w4d-source01-fg-disk3"
ORIGIN_IMAGE_SHA256 = "903b7a7cc4dbe4172733ce98187c38fcb3f3878f7acbd2b390e970d36e28b9be"
ORIGIN_G_SHA256 = "fd6b8f00f6f342316ace7d33b34e96c09a820a7017aff379ff352c2da712f328"
ORIGIN_PREPARED_SHA256 = "de70cca6e178026d60f406c9e64bee3cd87a1da5d8bd2da2e067451919da127f"
# The live area byte a load of source-01 G reads (Kalistes' Parlor); the save's place reads 5.
ORIGIN_LIVE_AREA = 82
ORIGIN_TARGET_AREA = 22
# Where the game itself puts this origin's party on a Return into Kalistes' Parlor:
# area 82's init entry ($8014) stores SAVE 7, 15, 0 into $34/$35/$11 at $8055-$80CD
# for this party's state ($1F7=1, $219=2, came-from $16=22), over the square Return wrote.
ORIGIN_RETURN_SQUARE = (7, 15, 0)
# Comparison labels: each binds one save letter, so a source G, the Return run's
# game-written F and the reload's reference cannot stand in for one another.
SOURCE_ROLES = ("selected-source", "same-run-F", "same-run-G",
                "origin-source-G", "return-new-F", "reload-F")


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


def _measured_regions(target: amiga.AmigaTarget, *, check_target: bool = True
                      ) -> tuple[tuple[int, int], ...]:
    """Validate Exec's actual MemHeader list; configured MEMORY is not a measurement."""
    def exact(address: int, size: int) -> bytes:
        data = target.read(address, size)
        _require(len(data) == size, "bundle_range_unsupported: short memory-region read")
        return data

    page = exact(0, amiga.EXEC_PAGE)
    base = int.from_bytes(page[amiga.EXEC_BASE_AT:amiga.EXEC_BASE_AT + 4], "big")
    _require(amiga._pointer(base), "bundle_range_unsupported: no valid ExecBase")
    complement = int.from_bytes(exact(base + amiga.EXEC_CHK_BASE, 4), "big")
    _require(complement == (~base & 0xffffffff),
             "bundle_range_unsupported: ExecBase complement differs")
    sentinel = base + amiga.EXEC_MEM_LIST + 4
    node = int.from_bytes(exact(base + amiga.EXEC_MEM_LIST, 4), "big")
    regions = []
    seen = set()
    for _ in range(amiga.MEM_NODES):
        if node == sentinel:
            break
        _require(amiga._pointer(node) and node not in seen,
                 "bundle_range_unsupported: invalid MemHeader link")
        seen.add(node)
        head = exact(node, amiga.MEM_UPPER + 4)
        lower = int.from_bytes(head[amiga.MEM_LOWER:amiga.MEM_LOWER + 4], "big")
        upper = int.from_bytes(head[amiga.MEM_UPPER:amiga.MEM_UPPER + 4], "big")
        _require(lower < upper <= 0x1000000,
                 "bundle_range_unsupported: invalid MemHeader bounds")
        regions.append((lower, upper - lower))
        node = int.from_bytes(head[:4], "big")
    else:
        raise RouteError("bundle_range_unsupported: MemHeader list exceeds bound")
    _require(regions and sum(size for _, size in regions) <= 0x1000000,
             "bundle_range_unsupported: empty or oversized memory regions")
    ordered = sorted(set(regions), reverse=True)
    _require(len(ordered) == len(regions) and
             all(a + size <= b or b + length <= a
                 for i, (a, size) in enumerate(ordered)
                 for b, length in ordered[i + 1:]),
             "bundle_range_unsupported: overlapping memory regions")
    if check_target:
        _require(tuple(ordered) == tuple(target.memory),
                 "bundle_range_unsupported: target ranges differ from measured regions")
    return tuple(ordered)


def _bundle_nodes(target: amiga.AmigaTarget, members: tuple) -> dict:
    """Read only checked 70-byte allocations and retain exact ordered child payloads."""
    _require(len(members) <= 8 and all(len(m.item_nodes) <= 64 for m in members),
             "bundle_bounds: party members or head count exceeds limit")
    heads = [(m.slot, index, node) for m in members
             for index, node in enumerate(m.item_nodes)]
    _require(len(heads) <= 448, "bundle_bounds: pool head count exceeds limit")
    bundles = [(slot, index, node) for slot, index, node in heads
               if len(node.raw) == 0x42 and node.raw[0x2e] == 0x49]
    if not bundles:
        return {"coverage": "not_exercised", "nodes": []}
    regions = _measured_regions(target)
    allocations: list[tuple[int, int]] = []

    def checked(address: int) -> bytes:
        _require(isinstance(address, int) and address >= 0x100 and not address & 1,
                 "bundle_pointer: odd or invalid node address")
        end = address + 0x46
        _require(any(base <= address and end <= base + size for base, size in regions),
                 "bundle_range_unsupported: node outside measured memory")
        _require(all(end <= start or address >= stop for start, stop in allocations),
                 "bundle_overlap: repeated or overlapping allocation")
        allocations.append((address, end))
        data = target.read(address, 0x46)
        _require(len(data) == 0x46, "bundle_short_read: node is not 70 bytes")
        return data

    # Reserve every main head's allocation before traversing any child.
    for _, _, node in heads:
        _require(isinstance(node.address, int) and node.address >= 0x100
                 and not node.address & 1, "bundle_pointer: invalid main head address")
        end = node.address + 0x46
        _require(any(base <= node.address and end <= base + size for base, size in regions),
                 "bundle_range_unsupported: main head outside measured memory")
        _require(all(end <= start or node.address >= stop for start, stop in allocations),
                 "bundle_overlap: overlapping main heads")
        allocations.append((node.address, end))
    result = []
    children_total = 0
    for slot, index, node in bundles:
        full = target.read(node.address, 0x46)
        _require(len(full) == 0x46, "bundle_short_read: head is not 70 bytes")
        _require(full[:0x42] == node.raw, "bundle_stale: head changed since party read")
        quantity = full[0x3a]
        children_total += quantity
        _require(children_total <= 120 and len(heads) + children_total <= 448,
                 "bundle_bounds: child quantity or pool exceeds limit")
        pointer = int.from_bytes(full[0x42:0x46], "big")
        children = []
        for ordinal in range(quantity):
            _require(pointer != 0, "bundle_null: missing required child")
            child = checked(pointer)
            children.append({"ordinal": ordinal, "address": pointer,
                             "raw_hex": child.hex(),
                             "sha256": hashlib.sha256(child).hexdigest()})
            pointer = int.from_bytes(child[0x42:0x46], "big")
        _require(pointer == 0, "bundle_quantity: non-NULL final child link")
        result.append({"slot": slot, "chain_index": index, "address": node.address,
                       "raw_hex": full.hex(), "sha256": hashlib.sha256(full).hexdigest(),
                       "children": children})
    for record in result:
        for node in (record, *record["children"]):
            raw = bytes.fromhex(node["raw_hex"])
            _require(target.read(node["address"], 0x46) == raw,
                     "bundle_stale: node changed before checkpoint ended")
    for _, _, node in heads:
        _require(target.read(node.address, 0x42) == node.raw,
                 "bundle_stale: main head changed before checkpoint ended")
    return {"coverage": "complete", "nodes": result}


def _source_members(members: tuple) -> None:
    _require(members is not None and len(members) == 7 and
             tuple((m.slot, m.name, len(m.item_nodes)) for m in members) ==
             tuple((i, name, count) for i, (name, count) in enumerate(zip(
                 BUNDLE_NAMES, BUNDLE_HEADS, strict=True))),
             "bundle_source_identity: seven ordered members or 64 head counts differ")
    cases = [(m.slot, i, node) for m in members for i, node in enumerate(m.item_nodes)
             if len(node.raw) == 0x42 and node.raw[0x2e] == 0x49]
    _require(len(cases) == 1 and cases[0][:2] == (4, 2) and cases[0][2].raw[0x3a] == 4,
             "bundle_source_identity: HILDE's third head is not the sole four-child case")


def _source_recheck(target: amiga.AmigaTarget, members: tuple,
                    regions: tuple[tuple[int, int], ...], located: tuple,
                    reading: dict) -> None:
    _require(_measured_regions(target) == regions,
             "bundle_source_stale: measured regions changed")
    _require(callable(getattr(target, "locate", None)),
             "bundle_source_stale: machine cannot be located again")
    target.locate(memory=regions)
    _require((target.anchor_base, target.data_base, tuple(target.memory)) == located,
             "bundle_source_stale: located build or memory ranges changed")
    fresh = amigaparty.read_party(target)
    _source_members(fresh)
    _require(tuple((m.slot, m.name, m.hp, m.hp_max, m.address,
                    hashlib.sha256(m.raw).hexdigest(),
                    [hashlib.sha256(raw).hexdigest() for _, raw in m.items()],
                    [hashlib.sha256(raw).hexdigest() for _, raw in m.effects()])
                   for m in fresh) ==
             tuple((m["slot"], m["name"], m["hp"], m["hp_max"],
                    m["record_address"], m["record_sha256"], m["items"], m["effects"])
                   for m in reading["party"]),
             "bundle_source_stale: member record, chain or effects changed")
    _require(tuple((m.slot, m.name, m.hp, m.hp_max,
                    tuple((n.address, n.raw) for n in m.item_nodes),
                    tuple(m.effects())) for m in fresh) ==
             tuple((m.slot, m.name, m.hp, m.hp_max,
                    tuple((n.address, n.raw) for n in m.item_nodes),
                    tuple(m.effects())) for m in members),
             "bundle_source_stale: member list, head or effects changed")


def _capture_nodes(path: pathlib.Path, members: tuple, reading: dict,
                    target: amiga.AmigaTarget | None = None, *, source: bool = False) -> dict:
    """Keep exact live nodes private and verify them against this read's hashes."""
    if source:
        _source_members(members)
        _require(target is not None, "bundle_source_identity: measured memory target is missing")
        regions = _measured_regions(target)
        located = (target.anchor_base, target.data_base, tuple(target.memory))
        for member, summary in zip(members, reading["party"], strict=True):
            _require(len(member.raw) == amiga_savegame.POD_RECORD_BYTES
                     and any(base <= member.address
                             and member.address + len(member.raw) <= base + size
                             for base, size in regions),
                     "bundle_source_range: member record is outside measured memory")
            summary["record_address"] = member.address
            summary["record_sha256"] = hashlib.sha256(member.raw).hexdigest()
    else:
        _require(bool(members) and members[0].name == "TURBO K" and members[0].slot == 0,
                 "the capture's first member is not TURBO K in slot 0")
        nodes = members[0].item_nodes
        _require(len(nodes) > 4, "the capture is missing first-member items 3 or 4")
    saved = []
    _require(len(members) == len(reading["party"]), "the live member count changed during capture")
    for member, summary in zip(members, reading["party"]):
        _require((member.slot, member.name) == (summary["slot"], summary["name"])
                 and len(member.item_nodes) == len(summary["items"]),
                 "the live member identity or item count changed during capture")
        for index, node in enumerate(member.item_nodes):
            _require(len(node.raw) == 0x42, "the capture item node is not 66 bytes")
            digest = hashlib.sha256(node.raw).hexdigest()
            _require(digest == summary["items"][index],
                     "the captured node differs from the ordinary live receipt")
            saved.append({"slot": member.slot, "name": member.name,
                          "chain_index": index, "address": node.address,
                          "length": len(node.raw), "raw_hex": node.raw.hex(),
                          "sha256": digest,
                          "tail20_sha256": hashlib.sha256(node.raw[0x2e:0x42]).hexdigest()})
    bundle = (_bundle_nodes(target, members) if target is not None else
               {"coverage": "legacy", "nodes": []})
    if source:
        _require(bundle["coverage"] == "complete" and len(bundle["nodes"]) == 1
                 and (bundle["nodes"][0]["slot"], bundle["nodes"][0]["chain_index"]) == (4, 2)
                 and len(bundle["nodes"][0]["children"]) == 4,
                 "bundle_source_capture: 64 heads and four children are required")
        _source_recheck(target, members, regions, located, reading)
    payload = (json.dumps({"items": saved, "bundle": bundle}, indent=2, sort_keys=True) + "\n").encode()
    temp = path.with_name(path.name + ".tmp")
    try:
        with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
            file.write(payload)
        if source:
            _require(os.name == "posix" and temp.stat().st_uid == os.getuid()
                     and stat.S_IMODE(temp.stat().st_mode) == 0o600,
                     "bundle_source_privacy: private node file has wrong owner or mode")
        temp.replace(path)
        _require(hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(payload).hexdigest(),
                 "the private node file did not read back")
        if source:
            _require(path.stat().st_uid == os.getuid()
                     and stat.S_IMODE(path.stat().st_mode) == 0o600,
                     "bundle_source_privacy: published node file has wrong owner or mode")
    finally:
        temp.unlink(missing_ok=True)
    return {"file_sha256": hashlib.sha256(payload).hexdigest(),
            "bundle_coverage": bundle["coverage"],
            "bundle_heads": len(bundle["nodes"]),
            "bundle_children": sum(len(node["children"]) for node in bundle["nodes"])}


def _compare_nodes(before_entry: dict, before_reading: dict, after_entry: dict,
                    after_reading: dict, disk: amiga_adf.AmigaDisk,
                    root: pathlib.Path, expected_f_sha256: str | None = None) -> dict:
    """Classify two private same-read captures against a game-written F."""
    slot_bytes = amiga_savegame.pod_read_slot(disk, SAVE_LETTER)
    saved = amiga_savegame.pod_parse(slot_bytes)
    f_digest = hashlib.sha256(slot_bytes).hexdigest()
    _require(expected_f_sha256 is None or expected_f_sha256 == f_digest,
             "bundle_f_alignment: game-written F digest differs")

    def load(entry: dict, reading: dict) -> dict:
        relative = pathlib.PurePosixPath(entry["path"])
        _require(not relative.is_absolute() and ".." not in relative.parts,
                 "the private node reference leaves its capture root")
        path = root.joinpath(*relative.parts)
        _require(path.is_file(), "a private node capture is missing")
        data = path.read_bytes()
        _require(hashlib.sha256(data).hexdigest() == entry["file_sha256"],
                 "the private node capture hash differs")
        artifact = json.loads(data)
        records = artifact["items"]
        _require(len(reading["party"]) == saved.count,
                 "the captured party count differs from game-written F")
        expected = [(member["slot"], member["name"], index, digest)
                    for member in reading["party"]
                    for index, digest in enumerate(member["items"])]
        _require(len(records) == len(expected), "a captured item is missing")
        groups = {member["slot"]: [] for member in reading["party"]}
        _require(len(groups) == len(reading["party"]), "a captured member slot repeats")
        for record, (slot, name, index, digest) in zip(records, expected):
            identity = (slot, name, index)
            _require((record["slot"], record["name"], record["chain_index"],
                      record["sha256"]) == (*identity, digest),
                     "a captured item identity or receipt hash differs")
            raw = bytes.fromhex(record["raw_hex"])
            _require(record["length"] == len(raw) == 0x42
                     and hashlib.sha256(raw).hexdigest() == digest
                     and hashlib.sha256(raw[0x2e:0x42]).hexdigest() == record["tail20_sha256"],
                     "a captured item is short or its hash differs")
            _require(isinstance(record["address"], int) and record["address"] > 0,
                     "a captured item address is invalid")
            groups[slot].append((identity, record["address"], raw))
        _require(len(groups) == len(reading["party"]), "a captured member is missing")
        result = {}
        addresses = set()
        for nodes in groups.values():
            for position, (identity, address, raw) in enumerate(nodes):
                _require(address not in addresses, "a captured item address repeats")
                addresses.add(address)
                next_address = nodes[position + 1][1] if position + 1 < len(nodes) else 0
                _require(int.from_bytes(raw[0x2a:0x2e], "big") == next_address,
                         "a captured item chain has a malformed link")
                _require(identity not in result, "a captured item identity repeats")
                result[identity] = raw
        return result, artifact.get("bundle", {"coverage": "legacy", "nodes": []})

    earlier, earlier_bundle = load(before_entry, before_reading)
    later, later_bundle = load(after_entry, after_reading)
    _require(earlier.keys() == later.keys(), "the captured item identities changed")
    differences = []
    all_payloads_match = True
    bundle = False
    bundle_head_differences = []
    bundle_differences = []
    bundle_complete = (earlier_bundle.get("coverage") == "complete"
                       and later_bundle.get("coverage") == "complete")
    bundle_seen = 0
    expected_bundles = {}
    for phase_bundle, phase_heads in ((earlier_bundle, earlier), (later_bundle, later)):
        if phase_bundle.get("coverage") == "complete":
            _require(phase_bundle.get("f_sha256") in (None, f_digest),
                     "bundle_f_alignment: saved F digest differs")
            _require(isinstance(phase_bundle.get("nodes"), list),
                     "bundle_capture: missing ordered bundle nodes")
            found = {}
            for node in phase_bundle["nodes"]:
                names = [m["name"] for m in before_reading["party"]
                         if m["slot"] == node["slot"]]
                _require(len(names) == 1, "bundle_capture: unmatched slot")
                identity = (node["slot"], names[0], node["chain_index"])
                _require(identity in phase_heads and identity not in found,
                         "bundle_capture: unexpected or repeated bundle identity")
                head = bytes.fromhex(node["raw_hex"])
                _require(len(head) == 0x46 and node["address"] > 0
                         and hashlib.sha256(head).hexdigest() == node["sha256"]
                         and head[:0x42] == phase_heads[identity]
                         and head[0x2e] == 0x49,
                         "bundle_capture: head bytes or hash differ")
                pointer = int.from_bytes(head[0x42:0x46], "big")
                _require(len(node["children"]) == head[0x3a],
                         "bundle_quantity: captured child count differs")
                for ordinal, child in enumerate(node["children"]):
                    raw = bytes.fromhex(child["raw_hex"])
                    _require(len(raw) == 0x46 and child["ordinal"] == ordinal
                             and child["address"] == pointer and pointer != 0
                             and hashlib.sha256(raw).hexdigest() == child["sha256"],
                             "bundle_capture: child link, bytes or hash differ")
                    pointer = int.from_bytes(raw[0x42:0x46], "big")
                _require(pointer == 0, "bundle_quantity: child chain did not end at NULL")
                found[identity] = node
            expected_bundles[id(phase_bundle)] = found
    for member_index, block in enumerate(saved.characters):
        member = before_reading["party"][member_index]
        _require(member["name"] == block.name and
                 after_reading["party"][member_index]["name"] == block.name and
                 len(member["items"]) == block.items and
                 len(after_reading["party"][member_index]["items"]) == block.items,
                 "the game-written F item count or member identity differs")
        at = block.at + amiga_savegame.POD_RECORD_BYTES
        for index in range(block.items):
            identity = (member["slot"], member["name"], index)
            _require(identity in earlier and identity in later,
                     "the captured item identity is missing")
            first, second = earlier[identity], later[identity]
            saved_tail = saved.data[at:at + amiga_savegame.POD_ITEM_BYTES]
            _require(len(saved_tail) == 20, "a game-written F item is short")
            at += 20
            if saved_tail[0] == amiga_savegame.POD_BUNDLE_ID:
                quantity = saved_tail[amiga_savegame.POD_BUNDLE_COUNT]
                if bundle_complete:
                    for capture in (earlier_bundle, later_bundle):
                        captured = expected_bundles[id(capture)].get(identity)
                        _require(captured is not None and
                                 len(captured["children"]) == quantity,
                                 "bundle_quantity: saved and captured quantities differ")
                child_tails = [saved.data[at + 20 * n:at + 20 * (n + 1)]
                               for n in range(quantity)]
                _require(all(len(tail) == 20 for tail in child_tails),
                         "bundle_f_alignment: saved child is short")
                at += 20 * quantity
                bundle_seen += 1
                if bundle_complete:
                    first_bundle = expected_bundles[id(earlier_bundle)].get(identity)
                    second_bundle = expected_bundles[id(later_bundle)].get(identity)
                    _require(first_bundle is not None and second_bundle is not None,
                             "bundle_capture: saved bundle lacks live head")
                    first_full = bytes.fromhex(first_bundle["raw_hex"])
                    second_full = bytes.fromhex(second_bundle["raw_hex"])
                    bundle_head_differences.append({
                        "slot": identity[0], "name": identity[1], "chain_index": index,
                        "differing_offsets": [i for i in range(0x46)
                                              if first_full[i] != second_full[i]],
                        "bundle_link_offsets": [i for i in range(0x42, 0x46)
                                                if first_full[i] != second_full[i]]})
                    for ordinal, saved_child in enumerate(child_tails):
                        first_child = bytes.fromhex(first_bundle["children"][ordinal]["raw_hex"])
                        second_child = bytes.fromhex(second_bundle["children"][ordinal]["raw_hex"])
                        offsets = [i for i in range(0x46)
                                   if first_child[i] != second_child[i]]
                        match = (first_child[0x2e:0x42] == saved_child
                                 == second_child[0x2e:0x42])
                        all_payloads_match &= match
                        bundle_differences.append({"slot": identity[0], "name": identity[1],
                                                   "chain_index": index, "child_index": ordinal,
                                                   "differing_offsets": offsets,
                                                   "payload_matches_f": match,
                                                   "differing_unnamed_saved_offsets": [i for i in
                                                       (0x2f, 0x3b, 0x3e) if
                                                       len({first_child[i], second_child[i],
                                                            saved_child[i - 0x2e]}) > 1]})
            decoded = [amiga_pod.PodItem.from_bytes(tail) for tail in
                       (first[0x2e:0x42], second[0x2e:0x42], saved_tail)]
            changed_fields = [field for field in amiga_pod.ITEM_FIELDS
                              if len({item.get(field) for item in decoded}) > 1]
            offsets = [offset for offset in range(0x42) if first[offset] != second[offset]]
            payload_match = first[0x2e:0x42] == second[0x2e:0x42] == saved_tail
            all_payloads_match &= payload_match
            bundle |= 0x49 in (first[0x2e], second[0x2e], saved_tail[0])
            differences.append({"slot": identity[0], "name": identity[1],
                                "chain_index": index, "differing_offsets": offsets,
                                "display_offsets": [i for i in offsets if i < 0x2a],
                                "link_offsets": [i for i in offsets if 0x2a <= i < 0x2e],
                                "payload_offsets": [i for i in offsets if i >= 0x2e],
                                "payload_matches_f": payload_match,
                                "differing_named_fields": changed_fields,
                                "differing_unnamed_saved_offsets": [i for i in
                                    (0x2f, 0x3b, 0x3e) if
                                    len({first[i], second[i], saved_tail[i - 0x2e]}) > 1]})
    if bundle_complete:
        _require(len(expected_bundles[id(earlier_bundle)]) == bundle_seen
                 and len(expected_bundles[id(later_bundle)]) == bundle_seen,
                 "bundle_f_alignment: bundle head count differs from F")
    bundle_incomplete = bundle and not bundle_complete
    if not all_payloads_match:
        status = "payload_mismatch"
    elif bundle_incomplete:
        status = "bundle_inventory_incomplete"
    elif any(row["differing_offsets"] for row in
             differences + bundle_head_differences + bundle_differences):
        status = "captured_metadata_differs"
    else:
        status = "captured_heads_equal"
    return {"items": differences, "bundle_heads": bundle_head_differences,
              "bundle_children": bundle_differences,
              "bundle_coverage": ("complete" if bundle and bundle_complete else
                                  "incomplete" if bundle else "not_exercised"),
              "saved_f_sha256": f_digest,
              "all_payloads_match_f": all_payloads_match,
              "bundle_inventory_incomplete": bundle_incomplete,
              "full_match": all_payloads_match and not bundle_incomplete
              and all(not row["differing_offsets"] for row in
                      differences + bundle_head_differences + bundle_differences),
             "evidence_status": status,
             "provenance": "receipt_artifact_consistency_only",
             "independently_authenticated": False,
             "preservation_established": False}


def _live_read(target: amiga.AmigaTarget, *, capture: pathlib.Path | None = None,
               source: bool = False) -> dict:
    row = None if source else amigatrip.row_for(TITLE)
    members = amigaparty.read_party(target)
    reading = {"party": None if members is None else [
                {"name": m.name, "slot": m.slot, "hp": m.hp, "hp_max": m.hp_max,
                  "items": [hashlib.sha256(node).hexdigest() for _, node in m.items()],
                  "effects": [hashlib.sha256(node).hexdigest() for _, node in m.effects()]}
                  for m in members]}
    if not source:
        reading = {"trip": fasttravelrun._reading(target, row),
                   "variables": [v.as_log() for v in amigavars.read_variables(
                       target, TITLE, (0x25, 0x26, 0x34, 0x35, 0x129, 0xC1, 0xBF))],
                   **reading}
    if capture is not None:
        reading["capture"] = _capture_nodes(capture, members, reading, target, source=True) if source else (
            _capture_nodes(capture, members, reading, target))
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
        "bundle_coverage": proof["bundle_coverage"],
        "bundle_heads": proof["bundle_heads"],
        "bundle_children": proof["bundle_children"],
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


def _source_slot(disk: amiga_adf.AmigaDisk, letter: str, expected: str) -> tuple[bytes, Any]:
    try:
        data = amiga_savegame.pod_read_slot(disk, letter)
        parsed = amiga_savegame.pod_parse(data)
    except (amiga_savegame.AmigaSaveError, amiga_savegame.PodSaveError) as exc:
        raise RouteError(f"bundle_source_{letter.lower()}: saved slot does not decode: {exc}") from exc
    _require(hashlib.sha256(data).hexdigest() == expected,
             f"bundle_source_{letter.lower()}: slot digest differs")
    _require(tuple(c.name.strip() for c in parsed.characters) == BUNDLE_NAMES
             and tuple(c.items for c in parsed.characters) == BUNDLE_HEADS
             and tuple(c.bundled for c in parsed.characters) == (0, 0, 0, 0, 4, 0, 0),
             f"bundle_source_{letter.lower()}: party or inventory count differs")
    cases = []
    for member, block in enumerate(parsed.characters):
        at = block.at + amiga_savegame.POD_RECORD_BYTES
        end = block.at + block.size - block.effects * amiga_savegame.POD_EFFECT_BYTES
        for index in range(block.items):
            head = data[at:at + 20]
            _require(len(head) == 20 and at + 20 <= end,
                     "bundle_source_saved: short head or item/effect boundary")
            at += 20
            if head[0] == 0x49:
                quantity = head[0x0c]
                children = tuple(data[at + 20 * n:at + 20 * (n + 1)]
                                 for n in range(quantity))
                _require(len(children) == quantity and all(len(child) == 20 for child in children)
                         and at + 20 * quantity <= end,
                         "bundle_source_saved: child crosses the effect boundary")
                cases.append((member, index, quantity, children))
                at += 20 * quantity
        _require(at == end, "bundle_source_saved: item cursor does not meet effect boundary")
    _require(len(cases) == 1 and cases[0][:3] == (4, 2, 4)
             and len(set(cases[0][3])) == 4
             and all(child[0] == 39 for child in cases[0][3]),
             "bundle_source_saved: HILDE's four distinct ordered children are missing")
    return data, parsed


def _source_contract(manifest_path: pathlib.Path, manifest: dict) -> tuple[pathlib.Path, str]:
    """Verify the registered F and the independently prepared, unoccupied working B."""
    entry = specimens._one_entry(BUNDLE_SPECIMEN, specimens.tree_root())
    source = pathlib.Path(entry["_provenance"]).parent / "fetched-disk3.adf"
    _require(entry["sha256"].get(source.name) == BUNDLE_IMAGE_SHA256
             and sha256(source) == BUNDLE_IMAGE_SHA256,
             "bundle_source_image: registered image digest differs")
    original = amiga_adf.AmigaDisk.open(source)
    _require(not original.verify(), "bundle_source_image: ADF verification failed")
    _source_slot(original, "F", BUNDLE_SOURCE_F_SHA256)
    _require(route_darkness.DARKNESS.read_slot(original, "F").get("place") == BUNDLE_PLACE,
             "bundle_source_image: selected F saved place differs")
    _require(manifest_path.is_file() and sha256(manifest_path) == BUNDLE_MANIFEST_SHA256
             and manifest.get("title") == "darkness"
             and manifest.get("loaded_letter") == "B"
             and manifest.get("names_a") == list(BUNDLE_NAMES)
             and manifest.get("state_a") == BUNDLE_PLACE
             and manifest.get("substitute") == {"path": str(source),
                                                "sha256": BUNDLE_IMAGE_SHA256, "letter": "F"},
             "bundle_source_manifest: prepared B is not the pinned seven-member F")
    for key, pin in (("disk1", route_darkness.DARKNESS_DISK1_SHA256),
                     ("disk2", route_darkness.DARKNESS_DISK2_SHA256)):
        row = manifest["disks"][key]
        _require(pathlib.Path(row["path"]).stat().st_uid == os.getuid()
                 and stat.S_IMODE(pathlib.Path(row["path"]).stat().st_mode) == 0o600,
                 f"bundle_source_privacy: {key} is not owner/0600")
        _require(row["sha256"] == pin and sha256(pathlib.Path(row["path"])) == pin,
                 f"bundle_source_manifest: {key} differs from its original pin")
    disk1 = amiga_adf.AmigaDisk.open(manifest["disks"]["disk1"]["path"])
    _require(hashlib.sha256(disk1.read_file("/Pools of Darkness")).hexdigest() ==
             BUNDLE_EXEC_SHA256, "bundle_source_manifest: executable differs")
    _require(sha256(pathlib.Path(__file__).with_name("goldbox-a500.uae")) ==
             BUNDLE_CONFIG_SHA256, "bundle_source_manifest: boot configuration differs")
    working = manifest["disks"]["disk3"]
    _require(pathlib.Path(working["path"]).stat().st_uid == os.getuid()
             and stat.S_IMODE(pathlib.Path(working["path"]).stat().st_mode) == 0o600,
             "bundle_source_privacy: working disk 3 is not owner/0600")
    disk_hash = sha256(pathlib.Path(working["path"]))
    _require(working["sha256"] == disk_hash == BUNDLE_PREPARED_SHA256,
             "bundle_source_manifest: prepared image digest differs or is original media")
    disk = amiga_adf.AmigaDisk.open(working["path"])
    _require(not disk.verify() and not ({"F", "G"} & set(route_darkness.DARKNESS.slot_letters(disk))),
             "bundle_source_manifest: prepared ADF is damaged or F/G is occupied")
    b, _ = _source_slot(disk, "B", BUNDLE_SOURCE_F_SHA256)
    _require(b == amiga_savegame.pod_read_slot(original, "F")
             and route_darkness.DARKNESS.read_slot(disk, "B").get("place") == BUNDLE_PLACE,
             "bundle_source_manifest: prepared B differs from selected F")
    return source, disk_hash


def _origin_source() -> pathlib.Path:
    entry = specimens._one_entry(ORIGIN_SPECIMEN, specimens.tree_root())
    source = pathlib.Path(entry["_provenance"]).parent / "fetched-disk3.adf"
    _require(entry["sha256"].get(source.name) == ORIGIN_IMAGE_SHA256
             and sha256(source) == ORIGIN_IMAGE_SHA256,
             "origin_source: preserved game-written image digest differs")
    original = amiga_adf.AmigaDisk.open(source)
    _require(not original.verify(), "origin_source: preserved ADF verification failed")
    try:
        _source_slot(original, "G", ORIGIN_G_SHA256)
    except RouteError as exc:
        raise RouteError(f"origin_source: saved G differs: {exc}") from exc
    _require(route_darkness.DARKNESS.read_slot(original, "G").get("place") == BUNDLE_PLACE,
             "origin_source: saved G place differs")
    _require(hashlib.sha256(original.read_file(LIBRARY)).hexdigest() == LIBRARY_HASH,
             "origin_source: ECL library digest differs")
    return source


def prepare_origin(run_id: str) -> pathlib.Path:
    """Stage a fresh, owner-only B copy of the separately pinned engine-written G."""
    _require(os.name == "posix", "origin_privacy: POSIX owner checks are required")
    source = _origin_source()
    old_umask = os.umask(0o077)
    try:
        manifest_path = acceptance.prepare(route_darkness.DARKNESS, run_id,
                                           substitute=source, substitute_letter="G", issue="360")
    finally:
        os.umask(old_umask)
    _require(_private_directory(manifest_path.parent.stat(), os.getuid()),
             "origin_privacy: fresh preparation is not owner/0700")
    _origin_contract(manifest_path, json.loads(manifest_path.read_text()))
    return manifest_path


def _private_media(manifest_path: pathlib.Path, manifest: dict, prefix: str) -> pathlib.Path:
    """Check the run's private registered disks 1-2, executable and configuration; return disk 3."""
    for key, pin in (("disk1", route_darkness.DARKNESS_DISK1_SHA256),
                     ("disk2", route_darkness.DARKNESS_DISK2_SHA256)):
        row = manifest["disks"][key]
        path = pathlib.Path(row["path"])
        _require(path.resolve().parent == manifest_path.parent.resolve()
                 and path.stat().st_uid == os.getuid()
                 and stat.S_IMODE(path.stat().st_mode) == 0o600
                 and row["sha256"] == sha256(path) == pin,
                 f"{prefix}_manifest: {key} is not a private registered copy")
    disk1 = amiga_adf.AmigaDisk.open(manifest["disks"]["disk1"]["path"])
    _require(hashlib.sha256(disk1.read_file("/Pools of Darkness")).hexdigest() ==
             BUNDLE_EXEC_SHA256, f"{prefix}_manifest: executable differs")
    _require(sha256(pathlib.Path(__file__).with_name("goldbox-a500.uae")) ==
             BUNDLE_CONFIG_SHA256, f"{prefix}_manifest: boot configuration differs")
    path = pathlib.Path(manifest["disks"]["disk3"]["path"])
    _require(path.resolve().parent == manifest_path.parent.resolve()
             and path.stat().st_uid == os.getuid()
             and stat.S_IMODE(path.stat().st_mode) == 0o600,
             f"{prefix}_privacy: prepared disk 3 is not owner/0600")
    return path


def _origin_contract(manifest_path: pathlib.Path, manifest: dict) -> tuple[pathlib.Path, str]:
    """Check the independently prepared B against source-01 G and registered media."""
    source = _origin_source()
    _require(manifest_path.is_file() and manifest_path.stat().st_uid == os.getuid()
             and stat.S_IMODE(manifest_path.stat().st_mode) == 0o600,
             "origin_privacy: prepared manifest is not owner/0600")
    _require(manifest.get("title") == "darkness" and manifest.get("loaded_letter") == "B"
             and manifest.get("names_a") == list(BUNDLE_NAMES)
             and manifest.get("state_a") == BUNDLE_PLACE
             and manifest.get("substitute") == {"path": str(source),
                                                "sha256": ORIGIN_IMAGE_SHA256, "letter": "G"},
             "origin_manifest: B was not made from pinned G")
    path = _private_media(manifest_path, manifest, "origin")
    prepared = manifest["disks"]["disk3"]
    digest = sha256(path)
    _require(prepared["sha256"] == digest == ORIGIN_PREPARED_SHA256
             and digest != ORIGIN_IMAGE_SHA256,
             "origin_manifest: independently prepared disk 3 digest differs")
    disk = amiga_adf.AmigaDisk.open(path)
    _require(not disk.verify() and not {"F", "G"} & set(route_darkness.DARKNESS.slot_letters(disk)),
             "origin_manifest: B disk is damaged or F/G is occupied")
    _require(hashlib.sha256(disk.read_file(LIBRARY)).hexdigest() == LIBRARY_HASH,
             "origin_manifest: prepared ECL library digest differs")
    try:
        prepared_b, _ = _source_slot(disk, "B", ORIGIN_G_SHA256)
    except RouteError as exc:
        raise RouteError(f"origin_manifest: saved B differs: {exc}") from exc
    original = amiga_adf.AmigaDisk.open(source)
    _require(prepared_b == amiga_savegame.pod_read_slot(original, "G")
             and route_darkness.DARKNESS.read_slot(disk, "B").get("place") == BUNDLE_PLACE,
             "origin_manifest: prepared B is not source G")
    return source, digest


def _origin_controls(path: pathlib.Path, source_manifest: pathlib.Path, disk_hash: str
                     ) -> tuple[PixelGuards, PixelGuards, dict]:
    """Use the source-01 selected rules without treating them as G-world measurements."""
    _require(disk_hash == ORIGIN_PREPARED_SHA256
             and source_manifest.is_file()
             and sha256(source_manifest) == BUNDLE_MANIFEST_SHA256,
             "origin_controls: source-01 controls or prepared disk differ")
    return _source_controls(path, source_manifest, BUNDLE_PREPARED_SHA256)


def _observe_origin(target: amiga.AmigaTarget, *, saved_area: int, disks: pathlib.Path
                    ) -> dict:
    """Read the loaded area and the one requested destination's ordinary eligibility."""
    row = amigatrip.row_for(TITLE)
    _require(row.area == 0x7A0A, "origin_reader: loaded area address differs")
    live = amigatrip.area_id(target, row)
    _require(live is not None, "origin_reader: live area is unreadable")
    gate = bool(amigatrip.gate(target, row))
    destination = areas.area_in(22, row.title)
    _require(destination is not None and destination.id == 22,
             "origin_reader: target 22 is missing")
    verdict = amigafasttravel.AmigaFastTravel(TITLE, disks=disks).legality(target, destination)
    after = amigatrip.area_id(target, row)
    _require(after == live,
             f"origin_reader: live area changed during target-22 legality ({live} to {after})")
    return {"saved_area": saved_area, "live_area": live, "gate": gate,
            "target_area": 22, "offered": bool(verdict), "reason": verdict.reason}


def _source_controls(path: pathlib.Path, manifest_path: pathlib.Path, disk_hash: str
                     ) -> tuple[PixelGuards, PixelGuards, dict]:
    """Require an offline preparer's explicitly selected current-reader screen rules."""
    validated = json.loads(path.read_text())
    _require(path.resolve().is_relative_to(manifest_path.parent.resolve())
             and path.stat().st_uid == os.getuid()
             and stat.S_IMODE(path.stat().st_mode) == 0o600,
             "bundle_source_privacy: source controls are not private to this run")
    _require(validated.get("source_image_sha256") == BUNDLE_IMAGE_SHA256
             and validated.get("source_f_sha256") == BUNDLE_SOURCE_F_SHA256
             and validated.get("prepared_disk3_sha256") == disk_hash == BUNDLE_PREPARED_SHA256
             and validated.get("manifest_sha256") == sha256(manifest_path) == BUNDLE_MANIFEST_SHA256
             and validated.get("current_rules_sha256") == BUNDLE_CURRENT_RULES_SHA256
             and validated.get("screen_reader_sha256") == sha256(pathlib.Path(screens.__file__))
             and validated.get("executable_sha256") == BUNDLE_EXEC_SHA256
             and validated.get("config_sha256") == BUNDLE_CONFIG_SHA256,
             "bundle_source_controls: offline preparation or current reader differs")
    current_path = pathlib.Path(guardmaps.__file__).with_name("guards_darkness.json")
    _require(sha256(current_path) == BUNDLE_CURRENT_RULES_SHA256,
             "bundle_source_controls: current rule map differs from offline reader")
    current = json.loads(current_path.read_text())
    controls = []
    for kind, needed in (("guards", BUNDLE_GUARD_VARIANTS),
                         ("identity", BUNDLE_IDENTITY_VARIANTS)):
        spec = validated[kind]
        file = pathlib.Path(spec["path"])
        _require(file.is_file() and file.resolve().is_relative_to(manifest_path.parent.resolve())
                 and file.stat().st_uid == os.getuid()
                 and stat.S_IMODE(file.stat().st_mode) == 0o600
                 and sha256(file) == spec["sha256"],
                 f"bundle_source_controls: {kind} file differs")
        choices = spec["variants"]
        _require(choices == needed,
                 f"bundle_source_controls: {kind} has missing or extra selected states")
        guard = PixelGuards(file)
        _require(set(guard.rules) == set(needed)
                 and all(len(rules_of(guard.rules[state])) == 1 for state in needed),
                 f"bundle_source_controls: {kind} is not a source-only subset")
        for state, index in needed.items():
            selected = rules_of(current[kind][state])[index]
            rule = rules_of(guard.rules[state])[0]
            _require(all(rule.get(field, ()) == selected.get(field, ())
                         for field in ("box", "sha256", "and")),
                     f"bundle_source_controls: {kind} {state} is not its selected rule")
        guard.rules = {state: rules_of(guard.rules[state])[0] for state in needed}
        controls.append(guard)
    return controls[0], controls[1], validated


def _source_checkpoint(target: amiga.AmigaTarget, directory: pathlib.Path, phase: str,
                       receipt: dict, run: SourceGuardedRun, disk_hash: str, *,
                       screens: tuple[str, ...] = ("save_picker", "camp_save_picker", "camp"),
                       reference: dict | None = None) -> dict:
    """Publish one complete capture only after the whole party and measured ranges recheck.

    `screens` are the guarded states the last matched frame may be; `reference`
    replaces the selected source F's image and slot digests in the entry.
    """
    _require(run.events and run.events[-1].get("screen") in screens,
             "bundle_source_capture: checkpoint screen has no matched guard")
    regions = _measured_regions(target)
    path = directory / f"{phase}.json"
    reading = _live_read(target, capture=path, source=True)
    proof = reading.pop("capture")
    _require(_measured_regions(target) == regions,
             "bundle_source_stale: checkpoint range identity changed")
    _require((proof["bundle_coverage"], proof["bundle_heads"], proof["bundle_children"]) ==
             ("complete", 1, 4) and len(path.read_bytes()) > 0,
             "bundle_source_capture: required 64+4 private file is missing")
    entry = {"checkpoint": phase, "path": path.relative_to(directory.parent).as_posix(),
             "file_sha256": proof["file_sha256"], "heads": sum(BUNDLE_HEADS),
             "bundle_heads": 1, "bundle_children": 4,
             "measured_regions": [list(r) for r in regions],
             "machine": {"anchor_base": target.anchor_base, "data_base": target.data_base},
             "order": len(receipt.get("item_nodes", [])),
             **(reference if reference is not None else
                {"source_disk_sha256": BUNDLE_IMAGE_SHA256,
                 "source_f_sha256": BUNDLE_SOURCE_F_SHA256}),
             "prepared_disk_sha256": disk_hash,
             "screen": {"shot": run.events[-1]["shot"], "time": run.events[-1]["time"],
                        "state": run.events[-1]["screen"]}}
    receipt.setdefault("item_nodes", []).append(entry)
    return reading


def _source_compare(entry: dict, reading: dict, disk: amiga_adf.AmigaDisk,
                    letter: str, digest: str, root: pathlib.Path,
                    *, role: str, previous: dict | None = None) -> dict:
    """Compare 64 ordered heads and four children with one specifically labelled slot."""
    _require(letter in ("F", "G") and role in SOURCE_ROLES,
             "bundle_source_reference: unsupported letter or role")
    _require((letter, digest, role) == ("F", BUNDLE_SOURCE_F_SHA256, "selected-source")
             or (letter, digest, role) == ("G", ORIGIN_G_SHA256, "origin-source-G")
             or (letter, role) in (("F", "same-run-F"), ("G", "same-run-G"),
                                   ("F", "return-new-F"), ("F", "reload-F")),
             "bundle_source_reference: source, F and G labels cannot be exchanged")
    data, parsed = _source_slot(disk, letter, digest)
    relative = pathlib.PurePosixPath(entry["path"])
    _require(not relative.is_absolute() and ".." not in relative.parts,
             "bundle_source_capture: private path escapes its run")
    artifact_path = root.joinpath(*relative.parts)
    payload = artifact_path.read_bytes()
    _require(hashlib.sha256(payload).hexdigest() == entry["file_sha256"],
             "bundle_source_capture: private artifact digest differs")
    artifact = json.loads(payload)
    records = artifact["items"]
    bundle = artifact["bundle"]
    _require(entry["heads"] == len(records) == 64 and bundle["coverage"] == "complete"
             and len(bundle["nodes"]) == entry["bundle_heads"] == 1
             and entry["bundle_children"] == 4
             and tuple((p["slot"], p["name"], len(p["items"]))
                       for p in reading["party"]) == tuple((i, name, count)
                       for i, (name, count) in enumerate(zip(BUNDLE_NAMES, BUNDLE_HEADS, strict=True))),
             "bundle_source_capture: seven members, 64 heads and one case required")
    region = entry["measured_regions"]
    _require(region and all(len(r) == 2 and r[1] > 0 for r in region),
             "bundle_source_capture: measured ranges are missing")
    spans: list[tuple[int, int]] = []

    def node(raw_hex: str, digest_hex: str, address: int, length: int) -> bytes:
        raw = bytes.fromhex(raw_hex)
        _require(len(raw) == length and hashlib.sha256(raw).hexdigest() == digest_hex
                 and type(address) is int and address >= 0x100 and not address & 1,
                 "bundle_source_capture: node bytes, pointer or digest differs")
        end = address + 70
        _require(any(base <= address and end <= base + size for base, size in region)
                 and all(end <= start or address >= stop for start, stop in spans),
                 "bundle_source_capture: overlapping or out-of-range allocation")
        spans.append((address, end))
        return raw

    heads: dict[tuple[int, int], tuple[int, bytes]] = {}
    n = 0
    for slot, count in enumerate(BUNDLE_HEADS):
        for index in range(count):
            record = records[n]
            n += 1
            _require((record["slot"], record["name"], record["chain_index"]) ==
                     (slot, BUNDLE_NAMES[slot], index),
                     "bundle_source_capture: head owner, name or order differs")
            raw = node(record["raw_hex"], record["sha256"], record["address"], 66)
            _require(record["length"] == 66
                     and record["sha256"] == reading["party"][slot]["items"][index]
                     and hashlib.sha256(raw[0x2e:0x42]).hexdigest() == record["tail20_sha256"],
                     "bundle_source_capture: ordinary same-read receipt differs")
            heads[slot, index] = (record["address"], raw)
    for slot, count in enumerate(BUNDLE_HEADS):
        for index in range(count):
            address, raw = heads[slot, index]
            next_address = heads[slot, index + 1][0] if index + 1 < count else 0
            _require(int.from_bytes(raw[0x2a:0x2e], "big") == next_address,
                     "bundle_source_capture: head-list topology differs")
    case = bundle["nodes"][0]
    _require((case["slot"], case["chain_index"]) == (4, 2)
             and len(case["children"]) == 4
             and case["address"] == heads[4, 2][0],
             "bundle_source_capture: HILDE case owner differs")
    # The full head uses an already reserved span. Replace its 66-byte reservation.
    spans.remove((case["address"], case["address"] + 70))
    full = node(case["raw_hex"], case["sha256"], case["address"], 70)
    _require(full[:66] == heads[4, 2][1] and full[0x2e] == 0x49 and full[0x3a] == 4,
             "bundle_source_capture: case head differs from same read")
    children = []
    pointer = int.from_bytes(full[0x42:0x46], "big")
    for ordinal, child in enumerate(case["children"]):
        _require((child["ordinal"], child["address"]) == (ordinal, pointer) and pointer != 0,
                 "bundle_source_capture: missing or reordered child")
        raw = node(child["raw_hex"], child["sha256"], pointer, 70)
        children.append(raw)
        pointer = int.from_bytes(raw[0x42:0x46], "big")
    _require(pointer == 0, "bundle_source_capture: terminal child link is not NULL")
    differences = []
    for slot, block in enumerate(parsed.characters):
        cursor = block.at + amiga_savegame.POD_RECORD_BYTES
        end = block.at + block.size - block.effects * amiga_savegame.POD_EFFECT_BYTES
        for index in range(block.items):
            saved = data[cursor:cursor + 20]
            cursor += 20
            raw = heads[slot, index][1]
            offsets = [i for i in range(20) if raw[0x2e + i] != saved[i]]
            if offsets:
                differences.append({"slot": slot, "head": index, "kind": "head",
                                    "payload_offsets": [i + 0x2e for i in offsets],
                                    "unnamed_saved_offsets": [i + 0x2e for i in offsets
                                                              if i in (1, 13, 16)]})
            if (slot, index) == (4, 2):
                _require(saved[0] == 0x49 and saved[0x0c] == 4,
                         "bundle_source_reference: saved case quantity differs")
                for ordinal, child in enumerate(children):
                    saved_child = data[cursor:cursor + 20]
                    cursor += 20
                    _require(len(saved_child) == 20 and saved_child[0] == 39,
                             "bundle_source_reference: saved child is missing")
                    offsets = [i for i in range(20) if child[0x2e + i] != saved_child[i]]
                    if offsets:
                        differences.append({"slot": 4, "head": 2, "kind": "child",
                                            "ordinal": ordinal,
                                            "payload_offsets": [i + 0x2e for i in offsets],
                                            "unnamed_saved_offsets": [i + 0x2e for i in offsets
                                                                      if i in (1, 13, 16)]})
        _require(cursor == end, "bundle_source_reference: item/effect boundary differs")
    _require(len(spans) == 68, "bundle_source_capture: allocation count differs")
    metadata = []
    if previous is not None:
        older = previous["items"]
        _require(len(older) == 64, "bundle_source_capture: earlier heads are missing")
        for first, second in zip(older, records, strict=True):
            a, b = bytes.fromhex(first["raw_hex"]), bytes.fromhex(second["raw_hex"])
            offsets = [i for i in range(66) if a[i] != b[i]]
            if offsets:
                metadata.append({"slot": second["slot"], "head": second["chain_index"],
                                 "display_offsets": [i for i in offsets if i < 0x2a],
                                 "link_offsets": [i for i in offsets if 0x2a <= i < 0x2e],
                                 "payload_offsets": [i for i in offsets if i >= 0x2e]})
        older_case = previous["bundle"]["nodes"][0]
        _require((older_case["slot"], older_case["chain_index"]) == (4, 2),
                 "bundle_source_capture: earlier case owner differs")
        older_full = bytes.fromhex(older_case["raw_hex"])
        _require(len(older_full) == 70, "bundle_source_capture: earlier case head is not 70 bytes")
        # The 66-byte head rows above stop before the case's first-child link.
        links = [i for i in range(0x42, 0x46) if older_full[i] != full[i]]
        if links:
            metadata.append({"slot": 4, "head": 2, "case_link_offsets": links})
        for ordinal, (a, b) in enumerate(zip(older_case["children"], case["children"], strict=True)):
            x, y = bytes.fromhex(a["raw_hex"]), bytes.fromhex(b["raw_hex"])
            offsets = [i for i in range(70) if x[i] != y[i]]
            if offsets:
                metadata.append({"slot": 4, "head": 2, "child": ordinal,
                                 "display_offsets": [i for i in offsets if i < 0x2a],
                                 "stale_link_offsets": [i for i in offsets if 0x2a <= i < 0x2e],
                                 "payload_offsets": [i for i in offsets if 0x2e <= i < 0x42],
                                 "child_link_offsets": [i for i in offsets if i >= 0x42]})
    return {"reference_letter": letter, "reference_role": role, "reference_sha256": digest,
            "heads": 64, "bundle_heads": 1, "bundle_children": 4,
            "payload_differences": differences, "metadata_differences": metadata,
            "all_payloads_match_reference": not differences,
            "evidence_status": "payload_mismatch" if differences else "capture_coverage_complete",
            "provenance": "receipt_artifact_consistency_only",
            "independently_authenticated": False, "preservation_established": False}


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
                # FS-UAE holds a key to an unrecognised screen until the title's emulator age.
                noted = getattr(self.guest, "note_recognised", None)
                if callable(noted):
                    noted()
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
        """Wait for the title for up to the title's limit, skipping a late intro if guarded.

        A guard set without an `intro` rule (the source-selected controls) keeps
        waiting, since the intro gives way to the title by itself.
        """
        beginning = time.monotonic()
        limit = route_darkness.DARKNESS.title_limit
        for attempt in range(4):
            remaining = limit - (time.monotonic() - beginning)
            _require(remaining > 0, f"the title did not match its guard within {limit:.0f}s")
            try:
                self.see("title", min(120, self.left(remaining)))
                return
            except RouteError as exc:
                if attempt == 3:
                    raise RouteError(f"the title did not match its guard within {limit:.0f}s"
                                     ) from exc
                if (time.monotonic() - beginning < route_darkness.DARKNESS.boot_span
                        or "intro" not in self.guards):
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


class SourceGuardedRun(GuardedRun):
    """Apply the preparer's party-specific identity variant on each matching frame."""

    def __init__(self, *args: Any, identity: PixelGuards):
        super().__init__(*args)
        self.identity = identity
        self.out.chmod(0o700)
        _require(_private_directory(self.out.stat(), os.getuid()),
                 "bundle_source_privacy: screenshot directory is not owner/0700")

    def see(self, state: str, limit: float | None = None) -> pathlib.Path:
        crop = super().see(state, limit)
        if state in BUNDLE_IDENTITY_STATES:
            _require(self.identity(state, crop),
                     f"bundle_source_identity: {state} shows another party")
        return crop


class SourcePrivateGuest:
    """Fetch only into exclusive, owner-readable files below this private run."""

    def __init__(self, guest: WinGuest, root: pathlib.Path):
        self.guest, self.root = guest, root

    def __getattr__(self, name: str) -> Any:
        return getattr(self.guest, name)

    def get(self, remote: str, local: pathlib.Path, timeout: float) -> Any:
        _require(local.resolve().is_relative_to(self.root.resolve()) and not local.exists(),
                 "bundle_source_privacy: fetch path is outside this fresh run")
        _require(_private_directory(self.root.stat(), os.getuid()),
                 "bundle_source_privacy: run directory lost owner-only access")
        local.parent.chmod(0o700)
        _require(_private_directory(local.parent.stat(), os.getuid()),
                 "bundle_source_privacy: fetched directory is not owner/0700")
        with os.fdopen(os.open(local, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"):
            pass
        live = getattr(self.guest, "get_live", None)
        emulator = getattr(self.guest, "emulator", None)
        if live is not None and emulator is not None and emulator.poll() is None:
            response = live(remote, local, timeout=timeout)
        else:
            response = self.guest.get(remote, local, timeout=timeout)
        _require(local.stat().st_uid == os.getuid()
                 and stat.S_IMODE(local.stat().st_mode) == 0o600,
                 "bundle_source_privacy: fetched media has wrong owner or mode")
        return response


class SourceBootGuest:
    """Bound source boot actions without limiting the lane's failure cleanup."""

    def __init__(self, guest: SourcePrivateGuest, action_end: float, deadline: float):
        self.guest, self.action_end, self.deadline = guest, action_end, deadline

    def __getattr__(self, name: str) -> Any:
        return getattr(self.guest, name)

    def _limited(self, timeout: float) -> float:
        left = self.action_end - time.monotonic()
        _require(left > 0, "bundle_source_deadline: boot action expired; cleanup reserved")
        return min(timeout, left)

    def _cleanup_limit(self, timeout: float) -> float:
        return min(timeout, max(1.0, self.deadline - time.monotonic()))

    def silence(self, proof: pathlib.Path | None) -> bool:
        self._limited(float("inf"))
        muted = self.guest.silence(proof)
        self._limited(float("inf"))
        return muted

    def _run(self, *args: str, timeout: float) -> str:
        output = self.guest._run(*args, timeout=self._limited(timeout))
        self._limited(float("inf"))
        return output

    def claim(self, holder: str, timeout: float, **options: Any) -> str:
        # Let boot_lane mark a successful claim before a later deadline check can fail.
        return self.guest.claim(holder, timeout=self._limited(timeout), **options)

    def put(self, local: pathlib.Path, remote: str, timeout: float) -> str:
        result = self.guest.put(local, remote, timeout=self._limited(timeout))
        self._limited(float("inf"))
        return result

    def start(self, holder: str, *drives: str | None, timeout: float,
              options: tuple[str, ...] = ()) -> str:
        result = self.guest.start(holder, *drives, timeout=self._limited(timeout),
                                  options=options)
        self._limited(float("inf"))
        return result

    def stop(self, holder: str, timeout: float) -> str:
        return self.guest.stop(holder, timeout=self._cleanup_limit(timeout))

    def release(self, holder: str, timeout: float) -> str:
        return self.guest.release(holder, timeout=self._cleanup_limit(timeout))


class OriginFetchGuest:
    """Fetch this boot's media after a successful stop and before lane release."""

    def __init__(self, guest: SourceBootGuest, root: pathlib.Path, remotes: dict,
                 folder: str = "origin-fetched"):
        self.guest, self.root, self.remotes, self.folder = guest, root, remotes, folder
        self.fetched: dict[str, dict[str, str]] = {}
        self.partial: dict[str, dict[str, str]] = {}
        self.errors: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.guest, name)

    def stop(self, holder: str, timeout: float) -> str:
        response = self.guest.stop(holder, timeout=timeout)
        folder = self.root / self.folder
        try:
            folder.mkdir(mode=0o700)
        except Exception as exc:  # noqa: BLE001 - release still needs to run
            self.errors.append(f"fetch folder: {exc}")
            return response
        for key in ("disk1", "disk2", "disk3"):
            local = folder / f"fetched-{key}.adf"
            try:
                self.guest.get(self.remotes[key], local,
                               timeout=self.guest._cleanup_limit(timeout))
                self.fetched[key] = {"path": str(local), "sha256": sha256(local)}
            except Exception as exc:  # noqa: BLE001 - remaining disks still need fetching
                self.errors.append(f"fetch {key}: {exc}")
                if local.exists():
                    try:
                        self.partial[key] = {"path": str(local), "sha256": sha256(local)}
                    except Exception as hash_exc:  # noqa: BLE001 - retain the fetch error
                        self.errors.append(f"partial {key} hash: {hash_exc}")
        return response


def _source_fetched(guest: SourcePrivateGuest, remote: str, out: pathlib.Path,
                    limit: float, *, place: dict | None = BUNDLE_PLACE
                    ) -> tuple[amiga_adf.AmigaDisk, str]:
    """Read the game-written F twice, before G, with independent identical ADF copies.

    `place`, when given, is the saved place F must hold; None leaves it to the caller.
    """
    _require(limit > 0, "bundle_source_deadline: no time remains for F readback")
    paths = (out / "f-readback-1.adf", out / "f-readback-2.adf")
    hashes = []
    for path in paths:
        guest.get(remote, path, timeout=min(30, limit))
        disk = amiga_adf.AmigaDisk.open(path)
        _require(not disk.verify(), "bundle_source_f: fetched ADF fails verification")
        raw = amiga_savegame.pod_read_slot(disk, "F")
        hashes.append(hashlib.sha256(raw).hexdigest())
    _require(hashes[0] == hashes[1] and sha256(paths[0]) == sha256(paths[1]),
             "bundle_source_f: two independent fetches differ")
    disk = amiga_adf.AmigaDisk.open(paths[1])
    _source_slot(disk, "F", hashes[1])
    _require(place is None or route_darkness.DARKNESS.read_slot(disk, "F").get("place") == place,
             "bundle_source_f: game-written save has another saved place")
    return disk, hashes[1]


def _source_saved_artifact(entry: dict, root: pathlib.Path) -> dict:
    relative = pathlib.PurePosixPath(entry["path"])
    _require(not relative.is_absolute() and ".." not in relative.parts,
             "bundle_source_capture: artifact path escapes its run")
    data = root.joinpath(*relative.parts).read_bytes()
    _require(hashlib.sha256(data).hexdigest() == entry["file_sha256"],
             "bundle_source_capture: earlier artifact changed")
    return json.loads(data)


def _source_world(run: SourceGuardedRun) -> None:
    run.press("loaded_menu", "B", "journal")
    run.press("journal", "X", "journal_answer")
    run.press("journal_answer", "RET")
    try:
        run.see("world", 60)
    except RouteError:
        for _ in range(3):
            run.press("continue", "RET")
            try:
                run.see("world", 60)
                return
            except RouteError:
                pass
        raise RouteError("bundle_source_world: no measured world followed the journal") from None


def run_bundle_source(args: argparse.Namespace, *, guest: WinGuest | None = None) -> dict:
    """Offline-built camp-only source capture; a separate runner must authorize execution."""
    _require(os.name == "posix", "bundle_source_privacy: POSIX owner checks are required")
    _require(0 < args.budget <= 1800 and args.budget > 600,
             "bundle_source_deadline: total budget must reserve 600 of at most 1800 seconds")
    _require(not args.out.exists(), "bundle_source_privacy: output must be fresh")
    root = pathlib.Path.home() / ".cache/wish/acceptance/WISH-360" / args.run_id
    _require(args.out.parent.resolve() == root.resolve() and args.manifest.parent.resolve() == root.resolve(),
             "bundle_source_privacy: output and prepared manifest must share this private run")
    _require(_private_directory(root.stat(), os.getuid()),
             "bundle_source_privacy: prepared run must have POSIX owner/0700")
    args.out.mkdir(mode=0o700)
    _require(_private_directory(args.out.stat(), os.getuid()),
             "bundle_source_privacy: output has wrong owner or mode")
    began = time.time()
    deadline = time.monotonic() + args.budget
    action_end = deadline - 600
    receipt: dict[str, Any] = {"phase": "bundle-source", "run_id": args.run_id,
                               "holder": args.holder, "began": began,
                               "combined_deadline": began + args.budget,
                               "source_image_sha256": BUNDLE_IMAGE_SHA256,
                               "selected_source_f_sha256": BUNDLE_SOURCE_F_SHA256,
                               "checks": {}, "cleanup": [], "success": False,
                               "independently_authenticated": False,
                               "preservation_established": False}
    guest = SourcePrivateGuest(guest or WinGuest(), root)
    command = [str(pathlib.Path(__file__)), "bundle-source", "--run-id", args.run_id,
               "--holder", args.holder]
    booted = False
    run = None
    manifest = None
    source = None
    disk_hash = None
    capture_dir = None

    def action_left(cap: float) -> float:
        left = min(cap, action_end - time.monotonic())
        _require(left > 0, "bundle_source_deadline: action time expired; cleanup reserved")
        return left

    try:
        _require(args.manifest.stat().st_uid == os.getuid()
                 and stat.S_IMODE(args.manifest.stat().st_mode) == 0o600,
                 "bundle_source_privacy: prepared manifest is not owner/0600")
        manifest = json.loads(args.manifest.read_text())
        source, disk_hash = _source_contract(args.manifest, manifest)
        guards, identity, controls = _source_controls(args.controls, args.manifest, disk_hash)
        receipt["prepared_disk_sha256"] = disk_hash
        receipt["controls_sha256"] = sha256(args.controls)
        receipt["selected_guard_sha256"] = controls["guards"]["sha256"]
        receipt["selected_identity_sha256"] = controls["identity"]["sha256"]
        capture_dir = _capture_dir(args.run_id)
        _require(not set(route_darkness.DARKNESS.slot_letters(
            amiga_adf.AmigaDisk.open(manifest["disks"]["disk3"]["path"]))) & {"F", "G"},
            "bundle_source_manifest: F/G occupied before boot")
        boot = _boot(SourceBootGuest(guest, action_end, deadline), args.manifest, manifest,
                     args.holder, args.audio_proof,
                     time.monotonic() + action_left(1200), command)
        booted = True
        receipt["boot"] = {key: boot[key] for key in ("holder", "claim", "start")}
        receipt["boot"]["disk_keys"] = sorted(boot["remotes"])
        run = SourceGuardedRun(guest, args.holder, args.out / "screens", guards, action_end,
                               identity=identity)
        run.title()
        run.press("title", "P", "party_menu")
        run.press("party_menu", "L", "load_from")
        run.press("load_from", "P", "load_picker")
        run.press("load_picker", "B", "disk2_prompt")
        guest.insert(args.holder, 0, boot["remotes"]["disk2"], timeout=action_left(60),
                     sha256=manifest["disks"]["disk2"]["sha256"])
        run.press("disk2_prompt", "SPACE", "loaded_menu")
        run.press("loaded_menu", "V", "sheet")
        run.press("sheet", "E", "loaded_menu")
        run.press("loaded_menu", "S", "save_picker")
        target = _target(args.holder)
        receipt["initial"] = _source_checkpoint(target, capture_dir, "initial-pre-f",
                                                  receipt, run, disk_hash)
        first = receipt["item_nodes"][-1]
        source_disk = amiga_adf.AmigaDisk.open(source)
        receipt["initial_comparison"] = _source_compare(
            first, receipt["initial"], source_disk, "F", BUNDLE_SOURCE_F_SHA256,
            root, role="selected-source")
        _require(receipt["initial_comparison"]["all_payloads_match_reference"],
                 "bundle_source_reference: initial payload mismatch before F")
        receipt["checks"]["initial_coverage"] = True
        action_left(30)
        run.press("save_picker", "F", "loaded_menu")
        receipt["checks"]["save_f_ui_acknowledged"] = True
        f_disk, f_digest = _source_fetched(guest, boot["remotes"]["disk3"],
                                          args.out, action_left(120))
        receipt["same_run_f_sha256"] = f_digest
        receipt["checks"]["same_run_f_verified"] = True
        _source_world(run)
        run.press("world", "E", "camp")
        _require([m["name"] for m in receipt["initial"]["party"]] == list(BUNDLE_NAMES),
                 "bundle_source_identity: camp entry does not have the selected party")
        steps = route_camp.steps_for(("items 5",), name="darkness", party_size=7)
        _require(all(kind == "key" for _key, _state, kind in steps)
                 and steps[-1][1] == "camp", "bundle_source_camp: unexpected item route")
        state = "camp"
        for key, following, _kind in steps:
            run.press(state, key, following)
            state = following
        run.press("camp", "S", "camp_save_picker")
        target = _target(args.holder)
        receipt["pre_g"] = _source_checkpoint(target, capture_dir, "pre-g",
                                                receipt, run, disk_hash)
        second = receipt["item_nodes"][-1]
        receipt["pre_g_comparison"] = _source_compare(
            second, receipt["pre_g"], f_disk, "F", f_digest, root,
            role="same-run-F", previous=_source_saved_artifact(first, root))
        _require(receipt["pre_g_comparison"]["all_payloads_match_reference"],
                 "bundle_source_reference: pre-G differs from same-run F")
        receipt["checks"]["pre_g_coverage"] = True
        action_left(30)
        run.press("camp_save_picker", "G", "exit_game")
        run.press("exit_game", "N", "camp")
        receipt["checks"]["save_g_ui_acknowledged"] = True
        target = _target(args.holder)
        receipt["post_g"] = _source_checkpoint(target, capture_dir, "post-g",
                                                 receipt, run, disk_hash)
        receipt["checks"]["post_g_coverage"] = True
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if run is not None:
            receipt["screens"] = [{**event, **({"crop": pathlib.Path(event["crop"])
                                  .relative_to(root).as_posix()} if "crop" in event else {})}
                                  for event in run.events]
        if booted:
            try:
                left = min(30.0, max(1.0, deadline - time.monotonic()))
                if deadline - time.monotonic() <= 0:
                    receipt["cleanup"].append("cleanup deadline expired")
                receipt["halt"] = acceptance.halt_lane(
                    guest, args.holder, timeout=left, manifest_path=args.manifest,
                    command=command)
                receipt["checks"]["halt"] = True
                if receipt["checks"].get("save_f_ui_acknowledged"):
                    fetched = receipt["halt"]["fetched"]["disk3"]
                    _require(sha256(pathlib.Path(fetched["path"])) == fetched["sha256"],
                             "bundle_source_f: final fetched image digest differs")
                    final_disk = amiga_adf.AmigaDisk.open(fetched["path"])
                    _require(not final_disk.verify(), "bundle_source_g: fetched ADF fails verification")
                    raw = amiga_savegame.pod_read_slot(final_disk, "F")
                    final_f = hashlib.sha256(raw).hexdigest()
                    receipt["final_f_sha256"] = final_f
                    _require(final_f == receipt.get("same_run_f_sha256"),
                             "bundle_source_f: final same-run F differs from prior fetch")
                    receipt["checks"]["final_f_verified"] = True
                    if receipt["checks"].get("save_g_ui_acknowledged"):
                        g_digest = hashlib.sha256(amiga_savegame.pod_read_slot(
                            final_disk, "G")).hexdigest()
                        _source_slot(final_disk, "G", g_digest)
                        _require(route_darkness.DARKNESS.read_slot(final_disk, "G").get("place") ==
                                 BUNDLE_PLACE, "bundle_source_g: saved place differs")
                        receipt["same_run_g_sha256"] = g_digest
                        receipt["checks"]["same_run_g_verified"] = True
                        if receipt["checks"].get("post_g_coverage"):
                            receipt["post_g_comparison"] = _source_compare(
                                receipt["item_nodes"][-1], receipt["post_g"], final_disk,
                                "G", g_digest, root, role="same-run-G",
                                previous=_source_saved_artifact(receipt["item_nodes"][-2], root))
                            _require(receipt["post_g_comparison"]["all_payloads_match_reference"],
                                     "bundle_source_reference: post-G differs from same-run G")
                            receipt["checks"]["post_g_alignment"] = True
            except Exception as exc:  # noqa: BLE001 - retain all independent cleanup failures
                receipt["cleanup"].append(f"halt or fetched save: {exc}")
        try:
            _require(source is not None and sha256(source) == BUNDLE_IMAGE_SHA256,
                     "bundle_source_image: original changed")
            _source_slot(amiga_adf.AmigaDisk.open(source), "F", BUNDLE_SOURCE_F_SHA256)
            receipt["checks"]["source_unchanged"] = True
        except Exception as exc:  # noqa: BLE001
            receipt["cleanup"].append(f"source hash: {exc}")
        if disk_hash is not None and manifest is not None:
            try:
                _require(sha256(pathlib.Path(manifest["disks"]["disk3"]["path"])) == disk_hash
                         and sha256(args.manifest) == BUNDLE_MANIFEST_SHA256
                         and all(sha256(pathlib.Path(manifest["disks"][key]["path"])) == pin
                                 for key, pin in (("disk1", route_darkness.DARKNESS_DISK1_SHA256),
                                                  ("disk2", route_darkness.DARKNESS_DISK2_SHA256))),
                         "bundle_source_image: prepared originals changed")
                receipt["checks"]["prepared_unchanged"] = True
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append(f"prepared source hash: {exc}")
        if "halt" in receipt:
            for file in receipt["halt"].get("fetched", {}).values():
                if "path" in file:
                    location = pathlib.Path(file["path"])
                    if not location.resolve().is_relative_to(root.resolve()):
                        receipt["cleanup"].append("fetched path escapes private run")
                        file.pop("path")
                    else:
                        file["path"] = location.relative_to(root).as_posix()
        receipt["success"] = ("error" not in receipt and not receipt["cleanup"] and
                              all(receipt["checks"].get(key) is True for key in
                                  ("initial_coverage", "pre_g_coverage", "post_g_coverage",
                                   "save_f_ui_acknowledged", "same_run_f_verified",
                                   "save_g_ui_acknowledged", "same_run_g_verified",
                                   "post_g_alignment", "final_f_verified", "halt",
                                   "source_unchanged", "prepared_unchanged")))
        _write_source_receipt(args.out / "bundle-source-receipt.json", receipt)
    if not receipt["success"]:
        raise RouteError(receipt.get("error") or "; ".join(receipt["cleanup"]))
    return receipt


def _origin_party(target: amiga.AmigaTarget) -> dict:
    members = amigaparty.read_party(target)
    _source_members(members)
    return {"names": [member.name for member in members],
            "heads": list(BUNDLE_HEADS), "case": {"member": 4, "head": 2,
                                                   "saved_children": 4}}


def run_origin_observe(args: argparse.Namespace, *, guest: WinGuest | None = None) -> dict:
    """Observe source-G's loaded area and one legality verdict; never arm travel or save."""
    _require(os.name == "posix", "origin_privacy: POSIX owner checks are required")
    _require(900 < args.budget <= 1500,
             "origin_deadline: one boot must leave 300 seconds for cleanup")
    _require(not args.out.exists(), "origin_privacy: output must be fresh")
    root = pathlib.Path.home() / ".cache/wish/acceptance/360" / args.run_id
    _require(args.run_id not in ("", ".", "..") and pathlib.Path(args.run_id).name == args.run_id
             and args.out.parent.resolve() == root.resolve()
             and args.manifest.parent.resolve() == root.resolve(),
             "origin_privacy: output and fresh G preparation must share one private run")
    _require(_private_directory(root.stat(), os.getuid()),
             "origin_privacy: prepared run is not owner/0700")
    args.out.mkdir(mode=0o700)
    _require(_private_directory(args.out.stat(), os.getuid()),
             "origin_privacy: output is not owner/0700")
    began = time.time()
    deadline = time.monotonic() + args.budget
    action_end = deadline - 300
    receipt: dict[str, Any] = {"phase": "origin-observe", "run_id": args.run_id,
                               "holder": args.holder, "began": began,
                               "combined_deadline": began + args.budget,
                               "source_image_sha256": ORIGIN_IMAGE_SHA256,
                               "source_g_sha256": ORIGIN_G_SHA256,
                               "checks": {}, "cleanup": [], "success": False,
                               "independently_authenticated": False,
                               "preservation_established": False}
    guest = SourcePrivateGuest(guest or WinGuest(), root)
    command = [str(pathlib.Path(__file__)), "origin-observe", "--run-id", args.run_id,
               "--holder", args.holder]
    booted = False
    boot = None
    run = None
    manifest = None
    source = None
    disk_hash = None
    manifest_hash = None

    def action_left(cap: float) -> float:
        left = min(cap, action_end - time.monotonic())
        _require(left > 0, "origin_deadline: boot action expired; cleanup reserved")
        return left

    try:
        manifest = json.loads(args.manifest.read_text())
        source, disk_hash = _origin_contract(args.manifest, manifest)
        manifest_hash = sha256(args.manifest)
        guards, identity, controls = _origin_controls(
            args.controls, args.source_manifest, disk_hash)
        receipt["prepared_disk_sha256"] = disk_hash
        receipt["manifest_sha256"] = manifest_hash
        receipt["source_controls_sha256"] = sha256(args.controls)
        receipt["selected_guard_sha256"] = controls["guards"]["sha256"]
        receipt["selected_identity_sha256"] = controls["identity"]["sha256"]
        receipt["checks"]["preflight"] = True
        boot = _boot(SourceBootGuest(guest, action_end, deadline), args.manifest, manifest,
                     args.holder, args.audio_proof,
                     time.monotonic() + action_left(1200), command)
        booted = True
        receipt["boot"] = {key: boot[key] for key in ("holder", "claim", "start")}
        if boot.get("log_error"):
            raise RouteError(f"origin_boot_log: {boot['log_error']}")
        run = SourceGuardedRun(guest, args.holder, args.out / "screens", guards, action_end,
                               identity=identity)
        run.title()
        run.press("title", "P", "party_menu")
        run.press("party_menu", "L", "load_from")
        run.press("load_from", "P", "load_picker")
        run.press("load_picker", "B", "disk2_prompt")
        guest.insert(args.holder, 0, boot["remotes"]["disk2"], timeout=action_left(60),
                     sha256=manifest["disks"]["disk2"]["sha256"])
        run.press("disk2_prompt", "SPACE", "loaded_menu")
        run.press("loaded_menu", "B", "journal")
        run.press("journal", "X", "journal_answer")
        run.press("journal_answer", "RET", "world")
        receipt["checks"]["world_guarded"] = True
        target = _target(args.holder)
        receipt["party"] = _origin_party(target)
        receipt["checks"]["seven_members"] = True
        receipt["observation"] = _observe_origin(
            target, saved_area=BUNDLE_PLACE["area"],
            disks=pathlib.Path(manifest["disks"]["disk3"]["path"]).parent)
        receipt["checks"]["single_target_observed"] = True
        observation = receipt["observation"]
        receipt["route_status"] = ("gate_blocked" if not observation["gate"] else
                                   "saved_area_5" if observation["live_area"] == 5 else
                                   "forward_held" if not observation["offered"] else
                                   "forward_offered_return_unmeasured")
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if run is not None:
            receipt["screens"] = [{**event, **({"crop": pathlib.Path(event["crop"])
                                  .relative_to(root).as_posix()} if "crop" in event else {})}
                                  for event in run.events]
        if booted:
            fetching = OriginFetchGuest(SourceBootGuest(guest, action_end, deadline),
                                        root, boot["remotes"])
            try:
                left = min(30.0, max(1.0, deadline - time.monotonic()))
                if deadline - time.monotonic() <= 0:
                    receipt["cleanup"].append("origin_deadline: cleanup allowance expired")
                receipt["halt"] = acceptance.halt_lane(
                    fetching, args.holder, timeout=left)
                receipt["checks"]["halt"] = True
            except Exception as exc:  # noqa: BLE001 - retain cleanup failure
                receipt["cleanup"].append(f"halt: {exc}")
            finally:
                receipt.setdefault("halt", {}).setdefault("fetched", fetching.fetched)
                if fetching.partial:
                    receipt["halt"]["partial"] = fetching.partial
                receipt["cleanup"].extend(fetching.errors)
        try:
            _require(sha256(_origin_source()) == ORIGIN_IMAGE_SHA256,
                     "origin_source: preserved original changed")
            receipt["checks"]["source_unchanged"] = True
        except Exception as exc:  # noqa: BLE001
            receipt["cleanup"].append(f"source hash: {exc}")
        if disk_hash is not None and manifest is not None and manifest_hash is not None:
            try:
                _require(sha256(args.manifest) == manifest_hash and
                         sha256(pathlib.Path(manifest["disks"]["disk3"]["path"])) == disk_hash
                         and all(sha256(pathlib.Path(manifest["disks"][key]["path"])) == pin
                                 for key, pin in (("disk1", route_darkness.DARKNESS_DISK1_SHA256),
                                                  ("disk2", route_darkness.DARKNESS_DISK2_SHA256))),
                         "origin_manifest: prepared originals changed")
                receipt["checks"]["prepared_unchanged"] = True
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append(f"prepared hash: {exc}")
        if "halt" in receipt:
            for group in ("fetched", "partial"):
                for file in receipt["halt"].get(group, {}).values():
                    if "path" in file:
                        path = pathlib.Path(file["path"])
                        if not path.resolve().is_relative_to(root.resolve()):
                            receipt["cleanup"].append(
                                "origin_privacy: fetched path escapes private run")
                            file.pop("path")
                        else:
                            file["path"] = path.relative_to(root).as_posix()
        receipt["success"] = ("error" not in receipt and not receipt["cleanup"] and
                              all(receipt["checks"].get(key) is True for key in
                                  ("preflight", "world_guarded", "seven_members",
                                   "single_target_observed", "halt", "source_unchanged",
                                   "prepared_unchanged")))
        _write_source_receipt(args.out / "origin-observe-receipt.json", receipt)
    if not receipt["success"]:
        raise RouteError(receipt.get("error") or "; ".join(receipt["cleanup"]))
    return receipt


ORIGIN_REFERENCE = {"source_disk_sha256": ORIGIN_IMAGE_SHA256,
                    "source_g_sha256": ORIGIN_G_SHA256}
RETURN_CHECKS = ("preflight", "world_guarded", "start", "pre_travel_coverage", "legs",
                 "returned", "return_square", "post_return_coverage", "pre_f_coverage",
                 "save_f_ui_acknowledged", "same_run_f_verified", "post_f_alignment",
                 "halt", "final_f_verified", "source_unchanged", "prepared_unchanged")
RELOAD_CHECKS = ("preflight", "world_guarded", "reloaded", "reloaded_square", "reload_coverage",
                 "item_sheet_coverage", "halt", "no_save_written", "sources_unchanged",
                 "prepared_unchanged")


def _failure(receipt: dict, required: tuple[str, ...]) -> str:
    """The error, the cleanup failures, or else the required checks that did not pass."""
    return (receipt.get("error") or "; ".join(receipt["cleanup"]) or
            "failed checks: " + ", ".join(key for key in required
                                          if receipt["checks"].get(key) is not True))


def _origin_start(target: amiga.AmigaTarget, disks: pathlib.Path) -> dict:
    """Require the live origin, the open menu gate and an offered ordinary trip to 22."""
    observed = _observe_origin(target, saved_area=BUNDLE_PLACE["area"], disks=disks)
    square = amigatrip.square(target, amigatrip.row_for(TITLE))
    observed["square"] = None if square is None else list(square)
    _require(observed["live_area"] == ORIGIN_LIVE_AREA,
             f"return7_start: live area {observed['live_area']} is not {ORIGIN_LIVE_AREA}")
    _require(observed["gate"], "return7_start: the world menu gate is shut")
    _require(observed["offered"],
             f"return7_start: Fast Travel withholds area {ORIGIN_TARGET_AREA}: "
             f"{observed['reason']}")
    _require(square is not None, "return7_start: the party square is unreadable")
    return observed


def _origin_place(target: amiga.AmigaTarget, stage: str) -> dict:
    """Require the party back in the live origin at an open world menu."""
    row = amigatrip.row_for(TITLE)
    live = amigatrip.area_id(target, row)
    gate = bool(amigatrip.gate(target, row))
    square = amigatrip.square(target, row)
    _require(live == ORIGIN_LIVE_AREA,
             f"{stage}_area: the party is in area {live}, not {ORIGIN_LIVE_AREA}")
    _require(gate, f"{stage}_arrival: the world menu gate is shut")
    _require(square is not None, f"{stage}_arrival: the party square is unreadable")
    return {"live_area": live, "gate": gate, "square": list(square)}


def _relative_fetched(receipt: dict, root: pathlib.Path, prefix: str) -> None:
    """Keep fetched paths relative to the private run, dropping any that escape it."""
    for group in ("fetched", "partial"):
        for file in receipt.get("halt", {}).get(group, {}).values():
            if "path" in file:
                path = pathlib.Path(file["path"])
                if not path.resolve().is_relative_to(root.resolve()):
                    receipt["cleanup"].append(f"{prefix}_privacy: fetched path escapes private run")
                    file.pop("path")
                else:
                    file["path"] = path.relative_to(root).as_posix()


def _fresh_output(out: pathlib.Path, prefix: str) -> None:
    """Create a phase's owner-only output and its private item-node folder."""
    for directory in (out, out / "item-nodes"):
        directory.mkdir(mode=0o700)
        _require(_private_directory(directory.stat(), os.getuid()),
                 f"{prefix}_privacy: {directory.name} is not owner/0700")


def _origin_guest(args: argparse.Namespace, guest: Any) -> Any:
    """The lane `--emulator` names, unless the caller supplied one."""
    if guest is not None:
        return guest
    if getattr(args, "emulator", "winuae") == "fsuae":
        from tools.amiga import fsuaesession  # noqa: PLC0415

        return fsuaesession.FsuaeGuest(game="amiga-darkness",
                                       first_key_after=fsuaesession.FIRST_KEY_AFTER["darkness"])
    return WinGuest()


def _require_fsuae_api(args: argparse.Namespace, guest: Any) -> None:
    """Stop before the boot when an FS-UAE guest lacks the screen or live-read calls the phase ends on."""
    if getattr(args, "emulator", "winuae") != "fsuae":
        return
    for name in ("shot", "get_live"):
        _require(callable(getattr(guest, name, None)),
                 f"fsuae_guest: the FS-UAE guest has no {name} method")


def run_origin_return(args: argparse.Namespace, *, guest: WinGuest | None = None) -> dict:
    """One boot: load source-01 G, Fast Travel to 22 and Return, capture, and save a new F."""
    _require(os.name == "posix", "return7_privacy: POSIX owner checks are required")
    _require(1800 < args.budget <= MAX_EXPERIMENT_SECONDS,
             "return7_deadline: the budget must exceed 1800 and stay within 3600 seconds")
    _require(not args.out.exists(), "return7_privacy: output must be fresh")
    root = pathlib.Path.home() / ".cache/wish/acceptance/360" / args.run_id
    _require(args.run_id not in ("", ".", "..") and pathlib.Path(args.run_id).name == args.run_id
             and args.out.parent.resolve() == root.resolve()
             and args.manifest.parent.resolve() == root.resolve(),
             "return7_privacy: output and the G preparation must share one private run")
    _require(_private_directory(root.stat(), os.getuid()),
             "return7_privacy: prepared run is not owner/0700")
    _fresh_output(args.out, "return7")
    nodes = args.out / "item-nodes"
    began = time.time()
    deadline = time.monotonic() + args.budget
    action_end = deadline - 300
    receipt: dict[str, Any] = {"phase": "origin-return", "run_id": args.run_id,
                               "holder": args.holder, "began": began,
                               "combined_deadline": began + args.budget,
                               "source_image_sha256": ORIGIN_IMAGE_SHA256,
                               "source_g_sha256": ORIGIN_G_SHA256,
                               "origin_live_area": ORIGIN_LIVE_AREA,
                               "target_area": ORIGIN_TARGET_AREA,
                               "checks": {}, "cleanup": [], "success": False,
                               "independently_authenticated": False,
                               "preservation_established": False}
    guest = SourcePrivateGuest(_origin_guest(args, guest), root)
    receipt["emulator"] = getattr(args, "emulator", "winuae")
    command = [str(pathlib.Path(__file__)), "origin-return", "--run-id", args.run_id,
               "--holder", args.holder]
    booted = False
    boot = None
    run = None
    manifest = None
    disk_hash = None
    manifest_hash = None

    def action_left(cap: float) -> float:
        left = min(cap, action_end - time.monotonic())
        _require(left > 0, "return7_deadline: boot action expired; cleanup reserved")
        return left

    def checkpoint(target: amiga.AmigaTarget, name: str, screen: str) -> tuple[dict, dict]:
        reading = _source_checkpoint(target, nodes, name, receipt, run, disk_hash,
                                     screens=(screen,), reference=ORIGIN_REFERENCE)
        return reading, receipt["item_nodes"][-1]

    try:
        manifest = json.loads(args.manifest.read_text())
        source, disk_hash = _origin_contract(args.manifest, manifest)
        manifest_hash = sha256(args.manifest)
        guards, identity, controls = _origin_controls(
            args.controls, args.source_manifest, disk_hash)
        receipt["prepared_disk_sha256"] = disk_hash
        receipt["manifest_sha256"] = manifest_hash
        receipt["source_controls_sha256"] = sha256(args.controls)
        receipt["selected_guard_sha256"] = controls["guards"]["sha256"]
        receipt["selected_identity_sha256"] = controls["identity"]["sha256"]
        source_disk = amiga_adf.AmigaDisk.open(source)
        receipt["checks"]["preflight"] = True
        _require_fsuae_api(args, guest)
        boot = _boot(SourceBootGuest(guest, action_end, deadline), args.manifest, manifest,
                     args.holder, args.audio_proof,
                     time.monotonic() + action_left(1200), command)
        booted = True
        receipt["boot"] = {key: boot[key] for key in ("holder", "claim", "start")}
        if boot.get("log_error"):
            raise RouteError(f"return7_boot_log: {boot['log_error']}")
        run = SourceGuardedRun(guest, args.holder, args.out / "screens", guards, action_end,
                               identity=identity)
        run.title()
        run.press("title", "P", "party_menu")
        run.press("party_menu", "L", "load_from")
        run.press("load_from", "P", "load_picker")
        run.press("load_picker", "B", "disk2_prompt")
        guest.insert(args.holder, 0, boot["remotes"]["disk2"], timeout=action_left(60),
                     sha256=manifest["disks"]["disk2"]["sha256"])
        run.press("disk2_prompt", "SPACE", "loaded_menu")
        run.press("loaded_menu", "B", "journal")
        run.press("journal", "X", "journal_answer")
        run.press("journal_answer", "RET", "world")
        receipt["checks"]["world_guarded"] = True
        target = _target_on(args.holder, guest)
        receipt["party"] = _origin_party(target)
        receipt["start"] = _origin_start(target, args.manifest.parent)
        receipt["checks"]["start"] = True
        receipt["pre_travel"], first = checkpoint(target, "pre-travel", "world")
        receipt["pre_travel_comparison"] = _source_compare(
            first, receipt["pre_travel"], source_disk, "G", ORIGIN_G_SHA256, args.out,
            role="origin-source-G")
        _require(receipt["pre_travel_comparison"]["all_payloads_match_reference"],
                 "return7_payload: the loaded party differs from source G before travel")
        receipt["checks"]["pre_travel_coverage"] = True
        receipt["legs"] = _origin_legs(_origin_trip(guest, args.holder, args.manifest.parent,
                                                   args.out / "trip", action_left(2000)),
                                       args.out / "trip" / "fasttravel.jsonl")
        receipt["checks"]["legs"] = True
        run.see("world", 60)
        target = _target_on(args.holder, guest)
        receipt["returned"] = _origin_place(target, "return7")
        receipt["return_square_matches_start"] = (
            receipt["returned"]["square"] == receipt["start"]["square"])
        receipt["return_square_expected"] = list(ORIGIN_RETURN_SQUARE)
        receipt["return_square_matches_arrival"] = (
            receipt["returned"]["square"] == list(ORIGIN_RETURN_SQUARE))
        # The game's own arrival square for this pinned origin; a miss fails the run,
        # but the save and comparisons still go ahead, so the item evidence is kept.
        receipt["checks"]["return_square"] = receipt["return_square_matches_arrival"]
        receipt["checks"]["returned"] = True
        receipt["post_return"], returned = checkpoint(target, "post-return", "world")
        receipt["post_return_comparison"] = _source_compare(
            returned, receipt["post_return"], source_disk, "G", ORIGIN_G_SHA256, args.out,
            role="origin-source-G", previous=_source_saved_artifact(first, args.out))
        _require(receipt["post_return_comparison"]["all_payloads_match_reference"],
                 "return7_payload: a saved payload byte changed across Return, before F")
        receipt["checks"]["post_return_coverage"] = True
        run.press("world", "E", "camp")
        run.press("camp", "S", "camp_save_picker")
        receipt["pre_f"], before_f = checkpoint(target, "pre-f", "camp_save_picker")
        receipt["pre_f_source_comparison"] = _source_compare(
            before_f, receipt["pre_f"], source_disk, "G", ORIGIN_G_SHA256, args.out,
            role="origin-source-G", previous=_source_saved_artifact(returned, args.out))
        _require(receipt["pre_f_source_comparison"]["all_payloads_match_reference"],
                 "return7_payload: the party differs from source G at the save picker")
        receipt["checks"]["pre_f_coverage"] = True
        action_left(30)
        run.press("camp_save_picker", SAVE_LETTER, "exit_game")
        run.press("exit_game", "N", "camp")
        receipt["checks"]["save_f_ui_acknowledged"] = True
        f_disk, f_digest = _source_fetched(guest, boot["remotes"]["disk3"], args.out,
                                           action_left(120), place=None)
        receipt["same_run_f_sha256"] = f_digest
        place = route_darkness.DARKNESS.read_slot(f_disk, SAVE_LETTER).get("place") or {}
        receipt["saved_place"] = place
        _require([place.get(field) for field in ("x", "y", "facing")] ==
                 receipt["returned"]["square"],
                 "return7_saved_place: F holds another square or facing than the returned party")
        receipt["checks"]["same_run_f_verified"] = True
        receipt["pre_f_comparison"] = _source_compare(
            before_f, receipt["pre_f"], f_disk, SAVE_LETTER, f_digest, args.out,
            role="return-new-F")
        _require(receipt["pre_f_comparison"]["all_payloads_match_reference"],
                 "return7_payload: game-written F differs from the party it saved")
        receipt["post_f"], after_f = checkpoint(target, "post-f", "camp")
        receipt["post_f_comparison"] = _source_compare(
            after_f, receipt["post_f"], f_disk, SAVE_LETTER, f_digest, args.out,
            role="return-new-F", previous=_source_saved_artifact(before_f, args.out))
        _require(receipt["post_f_comparison"]["all_payloads_match_reference"],
                 "return7_payload: the party after the save differs from game-written F")
        receipt["checks"]["post_f_alignment"] = True
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if run is not None:
            receipt["screens"] = [{**event, **({"crop": pathlib.Path(event["crop"])
                                  .relative_to(root).as_posix()} if "crop" in event else {})}
                                  for event in run.events]
        if booted:
            fetching = OriginFetchGuest(SourceBootGuest(guest, action_end, deadline),
                                        root, boot["remotes"], folder=f"{args.out.name}/fetched")
            try:
                left = min(30.0, max(1.0, deadline - time.monotonic()))
                if deadline - time.monotonic() <= 0:
                    receipt["cleanup"].append("return7_deadline: cleanup allowance expired")
                receipt["halt"] = acceptance.halt_lane(fetching, args.holder, timeout=left)
                receipt["checks"]["halt"] = True
            except Exception as exc:  # noqa: BLE001 - retain cleanup failure
                receipt["cleanup"].append(f"halt: {exc}")
            finally:
                receipt.setdefault("halt", {}).setdefault("fetched", fetching.fetched)
                if fetching.partial:
                    receipt["halt"]["partial"] = fetching.partial
                receipt["cleanup"].extend(fetching.errors)
            if receipt["checks"].get("save_f_ui_acknowledged"):
                try:
                    fetched = fetching.fetched["disk3"]
                    final_path = pathlib.Path(fetched["path"])
                    _require(sha256(final_path) == fetched["sha256"],
                             "return7_f: final fetched image digest differs")
                    final = amiga_adf.AmigaDisk.open(final_path)
                    _require(not final.verify(), "return7_f: final fetched ADF fails verification")
                    final_f = hashlib.sha256(amiga_savegame.pod_read_slot(
                        final, SAVE_LETTER)).hexdigest()
                    receipt["final_f_sha256"] = final_f
                    _require(final_f == receipt.get("same_run_f_sha256"),
                             "return7_f: final fetched F differs from its readback")
                    _require("G" not in route_darkness.DARKNESS.slot_letters(final),
                             "return7_f: the run wrote slot G")
                    receipt["checks"]["final_f_verified"] = True
                except Exception as exc:  # noqa: BLE001
                    receipt["cleanup"].append(f"final F: {exc}")
        try:
            _require(sha256(_origin_source()) == ORIGIN_IMAGE_SHA256,
                     "origin_source: preserved original changed")
            receipt["checks"]["source_unchanged"] = True
        except Exception as exc:  # noqa: BLE001
            receipt["cleanup"].append(f"source hash: {exc}")
        if disk_hash is not None and manifest is not None and manifest_hash is not None:
            try:
                _require(sha256(args.manifest) == manifest_hash and
                         sha256(pathlib.Path(manifest["disks"]["disk3"]["path"])) == disk_hash
                         and all(sha256(pathlib.Path(manifest["disks"][key]["path"])) == pin
                                 for key, pin in (("disk1", route_darkness.DARKNESS_DISK1_SHA256),
                                                  ("disk2", route_darkness.DARKNESS_DISK2_SHA256))),
                         "origin_manifest: prepared originals changed")
                receipt["checks"]["prepared_unchanged"] = True
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append(f"prepared hash: {exc}")
        _relative_fetched(receipt, root, "return7")
        receipt["success"] = ("error" not in receipt and not receipt["cleanup"] and
                              all(receipt["checks"].get(key) is True for key in RETURN_CHECKS))
        _write_source_receipt(args.out / "origin-return-receipt.json", receipt)
    if not receipt["success"]:
        raise RouteError(_failure(receipt, RETURN_CHECKS))
    return receipt


def _return_seed(path: pathlib.Path) -> dict:
    """The successful Return receipt's fetched disk 3 and the game-written F it holds."""
    _require(path.name == "origin-return-receipt.json" and path.is_file()
             and path.stat().st_uid == os.getuid()
             and stat.S_IMODE(path.stat().st_mode) == 0o600,
             "reload7_receipt: the Return receipt is missing or not owner/0600")
    receipt = json.loads(path.read_text())
    checks = receipt.get("checks", {})
    _require(receipt.get("source_g_sha256") == ORIGIN_G_SHA256
             and receipt.get("source_image_sha256") == ORIGIN_IMAGE_SHA256,
             "reload7_receipt: the Return receipt names another source G or image")
    _require(receipt.get("phase") == "origin-return" and receipt.get("success") is True
             and not receipt.get("cleanup")
             and all(checks.get(key) is True for key in RETURN_CHECKS),
             "reload7_receipt: the Return receipt is not a complete success")
    digest = receipt.get("same_run_f_sha256")
    _require(isinstance(digest, str) and digest == receipt.get("final_f_sha256"),
             "reload7_receipt: the Return run's F readbacks differ")
    out = path.parent
    root = out.parent
    relative = pathlib.PurePosixPath(receipt["halt"]["fetched"]["disk3"]["path"])
    _require(not relative.is_absolute() and ".." not in relative.parts,
             "reload7_receipt: the fetched disk path escapes its run")
    disk_path = root.joinpath(*relative.parts)
    _require(disk_path.is_file()
             and sha256(disk_path) == receipt["halt"]["fetched"]["disk3"]["sha256"],
             "reload7_seed: the fetched disk 3 differs from its receipt")
    disk = amiga_adf.AmigaDisk.open(disk_path)
    _require(not disk.verify(), "reload7_seed: the fetched disk 3 fails ADF verification")
    try:
        _source_slot(disk, SAVE_LETTER, digest)
    except RouteError as exc:
        raise RouteError(f"reload7_seed: game-written F differs: {exc}") from exc
    entries = {entry["checkpoint"]: entry for entry in receipt["item_nodes"]}
    _require("post-f" in entries, "reload7_receipt: the post-F capture is missing")
    return {"receipt": receipt, "out": out, "disk": disk_path, "disk_sha256": sha256(disk_path),
            "f_sha256": digest, "post_f": entries["post-f"], "place": receipt["saved_place"],
            "square": receipt["returned"]["square"]}


def _reload_contract(manifest_path: pathlib.Path, manifest: dict, seed: dict) -> str:
    """Check the fresh B made from the Return run's game-written F."""
    _require(manifest_path.is_file() and manifest_path.stat().st_uid == os.getuid()
             and stat.S_IMODE(manifest_path.stat().st_mode) == 0o600,
             "reload7_privacy: prepared manifest is not owner/0600")
    _require(manifest.get("title") == "darkness" and manifest.get("loaded_letter") == "B"
             and manifest.get("names_a") == list(BUNDLE_NAMES)
             and manifest.get("substitute") == {"path": str(seed["disk"]),
                                                "sha256": seed["disk_sha256"], "letter": "F"},
             "reload7_manifest: B was not made from the Return run's F")
    path = _private_media(manifest_path, manifest, "reload7")
    digest = sha256(path)
    _require(manifest["disks"]["disk3"]["sha256"] == digest and digest != seed["disk_sha256"],
             "reload7_manifest: prepared disk 3 digest differs or is the fetched disk")
    disk = amiga_adf.AmigaDisk.open(path)
    _require(not disk.verify() and not {"F", "G"} & set(route_darkness.DARKNESS.slot_letters(disk)),
             "reload7_manifest: B disk is damaged or F/G is occupied")
    _require(hashlib.sha256(disk.read_file(LIBRARY)).hexdigest() == LIBRARY_HASH,
             "reload7_manifest: prepared ECL library digest differs")
    try:
        prepared_b, _ = _source_slot(disk, "B", seed["f_sha256"])
    except RouteError as exc:
        raise RouteError(f"reload7_manifest: saved B differs: {exc}") from exc
    _require(prepared_b == amiga_savegame.pod_read_slot(
        amiga_adf.AmigaDisk.open(seed["disk"]), SAVE_LETTER)
             and route_darkness.DARKNESS.read_slot(disk, "B").get("place") == seed["place"],
             "reload7_manifest: prepared B is not the Return run's F")
    return digest


def _reload_controls(path: pathlib.Path, source_manifest: pathlib.Path
                     ) -> tuple[PixelGuards, PixelGuards, dict]:
    """Use the source-01 selected rules for the reload of the same seven-member party."""
    _require(source_manifest.is_file() and sha256(source_manifest) == BUNDLE_MANIFEST_SHA256,
             "reload7_controls: source-01 manifest differs")
    return _source_controls(path, source_manifest, BUNDLE_PREPARED_SHA256)


def run_origin_reload(args: argparse.Namespace, *, guest: WinGuest | None = None) -> dict:
    """One boot: load the Return run's game-written F, view the sheet and HILDE's items."""
    _require(os.name == "posix", "reload7_privacy: POSIX owner checks are required")
    _require(900 < args.budget <= 1500,
             "reload7_deadline: one boot must leave 300 seconds for cleanup")
    root = pathlib.Path.home() / ".cache/wish/acceptance/360" / args.run_id
    _require(args.run_id not in ("", ".", "..") and pathlib.Path(args.run_id).name == args.run_id
             and args.out.parent.resolve() == root.resolve() and not root.exists(),
             "reload7_privacy: the reload needs a fresh private run holding its output")
    seed = _return_seed(args.return_receipt)
    old_umask = os.umask(0o077)
    try:
        manifest_path = acceptance.prepare(route_darkness.DARKNESS, args.run_id,
                                           substitute=seed["disk"], substitute_letter="F",
                                           issue="360")
    finally:
        os.umask(old_umask)
    _require(manifest_path.parent.resolve() == root.resolve()
             and _private_directory(root.stat(), os.getuid()),
             "reload7_privacy: fresh preparation is not owner/0700")
    _fresh_output(args.out, "reload7")
    nodes = args.out / "item-nodes"
    began = time.time()
    deadline = time.monotonic() + args.budget
    action_end = deadline - 300
    receipt: dict[str, Any] = {"phase": "origin-reload", "run_id": args.run_id,
                               "holder": args.holder, "began": began,
                               "combined_deadline": began + args.budget,
                               "return_receipt": str(args.return_receipt),
                               "return_receipt_sha256": sha256(args.return_receipt),
                               "seed_disk_sha256": seed["disk_sha256"],
                               "reference_f_sha256": seed["f_sha256"],
                               "checks": {}, "cleanup": [], "success": False,
                               "independently_authenticated": False,
                               "preservation_established": False}
    guest = SourcePrivateGuest(_origin_guest(args, guest), root)
    receipt["emulator"] = getattr(args, "emulator", "winuae")
    command = [str(pathlib.Path(__file__)), "origin-reload", "--run-id", args.run_id,
               "--holder", args.holder]
    reference = {"source_disk_sha256": seed["disk_sha256"], "source_f_sha256": seed["f_sha256"]}
    booted = False
    boot = None
    run = None
    manifest = None
    disk_hash = None
    manifest_hash = None

    def action_left(cap: float) -> float:
        left = min(cap, action_end - time.monotonic())
        _require(left > 0, "reload7_deadline: boot action expired; cleanup reserved")
        return left

    try:
        manifest = json.loads(manifest_path.read_text())
        disk_hash = _reload_contract(manifest_path, manifest, seed)
        manifest_hash = sha256(manifest_path)
        guards, identity, controls = _reload_controls(args.controls, args.source_manifest)
        receipt["prepared_disk_sha256"] = disk_hash
        receipt["manifest_sha256"] = manifest_hash
        receipt["source_controls_sha256"] = sha256(args.controls)
        receipt["selected_guard_sha256"] = controls["guards"]["sha256"]
        receipt["selected_identity_sha256"] = controls["identity"]["sha256"]
        seed_disk = amiga_adf.AmigaDisk.open(seed["disk"])
        receipt["checks"]["preflight"] = True
        _require_fsuae_api(args, guest)
        boot = _boot(SourceBootGuest(guest, action_end, deadline), manifest_path, manifest,
                     args.holder, args.audio_proof,
                     time.monotonic() + action_left(1200), command)
        booted = True
        receipt["boot"] = {key: boot[key] for key in ("holder", "claim", "start")}
        if boot.get("log_error"):
            raise RouteError(f"reload7_boot_log: {boot['log_error']}")
        run = SourceGuardedRun(guest, args.holder, args.out / "screens", guards, action_end,
                               identity=identity)
        run.title()
        run.press("title", "P", "party_menu")
        run.press("party_menu", "L", "load_from")
        run.press("load_from", "P", "load_picker")
        run.press("load_picker", "B", "disk2_prompt")
        guest.insert(args.holder, 0, boot["remotes"]["disk2"], timeout=action_left(60),
                     sha256=manifest["disks"]["disk2"]["sha256"])
        run.press("disk2_prompt", "SPACE", "loaded_menu")
        run.press("loaded_menu", "V", "sheet")
        run.press("sheet", "E", "loaded_menu")
        run.press("loaded_menu", "B", "journal")
        run.press("journal", "X", "journal_answer")
        run.press("journal_answer", "RET", "world")
        receipt["checks"]["world_guarded"] = True
        target = _target_on(args.holder, guest)
        receipt["party"] = _origin_party(target)
        receipt["reloaded"] = _origin_place(target, "reload7")
        receipt["reloaded_square_matches_saved"] = receipt["reloaded"]["square"] == seed["square"]
        receipt["checks"]["reloaded_square"] = receipt["reloaded_square_matches_saved"]
        receipt["checks"]["reloaded"] = True
        receipt["reload_world"] = _source_checkpoint(
            target, nodes, "reload-world", receipt, run, disk_hash,
            screens=("world",), reference=reference)
        loaded = receipt["item_nodes"][-1]
        receipt["reload_comparison"] = _source_compare(
            loaded, receipt["reload_world"], seed_disk, SAVE_LETTER, seed["f_sha256"],
            args.out, role="reload-F",
            previous=_source_saved_artifact(seed["post_f"], seed["out"]))
        _require(receipt["reload_comparison"]["all_payloads_match_reference"],
                 "reload7_payload: the reloaded party differs from the Return run's F")
        receipt["checks"]["reload_coverage"] = True
        run.press("world", "E", "camp")
        steps = route_camp.steps_for(("items 5",), name="darkness", party_size=7)
        _require(all(kind == "key" for _key, _state, kind in steps)
                 and steps[-1][1] == "camp", "reload7_camp: unexpected item route")
        state = "camp"
        for key, following, _kind in steps:
            run.press(state, key, following)
            state = following
        receipt["reload_items"] = _source_checkpoint(
            target, nodes, "reload-items", receipt, run, disk_hash,
            screens=("camp",), reference=reference)
        receipt["item_sheet_comparison"] = _source_compare(
            receipt["item_nodes"][-1], receipt["reload_items"], seed_disk, SAVE_LETTER,
            seed["f_sha256"], args.out, role="reload-F",
            previous=_source_saved_artifact(loaded, args.out))
        _require(receipt["item_sheet_comparison"]["all_payloads_match_reference"],
                 "reload7_payload: HILDE's item view changed a saved payload byte")
        receipt["checks"]["item_sheet_coverage"] = True
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if run is not None:
            receipt["screens"] = [{**event, **({"crop": pathlib.Path(event["crop"])
                                  .relative_to(root).as_posix()} if "crop" in event else {})}
                                  for event in run.events]
        if booted:
            fetching = OriginFetchGuest(SourceBootGuest(guest, action_end, deadline),
                                        root, boot["remotes"], folder=f"{args.out.name}/fetched")
            try:
                left = min(30.0, max(1.0, deadline - time.monotonic()))
                if deadline - time.monotonic() <= 0:
                    receipt["cleanup"].append("reload7_deadline: cleanup allowance expired")
                receipt["halt"] = acceptance.halt_lane(fetching, args.holder, timeout=left)
                receipt["checks"]["halt"] = True
            except Exception as exc:  # noqa: BLE001 - retain cleanup failure
                receipt["cleanup"].append(f"halt: {exc}")
            finally:
                receipt.setdefault("halt", {}).setdefault("fetched", fetching.fetched)
                if fetching.partial:
                    receipt["halt"]["partial"] = fetching.partial
                receipt["cleanup"].extend(fetching.errors)
            try:
                # A load without a save leaves disk 3 byte-identical to the uploaded copy
                # (the origin observer's fetched disk 3 equals its prepared one).
                final = fetching.fetched["disk3"]
                _require(disk_hash is not None and final["sha256"] == disk_hash
                         and sha256(pathlib.Path(final["path"])) == disk_hash,
                         "reload7_save: the disk 3 the game ran differs from the prepared disk 3")
                receipt["checks"]["no_save_written"] = True
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append(f"reload disk: {exc}")
        try:
            _require(sha256(_origin_source()) == ORIGIN_IMAGE_SHA256
                     and sha256(seed["disk"]) == seed["disk_sha256"]
                     and sha256(args.return_receipt) == receipt["return_receipt_sha256"],
                     "reload7_source: source G, the Return disk or its receipt changed")
            receipt["checks"]["sources_unchanged"] = True
        except Exception as exc:  # noqa: BLE001
            receipt["cleanup"].append(f"source hash: {exc}")
        if disk_hash is not None and manifest is not None and manifest_hash is not None:
            try:
                _require(sha256(manifest_path) == manifest_hash and
                         sha256(pathlib.Path(manifest["disks"]["disk3"]["path"])) == disk_hash
                         and all(sha256(pathlib.Path(manifest["disks"][key]["path"])) == pin
                                 for key, pin in (("disk1", route_darkness.DARKNESS_DISK1_SHA256),
                                                  ("disk2", route_darkness.DARKNESS_DISK2_SHA256))),
                         "reload7_manifest: prepared originals changed")
                receipt["checks"]["prepared_unchanged"] = True
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append(f"prepared hash: {exc}")
        _relative_fetched(receipt, root, "reload7")
        receipt["success"] = ("error" not in receipt and not receipt["cleanup"] and
                              all(receipt["checks"].get(key) is True for key in RELOAD_CHECKS))
        _write_source_receipt(args.out / "origin-reload-receipt.json", receipt)
    if not receipt["success"]:
        raise RouteError(_failure(receipt, RELOAD_CHECKS))
    return receipt


def _write_source_receipt(path: pathlib.Path, receipt: dict) -> None:
    """Publish a private, read-back checked report without game payloads."""
    _require("raw_hex" not in json.dumps(receipt),
             "bundle_source_privacy: raw node bytes reached the public receipt")
    payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    temp = path.with_name(path.name + ".tmp")
    try:
        with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
            file.write(payload)
        _require(temp.stat().st_uid == os.getuid()
                 and stat.S_IMODE(temp.stat().st_mode) == 0o600,
                 "bundle_source_privacy: receipt has wrong owner or mode")
        temp.replace(path)
        _require(path.stat().st_uid == os.getuid()
                 and stat.S_IMODE(path.stat().st_mode) == 0o600
                 and hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(payload).digest(),
                 "bundle_source_privacy: private receipt readback differs")
    finally:
        temp.unlink(missing_ok=True)


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
    legs = _run_trip(holder, disks, out, left)
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


def _origin_legs(legs: list[dict], log: pathlib.Path) -> list[dict]:
    """Require ordinary forward travel from the live origin to 22 and Return to it.

    Each arrival may take one RET, and only at the PRESS RETURN bar: the trip
    log must show that the title's continue guard matched the frame the key
    answered. Taydome's Keep and Kalistes' Parlor both open on that bar.
    """
    _require(len(legs) == 2 and all(leg.get("result") == "idle"
                                   and leg.get("settled") for leg in legs),
             "return7_trip: the trip did not finish two settled legs")
    forward, back = (leg.get("areas_seen") or [None] for leg in legs)
    _require(forward[0] == ORIGIN_LIVE_AREA and forward[-1] == ORIGIN_TARGET_AREA
             and back[0] == ORIGIN_TARGET_AREA and back[-1] == ORIGIN_LIVE_AREA,
             f"return7_area: legs saw {forward} then {back}, not "
             f"{ORIGIN_LIVE_AREA} to {ORIGIN_TARGET_AREA} and back")
    _require(all(leg.get("arrival_keys") in ([], ["RET"]) for leg in legs),
             "return7_prompt: a leg answered a prompt other than the guarded arrival bar")
    try:
        events = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        raise RouteError(f"return7_prompt: the trip log is unreadable: {exc}") from exc
    starts = [i for i, event in enumerate(events) if event.get("event") == "legality"]
    _require(len(starts) == 2, "return7_prompt: the trip log does not hold two legs")
    for leg, begin, end in zip(legs, starts, starts[1:] + [len(events)], strict=True):
        answers = [event for event in events[begin:end]
                   if event.get("event") == "arrival_answer"]
        _require([event.get("key") for event in answers] == leg["arrival_keys"]
                 and all(event.get("at_continue") is True for event in answers),
                 "return7_prompt: an arrival key went without the guarded PRESS RETURN bar")
    return legs


def _run_trip(holder: str, disks: pathlib.Path, out: pathlib.Path, left: float) -> list[dict]:
    """Run the ordinary forward trip to 22 and its Return in the Fast Travel driver."""
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
        return [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
    except json.JSONDecodeError as exc:
        raise RouteError("the trip returned an unreadable leg receipt") from exc


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
    target.locate(memory=_measured_regions(target, check_target=False))
    return target


def _target_on(holder: str, guest: Any) -> amiga.AmigaTarget:
    """The target on the debugger connection of an FS-UAE guest, else on WinUAE's pipe for `holder`."""
    gdb = getattr(guest, "gdb", None)
    if gdb is None:
        return _target(holder)
    target = amiga.AmigaTarget(gdb, amiga.MACHINES[TITLE])
    target.locate(memory=_measured_regions(target, check_target=False))
    return target


def _origin_trip(guest: Any, holder: str, disks: pathlib.Path, out: pathlib.Path,
                 left: float) -> list[dict]:
    """The guarded trip to 22 and back: a driver subprocess on WinUAE, in this process on FS-UAE.

    FS-UAE serves one debugger client and the guest holds it, so the legs run here on its target.
    Each leg gets half of `left`, at most 900 seconds; on WinUAE `left` bounds the subprocess.
    """
    if getattr(guest, "gdb", None) is None:
        return _run_trip(holder, disks, out, left)
    target = _target_on(holder, guest)

    def press(key: str) -> None:
        guest.press(holder, key, 30)
        time.sleep(fasttravelrun.SETTLE_SECONDS)

    out.mkdir(parents=True, exist_ok=False)
    legs: list[dict] = []
    try:
        fasttravelrun.run_legs(
            TITLE, str(disks), 22, True, ("RET",),
            fasttravelrun.amigavars.parse_list("25,26,34,35,129,C1,BF"), out, target,
            guest.shot, press, min(900.0, left / 2), report=legs.append)
    except (fasttravelrun.DriverError, amiga.GuestError, amiga.FsuaeError) as exc:
        raise RouteError(str(exc)) from exc
    return legs


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
        receipt["pre_f"] = _checkpoint(target, capture_dir, "pre-f", receipt, run,
                                       disk_sha256=disk_hash, loaded_slot_sha256=slot_hash,
                                       intervention=intervention)
        run.press("camp_save_picker", SAVE_LETTER, "exit_game")
        run.press("exit_game", "N", "camp")
        receipt["checks"]["save_ui_acknowledged"] = True
        receipt["post_save"] = _checkpoint(target, capture_dir, "post-save-quit", receipt, run,
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
                    if receipt["checks"]["post_save_capture"]:
                        entries = {entry["checkpoint"]: entry for entry in receipt["item_nodes"]}
                        receipt["item_comparison"] = _compare_nodes(
                            entries["pre-f"], receipt["pre_f"],
                            entries["post-save-quit"], receipt["post_save"], saved_disk,
                            capture_dir.parent.parent, slot_f_hash)
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
        prior = {entry["checkpoint"]: entry for entry in p2["item_nodes"]}
        receipt["item_comparison"] = _compare_nodes(
            prior["pre-f"], p2["pre_f"], receipt["item_nodes"][0], before,
            prepared, capture_dir.parent.parent, p2.get("game_written_f_sha256"))
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
    source = phases.add_parser("bundle-source")
    source.add_argument("--run-id", required=True)
    source.add_argument("--holder", required=True)
    source.add_argument("--audio-proof", type=pathlib.Path, required=True)
    source.add_argument("--manifest", type=pathlib.Path, required=True)
    source.add_argument("--controls", type=pathlib.Path, required=True)
    source.add_argument("--out", type=pathlib.Path, required=True)
    source.add_argument("--budget", type=float, required=True)
    origin_prepare = phases.add_parser("origin-prepare")
    origin_prepare.add_argument("--run-id", required=True)
    for name in ("origin-observe", "origin-return", "origin-reload"):
        origin = phases.add_parser(name)
        origin.add_argument("--run-id", required=True)
        origin.add_argument("--holder", required=True)
        if name == "origin-observe":
            origin.add_argument("--audio-proof", type=pathlib.Path, required=True)
        else:
            origin.add_argument("--emulator", choices=("winuae", "fsuae"), default="winuae")
            origin.add_argument("--audio-proof", type=pathlib.Path)
        if name == "origin-reload":
            origin.add_argument("--return-receipt", type=pathlib.Path, required=True)
        else:
            origin.add_argument("--manifest", type=pathlib.Path, required=True)
        origin.add_argument("--source-manifest", type=pathlib.Path, required=True)
        origin.add_argument("--controls", type=pathlib.Path, required=True)
        origin.add_argument("--out", type=pathlib.Path, required=True)
        origin.add_argument("--budget", type=float, required=True)
    args = parser.parse_args(argv)
    if args.phase in ("origin-return", "origin-reload"):
        if args.emulator == "winuae" and args.audio_proof is None:
            parser.error("--audio-proof is required with --emulator winuae")
        if args.emulator == "fsuae" and args.audio_proof is not None:
            parser.error("--audio-proof belongs to --emulator winuae; an FS-UAE run proves its "
                         "silence from the emulator's own environment")
    runners = {"origin-observe": run_origin_observe, "origin-return": run_origin_return,
               "origin-reload": run_origin_reload, "bundle-source": run_bundle_source,
               "p2": run_p2, "reload": run_reload}
    labels = {"origin-observe": "Origin observer", "origin-prepare": "Origin observer",
              "origin-return": "Seven-member Return", "origin-reload": "Seven-member reload",
              "bundle-source": "Bundle source"}
    try:
        if args.phase == "origin-prepare":
            manifest = prepare_origin(args.run_id)
            print(json.dumps({"prepared_manifest": str(manifest),
                              "prepared_disk_sha256": ORIGIN_PREPARED_SHA256,
                              "source_g_sha256": ORIGIN_G_SHA256}, sort_keys=True))
            return 0
        with terminating():
            result = runners[args.phase](args)
    except (RouteError, OSError, ValueError, KeyError) as exc:
        print(f"{labels.get(args.phase, 'darknessreturn')}: {exc}", file=sys.stderr)
        return 2
    if args.phase in ("origin-return", "origin-reload"):
        statuses = {key: value["evidence_status"] for key, value in result.items()
                    if key.endswith("comparison") and isinstance(value, dict)}
        print(json.dumps({"success": result["success"],
                          "receipt": str(args.out / f"{args.phase}-receipt.json"),
                          "checks": result["checks"], "comparisons": statuses,
                          "independently_authenticated": False,
                          "preservation_established": False}, indent=2, sort_keys=True))
        return 0
    if args.phase == "origin-observe":
        print(json.dumps({"success": result["success"],
                          "receipt": str(args.out / "origin-observe-receipt.json"),
                          "observation": result["observation"],
                          "route_status": result["route_status"],
                          "independently_authenticated": False,
                          "preservation_established": False}, indent=2, sort_keys=True))
        return 0
    print(json.dumps({"success": True, "receipt": ("bundle-source-receipt.json"
                                                   if args.phase == "bundle-source" else
                                                   str(args.out / f"{args.phase}-receipt.json")),
                      "checks": result["checks"],
                      "item_comparison_status": (result["post_g_comparison"]["evidence_status"]
                                                 if args.phase == "bundle-source" else
                                                 result["item_comparison"]["evidence_status"]),
                      **({"independently_authenticated": False,
                          "preservation_established": False}
                         if args.phase == "bundle-source" else {})},
                      indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
