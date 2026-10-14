#!/usr/bin/env python3
"""Take an Amiga Silver Blades party into New Verdigris' wandering fight, log each command bar's owner, and save.

`stage` copies a Silver Blades disk one whose slot stands on a street square of New Verdigris
(area 16), writes 1 to the slot's wandering-fight gate `$4C2D` in place (the area's script,
`ECL10` on the C64 and block 16 of disk B's `ECL.GLB`, rolls a fight on a street step only
then), plans a walk over the area's map (`GEO10` in disk B's `GEO.GLB`) to two street squares
side by side, and writes a manifest. `run` boots it in one muted WinUAE lane and, pressing only
on guarded screens, loads the slot, begins, has the journal answerer answer the journal
question, and steps between the two squares until a step brings up a screen that is not the
map. From there it answers every command bar with QUICK, as `cursefight.py` does, logging whose
bar it is from memory. A won fight is checked and saved once; a fight the party loses is
recorded and nothing is saved. `--capture` stops at the fight's first command bar instead and
presses nothing on it, keeping the frame for a guard to be cut from. Memory is only read,
never written.
`read` reads a fetched disk's saved slot against a staged manifest.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from goldbox import amiga_adf, amiga_savegame, world_state  # noqa: E402
from tools.amiga import (  # noqa: E402
    acceptance,
    curseadd,
    cursefight,
    route_silver_blades,
)
from tools.amiga.screens import PixelGuards  # noqa: E402
from tools.amiga.staging import replace_file_in_place, sha256  # noqa: E402
from tools.amiga.winuaesession import RouteError, WinGuest, terminating  # noqa: E402

require = curseadd.require
write_json = curseadd.write_json
TITLE = route_silver_blades.TITLE
CONTAINER = amiga_savegame.SILVER_BLADES
GUARDS = pathlib.Path(__file__).with_name("guards_silver_blades.json")

#: New Verdigris, whose script rolls the wandering fight, and its map in disk B's `GEO.GLB`.
AREA = 16
GEO = "GEO10"
#: The gate the script's street-step roll reads: at 1 a roll that comes up starts a fight,
#: otherwise the townsmen only cheer. `amiga_savegame.word` takes Pool's numbering, $200 lower.
GATE = 0x4C2D
GATE_ON = 1
#: Words the stage records beside the gate: the arrival entry rewrites the gate when `$4CD9`
#: is not 0 unless the party came from area 16 (`$4BF2`), and `$4C05` counts street steps.
NOTED = (0x4CD9, 0x4BF2, 0x4C05)
#: A street square's map attribute: no script and bit 7 clear, the squares the roll runs on.
STREET = 0x00
#: Record offsets in `/Secret`: name at 0, control 0x9A, status 0x143, side 0x145, quickfight
#: 0x146 (QUICK at 0x4A2E sets it; the turn routine reads it at 0x3DB2), hit points 0x152.
RECORD = {"control": 0x9A, "status": 0x143, "side": 0x145, "quickfight": 0x146,
          "hit_points": 0x152}
RECORD_SIZE = 0x154
#: The data-hunk global holding the record whose turn it is: the turn routine 0x3CC6 stores
#: it at 0x3D26, before 0x3DB2 picks the command bar or the computer's turn.
CURRENT = 0x516C

#: Fight screens no capture has shown yet; each takes its guard from the Silver Blades guard
#: map once `guardmaps.py add --title ssb` cuts it from a capture. A run that meets one stops
#: there, unchanged, and keeps the frame.
UNCAPTURED = {
    "continue_battle": "CONTINUE BATTLE: with YES NO",
}
#: The treasure bar cut short of its last button, which reads EXIT or DETECT EXIT by party
#: (`View Take Pool Share%s` in `/Secret`); cut from `640/ssb2/accept2/shots/11-world.png`,
#: the opening scene's own `COMBAT` statement's treasure, as are both kept crops of the bar.
TREASURE_SHORT = {"box": [72, 404, 400, 426],
                  "sha256": "6f5859dffc35646e493759a887da3132f4347cd4fc454160a4af4733e153fcbd"}
KNOWN = ("credits", "title", "party_menu", "load_picker", "load_anyway", "scrolls_dropped",
         "loaded_menu", "journal", "world", "continue", "combat_bar", "continue_battle",
         "treasure_bar", "treasure", "party_destroyed", "camp", "camp_save_picker", "exit_game")
#: The only keys each screen may receive. The journal is answered by the answerer, which types
#: through its own channel, so it takes none here. Of a lost fight's screens only the destroyed
#: message takes a key, RETURN at its PRESS ANY KEY prompt; the menus take none.
ALLOWED_KEYS = {
    "credits": frozenset({"ESC"}), "title": frozenset({"P"}), "party_menu": frozenset({"L"}),
    "load_picker": frozenset("ABCDEFGHIJ"), "loaded_menu": frozenset({"B"}),
    "world": frozenset({"NP4", "NP6", "NP8", "E"}), "continue": frozenset({"RET"}),
    "combat_bar": frozenset({"Q"}), "continue_battle": frozenset({"N"}),
    "treasure_bar": frozenset({"E"}), "treasure": frozenset({"N"}), "camp": frozenset({"S"}),
    "camp_save_picker": frozenset("ABCDEFGHIJ"), "exit_game": frozenset({"N"}),
    "party_destroyed": frozenset({"RET"}),
}
#: Answers to the screens that come between the encounter and the map after a won fight.
FIGHT_ANSWERS = {"combat_bar": "Q", "continue_battle": "N", "treasure_bar": "E",
                 "treasure": "N", "continue": "RET", "party_destroyed": "RET"}
#: Screens that mean the party was destroyed: the message, whose PRESS ANY KEY prompt gets
#: RETURN, or a menu the game returns to, which gets no key. Either ends the step there, and
#: the step assumes nothing about the screen that follows.
DEFEAT = ("party_destroyed", "loaded_menu", "party_menu", "title")
TURN_KEYS = cursefight.TURN_KEYS
STEP = cursefight.STEP
#: ESC presses that may be spent leaving the credits for the title.
BOOT_ESCAPES = 4
#: Steps the walk takes looking for the fight before the run stops.
WANDER_STEPS = 60
#: Seconds the map must hold after a step before the next key: a fight's monsters load with
#: the map bar still drawn, and a key sent then would land in the fight.
STEP_SETTLE = 12.0
#: Seconds the map may show after the fight began with no command bar yet.
NO_BAR_LIMIT = 60.0
FIGHT_STALL = cursefight.FIGHT_STALL
FIGHT_LIMIT = cursefight.FIGHT_LIMIT
AFTER_KEY = cursefight.AFTER_KEY
MAP_SETTLE = cursefight.MAP_SETTLE
MOVE_LIMIT = cursefight.MOVE_LIMIT
READ_LIMIT = cursefight.READ_LIMIT
POST_WRITE_WAIT = cursefight.POST_WRITE_WAIT
#: Seconds `--capture` waits after the fight began for a member's command bar.
CAPTURE_LIMIT = 600.0
#: Seconds a screen must stay unchanged, with a member's record in turn, to be taken as his bar.
CAPTURE_STILL = 10.0
#: Calls of the journal answerer that may find no challenge before the run stops.
JOURNAL_TRIES = 4
SLOT = curseadd.SLOT


class Screens(curseadd.Screens):
    known = KNOWN
    allowed = ALLOWED_KEYS

    def to_title(self, limit: float) -> None:
        """Wait out the boot for the PLAY DEMO QUIT title, leaving the credits with ESC."""
        end = self.clock() + self.left(limit)
        escapes = 0
        while True:
            require(self.clock() < end, f"the title did not show within {limit:.0f}s")
            seen, shot = self.look("boot")
            if "title" in seen:
                self.events.append({"screen": "title", "shot": str(shot)})
                return
            if "credits" in seen:
                require(escapes < BOOT_ESCAPES, f"{BOOT_ESCAPES} ESCs did not reach the title")
                self.press("ESC", "credits")
                escapes += 1
            stray = [s for s in seen if s != "credits"]
            require(not stray, f"the boot showed {stray} before the title; shot {shot}")
            self.sleep(3.0)


def guard_rules() -> dict:
    """The Silver Blades guard map, with the treasure bar's short rule as an alternative."""
    rules = curseadd.load_guard_map(GUARDS)
    treasure = rules["treasure_bar"]
    rules["treasure_bar"] = [*(treasure if isinstance(treasure, list) else [treasure]),
                             TREASURE_SHORT]
    return rules


