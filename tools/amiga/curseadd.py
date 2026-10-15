#!/usr/bin/env python3
"""Add Pool of Radiance characters to an Amiga Curse party through ADD CHARACTER and save it.

`stage` copies each `NAME.cha` and `NAME.spc` off a Pool save disk's root, where REMOVE
writes them (or a named drawer), into
the `SAVE` drawer of a copy of a prepared Curse disk A, as Curse's Transfer does
(no `.itm`), and writes a manifest `acceptance.py boot` and `run` take. `run` boots
that manifest in one muted WinUAE lane and, pressing only on guarded screens, loads
a slot, adds every staged character through ADD CHARACTER > Pool, views the party,
saves once with SAVE CURRENT GAME, halts, fetches the disk and reads the save back.
`read` reads a fetched disk's slot against the staged records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from goldbox import amiga_adf, amiga_savegame  # noqa: E402
from goldbox.amiga_por import AMIGA_POR_RECORD_SIZE  # noqa: E402
from tools.amiga import acceptance, route_curse  # noqa: E402
from tools.amiga.route import effect_fields  # noqa: E402
from tools.amiga.screens import PixelGuards  # noqa: E402
from tools.amiga.staging import sha256  # noqa: E402
from tools.amiga.winuaesession import RouteError, WinGuest, terminating  # noqa: E402

#: Where Amiga Pool's REMOVE writes `name.cha`, `.itm` and `.spc`: the save disk's root.
SOURCE_ROOT = "/"
#: Curse's own drawer on disk A, the one its load, save and ADD pickers read.
CURSE_DRAWER = "SAVE"
#: What Transfer copies and the ADD picker lists; `.sav` is listed too (picker 0x24D6E).
CHARACTER_SUFFIXES = (".cha", ".spc")
LISTED = re.compile(r".*\.(cha|sav)", re.IGNORECASE)
#: The characters Amiga Pool's `.cha` writer removes from a name (0x1627C, 0x1634C).
_CLEANED = set(" .*,?/:;|")
#: Pool record offset -> Curse record offset, as the import mapper 0x251FE copies them.
MAPPED = {"control": (0x85, 0xF7), "status": (0x10E, 0x19A), "type": (0xA1, 0x11B),
          "hit_points": (0x11D, 0x1A9)}
#: The most a party may hold for ADD to seat a player character (0x15590) or an NPC (0x155AC).
PLAYER_SEATS, PARTY_SEATS = 6, 8
SLOT = re.compile(r"[A-J]")
GUARDS = pathlib.Path(__file__).with_name("guards_curse.json")


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RouteError(reason)


def write_json(path: pathlib.Path, value: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def cha_stem(name: str) -> str:
    """The file stem Amiga Pool's REMOVE writes for a record named `name`.

    A player character's space is stored as 0xFF, which the writer keeps.
    """
    return "".join(c.upper() if "a" <= c <= "z" else c for c in name if c not in _CLEANED)


def name_key(name: str) -> str:
    """One spelling for a Pool record name, its file stem, Curse's copy and the live list.

    0xFF is read as a space, then the writer's cleaning removes it with the rest.
    """
    return cha_stem(name.replace("\xff", " "))


def _record_name(record: bytes) -> str:
    return record[:0x10].split(b"\0", 1)[0].decode("latin-1")


def _is_root(drawer: str) -> bool:
    return not drawer.strip("/")


def _drawer_files(disk: amiga_adf.AmigaDisk, drawer: str) -> list[str]:
    header = None if _is_root(drawer) else disk.lookup(drawer).block
    return [e.name for e in disk.entries(header) if not e.is_dir]


def _in_drawer(drawer: str, name: str) -> str:
    return f"/{name}" if _is_root(drawer) else f"{drawer.strip('/')}/{name}"


def copy_characters(source: amiga_adf.AmigaDisk, target: amiga_adf.AmigaDisk,
                    names: list[str], *, source_drawer: str = SOURCE_ROOT) -> list[dict]:
    """Copy each name's `.cha` and `.spc` into the target's `SAVE` drawer, unchanged.

    The source files are found where REMOVE writes them, the disk root unless `source_drawer`
    names a drawer, by `name_key`, so case and REMOVE's cleaning do not matter; each keeps its
    own file name on the Curse disk. The `.itm` stays behind, as Curse's Transfer leaves it.

    The drawer must list no `.cha` or `.sav` before the copy, so the ADD picker then lists
    exactly the staged characters. A `.cha` that is not a Pool record, or a name already on
    the target, stops the copy; a missing `.spc` is recorded, since a character with no
    effects has none. Nothing is written to `source`.
    """
    require(bool(names), "no character named")
    keys = [name_key(name) for name in names]
    require(len(set(keys)) == len(keys), f"two names give one character: {keys}")
    present = _drawer_files(target, CURSE_DRAWER)
    listed = [name for name in present if LISTED.fullmatch(name)]
    require(not listed, f"the Curse drawer already lists {listed}")
    files = _drawer_files(source, source_drawer)
    offered = [n[:-4] for n in files if n.lower().endswith(".cha")]
    copies = []
    for name, key in zip(names, keys):
        found = [stem for stem in offered if name_key(stem) == key]
        require(len(found) == 1, f"{len(found)} .cha files on {source.volume_name} "
                                 f"are {name!r}: {found}")
        stem = found[0]
        row: dict[str, Any] = {"name": name, "stem": stem, "key": key}
        for suffix in CHARACTER_SUFFIXES:
            named = [n for n in files if n.lower() == f"{stem}{suffix}".lower()]
            if not named:
                require(suffix != ".cha", f"{stem}{suffix} is not on {source.volume_name}")
                row[suffix[1:]] = None
                continue
            path = _in_drawer(source_drawer, named[0])
            data = source.read_file(path)
            if suffix == ".cha":
                require(len(data) == AMIGA_POR_RECORD_SIZE,
                        f"{path} is {len(data)} bytes, not a Pool record")
                require(name_key(_record_name(data)) == key,
                        f"{path} holds {_record_name(data)!r}, not {name!r}")
            destination = f"{CURSE_DRAWER}/{named[0]}"
            require(not any(n.lower() == named[0].lower() for n in present),
                    f"{destination} is already on the Curse disk")
            target.write_file(destination, data)
            back = target.read_file(destination)
            require(back == data, f"{destination} reads back changed")
            row[suffix[1:]] = {"source": path, "target": destination, "bytes": len(data),
                               "sha256": hashlib.sha256(data).hexdigest(), "equal": True}
        copies.append(row)
    problems = target.verify()
    require(not problems, f"the Curse disk fails verification after the copy: {problems}")
    return copies


def slot_letters(disk: amiga_adf.AmigaDisk) -> list[str]:
    return route_curse.CURSE.slot_letters(disk)


def _slot_members(disk: amiga_adf.AmigaDisk, letter: str) -> list:
    return list(amiga_savegame.read_slot(disk, letter, route_curse.CURSE_KEY).characters)


def stage(manifest_path: pathlib.Path, source_disk: pathlib.Path, names: list[str],
          out: pathlib.Path, *, load: str = "A", save: str = "D",
          source_drawer: str = SOURCE_ROOT) -> pathlib.Path:
    """Copy a Curse prepare run's disks into `out`, stage the characters, write `out/prepare.json`."""
    require(not out.exists(), f"{out} already exists")
    require(bool(SLOT.fullmatch(load)) and bool(SLOT.fullmatch(save)) and load != save,
            "the load and save letters must be two letters A-J")
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get("title") == "curse", "the manifest is not a Curse prepare")
    for key in ("save", "diskb"):
        entry = manifest["disks"][key]
        require(sha256(pathlib.Path(entry["path"])) == entry["sha256"],
                f"the prepared {key} disk hash differs")
    for entry in manifest["registered"].values():
        require(sha256(pathlib.Path(entry["path"])) == entry["sha256"],
                "a registered disk hash differs")
    source_hash = sha256(source_disk)
    source = amiga_adf.AmigaDisk.open(source_disk)
    working = amiga_adf.AmigaDisk(bytearray(pathlib.Path(manifest["disks"]["save"]["path"])
                                            .read_bytes()))
    letters = slot_letters(working)
    require(load in letters, f"slot {load} is not on the Curse disk: {letters}")
    require(save not in letters, f"slot {save} is already on the Curse disk")
    members = _slot_members(working, load)
    players = sum(1 for m in members if m.raw[0xF7] < 0x80)
    copies = copy_characters(source, working, names, source_drawer=source_drawer)
    records = [working.read_file(row["cha"]["target"]) for row in copies]
    adding_players = sum(1 for r in records if r[0x85] < 0x80)
    require(players < PLAYER_SEATS and players + adding_players <= PLAYER_SEATS,
            f"slot {load} has {players} player members; ADD seats at most {PLAYER_SEATS}")
    require(len(members) + len(names) <= PARTY_SEATS,
            f"slot {load} has {len(members)} members; too many to seat {len(names)} more")
    # Made only once the copy and the seat checks pass, so a stopped stage can be rerun.
    out.mkdir(parents=True)
    disks = {}
    for key in ("save", "diskb"):
        local = out / f"{key}.adf"
        if key == "save":
            working.save(local)
        else:
            shutil.copyfile(manifest["disks"][key]["path"], local)
        disks[key] = {"path": str(local), "sha256": sha256(local)}
    require(sha256(source_disk) == source_hash, "the source disk changed")
    staged = {**manifest, "disks": disks,
              "prepared_from": {"path": str(manifest_path.resolve()),
                                "save_sha256": manifest["disks"]["save"]["sha256"]},
              "add": {"source": {"path": str(source_disk.resolve()), "sha256": source_hash,
                                 "drawer": source_drawer, "volume": source.volume_name},
                      "copies": copies, "load": load, "save": save,
                      "load_names": [m.name for m in members],
                      "load_players": players}}
    path = out / "prepare.json"
    write_json(path, staged)
    return path


