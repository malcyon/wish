#!/usr/bin/env python3
"""Run the app's own Amiga Fast Travel against a live Amiga title under WinUAE.

`automap.amigafasttravel.AmigaFastTravel` is built over an `AmigaTarget` on a
`WinuaePipe`, and one trip is made the way the automap window's timer makes it:
`legality`, then `apply`, then `continue_pending` every 200 ms until no trip and
no second hop remain. Every memory write comes from that code; this driver
writes nothing of its own, and a trip still armed when the run ends for any
reason is disarmed.

    tools/amiga/fasttravelrun.py --holder wish1-f4a --disks DIR --to 5 --answer y --out OUT

`--title KEY` is the `amiga.MACHINES` key of the title in the machine
(`pool-of-radiance` by default); it picks the machine, the trip row and the
area table. `--to` is the destination area id. `--answer KEY` presses KEY once, when the
door key has been taken, the area byte is still the starting area and the
screen differs from the one before the trip (the game is asking something).
`--back` makes `apply_back` once the trip has finished.
`--waypoint AREA,X,Y,F` stages `fasttravel.back` as a party that stood on that
square of that area, and with `--back` and no `--to` the run makes `apply_back`
alone; it is staged input, for a Return no forward trip of this run produced.
`--measure-row` makes the title's trip row confirmed, with every difference
offered, for this process only, so a title whose row is not yet confirmed can be
measured; the row is put back when the run ends and the log records it.
`--peek-var V[,V...]` (hex, `$` or `0x` optional) reads script variables through
`automap.amigavars` before and after each leg and logs them as `peek` events;
a variable the title's map cannot address is logged with the reason. The lane claim is the
caller's, as in `amigadrive.py`.

OUT/fasttravel.jsonl holds one line per event: the verdict, each outcome, every
poll's area byte, square and the step-entry words (`amigatrip.entry_words`:
five on Pool of Radiance, one on the other titles), the party's names before
and after each trip, every screenshot and every key pressed. A trip's result
carries `areas_seen`: the starting area, then each area byte the polls read,
repeats dropped, so a trip that passes through another area shows it. A screenshot is kept as
OUT/NNN.png only when it differs from the one before it. Every wait is
bounded: the poll loop by `--budget` seconds (a trip or hop still waiting then
is cancelled and the run ends nonzero), and an answer by `ANSWER_SECONDS`
once nothing else is pending. The final screenshot waits for the game's menu
gate and then `SETTLE_SECONDS`, bounded by the same budget.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
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
from automap import (  # noqa: E402
    amiga,
    amigafasttravel,
    amigaparty,
    amigatrip,
    amigavars,
)
from goldbox import areas as goldbox_areas  # noqa: E402
from tools.amiga import amigakeys, tripprobe  # noqa: E402

DEFAULT_TITLE = "pool-of-radiance"

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


def parse_waypoint(text: str) -> engine.Waypoint:
    """`AREA,X,Y,F` as the Waypoint a trip from that square would have left behind."""
    parts = text.split(",")
    if len(parts) != 4:
        raise ValueError(text)
    area, x, y, facing = (int(part, 0) for part in parts)
    return engine.Waypoint(area, None, (x, y, facing))


@contextlib.contextmanager
def measuring_row(key: str, log: Callable[..., None]):
    """Swap `key`'s trip row for a confirmed one with no held difference, then put it back.

    `legality` answers `not_built` for an unconfirmed row, which would keep the
    first live run that confirms the row from ever arming a trip.
    """
    original = amigatrip.ROWS[key]
    try:
        amigatrip.ROWS[key] = dataclasses.replace(
            original, confirmed=True,
            differences=tuple(dataclasses.replace(d, offered=True) for d in original.differences))
        log("measure_row", title=key, was_confirmed=original.confirmed,
            newly_offered=[d.name for d in original.differences if not d.offered])
        yield amigatrip.ROWS[key]
    finally:
        amigatrip.ROWS[key] = original


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
    return {"area": amigatrip.area_id(target, row),
            "square": amigatrip.square(target, row),
            "entry_words": amigatrip.entry_words(target, row).hex()}


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


def _names(party, target) -> list[str] | None:
    """The party's names, or None when no reader is given or the list does not decode."""
    members = party(target) if party is not None else None
    return None if members is None else [m.name for m in members]


def _peek(target, title, variables, why: str, log: Log) -> None:
    if variables:
        log("peek", why=why, variables=[
            r.as_log() for r in amigavars.read_variables(target, title, variables)])


