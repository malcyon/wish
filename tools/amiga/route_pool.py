"""Pool of Radiance: pins, readers and the description of its load, save and read-back route."""

from __future__ import annotations

import dataclasses
import hashlib
import pathlib
import re
from collections.abc import Callable
from typing import Any

from goldbox import amiga_adf, amiga_savegame, areas, geo
from goldbox.geo import load_geo_files
from tools.amiga import amigaporslot
from tools.amiga.route import ISSUE, AmigaTitle, RouteError, effect_fields
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


_ABOUT_STEP = ("NP2", "world", "turn")


def _without_turn(route: tuple) -> tuple:
    return tuple(step for step in route if step != _ABOUT_STEP)


#: The same route for a party that walks out the way it faces, with no turn about.
POOL_FORWARD = dataclasses.replace(
    POOL, route=_without_turn(POOL.route), measure_route=_without_turn(POOL.measure_route),
    turn=None)


def _walkable(walls: geo.Geo, x: int, y: int, direction: int) -> bool:
    """No wall on the edge, or a door standing open; a solid wall and a locked door are not."""
    return (walls.wall(x, y, direction) == 0
            or walls.barrier(x, y, direction) == geo.PASSABLE)


def _disk_geo(name: str) -> geo.Geo:
    from automap.paths import (
        tool_disks,  # noqa: PLC0415 - the player's disks, only when asked
    )
    from tools.areas import geomap  # noqa: PLC0415
    root = tool_disks()
    if root is None:
        raise RouteError(f"the game disks are not found, so the wall data {name} cannot be read "
                         "and the route's step cannot be checked")
    for path in geomap.game_disks(root):
        found = load_geo_files(path)
        if name in found:
            return found[name]
    raise RouteError(f"the wall data {name} is not on the game disks, so the route's "
                     "step cannot be checked")


def pool_turns_about(place: dict, *,
                     load_geo: Callable[[str], geo.Geo] | None = None) -> bool:
    """Whether the route turns the party about before its one step, from the start square's own walls.

    The route turns about unless that edge is closed and the edge the party
    faces is open. An area with more than one map cannot say which the game
    loaded, so it keeps the turn about.
    """
    try:
        number, x, y, facing = place["area"], place["x"], place["y"], place["facing"]
    except (KeyError, TypeError) as exc:
        raise RouteError(f"the recorded place {place!r} lacks an area, x, y or facing") from exc
    area = areas.area_in(number, areas.POOL_OF_RADIANCE)
    if area is None or area.geo is None:
        return True
    walls = (load_geo or _disk_geo)(area.geo)
    if _walkable(walls, x, y, geo.OPPOSITE[facing]):
        return True
    if _walkable(walls, x, y, facing):
        return False
    raise RouteError(f"area {place['area']} ({x},{y}) has no open edge ahead or behind "
                     f"facing {facing}, so the route has no step to take")


def pool_title_for(manifest: dict, *,
                   load_geo: Callable[[str], geo.Geo] | None = None) -> AmigaTitle:
    """The route this manifest's start square needs, refusing a recorded `turn_about` its walls contradict.

    A manifest with no `turn_about` predates the choice and keeps the turn about.
    """
    if "turn_about" not in manifest:
        return POOL
    turn_about = manifest["turn_about"]
    if not isinstance(turn_about, bool):
        raise RouteError("the manifest turn_about is not a boolean")
    if "state_a" not in manifest:
        raise RouteError("the manifest has a turn_about but no state_a to check it against")
    if turn_about != pool_turns_about(manifest["state_a"], load_geo=load_geo):
        raise RouteError("the manifest turn_about disagrees with its recorded place")
    return POOL if turn_about else POOL_FORWARD


POOL_SOURCES = _Sources("pool", POOL, POOL_SPECIMEN, POOL_SPECIMEN_SHA256, POOL_VOLUME,
                        POOL_LOADED, POOL_LATER,
                        {"disk1": POOL_DISK1_SHA256, "disk2": POOL_DISK2_SHA256},
                        amigaporslot.import_slot)


def _prepare_pool(run: pathlib.Path, specimen: pathlib.Path | None, *,
                  substitute: pathlib.Path | None = None, substitute_letter: str = "A"
                  ) -> dict[str, Any]:
    manifest = _prepare_from(POOL_SOURCES, run, specimen,
                             substitute=substitute, substitute_letter=substitute_letter)
    manifest["turn_about"] = pool_turns_about(manifest["state_a"])
    return manifest
