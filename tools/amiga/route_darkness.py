"""Pools of Darkness: pins, readers and the description of its load, save, read-back and reload routes."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import re
import shutil
import struct
from typing import Any

from goldbox import amiga_adf, amiga_pod, amiga_savegame, dos_codec
from tools.amiga import route_camp
from tools.amiga.route import ISSUE, AmigaTitle, effect_fields, outdoor_square
from tools.amiga.staging import _find_images, sha256
from tools.amiga.winuaesession import RouteError
from tools.registry import scratch

DARKNESS_DISK1_SHA256 = "9d38338ecb44434331485a908b0d6c204f9b0a8a6e509baa2a8e1b24e892b3ee"
DARKNESS_DISK2_SHA256 = "f7819b475e4071c36d349003277e9516abfee8f9c294830d8423e98a9e6c7b71"
DARKNESS_DISK3_SHA256 = "bba0945c39e54fee75e4453e552a54534a584a395f9796ca570c655bf02f2fdd"
DARKNESS_VOLUME = "POD 3"
# Columns and rows of the overland map; `NP8` steps north on it and the game stops at the edge.
WILDERNESS_GRID = (38, 15)
DARKNESS_LOADED = "B"

_DARKNESS_SAVED_GAME = re.compile(r"savgam([A-Z])\.pty", re.IGNORECASE)


def _darkness_read_slot(disk: amiga_adf.AmigaDisk, letter: str) -> dict[str, Any]:
    """One Pools of Darkness slot in `/Save` of disk 3: `missing`, `decode_error`, or place, names and effects."""
    try:
        raw = disk.read_file(amiga_savegame.pod_slot_path(letter))
    except amiga_adf.AmigaDiskError:
        return {"missing": True, "sha256": None}
    reading: dict[str, Any] = {"sha256": hashlib.sha256(raw).hexdigest()}
    try:
        data = amiga_savegame.pod_read_slot(disk, letter)
        state = amiga_savegame.pod_from_amiga(data)
        parsed = amiga_savegame.pod_parse(data)
        reading["names"] = [member.name.strip() for member in parsed.characters]
        reading["place"] = {"area": state.dungeon_map, "x": state.x, "y": state.y,
                            "facing": state.facing}
        # Outdoors the game steps on the wilderness grid and leaves the dungeon square stale.
        reading["in_dungeon"] = state.in_dungeon
        reading["wilderness_square"] = list(state.wilderness_square)
        reading["effects"] = {member.name.strip(): [list(effect_fields(node)) for node in nodes]
                              for member, nodes in zip(parsed.characters, parsed.effect_nodes,
                                                       strict=True)}
    except Exception as exc:  # noqa: BLE001 - every reader failure is the verdict's `decode_error`
        reading.pop("names", None)
        reading.pop("effects", None)
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

#: ESC on a picture page of the intro ends the intro and shows the PLAY / DEMO / QUIT title within
#: about two seconds. Left alone, the intro's pages brought the title 238 to 408 s after the start,
#: and a boot on a loaded VM was still on them at 420 s. At most three presses, only while waiting
#: for the title.
DARKNESS_INTRO = ("intro", ("keys", "ESC"), frozenset({"title"}), 3)

DARKNESS = AmigaTitle(
    issue=ISSUE,
    mounted=("disk1", "disk3"), spares=("disk2",),
    save_disk="disk3", wilderness_grid=WILDERNESS_GRID,
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
        DARKNESS_INTRO,
        ("yes_no", ("keys", "N"), frozenset({"world"}), 1),
        ("continue", ("keys", "RET"), frozenset({"world"}), 3),
        # FLEE's key is the control letter, so the row presses it only where the `encounter`
        # guard matches the encounter bar; `run_recon` then presses the move again.
        ("encounter", ("keys", "F"), frozenset({"world"}), 1),
    ),
    interstitial_letters=(("F", "encounter"),),
    move_again_after=frozenset({"encounter"}),
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


#: Elminster's menu in Limbo (area 18), the only place the game offers the item vault. A party
#: saved there opens on it after the journal, whatever square it stands on, and `S` is its
#: `STORAGE`. The vault's bar is `View Pool Money Items Exit`; `T` opens `TAKE: MONEY ITEMS EXIT`,
#: which has a Money word only when the vault holds coins, and `I` lists the stored items with
#: `NP2` moving the highlight one row. The menu guard is cut; the others are not, so a measure
#: boot settles each of them.
VAULT_MENU = "elminster_menu"
VAULT_STORAGE = "vault_bar"
VAULT_TAKE = "vault_take"
VAULT_ITEMS = "vault_items"
VAULT_ROW = "vault_row"
#: What the default title holds: the 40-item vault with coins that the DOS game wrote.
VAULT_DEFAULT_ITEMS = 40


def camp_in_place_title(title: AmigaTitle) -> AmigaTitle:
    """`title` with its walk steps dropped, so the route goes from the loaded menu to camp where the party stands.

    For a party whose next square holds a scripted prompt the route has no answer for.
    Camp entry and every guard after it are unchanged.
    """
    def without_walk(route: tuple) -> tuple:
        return tuple(step for step in route if step[2] != "move")

    if without_walk(title.route) == title.route:
        raise RouteError("the route has no walk step to skip")
    return dataclasses.replace(title, route=without_walk(title.route),
                               measure_route=without_walk(title.measure_route))


def vault_steps(items: int, coins: bool) -> tuple[tuple[str, str, str], ...]:
    """From Elminster's menu: open the vault, move the highlight to its last item, and come back to the menu.

    The first row is highlighted when the list opens, so `items - 1` presses reach the last one.
    A vault with coins puts the TAKE bar between the vault bar and the list.
    The bound is the item pool size, an upper bound on any vault file the harness may meet; the
    party's own items share the pool, so the converter writes at most 445 minus the party's items.
    """
    if not 1 <= items <= amiga_savegame.POD_POOL_NODES:
        raise RouteError(f"a vault run lists 1 to {amiga_savegame.POD_POOL_NODES} items (the item "
                         f"pool size, not the reachable vault size), not {items}")
    return (
        ("S", VAULT_STORAGE, "key"),
        ("T", VAULT_TAKE if coins else VAULT_ITEMS, "key"),
        *((("I", VAULT_ITEMS, "key"),) if coins else ()),
        *(("NP2", VAULT_ROW, "key") for _ in range(items - 1)),
        *((("E", VAULT_TAKE, "key"),) if coins else ()),
        ("E", VAULT_STORAGE, "key"), ("E", VAULT_MENU, "key"),
    )


def vault_title(items: int = VAULT_DEFAULT_ITEMS, coins: bool = True) -> AmigaTitle:
    """`DARKNESS` loading a party saved in area 18: the vault, then the camp loop, a save and the exit.

    `REST` on Elminster's menu opens the camp loop, which is how the party gets back to the
    camp save. The vault states are not strict, so a screen the guard map lacks is settled and
    the run is marked as measuring; the camp save's picker still stops a run before any write.
    """
    added = vault_steps(items, coins)

    def vault_route(route: tuple) -> tuple:
        steps = list(route)
        at = steps.index(("RET", "world", "key"))
        steps[at:at + 1] = [("RET", VAULT_MENU, "key"), *added]
        # The walk step and the camp key follow the world; here the menu's `REST` opens the camp.
        steps[at + 1 + len(added):steps.index(("S", "camp_save_picker", "key"))] = [
            ("R", "camp", "key")]
        return tuple(steps)

    states = {state for _, state, _ in added}
    return dataclasses.replace(
        DARKNESS, route=vault_route(DARKNESS.route),
        measure_route=vault_route(DARKNESS.measure_route),
        plain_keys=(("E", "loaded_menu"), *((("E", VAULT_TAKE),) if coins else ()),
                    ("E", VAULT_STORAGE), ("E", VAULT_MENU)),
        strict=(DARKNESS.strict - {"world"}) | {VAULT_MENU},
        # The route never expects `world`, the only state the other inherited rows answer.
        interstitials=(DARKNESS_INTRO,), interstitial_letters=(), move_again_after=frozenset(),
        min_waits={**DARKNESS.min_waits, VAULT_MENU: 45.0,
                   **{state: 10.0 for state in states}, VAULT_ROW: route_camp.ROW_WAIT},
    )


DARKNESS_VAULT = vault_title()

#: The manifest key of a second save disk, staged with `prepare --spare-disk` and put in DF1 by
#: the route's `swap-df1` steps. The game saves to whichever disk with a `SAVE` drawer is in DF1.
SPARE = "spare"
#: `INSERT DISK 3 AND PRESS A KEY`, which the game shows after loading a slot from a disk that is
#: not disk 3, in the strip where it asks for disk 2.
DISK3_PROMPT = "disk3_prompt"
#: What `T` shows on the vault bar of a vault with no items and no coins; no guard is cut for it.
VAULT_EMPTY = "vault_empty"
_CAMP_SAVE = ("S", "camp_save_picker", "key")
_QUIT_NO = ("N", "camp", "key")


def swap_df1(disk_key: str, step: tuple) -> tuple:
    """The route step `swap-df1 <disk_key>`: put that disk in DF1, then press `step`'s key.

    It is an `insert` step on drive 1, so the screen before it must be a strict state.
    """
    key, state, kind = step
    if kind != "key":
        raise RouteError(f"swap-df1 goes before a key step, not {step!r}")
    return ((1, disk_key, key), state, "insert")


def spare_save_title(title: AmigaTitle) -> AmigaTitle:
    """`title` with its camp save made on the spare disk instead of disk 3.

    `swap-df1 spare` comes before the `S` that opens the camp save picker and `swap-df1 disk3`
    before the `N` that answers the quit question after the save. The control save at the
    loaded menu stays on disk 3, so one boot saves the same party to both disks.
    """
    def swapped(route: tuple) -> tuple:
        if _CAMP_SAVE not in route:
            raise RouteError("the route has no camp save to make on the spare disk")
        out: list[tuple] = []
        for step in route:
            if step == _CAMP_SAVE:
                out.append(swap_df1(SPARE, step))
            elif step == _QUIT_NO:
                if not out or out[-1][1] != "exit_game":
                    raise RouteError("the route's quit answer does not follow exit_game, so "
                                     "disk 3 cannot be put back before it")
                out.append(swap_df1("disk3", step))
            else:
                out.append(step)
        return tuple(out)

    if SPARE in title.disk_keys:
        raise RouteError("the route already has a spare disk")
    return dataclasses.replace(title, spares=(*title.spares, SPARE), route=swapped(title.route),
                               measure_route=swapped(title.measure_route))


def spare_reload_title(loaded: str, items: int, coins: bool,
                       kept: tuple[str, ...] = ()) -> AmigaTitle:
    """Load `loaded` from the spare disk and open Elminster's vault, writing nothing.

    `swap-df1 spare` comes before `L` at the party menu, so the load picker lists the spare's
    slots; after the slot letter the game asks for disk 3, which `swap-df1 disk3` answers, and
    then for disk 2 in DF0. The vault steps list `items` rows; a vault with none goes as far as
    the screen `T` opens, which settles unguarded. Like `DARKNESS_UNSTARTED` it runs as
    `measure`, so it names two free letters as its save letters and never presses them.
    """
    control, after, _kept = published_letters(loaded, (loaded, *kept))
    vault = (vault_steps(items, coins) if items
             else (("S", VAULT_STORAGE, "key"), ("T", VAULT_EMPTY, "key")))
    route = (
        ("P", "party_menu", "key"), swap_df1(SPARE, ("L", "load_from", "key")),
        ("P", "load_picker", "key"), (loaded, DISK3_PROMPT, "key"),
        swap_df1("disk3", ("SPACE", "disk2_prompt", "key")), DISK2_INSERT,
        ("V", "sheet", "key"), ("E", "loaded_menu", "key"),
        ("B", "journal", "key"), ("X", "journal_answer", "key"), ("RET", VAULT_MENU, "key"),
        *vault,
    )
    states = {state for _, state, _ in vault}
    return dataclasses.replace(
        DARKNESS_RELOAD, spares=(*DARKNESS.spares, SPARE), save_disk=SPARE,
        route=route, measure_route=route, kept_letters=tuple(kept),
        control_letter=control, after_letter=after,
        plain_keys=tuple(e for e in _SIMPLE_KEY_STATES[:2] if e[0] in kept),
        strict=frozenset({"party_menu", "load_from", "load_picker", DISK3_PROMPT, "disk2_prompt",
                          "loaded_menu", "sheet", "journal", "journal_answer", VAULT_MENU}),
        interstitials=(DARKNESS_INTRO,), interstitial_letters=(), move_again_after=frozenset(),
        min_waits={**DARKNESS.min_waits, DISK3_PROMPT: 10.0, VAULT_MENU: 45.0,
                   **{state: 10.0 for state in states}, VAULT_ROW: route_camp.ROW_WAIT},
    )


def vault_evidence(disk: amiga_adf.AmigaDisk, letter: str) -> dict[str, Any] | None:
    """`_vault_reading` of `letter`'s vault on `disk`, or None when the disk holds no such file."""
    try:
        disk.lookup(amiga_savegame.pod_vault_path(letter))
    except amiga_adf.AmigaDiskError:
        return None
    return _vault_reading(disk, letter)


