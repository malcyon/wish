#!/usr/bin/env python3
"""Take an Amiga Curse party into Tilverton's tavern brawl, log each command bar's owner, and save.

`stage` puts a copy of a Curse save disk some earlier run fetched in place of a prepare run's
disk A and writes a manifest. `run` boots it in one muted WinUAE lane and, pressing only on
guarded screens, loads the slot, begins, walks the area's own map (`GEO.GLB` on disk B) to the
tavern at 6,10, answers PUNCH BARKEEP, and answers every command bar with QUICK, so the fight
runs itself as the DOS fight step's does. At each bar it reads whose bar it is from memory and
logs it. After the fight it checks each `--member` had a bar, now holds quickfight 1 and still
stands, then camps and saves once to the staged letter, halts, fetches the disk and reads the
slot back. `--no-save` stops after that check. Memory is only read, never written.
`read` reads a fetched disk's saved slot against a staged manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from goldbox import amiga_adf, amiga_savegame  # noqa: E402
from tools.amiga import acceptance, curseadd, route_curse  # noqa: E402
from tools.amiga.screens import PixelGuards  # noqa: E402
from tools.amiga.staging import sha256  # noqa: E402
from tools.amiga.winuaesession import RouteError, WinGuest, terminating  # noqa: E402

require = curseadd.require
write_json = curseadd.write_json
TITLE = route_curse.CURSE_KEY

#: Tilverton's tavern: area 1, square 6,10, whose bar starts the brawl (the DOS fight step's
#: `CURSE_TAVERN`), walked over the area's own map, `GEO01` in disk B's `GEO.GLB`.
TAVERN_AREA = 1
TAVERN_GEO = "GEO01"
TAVERN = (6, 10)
#: Record offsets in `/Curse`: name at 0, control 0xF7, status 0x19A, side 0x19C, quickfight
#: 0x19D (QUICK at 0x386C sets it; the turn test at 0x2C24 reads it), hit points 0x1A9.
RECORD = {"control": 0xF7, "status": 0x19A, "side": 0x19C, "quickfight": 0x19D,
          "hit_points": 0x1A9}
RECORD_SIZE = 0x1AC
#: The data-hunk global holding the record whose turn it is: the turn routine 0x2B68 stores
#: it at 0x2BB6, before 0x2C24 picks the command bar or the computer's turn.
CURRENT = 0x3CFC

#: The screens this route adds to the Curse guard map. The load error is the one a slot
#: holding a Pool import shows four times while it loads (`Invalid item (%d/%d)`, printed by
#: 0x39FCA, which waits for a key and goes on unless it is `q`).
FIGHT_GUARDS = {
    "load_error": {"box": [60, 416, 600, 430],
                   "sha256": "4a6806c8d6012a5bbd5ded17d87c260f61d5fcd05ec2e2cd025ffa4418a1fa71"},
    "tavern": {"box": [72, 404, 592, 426],
               "sha256": "729a8de7b9157b080928e2e212f775c0738ffd23b20344ddbc82aa2b75f9ae17"},
    # MOVE VIEW AIM, the start of every member's command bar.
    "combat_bar": {"box": [72, 404, 288, 426],
                   "sha256": "140a5633d4aa744c3cf0bcf3d4a1bd5870f0ca7701590fa635ddd66abdff61df"},
    "continue_battle": {"box": [72, 404, 434, 426],
                        "sha256": "9c43f3c3f0819edd3f09e9d5843cb8dfaf923834790425cd0dabfdf6ab868914"},
    "treasure": {"box": [72, 404, 384, 426],
                 "sha256": "16e9130520404b31cfbee989cc1a167a940b5a441aea7e2e048e2d569ec8edb3"},
    # Two YES NO bars, told apart by the question's first line.
    "treasure_left": {"box": [72, 404, 178, 426],
                      "sha256": "89b99bc33b8a2b0494ad7d39adcf238a8802b4fec1186f7ce8774f168ff04a73",
                      "and": [{"box": [74, 302, 690, 318],
                               "sha256": "4876bed5dd347da0b9f1d21713a1a52711ed08a02668a71f67b5ff979021223f"}]},
    "investigate": {"box": [72, 404, 178, 426],
                    "sha256": "89b99bc33b8a2b0494ad7d39adcf238a8802b4fec1186f7ce8774f168ff04a73",
                    "and": [{"box": [74, 302, 690, 318],
                             "sha256": "62e2c5b54a7168bf15231eb25872aa96f17c857a1994d07fcecf3c381750cdd2"}]},
}
KNOWN = ("intro", "front_end", "title", "load_picker", "load_error", "loaded_menu", "world",
         "continue", "tavern", "combat_bar", "continue_battle", "treasure", "treasure_left",
         "investigate", "camp", "camp_save_picker", "exit_game")
#: The only keys each screen may receive. The tavern's L(EAVE) is for a bar shown again after
#: the fight; the investigate question is answered NO, which keeps the party out of a second fight.
ALLOWED_KEYS = {
    "intro": frozenset({"ESC"}), "front_end": frozenset({"ESC"}), "title": frozenset({"L"}),
    "load_picker": frozenset("ABCDEFGHIJ"), "load_error": frozenset({"RET"}),
    "loaded_menu": frozenset({"B"}), "world": frozenset({"NP4", "NP6", "NP8", "E"}),
    "continue": frozenset({"RET"}), "tavern": frozenset({"P", "L"}),
    "combat_bar": frozenset({"Q"}), "continue_battle": frozenset({"N"}),
    "treasure": frozenset({"E"}), "treasure_left": frozenset({"N"}),
    "investigate": frozenset({"N"}), "camp": frozenset({"S"}),
    "camp_save_picker": frozenset("ABCDEFGHIJ"), "exit_game": frozenset({"N"}),
}
#: Answers to the screens that come between the first command bar and the map.
FIGHT_ANSWERS = {"combat_bar": "Q", "continue_battle": "N", "treasure": "E",
                 "treasure_left": "N", "investigate": "N", "continue": "RET"}
#: Facing steps (0 N, 1 E, 2 S, 3 W) and the key that turns the party by each.
TURN_KEYS = {1: ("NP6",), 2: ("NP6", "NP6"), 3: ("NP4",)}
STEP = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}
#: Load errors a run answers before it stops; a slot holding a Pool import shows four.
LOAD_ERRORS = 8
#: Seconds any screen may stay unchanged mid-fight before the run stops: the QUICK turns
#: redraw the field all the time, and a still screen is a key the game ignores or a question
#: nobody answers.
FIGHT_STALL = 90.0
#: Seconds the whole fight may take; a fight of QUICK turns takes about ten minutes.
FIGHT_LIMIT = 1500.0
#: Seconds after a key before the next grab, so a screen the key replaces is not read again.
AFTER_KEY = 3.0
#: Seconds the tavern bar may stay on screen after PUNCH before the run stops.
TAVERN_LINGER = 15.0
#: Seconds the map must hold before the fight is taken as over.
MAP_SETTLE = 6.0
#: Seconds the run waits for a step or a turn to show in the party's live square.
MOVE_LIMIT = 20.0
READ_LIMIT = 60.0
POST_WRITE_WAIT = 20.0
SLOT = curseadd.SLOT


class Screens(curseadd.Screens):
    known = KNOWN
    allowed = ALLOWED_KEYS


def guard_rules() -> dict:
    """The Curse guard map with this route's screens added."""
    rules = curseadd.guard_rules()
    require(not set(FIGHT_GUARDS) & set(rules), "a fight guard name is already a Curse guard")
    return {**rules, **FIGHT_GUARDS}