def read_back(disk_path: pathlib.Path, manifest: dict) -> dict:
    """The saved slot's party, and each staged character's mapped bytes against its `.cha`."""
    add = manifest["add"]
    disk = amiga_adf.AmigaDisk.open(disk_path)
    letter = add["save"]
    members = _slot_members(disk, letter)
    staged = amiga_adf.AmigaDisk.open(manifest["disks"]["save"]["path"])
    found: dict[str, Any] = {"letter": letter, "names": [m.name for m in members],
                             "verify": disk.verify(), "members": {}}
    for row in add["copies"]:
        cha = staged.read_file(row["cha"]["target"])
        spc = staged.read_file(row["spc"]["target"]) if row.get("spc") else b""
        match = [m for m in members if name_key(m.name) == row["key"]]
        entry: dict[str, Any] = {"seated": len(match)}
        if len(match) == 1:
            curse = match[0].raw
            entry["fields"] = {field: {"cha": cha[pool], "curse": curse[later],
                                       "equal": cha[pool] == curse[later]}
                               for field, (pool, later) in MAPPED.items()}
            entry["effects"] = [list(effect_fields(node)) for node in match[0].effects]
            entry["spc"] = [list(effect_fields(spc[i:i + 10]))
                            for i in range(0, len(spc) - 9, 10)]
        found["members"][row["stem"]] = entry
    saved = [name_key(name) for name in found["names"]]
    found["kept"] = [name for name in add["load_names"] if name_key(name) in saved]
    return found


