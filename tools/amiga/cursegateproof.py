#!/usr/bin/env python3
"""Compare Curse's ECL01 chance gate with an unsuppressed, same-snapshot fight.

This is a no-save harness experiment, not conversion acceptance. An unknown
screen, an unqualified fight or two ordinary moves without a fight proves
nothing about suppression. Only the holder this command claims is stopped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import signal
import sys
import time
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import amiga, amigaparty, amigatrip, amigavars  # noqa: E402
from tools.amiga import acceptance, noencounters, route_curse, screens  # noqa: E402
from tools.amiga.winuaesession import RouteError, WinGuest, terminating  # noqa: E402
from tools.registry import scratch  # noqa: E402

TITLE = "curse-of-the-azure-bonds"
SOURCE = pathlib.Path.home() / ".cache/wish/acceptance/WISH-303/curse-prep-L1"
GUARDS = SOURCE.parent / "maps2/guards.json"
IDENTITY = SOURCE.parent / "maps2/identity.json"
COMBAT_REFERENCE = (pathlib.Path.home() /
                    ".cache/wish/acceptance/WISH-359/m1/curse-fight-menu.png")
COMBAT_SHA256 = "2748c6b26945f04fe909054136a23cf8ef8a0a482b8baaff495ec2711610f52a"
COMBAT_BOX = (72, 404, 686, 426)
MEDIA = {"save": "faa013855dd0c468e9ac90a132b91b2f50e6ea457ef763caf125ba98e9021684",
         "diskb": "a6f94bb42664ab94b673bf0c7390420d94bec257ae09fea488a53504b6e1fca3"}
ENTRY = "c80bfd1e"
CHANCE = "9afc9873"
ORIGINAL = bytes.fromhex("08006401797f")
PATCHED = bytes.fromhex("09006401797f")
GATE = "*0x5006+0x9952"
SNAPSHOT = "curse_ecl01_off"
TOTAL = 900
CLEANUP = 300
VARS = (0x4C02, 0x4C05, 0x4C06, 0x7ECA, 0x7F79, 0x7F7A)
QUALIFIED = (0x4C02, 0x4C05, 0x4C06)
NAMES = ("MATHEW", "PHILIPPE", "SHARA", "LEDERA", "TRAVIS", "MARK")


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RouteError(reason)


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: pathlib.Path, report: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def receipt_of(value: Any) -> Any:
    """Keep a pipe receipt in JSON without discarding its diagnostic fields."""
    return value.as_dict() if hasattr(value, "as_dict") else value


def private_media(manifest: dict, out: pathlib.Path) -> dict:
    """Copy only approved prepared media; leave all source paths and bytes alone."""
    disks = {}
    for key, digest in MEDIA.items():
        destination = out / f"{key}.adf"
        shutil.copyfile(SOURCE / f"{key}.adf", destination)
        require(sha256(destination) == digest, f"the private {key} copy differs")
        disks[key] = {**manifest["disks"][key], "path": str(destination)}
    return {**manifest, "disks": disks}


def preflight(args: argparse.Namespace, state: noencounters.WinuaeState) -> dict:
    """Pin the source, holder, guards and previous journal before claiming a lane."""
    require(args.manifest.resolve() == (SOURCE / "prepare.json").resolve(),
            "only the prepared Curse source manifest is approved")
    require(args.guards.resolve() == GUARDS.resolve()
            and args.identity.resolve() == IDENTITY.resolve(),
            "the screen guards must be the measured Curse maps2 pair")
    root = scratch.cache_dir("acceptance", "WISH-365").resolve()
    require(args.out.resolve().is_relative_to(root) and args.out.resolve() != root
            and not args.out.exists(), "the proof needs a fresh WISH-365 cache folder")
    require(args.wait_lane == 0 and args.holder == "wish365-ecl01",
            "this one-boot proof requires its new holder and no lane wait")
    require(state.load().get("on") is False and state.load().get("rows") == [],
            "this holder has outstanding encounter changes; do not boot")
    require(sha256(COMBAT_REFERENCE) == COMBAT_SHA256,
            "the measured Curse combat reference is absent or changed")
    guards = screens.PixelGuards(args.guards)
    identity = screens.PixelGuards(args.identity)
    require({"title", "front_end", "intro", "load_picker", "loaded_menu", "sheet", "world"}
            <= guards.rules.keys() and {"loaded_menu", "sheet"} <= identity.rules.keys(),
            "the measured load/sheet/world guards are incomplete")
    manifest = json.loads(args.manifest.read_text())
    require(manifest.get("title") == "curse" and manifest.get("loaded_letter") == "B"
            and manifest.get("state_a") == {"area": 1, "x": 4, "y": 14, "facing": 1}
            and tuple(manifest.get("names_a", ())) == NAMES,
            "the source does not hold the prepared Tilverton B party")
    require(set(manifest.get("disks", {})) == set(MEDIA)
            and all(manifest["disks"][key]["sha256"] == want
                    and pathlib.Path(manifest["disks"][key]["path"]).resolve()
                    == (SOURCE / f"{key}.adf").resolve()
                    and sha256(SOURCE / f"{key}.adf") == want
                    for key, want in MEDIA.items()), "prepared media pins or source bytes differ")
    for entry in (manifest["registered"]["specimen"], manifest["substitute"]):
        require(sha256(pathlib.Path(entry["path"])) == entry["sha256"],
                "registered or substitute provenance changed")
    require(WinGuest.silence(args.audio_proof), "fresh Windows playback mute proof is required")
    return manifest


def gate_row() -> noencounters.Row:
    rows = [r for r in noencounters.rows_for(TITLE) if r.spec == GATE]
    require(len(rows) == 1 and rows[0].kind == noencounters.GATE
            and rows[0].area == ENTRY and rows[0].digest == CHANCE
            and rows[0].changes == ((0, noencounters.SAVE),),
            "the committed ECL01 row does not match this experiment")
    return rows[0]


def script(target) -> dict:
    """Read the live entry, full statement and resolved pointer, without writes."""
    target.locate()
    pointer = int.from_bytes(target.read(target.data_base + 0x5006, 4), "big")
    require(pointer != 0 and noencounters.inside_memory(pointer + 0x8000, 20)
            and noencounters.inside_memory(pointer + 0x9952, 6),
            "the Curse area-script pointer is unresolved or outside memory")
    entry = target.read(pointer + 0x8000, 20)
    chance = target.read(pointer + 0x9952, 6)
    return {"pointer": pointer, "entry": noencounters.digest(entry),
            "address": pointer + 0x9952, "statement": chance.hex()}


def pinned(target, expected: bytes) -> dict:
    result = script(target)
    require(result["entry"] == ENTRY and result["statement"] == expected.hex(),
            f"ECL01 pin or $9952 bytes differ: {result}")
    return result


def live(target, *, names: bool = False) -> dict:
    """Keep note-backed member-table readings distinct from qualified flags."""
    target.locate()
    row = amigatrip.row_for(TITLE)
    fields = {f"{v:04X}": reading.as_log()
              for v in VARS for reading in amigavars.read_variables(target, TITLE, (v,))}
    for v in QUALIFIED:
        reading = fields[f"{v:04X}"]
        require(reading["value"] is not None and reading["note"] is None,
                f"${v:04X} cannot be checked as a live flag")
    got = {"area": amigatrip.area_id(target, row),
           "square": amigatrip.square(target, row),
           "mode": target.read(target.data_base + amigaparty.ROWS[TITLE].mode, 1)[0],
           "attribute": target.read(target.data_base + amiga.MACHINES[TITLE].notes[
               "square_attribute"], 1)[0], "variables": fields}
    if names:
        party = amigaparty.read_party(target)
        got["names"] = None if party is None else [member.name for member in party]
    fix = target.fix()
    got["fix"] = None if fix is None else {"x": fix.x, "y": fix.y, "facing": fix.facing,
                                           "world_map": fix.world_map}
    return got


def qualified(got: dict) -> dict:
    return {f"{v:04X}": got["variables"][f"{v:04X}"]["value"] for v in QUALIFIED}


def at_world(got: dict, square: tuple[int, int, int]) -> None:
    require(got["area"] == 1 and got["square"] == square and got["mode"] == 4
            and got["attribute"] == 0 and got["fix"] == {"x": square[0], "y": square[1],
                                                         "facing": square[2], "world_map": False},
            f"not the ordinary Tilverton square {square}: {got}")


def switched(reply: dict, target, *, first: bool = False) -> dict:
    """A blocked ECL01 row cannot be mistaken for another row's write."""
    require("error" not in reply and "stopped" not in reply,
            f"the switch command failed: {reply}")
    rows = list(reply.get("rows", []))
    rows += [r for entry in reply.get("applied", []) for r in entry.get("rows", [])]
    ours = [r for r in rows if r.get("row") == GATE]
    require(not any("error" in r or "stopped" in r for r in ours),
            f"the ECL01 row was stopped: {ours}")
    require(not any("new" in r for r in rows if r.get("row") != GATE),
            f"another encounter row changed this script: {reply}")
    now = pinned(target, PATCHED)
    require(len(state_rows := [r for r in rows if r.get("row") == GATE and "new" in r]) <= 1,
            f"duplicate ECL01 writes: {state_rows}")
    if first:
        require(len(state_rows) == 1 and state_rows[0].get("address") == now["address"]
                and state_rows[0].get("new") == "09",
                f"the ECL01 row did not write its one opcode: {reply}")
    return now


