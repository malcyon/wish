#!/usr/bin/env python3
"""Compare Curse's ECL01 chance gate with an unsuppressed, same-snapshot fight.

This is a no-save harness experiment, not conversion acceptance. An unknown
screen, an unqualified fight or two ordinary moves without a fight proves
nothing about suppression. Only the holder this command claims is stopped.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import stat
import sys
import time
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import amiga, amigaparty, amigatrip, amigavars, gamedisks  # noqa: E402
from goldbox.amiga_adf import AmigaDisk  # noqa: E402
from tools.amiga import (  # noqa: E402
    acceptance,
    amiga68k,
    noencounters,
    route_curse,
    screens,
    winvmguest,
)
from tools.amiga.winuaesession import RouteError, WinGuest, terminating  # noqa: E402
from tools.registry import scratch  # noqa: E402

TITLE = "curse-of-the-azure-bonds"
SOURCE = pathlib.Path.home() / ".cache/wish/acceptance/WISH-303/curse-prep-L1"
GUARDS = SOURCE.parent / "maps2/guards.json"
IDENTITY = SOURCE.parent / "maps2/identity.json"
COMBAT_REFERENCE = (pathlib.Path.home() /
                    ".cache/wish/acceptance/WISH-359/m1/curse-fight-menu.png")
COMBAT_SHA256 = "2748c6b26945f04fe909054136a23cf8ef8a0a482b8baaff495ec2711610f52a"
COMBAT_BOX = (72, 404, 686, 426)
MEDIA = {"save": "faa013855dd0c468e9ac90a132b91b2f50e6ea457ef763caf125ba98e9021684",
         "diskb": "a6f94bb42664ab94b673bf0c7390420d94bec257ae09fea488a53504b6e1fca3"}
ENTRY = "c80bfd1e"
CHANCE = "9afc9873"
ORIGINAL = bytes.fromhex("08006401797f")
PATCHED = bytes.fromhex("09006401797f")
GATE = "*0x5006+0x9952"
SNAPSHOT = "curse_ecl01_off"
TOTAL = 900
CLEANUP = 300
VARS = (0x4C02, 0x4C05, 0x4C06, 0x7ECA, 0x7F79, 0x7F7A)
QUALIFIED = (0x4C02, 0x4C05, 0x4C06)
NAMES = ("MATHEW", "PHILIPPE", "SHARA", "LEDERA", "TRAVIS", "MARK")
EXE_SHA256 = "8d4ceba86e4b7659e5fa678446f9cafdfd5f4aa70c59c68d44862ed12bb83fb8"
ECL_SHA256 = "18a41bbd89cf136b4140c5a215606dab747d744e706b5cf7b9f8de8321e3b450"
ECL_SIZE = 7622
COMPARISON = bytes.fromhex("00010001000100")
HANDLERS = {1: 0x42BB2, 5: 0x432FC, 7: 0x43518}
DIRECT = {"pc": (0x5004, 2), "script_pointer": (0x5006, 4),
          "opcode": (0x58C2, 1), "previous": (0x5CF1, 1),
          "caller": (0x583C, 4), "comparison": (0x5844, 7),
          "stop": (0x3330, 1), "area_change": (0x332F, 1),
          "change_pending": (0x4FFF, 1), "mode": (0x3D56, 1),
          "menu": (0x1C24, 2), "variable_pointer": (0x3DBE, 4),
          "word_pointer": (0x3D00, 4), "cursor_pointer": (0x383C, 4),
          "dialog_pointer": (0x66EA, 4), "dialog_count": (0x39F6, 2),
          "dialog_initialized": (0x39F4, 1)}


def _u(raw: bytes) -> int:
    return int.from_bytes(raw, "big")


def _range(target, address: int, length: int, label: str) -> None:
    regions = getattr(target, "memory", None)
    require(isinstance(regions, tuple) and bool(regions)
            and any(base <= address and address + length <= base + size
                    for base, size in regions), f"{label} is outside measured memory")


def _disjoint(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[1] <= b[0] or b[1] <= a[0]


def pinned_executable() -> dict:
    """Resolve handlers and runtime code anchoring from the registered executable."""
    root = gamedisks.find("amiga")
    require(root is not None, "the registered Amiga disk root is missing")
    path = (root / "Curse_Of_The_Azure_Bonds" /
            "CurseOfTheAzureBonds_A.adf")
    raw = AmigaDisk.open(path).read_file("/Curse")
    require(hashlib.sha256(raw).hexdigest() == EXE_SHA256,
            "the registered Curse executable does not match the full pin")
    exe = amiga68k.Executable.parse(raw)
    data = exe.small_data
    code = exe.hunks[0]
    require(data is not None and code.kind == "CODE" and code.file_offset is not None,
            "the pinned executable has no expected code/data hunks")
    jumps = []
    for offset in (0, 6, 12):
        blob = raw[data.file_offset + offset:data.file_offset + offset + 6]
        require(blob[:2] == b"\x4e\xf9"
                and exe.relocs.get((data.number, offset + 2)) == code.number,
                "the executable's code-base relocation is not pinned")
        jumps.append((offset, _u(blob[2:])))
    handlers = {}
    for kind, file_at in HANDLERS.items():
        table = 0x2FD2 + 4 * (kind - 1)
        require(exe.relocs.get((data.number, table)) == code.number,
                "a dialog handler is not relocated to the code hunk")
        relative = _u(raw[data.file_offset + table:data.file_offset + table + 4])
        require(code.file_offset + relative == file_at,
                "the executable's dialog handler differs")
        handlers[kind] = (relative, raw[file_at:file_at + 4])
    return {"jumps": tuple(jumps), "handlers": handlers,
            "code_size": code.size, "sha256": EXE_SHA256}


def relocated_handlers(target, pinned: dict) -> dict[int, int]:
    """Measure a common runtime code base from three independently relocated jumps."""
    base = target.data_base
    jumps = pinned["jumps"]
    for offset, _ in jumps:
        _range(target, base + offset, 6, "code-base jump")
    live_jumps = [target.read(base + offset, 6) for offset, _ in jumps]
    require(all(blob[:2] == b"\x4e\xf9" and len(blob) == 6 for blob in live_jumps),
            "the live code-base jumps differ")
    bases = {_u(blob[2:]) - relative for blob, (_, relative)
             in zip(live_jumps, jumps)}
    require(len(bases) == 1, "the live jumps disagree on the code base")
    code_base = bases.pop()
    _range(target, code_base, pinned["code_size"], "relocated code hunk")
    handlers = {}
    for kind, (relative, prefix) in pinned["handlers"].items():
        address = code_base + relative
        _range(target, address, len(prefix), "relocated dialog handler")
        require(target.read(address, len(prefix)) == prefix,
                "the live dialog handler differs from the pinned executable")
        handlers[kind] = address
    return handlers


def observe_state(target, pinned: dict) -> dict:
    """Read one bounded, raw diagnostic state without altering the running game."""
    if getattr(target, "data_base", None) is None:
        target.locate()
    elif getattr(target, "anchor_base", None) is not None:
        target.check_base()
    d = target.data_base
    for name, (offset, length) in DIRECT.items():
        _range(target, d + offset, length, name)
    direct = {name: target.read(d + offset, length)
              for name, (offset, length) in DIRECT.items()}
    s, v, w, p = (_u(direct[name]) for name in
                  ("script_pointer", "variable_pointer", "word_pointer",
                   "cursor_pointer"))
    for name, address in (("script", s), ("variables", v),
                          ("word table", w), ("cursor", p)):
        require(address and not address & 1, f"{name} pointer is null or odd")
        _range(target, address, 4, f"{name} pointer")
    count = _u(direct["dialog_count"])
    require(1 <= count <= 24, "dialog item count is not 1..24")
    require(_u(direct["dialog_pointer"]) == d + 0x39F8,
            "dialog items do not use the inline array")
    pointed = {"script": (s + 0x8000, ECL_SIZE),
               "roll_limit": (v + 0xFEF2, 4),
               "word_table": (w + 0x9804, 10),
               "cursor": (p, 68), "dialog": (d + 0x39F8, count * 32)}
    for name, (address, length) in pointed.items():
        require(address >= 0 and (address & 1) == 0,
                f"{name} has an invalid pointer")
        _range(target, address, length, name)
    protected = [(d + offset, d + offset + length)
                 for offset, length in DIRECT.values()]
    protected.extend((address, address + length) for name, (address, length)
                     in pointed.items() if name != "cursor")
    for destination in ((d + 0x348A, d + 0x368E), (p + 4, p + 68)):
        require(all(_disjoint(destination, span) for span in protected),
                "cursor writes alias protected interpreter or pointed data")
    raw = {name: target.read(address, length)
           for name, (address, length) in pointed.items()}
    handlers = relocated_handlers(target, pinned)
    for i in range(count):
        item = raw["dialog"][32 * i:32 * (i + 1)]
        handler = _u(item[:4])
        kinds = [kind for kind, address in handlers.items() if handler == address]
        require(len(kinds) == 1, f"dialog item {i} has an unpinned handler")
        require(item[0x1C] & 0x80, f"dialog item {i} is not drawn")
        require(kinds[0] != 5 or _u(item[4:8]) == 0,
                f"dialog item {i} has an active type-5 callback")
    require(direct["dialog_initialized"] != b"\x00",
            "world dialog is not initialized")
    require(len(raw["script"]) == ECL_SIZE
            and hashlib.sha256(raw["script"]).hexdigest() == ECL_SHA256
            and hashlib.sha256(raw["script"][:20]).hexdigest()[:8] == ENTRY
            and raw["script"][0x1952:0x1958] == ORIGINAL
            and raw["script"][0x1960] == 0,
            "the complete original ECL01 body or EXIT differs")
    result = {"direct": direct, "pointed": raw, "pointers": (s, v, w, p),
              "handlers": handlers, "reading": live(target, reuse_location=True),
              "time": time.time(), "monotonic": time.monotonic()}
    return result


def rejected_candidate(before: dict, captures: list[dict], index: int,
                       world_frames: list[bool]) -> tuple[bool, list[str]]:
    """A sampled persistent EXIT is diagnostic, never a branch or suppression proof."""
    errors = []
    if len(captures) != 4 or len(world_frames) != 2 or not all(world_frames):
        return False, ["world frame or bracket is missing"]
    expected = (4 - index, 14, 3)
    try:
        at_world(before["reading"], (5 - index, 14, 3))
        for capture in captures:
            at_world(capture["reading"], expected)
    except RouteError:
        errors.append("area, mode, destination, or live attribute differs")
    baseline = captures[0]
    for i, capture in enumerate(captures[1:], 1):
        for key, value in baseline["direct"].items():
            if capture["direct"][key] != value:
                errors.append(f"bracket {i} changed {key}")
        for key in ("pointers", "handlers"):
            if capture[key] != baseline[key]:
                errors.append(f"bracket {i} changed {key}")
        for key in ("script", "roll_limit", "word_table", "dialog"):
            if capture["pointed"][key] != baseline["pointed"][key]:
                errors.append(f"bracket {i} changed {key}")
    direct = baseline["direct"]
    expected_bytes = {"pc": b"\x99\x61", "opcode": b"\x00", "previous": b"\x19",
                      "caller": b"\x00" * 4, "comparison": COMPARISON,
                      "stop": b"\x00", "area_change": b"\x00",
                      "change_pending": b"\x00", "mode": b"\x04",
                      "menu": b"\x00\x01"}
    errors.extend(f"the EXIT {key} differs" for key, value in expected_bytes.items()
                  if direct[key] != value)
    if all(before["direct"][key] == expected_bytes[key]
           for key in ("pc", "opcode", "previous", "caller")):
        errors.append("the EXIT signature was present before the move")
    roll, limit = _u(baseline["pointed"]["roll_limit"][:2]), _u(
        baseline["pointed"]["roll_limit"][2:])
    if limit not in (10, 20, 30, 40) or not limit < roll <= 100:
        errors.append("the rejected comparison has no bounded roll and limit")
    return not errors, errors


def _private_observation(folder: pathlib.Path, label: str, state: dict) -> dict:
    """Write raw measured bytes only beneath the owner-private evidence directory."""
    actual = folder.stat()
    require(os.name == "posix" and actual.st_uid == os.getuid()
            and stat.S_IMODE(actual.st_mode) == 0o700,
            "the observation directory is not owner-private")
    payload = {"time": state["time"], "monotonic": state["monotonic"],
               "reading": state["reading"], "pointers": state["pointers"],
               "handlers": state["handlers"],
               "direct": {k: v.hex() for k, v in state["direct"].items()},
               "pointed": {k: v.hex() for k, v in state["pointed"].items()}}
    blob = (json.dumps(payload, sort_keys=True) + "\n").encode()
    path = folder / f"{label}.json"
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
        out.write(blob)
    require(stat.S_IMODE(path.stat().st_mode) == 0o600,
            "the raw observation is not owner-private")
    return {"order": label, "time": state["time"],
            "sha256": hashlib.sha256(blob).hexdigest(),
            "script_sha256": hashlib.sha256(state["pointed"]["script"]).hexdigest()}


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RouteError(reason)


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: pathlib.Path, report: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def receipt_of(value: Any) -> Any:
    """Keep a pipe receipt in JSON without discarding its diagnostic fields."""
    return value.as_dict() if hasattr(value, "as_dict") else value


def complete_claims(status: str) -> dict[int, tuple[str | None, str]]:
    """Accept only a complete four-lane guest reply before inferring absent ownership."""
    lines = [line.strip() for line in status.splitlines()]
    require(lines.count("lanes = 4") == 1
            and not any(re.match(r"^lanes\s*=", line) and line != "lanes = 4"
                        for line in lines), "guest status has no unique four-lane count")
    claims: dict[int, tuple[str | None, str]] = {}
    for line in lines:
        if not line.startswith("claim"):
            continue
        match = re.fullmatch(r"claim(?:\s+([1-4]))?\s*=\s*([A-Za-z0-9._-]+)"
                             r"(?:\s+since\s+(.+))?", line)
        require(match is not None, f"malformed guest claim: {line}")
        lane = int(match[1] or 1)
        require(lane not in claims, f"duplicate guest claim for lane {lane}")
        holder, since = match[2], (match[3] or "").strip()
        require((holder == "none" and not since) or (holder != "none" and bool(since)),
                f"invalid guest claim for lane {lane}")
        claims[lane] = (None if holder == "none" else holder, since)
    require(set(claims) == {1, 2, 3, 4}, "guest status has incomplete claims")
    parsed = winvmguest.parse_status(status)
    require(parsed.driver and parsed.lanes == claims, "parsed guest claims differ")
    return claims


@contextlib.contextmanager
def bounded_until(deadline: float):
    """Interrupt a cleanup call without granting time beyond the original run deadline."""
    remaining = deadline - time.monotonic()
    require(remaining > 0, "cleanup deadline reached")

    def expired(signum, frame):
        raise RouteError("cleanup call exceeded its deadline")

    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
    require(time.monotonic() <= deadline, "cleanup call exceeded its deadline")


class CleanupGuest:
    """Give the shared halt sequence one deadline and preserve release time."""

    def __init__(self, guest, deadline):
        self.guest, self.deadline = guest, deadline
        self.release_receipt = None

    def __getattr__(self, name):
        return getattr(self.guest, name)

    def _time(self, cap, *, release=False):
        remaining = self.deadline - time.monotonic() - (0 if release else 45)
        require(remaining > 0, "cleanup reserve reached before release" if not release
                else "total deadline reached before release")
        return min(cap, remaining)

    def stop(self, holder, timeout):
        return self.guest.stop(holder, timeout=self._time(timeout))

    def get(self, remote, local, timeout):
        return self.guest.get(remote, local, timeout=self._time(timeout))

    def release(self, holder, timeout):
        self.release_receipt = self.guest.release(
            holder, timeout=self._time(timeout, release=True))
        return self.release_receipt


def private_media(manifest: dict, out: pathlib.Path) -> dict:
    """Copy only approved prepared media; leave all source paths and bytes alone."""
    disks = {}
    for key, digest in MEDIA.items():
        destination = out / f"{key}.adf"
        shutil.copyfile(SOURCE / f"{key}.adf", destination)
        require(sha256(destination) == digest, f"the private {key} copy differs")
        disks[key] = {**manifest["disks"][key], "path": str(destination)}
    return {**manifest, "disks": disks}


def preflight(args: argparse.Namespace, state: noencounters.WinuaeState) -> dict:
    """Pin the source, holder, guards and previous journal before claiming a lane."""
    require(args.manifest.resolve() == (SOURCE / "prepare.json").resolve(),
            "only the prepared Curse source manifest is approved")
    require(args.guards.resolve() == GUARDS.resolve()
            and args.identity.resolve() == IDENTITY.resolve(),
            "the screen guards must be the measured Curse maps2 pair")
    root = scratch.cache_dir("acceptance", "WISH-365").resolve()
    require(args.out.resolve().is_relative_to(root) and args.out.resolve() != root
            and not args.out.exists(), "the proof needs a fresh WISH-365 cache folder")
    require(args.wait_lane == 0 and args.holder == "wish365-ecl01",
            "this one-boot proof requires its new holder and no lane wait")
    require(state.load().get("on") is False and state.load().get("rows") == [],
            "this holder has outstanding encounter changes; do not boot")
    require(sha256(COMBAT_REFERENCE) == COMBAT_SHA256,
            "the measured Curse combat reference is absent or changed")
    guards = screens.PixelGuards(args.guards)
    identity = screens.PixelGuards(args.identity)
    require({"title", "front_end", "intro", "load_picker", "loaded_menu", "sheet", "world"}
            <= guards.rules.keys() and {"loaded_menu", "sheet"} <= identity.rules.keys(),
            "the measured load/sheet/world guards are incomplete")
    manifest = json.loads(args.manifest.read_text())
    require(manifest.get("title") == "curse" and manifest.get("loaded_letter") == "B"
            and manifest.get("state_a") == {"area": 1, "x": 4, "y": 14, "facing": 1}
            and tuple(manifest.get("names_a", ())) == NAMES,
            "the source does not hold the prepared Tilverton B party")
    require(set(manifest.get("disks", {})) == set(MEDIA)
            and all(manifest["disks"][key]["sha256"] == want
                    and pathlib.Path(manifest["disks"][key]["path"]).resolve()
                    == (SOURCE / f"{key}.adf").resolve()
                    and sha256(SOURCE / f"{key}.adf") == want
                    for key, want in MEDIA.items()), "prepared media pins or source bytes differ")
    for entry in (manifest["registered"]["specimen"], manifest["substitute"]):
        require(sha256(pathlib.Path(entry["path"])) == entry["sha256"],
                "registered or substitute provenance changed")
    require(WinGuest.silence(args.audio_proof), "fresh Windows playback mute proof is required")
    return manifest


def gate_row() -> noencounters.Row:
    rows = [r for r in noencounters.rows_for(TITLE) if r.spec == GATE]
    require(len(rows) == 1 and rows[0].kind == noencounters.GATE
            and rows[0].area == ENTRY and rows[0].digest == CHANCE
            and rows[0].changes == ((0, noencounters.SAVE),),
            "the committed ECL01 row does not match this experiment")
    return rows[0]


def script(target) -> dict:
    """Read the live entry, full statement and resolved pointer, without writes."""
    target.locate()
    pointer = int.from_bytes(target.read(target.data_base + 0x5006, 4), "big")
    require(pointer != 0 and noencounters.inside_memory(pointer + 0x8000, 20)
            and noencounters.inside_memory(pointer + 0x9952, 6),
            "the Curse area-script pointer is unresolved or outside memory")
    entry = target.read(pointer + 0x8000, 20)
    chance = target.read(pointer + 0x9952, 6)
    return {"pointer": pointer, "entry": noencounters.digest(entry),
            "address": pointer + 0x9952, "statement": chance.hex()}


def pinned(target, expected: bytes) -> dict:
    result = script(target)
    require(result["entry"] == ENTRY and result["statement"] == expected.hex(),
            f"ECL01 pin or $9952 bytes differ: {result}")
    return result


def live(target, *, names: bool = False, reuse_location: bool = False) -> dict:
    """Keep note-backed member-table readings distinct from qualified flags."""
    if not reuse_location or getattr(target, "data_base", None) is None:
        target.locate()
    elif getattr(target, "anchor_base", None) is not None:
        target.check_base()
    row = amigatrip.row_for(TITLE)
    fields = {f"{v:04X}": reading.as_log()
              for v in VARS for reading in amigavars.read_variables(target, TITLE, (v,))}
    for v in QUALIFIED:
        reading = fields[f"{v:04X}"]
        require(reading["value"] is not None and reading["note"] is None,
                f"${v:04X} cannot be checked as a live flag")
    got = {"area": amigatrip.area_id(target, row),
           "square": amigatrip.square(target, row),
           "mode": target.read(target.data_base + amigaparty.ROWS[TITLE].mode, 1)[0],
           "attribute": target.read(target.data_base + amiga.MACHINES[TITLE].notes[
               "square_attribute"], 1)[0], "variables": fields}
    if names:
        party = amigaparty.read_party(target)
        got["names"] = None if party is None else [member.name for member in party]
    fix = target.fix()
    got["fix"] = None if fix is None else {"x": fix.x, "y": fix.y, "facing": fix.facing,
                                           "world_map": fix.world_map}
    return got


def qualified(got: dict) -> dict:
    return {f"{v:04X}": got["variables"][f"{v:04X}"]["value"] for v in QUALIFIED}


def at_world(got: dict, square: tuple[int, int, int]) -> None:
    require(got["area"] == 1 and got["square"] == square and got["mode"] == 4
            and got["attribute"] == 0 and got["fix"] == {"x": square[0], "y": square[1],
                                                         "facing": square[2], "world_map": False},
            f"not the ordinary Tilverton square {square}: {got}")


def switched(reply: dict, target, *, first: bool = False) -> dict:
    """A blocked ECL01 row cannot be mistaken for another row's write."""
    require("error" not in reply and "stopped" not in reply,
            f"the switch command failed: {reply}")
    rows = list(reply.get("rows", []))
    rows += [r for entry in reply.get("applied", []) for r in entry.get("rows", [])]
    ours = [r for r in rows if r.get("row") == GATE]
    require(not any("error" in r or "stopped" in r for r in ours),
            f"the ECL01 row was stopped: {ours}")
    require(not any("new" in r for r in rows if r.get("row") != GATE),
            f"another encounter row changed this script: {reply}")
    now = pinned(target, PATCHED)
    require(len(state_rows := [r for r in rows if r.get("row") == GATE and "new" in r]) <= 1,
            f"duplicate ECL01 writes: {state_rows}")
    if first:
        require(len(state_rows) == 1 and state_rows[0].get("address") == now["address"]
                and state_rows[0].get("new") == "09",
                f"the ECL01 row did not write its one opcode: {reply}")
    return now