def verdict(found: dict, manifest: dict) -> list[str]:
    """Problems with a read-back: an empty list means every staged character joined unchanged."""
    problems = []
    if found["verify"]:
        problems.append(f"the fetched disk fails verification: {found['verify']}")
    if found["kept"] != manifest["add"]["load_names"]:
        problems.append(f"the loaded party is not kept: {found['names']}")
    stems = [row["stem"] for row in manifest["add"].get("copies", [])]
    if not stems:
        problems.append("the manifest stages no character")
    for stem in stems:
        if stem not in found["members"]:
            problems.append(f"{stem} was not read back")
    for stem, entry in found["members"].items():
        if entry["seated"] != 1:
            problems.append(f"{stem} is in the saved party {entry['seated']} times")
            continue
        for field in ("control", "status", "type"):
            if not entry["fields"][field]["equal"]:
                problems.append(f"{stem} {field} {entry['fields'][field]}")
    return problems


#: The screens ADD CHARACTER draws, cut from the first capture boot's crops
#: (`~/.cache/wish/acceptance/WISH-303/s3-add/cap1/screens`): the source menu before a key,
#: the picker's prompt bar (the list above it changes, the bar does not) and the save message.
ADD_GUARDS = {
    "add_from": {"box": [72, 404, 610, 426],
                 "sha256": "78dc9f71ac526462e378c8b484c034f61dfc7e831a4543fa4122a178a6ac621f"},
    "add_picker": {"box": [72, 404, 466, 426],
                   "sha256": "569098385cb05b72218d1930351ee76f69f7c7329a4838b44250bbf03e28dbab"},
    "saving": {"box": [72, 404, 398, 426],
               "sha256": "0d65a3f6a1e58d6b53b00ed5de55fb09d9cd6488c310e9709d0a4329df9341bb"},
}
#: The states a run tells apart; any of them showing where another is expected stops it.
KNOWN = ("intro", "front_end", "title", "load_picker", "loaded_menu", "add_from",
         "add_picker", "sheet", "save_picker", "saving")
