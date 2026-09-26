#!/usr/bin/env python3
"""Prepare an exact Silver Blades Save As disk and preserve a guarded WinUAE probe."""

from __future__ import annotations

import argparse
import contextlib
import functools
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
from goldbox import amiga_adf, amiga_savegame, geo  # noqa: E402
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


class Terminated(BaseException):
    """The wrapper's `timeout` sent SIGTERM; a `BaseException` so a `finally` still runs."""


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

    def grab(self, state: str, raw: pathlib.Path, cropped: pathlib.Path,
             timeout: float) -> bool:
        """One grab, cropped to the Amiga screen; False when WinUAE's window is not up.

        A guard reads a static box, so an animated screen needs no settling.
        """
        if timeout <= 0:
            raise RouteError(f"no time left to grab {state}")
        allowed = min(SHOT_SECONDS, timeout)
        self._run("shot", str(raw), "--timeout", str(max(1, int(allowed))),
                  timeout=allowed)
        try:
            amigashots.crop(raw, cropped)
        except LookupError:
            return False
        return True

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


def _box_pixels(image_path: pathlib.Path, box, state: str) -> bytes:
    """The RGB pixels inside `box` of a cropped Amiga screen."""
    from PIL import Image  # noqa: PLC0415

    with Image.open(image_path) as image:
        if (len(box) != 4 or min(box) < 0 or box[2] > image.width
                or box[3] > image.height or box[0] >= box[2]
                or box[1] >= box[3]):
            raise RouteError(f"invalid crop box for {state}")
        return image.convert("RGB").crop(tuple(box)).tobytes()


def _box_digest(image_path: pathlib.Path, box, state: str) -> str:
    """SHA-256 of the RGB pixels inside `box` of a cropped Amiga screen."""
    return hashlib.sha256(_box_pixels(image_path, box, state)).hexdigest()


def _box_is_uniform(image_path: pathlib.Path, box, state: str) -> bool:
    """Whether every pixel in `box` is one colour, so the box matches any screen showing it."""
    pixels = _box_pixels(image_path, box, state)
    return len({pixels[i:i + 3] for i in range(0, len(pixels), 3)}) == 1


def guard_rule(image_path: pathlib.Path, box, state: str = "guard") -> dict[str, Any]:
    """The `PixelGuards` rule that recognises `box` exactly as this crop shows it."""
    box = [int(n) for n in box]
    return {"box": box, "sha256": _box_digest(pathlib.Path(image_path), box, state)}


class PixelGuards:
    """Exact static regions from measured captures; an unknown screen fails closed."""

    def __init__(self, path: pathlib.Path):
        self.rules = json.loads(pathlib.Path(path).read_text())
        for state, rule in self.rules.items():
            if (not isinstance(rule, dict) or not isinstance(rule.get("box"), list)
                    or not re.fullmatch(r"[0-9a-f]{64}", str(rule.get("sha256")))):
                raise RouteError(f"screen guard for {state} needs a box and a sha256")

    def __contains__(self, state: str) -> bool:
        return state in self.rules

    def __call__(self, state: str, image_path: pathlib.Path) -> bool:
        rule = self.rules.get(state)
        if rule is None:
            return False
        return _box_digest(image_path, rule["box"], state) == rule["sha256"]


def _guards(guard: Any, state: str) -> bool:
    """Whether `guard` has a rule for `state`; a bare callable guards every state."""
    if guard is None:
        return False
    try:
        return state in guard
    except TypeError:
        return True


# `title` is the screen the route starts from: the version line over the
# PLAY / DEMO / QUIT bar, which takes `P` and ignores RETURN. Left alone, the
# attract loop moves on from it to the story intro and the credits.
ROUTE = (
    ("P", "party_menu"), ("L", "load_picker"), (SLOT_LETTER, "loaded_menu"),
    ("V", "sheet"), ("I", "items"), ("E", "sheet"), ("E", "loaded_menu"),
    ("S", "save_picker"),
)


MIN_WAIT_OVERRIDES = {"load_picker": 20.0, "loaded_menu": 20.0}
DEFAULT_MIN_WAIT = 15.0
# Single grabs every ~8-10 s in all against a bar that held still for at least 24 s.
TITLE_POLL = 2.0
TITLE_LIMIT = 180.0
MEASURE_BOOT_POLL = 10.0
MEASURE_TITLE_SPAN = 120.0
GUARD_POLL = 5.0
GUARD_LIMIT = 120.0
# A key pressed while the disk is being written is swallowed, so the screen
# after the write gets the same long first wait as the load picker.
POST_WRITE_WAIT = 20.0

