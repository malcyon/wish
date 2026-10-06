#!/usr/bin/env python3
"""Run the app's own Amiga Fast Travel against a live Pool of Radiance under WinUAE.

`automap.amigafasttravel.AmigaFastTravel` is built over an `AmigaTarget` on a
`WinuaePipe`, and one trip is made the way the automap window's timer makes it:
`legality`, then `apply`, then `continue_pending` every 200 ms until no trip and
no second hop remain. Every memory write comes from that code; this driver
writes nothing of its own, and a trip still armed when the run ends for any
reason is disarmed.

    tools/amiga/fasttravelrun.py --holder wish1-f4a --disks DIR --to 5 --answer y --out OUT

`--to` is the destination area id. `--answer KEY` presses KEY once, when the
door key has been taken, the area byte is still the starting area and the
screen differs from the one before the trip (the game is asking something).
`--back` makes `apply_back` once the trip has finished. The lane claim is the
caller's, as in `amigadrive.py`.

OUT/fasttravel.jsonl holds one line per event: the verdict, each outcome, every
poll's area byte, square and the five step-entry words (`$AA` to `$B3` of the
data hunk), every screenshot and every key pressed. A screenshot is kept as
OUT/NNN.png only when it differs from the one before it. Every wait is
bounded: the poll loop by `--budget` seconds (a trip or hop still waiting then
is cancelled and the run ends nonzero), and an answer by `ANSWER_SECONDS`
once nothing else is pending.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import time
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from automap import actions as engine  # noqa: E402
from automap import amiga, amigafasttravel, amigatrip  # noqa: E402
from tools.amiga import amigakeys, tripprobe  # noqa: E402

KEY = "pool-of-radiance"

#: Seconds between two `continue_pending` calls, as the window's timer.
POLL_SECONDS = 0.2
#: The longest a whole run waits for the trip and any second hop.
BUDGET_SECONDS = 150.0
#: Seconds between screenshots while a trip or an answer is outstanding.
SHOT_SECONDS = 2.0
#: How long an unanswered `--answer` waits for the screen once nothing else is pending.
ANSWER_SECONDS = 20.0
#: Seconds the game takes to act on a key, after it is pressed.
SETTLE_SECONDS = 3.0

#: Bytes of the data hunk's step-entry words: five words from `row.step_entry`.
ENTRY_BYTES = 10


class DriverError(RuntimeError):
    """The run cannot go on."""


def _disarm(fasttravel, target) -> None:
    """Put an armed trip's statements and key back in the game, then forget the trip."""
    trip = fasttravel.trip
    try:
        if trip is not None:
            amigatrip.disarm(target, trip.armed)
    finally:
        fasttravel.cancel_pending()


class Log:
    """JSON lines, each stamped with seconds since the run began."""

    def __init__(self, stream, clock: Callable[[], float]):
        self.stream = stream
        self.clock = clock
        self.began = clock()

    def __call__(self, event: str, **fields) -> None:
        self.stream.write(json.dumps(
            {"t": round(self.clock() - self.began, 3), "event": event, **fields}) + "\n")
        self.stream.flush()


def _reading(target, row) -> dict:
    base = target.data_base
    return {"area": amigatrip.area_id(target, row),
            "square": amigatrip.square(target, row),
            "entry_words": target.read(base + row.step_entry, ENTRY_BYTES).hex()}


class _Screen:
    """Screenshots kept only when they differ from the last one kept."""

    def __init__(self, out: pathlib.Path, shot: Callable[[pathlib.Path], object], log: Log):
        self.out, self.shot, self.log = out, shot, log
        self.count = 0
        self.last: bytes | None = None
        self.digest: str | None = None

    def take(self, why: str) -> bool:
        """Photograph the screen; True when it differs from the last kept one."""
        scratch = self.out / "current.png"
        self.shot(scratch)
        data = scratch.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        changed = digest != self.digest
        name = None
        if changed:
            self.count += 1
            name = f"{self.count:03d}.png"
            scratch.replace(self.out / name)
            self.last, self.digest = data, digest
        else:
            scratch.unlink()
        self.log("screenshot", why=why, file=name, changed=changed, sha256=digest)
        return changed


