#!/usr/bin/env python3
"""Prepare, measure and accept one Amiga title's load, inspect, move, save and read-back run under WinUAE."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import pathlib
import re
import shutil
import sys
import uuid
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from goldbox import amiga_adf, amiga_savegame  # noqa: E402
from tools.amiga import amigasaves  # noqa: E402
from tools.amiga.amigasecretsave import (  # noqa: E402
    HOLDER,
    AmigaTitle,
    PixelGuards,
    RouteError,
    WinGuest,
    run_recon,
    sha256,
    terminating,
)
from tools.registry import scratch, specimens  # noqa: E402

ISSUE = "679"

POOL_DISK1_SHA256 = "6ad445f5715d021d560ddcf003e78153003315af016a19dbc4b56d55d3019d4c"
POOL_DISK2_SHA256 = "4c9d42c8880e94827b7e0e886aed1ad7884c83ed90d8495ac83bc53ab908c6ca"
POOL_SPECIMEN_SHA256 = "20ef29b226180a9544efb47aa14f6ec26675f115efd765b6138716b23a81d77b"
POOL_SPECIMEN = ("por-amiga", "WISH-SPEC-por-52-c64toamiga-walk-resave",
                 "pulled-after-stop.adf")
POOL_VOLUME = "POOLSAVE"
POOL_LOADED = "A"
# The specimen's own camp save, made after the same about-face and one step.
POOL_LATER = "B"

_POOL_SAVED_GAME = re.compile(r"savgam([A-Z])\.dat", re.IGNORECASE)


def _pool_name(name: str) -> str:
    """A member's name as the game saves it: the specimen's own slot B drops the space that slot A keeps."""
    return name.replace(" ", "")


def _pool_read_slot(disk: amiga_adf.AmigaDisk, letter: str) -> dict[str, Any]:
    """One Pool save slot in the root of a fetched POOLSAVE disk: `missing`, `decode_error`, or place and names."""
    try:
        raw = disk.read_file(f"/savgam{letter}.dat")
    except amiga_adf.AmigaDiskError:
        return {"missing": True, "sha256": None}
    reading: dict[str, Any] = {"sha256": hashlib.sha256(raw).hexdigest()}
    try:
        party, save = amiga_savegame.read_por_slot(disk, letter, drawer="")
        state = amiga_savegame.por_state_from_amiga(save)
        reading["names"] = [_pool_name(member.name) for member in party]
        reading["place"] = {"area": state.area, "x": state.x, "y": state.y,
                            "facing": state.facing}
    except Exception as exc:  # noqa: BLE001 - every reader failure is the verdict's `decode_error`
        reading.pop("names", None)
        reading["decode_error"] = f"{type(exc).__name__}: {exc}"
    return reading


def _pool_slot_letters(disk: amiga_adf.AmigaDisk) -> list[str]:
    letters = []
    for entry in disk.entries():
        found = _POOL_SAVED_GAME.fullmatch(entry.name)
        if found and not entry.is_dir:
            letters.append(found.group(1).upper())
    return sorted(letters)


def _pool_slot_files(disk: amiga_adf.AmigaDisk, letter: str) -> dict[str, bytes]:
    """The slot's saved game and its character, item and effect files, which a later save must leave alone."""
    mine = re.compile(rf"(savgam{letter}\.dat|CHRDAT{letter}[0-9]\.(sav|itm|spc))",
                      re.IGNORECASE)
    return {entry.name: disk.read_file(f"/{entry.name}")
            for entry in disk.entries() if not entry.is_dir and mine.fullmatch(entry.name)}


