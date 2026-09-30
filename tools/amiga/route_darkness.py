"""Pools of Darkness: pins, readers and the description of its load, save, read-back and reload routes."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import re
import shutil
from typing import Any

from goldbox import amiga_adf, amiga_savegame
from tools.amiga.route import ISSUE, AmigaTitle
from tools.amiga.staging import _find_images, sha256
from tools.amiga.winuaesession import RouteError
from tools.registry import scratch

DARKNESS_DISK1_SHA256 = "9d38338ecb44434331485a908b0d6c204f9b0a8a6e509baa2a8e1b24e892b3ee"
DARKNESS_DISK2_SHA256 = "f7819b475e4071c36d349003277e9516abfee8f9c294830d8423e98a9e6c7b71"
DARKNESS_DISK3_SHA256 = "bba0945c39e54fee75e4453e552a54534a584a395f9796ca570c655bf02f2fdd"
DARKNESS_VOLUME = "POD 3"
DARKNESS_LOADED = "B"

_DARKNESS_SAVED_GAME = re.compile(r"savgam([A-Z])\.pty", re.IGNORECASE)


def _darkness_read_slot(disk: amiga_adf.AmigaDisk, letter: str) -> dict[str, Any]:
    """One Pools of Darkness slot in `/Save` of disk 3: `missing`, `decode_error`, or place and names."""
    try:
        raw = disk.read_file(amiga_savegame.pod_slot_path(letter))
    except amiga_adf.AmigaDiskError:
        return {"missing": True, "sha256": None}
    reading: dict[str, Any] = {"sha256": hashlib.sha256(raw).hexdigest()}
    try:
        data = amiga_savegame.pod_read_slot(disk, letter)
        state = amiga_savegame.pod_from_amiga(data)
        reading["names"] = [member.name.strip()
                            for member in amiga_savegame.pod_parse(data).characters]
        reading["place"] = {"area": state.dungeon_map, "x": state.x, "y": state.y,
                            "facing": state.facing}
    except Exception as exc:  # noqa: BLE001 - every reader failure is the verdict's `decode_error`
        reading.pop("names", None)
        reading["decode_error"] = f"{type(exc).__name__}: {exc}"
    return reading


def _darkness_saves(disk: amiga_adf.AmigaDisk) -> list:
    return [e for e in disk.entries(disk.lookup("/SAVE").block) if not e.is_dir]


def _darkness_slot_letters(disk: amiga_adf.AmigaDisk) -> list[str]:
    found = (_DARKNESS_SAVED_GAME.fullmatch(e.name) for e in _darkness_saves(disk))
    return sorted(m.group(1).upper() for m in found if m)


def _darkness_slot_files(disk: amiga_adf.AmigaDisk, letter: str) -> dict[str, bytes]:
    return {e.name: disk.read_file(f"/SAVE/{e.name}") for e in _darkness_saves(disk)
            if e.name.lower() == f"savgam{letter}.pty".lower()}


# Disk 3 is the save disk and is mounted in DF1 from the start; with it there the boot showed
# no disk 3 prompt, and the title screen is the first screen a key answers.
# Disk 1 is in DF0 from the start. The game asks for disk 2 right after the slot letter and
# accepts it only in DF0, so disk 2 is staged as a spare and the route inserts it there at that
# prompt. A, C, D and E stay unchanged; E is also the game's own exit key on the sheet and at
# camp, which `plain_keys` names.
# The control and after saves go to F and G, letters the game's own save picker (A to H) offers
# and no saved game on disk 3 uses; B is the loaded slot. The measure route types one throwaway
# letter and Return into the journal question that follows Begin Adventuring, then walks to the
# camp save picker, before any save letter. The accept route answers the same question the same
# way, with explicit keys and no answerer, between the control save and the walk.
# The game answers the camp save with its quit question, which the accept route answers `N`.
# `camp_save_picker`'s second guard rule is deliberately weak: once camp steps have cleared the
# text window it sees only the `SAVE WHICH GAME` strip, which is pixel-identical to the party
# menu's `save_picker`. G is still pressed only there, because the route reaches that state only
# by `S` from a recognised `camp` bar, and the party menu's picker is never one step from camp.
# `SPACE` answers `INSERT DISK 2 AND PRESS A KEY` after the DF0 insert: both accept boots then
# recognised the loaded menu 24 to 25 s after the key.
DISK2_INSERT = ((0, "disk2", "SPACE"), "loaded_menu", "insert")

DARKNESS = AmigaTitle(
    issue=ISSUE,
    mounted=("disk1", "disk3"), spares=("disk2",),
    save_disk="disk3",
    read_slot=_darkness_read_slot, slot_letters=_darkness_slot_letters,
    slot_files=_darkness_slot_files,
    # `L` opens a prompt asking where to load from, with three choices; `P` picks this title's
    # own saves. The slot list after it is the guarded state `load_picker`.
    route=(
        ("P", "party_menu", "key"), ("L", "load_from", "key"), ("P", "load_picker", "key"),
        ("B", "disk2_prompt", "key"), DISK2_INSERT,
        ("V", "sheet", "key"), ("E", "loaded_menu", "key"),
        ("S", "save_picker", "key"), ("F", "loaded_menu", "write"),
        ("B", "journal", "key"), ("X", "journal_answer", "key"), ("RET", "world", "key"),
        ("NP8", "world", "move"), ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
        ("G", "exit_game", "write"), ("N", "camp", "key"),
    ),
    # Ends at the camp save picker and writes nothing.
    measure_route=(
        ("P", "party_menu", "key"), ("L", "load_from", "key"), ("P", "load_picker", "key"),
        ("B", "disk2_prompt", "key"), DISK2_INSERT,
        ("V", "sheet", "key"), ("E", "loaded_menu", "key"),
        ("B", "journal", "key"), ("X", "journal_answer", "key"), ("RET", "world", "key"),
        ("NP8", "world", "move"), ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
    ),
    # In the measured boot the settled captures ended at 27, 99, 153 (loading screens), 247 (the
    # first showing the title), 271, 297 (the same title) and 331 s (the demo) after the claim,
    # so the title appeared between 153 and 247 s and the demo began between 297 and 331 s: at
    # least 50 s later. The first key goes out about 8 s after the first capture that ends at or
    # after `boot_span` seconds from the start, so 225 puts it near 255 s, on the title; a title
    # 30 s slower would put it on a loading screen. A measure run has no title guard, so the span
    # is unchecked on a boot that slow; the accept boots recognised the title 237 and 238 s after
    # the claim.
    boot_span=225.0, title_limit=420.0,
    control_letter="F", after_letter="G", kept_letters=("A", "C", "D", "E"),
    plain_keys=(("E", "loaded_menu"), ("E", "camp")),
    strict=frozenset({"party_menu", "load_from", "load_picker", "disk2_prompt", "loaded_menu",
                      "sheet", "save_picker", "journal", "journal_answer", "world",
                      "camp", "camp_save_picker", "exit_game"}),
    disk_prompts=frozenset({"disk2_prompt"}),
    # Both accept boots recognised `disk2_prompt` 14 s after the key before it; whether a shorter
    # `disk2_prompt` wait would also show it is unmeasured.
    min_waits={"party_menu": 20.0, "load_from": 20.0, "load_picker": 10.0,
               "disk2_prompt": 10.0, "loaded_menu": 20.0,
               "sheet": 5.0, "save_picker": 10.0, "journal": 45.0, "journal_answer": 3.0,
               "world": 45.0, "world_after_move": 5.0,
               "camp": 10.0, "camp_save_picker": 10.0,
               # Copied from Curse, which meets the same quit question after its camp save.
               "exit_game": 20.0},
    interstitials=(
        ("yes_no", ("keys", "N"), frozenset({"world"}), 1),
        ("continue", ("keys", "RET"), frozenset({"world"}), 3),
    ),
)

# Loads the game-written slot G and writes nothing. `run_recon` adds G to the kept slots itself,
# and B is a kept letter here, so `plain_keys` names where the game's own B (Begin Adventuring)
# goes out.
DARKNESS_RELOAD_LOADED = "G"
_RELOAD_ROUTE = (
    ("P", "party_menu", "key"), ("L", "load_from", "key"), ("P", "load_picker", "key"),
    (DARKNESS_RELOAD_LOADED, "disk2_prompt", "key"), DISK2_INSERT,
    ("V", "sheet", "key"), ("E", "loaded_menu", "key"),
    ("B", "journal", "key"), ("X", "journal_answer", "key"), ("RET", "world", "key"),
)
DARKNESS_RELOAD = dataclasses.replace(
    DARKNESS, route=_RELOAD_ROUTE, measure_route=_RELOAD_ROUTE,
    control_letter=None, after_letter=None, kept_letters=("A", "B", "C", "D", "E", "F"),
    plain_keys=(("E", "loaded_menu"), ("B", "journal")),
    strict=frozenset({"party_menu", "load_from", "load_picker", "disk2_prompt", "sheet",
                      "loaded_menu", "journal", "journal_answer", "world"}),
)

# Loads disk 3's own slot A, a party that has not set out, and writes nothing, so the screens
# between the journal and the world can be measured. Slot A's load showed no disk 2 prompt, so
# the prompt is an optional row answered wherever it appears. B is a kept letter here and is also
# the game's Begin key, which `plain_keys` names. The arrival screens are not in the guard map,
# so `yes_no` and `continue` wait as long as `world` does after the journal, the area loading first.
DARKNESS_UNSTARTED_LOADED = "A"
_UNSTARTED_ROUTE = (
    ("P", "party_menu", "key"), ("L", "load_from", "key"), ("P", "load_picker", "key"),
    (DARKNESS_UNSTARTED_LOADED, "loaded_menu", "key"),
    ("V", "sheet", "key"), ("E", "loaded_menu", "key"),
    ("B", "journal", "key"), ("X", "journal_answer", "key"), ("RET", "yes_no", "key"),
    ("N", "continue", "key"), ("RET", "continue", "key"), ("RET", "world", "key"),
)
DARKNESS_UNSTARTED = dataclasses.replace(
    DARKNESS, route=_UNSTARTED_ROUTE, measure_route=_UNSTARTED_ROUTE,
    kept_letters=("B", "C", "D", "E"),
    plain_keys=(("E", "loaded_menu"), ("B", "journal")),
    min_waits={**DARKNESS.min_waits, "yes_no": 45.0, "continue": 10.0},
    interstitials=(
        ("disk2_prompt", ("insert", 0, "disk2", "SPACE"),
         frozenset({"loaded_menu", "sheet", "journal", "journal_answer", "yes_no", "continue",
                    "world"}), 1),
        *DARKNESS.interstitials,
    ),
)


def _prepare_darkness(run: pathlib.Path, override: pathlib.Path | None,
                      loaded: str = DARKNESS_LOADED) -> dict[str, Any]:
    """Disk 3 is itself the registered save disk, so `override` stands in for it and no specimen file exists."""
    wanted = {"disk1": DARKNESS_DISK1_SHA256, "disk2": DARKNESS_DISK2_SHA256,
              "disk3": DARKNESS_DISK3_SHA256}
    if override is not None:
        override = pathlib.Path(override)
        if not override.is_file():
            raise RouteError(f"the disk {override} is missing")
        if sha256(override) != DARKNESS_DISK3_SHA256:
            raise RouteError(f"the specimen SHA-256 differs: {sha256(override)}")
    images = _find_images({k: v for k, v in wanted.items() if override is None or k != "disk3"})
    if override is not None:
        images["disk3"] = (str(override), override.read_bytes())
    save = amiga_adf.AmigaDisk(images["disk3"][1])
    if save.verify() or save.volume_name != DARKNESS_VOLUME:
        raise RouteError(f"disk 3 is not a verified {DARKNESS_VOLUME} disk")
    present = DARKNESS.slot_letters(save)
    for taken in (DARKNESS.control_letter, DARKNESS.after_letter):
        if taken in present:
            raise RouteError(f"slot {taken} already exists on disk 3")
    reading = DARKNESS.read_slot(save, loaded)
    if "place" not in reading:
        raise RouteError(f"slot {loaded} does not decode: {reading}")
    scratch.ensure(run)
    disks: dict[str, dict[str, str]] = {}
    for key, (_label, data) in images.items():
        path = run / f"{key}.adf"
        path.write_bytes(data)
        disks[key] = {"path": str(path), "sha256": sha256(path)}
    if any(disks[key]["sha256"] != pinned for key, pinned in wanted.items()):
        raise RouteError("a working copy differs from the pinned disk")
    manifest = {
        "title": "darkness", "disks": disks, "registered": {},
        "sources": {key: {"label": label, "sha256": wanted[key]}
                    for key, (label, _data) in images.items()},
        "loaded_letter": loaded,
        "state_a": reading["place"], "names_a": reading["names"],
    }
    after = _find_images({k: v for k, v in wanted.items() if override is None or k != "disk3"})
    if any(hashlib.sha256(after[key][1]).hexdigest() != wanted[key] for key in after):
        raise RouteError("a registered image changed during preparation")
    return manifest


def _walk_names(disk: amiga_adf.AmigaDisk) -> dict[str, bytes]:
    """Every file on the disk by its lower-cased path, with its bytes."""
    return {path.lower(): disk.read_file(path) for path, _entry in disk.walk()}


def _prepare_darkness_reload(run: pathlib.Path, disk3: pathlib.Path, disk3_sha256: str,
                             accept_summary: pathlib.Path) -> dict[str, Any]:
    """Prepare a reload run on a disk 3 that a successful accept run fetched.

    Refuses a file that does not hash to `disk3_sha256`, a summary that is not a successful
    accept run whose fetched disk 3 has that hash, a disk that is not the registered disk 3
    plus exactly the control and after saves, saves that do not decode to the registered
    party, and two saves at one place.
    """
    title = DARKNESS_RELOAD
    disk3, accept_summary = pathlib.Path(disk3), pathlib.Path(accept_summary)
    for path in (disk3, accept_summary):
        if not path.is_file():
            raise RouteError(f"the file {path} is missing")
    if sha256(disk3) != disk3_sha256:
        raise RouteError(f"the disk 3 SHA-256 differs: {sha256(disk3)}")
    try:
        summary = json.loads(accept_summary.read_text())
        fetched_sha = summary["fetched"]["disk3"]["sha256"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RouteError(f"the accept summary {accept_summary} is unreadable: {exc}") from exc
    if summary.get("success") is not True or summary.get("accept") is not True:
        raise RouteError("the summary is not a successful accept run")
    if fetched_sha != disk3_sha256:
        raise RouteError("the summary's fetched disk 3 is another disk")
    save = amiga_adf.AmigaDisk(disk3.read_bytes())
    if save.verify() or save.volume_name != DARKNESS_VOLUME:
        raise RouteError(f"disk 3 is not a verified {DARKNESS_VOLUME} disk")
    wanted = {"disk1": DARKNESS_DISK1_SHA256, "disk2": DARKNESS_DISK2_SHA256,
              "disk3": DARKNESS_DISK3_SHA256}
    images = _find_images(wanted)
    registered = amiga_adf.AmigaDisk(images["disk3"][1])
    written = {letter: title.slot_files(save, letter) for letter in ("F", "G")}
    added = {f"/save/{name}".lower() for files in written.values() for name in files}
    have, before = _walk_names(save), _walk_names(registered)
    if len(added) != 2 or set(have) != set(before) | added or any(
            have[name] != data for name, data in before.items()):
        raise RouteError("disk 3 is not the registered disk 3 plus slots F and G")
    reading = {letter: title.read_slot(save, letter) for letter in ("F", "G")}
    party = title.read_slot(registered, DARKNESS_LOADED)
    for letter, one in reading.items():
        if "place" not in one:
            raise RouteError(f"slot {letter} does not decode: {one}")
        if one["names"] != party["names"]:
            raise RouteError(f"slot {letter} names another party than slot {DARKNESS_LOADED}")
    if reading["F"]["place"] == reading["G"]["place"]:
        raise RouteError("slots F and G are at one place, which the screen cannot tell apart")
    scratch.ensure(run)
    disks: dict[str, dict[str, str]] = {}
    for key in ("disk1", "disk2"):
        path = run / f"{key}.adf"
        path.write_bytes(images[key][1])
        disks[key] = {"path": str(path), "sha256": sha256(path)}
    working = run / "disk3.adf"
    shutil.copyfile(disk3, working)
    disks["disk3"] = {"path": str(working), "sha256": sha256(working)}
    if any(disks[key]["sha256"] != wanted[key] for key in ("disk1", "disk2")):
        raise RouteError("a working copy differs from the pinned disk")
    if disks["disk3"]["sha256"] != disk3_sha256:
        raise RouteError("the working disk 3 differs from the input")
    after = _find_images(wanted)
    if (sha256(disk3) != disk3_sha256
            or any(hashlib.sha256(after[key][1]).hexdigest() != wanted[key] for key in after)):
        raise RouteError("a registered image changed during preparation")
    return {
        "title": "darkness-reload", "disks": disks,
        "registered": {"accept_disk3": {"path": str(disk3), "sha256": disk3_sha256}},
        "sources": {key: {"label": images[key][0], "sha256": wanted[key]}
                    for key in ("disk1", "disk2")},
        "loaded_letter": DARKNESS_RELOAD_LOADED,
        "state_a": reading["G"]["place"], "names_a": reading["G"]["names"],
        "other_letter": "F", "other_place": reading["F"]["place"],
        "slot_sha256": {letter: one["sha256"] for letter, one in reading.items()},
        "accept_summary": {"path": str(accept_summary), "sha256": sha256(accept_summary)},
    }
