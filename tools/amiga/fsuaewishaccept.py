#!/usr/bin/env python3
"""Collect bounded Wish-window and FS-UAE mapping evidence for one Amiga title.

The WinUAE controller in `winwishaccept.py` runs the route; this subclass
replaces its Windows ends. The game runs in a patched FS-UAE in an
instance-pool slot, started without the driver's own debugger connection, and
the real Wish window runs offscreen in this process, so its connection helper
is the emulator's one client. Keys go through X, so the Automapper stays up
while the party walks, and the driver reads memory through a client of that
helper. The mapping, persist and fight legs run here. The fight leg takes no control
branch, because the shipped FS-UAE cannot restore an exact picture; every write Wish's own
session makes is logged instead. Discovery modes, `--leg reconnect`, `--watch-dip` and
`--quickfight-control` stop before a slot is claimed.

A person must review the paired game and Wish images before a mapping row can
be accepted.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import inspect
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import fsuaegdb, guardmaps, screens  # noqa: E402
from tools.amiga import winwishaccept as base  # noqa: E402
from tools.amiga.winuaesession import RouteError  # noqa: E402
from tools.amiga.winwishaccept import AcceptanceStop, digest, row  # noqa: E402

#: The actions flag Wish reads when a window is built; `winwish.ACTIONS_FLAG` spells it too.
ACTIONS_FLAG = "WISH_EXPERIMENTAL_AMIGA_ACTIONS"
#: Seconds the emulator waits for its one debugger client, which here is Wish's helper.
CLIENT_WAIT = 120
#: Seconds between the journal answerer's keys and its next grab.
JOURNAL_SETTLE = 1.0
#: Seconds the connection helper may take to end once the emulator has gone.
HELPER_END_WAIT = 10.0
#: Route step kinds and the guest call each needs; a guest's `supports(kind)`, where it has one,
#: says whether that call is built rather than a placeholder that raises.
STEP_CALLS = {"insert": "insert", "snapshot": "snapshot", "restore": "restore", "reset": "reset"}
#: The per-poll log `PollLog` writes in the run folder.
POLL_LOG = "polls.jsonl"
#: The log `WishWriteLog` writes in the run folder: one row per write Wish's session made.
WRITE_LOG = "writes.jsonl"
#: Seconds a hold may end early, from the clock's own granularity, before it stops the run.
HOLD_SLACK = 0.5


def _git(*argv: str) -> str:
    root = pathlib.Path(__file__).resolve().parents[2]
    return subprocess.run(["git", "-C", str(root), *argv], check=True, text=True,
                          capture_output=True).stdout


def driver_state() -> dict[str, Any]:
    """The source commit this run's driver came from, and whether the tree had changes."""
    return {"sha": _git("rev-parse", "HEAD").strip(),
            "dirty": bool(_git("status", "--porcelain").strip())}


def control_lines(rows: list[dict[str, Any]]) -> list[str]:
    """Button rows as `Type|Name|objectName|enabled=B|visible=B`, the field order the WinUAE
    controls listing has, so `flag_controls` reads `parts[1]` and `parts[3]` from both."""
    from tools.gui import windowbuttons  # noqa: PLC0415

    return windowbuttons.button_lines(rows)


