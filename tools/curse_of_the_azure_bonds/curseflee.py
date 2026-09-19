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

    POR_HEADLESS=1 .venv/bin/python tools/curse_of_the_azure_bonds/curseflee.py --slot 6 \\
        --save path/to/CURSEI.D64 --out DIR

`--save` is a Curse save disk (SIDE0) to copy into the slot.  The disks come
from `--disks`, else `$POR_DISKS`, else `tools/registry/gamedisks.py`'s Curse entry.
Loads the save with `tools/curse_of_the_azure_bonds/curseload.py`, walks until an encounter starts,
then fights it with `Flight` and writes a JSON log, a screenshot and the final
screen under `--out`.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from tools.c64 import session as S  # noqa: E402
from tools.curse_of_the_azure_bonds import curseload, curserun  # noqa: E402
from tools.pool_of_radiance.fleedrive import Flight, Log, rows_of  # noqa: E402
from tools.registry import scratch  # noqa: E402


def run(args) -> int:
    out = scratch.ensure(args.out)
    log = Log(out, args.quiet)
    flight = Flight(log)
    slot = S.claim_slot(args.slot, "curseflee/445")
    log.say(f"slot {slot.n} display {slot.display}  out {out}")
    rc, sess = 0, None
    try:
        disk = curserun.stage(slot, args.disks, args.save)
        sess = curserun.CurseSession(disk, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed (never reached the party menu)")
        log.say("reached the party menu")
        # `Session.load_save` expects `LOAD SAVED GAME: YES`, which is Pool
        # of Radiance's wording; Curse draws `LOAD SAVED GAME ? YES NO` and
        # needs its own sequence -- `tools/curse_of_the_azure_bonds/curseload.py`'s, built for exactly
        # this (`#291`).
        outcome = curseload.load_saved_game(
            sess, note=lambda **kw: log.emit("curseload", **kw))
        log.emit("load_saved_game", outcome=outcome)
        log.say(f"  load_saved_game: {outcome}")
        if outcome != "loaded":
            raise RuntimeError(f"load_saved_game: {outcome}")
        if not sess.begin_adventuring():
            raise RuntimeError("begin_adventuring failed")
        sess.settle(3)
        log.say(f"in the world at {sess.position()}")

        # `tools/c64/laterfight.py`'s own walker turns to the next key in its
        # pattern whenever the last one changed nothing -- documented there
        # as the fix for `#131`, where a party facing a shopkeeper's script
        # (Tilverton's armourer at 3,12, which is exactly where `CURSEI.D64`
        # starts) repeats the same blocked step forever otherwise.  Repeating
        # `args.walk`'s single key hit that here first, so the loop below is
        # the same design: advance the pattern index only on a step that moved
        # nothing.
        pattern = list(args.walk)
        p = 0
        steps = 0
        while not sess.in_combat():
            if steps > args.steps:
                raise RuntimeError("route exhausted with no fight")
            moved = sess.walk_one(pattern[p % len(pattern)])
            sess.handle_prompt()
            if not moved:
                p += 1
            steps += 1
        log.say(f"ambushed after {steps} steps")
        sess.settle(2)

        b = sess.battle()
        if b is not None:
            log.say(f"  the map is {b.shape.width} x {b.shape.height}")
            for c in b.party:
                log.say(f"    {c.name.strip():<12} at {c.x},{c.y}  "
                        f"move {c.movement}")
        else:
            log.say("  battle() returned None at combat start")

        result = sess.fight(args.budget, tactic=flight)
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
    p.add_argument("--disks", default=str(
        pathlib.Path(os.environ.get("POR_DISKS") or "")))
    p.add_argument("--save", required=True,
                   help="a Curse save disk (SIDE0) to copy in")
    p.add_argument("--slot", type=int, default=None)
    p.add_argument("--budget", type=float, default=900.0)
    p.add_argument("--walk", default="IIIKIIIJ",
                   help="the move-key pattern; the next key is tried "
                        "whenever the last one changed nothing")
    p.add_argument("--steps", type=int, default=300)
    p.add_argument("--out", default=str(scratch.scratch_dir("curseflee", "run")))
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    if not args.disks or args.disks == ".":
        from tools.registry import gamedisks
        found = gamedisks.find("curse-of-the-azure-bonds")
        if not found:
            print("no Curse disks found; pass --disks")
            return 2
        args.disks = str(found)
    from tools.c64 import savecheck as SC
    SC.catch_signals()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