def _settle(target, row, log: Log, sleep, clock, budget: float) -> bool:
    """Wait for the game to sit at its menu again, then `SETTLE_SECONDS`, before the last shot.

    The trip is idle when the area byte has changed, but the game is still
    drawing the arrival; a shot then matches the one before the second hop.
    Returns whether the gate passed.
    """
    began = clock()
    while not amigatrip.gate(target, row) and clock() - began < budget:
        sleep(POLL_SECONDS)
    passed = bool(amigatrip.gate(target, row))
    log("settle", gate=passed, waited=round(clock() - began, 3))
    sleep(SETTLE_SECONDS)
    return passed


def run_trip(fasttravel, target, row, area, out: pathlib.Path,
             shot: Callable[[pathlib.Path], object], press: Callable[[str], object],
             log: Log, answer: str | None = None, back: bool = False,
             sleep: Callable[[float], None] = time.sleep,
             clock: Callable[[], float] = time.monotonic,
             budget: float = BUDGET_SECONDS, party: Callable | None = None,
             peek_vars=(), title: str | None = None) -> dict:
    """One trip, or the way back, driven as the window's timer drives it.

    Returns `{"result": ..., "outcomes": [...], "answered": bool, "settled": bool, ...}`
    where result is `not_legal`, `not_applied`, `idle` (no trip or hop left) or
    `timeout`; `settled` is False when an idle game never reached the menu gate;
    `areas_seen` is the starting area and then each new area byte the polls
    read. `party` reads the party (as `amigaparty.read_party`); its names are
    logged and returned before and after the trip. `peek_vars` are read
    through `amigavars` for `title` before and after, and logged.
    """
    verdict = fasttravel.back_verdict(target) if back else fasttravel.legality(target, area)
    log("legality", ok=bool(verdict), reason=verdict.reason, back=back)
    summary = {"result": "not_legal", "outcomes": [], "answered": False,
               "settled": True, "areas_seen": [], "party_before": None, "party_after": None}
    if not verdict:
        return summary
    screen = _Screen(out, shot, log)
    screen.take("before")
    baseline = screen.last
    before = _reading(target, row)
    log("read", why="before", **before)
    summary["areas_seen"] = [before["area"]]
    _peek(target, title, peek_vars, "before", log)
    summary["party_before"] = _names(party, target)
    if party is not None:
        log("party", why="before", names=summary["party_before"])

    def seen(area) -> None:
        if area is not None and area != summary["areas_seen"][-1]:
            summary["areas_seen"].append(area)
    outcome = fasttravel.apply_back(target) if back else fasttravel.apply(target, area=area)
    try:
        log("apply", ok=outcome.ok, message=outcome.message,
            writes=[[hex(a), d.hex()] for a, d in outcome.writes], notes=list(outcome.notes))
        summary["outcomes"].append({"ok": outcome.ok, "message": outcome.message})
        if not outcome.ok:
            summary["result"] = "not_applied"
            return summary
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
            seen(now["area"])
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
        except Exception as failed:
            print(f"disarm failed ({failed!r}); the game may still hold the armed trip",
                  file=sys.stderr)
        raise
    if summary["result"] == "timeout":
        _disarm(fasttravel, target)
        log("timeout", budget=budget)
    if summary["result"] == "idle":
        summary["settled"] = _settle(target, row, log, sleep, clock, budget)
    screen.take("after")
    last = _reading(target, row)
    seen(last["area"])
    log("read", why="after", **last)
    _peek(target, title, peek_vars, "after", log)
    summary["party_after"] = _names(party, target)
    if party is not None:
        log("party", why="after", names=summary["party_after"])
    return summary


def candidate_areas(title: str) -> list:
    """Every area of `title`, from the table `main` looks a destination up in."""
    rows = list(engine.area_rows(title)) or list(goldbox_areas.areas_for(title))
    return [row for row in rows if getattr(row, "id", None) is not None]


def legality_report(fasttravel, target, rows) -> list[str]:
    """One line per area: its id, name, whether Fast Travel offers it, and why not."""
    lines = []
    for row in rows:
        verdict = fasttravel.legality(target, row)
        name = getattr(row, "name", None) or ""
        state = "offered" if verdict else "withheld"
        lines.append(f"{row.id}\t{name}\t{state}\t{verdict.reason}".rstrip("\t"))
    return lines