def run_trip(fasttravel, target, row, area, out: pathlib.Path,
             shot: Callable[[pathlib.Path], object], press: Callable[[str], object],
             log: Log, answer: str | None = None, back: bool = False,
             sleep: Callable[[float], None] = time.sleep,
             clock: Callable[[], float] = time.monotonic,
             budget: float = BUDGET_SECONDS) -> dict:
    """One trip, or the way back, driven as the window's timer drives it.

    Returns `{"result": ..., "outcomes": [...], "answered": bool}` where result
    is `not_legal`, `not_applied`, `idle` (no trip or hop left) or `timeout`.
    """
    verdict = fasttravel.back_verdict(target) if back else fasttravel.legality(target, area)
    log("legality", ok=bool(verdict), reason=verdict.reason, back=back)
    summary = {"result": "not_legal", "outcomes": [], "answered": False}
    if not verdict:
        return summary
    screen = _Screen(out, shot, log)
    screen.take("before")
    baseline = screen.last
    before = _reading(target, row)
    log("read", why="before", **before)
    outcome = fasttravel.apply_back(target) if back else fasttravel.apply(target, area=area)
    log("apply", ok=outcome.ok, message=outcome.message,
        writes=[[hex(a), d.hex()] for a, d in outcome.writes], notes=list(outcome.notes))
    summary["outcomes"].append({"ok": outcome.ok, "message": outcome.message})
    if not outcome.ok:
        summary["result"] = "not_applied"
        return summary

    try:
        started = clock()
        next_shot = started
        idle_since = None
        summary["result"] = "timeout"
        while clock() - started < budget:
            sleep(POLL_SECONDS)
            got = fasttravel.continue_pending(target)
            if got is not None:
                log("continue", ok=got.ok, message=got.message)
                summary["outcomes"].append({"ok": got.ok, "message": got.message})
            now = _reading(target, row)
            taken = tripprobe.key_taken(target, row)
            log("read", why="poll", key_taken=taken, trip=fasttravel.trip is not None,
                pending=fasttravel.pending is not None, **now)
            waiting = answer is not None and not summary["answered"]
            if clock() >= next_shot and (fasttravel.trip is not None
                                         or fasttravel.pending is not None or waiting):
                next_shot = clock() + SHOT_SECONDS
                screen.take("poll")
                if waiting:
                    why = tripprobe._unanswered(
                        {"key_taken": taken, "area_changed": now["area"] != before["area"]},
                        baseline, screen.last)
                    if why is None:
                        log("answer", key=answer)
                        press(answer)
                        summary["answered"] = True
                        sleep(SETTLE_SECONDS)
                    else:
                        log("answer_held", reason=why)
            if fasttravel.trip is None and fasttravel.pending is None:
                idle_since = clock() if idle_since is None else idle_since
                if not (answer is not None and not summary["answered"]) \
                        or clock() - idle_since >= ANSWER_SECONDS:
                    summary["result"] = "idle"
                    break
            else:
                idle_since = None
    except BaseException:
        # An armed trip left in the game is put back before the exception goes on.
        try:
            _disarm(fasttravel, target)
        except Exception:  # noqa: S110 - the first exception is the one to report
            pass
        raise
    if summary["result"] == "timeout":
        _disarm(fasttravel, target)
        log("timeout", budget=budget)
    screen.take("after")
    log("read", why="after", **_reading(target, row))
    return summary


def main(argv: list[str] | None = None) -> int:
    from tools.amiga import amigadrive  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holder", required=True, help="the winuae.ps1 lane claim this run holds")
    parser.add_argument("--disks", required=True, help="the folder of the title's ADFs")
    parser.add_argument("--to", type=int, required=True, help="the destination area id")
    parser.add_argument("--answer", help="the key that answers the game's question")
    parser.add_argument("--back", action="store_true",
                        help="make apply_back once the trip has finished")
    parser.add_argument("--budget", type=float, default=BUDGET_SECONDS,
                        help="seconds each trip may take")
    parser.add_argument("--out", required=True, help="directory for the log and screenshots")
    args = parser.parse_args(argv)
    if args.answer is not None:
        try:
            amigakeys.lookup(args.answer)
        except KeyError:
            parser.error(f"--answer {args.answer!r} is not a key name")
    machine = amiga.MACHINES[KEY]
    area = engine.area_by_id(args.to, machine.title)
    if area is None:
        parser.error(f"--to {args.to} is not an area of {machine.title}")
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pipe = amiga.WinuaePipe(holder=args.holder)
    target = amiga.AmigaTarget(pipe, machine)
    row = amigatrip.row_for(KEY)
    fasttravel = amigafasttravel.AmigaFastTravel(KEY, args.disks)

    def shot(path: pathlib.Path) -> None:
        amigadrive.shot(args.holder, path)

    def press(key: str) -> None:
        amigadrive.press(args.holder, key, SETTLE_SECONDS)

    try:
        target.locate()
        with open(out / "fasttravel.jsonl", "w") as stream:
            log = Log(stream, time.monotonic)
            results = [run_trip(fasttravel, target, row, area, out, shot, press, log,
                                answer=args.answer, budget=args.budget)]
            if args.back and results[0]["result"] == "idle":
                results.append(run_trip(fasttravel, target, row, None, out, shot, press, log,
                                        back=True, budget=args.budget))
    except (DriverError, amiga.GuestError) as exc:
        raise SystemExit(str(exc)) from exc
    for result in results:
        print(json.dumps(result))
    return 0 if all(r["result"] == "idle" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
