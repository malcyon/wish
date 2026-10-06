#!/usr/bin/env python3
"""Run the app's own Fast Travel against a live C64 Pool of Radiance and log every trip.

`automap.actions.FastTravel` is applied through a `ViceTarget` on the session's
monitor port, one trip per `--to`, in order, with `continue_pending` called every
poll so a two-hop trip makes its second hop. Every memory write comes from that
code; the driver writes nothing of its own and fails on any write that
touches the random-number generator (`$03C2`-`$03C8`).

    tools/c64/fasttravelrun.py --save SPECIMEN.D64 --to 18 --to 2 --to 15 --answer YES

A trip has arrived when `$6E1B` and `$49F2` both equal the destination and
`legality` toward a different area passes; a check toward the destination
itself answers "already in that area" and proves nothing. Each poll first lets
`Session.handle_prompt` answer an `insert a disk` prompt, and only then
presses RETURN, and only on a `PRESS ...` message: the move sub-bar
`I,J,K,M, RETURN OR BUTTON` is left alone. `--answer WORD` selects that word
on a bar offering it (`YES NO`, at most `ANSWERS_PER_TRIP` times a trip).
A "cannot act right now" answer from `legality` or `apply` is retried every
`BUSY_SECONDS`, at most `BUSY_TRIES` times.

OUT/run.jsonl holds one line per event; screenshots sit beside it. OUT defaults
to a directory under `~/.cache/wish/fasttravel`. The emulator slot is claimed
from the pool (`--slot` names one) and released on every exit, and a trip still
pending when the run ends is cancelled.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import sys
import time
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from automap import actions as engine  # noqa: E402
from automap.target import NotConnected  # noqa: E402

#: Seconds between two `continue_pending` calls.
POLL_SECONDS = 0.2
#: Seconds between two looks at the screen while a trip is outstanding.
SCREEN_SECONDS = 2.0
#: Seconds a leg may take.
BUDGET_SECONDS = 180.0
#: Seconds between two tries of a call that answered "cannot act right now".
BUSY_SECONDS = 0.5
#: Tries of such a call before the leg is given up.
BUSY_TRIES = 40
#: Tries of one connection to the monitor before the run gives up.
CONNECT_TRIES = 5
#: Times one leg answers a bar with `--answer`.
ANSWERS_PER_TRIP = 4
#: Seconds the game takes to draw an arrival, before the last screenshot.
SETTLE_SECONDS = 3.0
#: Every Nth screen look also takes a screenshot.
SHOT_EVERY = 4

#: The generator's seven bytes.
RNG_FIRST, RNG_LAST = 0x03C2, 0x03C8
MOVE_SUBBAR = "I,J,K,M"
#: A script's acknowledgement, which is answered with RETURN.
RETURN_MESSAGE = "PRESS"


class DriverError(RuntimeError):
    """The run cannot go on."""


class GuardedTarget:
    """A target that fails on any write touching the generator and passes the rest on."""

    def __init__(self, target):
        self._target = target

    def write(self, addr: int, data: bytes) -> None:
        if addr <= RNG_LAST and addr + len(data) - 1 >= RNG_FIRST:
            raise DriverError(
                f"write of {len(data)} bytes at ${addr:04X} touches the random-number "
                f"generator ${RNG_FIRST:04X}-${RNG_LAST:04X}")
        self._target.write(addr, data)

    def __getattr__(self, name):
        return getattr(self._target, name)


class Log:
    """JSON lines, each stamped with seconds since the run began."""

    def __init__(self, stream, clock: Callable[[], float]):
        self.stream = stream
        self.clock = clock
        self.began = clock()

    def __call__(self, event: str, **fields) -> None:
        self.stream.write(json.dumps(
            {"t": round(self.clock() - self.began, 3), "event": event, **fields},
            default=repr) + "\n")
        self.stream.flush()


def _byte(target, addr: int) -> int:
    return bytes(target.read(addr, 1))[0]


def reading(target) -> dict:
    return {"area6E1B": _byte(target, 0x6E1B), "script49F2": _byte(target, 0x49F2)}


def other_area(dest: int) -> int:
    """An area to ask legality about that is not the destination."""
    return 2 if dest != 2 else 18


class Driver:
    """The trips of one session."""

    def __init__(self, sess, connect: Callable[[], object], fasttravel, out: pathlib.Path,
                 log: Log, answer: str | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 budget: float = BUDGET_SECONDS):
        self.sess, self.connect, self.ft = sess, connect, fasttravel
        self.out, self.log, self.answer = out, log, answer
        self.sleep, self.clock, self.budget = sleep, clock, budget
        #: The legs finished so far, kept here so a run that stops early can still report them.
        self.results: list[dict] = []

    def target(self):
        """A guarded connection; a busy or briefly absent monitor is retried, bounded."""
        for attempt in range(CONNECT_TRIES):
            try:
                connection = self.connect()
                break
            except NotConnected as exc:
                self.log("connect-retry", attempt=attempt, error=repr(exc))
                if attempt == CONNECT_TRIES - 1:
                    raise
                self.sleep(BUSY_SECONDS)
        return contextlib.closing(GuardedTarget(connection))

    def shot(self, tag: str) -> None:
        self.sess.kbd.screenshot(str(self.out / f"{tag}.png"))

    def row24(self, screen) -> str:
        return screen.row(24).strip() if screen is not None else ""

    def service(self, answer: str | None, answered: int) -> tuple[str | None, str]:
        """Deal with whatever the game is asking; returns (what was done, row 24).

        The order is the point: a disk prompt is answered by `handle_prompt`
        and RETURN is never pressed on one, whatever else the row says.
        """
        screen = self.sess.screen()
        row = self.row24(screen)
        if screen is None:
            return None, row
        if self.sess.handle_prompt(screen):
            return "disk", row
        if self.sess.wanted_disk(screen) is not None or "INSERT" in screen.text():
            return None, row
        if MOVE_SUBBAR in row:
            return None, row
        if answer and answered < ANSWERS_PER_TRIP and answer in row.split():
            self.sess.select_bar(answer, timeout=15)
            return "answer", row
        if RETURN_MESSAGE in row:
            self.sess.kbd.key("Return", 0.2, 0.3)
            return "return", row
        return None, row

    def _retry_busy(self, tag: str, call: Callable[[object], tuple[bool, str, object]]):
        """`call` until it stops answering "cannot act right now"; bounded."""
        for attempt in range(BUSY_TRIES):
            with self.target() as target:
                ok, message, value = call(target)
            if ok or message != engine.FASTTRAVEL_BUSY:
                return ok, message, value
            self.log("busy", tag=tag, attempt=attempt, message=message)
            if attempt % 4 == 3:
                self.service(None, 0)
            self.sleep(BUSY_SECONDS)
        return False, message, value

    def trip(self, dest_id: int, tag: str) -> dict:
        """One trip. Result: not_legal, not_applied, arrived, failed (with a reason) or timeout."""
        dest = engine.area_by_id(dest_id)
        if dest is None:
            raise DriverError(f"{dest_id} is not an area of Pool of Radiance")
        summary = {"dest": dest_id, "result": "not_legal", "questions": 0}

        def legal(target):
            v = self.ft.legality(target, dest)
            return bool(v), v.reason, v

        ok, reason, _ = self._retry_busy(tag, legal)
        self.log("legality", tag=tag, ok=ok, reason=reason)
        if not ok:
            self.shot(tag + "-blocked")
            return summary

        def apply(target):
            o = self.ft.apply(target, area=dest)
            return o.ok, o.message, o

        try:
            with self.target() as target:
                self.log("pre-apply", tag=tag, **reading(target))
            ok, message, _ = self._retry_busy(tag, apply)
            self.log("apply", tag=tag, ok=ok, message=message)
            if not ok:
                summary["result"] = "not_applied"
                return summary
            summary["result"] = self._poll(dest_id, tag, summary)
        finally:
            # A trip still pending when this leg ends for any reason is dropped.
            self.ft.cancel_pending()
        self.sleep(SETTLE_SECONDS)
        self.shot(tag + "-final")
        return summary

    def _poll(self, dest_id: int, tag: str, summary: dict) -> str:
        started = self.clock()
        next_look = started
        looks = 0
        while self.clock() - started < self.budget:
            self.sleep(POLL_SECONDS)
            with self.target() as target:
                got = self.ft.continue_pending(target)
                if got is not None:
                    self.log("continue_pending", tag=tag, ok=got.ok, message=got.message,
                             pending=self.ft.pending is not None)
                    if not got.ok:
                        # The game has dropped the trip, so waiting out the budget finds nothing.
                        summary["reason"] = got.message
                        return "failed"
                now = reading(target)
            if self.clock() >= next_look:
                next_look = self.clock() + SCREEN_SECONDS
                done, row = self.service(self.answer, summary["questions"])
                if done == "answer":
                    summary["questions"] += 1
                if done:
                    self.shot(f"{tag}-{done}{summary['questions']}")
                self.log("poll", tag=tag, row24=row, did=done, **now)
                if looks % SHOT_EVERY == 0:
                    self.shot(f"{tag}-poll-{looks:03d}")
                looks += 1
            if now["area6E1B"] == dest_id and now["script49F2"] == dest_id:
                with self.target() as target:
                    verdict = self.ft.legality(target, engine.area_by_id(other_area(dest_id)))
                self.log("arrival-check", tag=tag, legality=bool(verdict),
                         reason=verdict.reason, **now)
                if verdict:
                    return "arrived"
        self.log("timeout", tag=tag, budget=self.budget)
        return "timeout"

    def run(self, legs: list[int]) -> list[dict]:
        """The legs in order, stopping at the first that does not arrive."""
        try:
            for index, dest in enumerate(legs):
                self.results.append(self.trip(dest, f"t{index}-to{dest}"))
                if self.results[-1]["result"] != "arrived":
                    break
        finally:
            self.ft.cancel_pending()
        return self.results


def main(argv: list[str] | None = None) -> int:
    from automap.paths import tool_disks  # noqa: PLC0415
    from tools.c64 import session as S  # noqa: PLC0415
    from tools.registry import scratch  # noqa: PLC0415
    from wish.backends import ViceTarget  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", required=True, help="a Pool of Radiance save disk image")
    parser.add_argument("--to", type=int, action="append", required=True,
                        help="a destination area id; repeat for each further leg")
    parser.add_argument("--answer", help="a bar word to select when the game asks, e.g. YES")
    parser.add_argument("--budget", type=float, default=BUDGET_SECONDS,
                        help="seconds each leg may take")
    parser.add_argument("--disks", help="the folder of POOL1.D64 to POOL8.D64")
    parser.add_argument("--slot", type=int, default=None,
                        help="a specific instance-pool slot; otherwise the next free one")
    parser.add_argument("--out", help="directory for the log and screenshots")
    args = parser.parse_args(argv)
    for dest in args.to:
        if engine.area_by_id(dest) is None:
            parser.error(f"--to {dest} is not an area of Pool of Radiance")
    disks = pathlib.Path(args.disks) if args.disks else tool_disks()
    if disks is None:
        parser.error("no Pool of Radiance disks; pass --disks or set POR_DISKS")
    os.environ.setdefault("POR_HEADLESS", "1")
    out = scratch.ensure(args.out or scratch.cache_dir(
        "fasttravel", time.strftime("%Y%m%d-%H%M%S")))
    slot = S.claim_slot(args.slot, "fasttravelrun")
    sess = None
    driver = None
    failure: Exception | None = None
    try:
        with open(out / "run.jsonl", "w") as stream:
            log = Log(stream, time.monotonic)
            try:
                boot = S.stage_disks(slot, disks)
                S.stage_writable(pathlib.Path(args.save), pathlib.Path(slot.dir) / "SIDE0.D64")
                for image in pathlib.Path(slot.dir).glob("*.D64"):
                    os.chmod(image, 0o644)
                sess = S.Session(boot, slot=slot)
                if not sess.boot():
                    raise DriverError("boot failed")
                if not sess.load_save():
                    raise DriverError("the game did not accept the save")
                if not sess.select_row("BEGIN ADVENTURING"):
                    raise DriverError("BEGIN ADVENTURING was not selected")
                if not sess.wait_for_world(timeout=240):
                    raise DriverError("the world bar never came up")
                sess.settle(4)
                driver = Driver(sess, lambda: ViceTarget(port=sess.mon_port),
                                engine.FastTravel(), out, log, answer=args.answer,
                                budget=args.budget)
                driver.shot("0-start")
                driver.run(args.to)
                driver.shot("final")
            except Exception as exc:
                # The failure is on record in the log before the slot goes away.
                log("error", error=repr(exc))
                failure = exc
    finally:
        for step in (lambda: sess and sess.close(), slot.teardown, slot.release):
            try:
                step()
            except Exception as failed:
                print(f"cleanup failed: {failed!r}", file=sys.stderr)
    results = driver.results if driver is not None else []
    for result in results:
        print(json.dumps(result))
    if isinstance(failure, DriverError):
        raise SystemExit(str(failure)) from failure
    if failure is not None:
        raise failure
    return 0 if len(results) == len(args.to) and all(
        r["result"] == "arrived" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
