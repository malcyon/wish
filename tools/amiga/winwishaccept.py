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
MAX_ACTION_COMMANDS = 30


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
    if args.deadline > MAX_SECONDS or args.deadline <= CLEANUP_SECONDS:
        raise AcceptanceStop(f"--deadline must be above {CLEANUP_SECONDS} and at most {MAX_SECONDS}")
    if not pathlib.Path(args.manifest).is_file():
        raise AcceptanceStop("the prepared manifest is missing")
    manifest = json.loads(pathlib.Path(args.manifest).read_text())
    route = route_for(args.title, manifest)
    _phase_map(route)
    if not winwish._mute_proof(pathlib.Path(args.mute_proof)):
        raise AcceptanceStop("the WinUAE audio mute proof is missing or stale")
    if len(route.mounted) > 4 or not route.mounted:
        raise AcceptanceStop("route has no initial media or has more than four drives")
    media = {item.key: item for item in route.media}
    if len(media) != len(route.media) or any(k not in media for k in route.mounted):
        raise AcceptanceStop("the route media keys are missing or repeated")
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
    missing = _states(route) - guards.rules.keys()
    if missing:
        raise AcceptanceStop("route has no measured guards for " + ", ".join(sorted(missing)))
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
        cap = MAX_ACTION_COMMANDS if action else MAX_MAPPING_COMMANDS
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
        from automap import amiga  # noqa: PLC0415

        if self.area_by_geo is None:
            self.area_by_geo = {}
            for medium in self.route.media:
                for key, area in amiga.load_maps(medium.path).items():
                    name = hashlib.sha256(area.to_bytes()).hexdigest()
                    self.area_by_geo.setdefault(name, set()).add(int(key[3:], 16))
        ids = self.area_by_geo.get(hashlib.sha256(resident).hexdigest(), set())
        return next(iter(ids)) if len(ids) == 1 else None

    def _compare_checkpoint(self, name: str, expected: Any,
                            engine: dict[str, Any]) -> dict[str, Any]:
        if expected is None:
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
            if fix.get("outdoors") and key in ("x", "y", "facing"):
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

    def run_phase(self, phase: Any, action_context: Any = None) -> None:
        if not phase.ready:
            raise AcceptanceStop(f"{phase.name} is unready: {phase.reason}")
        self._game_section()
        self._await(phase.initial_state, limit=self.route.amiga_title.wait_limits.get(
            phase.initial_state, self.route.amiga_title.title_limit))
        for step in phase.steps:
            kind = step.kind
            if kind in ("key", "turn", "move"):
                self._press(step.key, action=action_context is not None)
            elif kind == "insert":
                medium = next(m for m in self.route.media if m.key == step.media)
                self.game.insert(self.args.holder, step.drive, self.remotes[step.media],
                                 self.left(60), medium.sha256)
                self._press(step.key, action=action_context is not None)
            elif kind == "snapshot":
                if self.encounters_on:
                    self._switch(False)
                self.game.snapshot(step.snapshot, self.args.holder)
            elif kind == "restore":
                if self.encounters_on:
                    self._switch(False)
                self.game.restore(step.snapshot, self.args.holder)
            elif kind == "encounters":
                self._switch(step.encounters)
            elif kind == "answer":
                from tools.amiga import route_silver_blades  # noqa: PLC0415

                if self.route.title != "ssb":
                    raise AcceptanceStop("journal answer is only defined for Silver Blades")
                disk = next(m.path for m in self.route.media if m.key == self.route.mounted[0])
                code, answer = route_silver_blades.run_journal_answer(
                    sys.executable, self.args.holder, disk, self.left(60))
                if code:
                    raise AcceptanceStop(f"journal was not answered: {answer}")
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
            elif kind != "observe":
                raise AcceptanceStop(f"unknown route step kind {kind}")
            frame = self._await(step.state, limit=self.route.amiga_title.wait_limits.get(
                step.state, 90))
            if step.checkpoint:
                self._checkpoint(step.checkpoint, step.expected, frame)
        self.summary["completed_sequence"].append(phase.name)

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
        from automap import amigalevelup  # noqa: PLC0415

        target, party = self._fresh_party()
        before = [self._member_record(member) for member in party]
        choice = None
        try:
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
                        choice = member
                if choice is not None:
                    break
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
            return context
        finally:
            target.close()

    def _unique_action(self, label: str | None = None, automation_id: str | None = None) -> None:
        listing = winwish.ui(self.guest, self.args.holder, "controls")
        path = self.out / f"action-controls-{self.action_commands:02d}.txt"
        path.write_text("\n".join(listing) + "\n")
        matches = [line for line in listing if len(parts := line.split("|")) >= 4
                   and ((automation_id is not None and parts[2] == automation_id)
                        or (label is not None and parts[1] == label))]
        if len(matches) != 1 or "enabled=True" not in matches[0]:
            raise AcceptanceStop(f"{label or automation_id}: absent, ambiguous or disabled; kept {path}")
        self._count(action=True)
        winwish.ui(self.guest, self.args.holder, "click", (() if label is None else (label,)),
                   automation_id=automation_id)
        self.log("action_click", control=label or automation_id, listing=str(path))

    def _action_readback(self) -> list[dict[str, Any]]:
        target, party = self._fresh_party()
        try:
            return [self._member_record(member) for member in party]
        finally:
            target.close()

    def run_actions(self) -> None:
        labels = {"heal": "Heal party", "identify": "Identify",
                  "quickfight": "Quickfight off"}
        for action in self.route.actions:
            if not action.enabled:
                self.summary["actions"][action.kind]["reason"] = "observation only on this route"
                continue
            try:
                if action.show is None or action.back is None:
                    raise AcceptanceStop("the game-display route is incomplete")
                self._game_section()
                context = self._action_input(action)
                self._map_section()
                if action.kind == "spells":
                    self._unique_action("Save spells")
                    self._game_section()
                    target, party = self._fresh_party()
                    try:
                        member = next(m for m in party if m.slot == context["slot"])
                        offset = member.row.memorised.offset + context["spell_index"]
                        target.write(member.address + offset, b"\x00")
                        context["staged"] = {"spell_index": context["spell_index"],
                                              "memorised_byte": 0}
                    finally:
                        target.close()
                    self._map_section()
                    self._unique_action("Restore spells")
                elif action.kind == "levelup":
                    self._unique_action(automation_id=f"card_{context['slot']}_level_up")
                else:
                    self._unique_action(labels[action.kind])
                self._game_section()
                after = self._action_readback()
                self.run_phase(action.show, context)
                self.run_phase(action.back, context)
                self.summary["actions"][action.kind] = row(
                    "awaiting image review", expected=context.get("staged"),
                    observed={"before": context["before"], "after": after},
                    evidence=[name for name in self.checkpoints if name.startswith(action.kind)])
            except AcceptanceStop as exc:
                self.summary["actions"][action.kind] = row("unproven", reason=str(exc))
                raise

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
                  "travel_targets": [], "no_flag": False, "map_only": False,
                  "wait_lanes": 0, "keep_lanes": False}
        for index, key in enumerate(self.route.mounted):
            values[f"df{index}"] = self.remotes[key]
        receipt = winwish.up(self.guest, self.lane, argparse.Namespace(**values))
        self.booted = True
        self.game.holder = self.args.holder
        self.log("up", receipt=receipt)

    def _cleanup(self) -> None:
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

    def run_title(self) -> dict[str, Any]:
        try:
            self._up()
            self._game_section()
            title = self._await("title", limit=300)
            self.summary["mapping"]["title"] = row("awaiting image review", evidence=[title])
            phases = _phase_map(self.route)
            self.run_phase(phases["load"])
            self.summary["mapping"]["load"] = row("awaiting image review")
            self.flag_controls()
            for name in ("stationary", "walk", "transition", "outdoor", "reload", "reopen_step"):
                if name not in phases:
                    continue
                if name == "reopen_step":
                    self._map_section()
                    winwish.stop_wish(self.guest, self.args.holder)
                    self.wish_closed = True
                self.run_phase(phases[name])
                label = "reopen" if name == "reopen_step" else name
                if label in self.summary["mapping"]:
                    self.summary["mapping"][label] = row("awaiting image review")
            self.run_actions()
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
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--holder", required=True)
    parser.add_argument("--mute-proof", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--deadline", type=int, default=MAX_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    from tools.amiga.maproute import route_for  # noqa: PLC0415

    guest, lane, game = winwish.Guest(), WinGuest(), WinGuest()
    try:
        route, guards, zipped, info = preflight(args, guest=guest, route_for=route_for)
        result = Controller(args, guest=guest, lane=lane, game=game, guards=guards,
                            route=route, zipped=zipped, info=info).run_title()
    except (AcceptanceStop, RouteError, winwish.WinwishError, OSError, ValueError) as exc:
        print(f"winwishaccept: {exc}", file=sys.stderr)
        return 2
    return 1 if result["failure"] or result["cleanup"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
