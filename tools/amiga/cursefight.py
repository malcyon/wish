#!/usr/bin/env python3
"""Take an Amiga Curse party into a fight, log each command bar's owner, and save.

`stage` puts a copy of a Curse save disk some earlier run fetched in place of a prepare run's
disk A and writes a manifest. A slot in Tilverton (area 1) gets the tavern brawl; a slot in the
Pit of Moander (area 17) gets a wandering fight, and the copy's slot has the Pit's wandering
gate `$4C2D` set to `$80`, a value the area's script writes itself. `run` boots it in one muted
WinUAE lane and, pressing only on guarded screens, loads the slot and begins. In Tilverton it
walks the area's own map (`GEO.GLB` on disk B) to the tavern at 6,10 and answers PUNCH
BARKEEP; in the Pit it reads the gate back from the running game, then steps between two of
`GEO11`'s roll squares, reading the party's square before each step and stepping only onto a
roll square, until a step brings up a screen that is not the map, and answers the giant
slugs' ATTACK EVADE with ATTACK. Either way it answers every command bar with QUICK, so the
fight runs itself as the DOS fight step's does, and at each bar it reads whose bar it is from
memory and logs it. After the fight it checks each `--member` had a bar, now holds
quickfight 1 and still stands, then camps and saves once to the staged letter, halts,
fetches the disk and reads the slot back. `--no-save` stops after that check. A party the
fight destroys gets RETURN on the destroyed message, and the run ends there, lost, saving
nothing. A brawl counts as won only once the game shows THE PARTY HAS WON. `--no-fight`
loads the slot, begins, then camps and saves at once, with no walk and no fight, and reads
the save back, each member's combat picture included. Memory is only read, never written, so the Pit's gate stays at `$80` in a save the run makes; the
receipt records it.
`read` reads a fetched disk's saved slot against a staged manifest.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
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
from tools.amiga.staging import replace_file_in_place, sha256  # noqa: E402
from tools.amiga.winuaesession import RouteError, WinGuest, terminating  # noqa: E402

require = curseadd.require
write_json = curseadd.write_json
TITLE = route_curse.CURSE_KEY

#: Tilverton's tavern: area 1, square 6,10, whose bar starts the brawl (the DOS fight step's
#: `CURSE_TAVERN`), walked over the area's own map, `GEO01` in disk B's `GEO.GLB`.
TAVERN_AREA = 1
TAVERN_GEO = "GEO01"
TAVERN = (6, 10)
#: Record offsets in `/Curse`: name at 0, control 0xF7, the combat picture 0x127 (a joined
#: companion's own, DOS 0x126), status 0x19A, side 0x19C, quickfight 0x19D (QUICK at 0x386C
#: sets it; the turn test at 0x2C24 reads it), hit points 0x1A9.
RECORD = {"control": 0xF7, "picture": 0x127, "status": 0x19A, "side": 0x19C,
          "quickfight": 0x19D, "hit_points": 0x1A9}
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
    # ASK ABOUT INJURIES / IGNORE THEM, which a save whose brawl already happened shows
    # before the PUNCH bar; the text line above it (the bartender's black eye) is the `and`.
    "injuries": {"box": [72, 404, 556, 426],
                 "sha256": "43f01d090eccc05783eeedda1c69823ad0474432caf91960c4fbb6370f76f71d",
                 "and": [{"box": [74, 302, 690, 318],
                          "sha256": "67c4990b5d5d9b01fabe5b7b710219be9e0bcdacf41f882e9a72ba2ed4d2098b"}]},
    # The brawl script's line after every fight it starts, won or lost (`ECL01 $8ACA`, the
    # same block in disk B's `ECL.GLB`), over the same RETURN bar as every `continue` box.
    "tossed": {"box": [74, 302, 690, 318],
               "sha256": "c0673a24f91bb7991f3c3139ce81fbc68556aee0ae50230a88d853ad4fe9c8f8"},
    # THE PARTY HAS WON, the first line of the game's end-of-fight message (`/Curse 0x2D620`)
    # over the RETURN bar, cut from the four won brawls kept (WISH-303 `i4-dos/stage/run2/
    # screens/178-fight.png`, `run1` 170, `i4-c64/stage/run2` 216, WISH-390 `run2` 111).
    "party_won": {"box": [74, 78, 640, 96],
                  "sha256": "64177b35adb9b7300e0e46e77a5de3f0973a5ada6de8336a8937ea04fe12cc4d",
                  "and": [{"box": [72, 404, 686, 426],
                           "sha256": "1bf2400681523aa4dc95ae92305564fd26f826fa60277596e7801505cb6dd73c"}]},
    # The destroyed party's message over a PRESS ANY KEY bar, cut from the Pit run that lost
    # to shambling mounds (WISH-388 `c64join-amiga-pit/run1/screens/216-fight.png`); the text
    # box alone would also match the same words over another bar, so the bar is the `and`.
    "party_destroyed": {"box": [90, 108, 656, 146],
                        "sha256": "ee9bc04a0212b97c277a22fd81edb01de359ad6cb1668a2128456fd1344d7c7b",
                        "and": [{"box": [72, 404, 686, 426],
                                 "sha256": "64ccbcfd2cec635e30dc2c838c8039916f77553e5a819c06412a00640054197b"}]},
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
#: "party_won", "party_destroyed" and "tossed" come before "continue": the first known screen
#: a grab matches names it.
KNOWN = ("intro", "front_end", "title", "load_picker", "load_error", "loaded_menu", "world",
         "party_won", "party_destroyed", "tossed", "continue", "tavern", "injuries", "combat_bar", "continue_battle", "treasure",
         "treasure_left", "investigate", "camp", "camp_save_picker", "exit_game")
#: The only keys each screen may receive. The tavern's L(EAVE) is for a bar shown again after
#: the fight; the investigate question is answered NO, which keeps the party out of a second fight.
ALLOWED_KEYS = {
    "intro": frozenset({"ESC"}), "front_end": frozenset({"ESC"}), "title": frozenset({"L"}),
    "load_picker": frozenset("ABCDEFGHIJ"), "load_error": frozenset({"RET"}),
    "loaded_menu": frozenset({"B"}), "world": frozenset({"NP4", "NP6", "NP8", "E"}),
    "continue": frozenset({"RET"}), "tossed": frozenset({"RET"}),
    "party_won": frozenset({"RET"}),
    "tavern": frozenset({"P", "L"}), "injuries": frozenset({"I"}),
    "combat_bar": frozenset({"Q"}), "continue_battle": frozenset({"N"}),
    "treasure": frozenset({"E"}), "treasure_left": frozenset({"N"}),
    "investigate": frozenset({"N"}), "camp": frozenset({"S"}),
    "camp_save_picker": frozenset("ABCDEFGHIJ"), "exit_game": frozenset({"N"}),
    "attack_evade": frozenset({"A"}), "party_destroyed": frozenset({"RET"}),
}
#: Answers to the screens that come between the first command bar and the map.
FIGHT_ANSWERS = {"combat_bar": "Q", "continue_battle": "N", "treasure": "E",
                 "treasure_left": "N", "investigate": "N", "continue": "RET", "tossed": "RET",
                 "party_won": "RET", "party_destroyed": "RET"}
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
READ_LIMIT = curseadd.READ_LIMIT
POST_WRITE_WAIT = 20.0
SLOT = curseadd.SLOT

#: The Pit of Moander, area 17, walked over its own map, `GEO11` in disk B's `GEO.GLB`. Its
#: script, the `ECL.GLB` block for area 17, is the C64's `ECL11` byte for byte. Its step
#: entry masks the square byte with `$3F` and sends id 0 to the wandering roll, which with
#: the gate `$4C2D` at `$80` rolls on every such step and fights under 15 (`$85A3`-`$85E3`);
#: at 0 it never rolls. Every arm the roll picks with the gate at `$80` fights.
PIT_AREA = 17
PIT_GEO = "GEO11"
PIT = "pit"
PIT_GATE = 0x4C2D
PIT_GATE_ON = 0x80
PIT_SQUARE_MASK = 0x3F
#: Steps between the two roll squares the walk takes looking for the fight before the run stops.
PIT_STEPS = 60
#: Seconds the map must hold after a step before the next key: a fight's monsters load with
#: the map bar still drawn, and a key sent then would land in the fight.
STEP_SETTLE = 12.0
#: Seconds the map, still drawn while the monsters load, may show before the first bar.
PIT_LINGER = 60.0
#: The receipt's names for the gate read from the running game at the first map screen and
#: after the fight, and from the saved slot read back.
LIVE_GATE = f"wander_gate_{PIT_GATE:04X}"
GATE_AFTER = f"wander_gate_{PIT_GATE:04X}_after_fight"
SAVED_GATE = f"saved_wander_gate_{PIT_GATE:04X}"
#: Pit screens the Curse guard map has no rule for. No grab matches one, so a run that meets
#: it presses nothing on it and stops after `FIGHT_STALL`, keeping the frame; `missing` lists
#: those still without a rule.
UNCAPTURED = {
    "attack_evade": "the giant slugs' ATTACK EVADE bar (`HORIZMENU` at `ECL11 $90DC`)",
}
#: "party_destroyed" comes before "continue": the first known screen a grab matches names it.
PIT_KNOWN = ("intro", "front_end", "title", "load_picker", "load_error", "loaded_menu", "world",
             "party_destroyed", "continue", "attack_evade", "combat_bar", "continue_battle", "treasure",
             "treasure_left", "camp", "camp_save_picker", "exit_game")
#: Answers to the screens between the step that met the monsters and the map after the fight;
#: the slugs' question gets ATTACK, never EVADE, and the destroyed party's message RETURN.
PIT_ANSWERS = {"continue": "RET", "attack_evade": "A", "combat_bar": "Q",
               "continue_battle": "N", "treasure": "E", "treasure_left": "N",
               "party_destroyed": "RET"}


class Screens(curseadd.Screens):
    known = KNOWN
    allowed = ALLOWED_KEYS


class PitScreens(curseadd.Screens):
    known = PIT_KNOWN
    allowed = ALLOWED_KEYS


def guard_rules() -> dict:
    """The Curse guard map with this route's screens added."""
    rules = curseadd.guard_rules()
    require(not set(FIGHT_GUARDS) & set(rules), "a fight guard name is already a Curse guard")
    return {**rules, **FIGHT_GUARDS}


