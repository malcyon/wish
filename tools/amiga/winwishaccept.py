#!/usr/bin/env python3
"""Collect bounded Wish-window and WinUAE mapping evidence for one Amiga title.

This driver records observations. A person must review paired game and Wish images
before the corresponding mapping row can be accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from dataclasses import asdict
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import guardmaps, noencounters, screens, winwish  # noqa: E402
from tools.amiga.winuaesession import RouteError, WinGuest  # noqa: E402

BUILD_SHA = re.compile(r"[0-9a-f]{40}\Z")
REQUIRED = ("load", "stationary", "walk", "transition", "reload", "reopen_step")
MAPPING_ROWS = ("title", "load", "stationary", "walk", "transition", "reload",
                "reopen", "disconnect")
STATUSES = ("passed", "failed", "unproven", "awaiting image review")
MAX_SECONDS = 3300
CLEANUP_SECONDS = 300
MAX_MAPPING_COMMANDS = 40
DISCOVERY_SECONDS = 1800
DISCOVERY_SNAPSHOT = "ssb_new_verdigris"
DISCOVERY_DF0_SHA256 = "068bc3e2bfd79e6014d427b5aef730d2bd52f0ba1cd28c3664fd9306a04a6948"
OPENING_FIRST_RULE = {
    "box": [88, 302, 700, 400],
    "sha256": "bfae49833516dc7b065f8121a4d5e6bd346cb091462c2b65baf334889eab7cfb",
    "and": [{"box": [186, 404, 586, 426],
             "sha256": "604731cd6f2b106a3670ba258e49c2545af33d3742467843fcd3a8c0f9ad7fe9"}],
}


def _opening_first_phase(route: Any) -> Any:
    from tools.amiga import maproute  # noqa: PLC0415

    load = maproute._load("ssb", "D")
    if (route.title != "ssb" or route.loaded_slot != "D"
            or route.mounted != ("df0", "df1")
            or not route.phases or route.phases[0] != load
            or any(action.enabled for action in route.actions)):
        raise AcceptanceStop("opening discovery needs the exact disabled Silver Blades load prefix")
    return maproute.Phase("opening_menu", "title", load.steps[:6])


def _discovery_phases(route: Any) -> dict[str, Any]:
    """Validate the measured prefix without accepting the unfinished mapping route."""
    from tools.amiga import maproute  # noqa: PLC0415

    if route.title != "ssb" or route.loaded_slot != "D" or route.mounted != ("df0", "df1"):
        raise AcceptanceStop("discovery needs the prepared Silver Blades slot D and two drives")
    phases = {phase.name: phase for phase in route.phases}
    if len(phases) != len(route.phases) or [p.name for p in route.phases[:3]] != [
            "load", "stationary", "walk"]:
        raise AcceptanceStop("discovery needs a distinct ordered load, stationary and walk prefix")
    if any(not phases[name].ready for name in ("load", "stationary", "walk")):
        raise AcceptanceStop("discovery prefix is not ready")
    if any(action.enabled for action in route.actions):
        raise AcceptanceStop("discovery cannot enable actions")
    load, stationary, walk = (phases[name] for name in ("load", "stationary", "walk"))
    if ([s.kind for s in load.steps] != ["key"] * 6 + ["answer"]
            or [s.key for s in load.steps[:6]] != ["P", "L", "D", "V", "E", "B"]
            or [s.key for s in stationary.steps] != ["NP4", "NP6", "NP6", "NP4"]
            or any(s.kind != "turn" for s in stationary.steps)
            or [s.kind for s in walk.steps].count("move") != 17
            or [s.kind for s in walk.steps].count("snapshot") != 1
            or [s.kind for s in walk.steps].count("encounters") != 2
            or walk.steps[0].kind != "snapshot"
            or walk.steps[0].snapshot != DISCOVERY_SNAPSHOT
            or [(s.kind, s.encounters) for s in walk.steps if s.kind == "encounters"] != [
                ("encounters", True), ("encounters", False)]
            or walk.steps[-1].kind != "encounters"
            or any(s.kind not in ("move", "turn", "snapshot", "encounters") for s in walk.steps)
            or any(s.key != "NP8" for s in walk.steps if s.kind == "move")
            or [s.key for s in walk.steps if s.kind == "turn"] != [
                "NP4", "NP6", "NP4", "NP6", "NP4"]):
        raise AcceptanceStop("discovery prefix is not the measured Silver Blades route")
    checkpoints = set()
    for phase in (load, stationary, walk):
        for step in phase.steps:
            expected = step.expected
            if expected and expected.compare_to and expected.compare_to not in checkpoints:
                raise AcceptanceStop(f"discovery checkpoint {expected.compare_to} is missing")
            if step.checkpoint:
                if step.checkpoint in checkpoints:
                    raise AcceptanceStop(f"discovery checkpoint {step.checkpoint} repeats")
                checkpoints.add(step.checkpoint)
    if not {"loaded", "ssb_exit_square", "ssb_facing_exit"} <= checkpoints:
        raise AcceptanceStop("discovery has no measured start and terminal checkpoints")
    final = walk.steps[-2].expected
    if (walk.steps[-2].checkpoint != "ssb_facing_exit" or final is None
            or dict(final.engine or {}) != {"area": 16, "x": 15, "y": 8, "facing": 1}):
        raise AcceptanceStop("discovery terminal square is not 15,8,E")
    if (load, stationary, walk) != (maproute._load("ssb", "D"),
                                    maproute._ssb_stationary(), maproute._ssb_walk()):
        raise AcceptanceStop("discovery prefix differs from the guarded measured route")
    return {name: phases[name] for name in ("load", "stationary", "walk")}

def _action_budget(route: Any) -> int:
    from automap import amigaparty  # noqa: PLC0415

    def keys(phase: Any) -> int:
        return sum((amigaparty.MAX_MEMBERS - 1 if step.kind == "select" else 1)
                   for step in phase.steps if step.kind in ("key", "turn", "move", "insert", "select"))

    total = max(1, keys(next(phase for phase in route.phases if phase.name == "reload")))
    for action in route.actions:
        if action.enabled:
            visits = 3 if action.kind == "spells" else 2
            total += visits * (keys(action.show) + keys(action.back))
            total += 2 if action.kind == "spells" else 1
    return total


class AcceptanceStop(RuntimeError):
    """A route failed closed; the run still collects evidence and cleans up."""


def digest(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def row(status: str = "unproven", *, expected: Any = None, observed: Any = None,
        evidence: Any = None, reason: str | None = None) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(status)
    return {"status": status, "expected": expected, "observed": observed,
            "evidence": evidence or [], "reason": reason}


def _driver_sha() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                            text=True, capture_output=True)
    return result.stdout.strip()


def _phase_map(route: Any) -> dict[str, Any]:
    phases = {phase.name: phase for phase in route.phases}
    if len(phases) != len(route.phases):
        raise AcceptanceStop("the route repeats a phase name")
    absent = [name for name in REQUIRED if name not in phases]
    if absent:
        raise AcceptanceStop(f"required phases missing: {', '.join(absent)}")
    names = [phase.name for phase in route.phases]
    if names[0] != "load":
        raise AcceptanceStop("load must be the first phase")
    if names.index("stationary") > names.index("walk"):
        raise AcceptanceStop("stationary must precede walk")
    if names.index("reload") > names.index("reopen_step"):
        raise AcceptanceStop("reload must precede reopen_step")
    checkpoints = set()
    for phase in route.phases:
        for step in phase.steps:
            expected = step.expected
            if (expected is not None and expected.compare_to is not None
                    and expected.compare_to not in checkpoints):
                raise AcceptanceStop(
                    f"checkpoint {expected.compare_to} must precede its comparison")
            if step.checkpoint:
                if step.checkpoint in checkpoints:
                    raise AcceptanceStop(f"checkpoint {step.checkpoint} is repeated")
                checkpoints.add(step.checkpoint)
    unready = [f"{p.name}: {p.reason or 'no reason supplied'}" for p in phases.values()
               if not p.ready]
    if route.unresolved:
        unready.extend(route.unresolved)
    if unready:
        raise AcceptanceStop("route incomplete: " + "; ".join(unready))
    return phases


def _states(route: Any) -> set[str]:
    phases = [*route.phases]
    for action in route.actions:
        if action.enabled:
            if action.show is None or action.back is None:
                raise AcceptanceStop(f"{action.kind} has no game-display route")
            if not action.show.ready or not action.back.ready:
                raise AcceptanceStop(f"{action.kind} has an unready game-display route")
            phases.extend((action.show, action.back))
    return {state for phase in phases for state in
            (phase.initial_state, *(step.state for step in phase.steps))}


def preflight(args: argparse.Namespace, *, guest: Any, route_for: Any,
              driver_sha: str | None = None) -> tuple[Any, Any, pathlib.Path, dict[str, Any]]:
    """Check every static dependency before a lane can be claimed."""
    if not BUILD_SHA.fullmatch(args.sha):
        raise AcceptanceStop("--sha must be a full 40-digit frozen-build commit")
    mode = getattr(args, "discover", None)
    opening = mode == "ssb-opening-first"
    discovery = mode in ("ssb-leave", "ssb-opening-first")
    maximum = DISCOVERY_SECONDS if discovery else MAX_SECONDS
    if args.deadline > maximum or args.deadline <= CLEANUP_SECONDS:
        raise AcceptanceStop(f"--deadline must be above {CLEANUP_SECONDS} and at most {maximum}")
    if not pathlib.Path(args.manifest).is_file():
        raise AcceptanceStop("the prepared manifest is missing")
    manifest = json.loads(pathlib.Path(args.manifest).read_text())
    route = route_for(args.title, manifest)
    if discovery:
        source = manifest.get("substitute")
        if args.title != "ssb" or manifest.get("title") != "ssb" or not isinstance(
                source, dict) or source.get("letter") != "A" or manifest.get("state_a") != {
                    "area": 16, "x": 3, "y": 3, "facing": 2}:
            raise AcceptanceStop("discovery needs source A imported into D at 16,3,3,S")
        if opening:
            if manifest.get("opening_scene") is not True:
                raise AcceptanceStop("opening discovery needs an approved opening scene")
            _opening_first_phase(route)
        else:
            _discovery_phases(route)
        from tools.amiga import route_silver_blades  # noqa: PLC0415

        route_silver_blades.journal_preflight(sys.executable)
    else:
        _phase_map(route)
    if not winwish._mute_proof(pathlib.Path(args.mute_proof)):
        raise AcceptanceStop("the WinUAE audio mute proof is missing or stale")
    if len(route.mounted) > 4 or not route.mounted:
        raise AcceptanceStop("route has no initial media or has more than four drives")
    media = {item.key: item for item in route.media}
    if len(media) != len(route.media) or any(k not in media for k in route.mounted):
        raise AcceptanceStop("the route media keys are missing or repeated")
    if discovery:
        from tools.amiga import route_silver_blades  # noqa: PLC0415

        pins = {"df0": DISCOVERY_DF0_SHA256,
                "df1": route_silver_blades.DISK_B_SHA256}
        if set(media) != set(pins) or any(media[key].sha256 != sha
                                          for key, sha in pins.items()):
            raise AcceptanceStop("discovery prepared media do not match the approved DF0/DF1 pins")
    for item in route.media:
        if not item.path.is_file() or digest(item.path) != item.sha256:
            raise AcceptanceStop(f"prepared medium {item.key} is missing or changed")
    expected_source = f"guards_{guardmaps.FILES[route.title]}.json"
    if route.guard_path.name != expected_source or not route.guard_path.is_file():
        raise AcceptanceStop(f"the measured guard source must be {expected_source}")
    export_dir = pathlib.Path(args.out) / "guards-export"
    if export_dir.exists():
        raise AcceptanceStop(f"guard export directory already exists: {export_dir}")
    export_dir.mkdir(parents=True)
    try:
        rc = guardmaps.main(["--maps", str(route.guard_path.parent), "export",
                             "--title", route.title, "--out", str(export_dir)])
    except (OSError, ValueError) as exc:
        raise AcceptanceStop(f"guard export failed: {exc}") from exc
    if rc:
        raise AcceptanceStop(f"guard export failed with exit {rc}")
    exported = export_dir / "guards.json"
    guards = screens.PixelGuards(exported)
    if opening:
        phase = _opening_first_phase(route)
        states = {phase.initial_state, *(step.state for step in phase.steps),
                  "ssb_opening_first"}
    elif discovery:
        states = {"title"} | {state for phase in _discovery_phases(route).values()
                              for state in (phase.initial_state, *(s.state for s in phase.steps))}
    else:
        states = _states(route)
    missing = states - guards.rules.keys()
    if missing:
        raise AcceptanceStop("route has no measured guards for " + ", ".join(sorted(missing)))
    if opening and guards.rules["ssb_opening_first"] != OPENING_FIRST_RULE:
        raise AcceptanceStop("opening discovery needs the independent exact two-box guard")
    if not route.loaded_slot or len(route.loaded_slot) != 1:
        raise AcceptanceStop("the manifest has no single prepared load slot")
    if not driver_sha:
        driver_sha = _driver_sha()
    os.environ["GH_REPO"] = "malcyon/wish"
    zipped = winwish.fetch(guest, args.sha)
    listing = guest.gh("run", "list", "--workflow", winwish.WORKFLOW,
                       "--commit", args.sha, "--limit", "20", "--json",
                       "databaseId,headSha,conclusion,createdAt")
    release_run = winwish.pick_run(listing, args.sha)
    note = zipped.parent / winwish.COMMIT_FILE
    if not note.is_file() or note.read_text().strip() != args.sha:
        raise AcceptanceStop("the frozen artifact lacks a matching commit note")
    winwish.check_zip_commit(zipped, args.sha)
    info = {"build_sha": args.sha, "driver_sha": driver_sha,
            "release_run": release_run,
            "guards": {"source": str(route.guard_path),
                       "source_sha256": digest(route.guard_path),
                       "export": str(exported), "export_sha256": digest(exported)},
            "release_artifact": {"path": str(zipped), "sha256": digest(zipped)},
            "loaded_slot": route.loaded_slot, "provenance": dict(route.provenance),
            "media": {key: {"source": str(item.path), "source_sha256": item.sha256}
                       for key, item in media.items()}}
    if discovery:
        info["provenance"]["approved_media_sha256"] = pins
    return route, guards, zipped, info


class Controller:
    """One bounded boot with injectable guests and clock for lifecycle tests."""

    def __init__(self, args: argparse.Namespace, *, guest: Any, lane: Any,
                 game: Any, guards: Any, route: Any, zipped: pathlib.Path,
                 info: dict[str, Any], clock=time.monotonic, sleep=time.sleep):
        self.args, self.guest, self.lane, self.game = args, guest, lane, game
        self.guards, self.route, self.zipped, self.info = guards, route, zipped, info
        self.clock, self.sleep = clock, sleep
        self.out = pathlib.Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.events = self.out / "events.jsonl"
        self.started = self.clock()
        self.route_end = self.started + args.deadline - CLEANUP_SECONDS
        self.total_end = self.started + args.deadline
        self.mapping_commands = self.action_commands = 0
        self.action_limit = _action_budget(route)
        self.discovery = getattr(args, "discover", None) in ("ssb-leave", "ssb-opening-first")
        self.discovery_snapshot = False
        self.encounters = None
        self.encounters_on = False
        self.booted = False
        self.down_done = False
        self.pipe_released = False
        self.wish_closed = False
        self.remotes: dict[str, str] = {}
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self.area_by_geo: dict[str, set[int]] | None = None
        self.summary: dict[str, Any] = {**info,
            "mapping": {name: row() for name in MAPPING_ROWS},
            "actions": {action.kind: row() for action in route.actions},
            "original_slot_reload": row(),
            "checkpoints": self.checkpoints, "completed_sequence": [],
            "failure": None, "cleanup": {}}

    def log(self, event: str, **data: Any) -> None:
        record = {"elapsed": round(self.clock() - self.started, 3),
                  "event": event, **data}
        with self.events.open("a") as stream:
            stream.write(json.dumps(record, default=str) + "\n")

    def left(self, limit: float) -> float:
        remaining = min(limit, self.route_end - self.clock())
        if remaining <= 0:
            raise AcceptanceStop("the bounded route time is spent")
        return remaining

    def _count(self, action: bool = False) -> None:
        name = "action_commands" if action else "mapping_commands"
        cap = self.action_limit if action else MAX_MAPPING_COMMANDS
        if getattr(self, name) >= cap:
            raise AcceptanceStop(f"the {cap}-command {'action' if action else 'mapping'} cap is reached")
        setattr(self, name, getattr(self, name) + 1)

    def _game_section(self) -> None:
        if self.pipe_released:
            return
        if self.wish_closed:
            self.pipe_released = True
            return
        winwish.ui(self.guest, self.args.holder, "click", ("View", "Character Editor"),
                   kind="MenuItem")
        self.pipe_released = True
        self.log("pipe_released")

    def _map_section(self) -> None:
        if not self.pipe_released:
            return
        if self.wish_closed:
            raise AcceptanceStop("Wish is closed; start it before changing tabs")
        # Close the temporary debugger connection before Wish reacquires the pipe.
        self.game._pipe = None
        winwish.ui(self.guest, self.args.holder, "click", ("View", "Automapper"),
                   kind="MenuItem")
        self.pipe_released = False
        self.log("map_tab")

    def _capture(self, state: str, *, check: bool = True) -> dict[str, Any]:
        number = sum(1 for _ in self.out.glob("game-*.raw.png"))
        raw = self.out / f"game-{number:03d}.raw.png"
        crop = self.out / f"game-{number:03d}.png"
        exact = self.game.grab(state, raw, crop, self.left(30))
        evidence = {"raw": str(raw), "crop": str(crop) if exact else None,
                    "shot_source": self.game.last_shot}
        self.log("game_frame", state=state, **evidence)
        if not exact:
            if check:
                raise AcceptanceStop(f"{state}: no exact Amiga crop; kept {raw}")
            return evidence
        if check and not self.guards(state, crop):
            raise AcceptanceStop(f"{state} screen was not recognized; kept {raw}")
        return evidence

    def _await(self, state: str, *, limit: float = 90) -> dict[str, Any]:
        end = self.clock() + self.left(limit)
        last = None
        while self.clock() < end:
            last = self._capture(state, check=False)
            if last["crop"] is not None and self.guards(state, pathlib.Path(last["crop"])):
                return last
            self.sleep(min(1.0, max(0, end - self.clock())))
        raise AcceptanceStop(f"{state} screen was not recognized before its deadline; last {last}")

    def _press(self, key: str, *, action: bool = False) -> None:
        self._count(action)
        if self.encounters_on:
            result = self.encounters.keys([key])
            if result.get("stopped") or result.get("error") or result.get("pressed") != [key]:
                raise AcceptanceStop(f"encounter-controlled key {key}: {result}")
        else:
            self.game.press(self.args.holder, key, self.left(30))
        self.log("key", key=key)

    def _switch(self, enabled: bool) -> None:
        if self.encounters is None:
            from automap import amiga  # noqa: PLC0415

            pipe = amiga.WinuaePipe(holder=self.args.holder)
            title = self.route.game_key
            self.encounters = noencounters.WinuaeEncounters(
                title, amiga.AmigaTarget(pipe, amiga.MACHINES[title]),
                state=noencounters.WinuaeState(noencounters.winuae_state_path(self.args.holder)),
                lane_check=lambda: pipe.drives(self.args.holder),
                press=lambda key: self.game.press(self.args.holder, key, self.left(30)))
        result = self.encounters.on() if enabled else self.encounters.off()
        if result.get("error") or result.get("stopped"):
            raise AcceptanceStop(f"encounter switch did not reach {enabled}: {result}")
        saved = self.encounters.state.load()
        if bool(saved["on"]) != enabled or (not enabled and saved["rows"]):
            raise AcceptanceStop(f"encounter switch readback did not reach {enabled}: {saved}")
        self.encounters_on = enabled
        self.log("encounters", enabled=enabled, readback=result)

    def _checkpoint(self, name: str, expected: Any, game_evidence: dict[str, Any]) -> None:
        from automap import (
            amiga,  # noqa: PLC0415
            amigaparty,  # noqa: PLC0415
        )
        from tools.amiga import amigatarget  # noqa: PLC0415

        target = amigatarget.connect_pipe(self.args.holder, amiga.MACHINES[self.route.game_key])
        party = amigaparty.read_party(target)
        fix = target.fix()
        area = self._area_of(geo) if (geo := target.geo()) is not None else None
        engine = {"fix": (None if fix is None else
                          {"x": fix.x, "y": fix.y, "facing": fix.facing,
                           "outdoors": fix.outdoors, "world_map": fix.world_map,
                           "window": fix.window, "heading": fix.heading,
                           "area": area}),
                  "geo_sha256": (None if geo is None else hashlib.sha256(geo).hexdigest()),
                  "party": (None if party is None else [
                      {"slot": member.slot, "name": member.name,
                       "address": member.address, "raw": member.raw.hex(),
                       "items": [[node.address, node.raw.hex()] for node in member.item_nodes]}
                      for member in party])}
        target.close()
        self.game._pipe = None
        if self.wish_closed:
            winwish.start_wish(self.guest, self.args.holder, flag=True, reseed=False)
            self.wish_closed = False
        self._map_section()
        self.sleep(self.left(10))
        wish_path = self.out / f"wish-{name}.png"
        winwish.shot(self.guest, self.args.holder, "wish", wish_path)
        controls = winwish.ui(self.guest, self.args.holder, "controls")
        controls_path = self.out / f"controls-{name}.txt"
        controls_path.write_text("\n".join(controls) + "\n")
        verdict = self._compare_checkpoint(name, expected, engine)
        self.checkpoints[name] = {"expected": asdict(expected) if expected else None,
                                  "observed": engine, "game": game_evidence,
                                  "comparison": verdict,
                                  "wish": str(wish_path), "wish_sidecar": str(wish_path) + ".json",
                                  "controls": str(controls_path),
                                  "elapsed": round(self.clock() - self.started, 3),
                                  "pair_atomic": False}
        self.log("checkpoint", name=name, game=game_evidence, wish=str(wish_path))
        self._game_section()
        if verdict["status"] != "awaiting image review":
            raise AcceptanceStop(f"{name}: {verdict['reason'] or verdict['status']}")

    def _area_of(self, resident: bytes) -> int | None:
        """Identify an unchanged resident map from the prepared disks only."""
        from automap import amiga, maps  # noqa: PLC0415
        from goldbox.amiga_adf import AmigaDisk  # noqa: PLC0415

        if self.area_by_geo is None:
            self.area_by_geo = {}
            for medium in self.route.media:
                found = amiga.load_maps(medium.path)
                if not found and self.route.title == "pool":
                    found = maps._dax_maps(AmigaDisk.open(medium.path))
                for key, area in found.items():
                    name = hashlib.sha256(area.to_bytes()).hexdigest()
                    self.area_by_geo.setdefault(name, set()).add(int(key[3:], 16))
        ids = self.area_by_geo.get(hashlib.sha256(resident).hexdigest(), set())
        return next(iter(ids)) if len(ids) == 1 else None

    def _compare_checkpoint(self, name: str, expected: Any,
                            engine: dict[str, Any]) -> dict[str, Any]:
        if expected is None:
            if name in ("ssb_leave_terminal", "ssb_opening_after_first") and engine.get("fix") is None:
                return row("unproven", observed=engine, reason="the game fix was not readable")
            return row("awaiting image review", observed=engine)
        fix = engine.get("fix")
        if fix is None:
            return row("unproven", expected=asdict(expected), observed=engine,
                       reason="the game fix was not readable")
        missing = []
        for key, want in (expected.window or {}).items():
            if key not in fix:
                missing.append(f"window {key}")
            elif fix[key] != want:
                return row("failed", expected=asdict(expected), observed=engine,
                           reason=f"window {key} reads {fix[key]}, expected {want}")
        for key, want in (expected.engine or {}).items():
            # On Pool's travel grid, the game prints global coordinates while
            # target.fix() deliberately returns the local map-window square.
            if fix.get("outdoors") and key in ("x", "y"):
                continue
            if fix.get("outdoors") and key == "facing":
                # Travel headings use eight points; cardinal facings use four.
                heading = fix.get("heading")
                if heading is None:
                    missing.append("engine heading")
                elif heading != want * 2:
                    return row("failed", expected=asdict(expected), observed=engine,
                               reason=f"engine heading reads {heading}, expected {want * 2}")
                continue
            if key not in fix:
                missing.append(key)
            elif fix[key] != want:
                return row("failed", expected=asdict(expected), observed=engine,
                           reason=f"engine {key} reads {fix[key]}, expected {want}")
        if expected.compare_to:
            previous = self.checkpoints.get(expected.compare_to)
            if previous is None:
                return row("unproven", expected=asdict(expected), observed=engine,
                           reason=f"comparison checkpoint {expected.compare_to} is missing")
            old = previous["observed"].get("fix")
            if old is None:
                missing.append("previous fix")
            else:
                same_square = (fix["x"], fix["y"]) == (old["x"], old["y"])
                relation = expected.relation
                if relation == "stationary" and not same_square:
                    return row("failed", expected=asdict(expected), observed=engine,
                               reason=f"stationary control moved from {old} to {fix}")
                if relation == "moved" and same_square:
                    return row("failed", expected=asdict(expected), observed=engine,
                               reason=f"movement control stayed at {fix}")
                if relation == "equal" and fix != old:
                    return row("failed", expected=asdict(expected), observed=engine,
                               reason=f"reload changed established fix from {old} to {fix}")
                if relation == "area_changed":
                    old_geo = previous["observed"].get("geo_sha256")
                    if old_geo is None or engine["geo_sha256"] is None:
                        missing.append("resident area")
                    elif old_geo == engine["geo_sha256"]:
                        return row("failed", expected=asdict(expected), observed=engine,
                                   reason="the resident map did not change")
        status = "unproven" if missing else "awaiting image review"
        return row(status, expected=asdict(expected), observed=engine,
                   reason=("unreadable expected fields: " + ", ".join(missing)) if missing else None)

    def flag_controls(self) -> None:
        """Pool's three flag modes use the same boot and retain Wish settings."""
        if self.route.title != "pool":
            return
        controls_wanted = ("Heal party", "Save spells", "Restore spells",
                           "Identify", "Quickfight off", "Fast Travel")
        self._map_section()
        for name, flag, features, delay in (("on", True, True, 10),
                                             ("map_only", True, False, 10),
                                             ("off", False, False, 20),
                                             ("restored", True, True, 10)):
            if name != "on":
                winwish.restart_wish(self.guest, self.args.holder, flag=flag,
                                     features=features, reseed=False)
            self.sleep(self.left(delay))
            listing = winwish.ui(self.guest, self.args.holder, "controls")
            listed = self.out / f"flags-{name}.txt"
            listed.write_text("\n".join(listing) + "\n")
            picture = self.out / f"flags-{name}.png"
            winwish.shot(self.guest, self.args.holder, "wish", picture)
            controls = {}
            for line in listing:
                parts = line.split("|")
                if len(parts) >= 4 and parts[1] in controls_wanted:
                    controls.setdefault(parts[1], []).append(parts[3])
            if name in ("on", "map_only", "restored"):
                missing = [key for key in controls_wanted if len(controls.get(key, ())) != 1]
                if missing:
                    raise AcceptanceStop(f"{name} flags: absent or ambiguous controls {missing}; kept {listed}")
            if name == "map_only":
                if any(controls[key][0] != "enabled=False" for key in controls_wanted):
                    raise AcceptanceStop(f"map-only flag left an action enabled; kept {listed}")
                if any("card_" in line and "_level_up" in line and "enabled=True" in line
                       for line in listing):
                    raise AcceptanceStop(f"map-only flag left Level up enabled; kept {listed}")
            self.summary.setdefault("flags", {})[name] = row(
                "awaiting image review", observed=controls,
                evidence=[str(listed), str(picture), str(picture) + ".json"])
            self.log("flags", mode=name, controls=controls, picture=str(picture))
        self._game_section()

    def _answer_journal(self) -> None:
        from tools.amiga import route_silver_blades  # noqa: PLC0415

        if self.route.title != "ssb":
            raise AcceptanceStop("journal answer is only defined for Silver Blades")
        disk = next(m.path for m in self.route.media if m.key == self.route.mounted[0])
        if self.discovery:
            self.summary["challenge_key_count"] = None
            self.summary["challenge_key_count_verified"] = False
            self.log("journal_answer", challenge_key_count=None, verified=False)
        code, answer = route_silver_blades.run_journal_answer(
            sys.executable, self.args.holder, disk, self.left(60))
        if code:
            raise AcceptanceStop(f"journal was not answered: {answer}")

    def run_phase(self, phase: Any, action_context: Any = None,
                  namespace: str | None = None) -> None:
        if not phase.ready:
            raise AcceptanceStop(f"{phase.name} is unready: {phase.reason}")
        self._game_section()
        last_frame = self._await(phase.initial_state, limit=self.route.amiga_title.wait_limits.get(
            phase.initial_state, self.route.amiga_title.title_limit))
        for step in phase.steps:
            kind = step.kind
            if kind in ("key", "turn", "move"):
                self._press(step.key, action=action_context is not None or namespace == "original_slot_reload")
            elif kind == "insert":
                medium = next(m for m in self.route.media if m.key == step.media)
                self.game.insert(self.args.holder, step.drive, self.remotes[step.media],
                                 self.left(60), medium.sha256)
                self._press(step.key, action=action_context is not None or namespace == "original_slot_reload")
            elif kind == "snapshot":
                if self.discovery or self.encounters_on:
                    self._switch(False)
                self.game.snapshot(step.snapshot, self.args.holder)
                if self.discovery and step.snapshot == DISCOVERY_SNAPSHOT:
                    self.discovery_snapshot = True
            elif kind == "restore":
                if self.encounters_on:
                    self._switch(False)
                self.game.restore(step.snapshot, self.args.holder)
            elif kind == "encounters":
                self._switch(step.encounters)
            elif kind == "answer":
                self._answer_journal()
            elif kind == "select":
                if action_context is None:
                    raise AcceptanceStop("member selection outside an action")
                from automap import amiga  # noqa: PLC0415
                from tools.amiga import amigatarget  # noqa: PLC0415

                layout = amiga.MACHINES[self.route.game_key]
                target = amigatarget.connect_pipe(self.args.holder, layout)
                selected = amigatarget.select(
                    target, layout, action_context["member"],
                    press=lambda key: self._press(key, action=True),
                    wait=lambda: self.sleep(self.left(1)))
                target.close()
                if selected.get("error"):
                    raise AcceptanceStop(f"member selection: {selected['error']}")
                action_context.setdefault("selections", []).append(selected)
            elif kind != "observe":
                raise AcceptanceStop(f"unknown route step kind {kind}")
            frame = self._await(step.state, limit=self.route.amiga_title.wait_limits.get(
                step.state, 90))
            last_frame = frame
            if step.checkpoint:
                expected = step.expected
                if namespace and expected and expected.compare_to:
                    from dataclasses import replace  # noqa: PLC0415

                    local = {s.checkpoint for s in phase.steps if s.checkpoint}
                    if action_context is not None:
                        local.update(action_context.get("visit_checkpoints", ()))
                    if expected.compare_to in local:
                        expected = replace(expected, compare_to=f"{namespace}.{expected.compare_to}")
                self._checkpoint(f"{namespace}.{step.checkpoint}" if namespace else step.checkpoint,
                                 expected, frame)
                if action_context is not None:
                    action_context.setdefault("visit_checkpoints", set()).add(step.checkpoint)
        if action_context is not None and namespace:
            self._checkpoint(f"{namespace}.{phase.name}_end", None, last_frame)
        self.summary["completed_sequence"].append(
            f"{namespace}.{phase.name}" if namespace else phase.name)

    def _fresh_party(self):
        from automap import amiga, amigaparty  # noqa: PLC0415
        from tools.amiga import amigatarget  # noqa: PLC0415

        target = amigatarget.connect_pipe(self.args.holder, amiga.MACHINES[self.route.game_key])
        party = amigaparty.read_party(target)
        if not party:
            target.close()
            raise AcceptanceStop("no complete current party is readable")
        return target, party

    @staticmethod
    def _member_record(member: Any) -> dict[str, Any]:
        return {"slot": member.slot, "name": member.name, "address": member.address,
                "raw": member.raw.hex(), "items": [
                    [node.address, node.raw.hex()] for node in member.item_nodes]}

    def _action_input(self, action: Any) -> dict[str, Any]:
        """Stage only the plan's named input on a newly resolved member."""
        from automap import amigalevelup, amigaparty  # noqa: PLC0415

        target, party = self._fresh_party()
        before = [self._member_record(member) for member in party]
        choice = None
        try:
            candidates = []
            for member in sorted(party, key=lambda item: item.slot):
                if action.selector == "hp" and member.hp_max >= 6 and member.hp > 0:
                    choice = member
                elif action.selector == "memorised" and any(member.memorised()):
                    choice = member
                elif action.selector == "item" and member.item_nodes:
                    choice = member
                elif action.selector == "controlled" and (member.row.control is None or
                        not member.row.control.value(member.raw)):
                    choice = member
                elif action.selector == "pod_levelup":
                    levels = amigalevelup.summary(member.raw, self.route.game_key)["levels"]
                    fighter = amigalevelup.POD_SLOTS.index("fighter")
                    if levels[fighter] > 0:
                        threshold = amigalevelup.pod_threshold(fighter, levels[fighter] + 1)
                        staged = bytearray(member.raw)
                        staged[amigalevelup._POD_EXPERIENCE:amigalevelup._POD_EXPERIENCE + 4] = (
                            threshold.to_bytes(4, "big"))
                        if "fighter" in amigalevelup.ready_classes(staged, self.route.game_key):
                            candidates.append(member)
                if choice is not None:
                    break
            if action.selector == "pod_levelup":
                eligible = [member for member in party if
                            amigalevelup.ready_classes(member.raw, self.route.game_key)]
                if eligible or not candidates:
                    raise AcceptanceStop("Level up has an existing eligible member or no ready fighter")
                choice = candidates[0]
            if choice is None:
                raise AcceptanceStop(f"no existing input for {action.selector}")
            context: dict[str, Any] = {"member": choice.name, "slot": choice.slot,
                                       "before": before}
            if action.kind == "heal":
                spot = choice.row.hp
                value = choice.hp_max - 5
                target.write(choice.address + spot.offset, value.to_bytes(spot.length, "big"))
                context["staged"] = {"hp": value}
            elif action.kind == "spells":
                index = next(i for i, value in enumerate(choice.memorised()) if value)
                context["spell_index"] = index
            elif action.kind == "identify":
                node = choice.item_nodes[0]
                spot = choice.row.hidden
                byte = node.raw[spot.offset]
                value = byte | spot.mask
                target.write(node.address + spot.offset, bytes([value]))
                context["staged"] = {"item_address": node.address,
                                      "hidden_before": byte, "hidden_staged": value}
            elif action.kind == "quickfight":
                spot = choice.row.quickfight
                if spot is None:
                    raise AcceptanceStop("this title has no quickfight spot")
                target.write(choice.address + spot.offset, bytes([1]))
                context["staged"] = {"quickfight": 1}
            elif action.kind == "levelup":
                if self.route.title != "darkness":
                    raise AcceptanceStop("Level up is observed without a press on this title")
                levels = amigalevelup.summary(choice.raw, self.route.game_key)["levels"]
                fighter = amigalevelup.POD_SLOTS.index("fighter")
                threshold = amigalevelup.pod_threshold(fighter, levels[fighter] + 1)
                offset = amigalevelup._POD_EXPERIENCE
                target.write(choice.address + offset, threshold.to_bytes(4, "big"))
                context["staged"] = {"experience": threshold}
            staged_party = amigaparty.read_party(target)
            if not staged_party:
                raise AcceptanceStop("the staged party is not readable")
            context["baseline"] = [self._member_record(member) for member in staged_party]
            if action.kind == "levelup":
                staged_member = next(member for member in staged_party if member.slot == choice.slot)
                context["levelup_effects"] = [node.raw.hex() for node in staged_member.effect_nodes]
            self._verify_staging(action.kind, context, party)
            return context
        finally:
            target.close()

    @staticmethod
    def _party_by_slot(records: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        slots = {record["slot"]: record for record in records}
        if len(slots) != len(records):
            raise AcceptanceStop("party has repeated slots")
        return slots

    def _verify_staging(self, kind: str, context: dict[str, Any], party: Any) -> None:
        from automap import amigalevelup  # noqa: PLC0415

        original = self._party_by_slot(context["before"])
        staged = self._party_by_slot(context["baseline"])
        if original.keys() != staged.keys():
            raise AcceptanceStop("staging changed the party slots")
        slot = context["slot"]
        for member in party:
            old, new = original[member.slot], staged[member.slot]
            raw = bytearray.fromhex(old["raw"])
            items = [[address, data] for address, data in old["items"]]
            if member.slot == slot:
                if kind == "heal":
                    spot = member.row.hp
                    raw[spot.offset:spot.offset + spot.length] = context["staged"]["hp"].to_bytes(spot.length, "big")
                elif kind == "identify":
                    items[0][1] = (bytes.fromhex(items[0][1])[:member.row.hidden.offset]
                                   + bytes([context["staged"]["hidden_staged"]])
                                   + bytes.fromhex(items[0][1])[member.row.hidden.offset + 1:]).hex()
                elif kind == "quickfight":
                    raw[member.row.quickfight.offset] = 1
                elif kind == "levelup":
                    offset = amigalevelup._POD_EXPERIENCE
                    raw[offset:offset + 4] = context["staged"]["experience"].to_bytes(4, "big")
            if new["raw"] != raw.hex() or new["items"] != items or new["name"] != old["name"]:
                raise AcceptanceStop(f"staging changed an unexpected byte for {member.name}")

    def _verify_action(self, kind: str, context: dict[str, Any], after: list[dict[str, Any]],
                       *, step: str = "action") -> None:
        from automap import amigalevelup, amigaparty  # noqa: PLC0415

        baseline = self._party_by_slot(context["baseline"])
        actual = self._party_by_slot(after)
        if baseline.keys() != actual.keys():
            raise AcceptanceStop("action changed the party slots")
        row_ = amigaparty.ROWS[self.route.game_key]
        for slot, old in baseline.items():
            new = actual[slot]
            raw = bytearray.fromhex(old["raw"])
            items = [[address, data] for address, data in old["items"]]
            if kind == "heal":
                hp, maximum = row_.hp.value(raw), row_.hp_max.value(raw)
                if 0 < hp < maximum:
                    raw[row_.hp.offset:row_.hp.offset + row_.hp.length] = maximum.to_bytes(row_.hp.length, "big")
            elif kind == "identify":
                for node in items:
                    data = bytearray.fromhex(node[1])
                    data[row_.hidden.offset] &= ~row_.hidden.mask & 0xff
                    node[1] = data.hex()
            elif kind == "quickfight":
                if row_.control is None or not row_.control.value(raw) & 0x80:
                    raw[row_.quickfight.offset] = 0
            elif kind == "spells":
                if step == "cleared" and slot == context["slot"]:
                    raw[row_.memorised.offset + context["spell_index"]] = 0
            elif kind == "levelup":
                if slot == context["slot"]:
                    import random  # noqa: PLC0415
                    from types import SimpleNamespace  # noqa: PLC0415

                    if "levelup_effects" not in context:
                        raise AcceptanceStop("Level up has no staged effect-node readback")
                    member = SimpleNamespace(
                        raw=bytes(raw),
                        item_nodes=[SimpleNamespace(raw=bytes.fromhex(data)) for _, data in items],
                        effect_nodes=[SimpleNamespace(raw=bytes.fromhex(data))
                                      for data in context["levelup_effects"]])

                    class Die:
                        def __init__(self, high):
                            self.high = high

                        def randint(self, low, high):
                            return high if self.high else low

                    try:
                        fixed = amigalevelup.plan_member(member, self.route.game_key,
                                                        rng=random.Random(0))
                        minimum = amigalevelup.plan_member(member, self.route.game_key,
                                                          rng=Die(False))
                        maximum = amigalevelup.plan_member(member, self.route.game_key,
                                                          rng=Die(True))
                    except amigalevelup.CannotLevel as exc:
                        raise AcceptanceStop(f"Level up plan cannot verify: {exc}") from exc
                    ready = amigalevelup.ready_classes(raw, self.route.game_key)
                    if fixed.classes != ready or fixed.added_effects:
                        raise AcceptanceStop("Level up classes or effect-node writes cannot be verified")
                    hp_rolled = amigalevelup._POD_HP_ROLLED
                    hp_max = amigalevelup._POD_HP_MAX
                    hp_current = amigalevelup._POD_HP_CURRENT
                    observed = bytes.fromhex(new["raw"])
                    rolled = (observed[hp_rolled] - raw[hp_rolled]) & 0xff
                    low = (amigalevelup.apply_to(raw, minimum)[hp_rolled] - raw[hp_rolled]) & 0xff
                    high = (amigalevelup.apply_to(raw, maximum)[hp_rolled] - raw[hp_rolled]) & 0xff
                    if not low <= rolled <= high:
                        raise AcceptanceStop("Level up rolled hit points outside the trainer's dice")
                    predicted = bytearray(amigalevelup.apply_to(raw, fixed))
                    if any(at <= hp_rolled < at + len(data) for at, data in fixed.writes):
                        fixed_roll = (predicted[hp_rolled] - raw[hp_rolled]) & 0xff
                        bonus = (predicted[hp_max] - raw[hp_max] - fixed_roll) & 0xff
                        damage = (raw[hp_max] - raw[hp_current]) & 0xff
                        predicted[hp_rolled] = observed[hp_rolled]
                        predicted[hp_max] = (raw[hp_max] + bonus + rolled) & 0xff
                        predicted[hp_current] = (0 if damage > predicted[hp_max]
                                                 else predicted[hp_max] - damage)
                    raw = predicted
            if new["name"] != old["name"] or new["raw"] != raw.hex() or new["items"] != items:
                raise AcceptanceStop(f"{kind} changed unexpected bytes for {old['name']}")

    def _unique_action(self, label: str | None = None, automation_id: str | None = None,
                       *, context: dict[str, Any]) -> None:
        listing = winwish.ui(self.guest, self.args.holder, "controls")
        path = self.out / f"action-controls-{context['kind']}-{len(context['evidence']):02d}.txt"
        path.write_text("\n".join(listing) + "\n")
        context["evidence"].append(str(path))
        matches = [line for line in listing if len(parts := line.split("|")) >= 4
                   and ((automation_id is not None and parts[2] == automation_id)
                        or (label is not None and parts[1] == label))]
        if len(matches) != 1 or "enabled=True" not in matches[0]:
            raise AcceptanceStop(f"{label or automation_id}: absent, ambiguous or disabled; kept {path}")
        if context["kind"] == "levelup":
            enabled = [line for line in listing if "_level_up" in line and "enabled=True" in line]
            if enabled != matches:
                raise AcceptanceStop(f"Level up has another enabled card; kept {path}")
            if context["member"] not in matches[0]:
                raise AcceptanceStop(f"Level up card does not name {context['member']}; kept {path}")
        self._count(action=True)
        event = {"control": label or automation_id, "listing": str(path),
                 "acknowledged": False}
        context["clicks"].append(event)
        self.log("action_click_attempt", **event)
        try:
            winwish.ui(self.guest, self.args.holder, "click", (() if label is None else (label,)),
                       automation_id=automation_id)
        except Exception as exc:
            raise AcceptanceStop(f"action click returned no acknowledgement: {exc}") from exc
        event["acknowledged"] = True
        self.log("action_click", **event)

    def _action_readback(self) -> list[dict[str, Any]]:
        target, party = self._fresh_party()
        try:
            return [self._member_record(member) for member in party]
        finally:
            target.close()

    def _action_visit(self, action: Any, context: dict[str, Any], label: str) -> None:
        namespace = f"{action.kind}.{label}"
        context["visit_checkpoints"] = set()
        before = set(self.checkpoints)
        frames_before = set(self.out.glob("game-*.raw.png"))
        try:
            self.run_phase(action.show, context, namespace=namespace)
            self.run_phase(action.back, context, namespace=namespace)
        finally:
            context["evidence"].extend(name for name in self.checkpoints if name not in before)
            context["evidence"].extend(str(path) for path in sorted(
                set(self.out.glob("game-*.raw.png")) - frames_before))

    def run_actions(self) -> None:
        labels = {"heal": "Heal party", "identify": "Identify",
                  "quickfight": "Quickfight off"}
        for action in self.route.actions:
            if not action.enabled:
                self.summary["actions"][action.kind]["reason"] = "observation only on this route"
                continue
            context = {"kind": action.kind, "evidence": [], "clicks": []}
            result = self.summary["actions"][action.kind]
            result["evidence"] = context["evidence"]
            result["observed"] = context
            try:
                if action.show is None or action.back is None:
                    raise AcceptanceStop("the game-display route is incomplete")
                self._game_section()
                context.update(self._action_input(action))
                context["kind"] = action.kind
                context["staged_readback"] = self._action_readback()
                self._action_visit(action, context, "before")
                self._map_section()
                if action.kind == "spells":
                    self._unique_action("Save spells", context=context)
                    self._game_section()
                    context["saved"] = self._action_readback()
                    self._verify_action("spells", context, context["saved"])
                    self._game_section()
                    target, party = self._fresh_party()
                    try:
                        member = next(m for m in party if m.slot == context["slot"])
                        offset = member.row.memorised.offset + context["spell_index"]
                        target.write(member.address + offset, b"\x00")
                    finally:
                        target.close()
                    context["cleared"] = self._action_readback()
                    self._verify_action("spells", context, context["cleared"], step="cleared")
                    self._action_visit(action, context, "cleared")
                    self._map_section()
                    self._unique_action("Restore spells", context=context)
                elif action.kind == "levelup":
                    self._unique_action(automation_id=f"card_{context['slot']}_level_up", context=context)
                else:
                    self._unique_action(labels[action.kind], context=context)
                self._game_section()
                context["after"] = self._action_readback()
                self._verify_action(action.kind, context, context["after"])
                self._action_visit(action, context, "after")
                result["status"] = "awaiting image review"
                result["expected"] = context.get("staged")
            except AcceptanceStop as exc:
                result["reason"] = str(exc)
                raise

    @staticmethod
    def _without_addresses(records: list[dict[str, Any]], row_: Any) -> list[dict[str, Any]]:
        normalized = []
        for record in records:
            raw = bytearray.fromhex(record["raw"])
            for offset in row_.pointers:
                raw[offset:offset + 4] = b"\x00" * 4
            items = []
            for _, value in record["items"]:
                node = bytearray.fromhex(value)
                node[row_.items.link:row_.items.link + 4] = b"\x00" * 4
                items.append(node.hex())
            normalized.append({"slot": record["slot"], "name": record["name"],
                               "raw": raw.hex(), "items": items})
        return sorted(normalized, key=lambda item: item["slot"])

    def _final_reload(self) -> None:
        from automap import amigaparty  # noqa: PLC0415

        self.summary["original_slot_reload"]["status"] = "unproven"
        initial = self.checkpoints.get("loaded", {}).get("observed")
        if not initial or initial.get("fix") is None or initial.get("party") is None:
            raise AcceptanceStop("the original loaded party and location were not recorded")
        reload_phase = next(phase for phase in self.route.phases if phase.name == "reload")
        self.run_phase(reload_phase, namespace="original_slot_reload")
        last = [name for name in self.checkpoints if name.startswith("original_slot_reload.")]
        if not last:
            raise AcceptanceStop("the original-slot reload has no checkpoint")
        final = self.checkpoints[last[-1]]["observed"]
        result = self.summary["original_slot_reload"]
        result["expected"] = initial
        result["observed"] = final
        result["evidence"] = last
        row_ = amigaparty.ROWS[self.route.game_key]
        if (final["fix"] != initial["fix"] or
                final["geo_sha256"] != initial["geo_sha256"] or
                final["party"] is None or
                self._without_addresses(final["party"], row_) !=
                self._without_addresses(initial["party"], row_)):
            result["reason"] = "original-slot reload changed location or party bytes"
            raise AcceptanceStop(result["reason"])
        result["status"] = "awaiting image review"

    def _stage_media(self) -> None:
        for medium in self.route.media:
            remote = self.game.remote_path(self.route.amiga_title.issue,
                                           self.args.holder, medium.key)
            self.game.put(medium.path, remote, timeout=self.left(60))
            self.remotes[medium.key] = remote
            self.info["media"][medium.key]["guest"] = remote

    def _up(self) -> None:
        self._stage_media()
        values = {"sha": self.args.sha, "holder": self.args.holder,
                  "mute_proof": self.args.mute_proof,
                  "df0": None, "df1": None, "df2": None, "df3": None,
                  "game": self.route.game_key, "zip": str(self.zipped),
                  "uae_option": list(self.route.amiga_title.options),
                  "travel_targets": [], "no_flag": False, "map_only": self.discovery,
                  "wait_lanes": 0, "keep_lanes": False}
        for index, key in enumerate(self.route.mounted):
            values[f"df{index}"] = self.remotes[key]
        receipt = winwish.up(self.guest, self.lane, argparse.Namespace(**values))
        self.booted = True
        self.game.holder = self.args.holder
        self.log("up", receipt=receipt)

    def _cleanup(self) -> None:
        if self.discovery:
            self._cleanup_discovery()
            return
        failures = []
        if self.encounters_on:
            try:
                self._game_section()
                self._switch(False)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"encounters: {exc}")
        if self.booted:
            try:
                self._game_section()
                self.game._pipe = None
            except Exception as exc:  # noqa: BLE001
                failures.append(f"pipe: {exc}")
            try:
                self.summary["cleanup"]["logs"] = winwish.collect_log(
                    self.guest, self.args.holder, self.out / "logs")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"logs: {exc}")
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
            try:
                self.summary["cleanup"]["down"] = winwish.down(
                    self.guest, self.lane, self.args.holder)
                self.down_done = True
            except Exception as exc:  # noqa: BLE001
                failures.append(f"down: {exc}")
                try:
                    self.summary["cleanup"]["down_retry"] = winwish.down(
                        self.guest, self.lane, self.args.holder)
                    self.down_done = True
                except Exception as retry:  # noqa: BLE001
                    failures.append(f"down retry: {retry}")
            try:
                status = self.lane.status(30)
                self.summary["cleanup"]["lane_status"] = status
                if self.args.holder in status:
                    failures.append(f"holder {self.args.holder} remains in lane status")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"lane status: {exc}")
        for medium in self.route.media:
            try:
                self.info["media"][medium.key]["source_after_sha256"] = digest(medium.path)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"source medium {medium.key}: {exc}")
        self.summary["cleanup"]["errors"] = failures
        try:
            self.log("cleanup", errors=failures)
        except OSError as exc:
            failures.append(f"event log: {exc}")

    def _cleanup_discovery(self) -> None:
        """Reserve teardown time before optional transfer of working media."""
        failures = []
        cleanup = self.summary["cleanup"]
        if self.encounters is not None:
            try:
                persistent = self.encounters.state.load()
                cleanup["encounters_before"] = persistent
                if persistent["on"] or persistent["rows"] or self.encounters_on:
                    self._game_section()
                    self._switch(False)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"encounters: {exc}")
        if self.discovery_snapshot and self.summary["failure"]:
            try:
                if self.encounters is not None:
                    state = self.encounters.state.load()
                    if state["on"] or state["rows"]:
                        raise AcceptanceStop("cannot restore with encounter suppression outstanding")
                self._game_section()
                self.game.restore(DISCOVERY_SNAPSHOT, self.args.holder)
                from automap import amiga  # noqa: PLC0415
                from tools.amiga import amigatarget  # noqa: PLC0415

                target = amigatarget.connect_pipe(self.args.holder,
                                                   amiga.MACHINES[self.route.game_key])
                try:
                    fix = target.fix()
                    geo = target.geo()
                    area = self._area_of(geo) if geo is not None else None
                    restored = {"area": area, "x": fix.x, "y": fix.y,
                                "facing": fix.facing} if fix is not None else None
                finally:
                    target.close()
                cleanup["restored_fix"] = restored
                if restored != {"area": 16, "x": 3, "y": 3, "facing": 2}:
                    raise AcceptanceStop(f"restored fix is not 16,3,3,S: {restored}")
                cleanup["restored"] = True
            except Exception as exc:  # noqa: BLE001
                failures.append(f"restore: {exc}")

        def allowed(timeout: float, reserve: float = 0) -> float:
            seconds = min(timeout, self.total_end - self.clock() - reserve)
            if seconds <= 0:
                raise RouteError("discovery cleanup has no time before the holder release reserve")
            return seconds

        if self.booted:
            try:
                self._game_section()
                self.game._pipe = None
            except Exception as exc:  # noqa: BLE001
                failures.append(f"pipe: {exc}")

            owner = self

            class BoundedLane:
                def stop(self, holder: str, timeout: float) -> Any:
                    return owner.lane.stop(holder, allowed(timeout, 60))

                def release(self, holder: str, timeout: float) -> Any:
                    return owner.lane.release(holder, allowed(timeout))

            bounded_guest = winwish.Guest(
                run=lambda command, timeout: self.guest.run(command, allowed(timeout, 120)))
            try:
                cleanup["down"] = winwish.down(bounded_guest, BoundedLane(), self.args.holder)
                self.down_done = True
            except Exception as exc:  # noqa: BLE001
                failures.append(f"down: {exc}")
            try:
                status = self.lane.status(allowed(30))
                cleanup["lane_status"] = status
                if self.args.holder in status:
                    failures.append(f"holder {self.args.holder} remains in lane status")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"lane status: {exc}")
            if not self.down_done or "lane_status" not in cleanup or self.args.holder in cleanup["lane_status"]:
                failures.append(f"holder {self.args.holder} release is unverified")
            for medium in self.route.media:
                if medium.key not in self.remotes:
                    failures.append(f"working medium {medium.key}: no staged copy")
                    continue
                try:
                    copied = self.out / f"working-{medium.key}.adf"
                    self.game.get(self.remotes[medium.key], copied, timeout=allowed(60))
                    self.info["media"][medium.key]["guest_working_sha256"] = digest(copied)
                    self.info["media"][medium.key]["guest_working_copy"] = str(copied)
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"working medium {medium.key}: {exc}")
        for medium in self.route.media:
            try:
                after = digest(medium.path)
                self.info["media"][medium.key]["source_after_sha256"] = after
                if after != medium.sha256:
                    failures.append(f"source medium {medium.key} changed")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"source medium {medium.key}: {exc}")
        if self.clock() > self.total_end:
            failures.append("the 1800-second total budget was exceeded during cleanup")
        try:
            self.log("cleanup", errors=failures)
        except OSError as exc:
            failures.append(f"event log: {exc}")
        cleanup["errors"] = failures
        if failures:
            if self.summary["failure"] is None:
                self.summary["failure"] = "Cleanup: " + "; ".join(failures)
            discovery = self.summary["discovery"]
            discovery["status"] = "failed"
            discovery["reason"] = self.summary["failure"]

    def _capture_unknown_frames(self, state: str, prefix: str, end: float) -> dict[str, Any]:
        frames = self.summary["discovery"]["evidence"]
        for number in range(3):
            remaining = end - self.clock()
            if remaining <= 0:
                if not frames:
                    raise AcceptanceStop("no terminal pipe frame within five seconds")
                break
            raw = self.out / f"{prefix}-{number}.raw.png"
            crop = self.out / f"{prefix}-{number}.png"
            previous = self.game.last_shot
            try:
                exact = self.game.grab(state, raw, crop, remaining)
            except Exception as exc:
                if raw.is_file():
                    current = self.game.last_shot
                    partial = {"raw": str(raw), "crop": None,
                               "shot_source": current.copy() if isinstance(current, dict)
                               and current is not previous else None,
                               "error": f"{type(exc).__name__}: {exc}"}
                    frames.append(partial)
                    self.log("terminal_frame", **partial)
                raise
            current = self.game.last_shot
            source = current.copy() if isinstance(current, dict) and current is not previous else None
            frame = {"raw": str(raw), "crop": str(crop) if exact else None,
                     "shot_source": source}
            frames.append(frame)
            self.log("terminal_frame", **frame)
            if exact and (source is None or source.get("source") != "winuae-pipe"
                          or type(source.get("pid")) is not int or source["pid"] <= 0
                          or type(source.get("counter")) is not int or source["counter"] <= 0):
                raise AcceptanceStop("exact terminal crop has no fresh valid pipe shot provenance")
        if not frames or self.clock() > end:
            raise AcceptanceStop("terminal pipe frames exceeded five seconds")
        exact_frames = [frame for frame in frames if frame["crop"] is not None]
        if not exact_frames:
            raise AcceptanceStop("no exact terminal crop; raw pipe frames retained")
        return exact_frames[-1]

    def run_opening_first(self) -> dict[str, Any]:
        """Stop after one RETURN on the independently pinned first opening page."""
        self.summary["discovery"] = row()
        self.summary["challenge_key_count"] = None
        self.summary["challenge_key_count_verified"] = False
        try:
            phase = _opening_first_phase(self.route)
            if getattr(self.args, "discover", None) != "ssb-opening-first":
                raise AcceptanceStop("opening discovery mode is required")
            if getattr(self.guards, "rules", {}).get("ssb_opening_first") != OPENING_FIRST_RULE:
                raise AcceptanceStop("opening discovery needs the independent exact two-box guard")
            self._up()
            self._game_section()
            title = self._await("title", limit=300)
            self.summary["mapping"]["title"] = row("awaiting image review", evidence=[title])
            self.run_phase(phase)
            self._answer_journal()
            self._await("ssb_opening_first", limit=300)
            self._press("RET")
            end = min(self.clock() + 5, self.route_end)
            frame = self._capture_unknown_frames("ssb_opening_unknown", "opening", end)
            self._checkpoint("ssb_opening_after_first", None, frame)
            if self.checkpoints.get("ssb_opening_after_first", {}).get(
                    "observed", {}).get("fix") is None:
                raise AcceptanceStop("the game fix was not readable")
            self.summary["discovery"]["status"] = "awaiting image review"
            self.summary["discovery"]["reason"] = "Opening image identification and mapping remain unproven"
        except BaseException as exc:
            self.summary["failure"] = f"{type(exc).__name__}: {exc}"
            self.log("failure", error=self.summary["failure"])
            self.summary["discovery"]["status"] = "failed"
            self.summary["discovery"]["reason"] = self.summary["failure"]
        finally:
            self._cleanup()
            (self.out / "summary.json").write_text(json.dumps(self.summary, indent=2, default=str) + "\n")
        return self.summary

    def run_discovery(self) -> dict[str, Any]:
        """Observe the first unknown leave-town frame without pressing its prompt."""
        self.summary["discovery"] = row()
        self.summary["challenge_key_count"] = None
        self.summary["challenge_key_count_verified"] = False
        try:
            phases = _discovery_phases(self.route)
            self._up()
            self._game_section()
            title = self._await("title", limit=300)
            self.summary["mapping"]["title"] = row("awaiting image review", evidence=[title])
            for name in ("load", "stationary", "walk"):
                self.run_phase(phases[name])
                self.summary["mapping"][name] = row("awaiting image review")
            if self.encounters is None or self.encounters_on:
                raise AcceptanceStop("terminal encounter suppression was not verified off")
            state = self.encounters.state.load()
            if state["on"] or state["rows"]:
                raise AcceptanceStop(f"terminal encounter suppression remains active: {state}")
            if self.checkpoints.get("ssb_facing_exit", {}).get("comparison", {}).get(
                    "status") != "awaiting image review":
                raise AcceptanceStop("terminal 15,8,E checkpoint is not verified")
            self.game.snapshot("ssb_leave_terminal", self.args.holder)
            terminal_start = self.clock()
            self._press("NP8")
            end = min(terminal_start + 5, self.route_end)
            frame = self._capture_unknown_frames("ssb_leave_unknown", "leave", end)
            discovery = self.summary["discovery"]
            self._checkpoint("ssb_leave_terminal", None, frame)
            discovery["status"] = "awaiting image review"
            discovery["reason"] = "Prompt identification and mapping remain unproven"
        except BaseException as exc:
            self.summary["failure"] = f"{type(exc).__name__}: {exc}"
            self.log("failure", error=self.summary["failure"])
            self.summary["discovery"]["status"] = "failed"
            self.summary["discovery"]["reason"] = self.summary["failure"]
        finally:
            self._cleanup()
            (self.out / "summary.json").write_text(json.dumps(self.summary, indent=2, default=str) + "\n")
        return self.summary

    def run_title(self) -> dict[str, Any]:
        try:
            self._up()
            self._game_section()
            title = self._await("title", limit=300)
            self.summary["mapping"]["title"] = row("awaiting image review", evidence=[title])
            _phase_map(self.route)
            for phase in self.route.phases:
                name = phase.name
                if name == "reopen_step":
                    self._map_section()
                    winwish.stop_wish(self.guest, self.args.holder)
                    self.wish_closed = True
                self.run_phase(phase)
                label = "reopen" if name == "reopen_step" else name
                if label in self.summary["mapping"]:
                    self.summary["mapping"][label] = row("awaiting image review")
                if name == "load":
                    self.flag_controls()
            self.run_actions()
            if any(action.enabled for action in self.route.actions):
                self._game_section()
                self._await("world")
                self._final_reload()
            self._map_section()
            self.lane.stop(self.args.holder, self.left(60))
            pictures = []
            for index, delay in enumerate((0, 15, 30)):
                if delay:
                    self.sleep(self.left(delay))
                path = self.out / f"disconnect-{index}.png"
                winwish.shot(self.guest, self.args.holder, "wish", path)
                pictures.append(str(path))
            self.summary["mapping"]["disconnect"] = row(
                "awaiting image review", evidence=pictures)
        except BaseException as exc:
            self.summary["failure"] = f"{type(exc).__name__}: {exc}"
            self.log("failure", error=self.summary["failure"])
            incomplete = next((name for name, result in self.summary["mapping"].items()
                               if result["status"] == "unproven"), None)
            if incomplete:
                self.summary["mapping"][incomplete]["reason"] = self.summary["failure"]
        finally:
            self._cleanup()
            (self.out / "summary.json").write_text(json.dumps(self.summary, indent=2, default=str) + "\n")
        return self.summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", choices=("pool", "curse", "ssb", "darkness"), required=True)
    parser.add_argument("--discover", choices=("ssb-leave", "ssb-opening-first"))
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--holder", required=True)
    parser.add_argument("--mute-proof", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--deadline", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.deadline is None:
        args.deadline = DISCOVERY_SECONDS if args.discover else MAX_SECONDS
    from tools.amiga.maproute import route_for  # noqa: PLC0415

    guest, lane, game = winwish.Guest(), WinGuest(), WinGuest()
    try:
        route, guards, zipped, info = preflight(args, guest=guest, route_for=route_for)
        controller = Controller(args, guest=guest, lane=lane, game=game, guards=guards,
                                route=route, zipped=zipped, info=info)
        result = (controller.run_opening_first() if args.discover == "ssb-opening-first"
                  else controller.run_discovery() if args.discover else controller.run_title())
    except (AcceptanceStop, RouteError, winwish.WinwishError, OSError, ValueError) as exc:
        print(f"winwishaccept: {exc}", file=sys.stderr)
        return 2
    return 1 if result["failure"] or result["cleanup"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
