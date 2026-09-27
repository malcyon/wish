"""Pool of Radiance: pins, readers and the description of its load, save and read-back route."""

from __future__ import annotations

import hashlib
import pathlib
import re
from typing import Any

from goldbox import amiga_adf, amiga_savegame
from tools.amiga import amigaporslot
from tools.amiga.route import ISSUE, AmigaTitle, effect_fields
from tools.amiga.staging import _prepare_from, _Sources

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
        names = [_pool_name(member.name) for member in party]
        place = {"area": state.area, "x": state.x, "y": state.y, "facing": state.facing}
        characters = amiga_savegame.read_por_characters(disk, letter, drawer="")
        effects = {_pool_name(char.name): [list(effect_fields(node)) for node in char.effects]
                  for char in characters}
    except Exception as exc:  # noqa: BLE001 - every reader failure is the verdict's `decode_error`
        reading["decode_error"] = f"{type(exc).__name__}: {exc}"
        return reading
    reading["names"] = names
    reading["place"] = place
    reading["effects"] = effects
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


POOL_SOURCES = _Sources("pool", POOL, POOL_SPECIMEN, POOL_SPECIMEN_SHA256, POOL_VOLUME,
                        POOL_LOADED, POOL_LATER,
                        {"disk1": POOL_DISK1_SHA256, "disk2": POOL_DISK2_SHA256},
                        amigaporslot.import_slot)


def _prepare_pool(run: pathlib.Path, specimen: pathlib.Path | None, *,
                  substitute: pathlib.Path | None = None, substitute_letter: str = "A"
                  ) -> dict[str, Any]:
    return _prepare_from(POOL_SOURCES, run, specimen,
                         substitute=substitute, substitute_letter=substitute_letter)