def _check_spare(spare: pathlib.Path) -> dict[str, Any]:
    """A spare save disk that verifies, has a `SAVE` drawer and holds no saved game: its record."""
    spare = pathlib.Path(spare)
    if not spare.is_file():
        raise RouteError(f"the spare disk {spare} is missing")
    try:
        disk = amiga_adf.AmigaDisk.open(spare)
        problems = disk.verify()
        if problems:
            raise RouteError(f"the spare disk {spare} fails ADF verification: {problems}")
        held = _darkness_slot_letters(disk)
        files = sorted(path for path, _entry in disk.walk())
    except amiga_adf.AmigaDiskError as exc:
        raise RouteError(f"the spare disk {spare} has no readable SAVE drawer: {exc}") from exc
    if held:
        raise RouteError(f"the spare disk {spare} already holds saved games {held}")
    for path in files:
        name = path.rsplit("/", 1)[-1].lower()
        if name.startswith("vault") and name.endswith(".dat"):
            try:
                vault = amiga_savegame.pod_vault_from_amiga(disk.read_file(path))
            except (amiga_adf.AmigaDiskError, ValueError) as exc:
                raise RouteError(f"the spare disk {spare} holds an unreadable vault "
                                 f"{path}: {exc}") from exc
            if vault != dos_codec.EMPTY_POD_VAULT:
                raise RouteError(f"the spare disk {spare} is not blank: {path} holds items or coins")
    return {"path": str(spare), "sha256": sha256(spare), "volume": disk.volume_name,
            "files": files}


