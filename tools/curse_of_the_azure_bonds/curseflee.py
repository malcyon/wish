#!/usr/bin/env python3
"""Drive a Curse of the Azure Bonds party into a fight and try to flee it, for `#445 (The game's third fight outcome, THE PARTY RUNS AWAY, has never been seen on a screen)`.

The Pool of Radiance half of that issue is `tools/pool_of_radiance/fleedrive.py`, which cannot be
reused whole for Curse: it boots `tools/c64/session.py`'s own `Session`, and Curse
boots through `tools/curse_of_the_azure_bonds/curserun.py`'s `CurseSession`.  What does reuse whole is
`Flight`, `tools/pool_of_radiance/fleedrive.py`'s tactic -- it is written against the generic
`Session` interface (`battle()`, `acting()`, `combat_bar()`, `await_bar()`,
`press_kernal()`, `kbd.key()`, `combat_turn()`), all of which `CurseSession`
already answers, with its own overrides where a bar needs the KERNAL buffer --
and `Session.fight(budget, tactic=...)` is already written to take it: its
`BAR_YESNO` branch names `Flight` and that issue.  So this file is the harness
around that pairing, not a second `Flight`.

**Reaching the fight is `tools/c64/laterbattle.py`'s `curse_fight`, not a fixed
walk**: `#648 (See THE PARTY RUNS AWAY on a Curse or Silver Blades screen, and
confirm the mercy heal on the losing side of a fight)` found that this file's
own fixed route from `cited/131-m1/CURSEI.D64` never met a fight at all, where
`curse_fight` already reaches Tilverton's tavern brawl over the area's own
`GEO` and `PUNCH BARKEEP` reliably, for `#334`'s own runs. So this file stages
a `laterbattle.Battle`, hands it to `curse_fight`, then waits for the combat
floor exactly as `laterbattle.main` does, and only then hands the fight to
`Flight`.

**The flee line is up for under half a second** (`Session.fight`'s own docs on
`poll`), so this file's `--poll` defaults to `0.12` rather than `fight`'s own
`1.0` -- a one-second poll is the reading `#648` says missed it.

    POR_HEADLESS=1 .venv/bin/python tools/curse_of_the_azure_bonds/curseflee.py --slot 6 \\
        --save path/to/CURSEI.D64 --out DIR

`--save` is a Curse save disk (SIDE0) to copy into the slot.  The disks come
from `--disks`, else `$POR_DISKS`, else `automap/gamedisks.py`'s Curse entry.
Loads the save with `tools/curse_of_the_azure_bonds/curseload.py`, walks to Tilverton's tavern and
punches the barkeep, then fights it with `Flight` and writes a JSON log, a
screenshot and the final screen under `--out`.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from tools.c64 import laterbattle  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.pool_of_radiance.fleedrive import Flight, Log, rows_of  # noqa: E402
from tools.registry import scratch  # noqa: E402


def run(args) -> int:
    out = scratch.ensure(args.out)
    log = Log(out, args.quiet)
    flight = Flight(log)
    slot = S.claim_slot(args.slot, "curseflee/445")
    log.say(f"slot {slot.n} display {slot.display}  out {out}")
    battle = laterbattle.Battle(out, args.quiet)
    battle.slot = slot
    rc, sess = 0, None
    try:
        fight_rc = laterbattle.curse_fight(battle, args, args.disks)
        battle.log("curse_fight", rc=fight_rc)
        if fight_rc:
            raise RuntimeError(f"curse_fight failed (rc={fight_rc})")
        sess = battle.sess
        log.say("reached the tavern script")

        # `laterbattle.main`'s own wait for the combat floor: `curse_fight`
        # only presses the script's word, and `YOU GET INTO A BRAWL.` draws
        # over a picture and waits on a keypress before the floor appears.
        for _ in range(args.wait):
            if battle.in_combat():
                break
            s = sess.screen()
            state = sess.combat_state(s)
            if state.kind == S.BAR_PRESS or s is None:
                sess.press_kernal(0x0D)
            sess.settle(4.0)
        if not battle.in_combat():
            raise RuntimeError("never reached the combat floor")
        log.say("on the combat floor")

        b = sess.battle()
        if b is not None:
            log.say(f"  the map is {b.shape.width} x {b.shape.height}")
            for c in b.party:
                log.say(f"    {c.name.strip():<12} at {c.x},{c.y}  "
                        f"move {c.movement}")
        else:
            log.say("  battle() returned None at combat start")

        result = sess.fight(args.budget, tactic=flight, poll=args.poll)
        log.say(f"fight ended: outcome={result.outcome!r} turns={result.turns}"
                f" seconds={result.seconds:.1f}")
        log.emit("fight_result", outcome=result.outcome, turns=result.turns,
                  seconds=result.seconds, bars=result.bars,
                  lines=result.lines)
        try:
            sess.kbd.screenshot(str(out / "outcome.png"))
        except Exception as exc:
            log.emit("shot_failed", error=repr(exc))
        s = sess.screen()
        if s is not None:
            (out / "final-screen.txt").write_text(
                "\n".join(rows_of(s)) + "\n")
        log.emit("flee", attempts=flight.attempts,
                  got_away=flight.got_away, failed=dict(flight.failed))
        log.say(f"  flee attempts {flight.attempts}, got away "
                f"{flight.got_away}, failed {dict(flight.failed)}")
    except Exception as exc:
        import traceback
        try:
            s = sess and sess.screen()
            screen = rows_of(s) if s else []
        except Exception:
            screen = []
        if screen:
            (out / "failed-screen.txt").write_text("\n".join(screen) + "\n")
            log.say("\n".join(ln for ln in screen if ln.strip()))
        log.emit("failed", error=repr(exc), screen=screen,
                  traceback=traceback.format_exc())
        traceback.print_exc()
        rc = 1
    finally:
        for what, step in (("session close", lambda: sess and sess.close()),
                           ("slot teardown", slot.teardown),
                           ("slot release", slot.release)):
            try:
                step()
            except Exception as exc:
                log.emit("cleanup_failed", step=what, error=repr(exc))
                log.say(f"Cleanup failed at {what}: {exc!r}")
                rc = rc or 1
        log.close()
    return rc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disks", default=os.environ.get("POR_DISKS") or None)
    p.add_argument("--save", required=True,
                   help="a Curse save disk (SIDE0) to copy in")
    p.add_argument("--slot", type=int, default=None)
    p.add_argument("--budget", type=float, default=900.0)
    p.add_argument("--poll", type=float, default=0.12,
                   help="Session.fight's poll interval; the flee line is up "
                        "for under half a second, which fight's own 1.0s "
                        "default misses")
    p.add_argument("--steps", type=int, default=60,
                   help="goto budget for the walk to the tavern")
    p.add_argument("--world", type=float, default=240.0,
                   help="seconds to give BEGIN ADVENTURING to reach the world")
    p.add_argument("--look", type=float, default=8.0,
                   help="seconds between readings while waiting for the world")
    p.add_argument("--wait", type=int, default=15,
                   help="settles to give the combat screen to draw")
    p.add_argument("--accept", action="store_true",
                   help="take the YES half of a script's own YES/NO bar "
                        "instead of declining it, for a walker that is "
                        "trying to reach a fight (#334)")
    p.add_argument("--out", default=str(scratch.scratch_dir("curseflee", "run")))
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    if args.disks is None:
        from automap import gamedisks
        found = gamedisks.find("curse-of-the-azure-bonds")
        if not found:
            print("no Curse disks found; pass --disks")
            return 2
        args.disks = str(found)
    from tools.c64 import runlog
    runlog.catch_signals()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