def missing(rules: dict) -> list[str]:
    """The `UNCAPTURED` screens the guard map still has no rule for."""
    return [state for state in UNCAPTURED if state not in rules]


def member_fields(raw: bytes) -> dict[str, int]:
    return {field: raw[at] for field, at in RECORD.items()}


def name_key(name: str) -> str:
    return name.strip().upper()


def _slot(disk: amiga_adf.AmigaDisk, letter: str):
    return amiga_savegame.read_slot(disk, letter, TITLE)


def word(data: bytes, address: int) -> int:
    """A Silver Blades variable (its own `$4Bxx` numbering) from a saved game's bytes."""
    return amiga_savegame.word(data, address - 0x200, CONTAINER)


def with_word(data: bytes, address: int, value: int) -> bytes:
    """The saved game's bytes with one Silver Blades variable replaced."""
    at = CONTAINER.vm_offset(address - 0x200)
    return data[:at] + value.to_bytes(2, "big") + data[at + 2:]


def boot_title(issue: str):
    """The two-drive Silver Blades title `acceptance.boot_lane` boots; only its drives, options
    and the letters it keeps for its own saves (C and F) are used here, not its route."""
    return route_silver_blades.substitute_title(issue=issue, items_screen=True,
                                                opening_scene=False)


def area_map(diskb: pathlib.Path):
    """`GEO` out of disk B's `GEO.GLB`."""
    from automap import amiga  # noqa: PLC0415

    maps = amiga.load_maps(diskb)
    require(GEO in maps, f"{diskb} holds no {GEO}")
    return maps[GEO]


