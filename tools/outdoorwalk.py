#!/usr/bin/env python3
"""Walk a party on the C64 travel grid, reading the square out of memory.

The status line has two shapes: indoors it reads `E 16:48 5,2` and outdoors it
reads `OUTDOORS 22:02 7,28`, with the word where the facing letter goes.  A
driver that watches it to decide whether a move happened therefore has, on the
travel grid, no facing to turn from, and a step it will see late -- the line
lags `$49C3`/`$49C4` by about a second.

This tool was written when `tools/session.py` knew none of that: it pressed the
dungeon's `I J K M` out here, read the facing out of the middle of the word
`OUTDOORS`, and fell back to `$49C0`-`$49C2`, which outdoors is the frozen
square the party left the grid on.  All three are fixed in `Session` now
(`#189 (The emulator driver cannot move a party on the travel grid, and reads
its facing out of the word OUTDOORS)`), so `savecheck --walk` can walk an
outdoor party too.  What is left here is the screenshot-per-press sweep, which
is the thing to reach for when the question is *which* digit went where.

It reads `$49C3`/`$49C4` -- the live travel square,
`#47 (Decode the travel grid's cache entries, so the wilderness can be
retargeted too)` and `#59 (Map the DOS saved game, not just the character
record)` -- through the binary monitor, before and after every key.  A turn
then shows as "the square did not move, and it was not meant to", and a step
shows as the square moving, which is the thing worth proving:

    tools/outdoorwalk.py --disk work/p50-outdoor/OUTC.D64 --slot 2 --moves 8484

Written for `#50 (Lift the wilderness refusal from the DOS save converter)`,
whose end-to-end proof is "convert a wilderness DOS save, load it, and walk".

Nothing is written to the player's disks: `Session.attach` refuses a path
outside the slot's own directory, and `stage_disks` copies the sides there
first.  The pool owns the emulator -- claim, launch, tear down.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import session as S  # noqa: E402

from automap.paths import find_disks  # noqa: E402

#: Where the player keeps the C64 game disks.  Read only.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: The live overland square.  `$49C0`-`$49C2` is the dungeon one and goes
#: stale out here, which is the whole reason this tool reads memory at all.
#: `Session.square` now reads whichever pair is live, so this is kept only as
#: the name the address was documented under.
TRAVEL_X = S.TRAVEL_XY


def travel_square(sess) -> tuple[int, int]:
    """The travel square, straight out of `$49C3`/`$49C4`.

    Not `Session.square`, which asks `$49E6` first: this tool is only ever run
    outdoors, and the extra read is one more monitor stop per poll.
    """
    with sess.mon(5) as mon:
        x, y = mon.read(TRAVEL_X, 2)
    return x, y


def run(args) -> int:
    out = pathlib.Path(args.out or ROOT / "work" / "outdoorwalk")
    out.mkdir(parents=True, exist_ok=True)
    slot = S.claim_slot(args.slot, f"outdoorwalk/{pathlib.Path(args.disk).name}")
    print(f"Slot {slot.n} display {slot.display}")
    sess = None
    trail: list[dict] = []
    try:
        boot = S.stage_disks(slot, pathlib.Path(args.disks))
        shutil.copy(args.disk, pathlib.Path(slot.dir) / "SIDE0.D64")
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("Boot failed")
        if not sess.load_save():
            raise RuntimeError("The game did not accept the disk")
        # `Session.begin_adventuring` reports a failure when the arrival plays
        # a scene, so the arrival is driven here instead -- the same
        # work-around `tools/savecheck.py` uses.
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING could not be selected")
        if not sess.wait_text("MOVE", timeout=args.arrive):
            raise RuntimeError("No world bar after BEGIN ADVENTURING")
        sess.settle(3)

        here = travel_square(sess)
        print(f"Arrived on the travel grid at {here[0]},{here[1]}")
        sess.kbd.screenshot(str(out / f"{args.tag}-arrived.png"))

        for i, move in enumerate(args.moves):
            before = travel_square(sess)
            # `Session.outdoor_key`, not `select_bar("MOVE")`: a walked exit
            # on to the grid lands with `1-8, RETURN OR BUTTON` already up, so
            # asking for MOVE finds no such word and spins to its timeout.
            # One press, not `walk_one`'s four: a turn is invisible to the
            # status line, so re-sending it would spin the party in a circle.
            if args.shots:
                sess.kbd.screenshot(str(out / f"{args.tag}-{i}{move}-menu.png"))
            if not sess.outdoor_key(move):
                print(f"  {move}: no direction prompt to press it at")
                continue
            if args.shots:
                time.sleep(1.5)
                sess.kbd.screenshot(
                    str(out / f"{args.tag}-{i}{move}-pressed.png"))
            # Polled, not slept.  An overland step is hours of game time and
            # can go to the disk, so a fixed wait measures this machine rather
            # than the game; the square is read until it moves or the patience
            # runs out.
            deadline = time.time() + args.patience
            after = before
            while time.time() < deadline:
                after = travel_square(sess)
                if after != before:
                    break
                time.sleep(0.5)
            sess.leave_outdoor_move()
            moved = after != before
            trail.append({"move": move, "before": list(before),
                          "after": list(after), "moved": moved})
            print(f"  {move}: {before[0]},{before[1]} -> {after[0]},{after[1]}"
                  f"{'  MOVED' if moved else ''}")
            sess.kbd.screenshot(str(
                out / f"{args.tag}-{i}{move}-"
                      f"{'moved' if moved else 'stuck'}.png"))
            if sess.in_combat():
                print("  A random encounter started; stopping here")
                sess.kbd.screenshot(str(out / f"{args.tag}-encounter.png"))
                break
    finally:
        for what, fn in (("session", sess.terminate if sess else None),
                         ("slot teardown", slot.teardown),
                         ("slot release", slot.release)):
            if fn is None:
                continue
            try:
                fn()
            except Exception as e:                 # noqa: BLE001
                print(f"  {what} failed: {e}")
    (out / f"{args.tag}.json").write_text(json.dumps(trail, indent=2))
    return 0 if any(step["moved"] for step in trail) else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", required=True, help="the save .d64 to boot")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's game disks are; read, never written")
    p.add_argument("--slot", type=int, default=None, help="the pool slot")
    # Compass digits, not `I J K M`. The travel grid's bar is
    # `1-8, RETURN OR BUTTON`, and a driver pressing the dungeon's letters out
    # here moves the party not at all while looking exactly like a save that
    # cannot walk -- which is what an hour of `#50 (Lift the wilderness refusal
    # from the DOS save converter)` was spent on. This default was that hour
    # written back into the tool meant to prevent it.
    #
    # The eight are the compass **clockwise from north**, not the numpad:
    # 1 N, 2 NE, 3 E, 4 SE, 5 S, 6 SW, 7 W, 8 NW, measured on 2026-09-02 by
    # writing `$49C3`/`$49C4`, pressing a digit and reading the square back.
    # So this default is north-west and south-east twice over, which is why it
    # moved the party a square each time without saying which way.
    p.add_argument("--moves", default="8484",
                   help="The compass digits 1-8 clockwise from north, not the "
                        "dungeon's I J K M; Return leaves the bar")
    p.add_argument("--tag", default="outdoorwalk",
                   help="prefix for the screenshots")
    p.add_argument("--out", default=None, help="where the run's output goes")
    p.add_argument("--arrive", type=float, default=240.0,
                   help="seconds to wait for the world bar")
    p.add_argument("--shots", action="store_true",
                   help="Photograph the move menu and the frame after the key")
    p.add_argument("--patience", type=float, default=25.0,
                   help="seconds to watch the travel square after each key")
    args = p.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