# The two saves the accept route writes, on slots the game's own disk never ships.
MENU_SAVE_LETTER = "B"
CAMP_SAVE_LETTER = "D"

# (key, state reached, kind). `write` saves, `answer` runs the journal answerer
# instead of pressing a key, `move` is a movement key. Silver Blades takes no
# RETURN after the camp save's letter, and RETURN at EXIT GAME is unmeasured, so
# the route never presses either.
ACCEPT_ROUTE = (
    *((key, state, "key") for key, state in ROUTE),
    (MENU_SAVE_LETTER, "loaded_menu", "write"),
    ("B", "journal", "key"),
    (None, "world", "answer"),
    ("NP8", "world", "move"), ("NP8", "world", "move"),
    ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
    (CAMP_SAVE_LETTER, "exit_game", "write"),
    ("N", "camp", "key"),
)
# The world bar is one state reached two ways, so its wait after a move has its own key.
ACCEPT_MIN_WAITS = {
    "loaded_menu": 20.0, "journal": 45.0, "world": 20.0, "world_after_move": 5.0,
    "camp": 10.0, "camp_save_picker": 10.0, "exit_game": 20.0,
}
# A state the guard map has must match or the run stops; the rest are measured
# by settling a capture and are marked unguarded.
IDENTITY_MESSAGES = {"sheet": "sheet shows another member",
                     "loaded_menu": "loaded_menu shows another party"}
JOURNAL_SCRIPT = pathlib.Path(__file__).with_name("amigabladesjournal.py")


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


def _slot_reading(fetched: amiga_adf.AmigaDisk, letter: str) -> dict[str, Any]:
    """Read one save slot off a fetched boot disk with the existing readers.

    Returns `missing`, or `decode_error`, or the digest, place, member names and
    inventory; `decode_error` still carries the digest.
    """
    try:
        raw = fetched.read_file(f"/SAVE/savgam{letter}.sav")
    except amiga_adf.AmigaDiskError:
        return {"missing": True, "sha256": None}
    reading: dict[str, Any] = {"sha256": hashlib.sha256(raw).hexdigest()}
    try:
        saved = amiga_savegame.read_slot(fetched, letter, TITLE)
        state = amiga_savegame.state_from_savegame(saved)
        inventory = _inventory(saved, require_joined=False)
    except BaseException as exc:
        reading["decode_error"] = f"{type(exc).__name__}: {exc}"
        return reading
    reading["place"] = {"area": state.area, "x": state.x, "y": state.y,
                        "facing": state.facing}
    reading["names"] = [member["name"] for member in inventory["members"]]
    reading["inventory"] = inventory
    return reading


def menu_save_problems(manifest: dict, reading: dict[str, Any], *, letter: str = "B",
                       check_place: bool = True) -> list[str]:
    """What a save left different from the prepared party; empty means it matches."""
    slot = f"slot {letter}"
    if reading.get("missing"):
        return [f"{slot} was not written"]
    if "decode_error" in reading:
        return [f"{slot} does not decode: {reading['decode_error']}"]
    problems = []
    if check_place and reading["place"] != manifest["state_a"]:
        problems.append(
            f"{slot} place {reading['place']} differs from {manifest['state_a']}")
    wanted = [member["name"] for member in manifest["inventory_a"]["members"]]
    if reading["names"] != wanted:
        problems.append(f"{slot} members {reading['names']} differ from {wanted}")
    if not reading["inventory"]["joined_inventory_expected"]:
        problems.append(f"{slot} is not Guy with 13 items and one +1 arrow stack of 35")
    return problems


def _span(a: dict, b: dict) -> str:
    """`3,5 to 3,7`; the area and facing are named only when they differ."""
    if a["area"] == b["area"] and a["facing"] == b["facing"]:
        return f"{a['x']},{a['y']} to {b['x']},{b['y']}"
    return (f"area {a['area']} {a['x']},{a['y']} facing {a['facing']} to "
            f"area {b['area']} {b['x']},{b['y']} facing {b['facing']}")


def _unreadable(letter: str, reading: dict[str, Any]) -> str:
    return f"slot {letter}: " + ("was not written" if reading.get("missing")
                                 else "does not decode")