def main(argv: list[str] | None = None) -> int:
    from tools.amiga import amigadrive  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holder", required=True, help="the winuae.ps1 lane claim this run holds")
    parser.add_argument("--disks", required=True, help="the folder of the title's ADFs")
    parser.add_argument("--title", default=DEFAULT_TITLE, choices=sorted(amiga.MACHINES),
                        help="the amiga.MACHINES key of the title in the machine")
    parser.add_argument("--to", type=int, help="the destination area id")
    parser.add_argument("--legality", action="store_true",
                        help="print each area with its legality verdict and make no trip")
    parser.add_argument("--answer", help="the key that answers the game's question")
    parser.add_argument("--back", action="store_true",
                        help="make apply_back once the trip has finished")
    parser.add_argument("--waypoint", metavar="AREA,X,Y,F",
                        help="stage the way back to this square; needs --back and no --to")
    parser.add_argument("--measure-row", action="store_true",
                        help="treat the title's trip row as confirmed, every difference offered, "
                             "for this process only")
    parser.add_argument("--peek-var", default="",
                        help="comma-separated hex script variables to read before and after each leg")
    parser.add_argument("--budget", type=float, default=BUDGET_SECONDS,
                        help="seconds each trip may take")
    parser.add_argument("--out", help="directory for the log and screenshots")
    args = parser.parse_args(argv)
    waypoint = None
    if args.waypoint is not None:
        try:
            waypoint = parse_waypoint(args.waypoint)
        except ValueError:
            parser.error(f"--waypoint {args.waypoint!r} is not AREA,X,Y,F")
        if not args.back:
            parser.error("--waypoint needs --back")
        if args.to is not None:
            parser.error("--waypoint is the way back of a run with no --to")
    if not args.legality and ((args.to is None and waypoint is None) or args.out is None):
        parser.error("--to and --out are required unless --legality is given")
    if args.answer is not None:
        try:
            amigakeys.lookup(args.answer)
        except KeyError:
            parser.error(f"--answer {args.answer!r} is not a key name")
    try:
        peek_vars = amigavars.parse_list(args.peek_var)
    except ValueError:
        parser.error(f"--peek-var {args.peek_var!r} is not a list of hex numbers")
    machine = amiga.MACHINES[args.title]
    if args.legality:
        pipe = amiga.WinuaePipe(holder=args.holder)
        target = amiga.AmigaTarget(pipe, machine)
        try:
            target.locate()
        except (DriverError, amiga.GuestError) as exc:
            raise SystemExit(str(exc)) from exc
        fasttravel = amigafasttravel.AmigaFastTravel(args.title, args.disks)
        print("\n".join(legality_report(fasttravel, target, candidate_areas(machine.title))))
        return 0
    # area_by_id is empty for a title the C64 fast travel does not support, which
    # Pools of Darkness is; the Amiga legality check decides what is offered.
    area = None if args.to is None else (
        engine.area_by_id(args.to, machine.title)
        or goldbox_areas.area_in(args.to, machine.title))
    if args.to is not None and area is None:
        parser.error(f"--to {args.to} is not an area of {machine.title}")
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pipe = amiga.WinuaePipe(holder=args.holder)
    target = amiga.AmigaTarget(pipe, machine)
    fasttravel = amigafasttravel.AmigaFastTravel(args.title, args.disks)
    if waypoint is not None:
        fasttravel.back = waypoint

    def shot(path: pathlib.Path) -> None:
        amigadrive.shot(args.holder, path)

    def press(key: str) -> None:
        amigadrive.press(args.holder, key, SETTLE_SECONDS)

    try:
        target.locate()
        with open(out / "fasttravel.jsonl", "w") as stream:
            log = Log(stream, time.monotonic)
            with (measuring_row(args.title, log) if args.measure_row
                  else contextlib.nullcontext()):
                row = amigatrip.row_for(args.title)
                results = []
                if area is not None:
                    results.append(run_trip(fasttravel, target, row, area, out, shot, press, log,
                                            answer=args.answer, budget=args.budget,
                                            party=amigaparty.read_party,
                                            peek_vars=peek_vars, title=args.title))
                if args.back and results and results[0]["result"] == "idle" \
                        and not results[0]["settled"]:
                    results.append({"result": "skipped", "reason": "leg 1 never became ready"})
                elif args.back and (not results or results[0]["result"] == "idle"):
                    results.append(run_trip(fasttravel, target, row, None, out, shot, press, log,
                                            back=True, budget=args.budget,
                                            party=amigaparty.read_party,
                                            peek_vars=peek_vars, title=args.title))
    except (DriverError, amiga.GuestError) as exc:
        raise SystemExit(str(exc)) from exc
    for result in results:
        print(json.dumps(result))
    for number, result in enumerate(results, 1):
        if not result.get("settled", True):
            leg = "the way back" if number > 1 else "the trip"
            print(f"Leg {number} ({leg}) never became ready for Fast Travel.", file=sys.stderr)
            return 1
    return 0 if all(r["result"] == "idle" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