def street(geo, x: int, y: int) -> bool:
    return 0 <= x < 16 and 0 <= y < 16 and geo.attributes(x, y) == STREET


def wander_plan(geo, start: tuple[int, int]) -> dict:
    """The facings to the nearest street square with a street square open beside it, and the
    facing from it to that neighbour; every square walked onto is a street square, so no
    square's script runs on the way."""
    def pair(x: int, y: int) -> int | None:
        for facing, (dx, dy) in STEP.items():
            if (street(geo, x + dx, y + dy) and geo.is_passable(x, y, facing)
                    and geo.is_passable(x + dx, y + dy, (facing + 2) % 4)):
                return facing
        return None

    previous: dict[tuple[int, int], Any] = {start: None}
    queue = collections.deque([start])
    while queue:
        here = queue.popleft()
        if street(geo, *here) and pair(*here) is not None:
            route, at = [], here
            while previous[at]:
                at, facing = previous[at]
                route.append(facing)
            return {"route": list(reversed(route)), "square": list(here),
                    "facing": pair(*here)}
        for facing, (dx, dy) in STEP.items():
            nxt = (here[0] + dx, here[1] + dy)
            if nxt in previous or not street(geo, *nxt) or not geo.is_passable(*here, facing):
                continue
            previous[nxt] = (here, facing)
            queue.append(nxt)
    raise RouteError(f"no street square with an open street neighbour is reachable from {start}")


