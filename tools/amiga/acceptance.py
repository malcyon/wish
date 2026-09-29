#!/usr/bin/env python3
"""Prepare, measure and accept one Amiga title's load, inspect, move, save and read-back run under WinUAE."""

from __future__ import annotations

import argparse
import base64
import functools
import hashlib
import json
import pathlib
import re
import shutil
import stat
import sys
import time
import uuid
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from goldbox import amiga_adf, areas, geo  # noqa: E402
from tools.amiga import route_silver_blades  # noqa: E402
from tools.amiga.route import (  # noqa: E402
    ISSUE,
    TITLE_LIMIT,
    AmigaTitle,
    check_expect,
    parse_expect,
)
from tools.amiga.route_curse import (  # noqa: E402
    CURSE,
    CURSE_DISK_B_SHA256,
    CURSE_SOURCES,
    _prepare_curse,
)
from tools.amiga.route_darkness import (  # noqa: E402
    DARKNESS,
    DARKNESS_RELOAD,
    DARKNESS_UNSTARTED,
    DARKNESS_UNSTARTED_LOADED,
    _prepare_darkness,
    _prepare_darkness_reload,
)
from tools.amiga.route_pool import (  # noqa: E402
    POOL,
    POOL_SOURCES,
    _prepare_pool,
    pool_title_for,
)
from tools.amiga.route_silver_blades import (  # noqa: E402
    ACCEPT_ROUTE,
    CAMP_SAVE_LETTER,
    MENU_SAVE_LETTER,
    ROUTE,
    SILVER_BLADES_INTERSTITIALS,
    SLOT_LETTER,
    _silver_blades_problems,
    _slot_reading,
    journal_preflight,
    run_journal_answer,
)
from tools.amiga.screens import PixelGuards, _guards, _has_rule  # noqa: E402
from tools.amiga.staging import _entry, _verified_disk, sha256  # noqa: E402
from tools.amiga.winuaesession import (  # noqa: E402
    HOLDER,
    SHOT_SECONDS,
    RouteError,
    WinGuest,
    _mute_proof,
    terminating,
)
from tools.registry import evidence, scratch, specimens  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PUBLISHED_ISSUE = "677"
PUBLISHED_SOURCES = {
    ("ssb", "c64"): "38c11440e578227c1a240b740f362b1b69943d9897f42dc35ac39b17508872dc",
    ("ssb", "dos"): "b3515793dada24b6a85061f5c2fdc5555a45df40381ee0009e9fd54ba381fb72",
    ("curse", "c64"): "fdf74e5ff41fe0f90f8f9b150d966df276c4dc4e5ecd6829efee2fee9019acc1",
    ("curse", "dos"): "4e911c12a449a4ff1694aab6d918f120c176df66483e32428cb50454db8b03df",
}
#: Pinned Save As sources per issue a published disk-one run may be filed under.
PUBLISHED_SOURCES_BY_ISSUE = {
    PUBLISHED_ISSUE: PUBLISHED_SOURCES,
    "640": {
        ("curse", "c64"): "97099201a9c77ae43ab7d4605fd7a9dab2864333a5239177a41c5658e997007b",
        ("ssb", "c64"): "5bb68551effa8a0d37ebc5f103a664e71505a798190d14ba8efa7730dd30e8a9",
    },
}
PUBLISHED_ISSUE_TEXT = {
    PUBLISHED_ISSUE: (
        "#677 (Save As to the Amiga puts a Curse or Silver Blades party on a separate "
        "save disk that the game never reads while its own disk A is in DF0)"),
    "640": ("#640 (A Curse or Silver Blades party saved before BEGIN ADVENTURING "
            "cannot be converted at all)"),
}
PUBLISHED_DISKS = {
    "ssb": ("2f9ae86494561231dd1d70b350ae07b959c9f62642b64e9d4b57ffd23686ace4",
            route_silver_blades.DISK_B_SHA256, "/Secret", "Secret 1"),
    "curse": ("4bfb64d1ebcf53867b941412ce04eb248b43dadebe34769f73ffa1aa609002ed",
              CURSE_DISK_B_SHA256, "/Curse", "CurseA"),
}

# Single grabs every ~8-10 s in all against a bar that held still for at least 24 s.
TITLE_POLL = 2.0
MEASURE_BOOT_POLL = 10.0
MEASURE_TITLE_SPAN = 120.0
GUARD_POLL = 5.0
GUARD_LIMIT = 120.0
# A key pressed while the disk is being written is swallowed, so the screen
# after the write gets the same long first wait as the load picker.
POST_WRITE_WAIT = 20.0
BOOT_LOG = r"C:\Users\Public\Documents\Amiga Files\WinUAE\winuaebootlog.txt"

#: The most draws one boot may make; the route's own camp save is the first.
RULEBOOK_DRAWS_MAX = 15
#: Seconds one draw's question may take to answer, for the deadline check; an allowance, not a measurement.
DRAW_ANSWER_SECONDS = 60.0


class DrawCounter:
    """Stages the next camp save's question in the running game, through the private helper.

    `target` is an `AmigaTarget`. `lane_check` proves this run still holds the WinUAE lane and
    raises when it does not; it runs before every write.
    """

    def __init__(self, target: Any, savecount: Any, lane_check: Callable[[], Any]) -> None:
        self.target, self.savecount, self.lane_check = target, savecount, lane_check
        self.base: int | None = None

    def locate(self) -> None:
        """Find the running game once; a title that is not there fails here, before any save."""
        from tools.amiga.amigatarget import A4_BIAS  # noqa: PLC0415

        if self.base is None:
            self.base = self.target.locate() + A4_BIAS

    def stage(self) -> None:
        self.locate()
        try:
            self.lane_check()
        except Exception as exc:
            raise RouteError(f"the lane claim was not confirmed: {type(exc).__name__}: {exc}") from exc
        self.savecount.stage_live(self.target.read, self.target.write, self.base)


def _step_wait(min_waits: dict[str, float], state: str, kind: str) -> float:
    return min_waits.get(state, POST_WRITE_WAIT if kind == "write" else 0)


def _check_draws_fit(draws: int, steps: Any, min_waits: dict[str, float],
                     deadline_seconds: float) -> None:
    """Refuse a run whose draws cannot fit the route time, by the steps' minimum waits.

    The route itself is estimated by the sum of its minimum waits, and each further draw by
    its three steps' waits plus `DRAW_ANSWER_SECONDS`; the route time is the deadline less
    its cleanup reserve.
    """
    route = sum(_step_wait(min_waits, state, kind) for _, state, kind in steps)
    each = sum(_step_wait(min_waits, state, kind) for _, state, kind in steps[-3:]
               ) + DRAW_ANSWER_SECONDS
    needed = route + (draws - 1) * each
    available = deadline_seconds - min(300.0, deadline_seconds / 2)
    if needed > available:
        raise RouteError(f"{draws} rulebook draws need about {needed:.0f}s of route time "
                         f"and the deadline leaves {available:.0f}s")


def _diagnose_bytes(guest: Any, holder: str, address: int, length: int,
                    limit: Callable[[float], float]) -> tuple[bytes, list[dict[str, Any]]]:
    from automap.amiga import parse_memory_dump  # noqa: PLC0415

    reads = []
    data: dict[int, int] = {}
    for line_address in range(address & ~15, address + length, 16):
        receipt = guest.diagnose(holder, "DBG", "m", address=line_address,
                                 timeout=limit(20))
        reads.append(receipt)
        data.update(parse_memory_dump(receipt["reply"]))
    try:
        return bytes(data[n] for n in range(address, address + length)), reads
    except KeyError as exc:
        raise RouteError(f"Exec memory reply omitted {exc.args[0]:#x}") from exc


def _exec_sample(guest: Any, holder: str,
                 limit: Callable[[float], float]) -> dict[str, Any]:
    ptr, ptr_reads = _diagnose_bytes(guest, holder, 4, 4, limit)
    base = int.from_bytes(ptr, "big")
    if not base or base > 0xFFFFFFFF - 0x120:
        raise RouteError(f"ExecBase pointer is invalid: {base:#x}")
    values, value_reads = _diagnose_bytes(guest, holder, base + 0x114, 12, limit)
    return {"execbase": base, "this_task": int.from_bytes(values[:4], "big"),
            "idle": int.from_bytes(values[4:8], "big"),
            "disp": int.from_bytes(values[8:], "big"),
            "replies": ptr_reads + value_reads}


def _white_screen(path: pathlib.Path) -> bool:
    from PIL import Image  # noqa: PLC0415

    with Image.open(path) as image:
        return all(low >= 245 for low, _ in image.convert("RGB").getextrema())