def missing(rules: dict) -> list[str]:
    """The `UNCAPTURED` screens the guard map still has no rule for."""
    return [state for state in UNCAPTURED if state not in rules]


def gate_word(data: bytes) -> int:
    """The Pit's gate from a saved game's bytes; `amiga_savegame.word` takes Pool's numbering."""
    return amiga_savegame.word(data, PIT_GATE - 0x200, amiga_savegame.CURSE)


def with_gate(data: bytes, value: int) -> bytes:
    """The saved game's bytes with the Pit's gate replaced."""
    at = amiga_savegame.CURSE.vm_offset(PIT_GATE - 0x200)
    return data[:at] + value.to_bytes(2, "big") + data[at + 2:]


def roll_square(geo, x: int, y: int) -> bool:
    """A Pit square whose step runs only the wandering roll: id 0 once masked as `$8523` masks it."""
    return 0 <= x < 16 and 0 <= y < 16 and geo.attributes(x, y) & PIT_SQUARE_MASK == 0


def pit_plan(geo, start: tuple[int, int]) -> dict:
    """The facings to the nearest roll square with a roll square open beside it both ways, the
    facing from it to that neighbour, and every roll square the walk may step onto. Only roll
    squares are entered, so no other square's script runs on the way."""
    def pair(x: int, y: int) -> int | None:
        for facing, (dx, dy) in STEP.items():
            if (roll_square(geo, x + dx, y + dy) and geo.is_passable(x, y, facing)
                    and geo.is_passable(x + dx, y + dy, (facing + 2) % 4)):
                return facing
        return None

    previous: dict[tuple[int, int], Any] = {start: None}
    queue = collections.deque([start])
    while queue:
        here = queue.popleft()
        if roll_square(geo, *here) and pair(*here) is not None:
            route, at = [], here
            while previous[at]:
                at, facing = previous[at]
                route.append(facing)
            facing = pair(*here)
            dx, dy = STEP[facing]
            squares = {here, (here[0] + dx, here[1] + dy)}
            at = start
            for heading in reversed(route):
                at = (at[0] + STEP[heading][0], at[1] + STEP[heading][1])
                squares.add(at)
            return {"route": list(reversed(route)), "square": list(here), "facing": facing,
                    "roll_squares": sorted([list(sq) for sq in squares])}
        for facing, (dx, dy) in STEP.items():
            nxt = (here[0] + dx, here[1] + dy)
            if nxt in previous or not roll_square(geo, *nxt) or not geo.is_passable(*here, facing):
                continue
            previous[nxt] = (here, facing)
            queue.append(nxt)
    raise RouteError(f"no roll square with an open roll square beside it is reachable from {start}")


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