def _slot(disk: amiga_adf.AmigaDisk, letter: str):
    return amiga_savegame.read_slot(disk, letter, TITLE)


def member_fields(raw: bytes) -> dict[str, int]:
    return {field: raw[at] for field, at in RECORD.items()}


def _name(raw: bytes) -> str:
    return raw[:0x10].split(b"\0", 1)[0].replace(b"\xff", b" ").decode("latin-1")


def _digest(shot: pathlib.Path) -> str | None:
    """The crop's bytes as a digest, None for a grab that left no crop."""
    try:
        return hashlib.sha256(pathlib.Path(shot).read_bytes()).hexdigest()
    except OSError:
        return None


def plan(geo, start: tuple[int, int], target: tuple[int, int]) -> list[int]:
    """The facings of the shortest walk over `geo` (`cursethac0.plan`, the DOS step's planner)."""
    from tools.curse_of_the_azure_bonds import cursethac0  # noqa: PLC0415

    return cursethac0.plan(geo, start, target)


def tavern_map(diskb: pathlib.Path):
    """`TAVERN_GEO` out of disk B's `GEO.GLB`."""
    from automap import amiga  # noqa: PLC0415

    maps = amiga.load_maps(diskb)
    require(TAVERN_GEO in maps, f"{diskb} holds no {TAVERN_GEO}")
    return maps[TAVERN_GEO]


