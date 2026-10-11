#!/usr/bin/env python3
"""Prove two Silver Blades neighbour trips in one guarded WinUAE lane."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import amiga, amigaparty, amigatrip, amigavars, gamedisks  # noqa: E402
from tools.amiga import (  # noqa: E402
    acceptance,
    amigabladesjournal,
    fasttravelrun,
    noencounters,
    route_silver_blades,
)
from tools.amiga.screens import PixelGuards  # noqa: E402
from tools.amiga.staging import sha256  # noqa: E402
from tools.amiga.winuaesession import (  # noqa: E402
    RouteError,
    ShotTimedOut,
    WinGuest,
    terminating,
)

TITLE = "secret-of-the-silver-blades"
GUARDS = pathlib.Path(__file__).with_name("guards_silver_blades.json")
VARIABLES = {0x4C62, 0x4C2A, 0x4CFD, 0x4CFE, 0x4C6C, 0x4C6D}
WELL_PENDING_STDERR = (
    "Leg 1 (the trip) never became ready for Fast Travel.\n"
    "The leg reached area 33 and the game is still waiting on its screen; "
    "give its keys with --arrival-answer (repeat it for several screens).\n"
)
TEMPLE_PENDING_STDERR = (
    "Leg 1 (the trip) never became ready for Fast Travel.\n"
    "The leg reached area 52 and the game is still waiting on its screen; "
    "give its keys with --arrival-answer (repeat it for several screens).\n"
)


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RouteError(reason)


def write_json(path: pathlib.Path, value: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


@contextlib.contextmanager
def bounded_answer(seconds: float):
    """Interrupt a blocked journal reader rather than allowing it to outlive this run."""
    previous = signal.getsignal(signal.SIGALRM)

    def expired(signum, frame):
        raise TimeoutError("journal answer timed out")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def preflight(path: pathlib.Path, out: pathlib.Path, retry_of: pathlib.Path | None,
              budget: float) -> tuple[dict, float]:
    """Validate registered media and the one-retry deadline before creating output."""
    require(not out.exists(), "the output directory is not fresh")
    require(0 < budget <= 3600, "budget must be at most 3600 seconds")
    manifest = json.loads(path.read_text())
    require(manifest.get("mode") == "substitute_title" and manifest.get("title") == "ssb"
            and manifest.get("loaded_letter") == manifest.get("slot_letter") == "D"
            and manifest.get("state_a") == {"area": 16, "x": 3, "y": 7, "facing": 2}
            and len(manifest.get("names_a", [])) == 6, "the manifest is not the prepared D party")
    require(manifest.get("disks", {}).get("df0") == manifest.get("df0")
            and manifest["disks"].get("df1") == manifest.get("df1"),
            "working disk entries disagree")
    sources = [manifest[key] for key in ("boot_source", "disk_b_source", "substitute",
                                         "published_df1", "df0", "df1")]
    require(manifest.get("registered", {}).get("boot_source") == sources[0]
            and manifest["registered"].get("disk_b_source") == sources[1]
            and manifest["registered"].get("substitute") == sources[2]
            and manifest["registered"].get("published") == sources[3],
            "registered disk entries disagree")
    require(all(sha256(pathlib.Path(row["path"])) == row["sha256"] for row in sources),
            "a prepared or registered disk hash differs")
    wall_deadline = time.time() + budget
    if retry_of is not None:
        old = json.loads(retry_of.read_text())
        require(old.get("success") is False and old.get("retryable") is True
                and not old.get("retry_of") and old.get("manifest") == str(path.resolve())
                and old.get("holder") and old.get("out") != str(out.resolve()),
                "the earlier receipt does not authorize a transport-only retry")
        require(pathlib.Path(old["out"]).resolve() == retry_of.resolve().parent,
                "retry receipt is not in its run directory")
        require(not retry_of.with_suffix(".retry-claimed").exists(),
                "the earlier run already has a retry")
        wall_deadline = old["combined_deadline"]
        require(time.time() < wall_deadline, "the combined retry deadline expired")
    try:
        # The codewheel override can resolve without loading the private registry.
        gamedisks.names()
        route_silver_blades.journal_preflight(sys.executable)
        extracted = amigabladesjournal.tables(pathlib.Path(manifest["df0"]["path"]))
        require(len(extracted) > 0, "the prepared side-A journal tables are empty")
    except (gamedisks.RegistryError, RouteError, OSError, ValueError, KeyError,
            ImportError, TypeError) as exc:
        raise RouteError("journal prerequisites are unavailable before boot") from exc
    except SystemExit as exc:
        raise RouteError("journal prerequisites are unavailable before boot") from exc
    require(time.time() < wall_deadline, "the combined deadline expired")
    return manifest, wall_deadline


class GuardedRun:
    """Press only on a matched existing Silver Blades screen."""

    def __init__(self, guest: WinGuest, holder: str, out: pathlib.Path,
                 guards: PixelGuards, deadline: float):
        self.guest, self.holder, self.out = guest, holder, out
        self.guards, self.deadline = guards, deadline
        self.events: list[dict] = []
        self.count = 0
        out.mkdir()

    def left(self, cap: float) -> float:
        left = min(cap, self.deadline - time.monotonic())
        require(left > 0, "the combined deadline expired")
        return left

    def see(self, state: str, limit: float) -> pathlib.Path:
        require(state in self.guards, f"missing {state} guard")
        end = time.monotonic() + self.left(limit)
        while time.monotonic() < end:
            self.count += 1
            raw = self.out / f"{self.count:03d}-{state}-raw.png"
            crop = self.out / f"{self.count:03d}-{state}.png"
            if self.guest.grab(state, raw, crop, self.left(20)):
                if self.guards(state, crop):
                    self.events.append({"screen": state, "raw": str(raw), "crop": str(crop)})
                    return crop
                for other in ("title", "party_menu", "load_picker", "loaded_menu",
                              "journal", "world"):
                    if other != state and other in self.guards and self.guards(other, crop):
                        raise RouteError(f"expected {state}, saw {other}; shot {raw}")
            time.sleep(min(1, max(0, end - time.monotonic())))
        raise RouteError(f"{state} did not match within {limit}s; last shot {raw}")

    def press(self, state: str, key: str, limit: float = 60) -> None:
        self.see(state, limit)
        self.guest.press(self.holder, key, timeout=self.left(20))
        self.events.append({"from": state, "key": key})


def read_live(holder: str) -> dict:
    target = amiga.AmigaTarget(amiga.WinuaePipe(holder=holder), amiga.MACHINES[TITLE])
    target.locate()
    row = amigatrip.row_for(TITLE)
    members = amigaparty.read_party(target)
    return {"area": amigatrip.area_id(target, row), "square": amigatrip.square(target, row),
            "names": None if members is None else [member.name for member in members],
            "variables": {f"{variable:04X}": reading.value for variable in VARIABLES
                          for reading in amigavars.read_variables(target, TITLE, (variable,))},
            "target": target}


def check(reading: dict, names: list[str], area: int,
          square: tuple[int, int, int] | None = None, variables: dict[int, int] | None = None) -> None:
    require(reading["area"] == area and reading["names"] == names,
            f"area or six names differ at {area}: {reading['area']}, {reading['names']}")
    if square is not None:
        require(tuple(reading["square"] or ()) == square,
                f"square in {area} is {reading['square']}, expected {square}")
    for variable, value in (variables or {}).items():
        require(reading["variables"].get(f"{variable:04X}") == value,
                f"${variable:04X} differs from {value}: {reading['variables']}")


def logged(reading: dict) -> dict:
    return {key: value for key, value in reading.items() if key != "target"}


def transport_timeout(exc: BaseException) -> bool:
    return isinstance(exc, ShotTimedOut) or (
        isinstance(exc, RouteError)
        and str(exc).startswith("winvm ")
        and " exceeded its " in str(exc)
        and isinstance(exc.__cause__, subprocess.TimeoutExpired)
    )


def trip(run: GuardedRun, disks: pathlib.Path, out: pathlib.Path, arguments: list[str],
         start: int, end: int) -> dict:
    """Execute one independently logged, bounded fasttravelrun child."""
    out.mkdir()
    command = [sys.executable, str(pathlib.Path(fasttravelrun.__file__)),
               "--holder", run.holder, "--disks", str(disks), "--title", TITLE,
               "--measure-row", "--budget", "300", "--out", str(out), *arguments]
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout = stderr = ""
    try:
        try:
            stdout, stderr = proc.communicate(timeout=run.left(480))
        except subprocess.TimeoutExpired as exc:
            proc.send_signal(signal.SIGTERM)
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=10)
            raise RouteError(f"trip child exceeded its deadline: {out}") from exc
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=10)
        (out / "stdout.txt").write_text(stdout)
        (out / "stderr.txt").write_text(stderr)
    if proc.returncode != 0:
        # A failing child must not conceal a diagnostic behind an expected JSON line.
        try:
            summary = json.loads(stdout)
        except (ValueError, TypeError) as exc:
            raise RouteError(f"trip child did not emit one JSON object: {out}") from exc
        require(isinstance(summary, dict), f"trip child did not emit one JSON object: {out}")
        rows = [summary]
    else:
        rows = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
    pending_well = (start == 16 and end == 33 and arguments == ["--to", "33"]
                    and proc.returncode == 1 and stderr == WELL_PENDING_STDERR
                    and len(rows) == 1 and rows[0].get("result") == "idle"
                    and rows[0].get("settled") is False
                    and rows[0].get("areas_seen") == [16, 33]
                    and rows[0].get("arrival_keys") == []
                    and rows[0].get("arrival_answered") is False
                    and isinstance(rows[0].get("party_before"), list)
                    and len(rows[0]["party_before"]) == 6
                    and all(isinstance(name, str) and name for name in rows[0]["party_before"])
                    and rows[0].get("party_before") == rows[0].get("party_after"))
    pending_temple = (start == 33 and end == 52
                      and arguments == ["--waypoint", "52,7,3,2", "--back", "--peek-var",
                                        "4C62,4C2A,4CFD,4CFE"]
                      and proc.returncode == 1 and stderr == TEMPLE_PENDING_STDERR
                      and len(rows) == 1 and rows[0].get("result") == "idle"
                      and rows[0].get("settled") is False
                      and rows[0].get("areas_seen") == [33, 52]
                      and rows[0].get("arrival_keys") == []
                      and rows[0].get("arrival_answered") is False
                      and isinstance(rows[0].get("party_before"), list)
                      and len(rows[0]["party_before"]) == 6
                      and all(isinstance(name, str) and name for name in rows[0]["party_before"])
                      and rows[0].get("party_before") == rows[0].get("party_after")
                      and isinstance(rows[0].get("outcomes"), list)
                      and bool(rows[0]["outcomes"])
                      and all(isinstance(outcome, dict) and outcome.get("ok") is True
                              for outcome in rows[0]["outcomes"]))
    require(proc.returncode == 0 or pending_well or pending_temple,
            f"trip child stopped with {proc.returncode}: {stderr[-500:]}")
    require(len(rows) == 1 and rows[0].get("result") == "idle"
            and (rows[0].get("settled") is True or pending_well or pending_temple),
            f"trip did not settle: {rows}")
    leg = rows[0]
    require(leg.get("areas_seen") == [start, end] and leg.get("arrival_keys") == []
            and leg.get("party_before") == leg.get("party_after"),
            f"trip diverged from {start} to {end}: {leg}")
    return {"command": command, "result": leg, "pending_well": pending_well,
            "pending_temple": pending_temple,
            "stdout": str(out / "stdout.txt"), "stderr": str(out / "stderr.txt")}


def run(args: argparse.Namespace, *, guest: WinGuest | None = None,
        guards: PixelGuards | None = None, reader=read_live, executor=trip,
        switch_factory=None) -> dict:
    require(0 <= args.wait_lane <= 300, "lane wait exceeds 300 seconds")
    manifest, wall_deadline = preflight(args.manifest, args.out, args.retry_of, args.budget)
    args.out.mkdir(parents=True)
    if args.retry_of is not None:
        marker = args.retry_of.with_suffix(".retry-claimed")
        try:
            descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RouteError("the earlier run already has a retry") from exc
        with os.fdopen(descriptor, "w") as stream:
            stream.write(str(args.out.resolve()) + "\n")
    deadline = time.monotonic() + min(args.budget, wall_deadline - time.time())
    receipt: dict[str, Any] = {"started_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": str(args.manifest.resolve()), "out": str(args.out.resolve()),
        "holder": args.holder, "retry_of": str(args.retry_of) if args.retry_of else None,
        "combined_deadline": wall_deadline, "success": False, "retryable": False,
        "cleanup": [], "trips": [], "reads": {}, "snapshots": []}
    guest = guest or WinGuest()
    local = args.out / "prepare.json"
    booted = False
    run_guard = None
    state = noencounters.WinuaeState(noencounters.winuae_state_path(args.holder))
    active_switch = None
    command = [str(pathlib.Path(__file__)), "--manifest", str(args.manifest),
               "--holder", args.holder, "--out", str(args.out)]
    try:
        copied = {key: args.out / f"{key}.adf" for key in ("df0", "df1")}
        for key, path in copied.items():
            shutil.copyfile(manifest["disks"][key]["path"], path)
            require(sha256(path) == manifest["disks"][key]["sha256"],
                    f"the copied {key} hash differs")
        prepared = {**manifest, "disks": {key: {**manifest["disks"][key], "path": str(path)}
                                                for key, path in copied.items()}}
        write_json(local, prepared)
        guard_file = args.out / "guards.json"
        write_json(guard_file, json.loads(GUARDS.read_text())["guards"])
        guards = guards or PixelGuards(guard_file)
        require({"title", "party_menu", "load_picker", "loaded_menu", "journal", "world",
                  "well_entry_continue", "temple_entry_continue", "temple_clear_world"}
                 <= guards.rules.keys(), "Silver Blades load guards are missing")
        proof = args.out / "mute.json"
        output = guest._run("ssh", acceptance.MUTE_READBACK, timeout=min(60, deadline - time.monotonic()))
        write_json(proof, json.loads(output[output.index("{"):]))
        require(guest.silence(proof), "the Windows playback endpoint did not read back muted")
        title = route_silver_blades.title_for_substitute(prepared)
        receipt["boot"] = acceptance.boot_lane(local, prepared, title, guest=guest,
            holder=args.holder, audio_proof=proof, wait_lane=args.wait_lane,
            timeout=min(300, deadline - time.monotonic()), command=command)
        booted = True
        run_guard = GuardedRun(guest, args.holder, args.out / "screens", guards, deadline)
        run_guard.press("title", "P", 300)
        run_guard.press("party_menu", "L")
        run_guard.press("load_picker", "D")
        run_guard.press("loaded_menu", "B")
        journal_shot = run_guard.out / "journal-before-answer.png"
        raw = run_guard.out / "journal-before-answer-raw.png"
        if guest.grab("journal", raw, journal_shot, run_guard.left(20)) and guards("journal", journal_shot):
            capture, press = guest.answer_io(args.holder)
            with bounded_answer(run_guard.left(180)):
                answered = amigabladesjournal.answer(args.holder, 1, copied["df0"],
                    capture=capture, press=press, keep=args.out / "journal")
            require(answered, "the journal answer did not finish")
            receipt["journal"] = "answered"
        else:
            receipt["journal"] = "absent"
        run_guard.see("world", 90)
        names = manifest["names_a"]
        initial = reader(args.holder)
        check(initial, names, 16, (3, 7, 2))
        receipt["reads"]["start"] = logged(initial)

        def snapshot(name: str) -> None:
            receipt["snapshots"].append(name)
            guest.snapshot(name, args.holder)

        def observed(label: str, area: int, square: tuple[int, int, int] | None,
                     variables: dict[int, int] | None = None,
                     screen: str = "world") -> dict:
            run_guard.see(screen, 60)
            reading = reader(args.holder)
            check(reading, names, area, square, variables)
            receipt["reads"][label] = logged(reading)
            return reading

        def step(label: str, area: int, square: tuple[int, int, int],
                 expected: tuple[int, int, int] | None = None,
                 temple: bool = False) -> None:
            nonlocal active_switch
            target = reader(args.holder)["target"]
            factory = switch_factory or (lambda target: noencounters.WinuaeEncounters(
                TITLE, target, state=state, lane_check=lambda: guest.lane(args.holder, timeout=30),
                press=lambda key: guest.press(args.holder, key, timeout=30)))
            active_switch = factory(target)
            on = active_switch.on()
            require("error" not in on and "stopped" not in on, f"gate did not switch on: {on}")
            try:
                if temple:
                    for key, before, after, stage in (
                            ("NP6", (2, 15, 3), (2, 15, 0), "turn-north"),
                            ("NP6", (2, 15, 0), (2, 15, 1), "turn-east"),
                            ("NP8", (2, 15, 1), (3, 15, 1), "step")):
                        observed(label + "-before-" + stage, area, before,
                                 screen="temple_clear_world")
                        response = active_switch.keys([key])
                        require(response.get("pressed") == [key] and "error" not in response
                                and "stopped" not in response,
                                f"{key} did not go through: {response}")
                        moved = observed(label + "-" + stage, area, after,
                                         screen="temple_clear_world")
                        receipt.setdefault("steps", []).append({"on": on, "key": response,
                                                                  "after": logged(moved)})
                else:
                    response = active_switch.keys(["NP8"])
                    require(response.get("pressed") == ["NP8"] and "error" not in response
                            and "stopped" not in response, f"NP8 did not go through: {response}")
                    moved = observed(label + "-step", area, expected)
                    require(tuple(moved["square"]) != square, "NP8 left the party on its square")
                    receipt.setdefault("steps", []).append({"on": on, "key": response,
                                                              "after": logged(moved)})
            finally:
                off = active_switch.off()
                require("error" not in off and not state.load()["on"]
                        and not state.load()["rows"], f"encounter gate did not restore: {off}")
                receipt.setdefault("switch_off", []).append(off)
                active_switch = None

        snapshot("s0")
        disks = pathlib.Path(manifest["boot_source"]["path"]).parent
        specs = [(["--to", "33"], 16, 33),
                 (["--waypoint", "52,7,3,2", "--back", "--peek-var", "4C62,4C2A,4CFD,4CFE"], 33, 52),
                 (["--to", "82"], 16, 82),
                 (["--waypoint", "81,5,8,1", "--back", "--peek-var", "4CFD,4CFE,4C6C,4C6D"], 82, 81)]
        for number, (flags, source, destination) in enumerate(specs, 1):
            if number == 3:
                require(not state.load()["on"] and not state.load()["rows"],
                        "encounter journal is not empty before restore")
                guest.restore("s0", args.holder)
                observed("restored", 16, (3, 7, 2))
            if number in (2, 4):
                snapshot(f"source-{source}")
            leg = executor(run_guard, disks, args.out / f"trip-{number}",
                           flags, source, destination)
            receipt["trips"].append(leg)
            if number == 1:
                if leg.get("pending_well"):
                    prompt = reader(args.holder)
                    check(prompt, names, 33, (1, 1, 2))
                    receipt["reads"]["well_prompt"] = logged(prompt)
                    run_guard.press("well_entry_continue", "RET")
                    run_guard.see("world", 60)
                    require(amigatrip.gate(reader(args.holder)["target"], amigatrip.row_for(TITLE)),
                            "the Well world gate is still shut after Return")
                observed("33", 33, (1, 1, 2))
            elif number == 2:
                if leg.get("pending_temple"):
                    prompt = reader(args.holder)
                    check(prompt, names, 52, (2, 15, 3), {0x4C62: 5, 0x4C2A: 1})
                    receipt["reads"]["temple_prompt"] = logged(prompt)
                    run_guard.press("temple_entry_continue", "RET")
                    run_guard.see("world", 60)
                    require(amigatrip.gate(reader(args.holder)["target"], amigatrip.row_for(TITLE)),
                            "the Temple world gate is still shut after Return")
                observed("52", 52, (2, 15, 3), {0x4C62: 5})
                snapshot("destination-52")
                step("52", 52, (2, 15, 3), (3, 15, 1), temple=True)
            elif number == 3:
                observed("82", 82, (1, 11, 1))
            else:
                observed("81", 81, (15, 6, 3), {0x4CFD: 64, 0x4CFE: 85,
                    0x4C6C: 64, 0x4C6D: 85})
                snapshot("destination-81")
                step("81", 81, (15, 6, 3), (14, 6, 3))
        receipt["screens"] = run_guard.events
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        receipt["retryable"] = transport_timeout(exc)
    finally:
        if run_guard is not None:
            receipt["screens"] = run_guard.events
        if booted:
            try:
                if state.load()["on"] or state.load()["rows"]:
                    target = reader(args.holder)["target"]
                    switch = active_switch or noencounters.WinuaeEncounters(
                        TITLE, target, state=state, lane_check=lambda: guest.lane(args.holder, timeout=30))
                    reply = switch.off()
                    require("error" not in reply, f"encounter cleanup did not restore: {reply}")
                require(not state.load()["on"] and not state.load()["rows"],
                        "encounter journal remains active")
                receipt["cleanup"].append({"encounters": "off"})
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append({"encounters_error": str(exc)})
            for name in receipt["snapshots"]:
                try:
                    guest.discard(name, args.holder)
                    receipt["cleanup"].append({"discard": name})
                except Exception as exc:  # noqa: BLE001
                    receipt["cleanup"].append({"discard_error": f"{name}: {exc}"})
            try:
                receipt["halt"] = acceptance.halt_lane(guest, args.holder,
                    manifest_path=local, command=command)
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append({"halt_error": str(exc)})
        try:
            original = json.loads(args.manifest.read_text())
            for key in ("boot_source", "disk_b_source", "substitute", "published_df1", "df0", "df1"):
                require(sha256(pathlib.Path(original[key]["path"])) == original[key]["sha256"],
                        f"original {key} changed")
            for key in ("df0", "df1"):
                require(sha256(args.out / f"{key}.adf") == manifest[key]["sha256"],
                        f"local {key} changed")
            receipt["source_hashes"] = "unchanged"
        except Exception as exc:  # noqa: BLE001
            receipt["cleanup"].append({"hash_error": str(exc)})
        errors = [item for item in receipt["cleanup"] if any(k.endswith("error") for k in item)]
        receipt["success"] = "error" not in receipt and not errors and "halt" in receipt
        receipt["retryable"] = receipt["retryable"] and not errors and not receipt["success"]
        receipt["remaining_budget"] = max(0, wall_deadline - time.time())
        write_json(args.out / "receipt.json", receipt)
    if not receipt["success"]:
        raise RouteError(receipt.get("error", "cleanup failed") + f"; cleanup: {errors}")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--holder", required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--budget", type=float, default=3600)
    parser.add_argument("--wait-lane", type=float, default=0)
    parser.add_argument("--retry-of", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        with terminating():
            run(args)
    except (RouteError, OSError, ValueError, KeyError) as exc:
        print(f"ssbneighbour: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