def area_map(diskb: pathlib.Path, name: str):
    """The map `name` out of disk B's `GEO.GLB`."""
    from automap import amiga  # noqa: PLC0415

    maps = amiga.load_maps(diskb)
    require(name in maps, f"{diskb} holds no {name}")
    return maps[name]


def tavern_map(diskb: pathlib.Path):
    """`TAVERN_GEO` out of disk B's `GEO.GLB`."""
    return area_map(diskb, TAVERN_GEO)


def stage_gate(local: pathlib.Path, load: str) -> dict:
    """Set the Pit's gate in slot `load` of the copy at `local`, in place; the copy's new digest."""
    path = amiga_savegame.slot_path(amiga_savegame.CURSE, load)
    copy = amiga_adf.AmigaDisk.open(local)
    staged = with_gate(copy.read_file(path), PIT_GATE_ON)
    replace_file_in_place(copy, path, staged)
    copy.save(local)
    check = amiga_adf.AmigaDisk.open(local)
    require(not check.verify() and check.read_file(path) == staged,
            "the staged slot does not read back")
    require(gate_word(check.read_file(path)) == PIT_GATE_ON, "the staged gate does not read back")
    return {"path": str(local), "sha256": sha256(local)}


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
    require(state.area in (TAVERN_AREA, PIT_AREA),
            f"slot {load} is in area {state.area}; the route knows only Tilverton, area "
            f"{TAVERN_AREA}, and the Pit of Moander, area {PIT_AREA}")
    diskb = pathlib.Path(manifest["disks"]["diskb"]["path"])
    if state.area == TAVERN_AREA:
        walk_plan: dict[str, Any] = {"route": plan(tavern_map(diskb), (state.x, state.y), TAVERN)}
        require(bool(walk_plan["route"]), f"no way from {state.x},{state.y} to the tavern")
    else:
        walk_plan = {"kind": PIT, **pit_plan(area_map(diskb, PIT_GEO), (state.x, state.y))}
    out.mkdir(parents=True)
    disks = {}
    for key, source in (("save", source_disk), ("diskb", diskb)):
        local = out / f"{key}.adf"
        shutil.copyfile(source, local)
        disks[key] = {"path": str(local), "sha256": sha256(local)}
    require(disks["save"]["sha256"] == source_hash, "the copy differs from the source disk")
    if state.area == PIT_AREA:
        walk_plan["staged"] = {f"{PIT_GATE:04X}": {"before": gate_word(saved.data),
                                                   "after": PIT_GATE_ON}}
        disks["save"] = stage_gate(pathlib.Path(disks["save"]["path"]), load)
    staged = {**manifest, "disks": disks,
              "prepared_from": {"path": str(manifest_path.resolve()),
                                "save_sha256": manifest["disks"]["save"]["sha256"]},
              "fight": {"source": {"path": str(source_disk.resolve()), "sha256": source_hash},
                        "load": load, "save": save, "place": place, **walk_plan,
                        "names": [m.name for m in saved.characters],
                        "members": {m.name: member_fields(m.raw) for m in saved.characters}}}
    path = out / "prepare.json"
    write_json(path, staged)
    return path