# Section 3 of the plan for Pool of Radiance. `RET` at the first screen is the
# `wheel` interstitial below, which takes RETURN on this image. No route step
# presses RET after C or D, and none presses Y.
_POOL_LOAD = (
    ("RET", "party_menu", "key"), ("L", "save_path", "key"), ("RET", "load_picker", "key"),
    ("A", "world", "key"), ("V", "sheet", "key"), ("E", "world", "key"),
)
POOL = AmigaTitle(
    issue=ISSUE,
    mounted=("disk1", "disk2", "save"),
    options=("nr_floppies=3", "floppy2type=0"),
    save_disk="save",
    read_slot=_pool_read_slot, slot_letters=_pool_slot_letters, slot_files=_pool_slot_files,
    route=(
        *_POOL_LOAD,
        ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
        ("C", "quit_prompt", "write"), ("N", "camp", "key"),
        ("E", "world", "key"), ("NP2", "world", "turn"), ("NP8", "world", "move"),
        ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
        ("D", "quit_prompt", "write"), ("N", "camp", "key"),
    ),
    # Stops before C, at the camp's save picker.
    measure_route=(
        ("RET", "title", "key"), ("RET", "party_menu", "key"), ("L", "save_path", "key"),
        ("RET", "load_picker", "key"), ("A", "world", "key"), ("V", "sheet", "key"),
        ("E", "world", "key"), ("NP2", "world", "turn"), ("NP8", "world", "move"),
        ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
    ),
    boot_span=150.0,
    control_letter="C", after_letter="D", kept_letters=(POOL_LATER,), turn="about",
    strict=frozenset({"party_menu", "load_picker", "sheet", "world", "camp_save_picker"}),
    min_waits={"party_menu": 20.0, "load_picker": 10.0, "world": 20.0,
               "world_after_move": 5.0, "camp": 10.0, "camp_save_picker": 10.0,
               "quit_prompt": 20.0},
    interstitials=(
        ("wheel", ("keys", "RET"), frozenset({"title"}), 1),
        ("save_path", ("keys", "RET"), frozenset({"camp_save_picker"}), 1),
    ),
)



CURSE_DISK_B_SHA256 = "a6f94bb42664ab94b673bf0c7390420d94bec257ae09fea488a53504b6e1fca3"
CURSE_SPECIMEN_SHA256 = "752ed821e94cbedb96b7f8e8d4df09cd61e0c1a63c40ff2aab07d2c5203bcd71"
CURSE_SPECIMEN = ("coab-amiga", "WISH-SPEC-curse-c64toamiga-slotb-walked-saved-c",
                  "curseA-slotB-resave-C.adf")
CURSE_VOLUME = "CurseA"
CURSE_LOADED = "B"
# The specimen's own camp save, made after the same two steps north.
CURSE_LATER = "C"
CURSE_KEY = "curse-of-the-azure-bonds"

_CURSE_SAVED_GAME = re.compile(r"savgam([A-Z])\.dat", re.IGNORECASE)


def _curse_read_slot(disk: amiga_adf.AmigaDisk, letter: str) -> dict[str, Any]:
    """One Curse save slot in `/SAVE` of a fetched boot disk: `missing`, `decode_error`, or place and names."""
    try:
        raw = disk.read_file(f"/SAVE/savgam{letter}.dat")
    except amiga_adf.AmigaDiskError:
        return {"missing": True, "sha256": None}
    reading: dict[str, Any] = {"sha256": hashlib.sha256(raw).hexdigest()}
    try:
        saved = amiga_savegame.read_slot(disk, letter, CURSE_KEY)
        state = amiga_savegame.state_from_savegame(saved)
        reading["names"] = [member.name for member in saved.characters]
        reading["place"] = {"area": state.area, "x": state.x, "y": state.y,
                            "facing": state.facing}
    except Exception as exc:  # noqa: BLE001 - every reader failure is the verdict's `decode_error`
        reading.pop("names", None)
        reading["decode_error"] = f"{type(exc).__name__}: {exc}"
    return reading


def _curse_saves(disk: amiga_adf.AmigaDisk) -> list:
    return [e for e in disk.entries(disk.lookup("/SAVE").block) if not e.is_dir]


def _curse_slot_letters(disk: amiga_adf.AmigaDisk) -> list[str]:
    found = (_CURSE_SAVED_GAME.fullmatch(e.name) for e in _curse_saves(disk))
    return sorted(m.group(1).upper() for m in found if m)


def _curse_slot_files(disk: amiga_adf.AmigaDisk, letter: str) -> dict[str, bytes]:
    """The slot's saved game and `spindisk`, which a later save must leave alone."""
    return {e.name: disk.read_file(f"/SAVE/{e.name}") for e in _curse_saves(disk)
            if e.name.lower() in (f"savgam{letter}.dat".lower(), "spindisk")}