def _run_diagnose(manifest_path: pathlib.Path, manifest: dict, title: AmigaTitle,
                  disks: dict, guest: Any, guard: Any, holder: str,
                  audio_proof: pathlib.Path, attempt: str, deadline: float,
                  boot_limit: float) -> dict[str, Any]:
    """Boot the published title without game input and preserve each read and cleanup receipt."""
    out = manifest_path.parent / attempt
    out.mkdir(parents=False, exist_ok=False)
    shots = scratch.ensure(out / "shots")
    remotes = {key: f"C:/Amiga/Disks/wish{title.issue}-{holder}-{key}.adf"
               for key in title.disk_keys}
    result: dict[str, Any] = {
        **evidence.git_state(REPO), "argv": sys.argv[1:], "diagnose": True,
        "accept": False, "measure": False, "success": False, "completed": False,
        "holder": holder, "input": str(manifest_path), "remotes": remotes,
        "events": [], "fetched": {}, "error": "", "deadline_seconds": deadline,
        "boot_limit_seconds": boot_limit,
    }
    begun = time.monotonic()
    end = begun + deadline
    claimed = started = stopped = config_staged = False

    def limit(seconds: float) -> float:
        left = end - time.monotonic()
        if left <= 0:
            raise RouteError("diagnose total deadline reached")
        return min(seconds, left)

    def cleanup_limit(seconds: float, minimum: float = 5.0) -> float:
        left = end - time.monotonic()
        if left < minimum:
            if left < 1:
                result["cleanup_after_deadline"] = True
            return min(seconds, minimum)
        return min(seconds, left)

    try:
        receipt = guest.claim(holder, timeout=limit(30))
        if receipt != f"ok claimed by {holder}":
            raise RouteError(f"claim was not new: {receipt!r}")
        claimed = True
        result["claim"] = receipt
        before_log = out / "winuaebootlog-before.txt"
        guest.get(BOOT_LOG, before_log, timeout=limit(30))
        result["boot_log_before"] = _entry(before_log)
        for key, path in disks.items():
            guest.put(path, remotes[key], timeout=limit(90))
        config_staged = True
        result["remote_config_path"] = WinGuest.private_config_path(holder)
        result["config"] = guest.stage_private_config(holder, timeout=limit(60))
        if not _mute_proof(audio_proof):
            raise RouteError("the Windows VM audio mute proof expired before WinUAE start")
        started = True
        result["start"] = guest.start(
            holder, *(None if key is None else remotes[key] for key in title.mounted),
            timeout=limit(60), options=title.options, config=result["config"]["path"])
        boot_started = time.monotonic()
        # Stop, two disk fetches, boot-log fetch, config removal and release each
        # have their own bounded call; keep their full allowance after the boot.
        boot_end = min(boot_started + boot_limit, end - 240)
        if boot_end <= boot_started:
            raise RouteError("diagnose has no time left for a boot and cleanup")

        def boot_limit_for(seconds: float) -> float:
            left = min(boot_end, end) - time.monotonic()
            if left <= 0:
                raise RouteError("diagnose boot deadline reached during a read")
            return min(seconds, left)

        result["readback"] = {
            key: guest.diagnose(holder, "CFG", key, timeout=boot_limit_for(20))
            for key in ("gfx_api", "floppy0", "floppy1")}
        expected = {"gfx_api": "directdraw", "floppy0": remotes["df0"].replace("/", "\\"),
                    "floppy1": remotes["df1"].replace("/", "\\")}
        for key, wanted in expected.items():
            if result["readback"][key]["reply"] != f"200 \n{wanted}":
                raise RouteError(f"guest {key} readback differs from the private run")
        n = 0
        sampled = False
        while time.monotonic() < boot_end:
            name = f"00-boot-{n:02d}"
            raw, crop = shots / f"{name}.raw.png", shots / f"{name}.png"
            remaining = boot_end - time.monotonic()
            if remaining <= 0:
                break
            shown = guest.grab(name, raw, crop, timeout=boot_limit_for(min(SHOT_SECONDS, remaining)))
            event = {"state": name, "raw": str(raw), "raw_sha256": sha256(raw),
                     "crop": str(crop) if shown else None}
            if shown:
                event["crop_sha256"] = sha256(crop)
                if guard("title", crop):
                    event["recognized"] = "title"
                    result["events"].append(event)
                    result["completed"] = True
                    break
                for other in getattr(guard, "rules", {}):
                    if other != "title" and guard(other, crop):
                        event["recognized"] = other
                        if other != "credits":
                            result["events"].append(event)
                            raise RouteError(f"recognized {other} before the title")
                        break
            result["events"].append(event)
            elapsed = time.monotonic() - boot_started
            if shown and elapsed >= 120 and not sampled and _white_screen(crop):
                sampled = True
                result["white_probe"] = {"elapsed_seconds": elapsed,
                                         "status": guest.status(timeout=boot_limit_for(20))}
                first = _exec_sample(guest, holder, boot_limit_for)
                result["white_probe"]["first"] = first
                time.sleep(min(1, boot_limit_for(1)))
                second = _exec_sample(guest, holder, boot_limit_for)
                result["white_probe"]["second"] = second
            n += 1
            time.sleep(min(TITLE_POLL, max(0, boot_end - time.monotonic())))
        if not result["completed"]:
            raise RouteError(f"title screen was not recognized within {boot_limit:.0f}s")
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if started:
            try:
                result["stop"] = guest.stop(holder, timeout=cleanup_limit(30, minimum=20))
                stopped = True
            except BaseException as exc:
                result["stop_error"] = f"{type(exc).__name__}: {exc}"
        if claimed:
            for key, remote in remotes.items():
                local = out / f"fetched-{key}.adf"
                try:
                    guest.get(remote, local, timeout=cleanup_limit(60))
                    result["fetched"][key] = _entry(local)
                except BaseException as exc:
                    result[f"fetch_{key}_error"] = f"{type(exc).__name__}: {exc}"
            if started:
                try:
                    bootlog = out / "winuaebootlog.txt"
                    guest.get(BOOT_LOG, bootlog, timeout=cleanup_limit(30))
                    result["boot_log"] = _entry(bootlog)
                    content = bootlog.read_text(errors="replace")
                    result["boot_log_fresh"] = (result["boot_log"]["sha256"] !=
                                                result["boot_log_before"]["sha256"])
                    result["boot_log_matches_start"] = all(
                        path in content for path in (
                            result["config"]["path"],
                            remotes["df0"].replace("/", "\\"),
                            remotes["df1"].replace("/", "\\")))
                    if not result["boot_log_fresh"] or not result["boot_log_matches_start"]:
                        result["boot_log_error"] = "boot log is stale or names another launch"
                    result["gfx_api_rejected"] = bool(re.search(
                        r"Unknown value .* for option 'gfx_api'",
                        content, re.IGNORECASE))
                except BaseException as exc:
                    result["boot_log_error"] = f"{type(exc).__name__}: {exc}"
            if config_staged:
                try:
                    result["config_removed"] = guest.remove_private_config(holder,
                                                                             timeout=cleanup_limit(30))
                except BaseException as exc:
                    result["config_remove_error"] = f"{type(exc).__name__}: {exc}"
            if not started or stopped:
                try:
                    result["release"] = guest.release(holder, timeout=cleanup_limit(30))
                except BaseException as exc:
                    result["release_error"] = f"{type(exc).__name__}: {exc}"
        for key, path in disks.items():
            result[f"{key}_local_unchanged"] = sha256(path) == manifest["disks"][key]["sha256"]
            if key in result["fetched"]:
                result[f"{key}_fetched_unchanged"] = (
                    result["fetched"][key]["sha256"] == manifest["disks"][key]["sha256"])
        result["remote_config_dirty"] = config_staged and not bool(result.get("config_removed"))
        result["success"] = bool(result["completed"] and not result["error"] and stopped
                                 and result.get("release") and result.get("config_removed")
                                 and result.get("boot_log_fresh")
                                 and result.get("boot_log_matches_start")
                                 and not result.get("gfx_api_rejected")
                                 and all(result.get(f"{key}_fetched_unchanged") for key in disks))
        result["elapsed_seconds"] = time.monotonic() - begun
        (out / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result

# A state the guard map has must match or the run stops; the rest are measured
# by settling a capture and are marked unguarded.
IDENTITY_MESSAGES = {"sheet": "sheet shows another member",
                     "loaded_menu": "loaded_menu shows another party"}

def _input(manifest: dict, name: str) -> pathlib.Path:
    entry = manifest[name]
    path = pathlib.Path(entry["path"])
    if not path.is_file() or sha256(path) != entry["sha256"]:
        raise RouteError(f"{name} is missing or changed from preparation")
    return path


def _no_problems(reading: dict[str, Any], slot: str) -> list[str]:
    return []


def menu_save_problems(manifest: dict, reading: dict[str, Any], *, letter: str = "B",
                       check_place: bool = True, names: list[str] | None = None,
                       extra_problems: Any = _silver_blades_problems) -> list[str]:
    """What a save left different from the prepared party; empty means it matches.

    `names` replaces the inventory's member names as what the save must hold, and
    `extra_problems(reading, slot)` adds a title's own checks.
    """
    slot = f"slot {letter}"
    if reading.get("missing"):
        return [f"{slot} was not written"]
    if "decode_error" in reading:
        return [f"{slot} does not decode: {reading['decode_error']}"]
    problems = []
    if check_place and reading["place"] != manifest["state_a"]:
        problems.append(
            f"{slot} place {reading['place']} differs from {manifest['state_a']}")
    wanted = names if names is not None else [
        member["name"] for member in manifest["inventory_a"]["members"]]
    if reading["names"] != wanted:
        problems.append(f"{slot} members {reading['names']} differ from {wanted}")
    problems += extra_problems(reading, slot)
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
                 squares: int, *, control: str = "B", after: str = "D",
                 turn: str | None = None) -> dict[str, Any]:
    """Judge the two saves: `control`, saved before the walk, must be `before`; `after` must be `squares` on.

    The step routine wraps at 0 and 15, so `after` is compared modulo 16 along the
    control's facing, or along the opposite facing when `turn` is "about". The
    screen never judges movement.
    """
    verdicts: list[str] = []
    b_place, d_place = b.get("place"), d.get("place")
    b_ok = d_ok = walk_blocked = False
    if b_place is None:
        verdicts.append(_unreadable(control, b))
    elif b_place == before:
        b_ok = True
        verdicts.append(f"slot {control}: did not move")
    else:
        verdicts.append(f"slot {control}: moved from {_span(before, b_place)}, "
                        f"expected the prepared place")
    base = b_place or before
    squares_moved = None
    if d_place is None:
        verdicts.append(_unreadable(after, d))
    else:
        facing = geo.OPPOSITE[base["facing"]] if turn == "about" else base["facing"]
        dx, dy = geo.STEP[facing]
        expected = dict(base, facing=facing, x=(base["x"] + dx * squares) % 16,
                        y=(base["y"] + dy * squares) % 16)
        if d_place["area"] == base["area"] and d_place["facing"] == facing:
            along = (d_place["x"] - base["x"]) * dx + (d_place["y"] - base["y"]) * dy
            across = (d_place["x"] - base["x"]) * dy + (d_place["y"] - base["y"]) * dx
            # A wrapped step and a full lap cannot be told apart on 16 squares.
            if across == 0 or (across % 16 == 0):
                squares_moved = along % 16
        same_square = (d_place["area"], d_place["x"], d_place["y"]) == (
            base["area"], base["x"], base["y"])
        if turn == "about" and d_place == expected:
            d_ok = True
            unit = "square" if squares == 1 else "squares"
            verdicts.append(f"slot {after}: moved {squares} {unit} from "
                            f"{_span(base, d_place)}")
        elif d_place == base or (turn == "about" and same_square):
            d_ok = squares == 0 and turn is None
            # The party did not move although steps were asked for; a wall and an
            # unregistered key press read identically here, so this is not proof of a wall.
            walk_blocked = squares != 0
            verdicts.append(f"slot {after}: did not move")
        elif d_place == expected:
            d_ok = True
            unit = "square" if squares == 1 else "squares"
            verdicts.append(f"slot {after}: moved {squares} {unit} from "
                            f"{_span(base, d_place)}")
        else:
            verdicts.append(f"slot {after}: moved from {_span(base, d_place)}, "
                            f"expected {expected['x']},{expected['y']}")
    return {"verdicts": verdicts, "b_ok": b_ok, "d_ok": d_ok, "walk_blocked": walk_blocked,
            "place_changed": None if d_place is None else d_place != base,
            "squares_moved": squares_moved}


_ACCEPT_ONLY = frozenset({"continue", "journal"})


def place_state(place: dict[str, Any]) -> str:
    """The guard-map key for a decoded place; the area is left out because the screen does not show it."""
    return f"place_x{place['x']}_y{place['y']}_f{place['facing']}"


def _title_inputs(manifest: dict, title: AmigaTitle) -> tuple[dict, dict, str]:
    """The manifest's disks and registered images, each checked, and its loaded letter."""
    try:
        disks = {key: _input(manifest["disks"], key) for key in title.disk_keys}
        registered = {key: _input(manifest["registered"], key) for key in manifest["registered"]}
        loaded = manifest["loaded_letter"]
        manifest["state_a"], manifest["names_a"]  # noqa: B018
    except KeyError as exc:
        raise RouteError(f"the manifest lacks {exc.args[0]!r}") from exc
    if len({p.resolve() for p in (*disks.values(), *registered.values())}) != (
            len(disks) + len(registered)):
        raise RouteError("the manifest's disks and registered images must be separate files")
    if loaded in (title.control_letter, title.after_letter):
        raise RouteError(f"save letter {loaded} would overwrite the prepared slot")
    return disks, registered, loaded


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


def _clock_advanced(before: str, after: str) -> bool:
    """Accept a short forward interval, including a midnight rollover."""
    try:
        start_h, start_m = (int(part) for part in before.split(":"))
        end_h, end_m = (int(part) for part in after.split(":"))
    except (AttributeError, TypeError, ValueError):
        return False
    if not all(0 <= h < 24 and 0 <= m < 60 for h, m in ((start_h, start_m),
                                                      (end_h, end_m))):
        return False
    elapsed = ((end_h * 60 + end_m) - (start_h * 60 + start_m)) % (24 * 60)
    return 0 < elapsed <= 120


