#!/usr/bin/env python3
"""Remove one member in Amiga Pool of Radiance's Training Hall, and check the `.cha` the game writes.

The party is loaded from a run folder `acceptance.py prepare --title pool` made,
walked to the Training Hall, and one member is highlighted and removed with the
hall's own party menu (`R`). The game writes `NAME.cha`, `.itm` and `.spc` to
the save disk. The run leaves the menu with `B`, halts the lane, fetches the
save disk and compares the `.cha` with the member's record read from memory
just before `R` and with his record in the loaded slot.

    tools/amiga/poolremove.py plan --manifest PREPARE.json
    tools/amiga/poolremove.py run --manifest PREPARE.json --member MAGNUS \\
        --holder H --out DIR [--wait-lane S]
    tools/amiga/poolremove.py judge --out DIR

The walk starts in New Phlan or anywhere in the Slums. A Slums walk keeps off
every Slums square that carries a script id until the gate square (`SLUMS_GATE`),
faces east and steps into New Phlan at (0,4). In New Phlan it keeps off every square
that carries a script id until the
hall's door at (6,2), where New Phlan's script loads the hall (area 11). Inside,
the party walks north to (6,0) and east into the magic-users' school at (7,0),
which asks whether to train; YES opens the party menu (ECL0B `PROGRAM 0`).
Every turn and step is checked against the party's square in memory, under the
encounter switch, after a machine snapshot the walk can go back to.

Every screen is matched against a guard, `guards_pool.json`'s or the hall's own
(`HALL_GUARDS` here), before a key goes in, and an unknown one stops the run; the
frames after `R` are kept.

The verdict passes when REMOVE wrote the member's `.cha` (a new file, or a
changed one where the name was already on the disk), nothing else changes but
`charlist.txt` and the member's `.itm` and `.spc`, the fetched disk verifies,
and the `.cha` equals
the in-memory record outside the cleaned name and the pointer fields
`POINTER_FIELDS`. Every difference from the slot record is listed, and the
control, status and creature-type bytes must agree with it.
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
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from goldbox import amiga_adf, amiga_por, amiga_savegame, areas, geo  # noqa: E402
from tools.amiga import acceptance, noencounters, route_pool  # noqa: E402
from tools.amiga.screens import PixelGuards  # noqa: E402
from tools.amiga.staging import sha256  # noqa: E402
from tools.amiga.winuaesession import RouteError, WinGuest, terminating  # noqa: E402

KEY = "pool-of-radiance"
GUARDS = pathlib.Path(__file__).with_name("guards_pool.json")
NEW_PHLAN, HALL, SLUMS = 0, 11, 20
#: A party square as the run compares it: area, x, y, facing 0-3.
Place = tuple[int, int, int, int]
#: The Slums square west of New Phlan's gate, where the temple runs' parties stand: two right
#: turns and a step east cross into New Phlan at (0,4) facing east (`route_pool._TEMPLE_WALK`).
SLUMS_START: Place = (SLUMS, 15, 4, geo.WEST)
SLUMS_EXIT: tuple[tuple[str, Place], ...] = (
    ("NP6", (SLUMS, 15, 4, geo.NORTH)), ("NP6", (SLUMS, 15, 4, geo.EAST)),
    ("NP8", (NEW_PHLAN, 0, 4, geo.EAST)))
#: The Slums square a step east from which lands in New Phlan at `GATE_LANDING`
#: (`route_pool.POOL.edge_exits`), and that landing.
SLUMS_GATE = SLUMS_START[1:3]
GATE_LANDING: Place = SLUMS_EXIT[-1][1]
#: New Phlan's square whose script id 10 sends the party into the hall (ECL00 `NEWECL 11`).
HALL_DOOR = (6, 2)
#: The Slums' wall data on the game disks.
SLUMS_GEO = areas.area_in(SLUMS, areas.POOL_OF_RADIANCE).geos[0]
#: Inside the hall, on New Phlan's map: north to (6,0), then east into the magic-users' school
#: (7,0), square attribute 13, whose `DO YOU WANT TO TRAIN?` is answered YES.
HALL_SQUARES = ((6, 1), (6, 0), (7, 0))
SCHOOL = HALL_SQUARES[-1]
#: Turn keys by how far clockwise the party must turn; `NP8` steps.
TURNS = {1: "NP6", 2: "NP2", 3: "NP4"}
STEP = "NP8"
DELTAS = {geo.NORTH: (0, -1), geo.EAST: (1, 0), geo.SOUTH: (0, 1), geo.WEST: (-1, 0)}

#: Record bytes the game holds as pointers: the effect list, the item list and the next
#: member; a file written from memory carries whatever they held.
POINTER_FIELDS = ((0x080, 4), (0x0CA, 4), (0x106, 4))
#: The record's name field.
NAME_FIELD = 16
#: Bytes the writer's two cleaning passes delete (0x1627C the stop, 0x1634C the table at h11+0x4C).
NAME_DROPPED = b" .*,?/:;|"
#: The three bytes the zombie route depends on, each at its Amiga offset.
NAMED_BYTES = {"control": amiga_por.amiga_por_offset(0x084),
               "status": amiga_por.amiga_por_offset(0x10C),
               "creature_type": amiga_por.amiga_por_offset(0x09F)}
RECORD_SIZE = amiga_por.AMIGA_POR_RECORD_SIZE
#: A file REMOVE may rewrite besides the three it creates.
CHARLIST = "charlist.txt"

#: Guards for the hall's screens, cut from a boot's crops: the school's `YES NO` bar
#: with its question, and the party menu's eleven items with `CHOOSE A FUNCTION` (the start
#: menu has the same bar but other items; `DISK ACCESS, PLEASE WAIT...` replaces the bar).
HALL_GUARDS: dict[str, Any] = {
    "hall_question": {
        "box": [54, 418, 588, 432],
        "sha256": "f99f091a025bba2419e0a56a991d3cd06cd22d6ac603bd1c9727377fbad6993c",
        "and": [{"box": [72, 304, 660, 338],
                 "sha256": "694e99357f87e005524fba4f81af6c03ba83f394148394a5efb62e607a809b7d"}]},
    "hall_menu": {
        "box": [86, 226, 524, 386],
        "sha256": "f2f0299192ed9b4c489f4779f106069e5427d8406093bb5e8aa6fe018d3f636c",
        "and": [{"box": [54, 418, 340, 432],
                 "sha256": "b969d7f649a2e4eb584b41cf2bba91b57b2ac20394d00b1748e42140ca608fb3"}]},
}
HALL_STATES = ("hall_question", "hall_menu")
#: Screens whose guard, met while another is awaited, stops the run.
KNOWN = ("title", "wheel", "party_menu", "save_path", "load_picker", "world", "continue",
         "encounter", "combat_bar", "surprised", "camp", "sheet", "quit_prompt", *HALL_STATES)

TITLE_LIMIT = 600.0
MOVE_SETTLE = 5.0
#: Seconds left for a screen the script draws in stages before it is matched.
SCREEN_SETTLE = 5.0
#: Highlight readbacks, a second apart, after each `NP1` before the move counts as missed.
SELECT_READS = 8
SNAPSHOT = "poolremove-walk"


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RouteError(reason)


def write_json(path: pathlib.Path, value: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


# -- names and records ---------------------------------------------------------------------


def record_name(raw: bytes) -> bytes:
    """The name field up to its terminator."""
    return raw[:NAME_FIELD].split(b"\0")[0]


def cha_stem(name: bytes) -> bytes:
    """The name as the `.cha` writer cleans it: `.` and each of ` .*,?/:;|` deleted, a-z upper-cased.

    Any other byte, the `0xFF` an Amiga record holds for a space included, is kept.
    """
    return bytes(b - 0x20 if 0x61 <= b <= 0x7A else b for b in name if b not in NAME_DROPPED)


def cha_name(raw: bytes) -> str:
    """The file name the writer opens on `poolsave:` for this record."""
    return cha_stem(record_name(raw)).decode("latin1") + ".cha"


def cleaned_record(raw: bytes) -> bytes:
    """`raw` as the writer leaves it: the cleaned name copied over the field with its terminator.

    The copy stops at the terminator (the runtime's `strncpy` does not pad), so the old
    field's tail beyond it stays.
    """
    stem = cha_stem(record_name(raw)) + b"\0"
    return stem + raw[len(stem):]


def _pointer(offset: int) -> bool:
    return any(start <= offset < start + size for start, size in POINTER_FIELDS)


def record_differences(cha: bytes, reference: bytes) -> list[dict[str, Any]]:
    """Each byte outside `POINTER_FIELDS` where `cha` differs from `reference` cleaned as the writer cleans it."""
    expected = cleaned_record(reference)
    return [{"offset": f"0x{at:03X}", "cha": cha[at], "reference": expected[at]}
            for at in range(max(len(cha), len(expected)))
            if not _pointer(at) and (at >= len(cha) or at >= len(expected)
                                     or cha[at] != expected[at])]


def named_bytes(raw: bytes) -> dict[str, int]:
    return {name: raw[at] for name, at in NAMED_BYTES.items()}


def disk_files(disk: amiga_adf.AmigaDisk) -> dict[str, bytes]:
    """Every file on the disk by path, with the name folded as AmigaDOS compares it."""
    return {path.casefold(): disk.read_file(path) for path, entry in disk.walk()
            if not entry.is_dir}


def judge(before: amiga_adf.AmigaDisk, after: amiga_adf.AmigaDisk, live: bytes,
          slot_record: bytes) -> dict[str, Any]:
    """Whether REMOVE wrote the member's `.cha` from memory and changed nothing else on the disk.

    `live` is the member's record read from memory before `R`; `slot_record` is his record
    in the loaded slot. Passes when `NAME.cha` was added or rewritten, no file but it,
    `charlist.txt`, `NAME.itm` and `NAME.spc` appeared or changed, none went, the fetched
    disk verifies, the `.cha` is one record long
    and equals `live` outside the cleaned name and the pointer fields, and its control, status
    and creature type equal the slot record's. Every difference from the slot record is listed.
    """
    stem = cha_stem(record_name(live)).decode("latin1")
    created = {f"/{stem}{suffix}".casefold() for suffix in (".cha", ".itm", ".spc")}
    old, new = disk_files(before), disk_files(after)
    added = sorted(set(new) - set(old))
    changed = sorted(p for p in set(old) & set(new) if old[p] != new[p])
    removed = sorted(set(old) - set(new))
    others = ([p for p in added if p not in created]
              + [p for p in changed if p != f"/{CHARLIST}".casefold() and p not in created]
              + removed)
    verdict: dict[str, Any] = {
        "member": record_name(live).decode("latin1"), "file": f"{stem}.cha",
        "added": added, "changed": changed, "removed": removed, "other_changes": others,
        "verify": after.verify()}
    path = f"/{stem}.cha".casefold()
    cha = new.get(path)
    problems = [f"no other file may change, but {', '.join(others)} did"] if others else []
    problems += [f"the fetched disk fails verification: {problem}"
                 for problem in verdict["verify"]]
    if cha is None:
        problems.append(f"the disk has no {stem}.cha")
        verdict.update(problems=problems, success=False)
        return verdict
    verdict["cha_sha256"] = hashlib.sha256(cha).hexdigest()
    if path not in added and path not in changed:
        problems.append(f"REMOVE did not write {stem}.cha: the disk held it unchanged before")
    for suffix in (".itm", ".spc"):
        found = new.get(f"/{stem}{suffix}".casefold())
        verdict[suffix[1:]] = None if found is None else {
            "size": len(found), "sha256": hashlib.sha256(found).hexdigest()}
    if len(cha) != RECORD_SIZE:
        problems.append(f"{stem}.cha is {len(cha)} bytes, not {RECORD_SIZE}")
    memory = record_differences(cha, live)
    saved = record_differences(cha, slot_record)
    verdict["memory_differences"] = memory
    verdict["slot_differences"] = saved
    verdict["pointers"] = {f"0x{at:03X}": {"cha": cha[at:at + size].hex(),
                                           "memory": live[at:at + size].hex(),
                                           "slot": slot_record[at:at + size].hex()}
                           for at, size in POINTER_FIELDS}
    verdict["named"] = {"cha": named_bytes(cha), "memory": named_bytes(live),
                        "slot": named_bytes(slot_record)}
    if memory:
        problems.append(f"{stem}.cha differs from the record in memory at "
                        + ", ".join(d["offset"] for d in memory))
    if named_bytes(cha) != named_bytes(slot_record):
        problems.append(f"{stem}.cha's control, status or creature type differs from the slot's")
    if record_name(live) != record_name(slot_record):
        problems.append("the record in memory and the slot record carry different names")
    verdict.update(problems=problems, success=not problems)
    return verdict


# -- the walk ------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class WalkStep:
    """One key and the place it leaves the party on; `None` for the step the school's question answers."""

    key: str
    expect: Place | None


def _open(walls: Any, x: int, y: int, direction: int) -> bool:
    return (walls.wall(x, y, direction) == 0
            or walls.barrier(x, y, direction) == geo.PASSABLE)


def _path(walls: Any, start: tuple[int, int], goal: tuple[int, int],
          where: str = "New Phlan", goal_name: str = "the hall's door") -> list[tuple[int, int]]:
    """The shortest path on `walls` from `start` to `goal` that enters no square with a script id but `goal`."""
    previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    queue = collections.deque([start])
    while queue:
        here = queue.popleft()
        if here == goal:
            break
        for direction, (dx, dy) in DELTAS.items():
            there = (here[0] + dx, here[1] + dy)
            if (there in previous or not (0 <= there[0] < 16 and 0 <= there[1] < 16)
                    or not _open(walls, *here, direction)
                    or (there != goal and walls.script_id(*there) != 0)):
                continue
            previous[there] = here
            queue.append(there)
    require(goal in previous, f"{where} has no path from {start} to {goal_name} {goal} "
                              "that keeps off the squares with scripts")
    path, square = [], goal
    while square is not None:
        path.append(square)
        square = previous[square]
    return path[::-1]


def _heading(here: tuple[int, int], there: tuple[int, int]) -> int:
    delta = (there[0] - here[0], there[1] - here[1])
    return next(direction for direction, step in DELTAS.items() if step == delta)


def _steps(place: Place, squares: Sequence[tuple[int, int]], area_of: Callable[[tuple[int, int]], int],
           walls: Any, last_answers: bool) -> tuple[list[WalkStep], Place]:
    steps: list[WalkStep] = []
    area, x, y, facing = place
    for n, there in enumerate(squares):
        heading = _heading((x, y), there)
        require(_open(walls, x, y, heading), f"({x},{y}) is closed towards {there}")
        turn = (heading - facing) % 4
        if turn:
            steps.append(WalkStep(TURNS[turn], (area, x, y, heading)))
            facing = heading
        area, (x, y) = area_of(there), there
        final = last_answers and n == len(squares) - 1
        steps.append(WalkStep(STEP, None if final else (area, x, y, facing)))
    return steps, (area, x, y, facing)


def _gate_exit(place: Place, slums: Any) -> list[WalkStep]:
    """From `SLUMS_GATE`, the turns to face east and the step into New Phlan.

    A party facing west turns right twice, the keys the temple runs measured (`SLUMS_EXIT`).
    """
    require(_open(slums, *SLUMS_GATE, geo.EAST), f"the Slums gate {SLUMS_GATE} is closed to the east")
    turn = (geo.EAST - place[3]) % 4
    if turn == 2:
        return [WalkStep(key, expect) for key, expect in SLUMS_EXIT]
    steps = [WalkStep(TURNS[turn], (SLUMS, *SLUMS_GATE, geo.EAST))] if turn else []
    return [*steps, WalkStep(STEP, GATE_LANDING)]


def plan_walk(place: Place, walls: Any, slums: Any = None) -> list[WalkStep]:
    """The keys from `place` to the school's question, each with the place it must leave the party on.

    `walls` is New Phlan's map (`GEO00`), which the hall shares; `slums` is the Slums' map
    (`GEO14`), needed for a start there. A start in any other area is blocked.
    """
    steps: list[WalkStep] = []
    if place[0] == SLUMS:
        require(slums is not None, "a walk from the Slums needs the Slums' map")
        route = _path(slums, (place[1], place[2]), SLUMS_GATE, "The Slums", "the gate")[1:]
        steps, place = _steps(place, route, lambda s: SLUMS, slums, last_answers=False)
        steps += _gate_exit(place, slums)
        place = GATE_LANDING
    require(place[0] == NEW_PHLAN, f"the walk starts in New Phlan or the Slums, "
                                   f"not at {place}")
    route = _path(walls, (place[1], place[2]), HALL_DOOR)[1:]
    outside, place = _steps(place, route, lambda s: HALL if s == HALL_DOOR else NEW_PHLAN,
                            walls, last_answers=False)
    inside, _ = _steps(place, HALL_SQUARES, lambda s: HALL, walls, last_answers=True)
    return steps + outside + inside


def manifest_place(manifest: dict) -> Place:
    state = manifest.get("state_a")
    require(isinstance(state, dict) and all(k in state for k in ("area", "x", "y", "facing")),
            "the manifest records no loaded place (state_a with area, x, y and facing)")
    return (state["area"], state["x"], state["y"], state["facing"])


# -- the running machine -------------------------------------------------------------------


class Live:
    """The running game's party, its highlight and its square, through WinUAE's pipe."""

    def __init__(self, holder: str):
        from automap import amiga, amigaparty, amigatrip  # noqa: PLC0415

        self.amiga, self.party, self.trip = amiga, amigaparty, amigatrip
        self.layout = amiga.MACHINES[KEY]
        self.target = amiga.AmigaTarget(amiga.WinuaePipe(holder=holder), self.layout)
        self.row = amigaparty.ROWS[KEY]
        self.located = False

    def _ready(self) -> None:
        if not self.located:
            self.target.locate()
            self.located = True

    def place(self) -> Place | None:
        self._ready()
        area = self.trip.area_id(self.target, KEY)
        square = self.trip.square(self.target, KEY)
        return None if area is None or square is None else (area, *square)

    def members(self) -> list[tuple[str, int, bytes]]:
        """`(name, address, record)` of each party member in list order."""
        self._ready()
        return [(m.name, m.address, m.raw[:RECORD_SIZE])
                for m in self.party.walk(self.target, self.row, self.target.data_base)
                if m.in_party]

    def current(self) -> int:
        self._ready()
        return int.from_bytes(self.target.read(self.target.data_base + self.row.current, 4), "big")

    def select(self, want: str, press: Callable[[str], object]) -> dict:
        from tools.amiga import amigatarget  # noqa: PLC0415

        self._ready()
        return amigatarget.select(self.target, self.layout, want, press, reads=SELECT_READS)


def _folded(name: str) -> str:
    return route_pool._pool_name(name).casefold()


class Screens:
    """Presses keys only on a screen its guard recognises."""

    def __init__(self, guest: Any, holder: str, out: pathlib.Path, guards: PixelGuards,
                 deadline: float):
        self.guest, self.holder, self.out = guest, holder, out
        self.guards, self.deadline = guards, deadline
        self.events: list[dict] = []
        self.count = 0
        self.pressed_on: str | None = None
        out.mkdir(parents=True)

    def left(self, cap: float) -> float:
        left = min(cap, self.deadline - time.monotonic())
        require(left > 0, "the run's deadline expired")
        return left

    def _paths(self, state: str) -> tuple[pathlib.Path, pathlib.Path]:
        self.count += 1
        return (self.out / f"{self.count:03d}-{state}-raw.png", self.out / f"{self.count:03d}-{state}.png")

    def see(self, state: str, limit: float, answer: tuple[str, str] | None = None) -> pathlib.Path:
        """Poll until `state`'s guard matches; `answer` is a screen met on the way and its key, pressed once."""
        require(state in self.guards, f"no guard for {state}")
        end = time.monotonic() + self.left(limit)
        raw = None
        while time.monotonic() < end:
            raw, crop = self._paths(state)
            if self.guest.grab(state, raw, crop, self.left(30)):
                if self.guards(state, crop):
                    self.events.append({"screen": state, "crop": str(crop)})
                    self.pressed_on = None
                    return crop
                if answer is not None and self.guards(answer[0], crop):
                    self.guest.press(self.holder, answer[1], timeout=self.left(30))
                    self.events.append({"screen": answer[0], "crop": str(crop), "key": answer[1]})
                    self.pressed_on, answer = answer[0], None
                    continue
                for other in KNOWN:
                    if (other not in (state, self.pressed_on) and other in self.guards
                            and self.guards(other, crop)):
                        raise RouteError(f"expected {state}, saw {other}; shot {raw}")
            time.sleep(min(1.0, max(0.0, end - time.monotonic())))
        raise RouteError(f"{state} did not match within {limit:.0f}s; last shot {raw}")

    def press(self, state: str, key: str) -> None:
        self.guest.press(self.holder, key, timeout=self.left(30))
        self.pressed_on = state
        self.events.append({"from": state, "key": key})

    def frames(self, name: str, seconds: float, done: Callable[[], bool]) -> list[str]:
        """Every distinct frame for up to `seconds`, ending early once `done()` holds and two frames agree."""
        kept: list[str] = []
        seen: set[str] = set()
        previous = None
        end = time.monotonic() + self.left(seconds)
        while time.monotonic() < end:
            raw, crop = self._paths(name)
            if not self.guest.grab(name, raw, crop, self.left(30)):
                time.sleep(1.0)
                continue
            digest = hashlib.sha256(crop.read_bytes()).hexdigest()
            if digest not in seen:
                seen.add(digest)
                kept.append(str(crop))
            if digest == previous and done():
                break
            previous = digest
            time.sleep(1.0)
        self.events.append({"frames": name, "kept": kept})
        return kept


# -- the run -------------------------------------------------------------------------------


def preflight(manifest_path: pathlib.Path, member: str,
              load_geo: Callable[[str], Any]) -> tuple[dict, list[WalkStep], int]:
    """The manifest, the walk and the member's party line, all checked before any lane is claimed."""
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get("title") == "pool", "the manifest is not a Pool of Radiance run")
    for key in ("disk1", "disk2", "save"):
        entry = manifest.get("disks", {}).get(key)
        require(isinstance(entry, dict) and sha256(pathlib.Path(entry["path"])) == entry["sha256"],
                f"the prepared {key} is missing or its hash differs")
    names = [_folded(n) for n in manifest.get("names_a", [])]
    wanted = _folded(member)
    require(names.count(wanted) == 1, f"the loaded party {manifest.get('names_a')} does not hold "
                                      f"exactly one {member}")
    require(all(state in HALL_GUARDS for state in HALL_STATES),
            "the hall's screens have no guards")
    steps = plan_walk(manifest_place(manifest), load_geo("GEO00"), load_geo(SLUMS_GEO))
    return manifest, steps, names.index(wanted) + 1