# The save picker offers ten letters, so F is free beside the specimen's A, B and C. The
# after slot is F because E is the game's own exit key on the sheet and at camp, and a
# save letter equal to a plain key cannot be told from it by the description.
CURSE = AmigaTitle(
    issue=ISSUE,
    mounted=("save", "diskb"),
    save_disk="save",
    read_slot=_curse_read_slot, slot_letters=_curse_slot_letters,
    slot_files=_curse_slot_files,
    route=(
        ("L", "load_picker", "key"), ("B", "loaded_menu", "key"), ("V", "sheet", "key"),
        ("E", "loaded_menu", "key"), ("S", "save_picker", "key"),
        ("D", "loaded_menu", "write"), ("B", "world", "key"),
        ("NP8", "world", "move"), ("NP8", "world", "move"),
        ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
        ("F", "exit_game", "write"), ("N", "camp", "key"),
    ),
    # Up to four ESCs leave the front end; two do on the measured disk, the first reaching
    # the copy-protection screen and the second the party menu, which is `title`. Stops before D.
    measure_route=(
        ("ESC", "front_end", "key"), ("ESC", "title", "key"),
        ("L", "load_picker", "key"), ("B", "loaded_menu", "key"),
        ("V", "sheet", "key"), ("E", "loaded_menu", "key"), ("S", "save_picker", "key"),
    ),
    boot_span=120.0,
    control_letter="D", after_letter="F", kept_letters=("A", "C"),
    strict=frozenset({"load_picker", "loaded_menu", "sheet", "save_picker",
                      "camp_save_picker"}),
    title_limit=300.0,
    min_waits={"load_picker": 10.0, "loaded_menu": 20.0, "sheet": 5.0, "save_picker": 10.0,
               "world": 20.0, "world_after_move": 5.0, "camp": 10.0,
               "camp_save_picker": 10.0, "exit_game": 20.0},
    interstitials=(
        # A cap: accept mode stops pressing once `title` is reached.
        ("front_end", ("keys", "ESC"), frozenset({"title"}), 4),
        ("intro", ("keys", "ESC"), frozenset({"title"}), 1),
        ("continue", ("keys", "RET"), frozenset({"world", "exit_game"}), 3),
    ),
)

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
# No step gives the game disk 2: whether a prompt for it appears is for the measuring boot
# to show, and a DF0 insert is decided after that. A, C, D and E stay unchanged; E is also
# the game's own exit key on the sheet and at camp, which `plain_keys` names.
DARKNESS = AmigaTitle(
    issue=ISSUE,
    mounted=("disk1", "disk3"),
    spares=("disk2",),
    save_disk="disk3",
    read_slot=_darkness_read_slot, slot_letters=_darkness_slot_letters,
    slot_files=_darkness_slot_files,
    route=(
        ("P", "play", "key"), ("P", "party_menu", "key"), ("L", "load_picker", "key"),
        ("B", "loaded_menu", "key"), ("V", "sheet", "key"), ("E", "loaded_menu", "key"),
        ("S", "save_picker", "key"), ("I", "loaded_menu", "write"), ("B", "world", "key"),
        ("NP8", "world", "move"), ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
        ("J", "camp", "write"),
    ),
    # Stops before I.
    measure_route=(
        ("P", "play", "key"),
        ("P", "party_menu", "key"), ("L", "load_picker", "key"), ("B", "loaded_menu", "key"),
        ("V", "sheet", "key"), ("E", "loaded_menu", "key"), ("S", "save_picker", "key"),
    ),
    # In the measured boot the settled captures ended at 27, 99, 153 (loading screens), 247 (the
    # first showing the title), 271, 297 (the same title) and 331 s (the demo) after the claim,
    # so the title appeared between 153 and 247 s and the demo began between 297 and 331 s: at
    # least 50 s later. The first key goes out about 8 s after the first capture that ends at or
    # after `boot_span` seconds from the start, so 225 puts it near 255 s, on the title; a title
    # 30 s slower would put it on a loading screen. Without a title guard this is a guess.
    boot_span=225.0, title_limit=420.0,
    control_letter="I", after_letter="J", kept_letters=("A", "C", "D", "E"),
    plain_keys=(("E", "loaded_menu"), ("E", "camp")),
    strict=frozenset({"party_menu", "load_picker", "loaded_menu", "sheet", "save_picker",
                      "camp_save_picker"}),
    min_waits={"play": 5.0, "party_menu": 20.0, "load_picker": 10.0, "loaded_menu": 20.0,
               "sheet": 5.0, "save_picker": 10.0, "world": 45.0, "world_after_move": 5.0,
               "camp": 10.0, "camp_save_picker": 10.0},
    interstitials=(
        ("journal", ("answer",), None, 1),
        ("yes_no", ("keys", "N"), frozenset({"world"}), 1),
        ("continue", ("keys", "RET"), frozenset({"world"}), 3),
    ),
)