def _darkness_import_slot(dest: amiga_adf.AmigaDisk, dest_letter: str,
                          source: amiga_adf.AmigaDisk, source_letter: str) -> bytes:
    """Replace `dest`'s `SavGam<dest_letter>.pty` with `source`'s slot and return the bytes written.

    A slot that is missing, or that the Pools of Darkness reader rejects, stops the call with an
    error. The existing file's own name case stays and no other file, `Vault<L>.DAT` included, is touched.
    """
    data = amiga_savegame.pod_read_slot(source, source_letter)
    amiga_savegame.pod_from_amiga(data)
    amiga_savegame.pod_parse(data)
    path = amiga_savegame.pod_slot_path(dest_letter)
    name = dest.lookup(path).name
    dest.remove_file(path)
    dest.write_file(path.rsplit("/", 1)[0] + "/" + name, data)
    return data


def _darkness_import_vault(dest: amiga_adf.AmigaDisk, dest_letter: str,
                           source: amiga_adf.AmigaDisk, source_letter: str) -> bytes:
    """Replace `dest`'s `Vault<dest_letter>.DAT` with `source`'s vault and return the bytes written.

    A source with no vault file, or one the reader rejects, stops the call with an error: the
    converter always writes a vault, so a missing one means the disk is wrong. The existing
    file's own name case stays and no other file is touched.
    """
    source_path = amiga_savegame.pod_vault_path(source_letter)
    try:
        data = source.read_file(source_path)
    except amiga_adf.AmigaDiskError as exc:
        raise RouteError(f"the substitute holds no vault {source_letter}: {exc}") from exc
    amiga_savegame.pod_vault_from_amiga(data)
    path = amiga_savegame.pod_vault_path(dest_letter)
    try:
        name = dest.lookup(path).name
    except amiga_adf.AmigaDiskError:
        name = path.rsplit("/", 1)[1]
    else:
        dest.remove_file(path)
    dest.write_file(path.rsplit("/", 1)[0] + "/" + name, data)
    return data


