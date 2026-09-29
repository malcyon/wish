#!/usr/bin/env python3
"""Drive Silver Blades' assassin fight at 15,12 and, with `--flee`, try to run from it, for `#648 (See THE PARTY RUNS AWAY on a Curse or Silver Blades screen, and confirm the mercy heal on the losing side of a fight)`.

Reaching the fight is `ssbarm16fight.py`'s own teleport onto `15,11` and one step
south onto `15,12`, which starts `ECL10`'s arm 16 (`#334`).  What differs is the
tactic: `--flee` gives `Session.fight` `tools/pool_of_radiance/fleedrive.py`'s
`Flight` instead of `melee_turn`, polling at `--poll`, which defaults to `0.12`
because the flee line is up for under half a second and `fight`'s own `1.0`
misses it.  Without `--flee` this is `ssbarm16fight`'s `melee_turn` fight.

    POR_HEADLESS=1 .venv/bin/python tools/secret_of_the_silver_blades/ssbflee.py --flee

Claims a pool slot, boots Silver Blades from `ssbarm16fight.SAVE`, and writes a
JSON log and dumps under `--out`.  Whether a character can leave this map is
what the first run settles.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap import gamedisks  # noqa: E402
from goldbox import c64_port as G  # noqa: E402
from tools.c64 import laterbattle  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.curse_of_the_azure_bonds import cursethac0  # noqa: E402
from tools.pool_of_radiance.fleedrive import Flight, Log  # noqa: E402
from tools.registry import scratch  # noqa: E402
from tools.secret_of_the_silver_blades import ssbarm16fight as arm16  # noqa: E402
from tools.secret_of_the_silver_blades import ssbsession  # noqa: E402

FLEE_POLL = 0.12
MELEE_POLL = 1.0


def fight(sess, run, args, flight_log=None):
    """Drive the fight on the floor: `Flight` at `args.poll` with `--flee`, else `melee_turn`."""
    if args.flee:
        flight = Flight(flight_log)
        result = sess.fight(budget=args.budget, tactic=flight, poll=args.poll)
        run.log("flee", attempts=flight.attempts, got_away=flight.got_away,
                failed=dict(flight.failed))
    else:
        result = sess.fight(budget=args.budget, tactic=S.Session.melee_turn)
    return result


def reach_fight(run, sess, disks) -> bool:
    """Teleport to 15,11 and step onto 15,12; True once the combat floor is up."""
    with sess.mon(8) as m:
        m.write(cursethac0.POSITION, bytes(arm16.STAGE))
        back = m.read(cursethac0.POSITION, 3)
        m.resume()
    if list(back) != list(arm16.STAGE):
        run.log("escape-hatch", why="the position triple did not take",
                read_back=list(back))
        return False
    run.press("I")
    after = run.triple()
    if list(after[:2]) != list(arm16.TARGET):
        run.log("escape-hatch", why="the step did not land on 15,12",
                triple=list(after))
        return False
    deadline = time.time() + 90.0
    while not run.in_combat() and time.time() < deadline:
        row = run.row24()
        ordinary = (not row or arm16.MOVE_SUBBAR_TEXT in row
                    or ("MOVE" in row and "ENCAMP" in row))
        if not ordinary:
            arm16.local_clear_bar(sess, run, accept=True)
        time.sleep(1.0)
    run.dump("combat-check")
    return run.in_combat()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--flee", action="store_true",
                   help="fight with Flight instead of melee_turn")
    p.add_argument("--poll", type=float, default=FLEE_POLL,
                   help="Session.fight's poll interval with --flee; the flee "
                        "line is up for under half a second")
    p.add_argument("--budget", type=float, default=300.0)
    p.add_argument("--out", default=str(scratch.scratch_dir("ssbflee")))
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    out = scratch.ensure(args.out)
    run = laterbattle.Battle(out, quiet=args.quiet)
    flight_log = Log(out, args.quiet)
    disks = str(gamedisks.find(G.SECRET_OF_THE_SILVER_BLADES.key))
    run.slot = S.claim_slot(None, "ssbflee/648")
    rc = 1
    try:
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
        if not reach_fight(run, sess, disks):
            run.log("negative-result", why="no fight at 15,12 in 90 seconds")
            return 0
        result = fight(sess, run, args, flight_log)
        run.log("fight-result", outcome=result.outcome, turns=result.turns,
                seconds=round(result.seconds, 1), bars=result.bars[-12:],
                lines=result.lines[-24:])
        run.dump("after-fight")
        rc = 0
    finally:
        run.log("done", rc=rc)
        flight_log.close()
        if run.sess is not None:
            run.sess.terminate()
        run.slot.teardown()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