TITLES: dict[str, AmigaTitle] = {"pool": POOL, "curse": CURSE, "darkness": DARKNESS}


def _find_images(wanted: dict[str, str]) -> dict[str, tuple[str, bytes]]:
    """Each wanted key's registered image, found by its SHA-256 inside the zips too: `{key: (label, bytes)}`."""
    found: dict[str, tuple[str, bytes]] = {}
    for label, data in amigasaves.images():
        digest = hashlib.sha256(data).hexdigest()
        for key, pinned in wanted.items():
            if digest == pinned and key not in found:
                found[key] = (label, data)
    missing = [key for key in wanted if key not in found]
    if missing:
        raise RouteError(f"registered image {missing} was not found by its SHA-256")
    return found


@dataclasses.dataclass(frozen=True)
class _Sources:
    """The registered specimen and disks a title's run starts from."""

    name: str
    title: AmigaTitle
    specimen: tuple[str, ...]
    specimen_sha256: str
    volume: str
    loaded: str
    later: str
    images: dict[str, str]


def _prepare_from(src: _Sources, run: pathlib.Path, specimen: pathlib.Path | None
                  ) -> dict[str, Any]:
    title = src.title
    specimen = (pathlib.Path(specimen) if specimen
                else specimens.tree_root().joinpath(*src.specimen))
    if not specimen.is_file():
        raise RouteError(f"the specimen {specimen} is missing")
    if sha256(specimen) != src.specimen_sha256:
        raise RouteError(f"the specimen SHA-256 differs: {sha256(specimen)}")
    save = amiga_adf.AmigaDisk.open(specimen)
    if save.verify() or save.volume_name != src.volume:
        raise RouteError(f"{specimen} is not a verified {src.volume} disk")
    present = title.slot_letters(save)
    for taken in (title.control_letter, title.after_letter):
        if taken in present:
            raise RouteError(f"slot {taken} already exists on the specimen")
    loaded, later = title.read_slot(save, src.loaded), title.read_slot(save, src.later)
    for letter, reading in ((src.loaded, loaded), (src.later, later)):
        if "place" not in reading:
            raise RouteError(f"specimen slot {letter} does not decode: {reading}")
    images = _find_images(src.images)
    scratch.ensure(run)
    disks: dict[str, dict[str, str]] = {}
    for key, (_label, data) in images.items():
        path = run / f"{key}.adf"
        path.write_bytes(data)
        disks[key] = {"path": str(path), "sha256": sha256(path)}
    working = run / "save.adf"
    shutil.copyfile(specimen, working)
    disks["save"] = {"path": str(working), "sha256": sha256(working)}
    if any(disks[key]["sha256"] != pinned for key, pinned in src.images.items()):
        raise RouteError("a working copy differs from the pinned disk")
    if disks["save"]["sha256"] != src.specimen_sha256:
        raise RouteError("the working save disk differs from the specimen")
    # A registered image inside a zip has no file of its own, so `registered` holds the
    # specimen and `sources` names each image by where it was found.
    manifest = {
        "title": src.name, "disks": disks,
        "registered": {"specimen": {"path": str(specimen), "sha256": sha256(specimen)}},
        "sources": {key: {"label": label, "sha256": src.images[key]}
                    for key, (label, _data) in images.items()},
        "loaded_letter": src.loaded,
        "state_a": loaded["place"], "names_a": loaded["names"],
        "expected_after": later["place"],
    }
    after = _find_images(src.images)
    if (sha256(specimen) != src.specimen_sha256
            or any(hashlib.sha256(after[key][1]).hexdigest() != pinned
                   for key, pinned in src.images.items())):
        raise RouteError("a registered image changed during preparation")
    return manifest