def _read_title(title: AmigaTitle, manifest: dict, result: dict[str, Any],
                out: pathlib.Path, disks: dict[str, pathlib.Path],
                registered: dict[str, pathlib.Path], kept_before: dict[str, dict],
                loaded: str, accept: bool, measure: bool, steps: tuple,
                reload: bool = False) -> None:
    """Compare the fetched disks with the manifest, read the saves and set `success`."""
    result["registered_unchanged"] = {
        key: sha256(path) == manifest["registered"][key]["sha256"]
        for key, path in registered.items()}
    result["working_unchanged"] = {
        key: sha256(path) == manifest["disks"][key]["sha256"] for key, path in disks.items()}
    result["disks_unchanged"] = {
        key: entry["sha256"] == manifest["disks"][key]["sha256"]
        for key, entry in result["fetched"].items()}
    if reload:
        _read_reload(title, manifest, result, out, kept_before, loaded)
        return
    if title.save_disk in result["fetched"]:
        try:
            fetched = _verified_disk(out / f"fetched-{title.save_disk}.adf")
            control = title.read_slot(fetched, title.control_letter)
            result["control_sha256"] = control.get("sha256")
            if not measure:
                result["menu_save_problems"] = menu_save_problems(
                    manifest, control, letter=title.control_letter,
                    names=manifest["names_a"], extra_problems=_no_problems)
            if accept:
                after = title.read_slot(fetched, title.after_letter)
                result["after_sha256"] = after.get("sha256")
                result["camp_save_problems"] = menu_save_problems(
                    manifest, after, letter=title.after_letter, check_place=False,
                    names=manifest["names_a"], extra_problems=_no_problems)
                squares = sum(1 for *_, kind in steps if kind == "move")
                walk = walk_verdict(manifest["state_a"], control, after, squares,
                                    control=title.control_letter, after=title.after_letter,
                                    turn=title.turn)
                verdicts = list(walk["verdicts"])
                expected = manifest.get("expected_after")
                result["expected_after_matches"] = None
                if expected is not None:
                    matches = after.get("place") == expected
                    result["expected_after_matches"] = matches
                    verdicts.append(
                        f"slot {title.after_letter} "
                        f"{'matches' if matches else 'differs from'} "
                        f"the game's own save after the same walk")
                result["walk"] = walk
                result["read"] = {
                    "place_before": manifest["state_a"], "menu_save": control.get("place"),
                    "place_after": after.get("place"),
                    "place_changed": walk["place_changed"],
                    "squares_moved": walk["squares_moved"], "verdicts": verdicts}
                result["kept_unchanged"] = {
                    c: title.slot_files(fetched, c) == before
                    for c, before in kept_before.items()}
                allowed = {*kept_before, title.control_letter, title.after_letter}
                result["extra_saves"] = sorted(set(title.slot_letters(fetched)) - allowed)
                if manifest.get("mode") == "published_disk_one":
                    published = _verified_disk(pathlib.Path(
                        manifest["registered"]["published"]["path"]))
                    before_files, after_files = _disk_files(published), _disk_files(fetched)
                    extension = "dat" if manifest["title"] == "curse" else "sav"
                    writable = {f"/save/savgam{c}.{extension}".lower()
                                for c in (title.control_letter, title.after_letter)}
                    result["published_files_preserved"] = (
                        set(after_files) == set(before_files) | writable and
                        all(after_files.get(path) == data for path, data in before_files.items()
                            if path not in writable))
                    result["control_clock_matches"] = control.get("clock") == manifest["clock_a"]
                    result["after_clock_advanced"] = _clock_advanced(
                        manifest["clock_a"], after.get("clock"))
        except BaseException as exc:
            result["fetched_save_error"] = f"{type(exc).__name__}: {exc}"
    every_disk_fetched = set(result["fetched"]) == set(title.disk_keys)
    if measure:
        result["success"] = bool(
            result.get("route_changed") and not result["error"] and every_disk_fetched
            and all(result["disks_unchanged"].values())
            and result.get("control_sha256", "absent") is None)
        return
    result.setdefault("menu_save_problems",
                      [f"slot {title.control_letter} was not read from the fetched save disk"])
    result.setdefault("read", {"verdicts": [
        f"slots {title.control_letter} and {title.after_letter} were not read from the "
        f"fetched save disk"]})
    others = [k for k in title.disk_keys if k != title.save_disk]
    rest = bool(
        not result["error"] and result["completed"] and not result["unguarded"]
        and every_disk_fetched and all(result["registered_unchanged"].values())
        and all(result["working_unchanged"].values())
        # The game writes to the save disk, and to nothing else.
        and result["disks_unchanged"].get(title.save_disk) is False
        and all(result["disks_unchanged"].get(k) for k in others)
        and result["menu_save_problems"] == []
        and result.get("camp_save_problems") == []
        and result.get("walk", {}).get("b_ok")
        and result.get("expected_after_matches") is not False
        and bool(result.get("kept_unchanged")) == bool(kept_before)
        and all(result.get("kept_unchanged", {}).values())
        and result.get("extra_saves") == [])
    if manifest.get("mode") == "published_disk_one":
        rest = bool(rest and result.get("published_files_preserved")
                    and result.get("control_clock_matches")
                    and result.get("after_clock_advanced"))
    d_ok = bool(result.get("walk", {}).get("d_ok"))
    result["success"] = rest and d_ok
    result["substitute_walk_blocked"] = bool(
        "substitute" in manifest and result.get("walk", {}).get("walk_blocked"))
    result["passed_except_walk"] = bool(result["substitute_walk_blocked"] and rest)
    if result["substitute_walk_blocked"] and result.get("read"):
        clause = "; every other check passed" if result["passed_except_walk"] else ""
        result["read"]["verdicts"].append(
            f"slot {title.after_letter}: the substituted party did not move from its own "
            f"square, which may face a wall{clause}")


def _place_text(place: dict[str, Any]) -> str:
    return f"area {place['area']} {place['x']},{place['y']} facing {place['facing']}"


def _read_reload(title: AmigaTitle, manifest: dict, result: dict[str, Any],
                 out: pathlib.Path, kept_before: dict[str, dict], loaded: str) -> None:
    """Judge a run that only loads: no slot changed, and the screen shows the loaded slot's place and not the other's."""
    place, other = manifest["state_a"], manifest["other_place"]
    seen = result.get("reload", {})
    if title.save_disk in result["fetched"]:
        try:
            fetched = _verified_disk(out / f"fetched-{title.save_disk}.adf")
            result["kept_unchanged"] = {
                c: title.slot_files(fetched, c) == before for c, before in kept_before.items()}
            result["extra_saves"] = sorted(set(title.slot_letters(fetched)) - set(kept_before))
        except BaseException as exc:
            result["fetched_save_error"] = f"{type(exc).__name__}: {exc}"
    verdicts = [
        f"slot {loaded}: reloaded at {_place_text(place)}" if seen.get("shown") is True
        else f"slot {loaded}: {_place_text(place)} is not on the screen"]
    other_letter = manifest["other_letter"]
    if seen.get("other_shown") is None:
        verdicts.append(f"slot {other_letter}: {_place_text(other)} was not compared with the screen")
    elif seen["other_shown"]:
        verdicts.append(f"slot {other_letter}: {_place_text(other)} is also on the screen")
    else:
        verdicts.append(f"slot {other_letter}: {_place_text(other)} is not on the screen")
    result["read"] = {"loaded_letter": loaded, "place_loaded": place, "other_place": other,
                      "verdicts": verdicts}
    result["success"] = bool(
        not result["error"] and result["completed"] and not result["unguarded"]
        and set(result["fetched"]) == set(title.disk_keys)
        and all(result["registered_unchanged"].values())
        and all(result["working_unchanged"].values())
        # The reload writes nothing, so every disk, the save disk included, comes back as it went in.
        and all(result["disks_unchanged"].get(k) for k in title.disk_keys)
        and bool(result.get("kept_unchanged")) and all(result["kept_unchanged"].values())
        and result.get("extra_saves") == []
        and seen.get("shown") is True and seen.get("other_shown") is False)


_FULL_TITLES = {"pool": "Pool of Radiance", "curse": "Curse of the Azure Bonds",
                "ssb": "Secret of the Silver Blades"}
SPECIMEN_ISSUE = re.compile(r"#(\d+) \(.+\)")


def _slug(value: str) -> str:
    # Base32 is reversible and uses only the specimen registry's lowercase slug alphabet.
    return base64.b32encode(value.encode()).decode().rstrip("=").lower()


def _register_fetched(specimen_name: str, full_title: str, issue: str, what: str,
                      fetched: pathlib.Path) -> dict[str, str]:
    """Add a fetched save disk to the specimen tree, or find the identical one already there."""
    root = specimens.tree_root()
    source_hash = sha256(fetched)
    source = str(fetched.resolve())
    existing = next((entry for entry in specimens.list_specimens(root)
                     if entry.get("name") == specimen_name and entry.get("platform") == "amiga"
                     and entry.get("title") == full_title), None)
    if existing is None:
        directory = specimens.add(
            "amiga", specimen_name, [fetched], title=full_title, issue=issue,
            made_by="WinUAE, driven by tools/amiga/acceptance.py", what=what,
            command=" ".join(sys.argv), root=root)
    else:
        if (existing.get("source") != source or
                existing.get("sha256", {}).get(fetched.name) != source_hash):
            raise RouteError(f"specimen name collision: {specimen_name}")
        directory = existing["_provenance"].parent
    saved = directory / fetched.name
    if sha256(saved) != source_hash:
        raise RouteError("preserved specimen differs from fetched DF0")
    return {"path": str(saved), "sha256": source_hash,
            "provenance": str(directory / specimens.PROVENANCE_NAME)}


def _preserve_published(manifest_path: pathlib.Path, attempt: str, name: str,
                        fetched: pathlib.Path, issue: str = PUBLISHED_ISSUE) -> dict[str, str]:
    """Register a successful game's fetched DF0 before its lane is released."""
    run_id = manifest_path.parent.name
    return _register_fetched(
        f"wish-{issue}-{name}-{_slug(run_id)}-{_slug(attempt)}", _FULL_TITLES[name],
        PUBLISHED_ISSUE_TEXT[issue],
        f"Run {run_id!r}, attempt {attempt!r}: loaded the published disk-one "
        "party, walked and saved slots C and F in game", fetched)


def _preserve_substituted(manifest_path: pathlib.Path, manifest: dict, attempt: str,
                          title: AmigaTitle, issue: str, fetched: pathlib.Path) -> dict[str, str]:
    """Register the save disk of a successful substituted run.

    The game wrote the control and after slots; Wish wrote the loaded slot by importing
    the substitute's, so the provenance says so. Only claims the run's success test checks:
    the kept slots and the loaded slot are unchanged and no other save letter appeared.
    """
    run_id = manifest_path.parent.name
    number = SPECIMEN_ISSUE.fullmatch(issue).group(1)
    sub, pinned = manifest["substitute"], manifest["registered"]["specimen"]
    kept = ", ".join(title.kept_letters)
    what = (
        f"Run {run_id!r}, attempt {attempt!r}: the save disk fetched after the game loaded "
        f"slot {manifest['loaded_letter']}, saved slot {title.control_letter}, walked and "
        f"saved slot {title.after_letter}. The game wrote slots {title.control_letter} and "
        f"{title.after_letter}. Slot {manifest['loaded_letter']} was written by Wish: it is "
        f"slot {sub['letter']} of {sub['path']} (SHA-256 {sub['sha256']} as recorded when "
        f"`prepare --substitute` imported it; the run did not hash it again), imported into a copy of the pinned specimen {pinned['path']} "
        f"(SHA-256 {pinned['sha256']}). Slots {kept} are that specimen's own; the run found "
        f"them and slot {manifest['loaded_letter']} unchanged and no other save letter. "
        "Files outside the slots were not checked.")
    return _register_fetched(
        f"wish-{number}-{manifest['title']}-{_slug(run_id)}-{_slug(attempt)}",
        _FULL_TITLES[manifest["title"]], issue, what, fetched)


