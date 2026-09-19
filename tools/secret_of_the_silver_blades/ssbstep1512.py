"""One instrumented step onto Silver Blades' `GEO10` square `15,12`.

Belongs to #334 (The session driver cannot fight in Curse or Silver Blades, and says the party is not in a fight while it is standing on the combat floor).

Stages the party one square short (15,11), takes one explicit step onto
15,12, and reads eleven addresses in one paused monitor block immediately
after the step and again at +5s, +15s, +30s, +60s, screenshotting each
reading. Also arms a non-stopping store watchpoint on $4C05 across the
approach walk and the final step, to see whether it is written where the
static reading says it should not be.

Run: `.venv/bin/python tools/secret_of_the_silver_blades/ssbstep1512.py`. It takes no arguments, claims
an emulator pool slot and boots Silver Blades with `$WISH_SPECIMENS/por-c64/WISH-SPEC-ssb-d-engine-resave-walked.D64`
as the save. Writes its log, dumps and `readings.json` under
`scratch.scratch_dir("ssbstep1512")`, in the temp directory.
`ssbreturnprobe.py` repeats this setup and adds one KERNAL Return.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap import gamedisks  # noqa: E402
from goldbox import c64_port as G  # noqa: E402
from tools.c64 import (  # noqa: E402
    laterbattle,
)
from tools.c64 import session as S  # noqa: E402
from tools.curse_of_the_azure_bonds import (  # noqa: E402
    cursethac0,
)
from tools.registry import (  # noqa: E402
    scratch,
    specimens,
)
from tools.secret_of_the_silver_blades import (  # noqa: E402
    ssbwarp,
)

OUT = scratch.scratch_dir("ssbstep1512")

SAVE = str(specimens.tree_root() / "por-c64"
            / "WISH-SPEC-ssb-d-engine-resave-walked.D64")
STAGE = (15, 11)
TARGET = (15, 12)
FACING_SOUTH = 2

#: The eight addresses the brief names, plus the three outcome-2 follow-on
#: reads the analyst's decision tree names: the monster id `SETUPMON` loads
#: and the id it last loaded, and the byte `DUNGEON $1AD0` (the `COMBAT`
#: handler) turns into the mode at `$7F11` -- ssb11 (first run) confirmed
#: outcome 2 (`$4C2E` bit 2 set, `$7F11` never reaches 2), so this run adds
#: these three to the same experiment rather than repeating it blind.
ADDR = {
    "4C2E": 0x4C2E,
    "4CD9": 0x4CD9,
    "4C2C": 0x4C2C,
    "4C05": 0x4C05,
    "4C2D": 0x4C2D,
    "C04F": 0xC04F,
    "7F11": 0x7F11,
    "7F1B": 0x7F1B,
    "7ED0": 0x7ED0,
    "2A7D": 0x2A7D,
    "7CFB": 0x7CFB,
}
WATCH_ADDR = 0x4C05


def peek8(sess) -> dict:
    with sess.mon(8) as m:
        vals = {name: m.read(addr, 1)[0] for name, addr in ADDR.items()}
        triple = list(m.read(0xC04B, 3))
        m.resume()
    vals["triple"] = triple
    return vals


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    run = laterbattle.Battle(OUT, quiet=False)
    disks = str(gamedisks.find(G.SECRET_OF_THE_SILVER_BLADES.key))
    run.slot = S.claim_slot(None, "ssb_probe_15_12/334")
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
        entered = ssbwarp.enter_world(sess, where, timeout=240, stop_at_idle=False)
        run.log("world", entered=entered, row24=run.row24())
        run.dump("world")
        if not entered:
            return 1

        area, geo = cursethac0.area_geo(SAVE, disks)
        run.log("area", area=str(area), map_read=geo is not None)

        # Arm the write watchpoint before the approach walk starts, so it
        # covers every step of the approach as well as the final one.
        with sess.mon(8) as m:
            watch = m.checkpoint_set(WATCH_ADDR, WATCH_ADDR, store=True,
                                     stop=False)
            m.resume()
        run.log("armed-watch", addr=f"${WATCH_ADDR:04X}", checkpoint=watch)

        # The stretch from the specimen's start to 13,11 crosses only
        # signpost squares (ids 12, 10, 14 -- "print and exit", already
        # known not to stop a driven walk), so the ordinary goto is safe
        # there. 14,11 is different: it is arm 2's shop challenge, and the
        # first driven attempt at this route (ssb11 run 1, see ssb11.out)
        # found `goto`'s per-step clear_bar checks row 24 before the
        # script has drawn anything -- the shop's picture and message take
        # several seconds on a fastloader-disabled 1541, and a press sent
        # into that gap does nothing, which goto reads as a wall and bans
        # the edge. So the corridor entrance is walked by hand below, with
        # settles long enough for the script to actually draw.
        WAYPOINT = (13, 11)
        arrived = run.goto(WAYPOINT, budget=20, geo=geo, accept=False)
        run.log("goto-waypoint", target=list(WAYPOINT), arrived=arrived,
                 triple=list(run.triple()), row24=run.row24())
        if not arrived:
            run.log("escape-hatch", why="did not reach the 13,11 waypoint")
            return 1

        MOVE_SUBBAR_TEXT = "I,J,K,M"

        def careful_step(key: str, tag: str, max_wait: float = 25.0):
            """One step, waiting out whatever script the landing square runs.

            **The race the first attempt at this route hit**: a script's
            picture and message take several seconds to draw on a
            fastloader-disabled 1541, and row 24 still shows the *previous*
            pass's ordinary move prompt for the whole of that time -- so a
            single `clear_bar()` right after the press sees nothing to
            clear and is not evidence that nothing is coming. This polls
            row 24 until it visibly changes, clears whatever bar appears
            (declining, per the specimen's own NO-does-not-push-back
            reading), and keeps polling until the row is back to the
            ordinary prompt and stays there, or `max_wait` runs out.
            """
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
                    word = run.clear_bar(accept=False)
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
                        break          # back to ordinary and staying there
                time.sleep(1.0)
            run.log(f"{tag}-settled", cleared=cleared, row24=run.row24(),
                     triple=list(run.triple()))
            return run.triple()

        # East into 14,11 -- the shop.
        run.turn_to(1)
        at_14_11 = careful_step("I", "step-into-14-11")
        run.dump("at-14-11")
        if list(at_14_11[:2]) != [14, 11]:
            run.log("escape-hatch", why="did not land on 14,11",
                     triple=list(at_14_11))
            return 1

        # East again into 15,11 -- the staging square, one short of target.
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

        with sess.mon(8) as m:
            writes_before_step = cursethac0.checkpoint_hits(m, watch)
            m.resume()
        run.log("writes-before-step", count=writes_before_step)

        # THE STEP.
        moved = run.press("I")
        after_triple = run.triple()
        run.log("the-step", before=list(before_triple), after=list(after_triple),
                 moved=moved)
        if list(after_triple[:2]) != list(TARGET):
            run.log("escape-hatch", why="the step did not land on the "
                     "target square", triple=list(after_triple))
            # Still take the five readings below -- the escape hatch is to
            # stop *improvising*, not to stop reporting what happened.

        t0 = time.time()
        readings = []
        for label, delay in (("immediately", 0.0), ("+5s", 5.0),
                              ("+15s", 15.0), ("+30s", 30.0), ("+60s", 60.0)):
            want = t0 + delay
            while time.time() < want:
                time.sleep(min(1.0, want - time.time()))
            vals = peek8(sess)
            elapsed = round(time.time() - t0, 2)
            run.log("five-reads", label=label, elapsed=elapsed, **vals)
            tag = f"reading-{label.replace('+', 'plus-')}"
            run.dump(tag)
            readings.append({"label": label, "elapsed": elapsed, **vals})

        with sess.mon(8) as m:
            writes_after = cursethac0.checkpoint_hits(m, watch)
            m.checkpoint_delete(watch)
            m.resume()
        run.log("writes-after-step", count=writes_after,
                 delta_since_before_step=writes_after - writes_before_step)

        (OUT / "readings.json").write_text(json.dumps(readings, indent=2))
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