def _vault_reading(disk: amiga_adf.AmigaDisk, letter: str) -> dict[str, Any]:
    """The loaded slot's vault as the vault screen lists it: its rows, its coins and its hash.

    `items` is the file's own count of top-level entries, a scroll case being one row, which is
    what the `NP2` presses of `vault_steps` walk.
    """
    data = disk.read_file(amiga_savegame.pod_vault_path(letter))
    vault = amiga_savegame.pod_vault_from_amiga(data)
    rows = struct.unpack_from(">H", data, amiga_savegame.POD_VAULT_HEADER + 2)[0]
    return {"items": rows, "coins": [vault.platinum, vault.gems, vault.jewelry],
            "sha256": hashlib.sha256(data).hexdigest()}


def _seeded_vault_bytes(data: bytes, rows: int) -> bytes:
    """`data`, a game-written vault file, cut to its first `rows` top-level rows and no coins.

    A scroll case is one row and keeps its chained nodes. The count is patched, and the bytes
    after the kept rows are the file's own padding followed, to keep the file's size, by its
    bytes at the offsets that remain, so no converter writes any of the seed. Raises
    `AmigaSaveError` unless 1 <= `rows` < the file's own row count.
    """
    header = amiga_savegame.POD_VAULT_HEADER
    node = amiga_savegame.POD_ITEM_BYTES
    total = struct.unpack_from(">H", data, header + 2)[0]
    if not 1 <= rows < total:
        raise amiga_savegame.AmigaSaveError(
            f"a spare seed of {rows} rows must be at least 1 and below the {total} rows "
            "the staged vault file holds")
    at, ends = header + 4, []
    for _row in range(total):
        if at + node > len(data):
            raise amiga_savegame.AmigaSaveError(f"the vault's item list runs off the end at byte {at}")
        item = amiga_pod.PodItem.from_bytes(data[at:at + node])
        at += node * (1 + (item.quantity if item.is_scroll else 0))
        ends.append(at)
    if ends[-1] > len(data):
        raise amiga_savegame.AmigaSaveError("the vault's last scroll case runs off the end")
    out = bytearray(bytes(header) + data[header:header + 2] + struct.pack(">H", rows)
                    + data[header + 4:ends[rows - 1]] + data[ends[-1]:])
    out += data[len(out):]
    return bytes(out)