POOL_SOURCES = _Sources("pool", POOL, POOL_SPECIMEN, POOL_SPECIMEN_SHA256, POOL_VOLUME,
                        POOL_LOADED, POOL_LATER,
                        {"disk1": POOL_DISK1_SHA256, "disk2": POOL_DISK2_SHA256})
CURSE_SOURCES = _Sources("curse", CURSE, CURSE_SPECIMEN, CURSE_SPECIMEN_SHA256, CURSE_VOLUME,
                         CURSE_LOADED, CURSE_LATER, {"diskb": CURSE_DISK_B_SHA256})


def _prepare_pool(run: pathlib.Path, specimen: pathlib.Path | None) -> dict[str, Any]:
    return _prepare_from(POOL_SOURCES, run, specimen)


def _prepare_curse(run: pathlib.Path, specimen: pathlib.Path | None) -> dict[str, Any]:
    return _prepare_from(CURSE_SOURCES, run, specimen)


def _prepare_darkness(run: pathlib.Path, override: pathlib.Path | None) -> dict[str, Any]:
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
    loaded = DARKNESS.read_slot(save, DARKNESS_LOADED)
    if "place" not in loaded:
        raise RouteError(f"slot {DARKNESS_LOADED} does not decode: {loaded}")
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
        "loaded_letter": DARKNESS_LOADED,
        "state_a": loaded["place"], "names_a": loaded["names"],
    }
    after = _find_images({k: v for k, v in wanted.items() if override is None or k != "disk3"})
    if any(hashlib.sha256(after[key][1]).hexdigest() != wanted[key] for key in after):
        raise RouteError("a registered image changed during preparation")
    return manifest


_PREPARE = {"pool": _prepare_pool, "curse": _prepare_curse, "darkness": _prepare_darkness}


def _name(title: AmigaTitle) -> str:
    for name, known in TITLES.items():
        if known is title:
            return name
    raise RouteError("that is not one of this module's titles")


def prepare(title: AmigaTitle, run_id: str, *, specimen: pathlib.Path | None = None
            ) -> pathlib.Path:
    """Copy the title's registered images and specimen into a run folder, write `prepare.json`, and return it.

    Refuses when any pinned hash differs, the loaded slot does not decode, or a
    save letter the run writes already exists. Nothing registered is written.
    """
    if not HOLDER.fullmatch(run_id):
        raise RouteError("run id must use letters, digits, dot, underscore or hyphen")
    name = _name(title)
    run = scratch.cache_dir("acceptance", ISSUE, run_id)
    if run.exists():
        raise RouteError(f"run folder already exists: {run}")
    manifest = _PREPARE[name](run, specimen)
    path = run / "prepare.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def _summary(result: dict[str, Any], manifest: pathlib.Path, attempt: str) -> str:
    return json.dumps({"success": result["success"], "error": result["error"],
                       "unguarded": result["unguarded"],
                       "summary": str(manifest.parent / attempt / "summary.json")},
                      sort_keys=True)


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
    m = sub.add_parser("measure", help="boot and press the route up to the first save; writes nothing")
    common(m)
    m.add_argument("--guards", type=pathlib.Path, default=None,
                   help="screen guard JSON; a route state it holds must match, and the boot waits for its title")
    a = sub.add_parser("accept", help="guarded load, sheet, two saves around a walk and the read-back")
    common(a)
    a.add_argument("--guards", required=True, type=pathlib.Path)
    a.add_argument("--identity", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        with terminating():
            if args.command == "prepare":
                print(prepare(TITLES[args.title], args.run_id))
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
                    deadline_seconds=args.deadline, accept=True, title=title)
            print(_summary(result, args.manifest, args.attempt))
            for line in result.get("read", {}).get("verdicts", []):
                print(line)
            return 0 if result["success"] else 1
    except (RouteError, OSError, ValueError) as exc:
        print(f"amigafoundation: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
