#!/usr/bin/env python3
"""Watch `ANIMATE00`'s picture buffer in a driven Curse session.

`#283 (What Curse keeps in the area map region at +$1800 is unread, and a
conversion writes zeroes there)`: the region is the picture buffer at
`$6300`-`$66FF` that `ANIMATE00` decodes the view-window picture into, and
`tools/cursepic.py` proves that on the bytes.  What the bytes cannot prove is
the claim that matters to a conversion -- that **the engine never reads what
a save put there**, so writing zeroes loses nothing.  This run takes that
measurement in the running game:

1. load a save through the game's own front end (`tools/curseload.py`);
2. read the buffer the load left, then overwrite it with `$A5` so any copy
   or read of it would show;
3. arm two counting checkpoints on `$6300`-`$66FF`, one for loads and one
   for stores, and enter the world, turn, step and draw the area map --
   both counts should stay at zero;
4. put the highlight on `ENCAMP`, arm a one-shot **stopping** store
   checkpoint, press Return, and catch the first write: its PC, the overlay
   that is running, and the load count at that instant -- zero means nothing
   read the region before the engine began overwriting it;
5. or, with `--no-stop`, take `ENCAMP` through the ordinary driver and
   sample the buffer for a few seconds, matching each sample to a `PIC1D`
   frame -- the animation cycling through frames 0 to 3 is the frame model
   confirmed in the machine.  A run does one or the other, because a
   checkpoint stop leaves VICE's monitor answering nothing afterwards;
6. read `$6700`-`$6740` at each step, because the decoder's colour bytes run
   65 bytes into the roster page and the specimens hold an intact roster.

    tools/cursepicrun.py --save work/issue192/CURSEH.D64 --out work/issue283/run1
    tools/cursepicrun.py --save ... --out work/issue283/run4 --no-stop

Writes `run.jsonl`, screenshots and the sampled buffers into `--out`.  Nothing
outside the slot's own directory is written, and the player's disks are read
only.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))

from tools import curseload, cursepic, curserun, gamedisks  # noqa: E402
from tools import session as por  # noqa: E402

BUFFER, BUFFER_END = 0x6300, 0x66FF
ROSTER = 0x6700
SPILL = 0x41
OVERLAY = 0x0800
#: The four overlays `LINKER` runs at `$0800`, told apart by their first bytes.
OVERLAYS = ("DUNGEON", "CAMP", "GEN", "COMBAT")


def aim_bar(sess, label: str, row: int = 24, timeout: float = 30.0) -> bool:
    """`Session.select_bar` without the Return: leave the highlight on `label`.

    The Return has to go *after* the checkpoint is armed, and arming it needs
    the monitor open, which `select_bar`'s own screen reads would fight over.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.3)
            continue
        col = s.row(row).find(label.upper())
        span = por.span_in(s, row)
        if col < 0 or span is None:
            sess.handle_prompt(s)
            time.sleep(0.3)
            continue
        if span[0] == col:
            return True
        sess.kbd.key("Right" if span[0] < col else "Left")
    return False


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "run.jsonl").open("a")

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw) + "\n")
        log.flush()
        print(json.dumps(kw), flush=True)

    def shot(tag: str) -> None:
        sess.kbd.screenshot(str(out / f"{tag}.png"))

    disks = args.disks or str(gamedisks.find("curse-of-the-azure-bonds") or "")
    pic = cursepic.Picture(cursepic.read_file(args.pic, disks))
    heads = {n: cursepic.read_file(n, disks)[:16] for n in OVERLAYS}

    def overlay(m) -> str:
        head = m.read(OVERLAY, 16)
        return next((n for n, h in heads.items() if h == head), "?")

    def sample(m, tag: str) -> dict:
        buf = m.read(BUFFER, 0x400)
        spill = m.read(ROSTER, SPILL)
        (out / f"{tag}.bin").write_bytes(buf + spill)
        best = min(pic.compare(buf), key=lambda kd: kd[1])
        return {"buffer_nonzero": sum(1 for b in buf if b),
                "a5": sum(1 for b in buf if b == 0xA5),
                "frame": best[0] if best[1] == 0 else None,
                "nearest": list(best),
                "roster_head": spill[:16].hex(),
                "roster_spill_nonzero": sum(1 for b in spill if b)}

    slot = por.claim_slot(args.pool, note=os.environ.get("POR_AGENT", "i283"))
    note(event="slot", n=slot.n, monitor=slot.port, display=slot.display,
         dir=str(slot.dir))
    disk = curserun.stage(slot, disks, args.save)
    save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
    os.chmod(save_disk, 0o644)
    sess = curserun.CurseSession(disk, slot=slot)
    sess.save_disk = save_disk
    cps: dict[str, int] = {}
    try:
        if not sess.boot():
            note(event="boot-failed")
            return 1
        outcome = curseload.load_saved_game(sess, note=note, shot=shot)
        if outcome == "failed":
            outcome = curseload.load_saved_game(sess, note=note, shot=shot,
                                                retry=True, tag="reload")
        if outcome != "loaded":
            note(event="load-failed", outcome=outcome)
            return 1
        with sess.mon(5) as m:
            note(event="after-load", **sample(m, "01-after-load"))
            if args.poke:
                m.write(BUFFER, bytes([0xA5]) * 0x400)
                note(event="poked", value="A5", count=0x400)
            cps["load"] = m.checkpoint_set(BUFFER, BUFFER_END, load=True,
                                           stop=False)
            cps["store"] = m.checkpoint_set(BUFFER, BUFFER_END, store=True,
                                            stop=False)
            note(event="armed", **cps)

        def hits(tag: str) -> None:
            with sess.mon(5) as m:
                note(event="hits", at=tag,
                     loads=curseload.checkpoint_hits(m, cps["load"]),
                     stores=curseload.checkpoint_hits(m, cps["store"]),
                     overlay=overlay(m), **sample(m, tag))

        if not sess.begin_adventuring():
            note(event="no-world")
            shot("02-no-world")
            return 1
        shot("02-world")
        hits("02-world")
        for move in args.moves:
            ok = sess.walk_one(move)
            note(event="move", key=move, moved=ok, status=str(sess.status()))
            hits(f"03-after-{move}")
        if args.area:
            if sess.select_bar("AREA"):
                sess.settle(3)
                shot("04-area")
                hits("04-area")
                sess.kbd.key("Return")
                sess.settle(2)

        def take(m, i: int) -> None:
            note(event="sample", i=i, overlay=overlay(m),
                 loads=curseload.checkpoint_hits(m, cps["load"]),
                 stores=curseload.checkpoint_hits(m, cps["store"]),
                 colours=m.read(0xD021, 3).hex(" "),
                 **sample(m, f"07-sample-{i:02d}"))

        if not args.stop:
            # The frame series.  `ENCAMP` through the ordinary driver, then
            # one fresh connection per sample, which is how every screen
            # read in `tools/session.py` works and never wedges.
            if not sess.select_bar("ENCAMP"):
                note(event="no-encamp-bar")
                shot("05-no-encamp")
                return 1
            sess.settle(2)
            shot("06-encamp")
            for i in range(args.samples):
                time.sleep(args.interval)
                try:
                    with sess.mon(5) as m:
                        take(m, i)
                except (por.MonitorError, OSError) as exc:
                    note(event="sample-failed", i=i, error=str(exc))
            note(event="done")
            return 0

        # ENCAMP, with the first store caught in the act.
        #
        # **A checkpoint stop ends the monitor for the rest of the run.**
        # After VICE has stopped on a checkpoint and been resumed, every
        # later read times out -- on a fresh connection (runs 1 and 2 of
        # this tool, `automap/vice.py`'s `Monitor.resume` note) and on the
        # connection that caught the stop (run 3), while the game itself
        # runs on and the screenshot shows the camp scene drawn.  So this
        # mode ends with the first store and its screenshot; the frame
        # series is `--no-stop`'s job, in a run of its own.
        if not aim_bar(sess, "ENCAMP"):
            note(event="no-encamp-bar")
            shot("05-no-encamp")
            return 1
        with sess.mon(60) as m:
            tmp = m.checkpoint_set(BUFFER, BUFFER_END, store=True, stop=True,
                                   temporary=True)
            loads_before = curseload.checkpoint_hits(m, cps["load"])
            m.resume()
            sess.kbd.key("Return")
            pc = m.wait_stopped(45)
            if pc is None:
                note(event="no-first-store", loads_before=loads_before)
            else:
                regs = m.registers()
                note(event="first-store", pc=f"${pc:04X}",
                     overlay=overlay(m),
                     loads_at_stop=curseload.checkpoint_hits(m, cps["load"]),
                     stores_at_stop=curseload.checkpoint_hits(m, cps["store"]),
                     registers={f"{k}": v for k, v in regs.items()},
                     code=m.read(pc, 8).hex(" "),
                     zp_fb_fe=m.read(0xFB, 4).hex(" "),
                     **sample(m, "05-first-store"))
                try:
                    m.checkpoint_delete(tmp)
                except Exception:
                    pass        # a temporary checkpoint deletes itself
                note(event="checkpoints-left", numbers=m.checkpoint_list())
                m.resume()
            time.sleep(2.0)
            shot("06-encamp")
            try:
                take(m, 0)
            except (por.MonitorError, OSError) as exc:
                note(event="sample-failed", i=0, error=str(exc))
        note(event="done")
        return 0
    finally:
        try:
            with sess.mon(5) as m:
                m.checkpoints_clear()
        except Exception:
            pass
        sess.close()
        slot.teardown()
        log.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", required=True, help="the save disk to load")
    ap.add_argument("--disks", default="", help="where the Curse sides are")
    ap.add_argument("--out", default="work/issue283/run", help="log directory")
    ap.add_argument("--pool", type=int, default=None, help="a specific slot")
    ap.add_argument("--pic", default="PIC1D", help="the picture ENCAMP draws")
    ap.add_argument("--moves", default="KI",
                    help="dungeon keys to send before ENCAMP (default K I: "
                         "turn right, step)")
    ap.add_argument("--area", action="store_true", help="draw AREA as well")
    ap.add_argument("--no-poke", dest="poke", action="store_false",
                    help="leave the loaded buffer as the save left it")
    ap.add_argument("--no-stop", dest="stop", action="store_false",
                    help="do not catch the first store; take the frame "
                         "series instead (a checkpoint stop ends the "
                         "monitor for the rest of the run)")
    ap.add_argument("--samples", type=int, default=24)
    ap.add_argument("--interval", type=float, default=0.25)
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
