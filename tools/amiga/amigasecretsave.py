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
import stat
import subprocess
import sys
import time
import uuid
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from goldbox import amiga_adf, amiga_savegame  # noqa: E402
from tools.amiga import (  # noqa: E402
    amigaacceptance,
    amigabladesjournal,
    amigadrive,
    amigashots,
    winvmsettle,
)
from tools.registry import scratch  # noqa: E402

JOIN_SHA256 = "38c11440e578227c1a240b740f362b1b69943d9897f42dc35ac39b17508872dc"
TITLE = "secret-of-the-silver-blades"
BOOT_CONFIG = r"C:\Amiga\configs\goldbox-a500.uae"
WINUAE_PS = r"powershell -NoProfile -ExecutionPolicy Bypass -File C:\Amiga\winuae.ps1"
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
    df0 = scratch.cache_dir("amigaacceptance", run_id, "boot-no-save.adf")
    if run.exists() or df0.exists():
        raise RouteError(f"run or staged DF0 already exists: {run}, {df0}")

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

    stage = amigaacceptance.stage_boot_disk(boot_source, df0)
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
    working = run / "SECRETSAVE-working.adf"
    with published.open("rb") as reader, working.open("xb") as writer:
        shutil.copyfileobj(reader, writer)
    if sha256(source) != JOIN_SHA256:
        raise RouteError("JOIN source changed during preparation")
    if sha256(boot_source) != amigaacceptance.SOURCE_SHA256:
        raise RouteError("registered boot disk changed during preparation")
    if sha256(working) != sha256(published):
        raise RouteError("working DF1 differs from Wish's published output")
    published.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    manifest = {
        "source": _entry(source), "boot_source": _entry(boot_source),
        "df0": _entry(df0), "published_df1": _entry(published),
        "working_df1": _entry(working), "slot_a_sha256": hashlib.sha256(
            disk.read_file("/SAVE/savgamA.sav")).hexdigest(),
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
    def _run(*args: str, timeout: int = 180) -> str:
        proc = subprocess.run(["winvm", *args], capture_output=True, text=True,
                              timeout=timeout,
                              env=dict(os.environ, SSH_ASKPASS_REQUIRE="never"))
        output = (proc.stdout + proc.stderr).strip()
        if proc.returncode:
            raise RouteError(f"winvm {args[0]} failed: {output}")
        return output

    def _lane(self, holder: str, command: str) -> str:
        output = self._run("ssh", f"{WINUAE_PS} {command} -Holder {holder}")
        if not output.startswith("ok"):
            raise RouteError(f"winuae.ps1 {command} returned {output!r}")
        return output

    def claim(self, holder: str) -> str:
        return self._lane(holder, "claim")

    def put(self, local: pathlib.Path, remote: str) -> str:
        return self._run("put", str(local), remote)

    def start(self, holder: str, df0: str, df1: str) -> str:
        df0 = df0.replace("/", "\\")
        df1 = df1.replace("/", "\\")
        command = (f"start -log -f {BOOT_CONFIG} -s floppy0={df0} "
                   f"-s floppy1={df1} -s joyport1=none "
                   f"-s sound_output=interrupts")
        return self._lane(holder, command)

    def capture(self, state: str, raw: pathlib.Path, cropped: pathlib.Path) -> None:
        settled = winvmsettle.settle(raw, limit=120)
        amigashots.crop(raw, cropped)
        if not settled:
            raise RouteError(f"{state} did not settle; kept {raw} and {cropped}")

    @staticmethod
    def press(holder: str, key: str) -> str:
        return amigadrive.press(holder, key, 0)

    def stop(self, holder: str) -> str:
        return self._lane(holder, "stop")

    def get(self, remote: str, local: pathlib.Path) -> str:
        return self._run("get", remote, str(local))

    def release(self, holder: str) -> str:
        return self._lane(holder, "release")


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
    ("L", "load_picker"), ("A", "loaded_menu"), ("V", "sheet"),
    ("I", "items"), ("E", "sheet"), ("E", "loaded_menu"),
    ("S", "save_picker"),
)


def _input(manifest: dict, name: str) -> pathlib.Path:
    entry = manifest[name]
    path = pathlib.Path(entry["path"])
    if not path.is_file() or sha256(path) != entry["sha256"]:
        raise RouteError(f"{name} is missing or changed from preparation")
    return path