def stage(manifest_path: pathlib.Path, source_disk: pathlib.Path, out: pathlib.Path, *,
          load: str, save: str) -> pathlib.Path:
    """Copy a Curse save disk in as a prepare run's disk A and write `out/prepare.json`."""
    require(not out.exists(), f"{out} already exists")
    require(bool(SLOT.fullmatch(load)) and bool(SLOT.fullmatch(save)) and load != save,
            "the load and save letters must be two letters A-J")
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get("title") == "curse", "the manifest is not a Curse prepare")
    for key, entry in (("diskb", manifest["disks"]["diskb"]), *manifest["registered"].items()):
        require(sha256(pathlib.Path(entry["path"])) == entry["sha256"], f"the {key} disk hash differs")
    source_hash = sha256(source_disk)
    disk = amiga_adf.AmigaDisk.open(source_disk)
    problems = disk.verify()
    require(not problems, f"{source_disk} fails ADF verification: {problems}")
    letters = curseadd.slot_letters(disk)
    require(load in letters, f"slot {load} is not on {source_disk}: {letters}")
    require(save not in letters, f"slot {save} is already on {source_disk}")
    saved = _slot(disk, load)
    state = amiga_savegame.state_from_savegame(saved)
    place = {"area": state.area, "x": state.x, "y": state.y, "facing": state.facing}
    require(state.area == TAVERN_AREA, f"slot {load} is in area {state.area}; the route "
                                       f"knows only Tilverton, area {TAVERN_AREA}")
    route = plan(tavern_map(pathlib.Path(manifest["disks"]["diskb"]["path"])),
                 (state.x, state.y), TAVERN)
    require(bool(route), f"no way from {state.x},{state.y} to the tavern")
    out.mkdir(parents=True)
    disks = {}
    for key, source in (("save", source_disk),
                        ("diskb", pathlib.Path(manifest["disks"]["diskb"]["path"]))):
        local = out / f"{key}.adf"
        shutil.copyfile(source, local)
        disks[key] = {"path": str(local), "sha256": sha256(local)}
    require(disks["save"]["sha256"] == source_hash, "the copy differs from the source disk")
    staged = {**manifest, "disks": disks,
              "prepared_from": {"path": str(manifest_path.resolve()),
                                "save_sha256": manifest["disks"]["save"]["sha256"]},
              "fight": {"source": {"path": str(source_disk.resolve()), "sha256": source_hash},
                        "load": load, "save": save, "place": place, "route": route,
                        "names": [m.name for m in saved.characters],
                        "members": {m.name: member_fields(m.raw) for m in saved.characters}}}
    path = out / "prepare.json"
    write_json(path, staged)
    return path


class Memory:
    """Reads of the running game through WinUAE's pipe: never a write."""

    def __init__(self, holder: str):
        self.holder = holder
        self._target: Any = None

    def target(self) -> Any:
        if self._target is None:
            from automap import amiga  # noqa: PLC0415

            target = amiga.AmigaTarget(amiga.WinuaePipe(holder=self.holder),
                                       amiga.MACHINES[TITLE])
            target.locate()
            self._target = target
        return self._target

    def fix(self) -> tuple[int, int, int] | None:
        fix = self.target().fix()
        return None if fix is None else (fix.x, fix.y, fix.facing)

    def owner(self) -> dict | None:
        target = self.target()
        address = int.from_bytes(target.read(target.data_base + CURRENT, 4), "big")
        if not address:
            return None
        raw = bytes(target.read(address, RECORD_SIZE))
        return {"address": address, "name": _name(raw), **member_fields(raw)}

    def party(self) -> list[dict]:
        from automap import amigaparty  # noqa: PLC0415

        members = amigaparty.read_party(self.target())
        require(members is not None, "the party list does not read")
        return [{"name": m.name, **member_fields(m.raw)} for m in members]