class Memory:
    """Reads of the running game through WinUAE's pipe: never a write.

    The class attributes name the title, the global holding the record in turn and the
    record's fields; a subclass for another title replaces them.
    """

    title = TITLE
    current = CURRENT
    record = RECORD
    record_size = RECORD_SIZE

    def __init__(self, holder: str):
        self.holder = holder
        self._target: Any = None

    def target(self) -> Any:
        if self._target is None:
            from automap import amiga  # noqa: PLC0415

            target = amiga.AmigaTarget(amiga.WinuaePipe(holder=self.holder),
                                       amiga.MACHINES[self.title])
            target.locate()
            self._target = target
        return self._target

    def fields(self, raw: bytes) -> dict[str, int]:
        return {field: raw[at] for field, at in self.record.items()}

    def fix(self) -> tuple[int, int, int] | None:
        fix = self.target().fix()
        return None if fix is None else (fix.x, fix.y, fix.facing)

    def turn_pointer(self) -> int:
        """The address the global names as the record in turn; 0 before any turn."""
        target = self.target()
        return int.from_bytes(target.read(target.data_base + self.current, 4), "big")

    def owner(self) -> dict | None:
        address = self.turn_pointer()
        if not address:
            return None
        raw = bytes(self.target().read(address, self.record_size))
        return {"address": address, "name": _name(raw), **self.fields(raw)}

    def party(self) -> list[dict]:
        from automap import amigaparty  # noqa: PLC0415

        members = amigaparty.read_party(self.target())
        require(members is not None, "the party list does not read")
        return [{"name": m.name, **self.fields(m.raw)} for m in members]

    def variable(self, var: int) -> int | None:
        """A script variable's value in the running game, None when it does not read."""
        from automap import amigavars  # noqa: PLC0415

        return amigavars.read_variable(self.target(), self.title, var).value


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


def pit_walk(screens: Any, memory: Any, start: dict, fight_: dict,
             limit: int = PIT_STEPS) -> dict:
    """Walk the plan's route, then step back and forth between its two roll squares, until a
    step brings up a screen that is not the map.

    Before each forward key the party's square and facing are read from memory, and the key
    goes only when they are where the walk left the party and the square ahead is one of the
    plan's roll squares; otherwise the walk stops with nothing sent. Every key goes on a grab
    the map guard matched. Each move is read back from memory, and after each step the map must
    hold `STEP_SETTLE` seconds before the next key.
    """
    steps: list[dict] = []
    roll = {tuple(sq) for sq in fight_["roll_squares"]}
    x, y, facing = start["x"], start["y"], start["facing"]
    seen = memory.fix()
    require(seen == (x, y, facing), f"the party stands at {seen}, not the loaded {x},{y},{facing}")

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

    headings = list(fight_["route"])
    back = (fight_["facing"] + 2) % 4
    for n in range(len(headings) + limit):
        heading = headings[n] if n < len(headings) else (
            fight_["facing"] if (n - len(headings)) % 2 == 0 else back)
        for key in TURN_KEYS.get((heading - facing) % 4, ()):
            facing = (facing + (1 if key == "NP6" else -1)) % 4
            screens.wait(("world",), 30, past=())
            screens.press(key, "world")
            got = until((x, y, facing))
            require(got == (x, y, facing), f"{key} left the party at {got}, not {x},{y},{facing}")
        screens.wait(("world",), 30, past=())
        seen = memory.fix()
        require(seen == (x, y, facing),
                f"the party stands at {seen}, not {x},{y},{facing}; no step was sent")
        dx, dy = STEP[heading]
        require((x + dx, y + dy) in roll,
                f"{x + dx},{y + dy} ahead of {x},{y} is not one of the plan's roll squares; "
                "no step was sent")
        x, y = x + dx, y + dy
        screens.press("NP8", "world")
        got = until((x, y, facing))
        met = settled()
        require(got == (x, y, facing) or met is not None,
                f"NP8 left the party at {got}, not {x},{y},{facing}")
        steps.append({"x": x, "y": y, "facing": facing})
        if met is not None:
            return {"steps": steps, "met": met}
    raise RouteError(f"{limit} steps between the two roll squares met no fight")