def walk_verdict(before: dict, b: dict[str, Any], d: dict[str, Any],
                 squares: int) -> dict[str, Any]:
    """Judge the two saves: B, saved before the walk, must be `before`; D must be `squares` on.

    The step routine wraps at 0 and 15, so D is compared modulo 16 along B's
    facing. The screen never judges movement.
    """
    verdicts: list[str] = []
    b_place, d_place = b.get("place"), d.get("place")
    b_ok = d_ok = False
    if b_place is None:
        verdicts.append(_unreadable("B", b))
    elif b_place == before:
        b_ok = True
        verdicts.append("slot B: did not move")
    else:
        verdicts.append(f"slot B: moved from {_span(before, b_place)}, expected the prepared place")
    base = b_place or before
    squares_moved = None
    if d_place is None:
        verdicts.append(_unreadable("D", d))
    else:
        dx, dy = geo.STEP[base["facing"]]
        expected = dict(base, x=(base["x"] + dx * squares) % 16,
                        y=(base["y"] + dy * squares) % 16)
        if d_place["area"] == base["area"] and d_place["facing"] == base["facing"]:
            along = (d_place["x"] - base["x"]) * dx + (d_place["y"] - base["y"]) * dy
            across = (d_place["x"] - base["x"]) * dy + (d_place["y"] - base["y"]) * dx
            # A wrapped step and a full lap cannot be told apart on 16 squares.
            if across == 0 or (across % 16 == 0):
                squares_moved = along % 16
        if d_place == base:
            d_ok = squares == 0
            verdicts.append("slot D: did not move")
        elif d_place == expected:
            d_ok = True
            unit = "square" if squares == 1 else "squares"
            verdicts.append(f"slot D: moved {squares} {unit} from {_span(base, d_place)}")
        else:
            verdicts.append(f"slot D: moved from {_span(base, d_place)}, "
                            f"expected {expected['x']},{expected['y']}")
    return {"verdicts": verdicts, "b_ok": b_ok, "d_ok": d_ok,
            "place_changed": None if d_place is None else d_place != base,
            "squares_moved": squares_moved}