def walk(screens: Screens, memory: Memory, start: dict, route: list[int]) -> list[dict]:
    """Turn and step along `route`, each key on the map and each move read back from memory."""
    steps = []
    x, y, facing = start["x"], start["y"], start["facing"]
    seen = memory.fix()
    require(seen == (x, y, facing), f"the party stands at {seen}, not the loaded {x},{y},{facing}")

    def on_map() -> None:
        while screens.wait(("world", "continue"), 60) == "continue":
            screens.press("RET", "continue")
            screens.sleep(AFTER_KEY)

    def until(want: tuple[int, int, int]) -> tuple[int, int, int] | None:
        end = screens.clock() + MOVE_LIMIT
        got = None
        while screens.clock() < end:
            got = memory.fix()
            if got == want:
                break
            screens.sleep(1.0)
        return got

    def move(key: str, want: tuple[int, int, int]) -> None:
        """Press `key` on the map; a box that took the key is answered and the key sent once more."""
        for attempt in (1, 2):
            on_map()
            screens.press(key, "world")
            got = until(want)
            if got == want:
                return
            if attempt == 1 and "continue" in screens.look("move")[0]:
                continue
            break
        raise RouteError(f"{key} left the party at {got}, not {want}")

    for heading in route:
        for key in TURN_KEYS.get((heading - facing) % 4, ()):
            facing = (facing + (1 if key == "NP6" else -1)) % 4
            move(key, (x, y, facing))
        dx, dy = STEP[heading]
        x, y = x + dx, y + dy
        move("NP8", (x, y, facing))
        steps.append({"x": x, "y": y, "facing": facing})
        screens.sleep(AFTER_KEY)
    return steps


def fight(screens: Screens, memory: Memory, members: list[str]) -> dict:
    """Answer every screen from the first bar to the map; log each bar with its owner."""
    bars: list[dict] = []
    answered: list[dict] = []
    started = still_since = screens.clock()
    settle_from = None
    last: object = object()
    while True:
        require(screens.clock() - started < FIGHT_LIMIT,
                f"the fight was still going after {FIGHT_LIMIT:.0f}s")
        seen, shot = screens.look("fight")
        state = next((s for s in KNOWN if s in seen), None)
        digest = _digest(shot)
        # A grab with no crop counts as one more of the same, so a stuck one stops the run too.
        if digest != last:
            last, still_since = digest, screens.clock()
        if state == "world" and bars:
            settle_from = settle_from if settle_from is not None else screens.clock()
            if screens.clock() - settle_from >= MAP_SETTLE:
                break
            screens.sleep(2.0)
            continue
        settle_from = None
        if state == "world" and not bars and screens.clock() - started < TAVERN_LINGER:
            # The map still showing while the brawl starts after PUNCH.
            screens.sleep(1.5)
            continue
        named = "a screen no guard knows" if state is None else f"the {state} screen"
        require(screens.clock() - still_since < FIGHT_STALL,
                f"{named} stayed {FIGHT_STALL:.0f}s unchanged mid-fight; shot {shot}")
        if state is None:
            screens.sleep(1.5)
            continue
        if state == "combat_bar":
            owner = curseadd.bounded(lambda _h: memory.owner(), memory.holder,
                                     screens.left(READ_LIMIT))
            again, _ = screens.look("bar-again")
            require("combat_bar" in again, f"the command bar went before its owner was read; {shot}")
            require(owner is not None, f"a command bar with no record in turn; {shot}")
            bars.append({"owner": owner["name"], "address": owner["address"],
                         "control": owner["control"], "status": owner["status"],
                         "quickfight": owner["quickfight"], "hit_points": owner["hit_points"],
                         "shot": str(shot), "number": len(bars) + 1})
            screens.events.append({"bar": bars[-1]})
        elif state == "tavern" and bars:
            screens.press("L", "tavern")
            answered.append({"screen": state, "key": "L", "shot": str(shot)})
            screens.sleep(AFTER_KEY)
            continue
        elif state == "tavern":
            # The bar PUNCH went out on, still drawn while the brawl starts.
            require(screens.clock() - started < TAVERN_LINGER,
                    f"the tavern bar stayed {TAVERN_LINGER:.0f}s after PUNCH; shot {shot}")
            screens.sleep(1.5)
            continue
        elif state not in FIGHT_ANSWERS:
            raise RouteError(f"{state} showed mid-fight; shot {shot}")
        key = FIGHT_ANSWERS[state]
        screens.press(key, state)
        answered.append({"screen": state, "key": key, "shot": str(shot)})
        screens.sleep(AFTER_KEY)
    owners = {bar["owner"] for bar in bars}
    missing = [name for name in members if name not in owners]
    require(not missing, f"{missing} had no command bar; bars went to {sorted(owners)}")
    return {"bars": bars, "answered": answered}