class _LaneWatch:
    """Wraps the lane so that an error can be tied to the call `route_limit` cut short."""

    SLACK = 1.0

    def __init__(self, guest: Any) -> None:
        self._guest = guest
        self.shortened: float | None = None
        self._failed: tuple[BaseException, float, float] | None = None

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._guest, name)
        if not callable(attr):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            limit, self.shortened, self._failed = self.shortened, None, None
            began = time.monotonic()
            try:
                return attr(*args, **kwargs)
            except BaseException as exc:
                if limit is not None and kwargs.get("timeout") == limit:
                    self._failed = (exc, limit, time.monotonic() - began)
                raise
        return call

    def timed_out(self, exc: BaseException) -> bool:
        """True when `exc` came from the shortened call and it used the time it was given."""
        if self._failed is None or self._failed[0] is not exc:
            return False
        _, limit, used = self._failed
        return used >= limit - min(self.SLACK, limit / 2)


def run_recon(manifest_path: pathlib.Path, *, guest: Any, guard: Any = None,
              holder: str, audio_proof: pathlib.Path, attempt: str = "recon1",
              deadline_seconds: float = 1800,
              route: tuple[tuple[str, str], ...] = ROUTE,
              write_keys: tuple[str, ...] = ("B",),
              min_waits: dict[str, float] | None = None,
              measure: bool = False, accept: bool = False,
              identity: Any = None, journal_python: str | None = None,
              answer: Any = None, preflight: Any = None,
              title: AmigaTitle | None = None, reload: bool = False,
              published_disk_one: bool = False, published_name: str | None = None,
              preserve_specimen: bool = False, specimen_issue: str | None = None,
              diagnose: bool = False, boot_limit: float = 300,
              rulebook_draws: int | None = None, target: Any = None,
              lane_check: Callable[[], Any] | None = None) -> dict[str, Any]:
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

    `rulebook_draws` (Silver Blades accept only) makes that many camp saves in one boot: the
    route's own, then each further one after the private helper's `stage_live` has run on
    `target` (an `AmigaTarget`), once `lane_check` has confirmed the lane claim. A draw that
    reaches EXIT GAME with no question fails the run; `result["rulebook"]` lists each. The
    run is refused before the claim when the deadline cannot cover the draws.

    `reload` runs a title with no save letters: it loads the manifest's `loaded_letter`, walks
    the route, then waits for the screen to show that slot's place (`place_state` of `state_a`)
    and not the other slot's (`other_place`), and writes nothing.

    With a `title`, the route, the disks, the interstitials and the readings come
    from its description, and the run is exactly one of `accept`, `measure` and `reload`;
    without one every line is Silver Blades'. The manifest of a title is
    `{"disks": {key: {path, sha256}}, "registered": {key: {path, sha256}},
    "loaded_letter", "state_a", "names_a"}` and optionally `"expected_after"`.
    """
    if guard is None and not measure:
        raise RouteError("a screen guard is required unless measuring")
    preserve_message = "specimen preservation requires a published disk-one or substituted accept"
    if preserve_specimen and not (accept and (published_disk_one or title is not None)):
        raise RouteError(preserve_message)
    if specimen_issue is not None and (not preserve_specimen or published_disk_one):
        raise RouteError("--specimen-issue goes with a substituted --preserve-specimen only")
    if title is not None:
        if not isinstance(title, AmigaTitle):
            raise RouteError("title must be an AmigaTitle")
        if reload and (accept or measure):
            raise RouteError("reload is a mode of its own, apart from accept and measure")
        if not reload and not diagnose and accept == measure:
            raise RouteError("a title run is either accept or measure")
        if not diagnose and reload != (title.control_letter is None):
            raise RouteError("only a title with no save letters is reloaded, and it runs only "
                             "as a reload")
        if route != ROUTE or write_keys != ("B",):
            raise RouteError("a title brings its own route and write keys")
    if reload and title is None:
        raise RouteError("reload needs a title")
    counter = None
    if rulebook_draws is not None:
        if not accept or title is not None:
            raise RouteError("rulebook draws are for the Silver Blades accept route")
        if not 1 <= rulebook_draws <= RULEBOOK_DRAWS_MAX:
            raise RouteError(f"rulebook draws are 1 to {RULEBOOK_DRAWS_MAX}")
        if rulebook_draws > 1:
            if target is None or lane_check is None:
                raise RouteError("rulebook draws need a memory target and a lane check")
            savecount = route_silver_blades._load_savecount()
            if not (hasattr(savecount, "stage_live") and hasattr(savecount, "SaveCountError")):
                raise RouteError("the private savecount module lacks stage_live or SaveCountError")
            counter = DrawCounter(target, savecount, lane_check)
    if accept or reload:
        if measure:
            raise RouteError("accept and measure are separate modes")
        if title is None:
            if route != ROUTE:
                raise RouteError("accept walks its own route")
            for letter in (MENU_SAVE_LETTER, CAMP_SAVE_LETTER):
                if letter in (SLOT_LETTER, "A"):
                    raise RouteError(f"save letter {letter} would overwrite the prepared slot")
        identity_states = (IDENTITY_MESSAGES if title is None else
                           [s for s in IDENTITY_MESSAGES
                            if s in {state for _, state, _ in title.route}])
        if identity_states and (
                identity is None or not all(_has_rule(identity, s) for s in identity_states)):
            raise RouteError(f"identity map lacks {sorted(identity_states)}")
        if accept and title is None and not journal_python and answer is None:
            raise RouteError("accept needs a journal interpreter")
    if diagnose:
        if (accept or measure or reload or not published_disk_one or published_name != "ssb"
                or title is None or boot_limit <= 0 or boot_limit > 300
                or deadline_seconds > 600 or deadline_seconds <= boot_limit):
            raise RouteError("diagnose needs the published Silver Blades title and bounded limits")
        if not _guards(guard, "title"):
            raise RouteError("diagnose needs a title screen guard")
    if not measure and not diagnose:
        needed = (("title", *(s for _, s in route)) if title is None
                  else ("title", *sorted(title.strict)))
        missing = [s for s in dict.fromkeys(needed) if not _guards(guard, s)]
        if missing:
            raise RouteError(f"screen guard map lacks {missing}")
    if title is not None and measure:
        # Measure mode settles a state with no guard rule and goes on, so a DF0 insert would
        # swap the disk on an unrecognised screen.
        steps = title.measure_route
        for (key, _, kind), (_, before, _) in zip(steps[1:], steps):
            if kind == "insert" and key[0] == 0 and not _guards(guard, before):
                raise RouteError(f"screen guard map lacks {before!r}: a DF0 insert needs a "
                                 f"guard on the prompt before it")
        for screen, action, _, _ in title.interstitials:
            if action[0] == "insert" and action[1] == 0 and not _guards(guard, screen):
                raise RouteError(f"screen guard map lacks {screen!r}: a DF0 insert needs a "
                                 f"guard on the prompt")
    if accept and journal_python is not None and (title is None or published_disk_one):
        (preflight or journal_preflight)(journal_python)
    min_waits = {**(title.min_waits if title else {}), **(min_waits or {})}
    if counter is not None:
        _check_draws_fit(rulebook_draws, ACCEPT_ROUTE, min_waits, deadline_seconds)
    write_keys = tuple(k.upper() for k in write_keys)
    if not all(write_keys):
        raise RouteError("write keys must not contain an empty entry")
    if measure and title is None:
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
    if published_disk_one:
        if published_name is None:
            raise RouteError("published disk-one mode needs its CLI title")
        manifest, expected_title = _published_manifest(manifest_path, published_name)
        if (title is None or title.issue != expected_title.issue or
                title.route != expected_title.route or
                title.mounted != expected_title.mounted or
                title.save_disk != expected_title.save_disk):
            raise RouteError("the selected title route differs from the published manifest")
    elif manifest.get("mode") == "published_disk_one":
        raise RouteError("a published disk-one manifest needs --published-disk-one")
    if preserve_specimen and not published_disk_one:
        if ("substitute" not in manifest or manifest.get("title") not in _FULL_TITLES
                or "specimen" not in manifest.get("registered", {})
                or specimen_issue is None or not SPECIMEN_ISSUE.fullmatch(specimen_issue)):
            raise RouteError(preserve_message + ", and a substituted one needs --specimen-issue "
                             '"#N (title)" naming its issue')
    if title is POOL:
        title = pool_title_for(manifest)
    if title is not None:
        disks, registered, letter = _title_inputs(manifest, title)
        originals: dict[str, pathlib.Path] = {}
        save_before = _verified_disk(disks[title.save_disk])
        present = title.slot_letters(save_before)
        if letter not in present:
            raise RouteError(f"the save disk holds no slot {letter} to load")
        for taken in (title.control_letter, title.after_letter):
            if taken is not None and taken in present:
                raise RouteError(f"slot {taken} already exists on the save disk")
        if reload:
            try:
                wanted = [place_state(manifest["state_a"]), place_state(manifest["other_place"])]
                other = manifest["other_letter"]
            except KeyError as exc:
                raise RouteError(f"the manifest lacks {exc.args[0]!r}") from exc
            except TypeError as exc:
                raise RouteError("the manifest's reload place is not a mapping") from exc
            if other not in present:
                raise RouteError(f"the save disk holds no slot {other} to compare")
            missing = [k for k in wanted if not _guards(guard, k)]
            if missing:
                raise RouteError(f"screen guard map lacks {missing}")
        kept_before = {c: title.slot_files(save_before, c)
                       for c in (*title.kept_letters, letter)}
        if published_disk_one:
            if sha256(disks["df0"]) != manifest["registered"]["published"]["sha256"]:
                raise RouteError("working DF0 differs from the exact published image")
            if sha256(disks["df1"]) != manifest["registered"]["disk_two"]["sha256"]:
                raise RouteError("working DF1 differs from registered disk 2")
        if diagnose:
            return _run_diagnose(manifest_path, manifest, title, disks, guest, guard,
                                 holder, audio_proof, attempt, deadline_seconds, boot_limit)
    else:
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
        # A save count edits only the staged slot, so the published one has its own digest.
        published_sha = manifest.get("published_slot_sha256", manifest["slot_sha256"])
        if hashlib.sha256(slot).hexdigest() != published_sha:
            raise RouteError("the published slot differs from the manifest")
        df0_disk = _verified_disk(df0)
        staged = df0_disk.read_file(f"/SAVE/savgam{letter}.sav")
        if hashlib.sha256(staged).hexdigest() != manifest["slot_sha256"]:
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
    if title is None:
        remotes = {"df0": f"C:/Amiga/Disks/wish672-{holder}-df0.adf",
                   "df1": f"C:/Amiga/Disks/wish672-{holder}-df1.adf"}
        local_disks = {"df0": df0, "df1": df1}
    else:
        remotes = {key: f"C:/Amiga/Disks/wish{title.issue}-{holder}-{key}.adf"
                   for key in title.disk_keys}
        local_disks = disks
    result: dict[str, Any] = {
        **evidence.git_state(REPO), "argv": sys.argv[1:],
        "success": False, "holder": holder, "input": str(manifest_path),
        "events": [], "error": "", "fetched": {},
        "deadline_seconds": deadline_seconds, "measure": measure,
        "accept": accept, "completed": False, "lost": None, "unguarded": [],
    }
    if title is not None:
        result["remotes"] = remotes
        result["interstitials_without_guard"] = sorted(
            {screen for screen, *_ in title.interstitials if not _has_rule(guard, screen)})
        steps = title.route
        strict_states = {"title", *title.strict}
        table = title.interstitials
    else:
        result["remote_df0"], result["remote_df1"] = remotes["df0"], remotes["df1"]
        steps = ACCEPT_ROUTE if accept else (
            *((k, s, "key") for k, s in route), (write_keys[0], "loaded_menu", "write"))
        strict_states = {"title", *(s for _, s in ROUTE)}
        table = SILVER_BLADES_INTERSTITIALS
    title_limit = title.title_limit if title else TITLE_LIMIT
    boot_span = title.boot_span if title else MEASURE_TITLE_SPAN
    if counter is not None:
        result["rulebook"] = []
    landed: dict[str, Any] = {"state": None}
    if accept and answer is None and journal_python is not None:
        answer = functools.partial(run_journal_answer, journal_python)
    claimed = start_attempted = copied = stopped = False
    begun = time.monotonic()
    cleanup_window = min(300.0, deadline_seconds / 2)
    route_end = begun + deadline_seconds - cleanup_window
    total_end = begun + deadline_seconds
    cleanup_scale = cleanup_window / 300.0
    route_note = (f"route time of {deadline_seconds - cleanup_window:.0f}s: the "
                  f"{deadline_seconds:.0f}s deadline less a {cleanup_window:.0f}s cleanup reserve")
    watch = _LaneWatch(guest)
    guest = watch

    def log(event: str, **fields: Any) -> None:
        runlog.write(json.dumps({"event": event, "t": time.time(), **fields},
                                sort_keys=True) + "\n")
        runlog.flush()

    if title is not None:
        log("interstitials_without_guard", screens=result["interstitials_without_guard"])

    def route_limit(cap: float) -> float:
        left = route_end - time.monotonic()
        if left <= 0:
            raise RouteError(f"the {route_note} ran out before the next route action")
        watch.shortened = min(cap, left) if left < cap else None
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
                raise RouteError(f"the {route_note} cannot cover a {seconds:g}s minimum wait")
            time.sleep(seconds)

    def check_identity(state: str, crop: pathlib.Path) -> None:
        if identity is not None and _has_rule(identity, state) and not identity(state, crop):
            raise RouteError(IDENTITY_MESSAGES.get(
                state, f"{state} shows a party other than the prepared party"))

    def run_title_answer() -> None:
        """Answer a challenge screen with X and RET while its guard matches, three rounds at most."""
        if not _has_rule(guard, "journal"):
            raise RouteError("screen guard map lacks ['journal']")
        for round_ in range(4):
            name = f"journal-{round_}"
            if not capture(name, check=False, settle=False) or not guard(
                    "journal", shots / f"{name}.png"):
                return
            if round_ == 3:
                raise RouteError("the journal challenge is still on screen after three answers")
            for key in ("X", "RET"):
                guest.press(holder, key, timeout=route_limit(30))
                result["events"].append({"answer_key": key, "round": round_ + 1})
                log("answer", key=key, round=round_ + 1)
            wait(GUARD_POLL)

    def run_answer() -> None:
        """Run the journal answerer, again while it sees no challenge, until GUARD_LIMIT."""
        if title is not None and answer is None:
            return run_title_answer()
        started = time.monotonic()
        adf = (disks["df0"] if published_disk_one else originals["boot_source"])
        while True:
            try:
                code, line = answer(holder, adf, route_limit(180))
            except RouteError as exc:
                result["events"].append({"answer_failed": str(exc)})
                log("answer", error=str(exc))
                raise
            result["events"].append({"answer": line, "exit_code": code})
            log("answer", exit_code=code, line=line)
            if code == 0 and line == "answered":
                return
            if line != "no challenge on screen":
                raise RouteError(f"the journal answerer ended {code}: {line!r}")
            if time.monotonic() - started >= GUARD_LIMIT:
                raise RouteError(f"no journal challenge on screen within {GUARD_LIMIT:.0f}s")
            wait(GUARD_POLL)

    inserts_done: dict[str, int] = {}

    def keep_interstitial(crop: pathlib.Path, screen: str, n: int) -> None:
        """Copy the matched crop and its raw grab under their own names, before the screen is acted on.

        Only a run of several draws keeps them; a failed copy is logged and the run goes on.
        The next grab of the same state overwrites `crop`, so without this the screen that
        was answered is gone by the time anybody wants to see it.
        """
        try:
            while (kept := shots / f"{crop.stem}-{screen}-{n}.png").exists():
                n += 1
            shutil.copyfile(crop, kept)
            raw = crop.with_name(f"{crop.stem}.raw.png")
            if raw.exists():
                shutil.copyfile(raw, kept.with_name(f"{kept.stem}.raw.png"))
        except OSError as exc:
            log("interstitial_keep_error", screen=screen, error=f"{type(exc).__name__}: {exc}")
            return
        log("interstitial_kept", screen=screen, crop=str(kept))

    def interstitial(state: str, crop: pathlib.Path, done: dict[str, int],
                     inserts_only: bool = False) -> bool:
        """Act on a known screen that is not the wanted one, by the title's table.

        An `insert` row's limit counts across the whole run, since the disk stays in the drive.
        `inserts_only` leaves the key and answer rows alone, for a measure run that writes nothing.
        """
        for screen, action, waiting_for, limit in table:
            if (title is None and not accept and screen in _ACCEPT_ONLY) or (
                    title is not None and measure and action[0] == "answer") or (
                    inserts_only and action[0] != "insert"):
                continue
            count = inserts_done if action[0] == "insert" else done
            if (count.get(screen, 0) >= limit or not _has_rule(guard, screen)
                    or (waiting_for is not None and state not in waiting_for)
                    or not guard(screen, crop)):
                continue
            count[screen] = count.get(screen, 0) + 1
            if counter is not None:
                keep_interstitial(crop, screen, count[screen])
            if action[0] == "answer":
                result["events"].append({"interstitial": screen})
                log("interstitial", screen=screen, key=None)
                run_answer()
            elif action[0] == "insert":
                _, drive, disk_key, key = action
                insert(drive, disk_key, screen)
                press_key(screen, key)
            else:
                names = (action[1],) if isinstance(action[1], str) else action[1]
                for key in names:
                    press_key(screen, key)
            return True
        return False

    def press_key(screen: str, key: str) -> None:
        guest.press(holder, key, timeout=route_limit(30))
        result["events"].append({"interstitial": screen, "key": key})
        log("interstitial", screen=screen, key=key)

    def insert(drive: int, disk_key: str, why: Any) -> None:
        entry = (manifest if title is None else manifest["disks"])[disk_key]
        try:
            receipt = guest.insert(holder, drive, remotes[disk_key], timeout=route_limit(60),
                                   sha256=entry["sha256"])
        except BaseException as exc:
            result["events"].append({"insert": disk_key, "drive": drive, "for": why,
                                     "error": str(exc),
                                     "receipt": getattr(exc, "receipt", None)})
            raise
        result["events"].append({"insert": disk_key, "drive": drive, "for": why,
                                 "receipt": receipt})
        log("insert", disk=disk_key, drive=drive, receipt=receipt)

    def settle_unguarded(state: str, name: str) -> str:
        """One settled capture of a state nobody has measured, marked as such."""
        digest = capture(name, check=False)
        result["events"][-1]["recognized"] = False
        if state not in result["unguarded"]:
            result["unguarded"].append(state)
        return digest

    def recognise(state: str, crop: pathlib.Path, done: dict[str, int]) -> str | None:
        """The state, or `party_menu` once `credits` is behind it, that the crop matches."""
        wanted = [state]
        if "credits" in done and _has_rule(guard, "party_menu"):
            wanted.append("party_menu")
        return next((s for s in wanted if guard(s, crop)), None)

    def until_guard(state: str, name: str, first_wait: float,
                    poll: float, limit: float, *, strict: bool = True) -> str:
        """Wait, then grab every `poll` seconds until the guard matches; keep the last crop.

        A state that is not `strict` and never matches falls back to a settled capture.
        """
        wait(first_wait)
        started = time.monotonic()
        done: dict[str, int] = {}
        crop = shots / f"{name}.png"
        while True:
            digest = capture(name, check=False, settle=False)
            if digest:
                hit = recognise(state, crop, done)
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
                missing = result.get("interstitials_without_guard")
                raise RouteError(f"{state} screen was not recognized within {limit:.0f}s;"
                                 f" kept {crop}"
                                 + (f"; the guard map has no rule for {missing}" if missing else ""))
            wait(poll)

    def reach(state: str, name: str, first_wait: float, *, strict: bool) -> str:
        if _guards(guard, state):
            limit = title.wait_limits.get(state, GUARD_LIMIT) if title else GUARD_LIMIT
            return until_guard(state, name, first_wait, GUARD_POLL, limit, strict=strict)
        wait(first_wait)
        done: dict[str, int] = {}
        digest = settle_unguarded(state, name)
        for again in range(1, 4):
            if not interstitial(state, shots / f"{name}.png", done, inserts_only=measure):
                break
            wait(first_wait)
            digest = settle_unguarded(state, f"{name}-after-{again}")
        return digest

    def perform(key: Any, kind: str, state: str, n: int) -> None:
        """Press one route step's key, after putting a disk in the drive when it is an `insert`."""
        if kind == "insert":
            drive, disk_key, key = key
            insert(drive, disk_key, n)
        guest.press(holder, key, timeout=route_limit(30))
        result["events"].append({"key": key, "step": n})
        log("write" if kind == "write" else "key", key=key, step=n, state=state)

    def measure_boot() -> str:
        """Capture the boot, keeping each distinct frame, until the title or a fixed span.

        With a `title` guard, single grabs every TITLE_POLL seconds act on the title's
        own interstitial table, as accept mode's boot wait does, until a grab recognises
        `title` (or `party_menu`, once `credits` is behind it), or the wait fails after
        TITLE_LIMIT. Without one, settled captures every MEASURE_BOOT_POLL seconds end
        after MEASURE_TITLE_SPAN.
        """
        title = _guards(guard, "title")
        started, last, n = time.monotonic(), "", 0
        done: dict[str, int] = {}
        while True:
            name = f"00-boot-{n:02d}"
            digest = capture(name, check=False, settle=not title)
            event = result["events"][-1]
            if title and digest:
                crop = shots / f"{name}.png"
                hit = recognise("title", crop, done)
                if hit:
                    event["recognized"] = hit
                    landed["state"] = hit
                    return digest
                interstitial("title", crop, done)
            if digest and digest == last:
                for path in (shots / f"{name}.raw.png", shots / f"{name}.png"):
                    path.unlink(missing_ok=True)
                event["kept"] = False
            elif digest:
                last, n = digest, n + 1
            elapsed = time.monotonic() - started
            if title and elapsed >= title_limit:
                raise RouteError(
                    f"title screen was not recognized within {title_limit:.0f}s")
            if not title and elapsed >= boot_span:
                return last
            wait(TITLE_POLL if title else MEASURE_BOOT_POLL)

    def rulebook_draws_after_route() -> None:
        """Each further draw: stage the question, camp-save to slot D, answer it, camp again."""
        save, write, back = steps[-3:]
        n = len(steps)
        for draw in range(2, rulebook_draws + 1):
            record = {"draw": draw, "asked": False, "answer": None, "exit_game": False}
            result["rulebook"].append(record)
            try:
                counter.stage()
            except counter.savecount.SaveCountError as exc:
                # The helper's own message can carry private detail, so only its type is kept.
                log("draw_error", draw=draw, error=type(exc).__name__)
                raise RouteError(f"draw {draw}: {type(exc).__name__}") from None
            except Exception as exc:
                log("draw_error", draw=draw, error=type(exc).__name__)
                raise
            first = len(result["events"])
            try:
                for key, state, kind in (save, write, back):
                    n += 1
                    perform(key, kind, state, n)
                    reach(state, f"{n:02d}-{state}", _step_wait(min_waits, state, kind),
                          strict=True)
                    events = result["events"][first:]
                    record["asked"] = any(
                        e.get("interstitial") == "journal" and "key" not in e for e in events)
                    record["answer"] = next(
                        (e["answer"] for e in reversed(events) if "answer" in e), None)
                    if state == "exit_game":
                        record["exit_game"] = True
                        if not record["asked"]:
                            raise RouteError(f"draw {draw} reached exit_game with no question")
            finally:
                log("draw", **record)

    try:
        receipt = guest.claim(holder, timeout=route_limit(30))
        if receipt != f"ok claimed by {holder}":
            raise RouteError(f"claim was not new: {receipt!r}; already yours is not a lane grant")
        result["claim"] = receipt
        log("claim", receipt=receipt)
        claimed = True
        for name, local in local_disks.items():
            guest.put(local, remotes[name], timeout=route_limit(90))
        copied = True
        if not _mute_proof(audio_proof):
            raise RouteError("the Windows VM audio mute proof expired before WinUAE start")
        start_attempted = True
        if title is None:
            result["start"] = guest.start(holder, remotes["df0"], remotes["df1"],
                                          timeout=route_limit(60))
        else:
            result["start"] = guest.start(
                holder, *(None if key is None else remotes[key] for key in title.mounted),
                timeout=route_limit(60), options=title.options)
        log("start", receipt=result["start"])
        if measure:
            previous = measure_boot()
            changed = True
            steps_m = route if title is None else title.measure_route
            skip = 0
            if landed["state"] == "title":
                skip = next((i for i, s in enumerate(steps_m, 1) if s[1] == "title"), 0)
            elif landed["state"] == "party_menu" and steps_m and steps_m[0][1] == "party_menu":
                # Leaving the credits with ESC can land on the party menu, which `P` opens.
                skip = 1
            for n, step in enumerate(steps_m, 1):
                if n <= skip:
                    result["events"].append({"skipped": step[0], "step": n})
                    continue
                if title is None:
                    (key, state), kind = step, "key"
                    if key.upper() in write_keys:
                        result["events"].append({"skipped_write_key": key, "step": n})
                        changed = False
                        break
                    guest.press(holder, key, timeout=route_limit(30))
                    result["events"].append({"key": key, "step": n})
                else:
                    key, state, kind = step
                    if kind in ("write", "answer"):
                        # The measured route ends where the run would first write or answer.
                        result["events"].append({"skipped_write_key": key, "step": n})
                        break
                    perform(key, kind, state, n)
                name = f"{n:02d}-{state}"
                if title is not None:
                    digest = reach(state, name, min_waits.get(state, 0), strict=True)
                elif _guards(guard, state):
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
            until_guard("title", "title", 0, TITLE_POLL, title_limit)
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
                    perform(key, kind, state, n)
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
                    if counter is not None:
                        counter.locate()
            if counter is not None:
                rulebook_draws_after_route()
            if reload:
                # The world bar matched before this point, so the place needs no first wait.
                place, other = manifest["state_a"], manifest["other_place"]
                name = f"{len(steps) + 1:02d}-place"
                shown = result["reload"] = {
                    "letter": letter, "place": place, "shown": False,
                    "other_letter": manifest["other_letter"], "other_place": other,
                    "other_shown": None}
                digest = until_guard(place_state(place), name, 0, GUARD_POLL, GUARD_LIMIT)
                crop = shots / f"{name}.png"
                shown.update(shown=True, other_shown=bool(guard(place_state(other), crop)),
                             crop=str(crop), crop_sha256=digest)
                log("reload", **shown)
            result["completed"] = True
    except BaseException as exc:
        if (isinstance(exc, (RouteError, OSError)) and "route time" not in str(exc)
                and watch.timed_out(exc)):
            # A lane call cut short by the route time reports its own few seconds as a timeout.
            result["error_cause"] = f"{type(exc).__name__}: {exc}"
            timed_out = RouteError(f"the {route_note} ran out during a lane call")
            timed_out.__cause__ = exc
            exc = timed_out
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
            for name, remote in remotes.items():
                local = out / f"fetched-{name}.adf"
                try:
                    guest.get(remote, local, timeout=cleanup_limit(60))
                    result["fetched"][name] = _entry(local)
                    log("fetch", disk=name, **result["fetched"][name])
                except BaseException as exc:
                    result[f"fetch_{name}_error"] = f"{type(exc).__name__}: {exc}"
        if preserve_specimen:
            try:
                _read_title(title, manifest, result, out, disks, registered,
                            kept_before, letter, accept, measure, steps, reload)
                if result["success"]:
                    if not stopped:
                        raise RouteError("guest did not stop before specimen preservation")
                    fetched = out / f"fetched-{title.save_disk}.adf"
                    result["specimen"] = (
                        _preserve_published(manifest_path, attempt, published_name, fetched,
                                            manifest.get("issue", PUBLISHED_ISSUE))
                        if published_disk_one else _preserve_substituted(
                            manifest_path, manifest, attempt, title, specimen_issue, fetched))
                    problems = specimens.check_specimens(specimens.tree_root())
                    if problems:
                        raise RouteError("specimen check failed: " + "; ".join(problems))
                    log("specimen", **result["specimen"])
            except BaseException as exc:
                result["specimen_error"] = f"{type(exc).__name__}: {exc}"
                result["success"] = False
                log("specimen_error", error=result["specimen_error"])
        if claimed and (not start_attempted or stopped):
            try:
                result["release"] = guest.release(
                    holder, timeout=cleanup_limit(30))
                log("release", receipt=result["release"])
            except BaseException as exc:
                result["release_error"] = f"{type(exc).__name__}: {exc}"
                if preserve_specimen:
                    result["success"] = False
        if title is None:
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
                    # The game loads the staged slot, which a save count edits away from
                    # the published one, so the staged file is what must survive.
                    result["slot_unchanged"] = (
                        fetched.read_file(f"/SAVE/savgam{letter}.sav") == staged)
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
        elif not preserve_specimen:
            _read_title(title, manifest, result, out, disks, registered,
                        kept_before, letter, accept, measure, steps, reload)
        result["elapsed_seconds"] = time.monotonic() - begun
        (out / "summary.json").write_text(json.dumps(result, indent=2,
                                                     sort_keys=True) + "\n")
        runlog.close()
    return result