def journal_preflight(journal_python: str) -> None:
    """Refuse before the lane is claimed unless the private reader's imports and tables are there."""
    try:
        proc = subprocess.run([journal_python, "-c", "import numpy, PIL"],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RouteError(f"the journal interpreter {journal_python!r} did not run: {exc}") from exc
    if proc.returncode:
        raise RouteError(f"the journal interpreter {journal_python!r} cannot import numpy and PIL")
    analysis = amigabladesjournal.wheel_repo() / "ssb" / "analysis"
    if not analysis.is_dir():
        raise RouteError(f"{analysis} is not a directory, so the journal cannot be answered")


def run_journal_answer(journal_python: str, holder: str, adf: pathlib.Path,
                       timeout: float, script: pathlib.Path = JOURNAL_SCRIPT
                       ) -> tuple[int, str]:
    """Run the answerer in its own interpreter; its exit code and last line of stdout.

    A subprocess, because numpy and Pillow live in `journal_python` and this
    driver imports neither. Nothing else it prints is kept.
    """
    try:
        proc = subprocess.run(
            [journal_python, str(script), "--holder", holder, "--adf", str(adf)],
            capture_output=True, text=True, timeout=timeout,
            env=dict(os.environ, SSH_ASKPASS_REQUIRE="never"))
    except subprocess.TimeoutExpired as exc:
        raise RouteError(f"the journal answerer exceeded its {timeout:.0f}s limit") from exc
    lines = proc.stdout.strip().splitlines()
    return proc.returncode, lines[-1].strip() if lines else ""


def _has_rule(guard: Any, state: str) -> bool:
    """Whether a guard *map* holds `state`; a bare callable holds none, so no interstitial fires."""
    return hasattr(guard, "__contains__") and state in guard


def _terminate(signum, frame):
    raise Terminated(f"signal {signum}")


@contextlib.contextmanager
def terminating():
    """SIGTERM raises `Terminated`, so a wrapper's `timeout` still reaches `run_recon`'s `finally`."""
    previous = signal.signal(signal.SIGTERM, _terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def menu_save_verdict(result: dict[str, Any], originals: tuple[str, ...]) -> bool:
    """A guarded run passes when the game wrote slot B as prepared and touched nothing else."""
    return bool(
        not result["error"] and not result["menu_save_problems"]
        and result.get("slot_unchanged") and result.get("slot_a_unchanged")
        and result.get("df1_unchanged") and result.get("published_unchanged")
        and result.get("working_unchanged")
        and all(result.get(f"{name}_unchanged") for name in originals)
        # The write to slot B is the point of the run, so DF0 must have changed.
        and result.get("df0_unchanged") is False)


def run_recon(manifest_path: pathlib.Path, *, guest: Any, guard: Any = None,
              holder: str, audio_proof: pathlib.Path, attempt: str = "recon1",
              deadline_seconds: float = 1800,
              route: tuple[tuple[str, str], ...] = ROUTE,
              write_keys: tuple[str, ...] = ("B",),
              min_waits: dict[str, float] | None = None,
              measure: bool = False, accept: bool = False,
              identity: Any = None, journal_python: str | None = None,
              answer: Any = None, preflight: Any = None) -> dict[str, Any]:
    """Walk the route, stopping at the first unrecognised state, and fetch both disks.

    A guarded state is found by polling single grabs until its static box
    matches, so an animated screen needs no settling. Guarded mode needs a
    guard for `title` and every route state, and presses the first write key
    after the route. Measure mode takes any subset of guards, settles the
    screens it has none for, presses no write key and nothing after the route,
    and stops at the first unrecognised guarded state or at the first key that
    leaves the screen unchanged.

    `accept` walks `ACCEPT_ROUTE` after the same guarded route: a menu save to
    slot B, BEGIN, the journal answer, two squares, a camp save to slot D. A
    state the guard map lacks is settled, marked unguarded and makes the run a
    measuring one; the route states never fall back. It reads slots B and D
    back, and `answer(journal_python, holder, adf, timeout)` stands in for the
    answerer's subprocess.
    """
    if guard is None and not measure:
        raise RouteError("a screen guard is required unless measuring")
    if accept:
        if measure:
            raise RouteError("accept and measure are separate modes")
        if route != ROUTE:
            raise RouteError("accept walks its own route")
        for letter in (MENU_SAVE_LETTER, CAMP_SAVE_LETTER):
            if letter in (SLOT_LETTER, "A"):
                raise RouteError(f"save letter {letter} would overwrite the prepared slot")
        if identity is None or not all(_has_rule(identity, s)
                                       for s in IDENTITY_MESSAGES):
            raise RouteError(f"identity map lacks {sorted(IDENTITY_MESSAGES)}")
        if not journal_python and answer is None:
            raise RouteError("accept needs a journal interpreter")
    if not measure:
        missing = [s for s in dict.fromkeys(("title", *(s for _, s in route)))
                   if not _guards(guard, s)]
        if missing:
            raise RouteError(f"screen guard map lacks {missing}")
    if accept:
        (preflight or journal_preflight)(journal_python)
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
    if accept and "boot_source" not in originals:
        raise RouteError("the manifest names no boot_source for the journal answerer")
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
    runlog = (out / "run.jsonl").open("a", encoding="utf-8")
    remote0 = f"C:/Amiga/Disks/wish672-{holder}-df0.adf"
    remote1 = f"C:/Amiga/Disks/wish672-{holder}-df1.adf"
    result: dict[str, Any] = {
        "success": False, "holder": holder, "input": str(manifest_path),
        "remote_df0": remote0, "remote_df1": remote1,
        "events": [], "error": "", "fetched": {},
        "deadline_seconds": deadline_seconds, "measure": measure,
        "accept": accept, "completed": False, "lost": None, "unguarded": [],
    }
    steps = ACCEPT_ROUTE if accept else (
        *((k, s, "key") for k, s in route), (write_keys[0], "loaded_menu", "write"))
    strict_states = {"title", *(s for _, s in ROUTE)}
    landed: dict[str, Any] = {"state": None}
    if accept and answer is None:
        answer = functools.partial(run_journal_answer, journal_python)
    claimed = start_attempted = copied = stopped = False
    begun = time.monotonic()
    cleanup_window = min(300.0, deadline_seconds / 2)
    route_end = begun + deadline_seconds - cleanup_window
    total_end = begun + deadline_seconds
    cleanup_scale = cleanup_window / 300.0

    def log(event: str, **fields: Any) -> None:
        runlog.write(json.dumps({"event": event, "t": time.time(), **fields},
                                sort_keys=True) + "\n")
        runlog.flush()

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
                cleanup: bool = False, settle: bool = True) -> str:
        """Capture `state` and return its crop's hash; "" when a grab found no window."""
        raw, cropped = shots / f"{state}.raw.png", shots / f"{state}.png"
        if settle:
            limit = cleanup_limit(90) if cleanup else route_limit(120)
            guest.capture(state, raw, cropped, timeout=limit)
        else:
            cropped.unlink(missing_ok=True)
            if not guest.grab(state, raw, cropped, timeout=route_limit(SHOT_SECONDS)):
                result["events"].append({"state": state, "raw": str(raw),
                                         "sha256": sha256(raw), "crop": None})
                log("grab", state=state, raw=str(raw), crop=None)
                return ""
        digest = sha256(cropped)
        result["events"].append({"state": state, "raw": str(raw),
                                 "crop": str(cropped), "sha256": sha256(raw),
                                 "crop_sha256": digest})
        log("settled" if settle else "grab", state=state, raw=str(raw),
            crop=str(cropped), crop_sha256=digest)
        if check and not guard(state, cropped):
            raise RouteError(f"{state} screen was not recognized; kept {raw}")
        return digest

    def wait(seconds: float) -> None:
        if seconds > 0:
            if route_end - time.monotonic() < seconds:
                raise RouteError("reconnaissance deadline reached during a minimum wait")
            time.sleep(seconds)

    def check_identity(state: str, crop: pathlib.Path) -> None:
        if identity is not None and _has_rule(identity, state) and not identity(state, crop):
            raise RouteError(IDENTITY_MESSAGES[state])

    def run_answer() -> None:
        """Run the journal answerer, again while it sees no challenge, until GUARD_LIMIT."""
        started = time.monotonic()
        adf = originals["boot_source"]
        while True:
            code, line = answer(holder, adf, route_limit(180))
            result["events"].append({"answer": line, "exit_code": code})
            log("answer", exit_code=code, line=line)
            if code == 0 and line == "answered":
                return
            if line != "no challenge on screen":
                raise RouteError(f"the journal answerer ended {code}: {line!r}")
            if time.monotonic() - started >= GUARD_LIMIT:
                raise RouteError(f"no journal challenge on screen within {GUARD_LIMIT:.0f}s")
            wait(GUARD_POLL)

    def interstitial(state: str, crop: pathlib.Path, done: set[str]) -> bool:
        """Act once per wait on a known screen that is not the wanted one."""
        def press(screen: str, key: str) -> None:
            done.add(screen)
            guest.press(holder, key, timeout=route_limit(30))
            result["events"].append({"interstitial": screen, "key": key})
            log("interstitial", screen=screen, key=key)

        if (state == "title" and "credits" not in done and _has_rule(guard, "credits")
                and guard("credits", crop)):
            press("credits", "ESC")
            return True
        if not accept:
            return False
        if ("continue" not in done and _has_rule(guard, "continue")
                and guard("continue", crop)):
            press("continue", "RET")
            return True
        if (state == "exit_game" and "journal" not in done and _has_rule(guard, "journal")
                and guard("journal", crop)):
            done.add("journal")
            result["events"].append({"interstitial": "journal"})
            log("interstitial", screen="journal", key=None)
            run_answer()
            return True
        return False

    def settle_unguarded(state: str, name: str) -> str:
        """One settled capture of a state nobody has measured, marked as such."""
        digest = capture(name, check=False)
        result["events"][-1]["recognized"] = False
        if state not in result["unguarded"]:
            result["unguarded"].append(state)
        return digest

    def until_guard(state: str, name: str, first_wait: float,
                    poll: float, limit: float, *, strict: bool = True) -> str:
        """Wait, then grab every `poll` seconds until the guard matches; keep the last crop.

        A state that is not `strict` and never matches falls back to a settled capture.
        """
        wait(first_wait)
        started = time.monotonic()
        done: set[str] = set()
        crop = shots / f"{name}.png"
        while True:
            digest = capture(name, check=False, settle=False)
            if digest:
                wanted = [state]
                if "credits" in done and _has_rule(guard, "party_menu"):
                    wanted.append("party_menu")
                hit = next((s for s in wanted if guard(s, crop)), None)
                if hit:
                    check_identity(hit, crop)
                    landed["state"] = hit
                    result["events"][-1]["recognized"] = hit
                    log("recognized", state=hit, name=name)
                    return digest
                interstitial(state, crop, done)
            if time.monotonic() - started >= limit:
                if not strict:
                    return settle_unguarded(state, name)
                raise RouteError(f"{state} screen was not recognized within {limit:.0f}s;"
                                 f" kept {crop}")
            wait(poll)

    def reach(state: str, name: str, first_wait: float, *, strict: bool) -> str:
        if _guards(guard, state):
            return until_guard(state, name, first_wait, GUARD_POLL, GUARD_LIMIT,
                               strict=strict)
        wait(first_wait)
        done: set[str] = set()
        digest = settle_unguarded(state, name)
        for again in range(1, 4):
            if not interstitial(state, shots / f"{name}.png", done):
                break
            wait(first_wait)
            digest = settle_unguarded(state, f"{name}-after-{again}")
        return digest

    def measure_boot() -> str:
        """Capture the boot, keeping each distinct frame, until the title or a fixed span.

        With a `title` guard, single grabs every TITLE_POLL seconds end at the
        first recognised title, or fail after TITLE_LIMIT. Without one, settled
        captures every MEASURE_BOOT_POLL seconds end after MEASURE_TITLE_SPAN.
        """
        title = _guards(guard, "title")
        started, last, n = time.monotonic(), "", 0
        while True:
            name = f"00-boot-{n:02d}"
            digest = capture(name, check=False, settle=not title)
            if title and digest and guard("title", shots / f"{name}.png"):
                result["events"][-1]["recognized"] = "title"
                return digest
            if digest and digest == last:
                for path in (shots / f"{name}.raw.png", shots / f"{name}.png"):
                    path.unlink(missing_ok=True)
                result["events"][-1]["kept"] = False
            elif digest:
                last, n = digest, n + 1
            elapsed = time.monotonic() - started
            if title and elapsed >= TITLE_LIMIT:
                raise RouteError(
                    f"title screen was not recognized within {TITLE_LIMIT:.0f}s")
            if not title and elapsed >= MEASURE_TITLE_SPAN:
                return last
            wait(TITLE_POLL if title else MEASURE_BOOT_POLL)

    try:
        receipt = guest.claim(holder, timeout=route_limit(30))
        if receipt != f"ok claimed by {holder}":
            raise RouteError(f"claim was not new: {receipt!r}; already yours is not a lane grant")
        result["claim"] = receipt
        log("claim", receipt=receipt)
        claimed = True
        guest.put(df0, remote0, timeout=route_limit(90))
        guest.put(df1, remote1, timeout=route_limit(90))
        copied = True
        if not _mute_proof(audio_proof):
            raise RouteError("the Windows VM audio mute proof expired before WinUAE start")
        start_attempted = True
        result["start"] = guest.start(holder, remote0, remote1,
                                      timeout=route_limit(60))
        log("start", receipt=result["start"])
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
                name = f"{n:02d}-{state}"
                if _guards(guard, state):
                    digest = until_guard(state, name, min_waits.get(state, 0),
                                         GUARD_POLL, GUARD_LIMIT)
                else:
                    wait(min_waits.get(state, 0))
                    digest = capture(name, check=False)
                if digest == previous:
                    result["events"].append({"unchanged": key, "step": n})
                    changed = False
                    break
                previous = digest
            result["route_changed"] = changed
        else:
            until_guard("title", "title", 0, TITLE_POLL, TITLE_LIMIT)
            # Leaving the credits with ESC can land on the party menu, which `P` opens.
            skip_first = landed["state"] == "party_menu" and steps[0][1] == "party_menu"
            previous_world = ""
            for n, (key, state, kind) in enumerate(steps, 1):
                if n == 1 and skip_first:
                    result["events"].append({"skipped": key, "step": n})
                    continue
                if kind == "answer":
                    run_answer()
                else:
                    guest.press(holder, key, timeout=route_limit(30))
                    result["events"].append({"key": key, "step": n})
                    log("write" if kind == "write" else "key", key=key, step=n, state=state)
                name = (f"{n:02d}-post_write" if kind == "write" and state == "loaded_menu"
                        else f"{n:02d}-{state}")
                if kind == "move":
                    first_wait = min_waits.get("world_after_move", 0)
                elif kind == "write":
                    first_wait = min_waits.get(state, POST_WRITE_WAIT)
                else:
                    first_wait = min_waits.get(state, 0)
                digest = reach(state, name, first_wait,
                               strict=not accept or state in strict_states)
                if kind == "move":
                    # Evidence only: the two saves judge the walk, never the picture.
                    result["events"][-1]["crop_changed"] = digest != previous_world
                if state == "world":
                    previous_world = digest
            result["completed"] = True
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        if not isinstance(exc, (RouteError, OSError, ValueError)):
            result["lost"] = result["error"]
            log("lost", reason=result["lost"])
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
                log("stop", receipt=result["stop"])
            except BaseException as exc:
                result["stop_error"] = f"{type(exc).__name__}: {exc}"
        if copied:
            for name, remote in (("df0", remote0), ("df1", remote1)):
                local = out / f"fetched-{name}.adf"
                try:
                    guest.get(remote, local, timeout=cleanup_limit(60))
                    result["fetched"][name] = _entry(local)
                    log("fetch", disk=name, **result["fetched"][name])
                except BaseException as exc:
                    result[f"fetch_{name}_error"] = f"{type(exc).__name__}: {exc}"
        if claimed and (not start_attempted or stopped):
            try:
                result["release"] = guest.release(
                    holder, timeout=cleanup_limit(30))
                log("release", receipt=result["release"])
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
                reading = _slot_reading(fetched, "B")
                result["slot_b_sha256"] = reading.get("sha256")
                if "decode_error" in reading:
                    result["slot_b_decode_error"] = reading["decode_error"]
                elif "inventory" in reading:
                    result["slot_b"] = {"inventory": reading["inventory"],
                                        "state": reading["place"]}
                if not measure:
                    result["menu_save_problems"] = menu_save_problems(
                        manifest, reading)
                if accept:
                    slot_d = _slot_reading(fetched, CAMP_SAVE_LETTER)
                    result["slot_d_sha256"] = slot_d.get("sha256")
                    result["camp_save_problems"] = menu_save_problems(
                        manifest, slot_d, letter=CAMP_SAVE_LETTER, check_place=False)
                    squares = sum(1 for *_, kind in steps if kind == "move")
                    walk = walk_verdict(manifest["state_a"], reading, slot_d, squares)
                    result["walk"] = walk
                    result["read"] = {
                        "place_before": manifest["state_a"],
                        "menu_save": reading.get("place"),
                        "place_after": slot_d.get("place"),
                        "place_changed": walk["place_changed"],
                        "squares_moved": walk["squares_moved"],
                        "verdicts": walk["verdicts"],
                    }
                    log("read", **result["read"])
                    allowed = {f"savgam{c}.sav".lower()
                               for c in ("A", letter, MENU_SAVE_LETTER, CAMP_SAVE_LETTER)}
                    result["extra_saves"] = sorted(
                        e.name for e in fetched.entries(fetched.lookup("/SAVE").block)
                        if e.name.lower().startswith("savgam")
                        and e.name.lower() not in allowed)
            except BaseException as exc:
                result["fetched_df0_error"] = f"{type(exc).__name__}: {exc}"
        if not measure:
            result.setdefault("menu_save_problems",
                              ["slot B was not read from the fetched boot disk"])
            result["success"] = menu_save_verdict(result, tuple(originals))
            if accept:
                result["read"] = result.get("read") or {
                    "verdicts": ["slots B and D were not read from the fetched boot disk"]}
                result["success"] = bool(
                    result["success"] and result["completed"] and not result["unguarded"]
                    and result.get("walk", {}).get("b_ok")
                    and result.get("walk", {}).get("d_ok")
                    and result.get("camp_save_problems") == []
                    and result.get("extra_saves") == [])
        else:
            result["success"] = bool(
                result.get("route_changed") and not result["error"]
                and result.get("df0_unchanged") and result.get("df1_unchanged")
                and result.get("slot_b_sha256", "absent") is None)
        result["elapsed_seconds"] = time.monotonic() - begun
        (out / "summary.json").write_text(json.dumps(result, indent=2,
                                                     sort_keys=True) + "\n")
        runlog.close()
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
                   help="screen guard JSON; required unless --measure, which "
                        "checks the states it names and settles the rest")
    r.add_argument("--measure", action="store_true",
                   help="capture and record; never presses a write key")
    r.add_argument("--route", default=None,
                   help="KEY:state,KEY:state; default is the built-in route")
    r.add_argument("--write-keys", default="B",
                   help="comma-separated keys that write; measure never presses them")
    r.add_argument("--audio-proof", required=True, type=pathlib.Path)
    r.add_argument("--attempt", default="recon1")
    r.add_argument("--holder", default=None)
    g = sub.add_parser("guard", help="add one state's static box from a measured crop "
                                     "to a guard JSON, refusing a box a neighbour shares")
    g.add_argument("--state", required=True)
    g.add_argument("--crop", required=True, type=pathlib.Path,
                   help="a 720x568 crop of the state, as recon saved it")
    g.add_argument("--box", required=True, help="X0,Y0,X1,Y1 inside the crop")
    g.add_argument("--unlike", type=pathlib.Path, action="append", default=[],
                   help="a crop of a neighbouring state the box must not match")
    g.add_argument("--out", required=True, type=pathlib.Path)
    g.add_argument("--replace", action="store_true",
                   help="overwrite the state's existing rule in --out")
    a = sub.add_parser("accept", help="guarded load, menu save, BEGIN, two squares, camp save "
                                      "and the two-save readback")
    a.add_argument("--manifest", required=True, type=pathlib.Path)
    a.add_argument("--guards", required=True, type=pathlib.Path)
    a.add_argument("--identity", required=True, type=pathlib.Path)
    a.add_argument("--journal-python", required=True,
                   help="an interpreter that can import numpy and PIL, for the journal answerer")
    a.add_argument("--audio-proof", required=True, type=pathlib.Path)
    a.add_argument("--attempt", default="accept1")
    a.add_argument("--holder", default=None)
    a.add_argument("--deadline", type=float, default=1800)
    sub.add_parser("spindisk-control", help="unavailable until the exact-output failure is measured")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            print(prepare(args.source, args.run_id))
            return 0
        if args.command == "guard":
            box = [int(n) for n in args.box.split(",")]
            rule = guard_rule(args.crop, box, args.state)
            for other in args.unlike:
                if _box_digest(other, box, args.state) == rule["sha256"]:
                    raise RouteError(f"{args.state} box {box} also matches {other}")
            if _box_is_uniform(args.crop, box, args.state):
                raise RouteError(f"{args.state} box {box} is one colour and would match "
                                 f"any screen showing it")
            rules = json.loads(args.out.read_text()) if args.out.exists() else {}
            if args.state in rules and not args.replace:
                raise RouteError(f"{args.out} already has a rule for {args.state}; "
                                 f"pass --replace to overwrite it")
            rules[args.state] = rule
            # Rename over the file so an interrupted write never leaves half a map.
            temp = args.out.with_name(args.out.name + ".tmp")
            try:
                temp.write_text(json.dumps(rules, indent=2, sort_keys=True) + "\n")
                os.replace(temp, args.out)
            finally:
                temp.unlink(missing_ok=True)
            print(json.dumps({args.state: rule}, sort_keys=True))
            return 0
        if args.command == "recon":
            if args.guards is None and not args.measure:
                raise RouteError("--guards is required unless --measure")
            guards = PixelGuards(args.guards) if args.guards else None
            route = parse_route(args.route) if args.route else ROUTE
            write_keys = parse_write_keys(args.write_keys)
            holder = args.holder or f"wish672-{uuid.uuid4().hex[:12]}"
            with terminating():
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
        if args.command == "accept":
            holder = args.holder or f"wish672-{uuid.uuid4().hex[:12]}"
            with terminating():
                result = run_recon(
                    args.manifest, guest=WinGuest(), guard=PixelGuards(args.guards),
                    identity=PixelGuards(args.identity), holder=holder,
                    audio_proof=args.audio_proof, attempt=args.attempt,
                    deadline_seconds=args.deadline, accept=True,
                    journal_python=args.journal_python,
                    min_waits={**default_min_waits(), **ACCEPT_MIN_WAITS})
            print(json.dumps({"success": result["success"], "error": result["error"],
                              "unguarded": result["unguarded"],
                              "summary": str(args.manifest.parent / args.attempt
                                             / "summary.json")}, sort_keys=True))
            for line in result["read"]["verdicts"]:
                print(line)
            return 0 if result["success"] else 1
        raise RouteError(f"{args.command} is unavailable until the measured route is reviewed")
    except (RouteError, OSError, ValueError) as exc:
        print(f"amigasecretsave: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