def reach_tavern(screens: Screens) -> None:
    """Wait for the PUNCH bar, answering the injuries question that comes first on a save
    whose brawl already happened with IGNORE THEM."""
    if screens.wait(("tavern", "injuries"), 60, past=("world", "continue")) == "injuries":
        screens.press("I", "injuries")
        screens.sleep(AFTER_KEY)
        screens.wait(("tavern",), 60, past=("world", "continue", "injuries"))


def _same(name: str) -> str:
    return name


@dataclasses.dataclass(frozen=True)
class FightRules:
    """What one title's fight loop recognises and answers."""

    #: The states told apart, in the order a grab's first match names it.
    known: tuple[str, ...]
    #: The key each answered screen gets.
    answers: dict[str, str]
    #: The record-in-turn fields each bar's log keeps.
    bar_fields: tuple[str, ...]
    #: Seconds the map, or a screen in `starting`, may show before the first bar.
    linger: float
    #: Screens still drawn while the fight starts, waited out for `linger`.
    starting: tuple[str, ...] = ()
    #: Screens that get a key only once a bar has shown.
    after_bars: dict[str, str] = dataclasses.field(default_factory=dict)
    #: Screens that mean the fight was won. When any are named, a fight that reaches the map
    #: without one of them stops the run instead of being taken as won.
    won: tuple[str, ...] = ()
    #: Screens that end the fight as lost at once: one with a key in `answers` gets that key,
    #: and nothing after it is waited for; the others get none.
    defeat: tuple[str, ...] = ()
    #: How a bar owner's name and a `--member` name are compared.
    name_key: Callable[[str], str] = _same


#: The tavern brawl: the PUNCH bar may still show as the brawl starts and gets LEAVE after it.
#: The script prints the "tossed outside" line after the fight whatever its result, so the
#: result is read from the game's own end-of-fight message (`/Curse 0x2D538`): THE PARTY HAS
#: WON for a win, and for a party all down the destroyed message, which the brawl's script
#: never stops by setting the spare flag `$7EE6`.
CURSE_FIGHT = FightRules(
    known=KNOWN, answers=FIGHT_ANSWERS,
    bar_fields=("control", "status", "quickfight", "hit_points"), linger=TAVERN_LINGER,
    starting=("tavern",), after_bars={"tavern": "L"}, defeat=("party_destroyed",),
    won=("party_won",))

#: The Pit's wandering fight: the map may still show while its monsters load, and the
#: encounter's own pages and the slugs' question come before the first bar. A destroyed party's
#: message gets RETURN and ends the fight as lost, with nothing after it waited for.
PIT_FIGHT = FightRules(
    known=PIT_KNOWN, answers=PIT_ANSWERS,
    bar_fields=("control", "status", "quickfight", "hit_points"), linger=PIT_LINGER,
    defeat=("party_destroyed",))