TITLES: dict[str, AmigaTitle] = {"pool": POOL, "curse": CURSE, "darkness": DARKNESS,
                                 "darkness-reload": DARKNESS_RELOAD,
                                 "darkness-unstarted": DARKNESS_UNSTARTED}

_PREPARE = {"pool": _prepare_pool, "curse": _prepare_curse, "darkness": _prepare_darkness,
            "darkness-reload": _prepare_darkness_reload,
            "darkness-unstarted": functools.partial(
                _prepare_darkness, loaded=DARKNESS_UNSTARTED_LOADED)}


def _name(title: AmigaTitle) -> str:
    for name, known in TITLES.items():
        if known is title:
            return name
    raise RouteError("that is not one of this module's titles")


#: Titles with a slot importer for their own save format.
_SUBSTITUTABLE = frozenset(
    source.name for source in (POOL_SOURCES, CURSE_SOURCES) if source.import_slot is not None)


def prepare(title: AmigaTitle, run_id: str, *, specimen: pathlib.Path | None = None,
            specimen_sha256: str | None = None, accept_summary: pathlib.Path | None = None,
            substitute: pathlib.Path | None = None, substitute_letter: str = "A",
            ) -> pathlib.Path:
    """Copy the title's registered images and specimen into a run folder, write `prepare.json`, and return it.

    Refuses when any pinned hash differs, the loaded slot does not decode, or a
    save letter the run writes already exists. Nothing registered is written.
    `darkness-reload` prepares from a game-written disk 3, so it requires `specimen`,
    `specimen_sha256` and `accept_summary`, and the other titles refuse the last two.
    `substitute`, only on a title in `_SUBSTITUTABLE`, replaces the route's
    loaded slot with `substitute_letter`'s slot from that disk; every other
    file, and the specimen's own pin, are unaffected.
    """
    if not HOLDER.fullmatch(run_id):
        raise RouteError("run id must use letters, digits, dot, underscore or hyphen")
    name = _name(title)
    reload = name == "darkness-reload"
    given = (specimen, specimen_sha256, accept_summary)
    if reload and not all(given):
        raise RouteError("darkness-reload needs the disk 3, its SHA-256 and the accept summary")
    if not reload and (specimen_sha256 or accept_summary):
        raise RouteError(f"{name} takes no disk 3 hash or accept summary")
    if substitute is not None and name not in _SUBSTITUTABLE:
        raise RouteError(f"{name} takes no substitute slot")
    run = scratch.cache_dir("acceptance", ISSUE, run_id)
    if run.exists():
        raise RouteError(f"run folder already exists: {run}")
    if reload:
        manifest = _PREPARE[name](run, specimen, specimen_sha256, accept_summary)
    elif name in _SUBSTITUTABLE:
        manifest = _PREPARE[name](run, specimen, substitute=substitute,
                                  substitute_letter=substitute_letter)
    else:
        manifest = _PREPARE[name](run, specimen)
    path = run / "prepare.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def _disk_files(disk: amiga_adf.AmigaDisk) -> dict[str, bytes]:
    return {path.lower(): disk.read_file(path) for path, _ in disk.walk()}