def _prepare_darkness(run: pathlib.Path, override: pathlib.Path | None,
                      loaded: str = DARKNESS_LOADED, *, substitute: pathlib.Path | None = None,
                      substitute_letter: str = "A", vault: bool = False,
                      spare: pathlib.Path | None = None,
                      spare_seed_rows: int | None = None) -> dict[str, Any]:
    """Disk 3 is itself the registered save disk, so `override` stands in for it and no specimen file exists.

    `substitute`, a disk some other tool wrote a party onto, has its `substitute_letter` slot
    replace the loaded slot on the run's working disk 3 (`_darkness_import_slot`); the pinned
    disks and the loaded slot's letter are unchanged, and `state_a` and `names_a` describe the
    substituted party.

    With `vault`, the substitute's vault is copied into the loaded letter's vault as well, the
    run stops before any disk is written when that vault holds no items, and the manifest's
    `vault` records its rows, coins and hash.

    `spare`, a save disk with a `SAVE` drawer and no saved game, is copied into the run as the
    disk `SPARE`, which the route puts in DF1 for the camp save (`spare_save_title`); the
    manifest's `spare` records where it came from.

    `spare_seed_rows` (with `vault` and `spare`) writes the first N rows of the vault staged in
    the loaded letter into the run copy of the spare's `Vault<loaded>.DAT`, so a vault experiment
    can tell which file the game's save copies. The source spare stays blank and checked; the
    manifest's `spare_seed` records the letter, rows, coins and hash, and `disks.spare.sha256` is
    the seeded copy's.
    """
    if spare_seed_rows is not None and not (vault and spare is not None):
        raise RouteError("a spare seed needs a vault title and a spare disk")
    spare_record = _check_spare(spare) if spare is not None else None
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
    substituted: dict[str, str] | None = None
    if substitute is not None:
        substitute = pathlib.Path(substitute)
        if not substitute.is_file():
            raise RouteError(f"the substitute {substitute} is missing")
        source_disk = amiga_adf.AmigaDisk.open(substitute)
        source_problems = source_disk.verify()
        if source_problems:
            raise RouteError(f"{substitute} fails ADF verification: {source_problems}")
        working = amiga_adf.AmigaDisk(bytearray(images["disk3"][1]))
        try:
            _darkness_import_slot(working, loaded, source_disk, substitute_letter)
            if vault:
                _darkness_import_vault(working, loaded, source_disk, substitute_letter)
        except (amiga_adf.AmigaDiskError, amiga_savegame.AmigaSaveError,
                amiga_savegame.PodSaveError, ValueError) as exc:
            raise RouteError(f"the substitute slot could not be imported: {exc}") from exc
        problems = working.verify()
        if problems:
            raise RouteError(f"the substituted working disk fails verification: {problems}")
        save = working
        images["disk3"] = (images["disk3"][0], working.to_bytes())
        substituted = {"path": str(substitute), "sha256": sha256(substitute),
                       "letter": substitute_letter}
    reading = DARKNESS.read_slot(save, loaded)
    if "place" not in reading:
        raise RouteError(f"slot {loaded} does not decode: {reading}")
    held = None
    if vault:
        try:
            held = _vault_reading(save, loaded)
        except (amiga_adf.AmigaDiskError, amiga_savegame.AmigaSaveError) as exc:
            raise RouteError(f"vault {loaded} on disk 3 cannot be read: {exc}") from exc
        if not held["items"]:
            raise RouteError(f"vault {loaded} on disk 3 holds no items, so a vault run "
                             "could show nothing")
    seed_bytes = None
    if spare_seed_rows is not None:
        try:
            seed_bytes = _seeded_vault_bytes(
                save.read_file(amiga_savegame.pod_vault_path(loaded)), spare_seed_rows)
        except (amiga_adf.AmigaDiskError, amiga_savegame.AmigaSaveError) as exc:
            raise RouteError(f"a spare seed of vault {loaded} cannot be made: {exc}") from exc
    scratch.ensure(run)
    disks: dict[str, dict[str, str]] = {}
    for key, (_label, data) in images.items():
        path = run / f"{key}.adf"
        path.write_bytes(data)
        disks[key] = {"path": str(path), "sha256": sha256(path)}
    if any(disks[key]["sha256"] != pinned for key, pinned in wanted.items()
           if not (key == "disk3" and substituted)):
        raise RouteError("a working copy differs from the pinned disk")
    if spare_record is not None:
        path = run / f"{SPARE}.adf"
        shutil.copyfile(spare_record["path"], path)
        if seed_bytes is not None:
            seeded = amiga_adf.AmigaDisk.open(path)
            vault_path = amiga_savegame.pod_vault_path(loaded)
            try:
                name = seeded.lookup(vault_path).name
            except amiga_adf.AmigaDiskError:
                name = vault_path.rsplit("/", 1)[1]
            else:
                seeded.remove_file(vault_path)
            seeded.write_file(vault_path.rsplit("/", 1)[0] + "/" + name,
                              seed_bytes)
            problems = seeded.verify()
            if problems:
                raise RouteError(f"the seeded spare disk fails verification: {problems}")
            seeded.save(path)
        disks[SPARE] = {"path": str(path), "sha256": sha256(path)}
        if seed_bytes is None and disks[SPARE]["sha256"] != spare_record["sha256"]:
            raise RouteError("the working spare disk differs from the input")
    manifest = {
        "title": "darkness", "disks": disks, "registered": {},
        "sources": {key: {"label": label, "sha256": wanted[key]}
                    for key, (label, _data) in images.items()},
        "loaded_letter": loaded,
        "state_a": reading["place"], "names_a": reading["names"],
    }
    if substituted:
        manifest["substitute"] = substituted
    if held:
        manifest["vault"] = held
    if spare_record is not None:
        manifest[SPARE] = spare_record
    if seed_bytes is not None:
        seeded_reading = _vault_reading(amiga_adf.AmigaDisk.open(disks[SPARE]["path"]), loaded)
        manifest["spare_seed"] = {"letter": loaded, **seeded_reading}
    after = _find_images({k: v for k, v in wanted.items() if override is None or k != "disk3"})
    if any(hashlib.sha256(after[key][1]).hexdigest() != wanted[key] for key in after):
        raise RouteError("a registered image changed during preparation")
    if spare_record is not None and sha256(pathlib.Path(spare_record["path"])) != spare_record["sha256"]:
        raise RouteError("the source spare disk changed during preparation")
    return manifest