def fight(screens: Screens, memory: Memory, members: list[str],
          rules: FightRules = CURSE_FIGHT, found: dict | None = None) -> dict:
    """Answer every screen from the first bar to the map; log each bar with its owner.

    With `found`, its `bars` and `answered` are the lists the loop fills as it goes, so a
    caller still holds them when a stop inside the fight raises.
    """
    bars: list[dict] = []
    answered: list[dict] = []
    if found is not None:
        found.update(bars=bars, answered=answered)
    started = still_since = screens.clock()
    settle_from = None
    lost = won = False
    last: object = object()
    while True:
        require(screens.clock() - started < FIGHT_LIMIT,
                f"the fight was still going after {FIGHT_LIMIT:.0f}s")
        seen, shot = screens.look("fight")
        state = next((s for s in rules.known if s in seen), None)
        digest = _digest(shot)
        # A grab with no crop counts as one more of the same, so a stuck one stops the run too.
        if digest != last:
            last, still_since = digest, screens.clock()
        # A fight the game ran without a command bar ends on the map after its won message.
        if state == "world" and (bars or won):
            settle_from = settle_from if settle_from is not None else screens.clock()
            if screens.clock() - settle_from >= MAP_SETTLE:
                break
            screens.sleep(2.0)
            continue
        settle_from = None
        if state == "world" and not bars and screens.clock() - started < rules.linger:
            # The map still showing while the fight starts.
            screens.sleep(1.5)
            continue
        if state in rules.defeat:
            key = rules.answers.get(state)
            if key is not None:
                screens.press(key, state)
            answered.append({"screen": state, "shot": str(shot),
                             **({"key": key} if key is not None else {})})
            lost = True
            break
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
                         **{field: owner[field] for field in rules.bar_fields},
                         "shot": str(shot), "number": len(bars) + 1})
            screens.events.append({"bar": bars[-1]})
        elif state in rules.after_bars and bars:
            key = rules.after_bars[state]
            screens.press(key, state)
            answered.append({"screen": state, "key": key, "shot": str(shot)})
            screens.sleep(AFTER_KEY)
            continue
        elif state in rules.starting:
            # The bar the fight began on, still drawn while it starts.
            require(screens.clock() - started < rules.linger,
                    f"the {state} bar stayed {rules.linger:.0f}s after the fight began; "
                    f"shot {shot}")
            screens.sleep(1.5)
            continue
        elif state not in rules.answers:
            raise RouteError(f"{state} showed mid-fight; shot {shot}")
        won = won or state in rules.won
        key = rules.answers[state]
        screens.press(key, state)
        answered.append({"screen": state, "key": key, "shot": str(shot)})
        screens.sleep(AFTER_KEY)
    require(lost or won or not rules.won,
            f"the fight reached the map without the {', '.join(rules.won)} screen, so its "
            f"result is unknown; shot {shot}")
    owners = {rules.name_key(bar["owner"]) for bar in bars}
    missing = [name for name in members if rules.name_key(name) not in owners]
    require(lost or not missing, f"{missing} had no command bar; bars went to {sorted(owners)}")
    return {"bars": bars, "answered": answered, "outcome": "lost" if lost else "won"}


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


def destroyed(found: dict, rules: FightRules) -> bool:
    """Record in `found` whether the fight ended on one of `rules`' defeat screens."""
    found["destroyed"] = bool(found["answered"]) and (
        found["answered"][-1]["screen"] in rules.defeat)
    return found["destroyed"]


def drive(screens: Screens, manifest: dict, members: list[str], memory: Memory, *,
          save: bool, found: dict | None = None, no_fight: bool = False) -> dict:
    """Load, begin, walk to the fight and take it; each reading goes into `found` as it is
    made, so a step that stops still leaves what came before it for the receipt. With
    `no_fight` the party camps and saves as loaded, with no walk and no fight. A destroyed
    party ends the drive at its message, saving nothing; after any other fight each member
    named must pass `check_members` before the save."""
    fight_ = manifest["fight"]
    pit = fight_.get("kind") == PIT
    found = {} if found is None else found
    screens.to_party_menu()
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
    if no_fight:
        screens.sleep(AFTER_KEY)
        camp_save(screens, fight_["save"])
        return found
    if pit:
        found[LIVE_GATE] = curseadd.bounded(lambda _h: memory.variable(PIT_GATE), memory.holder,
                                            screens.left(READ_LIMIT))
        require(found[LIVE_GATE] == PIT_GATE_ON,
                f"the gate ${PIT_GATE:04X} reads {found[LIVE_GATE]} in the running game, "
                f"not {PIT_GATE_ON}; no step was sent")
        screens.sleep(AFTER_KEY)
        found["walk"] = pit_walk(screens, memory, fight_["place"], fight_)
        found.update(fight(screens, memory, members, PIT_FIGHT, found=found))
        found["first_bar"] = found["bars"][0] if found["bars"] else None
        if destroyed(found, PIT_FIGHT):
            return found
        found[GATE_AFTER] = curseadd.bounded(lambda _h: memory.variable(PIT_GATE),
                                             memory.holder, screens.left(READ_LIMIT))
    else:
        screens.sleep(AFTER_KEY)
        found["walk"] = walk(screens, memory, fight_["place"], fight_["route"])
        reach_tavern(screens)
        screens.press("P", "tavern")
        screens.sleep(AFTER_KEY)
        found.update(fight(screens, memory, members))
        if destroyed(found, CURSE_FIGHT):
            return found
    found["after"] = curseadd.bounded(lambda _h: memory.party(), memory.holder,
                                      screens.left(READ_LIMIT))
    found["members"] = check_members(found["after"], manifest, members)
    if not save:
        return found
    camp_save(screens, fight_["save"])
    return found