def _published_title(name: str, letter: str, *, issue: str = PUBLISHED_ISSUE,
                     turn_about: bool | None = None,
                     items_screen: bool = True,
                     opening_scene: bool = False) -> AmigaTitle:
    if name == "curse":
        from tools.amiga.route_curse import published_title  # noqa: PLC0415
        return published_title(letter, issue=issue, turn_about=turn_about)
    if name == "ssb":
        return route_silver_blades.published_title(
            letter, issue=issue, turn_about=turn_about, items_screen=items_screen,
            opening_scene=opening_scene)
    raise RouteError("published disk one is only for Curse and Silver Blades")


def _items_screen(name: str, reading: dict) -> bool:
    """Whether the route visits the items screen: only Silver Blades' sheet ever lacks the button.

    The button is absent for a character with nothing, and the sheet the route
    opens is the party's first member, GUY DE VALOIS, first in the saved order too.
    """
    return name != "ssb" or reading["inventory"]["members"][0]["count"] > 0


def _opening_scene(name: str, place: dict | None) -> bool:
    """Whether the party has not set out, so the game shows its opening scene before the world."""
    if name != "ssb":
        return False
    start = areas.start_of(areas.SECRET_OF_THE_SILVER_BLADES)
    return place == {"area": start.area, "x": start.arrival.x, "y": start.arrival.y,
                     "facing": start.arrival.facing}


def _turn_about(name: str, letter: str, place: dict | None) -> bool:
    """Whether the route turns the party about before walking out of the start square."""
    if letter == "D":
        return True
    if name != "curse":
        return False
    start = areas.start_of(areas.CURSE_OF_THE_AZURE_BONDS)
    return place == {"area": start.area, "x": start.arrival.x, "y": start.arrival.y,
                     "facing": start.arrival.facing}