def guard_file(out: pathlib.Path, extra: pathlib.Path | None) -> pathlib.Path:
    """`guards_pool.json`'s rules and the hall's, with `extra`'s on top, as the file `PixelGuards` reads."""
    rules = {**json.loads(GUARDS.read_text())["guards"], **HALL_GUARDS}
    if extra is not None:
        rules.update(json.loads(extra.read_text()))
    path = out / "guards.json"
    write_json(path, rules)
    return path


def _wait_place(live: Live, expect: Place, limit: float) -> Place | None:
    end = time.monotonic() + limit
    place = None
    while time.monotonic() < end:
        place = live.place()
        if place == expect:
            return place
        time.sleep(1.0)
    return place


def walk(screens: Screens, live: Live, switch: Any, steps: Sequence[WalkStep],
         start: Place, log: list) -> None:
    """Press each key through the encounter switch and check the square it leaves the party on."""
    area = start[0]
    for step in steps:
        pressed = time.monotonic()
        response = switch.keys([step.key])
        require(response.get("pressed") == [step.key] and "error" not in response
                and "stopped" not in response, f"{step.key} did not go in: {response}")
        screens.pressed_on = "world"
        screens.events.append({"from": "world", "key": step.key})
        if step.expect is None:
            log.append({"key": step.key, "expect": "the school's question"})
            return
        # A step into another area loads its script and map first.
        place = _wait_place(live, step.expect, screens.left(60.0 if step.expect[0] != area else 30.0))
        log.append({"key": step.key, "expect": list(step.expect),
                    "place": None if place is None else list(place)})
        require(place == step.expect, f"{step.key} left the party at {place}, not {step.expect}")
        area = place[0]
        screens.see("world", 60)
        time.sleep(max(0.0, MOVE_SETTLE - (time.monotonic() - pressed)))