def stage(source_disk: pathlib.Path, out: pathlib.Path, *, load: str, save: str,
          diskb: pathlib.Path | None = None, issue: str = "391") -> pathlib.Path:
    """Copy a Silver Blades disk one in as DF0 with its slot's gate set, and write `out/prepare.json`."""
    require(not out.exists(), f"{out} already exists")
    require(bool(SLOT.fullmatch(load)) and bool(SLOT.fullmatch(save)) and load != save,
            "the load and save letters must be two letters A-J")
    title = boot_title(issue)
    require(load not in (title.control_letter, title.after_letter),
            f"slot {load} is a letter the boot keeps for its own saves")
    diskb = route_silver_blades.find_disk_b() if diskb is None else diskb
    require(sha256(diskb) == route_silver_blades.DISK_B_SHA256, f"{diskb} is not the registered disk B")
    source_hash = sha256(source_disk)
    disk = amiga_adf.AmigaDisk.open(source_disk)
    problems = disk.verify()
    require(not problems, f"{source_disk} fails ADF verification: {problems}")
    letters = amiga_savegame.slots_present(disk, TITLE)
    require(load in letters, f"slot {load} is not on {source_disk}: {letters}")
    require(save not in letters, f"slot {save} is already on {source_disk}")
    saved = _slot(disk, load)
    state = amiga_savegame.state_from_savegame(saved)
    require(not world_state.has_not_set_out(state),
            f"the party in slot {load} has not set out; the game starts it in the opening scene")
    require(state.area == AREA, f"slot {load} is in area {state.area}; the fight is New "
                                f"Verdigris', area {AREA}")
    place = {"area": state.area, "x": state.x, "y": state.y, "facing": state.facing}
    plan = wander_plan(area_map(diskb), (state.x, state.y))
    path = f"/SAVE/savgam{load}.sav"
    before = disk.read_file(path)
    staged = with_word(before, GATE, GATE_ON)
    out.mkdir(parents=True)
    df0 = out / "df0.adf"
    shutil.copyfile(source_disk, df0)
    require(sha256(df0) == source_hash, "the copy differs from the source disk")
    copy = amiga_adf.AmigaDisk.open(df0)
    replace_file_in_place(copy, path, staged)
    copy.save(df0)
    check = amiga_adf.AmigaDisk.open(df0)
    require(not check.verify() and check.read_file(path) == staged,
            "the staged slot does not read back")
    require(word(check.read_file(path), GATE) == GATE_ON, "the staged gate does not read back")
    df1 = out / "df1.adf"
    shutil.copyfile(diskb, df1)
    names = [m.name for m in saved.characters]
    manifest = {
        "title": "ssb", "issue": issue,
        "disks": {"df0": {"path": str(df0), "sha256": sha256(df0)},
                  "df1": {"path": str(df1), "sha256": sha256(df1)}},
        "registered": {}, "loaded_letter": load, "state_a": place, "names_a": names,
        "fight": {"source": {"path": str(source_disk.resolve()), "sha256": source_hash},
                  "load": load, "save": save, "place": place, **plan,
                  "staged": {f"{GATE:04X}": {"before": word(before, GATE), "after": GATE_ON}},
                  "noted": {f"{a:04X}": word(before, a) for a in NOTED},
                  "names": names,
                  "members": {m.name: member_fields(m.raw) for m in saved.characters}}}
    manifest_path = out / "prepare.json"
    write_json(manifest_path, manifest)
    return manifest_path


class Memory(cursefight.Memory):
    """Reads of the running game through WinUAE's pipe: never a write."""

    title = TITLE
    current = CURRENT
    record = RECORD
    record_size = RECORD_SIZE

    def variable(self, var: int) -> int | None:
        """A script variable's value in the running game, None when it does not read."""
        from automap import amigavars  # noqa: PLC0415

        return amigavars.read_variable(self.target(), self.title, var).value