def _published_manifest(path: pathlib.Path, name: str) -> tuple[dict, AmigaTitle]:
    manifest = json.loads(path.read_text())
    if manifest.get("mode") != "published_disk_one" or manifest.get("issue") not in PUBLISHED_SOURCES_BY_ISSUE:
        raise RouteError("the manifest is not a published disk-one run")
    if manifest.get("title") != name:
        raise RouteError("the CLI title differs from the published manifest")
    port, letter = manifest["source_port"], manifest["loaded_letter"]
    if port not in ("c64", "dos") or letter != ("A" if port == "c64" else "D"):
        raise RouteError("the published source port and slot letter disagree")
    if manifest.get("source_sha256") != PUBLISHED_SOURCES_BY_ISSUE[manifest["issue"]].get(
            (name, port)):
        raise RouteError("the manifest source differs from the pinned specimen")
    turn_about = manifest.get("turn_about", letter == "D")
    if not isinstance(turn_about, bool):
        raise RouteError("the manifest turn_about is not a boolean")
    if "turn_about" in manifest and turn_about != _turn_about(name, letter,
                                                              manifest.get("state_a")):
        raise RouteError("the manifest turn_about disagrees with its recorded place")
    if name != "ssb" and "items_screen" in manifest:
        raise RouteError("only a Silver Blades manifest records items_screen")
    items_screen = manifest.get("items_screen", True)
    if not isinstance(items_screen, bool):
        raise RouteError("the manifest items_screen is not a boolean")
    opening_scene = _opening_scene(name, manifest.get("state_a"))
    if manifest.get("opening_scene", opening_scene) != opening_scene:
        raise RouteError("the manifest opening_scene disagrees with its recorded place")
    title = _published_title(name, letter, issue=manifest["issue"], turn_about=turn_about,
                             items_screen=items_screen, opening_scene=opening_scene)
    for key in ("source", "report", "published", "disk_one", "disk_two"):
        _input(manifest["registered"], key)
    if name == "ssb":
        recorded = title.read_slot(
            _verified_disk(_input(manifest["registered"], "published")), letter)
        if "inventory" not in recorded:
            cause = ("is missing" if recorded.get("missing") else
                     f"does not decode: {recorded.get('decode_error', 'no inventory')}")
            raise RouteError(f"the published slot {cause}, so items_screen cannot be checked")
        if items_screen != _items_screen(name, recorded):
            raise RouteError("the manifest items_screen disagrees with the published slot")
    disk1_pin, disk2_pin, executable, volume = PUBLISHED_DISKS[name]
    if (manifest["registered"]["disk_one"]["sha256"] != disk1_pin or
            manifest["registered"]["disk_two"]["sha256"] != disk2_pin):
        raise RouteError("the registered disks differ from the title's pins")
    if manifest["disks"]["df0"]["sha256"] != manifest["registered"]["published"]["sha256"]:
        raise RouteError("working DF0 is not the exact published image")
    if manifest["disks"]["df1"]["sha256"] != disk2_pin:
        raise RouteError("working DF1 differs from the pinned disk 2")
    report = json.loads(_input(manifest["registered"], "report").read_text())
    if (report.get("specimen_sha256") != manifest["source_sha256"] or
            pathlib.Path(report.get("specimen", "")) !=
            pathlib.Path(manifest["registered"]["source"]["path"]) or
            pathlib.Path(report.get("amiga_disk1", "")) !=
            pathlib.Path(manifest["registered"]["disk_one"]["path"]) or
            pathlib.Path(report.get("amiga_disk2", "")) !=
            pathlib.Path(manifest["registered"]["disk_two"]["path"]) or
            report.get("written") != report.get("save_as", {}).get("written") or
            len(report.get("written", [])) != 1 or
            pathlib.Path(report["written"][0]).name != "POOLSAVE.ADF" or
            pathlib.Path(report.get("save_as", {}).get("destination", "")) !=
            pathlib.Path(report["written"][0]) or
            manifest.get("published_source", {
                "path": report["written"][0],
                "sha256": manifest["registered"]["published"]["sha256"],
            }) != {
                "path": report["written"][0],
                "sha256": manifest["registered"]["published"]["sha256"],
            } or
            report.get("save_as", {}).get("slot") != letter or
            report.get("save_as", {}).get("to") != "amiga" or
            report.get("save_as", {}).get("refused") or
            report.get("save_as", {}).get("losses") or
            report.get("save_as", {}).get("dropped") or
            report.get("written_sha256") != {"POOLSAVE.ADF": manifest["registered"]["published"]["sha256"]}):
        raise RouteError("the Save As report differs from the published manifest")
    published = _verified_disk(_input(manifest["registered"], "published"))
    original = _verified_disk(_input(manifest["registered"], "disk_one"))
    if published.volume_name != volume or original.volume_name != volume:
        raise RouteError("the published image is not the title's disk 1")
    slot_path = f"/SAVE/savgam{letter}.{'dat' if name == 'curse' else 'sav'}".lower()
    old, new = _disk_files(original), _disk_files(published)
    if (set(new) != set(old) | {slot_path} or
            any(new.get(key) != value for key, value in old.items() if key != slot_path) or
            set(path.lower() for path, _ in published.walk_dirs()) !=
            set(path.lower() for path, _ in original.walk_dirs()) or
            published.to_bytes()[:1024] != original.to_bytes()[:1024] or
            executable.lower() not in new or "/save/spindisk" not in new):
        raise RouteError("the published image differs from disk 1 outside the converted slot")
    if new[slot_path] == old.get(slot_path):
        raise RouteError("the published slot was not converted")
    reading = title.read_slot(published, letter)
    if (reading.get("place") != manifest["state_a"] or
            reading.get("names") != manifest["names_a"] or
            reading.get("clock") != manifest["clock_a"]):
        raise RouteError("the published slot differs from the prepared party")
    return manifest, title


def prepare_published(name: str, run_id: str, report_path: pathlib.Path,
                      issue: str = PUBLISHED_ISSUE) -> pathlib.Path:
    """Preserve and check the exact Save As disk one before any guest run."""
    if not HOLDER.fullmatch(run_id):
        raise RouteError("run id must use letters, digits, dot, underscore or hyphen")
    if name not in PUBLISHED_DISKS:
        raise RouteError("published disk one is only for Curse and Silver Blades")
    if issue not in PUBLISHED_SOURCES_BY_ISSUE:
        raise RouteError(f"published disk one has no pinned sources for issue {issue}")
    report_path = pathlib.Path(report_path)
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    outcome = report.get("save_as", {})
    if (outcome.get("refused") or outcome.get("losses") or outcome.get("dropped") or
            report.get("written") != outcome.get("written") or
            len(report.get("written", [])) != 1 or
            outcome.get("to") != "amiga"):
        raise RouteError("Save As did not publish one lossless Amiga image")
    port = "c64" if report.get("c64_disks_dir") else "dos"
    letter = "A" if port == "c64" else "D"
    if outcome.get("slot") != letter:
        raise RouteError("Save As reported the wrong source slot letter")
    source = pathlib.Path(report["specimen"])
    image = pathlib.Path(report["written"][0])
    disk1 = pathlib.Path(report["amiga_disk1"])
    disk2 = pathlib.Path(report["amiga_disk2"])
    source_pin = PUBLISHED_SOURCES_BY_ISSUE[issue].get((name, port))
    if source_pin is None:
        raise RouteError(f"issue {issue} pins no {port} source for {name}")
    disk1_pin, disk2_pin, _executable, _volume = PUBLISHED_DISKS[name]
    if (source != pathlib.Path(outcome.get("source", "")) or
            report.get("specimen_sha256") != source_pin or sha256(source) != source_pin):
        raise RouteError("the Save As source differs from the pinned specimen")
    if sha256(disk1) != disk1_pin or sha256(disk2) != disk2_pin:
        raise RouteError("the Save As game disks differ from the registered pins")
    image_sha = sha256(image)
    if (report.get("written_sha256") != {image.name: image_sha} or
            image.name != "POOLSAVE.ADF" or
            pathlib.Path(outcome.get("destination", "")) != image):
        raise RouteError("the Save As image differs from its report")
    disk = _verified_disk(image)
    reading = _published_title(name, letter, issue=issue).read_slot(disk, letter)
    if "place" not in reading or "clock" not in reading:
        raise RouteError(f"published slot {letter} does not decode: {reading}")
    # The way out of the start square depends on where the party stands, not on the port:
    # Curse's party-menu square faces a wall to the east.
    turn_about = _turn_about(name, letter, reading["place"])
    items_screen = _items_screen(name, reading)
    opening_scene = _opening_scene(name, reading["place"])
    title = _published_title(name, letter, issue=issue, turn_about=turn_about,
                             items_screen=items_screen, opening_scene=opening_scene)
    original = _verified_disk(disk1)
    slot_path = f"/SAVE/savgam{letter}.{'dat' if name == 'curse' else 'sav'}".lower()
    old, new = _disk_files(original), _disk_files(disk)
    executable, volume = PUBLISHED_DISKS[name][2:]
    if (disk.volume_name != volume or original.volume_name != volume or
            set(new) != set(old) | {slot_path} or
            any(new.get(key) != value for key, value in old.items() if key != slot_path) or
            set(path.lower() for path, _ in disk.walk_dirs()) !=
            set(path.lower() for path, _ in original.walk_dirs()) or
            disk.to_bytes()[:1024] != original.to_bytes()[:1024] or
            executable.lower() not in new or "/save/spindisk" not in new or
            new[slot_path] == old.get(slot_path)):
        raise RouteError("the published image differs from disk 1 outside the converted slot")
    present = title.slot_letters(disk)
    if letter not in present or any(c in present for c in ("C", "F")):
        raise RouteError("the published image lacks its slot or already holds a save target")
    run = scratch.cache_dir("acceptance", issue, run_id)
    if run.exists():
        raise RouteError(f"run folder already exists: {run}")
    scratch.ensure(run)
    published = run / "published.adf"
    df0 = run / "df0.adf"
    df1 = run / "df1.adf"
    report_copy = run / "saveas-report.json"
    for src, dst in ((image, published), (image, df0), (disk2, df1)):
        with src.open("rb") as reader, dst.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
    report_copy.write_bytes(report_bytes)
    published.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    report_copy.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    if (sha256(published) != image_sha or sha256(df0) != image_sha or
            sha256(df1) != disk2_pin):
        raise RouteError("a copied acceptance disk differs from its input")
    manifest = {
        "mode": "published_disk_one", "issue": issue,
        "turn_about": turn_about,
        "title": name, "source_port": port, "source_sha256": source_pin,
        "loaded_letter": letter, "names_a": reading["names"],
        "state_a": reading["place"], "clock_a": reading["clock"],
        "expected_after": None,
        "published_source": {"path": str(image), "sha256": image_sha},
        "disks": {"df0": _entry(df0), "df1": _entry(df1)},
        "registered": {"source": _entry(source), "report": _entry(report_copy),
                       "published": _entry(published), "disk_one": _entry(disk1),
                       "disk_two": _entry(disk2)},
    }
    if name == "ssb":
        manifest["items_screen"] = items_screen
        manifest["opening_scene"] = opening_scene
    path = run / "prepare.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    _published_manifest(path, name)
    return path


def _summary(result: dict[str, Any], manifest: pathlib.Path, attempt: str) -> str:
    path = str(manifest.parent / attempt / "summary.json")
    if result.get("diagnose"):
        error = next((result[key] for key in (
            "error", "stop_error", "fetch_df0_error", "fetch_df1_error",
            "boot_log_error", "config_remove_error", "release_error")
            if result.get(key)), "")
        if not error and not result["success"]:
            error = f"diagnostic failed; see {path}"
    else:
        error = (result["error"] or result.get("specimen_error") or
                 result.get("release_error") or "")
    summary = {"success": result["success"], "error": error,
               "unguarded": result.get("unguarded", []),
               "summary": path}
    if result.get("release_error"):
        summary["release_error"] = result["release_error"]
    if result.get("error_cause"):
        summary["error_cause"] = result["error_cause"]
    if result.get("diagnose"):
        summary["remote_config_dirty"] = result.get("remote_config_dirty", False)
        if result.get("remote_config_path"):
            summary["remote_config_path"] = result["remote_config_path"]
        if result.get("config_remove_error"):
            summary["config_remove_error"] = result["config_remove_error"]
    return json.dumps(summary,
                      sort_keys=True)