def check_members(party: list[dict], manifest: dict, members: list[str]) -> dict:
    """Each named member is in the party with quickfight 1, still standing as loaded."""
    loaded = manifest["fight"]["members"]
    found = {}
    for name in members:
        rows = [m for m in party if m["name"] == name]
        require(len(rows) == 1, f"{name} is in the party {len(rows)} times after the fight")
        row = rows[0]
        require(row["quickfight"] == 1, f"{name} holds quickfight {row['quickfight']} after QUICK")
        require(row["control"] == loaded[name]["control"] and row["status"] == loaded[name]["status"]
                and row["hit_points"] > 0,
                f"{name} fell or changed in the fight: {row}, loaded as {loaded[name]}")
        found[name] = row
    return found


def drive(screens: Screens, manifest: dict, members: list[str], memory: Memory, *,
          save: bool) -> dict:
    fight_ = manifest["fight"]
    found: dict[str, Any] = {}
    screens.to_party_menu(300)
    screens.press("L", "title")
    screens.wait(("load_picker",), 60, past=("title",))
    screens.press(fight_["load"], "load_picker")
    errors = 0
    while screens.wait(("loaded_menu", "load_error"), 120, past=("load_picker",)) == "load_error":
        require(errors < LOAD_ERRORS, f"{LOAD_ERRORS} load errors and still no party menu")
        screens.press("RET", "load_error")
        errors += 1
        screens.sleep(AFTER_KEY + 1)
    found["load_errors"] = errors
    found["loaded"] = curseadd.bounded(lambda _h: memory.party(), memory.holder,
                                       screens.left(READ_LIMIT))
    names = [m["name"] for m in found["loaded"]]
    require(names == fight_["names"], f"the loaded party is {names}, not {fight_['names']}")
    screens.press("B", "loaded_menu")
    screens.wait(("world",), 90, past=("loaded_menu",))
    screens.sleep(AFTER_KEY)
    found["walk"] = walk(screens, memory, fight_["place"], fight_["route"])
    screens.wait(("tavern",), 60, past=("world", "continue"))
    screens.press("P", "tavern")
    screens.sleep(AFTER_KEY)
    found.update(fight(screens, memory, members))
    found["after"] = curseadd.bounded(lambda _h: memory.party(), memory.holder,
                                      screens.left(READ_LIMIT))
    found["members"] = check_members(found["after"], manifest, members)
    if not save:
        return found
    screens.wait(("world",), 30, past=())
    screens.press("E", "world")
    screens.wait(("camp",), 60, past=("world",))
    screens.press("S", "camp")
    screens.wait(("camp_save_picker",), 60, past=("camp",))
    screens.press(fight_["save"], "camp_save_picker")
    screens.wait(("exit_game",), 120, past=("camp_save_picker",))
    screens.sleep(POST_WRITE_WAIT)
    screens.press("N", "exit_game")
    screens.wait(("camp",), 60, past=("exit_game",))
    return found


def read_back(disk_path: pathlib.Path, manifest: dict) -> dict:
    """The saved slot's members, and whether the loaded slot's file is still as staged."""
    fight_ = manifest["fight"]
    disk = amiga_adf.AmigaDisk.open(disk_path)
    staged = amiga_adf.AmigaDisk.open(manifest["disks"]["save"]["path"])
    loaded_file = f"/SAVE/savgam{fight_['load']}.dat"
    return {"letter": fight_["save"], "verify": disk.verify(),
            "loaded_slot_unchanged": disk.read_file(loaded_file) == staged.read_file(loaded_file),
            "members": [{"name": m.name, **member_fields(m.raw)}
                        for m in _slot(disk, fight_["save"]).characters]}