def off_checked(switch, state, target) -> dict:
    reply = switch.off()
    require("error" not in reply and "stopped" not in reply
            and not state.load()["on"] and not state.load()["rows"],
            f"encounter off did not clear its journal: {reply}")
    pinned(target, ORIGINAL)
    return reply


class Screens:
    """Grab the emulator's frame; only a matched guard permits the next key."""

    def __init__(self, guest, holder, folder, guards, identity, route_end, report, receipt,
                 *, private=False):
        self.guest, self.holder, self.folder = guest, holder, folder
        self.guards, self.identity, self.route_end = guards, identity, route_end
        self.report, self.receipt = report, receipt
        self.events = report.setdefault("events", [])
        self.count = 0
        self.private = private
        if private:
            folder.mkdir(mode=0o700)
            require(os.name == "posix" and folder.stat().st_uid == os.getuid()
                    and stat.S_IMODE(folder.stat().st_mode) == 0o700,
                    "the private screenshot directory has the wrong owner or mode")
        else:
            folder.mkdir()

    def left(self, cap: float) -> float:
        left = min(cap, self.route_end - time.monotonic())
        require(left > 0, "route deadline reached; reserve cleanup time")
        return left

    def grab(self, label: str) -> pathlib.Path | None:
        self.count += 1
        raw = self.folder / f"{self.count:03d}-{label}.raw.png"
        crop = self.folder / f"{self.count:03d}-{label}.png"
        good = self.guest.grab(label, raw, crop, self.left(20))
        if self.private:
            for path in (raw, crop) if good else (raw,):
                path.chmod(0o600)
                require(stat.S_IMODE(path.stat().st_mode) == 0o600,
                        "the screenshot is not owner-private")
        event = {"label": label, "raw": str(raw),
                 "crop": str(crop) if good else None, "sha256": sha256(raw)}
        if self.private:
            event.update(time=time.time(), order=self.count)
        self.events.append(event)
        self.receipt()
        return crop if good else None

    def see(self, state: str, seconds: float, *, opening: bool = False,
            from_state: str | None = None) -> pathlib.Path:
        require(state in self.guards, f"missing {state} guard")
        end, count = time.monotonic() + self.left(seconds), {"front_end": 0, "intro": 0}
        while time.monotonic() < end:
            crop = self.grab(state)
            if crop is not None:
                if self.guards(state, crop):
                    if state in self.identity:
                        require(self.identity(state, crop), f"wrong party on {state}: {crop}")
                    return crop
                if opening:
                    for other, cap in (("front_end", 4), ("intro", 1)):
                        if self.guards(other, crop):
                            require(count[other] < cap, f"{other} exceeded its ESC cap")
                            count[other] += 1
                            self.guest.press(self.holder, "ESC", timeout=self.left(20))
                            self.events.append({"interstitial": other, "key": "ESC"})
                            self.receipt()
                            break
                    else:
                        require(not any(self.guards(s, crop) for s in self.guards.rules
                                        if s != state), f"expected {state}, got another screen: {crop}")
                elif any(self.guards(s, crop) for s in self.guards.rules
                         if s not in (state, from_state)):
                    raise RouteError(f"expected {state}, saw another measured screen: {crop}")
            time.sleep(min(0.5, max(0.0, end - time.monotonic())))
        raise RouteError(f"{state} never matched before its guarded wait expired")

    def press(self, key: str) -> None:
        require(key in {"L", "B", "V", "E", "NP2", "NP8"}, f"unreviewed key {key}")
        self.guest.press(self.holder, key, timeout=self.left(20))
        self.events.append({"key": key})
        self.receipt()

    def world_at(self, target, square: tuple[int, int, int], seconds: float,
                 *, from_state: str | None = None) -> dict:
        """Do not mistake a frame from before a turn or restore for the result."""
        end = time.monotonic() + self.left(seconds)
        while time.monotonic() < end:
            crop = self.grab("world")
            if crop is not None and self.guards("world", crop):
                got = live(target)
                if got["area"] == 1 and got["square"] == square and got["mode"] == 4:
                    at_world(got, square)
                    return got
                require(got["area"] in (None, 1) and got["mode"] in (None, 4),
                        f"world guard matched another area or mode: {got}")
            elif crop is not None and any(self.guards(s, crop) for s in self.guards.rules
                                           if s not in ("world", from_state)):
                raise RouteError(f"expected Tilverton {square}, another screen: {crop}")
            time.sleep(min(0.5, max(0.0, end - time.monotonic())))
        raise RouteError(f"world fix {square} never matched; last raw capture in {self.folder}")