def expect_verdict(title: AmigaTitle, manifest: pathlib.Path, attempt: str,
                   expect: tuple[str, int, int, int]) -> tuple[bool, str]:
    """Read the route's later slot off the run's fetched save disk and check `expect` against it.

    Re-opens `<manifest.parent>/<attempt>/fetched-<save_disk>.adf`, which
    `run_recon` writes for every attempt that reached the fetch step, and
    reads `title.after_letter` -- the camp-save slot the accept route writes
    after its walk. Refutes, naming why, when that file is missing or the
    slot holds no matching node. Returns `(accepted, verdict line)`.
    """
    fetched = manifest.parent / attempt / f"fetched-{title.save_disk}.adf"
    if not fetched.is_file():
        name, eid, minutes, _data = expect
        return False, f"expect {name} id {eid} at {minutes} minutes: refutes (no fetched save disk)"
    reading = title.read_slot(_verified_disk(fetched), title.after_letter)
    return check_expect(reading, expect)


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


def _draw_options(args: argparse.Namespace, holder: str) -> dict[str, Any]:
    """`run_recon`'s rulebook keywords, with the memory target only when there is more than one draw."""
    draws = getattr(args, "rulebook_draws", None)
    if draws is None:
        return {}
    if draws < 2:
        return {"rulebook_draws": draws}
    from automap import amiga  # noqa: PLC0415

    pipe = amiga.WinuaePipe()
    return {"rulebook_draws": draws,
            "target": amiga.AmigaTarget(pipe, amiga.MACHINES["secret-of-the-silver-blades"]),
            "lane_check": lambda: pipe.drives(holder)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    choices = sorted((*TITLES, "ssb"))

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--title", required=True, choices=choices)
        p.add_argument("--manifest", required=True, type=pathlib.Path)
        p.add_argument("--audio-proof", required=True, type=pathlib.Path)
        p.add_argument("--attempt")
        p.add_argument("--holder", default=None)
        p.add_argument("--deadline", type=float, default=1800,
                       help="seconds for the whole run; the route gets this less "
                            "min(300, deadline/2), which is kept for cleanup")
        p.add_argument("--published-disk-one", action="store_true")

    p = sub.add_parser("prepare", help="copy the registered images and the specimen into a run folder")
    p.add_argument("--title", required=True, choices=choices)
    p.add_argument("--run-id", required=True)
    p.add_argument("--published-disk-one", action="store_true")
    p.add_argument("--saveas-report", type=pathlib.Path)
    p.add_argument("--source", type=pathlib.Path)
    p.add_argument("--staged-from", type=pathlib.Path)
    p.add_argument("--issue")
    p.add_argument("--save-count", type=int, default=None,
                   help="Silver Blades only: a value for the private helper that stages the prepared slot")
    p.add_argument("--disk3", type=pathlib.Path, default=None,
                   help="darkness-reload only: the game-written disk 3 an accept run fetched")
    p.add_argument("--disk3-sha256", default=None, help="darkness-reload only: that disk's SHA-256")
    p.add_argument("--accept-summary", type=pathlib.Path, default=None,
                   help="darkness-reload only: that accept run's summary.json")
    p.add_argument("--substitute", type=pathlib.Path, default=None,
                   help="a disk holding a party some other tool wrote, whose "
                        "--substitute-letter slot replaces the route's loaded "
                        "slot; only titles in _SUBSTITUTABLE accept this")
    p.add_argument("--substitute-letter", default="A",
                   help="the slot to read off --substitute (default A)")
    m = sub.add_parser("measure", help="boot and press the route up to the first save; writes nothing")
    common(m)
    m.add_argument("--guards", type=pathlib.Path, default=None,
                   help="screen guard JSON; a route state it holds must match, and the boot waits for its title")
    m.add_argument("--route", help="Silver Blades only: KEY:state,KEY:state; default is the built-in route")
    m.add_argument("--write-keys", help="Silver Blades only: comma-separated keys that write; default B")
    a = sub.add_parser("accept", help="guarded load, sheet, two saves around a walk and the read-back")
    common(a)
    a.add_argument("--guards", required=True, type=pathlib.Path)
    a.add_argument("--identity", required=True, type=pathlib.Path)
    a.add_argument("--expect", default=None,
                   help="NAME:ID:MINUTES:DATA, checked against the route's later slot")
    a.add_argument("--journal-python")
    a.add_argument("--rulebook-draws", type=int, default=None,
                   help=f"Silver Blades only: camp saves to make in this boot, 1 to {RULEBOOK_DRAWS_MAX}")
    a.add_argument("--preserve-specimen", action="store_true",
                   help="register and check a successful published or substituted game's fetched "
                        "save disk before release")
    a.add_argument("--specimen-issue", default=None,
                   help='a substituted --preserve-specimen: the issue the specimen is for, as '
                        '"#N (title)"')
    r = sub.add_parser("reload", help="guarded load of a game-written slot and a check of the place "
                                      "on screen; writes nothing")
    common(r)
    r.add_argument("--guards", required=True, type=pathlib.Path)
    r.add_argument("--identity", required=True, type=pathlib.Path)
    d = sub.add_parser("diagnose", help="guarded title-only boot of the published Silver Blades image")
    common(d)
    d.set_defaults(deadline=600)
    d.add_argument("--guards", required=True, type=pathlib.Path)
    d.add_argument("--boot-limit", type=float, default=300)
    args = parser.parse_args(argv)
    try:
        silver_blades = args.title == "ssb"
        if args.command == "diagnose" and (not silver_blades or not args.published_disk_one
                                           or args.deadline > 600 or args.boot_limit > 300):
            raise RouteError("diagnose needs published Silver Blades and bounded limits")
        if args.published_disk_one:
            if args.command == "reload":
                raise RouteError("published disk one has no reload route")
            if args.command == "prepare":
                if args.saveas_report is None:
                    raise RouteError("published disk one needs --saveas-report")
                if any((args.source, args.staged_from, args.disk3,
                        args.disk3_sha256, args.accept_summary, args.substitute,
                        args.save_count is not None)):
                    raise RouteError("published disk one takes only a Save As report")
                print(prepare_published(args.title, args.run_id, args.saveas_report,
                                        args.issue or PUBLISHED_ISSUE))
                return 0
            if args.title not in PUBLISHED_DISKS:
                raise RouteError("published disk one is only for Curse and Silver Blades")
            if args.command == "measure" and (args.route or args.write_keys):
                raise RouteError("published disk one uses its source-specific route")
        elif args.command == "prepare" and args.saveas_report is not None:
            raise RouteError("--saveas-report requires --published-disk-one")
        if args.command == "reload" and silver_blades:
            raise RouteError("Silver Blades has no reload route")
        if args.title == "darkness-unstarted" and args.command in ("accept", "reload"):
            raise RouteError("darkness-unstarted only measures: its route has no write step "
                             "and no walk")
        if args.command == "prepare":
            if silver_blades:
                if args.source is None:
                    raise RouteError("Silver Blades prepare requires --source")
                if (args.disk3 is not None or args.disk3_sha256 is not None
                        or args.accept_summary is not None or args.substitute is not None
                        or args.substitute_letter != "A"):
                    raise RouteError("Silver Blades prepare takes no title-only options")
            elif (args.source is not None or args.staged_from is not None
                  or args.issue is not None or args.save_count is not None):
                raise RouteError("--source, --staged-from, --issue and --save-count "
                                 "require --title ssb")
        elif not silver_blades and args.attempt is None:
            raise RouteError("--attempt is required for this title")
        if (args.command == "measure" and not silver_blades
                and (args.route is not None or args.write_keys is not None)):
            raise RouteError("--route and --write-keys require --title ssb")
        if args.command == "accept":
            if silver_blades and args.journal_python is None:
                raise RouteError("Silver Blades accept requires --journal-python")
            if not silver_blades and args.journal_python is not None:
                raise RouteError("--journal-python requires --title ssb")
            if args.rulebook_draws is not None and (not silver_blades or args.published_disk_one):
                raise RouteError("--rulebook-draws requires --title ssb without "
                                 "--published-disk-one")
        expect = parse_expect(args.expect) if getattr(args, "expect", None) else None
        with terminating():
            if args.command == "prepare":
                if silver_blades:
                    print(route_silver_blades.prepare(
                        args.source, args.run_id, staged_from=args.staged_from,
                        issue=args.issue or "672",
                        **({} if args.save_count is None else {"save_count": args.save_count})))
                    return 0
                print(prepare(TITLES[args.title], args.run_id, specimen=args.disk3,
                              specimen_sha256=args.disk3_sha256,
                              accept_summary=args.accept_summary,
                              substitute=args.substitute,
                              substitute_letter=args.substitute_letter))
                return 0
            if args.published_disk_one:
                manifest, title = _published_manifest(args.manifest, args.title)
            else:
                title = None if silver_blades else TITLES[args.title]
            attempt = args.attempt or ("recon1" if args.command == "measure" else
                                       "gfx705-directdraw1" if args.command == "diagnose" else
                                       "accept1")
            holder_issue = manifest.get("issue", PUBLISHED_ISSUE) if args.published_disk_one else (
                "672" if silver_blades else ISSUE)
            holder = args.holder or f"wish{holder_issue}-{uuid.uuid4().hex[:12]}"
            if args.command == "diagnose":
                result = run_recon(
                    args.manifest, guest=WinGuest(), holder=holder,
                    audio_proof=args.audio_proof, attempt=attempt,
                    guard=PixelGuards(args.guards), deadline_seconds=args.deadline,
                    boot_limit=args.boot_limit, diagnose=True, title=title,
                    published_disk_one=True, published_name=args.title)
            elif args.command == "measure":
                route = (parse_route(args.route) if args.route else route_silver_blades.ROUTE)
                write_keys = parse_write_keys(
                    args.write_keys if args.write_keys is not None else "B") if silver_blades else None
                result = run_recon(
                    args.manifest, guest=WinGuest(), holder=holder,
                    audio_proof=args.audio_proof, attempt=attempt,
                    guard=PixelGuards(args.guards) if args.guards else None,
                    deadline_seconds=args.deadline, measure=True, title=title,
                    published_disk_one=args.published_disk_one,
                    published_name=args.title if args.published_disk_one else None,
                    **({"route": route,
                        "write_keys": write_keys,
                        "min_waits": route_silver_blades.default_min_waits(route)}
                       if silver_blades and not args.published_disk_one else {}))
            else:
                result = run_recon(
                    args.manifest, guest=WinGuest(), guard=PixelGuards(args.guards),
                    identity=PixelGuards(args.identity), holder=holder,
                    audio_proof=args.audio_proof, attempt=attempt,
                    deadline_seconds=args.deadline, title=title,
                    published_disk_one=args.published_disk_one,
                    published_name=args.title if args.published_disk_one else None,
                    journal_python=getattr(args, "journal_python", None),
                    **_draw_options(args, holder),
                    preserve_specimen=getattr(args, "preserve_specimen", False),
                    specimen_issue=getattr(args, "specimen_issue", None),
                    **({"accept": True,
                        "min_waits": {**route_silver_blades.default_min_waits(),
                                      **route_silver_blades.ACCEPT_MIN_WAITS}}
                       if silver_blades and not args.published_disk_one else
                       {"reload" if args.command == "reload" else "accept": True}))
            if silver_blades and args.command == "measure":
                measured = {"success": result["success"], "error": result["error"],
                            "summary": str(args.manifest.parent / attempt / "summary.json")}
                if result.get("error_cause"):
                    measured["error_cause"] = result["error_cause"]
                print(json.dumps(measured, sort_keys=True))
            else:
                print(_summary(result, args.manifest, attempt))
            for line in result.get("read", {}).get("verdicts", []):
                print(line)
            success = result["success"]
            if args.command == "accept" and expect is not None:
                if silver_blades and not args.published_disk_one:
                    accepted, line = route_silver_blades.expect_verdict(
                        args.manifest, attempt, expect)
                else:
                    accepted, line = expect_verdict(title, args.manifest, attempt, expect)
                print(line)
                success = success and accepted
            return 0 if success else 1
    except (RouteError, OSError, ValueError) as exc:
        print(f"acceptance: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
