"""Drive `ECL10`'s arm 16 (the assassins at `15,12`) into a real fight with `QUICK`.

Belongs to #334 (The session driver cannot fight in Curse or Silver Blades, and says the party is not in a fight while it is standing on the combat floor).

The route changed from every earlier run on this ticket, and the bytecode is
why. `14,11`'s arm 2 ends both its answers at `$9AB2`:

    $9AB2  SAVE [$4BF0], [$C04B]      party x := the square stepped from
    $9AB9  SAVE [$4BF1], [$C04C]      party y := the same
    $9AC0  CALL [$2DCB]               redraw

-- so declining *and* accepting put the party back on `13,11`, and `14,11` is
the only square with a passable edge into the `15,10`/`15,11`/`15,12` corridor.
No walk over `GEO10` can reach `15,12` while that arm is live.

So this uses the technique `#158 (Track the quests the game itself forgets, starting with Ohlo's potion)`
established for driving a square's script on Pool of Radiance: write the live
position triple `$C04B`-`$C04D` and take one step. The teleport does not
dispatch; the step does, on the square arrived at. Nothing is written to any
disk and no script flag is touched -- the only bytes this changes are the
three the engine itself writes on every step.

Run: `.venv/bin/python tools/ssbarm16quick.py`. It takes no arguments, claims
an emulator pool slot and boots Silver Blades with `$WISH_SPECIMENS/por-c64/WISH-SPEC-ssb-d-engine-resave-walked.D64`
as the save. Writes its log and dumps under `work/issue334/ssb21/`.
`ssbarm16fight.py` is the earlier version, which fights with `melee_turn` and
a shorter budget.
"""
from __future__ import annotations

import argparse
import glob
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_port as G  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools import (  # noqa: E402
    cursethac0,
    gamedisks,
    laterbattle,
    specimens,
    ssbwarp,
)
from tools import session as S  # noqa: E402

OUT = ROOT / "work/issue334/ssb21"

SAVE = str(specimens.tree_root() / "por-c64"
            / "WISH-SPEC-ssb-d-engine-resave-walked.D64")
STAGE = (15, 11, 2)          # x, y, facing south
TARGET = (15, 12)
MOVE_SUBBAR_TEXT = "I,J,K,M"

#: `ECL10` runs at `$8000`; arm 16 is at `+$1638` in the file.
SCRIPT_BASE = 0x8000
ARM16 = 0x9638
ARM16_LEN = 0x9A                        # through the COMBAT at $96C9 and past
#: The square attribute the engine leaves at `$C04F`, and the flags arm 16
#: reads. `15,12` is attribute 16 with bit 7 set, so `$90`.
SQUARE_ATTR = 0xC04F
FLAGS = {"$4C2E": 0x4C2E, "$4CD9": 0x4CD9, "$4C2C": 0x4C2C, "$7F1B": 0x7F1B}


def local_clear_bar(sess, run, accept: bool = False) -> str | None:
    """`cursethac0.Run.clear_bar` without the `press_bar` #569 crashes on."""
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