def classify(world: bool, combat: bool, mode: int | None,
              prior: dict, index: int) -> str:
    """A matched menu on an ordinary step identifies a screen, not its branch."""
    require(not (world and combat), "world and combat guards matched the same frame")
    if world and mode == 4:
        return "world"
    if (combat and not world and mode == amigaparty.ROWS[TITLE].combat_value
            and prior["area"] == 1 and prior["mode"] == 4
            and prior["attribute"] == 0
            and prior["square"] == ((4, 14, 3) if index == 1 else (3, 14, 3))
            and prior["fix"] == {"x": 5 - index, "y": 14, "facing": 3,
                                 "world_map": False}):
        return "combat_observation"
    return "unknown"


def observe_step(shots: Screens, target, index: int, before: dict,
                 combat_guard, *, replay: bool, observe_rejected: bool = False,
                 pinned_exe: dict | None = None, private: pathlib.Path | None = None
                 ) -> tuple[str, dict | None]:
    """Keep an unknown screen as evidence; do not interpret a world miss as combat."""
    if observe_rejected:
        require(not replay and pinned_exe is not None and private is not None,
                "the rejected observation is not a replay")
        end = time.monotonic() + shots.left(35)
        expected = (4 - index, 14, 3)
        while time.monotonic() < end:
            crop = shots.grab(f"observe-{index}-settle")
            if crop is None:
                continue
            if not shots.guards("world", crop):
                return "unknown", {"outcome": "unknown", "reason": "not the world screen",
                                   "crop": str(crop)}
            reading = live(target, reuse_location=True)
            if reading["area"] != 1 or reading["mode"] != 4:
                return "unknown", {"outcome": "unknown", "reason": "not ordinary area 1",
                                   "crop": str(crop)}
            if reading["square"] == before["square"]:
                time.sleep(min(0.5, max(0, end - time.monotonic())))
                continue
            at_world(reading, expected)
            break
        else:
            return "unknown", {"outcome": "unknown", "reason": "no indexed destination"}

        captured, frames, ordering = [], [], []
        stream = shots.report["candidate_observation"].setdefault("read_order", [])

        def measured(entry: dict) -> None:
            ordering.append(entry)
            stream.append({"move": index, **entry})
            shots.receipt()

        for bracket in range(2):
            first = observe_state(target, pinned_exe)
            measured(_private_observation(private, f"move-{index}-b{bracket}-pre", first))
            crop = shots.grab(f"observe-{index}-b{bracket}")
            frames.append(crop is not None and shots.guards("world", crop))
            measured({"order": f"move-{index}-b{bracket}-screen", "time": time.time(),
                      "sha256": sha256(crop) if crop is not None else None,
                      "raw_sha256": shots.events[-1]["sha256"]})
            last = observe_state(target, pinned_exe)
            measured(_private_observation(private, f"move-{index}-b{bracket}-post", last))
            captured.extend((first, last))
            if bracket == 0:
                pause = min(1.0, shots.left(2))
                interval = {"order": "NO-COMMAND interval", "started": time.time(),
                            "seconds": pause}
                measured(interval)
                time.sleep(pause)
                interval["ended"] = time.time()
                stream[-1]["ended"] = interval["ended"]
                shots.receipt()
        valid, reasons = rejected_candidate(before, captured, index, frames)
        unsafe = any(reason.startswith(("world frame", "area, mode", "bracket "))
                     or reason == "the EXIT signature was present before the move"
                     for reason in reasons)
        outcome = "candidate" if valid else ("unknown" if unsafe else "world")
        return outcome, {"outcome": outcome, "reading": captured[-1]["reading"],
                         "valid": valid, "mismatches": reasons, "order": ordering,
                         "crop": str(crop) if crop is not None else None}
    end = time.monotonic() + shots.left(35)
    last: dict | None = None
    while time.monotonic() < end:
        crop = shots.grab(f"{'replay' if replay else 'control'}-{index}")
        if crop is None:
            continue
        reading = live(target)
        world = shots.guards("world", crop)
        combat = combat_guard(crop)
        outcome = classify(world, combat, reading["mode"], before, index)
        last = {"outcome": outcome, "reading": reading, "crop": str(crop)}
        if outcome == "combat_observation":
            return outcome, last
        if outcome == "world":
            expected = (4 - index, 14, 3)
            if reading["area"] == 1 and reading["square"] == before["square"]:
                time.sleep(min(0.5, max(0.0, end - time.monotonic())))
                continue
            at_world(reading, expected)
            return outcome, last
        if reading["mode"] == 5 or any(
                shots.guards(s, crop) for s in shots.guards.rules if s != "world"):
            return "unknown", last
        time.sleep(min(0.5, max(0.0, end - time.monotonic())))
    return "unknown", last


