#!/usr/bin/env python3
"""Prepare, measure and accept one Amiga title's load, inspect, move, save and read-back run under WinUAE."""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import pathlib
import sys
import time
import uuid
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from goldbox import geo  # noqa: E402
from tools.amiga.route import (  # noqa: E402
    ISSUE,
    TITLE_LIMIT,
    AmigaTitle,
    check_expect,
    parse_expect,
)
from tools.amiga.route_curse import CURSE, _prepare_curse  # noqa: E402
from tools.amiga.route_darkness import (  # noqa: E402
    DARKNESS,
    DARKNESS_RELOAD,
    _prepare_darkness,
    _prepare_darkness_reload,
)
from tools.amiga.route_pool import POOL, _prepare_pool  # noqa: E402
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
from tools.registry import evidence, scratch  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]

# Single grabs every ~8-10 s in all against a bar that held still for at least 24 s.
TITLE_POLL = 2.0
MEASURE_BOOT_POLL = 10.0
MEASURE_TITLE_SPAN = 120.0
GUARD_POLL = 5.0
GUARD_LIMIT = 120.0
# A key pressed while the disk is being written is swallowed, so the screen
# after the write gets the same long first wait as the load picker.
POST_WRITE_WAIT = 20.0

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



def run_recon(manifest_path: pathlib.Path, *, guest: Any, guard: Any = None,
              holder: str, audio_proof: pathlib.Path, attempt: str = "recon1",
              deadline_seconds: float = 1800,
              route: tuple[tuple[str, str], ...] = ROUTE,
              write_keys: tuple[str, ...] = ("B",),
              min_waits: dict[str, float] | None = None,
              measure: bool = False, accept: bool = False,
              identity: Any = None, journal_python: str | None = None,
              answer: Any = None, preflight: Any = None,
              title: AmigaTitle | None = None, reload: bool = False) -> dict[str, Any]:
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
    if title is not None:
        if not isinstance(title, AmigaTitle):
            raise RouteError("title must be an AmigaTitle")
        if reload and (accept or measure):
            raise RouteError("reload is a mode of its own, apart from accept and measure")
        if not reload and accept == measure:
            raise RouteError("a title run is either accept or measure")
        if reload != (title.control_letter is None):
            raise RouteError("only a title with no save letters is reloaded, and it runs only "
                             "as a reload")
        if route != ROUTE or write_keys != ("B",):
            raise RouteError("a title brings its own route and write keys")
    if reload and title is None:
        raise RouteError("reload needs a title")
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
    if not measure:
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
    if accept and journal_python is not None and title is None:
        (preflight or journal_preflight)(journal_python)
    min_waits = {**(title.min_waits if title else {}), **(min_waits or {})}
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
        if title is not None:
            return run_title_answer()
        started = time.monotonic()
        adf = originals["boot_source"]
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

    def interstitial(state: str, crop: pathlib.Path, done: dict[str, int]) -> bool:
        """Act on a known screen that is not the wanted one, by the title's table."""
        for screen, action, waiting_for, limit in table:
            if (title is None and not accept and screen in _ACCEPT_ONLY) or (
                    title is not None and measure and action[0] == "answer"):
                continue
            if (done.get(screen, 0) >= limit or not _has_rule(guard, screen)
                    or (waiting_for is not None and state not in waiting_for)
                    or not guard(screen, crop)):
                continue
            done[screen] = done.get(screen, 0) + 1
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
        done: dict[str, int] = {}
        digest = settle_unguarded(state, name)
        for again in range(1, 4):
            if not interstitial(state, shots / f"{name}.png", done):
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
            if title and elapsed >= title_limit:
                raise RouteError(
                    f"title screen was not recognized within {title_limit:.0f}s")
            if not title and elapsed >= boot_span:
                return last
            wait(TITLE_POLL if title else MEASURE_BOOT_POLL)

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
            for n, step in enumerate(route if title is None else title.measure_route, 1):
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
        if claimed and (not start_attempted or stopped):
            try:
                result["release"] = guest.release(
                    holder, timeout=cleanup_limit(30))
                log("release", receipt=result["release"])
            except BaseException as exc:
                result["release_error"] = f"{type(exc).__name__}: {exc}"
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
        else:
            _read_title(title, manifest, result, out, disks, registered,
                        kept_before, letter, accept, measure, steps, reload)
        result["elapsed_seconds"] = time.monotonic() - begun
        (out / "summary.json").write_text(json.dumps(result, indent=2,
                                                     sort_keys=True) + "\n")
        runlog.close()
    return result