def wander(screens: Screens, memory: Any, start: dict, plan: dict,
           limit: int = WANDER_STEPS) -> dict:
    """Walk `plan`'s route, then step back and forth between its two squares, until a step
    brings up a screen that is not the map. Each move is read back from memory, and after each
    step the map must hold `STEP_SETTLE` seconds before the next key."""
    steps: list[dict] = []
    x, y, facing = start["x"], start["y"], start["facing"]
    seen = memory.fix()
    require(seen == (x, y, facing), f"the party stands at {seen}, not the loaded {x},{y},{facing}")
    screens.wait(("world",), 30, past=())

    def until(want: tuple[int, int, int]) -> tuple[int, int, int] | None:
        end = screens.clock() + MOVE_LIMIT
        got = None
        while screens.clock() < end:
            got = memory.fix()
            if got == want:
                break
            screens.sleep(1.0)
        return got

    def settled() -> str | None:
        """None while the map holds for `STEP_SETTLE`; else the crop that showed another screen."""
        end = screens.clock() + STEP_SETTLE
        while screens.clock() < end:
            shown, shot = screens.look("step")
            # A grab that left no crop is no reading of the screen.
            if "world" not in shown and not pathlib.Path(shot).name.endswith("-raw.png"):
                screens.events.append({"met": shown, "shot": str(shot)})
                return str(shot)
            screens.sleep(2.0)
        return None

    headings = list(plan["route"])
    back = (plan["facing"] + 2) % 4
    for n in range(len(headings) + limit):
        heading = headings[n] if n < len(headings) else (
            plan["facing"] if (n - len(headings)) % 2 == 0 else back)
        for key in TURN_KEYS.get((heading - facing) % 4, ()):
            facing = (facing + (1 if key == "NP6" else -1)) % 4
            screens.press(key, "world")
            got = until((x, y, facing))
            require(got == (x, y, facing), f"{key} left the party at {got}, not {x},{y},{facing}")
        dx, dy = STEP[heading]
        x, y = x + dx, y + dy
        screens.press("NP8", "world")
        got = until((x, y, facing))
        met = settled()
        require(got == (x, y, facing) or met is not None,
                f"NP8 left the party at {got}, not {x},{y},{facing}")
        steps.append({"x": x, "y": y, "facing": facing})
        if met is not None:
            return {"steps": steps, "met": met}
    raise RouteError(f"{limit} steps between the two squares met no fight")


#: The wandering fight: the map may still show while its monsters load, and a lost fight ends
#: on the destroyed message, after its one RETURN, or on a menu, with no key.
SSB_FIGHT = cursefight.FightRules(
    known=KNOWN, answers=FIGHT_ANSWERS, bar_fields=tuple(RECORD), linger=NO_BAR_LIMIT,
    defeat=DEFEAT, name_key=name_key)


def fight(screens: Screens, memory: Any, members: list[str], found: dict | None = None) -> dict:
    """Answer every screen from the encounter to the map; log each bar with its owner."""
    return cursefight.fight(screens, memory, members, SSB_FIGHT, found=found)


def capture(screens: Screens, memory: Any, before: int) -> dict:
    """Wait, pressing only RETURN on a continue page, for a member's command bar; press nothing on it.

    A bar is a screen held `CAPTURE_STILL` seconds while the record in turn is a party member
    the player controls and the turn pointer has moved off `before`, its value before the walk,
    or a screen the `combat_bar` guard knows. Only the guard confirms it: this repository has no
    reader for the title's font, so a bar known by stillness alone is returned unconfirmed, for
    the crop to be read by eye before it becomes a guard.
    """
    started = still_since = screens.clock()
    last: object = object()
    while True:
        require(screens.clock() - started < CAPTURE_LIMIT,
                f"no member's command bar within {CAPTURE_LIMIT:.0f}s")
        seen, shot = screens.look("capture")
        state = next((s for s in KNOWN if s in seen), None)
        digest = cursefight._digest(shot)
        if digest != last:
            last, still_since = digest, screens.clock()
        if state in DEFEAT:
            return {"outcome": "lost", "shot": str(shot)}
        if state == "continue":
            screens.press("RET", "continue")
            screens.sleep(AFTER_KEY)
            continue
        held = digest is not None and screens.clock() - still_since >= CAPTURE_STILL
        if state == "combat_bar" or (state is None and held):
            owner = curseadd.bounded(lambda _h: memory.owner(), memory.holder,
                                     screens.left(READ_LIMIT))
            guarded = state == "combat_bar"
            if owner is not None and (guarded or (owner["address"] != before
                                                  and owner["side"] == 0
                                                  and owner["control"] < 0x80)):
                again, again_shot = screens.look("capture-again")
                if cursefight._digest(again_shot) == digest:
                    found = {"outcome": "bar", "shot": str(shot), "owner": owner,
                             "turn_before": before, "confirmed": guarded,
                             "support": "the combat_bar guard" if guarded else
                             "stillness and the turn pointer only; read the crop by eye"}
                    screens.events.append({"capture": found})
                    return found
        screens.sleep(2.0)