def proof(shots: Screens, target, switch, state, guest, holder, combat_guard,
          report: dict, *, observe_rejected: bool = False,
          pinned_exe: dict | None = None, private: pathlib.Path | None = None) -> None:
    """One off snapshot, up to two control moves, then only a matched replay."""
    report["candidate"] = False
    shots.see("title", 250, opening=True)
    previous = "title"
    for key, screen in (("L", "load_picker"), ("B", "loaded_menu"), ("V", "sheet"),
                        ("E", "loaded_menu")):
        shots.press(key)
        shots.see(screen, 40, from_state=previous)
        previous = screen
    shots.press("B")
    shots.world_at(target, (4, 14, 1), 50, from_state="loaded_menu")
    start = live(target, names=True)
    at_world(start, (4, 14, 1))
    require(tuple(start["names"] or ()) == NAMES, "slot B is not the MATHEW party")
    original = pinned(target, ORIGINAL)
    report["start"] = {"reading": start, "script": original}
    if observe_rejected:
        require(pinned_exe is not None and private is not None and switch is None,
                "rejected observation cannot activate the switch or replay")
        require(not state.load()["on"] and state.load()["rows"] == [],
                "rejected observation needs an empty, switched-off journal")
        report["candidate_observation"] = {
            "status": "incomplete", "moves": [], "read_order": [],
            "allocation_qualified": False,
            "allocation_limit": "Physical memory and selected span disjointness only; "
                                "allocation ownership and sizes are unverified"}
        report["snapshot_attempted"] = {"holder": holder, "name": SNAPSHOT}
        shots.receipt()
        report["snapshot"] = receipt_of(guest.snapshot(SNAPSHOT, holder))
        report["snapshot_taken"] = True
        shots.receipt()
        shots.press("NP2")
        prior = shots.world_at(target, (4, 14, 3), 35)
        report["observation_turn"] = prior
        shots.receipt()
        for index in (1, 2):
            at_world(prior, (5 - index, 14, 3))
            require(not state.load()["on"] and state.load()["rows"] == [],
                    "the observation journal was changed")
            pre = observe_state(target, pinned_exe)
            at_world(pre["reading"], (5 - index, 14, 3))
            initial = _private_observation(private, f"move-{index}-before", pre)
            report["candidate_observation"]["read_order"].append({"move": index, **initial})
            shots.receipt()
            shots.press("NP8")
            outcome, seen = observe_step(shots, target, index, prior, combat_guard,
                                         replay=False, observe_rejected=True,
                                         pinned_exe=pinned_exe, private=private)
            candidate = report["candidate_observation"]
            candidate["moves"].append({"index": index, "before": initial,
                                       **(seen or {"outcome": outcome})})
            shots.receipt()
            if outcome == "candidate":
                candidate["status"] = "sampled rejected-chance candidate"
                return
            if outcome != "world":
                candidate["status"] = "incomplete"
                return
            prior = seen["reading"]
        report["candidate_observation"]["status"] = "no candidate in two moves"
        return
    world_crop = pathlib.Path(shots.events[-1]["crop"])
    screens.checked_rule(shots.folder.parent / "combat-reference.png", COMBAT_BOX,
                         "combat", (world_crop,))
    report["snapshot_attempted"] = {"holder": holder, "name": SNAPSHOT}
    shots.receipt()
    report["snapshot"] = receipt_of(guest.snapshot(SNAPSHOT, holder))
    report["snapshot_taken"] = True
    shots.receipt()
    shots.press("NP2")
    prior = shots.world_at(target, (4, 14, 3), 35)
    report["control_turn"] = prior
    shots.receipt()
    fight_index = None
    for index in (1, 2):
        at_world(prior, (5 - index, 14, 3))
        check = pinned(target, ORIGINAL)
        report.setdefault("control_before", []).append({"move": index, "reading": prior,
                                                        "script": check})
        shots.receipt()
        shots.press("NP8")
        outcome, seen = observe_step(shots, target, index, prior, combat_guard, replay=False)
        report.setdefault("control", []).append({"move": index, **(seen or {"outcome": outcome})})
        shots.receipt()
        if outcome == "unknown":
            report["verdict"] = "inconclusive: unclassified control screen"
            return
        if outcome == "combat_observation":
            fight_index = index
            break
        prior = seen["reading"]
    if fight_index is None:
        report["verdict"] = "inconclusive: no control fight in two moves"
        return
    require(not state.load()["on"] and not state.load()["rows"],
            "the control unexpectedly changed encounter state")
    pinned(target, ORIGINAL)
    report["control_off"] = off_checked(switch, state, target)
    shots.receipt()
    report["restore_control"] = receipt_of(guest.restore(SNAPSHOT, holder))
    shots.world_at(target, (4, 14, 1), 35)
    again = live(target, names=True)
    at_world(again, (4, 14, 1))
    require(tuple(again["names"] or ()) == NAMES and qualified(again) == qualified(start)
            and pinned(target, ORIGINAL) == original,
            "snapshot did not restore the party, qualified flags or ECL01")
    report["restored_start"] = again
    shots.receipt()
    response = switch.on()
    report["switch_on"] = response
    shots.receipt()
    switched(response, target, first=True)
    report["journal_on"] = state.load()
    shots.receipt()
    try:
        for index, key in enumerate(("NP2", *("NP8",) * fight_index)):
            # The switch re-applies after a script reload. The press callback checks
            # the exact ECL01 opcode at the instant each key leaves the driver.
            result = switch.keys([key])
            report.setdefault("switch_keys", []).append(result)
            shots.receipt()
            require(result.get("pressed") == [key], f"the guarded {key} was not pressed: {result}")
            switched(result, target)
            if index == 0:
                prior = shots.world_at(target, (4, 14, 3), 35)
                report["replay_turn"] = prior
                shots.receipt()
                continue
            outcome, seen = observe_step(shots, target, index, prior, combat_guard, replay=True)
            report.setdefault("replay", []).append({"move": index, **(seen or {"outcome": outcome})})
            shots.receipt()
            if outcome != "world":
                report["verdict"] = f"inconclusive: replay move {index} was {outcome}"
                return
            prior = seen["reading"]
        report["diagnostic_pair"] = True
    finally:
        report["switch_off"] = off_checked(switch, state, target)
        report["journal_off"] = state.load()
        shots.receipt()