TITLES: dict[str, AmigaTitle] = {"pool": POOL, "curse": CURSE, "darkness": DARKNESS,
                                 "darkness-reload": DARKNESS_RELOAD}

_PREPARE = {"pool": _prepare_pool, "curse": _prepare_curse, "darkness": _prepare_darkness,
            "darkness-reload": _prepare_darkness_reload}


def _name(title: AmigaTitle) -> str:
    for name, known in TITLES.items():
        if known is title:
            return name
    raise RouteError("that is not one of this module's titles")


#: Titles whose `_PREPARE` function accepts a substitute slot -- the ones
#: routed through `staging._prepare_from`, whose party lives in one savegame
#: file `amigalaterslot.import_slot` can graft onto a copy of the pinned disk.
_SUBSTITUTABLE = frozenset({"curse"})


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


def _summary(result: dict[str, Any], manifest: pathlib.Path, attempt: str) -> str:
    return json.dumps({"success": result["success"], "error": result["error"],
                       "unguarded": result["unguarded"],
                       "summary": str(manifest.parent / attempt / "summary.json")},
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    choices = sorted(TITLES)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--title", required=True, choices=choices)
        p.add_argument("--manifest", required=True, type=pathlib.Path)
        p.add_argument("--audio-proof", required=True, type=pathlib.Path)
        p.add_argument("--attempt", required=True)
        p.add_argument("--holder", default=None)
        p.add_argument("--deadline", type=float, default=1800)

    p = sub.add_parser("prepare", help="copy the registered images and the specimen into a run folder")
    p.add_argument("--title", required=True, choices=choices)
    p.add_argument("--run-id", required=True)
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
    a = sub.add_parser("accept", help="guarded load, sheet, two saves around a walk and the read-back")
    common(a)
    a.add_argument("--guards", required=True, type=pathlib.Path)
    a.add_argument("--identity", required=True, type=pathlib.Path)
    a.add_argument("--expect", default=None,
                   help="NAME:ID:MINUTES:DATA, checked against the route's later slot")
    r = sub.add_parser("reload", help="guarded load of a game-written slot and a check of the place "
                                      "on screen; writes nothing")
    common(r)
    r.add_argument("--guards", required=True, type=pathlib.Path)
    r.add_argument("--identity", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        expect = parse_expect(args.expect) if getattr(args, "expect", None) else None
        with terminating():
            if args.command == "prepare":
                print(prepare(TITLES[args.title], args.run_id, specimen=args.disk3,
                              specimen_sha256=args.disk3_sha256,
                              accept_summary=args.accept_summary,
                              substitute=args.substitute,
                              substitute_letter=args.substitute_letter))
                return 0
            title = TITLES[args.title]
            holder = args.holder or f"wish{ISSUE}-{uuid.uuid4().hex[:12]}"
            if args.command == "measure":
                result = run_recon(
                    args.manifest, guest=WinGuest(), holder=holder,
                    audio_proof=args.audio_proof, attempt=args.attempt,
                    guard=PixelGuards(args.guards) if args.guards else None,
                    deadline_seconds=args.deadline, measure=True, title=title)
            else:
                result = run_recon(
                    args.manifest, guest=WinGuest(), guard=PixelGuards(args.guards),
                    identity=PixelGuards(args.identity), holder=holder,
                    audio_proof=args.audio_proof, attempt=args.attempt,
                    deadline_seconds=args.deadline, title=title,
                    **{"reload" if args.command == "reload" else "accept": True})
            print(_summary(result, args.manifest, args.attempt))
            for line in result.get("read", {}).get("verdicts", []):
                print(line)
            success = result["success"]
            if args.command == "accept" and expect is not None:
                accepted, line = expect_verdict(title, args.manifest, args.attempt, expect)
                print(line)
                success = success and accepted
            return 0 if success else 1
    except (RouteError, OSError, ValueError) as exc:
        print(f"acceptance: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
