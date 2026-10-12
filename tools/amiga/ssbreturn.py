#!/usr/bin/env python3
"""Prove four Silver Blades Returns from New Verdigris, a camp save and its reload, in guarded WinUAE lanes.

One lane loads the prepared slot D party in New Verdigris, snapshots it, and makes
each Return from that snapshot: into the castle gates (82), the temple level of the
mines (51), the Frost giant village (81) and the Temple of Tyr (52). Each Return must
land on the area's normal entrance, then take one switched NP8 step. The Temple
Return goes last; its party camps and saves to slot B, the lane halts with its disks
fetched, and a second boot loads that save and reads the party's square.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import pathlib
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import (  # noqa: E402
    acceptance,
    amigabladesjournal,
    fasttravelrun,
    noencounters,
    route_silver_blades,
)
from tools.amiga import ssbneighbour as nb  # noqa: E402
from tools.amiga.screens import PixelGuards  # noqa: E402
from tools.amiga.staging import _verified_disk, sha256  # noqa: E402
from tools.amiga.winuaesession import RouteError, WinGuest, terminating  # noqa: E402

TITLE = nb.TITLE
VARIABLES = {0x4C62, 0x4C2A, 0x4CFD, 0x4CFE, 0x4C6A, 0x4C6C, 0x4C6D, 0x4C6F}
START = (16, (3, 7, 2))
#: The ticket as `AmigaTitle` and the VM disk names take it: the bare number.
ISSUE = "367"
SAVE_LETTER = "B"
SAVED = {"area": 52, "x": 7, "y": 1, "facing": 2}
STEP_AFTER_SAVE = (7, 2, 2)
GUARDS_NEEDED = {"title", "party_menu", "load_picker", "loaded_menu", "journal", "world",
                 "camp", "camp_save_picker", "exit_game", "giants_menu", "village_keys_page",
                 "village_teleporter_page"}


@dataclasses.dataclass(frozen=True)
class Return:
    """One Return from New Verdigris: its child flags, the keys its arrival takes and where it lands.

    `landing` is the area's normal entrance, read in the child's first poll that sees
    `dest`; `end` is the area and square once the arrival keys are answered, and `step`
    the square one NP8 later. `keys` go to the child, which presses each only on a frame
    showing the PRESS RETURN bar. `guarded` are (screen, key) pairs this driver presses
    itself after the child, each only once that screen's own guard matches; the child
    then stops unsettled on the first of those screens.
    """

    dest: int
    waypoint: str
    keys: tuple[str, ...]
    peek: str
    areas: tuple[int, ...]
    landing: tuple[int, int, int]
    end: tuple[int, tuple[int, int, int]]
    step: tuple[int, int, int]
    guarded: tuple[tuple[str, str], ...] = ()

    def flags(self) -> list[str]:
        answers = [flag for key in self.keys for flag in ("--arrival-answer", key)]
        return ["--waypoint", self.waypoint, "--back", *answers, "--peek-var", self.peek]


#: The order is fixed: the Temple goes last, because its party is the one that saves.
RETURNS = (
    Return(82, "82,5,5,1", (), "4CFD,4CFE,4C6C,4C6D", (16, 82),
           (1, 11, 1), (82, (1, 11, 1)), (2, 11, 1)),
    # "You have reached the temple level" over PRESS RETURN.
    Return(51, "51,8,8,1", ("Return",), "4CFD,4CFE,4C6A,4C6F", (16, 51),
           (3, 3, 1), (51, (3, 3, 1)), (4, 3, 1)),
    # The giants' ATTACK/TALK/LEAVE menu has no PRESS RETURN bar, so LEAVE and the two
    # pages after it are pressed here behind their own guards; LEAVE ends in 80.
    Return(81, "81,5,8,1", (), "4CFD,4CFE,4C6C,4C6D", (16, 81),
           (0, 8, 1), (80, (3, 5, 3)), (2, 5, 3),
           (("giants_menu", "L"), ("village_keys_page", "RET"),
            ("village_teleporter_page", "RET"))),
    # Two Temple of Tyr pages, each over PRESS RETURN.
    Return(52, "52,7,3,2", ("Return", "Return"), "4CFD,4CFE", (16, 52),
           (7, 0, 2), (52, (7, 0, 2)), (7, 1, 2)),
)


def _events(log: pathlib.Path) -> list[dict]:
    try:
        rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        raise RouteError(f"the child log {log} is unreadable: {exc}") from exc
    return [row for row in rows if isinstance(row, dict)]


def return_leg(run: nb.GuardedRun, disks: pathlib.Path, out: pathlib.Path, leg: Return) -> dict:
    """Run one Return child and accept it only as `leg` describes it.

    Every arrival key must be logged on a frame the title's continue guard matched, and the
    first poll in the destination must read the area's normal entrance. A leg with
    `guarded` keys must stop unsettled in its destination with no key pressed.
    """
    out.mkdir()
    command = [sys.executable, str(pathlib.Path(fasttravelrun.__file__)),
               "--holder", run.holder, "--disks", str(disks), "--title", TITLE,
               "--measure-row", "--budget", "300", "--out", str(out), *leg.flags()]
    code, stdout, stderr = nb.run_child(run, out, command)
    rows = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
    pending = bool(leg.guarded)
    waiting = nb.WELL_PENDING_STDERR.replace("area 33", f"area {leg.dest}")
    nb.require(code == 0 if not pending else (code == 1 and stderr == waiting),
               f"Return into {leg.dest} stopped with {code}: {stderr[-500:]}")
    nb.require(len(rows) == 1 and isinstance(rows[0], dict), f"Return into {leg.dest} "
               f"did not print one result: {out}")
    result = rows[0]
    names = result.get("party_before")
    nb.require(result.get("result") == "idle" and result.get("settled") is not pending
               and result.get("areas_seen") == list(leg.areas)
               and result.get("arrival_keys") == list(leg.keys)
               and result.get("arrival_answered") is bool(leg.keys)
               and isinstance(names, list) and len(names) == 6
               and names == result.get("party_after"),
               f"Return into {leg.dest} diverged: {result}")
    events = _events(out / "fasttravel.jsonl")
    answers = [event for event in events if event.get("event") == "arrival_answer"]
    nb.require([event.get("key") for event in answers] == list(leg.keys)
               and all(event.get("at_continue") is True for event in answers),
               f"Return into {leg.dest}: an arrival key was not on the continue bar: {out}")
    landed = next((event for event in events if event.get("event") == "read"
                   and event.get("area") == leg.dest), None)
    nb.require(landed is not None and tuple(landed.get("square") or ()) == leg.landing,
               f"Return into {leg.dest} first read {landed}, not the entrance {leg.landing}")
    return {"command": command, "result": result, "landing": landed, "answers": answers,
            "stdout": str(out / "stdout.txt"), "stderr": str(out / "stderr.txt")}


def shots(root: pathlib.Path) -> dict[str, str]:
    """Every screenshot under `root`, by its relative path written with `/` on every OS, with its SHA-256."""
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*.png"))}


class Lane:
    """One booted lane: guarded load, readings, switched steps and cleanup."""

    def __init__(self, args, guest, guards, reader, switch_factory, receipt: dict,
                 holder: str, out: pathlib.Path, deadline: float):
        self.args, self.guest, self.guards, self.reader = args, guest, guards, reader
        self.switch_factory, self.receipt, self.holder = switch_factory, receipt, holder
        self.out, self.deadline = out, deadline
        self.state = noencounters.WinuaeState(noencounters.winuae_state_path(holder))
        self.switch = None
        self.snapshots: list[str] = []
        self.booted = False
        self.run: nb.GuardedRun | None = None
        self.local: pathlib.Path | None = None
        self.command: list[str] = []

    def boot(self, manifest: dict) -> dict:
        """Copy `manifest`'s disks beside this lane's output, mute, boot and load slot D."""
        self.out.mkdir(parents=True, exist_ok=True)
        copied = {key: self.out / f"{key}.adf" for key in ("df0", "df1")}
        for key, path in copied.items():
            shutil.copyfile(manifest["disks"][key]["path"], path)
            nb.require(sha256(path) == manifest["disks"][key]["sha256"],
                       f"the copied {key} hash differs")
        prepared = {**manifest, "disks": {key: {**manifest["disks"][key], "path": str(path)}
                                          for key, path in copied.items()}}
        self.local = self.out / "prepare.json"
        nb.write_json(self.local, prepared)
        proof = self.out / "mute.json"
        output = self.guest._run("ssh", acceptance.MUTE_READBACK,
                                 timeout=min(60, self.deadline - time.monotonic()))
        nb.write_json(proof, json.loads(output[output.index("{"):]))
        nb.require(self.guest.silence(proof), "the Windows playback endpoint did not read back muted")
        self.command = [str(pathlib.Path(__file__)), "--manifest", str(self.args.manifest),
                        "--holder", self.holder, "--out", str(self.args.out)]
        title = route_silver_blades.title_for_substitute(prepared)
        boot = acceptance.boot_lane(self.local, prepared, title, guest=self.guest,
                                    holder=self.holder, audio_proof=proof,
                                    wait_lane=self.args.wait_lane,
                                    timeout=min(300, self.deadline - time.monotonic()),
                                    command=self.command)
        self.booted = True
        run = self.run = nb.GuardedRun(self.guest, self.holder, self.out / "screens",
                                       self.guards, self.deadline)
        run.press("title", "P", 300)
        run.press("party_menu", "L")
        run.press("load_picker", "D")
        run.press("loaded_menu", "B")
        journal = "absent"
        if run.shows("journal", "journal-before-answer"):
            capture, press = self.guest.answer_io(self.holder)
            with nb.bounded_answer(run.left(180)):
                answered = amigabladesjournal.answer(self.holder, 1, copied["df0"],
                                                     capture=capture, press=press,
                                                     keep=self.out / "journal")
            nb.require(answered, "the journal answer did not finish")
            journal = "answered"
        return {"boot": boot, "journal": journal, "df0": copied["df0"]}

    def read(self, label: str, names: list[str], area: int,
             square: tuple[int, int, int]) -> dict:
        assert self.run is not None
        self.run.see("world", 60)
        reading = self.reader(self.holder)
        nb.check(reading, names, area, square)
        self.receipt["reads"][label] = nb.logged(reading)
        return reading

    def step(self, label: str, names: list[str], area: int,
             expected: tuple[int, int, int]) -> dict:
        """One NP8 with the encounter switch on, then off; the party must reach `expected`."""
        target = self.reader(self.holder)["target"]
        factory = self.switch_factory or (lambda target: noencounters.WinuaeEncounters(
            TITLE, target, state=self.state,
            lane_check=lambda: self.guest.lane(self.holder, timeout=30),
            press=lambda key: self.guest.press(self.holder, key, timeout=30)))
        self.switch = factory(target)
        on = self.switch.on()
        nb.require("error" not in on and "stopped" not in on, f"gate did not switch on: {on}")
        try:
            response = self.switch.keys(["NP8"])
            nb.require(response.get("pressed") == ["NP8"] and "error" not in response
                       and "stopped" not in response, f"NP8 did not go through: {response}")
            moved = self.read(label, names, area, expected)
        finally:
            off = self.switch.off()
            self.switch = None
            nb.require("error" not in off and not self.state.load()["on"]
                       and not self.state.load()["rows"], f"encounter gate did not restore: {off}")
        self.receipt.setdefault("switch", []).append({"label": label, "on": on, "key": response,
                                                      "off": off})
        return moved

    def snapshot(self, name: str) -> None:
        self.snapshots.append(name)
        self.guest.snapshot(name, self.holder)

    def halt(self, cleanup: list) -> dict | None:
        """Switch off, discard snapshots and halt with the disks fetched; errors go to `cleanup`."""
        if not self.booted:
            return None
        self.booted = False
        try:
            if self.state.load()["on"] or self.state.load()["rows"]:
                target = self.reader(self.holder)["target"]
                switch = self.switch or noencounters.WinuaeEncounters(
                    TITLE, target, state=self.state,
                    lane_check=lambda: self.guest.lane(self.holder, timeout=30))
                reply = switch.off()
                nb.require("error" not in reply, f"encounter cleanup did not restore: {reply}")
            nb.require(not self.state.load()["on"] and not self.state.load()["rows"],
                       "encounter journal remains active")
            cleanup.append({"holder": self.holder, "encounters": "off"})
        except Exception as exc:  # noqa: BLE001
            cleanup.append({"holder": self.holder, "encounters_error": str(exc)})
        for name in self.snapshots:
            try:
                self.guest.discard(name, self.holder)
                cleanup.append({"holder": self.holder, "discard": name})
            except Exception as exc:  # noqa: BLE001
                cleanup.append({"discard_error": f"{self.holder} {name}: {exc}"})
        self.snapshots = []
        try:
            return acceptance.halt_lane(self.guest, self.holder, manifest_path=self.local,
                                        command=self.command)
        except Exception as exc:  # noqa: BLE001
            cleanup.append({"halt_error": f"{self.holder}: {exc}"})
            return None


def read_slot(df0: pathlib.Path, letter: str) -> dict:
    return route_silver_blades._slot_reading(_verified_disk(df0), letter)


def run(args: argparse.Namespace, *, guest: WinGuest | None = None,
        guards: PixelGuards | None = None, reader=None, executor=return_leg,
        switch_factory=None, preparer=route_silver_blades.prepare_substitute,
        slot_reader=read_slot) -> dict:
    nb.require(0 <= args.wait_lane <= 300, "lane wait exceeds 300 seconds")
    nb.require(args.holder != args.reload_holder, "the reload boot needs its own holder")
    manifest, wall_deadline = nb.preflight(args.manifest, args.out, None, args.budget)
    args.out.mkdir(parents=True)
    deadline = time.monotonic() + min(args.budget, wall_deadline - time.time())
    reader = reader or (lambda holder: nb.read_live(holder, VARIABLES))
    receipt: dict[str, Any] = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": str(args.manifest.resolve()), "out": str(args.out.resolve()),
        "holders": [args.holder, args.reload_holder], "success": False, "cleanup": [],
        "returns": {}, "reads": {}}
    guest = guest or WinGuest()
    lanes: list[Lane] = []
    try:
        guard_file = args.out / "guards.json"
        nb.write_json(guard_file, json.loads(nb.GUARDS.read_text())["guards"])
        guards = guards or PixelGuards(guard_file)
        nb.require(GUARDS_NEEDED <= guards.rules.keys(), "Silver Blades Return guards are missing")
        names = manifest["names_a"]
        lane = Lane(args, guest, guards, reader, switch_factory, receipt, args.holder,
                    args.out / "lane", deadline)
        lanes.append(lane)
        receipt["boot"] = lane.boot(manifest)["boot"]
        lane.read("start", names, *START)
        lane.snapshot("s0")
        disks = pathlib.Path(manifest["boot_source"]["path"]).parent
        for number, leg in enumerate(RETURNS):
            if number:
                nb.require(not lane.state.load()["on"] and not lane.state.load()["rows"],
                           "encounter journal is not empty before restore")
                guest.restore("s0", args.holder)
                lane.read(f"restored-{leg.dest}", names, *START)
            child = executor(lane.run, disks, args.out / f"return-{leg.dest}", leg)
            entry = receipt["returns"][str(leg.dest)] = {"child": child, "guarded": []}
            for state, key in leg.guarded:
                lane.run.press(state, key)
                entry["guarded"].append({"screen": state, "key": key})
            entry["after"] = nb.logged(lane.read(f"{leg.dest}", names, *leg.end))
            entry["step"] = nb.logged(lane.step(f"{leg.dest}-step", names, leg.end[0], leg.step))
        nb.require(not lane.state.load()["on"] and not lane.state.load()["rows"],
                   "the encounter switch is still on before the save")
        assert lane.run is not None
        lane.run.press("world", "E")
        lane.run.press("camp", "S")
        lane.run.press("camp_save_picker", SAVE_LETTER)
        lane.run.press("exit_game", "N")
        lane.run.see("camp", 60)
        halted = receipt["halt"] = lane.halt(receipt["cleanup"])
        nb.require(halted is not None and "df0" in halted.get("fetched", {}),
                   "the first lane's disks were not fetched")
        saved_df0 = pathlib.Path(halted["fetched"]["df0"]["path"])
        slot = receipt["save"] = {"letter": SAVE_LETTER, "df0": halted["fetched"]["df0"],
                                  **slot_reader(saved_df0, SAVE_LETTER)}
        nb.require(not slot.get("missing") and "decode_error" not in slot
                   and slot.get("place") == SAVED
                   and [name.strip() for name in slot.get("names") or []] == names,
                   f"slot {SAVE_LETTER} is not the Temple party at 7,1 S: {slot}")

        reload_path = preparer(saved_df0, f"{args.out.name}-reload", letter=SAVE_LETTER,
                               issue=ISSUE, camp=("view 1",))
        reload_manifest = json.loads(pathlib.Path(reload_path).read_text())
        nb.require(reload_manifest.get("state_a") == SAVED
                   and reload_manifest.get("names_a") == names,
                   f"the reload manifest is not the saved party: {reload_path}")
        receipt["reload_manifest"] = str(reload_path)
        second = Lane(args, guest, guards, reader, switch_factory, receipt, args.reload_holder,
                      args.out / "reload", deadline)
        lanes.append(second)
        receipt["reload_boot"] = second.boot(reload_manifest)["boot"]
        reloaded = second.read("reloaded", names, SAVED["area"],
                               (SAVED["x"], SAVED["y"], SAVED["facing"]))
        receipt["reloaded"] = nb.logged(reloaded)
        receipt["reloaded_step"] = nb.logged(second.step("reloaded-step", names, SAVED["area"],
                                                         STEP_AFTER_SAVE))
        receipt["reload_halt"] = second.halt(receipt["cleanup"])
    except Exception as exc:  # noqa: BLE001 - recorded, then raised as RouteError after cleanup
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    except BaseException as exc:
        # An interrupt is recorded and cleaned up like any stop, then goes on as itself.
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        receipt["screens"] = [event for lane in lanes if lane.run is not None
                              for event in lane.run.events]
        for lane in lanes:
            halted = lane.halt(receipt["cleanup"])
            if halted is not None:
                receipt.setdefault("halts", []).append({"holder": lane.holder, **halted})
        try:
            original = json.loads(args.manifest.read_text())
            for key in ("boot_source", "disk_b_source", "substitute", "published_df1", "df0", "df1"):
                nb.require(sha256(pathlib.Path(original[key]["path"])) == original[key]["sha256"],
                           f"original {key} changed")
            receipt["source_hashes"] = "unchanged"
        except Exception as exc:  # noqa: BLE001
            receipt["cleanup"].append({"hash_error": str(exc)})
        try:
            receipt["shots"] = shots(args.out)
        except OSError as exc:
            receipt["cleanup"].append({"shots_error": str(exc)})
        errors = [item for item in receipt["cleanup"] if any(k.endswith("error") for k in item)]
        receipt["success"] = ("error" not in receipt and not errors
                              and receipt.get("halt") is not None
                              and receipt.get("reload_halt") is not None)
        receipt["remaining_budget"] = max(0, wall_deadline - time.time())
        nb.write_json(args.out / "receipt.json", receipt)
    if not receipt["success"]:
        raise RouteError(receipt.get("error", "cleanup failed") + f"; cleanup: {errors}")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--holder", required=True)
    parser.add_argument("--reload-holder", required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--budget", type=float, default=3600)
    parser.add_argument("--wait-lane", type=float, default=0)
    args = parser.parse_args(argv)
    try:
        with terminating():
            run(args)
    except (RouteError, OSError, ValueError, KeyError) as exc:
        print(f"ssbreturn: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
