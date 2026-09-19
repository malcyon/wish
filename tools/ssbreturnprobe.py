"""Answer the acknowledgement-bar diagnosis with one KERNAL Return.

Belongs to #334 (The session driver cannot fight in Curse or Silver Blades, and says the party is not in a fight while it is standing on the combat floor).

Reuses the exact `ssb12` setup (stage at 15,11, one step onto 15,12 -- the
assassins' `ECL10` arm 16, as `ssbstep1512.py` does) but this time, once the
message is visibly on screen, sends **one** KERNAL Return ($0D) through
`Session.press_kernal` -- the same route `Session.combat_turn` already uses to
back out of `MOVE` mode -- and reads the interpreter's own state before and
after: the 6502 PC, the script PC (`$7F47`/`$7F48`), the GOSUB depth
(`$7F49`), the `HORIZMENU` flag (`$7F94`), the last key/joystick bytes
(`$03CB`/`$03F0`), plus the mode byte (`$7F11`), the monster-group count
(`$7CFB`) and the four continuity addresses (`$4C2E`, `$C04F`, `$7F1B`,
`$4C2D`).

If `$7CFB` goes to 6 and `$7F11` settles at 4 then 2, the acknowledgement bar
was the whole of the break and the fix belongs in the driver. If nothing
moves, the diagnosis needs revisiting and this script says so rather than
trying anything further.

Run: `.venv/bin/python tools/ssbreturnprobe.py`. It takes no arguments,
claims an emulator pool slot and boots Silver Blades with `$WISH_SPECIMENS/por-c64/WISH-SPEC-ssb-d-engine-resave-walked.D64`
as the save. Writes its log, dumps and `readings.json` under
this tool's scratch directory.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from automap.actions import pc_register  # noqa: E402
from goldbox import c64_port as G  # noqa: E402
from tools import (  # noqa: E402
    gamedisks,
    scratch,
    specimens,
    ssbwarp,
)
from tools.c64 import (  # noqa: E402
    laterbattle,
)
from tools.c64 import session as S  # noqa: E402
from tools.curse_of_the_azure_bonds import (  # noqa: E402
    cursethac0,
)

OUT = scratch.scratch_dir("ssbreturnprobe")

SAVE = str(specimens.tree_root() / "por-c64"
            / "WISH-SPEC-ssb-d-engine-resave-walked.D64")
STAGE = (15, 11)
TARGET = (15, 12)
FACING_SOUTH = 2

#: The continuity addresses from ssb11/ssb12, plus what this run adds: the
#: 6502 PC (read via `pc_register`, not in this dict), the interpreter's own
#: script PC and GOSUB depth, the HORIZMENU flag, and the last key/joystick
#: bytes -- exactly the five follow-on reads the analyst's second comment
#: names as what would settle it.
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
    "7F47": 0x7F47,
    "7F48": 0x7F48,
    "7F49": 0x7F49,
    "7F94": 0x7F94,
    "03CB": 0x03CB,
    "03F0": 0x03F0,
}
WATCH_ADDR = 0x4C05


def peek(sess) -> dict:
    with sess.mon(8) as m:
        vals = {name: m.read(addr, 1)[0] for name, addr in ADDR.items()}
        triple = list(m.read(0xC04B, 3))
        pc = m.registers().get(pc_register(m))
        m.resume()
    vals["triple"] = triple
    vals["pc"] = pc
    return vals


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    run = laterbattle.Battle(OUT, quiet=False)
    disks = str(gamedisks.find(G.SECRET_OF_THE_SILVER_BLADES.key))
    run.slot = S.claim_slot(None, "ssb_probe_return/334")
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

        with sess.mon(8) as m:
            watch = m.checkpoint_set(WATCH_ADDR, WATCH_ADDR, store=True,
                                     stop=False)
            m.resume()
        run.log("armed-watch", addr=f"${WATCH_ADDR:04X}", checkpoint=watch)

        # Same route as ssb12: goto to 13,11 over GEO, then hand-walk the
        # scripted 14,11 -> 15,11 stretch, waiting out each square's own bar
        # rather than trusting a single `clear_bar()` right after the press
        # -- ssb11's first attempt found row 24 lags the script's own
        # drawing by several seconds on this fastloader-disabled 1541.
        WAYPOINT = (13, 11)
        arrived = run.goto(WAYPOINT, budget=20, geo=geo, accept=False)
        run.log("goto-waypoint", target=list(WAYPOINT), arrived=arrived,
                 triple=list(run.triple()), row24=run.row24())
        if not arrived:
            run.log("escape-hatch", why="did not reach the 13,11 waypoint")
            return 1

        MOVE_SUBBAR_TEXT = "I,J,K,M"

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
                        break
                time.sleep(1.0)
            run.log(f"{tag}-settled", cleared=cleared, row24=run.row24(),
                     triple=list(run.triple()))
            return run.triple()

        run.turn_to(1)
        at_14_11 = careful_step("I", "step-into-14-11")
        run.dump("at-14-11")
        if list(at_14_11[:2]) != [14, 11]:
            run.log("escape-hatch", why="did not land on 14,11",
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
            # Report rather than improvise past it, but still take readings.

        t0 = time.time()

        # ssb12 found the message stably on screen by +5s and unchanged
        # through +60s; wait that long before reading and screenshotting the
        # pre-Return state, so the "before" picture is the same state every
        # prior run of this experiment sat in for a minute.
        while time.time() < t0 + 6.0:
            time.sleep(0.5)
        before_return = peek(sess)
        elapsed = round(time.time() - t0, 2)
        run.log("pre-return", elapsed=elapsed, **before_return)
        run.dump("pre-return")

        # THE PRESS: one KERNAL Return, the same route Session.combat_turn
        # already uses to back out of a bar, per the brief.
        t1 = time.time()
        sess.press_kernal(0x0D)
        run.log("sent-return", at=round(t1 - t0, 2))

        readings = [{"label": "pre-return", "elapsed": elapsed, **before_return}]
        for label, delay in (("immediately", 0.0), ("+2s", 2.0), ("+5s", 5.0),
                              ("+10s", 10.0), ("+20s", 20.0)):
            want = t1 + delay
            while time.time() < want:
                time.sleep(min(1.0, want - time.time()))
            vals = peek(sess)
            elapsed = round(time.time() - t1, 2)
            run.log("post-return", label=label, elapsed=elapsed, **vals)
            tag = f"post-return-{label.replace('+', 'plus-')}"
            run.dump(tag)
            readings.append({"label": label, "elapsed": elapsed, **vals})

        with sess.mon(8) as m:
            writes_after = cursethac0.checkpoint_hits(m, watch)
            m.checkpoint_delete(watch)
            m.resume()
        run.log("writes-after-step", count=writes_after,
                 delta_since_before_step=writes_after - writes_before_step)

        (OUT / "readings.json").write_text(json.dumps(readings, indent=2))

        # If the mode byte reached 2 (real COMBAT, past COM.PREP), drive a
        # few turns the same way run5's Curse fight was, for the full
        # confirmation named in the brief.
        final_mode = readings[-1].get("7F11")
        if run.in_combat() or final_mode == 2:
            run.log("driving-combat", mode=final_mode)
            result = sess.fight(budget=90.0, tactic=S.Session.melee_turn)
            run.log("fight-result", outcome=result.outcome, turns=result.turns,
                     blows=result.blows, seconds=result.seconds,
                     bars=result.bars, lines=result.lines)
            run.dump("after-fight-drive")
        else:
            run.log("not-driving-combat", why="mode byte never reached 2",
                     final_mode=final_mode)

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