def load_slot(screens: Screens, manifest: dict) -> None:
    """From the start of the emulator to the world screen of the manifest's loaded slot, each key on a guarded screen."""
    waits = route_pool.POOL.min_waits
    screens.see("title", TITLE_LIMIT, answer=("wheel", "RET"))
    for state, key, nxt in (("title", "RET", "party_menu"), ("party_menu", "L", "save_path"),
                            ("save_path", "RET", "load_picker"),
                            ("load_picker", manifest["loaded_letter"], "world")):
        screens.press(state, key)
        time.sleep(waits.get(nxt, 0.0))
        screens.see(nxt, 120)


def run(args: argparse.Namespace, *, guest: Any = None, live_factory: Callable[[str], Live] = Live,
        switch_factory: Callable[..., Any] | None = None,
        load_geo: Callable[[str], Any] = route_pool._disk_geo) -> dict:
    """Load, walk to the hall, remove the member, halt, fetch the save disk and judge it."""
    manifest, steps, line = preflight(args.manifest, args.member, load_geo)
    require(not args.out.exists(), f"the output folder {args.out} already exists")
    require(0 <= args.wait_lane <= 3600, "the lane wait is longer than an hour")
    args.out.mkdir(parents=True)
    command = [str(pathlib.Path(__file__)), "run", "--manifest", str(args.manifest), "--member",
               args.member, "--holder", args.holder, "--out", str(args.out)]
    receipt: dict[str, Any] = {
        "started_utc": datetime.now(timezone.utc).isoformat(), "command": command,
        "manifest": str(args.manifest.resolve()), "holder": args.holder,
        "member": args.member, "line": line,
        "plan": [[s.key, None if s.expect is None else list(s.expect)] for s in steps],
        "walk": [], "cleanup": [], "success": False}
    guest = guest or WinGuest()
    local = args.out / "prepare.json"
    booted = snapshot_taken = False
    screens: Screens | None = None
    switch = None
    state = noencounters.WinuaeState(noencounters.winuae_state_path(args.holder))
    try:
        disks = {}
        for key, entry in manifest["disks"].items():
            path = args.out / f"{key}.adf"
            shutil.copyfile(entry["path"], path)
            require(sha256(path) == entry["sha256"], f"the copied {key} differs from the prepared one")
            disks[key] = {**entry, "path": str(path)}
        prepared = {**manifest, "disks": disks}
        write_json(local, prepared)
        guards = PixelGuards(guard_file(args.out, args.guards))
        proof = args.out / "mute.json"
        output = guest._run("ssh", acceptance.MUTE_READBACK, timeout=60)
        write_json(proof, json.loads(output[output.index("{"):]))
        require(guest.silence(proof), "the Windows playback endpoint did not read back muted")
        receipt["mute"] = json.loads(proof.read_text())
        receipt["boot"] = acceptance.boot_lane(
            local, prepared, route_pool.POOL, guest=guest, holder=args.holder, audio_proof=proof,
            wait_lane=args.wait_lane, timeout=300.0, command=command)
        booted = True
        # The budget runs from the start of the emulator, not from the wait for a lane.
        deadline = time.monotonic() + args.budget
        screens = Screens(guest, args.holder, args.out / "screens", guards, deadline)
        load_slot(screens, manifest)
        live = live_factory(args.holder)
        start = live.place()
        receipt["loaded"] = {"place": start, "names": [n for n, _a, _r in live.members()]}
        require(start == manifest_place(manifest), f"the party stands at {start}, not at "
                                                    f"{manifest_place(manifest)}")
        require([_folded(n) for n, _a, _r in live.members()]
                == [_folded(n) for n in manifest["names_a"]], "the loaded party is not the slot's")
        guest.snapshot(SNAPSHOT, args.holder)
        snapshot_taken = True
        factory = switch_factory or (lambda target: noencounters.WinuaeEncounters(
            KEY, target, state=state, lane_check=lambda: guest.lane(args.holder, timeout=30),
            press=lambda key: guest.press(args.holder, key, timeout=30)))
        for attempt in range(args.walk_retry + 1):
            switch = factory(live.target)
            on = switch.on()
            require("error" not in on and "stopped" not in on, f"the encounter switch did not go on: {on}")
            log: list = []
            receipt["walk"].append(log)
            try:
                walk(screens, live, switch, steps, start, log)
                break
            except RouteError as exc:
                log.append({"error": str(exc)})
                if attempt == args.walk_retry:
                    raise
                off = switch.off()
                switch = None
                require("error" not in off, f"the encounter switch did not go off: {off}")
                guest.restore(SNAPSHOT, args.holder)
                screens.see("world", 120)
                require(_wait_place(live, start, 30) == start, "the restore did not put the party back")
        off = switch.off()
        switch = None
        require("error" not in off and not state.load()["on"] and not state.load()["rows"],
                f"the encounter switch did not go off: {off}")
        receipt["switch_off"] = off
        time.sleep(SCREEN_SETTLE)
        screens.see("hall_question", 90)
        screens.press("hall_question", "Y")
        time.sleep(SCREEN_SETTLE)
        menu = screens.see("hall_menu", 90)
        require(live.current() != 0, "the menu opened with no member highlighted")
        party = live.members()
        lines = [n for n, (name, _a, _r) in enumerate(party, 1)
                 if _folded(name) == _folded(args.member)]
        require(len(lines) == 1, f"the party in memory does not hold exactly one {args.member}")
        chosen = live.select(str(lines[0]), lambda key: guest.press(args.holder, key, timeout=30))
        receipt["select"] = chosen
        require("error" not in chosen, f"the highlight did not reach {args.member}: {chosen}")
        screens.see("hall_menu", 60)
        address = int(chosen["address"], 16)
        rows = [(name, raw) for name, a, raw in live.members() if a == address]
        require(len(rows) == 1 and live.current() == address
                and _folded(rows[0][0]) == _folded(args.member),
                f"the highlighted record is not {args.member}")
        record = rows[0][1]
        (args.out / "member-memory.bin").write_bytes(record)
        receipt["memory_record"] = {"address": hex(address), "line": chosen.get("line"),
                                    "sha256": hashlib.sha256(record).hexdigest(),
                                    "menu": str(menu)}
        screens.press("hall_menu", "R")

        def gone() -> bool:
            return all(a != address for _n, a, _r in live.members())

        receipt["after_remove_frames"] = screens.frames("remove", 120, gone)
        require(gone(), f"{args.member} is still in the party after REMOVE")
        receipt["after_remove"] = [n for n, _a, _r in live.members()]
        screens.see("hall_menu", 60)
        time.sleep(10.0)
        # Matched again just before the key: `B` is BEGIN ADVENTURING only on this menu.
        screens.see("hall_menu", 30)
        screens.press("hall_menu", "B")
        try:
            screens.see("world", 90)
            receipt["left_menu"] = {"place": live.place()}
        except RouteError as exc:
            receipt["left_menu"] = {"error": str(exc)}
        time.sleep(15.0)
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if screens is not None:
            receipt["screens"] = screens.events
        if booted:
            try:
                if switch is not None or state.load()["on"] or state.load()["rows"]:
                    reply = (switch or noencounters.WinuaeEncounters(
                        KEY, live_factory(args.holder).target, state=state,
                        lane_check=lambda: guest.lane(args.holder, timeout=30))).off()
                    require("error" not in reply, f"encounter cleanup: {reply}")
            except Exception as exc:  # noqa: BLE001 - every cleanup failure is named
                receipt["cleanup"].append({"encounters_error": str(exc)})
            if snapshot_taken:
                try:
                    guest.discard(SNAPSHOT, args.holder)
                except Exception as exc:  # noqa: BLE001
                    receipt["cleanup"].append({"discard_error": str(exc)})
            try:
                receipt["halt"] = acceptance.halt_lane(guest, args.holder, manifest_path=local,
                                                       command=command)
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append({"halt_error": str(exc)})
        write_json(args.out / "receipt.json", receipt)
    if "halt" in receipt and (args.out / "member-memory.bin").exists():
        try:
            receipt["verdict"] = judge_out(args.out)
        except (RouteError, OSError, ValueError, KeyError, IndexError) as exc:
            receipt["verdict"] = {"success": False, "problems": [f"{type(exc).__name__}: {exc}"]}
    errors = [c for c in receipt["cleanup"] if any(k.endswith("error") for k in c)]
    receipt["success"] = ("error" not in receipt and not errors
                          and bool(receipt.get("verdict", {}).get("success")))
    write_json(args.out / "receipt.json", receipt)
    if not receipt["success"]:
        raise RouteError(receipt.get("error") or "; ".join(
            receipt.get("verdict", {}).get("problems", [])) or f"cleanup failed: {errors}")
    return receipt