def answer_journal(screens: Screens, answer: Callable, adf: pathlib.Path) -> None:
    """Run the journal answerer on the challenge the guard saw, again while it finds none."""
    for _ in range(JOURNAL_TRIES):
        code, line = answer(screens.holder, adf, screens.left(180))
        screens.events.append({"answer": line, "exit_code": code})
        if code == 0 and line == "answered":
            return
        require(line == "no challenge on screen", f"the journal answerer ended {code}: {line!r}")
        screens.sleep(3.0)
    raise RouteError(f"the journal answerer found no challenge in {JOURNAL_TRIES} tries")


def wait_past_journal(screens: Screens, want: tuple[str, ...], limit: float, answer: Callable,
                      adf: pathlib.Path, past: tuple[str, ...]) -> str:
    """Wait for one of `want`, answering the journal question if it comes first."""
    got = screens.wait((*want, "journal"), limit, past=past)
    if got != "journal":
        return got
    answer_journal(screens, answer, adf)
    return screens.wait(want, limit, past=("journal", *past))


def drive(screens: Screens, manifest: dict, members: list[str], memory: Any, answer: Callable,
          *, save: bool, capture_only: bool = False, found: dict | None = None) -> dict:
    """Load, begin, walk to the fight and take it; each reading goes into `found` as it is
    made, so a step that stops still leaves what came before it for the receipt."""
    fight_ = manifest["fight"]
    adf = pathlib.Path(manifest["disks"]["df0"]["path"])
    found = {} if found is None else found
    screens.to_title(300)
    screens.press("P", "title")
    screens.wait(("party_menu",), 60, past=("title",))
    screens.press("L", "party_menu")
    screens.wait(("load_picker",), 60, past=("party_menu",))
    screens.press(fight_["load"], "load_picker")
    screens.wait(("loaded_menu",), 120, past=("load_picker", "scrolls_dropped"))
    found["loaded"] = curseadd.bounded(lambda _h: memory.party(), memory.holder,
                                       screens.left(READ_LIMIT))
    names = [name_key(m["name"]) for m in found["loaded"]]
    require(names == [name_key(n) for n in fight_["names"]],
            f"the loaded party is {names}, not {fight_['names']}")
    screens.press("B", "loaded_menu")
    wait_past_journal(screens, ("world",), 120, answer, adf, past=("loaded_menu",))
    found["gate"] = curseadd.bounded(lambda _h: memory.variable(GATE), memory.holder,
                                     screens.left(READ_LIMIT))
    require(found["gate"] == GATE_ON,
            f"the gate ${GATE:04X} reads {found['gate']} in the running game, not {GATE_ON}")
    found["turn_before"] = curseadd.bounded(lambda _h: memory.turn_pointer(), memory.holder,
                                            screens.left(READ_LIMIT))
    screens.sleep(AFTER_KEY)
    found["walk"] = wander(screens, memory, fight_["place"], fight_)
    if capture_only:
        found["capture"] = capture(screens, memory, found["turn_before"])
        return found
    found.update(fight(screens, memory, members, found=found))
    if found["outcome"] != "won":
        return found
    found["after"] = curseadd.bounded(lambda _h: memory.party(), memory.holder,
                                      screens.left(READ_LIMIT))
    found["members"] = check_members(found["after"], manifest, members)
    if not save:
        return found
    screens.wait(("world",), 30, past=())
    screens.press("E", "world")
    screens.wait(("camp",), 60, past=("world",))
    screens.press("S", "camp")
    wait_past_journal(screens, ("camp_save_picker",), 60, answer, adf, past=("camp",))
    screens.press(fight_["save"], "camp_save_picker")
    wait_past_journal(screens, ("exit_game",), 120, answer, adf, past=("camp_save_picker",))
    screens.sleep(POST_WRITE_WAIT)
    screens.press("N", "exit_game")
    screens.wait(("camp",), 60, past=("exit_game",))
    return found


def _keyed(rows: list[dict]) -> list[dict]:
    return [{**row, "name": name_key(row["name"])} for row in rows]