#: The ERROR and CRITICAL record starts and the line that ends one, in the session log and in `crashes.log`.
_LOG_BLOCKS = (
    ("wish-", re.compile(r"\d\d:\d\d:\d\d (ERROR|CRITICAL) "), re.compile(r"\d\d:\d\d:\d\d ")),
    ("crashes.log", re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d "),
     re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ")))


def wish_log_blocks(folder: pathlib.Path) -> list[dict[str, Any]]:
    """The ERROR and CRITICAL records of Wish's logs in `folder`, in `winwish.wish_log_errors` form.

    Each is a dict with its `file`, its `lines` (the record and its traceback) and the
    `exception` line that closes it; a missing folder holds none."""
    from tools.amiga import winwish  # noqa: PLC0415

    blocks: list[dict[str, Any]] = []
    for path in sorted(pathlib.Path(folder).glob("*")) if pathlib.Path(folder).is_dir() else ():
        rule = next((r for prefix, *r in _LOG_BLOCKS
                     if path.name.startswith(prefix) and (prefix != "wish-" or ".log" in path.name)), None)
        if rule is None or not path.is_file():
            continue
        start, stop = rule
        inside = False
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if start.match(line):
                inside = True
                blocks.append({"file": path.name, "lines": [line]})
            elif stop.match(line):
                inside = False
            elif inside:
                blocks[-1]["lines"].append(line)
    for block in blocks:
        while len(block["lines"]) > 1 and not block["lines"][-1].strip():
            block["lines"].pop()
        block["exception"] = winwish._log_exception(block["lines"])  # noqa: SLF001
        if len(block["lines"]) > winwish.LOG_BLOCK_LINES:
            block["lines"] = block["lines"][:1] + block["lines"][1 - winwish.LOG_BLOCK_LINES:]
    return blocks


def guest_gaps(game: Any, route: Any) -> list[str]:
    """What the guest lacks that this route needs, as reasons; empty when it has everything."""
    gaps = []
    if "attach" not in inspect.signature(game.start).parameters:
        gaps.append("the FS-UAE guest cannot start without attaching its own debugger")
    if not hasattr(game, "last_shot"):
        gaps.append("the FS-UAE guest records no last shot")
    kinds = sorted({step.kind for phase in route.phases for step in phase.steps})
    supports = getattr(game, "supports", None)
    for kind in kinds:
        call = STEP_CALLS.get(kind)
        if call and not callable(getattr(game, call, None)):
            gaps.append(f"the route has a {kind} step and the FS-UAE guest has no {call}")
        elif call and supports is not None and not supports(kind):
            gaps.append(f"the route has a {kind} step and the FS-UAE guest's {call} is not built yet")
    return gaps


def check_holds(route: Any) -> None:
    """A hold step waits some seconds with no screen grab and no checkpoint. Without a key it
    waits on the screen the step before it reached. With one, it presses the key on that
    screen first, and `state` is the screen the wait after the hold must find."""
    for phase in route.phases:
        before = phase.initial_state
        for step in phase.steps:
            if step.kind == "hold":
                seconds = getattr(step, "seconds", None)
                if not isinstance(seconds, (int, float)) or not seconds > 0:
                    raise AcceptanceStop(f"{phase.name}: a hold step needs a positive number of seconds")
                if step.checkpoint:
                    raise AcceptanceStop(f"{phase.name}: a hold step has no checkpoint")
                if step.key is None and step.state != before:
                    raise AcceptanceStop(f"{phase.name}: a hold on {step.state} follows a step "
                                         f"that reached {before}")
            before = step.state


def stage_search_area(manifest_path: pathlib.Path, out: pathlib.Path) -> pathlib.Path:
    """Copy the prepared Curse save disk into `out` with `maproute.SEARCH_FLAG` set to 1 in the
    loaded slot, and write `out/prepare.json` naming the copy. The prepared disk is not written.

    Returns the new manifest's path; the manifest records the word's file offset, before and after."""
    from goldbox import amiga_adf, amiga_savegame  # noqa: PLC0415
    from tools.amiga import cursefight, maproute  # noqa: PLC0415

    manifest = json.loads(pathlib.Path(manifest_path).read_text())
    if manifest.get("title") != "curse":
        raise AcceptanceStop("SEARCH AREA staging needs a Curse manifest")
    source = manifest.get("disks", {}).get("save")
    if not isinstance(source, dict) or digest(pathlib.Path(source["path"])) != source["sha256"]:
        raise AcceptanceStop("the prepared save disk is missing or changed")
    slot = maproute._slot_from(manifest)
    if out.exists():
        raise AcceptanceStop(f"the staging folder already exists: {out}")
    out.mkdir(parents=True)
    local = out / "save.adf"
    shutil.copyfile(source["path"], local)
    path = amiga_savegame.slot_path(amiga_savegame.CURSE, slot)
    data = amiga_adf.AmigaDisk.open(local).read_file(path)
    pool_address = maproute.SEARCH_FLAG - 0x200
    at = amiga_savegame.CURSE.vm_offset(pool_address)
    before = amiga_savegame.word(data, pool_address, amiga_savegame.CURSE)
    staged = data[:at] + (1).to_bytes(2, "big") + data[at + 2:]
    disk = cursefight.stage_slot(local, slot, staged)
    staged_manifest = {
        **manifest, "disks": {**manifest["disks"], "save": disk},
        "prepared_from": {"path": str(pathlib.Path(manifest_path).resolve()),
                          "save_sha256": source["sha256"]},
        "staged_word": {"word": f"${maproute.SEARCH_FLAG:04X}", "slot": slot, "file": path,
                        "file_offset": at, "before": before, "after": 1}}
    written = out / "prepare.json"
    written.write_text(json.dumps(staged_manifest, indent=2, sort_keys=True) + "\n")
    return written


def _export_guards(args: argparse.Namespace, route: Any, states: set[str] | None = None,
                   *, extra: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any]]:
    """The measured guards exported into the run folder, renamed into place only once complete.

    `states` are the screens the leg needs a guard for; the mapping route's own when None.
    `extra` is the fight plan's own guards, merged into the export before the check."""
    final = pathlib.Path(args.out) / "guards-export"
    if final.exists():
        raise AcceptanceStop(f"guard export directory already exists: {final}")
    expected_source = f"guards_{guardmaps.FILES[route.title]}.json"
    if route.guard_path.name != expected_source or not route.guard_path.is_file():
        raise AcceptanceStop(f"the measured guard source must be {expected_source}")
    pathlib.Path(args.out).mkdir(parents=True, exist_ok=True)
    made = pathlib.Path(tempfile.mkdtemp(prefix=".guards-export.", dir=args.out))
    try:
        try:
            rc = guardmaps.main(["--maps", str(route.guard_path.parent), "export",
                                 "--title", route.title, "--out", str(made)])
        except (OSError, ValueError) as exc:
            raise AcceptanceStop(f"guard export failed: {exc}") from exc
        if rc:
            raise AcceptanceStop(f"guard export failed with exit {rc}")
        if extra:
            base._merge_guards(made / "guards.json", extra)
        guards = screens.PixelGuards(made / "guards.json")
        missing = (base._states(route, actions=False) if states is None else states) - guards.rules.keys()
        if missing:
            raise AcceptanceStop("route has no measured guards for " + ", ".join(sorted(missing)))
        made.rename(final)
    except BaseException:
        shutil.rmtree(made, ignore_errors=True)
        raise
    exported = final / "guards.json"
    return screens.PixelGuards(exported), {
        "source": str(route.guard_path), "source_sha256": digest(route.guard_path),
        "export": str(exported), "export_sha256": digest(exported)}


def preflight(args: argparse.Namespace, *, game: Any, route_for: Any,
              binary: Any = None, kickstart: Any = None, driver: Any = driver_state,
              journal_check: Any = None, export: Any = _export_guards,
              ) -> tuple[Any, Any, dict[str, Any]]:
    """Check every static dependency before a slot is claimed."""
    if getattr(args, "discover", None):
        raise AcceptanceStop("discovery modes are not run on FS-UAE")
    leg = getattr(args, "leg", "mapping")
    if leg not in ("mapping", "persist", "fight"):
        raise AcceptanceStop(f"--leg {leg} is not run on FS-UAE")
    if getattr(args, "quickfight_control", False):
        raise AcceptanceStop("--quickfight-control is not run on FS-UAE")
    if getattr(args, "watch_dip", False):
        raise AcceptanceStop("--watch-dip is not run on FS-UAE: no key can wait in the "
                             "emulator while Wish does not read the game")
    base.check_leg_flags(args)
    if args.deadline > base.MAX_SECONDS or args.deadline <= base.CLEANUP_SECONDS:
        raise AcceptanceStop(f"--deadline must be above {base.CLEANUP_SECONDS} "
                             f"and at most {base.MAX_SECONDS}")
    if not pathlib.Path(args.manifest).is_file():
        raise AcceptanceStop("the prepared manifest is missing")
    hold = getattr(args, "arrival_hold", None)
    search = bool(getattr(args, "search_area", False))
    if (hold is not None or search) and args.title != "curse":
        raise AcceptanceStop("--arrival-hold and --search-area are Curse legs")
    idle = getattr(args, "idle", None)
    if idle is not None:
        if not idle > 0:
            raise AcceptanceStop("--idle needs a positive number of seconds")
        if hold is not None or search:
            raise AcceptanceStop("--idle is its own leg, not combined with --arrival-hold or --search-area")
    if search:
        args.manifest = stage_search_area(args.manifest, pathlib.Path(args.out) / "staged-search")
    manifest = json.loads(pathlib.Path(args.manifest).read_text())
    if leg != "fight" and isinstance(manifest, dict) and "fight" in manifest:
        raise AcceptanceStop("a fight stage runs only with --leg fight")
    legs = {key: value for key, value in (("arrival_hold", hold), ("search_area", search))
            if value is not None and value is not False}
    try:
        route = route_for(args.title, manifest, **legs)
    except RouteError as exc:
        raise AcceptanceStop(str(exc)) from exc
    if leg == "mapping":
        base._phase_map(route)
    check_holds(route)
    checked = base.leg_preflight(args, route, manifest)
    gaps = guest_gaps(game, route)
    if gaps:
        raise AcceptanceStop("; ".join(gaps))
    if args.title == "ssb":
        if journal_check is None:
            from tools.amiga import route_silver_blades  # noqa: PLC0415

            journal_check = route_silver_blades.journal_preflight
        try:
            journal_check(sys.executable)
        except RouteError as exc:
            raise AcceptanceStop(str(exc)) from exc
    if len(route.mounted) > 4 or not route.mounted:
        raise AcceptanceStop("route has no initial media or has more than four drives")
    media = {item.key: item for item in route.media}
    if len(media) != len(route.media) or any(k not in media for k in route.mounted):
        raise AcceptanceStop("the route media keys are missing or repeated")
    for item in route.media:
        if not item.path.is_file() or digest(item.path) != item.sha256:
            raise AcceptanceStop(f"prepared medium {item.key} is missing or changed")
    if not route.loaded_slot or len(route.loaded_slot) != 1:
        raise AcceptanceStop("the manifest has no single prepared load slot")
    from tools.amiga import fsuaesession  # noqa: PLC0415

    try:
        emulator = pathlib.Path((binary or fsuaesession._binary)())
        rom = pathlib.Path((kickstart or fsuaesession._kickstart)())
    except RouteError as exc:
        raise AcceptanceStop(str(exc)) from exc
    plan = checked["plan"]
    guards, guard_info = export(args, route, *(() if checked["states"] is None else (checked["states"],)),
                                **({} if plan is None else {"extra": plan.extra_guards}))
    info = {"emulator": "fsuae", "driver": driver(),
            "fs_uae": {"path": str(emulator), "sha256": digest(emulator)},
            "kickstart": {"path": str(rom), "sha256": digest(rom)},
            "guards": guard_info, "loaded_slot": route.loaded_slot,
            "provenance": dict(route.provenance),
            "media": {key: {"source": str(item.path), "source_sha256": item.sha256}
                      for key, item in media.items()}}
    if checked["persist"]:
        info["leg"] = "persist"
        info["persist"] = checked["persist"]
    if plan is not None:
        info["leg"] = "fight"
        info["fight"] = base.fight_info(checked, manifest)
    return route, guards, info


class PollLog:
    """Every Automapper poll in this process, one JSON row each in `path`.

    While installed, `automap.state.Automapper.poll` and the `read_fix` it calls are wrapped,
    so the row's fix is the one that poll read. After the poll the row adds the resident GEO
    pointer (`resident_geo_address`), the map `ResidentGeo.identify` names there, a sha1
    prefix of that block, and what Wish then believes. Its own reads come after the poll's.
    """

    def __init__(self, path: pathlib.Path, elapsed: Any):
        self.path, self.elapsed = pathlib.Path(path), elapsed
        self.polls = 0
        self.starts: list[float] = []
        self.durations: list[float] = []
        self.failure: str | None = None
        self._fix: Any = None
        self._began: float | None = None
        self._saved: tuple[Any, Any] | None = None

    def install(self) -> None:
        from automap import state  # noqa: PLC0415

        if self._saved is not None:
            return
        self._saved = original_poll, original_read = state.Automapper.poll, state.read_fix
        log = self

        def read_fix(target: Any, game: Any = None) -> Any:
            log._fix = original_read(target, game)
            return log._fix

        def poll(mapper: Any) -> bool:
            log._fix = None
            log._began = log.elapsed()
            changed = original_poll(mapper)
            log.record(mapper, changed)
            return changed

        state.read_fix, state.Automapper.poll = read_fix, poll

    def remove(self) -> None:
        from automap import state  # noqa: PLC0415

        if self._saved is not None:
            state.Automapper.poll, state.read_fix = self._saved
            self._saved = None

    @staticmethod
    def _fix_fields(fix: Any) -> dict[str, Any] | None:
        if fix is None:
            return None
        return {key: getattr(fix, key, None) for key in
                ("x", "y", "facing", "source", "world_map", "world_node", "outdoors")}

    def spans(self, since: int) -> dict[str, Any]:
        """The polls after the first `since`: how many, the longest gap between two starts, the longest poll."""
        starts, durations = self.starts[since:], self.durations[since:]
        gaps = [later - earlier for earlier, later in zip(starts, starts[1:])]
        return {"polls": len(starts),
                "longest_gap": round(max(gaps), 3) if gaps else None,
                "longest_poll": round(max(durations), 3) if durations else None}

    def record(self, mapper: Any, changed: bool) -> None:
        self.polls += 1
        now = self.elapsed()
        began = now if self._began is None else self._began
        self.starts.append(began)
        self.durations.append(now - began)
        row: dict[str, Any] = {"poll": self.polls, "elapsed": round(now, 3),
                               "started": round(began, 3), "duration": round(now - began, 3),
                               "wall": round(time.time(), 3), "changed": bool(changed),
                               "fix": self._fix_fields(self._fix)}
        try:
            target = mapper.target
            address = (target.resident_geo_address()
                       if callable(getattr(target, "resident_geo_address", None)) else None)
            row["geo_address"] = None if address is None else hex(address)
            name = block = None
            if address is not None:
                from automap.area import ResidentGeo  # noqa: PLC0415

                resident = ResidentGeo(target, address)
                name = resident.identify(getattr(mapper, "_maps", None) or {})
                block = resident.block
            row["geo_name"] = name
            row["geo_sha1"] = None if block is None else hashlib.sha1(block).hexdigest()[:8]
            believed = mapper.state
            row["believed"] = {key: getattr(believed, key, None) for key in
                               ("x", "y", "facing", "area", "world_map", "outdoors")}
            row["pending"] = getattr(mapper, "_pending", None)
            row["verdict"] = getattr(mapper, "_verdict", None)
        except Exception as exc:  # noqa: BLE001 -- the row is evidence; Wish's poll goes on
            row["error"] = f"{type(exc).__name__}: {exc}"
        if self.failure is not None:
            return
        try:
            with self.path.open("a") as stream:
                stream.write(json.dumps(row, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001 -- a full disk must not end Wish's poll
            self.failure = f"{type(exc).__name__}: {exc}"


class WishWriteLog:
    """Every write Wish's own session makes to the game, one JSON row each in `path`.

    While installed, `automap.amiga.AmigaTarget.write` is wrapped for the whole class, the one
    method every Amiga action, Level up and the automatic Quickfight clear writes through. A call
    is recorded only when its target is `wish_target()` at that moment, so the driver's own
    helper client, which is an `AmigaTarget` too, is not. A write that raised is recorded with
    its error, since part of it may have landed.
    """

    def __init__(self, path: pathlib.Path, elapsed: Any, wish_target: Any):
        self.path, self.elapsed, self.wish_target = pathlib.Path(path), elapsed, wish_target
        #: `(address, bytes)` of each recorded write, oldest first.
        self.made: list[tuple[int, bytes]] = []
        self.failure: str | None = None
        self._saved: Any = None

    def install(self) -> None:
        from automap import amiga  # noqa: PLC0415

        if self._saved is not None:
            return
        self._saved = original = amiga.AmigaTarget.write
        log = self

        def write(target: Any, addr: int, data: bytes, *args: Any, **kwargs: Any) -> Any:
            wished = log.wish_target()
            if wished is None or target is not wished:
                return original(target, addr, data, *args, **kwargs)
            error = None
            try:
                return original(target, addr, data, *args, **kwargs)
            except BaseException as exc:
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                log.record(addr, bytes(data), error)

        amiga.AmigaTarget.write = write

    def remove(self) -> None:
        from automap import amiga  # noqa: PLC0415

        if self._saved is not None:
            amiga.AmigaTarget.write = self._saved
            self._saved = None

    def record(self, address: int, data: bytes, error: str | None) -> None:
        self.made.append((address, data))
        if self.failure is not None:
            return
        row = {"write": len(self.made), "elapsed": round(self.elapsed(), 3),
               "wall": round(time.time(), 3), "address": f"0x{address:X}",
               "length": len(data), "data": data.hex(), "error": error}
        try:
            with self.path.open("a") as stream:
                stream.write(json.dumps(row) + "\n")
        except Exception as exc:  # noqa: BLE001 -- a full disk must not end Wish's write
            self.failure = f"{type(exc).__name__}: {exc}"


def helper_memory(memory: Any, open_client: Any) -> Any:
    """Point a fight driver's `Memory` at a client of the connection helper of its own.

    `cursefight.Memory.target()` opens WinUAE's pipe. Here it returns `cursefight.Serial` over
    the target `open_client()` gives, under the memory's own lock, and opens a new client when
    that one is lost. A client of its own keeps a read a timed-out worker is still making off the
    driver's client. `memory.close_client()` closes it. Returns `memory`."""
    from automap import amiga  # noqa: PLC0415
    from tools.amiga import cursefight  # noqa: PLC0415

    held: dict[str, Any] = {"gdb": None}

    def close_client() -> None:
        with memory._lock:
            gdb, held["gdb"], memory._target = held["gdb"], None, None
            if gdb is not None:
                gdb.close()

    def target() -> Any:
        with memory._lock:
            gdb = held["gdb"]
            if (memory._target is None or gdb is None or getattr(gdb, "lost", False)
                    or getattr(gdb, "sock", True) is None):
                with contextlib.suppress(Exception):
                    close_client()
                gdb, found, layout = open_client()
                want = amiga.MACHINES[memory.title].title
                if getattr(layout, "title", None) != want:
                    gdb.close()
                    raise AcceptanceStop(f"the helper's game is {getattr(layout, 'title', None)}, "
                                         f"not {want}")
                held["gdb"] = gdb
                memory._target = cursefight.Serial(found, memory._lock)
            return memory._target

    memory.target = target
    memory.close_client = close_client
    return memory


@contextlib.contextmanager
def _fight_memory_from(build: Any):
    """`winwishaccept._fight_memory` answered by `build(original, holder, route)` for
    `run_fight`, which looks it up at call time."""
    saved = base._fight_memory
    base._fight_memory = lambda holder, route: build(saved, holder, route)
    try:
        yield
    finally:
        base._fight_memory = saved


class _NotingGuards:
    """The screen guards, telling the guest when a frame matched, so its first key is not held."""

    def __init__(self, guards: Any, noted: Any):
        self._guards, self._noted = guards, noted

    def __call__(self, state: str, crop: pathlib.Path) -> bool:
        matched = self._guards(state, crop)
        if matched:
            self._noted()
        return matched

    def __getattr__(self, name: str) -> Any:
        return getattr(self._guards, name)


def _log_note(log: Any, name: str, payload: dict[str, Any]) -> None:
    """Log a debugger note whose own `event` would collide with the log's first argument."""
    fields = dict(payload)
    if "event" in fields:
        fields["note_event"] = fields.pop("event")
    log(name, **fields)


class _StateView:
    def __init__(self, owner: _Encounters):
        self.owner = owner

    def load(self) -> dict[str, Any]:
        enc = self.owner.enc
        return {"on": enc.active, "rows": enc.outstanding()}


class _Encounters:
    """`fsuaegdb.Encounters` with the calls `Controller` makes of the WinUAE switch.

    `on`, `off` and `keys` return the result dictionary the controller checks, with
    `error` set when the switch noted one; `state.load()` is whether it is on and the
    journal rows still in the game.
    """

    def __init__(self, title: str, machine: Any, port: int, *, log: Any, press: Any,
                 now: Any, encounters: Any = None):
        self.title, self.log, self.press, self.now = title, log, press, now
        self.errors: list[str] = []
        self.enc = encounters or fsuaegdb.Encounters(
            self._note, machine, every=fsuaegdb.WISH_REAPPLY_EVERY,
            journal=fsuaegdb.Journal(fsuaegdb.encounter_journal(port)))
        self.state = _StateView(self)

    def _note(self, **payload: Any) -> None:
        if payload.get("error"):
            self.errors.append(str(payload["error"]))
        _log_note(self.log, "no_encounters_row", payload)

    def _result(self, **extra: Any) -> dict[str, Any]:
        found, self.errors = self.errors, []
        return {**extra, **({"error": "; ".join(found)} if found else {})}

    def on(self) -> dict[str, Any]:
        self.errors = []
        self.enc.command("on", self.now())
        if self.enc.title is not None and self.enc.title != self.title:
            self.errors.append(f"the helper's game is {self.enc.title}, not {self.title}")
        if not self.enc.active and not self.errors:
            self.errors.append("the switch did not come on")
        return self._result(on=self.enc.active)

    def off(self) -> dict[str, Any]:
        self.errors = []
        self.enc.command("off", self.now())
        return self._result(on=self.enc.active)

    def keys(self, names: list[str]) -> dict[str, Any]:
        self.errors, pressed = [], []
        for key in names:
            if self.enc.blocks_key(key, self.now()):
                return self._result(pressed=pressed,
                                    stopped=f"{key} was blocked while the switch may be in the game")
            self.press(key)
            pressed.append(key)
        return self._result(pressed=pressed)

    def reapply(self) -> None:
        self.enc.reapply(self.now())

    def close(self) -> None:
        self.enc.close()


class _TargetView:
    """A target over the cached helper client whose `close` leaves that client open."""

    def __init__(self, target: Any):
        self._target = target

    def close(self) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)


def helper_machine(port: int) -> tuple[Any, Any, Any]:
    """`fsuaegdb.helper_machine`, with the machine's memory regions measured as `connect_pipe` does."""
    from automap import amiga  # noqa: PLC0415

    gdb, target, layout = fsuaegdb.helper_machine(port)
    try:
        target.memory = amiga.memory_regions(target.read)
    except BaseException:
        gdb.close()
        raise
    return gdb, target, layout


def install_wish_hooks() -> tuple[Any, ...]:
    """Install Wish's exception hooks in this process and return what they replaced.

    Without them an exception in a Qt slot aborts the process; with them it is written to
    Wish's log, which `wish_log_blocks` reads."""
    from wish import debuglog  # noqa: PLC0415

    saved = (sys.excepthook, sys.unraisablehook, debuglog._previous_hook)  # noqa: SLF001
    debuglog._previous_hook = None  # noqa: SLF001
    debuglog.install_excepthook()
    return saved


def restore_wish_hooks(saved: tuple[Any, ...]) -> None:
    """Put back what `install_wish_hooks` replaced."""
    from wish import debuglog  # noqa: PLC0415

    sys.excepthook, sys.unraisablehook, debuglog._previous_hook = saved  # noqa: SLF001


@contextlib.contextmanager
def _reads_through(connect: Any):
    """`amigatarget.connect_pipe` answered by `connect` for the inherited readers, which import it at call time."""
    from tools.amiga import amigatarget  # noqa: PLC0415

    saved = amigatarget.connect_pipe
    amigatarget.connect_pipe = connect
    try:
        yield
    finally:
        amigatarget.connect_pipe = saved


# A step needs about a second to land; Wish must then read twice, and its slowest measured poll is 14.3 s.
KEY_LAND_SECONDS = 1.0
WISH_READS_PER_KEY = 2
KEY_READ_LIMIT = 20.0


class FsuaeController(base.Controller):
    """One bounded FS-UAE boot. One `FsuaeGuest` is both the lane and the game."""

    #: The shipped FS-UAE binary cannot restore an exact picture, so no leg takes a branch that needs one.
    control_branches = False

    def __init__(self, args: argparse.Namespace, *, game: Any, guards: Any, route: Any,
                 info: dict[str, Any], wish_run: Any = None, machine: Any = helper_machine,
                 clock=time.monotonic, sleep=None):
        self.wish = wish_run
        self.machine_factory = machine
        self.held_machine: tuple[Any, Any, Any] | None = None
        self.claimed = False
        self.stopped = False
        self.cleaning = False
        self.saved_env: dict[str, str | None] | None = None
        self.saved_port: Any = None
        self.poll_log: PollLog | None = None
        self.write_log: WishWriteLog | None = None
        #: The fight drivers' memories, each with a helper client of its own to close.
        self.fight_memories: list[Any] = []
        self.saved_hooks: tuple[Any, ...] | None = None
        super().__init__(args, guest=None, lane=game, game=game,
                         guards=_NotingGuards(guards, game.note_recognised)
                         if callable(getattr(game, "note_recognised", None)) else guards,
                         route=route, zipped=None, info=info, clock=clock,
                         sleep=sleep or self._idle)

    # -- time ------------------------------------------------------------------

    def left(self, limit: float) -> float:
        why = fsuaegdb.STOP["why"]
        if why and not self.cleaning:
            raise AcceptanceStop(f"the run was stopped: {why}")
        return super().left(limit)

    def _idle(self, seconds: float) -> None:
        """Wait with Wish's events running and the encounter switch applied again as it is due."""
        end = self.clock() + seconds
        while True:
            remaining = end - self.clock()
            if remaining <= 0 or fsuaegdb.STOP["why"]:
                return
            active = self.encounters is not None and self.encounters.enc.active
            self.wish.pump(min(remaining, fsuaegdb.WISH_REAPPLY_EVERY) if active else remaining)
            if self.encounters is not None:
                self.encounters.reapply()

    # -- the window --------------------------------------------------------------

    def _game_section(self) -> None:
        """Keys go through X, so the Automapper never gives way to another tab."""

    def _map_section(self) -> None:
        """Keys go through X, so the map tab is never left, as it is never left for a player.

        A tab switch calls the mapper's `resume()`, which changes which positions Wish believes."""

    def _press(self, key: str, *, action: bool = False) -> None:
        super()._press(key, action=action)
        self._let_wish_read(key)

    def _send_key(self, key: str) -> None:
        """One key now, through the encounter switch while it is on; the caller counts it."""
        if self.encounters_on:
            result = self.encounters.keys([key])
            if result.get("stopped") or result.get("error") or result.get("pressed") != [key]:
                raise AcceptanceStop(f"encounter-controlled key {key}: {result}")
        else:
            self.game.press(self.args.holder, key, self.left(30))
        self.log("key", key=key)

    def _scheduled_key(self, key: str, *, show_map: bool, index: int | None = None) -> dict[str, Any]:
        """WinUAE's queued key, on FS-UAE: the emulator queues nothing, so the key is pressed now.

        The Automapper is never left here, so it is showing before the key lands. Wish is pumped
        until it has read the game twice, then for `WALK_SETTLE` more. The schedule has the
        WinUAE fields, with no lead. A key with Wish not reading cannot be sent: that is the
        control branch, which FS-UAE does not run."""
        if not show_map:
            raise AcceptanceStop(f"{key}: FS-UAE cannot send a key while Wish does not read the game")
        before = self.clock()
        self._send_key(key)
        sent = self.key_sent = self.clock()
        self._let_wish_read(key)
        read = self.clock()
        self.sleep(self.left(base.WALK_SETTLE))
        schedule = {"key": key, "index": index, "lead_frames": 0, "min_emulation_speed": None,
                    "tab_shown_s": 0.0, "key_earliest_s": round(sent - before, 3),
                    "key_latest_s": round(sent - before, 3),
                    "shot_s": round(self.clock() - before, 3)}
        self.log("map_walk", **schedule)
        if self.clock() < read + base.WALK_SETTLE:
            raise AcceptanceStop(f"the route time ran out before Wish had read for "
                                 f"{base.WALK_SETTLE:.0f} s after key {key}")
        return schedule

    def _fight_memory(self, make: Any, holder: str, route: Any) -> Any:
        """The fight driver's memory from `make`, reading through a helper client of its own."""
        memory = helper_memory(make(holder, route),
                               lambda: self.machine_factory(self.game.slot.port))
        self.fight_memories.append(memory)
        self.log("fight_memory", title=memory.title)
        return memory

    def _let_wish_read(self, key: str) -> None:
        """Pump Wish's events until it has read the game again, so no key lands between two reads.

        A player's Wish runs its own event loop; here it reads only while the runner pumps. A
        starved window stops the run instead of grading Wish on a marker it had no chance to move."""
        window = self.wish.window
        if window is None:
            return
        begin = self.clock()
        mapper = window.mapper
        before = mapper._ticks
        self.wish.pump(KEY_LAND_SECONDS)
        while mapper._ticks - before < WISH_READS_PER_KEY:
            if self.clock() - begin >= KEY_READ_LIMIT:
                raise AcceptanceStop(
                    f"Wish read the game {mapper._ticks - before} times in "
                    f"{self.clock() - begin:.1f} s after key {key}")
            self.wish.pump(0.25)
        self.log("wish_reads", key=key, reads=mapper._ticks - before,
                 seconds=round(self.clock() - begin, 3))

    def _free_pipe(self) -> str | None:
        return None

    def _helper(self) -> dict[str, Any]:
        return fsuaegdb.helper_row(self.game.slot.port)

    def _open_wish(self) -> dict[str, Any]:
        self.wish.open()
        connected = self.wish.wait_connected(min(CLIENT_WAIT, self.left(CLIENT_WAIT)))
        self.log("wish_open", **connected)
        self.summary.setdefault("helper_rows", []).append({"at": "open", **connected})
        if not connected.get("connected"):
            raise AcceptanceStop(f"Wish did not connect: {connected.get('error')}")
        self.wish_closed = False
        return connected

    def _close_wish(self) -> None:
        self.wish.close()
        self.wish_closed = True
        helper = self._helper()
        self.log("wish_closed", helper=helper)
        self.summary.setdefault("helper_rows", []).append({"at": "close", "helper": helper})

    def _shoot_window(self, path: pathlib.Path) -> None:
        from tools.gui import mapmarker  # noqa: PLC0415

        mapmarker.shot(self.wish.app, self.wish.window, path)

    def _wish_shot(self, path: pathlib.Path, name: str) -> None:
        """The window's picture, with a sidecar of its session, its reading and the helper."""
        self._shoot_window(path)
        sidecar: dict[str, Any] = {"source": "wish-offscreen", "helper": self._helper()}
        try:
            window = self.wish.window
            sidecar["session"] = {"state": window.session.state, "note": window.session.note,
                                  "connected": window.session.target is not None}
            from tools.gui import mapmarker  # noqa: PLC0415

            sidecar["reading"] = mapmarker.reading(window.map, name)
        except Exception as exc:  # noqa: BLE001 -- the sidecar is evidence, not a verdict
            sidecar["error"] = f"{type(exc).__name__}: {exc}"
        pathlib.Path(str(path) + ".json").write_text(json.dumps(sidecar, indent=1, default=str) + "\n")

    def _controls_listing(self) -> list[str]:
        from tools.gui import windowbuttons  # noqa: PLC0415

        return windowbuttons.listing(self.wish.window.map)

    def _click(self, label: str | None = None, automation_id: str | None = None) -> Any:
        """Press a button by its label or its id, answering Yes to its question; a greyed one raises ControlGreyed.

        A choice dialog is cancelled, as `windowbuttons.click` does with no spell."""
        from tools.gui import windowbuttons  # noqa: PLC0415

        window = self.wish.window.map
        if automation_id is not None:
            name = automation_id.rsplit(".", 1)[-1]
        else:
            names = [r["name"] for r in windowbuttons.rows(window)
                     if r["text"].replace("&", "") == label]
            if len(names) != 1:
                raise AcceptanceStop(f"{label}: {len(names)} buttons carry that label")
            name = names[0]
        reply = windowbuttons.click(window, name, answer="yes")
        if reply["error"] == "button is disabled":
            raise base.ControlGreyed(name, reply["error"])
        if reply["error"]:
            raise AcceptanceStop(f"{name}: {reply['error']}")
        self.log("click_dialogs", control=name, dialogs=reply["dialogs"])
        unexpected = [d for d in reply["dialogs"] if d["kind"] in ("choice", "message")]
        if unexpected:
            raise AcceptanceStop(f"{name} raised a {unexpected[0]['kind']} dialog that was not answered "
                                 f"as a question: {unexpected[0].get('text')!r}")
        return reply

    def _wish_log_blocks(self) -> list[dict[str, Any]]:
        from wish import debuglog  # noqa: PLC0415

        return wish_log_blocks(debuglog.log_dir())

    def _wish_target(self) -> Any:
        """The target Wish's session reads and writes through now; None while it is not attached."""
        window = getattr(self.wish, "window", None)
        return getattr(getattr(window, "session", None), "target", None)

    def _wish_writes(self) -> list[tuple[int, bytes]] | None:
        """Every write Wish's session has made since the fight leg began; None with no log kept."""
        return None if self.write_log is None else list(self.write_log.made)

    def _wish_pair(self, name: str, lap: Any) -> tuple[pathlib.Path, pathlib.Path]:
        wish_path = self.out / f"wish-{name}.png"
        self._wish_shot(wish_path, name)
        lap("wish_shot")
        controls_path = self.out / f"controls-{name}.txt"
        controls_path.write_text("\n".join(self._controls_listing()) + "\n")
        lap("controls")
        return wish_path, controls_path

    def _checkpoint(self, name: str, expected: Any, game_evidence: dict[str, Any],
                    *, reads: tuple = ()) -> None:
        if self.wish_closed:
            self._open_wish()
        super()._checkpoint(name, expected, game_evidence, **({"reads": reads} if reads else {}))

    def flag_controls(self) -> None:
        """Pool's and Silver Blades' flag modes: the window closed and opened with the
        actions flag on, off, then on, each listing read as the WinUAE controller reads it."""
        if self.route.title not in ("pool", "ssb"):
            return
        flagged_actions = ("Heal party", "Save spells", "Restore spells",
                           "Identify", "Quickfight off")
        controls_wanted = (*flagged_actions, "Fast Travel")
        flags_on_travel = None
        before = os.environ.get(ACTIONS_FLAG)
        try:
            for name, features in (("on", True), ("map_only", False), ("restored", True)):
                if name != "on":
                    self._close_wish()
                    if features:
                        os.environ[ACTIONS_FLAG] = "1"
                    else:
                        os.environ.pop(ACTIONS_FLAG, None)
                    self._open_wish()
                self.sleep(self.left(10))
                listing = control_lines(self.wish.buttons())
                listed = self.out / f"flags-{name}.txt"
                listed.write_text("\n".join(listing) + "\n")
                picture = self.out / f"flags-{name}.png"
                self._wish_shot(picture, f"flags-{name}")
                controls: dict[str, list[str]] = {}
                for line in listing:
                    parts = line.split("|")
                    if len(parts) >= 4 and parts[1] in controls_wanted:
                        controls.setdefault(parts[1], []).append(parts[3])
                missing = [key for key in controls_wanted if len(controls.get(key, ())) != 1]
                if missing:
                    raise AcceptanceStop(f"{name} flags: absent or ambiguous controls {missing}; kept {listed}")
                if name == "on":
                    flags_on_travel = controls["Fast Travel"][0]
                if name == "map_only":
                    if any(controls[key][0] != "enabled=False" for key in flagged_actions):
                        raise AcceptanceStop(f"map-only flag left an action enabled; kept {listed}")
                    if controls["Fast Travel"][0] != flags_on_travel:
                        raise AcceptanceStop(
                            f"map-only flag changed Fast Travel from the flags-on state; kept {listed}")
                    if any("card_" in line and "_level_up" in line and "enabled=True" in line
                           for line in listing):
                        raise AcceptanceStop(f"map-only flag left Level up enabled; kept {listed}")
                self.summary.setdefault("flags", {})[name] = row(
                    "awaiting image review", observed=controls,
                    evidence=[str(listed), str(picture), str(picture) + ".json"])
                self.log("flags", mode=name, controls=controls, picture=str(picture))
        finally:
            if before is None:
                os.environ.pop(ACTIONS_FLAG, None)
            else:
                os.environ[ACTIONS_FLAG] = before

    # -- the route ------------------------------------------------------------------

    def run_phase(self, phase: Any, action_context: Any = None,
                  namespace: str | None = None) -> None:
        """The WinUAE controller's phase, with `hold` steps run here between its parts.

        Each run of steps between holds is one phase of the controller's own, starting on the
        screen the hold waited on; the phase is recorded as completed once."""
        if not phase.ready or not any(step.kind == "hold" for step in phase.steps):
            return super().run_phase(phase, action_context, namespace)
        if action_context is not None or namespace:
            raise AcceptanceStop(f"{phase.name}: a hold step runs only in a mapping phase")
        initial, part = phase.initial_state, []
        for step in (*phase.steps, None):
            if step is not None and step.kind != "hold":
                part.append(step)
                continue
            # With no steps, the part is only its wait for the screen the hold is on.
            super().run_phase(dataclasses.replace(phase, initial_state=initial,
                                                  steps=tuple(part)))
            self.summary["completed_sequence"].pop()
            if step is not None:
                self._hold(phase, step)
                initial, part = step.state, []
        self.summary["completed_sequence"].append(phase.name)

    def _idle_leg(self) -> None:
        """No key and no grab for `--idle` seconds with Wish attached, its every poll logged."""
        seconds = float(self.args.idle)
        before = self.poll_log.polls if self.poll_log else 0
        start = self.clock()
        self.log("idle", seconds=seconds, polls=before)
        self.sleep(self.left(seconds))
        held = round(self.clock() - start, 3)
        spans = self.poll_log.spans(before) if self.poll_log else {}
        self.log("idle_end", held=held, **spans)
        self.summary["idle"] = {"seconds": seconds, "held": held, **spans}
        if held < seconds - HOLD_SLACK:
            raise AcceptanceStop(f"the idle ended after {held} s of {seconds}")

    def _hold(self, phase: Any, step: Any) -> None:
        """Press the step's key, if it has one, then wait `step.seconds` with no grab, Wish
        polling throughout; the next part's first wait checks the screen is `step.state`."""
        if step.key is not None:
            self._press(step.key)
        start = self.clock()
        self.log("hold", phase=phase.name, state=step.state, seconds=step.seconds,
                 key=step.key, polls=self.poll_log.polls if self.poll_log else None)
        self.sleep(self.left(step.seconds))
        held = round(self.clock() - start, 3)
        self.log("hold_end", phase=phase.name, state=step.state, held=held,
                 polls=self.poll_log.polls if self.poll_log else None)
        self.summary.setdefault("holds", []).append(
            {"phase": phase.name, "state": step.state, "seconds": step.seconds, "held": held})
        if held < step.seconds - HOLD_SLACK:
            raise AcceptanceStop(f"the hold on {step.state} ended after {held} s of {step.seconds}")

    # -- the game -------------------------------------------------------------------

    def _machine(self) -> tuple[Any, Any, Any]:
        held = self.held_machine
        if held is None or getattr(held[0], "lost", False) or getattr(held[0], "sock", True) is None:
            self._drop_machine()
            self.held_machine = self.machine_factory(self.game.slot.port)
            self.log("helper_client", located=hex(getattr(self.held_machine[1], "data_base", 0) or 0))
        return self.held_machine

    def _drop_machine(self) -> None:
        held, self.held_machine = self.held_machine, None
        if held is not None:
            try:
                held[0].close()
            except Exception as exc:  # noqa: BLE001
                self.log("helper_client_close", error=str(exc))

    def _connect(self, holder: str, layout: Any, *args: Any, **kwargs: Any) -> _TargetView:
        _gdb, target, found = self._machine()
        if getattr(found, "title", None) != getattr(layout, "title", None):
            raise AcceptanceStop(f"the helper's game is {getattr(found, 'title', None)}, "
                                 f"not {getattr(layout, 'title', None)}")
        return _TargetView(target)

    def _read_engine(self, lap: Any, *, reads: tuple = ()) -> tuple[dict[str, Any], dict[str, int]]:
        with _reads_through(self._connect):
            return super()._read_engine(lap, reads=reads)

    def _read_fix(self) -> dict[str, Any] | None:
        with _reads_through(self._connect):
            return super()._read_fix()

    def _fresh_party(self):
        with _reads_through(self._connect):
            return super()._fresh_party()

    def _relaunched(self) -> None:
        """The program started again: the helper client is located again on its next read."""
        super()._relaunched()
        self._drop_machine()

    def _switch(self, enabled: bool) -> None:
        if self.encounters is None:
            self.encounters = _Encounters(
                self.route.game_key, self._machine, self.game.slot.port, log=self.log,
                press=lambda key: self.game.press(self.args.holder, key, self.left(30)),
                now=lambda: round(self.clock() - self.started, 1))
        super()._switch(enabled)
        self._let_wish_read("encounter switch")

    def _answer_journal(self) -> None:
        if self.route.title != "ssb":
            raise AcceptanceStop("journal answer is only defined for Silver Blades")
        disk = next(m.path for m in self.route.media if m.key == self.route.mounted[0])
        answered = fsuaegdb.journal(argparse.Namespace(display=self.game.slot.display,
                                                       settle=JOURNAL_SETTLE), adf=str(disk),
                                    guest=self.game)
        self.log("journal_answer", answered=bool(answered))
        if not answered:
            raise AcceptanceStop("journal was not answered")
        self._let_wish_read("journal")
        self.summary["interstitial_keys"] = self.summary.get("interstitial_keys", 0) + 1

    def _answer_wheel(self, screen: str) -> None:
        raise AcceptanceStop(f"{screen} appeared, and the code wheel has no FS-UAE answerer")

    # -- lifecycle ----------------------------------------------------------------------

    def _disk_folder(self) -> pathlib.Path:
        """The title's folder for Wish: copies of the first two mounted disks, as the WinUAE window gets."""
        folder = self.out / "disks"
        folder.mkdir(exist_ok=True)
        media = {m.key: m for m in self.route.media}
        for number, key in enumerate(self.route.mounted[:2]):
            source = media[key].path
            shutil.copyfile(source, folder / f"df{number}-{source.name}")
        return folder

    def _enter_environment(self) -> None:
        """The window's environment as `fsuaegdb.wish` sets it, saved first so cleanup can put it back."""
        from automap import amiga  # noqa: PLC0415
        from automap.config import Settings  # noqa: PLC0415
        from tools.gui import mapmarker  # noqa: PLC0415

        self.saved_env = {name: os.environ.get(name)
                          for name in (*fsuaegdb.WISH_ENV, ACTIONS_FLAG)}
        self.saved_port = amiga.FSUAE_PORT
        for name in fsuaegdb.WISH_UNSET:
            os.environ.pop(name, None)
        os.environ[ACTIONS_FLAG] = "1"
        amiga.FSUAE_PORT = self.game.slot.port
        runtime = self.out / "runtime"
        runtime.mkdir(mode=0o700, exist_ok=True)
        os.environ["XDG_RUNTIME_DIR"] = str(runtime.resolve())
        (self.out / fsuaegdb.RUNTIME_NOTE).write_text(f"{runtime.resolve()}\n", encoding="utf-8")
        mapmarker.private_settings(self.out)
        settings = Settings.load()
        settings.game_folders = {**(settings.game_folders or {}),
                                 self.route.game_key: str(self._disk_folder().resolve())}
        settings.diagnostics = True
        settings.clear_quickfight = bool(getattr(self.args, "watch", False))
        settings.save()
        self.saved_hooks = install_wish_hooks()

    def _leave_environment(self) -> None:
        from automap import amiga  # noqa: PLC0415

        if self.saved_hooks is not None:
            restore_wish_hooks(self.saved_hooks)
            self.saved_hooks = None
        if self.saved_env is None:
            return
        for name, value in self.saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        amiga.FSUAE_PORT = self.saved_port
        self.saved_env = None

    def _up(self) -> None:
        holder = self.args.holder
        receipt = self.game.claim(holder, self.left(60))
        self.claimed = True
        self.log("claim", receipt=receipt)
        self._stage_media()
        drives = [self.remotes[key] for key in self.route.mounted]
        self.booted = True
        receipt = self.game.start(holder, *drives, timeout=self.left(CLIENT_WAIT),
                                  options=tuple(self.route.amiga_title.options), attach=False)
        environ = self.game.work / "environ.txt"
        self.summary["silence"] = {"environ": environ.read_text() if environ.is_file() else None,
                                   "silent": self.game.silence()}
        self.game.holder = holder
        self.log("up", receipt=receipt, silence=self.summary["silence"])
        self._enter_environment()
        if getattr(self.args, "poll_log", False):
            self.poll_log = PollLog(self.out / POLL_LOG, lambda: self.clock() - self.started)
            self.poll_log.install()
            self.summary["poll_log"] = str(self.out / POLL_LOG)
        if self.leg == "fight":
            self.write_log = WishWriteLog(self.out / WRITE_LOG, lambda: self.clock() - self.started,
                                          self._wish_target)
            self.write_log.install()
            self.summary["wish_writes"] = {"log": str(self.out / WRITE_LOG), "writes": 0,
                                           "failure": None}
        if self.wish is None:
            self.wish = fsuaegdb.WishRun(argparse.Namespace(
                port=self.game.slot.port, display=self.game.slot.display, observe_wait=0.0),
                self.out)
        self._open_wish()

    def _stop_game(self, timeout: float) -> str:
        self.stopped = True
        return self.game.stop(self.args.holder, timeout)

    def _cleanup(self) -> None:
        self.cleaning = True
        failures: list[str] = []
        cleanup = self.summary["cleanup"]
        if self.encounters_on:
            self._encounters_off(failures)
        if self.encounters is not None:
            try:
                self.encounters.close()
            except Exception as exc:  # noqa: BLE001
                failures.append(f"encounters close: {exc}")
        for memory in self.fight_memories:
            try:
                memory.close_client()
            except Exception as exc:  # noqa: BLE001
                failures.append(f"fight memory client: {exc}")
        self._drop_machine()
        if self.wish is not None and getattr(self.wish, "window", None) is not None:
            try:
                self._close_wish()
            except Exception as exc:  # noqa: BLE001
                failures.append(f"wish close: {exc}")
        if self.booted and not self.stopped:
            try:
                cleanup["stop"] = self._stop_game(60)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"stop: {exc}")
        if self.booted:
            for medium in self.route.media:
                if medium.key not in self.remotes:
                    continue
                try:
                    copied = self.out / f"working-{medium.key}.adf"
                    self.game.get(self.remotes[medium.key], copied, timeout=60)
                    self.info["media"][medium.key]["guest_working_sha256"] = digest(copied)
                    self.info["media"][medium.key]["guest_working_copy"] = str(copied)
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"working medium {medium.key}: {exc}")
            if self.saved_env is not None:
                end = time.monotonic() + HELPER_END_WAIT
                try:
                    helper = self._helper()
                    while helper["alive"] and time.monotonic() < end:
                        time.sleep(0.5)
                        helper = self._helper()
                    cleanup["helper_after_stop"] = helper
                    if helper["alive"]:
                        failures.append(f"the connection helper (pid {helper['pid']}) outlived the emulator")
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"helper: {exc}")
        if self.claimed:
            try:
                cleanup["release"] = self.game.release(self.args.holder, 30)
                self.claimed = False
            except Exception as exc:  # noqa: BLE001
                failures.append(f"release: {exc}")
        for medium in self.route.media:
            try:
                after = digest(medium.path)
                self.info["media"][medium.key]["source_after_sha256"] = after
                if after != medium.sha256:
                    failures.append(f"source medium {medium.key} changed")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"source medium {medium.key}: {exc}")
        try:
            self._leave_environment()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"environment: {exc}")
        if self.poll_log is not None:
            self.poll_log.remove()
            self.summary["poll_count"] = self.poll_log.polls
            if self.poll_log.failure is not None:
                self.summary["poll_log_failure"] = self.poll_log.failure
        if self.write_log is not None:
            self.write_log.remove()
            self.summary["wish_writes"].update(writes=len(self.write_log.made),
                                               failure=self.write_log.failure)
        cleanup["errors"] = failures
        try:
            self.log("cleanup", errors=failures)
        except OSError as exc:
            failures.append(f"event log: {exc}")

    def _finish_route(self) -> None:
        """Everything after the last phase: the connected picture, the stop and the disconnect pictures."""
        for action in self.route.actions:
            if action.enabled:
                self.summary["actions"][action.kind]["reason"] = (
                    "pressed only on the persist leg")
        if self.wish_closed:
            self._open_wish()
        connected = self.out / "connected.png"
        self._wish_shot(connected, "connected")
        self.summary["cleanup"]["stop"] = self._stop_game(self.left(60))
        pictures = []
        for index, delay in enumerate((0, 15, 30)):
            if delay:
                self.sleep(self.left(delay))
            path = self.out / f"disconnect-{index}.png"
            self._wish_shot(path, f"disconnect-{index}")
            pictures.append(str(path))
        self.summary["mapping"]["disconnect"] = row(
            "awaiting image review", evidence=[str(connected), *pictures])

    def run_title(self) -> dict[str, Any]:
        with fsuaegdb.interruptible(lambda **payload: _log_note(self.log, "interrupt", payload)):
            with _reads_through(self._connect):
                if self.leg == "fight":
                    with _fight_memory_from(self._fight_memory):
                        return self.run_fight()
                return self.run_persist() if self.leg == "persist" else self._run_mapping()

    def _run_mapping(self) -> dict[str, Any]:
        try:
            self._up()
            title = self._await_title()
            self.summary["mapping"]["title"] = row("awaiting image review", evidence=[title])
            base._phase_map(self.route)
            for phase in self.route.phases:
                if phase.name == "reopen_step":
                    self._close_wish()
                self.run_phase(phase)
                label = "reopen" if phase.name == "reopen_step" else phase.name
                if label in self.summary["mapping"]:
                    self.summary["mapping"][label] = row("awaiting image review")
                if phase.name == "load":
                    if getattr(self.args, "idle", None) is not None:
                        self._idle_leg()
                        break
                    self.flag_controls()
            else:
                self._finish_route()
        except BaseException as exc:
            self.summary["failure"] = f"{type(exc).__name__}: {exc}"
            self.log("failure", error=self.summary["failure"])
            incomplete = next((name for name, result in self.summary["mapping"].items()
                               if result["status"] == "unproven"), None)
            if incomplete:
                self.summary["mapping"][incomplete]["reason"] = self.summary["failure"]
        finally:
            self._cleanup()
            (self.out / "summary.json").write_text(
                json.dumps(self.summary, indent=2, default=str) + "\n")
        return self.summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", choices=("pool", "curse", "ssb", "darkness"), required=True)
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--holder", required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--deadline", type=int, default=base.MAX_SECONDS)
    parser.add_argument("--discover", choices=(*base.LEAVE_MODES, *base.OPENING_MODES),
                        help="not run on FS-UAE; the run stops before a slot is claimed")
    parser.add_argument("--leg", choices=base.LEGS, default="mapping",
                        help="mapping, persist and fight run on FS-UAE; reconnect stops before "
                             "a slot is claimed")
    parser.add_argument("--action", action="append", choices=base.ACTION_KINDS,
                        help="run only this enabled action; repeat for several (--leg persist only)")
    parser.add_argument("--watch", action="store_true",
                        help="fight leg: start Wish with the clear-quickfight preference ticked "
                             "and take the Automapper branch at CONTINUE BATTLE, judged from "
                             f"Wish's writes in {WRITE_LOG}")
    parser.add_argument("--watch-map", action="store_true",
                        help="fight leg, with --watch: keep the Automapper showing from the last Q "
                             "to CONTINUE BATTLE, glancing at the game now and then")
    parser.add_argument("--press-quickfight-off", action="store_true",
                        help="fight leg, Pools of Darkness only: press Quickfight off at a second "
                             "member's bar, with no replay")
    parser.add_argument("--arrival-hold", type=float, metavar="SECONDS",
                        help="Curse Yulash: hold the arrival question this long before SNEAK IN; "
                             "implies --poll-log")
    parser.add_argument("--search-area", action="store_true",
                        help="Curse Yulash: stage $4C5B = 1 on a copy of the save disk in the run "
                             "folder and take SEARCH AREA from the world map; implies --poll-log")
    parser.add_argument("--idle", type=float, metavar="SECONDS",
                        help="load the party, then send no key and take no grab for this long "
                             "with Wish attached, and end the run; implies --poll-log")
    parser.add_argument("--poll-log", action="store_true",
                        help=f"write every Automapper poll's fix and resident GEO to {POLL_LOG}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    args.poll_log = (args.poll_log or args.arrival_hold is not None or args.search_area
                     or args.idle is not None)
    from tools.amiga import fsuaesession  # noqa: PLC0415
    from tools.amiga.maproute import route_for  # noqa: PLC0415

    game = fsuaesession.FsuaeGuest(game=f"amiga-{args.title}",
                                   first_key_after=fsuaesession.FIRST_KEY_AFTER.get(args.title))
    try:
        route, guards, info = preflight(args, game=game, route_for=route_for)
        controller = FsuaeController(args, game=game, guards=guards, route=route, info=info)
        result = controller.run_title()
    except (AcceptanceStop, RouteError, OSError, ValueError) as exc:
        print(f"fsuaewishaccept: {exc}", file=sys.stderr)
        return 2
    return 1 if result["failure"] or result["cleanup"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
