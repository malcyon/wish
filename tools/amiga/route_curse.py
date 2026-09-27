"""Curse of the Azure Bonds: pins, readers and the description of its load, save and read-back route."""

from __future__ import annotations

import hashlib
import pathlib
import re
from typing import Any

from goldbox import amiga_adf, amiga_savegame
from tools.amiga.route import ISSUE, AmigaTitle
from tools.amiga.staging import _prepare_from, _Sources

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
        # Caps: accept mode stops pressing once `title` is reached, but the two rows together
        # allow up to five ESCs while it waits.
        ("front_end", ("keys", "ESC"), frozenset({"title"}), 4),
        ("intro", ("keys", "ESC"), frozenset({"title"}), 1),
        ("continue", ("keys", "RET"), frozenset({"world", "exit_game"}), 3),
    ),
)


CURSE_SOURCES = _Sources("curse", CURSE, CURSE_SPECIMEN, CURSE_SPECIMEN_SHA256, CURSE_VOLUME,
                         CURSE_LOADED, CURSE_LATER, {"diskb": CURSE_DISK_B_SHA256})


def _prepare_curse(run: pathlib.Path, specimen: pathlib.Path | None) -> dict[str, Any]:
    return _prepare_from(CURSE_SOURCES, run, specimen)
