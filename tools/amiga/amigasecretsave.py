#!/usr/bin/env python3
"""Prepare an exact Silver Blades Save As disk and preserve a guarded WinUAE probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import gamedisks  # noqa: E402
from goldbox import amiga_adf, amiga_savegame  # noqa: E402
from tools.amiga import (  # noqa: E402
    amigaacceptance,
    amigabladesjournal,
    amigadrive,
    amigashots,
    winvmsettle,
)
from tools.registry import scratch  # noqa: E402

DISK_B_SHA256 = "d7caf68c3333b44a4ca2951b8d51f388e4bfd7a8bafa4fd8a7fca37aa639b468"
# The slot letter the game is offered on its own boot disk; side A ships only A.
SLOT_LETTER = "C"
JOIN_SHA256 = "38c11440e578227c1a240b740f362b1b69943d9897f42dc35ac39b17508872dc"
TITLE = "secret-of-the-silver-blades"
BOOT_CONFIG = r"C:\Amiga\configs\goldbox-a500.uae"
WINUAE_PS = r"powershell -NoProfile -ExecutionPolicy Bypass -File C:\Amiga\winuae.ps1"
# One `winvm shot` measured 5.6-7.8 s round trip; the capture script caps itself at 20 s.
SHOT_SECONDS = 20.0
HOLDER = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RouteError(RuntimeError):
    """A source, screen, lane action or fetched image failed its guard."""


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _entry(path: pathlib.Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256(path)}


def _verified_disk(path: pathlib.Path) -> amiga_adf.AmigaDisk:
    disk = amiga_adf.AmigaDisk.open(path)
    problems = disk.verify()
    if problems:
        raise RouteError(f"{path} fails ADF verification: {problems}")
    return disk


def _inventory(save: amiga_savegame.AmigaSavegame, *, require_joined: bool = True
               ) -> dict[str, Any]:
    members = []
    for person in save.characters:
        items = [
            {"type": item.get("type_index"), "plus": item.get("plus"),
             "quantity": item.get("quantity"), "names": [
                 item.get("name1"), item.get("name2"), item.get("name3")],
             "text": item.text}
            for item in person.items
        ]
        members.append({"name": person.name, "count": len(items), "items": items})
    guy = next((member for member in members
                if member["name"].upper() == "GUY DE VALOIS"), None)
    if guy is None:
        raise RouteError("Guy de Valois is absent from the converted Amiga party")
    arrows = [item for item in guy["items"]
              if item["type"] == 0x1E and item["plus"] == 1]
    joined_ok = (guy["count"] == 13 and len(arrows) == 1
                 and arrows[0]["quantity"] == 35)
    if require_joined and not joined_ok:
        raise RouteError(
            "Guy's converted inventory is not 13 items and one +1 arrow stack of 35")
    return {"members": members, "guy_index": members.index(guy),
            "joined_inventory_expected": joined_ok}


def find_disk_b() -> pathlib.Path:
    """The registered Silver Blades disk B, found by its pinned hash."""
    for root in gamedisks.candidates("amiga"):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.adf")):
            if path.stat().st_size == 901120 and sha256(path) == DISK_B_SHA256:
                return path
    raise RouteError("registered Silver Blades disk B was not found by its SHA-256")


def prepare(source: pathlib.Path, run_id: str) -> pathlib.Path:
    """Publish the C64 JOIN party as an immutable ADF and stage a private DF0."""
    if not HOLDER.fullmatch(run_id):
        raise RouteError("run id must use letters, digits, dot, underscore or hyphen")
    source = source.expanduser().resolve()
    if sha256(source) != JOIN_SHA256:
        raise RouteError(f"JOIN source SHA-256 differs: {sha256(source)}")
    boot_source = amigabladesjournal.find_disk()
    if sha256(boot_source) != amigaacceptance.SOURCE_SHA256:
        raise RouteError("registered Silver Blades side A differs from the measured build")
    run = scratch.cache_dir("acceptance", "672", run_id)
    df0 = scratch.cache_dir("amigaacceptance", run_id, "boot-with-slot.adf")
    if run.exists() or df0.exists():
        raise RouteError(f"run or staged DF0 already exists: {run}, {df0}")
    disk_b_source = find_disk_b()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from editor import roster, saveplan  # noqa: PLC0415
    from editor.convert import Source  # noqa: PLC0415
    from tools.convert import convertdrops  # noqa: PLC0415

    party = roster.Party(str(source))
    snapshot = saveplan.prepare(party)
    if snapshot is None:
        raise RouteError("the JOIN disk has no saved party")
    assets = saveplan.resolve_assets(Source.of_snapshot(snapshot), "amiga",
                                     game_files=convertdrops.game_files)
    published = run / "SECRETSAVE-published.adf"
    plan = saveplan.prepare_save_as(party, "amiga", published, assets)
    if plan.destination.slot != "A":
        raise RouteError(f"Save As selected slot {plan.destination.slot!r}, not A")
    if plan.report is None or plan.report.dropped or plan.report.losses:
        raise RouteError("Save As reports dropped fields or losses")

    scratch.ensure(run)
    saveplan.publish(plan, party)
    disk = _verified_disk(published)
    if disk.volume_name != "SECRETSAVE":
        raise RouteError(f"published volume is {disk.volume_name!r}, not SECRETSAVE")
    files = [path for path, _ in disk.walk()]
    if files != ["/SAVE/savgamA.sav"]:
        raise RouteError(f"published save disk has unexpected files: {files}")
    save = amiga_savegame.read_slot(disk, "A", TITLE)
    inventory = _inventory(save)
    state = amiga_savegame.state_from_savegame(save)
    slot = disk.read_file("/SAVE/savgamA.sav")
    stage = amigaacceptance.stage_embedded_boot_disk(boot_source, slot, SLOT_LETTER, df0)
    df1 = run / "disk-b-working.adf"
    with disk_b_source.open("rb") as reader, df1.open("xb") as writer:
        shutil.copyfileobj(reader, writer)
    if sha256(source) != JOIN_SHA256:
        raise RouteError("JOIN source changed during preparation")
    if sha256(boot_source) != amigaacceptance.SOURCE_SHA256:
        raise RouteError("registered boot disk changed during preparation")
    if sha256(df1) != DISK_B_SHA256 or sha256(disk_b_source) != DISK_B_SHA256:
        raise RouteError("working DF1 differs from the pinned disk B")
    published.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    manifest = {
        "source": _entry(source), "boot_source": _entry(boot_source),
        "df0": _entry(df0), "published_df1": _entry(published),
        "disk_b_source": _entry(disk_b_source), "df1": _entry(df1),
        "slot_letter": SLOT_LETTER, "slot_sha256": hashlib.sha256(slot).hexdigest(),
        "stage": stage, "inventory_a": inventory,
        "state_a": {"area": state.area, "x": state.x, "y": state.y,
                    "facing": state.facing},
        "dropped": list(plan.report.dropped), "losses": list(plan.report.losses),
    }
    manifest_path = run / "prepare.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest_path


class WinGuest:
    """One holder's WinUAE commands through the agent guest's `winvm`."""

    @staticmethod
    def _run(*args: str, timeout: float) -> str:
        proc = subprocess.Popen(
            ["winvm", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
            env=dict(os.environ, SSH_ASKPASS_REQUIRE="never"))
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
            raise RouteError(f"winvm {args[0]} exceeded its {timeout:.1f}s limit") from exc
        output = (stdout + stderr).strip()
        if proc.returncode:
            raise RouteError(f"winvm {args[0]} failed: {output}")
        return output

    def _lane(self, holder: str, command: str, timeout: float) -> str:
        output = self._run("ssh", f"{WINUAE_PS} {command} -Holder {holder}",
                           timeout=timeout)
        if not output.startswith("ok"):
            raise RouteError(f"winuae.ps1 {command} returned {output!r}")
        return output

    def claim(self, holder: str, timeout: float) -> str:
        return self._lane(holder, "claim", timeout)

    def put(self, local: pathlib.Path, remote: str, timeout: float) -> str:
        return self._run("put", str(local), remote, timeout=timeout)

    def start(self, holder: str, df0: str, df1: str, timeout: float) -> str:
        df0 = df0.replace("/", "\\")
        df1 = df1.replace("/", "\\")
        command = (f"start -f {BOOT_CONFIG} -s floppy0={df0} "
                   f"-s floppy1={df1} -s joyport1=none "
                   f"-s sound_output=interrupts")
        return self._lane(holder, command, timeout)

    def capture(self, state: str, raw: pathlib.Path, cropped: pathlib.Path,
                timeout: float) -> None:
        """Grab until two consecutive crops of the Amiga screen are identical."""
        started, previous, made, shots = time.monotonic(), None, False, 0
        try:
            while True:
                left = timeout - (time.monotonic() - started)
                # A short shot risks a timeout, so only the first one is allowed to be
                # short: a failure capture with little time left must still leave a frame.
                if left <= 0 or (left < SHOT_SECONDS and shots):
                    raise RouteError(f"{state} did not settle inside {timeout:.0f}s")
                allowed = min(SHOT_SECONDS, left)
                made = False
                shots += 1
                self._run("shot", str(raw), "--timeout", str(max(1, int(allowed))),
                          timeout=allowed)
                try:
                    amigashots.crop(raw, cropped)
                except LookupError:
                    # The WinUAE window is not up yet; the desktop is not a screen.
                    previous = None
                else:
                    made = True
                    frame = cropped.read_bytes()
                    if previous == frame:
                        return
                    previous = frame
                left = timeout - (time.monotonic() - started)
                if left > 0:
                    time.sleep(min(winvmsettle.INTERVAL, left))
        finally:
            if not made and raw.exists() and sys.exc_info()[0] is not None:
                try:
                    amigashots.crop(raw, cropped)
                except Exception:
                    pass

    def press(self, holder: str, key: str, timeout: float) -> str:
        name = key.upper()
        code = amigadrive.KEYS.get(name)
        if code is None:
            raise RouteError(f"{name} has no WinUAE key code")
        extended = " -Extended" if name in amigadrive.EXTENDED else ""
        return self._lane(holder, f"key {code:02X}{extended}", timeout)

    def stop(self, holder: str, timeout: float) -> str:
        return self._lane(holder, "stop", timeout)

    def get(self, remote: str, local: pathlib.Path, timeout: float) -> str:
        return self._run("get", remote, str(local), timeout=timeout)

    def release(self, holder: str, timeout: float) -> str:
        return self._lane(holder, "release", timeout)


class PixelGuards:
    """Exact static regions from measured captures; an unknown screen fails closed."""

    def __init__(self, path: pathlib.Path):
        self.rules = json.loads(path.read_text())
        required = {"title", "version", "play", "party_menu", "load_picker",
                    "loaded_menu", "sheet", "items", "save_picker"}
        if not required.issubset(self.rules):
            raise RouteError(f"screen guard map lacks {sorted(required - self.rules.keys())}")

    def __call__(self, state: str, image_path: pathlib.Path) -> bool:
        from PIL import Image  # noqa: PLC0415

        rule = self.rules.get(state)
        if rule is None:
            return False
        with Image.open(image_path) as image:
            box = rule["box"]
            if (len(box) != 4 or min(box) < 0 or box[2] > image.width
                    or box[3] > image.height or box[0] >= box[2]
                    or box[1] >= box[3]):
                raise RouteError(f"invalid crop box for {state}")
            pixels = image.convert("RGB").crop(tuple(box)).tobytes()
        return hashlib.sha256(pixels).hexdigest() == rule["sha256"]


ROUTE = (
    ("RET", "version"), ("RET", "play"), ("P", "party_menu"),
    ("L", "load_picker"), (SLOT_LETTER, "loaded_menu"), ("V", "sheet"),
    ("I", "items"), ("E", "sheet"), ("E", "loaded_menu"),
    ("S", "save_picker"),
)


MIN_WAIT_OVERRIDES = {"version": 50.0, "load_picker": 20.0, "loaded_menu": 20.0}
DEFAULT_MIN_WAIT = 15.0
TITLE_POLL = 10.0
TITLE_LIMIT = 180.0
MEASURE_TITLE_SPAN = 120.0
GUARD_POLL = 5.0
GUARD_LIMIT = 120.0


def default_min_waits(route=ROUTE) -> dict[str, float]:
    """Minimum seconds to sit on each state before its screen is captured."""
    return {state: MIN_WAIT_OVERRIDES.get(state, DEFAULT_MIN_WAIT)
            for _, state in route}


def parse_route(text: str) -> tuple[tuple[str, str], ...]:
    """Read `KEY:state,KEY:state` into a route."""
    steps = []
    for part in text.split(","):
        key, sep, state = part.strip().partition(":")
        if not sep or not key or not state:
            raise RouteError(f"route step {part!r} is not KEY:state")
        steps.append((key.upper(), state))
    return tuple(steps)


def parse_write_keys(text: str) -> tuple[str, ...]:
    """Read `KEY,KEY` into upper-case write keys; an empty entry is an error."""
    keys = tuple(k.strip().upper() for k in text.split(","))
    if not all(keys):
        raise RouteError(f"write keys {text!r} contain an empty entry")
    return keys


def _input(manifest: dict, name: str) -> pathlib.Path:
    entry = manifest[name]
    path = pathlib.Path(entry["path"])
    if not path.is_file() or sha256(path) != entry["sha256"]:
        raise RouteError(f"{name} is missing or changed from preparation")
    return path


def run_recon(manifest_path: pathlib.Path, *, guest: Any, guard: Any = None,
              holder: str, audio_proof: pathlib.Path, attempt: str = "recon1",
              deadline_seconds: float = 1800,
              route: tuple[tuple[str, str], ...] = ROUTE,
              write_keys: tuple[str, ...] = ("B",),
              min_waits: dict[str, float] | None = None,
              measure: bool = False) -> dict[str, Any]:
    """Walk the route, stopping at the first unrecognised state, and fetch both disks.

    Guarded mode presses the first write key after the route. Measure mode needs
    no guards, presses no write key and nothing after the route, and stops at the
    first key that leaves the settled screen unchanged.
    """
    if guard is None and not measure:
        raise RouteError("a screen guard is required unless measuring")
    min_waits = min_waits or {}
    write_keys = tuple(k.upper() for k in write_keys)
    if not all(write_keys):
        raise RouteError("write keys must not contain an empty entry")
    if measure:
        if not route:
            raise RouteError("measure mode needs at least one route step")
        # Measuring never writes, whatever the caller listed as write keys.
        write_keys = tuple(dict.fromkeys(write_keys + ("B",)))
    if not HOLDER.fullmatch(holder) or not HOLDER.fullmatch(attempt):
        raise RouteError("holder and attempt must use plain lane-safe names")
    if deadline_seconds <= 0:
        raise RouteError("reconnaissance deadline must be positive")
    audio_proof = pathlib.Path(audio_proof)
    if not _mute_proof(audio_proof):
        raise RouteError("the Windows VM audio mute has not been verified")
    manifest_path = pathlib.Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    originals = {name: _input(manifest, name)
                 for name in ("source", "boot_source", "disk_b_source")
                 if name in manifest}
    df0 = _input(manifest, "df0")
    published = _input(manifest, "published_df1")
    df1 = _input(manifest, "df1")
    if len({df0.resolve(), published.resolve(), df1.resolve()}) != 3:
        raise RouteError("DF0, published DF1 and working DF1 must be separate files")
    letter = manifest["slot_letter"]
    slot = _verified_disk(published).read_file("/SAVE/savgamA.sav")
    if hashlib.sha256(slot).hexdigest() != manifest["slot_sha256"]:
        raise RouteError("the published slot differs from the manifest")
    df0_disk = _verified_disk(df0)
    if df0_disk.read_file(f"/SAVE/savgam{letter}.sav") != slot:
        raise RouteError(f"DF0 /SAVE/savgam{letter}.sav is not Wish's published slot")
    df1_disk = _verified_disk(df1)
    if df1_disk.volume_name != "Secret 2":
        raise RouteError("working DF1 is not disk B, volume 'Secret 2'")
    if sha256(df1) != manifest["disk_b_source"]["sha256"]:
        raise RouteError("working DF1 differs from the registered disk B")
    out = manifest_path.parent / attempt
    out.mkdir(parents=False, exist_ok=False)
    shots = scratch.ensure(out / "shots")
    remote0 = f"C:/Amiga/Disks/wish672-{holder}-df0.adf"
    remote1 = f"C:/Amiga/Disks/wish672-{holder}-df1.adf"
    result: dict[str, Any] = {
        "success": False, "holder": holder, "input": str(manifest_path),
        "remote_df0": remote0, "remote_df1": remote1,
        "events": [], "error": "", "fetched": {},
        "deadline_seconds": deadline_seconds, "measure": measure,
    }
    claimed = start_attempted = copied = stopped = False
    return_early = False
    begun = time.monotonic()
    cleanup_window = min(300.0, deadline_seconds / 2)
    route_end = begun + deadline_seconds - cleanup_window
    total_end = begun + deadline_seconds
    cleanup_scale = cleanup_window / 300.0

    def route_limit(cap: float) -> float:
        left = route_end - time.monotonic()
        if left <= 0:
            raise RouteError("reconnaissance deadline reached before the next route action")
        return min(cap, left)

    def cleanup_limit(cap: float) -> float:
        left = total_end - time.monotonic()
        if left <= 0:
            raise RouteError("reconnaissance deadline reached during cleanup")
        return min(cap * cleanup_scale, left)

    def capture(state: str, *, check: bool = True,
                cleanup: bool = False) -> str:
        raw, cropped = shots / f"{state}.raw.png", shots / f"{state}.png"
        limit = cleanup_limit(90) if cleanup else route_limit(120)
        guest.capture(state, raw, cropped, timeout=limit)
        digest = sha256(cropped)
        result["events"].append({"state": state, "raw": str(raw),
                                 "crop": str(cropped), "sha256": sha256(raw),
                                 "crop_sha256": digest})
        if check and not guard(state, cropped):
            raise RouteError(f"{state} screen was not recognized; kept {raw}")
        return digest

    def wait(seconds: float) -> None:
        if seconds > 0:
            if route_end - time.monotonic() < seconds:
                raise RouteError("reconnaissance deadline reached during a minimum wait")
            time.sleep(seconds)

    def until_guard(state: str, name: str, first_wait: float,
                    poll: float, limit: float) -> None:
        """Wait, capture, and re-capture every `poll` seconds until the guard matches."""
        wait(first_wait)
        started = time.monotonic()
        while True:
            capture(name, check=False)
            if guard(state, shots / f"{name}.png"):
                return
            if time.monotonic() - started >= limit:
                raise RouteError(f"{state} screen was not recognized within {limit:.0f}s")
            wait(poll)

    def measure_boot() -> str:
        """Capture the boot every TITLE_POLL seconds, keeping each distinct frame."""
        started, last, n = time.monotonic(), "", 0
        while True:
            name = f"00-boot-{n:02d}"
            digest = capture(name, check=False)
            if digest == last:
                for path in (shots / f"{name}.raw.png", shots / f"{name}.png"):
                    path.unlink(missing_ok=True)
                result["events"][-1]["kept"] = False
            else:
                last, n = digest, n + 1
            if time.monotonic() - started >= MEASURE_TITLE_SPAN:
                return last
            wait(TITLE_POLL)

    try:
        receipt = guest.claim(holder, timeout=route_limit(30))
        if receipt != f"ok claimed by {holder}":
            raise RouteError(f"claim was not new: {receipt!r}; already yours is not a lane grant")
        result["claim"] = receipt
        claimed = True
        guest.put(df0, remote0, timeout=route_limit(90))
        guest.put(df1, remote1, timeout=route_limit(90))
        copied = True
        if not _mute_proof(audio_proof):
            raise RouteError("the Windows VM audio mute proof expired before WinUAE start")
        start_attempted = True
        result["start"] = guest.start(holder, remote0, remote1,
                                      timeout=route_limit(60))
        if measure:
            previous = measure_boot()
            changed = True
            for n, (key, state) in enumerate(route, 1):
                if key.upper() in write_keys:
                    result["events"].append({"skipped_write_key": key, "step": n})
                    changed = False
                    break
                guest.press(holder, key, timeout=route_limit(30))
                result["events"].append({"key": key, "step": n})
                wait(min_waits.get(state, 0))
                digest = capture(f"{n:02d}-{state}", check=False)
                if digest == previous:
                    result["events"].append({"unchanged": key, "step": n})
                    changed = False
                    break
                previous = digest
            result["route_changed"] = changed
            return_early = True
        else:
            until_guard("title", "title", 0, TITLE_POLL, TITLE_LIMIT)
            for n, (key, state) in enumerate(route, 1):
                guest.press(holder, key, timeout=route_limit(30))
                result["events"].append({"key": key, "step": n})
                until_guard(state, f"{n:02d}-{state}", min_waits.get(state, 0),
                            GUARD_POLL, GUARD_LIMIT)
            write = write_keys[0]
            guest.press(holder, write, timeout=route_limit(30))
            result["events"].append({"key": write, "step": len(route) + 1})
            capture("post-write", check=False)
        if not return_early:
            result["error"] = "post-write screen needs measured classification"
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        if start_attempted:
            try:
                capture("failure", check=False, cleanup=True)
            except BaseException as shot_error:
                result["failure_capture_error"] = f"{type(shot_error).__name__}: {shot_error}"
    finally:
        if start_attempted:
            try:
                result["stop"] = guest.stop(holder, timeout=cleanup_limit(30))
                stopped = True
            except BaseException as exc:
                result["stop_error"] = f"{type(exc).__name__}: {exc}"
        if copied:
            for name, remote in (("df0", remote0), ("df1", remote1)):
                local = out / f"fetched-{name}.adf"
                try:
                    guest.get(remote, local, timeout=cleanup_limit(60))
                    result["fetched"][name] = _entry(local)
                except BaseException as exc:
                    result[f"fetch_{name}_error"] = f"{type(exc).__name__}: {exc}"
        if claimed and (not start_attempted or stopped):
            try:
                result["release"] = guest.release(
                    holder, timeout=cleanup_limit(30))
            except BaseException as exc:
                result["release_error"] = f"{type(exc).__name__}: {exc}"
        result["published_unchanged"] = sha256(published) == manifest[
            "published_df1"]["sha256"]
        result["working_unchanged"] = sha256(df1) == manifest["df1"]["sha256"]
        for name, path in originals.items():
            result[f"{name}_unchanged"] = sha256(path) == manifest[name]["sha256"]
        if "df0" in result["fetched"]:
            result["df0_unchanged"] = result["fetched"]["df0"]["sha256"] == manifest[
                "df0"]["sha256"]
        if "df1" in result["fetched"]:
            result["df1_unchanged"] = result["fetched"]["df1"]["sha256"] == manifest[
                "df1"]["sha256"]
        if "df0" in result["fetched"]:
            # The game saves to the boot disk it found its SAVE drawer on.
            try:
                fetched = _verified_disk(out / "fetched-df0.adf")
                result["slot_unchanged"] = (
                    fetched.read_file(f"/SAVE/savgam{letter}.sav") == slot)
                result["slot_a_unchanged"] = (
                    fetched.read_file("/SAVE/savgamA.sav")
                    == df0_disk.read_file("/SAVE/savgamA.sav"))
                try:
                    b = fetched.read_file("/SAVE/savgamB.sav")
                except amiga_adf.AmigaDiskError:
                    result["slot_b_sha256"] = None
                else:
                    result["slot_b_sha256"] = hashlib.sha256(b).hexdigest()
                    try:
                        saved_b = amiga_savegame.read_slot(fetched, "B", TITLE)
                        state_b = amiga_savegame.state_from_savegame(saved_b)
                        result["slot_b"] = {
                            "inventory": _inventory(saved_b, require_joined=False),
                            "state": {"area": state_b.area, "x": state_b.x,
                                      "y": state_b.y, "facing": state_b.facing},
                        }
                    except BaseException as exc:
                        result["slot_b_decode_error"] = (
                            f"{type(exc).__name__}: {exc}")
            except BaseException as exc:
                result["fetched_df0_error"] = f"{type(exc).__name__}: {exc}"
        if measure:
            result["success"] = bool(
                result.get("route_changed") and not result["error"]
                and result.get("df0_unchanged") and result.get("df1_unchanged")
                and result.get("slot_b_sha256", "absent") is None)
        result["elapsed_seconds"] = time.monotonic() - begun
        (out / "summary.json").write_text(json.dumps(result, indent=2,
                                                     sort_keys=True) + "\n")
    return result


def _mute_proof(path: pathlib.Path) -> bool:
    """Require a recent UTC readback of the Windows VM's muted endpoint."""
    try:
        proof = json.loads(path.read_text())
        observed = datetime.fromisoformat(proof["observed_utc"].replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - observed
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return False
    return (proof.get("vm") == "WIN11-DEV" and proof.get("muted") is True
            and proof.get("readback") is True
            and proof.get("method") == "Windows Core Audio endpoint mute readback"
            and isinstance(proof.get("endpoint_id"), str)
            and bool(proof["endpoint_id"].strip())
            and observed.utcoffset() == timedelta(0)
            and timedelta() <= age <= timedelta(minutes=5))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="publish Wish's slot, stage DF0 holding it and DF1 as disk B")
    p.add_argument("--source", required=True, type=pathlib.Path)
    p.add_argument("--run-id", required=True)
    r = sub.add_parser("recon", help="guarded first load and menu-save probe")
    r.add_argument("--manifest", required=True, type=pathlib.Path)
    r.add_argument("--guards", type=pathlib.Path,
                   help="screen guard JSON; required unless --measure")
    r.add_argument("--measure", action="store_true",
                   help="capture only: no guards, never presses a write key")
    r.add_argument("--route", default=None,
                   help="KEY:state,KEY:state; default is the built-in route")
    r.add_argument("--write-keys", default="B",
                   help="comma-separated keys that write; measure never presses them")
    r.add_argument("--audio-proof", required=True, type=pathlib.Path)
    r.add_argument("--attempt", default="recon1")
    r.add_argument("--holder", default=None)
    sub.add_parser("accept", help="unavailable until the route is measured")
    sub.add_parser("spindisk-control", help="unavailable until the exact-output failure is measured")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            print(prepare(args.source, args.run_id))
            return 0
        if args.command == "recon":
            if args.guards is None and not args.measure:
                raise RouteError("--guards is required unless --measure")
            guards = PixelGuards(args.guards) if args.guards else None
            route = parse_route(args.route) if args.route else ROUTE
            write_keys = parse_write_keys(args.write_keys)
            holder = args.holder or f"wish672-{uuid.uuid4().hex[:12]}"
            result = run_recon(args.manifest, guest=WinGuest(), guard=guards,
                               holder=holder,
                               audio_proof=args.audio_proof,
                               attempt=args.attempt, route=route,
                               write_keys=write_keys, measure=args.measure,
                               min_waits=default_min_waits(route))
            print(json.dumps({"success": result["success"],
                              "error": result["error"],
                              "summary": str(args.manifest.parent / args.attempt
                                             / "summary.json")}, sort_keys=True))
            return 0 if result["success"] else 1
        raise RouteError(f"{args.command} is unavailable until the measured route is reviewed")
    except (RouteError, OSError, ValueError) as exc:
        print(f"amigasecretsave: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