def off_checked(switch, state, target) -> dict:
    reply = switch.off()
    require("error" not in reply and "stopped" not in reply
            and not state.load()["on"] and not state.load()["rows"],
            f"encounter off did not clear its journal: {reply}")
    pinned(target, ORIGINAL)
    return reply


class Screens:
    """Grab the emulator's frame; only a matched guard permits the next key."""

    def __init__(self, guest, holder, folder, guards, identity, route_end, report, receipt):
        self.guest, self.holder, self.folder = guest, holder, folder
        self.guards, self.identity, self.route_end = guards, identity, route_end
        self.report, self.receipt = report, receipt
        self.events = report.setdefault("events", [])
        self.count = 0
        folder.mkdir()

    def left(self, cap: float) -> float:
        left = min(cap, self.route_end - time.monotonic())
        require(left > 0, "route deadline reached; reserve cleanup time")
        return left

    def grab(self, label: str) -> pathlib.Path | None:
        self.count += 1
        raw = self.folder / f"{self.count:03d}-{label}.raw.png"
        crop = self.folder / f"{self.count:03d}-{label}.png"
        good = self.guest.grab(label, raw, crop, self.left(20))
        self.events.append({"label": label, "raw": str(raw),
                            "crop": str(crop) if good else None,
                            "sha256": sha256(raw)})
        self.receipt()
        return crop if good else None

    def see(self, state: str, seconds: float, *, opening: bool = False,
            from_state: str | None = None) -> pathlib.Path:
        require(state in self.guards, f"missing {state} guard")
        end, count = time.monotonic() + self.left(seconds), {"front_end": 0, "intro": 0}
        while time.monotonic() < end:
            crop = self.grab(state)
            if crop is not None:
                if self.guards(state, crop):
                    if state in self.identity:
                        require(self.identity(state, crop), f"wrong party on {state}: {crop}")
                    return crop
                if opening:
                    for other, cap in (("front_end", 4), ("intro", 1)):
                        if self.guards(other, crop):
                            require(count[other] < cap, f"{other} exceeded its ESC cap")
                            count[other] += 1
                            self.guest.press(self.holder, "ESC", timeout=self.left(20))
                            self.events.append({"interstitial": other, "key": "ESC"})
                            self.receipt()
                            break
                    else:
                        require(not any(self.guards(s, crop) for s in self.guards.rules
                                        if s != state), f"expected {state}, got another screen: {crop}")
                elif any(self.guards(s, crop) for s in self.guards.rules
                         if s not in (state, from_state)):
                    raise RouteError(f"expected {state}, saw another measured screen: {crop}")
            time.sleep(min(0.5, max(0.0, end - time.monotonic())))
        raise RouteError(f"{state} never matched before its guarded wait expired")

    def press(self, key: str) -> None:
        require(key in {"L", "B", "V", "E", "NP2", "NP8"}, f"unreviewed key {key}")
        self.guest.press(self.holder, key, timeout=self.left(20))
        self.events.append({"key": key})
        self.receipt()

    def world_at(self, target, square: tuple[int, int, int], seconds: float,
                 *, from_state: str | None = None) -> dict:
        """Do not mistake a frame from before a turn or restore for the result."""
        end = time.monotonic() + self.left(seconds)
        while time.monotonic() < end:
            crop = self.grab("world")
            if crop is not None and self.guards("world", crop):
                got = live(target)
                if got["area"] == 1 and got["square"] == square and got["mode"] == 4:
                    at_world(got, square)
                    return got
                require(got["area"] in (None, 1) and got["mode"] in (None, 4),
                        f"world guard matched another area or mode: {got}")
            elif crop is not None and any(self.guards(s, crop) for s in self.guards.rules
                                           if s not in ("world", from_state)):
                raise RouteError(f"expected Tilverton {square}, another screen: {crop}")
            time.sleep(min(0.5, max(0.0, end - time.monotonic())))
        raise RouteError(f"world fix {square} never matched; last raw capture in {self.folder}")