def _keyed_manifest(manifest: dict) -> dict:
    fight_ = manifest["fight"]
    return {**manifest, "fight": {**fight_, "names": [name_key(n) for n in fight_["names"]],
                                  "members": {name_key(n): v
                                              for n, v in fight_["members"].items()}}}


def check_members(party: list[dict], manifest: dict, members: list[str]) -> dict:
    """Each named member is in the party with quickfight 1, still standing as loaded."""
    return cursefight.check_members(_keyed(party), _keyed_manifest(manifest),
                                    [name_key(n) for n in members])


def read_back(disk_path: pathlib.Path, manifest: dict) -> dict:
    """The saved slot's members and gate, and whether the loaded slot's file is still as staged."""
    fight_ = manifest["fight"]
    disk = amiga_adf.AmigaDisk.open(disk_path)
    staged = amiga_adf.AmigaDisk.open(manifest["disks"]["df0"]["path"])
    loaded_file = f"/SAVE/savgam{fight_['load']}.sav"
    saved = _slot(disk, fight_["save"])
    return {"letter": fight_["save"], "verify": disk.verify(),
            "loaded_slot_unchanged": disk.read_file(loaded_file) == staged.read_file(loaded_file),
            "gate": word(saved.data, GATE),
            "members": [{"name": m.name, **member_fields(m.raw)} for m in saved.characters]}


def verdict(found: dict, manifest: dict, members: list[str]) -> list[str]:
    """Problems with a read-back: empty when each named member was saved QUICK, as loaded."""
    keyed = {**found, "members": _keyed(found["members"])}
    return cursefight.verdict(keyed, _keyed_manifest(manifest), [name_key(n) for n in members])


