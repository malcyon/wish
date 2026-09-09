#!/usr/bin/env python3
"""Boot Pool of Radiance with a save disk and say whether the drive would open it.

`tools/curseload.py` asks this question of Curse of the Azure Bonds, whose
front end is its own; this asks it of Pool of Radiance, where the party menu
is the one `tools/session.py` already drives.  The reason there are two is
`#298 (A save disk copied out of an emulator slot before the drive closes the
file cannot be loaded by the game)`: an image copied out of a pool slot before
the emulated 1541 finished its write-back carries a directory entry the drive
still believes is open for writing -- type byte `$02` rather than `$82`, a
block count of zero, `*PRG` in a listing -- and the drive will not open one for
reading.  The payload is on the disk and every one of this project's readers
gets it out, because they follow the sector chain; only the game is refused.

**The measurement is `$03F1`, not the sentence on the screen.**  That byte is
where the load's result is turned into a number, and the drive's own error
number reaches it whenever the game's fastloader is not installed --
`docs/179-loading-a-curse-save.md` has the two arms of `$401E` and which one
runs at the party menu.  0 is a load that worked and `$3C` is 60 decimal,
`WRITE FILE OPEN`.  The screen is not the measurement because the two titles
do not print the same sentence for it: Pool of Radiance says
`SAVED GAME NOT FOUND!` and Curse says `UNABLE TO LOAD SAVED GAME.`, and
neither names the drive error.

    tools/splatload.py --save ~/wish-specimens/por-c64/WISH-SPEC-...d64
    tools/splatload.py --save ... --repair

`--repair` closes the entry in the **staged copy inside the pool slot**, using
`tools/curseload.py`'s `close_splat()`, and never touches the file it was
copied from.  Run it both ways over the same disk and the pair is the
differential: one refusal and one party, with nothing else changed.

The player's disks are read and never written -- `Session.attach` refuses a
path outside the slot's own directory, and `stage_disks` copies the sides
there first.  The pool owns the emulator: claim, launch, tear down.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from tools import gamedisks  # noqa: E402
from tools import session as S  # noqa: E402
from tools.curseload import close_splat  # noqa: E402

#: Where the load's result becomes a number.  0 is success; anything else is
#: the drive's own error code, and 60 (`$3C`) is `WRITE FILE OPEN`.
RESULT = 0x03F1

#: 1 while the game's own fastloader is installed, in which case `$03F1` gets
#: `$3E` and says nothing about which fault it was.  Read so a run that
#: measured nothing can be told from one that measured 60.
FASTLOADER = 0x7E9F

#: What the party menu shows once a save is in, and what it shows when the
#: drive would not give it one.  Both are screen text and neither is the
#: measurement; they are here so the log says what a person would have seen.
LOADED_HINT = "BEGIN ADVENTURING"
REFUSED_HINTS = ("NOT FOUND", "UNABLE TO LOAD", "ERROR")


def probe(sess) -> dict:
    """The two bytes that say what the load did, in one monitor connection."""
    try:
        with sess.mon(8) as m:
            return {"03F1_result": m.peek(RESULT),
                    "7E9F_fastloader": m.peek(FASTLOADER)}
    except Exception as exc:                             # noqa: BLE001
        return {"probe_error": f"{type(exc).__name__}: {exc}"}


def watch(sess, note, budget: float = 120.0) -> tuple[str, str]:
    """Poll the screen until it says something, and log every change.

    Not `Session.load_save`'s own wait: that watches for `BEGIN ADVENTURING`,
    which on this title is a label the party menu carries **before** the load
    as well as after it, so a refusal that redraws the menu looks exactly like
    a success.  This one records what each screen said and lets the caller
    decide against `$03F1`.
    """
    deadline, last, outcome = time.time() + budget, "", "timeout"
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(1.0)
            continue
        text = s.text()
        if text != last:
            note(event="screen", row24=s.row(24).strip())
            last = text
        if any(h in text for h in REFUSED_HINTS):
            return "refused", text
        if LOADED_HINT in text:
            return "menu", text
        time.sleep(1.0)
    return outcome, last


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "run.jsonl").open("a")

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw) + "\n")
        log.flush()
        print(json.dumps(kw), flush=True)

    disks = pathlib.Path(args.disks or gamedisks.find("pool-of-radiance"))
    slot = S.claim_slot(args.slot, note=os.environ.get("POR_AGENT", "splatload"))
    note(event="slot", n=slot.n, display=slot.display, dir=str(slot.dir),
         save=args.save, repair=bool(args.repair))
    sess, outcome = None, "not reached"
    try:
        boot = S.stage_disks(slot, disks)
        save = pathlib.Path(slot.dir) / "SIDE0.D64"
        # the specimen tree is read-only; `stage_writable` unlinks whatever
        # an earlier tenant of this slot left here and gives the copy back
        # the write bit the game needs (#472)
        S.stage_writable(args.save, save)
        if args.repair:
            # Before the boot.  Rewriting an image VICE has already attached
            # is a different kind of mistake, and this copy is not in the
            # drive yet.
            note(event="repaired", entries=close_splat(str(save)))
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            note(event="boot-failed")
            return 1
        note(event="booted", **probe(sess))
        if sess.wait_text("LOAD SAVED GAME", 240)[0] is None:
            note(event="no-party-menu")
            return 1
        sess.kbd.screenshot(str(out / f"{args.tag}-00-menu.png"))
        if not sess.select_row("LOAD SAVED GAME"):
            note(event="menu-miss")
            return 1
        sess.settle(4)
        if sess.wait_text("LOAD SAVED GAME: YES", 60)[0] is None:
            note(event="no-confirm")
            return 1
        sess.kbd.key("Return")          # YES is already the white one
        note(event="yes")
        seen, text = watch(sess, note, args.wait)
        sess.kbd.screenshot(str(out / f"{args.tag}-01-{seen}.png"))
        (out / f"{args.tag}-01-{seen}.txt").write_text(text + "\n")
        p = probe(sess)
        note(event="outcome", screen=seen, **p)
        result = p.get("03F1_result")
        outcome = "loaded" if result == 0 and seen != "refused" else "failed"
        note(event="verdict", outcome=outcome, result=result,
             meaning=("the drive opened the file" if result == 0 else
                      "60, WRITE FILE OPEN" if result == 60 else
                      f"drive error {result}"))
        if args.serve:
            S.serve(sess)
        return 0 if outcome == "loaded" else 1
    finally:
        note(event="done", outcome=outcome)
        if sess is not None and not args.serve:
            sess.close()
        if not args.serve:
            slot.teardown()
        log.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", required=True, help="the save disk to load")
    ap.add_argument("--disks", default="", help="where the POOL<n>.D64 sides are")
    ap.add_argument("--slot", type=int, default=None)
    ap.add_argument("--repair", action="store_true",
                    help="close any unclosed entry in the staged copy first")
    ap.add_argument("--wait", type=float, default=120.0,
                    help="seconds to let the load say something")
    ap.add_argument("--tag", default="load", help="prefix for this run's files")
    ap.add_argument("--serve", action="store_true",
                    help="hand the session over on the command port at the end")
    ap.add_argument("--out", default="work/issue298/splatload")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