def classify(world: bool, combat: bool, mode: int | None,
             prior: dict, index: int) -> str:
    """Only an independently measured combat menu on an ordinary step is a control."""
    require(not (world and combat), "world and combat guards matched the same frame")
    if world and mode == 4:
        return "world"
    if (combat and not world and mode == amigaparty.ROWS[TITLE].combat_value
            and prior["area"] == 1 and prior["mode"] == 4
            and prior["attribute"] == 0
            and prior["square"] == ((4, 14, 3) if index == 1 else (3, 14, 3))
            and prior["fix"] == {"x": 5 - index, "y": 14, "facing": 3,
                                 "world_map": False}):
        return "combat"
    return "unknown"


def observe_step(shots: Screens, target, index: int, before: dict,
                 combat_guard, *, replay: bool) -> tuple[str, dict | None]:
    """Keep an unknown screen as evidence; do not interpret a world miss as combat."""
    end = time.monotonic() + shots.left(35)
    last: dict | None = None
    while time.monotonic() < end:
        crop = shots.grab(f"{'replay' if replay else 'control'}-{index}")
        if crop is None:
            continue
        reading = live(target)
        world = shots.guards("world", crop)
        combat = combat_guard(crop)
        outcome = classify(world, combat, reading["mode"], before, index)
        last = {"outcome": outcome, "reading": reading, "crop": str(crop)}
        if outcome == "combat":
            return outcome, last
        if outcome == "world":
            expected = (4 - index, 14, 3)
            if reading["area"] == 1 and reading["square"] == before["square"]:
                time.sleep(min(0.5, max(0.0, end - time.monotonic())))
                continue
            at_world(reading, expected)
            return outcome, last
        if reading["mode"] == 5 or any(
                shots.guards(s, crop) for s in shots.guards.rules if s != "world"):
            return "unknown", last
        time.sleep(min(0.5, max(0.0, end - time.monotonic())))
    return "unknown", last