def _walk_names(disk: amiga_adf.AmigaDisk) -> dict[str, bytes]:
    """Every file on the disk by its lower-cased path, with its bytes."""
    return {path.lower(): disk.read_file(path) for path, _entry in disk.walk()}


def _prepare_darkness_reload(run: pathlib.Path, disk3: pathlib.Path, disk3_sha256: str,
                             accept_summary: pathlib.Path) -> dict[str, Any]:
    """Prepare a reload run on a disk 3 that a successful accept run fetched.

    Raises on a file that does not hash to `disk3_sha256`, a summary that is not a successful
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
    outdoors = {letter: outdoor_square(one) for letter, one in reading.items()}
    if (reading["F"]["place"] == reading["G"]["place"]
            and outdoors["F"] == outdoors["G"]):
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
        **({"wilderness_a": outdoors["G"], "wilderness_other": outdoors["F"]}
           if outdoors["G"] or outdoors["F"] else {}),
        "slot_sha256": {letter: one["sha256"] for letter, one in reading.items()},
        "accept_summary": {"path": str(accept_summary), "sha256": sha256(accept_summary)},
    }


def _prepare_darkness_spare_reload(run: pathlib.Path, disk3: pathlib.Path, disk3_sha256: str,
                                   accept_summary: pathlib.Path,
                                   spare: pathlib.Path,
                                   disk3_seed_rows: int | None = None) -> dict[str, Any]:
    """Prepare a run that loads the one saved game on the spare disk a spare accept run fetched.

    Raises on a disk 3 that does not hash to `disk3_sha256`, a summary that is not a successful
    accept run whose fetched disk 3 and spare are these two files, a spare that does not hold
    exactly one saved game, and a saved game that does not decode. The manifest's `spare_vault`
    is that slot's vault on the spare, which the route's vault steps list.

    `disk3_seed_rows` writes the first N rows of disk 3's control-letter vault (the summary's
    `spare_vault.control_letter`) over the run copy's loaded-letter vault, which must be empty
    there; `disks.disk3.sha256` is then the seeded copy's and `disk3_seed` records the seed. The
    input disk 3 is never written.
    """
    disk3, accept_summary, spare = (pathlib.Path(p) for p in (disk3, accept_summary, spare))
    for path in (disk3, accept_summary, spare):
        if not path.is_file():
            raise RouteError(f"the file {path} is missing")
    if sha256(disk3) != disk3_sha256:
        raise RouteError(f"the disk 3 SHA-256 differs: {sha256(disk3)}")
    try:
        summary = json.loads(accept_summary.read_text())
        fetched = {key: summary["fetched"][key]["sha256"] for key in ("disk3", SPARE)}
    except (ValueError, KeyError, TypeError) as exc:
        raise RouteError(f"the accept summary {accept_summary} is unreadable or has no fetched "
                         f"spare: {exc!r}") from exc
    if summary.get("success") is not True or summary.get("accept") is not True:
        raise RouteError("the summary is not a successful accept run")
    if fetched != {"disk3": disk3_sha256, SPARE: sha256(spare)}:
        raise RouteError("the summary's fetched disk 3 or spare is another disk")
    try:
        save = amiga_adf.AmigaDisk(spare.read_bytes())
        if save.verify():
            raise RouteError(f"the spare disk {spare} fails ADF verification")
        letters = _darkness_slot_letters(save)
    except amiga_adf.AmigaDiskError as exc:
        raise RouteError(f"the spare disk {spare} has no readable SAVE drawer: {exc}") from exc
    if len(letters) != 1:
        raise RouteError(f"the spare disk holds {letters}, not one saved game")
    loaded = letters[0]
    reading = DARKNESS.read_slot(save, loaded)
    if "place" not in reading:
        raise RouteError(f"slot {loaded} on the spare does not decode: {reading}")
    try:
        held = vault_evidence(save, loaded)
    except (amiga_adf.AmigaDiskError, amiga_savegame.AmigaSaveError) as exc:
        raise RouteError(f"vault {loaded} on the spare cannot be read: {exc}") from exc
    wanted = {"disk1": DARKNESS_DISK1_SHA256, "disk2": DARKNESS_DISK2_SHA256}
    images = _find_images(wanted)
    scratch.ensure(run)
    disks: dict[str, dict[str, str]] = {}
    for key in wanted:
        path = run / f"{key}.adf"
        path.write_bytes(images[key][1])
        disks[key] = {"path": str(path), "sha256": sha256(path)}
    for key, source in (("disk3", disk3), (SPARE, spare)):
        path = run / f"{key}.adf"
        shutil.copyfile(source, path)
        disks[key] = {"path": str(path), "sha256": sha256(path)}
    if (any(disks[key]["sha256"] != pinned for key, pinned in wanted.items())
            or disks["disk3"]["sha256"] != disk3_sha256
            or disks[SPARE]["sha256"] != fetched[SPARE]):
        raise RouteError("a working copy differs from its input")
    seed = None
    if disk3_seed_rows is not None:
        seed = _seed_disk3(pathlib.Path(disks["disk3"]["path"]), loaded, disk3_seed_rows,
                           summary)
        disks["disk3"]["sha256"] = sha256(pathlib.Path(disks["disk3"]["path"]))
    return {
        "title": "darkness-reload", "disks": disks,
        "registered": {"accept_disk3": {"path": str(disk3), "sha256": disk3_sha256},
                       "accept_spare": {"path": str(spare), "sha256": fetched[SPARE]}},
        "sources": {key: {"label": images[key][0], "sha256": wanted[key]} for key in wanted},
        "loaded_letter": loaded, "state_a": reading["place"], "names_a": reading["names"],
        SPARE: {"path": str(spare), "sha256": fetched[SPARE]},
        "spare_vault": held or {"items": 0, "coins": [0, 0, 0], "sha256": None},
        "accept_summary": {"path": str(accept_summary), "sha256": sha256(accept_summary)},
        **({} if seed is None else {"disk3_seed": seed}),
    }


def _seed_disk3(path: pathlib.Path, loaded: str, rows: int,
                summary: dict[str, Any]) -> dict[str, Any]:
    """Write `rows` of the control letter's vault over `loaded`'s on the disk 3 copy at `path`.

    Returns the manifest's `disk3_seed`. Raises `RouteError` when the summary names no control
    letter, the loaded-letter vault already holds rows or coins, or `rows` is out of bounds.
    """
    try:
        control = summary["spare_vault"]["control_letter"]
        disk = amiga_adf.AmigaDisk.open(path)
        held = vault_evidence(disk, loaded)
        if held is None or held["items"] or any(held["coins"]):
            raise RouteError(f"vault {loaded} on disk 3 is not empty, so a seed would not be "
                             "the only vault there")
        data = _seeded_vault_bytes(disk.read_file(amiga_savegame.pod_vault_path(control)), rows)
        vault_path = amiga_savegame.pod_vault_path(loaded)
        name = disk.lookup(vault_path).name
        disk.remove_file(vault_path)
        disk.write_file(vault_path.rsplit("/", 1)[0] + "/" + name, data)
        problems = disk.verify()
        if problems:
            raise RouteError(f"the seeded disk 3 fails verification: {problems}")
        disk.save(path)
        return {"letter": loaded, "from_letter": control, **_vault_reading(disk, loaded)}
    except (KeyError, TypeError) as exc:
        raise RouteError(f"the accept summary has no spare_vault control letter: {exc!r}") from exc
    except (amiga_adf.AmigaDiskError, amiga_savegame.AmigaSaveError) as exc:
        raise RouteError(f"a disk 3 seed of {rows} rows cannot be made: {exc}") from exc


def spare_title_for(name: str, manifest: dict, title: AmigaTitle, command: str) -> AmigaTitle:
    """The route a manifest prepared with a spare disk runs: `title` itself when it has none.

    `darkness` and `darkness-vault` make their camp save on the spare; `darkness-reload` loads
    from it and writes nothing, so it runs as `measure` only.
    """
    if SPARE not in manifest:
        return title
    if name in ("darkness", "darkness-vault"):
        return spare_save_title(title)
    if name == "darkness-reload":
        if command != "measure":
            raise RouteError("a reload from the spare disk writes nothing and runs as measure")
        try:
            held = manifest.get("disk3_seed") or manifest["spare_vault"]
            return spare_reload_title(manifest["loaded_letter"], held["items"],
                                      any(held["coins"]))
        except (KeyError, TypeError) as exc:
            raise RouteError(f"the spare reload manifest lacks {exc!r}") from exc
    raise RouteError(f"{name} takes no spare disk")


#: The letters a published disk 3 run saves to, in the order they are taken. The game's own save
#: picker offers A to H, and `B` and `E` are left out because the route presses them as the
#: Begin Adventuring key and the exit key, which only a letter that is not a kept slot may take.
PUBLISHED_SAVE_LETTERS = ("F", "G", "H", "A", "C", "D")

_SIMPLE_KEY_STATES = (("E", "loaded_menu"), ("B", "journal"), ("E", "camp"))
_LOAD_STEP = ("B", "disk2_prompt", "key")
_CONTROL_STEP = ("F", "loaded_menu", "write")
_AFTER_STEP = ("G", "exit_game", "write")


def published_letters(loaded: str, present: list[str] | tuple[str, ...]
                      ) -> tuple[str, str, tuple[str, ...]]:
    """The control letter, the after letter and the kept letters of a disk 3 that holds `present`.

    The control and after letters are the first two of `PUBLISHED_SAVE_LETTERS` that hold no saved
    game in `present`; every other saved-game letter but the loaded one is kept. A letter's
    `Vault<L>.DAT` does not take it: every disk 3 ships all of them and the game overwrites one
    when it saves to that letter.
    """
    free = [c for c in PUBLISHED_SAVE_LETTERS if c not in present]
    if len(free) < 2:
        raise RouteError(f"disk 3 holds {sorted(present)}: fewer than two of "
                         f"{PUBLISHED_SAVE_LETTERS} are free to save to")
    return free[0], free[1], tuple(sorted(c for c in present if c != loaded))


def published_title(loaded: str, present: list[str] | tuple[str, ...]) -> AmigaTitle:
    """`DARKNESS` for a disk 3 whose loaded slot is `loaded` and which holds the letters `present`.

    The registered route loads B and saves to F and G, which a published disk 3 may hold or
    lack, so the load key, the control save and the after save are the letters this disk allows.
    """
    control, after, kept = published_letters(loaded, present)

    def swap(route: tuple) -> tuple:
        return tuple((loaded, *step[1:]) if step == _LOAD_STEP
                     else (control, *step[1:]) if step == _CONTROL_STEP
                     else (after, *step[1:]) if step == _AFTER_STEP else step
                     for step in route)

    return dataclasses.replace(
        DARKNESS, route=swap(DARKNESS.route), measure_route=swap(DARKNESS.measure_route),
        control_letter=control, after_letter=after, kept_letters=kept,
        plain_keys=tuple(e for e in _SIMPLE_KEY_STATES if e[0] in kept))


def published_reload_title(loaded: str, present: list[str] | tuple[str, ...]) -> AmigaTitle:
    """`DARKNESS_RELOAD` loading `loaded` from a disk 3 that holds `present`; every other held slot is kept."""
    kept = tuple(sorted(c for c in present if c != loaded))
    route = tuple((loaded, *step[1:]) if step == (DARKNESS_RELOAD_LOADED, "disk2_prompt", "key")
                  else step for step in _RELOAD_ROUTE)
    return dataclasses.replace(
        DARKNESS_RELOAD, route=route, measure_route=route, kept_letters=kept,
        plain_keys=tuple(e for e in _SIMPLE_KEY_STATES[:2] if e[0] in kept))