def quick_turn(sess, state) -> str:
    """The game's own quickfight, one combatant's turn per press.

    `melee_turn` drove 91 turns and 76 blows in `ssb20` and did not finish
    six 52-hit-point assassins inside its budget. `QUICK` resolves a turn
    with the game's own combat AI instead of walking the figure by hand,
    which is how a fight gets to `THE PARTY HAS WON !` rather than to the
    end of a budget. Falls back to passing the turn if `QUICK` is not on
    this character's bar.
    """
    if sess.combat_bar("QUICK", timeout=12):
        return "QUICK"
    return sess.combat_turn()


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    run = laterbattle.Battle(OUT, quiet=False)
    disks = str(gamedisks.find(G.SECRET_OF_THE_SILVER_BLADES.key))
    run.slot = S.claim_slot(None, "ssb_arm16_fight/334")
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
        run.log("world", entered=entered, row24=run.row24(),
                triple=list(run.triple()))
        run.dump("world")
        if not entered:
            run.log("escape-hatch", why="enter_world did not reach the world")
            return 1

        # -- did ECL10 load whole this time? -----------------------------
        # The file's own arm 16 against what is in RAM at $9638. Under the
        # Escape-abort bug everything past $97CE was power-on RAM, so this is
        # the check that says the fix held for this boot as well.
        want = None
        for side in sorted(glob.glob(f"{disks}/*.[dD]64")):
            image = D64.open(side)
            entry = image.find(b"ECL10")
            if entry is not None:
                body = image.read_file(entry)[2:]
                want = body[ARM16 - SCRIPT_BASE:ARM16 - SCRIPT_BASE + ARM16_LEN]
                break
        live = run.peek(ARM16, ARM16_LEN)
        run.log("script-loaded", arm16_at=hex(ARM16),
                matched=(want is not None and bytes(live) == bytes(want)),
                live=live.hex(" "), file=None if want is None else want.hex(" "))

        flags = {name: run.peek(addr, 1)[0] for name, addr in FLAGS.items()}
        run.log("flags-before", **flags)

        # -- the teleport ------------------------------------------------
        with sess.mon(8) as m:
            m.write(cursethac0.POSITION, bytes(STAGE))
            back = m.read(cursethac0.POSITION, 3)
            m.resume()
        run.log("teleport", wrote=list(STAGE), read_back=list(back))
        if list(back) != list(STAGE):
            run.log("escape-hatch", why="the position triple did not take",
                    read_back=list(back))
            return 1

        # -- the step ----------------------------------------------------
        before = run.triple()
        moved = run.press("I")
        after = run.triple()
        attr = run.peek(SQUARE_ATTR, 1)[0]
        run.log("the-step", before=list(before), after=list(after), moved=moved,
                square_attr=attr, arm=attr & 63, row24=run.row24())
        run.dump("after-the-step")
        if list(after[:2]) != list(TARGET):
            run.log("escape-hatch", why="the step did not land on 15,12",
                    triple=list(after))
            return 1

        # -- watch for the fight -----------------------------------------
        fight_seen = run.in_combat()
        cleared: list[str] = []
        deadline = time.time() + 180.0
        while not fight_seen and time.time() < deadline:
            row = run.row24()
            ordinary = (not row or MOVE_SUBBAR_TEXT in row
                        or ("MOVE" in row and "ENCAMP" in row))
            if not ordinary:
                word = local_clear_bar(sess, run, accept=True)
                if word:
                    cleared.append(word)
                    run.log("cleared", word=word, row24=row)
                else:
                    run.log("unrecognised-row", row24=row)
            time.sleep(1.0)
            fight_seen = run.in_combat()
            run.log("watch", in_combat=fight_seen, mode=sess.mode(),
                    row24=run.row24(), triple=list(run.triple()))
        run.log("fight-triggered", result=fight_seen, cleared=cleared,
                triple=list(run.triple()))
        run.dump("combat-check")
        if not fight_seen:
            run.log("negative-result", why="no fight at 15,12 in 180 seconds",
                    flags={name: run.peek(addr, 1)[0]
                           for name, addr in FLAGS.items()})
            rc = 0
            return rc

        run.log("probe-on-the-floor", **{k: v for k, v in
                                         run.probe("combat").items()})
        run.log("driving-fight")
        result = sess.fight(budget=900.0, tactic=quick_turn)
        run.log("fight-result", outcome=result.outcome, turns=result.turns,
                blows=result.blows, seconds=round(result.seconds, 1),
                evidence=result.evidence, bars=result.bars[-12:],
                lines=result.lines[-24:])
        run.dump("after-fight")
        run.log("flags-after", **{name: run.peek(addr, 1)[0]
                                  for name, addr in FLAGS.items()},
                triple=list(run.triple()), mode=sess.mode())
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