#: ESC presses that may be spent leaving the intro and the front end for the party menu.
BOOT_ESCAPES = 6
#: Seconds a screen may stay unchanged after an ESC before ESC is pressed on it again.
ESCAPE_AGAIN = 15.0
#: The only keys each screen may receive; the save and load letters come from the manifest
#: and are checked against `SLOT`. The party menu's D(rop), E(xit), R(emove), C(reate) and
#: M(odify) and the sheet's D(rop) and T(rade) are deliberately absent.
ALLOWED_KEYS = {
    "intro": frozenset({"ESC"}), "front_end": frozenset({"ESC"}), "title": frozenset({"L"}),
    "load_picker": frozenset("ABCDEFGHIJ"), "loaded_menu": frozenset({"A", "V", "S", "NP7"}),
    "add_from": frozenset({"P"}), "add_picker": frozenset({"A", "NP1", "E"}),
    "sheet": frozenset({"E"}), "save_picker": frozenset("ABCDEFGHIJ"),
}
#: Seconds the live party read may take before the run stops without saving: three times the
#: 60 s that timed out when the host was loaded (the same read answers in about 30 s idle).
READ_LIMIT = 180.0
#: Seconds one boot frame may stay unchanged before the wait for the party menu stops, and the
#: seconds in all it may take: a loaded host stretches the credits, which keep changing.
BOOT_IDLE = 150.0
BOOT_CEILING = 900.0
#: Seconds the game is left to finish writing after the save message clears.
POST_WRITE_WAIT = 20.0
TITLE = route_curse.CURSE_KEY


def load_guard_map(path: pathlib.Path) -> dict:
    """A title's guard map file as `PixelGuards` rules: each rule's box, digest and `and` boxes."""
    keep = ("box", "sha256", "and")
    return {state: {k: v for k, v in rule.items() if k in keep} if isinstance(rule, dict) else
            [{k: v for k, v in r.items() if k in keep} for r in rule]
            for state, rule in json.loads(path.read_text())["guards"].items()}


def guard_rules() -> dict:
    """The Curse guard map with the ADD screens added."""
    rules = load_guard_map(GUARDS)
    require(not set(ADD_GUARDS) & set(rules), "an ADD guard name is already a Curse guard")
    return {**rules, **ADD_GUARDS}


