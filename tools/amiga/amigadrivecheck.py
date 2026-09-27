#!/usr/bin/env python3
"""Prove that a floppy change over WinUAE's pipe works, on generated disks and one launch.

Three disposable ADFs with distinct markers are staged for one holder. DF0 starts
with A and DF1 with C, DF0 is swapped to B and back to A, and four controls (another
holder, another holder's path, a file never staged, the same path twice) must leave
both drives as they were. No game data is used and no game is booted.
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import subprocess
import sys
import time
import uuid
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import amiga  # noqa: E402
from tools.amiga.staging import sha256  # noqa: E402
from tools.amiga.winuaesession import (  # noqa: E402
    RouteError,
    Terminated,
    WinGuest,
    _mute_proof,
    terminating,
)
from tools.registry import scratch  # noqa: E402

ISSUE = "679"
ADF_SIZE = 901120
MARKER_AT = 0x400
KEYS = ("A", "B", "C")
DESKTOP_EXE = r"C:\Program Files\WinUAE\winuae64.exe"
DEPLOYED_SCRIPT = r"C:\Amiga\winuae.ps1"
REPO_SCRIPT = pathlib.Path(__file__).resolve().with_name("winuae.ps1")
#: The probing phase and the cleanup after it, in seconds.
PROBE_SECONDS = 180.0
CLEANUP_SECONDS = 60.0
#: How long the emulator may take before the pipe first answers.
READY_SECONDS = 30.0
INTRUDER = f"wish{ISSUE}-intruder"

READ_DEPLOYED = f"""$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$exe = '{DESKTOP_EXE}'
'winuae64_sha256=' + (Get-FileHash -Algorithm SHA256 -LiteralPath $exe).Hash
'winuae64_version=' + (Get-Item -LiteralPath $exe).VersionInfo.FileVersion
'winuae_ps1_sha256=' + (Get-FileHash -Algorithm SHA256 -LiteralPath '{DEPLOYED_SCRIPT}').Hash
"""


def make_adf(key: str) -> bytes:
    """A blank 880 KB floppy image with its own marker, so the three hashes differ."""
    image = bytearray(ADF_SIZE)
    marker = f"WISH PROBE {key}".encode("ascii")
    image[MARKER_AT:MARKER_AT + len(marker)] = marker
    return bytes(image)


class ProbeGuest(WinGuest):
    """`WinGuest`, plus the reads the probe needs that a route never does."""

    def deployed(self, timeout: float) -> dict[str, str]:
        script = base64.b64encode(READ_DEPLOYED.encode("utf-16-le")).decode("ascii")
        text = self._run("ssh", f"powershell -NoProfile -EncodedCommand {script}",
                         timeout=timeout)
        wanted = ("winuae64_sha256", "winuae64_version", "winuae_ps1_sha256")
        found = {}
        for line in text.splitlines():
            key, _, value = line.strip().partition("=")
            if key in wanted and value:
                if key in found:
                    raise RouteError(f"The guest reported {key} twice: {text[-300:]!r}")
                found[key] = value
        for key in wanted:
            if key not in found:
                raise RouteError(f"The guest did not report {key}: {text[-300:]!r}")
        return found

    def lane_is_free(self, timeout: float) -> str:
        return self._run("lane", "--expect", "free", timeout=timeout)


def _git(repo: pathlib.Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def run_drivecheck(*, guest: Any, run_dir: pathlib.Path, holder: str,
                   audio_proof: pathlib.Path, repo: pathlib.Path | None = None,
                   script: pathlib.Path = REPO_SCRIPT,
                   pipe_factory: Callable[[float], Any] | None = None,
                   clock: Callable[[], float] = time.monotonic,
                   sleep: Callable[[float], None] = time.sleep,
                   argv: list[str] | None = None) -> dict[str, Any]:
    """Run the probe once and write `run.jsonl` and `summary.json` under `run_dir`.

    Refuses, before touching the guest's lane, a stale or missing audio proof and
    a deployed `winuae.ps1` that is not this repository's copy. From the claim on
    it always stops only its own emulator, fetches and hashes every staged disk,
    releases the claim and records whether the lane is free.
    """
    audio_proof = pathlib.Path(audio_proof)
    if not _mute_proof(audio_proof):
        raise RouteError("The Windows VM audio mute has not been verified")
    if run_dir.exists():
        raise RouteError(f"The run directory {run_dir} already exists")
    repo = repo or pathlib.Path(__file__).resolve().parents[2]
    started = clock()
    deployed = guest.deployed(timeout=30)
    want = sha256(script)
    if deployed["winuae_ps1_sha256"].lower() != want.lower():
        raise RouteError(
            f"The deployed {DEPLOYED_SCRIPT} hashes {deployed['winuae_ps1_sha256'].lower()}, "
            f"not this repository's {want}; copy it with `winvm put` first")
    pipe_factory = pipe_factory or (lambda timeout: amiga.WinuaePipe(timeout=timeout))

    scratch.ensure(run_dir / "images")
    remotes = {k: f"C:/Amiga/Disks/wish{ISSUE}-{holder}-probe{k}.adf" for k in KEYS}
    windows = {k: v.replace("/", "\\") for k, v in remotes.items()}
    foreign = f"C:\\Amiga\\Disks\\wish{ISSUE}-{INTRUDER}-probeB.adf"
    never = f"C:\\Amiga\\Disks\\wish{ISSUE}-{holder}-probeZ.adf"
    generated: dict[str, dict[str, str]] = {}
    for key in KEYS:
        path = run_dir / "images" / f"probe{key}.adf"
        path.write_bytes(make_adf(key))
        generated[key] = {"path": str(path), "sha256": sha256(path)}
    if len({entry["sha256"] for entry in generated.values()}) != 3:
        raise RouteError("The three generated disks are not distinct")

    log_file = (run_dir / "run.jsonl").open("a", encoding="utf-8")
    result: dict[str, Any] = {
        "issue": ISSUE, "holder": holder, "argv": argv or [],
        "sha": _git(repo, "rev-parse", "HEAD") or "unknown",
        "dirty": bool(_git(repo, "status", "--porcelain")),
        "deployed": deployed, "repository_winuae_ps1_sha256": want,
        "generated": generated, "steps": [], "passed": False, "error": "",
        "fetched": {}, "unchanged": {},
    }

    def log(event: str, **fields: Any) -> None:
        log_file.write(json.dumps({"event": event, "t": round(clock() - started, 3),
                                   **fields}, sort_keys=True, default=str) + "\n")
        log_file.flush()

    def step(name: str, verdict: str, **fields: Any) -> None:
        result["steps"].append({"step": name, "verdict": verdict, **fields})
        log("step", step=name, verdict=verdict, **fields)

    deadline = started + PROBE_SECONDS

    def left() -> float:
        return deadline - clock()

    def limit(seconds: float) -> float:
        """A call's timeout: no more than the probing phase has left."""
        if left() <= 0:
            raise RouteError(f"The {PROBE_SECONDS:.0f} s probing budget is spent")
        return min(seconds, left())

    def insert_limit() -> float:
        """A floppy change needs its 10 s poll and the round trip around it."""
        if left() < 20:
            raise RouteError("Less than 20 s of the probing budget is left for a floppy change")
        return min(60.0, left())

    def read_drives(name: str, paths: dict[int, str], *, modes=("rw", "rw")) -> dict:
        receipt = pipe_factory(limit(30)).drives(holder)
        state = receipt.drive_state()
        got = {0: state["paths"][0], 1: state["paths"][1]}
        ok = got == paths and (state["modes"][0], state["modes"][1]) == tuple(modes)
        step(name, "pass" if ok else "fail", expected={"paths": {f"DF{n}": v for n, v in paths.items()},
                                                     "modes": list(modes)},
             observed={"paths": {f"DF{n}": v for n, v in got.items()},
                       "modes": [state["modes"][0], state["modes"][1]]},
             receipt=receipt.as_dict())
        if not ok:
            raise RouteError(f"{name}: the drives are not as expected: {got} {state['modes']}")
        return state

    def change(name: str, drive: int, key: str, paths: dict[int, str]) -> None:
        receipt = guest_insert(drive, windows[key], generated[key]["sha256"])
        step(name, "pass", receipt=receipt.as_dict())
        read_drives(f"{name}: readback", paths)

    def guest_insert(drive: int, path: str, digest: str):
        return pipe_factory(insert_limit()).insert_floppy(
            drive, path, holder, digest, staged=guest.staged)

    def refused(name: str, call: Callable[[], Any], error: type, needle: str) -> str:
        """Run a request that must be refused and pin the reason it gives.

        A guest refusal is matched on the guest's own `fail` line, so a transport
        or PowerShell error can never stand in for one.
        """
        try:
            said = call()
        except Exception as exc:
            text = exc.line if isinstance(exc, amiga.GuestRefusal) else str(exc)
            if not isinstance(exc, error):
                step(name, "fail", expected=needle, observed=text)
                raise RouteError(f"{name}: not refused as expected: {text}") from exc
            if needle not in text:
                step(name, "fail", expected=needle, observed=text)
                raise RouteError(f"{name}: refused, but not for the expected reason: {text}") from exc
            step(name, "pass", refusal=text)
            return text
        step(name, "fail", expected=needle, observed=said or "accepted")
        raise RouteError(f"{name}: the request was accepted: {said}")

    claimed = copied = start_attempted = stopped = False
    try:
        receipt = guest.claim(holder, timeout=limit(30))
        if receipt != f"ok claimed by {holder}":
            raise RouteError(f"The claim was not new: {receipt!r}")
        claimed = True
        step("claim", "pass", receipt=receipt)
        for key in KEYS:
            guest.put(pathlib.Path(generated[key]["path"]), remotes[key], timeout=limit(60))
        copied = True
        step("stage", "pass", disks={k: remotes[k] for k in KEYS})
        if not _mute_proof(audio_proof):
            raise RouteError("The Windows VM audio mute proof expired before WinUAE start")
        start_attempted = True
        receipt = guest.start(holder, remotes["A"], remotes["C"], timeout=limit(60))
        step("start", "pass", receipt=receipt)
        wait_until = min(deadline, clock() + READY_SECONDS)
        while True:
            try:
                pipe_factory(limit(30)).drives(holder)
                break
            except (amiga.GuestError, amiga.NotConnected) as exc:
                if clock() >= wait_until:
                    raise RouteError(f"The pipe never answered `drives`: {exc}") from exc
                sleep(2.0)
        step("ready", "pass")
        both = {0: windows["A"], 1: windows["C"]}
        read_drives("baseline", both)
        change("swap DF0 to B", 0, "B", {0: windows["B"], 1: windows["C"]})
        change("restore DF0 to A", 0, "A", both)

        def wrong_holder():
            return pipe_factory(limit(30)).refused_verb(
                "insert", INTRUDER, ["0", windows["B"], generated["B"]["sha256"]])

        refused("control: another holder's claim", wrong_holder, amiga.GuestRefusal,
                f"claimed by {holder}")
        read_drives("control: another holder's claim leaves both drives", both)

        refused("control: another holder's path, refused in Python",
                lambda: guest_insert(0, foreign, generated["B"]["sha256"]),
                ValueError, "belongs to another holder")
        refused("control: another holder's path, refused in the guest",
                lambda: pipe_factory(limit(30)).refused_verb(
                    "insert", holder, ["0", foreign, generated["B"]["sha256"]]),
                amiga.GuestRefusal, f"is not staged for {holder}")
        read_drives("control: another holder's path leaves both drives", both)

        refused("control: a file never staged, refused in Python",
                lambda: guest_insert(0, never, generated["B"]["sha256"]),
                ValueError, "is not a disk this run staged")
        refused("control: a file never staged, refused in the guest",
                lambda: pipe_factory(limit(30)).refused_verb(
                    "insert", holder, ["0", never, generated["B"]["sha256"]]),
                amiga.GuestRefusal, "does not exist")
        read_drives("control: a file never staged leaves both drives", both)

        again = guest_insert(0, windows["A"], generated["A"]["sha256"])
        replies = {r["label"] for r in again.as_dict()["replies"]}
        same = again.already and "set" not in replies
        step("control: the same path twice", "pass" if same else "fail",
             receipt=again.as_dict())
        if not same:
            raise RouteError("The same path twice sent a setter or was not reported as already loaded")
        read_drives("control: the same path leaves both drives", both)

        result["passed"] = all(s["verdict"] in ("pass", "info") for s in result["steps"])
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        step("stopped", "fail", error=result["error"])
    finally:
        cleanup_deadline = clock() + CLEANUP_SECONDS

        def cleanup_limit(seconds: float) -> float:
            return max(1.0, min(seconds, cleanup_deadline - clock()))

        if start_attempted:
            try:
                result["stop"] = guest.stop(holder, timeout=cleanup_limit(30))
                stopped = True
                log("stop", receipt=result["stop"])
            except BaseException as exc:
                result["stop_error"] = f"{type(exc).__name__}: {exc}"
        if copied:
            for key in KEYS:
                local = run_dir / f"fetched-probe{key}.adf"
                try:
                    guest.get(remotes[key], local, timeout=cleanup_limit(60))
                    result["fetched"][key] = {"path": str(local), "sha256": sha256(local)}
                    result["unchanged"][key] = (
                        result["fetched"][key]["sha256"] == generated[key]["sha256"])
                    log("fetch", disk=key, **result["fetched"][key])
                except BaseException as exc:
                    result[f"fetch_{key}_error"] = f"{type(exc).__name__}: {exc}"
        if claimed and (not start_attempted or stopped):
            try:
                result["release"] = guest.release(holder, timeout=cleanup_limit(30))
                log("release", receipt=result["release"])
            except BaseException as exc:
                result["release_error"] = f"{type(exc).__name__}: {exc}"
        if claimed:
            try:
                result["lane"] = guest.lane_is_free(cleanup_limit(30))
            except BaseException as exc:
                result["lane_error"] = f"{type(exc).__name__}: {exc}"
        clean = (not start_attempted or stopped) and not any(
            k.endswith("_error") for k in result)
        result["cleaned_up"] = bool(clean)
        if result["passed"] and (not clean or not all(result["unchanged"].values())
                                 or len(result["unchanged"]) != 3):
            result["passed"] = False
            result["error"] = result["error"] or "Cleanup failed or a staged disk changed"
        result["elapsed_seconds"] = round(clock() - started, 3)
        (run_dir / "summary.json").write_text(
            json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
        log_file.close()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-proof", required=True, type=pathlib.Path,
                        help="a Windows VM audio mute readback no older than five minutes")
    parser.add_argument("--holder", default=None,
                        help="the lane holder name (default: a fresh wish679-<random>)")
    args = parser.parse_args(argv)
    holder = args.holder or f"wish{ISSUE}-{uuid.uuid4().hex[:12]}"
    repo = pathlib.Path(__file__).resolve().parents[2]
    sha = _git(repo, "rev-parse", "HEAD")[:10] or "unknown"
    run_dir = scratch.cache_dir("acceptance", ISSUE, f"{sha}-amiga-drivecheck")
    try:
        with terminating():
            result = run_drivecheck(
                guest=ProbeGuest(), run_dir=run_dir, holder=holder,
                audio_proof=args.audio_proof,
                argv=list(sys.argv[1:] if argv is None else argv))
    except Terminated as exc:
        print(f"Amigadrivecheck: {exc}", file=sys.stderr)
        return 2
    except (RouteError, OSError, ValueError) as exc:
        print(f"Amigadrivecheck: {exc}", file=sys.stderr)
        return 2
    print(f"Drive check {'passed' if result['passed'] else 'failed'}: {run_dir / 'summary.json'}")
    for entry in result["steps"]:
        print(f"{entry['verdict'].upper()}: {entry['step']}")
    if result["error"]:
        print(f"Error: {result['error']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
