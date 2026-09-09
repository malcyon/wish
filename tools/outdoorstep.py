#!/usr/bin/env python3
"""Take one compass step on Pool of Radiance's travel grid, and say what happened.

`tools/savecheck.py --walk` answers a step with `moved=True` or `moved=False`,
and a `False` out here has meant three different things at once: the square
refused the party, the driver never found the movement prompt, or the key went
somewhere the game was not reading.  `#382 (An outdoor Pool of Radiance party's
compass step is refused, and the retry cannot find the movement prompt
afterwards)` is what that ambiguity cost -- eight directions all reported as
refused, with no reading that says which of the three it was.

So this reads, for every stage of one step:

* row 24 verbatim, before `MOVE`, after `MOVE` and after the digit;
* the live travel square `$49C3`/`$49C4` and the frozen dungeon triple at
  `$49C0`, polled while the game thinks;
* the game clock, because a blocked overland step still costs a minute and a
  step the driver never sent costs nothing;
* a screenshot at each stage, named for the direction and the stage.

Both routes for the digit are tried in turn -- XTEST first, then the KERNAL
buffer -- because a title that reads only one of them looks exactly like a
party hemmed in (`#192`, `#360`).

    tools/outdoorstep.py --disk work/376/PORSAVEB-fixed.D64 --moves 7315 \\
        --tag amiga --resave work/382/amiga-resaved.D64

Nothing is written to the player's disks: the save is copied into the pool
slot's own directory and the engine's resave is copied back out of it.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from tools import savecheck as SC  # noqa: E402
from tools import session as S  # noqa: E402

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: The clock's six digit bytes -- sub-minute, minute units, minute tens, hour,
#: day, month (`docs/141-dos-savegame.md`).  Read beside the square because a
#: *blocked* overland step still advances it and a step the driver never sent
#: does not, which is the one reading that tells a wall from a driver fault
#: without a screenshot (`#382`).
CLOCK_AT = 0x49C6
CLOCK_BYTES = 6


#: `SC.Log` -- it keeps a second run's log rather than truncating it, and a
#: `say` a dead console cannot take down with it (`#442`).  Nothing here adds
#: anything beyond that, so the class is just the name this file already uses.
Log = SC.Log


def reading(sess) -> dict:
    """Everything the machine will say about where the party is standing."""
    out: dict = {}
    try:
        with sess.mon(5) as m:
            out["travel"] = list(m.read(S.TRAVEL_XY, 2))
            out["dungeon"] = list(m.read(S.DUNGEON_XY, 3))
            out["indoors_byte"] = m.read(S.INDOORS_AT, 1)[0]
            out["clock"] = list(m.read(CLOCK_AT, CLOCK_BYTES))
            out["area"] = list(m.read(0x49F2, 2))
    except Exception as exc:                     # noqa: BLE001 -- reported
        out["error"] = repr(exc)
    at = sess.status()
    out["status"] = None if at is None else at.where()
    return out


def rows(sess, first: int = 20, last: int = 24) -> list[str]:
    s = sess.screen()
    if s is None:
        return ["(bitmap or no screen)"]
    return [f"{r:2d}|{s.row(r)}|" for r in range(first, last + 1)]


def show(sess, log: Log, label: str) -> None:
    log.say(f"    {label}:")
    for line in rows(sess):
        log.say(f"      {line}")


def reach_prompt(sess, log: Log, timeout: float = 40.0,
                 boat: str = "STAY") -> list[str]:
    """Get row 24 to the `1-8` prompt, answering whatever stands in the way.

    **A boat landing is in the way, and that is what `#382 (An outdoor Pool of
    Radiance party's compass step is refused, and the retry cannot find the
    movement prompt afterwards)` turned out to be.**  Selecting `MOVE` on the
    square the Amiga party sailed to puts up `TAKE BOAT STAY` rather than the
    direction prompt, so a driver that only knows `MOVE` and `1-8` waits out
    its timeout on a game that is asking it a question.  `STAY` declines the
    passage and leaves the party where it is, which is the answer a run
    measuring an overland step wants; `TAKE` would sail it back to New Phlan.
    """
    seen: list[str] = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.5)
            continue
        row = s.row(24)
        if row.strip() and (not seen or seen[-1] != row.strip()):
            seen.append(row.strip())
        if S.OUTDOOR_PROMPT in row:
            return seen
        if sess.handle_prompt(s):
            continue
        if "TAKE" in row and "STAY" in row:
            log.say(f"    the square offers a boat: |{row.strip()}| -- {boat}")
            sess.select_bar(boat, timeout=10)
        elif "PRESS" in row:
            sess.kbd.key("Return")
        elif "YES" in row and "NO" in row:
            sess.select_bar("NO", timeout=8)
        elif S.word_column(row, "MOVE") >= 0 and "ENCAMP" in row:
            sess.select_bar("MOVE", timeout=10)
        time.sleep(1.0)
    return seen


def step(sess, log: Log, move: str, tag: str, patience: float = 20.0,
         boat: str = "STAY") -> dict:
    """One digit, with every stage of it recorded."""
    log.say(f"--- {move} ---")
    before = reading(sess)
    log.say(f"    before: {before}")
    show(sess, log, "row 20-24 before")
    sess.kbd.screenshot(str(log.dir / f"{tag}-{move}-before.png"))

    seen = reach_prompt(sess, log, boat=boat)
    took_move = " -> ".join(seen) if seen else "nothing on row 24"
    log.say(f"    row 24 went: {took_move}")
    show(sess, log, "row 20-24 after MOVE")
    sess.kbd.screenshot(str(log.dir / f"{tag}-{move}-prompt.png"))

    routes = []
    after = before
    for route in ("xtest", "kernal"):
        if route == "xtest":
            sess.kbd.key(move, 0.15, 0.30)
        else:
            sess.press_kernal(ord(move))
        deadline = time.time() + patience
        moved = False
        while time.time() < deadline:
            now = reading(sess)
            if now.get("travel") != before.get("travel"):
                moved = True
                after = now
                break
            time.sleep(0.7)
        after = after if moved else reading(sess)
        routes.append({"route": route, "moved": moved, "after": after})
        log.say(f"    {route}: moved={moved} {after}")
        show(sess, log, f"row 20-24 after {route}")
        sess.kbd.screenshot(str(log.dir / f"{tag}-{move}-{route}.png"))
        if moved:
            break

    left = sess.leave_outdoor_move()
    log.say(f"    leave_outdoor_move -> {left}")
    routed = SC.walk_step_routed(sess, log, "NO")
    log.say(f"    what the step put up afterwards: {routed}")
    show(sess, log, "row 20-24 settled")
    rec = {"move": move, "before": before, "took_move": took_move,
           "routes": routes, "left": left, "routed": routed,
           "settled": reading(sess)}
    log.emit("step", **rec)
    return rec


def run(args, log: Log) -> int:
    SC.catch_signals()
    slot = S.claim_slot(args.slot, f"outdoorstep/{pathlib.Path(args.disk).name}")
    log.say(f"slot {slot.n} display {slot.display}")
    sess = None
    rc = 0
    try:
        boot = S.stage_disks(slot, pathlib.Path(args.disks))
        S.stage_writable(args.disk, pathlib.Path(slot.dir) / "SIDE0.D64")
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("the game did not list the save")
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING could not be selected")
        arrived = SC.answer_bars(sess, log, "NO", seconds=args.arrive)
        log.emit("arrival", outcome=arrived)
        if arrived != "world":
            raise RuntimeError(f"no world bar {args.arrive}s after BEGIN")
        sess.settle(3)
        at = reading(sess)
        log.emit("arrived", **at)
        log.say(f"arrived: {at}")
        show(sess, log, "row 20-24 on arrival")
        sess.kbd.screenshot(str(log.dir / f"{args.tag}-arrived.png"))

        moved_any = False
        for move in args.moves:
            rec = step(sess, log, move, args.tag, args.patience, args.boat)
            if any(r["moved"] for r in rec["routes"]):
                moved_any = True
                if args.stop_on_move:
                    break
        log.emit("summary", moved_any=moved_any)
        log.say(f"any direction moved the party: {moved_any}")

        if args.resave:
            ok = sess.save_game()
            log.emit("resave", ok=ok, to=args.resave)
            log.say(f"the game's own ENCAMP > SAVE wrote back: {ok}")
            if ok:
                pathlib.Path(args.resave).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(sess.save_disk, args.resave)
                log.say(f"the engine-written disk is at {args.resave}")
            sess.settle(3)
        rc = 0 if moved_any else 1
    except Exception as exc:                      # noqa: BLE001 -- reported
        log.emit("failed", error=repr(exc))
        log.say(f"FAILED: {exc!r}")
        if sess is not None:
            sess.kbd.screenshot(str(log.dir / f"{args.tag}-failed.png"))
        rc = 2
    finally:
        if sess is not None:
            sess.terminate()
        slot.release()
    return rc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", required=True, help="the save .d64 to boot")
    p.add_argument("--disks", default=str(DISKS), help="the game disks")
    p.add_argument("--slot", type=int, default=None, help="the pool slot")
    p.add_argument("--tag", default=None, help="prefix for the screenshots")
    p.add_argument("--out", default=None, help="where the .jsonl goes")
    p.add_argument("--moves", default="7", help="compass digits, one per step")
    p.add_argument("--patience", type=float, default=20.0,
                   help="seconds to watch the square after one key")
    p.add_argument("--boat", default="STAY",
                   help="what to answer a TAKE BOAT / STAY bar; STAY declines "
                        "the passage and leaves the party on the landing")
    p.add_argument("--stop-on-move", action="store_true",
                   help="stop at the first direction that moves the party")
    p.add_argument("--resave", default=None,
                   help="copy the engine's own ENCAMP > SAVE disk here")
    p.add_argument("--arrive", type=float, default=240.0,
                   help="seconds to wait for the world bar")
    args = p.parse_args(argv)
    stem = pathlib.Path(args.disk).stem
    args.tag = args.tag or stem
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "work" / "382" / f"{stem}.jsonl")
    log = Log(out)
    try:
        return run(args, log)
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
