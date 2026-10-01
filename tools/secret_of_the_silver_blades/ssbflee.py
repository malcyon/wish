#!/usr/bin/env python3
"""Drive Silver Blades' assassin fight at 15,12 and, with `--flee`, try to run from it.

Reaching the fight is `ssbarm16fight.reach_fight`; `--flee` then hands
`Session.fight` `tools/pool_of_radiance/fleedrive.py`'s `Flight` instead of
`melee_turn`. `--poll` is `Session.fight`'s poll interval and defaults to
`0.12` with `--flee`, because the flee line is up for under half a second, and
to `1.0` without it.

    POR_HEADLESS=1 .venv/bin/python tools/secret_of_the_silver_blades/ssbflee.py --flee

Claims a pool slot, boots Silver Blades from `ssbarm16fight.SAVE`, and writes a
JSON log and dumps under `--out`.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap import gamedisks  # noqa: E402
from goldbox import c64_port as G  # noqa: E402
from tools.c64 import laterbattle  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.pool_of_radiance.fleedrive import Flight, Log  # noqa: E402
from tools.registry import scratch  # noqa: E402
from tools.secret_of_the_silver_blades import ssbarm16fight as arm16  # noqa: E402
from tools.secret_of_the_silver_blades import ssbsession  # noqa: E402

FLEE_POLL = 0.12
MELEE_POLL = 1.0


def poll_for(args) -> float:
    """`--poll` if given, else the interval that suits the tactic."""
    if args.poll is not None:
        return args.poll
    return FLEE_POLL if args.flee else MELEE_POLL


def fight(sess, run, args, flight_log=None):
    """Drive the fight in the arena: `Flight` with `--flee`, else `melee_turn`."""
    poll = poll_for(args)
    if args.flee:
        flight = Flight(flight_log)
        result = sess.fight(budget=args.budget, tactic=flight, poll=poll)
        run.log("flee", attempts=flight.attempts, got_away=flight.got_away,
                failed=dict(flight.failed))
    else:
        result = sess.fight(budget=args.budget, tactic=S.Session.melee_turn,
                            poll=poll)
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--flee", action="store_true",
                   help="fight with Flight instead of melee_turn")
    p.add_argument("--poll", type=float, default=None,
                   help="Session.fight's poll interval; default 0.12 with "
                        "--flee (the flee line is up for under half a "
                        "second), else 1.0")
    p.add_argument("--budget", type=float, default=300.0)
    p.add_argument("--out", default=str(scratch.scratch_dir("ssbflee")))
    p.add_argument("--quiet", action="store_true")
    return p


def cleanup(run, flight_log, rc) -> None:
    """Run every teardown step, each isolated so one failure cannot skip the rest."""
    steps = [("done log", lambda: run.log("done", rc=rc))]
    if flight_log is not None:
        steps.append(("flight log", flight_log.close))
    if run.sess is not None:
        def clear_checkpoints():
            with run.sess.mon(5) as m:
                m.checkpoints_clear()
                m.resume()
        steps += [("checkpoints", clear_checkpoints),
                  ("terminate", run.sess.terminate)]
    steps += [("slot teardown", run.slot.teardown),
              ("slot release", run.slot.release)]
    for what, step in steps:
        try:
            step()
        except Exception as exc:
            try:
                run.log("cleanup-failed", step=what, error=repr(exc))
            except Exception:
                pass


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = scratch.ensure(args.out)
    run = laterbattle.Battle(out, quiet=args.quiet)
    disks = str(gamedisks.find(G.SECRET_OF_THE_SILVER_BLADES.key))
    run.slot = S.claim_slot(None, "ssbflee/648")
    flight_log = None
    rc = 1
    try:
        flight_log = Log(out, args.quiet)
        sess = ssbsession.SSBSession(
            ssbsession.stage(run.slot, disks, arm16.SAVE), slot=run.slot)
        run.sess = sess
        sess.save_disk = str(pathlib.Path(run.slot.dir) / "SIDE0.D64")
        if not sess.boot() or not ssbsession.load_party(sess):
            run.log("escape-hatch", why="boot or load_party failed")
            return 1
        where = ssbsession.Addresses(G.SECRET_OF_THE_SILVER_BLADES, disks)
        if not ssbsession.enter_world(sess, where, timeout=240,
                                      stop_at_idle=False):
            run.log("escape-hatch", why="enter_world did not reach the world")
            return 1
        reached = arm16.reach_fight(run, sess)
        if reached is None:
            return 1
        if not reached:
            run.log("negative-result", why="no fight at 15,12 in 90 seconds")
            rc = 0
            return rc
        result = fight(sess, run, args, flight_log)
        run.log("fight-result", outcome=result.outcome, turns=result.turns,
                seconds=round(result.seconds, 1), bars=result.bars[-12:],
                lines=result.lines[-24:])
        run.dump("after-fight")
        rc = 0
    finally:
        cleanup(run, flight_log, rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