def verdict(found: dict, manifest: dict, members: list[str]) -> list[str]:
    """Problems with a read-back: empty when each named member was saved QUICK, as loaded."""
    problems = []
    if found["verify"]:
        problems.append(f"the fetched disk fails verification: {found['verify']}")
    if not found["loaded_slot_unchanged"]:
        problems.append(f"slot {manifest['fight']['load']} changed on the disk")
    names = [m["name"] for m in found["members"]]
    if names != manifest["fight"]["names"]:
        problems.append(f"the saved party is {names}, not {manifest['fight']['names']}")
    for name in members:
        rows = [m for m in found["members"] if m["name"] == name]
        if len(rows) != 1:
            problems.append(f"{name} is in the saved party {len(rows)} times")
            continue
        loaded = manifest["fight"]["members"][name]
        row = rows[0]
        if row["quickfight"] != 1:
            problems.append(f"{name} was saved with quickfight {row['quickfight']}")
        if row["control"] != loaded["control"] or row["status"] != loaded["status"]:
            problems.append(f"{name} was saved as {row}, loaded as {loaded}")
        if row["hit_points"] == 0:
            problems.append(f"{name} was saved at 0 hit points")
    return problems


def run(args: argparse.Namespace, *, guest: Any = None, guards: Any = None,
        boot: Callable = acceptance.boot_lane, halt: Callable = acceptance.halt_lane,
        memory: Any = None, clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep) -> dict:
    """Boot a staged manifest, drive the tavern route, save once unless told not to, read back."""
    require(0 <= args.wait_lane <= 1800, "lane wait exceeds 1800 seconds")
    require(0 < args.budget <= 3600, "budget must be at most 3600 seconds")
    require(not args.out.exists(), f"{args.out} already exists")
    manifest = json.loads(args.manifest.read_text())
    require("fight" in manifest and manifest.get("title") == "curse",
            "the manifest is not a cursefight.py stage")
    fight_ = manifest["fight"]
    require(bool(args.member), "name at least one --member")
    absent = [name for name in args.member if name not in fight_["names"]]
    require(not absent, f"{absent} are not in slot {fight_['load']}: {fight_['names']}")
    for key, entry in (*manifest["disks"].items(), *manifest["registered"].items()):
        require(sha256(pathlib.Path(entry["path"])) == entry["sha256"], f"the {key} disk hash differs")
    staged = amiga_adf.AmigaDisk.open(manifest["disks"]["save"]["path"])
    require(fight_["save"] not in curseadd.slot_letters(staged),
            f"slot {fight_['save']} is already on the staged disk")
    args.out.mkdir(parents=True)
    receipt: dict[str, Any] = {"started_utc": datetime.now(timezone.utc).isoformat(),
                               "manifest": str(args.manifest.resolve()), "holder": args.holder,
                               "members": list(args.member), "save": not args.no_save,
                               "out": str(args.out.resolve()), "success": False, "cleanup": []}
    guest = guest if guest is not None else WinGuest()
    memory = memory if memory is not None else Memory(args.holder)
    command = [str(pathlib.Path(__file__)), "run", "--manifest", str(args.manifest),
               "--holder", args.holder, "--out", str(args.out),
               *(f"--member={name}" for name in args.member),
               *(["--no-save"] if args.no_save else [])]
    booted = False
    screens = None
    try:
        guard_file = args.out / "guards.json"
        write_json(guard_file, guard_rules())
        guards = guards if guards is not None else PixelGuards(guard_file)
        proof = curseadd.mute(guest, args.out, timeout=60)
        receipt["boot"] = boot(args.manifest, manifest, route_curse.CURSE, guest=guest,
                               holder=args.holder, audio_proof=proof, wait_lane=args.wait_lane,
                               timeout=300, command=command)
        booted = True
        screens = Screens(guest, args.holder, args.out / "screens", guards, clock() + args.budget,
                          clock=clock, sleep=sleep)
        receipt.update(drive(screens, manifest, list(args.member), memory,
                             save=not args.no_save))
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if screens is not None:
            receipt["screens"] = screens.events
        if booted:
            try:
                receipt["halt"] = halt(guest, args.holder, manifest_path=args.manifest,
                                       command=command)
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append({"halt_error": str(exc)})
        try:
            original = json.loads(args.manifest.read_text())
            for key, entry in (*original["disks"].items(), *original["registered"].items()):
                require(sha256(pathlib.Path(entry["path"])) == entry["sha256"], f"{key} changed")
            source = original["fight"]["source"]
            require(sha256(pathlib.Path(source["path"])) == source["sha256"],
                    "the source disk changed")
            receipt["source_hashes"] = "unchanged"
        except Exception as exc:  # noqa: BLE001
            receipt["cleanup"].append({"hash_error": str(exc)})
        fetched = (receipt.get("halt") or {}).get("fetched", {}).get("save")
        if "error" in receipt:
            pass
        elif args.no_save:
            receipt["problems"] = []
        elif fetched:
            try:
                found = read_back(pathlib.Path(fetched["path"]), manifest)
                receipt["read_back"] = found
                receipt["problems"] = verdict(found, manifest, list(args.member))
            except Exception as exc:  # noqa: BLE001
                receipt["problems"] = [f"read-back: {type(exc).__name__}: {exc}"]
        else:
            receipt["problems"] = ["no fetched save disk"]
        errors = [item for item in receipt["cleanup"] if any(k.endswith("error") for k in item)]
        receipt["success"] = ("error" not in receipt and not errors and "halt" in receipt
                              and receipt.get("problems") == [])
        write_json(args.out / "receipt.json", receipt)
    if not receipt["success"]:
        raise RouteError(receipt.get("error") or f"problems: {receipt.get('problems')}; "
                         f"cleanup: {receipt['cleanup']}")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("stage", help="copy a fetched Curse save disk in as a prepare run's disk A")
    s.add_argument("--manifest", type=pathlib.Path, required=True,
                   help="an `acceptance.py prepare --title curse` prepare.json")
    s.add_argument("--source-disk", type=pathlib.Path, required=True,
                   help="a Curse disk A whose SAVE drawer holds the slot to load")
    s.add_argument("--load", required=True, help="the slot the run loads")
    s.add_argument("--save", required=True, help="the free slot the run saves to")
    s.add_argument("--out", type=pathlib.Path, required=True)
    g = sub.add_parser("run", help="boot a staged manifest in one muted WinUAE lane, take the "
                                   "tavern fight, save once, halt, fetch and read back")
    g.add_argument("--manifest", type=pathlib.Path, required=True, help="the stage's prepare.json")
    g.add_argument("--holder", required=True)
    g.add_argument("--out", type=pathlib.Path, required=True, help="a fresh folder for the run")
    g.add_argument("--member", action="append", default=[],
                   help="a member who must get a command bar, hold quickfight 1 after the fight "
                        "and still stand; repeat for several")
    g.add_argument("--no-save", action="store_true",
                   help="stop after the fight's checks, saving nothing")
    g.add_argument("--budget", type=float, default=2700)
    g.add_argument("--wait-lane", type=float, default=0, metavar="SECONDS")
    r = sub.add_parser("read", help="read a fetched Curse disk's saved slot against a manifest")
    r.add_argument("--manifest", type=pathlib.Path, required=True)
    r.add_argument("--disk", type=pathlib.Path, required=True)
    r.add_argument("--member", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        with terminating():
            if args.command == "stage":
                print(stage(args.manifest, args.source_disk, args.out, load=args.load,
                            save=args.save))
                return 0
            if args.command == "run":
                print(json.dumps(run(args), indent=1, sort_keys=True))
                return 0
            require(bool(args.member), "name at least one --member")
            manifest = json.loads(args.manifest.read_text())
            found = read_back(args.disk, manifest)
            problems = verdict(found, manifest, args.member)
            print(json.dumps({"found": found, "problems": problems}, indent=1, sort_keys=True))
            return 0 if not problems else 1
    except (RouteError, OSError, ValueError, KeyError, amiga_adf.AmigaDiskError) as exc:
        print(f"cursefight: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