def camp_save(screens: Screens, letter: str) -> None:
    """From the map: camp, save to `letter`, and answer the exit question with NO."""
    screens.wait(("world",), 30, past=())
    screens.press("E", "world")
    screens.wait(("camp",), 60, past=("world",))
    screens.press("S", "camp")
    screens.wait(("camp_save_picker",), 60, past=("camp",))
    screens.press(letter, "camp_save_picker")
    screens.wait(("exit_game",), 120, past=("camp_save_picker",))
    screens.sleep(POST_WRITE_WAIT)
    screens.press("N", "exit_game")
    screens.wait(("camp",), 60, past=("exit_game",))


def read_back(disk_path: pathlib.Path, manifest: dict) -> dict:
    """The saved slot's members, and whether the loaded slot's file is still as staged."""
    fight_ = manifest["fight"]
    disk = amiga_adf.AmigaDisk.open(disk_path)
    staged = amiga_adf.AmigaDisk.open(manifest["disks"]["save"]["path"])
    loaded_file = f"/SAVE/savgam{fight_['load']}.dat"
    saved = _slot(disk, fight_["save"])
    return {"letter": fight_["save"], "verify": disk.verify(),
            "loaded_slot_unchanged": disk.read_file(loaded_file) == staged.read_file(loaded_file),
            **({SAVED_GATE: gate_word(saved.data)} if fight_.get("kind") == PIT else {}),
            "members": [{"name": m.name, **member_fields(m.raw)} for m in saved.characters]}


def verdict(found: dict, manifest: dict, members: list[str], outcome: str = "won") -> list[str]:
    """Problems with a read-back: empty when each named member was saved QUICK, as loaded,
    and a Pit run's saved slot still holds the staged gate. After a lost fight the members
    never got a bar and some fell, so only their presence and control are checked; a fight does
    not change control. With no fight (`unfought`) nobody pressed QUICK, so quickfight is not
    checked. A member staged with his combat picture must be saved with the same one."""
    problems = []
    if manifest["fight"].get("kind") == PIT and found.get(SAVED_GATE) != PIT_GATE_ON:
        problems.append(f"the saved slot holds ${PIT_GATE:04X} = {found.get(SAVED_GATE)}, "
                        f"not the staged {PIT_GATE_ON}")
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
        if row["control"] != loaded["control"]:
            problems.append(f"{name} was saved as {row}, loaded as {loaded}")
        if "picture" in loaded and row.get("picture") != loaded["picture"]:
            problems.append(f"{name} was saved with picture {row.get('picture')}, "
                            f"staged with {loaded['picture']}")
        if outcome == "lost":
            continue
        if outcome == "won" and row["quickfight"] != 1:
            problems.append(f"{name} was saved with quickfight {row['quickfight']}")
        if row["status"] != loaded["status"]:
            problems.append(f"{name} was saved as {row}, loaded as {loaded}")
        if row["hit_points"] == 0:
            problems.append(f"{name} was saved at 0 hit points")
    return problems