def run_recon(manifest_path: pathlib.Path, *, guest: Any, guard: Any,
              holder: str, mute_verified: bool, attempt: str = "recon1",
              deadline_seconds: float = 1800) -> dict[str, Any]:
    """Stop at the first unrecognised state and fetch both disks after any write."""
    if not HOLDER.fullmatch(holder) or not HOLDER.fullmatch(attempt):
        raise RouteError("holder and attempt must use plain lane-safe names")
    if not mute_verified:
        raise RouteError("the Windows VM audio mute has not been verified")
    manifest_path = pathlib.Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    originals = {name: _input(manifest, name)
                 for name in ("source", "boot_source") if name in manifest}
    df0 = _input(manifest, "df0")
    published = _input(manifest, "published_df1")
    working = _input(manifest, "working_df1")
    if len({df0.resolve(), published.resolve(), working.resolve()}) != 3:
        raise RouteError("DF0, published DF1 and working DF1 must be separate files")
    if sha256(published) != sha256(working):
        raise RouteError("working DF1 differs from the exact published output")
    _verified_disk(df0)
    df1_disk = _verified_disk(working)
    if df1_disk.volume_name != "SECRETSAVE" or [p for p, _ in df1_disk.walk()] != [
            "/SAVE/savgamA.sav"]:
        raise RouteError("working DF1 is not the standalone slot-A SECRETSAVE")
    out = manifest_path.parent / attempt
    out.mkdir(parents=False, exist_ok=False)
    shots = scratch.ensure(out / "shots")
    remote0 = f"C:/Amiga/Disks/wish672-{holder}-df0.adf"
    remote1 = f"C:/Amiga/Disks/wish672-{holder}-df1.adf"
    result: dict[str, Any] = {
        "success": False, "holder": holder, "input": str(manifest_path),
        "remote_df0": remote0, "remote_df1": remote1,
        "events": [], "error": "", "fetched": {},
    }
    claimed = start_attempted = copied = stopped = False
    begun = time.monotonic()

    def capture(state: str, *, check: bool = True) -> None:
        raw, cropped = shots / f"{state}.raw.png", shots / f"{state}.png"
        guest.capture(state, raw, cropped)
        result["events"].append({"state": state, "raw": str(raw),
                                 "crop": str(cropped), "sha256": sha256(raw)})
        if check and not guard(state, cropped):
            raise RouteError(f"{state} screen was not recognized; kept {raw}")

    try:
        result["claim"] = guest.claim(holder)
        claimed = True
        guest.put(df0, remote0)
        guest.put(working, remote1)
        copied = True
        start_attempted = True
        result["start"] = guest.start(holder, remote0, remote1)
        capture("title")
        for n, (key, state) in enumerate(ROUTE, 1):
            if time.monotonic() - begun > deadline_seconds:
                raise RouteError("reconnaissance exceeded its 1800-second deadline")
            guest.press(holder, key)
            result["events"].append({"key": key, "step": n})
            capture(f"{n:02d}-{state}", check=False)
            if not guard(state, shots / f"{n:02d}-{state}.png"):
                raise RouteError(f"{state} screen was not recognized after {key}")
        guest.press(holder, "B")
        result["events"].append({"key": "B", "step": len(ROUTE) + 1})
        capture("post-write", check=False)
        result["error"] = "post-write screen needs measured classification"
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        if start_attempted:
            try:
                capture("failure", check=False)
            except BaseException as shot_error:
                result["failure_capture_error"] = f"{type(shot_error).__name__}: {shot_error}"
    finally:
        if start_attempted:
            try:
                result["stop"] = guest.stop(holder)
                stopped = True
            except BaseException as exc:
                result["stop_error"] = f"{type(exc).__name__}: {exc}"
        if copied:
            for name, remote in (("df0", remote0), ("df1", remote1)):
                local = out / f"fetched-{name}.adf"
                try:
                    guest.get(remote, local)
                    result["fetched"][name] = _entry(local)
                except BaseException as exc:
                    result[f"fetch_{name}_error"] = f"{type(exc).__name__}: {exc}"
        if claimed and (not start_attempted or stopped):
            try:
                result["release"] = guest.release(holder)
            except BaseException as exc:
                result["release_error"] = f"{type(exc).__name__}: {exc}"
        result["published_unchanged"] = sha256(published) == manifest[
            "published_df1"]["sha256"]
        result["working_unchanged"] = sha256(working) == manifest[
            "working_df1"]["sha256"]
        for name, path in originals.items():
            result[f"{name}_unchanged"] = sha256(path) == manifest[name]["sha256"]
        if "df0" in result["fetched"]:
            result["df0_unchanged"] = result["fetched"]["df0"]["sha256"] == manifest[
                "df0"]["sha256"]
        if "df1" in result["fetched"]:
            try:
                fetched = _verified_disk(out / "fetched-df1.adf")
                result["slot_a_unchanged"] = (
                    fetched.read_file("/SAVE/savgamA.sav")
                    == df1_disk.read_file("/SAVE/savgamA.sav"))
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
                result["fetched_df1_error"] = f"{type(exc).__name__}: {exc}"
        (out / "summary.json").write_text(json.dumps(result, indent=2,
                                                     sort_keys=True) + "\n")
    return result


def _mute_proof(path: pathlib.Path) -> bool:
    """Require an external, dated VM endpoint-mute measurement before boot."""
    proof = json.loads(path.read_text())
    return (proof.get("vm") == "WIN11-DEV" and proof.get("muted") is True
            and bool(proof.get("method")) and bool(proof.get("observed_utc")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="publish exact DF1 and stage private DF0")
    p.add_argument("--source", required=True, type=pathlib.Path)
    p.add_argument("--run-id", required=True)
    r = sub.add_parser("recon", help="guarded first load and menu-save probe")
    r.add_argument("--manifest", required=True, type=pathlib.Path)
    r.add_argument("--guards", required=True, type=pathlib.Path)
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
            guards = PixelGuards(args.guards)
            holder = args.holder or f"wish672-{uuid.uuid4().hex[:12]}"
            result = run_recon(args.manifest, guest=WinGuest(), guard=guards,
                               holder=holder,
                               mute_verified=_mute_proof(args.audio_proof),
                               attempt=args.attempt)
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