class Screens:
    """Grab, recognise and press only on a matched screen; an unknown screen times out."""

    #: The states told apart, and the keys each may receive; a driver for another route
    #: replaces both.
    known: tuple[str, ...] = KNOWN
    allowed: dict[str, frozenset[str]] = ALLOWED_KEYS

    def __init__(self, guest: Any, holder: str, out: pathlib.Path, guards: Any,
                 deadline: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.guest, self.holder, self.out, self.guards = guest, holder, out, guards
        self.deadline, self.clock, self.sleep = deadline, clock, sleep
        self.events: list[dict] = []
        self.count = 0
        self.grabbed = False
        out.mkdir(parents=True)

    def left(self, cap: float) -> float:
        left = min(cap, self.deadline - self.clock())
        require(left > 0, "the run deadline expired")
        return left

    def look(self, label: str) -> tuple[list[str], pathlib.Path]:
        """One grab and every known state it matches."""
        self.count += 1
        raw = self.out / f"{self.count:03d}-{label}-raw.png"
        crop = self.out / f"{self.count:03d}-{label}.png"
        self.grabbed = bool(self.guest.grab(label, raw, crop, self.left(20)))
        if not self.grabbed:
            return [], raw
        return [s for s in self.known if s in self.guards and self.guards(s, crop)], crop

    def wait(self, states: tuple[str, ...], limit: float, *, past: tuple[str, ...] = ()) -> str:
        """Grab until one of `states` shows; another known screen stops the run.

        `past` holds the screen the last key went out on and any the game shows while it acts
        on that key, which are polled past rather than taken as a wrong screen.
        """
        end = self.clock() + self.left(limit)
        shot = None
        while self.clock() < end:
            seen, shot = self.look("-".join(states))
            hits = [s for s in states if s in seen]
            if hits:
                self.events.append({"screen": hits[0], "shot": str(shot)})
                return hits[0]
            stray = [s for s in seen if s not in past]
            require(not stray, f"expected {'/'.join(states)}, saw {stray}; shot {shot}")
            self.sleep(min(2.0, max(0.0, end - self.clock())))
        raise RouteError(f"{'/'.join(states)} did not show within {limit:.0f}s; last shot {shot}")

    def press(self, key: str, on: str) -> None:
        require(key in self.allowed.get(on, ()), f"{key} is not a key this driver sends on {on}")
        self.guest.press(self.holder, key, timeout=self.left(30))
        self.events.append({"from": on, "key": key})

    def to_party_menu(self, idle: float = BOOT_IDLE, ceiling: float = BOOT_CEILING) -> None:
        """Wait out the boot, pressing ESC on the intro and the front end until the party menu.

        The wait goes on while the frame keeps changing; it fails after `idle` seconds on one
        unchanged frame or `ceiling` seconds in all.
        """
        began = self.clock()
        end = began + self.left(ceiling)
        changed_at, last = began, None
        escapes, pressed_on, pressed_at = 0, None, 0.0
        while True:
            now = self.clock()
            require(now < end, f"the party menu did not show within {ceiling:.0f}s")
            require(now - changed_at < idle,
                    f"the boot frame stayed unchanged for {idle:.0f}s before the party menu")
            seen, shot = self.look("boot")
            # A failed grab shows nothing, so it is neither a change nor a stall.
            frame = (hashlib.sha256(shot.read_bytes()).hexdigest()
                     if self.grabbed and shot.exists() else None)
            if frame is not None and frame != last:
                last, changed_at = frame, self.clock()
            if "title" in seen:
                self.events.append({"screen": "title", "shot": str(shot)})
                return
            screen = next((s for s in ("intro", "front_end") if s in seen), None)
            if screen is not None and (screen != pressed_on
                                       or self.clock() - pressed_at >= ESCAPE_AGAIN):
                require(escapes < BOOT_ESCAPES, f"{BOOT_ESCAPES} ESCs did not reach the party menu")
                self.press("ESC", screen)
                escapes += 1
                pressed_on, pressed_at = screen, self.clock()
            stray = [s for s in seen if s not in ("intro", "front_end")]
            require(not stray, f"the boot showed {stray} before the party menu; shot {shot}")
            self.sleep(3.0)


#: Seconds each pipe call of the latest live read took. The read runs on a worker thread that
#: may still be waiting when `bounded` gives up, so the list is shared and only appended to
#: there; `list(...)` of it is a single atomic copy under the GIL.
PIPE_CALLS: list[float] = []


def read_live(holder: str) -> list[dict]:
    """The running party from memory: name, control, status and type of each member."""
    from automap import amiga, amigaparty  # noqa: PLC0415

    pipe = amiga.WinuaePipe(holder=holder)
    pipe.call_seconds = PIPE_CALLS
    target = amiga.AmigaTarget(pipe, amiga.MACHINES[TITLE])
    target.locate()
    members = amigaparty.read_party(target)
    require(members is not None, "the party list does not read")
    return [{"name": m.name, "control": m.raw[0xF7], "status": m.raw[0x19A],
             "type": m.raw[0x11B]} for m in members]


def check_live(live: list[dict], manifest: dict) -> dict:
    """The live party must be the loaded one with every staged character after it.

    The names decide; each added member's control, status and type are recorded beside the
    staged `.cha`'s, and the saved slot's read-back is what judges them.
    """
    add = manifest["add"]
    names = [name_key(m["name"]) for m in live]
    loaded = [name_key(name) for name in add["load_names"]]
    rows = {row["key"]: row for row in add["copies"]}
    require(names[:len(loaded)] == loaded and sorted(names[len(loaded):]) == sorted(rows),
            f"the party after ADD is {[m['name'] for m in live]}, not "
            f"{add['load_names']} and {[row['stem'] for row in add['copies']]}")
    staged = amiga_adf.AmigaDisk.open(manifest["disks"]["save"]["path"])
    fields = {}
    for member in live[len(loaded):]:
        cha = staged.read_file(rows[name_key(member["name"])]["cha"]["target"])
        fields[member["name"]] = {field: {"cha": cha[pool], "live": member[field],
                                          "equal": cha[pool] == member[field]}
                                  for field, (pool, _later) in MAPPED.items()
                                  if field != "hit_points"}
    return fields


def mute(guest: Any, out: pathlib.Path, timeout: float) -> pathlib.Path:
    """Mute the Windows VM's playback endpoint and keep the readback as the run's audio proof."""
    proof = out / "mute.json"
    output = guest._run("ssh", acceptance.MUTE_READBACK, timeout=timeout)
    require("{" in output, f"winuaemute.ps1 printed no JSON: {output!r}")
    write_json(proof, json.loads(output[output.index("{"):]))
    require(guest.silence(proof), "the Windows playback endpoint did not read back muted")
    return proof


def bounded(reader: Callable, holder: str, seconds: float) -> Any:
    """`reader(holder)` in a worker thread given `seconds`; a failure or a timeout stops the save.

    A thread and `join` work on every platform, where an alarm signal exists only on POSIX.
    A reader still running at the timeout is left to finish on its own daemon thread.
    """
    result: dict[str, Any] = {}

    def work() -> None:
        try:
            result["value"] = reader(holder)
        except BaseException as exc:  # noqa: BLE001 - handed to the caller below
            result["error"] = exc

    worker = threading.Thread(target=work, name="curseadd-party-read", daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise RouteError(f"the party did not read before the save: no answer in {seconds:.0f}s")
    if "error" in result:
        exc = result["error"]
        raise RouteError(f"the party did not read before the save: "
                         f"{type(exc).__name__}: {exc}") from exc
    return result["value"]


def drive(screens: Screens, manifest: dict, holder: str, reader: Callable) -> dict:
    """Load, add every staged character, view each and save once; return what was read live."""
    add = manifest["add"]
    count = len(add["copies"])
    screens.to_party_menu()
    screens.press("L", "title")
    screens.wait(("load_picker",), 60, past=("title",))
    screens.press(add["load"], "load_picker")
    screens.wait(("loaded_menu",), 90, past=("load_picker",))
    screens.press("A", "loaded_menu")
    screens.wait(("add_from",), 30, past=("loaded_menu",))
    screens.press("P", "add_from")
    screens.wait(("add_picker",), 60, past=("add_from",))
    for number in range(count):
        if number:
            # The highlight stays on the row just added; the next unadded row is below it.
            screens.press("NP1", "add_picker")
        screens.press("A", "add_picker")
        screens.sleep(5.0)
        shown = screens.wait(("add_picker", "loaded_menu"), 60, past=("add_picker",))
        if shown == "loaded_menu":
            require(number == count - 1,
                    f"the picker closed after {number + 1} of {count} characters")
            break
    else:
        # E on the party menu is EXIT FROM GAME, so the grab that matches the ADD list is the
        # last thing before the key; a list that closed late is taken as closed.
        if screens.wait(("add_picker", "loaded_menu"), 30) == "add_picker":
            screens.press("E", "add_picker")
            screens.wait(("loaded_menu",), 30, past=("add_picker",))
    PIPE_CALLS.clear()
    try:
        live = bounded(reader, holder, screens.left(READ_LIMIT))
    except RouteError as exc:
        raise RouteError(f"{exc}; pipe calls took {list(PIPE_CALLS)} s") from exc
    found: dict[str, Any] = {"live": live, "live_fields": check_live(live, manifest),
                             "pipe_call_seconds": list(PIPE_CALLS)}
    # ADD leaves the last character added highlighted; NP7 moves up the list.
    for number in range(count):
        if number:
            screens.press("NP7", "loaded_menu")
            screens.sleep(2.0)
        screens.press("V", "loaded_menu")
        screens.wait(("sheet",), 30, past=("loaded_menu",))
        screens.press("E", "sheet")
        screens.wait(("loaded_menu",), 30, past=("sheet",))
    screens.press("S", "loaded_menu")
    screens.wait(("save_picker",), 30, past=("loaded_menu",))
    screens.press(add["save"], "save_picker")
    screens.wait(("loaded_menu",), 120, past=("save_picker", "saving"))
    screens.sleep(POST_WRITE_WAIT)
    screens.wait(("loaded_menu",), 30)
    return found


def run(args: argparse.Namespace, *, guest: Any = None, guards: Any = None,
        boot: Callable = acceptance.boot_lane, halt: Callable = acceptance.halt_lane,
        reader: Callable = read_live, clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep) -> dict:
    """Boot a staged manifest, drive the ADD route, save once, halt, fetch and read back."""
    require(0 <= args.wait_lane <= 1800, "lane wait exceeds 1800 seconds")
    require(0 < args.budget <= 3600, "budget must be at most 3600 seconds")
    require(not args.out.exists(), f"{args.out} already exists")
    manifest = json.loads(args.manifest.read_text())
    require("add" in manifest and manifest.get("title") == "curse",
            "the manifest is not a curseadd.py stage")
    add = manifest["add"]
    require(bool(add.get("copies")), "the manifest stages no character")
    require(bool(SLOT.fullmatch(str(add.get("load")))) and bool(SLOT.fullmatch(str(add.get("save"))))
            and add["load"] != add["save"], "the load and save letters must be two letters A-J")
    for key, entry in (*manifest["disks"].items(), *manifest["registered"].items()):
        require(sha256(pathlib.Path(entry["path"])) == entry["sha256"], f"the {key} disk hash differs")
    staged = amiga_adf.AmigaDisk.open(manifest["disks"]["save"]["path"])
    require(add_letter_free(staged, manifest["add"]["save"]),
            f"slot {manifest['add']['save']} is already on the staged disk")
    args.out.mkdir(parents=True)
    receipt: dict[str, Any] = {"started_utc": datetime.now(timezone.utc).isoformat(),
                               "manifest": str(args.manifest.resolve()), "holder": args.holder,
                               "out": str(args.out.resolve()), "success": False, "cleanup": []}
    guest = guest if guest is not None else WinGuest()
    command = [str(pathlib.Path(__file__)), "run", "--manifest", str(args.manifest),
               "--holder", args.holder, "--out", str(args.out)]
    booted = False
    screens = None
    try:
        guard_file = args.out / "guards.json"
        write_json(guard_file, guard_rules())
        guards = guards if guards is not None else PixelGuards(guard_file)
        proof = mute(guest, args.out, timeout=60)
        receipt["boot"] = boot(args.manifest, manifest, route_curse.CURSE, guest=guest,
                               holder=args.holder, audio_proof=proof, wait_lane=args.wait_lane,
                               timeout=300, command=command)
        booted = True
        deadline = clock() + args.budget
        screens = Screens(guest, args.holder, args.out / "screens", guards, deadline,
                          clock=clock, sleep=sleep)
        receipt.update(drive(screens, manifest, args.holder, reader))
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
            require(sha256(pathlib.Path(original["add"]["source"]["path"]))
                    == original["add"]["source"]["sha256"], "the source disk changed")
            receipt["source_hashes"] = "unchanged"
        except Exception as exc:  # noqa: BLE001
            receipt["cleanup"].append({"hash_error": str(exc)})
        fetched = (receipt.get("halt") or {}).get("fetched", {}).get("save")
        if "error" not in receipt and fetched:
            try:
                found = read_back(pathlib.Path(fetched["path"]), manifest)
                receipt["read_back"] = found
                receipt["problems"] = verdict(found, manifest)
            except Exception as exc:  # noqa: BLE001
                receipt["problems"] = [f"read-back: {type(exc).__name__}: {exc}"]
        elif "error" not in receipt:
            receipt["problems"] = ["no fetched save disk"]
        errors = [item for item in receipt["cleanup"] if any(k.endswith("error") for k in item)]
        receipt["success"] = ("error" not in receipt and not errors and "halt" in receipt
                              and receipt.get("problems") == [])
        write_json(args.out / "receipt.json", receipt)
    if not receipt["success"]:
        raise RouteError(receipt.get("error") or f"problems: {receipt.get('problems')}; "
                         f"cleanup: {receipt['cleanup']}")
    return receipt


def add_letter_free(disk: amiga_adf.AmigaDisk, letter: str) -> bool:
    return letter not in slot_letters(disk)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("stage", help="copy Pool characters onto a copy of a prepared Curse disk A")
    s.add_argument("--manifest", type=pathlib.Path, required=True,
                   help="an `acceptance.py prepare --title curse` prepare.json")
    s.add_argument("--source-disk", type=pathlib.Path, required=True,
                   help="the Pool disk whose drawer holds NAME.cha")
    s.add_argument("--source-drawer", default=SOURCE_ROOT,
                   help="where the Pool files are: the disk root, where REMOVE writes them "
                        "(default), or a drawer such as `save`")
    s.add_argument("--name", action="append", required=True,
                   help="a member's name; repeat for several (the file stem is cleaned as "
                        "Pool's REMOVE cleans it)")
    s.add_argument("--load", default="A", help="the slot the run loads (default A)")
    s.add_argument("--save", default="D", help="the free slot the run saves to (default D)")
    s.add_argument("--out", type=pathlib.Path, required=True)
    g = sub.add_parser("run", help="boot a staged manifest in one muted WinUAE lane, add, view, "
                                   "save once, halt, fetch and read back")
    g.add_argument("--manifest", type=pathlib.Path, required=True, help="the stage's prepare.json")
    g.add_argument("--holder", required=True)
    g.add_argument("--out", type=pathlib.Path, required=True, help="a fresh folder for the run")
    g.add_argument("--budget", type=float, default=1800)
    g.add_argument("--wait-lane", type=float, default=0, metavar="SECONDS")
    r = sub.add_parser("read", help="read a fetched Curse disk against a staged manifest")
    r.add_argument("--manifest", type=pathlib.Path, required=True)
    r.add_argument("--disk", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    try:
        with terminating():
            if args.command == "stage":
                print(stage(args.manifest, args.source_disk, args.name, args.out,
                            load=args.load, save=args.save, source_drawer=args.source_drawer))
                return 0
            if args.command == "run":
                print(json.dumps(run(args), indent=1, sort_keys=True))
                return 0
            manifest = json.loads(args.manifest.read_text())
            found = read_back(args.disk, manifest)
            problems = verdict(found, manifest)
            print(json.dumps({"found": found, "problems": problems}, indent=1, sort_keys=True))
            return 0 if not problems else 1
    except (RouteError, OSError, ValueError, KeyError, amiga_adf.AmigaDiskError) as exc:
        print(f"curseadd: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