def run(args: argparse.Namespace, *, guest=None, target=None, switch_factory=None,
          guards=None, identity=None, combat_guard=None) -> dict:
    """Prepare private images, claim one lane, compare, and always clean up ours."""
    start_time = time.monotonic()
    route_end, total_end = start_time + TOTAL - CLEANUP, start_time + TOTAL
    state = noencounters.WinuaeState(noencounters.winuae_state_path(args.holder))
    manifest = preflight(args, state)
    gate_row()
    observation = getattr(args, "observe_rejected", False)
    pinned_exe = pinned_executable() if observation else None
    require(not observation or os.name == "posix",
            "private rejected observations need POSIX owner and mode checks")
    require(route_end - time.monotonic() > 120, "too little route time remains to boot")
    private = None
    if observation:
        args.out.mkdir(parents=True, mode=0o700)
        private = args.out / "observations"
        require(args.out.stat().st_uid == os.getuid()
                and stat.S_IMODE(args.out.stat().st_mode) == 0o700,
                "the rejected-observation folder is not owner-private")
        private.mkdir(mode=0o700)
        require(private.stat().st_uid == os.getuid()
                and stat.S_IMODE(private.stat().st_mode) == 0o700,
                "the raw evidence folder is not owner-private")
    else:
        args.out.mkdir(parents=True)
    local = args.out / "prepare.json"
    prepared = private_media(manifest, args.out)
    record(local, prepared)
    if observation:
        for path in (local, *(args.out / f"{key}.adf" for key in MEDIA)):
            path.chmod(0o600)
    report: dict[str, Any] = {"verdict": "inconclusive", "candidate": False,
                              "branch_witness_verified": False,
                              "branch_witness_reason": "no independent live ECL01 branch witness",
                              "holder": args.holder, "input": str(args.manifest),
                              "media": MEDIA, "cleanup": [],
                              "journal_path": str(state.path),
                              "journal_initial": state.load()}
    screens.canonical_file(COMBAT_REFERENCE, args.out / "combat-reference.png")
    combat_reference = args.out / "combat-reference.png"
    if observation:
        combat_reference.chmod(0o600)
    report["combat_reference"] = {"original": str(COMBAT_REFERENCE),
                                  "original_sha256": COMBAT_SHA256,
                                  "canonical": str(combat_reference),
                                  "canonical_sha256": sha256(combat_reference)}
    guest = guest or WinGuest()
    guards = guards or screens.PixelGuards(args.guards)
    identity = identity or screens.PixelGuards(args.identity)
    booted = False
    switch = None
    shots = None
    old_alarm = signal.getsignal(signal.SIGALRM)
    alarm_set = False
    command = [str(pathlib.Path(__file__)), "--manifest", str(args.manifest),
                "--holder", args.holder, "--out", str(args.out)]
    if observation:
        command.append("--observe-rejected")
    def receipt():
        record(args.out / "summary.json", report)
        if observation:
            (args.out / "summary.json").chmod(0o600)

    receipt()
    try:
        require(route_end - time.monotonic() > 120, "too little route time remains to boot")
        def route_expired(signum, frame):
            raise RouteError("the 600-second route deadline expired; begin cleanup")

        signal.signal(signal.SIGALRM, route_expired)
        alarm_set = True
        signal.setitimer(signal.ITIMER_REAL, route_end - time.monotonic())
        report["boot"] = acceptance.boot_lane(
            local, prepared, route_curse.title_for_manifest(prepared), guest=guest,
            holder=args.holder, audio_proof=args.audio_proof, wait_lane=args.wait_lane,
            timeout=min(120, route_end - time.monotonic()), command=command)
        booted = True
        receipt()
        target = target or amiga.AmigaTarget(amiga.WinuaePipe(holder=args.holder),
                                            amiga.MACHINES[TITLE])
        if observation:
            shots = Screens(guest, args.holder, args.out / "shots", guards, identity,
                            route_end, report, receipt, private=True)
        else:
            shots = Screens(guest, args.holder, args.out / "shots", guards, identity,
                            route_end, report, receipt)
        # The reference is an observed combat menu, not an invented pixel hash.
        rule = screens.guard_rule(combat_reference, COMBAT_BOX, "combat")
        report["combat_reference"]["box"] = rule
        combat_guard = combat_guard or (lambda crop: screens.box_digests(
            crop, (COMBAT_BOX,), "combat")[COMBAT_BOX] == rule["sha256"])
        switch_factory = switch_factory or (lambda press: noencounters.WinuaeEncounters(
            TITLE, target, state=state,
            lane_check=lambda: guest.lane(args.holder, timeout=shots.left(20)),
            press=press))

        def press_when_patched(key):
            index = len(report.get("switch_keys", ()))
            require(index <= 2 and key == ("NP2" if index == 0 else "NP8"),
                    f"unreviewed switched key {index}: {key}")
            expected = ((4, 14, 1), (4, 14, 3), (3, 14, 3))[index]
            reading = shots.world_at(target, expected, 15)
            require(state.load()["on"] and len(state.load()["rows"]) == 1
                    and state.load()["rows"][0]["spec"] == GATE
                    and state.load()["rows"][0]["original"] == "08"
                    and state.load()["rows"][0]["changed"] == "09",
                    "the switch journal does not hold only the ECL01 opcode")
            report.setdefault("replay_before", []).append({"key": key, "reading": reading,
                                                           "script": pinned(target, PATCHED)})
            receipt()
            shots.press(key)

        if observation:
            proof(shots, target, None, state, guest, args.holder, combat_guard,
                  report, observe_rejected=True, pinned_exe=pinned_exe, private=private)
        else:
            switch = switch_factory(press_when_patched)
            proof(shots, target, switch, state, guest, args.holder, combat_guard, report)
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        receipt()
    finally:
        if alarm_set:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_alarm)
        if shots is not None:
            report["screens"] = shots.events
        if booted:
            off_ok = False
            off_deadline = min(time.monotonic() + 90, total_end - 90)
            try:
                with bounded_until(off_deadline):
                    if switch is not None:
                        report["cleanup"].append({"off": off_checked(switch, state, target)})
                    else:
                        require(not state.load()["on"] and not state.load()["rows"],
                                "switch state is pending without its driver")
                        pinned(target, ORIGINAL)
                        report["cleanup"].append({"off": "already original"})
                off_ok = True
            except BaseException as exc:
                report["cleanup"].append({"off_error": f"{type(exc).__name__}: {exc}"})
            if report.get("snapshot_attempted") and off_ok:
                snapshot_deadline = min(time.monotonic() + 120, total_end - 90)
                restored = False
                if report.get("snapshot_taken"):
                    try:
                        with bounded_until(snapshot_deadline):
                            report["cleanup"].append({"restore": receipt_of(
                                guest.restore(SNAPSHOT, args.holder))})
                            pinned(target, ORIGINAL)
                            require(not state.load()["on"] and not state.load()["rows"],
                                    "the journal changed after restore")
                            report["cleanup"].append({"readback": "original and empty journal"})
                            restored = True
                    except BaseException as exc:
                        report["cleanup"].append({"snapshot_error":
                                                  f"{type(exc).__name__}: {exc}"})
                else:
                    report["cleanup"].append({"snapshot_error":
                                              "snapshot creation has no verified receipt"})
                if restored or not report.get("snapshot_taken"):
                    try:
                        with bounded_until(snapshot_deadline):
                            report["cleanup"].append({"discard": receipt_of(
                                guest.discard(SNAPSHOT, args.holder))})
                    except BaseException as exc:
                        report["cleanup"].append({"snapshot_error":
                                                  f"{type(exc).__name__}: {exc}"})
                if report.get("snapshot_taken") and not restored:
                    report["snapshot_unresolved"] = {
                        "holder": args.holder, "name": SNAPSHOT,
                        "exists": None, "discard_attempted": False}
            if report.get("snapshot_attempted") and not off_ok:
                report["cleanup"].append({"snapshot_skipped": "off was not verified"})
            remaining = total_end - time.monotonic()
            fetch = remaining >= 150
            if not fetch:
                report["cleanup"].append({"fetch_skipped": "less than 150 seconds remain"})
            cleanup_guest = CleanupGuest(guest, total_end)
            try:
                report["halt"] = acceptance.halt_lane(
                    cleanup_guest, args.holder,
                    timeout=min(30, max(0, remaining)),
                    manifest_path=local if fetch else None, command=command)
                if fetch:
                    for key, digest in MEDIA.items():
                        require(report["halt"]["fetched"][key]["sha256"] == digest,
                                f"the guest changed its private {key} disk")
            except BaseException as exc:
                report["cleanup"].append({"halt_error": f"{type(exc).__name__}: {exc}"})
            if cleanup_guest.release_receipt is not None:
                report["release_receipt"] = receipt_of(cleanup_guest.release_receipt)
            if "halt" not in report or "release" not in report["halt"]:
                if cleanup_guest.release_receipt is not None:
                    report["holder_unresolved"] = False
                else:
                    try:
                        with bounded_until(total_end):
                            status = guest.status(timeout=total_end - time.monotonic())
                        report["holder_status"] = status
                        claims = complete_claims(status)
                        report["holder_unresolved"] = any(
                            holder == args.holder for holder, _ in claims.values())
                    except BaseException as exc:
                        report["holder_unresolved"] = True
                        report["cleanup"].append({"status_error": f"{type(exc).__name__}: {exc}"})
        try:
            require(all(sha256(SOURCE / f"{key}.adf") == digest
                        and sha256(args.out / f"{key}.adf") == digest
                        for key, digest in MEDIA.items()), "source or private disk changed")
            for entry in (manifest["registered"]["specimen"], manifest["substitute"]):
                require(sha256(pathlib.Path(entry["path"])) == entry["sha256"],
                        "original provenance changed")
            report["source_hashes"] = "unchanged"
        except BaseException as exc:
            report["cleanup"].append({"media_error": f"{type(exc).__name__}: {exc}"})
        clean_pair = not report.get("error") and report.get("halt") \
                and "release" in report["halt"] and fetch \
                and off_ok and report.get("snapshot_taken") \
                and any("readback" in item for item in report["cleanup"]) \
                and any("discard" in item for item in report["cleanup"]) \
                and report.get("source_hashes") == "unchanged" \
                and not any(any(k.endswith("_error") for k in item)
                            for item in report["cleanup"])
        if clean_pair and report.get("candidate") and report["branch_witness_verified"]:
            report["verdict"] = "paired suppression and restoration observed"
        elif report.get("candidate") or report.get("diagnostic_pair"):
            report["verdict"] = ("inconclusive: diagnostic pair lacks verified branch witness"
                                 if clean_pair else "inconclusive: cleanup or media check failed")
        try:
            report["journal_final"] = state.load()
            require(report["journal_final"]["on"] is False
                    and report["journal_final"]["rows"] == [],
                    "the encounter journal still records changed bytes")
        except BaseException as exc:
            report["cleanup"].append({"journal_error": f"{type(exc).__name__}: {exc}"})
            report["verdict"] = "inconclusive: final encounter journal is not clear"
        report["elapsed_seconds"] = time.monotonic() - start_time
        if report["elapsed_seconds"] > TOTAL:
            report["cleanup"].append({"deadline_error": "total 900-second deadline passed"})
            report["verdict"] = "inconclusive: total deadline passed"
        record(args.out / "summary.json", report)
        if observation:
            (args.out / "summary.json").chmod(0o600)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--guards", type=pathlib.Path, required=True)
    parser.add_argument("--identity", type=pathlib.Path, required=True)
    parser.add_argument("--audio-proof", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--holder", required=True)
    parser.add_argument("--wait-lane", type=float, default=0)
    parser.add_argument("--observe-rejected", action="store_true")
    args = parser.parse_args(argv)
    with terminating():
        result = run(args)
    fields = ("verdict", "error", "cleanup", "elapsed_seconds", "diagnostic_pair",
              "branch_witness_verified", "branch_witness_reason")
    if args.observe_rejected:
        fields += ("candidate_observation",)
    print(json.dumps({k: result.get(k) for k in fields},
                      sort_keys=True))
    return 1


if __name__ == "__main__":
    sys.exit(main())
