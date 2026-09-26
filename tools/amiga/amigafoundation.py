#!/usr/bin/env python3
"""Prepare, measure and accept one Amiga title's load, inspect, move, save and read-back run under WinUAE."""

from __future__ import annotations

import argparse
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

TITLES: dict[str, AmigaTitle] = {"pool": POOL}


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


def _prepare_pool(run: pathlib.Path, specimen: pathlib.Path | None) -> dict[str, Any]:
    specimen = pathlib.Path(specimen) if specimen else specimens.tree_root().joinpath(*POOL_SPECIMEN)
    if not specimen.is_file():
        raise RouteError(f"the specimen {specimen} is missing")
    if sha256(specimen) != POOL_SPECIMEN_SHA256:
        raise RouteError(f"the specimen SHA-256 differs: {sha256(specimen)}")
    save = amiga_adf.AmigaDisk.open(specimen)
    if save.verify() or save.volume_name != POOL_VOLUME:
        raise RouteError(f"{specimen} is not a verified {POOL_VOLUME} disk")
    present = POOL.slot_letters(save)
    for taken in (POOL.control_letter, POOL.after_letter):
        if taken in present:
            raise RouteError(f"slot {taken} already exists on the specimen")
    loaded, later = POOL.read_slot(save, POOL_LOADED), POOL.read_slot(save, POOL_LATER)
    for letter, reading in ((POOL_LOADED, loaded), (POOL_LATER, later)):
        if "place" not in reading:
            raise RouteError(f"specimen slot {letter} does not decode: {reading}")
    wanted = {"disk1": POOL_DISK1_SHA256, "disk2": POOL_DISK2_SHA256}
    images = _find_images(wanted)
    scratch.ensure(run)
    disks: dict[str, dict[str, str]] = {}
    for key, (_label, data) in images.items():
        path = run / f"{key}.adf"
        path.write_bytes(data)
        disks[key] = {"path": str(path), "sha256": sha256(path)}
    working = run / "save.adf"
    shutil.copyfile(specimen, working)
    disks["save"] = {"path": str(working), "sha256": sha256(working)}
    if any(disks[key]["sha256"] != pinned for key, pinned in wanted.items()):
        raise RouteError("a working copy differs from the pinned disk")
    if disks["save"]["sha256"] != POOL_SPECIMEN_SHA256:
        raise RouteError("the working save disk differs from the specimen")
    # A registered image inside a zip has no file of its own, so `registered` holds the
    # specimen and `sources` names each image by where it was found.
    manifest = {
        "title": "pool", "disks": disks,
        "registered": {"specimen": {"path": str(specimen), "sha256": sha256(specimen)}},
        "sources": {key: {"label": label, "sha256": wanted[key]}
                    for key, (label, _data) in images.items()},
        "loaded_letter": POOL_LOADED,
        "state_a": loaded["place"], "names_a": loaded["names"],
        "expected_after": later["place"],
    }
    after = _find_images(wanted)
    if (sha256(specimen) != POOL_SPECIMEN_SHA256
            or any(hashlib.sha256(after[key][1]).hexdigest() != pinned
                   for key, pinned in wanted.items())):
        raise RouteError("a registered image changed during preparation")
    return manifest


_PREPARE = {"pool": _prepare_pool}


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
    common(sub.add_parser("measure", help="boot and press the route up to the first save; writes nothing"))
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