def fetched_save(out: pathlib.Path) -> pathlib.Path:
    found = sorted(out.glob("halt-*/fetched-save.adf"))
    require(len(found) == 1, f"{out} holds {len(found)} fetched save disks, not one")
    return found[0]


def judge_out(out: pathlib.Path) -> dict:
    """`judge` over a run folder: its prepared save disk, the fetched one and the record read before `R`."""
    receipt = json.loads((out / "receipt.json").read_text())
    manifest = json.loads((out / "prepare.json").read_text())
    before = amiga_adf.AmigaDisk.open(pathlib.Path(manifest["disks"]["save"]["path"]))
    after = amiga_adf.AmigaDisk.open(fetched_save(out))
    live = (out / "member-memory.bin").read_bytes()
    characters = amiga_savegame.read_por_characters(before, manifest["loaded_letter"], drawer="")
    slot = characters[receipt["line"] - 1].raw
    verdict = judge(before, after, live, slot)
    verdict["fetched"] = str(fetched_save(out))
    write_json(out / "verdict.json", verdict)
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="print the walk the run would take; boots nothing")
    plan.add_argument("--manifest", type=pathlib.Path, required=True)
    go = sub.add_parser("run", help="boot, walk to the hall, remove the member, halt and judge")
    go.add_argument("--manifest", type=pathlib.Path, required=True)
    go.add_argument("--member", required=True, help="the member's name, spaces optional")
    go.add_argument("--holder", required=True)
    go.add_argument("--out", type=pathlib.Path, required=True)
    go.add_argument("--guards", type=pathlib.Path, default=None,
                    help="extra guard rules, merged over the built-in ones")
    go.add_argument("--wait-lane", type=float, default=0)
    go.add_argument("--walk-retry", type=int, default=1)
    go.add_argument("--budget", type=float, default=2400,
                    help="seconds from the emulator's start to the halt")
    again = sub.add_parser("judge", help="judge a finished run folder again")
    again.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            manifest = json.loads(args.manifest.read_text())
            steps = plan_walk(manifest_place(manifest), route_pool._disk_geo("GEO00"),
                              route_pool._disk_geo(SLUMS_GEO))
            print(json.dumps([[s.key, None if s.expect is None else list(s.expect)]
                              for s in steps]))
        elif args.command == "judge":
            print(json.dumps(judge_out(args.out), indent=2, default=str))
        else:
            with terminating():
                receipt = run(args)
            print(json.dumps(receipt["verdict"], indent=2, default=str))
    except (RouteError, OSError, ValueError, KeyError) as exc:
        print(f"Poolremove: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