def run(args: argparse.Namespace, *, guest: Any = None, guards: Any = None,
        boot: Callable = acceptance.boot_lane, halt: Callable = acceptance.halt_lane,
        memory: Any = None, clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep) -> dict:
    """Boot a staged manifest, drive its route, save once unless told not to, read back."""
    require(0 <= args.wait_lane <= 1800, "lane wait exceeds 1800 seconds")
    require(0 < args.budget <= 3600, "budget must be at most 3600 seconds")
    require(not args.out.exists(), f"{args.out} already exists")
    no_fight = getattr(args, "no_fight", False)
    require(not (no_fight and args.no_save), "--no-fight saves; it cannot go with --no-save")
    manifest = json.loads(args.manifest.read_text())
    require("fight" in manifest and manifest.get("title") == "curse",
            "the manifest is not a cursefight.py stage")
    fight_ = manifest["fight"]
    pit = fight_.get("kind") == PIT
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
                               "fight": not no_fight,
                               "out": str(args.out.resolve()), "success": False, "cleanup": []}
    rules = guard_rules()
    if pit:
        receipt["uncaptured"] = missing(rules)
    guest = guest if guest is not None else WinGuest()
    memory = memory if memory is not None else Memory(args.holder)
    command = [str(pathlib.Path(__file__)), "run", "--manifest", str(args.manifest),
               "--holder", args.holder, "--out", str(args.out),
               *(f"--member={name}" for name in args.member),
               *(["--no-save"] if args.no_save else []),
               *(["--no-fight"] if no_fight else [])]
    booted = False
    found: dict[str, Any] = {}
    screens = None
    try:
        guard_file = args.out / "guards.json"
        write_json(guard_file, rules)
        guards = guards if guards is not None else PixelGuards(guard_file)
        proof = curseadd.mute(guest, args.out, timeout=60)
        receipt["boot"] = boot(args.manifest, manifest, route_curse.CURSE, guest=guest,
                               holder=args.holder, audio_proof=proof, wait_lane=args.wait_lane,
                               timeout=300, command=command)
        booted = True
        screens = (PitScreens if pit else Screens)(
            guest, args.holder, args.out / "screens", guards, clock() + args.budget,
            clock=clock, sleep=sleep)
        receipt.update(drive(screens, manifest, list(args.member), memory,
                             save=not args.no_save, found=found,
                             **({"no_fight": True} if no_fight else {})))
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
        fetched = (receipt.get("halt") or {}).get("fetched", {}).get("save")
        if "error" in receipt:
            pass
        elif receipt.get("destroyed"):
            receipt["problems"] = ["the party was destroyed, so nothing was saved"]
        elif args.no_save:
            receipt["problems"] = []
        elif fetched:
            try:
                found = read_back(pathlib.Path(fetched["path"]), manifest)
                receipt["read_back"] = found
                receipt["problems"] = verdict(found, manifest, list(args.member),
                                              "unfought" if no_fight
                                              else receipt.get("outcome", "won"))
            except Exception as exc:  # noqa: BLE001
                receipt["problems"] = [f"read-back: {type(exc).__name__}: {exc}"]
        else:
            receipt["problems"] = ["no fetched save disk"]
        errors = [item for item in receipt["cleanup"] if any(k.endswith("error") for k in item)]
        receipt["success"] = ("error" not in receipt and not errors and "halt" in receipt
                              and receipt.get("problems") == [])
        if "outcome" in receipt:
            receipt["fight_won"] = receipt["outcome"] == "won"
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
    s.add_argument("--load", required=True,
                   help="the slot the run loads, in Tilverton (area 1) or the Pit (area 17)")
    s.add_argument("--save", required=True, help="the free slot the run saves to")
    s.add_argument("--out", type=pathlib.Path, required=True)
    g = sub.add_parser("run", help="boot a staged manifest in one muted WinUAE lane, take the "
                                   "tavern or Pit fight, save once, halt, fetch and read back")
    g.add_argument("--manifest", type=pathlib.Path, required=True, help="the stage's prepare.json")
    g.add_argument("--holder", required=True)
    g.add_argument("--out", type=pathlib.Path, required=True, help="a fresh folder for the run")
    g.add_argument("--member", action="append", default=[],
                   help="a member who must get a command bar, hold quickfight 1 after the fight "
                        "and still stand; repeat for several")
    g.add_argument("--no-save", action="store_true",
                   help="stop after the fight's checks, saving nothing")
    g.add_argument("--no-fight", action="store_true",
                   help="load the slot, begin, then camp and save at once, with no walk and no "
                        "fight, and read the save back")
    g.add_argument("--budget", type=float, default=2700)
    g.add_argument("--wait-lane", type=float, default=0, metavar="SECONDS")
    r = sub.add_parser("read", help="read a fetched Curse disk's saved slot against a manifest")
    r.add_argument("--manifest", type=pathlib.Path, required=True)
    r.add_argument("--disk", type=pathlib.Path, required=True)
    r.add_argument("--member", action="append", default=[])
    r.add_argument("--receipt", type=pathlib.Path,
                   help="the run's receipt.json, whose outcome the read-back is judged by")
    r.add_argument("--outcome", choices=("won", "lost", "unfought"),
                   help="the fight's outcome, when no receipt is given")
    args = parser.parse_args(argv)
    try:
        with terminating():
            if args.command == "stage":
                print(stage(args.manifest, args.source_disk, args.out, load=args.load,
                            save=args.save))
                return 0
            if args.command == "run":
                receipt = run(args)
                print(json.dumps(receipt, indent=1, sort_keys=True))
                print(f"cursefight: fight outcome {receipt.get('outcome', 'unknown')}; "
                      f"success {receipt['success']}")
                return 0
            require(bool(args.member), "name at least one --member")
            require((args.receipt is None) != (args.outcome is None),
                    "give one of --receipt and --outcome")
            outcome = (args.outcome if args.receipt is None
                       else json.loads(args.receipt.read_text()).get("outcome"))
            if args.receipt is not None and outcome is None and not json.loads(
                    args.receipt.read_text()).get("fight", True):
                outcome = "unfought"
            require(outcome in ("won", "lost", "unfought"),
                    f"the fight outcome is {outcome!r}, not won, lost or unfought")
            manifest = json.loads(args.manifest.read_text())
            found = read_back(args.disk, manifest)
            problems = verdict(found, manifest, args.member, outcome)
            print(json.dumps({"found": found, "problems": problems}, indent=1, sort_keys=True))
            return 0 if not problems else 1
    except (RouteError, OSError, ValueError, KeyError, amiga_adf.AmigaDiskError) as exc:
        print(f"cursefight: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
