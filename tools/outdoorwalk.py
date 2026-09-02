#!/usr/bin/env python3
"""Walk a party on the C64 travel grid, reading the square out of memory.

`tools/savecheck.py` proves a converted save loads and reads the party off the
screen.  It cannot prove an **outdoor** party took a step, and the reason is
the status line itself: indoors it reads `E 16:48 5,2` and outdoors it reads
`OUTDOORS 22:02 7,28`, with the word where the facing letter goes.  So a driver
that watches the status line to decide whether a move happened has, outdoors:

* no facing to turn from -- `Session.walk_one` re-sends a move until the status
  line changes, and a *turn* never changes it, so a single `K` is sent four
  times and the party comes back round to where it started;
* a facing it reads wrongly anyway -- `tools/session.py`'s `RE_STATUS` matches
  the final `S` of `OUTDOORS`, so every outdoor status reports the party facing
  south, filed as its own issue;
* a memory fallback pointed at `$49C0`-`$49C2`, which outdoors is the frozen
  square the party left the grid on rather than where it is standing.

What this does instead is read `$49C3`/`$49C4` -- the live travel square,
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
TRAVEL_X = 0x49C3


def travel_square(sess) -> tuple[int, int]:
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
            if not sess.select_bar("MOVE", timeout=10):
                print(f"  {move}: the MOVE command could not be selected")
                sess.leave_move(2)
                continue
            time.sleep(0.6)
            if args.shots:
                sess.kbd.screenshot(str(out / f"{args.tag}-{i}{move}-menu.png"))
            # One press, not `walk_one`'s four: a turn is invisible to the
            # status line, so re-sending it would spin the party in a circle.
            sess.kbd.key(move.lower(), 0.15, 0.30)
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
            sess.leave_move()
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
    # written back into the tool meant to prevent it. `8` and `4` are the two
    # driven on 2026-09-02, each moving the party a square.
    p.add_argument("--moves", default="8484",
                   help="the compass digits 1-8, not the dungeon's I J K M; "
                        "Return leaves the bar")
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
