"""Re-run the walk to Silver Blades `15,11` -> `15,12` with the Escape fix.

Belongs to #334 (The session driver cannot fight in Curse or Silver Blades, and says the party is not in a fight while it is standing on the combat floor).

`tools/secret_of_the_silver_blades/ssbwarp.py`'s `enter_world` no longer sends an unconditional Escape at
a stuck screen (`#568 (cursewarp.py and ssbwarp.py can abort a mid-load ECL
script by sending Escape to a screen that is merely slow, not stuck)`, committed on `main` as `f7f49c7`);
the root cause comment on the issue traced every earlier no-fight result on
this exact route to that Escape aborting `ECL10`'s KERNAL load mid-file. This
is the live re-validation those comments asked for: same save, same route,
same staging square and same step, with the fix in place, checking
`Session.in_combat()` (the `$7F11` mode byte, not row 24 or a screenshot) and
driving a real fight with `Session.fight()` if one starts.

Run: `.venv/bin/python tools/secret_of_the_silver_blades/ssbrevalidate.py`. It takes no arguments, claims
an emulator pool slot and boots Silver Blades with `$WISH_SPECIMENS/por-c64/WISH-SPEC-ssb-d-engine-resave-walked.D64`
as the save. Writes its log and dumps under its own scratch directory. The
walk itself is the one `ssbstep1512.py` and `ssbreturnprobe.py` make.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_port as G  # noqa: E402
from tools import (  # noqa: E402
    gamedisks,
    scratch,
    specimens,
)
from tools.c64 import (  # noqa: E402
    laterbattle,
)
from tools.c64 import session as S  # noqa: E402
from tools.curse_of_the_azure_bonds import (  # noqa: E402
    cursethac0,
)
from tools.secret_of_the_silver_blades import (  # noqa: E402
    ssbwarp,
)

OUT = scratch.scratch_dir("ssbrevalidate")

SAVE = str(specimens.tree_root() / "por-c64"
            / "WISH-SPEC-ssb-d-engine-resave-walked.D64")
STAGE = (15, 11)
TARGET = (15, 12)
FACING_SOUTH = 2

MOVE_SUBBAR_TEXT = "I,J,K,M"

#: `cursethac0.Run.clear_bar` calls `self.sess.press_bar`, which exists only
#: on `tools/curse_of_the_azure_bonds/curserun.py`'s `CurseSession` (a one-line alias for
#: `select_bar`) -- `tools.c64.session.Session` and `ssbwarp.SSBSession` have no
#: such method, so calling it on a Silver Blades session raises
#: `AttributeError`. Hit live in this run's first `clear_bar()` call at
#: 14,11 (the shop square) -- reported to #334 as a discovered defect
#: rather than patched, per this brief's file ownership. This is a local,
#: read-only reimplementation of the same three word lists against
#: `Session.select_bar`, which both `Session` and `SSBSession` do have, so
#: this throwaway driver does not depend on the missing method.
def local_clear_bar(sess, run, accept: bool = False) -> str | None:
    row = run.row24()
    if not row or MOVE_SUBBAR_TEXT in row or run.in_combat():
        return None
    if all(w in row for w in cursethac0.WORLD_WORDS):
        return None
    if accept:
        for word in cursethac0.ACCEPT:
            if word in row.split():
                sess.select_bar(word, timeout=10)
                run.log("accepted", word=word, was=row, now=run.row24())
                return word
    for word in cursethac0.DISMISS:
        if word in row.split():
            sess.select_bar(word, timeout=10)
            run.log("dismissed", word=word, was=row, now=run.row24())
            return word
    if "PRESS" in row.split():
        sess.press_kernal(0x0D)
        run.log("acknowledged", was=row, now=run.row24())
        return "PRESS"
    return None


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    run = laterbattle.Battle(OUT, quiet=False)
    disks = str(gamedisks.find(G.SECRET_OF_THE_SILVER_BLADES.key))
    run.slot = S.claim_slot(None, "ssb_revalidate_334/334")
    run.log("slot", n=run.slot.n, display=run.slot.display,
             dir=str(run.slot.dir), save=SAVE, disks=disks)
    rc = 1
    try:
        boot = ssbwarp.stage(run.slot, disks, SAVE)
        sess = ssbwarp.SSBSession(boot, slot=run.slot)
        run.sess = sess
        sess.save_disk = str(pathlib.Path(run.slot.dir) / "SIDE0.D64")
        if not sess.boot():
            run.log("boot", reached_menu=False)
            return 1
        run.log("boot", reached_menu=True)
        if not ssbwarp.load_party(sess):
            run.log("loaded", outcome="no")
            return 1
        run.log("loaded", outcome="loaded")
        where = ssbwarp.Addresses(G.SECRET_OF_THE_SILVER_BLADES, disks)
        entered = ssbwarp.enter_world(sess, where, timeout=240,
                                      stop_at_idle=False)
        run.log("world", entered=entered, row24=run.row24())
        run.dump("world")
        if not entered:
            run.log("escape-hatch", why="enter_world did not reach the world")
            return 1

        area, geo = cursethac0.area_geo(SAVE, disks)
        run.log("area", area=str(area), map_read=geo is not None)

        WAYPOINT = (13, 11)
        arrived = run.goto(WAYPOINT, budget=20, geo=geo, accept=False)
        run.log("goto-waypoint", target=list(WAYPOINT), arrived=arrived,
                 triple=list(run.triple()), row24=run.row24())
        if not arrived:
            run.log("escape-hatch", why="did not reach the 13,11 waypoint")
            return 1

        def careful_step(key: str, tag: str, max_wait: float = 25.0):
            before = run.triple()
            moved = run.press(key)
            after = run.triple()
            run.log(tag, before=list(before), after=list(after), moved=moved,
                     row24=run.row24())
            deadline = time.time() + max_wait
            cleared = []
            quiet_since = None
            while time.time() < deadline:
                if run.in_combat():
                    run.log(f"{tag}-in-combat")
                    break
                row = run.row24()
                ordinary = (not row or MOVE_SUBBAR_TEXT in row
                            or ("MOVE" in row and "ENCAMP" in row))
                if not ordinary:
                    word = local_clear_bar(sess, run, accept=False)
                    if word:
                        cleared.append(word)
                        run.log(f"{tag}-cleared", word=word, row24=row)
                    else:
                        run.log(f"{tag}-unrecognised-row", row24=row)
                    quiet_since = None
                    time.sleep(1.5)
                    continue
                if cleared:
                    if quiet_since is None:
                        quiet_since = time.time()
                    elif time.time() - quiet_since > 3.0:
                        break
                time.sleep(1.0)
            run.log(f"{tag}-settled", cleared=cleared, row24=run.row24(),
                     triple=list(run.triple()))
            return run.triple()

        # 14,11 is the shop challenge (arm 2). This ticket's own analysis
        # predicted a YES/NO bar at $9B20 there that "has never appeared" in
        # any prior run -- every earlier attempt hit the Escape-abort bug
        # before the script could draw it. With the fix in place this run's
        # first attempt did draw that bar, declining it (NO) bounced the
        # party back to the 13,11 waypoint rather than leaving it on 14,11 --
        # a shop's own response to being declined, not a walk failure. So a
        # bounce-back gets one retry (the bar is already resolved) before
        # this is treated as not landing on the square.
        at_14_11 = None
        for attempt in range(3):
            run.turn_to(1)
            at_14_11 = careful_step("I", f"step-into-14-11-try{attempt}")
            run.dump(f"at-14-11-try{attempt}")
            if list(at_14_11[:2]) == [14, 11]:
                break
            run.log("step-into-14-11-bounced", attempt=attempt,
                    triple=list(at_14_11))
        if list(at_14_11[:2]) != [14, 11]:
            run.log("escape-hatch", why="did not land on 14,11 after "
                     "3 attempts (bounced back by the shop bar each time)",
                     triple=list(at_14_11))
            return 1

        run.turn_to(1)
        at_15_11 = careful_step("I", "step-into-15-11")
        run.dump("staged-15-11")
        if list(at_15_11[:2]) != list(STAGE):
            run.log("escape-hatch", why="did not reach staging square",
                     triple=list(at_15_11))
            return 1
        run.log("goto-staging", target=list(STAGE), arrived=True,
                 triple=list(at_15_11), row24=run.row24())

        run.turn_to(FACING_SOUTH)
        before_triple = run.triple()
        if before_triple[:2] != STAGE:
            run.log("escape-hatch", why="not standing on staging square "
                     "before the step", triple=list(before_triple))
            return 1

        # THE STEP.
        moved = run.press("I")
        after_triple = run.triple()
        run.log("the-step", before=list(before_triple), after=list(after_triple),
                 moved=moved)
        run.dump("after-the-step")

        in_combat_immediately = run.in_combat()
        run.log("in-combat-check", immediately=in_combat_immediately,
                mode=sess.mode(), row24=run.row24(),
                triple=list(after_triple))

        # Poll a while in case the fight starts a beat after the step (a
        # picture or message drawing first) rather than exactly on it.
        fight_seen = in_combat_immediately
        deadline = time.time() + 20.0
        while not fight_seen and time.time() < deadline:
            time.sleep(1.0)
            fight_seen = run.in_combat()
            run.log("in-combat-poll", elapsed=round(20.0 - (deadline - time.time()), 1),
                    in_combat=fight_seen, mode=sess.mode())

        run.log("fight-triggered", result=fight_seen)
        run.dump("combat-check")

        if not fight_seen:
            run.log("negative-result",
                    why="no fight at 15,12 after the step, with the "
                        "enter_world Escape fix in place")
            rc = 0
            return rc

        run.log("driving-fight")
        result = sess.fight(budget=240.0, tactic=S.Session.melee_turn)
        run.log("fight-result", outcome=result.outcome, turns=result.turns,
                blows=result.blows, seconds=round(result.seconds, 1),
                evidence=result.evidence, bars=result.bars[-12:],
                lines=result.lines[-20:])
        run.dump("after-fight")
        rc = 0
    finally:
        run.log("done", rc=rc)
        if run.sess is not None:
            try:
                with run.sess.mon(5) as m:
                    m.checkpoints_clear()
                    m.resume()
            except Exception as exc:
                run.log("checkpoints", cleared=False, why=str(exc))
            run.sess.terminate()
        if getattr(run, "slot", None) is not None:
            run.slot.teardown()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