def run(args: argparse.Namespace, *, guest: Any = None, guards: Any = None,
        boot: Callable = acceptance.boot_lane, halt: Callable = acceptance.halt_lane,
        memory: Any = None, answer: Callable | None = None,
        preflight: Callable[[str], None] = route_silver_blades.journal_preflight,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep) -> dict:
    """Boot a staged manifest, walk to the fight, fight or capture, save once unless told not to."""
    require(0 <= args.wait_lane <= 1800, "lane wait exceeds 1800 seconds")
    require(0 < args.budget <= 3600, "budget must be at most 3600 seconds")
    require(not args.out.exists(), f"{args.out} already exists")
    manifest = json.loads(args.manifest.read_text())
    require("fight" in manifest and manifest.get("title") == "ssb",
            "the manifest is not an ssbfight.py stage")
    fight_ = manifest["fight"]
    keys = [name_key(n) for n in fight_["names"]]
    absent = [name for name in args.member if name_key(name) not in keys]
    require(not absent, f"{absent} are not in slot {fight_['load']}: {fight_['names']}")
    rules = guard_rules()
    if not args.capture:
        require(bool(args.member), "name at least one --member")
        require("combat_bar" in rules, "the Silver Blades guard map has no combat_bar rule yet; "
                                       "capture the bar with --capture first")
    require(answer is not None or bool(args.journal_python),
            "--journal-python is needed to answer the journal question at BEGIN")
    if args.journal_python:
        preflight(args.journal_python)
    if answer is None:
        answer = lambda holder, adf, timeout: route_silver_blades.run_journal_answer(  # noqa: E731
            args.journal_python, holder, adf, timeout)
    for key, entry in (*manifest["disks"].items(), *manifest["registered"].items()):
        require(sha256(pathlib.Path(entry["path"])) == entry["sha256"], f"the {key} disk hash differs")
    staged = amiga_adf.AmigaDisk.open(manifest["disks"]["df0"]["path"])
    require(fight_["save"] not in amiga_savegame.slots_present(staged, TITLE),
            f"slot {fight_['save']} is already on the staged disk")
    args.out.mkdir(parents=True)
    receipt: dict[str, Any] = {"started_utc": datetime.now(timezone.utc).isoformat(),
                               "manifest": str(args.manifest.resolve()), "holder": args.holder,
                               "members": list(args.member), "capture": args.capture,
                               "save": not (args.no_save or args.capture),
                               "uncaptured": missing(rules), "out": str(args.out.resolve()),
                               "success": False, "cleanup": []}
    guest = guest if guest is not None else WinGuest()
    memory = memory if memory is not None else Memory(args.holder)
    command = [str(pathlib.Path(__file__)), "run", "--manifest", str(args.manifest),
               "--holder", args.holder, "--out", str(args.out),
               *(f"--member={name}" for name in args.member),
               *(["--no-save"] if args.no_save else []), *(["--capture"] if args.capture else [])]
    booted = False
    found: dict[str, Any] = {}
    screens = None
    try:
        guard_file = args.out / "guards.json"
        write_json(guard_file, rules)
        guards = guards if guards is not None else PixelGuards(guard_file)
        proof = curseadd.mute(guest, args.out, timeout=60)
        title = boot_title(manifest["issue"])
        receipt["boot"] = boot(args.manifest, manifest, title, guest=guest, holder=args.holder,
                               audio_proof=proof, wait_lane=args.wait_lane, timeout=300,
                               command=command)
        booted = True
        screens = Screens(guest, args.holder, args.out / "screens", guards, clock() + args.budget,
                          clock=clock, sleep=sleep)
        receipt.update(drive(screens, manifest, list(args.member), memory, answer,
                             save=receipt["save"], capture_only=args.capture, found=found))
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for key, value in found.items():
            receipt.setdefault(key, value)
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
        fetched = (receipt.get("halt") or {}).get("fetched", {}).get("df0")
        if "error" in receipt:
            pass
        elif args.capture:
            got = receipt.get("capture", {})
            if got.get("outcome") != "bar":
                receipt["problems"] = [
                    f"the party was destroyed before a member's bar; shot {got.get('shot')}"]
            elif not got.get("confirmed"):
                receipt["problems"] = [
                    f"the bar at {got.get('shot')} is known only by {got.get('support')}; "
                    "nothing confirms it"]
            else:
                receipt["problems"] = []
        elif receipt.get("outcome") == "lost":
            receipt["problems"] = ["the party was destroyed, so nothing was saved"]
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
    s = sub.add_parser("stage", help="copy a Silver Blades disk one in as DF0 with its slot's "
                                     "wandering-fight gate set")
    s.add_argument("--source-disk", type=pathlib.Path, required=True,
                   help="a Silver Blades disk one whose SAVE drawer holds the slot to load")
    s.add_argument("--load", required=True, help="the slot the run loads, in area 16")
    s.add_argument("--save", required=True, help="the free slot the run saves to")
    s.add_argument("--diskb", type=pathlib.Path, help="disk B; the registered one by default")
    s.add_argument("--issue", default="391", help="the ticket number naming the guest's disks")
    s.add_argument("--out", type=pathlib.Path, required=True)
    g = sub.add_parser("run", help="boot a staged manifest in one muted WinUAE lane, walk until "
                                   "the fight, take it, save once, halt, fetch and read back")
    g.add_argument("--manifest", type=pathlib.Path, required=True, help="the stage's prepare.json")
    g.add_argument("--holder", required=True)
    g.add_argument("--out", type=pathlib.Path, required=True, help="a fresh folder for the run")
    g.add_argument("--member", action="append", default=[],
                   help="a member who must get a command bar, hold quickfight 1 after the fight "
                        "and still stand; repeat for several")
    g.add_argument("--journal-python", help="the interpreter `amigabladesjournal.py` runs under")
    g.add_argument("--no-save", action="store_true",
                   help="stop after the fight's checks, saving nothing")
    g.add_argument("--capture", action="store_true",
                   help="stop at the fight's first member's command bar, pressing nothing on it")
    g.add_argument("--budget", type=float, default=2700)
    g.add_argument("--wait-lane", type=float, default=0, metavar="SECONDS")
    r = sub.add_parser("read", help="read a fetched disk's saved slot against a manifest")
    r.add_argument("--manifest", type=pathlib.Path, required=True)
    r.add_argument("--disk", type=pathlib.Path, required=True)
    r.add_argument("--member", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        with terminating():
            if args.command == "stage":
                print(stage(args.source_disk, args.out, load=args.load, save=args.save,
                            diskb=args.diskb, issue=args.issue))
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
        print(f"ssbfight: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