def proof(shots: Screens, target, switch, state, guest, holder, combat_guard,
          report: dict) -> None:
    """One off snapshot, up to two control moves, then only a matched replay."""
    shots.see("title", 250, opening=True)
    previous = "title"
    for key, screen in (("L", "load_picker"), ("B", "loaded_menu"), ("V", "sheet"),
                        ("E", "loaded_menu")):
        shots.press(key)
        shots.see(screen, 40, from_state=previous)
        previous = screen
    shots.press("B")
    shots.world_at(target, (4, 14, 1), 50, from_state="loaded_menu")
    start = live(target, names=True)
    at_world(start, (4, 14, 1))
    require(tuple(start["names"] or ()) == NAMES, "slot B is not the MATHEW party")
    original = pinned(target, ORIGINAL)
    report["start"] = {"reading": start, "script": original}
    world_crop = pathlib.Path(shots.events[-1]["crop"])
    screens.checked_rule(shots.folder.parent / "combat-reference.png", COMBAT_BOX,
                         "combat", (world_crop,))
    report["snapshot"] = receipt_of(guest.snapshot(SNAPSHOT, holder))
    report["snapshot_taken"] = True
    shots.receipt()
    shots.press("NP2")
    prior = shots.world_at(target, (4, 14, 3), 35)
    report["control_turn"] = prior
    shots.receipt()
    fight_index = None
    for index in (1, 2):
        at_world(prior, (5 - index, 14, 3))
        check = pinned(target, ORIGINAL)
        report.setdefault("control_before", []).append({"move": index, "reading": prior,
                                                        "script": check})
        shots.receipt()
        shots.press("NP8")
        outcome, seen = observe_step(shots, target, index, prior, combat_guard, replay=False)
        report.setdefault("control", []).append({"move": index, **(seen or {"outcome": outcome})})
        shots.receipt()
        if outcome == "unknown":
            report["verdict"] = "inconclusive: unclassified control screen"
            return
        if outcome == "combat":
            fight_index = index
            break
        prior = seen["reading"]
    if fight_index is None:
        report["verdict"] = "inconclusive: no control fight in two moves"
        return
    require(not state.load()["on"] and not state.load()["rows"],
            "the control unexpectedly changed encounter state")
    pinned(target, ORIGINAL)
    report["control_off"] = off_checked(switch, state, target)
    shots.receipt()
    report["restore_control"] = receipt_of(guest.restore(SNAPSHOT, holder))
    shots.world_at(target, (4, 14, 1), 35)
    again = live(target, names=True)
    at_world(again, (4, 14, 1))
    require(tuple(again["names"] or ()) == NAMES and qualified(again) == qualified(start)
            and pinned(target, ORIGINAL) == original,
            "snapshot did not restore the party, qualified flags or ECL01")
    report["restored_start"] = again
    shots.receipt()
    response = switch.on()
    report["switch_on"] = response
    shots.receipt()
    switched(response, target, first=True)
    report["journal_on"] = state.load()
    shots.receipt()
    try:
        for index, key in enumerate(("NP2", *("NP8",) * fight_index)):
            # The switch re-applies after a script reload. The press callback checks
            # the exact ECL01 opcode at the instant each key leaves the driver.
            result = switch.keys([key])
            report.setdefault("switch_keys", []).append(result)
            shots.receipt()
            require(result.get("pressed") == [key], f"the guarded {key} was not pressed: {result}")
            switched(result, target)
            if index == 0:
                prior = shots.world_at(target, (4, 14, 3), 35)
                report["replay_turn"] = prior
                shots.receipt()
                continue
            outcome, seen = observe_step(shots, target, index, prior, combat_guard, replay=True)
            report.setdefault("replay", []).append({"move": index, **(seen or {"outcome": outcome})})
            shots.receipt()
            if outcome != "world":
                report["verdict"] = f"inconclusive: replay move {index} was {outcome}"
                return
            prior = seen["reading"]
        report["candidate"] = True
    finally:
        report["switch_off"] = off_checked(switch, state, target)
        report["journal_off"] = state.load()
        shots.receipt()


def run(args: argparse.Namespace, *, guest=None, target=None, switch_factory=None,
        guards=None, identity=None, combat_guard=None) -> dict:
    """Prepare private images, claim one lane, compare, and always clean up ours."""
    state = noencounters.WinuaeState(noencounters.winuae_state_path(args.holder))
    manifest = preflight(args, state)
    gate_row()
    start_time = time.monotonic()
    route_end, total_end = start_time + TOTAL - CLEANUP, start_time + TOTAL
    args.out.mkdir(parents=True)
    local = args.out / "prepare.json"
    prepared = private_media(manifest, args.out)
    record(local, prepared)
    report: dict[str, Any] = {"verdict": "inconclusive", "candidate": False,
                              "holder": args.holder, "input": str(args.manifest),
                              "media": MEDIA, "cleanup": [],
                              "journal_path": str(state.path),
                              "journal_initial": state.load()}
    screens.canonical_file(COMBAT_REFERENCE, args.out / "combat-reference.png")
    combat_reference = args.out / "combat-reference.png"
    report["combat_reference"] = {"original": str(COMBAT_REFERENCE),
                                  "original_sha256": COMBAT_SHA256,
                                  "canonical": str(combat_reference),
                                  "canonical_sha256": sha256(combat_reference)}
    guest = guest or WinGuest()
    guards = guards or screens.PixelGuards(args.guards)
    identity = identity or screens.PixelGuards(args.identity)
    booted = False
    switch = None
    shots = None
    old_alarm = signal.getsignal(signal.SIGALRM)
    alarm_set = False
    command = [str(pathlib.Path(__file__)), "--manifest", str(args.manifest),
               "--holder", args.holder, "--out", str(args.out)]
    def receipt():
        record(args.out / "summary.json", report)

    receipt()
    try:
        require(route_end - time.monotonic() > 120, "too little route time remains to boot")
        def route_expired(signum, frame):
            raise RouteError("the 600-second route deadline expired; begin cleanup")

        signal.signal(signal.SIGALRM, route_expired)
        alarm_set = True
        signal.setitimer(signal.ITIMER_REAL, route_end - time.monotonic())
        report["boot"] = acceptance.boot_lane(
            local, prepared, route_curse.title_for_manifest(prepared), guest=guest,
            holder=args.holder, audio_proof=args.audio_proof, wait_lane=args.wait_lane,
            timeout=min(120, route_end - time.monotonic()), command=command)
        booted = True
        receipt()
        target = target or amiga.AmigaTarget(amiga.WinuaePipe(holder=args.holder),
                                            amiga.MACHINES[TITLE])
        shots = Screens(guest, args.holder, args.out / "shots", guards, identity,
                        route_end, report, receipt)
        # The reference is an observed combat menu, not an invented pixel hash.
        rule = screens.guard_rule(combat_reference, COMBAT_BOX, "combat")
        report["combat_reference"]["box"] = rule
        combat_guard = combat_guard or (lambda crop: screens.box_digests(
            crop, (COMBAT_BOX,), "combat")[COMBAT_BOX] == rule["sha256"])
        switch_factory = switch_factory or (lambda press: noencounters.WinuaeEncounters(
            TITLE, target, state=state,
            lane_check=lambda: guest.lane(args.holder, timeout=shots.left(20)),
            press=press))

        def press_when_patched(key):
            index = len(report.get("switch_keys", ()))
            require(index <= 2 and key == ("NP2" if index == 0 else "NP8"),
                    f"unreviewed switched key {index}: {key}")
            expected = ((4, 14, 1), (4, 14, 3), (3, 14, 3))[index]
            reading = shots.world_at(target, expected, 15)
            require(state.load()["on"] and len(state.load()["rows"]) == 1
                    and state.load()["rows"][0]["spec"] == GATE
                    and state.load()["rows"][0]["original"] == "08"
                    and state.load()["rows"][0]["changed"] == "09",
                    "the switch journal does not hold only the ECL01 opcode")
            report.setdefault("replay_before", []).append({"key": key, "reading": reading,
                                                           "script": pinned(target, PATCHED)})
            receipt()
            shots.press(key)

        switch = switch_factory(press_when_patched)
        proof(shots, target, switch, state, guest, args.holder, combat_guard, report)
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        receipt()
    finally:
        if alarm_set:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_alarm)
        if shots is not None:
            report["screens"] = shots.events
        if booted:
            off_ok = False
            try:
                if switch is not None:
                    report["cleanup"].append({"off": off_checked(switch, state, target)})
                else:
                    require(not state.load()["on"] and not state.load()["rows"],
                            "switch state is pending without its driver")
                    pinned(target, ORIGINAL)
                    report["cleanup"].append({"off": "already original"})
                off_ok = True
            except BaseException as exc:
                report["cleanup"].append({"off_error": f"{type(exc).__name__}: {exc}"})
            if report.get("snapshot_taken") and off_ok:
                try:
                    report["cleanup"].append({"restore": receipt_of(
                        guest.restore(SNAPSHOT, args.holder))})
                    shots.world_at(target, (4, 14, 1), 25)
                    pinned(target, ORIGINAL)
                    guest.discard(SNAPSHOT, args.holder)
                    report["cleanup"].append({"discard": SNAPSHOT})
                except BaseException as exc:
                    report["cleanup"].append({"snapshot_error": f"{type(exc).__name__}: {exc}"})
            try:
                report["halt"] = acceptance.halt_lane(
                    guest, args.holder, timeout=max(1, min(30, total_end - time.monotonic())),
                    manifest_path=local, command=command)
                for key, digest in MEDIA.items():
                    require(report["halt"]["fetched"][key]["sha256"] == digest,
                            f"the guest changed its private {key} disk")
            except BaseException as exc:
                report["cleanup"].append({"halt_error": f"{type(exc).__name__}: {exc}"})
        try:
            require(all(sha256(SOURCE / f"{key}.adf") == digest
                        and sha256(args.out / f"{key}.adf") == digest
                        for key, digest in MEDIA.items()), "source or private disk changed")
            for entry in (manifest["registered"]["specimen"], manifest["substitute"]):
                require(sha256(pathlib.Path(entry["path"])) == entry["sha256"],
                        "original provenance changed")
            report["source_hashes"] = "unchanged"
        except BaseException as exc:
            report["cleanup"].append({"media_error": f"{type(exc).__name__}: {exc}"})
        if report.get("candidate") and not report.get("error") and report.get("halt") \
                and report.get("source_hashes") == "unchanged" \
                and not any(any(k.endswith("_error") for k in item)
                            for item in report["cleanup"]):
            report["verdict"] = "paired suppression and restoration observed"
        elif report.get("candidate"):
            report["verdict"] = "inconclusive: cleanup or media check failed"
        try:
            report["journal_final"] = state.load()
            require(report["journal_final"]["on"] is False
                    and report["journal_final"]["rows"] == [],
                    "the encounter journal still records changed bytes")
        except BaseException as exc:
            report["cleanup"].append({"journal_error": f"{type(exc).__name__}: {exc}"})
            report["verdict"] = "inconclusive: final encounter journal is not clear"
        report["elapsed_seconds"] = time.monotonic() - start_time
        record(args.out / "summary.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--guards", type=pathlib.Path, required=True)
    parser.add_argument("--identity", type=pathlib.Path, required=True)
    parser.add_argument("--audio-proof", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--holder", required=True)
    parser.add_argument("--wait-lane", type=float, default=0)
    args = parser.parse_args(argv)
    with terminating():
        result = run(args)
    print(json.dumps({k: result.get(k) for k in ("verdict", "error", "cleanup", "elapsed_seconds")},
                     sort_keys=True))
    return 0 if result["verdict"] == "paired suppression and restoration observed" else 1


if __name__ == "__main__":
    sys.exit(main())
